#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_demo_cycle.py — 按现场演示的工序, **带夹爪时序**跑一整圈(或从某段开始)。

为什么要有这个: 我在"空跑"时漏了夹爪时序 —— 槽2夹一次之后一路闭着, 到钩拉环才发现没张开。
现场实物是这样走的(老倪 11-22 逐段口述 + 真值实测):
    抓取 → 夹紧(0) → 搬运/扫码/插入 全程夹紧 → 拉环解锁前**必须全开(1000)**
    → 金手指/侧面检测 夹紧 → 下盘放料时张开 → 回初始位(空夹)

每一段: 机械臂用 tools/rokae/replay_demo_seg.py 回放(容器内), 夹爪用 8793 的
`POST /ctl/move {"skill":"L2.grip_close|grip_open","speed_mm_s":10,"arm":1}` 真动。
任一段失败 ⇒ 立即停止, 不再往下走(不硬顶、不重发)。

用法:
  ./gui-venv311/bin/python tools/run_demo_cycle.py --list          # 只列工序
  ./gui-venv311/bin/python tools/run_demo_cycle.py                 # 从"搬运→槽2抓取"整圈跑
  ./gui-venv311/bin/python tools/run_demo_cycle.py --from 扫码      # 从某段开始
  ./gui-venv311/bin/python tools/run_demo_cycle.py --speed 40 --dry # 只打印不发
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request

STATION = "http://10.163.146.76:8793/ctl/move"
ROOT = "/home/ubuntu/zmax"

# (段名, 该段开始前要做的夹爪动作: None / "close" / "open", 回放速度 mm/s)
PLAN = [
    ("初始点",       None, 40),      # 第一步是"初始点"(老倪 11-22), 不是搬运
    ("搬运→槽2抓取", None, 60),
    ("槽2抓取",      "close", 40),   # 抓取: 夹紧(实物有件时夹住; 空跑也会闭合到 0)
    ("搬运→扫码",    None, 60),
    ("扫码",         None, 40),
    ("移动→插入到底", None, 40),
    ("插入到底",     None, 25),
    ("后退→等待检测", None, 30),
    ("等待检测",     None, 30),
    ("移动→钩拉环解锁", "open", 20),  # 钩子要露出来, 必须全开 1000
    ("钩拉环解锁",   None, 20),
    ("移动→金手指检测1", None, 60),
    ("金手指检测1",  "close", 25),   # 送检前重新夹紧(实物流程)
    ("移动→翻转→金手指检测2", None, 40),
    ("翻转→金手指检测2", None, 20),
    ("移动→侧面点1", None, 40),
    ("侧面点1",      None, 20),
    ("移动→侧面点2", None, 40),
    ("侧面点2",      None, 20),
    ("移动→侧面点3", None, 40),
    ("侧面点3",      None, 20),
    ("移动→侧面点4", None, 40),
    ("侧面点4",      None, 20),
    ("移动→下盘放料", None, 40),
    ("下盘放料",     "open", 20),    # 放料: 张开
    ("移动→回初始位", None, 60),
]


def grip(action: str) -> bool:
    skill = "L2.grip_close" if action == "close" else "L2.grip_open"
    body = json.dumps({"skill": skill, "speed_mm_s": 10, "arm": 1}).encode()
    req = urllib.request.Request(STATION, data=body, headers={"Content-Type": "application/json"})
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=15).read())
    except Exception as e:                                    # noqa: BLE001
        print("  ✗ 夹爪下发失败: %s" % e, flush=True)
        return False
    ok = bool(r.get("ok"))
    print("  🗜 %s → ok=%s dry=%s %s" % (skill, ok, r.get("dry"), r.get("msg", "")), flush=True)
    return ok


def grip_value() -> float | None:
    import glob
    fs = sorted(glob.glob(ROOT + "/zmax_data/live_gripper/grip_*.jsonl"))
    if not fs:
        return None
    try:
        return float(json.loads(open(fs[-1]).read().strip().splitlines()[-1])["pos"])
    except Exception:                                         # noqa: BLE001
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="frm", default=None)
    ap.add_argument("--speed", type=float, default=0.0, help="覆盖所有段速度(mm/s)")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()

    plan = PLAN
    if a.frm:
        names = [p[0] for p in PLAN]
        if a.frm not in names:
            print("✗ 没有这一段: %s\n可选: %s" % (a.frm, ", ".join(names)))
            return 2
        plan = PLAN[names.index(a.frm):]

    if a.list or a.dry:
        print("%-22s %-6s %s" % ("段", "夹爪", "速度"))
        for n, g, s in plan:
            print("%-22s %-6s %.0f" % (n, g or "-", a.speed or s))
        return 0

    for k, (name, gact, spd) in enumerate(plan, 1):
        spd = a.speed or spd
        print("\n=== [%d/%d] %s%s (%.0fmm/s) ===" % (k, len(plan), name, " + 夹爪 " + gact if gact else "", spd), flush=True)
        if gact:
            if not grip(gact):
                print("✗ 夹爪失败, 停止", flush=True)
                return 1
            time.sleep(1.0)
            print("  夹爪读数: %s" % grip_value(), flush=True)
        # 🔴 传到回放脚本的必须是**去掉转移前缀的段名**(脚本自己会补 移动→/后退→ 去状态表里找),
        #    否则会拼成 "移动→移动→金手指检测1" 而找不到段(实测就是这个错)
        _seg = name
        for _pre in ("移动→", "搬运→", "后退→"):
            if _seg.startswith(_pre):
                _seg = _seg[len(_pre):]
                break
        cmd = 'cd %s && ZMAX_SEG_NAME="%s" ZMAX_SEG_SPEED=%.0f timeout 900 bash tools/rokae_sdk_run.sh --script replay_demo_seg.py' % (ROOT, _seg, spd)
        p = subprocess.run(["bash", "-lc", cmd], capture_output=True, text=True)
        tail = "\n".join(p.stdout.strip().splitlines()[-3:])
        print(tail, flush=True)
        if p.returncode != 0 or "OK" not in p.stdout:
            print("✗ 段失败(rc=%d), 停止; 不重发不硬顶" % p.returncode, flush=True)
            return 1
    print("\n✅ 整圈完成 · 夹爪末值 %s" % grip_value(), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
