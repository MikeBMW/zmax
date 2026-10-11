#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dds_verify_real.py — 「数据空间的 topic 是不是真实发出的 DDS 数据」可复用取证工具

背景 (老倪 2026-10-11 追问): 数据空间 topic 是不是真 DDS? 判定必须分三件事, 不能混:
  ① **总线真不真**  → selftest: 用工程自己的 Node/类型, 同进程自发自收
  ② **跨进程/跨机真不真** → pair: 两个进程, 一个发一个收 (同域)
  ③ **现在有没有真实数据** → listen: 按注册表允许话题订阅窗口, 统计条数 + 发布者配对

用法 (必须用 dds-venv):
  venvs/dds-venv/bin/python tools/dds_verify_real.py selftest
  venvs/dds-venv/bin/python tools/dds_verify_real.py pair          # 需另开一个进程跑 pair-sub
  venvs/dds-venv/bin/python tools/dds_verify_real.py pair-sub
  venvs/dds-venv/bin/python tools/dds_verify_real.py listen [秒] [话题...]

判据 (不夸大):
  · ① 成立 = DDS 机制真 (不是假总线)     · ② 成立 = 进程间真能互通
  · ③ 有样本 = 此刻真在发; 0 条/0 配对 = 管道真但源头没数据 (看 zmax_data/ss_live/ 与 /tmp/zmax_dds_ss.log)
"""
from __future__ import annotations

import json
import os
import sys
import time

REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")
sys.path.insert(0, os.path.join(REPO, "dds"))

from ss_types import SSAction, SSState                                          # noqa: E402
from zmax_node import Node                                                      # noqa: E402

# calib 档允许的话题 (与 tools/dds/ss_daemon.py MODE_TOPICS 同源)
CALIB_TOPICS = ["ss_state", "ss_action", "link_value", "hw_state", "heartbeat",
                "ss_calib", "ss_diag", "ss_plan", "ss_energy"]
TOPIC = "ss_state"
_TYPE = {TOPIC: SSState, "ss_action": SSAction}


def _node(tag):
    return Node("zmax-verify-" + tag, domain=0)


def selftest():
    """同进程自发自收 (证 DDS API/类型/QoS 可用)。"""
    n = _node("selftest")
    n.pub(TOPIC)
    n.sub(TOPIC)
    for i in range(5):
        n.send(TOPIC, SSState(ts=time.time(), layer="L2", stage="selftest", vec=[float(i)] * 6, dim=6,
                              pos_x=0.1 * i, pos_y=0.2, pos_z=0.3, source="selftest",
                              note="bus check #%d" % i))
        time.sleep(0.2)
    got, t0 = [], time.time()
    while time.time() - t0 < 6 and not got:
        got += (n.take(TOPIC, timeout=0.5) or [])
    ok = bool(got)
    print("%s 同进程自发自收: 发 5 条, 收 %d 条" % ("✅" if ok else "❌", len(got)))
    return 0 if ok else 1


def pair_pub():
    n = _node("pair-pub")
    n.pub(TOPIC)
    time.sleep(2)
    for i in range(15):
        n.send(TOPIC, SSState(ts=time.time(), layer="L2", stage="xproc", vec=[float(i)] * 6, dim=6,
                              pos_x=float(i), pos_y=0.0, pos_z=0.0, source="xproc-pub",
                              note="xproc #%d" % i))
        time.sleep(0.5)
    print("✅ 跨进程发布端: 已发 15 条 → %s" % TOPIC)
    return 0


def pair_sub():
    n = _node("pair-sub")
    n.sub(TOPIC)
    got, t0 = [], time.time()
    while time.time() - t0 < 16:
        got += (n.take(TOPIC, timeout=0.4) or [])
    ok = bool(got)
    print("%s 跨进程订阅端: 收到 %d 条" % ("✅" if ok else "❌", len(got)))
    return 0 if ok else 1


def listen(secs=25.0, topics=None):
    """窗口内统计: 每个话题 配对 + 真收条数 (take() 返回**列表**, 空列表 ≠ 一条)。"""
    topics = topics or CALIB_TOPICS
    n = _node("listen")
    subs = []
    for t in topics:
        try:
            n.sub(t)
            subs.append(t)
        except Exception as e:                                                  # noqa: BLE001
            print("  订阅失败 %-12s %s: %s" % (t, type(e).__name__, str(e)[:60]))
    print("\n── ① 发布者配对 (有真远端 DataWriter 才 True) ──")
    for t in subs:
        try:
            print("  %-12s 配对=%s" % (t, bool(n.wait_for_match(t, n=1, timeout=3.0))))
        except Exception:                                                       # noqa: BLE001
            print("  %-12s 配对=? (不支持)" % t)
    print("\n── ② 窗口内真收样本 (%gs) ──" % secs)
    cnt = dict.fromkeys(subs, 0)
    t0 = time.time()
    while time.time() - t0 < secs:
        for t in subs:
            try:
                cnt[t] += len(n.take(t, timeout=0.02) or [])
            except Exception:                                                   # noqa: BLE001
                pass
    for t in subs:
        print("  %-12s %4d 条" % (t, cnt[t]))
    alive = [t for t, v in cnt.items() if v > 0]
    print("\n合计: 有样本话题 %d/%d %s" % (len(alive), len(subs), alive or "(无 → 管道真, 源头没数据)"))
    return 0 if alive else 2


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "listen"
    if cmd == "selftest":
        sys.exit(selftest())
    if cmd == "pair":
        sys.exit(pair_pub())
    if cmd == "pair-sub":
        sys.exit(pair_sub())
    secs = float(sys.argv[2]) if len(sys.argv) > 2 else 25.0
    sys.exit(listen(secs, sys.argv[3:] or None))
