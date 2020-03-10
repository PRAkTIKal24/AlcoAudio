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
    # todo: UAR implementation is wrong. Tweak it once the model is ready
    predictions = torch.where(preds > tensor(threshold), tensor(1), tensor(0))
    print("pred sum ", torch.sum(predictions).numpy(), "pred len ", len(predictions), "actual sum ",
          "sigmoided ", torch.sum(labels).numpy(), torch.mean(preds).numpy())
    accuracy = torch.sum(predictions == labels) / float(len(labels))
    uar = recall_score(labels, predictions.numpy(), average='macro')
    if np.array_equal(labels, predictions.numpy()):
        ua = 1
    else:
        tn, fp, fn, tp = confusion_matrix(labels, predictions).ravel()
        ua = (tp + tn) / (tn + fp + fn + tp)
    return accuracy, uar, ua


def log_summary(writer, global_step, accuracy, loss, uar, ua, is_train):
    if is_train:
        mode = 'Train'
    else:
        mode = 'Test'

    writer.add_scalar(f'{mode}/Accuracy', accuracy, global_step)
    writer.add_scalar(f'{mode}/Loss', loss, global_step)
    writer.add_scalar(f'{mode}/UAR', uar, global_step)
    writer.add_scalar(f'{mode}/UA', ua, global_step)

    writer.flush()


def normalize_image(image):
    # return (image - image.mean())/image.std()
    return (image - image.min()) / (image.max() - image.min())
