#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""VLM 辅助自动标注 → YOLO 数据集

设计原则 (基于 2026-10-20 实测, 不是猜):
  ① 本地 SmolVLM 的 yes/no **不可作判据** —— 纯黑对照图问「有缺陷吗」答 yes,
     问「缺陷在哪」答 RIGHT; 纯灰图把 LEFT/TOP/CENTER/BOTTOM/RIGHT/DENT 全列一遍。
     ⇒ VLM 只做**区域提议/描述**, 绝不做通过/不通过决策。
  ② 几何量 (边界框) 必须由 CV 给出: 缺陷形态是「凸凹不平」⇒ 局部 std 的 MAD-z 峰值,
     配形态学闭运算成块, 面积闸 ≥ 1.5% ROI。
  ③ VLM 与 CV 不一致 ⇒ 该样本标 pending, 交人工, 不进训练集 (避免垃圾进垃圾出)。

用法:
  python tools/vlm_auto_label.py --src <图片目录> --out <数据集目录> [--vlm] [--min-area 0.015]
产出:
  <out>/images/{train,val}/*.jpg   <out>/labels/{train,val}/*.txt
  <out>/dataset.yaml               <out>/auto_label_report.json
"""
import argparse
import json
import os
import random
import sys
import time

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 缺陷类别 (YOLO class 0)
CLASSES = ['defect']
Q_POS = ('Look at this optical module surface. If there is a defect, answer ONLY its location: '
         'LEFT, RIGHT, TOP, BOTTOM, CENTER, or NONE. One word only.')
REGION_MAP = {'LEFT': 'left', 'RIGHT': 'right', 'TOP': 'top',
              'BOTTOM': 'bottom', 'CENTER': 'center', 'NONE': 'none'}


# ────────────────────────── CV 通道 ──────────────────────────
def waviness_mask(gray, min_area_frac=0.015, max_area_frac=0.30, z_thr=2.5, k=31):
    """凸凹检测: 局部 std 的稳健 z 分数 (MAD 归一), 返回框列表 [(x,y,w,h,score)]

    2026-10-20 实测三条防误报闸 (不加时框会覆盖整图乃至超出边界, 覆盖率 104%):
      ① 上限 max_area_frac=0.30: 缺陷是局部斑块, 覆盖 >30% 的「检测」必然是背景/过曝整块
      ② 过曝区剔除: 灰≥250 的像素周围不算凸凹 (死白没有纹理, std 假高)
      ③ 框夹到图像内: 形态学膨胀后连通域可能超出 ROI
    """
    f = gray.astype(np.float32)
    mean = cv2.blur(f, (k, k))
    sq = cv2.blur(f * f, (k, k))
    std = np.sqrt(np.maximum(sq - mean * mean, 0))
    med = float(np.median(std))
    mad = float(np.median(np.abs(std - med))) + 1e-6
    z = (std - med) / (1.4826 * mad)

    # ② 过曝区(死白)不参与: 那里没有可辨纹理, 局部 std 高但没有信息
    blown = (gray >= 250).astype(np.uint8)
    if blown.any():
        blown = cv2.dilate(blown, np.ones((15, 15), np.uint8), iterations=2)
        z = np.where(blown > 0, 0.0, z)

    m = (z > z_thr).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)

    h, w = gray.shape[:2]
    area_min = h * w * min_area_frac
    area_max = h * w * max_area_frac          # ① 上限
    out = []
    for i in range(1, n):
        x, y, bw, bh, area = (st[i, cv2.CC_STAT_LEFT], st[i, cv2.CC_STAT_TOP],
                              st[i, cv2.CC_STAT_WIDTH], st[i, cv2.CC_STAT_HEIGHT],
                              st[i, cv2.CC_STAT_AREA])
        # ① 上限必须用**外接矩形面积**卡, 不能用 CC_STAT_AREA(实际像素数):
        #   环形/L 形连通域的像素数可能只占 5%, 外接矩形却盖满整图
        #   (实测 surf04 单框覆盖 100% 而 area 闸没拦住, 就是这个错)
        if bw * bh < area_min or bw * bh > area_max:
            continue
        # ③ 夹到图像内
        x2, y2 = min(x + bw, w), min(y + bh, h)
        x, y = max(0, x), max(0, y)
        bw, bh = x2 - x, y2 - y
        if bw < 2 or bh < 2:
            continue
        sub = z[y:y + bh, x:x + bw]
        out.append((int(x), int(y), int(bw), int(bh), float(sub.max()) if sub.size else 0.0))
    out.sort(key=lambda r: -r[4])
    return out


def region_of_box(x, y, w, h, W, H):
    """框中心落在哪个区 (与 VLM 的词汇对齐)"""
    cx, cy = x + w / 2.0, y + h / 2.0
    if 0.33 <= cx / W <= 0.67 and 0.33 <= cy / H <= 0.67:
        return 'center'
    if cx / W < 0.33:
        return 'left'
    if cx / W > 0.67:
        return 'right'
    return 'top' if cy / H < 0.5 else 'bottom'


# ────────────────────────── VLM 通道 ──────────────────────────
class VLMProposer:
    """只用来提供区域先验, 不判有无"""

    def __init__(self, model_dir):
        import torch
        from transformers import AutoProcessor
        try:
            from transformers import AutoModelForImageTextToText as _M
        except ImportError:
            from transformers import AutoModelForVision2Seq as _M  # type: ignore
        self.torch = torch
        self.proc = AutoProcessor.from_pretrained(model_dir, trust_remote_code=True)
        self.model = _M.from_pretrained(model_dir, torch_dtype=torch.float16,
                                        device_map='cuda', trust_remote_code=True).eval()
        self.ok = True

    def propose(self, bgr):
        from PIL import Image
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        conv = [{"role": "user", "content": [{"type": "image"},
                                            {"type": "text", "text": Q_POS}]}]
        prompt = self.proc.apply_chat_template(conv, add_generation_prompt=True)
        inp = self.proc(text=prompt, images=[Image.fromarray(rgb)],
                        return_tensors='pt').to('cuda', dtype=self.torch.float16)
        with self.torch.no_grad():
            out = self.model.generate(**inp, max_new_tokens=20, do_sample=False)
        n = inp['input_ids'].shape[1]
        ans = self.proc.batch_decode(out[:, n:], skip_special_tokens=True)[0].strip().upper()
        for k, v in REGION_MAP.items():
            if k in ans:
                return v, ans[:40]
        return 'unknown', ans[:40]


# ────────────────────────── 主流程 ──────────────────────────
def to_yolo(boxes, W, H):
    lines = []
    for x, y, w, h, _s in boxes:
        cx, cy = (x + w / 2.0) / W, (y + h / 2.0) / H
        lines.append('0 %.6f %.6f %.6f %.6f' % (cx, cy, w / float(W), h / float(H)))
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--vlm', action='store_true', help='启用 VLM 区域先验 (默认关: 实测不可靠)')
    ap.add_argument('--vlm-model', default=os.path.join(ROOT, 'zmax_data/models/l5_vlm_merged_20261009_231339'))
    ap.add_argument('--min-area', type=float, default=0.015)
    ap.add_argument('--val-frac', type=float, default=0.2)
    ap.add_argument('--seed', type=int, default=0)
    a = ap.parse_args()

    files = sorted(f for f in os.listdir(a.src)
                   if f.lower().endswith(('.png', '.jpg', '.jpeg')))
    if not files:
        print('源目录没有图片: %s' % a.src)
        return 2

    for sub in ('images/train', 'images/val', 'labels/train', 'labels/val'):
        os.makedirs(os.path.join(a.out, sub), exist_ok=True)

    vlm = None
    if a.vlm:
        print('加载 VLM (仅作区域先验) ...', flush=True)
        try:
            vlm = VLMProposer(a.vlm_model)
        except Exception as e:
            print('  VLM 加载失败, 退回纯 CV: %s' % str(e)[:100], flush=True)
            vlm = None

    random.Random(a.seed).shuffle(files)
    n_val = max(1, int(round(len(files) * a.val_frac))) if len(files) > 4 else 0

    rec = {'src': a.src, 'n_src': len(files), 'min_area': a.min_area,
           'vlm_enabled': bool(vlm), 'items': [], 't0': time.strftime('%Y-%m-%dT%H:%M:%S')}
    stat = {'pos': 0, 'neg': 0, 'pending': 0, 'boxes': 0, 'vlm_agree': 0, 'vlm_disagree': 0}

    for i, f in enumerate(files):
        p = os.path.join(a.src, f)
        im = cv2.imread(p)
        if im is None:
            continue
        gray = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
        H, W = gray.shape[:2]
        boxes = waviness_mask(gray, a.min_area)

        vlm_region, vlm_raw = 'n/a', ''
        if vlm is not None:
            try:
                vlm_region, vlm_raw = vlm.propose(im)
            except Exception as e:
                vlm_region, vlm_raw = 'error', str(e)[:60]

        status = 'auto'
        if boxes:
            stat['pos'] += 1
            stat['boxes'] += len(boxes)
            if vlm is not None and vlm_region not in ('n/a', 'unknown', 'error', 'none'):
                cv_regions = {region_of_box(b[0], b[1], b[2], b[3], W, H) for b in boxes}
                if vlm_region in cv_regions:
                    stat['vlm_agree'] += 1
                else:
                    stat['vlm_disagree'] += 1
                    status = 'pending'      # 两通道冲突 ⇒ 交人工
        else:
            stat['neg'] += 1
        if status == 'pending':
            stat['pending'] += 1

        split = 'val' if i < n_val else 'train'
        base = os.path.splitext(f)[0]
        cv2.imwrite(os.path.join(a.out, 'images', split, base + '.jpg'), im,
                    [cv2.IMWRITE_JPEG_QUALITY, 92])
        with open(os.path.join(a.out, 'labels', split, base + '.txt'), 'w') as fh:
            if status == 'auto':
                fh.write('\n'.join(to_yolo(boxes, W, H)))

        rec['items'].append({'file': f, 'split': split, 'status': status,
                             'n_boxes': len(boxes), 'vlm_region': vlm_region,
                             'vlm_raw': vlm_raw,
                             'boxes': [[int(v) for v in b[:4]] for b in boxes]})
        if (i + 1) % 20 == 0:
            print('  已处理 %d/%d' % (i + 1, len(files)), flush=True)

    with open(os.path.join(a.out, 'dataset.yaml'), 'w') as fh:
        fh.write('path: %s\ntrain: images/train\nval: images/val\nnames:\n  0: %s\n'
                 % (os.path.abspath(a.out), CLASSES[0]))

    rec['stat'] = stat
    with open(os.path.join(a.out, 'auto_label_report.json'), 'w') as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=1)

    print('\n=== 自动标注完成 ===')
    print('  源图 %d 张 → 正样本 %d / 负样本 %d / 待人工 %d · 框 %d'
          % (len(files), stat['pos'], stat['neg'], stat['pending'], stat['boxes']))
    if vlm is not None:
        print('  VLM-CV 一致 %d / 冲突 %d' % (stat['vlm_agree'], stat['vlm_disagree']))
    print('  数据集: %s' % a.out)
    print('  报告  : %s' % os.path.join(a.out, 'auto_label_report.json'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
