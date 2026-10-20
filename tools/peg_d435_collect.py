#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""peg_d435_collect.py — 采集 **D435(本机 USB RealSense)** 视角的帧, 供「D435 专用检测头」训练用。

背景(老倪 2026-10-20 选 B): 「单独给 D435 视角训一个检测头(现权重在 D435 上 0 检出), 只能给 2D 框」。
现役 `models/yolo_peg_live.pt` 是在**腕相机(D405)**视角/尺度上训的, 到 D435 上几乎检不出;
但腕相机与 D435 看的是**同一个光模块**(只是侧面) ⇒ D435 这条链路要自己的检测权重。

采集口径(每条都可复核):
  · 源: `http://127.0.0.1:8797/snap/rs.jpg`(AR 服务代理 → rs_service 单进程独占 D435), 只读, 不抢设备
  · 去重: md5 相同丢弃; 相邻帧平均绝对差 < --min-diff 也丢弃(静止帧对训练没用)
  · 每帧同时落: 时间戳 / 深度统计(/api/rs_info) / 当时 TCP 真值(zmax_data/tcp_out/latest.json)
    —— 位姿留着, 将来要做「D435 外参」时这批数据能直接复用(现在是 B 路线, 位姿只作元数据)
  · 落盘: <out>/raw/<ts_ms>.jpg + <out>/meta.jsonl (一行一帧)

用法:
  gui-venv311/bin/python tools/peg_d435_collect.py --n 600 --period 0.6
  gui-venv311/bin/python tools/peg_d435_collect.py --n 0        # 0=不停, 直到 SIGTERM
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import sys
import time
import urllib.request

import cv2
import numpy as np

ROOT = "/home/ubuntu/zmax"
SNAP = "http://127.0.0.1:8797/snap/rs.jpg"
INFO = "http://127.0.0.1:8797/api/rs_info"
TCP = os.path.join(ROOT, "zmax_data", "tcp_out", "latest.json")

_STOP = {"v": False}


def _get(url, timeout=8.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.read()


def _get_json(url, timeout=6.0):
    try:
        return json.loads(_get(url, timeout).decode("utf-8", "ignore"))
    except Exception as e:                                                      # noqa: BLE001
        return {"ok": False, "err": "%s: %s" % (type(e).__name__, e)}


def _tcp_pose():
    try:
        with open(TCP, encoding="utf-8") as f:
            d = json.load(f)
        return {"pos": d.get("pos") or d.get("position"), "ts": d.get("ts"), "age_s": d.get("age_s")}
    except Exception as e:                                                      # noqa: BLE001
        return {"err": "%s: %s" % (type(e).__name__, e)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "zmax_data/datasets/peg_d435"))
    ap.add_argument("--n", type=int, default=600, help="帧数上限, 0=不停")
    ap.add_argument("--period", type=float, default=0.6, help="采样周期 s")
    ap.add_argument("--min-diff", type=float, default=0.6, help="相邻帧平均绝对差下限(灰阶)")
    ap.add_argument("--max-age", type=float, default=1.5, help="帧龄上限 s, 超过当次丢弃")
    a = ap.parse_args()

    raw = os.path.join(a.out, "raw")
    os.makedirs(raw, exist_ok=True)
    meta_p = os.path.join(a.out, "meta.jsonl")

    def _sig(*_):
        _STOP["v"] = True
    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)

    seen = set()
    prev = None
    kept = dropped = 0
    t0 = time.time()
    print("[collect] 目标 %s 帧 · 周期 %.2fs · 输出 %s" % (a.n or "无限", a.period, a.out), flush=True)

    while not _STOP["v"]:
        try:
            raw_b = _get(SNAP)
        except Exception as e:                                                  # noqa: BLE001
            print("[collect] 取帧失败 %r" % (e,), flush=True)
            time.sleep(a.period)
            continue
        md5 = hashlib.md5(raw_b).hexdigest()
        im = cv2.imdecode(np.frombuffer(raw_b, np.uint8), cv2.IMREAD_COLOR)
        if im is None:
            print("[collect] 解码失败 bytes=%d" % len(raw_b), flush=True)
            time.sleep(a.period)
            continue
        g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
        info = _get_json(INFO)
        age = info.get("age_s")
        diff = None if prev is None else float(np.abs(g.astype(np.int16) - prev).mean())
        if md5 in seen:
            dropped += 1
            time.sleep(a.period)
            continue
        if diff is not None and diff < a.min_diff:
            dropped += 1
            time.sleep(a.period)
            continue
        if isinstance(age, (int, float)) and age > a.max_age:
            dropped += 1
            time.sleep(a.period)
            continue
        ts = time.time()
        name = "%d.jpg" % int(ts * 1000)
        cv2.imwrite(os.path.join(raw, name), im)
        rec = {"file": name, "ts": ts, "md5": md5, "bytes": len(raw_b),
               "w": im.shape[1], "h": im.shape[0], "mean": round(float(g.mean()), 2),
               "diff_prev": None if diff is None else round(diff, 3),
               "rs": {"frames": info.get("frames"), "age_s": age,
                      "depth": info.get("depth")},
               "tcp": _tcp_pose()}
        with open(meta_p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        seen.add(md5)
        prev = g
        kept += 1
        if kept % 25 == 0:
            print("[collect] 已收 %d 帧 (丢 %d) · %.0fs" % (kept, dropped, time.time() - t0), flush=True)
        if a.n and kept >= a.n:
            break
        time.sleep(a.period)

    print("[collect] 结束: 收 %d 帧 · 丢 %d · 用时 %.0fs" % (kept, dropped, time.time() - t0), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
