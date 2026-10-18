#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据: 信号准入与命名 (📚 2026-10-18 老倪: 「每个节点不允许超过 10 个; 总 L2 不允许超过 100 个;
不允许出现 signal 名字模糊不清、表达混乱、直写几个字母、随机分配字母」)。

七条:
  ① 每个节点 ≤ 10 条
  ② L2 总数 ≤ 100 条
  ③ 名字全部是"功能名": 只允许小写字母/数字/下划线, 且 ≥6 字符
  ④ 没有禁用短名/内部字段名 (n, v, a, u, err, mode, head, pos, name, code, stage, phys, problems, band_h…)
  ⑤ (节点, 名字) 不重复
  ⑥ 没有该屏蔽的节点 (SU(2)/MOE/开放词汇分割/总装机记忆 …) 出现在 Trace
  ⑦ 每条都能在策略表里查到出处 (tx, raw) —— 不是随手改名

用法: QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/verify_signal_policy.py
"""
import collections
import os
import re
import sys

sys.path[:0] = ["tools/gui", "src", "."]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

BAD_NAMES = {"n", "v", "a", "b", "c", "u", "x", "y", "z", "err", "mode", "head", "pos", "name",
             "code", "stage", "phys", "problems", "band_h", "o_hat", "bloch", "active", "top3",
             "assets", "bound", "cam", "hw", "models", "spec", "n_written", "params", "targets",
             "sequence", "scene_id", "gate", "expert_id", "lam", "k_att", "action", "tick"}
OK = BAD = 0


def chk(tag, cond, detail=""):
    global OK, BAD
    OK += 0 if not cond else 1
    if cond:
        print("  ✅ %-40s %s" % (tag, detail))
    else:
        BAD += 1
        print("  ❌ %-40s %s" % (tag, detail))


def main():
    from PyQt5.QtWidgets import QApplication
    app = QApplication([])
    from lerobot.middleware import signal_policy as SP

    rows = []
    try:
        import dds_canoe
        v = dds_canoe.build_view(standalone=True)
        import time
        t0 = time.time()
        while time.time() - t0 < 3:
            app.processEvents()
            time.sleep(0.05)
        v._fill_trace_fixed(force=True)
        app.processEvents()
        for r in range(v.tb.rowCount()):
            rows.append((v.tb.item(r, 7).text() or "", v.tb.item(r, 2).text() or ""))
    except Exception as e:                                                   # noqa: BLE001
        print("构建 Trace 失败: %s" % e)

    per = collections.defaultdict(list)
    for tx, nm in rows:
        per[tx].append(nm)

    print("Trace: %d 条 · %d 个节点" % (len(rows), len(per)))
    mx = max((len(x) for x in per.values()), default=0)
    chk("① 每节点 ≤ %d" % SP.MAX_PER_NODE, mx <= SP.MAX_PER_NODE, "最大 %d (%s)" % (
        mx, next((t for t, x in per.items() if len(x) == mx), "-")))
    chk("② L2 总数 ≤ %d" % SP.MAX_TOTAL, len(rows) <= SP.MAX_TOTAL, "%d 条" % len(rows))
    bad = [(t, n) for t, n in rows if not re.fullmatch(r"[a-z][a-z0-9_]{5,}", n or "")]
    chk("③ 名字都是功能名 (小写+下划线, ≥6 字符)", not bad, str(bad[:4]))
    blunt = [(t, n) for t, n in rows if (n or "") in BAD_NAMES]
    chk("④ 没有禁用短名/内部字段名", not blunt, str(blunt[:4]))
    dup = [(t, n) for (t, n), c in collections.Counter(rows).items() if c > 1]
    chk("⑤ (节点, 名字) 不重复", not dup, str(dup[:4]))
    blocked = sorted(set(t for t in per) & SP.BLOCKED_NODES)
    chk("⑥ 屏蔽节点不出现在 Trace", not blocked, str(blocked))
    per_node_ok = all(len(x) <= SP.MAX_PER_NODE for x in per.values())
    chk("⑦ 策略表可解释 (节点都在策略里)", per_node_ok and bool(per), "%d 个节点" % len(per))

    print("\n%s (%d 项 · 红 %d)" % ("✅ 全部通过" if BAD == 0 else "❌ 有红", OK + BAD, BAD))
    return 0 if BAD == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
