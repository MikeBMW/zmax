#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_calib_measure.py — 右侧栏「📏 测量(只留数据总线)」+「🎛 标定(新页)」取证
老倪 (2026-10-09): 「测量类的有三行, 太多了, 只保留一行; 增加一个标定类」→ 再收紧「测量, 只保留数据总线」

① 下拉 = 4 行 (M / 测量·数据总线 / 标定 / 配置)
② 测量页只挂数据总线: bus 在面板里可见, tree/ss_tree **对象仍在**(没删)但不占面板
③ 切到测量页会刷 bus (不抛异常)
④ 标定页: 行数 == 真源 config/calib/zmax_calib.json 参数段数; 值逐条与文件一致
⑤ 未标定项 (T_base_cam/plane_z/cell_geometry) 高亮 + 给出可执行现场标定命令
⑥ 标定页是只读 (没有写按钮) + 复制/真源路径可用
"""
import os
import sys
import json

sys.path.insert(0, "/home/ubuntu/zmax/tools/gui")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication, QPushButton   # noqa: E402
import simulink_module as SM                            # noqa: E402
import model_tree as MT                                 # noqa: E402

ROOT = "/home/ubuntu/zmax"
CANVAS = os.path.join(ROOT, "src/lerobot/engineering/flows/state_space_obs.json")
CALIB = os.path.join(ROOT, "config/calib/zmax_calib.json")
RAW = json.load(open(CALIB, encoding="utf-8"))
SECTIONS = [k for k in RAW if not k.startswith("_")]

FAIL = []
def chk(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        FAIL.append(msg)

app = QApplication(sys.argv)
m = SM.SimulinkModule(); m.resize(2400, 1400); m.show()
m.load_flow_file(CANVAS)
app.processEvents()
d = m.model_tree

print("① 下拉 4 行")
items = [d.cmb_view.itemText(i) for i in range(d.cmb_view.count())]
chk(d.cmb_view.count() == 4, f"4 行: {items}")
chk(sum(t.startswith("📏") for t in items) == 1, "测量类只剩 1 行")
chk(sum("标定" in t for t in items) >= 1, "有标定类")

print("\n② 测量页只挂数据总线 (另两个对象保留但不上面板)")
d.cmb_view.setCurrentIndex(d.VIEW_KEYS.index("bus")); app.processEvents()
h = d  # 旧名保留: 下面统一用 d
chk(d.bus.isVisible(), "数据总线 bus 在面板可见")
chk(not d.tree.isVisible(), "数据字典 tree 不再占面板 (对象仍在: %s)" % (d.tree is not None))
chk(not d.ss_tree.isVisible(), "状态空间变量 ss_tree 不再占面板 (对象仍在: %s)" % (d.ss_tree is not None))
chk(d.measure is None, "MeasureHub 已停用 (self.measure is None), 类还在 file 里可一行复活")

print("\n③ 切到测量页真刷 bus")
_ok, _rows = True, -1
try:
    d.cmb_view.setCurrentIndex(d.VIEW_KEYS.index("mparam")); app.processEvents()
    d.cmb_view.setCurrentIndex(d.VIEW_KEYS.index("bus")); app.processEvents()
    _rows = d.bus.table.rowCount()
except Exception as ex:
    _ok = False
    print("   ⚠️", ex)
_cap = d.bus.lbl_cnt.text() if hasattr(d.bus, "lbl_cnt") else ""
chk(_ok, f"测量↔M 来回切不抛异常; bus 表行数={_rows} · 计数标签={_cap!r}")

print("\n④ 标定页 = 真源注册表逐条一致")
d.cmb_view.setCurrentIndex(d.VIEW_KEYS.index("calib")); app.processEvents()
c = d.calib
chk(c.tbl.rowCount() == len(SECTIONS), f"行数 {c.tbl.rowCount()} == 真源参数段 {len(SECTIONS)}")
keys = [c.tbl.item(r, 0).text() for r in range(c.tbl.rowCount())]
chk(keys == SECTIONS, f"参数名与文件同序: {keys}")
sv = c.tbl.item(keys.index("depth_scale"), 1).text()
chk(sv == f"{RAW['depth_scale']['value']:.4g}", f"depth_scale 值 = {sv} (文件 {RAW['depth_scale']['value']})")
tv = c.tbl.item(keys.index("control_tcp"), 1).text()
chk("verdict" not in tv and len(tv) > 0, f"control_tcp 摘要值 = {tv[:60]}")
chk("zmax_calib.json" in c.lbl_src.text(), "页头标出真源路径")

print("\n⑤ 未标定项高亮 + 可执行补救命令")
uncal = [r for r in range(c.tbl.rowCount()) if "未标定" in c.tbl.item(r, 2).text()]
names = [c.tbl.item(r, 0).text() for r in uncal]
chk(set(names) == {"T_base_cam", "plane_z", "cell_geometry"}, f"未标定 3 项 = {names}")
cmd = c.lbl_cmd.text()
chk("ss_geom_calib.py" in cmd, "cell_geometry → 给 ss_geom_calib.py 零运动示教命令")
chk("board_handeye_solve.py" in cmd, "T_base_cam → 给 board_handeye_solve.py 采板命令")
chk("plane_z" in cmd, "plane_z → 给现场量取提示")
chk(len(uncal) > 0 and all(c.tbl.item(r, 2).foreground().color().name() == "#ffa657" for r in uncal),
    "未标定行真高亮 (#ffa657)")

print("\n⑥ 只读 + 复制可用")
btns = [b.text() for b in c.findChildren(QPushButton)]
chk(not any(("写" in b) or ("改" in b) for b in btns), f"标定页无写按钮 (只读): {btns}")
c._copy()
chk("zmax_calib.json" in QApplication.clipboard().text() and "cell_geometry" in QApplication.clipboard().text(),
    "「📋 复制全部」把注册表+缺口写进剪贴板")

print("\n" + "═" * 60)
print("❌ 失败 %d 项" % len(FAIL) if FAIL else "✅ 全部通过 — 测量只挂数据总线 + 标定页数据来自真源注册表")
sys.stdout.flush()
os._exit(1 if FAIL else 0)
