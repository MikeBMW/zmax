#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""精细版: 按「映射段」追踪 studio.py 的 RSS 增长 (区分具体是哪一段在涨)

上一次按名字聚合只得到 [anon]，太粗。本脚本按 (起址, 权限, 名字) 对齐两次快照，
列出 RSS 增长最大的具体段 —— 是单个巨型数组还是大量小分配，一眼看出。
用法: python3 tools/probe_rss_seg.py [--wait 90]
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import time

SEG = re.compile(r"^([0-9a-f]+)-([0-9a-f]+) (\S{4}) \S+ \S+ \S+\s*(.*)$")


def snap(pid: int):
    out = subprocess.run(["sudo", "cat", "/proc/%d/smaps" % pid],
                         capture_output=True, text=True).stdout
    segs = {}
    cur = None
    for ln in out.splitlines():
        m = SEG.match(ln)
        if m:
            start = int(m.group(1), 16)
            size = (int(m.group(2), 16) - start) / 1048576.0
            name = (m.group(4) or "").strip()
            name = os.path.basename(name) if name else "[anon]"
            cur = (start, m.group(3), name, round(size, 1))
            segs[cur] = 0
        elif ln.startswith("Rss:") and cur:
            segs[cur] += int(ln.split()[1])
    return segs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=float, default=90.0)
    a = ap.parse_args()
    pid = int(subprocess.run(["pgrep", "-f", "gui/studio.py"],
                             capture_output=True, text=True).stdout.split()[0])
    print("pid=%d 采样…" % pid)
    s1 = snap(pid)
    print("  RSS %.0f MB / %d 段" % (sum(s1.values()) / 1024.0, len(s1)))
    time.sleep(a.wait)
    s2 = snap(pid)
    print("  RSS %.0f MB · Δ %+.0f MB / %.0fs (%.2f GB/h)"
          % (sum(s2.values()) / 1024.0, (sum(s2.values()) - sum(s1.values())) / 1024.0,
             a.wait, (sum(s2.values()) - sum(s1.values())) / 1024.0 * 3600 / a.wait))

    rows = []
    for k, v2 in s2.items():
        v1 = s1.get(k)
        if v1 is None:
            rows.append((v2 / 1024.0, k, v2 / 1024.0, "新映射"))
        else:
            d = (v2 - v1) / 1024.0
            if abs(d) >= 1.0:
                rows.append((d, k, v2 / 1024.0, ""))
    print("\n%-10s %8s %8s %-30s %s" % ("ΔMB", "现在MB", "段大小", "权限", "名字"))
    for d, k, now, tag in sorted(rows, reverse=True)[:15]:
        print("%+10.1f %8.1f %8.1f %-30s %s%s"
              % (d, now, k[3], k[1], k[2][:40], (" " + tag) if tag else ""))
    n_small = len([r for r in rows if r[0] > 0 and r[0] < 1.0])
    print("\n(另有 %d 段增长 <1MB — 大量小分配的特征)" % n_small)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
