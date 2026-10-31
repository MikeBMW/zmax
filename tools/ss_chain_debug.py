#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_chain_debug.py — 🐞 单进程调试入口 (VSCode F5 直接跑这个文件)

为什么要有它: 生产的技能派发是独立 systemd 单元 (pid 和 studio 不是一个), 所以在 IDE 里
给 `SK05Lift.clamp` / `InertiaLimiter.limit` 打红点, 只要那份代码不在你调试的进程里跑,
红点就永远不会停 —— 跟代码写没写、断点打没打对无关。

这个文件把「派发 → 技能 clamp → 四道闸」拉进**当前这一个进程**, 一拍一拍跑:

    python tools/ss_chain_debug.py                # 默认 60Hz 跑 10 秒
    python tools/ss_chain_debug.py --hz 10 --seconds 30
    python tools/ss_chain_debug.py --probe        # 额外统计每个技能 clamp 被调了几次 (证明真跑)

红点打在这些地方都会停:
    src/.../skills/atomic_skills.py     SK05Lift.clamp 里任意一行 (比如 ② 加速度那行)
    tools/ss_skill_dispatch.py          _phys() 里 r = _sk.clamp(...)
    src/.../physics_constraints.py      KinematicLimiter.limit (只在无技能段兜底时才走)

⚠️ 单进程跑之前, 把生产派发停掉, 免得两个进程同时写 skill_*.json:
    sudo systemctl stop zmax-ss-skill-dispatch
⚠️ 真要只读不写, 用隔离目录:
    ZMAX_LIVE_DIR=/tmp/dbg_live python tools/ss_chain_debug.py --probe
"""
from __future__ import annotations

import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(ROOT, "src"), os.path.join(ROOT, "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hz", type=float, default=60.0)
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--probe", action="store_true", help="统计每个技能 clamp 调用次数/本进程 pid")
    a = ap.parse_args()

    import ss_skill_dispatch as sd

    hits = {}
    if a.probe:
        from lerobot.policies.left_right.state_space.skills.atomic_skills import SKILLS
        for cls in SKILLS:
            orig = cls.clamp

            def wrap(self, u, dt=None, v_prev=None, a_prev=None, dmdt=None, _o=orig, _c=cls):
                r = _o(self, u, dt=dt, v_prev=v_prev, a_prev=a_prev, dmdt=dmdt)
                hits[_c.__name__] = hits.get(_c.__name__, 0) + 1
                return r

            cls.clamp = wrap

    d = sd.Dispatcher(hz=a.hz)
    n = int(max(1, a.hz * a.seconds))
    print("pid=%d  hz=%.1f  拍数=%d  LIVE=%s" % (os.getpid(), a.hz, n, sd.LIVE), flush=True)
    t0 = time.time()
    for i in range(n):
        d.cycle()
        if i % max(1, int(a.hz)) == 0:
            print("  #%4d 在职=%s 闸拍=%s" % (i, d.active or "-", getattr(d, "n_all", 0)), flush=True)
        nap = t0 + (i + 1) / a.hz - time.time()
        if nap > 0:
            time.sleep(nap)
    print("完成: 拍=%d 在职=%s 切换=%d 闸拍=%d 削因=%s"
          % (n, d.active or "-", d.n_switch, d.n_all, d.cut_n), flush=True)
    if a.probe:
        tot = sum(hits.values())
        print("本进程 pid=%d 里技能 clamp 调用: 合计 %d 次 · %s"
              % (os.getpid(), tot, {k: v for k, v in sorted(hits.items()) if v}), flush=True)
        return 0 if tot > 0 else 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
