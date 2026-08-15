import datetime
import os

import torch
import matplotlib
matplotlib.use('Agg')
from matplotlib import pyplot as plt
from torch.utils.tensorboard import SummaryWriter

import shutil
import numpy as np

from PIL import Image
from tqdm import tqdm
from .utils import cvtColor, preprocess_input, resize_image
from .utils_bbox import DecodeBox
from .utils_map import get_coco_map, get_map


class LossHistory():
    def __init__(self, log_dir, model, input_shape):
        self.log_dir    = log_dir
        self.losses     = []
        self.val_loss   = []
        
        os.makedirs(self.log_dir, exist_ok=True)
        self.writer = SummaryWriter(self.log_dir)

    def append_loss(self, epoch, loss, val_loss):
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)

        self.losses.append(loss)
        self.val_loss.append(val_loss)

        with open(os.path.join(self.log_dir, "epoch_loss.txt"), 'a') as f:
            f.write(str(loss))
            f.write("\n")
        with open(os.path.join(self.log_dir, "epoch_val_loss.txt"), 'a') as f:
            f.write(str(val_loss))
            f.write("\n")

        self.writer.add_scalar('loss', loss, epoch)
        self.writer.add_scalar('val_loss', val_loss, epoch)
        self.loss_plot()

    def loss_plot(self):
        iters = range(len(self.losses))

        plt.figure()
        plt.plot(iters, self.losses, 'red', linewidth = 2, label='train loss')
        plt.plot(iters, self.val_loss, 'coral', linewidth = 2, label='val loss')

        plt.grid(True)
        plt.xlabel('Epoch')
        plt.ylabel('Loss')
        plt.legend(loc="upper right")

        plt.savefig(os.path.join(self.log_dir, "epoch_loss.png"))

        plt.cla()
        plt.close("all")

class EvalCallback():
    def __init__(self, net, input_shape, class_names, num_classes, val_lines, log_dir, cuda, \
            map_out_path=".temp_map_out", max_boxes=100, confidence=0.05, nms_iou=0.5, letterbox_image=True, MINOVERLAP=0.5, eval_flag=True, period=1, verbose=False):
        super(EvalCallback, self).__init__()
        
        self.net                = net
        self.input_shape        = input_shape
        self.class_names        = class_names
        self.num_classes        = num_classes
        self.val_lines          = val_lines
        self.log_dir            = log_dir
        self.cuda               = cuda
        self.map_out_path       = map_out_path
        self.max_boxes          = max_boxes
        self.confidence         = confidence
        self.nms_iou            = nms_iou
        self.letterbox_image    = letterbox_image
        self.MINOVERLAP         = MINOVERLAP
        self.eval_flag          = eval_flag
        self.period             = period
        self.verbose            = verbose  # 控制输出详细程度
        
        self.bbox_util          = DecodeBox(self.num_classes, (self.input_shape[0], self.input_shape[1]))
        
        self.maps       = [0]
        self.epoches    = [0]
        self.metrics    = {}
        if self.eval_flag:
            with open(os.path.join(self.log_dir, "epoch_map.txt"), 'a') as f:
                f.write(str(0))
                f.write("\n")

    def get_map_txt(self, image_id, image, class_names, map_out_path):
        f = open(os.path.join(map_out_path, "detection-results/"+image_id+".txt"), "w", encoding='utf-8') 
        image_shape = np.array(np.shape(image)[0:2])
        image       = cvtColor(image)
        datasets  = resize_image(image, (self.input_shape[1], self.input_shape[0]), self.letterbox_image)
        datasets  = np.expand_dims(np.transpose(preprocess_input(np.array(datasets, dtype='float32')), (2, 0, 1)), 0)

        with torch.no_grad():
            images = torch.from_numpy(datasets)
            if self.cuda:
                images = images.cuda()
            outputs = self.net(images)
            outputs = self.bbox_util.decode_box(outputs)
            results = self.bbox_util.non_max_suppression(outputs, self.num_classes, self.input_shape, 
                        image_shape, self.letterbox_image, conf_thres = self.confidence, nms_thres = self.nms_iou)
                                                    
            if results[0] is None: 
                return 

            top_label   = np.array(results[0][:, 5], dtype = 'int32')
            top_conf    = results[0][:, 4]
            top_boxes   = results[0][:, :4]

        top_100     = np.argsort(top_conf)[::-1][:self.max_boxes]
        top_boxes   = top_boxes[top_100]
        top_conf    = top_conf[top_100]
        top_label   = top_label[top_100]

        for i, c in list(enumerate(top_label)):
            predicted_class = self.class_names[int(c)]
            box             = top_boxes[i]
            score           = str(top_conf[i])

            top, left, bottom, right = box
            if predicted_class not in class_names:
                continue

            f.write("%s %s %s %s %s %s\n" % (predicted_class, score[:6], str(int(left)), str(int(top)), str(int(right)),str(int(bottom))))

        f.close()
        return 
    
    def calculate_metrics(self, map_out_path):
        """
        计算详细的评估指标，包括准确率、召回率、F1分数和平均置信度
        """
        # 初始化指标统计
        total_tp, total_fp, total_fn = 0, 0, 0
        total_confidence = 0
        detection_count = 0
        
        class_metrics = {}
        for class_name in self.class_names:
            class_metrics[class_name] = {'tp': 0, 'fp': 0, 'fn': 0, 'total_conf': 0, 'count': 0}
        
        # 遍历所有验证样本
        for annotation_line in self.val_lines:
            line = annotation_line.split()
            image_id = os.path.basename(line[0]).split('.')[0]
            
            # 读取真实框
            gt_boxes = []
            try:
                with open(os.path.join(map_out_path, "ground-truth/"+image_id+".txt"), "r") as f:
                    for line in f.readlines():
                        line = line.strip().split()
                        class_name = line[0]
                        gt_boxes.append({
                            'class_name': class_name,
                            'bbox': [int(x) for x in line[1:5]]
                        })
            except FileNotFoundError:
                continue
                
            # 读取检测结果
            detections = []
            try:
                with open(os.path.join(map_out_path, "detection-results/"+image_id+".txt"), "r") as f:
                    for line in f.readlines():
                        line = line.strip().split()
                        class_name = line[0]
                        confidence = float(line[1])
                        bbox = [int(x) for x in line[2:6]]
                        detections.append({
                            'class_name': class_name,
                            'confidence': confidence,
                            'bbox': bbox
                        })
            except FileNotFoundError:
                continue
            
            # 计算每个类别的指标
            for det in detections:
                det_class = det['class_name']
                det_conf = det['confidence']
                
                # 累计置信度和检测数量
                total_confidence += det_conf
                detection_count += 1
                class_metrics[det_class]['total_conf'] += det_conf
                class_metrics[det_class]['count'] += 1
                
                # 查找匹配的真实框
                matched_gt = None
                max_iou = 0
                for gt in gt_boxes:
                    if gt['class_name'] == det_class:
                        iou = self.calculate_iou(det['bbox'], gt['bbox'])
                        if iou > max_iou and iou >= self.MINOVERLAP:
                            max_iou = iou
                            matched_gt = gt
                
                # 根据IoU判断TP/FP
                if matched_gt:
                    total_tp += 1
                    class_metrics[det_class]['tp'] += 1
                    gt_boxes.remove(matched_gt)
                else:
                    total_fp += 1
                    class_metrics[det_class]['fp'] += 1
            
            # 剩余未匹配的真实框为FN
            for gt in gt_boxes:
                total_fn += 1
                class_metrics[gt['class_name']]['fn'] += 1
        
        # 计算总体指标
        precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0
        recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0
        f1_score = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
        avg_confidence = total_confidence / detection_count if detection_count > 0 else 0
        
        # 计算每个类别的指标
        per_class_metrics = {}
        for class_name, metrics in class_metrics.items():
            tp = metrics['tp']
            fp = metrics['fp']
            fn = metrics['fn']
            class_precision = tp / (tp + fp) if (tp + fp) > 0 else 0
            class_recall = tp / (tp + fn) if (tp + fn) > 0 else 0
            class_f1 = 2 * class_precision * class_recall / (class_precision + class_recall) if (class_precision + class_recall) > 0 else 0
            class_avg_conf = metrics['total_conf'] / metrics['count'] if metrics['count'] > 0 else 0
            
            per_class_metrics[class_name] = {
                'precision': class_precision,
                'recall': class_recall,
                'f1_score': class_f1,
                'avg_confidence': class_avg_conf,
                'count': metrics['count']
            }
        
        return {
            'precision': precision,
            'recall': recall,
            'f1_score': f1_score,
            'confidence': avg_confidence,
            'class_metrics': per_class_metrics
        }
    
    def calculate_iou(self, box1, box2):
        """
        计算两个边界框的IoU
        box: [x1, y1, x2, y2]
        """
        xi1 = max(box1[0], box2[0])
        yi1 = max(box1[1], box2[1])
        xi2 = min(box1[2], box2[2])
        yi2 = min(box1[3], box2[3])
        
        inter_area = max(0, xi2 - xi1) * max(0, yi2 - yi1)
        
        box1_area = (box1[2] - box1[0]) * (box1[3] - box1[1])
        box2_area = (box2[2] - box2[0]) * (box2[3] - box2[1])
        
        union_area = box1_area + box2_area - inter_area
        
        return inter_area / union_area if union_area > 0 else 0

    def on_epoch_end(self, epoch, model_eval):
        if epoch % self.period == 0 and self.eval_flag:
            self.net = model_eval
            if not os.path.exists(self.map_out_path):
                os.makedirs(self.map_out_path)
            if not os.path.exists(os.path.join(self.map_out_path, "ground-truth")):
                os.makedirs(os.path.join(self.map_out_path, "ground-truth"))
            if not os.path.exists(os.path.join(self.map_out_path, "detection-results")):
                os.makedirs(os.path.join(self.map_out_path, "detection-results"))
            
            for annotation_line in tqdm(self.val_lines, desc="Getting map", disable=not self.verbose):
                line        = annotation_line.split()
                image_id    = os.path.basename(line[0]).split('.')[0]
                image       = Image.open(line[0])
                gt_boxes    = np.array([np.array(list(map(int,box.split(',')))) for box in line[1:]])
                self.get_map_txt(image_id, image, self.class_names, self.map_out_path)
                
                with open(os.path.join(self.map_out_path, "ground-truth/"+image_id+".txt"), "w") as new_f:
                    for box in gt_boxes:
                        left, top, right, bottom, obj = box
                        obj_name = self.class_names[obj]
                        new_f.write("%s %s %s %s %s\n" % (obj_name, left, top, right, bottom))
                        
            try:
                temp_map = get_coco_map(class_names = self.class_names, path = self.map_out_path)[1]
            except:
                temp_map = get_map(self.MINOVERLAP, False, path = self.map_out_path)
            self.maps.append(temp_map)
            self.epoches.append(epoch)

            with open(os.path.join(self.log_dir, "epoch_map.txt"), 'a') as f:
                f.write(str(temp_map))
                f.write("\n")
            
            plt.figure()
            plt.plot(self.epoches, self.maps, 'red', linewidth = 2, label='train map')

            plt.grid(True)
            plt.xlabel('Epoch')
            plt.ylabel('Map %s'%str(self.MINOVERLAP))
            plt.title('A Map Curve')
            plt.legend(loc="upper right")

            plt.savefig(os.path.join(self.log_dir, "epoch_map.png"))
            plt.cla()
            plt.close("all")

            # 计算并存储详细评估指标
            try:
                self.metrics = self.calculate_metrics(self.map_out_path)
                self.metrics['mAP'] = temp_map
            except Exception as e:
                self.metrics = {}

            try:
                shutil.rmtree(self.map_out_path)
            except PermissionError:
                pass  # 临时文件被占用时跳过清理，不影响训练