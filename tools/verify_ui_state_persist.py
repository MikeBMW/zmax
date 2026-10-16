#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/verify_ui_state_persist.py — 侧栏「视图选择」开机回选 判据 (只读真源; 只写自己的界面态键)

老倪 2026-10-16: 「画布右侧栏, 主参数的太阳系, 不是你关机前的状态。找回来恢复」
根因: `cmb_viz_view` 的选择只在内存 ⇒ 控制台重启回到第 0 项 (🧊 四面板), 太阳系"不见"。
修法: 落盘 QSettings("ZMAX","studio") `mparam/viz_view`; 开机按存值回选;
      **只有人点下拉 / 命令通道 `echo orbital` 才写盘**, 程序化切换 (含判据脚本) 一律不写。

跑法: QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/verify_ui_state_persist.py
判据全部读真源/真构造, 不编数; 跑完把界面态键还原成跑之前的原值。
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tools/gui"))

from PyQt5.QtWidgets import QApplication                                     # noqa: E402

import model_tree as MT                                                      # noqa: E402

ROWS = []


def chk(tag, title, got, ok, expect):
    ROWS.append({"tag": tag, "title": title, "got": got, "ok": bool(ok), "expect": expect})
    print("%s %-4s %s" % ("✅" if ok else "❌", tag, title))
    print("        got=%s  expect=%s" % (got, expect))


def conf_path():
    from PyQt5.QtCore import QSettings
    return QSettings(MT.UI_CFG_ORG, MT.UI_CFG_APP).fileName()


def raw_conf():
    p = conf_path()
    try:
        with open(p, encoding="utf-8") as f:
            return f.read()
    except Exception as _e:                                                  # noqa: BLE001
        return "<读不到 %s: %r>" % (p, _e)


def main():
    app = QApplication(sys.argv)
    orig = MT.ui_state_get(MT.MPARAM_VIZ_KEY, 0)

    # ── S1 落盘: 写后**立刻**在盘上看得见 (不等进程退出) ──
    MT.ui_state_put(MT.MPARAM_VIZ_KEY, 1)
    txt = raw_conf()
    chk("S1", "写后立刻落盘 (QSettings sync ⇒ 盘上就有这行; 关机急断电也不丢)",
        {"文件": conf_path(), "含键行": [l for l in txt.splitlines() if "viz_view" in l]},
        "viz_view=1" in txt.replace(" ", ""), "落盘文件里出现 mparam/viz_view=1")

    # ── S2 开机回选: 存 1 ⇒ 新构造的 M 页直接停在「🪐 球心引力架构」 ──
    class _M:
        nodes = []
        def __init__(self):
            self._root = ROOT
    page = MT.MasterParamMView(_M())
    app.processEvents()
    chk("S2", "开机回选: 存值=1 ⇒ 新构造的 M 页下拉与 stack 都在「🪐 太阳系」",
        {"下拉": page.cmb_viz_view.currentIndex(), "下拉文字": page.cmb_viz_view.currentText(),
         "stack": page.viz_stack.currentIndex()},
        page.cmb_viz_view.currentIndex() == 1 and page.viz_stack.currentIndex() == 1,
        "下拉=1 且 stack=1 (不是回到第 0 项)")

    # ── S3 存 0 ⇒ 回选四面板 (不是只会回选 1) ──
    MT.ui_state_put(MT.MPARAM_VIZ_KEY, 0)
    page2 = MT.MasterParamMView(_M())
    app.processEvents()
    chk("S3", "存值=0 ⇒ 回选「🧊 几何四面板」(回选按真值走, 不是写死 1)",
        {"下拉": page2.cmb_viz_view.currentIndex(), "stack": page2.viz_stack.currentIndex()},
        page2.cmb_viz_view.currentIndex() == 0 and page2.viz_stack.currentIndex() == 0, "两处都是 0")

    # ── S4 程序化切换**不写盘** (否则跑一次判据就把老倪的偏好刷掉) ──
    MT.ui_state_put(MT.MPARAM_VIZ_KEY, 1)
    page2.cmb_viz_view.setCurrentIndex(0)          # 程序化 (判据/开机回选走的就是这条)
    app.processEvents()
    after = MT.ui_state_get(MT.MPARAM_VIZ_KEY, -1)
    chk("S4", "程序化 setCurrentIndex 不写盘 (判据脚本跑完不会把偏好刷成四面板)",
        {"切到": page2.viz_stack.currentIndex(), "盘上存值": after}, after == 1, "盘上仍是 1")

    # ── S5 **人点下拉**才写盘 ──
    try:
        page2.cmb_viz_view.activated[int].emit(0)   # 模拟用户在下拉里选第 0 项
        app.processEvents()
        got5 = MT.ui_state_get(MT.MPARAM_VIZ_KEY, -1)
        ok5 = (got5 == 0)
    except Exception as _e:                                                  # noqa: BLE001
        got5, ok5 = "异常: %r" % _e, False
    chk("S5", "人点下拉 (combo.activated) ⇒ 立刻写盘 (下一次开机就回到人点的那一个)",
        {"盘上存值": got5}, ok5, "等于人点的 0")

    # ── S6 命令通道 `echo orbital` 也落盘 ──
    with open(os.path.join(ROOT, "tools", "gui", "studio.py"), encoding="utf-8") as fh:
        st = fh.read()
    seg = st.split("def _goto_orbital_cmd(self):", 1)[-1][:900]
    chk("S6", "命令通道 orbital 落盘真接线 (切到 🪐 之后写 ui_state_put(MPARAM_VIZ_KEY, 1))",
        {"切视图": "cmb.setCurrentIndex(1)" in seg, "落盘": "ui_state_put(MPARAM_VIZ_KEY, 1)" in seg},
        ("cmb.setCurrentIndex(1)" in seg) and ("ui_state_put(MPARAM_VIZ_KEY, 1)" in seg), "两处都在")

    # ── S7 回选不劫持刷新链: 回选后仍能 refresh 拿到真值 (太阳 M 与标定真源同值) ──
    MT.ui_state_put(MT.MPARAM_VIZ_KEY, 1)
    page3 = MT.MasterParamMView(_M())
    app.processEvents()
    import json
    # 真源 = 视图自己读的那一个 (仓库根 config/calib/zmax_manifold.json ⇒ data/database/... 真源;
    # 注意别拿 defaults/config/... 的出厂默认 M 去比 —— 那是另一个文件, 2026-10-16 踩过)
    _mp = os.path.join(ROOT, "config", "calib", "zmax_manifold.json")
    with open(_mp, encoding="utf-8") as fh:
        mani = json.load(fh)
    sunM = getattr(getattr(page3, "orbital", None), "data", None)
    sunM = (sunM.body.get("sun", {}) or {}).get("M") if sunM is not None else None
    chk("S7", "回选到 🪐 之后真源照读 (太阳 M == 视图自己的真源 config/calib/zmax_manifold.json)",
        {"太阳 M": sunM, "真源 M": mani.get("M"), "真源文件": os.path.relpath(_mp, ROOT)},
        sunM == float(mani.get("M")), "同值")

    # ── 还原跑之前的界面态 (判据不许改老倪的偏好) ──
    MT.ui_state_put(MT.MPARAM_VIZ_KEY, orig)
    npass = sum(1 for r in ROWS if r["ok"])
    print("\n═══ 判据 %d 条: PASS %d · FAIL %d ═══" % (len(ROWS), npass, len(ROWS) - npass))
    print("（跑前原值 %s 已还原; 界面态文件 %s）" % (orig, conf_path()))
    out = os.path.join(ROOT, "zmax_data", "eval", "ui_state_persist_verify.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    import json
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"pass": npass, "fail": len(ROWS) - npass, "restored_orig": orig, "rows": ROWS},
                  fh, ensure_ascii=False, indent=1)
    print("📄 落盘: %s" % out)
    return 0 if npass == len(ROWS) else 1


if __name__ == "__main__":
    sys.exit(main())
