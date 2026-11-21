#!/usr/bin/env python3
"""找出「同一父进程下 cmdline 完全相同的孪生进程」(泄漏的 worker)。

用法:
  python3 dup_children.py                 # 全部进程
  python3 dup_children.py --min-mb 200    # 只报占据超过 200MB 的组
  python3 dup_children.py --unit zmax-ss-engine-loop   # 只报某个 systemd 单元的成员

判据: 同一 (ppid, 归一 argv) 下出现 >=2 条 ⇒ 主进程没回收旧 worker。
处置口径: 杀 N-1 份、留最老那份, 然后复核目标链路产物 mtime 仍在推进(见 SKILL §1g)。
"""
import argparse
import os
import re
import sys
from collections import defaultdict


def read(path):
    try:
        with open(path, 'rb') as f:
            return f.read()
    except OSError:
        return b''


def norm_args(argv):
    """去掉会把同一条命令写成不同串的部分: 时间戳/路径里的时间目录。"""
    out = []
    for a in argv:
        a = re.sub(r'\d{8}[_\-]?\d{4,6}', '<TS>', a)
        a = re.sub(r'run_\d+', 'run_<N>', a)
        out.append(a)
    return ' '.join(out)


def unit_of(pid):
    txt = read(f'/proc/{pid}/cgroup').decode('utf8', 'replace')
    m = re.search(r'/([\w.\-]+\.service)', txt)
    return m.group(1) if m else '?'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--min-mb', type=int, default=0)
    ap.add_argument('--unit', default=None)
    a = ap.parse_args()

    groups = defaultdict(list)
    for pid in (p for p in os.listdir('/proc') if p.isdigit()):
        raw = read(f'/proc/{pid}/cmdline')
        if not raw:
            continue
        argv = [x for x in raw.decode('utf8', 'replace').split('\x00') if x]
        if not argv:
            continue
        stat = read(f'/proc/{pid}/stat').decode('utf8', 'replace').split()
        ppid = stat[3] if len(stat) > 3 else '?'
        try:
            rss_mb = int([l for l in read(f'/proc/{pid}/status').decode().splitlines()
                          if l.startswith('VmRSS')][0].split()[1]) // 1024
        except (IndexError, ValueError):
            rss_mb = 0
        if rss_mb < a.min_mb:
            continue
        groups[(ppid, norm_args(argv))].append((int(pid), rss_mb, unit_of(pid)))

    found = 0
    for (ppid, cmd), items in sorted(groups.items(), key=lambda kv: -sum(i[1] for i in kv[1])):
        if len(items) < 2:
            continue
        if a.unit and not any(a.unit in u for _, _, u in items):
            continue
        found += 1
        total = sum(i[1] for i in items)
        print(f'\n[{len(items)} 份] 合计 {total}MB  父 pid {ppid}  单元 {items[0][2]}')
        print(f'  argv: {cmd[:150]}')
        for pid, rss, _ in sorted(items):
            et = read(f'/proc/{pid}/stat').decode('utf8', 'replace').split()
            print(f'    pid {pid:<8} {rss:6d}MB  (保留最老那份, 其余 kill -TERM)')
    if not found:
        print('未发现孪生进程 ✅')
    else:
        print(f'\n共 {found} 组重复; 处置后必须复核目标链路产物 mtime 仍在推进。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
