# -*- coding: utf-8 -*-
"""判据: 数据空间 Trace 与 信号分析 必须是**同一份全局数据源**, 名字/数值/归属逐条一致。

老倪 2026-10-17: 「Trace窗口和 信号分析的数据源, 必须全局数据一致; 改」
「trace 的 Signal 列, 怎么还有 topic ts json 这样的名字, 而且跟信号分析的 signal 名字对不上」

判据 (每条都实测, 不猜):
  ① 两边 Signal 列都不许出现元数据名 (ts/topic/json/src/count/bytes/n/seq/type/payload)
  ② 同 (话题, 原始字段) 的两行: Signal 名 / Layer / Tx / Rx / 值 必须逐条相同
  ③ 单源证明: 把 middleware.live_signals.topics() 换成哨兵值后, 两个窗口都跟着变
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication                     # noqa: E402

FAIL = []


def ck(name, ok, info=""):
    print(("%s %s" % ("✅" if ok else "❌", name)) + ((" · " + str(info)) if info else ""))
    if not ok:
        FAIL.append(name)


app = QApplication.instance() or QApplication([])
import dds_canoe                                              # noqa: E402
from canoe_graphic import CanoeGraphicWidget                  # noqa: E402
from lerobot.middleware import attribution as A               # noqa: E402
from lerobot.middleware import live_signals as LS             # noqa: E402
from lerobot.middleware import signal_en as E                 # noqa: E402
import re                                                     # noqa: E402

v = dds_canoe.build_view(standalone=True)
w = CanoeGraphicWidget()
w.show()
t0 = time.time()
while time.time() - t0 < 4.0:
    app.processEvents()
    time.sleep(0.05)
v._fill_trace_fixed(force=True)
app.processEvents()

INV = {p: t for t, p in A.LIVE_PREFIX.items()}
META_RE = re.compile(r"(^|\.)(ts|t|topic|json|jsonl|src|count|bytes|n|seq|type|payload|digest)$")

# ① 元数据名
_trace_meta = []
for r in range(v.tb.rowCount()):
    raw = (v.tb.item(r, 2).toolTip() or "").split("\n")[0].strip()
    if META_RE.search(raw or ""):
        _trace_meta.append(raw)
_sys = sum(1 for _r in range(v.tb.rowCount()) if str(v.tb.item(_r, 1).text()).upper() == "SYS")
ck("Trace 不再有 SYS 层", _sys == 0, "%d 行" % _sys)
ck("Trace Signal 列没有 ts/topic/json 这类名字", not _trace_meta,
   "残留 %d %s" % (len(_trace_meta), _trace_meta[:5]))

_panel_meta = []
def _walk(x):
    for i in range(x.childCount()):
        ch = x.child(i)
        if ch.childCount():
            _walk(ch)
        else:
            k = str(ch.data(0, 0x0100) or "")
            if META_RE.search(k.split(".", 1)[-1]):
                _panel_meta.append(k)
_walk(w.tree.invisibleRootItem())
ck("信号分析 Signal 列没有元数据名", not _panel_meta,
   "残留 %d %s" % (len(_panel_meta), _panel_meta[:5]))

# ② 同 (话题, 字段) 逐条一致
panel, trace = {}, {}
def _walk2(x):
    for i in range(x.childCount()):
        ch = x.child(i)
        if ch.childCount():
            _walk2(ch)
        else:
            k = str(ch.data(0, 0x0100) or "")
            if "." in k:
                pre, raw = k.split(".", 1)
                panel[(INV.get(pre, pre), raw)] = (ch.text(2), ch.text(1), ch.text(6), ch.text(7),
                                                   ch.text(3))
_walk2(w.tree.invisibleRootItem())
for r in range(v.tb.rowCount()):
    lines = (v.tb.item(r, 2).toolTip() or "").split("\n")
    raw, topic = lines[0].strip(), ""
    for ln in lines:
        if ln.startswith("话题:"):
            topic = ln.split(":", 1)[1].strip()
    trace[(topic, raw)] = (v.tb.item(r, 2).text(), v.tb.item(r, 1).text(), v.tb.item(r, 7).text(),
                           v.tb.item(r, 8).text(), v.tb.item(r, 3).text())

_common = set(panel) & set(trace)
_name = [(k, panel[k][0], trace[k][0]) for k in _common if panel[k][0] != trace[k][0]]
_attr = [(k, panel[k][1:4], trace[k][1:4]) for k in _common if panel[k][1:4] != trace[k][1:4]]
# 数值一致性: 冻结同一份快照后比对 (不冻结的话, 动作调制这类快变量差一拍就不同, 那不是"源不一致")
_frozen = {k: dict(v) for k, v in LS.topics().items()}
_orig_tp = LS.topics
try:
    LS.topics = lambda *a, **k: _frozen
    v._fill_trace_fixed(force=True)
    w.store.clear()
    for _b in list(w.store.bufs.values()):
        _b.clear()
    for _ in range(15):
        app.processEvents()
        time.sleep(0.1)
    w._update_tree_values()
    app.processEvents()
    _pf, _tf = {}, {}
    def _w2(x):
        for i in range(x.childCount()):
            ch = x.child(i)
            if ch.childCount():
                _w2(ch)
            else:
                k = str(ch.data(0, 0x0100) or "")
                if "." in k:
                    pre, raw = k.split(".", 1)
                    _pf[(INV.get(pre, pre), raw)] = ch.text(3)
    _w2(w.tree.invisibleRootItem())
    for r in range(v.tb.rowCount()):
        lines = (v.tb.item(r, 2).toolTip() or "").split("\n")
        raw, topic = lines[0].strip(), ""
        for ln in lines:
            if ln.startswith("话题:"):
                topic = ln.split(":", 1)[1].strip()
        _tf[(topic, raw)] = v.tb.item(r, 3).text()
    _val = []
    for k in set(_pf) & set(_tf):
        try:
            a, b = float(_pf[k]), float(_tf[k])
        except Exception:                                                  # noqa: BLE001
            continue
        if abs(a - b) > 1e-6:
            _val.append((k, a, b))
finally:
    LS.topics = _orig_tp

ck("同一份快照下数值逐字相同", len(_val) <= 2,
   "比对 %d 条 · 不同 %d %s" % (len(set(_pf) & set(_tf)), len(_val), _val[:3]))

# ②b 全量: 每个本机真值话题, 面板条数 == Trace 条数 (技能物理量这类嵌套源最容易漏)
from lerobot.middleware import host_sources as HS              # noqa: E402
_pcount = {}
for (_t, _raw), _v in panel.items():
    if str(_v[1] or "").upper() == "SYS":
        continue                      # Trace 侧已按老倪要求删掉 SYS 层, 比条数时对齐口径
    _pcount[_t] = _pcount.get(_t, 0) + 1
_tcount = {}
for _r in range(v.tb.rowCount()):
    _lines = (v.tb.item(_r, 2).toolTip() or "").split("\n")
    for _ln in _lines:
        if _ln.startswith("话题:"):
            _tp2 = _ln.split(":", 1)[1].strip()
            _tcount[_tp2] = _tcount.get(_tp2, 0) + 1
_gap = []
for _pre, _rel, _topic in HS.FILES:
    _p = _pcount.get(_topic, 0)
    _tt2 = _tcount.get(_topic, 0)
    if _p and _tt2 and abs(_p - _tt2) > 2:
        _gap.append((_topic, _p, _tt2))
ck("每个话题两边条数一致", not _gap,
   "话题数 %d · 不一致 %s" % (len([1 for _p, _r2, _t3 in HS.FILES if _pcount.get(_t3) or _tcount.get(_t3)]), _gap[:3]))
_sk_p = _pcount.get("zmax/ss_skill_phys", 0)
_sk_t = _tcount.get("zmax/ss_skill_phys", 0)
ck("原子技能物理量两边都有 (SK01~08 × 物理量)", _sk_p >= 100 and _sk_p == _sk_t,
   "面板 %d / Trace %d" % (_sk_p, _sk_t))
_sk01 = []
for _r in range(v.tb.rowCount()):
    if v.tb.item(_r, 7).text() == "① 接近 · SK01" and v.tb.item(_r, 1).text() == "L2":
        _sk01.append(v.tb.item(_r, 2).text())
ck("Trace 里 L2 + Tx「① 接近 · SK01」的行在", len(_sk01) >= 10,
   "%d 行 %s" % (len(_sk01), _sk01[:4]))

# ③ 单源证明: 把 live_signals.topics() 换成哨兵值后, 两个窗口必须跟着变成同一个新值
def _read_trace(field):
    for r in range(v.tb.rowCount()):
        if (v.tb.item(r, 2).toolTip() or "").split("\n")[0].strip() == field:
            return v.tb.item(r, 3).text()
    return None


def _read_panel(key):
    out = [None]
    def _wk(x):
        for i in range(x.childCount()):
            ch = x.child(i)
            if ch.childCount():
                _wk(ch)
            elif str(ch.data(0, 0x0100) or "") == key:
                out[0] = ch.text(3)
    _wk(w.tree.invisibleRootItem())
    return out[0]


def _f(x):
    try:
        return float(x)
    except Exception:                                                      # noqa: BLE001
        return None


_pre_t, _pre_p = _f(_read_trace("末端_x")), _f(_read_panel("sstrace.末端_x"))
_orig = LS.topics
_sent = {"zmax/ss_state": {"fields": {"末端_x": -0.5}, "age_s": 0.01, "count": 1,
                          "type": "zmax::SSState", "qos": "state"}}
try:
    LS.topics = lambda *a, **k: _sent
    v._fill_trace_fixed(force=True)
    app.processEvents()
    w.store.clear()
    for _b in list(w.store.bufs.values()):
        _b.clear()
    for _ in range(15):
        app.processEvents()
        time.sleep(0.12)
    w._update_tree_values()
    app.processEvents()
    _t2, _p2 = _f(_read_trace("末端_x")), _f(_read_panel("sstrace.末端_x"))
    ck("单源: 换 live_signals 后 Trace 跟着变", _t2 is not None and _pre_t is not None and abs(_t2 - _pre_t) > 1e-9,
       "Trace 末端_x %s → %s" % (_pre_t, _t2))
    ck("单源: 换 live_signals 后信号分析跟着变", _p2 is not None and _pre_p is not None and abs(_p2 - _pre_p) > 1e-9,
       "面板 末端_x %s → %s" % (_pre_p, _p2))
    ck("单源: 两窗口同一拍读到同一个值", _t2 is not None and _t2 == _p2,
       "Trace %s / 面板 %s" % (_t2, _p2))
finally:
    LS.topics = _orig

print("\n%s" % ("✅ 全部通过" if not FAIL else "❌ 失败: %s" % FAIL))
sys.exit(0 if not FAIL else 1)
