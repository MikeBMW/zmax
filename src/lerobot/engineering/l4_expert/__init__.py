# -*- coding: utf-8 -*-
"""L4 · 专家功能 —— 工作安全 · 物理世界导航 · 能力档位 · 流形世界模型 · 势场

必须还能干的事：
  · 工作安全(INTACT)
  · 物理世界导航
  · 能力档位切换
  · 标定/流形世界模型
  · 恢复策略/筹划入库
  · 势场联络 (−∇Φ)

本层节点：
  n_calib_mani   🧮 标定诊断测量 · 主参数 M (状态空间结构参数 · 等效惯量)
  n_intent_bundle 🧠 意图丛 · 四槽语法
  n_intent_direct 🧾 元任务预测 (驱动扭矩 → 元任务预测值)
  ss_grav_h      🌍 万有引力 · SE(3) 几何阻抗 + H=K+U (力场仲裁)
  ss_lora_l4     🎛 L4 · INTACT LoRA 微调 (接在意图解码器后 · 冻结原权重 · 只调 ΔW=(α/r)BA)
  ss_mani_eng    🧮 流形引擎 (Manifold Engine · 编码→投影→度量→导航→反馈)
  ss_mem_field   🧲 总装机记忆 · 势场联络 (L2/L3/L4 势场 → 意图 −∇Φ)
  ss_mem_l4      🏆 L4 · 工作安全 + 物理世界导航 (记忆: 前额叶)
  ss_mem_share   🧠 总装记忆中枢 (前额叶总装 · 三层协同)
  sscalib        🧮 标定层 · 引力-斥力-动作
  sscap          🧭 能力档位
  ssintact       🎯 INTACT (L4) · 工作安全 + 物理世界导航
  ssintact_dec   🎯 INTACT 意图解码器 (L4 → L3 条件)
  sslat          🧮 潜空-流形
  ssmani_c       🧮 接触流形 · 导航地图 (e∥进度/e⊥偏离)
  ssmani_exp     🧠 流形专家预测器 (JEPA: 潜空间→流形→动作)
  ssmani_p       🧮 性能流形 · 耦合代价 (V_p/η)
  swintact       🎯 INTACT 插拔策略 · 光模块抓取插入 (本域微调 · 零搜索)
  swworld        🌍 Z-MAX 引擎 · 光模块插拔真物理 (模型动作真下发 env.step)

⚠️ 这里只有**分层设计**(层义/归属/判据), 节点实现不在本包:
   实现  src/lerobot/middleware/nodes/impl/<node_key>.py
   契约  src/lerobot/middleware/nodes/n_<node_id>.py
   算法  src/lerobot/policies/...
生成物: tools/gen_layers.py (勿手改)
"""
LAYER = 'L4'
TITLE = '专家功能'
FOLDER = 'l4_expert'
MUST = '  · 工作安全(INTACT)\n  · 物理世界导航\n  · 能力档位切换\n  · 标定/流形世界模型\n  · 恢复策略/筹划入库\n  · 势场联络 (−∇Φ)'

# (画布节点 id, 名称, 注册 key, 实现文件)
NODES = [('n_calib_mani', '🧮 标定诊断测量 · 主参数 M (状态空间结构参数 · 等效惯量)', 'n_calib_mani', 'n_calib_mani.py', 'node_ss_calib_mani'), ('n_intent_bundle', '🧠 意图丛 · 四槽语法', 'ss_intent_bundle', 'mem_nodes.py', 'node_ss_intent_bundle'), ('n_intent_direct', '🧾 元任务预测 (驱动扭矩 → 元任务预测值)', 'ss_intent_direct', 'mem_nodes.py', 'node_ss_intent_direct'), ('ss_grav_h', '🌍 万有引力 · SE(3) 几何阻抗 + H=K+U (力场仲裁)', 'ss_grav_h', 'shared_runtime.py', 'node_ss_grav_h'), ('ss_lora_l4', '🎛 L4 · INTACT LoRA 微调 (接在意图解码器后 · 冻结原权重 · 只调 ΔW=(α/r)BA)', 'ss_lora_l4', 'ss_lora_l4.py', 'node_ss_lora_l4'), ('ss_mani_eng', '🧮 流形引擎 (Manifold Engine · 编码→投影→度量→导航→反馈)', 'ss_mani_eng', 'ss_mani_eng.py', 'node_ss_mani_eng'), ('ss_mem_field', '🧲 总装机记忆 · 势场联络 (L2/L3/L4 势场 → 意图 −∇Φ)', 'ss_mem_field', 'mem_nodes.py', 'node_ss_mem_field'), ('ss_mem_l4', '🏆 L4 · 工作安全 + 物理世界导航 (记忆: 前额叶)', 'ss_world', 'ss_act.py', 'node_ss_exec'), ('ss_mem_share', '🧠 总装记忆中枢 (前额叶总装 · 三层协同)', 'ss_mem_share', 'mem_nodes.py', 'node_ss_mem_share'), ('sscalib', '🧮 标定层 · 引力-斥力-动作', 'ss_calib', 'ss_calib.py', 'node_ss_calib'), ('sscap', '🧭 能力档位', 'ss_cap', 'ss_cap.py', 'node_ss_cap'), ('ssintact', '🎯 INTACT (L4) · 工作安全 + 物理世界导航', 'intact', 'intact.py', 'node_intact'), ('ssintact_dec', '🎯 INTACT 意图解码器 (L4 → L3 条件)', 'intact_dec', 'intact_dec.py', 'node_intact_dec'), ('sslat', '🧮 潜空-流形', 'ss_lat', 'ss_lat.py', 'node_ss_lat'), ('ssmani_c', '🧮 接触流形 · 导航地图 (e∥进度/e⊥偏离)', 'ss_mani_c', 'ss_mani_c.py', 'node_ss_mani'), ('ssmani_exp', '🧠 流形专家预测器 (JEPA: 潜空间→流形→动作)', 'ss_pred', 'ss_pred.py', 'node_ss_pred'), ('ssmani_p', '🧮 性能流形 · 耦合代价 (V_p/η)', 'ss_mani_p', 'ss_mani_c.py', 'node_ss_mani'), ('swintact', '🎯 INTACT 插拔策略 · 光模块抓取插入 (本域微调 · 零搜索)', 'sw_intact', 'sw_intact.py', 'node_sw_intact'), ('swworld', '🌍 Z-MAX 引擎 · 光模块插拔真物理 (模型动作真下发 env.step)', 'sw_world', 'sw_world.py', 'node_sw_world')]


def keys():
    """本层的逻辑 key 列表 (可执行/可查源码)"""
    return [n[2] for n in NODES if n[2]]


def ids():
    return [n[0] for n in NODES]


def describe():
    return {"layer": LAYER, "title": TITLE, "must": list(MUST), "n": len(NODES), "keys": keys()}
