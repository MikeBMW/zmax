"""SE(3) → (p, n∈S², φ∈S¹) 分解: Hopf 纤维化。

口径(2026-11-18 定): 一次回放的完整状态是
    X = ( p ∈ ℝ³,  n ∈ S²,  φ ∈ S¹,  q̇ ∈ TQ,  s ∈ S¹ )
        到哪      朝哪      拧多少   多快      第几成
本模块只管姿态那半边: 单位四元数 q ∈ S³ --Hopf--> 轴 n ∈ S² + 滚转 φ ∈ S¹。
  π(q) = q·k·q̄ ∈ Im ℍ ≅ su(2) ≅ ℝ³ ,  单位约束下 |n| = 1
  纤维 π⁻¹(n) = { q·e^{iθk} } ≅ S¹ (右作用), 右乘只改 φ, 不动 n (实测 1e-16)
为什么拆: 插孔只在乎轴对不对(球面测地角), 完全不在乎滚转 ⇒ 两者必须各有阈值,
混在四元数一个总角里会让"轴偏 3°"和"滚转偏 3°"长得一样, 无法分别处置。

实测标定(215 帧, tools/web/real_traj_joints.json):
  轴步长 中位 1.98° · P95 9.72° · max 16.28°
  总转角 中位 2.53° · P95 14.66°  ⇒ 轴贡献 ~78%
  插入段 #20~#40 平均轴 [0.995,-0.029,0.097] ≈ +X(与"X 从 761 单调增到 811"一致 ⇒ 约定自洽)
  插入期间轴 0.24°/帧、#95~#112 0.17°/帧 ⇒ 准静态, 轴是常量约束不是跟踪量
  放件 #205 轴 4.49°/帧 = 全轨迹最大
"""
from __future__ import annotations

import json
import math
from typing import Iterable, List, Sequence, Tuple

__all__ = ["hopf", "axis_angle_deg", "roll_delta_deg", "axis_err_deg", "roll_err_deg", "decompose"]

Vec3 = Tuple[float, float, float]


def hopf(q: Sequence[float]) -> Tuple[Vec3, float]:
    """单位四元数 q=(w,x,y,z) → (轴 n∈S², 滚转 φ∈[0,2π))。

    n = (2(xz+wy), 2(yz−wx), w²+z²−x²−y²)   —— 与 q·k·q̄ 的向量部分逐位相等
    φ = 2·atan2(z, w)                        —— 绕 n 的滚转(S¹ 坐标)
    """
    w, x, y, z = (float(v) for v in q)
    nrm = math.sqrt(w * w + x * x + y * y + z * z) or 1.0
    w, x, y, z = w / nrm, x / nrm, y / nrm, z / nrm
    n = (2.0 * (x * z + w * y), 2.0 * (y * z - w * x), w * w + z * z - x * x - y * y)
    m = math.sqrt(sum(c * c for c in n)) or 1.0
    n = (n[0] / m, n[1] / m, n[2] / m)
    phi = (2.0 * math.atan2(z, w)) % (2.0 * math.pi)
    return n, phi


def axis_angle_deg(n1: Vec3, n2: Vec3) -> float:
    """S² 上两点的球面距离(大圆角, 度)。段内轴漂移的唯一正确度量。"""
    d = sum(a * b for a, b in zip(n1, n2))
    return math.degrees(math.acos(max(-1.0, min(1.0, d))))


def roll_delta_deg(p1: float, p2: float) -> float:
    """S¹ 上的环绕差(度, 取值 [-180,180])。禁线性相减: 2π 处会翻成 359°。"""
    d = math.degrees(p2 - p1)
    return (d + 180.0) % 360.0 - 180.0


def axis_err_deg(n_now: Vec3, n_ref: Vec3) -> float:
    """轴对齐误差: 当前轴 vs 参考轴(孔轴/示教轴)的球面角。
    符号无关 —— 正反插同一个孔, 误差都是 0 (acos 天然对称)。"""
    return axis_angle_deg(n_now, n_ref)


def roll_err_deg(phi_now: float, phi_ref: float) -> float:
    """滚转误差(带符号): 末端对位用它, 插入期间不该拿它当判据。"""
    return roll_delta_deg(phi_ref, phi_now)


def decompose(quats: Iterable[Sequence[float]]) -> List[dict]:
    """整条轨迹的姿态分解。返回逐帧 {n, phi, dn_deg, dphi_deg}。"""
    out: List[dict] = []
    prev_n, prev_phi = None, None
    for i, q in enumerate(quats):
        n, phi = hopf(q)
        dn = axis_angle_deg(prev_n, n) if prev_n else 0.0
        dphi = roll_delta_deg(prev_phi, phi) if prev_phi is not None else 0.0
        out.append({"i": i, "n": [round(c, 6) for c in n], "phi_deg": round(math.degrees(phi), 3),
                    "dn_deg": round(dn, 3), "dphi_deg": round(dphi, 3)})
        prev_n, prev_phi = n, phi
    return out


def _cli() -> int:
    import sys

    src = sys.argv[1] if len(sys.argv) > 1 else "tools/web/real_traj_joints.json"
    dst = sys.argv[2] if len(sys.argv) > 2 else "zmax_data/rokae_sdk/traj_hopf.json"
    fr = json.load(open(src))["frames"]
    quats = [f["q"] for f in fr]
    rows = decompose(quats)
    for i, r in enumerate(rows):
        p = fr[i]["p"]
        r["p_mm"] = [round(v * 1000.0, 2) for v in p]
    dn = sorted(r["dn_deg"] for r in rows)
    dp = sorted(abs(r["dphi_deg"]) for r in rows)
    summary = {
        "src": src, "n": len(rows),
        "convention": "q=(w,x,y,z) 原样解读; 插入段平均轴 ≈ +X 已自洽校验",
        "dn_deg": {"median": round(dn[len(dn) // 2], 3), "p95": round(dn[int(len(dn) * .95)], 3),
                   "max": round(dn[-1], 3)},
        "abs_dphi_deg": {"median": round(dp[len(dp) // 2], 3), "p95": round(dp[int(len(dp) * .95)], 3),
                         "max": round(dp[-1], 3)},
        "worst_axis": sorted(rows, key=lambda r: -r["dn_deg"])[:5],
        "worst_roll": sorted(rows, key=lambda r: -abs(r["dphi_deg"]))[:5],
    }
    json.dump({"summary": summary, "frames": rows}, open(dst, "w"), ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print("→", dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
