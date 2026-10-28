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
    # 🎨 场景色**随数据源唯一依据取**, 不预先固定 (老倪 10-13: 画布数据源切到摆盘后, sstrace 全族应转蓝)
    #   预先固定 #2e8b57 会让"摆盘在跑"这件事被判成红 —— 判据必须跟唯一依据, 不跟历史某一刻。
    _scol = (SSW.now() or {}).get("color") or SST.color("sstrace.接触概率") or "#1f6feb"
    chk("画布数据源场景可读", bool(scene), scene or "读不到")
    chk("sstrace.* → 画布场景", SST.tag("sstrace.末端.0") == scene, SST.tag("sstrace.末端.0"))
    chk("摆盘末端 x y z 具名注册 (老倪 10-13「末端执行器 x y z 必须有」)",
        all(SST.tag("sstrace.末端_%s" % _a) == "摆盘场景" for _a in "xyz")
        and all(SST.tag("sstrace.光模块_%s" % _a) == "摆盘场景" for _a in "xyz"),
        "末端_x/_y/_z → 摆盘场景")
    chk("sstrace.* 着色 = 数据源场景色", SST.color("sstrace.接触概率") == _scol,
        "%s (期望 %s)" % (SST.color("sstrace.接触概率"), _scol))
    chk("force_torque → 插拔(力控专属, 摆盘是真空吸盘)", SST.tag("ros./robot/force_torque.fx") == "插拔场景",
        SST.tag("ros./robot/force_torque.fx") or "空")
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
    for _ in range(30):                # 等本机源线程真推一帧进 store (1s 太短会假红: 组在但行没到)
        app.processEvents()
        time.sleep(0.1)
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
    px = pixels(img, (_scol, "#c9d1d9", "#8957e5"), step=1, rect=rect_tree)
    rows, greens = 0, 0
    if _tree is not None:
        for i in range(_tree.topLevelItemCount()):
            r = _tree.topLevelItem(i)
            for j in range(r.childCount()):
                rows += 1
                if r.child(j).foreground(0).color().name() == _scol:
                    greens += 1
    chk("树里条目 ≥ 20 行", rows >= 20, "%d 行" % rows)
    chk("数据源场景色条目 ≥ 20 行", greens >= 20, "%d 行 (色 %s)" % (greens, _scol))
    chk("渲染场景色像素 ≥ 500", px[_scol] >= 500, "%d px" % px[_scol])
    chk("仍有白像素(不是全涂一色)", px["#c9d1d9"] > 0, "%d px" % px["#c9d1d9"])

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
        px2 = pixels(img2, (_scol,), step=1, rect=rect_tree)
        chk("旧样式下场景色像素 = 0 (真因可复现)", px2[_scol] == 0, "%d px" % px2[_scol])
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

    print("⑦ 四场景组 + 组名/组色 (老倪 10-12: 绿色组叫插拔场景 · 摆盘蓝 · AR 紫 · 其余基础场景白)")
    gnames, gcols = [], {}
    if _tree is not None:
        for i in range(_tree.topLevelItemCount()):
            r = _tree.topLevelItem(i)
            gnames.append(r.text(0))
            gcols[r.text(0)] = r.foreground(0).color().name()
    def _gcol(want):
        for nm, c in gcols.items():
            if want in nm:
                return c
        return "缺"
    chk("四组齐全(插拔/摆盘/AR/基础)", all(any(k in n for n in gnames) for k in ("插拔场景", "摆盘场景", "AR 场景", "基础场景")),
        " / ".join(n[:14] for n in gnames))
    chk("插拔组标题不再叫 3D 场景实时数据", not any("3D 场景实时数据" in n for n in gnames))
    chk("插拔组=绿 #2e8b57", _gcol("插拔场景") == "#2e8b57", _gcol("插拔场景"))
    chk("摆盘组=蓝 #1f6feb", _gcol("摆盘场景") == "#1f6feb", _gcol("摆盘场景"))
    chk("AR组=紫 #8957e5", _gcol("AR 场景") == "#8957e5", _gcol("AR 场景"))
    chk("基础组=白 #ffffff", _gcol("基础场景") == "#ffffff", _gcol("基础场景"))

    print("⑧ 折叠/展开状态可保持 (老倪: 三角点了没反应)")
    _r0 = _tree.topLevelItem(0) if _tree is not None else None
    if _r0 is not None:
        _r0.setExpanded(False)
        w._fill_tree()
        for _ in range(4):
            app.processEvents()
        chk("折叠插拔组后重建仍折叠", _tree.topLevelItem(0).isExpanded() is False)

    print("⑨ 摆盘末端执行器 x y z 真出行 (老倪 10-13: 「摆盘的机器人, 末端执行器的 x y z, 必须有」)")
    try:
        # 注入 3D 面板改后要发的**具名标量** (末端_x/_y/_z), 断言面板树上真出现这三行、且是摆盘蓝。
        # 这条判据盯的就是"只发列表键 ⇒ 渲染成未注册的 末端.0/.1/.2 ⇒ 那几行永远空"的老毛病。
        d2 = json.load(open(real, encoding="utf-8"))
        for _a, _v in zip("xyz", (0.1234, 0.5678, 0.9101)):
            d2["末端_%s" % _a] = _v
            d2["光模块_%s" % _a] = _v
        d2["scene"] = "SS-TRAY-PLACE"
        d2["ts"] = time.time()
        fx2 = os.path.join(fixd, "sstrace_tray_xyz.json")
        json.dump(d2, open(fx2, "w", encoding="utf-8"), ensure_ascii=False)
        C.HOST_SOURCES = [("sstrace", fx2)]
        w2 = C.CanoeGraphicWidget()
        w2.resize(1500, 960)
        w2.setAttribute(0x00800000, True)
        w2.show()
        for _ in range(30):
            app.processEvents()
            time.sleep(0.1)
        hits = []
        for t in w2.findChildren(QTreeWidget):
            for i in range(t.topLevelItemCount()):
                r = t.topLevelItem(i)
                for j in range(r.childCount()):
                    nm = r.child(j).text(0)
                    if "末端_" in nm or "光模块_" in nm:
                        _clean = re.sub(r"^[●○\s]+", "", re.sub(r"^[a-z]+\.", "", nm)).strip()
                        hits.append((_clean[:14], r.child(j).foreground(0).color().name()))
        got = {n for n, _c in hits}
        chk("面板树真出 末端_x/_y/_z 三行", {"末端_x", "末端_y", "末端_z"} <= got,
            " | ".join(sorted(got)[:6]) or "0 行")
        chk("这三行是摆盘蓝 #1f6feb", bool(hits) and all(c == "#1f6feb" for _n, c in hits),
            " ".join("%s=%s" % (n, c) for n, c in hits[:4]))
    except Exception as e:                                                    # noqa: BLE001
        chk("摆盘末端 x y z 真出行可跑", False, str(e)[:80])

    print("\n%s  %d/%d PASS" % ("✅" if not FAIL else "❌", OK, OK + FAIL))
    sys.stdout.flush()
    os._exit(1 if FAIL else 0)      # Qt 退出期线程偶发崩溃(segfault) ⇒ 判据结论以打印为准, 直接硬退


if __name__ == "__main__":
    raise SystemExit(main())
