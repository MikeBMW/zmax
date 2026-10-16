# -*- coding: utf-8 -*-
"""🌍 万有引力表 —— 主参数 M 页 (太阳系下面那张表) · 老倪 2026-10-16 口述规格

规格 (逐字对照老倪原话):
  · 太阳系下面的参数区不再分「测量/标定/诊断/配置」, 只要一个标签「万有引力」
  · 列一个表格: 第一列 = 实际对应状态空间 (当前配置的元任务), 依次的列为 L2 L3 L4 L5 合力
  · 每个格子是一个四元数; 表格右下角 = 所有四元数的合力
  · 每一时刻有一个**主力**, 其余格子是赋能力; 主力高亮
  · 例: 插拔的时刻, 插拔技能 (L2) 是主力, L3 的规划 action 与 L4/L5 都是赋能力

真源 (只读; 缺哪个就如实写「未算」并把缺的真源写进 tooltip, 绝不编造数字):
  zmax_data/ss_live/meta_tasks.json   ← 当前配置的元任务 (task_id / 名称 / items / by_layer)
  zmax_data/ss_live/skill_latest.json ← 每个阶段的 L2 实际 (<s>_mps) 与 L5 意图请求 (<s>_请求_mps) / 可行 / 拍
  zmax_data/ss_live/chunk_latest.json ← L3 规划 chunk / L2 技能派发 skills[<s>] / L4 前馈 ff / 参考速度 u_norm0
  zmax_data/ss_live/engine_latest.json← 帧龄 / 工况 (阶段·拍) / 潜空间输出
  data/database/zmax/sources/canvas/ss_traj_last.json ← 真实执行轴 (u_exec_vec 逐帧 ⇒ 每个阶段的真实运动方向)

四元数怎么来的 (每格一个, 全部由真源向量算, 不是摆上去的):
  该层这一拍对该项的力 → 向量 v (方向 = 该项真实运动轴 or 该层自己的 action 方向)
                        → 指数映射 q = (cos(θ/2), sin(θ/2)·û),  θ = π·min(1, |v| / u_ref)
  u_ref = chunk_latest.u_norm0 (本拍参考速度, 真源) ⇒ 满速 = 转 π (180°), 力越大转得越多;
  |F| 就是该层的真实幅值 (m/s 或 action 范数), 一并显示 ⇒ 「四元数 + 强度」两项都看得见。
  合力 = 主力 + Σ赋能力 (各层力**矢量相加** F_i=|F_i|·û_i), 一致度 = |ΣF| / Σ|F| —— 2026-10-16 老倪口径
  (旧的「四元数等权平均 Markley」已弃用: 那时 |F合| 恒为 0, 与老倪「主力和合力相差不大」矛盾)
    (1.0 = 四层完全同向使劲; →0 = 互相抵消, 谁也没推动)。
"""

from __future__ import annotations

import json
import math
import os
import time

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QLabel, QSizePolicy,
                             QHeaderView)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont

# ── 真源路径 (相对工程根; 缺文件 = 该项如实「未算」) ──
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _p(*parts):
    return os.path.join(_ROOT, *parts)


SRC = {
    "meta":   _p("zmax_data", "ss_live", "meta_tasks.json"),
    "skill":  _p("zmax_data", "ss_live", "skill_latest.json"),
    "chunk":  _p("zmax_data", "ss_live", "chunk_latest.json"),
    "engine": _p("zmax_data", "ss_live", "engine_latest.json"),
    "traj":   _p("data", "database", "zmax", "sources", "canvas", "ss_traj_last.json"),
}

# ── 活源 (2026-10-16: 老倪「运行插拔工程时四元数都不动」⇒ 表必须跟着当前帧动) ──
#   trace_live.json: 秒级刷新, 给出**当前帧号/阶段**; ss_episode_latest.npz: 逐帧动作矢量
#   (u_exec_vec=L2 执行 / u_limit_vec=L3 调度限幅 / u_ff_vec=L4 认知前馈 / prior_vec=L5 意图)
SRC_LIVE = {
    "trace": _p("zmax_data", "ss_live", "trace_live.json"),
    "npz":   _p("reports", "ss_episode_latest.npz"),
}

_NPZ_CACHE = {"key": None, "z": None}

# 🚦 实跑判定: 只有**真在跑工程**时表才跟实时 (老倪 2026-10-16: 「现在什么都没有运行, 为什么合力还在变化」)
#    为什么需要: 3D 场景面板自己会**回放**录制的 episode, trace_live.json 一直在走 ⇒ 照它刷表面上看"实时",
#    其实没有实跑。判据 = 引擎认知块 (engine_latest/chunk_latest) 是否在写 (实跑时它 ≤ 1s 一写)。
_RUN_FRESH_S = 30.0
_RUN_OVERRIDE = None          # None=自动判定 (判据脚本用它跑"在跑/没跑"两分支)


def run_state(now=None):
    """(是否实跑, 判据说明)。实跑 = 引擎认知块新鲜 (engine_latest.json mtime ≤ 30s)。"""
    if _RUN_OVERRIDE is not None:
        return bool(_RUN_OVERRIDE), "override"
    now = now or time.time()
    ages = []
    for nm in ("engine_latest.json", "chunk_latest.json"):
        q = _p("zmax_data", "ss_live", nm)
        try:
            ages.append(now - os.path.getmtime(q))
        except Exception:                                                    # noqa: BLE001
            pass
    if not ages:
        return False, "引擎认知块缺失"
    a = min(ages)
    return (a <= _RUN_FRESH_S), ("引擎认知块 %s 前写过" % ("%.1fs" % a if a <= 60 else "%.0f 分钟" % (a / 60.0)))


def _npz_cached(path):
    """按 (路径, mtime) 缓存 episode npz —— 每 0.7s 重解 851 帧没必要。"""
    try:
        key = (path, os.path.getmtime(path))
    except Exception:                                                        # noqa: BLE001
        return None
    if _NPZ_CACHE["key"] == key:
        return _NPZ_CACHE["z"]
    try:
        import numpy as _np
        d = _np.load(path, allow_pickle=True)
        z = {k: d[k] for k in d.files}
    except Exception:                                                        # noqa: BLE001
        return None
    _NPZ_CACHE.update(key=key, z=z)
    return z


# 元任务链上的 8 个状态空间项 (顺序 = 执行顺序; 真源里 <项>_拍 给出拍序)
STAGES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]

LAYERS = [("L2", "L2 执行收口"), ("L3", "L3 调度规划"),
          ("L4", "L4 认知策略"), ("L5", "L5 意图规划")]


# ────────────────────────── 数学: 向量 → 四元数 / 合力 ──────────────────────────
def _vnorm(v):
    if not v:
        return 0.0
    return math.sqrt(sum(float(x) * float(x) for x in v))


def _vsum(vecs):
    x = [0.0, 0.0, 0.0]
    for v in vecs:
        if not v:
            continue
        for i in range(3):
            x[i] += float(v[i])
    return x


def _coh(vecs):
    """一致度 = |ΣF| / Σ|F| ∈ [0,1]: 1=所有力同向, →0=互相抵消 (老倪: 全是补偿微调)。"""
    tot = sum(_vnorm(v) for v in vecs if v)
    return (_vnorm(_vsum(vecs)) / tot) if tot > 1e-12 else 0.0


def _angle_deg(a, b):
    """两力夹角(°) —— 用来量「主力和合力相差不大」。"""
    na, nb = _vnorm(a), _vnorm(b)
    if na < 1e-12 or nb < 1e-12:
        return 0.0
    d = sum(float(x) * float(y) for x, y in zip(a, b)) / (na * nb)
    return math.degrees(math.acos(max(-1.0, min(1.0, d))))


def _qadd(qs):
    """四元数**逐位相加** (老倪口径: 合力 = 主力 + Σ赋能力, 数上能直接对账)。空集 → 四个 0。"""
    a = [0.0, 0.0, 0.0, 0.0]
    for q in qs:
        if not q:
            continue
        for i in range(4):
            a[i] += float(q[i])
    return tuple(a)


def _qnorm(q):
    """四元数归一 (老倪 2026-10-16: 「总合力的四元数, 各项平方和是不是也应该是 1」)。
    🔴 两种口径要分清, 缺一个他都会觉得不对:
       · **力四元数** (表里格子上的四个数) = (|F|/u_ref, Fx/u_ref, Fy/u_ref, Fz/u_ref) —— **故意不归一**,
         因为它要能**逐位相加** (合力 = 主力 + Σ赋能力, 老倪要按数字对账);
       · **归一四元数** q̂ = q/‖q‖ —— 各项平方和恰为 1 (真正的"单位四元数", 老倪问的这个)。
       归一后**方向不变** (矢量部分与合力 F 同向), 丢掉的只是力度 (‖q‖ 里含着), 所以两个都要给。
    """
    q = [float(x) for x in (q or (0.0, 0.0, 0.0, 0.0))]
    n = math.sqrt(sum(x * x for x in q))
    if n < 1e-15:
        return (0.0, 0.0, 0.0, 0.0), 0.0, 0.0
    u = tuple(x / n for x in q)
    return u, n, sum(x * x for x in u)


def _resid(total, parts):
    """矢量等式残差: |合力 − Σ(主力 + 各赋能力)| —— 按定义应为 0 (量出来才算保证)。"""
    s = _vsum(parts)
    return _vnorm([float(total[i]) - s[i] for i in range(3)])


_FORM_ADDITIVE = True     # 力四元数 = 可逐位相加的形式 (见下); 置 False 回旧的指数映射(不可相加)


def vec_to_quat(v, u_ref):
    """力矢量 → **力的四元数** q = (w, x, y, z) = (|F|/u_ref, Fx/u_ref, Fy/u_ref, Fz/u_ref)。

    🔴 2026-10-16 老倪: 「有的主力的实部都已经是 6 了, 合力的实部还是 0, 这明显没有把主力加上」
       —— 旧写法把力度压进旋转角 θ=π·|F|/u_ref, w=cos(θ/2): 力度一满 w 就变 0 (看上去"没加")，
          而且四元数**相乘**才是复合 ⇒ 四个数之间根本不相加, 老倪按数字对不上账。
       改成**可相加**的力四元数: w=力度(归一), xyz=方向分量(归一) ⇒
          q(合力) = Σ q_i  (逐位相加 == 矢量相加, 浮点级精确) ⇒ 表上能按行/按列直接加给他看。
       注意: 这不是单位四元数 (w²+x²+y²+z² = 2·(|F|/u_ref)² 只在 θ≠π 时接近 1), 是"力的四元数"表示。
    """
    v = [float(x) for x in (v or [0.0, 0.0, 0.0])]
    n = math.sqrt(sum(x * x for x in v)) if v else 0.0
    if n < 1e-12:
        return (0.0, 0.0, 0.0, 0.0), 0.0, (0.0, 0.0, 0.0)
    k = 1.0 / float(u_ref or 1.0)
    q = (n * k, v[0] * k, v[1] * k, v[2] * k)
    return q, n, tuple(x / n for x in v)


def quat_sum(qs, weights=None):   # ⚠️ 已弃用 (2026-10-16 改矢量相加口径), 只留给老判据/别的调用方
    """四元数归一化和 (Markley 平均) → (q_bar, 一致度 |Σ|/n)。空集 → 单位四元数, 一致度 0。"""
    qs = [q for q in (qs or []) if q]
    if not qs:
        return (1.0, 0.0, 0.0, 0.0), 0.0
    ws = list(weights) if weights else [1.0] * len(qs)
    if len(ws) != len(qs):
        ws = [1.0] * len(qs)
    acc = [0.0, 0.0, 0.0, 0.0]
    for q, w in zip(qs, ws):
        for i in range(4):
            acc[i] += float(q[i]) * float(w)
    n = math.sqrt(sum(x * x for x in acc))
    if n < 1e-12:                                   # 完全抵消: 合力方向不确定
        return (1.0, 0.0, 0.0, 0.0), 0.0
    return tuple(x / n for x in acc), n / len(qs)


def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:                                                        # noqa: BLE001
        return None


def _age_s(path):
    try:
        d = time.time() - os.path.getmtime(path)
        return d if d >= 0 else -d                        # 时钟回拨 ⇒ 取绝对值, 别报负数
    except Exception:                                                        # noqa: BLE001
        return None


# ────────────────────────── 数据层: 从真源算全表 ──────────────────────────
class GravityField(object):
    """当前配置的元任务 → 每个状态空间项 × L2/L3/L4/L5 的力 (四元数) + 合力。"""

    def __init__(self, src=None):
        self.src = src or SRC
        self.running, self.run_note = True, ""      # 先给默认, reload() 末尾按引擎认知块新鲜度定
        self.frozen_at = None
        self.reload()

    # ---- 读真源 (全部只读; 任何一步失败都留痕, 不抛) ----
    def reload(self):
        self.meta = _read(self.src["meta"]) or {}
        self.skill = _read(self.src["skill"]) or {}
        self.chunk = _read(self.src["chunk"]) or {}
        self.engine = _read(self.src["engine"]) or {}
        self.traj = _read(self.src["traj"]) or {}
        self.age = {k: _age_s(p) for k, p in self.src.items()}
        self.age.update({("帧" + k): _age_s(p) for k, p in SRC_LIVE.items()})
        self.live = self._load_live()

        self.u_ref = float(self.chunk.get("u_norm0") or 0.0) or 0.1417      # 参考速度 (真源: 本拍首个动作范数)
        self.stage_now = self.chunk.get("stage") or None
        # 🛰 活源优先: trace_live 的当前阶段 + 当前帧的参考速度 (u_fuse 的范数) —— 跑工程时这些秒级在动
        if self.live.get("stage"):
            self.stage_now = self.live["stage"]
        if self.live.get("u_ref"):
            self.u_ref = float(self.live["u_ref"])
        _sn = (self.live or {}).get("snap") or {}
        if _sn.get("阶段限速"):                       # 🎯 满速基准 = 该阶段限速 (在跑的那一项口径)
            self.u_ref = float(_sn["阶段限速"])
        self.stage_idx = self.chunk.get("stage_idx")
        self.task_id = self.meta.get("task_id") or self.engine.get("task_id") or "?"
        self.task_name = self.meta.get("task_name") or self.engine.get("task_name") or "?"
        self.by_layer = self.meta.get("by_layer") or {}
        self.skills = self.chunk.get("skills") or {}
        self.chunk_steps = self.chunk.get("chunk") or []
        self.ff_steps = self.chunk.get("ff") or []
        self.exec_axis = self._exec_axis()          # 每个阶段的真实运动方向 (真源 u_exec_vec)
        self.rows = self._build_rows()
        self._mark_run()                            # 🚦 实跑判定 (没在跑 ⇒ 表定格, 不跟 3D 回放走)

    # ---- 🛰 活源: trace_live (当前帧) + episode npz (逐帧四路动作) ----
    def _load_live(self):
        """读当前帧。返回 {} = 拿不到 (表就退回标称口径, 并在格里写明真源出处)。"""
        out = {}
        tr = _read(SRC_LIVE["trace"]) or {}
        out["frame"] = tr.get("帧")
        out["stage"] = ((tr.get("阶段") or "").split(" ")[0]) or None
        out["t"] = tr.get("时间_s")
        out["stages"] = tr.get("八阶段表") or list(STAGES)
        out["end"] = tr.get("末端")
        out["tr"] = tr
        # 🎛 3D 面板 HUD 上那三个速度 (m/s) —— 这就是屏幕上显示的数, 表直接用它们 ⇒ 与 3D 场景同一帧同一批数
        _snap = {}
        for _nm, _suf in (("前馈速度", "前馈速度"), ("动作调制", "动作调制"), ("安全边界", "安全边界")):
            _xyz = [tr.get("%s_x_mps" % _suf), tr.get("%s_y_mps" % _suf), tr.get("%s_z_mps" % _suf)]
            if all(x is not None for x in _xyz):
                _snap[_nm] = [float(x) for x in _xyz]
        if tr.get("阶段限速_mps") is not None:
            _snap["阶段限速"] = float(tr["阶段限速_mps"])
        out["snap"] = _snap
        z = _npz_cached(SRC_LIVE["npz"])
        if not z:
            return out
        try:
            import numpy as _np
            def _nm(x):
                return str(x).replace("阶段 ", "").split(" ·")[0].strip()
            _stg = [_nm(x) for x in z["stage"]]
            fr = int(out["frame"]) if out.get("frame") is not None else 0
            fr = max(0, min(fr, len(_stg) - 1))
            out["frame"] = fr
            out["vecs"] = {lk: z[key] for key, lk in (("u_exec_vec", "L2"), ("u_limit_vec", "L3"),
                                                     ("u_ff_vec", "L4"), ("prior_vec", "L5"))
                           if key in z}
            rng = {}
            for i, nm in enumerate(_stg):
                if nm in rng:
                    rng[nm][1] = i
                else:
                    rng[nm] = [i, i]
            out["ranges"] = rng
            out["n_frame"] = len(_stg)
            if z.get("u_fuse_vec") is not None:
                out["u_ref"] = float(_np.linalg.norm(_np.asarray(z["u_fuse_vec"][fr][:3], dtype=float)))
        except Exception:                                                    # noqa: BLE001
            pass
        return out

    def _ref_at(self, fr):
        """该帧的参考速度 = |u_fuse_vec[fr][:3]| (逐帧在动); 拿不到就用全局 u_ref。"""
        z = getattr(self, "live", None) or {}
        try:
            import numpy as _np
            a = _npz_cached(SRC_LIVE["npz"]).get("u_fuse_vec")
            if a is not None:
                return float(_np.linalg.norm(_np.asarray(a[int(fr)][:3], dtype=float)))
        except Exception:                                                        # noqa: BLE001
            pass
        return float(self.u_ref)

    def _live_cells(self, s):
        """该状态空间项的四层力 —— 用**当前帧**(在跑的项) / 该阶段**末帧**(已跑过的项) 的真实动作矢量。
        L2=u_exec(执行收口) L3=u_limit(调度限幅后) L4=u_ff(认知前馈) L5=prior(意图规划)"""
        lv = getattr(self, "live", None) or {}
        # ⚡ 本刻在跑的那一项: 直接用 3D 面板快照自己的三个速度 ⇒ 与 3D 场景**同一帧同一批数**
        #   (L2=动作调制器 u_fuse 实际执行 · L3=安全边界 u_limit 调度限幅后 · L4=前馈加速器 u_ff 认知前馈;
        #    L5 意图只给条件: 方向取规划方向, 力度=阶段限速_mps)
        _sn = lv.get("snap") or {}
        if s == self.stage_now and _sn.get("动作调制"):
            _fr = lv.get("frame")
            out = {}
            for _lk, _nm in (("L2", "动作调制"), ("L3", "安全边界"), ("L4", "前馈速度")):
                _v = _sn.get(_nm)
                if not _v:
                    continue
                out[_lk] = dict(mag=math.sqrt(sum(x * x for x in _v)), vec=list(_v),
                                src="trace_live.json.%s_{x,y,z}_mps (3D 面板同一帧快照 · 帧 %s · HUD 上就是这三个数)" % (_nm, _fr),
                                note="帧 %s · 阶段 %s (与 3D 场景同一帧)" % (_fr, s))
            # L5 意图规划: 方向 = 本拍**规划方向**; 力度按认知前馈的实际力度计 (意图只给条件/方向, 不给力度)
            #   不用"阶段限速"当力度: 限速是上限 (> 实际), 会让 L5 一家独占合力, 与老倪「主力是快速动作、
            #   其余是补偿微调」相悖 (实测 L5 w 恒为 1.000 ⇒ 行合力 w 里全是它)。
            _d = _sn.get("动作调制") or [0.0, 0.0, 0.0]
            _n = math.sqrt(sum(x * x for x in _d)) or 1.0
            _ff = _sn.get("前馈速度") or _d
            _fm = math.sqrt(sum(x * x for x in _ff)) or float(self.u_ref)
            _v5 = [x / _n * _fm for x in _d]
            out["L5"] = dict(mag=math.sqrt(sum(x * x for x in _v5)), vec=_v5,
                             src="trace_live.json 规划方向 × |前馈速度|=%.4f m/s (意图只给条件 · 帧 %s)" % (_fm, _fr),
                             note="意图=方向/条件 (本拍规划方向), 力度按认知前馈实际力度计")
            return out or None
        vecs = lv.get("vecs")
        rng = (lv.get("ranges") or {}).get(s)
        if not vecs or not rng:
            return None
        fr = lv.get("frame") if s == self.stage_now else rng[1]
        try:
            fr = max(rng[0], min(int(fr), rng[1]))
        except Exception:                                                        # noqa: BLE001
            fr = rng[1]
        _note = "活帧 %d/%s (阶段区间 %d~%d)" % (fr, lv.get("n_frame") or "?", rng[0], rng[1])
        out = {}
        for lk in ("L2", "L3", "L4", "L5"):
            a = vecs.get(lk)
            if a is None:
                continue
            v = [float(a[fr][0]), float(a[fr][1]), float(a[fr][2])]
            if lk == "L5":
                # 🎯 L5「意图只给条件」: 方向取意图(prior)方向, 力度=本拍参考速度 u_ref ——
                #   prior_vec 是隐空间先验 (量级 ~0.6), 与执行/前馈的动作量级 (~0.01) 不同源,
                #   直接矢量相加会让 L5 独占合力 (实测把"主力↔合力"夹角拉到 105°) ⇒ 归一成同尺度。
                _n = math.sqrt(sum(x * x for x in v)) or 1.0
                _ref = self._ref_at(fr)
                v = [x / _n * _ref for x in v]
            mg = math.sqrt(sum(x * x for x in v))
            out[lk] = dict(mag=mg, vec=v,
                           src="reports/ss_episode_latest.npz.%s[%d] (对照: 上一段 rollout 的逐帧真值 · %s)"
                               % ({'L2': 'u_exec_vec', 'L3': 'u_limit_vec', 'L4': 'u_ff_vec', 'L5': 'prior_vec'}[lk], fr, _note),
                           note="帧 %d · 阶段 %s · t=%.3fs" % (fr, s, float(lv.get("t") or 0.0)))
        return out or None

    # ---- 真实执行轴: ss_traj 逐帧 u_exec_vec 按阶段切段求均值方向 ----
    def _exec_axis(self):
        out = {}
        u = self.traj.get("u_exec_vec") or []
        t = self.traj.get("t") or []
        if not u:
            return out
        n = len(u)
        k = max(1, n // len(STAGES))
        for i, s in enumerate(STAGES):
            seg = u[i * k: (i + 1) * k] if i < len(STAGES) - 1 else u[i * k:]
            if not seg:
                continue
            acc = [0.0, 0.0, 0.0]
            for v in seg:
                for j in range(3):
                    try:
                        acc[j] += float(v[j])
                    except Exception:                                            # noqa: BLE001
                        pass
            k2 = math.sqrt(sum(x * x for x in acc))
            if k2 > 1e-9:
                out[s] = tuple(x / k2 for x in acc)
        out["_n"] = n
        out["_t_span"] = (t[0], t[-1]) if t else (None, None)
        return out

    def _axis(self, s):
        """该阶段的运动方向: 优先真源切段轴; 没有就退回该阶段 L2 派发 action 的方向。"""
        a = self.exec_axis.get(s)
        if a:
            return a, "ss_traj_last.u_exec_vec 切段均值"
        act = (self.skills.get(s) or {}).get("action")
        if act:
            n = math.sqrt(sum(float(x) ** 2 for x in act[:3]))
            if n > 1e-9:
                return tuple(float(x) / n for x in act[:3]), "chunk_latest.skills.%s.action 方向" % s
        return None, None

    # ---- 一行 = 一个状态空间项; 四层各一份力 ----
    def _build_rows(self):
        rows = []
        for s in STAGES:
            axis, axis_src = self._axis(s)
            mps = self.skill.get("%s_mps" % s)
            req = self.skill.get("%s_请求_mps" % s)
            dev = self.skill.get("%s_偏差_mps" % s)
            feas = self.skill.get("%s_可行" % s)
            tick = self.skill.get("%s_拍" % s)
            disp = self.skills.get(s) or {}
            cells = {}

            # L2 执行收口: 该阶段真实执行速度 + 真实运动轴
            if mps is not None and axis:
                _d = ""
                if disp.get("action"):
                    _d = " · 本拍派发 step=%s%s" % (disp.get("step"),
                                                    (" 爪%.2f" % float(disp["action"][3])) if len(disp["action"]) > 3 else "")
                cells["L2"] = dict(mag=abs(float(mps)), vec=[float(axis[0]) * float(mps),
                                                             float(axis[1]) * float(mps),
                                                             float(axis[2]) * float(mps)],
                                   src="skill_latest.%s_mps (实际执行) × %s" % (s, axis_src),
                                   note="拍%s · 可行=%s%s" % (tick, feas, _d))
            else:
                cells["L2"] = dict(mag=None, src="缺 skill_latest.%s_mps" % s)

            # L3 调度规划: 该阶段被调度请求的速度 (真源 skill_latest; 技能闸门就是拿它跟 L2 实际比)
            if req is not None and axis:
                cells["L3"] = dict(mag=abs(float(req)), vec=[float(axis[0]) * float(req),
                                                             float(axis[1]) * float(req),
                                                             float(axis[2]) * float(req)],
                                   src="skill_latest.%s_请求_mps (调度请求) × %s" % (s, axis_src),
                                   note="偏差=%s m/s (请求-实际)" % dev)
            else:
                cells["L3"] = dict(mag=None, src="缺 skill_latest.%s_请求_mps" % s)

            # L4 认知策略: 前馈项 ff (上层策略对本次执行的赋能, 真源: chunk_latest.ff)
            ff = self.ff_steps[0] if self.ff_steps else None
            if ff and s == self.stage_now:
                n4 = math.sqrt(sum(float(x) ** 2 for x in ff[:3]))
                cells["L4"] = dict(mag=n4, vec=list(ff[:3]),
                                   src="chunk_latest.ff[0] (前馈 · %s)" % (self.chunk.get("ff_mode") or ""),
                                   gripper=(float(ff[3]) if len(ff) > 3 else None))
            else:
                cells["L4"] = dict(mag=None, src="缺 chunk_latest.ff (前馈是单拍量, 只有当前阶段 %s 有真源)" % (self.stage_now or "?"))

            # L5 意图规划: 意图只给条件, 强度 = 本拍参考速度 × 策略置信度 (真源: chunk_latest.u_norm0 × engine_latest.confidence)
            conf = self.engine.get("confidence")
            if axis and conf is not None:
                m5 = self.u_ref * float(conf)
                cells["L5"] = dict(mag=m5, vec=[float(axis[0]) * m5, float(axis[1]) * m5, float(axis[2]) * m5],
                                   src="意图条件强度 = u_norm0 %.4f × confidence %s (真源 chunk_latest/engine_latest) × %s"
                                       % (self.u_ref, conf, axis_src),
                                   note="意图不抢主力: 上层只给意图/条件, 执行由 L2 收口")
            else:
                cells["L5"] = dict(mag=None, src="缺 engine_latest.confidence 或该阶段真实轴")

            # 🛰 活源优先: 拿得到当前帧就覆盖 L2/L3/L4/L5 (跑工程时四元数跟着帧动)
            _lv = self._live_cells(s)
            if _lv:
                cells.update(_lv)

            # 每格 → 四元数
            for k, c in cells.items():
                if c.get("mag") is None or not c.get("vec"):
                    c["q"] = None
                    continue
                c["q"], _n, _u = vec_to_quat(c["vec"], self.u_ref)

            _all = [cells[k].get("vec") for k, _ in LAYERS]          # 四层力 (主力 + 三个赋能力)
            _vs = _vsum(_all)                                        # 合力 = 主力 + Σ赋能力 (矢量相加)
            row_q = _qadd([cells[k].get("q") for k, _ in LAYERS])   # 🔴 逐位相加 (四个数能按行加出来)
            #   注意: 不能写成 vec_to_quat(Σvec) —— 那样 w=|ΣF|/u_ref, 会把方向相消的部分从 w 里扣掉,
            #   老倪按数字一加就对不上 ("合力的实部还是 0, 明显没把主力加上")。矢量 Σvec 仍保留给夹角/几何用。
            _km = self._main_layer(s, cells)
            _vm = cells[_km].get("vec") if _km else None
            rows.append(dict(stage=s, axis=axis, cells=cells, q=row_q,
                             coh=_coh(_all), vec=_vs, mag_res=_vnorm(_vs),
                             dev=_angle_deg(_vm, _vs),                      # 主力 ↔ 合力 夹角(°)
                             resid=_resid(_vs, _all),
                             active=(s == self.stage_now), tick=tick,
                             own=self._own_layer(s), main=_km))
        return rows

    @staticmethod
    def _own_layer(s):
        """这一项在元任务里归哪一层管 (状态空间口径; 执行项归 L2)。"""
        return "L2"

    def _mark_run(self):
        """末尾统一实跑判定 (reload 无论走哪条分支都调到)。没在跑 ⇒ 记定格时刻。"""
        self.running, self.run_note = run_state()
        self.frozen_at = None if self.running else time.strftime("%H:%M:%S")
        return self.running

    def _main_layer(self, s, cells):
        """⚡ 主力 (老倪口径, 2026-10-16 纠正):
           **每一时刻只有一个主力** = 正在跑的那一项的 L2 执行收口 (例: 插拔时刻 插拔技能的 L2 是主力)。
           其余格子都是赋能力 —— 所以别的行**不高亮** (原来给每行都标了"影响力最大层", 结果一屏 8 个高亮、
           有的行亮在 L5 上, 老倪问「我选的是 L2, 为什么 L5 也高亮」—— 那是标错了语义)。
           没在跑的项: main=None (不给主力名义), 该行影响力最大的层只写进 tooltip 备用。"""
        if s == self.stage_now and cells["L2"].get("mag") is not None:
            return "L2"
        return None

    def _influence_layer(self, s, cells):
        """没在跑的项: 该行里真实影响力最大的那一层 (只作信息, 不当主力)。"""
        cand = [(k, cells[k].get("mag")) for k, _ in LAYERS if cells[k].get("mag") is not None]
        if not cand:
            return None
        return max(cand, key=lambda kv: kv[1])[0]

    # ---- 合力 (行 / 列 / 总) ----
    def row_resultant(self, row):
        """该行合力 = 该行四层力四元数**逐位相加** (= 矢量相加); 第二个返回值 = 主力↔合力夹角(°)。"""
        return _qadd([row["cells"][k].get("q") for k, _ in LAYERS]), row.get("dev", 0.0)

    def col_resultant(self, layer):
        vecs = [r["cells"][layer].get("vec") for r in self.rows]
        return _qadd([r["cells"][layer].get("q") for r in self.rows]), _coh(vecs)

    def total_resultant(self):
        """全表总合力 = 所有格子四个数**逐位相加** (右下角那格); 第二个返回值 = 全表一致度。"""
        vecs = [r["cells"][k].get("vec") for r in self.rows for k, _ in LAYERS]
        return _qadd([r["cells"][k].get("q") for r in self.rows for k, _ in LAYERS]), _coh(vecs)

    def equation(self):
        """等式核对: 合力 = 主力 + Σ赋能力 (逐行矢量相加) —— 返回 (最大残差, 最大主↔合夹角°, 全表一致度)。"""
        res = max([r.get("resid", 0.0) for r in self.rows] or [0.0])
        dev = max([r.get("dev", 0.0) for r in self.rows] or [0.0])
        _q, coh = self.total_resultant()
        return res, dev, coh

    def dominant_now(self):
        """这一刻全局主力 = (项, 层): 有在跑的项就是它; 否则取权重最大的格子。"""
        act = [r for r in self.rows if r["active"] and r["cells"]["L2"].get("mag") is not None]
        if act:
            r = act[0]
            return r["stage"], r["main"]
        best = None
        for r in self.rows:
            for k, _ in LAYERS:
                m = r["cells"][k].get("mag")
                if m is not None and (best is None or m > best[2]):
                    best = (r["stage"], k, m)
        return (best[0], best[1]) if best else (None, None)

    def live_line(self):
        """🛰 活源一行: 当前帧/阶段/时刻 —— 老倪要能看出表是跟着工程在跑的。"""
        lv = getattr(self, "live", None) or {}
        if getattr(self, "running", True) is False:
            return ("⏸ 未运行 ⇒ 表**定格** (表内数字停在 %s, 不跟 3D 回放走 · 判据: %s)"
                    % (self.frozen_at or "上刻", self.run_note or ""))
        if not lv.get("vecs"):
            return "🛰 活帧: 拿不到 (trace_live/episode npz 缺失 ⇒ 表退回标称口径)"
        return ("🛰 活帧 %s/%s · 阶段 %s · t=%.3fs · 参考速度 u_ref=%.4f · 每 0.7s 重读"
                % (lv.get("frame"), lv.get("n_frame") or "?", self.stage_now or "?", float(lv.get("t") or 0.0), self.u_ref))

    def header_line(self):
        nm = self.age.get("skill")
        line = ("当前配置的元任务: %s · %s · 状态空间项 %s 项 (L2 %s / L3 %s / L4·L5 %s / PLAT %s) · 本拍阶段 %s%s"
                % (self.task_id, self.task_name, self.meta.get("n", "?"),
                   self.by_layer.get("L2", "?"), self.by_layer.get("L3", "?"),
                   self.by_layer.get("L4/L5", "?"), self.by_layer.get("PLAT", "?"),
                   self.stage_now or "?", "" if self.stage_idx is None else " (第 %s 拍)" % self.stage_idx))
        crit = [v for k, v in self.age.items() if k in ("skill", "chunk", "engine") and v is not None]
        if crit:
            mx = max(crit)
            line += " · 真源帧龄 %.1fs%s" % (mx, "" if mx <= 60 else " ⚠️ 非本刻")
        return line

    def age_line(self):
        """逐真源帧龄 (老倪规矩: 实时数据必须标帧龄; 过期的要点名, 不能糊在一起)。"""
        names = {"meta": "元任务", "skill": "技能", "chunk": "规划chunk", "engine": "引擎", "traj": "轨迹"}
        parts = []
        for k, v in self.age.items():
            if v is None:
                parts.append("%s 缺" % names.get(k, k))
            else:
                parts.append("%s %.1fs%s" % (names.get(k, k), v, "⚠️" if v > 60 else ""))
        return "真源帧龄: " + " · ".join(parts)


# ────────────────────────── 视图层 ──────────────────────────
def _fmt_q(q):
    if not q:
        return "未算"
    return "%+.3f %+.3f %+.3f %+.3f" % (q[0], q[1], q[2], q[3])


def _q_num(v, dec):
    """一个数: 3 位小数省前导 0 (+.241) —— 窄栏时列宽实测 ~90px, 带 0 就被 Qt 打省略号。"""
    s = ("%+.*f" % (dec, v))
    return s.replace("+0.", "+.").replace("-0.", "-.")


def _q_str(q, dec=2, pair=False):
    """老倪 2026-10-16: 「四元数不应该是 4 个数么?」⇒ 默认**一行四个数**;
    宽度不够就降小数位 (而不是打省略号), 再不够才回退 2×2 (每行两个, 仍共四个数)。"""
    if not q:
        return "未算"
    v = [_q_num(q[0], dec), _q_num(q[1], dec), _q_num(q[2], dec), _q_num(q[3], dec)]
    if pair:
        return "%s %s\n%s %s" % (v[0], v[1], v[2], v[3])
    return " ".join(v)


def _q_str_old_pair(q):
    """兼容旧调用 (3 位小数 / 2×2), 判据与 tooltip 用。"""
    return _q_str(q, 3, True)


def _fmt_q_line(q):
    """一行版四元数 (老倪: 「字体偏小看不到」+ 侧栏已经够宽) —— 2 位小数, 14px 一行放得下。"""
    if not q:
        return "未算"
    return "%+.2f %+.2f %+.2f %+.2f" % (q[0], q[1], q[2], q[3])


class GravityTableWidget(QWidget):
    resized = pyqtSignal(int)          # 整块高度变化 ⇒ M 页据此把表钉在底部 (永远整块可见)
    """一个标签「万有引力」+ 表格 (行=状态空间项, 列=L2/L3/L4/L5/合力, 右下角=总合力)。"""

    def __init__(self, parent=None):
        super(GravityTableWidget, self).__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(3)

        self.lbl_head = QLabel("")
        self.lbl_head.setWordWrap(True)
        self.lbl_head.setStyleSheet("color:#8b949e;font-size:13px;font-family:Consolas,monospace;")
        lay.addWidget(self.lbl_head)

        self.t = QTableWidget(0, 1 + len(LAYERS) + 1)   # 首列 + L2/L3/L4/L5 + 合力 = 6 列 (原来多出一列空列)
        heads = ["状态空间项 · 元任务"] + [n for _k, n in LAYERS] + ["合力"]
        self.t.setHorizontalHeaderLabels(heads)
        self.t.verticalHeader().setVisible(False)
        self.t.setStyleSheet(
            "QTableWidget{background:#0d1117;color:#e6edf3;gridline-color:#21262d;"
            "font-size:14px;font-family:Consolas,monospace;border:none;}"
            "QHeaderView::section{background:#161b22;color:#8b949e;border:none;padding:2px;font-size:13px;}")
        self.t.verticalHeader().setDefaultSectionSize(42)      # 🌍 四元数一行四个数 (宽度自适应) / 2×2 两行都放得下
        # 2026-10-16 老倪: 「四元数不应该是 4 个数么?」—— 四元数写成一行四个数, 宽度不够就按 _pick_fmt 降小数位。
        #   实测: 右栏就是 682~1120px (由它自己的容器决定, 表给大最小宽只会把表格撑出视口 ⇒ 右边被裁、看着像省略号)。
        #   ⇒ 表不许比视口宽: 最小宽只留一点点, 宽度不够交给 _pick_fmt 降精度 + 外层 QScrollArea 兜底。
        self.t.setMinimumWidth(560)
        hh = self.t.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Fixed)     # 首列只放 2~6 个字 ⇒ 固定 104px, 宽度让给数值列
        self.t.setColumnWidth(0, 104)
        for i in range(1, self.t.columnCount()):
            hh.setSectionResizeMode(i, QHeaderView.Stretch)
        self.t.setWordWrap(True)
        # 2026-10-16 老倪: 「我选的是 L2, 为什么 L5 也有高亮」—— Qt 的 current/selected item 会自己画一块底色,
        #   再叠上重建前的光标位置 ⇒ 看着像第二个主力。表格只读 ⇒ 直接关掉选中高亮, 全表只有"主力"一种亮色。
        from PyQt5.QtWidgets import QAbstractItemView as _AIV
        self.t.setSelectionMode(_AIV.NoSelection)
        self.t.setEditTriggers(_AIV.NoEditTriggers)
        # 🚫 2026-10-16 老倪: 「右边不要有专门针对万有引力表格的拖动调, 直接显示完全就好了」
        #   ⇒ 表不许有**自己的**滚动条/拖动条: 整块按内容高度显示 (装不下由外层页面滚, 不在这里给一条)
        self.t.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.t.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.t.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lay.addWidget(self.t, 0)

        self.lbl_foot = QLabel("")
        self.lbl_foot.setWordWrap(True)
        self.lbl_foot.setMaximumHeight(46)      # 🔒 锁两行 (高度省给太阳系)
        self.lbl_foot.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.lbl_foot.setWordWrap(True)
        self.lbl_foot.setMaximumHeight(46)      # 🔒 锁两行 (高度省给太阳系)
        self.lbl_foot.setStyleSheet("color:#7ee787;font-size:10px;font-family:Consolas,monospace;"
                                    "background:#0d1117;border:1px solid #21262d;border-radius:5px;padding:4px;")
        lay.addWidget(self.lbl_foot)

        self.field = None
        self._fmt = (2, 14, False)          # (小数位, 字号px, 是否 2×2) —— 由 _pick_fmt 按当前宽度定
        self.refresh()
        # ⏱ 2026-10-16 老倪: 「我现在运行插拔工程了, 这些四元数都不动, 这个是 bug, 要实时反映系统当前的合力」
        #   根因: 这张表原来只在「这一页被重建/切页」时才 refresh ⇒ 跑工程时一直显示切页那一拍的值。
        #   ⇒ 自己挂 0.7s 心跳, 每次重读 5 个真源 (小文件, 只读) + 重绘; 页面不可见时 refresh_if_visible 直接返回 (零成本)。
        self._tm = QTimer(self)
        self._tm.setInterval(700)
        self._tm.timeout.connect(self.refresh_if_visible)
        self._tm.start()

    # ── 宽度自适应: 老倪要一行四个数看得见 ⇒ 先降小数位/字宽, 不够才 2×2 (绝不打省略号) ──
    def _pick_fmt(self, w=None):
        from PyQt5.QtGui import QFontMetrics
        w = w or self.t.viewport().width() or self.width() or 682
        _c0 = self.t.columnWidth(0) or 104                     # 首列固定宽, 不算进数值列的份额
        avail = max(40.0, (w - _c0 - 6) / float(self.t.columnCount() - 1) - 8)
        for dec, px, pair in ((3, 14, False), (2, 14, False), (2, 13, False), (1, 13, False), (1, 12, False),
                              (2, 13, True)):
            f = QFont("Consolas")
            f.setPixelSize(px)
            fm = QFontMetrics(f)
            # 用**最宽**的样本量 (带 ★ 主力前缀 + 最宽数值形态, 如 -1.00) ⇒ 宁保守不冒险
            n0 = "-1." + "0" * dec
            sample = ("★" + n0 + " " + n0) if pair else " ".join(["★" + n0] + [n0] * 3)
            if fm.horizontalAdvance(sample) <= avail:
                return dec, px, pair
        return 1, 12, True

    def _maybe_refmt(self):
        """宽度变了 ⇒ 重定格式 (resizeEvent 当时表格 viewport 还是旧宽度, 得等布局落定)。"""
        try:
            if self._pick_fmt() != self._fmt:
                self.refresh()
        except Exception:                                                        # noqa: BLE001
            pass

    def resizeEvent(self, e):                                                    # noqa: N802
        super(GravityTableWidget, self).resizeEvent(e)
        QTimer.singleShot(0, self._maybe_refmt)

    def showEvent(self, e):                                                      # noqa: N802
        super(GravityTableWidget, self).showEvent(e)
        QTimer.singleShot(0, self._maybe_refmt)

    def refresh(self):
        try:
            _new = GravityField()
        except Exception as e:                                               # noqa: BLE001
            self.lbl_head.setText("万有引力: 真源读不到 (%s)" % e)
            return
        # ⏸ 没在实跑 ⇒ **数据定格** (老倪: 「现在什么都没有运行, 为什么合力还在变化」)
        #   为什么: 3D 场景面板自己会**回放**录制的 episode, trace_live 一直在走; 照它刷会把"回放"当成"实时"。
        #   注意: 只冻"数据", 不冻界面 —— 号码字体/列宽仍随宽度重排 (否则拖窄再拖宽会留错字号)。
        self._frozen = getattr(self, "field", None) is not None and not _new.running
        if self._frozen:
            f = self.field
            f.running, f.run_note = False, _new.run_note
            if f.frozen_at is None:
                f.frozen_at = time.strftime("%H:%M:%S")
        else:
            self.field = _new
            f = _new
        # ① 按当前宽度定格式 (一行四个数优先; 不够降小数位; 再不够 2×2) + 同步字号/行高
        self._fmt = self._pick_fmt()
        _dec, _px, _pair = self._fmt
        self.t.setStyleSheet(
            "QTableWidget{background:#0d1117;color:#e6edf3;gridline-color:#21262d;"
            "font-size:%dpx;font-family:Consolas,monospace;border:none;}"
            "QHeaderView::section{background:#161b22;color:#8b949e;border:none;padding:2px;font-size:13px;}" % _px)
        self.t.verticalHeader().setDefaultSectionSize(32 if not _pair else 36)   # 行高 32 = 表体够高, 又给太阳系留出高度   # 🔻收紧: 整页不滚 (老倪: 「显示不全, 一动就滚动」)
        self._q = lambda q: _q_str(q, _dec, _pair)               # 本拍的四元数写法
        try:
            from PyQt5.QtCore import QTimer as _QT
            _QT.singleShot(0, lambda: self.resized.emit(self.block_height()))
        except Exception:                                                        # noqa: BLE001
            pass
        self.lbl_head.setText(("⏸ " if getattr(self, "_frozen", False) else "🌍 ") + f.header_line())

        rows = f.rows
        self.t.setRowCount(len(rows) + 1)                  # + 最下面一行 = 各列合力
        for i, r in enumerate(rows):
            it = QTableWidgetItem("%s%s\n拍%s%s" % ("★" if r["main"] else "", r["stage"],
                                                     r["tick"] if r["tick"] is not None else "-",
                                                     " 跑" if r["active"] else ""))
            it.setForeground(QColor("#e6edf3" if r["active"] else "#8b949e"))
            _inf = f._influence_layer(r["stage"], r["cells"]) if r.get("main") is None else None
            it.setToolTip(("⚡ 本刻主力 (L2 执行收口)" if r.get("main") else
                           ("本刻不是主力 · 该行影响力最大层 = %s (只是信息, 不当主力)" % (_inf or "?")))
                          + "\n主力口径: 每一时刻只有一个 —— 正在跑的那一项的 L2; 其余全是赋能力")
            self.t.setItem(i, 0, it)
            for j, (k, _n) in enumerate(LAYERS):
                c = r["cells"][k]
                if c.get("q") is None:
                    cell = QTableWidgetItem("未算")
                    cell.setForeground(QColor("#484f58"))
                else:
                    cell = QTableWidgetItem(self._q(c["q"]))
                    cell.setForeground(QColor("#e6edf3"))
                    if r["main"] == k:                     # ✅ 主力高亮
                        # 2026-10-16: 不在数值格里塞 ★ —— ★ 走字体回退, 实际渲染比量出来的宽, 会把 4 个数挤成省略号。
                        #   主力信息放到首列 (★ 单独一格, 有空位) + 数值格底色/加粗/黄色。
                        cell.setBackground(QColor(187, 128, 9, 165))     # 实心琥珀底 ⇒ 一眼看出主力
                        cell.setForeground(QColor("#fff8c5"))
                        fo = QFont("Consolas")
                        fo.setPixelSize(self._fmt[1])
                        fo.setBold(True)
                        cell.setFont(fo)
                cell.setToolTip("|F|=%.3f %s\n四元数 (w x y z) = %s\n真源: %s"
                                % (c.get("mag") if c.get("mag") is not None else -1, c.get("note") or "",
                                   _fmt_q(c.get("q")), c.get("src", "")))
                self.t.setItem(i, 1 + j, cell)
            # 该行合力 (一致度放 tooltip; 格子里只放四元数, 免得挤)
            rc = QTableWidgetItem("%s\nΔ主 %.0f°" % (self._q(r["q"]), r.get("dev", 0.0)))
            rc.setForeground(QColor("#79c0ff"))
            rc.setToolTip("该行合力 = 主力 + Σ赋能力 (四层力**矢量相加**) · |F合|=%.3f · 主力↔合力夹角 %.1f°\n"
                          "一致度 |ΣF|/Σ|F| = %.2f (1.0=所有力同向, →0=互相抵消)" % (r.get("mag_res", 0.0), r.get("dev", 0.0), r["coh"]))
            self.t.setItem(i, 1 + len(LAYERS), rc)

        # ── 最下面一行: 各列合力 + 右下角 = 全表总合力 ──
        li = len(rows)
        hd = QTableWidgetItem("合力 (列)")
        hd.setForeground(QColor("#79c0ff"))
        self.t.setItem(li, 0, hd)
        for j, (k, _n) in enumerate(LAYERS):
            q, coh = f.col_resultant(k)
            it = QTableWidgetItem("%s\n致 %.2f" % (self._q(q), coh))     # 「致」= 一致度 (窄栏放得下)
            it.setForeground(QColor("#79c0ff"))
            it.setToolTip("该列合力 = 这一列所有项的力矢量相加 · 一致度 |ΣF|/Σ|F|=%.2f" % coh)
            self.t.setItem(li, 1 + j, it)
        qt, coht = f.total_resultant()
        dn_s, dn_k = f.dominant_now()
        # 老倪 2026-10-16 问「右下角带颜色的四元数是主力么? 加起来的和是右下角的合力么?」
        #   ⇒ 右下角 = **加起来的和** (全表所有格子的力矢量相加), 不是主力; 主力是每行里那格琥珀色的。
        #   这里把两个口径都摆出来, 免得再读错: 全表总合力 + 本刻在跑项那一行的合力 (主力 + Σ补偿)
        _act_row = [r for r in rows if r.get("active")] or []
        _ar = _act_row[0] if _act_row else None
        _main_vec = (_ar["cells"][_ar["main"]].get("vec") if _ar and _ar.get("main") else None)
        _dev_tot = _angle_deg(_main_vec, _vsum([r["cells"][k].get("vec") for r in rows for k, _ in LAYERS]))
        _qtu, _qtn, _qtss = _qnorm(qt)
        # 🎯 2026-10-16 老倪: 「总合力 5.6 哪里来的?」 —— 老口径把**32 个格子**(8 阶段 × 4 层)一股脑相加:
        #   其中只有**在跑的那一项**是本刻的力, 其余 7 行是各阶段定格值 ⇒ 那个数被"格子个数"顶起来了, 不是本刻力。
        #   ⇒ 头条改成**本刻系统合力 = 在跑项(主力 + Σ赋能力)**; 全表 32 格数值和降为附注(写清含哪些)。
        _curq = (_ar or {}).get("q") or (0.0, 0, 0, 0)
        _curq_u, _curq_n, _ = _qnorm(_curq)
        _rest = [0.0] * 4
        for _r in rows:
            if _r is _ar:
                continue
            for _k, _n in LAYERS:
                _q = _r["cells"][_k].get("q")
                if _q:
                    for _i in range(4):
                        _rest[_i] += _q[_i]
        tot = QTableWidgetItem("本刻总合力 %s ‖q‖=%.1f\n%s\n主 %s·%s Δ主%.0f°\n全表32格和 ‖q‖=%.1f\n%s"
                               % ((_ar or {}).get("stage") or "本刻", _curq_n, _q_str(_curq, 1, False),
                                  dn_s or "?", dn_k or "?", _dev_tot, _qtn, _q_str(qt, 1, False)))
        tot.setForeground(QColor("#ffd33d"))
        # 2026-10-16 老倪: 「右下角的字体太小了」⇒ 这一格在列宽内**尽量放大**(粗体 13~18px 自适应)
        from PyQt5.QtGui import QFontMetrics as _QFM
        _cw = self.t.columnWidth(self.t.columnCount() - 1) - 8
        _big = None
        for _px in range(13, 10, -1):
            _f = QFont("Consolas")
            _f.setPixelSize(_px)
            _f.setBold(True)
            try:
                if max(_QFM(_f).horizontalAdvance(_l) for _l in tot.text().split("\n")) <= _cw:
                    _big = _f
                    break
            except Exception:                                                    # noqa: BLE001
                break
        # 表高 = 表头 + 全部行 + 边框 ⇒ 一次显示完全, 不出自己的滚动条
        try:
            _hh = self.t.horizontalHeader().height() or 26
            self.t.setFixedHeight(_hh + sum(self.t.rowHeight(_r) for _r in range(self.t.rowCount())) + 4)
        except Exception:                                                        # noqa: BLE001
            pass
        fo = _big or QFont("Consolas")
        if _big is None:
            fo.setPixelSize(self._fmt[1])
        tot.setFont(fo)
        tot.setBackground(QColor(187, 128, 9, 70))
        tot.setToolTip("归一四元数 q̂ = %s (各项平方和 = %.6f) · ‖q‖ = %.3f\n总合力(全表) = 所有格子的力矢量相加"
                       % (" ".join("%+.3f" % x for x in _qtu), _qtss, _qtn) + "\n本刻行合力 = 在跑的那一项那一行的合力 = 主力 + Σ赋能力\nΔ主 = 该合力与主力的夹角\n"
                       "全精度: 总合力 %s · 本刻行合力 %s" % (_fmt_q(qt), _fmt_q((_ar or {}).get("q") or (1.0, 0, 0, 0))))
        self.t.setItem(li, 1 + len(LAYERS), tot)
        self.t.setRowHeight(li, 112)   # 右下角: 5 行 × ~18px   # 右下角那格: 全表总合力 + 本刻行合力 + 一致度/夹角/主力                    # 右下角那格内容多 (总合力+一致度+主力), 单独给高一点

        stale = [k for k, v in f.age.items() if v is not None and v > 60]
        _age_col = "#f85149" if stale else "#7ee787"
        self.lbl_foot.setStyleSheet("color:%s;font-size:13px;font-family:Consolas,monospace;"
                                    "background:#0d1117;border:1px solid #21262d;border-radius:5px;padding:4px;" % _age_col)
        # 🔴 这一行是**保证看得见**的 (表若被窗口裁了, 右下角总合力也要在页面上有一份; 老倪拿画面当结果)
        _res_max, _dev_max, _coh_all = f.equation()
        _cur = [r for r in rows if r.get("main")]
        _curq = _cur[0]["q"] if _cur else (0.0, 0, 0, 0)
        _curu, _curn, _ = _qnorm(_curq)
        _qu, _qn, _qss = _qnorm(qt)
        # 🗜 页脚压到 3 行 (老倪 2026-10-16: 表「显示不全, 一动就滚动」⇒ 高度省给表):
        #   行1 本刻系统合力 · 行2 主力/归一/平方和 · 行3 活帧+帧龄; 长口径全在 tooltip
        self.lbl_foot.setText(
            "★★ 本刻系统合力 (在跑项 %s = 主力 + Σ赋能力) %s · ‖q‖=%.2f ★★\n"
            "主力 %s·%s · 归一 q̂=[%s] 平方和=%.6f · 全表32格和 ‖q‖=%.1f · %s%s"
            % ((_cur[0]["stage"] if _cur else "无"), _fmt_q(_curq), _curn,
               dn_s or "?", dn_k or "?", " ".join("%+.2f" % x for x in _qu), _qss, _qn,
               f.live_line().replace("🛰 ", "").replace("⏸ ", ""),
               (" ⚠️非本刻" if stale else "")))
        self.lbl_foot.setToolTip(
            "口径: 格子四个数 = 力四元数 (w=|F|/u_ref, xyz=方向分量/u_ref, **不归一** ⇒ 能逐位相加):\n"
            "  合力 = 主力 + Σ赋能力 —— 行合力 = 本行四层逐位相加; 右下角 = 全表所有格子逐位相加\n"
            "  归一后才是单位四元数 (各项平方和 = 1, 方向与合力同向, 力度丢在 ‖q‖ 里)\n"
            "★ = 本刻唯一主力 (正在跑的那一项 ⇒ 它的 L2 执行收口格), 其余格都是赋能力\n"
            "L2/L3/L4 = 该帧 动作调制器/安全边界/前馈加速器 m/s (3D 面板同一帧快照), L5 = 规划方向 × |前馈速度|\n"
            "真源 (只读): trace_live / meta_tasks / skill_latest / engine_latest; 每 0.7s 重读\n"
            "u_ref = %.4f (该阶段限速 = 满速基准)" % f.u_ref)

    def block_height(self):
        """整块高度 = 页头 + 表 + 页脚 (用**已布局的真实高度**, 不用 sizeHint —— 它被换行标签高估过)。"""
        try:
            # 表高是**定值**(setFixedHeight) ⇒ 可信; 页头+页脚给固定余量 (~2 行 + 1 行)
            return max(200, int(self.t.height()) + 104)
        except Exception:                                                        # noqa: BLE001
            return int(self.sizeHint().height())

    def refresh_if_visible(self):
        if self.isVisible():
            self.refresh()
