#!/usr/bin/env python3
"""两机文件级对账 (纯标准库, 跨机直接拷过去跑).

为什么不用 rsync: `rsync -rcn` 默认**不跟软链**, 对软链一律输出
`skipping non-regular file` 且不报差异 —— 仓库根目录大量软链到数据盘时,
会得出"两台完全一致"的假结论。本脚本跟随软链, 并把**断链**单独记下来
(断链 = 目标机上那个数据/记忆/技能库根本没搬过来)。

用法:
    python3 two_host_manifest_diff.py scan <root> <out.txt> [--dirs a,b,c] [--max-mb 40]
    python3 two_host_manifest_diff.py diff <A.txt> <B.txt>

scan 产物:
    <out.txt>          每行 "hash16  relpath"
    <out.txt>.broken   断链/不可读清单 (JSON)

diff 输出:
    ONLY_A / ONLY_B / CHANGED 三段 + 按顶层目录的缺失计数 (看哪一面整片没搬)
"""
import hashlib
import json
import os
import sys

DEFAULT_DIRS = [
    "tools", "src", "dds", "config", "defaults", "capability", "launch",
    "scripts", "data/skills", "data/memory", "flows",
]
SKIP_DIR = {
    "__pycache__", ".git", "node_modules", "venvs", "site-packages",
    "_archive", "outputs", "external", "runs", "logs",
}


def scan(root, out, dirs, max_bytes):
    skip = set(SKIP_DIR)
    rows, broken, seen = {}, [], set()
    for d in dirs:
        base = os.path.join(root, d)
        if not os.path.exists(base):
            broken.append(d + "/  (DIR MISSING)")
            continue
        for dp, dns, fns in os.walk(base, followlinks=True):
            real = os.path.realpath(dp)
            if real in seen:
                dns[:] = []
                continue
            seen.add(real)
            dns[:] = [x for x in dns if x not in skip]
            for fn in fns:
                p = os.path.join(dp, fn)
                rel = os.path.relpath(p, root)
                if os.path.islink(p) and not os.path.exists(p):
                    broken.append(rel + "  (BROKEN LINK)")
                    continue
                try:
                    st = os.stat(p)
                except OSError:
                    broken.append(rel + "  (STAT FAIL)")
                    continue
                if not os.path.isfile(p) or st.st_size > max_bytes:
                    continue
                h = hashlib.sha256()
                try:
                    with open(p, "rb") as f:
                        for chunk in iter(lambda: f.read(1 << 20), b""):
                            h.update(chunk)
                except OSError:
                    broken.append(rel + "  (READ FAIL)")
                    continue
                rows[rel] = h.hexdigest()[:16]
    with open(out, "w", encoding="utf-8") as f:
        for k in sorted(rows):
            f.write("%s  %s\n" % (rows[k], k))
    with open(out + ".broken", "w", encoding="utf-8") as f:
        json.dump(broken, f, ensure_ascii=False, indent=1)
    print("scan %s: files=%d broken=%d -> %s" % (root, len(rows), len(broken), out))
    for b in broken[:40]:
        print("  BROKEN", b)
    return 0


def load(path):
    d = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            if "  " not in line:
                continue
            h, p = line.split("  ", 1)
            d[p] = h
    return d


def diff(pa, pb):
    a, b = load(pa), load(pb)
    only_a = sorted(set(a) - set(b))
    only_b = sorted(set(b) - set(a))
    changed = sorted(p for p in set(a) & set(b) if a[p] != b[p])
    print("A=%d B=%d  ONLY_A=%d ONLY_B=%d CHANGED=%d" % (len(a), len(b), len(only_a), len(only_b), len(changed)))
    for tag, lst in (("ONLY_A", only_a), ("ONLY_B", only_b), ("CHANGED", changed)):
        for x in lst:
            print(tag, x)
    # 按顶层目录聚合, 一眼看出“哪一面整片没搬”
    agg = {}
    for x in only_a:
        key = "/".join(x.split("/")[:3])
        agg[key] = agg.get(key, 0) + 1
    if agg:
        print("-- ONLY_A 按目录 --")
        for k in sorted(agg, key=lambda k: -agg[k]):
            print("  %4d  %s" % (agg[k], k))
    # 断链在 A 侧有没有
    for side, path in (("A", pa), ("B", pb)):
        bp = path + ".broken"
        if os.path.exists(bp):
            try:
                br = json.load(open(bp, encoding="utf-8"))
            except ValueError:
                br = []
            print("BROKEN_IN_%s=%d" % (side, len(br)))
            for x in br[:20]:
                print("  BROKEN_%s %s" % (side, x))
    return 0


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1]
    if cmd == "scan" and len(argv) >= 4:
        dirs = DEFAULT_DIRS
        max_mb = 40
        rest = argv[4:]
        i = 0
        while i < len(rest):
            if rest[i] == "--dirs" and i + 1 < len(rest):
                dirs = [x.strip() for x in rest[i + 1].split(",") if x.strip()]
                i += 2
            elif rest[i] == "--max-mb" and i + 1 < len(rest):
                max_mb = int(rest[i + 1])
                i += 2
            else:
                i += 1
        return scan(argv[2], argv[3], dirs, max_mb << 20)
    if cmd == "diff" and len(argv) >= 4:
        return diff(argv[2], argv[3])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
