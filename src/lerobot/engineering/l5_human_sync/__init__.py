# -*- coding: utf-8 -*-
"""L5 · 人机同步 —— 大模型理解 · 任务指令解析 · 自动标注监督下层 · 人机同步

必须还能干的事：
  · 视觉语言场景理解(VLM/DeepSeek)
  · 自动标注 → 监督 L2/L3/L4
  · 任务指令解析(MES/自然语言)
  · 工程记忆/技能库
  · 标注→自动训练闭环

本层节点：
  n_dsvl         🧿 DeepSeek-V4-Flash · 场景理解 (L5 大模型主路)
  n_eng_mem      📚 工程记忆 · 技能与经验库
  n_hil          🙋 HIL 人机在环 · 状态↔指示
  n_mem_links    🔗 跨层连接 · 记忆图谱
  n_skill_dict   🧬 技能词典 · L2 动作基
  n_vlm_llm      👁 视觉语言大模型 · 场景理解 (Qwen2.5/3-VL)
  n_web_agent    🌐 Web 智能体桥 · 远程提示词
  ss_l5          🧿 L5 · 视觉语言自动标注 → L2/L3/L4 监督 → 自动训练
  ssllm          🧠 长程序列规划器 (场景理解驱动)
  ssllm_in       📝 任务指令 · MES/自然语言
  ssreason       🔍 异常推理器 (LLM)

⚠️ 这里只有**分层设计**(层义/归属/判据), 节点实现不在本包:
   实现  src/lerobot/middleware/nodes/impl/<node_key>.py
   契约  src/lerobot/middleware/nodes/n_<node_id>.py
   算法  src/lerobot/policies/...
生成物: tools/gen_layers.py (勿手改)
"""
LAYER = 'L5'
TITLE = '人机同步'
FOLDER = 'l5_human_sync'
MUST = '  · 视觉语言场景理解(VLM/DeepSeek)\n  · 自动标注 → 监督 L2/L3/L4\n  · 任务指令解析(MES/自然语言)\n  · 工程记忆/技能库\n  · 标注→自动训练闭环'

# (画布节点 id, 名称, 注册 key, 实现文件)
NODES = [('n_dsvl', '🧿 DeepSeek-V4-Flash · 场景理解 (L5 大模型主路)', 'n_dsvl', 'n_dsvl.py', 'node_dsvl'), ('n_eng_mem', '📚 工程记忆 · 技能与经验库', 'n_eng_mem', 'n_eng_mem.py', 'node_ss_eng_mem'), ('n_hil', '🙋 HIL 人机在环 · 状态↔指示', 'n_hil', 'n_hil.py', 'node_hil'), ('n_mem_links', '🔗 跨层连接 · 记忆图谱', 'ss_mem_links', 'mem_nodes.py', 'node_ss_mem_links'), ('n_skill_dict', '🧬 技能词典 · L2 动作基', 'ss_skill_dict', 'mem_nodes.py', 'node_ss_skill_dict'), ('n_vlm_llm', '👁 视觉语言大模型 · 场景理解 (Qwen2.5/3-VL)', 'n_dsvl', 'n_dsvl.py', 'node_dsvl'), ('n_web_agent', '🌐 Web 智能体桥 · 远程提示词', 'n_web_agent', 'n_web_agent.py', 'node_web_agent'), ('ss_l5', '🧿 L5 · 视觉语言自动标注 → L2/L3/L4 监督 → 自动训练', 'l5_loop', 'l5_loop.py', 'node_l5_loop'), ('ssllm', '🧠 长程序列规划器 (场景理解驱动)', 'ss_llm', 'ss_llm.py', 'node_ss_llm'), ('ssllm_in', '📝 任务指令 · MES/自然语言', 'ss_llm_in', 'ss_llm_in.py', 'node_ss_llm_in'), ('ssreason', '🔍 异常推理器 (LLM)', 'ss_reason', 'ss_reason.py', 'node_ss_reason')]


def keys():
    """本层的逻辑 key 列表 (可执行/可查源码)"""
    return [n[2] for n in NODES if n[2]]


def ids():
    return [n[0] for n in NODES]


def describe():
    return {"layer": LAYER, "title": TITLE, "must": list(MUST), "n": len(NODES), "keys": keys()}
