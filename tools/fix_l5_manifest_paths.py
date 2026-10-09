#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 L5 SFT 清单里的旧绝对路径 (data/l5_vlm_sft/...) 修正为现路径 (data/datasets/l5_vlm_sft/...)

背景: 2026-10-09 数据整合把 data/l5_vlm_sft 迁到 data/datasets/l5_vlm_sft, 但 jsonl 里写的是
旧绝对路径 ⇒ 38/38 样本 FileNotFoundError, L5 训练空样本失败。此脚本只做路径改写, 不碰内容。
先备份到 zmax_data/backups/ , 再原地改写, 最后逐条校验文件存在。
"""
import json
import os
import shutil
import time

ROOT = "/home/ubuntu/zmax"
DATA = os.path.join(ROOT, "data/datasets/l5_vlm_sft")
BK = os.path.join(ROOT, "zmax_data/backups/l5_vlm_sft_manifest_fix_%s" % time.strftime("%Y%m%d_%H%M%S"))

os.makedirs(BK, exist_ok=True)
files = [f for f in sorted(os.listdir(DATA)) if f.endswith(".jsonl")]
total = fixed = 0
for fn in files:
    src = os.path.join(DATA, fn)
    rows = []
    n_fix = 0
    for line in open(src, encoding="utf-8"):
        if not line.strip():
            continue
        r = json.loads(line)
        p = r.get("image") or ""
        if p and not os.path.exists(p):
            cand = ""
            # ① 尾段重挂到 DATA (l5_vlm_sft 内部迁移)
            if "l5_vlm_sft/" in p:
                c = os.path.join(DATA, p.split("l5_vlm_sft/", 1)[-1])
                cand = c if os.path.exists(c) else ""
            # ② data/<x> → data/datasets/<x> (yolo_annot 等目录整体挪进 datasets/ 的通用修补)
            if not cand and "/data/" in p:
                tail = p.split("/data/", 1)[-1]
                c = os.path.join(ROOT, "data/datasets", tail)
                cand = c if os.path.exists(c) else ""
            # ③ 按文件名全盘找 (兜底)
            if not cand:
                b = os.path.basename(p)
                for root, _dirs, fs in os.walk(os.path.join(ROOT, "data")):
                    if b in fs:
                        cand = os.path.join(root, b)
                        break
            if cand:
                r["image"] = cand
                n_fix += 1
        rows.append(r)
    shutil.copy2(src, os.path.join(BK, fn))
    with open(src, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    total += len(rows)
    fixed += n_fix
    print("  %-18s %3d 条 · 修正 %3d" % (fn, len(rows), n_fix))

print("\n合计 %d 条, 修正 %d 条" % (total, fixed))
# 校验
bad = 0
for fn in files:
    for line in open(os.path.join(DATA, fn), encoding="utf-8"):
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("image") and not os.path.exists(r["image"]):
            bad += 1
print("改写后仍缺图: %d 条 %s" % (bad, "✅" if bad == 0 else "❌"))
print("备份: %s" % BK)
