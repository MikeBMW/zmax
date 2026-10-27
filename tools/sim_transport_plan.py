#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sim_transport_plan.py — 左臂仿真搬运路径规划 (只规划 + 落盘, 不动真机一个字)

老倪 2026-10-27: 「用状态空间工程的 规划 plan 节点, 规划运送光模块的路径, 由左臂仿真
从左侧料盘抓起, 横移, 放下到右侧料盘, 全程都在 ar3d 里执行, 不需要动真正的机器人右臂」

两层, 各管各的:
  ① 任务层 = 状态空间工程的 plan 节点
     src/lerobot/policies/left_right/state_space/planner.py:TaskPlanner
     自然语言 → 技能 Token 序列 (只输出序列, 不进实时回路)。这一层的输出原样存进产物, 作为取证。
  ② 几何层 = 本文件
     槽位真源读 zmax_data/ar_rs/fences.json 的「左槽1~14 / 槽1~14」实测盒,
     每搬运一个模块生成 6 段(接近→抓取下降→抬起→横移→放置下降→抬起),
     14 个模块依次循环。

为什么几何层不照抄 token 序列:
  plan 节点的规则回退对"搬运"这类指令会给出 取料→对准→插入→检测 四个 token,
  其中"插入/检测"属于插装场景, 搬到另一个料盘没有插入动作。所以几何段按物理动作编排,
  token 序列只作为任务层意图留证 (产物里两个都存, 谁也别替谁背书)。

产出: zmax_data/runtime/traj/sim_transport.json
  {
    "at", "plan_tokens", "cycles": 14,
    "segs": [{"i","k","kind","p_from"[m],"p_to"[m],"label"}],
    "z_grasp","z_clear","n_segs"
  }

坐标: base 世界系, 单位米 (与 /api/tcp、fences.json 同系)。
左臂 base 在 (0, +0.5, 0) (tcp-ar.html:426 LARM.off), 页面播放时把点减掉这个偏移再解 IK。

用法:
  python tools/sim_transport_plan.py                 # 生成 14 循环并落盘
  python tools/sim_transport_plan.py --cycles 3      # 只排 3 个
  python tools/sim_transport_plan.py --show          # 只看已有的
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")
FENCES = os.path.join(REPO, "zmax_data", "ar_rs", "fences.json")
OUT = os.path.join(REPO, "zmax_data", "runtime", "traj", "sim_transport.json")

Z_CLEAR = 0.350      # 空中横移高度 (槽底 0.11 + 240mm)
Z_GRASP = 0.140      # 抓取/放置高度 (模块顶面约 0.125, tool1 压到模块中心附近)
Z_SAFE = 0.200       # 进出料盘前的过渡高度


def _load_slots() -> tuple[list, list]:
    """读左右两组槽的中心点 (世界系, 米)。左槽 = 名称以"左槽"开头。"""
    d = json.load(open(FENCES, encoding="utf-8"))
    left, right = {}, {}
    for it in d.get("items", []):
        n = (it.get("name") or "").strip()
        p1, p2 = it.get("p1"), it.get("p2")
        if not p1 or not p2 or it.get("type") != "box":
            continue
        c = [(p1[i] + p2[i]) / 2.0 for i in range(3)]
        if n.startswith("左槽"):
            num = "".join(ch for ch in n[2:] if ch.isdigit())
            if num:
                left[int(num)] = c
        elif n.startswith("槽"):
            num = "".join(ch for ch in n if ch.isdigit())
            if num:
                right[int(num)] = c
    return ([left[k] for k in sorted(left)], [right[k] for k in sorted(right)])


def _plan_tokens(instruction: str) -> list:
    """① 任务层: 调状态空间工程的 plan 节点。失败就如实记, 不编造。"""
    p = os.path.join(REPO, "src", "lerobot", "policies", "left_right", "state_space")
    if p not in sys.path:
        sys.path.insert(0, p)
    try:
        from planner import TaskPlanner                        # noqa: PLC0415
        tp = TaskPlanner()
        toks = tp.plan(instruction)
        return list(toks) if isinstance(toks, (list, tuple)) else [str(toks)]
    except Exception as e:                                     # noqa: BLE001
        return ["<plan 节点不可用: %s: %s>" % (type(e).__name__, e)]


def build(cycles: int) -> dict:
    left, right = _load_slots()
    if not left or not right:
        raise SystemExit("fences.json 里没有左槽/槽, 先确认 14 槽已画好")
    n = min(cycles, len(left), len(right))
    segs = []
    cur = None                                                 # 当前末端所在点 (空中)
    for k in range(n):
        L, R = left[k], right[k]
        p_l_up = [L[0], L[1], Z_CLEAR]
        p_l_safe = [L[0], L[1], Z_SAFE]
        p_l_grasp = [L[0], L[1], Z_GRASP]
        p_r_up = [R[0], R[1], Z_CLEAR]
        p_r_safe = [R[0], R[1], Z_SAFE]
        p_r_place = [R[0], R[1], Z_GRASP]

        def seg(kind, a, b, label):
            segs.append({"i": len(segs) + 1, "k": k + 1, "kind": kind,
                         "p_from": [round(v, 4) for v in a],
                         "p_to": [round(v, 4) for v in b], "label": label})

        # 从上一位置(或起点)平移到左槽上方
        seg("air", cur or p_l_up, p_l_up, "k%d 移到左槽%d上方" % (k + 1, k + 1))
        seg("down", p_l_up, p_l_safe, "k%d 下降到安全高度" % (k + 1))
        seg("down", p_l_safe, p_l_grasp, "k%d 接近抓取" % (k + 1))
        seg("up", p_l_grasp, p_l_up, "k%d 抓起并抬到横移高度" % (k + 1))
        seg("carry", p_l_up, p_r_up, "k%d 横移 左槽→右槽" % (k + 1))
        seg("down", p_r_up, p_r_safe, "k%d 下降到安全高度" % (k + 1))
        seg("down", p_r_safe, p_r_place, "k%d 对准右槽%d" % (k + 1, k + 1))
        seg("up", p_r_place, p_r_up, "k%d 放下并抬起" % (k + 1))
        cur = p_r_up

    return {
        "at": time.strftime("%F %T"),
        "source": "sim_transport_plan.py · 任务层=状态空间工程 plan 节点, 几何层=槽位实测盒",
        "plan_tokens": _plan_tokens("从左料盘逐个抓取光模块, 横移, 依次放到右侧料盘的14个槽位"),
        "cycles": n,
        "z_grasp": Z_GRASP, "z_clear": Z_CLEAR, "z_safe": Z_SAFE,
        "left_slots": len(left), "right_slots": len(right),
        "n_segs": len(segs),
        "segs": segs,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycles", type=int, default=14)
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args()

    if a.show:
        d = json.load(open(OUT, encoding="utf-8"))
        print("%s · %d 循环 · %d 段 · plan=%s" % (
            d.get("at"), d.get("cycles"), d.get("n_segs"),
            " ".join(d.get("plan_tokens") or [])))
        for s in d["segs"][:10]:
            print("  %2d k%-2d %-5s %s → %s" % (s["i"], s["k"], s["kind"], s["p_from"], s["p_to"]))
        return

    d = build(a.cycles)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    print("plan 节点 token:", " ".join(d["plan_tokens"]))
    print("槽位: 左 %d / 右 %d ⇒ 排了 %d 个循环, %d 段" % (
        d["left_slots"], d["right_slots"], d["cycles"], d["n_segs"]))
    print("首段:", d["segs"][0]["label"], d["segs"][0]["p_from"], "→", d["segs"][0]["p_to"])
    print("末段:", d["segs"][-1]["label"], d["segs"][-1]["p_from"], "→", d["segs"][-1]["p_to"])
    print("落盘:", OUT)


if __name__ == "__main__":
    main()
