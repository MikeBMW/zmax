#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""win_cmd.py — 向工控机(192.168.23.23)下发一条命令并精确取回"这一次"的回执。
坑: station_cmd.py 取 max(新文件名) —— 队列里若还有历史命令在排队, 拿到的可能是别人的回执。
做法: 每条命令前面加 `echo ZMAXM<tag>` 标记, 只认含该标记的回执; 并打印回执文件名与时间。
用法: win_cmd.py '<cmd>' [wait_sec]
"""
import os, subprocess, sys, time, uuid

ROOT = "/home/ubuntu/zmax"
PY = os.path.join(ROOT, "gui-venv311", "bin", "python")
HUB = os.path.join(ROOT, "tools", "agent_hub.py")
OUT = "/home/ubuntu/zmax/zmax_data/agent_hub/out"


def snaps():
    try:
        return {x for x in os.listdir(OUT) if x.endswith(".txt")}
    except OSError:
        return set()


def main():
    raw = sys.argv[1]
    wait = int(sys.argv[2]) if len(sys.argv) > 2 else 90
    tag = "ZMAXM" + uuid.uuid4().hex[:8]
    cmd = "echo %s; %s" % (tag, raw)
    before = snaps()
    r = subprocess.run([PY, HUB, "--enqueue", cmd], capture_output=True, text=True)
    if r.returncode != 0:
        print("!! 入队失败:", (r.stderr or r.stdout)[:300])
        return 2
    print("[tag] %s" % tag)
    t0 = time.time()
    seen = set()
    while time.time() - t0 < wait:
        for name in sorted(snaps() - before):
            if name in seen:
                continue
            seen.add(name)
            p = os.path.join(OUT, name)
            try:
                txt = open(p, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            if tag in txt:
                print("== 回执 %s (等了 %ds) ==" % (name, int(time.time() - t0)))
                print(txt.replace(tag, "").strip())
                return 0
        time.sleep(1.5)
    print("!! %ds 内没拿到本次回执(共见 %d 个新回执)。可能还在排历史队列。" % (wait, len(seen)))
    return 3


if __name__ == "__main__":
    sys.exit(main())
