# -*- coding: utf-8 -*-
"""
@created on: 2/23/20,
@author: Shreesha N,
@version: v0.0.1
@system name: badgod
Description:

..todo::

"""

from torch import tensor
import torch
from sklearn.metrics import recall_score
from sklearn.metrics import confusion_matrix
import numpy as np


def accuracy_fn(preds, labels, threshold):
    labels = labels.cpu().detach().numpy()
    # todo: UAR implementation is wrong. Tweak it once the model is ready
    # predictions = torch.where(preds > threshold, tensor(1), tensor(0))
    predictions = np.where(preds.cpu().detach().numpy() > threshold, 1, 0)
    accuracy = np.sum(predictions == labels) / float(len(labels))
    uar = recall_score(labels, predictions, average='macro')
    return accuracy, uar


def log_summary(writer, global_step, accuracy, loss, uar, is_train):
    if is_train:
        mode = 'Train'
    else:
        mode = 'Test'

    writer.add_scalar(f'{mode}/Accuracy', accuracy, global_step)
    writer.add_scalar(f'{mode}/Loss', loss, global_step)
    writer.add_scalar(f'{mode}/UAR', uar, global_step)
    writer.flush()


def normalize_image(image):
    # return (image - image.mean())/image.std()
    return (image - image.min()) / (image.max() - image.min())
