# -*- coding: utf-8 -*-
"""ss_z700_signals — 节点实现正文 (文件名 = 画布节点: ss_z700_signals)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_ss_z700_signals   ·   registry key: ss_z700_signals
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
from .library import (  # noqa: F401
    _gui_host_ok,
)

def node_ss_z700_signals(ctx):
    """🖥 Z700 真机信号 (可视化层观察器) — 输入 = 🌍 物理世界 输出; 显示全部真机信号
    (TCP 位姿+四元数 / 六关节位置速度 / 六维力力矩 / 夹爪 / 触觉 / 机器人状态 / 产线阶段)"""
    log = ctx.get("log")
    module = ctx.get("module")
    if not _gui_host_ok():
        # 🪟 2026-11-01: 本节点本就是"显示层", 但常驻循环没有 QApplication/不在主线程 ⇒
        #   在这里建窗会让 Qt 直接 ABRT 打死整个 canvas loop (faulthandler 实测: 本行 → ss_bypass_view:1370)
        if log:
            log("🖥 Z700 真机信号: 无窗档 (常驻循环/CLI) ⇒ 本拍只跑数据, 不开窗")
        return True, "Z700 真机信号 (无窗档)"
    try:
        import ss_bypass_view
        win = getattr(module, "_z700_signals_win", None) if module is not None else None
        if win is None or getattr(win, "isVisible", lambda: False)() is False:
            win = ss_bypass_view.Z700SignalsView(module)
            if module is not None:
                try:
                    module._z700_signals_win = win
                except Exception:
                    pass
        win.show()
        win.raise_()
        win.refresh()
        if log:
            log(f"🖥 Z700 真机信号: 已打开 (TCP={win.labs['tcp_x'].text()},{win.labs['tcp_y'].text()},"
                f"{win.labs['tcp_z'].text()} · 运行={win.labs['s_op'].text()} · "
                f"旁路阶段={win.labs['b_stage'].text()})")
        return True, "Z700 真机信号窗口"
    except Exception as e:
        if log:
            log(f"🖥 Z700 真机信号打开失败: {type(e).__name__}: {e}")
        return False


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_z700_signals
