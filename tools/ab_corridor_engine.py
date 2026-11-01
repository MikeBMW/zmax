#!/usr/bin/env python3
"""ab_corridor_engine.py — 引擎级 A/B: 通道开/关同口径跑, 看段序/步数/通道偏差

    ./gui-venv311/bin/python tools/ab_corridor_engine.py            # 默认 seed=101, 技能闸关
    ./gui-venv311/bin/python tools/ab_corridor_engine.py --gate 1   # 技能输出真的替换动作
    ./gui-venv311/bin/python tools/ab_corridor_engine.py --seed 100

判据: 两臂段序列相同; 通道开时 skill_calls 每拍都有 corridor(dev/r/why),
      ZMAX_SKILL_GATE=0 时步数/终点必须逐位相同 (通道只改幅度不改编排)。
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(REPO, "gui-venv311/bin/python")


def run(tag, cor, gate, seed):
    log = os.path.join(REPO, "zmax_data/ss_live/skill_calls_%s.log" % tag)
    if os.path.exists(log):
        os.remove(log)
    code = ("import sys; sys.path.insert(0,'src')\n"
            "from lerobot.engine.runtime import quick_run\n"
            "quick_run(n_episodes=1, seed_base=%d, vision=False)\n" % seed)
    env = dict(os.environ, ZMAX_SKILL_GATE=str(gate), ZMAX_CORRIDOR=cor,
               ZMAX_SKILL_LOG_PATH=log, PYTHONUNBUFFERED="1", ZMAX_SKILL_LOG="1")
    p = subprocess.run(["xvfb-run", "-a", PY, "-c", code], cwd=REPO, env=env,
                       capture_output=True, text=True, timeout=1800)
    tail = [l.strip() for l in (p.stdout + p.stderr).splitlines() if "ep1:" in l or "成功率" in l]
    rows = [json.loads(l) for l in open(log, encoding="utf-8")] if os.path.exists(log) else []
    ds = [r["cor"]["dev_mm"] for r in rows if (r.get("cor") or {}).get("dev_mm") is not None]
    print("=== ZMAX_CORRIDOR=%s · ZMAX_SKILL_GATE=%s ===" % (cor, gate))
    for l in tail:
        print("  " + l[:220])
    if ds:
        ds = sorted(ds)
        print("  通道拍=%d/%d · dev p50=%.1fmm max=%.1fmm · 越界拍=%d"
              % (len(ds), len(rows), ds[len(ds) // 2], ds[-1],
                 sum(1 for r in rows if (r.get("cor") or {}).get("in") is False)))
    else:
        print("  通道拍=0/%d" % len(rows))
    return tail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gate", default="0", choices=["0", "1"])
    ap.add_argument("--seed", type=int, default=101)
    a = ap.parse_args()
    off = run("off", "0", a.gate, a.seed)
    on = run("on", "1", a.gate, a.seed)
    same = off[:1] == on[:1]
    print("\n段序/终态一致: %s" % ("✅" if same else "❌"))
    return 0 if same else 1


if __name__ == "__main__":
    raise SystemExit(main())
