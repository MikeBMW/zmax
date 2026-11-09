#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按 L1~L5 生成 engineering 的分层文件夹 + 汇总模块。

老倪 2026-11-10 定的层义:
    L1 机器人接口 · L2 基础功能 · L3 高级功能 · L4 专家功能 · L5 人机同步

生成:
    engineering/l1_robot/__init__.py      LAYER/TITLE/MUST/NODES
    engineering/l2_basic/__init__.py
    engineering/l3_advanced/__init__.py
    engineering/l4_expert/__init__.py
    engineering/l5_human_sync/__init__.py
    engineering/layers.py                 汇总: LEVELS_INDEX · keys_of · funcs_of · summary

唯一依据: levels.py (层义/归属) + registry (key→实现) + flows (画布)。
节点实现**不在这里** (在 middleware/nodes/impl/), 本层只描述"这一层有什么、必须还能干什么"。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENG = ROOT / "src/lerobot/engineering"

FOLDERS = {"L1": "l1_robot", "L2": "l2_basic", "L3": "l3_advanced",
           "L4": "l4_expert", "L5": "l5_human_sync"}
SHORT = {"L1": "机器人接口", "L2": "基础功能", "L3": "高级功能",
         "L4": "专家功能", "L5": "人机同步"}
TAGLINE = {
    "L1": "真机/仿真臂的进出都从这层过: 指令收口 · 执行 · 安全边界 · 物理闭环",
    "L2": "分段感知 → 融合 → 估计/预测/校正 → 原子技能 → 小模型控制",
    "L3": "长程序列规划 · 技能编排 · VLM+Flow-Matching 连续动作",
    "L4": "工作安全 · 物理世界导航 · 能力档位 · 流形世界模型 · 势场",
    "L5": "大模型理解 · 任务指令解析 · 自动标注监督下层 · 人机同步",
}

HEADER = '''# -*- coding: utf-8 -*-
"""{layer} · {short} —— {tag}

必须还能干的事：
{must}

本层节点：
{nodes_txt}

⚠️ 这里只有**分层设计**(层义/归属/判据), 节点实现不在本包:
   实现  src/lerobot/middleware/nodes/impl/<node_key>.py
   契约  src/lerobot/middleware/nodes/n_<node_id>.py
   算法  src/lerobot/policies/...
生成物: tools/gen_layers.py (勿手改)
"""
LAYER = {layer!r}
TITLE = {short!r}
FOLDER = {folder!r}
MUST = {must!r}

# (画布节点 id, 名称, 注册 key, 实现文件)
NODES = {nodes_repr!r}


def keys():
    """本层的逻辑 key 列表 (可执行/可查源码)"""
    return [n[2] for n in NODES if n[2]]


def ids():
    return [n[0] for n in NODES]


def describe():
    return {{"layer": LAYER, "title": TITLE, "must": list(MUST), "n": len(NODES), "keys": keys()}}
'''

FOOT = '''# -*- coding: utf-8 -*-
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
'''


def main():
    sys.path.insert(0, str(ROOT / "src"))
    from lerobot.engineering import levels, flows, registry  # noqa: PLC0415
    import lerobot.middleware.nodes.impl.shared_runtime  # noqa: F401,PLC0415

    d = flows.load_canvas(validate=False)
    d = d[0] if isinstance(d, tuple) else d
    names = {n.get("id"): n.get("name") for n in d.get("nodes") or []}
    bm = levels.band_map(d)
    by = {lv: [] for lv in FOLDERS}
    for nid, lv in bm.items():
        if lv not in by:
            continue
        key = registry.match_node(names.get(nid) or "")
        info = registry.get(key) or {}
        f = (info.get("file") or "?").split("/")[-1]
        _fn = info.get("fn")
        by[lv].append((nid, names.get(nid) or "", key, f, getattr(_fn, "__name__", None)))

    for lv, folder in FOLDERS.items():
        rows = sorted(by[lv], key=lambda r: r[0])
        must = "\n".join("  · " + m for m in levels.LEVELS[lv]["must"])
        nl = "\n".join("  %-14s %s" % (r[0], r[1]) for r in rows) or "  (本层暂无节点)"
        p = ENG / folder
        p.mkdir(exist_ok=True)
        (p / "__init__.py").write_text(
            HEADER.format(layer=lv, short=SHORT[lv], tag=TAGLINE[lv], must=must,
                          nodes_txt=nl, folder=folder, nodes_repr=rows),
            encoding="utf-8")
        print("%-4s %-14s %2d 节点" % (lv, folder + "/", len(rows)))
    (ENG / "layers.py").write_text(FOOT, encoding="utf-8")
    print("→ engineering/layers.py")


if __name__ == "__main__":
    main()
