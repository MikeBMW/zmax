# -*- coding: utf-8 -*-
"""🎯 Flow-Matching Action Head (DiT) — L3 层真执行

老倪 2026-10-29:「继续接入 L3 层, 从万有引力节点和 flow matching 节点接入;
                 原则上, L2 层是基础输出, L3 是加权修正」

本节点在链上的位置 (画布连线为唯一依据):
    in1 ← ssvlm / ss_lora_l4 / sslat   (条件: 潜空间 z / VLM 特征)
    in5 ← ssmani_c / ssmani_p / sslat  (流形坐标: 接触/性能代价)
    out1 → n_moveit / ssff             (L3 名义动作 → 执行/前馈固化)
    out2 → ss_grav_h.in3               (L3 力 → 万有引力分层力仲裁)

三条硬规矩 (老倪工程真实性零容忍):
  ① **动作来自真数据**: L3 名义动作 = `zmax_data/ss_live/chunk_latest.json` 的 `chunk[0]`
     (动作头/测地线解码的**真实输出**, 同 layer_forces.py 的 L3 唯一依据 —— 两处不各算一套)。
  ② **L2 基础 / L3 修正 的语义显式化**: 修正量 Δ = chunk[0] − ff[0] (ff = L2 前馈 MLP 输出),
     out1 同时给 base(L2) / nominal(L3) / delta(修正量), 谁在修正谁一目了然。
  ③ **模型前向只作结构自检, 不冒充推理**: `StateSpaceActionHead` 目前**没有训练权重**
     (文件自述: 真实推理需 smolvla_lew 训练加载), 所以前向结果**不参与输出**,
     只报 shape/耗时/参数量与 `weights=random` 标记; 配 `ZMAX_DIT_CKPT` 才加载真权重并转正。

铁律: 只读真值 / 不造数 / 不下发动作 (下发只走 l2_daemon + 8793 授权)。
"""
from __future__ import annotations
import os
import time
from .library import _REPO_ROOT


def _read_json(p):
    import json
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh) or {}
    except Exception:                                                        # noqa: BLE001
        return None


def _vec(a, n=3):
    try:
        v = [float(x) for x in (a or [])[:n]]
        return v if len(v) == n else None
    except Exception:                                                        # noqa: BLE001
        return None


def run(ctx):
    log = ctx.get("log")
    root = ctx.get("root") or _REPO_ROOT
    live = os.path.join(root, "zmax_data", "ss_live")
    try:
        import numpy as np

        ck = _read_json(os.path.join(live, "chunk_latest.json"))
        if not ck:
            if log:
                log("🎯 Flow-Matching: 缺 chunk_latest.json ⇒ 不出数, 不造数")
            return {"out1": None, "out2": None}
        tr = _read_json(os.path.join(live, "trace_live.json")) or {}
        age = (time.time() - os.path.getmtime(os.path.join(live, "chunk_latest.json")))

        # ── ① L3 名义动作 (真数据) / L2 基础 (ff) / 修正量 Δ ──────────────────
        ch = _vec((ck.get("chunk") or [None])[0], 4)
        ff = _vec((ck.get("ff") or [None])[0], 4)
        u0 = _vec((ck.get("u") or [None])[0], 4)
        if ch is None:
            if log:
                log("🎯 Flow-Matching: chunk[0] 取不到 ⇒ 不出数")
            return {"out1": None, "out2": None}
        delta = [round(ch[i] - ff[i], 6) for i in range(3)] if ff else None

        # ── ② 结构自检 (真前向, 但权重=随机 ⇒ 结果不参与输出) ────────────────
        selftest = {"ran": False}
        t0 = time.monotonic()
        try:
            import torch
            from lerobot.policies.smolvla_lew.state_space_action_head import StateSpaceActionHead
            head = StateSpaceActionHead(input_dim=7, action_dim=4, chunk_size=7)
            ckpt = os.environ.get("ZMAX_DIT_CKPT", "")
            weights = "random"
            if ckpt and os.path.exists(ckpt):
                sd = torch.load(ckpt, map_location="cpu")
                sd = sd.get("state_dict", sd) if isinstance(sd, dict) else sd
                try:
                    head.load_state_dict(sd, strict=False)
                    weights = os.path.basename(ckpt)
                except Exception as _e:                                      # noqa: BLE001
                    weights = "random(加载失败: %s)" % type(_e).__name__
            x = np.asarray(tr.get("末端") or [0, 0, 0], dtype=float)[:3]
            tgt = np.asarray([float(tr.get("光模块_x") or 0.0), float(tr.get("光模块_y") or 0.0),
                              float(tr.get("光模块_z") or 0.0)], dtype=float)
            z7 = np.concatenate([x - tgt, x - np.asarray(tr.get("光模块头") or x, dtype=float)[:3],
                                 [float(tr.get("夹持") or 0.0)]])
            with torch.no_grad():
                out = head(torch.from_numpy(z7.astype(np.float32)).unsqueeze(0))
            selftest = {"ran": True, "shape": list(out.shape), "weights": weights,
                        "n_params": int(sum(p.numel() for p in head.parameters())),
                        "z_src": "trace_live: 末端−光模块 / 末端−光模块头 / 夹持 (R⁷)",
                        "ms": round((time.monotonic() - t0) * 1000, 2),
                        "note": ("权重已加载" if weights != "random"
                                 else "权重=随机(未训练) ⇒ 前向结果不参与动作输出, 动作来自 chunk_latest 真数据")}
        except Exception as e:                                               # noqa: BLE001
            selftest = {"ran": False, "err": "%s: %s" % (type(e).__name__, e),
                        "ms": round((time.monotonic() - t0) * 1000, 2)}

        # ── ③ 输出 (out1 给执行/前馈固化; out2 给万有引力 in3) ───────────────
        out1 = {
            "kind": "l3_nominal",
            "layer": "L3", "role": "加权修正",
            "base_L2": ff, "nominal_L3": ch, "delta": delta,
            "sub_ref": (u0 if u0 else None),
            "stage": ck.get("stage"), "cycle": ck.get("cycle"),
            "chunk_src": str(ck.get("chunk_src") or "")[:120],
            "ff_mode": ck.get("ff_mode"),
            "age_s": round(age, 3), "fresh": bool(age <= 5.0),
            "src": "zmax_data/ss_live/chunk_latest.json (chunk[0] / ff[0])",
            "selftest": selftest, "t": float(ck.get("ts") or time.time()),
        }
        out2 = {
            "layer": "L3",
            "vec": delta if delta is not None else ch[:3],
            "vec_semantics": ("修正量 chunk−ff (相对 L2 基础)" if delta is not None else "chunk[0] 绝对动作"),
            "nominal": ch[:3], "base": (ff[:3] if ff else None),
            "w_hint": "权重在 config/calib/layer_forces.json 的 w.L3 (热读, 见万有引力节点)",
            "age_s": round(age, 3), "fresh": bool(age <= 5.0),
            "src": "chunk_latest.chunk[0] − ff[0]",
        }
        if log:
            log("🎯 Flow-Matching (L3 加权修正): 名义=%s · L2 基础=%s · 修正Δ=%s · 阶段 %s · 帧龄 %.2fs"
                % ([round(x, 4) for x in ch[:3]], ([round(x, 4) for x in ff[:3]] if ff else None),
                   delta, ck.get("stage"), age))
            log("   前向自检: %s · %s" % (
                ("shape=%s · %s 参数 · %.2fms" % (selftest.get("shape"), selftest.get("n_params"),
                                                  selftest.get("ms", 0)))
                if selftest.get("ran") else ("未跑 (%s)" % selftest.get("err")),
                selftest.get("note") or selftest.get("err") or ""))
        return {"out1": out1, "out2": out2}
    except Exception as e:                                                   # noqa: BLE001
        if log:
            log("⚠️ Flow-Matching 节点失败: %s: %s" % (type(e).__name__, e))
        return {"out1": None, "out2": None}
