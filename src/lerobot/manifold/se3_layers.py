"""SE(3) 分层几何: 把 A/B/C/D/E 五个流形接进流形引擎。

状态口径(2026-11-18 定案):
    X = ( p ∈ ℝ³,  n ∈ S²,  φ ∈ S¹,  q̇ ∈ TQ,  s ∈ S¹ )
        到哪       朝哪       拧多少     多快      第几成

    A 位置   ℝ³   euclidean  (无约束, 度量=欧氏 mm)
    B 轴     S²   sphere     (大圆角; n = R·e₁, 单位约束)
    C 四元数 S³   su2        (群流形; Hopf 全空间, q 双覆盖 ⇒ 距离用 |q·q̂|)
    D 滚转   S¹   torus      (退化切片: 点取 [φ, 0], 距离=T² 上的环绕距离)
    E 相位   S¹   torus      (退化切片: 点取 [2πs, 0], s 为弧长真相位)
    TQ 速度  —    切空间     (不是流形: δp/δn/δφ/δs 的导数, 只观测不下发)

每层都是一个**真的 ManifoldEngine 实例**(projector/metric/navigator 都在用), 不是常量表。
唯一例外写在 C 层注释里: 引擎的 su2 投影器走 ``bounded_rotvec(gain=2.0)``, 那是有界控制器
映射(会把转角压缩), 不是投影 ⇒ C 的几何口径用 S³ 恒等归一, 引擎 su2 的**度量**照用。

与固定轨迹的关系(为什么要这么接):
    · 安全由结构保证 —— 相位 s 由录制轨迹的弧长给出, 目标点永远从轨迹插值, 不在管内不可能
    · 模型只提议 Δs(见 tools/se3_safe_policy.py), 五流形是**观测/闸门**, 不改指令
"""
from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path
from typing import Sequence

import numpy as np

try:                                                     # 包内导入 (引擎路径)
    from .se3_hopf import (axis_angle_deg, hopf, hopf_join, q_normalize, quat_angle_deg,
                           roll_delta_deg, slerp, R_from_q)
except ImportError:                                      # 裸脚本运行 (python3 se3_layers.py)
    from se3_hopf import (axis_angle_deg, hopf, hopf_join, q_normalize,  # type: ignore
                          quat_angle_deg, roll_delta_deg, slerp, R_from_q)

ROOT = Path(__file__).resolve().parents[3]
TRAJ = ROOT / "tools/web/real_traj_joints.json"
PHASE = ROOT / "zmax_data/rokae_sdk/traj_phase.json"
HOPFJ = ROOT / "zmax_data/rokae_sdk/traj_hopf.json"
OUTDIR = ROOT / "zmax_data/se3_layers"

# 层规格: 与 MANIFOLD_REGISTRY 的 type 一一对应 (A/B/C/D/E ⇒ 5 个真引擎实例)
SPEC = {
    "A": {"type": "euclidean", "dim": 3, "name": "位置 ℝ³", "unit": "mm"},
    "B": {"type": "sphere", "dim": 2, "name": "轴 S²", "unit": "°"},
    "C": {"type": "su2", "dim": 3, "name": "四元数 S³", "unit": "°"},
    "D": {"type": "torus", "dim": 1, "name": "滚转 S¹", "unit": "°"},
    "E": {"type": "torus", "dim": 1, "name": "相位 S¹", "unit": "%"},
}
LAYERS = ("A", "B", "C", "D", "E")


def _load_engine_cls():
    try:
        from .manifold_engine import ManifoldEngine      # 正常包内导入
        return ManifoldEngine
    except Exception:                                    # noqa: BLE001  裸脚本运行
        import importlib.util
        p = Path(__file__).with_name("manifold_engine.py")
        spec = importlib.util.spec_from_file_location("manifold_engine_solo", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)                     # type: ignore[union-attr]
        return mod.ManifoldEngine


class SE3Layered:
    """五流形编排器: 每层一个真引擎实例 + Hopf 耦合 + 弧长相位。"""

    def __init__(self, traj: str | Path = TRAJ, phase: str | Path = PHASE,
                 hopf_ref: str | Path = HOPFJ, M: float = 3.643, lazy: bool = True) -> None:
        ManifoldEngine = _load_engine_cls()
        self.traj_path, self.phase_path, self.hopf_ref = Path(traj), Path(phase), Path(hopf_ref)
        self.M = float(M)
        # 五层引擎: **每层独立实例** (各自的 projector/metric/navigator), 不共用潜空间
        self.eng = {k: ManifoldEngine(manifold_type=SPEC[k]["type"], latent_dim=max(SPEC[k]["dim"], 3),
                                      state_dim=SPEC[k]["dim"], action_dim=1, manifold_M=self.M)
                    for k in LAYERS}
        self.ready = {k: bool(self.eng[k].projector.ready) for k in LAYERS}
        self._frames = None
        self._phase = None
        self._hopf_ref = None
        self.lazy = bool(lazy)
        self.stats: dict = {}

    # ── 数据 ────────────────────────────────────────────────────────────────
    def frames(self) -> list[dict]:
        if self._frames is None:
            self._frames = json.load(open(self.traj_path))["frames"]
        return self._frames

    def phase_tab(self) -> list[dict]:
        if self._phase is None:
            d = json.load(open(self.phase_path))
            rows = d.get("frames") or d.get("rows") or []
            self._phase = rows
        return self._phase

    def phase_of(self, i: int) -> float:
        """弧长真相位 s ∈ [0,1) —— 与 tools/se3_phase.py 同源(盘上 JSON, 不重算)。"""
        rows = self.phase_tab()
        if not rows:
            return float(i) / max(1, len(self.frames()) - 1)
        for r in rows:
            if int(r.get("i", -1)) == int(i):
                return float(r.get("s", 0.0)) % 1.0
        return float(i) / max(1, len(self.frames()) - 1)

    def hopf_ref_rows(self) -> list[dict]:
        if self._hopf_ref is None:
            try:
                self._hopf_ref = json.load(open(self.hopf_ref))["frames"]
            except Exception:                            # noqa: BLE001
                self._hopf_ref = []
        return self._hopf_ref

    # ── 五层几何算子 (每层调对应子引擎) ───────────────────────────────────────
    def to_point(self, layer: str, x) -> np.ndarray:
        """把物理量换成本层流形的坐标表示 (投影的输入口径)。"""
        if layer == "A":
            return np.asarray(x, float).ravel()[:3]
        if layer == "B":
            return np.asarray(x, float).ravel()[:3]
        if layer == "C":
            return np.asarray(x, float).ravel()[:4]
        if layer == "D":                                  # 退化切片 S¹×{0} ⊂ T²
            v = float(np.asarray(x, float).ravel()[0])
            return np.array([v % (2 * math.pi), 0.0])
        if layer == "E":
            v = float(np.asarray(x, float).ravel()[0])
            return np.array([(v % 1.0) * 2 * math.pi, 0.0])
        raise KeyError(layer)

    def project(self, layer: str, x) -> tuple[np.ndarray, float, dict]:
        """投影到本层流形, 返回 (点, 约束残差, meta)。残差≈0 才算投影器对。"""
        z = self.to_point(layer, x)
        if layer == "C":            # S³ 恒等归一 (见模块 docstring: 不用 bounded_rotvec)
            q = np.asarray(q_normalize(z), float)
            return q, abs(float(np.linalg.norm(q)) - 1.0), {"layer": "C", "src": "S³ 恒等归一",
                                                             "engine_metric": "su2(e8ds)", "drift": 0.0}
        p, resid, meta = self.eng[layer].projector.project(z)
        meta = {**meta, "layer": layer, "engine_type": SPEC[layer]["type"]}
        return np.asarray(p, float), float(resid), meta

    def distance(self, layer: str, a, b) -> float:
        """本层度量的距离。A:mm · B:°(大圆角) · C:°(SU(2) 双覆盖) · D/E:°(S¹ 环绕)。"""
        pa, pb = self.to_point(layer, a), self.to_point(layer, b)
        if layer == "C":
            return quat_angle_deg(pa, pb)
        d = float(self.eng[layer].metric.distance(pa, pb))
        return math.degrees(d) if layer in ("B", "D", "E") else d

    def geodesic(self, layer: str, a, b, t: float) -> np.ndarray:
        """本层测地线 (A 直线 · B 球面 slerp · C S³ slerp · D/E S¹ 最短弧)。"""
        pa, pb = self.to_point(layer, a), self.to_point(layer, b)
        t = float(t)
        if layer == "A":
            return (1 - t) * pa + t * pb
        if layer in ("B", "C"):
            if layer == "B":                              # 单位向量 slerp
                c = float(np.clip(np.dot(pa, pb), -1, 1))
                if c > 0.999999:
                    v = (1 - t) * pa + t * pb
                    return v / (np.linalg.norm(v) or 1.0)
                th = math.acos(c)
                return (math.sin((1 - t) * th) * pa + math.sin(t * th) * pb) / math.sin(th)
            return np.asarray(slerp(pa, pb, t), float)
        if layer == "D":
            d = math.radians(roll_delta_deg(pa[0], pb[0]))
            return np.array([(pa[0] + t * d) % (2 * math.pi), 0.0])
        if layer == "E":                                  # 回到 s 空间(点坐标即 s∈[0,1))
            d = (pb[0] - pa[0] + math.pi) % (2 * math.pi) - math.pi
            return np.array([((pa[0] + t * d) % (2 * math.pi)) / (2 * math.pi)])
        raise KeyError(layer)

    # ── Hopf: C ⇄ B + D ─────────────────────────────────────────────────────
    def split_C(self, q) -> tuple[np.ndarray, float]:
        n, phi = hopf(q)
        return np.asarray(n, float), float(phi)

    def join_BD(self, n, phi: float) -> np.ndarray:
        return np.asarray(hopf_join(n, phi), float)

    # ── 实时快照 (引擎每拍调用) ───────────────────────────────────────────────
    def snapshot(self, i: int | None = None, p_mm=None, q=None, j_deg=None) -> dict:
        """给一拍状态出五层几何量。p_mm(mm) / q(x,y,z,w) / j_deg(6 关节角)。"""
        t0 = time.perf_counter()
        fr = self.frames()
        if i is None:
            i = len(fr) - 1
        i = int(max(0, min(i, len(fr) - 1)))
        if p_mm is None:
            p_mm = np.asarray(fr[i]["p"], float) * 1000.0
        else:
            p_mm = np.asarray(p_mm, float).ravel()[:3]
        if q is None:
            q = fr[i]["q"]
        qv = np.asarray(q_normalize(q), float)
        n, phi = self.split_C(qv)
        s = self.phase_of(i)

        out: dict = {"i": i, "t": round(time.time(), 3), "ms": {}}
        t1 = time.perf_counter()
        for L, x in (("A", p_mm), ("B", n), ("C", qv), ("D", phi), ("E", s)):
            pt, resid, meta = self.project(L, x)
            out[L] = {"x": [round(float(v), 6) for v in pt], "resid": float(f"{resid:.3e}"),
                      "type": SPEC[L]["type"], "name": SPEC[L]["name"]}
            out["ms"][L] = round((time.perf_counter() - t1) * 1000.0, 3)
        out["A"].update({"mm": [round(float(v), 2) for v in p_mm]})
        out["B"].update({"n": [round(float(v), 6) for v in n]})
        out["C"].update({"q": [round(float(v), 6) for v in qv],
                         "theta_deg": round(quat_angle_deg((0, 0, 0, 1), qv), 3)})
        out["D"].update({"phi_deg": round(math.degrees(phi), 3)})
        out["E"].update({"s": round(s, 6), "s_pct": round(s * 100.0, 2),
                         "s_mm": round(s * 7861.8, 1)})

        # TQ 切空间: 只观测, 不下发
        TQ: dict = {"src": "traj j/dt (Δ 到上一帧)", "note": "切空间不是流形; 跨点不可比, 需逐块重锚"}
        if i > 0:
            j0 = fr[i - 1].get("j") or j_deg
            j1 = fr[i].get("j") if j_deg is None else j_deg
            if j0 is not None and j1 is not None:
                dt = float(fr[i].get("t", 0)) - float(fr[i - 1].get("t", 0)) or 0.2
                TQ["dq_deg_s"] = [round(abs(float(b) - float(a)) / dt, 2) for a, b in zip(j0, j1)]
            dp = (p_mm - np.asarray(fr[i - 1]["p"], float) * 1000.0)
            TQ["dp_mm_s"] = round(float(np.linalg.norm(dp)) / (float(fr[i].get("t", 0)) -
                                                               float(fr[i - 1].get("t", 0)) or 0.2), 2)
        out["TQ"] = TQ
        out["layers_ready"] = self.ready
        out["ms"]["total"] = round((time.perf_counter() - t0) * 1000.0, 3)
        return out

    # ── 判据: 每层几何是不是真的 (不是占位) ───────────────────────────────────
    def selftest(self, max_pairs: int = 214) -> dict:
        fr = self.frames()
        res: dict = {"n_frames": len(fr), "layers": {}, "criteria": {}}
        qs = [f["q"] for f in fr]
        ns, phis = [], []
        for q in qs:
            n, phi = self.split_C(q)
            ns.append(n)
            phis.append(phi)

        # ① 投影残差 (每层随机 40 帧)
        idx = list(range(0, len(fr), max(1, len(fr) // 40)))[:40]
        proj = {}
        for L in LAYERS:
            worst = 0.0
            for i in idx:
                x = {"A": np.asarray(fr[i]["p"], float) * 1000.0, "B": ns[i], "C": qs[i],
                     "D": phis[i], "E": self.phase_of(i)}[L]
                _, r, _ = self.project(L, x)
                worst = max(worst, abs(r))
            proj[L] = round(worst, 12)
        res["criteria"]["project_residual_worst"] = proj

        # ② 测地线中点 = 距离一半 (每层 60 对相邻帧)
        geo = {}
        for L in LAYERS:
            worst = 0.0
            for i in range(0, min(len(fr) - 1, max_pairs), 3)[:60]:
                a = {"A": np.asarray(fr[i]["p"], float) * 1000.0, "B": ns[i], "C": qs[i],
                     "D": phis[i], "E": self.phase_of(i)}[L]
                b = {"A": np.asarray(fr[i + 1]["p"], float) * 1000.0, "B": ns[i + 1], "C": qs[i + 1],
                     "D": phis[i + 1], "E": self.phase_of(i + 1)}[L]
                d = self.distance(L, a, b)
                if not (0.5 < d < 150.0):                 # 零距离/近对跖: 中点数值敏感, 不算判据
                    continue
                m = self.geodesic(L, a, b, 0.5)
                worst = max(worst, abs(self.distance(L, a, m) - d / 2.0) / max(d, 1e-9))
            geo[L] = round(worst, 9)
        res["criteria"]["geodesic_half_rel_err"] = geo

        # ③ Hopf 往返 S³ → S²×S¹ → S³ (单位: 度)
        rt = 0.0
        for q in qs:
            n, phi = self.split_C(q)
            rt = max(rt, quat_angle_deg(q, self.join_BD(n, phi)))
        res["criteria"]["hopf_roundtrip_deg_max"] = round(rt, 9)

        # ④ n 与 R·e₁ 一致 (分解自洽, 不是另一个约定)
        nerr = 0.0
        for q in qs[:60]:
            R = R_from_q(q)
            col = np.array([R[0][2], R[1][2], R[2][2]])       # e₃ 列 = 工具接近轴
            n, _ = self.split_C(q)
            nerr = max(nerr, float(np.degrees(np.arccos(np.clip(np.dot(col, n), -1, 1)))))
        res["criteria"]["n_vs_Rcol_deg_max"] = round(nerr, 9)

        # ⑤ 与权威工具对账 (traj_hopf.json 的 215 帧)
        ref = self.hopf_ref_rows()
        if ref:
            dn = max(abs(axis_angle_deg(ns[i], ref[i]["n"])) for i in range(min(len(ref), len(ns))))
            # ⚠ 参考文件里 n 只存 6 位小数; arccos 在 dot→1 处把 1e-6 的舍入放大成 ~0.06°,
            #    所以对账看**分量最大差** (真判据), 角度只作参考
            dcomp = max(abs(float(ns[i][k]) - float(ref[i]["n"][k]))
                        for i in range(min(len(ref), len(ns))) for k in range(3))
            dp = max(abs(roll_delta_deg(math.degrees(phis[i]), ref[i]["phi_deg"]))
                     for i in range(min(len(ref), len(phis))))
            res["criteria"]["vs_traj_hopf"] = {"axis_deg_max": round(dn, 6), "roll_deg_max": round(dp, 6),
                                               "n_comp_max_abs": round(dcomp, 12),
                                               "note": "参考 n 存 6 位小数 ⇒ axis_deg_max 受 arccos 放大, 以 n_comp_max_abs<2e-6 为准",
                                               "n_ref": min(len(ref), len(ns))}

        # ⑥ S¹ 跨 ±π 环绕 (合成)
        res["criteria"]["s1_wrap"] = {"a_deg": 179.0, "b_deg": -179.0,
                                      "delta_deg": round(roll_delta_deg(math.radians(179.0),
                                                                       math.radians(-179.0)), 6),
                                      "expected": 2.0}

        # ⑦ 相位单调 + 闭合
        ss = [self.phase_of(i) for i in range(len(fr))]
        back = sum(1 for i in range(1, len(ss)) if ss[i] + 1e-9 < ss[i - 1])
        res["criteria"]["phase"] = {"n": len(ss), "s_first": round(ss[0], 6), "s_last": round(ss[-1], 6),
                                    "back_steps": back, "closure_err": round(abs(ss[-1] - 1.0), 6)}

        # ⑧ 层耗 (每拍)
        t0 = time.perf_counter()
        for i in idx:
            self.snapshot(i)
        res["criteria"]["snapshot_ms_per_call"] = round((time.perf_counter() - t0) * 1000.0 / len(idx), 3)

        res["layers"] = {k: {"engine_type": SPEC[k]["type"], "dim": SPEC[k]["dim"],
                             "name": SPEC[k]["name"], "projector_ready": self.ready[k],
                             "metric_src": "su2(e8ds)" if k == "C" else f"ManifoldEngine({SPEC[k]['type']})"}
                         for k in LAYERS}
        res["M"] = self.M
        vs = res["criteria"].get("vs_traj_hopf", {})
        res["ok"] = bool(all(v < 1e-8 for v in proj.values())
                         and all(v < 1e-6 for v in geo.values())
                         and rt < 1e-5 and nerr < 1e-5                  # 往返/自洽 (度)
                         and vs.get("n_comp_max_abs", 0.0) < 2e-6        # 与权威工具对账(分量)
                         and res["criteria"]["phase"]["back_steps"] == 0
                         and res["criteria"]["s1_wrap"]["delta_deg"] == 2.0)
        res["thresholds"] = {"project_residual": 1e-8, "geodesic_half_rel": 1e-6,
                             "hopf_roundtrip_deg": 1e-5, "n_vs_Rcol_deg": 1e-5,
                             "vs_traj_hopf_comp": 2e-6, "phase_back_steps": 0}
        self.stats = res
        return res


def dump_layers(layered: SE3Layered, outdir: Path = OUTDIR) -> dict:
    """把 215 帧的五层几何落盘 (数据留存, 看板/复算都用它)。"""
    outdir.mkdir(parents=True, exist_ok=True)
    rows = []
    for i in range(len(layered.frames())):
        snap = layered.snapshot(i)
        rows.append({"i": i, "A_mm": snap["A"]["mm"], "B_n": snap["B"]["n"],
                     "C_q": snap["C"]["q"], "C_theta_deg": snap["C"]["theta_deg"],
                     "D_phi_deg": snap["D"]["phi_deg"], "E_s": snap["E"]["s"],
                     "TQ": snap["TQ"]})
    doc = {"src": str(layered.traj_path), "n": len(rows),
           "convention": "X=(p∈ℝ³, n∈S², φ∈S¹, q̇∈TQ, s∈S¹); q=(x,y,z,w); n=R·e₁",
           "layers": layered.selftest()["layers"], "M": layered.M, "frames": rows}
    p1 = outdir / "layers_215.json"
    json.dump(doc, open(p1, "w"), ensure_ascii=False)
    st = layered.stats
    json.dump(st, open(outdir / "selftest.json", "w"), ensure_ascii=False, indent=1)
    return {"layers_215": str(p1), "selftest": str(outdir / "selftest.json"), "n": len(rows)}


def _cli() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="SE(3) 五流形 ↔ 流形引擎: 自检 / 落盘 / 单帧")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--frame", type=int, default=None)
    a = ap.parse_args()
    L = SE3Layered()
    if a.frame is not None:
        print(json.dumps(L.snapshot(a.frame), ensure_ascii=False, indent=1))
    if a.selftest or not a.dump:
        print(json.dumps(L.selftest(), ensure_ascii=False, indent=1))
    if a.dump:
        print(json.dumps(dump_layers(L), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
