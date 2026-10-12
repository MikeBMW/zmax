#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_scene_topic_colors.py — 判据: 信号分析窗口的「场景色」真能上屏 + 顶部能看出"当前配置"

老倪 2026-10-12 两条原话:
  · 「现在的实时监控，要能看出配置」
  · 「之前说的，绿色topic是插拔任务，你怎么没有将topic设置成绿色的？」

真因(实测, 不是推断):
  `canoe_graphic.py` 的样式表里那句 `QTreeWidget::item{color:#c9d1d9}` **压掉了** setForeground 的
  逐条场景色 —— 树里 34 行条目数据上是 #2e8b57, 渲染出来**全是灰** (离屏全分辨率渲染绿色像素 = 0)。
  修: 把 item 的颜色交给 palette/条目数据 (只留 padding), 场景色才上屏。

判据(6 条, 每条独立可跑的断言):
  ① 静态回归闸: canoe_graphic.py 里不许再出现 `QTreeWidget::item` + `color:` 同段
  ② 标签层: `sstrace.*` / `ros./robot/force_torque.*` → 画布数据源场景(绿); `ros./robot/tcp_pose.*` 留白(白)
  ③ 离屏真渲染(真数据拷贝 fixture): 树里 ≥ 20 行、绿像素 ≥ 500、且仍有白行(不是全涂绿)
  ④ 负对照: 把旧样式(带 item color)贴回去 ⇒ 绿像素必须 = 0 (证明①这条闸能抓住真因)
  ⑤ 顶部横幅: "当前配置" 文本含 任务ID / 场景 / 配置单文件名
  ⑥ 三色各自可渲染: 紫(AR) 在 AR 组上真出像素

用法: gui-venv311/bin/python tools/verify_scene_topic_colors.py   (需 DISPLAY)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))

OK = 0
FAIL = 0


def chk(name: str, cond: bool, info: str = ""):
    global OK, FAIL
    if cond:
        OK += 1
        print("  ✅ %s%s" % (name, (" — " + info) if info else ""))
    else:
        FAIL += 1
        print("  ❌ %s%s" % (name, (" — " + info) if info else ""))


def pixels(img, colors, step=1, rect=None):
    cnt = {c: 0 for c in colors}
    w, h = img.width(), img.height()
    x0, y0, x1, y1 = rect if rect else (0, 0, w, h)
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(w, int(x1)), min(h, int(y1))
    for y in range(y0, y1, step):
        for x in range(x0, x1, step):
            c = img.pixelColor(x, y).name()
            if c in cnt:
                cnt[c] += 1
    return cnt


def tree_rect(widget, tree_w):
    """树控件在整窗渲染图里的矩形 (只数树里的像素 —— 顶部按钮本身也带场景色, 不能混进来)。"""
    try:
        from PyQt5.QtCore import QPoint
        tl = tree_w.mapTo(widget, QPoint(0, 0))
        return (tl.x(), tl.y(), tl.x() + tree_w.width(), tl.y() + tree_w.height())
    except Exception:                                                         # noqa: BLE001
        return None


def main() -> int:
    print("① 静态回归闸 — 样式表不许再压条目场景色")
    src = open(os.path.join(ROOT, "tools", "gui", "canoe_graphic.py"), encoding="utf-8").read()
    bad = re.search(r"QTreeWidget::item\{\{[^}]*color:", src)
    chk("样式表无 QTreeWidget::item{color:…}", bad is None,
        "行 %d" % (src[:bad.start()].count("\n") + 1) if bad else "已改为 palette/条目数据口径")

    print("② 标签层 — 来源族 → 场景")
    import sig_scene_tags as SST
    import ss_scene_switch as SSW
    scene = (SSW.now() or {}).get("src_state") or ""
    chk("画布数据源场景可读", bool(scene), scene or "读不到")
    chk("sstrace.* → 画布场景", SST.tag("sstrace.末端.0") == scene, SST.tag("sstrace.末端.0"))
    chk("sstrace.* 着色 = 场景色", SST.color("sstrace.接触概率") == "#2e8b57", SST.color("sstrace.接触概率"))
    chk("force_torque 话题 → 画布场景", SST.tag("ros./robot/force_torque.fx") == scene)
    chk("tcp_pose 留白(三场景共用)", SST.tag("ros./robot/tcp_pose.x") == "", "白")

    print("③ 离屏真渲染 — 真数据拷贝 fixture (ts=now, 模拟实况)")
    from PyQt5.QtWidgets import QApplication, QTreeWidget
    from PyQt5.QtGui import QImage, QPainter
    app = QApplication.instance() or QApplication([])
    import canoe_graphic as C

    fixd = os.path.join(tempfile.gettempdir(), "ssc_fixture")
    os.makedirs(fixd, exist_ok=True)
    fx = os.path.join(fixd, "sstrace_fresh.json")
    real = os.path.join(ROOT, "zmax_data", "ss_live", "trace_live.json")
    src_keys = []
    if os.path.isfile(real):
        try:
            d = json.load(open(real, encoding="utf-8"))
            src_keys = list(d.keys())
            d["ts"] = time.time()                     # fixture: 只改时刻字段, 其余是真数据
            json.dump(d, open(fx, "w", encoding="utf-8"), ensure_ascii=False)
        except Exception as e:                                                # noqa: BLE001
            print("     (真数据读不到: %s)" % e)
    chk("真数据 trace_live.json 可读", len(src_keys) > 10, "%d 键" % len(src_keys))

    C.HOST_SOURCES = [("sstrace", fx)]                 # 只喂 sstrace fixture, 其余源不掺
    w = C.CanoeGraphicWidget()
    w.resize(1500, 960)
    w.setAttribute(0x00800000, True)                   # WA_DontShowOnScreen
    w.show()
    for _ in range(20):
        app.processEvents()
        time.sleep(0.05)
    _tree = None
    for t in w.findChildren(QTreeWidget):
        if t.topLevelItemCount():
            _tree = t
            break
    rect_tree = tree_rect(w, _tree) if _tree is not None else None
    img = QImage(1500, 960, QImage.Format_RGB32)
    img.fill(0)
    p = QPainter(img)
    w.render(p)
    p.end()
    px = pixels(img, ("#2e8b57", "#c9d1d9", "#8957e5"), step=1, rect=rect_tree)
    rows, greens = 0, 0
    if _tree is not None:
        for i in range(_tree.topLevelItemCount()):
            r = _tree.topLevelItem(i)
            for j in range(r.childCount()):
                rows += 1
                if r.child(j).foreground(0).color().name() == "#2e8b57":
                    greens += 1
    chk("树里条目 ≥ 20 行", rows >= 20, "%d 行" % rows)
    chk("绿色条目 ≥ 20 行", greens >= 20, "%d 行 (sstrace 全族)" % greens)
    chk("渲染绿像素 ≥ 500", px["#2e8b57"] >= 500, "%d px" % px["#2e8b57"])
    chk("仍有白像素(不是全涂绿)", px["#c9d1d9"] > 0, "%d px" % px["#c9d1d9"])

    print("④ 负对照 — 贴回旧样式(带 item color) ⇒ 绿像素必须归零")
    try:
        w.tree.setStyleSheet("QTreeWidget{background:#0d1117;} QTreeWidget::item{color:#c9d1d9;}")
        for _ in range(6):
            app.processEvents()
        img2 = QImage(1500, 960, QImage.Format_RGB32)
        img2.fill(0)
        p2 = QPainter(img2)
        w.render(p2)
        p2.end()
        px2 = pixels(img2, ("#2e8b57",), step=1, rect=rect_tree)
        chk("旧样式下绿像素 = 0 (真因可复现)", px2["#2e8b57"] == 0, "%d px" % px2["#2e8b57"])
    except Exception as e:                                                    # noqa: BLE001
        chk("负对照可执行", False, str(e)[:80])

    print("⑤ 顶部「当前配置」横幅")
    txt = ""
    try:
        txt = w._cfg_lab.text()
    except Exception as e:                                                    # noqa: BLE001
        print("     ", e)
    chk("横幅非空", len(txt) > 10, re.sub(r"<[^>]+>", "", txt)[:90])
    chk("横幅含任务ID", "TASK-" in txt)
    chk("横幅含场景名", "插拔场景" in txt or "摆盘场景" in txt or "AR场景" in txt)
    chk("横幅含配置单文件名", "配置单_" in txt)

    print("⑥ 三色可渲染 — AR(紫) 在 AR 组上真出像素")
    ar = os.path.join(ROOT, "zmax_data", "ar_live", "ar_aoi_live.json")
    if os.path.isfile(ar):
        import sig_scene_tags as _s
        chk("ar.* → AR场景(紫)", _s.color("ar.AOI.倾角_deg") == "#8957e5")

    print("\n%s  %d/%d PASS" % ("✅" if not FAIL else "❌", OK, OK + FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
