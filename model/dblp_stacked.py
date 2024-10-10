# -*- coding: utf-8 -*-
"""

@author: Radin Hamidi Rad
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from keras.callbacks import EarlyStopping
from datetime import datetime
from keras.callbacks import Callback
from keras.layers import Lambda
from keras.losses import mse, binary_crossentropy, mae, kld, categorical_crossentropy
import time
import pickle as pkl
from keras import regularizers
import cmn.utils
from keras.layers import Input, Dense, Concatenate, Dropout
from keras.models import Model
from contextlib import redirect_stdout
import cmn.utils
from cmn.utils import *
import dal.load_dblp_data as dblp
import eval.evaluator as dblp_eval
import csv
import eval.ranking as rk
import ml_metrics as metrics

os.environ["CUDA_VISIBLE_DEVICES"] = "1"
# from keras import backend as K
# import tensorflow as tf
# with tf.dvice('/gpu:1'):
#     config = tf.ConfigProto(intra_op_parallelism_threads=4, inter_op_parallelism_threads=4, allow_soft_placement=True, device_count={'CPU': 1, 'GPU': 1})
#     session =tf.Session(config=config)
#     K.set_session(session)

class watcher(Callback):
    def on_train_begin(self, logs={}):
        self.intervals = []
        self.ndcg = []
        self.map = []
        self.sum = 0

    def on_epoch_begin(self, epoch, logs={}):
        self.epoch_time_start = time.time()

    def on_epoch_end(self, epoch, logs={}):
        self.sum += time.time() - self.epoch_time_start
        if epoch < 30:
            recorder_step = 5
        elif epoch < 300:
            recorder_step = 50
        else:
            recorder_step = 150
        if epoch%recorder_step == 0:
            self.intervals.append(self.sum)
            self.sum = 0
            y_true = y_test
            y_pred = autoencoder.predict([x_test_skill, x_test_user])
            pred_index, true_index = dblp_eval.find_indices(y_pred, y_true)
            self.ndcg.append(ndcg_metric(pred_index, true_index))
            self.map.append(map_metric(pred_index, true_index))


watchDog = watcher()


def ndcg_metric(pred_index, true_index):
    return np.mean([rk.ndcg_at(pred_index, true_index, k=5), rk.ndcg_at(pred_index, true_index, k=10)])


def map_metric(pred_index, true_index):
    return np.mean([metrics.mapk(true_index, pred_index, k=5), metrics.mapk(true_index, pred_index, k=10)])

# fix random seed for reproducibility
seed = 7
np.random.seed(seed)
es = EarlyStopping(monitor='val_loss', mode='min', verbose=1, patience=35, min_delta=0.0001)

logdir = "logs/scalars/" + datetime.now().strftime("%Y%m%d-%H%M%S")
tensorboard_callback = keras.callbacks.TensorBoard(log_dir=logdir)

#running settings
dataset_name = 'DBLP'
method_name = 'stacked'

#eval settings
k_fold = 10
k_max = 100
evaluation_k_set = np.arange(1, k_max+1, 1)

#nn settings
epochs = 2000
back_propagation_batch_size = 32
min_skill_size = 0
min_member_size = 0
latent_dim = 2
latent_dim_merged = 2
beta = 30


print('Skill embedding options')
t2v_model_skill = Team2Vec()
t2v_model_skill = load_T2V_model(t2v_model_skill)
embedding_dim_skill = t2v_model_skill.model.vector_size

print('User embedding options')
t2v_model_user = Team2Vec()
t2v_model_user = load_T2V_model(t2v_model_user)
embedding_dim_user = t2v_model_user.model.vector_size

merge_dense = int((embedding_dim_skill + embedding_dim_user)/2)

if dblp.ae_data_exist(file_path='../dataset/ae_t2v_dimSkill{}_dimUser{}_tFull_dataset_V2.2.pkl'.format(embedding_dim_skill, embedding_dim_user)):
    dataset = dblp.load_ae_dataset(file_path='../dataset/ae_t2v_dimSkill{}_dimUser{}_tFull_dataset_V2.2.pkl'.format(embedding_dim_skill, embedding_dim_user))
else:
    if not dblp.ae_data_exist(file_path='../dataset/ae_dataset_V2.2.pkl'):
        dblp.extract_data(filter_journals=True, skill_size_filter=min_skill_size, member_size_filter=min_member_size)
    if not dblp.preprocessed_dataset_exist(
            file_path='../dataset/dblp_preprocessed_dataset_V2.2.pkl') or not dblp.train_test_indices_exist(
            file_path='../dataset/Train_Test_indices_V2.2.pkl'):
        dblp.dataset_preprocessing(dblp.load_ae_dataset(file_path='../dataset/ae_dataset_V2.2.pkl'),
                                   indices_dict_file_path='../dataset/Train_Test_indices_V2.2.pkl',
                                   preprocessed_dataset_file_path='../dataset/dblp_preprocessed_dataset_V2.2.pkl',
                                   seed=seed, kfolds=k_fold)
    preprocessed_dataset = dblp.load_preprocessed_dataset(file_path='../dataset/dblp_preprocessed_dataset_V2.2.pkl')

    dblp.nn_t2v_dataset_generator({'skill':t2v_model_skill, 'user':t2v_model_user}, preprocessed_dataset,
                                  output_file_path='../dataset/ae_t2v_dimSkill{}_dimUser{}_tFull_dataset_V2.2.pkl'
                                  .format(embedding_dim_skill, embedding_dim_user), mode='full')
    del preprocessed_dataset
    dataset = dblp.load_ae_dataset(file_path='../dataset/ae_t2v_dimSkill{}_dimUser{}_tFull_dataset_V2.2.pkl'.format(embedding_dim_skill, embedding_dim_user))



# reparameterization trick
# instead of sampling from Q(z|X), sample epsilon = N(0,I)
# z = z_mean + sqrt(var) * epsilon
def sampling(args):
    """Reparameterization trick by sampling from an isotropic unit Gaussian.

    # Arguments
        args (tensor): mean and log of variance of Q(z|X)

    # Returns
        z (tensor): sampled latent vector
    """

    z_mean, z_log_var = args
    batch = K.shape(z_mean)[0]
    dim = K.int_shape(z_mean)[1]
    # by default, random_normal has mean = 0 and std = 1.0
    epsilon = K.random_normal(shape=(batch, dim))
    return z_mean + K.exp(0.5 * z_log_var) * epsilon

# k_fold Cross Validation
cvscores = []

# Defining evaluation scores holders for train data
r_at_k_all_train = dblp_eval.init_eval_holder(evaluation_k_set)  # all r@k of instances in one fold and one k_evaluation_set
r_at_k_overall_train = dblp_eval.init_eval_holder(evaluation_k_set)  # overall r@k of instances in one fold and one k_evaluation_set

# Defining evaluation scores holders for test data
r_at_k_all = dblp_eval.init_eval_holder(evaluation_k_set)  # all r@k of instances in one fold and one k_evaluation_set
r_at_k_overall = dblp_eval.init_eval_holder(evaluation_k_set)  # overall r@k of instances in one fold and one k_evaluation_set
mapk = dblp_eval.init_eval_holder(evaluation_k_set)  # all r@k of instances in one fold and one k_evaluation_set
ndcg = dblp_eval.init_eval_holder(evaluation_k_set)  # all r@k of instances in one fold and one k_evaluation_set
mrr = dblp_eval.init_eval_holder(evaluation_k_set)  # all r@k of instances in one fold and one k_evaluation_set

lambda_val = 0.001  # Weight decay , refer : https://stackoverflow.com/questions/44495698/keras-difference-between-kernel-and-activity-regularizers

load_weights_from_file_q = input('Load weights from file? (y/n)')
more_train_q = input('Train more? (y/n)')

time_str = time.strftime("%Y_%m_%d-%H_%M_%S")
result_output_name = "../output/predictions/{}_output.csv".format(method_name)
with open(result_output_name, 'w') as file:
    writer = csv.writer(file)
    writer.writerow(
        ['Method Name', '# Total Folds', '# Fold Number', '# Predictions', '# Truth', 'Computation Time (ms)',
         'Prediction Indices', 'True Indices'])

train_test_indices = dblp.load_train_test_indices(file_path='../dataset/Train_Test_indices_V2.2.pkl')
for fold_counter in range(1, k_fold+1):
    x_train_skill, x_train_user, x_test_skill, x_test_user = dblp.get_fold_data(fold_counter, dataset, train_test_indices)

    # this is our input placeholder
    # input_img = Input(shape=(input_dim,))

    train_index = train_test_indices[fold_counter]['Train']
    test_index = train_test_indices[fold_counter]['Test']
    y_sparse_train = []
    y_sparse_test = []
    y_train = []
    y_test = []
    preprocessed_dataset = dblp.load_preprocessed_dataset(file_path='../dataset/dblp_preprocessed_dataset_V2.2.pkl')
    for sample in preprocessed_dataset:
        id = sample[0]
        if id in train_index:
            y_sparse_train.append(sample[2])
            y_train.append(sample[2].todense())
        elif id in test_index:
            y_sparse_test.append(sample[2])
            y_test.append(sample[2].todense())

    y_sparse_train = np.asarray(y_sparse_train).reshape(y_sparse_train.__len__(), -1)
    y_sparse_test = np.asarray(y_sparse_test).reshape(y_sparse_test.__len__(), -1)
    y_train = np.asarray(y_train).reshape(y_train.__len__(), -1)
    y_test = np.asarray(y_test).reshape(y_test.__len__(), -1)
    del preprocessed_dataset

    input_skill_dim = x_train_skill[0].shape[0]
    input_user_dim = x_train_user[0].shape[0]
    input_dim = input_skill_dim + input_user_dim
    output_dim = y_train[0].shape[0]
    print("Input/output Dimensions:  ", input_dim, output_dim)


   	#### Main model ####
   	# this is our input placeholder
    # network parameters
    intermediate_dim_encoder = input_dim
    intermediate_dim_decoder = output_dim

    # VAE model = encoder + decoder
    # build encoder model

    input_skill = Input(shape=(input_skill_dim,), name='encoder_input_skill')
    input_user = Input(shape=(input_user_dim,), name='encoder_input_user')
    # pre_z_skill = Dense(input_skill_dim, activation='relu')(input_skill)
    # pre_z_user = Dense(input_user_dim, activation='relu')(input_user)
    z_mean_skill = Dense(latent_dim, name='z_mean_skill', activation='relu')(input_skill)
    z_log_var_skill = Dense(latent_dim, name='z_log_var_skill', activation='relu')(input_skill)
    z_mean_user = Dense(latent_dim, name='z_mean_user', activation='relu')(input_user)
    z_log_var_user = Dense(latent_dim, name='z_log_var_user', activation='relu')(input_user)
    z_skill = Lambda(sampling, output_shape=(latent_dim,), name='z_skill')([z_mean_skill, z_log_var_skill])
    z_user = Lambda(sampling, output_shape=(latent_dim,), name='z_user')([z_mean_user, z_log_var_user])
    merged = Concatenate()([z_skill, z_user])
    mergeHidden = Dense(merge_dense, activation='relu')(merged)
    mergeHidden = Dropout(0.3)(mergeHidden)
    mergeHidden = Dense(merge_dense, activation='relu')(mergeHidden)
    mergeHidden = Dropout(0.3)(mergeHidden)
    z_mean = Dense(latent_dim_merged, name='z_mean', activation='relu')(mergeHidden)
    z_log_var = Dense(latent_dim_merged, name='z_log_var', activation='relu')(mergeHidden)
    z = Lambda(sampling, output_shape=(latent_dim_merged,), name='z')([z_mean, z_log_var])
    x = Dense(intermediate_dim_decoder, activation='relu')(z)
    outputs = Dense(output_dim, activation='sigmoid')(x)
    # use reparameterization trick to push the sampling out as input
    # note that "output_shape" isn't necessary with the TensorFlow backend
    # z = Lambda(sampling, output_shape=(latent_dim,), name='z')([z_mean, z_log_var])

    # instantiate encoder model
    # encoder = Model(inputs, [z_mean, z_log_var, z], name='encoder')
    # encoder.summary()
    # plot_model(encoder, to_file='vae_mlp_encoder.png', show_shapes=True)

    # build decoder model
    # latent_inputs = Input(shape=(latent_dim,), name='z_sampling')
    # x = Dense(intermediate_dim_decoder, activation='relu')(latent_inputs)
    # outputs = Dense(output_dim, activation='sigmoid')(x)

    # instantiate decoder model
    # decoder = Model(latent_inputs, outputs, name='decoder')
    # decoder.summary()
    # plot_model(decoder, to_file='vae_mlp_decoder.png', show_shapes=True)

    # instantiate VAE model
    # outputs = decoder(encoder(inputs)[2])
    # autoencoder = Model(inputs, outputs, name='vae_mlp')

    # models_main = (encoder, decoder)
    # mergeOut = Concatenate()([S_model.output, U_model.output])
    # mergeOut = Dense(output_dim, activation='relu')(mergeOut)
    # z_mean = Dense(latent_dim, name='z_mean')(mergeOut)
    # z_log_var = Dense(latent_dim, name='z_log_var')(mergeOut)
    # z = Lambda(sampling, output_shape=(latent_dim,), name='z')([z_mean, z_log_var])
    # encoder = Model([S_model.input, U_model.input], [z_mean, z_log_var, z])
    # latent_inputs = Input(shape=(latent_dim,), name='z_sampling')
    # x = Dense(intermediate_dim_decoder, activation='relu')(z)
    # outputs = Dense(output_dim, activation='sigmoid')(x)
    # decoder = Model(latent_inputs, outputs, name='decoder')
    # decoder.summary()
    # outputs = decoder(encoder([S_model.input, U_model.input])[2])
    autoencoder = Model([input_skill, input_user], outputs, name='vae_mlp')

    # autoencoder.get_layer('dense_7').set_weights(S_encoder.get_layer('dense_1').get_weights())
    # autoencoder.get_layer('dense_7').trainable = False

    # autoencoder.get_layer('z_mean_skill').set_weights(S_encoder.get_layer('S_z_mean').get_weights())
    # autoencoder.get_layer('z_mean_skill').trainable = False
    #
    # autoencoder.get_layer('z_log_var_skill').set_weights(S_encoder.get_layer('S_z_log_var').get_weights())
    # autoencoder.get_layer('z_log_var_skill').trainable = False

    # autoencoder.get_layer('dense_8').set_weights(U_encoder.get_layer('dense_4').get_weights())
    # autoencoder.get_layer('dense_8').trainable = False

    # autoencoder.get_layer('z_mean_user').set_weights(U_encoder.get_layer('U_z_mean').get_weights())
    # autoencoder.get_layer('z_mean_user').trainable = False
    #
    # autoencoder.get_layer('z_log_var_user').set_weights(U_encoder.get_layer('U_z_log_var').get_weights())
    # autoencoder.get_layer('z_log_var_user').trainable = False

    def vae_loss(y_true, y_pred):
        reconstruction_loss = mse(y_true, y_pred)

        reconstruction_loss *= output_dim
        kl_loss = 1 + z_log_var - K.square(z_mean) - K.exp(z_log_var)
        kl_loss = K.sum(kl_loss, axis=-1)
        kl_loss *= -0.5
        vae_loss = K.mean(reconstruction_loss + beta * kl_loss)
        return vae_loss

    autoencoder.compile(optimizer='adam', loss=vae_loss)
    autoencoder.summary()

    # break
    # w = rev_model.get_weights()[::-1]
    # w = [i.T for i in w]
    # v = autoencoder.get_weights()
    # v[0] = w[1]
    # # v[2] = w[3]
    # v[-2] = w[-1]
    # autoencoder.set_weights(v)
    # autoencoder.layers[1].trainable = False
    # autoencoder.layers[2].trainable = False

    # Loading model weights
    if load_weights_from_file_q.lower() == 'y':
        pick_model_weights(autoencoder, dataset_name=dataset_name)
    # x_train = x_train.astype('float32')
    # x_test = x_test.astype('float32')

    if more_train_q.lower() == 'y':
        # Training
        autoencoder.fit([x_train_skill, x_train_user], y_train,
                        epochs=epochs,
                        batch_size=back_propagation_batch_size,
                        callbacks=[es, tensorboard_callback],
                        shuffle=True,
                        verbose=2,
                        validation_data=([x_test_skill, x_test_user], y_test))
                # Cool down GPU
                # time.sleep(300)

    score = autoencoder.evaluate([x_test_skill, x_test_user], y_test, verbose=2)
    print('Test loss of fold {}: {}'.format(fold_counter, score))
    cvscores.append(score)

    # # @k evaluation process for last train batch data
    # print("eval on last batch of train data.")
    # for k in evaluation_k_set:
    #     # r@k evaluation
    #     print("Evaluating r@k for top {} records in fold {}.".format(k, fold_counter))
    #     r_at_k, r_at_k_array = dblp_eval.r_at_k(autoencoder.predict(x_train), y_train, k=k)
    #     r_at_k_overall_train[k].append(r_at_k)
    #     r_at_k_all_train[k].append(r_at_k_array)
    #
    #     # print("For top {} in Train data:\nP@{}:{}\nR@{}:{}".format(k, k, p_at_k, k, r_at_k))
    #     print("For top {} in train data: R@{}:{}".format(k, k, r_at_k))

    # @k evaluation process for test data
    print("eval on test data fold #{}".format(fold_counter))
    true_indices = []
    pred_indices = []
    with open(result_output_name, 'a+') as file:
        writer = csv.writer(file)
        for sample_x, sample_y in zip(zip(x_test_skill, x_test_user), y_test):
            start_time = time.time()
            sample_prediction = autoencoder.predict([np.asmatrix(sample_x[0]), np.zeros_like(np.asmatrix(sample_x[1]))])
            end_time = time.time()
            elapsed_time = (end_time - start_time)*1000
            pred_index, true_index = dblp_eval.find_indices(sample_prediction, [sample_y])
            true_indices.append(true_index[0])
            pred_indices.append(pred_index[0])
            writer.writerow([method_name, k_fold, fold_counter, len(pred_index[0][:k_max]), len(true_index[0]),
                             elapsed_time] + pred_index[0][:k_max] + true_index[0])

    # print("eval on test data.")
    # prediction_test = autoencoder.predict(x_test)
    # pred_indices, true_indices = dblp_eval.find_indices(prediction_test, y_test)
    # for k in evaluation_k_set:
    #     # r@k evaluation
    #     print("Evaluating map@k and r@k for top {} records in fold {}.".format(k, fold_counter))
    #     r_at_k, r_at_k_array = dblp_eval.r_at_k(pred_indices, true_indices, k=k)
    #     r_at_k_overall[k].append(r_at_k)
    #     r_at_k_all[k].append(r_at_k_array)
    #     mapk[k].append(metrics.mapk(true_indices, pred_indices, k=k))
    #     ndcg[k].append(rk.ndcg_at(pred_indices, true_indices, k=k))
    #     print("For top {} in test data: R@{}:{}".format(k, k, r_at_k))
    #     print("For top {} in test data: MAP@{}:{}".format(k, k, mapk[k][-1]))
    #     print("For top {} in test data: NDCG@{}:{}".format(k, k, ndcg[k][-1]))
    # mrr[k].append(dblp_eval.mean_reciprocal_rank(dblp_eval.cal_relevance_score(pred_indices, true_indices)))
    # print("For top {} in test data: MRR@{}:{}".format(k, k, mrr[k][-1]))



    # saving model
    # save_model_q = input('Save the models? (y/n)')
    # if save_model_q.lower() == 'y':
    model_json = autoencoder.to_json()

    # model_name = input('Please enter autoencoder model name:')

    with open('../output/Models/{}_{}_Time{}_Fold{}.json'.format(dataset_name, method_name, time_str, fold_counter), "w") as json_file:
        json_file.write(model_json)

    autoencoder.save_weights(
        "../output/Models/Weights/{}_{}_Time{}_Fold{}.h5".format(dataset_name, method_name, time_str, fold_counter))

    try:
        with open('../output/Models/{}_{}_Time{}_EncodingDim{}to{}_Fold{}_Loss{}_Epoch{}_kFold{}_BatchBP{}.txt'
                        .format(dataset_name, method_name, time_str, embedding_dim_skill, embedding_dim_user, fold_counter,
                        int(score * 1000), epochs, k_fold, back_propagation_batch_size), 'w') as f:
            with redirect_stdout(f):
                autoencoder.summary()
    except:
        with open('../output/Models/{}_{}_Time{}_EncodingDim{}to{}_Fold{}_Loss{}_Epoch{}_kFold{}_BatchBP{}.txt'
                        .format(dataset_name, method_name, time_str, embedding_dim_skill, embedding_dim_user, fold_counter,
                        'nan', epochs, k_fold, back_propagation_batch_size), 'w') as f:
            with redirect_stdout(f):
                autoencoder.summary()

    # plot_model(autoencoder, '../output/Models/{}_Time{}_EncodingDim{}_Fold{}_Loss{}_Epoch{}_kFold{}_BatchBP{}_BatchTraining{}.png'
    #            .format(dataset_name, time_str, encoding_dim, fold_counter, int(np.mean(cvscores) * 1000), epoch, k_fold,
    #                    back_propagation_batch_size, training_batch_size))
    # print('Model and its summary and architecture plot are saved.')
    print('Model and its summary are saved.')

    # Deleting model from RAM
    K.clear_session()

    # Saving evaluation data
    # cmn.utils.save_record(r_at_k_all_train, '{}_{}_r@k_all_train_Time{}'.format(dataset_name, method_name, time_str))
    # cmn.utils.save_record(r_at_k_overall_train, '{}_{}_r@k_train_Time{}'.format(dataset_name, method_name, time_str))
    #
    # cmn.utils.save_record(r_at_k_all, '{}_{}_r@k_all_Time{}'.format(dataset_name, method_name, time_str))
    # cmn.utils.save_record(r_at_k_overall, '{}_{}_r@k_Time{}'.format(dataset_name, method_name, time_str))
    #
    # print('eval records are saved successfully for fold #{}'.format(fold_counter))

    fold_counter += 1
    # break

print('Loss for each fold: {}'.format(cvscores))

# compare_submit = input('Submit for compare? (y/n)')
# if compare_submit.lower() == 'y':
#     with open('../misc/{}_KL_dim{}_r_at_k_50.pkl'.format(method_name, embedding_dim), 'wb') as f:
#         pkl.dump(r_at_k_overall, f)
#     with open('../misc/{}_dim{}_mapk_50.pkl'.format(method_name, embedding_dim), 'wb') as f:
#         pkl.dump(mapk, f)
#     with open('../misc/{}_dim{}_ndcg_50.pkl'.format(method_name, embedding_dim), 'wb') as f:
#         pkl.dump(ndcg, f)
#     with open('../misc/{}_dim{}_mrr_50.pkl'.format(method_name, embedding_dim), 'wb') as f:
#         pkl.dump(mrr, f)

result_output_name = "../output/eval_results/{}_performance_curve.csv".format(method_name)
with open(result_output_name, 'w') as file:
    writer = csv.writer(file)
    writer.writerow(
        ['time (second)', 'ndcg', 'map'])
    for t1,t2,t3 in zip(watchDog.intervals, watchDog.ndcg, watchDog.map):
        writer.writerow([t1, t2, t3])
