#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔁 自主进化闭环（550A 训练 → 550C/引擎部署门禁）

一轮 = 演练取证 → 失败段识别 → 增量训练 → 产物整形 → 引擎接管门禁 → 报告
纪律:
  · 全自动但**不自动替换在役权重**: 只产出 candidate + 门禁结论, 晋级须人确认
  · 任一闸失败即整轮判失败, 不静默降级
  · 全部数字落 JSON, 供 PPT/验收引用
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

ROOT = "/home/ubuntu/zmax"
PY_TRAIN = f"{ROOT}/external/INTACT-JEPA/.venv/bin/python"
PY_ENG = f"{ROOT}/gui-venv311/bin/python"
DATA = f"{ROOT}/zmax_data/stable-wm-cache/datasets/mm_v6_roi.h5"
CKPT_ROOT = f"{ROOT}/zmax_data/stable-wm-cache/checkpoints"
REF_CFG = f"{CKPT_ROOT}/intact_l4_current/config.json"


def sh(cmd: str, timeout: int = 1500) -> tuple[int, str]:
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=200)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    tag = a.tag or time.strftime("%Y%m%d_%H%M%S")
    out = f"{ROOT}/reports/evolve_{tag}.json"
    rep: dict = {"tag": tag, "steps": a.steps, "seed": a.seed, "gates": {}}

    # ── 0. 环境 ────────────────────────────────────────────────
    rc, o = sh("nvidia-smi --query-gpu=name,memory.free --format=csv,noheader")
    rep["gpu"] = o.strip()
    rep["gates"]["gpu"] = {"ok": rc == 0, "detail": o.strip()}
    rep["gates"]["data"] = {"ok": os.path.exists(DATA), "detail": DATA}

    # ── 1. 演练取证: 找出耗时最长/未完成的阶段 ─────────────────
    rc, o = sh(f"ls -t {ROOT}/zmax_data/deliverables/rehearsal/*_summary.json | head -1")
    latest = o.strip().splitlines()[0] if o.strip() else ""
    fail_seg = {}
    if latest and os.path.exists(latest):
        s = json.load(open(latest))
        seg = s.get("stage_seconds", {})
        tot = sum(seg.values()) or 1.0
        fail_seg = {k: round(v / tot, 3) for k, v in sorted(seg.items(), key=lambda x: -x[1])[:3]}
        rep["rehearsal"] = {"file": latest, "frames": s.get("frames"), "done": s.get("done"),
                            "top_stages_share": fail_seg, "max_force": s.get("max_force_norm")}
    rep["gates"]["rehearsal"] = {"ok": bool(fail_seg), "detail": fail_seg}

    # ── 2. 增量训练 (一条 autograd 图) ─────────────────────────
    ck = f"{CKPT_ROOT}/evolve_{tag}"
    cmd = (f"cd {ROOT} && {PY_TRAIN} tools/joint_train_real_v6.py --h5 {DATA} "
           f"--steps {a.steps} --batch 6 --seed {a.seed} --save {ck} "
           f"--out {ROOT}/reports/evolve_{tag}_train.json")
    rc, o = sh(cmd)
    train_ok = rc == 0 and os.path.exists(f"{ck}/weights.pt")
    rep["gates"]["train"] = {"ok": train_ok, "ckpt": ck}
    if not train_ok:
        rep["gates"]["train"]["log_tail"] = o[-800:]
        json.dump(rep, open(out, "w"), ensure_ascii=False, indent=1)
        print("EVOLVE_FAIL train", out)
        return 1
    try:
        h = json.load(open(f"{ROOT}/reports/evolve_{tag}_train.json"))["hist"][-1]
        rep["train_last"] = {k: round(float(v), 5) for k, v in h.items()
                             if isinstance(v, (int, float))}
    except Exception:                                                # noqa: BLE001
        pass

    # ── 3. 产物整形 (扁平 weights + config; 目录内只留一个 .pt) ─
    for f in os.listdir(ck):
        if f.endswith(".pt") and f != "weights.pt":
            shutil.move(f"{ck}/{f}", f"{ck}/{f}.bak")
    if os.path.exists(REF_CFG) and not os.path.exists(f"{ck}/config.json"):
        shutil.copy(REF_CFG, f"{ck}/config.json")
    rep["gates"]["package"] = {"ok": os.path.exists(f"{ck}/weights.pt")
                               and os.path.exists(f"{ck}/config.json"),
                               "files": sorted(os.listdir(ck))}

    # ── 4. 引擎接管门禁 (w>0 / src=intact / refused==0) ────────
    log = f"{ROOT}/reports/evolve_{tag}_ab.log"
    cmd = (f"cd {ROOT} && INTACT_POLICY={os.path.basename(ck)} INTACT_RUNTIME=root SS_L4_INTACT=1 "
           f"MUJOCO_GL=egl {PY_ENG} tools/ab_v6_engine.py --arm A --ckpt {os.path.basename(ck)} "
           f"--steps 600 > {log} 2>&1")
    sh(cmd)
    txt = open(log, encoding="utf-8", errors="ignore").read() if os.path.exists(log) else ""
    m_w = re.search(r'"w":\s*([\d.]+)', txt) or re.search(r"'w':\s*([\d.]+)", txt)
    w = float(m_w.group(1)) if m_w else 0.0
    src_intact = "intact" in txt
    refused = 0
    m_r = re.search(r'"refused":\s*(\d+)', txt) or re.search(r"'refused':\s*(\d+)", txt)
    if m_r:
        refused = int(m_r.group(1))
    gate = w > 0 and src_intact and refused == 0
    rep["gates"]["engage"] = {"ok": gate, "w": w, "src_intact": src_intact,
                              "refused": refused, "log": log}

    # ── 5. 结论 ───────────────────────────────────────────────
    passed = all(g.get("ok") for g in rep["gates"].values())
    rep["verdict"] = "PASS" if passed else "FAIL"
    rep["deployable_candidate"] = ck if passed else None
    rep["note"] = ("全部闸通过, 候选权重可提交人确认晋级 (不自动替换在役)"
                   if passed else "存在未通过闸, 候选权重不晋级")
    json.dump(rep, open(out, "w"), ensure_ascii=False, indent=1)
    print(f"EVOLVE_{rep['verdict']} {out}")
    return 0 if passed else 2


if __name__ == "__main__":
    sys.exit(main())
