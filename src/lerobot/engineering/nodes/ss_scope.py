# -*- coding: utf-8 -*-
"""ss_scope — 节点实现正文 (文件名 = 画布节点: ss_scope)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_ss_scope   ·   registry key: ss_scope
"""

def node_ss_scope(ctx):
    """📊 仿真波形 — 双击显示最近一次状态空间仿真波形 (距离/残差/接触概率 + 阶段切换)"""
    module = ctx.get("module")
    label = ctx.get("label", "")
    if label == "▶运行":
        # 🐛 2026-09-01 老倪: 同 node_ss_video — 运行模式不弹窗, 双击节点才打开
        log = ctx.get("log")
        if log:
            log("📊 仿真波形: 运行模式跳过弹窗 — 双击节点查看")
        return True
    if module and hasattr(module, "show_state_space_scope"):
        module.show_state_space_scope()
    return True


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_ss_scope
