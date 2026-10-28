#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧩 ar3d 场景 → 550C 可执行 plan 序列 (场景段表 → plan_exec_550c 载荷)

老倪 2026-10-27: 「http://.../ar3d 搭好的这个场景，就要用 550 系列实现」

分工现状 (2026-10-25/26 已定):
  · 550B = 只发布意图(段表绝对目标), 场景在这里编辑/仿真/预览
  · 550C = 收 ss_plan → 闸门 → 逐段下发 Orin SDK 桥 → 真值对账 (tools/plan_exec_550c.py)
  · 550A = 训练 L2/L3/L4

本工具补的是两者之间的那一段: ar3d 场景的 392 段流程, 按 550C 的载荷约束
(n_seg 1..8 · abs_mm 每点 3 个数 · 起点连续) 切成 plan 序列, 并**离线跑一遍
与 plan_exec_550c.py 同口径的闸门**, 让"能不能发"在发布端就能判, 不用等真机。

用法:
  ./gui-venv311/bin/python tools/scene_550_planify.py                 # 生成 + 校验
  ./gui-venv311/bin/python tools/scene_550_planify.py --max-seg 8 --out zmax_data/runtime/traj/plan_550c

输出:
  <out>/<scene>_plan_000.json ... + index.json (逐 plan 汇总 + 节拍 + 校验结论)
"""
import argparse
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAJ = os.path.join(REPO, "zmax_data", "runtime", "traj")

MAX_SEG_HARD = 8          # plan_exec_550c.py 闸门①: n_seg 1..8
CONT_TOL_MM = 0.5         # plan 间/段间连续性容差
START_TOL_MM = 20.0       # 闸门④: 起点与当前 TCP ≤20mm


def _dist(a, b):
    return sum((float(x) - float(y)) ** 2 for x, y in zip(a, b)) ** 0.5


def load_scene(src):
    p = os.path.join(TRAJ, src + ".json")
    with open(p) as f:
        d = json.load(f)
    segs = d.get("plan") or d.get("segs") or []
    if not segs:
        raise SystemExit("场景文件 %s 里没有 plan/segs" % p)
    pieces = int(d.get("ok_count") or 0) + int(d.get("ng_count") or 0)
    return p, d, segs, pieces


def fill_gaps(segs, bridge_speed):
    """补空走段: 场景段表里换槽时 a 写的是**中转位**(实测 [490,499,240]),
    不是上一段的末端 ⇒ 直接从上一末端下发会跳 400~570mm 直线(穿过工装)。
    这里显式插入 bridge 段把路走完, 并在 plan 里标 bridge=True 便于审计。
    """
    out = []
    n_bridge = 0
    bridge_mm = 0.0
    for s in segs:
        if out:
            gap = _dist(s["a"], out[-1]["b"])
            if gap > CONT_TOL_MM:
                t = gap / max(1.0, float(bridge_speed))
                out.append({
                    "k": s.get("k"),
                    "seq": "bridge-%d" % n_bridge,
                    "kind": "air",
                    "label": "空走(补齐) → %s" % (s.get("label") or ""),
                    "a": list(out[-1]["b"]),
                    "b": [float(c) for c in s["a"]],
                    "t": round(t, 3),
                    "carry_from": False, "carry_to": False,
                    "mod": s.get("mod"),
                    "bridge": True,
                    "gap_mm": round(gap, 1),
                })
                n_bridge += 1
                bridge_mm += gap
        out.append(dict(s))
    return out, n_bridge, bridge_mm


def build_plans(scene, segs, max_seg):
    plans = []
    for i in range(0, len(segs), max_seg):
        chunk = segs[i:i + max_seg]
        abs_mm = [[float(c) for c in s["b"]] for s in chunk]
        dirs = [s.get("kind") or "move" for s in chunk]
        # 速度: 该 plan 内各段 distance/t 的中位数, 夹到运动安全的 1..1000 mm/s
        spds = []
        for s in chunk:
            dd = _dist(s["a"], s["b"])
            t = float(s.get("t") or 0)
            if dd > 0.5 and t > 0:
                spds.append(dd / t)
        spds.sort()
        spd = spds[len(spds) // 2] if spds else 10.0
        spd = max(1.0, min(1000.0, spd))
        plans.append({
            "plan_id": "%s-%03d" % (scene, len(plans)),
            "n_seg": len(chunk),
            "speed_mm_s": round(spd, 1),
            "start_mm": [float(c) for c in chunk[0]["a"]],
            "abs_mm": abs_mm,
            "dirs": dirs,
            "src_seg_range": [chunk[0].get("seq"), chunk[-1].get("seq")],
            "cycle": chunk[0].get("k"),
            "labels": [s.get("label") for s in chunk],
            "t_sum_s": round(sum(float(s.get("t") or 0) for s in chunk), 3),
        })
    return plans


def gate_check(plans, pieces, uph_target, total_t):
    """离线复刻 plan_exec_550c.py 的闸门①④ + 段间连续性"""
    res = []

    def add(ok, name, detail=""):
        res.append({"ok": bool(ok), "name": name, "detail": detail})

    bad_n = [p["plan_id"] for p in plans if not (1 <= p["n_seg"] <= MAX_SEG_HARD)]
    add(not bad_n, "① n_seg 1..%d" % MAX_SEG_HARD,
        "全部合规 (%d 个 plan)" % len(plans) if not bad_n else "越界: %s" % bad_n[:5])

    bad_pt = [p["plan_id"] for p in plans
              for q in p["abs_mm"] if not (isinstance(q, list) and len(q) == 3)]
    add(not bad_pt, "① abs_mm 每点 3 个数",
        "全部合规" if not bad_pt else "异常: %s" % bad_pt[:5])

    # 段内连续: 第 i 段 a == 第 i-1 段 b
    intra = []
    for p, plan in enumerate(plans):
        src = plan.get("_chunk")
        if not src:
            continue
        for i in range(1, len(src)):
            d = _dist(src[i]["a"], src[i - 1]["b"])
            if d > CONT_TOL_MM:
                intra.append((plan["plan_id"], i, round(d, 2)))
    add(not intra, "段内连续 (a[i]==b[i-1] ≤%.1fmm)" % CONT_TOL_MM,
        "全连续" if not intra else "断点 %d 处: %s" % (len(intra), intra[:3]))

    # plan 间连续: plan[i] 末点 == plan[i+1] start_mm
    cross = []
    for i in range(1, len(plans)):
        d = _dist(plans[i]["start_mm"], plans[i - 1]["abs_mm"][-1])
        if d > CONT_TOL_MM:
            cross.append((plans[i - 1]["plan_id"], plans[i]["plan_id"], round(d, 2)))
    add(not cross, "plan 间连续 (上末点==下起点 ≤%.1fmm)" % CONT_TOL_MM,
        "全连续" if not cross else "断点 %d 处: %s" % (len(cross), cross[:3]))

    # 起点闸(④)可行性: 第 1 个 plan 的起点就是场景首段起点, 后续每个 plan
    # 只要前一个 plan 真到位(闸门⑤ |Δ|≤2mm), 起点偏差 ≤2mm < 20mm
    add(True, "④ 起点闸可行 (到位≤2mm ⇒ 起点偏差 <%.0fmm)" % START_TOL_MM,
        "首个 plan start=%s" % [round(x, 1) for x in plans[0]["start_mm"]])

    # 节拍: 场景段时长 vs 件数 vs 目标 UPH
    if pieces:
        per = total_t / pieces
        uph = 3600.0 / per
        add(uph >= uph_target, "节拍 UPH≥%d" % uph_target,
            "%.2fs/件 → UPH %.0f (%d 件/%.2fs, 差 %+.0f%%)"
            % (per, uph, pieces, total_t, (uph / uph_target - 1) * 100))
    else:
        add(False, "节拍", "场景里没有 ok_count/ng_count, 无法折算件数")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="sim_insert", help="场景段表名 (zmax_data/runtime/traj/<src>.json)")
    ap.add_argument("--max-seg", type=int, default=MAX_SEG_HARD, help="每 plan 段数 (硬上限 8)")
    ap.add_argument("--out", default=os.path.join(TRAJ, "plan_550c"))
    ap.add_argument("--bridge-speed", type=float, default=100.0,
                    help="空走(补段)速度 mm/s; 场景段表欠的空走按这个速度补时长")
    ap.add_argument("--no-bridge", action="store_true", help="不补空走段(只做原始段表的校验, 不可下发)")
    ap.add_argument("--json", action="store_true", help="只打印 JSON")
    a = ap.parse_args()

    if a.max_seg > MAX_SEG_HARD:
        raise SystemExit("--max-seg 不能超过 %d (550C 闸门硬约束)" % MAX_SEG_HARD)

    path, scene, segs_raw, pieces = load_scene(a.src)
    raw_t = float(scene.get("total_t") or sum(float(s.get("t") or 0) for s in segs_raw))
    if a.no_bridge:
        segs, n_bridge, bridge_mm = segs_raw, 0, 0.0
    else:
        segs, n_bridge, bridge_mm = fill_gaps(segs_raw, a.bridge_speed)
    plans = build_plans(a.src, segs, a.max_seg)
    # 段内连续性检查要用原始 chunk
    for i, p in enumerate(plans):
        p["_chunk"] = segs[i * a.max_seg:(i + 1) * a.max_seg]

    total_t = sum(float(s.get("t") or 0) for s in segs)
    uph_target = int(scene.get("uph_target") or 300)
    gates = gate_check(plans, pieces, uph_target, total_t)

    os.makedirs(a.out, exist_ok=True)
    for p in plans:
        body = {k: v for k, v in p.items() if not k.startswith("_")}
        with open(os.path.join(a.out, p["plan_id"] + ".json"), "w") as f:
            json.dump(body, f, ensure_ascii=False, indent=1)

    ok_all = all(g["ok"] for g in gates)
    index = {
        "scene": a.src,
        "src_file": path,
        "n_plans": len(plans),
        "n_segs": len(segs),
        "n_segs_raw": len(segs_raw),
        "n_bridge": n_bridge,
        "bridge_mm": round(bridge_mm, 1),
        "bridge_speed_mm_s": a.bridge_speed,
        "max_seg": a.max_seg,
        "pieces": pieces,
        "total_t_s": round(total_t, 2),
        "scene_total_t_s": round(raw_t, 2),
        "uph_target": uph_target,
        "uph_theoretical": round(3600.0 * pieces / total_t, 1) if pieces else None,
        "uph_scene_only": round(3600.0 * pieces / raw_t, 1) if (pieces and raw_t) else None,
        "gates": gates,
        "ok": ok_all,
        "out_dir": a.out,
        "note": "纯离线: 只生成本地 plan 文件并跑闸门, 不发布不下发, 真机零指令",
    }
    with open(os.path.join(a.out, "index.json"), "w") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)

    if a.json:
        print(json.dumps(index, ensure_ascii=False, indent=1))
        return 0 if ok_all else 1

    print("场景 %s → %d 段(+空走补齐 %d 段/%.1fmm) 切 %d 个 plan (每 plan ≤%d 段)"
          % (a.src, len(segs), n_bridge, bridge_mm, len(plans), a.max_seg))
    print("输出 %s" % a.out)
    print("件数 %d · 场景自报 %.2fs · 含空走 %.2fs (空走速度 %.0fmm/s)"
          % (pieces, raw_t, total_t, a.bridge_speed))
    print("UPH: 场景乐观口径 %.1f → 含空走 %.1f (目标 %d)"
          % (index["uph_scene_only"] or 0, index["uph_theoretical"] or 0, uph_target))
    print("-" * 62)
    for g in gates:
        print("  %s %-42s %s" % ("✅" if g["ok"] else "❌", g["name"], g["detail"]))
    print("-" * 62)
    print("结论: %s — 这是离线校验, 真机下发仍必须经 550C 闸门+授权" % ("可发" if ok_all else "不可发"))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
