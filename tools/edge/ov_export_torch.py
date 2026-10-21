#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ov_export_torch.py — 把 Z-MAX 的 PyTorch 模型导成 ONNX(静态 shape), 供 Intel 端转 IR 跑 NPU/GPU。

老倪 2026-10-21: 「intel上 550C 全模型运行, 将 NPU GPU 最大化使用」
⇒ 端侧只有 OpenVINO, 没有 torch。路线固定三步, 本脚本干第 1 步 (本机有 torch):
    ① torch 模型 → ONNX (静态 shape, opset17)      ← ov_export_torch.py
    ② ONNX → IR fp16 (Intel 机, ov.convert_model)  ← 见 ov_convert_ir.py
    ③ 跑 + 量 (edge_service /detect?model=&device= ← 或 /bench)

用法 (示例: H-JEPA z 流):
  ./gui-venv311/bin/python tools/edge/ov_export_torch.py \
      --module tools/fork_experiments/h_jepa_zflow.py --cls ZFlow_VLA \
      --ckpt zmax_data/models/hjepa_zflow_model.pt \
      --rgb 1,3,128,128 --state 1,7 --out zmax_data/models/ir/hjepa_zflow.onnx

约定:
  · 权重缺失/多余一律**打印出来**再决定要不要继续 (--allow-partial 才允许 strict=False 落地);
  · 导出后必做 **torch vs onnxruntime 数值对账** (max|Δ|), 不过阈值就红, 不给"应该没问题";
  · 不在磁盘上覆盖老 onnx (同名就加 _v2), 产物旁边写 .json 说明 shape/校验结果。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import time

import numpy as np
import torch


def _load_module(path):
    p = os.path.abspath(path)
    sys.path.insert(0, os.path.dirname(p))          # 让模型文件自己的 import (同目录兄弟模块) 能解析
    spec = importlib.util.spec_from_file_location("zmax_export_" + os.path.basename(p)[:-3], p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _shape(s):
    return [int(x) for x in str(s).split(",") if x.strip() != ""]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--module", required=True, help="模型定义 .py 路径")
    ap.add_argument("--cls", required=True, help="类名 (无参构造, 或配合 --init-json)")
    ap.add_argument("--init-json", default="", help="类构造参数 JSON, 如 '{}'")
    ap.add_argument("--ckpt", default="", help="state_dict .pt (可空 = 随机权重, 只验结构)")
    ap.add_argument("--rgb", default="1,3,128,128", help="图像输入 shape, 逗号分隔")
    ap.add_argument("--state", default="1,7", help="状态向量输入 shape (模型只要一个输入时置空)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--opset", type=int, default=17)
    ap.add_argument("--parity", type=float, default=1e-4, help="torch vs onnxruntime max|Δ| 阈值")
    ap.add_argument("--allow-partial", action="store_true", help="权重对不上也继续 (仅结构验证)")
    a = ap.parse_args()

    rep = {"module": a.module, "cls": a.cls, "ckpt": a.ckpt, "opset": a.opset,
           "ts": time.strftime("%F %T")}
    mod = _load_module(a.module)
    cls = getattr(mod, a.cls, None)
    if cls is None:
        sys.exit("找不到类 %s (模块 %s 里有: %s)" % (a.cls, a.module,
                                                 [x for x in dir(mod) if x[0].isupper()][:10]))
    init = json.loads(a.init_json) if a.init_json.strip() else {}
    model = cls(**init) if init else cls()
    model.eval()

    if a.ckpt:
        sd = torch.load(a.ckpt, map_location="cpu", weights_only=False)
        if isinstance(sd, dict) and "model" in sd and isinstance(sd["model"], dict):
            sd = sd["model"]
        if not isinstance(sd, dict):
            sys.exit("ckpt 不是 state_dict: %s" % type(sd))
        own = model.state_dict()
        missing = [k for k in own if k not in sd]
        unexpected = [k for k in sd if k not in own]
        rep["keys"] = {"model": len(own), "ckpt": len(sd), "missing": len(missing),
                       "unexpected": len(unexpected)}
        if missing or unexpected:
            rep["keys"]["missing_sample"] = missing[:8]
            rep["keys"]["unexpected_sample"] = unexpected[:8]
            print("[export] ⚠ 权重对不齐: 缺 %d / 多 %d" % (len(missing), len(unexpected)))
            print("         缺示例:", missing[:5])
            print("         多示例:", unexpected[:5])
            if not a.allow_partial:
                sys.exit("[export] 拒绝导出 (要仅验结构请加 --allow-partial)")
        model.load_state_dict(sd, strict=False)
        rep["ckpt_loaded"] = True

    rgb = torch.randn(*_shape(a.rgb))
    st = torch.randn(*_shape(a.state)) if a.state.strip() else None
    inputs = (rgb,) if st is None else (rgb, st)
    with torch.no_grad():
        ref = model(*inputs)
    out_t = ref[0] if isinstance(ref, (tuple, list)) else ref
    rep["inputs"] = [list(x.shape) for x in inputs]
    rep["output"] = list(out_t.shape)

    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    out = a.out
    if os.path.exists(out):
        base, ext = os.path.splitext(out)
        i = 2
        while os.path.exists("%s_v%d%s" % (base, i, ext)):
            i += 1
        out = "%s_v%d%s" % (base, i, ext)
        print("[export] 目标已存在, 改写 %s" % out)

    names = ["rgb", "state"] if st is not None else ["rgb"]
    torch.onnx.export(model, inputs, out, input_names=names, output_names=["out"],
                      opset_version=a.opset, do_constant_folding=True, verbose=False)
    rep["onnx"] = out
    rep["onnx_mb"] = round(os.path.getsize(out) / 1e6, 2)
    rep["onnx_sha16"] = hashlib.sha256(open(out, "rb").read()).hexdigest()[:16]

    # —— 数值对账: onnxruntime 跑同一批输入, 和 torch 比 ——
    try:
        import onnxruntime as ort
        sess = ort.InferenceSession(out, providers=["CPUExecutionProvider"])
        feed = {names[i]: inputs[i].numpy() for i in range(len(names))}
        got = sess.run(None, feed)[0]
        d = np.abs(got - out_t.detach().numpy())
        rep["parity"] = {"max_abs": float(d.max()), "mean_abs": float(d.mean()),
                         "ok": bool(d.max() <= a.parity)}
        print("[export] 对账 max|Δ|=%.3e mean|Δ|=%.3e → %s"
              % (d.max(), d.mean(), "PASS" if rep["parity"]["ok"] else "FAIL"))
    except Exception as e:                                          # noqa: BLE001
        rep["parity"] = {"err": "%s: %s" % (type(e).__name__, str(e)[:120])}
        print("[export] ⚠ 对账没做成:", rep["parity"]["err"])

    with open(out + ".json", "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    print("[export] 产物:", out)
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    if rep.get("parity", {}).get("ok") is False:
        sys.exit(2)


if __name__ == "__main__":
    main()
