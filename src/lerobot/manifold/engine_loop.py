# -*- coding: utf-8 -*-
"""⚙️ 流形引擎闭环 (老倪 2026-10-12 设计口径) —— 度量张量 → 健康度 → 动力 → 五层闭环。

老倪的设计 (摘要):
> 流形引擎是状态空间工程的**核心**, 输出类似发动机扭矩的"动力", 驱动 L5 用 agent 构建任务
> 实现路径; L5→L4 系统边界+安全规范; L5→L3 任务规划; L3→L2 具体操作任务; L2 执行
> (原子技能/肌肉记忆, 快速反馈); L4 监督 L3 与 L2 (确保没有违反安全的错误动作); 反馈上行
> L2→L3→L4→L5 记忆, L5 汇总 L2/L3/L4 记忆并指挥每层更新策略: 微调 L4/L3 模型 + 补偿 L2
> 肌肉记忆动作。**必须是完整闭环反馈状态空间**。

本模块逐 tick 把上面这句话写成**真跑可查**的闭环 (纯 numpy, 不依赖 torch/引擎):

  ┌─ 每 tick ────────────────────────────────────────────────────────────────────────┐
  │ ① g_ij(x) ← MetricField.g(x)   (主参数来自真源 config/calib/zmax_manifold.json)    │
  │ ② H, κ, aniso ← health.HealthMonitor.evaluate(g)   (阈值真源 → 分级/趋势)          │
  │ ③ 动力 τ = ‖g⁻¹F‖  [m/s²]  = 度量诱导的加速预算 (引擎的"扭矩"); 各向同性 ⇒ τ=|F|/M  │
  │ ④ L5(agent 构建任务实现路径: 系统边界+安全规范+任务规划) → L4(认知+监督)            │
  │    → L3(调度/任务规划) → L2(执行原子技能/肌肉记忆+快速反馈)                         │
  │ ⑤ 记忆上行 L2→L3→L4→L5; L5 汇总指挥: 微调 L4/L3 增益 + 补偿 L2 肌肉记忆动作        │
  │ ⑥ 每步记录 H/κ/τ/动作/记忆更新 (逐 tick dict, 可整体 JSON 落盘)                     │
  └──────────────────────────────────────────────────────────────────────────────────┘

单位口径 (必须写死清楚):
  · x 为状态 (米/rad), F 为**广义力** (与状态量纲共轭; 本实现取真实 trace 的归一化力幅 f 乘方向),
    g⁻¹F 量纲 = 状态/时间² = **加速度**; 故 τ = ‖g⁻¹F‖ 单位 = **m/s²** (每单位广义力的加速预算)。
  · 旧标量语义: 各向同性 g=M·I ⇒ g⁻¹ = I/M ⇒ τ = ‖F‖/M, a = F/M (逐字一致, 零回归)。

层的真实对应 (先 grep 确认真源存在, 不凭空造名):
  L5 ← 任务实现路径/系统边界/安全规范 (meta 的 task_id/stages/tol/takt/force_cap; 参见 ar_l5_understand / l5 口径)
  L4 ← 认知+监督 (ab_l4_gate 的"上层只给意图, 执行由下层收口"; 真实 trace l4_f/l4_veto)
  L3 ← 调度/规划 (eval_l3_engine 的流程规划位; 真实 trace u_ff)
  L2 ← 执行+肌肉记忆 (tools/gui/muscle_memory.py 真源; 真实 trace u_exec_vec, 收口闸逐轴 |corr|≥0.5)

自检: gui-venv311/bin/python src/lerobot/manifold/engine_loop.py
"""
from __future__ import annotations

import importlib.util
import json
import os
from dataclasses import dataclass, field
from typing import Any

import numpy as np

try:                                                                            # 包内正常导入
    from .health import HealthMonitor, HealthThresholds
    from .metric_field import MetricField, MODE_ISOTROPIC
except ImportError:                                                             # 直接跑本文件 (无父包) 的兜底
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from health import HealthMonitor, HealthThresholds                          # type: ignore  # noqa: E402
    from metric_field import MetricField, MODE_ISOTROPIC                        # type: ignore  # noqa: E402


_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# 8 阶段 (与 tools/gui/muscle_memory.py 逐字一致)
STAGES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]
# 健康度分级 → 层的保守系数 (H 低 ⇒ 动作更保守; 唯一一处按分级给系数)
H_CONSERVATIVE = {"excellent": 1.0, "good": 0.9, "warning": 0.6, "critical": 0.3}


def _stage_key(stage) -> str:
    """'阶段 插入 · 接触' → '插入' (与 muscle_memory 同口径)。"""
    return str(stage).replace("阶段", "").replace("·", " ").split()[0] if str(stage).strip() else ""


def _unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=float).ravel()
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else np.zeros_like(v)


def _load_muscle_module():
    """按路径加载真源 tools/gui/muscle_memory.py (避免给 sys.path 加 tools/gui 影响其它 import)。"""
    p = os.path.join(_ROOT, "tools", "gui", "muscle_memory.py")
    if not os.path.isfile(p):
        return None
    try:
        spec = importlib.util.spec_from_file_location("zmax_muscle_memory", p)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    except Exception:                                                       # noqa: BLE001
        return None


# ────────────────────────────── 五层 ──────────────────────────────
@dataclass
class L5Plan:
    task_id: str
    stage: str
    stage_idx: int
    n_stages: int
    next_stage: str
    goal: list
    remaining: int
    system_boundary: dict
    safety: dict
    plan: list


class L5Planner:
    """L5 — agent 构建任务实现路径: 出「系统边界 + 安全规范 + 任务规划」。"""

    def __init__(self, task_id: str = "TASK", stages: list | None = None, goal=None,
                 tol: dict | None = None, takt_s: float = 3.15, force_cap_n: float = 5.0,
                 speed_cap_ms: float = 0.6, workspace=None):
        self.task_id = str(task_id or "TASK")
        self.stages = list(stages) if stages else list(STAGES)
        self.goal = np.asarray(goal if goal is not None else [0.0, 0.0, 0.0], dtype=float).ravel()[:3]
        self.tol = dict(tol or {})
        self.takt_s = float(takt_s)
        self.calls = 0
        self.commands = 0
        self.history: list = []
        # 系统边界 (workspace): 由现场几何给出; 缺省 = goal 附近 0.3 m 盒
        _w = workspace if workspace is not None else [[g - 0.3 for g in self.goal], [g + 0.3 for g in self.goal]]
        self.workspace = [np.asarray(_w[0], float), np.asarray(_w[1], float)]
        # 安全规范 (唯一出口: 所有层的动作都要过这里)
        self.safety = {"force_cap_n": float(force_cap_n), "speed_cap_ms": float(speed_cap_ms),
                       "xy_tol_m": float(self.tol.get("xy_m", 1e-3)), "yaw_tol_deg": float(self.tol.get("yaw_deg", 1.0)),
                       "dz_tol_m": float(self.tol.get("dz_m", 4e-3)), "takt_s": self.takt_s,
                       "workspace_lo": self.workspace[0].tolist(), "workspace_hi": self.workspace[1].tolist()}

    def plan(self, stage: str) -> L5Plan:
        self.calls += 1
        key = _stage_key(stage)
        idx = self.stages.index(key) if key in self.stages else 0
        nxt = self.stages[idx + 1] if idx + 1 < len(self.stages) else "完成"
        p = L5Plan(task_id=self.task_id, stage=key or stage, stage_idx=idx, n_stages=len(self.stages),
                   next_stage=nxt, goal=self.goal.tolist(), remaining=max(0, len(self.stages) - 1 - idx),
                   system_boundary={"lo": self.workspace[0].tolist(), "hi": self.workspace[1].tolist()},
                   safety=dict(self.safety), plan=list(self.stages))
        self.history.append(p)
        return p

    def aggregate_command(self, stats: dict) -> dict:
        """L5 汇总 L2/L3/L4 记忆并指挥每层更新策略 (微调 L4/L3 + 补偿 L2 肌肉记忆)。

        口径: 出的是**目标增益** (由 L5 定策略), 由各层以有限速率 (lr) 逼近 —— 不做无界漂移。
        """
        self.commands += 1
        veto_rate = float(stats.get("veto_rate", 0.0))
        champ_err = float(stats.get("champ_err", 0.0))
        h_status = str(stats.get("h_status", "excellent"))
        cons = H_CONSERVATIVE.get(h_status, 1.0)
        # 微调 L4: 否决率高 ⇒ 目标导航增益收紧 (上层少插手, 执行交 L2 收口); 否则放开
        target_nav = 0.05 if veto_rate > 0.02 else 0.30
        # 微调 L3: 健康度优秀 ⇒ 放开流程增益; 否则收紧 (保守)
        target_flow = 0.25 if h_status == "excellent" else 0.10
        # 补偿 L2 肌肉记忆: 标杆误差大 ⇒ 目标补偿权重高 (更依赖练熟动作)
        target_mm = min(0.5, 0.2 + 0.5 * champ_err)
        return {"finetune_l4": {"target_nav_gain": target_nav, "why": f"veto_rate={veto_rate:.4f}"},
                "finetune_l3": {"target_flow_gain": target_flow, "why": f"H={h_status}"},
                "compensate_l2": {"target_k_mm": target_mm, "why": f"champ_err={champ_err:.4f}"},
                "conservative": cons, "h_status": h_status}


@dataclass
class L4Proposal:
    u_nav: np.ndarray
    direction: np.ndarray
    magnitude: float
    gain: float


@dataclass
class SupervisorVerdict:
    veto: bool
    reasons: list
    u_nav_out: np.ndarray
    checked: int


class L4Cognition:
    """L4 — 认知 (提意图) + 监督 (拦违规动作, 保证不违反 L5 安全规范)。"""

    def __init__(self, nav_gain: float = 0.30, kappa_warn: float = 100.0):
        self.nav_gain = float(nav_gain)
        self.kappa_warn = float(kappa_warn)
        self.proposals = 0
        self.checks = 0
        self.vetoes = 0
        self.veto_reasons: dict = {}
        self.u_nav_hist: list = []
        self.u_exec_hist: list = []

    def propose(self, x, l5: L5Plan, l4_f: float = 0.0) -> L4Proposal:
        self.proposals += 1
        d = np.asarray(l5.goal, float) - np.asarray(x, float).ravel()[:3]
        direction = _unit(d)
        mag = float(abs(l4_f))
        u = direction * mag * self.nav_gain
        return L4Proposal(u_nav=u, direction=direction, magnitude=mag, gain=self.nav_gain)

    def supervise(self, prop: L4Proposal, l5: L5Plan, x, force_mag: float = 0.0,
                  trace_veto: float = 0.0, l4_force_n: float = 0.0) -> SupervisorVerdict:
        """监督: 违规 ⇒ 否决 (违规动作**不进入执行**)。判据全部可测。"""
        self.checks += 1
        reasons: list[str] = []
        x = np.asarray(x, float).ravel()[:3]
        u = np.asarray(prop.u_nav, float)
        cap = float(l5.safety["speed_cap_ms"])
        if u.size and float(np.max(np.abs(u))) > cap:
            reasons.append("超速度上限")
        if float(force_mag) > float(l5.safety["force_cap_n"]):
            reasons.append("超力上限")
        if float(l4_force_n) > float(l5.safety["force_cap_n"]):     # L4 提案的力 (N) 超安全规范
            reasons.append("L4提案超力上限")
        xn = x + u * 1.0                                     # 一阶外推
        lo, hi = np.asarray(l5.system_boundary["lo"]), np.asarray(l5.system_boundary["hi"])
        x_in = bool(np.all(x >= lo - 1e-9) and np.all(x <= hi + 1e-9))
        xn_out = bool(np.any(xn < lo - 1e-9) or np.any(xn > hi + 1e-9))
        if x_in and xn_out:                                  # 只拦"会把状态推出边界"的动作 (穿越违规)
            reasons.append("越系统边界")
        if float(trace_veto) > 0.0:                          # 真实 trace 的 L4 力否决 (真源信号)
            reasons.append("trace力否决")
        self.u_nav_hist.append(u.copy())
        veto = bool(reasons)
        if veto:
            self.vetoes += 1
            for r in reasons:
                self.veto_reasons[r] = self.veto_reasons.get(r, 0) + 1
        return SupervisorVerdict(veto=veto, reasons=reasons,
                                 u_nav_out=(np.zeros_like(u) if veto else u), checked=self.checks)


@dataclass
class L3Schedule:
    stage: str
    stage_idx: int
    subtask: str
    next_stage: str
    scheduled: bool
    dwell: int


class L3Scheduler:
    """L3 — 调度/任务规划: 把 L5 的阶段计划落成具体操作子任务 (到 L2 可执行粒度)。"""

    def __init__(self, flow_gain: float = 0.20):
        self.flow_gain = float(flow_gain)
        self.calls = 0
        self._last = None
        self._dwell = 0
        self.transitions = 0

    def schedule(self, l5: L5Plan) -> L3Schedule:
        self.calls += 1
        if l5.stage != self._last:
            self.transitions += 1
            self._dwell = 0
            self._last = l5.stage
        self._dwell += 1
        return L3Schedule(stage=l5.stage, stage_idx=l5.stage_idx, subtask=f"SK{l5.stage_idx + 1:02d}-{l5.stage}",
                          next_stage=l5.next_stage, scheduled=True, dwell=self._dwell)

    def flow(self, sched: L3Schedule, x, l5: L5Plan, u_ff: float = 0.0) -> np.ndarray:
        d = _unit(np.asarray(l5.goal, float) - np.asarray(x, float).ravel()[:3])
        return d * float(abs(u_ff)) * self.flow_gain


@dataclass
class ExecOut:
    u_exec: np.ndarray
    u_ref: np.ndarray
    budget: float
    h_factor: float
    k_nav: float
    k_flow: float
    k_mm: float
    clipped: float


class L2Executor:
    """L2 — 执行原子技能/肌肉记忆 + 快速反馈 (唯一对物理世界出口)。"""

    def __init__(self, k_mm0: float = 0.35, bounds=(-1.0, 1.0)):
        self.k_mm0 = float(k_mm0)
        self.lo, self.hi = float(bounds[0]), float(bounds[1])
        self.calls = 0
        self.execs = 0
        self.clipped = 0
        self.clip_max = 0.0
        # 收口闸 (逐轴 |corr|≥0.5): 滚动窗口
        self.win = 60
        self._nav: list = []
        self._exe: list = []
        self.gate_checked = 0
        self.gate_axis_veto = 0

    def propose(self, u_exec_trace) -> np.ndarray:
        """L2 执行参考 = 真实执行动作 (trace u_exec_vec 前 3 维)。"""
        self.calls += 1
        v = np.asarray(u_exec_trace, dtype=float).ravel()
        out = np.zeros(3)
        out[: min(3, v.size)] = v[:3]
        return out

    def execute(self, u_l2, u_nav=None, u_flow=None, champ=None, tau: float = 0.0,
                tau_ref: float = 0.0, h_status: str = "excellent") -> ExecOut:
        """融合 + 度量预算 + 健康度保守 + 肌肉记忆补偿, 最后收口到 U_L2。"""
        self.execs += 1
        base = np.asarray(u_l2, float).ravel()[:3].copy()
        u = base.copy()
        k_nav = k_flow = k_mm = 0.0
        if u_nav is not None:                                # L4 导航 (已过监督)
            k_nav = float(np.clip(self._nav_gain, 0, 1))
            u = u + k_nav * (np.asarray(u_nav, float).ravel()[:3] - u)
        if u_flow is not None:                               # L3 流程
            k_flow = float(np.clip(self._flow_gain, 0, 1))
            u = u + k_flow * (np.asarray(u_flow, float).ravel()[:3] - u)
        if champ is not None:                                # L2 肌肉记忆补偿
            k_mm = float(np.clip(self.k_mm0, 0, 1))
            c = np.asarray(champ, float).ravel()[:3]
            u = u + k_mm * (c - u)
        # 度量预算 (τ/τ_ref) + 健康度保守系数 (各向同性默认 ⇒ 都 = 1.0, 零回归)
        budget = float(np.clip(tau / tau_ref, 0.2, 2.0)) if tau_ref > 1e-12 else 1.0
        h_factor = H_CONSERVATIVE.get(h_status, 1.0)
        u = u * budget * h_factor
        a = np.asarray(u, float)
        u = np.clip(a, self.lo, self.hi)
        clip = float(np.max(np.abs(u - a))) if a.size else 0.0
        if clip > 0:
            self.clipped += 1
            self.clip_max = max(self.clip_max, clip)
        return ExecOut(u_exec=u, u_ref=base, budget=budget, h_factor=h_factor,
                       k_nav=k_nav, k_flow=k_flow, k_mm=k_mm, clipped=clip)

    # 增益由 L5 指挥注入 (闭环)
    _nav_gain = 0.0
    _flow_gain = 0.0

    def closure_gate(self, u_nav, u_exec, axes: int = 3) -> dict:
        """L2 收口闸: 逐轴 Pearson corr(L4提案, 执行) —— 任一轴 |corr|<0.5 ⇒ 该轴否决。"""
        n = np.asarray(u_nav, float).ravel()
        e = np.asarray(u_exec, float).ravel()
        m = min(n.size, e.size, axes)
        self._nav.append(np.array([n[i] if i < n.size else 0.0 for i in range(m)]))
        self._exe.append(np.array([e[i] if i < e.size else 0.0 for i in range(m)]))
        if len(self._nav) > self.win:
            self._nav.pop(0)
            self._exe.pop(0)
        if len(self._nav) < 10:
            return {"corr": [None] * m, "axis_veto": [False] * m, "ok": True, "n": len(self._nav)}
        N = np.asarray(self._nav, float)
        E = np.asarray(self._exe, float)
        corr = []
        for i in range(m):
            a, b = N[:, i], E[:, i]
            if a.std() < 1e-12 or b.std() < 1e-12:
                corr.append(0.0)
            else:
                corr.append(float(np.corrcoef(a, b)[0, 1]))
        axis_veto = [abs(c) < 0.5 for c in corr]
        self.gate_checked += 1
        if any(axis_veto):
            self.gate_axis_veto += 1
        return {"corr": [round(c, 4) for c in corr], "axis_veto": axis_veto,
                "ok": not any(axis_veto), "n": len(self._nav)}


# ────────────────────────────── 主循环 ──────────────────────────────
class ManifoldEngineLoop:
    """流形引擎闭环 —— 度量 → 健康度 → 动力 → L5/L4/L3/L2 → 记忆上行 → L5 指挥更新。"""

    def __init__(self, metric: MetricField | None = None, meta: dict | None = None,
                 thresholds: HealthThresholds | None = None, muscle=None, muscle_path: str | None = None,
                 nav_gain0: float = 0.30, flow_gain0: float = 0.20, k_mm0: float = 0.35,
                 force_cap_n: float | None = None, speed_cap_ms: float | None = None,
                 apply_updates: bool = True, window: int = 200):
        meta = dict(meta or {})
        self.metric = metric if metric is not None else MetricField.from_config()
        self.meta = meta
        self.monitor = HealthMonitor(thresholds=thresholds, window=window)
        self.apply_updates = bool(apply_updates)
        # 目标/任务 (L5 的真源: meta 的 goal / L5 段)
        l5m = meta.get("l45", {}).get("L5", {}) if isinstance(meta.get("l45"), dict) else {}
        goal = meta.get("goal")
        if goal is None:
            goal = meta.get("target_goal")
        self.goal = np.asarray(goal, float).ravel()[:3] if goal is not None else np.zeros(3)
        tol = (l5m.get("tol") or {}) if isinstance(l5m, dict) else {}
        task_id = (l5m.get("task_id") or meta.get("task_id") or meta.get("params", {}).get("task_id") or "TASK")
        stages = l5m.get("stages") if isinstance(l5m.get("stages"), list) else None
        takt = float(l5m.get("takt_s") or meta.get("params", {}).get("takt_s") or 3.15)
        fcap = float(force_cap_n if force_cap_n is not None else (l5m.get("force_cap_n") or 5.0))
        scap = float(speed_cap_ms if speed_cap_ms is not None else (l5m.get("speed_cap") or 0.6))
        self.L5 = L5Planner(task_id=task_id, stages=stages, goal=self.goal, tol=tol,
                            takt_s=takt, force_cap_n=fcap, speed_cap_ms=scap)
        self.L4 = L4Cognition(nav_gain=nav_gain0)
        self.L3 = L3Scheduler(flow_gain=flow_gain0)
        self.L2 = L2Executor(k_mm0=k_mm0)
        self.L2._nav_gain = float(nav_gain0)
        self.L2._flow_gain = float(flow_gain0)
        # 肌肉记忆 (真源 tools/gui/muscle_memory.py; 缺则 None, 诚实标注)
        self._muscle_mod = _load_muscle_module()
        if muscle is not None:
            self.muscle = muscle
        elif self._muscle_mod is not None:
            self.muscle = self._muscle_mod.MuscleMemory(path=muscle_path)
        else:
            self.muscle = None
        self.muscle_src = ((os.path.abspath(muscle_path) if muscle_path else
                            "tools/gui/muscle_memory.py (默认 data/memory/muscle_memory.json)")
                           if self.muscle is not None else "缺 (未加载 muscle_memory 真源)")
        # 记忆总线 (上行 L2→L3→L4→L5)
        self.memory = {"L2": [], "L3": [], "L4": [], "L5": []}
        self.mem_events = {"L2_to_L3": 0, "L3_to_L4": 0, "L4_to_L5": 0, "L5_writeback": 0}
        self.records: list = []
        self.layer_calls = {"L5": 0, "L4": 0, "L3": 0, "L2": 0}
        self.veto_total = 0
        self.tau_hist: list = []
        self.h_hist: list = []
        self._cur_seed = 0

    # ── 动力 τ = ‖g⁻¹F‖ (单位 m/s²) ──
    def torque(self, x, F) -> tuple[float, np.ndarray]:
        a = self.metric.ginv_mul(x, np.asarray(F, float))
        return float(np.linalg.norm(a)), a

    def force_vector(self, frame: dict, x) -> np.ndarray:
        """广义力 F = f·d̂ (f = 真实力幅, d̂ = 指向 L5 目标方向)。"""
        f = float(frame.get("force", 0.0))
        p = frame.get("force_vec")
        if p is not None:
            return np.asarray(p, float).ravel()[:3]
        d = _unit(np.asarray(self.goal, float) - np.asarray(x, float).ravel()[:3])
        return f * d

    # ── 单 tick ──
    def _embed(self, v3, arity: int) -> np.ndarray:
        """把 3D 状态/力嵌入到度量维度 (后位补 0) —— 真源 metric.dim 可被现场标定改动, 引擎不受其绑定。"""
        out = np.zeros(int(arity))
        v = np.asarray(v3, float).ravel()
        out[: min(v.size, arity)] = v[: min(v.size, arity)]
        return out

    def step(self, frame: dict) -> dict:
        x = np.asarray(frame.get("x", np.zeros(3)), float).ravel()[:3]
        stage = frame.get("stage", "")
        arity = int(self.metric.dim)
        # ① 度量 (在真源度量维度上求值; 3D trace 状态/力嵌入后位补 0)
        xg = self._embed(x, arity)
        g = self.metric.g(xg)
        # ② 健康度
        rep = self.monitor.evaluate(g)
        self.h_hist.append(rep.H)
        # ③ 动力
        F3 = self.force_vector(frame, x)
        Fg = self._embed(F3, arity)
        tau, avec = self.torque(xg, Fg)
        tau_ref = float(np.linalg.norm(F3)) / float(self.metric.scale)     # 旧标量 M 参照 (各向同性 ⇒ τ=τ_ref)
        self.tau_hist.append(tau)
        # ④ L5 规划
        plan = self.L5.plan(stage)
        self.layer_calls["L5"] += 1
        # L4 认知 + 监督
        prop = self.L4.propose(x, plan, l4_f=float(frame.get("l4_f", 0.0)))
        self.layer_calls["L4"] += 1
        sup = self.L4.supervise(prop, plan, x, force_mag=float(frame.get("force", 0.0)),
                                trace_veto=float(frame.get("l4_veto", 0.0)),
                                l4_force_n=float(frame.get("l4_f", 0.0)))
        if sup.veto:
            self.veto_total += 1
        # L3 调度 + 流程
        sched = self.L3.schedule(plan)
        self.layer_calls["L3"] += 1
        u_flow = self.L3.flow(sched, x, plan, u_ff=float(frame.get("u_ff", 0.0)))
        # L2 执行
        u_l2 = self.L2.propose(frame.get("u_exec", np.zeros(3)))
        self.layer_calls["L2"] += 1
        champ = self._champ(plan.stage)
        ex = self.L2.execute(u_l2, u_nav=(None if sup.veto else prop.u_nav), u_flow=u_flow,
                             champ=champ, tau=tau, tau_ref=tau_ref, h_status=rep.status)
        gate = self.L2.closure_gate(prop.u_nav, ex.u_exec)
        # ⑤ 记忆上行 L2→L3→L4→L5
        mem = self._memory_ascent(frame, plan, sched, ex, rep, tau, gate, sup, champ)
        # L5 汇总指挥 (每 tick 也可, 用滚动统计)
        cmd = self.L5.aggregate_command(self._command_stats(sup, champ, ex, rep))
        if self.apply_updates:
            self._apply_updates(cmd)
        self.mem_events["L5_writeback"] += 1
        _cap = float(plan.safety["speed_cap_ms"])
        rec = {
            "t": float(frame.get("t", len(self.records))),
            "stage": plan.stage, "stage_idx": plan.stage_idx,
            # 健康度
            "H": round(rep.H, 8), "kappa": round(rep.kappa, 8), "anisotropy": round(rep.anisotropy, 8),
            "status": rep.status, "trend": rep.trend,
            # 动力
            "tau": round(tau, 8), "tau_ref": round(tau_ref, 8), "budget": round(ex.budget, 6),
            # 动作
            "u_l2": [round(v, 6) for v in u_l2], "u_nav": [round(v, 6) for v in prop.u_nav],
            "u_flow": [round(v, 6) for v in u_flow], "u_exec": [round(v, 6) for v in ex.u_exec],
            "k_nav": round(ex.k_nav, 4), "k_flow": round(ex.k_flow, 4), "k_mm": round(ex.k_mm, 4),
            # 监督 + 收口闸
            "l4_veto": bool(sup.veto), "l4_veto_reasons": list(sup.reasons),
            "nav_applied": (not sup.veto), "exec_in_bounds": bool(float(np.max(np.abs(ex.u_exec))) <= _cap + 1e-9),
            "gate_corr": gate["corr"], "gate_ok": gate["ok"],
            # 记忆
            "memory": mem,
        }
        self.records.append(rec)
        return rec

    def _champ(self, stage: str):
        if self.muscle is None:
            return None
        try:
            cu, _ = self.muscle.get_champ(self._cur_seed, stage)
            if cu is None:
                return None
            i = min(len(cu) - 1, self._frame_idx if hasattr(self, "_frame_idx") else 0)
            return np.asarray(cu[i], float).ravel()[:3]
        except Exception:                                                       # noqa: BLE001
            return None

    def _memory_ascent(self, frame, plan, sched, ex, rep, tau, gate, sup, champ) -> dict:
        """记忆上行 L2→L3→L4→L5: 每层记本层结果, 逐级上推; L5 汇总。"""
        l2 = {"action": [round(v, 6) for v in ex.u_exec], "gate_ok": gate["ok"],
              "h": round(rep.H, 6), "tau": round(tau, 6)}
        self.memory["L2"].append(l2)
        self.mem_events["L2_to_L3"] += 1
        l3 = {"stage": sched.stage, "subtask": sched.subtask, "dwell": sched.dwell, "from_L2": l2}
        self.memory["L3"].append(l3)
        self.mem_events["L3_to_L4"] += 1
        l4 = {"veto": sup.veto, "reasons": list(sup.reasons), "from_L3": {"stage": l3["stage"], "dwell": l3["dwell"]}}
        self.memory["L4"].append(l4)
        self.mem_events["L4_to_L5"] += 1
        l5 = {"task_id": plan.task_id, "stage": plan.stage, "remaining": plan.remaining,
              "h_status": rep.status, "veto": sup.veto}
        self.memory["L5"].append(l5)
        # L2 逐帧喂入真源肌肉记忆 (固化/精进在 end_episode)
        if self.muscle is not None:
            try:
                self.muscle.feed(plan.stage, ex.u_exec * 0.0 + np.asarray(frame.get("x", np.zeros(3)), float)[:3],
                                 ex.u_exec)
            except Exception:                                                   # noqa: BLE001
                pass
        return {"L2": l2, "L3": {"stage": l3["stage"], "dwell": l3["dwell"]},
                "L4": {"veto": l4["veto"]}, "L5": {"stage": l5["stage"], "remaining": l5["remaining"]}}

    def _command_stats(self, sup, champ, ex, rep) -> dict:
        champ_err = float(np.linalg.norm(ex.u_ref - np.asarray(champ, float))) if champ is not None else 0.0
        return {"veto_rate": self.L4.vetoes / max(1, self.L4.checks), "champ_err": champ_err,
                "h_status": rep.status}

    def _apply_updates(self, cmd: dict) -> None:
        """L5 指挥每层更新: 微调 L4/L3 增益 + 补偿 L2 肌肉记忆 (有限速率逼近目标, 真实影响下一 tick)。"""
        lr = 0.02
        self.L4.nav_gain += lr * (float(cmd["finetune_l4"]["target_nav_gain"]) - self.L4.nav_gain)
        self.L3.flow_gain += lr * (float(cmd["finetune_l3"]["target_flow_gain"]) - self.L3.flow_gain)
        self.L2.k_mm0 += lr * (float(cmd["compensate_l2"]["target_k_mm"]) - self.L2.k_mm0)
        self.L4.nav_gain = float(np.clip(self.L4.nav_gain, 0.0, 1.0))
        self.L3.flow_gain = float(np.clip(self.L3.flow_gain, 0.0, 1.0))
        self.L2.k_mm0 = float(np.clip(self.L2.k_mm0, 0.0, 1.0))
        self.L2._nav_gain = self.L4.nav_gain
        self.L2._flow_gain = self.L3.flow_gain

    # ── 跑一个 episode (真 trace) ──
    def run_episode(self, frames: list, seed: int = 0, success: bool = True,
                    feed_muscle: bool = True, tag: str = "") -> dict:
        self._cur_seed = int(seed)
        if self.muscle is not None and feed_muscle:
            self.muscle.begin_episode(seed)
        self._frame_idx = 0
        start = len(self.records)
        for fr in frames:
            self.step(fr)
            self._frame_idx += 1
        merged = None
        if self.muscle is not None and feed_muscle:
            merged = self.muscle.end_episode(bool(success))
        n = len(self.records) - start
        seg = self.records[start:]
        return {"tag": tag, "seed": int(seed), "frames": n, "success": bool(success),
                "muscle": merged, "H_mean": float(np.mean([r["H"] for r in seg])) if seg else 0.0,
                "tau_mean": float(np.mean([r["tau"] for r in seg])) if seg else 0.0,
                "vetoes": int(sum(1 for r in seg if r["l4_veto"]))}

    # ── 摘要 ──
    def summary(self) -> dict:
        hs = np.asarray(self.h_hist, dtype=float)
        ts = np.asarray(self.tau_hist, dtype=float)
        hist = self.monitor.stats() if self.h_hist else {}
        n = max(1, len(self.records))
        return {
            "metric": self.metric.spec(),
            "thresholds": self.monitor.th.to_dict(),
            "ticks": len(self.records),
            "layer_calls": dict(self.layer_calls),
            "veto_total": self.veto_total,
            "l4_veto_reasons": dict(self.L4.veto_reasons),
            "closure_gate": {"checked": self.L2.gate_checked, "axis_veto_frames": self.L2.gate_axis_veto},
            "memory_events": dict(self.mem_events),
            "memory_layers": {k: len(v) for k, v in self.memory.items()},
            "muscle_src": self.muscle_src,
            "muscle_status": (self.muscle.status() if self.muscle is not None else {}),
            "H": {"mean": float(hs.mean()) if hs.size else 0.0, "min": float(hs.min()) if hs.size else 0.0,
                  "max": float(hs.max()) if hs.size else 0.0},
            "tau": {"mean": float(ts.mean()) if ts.size else 0.0, "min": float(ts.min()) if ts.size else 0.0,
                    "max": float(ts.max()) if ts.size else 0.0, "unit": "m/s²"},
            "health_stats": hist,
            "gains_final": {"L4_nav_gain": self.L4.nav_gain, "L3_flow_gain": self.L3.flow_gain,
                            "L2_k_mm0": self.L2.k_mm0},
            "L5_commands": self.L5.commands,
        }

    # ── 零回归探针 (各向同性时与旧标量 M 对照) ──
    def scalar_reference(self, x, F) -> dict:
        """旧标量 M 语义的参照量: a = F/M, τ = ‖F‖/M (无曲率/无各向异性)。"""
        M = float(self.metric.scale)
        F = np.asarray(F, float)
        return {"a": F / M, "tau": float(np.linalg.norm(F) / M)}

    def save(self, path: str) -> dict:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"summary": self.summary(), "records": self.records}, f, ensure_ascii=False, indent=1)
        back = json.loads(open(path, encoding="utf-8").read())
        return {"ok": len(back.get("records", [])) == len(self.records), "dest": path,
                "n_records": len(self.records)}


# ────────────────────────────── 自检 ──────────────────────────────
def _self_test() -> int:
    print("⚙️ engine_loop 自检 — 度量→健康度→动力→五层闭环")
    ok = True

    def ck(name, cond, ev=""):
        nonlocal ok
        ok &= bool(cond)
        print(f"  {'✅' if cond else '❌'} {name}" + (f"   ← {ev}" if ev else ""))

    # 真源配置 (现场可改; 自检的零回归用**显式各向同性**度量, 不依赖真源当前形状)
    eng = ManifoldEngineLoop(metric=MetricField(3, scale=1.0, mode=MODE_ISOTROPIC),
                             meta={"goal": [0.0, 0.6, 0.15]})
    frames = [{"x": [0.0, 0.6, 0.15 - 0.001 * i], "stage": STAGES[min(i // 5, 7)], "force": 0.5,
               "l4_f": 0.2, "l4_veto": 0.0, "u_exec": [0.01, 0.0, -0.01], "u_ff": 0.1, "t": i * 0.0125}
              for i in range(60)]
    for fr in frames:
        eng.step(fr)
    s = eng.summary()
    ck("五层都被真跑过", all(v > 0 for v in s["layer_calls"].values()), str(s["layer_calls"]))
    ck("记忆上行四级计数 > 0", all(s["memory_events"][k] > 0 for k in
                                  ("L2_to_L3", "L3_to_L4", "L4_to_L5", "L5_writeback")),
       str(s["memory_events"]))
    ck("每步记录 H/κ/τ/动作/记忆", all(k in eng.records[0] for k in
                                     ("H", "kappa", "tau", "u_exec", "memory")), str(list(eng.records[0].keys()))[:80])

    # 零回归: 各向同性 ⇒ τ == ‖F‖/M 且前 3 维 a == F/M
    x = np.array([0.1, 0.6, 0.15])
    F = np.array([0.3, 0.1, -0.2])
    tau, a = eng.torque(eng._embed(x, eng.metric.dim), eng._embed(F, eng.metric.dim))
    ref = eng.scalar_reference(x, F)
    ck("各向同性 τ == ‖F‖/M", abs(tau - ref["tau"]) < 1e-12, f"τ={tau:.8f} ref={ref['tau']:.8f}")
    ck("各向同性 a[:3] == F/M", float(np.linalg.norm(a[:3] - ref["a"])) < 1e-12, "")

    # L4 监督: 注入违规 (越速度上限) ⇒ 真拦
    v = eng.L4.supervise(L4Proposal(u_nav=np.array([5.0, 0, 0]), direction=np.array([1.0, 0, 0]),
                                    magnitude=5.0, gain=1.0), eng.L5.plan("接近"), x,
                         force_mag=0.0, trace_veto=0.0)
    ck("L4 监督拦下越限动作 (veto=True)", v.veto and "超速度上限" in v.reasons, str(v.reasons))

    # 各向异性 ⇒ τ != ‖F‖/M (度量真起作用)
    aniso = MetricField(3, scale=1.0, mode="diag", diag=[4.0, 1.0, 1.0])
    tau_a, _ = ManifoldEngineLoop(metric=aniso).torque(x, F)
    ck("各向异性 τ != ‖F‖/M (度量真进入动力)", abs(tau_a - float(np.linalg.norm(F))) > 1e-6,
       f"τ_aniso={tau_a:.6f} vs ‖F‖={float(np.linalg.norm(F)):.6f}")

    print(f"── 自检结论: {'全部通过' if ok else '有判据未过'} ──")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_self_test())
