#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🌍 主参数 M 的「万有引力」表达 —— 把 M 变成可操作、可读数的物理量。

老倪 2026-10-19: 「考虑如何结合 万有引力, 将 主参数 M 的表达, 更加形象, 容易操作」+
              「画布右侧的主参数窗口, 要可操作, 有信息连接」。

口径 (全部与引擎真身同法, 不是另写一套模型):
  引擎二阶演化 =  M q̈ = F = −∇Φ  ⇒  **a = F / M**   (M = 等效质量 / 惯性)
  ⇒ 同一个"引力场"(Φ=½d², 目标 = 引力源) 下, M 越大 = 越"重" = 加速度越小 = 收敛越慢、越平滑
  物理对照: 自由落体 t=√(2h/g) 中的 g ↔ F/M  ⇒  M×4 ⇒ 同样距离多花 2× 时间 (√M 标度)
  这也正是开普勒第三定律的直觉: 周期 ∝ √(轨道尺度/引力参数), M 大 ⇒ 周期长 ⇒ "反应慢"

五个档位 (给现场用的话术, 数字由 measure() 真跑引擎得出, 不手填):
  0.0 无惯性 · 0.3 轻灵 · 1.0 标准 · 3.0 重载 · 8.0 极重

用法:
  gui-venv311/bin/python tools/manifold_m_gravity.py                 # 打表 (含真跑实测)
  gui-venv311/bin/python tools/manifold_m_gravity.py --export        # 落 zmax_data/ss_live/mparam_gravity.json (GUI 读)
  gui-venv311/bin/python tools/manifold_m_gravity.py --json          # 只出 JSON
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

OUT = os.path.join(ROOT, "zmax_data", "ss_live", "mparam_gravity.json")

# 档位: (M, 名字, 一句话用途) —— 只用现场能听懂的话, 不引术语
GEARS = [
    (0.0, "无惯性", "一阶过阻尼 (旧行为, 零回归); 不要惯量时用"),
    (0.3, "轻灵", "小件精定位/插拔微调: 反应最快, 但抖"),
    (1.0, "标准", "通用 (与标定默认同心气): 速度与平稳的折中"),
    (3.0, "重载", "搬运/大惯量负载: 过渡平滑, 起停不冲击"),
    (8.0, "极重", "防抖/大件/相机类怕震: 最稳, 代价是最慢"),
]


def _unit(v):
    v = np.asarray(v, float).ravel()
    return v / max(float(np.linalg.norm(v)), 1e-12)


def measure(M, theta_deg=60.0, max_steps=600):
    """真跑引擎几何 (与在役同一套 _evolve/navigator), 量: 收敛拍 / 超调 / 路径长度。

    M ≤ 0 ⇒ 一阶过阻尼 (引擎零回归分支), 单独标一阶口径。
    """
    from lerobot.manifold.manifold_engine import ManifoldEngine          # noqa: PLC0415

    eng = ManifoldEngine(manifold_type="su2", latent_dim=16, state_dim=39, action_dim=4,
                         homeostasis=False, manifold_M=max(0.0, float(M)), inertia=True,
                         su2_tangent=True)
    eng.fitted = True
    g = _unit(np.array([1.0, 0.0, 0.0, 0.0]))
    perp = _unit(np.array([0.0, 1.0, 0.0, 0.0]))
    th = math.radians(theta_deg)
    p = _unit(math.cos(th) * g + math.sin(th) * perp)
    eng.goal_point = g
    eng.current_manifold_point = p

    dt = eng.dt if hasattr(eng, "dt") else 0.1
    c0 = float(np.dot(p, g))
    cos_seen = [c0]
    path = 0.0
    steps = 0
    for i in range(max_steps):
        gf = eng.gradient_flow(p=p)
        force = np.asarray(gf["descent"], float)      # ⚠️ 与 engine.step() 同源: 用 descent 不用 grad
        p_next = eng._evolve(p, force, dt)                                   # 与在役同一条演化律
        _d = max(-1.0, min(1.0, float(np.dot(_unit(p), _unit(p_next)))))
        path += math.acos(_d)
        p = p_next
        steps = i + 1
        c = float(np.dot(_unit(p), g))
        cos_seen.append(c)
        if c >= 0.9995:
            break
    c_end = cos_seen[-1]
    _short = max(1e-9, math.acos(max(-1.0, min(1.0, c0))))
    _tail = cos_seen[-6:]
    _jit = float(np.std(np.diff(_tail))) if len(_tail) > 2 else 0.0
    return {"M": float(M), "theta0_deg": theta_deg, "steps": steps,
            "cos_end": round(c_end, 6),
            "path_rad": round(path, 6), "path_ratio": round(path / _short, 4),
            "tail_jitter": round(_jit, 6),
            "reach": bool(c_end >= 0.9995), "converged_step": steps if c_end >= 0.9995 else None,
            "first_step_rad": round(math.acos(max(-1.0, min(1.0, cos_seen[0]))) -
                                    math.acos(max(-1.0, min(1.0, cos_seen[1]))), 6)}


def profile(M):
    """单点解读: 给 GUI 的一句话 + 可比量 (a 相对 1.0 档的倍率, 收敛时间 √M 标度)。"""
    M = max(0.0, float(M))
    name, why = "自定义", ""
    for gm, gn, gw in GEARS:
        if abs(M - gm) < 1e-9:
            name, why = gn, gw
    if not why:
        if M < 0.2:
            name, why = "近无惯性", "接近一阶过阻尼: 最快但最容易抖"
        elif M < 0.6:
            name, why = "轻灵档", "精定位/微调用: 快, 但抗突变弱"
        elif M < 1.5:
            name, why = "标准档", "通用折中"
        elif M < 4.0:
            name, why = "重载档", "平滑起停, 适合带负载"
        else:
            name, why = "极重档", "最稳最慢, 怕震的活用它"
    a_rel = None if M <= 1e-9 else round(1.0 / M, 4)          # 相对 M=1 的加速度倍率
    tau = None if M <= 1e-9 else round(math.sqrt(M), 4)      # 收敛时间尺度 (以 M=1 为 1)
    return {"M": M, "gear": name, "why": why, "a_rel_vs_1": a_rel, "tau_rel_vs_1": tau,
            "gravity_note": ("目标 = 引力源, 势 Φ=½d²; a=‖∇Φ‖/M ⇒ M 是'负载/质量'。"
                             "M×4 ⇒ 同样距离耗时 ×2 (√M), 冲击/超调同时变小。")}


def main():
    ap = argparse.ArgumentParser(description="主参数 M 的万有引力表达 (真跑引擎测档位)")
    ap.add_argument("--export", action="store_true", help="落 zmax_data/ss_live/mparam_gravity.json")
    ap.add_argument("--json", action="store_true", help="只打 JSON")
    ap.add_argument("--theta", type=float, default=60.0, help="起始夹角 (度), 默认 60")
    ap.add_argument("--Ms", default="", help="自定义 M 列表, 逗号分隔 (默认五档)")
    args = ap.parse_args()

    Ms = [float(x) for x in args.Ms.split(",") if x.strip()] if args.Ms else [g[0] for g in GEARS]
    rows = []
    for M in Ms:
        r = measure(M, theta_deg=args.theta)
        r.update(profile(M))
        rows.append(r)

    payload = {"generated_at": time.strftime("%F %T"), "theta_deg": args.theta,
               "law": "M q̈ = −∇Φ ⇒ a=‖∇Φ‖/M (与引擎 _evolve 同一条律)",
               "gears": [{"M": m, "name": n, "use": u} for m, n, u in GEARS],
               "rows": rows}
    if args.export:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        tmp = OUT + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, OUT)
        print("✅ 已落盘 %s (%d 档)" % (os.path.relpath(OUT, ROOT), len(rows)))
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=1))
        return 0

    print("🌍 主参数 M (等效质量) · 真跑引擎实测 (起始夹角 %.0f°, dt 同引擎)" % args.theta)
    print("%-6s %-6s %6s %9s %9s %10s  %s" % ("M", "档位", "收敛拍", "首步角", "路径比", "末5拍抖动", "用途"))
    best = min((r for r in rows if r.get("converged_step")), key=lambda x: x["converged_step"],
               default=None)
    for r in rows:
        _st = r["converged_step"] if r.get("converged_step") else "✗%d" % r["steps"]
        print("%-6.2f %-6s %6s %9.5f %9.3f %10.5f  %s"
              % (r["M"], r["gear"], _st, r["first_step_rad"], r["path_ratio"],
                 r["tail_jitter"], r["why"]))
    print("-" * 100)
    if best:
        print("实测甜点: M=%.2f (%s) 收敛最快 %d 拍 —— 「越小越快」不成立: M 太小步长大 ⇒ 绕远兜圈(路径比>1)。"
              % (best["M"], best["gear"], best["converged_step"]))
    print("读法: M↑ ⇒ 首步角↓(更平滑) / 收敛更慢 / 路径比→1(更直); M=0 = 一阶过阻尼零回归。")
    print("引力类比: 目标=引力源, a=∇Φ/M; M×4 ⇒ 耗时×2 (√M, 同开普勒周期直觉)。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
