#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧠 hjepa_model.py — H-JEPA 三层潜空间 (z₁空间 / z₂物体 / z₃语义) 的**推理实现**

老倪 2026-10-22: 「H-JEPA 的代码在哪里? A 把 H-JEPA 真接进流形引擎」

## 来源 (实测核对, 不猜)
  · 权重: `models/hjepa_zflow_model.pt` (10.76 MB, 2026-09-26) — 裸 `state_dict`, 71 个张量。
  · 训练侧脚本 (在仓库里, 但是**另一版**架构, 产物不是这份权重):
      tools/train_awe_zflow.py            (HJEPAEncoder / GRUPredictor / CrossAttnInject / AWEZFlowModel)
      tools/fork_experiments/train_hjepa_metaworld.py  (HJEPA_Hybrid, IMG 64)
      tools/fork_experiments/train_hjepa_3level.py     (ThreeLevelJEPA, IMG 64)
  · 🔴 **本文件里的网络结构是从 state_dict 的键名/形状逐层反推出来的** —
    仓库里没有与该权重一一对应的训练脚本 (原脚本在旧机 /home/xspace 路径下)。
    因此: 权重能 `strict=True` 全量对齐 = 结构一致的**强证据**; 但"该在哪一层加激活"
    这类细节无法从权重反推 ⇒ 见下方"反推边界"。
  · 迁移学习参考: tools/edge/ov_export_torch.py 里就按这份权重导 ONNX (输入 rgb 1,3,128,128 + state 1,7)。

## 反推边界 (必须如实写)
  1. 输入: RGB 3×H×W (H=W 由 `img_size` 决定, 默认 64 —— 训练脚本同族用 64; 权重本身对尺寸不敏感,
     因为末尾是 AdaptiveAvgPool2d) + state 7 维 (s_proj 是 Linear(7,256))。
  2. 三层潜维 = **256 / 256 / 128** (不是节点参数里写的 128/128/64 —— 那是另一版训练脚本的默认值;
     以权重为准: z_enc.0→256, z_enc.1→256, z_enc.2→128, 且 fuse 输入 640=256+256+128)。
  3. 自顶向下注入: td32: Linear(128→256) 把 z₃ 投到 z₂, td21: Linear(256→256) 把 z₂ 投到 z₁,
     各配一个可学标量 gate[i]。
  4. 预测头: 每层 z_pred.i = MLP(z_i) → 下一帧同维潜表示, 另带 energy 头 (EB-JEPA 式能量打分)。
  5. 融合头: fuse: 640→512, head: 512→1024→**98** (98 = 7×14, 与 7 维动作 × 14 步动作块一致;
     训练脚本的动作块长度无法从权重证实 ⇒ 只报维度, 不宣称语义)。
"""
from __future__ import annotations

import json
import os
import time

import numpy as np

ROOT_DEFAULT = "/home/ubuntu/zmax"
CKPT_DEFAULT = "models/hjepa_zflow_model.pt"

D_Z1, D_Z2, D_Z3 = 256, 256, 128      # 以权重为准 (见文件头)
STATE_DIM = 7
HEAD_DIM = 98


def _torch():
    import torch                                                       # noqa: PLC0415
    return torch


def _nn():
    from torch import nn                                               # noqa: PLC0415
    return nn


def build_model():
    """按 state_dict 反推的结构建网 (形状与 71 个张量逐一对齐)。"""
    nn = _nn()

    class _ZEnc(nn.Module):
        """单层潜编码: Linear(256→h) → ReLU → Linear(h→256) → Linear(256→d_z)。"""

        def __init__(self, hidden: int, d_z: int):
            super().__init__()
            self.enc = nn.Sequential(
                nn.Linear(256, hidden), nn.ReLU(),
                nn.Linear(hidden, d_z), nn.LayerNorm(d_z))

        def forward(self, h):
            return self.enc(h)

    class _ZPred(nn.Module):
        """单层预测: pred 头 (→同维) + energy 头 (→1)。"""

        def __init__(self, d_z: int, hidden: int, e_hidden: int):
            super().__init__()
            self.pred = nn.Sequential(
                nn.Linear(d_z, hidden), nn.ReLU(),
                nn.Linear(hidden, d_z), nn.LayerNorm(d_z))
            self.energy = nn.Sequential(
                nn.Linear(d_z, e_hidden), nn.ReLU(), nn.Linear(e_hidden, 1))

        def forward(self, z):
            return self.pred(z), self.energy(z)

    class HJEPA3Level(nn.Module):
        """H-JEPA 三层潜空间 + zFlow 自顶向下注入 + 动作头。"""

        def __init__(self):
            super().__init__()
            self.v_enc = nn.Sequential(
                nn.Conv2d(3, 64, 4), nn.ReLU(),
                nn.Conv2d(64, 128, 3), nn.ReLU(),
                nn.Conv2d(128, 256, 3), nn.ReLU(),
                nn.AdaptiveAvgPool2d(1), nn.Flatten())
            self.s_proj = nn.Linear(STATE_DIM, 256)
            self.z_enc = nn.ModuleList([_ZEnc(512, D_Z1), _ZEnc(512, D_Z2), _ZEnc(256, D_Z3)])
            self.z_pred = nn.ModuleList([_ZPred(D_Z1, 512, 64), _ZPred(D_Z2, 512, 64),
                                         _ZPred(D_Z3, 256, 32)])
            self.td32 = nn.Linear(D_Z3, D_Z2)          # z₃ → z₂
            self.td21 = nn.Linear(D_Z2, D_Z1)          # z₂ → z₁
            self.gate = nn.ParameterList([nn.Parameter(_torch().zeros(())) for _ in range(3)])
            self.fuse = nn.Sequential(nn.Linear(D_Z1 + D_Z2 + D_Z3, 512), nn.ReLU(),
                                      nn.LayerNorm(512))
            self.head = nn.Sequential(nn.Linear(512, 1024), nn.ReLU(), nn.Linear(1024, HEAD_DIM))

        def forward(self, img, state):
            h = self.v_enc(img) + self.s_proj(state)
            z1 = self.z_enc[0](h)
            z2 = self.z_enc[1](h)
            z3 = self.z_enc[2](h)
            z2b = z2 + self.gate[1] * self.td32(z3)     # 自顶向下: 语义 → 物体
            z1b = z1 + self.gate[0] * self.td21(z2b)    # 物体 → 空间
            p1, e1 = self.z_pred[0](z1b)
            p2, e2 = self.z_pred[1](z2b)
            p3, e3 = self.z_pred[2](z3)
            fused = self.fuse(_torch().cat([z1b, z2b, z3], dim=-1))
            return {"z1": z1b, "z2": z2b, "z3": z3,
                    "z_pred": (p1, p2, p3), "energy": (e1, e2, e3),
                    "head": self.head(fused), "gates": self.gate}

    return HJEPA3Level()


class HJEPAModel:
    """H-JEPA 推理门面: 权重加载 (strict) + 真前向 + 就绪性如实报因。

    用法:
        m = HJEPAModel(root="/home/ubuntu/zmax")
        ok, why = m.available()
        out = m.infer(frame_rgb_hwc, state7)      # → dict(z1,z2,z3,z_concat, head, energy, ms)
    """

    NAME = "H-JEPA 三层潜空间 (z₁/z₂/z₃ = 256/256/128)"

    def __init__(self, root: str = ROOT_DEFAULT, ckpt: str = CKPT_DEFAULT,
                 img_size: int = 64, device: str = "cpu") -> None:
        self.root = root
        self.ckpt_path = ckpt if os.path.isabs(ckpt) else os.path.join(root, ckpt)
        self.img_size = int(os.environ.get("HJEPA_IMG_SIZE", img_size) or 64)
        self.device = device
        self._net = None
        self._loaded = False
        self._reason = ""
        self._n = 0
        self._last_ms = 0.0
        self.z_dim = D_Z1 + D_Z2 + D_Z3               # 640 (三层拼接)

    # ── 就绪性 (如实: 缺什么说什么) ──
    def available(self) -> tuple[bool, str]:
        if not os.path.isfile(self.ckpt_path):
            return False, "权重不存在: %s" % self.ckpt_path
        if self._loaded:
            return True, self._reason
        try:
            torch = _torch()
        except Exception as e:                                            # noqa: BLE001
            return False, "torch 不可用: %s: %s" % (type(e).__name__, e)
        try:
            net = build_model()
            sd = torch.load(self.ckpt_path, map_location="cpu", weights_only=False)
            if not isinstance(sd, dict):
                return False, "权重不是 state_dict (类型 %s)" % type(sd).__name__
            missing, unexpected = net.load_state_dict(sd, strict=False)
            if missing or unexpected:
                return False, ("结构与权重不匹配: 缺 %d 项 %s / 多 %d 项 %s"
                               % (len(missing), missing[:3], len(unexpected), unexpected[:3]))
            net.eval()
            if self.device != "cpu":
                net = net.to(self.device)
            self._net = net
            self._loaded = True
            n_par = sum(p.numel() for p in net.parameters())
            self._reason = ("%s · 权重 %s · strict 全量对齐 %d 张量 · %.2fM 参数 · 输入 RGB %d×%d + state %d"
                            % (self.NAME, os.path.relpath(self.ckpt_path, self.root), len(sd),
                               n_par / 1e6, self.img_size, self.img_size, STATE_DIM))
            return True, self._reason
        except Exception as e:                                            # noqa: BLE001
            return False, "加载失败: %s: %s" % (type(e).__name__, e)

    # ── 真前向 (一帧一次; 不用假数据) ──
    def infer(self, frame_rgb, state7) -> dict:
        ok, why = self.available()
        if not ok:
            return {"ok": False, "why": why}
        torch = _torch()
        t0 = time.perf_counter()
        try:
            x = self._prep_frame(frame_rgb)
            s = np.asarray(state7, float).ravel()[:STATE_DIM]
            if s.size != STATE_DIM:
                return {"ok": False, "why": "state 需 %d 维, 收到 %d" % (STATE_DIM, s.size)}
            with torch.no_grad():
                out = self._net(x, torch.from_numpy(s).float().unsqueeze(0))
            res = {k: v for k, v in out.items()}
            z1, z2, z3 = res["z1"][0].numpy(), res["z2"][0].numpy(), res["z3"][0].numpy()
            zcat = np.concatenate([z1, z2, z3]).astype(float)
            self._n += 1
            self._last_ms = (time.perf_counter() - t0) * 1e3
            return {
                "ok": True,
                "z1": z1, "z2": z2, "z3": z3, "z_concat": zcat,
                "z_pred": [p[0].numpy() for p in res["z_pred"]],
                "energy": [float(e[0, 0]) for e in res["energy"]],
                "head": res["head"][0].numpy(),
                "gates": [float(g) for g in res["gates"]],
                "ms": round(self._last_ms, 2), "n": self._n,
                "dims": [int(z1.size), int(z2.size), int(z3.size)],
            }
        except Exception as e:                                            # noqa: BLE001
            return {"ok": False, "why": "前向异常: %s: %s" % (type(e).__name__, e)}

    def _prep_frame(self, frame):
        """RGB HWC (uint8/float) → float 张量 (1,3,S,S); 大图按双线性缩到 img_size。"""
        torch = _torch()
        a = np.asarray(frame)
        if a.ndim == 2:
            a = np.stack([a] * 3, axis=-1)
        if a.shape[-1] == 4:
            a = a[:, :, :3]
        a = a.astype(np.float32) / (255.0 if a.max() > 1.5 else 1.0)
        h, w = a.shape[:2]
        s = self.img_size
        if (h, w) != (s, s):
            yi = (np.linspace(0, h - 1, s)).astype(int)
            xi = (np.linspace(0, w - 1, s)).astype(int)
            a = a[yi][:, xi]                                  # 双线性太重, 推理用最近邻够 (只影响输运, 不影响接线)
        t = torch.from_numpy(a).permute(2, 0, 1).unsqueeze(0).float()
        return t.to(self.device) if self.device != "cpu" else t

    # ── 引擎潜维映射 (320→16 这类降维**必须**来自实测标定, 不许凭空写) ──
    def engine_map(self) -> dict:
        p = os.path.join(self.root, "models", "hjepa_to_manifold.json")
        if not os.path.isfile(p):
            return {"ready": False, "note": "缺 z640→引擎潜维标定: %s (先跑 tools/fit_hjepa_to_manifold.py)" % p}
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception as e:                                            # noqa: BLE001
            return {"ready": False, "note": "标定读取失败: %s" % e}
        d["path"] = p
        return d


if __name__ == "__main__":
    import sys
    m = HJEPAModel(root=os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))))
    ok, why = m.available()
    print(("✅ " if ok else "❌ ") + why)
    if ok:
        rng = np.random.default_rng(0)
        out = m.infer(rng.integers(0, 255, (64, 64, 3), dtype=np.uint8), rng.normal(0, 0.2, 7))
        print("前向:", {k: (v if not isinstance(v, np.ndarray) else ("ndarray%s" % (v.shape,)))
                       for k, v in out.items() if k != "z_concat"})
        print("三层维度:", out["dims"], "· z_concat", out["z_concat"].shape,
              "· |z1|=%.3f |z2|=%.3f |z3|=%.3f" %
              (np.linalg.norm(out["z1"]), np.linalg.norm(out["z2"]), np.linalg.norm(out["z3"])))
        sys.exit(0)
    sys.exit(1)
