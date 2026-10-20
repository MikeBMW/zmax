#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lissa_fc.py —— 里萨如力控插拔 (xCoreSDK 直连) 的计划/画布节点入口。

为什么要有这一层:
  `insert_sdk_fc.py` 必须跑在 SDK 容器里 (`tools/rokae_sdk_run.sh --script ...`),
  而计划节点/画布按钮只会 exec 一个本地脚本 + 参数 ⇒ 这里做参数→容器命令的翻译,
  并把脚本的人读输出解析成**一行 JSON**(verdict / 推进量 / 三轴峰值 / 卸力后 |F|), 供计划节点判成功。

口径(真机红线, 与 insert_sdk_fc.py 一致, 这里只是转发, 不在这一层放宽):
  · 轴向硬红线 40N, 实际停手 ≤34N (脚本内 clamp, 命令行给更大也无效)
  · 侧向插入 20N / 解止口 25N; 力矩 10~12Nm; 全部可用参数下调
  · 任何 force/axial/lateral/torque_stop 之后脚本自动沿轴退 1.5mm 卸力 (stop() 只保持位置, 力不会自己掉)

用法:
  ./gui-venv311/bin/python tools/lissa_fc.py --mode lissa --travel-mm 50 --speed 2 --dry-run
  ./gui-venv311/bin/python tools/lissa_fc.py --mode lissa --travel-mm -30 --speed 8 --lat-max 25
  ./gui-venv311/bin/python tools/lissa_fc.py --mode seat --seat-pos 0.811571,0.230612,0.184349 \
      --seat-rpy 3.12260,-1.47094,0.07103 --speed 2
  ./gui-venv311/bin/python tools/lissa_fc.py --selftest        # 不动机器人: 只验参数→命令 + 输出解析

退出码: 0 = 走到位/走完全程 · 1 = 力停手/未到位 · 2 = 参数或连接错误
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OK_VERDICTS = ("done", "target_reached", "reached")

SAMPLES = """[12:00:00] 起点 TCP=[0.64730, 0.20590, 0.17430] · 工具Z=[+0.994,+0.052,-0.100]
[12:00:02] 李萨如: 轴向 50.0mm = 100 段 × 0.50mm · 侧向正弦 ±0.20mm @ 0.60/1.00Hz
[12:00:55] ↩ 自动卸力: 沿轴退 1.5mm ⇒ |F|=8.4N
[12:00:55] 结果: lateral_stop (侧向 Δ20.1N ≥ 20N ⇒ 停, 防划伤)
[12:00:55] 沿轴推进 43.50mm · 峰值 轴向 21.8N / 侧向 20.1N / 力矩 3.67Nm
[12:00:55] 到点位误差 0.25mm
"""


def build_cmd(a) -> list:
    inner = ["insert_sdk_fc.py", "--mode", a.mode]
    if a.mode == "seat":
        if not a.seat_pos or not a.seat_rpy:
            raise SystemExit("seat 模式必须给 --seat-pos 和 --seat-rpy")
        inner += ["--seat-pos", a.seat_pos, "--seat-rpy", a.seat_rpy,
                  "--approach-mm", str(a.approach_mm), "--fast-speed", str(a.fast_speed)]
    if a.mode in ("lissa", "push"):
        inner += ["--travel-mm", str(a.travel_mm)]
        if a.mode == "lissa":
            inner += ["--lissa-step", str(a.step), "--lissa-amp", str(a.amp),
                      "--lissa-adm-k", str(a.adm_k), "--lissa-adm-max", str(a.adm_max)]
    if a.mode == "scan":
        inner += ["--scan-mm", str(a.scan_mm)]
    inner += ["--speed", str(a.speed), "--stop-n", str(a.stop_n),
              "--lat-max", str(a.lat_max), "--lissa-tq-max", str(a.tq_max),
              "--timeout", str(a.timeout)]
    return ["bash", os.path.join(ROOT, "tools", "rokae_sdk_run.sh"), "--script"] + inner


def parse(text: str) -> dict:
    out: dict = {"verdict": None, "advanced_mm": None, "peak_axial_n": None,
           "peak_lateral_n": None, "peak_torque_nm": None, "err_mm": None,
           "unload_after_N": None}
    m = re.search(r"结果:\s*([A-Za-z_]+)", text)
    if m:
        out["verdict"] = m.group(1)
    m = re.search(r"沿轴推进\s*(-?[\d.]+)mm", text)
    if m:
        out["advanced_mm"] = float(m.group(1))
    m = re.search(r"峰值\s*轴向\s*([\d.]+)N\s*/\s*侧向\s*([\d.]+)N\s*/\s*力矩\s*([\d.]+)Nm", text)
    if m:
        out["peak_axial_n"] = float(m.group(1))
        out["peak_lateral_n"] = float(m.group(2))
        out["peak_torque_nm"] = float(m.group(3))
    m = re.search(r"到点位误差\s*([\d.]+)mm", text)
    if m:
        out["err_mm"] = float(m.group(1))
    m = re.search(r"自动卸力:.*?\|F\|=([\d.]+)N", text)
    if m:
        out["unload_after_N"] = float(m.group(1))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="里萨如力控插拔 (SDK直连) 计划节点入口")
    ap.add_argument("--mode", default="lissa", choices=["lissa", "push", "seat", "scan"])
    ap.add_argument("--travel-mm", type=float, default=50.0, help="推进量(+插/−拔) mm")
    ap.add_argument("--step", type=float, default=0.5, help="李萨如每段轴向 mm")
    ap.add_argument("--amp", type=float, default=0.2, help="李萨如侧向摆幅 mm")
    ap.add_argument("--adm-k", type=float, default=0.08, help="侧向导纳系数 (0=关)")
    ap.add_argument("--adm-max", type=float, default=2.0, help="侧向导纳饱和 mm")
    ap.add_argument("--scan-mm", type=float, default=0.5, help="力扫描每点偏移 mm")
    ap.add_argument("--speed", type=float, default=2.0, help="控制器档位 (实测 speed2≈1.9mm/s, 8≈6.6mm/s)")
    ap.add_argument("--stop-n", type=float, default=30.0, help="轴向停手 N (脚本内 ≤34)")
    ap.add_argument("--lat-max", type=float, default=20.0, help="侧向停手 N")
    ap.add_argument("--tq-max", type=float, default=10.0, help="力矩停手 Nm")
    ap.add_argument("--timeout", type=float, default=180.0, help="脚本内部超时 s")
    ap.add_argument("--seat-pos", default="", help="seat: x,y,z")
    ap.add_argument("--seat-rpy", default="", help="seat: rx,ry,rz (rad)")
    ap.add_argument("--approach-mm", type=float, default=12.0, help="seat: 轴向前置 mm")
    ap.add_argument("--fast-speed", type=float, default=6.0, help="seat: 快段档位")
    ap.add_argument("--dry-run", action="store_true", help="只打印将要执行的容器命令")
    ap.add_argument("--selftest", action="store_true", help="不动机器人: 验命令拼装 + 输出解析")
    a = ap.parse_args()

    cmd = build_cmd(a)
    if a.dry_run:
        print(" ".join(shlex.quote(c) for c in cmd))
        return 0
    if a.selftest:
        p = parse(SAMPLES)
        print(json.dumps({"cmd": " ".join(shlex.quote(c) for c in cmd), "parsed": p},
                         ensure_ascii=False, indent=1))
        need = {"verdict": "lateral_stop", "advanced_mm": 43.5, "peak_axial_n": 21.8,
                "peak_lateral_n": 20.1, "peak_torque_nm": 3.67, "unload_after_N": 8.4}
        bad = {k: (p[k], v) for k, v in need.items() if p[k] != v}
        print("解析自检:", "PASS" if not bad else "FAIL %r" % (bad,))
        return 0 if not bad else 2

    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=a.timeout + 180)
    text = (proc.stdout or "") + (proc.stderr or "")
    tail = "\n".join(text.strip().splitlines()[-14:])
    info = parse(text)
    info["exit_code"] = proc.returncode
    info["ok"] = info["verdict"] in OK_VERDICTS
    info["mode"] = a.mode
    info["cmd"] = " ".join(shlex.quote(c) for c in cmd)
    print(json.dumps(info, ensure_ascii=False))
    if not info["ok"]:
        print("--- 末尾输出 ---\n" + tail, file=sys.stderr)
    return 0 if info["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
