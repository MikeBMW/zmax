#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""energy_manifold.py — 流形引擎 · 能量层 (Energy Manifold) · 2026-10-07

老倪的要求 (原文口径):
  「设计流形引擎节点的逻辑, 类比发动机 —— 有输出功率、效率、转数等物理量; 流形引擎也要有
   结构化参数, 要有物理量, 有能量值。能量值要与 L2/L3/L4/L5 的模型和 LoRA 适配模型有映射。
   要能像作功一样, 从引擎读取到每层模型的能量值 (基础 L2 能量 / L3 增强 / L4 增强 / L5 增强)。
   随着能级的增加, 能量也可以扩展增加。总能量在流形引擎节点能被观察到, 能通过全局数据空间的
   topic 被观测 / 被测量 / 被记录。引擎总能量值 = 每层模型的能力总量。」

═══ 一、发动机 ↔ 流形引擎 对应表 (每个物理量都必须有真实可核的来源) ═══
   发动机                流形引擎                      真实来源 (缺 → -1/0 并如实标注)
   ─────────────────────────────────────────────────────────────────────────────
   缸数 / 排量            每层活跃子模型数 / 参数量        models_manifest · ckpt 实际参数量
   燃烧室几何             流形几何 + 潜维 (SU(2)/…, n)     manifold_engine.MANIFOLD_REGISTRY
   等效惯量 M             状态空间结构参数 (已有主标定)    manifold_engine.manifold_M_spec()
   转速 ω (r/min)         该层**更新频率** Hz             训练: 步/s (日志/进度) · 运行: 实测 Hz
   扭矩 τ (N·m)           该层**每循环有效做功** CJ/循环  势能(损失/误差)序列的每循环下降量
   输出功率 P = τ·ω       能力功率 CJ/s = 每循环做功×Hz   P = τ·ω (与发动机同式)
   输入功率 P_in           **GPU 电功率 W (真瓦特)**       nvidia-smi power.draw 实测
   累计能量 E = ∫P dt     能力能量 CJ (每层)               E = τ·ω·secs = τ·循环数
   效率 η = P_out/P_in    能力/电功比 CJ/J                 η = E_layer / W_in
   涡轮增压 LoRA          适配器注入的**附加扭矩** Δτ      适配器参数量占比; 有 A/B 时用实测 Δ
   摩擦/排气损耗          被否决 (w=0) / 被夹紧 (clip)      CapabilityStack.stats (真计数)
   冷却/保护 (爆震)       安全闸 (收口否决、Γ 主瓣)         闸门计数 (真值)

═══ 二、单位 (先钉死, 再谈数值) ═══
   1 CJ (能力焦耳) ≜ 把**归一化势能**下降 1.0 的能力       ⇒ 无量纲但可比, 逐层同口径
   1 J  (电焦耳)  = 1 W·s                                  ⇒ GPU 电功, 物理真实量
   η 单位 = CJ/J  ⇒ "每焦耳电换多少归一化能力" —— 可跨轮/跨层比较
   ⚠️ 绝不把 CJ 与 J 相加: 电功是**输入**, 能力是**输出**, 二者只能通过 η 相除比较。

═══ 三、能级壳层律 (「随着能级的增加, 能量也可以扩展增加」) ═══
   壳层 n:      L2=1 (基座)      L3=2          L4=3          L5=4
   能量:        E_L2 (基础自持)   +增强         +增强          +增强 (仅意图)
   累积:        E_cum(n) = Σ_{i≤n} E_i  ⇒ **单调不减** (能级越高, 总能量越大)
   可行域:      R_L2 ≥ R_L3 ≥ R_L4 ≥ R_L5     ⇒ **逐层收窄** (上层只给意图, L2 收口)
   ⚠️ 两条律同时成立才是这套架构: 能力(能量)向上**扩张**, 可行域(权限)向上**收窄**。
      任何一层报告自身能量 ⇒ 必须能回答"它比下一能级多给了什么"。

═══ 四、纪律 (本仓库铁律) ═══
   · 未测到的量 = -1.0 (或 τ/ω/E = 0 且 note 写明"缺信号"), **绝不用 0 冒充真值**。
   · 能量只增不减: E ≥ 0 恒成立; 出现负增量 = 势能回升 = 必须记账 (reversal_cnt), 不掩盖。
   · 总量自检: e_total == Σ energy_j (逐位, 同一浮点下 1e-12)。
   · 零回归: 本模块纯旁路 (只读 trace/日志/GPU 表), 不参与任何控制路径, 不改既有行为。

用法:
    gui-venv311/bin/python src/lerobot/manifold/energy_manifold.py --spec        # 规格书
    gui-venv311/bin/python src/lerobot/manifold/energy_manifold.py --selftest    # 物理自检
    gui-venv311/bin/python src/lerobot/manifold/energy_manifold.py --demo        # 真实 GPU 功耗采一轮
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import time
from dataclasses import dataclass, field, asdict

VERSION = "1.0.0"
UPDATED = "2026-10-07"

# ══════════════════════════════════════════════════════════════════════════════
# 能级壳层定义 (结构参数真源 —— 画布节点/控制台/话题都从这里取)
# ══════════════════════════════════════════════════════════════════════════════
LEVELS = ("L2", "L3", "L4", "L5")

LEVEL_STRUCT = {
    "L2": {
        "shell_n": 1, "name": "执行层 (基座)", "role": "base",
        "models": ["yolo_peg_live.pt (检测)", "2D→3D 几何 (K+手眼)"],
        "torque_src": "势能下降 (检测/几何误差 e∥,e⊥ 每帧降低量)",
        "omega_src": "推理帧率 (实测 Hz)",
        "feasible_r": 1.00, "feasible_src": "capability_stack.bounds ±1.0 (执行出口归一幅度)",
        "params_src": "models/yolo_peg_live.pt",
    },
    "L3": {
        "shell_n": 2, "name": "调度层 (流程/条件)", "role": "enhance",
        "models": ["smolvla_lew (SmolVLA+LEW)", "LoRA 适配器 (可选增压)"],
        "torque_src": "流形进度 e∥ 闭合率 (每步 mani_progress 增量)",
        "omega_src": "训练步率 (步/s) / 运行重规划频率",
        "feasible_r": 0.60, "feasible_src": "相位/子目标条件约束 (未标定 → 记默认值并标注)",
        "params_src": "outputs/train/smolvla_lew_* ckpt",
    },
    "L4": {
        "shell_n": 3, "name": "认知层 (自主/世界模型)", "role": "enhance",
        "models": ["INTACT 世界模型", "流形引擎 (本引擎自身)", "LoRA 适配器 (可选增压)"],
        "torque_src": "意图–动作一致性 · 限幅后动作范数 · 接触概率 (修正能力)",
        "omega_src": "推理稳态频率 (MoE 101ms → ~9.9Hz)",
        "feasible_r": 0.35, "feasible_src": "限幅后动作范数上界 u_sat (配置真值)",
        "params_src": "stable-wm-cache/checkpoints/intact_goal_*",
    },
    "L5": {
        "shell_n": 4, "name": "规划层 (大模型意图)", "role": "enhance",
        "models": ["VLM/VLA 规划器 (DeepSeek 视觉)", "五层记忆 宏观层 (SS_MACRO)"],
        "torque_src": "意图向量范数 · 计划增益 (未接入 ⇒ 0, 如实标注)",
        "omega_src": "规划周期 (0.2Hz 量级)",
        "feasible_r": 0.15, "feasible_src": "架构定义: 上层只给意图, 不直接改执行量",
        "params_src": "远端 API (无本地权重)",
    },
}

CJ_DEFINITION = "1 CJ (能力焦耳) ≜ 把归一化势能下降 1.0 的能力 (逐层同口径, 无量纲可比)"
POWER_QUERY = "power.draw,utilization.gpu,memory.used"
TOL_SUM = 1e-12          # 总量自检容差 (同浮点下加法)
TOL_MONO = 1e-12         # 壳层单调容差


# ══════════════════════════════════════════════════════════════════════════════
# 规格书 (单一真源: 节点 / 控制台 / 话题 / 报告都取这一份)
# ══════════════════════════════════════════════════════════════════════════════
def energy_spec() -> dict:
    """流形引擎能量层的**规格真源** (结构化参数 + 物理量 + 单位 + 映射 + 能级律)。"""
    return {
        "version": VERSION, "updated": UPDATED,
        "analogy": "发动机 ↔ 流形引擎 (见模块头注释对应表)",
        "structural": {                       # 结构参数 (静态, 类比发动机规格书)
            "levels": list(LEVELS),
            "shells": {L: {"n": LEVEL_STRUCT[L]["shell_n"], "name": LEVEL_STRUCT[L]["name"],
                           "role": LEVEL_STRUCT[L]["role"], "models": LEVEL_STRUCT[L]["models"],
                           "feasible_r": LEVEL_STRUCT[L]["feasible_r"],
                           "feasible_src": LEVEL_STRUCT[L]["feasible_src"]} for L in LEVELS},
            "geometry": "流形几何 (MANIFOLD_REGISTRY: su2/se3/so3/… 由 manifold_engine 定)",
            "inertia_M": "等效惯量 M = manifold_engine.MANIFOLD_M_DEFAULT (主标定参数, 已有)",
            "ratio": "比功率 = E_layer / 参数量(M params)  ⇒ 每 M 参数产出多少能力",
        },
        "physical": {                         # 物理量 (每轮实测)
            "omega_hz": "转速 — 该层更新频率 (Hz); 训练=步/秒, 运行=实测帧率",
            "tau_cj": "扭矩 — 每循环有效做功 (CJ/循环) = 归一化势能下降 / 循环数",
            "p_out_cjs": "输出功率 = τ·ω (CJ/s)",
            "p_in_w": "输入功率 = GPU 电功率 (W, nvidia-smi 实测)",
            "energy_cj": "做功能量 (增量) = ∫P dt = τ·ω·secs = τ·循环数 (CJ)",
            "standing_cj": "存量能力能量 = 能力水平 c∈[0,1] × 循环数 (CJ) —— 基座在场就有, 不靠本轮训练",
            "energy_total_cj": "层能量 = 存量 + 做功 (CJ)",
            "e_total_cj": "总能量 = Σ_layer (存量+做功)  ← 流形引擎节点可观测量 (能力总量)",
            "w_in_j": "电功 = ∫P_in dt (J)",
            "eta_cjj": "效率 = energy_total_cj / w_in_j (CJ/J)",
            "eta_mech": "机械效率 = 1 − (否决+夹紧)/总判定 (摩擦/排气损耗的工程对应)",
        },
        "units": {"CJ": CJ_DEFINITION, "J": "1 W·s (GPU 电功, 物理真实)",
                  "eta": "CJ/J —— 每焦耳电换多少归一化能力 (可跨轮比较)",
                  "warning": "CJ 与 J 不可相加: 电功是输入、能力是输出, 只能通过 η 相除比较"},
        "mapping": {                          # 能量 ↔ 模型 映射
            "L2": {"kind": "base", "energy": "基础 L2 能量 (基座自持, 永远在场)",
                   "models": LEVEL_STRUCT["L2"]["models"], "lora_host": False},
            "L3": {"kind": "enhance", "energy": "L3 增强能量 (增量, 叠在基座壳上)",
                   "models": LEVEL_STRUCT["L3"]["models"], "lora_host": True},
            "L4": {"kind": "enhance", "energy": "L4 增强能量",
                   "models": LEVEL_STRUCT["L4"]["models"], "lora_host": True},
            "L5": {"kind": "enhance", "energy": "L5 增强能量 (意图; 未接入=0 并如实标注)",
                   "models": LEVEL_STRUCT["L5"]["models"], "lora_host": False},
            "lora": {"mechanism": "涡轮增压: 适配器给宿主层注入附加扭矩 Δτ",
                     "structural": "Δτ 结构量 = τ_host × (适配器参数量/宿主参数量)",
                     "measured": "有 A/B 对照时改用实测 Δ (老倪门槛: 未证明提升不算增量)",
                     "targets_src": "tools/lora_inject.py (ZMAX_LORA_TARGETS)"},
        },
        "shell_law": {
            "energy": "E_cum(n) = Σ_{i≤n} E_i ⇒ 单调不减 (能级越高总能量越大)",
            "feasible": "R_L2 ≥ R_L3 ≥ R_L4 ≥ R_L5 ⇒ 逐层收窄 (上层只给意图, L2 收口)",
            "statement": "能力(能量)向上扩张 + 可行域(权限)向上收窄 = 本架构的双律",
        },
        "observability": {
            "topic": "zmax/ss_energy (zmax::SSEnergy) — 全局数据空间, qos=state",
            "tap": "zmax_data/ss_live/energy_<ts>.jsonl (可被守护/控制台/备份端消费)",
            "rules": ["freshness", "hz_tol", "energy_nonneg", "sum_consistent", "shell_monotonic",
                      "feasible_narrowing", "finite", "no_zero_fake"],
        },
        "discipline": ["未测 = -1.0 / τ,ω,E = 0 并写 note (不造数)",
                       "E ≥ 0; 势能回升要记 reversal_cnt 不掩盖",
                       "e_total == Σ energy_j (1e-12)",
                       "纯旁路只读, 不改控制路径 (零回归)"],
    }


# ══════════════════════════════════════════════════════════════════════════════
# 输入功率: GPU 电功率 (真瓦特) —— 引擎的"燃料表"
# ══════════════════════════════════════════════════════════════════════════════
def read_input_power_w() -> tuple[float, str]:
    """读 GPU 电功率 (W)。返回 (瓦特, 来源说明); 测不到返回 (-1.0, 原因) —— 不猜。"""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=" + POWER_QUERY, "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            return -1.0, f"nvidia-smi rc={r.returncode}"
        vals = []
        for line in r.stdout.strip().splitlines():
            p = line.split(",")[0].strip()
            try:
                v = float(p)
            except ValueError:
                continue
            if v > 0:
                vals.append(v)
        return (sum(vals) / len(vals), f"nvidia-smi power.draw ×{len(vals)}") if vals else (-1.0, "power.draw 不可读")
    except Exception as e:                                                       # noqa: BLE001
        return -1.0, f"{type(e).__name__}: {e}"


def mean_power(series: list[float]) -> float:
    """采样序列均值; 全无效 → -1.0 (不并入 0, 避免把"没测"算成"不耗电")。"""
    v = [x for x in (series or []) if x is not None and x > 0]
    return (sum(v) / len(v)) if v else -1.0


# ══════════════════════════════════════════════════════════════════════════════
# 单层能量读数
# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class LayerEnergy:
    """一层在**一轮**里的能量读数 (全部字段要么实测、要么标注为缺)。

    两个分量 (老倪口径: 「基础 L2 能量 / L3·L4·L5 增强能量」+「总能量=能力总量」):
      · 存量能力 standing_cj = 能力水平 c ∈[0,1] × 循环数  —— **基座在场就有**, 不靠本轮训练
      · 增量做功 energy_cj   = τ × 循环数 (势能下降累计)   —— 本轮**做出来的**功
      · 层能量 energy_total_cj = standing + work
    """
    layer: str = ""
    shell_n: int = 0
    tau_cj: float = 0.0          # 扭矩: 每循环有效做功 (CJ/循环)
    omega_hz: float = -1.0       # 转速: 更新频率 (Hz)
    p_out_cjs: float = -1.0      # 输出功率 = τ·ω
    energy_cj: float = 0.0       # 增量做功能量 = τ·ω·secs = τ·循环数
    level_c: float = -1.0        # 能力水平 c ∈[0,1] (真实指标归一; -1=未测)
    standing_cj: float = 0.0     # 存量能力能量 = c × 循环数
    energy_total_cj: float = 0.0  # 层能量 = standing + energy
    cycles: float = -1.0         # 循环数 (步数/帧数)
    secs: float = -1.0
    params_m: float = -1.0       # 参数量 (M) — 排量
    cylinders: int = -1          # 缸数 = 活跃子模型数
    lora_r: int = -1             # LoRA rank (未挂 = -1)
    lora_params_m: float = -1.0  # 适配器参数量 (M)
    lora_boost_cj: float = 0.0   # 增压带来的附加能量 (CJ)
    feasible_r: float = -1.0     # 可行域半径 (该层允许的执行改动上界)
    w_in_j: float = -1.0         # 该层分到的电功 (J)
    eta_cjj: float = -1.0        # 效率 E/W_in (CJ/J)
    share: float = -1.0          # 本轮能量占比 (Σ=1)
    reversal_cnt: int = 0        # 势能回升次数 (负增量记账)
    src: str = ""                # 数据来源 (日志路径/话题/清单)
    note: str = ""               # 缺项/口径说明 —— 必须能自证

    def as_dict(self) -> dict:
        return asdict(self)


# ══════════════════════════════════════════════════════════════════════════════
# 引擎能量层主体
# ══════════════════════════════════════════════════════════════════════════════
class EnergyManifold:
    """流形引擎的能量层: 逐层作功记账 → 壳层累积 → 总能量 (节点可观测量)。

    典型用法 (一轮 = 一次 pipeline 迭代 / 一段真实运行):
        em = EnergyManifold()
        em.note_power(series)                                   # 或 em.sample_power(secs=…)
        em.absorb_stage("L4", secs=…, cycles=…, loss0=…, loss1=…, params_m=…, lora=…)
        em.absorb_stage("L3", …)
        print(em.spec_sheet())                                  # 规格书 + 实测表
        payload = em.topic_payload()                            # → zmax/ss_energy
    """

    def __init__(self, levels: tuple[str, ...] = LEVELS, power_series: list[float] | None = None,
                 power_src: str = "") -> None:
        self.levels = tuple(levels)
        self.power_series: list[float] = list(power_series or [])
        self.power_src: str = power_src
        self.layers: dict[str, LayerEnergy] = {}
        self.t0 = time.time()
        self.notes: list[str] = []

    # ── 输入侧 ────────────────────────────────────────────────
    def note_power(self, series: list[float], src: str = "外部采样") -> "EnergyManifold":
        self.power_series.extend([x for x in series if x is not None])
        self.power_src = src or self.power_src
        return self

    def sample_power(self, secs: float = 1.0, hz: float = 5.0) -> "EnergyManifold":
        """真实采一轮 GPU 电功率 (用于"此刻引擎在吃什么功率")。"""
        n = max(1, int(secs * hz))
        for i in range(n):
            w, _ = read_input_power_w()
            self.power_series.append(w)
            if i < n - 1:
                time.sleep(max(0.0, 1.0 / hz))
        self.power_src = "nvidia-smi 采样"
        return self

    def p_in_w(self) -> float:
        return mean_power(self.power_series)

    # ── 吸收一个阶段 (训练一轮 / 一段运行) ─────────────────────
    def absorb_stage(self, layer: str, *, secs: float, cycles: float | None = None,
                     loss0: float | None = None, loss1: float | None = None,
                     work_cj: float | None = None, params_m: float | None = None,
                     lora: dict | None = None, feasible_r: float | None = None,
                     level_c: float | None = None,
                     src: str = "", note: str = "", reversal_cnt: int = 0,
                     loss_series: list[float] | None = None) -> LayerEnergy:
        """把一层的一轮真实数据折算成物理量。

        扭矩 τ (每循环有效做功, CJ/循环):
            优先用**逐循环序列** (loss_series / 势能序列): τ = Σ max(ΔV_c, 0) / 循环数 (负增量记 reversal)
            否则用 (loss0 − loss1)/loss0 的**相对下降** (归一化势能), 再 / 循环数
        转速 ω (Hz): cycles/secs;cycles 未知但给了名义频率则由调用方负责 (此处如实标 -1)
        输出功率 P = τ·ω ; 能量 E = P·secs = τ·cycles ; 效率 η = E / (P_in·secs)
        """
        st = LEVEL_STRUCT.get(layer, {})
        if secs is None or secs <= 0:
            note = (note + " | 时长缺失 ⇒ 物理量不可用(如实)").strip(" |")
            secs = -1.0

        # ① 归一化势能下降总量 (CJ) = 本轮有效做功
        if work_cj is None:
            if loss_series:
                v = [float(x) for x in loss_series if x is not None and math.isfinite(float(x))]
                d = [v[i] - v[i + 1] for i in range(len(v) - 1)]
                pos = sum(x for x in d if x > 0)
                negatives = [x for x in d if x < 0]
                reversal_cnt = reversal_cnt or len(negatives)
                base = max(abs(v[0]), 1e-12) if v else 1e-12
                work_cj = pos / base                      # 归一化势能下降 (相对)
                if cycles is None:
                    cycles = float(max(len(v) - 1, 0))
                src = src or f"损失/势能序列 {len(v)} 点"
                if negatives:
                    note = (note + f" | 势能回升 {len(negatives)} 次 (已记 reversal, 未掩盖)").strip(" |")
            elif loss0 is not None and loss1 is not None and abs(float(loss0)) > 0:
                # ⚠️ 分母用 |loss0|: INTACT 的 validate/loss 是**负值**(越负越好, 如 −3.5→−3.9),
                #    除以带符号的 loss0 会把"变好"算成"变差" (符号翻转) —— 实测踩过。
                rel = (float(loss0) - float(loss1)) / abs(float(loss0))
                work_cj = max(0.0, rel)
                cycles = cycles if cycles is not None else -1.0
                src = src or "起止势能 (相对下降)"
                if rel < 0:
                    reversal_cnt = 1
                    note = (note + f" | 末态势能高于首态 ({rel:+.4f}) ⇒ 本轮未作正功, 已记 reversal").strip(" |")
            else:
                work_cj = 0.0
                note = (note + " | 缺损失/势能序列 ⇒ τ=0 (如实, 不造)").strip(" |")

        # ② 转速 ω (Hz) = 循环数 / 秒
        omega = (float(cycles) / float(secs)) if (cycles and secs and secs > 0 and cycles > 0) else -1.0
        tau = (float(work_cj) / float(cycles)) if (cycles and cycles > 0) else 0.0
        p_out = (tau * omega) if (omega > 0) else -1.0
        energy = (p_out * secs) if (p_out > 0 and secs > 0) else float(work_cj or 0.0)

        # ③ LoRA 增压 (结构量; 有 A/B 实测则调用方直接改 lora_boost_cj)
        lora_r = -1
        lora_params_m = -1.0
        boost = 0.0
        lora_note = ""
        if lora:
            lora_r = int(lora.get("r", -1))
            lora_params_m = float(lora.get("params_m", -1.0))
            host_m = float(params_m) if (params_m and params_m > 0) else -1.0
            if lora_params_m > 0 and host_m > 0:
                boost = energy * (lora_params_m / host_m)          # Δτ ∝ 适配器/宿主参数占比
                lora_note = f"LoRA 增压 {boost:.4g}CJ (结构量: 适配器/宿主 = {lora_params_m:.3g}/{host_m:.3g}M)"
            elif "gain" in (lora or {}):
                boost = energy * float(lora["gain"])
                lora_note = f"LoRA 增压 {boost:.4g}CJ (实测 Δ, A/B 对照)"
            else:
                lora_note = "LoRA 已挂但参数量/实测Δ未知 ⇒ 增压 0 (如实)"
            if (lora or {}).get("targets"):
                lora_note += f" · 目标 {lora['targets']}"

        # ④ 效率: 该层分到的电功 (按能量占比分配; 单层轮次则整机功率都算它)
        p_in = self.p_in_w()
        w_in = (p_in * secs) if (p_in > 0 and secs > 0) else -1.0
        eta = (energy / w_in) if (w_in > 0 and energy > 0) else -1.0

        # ④b 存量能力能量 (基座在场就有) = 能力水平 c × 循环数
        c = float(level_c) if level_c is not None else -1.0
        if c >= 0:
            c = min(1.0, max(0.0, c))
        n_cyc = float(cycles) if (cycles and cycles > 0) else 0.0
        standing = (c * n_cyc) if (c > 0 and n_cyc > 0) else 0.0
        e_total_layer = standing + float(energy)

        le = LayerEnergy(
            layer=layer, shell_n=int(st.get("shell_n", 0)), tau_cj=round(float(tau), 9),
            omega_hz=round(omega, 6), p_out_cjs=round(p_out, 9) if p_out > 0 else -1.0,
            energy_cj=round(float(energy), 9), level_c=round(c, 6),
            standing_cj=round(standing, 9), energy_total_cj=round(e_total_layer, 9),
            cycles=cycles if cycles is not None else -1.0,
            secs=round(secs, 3), params_m=params_m if params_m is not None else -1.0,
            cylinders=len(st.get("models") or []) or -1, lora_r=lora_r, lora_params_m=lora_params_m,
            lora_boost_cj=round(boost, 9), feasible_r=feasible_r if feasible_r is not None else st.get("feasible_r", -1.0),
            w_in_j=round(w_in, 6), eta_cjj=round(eta, 9), reversal_cnt=int(reversal_cnt),
            src=src, note=" · ".join(x for x in (
                note, (f"能力水平 c={c:.4f} × {n_cyc:.0f} 循环 ⇒ 存量 {standing:.4f}CJ" if standing > 0
                       else "无能力水平输入 ⇒ 存量 0 (如实)"), lora_note) if x))
        # 同一层再吸收 → 累加 (多阶段同层)
        if layer in self.layers:
            prev = self.layers[layer]
            le.energy_cj += prev.energy_cj
            le.standing_cj += prev.standing_cj
            le.energy_total_cj = le.energy_cj + le.standing_cj
            le.lora_boost_cj += prev.lora_boost_cj
            le.reversal_cnt += prev.reversal_cnt
            le.level_c = max(le.level_c, prev.level_c)
            le.secs += prev.secs if prev.secs > 0 else 0.0
            le.cycles = (le.cycles if le.cycles > 0 else 0) + (prev.cycles if prev.cycles > 0 else 0) or -1.0
            le.w_in_j = (le.w_in_j if le.w_in_j > 0 else 0) + (prev.w_in_j if prev.w_in_j > 0 else 0) or -1.0
            le.eta_cjj = round(le.energy_total_cj / le.w_in_j, 9) if le.w_in_j > 0 else -1.0
            le.note = (le.note + " | " + prev.note).strip(" |")
        self.layers[layer] = le
        return le

    # ── 运行态吸收: 直接从引擎 trace 读 (画布节点用) ────────────
    def absorb_trace(self, trace: dict, fps: float = -1.0, tcp_pose: list | None = None,
                     src: str = "引擎 trace") -> "EnergyManifold":
        """从**真跑 trace** 折算各层能量 (推理/闭环态, 而非训练态)。

        trace 列 (与引擎同源, 缺列即该层 0 并写明): mani_progress / mani_dperp / mani_rem /
        u_sat / contact_p / mani_eta / obs(43) ; 另有 u_exec_vec。
        τ 取"每帧势能下降量", ω 取实测帧率 —— 与训练态同一套公式 (P = τ·ω)。
        """
        def _series(k):
            v = trace.get(k)
            return [float(x) for x in v if x is not None and math.isfinite(float(x))] if v else []

        n = len(_series("mani_progress")) or len(_series("u_sat")) or 0
        if n == 0:
            self.notes.append("trace 无可用列 ⇒ 各层 0 (如实)")
            return self
        secs = (n / fps) if (fps and fps > 0) else -1.0

        # L2: 几何误差 (obs43 → peg−hole) 每帧下降 ⇒ 执行层作功
        prog = _series("mani_progress")
        dperp = _series("mani_dperp")
        if prog:
            self.absorb_stage("L2", secs=secs if secs > 0 else n, cycles=n,
                              loss_series=[1.0 - p for p in prog],  # 势能 = 1 − 进度
                              src=f"{src} · mani_progress", note="L2 扭矩←进度闭合 (势能=1−e∥)")
        # L3: 法向偏离收敛速率 ⇒ 调度层把状态压回通道
        if dperp:
            self.absorb_stage("L3", secs=secs if secs > 0 else n, cycles=n,
                              loss_series=dperp, src=f"{src} · mani_dperp", note="L3 扭矩←法向偏离 e⊥ 收敛")
        # L4: 限幅后动作范数 × 接触概率 ⇒ 认知层修正能力
        us, cp = _series("u_sat"), (_series("contact_p") or [0.5])
        if us:
            eff = [abs(u) * (cp[i] if i < len(cp) else cp[-1]) for i, u in enumerate(us)]
            self.absorb_stage("L4", secs=secs if secs > 0 else n, cycles=n,
                              loss_series=[max(eff) - e for e in eff],
                              src=f"{src} · u_sat×contact_p", note="L4 扭矩←修正能力 (限幅范数×接触概率)")
        # L5: 意图向量 (未接入 → 0 并标注)
        if "intent" in trace and trace["intent"]:
            iv = [float(x) for x in trace["intent"]][:3]
            self.absorb_stage("L5", secs=secs if secs > 0 else n, cycles=n, loss_series=iv,
                              src=f"{src} · intent", note="L5 扭矩←意图向量")
        else:
            self.layers.setdefault("L5", LayerEnergy(
                layer="L5", shell_n=4, feasible_r=LEVEL_STRUCT["L5"]["feasible_r"],
                src=src, note="L5 未接入 (trace 无 intent 列) ⇒ 能量 0 — 如实标注, 不伪装在工作"))
        return self

    # ── 壳层 / 总量 ───────────────────────────────────────────
    def total(self) -> dict:
        e_work = sum(l.energy_cj for l in self.layers.values())
        e_stand = sum(l.standing_cj for l in self.layers.values())
        e_total = e_stand + e_work                      # 总能量 = 存量能力 + 本轮做功
        e_boost = sum(l.lora_boost_cj for l in self.layers.values())
        w_in = sum(l.w_in_j for l in self.layers.values() if l.w_in_j > 0) or -1.0
        n = len(self.layers)
        for l in self.layers.values():
            l.share = round(l.energy_total_cj / e_total, 6) if e_total > 0 else -1.0
        return {
            "e_total_cj": round(e_total, 9),            # ← 节点可观测量 (能力总量)
            "e_worksum_cj": round(e_work, 9),           # 本轮做功合计 (增量)
            "e_standsum_cj": round(e_stand, 9),         # 存量能力合计 (基座+各层既有水平)
            "e_base_cj": round(self.layers["L2"].energy_total_cj, 9) if "L2" in self.layers else 0.0,
            "e_boost_cj": round(e_boost, 9),
            "n_levels_active": sum(1 for L in LEVELS if L in self.layers and self.layers[L].energy_total_cj > 0),
            "p_in_w": round(self.p_in_w(), 3),
            "w_in_j": round(w_in, 6),
            "eta_total_cjj": round(e_total / w_in, 9) if w_in > 0 else -1.0,
            "sum_ok": abs(e_total - sum(l.energy_total_cj for l in self.layers.values())) <= TOL_SUM,
            "layers": {k: v.as_dict() for k, v in self.layers.items()},
            "n_layers": n,
        }

    def shells(self) -> list[dict]:
        """能级壳层: 累积能量单调不减 + 可行域逐层收窄 (双律)。"""
        out, cum = [], 0.0
        for L in LEVELS:
            le = self.layers.get(L)
            e = le.energy_total_cj if le else 0.0
            cum += e
            out.append({
                "shell_n": LEVEL_STRUCT[L]["shell_n"], "layer": L,
                "e_layer_cj": round(e, 9),
                "e_work_cj": round(le.energy_cj, 9) if le else 0.0,
                "e_standing_cj": round(le.standing_cj, 9) if le else 0.0,
                "level_c": (le.level_c if le else -1.0),
                "e_cum_cj": round(cum, 9),
                "feasible_r": LEVEL_STRUCT[L]["feasible_r"],
                "present": le is not None,
                "note": (le.note if le else "未接入本轮"),
            })
        mono = all(out[i + 1]["e_cum_cj"] + TOL_MONO >= out[i]["e_cum_cj"] for i in range(len(out) - 1))
        narrow = all(out[i + 1]["feasible_r"] <= out[i]["feasible_r"] + 1e-12 for i in range(len(out) - 1))
        for o in out:
            o["shell_monotonic_ok"] = mono
            o["feasible_narrowing_ok"] = narrow
        return out

    def eta_mech(self, vetoed: int = 0, clipped: int = 0, total_judgements: int = 0) -> float:
        """机械效率 = 1 − (否决+夹紧)/总判定 (CapabilityStack 真计数; 无计数 → -1)。"""
        if total_judgements <= 0:
            return -1.0
        loss = (int(vetoed) + int(clipped)) / float(total_judgements)
        return round(max(0.0, 1.0 - loss), 6)

    # ── 观测: 话题载荷 / 规格书 ────────────────────────────────
    def topic_payload(self, node: str = "流形引擎", state: str = "train", **extra) -> dict:
        """全局数据空间 zmax/ss_energy 的载荷 (字段与 dds/ss_types.py::SSEnergy 对齐)。"""
        t = self.total()
        sh = self.shells()
        p = {
            "ts": round(self.t0 if not self.t0 else time.time(), 3),
            "node": node, "state": state, "version": VERSION,
            "layers": list(self.layers.keys()),
            "shells": [{"layer": s["layer"], "shell_n": s["shell_n"], "e_layer_cj": s["e_layer_cj"],
                        "e_cum_cj": s["e_cum_cj"], "feasible_r": s["feasible_r"],
                        "e_work_cj": s.get("e_work_cj", 0.0), "e_standing_cj": s.get("e_standing_cj", 0.0),
                        "level_c": s.get("level_c", -1.0),
                        "tau_cj": (self.layers[s["layer"]].tau_cj if s["present"] else 0.0),
                        "omega_hz": (self.layers[s["layer"]].omega_hz if s["present"] else -1.0),
                        "p_out_cjs": (self.layers[s["layer"]].p_out_cjs if s["present"] else -1.0),
                        "params_m": (self.layers[s["layer"]].params_m if s["present"] else -1.0),
                        "lora_r": (self.layers[s["layer"]].lora_r if s["present"] else -1),
                        "lora_boost_cj": (self.layers[s["layer"]].lora_boost_cj if s["present"] else 0.0),
                        "eta_cjj": (self.layers[s["layer"]].eta_cjj if s["present"] else -1.0),
                        "share": (self.layers[s["layer"]].share if s["present"] else -1.0),
                        "note": s["note"]} for s in sh],
            "e_base_cj": t["e_base_cj"], "e_boost_cj": t["e_boost_cj"], "e_total_cj": t["e_total_cj"],
            "e_worksum_cj": t["e_worksum_cj"], "e_standsum_cj": t["e_standsum_cj"],
            "n_levels_active": t["n_levels_active"], "p_in_w": t["p_in_w"], "w_in_j": t["w_in_j"],
            "eta_total_cjj": t["eta_total_cjj"],
            "shell_monotonic_ok": bool(sh and sh[0]["shell_monotonic_ok"]),
            "feasible_narrowing_ok": bool(sh and sh[0]["feasible_narrowing_ok"]),
            "sum_ok": t["sum_ok"], "criterion": CJ_DEFINITION,
            "source": self.power_src or "未知", "unit": "CJ",
        }
        p.update(extra)
        return p

    def spec_sheet(self) -> str:
        """规格书 + 实测表 (控制台/日志用; 人可读)。"""
        t = self.total()
        L = ["┌─ 流形引擎 · 能量层规格书 " + VERSION + " ─────────────────────────────",
             f"│ 单位: {CJ_DEFINITION}",
             f"│ 输入功率 P_in = {t['p_in_w']} W ({self.power_src or '未采'}) · 电功 {t['w_in_j']} J",
             "├─ 能级壳层 (能量向上扩张 / 可行域向上收窄) ───────────────────",
             "│ 壳 层   存量CJ(基座)  增量CJ(做功)  层能量CJ     累积CJ     τ(CJ/循环)  ω(Hz)  可行域  占比   主模型"]
        for s in self.shells():
            le = self.layers.get(s["layer"])
            mdl = (LEVEL_STRUCT[s["layer"]]["models"] or ["—"])[0][:20]
            tau = f"{le.tau_cj:>10.6f}" if le else "         —"
            om = f"{le.omega_hz:>6.3f}" if le else "     —"
            sh = f"{le.share:>6.3f}" if (le and le.share >= 0) else "     —"
            L.append(f"│ {s['shell_n']} {s['layer']:<4} {s['e_standing_cj']:>11.4f}  {s['e_work_cj']:>11.4f}  "
                     f"{s['e_layer_cj']:>10.4f}  {s['e_cum_cj']:>10.4f}  {tau}  {om}  {s['feasible_r']:>5.2f}  "
                     f"{sh}  {mdl}")
        L += ["├─ 总量 (节点可观测量) ──────────────────────────────────────",
              f"│ 总能量 E_total = {t['e_total_cj']:.6f} CJ  = 存量 {t['e_standsum_cj']:.6f} + 做功 {t['e_worksum_cj']:.6f}",
              f"│   其中基础 L2 能量 {t['e_base_cj']:.6f} CJ · LoRA 增压 {t['e_boost_cj']:.6f} CJ"
              f" · 活跃能级 {t['n_levels_active']}/{len(LEVELS)}",
              f"│ 效率 η = {t['eta_total_cjj']} CJ/J (电功 {t['w_in_j']} J)",
              f"│ 自检: Σ分层==总量 {t['sum_ok']} · 壳层单调 {self.shells()[0]['shell_monotonic_ok']}"
              f" · 可行域收窄 {self.shells()[0]['feasible_narrowing_ok']}",
              "└────────────────────────────────────────────────────────────"]
        if self.notes:
            L.append("  注: " + " · ".join(self.notes))
        return "\n".join(L)


# ══════════════════════════════════════════════════════════════════════════════
# 物理自检 (报数值, 不报"通过")
# ══════════════════════════════════════════════════════════════════════════════
def self_test(verbose: bool = True) -> tuple[bool, list[dict]]:
    """能量层物理自检: 同式性(P=τω)、可加性、非负、单调、收窄、单位一致性。"""
    checks: list[dict] = []

    def add(name, ok, val, note=""):
        checks.append({"name": name, "ok": bool(ok), "value": val, "note": note})

    # ① P = τ·ω 同式性: 用构造序列反推
    em = EnergyManifold(power_series=[100.0] * 4)
    em.absorb_stage("L2", secs=10.0, cycles=100, loss_series=[1.0 - 0.01 * i for i in range(101)], src="selftest")
    le = em.layers["L2"]
    add("P == τ·ω", abs(le.p_out_cjs - le.tau_cj * le.omega_hz) < 1e-9,
        f"P={le.p_out_cjs:.9f}, τ·ω={le.tau_cj * le.omega_hz:.9f}")
    # ② E = τ·cycles (累计功 = 每循环功 × 循环数)
    add("E == τ·cycles", abs(le.energy_cj - le.tau_cj * le.cycles) < 1e-6,
        f"E={le.energy_cj:.9f}, τ·N={le.tau_cj * le.cycles:.9f}")
    # ③ ω = cycles/secs
    add("ω == cycles/secs", abs(le.omega_hz - 10.0) < 1e-9, f"ω={le.omega_hz}")
    # ④ 可加性: 总量 == 分层之和 (1e-12)
    em.absorb_stage("L3", secs=5.0, cycles=50, loss_series=[1.0, 0.9, 0.8],
                    level_c=0.4, src="selftest")
    t = em.total()
    s = sum(l["energy_total_cj"] for l in t["layers"].values())
    add("E_total == Σ E_layer(存量+做功)", abs(t["e_total_cj"] - s) <= TOL_SUM, f"Δ={abs(t['e_total_cj'] - s):.2e}")
    # ④b 存量/做功分解 (基础 L2 能量 = 基座在场就有)
    em_st = EnergyManifold(power_series=[100.0])
    em_st.absorb_stage("L2", secs=2.0, cycles=10, loss_series=[0.005] * 5, level_c=0.995, src="st")
    l2 = em_st.layers["L2"]
    add("存量=能力水平×循环 (基础L2能量)", abs(l2.standing_cj - 0.995 * 10) < 1e-9 and l2.energy_cj == 0.0,
        f"standing={l2.standing_cj} (c={l2.level_c}, 无提升则做功=0) ⇒ L2 能量仍非零 = 基座自持")
    # ⑤ 非负: 任何一轮 E ≥ 0
    add("E ≥ 0 (全部)", all(l["energy_cj"] >= 0 for l in t["layers"].values()),
        str([l["energy_cj"] for l in t["layers"].values()]))
    # ⑥ 壳层单调 (能量向上扩张)
    sh = em.shells()
    add("壳层 E_cum 单调不减", bool(sh[0]["shell_monotonic_ok"]),
        " → ".join(f"{x['e_cum_cj']:.4f}" for x in sh))
    # ⑦ 可行域逐层收窄
    add("可行域 R 逐层收窄", bool(sh[0]["feasible_narrowing_ok"]),
        " → ".join(f"{x['feasible_r']:.2f}" for x in sh))
    # ⑧ 势能回升被记账 (不掩盖)
    em2 = EnergyManifold(power_series=[100.0])
    em2.absorb_stage("L4", secs=1.0, cycles=4, loss_series=[1.0, 0.8, 0.9, 0.85], src="selftest")
    add("势能回升记账 reversal_cnt>0", em2.layers["L4"].reversal_cnt > 0,
        f"reversal={em2.layers['L4'].reversal_cnt}")
    # ⑨ 缺信号诚实: 不造数
    em3 = EnergyManifold(power_series=[-1.0])
    em3.absorb_stage("L5", secs=1.0, cycles=1, src="selftest")
    add("缺信号 ⇒ τ=0 且 note 写明", em3.layers["L5"].tau_cj == 0.0 and "不造" in em3.layers["L5"].note,
        em3.layers["L5"].note[:40])
    # ⑩ 效率: 无功率 → -1 (不除以 0, 也不假装)
    add("无功率实测 ⇒ η=-1", em3.layers["L5"].eta_cjj == -1.0, str(em3.layers["L5"].eta_cjj))
    # ⑪ 单位一致性: CJ 不进 J (两字段永不相同语义)
    add("CJ/J 分离 (输入/输出分字段)",
        bool(t["layers"]) and all(("w_in_j" in l and "energy_cj" in l) for l in t["layers"].values()),
        "每层同时带 energy_cj(输出) 与 w_in_j(输入) ✓")
    # ⑫ 同层累加: 两段吸收合成一段
    em4 = EnergyManifold(power_series=[50.0])
    e1 = em4.absorb_stage("L3", secs=2.0, cycles=10, loss_series=[1.0, 0.5], src="s").energy_cj
    e2 = em4.absorb_stage("L3", secs=2.0, cycles=10, loss_series=[1.0, 0.5], src="s").energy_cj
    add("同层两段累加 == e1+e2", abs(e2 - (e1 + e1)) < 1e-9, f"{e2:.6f} vs {2 * e1:.6f}")

    ok_all = all(c["ok"] for c in checks)
    if verbose:
        print(f"═══ 流形引擎能量层自检 v{VERSION} ═══")
        for c in checks:
            print(f"  {'✅' if c['ok'] else '❌'} {c['name']:<26} {c['value']}")
        print(f"  ⇒ {'全部通过' if ok_all else '存在失败项'} ({sum(c['ok'] for c in checks)}/{len(checks)})")
    return ok_all, checks


# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="流形引擎 · 能量层")
    ap.add_argument("--spec", action="store_true", help="打印规格真源 JSON")
    ap.add_argument("--selftest", action="store_true", help="物理自检")
    ap.add_argument("--spec-sheet", action="store_true", help="打印人可读规格书")
    ap.add_argument("--demo", type=float, default=0.0, help="采 N 秒 GPU 功耗做演示轮 (N>0)")
    a = ap.parse_args()
    if a.spec:
        print(json.dumps(energy_spec(), ensure_ascii=False, indent=1))
    elif a.selftest:
        ok, _ = self_test()
        raise SystemExit(0 if ok else 1)
    elif a.demo > 0:
        em = EnergyManifold()
        em.sample_power(secs=a.demo)
        w, src = read_input_power_w()
        print(f"GPU 输入功率 {w:.1f} W ({src})")
        em.absorb_stage("L2", secs=a.demo, cycles=int(a.demo * 30),
                        loss_series=[1.0 - 0.005 * i for i in range(int(a.demo * 30))],
                        src="demo (合成序列仅作管道演示)")
        print(em.spec_sheet())
    else:
        print(json.dumps(energy_spec()["observability"], ensure_ascii=False, indent=1))
        print("\n提示: --selftest / --spec / --spec-sheet / --demo N")
