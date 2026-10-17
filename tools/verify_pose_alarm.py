# -*- coding: utf-8 -*-
"""判据: ① 信号分析有「变化率」列且在变 ② SK01~08 位姿与 3D 场景一致
       ③ 不一致时全局数据空间 QoS 报警真的会亮 (用注入错误值验证, 不靠嘴)

老倪 2026-10-17: 「L2 原子技能 SK01~SK08, 每个发出的信号, 尤其是位姿 x y z a b c, 结合 3D 插拔场景,
   一个一个的检查, 每个信号我都要在信号分析看到变化率, 每个信号如果与 3D 动画不符合,
   都要在全局数据空间 QoS 报警」
"""
import copy
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
os.environ.setdefault("DISPLAY", ":0")

FAIL = []


def ck(name, ok, info=""):
    print(("%s %s" % ("✅" if ok else "❌", name)) + ((" · " + str(info)) if info else ""))
    if not ok:
        FAIL.append(name)


from PyQt5.QtWidgets import QApplication                          # noqa: E402

app = QApplication.instance() or QApplication([])
from lerobot.middleware import pose_check as PC                    # noqa: E402

LIVE = os.path.join(ROOT, "zmax_data", "ss_live")


def load(n):
    with open(os.path.join(LIVE, n), encoding="utf-8") as f:
        return json.load(f)


# ① 变化率列
from canoe_graphic import CanoeGraphicWidget                       # noqa: E402

w = CanoeGraphicWidget()
w.show()
t0 = time.time()
while time.time() - t0 < 3.5:
    app.processEvents()
    time.sleep(0.05)
_hdr = [w.tree.headerItem().text(i).split(" ▾")[0] for i in range(w.tree.columnCount())]
ck("信号分析有 Rate 列", "Rate" in _hdr, _hdr)


def _row(key):
    out = [None]

    def _wk(x):
        for i in range(x.childCount()):
            ch = x.child(i)
            if ch.childCount():
                _wk(ch)
            elif str(ch.data(0, 0x0100) or "") == key and out[0] is None:
                out[0] = (ch.text(3), ch.text(4))
    _wk(w.tree.invisibleRootItem())
    return out[0]


_k = "skillphys.SK01 接近 · x 位置 mm"
_a = _row(_k)
t = time.time()
while time.time() - t < 2.0:
    app.processEvents()
    time.sleep(0.05)
_b = _row(_k)
ck("Rate 有值且在变", bool(_a) and bool(_b) and _a[1] not in ("-", "", None)
   and _a != _b, "%s → %s" % (_a, _b))

# ② 现场数据: 位置三轴与场景一致 (fail=0)
tl, sp = load("trace_live.json"), load("skill_phys.json")
_al = PC.check(tl, sp, tol_mm=5.0)
_fail = [a for a in _al if a[0] == "fail"]
ck("SK01~08 位置与 3D 场景一致 (无 fail)", not _fail, _fail[:2])
_sk = [k for k in (sp.get("skills") or {}) if str(k).startswith("SK")]
ck("SK01~08 都有 x/y/z/a/b/c 字段", len(_sk) >= 8 and all(
    all(k2 in (sp["skills"][c] or {}) for k2 in ("x", "y", "z", "a", "b", "c")) for c in _sk),
   "%d 个技能" % len(_sk))
ck("姿态不可观测时有 warn (不伪造)", any(a[0] == "warn" and "姿态" in a[1] for a in _al),
   [a[1] for a in _al if a[0] == "warn"][:2])

# ③ 注入错误值 ⇒ 必须报警
_bad = copy.deepcopy(sp)
_bad["skills"]["SK04"]["x"] = float((tl.get("末端_x") or 0) * 1000.0) + 25.0
_al2 = PC.check(tl, _bad, tol_mm=5.0)
_hit = [a for a in _al2 if a[0] == "fail" and "SK04" in a[1] and "· x" in a[1]]
ck("注入 +25mm 偏差 ⇒ QoS fail 报警", bool(_hit), _hit[:1])

# 真界面的 QoS 告警表里能看到这条通道
import dds_canoe                                                # noqa: E402
v = dds_canoe.build_view(standalone=True)
v._fill_trace_fixed(force=True)
v._fill_alerts()
app.processEvents()
_rows = []
for r in range(v.tb_alert.rowCount()):
    _rows.append(" | ".join(v.tb_alert.item(r, c).text() if v.tb_alert.item(r, c) else ""
                            for c in range(v.tb_alert.columnCount())))
ck("全局数据空间告警表里真出现姿态判据", any("姿态" in x for x in _rows),
   "告警 %d 行, 例 %s" % (len(_rows), [x[:60] for x in _rows[:2]]))

print("\n%s" % ("✅ 全部通过" if not FAIL else "❌ 失败: %s" % FAIL))
sys.exit(0 if not FAIL else 1)
