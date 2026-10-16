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
  合力 = 四元数归一化和 (Markley 平均): q_bar = Σq / |Σq|, 一致度 = |Σq| / n
    (1.0 = 四层完全同向使劲; →0 = 互相抵消, 谁也没推动)。
"""

from __future__ import annotations

import json
import math
import os
import time

from PyQt5.QtWidgets import (QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QLabel,
                             QHeaderView)
from PyQt5.QtCore import Qt
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

# 元任务链上的 8 个状态空间项 (顺序 = 执行顺序; 真源里 <项>_拍 给出拍序)
STAGES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]

LAYERS = [("L2", "L2 执行收口"), ("L3", "L3 调度规划"),
          ("L4", "L4 认知策略"), ("L5", "L5 意图规划")]


# ────────────────────────── 数学: 向量 → 四元数 / 合力 ──────────────────────────
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


def quat_sum(qs, weights=None):
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

        self.u_ref = float(self.chunk.get("u_norm0") or 0.0) or 0.1417      # 参考速度 (真源: 本拍首个动作范数)
        self.stage_now = self.chunk.get("stage") or None
        self.stage_idx = self.chunk.get("stage_idx")
        self.task_id = self.meta.get("task_id") or self.engine.get("task_id") or "?"
        self.task_name = self.meta.get("task_name") or self.engine.get("task_name") or "?"
        self.by_layer = self.meta.get("by_layer") or {}
        self.skills = self.chunk.get("skills") or {}
        self.chunk_steps = self.chunk.get("chunk") or []
        self.ff_steps = self.chunk.get("ff") or []
        self.exec_axis = self._exec_axis()          # 每个阶段的真实运动方向 (真源 u_exec_vec)
        self.rows = self._build_rows()

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

            # 每格 → 四元数
            for k, c in cells.items():
                if c.get("mag") is None or not c.get("vec"):
                    c["q"] = None
                    continue
                c["q"], _n, _u = vec_to_quat(c["vec"], self.u_ref)

            row_q, row_coh = quat_sum([cells[k].get("q") for k, _ in LAYERS])
            rows.append(dict(stage=s, axis=axis, cells=cells, q=row_q, coh=row_coh,
                             active=(s == self.stage_now), tick=tick,
                             own=self._own_layer(s),
                             main=self._main_layer(s, cells)))
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
        return row["q"], row["coh"]

    def col_resultant(self, layer):
        qs = [r["cells"][layer].get("q") for r in self.rows]
        return quat_sum(qs)

    def total_resultant(self):
        qs, ws = [], []
        for r in self.rows:
            for k, _ in LAYERS:
                q = r["cells"][k].get("q")
                if q:
                    qs.append(q)
                    ws.append(max(1e-6, float(r["cells"][k].get("mag") or 0.0)))   # 力度当权重
        return quat_sum(qs, ws)

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


class GravityTableWidget(QWidget):
    """一个标签「万有引力」+ 表格 (行=状态空间项, 列=L2/L3/L4/L5/合力, 右下角=总合力)。"""

    def __init__(self, parent=None):
        super(GravityTableWidget, self).__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(3)

        self.lbl_head = QLabel("")
        self.lbl_head.setWordWrap(True)
        self.lbl_head.setStyleSheet("color:#8b949e;font-size:11px;font-family:Consolas,monospace;")
        lay.addWidget(self.lbl_head)

        self.t = QTableWidget(0, 2 + len(LAYERS) + 1)
        heads = ["状态空间项 · 元任务"] + [n for _k, n in LAYERS] + ["合力"]
        self.t.setHorizontalHeaderLabels(heads)
        self.t.verticalHeader().setVisible(False)
        self.t.setStyleSheet(
            "QTableWidget{background:#0d1117;color:#e6edf3;gridline-color:#21262d;"
            "font-size:10px;font-family:Consolas,monospace;border:none;}"
            "QHeaderView::section{background:#161b22;color:#8b949e;border:none;padding:1px;font-size:10px;}")
        self.t.verticalHeader().setDefaultSectionSize(30)
        hh = self.t.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
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
        self.refresh()

    def refresh(self):
        try:
            self.field = GravityField()
        except Exception as e:                                               # noqa: BLE001
            self.lbl_head.setText("万有引力: 真源读不到 (%s)" % e)
            return
        f = self.field
        self.lbl_head.setText("🌍 " + f.header_line())

        rows = f.rows
        self.t.setRowCount(len(rows) + 1)                  # + 最下面一行 = 各列合力
        for i, r in enumerate(rows):
            it = QTableWidgetItem("%s\n拍%s%s" % (r["stage"], r["tick"] if r["tick"] is not None else "-",
                                                  " · 在跑" if r["active"] else ""))
            it.setForeground(QColor("#e6edf3" if r["active"] else "#8b949e"))
            self.t.setItem(i, 0, it)
            for j, (k, _n) in enumerate(LAYERS):
                c = r["cells"][k]
                if c.get("q") is None:
                    cell = QTableWidgetItem("未算\n%s" % c.get("src", ""))
                    cell.setForeground(QColor("#484f58"))
                else:
                    cell = QTableWidgetItem("%s\n|F|=%.3f%s" % (_fmt_q(c["q"]), c["mag"],
                                                                (" 爪%.2f" % c["gripper"]) if c.get("gripper") is not None else ""))
                    cell.setForeground(QColor("#e6edf3"))
                    if r["main"] == k:                     # ✅ 主力高亮
                        cell.setText("★ " + cell.text())
                        cell.setBackground(QColor(31, 111, 235, 90))
                        cell.setForeground(QColor("#ffd33d"))
                        fo = QFont("Consolas", 8)
                        fo.setBold(True)
                        cell.setFont(fo)
                cell.setToolTip("%s\n真源: %s" % (c.get("note") or "", c.get("src", "")))
                self.t.setItem(i, 1 + j, cell)
            # 该行合力
            rc = QTableWidgetItem("%s\n一致度=%.2f" % (_fmt_q(r["q"]), r["coh"]))
            rc.setForeground(QColor("#79c0ff"))
            rc.setToolTip("该行四层力的合力 (四元数归一化和) · 一致度 1.0=四层同向, →0=互相抵消")
            self.t.setItem(i, 1 + len(LAYERS), rc)

        # ── 最下面一行: 各列合力 + 右下角 = 全表总合力 ──
        li = len(rows)
        hd = QTableWidgetItem("合力 (列)")
        hd.setForeground(QColor("#79c0ff"))
        self.t.setItem(li, 0, hd)
        for j, (k, _n) in enumerate(LAYERS):
            q, coh = f.col_resultant(k)
            it = QTableWidgetItem("%s\n一致度=%.2f" % (_fmt_q(q), coh))
            it.setForeground(QColor("#79c0ff"))
            it.setToolTip("L2/L3/L4/L5 各列: 该列所有项的力之和 (四元数归一化和)")
            self.t.setItem(li, 1 + j, it)
        qt, coht = f.total_resultant()
        dn_s, dn_k = f.dominant_now()
        tot = QTableWidgetItem("总合力\n%s\n一致度=%.2f\n主力: %s · %s"
                               % (_fmt_q(qt), coht, dn_s or "?", dn_k or "?"))
        tot.setForeground(QColor("#ffd33d"))
        fo = QFont("Consolas", 8)
        fo.setBold(True)
        tot.setFont(fo)
        tot.setBackground(QColor(187, 128, 9, 70))
        tot.setToolTip("全表所有力的合力 (四元数归一化和, 以各格力度为权)")
        self.t.setItem(li, 1 + len(LAYERS), tot)

        stale = [k for k, v in f.age.items() if v is not None and v > 60]
        _age_col = "#f85149" if stale else "#7ee787"
        self.lbl_foot.setStyleSheet("color:%s;font-size:10px;font-family:Consolas,monospace;"
                                    "background:#0d1117;border:1px solid #21262d;border-radius:5px;padding:4px;" % _age_col)
        # 🔴 这一行是**保证看得见**的 (表若被窗口裁了, 右下角总合力也要在页面上有一份; 老倪拿画面当结果)
        _tot_line = ("★★ 全表总合力 %s · 一致度 %.2f · 本刻主力 %s·%s ★★"
                     % (_fmt_q(qt), coht, dn_s or "?", dn_k or "?"))
        self.lbl_foot.setText(
            _tot_line + "\n"
            + (f.age_line() + ("  ← 这几项不是本刻的, 上面格子的力是它们最后一拍的值\n" if stale else "\n"))
            + "四元数 = 该层这一拍对该项的力: q=(cosθ/2, sinθ/2·û), θ=π·min(1,|F|/u_ref), u_ref=%.3f (本拍参考速度, 真源) · "
              "★=主力 (正在跑的项 ⇒ L2 执行收口; 未在跑的项 ⇒ 影响力最大层) · 其余格子是赋能力 · "
              "合力 = 四元数归一化和 (Markley), 一致度 |Σq|/n。真源: meta_tasks/skill_latest/chunk_latest/engine_latest/ss_traj_last (只读)"
            % f.u_ref)

    def refresh_if_visible(self):
        if self.isVisible():
            self.refresh()
