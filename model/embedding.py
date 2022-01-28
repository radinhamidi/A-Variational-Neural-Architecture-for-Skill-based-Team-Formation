# -*- coding: utf-8 -*-
"""
Created on Thursday Nov 21 2019

@author: Hossein Fani (sites.google.com/site/hosseinfani/)
"""

import gensim, numpy, pylab, random, pickle
import os, getopt, sys, multiprocessing

sys.path.extend(['./../team_formation'])

from cmn.tsne import tsne, pca


# teams as documents, members as words
# doc_list = ['u1 u2 u3','u2 u3','u1 u2 u1 u2']
# label_list = ['t1','t2','t3']

class Team2Vec:
    def __init__(self):
        self.teams = []
        self.member_type = ''

    def init(self, team_matrix, member_type='user'):  # member_type={'user','skill'}
        self.member_type = member_type
        teams_label = []
        # teams_skils = []
        teams_members = []
        for team in team_matrix:
            teams_label.append(team[0])
            if member_type.lower() == 'skill':
                teams_members.append(team[1].col)
            else:  # member_type == 'user'
                teams_members.append(team[2].col)

        for index, team in enumerate(teams_members):
            td = gensim.models.doc2vec.TaggedDocument([str(m) for m in team], [
                str(teams_label[index])])  # the [] is needed to surround the tags!
            self.teams.append(td)
        print('#teams loaded: {}; member type = {}'.format(len(self.teams), member_type))

    def train(self, dimension=300, window=2, dist_mode=1, epochs=100, output='./output/Models/T2V/', dataset_name='dblp'):

        self.settings = dataset_name + '_d' + str(dimension) + '_w' + str(window) + '_m' + str(dist_mode) + '_t' + str(self.member_type.capitalize()) + '_V2.2'
        print('training settings: %s\n' % self.settings)

        # build the model
        # alpha=0.025
        # min_count=5
        # max_vocab_size=None
        # sample=0
        # seed=1
        # min_alpha=0.0001
        # hs=1
        # negative=0
        # dm_mean=0
        # dm_concat=0
        # dm_tag_count=1
        # docvecs=None
        # docvecs_mapfile=None
        # comment=None
        # trim_rule=None

        self.model = gensim.models.Doc2Vec(dm=dist_mode,
                                           # ({1,0}, optional) – Defines the training algorithm. If dm=1, ‘distributed memory’ (PV-DM) is used. Otherwise, distributed bag of words (PV-DBOW) is employed.
                                           vector_size=dimension,
                                           window=window,
                                           dbow_words=1,
                                           negative=15,
                                           # ({1,0}, optional) – If set to 1 trains word-vectors (in skip-gram fashion) simultaneous with DBOW doc-vector training; If 0, only trains doc-vectors (faster).
                                           min_alpha=0.025,
                                           min_count=0,
                                           workers=multiprocessing.cpu_count())
        self.model.build_vocab(self.teams)

        # start training
        for e in range(epochs):
            if not (e % 10):
                print('iteration {0}'.format(e))
            self.model.train(self.teams, total_examples=self.model.corpus_count, epochs=self.model.epochs)
            self.model.alpha -= 0.002  # decrease the learning rate
            self.model.min_alpha = self.model.alpha  # fix the learning rate, no decay

        if output:
            with open('{}teams_{}'.format(output, self.settings), 'wb') as f:
                pickle.dump(self.teams, f)
            self.model.save('{}model_{}'.format(output, self.settings))
            self.model.save_word2vec_format('{}members2vec_{}'.format(output, self.settings))
            self.model.docvecs.save_word2vec_format('{}team2vec_{}'.format(output, self.settings))
            print('Model saved for {} under directory {}'.format(self.settings, output))

    def get_teams(self):
        return self.model.docvecs.doctags

    def get_members(self):
        return self.model.wv.vocab

    def get_team_members(self, tid):
        return [int(m) for t in self.teams if str(tid) in t.tags for m in t.words]

    def get_member_vec(self, mid):
        return self.model[str(mid)]

    def get_team_vec(self, tid):
        return self.model.docvecs[str(tid)]

    def get_member_similarity(self, m1, m2):
        return self.model.wv.similarity(str(m1), str(m2))

    def get_team_similarity(self, t1, t2):
        return self.model.docvecs.similarity(str(t1), str(t2))

    def get_team_most_similar(self, tid, topn=10):
        return self.model.docvecs.most_similar(str(tid), topn=topn)

    def load_model(self, modelfile, includeTeams=False):
        # ModuleNotFoundError: No module named 'numpy.random._pickle': numpy version conflict when saving and loading
        self.model = gensim.models.Doc2Vec.load(modelfile)
        if includeTeams:
            with open(modelfile.replace('model', 'teams'), 'rb') as f:
                self.teams = pickle.load(f)

    def get_member_most_similar_by_vector(self, mvec, topn=10):
        similar_list = self.model.wv.similar_by_vector(mvec, topn=topn)  # is it sorted?
        similar_list.sort(key=lambda x: x[1], reverse=True)  # now it is sorted :)
        return similar_list

    def get_team_most_similar_by_vector(self, tvec, topn=10):
        similar_list = self.model.similar_by_vector(tvec, topn=topn)  # is it sorted?
        similar_list.sort(key=lambda x: x[1], reverse=True)  # now it is sorted :)
        return similar_list

    def infer_team_vector(self, members):
        iv = self.model.infer_vector(members)
        return iv, self.model.docvecs.most_similar([iv])

    def plot_model(self, method='pca', memberids=None, teamids=None, output='./'):
        team_vecs = []
        team_labels = []
        member_vecs = []
        member_labels = []

        for member in self.model.wv.vocab.keys():
            if memberids is None or member in memberids:
                member_vecs.append(self.model.wv[member])
                member_labels.append(member)

        for team in self.model.docvecs.doctags.keys():
            if teamids is None or member in teamids:
                team_vecs.append(self.model.docvecs[team])
                team_labels.append(team)

        if method == 'pca':
            members = pca(numpy.array(member_vecs), 2)
            teams = pca(numpy.array(team_vecs), 2)
            all_dw = pca(numpy.array(team_vecs + member_vecs), 2)
        else:
            members = tsne(numpy.array(member_vecs), 2)
            teams = tsne(numpy.array(team_vecs), 2)
            all_dw = tsne(numpy.array(team_vecs + member_vecs), 2)

        # plt.plot(pca.explained_variance_ratio_)
        for index, vec in enumerate(members):
            # print ('%s %s'%(words_label[index], vec))
            pylab.scatter(vec[0], vec[1])
            pylab.annotate(member_labels[index], xy=(vec[0], vec[1]))
        # fig_words_pca = pylab.figure()
        # ax = Axes3D(fig_words_pca)
        # ax.scatter(words_pca[:, 0], words_pca[:, 1], color='r')
        if output:
            pylab.savefig('{}members_{}_{}.png'.format(output, method, self.settings))
        # pylab.show()
        pylab.close()

        for index, vec in enumerate(teams):
            pylab.scatter(vec[0], vec[1])
            pylab.annotate(team_labels[index], xy=(vec[0], vec[1]))

        if output:
            pylab.savefig('{}teams_{}_{}.png'.format(output, method, self.settings))
        pylab.close()

        for index, vec in enumerate(all_dw):
            pylab.scatter(vec[0], vec[1])
            if index < len(member_labels):
                pylab.annotate(member_labels[index], xy=(vec[0], vec[1]))
            else:
                pylab.annotate(team_labels[index - len(member_labels)], xy=(vec[0], vec[1]))
        if output:
            pylab.savefig('{}teams_members_{}_{}.png'.format(output, method, self.settings))
        pylab.close()


def main_train_team2vec():
    import dal.load_dblp_data as dblp
    # if dblp.preprocessed_dataset_exist(file_path='../dataset/dblp_preprocessed_dataset_V2.2.pkl'):
    #     team_matrix = dblp.load_preprocessed_dataset(file_path='../dataset/dblp_preprocessed_dataset_V2.2.pkl')
    if dblp.preprocessed_dataset_exist(file_path='../dataset/imdb/imdb.pkl'):
        team_matrix = dblp.load_preprocessed_dataset(file_path='../dataset/imdb/imdb.pkl')
    else:
        print('Source file does not exist.')
        # dblp.extract_data(filter_journals=True)
        # dblp.dataset_preprocessing(dblp.load_ae_dataset(file_path='../dataset/ae_dataset.pkl'), seed=7, kfolds=10)
        # team_matrix = dblp.load_preprocessed_dataset(file_path='../dataset/dblp_preprocessed_dataset_V2.2.pkl')

    t2v = Team2Vec()

    help_str = 'team2vec.py [-m] [-s] [-d <dimension=100>] [-e <epochs=100>] [-w <window=2>] \n-m: distributed memory mode; default=distributed bag of members\n-s: member type = skill; default = user'
    try:
        opts, args = getopt.getopt(sys.argv[1:], "hmsd:w:", ["dimension=", "window="])
    except getopt.GetoptError:
        print(help_str)
        sys.exit(2)

    ### Settings
    dimension = 300
    epochs = 500
    window = 2
    dm = 1
    member_type = 'User'
    dataset_name = 'imdb'

    for opt, arg in opts:
        if opt == '-h':
            print(help_str)
            sys.exit()
        elif opt == '-s':
            member_type = 'skill'
        elif opt == '-m':
            dm = 1
        elif opt in ("-d", "--dimension"):
            dimension = int(arg)
        elif opt in ("-e", "--epochs"):
            epochs = int(arg)
        elif opt in ("-w", "--window"):
            window = int(arg)

    t2v.init(team_matrix, member_type=member_type)
    t2v.train(dimension=dimension, window=window, dist_mode=dm,
              output='../output/Models/T2V/', epochs=epochs, dataset_name=dataset_name)
    # t2v.plot_model('pca', output='../output/Figures/')
    # t2v.plot_model('tsne', output='../output/Figures/')

    # sample running string
    # python3 -u ./ml/team2vec.py -d 500 -w 2 -m 2>&1 |& tee  ./output/Team2Vec/log_d500_w2_m1.txt

    # test
    # t2v.init(random.sample(team_matrix, 100))
    # t2v.train(dimension=100, window=2, dist_mode=1, output='./output/Team2Vec/', epochs=10)
    # t2v.plot_model('pca', output='./output/Team2Vec/')
    # t2v.plot_model('tsne', output='./output/Team2Vec/')


if __name__ == "__main__":
    main_train_team2vec()

    # t2v = Team2Vec()
    # t2v.load_model('./output/Team2Vec/team_user/model_d500_w2_m1')
    # with open('./dataset/ae_dataset.pkl', 'rb') as f:
    #     team_matrix = pickle.load(f)
    # t2v.init(team_matrix)
    # for r in team_matrix:
    #     try:
    #         id = r[0]
    #         team_vec = t2v.get_team_vec(id)
    #         team_vec = t2v.get_teams()[str(id)]
    #         print(t2v.get_team_members(id))
    #     except:
    #         print('{} not found!'.format(id))
    pass
