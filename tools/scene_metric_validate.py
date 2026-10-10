#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scene_metric_validate.py — 在**仿真场景**里验证性能指标 (老倪 2026-10-10)

「性能指标能在仿真场景验证」——本工具跑真引擎 (tools/gui/state_space_sim.py, 即画布 ▶运行 / L5 回路
背后的同一个 StateSpaceSim), 在 N 轮起始扰动下量出**仿真可量**的那些指标, 并与性能指标真源
config/platform/zmax_perf_spec.json 的目标值对照。

🔴 口径纪律 (老倪零容忍: 不以设计值冒充实测值, 指标不夸大):
   · 仿真能验的: 流程完整性(八阶段是否走完) · 成功率 · 节拍 · **重复性 σ** (对位/姿态的散布) ·
     力超调 · 终到残差 —— 这些是"结构/流程可复现性"的证据。
   · 仿真不能代替真机的: **绝对精度 (mm/µm 级)** · 力传感器分辨率 · 光耦合 IL/RL · ESD/洁净度/MTBF。
     仿真残差是模型尺度下的量, 与真机的 mm 口径不同源 ⇒ 一律标「真机待验」, 不换算、不冒充。
   · 本工具**不写**任何指标实测值 (perf_spec 里实测字段保持为空), 只出对照报告。

用法:
    python3 tools/scene_metric_validate.py                        # SCN-07-UP, 5 轮
    python3 tools/scene_metric_validate.py --n 9 --scene SCN-07-UP
    python3 tools/scene_metric_validate.py --json                 # 机器可读
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
PERF = os.path.join(ROOT, "config", "platform", "zmax_perf_spec.json")
SCENES = os.path.join(ROOT, "flows", "scenes_5jobs.json")
OUTDIR = os.path.join(ROOT, "outputs", "scene_metric_validate")

# 指标 → 验证通道 (仿真 / 真机) 与口径
CHANNEL = {
    "perf.success_rate": ("仿真", "N 轮起始扰动下 引擎 done=True 且 stage 到「完成」的比例 (仿真流程成功率)"),
    "perf.cycle_s": ("仿真", "到达「完成」阶段的仿真时间 tr['t'] (不含上下料真机换料/通讯开销)"),
    "perf.mate_align_repeat": ("仿真", "终态末端 X/Y 残差的 ±3σ (ISO 9283 重复性口径; 仿真尺度)"),
    "perf.mate_angle_repeat": ("仿真", "终态 peg 轴向相对 +Z 的倾角 ±3σ (仿真尺度)"),
    "perf.D_INSERT_mm": ("真机待验", "仿真残差是模型尺度量, 与真机 mm 口径不同源 ⇒ 真机(手眼+力控)口径"),
    "perf.insert_depth_res": ("真机待验", "分辨率由真机控制/编码器步长决定, 仿真无量化 ⇒ 真机口径"),
    "perf.force_res": ("真机待验", "力分辨率由真机力传感器量程/噪声决定 ⇒ 真机口径"),
    "perf.force_overshoot": ("仿真", "接触概率/力估计峰值相对稳态的过冲 (仿真力模型口径)"),
    "perf.face_gap": ("真机待验", "光口端面非接触间隙须真机测量 (仿真为刚体插孔, 无端面模型)"),
}


def check_ids():
    """判据: 场景 perf_metrics 与验证通道引用的每个 perf.* id, 必须能在性能指标真源里解析 (无悬空 id)。"""
    tg = targets()
    refs = {}
    for s in (_j(SCENES, {}) or {}).get("scenes", []):
        for mid in s.get("perf_metrics", []) or []:
            refs.setdefault(mid, []).append(s["scene_id"])
        for st in s.get("steps", []):
            for mid in str(st.get("metric", "")).split("/"):
                mid = mid.strip()
                if mid.startswith("perf."):
                    refs.setdefault(mid, []).append(s["scene_id"])
    for mid in CHANNEL:
        refs.setdefault(mid, []).append("validator")
    bad = {k: v for k, v in refs.items() if k not in tg}
    print("引用检查: %d 个 perf.* id, 悬空 %d %s" % (len(refs), len(bad), "✅ 全部可解析" if not bad else "⛔ " + str(bad)))
    return 1 if bad else 0


def _j(p, d=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return d if d is not None else {}


def targets():
    out = {}
    for g in (_j(PERF, {}) or {}).get("groups", []):
        for m in g.get("metrics", []):
            out[m["id"]] = {"cn": m.get("cn"), "unit": m.get("unit"), "target": m.get("target"),
                            "group": g.get("gid") + "·" + str(g.get("name"))}
    return out


def run_episode(seed, perturb=0.01, log=False):
    """一轮真引擎仿真 (起始扰动 = 重复性试验的工位差异)。"""
    import numpy as np  # noqa: PLC0415
    from state_space_sim import StateSpaceSim, X0  # noqa: PLC0415
    np.random.seed(seed)
    sim = StateSpaceSim(log=(print if log else None))
    sim.x = X0 + np.array([np.random.uniform(-perturb, perturb), np.random.uniform(-perturb, perturb), 0.0])
    tr = sim.run()
    st = [str(s).replace("阶段 ", "").split("·")[0].strip() for s in tr["stage"]]
    # 完成时刻
    t_done = next((float(tr["t"][i]) for i, s in enumerate(st) if s == "完成"), float(tr["t"][-1]))
    fin = len(tr["x"]) - 1
    xf = [float(v) for v in tr["x"][fin]]
    tf = [float(v) for v in tr["target"][fin]]
    peg = [float(v) for v in tr["peg"][fin]] if tr.get("peg") else [0, 0, 0]
    ph = [float(v) for v in tr["peg_head"][fin]] if tr.get("peg_head") else None
    ang = 0.0
    if ph:  # peg 轴向 = peg_head - peg  (相对 +Z 的倾角)
        d = [ph[i] - peg[i] for i in range(3)]
        n = math.sqrt(sum(v * v for v in d)) or 1e-9
        ang = math.degrees(math.acos(max(-1.0, min(1.0, abs(d[2]) / n))))
    fn = [float(v) for v in tr.get("force_norm", [])] or [0.0]
    steady = statistics.mean(fn[len(fn) // 2:]) if len(fn) > 4 else fn[-1]
    overshoot = ((max(fn) / steady - 1.0) * 100.0) if steady > 1e-9 else 0.0
    return {"seed": seed, "done": bool(tr["done"][-1]), "stages": len(set(st)),
            "stage_ok": "完成" in st and "插入" in st and "抓取" in st,
            "t_done_s": round(t_done, 3), "dist": round(float(tr["dist"][-1]), 5),
            "err_xy": [round(xf[0] - tf[0], 5), round(xf[1] - tf[1], 5)],
            "err_z": round(peg[2] - tf[2], 5) if tr.get("peg") else None,
            "tilt_deg": round(ang, 4), "force_overshoot_pct": round(overshoot, 3),
            "contact_p_max": round(max(float(v) for v in tr.get("contact_p", [0])), 3)}


def validate(scene_id="SCN-07-UP", n=5, seed_base=200):
    tg = targets()
    eps = [run_episode(seed_base + i) for i in range(n)]
    ok = [e for e in eps if e["done"] and e["stage_ok"]]
    xs = [e["err_xy"][0] for e in ok] or [0.0]
    ys = [e["err_xy"][1] for e in ok] or [0.0]
    an = [e["tilt_deg"] for e in ok] or [0.0]
    stats = {
        "n": n, "成功轮数": len(ok),
        "仿真成功率_%": round(100.0 * len(ok) / n, 1),
        "平均完成节拍_s": round(statistics.mean([e["t_done_s"] for e in ok]), 3) if ok else None,
        "节拍范围_s": [min([e["t_done_s"] for e in ok]), max([e["t_done_s"] for e in ok])] if ok else None,
        "对位X_3sigma_sim": round(3 * statistics.pstdev(xs), 5),
        "对位Y_3sigma_sim": round(3 * statistics.pstdev(ys), 5),
        "姿态角_3sigma_deg": round(3 * statistics.pstdev(an), 4),
        "力超调_%": round(statistics.mean([e["force_overshoot_pct"] for e in ok]), 3) if ok else None,
        "终到残差_sim": round(statistics.mean([e["dist"] for e in ok]), 5) if ok else None,
        "阶段完整性": all(e["stage_ok"] for e in eps),
    }
    rows = []
    for mid in CHANNEL:
        ch, how = CHANNEL[mid]
        t = tg.get(mid, {})
        val = {"perf.success_rate": stats["仿真成功率_%"],
               "perf.cycle_s": stats["平均完成节拍_s"],
               "perf.mate_align_repeat": max(stats["对位X_3sigma_sim"], stats["对位Y_3sigma_sim"]),
               "perf.mate_angle_repeat": stats["姿态角_3sigma_deg"],
               "perf.force_overshoot": stats["力超调_%"]}.get(mid)
        rows.append({"id": mid, "cn": t.get("cn"), "unit": t.get("unit"), "目标": t.get("target"),
                     "通道": ch, "仿真实测": val, "口径": how})
    return {"scene": scene_id, "scene_name": _scene_name(scene_id), "at": time.strftime("%F %T"),
            "episodes": eps, "stats": stats, "metrics": rows,
            "未在仿真验证的指标数": sum(1 for r in rows if r["通道"] != "仿真"),
            "纪律": "仿真值只作'流程/结构可复现'证据; 指标实测字段保持为空, 绝不拿仿真值冒充实测值"}


def _scene_name(sid):
    for s in (_j(SCENES, {}) or {}).get("scenes", []):
        if s.get("scene_id") == sid:
            return s.get("name")
    return sid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", default="SCN-07-UP")
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check-ids", dest="check_ids", action="store_true",
                    help="只查: 场景/通道引用的 perf.* id 是否都能在真源解析 (无悬空)")
    a = ap.parse_args()
    if a.check_ids:
        return check_ids()
    r = validate(a.scene, a.n)
    d = os.path.join(OUTDIR, time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(d, exist_ok=True)
    json.dump(r, open(os.path.join(d, "report.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0
    s = r["stats"]
    print("═" * 82)
    print("仿真场景指标验证 · %s · %s" % (r["scene"], r["scene_name"]))
    print("  引擎: tools/gui/state_space_sim.py (StateSpaceSim, 与画布 ▶运行/L5 同一引擎) · %d 轮起始扰动" % s["n"])
    print("  流程: 成功 %d/%d (%.1f%%) · 阶段完整性 %s · 平均节拍 %ss (范围 %s)"
          % (s["成功轮数"], s["n"], s["仿真成功率_%"], "✅" if s["阶段完整性"] else "❌",
             s["平均完成节拍_s"], s["节拍范围_s"]))
    print("  重复性(仿真尺度): 对位 X ±3σ=%s · Y ±3σ=%s · 姿态 ±3σ=%s° · 力超调 %s%% · 终到残差 %s"
          % (s["对位X_3sigma_sim"], s["对位Y_3sigma_sim"], s["姿态角_3sigma_deg"], s["力超调_%"], s["终到残差_sim"]))
    print("─" * 82)
    print("  %-24s %-22s %-10s %-10s %s" % ("指标", "目标值", "通道", "仿真实测", "口径"))
    for x in r["metrics"]:
        print("  %-24s %-22s %-10s %-10s %s" % (x["id"], str(x["目标"])[:22], x["通道"],
                                                 "—" if x["仿真实测"] is None else x["仿真实测"], x["口径"][:34]))
    print("─" * 82)
    print("  🔴 %s" % r["纪律"])
    print("  报告: %s" % os.path.relpath(os.path.join(d, "report.json"), ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
