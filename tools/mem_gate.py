#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧯 内存闸 (mem_gate) —— 起重活前的**开闸闸门**, 防"第二套模型进程"把整机拖进 thrash

事故背景 (2026-11-01 18:48 死机复盘):
  本机基线栈本身已占 ~14GB / 31GB (ss_canvas_loop 3.2G · intact_sw_bridge 2.3G ·
  2× intact_worker 2.5G · ss_engine_loop 1.3G)。此时我又起了一个 offscreen 的
  `full_tick_bench.py` (load_project → 80 节点真跑), 它等于**在已跑满的栈上又叠了
  一整套**(还 fork 了第二个引擎桥 + 加载 489 分片权重)。日志里分片加载从 5s/片
  恶化到 22s/片 ⇒ 换页颠簸 ⇒ 桌面无响应 ⇒ 只能长按下电, 内核没留任何 OOM/panic 记录。

判据 (两条, 都可复跑):
  ① 可用内存 MemAvailable < NEED_GB (默认 6GB)                  → 拒绝 (exit 3)
  ② 已有同类重载进程 (cmdline 命中 --alone) 且 RSS ≥ HEAVY_GB   → 拒绝 (exit 5)  "第二套"
  ③ 跑起来后子进程(含子孙) RSS > MAX_RSS_GB (默认 8GB)          → 掐掉 (exit 4)

用法:
  # 只看现状 (只读)
  gui-venv311/bin/python tools/mem_gate.py check
  # 开闸跑 (安全才能起; 超 8GB 自动掐)
  gui-venv311/bin/python tools/mem_gate.py run -- ./gui-venv311/bin/python tools/full_tick_bench.py
  # 明确禁止第二套 (例如基准测试不许和常驻引擎栈并存)
  gui-venv311/bin/python tools/mem_gate.py run --alone 'ss_canvas_loop|ss_engine_loop' -- cmd...
  # 只判定不开跑 (给脚本/CI 用)
  gui-venv311/bin/python tools/mem_gate.py check --need-gb 12 --json

退出码: 0 安全 · 3 可用内存不足 · 5 已有同类重载 · 4 被 RSS 上限掐掉
"""
from __future__ import annotations

import json
import os
import re
import signal
import sys
import time

NEED_GB = 6.0      # 可用内存下限
HEAVY_GB = 8.0     # 单个重载进程算"一整套"的门槛
MAX_RSS_GB = 8.0   # 子进程 RSS 上限 (超了掐)
POLL_S = 2.0


def meminfo() -> dict:
    out = {}
    try:
        with open("/proc/meminfo") as f:
            for ln in f:
                k, _, rest = ln.partition(":")
                v = rest.strip().split()
                if v and v[0].isdigit():
                    out[k] = int(v[0]) / 1024.0  # MB
    except OSError:
        pass
    return out


def procs() -> list[dict]:
    """所有有 cmdline 的进程 + VmRSS(MB)"""
    rows = []
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        pid = int(d)
        try:
            with open("/proc/%d/cmdline" % pid, "rb") as f:
                raw = f.read()
            if not raw:
                continue
            cmd = raw.replace(b"\0", b" ").decode("utf-8", "replace").strip()
            rss = 0.0
            with open("/proc/%d/status" % pid) as f:
                for ln in f:
                    if ln.startswith("VmRSS:"):
                        rss = int(ln.split()[1]) / 1024.0
                        break
        except OSError:
            continue
        rows.append({"pid": pid, "rss_mb": round(rss, 1), "cmd": cmd})
    rows.sort(key=lambda r: -r["rss_mb"])
    return rows


def snapshot() -> dict:
    mi = meminfo()
    avail = mi.get("MemAvailable", 0.0)
    ps = procs()
    return {
        "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mem_total_gb": round(mi.get("MemTotal", 0) / 1024.0, 1),
        "available_gb": round(avail / 1024.0, 2),
        "used_gb": round((mi.get("MemTotal", 0) - mi.get("MemAvailable", 0)) / 1024.0, 1),
        "swap_used_gb": round((mi.get("SwapTotal", 0) - mi.get("SwapFree", 0)) / 1024.0, 2),
        # 全量进程表(按 RSS 降序), 阈值在 judge 里按调用者的 --heavy-gb 过滤
        "_procs": ps,
        "procs": [{"pid": p["pid"], "rss_gb": round(p["rss_mb"] / 1024.0, 2),
                   "cmd": p["cmd"][:110]} for p in ps],
        "top": [{"pid": p["pid"], "rss_gb": round(p["rss_mb"] / 1024.0, 2),
                 "cmd": p["cmd"][:110]} for p in ps[:5]],
    }


def judge(snap: dict, need_gb: float, alone: str | None, heavy_gb: float) -> tuple[int, str]:
    if snap["available_gb"] < need_gb:
        return 3, "可用内存 %.1fGB < 下限 %.1fGB ⇒ 拒绝起新进程 (先停掉不用的重载)" % (
            snap["available_gb"], need_gb)
    if alone:
        pat = re.compile(alone)
        hit = [p for p in snap["_procs"]
               if p["rss_mb"] >= heavy_gb * 1024 and pat.search(p["cmd"])]
        if hit:
            return 5, "已有同类重载 pid=%d (%.1fGB, %s) ⇒ 拒绝第二套" % (
                hit[0]["pid"], hit[0]["rss_mb"] / 1024.0, hit[0]["cmd"][:60])
    return 0, "闸门开: 可用 %.1fGB / 总 %.1fGB · swap %.2fGB" % (
        snap["available_gb"], snap["mem_total_gb"], snap["swap_used_gb"])


def descendants(root: int) -> list[int]:
    kids: dict[int, list[int]] = {}
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            with open("/proc/%s/stat" % d) as f:
                ppid = int(f.read().split(") ", 1)[1].split()[1])
        except (OSError, IndexError):
            continue
        kids.setdefault(ppid, []).append(int(d))
    out, stack = [], [root]
    while stack:
        p = stack.pop()
        out.append(p)
        stack.extend(kids.get(p, []))
    return out


def rss_mb(pid: int) -> float:
    try:
        with open("/proc/%d/status" % pid) as f:
            for ln in f:
                if ln.startswith("VmRSS:"):
                    return int(ln.split()[1]) / 1024.0
    except OSError:
        pass
    return 0.0


def do_run(cmd: list[str], need_gb: float, alone: str | None, heavy_gb: float, cap_gb: float) -> int:
    snap = snapshot()
    code, msg = judge(snap, need_gb, alone, heavy_gb)
    print("[mem_gate] " + msg, flush=True)
    if code:
        return code
    if not cmd:
        return 2
    import subprocess
    p = subprocess.Popen(cmd)
    peak = 0.0
    while True:
        rc = p.poll()
        if rc is not None:
            print("[mem_gate] 子进程退出 rc=%s · 峰值 RSS %.1fGB" % (rc, peak), flush=True)
            return rc
        tot = sum(rss_mb(x) for x in descendants(p.pid)) / 1024.0
        peak = max(peak, tot)
        if cap_gb > 0 and tot > cap_gb:
            print("[mem_gate] 🔴 子进程树 RSS %.1fGB > 上限 %.1fGB ⇒ 掐掉 pid=%d" % (tot, cap_gb, p.pid),
                  flush=True)
            for x in descendants(p.pid):
                try:
                    os.kill(x, signal.SIGTERM)
                except OSError:
                    pass
            time.sleep(3)
            for x in descendants(p.pid):
                try:
                    os.kill(x, signal.SIGKILL)
                except OSError:
                    pass
            return 4
        time.sleep(POLL_S)


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("check", "run"):
        print(__doc__)
        return 2
    mode, rest = argv[1], argv[2:]
    need_gb, heavy_gb, cap_gb, alone, as_json = NEED_GB, HEAVY_GB, MAX_RSS_GB, None, False
    cmd: list[str] = []
    i = 0
    while i < len(rest):
        a = rest[i]
        if a == "--":
            cmd = rest[i + 1:]
            break
        if a == "--need-gb":
            need_gb = float(rest[i + 1]); i += 2
        elif a == "--heavy-gb":
            heavy_gb = float(rest[i + 1]); i += 2
        elif a == "--max-rss-gb":
            cap_gb = float(rest[i + 1]); i += 2
        elif a == "--alone":
            alone = rest[i + 1]; i += 2
        elif a == "--json":
            as_json = True; i += 1
        else:
            cmd = rest[i:]
            break
    if mode == "run":
        return do_run(cmd, need_gb, alone, heavy_gb, cap_gb)
    snap = snapshot()
    code, msg = judge(snap, need_gb, alone, heavy_gb)
    if as_json:
        body = {k: v for k, v in snap.items() if not k.startswith("_")}
        print(json.dumps({"verdict": code, "msg": msg, **body}, ensure_ascii=False))
    else:
        print("[mem_gate] " + msg)
        print("  %-7s %-7s %s" % ("pid", "RSS(GB)", "cmd"))
        for row in snap["top"]:
            print("  %-7d %-7.2f %s" % (row["pid"], row["rss_gb"], row["cmd"]))
        n_heavy = sum(1 for p in snap["_procs"] if p["rss_mb"] >= heavy_gb * 1024)
        print("  重载(≥%.1fGB): %d 个" % (heavy_gb, n_heavy))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
