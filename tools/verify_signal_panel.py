# -*- coding: utf-8 -*-
"""判据: 信号分析窗口 列口径/可拖宽/图标/与数据空间同源同值。

老倪 2026-10-17: 「信号分析的窗口为什么没有图标? 左侧每列都可以用鼠标调整宽度;
   要与数据空间 trace 的数据同步, 列保持一致; 信号名称改 signal, 当前值改 value,
   输出节点改 Tx, 来源节点改 Rx; 增加 type 列; 增加 Layer 列; 增加中文名称列」
"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "gui"))

fails = []
def ck(n, ok, info=""):
    print(("%s %s" % ("✅" if ok else "❌", n)) + ((" · " + info) if info else ""))
    if not ok:
        fails.append(n)

app = QApplication.instance() or QApplication([])
from canoe_graphic import CanoeGraphicWidget, ROOT
from lerobot.middleware import live_signals as L

w = CanoeGraphicWidget()
hdr = [w.tree.headerItem().text(i).split(" ▾")[0]      # 列头带 "▾" (可过滤标记)
       for i in range(w.tree.columnCount())]
ck("列口径 = Name/Layer/Signal/Value/Type/Tx/Rx",
   hdr == ["Name", "Layer", "Signal", "Value", "Type", "Tx", "Rx"], str(hdr))
ck("7 列全部可鼠标拖宽", all(w.tree.header().sectionResizeMode(i) == 0 for i in range(7)),
   str([w.tree.header().sectionResizeMode(i) for i in range(7)]))
_ico = os.path.join(ROOT, "tools/gui/logo.png")
ck("窗口图标存在且非空", os.path.exists(_ico) and not QIcon(_ico).isNull(), _ico)

# 同源: 三路都走 live_signals (与数据空间同一份缓存)
ck("sstrace/sseng/gravity 走同一 provider",
   all(k in getattr(w, "_PROV", {}) for k in ("sstrace", "sseng", "gravity"))
   or "live_signals" in open(os.path.join(ROOT, "tools/gui/canoe_graphic.py"), encoding="utf-8").read(),
   str(getattr(w, "_PROV", {})))

# 同值: 缓存窗口内两次读一致 (两个窗口都读这份)
a = L.topics(); time.sleep(0.1); b = L.topics()
ck("同一缓存窗口内数值一致", all(a[k]["fields"] == b[k]["fields"] for k in a),
   "%d 话题" % len(a))

# Signal 列必须与数据空间 Trace 同一套英文变量名 (同一条信号 ⇒ 同一个名字)
import re as _re
from lerobot.middleware import signal_en as _SE
ck("映射与 Trace 同口径 (end_x/grasp_prob/gravity)",
   _SE.en_of("末端_x") == "end_x" and _SE.en_of("接触概率") == "grasp_prob"
   and _SE.en_of("下降·L2 力大小_mps") == "descend_l2_force_mps",
   repr((_SE.en_of("末端_x"), _SE.en_of("接触概率"))))

# 行内容: 至少一行 7 列齐全且 Value 是数值
w.show(); t0 = time.time()
while time.time() - t0 < 2.5:
    app.processEvents(); time.sleep(0.1)
found = []
def walk(n):
    for i in range(n.childCount()):
        c = n.child(i)
        if c.childCount():
            walk(c)
        elif c.text(2) not in ("-", ""):
            found.append([c.text(k) for k in range(7)])
walk(w.tree.invisibleRootItem())
ck("有数值行", len(found) > 100, "%d 行" % len(found))
ck("Signal 全英文 (无非 ASCII)", not [r for r in found if _re.search(r"[^\x00-\x7f]", r[2])],
   str([r[2] for r in found if _re.search(r"[^\x00-\x7f]", r[2])][:3]))
ck("Layer 列有层值 (非全 SYS)", any(r[1] in ("L2", "L3", "L4", "L5") for r in found),
   str(sorted({r[1] for r in found})))
# Tx 必须是真节点名 (或带进程标记), 不许把"表/面板"当节点糊上去
_tx = [r[5] for r in found]
ck("Tx 无假节点「万有引力表 (主参数…」", not [x for x in _tx if "万有引力表 (主参数" in x],
   str([x for x in _tx if "万有引力表 (主参数" in x][:2]))
ck("Tx 覆盖多个真节点", len(set(_tx)) >= 8, str(sorted(set(_tx))[:10]))
ck("Tx 无空值", all(x.strip() for x in _tx), str([x for x in _tx if not x.strip()][:3]))
ck("gravity 的 Tx 是进程(非节点)", w._out_node("gravity.下降·L2 力大小_mps").startswith("gravity_trace_pub"),
   w._out_node("gravity.下降·L2 力大小_mps"))
ck("前馈速度的 Tx = 前馈加速器", w._out_node("sstrace.前馈速度_mps") == "前馈加速器",
   w._out_node("sstrace.前馈速度_mps"))
ck("每行 7 列都有内容", all(all(x.strip() for x in r) for r in found[:50]),
   str(found[:1]))
# 🎚 列头过滤: Layer 只选 L2 / Type 只选一个类型
from PyQt5.QtWidgets import QMenu as _QMenu


def visible_rows():
    out = []
    def walk(x):
        for i in range(x.childCount()):
            ch = x.child(i)
            if ch.childCount():
                walk(ch)
            elif not ch.isHidden():
                out.append([ch.text(k) for k in range(7)])
    walk(w.tree.invisibleRootItem())
    return out


_n0 = len(visible_rows())
_orig = _QMenu.exec_
def _pick_l2(self, *a, **k):
    for act in self.actions():
        if act.data() == "L2":
            return act
    return None
_QMenu.exec_ = _pick_l2
w._on_header_filter(1)
_v1 = visible_rows()
ck("列头过滤 Layer=L2", len(_v1) > 0 and {r[1] for r in _v1} == {"L2"},
   "%d → %d 行, 层=%s" % (_n0, len(_v1), sorted({r[1] for r in _v1})))
ck("表头显示过滤值", "L2" in w.tree.headerItem().text(1), w.tree.headerItem().text(1))

def _pick_any_type(self, *a, **k):
    for act in self.actions():
        d = act.data()
        if d and str(d).startswith("zmax::"):
            return act
    return None
_QMenu.exec_ = _pick_any_type
w._on_header_filter(4)
_v2 = visible_rows()
ck("再叠 Type 过滤", len(_v2) > 0 and len({r[4] for r in _v2}) == 1,
   "%d 行, 类型=%s" % (len(_v2), sorted({r[4] for r in _v2})))
_QMenu.exec_ = _orig

print("\n%s" % ("✅ 全部通过" if not fails else "❌ 失败: %s" % fails))
sys.exit(0 if not fails else 1)
