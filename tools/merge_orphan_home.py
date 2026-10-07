#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""merge_orphan_home.py — 把家目录里又冒出来的「老路径产物」并回工程内(2026-10-08)

为什么会有: 家目录整合后, **已经在跑的老进程**仍把产物写回 /home/ubuntu/{zmax_data,lerobot-smolvla-lew}
(2026-10-08 实测: GUI 子进程写启动日志; YOLO 标注训练 06:41/06:56 两轮把 runs/ 写回家目录)。
处理口径(与 10-07 一致): 先并回工程内对应位置(**不覆盖更新的文件**), 老目录里剩下的归档, 再删空目录,
每步写清单可回滚。**绝不动正在跑的进程**(里面可能有在飞训练)。
用法: python3 tools/merge_orphan_home.py [--apply]
"""
import filecmp
import json
import os
import shutil
import sys
import time

HOME = "/home/ubuntu"
REPO = "/home/ubuntu/zmax"
PAIRS = [
    (HOME + "/zmax_data", REPO + "/zmax_data"),
    (HOME + "/lerobot-smolvla-lew", REPO + "/external/lerobot-smolvla-lew"),
]
ARCHIVE = REPO + "/zmax_data/backups/orphan_home_%s" % time.strftime("%Y%m%d_%H%M%S")
MANIFEST = ARCHIVE + "/MERGE_MANIFEST.jsonl"


def main():
    apply = "--apply" in sys.argv
    rows = []
    for src_root, dst_root in PAIRS:
        if not os.path.isdir(src_root):
            print("  (跳过, 不存在) %s" % src_root)
            continue
        n_moved = n_arch = n_same = n_skip = 0
        for root, dirs, files in os.walk(src_root):
            for fn in files:
                sp = os.path.join(root, fn)
                rel = os.path.relpath(sp, src_root)
                dp = os.path.join(dst_root, rel)
                try:
                    sm, dm = os.path.getmtime(sp), os.path.getmtime(dp) if os.path.exists(dp) else -1
                except OSError:
                    continue
                if dm < 0:
                    act = "move"                       # 目标没有 -> 并过去
                elif sm > dm + 1:
                    act = "move"                       # 源更新 -> 以源为准
                else:
                    # 目标同新或更新 -> 归档源(留痕不丢)
                    try:
                        if filecmp.cmp(sp, dp, shallow=False):
                            act = "same"
                        else:
                            act = "archive"
                    except OSError:
                        act = "archive"
                rows.append({"src": sp, "dst": dp, "act": act})
                if not apply:
                    continue
                if act == "move":
                    os.makedirs(os.path.dirname(dp), exist_ok=True)
                    shutil.move(sp, dp)
                    n_moved += 1
                elif act == "archive":
                    ap = os.path.join(ARCHIVE, os.path.basename(src_root), rel)
                    os.makedirs(os.path.dirname(ap), exist_ok=True)
                    shutil.move(sp, ap)
                    n_arch += 1
                elif act == "same":
                    n_same += 1
                    os.remove(sp)
                else:
                    n_skip += 1
        print("  %-34s → 并回 %d · 归档 %d · 丢弃重复 %d" % (os.path.basename(src_root), n_moved, n_arch, n_same))
        # 清理空目录
        if apply:
            for root, dirs, files in os.walk(src_root, topdown=False):
                if not os.listdir(root):
                    try:
                        os.rmdir(root)
                    except OSError:
                        pass
    if apply:
        os.makedirs(ARCHIVE, exist_ok=True)
        with open(MANIFEST, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print("\n清单: %s" % MANIFEST)
        for src_root, _ in PAIRS:
            print("  剩余: %s %s" % (src_root, "还在" if os.path.isdir(src_root) else "已清空/移除"))
    else:
        print("预演: 共 %d 个文件待处理" % len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
