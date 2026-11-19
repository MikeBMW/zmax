#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""safe_envelope.py — 真机运动的**硬边界**闸(所有 move 脚本必须先过这里)。

为什么有它(2026-11-19 事故):
  我连着跑两个探针脚本, 第二个脚本把"起点"重新读成**当前位姿**(y=49.1, 已经比原点偏了 180mm),
  然后按模板下发了 x+60mm ⇒ 方向正对中央相机/夹具, 老倪现场急停才停住(实际未动: 差 60.00mm)。
  根因不是"手抖", 是**脚本没有绝对坐标包络** —— 只做了单段位移核验, 没做"这个点在整个工作空间里合不合法"。

口径: 只做坐标判定(不碰控制器), 任何脚本在 moveAppend 之前调 check(tcp_mm) —— 返回 (ok, why)。
边界按现场实测收紧, 宁可拒绝也不要"擦边":
  x  ∈ [ 380, 815 ] mm        815 = 插口底面 811.6 之外 3mm 的硬顶
  y  ∈ [ 150, 330 ] mm        保护中央相机一侧(y<150 会被相机/支架挡住)
  z  ∈ [ 130, 330 ] mm
  另外: x > 760 时要求 |y-229| < 20 且 z ∈ [180,200] —— 这就是插口轴线窄通道,
        只有在这条通道里才允许越过夹具面(758)进入插口区域, 其它任何越界一律拒
"""
from __future__ import annotations

X_LO, X_HI = 380.0, 815.0
Y_LO, Y_HI = 150.0, 330.0
Z_LO, Z_HI = 130.0, 330.0
NEAR_X = 760.0
NEAR_Y = 229.0
NEAR_Y_TOL = 20.0
NEAR_Z_LO, NEAR_Z_HI = 180.0, 200.0


def check(tcp_mm, tag: str = "") -> tuple[bool, str]:
    x, y, z = float(tcp_mm[0]), float(tcp_mm[1]), float(tcp_mm[2])
    if not (X_LO <= x <= X_HI):
        return False, "%s x=%.1f 越界 [%.0f,%.0f]" % (tag, x, X_LO, X_HI)
    if not (Y_LO <= y <= Y_HI):
        return False, "%s y=%.1f 越界 [%.0f,%.0f]" % (tag, y, Y_LO, Y_HI)
    if not (Z_LO <= z <= Z_HI):
        return False, "%s z=%.1f 越界 [%.0f,%.0f]" % (tag, z, Z_LO, Z_HI)
    if x > NEAR_X + 0.5:   # 0.5mm 容差: 插值会带浮点噪声, x=700.0000001 不应被判成"贴近"
        if abs(y - NEAR_Y) > NEAR_Y_TOL:
            return False, "%s x=%.1f 贴近夹具但 |y-229|=%.1f > %.0f" % (tag, x, abs(y - NEAR_Y), NEAR_Y_TOL)
        if not (NEAR_Z_LO <= z <= NEAR_Z_HI):
            return False, "%s x=%.1f 贴近夹具但 z=%.1f 不在 [%.0f,%.0f]" % (tag, x, z, NEAR_Z_LO, NEAR_Z_HI)
    return True, "ok"


def check_path(p_from, p_to, n: int = 10) -> tuple[bool, str]:
    """直线插值逐点过闸(防"两端合法、中途穿夹具")。"""
    for i in range(1, n + 1):
        t = i / float(n)
        p = [p_from[j] + (p_to[j] - p_from[j]) * t for j in range(3)]
        ok, why = check(p, "路径%d/%d" % (i, n))
        if not ok:
            return False, why
    return True, "ok"
