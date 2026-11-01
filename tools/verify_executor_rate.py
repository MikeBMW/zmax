#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_executor_rate.py — 机器人执行器变化率判据 (离线, 不动真机)

修的问题 (2026-11-01 老倪「修」): _LAST 原先类级共享且从不复位 ⇒ 下一轮第一拍拿上一轮末拍差分,
必误报"变化率超限"。修法: 共享保留(节点每拍 new 实例) + 加锁 + 按间隔判新周期 + reset()。

判据:
  ① 同一轮连续两拍突变 > max_rate ⇒ 真报 over_rate
  ② 每拍 new 实例也照样能判 (跨实例共享没被修坏)
  ③ 间隔 > ZMAX_RATE_STALE_S ⇒ 判为新周期, **不报** over_rate, 且 why 里说清
  ④ 显式 reset() ⇒ 下一拍是"首个指令", 不报
  ⑤ 维度变化 ⇒ 不判 (不拿 4 维比 3 维)
  ⑥ NaN ⇒ 整条归零 + valid=False
  ⑦ 多线程并发跑 200 次不炸, 末值长度一致
"""
import os
import sys
import threading

ROOT = "/home/ubuntu/zmax"
sys.path.insert(0, os.path.join(ROOT, "src"))

import numpy as np                                                        # noqa: E402

from lerobot.policies.left_right.state_space.execution import RobotExecutor as RE  # noqa: E402

ROWS = []


def ck(tag, name, ok, detail=""):
    ROWS.append((tag, ok, name, detail))
    print(("  ✅ " if ok else "  ❌ ") + "%s %s — %s" % (tag, name, detail))


def main() -> int:
    # ① 同一轮突变
    RE.reset("test")
    e = RE()
    e.execute(np.array([0.0, 0.0, 0.0, 0.0]))
    e2 = RE()                        # 每拍 new 一个实例 (模拟节点行为)
    e2.execute(np.array([0.9, 0.0, 0.0, 0.0]))
    ck("①", "同一轮突变 ⇒ 报 over_rate", bool(e2.last_check["over_rate"])
       and e2.last_check["over_rate"][0][0] == 0,
       "over_rate=%s · cycle=%s" % (e2.last_check["over_rate"], e2.last_check.get("cycle")))

    # ② 跨实例共享 (没被修坏)
    e3 = RE()
    e3.execute(np.array([0.0, 0.0, 0.0, 0.0]))
    hit = bool(e3.last_check["over_rate"])
    ck("②", "每拍 new 实例照样能判 (共享还在)", hit,
       "新实例上拍差 0.9 ⇒ over_rate=%s" % (e3.last_check["over_rate"][:1],))

    # ③ 新周期 (间隔超过阈值)
    RE.reset("test")
    a = RE()
    a.execute(np.array([0.0, 0.0, 0.0, 0.0]))
    RE._LAST_T = RE._LAST_T - (RE._RATE_STALE_S + 1.0)      # 假装上一拍是 3s 前
    b = RE()
    b.execute(np.array([0.9, 0.0, 0.0, 0.0]))
    ck("③", "间隔超阈值 ⇒ 新周期不判变化率", (not b.last_check["over_rate"])
       and "新周期" in str(b.last_check.get("cycle")),
       "cycle=%s · over_rate=%s" % (b.last_check.get("cycle"), b.last_check["over_rate"]))

    # ④ 显式 reset
    RE.reset("test")
    c = RE()
    c.execute(np.array([0.0, 0.0, 0.0, 0.0]))
    RE.reset("换轮")
    d = RE()
    d.execute(np.array([0.9, 0.0, 0.0, 0.0]))
    ck("④", "reset() ⇒ 下一拍按首指令 (不报)", (not d.last_check["over_rate"])
       and d.last_check.get("cycle") == "首个指令",
       "cycle=%s" % d.last_check.get("cycle"))

    # ⑤ 维度变化
    RE.reset("test")
    RE().execute(np.array([0.1, 0.1, 0.1, 0.1]))
    f = RE()
    f.execute(np.array([0.9, 0.9, 0.9]))
    ck("⑤", "维度变化 ⇒ 不判 (4维→3维)", (not f.last_check["over_rate"])
       and "维度变化" in str(f.last_check.get("cycle")),
       "cycle=%s" % f.last_check.get("cycle"))

    # ⑥ NaN 归零
    RE.reset("test")
    g = RE()
    out = g.execute(np.array([np.nan, 0.2, 0.3, 0.4]))
    ck("⑥", "NaN ⇒ 整条归零 + valid=False", (not g.last_check["valid"])
       and float(np.abs(out).sum()) == 0.0, "why=%s" % g.last_check["why"])

    # ⑦ 并发
    RE.reset("test")
    err = []

    def work(i):
        try:
            for k in range(50):
                RE().execute(np.array([0.01 * (i + k), 0.0, 0.0, 0.0]))
        except Exception as e:                                           # noqa: BLE001
            err.append("%s: %s" % (type(e).__name__, e))

    ts = [threading.Thread(target=work, args=(i,)) for i in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    ck("⑦", "4 线程 × 50 拍并发不炸", not err and RE._LAST is not None and RE._LAST.size == 4,
       "err=%s · _LAST=%s" % (err[:1], (RE._LAST.tolist() if RE._LAST is not None else None)))

    npass = sum(1 for r in ROWS if r[1])
    print("\n判据: PASS %d / FAIL %d   (stale阈值 %.1fs)" % (npass, len(ROWS) - npass, RE._RATE_STALE_S))
    return 0 if npass == len(ROWS) else 1


if __name__ == "__main__":
    sys.exit(main())
