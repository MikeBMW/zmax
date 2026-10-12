# -*- coding: utf-8 -*-
"""🩺 流形引擎健康度 H (老倪 2026-10-12 设计口径) —— 从度量张量算"体系健不健康"。

老倪口径 (原文摘要):
> 健康度: H = (1/κ)·λ_min, κ = λ_max/λ_min (λ 为度量张量特征值, eigvalsh)。
>   分级: H>0.5 优秀 / 0.1~0.5 良好 / 0.01~0.1 警告 / ≤0.01 危险。
>   λ_min 决定稳不稳, λ_max 决定快不快, κ 决定各向同性。
>   还要报 anisotropy = std(λ)/mean(λ)。

物理读法 (为什么这么定义):
  · λ_min (最小特征值) = 度量在该方向上的"最小惯量尺度" ⇒ **稳不稳** (越小 ⇒ 越容易跑飞);
  · λ_max (最大特征值) = 最大尺度 ⇒ **快不快**;
  · κ = λ_max/λ_min (条件数) = 各向异性/病态度 ⇒ 越大越"拧巴";
  · H = (1/κ)·λ_min —— 把"稳"(λ_min)按"拧巴度"(κ) 打折: **又稳又各向同性 ⇒ H 高**。
  · anisotropy = std(λ)/mean(λ) —— 无量纲的各向异性幅度 (补充 κ, 对多轴更细)。

阈值 (全部**从配置读, 可标定**, 不写死到处复制):
  真源 config/calib/zmax_health.json (grades.excellent/good/warning + trend_eps)。
  · 缺文件 ⇒ 用本模块 DEFAULT_THRESHOLDS (老倪口径), 但会标 _src=defaults;
  · 现场改分级 ⇒ 改配置 (或用 write_thresholds() 钩子), 全系统读同一份;
  · 环境变量 ZMAX_HEALTH_THRESHOLDS (JSON) 可临时覆盖 (取证/实验用)。

用法:
  from lerobot.manifold.health import HealthMonitor, health_from_metric, load_thresholds
  h = health_from_metric(g)                    # g: n×n 对称正定度量张量
  print(h.H, h.kappa, h.status, h.anisotropy)
  mon = HealthMonitor()                        # 带历史的监视器 (趋势)
  R = mon.evaluate(g)                          # 追加一条 H, 回带 trend
  print(mon.stats())                           # mean/min/max H · κ · 序列

自检: gui-venv311/bin/python src/lerobot/manifold/health.py
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

import numpy as np

# 仓库根 (src/lerobot/manifold/health.py → 上溯 4 级)
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
HEALTH_CFG = os.path.join(_ROOT, "config", "calib", "zmax_health.json")
ENV_OVERRIDE = "ZMAX_HEALTH_THRESHOLDS"

# 老倪口径出厂值 (真源缺文件时的兜底; 一旦 config 存在即以配置为准)
DEFAULT_THRESHOLDS = {
    "excellent": 0.5,     # H >   0.5 ⇒ 优秀
    "good": 0.1,          # H >   0.1 ⇒ 良好   (0.1~0.5)
    "warning": 0.01,      # H >  0.01 ⇒ 警告   (0.01~0.1)
    #                      # H ≤  0.01 ⇒ 危险
    "trend_eps": 1e-4,    # H 历史线性拟合斜率 |slope| ≤ eps ⇒ stable
    "kappa_warn": 100.0,  # 仅记录 (条件数警戒线; 不参与分级, 供上层参考)
}
_STATUS = ("excellent", "good", "warning", "critical")


def _load_json(p: str) -> dict:
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                       # noqa: BLE001
        return {}


def load_thresholds(path: str | None = None) -> dict:
    """读健康度阈值真源 (配置 > 默认; 环境变量可临时覆盖)。返回扁平 dict。"""
    src = "defaults"
    th = dict(DEFAULT_THRESHOLDS)
    p = path if path is not None else HEALTH_CFG
    cfg = _load_json(p)
    grades = cfg.get("grades") or {}
    for k in ("excellent", "good", "warning"):
        if k in grades and grades[k] is not None:
            th[k] = float(grades[k])
    if cfg.get("trend_eps") is not None:
        th["trend_eps"] = float(cfg["trend_eps"])
    if cfg.get("kappa_warn") is not None:
        th["kappa_warn"] = float(cfg["kappa_warn"])
    if cfg:
        src = os.path.relpath(p, _ROOT) if os.path.isabs(p) else p
    env = os.environ.get(ENV_OVERRIDE)
    if env:
        try:
            th.update({k: v for k, v in json.loads(env).items() if k in th})
            src = "env:" + ENV_OVERRIDE
        except Exception:                                                   # noqa: BLE001
            pass
    th["_src"] = src
    return th


def write_thresholds(path: str | None = None, **kw: Any) -> dict:
    """标定钩子: 写健康度阈值到配置真源 (只改显式给的字段), 写后回读。"""
    p = path if path is not None else HEALTH_CFG
    d = _load_json(p) or {}
    d.setdefault("_doc", ("流形引擎健康度 H 阈值真源 (老倪 2026-10-12 口径)。"
                          "H=(1/κ)·λ_min, κ=λ_max/λ_min; 分级由 grades 决定。"))
    grades = dict(d.get("grades") or {})
    for k in ("excellent", "good", "warning"):
        if k in kw and kw[k] is not None:
            grades[k] = float(kw[k])
    if "trend_eps" in kw and kw["trend_eps"] is not None:
        d["trend_eps"] = float(kw["trend_eps"])
    if "kappa_warn" in kw and kw["kappa_warn"] is not None:
        d["kappa_warn"] = float(kw["kappa_warn"])
    d["grades"] = grades
    d.setdefault("definition", {"H": "(1/κ)·λ_min", "kappa": "λ_max/λ_min",
                                "anisotropy": "std(λ)/mean(λ)", "lambda": "eigvalsh(g)"})
    d["_updated_at"] = __import__("time").strftime("%F %T")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    back = load_thresholds(p)
    return {"ok": all(float(back[k]) == float(grades.get(k, back[k])) for k in ("excellent", "good", "warning")),
            "dest": os.path.relpath(p, _ROOT), "thresholds": {k: back[k] for k in
            ("excellent", "good", "warning", "trend_eps", "kappa_warn")}}


@dataclass
class HealthThresholds:
    """健康度阈值 + 分级/趋势判定 (唯一来源 = load_thresholds)。"""
    excellent: float = DEFAULT_THRESHOLDS["excellent"]
    good: float = DEFAULT_THRESHOLDS["good"]
    warning: float = DEFAULT_THRESHOLDS["warning"]
    trend_eps: float = DEFAULT_THRESHOLDS["trend_eps"]
    kappa_warn: float = DEFAULT_THRESHOLDS["kappa_warn"]
    src: str = "defaults"

    @classmethod
    def from_config(cls, path: str | None = None) -> "HealthThresholds":
        t = load_thresholds(path)
        return cls(excellent=t["excellent"], good=t["good"], warning=t["warning"],
                   trend_eps=t["trend_eps"], kappa_warn=t["kappa_warn"], src=t.get("_src", "defaults"))

    def status(self, H: float) -> str:
        """H 分级 (严格按老倪口径: 大者优先)。"""
        h = float(H)
        if h > self.excellent:
            return "excellent"
        if h > self.good:
            return "good"
        if h > self.warning:
            return "warning"
        return "critical"

    def trend(self, slope: float) -> str:
        s = float(slope)
        if s > self.trend_eps:
            return "improving"
        if s < -self.trend_eps:
            return "declining"
        return "stable"

    def to_dict(self) -> dict:
        return {"excellent": self.excellent, "good": self.good, "warning": self.warning,
                "trend_eps": self.trend_eps, "kappa_warn": self.kappa_warn, "_src": self.src}


@dataclass
class HealthReport:
    """一帧健康度报告 (H/κ/λ/anisotropy/分级/趋势 + 原始特征值)。"""
    H: float
    kappa: float
    lambda_min: float
    lambda_max: float
    anisotropy: float
    status: str
    dim: int
    eigvals: list = field(default_factory=list)
    trend: str = ""
    slope: float = 0.0
    kappa_warn: bool = False

    def to_dict(self) -> dict:
        return {"H": round(self.H, 8), "kappa": round(self.kappa, 8),
                "lambda_min": round(self.lambda_min, 8), "lambda_max": round(self.lambda_max, 8),
                "anisotropy": round(self.anisotropy, 8), "status": self.status,
                "dim": self.dim, "eigvals": [round(float(v), 8) for v in self.eigvals],
                "trend": self.trend, "slope": round(self.slope, 10), "kappa_warn": self.kappa_warn}


def health_from_eigvals(eigvals, thresholds: HealthThresholds | None = None) -> HealthReport:
    """从度量张量的**特征值**直接算 H/κ/anisotropy (核心公式, 唯一实现)。"""
    th = thresholds or HealthThresholds.from_config()
    w = np.sort(np.asarray(eigvals, dtype=float).ravel())
    w = w[w > 0.0] if np.any(w > 0.0) else np.abs(w) + 1e-300     # 非正定兜底 (会被标出但不算崩)
    lmin = float(w.min()) if w.size else 0.0
    lmax = float(w.max()) if w.size else 0.0
    mean = float(w.mean()) if w.size else 0.0
    kappa = float(lmax / lmin) if lmin > 0 else float("inf")
    H = float((1.0 / kappa) * lmin) if kappa > 0 and np.isfinite(kappa) else 0.0
    aniso = float(w.std() / mean) if mean > 0 else 0.0
    return HealthReport(H=H, kappa=kappa, lambda_min=lmin, lambda_max=lmax, anisotropy=aniso,
                        status=th.status(H), dim=int(w.size), eigvals=w.tolist(),
                        kappa_warn=bool(kappa > th.kappa_warn))


def health_from_metric(g, thresholds: HealthThresholds | None = None) -> HealthReport:
    """从**度量张量 g_ij(x)** 算健康度 (对称化 + eigvalsh)。"""
    g = np.asarray(g, dtype=float)
    g = (g + g.T) / 2.0
    w = np.linalg.eigvalsh(g)
    return health_from_eigvals(w, thresholds)


def health_from_field(field, x=None, thresholds: HealthThresholds | None = None) -> HealthReport:
    """从 MetricField 在某状态 x 处算健康度。"""
    if x is None:
        x = np.zeros(getattr(field, "dim", 3))
    return health_from_metric(field.g(x), thresholds)


class HealthMonitor:
    """健康度监视器 —— 累积 H 历史, 线性拟合趋势 (improving/stable/declining)。"""

    def __init__(self, thresholds: HealthThresholds | None = None,
                 window: int = 0, cfg_path: str | None = None):
        self.th = thresholds or HealthThresholds.from_config(cfg_path)
        self.window = int(window)                 # 0 = 全历史
        self.history: list[float] = []
        self.kappas: list[float] = []
        self.reports: list[HealthReport] = []

    def _trend(self) -> tuple[str, float]:
        h = np.asarray(self.history, dtype=float)
        if h.size < 3:
            return "stable", 0.0
        if self.window and h.size > self.window:
            h = h[-self.window:]
        idx = np.arange(h.size, dtype=float)
        slope = float(np.polyfit(idx, h, 1)[0])   # 最小二乘线性拟合斜率
        return self.th.trend(slope), slope

    def evaluate(self, g=None, report: HealthReport | None = None) -> HealthReport:
        """吃度量张量 g (或已算好的 report) → 追加 H → 回带趋势。"""
        r = report if report is not None else health_from_metric(g, self.th)
        self.history.append(r.H)
        self.kappas.append(r.kappa)
        trend, slope = self._trend()
        r.trend, r.slope = trend, slope
        self.reports.append(r)
        return r

    # ── 统计摘要 (健康度序列) ──
    def stats(self) -> dict:
        h = np.asarray(self.history, dtype=float)
        k = np.asarray(self.kappas, dtype=float)
        if h.size == 0:
            return {"n": 0}
        cnt: dict = {s: 0 for s in _STATUS}
        for s in (r.status for r in self.reports):
            cnt[s] = cnt.get(s, 0) + 1
        trend, slope = self._trend()
        return {"n": int(h.size), "H_mean": float(h.mean()), "H_min": float(h.min()),
                "H_max": float(h.max()), "H_last": float(h[-1]),
                "kappa_mean": float(k.mean()), "kappa_max": float(k.max()),
                "anisotropy_mean": float(np.mean([r.anisotropy for r in self.reports])),
                "status_counts": cnt, "trend": trend, "slope": slope,
                "thresholds": self.th.to_dict()}

    def series(self) -> list[float]:
        return list(self.history)


# ────────────────────────────── 自检 ──────────────────────────────
def _self_test() -> int:
    print("🩺 health 自检 — 健康度 H=(1/κ)·λ_min (老倪 2026-10-12 口径)")
    ok = True

    # ① 各向同性: κ=1, H=λ (M=1 ⇒ H=1.0 excellent)
    r = health_from_metric(np.eye(3))
    c1 = abs(r.kappa - 1.0) < 1e-12 and abs(r.H - 1.0) < 1e-12 and r.status == "excellent"
    print(f"① 各向同性 I₃: λ={[round(v,3) for v in r.eigvals]} κ={r.kappa:.4g} H={r.H:.4g} "
          f"aniso={r.anisotropy:.4g} → {r.status} → {'✓' if c1 else '✗'}")
    ok &= c1

    # ② 各向异性 diag(100,1,1): λmax=100 λmin=1 κ=100 H=0.01 critical + aniso 大
    r = health_from_metric(np.diag([100.0, 1.0, 1.0]))
    c2 = (abs(r.kappa - 100.0) < 1e-9 and abs(r.H - 0.01) < 1e-12
          and r.status == "critical" and r.anisotropy > 0.5)
    print(f"② 病态 diag(100,1,1): κ={r.kappa:.4g} H={r.H:.4g} aniso={r.anisotropy:.4g} "
          f"→ {r.status} → {'✓' if c2 else '✗'}")
    ok &= c2

    # ③ 分级边界 (老倪口径): 0.5/0.1/0.01 严格大于
    th = HealthThresholds.from_config()
    edges = {0.6: "excellent", 0.5: "good", 0.3: "good", 0.1: "warning", 0.05: "warning",
             0.01: "critical", 0.005: "critical"}
    pts = [(float(h), th.status(h)) for h in edges]
    c3 = all(th.status(h) == want for h, want in edges.items())
    print(f"③ 分级边界: {pts} → {'✓' if c3 else '✗'}")
    ok &= c3

    # ④ 趋势: 线性升/平/降 各自判定
    m = HealthMonitor(thresholds=th)
    for _ in range(20):
        m.evaluate(report=health_from_metric(np.eye(3)))          # 平
    up = HealthMonitor(thresholds=th)
    for i in range(20):
        up.evaluate(report=health_from_metric(np.eye(3) * (1.0 + 0.1 * i)))
    dn = HealthMonitor(thresholds=th)
    for i in range(20):
        dn.evaluate(report=health_from_metric(np.eye(3) * (3.0 - 0.1 * i)))
    c4 = m.stats()["trend"] == "stable" and up.stats()["trend"] == "improving" and dn.stats()["trend"] == "declining"
    print(f"④ 趋势: 平={m.stats()['trend']} 升={up.stats()['trend']} 降={dn.stats()['trend']} → {'✓' if c4 else '✗'}")
    ok &= c4

    # ⑤ 阈值从配置读 (真源 + 环境覆盖钩子)
    src = load_thresholds()["_src"]
    env_ok = False
    os.environ[ENV_OVERRIDE] = json.dumps({"excellent": 9.9})
    try:
        env_ok = abs(load_thresholds()["excellent"] - 9.9) < 1e-12
    finally:
        os.environ.pop(ENV_OVERRIDE, None)
    c5 = (src != "") and env_ok
    print(f"⑤ 阈值真源 _src={src} · 环境覆盖钩子生效={env_ok} → {'✓' if c5 else '✗'}")
    ok &= c5

    # ⑥ 统计摘要字段齐
    s = up.stats()
    c6 = all(k in s for k in ("H_mean", "H_min", "H_max", "kappa_mean", "anisotropy_mean", "status_counts", "trend"))
    print(f"⑥ 统计摘要: {json.dumps({k: (round(v, 5) if isinstance(v, float) else v) for k, v in s.items() if k != 'thresholds'}, ensure_ascii=False)} → {'✓' if c6 else '✗'}")
    ok &= c6

    print(f"── 自检结论: {'全部通过' if ok else '有判据未过'} ──")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_self_test())
