#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""归档 v5.50.751 (「保存数据」= 归档目录 + MANIFEST + sha256, zmax_data 不进 git)。"""
from __future__ import annotations

import json
import os
import shutil
import time

REPO = "/home/ubuntu/zmax"
DST = os.path.join(REPO, "zmax_data", "release_5.50.751_20261020")

CODE = [
    "tools/lissa_fc.py",
    "tools/register_lissa_fc.py",
    "tools/rokae/sdk_power.py",
    "tools/rokae/insert_sdk_fc.py",
    "tools/rokae_sdk_run.sh",
    "tools/practice_insert_x3.py",
    "tools/ar_aoi_bus.py",
    "tools/gui/canoe_graphic.py",
    "tools/gui/ss_dreamview.py",
    "tools/verify_force6_signal_window.py",
    "tools/peg_d435_collect.py",
    "tools/peg_d435_train.py",
    "tools/insert_force_advance.py",
    "docs/INCIDENT-INDEX.md",
    "VERSION.md",
    "data/skills/l2_atomic/registry.json",
    "data/skills/l2_atomic/taught_points.json",
]
REPORTS = [
    "zmax_data/reports/insert_session_20261020_1918.json",
    "zmax_data/reports/insert_seat_1020c.json",
    "zmax_data/reports/insert_practice_x3.json",
]
LOGS = [
    "zmax_data/rokae_sdk/logs",
]


def main() -> int:
    if os.path.isdir(DST):
        shutil.rmtree(DST)
    for d in ("tools", "gui", "src", "docs", "data", "logs", "evidence"):
        os.makedirs(os.path.join(DST, d), exist_ok=True)
    n = 0
    for rel in CODE:
        src = os.path.join(REPO, rel)
        if not os.path.isfile(src):
            print("⚠️ 缺文件(跳过): %s" % rel)
            continue
        out = os.path.join(DST, rel)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        shutil.copy2(src, out)
        n += 1
    for rel in REPORTS:
        src = os.path.join(REPO, rel)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(DST, "data", os.path.basename(rel)))
            n += 1
    # 运行日志: 只留本轮的 lissa/push/seat CSV+JSON (体积可控)
    logdir = os.path.join(REPO, "zmax_data/rokae_sdk/logs")
    kept = 0
    if os.path.isdir(logdir):
        for f in sorted(os.listdir(logdir)):
            if not f.endswith((".csv", ".json")):
                continue
            if not any(k in f for k in ("lissa_20261020", "push_20261020", "seat_20261020",
                                        "insert_fc_", "sdk_ctl_20261020")):
                continue
            shutil.copy2(os.path.join(logdir, f), os.path.join(DST, "logs", f))
            kept += 1
            if kept >= 200:
                break
    meas = """# v5.50.751 实测数字 (全部来自本轮真机运行)

## 1. 插拔练习 ×3 (侧向 25N / 力矩 10Nm)
| 轮 | 判决 | 到点位误差 | 轴向峰 | 侧向峰 | 力矩峰 |
|---|---|---|---|---|---|
| 1 | lateral_stop | 2.87mm | 11.1N | 25.3N | 2.44Nm |
| 2 | axial_stop | 3.17mm | 30.1N | 13.9N | 3.26Nm |
| 3 | axial_stop | 3.47mm | 30.5N | 14.4N | 3.41Nm |

对照(前一版口径 侧向15N/力矩8Nm): 三轮分别差 26.997 / 25.47 / 23.907mm —— 侧向限太紧反而进不去。

## 2. 插入/拔出 (SDK 位置推 + 六维力被动看门狗)
- 拔出 speed8 (≈6.6mm/s): −19.99mm/3s, ΔFz 峰 14.8N; 再 −29.98mm, ΔFz 峰 4.3N (已脱离孔口)
- 后退 speed2 (≈1.9mm/s): −4.82~−4.89mm/5~6s, 侧向峰 2.6~5.6N
- 解止口 (侧向 20N / 力矩 8Nm): −2.81mm/3.1s, 侧向 Δ 峰 13.9N, 力矩 Δ 峰 7.28Nm, 松后 |F| 15.1N = 自由基准

## 3. 楔紧事故与卸力 (INC-20261020-04)
- axial_stop 之后 stop() 只保持位置 ⇒ 六维力自涨 35N → 119.8N → **178.8N** (fx −165.9N, |T| 54.8Nm)
- `move-rel --dx -3` 回退 3mm ⇒ **12.6N** (|T| 0.4Nm)
- 已在脚本内改为「力停手后自动沿轴退 1.5mm 卸力」

## 4. 信号分析波形连续性
- 改前: ar_aoi_bus sleep 下限 0.5s + DDS take(timeout=0.30) ⇒ pull() 400ms/轮 ⇒ 0.5~2Hz
- 改后: sleep 0.05s + DDS 降频 1s 缓存 + 二次起 timeout 0.02s ⇒ pull() 101ms
- 实测: 3s 内 19 次更新 = **6.3Hz**, 间隔中位 166ms / 最大 269ms

## 5. 力扫描找孔 (--mode scan)
- 自由段 5 点十字 (±0.5mm): 侧向 Δ 0.38~1.62N, fz +0.81~1.42N ⇒ 判定"未接触", 避免盲推
- 结论: 模块尖端与孔口仍有横向偏差时, 摆幅 ±0.2mm 只推进 1.2mm 就顶 30N; ±1.2mm 能推进 3.2mm

## 6. 计划节点自验
- `tools/lissa_fc.py --selftest`: 解析自检 PASS
- 空中实跑 `--mode lissa --travel-mm 2`: verdict=done, advanced=2.0mm, 退出码 0
- registry.json: L2.lissa_fc / L2.seat_fc 已注册 (技能总数 99)
"""
    open(os.path.join(DST, "evidence", "measured_20261020.md"), "w", encoding="utf-8").write(meas)
    man = """# 归档 v5.50.751 (2026-10-20)

主题: 里萨如力控插拔下沉为计划节点 + 插入安全三道闸 + 信号分析连续性

## 本轮改动
- 新增 `tools/lissa_fc.py`: 计划/画布节点入口, 把 insert_sdk_fc.py(容器内) 包装成本地脚本+参数, 输出单行 JSON(verdict/推进量/三轴峰/卸力后|F|)
- 新增 `tools/register_lissa_fc.py`: 注册 L2.lissa_fc / L2.seat_fc 两个 script 型计划节点
- 新增 `tools/rokae/sdk_power.py`: 上电/下电 (setPowerState(bool)); off/manual 时所有运动被拒却只表现为"不动"
- `tools/rokae/insert_sdk_fc.py`: 新增 unload_after_stop() 自动卸力 · 预静止闸(残留 MoveL 队列) · --mode scan 力扫描找孔
- `tools/ar_aoi_bus.py`: 节流下限 0.5s→0.05s · DDS 降频+缓存 · 原子写 tmp 按 pid 唯一 ⇒ 波形 0.5Hz→6.3Hz
- `tools/gui/canoe_graphic.py`: CORE_SIGNALS 16 条(六维力全量)
- `docs/INCIDENT-INDEX.md`: INC-20261020-02/03/04

## 目录
- `tools/ gui/ docs/ data/` 本轮改过的代码与注册表(不是整仓)
- `data/` 会话报告 + 到位候选 + 练习汇总
- `logs/` 本轮 lissa/push/seat 的 CSV/JSON (20ms 一行六维力+推进量)
- `evidence/measured_20261020.md` 全部实测数字
"""
    open(os.path.join(DST, "MANIFEST.md"), "w", encoding="utf-8").write(man)
    # sha256
    lines = []
    for root, _dirs, files in os.walk(DST):
        for f in sorted(files):
            if f == "sha256sums.txt":
                continue
            p = os.path.join(root, f)
            rel = os.path.relpath(p, DST)
            import hashlib
            h = hashlib.sha256(open(p, "rb").read()).hexdigest()
            lines.append("%s  %s" % (h, rel))
    lines.sort(key=lambda s: s.split("  ", 1)[1])
    open(os.path.join(DST, "sha256sums.txt"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    size = sum(os.path.getsize(os.path.join(r, f)) for r, _d, fs in os.walk(DST) for f in fs)
    print("归档 %d 份代码/数据 · logs %d 份 · 文件行 %d · 体积 %.1fMB" % (n, kept, len(lines), size / 1e6))
    print("目录: %s" % DST)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
