#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""det_src.py — 检测输入帧源唯一真源 (真机帧 ⇄ AR 渲染帧), 两个消费者共用。

老倪 2026-10-29: 「在 550A 上运行的时候, 需要接到渲染后的图像给 YOLO; 550C 是可以看到真机器人的,
但 550A 是在仿真的 AR 上运行的。能切换么?」⇒ 帧源与权重必须成对切换, 且同一份配置对两条链生效:
  · AR 页 (8797) 光模块 3D 框  —— tcp_ar_server._mod3_worker
  · 状态空间 L2 感知节点        —— tools/ss_engine_loop.py --pipe-img / ZMAX_L2_WEIGHTS

口径 (改这里就同时改两处, 不要在各服务里各写一份):
  real   : 真机相机帧  http://127.0.0.1:8791/snap/arm.jpg   权重 models/yolo_peg_live.pt  (D405 腕相机域)
  render : AR 工位渲染帧 http://127.0.0.1:8802/frame.png      权重 models/yolo_ar_peg.pt    (AR 渲染域)
  auto   : 真机帧可取且不陈旧 ⇒ real, 否则 render
"""
from __future__ import annotations

import json
import os
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_FILE = os.path.join(REPO, "zmax_data", "runtime", "det_src.json")

MAP = {
    "real": {"frame_url": "http://127.0.0.1:8791/snap/arm.jpg",
             "weights": "models/yolo_peg_live.pt",
             "why": "真机臂相机原始帧 (D405 视角) ⇒ 真机域权重"},
    "render": {"frame_url": "http://127.0.0.1:8802/frame.png",
               "weights": "models/yolo_ar_peg.pt",
               "why": "AR 工位场景渲染帧 (ArMujocoEnv 960x720) ⇒ AR 渲染域权重"},
}


def want() -> str:
    """配置里要什么: auto|real|render (不判在线)。env 优先, 其次真源文件。"""
    e = (os.environ.get("ZMAX_DET_SRC") or "").strip().lower()
    if e in ("real", "render", "auto"):
        return e
    try:
        with open(SRC_FILE, encoding="utf-8") as f:
            s = str((json.load(f) or {}).get("src") or "auto").strip().lower()
        return s if s in ("real", "render", "auto") else "auto"
    except Exception:                                                       # noqa: BLE001
        return "auto"


def _fetch(url: str, timeout: float = 3.0) -> bytes:
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.read()
    except Exception:                                                       # noqa: BLE001
        return b""


def real_available() -> bool:
    """真机帧真能取到真 JPEG 才算可用 (只看"有配置"会误判)。"""
    b = _fetch(MAP["real"]["frame_url"])
    return bool(b) and b[:2] == b"\xff\xd8" and len(b) > 2000


def resolve(probe: bool = True) -> dict:
    """返回 {src, frame_url, weights, weights_abs, why, ts, probed}。src 可能是 auto 解析后的实际值。"""
    w = want()
    src = w
    probed = False
    if w == "auto" and probe:
        probed = True
        src = "real" if real_available() else "render"
    elif w == "auto":
        src = "render"          # 不探测时给确定性默认, 不让调用方猜
    m = MAP[src]
    wp = m["weights"]
    return {"want": w, "src": src, "frame_url": m["frame_url"],
            "weights": os.path.basename(wp),
            "weights_abs": wp if os.path.isabs(wp) else os.path.join(REPO, wp),
            "why": m["why"], "ts": time.time(), "probed": probed,
            "src_file": SRC_FILE}


def set_src(src: str) -> dict:
    src = str(src or "").strip().lower()
    if src not in ("auto", "real", "render"):
        return {"ok": False, "err": "src 只能是 auto|real|render"}
    os.makedirs(os.path.dirname(SRC_FILE), exist_ok=True)
    tmp = SRC_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"src": src, "ts": time.time(),
                   "at": time.strftime("%Y-%m-%d %H:%M:%S")}, f)
    os.replace(tmp, SRC_FILE)
    return {"ok": True, "src": src, "path": SRC_FILE}


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        print(json.dumps(set_src(sys.argv[1]), ensure_ascii=False))
    print(json.dumps(resolve(), ensure_ascii=False, indent=1))
