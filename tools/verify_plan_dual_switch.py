#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_dual_switch.py — plan 节点双开关取证 (离屏渲图 + 事件级点击 + station 闸)

老倪 2026-10-25: ①「桥接 v_ff 这几个字改成 v_ff 连接 / v_ff 断开 (绿=连接 红=断开)」
                ②「再增加一个一样的开关放在节点右侧, 显示 station 连接 / station 断开」
"""
import os
import sys
import json
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPO = "/home/ubuntu/zmax"
sys.path.insert(0, os.path.join(REPO, "tools", "gui"))
sys.path.insert(0, REPO)

from PyQt5.QtWidgets import QApplication  # noqa: E402
from PyQt5.QtCore import QPointF, QPoint, Qt, QRectF  # noqa: E402
from PyQt5.QtGui import (QImage, QPainter, QMouseEvent, QColor, QFont, QPen, QBrush,  # noqa: E402
                         QFontMetrics)
from PyQt5.QtWidgets import QGraphicsScene  # noqa: E402

app = QApplication([])
import simulink_module as SM  # noqa: E402

OUT = os.path.join(REPO, "reports", "probe_dual_switch")
os.makedirs(OUT, exist_ok=True)
FAIL = []


def ck(name, cond, detail=""):
    print(("  ✅ " if cond else "  ❌ ") + name + (("  " + str(detail)) if detail else ""))
    if not cond:
        FAIL.append(name)


class Stub:
    links = []
    nodes = {}
    _items = {}
    _flow_path = None

    def __init__(self):
        self.calls = []

    def __getattr__(self, _name):          # undo/redo/log 等模块方法一律当空操作
        return lambda *a, **k: None

    def on_toggle_bridge(self, node):
        self.calls.append("bridge")

    def on_toggle_station(self, node):
        self.calls.append("station")


def mkn(vff, st):
    return {"id": "n_moveit", "name": "🧭 运动规划", "type": "model",
            "x": 100, "y": 100, "w": 280, "h": 110,
            "params": {"bridge_vff": bool(vff), "bridge_vff_cap_mms": 10.0,
                       "bridge_vff_deadband_mms": 3.0, "station_link": bool(st)}}


print("① 开关几何 (左右各半, 不重叠, 都在节点内)")
w, h = 280, 110
r = SM._bridge_sw_rects(w, h)
print("    vff=%s\n    station=%s" % (r["vff"], r["station"]))
ck("两个矩形", len(r) == 2)
ck("左右不重叠", r["vff"].right() <= r["station"].left())
ck("同一行高", abs(r["vff"].top() - r["station"].top()) < 1e-6 and abs(r["vff"].height() - r["station"].height()) < 1e-6)
ck("都在节点内", r["station"].right() <= w and r["vff"].top() > h * 0.5 and r["vff"].bottom() <= h)
ck("_bridge_rect 兼容=左半", SM._bridge_rect(w, h) == r["vff"])

print("② 离屏渲图 (两态各一张, OCR 认字)")
for tag, (vff, st) in (("on", (True, True)), ("off", (False, False))):
    sc = QGraphicsScene()
    it = SM.SimNodeItem(mkn(vff, st), Stub())
    sc.addItem(it)
    box = it.mapToScene(it.boundingRect()).boundingRect()
    SC = 2
    img = QImage(int(box.width()) * SC, int(box.height()) * SC, QImage.Format_ARGB32)
    img.fill(QColor("#0d1117"))
    p = QPainter(img)
    sc.render(p, QRectF(0, 0, box.width() * SC, box.height() * SC), box)
    p.end()
    fp = os.path.join(OUT, "plan_%s.png" % tag)
    img.save(fp)
    print("    渲染 → %s (%dx%d)" % (fp, img.width(), img.height()))

import subprocess  # noqa: E402
for tag, want in (("on", ("v_ff 连接", "station 连接")), ("off", ("v_ff 断开", "station 断开"))):
    fp = os.path.join(OUT, "plan_%s.png" % tag)
    txt = subprocess.run(["tesseract", fp, "-", "-l", "chi_sim+eng", "--psm", "6"],
                         capture_output=True, text=True).stdout.replace(" ", "")
    ok = all(w.replace(" ", "") in txt for w in want)
    print("    OCR[%s] = %r" % (tag, txt.strip().replace("\n", " | ")[:120]))
    print("    (OCR 参考, 不作判据)")

print("③ 事件级点击 (viewport → SimCanvas.mousePressEvent → 命中 → handler)")
st = Stub()
cv = SM.SimCanvas(st)
cv.resize(1200, 800)
it = SM.SimNodeItem(mkn(True, True), st)
cv._scene.addItem(it)
it.setPos(100, 100)
cv.show()
app.processEvents()
rects = SM._bridge_sw_rects(it.w, it.h)


def click(scene_pt):
    pos = cv.mapFromScene(scene_pt)
    ev = QMouseEvent(QMouseEvent.MouseButtonPress, QPoint(pos.x(), pos.y()),
                     Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    n0 = len(st.calls)
    QApplication.sendEvent(cv.viewport(), ev)
    app.processEvents()
    return st.calls[n0:] if len(st.calls) > n0 else []


c1 = click(QPointF(100 + rects["vff"].center().x(), 100 + rects["vff"].center().y()))
ck("点左半 → 桥接 handler", c1 == ["bridge"], c1)
c2 = click(QPointF(100 + rects["station"].center().x(), 100 + rects["station"].center().y()))
ck("点右半 → station handler", c2 == ["station"], c2)
c3 = click(QPointF(100 + 20, 100 + 12))
ck("点标题区 → 不误触 (拖动/选中照旧)", c3 == [], c3)

print("④ 两个 handler 真逻辑 (状态翻 + 存回参数 + 日志)")
node = mkn(True, True)


class HStub:
    _items = {}

    def __init__(self):
        self.saved = []
        self.logs = []

    def _save_param_to_flow(self, n, k):
        self.saved.append((n["id"], k, n["params"].get(k)))

    def _log(self, m):
        self.logs.append(m)


HStub.on_toggle_bridge = SM.SimulinkModule.on_toggle_bridge
HStub.on_toggle_station = SM.SimulinkModule.on_toggle_station
hs = HStub()
hs.on_toggle_bridge(node)
ck("v_ff: True→False 并存回", node["params"]["bridge_vff"] is False and hs.saved[-1] == ("n_moveit", "bridge_vff", False), hs.saved[-1:])
hs.on_toggle_station(node)
ck("station: True→False 并存回", node["params"]["station_link"] is False and hs.saved[-1] == ("n_moveit", "station_link", False), hs.saved[-1:])
print("    日志: %s" % hs.logs[-1])
hs.on_toggle_station(node)
ck("station: False→True (可再接通)", node["params"]["station_link"] is True)

print("⑤ station 闸真消费点 (cam_live_stream._plan_node_station_link)")
try:
    import cam_live_stream as CLS
except Exception as e:  # noqa: BLE001
    ck("import cam_live_stream", False, e)
    CLS = None
if CLS:
    base = json.load(open(os.path.join(REPO, "flows", "state_space_obs.json"), encoding="utf-8"))
    for want in (True, False):
        d = json.loads(json.dumps(base))
        for n in d.get("nodes") or []:
            if "bridge_vff" in (n.get("params") or {}):
                n["params"]["station_link"] = want
        tf = os.path.join(tempfile.mkdtemp(), "canvas_%s.json" % want)
        with open(tf, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.environ["ZMAX_CANVAS_JSON"] = tf
        CLS._STATION_LINK_CACHE.clear()
        got = CLS._plan_node_station_link()
        ck("画布 station_link=%s ⇒ 闸=%s" % (want, want), got is want, got)
    os.environ.pop("ZMAX_CANVAS_JSON", None)
    CLS._STATION_LINK_CACHE.clear()
    ck("默认(真画布) 闸=连接", CLS._plan_node_station_link() is True)

print("⑥ 截获 paint 的 drawText = 真判据 (离屏字体太小 OCR 认不准, 这条不看字库)")
class Rec:
    """假 painter: 只记 drawText 的字符串, 其余绘制调用吞掉 (但 font/pen/brush 要回真对象)。"""
    def __init__(self):
        self.texts = []
        self._font = QFont("Sans", 9)
    def __getattr__(self, _n):
        return lambda *a, **k: None
    def font(self):
        return self._font
    def setFont(self, f):
        self._font = f
    def pen(self):
        return QPen(QColor("#e6edf3"))
    def brush(self):
        return QBrush(QColor("#000000"))
    def fontMetrics(self):
        return QFontMetrics(self._font)
    def drawText(self, *a):
        for x in a:
            if isinstance(x, str):
                self.texts.append(x)


def paint_texts(vff, st):
    rec = Rec()
    it = SM.SimNodeItem(mkn(vff, st), Stub())
    it.paint(rec, None, None)
    return rec.texts


for tag, (vff, st), want in (("连接", (True, True), ("v_ff 连接", "station 连接")),
                             ("断开", (False, False), ("v_ff 断开", "station 断开"))):
    txts = paint_texts(vff, st)
    print("    [%s] drawText = %s" % (tag, [t for t in txts if "v_ff" in t or "station" in t]))
    for wd in want:
        ck("画出来的字包含 %r" % wd, wd in txts)

print("⑦ 配色: 连接=绿 #3fb950 / 断开=红 #e05252 (数绘制像素)")
try:
    import numpy as np
    for tag, vff, st in (("on", True, True), ("off", False, False)):
        sc2 = QGraphicsScene()
        it2 = SM.SimNodeItem(mkn(vff, st), Stub())
        sc2.addItem(it2)
        box2 = it2.mapToScene(it2.boundingRect()).boundingRect()
        im2 = QImage(int(box2.width()), int(box2.height()), QImage.Format_ARGB32)
        im2.fill(QColor("#0d1117"))
        pp = QPainter(im2)
        sc2.render(pp, QRectF(0, 0, box2.width(), box2.height()), box2)
        pp.end()
        _buf = im2.constBits(); _buf.setsize(im2.byteCount())
        arr = np.frombuffer(bytes(_buf), dtype=np.uint8).reshape(im2.height(), im2.width(), 4)
        g = int(((arr[:, :, 1] > 140) & (arr[:, :, 2] < 120) & (arr[:, :, 0] < 110)).sum())
        r = int(((arr[:, :, 2] > 170) & (arr[:, :, 0] < 140) & (arr[:, :, 1] < 130)).sum())
        print("    [%s] 绿像素=%d 红像素=%d" % (tag, g, r))
        ck("配色对 (%s)" % ("绿>红" if tag == "on" else "红>绿"), (g > r and g > 300) if tag == "on" else (r > g and r > 300))
except Exception as e:  # noqa: BLE001
    ck("配色统计", False, e)

print("\n=== %s (失败 %d 项) ===" % ("全过" if not FAIL else "有失败: " + ", ".join(FAIL), len(FAIL)))
sys.exit(1 if FAIL else 0)
