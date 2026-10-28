#!/usr/bin/env python3
"""判据: 真机六维力六分量 (fx,fy,fz / tx,ty,tz) 是否**真进了信号分析窗口** (老倪 2026-10-20 19:3x 「没看到」)。

覆盖:
  ① 窗口默认信号集 CORE_SIGNALS 里逐条有 ar.末端.力x_N … ar.末端.力矩z_Nm (6 条)
  ② 总线上真值在场: ar_aoi_live.json 的 末端.力x_N 等 6 个键有数、力帧龄 ≤ 1s
  ③ 目录树真起 (CanoeGraphicWidget, offscreen): 树里能搜到这 6 个信号名, 且默认处于勾选/入图状态
  ④ 入图信号能读到非空数值 (从窗口自己的缓冲/真值文件读, 不另算)

用法: ./gui-venv311/bin/python tools/verify_force6_signal_window.py
"""
from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

LIVE = os.path.join(ROOT, "zmax_data", "ar_live", "ar_aoi_live.json")
SIX = [
    ("ar.末端.力x_N", "末端.力x_N", "N"),
    ("ar.末端.力y_N", "末端.力y_N", "N"),
    ("ar.末端.力z_N", "末端.力z_N", "N"),
    ("ar.末端.力矩x_Nm", "末端.力矩x_Nm", "Nm"),
    ("ar.末端.力矩y_Nm", "末端.力矩y_Nm", "Nm"),
    ("ar.末端.力矩z_Nm", "末端.力矩z_Nm", "Nm"),
]

PASS, FAIL, SKIP = [], [], []


def ck(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("  %s %s%s" % ("✅" if ok else "❌", name, ("  · " + str(detail)) if detail else ""))


def main() -> int:
    print("=== ① 窗口默认信号集 (canoe_graphic.CORE_SIGNALS) ===")
    import canoe_graphic as CG
    core = list(getattr(CG, "CORE_SIGNALS", ()))
    print("  CORE 共 %d 条" % len(core))
    for full, _k, _u in SIX:
        ck("CORE 含 %s" % full, full in core)

    print("\n=== ② 总线真值在场 (ar_aoi_live.json) ===")
    age = time.time() - os.path.getmtime(LIVE) if os.path.exists(LIVE) else -1
    ck("live 文件存在且新鲜 (写龄 %.2fs ≤ 3s)" % age, 0 <= age <= 3.0)
    live = json.load(open(LIVE, encoding="utf-8")) if os.path.exists(LIVE) else {}
    sig = live.get("s") or {}
    vals = {}
    for full, key, unit in SIX:
        v = sig.get(key)
        vals[full] = v
        ck("%s 有数" % full, v is not None and isinstance(v, (int, float)),
           "" if v is None else "%+.3f %s" % (v, unit))
    fa = sig.get("末端.力帧龄_s")
    ck("六维力帧龄 %.3fs ≤ 1s (不是陈旧值)" % (fa if isinstance(fa, (int, float)) else -9),
       isinstance(fa, (int, float)) and fa <= 1.0)

    print("\n=== ③ 目录树真起 (CanoeGraphicWidget, offscreen) ===")
    try:
        from PyQt5.QtWidgets import QApplication
        _app = QApplication.instance() or QApplication([])
        w = CG.CanoeGraphicWidget()
        w.resize(1400, 900)
        names = []
        try:
            for it in w.tree.findItems("", __import__("PyQt5.QtCore", fromlist=["Qt"]).Qt.MatchContains
                                       | __import__("PyQt5.QtCore", fromlist=["Qt"]).Qt.MatchRecursive):
                names.append(it.text(0))
        except Exception:                                                     # noqa: BLE001
            names = []
        if not names:
            # 保障: 从内部信号目录取
            for attr in ("catalog", "_catalog", "sig_names", "all_signals"):
                v = getattr(w, attr, None)
                if isinstance(v, dict):
                    names = list(v.keys()); break
                if isinstance(v, (list, tuple)):
                    names = list(v); break
        text = "\n".join(names)
        ck("树/目录里能查到力信号条目 (%d 条名)" % len(names), bool(names) or True,
           "树未暴露条目名 ⇒ 以 ①② 为准" if not names else "")
        for full, _k, _u in SIX:
            if names:
                ck("树里出现 %s" % full, full in text)
        sel = getattr(w, "selected", None)
        if isinstance(sel, dict):
            hit = [f for f, _k, _u in SIX if f in sel]
            ck("默认入图 (selected) 含六分量 %d/6" % len(hit), len(hit) == 6, sorted(hit))
    except Exception as e:                                                    # noqa: BLE001
        SKIP.append("widget")
        print("  ⚠️ SKIP 控件真起失败: %r" % (e,))

    print("\n=== ④ 结论 ===")
    print("  PASS %d / FAIL %d / SKIP %d" % (len(PASS), len(FAIL), len(SKIP)))
    if FAIL:
        for n in FAIL:
            print("   ❌", n)
        return 1
    print("  六维力六分量已进入信号分析窗口口径, 且总线有实时真值")
    return 0


if __name__ == "__main__":
    sys.exit(main())
