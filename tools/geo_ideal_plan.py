#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧭 测地线规划引导 · 理想规划 (300UPH 档) —— 命令行出口

实现只有一份: src/lerobot/engineering/nodes/geo_plan_impl.py 的 build_ideal_plan() / ideal_run()
本脚本只是把它跑出来给人看 + 落盘, 不另写一套几何/时序 (避免"脚本对、节点不对")。

L2 设计逻辑 (不变): obs43 → 流形投影 → 目标点 → 测地线 H 步 → 解码 → 块 chunk[H,4];
    out1 = 3D 引导位姿 · out2 = 块 · 下游 sslimit / sssched · 只规划不下发。
理想档: 现场没有 obs43 落盘, 所以几何取**执行器同一生成器** cycle_plan 的稳态窗口,
    段内用 S² 大圆测地线采样, 时序按理想剖面 (抬升/横移 1000, 下落/插入/拔 300)。
    与 fixed_cycle.json 逐段一致 (kind+a+b+t 112/112), 见 tools/compare_fixed_cycle_vs_fullflow.py。

用法:
  ./gui-venv311/bin/python tools/geo_ideal_plan.py           # 报告 + 300UPH 判定 (rc=0 成立)
  ./gui-venv311/bin/python tools/geo_ideal_plan.py --emit    # 落 zmax_data/ss_live/geo_ideal_plan.json
  ./gui-venv311/bin/python tools/geo_ideal_plan.py --run     # 真跑节点 ideal_run() 两拍, 看 out1/out2
  ./gui-venv311/bin/python tools/geo_ideal_plan.py --h 8
"""
from __future__ import annotations

import argparse
import json
import sys
import time

ROOT = "/home/ubuntu/zmax"
OUT = ROOT + "/zmax_data/ss_live/geo_ideal_plan.json"
sys.path[:0] = [ROOT, ROOT + "/src"]


def report(doc):
    print("=== 🧭 测地线规划引导 · 理想规划 ===")
    print("几何真源: %s" % doc["src"])
    m = doc["model"]
    print("模型    : 抬升/横移 %.0f mm/s a=%.0f · 下落/插入/拔 %.0f mm/s a=%.0f · 段内 S² 大圆 %d 点/段"
          % (m["v_fast"], m["a_fast"], m["v_slow"], m["a_slow"], m["H"]))
    print("段表    : %d 段 (运动 %.2fs + 流程 %.2fs)" % (doc["n_seg"], doc["move_s"], doc["proc_s"]))
    print("循环    : %.2f s / %d 件 → 节拍 %.3f s/件 → %.0f UPH" %
          (doc["cycle_s"], doc["mods"], doc["tact_s"], doc["uph"]))
    print("300UPH  : %s (节拍余量 %+.3f s, 门槛 12.000 s/件)" %
          ("成立 ✓" if doc["ok300"] else "不成立 ✗", doc["margin_s"]))
    top = sorted(doc["segs"], key=lambda s: -s["t"])[:6]
    print("最吃时间的 6 段 (段表 → 理想):")
    for s in top:
        print("   #%-3d %-9s %-24s %6.1fmm  %.2f → %.2f s" %
              (s["i"], s["kind"], (s["label"] or "")[:24], s["len_mm"], s["src_t"], s["t"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--h", type=int, default=8)
    ap.add_argument("--emit", action="store_true")
    ap.add_argument("--run", action="store_true", help="真跑节点 ideal_run() 两拍")
    a = ap.parse_args()

    from lerobot.engineering.nodes import geo_plan_impl as G      # noqa: PLC0415
    doc = G.build_ideal_plan(h=a.h)
    report(doc)

    if a.run:
        print("\n--- 节点 ideal_run() 两拍 (out1 引导位姿 / out2 块) ---")
        for k in range(2):
            o = G.run({"params": {"ideal": True}})
            v = o["out1"]["value"]
            print("  拍%d 段 %d/%d %-7s u=%.2f tcp=%s · 块 %d 点" %
                  (k + 1, v["seg_i"], v["seg_n"], v["kind"], v["u"], v["tcp"],
                   len(o["out2"]["value"]["chunk"])))
            print("      %s" % o["status"])
            time.sleep(2.0)

    if a.emit:
        json.dump(doc, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("\n已写 %s (%d 段 · %d 点/段)" % (OUT, doc["n_seg"], a.h))
    return 0 if doc["ok300"] else 1


if __name__ == "__main__":
    sys.exit(main())
