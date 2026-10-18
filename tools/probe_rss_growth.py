#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""找出 studio.py 里「哪一块内存正在涨」— 两次 smaps 快照按映射名聚合 diff

用法: python3 tools/probe_rss_growth.py [--pid N] [--wait 90]
输出: 增长最多的映射 (名字/权限/RSS 增量), 用来区分
  [heap]  = Python/C 堆对象 (glibc malloc)
  [anon]  = 匿名 mmap (numpy 大数组 / 线程栈 / Qt 大缓冲)
  libGL*/swrast/llvmpipe = OpenGL 驱动内部 (mesh/VBO 上传)
"""
from __future__ import annotations

import argparse
import collections
import os
import re
import subprocess
import time

SEG = re.compile(r"^([0-9a-f]+)-([0-9a-f]+) (\S{4}) \S+ \S+ \S+\s*(.*)$")


def snap(pid: int) -> dict:
    out = subprocess.run(["sudo", "cat", "/proc/%d/smaps" % pid],
                         capture_output=True, text=True).stdout
    agg = collections.Counter()
    cur = None
    for ln in out.splitlines():
        m = SEG.match(ln)
        if m:
            name = (m.group(4) or "").strip()
            if not name:
                name = "[anon]" if "rw-p" in m.group(3) else "[file]"
            else:
                name = os.path.basename(name) or name
            cur = name
        elif ln.startswith("Rss:") and cur:
            agg[cur] += int(ln.split()[1])
    return agg


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, default=0)
    ap.add_argument("--wait", type=float, default=90.0)
    a = ap.parse_args()
    pid = a.pid
    if not pid:
        out = subprocess.run(["pgrep", "-f", "gui/studio.py"], capture_output=True, text=True).stdout.split()
        if not out:
            print("✗ 找不到 studio.py")
            return 2
        pid = int(out[0])
    print("pid=%d · 第一次采样…" % pid)
    s1 = snap(pid)
    t1 = sum(s1.values()) / 1024.0
    print("  RSS 合计 %.0f MB · 映射类 %d" % (t1, len(s1)))
    print("等 %.0fs…" % a.wait)
    time.sleep(a.wait)
    s2 = snap(pid)
    t2 = sum(s2.values()) / 1024.0
    print("  RSS 合计 %.0f MB  (Δ %+.1f MB / %.0fs ≈ %.2f GB/h)"
          % (t2, t2 - t1, a.wait, (t2 - t1) / 1024.0 * 3600.0 / a.wait))

    d = {k: s2[k] - s1.get(k, 0) for k in set(s1) | set(s2)}
    print("\n%-32s %10s %10s %10s" % ("映射名", "现在MB", "Δ MB", "段数说明"))
    for k, v in sorted(d.items(), key=lambda x: -x[1])[:12]:
        if abs(v) < 512:            # 小于 0.5MB 的忽略
            continue
        print("%-32s %10.1f %+10.1f" % (k[:32], s2[k] / 1024.0, v / 1024.0))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
