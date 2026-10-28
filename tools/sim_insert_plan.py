#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sim_insert_plan.py — 段表**薄壳 CLI** (规划本体已迁入状态空间节点)

老倪 2026-10-28: 「所有层的所有节点，要真正的状态空间代码执行」⇒ 段表由 **L2 Plan 节点**
自己算 (`src/lerobot/engineering/nodes/cycle_plan.py`, 由 `plan_long_impl` 每轮调用);
本脚本只剩两件事: ①算一遍落盘供对拍/离线查看 ②打印人看得懂的一轮编排 (轮次/驻留/节拍/UPH)。

用法: ./gui-venv311/bin/python tools/sim_insert_plan.py [--quiet]
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))

from lerobot.engineering.nodes import cycle_plan as CP                          # noqa: E402


def main():
    out = CP.build()
    path = CP.write(out)
    if "--quiet" in sys.argv:
        print(path)
        return
    plan, rounds, mods = out["plan"], out["rounds"], out["cycles_data"]
    print("写入", path)
    print("  轮次 %d · 模块 %d · 段 %d · 全程 %.1fs · 台均 %.2f s/个 · UPH %.0f"
          % (len(rounds), len(mods), len(plan), out["total_t"], out["tact_module_s"],
             len(mods) / out["total_t"] * 3600))
    print("  驻留(自然值) min %.2fs / max %.2fs · 良率 %.1f%% (%d NG / %d 件) · 配置指纹 %s"
          % (out["dwell_min_s"], out["dwell_max_s"], 100.0 * (1 - out["ng_ratio"]),
             out["ng_count"], out["mods"], out["cfg_sha"]))
    print("  孔 %d 个 · 节距 %dmm · 全在检测设备内: %s"
          % (len(out["holes"]), out["hole_pitch_mm"], out["holes_inside_device"]))
    lb = out["loop"]
    print("  稳态循环块: 轮 %s · %.2fs / %d 件 ⇒ %.2f s/件 · UPH %.1f"
          % (lb["ks"], lb["dur"], lb["mods"], lb["tact_s"], lb["uph"]))
    for rd in rounds:
        print("   R%-2d 孔%-6s 插 %-10s 拔 %-10s 作业 %5.1fs 等待 %5.1fs"
              % (rd["r"], str(rd["holes"]), str(rd["insert_mods"]), str(rd["pull_mods"]),
                 rd["t_work"], rd["t_wait"]))
    for m in mods:
        print("   %2d %-6s → %-6s 插R%d 拔R%d 驻留 %.0fs %s → %s"
              % (m["k"], m["slot_name"], "孔%d" % m["hole"], m["insert_round"], m["pull_round"],
                 m["dwell_s"], m["verdict"], m["target_label"]))


if __name__ == "__main__":
    main()
