# -*- coding: utf-8 -*-
"""wm_adapter.py — L4 世界模型 → L3 动作头的适配层（ZMP-2026-019）

职责
----
只做三件事：**懒加载权重、把候选修正量翻译成世界模型的输入、返回预测 d_perp**。
不做任何决策（决策在 `wm_verify.verify()`），不做任何降级判断之外的副作用。

真实链路（已在引擎 runtime.py 中验证）
--------------------------------------
    z7 = [ hx − target , hx − hole , grasped ]      7 维几何潜空间, 单位 **m**
    a4 = u_vec[:4]                                   4 维动作 (前 3 维位移 + 夹爪)
    WorldModelPredictor(z7, a4) → z' → ManifoldReadout → 6 维:
         [0]progress [1]risk [2]V [3]eta [4]rem [5]**d_perp**

单位契约（最容易出错的地方）
---------------------------
- z7 用 **m**（引擎口径）
- 修正量 Δξ 在本项目里用 **mm**（动作层口径）
- 因此 predict() 内部必须 `Δξ/1000` 再叠加到动作上
- 输出的 d_perp 是 **m**，调用方比较时两边都要同单位（本模块统一返回 m）

零回退契约
----------
权重缺失 / z7 缺失 / 任何异常 ⇒ 返回 `None`，调用方（wm_verify）据 None 判定
"不可验证 ⇒ 原样放行"。**绝不返回一个编造的预测值。**
"""
from __future__ import annotations

import os
import threading

import numpy as np

_LOCK = threading.Lock()
_CACHE: dict = {"model": None, "meta": None, "err": None, "path": None, "tried": False}

CKPTS = ("models/l4_mani_predictor_v5.pt",
         "models/l4_mani_predictor_v4.pt",
         "models/l4_mani_predictor_v2.pt")


def _repo_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", "..", "..", ".."))


def load(force: bool = False) -> dict:
    """懒加载世界模型权重（单例）。返回 meta dict，失败时含 err。"""
    with _LOCK:
        if _CACHE["tried"] and not force:
            return dict(_CACHE)
    meta: dict = {"model": None, "meta": None, "err": None, "path": None, "tried": True}
    try:
        import torch
        from lerobot.manifold.predictor_layer import WorldModelPredictor
        root = _repo_root()
        for rel in CKPTS:
            p = os.path.join(root, rel)
            if not os.path.exists(p):
                continue
            sd = torch.load(p, map_location="cpu", weights_only=False)
            if not isinstance(sd, dict):
                continue
            z_dim = int(sd["readout.mlp.0.weight"].shape[1])
            hidden, zin = sd["predictor.mlp.0.weight"].shape
            act_dim = int(zin - z_dim)
            n_linear = len([k for k in sd if k.startswith("predictor.mlp.") and k.endswith(".weight")])
            manifold_dim = int(sd["readout.mlp.4.weight"].shape[0])
            m = WorldModelPredictor(z_dim=z_dim, act_dim=act_dim, manifold_dim=manifold_dim,
                                    hidden_dim=int(hidden), num_layers=max(1, n_linear - 1))
            missing, unexpected = m.load_state_dict(sd, strict=False)
            if len(missing) or len(unexpected):
                continue
            m.eval()
            meta.update({"model": m, "path": rel,
                         "meta": {"z_dim": z_dim, "act_dim": act_dim,
                                  "manifold_dim": manifold_dim, "hidden": int(hidden),
                                  "layers": max(1, n_linear - 1)}})
            break
        if meta["model"] is None:
            meta["err"] = "无可用权重(检查 models/l4_mani_predictor_v*.pt)"
    except Exception as e:                                              # noqa: BLE001
        meta["err"] = "%s: %s" % (type(e).__name__, e)
    with _LOCK:
        _CACHE.update(meta)
        return dict(_CACHE)


def available() -> tuple[bool, str]:
    m = load()
    if m.get("model") is None:
        return False, m.get("err") or "未加载"
    return True, "ok(%s)" % m.get("path")


def predict_dperp(z7, delta_mm, base_action=None, *, model_box=None) -> float | None:
    """给定几何潜空间 z7 与**候选修正量(mm)**，返回预测的未来 d_perp（m）。

    z7            : 7 维（m）—— `[hx−target, hx−hole, grasped]`
    delta_mm      : 3 维候选修正量（mm），叠加到动作前 3 维
    base_action   : 4 维基础动作（默认沿用 z7 的夹持位与零位移）
    model_box     : 可选，复用已加载的模型（避免重复 load）

    返回 None ⇒ 不可预测（调用方零回退）
    """
    box = model_box or load()
    model = box.get("model")
    if model is None:
        return None
    try:
        import torch
        meta = box.get("meta") or {}
        zd, ad = int(meta.get("z_dim") or 7), int(meta.get("act_dim") or 4)
        z = np.asarray(z7, dtype=np.float32).reshape(-1)[:zd]
        if z.size < zd:
            return None
        a = np.zeros(ad, dtype=np.float32)
        if base_action is not None:
            b = np.asarray(base_action, dtype=np.float32).reshape(-1)
            a[:min(ad, b.size)] = b[:min(ad, b.size)]
        d = np.asarray(delta_mm, dtype=np.float32).reshape(-1)
        # 🔴 单位: Δξ 是 mm, 动作/z7 是 m
        a[:min(3, ad, d.size)] += d[:min(3, ad, d.size)] / 1000.0
        with torch.no_grad():
            out = model(torch.from_numpy(z).unsqueeze(0), torch.from_numpy(a).unsqueeze(0))
        mani = out["manifold"] if isinstance(out, dict) else out
        v = mani.reshape(-1)
        if v.numel() < 6:
            return None
        dp = float(v[5].item())
        return dp if np.isfinite(dp) else None
    except Exception:                                                   # noqa: BLE001
        return None


def make_predictor(z7, base_action=None):
    """给 `wm_verify.verify()` 用的 predict_fn：(delta_mm) → d_perp(m)。

    返回 None 表示不可用 —— verify() 会据此走零回退。
    """
    box = load()
    if box.get("model") is None or z7 is None:
        return None

    def _p(delta_mm):
        v = predict_dperp(z7, delta_mm, base_action, model_box=box)
        if v is None:
            raise RuntimeError("世界模型预测失败(权重/z7/推理异常)")
        return v

    return _p


def z7_from_state(state: dict | None = None) -> np.ndarray | None:
    """从进程内共享状态取 z7（引擎每帧写入）。取不到返回 None。"""
    if state is None:
        try:
            from .shared_runtime import _SS_STATE as _SS
        except Exception:                                               # noqa: BLE001
            try:
                from lerobot.middleware.nodes.impl.shared_runtime import _SS_STATE as _SS
            except Exception:                                           # noqa: BLE001
                return None
        state = _SS
    z = (state or {}).get("z7")
    if z is None:
        return None
    a = np.asarray(z, dtype=np.float32).reshape(-1)
    return a if a.size >= 7 and np.all(np.isfinite(a[:7])) else None


__all__ = ["load", "available", "predict_dperp", "make_predictor", "z7_from_state", "CKPTS"]
