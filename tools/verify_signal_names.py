#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据: 信号名不许是裸端口名 (out1 / in1)。

📚 2026-10-18 老倪: 「你看信号 out1 in1，根本看不出来是什么意思。全局搜索，signal 要能表达出
   这个信号的基本含义，简单明了。全局修改信号的英文字符串」
—— 所以这里做三条硬约束:
   ① 全部 272 个端口的信号名都不许剩裸 in1/out1
   ② Trace 表 (L2) 的 Signal 列 0 条裸端口名
   ③ 打印端口 → 语义名对照, 人能一眼看懂 (plan / plan_in / action_in …)

用法: QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/verify_signal_names.py
"""
import os
import re
import sys
import time

sys.path[:0] = ["tools/gui", "src", "."]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

BARE = re.compile(r"^(in|out)\d+$")
ok_n = 0
bad_n = 0


def chk(tag, cond, detail=""):
    global ok_n, bad_n
    if cond:
        ok_n += 1
        print("  ✅ %-34s %s" % (tag, detail))
    else:
        bad_n += 1
        print("  ❌ %-34s %s" % (tag, detail))
    return cond


def main():
    from PyQt5.QtWidgets import QApplication
    app = QApplication([])
    from lerobot.middleware import attribution as A, db, signal_en as S

    print("① 全端口 (mw_topic · 272 个) 信号名")
    rows = db.topics()
    bare = []
    sample = {}
    for r in rows:
        tp, port, ty = r.get("topic"), r.get("port"), r.get("type")
        if not BARE.match(str(port)):
            continue
        nm = S.en_of_key("", port, ty) or port
        sample[str(port) + "@" + str(ty)] = nm
        if BARE.match(str(nm)):
            bare.append((tp, port, ty))
    chk("裸端口名剩余", len(bare) == 0, "端口 %d 个 · 仍裸 %d %s" % (len(rows), len(bare), bare[:3]))
    pretty = sorted({(k.split("@")[1], v) for k, v in sample.items()})
    print("     端口语义名样例: " + " · ".join("%s→%s" % (t, n) for t, n in pretty[:10]))

    print("② Trace 表 (L2) Signal 列")
    import dds_canoe
    v = dds_canoe.build_view(standalone=True)
    t0 = time.time()
    while time.time() - t0 < 3:
        app.processEvents()
        time.sleep(0.05)
    v._fill_trace_fixed(force=True)
    app.processEvents()
    sig = [v.tb.item(r, 2).text() for r in range(v.tb.rowCount())]
    b2 = [s for s in sig if BARE.match(str(s))]
    chk("Trace 裸端口名", len(b2) == 0, "行 %d · 裸 %d %s" % (len(sig), len(b2), b2[:4]))
    chk("Trace 行数", len(sig) > 300, "%d 行" % len(sig))

    print("③ n_moveit 两条口 (老倪点名的 out1 / in1)")
    for key in ("out1", "in1", "in2"):
        ty = A.type_of_topic("ss.node.n_moveit." + key)
        nm = S.en_of_key("", key, ty)
        chk("n_moveit.%s" % key, bool(nm) and not BARE.match(str(nm)), "%s → %s" % (ty or "(无类型)", nm))

    print("\n%s (%d 项 · 红 %d)" % ("✅ 全部通过" if bad_n == 0 else "❌ 有红", ok_n + bad_n, bad_n))
    return 0 if bad_n == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
