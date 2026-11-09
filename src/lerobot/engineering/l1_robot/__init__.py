# -*- coding: utf-8 -*-
"""L1 · 机器人接口 —— 真机/仿真臂的进出都从这层过: 指令收口 · 执行 · 安全边界 · 物理闭环

必须还能干的事：
  · 动作调制后的指令在这里收口(授权/闸/到位)
  · 执行器真下发/真回读
  · 安全限幅饱和
  · 物理世界闭环(质量/自由度)

本层节点：
  n_exec         ⚙️ 动作执行器 (L2 收口 · 授权/闸/到位)
  ssact          🤖 机器人执行器
  sslimit        🛡 安全执行边界 (饱和限幅)
  ssworld        🌍 物理世界

⚠️ 这里只有**分层设计**(层义/归属/判据), 节点实现不在本包:
   实现  src/lerobot/middleware/nodes/impl/<node_key>.py
   契约  src/lerobot/middleware/nodes/n_<node_id>.py
   算法  src/lerobot/policies/...
生成物: tools/gen_layers.py (勿手改)
"""
LAYER = 'L1'
TITLE = '机器人接口'
FOLDER = 'l1_robot'
MUST = '  · 动作调制后的指令在这里收口(授权/闸/到位)\n  · 执行器真下发/真回读\n  · 安全限幅饱和\n  · 物理世界闭环(质量/自由度)'

# (画布节点 id, 名称, 注册 key, 实现文件)
NODES = [('n_exec', '⚙️ 动作执行器 (L2 收口 · 授权/闸/到位)', 'n_exec', 'n_exec.py', 'node_exec'), ('ssact', '🤖 机器人执行器', 'ss_act', 'ss_act.py', 'node_ss_exec'), ('sslimit', '🛡 安全执行边界 (饱和限幅)', 'ss_limit', 'ss_limit.py', 'node_ss_s3'), ('ssworld', '🌍 物理世界', 'ss_world', 'ss_act.py', 'node_ss_exec')]


def keys():
    """本层的逻辑 key 列表 (可执行/可查源码)"""
    return [n[2] for n in NODES if n[2]]


def ids():
    return [n[0] for n in NODES]


def describe():
    return {"layer": LAYER, "title": TITLE, "must": list(MUST), "n": len(NODES), "keys": keys()}
