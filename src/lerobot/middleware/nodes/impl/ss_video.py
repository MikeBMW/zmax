# -*- coding: utf-8 -*-
"""ss_video — 节点实现正文 (文件名 = 画布节点: ss_video)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_ss_video   ·   registry key: ss_video
"""

def node_ss_video(ctx):
    """🎥 操作视频 — 双击打开 metaworld 训练后 rollout 视频对比窗口 (多模型同步播放)"""
    module = ctx.get("module")
    label = ctx.get("label", "")
    if label == "▶运行":
        # 🐛 2026-09-01 老倪: ▶运行动画播放中不自动弹窗 — 弹窗置顶(_show_nonmodal) +
        #   断点暂停时主线程冻结 → 窗口关不掉 + "studio.py is not responding"; 双击才弹
        log = ctx.get("log")
        if log:
            log("🎥 操作视频: 运行模式跳过弹窗 — 双击节点打开")
        return True
    if module and hasattr(module, "on_infer_video"):
        module.on_infer_video()
    return True


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_video
