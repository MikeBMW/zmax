"""流形引擎 · 内稳态层 / 功能性感受 / 自我模型  (2026-10-10 老倪)

════════════════════════════════════════════════════════════════════════════════
边界 (先写清楚, 免得被读成"它真有感受")
────────────────────────────────────────────────────────────────────────────────
代码**能**做的: 持续存在的身体状态 · 内部稳态指标 · 失衡→行为驱动 · 自我模型。
代码**不能**做的: 主观感受("难受/愉悦") · 真正的欲望体验。
本模块里所有"感受"都是**功能性**的 —— 它们驱动行为、可观测、可调试、可被 VSCode 逐行断点,
但不声称有主观体验。这是意识硬难题, 不在工程范围内。

════════════════════════════════════════════════════════════════════════════════
口径 (老倪文章 → 工程口径, 先定后跑)
────────────────────────────────────────────────────────────────────────────────
  稳态指标 s_i ∈ [0,1]  (1=最佳, 0=崩溃), 自然衰减 ds_i/dt = −decay_i
  偏差     d_i = 1 − s_i
  紧迫度   u_i = d_i · w_i · (1 + d_i)      # 非线性放大: 偏差越大越急
  危险     s_i < crit_i (任一)              → 安全停止 (veto, 动作全零)
  中断     max(u) > interrupt_thr           → 抢占当前任务 (safe_stop, 可恢复)
  动作切换 energy<0.3 → recharge · wear<0.2 → maintenance · 否则正常任务
  自我模型 记录 (t, s, a) · 预测下一步 s' · 估行为后果 · 出趋势

真信号 vs 估计 (诚实口径, 不许编):
  · 有真实传感器就直接 ingest(): 见 SENSOR_MAP (温度/功率/循环数/姿态/残差)。
  · 没传感器就不更新那一路 —— 只按衰减走, 并在 snapshot() 里标 estimated=True。
  · 任何一路都不"补数", 缺失就是缺失。

可运行 / 可观察 / 可调试:
  python3 src/lerobot/manifold/homeostasis.py --selftest   # 断言自检 (判据可核)
  python3 src/lerobot/manifold/homeostasis.py --demo       # 三阶段演示 (照老倪文章的剧本)
  python3 src/lerobot/manifold/homeostasis.py --state      # 打印当前快照 JSON (可被画布/控制台读)
  --watch N --dt D  连续 N 步打印每步快照 (VSCode F5 断点用: 见 .vscode/launch.json)
"""
from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

# ── 观测/落盘位置 (绝对路径, 便于 VSCode 直接跳转与外部读取) ──
ZMAX_ROOT = "/home/ubuntu/zmax"
STATE_JSON = os.path.join(ZMAX_ROOT, "zmax_data/ss_live/manifold_homeostasis.json")
LEDGER_JSONL = os.path.join(ZMAX_ROOT, "zmax_data/ss_live/manifold_homeostasis.jsonl")


# ══════════════════════════════════════════════════════════════════════════════
# 真传感器映射 (有就 ingest, 没有就不更新 → 标 estimated)
# ══════════════════════════════════════════════════════════════════════════════
SENSOR_MAP = {
    # 稳态量       真实来源                                          换算
    "temperature": "nvidia-smi temperature.gpu (℃) / 主机温度传感器",
    "energy": "(无电池时机型) 供电功率瓦数 → 剩余可用预算; 有电池 = SOC",
    "wear": "关节循环数 / 累计运行时长 (维护台账)",
    "balance": "tcp_pose 姿态倾角 (相对重力) 或 投影点到流形边界距离",
    "alignment": "任务残差 (‖residual‖) 与流形置信度 confidence 的组合",
}


def satisfy(x: float, lo: float, hi: float) -> float:
    """把**够用就好**的工程量映射成稳态满意度 s ∈ [0,1] (x ≥ hi → 1.0 满足)。

    为什么需要它 (2026-10-10 实测踩到): 直接把"置信度 0.9"当 alignment 喂进去, 偏差 0.1 ⇒
    u=0.1·1.5·1.1=0.165 虽不触发抢占, 但会通过动作调制把增益压到 <1 ⇒ **健康状态下动作也被改**,
    零回归断言直接失败。稳态要的是"够用", 不是"满分"; 故每路真信号都要先过 satisfy 换算,
    阈值 (lo/hi) 写在注释里, 可核可调。
    """
    if hi <= lo:
        return 0.0
    return float(max(0.0, min(1.0, (float(x) - float(lo)) / (float(hi) - float(lo)))))


def sensor_map_note() -> dict:
    """各路的 satisfy 阈值 (真信号 → 满意度的换算口径, 交付时可核)。"""
    return {"alignment": "流形投影置信度 confidence: ≤0.20 → 0.0, ≥0.80 → 1.0 (线性)",
            "balance": "tcp 倾角(度) 相对重力: ≤2° → 1.0, ≥25° → 0.0 (线性反向)",
            "temperature": "GPU/关节温度: ≤65℃ → 1.0, ≥85℃ → 0.0 (线性反向)",
            "energy": "供电余量/SOC: ≥60% → 1.0, ≤5% → 0.0",
            "wear": "累计循环/设计寿命: ≤20% → 1.0, ≥100% → 0.0"}


@dataclass
class HomeostasisState:
    """内稳态状态 —— 机器人的"身体"。

    五个核心指标, 全部 [0,1], 1=最佳, 0=崩溃。
    `estimated[i]=True` 表示这一路**没有真传感器**, 是纯衰减外推 (如实标注, 不冒充测量值)。
    """

    energy: float = 1.0          # 能量 (供电预算 / SOC)
    temperature: float = 1.0     # 温度安全度 (越热越低)
    wear: float = 1.0            # 硬件健康度 (磨损 = 1 − 累计损伤)
    balance: float = 1.0         # 姿态安全度
    alignment: float = 1.0       # 任务对齐度

    KEYS: tuple = ("energy", "temperature", "wear", "balance", "alignment")
    # ⚠️ 2026-10-10 实测修正: 硬闸只认**身体量** (能量/温度/磨损/姿态)。第一版把 alignment 也算进去,
    #   结果流形置信度低的帧 → alignment≈0 → 直接判"危险"全零动作 (自检 ⚖ 健康项实测失败, mode=safe_stop)。
    #   语义上: 对齐差 ≠ 身体危险, 它该触发**任务级**响应 (重规划/导航), 由流形链路自己做。故:
    BODY_KEYS: tuple = ("energy", "temperature", "wear", "balance")

    # 危险阈值 (低于它 = 该路崩溃)
    ENERGY_CRITICAL: float = 0.15
    TEMP_CRITICAL: float = 0.10
    WEAR_CRITICAL: float = 0.05
    BALANCE_CRITICAL: float = 0.20
    ALIGNMENT_CRITICAL: float = 0.10

    # 自然衰减率 (每秒) —— 身体在消耗
    decay_rates: dict = field(default_factory=lambda: {
        "energy": 0.0005, "temperature": 0.0001, "wear": 0.00001,
        "balance": 0.0002, "alignment": 0.0003,
    })
    # 每路是否只有衰减外推 (无真传感器)
    estimated: dict = field(default_factory=lambda: {k: True for k in
                                                     ("energy", "temperature", "wear", "balance", "alignment")})
    last_sensor_ts: dict = field(default_factory=dict)

    # ── 时间积分 ──
    def step_decay(self, dt: float = 0.01) -> None:
        """自然衰减: 身体在消耗 (不含任何外部做功)。"""
        for k in self.KEYS:
            v = getattr(self, k) - self.decay_rates.get(k, 0.0) * dt
            setattr(self, k, float(max(0.0, min(1.0, v))))

    # ── 真信号注入 ──
    def ingest(self, **kw: float) -> dict:
        """注入真传感器读数 (只覆盖给到的那几路, 并解除 estimated 标记)。

        返回被接受的键 —— 调用方据此知道"哪几路是真测量"。
        """
        got = {}
        for k, v in kw.items():
            if k not in self.KEYS or v is None:
                continue
            setattr(self, k, float(max(0.0, min(1.0, float(v)))))
            self.estimated[k] = False
            self.last_sensor_ts[k] = time.time()
            got[k] = round(getattr(self, k), 6)
        return got

    # ── 派生量 ──
    def deviations(self) -> dict:
        """偏离最佳状态的程度 (0=最佳, 1=崩溃)。"""
        return {k: round(1.0 - getattr(self, k), 6) for k in self.KEYS}

    def is_critical(self) -> bool:
        """是否处于**危险**状态 (硬闸: 任一**身体量**跌破阈值; 对齐不参与, 见 BODY_KEYS 注释)。"""
        return any(getattr(self, k) < self._crit()[k] for k in self.BODY_KEYS)

    def _crit(self) -> dict:
        return {"energy": self.ENERGY_CRITICAL, "temperature": self.TEMP_CRITICAL,
                "wear": self.WEAR_CRITICAL, "balance": self.BALANCE_CRITICAL,
                "alignment": self.ALIGNMENT_CRITICAL}

    def critical_keys(self) -> list:
        c = self._crit()
        return [k for k in self.BODY_KEYS if getattr(self, k) < c[k]]

    def as_dict(self) -> dict:
        return {k: round(float(getattr(self, k)), 6) for k in self.KEYS}

    def vitality(self) -> float:
        """生命力 = 最低那一路 (木桶原理; 用于对外报数, 不用平均值掩盖短板)。"""
        return float(min(getattr(self, k) for k in self.KEYS))


class FunctionalFeeling:
    """功能性感受层 —— 偏差 → 紧迫度 → 行为权重。

    ⚠️ 功能性: 它驱动行为, 不声称主观体验。
    """

    DEFAULT_WEIGHTS = {"energy": 2.0, "temperature": 3.0, "wear": 1.0,
                       "balance": 5.0, "alignment": 1.5}

    # ⚠️ 2026-10-10 实测修正: 软闸(抢占)只能看**没有专属行为**的瞬时安全量。
    #   第一版把 5 路全放进软闸 → energy=0.25 时 u(energy)=0.75·2·1.75=2.625 早已越过阈值,
    #   于是永远走"抢占"而**轮不到 recharge**(自检 ⑥ 实测失败)。能量/磨损各自有专属行为
    #   (recharge / maintenance), 该由能量阈值先接管; 抢占只留给姿态/温度这类"必须马上停"的量。
    DEFAULT_INTERRUPT_KEYS = ("balance", "temperature")
    # 动作调制(越急越谨慎)只看身体量; 对齐差不该让动作变小 (那是任务级的事)
    DEFAULT_MODULATION_KEYS = ("balance", "temperature", "energy", "wear")

    def __init__(self, weights: Optional[dict] = None,
                 interrupt_threshold: float = 0.8,
                 interrupt_keys: Optional[tuple] = None) -> None:
        self.urgency_weights = dict(self.DEFAULT_WEIGHTS)
        if weights:
            self.urgency_weights.update(weights)
        self.interrupt_threshold = float(interrupt_threshold)
        self.interrupt_keys = tuple(interrupt_keys or self.DEFAULT_INTERRUPT_KEYS)
        self.modulation_keys = tuple(self.DEFAULT_MODULATION_KEYS)

    def compute_urgency(self, deviations: dict) -> dict:
        """u_i = d_i · w_i · (1 + d_i)  —— 偏差越大, 紧迫度增长越快 (非线性放大)。"""
        out = {}
        for k, d in deviations.items():
            w = self.urgency_weights.get(k, 1.0)
            out[k] = round(float(d * w * (1.0 + d)), 6)
        return out

    def dominant_drive(self, urgency: dict) -> tuple:
        """当前最强驱动力 (键, 值)。空输入时给 ("none", 0.0), 不编。"""
        if not urgency:
            return "none", 0.0
        k = max(urgency, key=lambda x: urgency[x])
        return k, urgency[k]

    def should_interrupt(self, urgency: dict, keys: Optional[tuple] = None) -> bool:
        """是否该抢占/中断当前任务 (默认只看 interrupt_keys: 姿态/温度)。

        keys=None → 用 self.interrupt_keys; 传 ("*",) 或 None 想全量时用 keys=tuple(urgency)。
        """
        ks = tuple(keys if keys is not None else self.interrupt_keys)
        vals = [urgency[k] for k in ks if k in urgency]
        return bool(vals) and max(vals) > self.interrupt_threshold

    def behavior_weights(self, urgency: dict) -> dict:
        """紧迫度 → 行为权重 (归一化; 供上层做动作调制/资源分配)。"""
        tot = float(sum(urgency.values())) or 1.0
        return {k: round(v / tot, 6) for k, v in urgency.items()}

    def adapt(self, key: str, factor: float, lo: float = 0.2, hi: float = 20.0) -> float:
        """按经历调权 (进化机制的最小可用版: 老是饿就提高能量权重)。夹在 [lo,hi]。"""
        if key not in self.urgency_weights:
            return 0.0
        self.urgency_weights[key] = float(max(lo, min(hi, self.urgency_weights[key] * factor)))
        return round(self.urgency_weights[key], 6)


class SelfModel:
    """自我模型 —— 记录自身状态与行为, 预测下一步, 估行为后果。

    注意: 这是**功能性的自我表征**, 不是"自我意识"。
    """

    def __init__(self, horizon: int = 10, memory: int = 1000) -> None:
        self.horizon = int(horizon)
        self.memory = int(memory)
        self.history: list = []
        self.n_actions = 0
        self.cum_energy_cost = 0.0

    def update(self, state: HomeostasisState, action: np.ndarray, ts: Optional[float] = None) -> None:
        a = np.asarray(action, float).ravel()
        self.history.append({"t": float(ts if ts is not None else time.time()),
                             "state": state.as_dict(), "action": [round(float(x), 6) for x in a],
                             "vitality": round(state.vitality(), 6)})
        if len(self.history) > self.memory:
            self.history.pop(0)
        self.n_actions += 1

    def predict_next(self, state: HomeostasisState, dt: float = 1.0,
                     action: Optional[np.ndarray] = None) -> dict:
        """预测下一步状态: 衰减 + 行为代价 (动作越大越费)。返回 dict (不原地改真实状态)。"""
        cons = self.estimate_action_consequence(np.zeros(6) if action is None else action)
        pred = {}
        for k in state.KEYS:
            decay = state.decay_rates.get(k, 0.0) * dt
            cost = cons["state_cost"].get(k, 0.0)
            pred[k] = round(float(max(0.0, min(1.0, getattr(state, k) - decay - cost))), 6)
        return pred

    def estimate_action_consequence(self, action: np.ndarray) -> dict:
        """行为后果预估 (一阶): 动作幅度 → 能量/姿态/磨损代价, 对齐收益。

        口径 (可核): |a|₁ = Σ|a_i|
          energy_cost = 0.001·|a|₁ · balance_risk = 0.01·|a_0| · wear_cost = 0.0002·|a|₁
        返回 state_cost 是**每路稳态量**的扣减, 供 predict_next 用 (单位与稳态量一致)。
        """
        a = np.asarray(action, float).ravel()
        l1 = float(np.abs(a).sum())
        if a.size == 0:
            l1 = 0.0
        ec, br, wc = 0.001 * l1, 0.01 * abs(float(a[0])) if a.size else 0.0, 0.0002 * l1
        return {"action_l1": round(l1, 6),
                "energy_cost": round(ec, 6), "balance_risk": round(br, 6), "wear_cost": round(wc, 6),
                "state_cost": {"energy": ec, "balance": br, "wear": wc}}

    def trend(self, window: int = 10) -> str:
        """状态趋势: improving / declining / stable / insufficient_data (按生命力)。"""
        if len(self.history) < window:
            return "insufficient_data"
        d = self.history[-1]["vitality"] - self.history[-window]["vitality"]
        if d > 0.01:
            return "improving"
        if d < -0.01:
            return "declining"
        return "stable"

    def summary(self, recent: int = 100) -> dict:
        if not self.history:
            return {"n_actions": 0, "state_trend": "insufficient_data"}
        h = self.history[-recent:]
        return {"n_actions": self.n_actions, "window": len(h),
                "avg_action_magnitude": round(float(np.mean([np.abs(x["action"]).sum() for x in h])), 6),
                "vitality_now": h[-1]["vitality"],
                "state_trend": self.trend(),
                "energy_spent_est": round(self.cum_energy_cost, 6)}


class HomeostasisEngine:
    """内稳态总控 —— 把"身体 + 功能性感受 + 自我模型"合成一个可嵌入的驱动器。

    对外只有两个动作:
      · drive(...)   → 决定此刻该干什么 (mode / urgency / veto / 动作调制权重)
      · snapshot()   → 可观察量 (JSON 可落盘、可上报、可在 VSCode 里逐行看)

    它**不**直接产生动作; 动作由 ManifoldEngine 的流形链路解出, 本层只做
    "该不该动 / 动多大 / 要不要停" —— 这就是"上层只给意图, 执行由下层收口"的分工。
    """

    def __init__(self, state: Optional[HomeostasisState] = None,
                 feeling: Optional[FunctionalFeeling] = None,
                 self_model: Optional[SelfModel] = None,
                 recharge_below: float = 0.30, maintenance_below: float = 0.20,
                 gain_lo: float = 0.25, gain_hi: float = 1.0) -> None:
        self.state = state or HomeostasisState()
        self.feeling = feeling or FunctionalFeeling()
        self.self_model = self_model or SelfModel()
        self.recharge_below = float(recharge_below)
        self.maintenance_below = float(maintenance_below)
        self.gain_lo, self.gain_hi = float(gain_lo), float(gain_hi)
        self.mode = "explore"
        self.safety_override = False
        self.n_steps = 0

    # ── 主循环 ──
    def drive(self, dt: float = 0.01, action: Optional[np.ndarray] = None,
              sensor: Optional[dict] = None, record: bool = True) -> dict:
        """一个时间步的驱动决策 (纯函数式输出, 无副作用除了自身状态推进)。"""
        if sensor:
            self.state.ingest(**sensor)
        self.state.step_decay(dt)
        dev = self.state.deviations()
        urg = self.feeling.compute_urgency(dev)
        dom, dom_u = self.feeling.dominant_drive(urg)
        self.n_steps += 1

        # ① 硬闸: 危险 → 安全停止 (veto)
        if self.state.is_critical():
            self.mode, self.safety_override = "safe_stop", True
            return self._finish(self._out("veto", urg, dom, dom_u, dev, gain=0.0,
                                          note="危险: %s 跌破阈值 → 动作全零" % ",".join(self.state.critical_keys())),
                                action, record)
        # ② 软闸: 紧迫度超阈 → 抢占 (可恢复)
        if self.feeling.should_interrupt(urg):
            self.mode, self.safety_override = "safe_stop", True
            return self._finish(self._out("interrupt", urg, dom, dom_u, dev, gain=0.0,
                                          note="紧迫度 %.3f > 阈值 %.2f → 抢占当前任务" % (dom_u, self.feeling.interrupt_threshold)),
                                action, record)
        # 危险解除 → 恢复
        if self.mode == "safe_stop":
            self.mode, self.safety_override = "explore", False
        # ③ 能量低 → 去充电; 磨损低 → 去维护
        if self.state.energy < self.recharge_below and not self.safety_override:
            self.mode = "recharge"
        elif self.state.wear < self.maintenance_below and not self.safety_override:
            self.mode = "maintenance"
        elif self.mode in ("recharge", "maintenance") and \
                self.state.energy >= self.recharge_below and self.state.wear >= self.maintenance_below:
            self.mode = "explore"

        # ④ 动作调制: **身体量**紧迫度越高, 允许的动作幅度越小 (越急越谨慎) —— 有下界, 不是急就停摆
        body_u = max([urg.get(k, 0.0) for k in self.feeling.modulation_keys] or [0.0])
        g = float(np.clip(1.0 - 0.5 * float(body_u) / max(self.feeling.interrupt_threshold, 1e-9),
                          self.gain_lo, self.gain_hi))
        return self._finish(self._out("drive", urg, dom, dom_u, dev, gain=g,
                                      note="mode=%s · 主导驱动 %s(%.3f) · 身体紧迫 %.3f · 动作调制 ×%.3f"
                                           % (self.mode, dom, dom_u, body_u, g)), action, record)

    def _finish(self, out: dict, action, record: bool) -> dict:
        """统一收尾: 自我模型在**所有**路径都记录 (停止也是行为, 必须进自我模型)。"""
        if record:
            a = np.zeros(6) if action is None else np.asarray(action, float).ravel()
            self.self_model.update(self.state, a)
            c = self.self_model.estimate_action_consequence(a)
            self.self_model.cum_energy_cost += c["energy_cost"]
        return out

    def _out(self, kind: str, urg: dict, dom: str, dom_u: float, dev: dict, gain: float, note: str) -> dict:
        return {"kind": kind, "mode": self.mode, "safety_override": self.safety_override,
                "urgency": urg, "dominant": dom, "dominant_urgency": round(float(dom_u), 6),
                "deviations": dev, "action_gain": round(float(gain), 6),
                "behavior_weights": self.feeling.behavior_weights(urg),
                "is_critical": self.state.is_critical(), "vitality": round(self.state.vitality(), 6),
                "note": note, "n_steps": self.n_steps}

    def snapshot(self) -> dict:
        """可观察量 (画布/控制台/外部工具都读这一份)。"""
        dev = self.state.deviations()
        urg = self.feeling.compute_urgency(dev)
        dom, dom_u = self.feeling.dominant_drive(urg)
        return {"ts": time.time(), "mode": self.mode, "sensor_satisfy": sensor_map_note(), "safety_override": self.safety_override,
                "state": self.state.as_dict(), "estimated": dict(self.state.estimated),
                "vitality": round(self.state.vitality(), 6),
                "is_critical": self.state.is_critical(), "critical_keys": self.state.critical_keys(),
                "deviations": dev, "urgency": urg, "dominant": dom,
                "dominant_urgency": round(float(dom_u), 6),
                "urgency_weights": dict(self.feeling.urgency_weights),
                "interrupt_threshold": self.feeling.interrupt_threshold,
                "interrupt_keys": list(self.feeling.interrupt_keys),
                "behavior_weights": self.feeling.behavior_weights(urg),
                "self_model": self.self_model.summary(),
                "next_predicted": self.self_model.predict_next(self.state),
                "sensor_map": SENSOR_MAP, "n_steps": self.n_steps,
                "boundary": "功能性内稳态: 驱动行为, 不声称主观体验"}

    def write_state(self, path: str = STATE_JSON, append_ledger: bool = False) -> str:
        """落盘 (原子写): 最新快照 + 可选台账逐行追加。"""
        snap = self.snapshot()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(snap, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
        if append_ledger:
            with open(LEDGER_JSONL, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts": snap["ts"], "mode": snap["mode"],
                                     "vitality": snap["vitality"],
                                     "dominant": snap["dominant"],
                                     "urgency": snap["dominant_urgency"],
                                     "state": snap["state"]}, ensure_ascii=False) + "\n")
        return path


# ══════════════════════════════════════════════════════════════════════════════
# 自检 / 演示 CLI (VSCode F5 可断点: 每步都有具名中间量)
# ══════════════════════════════════════════════════════════════════════════════
def _selftest() -> int:
    print("=" * 78)
    print("🧮 内稳态层自检 (阈值/紧迫度/硬闸/软闸/自我模型 全部可核)")
    print("=" * 78)
    ok = True

    # ① 衰减单调 + 不越界
    st = HomeostasisState()
    before = st.as_dict()
    for _ in range(1000):
        st.step_decay(1.0)
    after = st.as_dict()
    dec = all(after[k] <= before[k] for k in before)
    inrange = all(0.0 <= v <= 1.0 for v in after.values())
    print(f"  ① 自然衰减: 单调不增={dec} · 界内={inrange} · 1000s 后 "
          f"energy {before['energy']:.4f}→{after['energy']:.4f} {'✅' if dec and inrange else '❌'}")
    ok &= bool(dec and inrange)

    # ② 紧迫度非线性放大 + 主导驱动
    f = FunctionalFeeling()
    u = f.compute_urgency({"balance": 0.5, "energy": 0.1})
    amp = u["balance"] > 0.5 * f.urgency_weights["balance"]
    dom = f.dominant_drive(u)[0]
    print(f"  ② 紧迫度: u(balance,0.5)={u['balance']:.3f} > 线性 {0.5 * f.urgency_weights['balance']:.3f} "
          f"= {amp} · 主导={dom} {'✅' if amp and dom == 'balance' else '❌'}")
    ok &= bool(amp and dom == "balance")

    # ③ 硬闸: 危险 → veto + gain 0
    h = HomeostasisEngine()
    h.state.energy = 0.01
    out = h.drive(dt=0.0)
    print(f"  ③ 硬闸: energy=0.01 → kind={out['kind']} mode={out['mode']} gain={out['action_gain']} "
          f"critical={out['is_critical']} {'✅' if out['kind'] == 'veto' and out['action_gain'] == 0 else '❌'}")
    ok &= bool(out["kind"] == "veto" and out["action_gain"] == 0.0)

    # ④ 软闸: 紧迫度超阈 → interrupt (不可恢复态未到危险)
    h2 = HomeostasisEngine()
    h2.feeling.interrupt_threshold = 0.5
    h2.state.balance = 0.85          # 偏差 0.15 → u = 0.15*5*1.15 = 0.8625 > 0.5, 但未破 0.20 硬闸
    out2 = h2.drive(dt=0.0)
    print(f"  ④ 软闸: balance=0.85 → u={out2['dominant_urgency']:.4f} kind={out2['kind']} "
          f"critical={out2['is_critical']} {'✅' if out2['kind'] == 'interrupt' and not out2['is_critical'] else '❌'}")
    ok &= bool(out2["kind"] == "interrupt" and not out2["is_critical"])

    # ⑤ 恢复: 危险解除后能自己出来
    h.state.energy = 0.9
    out3 = h.drive(dt=0.0)
    print(f"  ⑤ 恢复: energy 0.01→0.9 → mode={out3['mode']} override={out3['safety_override']} "
          f"kind={out3['kind']} {'✅' if out3['mode'] != 'safe_stop' and not out3['safety_override'] else '❌'}")
    ok &= bool(out3["mode"] != "safe_stop" and not out3["safety_override"])

    # ⑥ 低能量 → recharge; 低磨损 → maintenance (软闸不得抢在专属行为之前)
    h3 = HomeostasisEngine(); h3.state.energy = 0.25
    o1 = h3.drive(dt=0.0); m1 = o1["mode"]
    h4 = HomeostasisEngine(); h4.state.wear = 0.15
    m2 = h4.drive(dt=0.0)["mode"]
    print(f"  ⑥ 行为切换: energy=0.25→{m1} (kind={o1['kind']}, u(energy)={o1['urgency']['energy']:.3f} "
          f"但软闸只看 {h3.feeling.interrupt_keys}) · wear=0.15→{m2} "
          f"{'✅' if m1 == 'recharge' and m2 == 'maintenance' else '❌'}")
    ok &= bool(m1 == "recharge" and m2 == "maintenance")

    # ⑦ 自我模型: 预测/后果/趋势
    h5 = HomeostasisEngine()
    a = np.array([0.5, 0.2, 0, 0, 0, 0.1])
    c = h5.self_model.estimate_action_consequence(a)
    pred = h5.self_model.predict_next(h5.state, dt=1.0, action=a)
    gate = c["energy_cost"] > 0 and pred["energy"] < h5.state.energy
    for _ in range(20):
        h5.drive(dt=0.01, action=a)
    tr = h5.self_model.trend()
    print(f"  ⑦ 自我模型: |a|₁={c['action_l1']:.3f} energy_cost={c['energy_cost']:.5f} "
          f"预测 energy 1.0→{pred['energy']:.5f} · 20 步后趋势={tr} "
          f"{'✅' if gate and tr in ('declining', 'stable', 'improving') else '❌'}")
    ok &= bool(gate)

    # ⑧ 观测量完整性 + 落盘
    snap = h5.snapshot()
    need = {"state", "urgency", "mode", "self_model", "estimated", "boundary", "next_predicted"}
    miss = need - set(snap)
    p = h5.write_state()
    print(f"  ⑧ 观测量: 键完整={not miss} (缺 {sorted(miss) or '无'}) · 已落盘 {os.path.relpath(p, ZMAX_ROOT)} "
          f"{'✅' if not miss and os.path.isfile(p) else '❌'}")
    ok &= bool(not miss and os.path.isfile(p))

    # ⑨ 真信号 ingest 必须解除 estimated 标记 (不许把外推冒充测量)
    st2 = HomeostasisState()
    got = st2.ingest(temperature=0.72)
    print(f"  ⑨ 真信号: ingest(temperature=0.72) → {got} · estimated['temperature']="
          f"{st2.estimated['temperature']} (其余仍 {sum(st2.estimated.values())} 路 estimated) "
          f"{'✅' if st2.estimated['temperature'] is False and st2.estimated['energy'] is True else '❌'}")
    ok &= bool(st2.estimated["temperature"] is False and st2.estimated["energy"] is True)

    print("\n自检结果:", "全部通过 ✅" if ok else "有失败 ❌")
    print("HOMEOSTASIS_SELFTEST_DONE")
    return 0 if ok else 1


def _demo() -> int:
    """照老倪文章的剧本走三阶段 (正常运行 / 能量耗尽 / 危险崩溃)。"""
    h = HomeostasisEngine()
    print("=" * 78)
    print("流形引擎 · 内稳态与自主安全演示 (功能性内稳态, 不声称主观体验)")
    print("=" * 78)
    #   阶段拆分比原剧本细一档: 能量「偏低→去充电」与「耗尽→安全停止」是**两种**行为, 分开看才不误读
    for phase, setup, n, dt in (("阶段1 正常运行", None, 100, 0.1),
                                ("阶段2 能量偏低 (0.28 → 去充电 ♻)", lambda: h.state.ingest(energy=0.28), 50, 0.1),
                                ("阶段3 能量耗尽 (0.10 → 安全停止 ⛔)", lambda: h.state.ingest(energy=0.10), 20, 0.1),
                                ("阶段4 危险状态 (崩溃模拟)", lambda: h.state.ingest(energy=0.01, temperature=0.05,
                                                                                balance=0.10), 20, 0.1)):
        if setup:
            setup()
        print(f"\n[{phase}]")
        _kinds, _modes = set(), set()
        for i in range(n):
            out = h.drive(dt=dt, action=np.array([0.1, 0, 0, 0, 0, 0]))
            _kinds.add(out["kind"]); _modes.add(out["mode"])
            if i % max(1, n // 5) == 0:
                print(f"  步骤{i:3d}: 生命力={out['vitality']:.3f} 能量={h.state.energy:.3f} "
                      f"模式={out['mode']:11s} 主导={out['dominant']}({out['dominant_urgency']:.3f}) "
                      f"增益={out['action_gain']:.3f} {'⛔危险' if out['is_critical'] else ''}")
        print(f"  小结: 行为 {sorted(_modes)} · 类型 {sorted(_kinds)} · 末态生命力 {h.state.vitality():.3f}")
    print("\n" + "=" * 78)
    print("演示结束 · 快照:", os.path.relpath(h.write_state(), ZMAX_ROOT))
    print("=" * 78)
    return 0


def _state() -> int:
    h = HomeostasisEngine()
    if os.path.isfile(STATE_JSON):                     # 有历史就接着读 (不重置)
        try:
            old = json.load(open(STATE_JSON, encoding="utf-8"))
            h.state.ingest(**{k: v for k, v in (old.get("state") or {}).items()})
            h.mode = old.get("mode", h.mode)
        except Exception as e:                                                 # noqa: BLE001
            print("⚠️ 读历史快照失败(按初始值来):", e)
    print(json.dumps(h.snapshot(), ensure_ascii=False, indent=1))
    print("HOMEOSTASIS_STATE_DONE")
    return 0


def _watch(n: int, dt: float) -> int:
    h = HomeostasisEngine()
    for i in range(n):
        out = h.drive(dt=dt, action=np.zeros(6))
        print(f"[{i:04d}] {json.dumps({k: out[k] for k in ('kind', 'mode', 'vitality', 'dominant', 'dominant_urgency', 'action_gain')}, ensure_ascii=False)}")
    h.write_state(append_ledger=True)
    print("HOMEOSTASIS_WATCH_DONE")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="流形引擎 · 内稳态层 (可运行/可观察/可调试)")
    ap.add_argument("--selftest", action="store_true", help="断言自检 (默认)")
    ap.add_argument("--demo", action="store_true", help="三阶段演示")
    ap.add_argument("--state", action="store_true", help="打印当前快照 JSON")
    ap.add_argument("--watch", type=int, default=0, help="连续 N 步打印每步快照")
    ap.add_argument("--dt", type=float, default=0.1, help="步长 (秒)")
    a = ap.parse_args()
    if a.watch:
        raise SystemExit(_watch(a.watch, a.dt))
    if a.demo:
        raise SystemExit(_demo())
    if a.state:
        raise SystemExit(_state())
    raise SystemExit(_selftest())
