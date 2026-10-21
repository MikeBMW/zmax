#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ov_convert.py — 在 Intel 机上把 ONNX 转成 OpenVINO IR (fp16) 并三设备实测。

跑法(Intel 机):
  /home/intel/openvino_2026.1_env/bin/python /tmp/ov_convert.py /tmp/intact_enc.onnx /tmp/intact_pred.onnx
产物放 /home/intel/edge_models/ir/ ；有同名 .npz 参考就做数值对账(和本机 onnxruntime 的 torch 输出比)。
"""
import json
import os
import sys
import time

import numpy as np
import openvino as ov

OUT = "/home/intel/edge_models/ir"
CORE = ov.Core()


def bench(model, dev, n=50):
    try:
        comp = CORE.compile_model(model, dev)
    except Exception as e:                                    # noqa: BLE001
        return {"dev": dev, "err": "%s: %s" % (type(e).__name__, str(e)[:100])}
    def _dim(d):
        try:                       # openvino Dimension: 静态才有 int; 动态(-1) 取 1
            return int(d.get_length()) if d.is_static else 1
        except Exception:          # noqa: BLE001
            return 1

    def _zeros(port):
        return np.zeros([_dim(d) for d in port.partial_shape], dtype=np.float32)

    ports = list(comp.inputs)
    x = _zeros(ports[0]) if len(ports) == 1 else {p: _zeros(p) for p in ports}
    t = []
    for i in range(n):
        t0 = time.perf_counter()
        comp(x)
        if i >= 5:
            t.append((time.perf_counter() - t0) * 1000.0)
    t.sort()
    return {"dev": dev, "median_ms": round(t[len(t) // 2], 2), "min_ms": round(t[0], 2),
            "first_ms": None, "n": len(t)}


def main(paths):
    os.makedirs(OUT, exist_ok=True)
    rep = {}
    for p in paths:
        name = os.path.splitext(os.path.basename(p))[0]
        m = CORE.read_model(p)
        t0 = time.perf_counter()
        xml = os.path.join(OUT, name + ".xml")
        ov.save_model(m, xml, compress_to_fp16=True)
        conv_s = time.perf_counter() - t0
        mb = round(os.path.getsize(xml) / 1e6, 2)
        info = {"xml": xml, "mb": mb, "convert_s": round(conv_s, 2),
                "inputs": [list(i.shape) for i in m.inputs],
                "bench": [bench(m, d) for d in ("CPU", "GPU", "NPU")]}
        # 数值对账: 本机(/tmp)留了 <name>_ref.npz 就比
        ref = os.path.join("/tmp", name + "_ref.npz")
        if os.path.exists(ref):
            z = np.load(ref)
            comp = CORE.compile_model(m, "CPU")
            got = comp({comp.input(0): z["px"]})[comp.output(0)]
            exp = z["emb"]
            d = np.abs(got - exp)
            info["parity"] = {"max_abs": float(d.max()), "mean_abs": float(d.mean()),
                              "ref": os.path.basename(ref)}
        rep[name] = info
        print("[convert] %s → %s (%.1f MB, %.1fs) | %s" % (p, xml, mb, conv_s, info["bench"]))
        if "parity" in info:
            print("          对账(IR fp16 vs torch/onnx): max|Δ|=%.4e mean|Δ|=%.4e"
                  % (info["parity"]["max_abs"], info["parity"]["mean_abs"]))
    print(json.dumps(rep, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main(sys.argv[1:])
