#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_entries_cleanup.py — 「INTACT机器人 / 数据闭环引导 / 数据闭环控制台」三入口体检 + 死面板删除验证
(老倪 2026-10-09: 「你觉得有必要保留么？没用就删掉」)

要证的事:
 ① 三个入口: 两个保留的真功能**真能打开**(🤖机器人切换面板 / 🎯数据闭环控制台 6环节), 一个(引导)已挪进面板内
 ② 死块确已删: CICDPanel/CICDStageItem/CICDLinkItem/open_cicd_panel 全没了, 且 `_cicd_panel` 引用清零
 ③ 6 环节能力没丢: module.on_collect/on_train/on_validate/on_integrate/on_deploy/on_infer 六个真处理函数都在
 ④ 引导按钮在面板里, 点击 → 教程真起来 (金色高亮 + 日志), 能 cleanup
 ⑤ 工具栏回归: btn_run/btn_step/btn_run_cfg/6 个开关(已归右侧页) 都还在
"""
import os
import sys

sys.path.insert(0, "/home/ubuntu/zmax/tools/gui")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication, QDialog, QLabel, QWidget  # noqa: E402

app = QApplication(sys.argv)
import simulink_module as SM  # noqa: E402

FAIL = []


def chk(cond, msg):
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        FAIL.append(msg)


m = SM.SimulinkModule()
m.resize(2200, 1300)
m.show()
app.processEvents()

print("① 三个入口按钮")
chk(not isinstance(getattr(m, "btn_intact_robot", None), QWidget), "🤖 INTACT机器人 按钮已删 (能力在画布节点双击 11798)")
chk(not isinstance(getattr(m, "btn_pipeline", None), QWidget), "🎯 数据闭环控制台 按钮已删 (入口改 Ctrl+Alt+P)")
chk(not hasattr(m, "btn_tutorial"), "🧭 数据闭环引导 已从工具栏摘除")

print("\n② 死块已删")
import pathlib
src = pathlib.Path("/home/ubuntu/zmax/tools/gui/simulink_module.py").read_text(encoding="utf-8")
for dead in ("class CICDPanel", "class CICDStageItem", "class CICDLinkItem",
             "def open_cicd_panel", "_cicd_panel"):
    chk(src.count(dead) == 0, f"源码不含 {dead}")
chk(src.count("class CICDWorker") == 1, "CICDWorker 保留 (PipelinePanel/训练仍在用)")

print("\n③ 6 环节处理函数仍在 (画布 CICD 节点双击走它们)")
for fn in ("on_collect", "on_train", "on_validate", "on_integrate", "on_deploy", "on_infer"):
    chk(callable(getattr(m, fn, None)), f"module.{fn} 存在")

print("\n④ 🎯 控制台真能开 + 引导在面板里")
m.open_pipeline_panel()   # 按钮已删 → 直调 (菜单/快捷键走它)
app.processEvents()
p = getattr(m, "_pipeline_panel", None)
chk(isinstance(p, QDialog), f"面板打开: {type(p).__name__ if p else None} · {p.windowTitle() if p else ''}")
chk(len(getattr(p, "_pipe_btns", {})) == 6, f"6 环节按钮: {list(getattr(p, '_pipe_btns', {}).keys())}")
chk(getattr(p, "btn_guide", None) is not None, "面板内有「🧭 引导 (分步高亮)」按钮")
p.btn_guide.click()
app.processEvents()
chk(getattr(m, "_tutorial_active", False) is True, "点引导 → 教程真的起来了")
chk(getattr(m, "_tutorial_hl", None) is not None, f"金色高亮已落在: {type(getattr(m,'_tutorial_hl',None)).__name__}")
for _ in range(2):
    m._tutorial_next()
    app.processEvents()
st = getattr(m, "_tutorial_step", None)
chk(isinstance(st, int) and st >= 2, f"能逐步推进 (当前步={st})")
m._tutorial_cleanup()
chk(getattr(m, "_tutorial_hl", None) is None, "cleanup 后高亮清除")
p.close()

print("\n⑤ 🤖 INTACT机器人 切换面板真能开")
m._open_intact_robot_panel()   # 按钮已删 → 直调 (画布节点双击走它)
app.processEvents()
dlg = getattr(m, "_intact_robot_dlg", None)
chk(dlg is not None, f"面板对象: {type(dlg).__name__ if dlg else None}")
if dlg is not None:
    txt = " ".join(x.text() for x in dlg.findChildren(QLabel))
    hits = [r for r in ("reacher", "pusht", "cube", "tworoom") if r in txt.lower()]
    chk(len(hits) >= 1, f"列出原项目机器人: {hits} (INTACT 上游只有 reacher ⇒ 1 个就是对)")
    chk(not dlg.isModal(), "非模态 (不挡画布操作)")
    dlg.close()

print("\n⑥ 工具栏回归")
for a in ("btn_run", "btn_step", "btn_restart", "btn_run_cfg"):
    w = getattr(m, a, None)
    chk(w is not None and (not hasattr(w, "isVisible") or w.parent() is not None), f"{a} 在位")
for a in ("chk_engine_demo", "chk_l3_full", "chk_mani_yaw", "chk_intact_exec", "chk_l4_dit", "chk_l2_compat"):
    chk(getattr(m, a, None) is not None, f"{a} 仍在 (已在右侧配置页)")

print("\n" + "═" * 58)
print(("❌ 失败 %d 项" % len(FAIL)) if FAIL else "✅ 全部通过")
sys.exit(3 if FAIL else 0)
