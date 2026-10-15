#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_signal_skill_topics.py — 【只读】离屏取证: 信号分析窗口里原子技能物理量到底有没有信号。

老倪 2026-10-15: 「所有的原子技能, 例如接近、对位, 都要有 topic 输出, 且在实时监控信号分析窗口都有对应的
信号; 我要在信号分析窗口看到实际的物理模型, x y z v a 等距离、速度、角度等物理值; 要实际发出来。」

本探针**只读不写**: offscreen 建 信号分析页 (CanoeGraphicWidget) → 采样 → 读回信号目录里的行:
  ① 技能物理量的行数 (每技能 x/y/z/v/a/s/angle/err + v_cap/a_max/jerk_max/s_step/s_max/m/F + 在职/step/位姿帧龄 → 18 行)
  ② 每行的当前值 / 单位 / 行色 (= 场景色; 技能物理量应为插拔场景绿 #2e8b57)
  ③ 勾选其中几条能不能真画出波形 (曲线点数 > 1)

用法:
  QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/probe_signal_skill_topics.py [--secs 8] [--shot 出图.png]
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--secs", type=float, default=8.0, help="采样秒数")
    ap.add_argument("--shot", default="", help="截图输出路径 (真机目检用)")
    a = ap.parse_args()

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtCore import Qt                                     # noqa: PLC0415
    from PyQt5.QtWidgets import QApplication, QTreeWidgetItemIterator    # noqa: PLC0415
    import canoe_graphic as CG                                      # noqa: PLC0415

    app = QApplication(sys.argv[:1])
    w = CG.CanoeGraphicWidget()
    w.resize(1900, 1000)
    w.show()
    try:
        w.start()
    except Exception as e:                                          # noqa: BLE001
        print("start() 异常: %s: %s" % (type(e).__name__, e))

    import time                                                     # noqa: PLC0415
    t0 = time.time()
    while time.time() - t0 < a.secs:
        app.processEvents()
        time.sleep(0.05)
    try:
        w.refresh_catalog(quiet=True)
        for _ in range(30):
            app.processEvents()
            time.sleep(0.05)
    except Exception as e:                                          # noqa: BLE001
        print("refresh_catalog 异常: %s" % e)

    # ── 读回: 信号目录里的原子技能行 ──
    HDR = ["信号", "当前值", "Min", "Max", "帧龄"]
    n_sk, rows, cols = 0, [], set()

    def _walk(node):                                                  # 递归走信号目录树 (不依赖迭代器类)
        out = [node]
        for i in range(node.childCount()):
            out += _walk(node.child(i))
        return out

    allnodes = []
    for i in range(w.tree.topLevelItemCount()):
        allnodes += _walk(w.tree.topLevelItem(i))
    for node in allnodes:
        if node.childCount():
            continue
        key = node.text(0)
        if "SK0" in key and "·" in key:
            n_sk += 1
            c = node.foreground(0).color().name()
            cols.add(c)
            rows.append((key, node.text(1), node.text(2), node.text(3), node.text(4), c))
    print("信号目录里原子技能物理量的行数 = %d (期望 8 技能 × 18 = 144: 实测 8 + 包络 7 + 在职/step/位姿帧龄 3)" % n_sk)
    print("行色集合 = %s (插拔场景绿 = #2e8b57)" % sorted(cols))
    print("\n%-46s %12s %12s %12s %9s %s" % tuple(HDR + ["行色"]))
    for k, v, mn, mx, age, c in rows[:12]:
        print("%-46s %12s %12s %12s %9s %s" % (k[:46], v, mn, mx, age, c))
    if len(rows) > 12:
        print("... 共 %d 行" % len(rows))

    # ── 勾选画波形: 真能出曲线吗 ──
    want = [r[0] for r in rows if ("· v 速度" in r[0] or "v_cap" in r[0] or "a_max" in r[0])][:4]
    print("\n勾选画波形: %s" % want)
    for k in want:
        for b in w.store.bufs.values():
            if k.endswith(b.key) or b.key.endswith(k) or k == b.key:
                try:
                    w.wave.set_checked(b.key, True)
                except Exception:                                   # noqa: BLE001
                    pass
    for _ in range(40):
        app.processEvents()
        time.sleep(0.05)
    n_pts = {b.key: int(b.n) for b in w.store.bufs.values() if b.n}
    _sk_pts = {k: v for k, v in n_pts.items() if "SK0" in k}
    print("有数据的曲线数 = %d (其中原子技能 %d 条)" % (len(n_pts), len(_sk_pts)))
    for k in list(_sk_pts.items())[:6]:
        print("    曲线 %-46s 点数 %d" % (k[0][:46], k[1]))

    try:
        w.stop()
    except Exception:                                               # noqa: BLE001
        pass
    if a.shot:
        os.makedirs(os.path.dirname(os.path.abspath(a.shot)), exist_ok=True)
        app.processEvents()
        w.grab().save(a.shot)
        print("\n出图: %s" % os.path.abspath(a.shot))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
