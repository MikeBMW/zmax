# -*- coding: utf-8 -*-
"""L1~L5 分层 (汇总) —— engineering 的骨架。

    L1 机器人接口 · L2 基础功能 · L3 高级功能 · L4 专家功能 · L5 人机同步

每个 lN_*.py 是那一层的设计 (层义 / 必须还能干什么 / 有哪些节点);
节点实现不在这里, 在 src/lerobot/middleware/nodes/impl/。
生成物: tools/gen_layers.py (勿手改)
"""
from . import l1_robot, l2_basic, l3_advanced, l4_expert, l5_human_sync  # noqa: F401

LAYERS = {"L1": l1_robot, "L2": l2_basic, "L3": l3_advanced,
          "L4": l4_expert, "L5": l5_human_sync}
LAYER_ORDER = ("L1", "L2", "L3", "L4", "L5")

# 兼容旧接口 (by_level): 层 → [(节点id, 名称, key, 实现文件, 函数)]
LEVELS_INDEX = {
    "L1": [tuple(r) for r in l1_robot.NODES],
    "L2": [tuple(r) for r in l2_basic.NODES],
    "L3": [tuple(r) for r in l3_advanced.NODES],
    "L4": [tuple(r) for r in l4_expert.NODES],
    "L5": [tuple(r) for r in l5_human_sync.NODES],
}


def keys_of(level):
    return [r[2] for r in LEVELS_INDEX.get(level, []) if r[2]]


def ids_of(level):
    return [r[0] for r in LEVELS_INDEX.get(level, [])]


def funcs_of(level):
    from .registry import get
    return {k: (get(k) or {}).get("fn") for k in keys_of(level)}


def summary():
    return {lv: {"nodes": len(rows), "with_logic": len([r for r in rows if r[2]])}
            for lv, rows in LEVELS_INDEX.items()}
