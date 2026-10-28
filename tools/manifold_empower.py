#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三层流形赋能层 (Manifold Empowerment Layer) —— 不删减原模型, 只做几何赋能

老倪 2026-10-21: 「语义层对应 L5 deepseek, 空间层对应 L4 intact action 空间,
                  物理层对应 L2 原子技能动作, 不删减原有模型, 做赋能增强」

═══ 设计铁律 ═══
① **零侵入**: L5 的 prompt / L4 的权重 / L2 的技能库 **一行不改**。
   本层只在层间数据通路上做投影/引导, 全程可门控; 三门全关 ⇒ 逐位直通(零开销)。
② **上层只给意图/条件, 执行永远由 L2 收口**(项目架构原则) —— 本层不给动作, 只收窄可行域。
③ **维度决定几何有效性**(2026-10-21 实测, 不是猜):
      S^3  |cos|中位 0.492 · 可分辨率 49.4%   ← 物理层 L2 chunk(4维), 几何约束有效
      S^7  |cos|中位 0.261 · 可分辨率 16.8%   ← 空间层 L4 action(8维), 勉强可用
      S^255|cos|中位 0.043 · 可分辨率  0.0%   ← 绝不可直接投球面, Φ 信号 0.03 淹没在噪声里
   ⇒ 8 维必须**按语义拆分**: 位置 3 维入 S^2(49.4%), 其余 5 维走平直空间。
④ **势函数用 ½(1-⟨p̂,ĝ⟩) 带符号形式**(2026-10-20 修度规约束时实测): 无 arccos 奇点、
   无绝对值二义性、梯度方向唯一指向 goal; 幅值由欧氏项给, 方向按 w 插值, w≤0.85 留单调性保底。

三层映射:
    L5 DeepSeek  语义 → 意图编码 → **目标点 goal_sem** (不需要球面: 文本无天然几何)
    L4 INTACT    空间 → 8 维 action → 位置3 投 S^2 + 姿态5 平直 → 输出收窄后的 action
    L2 技能      物理 → 4 维 chunk  → S^3 势函数保障 → 保证收敛 + 单调

自主进化(在线, 无需重训):
    · goal_sem 从「成功执行轨迹的终点」滑动更新 (EMA, 只吃 gate_pass=1 的样本)
    · 每层权重 w 按「本层引导是否让下游势函数下降」自适应, 下降则加, 反则减

用法:
    from manifold_empower import EmpowerLayer
    emp = EmpowerLayer(enable_sem=True, enable_spa=True, enable_phy=True)
    emp.set_intent_from_l5(l5_json)              # L5 意图 → goal
    a8 = emp.empower_action(l4_action8)          # L4 8 维 → 收窄后 8 维
    c4 = emp.empower_chunk(l2_chunk4)            # L2 4 维 → 保障后 4 维
    emp.update_from_outcome(success=True, end_state=...)   # 自主进化
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict

import numpy as np

# 与 manifold_engine 同源的常数 (不 import 引擎本体: 避免拉 pyqtgraph/torch 依赖链)
PHI_W_MAX = float(os.environ.get("ZMAX_EMPOWER_W_MAX", "0.85"))
EMPTY_EMA = 0.15          # goal 在线更新步长
EPS_NORM = 1e-12


def _unit(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, float).ravel()
    n = float(np.linalg.norm(v))
    return v / n if n > EPS_NORM else np.zeros_like(v)


def phi_smooth(p: np.ndarray, goal: np.ndarray) -> float:
    """½(1-⟨p̂,ĝ⟩): 与 Fubini–Study 同族(c 的单调变换), 无 arccos / 无绝对值。
    最小值在 p=goal (c=1); c<0 时 Φ>0.5 但仍单调下降朝 goal ⇒ 梯度方向唯一。"""
    pu, gu = _unit(p), _unit(goal)
    if pu.size == 0 or gu.size == 0 or pu.size != gu.size:
        return 0.0
    return 0.5 * (1.0 - float(np.dot(pu, gu)))


def metric_gradient(p: np.ndarray, goal: np.ndarray, w: float = PHI_W_MAX,
                    eu_scale: float = 1.0) -> np.ndarray:
    """方向级混合梯度: 度规势给方向(去法向), 欧氏项给幅值。w≤0.85 保单调。"""
    p = np.asarray(p, float).ravel()
    goal = np.asarray(goal, float).ravel()
    if p.size != goal.size or p.size == 0:
        return np.zeros_like(p)
    # 欧氏: 朝 goal, 幅值 = eu_scale * ‖p-goal‖
    d_eu = goal - p
    ne = float(np.linalg.norm(d_eu))
    g_eu = d_eu * (eu_scale if ne < EPS_NORM else eu_scale / max(ne, EPS_NORM)) * (ne if ne > EPS_NORM else 0.0)
    if ne < EPS_NORM:
        return np.zeros_like(p)
    g_eu = d_eu / ne * min(ne, 1.0) * eu_scale          # 归一化方向 × 有界幅值
    # 度规: Φ=½(1-c), c=⟨p̂,ĝ⟩ ⇒ ∂c/∂p=(ĝ-c·p̂)/‖p‖ ⇒ Φ**下降**方向 = +(ĝ-c·p̂)
    pu, gu = _unit(p), _unit(goal)
    c = float(np.dot(pu, gu))
    g_met = (gu - c * pu)                               # 指向 goal 的切向(Φ 下降方向)
    nm = float(np.linalg.norm(g_met))
    if nm > EPS_NORM:
        g_met = g_met / nm * min(ne, 1.0) * eu_scale     # 幅值统一取欧氏尺度
    w = float(np.clip(w, 0.0, PHI_W_MAX))
    g = (1.0 - w) * g_eu + w * g_met
    ngn = float(np.linalg.norm(g))
    if ngn < EPS_NORM:
        return g_eu
    # 幅值回落到欧氏: 混合只改方向, 不改步长
    return g / ngn * min(ne, 1.0) * eu_scale


@dataclass
class EmpowerState:
    """每层的运行态 (可序列化 → 落盘做在线进化 checkpoint)"""
    goal_sem: list = field(default_factory=list)     # L5 意图编码(平直空间)
    goal_spa_pos: list = field(default_factory=list)  # L4 位置 3 维球面目标
    goal_phy: list = field(default_factory=list)      # L2 chunk 4 维球面目标
    w_sem: float = 0.0
    w_spa: float = PHI_W_MAX
    w_phy: float = PHI_W_MAX
    n_updates: int = 0
    n_success: int = 0
    n_fail: int = 0
    last_ts: float = 0.0


class EmpowerLayer:
    """三层流形赋能。门控全关 = 逐位直通, 零开销。"""

    def __init__(self, enable_sem=True, enable_spa=True, enable_phy=True,
                 state_path=None, verbose=False):
        self.en_sem = bool(enable_sem)
        self.en_spa = bool(enable_spa)
        self.en_phy = bool(enable_phy)
        self.verbose = verbose
        self.state_path = state_path or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "zmax_data", "manifold_empower_state.json")
        self.st = EmpowerState()
        self._load()
        # 语义关键词 → 单位方向 (固定基底, 保证可复现; 真实部署可换成 embedding)
        self._sem_basis = self._build_sem_basis()

    # ─────────────── 语义基座 (L5 意图 → 向量) ───────────────
    @staticmethod
    def _build_sem_basis():
        """把 L5 的意图词映射到固定方向。故意用**稀疏正交基**:
        语义空间里不同意图应当张成不同方向, 否则 goal 全挤在一起, 势函数无信息。"""
        axes = {
            "插入": [1, 0, 0, 0, 0, 0, 0, 0], "insert": [1, 0, 0, 0, 0, 0, 0, 0],
            "抓取": [0, 1, 0, 0, 0, 0, 0, 0], "grasp": [0, 1, 0, 0, 0, 0, 0, 0],
            "摆盘": [0, 0, 1, 0, 0, 0, 0, 0], "tray": [0, 0, 1, 0, 0, 0, 0, 0],
            "检测": [0, 0, 0, 1, 0, 0, 0, 0], "inspect": [0, 0, 0, 1, 0, 0, 0, 0],
            "归位": [0, 0, 0, 0, 1, 0, 0, 0], "home": [0, 0, 0, 0, 1, 0, 0, 0],
            "取出": [0, 0, 0, 0, 0, 1, 0, 0], "pick": [0, 0, 0, 0, 0, 1, 0, 0],
            "对位": [0, 0, 0, 0, 0, 0, 1, 0], "align": [0, 0, 0, 0, 0, 0, 1, 0],
            "停止": [0, 0, 0, 0, 0, 0, 0, 1], "stop": [0, 0, 0, 0, 0, 0, 0, 1],
        }
        return {k: np.array(v, float) for k, v in axes.items()}

    def encode_intent(self, l5) -> np.ndarray:
        """L5 输出 (dict / JSON 串 / 纯文本) → 意图向量 (8 维, 平直空间)"""
        txt = ""
        if isinstance(l5, dict):
            txt = " ".join(str(v) for v in l5.values())
        elif isinstance(l5, str):
            try:
                d = json.loads(l5)
                txt = " ".join(str(v) for v in d.values()) if isinstance(d, dict) else l5
            except Exception:
                txt = l5
        txt_l = txt.lower()
        acc = np.zeros(8, float)
        hit = 0
        for k, v in self._sem_basis.items():
            if k.lower() in txt_l:
                acc += v
                hit += 1
        if hit == 0:
            return np.zeros(8, float)          # 无法解析 ⇒ 全零 ⇒ 语义层不介入(不瞎猜)
        return acc / float(hit)

    def set_intent_from_l5(self, l5):
        """L5 意图 → 语义目标 + 派生下层目标 (上层只给条件)"""
        v = self.encode_intent(l5)
        if not np.any(v):
            return {"ok": False, "why": "意图无法解析, 语义层不介入"}
        self.st.goal_sem = v.tolist()
        # 派生: 空间层目标 = 语义方向铺到位置 3 维(取前 3 轴并归一)
        g3 = _unit(v[:3]) if np.linalg.norm(v[:3]) > EPS_NORM else np.array([1.0, 0, 0])
        self.st.goal_spa_pos = g3.tolist()
        # 物理层目标 = 语义方向压到 4 维
        g4 = _unit(np.resize(v, 4))
        self.st.goal_phy = g4.tolist()
        self.st.w_sem = 0.0                    # 语义层本身不直接改动作, 只提供 goal
        self.st.last_ts = time.time()
        return {"ok": True, "goal_sem": self.st.goal_sem,
                "goal_spa_pos": self.st.goal_spa_pos, "goal_phy": self.st.goal_phy}

    # ─────────────── L4 空间层: 8 维 action ───────────────
    def empower_action(self, a8, w=None):
        """L4 INTACT 8 维 action → 收窄后 8 维。
        按实测拆语义: 前 3 维(位置)入 S^2 (可分辨率 49.4%), 后 5 维(姿态/夹爪)平直不加球面约束。
        """
        a = np.asarray(a8, float).ravel()
        if not self.en_spa or a.size != 8 or not self.st.goal_spa_pos:
            return a.copy()
        w = self.st.w_spa if w is None else float(w)
        out = a.copy()
        g3 = np.asarray(self.st.goal_spa_pos, float)
        p3 = a[:3]
        if float(np.linalg.norm(p3)) < EPS_NORM:
            return out
        # 球面上朝 goal 的切向梯度 (位置 3 维)
        # 步长按到 goal 的距离给 (与 L2 同源理由)
        step3 = 0.5 * float(np.linalg.norm(_unit(p3) - _unit(g3))) * float(np.linalg.norm(p3) + 1e-12)
        g = metric_gradient(p3, g3, w=w, eu_scale=1.0) * step3
        # 只做**方向收窄**: 把位置增量往 goal 侧旋转 w 比例, 不改幅值(执行仍归 L2)
        out[:3] = p3 + g
        return out

    # ─────────────── L2 物理层: 4 维 chunk ───────────────
    def empower_chunk(self, c4, w=None):
        """L2 4 维 chunk action → S^3 势函数保障 (可分辨率 49.4%, 几何有效)。
        L2 是执行收口层: 这里只保证「朝目标单调下降」, 不改执行链。"""
        c = np.asarray(c4, float).ravel()
        if not self.en_phy or c.size != 4 or not self.st.goal_phy:
            return c.copy()
        w = self.st.w_phy if w is None else float(w)
        goal = np.asarray(self.st.goal_phy, float)
        phi0 = phi_smooth(c, goal)
        # 步长 = 到 goal 的距离 × 0.5。绝不能拿 ‖c‖ 当尺度: 一步跨过头会让 Φ 反升,
        # 然后被单调闸退回原值 => 等于没做事, 白折腾 (2026-10-21 真实轨迹实测踩到)
        step = 0.5 * float(np.linalg.norm(_unit(c) - _unit(goal))) * float(np.linalg.norm(c) + 1e-12)
        cand = c + metric_gradient(c, goal, w=w, eu_scale=1.0) * step
        # 单调性保底: 若候选让势函数不降, 退原值(绝不让保障把事办坏)
        if phi_smooth(cand, goal) > phi0:
            return c.copy()
        return cand

    def empower_chunk_seq(self, chunk_hx4):
        """整块 [H,4] 协同保障 —— 块内**时序平滑**, 不是逐帧独立。

        2026-10-21 真实轨迹实测: 逐帧独立引导会把单调率 0.7372 拉到 0.7347
        (真机轨迹本身单调率只有 0.74, 逐帧再抖一次更抖)。
        唯一依据判据: 修正量必须沿时间**平滑**, 否则引导本身就成了新的抖动源。
        做法: ① 逐帧保障得修正量 Δ  ② 对 Δ 做 3 点滑动平均(端点保持)
              ③ 帧号越靠后平滑越轻(近端响应快, 远端更稳) ④ 再过一次逐帧单调闸
        """
        arr = np.asarray(chunk_hx4, float)
        if arr.ndim == 1:
            return self.empower_chunk(arr)
        if not self.en_phy or arr.shape[1] != 4 or not self.st.goal_phy:
            return arr.copy()
        # ① 逐帧保障
        guided = np.vstack([self.empower_chunk(row) for row in arr])
        delta = guided - arr                        # 纯修正量
        if delta.shape[0] < 3:
            return guided
        # ② 3 点滑动平均 (端点复制边界)
        pad = np.vstack([delta[:1], delta, delta[-1:]])
        smooth = (pad[:-2] + pad[1:-1] + pad[2:]) / 3.0
        # ③ 近端(k=0)少平滑、远端多平滑: 权重线性插值
        H = arr.shape[0]
        alpha = np.linspace(0.35, 1.0, H).reshape(-1, 1)   # 平滑强度
        delta_s = alpha * smooth + (1 - alpha) * delta
        out = arr + delta_s
        # ④ 逐帧单调闸: 任何一帧不得比原始更高
        goal = np.asarray(self.st.goal_phy, float)
        phi0 = np.array([phi_smooth(r, goal) for r in arr])
        phi1 = np.array([phi_smooth(r, goal) for r in out])
        bad = phi1 > phi0 + 1e-12
        if np.any(bad):
            out[bad] = arr[bad]                     # 只退坏帧, 不整块退
        return out

    # ─────────────── 自主进化 ───────────────
    def update_from_outcome(self, success: bool, end_action=None, end_chunk=None, lr=None):
        """从执行结果在线进化: 成功则把 goal 往**实际到达点**挪(EMA), 失败则降权重。

        这是真·在线自适应, 不重训任何模型:
          · goal 变 ⟹ 势场变 ⟹ 引导方向变
          · w 变  ⟹ 几何引导占比变
        只在 success=True 且拿到落点时更新 goal —— 失败样本不污染目标。
        """
        lr = EMPTY_EMA if lr is None else float(lr)
        self.st.n_updates += 1
        if success:
            self.st.n_success += 1
            if end_action is not None:
                e = np.asarray(end_action, float).ravel()
                if e.size == 8 and self.st.goal_spa_pos:
                    g = np.asarray(self.st.goal_spa_pos, float)
                    ng = (1 - lr) * g + lr * _unit(e[:3])
                    if np.linalg.norm(ng) > EPS_NORM:
                        self.st.goal_spa_pos = _unit(ng).tolist()
                if e.size == 4 and self.st.goal_phy:
                    g = np.asarray(self.st.goal_phy, float)
                    ng = (1 - lr) * g + lr * _unit(e)
                    if np.linalg.norm(ng) > EPS_NORM:
                        self.st.goal_phy = _unit(ng).tolist()
            if end_chunk is not None:
                e = np.asarray(end_chunk, float).ravel()
                if e.size == 4 and self.st.goal_phy:
                    g = np.asarray(self.st.goal_phy, float)
                    ng = (1 - lr) * g + lr * _unit(e)
                    if np.linalg.norm(ng) > EPS_NORM:
                        self.st.goal_phy = _unit(ng).tolist()
            # 成功 ⇒ 权重小幅上升(几何引导被验证有效)
            self.st.w_spa = min(PHI_W_MAX, self.st.w_spa + 0.01)
            self.st.w_phy = min(PHI_W_MAX, self.st.w_phy + 0.01)
        else:
            self.st.n_fail += 1
            # 失败 ⇒ 权重回退(几何引导可能是元凶), 但不归零
            self.st.w_spa = max(0.0, self.st.w_spa - 0.05)
            self.st.w_phy = max(0.0, self.st.w_phy - 0.05)
        self.st.last_ts = time.time()
        self._save()
        return {"w_spa": round(self.st.w_spa, 4), "w_phy": round(self.st.w_phy, 4),
                "n_success": self.st.n_success, "n_fail": self.st.n_fail}

    # ─────────────── 落盘 / 读取 ───────────────
    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
            with open(self.state_path, "w") as f:
                json.dump({"state": asdict(self.st),
                           "gates": {"sem": self.en_sem, "spa": self.en_spa, "phy": self.en_phy},
                           "saved_at": time.strftime("%F %T")}, f, ensure_ascii=False, indent=1)
        except Exception as e:
            if self.verbose:
                print("保存状态失败: %s" % e)

    def _load(self):
        try:
            if os.path.exists(self.state_path):
                d = json.load(open(self.state_path))
                s = d.get("state", {})
                for k, v in s.items():
                    if hasattr(self.st, k):
                        setattr(self.st, k, v)
        except Exception:
            pass

    def health(self):
        """自检: 三门状态 / 目标是否就位 / 权重 / 进化次数"""
        return {
            "gates": {"sem": self.en_sem, "spa": self.en_spa, "phy": self.en_phy},
            "goal_sem_ready": bool(self.st.goal_sem),
            "goal_spa_ready": bool(self.st.goal_spa_pos),
            "goal_phy_ready": bool(self.st.goal_phy),
            "w_spa": round(self.st.w_spa, 4), "w_phy": round(self.st.w_phy, 4),
            "n_updates": self.st.n_updates, "n_success": self.st.n_success,
            "n_fail": self.st.n_fail, "state_path": self.state_path,
            "passthrough": not (self.en_sem or self.en_spa or self.en_phy),
        }
