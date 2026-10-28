#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断: 两条入口打开"同一个工程", 画布为什么看起来不一样。

A 路 = 画布工具栏「🧮 状态空间」按钮  → SimulinkModule.open_state_space()
        (clear + load_flow_file(state_space_obs.json) + _relayout_row_gaps())
B 路 = 文件 → 📂 加载工程文件 / 🗂 打开总工程
        (project_file._write_canvas → flows.save_canvas() 写回唯一依据 → 重载, 无 relayout)

输出三段铁证:
  ① 内容是否同源 (samefile + canvas md5) —— 内容不同才是"两个工程"
  ② A vs B 加载后逐节点几何 (x/y/w/h) 差多少、差哪些节点
  ③ 两边各自 vs 唯一依据 JSON 里写的坐标 —— 量化"加载时界面自己改了多少"

用法:  cd /home/ubuntu/zmax && ./gui-venv311/bin/python <本脚本>
(离屏, 不碰正在跑的控制台; 只读唯一依据, 不写盘)

⚠️ 写"逐项比对"探针必看下面的 key() 与 matched 断言: 键集合不相交时, 比对会
   报出"一致 0 个 / 不一致 0 个", 看起来像"没有差异", 实际是根本没比上 (假绿)。
"""
import json
import os
import sys

ROOT = "/home/ubuntu/zmax"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # 必须在 import PyQt 之前
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from PyQt5.QtWidgets import QApplication                       # noqa: E402

app = QApplication.instance() or QApplication(sys.argv[:1])
import simulink_module as SM                                   # noqa: E402
import project_file as _pj                                     # noqa: E402

flows = _pj._flows()
CANVAS = flows.canvas_path()                    # 工程文件写回的那份
BTN = SM._flows_path("state_space_obs.json")    # 按钮读的那份

print("① 内容同源?")
print("   工程加载写: %s" % CANVAS)
print("   按钮路读:   %s" % BTN)
same = False
try:
    same = os.path.samefile(CANVAS, BTN)
except OSError:
    same = False
print("   os.path.samefile = %s  (False ⇒ 真的是两份文件, 先去查软链/唯一依据)" % same)

src = json.load(open(CANVAS, encoding="utf-8"))

def key(n):
    """统一键: 优先 name。用 id 做键会在"文件里 id 非空、内存里 id 被重编"时两边错开。"""
    return str(n.get("name") or n.get("id") or "")


def geo(items):
    out = {}
    for n in items:
        if n.get("type") in ("bg", "row_bg"):       # 背景行条不算节点
            continue
        out[key(n)] = (round(float(n.get("x", 0)), 1), round(float(n.get("y", 0)), 1),
                       round(float(n.get("w", 0)), 1), round(float(n.get("h", 0)), 1))
    return out

json_geo = geo(src.get("nodes", []))
print("   唯一依据: %d 节点 / %d 连线" % (len(json_geo), len(src.get("links") or [])))

print("\n② 两条入口各加载一次")
mA = SM.SimulinkModule()
mA.open_state_space()                            # A 路 (按钮, 含 relayout)
gA = geo(mA.nodes)
mB = SM.SimulinkModule()
mB.clear()
mB.load_flow_file(CANVAS, confirm=False)         # B 路 (工程加载后重载, 无 relayout)
gB = geo(mB.nodes)
print("   A(🧮 状态空间按钮) %d 节点 · B(📂 加载工程文件) %d 节点" % (len(gA), len(gB)))

# ⚠️ 假绿闸: 键集合不相交时下面全是 0, 会被误读成"一致"
common = set(gA) & set(gB)
assert common, "两边键集合不相交 (id/name 口径不一致) —— 比对无效, 先统一 key()"
print("   键交集 %d / %d —— 低于任一边条数就说明有节点没比上" % (len(common), min(len(gA), len(gB))))

diff = [k for k in common if gA[k] != gB[k]]
moved_vs_json = {nm: [k for k in g if k in json_geo and g[k] != json_geo[k]] for nm, g in (("A", gA), ("B", gB))}

print("\n③ 结论")
print("   A vs B 几何差: %d/%d 个节点不一致" % (len(diff), len(common)))
for k in diff[:10]:
    print("     %-30s A%s  B%s" % (k[:30], gA[k], gB[k]))
for nm, mv in moved_vs_json.items():
    print("   %s 被界面改动过: %d/%d" % (nm, len(mv), len(
        [k for k in (gA if nm == "A" else gB) if k in json_geo])))
for nm, mv in moved_vs_json.items():
    for k in mv[:4]:
        g = (gA if nm == "A" else gB)[k]
        print("     %s %-28s 文件%s → 界面%s" % (nm, k[:28], json_geo[k], g))

print("\nRESULT %s" % ("A != B ⇒ 差异来自'加载后处理不一致' (含 _relayout_row_gaps), 不是两个工程"
                        if diff else "A == B ⇒ 画布几何一致, 差异在别处 (回填范围/右尸栏/档位/标定)"))
