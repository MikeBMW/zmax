#!/usr/bin/env python3
"""Per-child directory sizes for Windows, junction-aware.

Usage:
    python dir_sizes.py <parent> [<parent> ...]

Prints one table per parent, largest child first, with file counts. Use it as the
first measuring pass of any disk audit: it never walks a junction or symlink (the
classic cause of a profile reporting 3x its real size) and it caps the file count
so one huge tree cannot hang the call.

Run it with PYTHONIOENCODING=utf-8 when child names are non-ASCII.
"""

import os
import sys
import time

FILE_BUDGET = 2_000_000  # stop accumulating past this many files in one subtree


def is_junction(path):
    try:
        return os.path.isjunction(path)
    except (AttributeError, OSError):
        return False


def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return ("%d B" % n) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0


def dirsize(path):
    total = 0
    files = 0
    stack = [path]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if e.is_symlink() or is_junction(e.path):
                                continue
                            stack.append(e.path)
                        elif e.is_file(follow_symlinks=False):
                            total += e.stat(follow_symlinks=False).st_size
                            files += 1
                    except OSError:
                        continue
        except OSError:
            continue
        if files > FILE_BUDGET:
            return total, files, True
    return total, files, False


def table(parent):
    if not os.path.isdir(parent):
        print("== %s MISSING" % parent)
        return
    t0 = time.time()
    rows = []
    try:
        entries = list(os.scandir(parent))
    except OSError as exc:
        print("== %s ERROR %s" % (parent, exc))
        return
    for e in entries:
        try:
            if e.is_dir(follow_symlinks=False):
                if e.is_symlink() or is_junction(e.path):
                    rows.append((0, 0, e.name + "  <junction>"))
                    continue
                size, files, capped = dirsize(e.path)
                rows.append((size, files, e.name + ("  [CAPPED]" if capped else "")))
            elif e.is_file(follow_symlinks=False):
                rows.append((e.stat(follow_symlinks=False).st_size, 1, e.name))
        except OSError:
            continue
    rows.sort(reverse=True)
    print("\n== %s   total %s   (%.1fs)" % (parent, human(sum(r[0] for r in rows)), time.time() - t0))
    for size, files, name in rows[:25]:
        print("   %10s  %8d  %s" % (human(size), files, name))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for arg in sys.argv[1:]:
        table(arg)
