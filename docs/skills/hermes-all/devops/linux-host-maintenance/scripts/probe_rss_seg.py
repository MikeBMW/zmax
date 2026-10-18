#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按映射段追踪某进程的 RSS 增长 —— 两次 /proc/<pid>/smaps 快照 diff

用途: 某进程 RSS 只增不减时, 第一件要回答的是"哪一块内存在涨"。
按映射名聚合只能答到 [anon]; 本脚本按 (起址, 权限, 名字) 对齐两快照, 列出 RSS 增长最大的具体段。

判读:
  [anon] rw-p 增长               → numpy 大数组 / GL 缓冲 / 线程栈
  [heap] 增长                    → 小对象
  56~72MB 段反复"新映射"         → glibc arena (默认 8×核数, 每个最多 64MB, 只增不还)
  128KB~1MB 段高频新增           → CPython pymalloc arena (_PyObject_ArenaMmap 每次 256KB)

用法:
  sudo python3 probe_rss_seg.py --pid 12345 --wait 120

之后再用 bpftrace 抓分配者 (决定性证据):
  P=<pid>
  sudo bpftrace -e 'tracepoint:syscalls:sys_enter_mmap /pid == '"$P"'/ { @u[ustack(5)] = count(); }
                    interval:s:40 { exit(); }' > /tmp/bt.txt 2>&1
  # 最大的栈在最后; 看到 _PyObject_ArenaMmap ← PyDict_SetItem ← scan_once_unicode = 高频 json 解析
"""
import argparse
import re
import subprocess
import time

SEG = re.compile(r"^([0-9a-f]+)-([0-9a-f]+) (\S+) \S+ \S+ \S+\s*(.*)$")


def snap(pid):
    out = subprocess.run(["sudo", "cat", "/proc/%s/smaps" % pid],
                         capture_output=True, text=True).stdout
    segs, cur = {}, None
    for ln in out.splitlines():
        m = SEG.match(ln)
        if m:
            start, end, perms, name = m.groups()
            cur = "%s-%s %s %s" % (start, end, perms, (name or "[anon]").strip())
            segs.setdefault(cur, 0)
        elif ln.startswith("Rss:") and cur:
            try:
                segs[cur] += int(ln.split()[1])
            except (IndexError, ValueError):
                pass
    return segs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--wait", type=int, default=120)
    ap.add_argument("--min-mb", type=float, default=0.5, help="小于这个增量的段不打印")
    a = ap.parse_args()

    s1 = snap(a.pid)
    t1 = sum(s1.values())
    print("pid=%d · 第一次采样… RSS 合计 %d MB · 映射类 %d" % (a.pid, t1 // 1024, len(s1)))
    print("等 %ds…" % a.wait)
    time.sleep(a.wait)
    s2 = snap(a.pid)
    t2 = sum(s2.values())
    d = (t2 - t1) / 1024.0 / 1024.0
    print("RSS 合计 %d MB → %d MB  (Δ %+.1f MB / %ds ≈ %+.2f GB/h)"
          % (t1 // 1024, t2 // 1024, (t2 - t1) / 1024.0, a.wait,
             d / (a.wait / 3600.0)))

    rows = []
    for k, v2 in s2.items():
        v1 = s1.get(k)
        rows.append((v2 - (v1 or 0), k, v1, v2))
    rows.sort(key=lambda r: -r[0])
    print("\n增长最大的段 ("新映射" = 两次采样间不存在):")
    shown = 0
    for delta, k, v1, v2 in rows:
        if delta < a.min_mb * 1024 or shown >= 14:
            continue
        shown += 1
        tag = "新映射" if v1 is None else "%d→%d MB" % (v1 // 1024, v2 // 1024)
        print("  %+8.1f MB  %-58s %s" % (delta / 1024.0, k[:58], tag))
    if not shown:
        print("  (没有 >%.1fMB 的段增长 —— 增长可能是大量小段同时长, 调小 --min-mb 或看 bpftrace)"
              % a.min_mb)


if __name__ == "__main__":
    main()
