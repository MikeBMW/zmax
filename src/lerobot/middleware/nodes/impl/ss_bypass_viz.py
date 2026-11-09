# -*- coding: utf-8 -*-
"""ss_bypass_viz — 节点实现正文 (文件名 = 画布节点: ss_bypass_viz)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_ss_bypass_viz   ·   registry key: ss_bypass_viz
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
from .shared_runtime import (  # noqa: F401
    _gui_host_ok,
)

def node_ss_bypass_viz(ctx):
    """📈 旁路实时可视化 (可视化层观察器) — 当前阶段 / 残差 / 接触概率 曲线 (500ms 实时刷新)

    🪟 无窗档 (常驻循环/CLI): 只推进数据, 不开窗 —— 建窗会让 Qt ABRT 打死整个 canvas loop。"""
    log = ctx.get("log")
    module = ctx.get("module")
    if not _gui_host_ok():
        if log:
            log("📈 旁路实时可视化: 无窗档 (常驻循环/CLI) ⇒ 本拍只跑数据, 不开窗")
        return True
    try:
        import ss_bypass_view                      # 同目录 (tools/gui)
        win = getattr(module, "_bypass_view_win", None) if module is not None else None
        if win is None or getattr(win, "isVisible", lambda: False)() is False:
            win = ss_bypass_view.SSBypassView(module)
            if module is not None:
                try:
                    module._bypass_view_win = win
                except Exception:
                    pass
        win.show()
        win.raise_()
        win.refresh()
        if log:
            from_ = (win.labs["stage"].text(), win.labs["residual"].text(), win.labs["contact_p"].text())
            log(f"📈 旁路实时可视化: 已打开 (当前阶段={from_[0]} · 残差={from_[1]} · 接触概率={from_[2]})")
        if log:
            try:
                # 上网通道最近一次结果 (旁路调试区块) — 取用并汇报成一行 (下面终端日志口径)
                log("🛰 " + ss_bypass_view.net_channel_status_line())
            except Exception:
                pass
        return True, "旁路可视化窗口"
    except Exception as e:
        if log:
            log(f"📈 旁路可视化打开失败: {type(e).__name__}: {e}")
        return False


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_bypass_viz
