#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据: 🤖 机器人执行器 的 AR / 真机 两个开关 (画布真源 + 绘制 + 事件级命中 + ctl_auth 联动)

四层, 缺一层就是"看起来有开关":
  ① 真源  画布 ssact.params 有 ar_real_sw / ar_scene / real_auth, 且两个开关默认 False
  ② 绘制  SimNodeItem 能渲染出两个开关条 (离屏渲图, 数红/绿像素)
  ③ 事件  真 sendEvent 到 viewport: 点左开关 → on_toggle_ar 1 次; 点右 → on_toggle_real 1 次; 点标题区 → 0 次
  ④ 消费  真连点 3 次断言 True→False→True; on_toggle_real 真写 ctl_auth (armed 跟着变), 结束时恢复关
"""
import os
import sys

REPO = "/home/ubuntu/zmax"
os.chdir(REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.path.insert(0, os.path.join(REPO, "tools", "gui"))
sys.path.insert(0, os.path.join(REPO, "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ZMAX_NO_OPEN"] = "1"        # 判据会连点 AR 开关, 不许弹浏览器

fails = []


def ck(ok, name, detail=""):
    print("%s %-46s %s" % ("✅" if ok else "❌", name, detail))
    if not ok:
        fails.append(name)


# ── ① 真源
from lerobot.engineering import flows  # noqa: E402
d, errs = flows.load_canvas()
n = next((x for x in d["nodes"] if x.get("id") == "ssact"), None)
ck(n is not None, "① 画布里有 🤖 机器人执行器 (ssact)")
p = (n or {}).get("params") or {}
ck(bool(p.get("ar_real_sw")), "① params.ar_real_sw", str(p.get("ar_real_sw")))
ck(p.get("ar_scene") is False, "① AR 开关默认关 (ar_scene=False)", str(p.get("ar_scene")))
ck(p.get("real_auth") is False, "① 真机开关默认关 (real_auth=False)", str(p.get("real_auth")))

# ── ② 绘制
from PyQt5.QtWidgets import QApplication  # noqa: E402
from PyQt5.QtCore import QRectF, QPointF, Qt, QEvent  # noqa: E402
from PyQt5.QtGui import QImage, QPainter, QMouseEvent  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import simulink_module as SM  # noqa: E402

rects = SM._ar_real_sw_rects(n["w"], n["h"])
ck(set(rects) == {"ar", "real"}, "② 两个开关矩形 (ar/real)", str({k: (round(v.x()), round(v.y()), round(v.width()), round(v.height())) for k, v in rects.items()}))
ck(rects["ar"].right() < rects["real"].left() + 1 and rects["ar"].left() < rects["real"].left(),
   "② 左=AR 右=真机 (不重叠)", "ar.right=%.0f real.left=%.0f" % (rects["ar"].right(), rects["real"].left()))

# 渲图: 关态应出现红色描边, 开态绿色
class _StubScene:
    links = []
    nodes = {}
    def __init__(self):
        self.calls = []


stub = _StubScene()
item = SM.SimNodeItem(n, stub)
img = QImage(int(n["w"]), int(n["h"]), QImage.Format_ARGB32)
img.fill(0)
painter = QPainter(img)
try:
    from PyQt5.QtWidgets import QStyleOptionGraphicsItem
    opt = QStyleOptionGraphicsItem()
    item._paint_core(painter, opt, None)
except Exception as e:
    print("   (paint 异常: %s: %s)" % (type(e).__name__, e))
painter.end()
red = green = 0
for y in range(int(rects["ar"].top()), int(rects["real"].bottom()) + 1):
    for x in range(0, int(n["w"])):
        c = img.pixelColor(x, y)
        if c.red() > 150 and c.green() < 110:
            red += 1
        elif c.green() > 140 and c.red() < 120:
            green += 1
ck(red > 200, "② 默认关态渲出红色开关", "红像素 %d / 绿像素 %d" % (red, green))

# ── ③ 事件级命中 (真 sendEvent 到 viewport)
from PyQt5.QtWidgets import QGraphicsView  # noqa: E402


class _Dummy:
    """SimCanvas 构造时会连 module 上一堆信号/回调, stub 里一律给一个可调用的空壳。"""

    def __call__(self, *a, **k):
        return None

    def __getattr__(self, k):
        return _Dummy()

    def __bool__(self):
        return False


class Mod:
    def __init__(self):
        self.ar = 0
        self.real = 0

    def on_toggle_ar(self, node):
        self.ar += 1

    def on_toggle_real(self, node):
        self.real += 1

    def __getattr__(self, k):
        return _Dummy()


mod = Mod()
cv = SM.SimCanvas(mod)
# 让 _paint_core 能拿到画布数据 (真 GUI 里由 load_flow_file 填)
cv.links = list(d["links"])
cv.nodes = {x["id"]: x for x in d["nodes"]}
cv.resize(1200, 800)
cv.show()
app.processEvents()

# 手工把 ssact 节点项放进 scene (不走整图加载, 只看命中路径)
it2 = SM.SimNodeItem(n, cv)
it2.scene_ref = cv
cv.scene().addItem(it2)
it2.setPos(n["x"], n["y"])
app.processEvents()

def _click_at(scene_pt):
    vp_pt = cv.mapFromScene(scene_pt)
    ev = QMouseEvent(QEvent.MouseButtonPress, QPointF(vp_pt), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    app.sendEvent(cv.viewport(), ev)
    app.processEvents()


_ar_c = it2.scenePos() + rects["ar"].center()
_re_c = it2.scenePos() + rects["real"].center()
_title = it2.scenePos() + QPointF(n["w"] / 2.0, 20)
_click_at(_ar_c)
_click_at(_re_c)
_click_at(_title)
ck(mod.ar == 1, "③ 点左开关 → on_toggle_ar 1 次", "实际 %d" % mod.ar)
ck(mod.real == 1, "③ 点右开关 → on_toggle_real 1 次", "实际 %d" % mod.real)
ck(mod.ar + mod.real == 2, "③ 点标题区不触发任何开关", "合计 %d" % (mod.ar + mod.real))

# ── ④ 处理器: 三连点 + ctl_auth 真联动
import ctl_auth as CA  # noqa: E402

class Mod2(Mod):
    def __init__(self):
        super().__init__()
        self._items = {}
        self.saved = []
        self.logs = []
    def _save_param_to_flow(self, node, key):
        self.saved.append((key, node["params"][key]))
    def _log(self, m):
        self.logs.append(m)
    def _publish_exec_switches(self, node):
        self.saved.append(("publish", (node["params"].get("ar_scene"), node["params"].get("real_auth"))))


m2 = Mod2()
node_t = {"id": "ssact", "name": "🤖 机器人执行器", "params": {"ar_real_sw": True, "ar_scene": False, "real_auth": False}}
for _ in range(3):
    SM.SimulinkModule.on_toggle_ar(m2, node_t)
ck([s[1] for s in m2.saved if s[0] == "ar_scene"] == [True, False, True],
   "④ AR 连点 3 次 True→False→True", str([s[1] for s in m2.saved if s[0] == "ar_scene"]))

before = (CA.info() or {}).get("armed")
SM.SimulinkModule.on_toggle_real(m2, node_t)          # 开
armed_on = (CA.info() or {}).get("armed")
left = (CA.info() or {}).get("left_s")
SM.SimulinkModule.on_toggle_real(m2, node_t)          # 关
armed_off = (CA.info() or {}).get("armed")
ck(armed_on is True and armed_off is False,
   "④ 真机开关真写 ctl_auth (开→armed, 关→撤销)",
   "before=%s on=%s(剩余%.0fs) off=%s" % (before, armed_on, left or 0, armed_off))
ck(node_t["params"]["real_auth"] is False, "④ 收尾真机开关回到关 (默认态)", str(node_t["params"]["real_auth"]))

print("-" * 66)
# 收尾: 判据连点会把画布 ar_scene 落成 True —— 必须复位成默认关, 否则下次打开控制台是 AR 模式
try:
    d3, _e3 = flows.load_canvas()
    n3 = next((x for x in d3["nodes"] if x.get("id") == "ssact"), None)
    if n3 is not None:
        n3.setdefault("params", {})["ar_scene"] = False
        n3["params"]["real_auth"] = False
        flows.save_canvas(d3)
        d4, _e4 = flows.load_canvas()
        n4 = next((x for x in d4["nodes"] if x.get("id") == "ssact"), None)
        ck(n4["params"].get("ar_scene") is False and n4["params"].get("real_auth") is False,
           "⑤ 跑完画布复位成默认关 (ar_scene/real_auth=False)",
           str((n4["params"].get("ar_scene"), n4["params"].get("real_auth"))))
except Exception as e:
    ck(False, "⑤ 跑完画布复位", "%s: %s" % (type(e).__name__, e))

print("结论:", "✅ 全过" if not fails else "❌ 失败 %d 项: %s" % (len(fails), fails))
sys.exit(0 if not fails else 1)
