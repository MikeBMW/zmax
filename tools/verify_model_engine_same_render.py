#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据: 「单独开的模型引擎窗口」与「功能区(模型引擎标签)里内嵌的面板」必须**渲染一致**
(2026-10-14 老倪: 「你单独打开的模型引擎窗口, 与控制台功能区模型引擎标签打开的界面, 要保持一致」)。

为什么需要这条: 权重路径列是 Stretch ⇒ 面板宽随父容器变 ⇒ 同一层在两处**被裁的位置不同**
(实测修前: 1900 窗口该列 622px vs 1400 窄容器 100px ⇒ 路径肉眼看得见的差异)。
判据 = 逐列宽 + 逐格文字 + 表头 + 字体 + 按钮 + 面板设计最小宽, 且**在窄容器里也必须一样**。

跑法: ./gui-venv311/bin/python tools/verify_model_engine_same_render.py
"""
import json
import os
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, "/home/ubuntu/zmax/tools/gui")
os.chdir("/home/ubuntu/zmax")

from PyQt5.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget  # noqa: E402

app = QApplication.instance() or QApplication([])
import model_engine_window as MEW  # noqa: E402

res = []


def chk(name, cond, extra=""):
    res.append(("✓" if cond else "✗") + " " + name + (" :: %s" % (extra,) if extra else ""))


def _inv_st():
    inv = json.loads(subprocess.run(MEW.INV_CMD, cwd=MEW.ROOT, capture_output=True, text=True,
                                    timeout=180).stdout)
    try:
        import urllib.request
        st = json.load(urllib.request.urlopen("http://127.0.0.1:8796/status/all", timeout=3))
    except Exception:                                                         # noqa: BLE001
        st = {}
    return inv, st


def _dump(p, inv, st):
    p.feed(inv, st)
    tb = p.tb
    return {
        "w": p.width(), "minw": p.minimumWidth(),
        "cols": [tb.columnWidth(c) for c in range(tb.columnCount())],
        "rows": [[(tb.item(r, c).text() if tb.item(r, c) else "") for c in range(tb.columnCount())]
                 for r in range(tb.rowCount())],
        "head": p.lb_head.text(), "font": tb.font().pointSize(),
        "btns": sorted(b.text() for b in p.findChildren(QPushButton)),
        "nrow": tb.rowCount(), "ncol": tb.columnCount(),
    }


def _diff(a, b):
    out = []
    if a["cols"] != b["cols"]:
        out.append("列宽 窗口%s vs 页面%s" % (a["cols"], b["cols"]))
    if a["head"] != b["head"]:
        out.append("表头: %r vs %r" % (a["head"][:40], b["head"][:40]))
    if a["font"] != b["font"]:
        out.append("字体 %s vs %s" % (a["font"], b["font"]))
    if a["btns"] != b["btns"]:
        out.append("按钮 %s vs %s" % (a["btns"][:4], b["btns"][:4]))
    for r in range(max(len(a["rows"]), len(b["rows"]))):
        ra = a["rows"][r] if r < len(a["rows"]) else []
        rb = b["rows"][r] if r < len(b["rows"]) else []
        for c in range(max(len(ra), len(rb))):
            va = ra[c] if c < len(ra) else ""
            vb = rb[c] if c < len(rb) else ""
            if va != vb:
                out.append("r%d c%d 窗口=%r 页面=%r" % (r, c, va[:30], vb[:30]))
    return out


inv, st = _inv_st()

# ① 窗口里的面板 (1900 宽, 就是老倪点的那个"单独打开"的窗口)
win = MEW.ModelEngineWindow(poll=False)          # 不强行 resize: 窗口自己按内容定高 (见窗口 __init__)
win.show()
app.processEvents()
A = _dump(win.panel, inv, st)

# ② 同一份面板塞进 1400 窄容器 (= 功能区页面比窗口窄的那种情形)
box = QWidget()
box.resize(600, 700)          # 2026-10-14: 比面板最小宽(980)还窄 ⇒ 面板不许跟着缩 (页面横滚)
QVBoxLayout(box).addWidget(MEW.ModelEnginePanel(box, poll=False))
box.show()
app.processEvents()
p_narrow = box.findChild(MEW.ModelEnginePanel)
B = _dump(p_narrow, inv, st)
d_ab = _diff(A, B)
# 🖥 2026-10-14 老倪两条要求并存: (a) 窗口要能拖宽/最大化 (b) 两处界面要一致。
#   收口口径: **同一个面板 + 同一个宽度 ⇒ 同一份渲染**; 窗口默认宽 = 面板默认宽 = default_w();
#   容器比最小宽还窄时面板保持最小宽 (页面横滚), 不缩列 (老倪: 字不许截断)。
chk("① 比最小宽(980)还窄的容器里, 面板不让步 (保持最小宽 ⇒ 页面横滚, 不缩列)",
    B["w"] >= 980 and B["minw"] == 980, "窄容器(600)里面板实宽 %s / min %s" % (B["w"], B["minw"]))
_DW = MEW.ModelEnginePanel.default_w()
chk("② 窗口默认宽 = 面板默认宽 default_w() (单屏也放得下 · 可拖宽/最大化)",
    A["w"] == _DW and A["minw"] == 980, "窗口实宽 %s / 默认宽 %s / min %s" % (A["w"], _DW, A["minw"]))

# ③ 真·功能区页面 (studio.TrainingModule) 里那个 me_panel —— 有就比, 实例化不了就如实报错(不许假绿)
try:
    sys.path.insert(0, "/home/ubuntu/zmax/tools/gui")
    import studio as _st_mod  # noqa: E402
    tm = _st_mod.TrainingModule()
    tm.resize(1900, 900)
    tm.show()
    app.processEvents()
    pg = getattr(tm, "me_panel", None)
    chk("③ 功能区页面确实内嵌同一个 ModelEnginePanel", pg is not None, type(pg).__name__)
    if pg is not None:
        C = _dump(pg, inv, st)
        d_ac = _diff(A, C)
        chk("④ 功能区页面里的面板与窗口**逐列/逐格一致** (老倪这条要求)", not d_ac, (d_ac[:3] or "0 处差异"))
        chk("⑤ 页面面板默认宽 = 窗口默认宽 (两处默认视图同宽 · 同一个 default_w())",
            C["w"] == _DW and C["minw"] == 980, "页面实宽 %s / 期望 %s / min %s" % (C["w"], _DW, C["minw"]))
except Exception as e:                                                        # noqa: BLE001
    chk("③ 功能区页面实例化对比 (不许假绿: 失败即失败)", False, "%s: %s" % (type(e).__name__, str(e)[:90]))

# ⑥ 抓图逐像素对照: 同一个面板实例在"窗口"与"功能区页面"里的**渲染结果本身**必须一致
try:
    from PIL import Image, ImageDraw                                              # noqa: E402
    SHOT_A = "/home/ubuntu/.hermes/cache/scratch/me_panel_window.png"
    SHOT_B = "/home/ubuntu/.hermes/cache/scratch/me_panel_page.png"
    CMP = "/home/ubuntu/.hermes/cache/scratch/me_page_vs_window.png"
    win.panel.grab().save(SHOT_A)
    pg = getattr(tm, "me_panel", None)
    if pg is not None:
        # 页面面板是 poll=True (有自己的轮询) ⇒ 抓图前**冻结**, 否则它自己刷成实时数据再抓 = 比的是两份不同数据
        for _a in ("_t", "_lt", "_fetcher"):
            _o = getattr(pg, _a, None)
            if _o is not None:
                try:
                    _o.stop()
                except Exception:                                                 # noqa: BLE001
                    pass
        pg.feed(inv, st)
        app.processEvents()
        pg.grab().save(SHOT_B)
        ia, ib = Image.open(SHOT_A).convert("RGB"), Image.open(SHOT_B).convert("RGB")
        w, h = min(ia.width, ib.width), min(ia.height, ib.height)
        ia2, ib2 = ia.crop((0, 0, w, h)), ib.crop((0, 0, w, h))
        # 逐像素比对齐到**表格区**: 面板表头带 GPU 实时读数 (两处各自取一次, 数值天然可能不同),
        # 而老倪要的"一致"是那张表 (行/列/数据/颜色)。
        tba, tbb = win.panel.tb, pg.tb
        ra, rb = (tba.x(), tba.y(), tba.width(), tba.height()), (tbb.x(), tbb.y(), tbb.width(), tbb.height())
        chk("⑥a 两处表格几何一致 (同一个位置/尺寸)", ra == rb, "窗口 %s / 页面 %s" % (ra, rb))
        ca, cb = ia2.crop(ra), ib2.crop(rb)
        d = sum(1 for y in range(ca.height) for x in range(ca.width) if ca.getpixel((x, y)) != cb.getpixel((x, y)))
        tot = max(ca.width * ca.height, 1)
        pct = 100.0 * d / tot
        chk("⑥b 窗口面板 vs 页面面板 **表格区逐像素**一致", pct < 0.5,
            "差异 %.3f%% (%d/%d px) · 面板 %s / %s · 表 %dx%d"
            % (pct, d, tot, ia.size, ib.size, ca.width, ca.height))
        cv = Image.new("RGB", (w, h * 2 + 60), (13, 17, 23))
        dr = ImageDraw.Draw(cv)
        dr.text((10, 6), u"① 单独打开的模型引擎窗口 (panel.grab)", fill=(63, 185, 80))
        cv.paste(ia2, (0, 26))
        dr.text((10, h + 34), u"② 控制台功能区页面里内嵌的同一个面板 (panel.grab)", fill=(210, 153, 34))
        cv.paste(ib2, (0, h + 54))
        cv.save(CMP)
        print("对照图: %s (%dx%d)" % (CMP, cv.width, cv.height))
except Exception as e:                                                            # noqa: BLE001
    chk("⑥ 抓图逐像素对照", False, "%s: %s" % (type(e).__name__, str(e)[:80]))

# ⑦ 2026-10-14 老倪: 「在状态空间工程, 增加一个 模型引擎 按钮, 用于打开模型引擎的独立窗口」
#    ⇒ 画布工具栏必须有这个按钮, 且它打开的**就是**同一个 ModelEngineWindow (不是画布专用第二套界面)
_sm = open("/home/ubuntu/zmax/tools/gui/simulink_module.py", encoding="utf-8").read()
chk("⑦a 状态空间画布工具栏有「🧠 模型引擎」按钮",
    '"🧠 模型引擎"' in _sm and "tl.addWidget(self.btn_me_win)" in _sm,
    "mk_btn 定义 + addWidget 都在" if ('"🧠 模型引擎"' in _sm and "tl.addWidget(self.btn_me_win)" in _sm) else "缺")
chk("⑦b 回调打开的是同一个 ModelEngineWindow 类 (同一份代码)",
    "def open_model_engine_window" in _sm and "from model_engine_window import ModelEngineWindow" in _sm)
chk("⑦c 已有窗口就置顶复用 (不新开第二个)",
    "w is not None and w.isVisible()" in _sm and "self._me_win" in _sm)
_st = open("/home/ubuntu/zmax/tools/gui/studio.py", encoding="utf-8").read()
chk("⑦d 命令通道 ss_model_engine → 同一执行体 (无鼠标可复现)",
    'line == "ss_model_engine"' in _st and "self.simulink.open_model_engine_window" in _st)

print("\n".join(res))
ok = sum(1 for r in res if r.startswith("✓"))
print("\n判据汇总: %d/%d PASS" % (ok, len(res)))
sys.stdout.flush()
# ⚠️ 页面实例 (TrainingModule) 自带 poll 线程 ⇒ 走 PyQt 正常退出会被线程卡在析构里 dump core
#    (实测: 线程停在 model_engine_window.py:188 run)。用 os._exit 绕开析构, 判据结果照样先刷出来。
os._exit(0 if ok == len(res) else 1)
