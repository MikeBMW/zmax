#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""export_intact.py — 用 external/INTACT-JEPA 自己的模型定义导出 L4(INTACT) 子图到 ONNX。

为什么必须用它的 venv: 模型类 = jepa.JEPA + module.ARPredictor/Embedder/IntentActionActor/MLP,
依赖 stable_pretraining(它的 ViT) + einops, 只有 external/INTACT-JEPA/.venv 里齐。
跑的姿势(实测):
  cd ~/zmax/external/INTACT-JEPA && .venv/bin/python ~/zmax/tools/edge/export_intact.py \
      --ckpt ~/zmax/zmax_data/stable-wm-cache/checkpoints/intact_goal_optical_insert_v6r11_s3072/weights_epoch_3.pt \
      --out-dir ~/zmax/zmax_data/models/ir

导出两块 (推理真正需要的, 其余是训练期的东西):
  ① intact_enc.onnx     pixels(B,3,224,224) → emb(B,192)                 每帧跑这块
  ② intact_pred.onnx    emb(B,3,192) + act_emb(B,3,192) → pred(B,3,192)  世界模型预测
配置真源 = ckpt 同目录的 config.json (那次训练实际用的), 不是仓库里任何一份 yaml。
对账 = torch vs onnxruntime, max|Δ| > 1e-4 直接红。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import torch
from hydra.utils import instantiate
from torch import nn

sys.path.insert(0, os.getcwd())          # 让 jepa / module 能 import (cwd = external/INTACT-JEPA)


class EncOnly(nn.Module):
    """encoder + projector: 单帧 (或 B 帧) 像素 → 潜表征。形状与 JEPA.encode 里逐字一致。"""

    def __init__(self, jepa):
        super().__init__()
        self.encoder = jepa.encoder
        self.projector = jepa.projector

    def forward(self, pixels):
        out = self.encoder(pixels, interpolate_pos_encoding=True)
        return self.projector(out.last_hidden_state[:, 0])


class PredOnly(nn.Module):
    """predictor + pred_proj: (emb 序列, 动作 emb 序列) → 预测 emb。"""

    def __init__(self, jepa):
        super().__init__()
        self.predictor = jepa.predictor
        self.pred_proj = jepa.pred_proj

    def forward(self, emb, act_emb):
        from einops import rearrange
        pred = self.predictor(emb, act_emb)
        pred = self.pred_proj(rearrange(pred, "b t d -> (b t) d"))
        return rearrange(pred, "(b t) d -> b t d", b=emb.size(0))


def parity(onnx_path, inputs, ref, names):
    try:
        import onnxruntime as ort
    except Exception as e:                                             # noqa: BLE001
        return {"err": "无 onnxruntime: %s" % e}
    sess = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
    got = sess.run(None, {names[i]: inputs[i].numpy() for i in range(len(names))})[0]
    d = np.abs(got - ref.detach().numpy())
    return {"max_abs": float(d.max()), "mean_abs": float(d.mean()), "ok": bool(d.max() <= 1e-4)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--cfg", default="", help="默认用 ckpt 同目录 config.json")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--seq", type=int, default=3)
    ap.add_argument("--img", type=int, default=224)
    a = ap.parse_args()

    cfg_path = a.cfg or os.path.join(os.path.dirname(os.path.abspath(a.ckpt)), "config.json")
    cfg = json.load(open(cfg_path, encoding="utf-8"))
    if "_target_" not in cfg:                     # config.json 里带 _target_: jepa.JEPA, 必须保留才能实例化成模型
        cfg["_target_"] = "jepa.JEPA"
    model = instantiate(cfg)                      # ← JEPA 本体 (jepa.JEPA)
    sd = torch.load(a.ckpt, map_location="cpu", weights_only=False)
    sd = sd.get("model", sd) if isinstance(sd, dict) else sd
    own = model.state_dict()
    missing = [k for k in own if k not in sd]
    unexpected = [k for k in sd if k not in own]
    bad = [k for k in sd if k in own and sd[k].shape != own[k].shape]
    print("[intact] 权重: 模型 %d 键 / ckpt %d 键 | 缺 %d 多 %d 形状错 %d"
          % (len(own), len(sd), len(missing), len(unexpected), len(bad)))
    if missing or unexpected or bad:
        print("  缺:", missing[:5], "\n  多:", unexpected[:5], "\n  形状错:", bad[:5])
        sys.exit("[intact] 对不齐, 拒绝导出")
    model.load_state_dict(sd, strict=True)
    model.eval()
    print("[intact] strict=True 载入通过 ⇒ 权重与 config.json 结构一致")

    os.makedirs(a.out_dir, exist_ok=True)
    report = {"ckpt": a.ckpt, "cfg": cfg_path, "strict_load": True, "parts": {}}

    # ① 编码器
    enc = EncOnly(model).eval()
    px = torch.randn(1, 3, a.img, a.img)
    with torch.no_grad():
        e_ref = enc(px)
    p1 = os.path.join(a.out_dir, "intact_enc.onnx")
    torch.onnx.export(enc, (px,), p1, input_names=["pixels"], output_names=["emb"],
                      opset_version=17, do_constant_folding=True)
    r1 = parity(p1, (px,), e_ref, ["pixels"])
    print("[intact] intact_enc.onnx %.1f MB | emb %s | 对账 %s"
          % (os.path.getsize(p1) / 1e6, tuple(e_ref.shape), r1))
    report["parts"]["enc"] = {"out": p1, "mb": round(os.path.getsize(p1) / 1e6, 2),
                              "emb": list(e_ref.shape), "parity": r1}

    # ② 世界模型预测头
    pred = PredOnly(model).eval()
    emb_dim = int(cfg["intent_actor"]["embed_dim"])          # 192 (tiny/ViT-S)
    emb = torch.randn(1, a.seq, emb_dim)
    act = torch.randn(1, a.seq, emb_dim)
    with torch.no_grad():
        p_ref = pred(emb, act)
    p2 = os.path.join(a.out_dir, "intact_pred.onnx")
    torch.onnx.export(pred, (emb, act), p2, input_names=["emb", "act_emb"], output_names=["pred"],
                      opset_version=17, do_constant_folding=True)
    r2 = parity(p2, (emb, act), p_ref, ["emb", "act_emb"])
    print("[intact] intact_pred.onnx %.1f MB | pred %s | 对账 %s"
          % (os.path.getsize(p2) / 1e6, tuple(p_ref.shape), r2))
    report["parts"]["pred"] = {"out": p2, "mb": round(os.path.getsize(p2) / 1e6, 2),
                               "pred": list(p_ref.shape), "parity": r2}

    with open(os.path.join(a.out_dir, "intact_export.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    ok = all(v.get("parity", {}).get("ok") for v in report["parts"].values())
    print("[intact] 结论:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
