#!/usr/bin/env python3
"""原子技能 · 3D 约束通道 = **实际轨迹的扫掠包络** (AR 场景用)

老倪 2026-10-31: 「你的约束, 是实际轨迹的包络外表面 —— 只能让机器人在你的约束之内运行。」
              「为什么离机器人很远?」

错在哪 (前两版):
  v1 拿 trace_live 的 末端/光模块 (另一路话题, -78/641/188 mm) 当锚点, 又自己拼 "模块上方 90mm"
     这类端点 ⇒ 通道画在别处, 离 AR 里机器人一米多远。
  v2 换 sim_transport.json (490/922/350 那套槽位盒) —— 也不是 AR 页面按拍驱动的段表。

这一版只认真在跑的那条轨迹:
  唯一依据 = plan_long_impl 的段表 (_S["segs"], 392 段; AR 页面按拍驱动的 a→b 就是它,
             页面 /api/ar/cmd 也是同一个 plan 节点写的)
  轴心 = 每段真实的 a→b (不自己编端点); 同一种动作的**每一次机动**各一条管子
  半径 r = 该动作允许的外廓 (工具/夹爪/工件半径 + 间隙)
  ⇒ 通道外表面 = 实际轨迹的扫掠包络面; 机器人跑不出这个面。

技能分组 (按真实段 kind/label):
  接近 = move·「上方」     对位 = move·「孔口」     下降 = down       抓取 = grip
  抬起 = up               转移 = move·「行进高度」  插入 = insert+pull 完成 = release

用法:
  python3 tools/ss_corridor_build.py                 # 重算 8 段 + 写 AR 管道线
  python3 tools/ss_corridor_build.py --check 插入     # 单段自检 (轨迹点在内/越界被切外)
  python3 tools/ss_corridor_build.py --tact 1.43     # 覆盖节拍 (缺省用段表真实 t)
"""
from __future__ import annotations

import json
import math
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

OUT = os.path.join(ROOT, "zmax_data", "ss_live", "skill_corridors.json")
FENCES = os.path.join(ROOT, "zmax_data", "ar_rs", "fences.json")

# 每段包络半径 (mm): 搬移 = 工具外廓 25mm; 越靠孔口越收紧 ⇒ 管子越贴轨迹
R_MM = {"接近": 25.0, "对位": 8.0, "下降": 6.0, "抓取": 3.0,
        "抬起": 25.0, "转移": 25.0, "插入": 3.0, "完成": 6.0}
ORDER = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]
SK = {"接近": "SK01", "对位": "SK02", "下降": "SK03", "抓取": "SK04",
      "抬起": "SK05", "转移": "SK06", "插入": "SK07", "完成": "SK08"}


def _mm(p):
    return [round(float(p[0]), 3), round(float(p[1]), 3), round(float(p[2]), 3)]


def seg_table():
    """取 plan 节点真实的段表 (AR 页面就是按它按拍动画)。"""
    from lerobot.engineering.nodes import plan_long_impl as P

    P.run({})
    return list(P._S.get("segs") or []), float(P._S.get("tact") or 0.0)


def group_polys(segs):
    """按真实段分组 → 8 条技能的多折线集合 (每条折线 = 一次真实机动)。"""
    groups = {k: [] for k in ORDER}
    tsum = {k: 0.0 for k in ORDER}
    vneed = {k: 0.0 for k in ORDER}          # 该技能里最快那一段的"节拍要求速度" m/s
    for s in segs:
        kind = str(s.get("kind") or "")
        label = str(s.get("label") or "")
        a, b = s.get("a"), s.get("b")
        if not (isinstance(a, (list, tuple)) and isinstance(b, (list, tuple))):
            continue
        A, B = _mm(a), _mm(b)
        t = float(s.get("t") or 0.0)
        if kind == "move":
            st = "转移" if "行进高度" in label else ("对位" if "孔口" in label else "接近")
        elif kind == "down":
            st = "下降"
        elif kind == "grip":
            st = "抓取"
        elif kind == "up":
            st = "抬起"
        elif kind in ("insert", "pull"):
            st = "插入"
        elif kind == "release":
            st = "完成"
        else:
            continue
        if A == B:                                    # 零位移段 (夹爪/检测) ⇒ 1mm 微段占位
            B = [A[0], A[1], A[2] - 1.0]
        groups[st].append([A, B])
        tsum[st] += t
        _L = sum((B[k] - A[k]) ** 2 for k in range(3)) ** 0.5
        if t > 1e-6 and _L > 0:
            vneed[st] = max(vneed[st], (_L / 1000.0) / t)
    return groups, tsum, vneed


def build_all(tact_s=None):
    from lerobot.policies.left_right.state_space import corridor as C

    segs, tact_tab = seg_table()
    if not segs:
        print("⛔ plan 段表为空 ⇒ 不造通道")
        return None
    groups, tsum, vneed = group_polys(segs)
    corrs = {}
    for st in ORDER:
        polys = groups.get(st) or []
        if not polys:
            continue
        tact = float(tact_s) if tact_s else (tsum[st] / max(1, len(polys)))
        # 🕐 节拍驱动的速度上限: 该段真实最快机动要求 × 1.15 余量, 夹在 [0.35, 1.2] m/s
        #    自由段(接近/转移/抬起)会放到 0.6~1.0; 精细段(对位/下降/插入/抓取)本来需求就低, 仍是慢速
        v_cap_st = min(1.2, max(0.35, vneed[st] * 1.15 if vneed[st] else 0.35))
        corrs[st] = C.build_polys(st, polys, r_mm=R_MM[st], tact_s=tact,
                                  v_cap=v_cap_st, s_step_m=v_cap_st * 0.1)
        corrs[st]["n_poly"] = len(polys)
        corrs[st]["v_need"] = round(vneed[st], 4)
    return {"schema": "zmax.ss_skill_corridor/3", "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "source": "plan_long_impl._S['segs'] (AR 按拍段表)",
            "note": "轴心=每段真实 a→b; 半径=工具/工件外廓 ⇒ 外表面=实际轨迹包络面",
            "seg_total": len(segs), "tact_tab_s": tact_tab, "tact_s": tact_s,
            "corridors": corrs}


# ── AR: 每次真实机动画一根管子 (两条母线贴着 r 外廓 + 两端横档) ──────────
def _unit(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _add(a, b, k=1.0):
    return [a[0] + b[0] * k, a[1] + b[1] * k, a[2] + b[2] * k]


def _perp(u):
    a = [1.0, 0.0, 0.0] if abs(u[0]) < 0.9 else [0.0, 1.0, 0.0]
    e1 = _unit([u[1] * a[2] - u[2] * a[1], u[2] * a[0] - u[0] * a[2], u[0] * a[1] - u[1] * a[0]])
    e2 = _unit([u[1] * e1[2] - u[2] * e1[1], u[2] * e1[0] - u[0] * e1[2], u[0] * e1[1] - u[1] * e1[0]])
    return e1, e2


def _line(fid, name, p1, p2, color, note=""):
    return {"id": fid, "type": "line", "name": name,
            "p1": [round(x / 1000.0, 6) for x in p1], "p2": [round(x / 1000.0, 6) for x in p2],
            "color": color, "enabled": True, "no_collision": True, "note": note}


def write_ar_fences(doc):
    try:
        cur = json.load(open(FENCES, encoding="utf-8")) or {}
    except Exception:                                                     # noqa: BLE001
        cur = {}
    items = [it for it in (cur.get("items") or []) if not str(it.get("id", "")).startswith("COR-")]
    n = 0
    for st in ORDER:
        c = (doc.get("corridors") or {}).get(st)
        if not c:
            continue
        r, sid = float(c["r_mm"]), SK[st]
        note = "%s 包络 r=%.1fmm · %d 次机动 · 节拍 %.2fs" % (st, r, c.get("n_poly") or 1, c.get("tact_s") or 0)
        for j, pts in enumerate(c.get("polys") or []):
            for i in range(len(pts) - 1):
                p0, p1 = pts[i], pts[i + 1]
                if sum((p1[k] - p0[k]) ** 2 for k in range(3)) < 1e-9:
                    continue
                u = _unit([p1[k] - p0[k] for k in range(3)])
                e1, _e2 = _perp(u)
                for k, off in enumerate((e1, [-x for x in e1])):
                    items.append(_line("COR-%s-p%d-s%de%d" % (sid, j, i, k),
                                       "包络 %s #%d 母线%d-%d" % (sid, j + 1, i + 1, k + 1),
                                       _add(p0, off, r), _add(p1, off, r), "#2ea043", note))
                    n += 1
            for tag, (p, q) in (("s", (pts[0], pts[1])), ("e", (pts[-1], pts[-2]))):
                u = _unit([p[k] - q[k] for k in range(3)])
                e1, _e2 = _perp(u)
                items.append(_line("COR-%s-p%d-%scap" % (sid, j, tag), "包络 %s #%d 端环" % (sid, j + 1),
                                   _add(p, e1, r), _add(p, [-x for x in e1], r), "#2ea043", note))
                n += 1
    doc_f = dict(cur)
    doc_f["items"] = items
    doc_f["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    doc_f["src"] = "tools/ss_corridor_build.py (实际轨迹包络)"
    os.makedirs(os.path.dirname(FENCES), exist_ok=True)
    tmp = FENCES + ".tmp"
    json.dump(doc_f, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, FENCES)
    return n


# ── 自检 ────────────────────────────────────────────────────────────────
def check(doc, stage):
    from lerobot.policies.left_right.state_space import corridor as C

    c = (doc.get("corridors") or {}).get(stage)
    if not c:
        print("没有该段通道:", stage)
        return 2
    polys, r = c["polys"], float(c["r_mm"])
    print("%s (%s): %d 次真实机动 · 总长 %.2fmm · r=%.1fmm · 节拍 %.2fs"
          % (stage, SK[stage], len(polys), c["L_mm"], r, c.get("tact_s") or 0))
    worst = 0.0
    for pts in polys:
        for p in pts:
            worst = max(worst, C.closest_on_polys(polys, p)[0])
    print("  ① 全部轨迹点到最近轴心最大距离 = %.6f mm (应为 0)" % worst)
    p0 = polys[0][0]
    _, info = C.project_stage(stage, [0, 0, 0, 0], p0, c)
    print("  ② 轨迹起点: in_channel=%s dev=%.4fmm" % (info["in_channel"], info["dev_mm"]))
    u = _unit([polys[0][-1][k] - p0[k] for k in range(3)])
    e1, _e2 = _perp(u)
    k_mul = 3.0
    bad = _add(p0, e1, r * k_mul)
    while C.closest_on_polys(polys, bad)[0] <= r and k_mul < 40:   # 通道是并集: 逐级外移直到真在外面
        k_mul += 1.0
        bad = _add(p0, e1, r * k_mul)
    u_out, info2 = C.project_stage(stage, [e1[0] * .3, e1[1] * .3, e1[2] * .3, 0.0], bad, c)
    print("  ③ 越界 %.0fr: dev=%.2f 超 %.2fmm ⇒ u_out=%s · 削因 %s"
          % (k_mul, info2["dev_mm"], info2["excess_mm"], [round(x, 3) for x in u_out[:3]], info2["why"]))
    ok = worst < 1e-6 and info["in_channel"] and (not info2["in_channel"]) and ("切外" in info2["why"])
    print("  判定:", "✅ 轴心=实际轨迹, 越界被关回" if ok else "❌ 需查")
    return 0 if ok else 1


def table(doc):
    print("  段     技能   机动数  总长mm   半径mm  节拍s  轴向v上限  单拍mm")
    for st in ORDER:
        c = (doc.get("corridors") or {}).get(st)
        if not c:
            continue
        print("  %-4s  %-6s %4d  %8.1f  %6.1f  %6.2f  %9.4f  %6.2f"
              % (st, SK[st], c.get("n_poly") or 1, c["L_mm"], c["r_mm"],
                 c.get("tact_s") or 0, c["v_along_cap"], c["s_tick_mm"]))


def main():
    tact, stage = None, None
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        if argv[i] == "--tact" and i + 1 < len(argv):
            tact = float(argv[i + 1]); i += 2
        elif argv[i] == "--check" and i + 1 < len(argv):
            stage = argv[i + 1]; i += 2
        elif argv[i] in ("-h", "--help"):
            print(__doc__); return 0
        else:
            i += 1
    doc = build_all(tact_s=tact)
    if doc is None:
        return 2
    if stage:
        return check(doc, stage)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(doc, open(OUT + ".tmp", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(OUT + ".tmp", OUT)
    n = write_ar_fences(doc)
    print("包络通道 · 源 %s · 段表节拍 %.2fs/件" % (doc["source"], doc["tact_tab_s"]))
    table(doc)
    print("→ 真源 %s" % OUT)
    print("→ AR 管道线 %d 条 → %s" % (n, FENCES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
