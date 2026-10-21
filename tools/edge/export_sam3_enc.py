#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SAM3 视觉编码器 → ONNX (静态 1×3×1008×1008, fp32) —— 之后在 intel 上转 IR fp16。

为什么要拆: SAM3 = 编码器(静态大 ViT, 适合 IR/NPU/GPU) + prompt 解码器(文本/框/点动态 shape, 只能 GPU 动态或 CPU)。
一次导整个模型进 IR 会因为动态 prompt 分支而失败或退化成 CPU 慢路径。
"""
import os
import sys
import time

import torch

P = "/home/ubuntu/zmax/zmax_data/models/sam3_hf"
OUT = "/home/ubuntu/zmax/zmax_data/models/ir/sam3_enc.onnx"
H = W = 1008


class Wrap(torch.nn.Module):
    def __init__(self, enc):
        super().__init__()
        self.enc = enc

    def forward(self, pixel_values):
        o = self.enc(pixel_values=pixel_values)
        if isinstance(o, torch.Tensor):
            return o
        for k in ("last_hidden_state", "hidden_states", "pooler_output"):
            v = getattr(o, k, None)
            if isinstance(v, torch.Tensor):
                return v
        if isinstance(o, (tuple, list)):
            return o[0]
        raise RuntimeError("encoder 输出既不是 tensor 也不是带 last_hidden_state 的对象: %r" % (type(o),))


def main():
    t0 = time.time()
    print("[1/4] load Sam3Model (fp32, low_cpu_mem_usage)…", flush=True)
    from transformers import Sam3Model
    m = Sam3Model.from_pretrained(P, torch_dtype=torch.float32, low_cpu_mem_usage=True).eval()
    enc = m.get_encoder(modality="image")
    n = sum(p.numel() for p in enc.parameters())
    print("    encoder = %s · %.1fM 参数" % (type(enc).__name__, n / 1e6), flush=True)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    x = torch.zeros(1, 3, H, W, dtype=torch.float32)
    print("[2/4] 试跑一次 forward…", flush=True)
    with torch.no_grad():
        y = Wrap(enc)(x)
    print("    out = %s" % (tuple(y.shape) if hasattr(y, "shape") else type(y),), flush=True)

    print("[3/4] 导出 ONNX (opset 17, 静态 1008×1008)…", flush=True)
    with torch.no_grad():
        torch.onnx.export(Wrap(enc), (x,), OUT, opset_version=17, do_constant_folding=True,
                          input_names=["pixel_values"], output_names=["features"],
                          dynamo=False)
    print("    ONNX = %s (%.0f MB)" % (OUT, os.path.getsize(OUT) / 1e6), flush=True)

    print("[4/4] onnx checker…", flush=True)
    import onnx
    mm = onnx.load(OUT)
    onnx.checker.check_model(mm)
    print("    checker ok · 节点 %d · %.1f 分钟" % (len(mm.graph.node), (time.time() - t0) / 60), flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    sys.exit(main())
