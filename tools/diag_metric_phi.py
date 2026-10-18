#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""为什么度规势 Φ=½·arccos|⟨p,g⟩|² 反而让方向一致性从 0.80 掉到 0.28?
直接量 Φ 的梯度在 |c|=⟨p,g⟩ 取不同值时的行为 (Fubini–Study 的绝对值在 c=0 处有尖点)。"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from lerobot.manifold.manifold_engine import ManifoldEngine  # noqa: E402


def unit(v):
    return v / max(float(np.linalg.norm(v)), 1e-12)


rng = np.random.default_rng(7)
g = unit(rng.normal(size=4))
print("p 与 goal 夹角 → 两种势的梯度方向 (与测地方向的 cos) 和 ||∇Φ||")
print("%-8s %-8s | %-26s | %-26s" % ("c=|⟨p,g⟩|", "θ(deg)", "欧氏势 cos / ‖∇‖", "度规势 cos / ‖∇‖"))
print("-" * 84)

for c_target in (0.999, 0.99, 0.9, 0.7, 0.5, 0.3, 0.1, 0.02, 0.001, 0.0):
    # 造一个与 g 夹角余弦为 c_target 的 p
    perp = unit(rng.normal(size=4))
    perp = unit(perp - g * float(np.dot(perp, g)))
    p = unit(c_target * g + np.sqrt(max(0.0, 1 - c_target ** 2)) * perp)

    row = []
    for phi_m in (False, True):
        e = ManifoldEngine(manifold_type="su2", latent_dim=16, state_dim=39, action_dim=4,
                           homeostasis=False, phi_metric=phi_m, su2_tangent=False)
        e.fitted = True
        e.current_manifold_point = p
        e.goal_point = g
        gf = e.gradient_flow()
        grad = np.asarray(gf["grad"], float)
        ng = float(np.linalg.norm(grad))
        c = float(np.dot(p, g))
        toward = g - c * p                     # 测地方向 (切空间, 指向 goal)
        nt = float(np.linalg.norm(toward))
        cos = float(np.dot(-grad, toward)) / (ng * nt) if ng > 1e-12 and nt > 1e-12 else float("nan")
        row.append("%s%.4f / %.4g" % (" " if abs(cos) < 2 else "", cos, ng))
    print("%-8.4f %-8.1f | %-26s | %-26s"
          % (c_target, np.degrees(np.arccos(min(1.0, c_target))), row[0], row[1]))

print("-" * 84)
print("判读: 度规势在 c→0 附近 cos 崩坏 ⇒ Fubini–Study 用 |⟨p,g⟩|, 绝对值在 0 处不可导,")
print("      且 arccos 导数 1/√(1−c²) 在 c→0 处有限但符号由 sign(c) 决定 ⇒ 中心差分跨过尖点即失真。")
