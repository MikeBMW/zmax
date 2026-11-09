# -*- coding: utf-8 -*-
"""ss_3d_view — 节点实现正文 (文件名 = 画布节点: ss_3d_view)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_ss_3d_view   ·   registry key: ss_3d_view
"""

def node_ss_3d_view(ctx):
    """🧭 3D 视图 — 打开 Apollo 风格 3D 分层视图 (可视化层观察器, 源=物理世界)
    ▶运行 模式跳过弹窗 (同操作视频); 双击/右键运行 → 打开/置顶 3D 窗口"""
    module = ctx.get("module")
    label = ctx.get("label", "")
    log = ctx.get("log")
    if label == "▶运行":
        if log:
            log("🧭 3D 视图: 运行模式跳过弹窗 — 双击节点打开 (防断点冻结关不掉)")
        return True
    if module and hasattr(module, "open_ss_3d"):
        module.open_ss_3d()
        if log:
            log("🧭 3D 视图: 已打开 (Apollo 风格分层视图, 与引擎/画布同源)")
        return True
    if log:
        log("⚠️ 3D 视图: 无 module 上下文 (仅画布内双击/右键运行可用)")
    return False


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_3d_view
