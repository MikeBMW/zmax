#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""smoke_load_ckpt_intel.py — 在 Intel(550C) 上真加载 550A 训出来的几何分支, 跑一次前向

为什么单独写: 「部署完成」不能只看文件到了。判据必须是 **在目标机上加载权重 + 跑一次真实前向**,
并打印参数量/输出形状/设备 —— 这样"550C 真在用它"才有据可查(而不是 550B 端口的自证)。
用法: /home/intel/train_venv/bin/python smoke_load_ckpt_intel.py <ckpt> [--device cpu|xpu]
"""
from __future__ import annotations

import json
import os
import sys

import torch

sys.path.insert(0, "/home/intel/zmax_550c/src")
from lerobot.manifold.hjepa_manifold import build_geometric_branch      # noqa: E402


def main():
    ck = sys.argv[1] if len(sys.argv) > 1 else \
        "/home/intel/zmax_550c/models/hjepa_mr_550a/geometric_branch_550a.pt"
    dev = "cpu"
    if "--device" in sys.argv:
        dev = sys.argv[sys.argv.index("--device") + 1]
    blob = torch.load(ck, map_location="cpu", weights_only=False)
    sd = blob.get("state_dict") or blob.get("model") or blob
    hp = blob.get("hp") or (blob.get("result") or {}).get("hp") or {}
    # 签名: build_geometric_branch(d_in=256, d_g=..., twist_dim=6, n_layers=2, with_uncertainty=True)
    #   ⇒ 按 ckpt 里的 hp 决定 d_in; 取不到就用训 550A 时的默认 256 (与 hjepa_mr_train_550a 同源)
    d_in = int(hp.get("d_in") or hp.get("feat_dim") or 256)
    model = build_geometric_branch(d_in=d_in, twist_dim=6)
    missing, unexpected = model.load_state_dict(sd, strict=False)
    model.eval().to(dev)
    n_par = sum(p.numel() for p in model.parameters())
    x = torch.randn(2, d_in, device=dev)      # 输入维度必须等于 d_in, 否则 mat1/mat2 形状不符
    with torch.no_grad():
        y = model(x)
    # 前向返回 dict (ξ 头 / 法线头 / 方差头), 不是单个张量
    if isinstance(y, dict):
        out_keys = {k: (list(v.shape) if hasattr(v, "shape") else v) for k, v in y.items()}
        am = float(sum(v.abs().mean() for v in y.values() if hasattr(v, "abs")) / max(1, len(y)))
        out_shape = out_keys
    else:
        out_keys = None
        am = float(y.abs().mean())
        out_shape = list(y.shape)
    out = {
        "host": os.uname().nodename, "ckpt": ck, "device": dev,
        "n_params": n_par, "missing": len(missing), "unexpected": len(unexpected),
        "in_shape": list(x.shape), "out_shape": out_shape, "out_heads": out_keys,
        "out_absmean": am, "hp": hp,
        "ok": len(missing) == 0 and len(unexpected) == 0,
    }
    print("__RESULT__" + json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
