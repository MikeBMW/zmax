"""aoi_pose_guide_dialog.py — 🎯 AOI 3D 位姿引导 (光学质量检测节点右键入口)。

为什么单独一个文件: simulink_module.py 已有 113 万字符, 往里塞 UI 大段代码风险高;
这里只暴露 open_pose_guide(parent, module) 一个入口, 由节点右键调用。

链路
    读 TCP 真值(tcp_out/latest.json, 全 0 视为陈旧)
      → POST 127.0.0.1:8795/api/aoi/gold_guide {mode, pose, axis}
      → 8795 内部: 10082 capture_detect + picture → 19 根定位 → 偏差 → 毫米 → 目标位姿
      → 本对话框显示, **不下发运动**(下发由 8797 授权链负责)

三种 mode 的现场含义
    auto   有标定直接算目标位姿; 没标定返回 probe(走 2mm 试探)
    probe  强制只给 2mm 试探
    solve  用上一次试探的前后画面差, 反算 mm/px 与轴符号, 写入标定
"""
from __future__ import annotations

import json
import os
import urllib.request

from PyQt5 import QtCore, QtWidgets

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TCP_JSON = os.path.join(REPO, "zmax_data", "rokae_sdk", "tcp_out", "latest.json")
GUIDE = "http://127.0.0.1:8795"


def _tcp_pose():
    """读 TCP 真值(mm)。返回 (pose_dict|None, note)。"""
    try:
        with open(TCP_JSON, encoding="utf-8") as fh:
            d = json.load(fh)
    except Exception as e:                                                # noqa: BLE001
        return None, "读 TCP 失败: %s" % e
    try:
        x, y, z = float(d["x"]) * 1000.0, float(d["y"]) * 1000.0, float(d["z"]) * 1000.0
    except Exception:                                                     # noqa: BLE001
        return None, "TCP 字段缺失"
    if abs(x) < 1e-6 and abs(y) < 1e-6 and abs(z) < 1e-6:
        return None, "TCP 全 0 ⇒ 陈旧, 先在 8797 确认真值"
    pose = {"x": round(x, 3), "y": round(y, 3), "z": round(z, 3)}
    for k in ("rx", "ry", "rz", "a", "b", "c"):
        if k in d:
            pose[k] = d[k]
    return pose, "ts=%.1f" % float(d.get("ts") or 0)


def _post(path, payload, timeout=60):
    req = urllib.request.Request(
        GUIDE + path, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace") or "{}")


class PoseGuideDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, module=None):
        super().__init__(parent)
        self.setWindowTitle("🎯 AOI 3D 位姿引导 · 金手指居中")
        self.resize(760, 520)
        self.module = module
        self._build()
        self.refresh()

    def _build(self):
        v = QtWidgets.QVBoxLayout(self)
        top = QtWidgets.QHBoxLayout()
        self.lbl_tcp = QtWidgets.QLabel("TCP: —")
        self.lbl_tcp.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        top.addWidget(self.lbl_tcp, 1)
        self.spin_tp = QtWidgets.QSpinBox()
        self.spin_tp.setRange(0, 4000)
        self.spin_tp.setValue(0)
        self.spin_tp.setToolTip("目标画面 x(px)。0 = 用图宽中心")
        top.addWidget(QtWidgets.QLabel("目标 x(px)"))
        top.addWidget(self.spin_tp)
        self.cmb_axis = QtWidgets.QComboBox()
        self.cmb_axis.addItems(["Y", "X", "Z"])
        top.addWidget(QtWidgets.QLabel("补偿轴"))
        top.addWidget(self.cmb_axis)
        v.addLayout(top)

        self.txt = QtWidgets.QPlainTextEdit()
        self.txt.setReadOnly(True)
        self.txt.setStyleSheet("font-family: monospace; font-size: 12px;")
        v.addWidget(self.txt, 1)

        row = QtWidgets.QHBoxLayout()
        self.b_auto = QtWidgets.QPushButton("▶ 测量并给位姿 (auto)")
        self.b_probe = QtWidgets.QPushButton("① 试探 2mm (probe)")
        self.b_solve = QtWidgets.QPushButton("② 走完 → 反算标定 (solve)")
        self.b_copy = QtWidgets.QPushButton("📋 复制目标位姿")
        self.b_cal = QtWidgets.QPushButton("标定值")
        for b in (self.b_auto, self.b_probe, self.b_solve, self.b_copy, self.b_cal):
            row.addWidget(b)
        v.addLayout(row)

        self.b_auto.clicked.connect(lambda: self.call("auto"))
        self.b_probe.clicked.connect(lambda: self.call("probe"))
        self.b_solve.clicked.connect(self.solve)
        self.b_copy.clicked.connect(self.copy_pose)
        self.b_cal.clicked.connect(self.show_calib)

        self.hint = QtWidgets.QLabel("")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color:#888;")
        v.addWidget(self.hint)

    # ── 数据 ──
    def refresh(self):
        p, note = _tcp_pose()
        self._pose = p
        self.lbl_tcp.setText("TCP: %s   (%s)" % (
            "x=%.2f y=%.2f z=%.2f mm" % (p["x"], p["y"], p["z"]) if p else "不可用", note))

    def call(self, mode):
        self.refresh()
        if not self._pose:
            QtWidgets.QMessageBox.warning(self, "没有 TCP 真值",
                                          "读不到当前 TCP, 无法算目标位姿。\n先确认 8797 真值在刷新。")
            return
        self.txt.setPlainText("请求中 (10082 触发检测 + 取图 + 19 根定位, 约 2~6 s) ...")
        QtWidgets.QApplication.processEvents()
        try:
            d = _post("/api/aoi/gold_guide", {
                "mode": mode, "axis": self.cmb_axis.currentText(),
                "pose": self._pose, "target_px": self.spin_tp.value()})
        except Exception as e:                                            # noqa: BLE001
            self.txt.setPlainText("调用失败: %s: %s\n\n8795 起了吗? gui-venv311/bin/python tools/aoi_pose_guide.py" % (type(e).__name__, e))
            return
        self._last = d
        self.txt.setPlainText(json.dumps(d, ensure_ascii=False, indent=1))
        m = d.get("measure") or {}
        self.hint.setText(
            "act=%s  n=%s  center=%s  off=%s px  d=%s mm  →  %s"
            % (d.get("act"), m.get("n"), m.get("center_px"), d.get("off_px"),
               d.get("d_mm"), d.get("note") or ""))

    def solve(self):
        self.refresh()
        try:
            d = _post("/api/aoi/guide/solve", {"pose": self._pose or {},
                                               "axis": self.cmb_axis.currentText()})
        except Exception as e:                                            # noqa: BLE001
            self.txt.setPlainText("solve 失败: %s: %s" % (type(e).__name__, e))
            return
        self.txt.setPlainText(json.dumps(d, ensure_ascii=False, indent=1))
        self.hint.setText(d.get("msg") or "")

    def copy_pose(self):
        d = getattr(self, "_last", None) or {}
        p = d.get("pose_target")
        if not p:
            self.hint.setText("还没有目标位姿, 先点「测量并给位姿」")
            return
        s = "x=%.3f y=%.3f z=%.3f" % (float(p.get("x", 0)), float(p.get("y", 0)), float(p.get("z", 0)))
        QtWidgets.QApplication.clipboard().setText(s)
        self.hint.setText("已复制: " + s)

    def show_calib(self):
        try:
            with urllib.request.urlopen(GUIDE + "/api/aoi/guide/calib", timeout=10) as r:
                d = json.loads(r.read().decode("utf-8", "replace") or "{}")
        except Exception as e:                                            # noqa: BLE001
            self.txt.setPlainText("读标定失败: %s" % e)
            return
        self.txt.setPlainText(json.dumps(d, ensure_ascii=False, indent=1))


def open_pose_guide(parent=None, module=None):
    dlg = PoseGuideDialog(parent=parent, module=module)
    dlg.show()
    return dlg
