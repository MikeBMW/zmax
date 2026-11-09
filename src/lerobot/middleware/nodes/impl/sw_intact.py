# -*- coding: utf-8 -*-
"""sw_intact — 节点实现正文 (文件名 = 画布节点: sw_intact)。

从 nodes/library.py 迁出 (2026-11-10 06:38)。老倪: 「是哪个节点, 就用哪个节点的名称」——
打开源码 / 下断点 / 改逻辑, 只面对这一个文件; library.py 只剩共享运行时和薄壳。

entry: node_sw_intact   ·   registry key: sw_intact
"""

# 共享运行时/辅助函数仍在 library.py —— 显式导入, 不搞 globals 注入
from .shared_runtime import (  # noqa: F401
    _sw_paths,
    _sw_task,
    _sw_wait,
    os,
)

def node_sw_intact(ctx):
    """🎯 L4 中间策略 — INTACT (本域微调权重 · 零搜索 · 真模型在环)"""
    log = ctx["log"]
    root = str(ctx.get("root") or os.getcwd())
    tsk = "光模块插拔" if _sw_task(root) == "optical_insert" else "cube"
    _, fr, st, _ = _sw_paths(root)
    d = _sw_wait(st, lambda s: bool(s.get("model_calls")), 300.0, log, "INTACT 策略")
    if not d:
        log("❌ INTACT 策略: 未拿到桥状态 (看 reports/intact_sw/bridge.log)")
        return False
    log(f"🎯 INTACT 策略 [L4·{tsk}]: ckpt={d.get('ckpt')}")
    log(f"   权重文件 {d.get('ckpt_file')} · action_dim={d.get('action_dim')} · "
        f"hist={d.get('hist_size')}")
    log(f"   真推理 模型调用 {d.get('model_calls')} 次 · 零搜索={d.get('zero_search', True)} "
        f"(candidate_action_steps=0)")
    log(f"   末帧 模型输出(已反归一化 u)={d.get('action')} → 下发 env 动作={d.get('env_action')}")
    log(f"   动作口径 {d.get('action_space')} · 统计 {d.get('stats')} (与权重同源, 非手写)")
    return True


# 与既有 *_impl.py 同约定: 外部也可以 from ... import run
run = node_sw_intact
