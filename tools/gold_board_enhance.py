#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""金手指整板 RAW 图增强 —— 让 2448x2048 整板看得清

origin 是相机 RAW 输出(无软件增益): mean 72、死白 15.8%、清晰度 22.8。
judge/topview 是它经 gain=0.8039 + gamma 压过的 900x332 条带(清晰度 196)。

本脚本做四步(全部无损/可复现):
  ① 死白掩膜: 灰>=250 的像素**已经饱和, 信息不可恢复** —— 明确标出来, 不假装能救
  ② CLAHE 局部对比度均衡 (clip=2.0, tile=8): 拉回暗部细节, 不让亮的更亮
  ③ 反光抑制: 对高亮区做 rolloff(不是硬裁), 压掉镀金层镜面反光
  ④ 非锐化掩模锐化: 提齿边缘轮廓

不改变几何、不 resize、不裁剪 —— 判据口径零影响。
"""
import os
import sys
import time

import cv2
import numpy as np

ROOT = '/home/ubuntu/zmax'
OUT = os.path.join(ROOT, 'data/deliver')


def enhance(bgr, clip=2.0, tile=8, rolloff_hi=200, sharpen=0.6):
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    blown = gray >= 250

    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)

    # ② CLAHE 只作用在 L 通道
    clahe = cv2.createCLAHE(clipLimit=clip, tileGridSize=(tile, tile))
    l2 = clahe.apply(l)

    # ③ 高亮 rolloff: 把 >=rolloff_hi 的区间压到 rolloff_hi..255 的 70% 位置, 保住层次
    lf = l2.astype(np.float32)
    hi = lf >= rolloff_hi
    lf[hi] = rolloff_hi + (lf[hi] - rolloff_hi) * 0.70
    l2 = np.clip(lf, 0, 255).astype(np.uint8)

    # ④ 非锐化掩模
    if sharpen > 0:
        blur = cv2.GaussianBlur(l2, (0, 0), 1.2)
        l2 = cv2.addWeighted(l2, 1.0 + sharpen, blur, -sharpen, 0)

    out = cv2.cvtColor(cv2.merge([l2, a, b]), cv2.COLOR_LAB2BGR)
    return out, blown


def metrics(g):
    return {'mean': round(float(g.mean()), 1), 'p90': int(np.percentile(g, 90)),
            'blown_pct': round(float((g >= 250).mean() * 100), 2),
            'sharp': round(float(cv2.Laplacian(g, cv2.CV_64F).var()), 1)}


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else None
    if not src or not os.path.exists(src):
        cand = sorted([f for f in os.listdir(OUT) if f.startswith('goldfinger_board_')])
        if not cand:
            print('找不到整板图, 请指定路径')
            return 2
        src = os.path.join(OUT, cand[-1])
    bgr = cv2.imread(src)
    if bgr is None:
        print('读图失败: %s' % src)
        return 2
    ts = time.strftime('%Y%m%d_%H%M%S')
    base = os.path.splitext(os.path.basename(src))[0]

    g0 = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    m0 = metrics(g0)

    enh, blown = enhance(bgr)
    g1 = cv2.cvtColor(enh, cv2.COLOR_BGR2GRAY)
    m1 = metrics(g1)

    p_enh = os.path.join(OUT, 'goldfinger_board_enhanced_%s.jpg' % ts)
    cv2.imwrite(p_enh, enh, [cv2.IMWRITE_JPEG_QUALITY, 96])

    # 死白掩膜可视化 (红色标出不可恢复区)
    vis = enh.copy()
    vis[blown] = (0, 0, 255)
    p_blown = os.path.join(OUT, 'goldfinger_board_blownmask_%s.jpg' % ts)
    cv2.imwrite(p_blown, vis, [cv2.IMWRITE_JPEG_QUALITY, 92])

    print('源图  : %s' % src)
    print('  mean=%s p90=%s 死白=%s%% 清晰度=%s' % (m0['mean'], m0['p90'], m0['blown_pct'], m0['sharp']))
    print('增强后: %s' % p_enh)
    print('  mean=%s p90=%s 死白=%s%% 清晰度=%s' % (m1['mean'], m1['p90'], m1['blown_pct'], m1['sharp']))
    print('清晰度提升: %.1fx' % (m1['sharp'] / max(m0['sharp'], 1e-6)))
    print('不可恢复死白掩膜: %s (红=像素已饱和 250+, 信息真丢了)' % p_blown)
    return 0


if __name__ == '__main__':
    sys.exit(main())
