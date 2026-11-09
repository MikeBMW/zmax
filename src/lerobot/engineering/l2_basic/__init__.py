# -*- coding: utf-8 -*-
"""L2 · 基础功能 —— 分段感知 → 融合 → 估计/预测/校正 → 原子技能 → 小模型控制

必须还能干的事：
  · 分段感知(检测/触觉/2D→3D/质量)
  · 传感器融合 → 43D 状态
  · 估计/预测/校正/前馈
  · 动作调制 + 安全限幅
  · 原子技能 SK01-08 可执行
  · 执行器 → 物理闭环
  · 肌肉记忆 固化→直通

本层节点：
  n_geoplan      🧭 测地线规划引导
  n_l2_muscle    💪 L2 肌肉记忆技能库 (光模块抓放循环)
  n_moveit       运动规划
  ss2d3d         📐 2D→3D 解算
  ss_mem_l2      🔧 L2 · 肌肉记忆操作 (小脑 · 标杆回放)
  ss_moe         🧬 元数据MOE门控路由
  ss_seg         🧩 SAM3分割
  ssaoi          🔍 光学质量检测
  ssest          🔮 自适应状态估计器
  ssff           ⚡ 前馈加速器
  ssinnov        🧪 状态校正器
  ssobs          🧩 SU(2) 统一状态空间 (二阶特殊酉群)
  ssphys         ⚖ 动力学约束
  sspred         📈 先验动力学预测器
  sssched        🧭 动作调制器
  sssensor       📡 融合定位建图
  sssk1          ① 接近 · SK01
  sssk2          ② 对位 · SK02
  sssk3          ③ 下降 · SK03
  sssk4          ④ 抓取 · SK04
  sssk5          ⑤ 抬起 · SK05
  sssk6          ⑥ 转移 · SK06
  sssk7          ⑦ 插入 · SK07
  sssk8          ⑧ 完成 · SK08
  sstactile      🖐 触觉感知
  ssyolo         🎯 YOLO 目标检测

⚠️ 这里只有**分层设计**(层义/归属/判据), 节点实现不在本包:
   实现  src/lerobot/middleware/nodes/impl/<node_key>.py
   契约  src/lerobot/middleware/nodes/n_<node_id>.py
   算法  src/lerobot/policies/...
生成物: tools/gen_layers.py (勿手改)
"""
LAYER = 'L2'
TITLE = '基础功能'
FOLDER = 'l2_basic'
MUST = '  · 分段感知(检测/触觉/2D→3D/质量)\n  · 传感器融合 → 43D 状态\n  · 估计/预测/校正/前馈\n  · 动作调制 + 安全限幅\n  · 原子技能 SK01-08 可执行\n  · 执行器 → 物理闭环\n  · 肌肉记忆 固化→直通'

# (画布节点 id, 名称, 注册 key, 实现文件)
NODES = [('n_geoplan', '🧭 测地线规划引导', 'n_geoplan', 'n_geoplan.py', 'node_geoplan'), ('n_l2_muscle', '💪 L2 肌肉记忆技能库 (光模块抓放循环)', 'n_l2_muscle', 'n_l2_muscle.py', 'node_n_l2_muscle'), ('n_moveit', '运动规划', 'n_moveit', 'n_moveit.py', 'node_moveit'), ('ss2d3d', '📐 2D→3D 解算', 'yolo_align', 'yolo_align.py', 'node_yolo_align'), ('ss_mem_l2', '🔧 L2 · 肌肉记忆操作 (小脑 · 标杆回放)', 'ss_mem_l2', 'mem_nodes.py', 'node_ss_mem_l2'), ('ss_moe', '🧬 元数据MOE门控路由', None, '?', None), ('ss_seg', '🧩 SAM3分割', 'ss_seg', 'ss_seg.py', 'node_ss_seg'), ('ssaoi', '🔍 光学质量检测', 'ss_aoi', 'ss_aoi.py', 'node_ss_aoi'), ('ssest', '🔮 自适应状态估计器', 'ss_est', 'ss_ff.py', 'node_ss_s2'), ('ssff', '⚡ 前馈加速器', 'ss_ff', 'ss_ff.py', 'node_ss_s2'), ('ssinnov', '🧪 状态校正器', 'ss_correct', 'ss_dyn.py', 'node_ss_dyn'), ('ssobs', '🧩 SU(2) 统一状态空间 (二阶特殊酉群)', 'ss_obs', 'ss_obs.py', 'node_ss_su2'), ('ssphys', '⚖ 动力学约束', 'ss_dyn_gate', 'ss_dyn_gate.py', 'node_ss_constraint_gate'), ('sspred', '📈 先验动力学预测器', 'ss_dyn', 'ss_dyn.py', 'node_ss_dyn'), ('sssched', '🧭 动作调制器', 'ss_sched', 'shared_runtime.py', 'node_ss_s3'), ('sssensor', '📡 融合定位建图', 'ss_sensor', 'ss_sensor.py', 'node_ss_s1'), ('sssk1', '① 接近 · SK01', 'sssk1', 'sssk1.py', 'node_ss_atomic'), ('sssk2', '② 对位 · SK02', 'sssk2', 'sssk1.py', 'node_ss_atomic'), ('sssk3', '③ 下降 · SK03', 'sssk3', 'sssk1.py', 'node_ss_atomic'), ('sssk4', '④ 抓取 · SK04', 'sssk4', 'sssk1.py', 'node_ss_atomic'), ('sssk5', '⑤ 抬起 · SK05', 'sssk5', 'sssk1.py', 'node_ss_atomic'), ('sssk6', '⑥ 转移 · SK06', 'sssk6', 'sssk1.py', 'node_ss_atomic'), ('sssk7', '⑦ 插入 · SK07', 'sssk7', 'sssk1.py', 'node_ss_atomic'), ('sssk8', '⑧ 完成 · SK08', 'sssk8', 'sssk1.py', 'node_ss_atomic'), ('sstactile', '🖐 触觉感知', 'yolo_tactile', 'yolo_tactile.py', 'node_yolo_tactile'), ('ssyolo', '🎯 YOLO 目标检测', 'ss_yolo', 'ss_yolo.py', 'node_ss_yolo')]


def keys():
    """本层的逻辑 key 列表 (可执行/可查源码)"""
    return [n[2] for n in NODES if n[2]]


def ids():
    return [n[0] for n in NODES]


def describe():
    return {"layer": LAYER, "title": TITLE, "must": list(MUST), "n": len(NODES), "keys": keys()}
