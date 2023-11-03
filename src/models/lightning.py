from lightning import LightningModule
import torch
from torch import nn, optim
# from torchmetrics.detection.mean_ap import MeanAveragePrecision
import matplotlib.pyplot as plt
import torchvision.transforms as T

from .ssdnet import SSDNet
from ..visualization.draw_bbox import draw_bboxes_on_axis_from_prediction
from torchmetrics.detection.mean_ap import MeanAveragePrecision
from torchvision.ops import nms

from typing import Tuple

class LightningWrapper(LightningModule):
    def __init__(self, image_size: Tuple[int, int], num_classes: int, model: str, batch_size: int, iou_threshold: float, conf_threshold: float, detections_per_img: int):
        super().__init__()
        self.model_variant = model
        self.model = SSDNet(image_size, num_classes, backbone=model, detections_per_img=detections_per_img)
        self.map_metric = MeanAveragePrecision()
        self.batch_size = batch_size
        self.iou_threshold = iou_threshold
        self.conf_threshold = conf_threshold
        self.image_size = image_size
        self.num_classes = num_classes
        self.detections_per_img = detections_per_img

        self.save_hyperparameters()

    def forward(self, images):
        return self.model(images)

    def get_accuracy(self, predictions, labels):

        def filter_confidence(prediction, indices):
            return indices[prediction["scores"][indices] >= self.conf_threshold]

        # For accuracy computation, perform NMS and filter out predictions with low confidence
        box_indices = [
            filter_confidence(prediction, nms(prediction["boxes"], prediction["scores"], self.iou_threshold))
            for prediction in predictions 
        ]
        # box_indices = [
        #     nms(prediction["boxes"], prediction["scores"], self.iou_threshold)
        #     for prediction in predictions
        # ]

        nms_prediction = [
            {
                "boxes": prediction["boxes"][box_indices],
                "scores": prediction["scores"][box_indices],
                "labels": prediction["labels"][box_indices]
            }
            for prediction, box_indices in zip(predictions, box_indices)
        ]

        return self.map_metric(nms_prediction, labels)


    def _step(self, images, labels):
        loss_dict = self.model(images, labels)
        losses = sum(loss for loss in loss_dict.values())

        return losses

    def training_step(self, batch, batch_idx):
        images, labels = batch
        loss = self._step(images, labels)
        self.log("train_loss", loss, batch_size=self.batch_size, prog_bar=True)
        return loss

    def validation_step(self, batch, batch_idx):
        images, labels = batch
        predictions = self.forward(images)

        score = self.get_accuracy(predictions, labels)
        
        self.log("val/map", score["map"], sync_dist=True, batch_size=self.batch_size, prog_bar=True)
        self.log("val/map50", score["map_50"], sync_dist=True, batch_size=self.batch_size)
        self.log("val/map75", score["map_75"], sync_dist=True, batch_size=self.batch_size)
        self.log("val/mar10", score["mar_10"], sync_dist=True, batch_size=self.batch_size)
        self.log("val/mar100", score["mar_100"], sync_dist=True, batch_size=self.batch_size)

    def configure_optimizers(self):
        optimizer = optim.Adam(self.parameters(), lr=1e-3)
        return optimizer

    def forward(self, images):
        return self.model(images)