#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""流形引擎输出 topic 收不到样本时的**链路分段取证** (不猜):
  ① tap 目录/文件 (守护读的那个)  ② 守护的 read_torque 返回什么
  ③ 用守护同一套类型/URI 起一个订阅, 看有没有样本 + matched pubs
用法: venvs/dds-venv/bin/python tools/probe_ss_torque_chain.py [秒]
"""
import os
import sys
import time

ROOT = "/home/ubuntu/zmax"
sys.path.insert(0, os.path.join(ROOT, "tools", "dds"))
sys.path.insert(0, os.path.join(ROOT, "dds"))

print("① CYCLONEDDS_URI(前) =", os.environ.get("CYCLONEDDS_URI"))
import ss_daemon as D                                                               # noqa: E402

print("   TORQUE_TAP_DIR =", getattr(D, "TORQUE_TAP_DIR", "缺失"))
print("   SS_REMOTE      =", getattr(D, "SS_REMOTE", "缺失"))
try:
    import glob
    for f in sorted(glob.glob(os.path.join(getattr(D, "TORQUE_TAP_DIR", ""), "torque_*.jsonl"))):
        print("   tap: %-52s %8.1fKB  mtime %s"
              % (os.path.basename(f), os.path.getsize(f) / 1024.0,
                 time.strftime("%H:%M:%S", time.localtime(os.path.getmtime(f)))))
except Exception as e:                                                              # noqa: BLE001
    print("   tap 枚举失败:", e)

print("② 守护算出来的扭矩帧:", flush=True)
try:
    d = D.read_torque()
    if not d:
        print("   read_torque() → None (守护认为没有新鲜 tap ⇒ 不会发)")
    else:
        print("   type=%s keys=%s" % (type(d).__name__, sorted(d)[:12]))
        for k in ("ts", "scene", "identity"):
            if k in d:
                print("   %s = %.5s" % (k, d[k]))
except Exception as e:                                                              # noqa: BLE001
    import traceback
    print("   read_torque() 抛异常:"); traceback.print_exc()

sec = float(sys.argv[1]) if len(sys.argv) > 1 else 8.0
print("③ 起订阅 (%ss):" % sec, flush=True)
try:
    from zmax_node import Node                                                      # noqa: E402
    n = Node("chain_probe", domain=0)
    rd = n.sub("ss_torque")
    t0 = time.time()
    got = 0
    while time.time() - t0 < sec:
        for s in rd.take_iter(timeout=1.0):
            got += 1
            print("   ✓ 收到 #%d ts=%s scene=%s task=%s M=%s"
                  % (got, getattr(s, "ts", None), getattr(s, "scene", None),
                     getattr(s, "task_id", None), getattr(s, "metric_M", None)))
            if got >= 2:
                break
        if got >= 2:
            break
    if not got:
        print("   ✗ %ss 内 0 样本 · 有效读者数/matched pubs:" % sec)
        for attr in ("matched_publications", "publication_matched_status"):
            try:
                print("     %s = %s" % (attr, getattr(rd, attr)))
            except Exception:                                                        # noqa: BLE001
                pass
except Exception as e:                                                              # noqa: BLE001
    import traceback
    print("   订阅侧异常:"); traceback.print_exc()

print("   CYCLONEDDS_URI(后) =", os.environ.get("CYCLONEDDS_URI"))
