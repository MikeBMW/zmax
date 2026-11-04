#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bench_compute.py — 在本机实测各模型的真实算力消耗 (只报实测, 不报论文值)

覆盖: YOLO(检测) · SAM3 编码器 · INTACT 编码/预测 · 流形引擎(numpy 规则计算) · 动作头(MLP)
设备: OpenVINO 可用则按 NPU/GPU/CPU 各测一遍; 没有 OpenVINO 就只测 CPU(numpy/torch)。
口径:
  · 每个组件先 warmup 再计时, 报 mean/p50/p95/max (ms) 与 吞吐
  · FLOPs 是**估算**(参数量×2×token/像素), 明确标注 est.; 实测延迟才是判据
  · 每个组件写明 device / 输入形状 / 权重文件, 读不到权重就记 N/A + 原因 (不猜)
用法:
  python tools/bench_compute.py --root ~/zmax --out reports/compute/bench_$(hostname).json
  python tools/bench_compute.py --devices NPU,GPU,CPU --repeat 20
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import statistics
import sys
import time

import numpy as np

ROOT = os.environ.get("ZMAX_ROOT", os.path.expanduser("~/zmax"))


def _stat(ts):
    ts = sorted(ts)
    return {"n": len(ts), "mean_ms": round(statistics.mean(ts), 3),
            "p50_ms": round(statistics.median(ts), 3),
            "p95_ms": round(ts[max(0, int(len(ts) * 0.95) - 1)], 3),
            "max_ms": round(ts[-1], 3),
            "hz": round(1000.0 / statistics.mean(ts), 1) if statistics.mean(ts) > 0 else None}


def bench_ov(model_path, device, repeat=20, warmup=3, inputs=None, imgsz=None):
    """用 OpenVINO 编译并计时; 返回 dict。读不到就返回 {ok: False, why}。"""
    try:
        import openvino as ov
    except Exception as e:                                                   # noqa: BLE001
        return {"ok": False, "why": "no openvino: %s" % e}
    if not os.path.isfile(model_path):
        return {"ok": False, "why": "缺权重 %s" % os.path.relpath(model_path, ROOT)}
    try:
        core = ov.Core()
        if device not in core.available_devices:
            return {"ok": False, "why": "设备不可用 %s (有: %s)" % (device, core.available_devices)}
        t0 = time.perf_counter()
        model = core.read_model(model_path)
        cm = core.compile_model(model, device)
        compile_ms = (time.perf_counter() - t0) * 1e3
        req = cm.create_infer_request()
        # 输入形状: 按模型第一输入, 未知维用 imgsz 或 1 填
        shapes = {}
        for i, inp in enumerate(cm.inputs):
            ps = inp.get_partial_shape()
            dims = []
            for d in ps:
                if d.is_dynamic:
                    dims.append(imgsz or 1)
                else:
                    dims.append(int(d.get_length()))
            shapes[inp.get_any_name()] = dims
        feeds = {}
        rng = np.random.default_rng(0)
        for name, dims in shapes.items():
            dt = np.float32
            feeds[name] = rng.standard_normal(dims).astype(dt)
        for _ in range(warmup):
            req.infer(feeds)
        ts = []
        for _ in range(repeat):
            t = time.perf_counter()
            req.infer(feeds)
            ts.append((time.perf_counter() - t) * 1e3)
        out = _stat(ts)
        out.update({"ok": True, "device": device, "compile_ms": round(compile_ms, 1),
                    "inputs": shapes, "model": os.path.relpath(model_path, ROOT),
                    "size_mb": round(os.path.getsize(model_path) / 1e6, 1)})
        return out
    except Exception as e:                                                   # noqa: BLE001
        return {"ok": False, "why": "%s: %s" % (type(e).__name__, str(e)[:160]), "device": device}


def bench_manifold(repeat=200):
    """流形引擎一步 (numpy 规则计算): 编码→投影→梯度流→导航→解码。"""
    ManifoldEngine = None
    try:                                                                     # 正常 (550A)
        sys.path.insert(0, os.path.join(ROOT, "src"))
        from lerobot.manifold.manifold_engine import ManifoldEngine          # noqa: PLC0415
    except Exception as _e:                                                  # 端侧 (包依赖缺失)
        try:
            import importlib.util                                            # noqa: PLC0415
            _f = os.path.join(ROOT, "src/lerobot/manifold/manifold_engine.py")
            _sp = importlib.util.spec_from_file_location("manifold_engine_standalone", _f)
            _m = importlib.util.module_from_spec(_sp)
            sys.modules[_sp.name] = _m
            _sp.loader.exec_module(_m)
            ManifoldEngine = _m.ManifoldEngine
        except Exception as e2:                                              # noqa: BLE001
            return {"ok": False, "why": "import 失败: %s / %s" % (type(_e).__name__, str(e2)[:100])}
    ck = None
    for c in (os.path.join(ROOT, "models/manifold_engine.npz"),
              os.path.join(ROOT, "zmax_data/models/manifold_engine.npz"),
              os.path.join(ROOT, "external/lerobot-smolvla-lew/models/manifold_engine.npz")):
        if os.path.isfile(c):
            ck = c
            break
    eng = ManifoldEngine(manifold_type="su2", latent_dim=16, state_dim=55)
    loaded = bool(eng.load(ck)) if ck else False
    rng = np.random.default_rng(0)
    if not loaded:
        eng.encoder.fit(rng.standard_normal((128, 55)))
    eng.goal_point = eng.project(np.zeros(55))["p"]
    x = rng.standard_normal(55) * 0.3
    # 引擎每步会写 homeostasis 快照; 端侧机上该目录可能是空树 ⇒ 先建目录, 写不了就跳过写盘继续计时
    try:
        for _d in ("zmax_data/ss_live", os.path.join(ROOT, "zmax_data/ss_live")):
            os.makedirs(_d, exist_ok=True)
    except Exception:                                                        # noqa: BLE001
        pass
    ts = []
    try:
        for _ in range(20):
            eng.step(x, dt=0.1)
        for _ in range(repeat):
            t = time.perf_counter()
            eng.step(x, dt=0.1)
            ts.append((time.perf_counter() - t) * 1e3)
    except Exception as e:                                                   # noqa: BLE001
        return {"ok": False, "why": "%s: %s" % (type(e).__name__, str(e)[:140])}
    out = _stat(ts)
    out.update({"ok": True, "device": "CPU(numpy)", "calib": os.path.basename(ck) if loaded else "fit-on-the-fly",
                "state_dim": 55, "latent_dim": int(eng.encoder.latent_dim)})
    return out


def bench_mlp(repeat=300):
    """动作头/前馈 MLP (左脑) — 实测单次前向。"""
    p = None
    for c in (os.path.join(ROOT, "models/ss_left_brain.npz"),
              os.path.join(ROOT, "zmax_data/models/ss_left_brain.npz")):
        if os.path.isfile(c):
            p = c
            break
    if not p:
        return {"ok": False, "why": "缺 models/ss_left_brain.npz"}
    d = np.load(p, allow_pickle=True)
    # npz 里 W 的遍历顺序不保证是层顺序 ⇒ 必须按名字里的数字排序, 否则矩阵维度对不上 (踩过)
    def _ln(k):
        import re
        m = re.findall(r"\d+", k)
        return int(m[0]) if m else 0
    Ws = sorted([(k, d[k]) for k in d.files if k.startswith("W") and d[k].ndim == 2],
                key=lambda kv: _ln(kv[0]))
    Bs = {k.replace("b", "B", 1): d[k] for k in d.files if k.lower().startswith("b") and d[k].ndim == 1}
    if not Ws:
        return {"ok": False, "why": "npz 内没有 W* 权重 (keys=%s)" % list(d.files)[:6]}
    # 权重按 (out, in) 存 ⇒ 输入维是 shape[1] (按 shape[0] 取会得到 512, 直接维度对不上)
    x = np.random.default_rng(0).standard_normal(Ws[0][1].shape[1])
    # 权重是 (out, in) 存储 ⇒ 用时必须转置; 输入/输出还有归一化 (sm/ss, am/astd)
    sm = np.asarray(d["sm"], float) if "sm" in d.files else np.zeros(Ws[0][1].shape[1])
    ss = np.asarray(d["ss"], float) if "ss" in d.files else np.ones(Ws[0][1].shape[1])
    am = np.asarray(d["am"], float) if "am" in d.files else None
    astd = np.asarray(d["astd"], float) if "astd" in d.files else None

    def fwd():
        a = (x - sm) / np.where(np.abs(ss) > 1e-9, ss, 1.0)
        for i, (k, W) in enumerate(Ws):
            a = a @ W.T
            b = Bs.get(k.replace("W", "b", 1))
            if b is not None and b.size == a.size:
                a = a + b
            if i < len(Ws) - 1:
                a = np.maximum(a, 0)
        if am is not None and astd is not None:
            a = a * np.where(np.abs(astd) > 1e-9, astd, 1.0) + am
        return a
    for _ in range(20):
        fwd()
    ts = []
    for _ in range(repeat):
        t = time.perf_counter()
        fwd()
        ts.append((time.perf_counter() - t) * 1e3)
    out = _stat(ts)
    n_par = sum(int(np.prod(W.shape)) for _, W in Ws)
    out.update({"ok": True, "device": "CPU(numpy)", "layers": len(Ws), "params": n_par,
                "flops_est": 2 * n_par, "model": os.path.basename(p)})
    return out


def bench_torch_models(repeat=10):
    """有 torch 时: INTACT / SmolVLM 视觉塔 / DiT 动作头 — 实测前向。"""
    res = {}
    try:
        import torch                                                         # noqa: PLC0415
    except Exception as e:                                                   # noqa: BLE001
        return {"_": {"ok": False, "why": "no torch: %s" % e}}
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    # ① INTACT (若本机有 ckpt dir)
    cands = [os.path.join(ROOT, "checkpoints/intact_l4_current"),
             os.path.join(ROOT, "zmax_data/stable-wm-cache/intact_goal_zmax_v2_s3072")]
    for c in cands:
        if os.path.isdir(c):
            try:
                from lerobot.world_model.intact_model import IntactWorldModel  # noqa: PLC0415
                m = IntactWorldModel.load(c).to(dev).eval()
                x = torch.randn(1, 3, 224, 224, device=dev)
                a = torch.zeros(1, 8, device=dev)
                with torch.no_grad():
                    for _ in range(2):
                        m(x, a)
                    ts = []
                    for _ in range(repeat):
                        t = time.perf_counter()
                        m(x, a)
                        ts.append((time.perf_counter() - t) * 1e3)
                s = _stat(ts)
                s.update({"ok": True, "device": dev, "ckpt": os.path.relpath(c, ROOT),
                          "params": sum(p.numel() for p in m.parameters())})
                res["intact"] = s
                break
            except Exception as e:                                           # noqa: BLE001
                res["intact"] = {"ok": False, "why": "%s: %s" % (type(e).__name__, str(e)[:120])}
    return res


def main() -> int:
    global ROOT
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=ROOT)
    ap.add_argument("--devices", default="NPU,GPU,CPU")
    ap.add_argument("--repeat", type=int, default=20)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    ROOT = a.root
    # IR 目录可能分散 (端侧服务用自己的 edge_models/ir) ⇒ 按候选表找, 找到哪个用哪个并写明
    cands = [os.path.join(ROOT, "zmax_data/models/ir"), os.path.join(ROOT, "ir"),
             "/home/intel/edge_models/ir", os.path.join(ROOT, "../edge_models/ir")]
    ir = next((c for c in cands if os.path.isdir(c)), cands[0])

    def _find(name):
        for c in cands:
            f = os.path.join(c, name)
            if os.path.isfile(f):
                return f
        return os.path.join(ir, name)

    rep = {"ir_dir": ir, "host": socket.gethostname(), "platform": platform.platform(),
           "cpu": platform.processor() or platform.machine(), "ts": time.strftime("%F %T"),
           "components": {}}
    try:
        import openvino as ov                                                # noqa: PLC0415
        core = ov.Core()
        rep["openvino"] = ov.__version__
        rep["devices"] = list(core.available_devices)
        rep["dev_names"] = {}
        for d in core.available_devices:
            try:
                rep["dev_names"][d] = core.get_property(d, "FULL_DEVICE_NAME")
            except Exception:                                                # noqa: BLE001
                pass
    except Exception as e:                                                   # noqa: BLE001
        rep["openvino"] = "none (%s)" % e
        rep["devices"] = []

    devs = [d.strip() for d in a.devices.split(",") if d.strip()]
    models = {
        "yolo_det": _find("yolo_peg_live.xml"),
        "sam3_encoder": _find("sam3_enc_static.xml"),
        "intact_enc": _find("intact_enc.onnx"),
        "intact_pred": _find("intact_pred.onnx"),
    }
    for name, path in models.items():
        for d in devs:
            k = "%s@%s" % (name, d)
            rep["components"][k] = bench_ov(path, d, repeat=(a.repeat if d != "NPU" else 10),
                                            imgsz=640)
    rep["components"]["manifold_engine@CPU"] = bench_manifold()
    rep["components"]["action_head_mlp@CPU"] = bench_mlp()
    rep["components"].update({("t_" + k): v for k, v in bench_torch_models().items()})

    out = a.out or os.path.join(ROOT, "reports/compute/bench_%s.json" % socket.gethostname())
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(rep, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    ok = {k: (v.get("mean_ms") if v.get("ok") else "N/A") for k, v in rep["components"].items()}
    print(json.dumps(ok, ensure_ascii=False, indent=1))
    print("\n===> %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
