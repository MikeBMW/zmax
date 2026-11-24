# -*- coding: utf-8 -*-
"""calabi_yau.py — 六维卡拉比-丘流形的实二维切面 (孔洞 = 亏格)

口径(为什么是"切面"而不是"画个 CY 形状"):
    十维引擎的隐藏部分 M6 在数学上是复三维(实六维)的卡拉比-丘型空间 (c₁=0, Ricci-flat)。
    复三维无法直接画, 所以取**标准的复二维切面**: 五次 Fermat 超曲面
        Q : z₁⁵ + z₂⁵ + z₃⁵ + z₄⁵ + z₅⁵ = 0 ⊂ CP⁴
    在仿射图 (z₄=z₃=1, z₅=0) 上的切片就是五次平面曲线
        C : x⁵ + y⁵ = 1,   x,y ∈ ℂ
    它是**实二维**的黎曼面 —— 这才是能画出来的东西。它的"孔洞"不是画上去的装饰,
    而是拓扑亏格 g:

        Riemann–Hurwitz:  2g − 2 = n(2g_x − 2) + Σ_p (e_p − 1)
        x ↦ (x,y) 是 5 重覆盖 (解 y 的 5 个分支), 基曲线 CP¹ 的 g_x = 0, n = 5;
        分歧点 = {x : 1 − x⁵ = 0} 共 5 个, 每个 e_p = 5 (全分歧)
        ⇒ 2g − 2 = 5(−2) + 5·(5−1) = −10 + 20 = 10 ⇒ **g = 6**

    所以"六维流形的切面有六个孔洞"是可算的结论, 不是比喻。本模块同时给出
    ① 网格 (5 个分支的真实解, 逐点满足 x⁵+y⁵=1) ② 亏格推导 ③ 自检。

投影 (ℂ² → ℝ³): (Re x, Im x, Re y), 另存 Im y 作为着色量 —— 四个实方向压到三维必然丢信息,
所以额外把 Im y 画成色带, 这样"五瓣 + 贯穿孔"在视觉上不会互相穿模。
"""
from __future__ import annotations

import json
import math

import numpy as np

DEGREE = 5
N_BRANCH = 5


def genus_riemann_hurwitz(n: int = DEGREE, g_base: int = 0,
                          branch_points: int = N_BRANCH, ram: int = DEGREE) -> int:
    """2g−2 = n(2g_base−2) + Σ(e_p−1)  ⇒  g"""
    chi = n * (2 * g_base - 2) + branch_points * (ram - 1)
    g = (chi + 2) // 2
    assert 2 * g - 2 == chi, "Riemann–Hurwitz 不整除 ⇒ 参数错"
    return int(g)


def branch_points() -> list:
    """1 − x⁵ = 0 的 5 个分歧点 (复数)"""
    return [complex(math.cos(2 * math.pi * k / N_BRANCH), math.sin(2 * math.pi * k / N_BRANCH))
            for k in range(N_BRANCH)]


def quintic_slice_mesh(n_rad: int = 26, n_ang: int = 96, r_max: float = 1.55,
                       tilt: float = 0.35) -> dict:
    """把 C : x⁵+y⁵=1 采样成 5 张实曲面 (每张 = 一个 y 分支), 投影到 ℝ³。

    参数化: x = r e^{iθ} (极坐标, 以 |x|=1 的分歧圆为界), y_k = (1−x⁵)^{1/5}·ω^k, ω = e^{2πi/5}
    返回: V(顶点 ℝ³, float) · SHEET(顶点属于哪一张) · IMP(Im y, 着色) · F(三角面, 每个顶点索引)
          · R(该点的 |x⁵+y⁵−1| 残差最大值, 用来证明"点真在流形上")
    """
    omega = complex(math.cos(2 * math.pi / N_BRANCH), math.sin(2 * math.pi / N_BRANCH))
    rs = np.linspace(0.02, r_max, n_rad)
    ths = np.linspace(0.0, 2 * math.pi, n_ang, endpoint=False)

    V, SHEET, IMP, IDX = [], [], [], []
    RX, IX, RY, IY = [], [], [], []          # 四个实分量, 供换投影复核 (ℂ² → ℝ³ 丢一维)
    resid_max = 0.0
    for k in range(N_BRANCH):
        base = len(V)
        for r in rs:
            for th in ths:
                x = complex(r * math.cos(th), r * math.sin(th))
                w = 1.0 - x ** 5
                y = (abs(w) ** (1.0 / 5.0)) * complex(math.cos(math.atan2(w.imag, w.real) / 5.0),
                                                      math.sin(math.atan2(w.imag, w.real) / 5.0))
                y *= omega ** k
                resid = abs(x ** 5 + y ** 5 - 1.0)
                resid_max = max(resid_max, resid)
                V.append([x.real, x.imag, y.real + tilt * y.imag])
                RX.append(x.real); IX.append(x.imag); RY.append(y.real); IY.append(y.imag)
                SHEET.append(k)
                IMP.append(y.imag)
        # 三角面: 极坐标网格 (r,θ) → 环带
        for i in range(n_rad - 1):
            for j in range(n_ang):
                a = base + i * n_ang + j
                b = base + i * n_ang + (j + 1) % n_ang
                c = base + (i + 1) * n_ang + j
                d = base + (i + 1) * n_ang + (j + 1) % n_ang
                IDX += [[a, b, d], [a, d, c]]
    V = np.asarray(V, float)
    return {"V": V, "SHEET": np.asarray(SHEET, int), "IMP": np.asarray(IMP, float),
            "RX": np.asarray(RX, float), "IX": np.asarray(IX, float),
            "RY": np.asarray(RY, float), "IY": np.asarray(IY, float),
            "F": np.asarray(IDX, int), "resid_max": float(resid_max),
            "meta": {"curve": "x^5 + y^5 = 1 (Fermat quintic 仿射切片)",
                     "ambient": "CY3 ⊂ CP^4 的复二维切面 ⇒ 实二维黎曼面",
                     "degree": DEGREE, "sheets": N_BRANCH,
                     "genus": genus_riemann_hurwitz(),
                     "branch_points": [ [p.real, p.imag] for p in branch_points() ],
                     "n_rad": n_rad, "n_ang": n_ang, "r_max": r_max}}


def to_obj(mesh: dict) -> str:
    """导出 OBJ (给 Blender/MeshLab 复核用)"""
    out = ["# Calabi-Yau slice: x^5 + y^5 = 1  (genus 6)",
           "# sheet 1..5 = 5 branches of y = (1-x^5)^(1/5)"]
    for (x, y, z), s in zip(mesh["V"], mesh["SHEET"]):
        out.append("v %.6f %.6f %.6f" % (x, y, z))
    for tri, s0 in zip(mesh["F"], mesh["F"][:, 0]):
        out.append("f %d %d %d" % (tri[0] + 1, tri[1] + 1, tri[2] + 1))
    return "\n".join(out) + "\n"


def selftest(verbose: bool = True) -> dict:
    """自检: 亏格推导 / 点是否真在流形上 / 分支点 / 网格规模 —— 失败抛 AssertionError"""
    g = genus_riemann_hurwitz()
    bp = branch_points()
    mesh = quintic_slice_mesh()
    res = {"genus": g, "branch_points": len(bp), "resid_max": mesh["resid_max"],
           "verts": int(len(mesh["V"])), "tris": int(len(mesh["F"]))}
    assert g == 6, "五次平面曲线的亏格必须是 6, 算得 %d" % g
    assert len(bp) == 5, "分歧点必须是 5 个"
    for p in bp:                       # 分歧点必须真满足 1−x⁵=0
        assert abs(1 - p ** 5) < 1e-12, "分歧点不在 1−x⁵=0 上"
    assert mesh["resid_max"] < 1e-9, "采样点不在 x⁵+y⁵=1 上: 残差 %.2e" % mesh["resid_max"]
    assert res["verts"] > 5000 and res["tris"] > 10000, "网格太稀"
    # 每个分支都必须真的分开 (不是 5 张重合的片)
    xs = mesh["V"][mesh["SHEET"] == 0]
    ys = mesh["V"][mesh["SHEET"] == 1]
    assert not np.allclose(xs, ys), "两个分支重合 ⇒ 分支没取到"
    res["ok"] = True
    if verbose:
        print("  ┌ 卡拉比-丘切面自检")
        print("  │ 曲线: x⁵ + y⁵ = 1 (Fermat 五次, 复二维切面 → 实二维)")
        print("  │ 分歧点: %d 个 (1−x⁵=0, 每个 e=5)" % len(bp))
        print("  │ Riemann–Hurwitz: 2g−2 = 5(−2) + 5·4 = 10 ⇒ g = %d (六个孔洞)" % g)
        print("  │ 采样点残差 max |x⁵+y⁵−1| = %.2e (点真在流形上)" % mesh["resid_max"])
        print("  │ 网格: %d 顶点 / %d 三角面 / 5 个分支" % (res["verts"], res["tris"]))
        print("  └ 通过 ✓")
    return res


if __name__ == "__main__":
    import sys
    if "--obj" in sys.argv:
        i = sys.argv.index("--obj")
        p = sys.argv[i + 1] if len(sys.argv) > i + 1 else "/tmp/cy_slice.obj"
        open(p, "w").write(to_obj(quintic_slice_mesh()))
        print("写出", p)
    else:
        r = selftest()
        print(json.dumps(r, ensure_ascii=False))
