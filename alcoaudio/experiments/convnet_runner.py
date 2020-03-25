# -*- coding: utf-8 -*-
"""
@created on: 02/16/20,
@author: Shreesha N,
@version: v0.0.1
@system name: badgod
Description:

..todo::

"""

from torch.utils.tensorboard import SummaryWriter
import torch
import torch.nn as nn
import torch.optim as optim
import pandas as pd
import numpy as np
from torch import tensor
import time
import json
import cv2
import random
import torchvision

from alcoaudio.networks.convnet import ConvNet
from alcoaudio.utils import file_utils
from alcoaudio.datagen.audio_feature_extractors import preprocess_data
from alcoaudio.utils.network_utils import accuracy_fn, log_summary, normalize_image
from alcoaudio.utils.data_utils import read_h5py, read_npy


class ConvNetRunner:
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

        self.network_metrics_basepath = args.network_metrics_basepath
        self.tensorboard_summary_path = self.current_run_basepath + args.tensorboard_summary_path
        self.network_save_path = self.current_run_basepath + args.network_save_path

        self.network_restore_path = args.network_restore_path

        self.device = torch.device("cuda" if self.is_cuda_available else "cpu")
        self.network_save_interval = args.network_save_interval
        self.normalise = args.normalise
        self.dropout = args.dropout
        self.threshold = args.threshold

        paths = [self.network_save_path, self.tensorboard_summary_path]
        file_utils.create_dirs(paths)

        self.weights = np.load(args.keras_model_weights, allow_pickle=True)
        self.network = None
        self.network = ConvNet().to(self.device)

        self.loss_function = nn.BCEWithLogitsLoss()

        self.optimiser = optim.Adam(self.network.parameters(), lr=self.learning_rate)

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

        self.batch_loss, self.batch_accuracy, self.uar = [], [], []

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
            ones_idx, zeros_idx = [idx for idx, label in enumerate(labels) if label == 1], [idx for idx, label in
                                                                                            enumerate(labels) if
                                                                                            label == 0]
            zeros_idx = zeros_idx[:len(ones_idx)]
            ids = ones_idx + zeros_idx
            input_data, labels = input_data[ids], labels[ids]

            data = [(x, y) for x, y in zip(input_data, labels)]
            random.shuffle(data)
            input_data, labels = [x[0] for x in data], [x[1] for x in data]

        print('Total data ', len(input_data))
        print('Event rate', sum(labels) / len(labels))
        print(np.array(input_data).shape, np.array(labels).shape)

        print('Total data ', len(input_data), file=self.log_file)
        print('Event rate', sum(labels) / len(labels), file=self.log_file)
        print(np.array(input_data).shape, np.array(labels).shape, file=self.log_file)
        # data = pd.read_csv(data_filepath)
        # if shuffle:
        #     data = data.sample(frac=1)
        # input_data, labels = data['spectrogram_path'].values, data['labels'].values

        if should_batch:
            batched_input = [input_data[pos:pos + self.batch_size] for pos in
                             range(0, len(input_data), self.batch_size)]
            batched_labels = [labels[pos:pos + self.batch_size] for pos in range(0, len(labels), self.batch_size)]
            return batched_input, batched_labels
        else:
            return input_data, labels

    def train(self):
        train_data, train_labels = self.data_reader(self.data_read_path + 'train_more_data.npy',
                                                    self.data_read_path + 'train_more_labels.npy', shuffle=True,
                                                    train=True)
        test_data, test_labels = self.data_reader(self.data_read_path + 'test_more_data.npy',
                                                  self.data_read_path + 'test_more_labels.npy',
                                                  shuffle=False, train=False)
        total_step = len(train_data)
        for epoch in range(1, self.epochs):
            self.batch_loss, self.batch_accuracy, self.batch_uar, audio_for_tensorboard_train = [], [], [], None
            for i, (audio_data, label) in enumerate(zip(train_data, train_labels)):
                self.optimiser.zero_grad()
                # audio_data = tensor(
                #         [normalize_image(cv2.cvtColor(cv2.imread(spec_image), cv2.COLOR_BGR2RGB)) for spec_image in
                #          audio_data])
                # audio_data = audio_data.float()
                label = tensor(label).float()
                if i == 0:
                    self.writer.add_graph(self.network, tensor(audio_data))
                predictions = self.network(audio_data).squeeze(1)
                loss = self.loss_function(predictions, label)
                predictions = nn.Sigmoid()(predictions)
                loss.backward()
                self.optimiser.step()
                accuracy, uar = accuracy_fn(predictions, label, self.threshold)
                self.batch_loss.append(loss.detach().numpy())
                self.batch_accuracy.append(accuracy)
                self.batch_uar.append(uar)

                if i % self.display_interval == 0:
                    print(
                            f"Epoch: {epoch}/{self.epochs} | Step: {i}/{total_step} | Loss: {loss} | Accuracy: {accuracy} | UAR: {uar}")
                    print(
                            f"Epoch: {epoch}/{self.epochs} | Step: {i}/{total_step} | Loss: {loss} | Accuracy: {accuracy} | UAR: {uar}",
                            file=self.log_file)
            log_summary(self.writer, epoch, accuracy=np.mean(self.batch_accuracy),
                        loss=np.mean(self.batch_loss),
                        uar=np.mean(self.batch_uar), is_train=True)
            print('***** Overall Train Metrics ***** ')
            print('***** Overall Train Metrics ***** ', file=self.log_file)
            print(
                    f"Loss: {np.mean(self.batch_loss)} | Accuracy: {np.mean(self.batch_accuracy)} | UAR: {np.mean(self.batch_uar)} ")
            print(
                    f"Loss: {np.mean(self.batch_loss)} | Accuracy: {np.mean(self.batch_accuracy)} | UAR: {np.mean(self.batch_uar)} ",
                    file=self.log_file)

            # Test data
            self.test_batch_loss, self.test_batch_accuracy, self.test_batch_uar, self.test_batch_ua, audio_for_tensorboard_test = [], [], [], [], None
            with torch.no_grad():
                for i, (audio_data, label) in enumerate(zip(test_data, test_labels)):
                    # audio_data = tensor(
                    #         [normalize_image(cv2.cvtColor(cv2.imread(spec_image), cv2.COLOR_BGR2RGB)) for spec_image in
                    #          audio_data])
                    # audio_data = audio_data.float()
                    label = tensor(label).float()
                    test_predictions = self.network(audio_data).squeeze(1)
                    test_loss = self.loss_function(test_predictions, label)
                    test_predictions = nn.Sigmoid()(test_predictions)
                    test_accuracy, test_uar = accuracy_fn(test_predictions, label, self.threshold)
                    self.test_batch_loss.append(test_loss.numpy())
                    self.test_batch_accuracy.append(test_accuracy.numpy())
                    self.test_batch_uar.append(test_uar)
            print('***** Test Metrics ***** ')
            print('***** Test Metrics ***** ', file=self.log_file)
            print(
                    f"Loss: {np.mean(self.test_batch_loss)} | Accuracy: {np.mean(self.test_batch_accuracy)} | UAR: {np.mean(self.test_batch_uar)}")
            print(
                    f"Loss: {np.mean(self.test_batch_loss)} | Accuracy: {np.mean(self.test_batch_accuracy)} | UAR: {np.mean(self.test_batch_uar)}",
                    file=self.log_file)

            log_summary(self.writer, epoch, accuracy=np.mean(self.test_batch_accuracy),
                        loss=np.mean(self.test_batch_loss),
                        uar=np.mean(self.test_batch_uar), is_train=False)

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
