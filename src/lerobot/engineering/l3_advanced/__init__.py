# -*- coding: utf-8 -*-
"""L3 · 高级功能 —— 长程序列规划 · 技能编排 · VLM+Flow-Matching 连续动作

必须还能干的事：
  · 长程序列规划(场景理解驱动)
  · 技能序列编排
  · 跨段技能序列入库/复用
  · VLM 编码 + Flow-Matching 连续动作输出

本层节点：
  ss_lora_l3     🎛 L3 · SmolVLA LoRA 微调 · 接入中
  ss_mem_l3      🚀 L3 · 长程序列规划 (记忆: 海马体)
  ssdec          🎯 Flow-Matching Action Head (DiT)
  ssskill        🛠 L3 技能序列编排
  ssvlm          🧠 VLM 通用视觉编码器 (SmolVLA)

⚠️ 这里只有**分层设计**(层义/归属/判据), 节点实现不在本包:
   实现  src/lerobot/middleware/nodes/impl/<node_key>.py
   契约  src/lerobot/middleware/nodes/n_<node_id>.py
   算法  src/lerobot/policies/...
生成物: tools/gen_layers.py (勿手改)
"""
LAYER = 'L3'
TITLE = '高级功能'
FOLDER = 'l3_advanced'
MUST = '  · 长程序列规划(场景理解驱动)\n  · 技能序列编排\n  · 跨段技能序列入库/复用\n  · VLM 编码 + Flow-Matching 连续动作输出'

# (画布节点 id, 名称, 注册 key, 实现文件)
NODES = [('ss_lora_l3', '🎛 L3 · SmolVLA LoRA 微调 · 接入中', 'ss_lora_l3', 'ss_lora_l3.py', 'node_ss_lora_l3'), ('ss_mem_l3', '🚀 L3 · 长程序列规划 (记忆: 海马体)', 'ss_mem_l3', 'mem_nodes.py', 'node_ss_mem_l3'), ('ssdec', '🎯 Flow-Matching Action Head (DiT)', 'action_head', 'action_head.py', 'node_action_head'), ('ssskill', '🛠 L3 技能序列编排', 'ss_skill', 'ss_skill.py', 'node_ss_skill'), ('ssvlm', '🧠 VLM 通用视觉编码器 (SmolVLA)', 'ss_vlm', 'ss_vlm.py', 'node_ss_vlm')]


def keys():
    """本层的逻辑 key 列表 (可执行/可查源码)"""
    return [n[2] for n in NODES if n[2]]


def ids():
    return [n[0] for n in NODES]


def describe():
    return {"layer": LAYER, "title": TITLE, "must": list(MUST), "n": len(NODES), "keys": keys()}
