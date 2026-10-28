#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""现场数据快照 (小版本迭代第①步: data/ 被 gitignore, 必须拷进 docs/data_snapshots/)

老倪口径: 「保存数据，小版本迭代」⇒ 把本轮唯一依据/证据拷进 docs/data_snapshots/<日期>_<主题>/,
生成 README + sha256, 之后才改版本号/提交。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time

ROOT = "/home/ubuntu/zmax"
TOPIC = "20261014_L4_latent_chain"
DST = os.path.join(ROOT, "docs", "data_snapshots", TOPIC)

ITEMS = [
    ("data/database/zmax/sources/canvas/state_space_obs.json", "画布唯一依据 (LoRA 入链 + 元任务预测接 LoRA)"),
    ("config/ss_task_binding.json", "任务↔节点绑定唯一依据"),
    ("config/calib/zmax_manifold.json", "主参数 M 唯一依据"),
    ("models/l4_latent_calib.json", "L4 潜空间标定 (μ/g_f/V/n 帧)"),
    ("zmax_data/ss_live/meta_tasks.json", "元任务派生件"),
    ("zmax_data/ss_live/meta_pred.json", "元任务预测值 (LoRA 门控唯一依据)"),
    ("zmax_data/ss_live/engine_loop_status.json", "常驻回路状态"),
    ("zmax_data/ss_live/engine_latest.json", "常驻回路最新一帧"),
    ("data/database/zmax/zmax_engineering.db", "工程库单文件"),
]


def sha(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main() -> int:
    os.makedirs(DST, exist_ok=True)
    rows = []
    for rel, why in ITEMS:
        src = os.path.join(ROOT, rel)
        if not os.path.exists(src):
            rows.append((rel, why, "缺", 0, "-"))
            continue
        out = os.path.join(DST, os.path.basename(rel))
        shutil.copy2(src, out)
        rows.append((rel, why, "已存", os.path.getsize(out), sha(out)[:16]))

    # 在役回路 tap 末 3 帧 + 判据输出 (证据留档)
    tap = "/dev/shm/zmax_ss_engine/engine_default.jsonl"
    if os.path.exists(tap):
        lines = open(tap, encoding="utf-8").read().strip().splitlines()[-3:]
        with open(os.path.join(DST, "engine_tap_last3.jsonl"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        rows.append(("tap 末 3 帧", "回路每周期一行 (含 encoder/z_source/z_latent)", "已存",
                     os.path.getsize(os.path.join(DST, "engine_tap_last3.jsonl")), "-"))

    judges = {"本机 python": subprocess.run(["python3", "-V"], capture_output=True, text=True).stdout.strip()}
    for name, cmd in (("L4 潜空间判据", ["tools/verify_l4_latent_space.py"]),
                      ("L4 LoRA 链判据", ["tools/verify_l4_lora_chain.py"])):
        r = subprocess.run([os.path.join(ROOT, "gui-venv311/bin/python"), os.path.join(ROOT, cmd[0])],
                           capture_output=True, text=True, timeout=600, cwd=ROOT,
                           env={**os.environ, "INTACT_POLICY": "intact_l4_current",
                                "STABLEWM_HOME": os.path.join(ROOT, "zmax_data/stable-wm-cache")})
        out = os.path.join(DST, name.replace(" ", "_") + ".txt")
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(r.stdout + r.stderr)
        tail = [l for l in r.stdout.splitlines() if "判据" in l]
        judges[name] = (tail[-1].strip() if tail else "无判据行") + " (完整输出见 %s)" % os.path.basename(out)

    readme = ["# 现场数据快照 — %s" % TOPIC, "",
              "> 主题: **L4 潜空间 (VLM 编码器 → 黎曼度规约束) + L4 后段链 (意图解码器 → INTACT LoRA 微调 → 流形专家预测器 → 接触/性能流形)**",
              "> 快照时间: %s · 触发: 老倪「保存数据，小版本迭代到 5.50.71」" % time.strftime("%Y-%m-%d %H:%M:%S"), "",
              "`data/` 与 `zmax_data/` 被 .gitignore 排除 ⇒ 唯一依据/证据必须拷贝进本目录才能进版本库。", "",
              "## 文件清单", "", "| 文件 | 来源 | 说明 | 大小 | sha256[:16] |", "|---|---|---|---|---|"]
    for rel, why, st, size, h in rows:
        readme.append("| %s | %s | %s | %s | %s |" % (os.path.basename(rel), rel, why + (" [" + st + "]" if st != "已存" else ""), size, h))
    readme += ["", "## 本轮判据 (原文见同目录 txt)", ""]
    for k, v in judges.items():
        readme.append("- **%s**: %s" % (k, v))
    readme += ["", "## 复现命令", "", "```bash",
               "cd /home/ubuntu/zmax",
               "INTACT_POLICY=intact_l4_current STABLEWM_HOME=$PWD/zmax_data/stable-wm-cache \\",
               "  ./gui-venv311/bin/python tools/verify_l4_latent_space.py     # L4 潜空间 10/10",
               "./gui-venv311/bin/python tools/verify_l4_lora_chain.py         # L4 后段链 8/8",
               "./gui-venv311/bin/python tools/verify_ss_engine_loop.py        # 常驻回路 16/16",
               "```"]
    with open(os.path.join(DST, "README.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(readme) + "\n")
    print("快照目录: %s" % DST)
    for rel, why, st, size, h in rows:
        print("  %-8s %-58s %8s B  %s" % (st, rel, size, h))
    print("README + 判据输出已写")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
