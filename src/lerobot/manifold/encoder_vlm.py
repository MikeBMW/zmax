#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""👁 通用视觉编码器 (VLM vision encoder) —— L4 潜空间的**输入编码** (老倪 2026-10-14)

老倪定稿口径: 「VLM 通用视觉编码器是输入，流形引擎根据黎曼度规加约束，INTACT 负责意图解码。
              —— 这才是 L4 的潜空间」

L4 潜空间链路 (本模块只负责第 ① 段):
   ① 通用视觉编码器 (本模块): 帧 → 通用视觉特征 f ∈ R^960   (SmolVLM2 视觉塔, 冻结, 不训练)
   ② 流形引擎 · 黎曼度规约束: z = Bᵀ D^{+1/2}(f−μ),  g = M·G(x), det G = 1  → 潜坐标 p (L4 潜空间)
      (`src/lerobot/manifold/l4_latent.py` + 引擎 `latent_provider`)
   ③ INTACT 意图解码: z_t / Δz → 意图 (goal/from/skill/gate)         (画布 `ssintact_dec`)

为什么用视觉塔而不是语言头: L4 潜空间要的是**通用视觉表示**, 不是问答文本; 视觉塔 86.4M 参数、
冻结、单帧 ms~百 ms 级 ⇒ 可当实时编码器。选择由真源决定 (本地 HF 缓存只有它和 Qwen2.5-VL)。
"""
from __future__ import annotations

import os
import time

os.environ.setdefault("HF_HOME", "/home/ubuntu/zmax/zmax_data/hf_cache")
os.environ.setdefault("HF_HUB_OFFLINE", "1")          # 离线: 只认本地缓存, 不联网
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

ROOT_DEFAULT = "/home/ubuntu/zmax"
DEFAULT_MID = "HuggingFaceTB/SmolVLM2-500M-Video-Instruct"
ALTS = ("Qwen/Qwen2.5-VL-3B-Instruct",)


class VLMVisionEncoder:
    """通用视觉编码器: 帧 → 特征向量 (池化) / token 特征。冻结, 不训练。"""

    NAME = "SmolVLM2-500M 视觉塔 (SmolVLMVisionTransformer, 冻结)"
    # 实测输出: (13 tiles, 1024 tokens, 768 hidden) ⇒ 池化后 **768 维** 通用视觉特征

    def __init__(self, mid: str = DEFAULT_MID, device: str | None = None) -> None:
        self.mid = mid
        self.device = device
        self._proc = None
        self._vis = None
        self._tok = None
        self._dtype = None

    # ── 就绪性 ──
    def available(self) -> tuple[bool, str]:
        try:
            import torch                                              # noqa: F401,PLC0415
            from transformers import AutoModelForImageTextToText, AutoProcessor  # noqa: F401,PLC0415
        except Exception as e:                                        # noqa: BLE001
            return False, "transformers/torch 不就绪: %s: %s" % (type(e).__name__, e)
        try:
            self._load()
        except Exception as e:                                        # noqa: BLE001
            return False, "视觉塔载入失败 (%s): %s" % (self.mid, str(e)[:120])
        return True, "就绪: %s · 特征 %d 维 · 设备 %s" % (
            self.NAME, int(getattr(self, "feature_dim", 0)), str(self._device))

    def _load(self) -> None:
        if self._vis is not None:
            return
        import torch                                                  # noqa: PLC0415
        from transformers import AutoModelForImageTextToText, AutoProcessor   # noqa: PLC0415
        _t0 = __import__("time").time()
        self._proc = AutoProcessor.from_pretrained(self.mid)
        mdl = AutoModelForImageTextToText.from_pretrained(self.mid, dtype=torch.float32).eval()
        try:                                 # 📋 模型台账 (L5 视觉编码塔: 真加载才打印)
            from lerobot.engineering.model_log import note as _note
            _n_par = sum(p.numel() for p in mdl.parameters()) / 1e6
            _note("L5", "SmolVLM2 视觉编码", self.mid, True, elapsed=__import__("time").time() - _t0,
                  detail="参数量 %.0fM · 设备 %s" % (_n_par, getattr(self, "_device", "cpu")))
        except Exception:                                                # noqa: BLE001
            pass
        core = getattr(mdl, "model", mdl)
        vis = getattr(core, "vision_model", None) or getattr(core, "vision_tower", None)
        if vis is None:
            raise RuntimeError("模型里没有视觉塔: %s" % [n for n, _ in core.named_children()])
        self._device = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._vis = vis.to(self._device).eval()
        self._tok = getattr(core, "connector", None)
        cfg = getattr(vis, "config", None)
        self.feature_dim = int(getattr(cfg, "hidden_size", 0) or 0)
        self._dtype = torch.float32

    # ── 真编码 ──
    def encode(self, frame, pool: str = "mean", return_tokens: bool = False):
        """帧 (PIL/np.ndarray/路径) → 特征。pool: mean|cls。返回 np.ndarray(960,) 或 token 矩阵。"""
        import numpy as np                                            # noqa: PLC0415
        import torch                                                  # noqa: PLC0415
        from PIL import Image                                         # noqa: PLC0415
        self._load()
        img = frame
        if isinstance(frame, str):
            img = Image.open(frame)
        if not isinstance(img, Image.Image):
            img = Image.fromarray(np.asarray(img).astype("uint8"))
        img = img.convert("RGB")
        o = self._proc(images=img, return_tensors="pt")
        pix = o["pixel_values"]
        if pix.ndim == 5:                    # (B, n_tiles, 3, H, W) ⇒ 视觉塔吃 4D
            b, t = pix.shape[0], pix.shape[1]
            pix = pix.reshape(b * t, *pix.shape[2:])
        t0 = time.time()
        with torch.no_grad():
            out = self._vis(pixel_values=pix.to(self._device))
        f = (out.last_hidden_state if hasattr(out, "last_hidden_state") else out[0])
        f = f.float().cpu().numpy()
        dt = (time.time() - t0) * 1e3
        if return_tokens:
            return f
        if f.ndim == 3:                    # (tiles, tokens, hidden) ⇒ 池化到 (hidden,)
            v = f.mean(axis=(0, 1)) if pool == "mean" else f[0, 0]
        else:
            v = f.mean(axis=0) if pool == "mean" else f[0]
        self.last_ms = dt
        return np.asarray(v, float).ravel()


def default_encoder() -> VLMVisionEncoder:
    return VLMVisionEncoder()
