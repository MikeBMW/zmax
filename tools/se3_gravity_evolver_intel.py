#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧬 se3_gravity_evolver_intel.py — 550C 万有引力(SE(3)几何阻抗)参数自主进化

跑在 Intel Arc 上。进化的是**阻抗参数**, 不是网络权重:
    k_lat / k_ax / k_rot_lat / k_rot_ax / alpha(阻尼比) / sigma(力增益)

## 适应度 (四个分量, 各自归一化后接固定权重)
  ① 被动性  f_pass : V̇ ≤ 0 必须**恒成立**, 违反一次就整代作废 (硬约束, 不是加权项)
  ② 收敛性  f_conv : 从 2cm 偏差闭环积分到位的最终残余 ρ_end (越小越好)
  ③ 超调    f_over : 过程最大超调 (越小越好)
  ④ 力峰值  f_peak : 最大 |u| / u_max (限幅不该常年贴着跑)

**为什么不进化权重**: H-JEPA-MR 那轮踩过 —— 让适应度权重参与变异时,
分数 6.17→11.89 全靠 w_nll 0.30→0.98, 模型本身没变好。这里权重同样固定。

## 为什么被动性是硬约束而不是加权项
V̇ > 0 意味着控制器在往系统里注能量, 接触时必然震荡。加权的话可以被高分项掩盖,
所以一旦出现就整代判废 —— 这是安全性判据, 不是性能判据。

台账 ~/se3_gravity/evolve_ledger.json

用法 (Intel 上):
    PYTHONPATH=~/se3_gravity MR_GENS=6 ~/train_venv/bin/python evolve.py
"""
import json
import os
import os.path as osp
import sys
import time

import numpy as np

_R = os.environ.get("ZMAX_ROOT", "/home/intel/se3_gravity")
for _p in (osp.join(_R, "src"), _R, os.path.expanduser("~/se3_gravity")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

OUT = osp.expanduser("~/se3_gravity")
os.makedirs(OUT, exist_ok=True)
LEDGER = osp.join(OUT, "evolve_ledger.json")


def log(*a):
    print(*a, flush=True)


def _import_imp():
    """扁平 / 包结构双兼容。"""
    try:
        from lerobot.manifold.se3_impedance import (  # type: ignore
            Se3ImpedanceController, _xi_std_to_lie, potential, potential_rate)
    except Exception:
        from se3_impedance import (  # type: ignore
            Se3ImpedanceController, _xi_std_to_lie, potential, potential_rate)
    try:
        from lerobot.manifold.lie_intent import se3_exp  # type: ignore
    except Exception:
        from lie_intent import se3_exp                    # type: ignore
    return Se3ImpedanceController, se3_exp, _xi_std_to_lie, potential, potential_rate


def simulate(hp, m=1.0, dt=2e-4, steps=6000, goal_z=0.02):
    """质量-弹簧-阻尼闭环仿真 (m=1kg, 目标 +z 2cm)。

    🔴 u 的量纲是**力**, 必须 m·v̇ = u 再积分。第一版直接拿 u 当速度 ⇒ V 炸到 1.8e7。
    """
    (Se3ImpedanceController, se3_exp, _xi_std_to_lie,
     potential, potential_rate) = _import_imp()
    ctrl = Se3ImpedanceController(k_lat=hp["k_lat"], k_ax=hp["k_ax"],
                                  k_rot_lat=hp["k_rot_lat"], k_rot_ax=hp["k_rot_ax"],
                                  alpha=hp["alpha"], filter_alpha=1.0)
    Kf = np.zeros((6, 6)); Kf[2, 2] = hp["kf_z"]
    ctrl.Kf = Kf

    g_cur = np.eye(4)
    g_goal = np.eye(4); g_goal[2, 3] = goal_z
    v = np.zeros(6)
    V0 = potential(g_cur, g_goal, ctrl.K)
    Vs, abs_acc, u_peak, passive_bad = [], [], 0.0, 0
    z_hist = []
    for _ in range(steps):
        rec = ctrl.step(g_cur, g_goal, xi=v)
        Vs.append(rec["V"])
        if rec["Vdot"] > 1e-12:
            passive_bad += 1
        u_peak = max(u_peak, float(np.abs(rec["u"]).max()))
        a = rec["u"] / m
        v = v + a * dt
        g_cur = g_cur @ se3_exp(_xi_std_to_lie(v * dt))
        z_hist.append(float(g_cur[2, 3]))
    V_end = Vs[-1]
    rho_end = float(np.sqrt(max(2 * V_end / max(ctrl.K[2, 2], 1e-9), 0)))
    # 超调: 越过目标的量 (z > goal_z)
    over = max(0.0, max(z_hist) - goal_z) if z_hist else 0.0
    return {"ok": True, "passive_violations": passive_bad,
            "rho_end": rho_end, "V_end": float(V_end), "V0": float(V0),
            "overshoot": float(over), "u_peak": float(u_peak),
            "u_max": float(ctrl.u_max.max())}


def fitness_of(hp):
    """适应度: 被动性是硬闸, 其余三项归一化后固定权重加权。"""
    try:
        r = simulate(hp)
    except Exception as e:                                             # noqa: BLE001
        import traceback
        return {"ok": False, "why": "%s: %s" % (type(e).__name__, str(e)[:160]),
                "tb": traceback.format_exc()[-500:]}
    # ① 硬闸: 被动性违反一次就判废
    if r["passive_violations"] > 0:
        return {"ok": False, "why": "被动性违反 %d 次 ⇒ 整代作废"
                                    % r["passive_violations"], "raw": r}
    # ② 收敛 (ρ_end 越小越好; 1mm 是参考尺度)
    u_conv = -r["rho_end"] / 1e-3
    # ③ 超调 (0.5mm 参考)
    u_over = -r["overshoot"] / 5e-4
    # ④ 力峰值占比 (贴着 1.0 跑说明限幅在救场)
    u_peak = -(r["u_peak"] / max(r["u_max"], 1e-9))
    fit = 1.0 * u_conv + 0.5 * u_over + 0.3 * u_peak
    return {"ok": True, "fitness": float(fit), "u_conv": float(u_conv),
            "u_over": float(u_over), "u_peak": float(u_peak), "raw": r}


def load_ledger():
    if osp.exists(LEDGER):
        try:
            return json.load(open(LEDGER))
        except Exception:                                              # noqa: BLE001
            pass
    return {"entries": [], "best": None, "best_fitness": None}


def save_ledger(led):
    tmp = LEDGER + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(led, f, ensure_ascii=False, indent=1)
    os.replace(tmp, LEDGER)


BASE_HP = dict(k_lat=80.0, k_ax=400.0, k_rot_lat=2.0, k_rot_ax=10.0,
               alpha=0.15, kf_z=0.0)


def main():
    gens = int(os.environ.get("MR_GENS", "6"))
    margin = float(os.environ.get("MR_MARGIN", "0.05"))
    led = load_ledger()
    best = led.get("best")
    best_f = led.get("best_fitness")
    log("[550C] 万有引力(SE3几何阻抗)进化 · 已跑 %d 代 · best_fitness=%s"
        % (len(led["entries"]), best_f))

    rng = np.random.default_rng(int(os.environ.get("MR_SEED", "0")) + len(led["entries"]))
    accepted = rejected = 0
    for _ in range(gens):
        base = dict(best["hp"]) if best else dict(BASE_HP)
        hp = dict(base)
        # 变异: 刚度/阻尼比/力增益 (限幅不动 —— 那是硬件保护, 不许进化)
        hp["k_lat"] = float(np.clip(base["k_lat"] * rng.uniform(0.4, 2.2), 5.0, 500.0))
        hp["k_ax"] = float(np.clip(base["k_ax"] * rng.uniform(0.5, 2.0), 50.0, 2000.0))
        hp["k_rot_lat"] = float(np.clip(base["k_rot_lat"] * rng.uniform(0.4, 2.5), 0.2, 30.0))
        hp["k_rot_ax"] = float(np.clip(base["k_rot_ax"] * rng.uniform(0.4, 2.5), 0.5, 60.0))
        hp["alpha"] = float(np.clip(base["alpha"] * rng.uniform(0.5, 2.5), 0.03, 2.0))
        hp["kf_z"] = float(np.clip(base["kf_z"] + rng.uniform(-0.1, 0.3), 0.0, 1.0))

        t0 = time.time()
        r = fitness_of(hp)
        secs = time.time() - t0
        gen = len(led["entries"]) + 1

        if not r.get("ok"):
            log("[550C] gen%d 判废: %s" % (gen, r.get("why")))
            rejected += 1
            led["entries"].append({"gen": gen, "hp": hp, "ok": False,
                                   "why": r.get("why"), "secs": round(secs, 2)})
            save_ledger(led)
            continue

        f = r["fitness"]
        acc = (best_f is None) or (f > best_f + margin)
        if acc:
            best, best_f = {"hp": hp}, f
            accepted += 1
        else:
            rejected += 1
        raw = r["raw"]
        led["entries"].append({
            "gen": gen, "hp": hp, "ok": True, "fitness": round(f, 6),
            "u_conv": round(r["u_conv"], 6), "u_over": round(r["u_over"], 6),
            "u_peak": round(r["u_peak"], 6),
            "rho_end_mm": round(raw["rho_end"] * 1000, 6),
            "overshoot_mm": round(raw["overshoot"] * 1000, 6),
            "u_peak_N": round(raw["u_peak"], 4),
            "passive_violations": raw["passive_violations"],
            "secs": round(secs, 2), "accepted": bool(acc),
            "reason": "提升 → 采纳" if acc else
                      "未提升 (%.4f ≤ best %.4f + %.3f)" % (f, best_f or 0, margin)})
        led["best"], led["best_fitness"] = best, best_f
        save_ledger(led)
        log("[550C] gen%d fitness=%.4f (ρ_end=%.4fmm 超调=%.4fmm |u|峰=%.1fN) "
            "k=(%.0f,%.0f,%.1f,%.1f) α=%.3f %.1fs %s"
            % (gen, f, raw["rho_end"] * 1000, raw["overshoot"] * 1000, raw["u_peak"],
               hp["k_lat"], hp["k_ax"], hp["k_rot_lat"], hp["k_rot_ax"], hp["alpha"],
               secs, "采纳" if acc else "回滚"))

    out = {"ok": True, "when": time.time(), "gens": gens,
           "accepted": accepted, "rejected": rejected,
           "best_fitness": best_f, "best_hp": (best or {}).get("hp"),
           "n_entries": len(led["entries"]), "host": os.uname().nodename,
           "data": "质量-弹簧-阻尼闭环仿真 (m=1kg, 目标 +z 2cm)",
           "fitness_semantics": "被动性硬闸 + 收敛/超调/力峰值归一化加权; 非真机精度"}
    print("__RESULT__" + json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
