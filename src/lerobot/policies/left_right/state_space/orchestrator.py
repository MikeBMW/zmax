#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""orchestrator.py —— 信号级总调度（仲裁器），装在 🧭 动作调制器 `cognition.ActionModulator` 里。

为什么放在调制器里（而不是新画布节点）：
  · 调制器是唯一同时握有「各层提案 + 阶段机 + 物理闸(原子技能 SK01-08 / InertiaLimiter)」的地方，
    总调度要的正是这三样；另开节点等于把闸复制一份，出现两个真源。
  · 权限顺序天然成立：仲裁只决定「听谁的、要不要停」，物理限幅仍由原来那条唯一路径收口。

职责边界（写死，防止越权）：
  ✗ 不算轨迹（流形引擎 ss_mani_eng 的事）
  ✗ 不识别图像（YOLO/VLM 的事）
  ✗ 不改物理限幅参数（`physics_constraints.InertiaLimiter` 真源）
  ✓ 只做四件事：① 层权重按阶段配比 ② 一票否决（力/残差/收敛）
                ③ 加权融合成候选动作 ④ 记录遥测，供画布与复盘读取

四步流水线（与脑内定位一致：基底核 = 投票/否决/限幅，不是规划）：
  Step1 相位      su2 遥测 (θ / |w| / 非交换) → 收敛度；收敛差 ⇒ 收窄 L3 权重
  Step2 层提案    L2 前馈(肌肉) / L3 VLA 动作块 / L4 流形梯度 / 记忆直通，缺项就归一化权重
  Step3 仲裁      力超限 → 否决 L3；残差超阈 → 保守化/连续则停；阶段敏感 → L4 主导
  Step4 交付     返回融合后的 u（随后由调制器既有 ③阶段限速 ④元任务门控 收口）+ 遥测

开关（默认关，逐位不变）：
  ZMAX_ORCH=1            启用仲裁；0/未设 ⇒ decide() 走原 ①② 路径，行为逐位不变
  ZMAX_ORCH_FORCE_N      力否决阈值 (N)，默认按阶段表，见 STAGE_FORCE_N
  ZMAX_ORCH_LOG          遥测 jsonl 路径，默认 zmax_data/ss_live/orch_telemetry.jsonl
  ZMAX_ORCH_KEEP         内存里保留最近多少条遥测，默认 200

真机现状（必须如实说明，避免把设计当能力）：
  · 现在能拿到的层只有 L2(u_ff 前馈/肌肉) 与 L4(u_fb 状态校正/流形)；VLA 的 H 步动作块
    在真机上还没有实时注入管线 ⇒ 本类按 `set_layer("L3", vec)` 预留，缺 L3 时权重自动归一化。
  · 控制频率不是他文中的 1kHz：画布循环 10Hz、标定口径 dt=0.1s（physics_constraints 真源），
    本类所有判据都用调用方传入的 dt，不假设频率。
"""

from __future__ import annotations

import json
import os
import threading
import time

import numpy as np

# 阶段 → 各层权重（L3 大模型意图 / L4 流形+物理几何 / L2 前馈肌肉 + 记忆直通）
# 取值依据：插装类敏感段让物理几何说话，自由移动段让大模型给方向；三者和为 1。
STAGE_W = {
    # 自由移动段：大模型给方向，物理只需兜底
    "接近":   {"L3": 0.50, "L4": 0.32, "L2": 0.18},
    "抬起":   {"L3": 0.50, "L4": 0.32, "L2": 0.18},
    "转移":   {"L3": 0.55, "L4": 0.30, "L2": 0.15},
    "AOI转移": {"L3": 0.55, "L4": 0.30, "L2": 0.15},
    "回程":   {"L3": 0.55, "L4": 0.30, "L2": 0.15},
    # 对位/检测段：几何精度主导
    "对位":   {"L3": 0.25, "L4": 0.55, "L2": 0.20},
    "下降":   {"L3": 0.20, "L4": 0.58, "L2": 0.22},
    "AOI检测": {"L3": 0.15, "L4": 0.60, "L2": 0.25},
    # 接触/插装段：物理几何一票独大，大模型只剩 10%
    "抓取":   {"L3": 0.10, "L4": 0.60, "L2": 0.30},
    "插入":   {"L3": 0.10, "L4": 0.60, "L2": 0.30},
    "拔出":   {"L3": 0.10, "L4": 0.60, "L2": 0.30},
    "放下":   {"L3": 0.10, "L4": 0.60, "L2": 0.30},
    "完成":   {"L3": 0.00, "L4": 0.60, "L2": 0.40},
}
STAGE_W_DEFAULT = {"L3": 0.40, "L4": 0.35, "L2": 0.25}

# 阶段 → 力否决阈值 (N)。来源：现场红线「插入力 ≤ 40N」；对位/接近段更保守。
STAGE_FORCE_N = {
    "接近": 30.0, "对位": 25.0, "下降": 25.0, "抓取": 40.0, "抬起": 30.0,
    "转移": 30.0, "插入": 40.0, "完成": 20.0, "拔出": 40.0, "AOI转移": 30.0,
    "AOI检测": 20.0, "回程": 30.0, "放下": 25.0,
}
FORCE_N_DEFAULT = 40.0

# 收敛度 |w| 低于此值 = 各层意图发散（群元素远离恒等元）⇒ 收窄大模型权重
CONV_WARN = 0.55
# 非交换量超过此值 = 层间强耦合（实测 L3|L4 = 1.19 rad ≈ 68°），敏感段要更依赖几何
NONCOMM_WARN = 0.80


class Orchestrator:
    """信号级仲裁器。线程安全（画布 10Hz 与服务可能并发读遥测）。"""

    def __init__(self, am=None, force_n=None, log_path=None, keep=None):
        self.am = am                                   # 调制器（取 stage()/veto_th/max_veto 等真源）
        self.force_n_override = force_n                # None ⇒ 按阶段表
        self.enabled = os.environ.get("ZMAX_ORCH", "0").strip().lower() in ("1", "true", "yes", "on")
        self.log_path = log_path or os.environ.get("ZMAX_ORCH_LOG") or ""
        self.keep = int(keep or os.environ.get("ZMAX_ORCH_KEEP") or 200)
        self._layers = {}                              # {"L3": vec, ...} 由上游注入（缺则不参与）
        self._last_u = None                            # 降级透传用的最后稳定动作
        self._veto_streak = 0
        self._lock = threading.Lock()
        self.tele = {}                                 # 最近一次遥测（画布读它）
        self.history = []                               # 最近 keep 条
        self.counts = {"steps": 0, "veto_force": 0, "veto_residual": 0,
                       "hold": 0, "degraded": 0, "blend": 0}

    # ── 上游注入层提案 ───────────────────────────────────────────────────
    def set_layer(self, name, vec):
        """注入某一层的动作提案（L3=VLA 动作块 / L4=流形梯度 / L2=肌肉直通）。
        vec=None 或空 ⇒ 该层退出本轮配比（不自造零动作冒充）。"""
        with self._lock:
            if vec is None:
                self._layers.pop(name, None)
                return
            v = np.asarray(vec, dtype=float).ravel()
            if v.size == 0:
                self._layers.pop(name, None)
            else:
                self._layers[name] = v

    def clear_layers(self):
        with self._lock:
            self._layers.clear()

    # ── 主入口 ─────────────────────────────────────────────────────────
    def arbitrate(self, u_ff, u_fb, contact_p=0.0, residual=0.0, meta=None,
                  stage=None, force_n=None, su2=None, dt=0.02, injected=True):
        """返回 (u | None, tag, vetoed)。

        u=None 且 vetoed=True ⇒ 本拍不下发动作（调制器返回全零/保持）。
        u=None 且 vetoed=False ⇒ 降级透传（视觉/网络丢失时用最后稳定动作）。
        """
        am = self.am
        st = stage or (am.stage() if am is not None and hasattr(am, "stage") else "未知")
        veto_th = float(getattr(am, "veto_th", 2.0)) if am is not None else 2.0
        max_veto = int(getattr(am, "max_veto", 3)) if am is not None else 3
        u_ff = np.asarray(u_ff, dtype=float).ravel()
        u_fb = np.asarray(u_fb, dtype=float).ravel() if u_fb is not None else np.zeros_like(u_ff)

        with self._lock:
            # ── Step2 层提案（缺项不参与，权重后面归一化）────────────────
            layers = {}
            for _n, _v in (("L2", u_ff), ("L4", u_fb)):
                if np.linalg.norm(_v) > 1e-12:      # 全零 = 该层没有提案(不动 ≠ 提案), 不参与配比
                    layers[_n] = _v
            for k, v in self._layers.items():
                if v.size == u_ff.size and np.linalg.norm(v) > 1e-12:
                    layers[k] = v
            # 🧠 2026-11-14 单一真源: 状态机的策略表(POLICY)优先 —— 状态与配比必须同源,
            #   否则"状态在这一处、权重在那一处"迟早对不上。fsm 不可用(或 ZMAX_FSM=0)才回退本文件的 STAGE_W。
            _fsm = getattr(am, "fsm", None) if am is not None else None
            if _fsm is not None:
                _p = _fsm.policy()
                w = {"L3": float(_p["w_L3"]), "L4": float(_p["w_L4"]), "L2": float(_p["w_L2"])}
            else:
                w = dict(STAGE_W.get(st, STAGE_W_DEFAULT))

            # ── Step1 相位（su2 遥测；没有就明说没有，不用默认值假装）────
            conv = None
            noncomm = None
            if isinstance(su2, dict):
                if su2.get("w_abs") is not None:
                    conv = float(su2["w_abs"])
                noncomm = su2.get("noncomm")
                noncomm = float(noncomm) if noncomm is not None else None
            if conv is not None and conv < CONV_WARN and w.get("L3", 0) > 0:
                # 层间发散 ⇒ 大模型让位给几何：L3 砍半，差额按比例给 L4/L2
                cut = w["L3"] * 0.5
                w["L3"] -= cut
                tot = max(1e-9, w["L4"] + w["L2"])
                w["L4"] += cut * w["L4"] / tot
                w["L2"] += cut * w["L2"] / tot
            if (noncomm is not None and noncomm > NONCOMM_WARN
                    and st in ("插入", "抓取", "对位", "下降") and w.get("L3", 0) > 0):
                cut = w["L3"] * 0.5
                w["L3"] -= cut
                w["L4"] += cut

            # ── Step3 仲裁：优先级 力 > 残差 > 层缺失 ─────────────────────
            flim = float(self.force_n_override if self.force_n_override is not None
                         else STAGE_FORCE_N.get(st, FORCE_N_DEFAULT))
            f_now = float(force_n) if force_n is not None else None
            veto_reason = ""
            if f_now is not None and f_now > flim:
                # 力超限：一票否决大模型，只留物理几何+肌肉（保住接触里的保守动作）
                w["L3"] = 0.0
                veto_reason = "力否决 %.1fN>%.1fN" % (f_now, flim)
                self.counts["veto_force"] += 1
            if residual > veto_th:
                self._veto_streak += 1
                if self._veto_streak >= max_veto:
                    self.counts["hold"] += 1
                    self.counts["veto_residual"] += 1
                    tele = self._tele(st, w, layers, conv, noncomm, f_now, flim, residual,
                                      0.0, "异常: 连续否决 (残差 %.2f)" % residual, veto_reason, dt)
                    return None, "异常: 连续否决 (残差 %.2f)" % residual, True
                self.counts["veto_residual"] += 1
                # 单次越阈：保守化 ⇒ 只信几何，方向仍按几何走（不硬停，避免抖动）
                w["L3"] = 0.0
                veto_reason = (veto_reason + " · " if veto_reason else "") + \
                              "残差异常 %.2f>%.2f → 只信几何" % (residual, veto_th)
            else:
                self._veto_streak = 0

            # 降级：视觉/网络丢失 ⇒ 原样透传最后稳定动作（并计数报警）
            if not injected:
                self.counts["degraded"] += 1
                u = self._last_u if self._last_u is not None else np.zeros_like(u_ff)
                tele = self._tele(st, w, layers, conv, noncomm, f_now, flim, residual,
                                  float(np.linalg.norm(u[:3])), "降级透传", veto_reason, dt)
                return u, "降级透传(最后稳定动作)", False

            # 权重归一（只对真实存在的层）
            avail = [k for k in ("L3", "L4", "L2") if k in layers and w.get(k, 0) > 0]
            if not avail:
                self.counts["hold"] += 1
                tele = self._tele(st, w, layers, conv, noncomm, f_now, flim, residual,
                                  0.0, "无可用层 → 保持", veto_reason, dt)
                return None, "无可用层 → 保持", True
            wsum = sum(w[k] for k in avail)
            u = np.zeros_like(u_ff)
            for k in avail:
                u = u + (w[k] / wsum) * layers[k].astype(float)

            # 维度不齐一律报出来（静默截断是最坏的习惯）
            if u.size != u_ff.size:
                tele = self._tele(st, w, layers, conv, noncomm, f_now, flim, residual,
                                  0.0, "维度不齐 → 保持", veto_reason, dt)
                return None, "维度不齐(%d≠%d) → 保持" % (u.size, u_ff.size), True

            self._last_u = u.copy()
            self.counts["blend"] += 1
            tag = "仲裁 %s" % "/".join("%s%.2f" % (k, w[k] / wsum) for k in avail)
            if veto_reason:
                tag += " · " + veto_reason
            tele = self._tele(st, w, layers, conv, noncomm, f_now, flim, residual,
                              float(np.linalg.norm(u[:3])), tag, veto_reason, dt)
            return u, tag, False

    # ── 遥测 ───────────────────────────────────────────────────────────
    def _tele(self, st, w, layers, conv, noncomm, f_now, flim, residual, u_norm, why, veto, dt):
        self.counts["steps"] += 1
        d = {
            "ts": round(time.time(), 3), "stage": st, "dt": float(dt),
            "weights": {k: round(float(v), 3) for k, v in w.items()},
            "layers": sorted(layers), "layer_norms": {k: round(float(np.linalg.norm(v[:3])), 4)
                                                     for k, v in layers.items()},
            "conv_w": None if conv is None else round(conv, 4),
            "noncomm": None if noncomm is None else round(noncomm, 4),
            "force_n": None if f_now is None else round(f_now, 2),
            "force_lim": round(flim, 2), "residual": round(float(residual), 3),
            "u_norm": round(float(u_norm), 4), "why": why, "veto": veto,
            "counts": dict(self.counts),
        }
        self.tele = d
        self.history.append(d)
        if len(self.history) > self.keep:
            self.history = self.history[-self.keep:]
        if self.log_path:
            try:
                os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(d, ensure_ascii=False) + "\n")
            except OSError:
                pass
        return d

    def line(self):
        """一行摘要，给画布节点日志用。"""
        t = self.tele or {}
        if not t:
            return "仲裁: 尚未运行"
        return ("仲裁 %s · 层 %s · 力 %s/%.0fN · 残差 %.2f · |u| %.3f · %s"
                % (t.get("stage"), "+".join(t.get("layers") or []),
                   "—" if t.get("force_n") is None else "%.1f" % t["force_n"],
                   t.get("force_lim", 0), t.get("residual", 0), t.get("u_norm", 0), t.get("why")))


def attach(am):
    """把仲裁器挂到调制器上（幂等）。ZMAX_ORCH 未开时返回 None，decide() 完全不走新路径。"""
    if os.environ.get("ZMAX_ORCH", "0").strip().lower() not in ("1", "true", "yes", "on"):
        return None
    if getattr(am, "orch", None) is not None:
        return am.orch
    am.orch = Orchestrator(am=am)
    return am.orch
