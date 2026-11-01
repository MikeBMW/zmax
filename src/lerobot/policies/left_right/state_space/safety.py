"""safety.py — 安全执行边界 (状态空间模型画布)

饱和限幅: 任何融合后的动作先过限幅再下发执行器。

双层安全:
  认知层否决权 (cognition.py) — 决策层看语义 (残差/接触概率)
  物理限幅 (本模块)          — 执行层卡物理 (速度/力/位置上限)
"""
import numpy as np

# 物理限幅 (默认: 与状态机标定一致)
VEL_LIMIT = 1.0     # 速度上限
FORCE_LIMIT = 5.0   # 力上限 (N) — 金手指保护 ≤2N 过盈段力控
POS_LIMIT = 0.6     # 位置/动作幅值上限


def saturate(u, limit=POS_LIMIT):
    """饱和限幅: 只裁**平移 3 维**; 夹爪通道按 [0,1] 单独裁。

    🔴 2026-11-01 老倪「要真接入」实测抓到的真 bug: 原来整条 clip(−0.6,0.6) 把夹爪 1.1 裁成 0.6
    ⇒ 夹紧力被悄悄砍掉一半, 且夹爪本就不是速度量 (0=张 1=夹)。
    """
    a = np.asarray(u, dtype=float).ravel().copy()
    if a.size >= 3:
        a[:3] = np.clip(a[:3], -limit, limit)
    if a.size >= 4:
        a[3] = float(np.clip(a[3], 0.0, 1.0))
    return a
