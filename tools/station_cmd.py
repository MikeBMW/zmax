#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""station_cmd.py — 给工控机(192.168.23.23)下发一条 PowerShell 并取回执。

用法: gui-venv311/bin/python station_cmd.py "Get-Date" [wait_sec]
原理: 走 8794 反向通道(agent_hub 入队 → 工控机的 ZMAX_Agent 每 3~5s 取走执行 → 回执落在 out/ 目录)。
      hub 由 systemd 单元 zmax-agent-hub.service 托管; 运行态文件在 ~/zmax/zmax_data/agent_hub/。
      (2026-09-29 三个坑: ①hub 没托管 ②队列放 /tmp 被 fs.protected_regular 拒写 ③两端 token 不一致)
"""
import os
import subprocess
import sys
import time

ROOT = "/home/ubuntu/zmax"
PY = os.path.join(ROOT, "gui-venv311", "bin", "python")
HUB = os.path.join(ROOT, "tools", "agent_hub.py")
OUT_DIR = "/home/ubuntu/zmax/zmax_data/agent_hub/out"


def snapshot():
    """按【文件名集合】取快照, 不按 mtime。

    坑(2026-10-13 实录): 原先用 max(mtime) 找"最新回执"。开机时 NTP 把墙钟回拨 8h
    (RTC 快 8h → 校正), 工控机在回拨前落的回执文件 mtime 变成【未来 8h】, 永远比新回执"新"
    ⇒ newest() 恒返回那几个陈旧文件 ⇒ 每次都误报"没等到回执(通道死了)"。
    文件名是落地时的 time.time() 整数, 用集合差找新出现的名字, 与墙钟跳变无关。
    """
    try:
        return {x for x in os.listdir(OUT_DIR) if x.endswith(".txt")}
    except OSError:
        return set()


def main():
    cmd = sys.argv[1]
    wait = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    before = snapshot()
    r = subprocess.run([PY, HUB, "--enqueue", cmd], capture_output=True, text=True)
    if r.returncode != 0:
        print("!! 入队失败:", (r.stderr or r.stdout)[:300])
        return 2
    t0 = time.time()
    while time.time() < t0 + wait:
        new = snapshot() - before
        if new:
            # 文件名=epoch 秒(等长), 取最大的即最新落的回执。多调用者并发时会互相抢回执(既有局限)
            name = max(new)
            f = os.path.join(OUT_DIR, name)
            print("== 回执 %s ==" % f)
            print(open(f, encoding="utf-8", errors="replace").read().strip())
            return 0
        time.sleep(1.5)
    print("!! %ds 内没等到回执(通道死了? 看 hub.log 与 /agent/beat)" % wait)
    return 3


if __name__ == "__main__":
    sys.exit(main())
