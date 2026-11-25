#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""昼夜架构 CLI —— 状态空间的"作息表"入口。

    python -m lerobot.manifold.daynight.cli status
    python -m lerobot.manifold.daynight.cli collect --tail 4000   # 白天: 收噪声日志
    python -m lerobot.manifold.daynight.cli day --scope 插拔       # 白天开始(相位闸打开)
    python -m lerobot.manifold.daynight.cli night                 # 夜间: 对齐+固化+闸门+原子切换
    python -m lerobot.manifold.daynight.cli promote <cand.json>    # 手动切换(闸门过了但想晚点切)
"""
from __future__ import annotations

import argparse
import json
import sys

from . import consolidate, daylog, online, phase, train_night


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="daynight")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status")

    p_col = sub.add_parser("collect")
    p_col.add_argument("--day", default="")
    p_col.add_argument("--tail", type=int, default=4000)

    p_day = sub.add_parser("day")
    p_day.add_argument("--scope", default="")

    p_night = sub.add_parser("night")
    p_night.add_argument("--day", default="")
    p_night.add_argument("--no-promote", action="store_true")

    p_learn = sub.add_parser("learn")          # 白天: 在线学习(有界 RLS)
    p_learn.add_argument("--day", default="")
    p_learn.add_argument("--steps", type=int, default=0)

    p_sh = sub.add_parser("shadow")            # 白天: 影子评估(只记录不切换)
    p_sh.add_argument("--day", default="")
    p_sh.add_argument("--window", type=int, default=500)

    p_tr = sub.add_parser("train")             # 夜间: XPU 训练 + 闸门 + 原子切换
    p_tr.add_argument("--day", default="")
    p_tr.add_argument("--epochs", type=int, default=30)
    p_tr.add_argument("--horizon", type=int, default=20)
    p_tr.add_argument("--no-promote", action="store_true")

    p_auto = sub.add_parser("auto")            # 作息自动机: 白天边学, 夜间训练(给 cron/systemd 调)
    p_auto.add_argument("--day-hours", default="7-21")
    p_auto.add_argument("--epochs", type=int, default=60)

    p_pro = sub.add_parser("promote")
    p_pro.add_argument("cand")

    a = ap.parse_args(argv)

    if a.cmd == "status":
        st = phase.read_state()
        prior = consolidate.load_prior()
        out = {"phase": st, "prior": {k: prior.get(k) for k in ("ver", "n", "th_mm", "p", "H", "k_share")},
               "days": daylog.days()[-3:]}
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0

    if a.cmd == "day":
        st = phase.start_day(scope=a.scope, why="白天开始" + ("(%s)" % a.scope if a.scope else ""))
        print(json.dumps(st, ensure_ascii=False, indent=1))
        return 0

    if a.cmd == "collect":
        st = phase.read_state()
        did = a.day or st.get("day_id") or daylog.new_day_id()
        if st.get("phase") != "day":
            phase.start_day(why="collect 自动进入白天")
        r = daylog.collect_live(did, tail=a.tail)
        r["summary"] = daylog.summarize(did)
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0

    if a.cmd == "night":
        rep = consolidate.night_run(day_id=a.day, why="夜间: 手动触发",
                                    promote_if_pass=not a.no_promote)
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        return 0 if rep.get("ok", True) else 2

    if a.cmd == "learn":
        st = phase.read_state()
        if st.get("phase") != "day":
            phase.start_day(why="learn 自动进入白天(边学边用)")
        print(json.dumps(online.learn_day(a.day, steps=a.steps), ensure_ascii=False, indent=1))
        return 0

    if a.cmd == "shadow":
        print(json.dumps(online.shadow_eval(a.day, window=a.window), ensure_ascii=False, indent=1))
        return 0

    if a.cmd == "train":
        rep = train_night.train(day_id=a.day, epochs=a.epochs, horizon=a.horizon,
                               promote_if_pass=not a.no_promote)
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        return 0 if rep.get("ok", True) else 2

    if a.cmd == "auto":
        import time as _t
        h = _t.localtime().tm_hour
        lo, hi = [int(x) for x in a.day_hours.split("-")]
        is_day = lo <= h < hi
        if is_day:
            st = phase.read_state()
            if st.get("phase") != "day":
                phase.start_day(why="cron: 进入白天窗口(%d时)" % h)
            # 优先用**有数据**的那一天(550C 自己不采相机, 日志靠产线机推过来)
            have = [d for d in daylog.days() if daylog.summarize(d).get("valid", 0) > 0]
            did = have[-1] if have else (phase.read_state().get("day_id") or daylog.new_day_id())
            try:
                col = daylog.collect_live(did, tail=5000)
            except Exception as e:                                  # noqa: BLE001
                col = {"added": 0, "why": "本机无实时源: %s" % e}
            ln = online.learn_day(did)
            sh = online.shadow_eval(did, window=800)
            out = {"mode": "day", "hour": h, "collect": col.get("added"),
                   "learn": {k: ln.get(k) for k in ("ok", "steps_added", "rmse_batch", "w_norm")},
                   "shadow": sh}
        else:
            rep = consolidate.night_run(why="cron: 夜间窗口(%d时)" % h)
            tr = train_night.train(epochs=a.epochs)
            out = {"mode": "night", "hour": h,
                   "consolidate": {"passed": (rep.get("gate") or {}).get("passed"),
                                   "improve_pct": (rep.get("gate") or {}).get("improve_pct"),
                                   "promoted": rep.get("promoted")},
                   "train": {k: tr.get(k) for k in ("ok", "device", "params", "dur_s", "promoted")},
                   "train_gate": tr.get("gate")}
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0

    if a.cmd == "promote":
        print(json.dumps(consolidate.promote(a.cand), ensure_ascii=False, indent=1))
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
