# -*- coding: utf-8 -*-
"""🌍 万有引力 · SE(3) 几何阻抗 + H=K+U — 全层力场仲裁

老倪 2026-10-28「把执行链上的节点按顺序迁出来」——
  实现正文从 registry 大文件 nodes/library.py 迁到本文件；library.node_ss_grav_h 只剩薄壳转调，
  右键「打开源代码」直接落到本文件 `run()`（registry key = `ss_grav_h`）。

执行链位置: 运动规划 → 🌍 万有引力 · SE(3) 几何阻抗 + H=K+U → 动作执行器 → 机器人执行器
铁律: 只读真值 / 不造数 / 不下发动作 (下发只走 l2_daemon + 8793 授权)。
本文件正文与迁移前逐字一致 (仅补显式 import 与文件头)。
"""
from __future__ import annotations
import os                                    # 正文里 os.path.join 用 (原在 library 模块级)
from .library import _HAM_CACHE, _NodeOut, _REPO_ROOT   # 与 registry 共用同一份运行时状态 (同源)


def run(ctx):
    log = ctx.get("log")
    root = ctx.get("root") or _REPO_ROOT
    live = os.path.join(root, "zmax_data", "ss_live")
    try:
        import json as _json
        import numpy as _np
        tr = _json.load(open(os.path.join(live, "trace_live.json"), encoding="utf-8"))
        try:
            ck = _json.load(open(os.path.join(live, "chunk_latest.json"), encoding="utf-8"))
        except Exception:                                                   # noqa: BLE001
            ck = {}
        # ① ② ③ 算式只有一份: state_space_energy.live_energy()（引擎 emit 每周期也调它,
        #   两处不各算一套 —— 公式/符号/单位改一处就全局一致）。
        from lerobot.manifold.state_space_energy import live_energy
        out = live_energy(root, _HAM_CACHE)
        U, K, F = float(out["U"]), float(out["K"]), out["F"]
        hd = float(out["hdot"])
        xi_e, stage = out["xi_e"], out["stage"]
        src_vel = out["xi_src"]
        try:
            os.makedirs(live, exist_ok=True)
            with open(os.path.join(live, "hamiltonian.json"), "w", encoding="utf-8") as fh:
                _json.dump(out, fh, ensure_ascii=False, indent=1)
        except Exception:                                                   # noqa: BLE001
            pass
        if log:
            log("🌍 万有引力: ξ_e=[%.1f,%.1f,%.1f]mm · U=%.6fJ · K=%.6fJ · H=%.6fJ · Ḣ=%.2e %s"
                % (xi_e[0] * 1000, xi_e[1] * 1000, xi_e[2] * 1000, U, K, K + U, hd,
                   "(被动✅)" if hd <= 0 else "(主动⚠)"))
            log("   力场: |F|=%.3fN (Fx %.3f · Fy %.3f · Fz %.3f) · 逐层 %s"
                % (out["F_norm"], F[0], F[1], F[2],
                   " ".join("%s %.3fN" % (k, float(_np.linalg.norm(v))) for k, v in out["F_layers"].items())))
            log("   数据源: %s · 阶段 %s · ξ 来自 %s · 落 zmax_data/ss_live/hamiltonian.json"
                % (str(out["src"])[:48], stage, src_vel))
        return _NodeOut(out)
    except Exception as e:                                                  # noqa: BLE001
        if log:
            log("⚠️ 万有引力节点: %s: %s (缺实况 ⇒ 不出数, 不造数)" % (type(e).__name__, e))
        return _NodeOut({"ok": False, "err": "%s: %s" % (type(e).__name__, e)})
