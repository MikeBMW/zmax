# -*- coding: utf-8 -*-
"""n_realscene_live — 节点实现正文 (文件名 = 画布节点: n_realscene_live)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_realscene_live   ·   registry key: n_realscene_live
"""

def node_realscene_live(ctx):
    """🎥 真实场景叠加 — 双击: 画布节点内实时显示叠加画面 (再双击一次 = 停)"""
    module = ctx.get("module")
    log = ctx.get("log")
    if module is None or not hasattr(module, "toggle_canvas_live_overlay"):
        if log:
            log("⚠️ 场景叠加: 无 module 上下文 (仅画布内双击/工具栏按钮可用)")
        return False
    ok = module.toggle_canvas_live_overlay()
    if log and not ok:
        log("⚠️ 场景叠加: 未能出画面 — 先确认视频流 8791 在跑 (工具栏「🧩 场景叠加」或「📡 视频流」)")
    return bool(ok)


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_realscene_live
