#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧩 验证 L4 档「🧩 L2 兼容 (前馈 MLP + YOLO)」勾选框 (offscreen, gui-venv311)

判据 (老倪规矩: 新增控件必须 ①创建 ②挂布局 ③行为生效, 少一件都是静默失败):
  ①对象存在 + 文字 ②parent() 非空 (真挂进布局) ③与 chk_intact_exec 同一工具栏 (同排)
  ④默认勾选 ⑤tooltip 写明实测代价与等效环境变量 ⑥点击可切换 (行为生效)
  ⑦装配块静态连线: 源码里读了控件状态 + 该状态参与了 _l2_compat 判定
用法: QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/verify_l2_compat_checkbox.py
"""
from __future__ import annotations

import inspect
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "tools", "gui"), os.path.join(ROOT, "tools"),
                os.path.join(ROOT, "src")]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
import simulink_module as sm  # noqa: E402

ok = True


def chk(name, cond, extra=""):
    global ok
    print(f"  {'✅' if cond else '❌'} {name}{(' · ' + extra) if extra else ''}")
    ok &= bool(cond)


m = sm.SimulinkModule()
cb = getattr(m, "chk_l2_compat", None)
chk("① 勾选框存在", cb is not None)
if cb is not None:
    chk("① 文字 = 🧩 L2 兼容 (前馈 MLP + YOLO)", cb.text() == "🧩 L2 兼容 (前馈 MLP + YOLO)",
        repr(cb.text()))
    chk("② 已挂进布局 (parent 非空)", cb.parent() is not None,
        type(cb.parent()).__name__ if cb.parent() is not None else "None")
    # ⚙️ 2026-10-09 老倪: 6 个运行开关已从画布工具栏**搬进**右侧「🔧 配置 · 运行开关」页
    #   ⇒ 判据改为: 两者仍落在**同一个页面容器** (每行有各自的行容器 ⇒ 不比较 parent 相等),
    #      且确实是 re-parent 的同一个对象 (引擎读 self.chk_* 零改动)
    def _page_of(w):
        _p, _dep = w, 0
        try:
            import model_tree as _MT
        except Exception:
            return None
        while _p is not None and _dep < 12:
            if isinstance(_p, _MT.RunConfigWidget):
                return _p
            _p = _p.parent()
            _dep += 1
        return None

    _pg1, _pg2 = _page_of(cb), _page_of(getattr(m, "chk_intact_exec"))
    chk("③ 与 chk_intact_exec 同一页面容器", _pg1 is not None and _pg1 is _pg2,
        type(_pg1).__name__ if _pg1 is not None else "None")
    _d = getattr(m, "model_tree", None)
    _in2 = _d is not None and _d.run_cfg is _pg1
    chk("③b 已归位到右侧「配置 · 运行开关」页", _in2)
    chk("③c 同一对象 (re-parent, 引擎读 self.chk_* 零改动)",
        _d is not None and _d.run_cfg._cks.get("chk_l2_compat") is cb)
    chk("④ 默认勾选", cb.isChecked())
    tt = cb.toolTip() or ""
    chk("⑤ tooltip 写明实测代价", ("6.82" in tt) and ("0.42" in tt) and ("SS_L4_L2_COMPAT" in tt),
        f"{len(tt)} 字符")
    cb.setChecked(False)
    chk("⑥ 取消勾选后状态可读 False", cb.isChecked() is False)
    cb.setChecked(True)
    chk("⑥ 重新勾选后状态可读 True", cb.isChecked() is True)

src = inspect.getsource(sm.SimulinkModule)
chk("⑦ 装配块读了控件状态", 'getattr(self, "chk_l2_compat", None)' in src)
chk("⑦ 状态参与 _l2_compat 判定", "_l2_compat_on\n" in src or "_l2_compat_on," in src
    or "and self._l2_compat_on" in src)
chk("⑦ 判定仍受环境变量总开关约束", 'os.environ.get("SS_L4_L2_COMPAT", "1") != "0"' in src)

print(f"\n结论: {'全部通过 ✅' if ok else '有判据未过 ❌'}")
sys.exit(0 if ok else 1)
