#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""win_cmd.py — 向无 SSH 的 Windows 产线机下发一条命令, 并**精确取回这一次的回执**。

为什么不用 station_cmd.py: 它按"新出现文件名取最大"认领回执。机器离线一段时间后历史命令在排队消费,
你发的命令很可能拿到上一条(别人的)回执 —— 表象是通道"通"、内容完全不相干。
本脚本给每条命令加一个 `echo ZMAXM<8位hex>;` 标记, 只认含该标记的回执。

另外两个经通道下发必须遵守的规矩(本脚本已内置):
  · 通道把命令交给 **PowerShell** 执行(不是 cmd) ⇒ 分隔符用 `;`, 不能用 `&&`。
  · 命令里不要出现 `$`/`%`, 不要嵌套引号(会被包装层吃掉)。

用法:
  ZMAX_ROOT=/home/ubuntu/zmax python3 win_cmd.py 'schtasks /query /tn <任务> /fo list' 120
  python3 win_cmd.py 'Get-NetTCPConnection -State Listen -LocalPort 10082,10083 | Select-Object LocalPort,OwningProcess | ConvertTo-Json -Compress' 120
"""
import os
import subprocess
import sys
import time
import uuid

ROOT = os.environ.get("ZMAX_ROOT", "/home/ubuntu/zmax")
PY = os.environ.get("ZMAX_PY", os.path.join(ROOT, "gui-venv311", "bin", "python"))
HUB = os.path.join(ROOT, "tools", "agent_hub.py")
OUT_DIR = os.environ.get("ZMAX_HUB_OUT", os.path.join(ROOT, "zmax_data", "agent_hub", "out"))


def snapshot():
    """按【文件名集合】取快照, 不按 mtime —— 墙钟回拨会让旧回执永远"最新"。"""
    try:
        return {x for x in os.listdir(OUT_DIR) if x.endswith(".txt")}
    except OSError:
        return set()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    raw = sys.argv[1]
    wait = int(sys.argv[2]) if len(sys.argv) > 2 else 90
    tag = "ZMAXM" + uuid.uuid4().hex[:8]
    cmd = "echo %s; %s" % (tag, raw)          # PowerShell 分隔符是 ;
    before = snapshot()
    r = subprocess.run([PY, HUB, "--enqueue", cmd], capture_output=True, text=True)
    if r.returncode != 0:
        print("!! 入队失败:", (r.stderr or r.stdout)[:300])
        return 2
    print("[tag] %s" % tag)
    t0 = time.time()
    seen = set()
    while time.time() - t0 < wait:
        for name in sorted(snapshot() - before):
            if name in seen:
                continue
            seen.add(name)
            p = os.path.join(OUT_DIR, name)
            try:
                txt = open(p, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            if tag in txt:                      # 只认这一次的回执
                print("== 回执 %s (等了 %ds) ==" % (name, int(time.time() - t0)))
                print(txt.replace(tag, "").strip())
                return 0
        time.sleep(1.5)
    print("!! %ds 内没拿到本次回执(其间见到 %d 个新回执)。可能仍在排历史队列, 或通道真的死了。" % (wait, len(seen)))
    return 3


if __name__ == "__main__":
    sys.exit(main())
