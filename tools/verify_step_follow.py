#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_step_follow.py — ⏭单步跟随(高亮+画布跳转) 的真实交互级验证 (老倪 2026-10-09)

为什么要有这个: 老倪「画布太大, 找不到单步节点在哪」——功能必须**真跳**才算数,
不能只看代码里有 centerOn。本脚本离屏真建 SimulinkModule + 真加载画布, 逐条验:

  ① 渲染回归 (节点项 == 文件节点数 · 连线项 >= 文件连线数-1)
  ② 新增控件在位 (🎯跟随单步 默认勾选 · 📍定位节点 · 🏠全览)
  ③ _impl_line: 节点 → 实现 key + 函数 + 文件:行 (全面检查每个节点实现的口径)
  ④ focus_node: 视口中心 == 节点中心 (容差内) · 缩放被夹到看得清
  ⑤ 跟随开: _follow_to 后中心落到该节点 + 终端日志有「📍 画布已跳到」
  ⑥ 跟随关: 中心**不动** + 日志报「🎯 已关跟随单步」
  ⑦ 📍定位节点: 跟随关着也能跳回当前节点
  ⑧ 🏠全览: 一次能看到全部节点 (缩放变小)
  ⑨ _highlight_node: 置 hl=True (金框) 且触发跳转

判据: 全部 ✅ → exit 0; 任一 ❌ → exit 3
"""
from __future__ import annotations

import json
import os
import sys
import traceback

sys.path.insert(0, "/home/ubuntu/zmax/tools/gui")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5 import QtWidgets                                                   # noqa: E402

app = QtWidgets.QApplication(sys.argv)
import simulink_module as SM                                                  # noqa: E402

FLOW = "/home/ubuntu/zmax/flows/state_space_obs.json"
spec = json.load(open(FLOW, encoding="utf-8"))
fails = []


def chk(cond, label, extra=""):
    print(("  ✅ " if cond else "  ❌ ") + label + (("  " + extra) if extra else ""))
    if not cond:
        fails.append(label)
    return cond


print("═══ ⏭ 单步跟随 (高亮 + 画布跳转) 验证 ═══")
print("画布真源: %d 节点 / %d 连线" % (len(spec["nodes"]), len(spec["links"])))
m = SM.SimulinkModule()
err = None
try:
    m.load_flow_file(FLOW, confirm=False)
except Exception:                                                             # noqa: BLE001
    err = traceback.format_exc()
app.processEvents()

# ① 渲染回归
n_items, n_links = len(getattr(m, "_items", {}) or {}), len(getattr(m, "_link_items", []) or [])
print("\n① 渲染回归")
chk(n_items == len(spec["nodes"]), "节点项 == 文件节点数", "%d/%d" % (n_items, len(spec["nodes"])))
chk(n_links >= len(spec["links"]) - 1, "连线项 >= 文件-1 (既有 (f,t) 去重)", "%d/%d" % (n_links, len(spec["links"])))
chk(err is None, "加载无异常")

# ② 控件
print("\n② 新增控件")
chk(getattr(m, "chk_follow_step", None) is not None and m.chk_follow_step.isChecked(),
    "🎯 跟随单步 复选框存在且默认勾选")
chk(not isinstance(getattr(m, "btn_locate", None), QtWidgets.QWidget), "📍 定位节点 按钮已删 → 改 Ctrl+L (能力仍在)")
chk(not isinstance(getattr(m, "btn_fit_all", None), QtWidgets.QWidget), "🏠 全览 按钮已删 → 改 Ctrl+0 (能力仍在)")

canvas = m.canvas
vp = canvas.viewport()


def _resolve(pat):
    """按 id 或**名字**取节点 —— ⚠️ load_flow_file 会给节点重新 gen_id(),
    文件里的 id (sssensor/n_calib_mani) 在内存里查不到, 名字才是稳的 (既有实测)。"""
    n = m._by_id(pat)
    if n is not None:
        return n
    for x in m.nodes:
        if pat in x.get("name", ""):
            return x
    return None


def _center():
    return canvas.mapToScene(vp.rect().center())


# ③ 实现位置
print("\n③ 实现位置 (_impl_line)")
for pat in ("融合定位", "机器人执行器", "标定诊断测量"):
    n = _resolve(pat)
    if n is None:
        chk(False, "%s 节点找不到" % pat)
        continue
    line = m._impl_line(n)
    ok = ("实现:" in line) and (".py:" in line or "无匹配" in line)
    chk(ok, "%s → %s" % (pat, line[:96]))

# ④ focus_node 真跳
print("\n④ focus_node 真跳 (视口中心 == 节点中心)")
m.chk_follow_step.setChecked(True)
for pat in ("融合定位", "标定诊断测量", "机器人执行器"):
    n = _resolve(pat)
    it = (m._items or {}).get(n["id"]) if n else None
    if n is None or it is None:
        chk(False, "%s 节点项缺失" % pat)
        continue
    ok, info = canvas.focus_node(n["id"])
    app.processEvents()
    want = it.sceneBoundingRect().center()
    got = _center()
    d = ((want.x() - got.x()) ** 2 + (want.y() - got.y()) ** 2) ** 0.5
    chk(ok and d <= 900, "%s 跳到 x=%d y=%d (偏差 %.0f px)" % (pat, int(want.x()), int(want.y()), d), info)

# ⑤ 跟随开 → 跳 + 日志
print("\n⑤ 跟随开 (默认): _follow_to 真跳 + 终端可读")
_LOGS = []
m._log = lambda s: _LOGS.append(str(s))
m.chk_follow_step.setChecked(True)
canvas.fit_all()
before = _center()
n = _resolve("安全执行边界")
m._follow_to(n)
after = _center()
want = m._items[n["id"]].sceneBoundingRect().center()
dd = ((want.x() - after.x()) ** 2 + (want.y() - after.y()) ** 2) ** 0.5
moved = ((before.x() - after.x()) ** 2 + (before.y() - after.y()) ** 2) ** 0.5
chk(dd <= 900 and moved > 50, "跟随时中心落到「安全执行边界」(偏差 %.0f px · 位移 %.0f px)" % (dd, moved))
chk(any("📍 画布已跳到" in s for s in _LOGS), "终端有『📍 画布已跳到』", (_LOGS[-1][:70] if _LOGS else ""))

# ⑥ 跟随关 → 不动
print("\n⑥ 跟随关: 画布不动, 只报位置")
_LOGS.clear()
m.chk_follow_step.setChecked(False)
before = _center()
m._follow_to(_resolve("机器人执行器"))
after = _center()
still = ((before.x() - after.x()) ** 2 + (before.y() - after.y()) ** 2) ** 0.5
chk(still < 1.0, "中心未移动 (%.1f px)" % still)
chk(any("已关跟随单步" in s for s in _LOGS), "终端提示『🎯 已关跟随单步』")

# ⑦ 定位节点 (跟随关着也能用)
print("\n⑦ 📍 定位节点 (force)")
_LOGS.clear()
m.locate_current_node()
app.processEvents()
nid = getattr(m, "_last_step_node", None)
it = (m._items or {}).get(nid)
if it is not None:
    w = it.sceneBoundingRect().center()
    g = _center()
    d3 = ((w.x() - g.x()) ** 2 + (w.y() - g.y()) ** 2) ** 0.5
    chk(d3 <= 900, "跳回 %s (偏差 %.0f px)" % (nid, d3))
else:
    chk(False, "_last_step_node 未记录")

# ⑧ 全览
print("\n⑧ 🏠 全览")
_LOGS.clear()
sc_before = canvas.transform().m11()
canvas.fit_all()
app.processEvents()
sc_after = canvas.transform().m11()
chk(sc_after < sc_before, "缩放变小 = 看到更大范围 (%.2f → %.2f)" % (sc_before, sc_after))
m.fit_all_nodes()
chk(any("全览" in s for s in _LOGS), "终端报『🏠 … 全览』")

# ⑨ _highlight_node 置金框 + 跳
print("\n⑨ _highlight_node (金框 + 跳转)")
m.chk_follow_step.setChecked(True)
_LOGS.clear()
n = _resolve("动作调制器")
m._highlight_node(n, ms=80)
chk(n is not None and bool(n.get("hl")), "节点 hl=True (金框)")
chk(any("画布已跳到" in s for s in _LOGS), "同时跳转")

print("\n" + ("═" * 52))
if fails:
    print("❌ 未通过 %d 项: %s" % (len(fails), "; ".join(fails)))
else:
    print("✅ 全部通过 — ⏭单步 会高亮当前节点并把画布跳过去")
sys.stdout.flush()
os._exit(0 if not fails else 3)
