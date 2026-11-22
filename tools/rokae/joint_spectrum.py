#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""joint_spectrum.py —— 实测关节速度频谱: 定位"还在抖"到底是哪一段频率、哪一根关节。

数据来源: arm_rt_stream2.py 在 ZMAX_RT_MEAS=1 时落的 meas_*.jsonl
          (每 ~5ms 一次 r.jointPos(), 同时记下当拍下发的指令 c)

它回答三个问题:
  ① 抖动在哪个频段(命令台阶 ~100Hz? 滤波器 20Hz? 机械共振 5~30Hz?)  —— 每关节 PSD 峰
  ② 是"跟随指令抖"还是"指令平滑、实测自己在抖"                        —— 指令/实测两条谱对比
  ③ 哪根关节最脏                                                       —— 各关节带内能量排序

用法:
  ./gui-venv311/bin/python tools/rokae/joint_spectrum.py zmax_data/rokae_sdk/logs/meas_XXX.jsonl
"""
from __future__ import annotations

import json
import math
import sys

import numpy as np

BANDS = [(0.5, 5.0), (5.0, 20.0), (20.0, 50.0), (50.0, 100.0), (100.0, 200.0)]


def load(path):
    ts, qs, cs = [], [], []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:                                    # noqa: BLE001
                continue
            ts.append(float(d["t"]))
            qs.append([float(v) for v in d["q"]])
            cs.append([float(v) for v in d.get("c") or d["q"]])
    return np.array(ts), np.array(qs), np.array(cs)


def uniform(ts, x, fs=400.0):
    t0 = ts[0]
    n = int((ts[-1] - t0) * fs) + 1
    g = t0 + np.arange(n) / fs
    out = np.empty((n, x.shape[1]))
    for c in range(x.shape[1]):
        out[:, c] = np.interp(g, ts, x[:, c])
    return g, out, fs


def welch(x, fs, seg=1024):
    x = x - np.mean(x)
    if len(x) < seg:
        seg = max(64, 2 ** int(math.log2(max(64, len(x)))))
    w = np.hanning(seg)
    step = seg // 2
    psd = np.zeros(seg // 2 + 1)
    k = 0
    for i in range(0, len(x) - seg + 1, step):
        seg_x = x[i:i + seg] * w
        sp = np.fft.rfft(seg_x)
        psd += (sp.real ** 2 + sp.imag ** 2)
        k += 1
    if k == 0:
        return np.zeros(1), np.zeros(1)
    psd /= k
    psd *= 2.0 / (fs * np.sum(w ** 2))
    fr = np.fft.rfftfreq(seg, 1.0 / fs)
    return fr, np.sqrt(psd)          # 幅度谱密度 (deg/s/√Hz)


def report(tag, ts, x, fs=400.0):
    g, xu, fs = uniform(ts, x, fs)
    v = np.gradient(xu, axis=0) * fs
    v = np.degrees(v)
    print("\n=== %s (样本 %d, 有效采样率 %.0f Hz, 时长 %.1fs) ===" % (tag, len(ts), 1.0 / np.median(np.diff(ts)), ts[-1] - ts[0]))
    rows = []
    for c in range(v.shape[1]):
        fr, amp = welch(v[:, c], fs)
        m = fr >= 0.5
        fr2, a2 = fr[m], amp[m]
        if len(a2) == 0:
            continue
        pk = int(np.argmax(a2))
        band_e = []
        for lo, hi in BANDS:
            msk = (fr2 >= lo) & (fr2 < hi)
            band_e.append(float(np.sqrt(np.sum(a2[msk] ** 2))))
        rows.append((c + 1, fr2[pk], a2[pk], band_e, float(np.std(v[:, c]))))
    print("关节  峰值频率  峰值幅度      RMS     0.5-5   5-20   20-50  50-100 100-200 (°/s)")
    for c, f0, a0, be, rms in rows:
        print(" J%d   %6.1fHz  %7.4f  %7.3f  " % (c, f0, a0, rms)
              + "  ".join("%6.3f" % e for e in be))
    return rows


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = sys.argv[1]
    ts, q, cmd = load(path)
    if len(ts) < 50:
        print("样本太少: %d" % len(ts))
        return 2
    dt = np.diff(ts)
    print("文件 %s\n采样 %d 点 · 中位间隔 %.2f ms (≈%.0f Hz) · 抖动 P95 %.2f ms · 时长 %.1f s"
          % (path, len(ts), np.median(dt) * 1000, 1.0 / np.median(dt), np.percentile(dt, 95) * 1000, ts[-1] - ts[0]))
    rep = report("实测关节位置(微分得速度)", ts, q)
    report("下发指令(同口径)", ts, cmd)

    # 指令台阶指纹: 与上一拍完全相同的比例(慢放时重复取同一表项)
    cd = np.max(np.abs(np.diff(cmd, axis=0)), axis=1)
    rep = float(np.mean(cd < 1e-9)) * 100
    md = np.max(np.abs(np.diff(q, axis=0)), axis=1)
    print("\n指令「停一下再跳」比例 %.1f%% · 实测同口径 %.1f%%" % (rep, float(np.mean(md < 1e-9)) * 100))
    return 0


if __name__ == "__main__":
    sys.exit(main())
