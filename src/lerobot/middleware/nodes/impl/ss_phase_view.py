# -*- coding: utf-8 -*-
"""ss_phase_view — 节点实现正文 (文件名 = 画布节点: ss_phase_view)。

🌀 相空间相图 (Θ,p) —— 可视化层观察器 (只读旁路)。
老倪 2026-11-20: 「要在 simulink 画布上加 相」 ⇒ 画布上加这一个节点, 双击出相图窗口。

口径 (与 tools/gui/phase_space.py · src/lerobot/manifold/state_space_energy.py 同一套, 不另立一套):
    轴向单自由度受迫阻尼振子 (SK07 插入段主模态):
        Θ̇ = p / m
        ṗ = −k_ax·Θ − b·p/m ,  b = α·k_ax
    H = p²/(2m) + ½·k_ax·Θ²            (相图上是椭圆等能线)
    数据源 zmax_data/ss_live/hamiltonian.json (🌍 万有引力 · ss_grav_h 每帧落);
    文件缺 ⇒ 只报「未出数」, 不造点 (工程真实性红线)。

引线: 🌍 万有引力 (ss_grav_h) out1 → 本节点 in1
entry: node_ss_phase_view   ·   registry key: ss_phase_view
"""
from __future__ import annotations

import json
import os
import time

from .shared_runtime import _SS_STATE  # noqa: F401  (总线状态, 供下游/单步查看)


def _repo_root():
    """向上找到仓库根 (同时含 zmax_data/ 与 tools/gui/phase_space.py 的最外层)。

    ⚠️ src/zmax_data 也存在(子目录), 只认 zmax_data 会误判 src/ ⇒ 必须两个标记一起认,
    并取**最外层**满足的那个 (仓库根)。
    """
    d = os.path.dirname(os.path.abspath(__file__))
    best = None
    for _ in range(8):
        if (os.path.isdir(os.path.join(d, "zmax_data"))
                and os.path.isfile(os.path.join(d, "tools", "gui", "phase_space.py"))):
            best = d
        nd = os.path.dirname(d)
        if nd == d:
            break
        d = nd
    if best:
        return best
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))))


def _ham_path():
    return os.path.join(_repo_root(), "zmax_data", "ss_live", "hamiltonian.json")


def compute_phase(sample=None):
    """一个相点 + 振子参数: → dict(ok, theta_mm, p, H, k_ax, alpha, m, zeta, age_s, src, err)

    sample 给了 (ctx['in1'] 的值) 就用总线来的实测, 否则读 ss_grav_h 落的 hamiltonian.json。
    """
    d = sample if isinstance(sample, dict) else None
    src = "bus:in1"
    if d is None:
        pth = _ham_path()
        src = pth
        try:
            with open(pth, encoding="utf-8") as f:
                d = json.load(f)
        except Exception as e:                                          # noqa: BLE001
            return {"ok": False, "err": "%s: %s" % (type(e).__name__, e), "src": pth}
    try:
        m = float(d.get("mass_kg") or 3.643)
        k = float((d.get("K_diag") or [0, 0, 400])[2])          # 轴向刚度 k_ax (N/m)
        alpha = float(d.get("alpha") or 0.15)
        b = alpha * k
        xi = d.get("xi") or [0] * 6
        xe = d.get("xi_e") or [0] * 6
        theta_mm = float(xe[2]) * 1000.0                        # 轴向位置偏差 Θ (mm)
        p_mom = m * float(xi[2])                                # 轴向动量 p (kg·m/s)
        H = float(d.get("H") or 0.0)
        if not H:                                               # 文件里没落 H ⇒ 按口径现算
            H = p_mom * p_mom / (2.0 * m) + 0.5 * k * (theta_mm / 1000.0) ** 2
        zeta = b / (2.0 * (k * m) ** 0.5) if k > 0 and m > 0 else 0.0
        age = max(0.0, time.time() - float(d.get("ts") or 0.0)) if d.get("ts") else -1.0
        return {"ok": True, "theta_mm": theta_mm, "p": p_mom, "H": H, "k_ax": k,
                "alpha": alpha, "m": m, "zeta": zeta, "age_s": age, "src": src}
    except Exception as e:                                              # noqa: BLE001
        return {"ok": False, "err": "字段不全 %s: %s" % (type(e).__name__, e), "src": src}


def node_ss_phase_view(ctx):
    """🌀 相空间相图 (Θ,p) — 读实测相点 → 打日志落 _SS_STATE → 双击打开相图窗口。

    引线: 🌍 万有引力 (ss_grav_h) out1 → 本节点 in1
    ▶运行 模式只算不开窗 (断点/无人值守时弹窗会冻住主线程, 与 3D 视图/操作视频同一条口径)。
    """
    log = ctx.get("log")
    label = ctx.get("label", "")
    module = ctx.get("module")
    try:
        r = compute_phase(ctx.get("in1"))
    except Exception as e:                                              # noqa: BLE001
        if log:
            log("⚠️ 相空间相图: 计算失败 %s: %s" % (type(e).__name__, e))
        return False
    if not r.get("ok"):
        if log:
            log("🌀 相空间相图: 未出数 (%s) — 先跑 🌍 万有引力节点 (ss_grav_h) 落 "
                "zmax_data/ss_live/hamiltonian.json; 不造点" % r.get("err"))
        return False
    _SS_STATE["phase"] = r
    if log:
        log("🌀 相空间相图: Θ %+.2f mm · p %+.4f kg·m/s · H %.5f J · "
            "k_ax %.0f N/m · α %.2f (ζ=%.2f) · m %.3f kg%s"
            % (r["theta_mm"], r["p"], r["H"], r["k_ax"], r["alpha"], r["zeta"], r["m"],
               ("  ⏸帧龄 %.1fs" % r["age_s"]) if r["age_s"] >= 0 else ""))
    if label == "▶运行":
        if log:
            log("🌀 相空间相图: 运行模式跳过弹窗 — 双击节点打开 (防断点冻结关不掉)")
        return True
    if module is not None and hasattr(module, "open_phase_space"):
        module.open_phase_space()
        return True
    if log:
        log("🌀 相空间相图: 无 GUI 宿主 (常驻循环/CLI 只算数据, 不开窗)")
    return True


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_phase_view
