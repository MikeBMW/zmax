# -*- coding: utf-8 -*-
"""判据: 数据空间 Trace 列口径 (删 Name / Signal 英文变量 / Time 可切绝对-相对)。

老倪 2026-10-17: 「trace窗口 删除 name 列, Signal列统一显示英文名称, 对应状态空间的实际变量信号;
   Trace Time 要可以显示跟 3D 场景一样的相对时间, 同步时间显示; 当然也可以显示绝对时间;
   要在 Time 列可以切换」
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication          # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "gui"))
from lerobot.middleware import signal_en as E     # noqa: E402

FAIL = []


def ck(name, ok, info=""):
    print(("%s %s" % ("✅" if ok else "❌", name)) + ((" · " + str(info)) if info else ""))
    if not ok:
        FAIL.append(name)


app = QApplication.instance() or QApplication([])
import dds_canoe                                   # noqa: E402

v = dds_canoe.build_view(standalone=True)
v._fill_trace_fixed(force=True)
t = v.tb
cols = [t.horizontalHeaderItem(i).text().split(" ▾")[0] for i in range(t.columnCount())]
ck("11 列且无 Name 列", t.columnCount() == 11 and "Name" not in cols, cols)
ck("Signal 列在(第3列)", cols[2] == "Signal", cols[2])
ck("默认 Time·abs", cols[0] == "Time·abs", cols[0])

def rows():
    return [[t.item(r, c).text() if t.item(r, c) else "" for c in range(t.columnCount())]
            for r in range(t.rowCount())]

r0 = rows()
sig_vals = [r[2] for r in r0 if r[2]]
ck("有数值行", len(r0) > 100, "%d 行" % len(r0))
bad = [s for s in sig_vals if re.search(r"[^\x00-\x7f]", s)]
ck("Signal 全 ASCII (英文变量名)", not bad, "非英文 %d 例: %s" % (len(bad), bad[:4]))
ck("Signal 无中文键", "末端_x" not in ",".join(sig_vals), "")

# 已知映射 (生产者代码里的真实变量)
want = {"下降·L2 力大小_mps": "descend_l2_force_mps", "接触概率": "grasp_prob",
        "势能_phi": "phi", "前向": None}
ck("映射规则: gravity", E.en_of("下降·L2 力大小_mps") == "descend_l2_force_mps",
   E.en_of("下降·L2 力大小_mps"))
ck("映射规则: 统一状态", E.en_of("末端_x") == "end_x" and E.en_of("接触概率") == "grasp_prob",
   (E.en_of("末端_x"), E.en_of("接触概率")))
ck("映射规则: 引擎", E.en_of("势能_phi") == "phi" and E.en_of("内稳态否决") == "homeo_veto",
   (E.en_of("势能_phi"), E.en_of("内稳态否决")))

# 时间: 绝对带毫秒
abs_t = r0[0][0]
ck("绝对时间 HH:MM:SS.mmm", bool(re.match(r"^\d{2}:\d{2}:\d{2}\.\d{3}$", abs_t)), abs_t)

# 切相对
v._on_hdr_click(0)
app.processEvents()
t2 = [v.tb.horizontalHeaderItem(i).text().split(" ▾")[0] for i in range(v.tb.columnCount())]
ck("点 Time 表头 → Time·rel", t2[0] == "Time·rel", t2[0])
rel_t = v.tb.item(0, 0).text() if v.tb.item(0, 0) else ""
ck("相对时间是秒(3 位小数)", bool(re.match(r"^\d+\.\d{3}$", rel_t)), rel_t)
# 与 3D 场景同一拍: 快照 时间_s
try:
    d = json.load(open(os.path.join(os.path.dirname(__file__), "..",
                                    "zmax_data/ss_live/trace_live.json"), encoding="utf-8"))
    ck("相对时间 == 3D 快照 时间_s (±0.5s)", abs(float(rel_t) - float(d.get("时间_s") or 0)) < 0.5,
       "Trace %s / 文件 %s" % (rel_t, d.get("时间_s")))
except Exception as e:                                   # noqa: BLE001
    ck("相对时间与快照同源", False, repr(e))
v._on_hdr_click(0)
app.processEvents()
ck("再点回 Time·abs", v.tb.horizontalHeaderItem(0).text().split(" ▾")[0] == "Time·abs",
   v.tb.horizontalHeaderItem(0).text())

# ⚡ 2026-10-17 老倪: 「Trace 窗口的操作, 为什么延迟这么大?」
import time as _t                                                # noqa: E402
_t0 = _t.time()
v._fill_trace_fixed()
app.processEvents()
_dt = _t.time() - _t0
ck("整表刷新 < 0.25s (原 0.62s)", _dt < 0.25, "%.2fs · %d 行" % (_dt, v.tb.rowCount()))

# 🖱 滚轮可滚 + 刷新不丢位置
from PyQt5.QtCore import QPoint, QPointF, Qt                     # noqa: E402
from PyQt5.QtGui import QWheelEvent                              # noqa: E402
_sb = v.tb.verticalScrollBar()
_vp = v.tb.viewport()
for _ in range(3):
    QApplication.sendEvent(_vp, QWheelEvent(QPointF(_vp.rect().center()),
                                            QPointF(_vp.mapToGlobal(_vp.rect().center())),
                                            QPoint(0, 0), QPoint(0, -120), Qt.NoButton,
                                            Qt.NoModifier, Qt.NoScrollPhase, False))
    app.processEvents()
ck("鼠标滚轮能上下滚", _sb.value() > 0, "滚动值 %d / 最大 %d" % (_sb.value(), _sb.maximum()))
_sb.setValue(min(40000, _sb.maximum()))
_b = _sb.value(); _topb = v.tb.rowAt(30)
v._fill_trace_fixed(); app.processEvents()
ck("刷新后滚动位置不跳", _sb.value() == _b and v.tb.rowAt(30) == _topb,
   "%d→%d 顶部行 %s→%s" % (_b, _sb.value(), _topb, v.tb.rowAt(30)))

# 🎚 列头过滤
def _vis():
    return sum(0 if v.tb.isRowHidden(r) else 1 for r in range(v.tb.rowCount()))
_tot = v.tb.rowCount()
v._tb_filters = {1: "L4"}
v._apply_col_filters()
_v4 = _vis()
ck("表头过滤 Layer=L4", 0 < _v4 < _tot, "%d → %d 行 · 表头 %s"
   % (_tot, _v4, v.tb.horizontalHeaderItem(1).text()))
_allsame = all(v.tb.isRowHidden(r) or v.tb.item(r, 1).text() == "L4" for r in range(_tot))
ck("过滤后只剩 L4", _allsame, "")
v._fill_trace_fixed(); app.processEvents()
ck("刷新后过滤仍生效", _vis() == _v4, "%d 行" % _vis())
v._tb_filters.clear(); v._apply_col_filters()
ck("清除过滤恢复全部", _vis() == _tot, "%d 行" % _vis())

print("\n%s" % ("✅ 全部通过" if not FAIL else "❌ 失败: %s" % FAIL))
sys.exit(0 if not FAIL else 1)
