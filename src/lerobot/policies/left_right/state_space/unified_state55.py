#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""unified_state55.py — L2 统一状态空间 55D (43D 的向后兼容升级)

分段 (唯一口径, 任何页面/模型/接口都按这张表说话):

    [ 0:39]  视觉与本体 39   tcp_p(3) | 夹爪标量(1) | 工件xyz(3) | 相对位移(3) | 夹爪两维(2)
                              | 右臂关节角(6) | 关节速(6) | TCP旋转(9) | 目标位(3) | 孔位(3)
    [39:43]  触觉力觉 4     grasp | contact | dir_x | dir_y
    [43:55]  预留扩展 12    多指触觉阵列(4) | 温度(1) | 声学(1) | 电流(2) | 备用(4)

为什么不是"改个数字": 43→55 是一次**接口升级**, 三条硬约束:
  ① 前 43 维语义一字不动 (老模型权重、老数据、老标定全部原样可用)
  ② 新增 12 维在模型侧**零行初始化** ⇒ 升级瞬间输出逐位不变 (可证: z 完全相同), 之后靠数据"觉醒"
  ③ 每个扩展通道都有名字/单位/来源, 不许匿名塞数 (匿名维 = 以后没人敢用)

数学部分 (SU(2)/S³ 与 SE(3)):
  · 测地线距离用 atan2 形式 —— acos(⟨q1,q2⟩) 在 q1≈q2 时导数发散, 训练一步就 NaN (实测过)
  · slerp 在 θ→0 与 θ→π 两处都要有安全分支, 且**不能**用 where 掩掉已除零的分支 (梯度仍是 NaN)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import numpy as np

VISUAL_DIM = 39
TACTILE_DIM = 4
EXTRA_DIM = 12
OBS55_DIM = VISUAL_DIM + TACTILE_DIM + EXTRA_DIM      # 55
LEGACY43_DIM = VISUAL_DIM + TACTILE_DIM               # 43


@dataclass(frozen=True)
class Segment:
    name: str
    start: int
    stop: int
    unit: str
    source: str
    note: str = ""

    @property
    def dim(self) -> int:
        return self.stop - self.start


# ── 0:39 视觉与本体 (与 metaworld/ar_mujoco_env 的 obs39 逐位一致, 不是重新定义) ──────────
VISUAL_SEGMENTS: tuple[Segment, ...] = (
    Segment("tcp_p", 0, 3, "m", "env._tcp()[0]", "手爪真实位置 = runtime 控制锚"),
    Segment("grip_scalar", 3, 4, "-", "env._get_obs()", "夹爪开合标量"),
    Segment("peg_xyz", 4, 7, "m", "env._gold()[0]", "光模块位置 (曾把旋转塞进 4:7 → 9.9 m 鬼值)"),
    Segment("peg_minus_tcp", 7, 10, "m", "gold_p - tcp_p", "相对位移"),
    Segment("grip_xy", 10, 12, "-", "gold_free qpos", "夹爪两指 (冗余保留)"),
    Segment("q_right", 12, 18, "rad", "R_j0..R_j5 qpos", "右臂关节角"),
    Segment("dq_right", 18, 24, "rad/s", "R_j0..R_j5 qvel", "右臂关节速度"),
    Segment("tcp_R", 24, 33, "-", "env._tcp()[1].ravel()", "TCP 旋转 3×3 展平"),
    Segment("target_xyz", 33, 36, "m", "env._gold_home", "目标位"),
    Segment("hole_xyz", 36, 39, "m", "env._hole_p()", "孔口世界坐标 (写死 36:39, 不许挪)"),
)

# ── 39:43 触觉力觉 (原始 4 维, 语义不变) ──────────────────────────────────────────────
TACTILE_SEGMENTS: tuple[Segment, ...] = (
    Segment("grasp", 39, 40, "-", "tactile[0]", "夹持状态"),
    Segment("contact", 40, 41, "N", "tactile[1]", "接触力标量"),
    Segment("dir_x", 41, 42, "-", "tactile[2]", "受力方向 x"),
    Segment("dir_y", 42, 43, "-", "tactile[3]", "受力方向 y"),
)

# ── 43:55 预留扩展 12 维: 有名有姓, 默认全 0 (沉睡) ───────────────────────────────────
EXTRA_SEGMENTS: tuple[Segment, ...] = (
    Segment("finger_pressure", 43, 47, "kPa", "多指触觉阵列 (预留)", "4 指峰值压力, 未来 C3 力控装配用"),
    Segment("temperature", 47, 48, "°C", "末端温度 (预留)", "热变形的慢变量"),
    Segment("acoustic", 48, 49, "dB", "声学/超声 (预留)", "插到位/划伤有不同频谱签名"),
    Segment("current", 49, 51, "A", "关节电流 (预留)", "无力传感器时的力矩代理"),
    Segment("spare", 51, 55, "-", "备用", "留给下一轮硬件升级, 不许临时借用改名"),
)

ALL_SEGMENTS = VISUAL_SEGMENTS + TACTILE_SEGMENTS + EXTRA_SEGMENTS

# 名称 → 切片, 供消费端按名取值 (禁止在消费端自己数下标)
SLICE: dict[str, slice] = {s.name: slice(s.start, s.stop) for s in ALL_SEGMENTS}


def layout_table() -> list[dict]:
    """结构化字段表 (可直接塞进页面/PPT/接口文档)。"""
    return [{"name": s.name, "start": s.start, "stop": s.stop, "dim": s.dim,
             "unit": s.unit, "source": s.source, "note": s.note} for s in ALL_SEGMENTS]


def validate_layout() -> None:
    """分段必须首尾相接、覆盖 0:55、无重叠 —— 布局本身也要有判据。"""
    pos = 0
    for s in ALL_SEGMENTS:
        if s.start != pos:
            raise ValueError("分段不连续: %s 从 %d 起, 期望 %d" % (s.name, s.start, pos))
        pos = s.stop
    if pos != OBS55_DIM or len({s.name for s in ALL_SEGMENTS}) != len(ALL_SEGMENTS):
        raise ValueError("分段未覆盖/有重名: 结尾 %d (期望 %d)" % (pos, OBS55_DIM))


validate_layout()


class UnifiedState55D:
    """L2 统一状态空间 55D 融合器。

    用法:
        us = UnifiedState55D()
        x55 = us.fuse(visual39, tactile4)                    # 扩展全 0
        x55 = us.fuse(visual39, tactile4, {"temperature": 36.4})
        us.get("hole_xyz")                                   # 按名取, 不数下标
    """

    def __init__(self, k_obs: float = 1.0) -> None:
        self.k_obs = float(k_obs)
        self.current_state = np.zeros(OBS55_DIM, dtype=np.float64)
        self.filled: dict[str, bool] = {s.name: False for s in EXTRA_SEGMENTS}

    # ---- 融合 ----------------------------------------------------------------
    def fuse(self, visual_39d, tactile_4d, extra: dict[str, float | Iterable[float]] | None = None,
             extra_12d: Iterable[float] | None = None) -> np.ndarray:
        v = np.asarray(visual_39d, dtype=np.float64).ravel()
        t = np.asarray(tactile_4d, dtype=np.float64).ravel()
        if v.size != VISUAL_DIM:
            raise ValueError("视觉与本体状态必须 %d 维, 收到 %d" % (VISUAL_DIM, v.size))
        if t.size != TACTILE_DIM:
            raise ValueError("触觉力觉必须 %d 维, 收到 %d" % (TACTILE_DIM, t.size))
        e = np.zeros(EXTRA_DIM, dtype=np.float64)
        if extra_12d is not None:
            raw = np.asarray(extra_12d, dtype=np.float64).ravel()
            if raw.size != EXTRA_DIM:
                raise ValueError("预留扩展通道必须 %d 维, 收到 %d" % (EXTRA_DIM, raw.size))
            e = raw
        if extra:
            for k, val in extra.items():
                if k not in SLICE or SLICE[k].start < 43:
                    raise KeyError("未注册的扩展通道: %r (只允许 %s)"
                                   % (k, [s.name for s in EXTRA_SEGMENTS]))
                sl = SLICE[k]
                arr = np.atleast_1d(np.asarray(val, dtype=np.float64)).ravel()
                if arr.size != sl.stop - sl.start:
                    raise ValueError("通道 %s 需要 %d 维, 收到 %d" % (k, sl.stop - sl.start, arr.size))
                e[sl.start - 43:sl.stop - 43] = arr
                self.filled[k] = True
        # 保持 float64: 43D 老口径也是 float64, 强转 float32 会引入 4e-8 级差异 (实测),
        # 那样"前 43 维逐位相同"就不成立 —— 升级必须逐位可对账。
        x = np.concatenate([self.k_obs * v, t, e])
        if x.size != OBS55_DIM:
            raise ValueError("融合结果应为 %d 维, 实际 %d" % (OBS55_DIM, x.size))
        self.current_state = x
        return x

    # ---- 按名取值 ------------------------------------------------------------
    def get(self, name: str, state: np.ndarray | None = None) -> np.ndarray:
        x = self.current_state if state is None else np.asarray(state, dtype=np.float32).ravel()
        if name not in SLICE:
            raise KeyError("未知字段 %r" % name)
        return x[SLICE[name]]

    def get_geometry_error(self) -> np.ndarray:
        """工件 − 孔位 (m)。用户方案写的是 obj[4:7] − hole[36:39] —— 与真实 obs39 布局一致。"""
        return self.get("peg_xyz") - self.get("hole_xyz")

    def to_tensor(self, dtype=None):
        import torch
        return torch.tensor(self.current_state, dtype=dtype or torch.float32).unsqueeze(0)

    # ---- 兼容 ----------------------------------------------------------------
    def awake(self) -> list[str]:
        return [k for k, v in self.filled.items() if v]


# ══════════════════════════════════════════════════════════════════════════════
# 流形数学 (numpy + torch 同口径)
# ══════════════════════════════════════════════════════════════════════════════
def normalize_q(q, eps: float = 1e-9):
    """投回 S³。numpy/torch 通用 (按是否 tensor 分派)。"""
    if hasattr(q, "dim"):                                        # torch
        import torch
        return q / torch.clamp(q.norm(dim=-1, keepdim=True), min=eps)
    a = np.asarray(q, dtype=np.float64)
    n = np.linalg.norm(a, axis=-1, keepdims=True)
    return a / np.maximum(n, eps)


def _qmul_torch(a, b):
    aw, ax, ay, az = a[..., 0], a[..., 1], a[..., 2], a[..., 3]
    bw, bx, by, bz = b[..., 0], b[..., 1], b[..., 2], b[..., 3]
    import torch
    return torch.stack([
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    ], dim=-1)


def geodesic_distance(q1, q2):
    """S³ 上测地线距离 θ ∈ [0, π] —— atan2 形式, 处处可导。

    为什么不用 2·acos(|⟨q1,q2⟩|): q1≈q2 时内积→1, acos'(1)=∞ ⇒ 首个训练步就 NaN。
    atan2 用 |w| 与 ‖v‖ 两个量, 在 (1,0) 处导数有限。
    """
    if hasattr(q1, "dim"):                                       # torch
        import torch
        a = normalize_q(q1)
        b = normalize_q(q2)
        conj = torch.stack([a[..., 0], -a[..., 1], -a[..., 2], -a[..., 3]], dim=-1)
        r = _qmul_torch(conj, b)
        w = r[..., 0].abs()
        v = torch.linalg.norm(r[..., 1:], dim=-1)
        return 2.0 * torch.atan2(v, w)
    a = normalize_q(q1)
    b = normalize_q(q2)
    conj = np.stack([a[..., 0], -a[..., 1], -a[..., 2], -a[..., 3]], axis=-1)
    r = _qmul_np(conj, b)
    w = np.abs(r[..., 0])
    v = np.linalg.norm(r[..., 1:], axis=-1)
    return 2.0 * np.arctan2(v, w)


def _qmul_np(a, b):
    aw, ax, ay, az = a[..., 0], a[..., 1], a[..., 2], a[..., 3]
    bw, bx, by, bz = b[..., 0], b[..., 1], b[..., 2], b[..., 3]
    return np.stack([
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    ], axis=-1)


def slerp_step(q_start, q_target, alpha: float = 0.1):
    """沿 S³ 测地线走一步 (alpha ∈ [0,1]); 三个安全分支:

      θ→0     : sinθ→0, 用线性插值 + 归一化 (slerp 的极限就是它)
      θ→π     : sinθ→0 但方向相反, ��须先取反 q_target (双覆盖)
      其他     : 标准 slerp

    实现要点: 分母**先**加 eps 再除, 而不是先除再用 where 掩盖 —— 后者梯度仍是 inf/NaN。
    """
    is_torch = hasattr(q_start, "dim")
    if is_torch:
        import torch
        a = normalize_q(q_start)
        b = normalize_q(q_target)
        dot = (a * b).sum(dim=-1, keepdim=True)
        b = torch.where(dot < 0, -b, b)                      # 双覆盖: 走短弧
        # 🔴 θ 必须用 atan2 形式算: acos(dot) 在 dot=1 (同姿态) 与 dot=-1 (对跖) 两处导数发散,
        #    即使后来用 where 掩盖, 被掩盖的那条支路里 NaN 仍会经 0*NaN 传回来 (实测复现)。
        conj = torch.stack([a[..., 0], -a[..., 1], -a[..., 2], -a[..., 3]], dim=-1)
        r = _qmul_torch(conj, b)
        theta = 2.0 * torch.atan2(torch.linalg.norm(r[..., 1:], dim=-1, keepdim=True),
                                  r[..., 0].abs().clamp_min(1e-12))
        sin_t = torch.sin(theta).clamp_min(1e-7)
        s0 = torch.sin((1.0 - alpha) * theta) / sin_t
        s1 = torch.sin(alpha * theta) / sin_t
        lin0 = 1.0 - alpha
        lin1 = alpha
        near = (theta < 1e-4).to(a.dtype)
        s0 = near * lin0 + (1 - near) * s0
        s1 = near * lin1 + (1 - near) * s1
        return normalize_q(s0 * a + s1 * b)
    a = normalize_q(q_start)
    b = normalize_q(q_target)
    dot = np.sum(a * b, axis=-1, keepdims=True)
    b = np.where(dot < 0, -b, b)
    conj = np.stack([a[..., 0], -a[..., 1], -a[..., 2], -a[..., 3]], axis=-1)
    r = _qmul_np(conj, b)
    theta = 2.0 * np.arctan2(np.linalg.norm(r[..., 1:], axis=-1, keepdims=True),
                             np.maximum(np.abs(r[..., 0:1]), 1e-12))
    sin_t = np.maximum(np.sin(theta), 1e-9)
    s0 = np.sin((1.0 - alpha) * theta) / sin_t
    s1 = np.sin(alpha * theta) / sin_t
    near = (theta < 1e-6).astype(np.float64)
    s0 = near * (1.0 - alpha) + (1.0 - near) * s0
    s1 = near * alpha + (1.0 - near) * s1
    return normalize_q(s0 * a + s1 * b)


def pad_state(state, dim_from: int, dim_to: int = OBS55_DIM) -> np.ndarray:
    """把低维状态补齐到高维 (后面补 0)。**只用于喂老模型**, 不许反向截断丢数据。"""
    x = np.asarray(state, dtype=np.float32).ravel()
    if x.size == dim_to:
        return x
    if x.size != dim_from or dim_to < dim_from:
        raise ValueError("pad_state 只支持 %d→%d, 收到 %d" % (dim_from, dim_to, x.size))
    return np.concatenate([x, np.zeros(dim_to - dim_from, dtype=np.float32)])


def crop_state(state, dim_to: int) -> np.ndarray:
    """把 55 维裁到老模型要的维度 (前 N 维语义不变 ⇒ 逐位等价)。"""
    x = np.asarray(state, dtype=np.float32).ravel()
    if x.size == dim_to:
        return x
    if x.size < dim_to:
        raise ValueError("crop_state 不能从 %d 补到 %d" % (x.size, dim_to))
    return x[:dim_to]


if __name__ == "__main__":
    us = UnifiedState55D()
    x = us.fuse(np.arange(39.0), np.ones(4), {"temperature": 36.4})
    print("55D ok:", x.shape, "| 工件−孔位 =", np.round(us.get_geometry_error(), 4),
          "| 已唤醒:", us.awake())
    print("分段数:", len(ALL_SEGMENTS), "| 扩展 12 维:", [s.name for s in EXTRA_SEGMENTS])
