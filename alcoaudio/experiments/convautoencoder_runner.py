# -*- coding: utf-8 -*-
"""
@created on: 4/4/20,
@author: Shreesha N,
@version: v0.0.1
@system name: badgod
Description:

..todo::

"""

from torch.utils.tensorboard import SummaryWriter
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import numpy as np
from torch import tensor
import time
import json
import random

from alcoaudio.networks.convautoencoder_net import AlcoConvAutoEncoder
from alcoaudio.utils import file_utils
from alcoaudio.datagen.audio_feature_extractors import preprocess_data
from alcoaudio.utils.network_utils import accuracy_fn, log_summary, normalize_image
from alcoaudio.utils.data_utils import read_h5py, read_npy
from alcoaudio.datagen.augmentation_methods import librosaSpectro_to_torchTensor, time_mask, freq_mask, time_warp


class ConvAutoEncoderRunner:
    def __init__(self, args):
        self.run_name = args.run_name + '_' + str(time.time()).split('.')[0]
        self.current_run_basepath = args.network_metrics_basepath + '/' + self.run_name + '/'
        self.learning_rate = args.learning_rate
        self.epochs = args.epochs
        self.test_net = args.test_net
        self.train_net = args.train_net
        self.batch_size = args.batch_size
        self.num_classes = args.num_classes
        self.audio_basepath = args.audio_basepath
        self.train_data_file = args.train_data_file
        self.test_data_file = args.test_data_file
        self.data_read_path = args.data_save_path
        self.is_cuda_available = torch.cuda.is_available()
        self.display_interval = args.display_interval
        self.sampling_rate = args.sampling_rate
        self.sample_size_in_seconds = args.sample_size_in_seconds
        self.overlap = args.overlap
        self.alpha = args.alpha
        self.beta = args.beta

        self.network_metrics_basepath = args.network_metrics_basepath
        self.tensorboard_summary_path = self.current_run_basepath + args.tensorboard_summary_path
        self.network_save_path = self.current_run_basepath + args.network_save_path

        self.network_restore_path = args.network_restore_path

        self.device = torch.device("cuda" if self.is_cuda_available else "cpu")
        self.network_save_interval = args.network_save_interval
        self.normalise = args.normalise_while_training
        self.dropout = args.dropout
        self.threshold = args.threshold

        paths = [self.network_save_path, self.tensorboard_summary_path]
        file_utils.create_dirs(paths)

        self.weights = np.load(args.keras_model_weights, allow_pickle=True)
        self.network = None
        self.network = AlcoConvAutoEncoder().to(self.device)
        self.pos_weight = None
        self.classification_loss = None
        self.reconstruction_loss = nn.BCEWithLogitsLoss()
        self.learning_rate_decay = args.learning_rate_decay
        self.optimiser = optim.Adam(self.network.parameters(), lr=self.learning_rate)
        self.scheduler = torch.optim.lr_scheduler.ExponentialLR(self.optimiser, gamma=self.learning_rate_decay)

        self._min, self._max = float('inf'), -float('inf')

        if self.train_net:
            self.network.train()
            self.log_file = open(self.network_save_path + '/' + self.run_name + '.log', 'w')
            self.log_file.write(json.dumps(args))
        if self.test_net:
            print('Loading Network')
            self.network.load_state_dict(torch.load(self.network_restore_path, map_location=self.device))
            self.network.eval()
            self.log_file = open(self.network_restore_path.replace('_40.pt', '.log'), 'a')
            print('\n\n\n********************************************************', file=self.log_file)
            print('Testing Model - ', self.network_restore_path)
            print('Testing Model - ', self.network_restore_path, file=self.log_file)
            print('********************************************************', file=self.log_file)

        self.writer = SummaryWriter(self.tensorboard_summary_path)
        print("Network config:\n", self.network)
        print("Network config:\n", self.network, file=self.log_file)

        self.batch_classification_loss, self.batch_accuracy, self.uar = [], [], []

        print('Configs used:\n', json.dumps(args, indent=4))
        print('Configs used:\n', json.dumps(args, indent=4), file=self.log_file)

    def data_reader(self, data_filepath, label_filepath, train, should_batch=True, shuffle=True):
        # data = pd.read_csv(data_file)[:50]
        # if shuffle:
        #     data = data.sample(frac=1)
        # input_data, labels = preprocess_data(self.audio_basepath, data['WAV_PATH'].values, data['label'].values,
        #                                      normalise=normalise, sample_size_in_seconds=self.sample_size_in_seconds,
        #                                      sampling_rate=self.sampling_rate, overlap=self.overlap)
        input_data, labels = read_npy(data_filepath), read_npy(label_filepath)

        if train:

            print('Original data size - before Augmentation')
            print('Original data size - before Augmentation', file=self.log_file)
            print('Total data ', len(input_data))
            print('Event rate', sum(labels) / len(labels))
            print(np.array(input_data).shape, np.array(labels).shape)

            print('Total data ', len(input_data), file=self.log_file)
            print('Event rate', sum(labels) / len(labels), file=self.log_file)
            print(np.array(input_data).shape, np.array(labels).shape, file=self.log_file)

            print('Data Augmentation starts . . .')
            print('Data Augmentation starts . . .', file=self.log_file)
            label_to_augment = 1
            amount_to_augment = 0.8
            ones_ids = [idx for idx, x in enumerate(labels) if x == label_to_augment]
            random_idxs = random.choices(ones_ids,
                                         k=int(len(ones_ids) * amount_to_augment))
            data_to_augment = input_data[random_idxs]
            augmented_data = []
            augmented_labels = []
            for x in data_to_augment:
                x = librosaSpectro_to_torchTensor(x)
                x = random.choice([time_mask, freq_mask])(x)[0].numpy()
                # x = time_warp(x)[0].numpy()
                augmented_data.append(x), augmented_labels.append(label_to_augment)

            input_data = np.concatenate((input_data, augmented_data))
            labels = np.concatenate((labels, augmented_labels))

            print('Data Augmentation done . . .')
            print('Data Augmentation done . . .', file=self.log_file)

            for x in input_data:
                self._min = min(np.min(x), self._min)
                self._max = max(np.max(x), self._max)

            data = [(x, y) for x, y in zip(input_data, labels)]
            random.shuffle(data)
            input_data, labels = np.array([x[0] for x in data]), [x[1] for x in data]

            # Initialize pos_weight based on training data
            self.pos_weight = len([x for x in labels if x == 0]) / len([x for x in labels if x == 1])
            print('Pos weight for the train data - ', self.pos_weight)
            print('Pos weight for the train data - ', self.pos_weight, file=self.log_file)

        print('Total data ', len(input_data))
        print('Event rate', sum(labels) / len(labels))
        print(np.array(input_data).shape, np.array(labels).shape)

        print('Total data ', len(input_data), file=self.log_file)
        print('Event rate', sum(labels) / len(labels), file=self.log_file)
        print(np.array(input_data).shape, np.array(labels).shape, file=self.log_file)

        # Normalizing `input data` on train dataset's min and max values
        if self.normalise:
            input_data = (input_data - self._min) / (self._max - self._min)

        if should_batch:
            batched_input = [input_data[pos:pos + self.batch_size] for pos in
                             range(0, len(input_data), self.batch_size)]
            batched_labels = [labels[pos:pos + self.batch_size] for pos in range(0, len(labels), self.batch_size)]
            return batched_input, batched_labels
        else:
            return input_data, labels

    def run_for_epoch(self, epoch, x, y, type):
        self.classification_test_batch_loss, self.test_batch_accuracy, self.test_batch_uar, self.test_batch_ua, self.test_batch_reconstruction_loss, self.test_total_loss, audio_for_tensorboard_test = [], [], [], [], [], [], None
        with torch.no_grad():
            for i, (audio_data, label) in enumerate(zip(x, y)):
                label = tensor(label).float()
                audio_data = tensor(audio_data)
                test_reconstructions, test_predictions = self.network(audio_data)
                test_reconstructions = test_reconstructions.squeeze(1)
                test_predictions = test_predictions.squeeze(1)
                classification_test_loss = self.classification_loss(test_predictions, label)
                reconstruction_test_loss = self.reconstruction_loss(test_reconstructions, audio_data)

                test_predictions = nn.Sigmoid()(test_predictions)
                test_accuracy, test_uar = accuracy_fn(test_predictions, label, self.threshold)
                self.classification_test_batch_loss.append(classification_test_loss.numpy())
                self.test_batch_reconstruction_loss.append(reconstruction_test_loss.numpy())
                self.test_total_loss.append((classification_test_loss + reconstruction_test_loss).numpy())
                self.test_batch_accuracy.append(test_accuracy.numpy())
                self.test_batch_uar.append(test_uar)
        print(f'***** {type} Metrics ***** ')
        print(f'***** {type} Metrics ***** ', file=self.log_file)
        print(
                f"CLoss: {np.mean(self.classification_test_batch_loss)}| RLoss: {np.mean(self.test_batch_reconstruction_loss)} | TLoss:{np.mean(self.test_total_loss)} | Accuracy: {np.mean(self.test_batch_accuracy)} | UAR: {np.mean(self.test_batch_uar)}")
        print(
                f"CLoss: {np.mean(self.classification_test_batch_loss)}| RLoss: {np.mean(self.test_batch_reconstruction_loss)}| TLoss:{np.mean(self.test_total_loss)} | Accuracy: {np.mean(self.test_batch_accuracy)} | UAR: {np.mean(self.test_batch_uar)}",
                file=self.log_file)

        log_summary(self.writer, epoch, accuracy=np.mean(self.test_batch_accuracy),
                    closs=np.mean(self.classification_test_batch_loss),
                    rloss=np.mean(self.test_batch_reconstruction_loss),
                    total_loss=np.mean(self.test_total_loss),
                    uar=np.mean(self.test_batch_uar), type=type)

    def train(self):

        # For purposes of calculating normalized values, call this method with train data followed by test
        train_data, train_labels = self.data_reader(self.data_read_path + 'train_challenge_data.npy',
                                                    self.data_read_path + 'train_challenge_labels.npy',
                                                    shuffle=True,
                                                    train=True)
        dev_data, dev_labels = self.data_reader(self.data_read_path + 'dev_challenge_data.npy',
                                                self.data_read_path + 'dev_challenge_labels.npy',
                                                shuffle=False, train=False)
        test_data, test_labels = self.data_reader(self.data_read_path + 'test_challenge_data.npy',
                                                  self.data_read_path + 'test_challenge_labels.npy',
                                                  shuffle=False, train=False)

        # For the purposes of assigning pos weight on the fly we are initializing the cost function here
        self.classification_loss = nn.BCEWithLogitsLoss(pos_weight=tensor(self.pos_weight))

        def shuffle_batch(train_data, train_labels):
            train_data = [item for sublist in train_data for item in sublist]
            train_labels = [item for sublist in train_labels for item in sublist]
            data = [(x, y) for x, y in zip(train_data, train_labels)]
            random.shuffle(data)
            input_data, labels = np.array([x[0] for x in data]), [x[1] for x in data]
            batched_input = [input_data[pos:pos + self.batch_size] for pos in
                             range(0, len(input_data), self.batch_size)]
            batched_labels = [labels[pos:pos + self.batch_size] for pos in range(0, len(labels), self.batch_size)]
            return batched_input, batched_labels

        total_step = len(train_data)
        for epoch in range(1, self.epochs):
            train_data, train_labels = shuffle_batch(train_data, train_labels)
            self.batch_classification_loss, self.batch_accuracy, self.batch_uar, self.batch_reconstruction_loss, self.batch_total_loss, audio_for_tensorboard_train = [], [], [], [], [], None
            for i, (audio_data, label) in enumerate(zip(train_data, train_labels)):
                self.optimiser.zero_grad()
                audio_data = tensor(audio_data)
                label = tensor(label).float()
                if i == 0:
                    self.writer.add_graph(self.network, audio_data)
                train_reconstructions, predictions = self.network(audio_data)
                predictions = predictions.squeeze(1)
                train_reconstructions = train_reconstructions.squeeze(1)
                classification_loss = self.classification_loss(predictions, label)
                reconstruction_loss = self.reconstruction_loss(train_reconstructions, audio_data)
                total_loss = (self.alpha * classification_loss) + (self.beta * reconstruction_loss)
                total_loss.backward()
                self.optimiser.step()
                predictions = nn.Sigmoid()(predictions)
                accuracy, uar = accuracy_fn(predictions, label, self.threshold)
                self.batch_classification_loss.append(classification_loss.detach().numpy())
                self.batch_reconstruction_loss.append(reconstruction_loss.detach().numpy())
                self.batch_total_loss.append((classification_loss + reconstruction_loss).detach().numpy())
                self.batch_accuracy.append(accuracy)
                self.batch_uar.append(uar)
                if i % self.display_interval == 0:
                    print(
                            f"Epoch: {epoch}/{self.epochs} | Step: {i}/{total_step} | CLoss: {classification_loss} | RLoss: {reconstruction_loss}| TLoss:{classification_loss + reconstruction_loss} | Accuracy: {accuracy} | UAR: {uar}")
                    print(
                            f"Epoch: {epoch}/{self.epochs} | Step: {i}/{total_step} | CLoss: {classification_loss} | RLoss: {reconstruction_loss} | TLoss:{classification_loss + reconstruction_loss} | Accuracy: {accuracy} | UAR: {uar}",
                            file=self.log_file)

            # Decay learning rate
            self.scheduler.step(epoch=epoch)
            log_summary(self.writer, epoch, accuracy=np.mean(self.batch_accuracy),
                        closs=np.mean(self.batch_classification_loss),
                        rloss=np.mean(self.batch_reconstruction_loss),
                        total_loss=np.mean(self.batch_total_loss),
                        uar=np.mean(self.batch_uar), type='Train')
            print('***** Overall Train Metrics ***** ')
            print('***** Overall Train Metrics ***** ', file=self.log_file)
            print(
                    f"CLoss: {np.mean(self.batch_classification_loss)}| RLoss: {np.mean(self.batch_reconstruction_loss)} | TLoss:{np.mean(self.batch_total_loss)}| Accuracy: {np.mean(self.batch_accuracy)} | UAR: {np.mean(self.batch_uar)} ")
            print(
                    f"CLoss: {np.mean(self.batch_classification_loss)}| RLoss: {np.mean(self.batch_reconstruction_loss)} | TLoss:{np.mean(self.batch_total_loss)} | Accuracy: {np.mean(self.batch_accuracy)} | UAR: {np.mean(self.batch_uar)} ",
                    file=self.log_file)

            # dev data
            self.run_for_epoch(epoch, dev_data, dev_labels, type='Dev')

            # test data
            self.run_for_epoch(epoch, test_data, test_labels, type='Test')

            if epoch % self.network_save_interval == 0:
                save_path = self.network_save_path + '/' + self.run_name + '_' + str(epoch) + '.pt'
                torch.save(self.network.state_dict(), save_path)
                print('Network successfully saved: ' + save_path)

    def test(self):
        test_data, test_labels = self.data_reader(self.data_read_path + 'test_data.npy',
                                                  shuffle=False,
                                                  should_batch=False)
        test_data, test_labels = test_data, test_labels
        test_predictions = self.network(test_data).detach()
        print(test_predictions)

        test_predictions = nn.Sigmoid()(test_predictions).squeeze(1)
        print(test_predictions)
        test_accuracy = accuracy_fn(test_predictions, test_labels, self.threshold)
        print(f"Accuracy: {test_accuracy}")
        print(f"Accuracy: {test_accuracy}", file=self.log_file)
