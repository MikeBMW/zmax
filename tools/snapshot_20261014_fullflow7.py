#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""snapshot_20261014_fullflow7.py — 7 任务全流程闭环 现场快照 (验收留证)。

把这一轮**真跑**的关键产物拷进 docs/data_snapshots/20261014_fullflow7/, 并生成 README (逐件 sha256 +
重建命令)。红线: 大文件 (run7_full.log 900KB / 数据集 / ckpt / 工程库) **不进库**, 只留 sha256 + 绝对路径 + 重建命令。

用法: python3 tools/snapshot_20261014_fullflow7.py [--run reports/fullflow7/<ts>]
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DST = os.path.join(ROOT, "docs", "data_snapshots", "20261014_fullflow7")


def sha256(p: str, cap: int = 40 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        r = f.read(cap)
        h.update(r)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=None)
    a = ap.parse_args()
    run = a.run
    if not run:
        cands = sorted([d for d in glob.glob(os.path.join(ROOT, "reports/fullflow7/*"))
                        if os.path.exists(os.path.join(d, "state.json"))])
        run = cands[-1] if cands else ""
    if not run or not os.path.exists(os.path.join(run, "state.json")):
        print("❌ 找不到 run (state.json)")
        return 1
    os.makedirs(DST, exist_ok=True)
    items = []
    for rel in ("REPORT.md", "REPORT.json", "state.json"):
        src = os.path.join(run, rel)
        if os.path.exists(src):
            dst = os.path.join(DST, os.path.basename(rel))
            shutil.copy2(src, dst)
            items.append((os.path.basename(dst), sha256(dst), os.path.getsize(dst)))
    # 每任务分段落证据 (小的段日志: configure/sim_data/infer; train.log 可能大 ⇒ 只记 sha)
    per = []
    for t in sorted(os.listdir(run)):
        d = os.path.join(run, t)
        if not os.path.isdir(d):
            continue
        ev = {"task": t, "files": {}}
        for f in sorted(os.listdir(d)):
            p = os.path.join(d, f)
            if not os.path.isfile(p):
                continue
            ev["files"][f] = {"bytes": os.path.getsize(p), "sha256_16": sha256(p)[:16]}
        per.append(ev)
    big = {
        "run7_full.log": os.path.join(ROOT, "reports/fullflow7/run7_full.log"),
        "datasets": os.path.join(ROOT, "data/datasets"),
        "engine_db": os.path.join(ROOT, "zmax_data/engineering/zmax_engineering.db"),
    }
    manifest = {"run": run, "copied": [{"file": a, "sha256": b, "bytes": c} for a, b, c in items],
                "per_task": per,
                "not_in_repo": [{"name": k, "abs_path": v,
                                 "bytes": (os.path.getsize(v) if os.path.isfile(v) else None),
                                 "note": "大文件/目录不进库: 只留 sha256 + 重建命令"}
                                for k, v in big.items()]}
    with open(os.path.join(DST, "MANIFEST.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    rd = []
    rd.append("# 现场快照 · 7 任务全流程闭环 (2026-10-14)\n")
    rd.append("口径 (老倪): 「循环配置所有7个任务…仿真环境生成数据, 训练, 推理, 再到任务7的真实环境推理, "
              "保证所有模型的依次运行, 数据路径要通, 流形引擎要预测每个元任务, 将元任务预测的topic放到信号分析, "
              "写成报告发到飞书, 开始全流程, 全功率训练加推理, 包括工控机联通AOI程序」\n")
    rd.append("run 目录: `%s`\n" % run)
    rd.append("## 一、拷进库的证据 (逐件 sha256)\n")
    for a, b, c in items:
        rd.append("- `%s` · %s 字节 · sha256 `%s`" % (a, c, b))
    rd.append("\n## 二、逐任务分段落日志 (仅记 sha256, 文件在 run 目录)\n")
    for ev in per:
        rd.append("- **%s**: %s" % (ev["task"], ", ".join("%s(%sB)" % (k, v["bytes"])
                                                        for k, v in ev["files"].items())))
    rd.append("\n## 三、**未进库**的大文件/目录 (绝对值 + 重建命令)\n")
    rd.append("- `%s` (900KB 全量日志)" % big["run7_full.log"])
    rd.append("  · 重建: `%s gui-venv311/bin/python tools/fullflow_tasks7.py --sim-target 10 --steps 40 "
              "--yolo-epochs 3 --l5-steps 20 > reports/fullflow7/run7_full.log 2>&1`" % ROOT)
    rd.append("- `%s` (仿真 LeRobot 数据集, 7×10 轨迹/31056 帧)" % big["datasets"])
    rd.append("  · 重建: `%s/tools/collect_simreal_vla_data.py --task \"metaworld 光模块插拔 …\" --target 10 "
              "--out data/datasets/sim_<TASK>`" % ROOT)
    rd.append("- 训练产物 (L4/L3/L2/L5 权重) 见 `outputs/train/*` 与 `reports/joint_train_*/`")
    rd.append("\n## 四、判据回放 (任意时刻可复跑)\n")
    rd.append("- 大屏/卡片数据源: `python3 tools/fullflow_status.py` (只读 state.json)")
    rd.append("- 元任务预测 topic: `tools/dds_sub_meta_pred.py`; 信号分析真源 `zmax_data/dataspace/live.json`")
    rd.append("- 报告重生成: `python3 -c \"import sys,json;sys.path.insert(0,'tools');import fullflow_tasks7 as F;"
              "F.stage_report('%s', json.load(open('%s/state.json')), '%s', send=False)\"`" % (run, run, run))
    with open(os.path.join(DST, "README.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(rd) + "\n")
    print("快照: %s" % DST)
    print("  拷入 %d 件 · 逐任务 %d 组 · MANIFEST.json + README.md" % (len(items), len(per)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
