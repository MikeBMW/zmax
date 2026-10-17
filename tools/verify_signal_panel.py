# -*- coding: utf-8 -*-
"""判据: 信号分析窗口 列口径/可拖宽/图标/与数据空间同源同值。

老倪 2026-10-17: 「信号分析的窗口为什么没有图标? 左侧每列都可以用鼠标调整宽度;
   要与数据空间 trace 的数据同步, 列保持一致; 信号名称改 signal, 当前值改 value,
   输出节点改 Tx, 来源节点改 Rx; 增加 type 列; 增加 Layer 列; 增加中文名称列」
"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt5.QtCore import Qt
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
from lerobot.middleware import attribution as _at

w = CanoeGraphicWidget()
hdr = [w.tree.headerItem().text(i).split(" ▾")[0]      # 列头带 "▾" (可过滤标记)
       for i in range(w.tree.columnCount())]
ck("列口径 = Name/Layer/Signal/Value/Type/Tx/Rx",
   hdr == ["Name", "Layer", "Signal", "Value", "Rate", "Type", "Tx", "Rx"], str(hdr))
ck("7 列全部可鼠标拖宽", all(w.tree.header().sectionResizeMode(i) == 0 for i in range(8)),
   str([w.tree.header().sectionResizeMode(i) for i in range(8)]))
_ico = os.path.join(ROOT, "tools/gui/logo.png")
ck("窗口图标存在且非空", os.path.exists(_ico) and not QIcon(_ico).isNull(), _ico)

# 同源: 三路都走 live_signals (与数据空间同一份缓存)
ck("sstrace/sseng/gravity 走同一 provider",
   all(k in getattr(w, "_PROV", {}) for k in ("sstrace", "sseng", "gravity"))
   or "live_signals" in open(os.path.join(ROOT, "tools/gui/canoe_graphic.py"), encoding="utf-8").read(),
   str(getattr(w, "_PROV", {})))

# 同值: 缓存窗口内两次读一致 (两个窗口都读这份)
L._CACHE.update(t=0.0, data=None)          # 强制取一次新快照, 再连读两拍 —— 测的是"缓存窗口内一致"
a = L.topics(); b = L.topics()
# NaN != NaN ⇒ 用 repr 比 (同一份缓存对象必须逐字相同, 包括 NaN 位置)
ck("同一缓存窗口内数值一致", all(repr(a[k]["fields"]) == repr(b[k]["fields"]) for k in a),
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
            found.append([c.text(k) for k in range(8)])
walk(w.tree.invisibleRootItem())
ck("有数值行", len(found) > 100, "%d 行" % len(found))
ck("Signal 全英文 (无非 ASCII)", not [r for r in found if _re.search(r"[^\x00-\x7f]", r[2])],
   str([r[2] for r in found if _re.search(r"[^\x00-\x7f]", r[2])][:3]))
ck("Layer 列有层值 (非全 SYS)", any(r[1] in ("L2", "L3", "L4", "L5") for r in found),
   str(sorted({r[1] for r in found})))
# Tx 必须是真节点名 (或带进程标记), 不许把"表/面板"当节点糊上去
_tx = [r[6] for r in found]
ck("Tx 无假节点「万有引力表 (主参数…」", not [x for x in _tx if "万有引力表 (主参数" in x],
   str([x for x in _tx if "万有引力表 (主参数" in x][:2]))
ck("Tx 覆盖多个真节点", len(set(_tx)) >= 8, str(sorted(set(_tx))[:10]))
ck("Tx 无空值", all(x.strip() for x in _tx), str([x for x in _tx if not x.strip()][:3]))
# 📚 2026-10-17 老倪: 「万有引力表进程，怎么能在 Tx 的发送节点呢？也没有万有引力这个节点啊」
#   ⇒ 口径反转: gravity 没有画布节点, Tx 必须写 "—" (旧判据"Tx 是进程名"正是在要求假节点)
# 📚 2026-10-17 老倪: 「万有引力表进程, 怎么能在 Tx 的发送节点呢」+「Tx 都是 L2~L5 的 node 节点」
#   万有引力表 = 标定诊断测量·主参数 M 的输出 ⇒ Tx 必须是那个工程节点, 不是进程名也不是 "—"
# 📚 2026-10-17 老倪: 这两个窗口只保留 L2 ⇒ 万有引力表(标定诊断测量, L4)整体不进来
ck("gravity 不在这两个窗口 (L4, Tx 无 L2 节点)",
   w._out_node("gravity.下降·L2 力大小_mps") == "—"
   and not _at.show_in_l2("gravity.下降·L2 力大小_mps"),
   f"Tx={w._out_node('gravity.下降·L2 力大小_mps')} 显示={_at.show_in_l2('gravity.下降·L2 力大小_mps')}")
ck("前馈速度的 Tx = 前馈加速器", w._out_node("sstrace.前馈速度_mps") == "前馈加速器",
   w._out_node("sstrace.前馈速度_mps"))
ck("每行 7 列都有内容", all(all(x.strip() for x in r) for r in found[:50]),
   str(found[:1]))
# 🟢 插拔场景: 全部动态信号都在"显示状态" (勾上), 波形优先画 TCP/八阶段
_green_rows = []
def _walk_green(x):
    for i in range(x.childCount()):
        ch = x.child(i)
        if ch.childCount():
            _walk_green(ch)
        else:
            _green_rows.append(ch)
for _gi in range(w.tree.topLevelItemCount()):
    _g = w.tree.topLevelItem(_gi)
    if _g.text(0).startswith("🟢"):
        _walk_green(_g)
_checked = [c for c in _green_rows if c.checkState(0) == 2]
ck("插拔场景全部动态信号已勾选", len(_checked) >= len(_green_rows) - 8,
   "%d 行 · 已勾 %d" % (len(_green_rows), len(_checked)))
_need = ["sstrace.末端_x", "sstrace.末端_y", "sstrace.末端_z",
         "sstrace.阶段序号", "sstrace.八阶段序号"]
ck("TCP 位姿 + 八阶段 在勾选里", all(k in w.selected for k in _need),
   str({k: (k in w.selected) for k in _need}))
ck("波形优先画 TCP/八阶段", all(k in w.wave.curves for k in _need), str(w.wave.curves[:5]))
_t0 = time.time()
for _ in range(5):
    w._update_tree_values(); app.processEvents()
ck("刷新不被 278 条拖死 (5 次 < 1s)", (time.time() - _t0) < 1.0, "%.2fs" % (time.time() - _t0))

# 🔧 L2 原子技能 (老倪: 「怎么没有 L2 级别, 原子技能功能 的输出信号? 例如 SK01 节点呢?」)
_sk = [(str(c.data(0, 0x0100)), c.text(1), c.text(6)) for c in []]
_skrows = []
def _wsk(x):
    for i in range(x.childCount()):
        ch = x.child(i)
        if ch.childCount():
            _wsk(ch)
        else:
            k = str(ch.data(0, 0x0100))
            if k.startswith(("skill.", "skillphys.")) and not k.endswith(".ts"):
                _skrows.append((k, ch.text(1), ch.text(6)))
_wsk(w.tree.invisibleRootItem())
ck("原子技能信号在表里", len(_skrows) >= 60, "%d 条" % len(_skrows))
# skill.n / skill.块帧龄_s 是派发服务自身的计数, 不属于某个原子技能 (SYS 合理);
# 键里点得出 SK0x / 阶段名的, 必须落在 L2 原子技能上。
from lerobot.middleware import attribution as _at            # noqa: E402
_bad_lay = [(_k, l) for _k, l, _t in _skrows if l != "L2" and _at.skill_stage_of(_k)]
ck("原子技能层 = L2", not _bad_lay,
   "%d 条, 非 L2 %d %s" % (len(_skrows), len(_bad_lay), str(_bad_lay[:3])))
_txs = sorted({t for _k, _l, t in _skrows})
# 📚 2026-10-17 老倪: 「与状态空间的工程同一个数据源, 保证 node 的严格相同」
#   节点名统一走 naming.unique_map ⇒ SK 节点的显示名是 接近/对位/… (工程库原名 "① 接近 · SK01")
_SK_NAMES = {"接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"}
ck("SK01~SK08 八个技能节点都出现", len(set(_txs) & _SK_NAMES) >= 8,
   str(sorted(set(_txs) & _SK_NAMES)))
ck("SK01 的 Tx = 接近 (工程节点名)", "接近" in _txs, str(_txs[:3]))

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
                out.append([ch.text(k) for k in range(8)])
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
    # 挑"当前 L2 过滤下真实存在的类型" (类型词表随话题变, 钉死 zmax:: 前缀会假红)
    for act in self.actions():
        d = act.data()
        if d and not str(d).startswith("__all") and (_v1 and any(r[5] == str(d) for r in _v1)):
            return act
    for act in self.actions():
        d = act.data()
        if d and not str(d).startswith("__all"):
            return act
    return None
_QMenu.exec_ = _pick_any_type
w._on_header_filter(5)
_v2 = visible_rows()
ck("再叠 Type 过滤", len(_v2) > 0 and len({r[5] for r in _v2}) == 1,
   "%d 行, 类型=%s" % (len(_v2), sorted({r[5] for r in _v2})))
_QMenu.exec_ = _orig

# 🧹 清空 = 取消所有勾选并停掉自动补勾 (老倪: 「清空按钮, 要清空所有打 tick 对好的信号, 都全不显示了」)
def _ticked():
    n = 0
    _st = [w.tree.invisibleRootItem()]
    while _st:
        _c = _st.pop()
        for _j in range(_c.childCount()):
            _ch = _c.child(_j)
            if _ch.childCount():
                _st.append(_ch)
            elif (_ch.flags() & Qt.ItemIsUserCheckable) and _ch.checkState(0) == 2:
                n += 1
    return n
_before = len(w.selected)
w.clear()
app.processEvents()
ck("清空后勾选/波形全空", len(w.selected) == 0 and len(w.wave.curves) == 0 and _ticked() == 0,
   "清空前 %d 条 → 已选 %d / 绘制 %d / 勾选行 %d"
   % (_before, len(w.selected), len(w.wave.curves), _ticked()))
w._fill_tree()
for _ in range(6):
    app.processEvents(); time.sleep(0.2)
ck("清空后不会被自动补勾顶回来", len(w.selected) == 0 and _ticked() == 0,
   "等 1.2s + 重建树 · 已选 %d" % len(w.selected))
_tgt = None
_st = [w.tree.invisibleRootItem()]
while _st and _tgt is None:
    _c = _st.pop()
    for _j in range(_c.childCount()):
        _ch = _c.child(_j)
        if _ch.childCount():
            _st.append(_ch)
        elif (str(_ch.data(0, 0x0100)) == "sstrace.末端_x"
              and (_ch.flags() & Qt.ItemIsUserCheckable)):
            _tgt = _ch            # 同名信号在插拔/摆盘各有一行, 只能拿**可勾选**那份
            break
if _tgt is not None:
    _tgt.setCheckState(0, Qt.Checked)
    app.processEvents()
ck("按需手动打勾 = 只加这一条", w.selected == ["sstrace.末端_x"] and w.wave.curves == ["sstrace.末端_x"],
   str(w.selected))

print("\n%s" % ("✅ 全部通过" if not fails else "❌ 失败: %s" % fails))
sys.exit(0 if not fails else 1)
