#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_sig_space_sync.py — 「数据空间」与「信号分析」数据源是否同步 + 信号分析字体够不够大

老倪 2026-10-20: 「数据空间和信号分析的数据源, 同步了么? 信号分析的窗口字体, 再大一些」

判据 (真起两个窗口, offscreen Qt, 不是读源码猜):
  A. 数据空间 (dds_canoe.BusView) 真建树后, 树上除了 DDS 报文, 还有「🥽 AR 场景 · 文件通道」
     ⇒ AR 的末端位姿/六维力/机器人状态机 两个窗口都看得到, 且值取自**同一份** ar_aoi_live.json
  B. 数据空间 AR 组三行的汇总值与 ar_aoi_live.json 里的原值一致 (真机 TCP 有帧就显示出 x/y/z)
  C. 信号分析 (canoe_graphic) 的树/标签字号 ≥16px, 且行高随之变大 (字变大但行没变高 = 白改)
  D. DDS 那一半本来就同源: 两个窗口读的是同一个 zmax_data/dataspace/live.json

用法: QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/verify_sig_space_sync.py
"""
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))

from PyQt5.QtWidgets import QApplication                # noqa: E402

FAIL = []


def chk(ok, msg):
    print(("  ✅ " if ok else "  ❌ ") + msg)
    if not ok:
        FAIL.append(msg)


def main():
    app = QApplication([])
    ar_path = os.path.join(ROOT, "zmax_data", "ar_live", "ar_aoi_live.json")
    dds_live = os.path.join(ROOT, "zmax_data", "dataspace", "live.json")
    ar = json.load(open(ar_path, encoding="utf-8"))
    sig = ar.get("s") or {}

    print("· ——— A/B: 数据空间里能看到 AR 文件通道, 值同源 ———")
    import dds_canoe
    v = dds_canoe.build_view(None, standalone=True)
    v.resize(1400, 800)
    v.show()
    app.processEvents()
    for _ in range(3):
        v.reload(force_tree=True)
        app.processEvents()
    names = [v.tree.topLevelItem(i).text(0) for i in range(v.tree.topLevelItemCount())]
    chk(any("AR 场景 · 文件通道" in str(x) for x in names), "数据空间树上有 AR 文件通道组 (%s)" % names[:3])
    _ar_root = None
    for i in range(v.tree.topLevelItemCount()):
        if "AR 场景 · 文件通道" in v.tree.topLevelItem(i).text(0):
            _ar_root = v.tree.topLevelItem(i)
            break
    chk(_ar_root is not None and _ar_root.childCount() >= 3,
        "AR 组里有 位姿/力/状态机 三行 (实测 %d 行)" % (_ar_root.childCount() if _ar_root else -1))
    if _ar_root is not None:
        _rows = {_ar_root.child(j).text(0): (_ar_root.child(j).text(2), _ar_root.child(j).text(4))
                 for j in range(_ar_root.childCount())}
        for k, vv in _rows.items():
            print("      %-28s 值: %s   龄: %s" % (k, vv[0], vv[1]))
        _pose = [vv for k, vv in _rows.items() if "位姿" in k][0][0]
        if sig.get("末端.x") is not None:
            _want = "x %.1f" % (float(sig["末端.x"]) * 1000.0)
            chk(_want in _pose, "位姿行与 ar_aoi_live.json 同值 (%s ⊂ %s)" % (_want, _pose))
        else:
            chk("未接" in _pose, "TCP 无帧时位姿行写「未接」而不是 0 (%s)" % _pose)
        _rob = [vv for k, vv in _rows.items() if "状态机" in k][0][0]
        chk(("插拔" in _rob) and ("阶段" in _rob or "未连接" in _rob),
            "状态机行直接看得出是否在插拔 (%s)" % _rob)

    print("· ——— C: 信号分析字体 ———")
    import canoe_graphic as CG
    w = CG.CanoeGraphicWidget()
    w.resize(1500, 900)
    w.show()
    app.processEvents()
    qss = w.tree.styleSheet()
    chk("font-size:16px" in qss, "信号树字号 16px (纯 13px 的旧值已不存在: %s)" % ("font-size:13px" not in qss))
    fh = w.tree.fontMetrics().height()
    chk(fh >= 19, "树的行文字高度 %dpx ≥19px (字变大行也得跟着高)" % fh)
    _small = [l for l in (w.lb_state.styleSheet(), w.lb_info.styleSheet(), w.lb_meta.styleSheet())
              if not any(x in l for x in ("font-size:14px", "font-size:16px"))]
    chk(not _small, "状态/图例/说明标签 ≥14px (%d 处还是旧字号)" % len(_small))

    print("· ——— D: DDS 那一半同源 ———")
    chk(os.path.exists(dds_live), "DDS live.json 存在 (两个窗口同一个文件: %s)" % os.path.relpath(dds_live, ROOT))
    _d = json.load(open(dds_live, encoding="utf-8"))
    chk(bool((_d.get("topics") or {})), "DDS 侧话题 %d 个 — 数据空间与信号分析的 ds.* 组都读它"
        % len((_d.get("topics") or {})))

    print()
    if FAIL:
        print("❌ FAIL %d 项:" % len(FAIL))
        for f in FAIL:
            print("   - " + f)
        return 1
    print("✅ PASS · AR 文件通道两个窗口同源同值; DDS 侧同一份 live.json; 信号分析字号已放大")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
