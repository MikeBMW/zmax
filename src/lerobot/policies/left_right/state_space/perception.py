"""perception.py — S1 时空感知前端 (状态空间模型画布)

传感器融合: RGB-D + 力觉 + 触觉 (+ 预留扩展) → **55D** 统一状态向量 obs。

状态空间视角: 观测方程 y = C·x
  x  = 真实世界状态 (末端位姿/工件位姿/接触力)
  C  = 观测矩阵 (传感器模型)
  y  = 55D obs (K_obs = 1.0, 状态直接作为观测)

55D = 39D 视觉与本体 + 4D 触觉力觉 + **12D 预留扩展** (多指触觉/温度/声学/电流/备用)
      43D 是它的前段 —— 老模型/老数据/老标定按前 43 维原样可用 (逐位不变)。
      分段表与取数接口见 unified_state55.py (禁止在消费端自己数下标)。

时空感知 = 当前帧 + 历史帧时序堆叠。
"""
import numpy as np

# 55D 是标准口径; 43D 为兼容口径 (老权重吃前 43 维)
OBS_DIM = 55          # 统一状态向量维度 (标准)
VISUAL_DIM = 39       # 视觉结构维度 (坐标=逻辑主线, 图像=背景)
TACTILE_DIM = 4       # 触觉增维: [grasp, contact, dir_x, dir_y]
EXTRA_DIM = 12        # 预留扩展: 多指触觉4 + 温度1 + 声学1 + 电流2 + 备用4
LEGACY_OBS_DIM = 43   # 兼容维度 = 39 + 4


def fuse_sensors(rgbd_feats, force_6d, tactile_marker, K_obs=1.0, dim=LEGACY_OBS_DIM, extra=None):
    """融合三类传感器 (+ 可选扩展通道) → 统一状态向量。

    Args:
        rgbd_feats: 39D 视觉结构特征 (YOLO 2D→3D 反投影后)
        force_6d:   六维力/力矩 (接触检测用, 不直接进 obs —— 口径不变)
        tactile_marker: 4D 触觉标记 (grasp/contact/dir)
        dim:        43 = 兼容口径 (默认; 在役 L3/L4 权重与演练脚本按此训练, 不许被静默改形状)
                    55 = 标准口径 (后 12 维全 0 沉睡) —— 引擎走 fuse_sensors55() / 新代码显式指定
        extra:      扩展通道 dict, 例如 {"temperature": 36.4} (按名, 不按下标)
    Returns:
        obs: dim 维统一状态向量 (默认 43 = 兼容口径; 标准口径用 dim=55)
    """
    assert np.asarray(rgbd_feats).shape[-1] == VISUAL_DIM, "视觉与本体状态必须 39 维"
    assert np.asarray(tactile_marker).shape[-1] == TACTILE_DIM, "触觉力觉必须 4 维"
    if int(dim) == LEGACY_OBS_DIM:
        obs = np.concatenate([K_obs * np.asarray(rgbd_feats, dtype=float),
                              np.asarray(tactile_marker, dtype=float)])
        assert obs.shape[-1] == LEGACY_OBS_DIM
        return obs
    if int(dim) != OBS_DIM:
        raise ValueError("dim 只支持 %d (标准) 或 %d (兼容), 收到 %s"
                         % (OBS_DIM, LEGACY_OBS_DIM, dim))
    try:
        from .unified_state55 import UnifiedState55D          # 包内正常路径
    except ImportError:                                      # 端侧按文件加载 (无包 __init__ 依赖)
        from unified_state55 import UnifiedState55D
    us = UnifiedState55D(k_obs=K_obs)
    return us.fuse(rgbd_feats, tactile_marker, extra=extra)


def fuse_sensors43(rgbd_feats, force_6d, tactile_marker, K_obs=1.0):
    """43D 兼容入口 (等价 fuse_sensors 默认口径; 与升级前逐位一致)。"""
    return fuse_sensors(rgbd_feats, force_6d, tactile_marker, K_obs=K_obs, dim=LEGACY_OBS_DIM)


def fuse_sensors55(rgbd_feats, force_6d, tactile_marker, K_obs=1.0, extra=None):
    """55D 标准入口: 39 视觉与本体 ⊕ 4 触觉力觉 ⊕ 12 预留扩展 (默认全 0)。"""
    return fuse_sensors(rgbd_feats, force_6d, tactile_marker, K_obs=K_obs, dim=OBS_DIM, extra=extra)
