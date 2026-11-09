# -*- coding: utf-8 -*-
"""ss_ff_hist — 节点实现正文 (文件名 = 画布节点: ss_ff_hist)。

从 nodes/library.py 迁出 (2026-11-10), 人工处理: 原实现用 `global _FF_HIST_WIN` 缓存 GUI 单例,
迁移后这个全局就本文件自己的, 不再污染 library 的命名空间。

entry: node_ss_ff_hist   ·   registry key: ss_ff_hist
"""

from .shared_runtime import (  # noqa: F401
    _SS_STATE,
    _gui_host_ok,
)

_FF_HIST_WIN = None   # 本节点的 GUI 单例缓存 (原来挂在 library 全局上)

def node_ss_ff_hist(ctx):
    """🧠 前馈激活直方图 — 读 ⚡前馈加速器探针 (ff_probe) → 三层 512 激活分布直方图
    引线: ⚡前馈加速器 → 本节点 (数据经 _SS_STATE['ff_probe'] 流通)

    🪟 窗口只在 GUI 宿主里开; 常驻循环/CLI 只算数据 (否则 Qt ABRT 会把整个循环打死)。"""
    log = ctx.get("log")
    try:
        import numpy as np   # 🐛 2026-09-09: 漏 import → 单步报 name 'np' is not defined
        probe = _SS_STATE.get("ff_probe")
        if not probe or "act_raw" not in probe:
            if log:
                log("🧠 前馈激活: 无探针数据 — 先运行 ⚡前馈加速器节点 (▶运行或单步)")
            return False
        _ls = probe.get("layers") or []
        _act = " · ".join(f"L{i+1}:{l.get('active', 0)}/512" for i, l in enumerate(_ls))
        if not _gui_host_ok():
            if log:
                log(f"🧠 前馈激活直方图 (无窗档): [{_act}] · u_ff={np.round(probe.get('u_ff', []), 3)} "
                    f"· 常驻循环/CLI 不开窗 (防 Qt ABRT 打死循环)")
            return True
        global _FF_HIST_WIN
        _win = getattr(ctx.get("module"), "_ff_hist_win", None)   # 优先 module 侧单例 (双击同窗)
        if _win is None:
            if _FF_HIST_WIN is None:
                from ff_hist_view import FFHistView   # 同目录, 延迟 import (Qt 依赖)
                _FF_HIST_WIN = FFHistView()
            _win = _FF_HIST_WIN
            if ctx.get("module") is not None:
                try:
                    ctx["module"]._ff_hist_win = _win
                except Exception:
                    pass
        _FF_HIST_WIN = _win
        _win.push(probe)
        if not _win.isVisible():
            _win.show()
        _win.raise_()
        _win.activateWindow()
        if log:
            ls = probe.get("layers") or []
            _act = " · ".join(f"L{i+1}:{l.get('active', 0)}/512" for i, l in enumerate(ls))
            log(f"🧠 前馈激活直方图: 已更新 [{_act}] · u_ff={np.round(probe.get('u_ff', []), 3)} "
                f"(窗口: 三层激活分布, 0=ReLU截断)")
        return True
    except Exception as e:
        if log:
            log(f"⚠️ 前馈激活直方图失败: {e}")
        return False

# 与既有 *_impl.py 同约定
run = node_ss_ff_hist
