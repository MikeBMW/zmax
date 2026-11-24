#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧠 编码模型 (Encoder Model) —— 给流形引擎用的**外部潜表示来源** (老倪 2026-10-14)

老倪: 「流形是被预测出来的，得加一个编码模型，INCACT(=INTACT)呢？」

事实: 流形引擎**内建**的编码器是 PCA (`Encoder.fit`, 对当前 43 维状态静态拟合, 120 帧) ——
      它把状态**拟合**成潜坐标, **不预测**; 引擎里 `Encoder.lift`(丛映射) 只是声明, 未接。
      INTACT-JEPA (L4 在役 ckpt) 的原生输出就是"预测的潜表示":
          z_t   = encoder(帧)              当前潜表示 (192 维)
          z_pred= ARPredictor(z_t, 动作)   **预测的下一步潜表示** (192 维)   ← "流形是被预测出来的"
          delta = z_goal − z_t             goal_displacement 意图
      且 `models/intact_fiber_map.json` (ready=True, n=582 真实引擎样本) 已标定:
          z7_morph:     z_pred(192) → z7_geo(7)    r²=0.850 / r²_loso=0.607
          geom_contact: z7_geo(7)   → 接触丛(6)    r²_loso=0.586
          l3_contact:   z_pred(192) → 接触丛(6)    r²_loso=0.471   (二次项)
      ⇒ 本模块把 INTACT 的**预测潜表示**经这些**已过闸的标定**投成引擎潜维 (16),
        作为流形引擎的状态来源; 没有标定/没装 INTACT 时**明确报因**, 绝不假装可用。

引擎侧接口: `ManifoldEngine(latent_provider=<callable→z16>, latent_provider_note="...")`
      provider 为 None ⇒ 逐位回到内建 PCA (零回归)。

用法:
    from lerobot.manifold.encoder_model import IntactEncoderModel
    m = IntactEncoderModel(root="/home/ubuntu/zmax")
    ok, why = m.available()
    z16, note = m.latent(frame)        # 真跑一次 INTACT → 预测潜表示 → 引擎潜维
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np

ROOT_DEFAULT = "/home/ubuntu/zmax"
FIBER_MAP = "models/intact_fiber_map.json"
CKPT_DIR = "zmax_data/stable-wm-cache/checkpoints"


class IntactEncoderModel:
    """INTACT-JEPA 编码模型: 帧 → z_t / z_pred(预测潜表示) → 引擎流形坐标 (经已过闸标定)。"""

    NAME = "INTACT-JEPA (L4 在役 ckpt, ViT-tiny + ARPredictor)"

    def __init__(self, root: str = ROOT_DEFAULT, policy: str | None = None) -> None:
        self.root = root
        self.policy = policy or os.environ.get("INTACT_POLICY") or "intact_l4_current"
        self.ckpt = os.path.join(root, CKPT_DIR, self.policy)
        self.map_path = os.path.join(root, FIBER_MAP)
        self._fmap = None
        self._svc = None
        self._skill = None
        self._reason = ""

    # ── 就绪性 (如实; 不猜不默认) ──
    def available(self) -> tuple[bool, str]:
        if not os.path.isdir(self.ckpt):
            return False, "INTACT 在役 ckpt 不存在: %s" % os.path.relpath(self.ckpt, self.root)
        if not (os.path.isfile(os.path.join(self.ckpt, "config.json"))):
            return False, "ckpt 缺 config.json: %s" % os.path.relpath(self.ckpt, self.root)
        w = os.path.join(self.ckpt, "weights.pt")
        if not (os.path.isfile(w) or os.path.islink(w)):
            return False, "ckpt 缺 weights.pt: %s" % os.path.relpath(self.ckpt, self.root)
        if not os.path.isfile(self.map_path):
            return False, "丛映射标定不存在: %s (先跑 tools/fit_fiber_map.py)" % FIBER_MAP
        fm = self.fiber_map()
        if not fm.get("ready"):
            return False, "丛映射标定未过闸 (ready=False): %s" % str(fm.get("note"))[:80]
        for blk in ("z7_morph", "geom_contact"):
            if blk not in fm:
                return False, "丛映射缺块 %s" % blk
        if os.path.join(self.root, "src") not in sys.path:
            sys.path.insert(0, os.path.join(self.root, "src"))
        try:
            from lerobot.policies.intact.service import get_service   # noqa: F401,PLC0415
        except Exception as e:                                        # noqa: BLE001
            return False, "INTACT 运行时不就绪: %s: %s" % (type(e).__name__, e)
        return True, "就绪: ckpt=%s · 标定 ready · z7_morph r²_loso=%.3f" % (
            self.policy, float((fm.get("z7_morph") or {}).get("r2_loso") or 0.0))

    def fiber_map(self) -> dict:
        if self._fmap is None:
            with open(self.map_path, encoding="utf-8") as fh:
                self._fmap = json.load(fh)
        return self._fmap

    # ── 真推理: 帧 → 潜表示 (z_t / z_pred / delta) ──
    def _service(self):
        if self._svc is None:
            if os.path.join(self.root, "src") not in sys.path:
                sys.path.insert(0, os.path.join(self.root, "src"))
            from lerobot.policies.intact.service import get_service   # noqa: PLC0415
            self._svc = get_service(self.root, log=lambda *a: None)
        return self._svc

    def _skill_ctx(self):
        """该 ckpt skill_dim>0 ⇒ 缺 skill_ctx 会被模型侧硬闸拒绝 (实测原文见 service.run_once)。"""
        if self._skill is None:
            from lerobot.policies.intact.skill_ctx import build_skill_ctx   # noqa: PLC0415
            from lerobot.memory.potential_field import MemoryLayerBridge    # noqa: PLC0415
            proc = MemoryLayerBridge.from_real_data(root=self.root, seed=104,
                                                    use_engine_geom=True).process
            self._skill = build_skill_ctx(proc, None, "encoder_model", 0.0)
        return self._skill

    def encode(self, frame=None, stage: str = "encoder_model", grip: float = 0.0) -> dict:
        """真跑 INTACT 一次 → 潜表示 (192 维 ×5)。frame=None ⇒ 由节点数据源出帧。"""
        svc = self._service()
        ok, why = svc.ensure_ready()
        if not ok:
            raise RuntimeError(why)
        skill = None
        try:
            skill = self._skill_ctx()
        except Exception:                                                 # noqa: BLE001
            skill = None                    # 模型侧会硬闸报错 ⇒ 由下面原样抛出, 不静默
        t0 = time.time()
        svc.run_once(stage=stage, obs_frame=frame, obs_source=("encoder_model_frame"
                                                               if frame is not None else None),
                     write_evidence=False, skill_ctx=skill)
        lat = getattr(getattr(svc, "node", None), "runtime", None)
        lat = getattr(lat, "last_latent", None) or {}
        if not lat:
            raise RuntimeError("INTACT 未返回潜表示 (last_latent 空) ⇒ 编码模型不可用")
        out = {k: np.asarray(v, float).ravel() for k, v in lat.items()}
        out["_ms"] = round((time.time() - t0) * 1e3, 1)
        out["_policy"] = self.policy
        return out

    # ── 潜表示 → 引擎流形坐标 (全部经**已过闸**的标定, 每段可追溯) ──
    def to_manifold(self, lat: dict, engine_dim: int = 16) -> tuple:
        fm = self.fiber_map()
        z_pred = np.asarray(lat.get("z_pred"), float).ravel()
        z_t = np.asarray(lat.get("z_t"), float).ravel()
        if z_pred.size != 192:
            raise ValueError("z_pred 维度 %d != 192 ⇒ 与标定口径不符" % z_pred.size)
        a = np.asarray(fm["z7_morph"]["w"], float)          # (7,192)
        zb = np.asarray(fm["z7_morph"]["b"], float)
        z7 = a @ z_pred + zb                                 # 预测的几何潜空间 R7
        g = np.asarray(fm["geom_contact"]["w"], float)        # (6,7)
        gb = np.asarray(fm["geom_contact"]["b"], float)
        contact = g @ z7 + gb                                # 接触丛 F_C(6)
        scal = np.array([                                              # 3 个真标量 (来自本次推理)
            float(np.linalg.norm(lat.get("delta") if lat.get("delta") is not None else z_pred - z_t)),
            float(np.linalg.norm(z_pred - z_t)),
            float(np.linalg.norm(z_pred)),
        ])
        z = np.concatenate([z7, contact, scal])
        if z.size < engine_dim:
            raise ValueError("编码模型输出 %d 维 < 引擎潜维 %d (需补标定, 不静默补零)" % (z.size, engine_dim))
        z = z[:engine_dim]
        note = ("编码模型 %s: z_pred(192)→z7_geo(7)[A, r²=%.3f] ⊕ 接触丛(6)[geom_contact, r²_loso=%.3f] "
                "⊕ 3 真标量(‖delta‖,‖z_pred−z_t‖,‖z_pred‖) ⇒ %d 维 · 推理 %.1fms · ckpt=%s"
                % (self.NAME, float(fm["z7_morph"]["r2"]), float(fm["geom_contact"]["r2_loso"]),
                   engine_dim, float(lat.get("_ms") or 0.0), self.policy))
        return z.astype(float), note

    def latent(self, frame=None, stage: str = "encoder_model", grip: float = 0.0,
               engine_dim: int = 16) -> tuple:
        """一步: 帧 → (引擎潜维向量, 口径说明)。"""
        lat = self.encode(frame=frame, stage=stage, grip=grip)
        return self.to_manifold(lat, engine_dim=engine_dim)


def provider_from(root: str = ROOT_DEFAULT, policy: str | None = None, frame_fn=None,
                  engine_dim: int = 16, strict: bool = True):
    """构造引擎用的 provider (callable → z) + 口径说明; 不可用 ⇒ 明确报因 (strict=True 时抛)。

    返回 (provider, note) 或 (None, why)。
    """
    m = IntactEncoderModel(root, policy)
    ok, why = m.available()
    if not ok:
        if strict:
            raise RuntimeError("编码模型不可用: %s" % why)
        return None, why
    state = {"n": 0}

    def _prov():
        fr = frame_fn() if callable(frame_fn) else None
        z, _note = m.latent(fr, engine_dim=engine_dim)
        state["n"] += 1
        return z

    return _prov, ("编码模型 %s (%s) · 每次 project() 真跑一次 INTACT 推理" % (m.NAME, m.policy))
