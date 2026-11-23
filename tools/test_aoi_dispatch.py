#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_aoi_dispatch.py —— 质量检测调度自检 (由万有引力节点调用的那条路)

判据六条:
  ① 到位点解析: 156→gold(10082) · 172→surface(10083) · 点名「金手指检测点2」→10082 · 「表面检测点」→10083
  ② 一轮内每个点只派发一次 (重复 tick 不再发)
  ③ 下一轮(rounds+1)同一点会再发
  ④ 冷却窗口内同类型不连发
  ⑤ tick 非阻塞: 200 次调用平均 <2ms (HTTP 在工作线程)
  ⑥ 真机: 真发一次 /capture_detect 并回读 /last_result (拿不到就如实 unavailable)
用法: PYTHONPATH=src ./gui-venv311/bin/python tools/test_aoi_dispatch.py [--live]
"""
from __future__ import annotations

import json
import sys
import time

sys.path.insert(0, "/home/ubuntu/zmax/src")

from lerobot.manifold import aoi_dispatch as A        # noqa: E402

fails = []


def chk(name, cond, extra=""):
    print(("  ✅ " if cond else "  ❌ ") + name + ((" · " + str(extra)) if extra else ""))
    if not cond:
        fails.append(name)


def main():
    live = "--live" in sys.argv
    print("[①] 到位点解析")
    chk("156 → gold/10082", A.resolve(156) == [("gold", 10082)], A.resolve(156))
    chk("172 → surface/10083", A.resolve(172) == [("surface", 10083)], A.resolve(172))
    chk("名字 金手指检测点2", A.resolve(None, "金手指检测点2") == [("gold", 10082)])
    chk("名字 表面检测点", A.resolve(None, "表面检测点") == [("surface", 10083)])
    chk("非检测点不触发", A.resolve(93) == [] and A.resolve(None, "插入到位") == [])

    print("[②③④] 去重 / 跨轮 / 冷却")
    A0 = A._Dispatcher()                                  # 用新实例, 不污染全局统计
    r1 = A0.request("gold", idx=156, rounds=1)
    r2 = A0.request("gold", idx=156, rounds=1)            # 冷却 + 同轮去重
    chk("首次派发 fired=True", r1.get("fired") is True, r1)
    chk("同轮重复不派发", r2.get("fired") is False, r2.get("why"))
    A0.last_fire["gold"] = 0.0                            # 跳过冷却, 只测跨轮
    r3 = A0.request("gold", idx=156, rounds=2)
    chk("下一轮会再发", r3.get("fired") is True, r3)
    A0.last_fire["gold"] = time.monotonic()
    r4 = A0.request("gold", idx=156, rounds=3)
    chk("冷却窗口内不连发", r4.get("fired") is False, r4.get("why"))

    print("[⑤] tick 非阻塞 (200 次)")
    A1 = A._Dispatcher()
    t0 = time.monotonic()
    for i in range(200):
        A1.tick(idx=150 + (i % 20), rounds=1)
    ms = (time.monotonic() - t0) * 1000.0 / 200.0
    chk("平均 tick < 2ms", ms < 2.0, "%.3fms/次" % ms)

    print("[⑦] 轨迹流陈旧 ⇒ 不按旧 cursor 发检测")
    import tempfile, os
    A3 = A._Dispatcher()
    td = tempfile.mkdtemp()
    os.makedirs(os.path.join(td, "zmax_data/ss_live"), exist_ok=True)
    fp = os.path.join(td, "zmax_data/ss_live/traj_flow.json")
    json.dump({"phase": "RUN", "cursor": 156, "rounds": 7, "ts": time.time() - 600}, open(fp, "w"))
    s = A3.tick(root=td)
    chk("陈旧 flow 不发", s.get("fired") == [] and "skipped" in s, s.get("skipped"))

    print("[⑧] 端到端: 新鲜 flow 的 cursor 扫过 150→175")
    A4 = A._Dispatcher()
    A4.last_fire.clear()
    fires = []
    for c in range(150, 176):
        json.dump({"phase": "RUN", "cursor": c, "rounds": 1, "ts": time.time()}, open(fp, "w"))
        out = A4.tick(root=td)
        for f in out.get("fired") or []:
            fires.append((c, f["kind"], f["port"]))
        time.sleep(0.005)
    chk("恰好两次: 金手指 + 表面", [(k, p) for _, k, p in fires] == [("gold", 10082), ("surface", 10083)], fires)
    chk("金手指在 155~157 窗口内", 155 <= fires[0][0] <= 157, fires[0][0])
    chk("表面在 171~173 窗口内", 171 <= fires[1][0] <= 173, fires[1][0])

    if live:
        print("[⑥] 真机派发 (156 → 10082 金手指)")
        A2 = A._Dispatcher()
        r = A2.request("gold", idx=156, rounds=99, reason="自检")
        print("   request:", json.dumps(r, ensure_ascii=False))
        for _ in range(40):
            if A2.stats["done"] or A2.stats["fail"]:
                break
            time.sleep(0.1)
        snap = A2.snapshot() if hasattr(A2, "snapshot") else {}
        with A2.lock:
            res = dict(A2.results)
            jobs = list(A2.jobs[-1:])
        print("   结果:", json.dumps(res, ensure_ascii=False)[:300])
        print("   最近作业:", json.dumps(jobs, ensure_ascii=False)[:300])
        chk("POST 到位 (ok 或明确错误, 不静默)", bool(jobs), jobs[-1].get("err") if jobs else "无作业")
        chk("判决不造假 (verdict 有值)", bool(res.get("gold", {}).get("verdict")),
            res.get("gold", {}).get("verdict"))

    print()
    if fails:
        print("❌ %d 项未过: %s" % (len(fails), fails))
        return 1
    print("✅ 全过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
