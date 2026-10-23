#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""orbit_evolve_watch.py — Intel 550C 上常驻的对称性判读旁路 (老倪 2026-10-23)

每 5 分钟读一次进化台账, 用等改进量推演给出 keep/escalate, 追加到
/home/intel/evolve/advisor.jsonl。v6 落地的代起, 同一个函数直接参与采样决策;
在那之前它就是可观察的证据 (不改正在跑的这一代)。
"""
import json
import os
import sys
import time

TOOLS = "/home/intel/zmax_map/tools"
WORK = os.environ.get("EVO_WORK", "/home/intel/evolve")
sys.path.insert(0, TOOLS)
from orbit_evolve_advisor import advise      # noqa: E402

OUT = os.path.join(WORK, "advisor.jsonl")
while True:
    try:
        a = advise(ledger_path=os.path.join(WORK, "ledger.json"))
        a["at"] = time.strftime("%F %T")
        with open(OUT, "a", encoding="utf-8") as f:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")
    except Exception as e:                                             # noqa: BLE001
        with open(OUT, "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": time.strftime("%F %T"), "verdict": "error",
                                "why": "%s: %s" % (type(e).__name__, e)}, ensure_ascii=False) + "\n")
    time.sleep(300)
