# -*- coding: utf-8 -*-
"""
FP 系列三级递进检测 Pipeline
Level 1: YOLO 全图检测 area 父区域 (Signal_area / Power_area)
Level 2: 每个 area 子图内用 PaddleOCR 定位文字区域 (VPL/CPL/PWR),
         OCR 在后台 worker 线程异步刷新 (缓存 20 帧), 主循环永不阻塞
Level 3: OCR 文字正下方延伸 OCR 区域 (PWR=100px, VPL/CPL=80px) →
         在全图检出的 LED_H/LED_L 子类框中筛选中心落在 OCR 区域内的候选,
         仅由 YOLO 类别判定亮灭 (LED_H=ON, LED_L=OFF), 不使用 HSV
标注框使用 EMA 滤波平滑显示; 预览右侧拼接亮灭统计折线图 (亮/灭时间累计)
最后输出 CSV + 带彩色三级框的可视化预览/视频

Usage:
    python detect/fp_cascade_pipeline.py --image ml/datasets/FP/JPEGImages/frame_000001.jpg
    python detect/fp_cascade_pipeline.py --video FP00.mp4 --no_show --max_frames 30

注：本脚本为早期 4 类实验 pipeline（YOLO 4 类 + OCR 分级），已非主线架构
（主线为 5 类 YOLO + TinyConv 二分类），保留仅供历史复现。
"""
import argparse
import os
import sys
import time
import csv
from pathlib import Path
import copy
import threading
from collections import deque

import cv2
import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont

# ------------------------------------------------------------
# 项目/模型根路径
# ------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]          # d:\Aging
ML_ROOT = PROJECT_ROOT / 'ml'                                # 模型/训练代码根
ROOT = str(ML_ROOT)                                          # 兼容旧变量名
sys.path.insert(0, ROOT)

from model.YOLOV8 import YoloBody
from utils.utils_bbox import DecodeBox
from utils.utils import get_classes


# ============================================================
# 常量 & 阈值（来自工程记忆 ablations）
# ============================================================
# 4 类: 0=Power_area  1=Signal_area  2=LED_H  3=LED_L
CLASSES_FP = ['Power_area', 'Signal_area', 'LED_H', 'LED_L']
AREA_CLASSES = {'Power_area', 'Signal_area'}
LED_H_CLS, LED_L_CLS = 2, 3

# Level 1 area 检测置信度 (area 很大, 置信度通常很高)
AREA_CONF = 0.30
# Level 3 YOLO LED 子类识别置信度 (低阈值保召回, 用 OCR 区域几何约束过滤)
LED_CONF_YOLO = 0.05
# area 帧间稳定性 (解决相邻 area 框交替检测/闪烁):
AREA_IOU_MERGE = 0.30    # 同 class 高重叠(嵌套/相邻)的 area 框合并阈值
AREA_MATCH_DIST = 120    # 帧间 area 追踪: 中心距离阈值 (px)
AREA_LOST_FRAMES = 5     # area 连续消失多少帧后移除 (防抖)
# OCR 区域: 从 OCR 文字顶部向下延伸的高度 (像素), 该区域即 LED 亮灭判断区域
#   PWR 的 LED 离文字更远, 保持 100px; VPL/CPL 用 80px
OCR_REGION_DY = 80
PWR_OCR_REGION_DY = 100
# OCR 结果缓存刷新间隔 (帧): 机位固定时文字位置几乎不变, 间隔内复用 OCR 结果
OCR_REFRESH_FRAMES = 20
# 标注框 EMA 滤波系数 (0~1, 越小越平滑): 缓解框逐帧抖动/刷新跳变
SMOOTH_ALPHA = 0.45
# 亮灭统计折线图: 展示最近 STAT_WINDOW 帧 (约 2 秒 @30fps)
STAT_WINDOW = 60
# 统计面板宽度 (px), 拼接在预览图右侧
STAT_PANEL_W = 430

# OCR 文字下方 → LED 偏移量 (基于真值LED与OCR匹配的中位数校准, 见 calib2.py)
#  CPL:  LED_DY=22  (文字底边 → LED 中心)  尺寸 70x37
#  VPL:  LED_DY=21                              75x38
#  PWR:  LED_DY=29                              48x39
# 简化取值: VPL/CPL 用 70x38 LED_DY=22; PWR 用 50x40 LED_DY=30
LED_DY_SIG = 22   # VPL/CPL
LED_DY_PWR = 30   # PWR
LED_W, LED_H = 70, 38
PWR_W, PWR_H = 50, 40

# OCR 目标词白名单 (只检测 VPL / CPL / PWR)
OCR_TARGETS = {'VPL', 'CPL', 'PWR'}
PWR_WORDS = {'PWR'}
SIG_LED_BELOW_WORDS = {'VPL', 'CPL'}

# 颜色: 三级递进 (画面只保留 area / OCR区域 / LED 三个框)
COLOR_AREA = (0, 255, 0)        # 绿: area 父区域
COLOR_OCR = (255, 140, 0)      # 橙: OCR 区域 (文字顶部向下延伸)
COLOR_LED_ON = (0, 0, 255)     # 红: LED 亮
COLOR_LED_OFF = (180, 180, 180)# 灰: LED 灭
COLOR_UNCERTAIN = (0, 255, 255)# 黄: 不确定


# ============================================================
# Level 2: OCR 文字检测与识别
# ============================================================
class OCRDetector:
    """PaddleOCR 轻量封装, 只保留目标词, 输出 (word, x1,y1,x2,y2, conf)

    后台线程化: submit() 异步提交任务, 由 worker 线程处理, 不阻塞主推理循环,
    解决每 OCR_REFRESH_FRAMES 帧刷新一次时产生的周期性卡顿。
    """

    def __init__(self, on_result=None):
        """
        on_result: callable(frame_no, area_idx, area_name, ocr_list, offset)
            后台 OCR 完成后回调 (ocr_list 坐标相对 area 裁剪图, offset=(dx,dy) 用于平移到全图)
        """
        try:
            from paddleocr import PaddleOCR
            self.ocr = PaddleOCR(
                use_textline_orientation=True,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                text_detection_model_name='PP-OCRv5_mobile_det',
                text_recognition_model_name='PP-OCRv5_mobile_rec',
            )
            self.ok = True
        except Exception as e:
            print(f'[WARN] PaddleOCR 不可用: {e}. Level 2 将跳过 OCR, 仅用 YOLO LED 检测.')
            self.ok = False

        self._on_result = on_result
        self._stop = False
        self._pending = None
        self._cv = threading.Condition()
        self._ocr_lock = threading.Lock()  # PaddleOCR 非线程安全, 串行化 detect()
        self._thread = threading.Thread(target=self._worker, daemon=True, name='ocr-worker')
        self._thread.start()

    def submit(self, frame_no, area_idx, area_name, img_bgr, offset=(0, 0)):
        """异步提交 OCR 任务 (不阻塞); 若已有未完成任务则覆盖为最新"""
        if not self.ok:
            return
        with self._cv:
            self._pending = (frame_no, area_idx, area_name, img_bgr, tuple(offset))
            self._cv.notify()

    def _worker(self):
        while not self._stop:
            with self._cv:
                while self._pending is None and not self._stop:
                    self._cv.wait(timeout=0.2)
                if self._stop:
                    break
                task = self._pending
                self._pending = None
            if task is None:
                continue
            frame_no, area_idx, area_name, img_bgr, offset = task
            try:
                ocr_list = self.detect(img_bgr, target_words=OCR_TARGETS)
            except Exception:
                ocr_list = []
            if self._on_result:
                try:
                    self._on_result(frame_no, area_idx, area_name, ocr_list, offset)
                except Exception:
                    pass

    def close(self):
        self._stop = True
        with self._cv:
            self._cv.notify_all()

    def detect(self, img_bgr, target_words=None):
        """
        img_bgr: BGR numpy
        target_words: set of str, None 表示返回全部
        返回: list of dict: {text, conf, box_xyxy(相对输入img_bgr的坐标)}
        """
        if not self.ok:
            return []
        try:
            with self._ocr_lock:
                result = self.ocr.ocr(img_bgr)
        except Exception as e:
            print(f'[WARN] OCR 异常: {e}')
            return []
        if not result:
            return []
        # 兼容 PaddleOCR 新老版本格式, 使用 annotate_fp_led.py 通用解析
        parsed = []
        for page in result:
            if page is None:
                continue
            j = page.json if hasattr(page, 'json') else (page if isinstance(page, dict) else {})
            res = j.get('res', j) if isinstance(j, dict) else {}
            if not isinstance(res, dict):
                continue
            texts = res.get('rec_texts', [])
            polys = res.get('dt_polys', [])
            confs = res.get('rec_scores', [])
            for i, (t, poly) in enumerate(zip(texts, polys)):
                poly_list = poly.tolist() if hasattr(poly, 'tolist') else list(poly)
                c = float(confs[i]) if i < len(confs) else 0.9
                parsed.append((str(t), poly_list, c))
        # 老版本格式兜底: result[0][[poly, [text, conf]], ...]
        if not parsed and isinstance(result, (list, tuple)):
            for page in result:
                if page is None:
                    continue
                if isinstance(page, (list, tuple)) and len(page) > 0:
                    for line in page:
                        try:
                            poly = line[0]
                            tc = line[1]
                            if isinstance(tc, (list, tuple)) and len(tc) >= 2:
                                t, c = tc[0], float(tc[1])
                            elif isinstance(tc, str):
                                t, c = tc, 0.9
                            else:
                                continue
                            poly_list = poly.tolist() if hasattr(poly, 'tolist') else list(poly)
                            parsed.append((str(t), poly_list, float(c)))
                        except Exception:
                            continue

        outs = []
        for text, poly, conf in parsed:
            xs = [p[0] for p in poly]
            ys = [p[1] for p in poly]
            x1, x2 = int(min(xs)), int(max(xs))
            y1, y2 = int(min(ys)), int(max(ys))
            if target_words:
                hit = None
                if text in target_words:
                    hit = text
                else:
                    for t in target_words:
                        if t in text or text.strip() == t.strip():
                            hit = t
                            break
                if hit is None:
                    continue
                text = hit
            outs.append({'text': text, 'conf': float(conf),
                         'box_xyxy': (x1, y1, x2, y2)})
        return outs


# ============================================================
# Level 3: LED 亮灭判定 (纯 YOLO LED_H/LED_L + 几何最近邻匹配)
# ============================================================
def _expected_led_center(text, ox1g, oy1g, ox2g, oy2g):
    """由 OCR 文字框 计算 LED 期望中心坐标 (校准偏移, 纯几何)
    返回 (exp_cx, exp_cy, lw, lh) 期望中心 + 框尺寸
    """
    ocx = (ox1g + ox2g) // 2
    oby = oy2g  # 文字底边
    if text in PWR_WORDS:
        lw, lh, ld = PWR_W, PWR_H, LED_DY_PWR
    else:
        lw, lh, ld = LED_W, LED_H, LED_DY_SIG
    exp_cx = ocx
    exp_cy = oby + ld  # 文字底边 + 偏移 → LED 期望中心
    return exp_cx, exp_cy, lw, lh


def _iou(a, b):
    """两个框的 IoU; 输入可为 (name, x1,y1,x2,y2, conf) 或纯 (x1,y1,x2,y2)"""
    ax1, ay1, ax2, ay2 = a[-4], a[-3], a[-2], a[-1]
    bx1, by1, bx2, by2 = b[-4], b[-3], b[-2], b[-1]
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    ua = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / ua if ua > 0 else 0.0


# ============================================================
# 三级递进核心类
# ============================================================
class FPCascadeDetector:
    def __init__(self,
                 model_path=os.path.join(ROOT, 'weights/FP/last_epoch_weights.pth'),
                 classes_path=os.path.join(ROOT, 'datasets/FP/label.txt'),
                 input_shape=(640, 640),
                 phi='n',
                 cuda=True,
                 confidence=AREA_CONF,
                 nms_iou=0.45):
        self.class_names, self.num_classes = get_classes(classes_path)
        assert len(self.class_names) == len(CLASSES_FP), \
            f'类别数不匹配: label={self.class_names}, expect={CLASSES_FP}'
        self.input_shape = list(input_shape)
        self.confidence = confidence
        self.nms_iou = nms_iou
        self.device = torch.device('cuda' if cuda and torch.cuda.is_available() else 'cpu')
        print(f'设备: {self.device}')

        # ---- Level1 + Level3 共用 YOLO ----
        yolo = YoloBody(self.input_shape, self.num_classes, phi, pretrained=False)
        state = torch.load(model_path, map_location=self.device, weights_only=False)
        if isinstance(state, dict) and 'model' in state:
            yolo.load_state_dict(state['model'])
        else:
            yolo.load_state_dict(state)
        self.yolo = yolo.to(self.device).eval()
        self.decodebox = DecodeBox(num_classes=self.num_classes, input_shape=self.input_shape)

        # Level 2 OCR (后台线程, 结果通过 on_result 回调写缓存, 主循环不阻塞)
        self.ocr = OCRDetector(on_result=self._on_ocr_result)

        # OCR 结果缓存 (固定机位场景下加速实时预览)
        self._frame_no = 0
        self._ocr_cache = {}       # area_key -> (frame_no, ocr_list)  由 worker 线程写
        self._cache_lock = threading.Lock()
        self._ema = {}             # 标注框 EMA 平滑状态 {key: (x1,y1,x2,y2)}
        self._tracked_areas = []   # area 帧间追踪 {key, name, box, missing}
        self._area_key_seq = 0

        # 亮灭统计 (run_video 使用): 最近 STAT_WINDOW 帧状态历史 + 每槽累计亮/灭帧数
        self.stat_history = deque(maxlen=STAT_WINDOW)
        self.stat_cnt = {}         # slot -> {'ON': n, 'OFF': n}

    # --------------------------------------------------------
    # OCR 后台回调: worker 线程完成后更新缓存 (带锁)
    # --------------------------------------------------------
    def _on_ocr_result(self, frame_no, area_idx, area_name, ocr_list, offset):
        dx, dy = offset
        for o in ocr_list:
            ox1, oy1, ox2, oy2 = o['box_xyxy']
            o['box_xyxy_g'] = (ox1 + dx, oy1 + dy, ox2 + dx, oy2 + dy)
            o['area_idx'] = area_idx
            o['area_name'] = area_name
        with self._cache_lock:
            # 帧号用写缓存时刻 (而非提交时刻): 保证刷新节流按主循环帧数计算,
            # 不受 worker 处理延迟影响, 避免每帧都触发刷新
            self._ocr_cache[area_idx] = (self._frame_no, ocr_list)

    # --------------------------------------------------------
    # 标注框 EMA 滤波 (平滑显示)
    # --------------------------------------------------------
    def _smooth_box(self, key, box):
        """EMA 平滑框坐标; box=(x1,y1,x2,y2); 返回平滑后 tuple"""
        prev = self._ema.get(key)
        if prev is None:
            self._ema[key] = box
            return box
        s = tuple(round(a * SMOOTH_ALPHA + b * (1 - SMOOTH_ALPHA)) for a, b in zip(box, prev))
        self._ema[key] = s
        return s

    def _record_stat(self, frame_states):
        """记录一帧所有槽位的亮灭状态 (供统计折线图/亮灭时长统计)
        frame_states: {slot: state, ...}
        """
        self.stat_history.append(dict(frame_states))
        for slot, state in frame_states.items():
            c = self.stat_cnt.setdefault(slot, {'ON': 0, 'OFF': 0})
            if state in ('ON', 'OFF'):
                c[state] += 1

    # --------------------------------------------------------
    # 通用: 单次 YOLO 检测, 返回 [(x1,y1,x2,y2,conf,cls_id), ...] (xyxy左上右下, 原图坐标)
    # input_shape 可传小尺寸 (如 Level 3 ROI 子图), 提升小图推理帧率
    # --------------------------------------------------------
    def _detect_raw(self, img_pil, conf_override=None, nms_override=None, input_shape=None):
        conf = conf_override if conf_override is not None else self.confidence
        nms  = nms_override if nms_override is not None else self.nms_iou
        in_shape = list(input_shape if input_shape is not None else self.input_shape)
        iw, ih = img_pil.size
        image_shape = np.array([ih, iw])

        scale = min(in_shape[0] / ih, in_shape[1] / iw)
        nw, nh = int(iw * scale), int(ih * scale)
        resized = img_pil.resize((nw, nh), Image.BICUBIC)
        canvas = Image.new('RGB', in_shape, (128, 128, 128))
        canvas.paste(resized, ((in_shape[1] - nw) // 2, (in_shape[0] - nh) // 2))
        arr = np.array(canvas, dtype='float32') / 255.0
        arr = np.transpose(arr, (2, 0, 1))[None]
        images = torch.from_numpy(arr).to(self.device)

        with torch.no_grad():
            outputs = self.yolo.forward(images)
            results = self.decodebox.decode_box(outputs)
            results = self.decodebox.non_max_suppression(
                results, self.num_classes, input_shape=in_shape,
                image_shape=image_shape, letterbox_image=True,
                conf_thres=conf, nms_thres=nms)

        if results[0] is None:
            return []
        out = []
        top_label = np.array(results[0][:, 5], dtype='int32')
        top_conf  = results[0][:, 4]
        top_boxes = results[0][:, :4]
        for i in range(len(top_label)):
            # DecodeBox 输出是 (y1,x1,y2,x2), 必须按此顺序解包
            y1, x1, y2, x2 = top_boxes[i]
            out.append((float(x1), float(y1), float(x2), float(y2),
                        float(top_conf[i]), int(top_label[i])))
        return out

    # --------------------------------------------------------
    # 单帧三级递进推理
    # --------------------------------------------------------
    def process_frame(self, img_bgr, debug_draw=True):
        """
        img_bgr: BGR 图像 (1280x720)
        返回: led_results [每个 LED 一条], vis_bgr (带框彩图, 可选)
        led_results: list of dict:
            slot / text / ocr_box / led_box_xyxy / state / method / v95 / yolo_conf
        """
        H, W = img_bgr.shape[:2]
        self._frame_no += 1
        img_pil = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))

        # ==================== Level 1: 全图 YOLO 检测 ====================
        #   一次低阈值推理同时取 area 与 LED_H/LED_L 子类:
        #   - area 超大框, 用 AREA_CONF 收紧;
        #   - LED 小目标置信度低(0.1~0.2), 必须用低阈值召回;
        #   - 注意 LED 子类识别必须保持训练尺度(640), 不能对 ROI 放大检测(模型尺度敏感)
        dets_all = self._detect_raw(img_pil, conf_override=LED_CONF_YOLO)

        # area 候选: 低阈值召回后按 AREA_CONF 收紧
        area_raw = []
        for x1, y1, x2, y2, conf, cls_ in dets_all:
            name = self.class_names[cls_]
            if name in AREA_CLASSES and conf >= AREA_CONF:
                area_raw.append((name, int(x1), int(y1), int(x2), int(y2), float(conf)))

        # (a) 同 class 高重叠 area 框合并 (同一物理区域被检测出多个相邻/嵌套框时只保留置信度高者)
        area_raw.sort(key=lambda a: a[5], reverse=True)
        area_dedup = []
        for a in area_raw:
            if not any(_iou(a, k) > AREA_IOU_MERGE for k in area_dedup):
                area_dedup.append(a)

        # (b) 帧间追踪: 中心距离关联到上一帧 area, 保持 key/EMA 状态稳定,
        #     解决相邻 area 框逐帧交替检测导致的闪烁; 消失的 area 防抖保留 AREA_LOST_FRAMES 帧
        old_tracked = list(self._tracked_areas)
        used = [False] * len(old_tracked)
        new_entries = []
        areas = []  # list of (key, name, x1,y1,x2,y2, conf)
        for a in area_dedup:
            name, ax1, ay1, ax2, ay2, conf = a
            acx, acy = (ax1 + ax2) // 2, (ay1 + ay2) // 2
            best_i, best_d = -1, AREA_MATCH_DIST ** 2
            for i, t in enumerate(old_tracked):
                if used[i] or t['name'] != name:
                    continue
                tcx = (t['box'][0] + t['box'][2]) // 2
                tcy = (t['box'][1] + t['box'][3]) // 2
                d = (acx - tcx) ** 2 + (acy - tcy) ** 2
                if d < best_d:
                    best_d, best_i = d, i
            if best_i >= 0:
                t = old_tracked[best_i]
                used[best_i] = True
                t['missing'] = 0
                sb = self._smooth_box(f'area:{t["key"]}', (ax1, ay1, ax2, ay2))
                t['box'] = sb
                areas.append((t['key'], name, sb[0], sb[1], sb[2], sb[3], conf))
            else:
                key = self._area_key_seq
                self._area_key_seq += 1
                sb = self._smooth_box(f'area:{key}', (ax1, ay1, ax2, ay2))
                new_entries.append({'key': key, 'name': name, 'box': sb, 'missing': 0})
                areas.append((key, name, sb[0], sb[1], sb[2], sb[3], conf))

        # (c) 未匹配的旧 area: 防抖期间继续用旧框参与检测; 超时则移除并清理缓存/EMA
        removed = []
        for i, t in enumerate(old_tracked):
            if used[i]:
                continue
            t['missing'] += 1
            if t['missing'] <= AREA_LOST_FRAMES:
                areas.append((t['key'], t['name'], t['box'][0], t['box'][1],
                              t['box'][2], t['box'][3], 0.0))
            else:
                removed.append(i)
        # 用快照重建追踪列表 (迭代期间不修改, 避免索引错位)
        self._tracked_areas = [t for i, t in enumerate(old_tracked)
                               if i not in removed] + new_entries
        for i in sorted(removed, reverse=True):
            key = old_tracked[i]['key']
            with self._cache_lock:
                self._ocr_cache.pop(key, None)
            self._ema.pop(f'area:{key}', None)

        # 按 (y,x) 排序保证处理顺序稳定 (缓存 key 已由追踪稳定, 不依赖排序索引)
        areas.sort(key=lambda a: (a[3], a[2]))

        # LED_H/LED_L 子类框 (低阈值召回), 去重: 同一中心 25px 内取置信度高者
        led_raw = [(cls_, int(x1), int(y1), int(x2), int(y2), float(conf))
                   for x1, y1, x2, y2, conf, cls_ in dets_all
                   if cls_ in (LED_H_CLS, LED_L_CLS)]
        led_yolo = []
        led_raw.sort(key=lambda r: r[5], reverse=True)
        for r in led_raw:
            cls_, x1, y1, x2, y2, conf = r
            cx = (x1 + x2) // 2; cy = (y1 + y2) // 2
            dup = False
            for s in led_yolo:
                if abs(cx - (s[1]+s[3])//2) < 25 and abs(cy - (s[2]+s[4])//2) < 25:
                    dup = True; break
            if not dup:
                led_yolo.append((cls_, x1, y1, x2, y2, conf))

        # -------------------- 可视化底图: Level 1 area 框 (已 EMA 平滑) --------------------
        vis = None
        if debug_draw:
            vis = img_bgr.copy()
            for idx, (area_key, name, ax1, ay1, ax2, ay2, cconf) in enumerate(areas):
                cv2.rectangle(vis, (ax1, ay1), (ax2, ay2), COLOR_AREA, 2)
                cv2.putText(vis, f'{idx+1}.{name}', (ax1+4, ay1+20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.42, COLOR_AREA, 1)

        led_results = []
        # 记录 led_yolo 中已被某个槽占用的框, 保证一个 LED 只归属一个槽
        led_used = [False] * len(led_yolo)
        # 同一目标(slot)只标注一次, 防止相邻/重叠 area 都识别出同一文字导致重复标注
        slots_seen = set()

        for area_key, area_name, ax1, ay1, ax2, ay2, aconf in areas:
            cx1, cy1 = max(0, ax1), max(0, ay1)
            cx2, cy2 = min(W, ax2), min(H, ay2)

            # ==================== Level 2: area 内 OCR 文字定位 ====================
            #   后台线程异步刷新 (OCR_REFRESH_FRAMES 帧间隔), 主循环永不等待 OCR, 消除周期性卡顿
            with self._cache_lock:
                cache = self._ocr_cache.get(area_key)
            if cache is not None and self._frame_no - cache[0] < OCR_REFRESH_FRAMES:
                # 缓存有效: 直接复用
                ocr_list = copy.deepcopy(cache[1])
                for o in ocr_list:
                    o['area_idx'] = area_key
                    o['area_name'] = area_name
            elif cache is not None:
                # 缓存过期: 本帧继续用旧结果, 同时后台提交刷新任务 (不阻塞)
                ocr_list = copy.deepcopy(cache[1])
                for o in ocr_list:
                    o['area_idx'] = area_key
                    o['area_name'] = area_name
                area_crop_bgr = img_bgr[cy1:cy2, cx1:cx2]
                if area_crop_bgr.size > 0:
                    self.ocr.submit(self._frame_no, area_key, area_name,
                                    area_crop_bgr, offset=(cx1, cy1))
            else:
                # 无缓存 (首帧 / 新 area): 同步跑一次, 保证立即有结果
                area_crop_bgr = img_bgr[cy1:cy2, cx1:cx2]
                if area_crop_bgr.size == 0:
                    continue
                ocr_list = self.ocr.detect(area_crop_bgr, target_words=OCR_TARGETS)
                # OCR 坐标 → 全图坐标 (平移)
                for o in ocr_list:
                    ox1, oy1, ox2, oy2 = o['box_xyxy']
                    ox1g, oy1g = ox1 + cx1, oy1 + cy1
                    ox2g, oy2g = ox2 + cx1, oy2 + cy1
                    o['box_xyxy_g'] = (ox1g, oy1g, ox2g, oy2g)
                    o['area_idx'] = area_key
                    o['area_name'] = area_name
                with self._cache_lock:
                    self._ocr_cache[area_key] = (self._frame_no, copy.deepcopy(ocr_list))

            # ==================== Level 3: OCR 区域内 LED 子类识别 (仅 YOLO 亮灭判断) ====================
            for o in ocr_list:
                text = o['text']
                ox1g, oy1g, ox2g, oy2g = o['box_xyxy_g']

                # (a) OCR 区域: 从 OCR 文字顶部向下延伸 (PWR=100, VPL/CPL=80)
                #     (文字 + 下方 LED 都包含在内, 即亮灭判断区域); EMA 平滑
                region_dy = PWR_OCR_REGION_DY if text in PWR_WORDS else OCR_REGION_DY
                rx1 = max(0, ox1g)
                ry1 = max(0, oy1g)
                rx2 = min(W, ox2g)
                ry2 = min(H, oy1g + region_dy)
                rx1, ry1, rx2, ry2 = self._smooth_box(f'ocr:{area_key}:{text}',
                                                      (rx1, ry1, rx2, ry2))

                # (b) 由 OCR 文字计算 LED 期望框 (几何校准: 文字底边下方偏移)
                exp_cx, exp_cy, lw, lh = _expected_led_center(text, ox1g, oy1g, ox2g, oy2g)
                led_x1 = exp_cx - lw // 2
                led_y1 = exp_cy - lh // 2
                led_x2 = led_x1 + lw
                led_y2 = led_y1 + lh

                # (c) LED 子类识别: 在全图检出的 LED_H/LED_L 中, 只接受中心落在本
                #     OCR 区域内的框 (LED 保持训练尺度检测); 槽位互斥, 多候选取置信度最高
                best_idx, best_conf = -1, 0.0
                for i, (lcls, lx1y, ly1y, lx2y, ly2y, lcon) in enumerate(led_yolo):
                    if led_used[i]:
                        continue
                    lcx = (lx1y + lx2y) // 2
                    lcy = (ly1y + ly2y) // 2
                    if rx1 <= lcx <= rx2 and ry1 <= lcy <= ry2 and lcon > best_conf:
                        best_conf = lcon
                        best_idx = i

                # (d) 亮灭判定: 仅由 YOLO 类别决定 (LED_H=ON, LED_L=OFF); 区域内无检出 → UNCERTAIN
                if best_idx >= 0:
                    lcls, lx1y, ly1y, lx2y, ly2y, lcon = led_yolo[best_idx]
                    final_state = 'ON' if lcls == LED_H_CLS else 'OFF'
                    matched_box = (lx1y, ly1y, lx2y, ly2y)
                    yolo_conf = lcon
                    led_used[best_idx] = True
                else:
                    final_state = 'UNCERTAIN'
                    matched_box = None
                    yolo_conf = 0.0

                # 槽名: 上半区=A, 下半区=B + 文字
                region_tag = 'A' if (ay1 + ay2) // 2 < H // 2 else 'B'
                slot = f'{text}_{region_tag}' if text != 'PWR' else 'PWR'
                # 同一 slot 只保留一条 (相邻/重叠 area 可能识别出同一目标, 避免重复标注)
                if slot in slots_seen:
                    continue
                slots_seen.add(slot)

                # LED 显示框: 有检出 → EMA 平滑; 无检出 → 保持上次平滑框 (避免闪跳)
                if matched_box is not None:
                    display_x1, display_y1, display_x2, display_y2 = \
                        self._smooth_box(f'led:{slot}', matched_box)
                else:
                    prev = self._ema.get(f'led:{slot}')
                    if prev is not None:
                        display_x1, display_y1, display_x2, display_y2 = prev
                    else:
                        display_x1, display_y1, display_x2, display_y2 = \
                            led_x1, led_y1, led_x2, led_y2

                rec = {
                    'slot': slot, 'text': text,
                    'ocr_box': (rx1, ry1, rx2, ry2),
                    'led_box': (display_x1, display_y1, display_x2, display_y2),
                    'state': final_state, 'method': 'YOLO',
                    'v95': 0, 'yolo_conf': yolo_conf,
                    'area': area_name, 'area_idx': area_key,
                    'exp_led_center': (exp_cx, exp_cy),
                }
                led_results.append(rec)

                # ---------- 可视化: 只画 area / OCR区域 / LED 三个框 ----------
                if debug_draw and vis is not None:
                    # OCR 区域 (橙): 文字顶部向下延伸 OCR_REGION_DY
                    cv2.rectangle(vis, (rx1, ry1), (rx2, ry2), COLOR_OCR, 2)
                    cv2.putText(vis, text, (rx1+2, ry1+14),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.38, COLOR_OCR, 1)
                    # LED 判断框 (红=亮 / 灰=灭 / 黄=不确定)
                    color = (COLOR_LED_ON if final_state == 'ON'
                             else COLOR_LED_OFF if final_state == 'OFF'
                             else COLOR_UNCERTAIN)
                    cv2.rectangle(vis, (display_x1, display_y1),
                                  (display_x2, display_y2), color, 2)
                    cv2.putText(vis, f'{slot}:{final_state}',
                                (display_x1-8, display_y1-4),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.36, color, 1)

        return led_results, vis


# ============================================================
# CLI 入口
# ============================================================
def parse_args():
    p = argparse.ArgumentParser(description='FP Cascade Pipeline: Area → OCR → LED')
    p.add_argument('--image', type=str, default=None, help='单张图片路径')
    p.add_argument('--video', type=str, default=None, help='视频路径')
    p.add_argument('--model', type=str,
                   default=os.path.join(ROOT, 'weights/FP/last_epoch_weights.pth'),
                   help='FP 模型路径 (4 类 area+LED); 默认用最新权重 (deploy 模型是早期精确率快照, 不推荐)')
    p.add_argument('--conf', type=float, default=AREA_CONF, help='area 检测置信度')
    p.add_argument('--max_frames', type=int, default=None, help='最大处理帧数 (视频)')
    p.add_argument('--no_show', action='store_true', help='不显示预览窗口')
    p.add_argument('--save_video', type=str, default=None,
                   help='输出可视化视频路径 (默认: detect/outputs/FP_cascade/<视频名>_cascade.mp4)')
    p.add_argument('--save_csv', type=str, default=None,
                   help='输出 LED 状态 CSV 路径 (默认: detect/outputs/FP_cascade/led_states_<视频名>.csv)')
    return p.parse_args()


def ensure_dir(p):
    d = os.path.dirname(p)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)


def draw_stats_panel(img, history, per_slot, fps):
    """在图像右侧拼接 LED 亮灭统计面板 (仅预览显示, 不写入输出视频):
    - 每个槽一行, 绘制最近 STAT_WINDOW 帧的亮灭折线 (上=亮 红, 下=灭 灰, 中=不确定 黄)
    - 右侧显示累计 亮/灭 时间 (秒)
    返回拼接后的整图
    """
    H, W = img.shape[:2]
    panel = np.full((H, STAT_PANEL_W, 3), 28, dtype=np.uint8)
    cv2.putText(panel, 'LED state', (10, 26), cv2.FONT_HERSHEY_SIMPLEX,
                0.7, (255, 255, 255), 2)
    cv2.putText(panel, f'last {len(history)/max(fps,1e-6):.1f}s', (140, 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180, 180, 180), 1)

    slots = sorted(per_slot.keys())
    if not slots:
        return np.hstack([img, panel])

    top = 44
    row_h = (H - top) / len(slots)
    px0, px1 = 95, STAT_PANEL_W - 148
    hist = list(history)

    def y_of(state, y0, y1):
        if state == 'ON':
            return y1 - 6
        if state == 'OFF':
            return y0 + 6
        return (y0 + y1) // 2  # UNCERTAIN 居中

    for i, slot in enumerate(slots):
        y0 = int(top + i * row_h)
        y1 = int(top + (i + 1) * row_h)
        cv2.line(panel, (px0, y0), (px1, y0), (70, 70, 70), 1)  # 行基线
        cv2.putText(panel, slot, (8, (y0 + y1) // 2 + 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)

        # 折线: 沿时间轴逐帧连线
        n = max(1, len(hist) - 1)
        prev_x = prev_y = None
        for f in range(len(hist)):
            st = hist[f].get(slot)
            if st is None:
                continue
            x = px0 + int(f * (px1 - px0) / n)
            y = y_of(st, y0, y1)
            if prev_x is not None:
                color = ((0, 0, 255) if st == 'ON'
                         else (180, 180, 180) if st == 'OFF' else (0, 255, 255))
                cv2.line(panel, (prev_x, prev_y), (x, y), color, 2)
            prev_x, prev_y = x, y

        # 右侧累计 亮/灭 时间
        c = per_slot[slot]
        on_s = c['ON'] / max(fps, 1e-6)
        off_s = c['OFF'] / max(fps, 1e-6)
        cy = (y0 + y1) // 2
        cv2.putText(panel, f'ON {on_s:.1f}s', (px1 + 6, cy - 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
        cv2.putText(panel, f'OFF {off_s:.1f}s', (px1 + 6, cy + 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 2)

    return np.hstack([img, panel])


def run_image(args, det):
    img = cv2.imread(args.image)
    if img is None:
        print(f'[ERROR] 无法读取图片: {args.image}')
        sys.exit(1)
    t0 = time.time()
    results, vis = det.process_frame(img, debug_draw=True)
    dt = time.time() - t0
    print(f'图片: {args.image}  {img.shape[1]}x{img.shape[0]}  耗时 {dt*1000:.0f}ms')
    print(f'  检测 LED 数量: {len(results)}')
    for r in results:
        print(f'    {r["slot"]:10s}  state={r["state"]:9s}  via={r["method"]:22s}  '
              f'V95={r["v95"]:3d}  YOLO={r["yolo_conf"]:.2f}  '
              f'text={r["text"]}  area={r["area"]}')
    out_path = os.path.splitext(args.image)[0] + '_cascade.jpg'
    ensure_dir(out_path)
    cv2.imwrite(out_path, vis)
    print(f'  结果图已保存: {out_path}')
    if not args.no_show:
        cv2.imshow('FP Cascade', vis)
        cv2.waitKey(0)
        cv2.destroyAllWindows()


def run_video(args, det):
    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        print(f'[ERROR] 无法打开视频: {args.video}')
        sys.exit(1)
    fps = cap.get(cv2.CAP_PROP_FPS)
    Wv = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    Hv = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    base = os.path.splitext(os.path.basename(args.video))[0]
    out_dir = os.path.join(PROJECT_ROOT, 'detect/outputs/FP_cascade')
    os.makedirs(out_dir, exist_ok=True)
    save_video = args.save_video or os.path.join(out_dir, f'{base}_cascade.mp4')
    save_csv = args.save_csv or os.path.join(out_dir, f'led_states_{base}.csv')
    ensure_dir(save_video); ensure_dir(save_csv)

    writer = None
    if args.no_show or save_video:
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        writer = cv2.VideoWriter(save_video, fourcc, fps, (Wv, Hv))

    csv_f = open(save_csv, 'w', newline='', encoding='utf-8-sig')
    csv_w = csv.writer(csv_f)
    csv_w.writerow(['frame', 'time_s', 'slot', 'text', 'state', 'method',
                    'v95', 'yolo_conf', 'area',
                    'led_x1', 'led_y1', 'led_x2', 'led_y2'])

    paused = False
    fi = 0
    t0 = time.time()

    while True:
        if not paused:
            ok, frame = cap.read()
            if not ok:
                break
            fi += 1
            if args.max_frames and fi > args.max_frames:
                print(f'达到 --max_frames={args.max_frames}, 停止')
                break
            t_frame = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0

            led_results, vis = det.process_frame(frame, debug_draw=True)

            # 汇总 & 写入 CSV + 亮灭统计
            line_parts = []
            frame_states = {}
            for r in led_results:
                slot = r['slot']
                lx1, ly1, lx2, ly2 = r['led_box']
                csv_w.writerow([fi, f'{t_frame:.3f}', slot, r['text'], r['state'],
                                r['method'], r['v95'], f'{r["yolo_conf"]:.3f}',
                                r['area'], lx1, ly1, lx2, ly2])
                line_parts.append(f'{slot}:{r["state"]}')
                frame_states[slot] = r['state']
            det._record_stat(frame_states)

            # 左上角帧信息 (单行, 保持画面干净)
            if vis is not None:
                info = f'frame {fi}/{total or "?"}  t={t_frame:.2f}s  LED={len(led_results)}'
                cv2.putText(vis, info, (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                            0.75, (255, 255, 255), 2)

            print(f'[{fi:5d}] t={t_frame:.2f}s  {"  ".join(line_parts)}')

            if writer is not None:
                writer.write(vis)
            if not args.no_show:
                # 预览: 拼接右侧亮灭统计折线图面板
                vis_show = draw_stats_panel(vis, det.stat_history, det.stat_cnt, fps)
                cv2.imshow('FP Cascade (q退出 s截图 空格暂停)', vis_show)
                k = cv2.waitKey(1) & 0xFF
                if k == ord('q'):
                    break
                elif k == ord(' '):
                    paused = not paused
                elif k == ord('s'):
                    sp = os.path.join(out_dir, f'{base}_frame_{fi:06d}.jpg')
                    cv2.imwrite(sp, vis); print(f'[截图] {sp}')
        else:
            # 暂停
            if not args.no_show:
                k = cv2.waitKey(20) & 0xFF
                if k == ord(' '):
                    paused = not paused
                elif k == ord('q'):
                    break

    cap.release()
    det.ocr.close()  # 停止 OCR 后台 worker 线程
    if writer is not None:
        writer.release()
    csv_f.close()
    if not args.no_show:
        cv2.destroyAllWindows()
    dt = time.time() - t0
    print(f'\n处理完成: {fi} 帧, 耗时 {dt:.1f}s, 平均 {fi/max(dt,1e-6):.0f} fps')
    print(f'状态日志: {save_csv}')
    if save_video:
        print(f'可视化视频: {save_video}')
    # 汇总统计
    print()
    print(f'===== {base}  总帧={fi} =====')
    # 从 CSV 重新读入统计
    from collections import Counter, defaultdict
    per_slot = defaultdict(Counter)
    with open(save_csv, 'r', encoding='utf-8-sig') as f:
        r = csv.DictReader(f)
        for row in r:
            per_slot[row['slot']][row['state']] += 1
    for s in sorted(per_slot.keys()):
        cc = per_slot[s]
        on = cc.get('ON', 0); off = cc.get('OFF', 0)
        un = cc.get('UNCERTAIN', 0)
        tot = on + off + un
        print(f'  {s:8s}  ON={on:4d}  OFF={off:4d}  UNCERTAIN={un:4d}  其他={tot-on-off-un}  槽帧={tot}')


if __name__ == '__main__':
    args = parse_args()
    if not args.image and not args.video:
        print('[ERROR] 必须指定 --image 或 --video')
        sys.exit(1)
    det = FPCascadeDetector(model_path=args.model, confidence=args.conf)
    if args.image:
        run_image(args, det)
    else:
        run_video(args, det)
