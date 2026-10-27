#!/usr/bin/env python3
"""右臂插拔全流程规划 (2026-10-27 老倪)

「左臂上料以后, 右臂插拔, 规划轨迹, 从左侧第二个盘依次抓取光模块, 插入插孔,
  再拔出放到下料盘; 如果是检测失败, 则放到废料盘; 按照12个良品, 2个不良品, 规划抓取路径」

左侧第二个盘 = 黑色料盘 (y +0.1511~+0.5445) = 1~14 号位 = 右臂主盘。
每循环: 抓取 → 抬起 → 插拔准备点 → 插入口 → 插入 47mm → 停留检测 → 拔出 → 抬起
        → 良品去下料盘 (下槽1~12) / NG 去废料盘 (2 个位)

输出: zmax_data/runtime/traj/sim_insert.json
"""
import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "zmax_data", "runtime", "traj", "sim_insert.json")

# ── 14 个槽位 = 料盘槽盒中心 (fences 实测: 槽1~14 / 下槽1~14) ───────────────
#    注意: 1~7 号位示教点 (x≈648) 是夹爪位置, 与槽盒中心 (x≈491) 差 159mm,
#    画模块/定抓取点必须用槽盒中心, 否则模块会甩到盘外面 —— 老倪 2026-10-27 纠正。
SLOTS = [
    ("槽1",  [490, 499, 118]),
    ("槽2",  [491, 449, 118]),
    ("槽3",  [492, 401, 118]),
    ("槽4",  [492, 353, 118]),
    ("槽5",  [493, 303, 118]),
    ("槽6",  [492, 255, 118]),
    ("槽7",  [494, 205, 118]),
    ("槽8",  [617, 501, 118]),
    ("槽9",  [615, 451, 118]),
    ("槽10", [615, 404, 118]),
    ("槽11", [618, 355, 118]),
    ("槽12", [614, 307, 118]),
    ("槽13", [614, 260, 118]),
    ("槽14", [617, 212, 118]),
]

PREP = [691, 227, 271]        # 光模块插拔准备点
MOUTH = [767, 228, 278]       # 光模块插入口
INSERT = [814, 228, 278]      # 光模块插入点 (插到位)
DY_LOWER = -423.4             # 下料盘槽 = 黑盘槽 y - 423.4mm
SCRAP = [[469, -402, 120], [569, -402, 120]]   # 废料盘两个落点(200x200mm 盘内)

NG_IDX = {4, 11}              # 预设不良品: 4号位 / 11号位 (其余 12 个为良品)

LIFT = 100                    # 抓/放抬升高度 mm
TRAV_Z = 340                  # 插拔段的行进高度 mm
V = 200.0                     # 名义速度 mm/s (只用来摊时间)
T_GRIP = 0.4                  # 抓爪闭合/松开
T_CHECK = 0.5                 # 插到位后的检测停留


def dist(a, b):
    return sum((a[i] - b[i]) ** 2 for i in range(3)) ** 0.5


def seg(plan, k, kind, label, a, b, carry_from, carry_to, t=None):
    if t is None:
        t = max(0.30, round(dist(a, b) / V, 2)) + (T_GRIP if kind in ("grip", "release") else 0)
        t = round(t, 2)
    seq = 1 + sum(1 for p in plan if p["k"] == k)      # 循环内序号: 1..15
    plan.append({"k": k, "seq": seq, "kind": kind, "label": label,
                 "a": [round(v, 1) for v in a], "b": [round(v, 1) for v in b],
                 "t": t, "carry_from": carry_from, "carry_to": carry_to})


def main():
    plan, cycles = [], []
    cur = [647, 206, 240]      # 起始位置: 7 号位上方(真机最后已知)
    lower_k = 0                # 下料盘用第几个槽
    scrap_k = 0

    for i, (name, slot) in enumerate(SLOTS, start=1):
        ng = i in NG_IDX
        if ng:
            target = SCRAP[scrap_k % len(SCRAP)]
            scrap_k += 1
            tkind = "scrap"
            tlabel = "废料盘(不良品)"
        else:
            lower_k += 1
            # 下料盘落位 = 对应下槽盒中心 (与源盘同一排布, 整体 y-423.4mm), z 与槽盒中心同高
            target = [slot[0], round(slot[1] + DY_LOWER, 1), 118]
            tkind = "lower"
            tlabel = "下料盘 下槽%d" % lower_k

        above = [slot[0], slot[1], slot[2] + LIFT]
        # ① 到槽上方
        seg(plan, i, "move", "→ %s 上方" % name, cur, above, False, False)
        # ② 下降抓取
        seg(plan, i, "down", "下降到 %s" % name, above, slot, False, False)
        # ③ 夹爪闭合
        seg(plan, i, "grip", "夹爪闭合", slot, slot, False, True, t=T_GRIP)
        # ④ 抬起
        seg(plan, i, "up", "抓起抬起", slot, above, True, True)
        # ⑤ 到准备点上方
        seg(plan, i, "move", "→ 准备点上方", above, [PREP[0], PREP[1], TRAV_Z], True, True)
        # ⑥ 下降到准备点
        seg(plan, i, "down", "下降到准备点", [PREP[0], PREP[1], TRAV_Z], PREP, True, True)
        # ⑦ 平移到插入口
        seg(plan, i, "move", "→ 插入口", PREP, MOUTH, True, True)
        # ⑧ 插入到位 47mm
        seg(plan, i, "insert", "插入到位 47mm", MOUTH, INSERT, True, False)
        # ⑨ 检测停留
        seg(plan, i, "check", "检测判定 · %s" % ("NG" if ng else "OK"), INSERT, INSERT, False, False, t=T_CHECK)
        # ⑩ 拔出
        seg(plan, i, "pull", "拔出到口", INSERT, MOUTH, False, True)
        # ⑪ 抬起让开
        seg(plan, i, "up", "拔出抬起", MOUTH, [MOUTH[0], MOUTH[1], TRAV_Z], True, True)
        # ⑫ 到目标盘上方
        tab = [target[0], target[1], target[2] + 80]
        seg(plan, i, "move", "→ %s 上方" % tlabel, [MOUTH[0], MOUTH[1], TRAV_Z], tab, True, True)
        # ⑬ 下降放置
        seg(plan, i, "down", "下降到 %s" % tlabel, tab, target, True, True)
        # ⑭ 松开
        seg(plan, i, "release", "松开", target, target, True, False, t=T_GRIP)
        # ⑮ 抬起
        seg(plan, i, "up", "抬起脱离", target, tab, False, False)

        cur = tab
        cycles.append({"k": i, "slot_name": name, "slot": slot,
                       "verdict": "NG" if ng else "OK",
                       "target_kind": tkind, "target": target,
                       "target_label": tlabel,
                       "t_cycle": round(sum(p["t"] for p in plan if p["k"] == i), 2)})

    total = round(sum(p["t"] for p in plan), 2)
    out = {
        "ok": True, "cycles": len(cycles), "n_segs": len(plan),
        "total_t": total,
        "ok_count": sum(1 for c in cycles if c["verdict"] == "OK"),
        "ng_count": sum(1 for c in cycles if c["verdict"] == "NG"),
        "ng_slots": sorted(c["slot_name"] for c in cycles if c["verdict"] == "NG"),
        "src_tray": "黑色料盘(左侧第二个盘) 1~14 号位",
        "dst_ok": "下料盘 下槽1~%d" % lower_k,
        "dst_ng": "废料盘",
        "points": {"prep": PREP, "mouth": MOUTH, "insert": INSERT},
        "cycles_data": cycles,
        "plan": plan,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("写入", OUT)
    print("  循环 %d · 段 %d · 节拍 %.1fs · 良品 %d / NG %d (%s)"
          % (out["cycles"], out["n_segs"], total, out["ok_count"], out["ng_count"],
             ",".join(out["ng_slots"])))
    for c in cycles:
        print("   %2d %-6s %-3s → %-14s %.2fs" % (c["k"], c["slot_name"], c["verdict"],
                                                  c["target_label"], c["t_cycle"]))


if __name__ == "__main__":
    main()
