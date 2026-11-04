#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bench_torch_550a.py — 550A(4060) 上的真实算力实测: YOLO / SmolVLM 视觉塔 / Qwen2.5-VL

只报实测: 每个组件 warmup + N 次计时, 报 mean/p50/p95; 显存峰值一并记。
按大→小顺序加载并在测完后释放, 避免 8GB 显存被两模型同时占住 (实测会 OOM)。
"""
from __future__ import annotations

import gc
import json
import os
import statistics
import sys
import time

import numpy as np

ROOT = os.environ.get("ZMAX_ROOT", os.path.expanduser("~/zmax"))
OUT = os.path.join(ROOT, "reports/compute/bench_550a_gpu.json")
REP: dict = {"host": "550A", "ts": time.strftime("%F %T"), "components": {}}


def _stat(ts):
    ts = sorted(ts)
    return {"n": len(ts), "mean_ms": round(statistics.mean(ts), 3),
            "p50_ms": round(statistics.median(ts), 3),
            "p95_ms": round(ts[max(0, int(len(ts) * 0.95) - 1)], 3),
            "max_ms": round(ts[-1], 3)}


def _gpu_mb():
    try:
        import torch
        return round(torch.cuda.max_memory_allocated() / 2**20, 1), round(torch.cuda.max_memory_reserved() / 2**20, 1)
    except Exception:                                                       # noqa: BLE001
        return None, None


def bench_yolo(n=15):
    import torch                                                          # noqa: PLC0415
    from ultralytics import YOLO                                          # noqa: PLC0415
    from PIL import Image                                                 # noqa: PLC0415
    w = os.path.join(ROOT, "models/yolo_peg_live.pt")
    if not os.path.isfile(w):
        return {"ok": False, "why": "缺 %s" % w}
    m = YOLO(w)
    img = Image.fromarray((np.random.default_rng(0).random((720, 1280, 3)) * 255).astype(np.uint8))
    for _ in range(3):
        m.predict(img, imgsz=640, verbose=False, device=0)
    ts = []
    for _ in range(n):
        t = time.perf_counter()
        m.predict(img, imgsz=640, verbose=False, device=0)
        ts.append((time.perf_counter() - t) * 1e3)
    torch.cuda.synchronize()
    r = _stat(ts)
    r.update({"ok": True, "device": "cuda:0 (RTX 4060)", "weights": os.path.relpath(w, ROOT),
              "imgsz": 640, "gpu_mb": _gpu_mb()})
    return r


def bench_smolvlm(n=8):
    import torch                                                          # noqa: PLC0415
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from lerobot.manifold.encoder_vlm import VLMVisionEncoder             # noqa: PLC0415
    enc = VLMVisionEncoder()
    ok, why = enc.available()
    if not ok:
        return {"ok": False, "why": why[:200]}
    frame = (np.random.default_rng(0).random((480, 640, 3)) * 255).astype(np.uint8)
    z = enc.encode(frame)
    for _ in range(2):
        enc.encode(frame)
    ts = []
    for _ in range(n):
        torch.cuda.synchronize()
        t = time.perf_counter()
        enc.encode(frame)
        torch.cuda.synchronize()
        ts.append((time.perf_counter() - t) * 1e3)
    r = _stat(ts)
    r.update({"ok": True, "device": str(enc._device), "feature_dim": int(np.asarray(z).size),
              "model": enc.mid.split("/")[-1], "gpu_mb": _gpu_mb(),
              "note": "L4 潜表示上游: 帧→768 维通用视觉特征"})
    return r


def bench_qwen(n=3):
    import torch                                                          # noqa: PLC0415
    from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration  # noqa: PLC0415
    from PIL import Image                                                 # noqa: PLC0415
    mid = "Qwen/Qwen2.5-VL-3B-Instruct"
    t0 = time.perf_counter()
    proc = AutoProcessor.from_pretrained(mid)
    m = Qwen2_5_VLForConditionalGeneration.from_pretrained(mid, dtype=torch.bfloat16).eval().cuda()
    load_s = time.perf_counter() - t0
    img = Image.fromarray((np.random.default_rng(0).random((480, 640, 3)) * 255).astype(np.uint8))
    msgs = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": "用一句话说明画面里有什么。"}]}]
    prompt = proc.apply_chat_template(msgs, add_generation_prompt=True)
    inp = proc(text=[prompt], images=[img], return_tensors="pt").to("cuda")
    ts = []
    for _ in range(n):
        torch.cuda.synchronize()
        t = time.perf_counter()
        with torch.no_grad():
            m.generate(**inp, max_new_tokens=24, do_sample=False)
        torch.cuda.synchronize()
        ts.append((time.perf_counter() - t) * 1e3)
    r = _stat(ts)
    r.update({"ok": True, "device": "cuda:0 (RTX 4060)", "load_s": round(load_s, 1),
              "params_b": round(sum(p.numel() for p in m.parameters()) / 1e9, 2),
              "max_new_tokens": 24, "gpu_mb": _gpu_mb(),
              "note": "L5 场景理解: 端到端 (含图像编码+解码 24 token)"})
    del m
    gc.collect()
    torch.cuda.empty_cache()
    return r


def bench_manifold(n=300):
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from lerobot.manifold.manifold_engine import ManifoldEngine           # noqa: PLC0415
    ck = os.path.join(ROOT, "models/manifold_engine.npz")
    eng = ManifoldEngine(manifold_type="su2", latent_dim=16, state_dim=55)
    loaded = bool(eng.load(ck)) if os.path.isfile(ck) else False
    rng = np.random.default_rng(0)
    if not loaded:
        eng.encoder.fit(rng.standard_normal((128, 55)))
    eng.goal_point = eng.project(np.zeros(55))["p"]
    x = rng.standard_normal(55) * 0.3
    for _ in range(30):
        eng.step(x, dt=0.1)
    ts = []
    for _ in range(n):
        t = time.perf_counter()
        eng.step(x, dt=0.1)
        ts.append((time.perf_counter() - t) * 1e3)
    r = _stat(ts)
    r.update({"ok": True, "device": "CPU(numpy)", "state_dim": 55})
    return r


if __name__ == "__main__":
    try:
        import torch
        if torch.cuda.is_available():
            REP["gpu"] = torch.cuda.get_device_name(0)
            torch.cuda.reset_peak_memory_stats()
    except Exception as e:                                                  # noqa: BLE001
        REP["gpu"] = "no torch: %s" % e
    for name, fn in (("yolo_det@gpu", bench_yolo), ("manifold_engine@CPU", bench_manifold),
                     ("smolvlm_vit@gpu", bench_smolvlm), ("qwen25vl3b@gpu", bench_qwen)):
        try:
            REP["components"][name] = fn()
        except Exception as e:                                              # noqa: BLE001
            REP["components"][name] = {"ok": False, "why": "%s: %s" % (type(e).__name__, str(e)[:200])}
        gc.collect()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(REP, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({k: (v.get("mean_ms") if v.get("ok") else v.get("why"))
                      for k, v in REP["components"].items()}, ensure_ascii=False, indent=1))
    print("===>", OUT)
