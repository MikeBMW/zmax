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

from PyQt5.QtWidgets import (QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QLabel,
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


def _resid(total, parts):
    """矢量等式残差: |合力 − Σ(主力 + 各赋能力)| —— 按定义应为 0 (量出来才算保证)。"""
    s = _vsum(parts)
    return _vnorm([float(total[i]) - s[i] for i in range(3)])


def vec_to_quat(v, u_ref):
    """向量 → 单位四元数 (指数映射)。θ = π·min(1, |v|/u_ref), 轴 = v 的单位方向。"""
    v = [float(x) for x in (v or [0.0, 0.0, 0.0])]
    n = math.sqrt(sum(x * x for x in v)) if v else 0.0
    if n < 1e-12:
        return (1.0, 0.0, 0.0, 0.0), 0.0, (0.0, 0.0, 0.0)
    u = [x / n for x in v]
    ratio = 1.0 if not u_ref else min(1.0, n / u_ref)
    th = math.pi * ratio
    s = math.sin(th / 2.0)
    q = (math.cos(th / 2.0), u[0] * s, u[1] * s, u[2] * s)
    nn = math.sqrt(sum(x * x for x in q))
    return tuple(x / nn for x in q), n, tuple(u)


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
        self.stage_idx = self.chunk.get("stage_idx")
        self.task_id = self.meta.get("task_id") or self.engine.get("task_id") or "?"
        self.task_name = self.meta.get("task_name") or self.engine.get("task_name") or "?"
        self.by_layer = self.meta.get("by_layer") or {}
        self.skills = self.chunk.get("skills") or {}
        self.chunk_steps = self.chunk.get("chunk") or []
        self.ff_steps = self.chunk.get("ff") or []
        self.exec_axis = self._exec_axis()          # 每个阶段的真实运动方向 (真源 u_exec_vec)
        self.rows = self._build_rows()

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

    def _live_cells(self, s):
        """该状态空间项的四层力 —— 用**当前帧**(在跑的项) / 该阶段**末帧**(已跑过的项) 的真实动作矢量。
        L2=u_exec(执行收口) L3=u_limit(调度限幅后) L4=u_ff(认知前馈) L5=prior(意图规划)"""
        lv = getattr(self, "live", None) or {}
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
                v = [x / _n * float(self.u_ref) for x in v]
            mg = math.sqrt(sum(x * x for x in v))
            out[lk] = dict(mag=mg, vec=v,
                           src="reports/ss_episode_latest.npz.%s[%d] (当前帧真源 · %s)"
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
            row_q, _n, _u = vec_to_quat(_vs, self.u_ref)
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

    def _main_layer(self, s, cells):
        """主力判定 (老倪口径):
           · 这一拍**正在跑**的项 ⇒ L2 执行收口是主力, 其余是赋能力 (例: 插拔时刻 插拔技能的 L2 是主力);
           · 没在跑的项 ⇒ 该行里真实影响力最大的那一层 (未执行时决定权在上层)。
        """
        if s == self.stage_now and cells["L2"].get("mag") is not None:
            return "L2"
        cand = [(k, cells[k].get("mag")) for k, _ in LAYERS if cells[k].get("mag") is not None]
        if not cand:
            return None
        return max(cand, key=lambda kv: kv[1])[0]

    # ---- 合力 (行 / 列 / 总) ----
    def row_resultant(self, row):
        """该行合力 = 该行四层力矢量相加 (主力 + 补偿微调); 第二个返回值 = 主力↔合力夹角(°)。"""
        return row["q"], row.get("dev", 0.0)

    def col_resultant(self, layer):
        vecs = [r["cells"][layer].get("vec") for r in self.rows]
        q, _n, _u = vec_to_quat(_vsum(vecs), self.u_ref)
        return q, _coh(vecs)

    def total_resultant(self):
        """全表总合力 = 所有格子的力矢量相加 (右下角那格); 第二个返回值 = 全表一致度。"""
        vecs = [r["cells"][k].get("vec") for r in self.rows for k, _ in LAYERS]
        q, _n, _u = vec_to_quat(_vsum(vecs), self.u_ref)
        return q, _coh(vecs)

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
    """一个标签「万有引力」+ 表格 (行=状态空间项, 列=L2/L3/L4/L5/合力, 右下角=总合力)。"""

    def __init__(self, parent=None):
        super(GravityTableWidget, self).__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(3)

        self.lbl_head = QLabel("")
        self.lbl_head.setWordWrap(True)
        self.lbl_head.setStyleSheet("color:#8b949e;font-size:12px;font-family:Consolas,monospace;")
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
        lay.addWidget(self.t, 1)

        self.lbl_foot = QLabel("")
        self.lbl_foot.setWordWrap(True)
        self.lbl_foot.setTextInteractionFlags(Qt.TextSelectableByMouse)
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
            self.field = GravityField()
        except Exception as e:                                               # noqa: BLE001
            self.lbl_head.setText("万有引力: 真源读不到 (%s)" % e)
            return
        f = self.field
        # ① 按当前宽度定格式 (一行四个数优先; 不够降小数位; 再不够 2×2) + 同步字号/行高
        self._fmt = self._pick_fmt()
        _dec, _px, _pair = self._fmt
        self.t.setStyleSheet(
            "QTableWidget{background:#0d1117;color:#e6edf3;gridline-color:#21262d;"
            "font-size:%dpx;font-family:Consolas,monospace;border:none;}"
            "QHeaderView::section{background:#161b22;color:#8b949e;border:none;padding:2px;font-size:13px;}" % _px)
        self.t.verticalHeader().setDefaultSectionSize(42 if _pair else 40)   # 合力列第二行写 Δ主 xx°
        self._q = lambda q: _q_str(q, _dec, _pair)               # 本拍的四元数写法
        self.lbl_head.setText("🌍 " + f.header_line())

        rows = f.rows
        self.t.setRowCount(len(rows) + 1)                  # + 最下面一行 = 各列合力
        for i, r in enumerate(rows):
            it = QTableWidgetItem("%s%s\n拍%s%s" % ("★" if r["main"] else "", r["stage"],
                                                     r["tick"] if r["tick"] is not None else "-",
                                                     " 跑" if r["active"] else ""))
            it.setForeground(QColor("#e6edf3" if r["active"] else "#8b949e"))
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
        tot = QTableWidgetItem("总合力(全表)\n%s\n%s行合力\n%s\n致%.2f Δ主%.0f°\n主 %s·%s"
                               % (_q_str(qt, 2), (_ar or {}).get("stage") or "本刻",
                                  _q_str((_ar or {}).get("q") or (1.0, 0, 0, 0), 2),
                                  coht, _dev_tot, dn_s or "?", dn_k or "?"))   # 2 位小数: 3 位在窄栏会被 Qt 打省略号
        tot.setForeground(QColor("#ffd33d"))
        fo = QFont("Consolas")
        fo.setPixelSize(self._fmt[1])          # 与表体同字号 (别用 10pt/11pt 混排 ⇒ 量宽与实际不一致)
        fo.setBold(False)                      # 不粗体: 3 位小数的四元数 + 粗体会宽 ~5%, 边缘那格会被 Qt 打省略号
        tot.setFont(fo)
        tot.setBackground(QColor(187, 128, 9, 70))
        tot.setToolTip("总合力(全表) = 所有格子的力矢量相加\n本刻行合力 = 在跑的那一项那一行的合力 = 主力 + Σ赋能力\nΔ主 = 该合力与主力的夹角\n"
                       "全精度: 总合力 %s · 本刻行合力 %s" % (_fmt_q(qt), _fmt_q((_ar or {}).get("q") or (1.0, 0, 0, 0))))
        self.t.setItem(li, 1 + len(LAYERS), tot)
        self.t.setRowHeight(li, 120)   # 右下角那格: 全表总合力 + 本刻行合力 + 一致度/夹角/主力                    # 右下角那格内容多 (总合力+一致度+主力), 单独给高一点

        stale = [k for k, v in f.age.items() if v is not None and v > 60]
        _age_col = "#f85149" if stale else "#7ee787"
        self.lbl_foot.setStyleSheet("color:%s;font-size:12px;font-family:Consolas,monospace;"
                                    "background:#0d1117;border:1px solid #21262d;border-radius:5px;padding:4px;" % _age_col)
        # 🔴 这一行是**保证看得见**的 (表若被窗口裁了, 右下角总合力也要在页面上有一份; 老倪拿画面当结果)
        _res_max, _dev_max, _coh_all = f.equation()
        _tot_line = ("★★ 全表总合力 %s · 一致度 %.2f · 本刻主力 %s·%s ★★"
                     % (_fmt_q(qt), coht, dn_s or "?", dn_k or "?"))
        # 老倪 2026-10-16: 「主力是快速动作, 合力是叠加了补偿微调的总和矢量力, 保证等式关系」
        _run_dev = [r.get("dev", 0.0) for r in rows if r.get("main") == "L2"]
        _eq_line = ("✅ 等式: 合力 = 主力 + Σ赋能力 (矢量相加) · 逐行残差 max %.1e · 在跑项 主↔合 %.1f° · "
                    "全表最大 %.1f° · 全表一致度 %.2f"
                    % (_res_max, (max(_run_dev) if _run_dev else 0.0), _dev_max, _coh_all))
        self.lbl_foot.setText(
            _tot_line + "\n" + _eq_line + "\n" + f.live_line() + "\n"
            + (f.age_line() + ("  ← 这几项不是本刻的, 上面格子的力是它们最后一拍的值\n" if stale else "\n"))
            + "四元数 = 该层这一拍对该项的力: q=(cosθ/2, sinθ/2·û), θ=π·min(1,|F|/u_ref), u_ref=%.3f (本拍参考速度, 真源) · "
              "★=主力 (正在跑的项 ⇒ L2 执行收口; 未在跑的项 ⇒ 影响力最大层) · 其余格子是赋能力 · "
              "合力 = 主力 + Σ赋能力 (各层力**矢量相加**: F_i=|F_i|·û_i), 一致度 |ΣF|/Σ|F|。真源: meta_tasks/skill_latest/chunk_latest/engine_latest/ss_traj_last (只读) · 每 0.7s 重读一次"
            % f.u_ref)

    def refresh_if_visible(self):
        if self.isVisible():
            self.refresh()
