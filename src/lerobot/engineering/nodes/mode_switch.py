# -*- coding: utf-8 -*-
"""mode_switch — 节点实现正文 (文件名 = 画布节点: mode_switch)。

从 nodes/library.py 迁出 (2026-11-10 06:35)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_mode_switch   ·   registry key: mode_switch
"""

def node_mode_switch(ctx):
    """🔀 训练/推理模式开关 — 双击切换 train ⇄ infer, 激活路径金色高亮, 未激活灰显
    数据流: 📦数据源 → 🔀开关 → 🚀训练 | 📷推理(rollout)
    train → 训练节点激活(推理灰显); infer → 推理节点激活(训练灰显)
    真实实现: simulink_module.py _toggle_mode / _apply_mode_highlight / paint(mode_active 灰显)"""
    log = ctx["log"]
    node = ctx.get("node", {})
    p = node.get("params", {})
    mode = p.get("mode", "train")
    log(f"🔀 模式开关: 当前={'训练' if mode == 'train' else '推理'} (双击切换, 激活路径高亮)")
    return True


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_mode_switch
