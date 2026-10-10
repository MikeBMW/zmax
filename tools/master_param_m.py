#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主参数 M 的**能量标定** (老倪 2026-10-10: 「主参数要有值, 类比能量/能级」)

M 的物理身份 (来自 zmax_manifold.json 的 _doc): 等效惯量尺度 —— 物理类比 kg, 信息类比 Fisher/Hessian 曲率尺度。
本工具把它**算出来**: 用一个作业循环的峰值机械能 (动能 + 重力势能) 归一化, 并给出「能级」类比。

    单循环峰值机械能  E_task = ½·m_eff·v_peak² + m_eff·g·h_stroke        [J]
    等效惯量尺度      M      = 1 + E_task / E_ref                        (E_ref = 2.0 J, 光模块级单件基准)
    能级类比          E1 M<1.5 (单件轻载) · E2 1.5~3 (单臂常载) · E3 3~6 (带夹具/高速) · E4 ≥6 (双臂/满载)

为什么是"能量/能级"而不是拍一个数:
  · M 进的是二阶演化 v ← v + (F/M)·dt —— 它**就是**把力折算成加速度的"质量"。
    一个循环里末端+工件要带走多少机械能, 决定了这个等效质量该有多大 ⇒ 用能量定 M 是有量纲依据的。
  · 能级 = M 的离散档 (把连续的能量尺度离散成 E1~E4), 便于按项目/场景归档与比较。

真源与假设分得很清 (老倪零容忍): 每个输入都标 来源 或 **假设(可标定)**; 假设项一律列在输出里, 不藏。
写盘: 只写 config/calib/zmax_manifold.json 的 M / inertia / _energy_derivation, 备份+原子写+回读 sha256。

用法:
    python3 tools/master_param_m.py --project PROJ-TH-TRAY        # 算 + 打印推导 (不写)
    python3 tools/master_param_m.py --project PROJ-TH-TRAY --write # 写回真源 (备份+回读)
    python3 tools/master_param_m.py --all --json                  # 所有项目一次算
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFOLD = os.path.join(ROOT, "config", "calib", "zmax_manifold.json")
PLATFORM = os.path.join(ROOT, "config", "platform", "zmax_platform.json")
BOM = os.path.join(ROOT, "config", "platform", "zmax_project_bom.json")
CALIB = os.path.join(ROOT, "config", "calib", "zmax_calib.json")
G = 9.81
E_REF = 2.0          # 光模块级单件基准能量 [J]
M_RANGE = (0.0, 8.0)  # 与 zmax_manifold.json 的 _range 一致

# 项目 → 能量输入 (质量/行程来自真源; 速度与夹具质量无真源 ⇒ 明标 假设)
PROJECTS = {
    "PROJ-TH-TRAY": {
        "name": "泰国摆盘 (光模块 周转盘 → 上料 Tray 盘)",
        "part_kg": 0.025, "fixture_kg": None,       # fixture 从 calib.tool_payload 取
        "v_peak_mps": 0.30, "v_src": "假设(可标定): 宏微复合转运峰值 ≈0.3 m/s",
        "stroke_m": 0.45, "stroke_src": "真源: 升降行程 0~450mm (zmax_project_bom/结构参数)",
        "arms": 1,
    },
    "PROJ-LOAD-UNLOAD": {
        "name": "上下料 (料仓/料盘 → 夹具 上料 → 卸料 → 回收)",
        "part_kg": 0.025, "fixture_kg": None,
        "v_peak_mps": 0.25, "v_src": "假设(可标定): 上下料节拍 ≤8s 下的峰值 ≈0.25 m/s",
        "stroke_m": 0.30, "stroke_src": "假设(可标定): 上下料工位升降 ≈300mm (待现场确认)",
        "arms": 1,
    },
}


def sha256(p):
    try:
        return hashlib.sha256(open(p, "rb").read()).hexdigest()
    except Exception:  # noqa: BLE001
        return ""


def _load(p, d=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return d if d is not None else {}


def _tool_mass():
    """末端夹具+吸嘴质量 (真源 config/calib/zmax_calib.json#tool_payload.mass_kg)。"""
    return ((_load(CALIB, {}) or {}).get("tool_payload", {}) or {}).get("mass_kg")


def energy_level(M):
    return "E1 单件轻载" if M < 1.5 else ("E2 单臂常载" if M < 3 else ("E3 带夹具/高速" if M < 6 else "E4 双臂/满载"))


def compute(pid):
    p = PROJECTS[pid]
    tool = _tool_mass()
    fix = p["fixture_kg"] if p["fixture_kg"] is not None else tool
    fix_src = "真源: config/calib/zmax_calib.json#tool_payload.mass_kg" if p["fixture_kg"] is None else "假设"
    if fix is None:
        fix, fix_src = 1.0, "假设(可标定): tool_payload.mass_kg 缺失, 暂按 1.0 kg"
    m = float(fix) + float(p["part_kg"])
    v, h = float(p["v_peak_mps"]), float(p["stroke_m"])
    e_kin = 0.5 * m * v * v
    e_pot = m * G * h
    e_task = e_kin + e_pot
    M = 1.0 + e_task / E_REF
    M = max(M_RANGE[0], min(M_RANGE[1], round(M, 3)))
    return {
        "project": pid, "name": p["name"], "arms": p["arms"],
        "m_eff_kg": round(m, 4), "m_breakdown": {"夹具/吸嘴": fix, "工件": p["part_kg"]},
        "v_peak_mps": v, "stroke_m": h,
        "E_kin_J": round(e_kin, 4), "E_pot_J": round(e_pot, 4), "E_task_J": round(e_task, 4),
        "E_ref_J": E_REF, "M": M, "energy_level": energy_level(M),
        "sources": {"夹具/吸嘴": fix_src, "工件": "真源: 光模块 100G/400G QSFP 级 ≈25g",
                    "峰值速度": p["v_src"], "行程": p["stroke_src"]},
        "formula": "M = 1 + (½·m_eff·v² + m_eff·g·h) / E_ref",
    }


def write_manifold(res):
    d = _load(MANIFOLD)
    before = sha256(MANIFOLD)
    bak = MANIFOLD + ".bak_m_%s" % time.strftime("%Y%m%d_%H%M%S")
    shutil.copy2(MANIFOLD, bak)
    d["M"] = res["M"]
    d["inertia"] = False   # 🔴 不自动开: 开二阶惯性须先有 ΔV<0 证据 (MCD judge: "有惯性时须 ΔV<0"),
                           #    且真模型默认零回归 — 本工具只负责把 M 标出来, 开不开由现场授权决定
    d["_energy_derivation"] = {
        "project": res["project"], "name": res["name"],
        "formula": res["formula"], "m_eff_kg": res["m_eff_kg"],
        "E_kin_J": res["E_kin_J"], "E_pot_J": res["E_pot_J"], "E_task_J": res["E_task_J"],
        "E_ref_J": res["E_ref_J"], "energy_level": res["energy_level"],
        "sources": res["sources"], "updated_at": time.strftime("%F %T"),
        "inertia_note": "inertia=false 保持零回归; 要开二阶需现场标定证据 ΔV<0 (本工具不代开)",
        "by": "tools/master_param_m.py (老倪: 主参数要有值, 类比能量/能级)",
    }
    d["_updated_at"] = time.strftime("%F %T")
    tmp = MANIFOLD + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, MANIFOLD)
    back = _load(MANIFOLD)
    ok = back.get("M") == res["M"] and back.get("_energy_derivation", {}).get("E_task_J") == res["E_task_J"]
    return {"ok": ok, "sha_before": before[:16], "sha_after": sha256(MANIFOLD)[:16], "backup": bak,
            "readback": {"M": back.get("M"), "inertia": back.get("inertia"),
                         "energy_level": back.get("_energy_derivation", {}).get("energy_level")}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="PROJ-TH-TRAY", choices=sorted(PROJECTS))
    ap.add_argument("--all", action="store_true", help="所有项目一次算 (只打印)")
    ap.add_argument("--write", action="store_true", help="写回 zmax_manifold.json (备份+回读)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    res = {pid: compute(pid) for pid in (sorted(PROJECTS) if a.all else [a.project])}
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        for pid, r in res.items():
            print("─" * 78)
            print("项目 %s · %s" % (pid, r["name"]))
            print("  m_eff = %.4f kg  (= %s %.3f + 工件 %.3f)" % (r["m_eff_kg"], "夹具", r["m_breakdown"]["夹具/吸嘴"], r["m_breakdown"]["工件"]))
            print("  E = ½·m·v² + m·g·h = %.4f + %.4f = %.4f J   (v=%.2f m/s, h=%.2f m, E_ref=%.1f J)"
                  % (r["E_kin_J"], r["E_pot_J"], r["E_task_J"], r["v_peak_mps"], r["stroke_m"], r["E_ref_J"]))
            print("  ⇒ 主参数 M = %s     能级 = %s" % (r["M"], r["energy_level"]))
            print("  来源: " + " | ".join("%s=%s" % (k, v) for k, v in r["sources"].items()))
        print("─" * 78)
    if a.write and not a.all:
        w = write_manifold(res[a.project])
        print("写回 %s: %s" % (os.path.relpath(MANIFOLD, ROOT), "✅ 回读一致" if w["ok"] else "⛔ 回读不一致"))
        print("  sha %s → %s · 备份 %s" % (w["sha_before"], w["sha_after"], os.path.relpath(w["backup"], ROOT)))
        print("  回读: M=%s inertia=%s 能级=%s" % (w["readback"]["M"], w["readback"]["inertia"], w["readback"]["energy_level"]))
        return 0 if w["ok"] else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
