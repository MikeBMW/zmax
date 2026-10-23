#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pull_symmetry_params.py — 把 Intel 进化出来的轨道参数采纳到本机引擎 (闭环最后一段)

链路: Intel `symmetry_evolve.py` 6 路搜索 → `symmetry_best.json`
      → 本脚本拉回 → 与已采纳参数比 → 提升 ≥ MARGIN 才采纳
      → 写 `zmax_data/ss_live/orbit_params.json` → 重启 `zmax-ss-engine-loop` 让引擎按新参数跑。

纪律: 只采纳"确实更好"的 (同源数据同判据), 且 1 小时内最多采纳一次 (避免反复重启常驻)。
用法: python3 tools/pull_symmetry_params.py [--dry-run] [--force]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

REPO = "/home/ubuntu/zmax"
LIVE = os.path.join(REPO, "zmax_data", "ss_live")
REMOTE = "intel@192.168.23.70:/home/intel/evolve/symmetry_best.json"
FETCHED = os.path.join(LIVE, "symmetry_best_intel.json")
PARAMS = os.path.join(LIVE, "orbit_params.json")
ADOPTED = os.path.join(LIVE, "orbit_params_adopted.json")
MARGIN = 0.05
MIN_SECS = 3600
SVC = "zmax-ss-engine-loop"


def sh(cmd, timeout=30):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)


def main():
    dry = "--dry-run" in sys.argv
    force = "--force" in sys.argv
    os.makedirs(LIVE, exist_ok=True)
    r = sh("scp -q -o ConnectTimeout=8 %s %s" % (REMOTE, FETCHED), timeout=40)
    if r.returncode != 0 or not os.path.isfile(FETCHED):
        print("拉取失败 (Intel 不可达或文件不在): %s" % (r.stderr or "").strip()[:160])
        return 2
    best = json.load(open(FETCHED))
    score = float((best.get("metrics") or {}).get("score") or -9)
    genome = best.get("genome") or {}
    prev = {}
    if os.path.isfile(ADOPTED):
        try:
            prev = json.load(open(ADOPTED))
        except Exception:                                                  # noqa: BLE001
            prev = {}
    pscore = float(prev.get("score") or -9)
    age = time.time() - float(prev.get("adopted_ts") or 0)
    better = score > pscore + MARGIN
    print("Intel best: score=%.4f cov=%s err_rel=%s bp=%s · 已采纳 %.4f · 差 %+.4f"
          % (score, best["metrics"].get("cov"), best["metrics"].get("err_rel"),
             best["metrics"].get("break_prec"), pscore, score - pscore))
    if not (better or force):
        print("不采纳 (提升 < %.2f 或未超过); 上次采纳 %.0f 分钟前" % (MARGIN, age / 60.0))
        return 0
    if age < MIN_SECS and not force:
        print("不采纳: 距上次采纳仅 %.0f 分钟 (< %d 分钟)" % (age / 60.0, MIN_SECS // 60))
        return 0
    out = {"genome": genome, "score": score, "metrics": best.get("metrics"),
           "source": "intel symmetry_evolve %s" % best.get("at"), "pulled_at": time.strftime("%F %T")}
    if dry:
        print("[dry-run] 将写入 %s:\n%s" % (PARAMS, json.dumps(out, ensure_ascii=False, indent=1)))
        return 0
    json.dump(out, open(PARAMS, "w"), ensure_ascii=False, indent=1)
    json.dump({**out, "adopted_ts": time.time(),
               "history": (prev.get("history") or [])[-9:] + [{"score": score, "at": out["pulled_at"]}]},
              open(ADOPTED, "w"), ensure_ascii=False, indent=1)
    r2 = sh("systemctl is-active %s" % SVC)
    if r2.stdout.strip() != "active":
        print("引擎常驻未在跑, 只写参数不重启")
        return 0
    r3 = sh("sudo -n systemctl restart %s" % SVC, timeout=60)
    print("已采纳并重启 %s (rc=%d)" % (SVC, r3.returncode))
    return 0


if __name__ == "__main__":
    sys.exit(main())
