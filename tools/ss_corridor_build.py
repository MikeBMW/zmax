#!/usr/bin/env python3
"""原子技能 · 3D 约束通道 构建器 (AR 场景用)

老倪 2026-10-31: 「你现在有 AR 动画仿真/UPH 节拍/每拍实际仿真动作/上升接近等状态和实际坐标;
根据 3D 坐标 + 动作状态 + 节拍, 调整运动学与动力学约束, 让每个原子动作都被约束在有效通道内;
把每个原子技能的通道边界画到 AR 场景里。」

做的事 (一条命令):
  ① 读 3D 真坐标: zmax_data/ss_live/trace_live.json 的 末端 / 光模块 (m, AR 场景同源)
  ② 按 8 段工艺几何造通道 (轴 A→B, 半径 r, 长度 L), 数字与 atomic_skills.clamp 同一套
     (v_cap/a_max/jerk/s_step 取自 config/calib/zmax_skill_physics.json, 缺则用技能类常量)
  ③ 节拍 (tact_s) 参与: ticks=tact/dt, 轴向速度 ≤ L/tact, 单拍行程 ≤ min(s_step, L/ticks)
  ④ 落盘 zmax_data/ss_live/skill_corridors.json  ← 技能过闸每拍读它 (同一真源)
  ⑤ 落盘 AR 场景边界线 zmax_data/ar_rs/fences.json (id=COR-SKxx, 轴 1 + 四边 4 条)

用法:
  python tools/ss_corridor_build.py                 # 建 8 条 + 写 AR 边界
  python tools/ss_corridor_build.py --tact 1.2      # 指定节拍 (s/段)
  python tools/ss_corridor_build.py --check 插入     # 只算一条, 打印边界与被削原因 (不改文件)
  python tools/ss_corridor_build.py --json          # 只打印 json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from lerobot.policies.left_right.state_space import corridor as C  # noqa: E402

LIVE = os.path.join(ROOT, "zmax_data", "ss_live")
CORR_JSON = os.path.join(LIVE, "skill_corridors.json")
PHYS_JSON = os.path.join(ROOT, "config", "calib", "zmax_skill_physics.json")
AR_FENCES = os.path.join(ROOT, "zmax_data", "ar_rs", "fences.json")

# 段名 → 技能类常量里的键 (真源 config/calib/zmax_skill_physics.json 段名同此)
STAGES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]
SK_ID = {"接近": "SK01", "对位": "SK02", "下降": "SK03", "抓取": "SK04",
         "抬起": "SK05", "转移": "SK06", "插入": "SK07", "完成": "SK08"}


def _live_points():
    """末端 / 光模块 (mm)。取不到就返回 None (如实, 不编坐标)。"""
    p = os.path.join(LIVE, "trace_live.json")
    try:
        t = json.load(open(p, encoding="utf-8")) or {}
    except Exception:                                                      # noqa: BLE001
        return None, None, {}
    e, m = t.get("末端"), t.get("光模块")
    if not (isinstance(e, (list, tuple)) and len(e) >= 3):
        return None, None, t
    E = [float(e[0]) * 1000.0, float(e[1]) * 1000.0, float(e[2]) * 1000.0]
    P = None
    if isinstance(m, (list, tuple)) and len(m) >= 3:
        P = [float(m[0]) * 1000.0, float(m[1]) * 1000.0, float(m[2]) * 1000.0]
    return E, P or [x + 40.0 for x in E], t


def _phys(stage):
    """段约束数字: 真源 json 优先, 缺项用技能类常量 (与 clamp 同源)。"""
    base = dict(v_cap=0.35, a_max=4.166667, jerk_max=15.0, s_step_m=0.035, dt=0.1)
    try:
        d = json.load(open(PHYS_JSON, encoding="utf-8"))
        seg = (d.get("skills") or d.get("segments") or d).get(stage) or {}
        for k_src, k_dst in (("v_cap", "v_cap"), ("a", "a_max"), ("a_max", "a_max"),
                             ("jerk", "jerk_max"), ("jerk_max", "jerk_max"),
                             ("s_step", "s_step_m"), ("s_step_m", "s_step_m"), ("dt", "dt")):
            if seg.get(k_src) is not None:
                base[k_dst] = float(seg[k_src])
    except Exception:                                                      # noqa: BLE001
        pass
    return base


def _targets(stage, E, P):
    """按工艺几何给 8 段造 A→B (mm)。"""
    up = lambda z: [P[0], P[1], P[2] + z]                                # noqa: E731
    return {
        "接近": (E, up(90.0)),
        "对位": (E, [P[0], P[1], E[2]]),
        "下降": (E, up(10.0)),
        "抓取": (E, [E[0], E[1], E[2] - 0.5]),
        "抬起": (E, [E[0], E[1], E[2] + 80.0]),
        "转移": (E, [P[0] + 60.0, P[1], P[2] + 40.0]),
        "插入": (E, [P[0], P[1], P[2]]),
        "完成": (E, [E[0], E[1], E[2] + 0.5]),
    }[stage]


def build_all(tact_s=None):
    E, P, trace = _live_points()
    if E is None:
        print("⛔ 没有 3D 真坐标 (zmax_data/ss_live/trace_live.json 缺 末端) ⇒ 不造通道, 不编坐标")
        return None
    out = {}
    for st in STAGES:
        a, b = _targets(st, E, P)
        ph = _phys(st)
        corr = C.build(st, a, b, v_cap=ph["v_cap"], a_max=ph["a_max"], jerk_max=ph["jerk_max"],
                       s_step_m=ph["s_step_m"], dt=ph["dt"], tact_s=tact_s)
        corr["pos_src"] = "trace_live.末端/光模块"
        out[st] = corr
    return {"schema": "zmax-skill-corridors", "version": "1.0",
            "built_at": time.strftime("%F %T"), "pos_src": "trace_live.json",
            "trace_stage": trace.get("阶段"), "tact_s": tact_s,
            "corridors": out}


def write_ar_fences(doc):
    """把通道边界写进 AR 场景围栏文件 (页面本来就渲染 line/box)。"""
    items = []
    try:
        old = json.load(open(AR_FENCES, encoding="utf-8")) or {}
        items = [it for it in (old.get("items") or []) if not str(it.get("id", "")).startswith("COR-")]
    except Exception:                                                      # noqa: BLE001
        pass
    at = time.strftime("%F %T")
    for st, corr in (doc.get("corridors") or {}).items():
        sid = SK_ID.get(st, st)
        for i, (p1, p2, kind) in enumerate(C.edges(corr)):
            items.append({
                "id": f"COR-{sid}-{'axis' if kind == 'axis' else f'e{i}'}",
                "type": "line",
                "name": f"约束通道 {sid} {st} {'轴' if kind == 'axis' else f'边{i}'} "
                        f"(r={corr['r_mm']}mm L={corr['L_mm']}mm)",
                "p1": [round(x / 1000.0, 5) for x in p1],
                "p2": [round(x / 1000.0, 5) for x in p2],
                "color": "#7ee787" if kind == "axis" else "#3fb950",
                "enabled": True,
                "note": f"技能约束通道 · 节拍 {corr.get('tact_s')}s/段 · 单拍 ≤{corr.get('s_tick_mm')}mm",
                "at": at,
            })
    doc2 = {"items": items, "margin_mm": 0, "at": at, "src": "tools/ss_corridor_build.py"}
    os.makedirs(os.path.dirname(AR_FENCES), exist_ok=True)
    tmp = AR_FENCES + ".tmp"
    json.dump(doc2, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, AR_FENCES)
    return len([i for i in items if str(i.get("id", "")).startswith("COR-")])


def table(doc):
    print(f"{'段落':<6}{'技能':<6}{'半径mm':>8}{'轴长mm':>9}{'节拍s':>7}{'轴向v上限':>11}{'单拍mm':>8}")
    for st, c in (doc.get("corridors") or {}).items():
        print(f"{st:<6}{SK_ID.get(st, ''):<6}{c['r_mm']:>8.2f}{c['L_mm']:>9.2f}"
              f"{(c.get('tact_s') or 0):>7.2f}{c['v_along_cap']:>11.4f}{c['s_tick_mm']:>8.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tact", type=float, default=None,
                    help="每段节拍 s (缺省按实测 UPH 314 → 11.47s/件 ÷ 8 段 = 1.43s)")
    ap.add_argument("--check", default=None, help="只算一段, 打印边界/越界判定 (不写文件)")
    ap.add_argument("--json", action="store_true", help="只打印 json")
    a = ap.parse_args()
    tact = a.tact if a.tact else 1.43
    if a.check:
        E, P, _ = _live_points()
        if E is None:
            print("⛔ 没有 3D 真坐标"); return 2
        ab = _targets(a.check, E, P)
        ph = _phys(a.check)
        corr = C.build(a.check, ab[0], ab[1], v_cap=ph["v_cap"], a_max=ph["a_max"],
                       jerk_max=ph["jerk_max"], s_step_m=ph["s_step_m"], dt=ph["dt"], tact_s=tact)
        u = [0.30, 0.0, 0.05, 0.0]
        uo, info = C.project_stage(a.check, u, [E[0] + corr["r_mm"] * 3, E[1], E[2]], corr)
        print(json.dumps({"corridor": corr, "u_in": u, "u_out": uo, "info": info},
                         ensure_ascii=False, indent=1))
        return 0
    doc = build_all(tact_s=tact)
    if doc is None:
        return 2
    if a.json:
        print(json.dumps(doc, ensure_ascii=False, indent=1)); return 0
    os.makedirs(LIVE, exist_ok=True)
    json.dump(doc, open(CORR_JSON + ".tmp", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(CORR_JSON + ".tmp", CORR_JSON)
    n = write_ar_fences(doc)
    table(doc)
    print(f"\n✅ 通道真源: {CORR_JSON}  (8 段)")
    print(f"✅ AR 边界线: {AR_FENCES}  (新增/更新 COR-* 共 {n} 条: 每段 轴1+四边4)")
    print(f"   节拍口径: {tact}s/段 (可 --tact 覆盖; UPH 314 实测 11.47s/件 ÷ 8)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
