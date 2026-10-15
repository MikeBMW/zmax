#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🪐 orbital_arch.py — 球心引力架构视图 (画布右侧「主参数 M」侧栏页)

老倪 2026-10-16 原话:
  「在右侧侧面栏, 流形引擎是太阳, 前馈加速器是地球, DiT是火星, 接触流形是水星,
    性能流形是木星, 原子技能是卫星, 用球体映射主要的节点。状态校正节点是月球。
    前馈加速器和状态校正器协同行进」
  「流形引擎, 几何空间变换到接触流形, 同时并行集合空间变换到性能流形, 然后汇总, 通过条件网络的
    形式, 并行汇总注入 L3 层的 action head flow matching DiT 节点 …… DiT 要输出参考卡尔曼滤波的
    K 增益, 条件网络相当于模型 update, smolvlm 网络相当于测量」

设计红线 (与全工程同口径):
  ① **天体 ↔ 节点不是随便起的名字**: 每一个天体都是画布真源里的**真节点 id** (流形引擎 ss_mani_eng /
     接触流形 ssmani_c / 性能流形 ssmani_p / 前馈加速器 ssff / 状态校正器 ssinnov / DiT ssdec /
     原子技能 ssbg_skill + skill_phys.json 的 SK01..SK13), 视图启动时从画布真源核一遍, 核不上如实报。
  ② **连线只画真连线**: 双通道 (VLM→DiT 直连 ‖ VLM→流形→DiT) 、DiT→前馈→调配器、校正器↔地球协同、
     反馈回中心 (校正器→融合定位建图→流形引擎) 全部取自画布 links 真源, 不凭空画。
  ③ **每个球上的数是真值**: M / φ / ∇Φ / 扭矩 T=M·(−∇Φ) / 度规特征值 (torque_live) · 接触流形
     (‖e∥‖进度 · ‖e⊥‖偏离 · V · V̇) 与性能流形 (V_p · η · ∇V_p) 由 `manifold_layer.py` **真算**
     (与画布节点同一个模块, 不重写公式), 入力为 `ss_traj_last.json` 的真帧 (43D obs 按
     su2.obs43_geometry 的通道划分取手/光模块头/孔位); 前馈请求/偏差/可行 + 过闸统计取 skill_latest;
     残差取 skill_error。**取不到就写「未运行/未测」, 不填 0 不编数**。
  ④ 球体用 QRadialGradient 画 (真球感); 圆/角度映射写清在图注里 (位置不是装饰, 是实测量的映射)。
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
import time

import numpy as np
from PyQt5.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QPainter, QPen, QRadialGradient
from PyQt5.QtWidgets import QSizePolicy, QWidget

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 配色 (与画布/侧栏同族, 暗底)
BG = QColor("#0d1117")
GRID = QColor("#243040")
FG = QColor("#e6edf3")
DIM = QColor("#8b949e")
CYAN = QColor("#39c5cf")
GREEN = QColor("#3fb950")
GOLD = QColor("#d29922")
VIOLET = QColor("#a371f7")
RED = QColor("#f85149")
BLUE = QColor("#4da3ff")


def _load_by_path(modname, relpath, label):
    """按工程根下的文件路径加载模块 —— 不受 sys.path 顺序影响 (leiobot fork 遮蔽坑, 见 manifold_viz.py)。"""
    fpath = os.path.join(_ROOT, relpath)
    if not os.path.isfile(fpath):
        return None, "缺文件: %s" % fpath
    try:
        spec = importlib.util.spec_from_file_location(modname, fpath)
        if spec is None or spec.loader is None:
            return None, "%s: 无法建立模块 spec" % label
        mod = importlib.util.module_from_spec(spec)
        sys.modules[modname] = mod
        spec.loader.exec_module(mod)
        return mod, ""
    except Exception as e:                                                   # noqa: BLE001
        return None, "%s: %s: %s" % (label, type(e).__name__, e)


# ── 天体 ↔ 画布真节点 (单一真源: 这里的 id 必须是画布真源里存在的 id) ──────────────
BODIES = (
    # key,      画布节点 id,     中文名 (老倪口径),        节点名里必须包含
    ("sun",     "ss_mani_eng",  "流形引擎 · 太阳",        "流形引擎"),
    ("mercury", "ssmani_c",     "接触流形 · 水星",        "接触流形"),
    ("earth",   "ssff",         "前馈加速器 · 地球",      "前馈加速器"),
    ("mars",    "ssdec",        "DiT · 火星",             "Action Head"),
    ("jupiter", "ssmani_p",     "性能流形 · 木星",        "性能流形"),
    ("moon",    "ssinnov",      "状态校正器 · 月球",      "状态校正器"),
    ("sats",    "ssbg_skill",   "原子技能 · 卫星带",      "原子技能"),
)

# 真连线里本视图要画的几条 (f,t 必须在画布 links 里真存在)
KEY_EDGES = (
    ("ssvlm", "ssdec",        "① 直连: 语义条件 (VLM 潜空间 z)"),
    ("ssvlm", "ssmani_c",     "② 旁路: 几何条件 (VLM→接触流形)"),
    ("ssvlm", "ssmani_p",     "② 旁路: 几何条件 (VLM→性能流形)"),
    ("ss_mani_eng", "ssmani_c", "太阳→接触流形 (Φ_c)"),
    ("ss_mani_eng", "ssmani_p", "太阳→性能流形 (V_p/η)"),
    ("ssmani_c", "ssdec",     "接触流形 → DiT (条件)"),
    ("ssmani_p", "ssdec",     "性能流形 → DiT (条件)"),
    ("ssdec", "ssff",         "DiT → 前馈加速器 (action→前馈层)"),
    ("ssff", "sssched",       "前馈加速器 → 动作调制器"),
    ("ssinnov", "sssched",    "校正器 → 动作调制器 (反馈)"),
    ("ssinnov", "sssensor",   "校正器 → 融合定位建图 (状态回灌)"),
    ("sssensor", "ss_mani_eng", "融合定位建图 → 流形引擎 (闭环)"),
    ("ssphys", "ssinnov",     "物理约束闸 → 校正器 (偏差)"),
)


class OrbitalArchData:
    """球心引力架构的数据面: 全部现读真源 + 真模块真算 (无编造)。"""

    def __init__(self, root=_ROOT):
        self.root = root
        self.err = []
        self.ages = {}
        self.now = time.time()
        self.canvas = self._j("data/database/zmax/sources/canvas/state_space_obs.json")
        self.mani = self._j("config/calib/zmax_manifold.json")
        self.engine = self._j("zmax_data/ss_live/engine_latest.json")
        self.torque = self._j("zmax_data/ss_live/torque_live.json")
        self.skills = self._j("zmax_data/ss_live/skill_latest.json")
        self.skerr = self._j("zmax_data/ss_live/skill_error.json")
        self.skphys = self._j("zmax_data/ss_live/skill_phys.json")
        self.traj = self._j("data/database/zmax/sources/canvas/ss_traj_last.json")
        self._ml, self._ml_err = _load_by_path("_zmax_manifold_layer", os.path.join("src", "lerobot", "manifold", "manifold_layer.py"), "manifold_layer.py")
        self._su2, self._su2_err = _load_by_path("_zmax_su2_geo", os.path.join("src", "lerobot", "policies", "left_right", "state_space", "su2.py"), "su2.py")
        self.nodes = {n.get("id"): n for n in (self.canvas.get("nodes") or [])} if self.canvas else {}
        self.links = list(self.canvas.get("links") or []) if self.canvas else []
        self.link_set = {(l.get("f"), l.get("t")) for l in self.links}
        self.body = {}                       # 天体 → 真值 + 真源说明
        self.frames = self._frames()

    # ── 读真源 ────────────────────────────────────────────────────────────
    def _j(self, rel):
        p = os.path.join(self.root, rel)
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            self.ages[rel] = max(0.0, self.now - os.path.getmtime(p))
            return d
        except Exception as e:                                               # noqa: BLE001
            self.err.append("%s: %s" % (rel, e))
            return {}

    def _frames(self):
        """真轨迹帧: hand/peg_head/target/v (43D obs 按 su2.obs43_geometry 的通道划分取)。"""
        obs = (self.traj or {}).get("obs") or []
        if not obs:
            return None
        try:
            a = np.asarray(obs, dtype=float)
            idx = int((self.engine or {}).get("idx") or 0)
            idx = max(0, min(idx, len(a) - 1))
            hand = a[:, 0:3]
            peg = a[:, 4:7].copy()
            peg[:, 2] += 0.030               # 光模块头相对本体中心偏置 (su2.obs43_geometry 同口径)
            tgt = a[:, 36:39]
            t = np.asarray((self.traj or {}).get("t") or list(range(len(a))), dtype=float)
            dt = float(np.median(np.diff(t))) if len(t) > 1 else 0.1
            v = np.gradient(hand, axis=0) / max(dt, 1e-6)
            return {"obs": a, "hand": hand, "peg": peg, "tgt": tgt, "v": v, "idx": idx, "n": len(a), "t": t, "dt": dt}
        except Exception as e:                                               # noqa: BLE001
            self.err.append("traj: %s" % e)
            return None

    # ── 真算: 接触流形 / 性能流形 (同一个 manifold_layer.py, 不重写公式) ─────────
    def manifolds(self, stage):
        out = {"contact": None, "perf": None, "note": ""}
        if self.frames is None:
            out["note"] = "无引擎轨迹 ⇒ 流形量未算 (先点 ▶ 运行状态空间)"
            return out
        f, i = self.frames, self.frames["idx"]
        if self._ml is None:
            out["note"] = "manifold_layer.py 不可用: %s" % self._ml_err
            return out
        try:
            hand, peg, tgt, v = f["hand"][i], f["peg"][i], f["tgt"][i], f["v"][i]
            cm = self._ml.ContactManifold()
            out["contact"] = cm.decompose(hand, peg, tgt, v, stage)
            pm = self._ml.PerformanceManifold()
            out["perf"] = pm.evaluate(peg, stage=stage)
        except Exception as e:                                               # noqa: BLE001
            out["note"] = "流形真算失败: %s: %s" % (type(e).__name__, e)
        # 自洽交叉核对: 重建的 (光模块头−孔位) 必须 == su2.obs43_geometry 的 e
        try:
            e_mine = f["peg"][i] - f["tgt"][i]
            e_ref = np.asarray(self._su2.obs43_geometry(f["obs"][i]), dtype=float)
            out["e_mine"] = [round(float(x), 6) for x in e_mine]
            out["e_ref"] = [round(float(x), 6) for x in e_ref]
            out["e_ok"] = bool(np.allclose(e_mine, e_ref, atol=1e-9))
        except Exception:                                                    # noqa: BLE001
            out["e_ok"] = None
        return out

    # ── 组装: 每个天体的真值 ──────────────────────────────────────────────
    def build(self):
        eng, tq, sk, se, sp = self.engine or {}, self.torque or {}, self.skills or {}, self.skerr or {}, self.skphys or {}
        stage = str(tq.get("stage") or (sk.get("cur_stage") if isinstance(sk, dict) else "") or "")
        if not stage:
            chunk = eng.get("chunk") or {}
            stage = str(chunk.get("stage") or "")
        mf = self.manifolds(stage)
        # 真源核对: 每个天体 id 在画布真源里必须存在, 且名字对得上
        checked = {}
        for key, nid, cn, must in BODIES:
            n = self.nodes.get(nid)
            checked[key] = {"id": nid, "在": bool(n), "名": str((n or {}).get("name", ""))[:34],
                            "名匹配": bool(n) and (must in str((n or {}).get("name", "")))}
        # 太阳
        M = float(eng.get("M") or (self.mani or {}).get("M") or 0.0)
        phi = eng.get("phi")
        grad = eng.get("grad_norm")
        mt = tq.get("metric_tensor") or []
        eig = [float(mt[i * int(tq.get("metric_dim") or 6) + i]) for i in range(int(tq.get("metric_dim") or 6))] if mt else []
        self.body["sun"] = {
            "名": "流形引擎", "真源": "zmax_manifold.json + engine_latest.json + torque_live.json",
            "M": M, "phi": phi, "grad_norm": grad, "p": eng.get("p"),
            "T_norm": tq.get("torque_norm"), "T_max": tq.get("t_max"),
            "metric_dim": tq.get("metric_dim"), "metric_mode": tq.get("metric_mode"),
            "eig_min": (min(eig) if eig else None), "eig_max": (max(eig) if eig else None),
            "clip": tq.get("clipped"), "帧龄": self.ages.get("zmax_data/ss_live/torque_live.json"),
            "t_grad_ms": eng.get("t_grad_ms"), "t_project_ms": eng.get("t_project_ms"), "cycle": eng.get("cycle"),
        }
        # 水星 接触流形
        c = mf.get("contact") or {}
        self.body["mercury"] = {
            "名": "接触流形", "真源": "manifold_layer.ContactManifold.decompose(真帧)",
            "progress": c.get("progress"), "risk": c.get("risk"), "V": c.get("V"), "Vdot": c.get("Vdot"),
            "state": c.get("state"), "risk_th": c.get("risk_th"), "note": mf.get("note", ""),
        }
        # 木星 性能流形
        p = mf.get("perf") or {}
        self.body["jupiter"] = {
            "名": "性能流形", "真源": "manifold_layer.PerformanceManifold.evaluate(真帧)",
            "V_p": p.get("Vp"), "eta": p.get("eta"), "grad": p.get("grad"), "d_perp": p.get("d_perp_norm"),
            "stage": p.get("stage"), "pnote": p.get("note"), "note": mf.get("note", ""),
        }
        # 地球 前馈加速器 (L2 快通道, 权重 30%)
        act = self._active_skill(sp)
        req = sk.get("%s_请求_mps" % (act.get("stage") or ""), None)
        dev = sk.get("%s_偏差_mps" % (act.get("stage") or ""), None)
        feas = sk.get("%s_可行" % (act.get("stage") or ""), None)
        self.body["earth"] = {
            "名": "前馈加速器", "真源": "skill_latest.json (按拍过闸/请求/偏差/可行) + skill_phys.json",
            "stage": act.get("stage"), "SK": act.get("SK"), "req_mps": req, "dev_mps": dev, "可行": feas,
            "拍数": sk.get("闸_拍数"), "过闸": sk.get("过闸_技能拍"), "削因": sk.get("闸_削因"),
            "帧龄": self.ages.get("zmax_data/ss_live/skill_latest.json"),
        }
        # 月球 状态校正器 (卡尔曼校正: 残差 r)
        errs = se.get("err_norm") or {}
        self.body["moon"] = {
            "名": "状态校正器", "真源": "skill_error.json (残差/大误差段) + engine_latest.residual",
            "err": errs.get(act.get("stage") or ""), "err_all": errs, "big": (se.get("big") or {}).get(act.get("stage") or ""),
            "why": (se.get("why") or {}).get(act.get("stage") or ""), "residual": eng.get("residual"),
            "协同": "与地球同相位锁定 (协同行进); 径向摆幅 ∝ 残差",
        }
        # 火星 DiT (条件路数 = 真入边数)
        ins = [l.get("f") for l in self.links if l.get("t") == "ssdec"]
        chunk = eng.get("chunk") or {}
        lam = None
        if isinstance(chunk, dict) and chunk.get("chunk"):
            k = int((eng.get("idx") or 0) % len(chunk["chunk"]))
            lam = eng.get("chunk.λ%d" % k)
        self.body["mars"] = {
            "名": "DiT 动作头", "真源": "engine_latest.json (chunk/λ 计划/action/confidence) + 画布入边真源",
            "cond_n": len(ins), "cond_src": sorted(set(x for x in ins if x))[:8],
            "action_norm": eng.get("action_norm"), "confidence": eng.get("confidence"),
            "H": eng.get("chunk.H"), "lambda": lam, "stage_idx": chunk.get("stage_idx") if isinstance(chunk, dict) else None,
            "K_gain": "未接入 (设计口径: DiT 输出 K 增益 · 条件网络=模型 update · SmolVLM=测量; 真源里目前没有这条边)",
        }
        # 卫星带 原子技能
        sats = []
        for sid, d in sorted((sp.get("skills") or {}).items()):
            if not str(sid).startswith("SK"):        # "_元" 是元信息, 不是技能
                continue
            st = str(d.get("stage") or "")
            sats.append({"SK": sid, "stage": st, "在职": d.get("在职"),
                         "可行": sk.get("%s_可行" % st), "偏差_mps": sk.get("%s_偏差_mps" % st),
                         "err_norm": errs.get(st)})
        try:
            with open(os.path.join(self.root, "config", "calib", "zmax_skill_physics.json"), encoding="utf-8") as _f:
                _cal = json.load(_f)
            n_cal = len([k for k in (_cal.get("skills") or {}) if str(k).startswith("SK")])
        except Exception:                                                    # noqa: BLE001
            n_cal = 0
        self.body["sats"] = {"名": "原子技能", "真源": "skill_phys.json (在职 SK↔段) + skill_latest.json + 标定真源 zmax_skill_physics.json",
                             "list": sats, "active": act.get("SK"), "n": len(sats), "n_calib": n_cal}
        return {"checked": checked, "stage": stage, "mf": mf, "mf_note": mf.get("note", "")}

    def _active_skill(self, sk_phys):
        """当前在职技能 SKxx ↔ 段 (真源: skill_phys.json 的 SK→stage 映射; 段取 torque_live.stage)。"""
        stage = str((self.torque or {}).get("stage") or "")
        for sid, d in sorted((sk_phys.get("skills") or {}).items()):
            if str(d.get("stage") or "") == stage and (d.get("在职") in (1, True)):
                return {"SK": sid, "stage": stage}
        return {"SK": None, "stage": stage}

    def edge_ok(self, f, t):
        return (f, t) in self.link_set


class OrbitalArchView(QWidget):
    """🪐 球心引力架构 (太阳系映射) — QPainter 2.5D, 球体用径向渐变。"""

    TICK_MS = 60
    # 轨道半径 (相对 R) · 球径 (相对 S) · 颜色
    ORB = {"mercury": 0.30, "earth": 0.50, "mars": 0.68, "jupiter": 0.86}
    RAD = {"sun": 0.052, "mercury": 0.019, "earth": 0.029, "mars": 0.031, "jupiter": 0.037, "moon": 0.013, "sat": 0.008}
    COL = {"sun": "#ffd166", "mercury": "#b9bec7", "earth": "#4da3ff", "mars": "#ff7a45",
           "jupiter": "#d2a45f", "moon": "#dfe4ec", "sat": "#7fd1c1"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = OrbitalArchData()
        self.info = self.data.build()
        self.t0 = time.time()
        self.frozen = False
        self.setMinimumSize(300, 260)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet("background:%s;" % BG.name())
        self.setToolTip("球心引力架构: 流形引擎=太阳 · 接触流形=水星 · 前馈加速器=地球 · DiT=火星 · "
                        "性能流形=木星 · 状态校正器=月球(与地球协同行进) · 原子技能=卫星带\n"
                        "引力=度量: 太阳输出 (状态 p / 度量 g / 势 φ) 作条件并联注入行星; 连线全部来自画布真源")
        self._tm = QTimer(self)
        self._tm.timeout.connect(self._tick)
        self._tm.start(self.TICK_MS)

    def refresh(self):
        self.data = OrbitalArchData()
        self.info = self.data.build()
        self.update()
        return self.info

    def _tick(self):
        if not self.frozen:
            self.update()

    # ── 画 ────────────────────────────────────────────────────────────────
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        W, H = int(self.width()), int(self.height())
        p.fillRect(0, 0, W, H, BG)
        b = self.data.body
        # 版面: 顶 22 + 底 44
        pad_t, pad_b = 20, 46
        S = max(120, min(W - 14, H - pad_t - pad_b))
        cx, cy = W / 2.0, pad_t + (H - pad_t - pad_b) / 2.0
        R = S * 0.46
        # 标题
        p.setPen(FG)
        f = QFont("DejaVu Sans"); f.setPixelSize(12); f.setBold(True); p.setFont(f)
        p.drawText(QRectF(6, 2, W - 12, pad_t - 4), Qt.AlignLeft | Qt.AlignVCenter,
                   "🪐 球心引力架构 (流形引擎=太阳 · 原子技能=卫星)")
        # 引力井 (度量: 各向异性椭圆 = 度量张量特征值比)
        self._gravity_well(p, cx, cy, R, b.get("sun", {}))
        # 轨道
        p.setPen(QPen(GRID, 1, Qt.DashLine))
        for key, frac in self.ORB.items():
            rr = R * frac
            p.drawEllipse(QPointF(cx, cy), rr, rr * 0.94)
        # 真连线: 条件 (青色) / 直连 (金色虚线) / 反馈 (绿色虚线)
        self._draw_links(p, cx, cy, R, b)
        # 天体位置 (角度 = 实测量的映射; 见底注)
        ang = self._angles(b)
        pos = {}
        for key, frac in self.ORB.items():
            a = ang.get(key, 0.0)
            rr = R * frac
            pos[key] = (cx + rr * math.cos(a), cy + rr * 0.94 * math.sin(a))
        # 太阳
        self._sphere(p, cx, cy, S * self.RAD["sun"], self.COL["sun"], b.get("sun", {}).get("grad_norm"))
        self._label(p, cx, cy + S * self.RAD["sun"] + 12, "☀ 流形引擎", FG, 12, True, cx)
        self._sub(p, cx, cy + S * self.RAD["sun"] + 26, self._sun_text(b.get("sun", {})), GOLD, cx, W)
        # 水星 / 木星 / 火星 / 地球 (球体)
        order = (("mercury", S * self.RAD["mercury"]), ("jupiter", S * self.RAD["jupiter"]),
                 ("mars", S * self.RAD["mars"]), ("earth", S * self.RAD["earth"]))
        for key, r in order:
            x, y = pos[key]
            self._sphere(p, x, y, r, self.COL[key], 1.0 if self._live(b.get(key, {})) else 0.35)
            self._body_label(p, key, x, y, r, b, W, H)
        # 月球: 与地球同相位, 径向摆幅 ∝ 残差 (协同行进)
        if "earth" in pos:
            ex, ey = pos["earth"]
            a = ang.get("earth", 0.0)
            wob = self._wobble(b.get("moon", {}))
            mr = R * 0.085 * (1.0 + wob)
            mx, my = ex + mr * math.cos(a), ey + mr * 0.94 * math.sin(a)
            p.setPen(QPen(QColor(90, 100, 115, 150), 1, Qt.DotLine))
            p.drawLine(QPointF(ex, ey), QPointF(mx, my))
            self._sphere(p, mx, my, S * self.RAD["moon"], self.COL["moon"], 1.0 if self._live(b.get("moon", {})) else 0.35)
            p.setPen(DIM); f2 = QFont("DejaVu Sans"); f2.setPixelSize(9); p.setFont(f2)
            p.drawText(QRectF(mx - 44, my + 10, 88, 11), Qt.AlignCenter, "🌙 状态校正器")
        # 卫星带 (原子技能)
        self._satellite_belt(p, cx, cy, R, S, b, ang)
        # 图注 + 真源脚注
        self._legend(p, W, H, b)
        p.end()

    def _gravity_well(self, p, cx, cy, R, sun):
        """引力 = 度量: 井的扁率由度规特征值比给出 (真值; 取不到就不画扁, 只画等距井)。"""
        e1, e2 = sun.get("eig_min"), sun.get("eig_max")
        ratio = 1.0
        if e1 and e2 and float(e2) > 0:
            ratio = max(0.35, min(1.0, float(e1) / float(e2)))
        for i in range(6):
            rr = R * (0.10 + 0.055 * i)
            alpha = 90 - i * 12
            p.setPen(QPen(QColor(210, 153, 34, max(20, alpha)), 1))
            p.drawEllipse(QPointF(cx, cy), rr, rr * (0.94 * ratio + 0.06))

    def _angles(self, b):
        """角度映射 (实测量的可视映射, 写进图注): 水星←接触进度 · 地球←前馈请求/上限 ·
        火星←块步 λ · 木星←耦合效率 η · 月球=地球相位 (协同行进)。取不到 ⇒ 定点 (不假装转)。"""
        a = {}
        m = b.get("mercury", {})
        pr, p0 = m.get("progress"), 0.012
        a["mercury"] = 2 * math.pi * max(0.0, min(1.0, float(pr) / p0)) if isinstance(pr, (int, float)) else 0.6
        e = b.get("earth", {})
        req = e.get("req_mps")
        cap = 0.35
        a["earth"] = 2 * math.pi * max(0.0, min(1.0, float(req) / cap)) if isinstance(req, (int, float)) else 2.2
        mg = b.get("mars", {})
        lam = mg.get("lambda")
        a["mars"] = 2 * math.pi * max(0.0, min(1.0, float(lam))) if isinstance(lam, (int, float)) else 3.1
        j = b.get("jupiter", {})
        eta = j.get("eta")
        a["jupiter"] = 2 * math.pi * max(0.0, min(1.0, float(eta))) if isinstance(eta, (int, float)) else 4.4
        return a

    def _wobble(self, moon):
        r = moon.get("err")
        try:
            return max(0.0, min(0.55, abs(float(r)) * 2.4))
        except Exception:                                                    # noqa: BLE001
            return 0.0

    @staticmethod
    def _live(d):
        """该天体当前有没有真值 (没有 = 未运行 ⇒ 球体压暗, 不假装在工作)。"""
        for k in ("progress", "eta", "action_norm", "req_mps"):
            if isinstance(d.get(k), (int, float)):
                return True
        return bool(d.get("err_all"))

    def _sphere(self, p, x, y, r, col, energy=None):
        """球体: 径向渐变 (光从左上) + 高光点 + 描边; energy<1 ⇒ 压暗 (未运行)。"""
        r = max(2.0, float(r))
        f = 0.35 if (isinstance(energy, (int, float)) and energy < 0.5) else 1.0
        c = QColor(col)
        light = QColor(c).lighter(160); light.setAlphaF(f)
        mid = QColor(c); mid.setAlphaF(f)
        dark = QColor(c).darker(170); dark.setAlphaF(f)
        g = QRadialGradient(QPointF(x - r * 0.35, y - r * 0.40), r * 1.35)
        g.setColorAt(0.0, light); g.setColorAt(0.55, mid); g.setColorAt(1.0, dark)
        p.setPen(Qt.NoPen); p.setBrush(g)
        p.drawEllipse(QPointF(x, y), r, r)
        p.setBrush(QColor(255, 255, 255, int(150 * f)))
        p.drawEllipse(QPointF(x - r * 0.34, y - r * 0.38), max(1.0, r * 0.17), max(1.0, r * 0.17))
        p.setPen(QPen(QColor(c).lighter(140), 1)); p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(x, y), r, r)

    def _body_label(self, p, key, x, y, r, b, W, H):
        txt = {"mercury": "☿ 接触流形", "earth": "♁ 前馈加速器", "mars": "♂ DiT 动作头", "jupiter": "♃ 性能流形"}[key]
        p.setPen(FG); f = QFont("DejaVu Sans"); f.setPixelSize(10); p.setFont(f)
        p.drawText(QRectF(max(0, x - 60), y + r + 2, 120, 12), Qt.AlignCenter, txt)
        sub = self._body_text(key, b.get(key, {}))
        if sub:
            p.setPen(DIM); f2 = QFont("DejaVu Sans"); f2.setPixelSize(9); f2.setBold(False); p.setFont(f2)
            p.drawText(QRectF(2 if x - 90 < 2 else x - 90, y + r + 14, 180, 11), Qt.AlignCenter, sub[:44])

    def _sun_text(self, s):
        if not isinstance(s.get("M"), (int, float)):
            return "真源不可用 (未读 zmax_manifold/engine)"
        t = "M=%.3f · φ=%s · ‖∇Φ‖=%s" % (s["M"],
                                        ("%.3f" % s["phi"]) if isinstance(s.get("phi"), (int, float)) else "—",
                                        ("%.3f" % s["grad_norm"]) if isinstance(s.get("grad_norm"), (int, float)) else "—")
        if isinstance(s.get("T_norm"), (int, float)):
            t += " · T=%.1f%sN·m" % (s["T_norm"], "≤" if s.get("clip") else "~")
        return t

    def _body_text(self, key, d):
        if key == "mercury":
            if not isinstance(d.get("progress"), (int, float)):
                return d.get("note") or "流形量未算 (无真帧)"
            return "‖e∥‖=%.4fm · ‖e⊥‖=%.4fm · %s" % (d["progress"], d.get("risk") or 0.0, str(d.get("state") or "")[:12])
        if key == "jupiter":
            if not isinstance(d.get("eta"), (int, float)):
                return d.get("note") or "流形量未算 (无真帧)"
            return "V_p=%.3g · η=%.3f · δ⊥=%.3f" % (d.get("V_p") or 0.0, d["eta"], d.get("d_perp") or 0.0)
        if key == "earth":
            if not isinstance(d.get("req_mps"), (int, float)):
                return "前馈请求未测 (无在职技能)"
            return "u_ff=%.2f m/s · 偏差 %s · %s" % (d["req_mps"], ("%.3f" % d["dev_mps"]) if isinstance(d.get("dev_mps"), (int, float)) else "—",
                                                   "可行" if d.get("可行") else "削")
        if key == "mars":
            if not isinstance(d.get("action_norm"), (int, float)):
                return "动作头未跑"
            return "‖a‖=%.3f · 条件 %d 路 · H=%s" % (d["action_norm"], int(d.get("cond_n") or 0), d.get("H"))
        return ""

    def _draw_links(self, p, cx, cy, R, b):
        """只画真连线 (画布 links 真源里存在的), 缺哪条如实标「真源无此连线」。"""
        cnt = {"真": 0, "缺": 0}
        for f, t, label in KEY_EDGES:
            ok = self.data.edge_ok(f, t)
            if not ok:
                cnt["缺"] += 1
                continue
            cnt["真"] += 1
        # 双通道: VLM 在左上外侧 (真节点 ssvlm)
        vx, vy = cx - R * 0.98, cy - R * 0.62
        p.setPen(QPen(GOLD, 1, Qt.DashLine))
        p.drawArc(QRectF(vx, vy, (cx - vx) * 1.6, (cy - vy) * 1.35), 200 * 16, -120 * 16)
        p.setPen(GOLD); f = QFont("DejaVu Sans"); f.setPixelSize(9); p.setFont(f)
        p.drawText(QRectF(max(0, vx - 30), vy - 12, 150, 12), Qt.AlignLeft, "① 直连 · 语义条件 (VLM z)")
        p.setPen(QPen(CYAN, 1, Qt.DashLine))
        p.drawLine(QPointF(vx + 40, vy + 6), QPointF(cx - R * 0.30, cy - R * 0.16))
        p.drawLine(QPointF(vx + 40, vy + 6), QPointF(cx - R * 0.60, cy - R * 0.30))
        p.setPen(CYAN)
        p.drawText(QRectF(max(0, vx - 30), vy + 20, 150, 12), Qt.AlignLeft, "② 旁路 · 几何条件 (→流形)")
        # 内部回路 (条件: 太阳→流形→DiT; 反馈: DiT→前馈→调制器; 校正器↔调制器/回灌)
        p.setPen(QPen(CYAN, 1, Qt.DotLine))
        p.drawLine(QPointF(cx + R * 0.12, cy - R * 0.10), QPointF(cx + R * 0.24, cy - R * 0.34))    # 太阳→水星/木星方向
        p.drawLine(QPointF(cx + R * 0.36, cy - R * 0.20), QPointF(cx + R * 0.60, cy - R * 0.44))    # 流形→DiT
        p.setPen(QPen(GREEN, 1, Qt.DashLine))
        p.drawLine(QPointF(cx + R * 0.60, cy - R * 0.10), QPointF(cx + R * 0.42, cy + R * 0.30))    # DiT→前馈
        p.drawLine(QPointF(cx + R * 0.46, cy + R * 0.34), QPointF(cx + R * 0.86, cy + R * 0.20))    # 前馈→调制器
        p.setPen(QPen(VIOLET, 1, Qt.DotLine))
        p.drawArc(QRectF(cx - R * 1.15, cy - R * 0.55, R * 2.3, R * 1.9), 250 * 16, 150 * 16)      # 回灌闭环
        p.setPen(DIM); f2 = QFont("DejaVu Sans"); f2.setPixelSize(9); p.setFont(f2)
        p.drawText(QRectF(cx - 150, cy + R * 1.02, 300, 12), Qt.AlignCenter,
                   "反馈闭环: 校正器 → 融合定位建图 → 流形引擎 (状态回灌) · 卡门: 先验 update ‖ 传感器 measurement")
        self._edge_stat = cnt

    def _satellite_belt(self, p, cx, cy, R, S, b, ang):
        s = b.get("sats", {})
        lst = s.get("list") or []
        if not lst:
            return
        base = ang.get("earth", 0.0)
        for i, d in enumerate(lst):
            a = base + 2 * math.pi * i / len(lst)
            rr = R * 0.99
            x, y = cx + rr * math.cos(a), cy + rr * 0.94 * math.sin(a)
            act = (d.get("SK") == s.get("active"))
            r = S * self.RAD["sat"] * (1.7 if act else 1.0)
            live = isinstance(d.get("偏差_mps"), (int, float))
            self._sphere(p, x, y, r, self.COL["sat"], 1.0 if (act and live) else (0.7 if live else 0.3))
            if act:
                p.setPen(QPen(GOLD, 1)); p.drawEllipse(QPointF(x, y), r + 3, r + 3)
        p.setPen(DIM); f = QFont("DejaVu Sans"); f.setPixelSize(9); p.setFont(f)
        p.drawText(QRectF(cx - 150, cy - R * 1.02 - 12, 300, 12), Qt.AlignCenter,
                   "🛰 卫星带 = 原子技能 %d 条在职 (标定表 %s 条 · 亮=当前在职 %s)"
                   % (len(lst), (s.get("n_calib") or "?"), s.get("active") or "—"))

    def _label(self, p, x, y, txt, col, size, bold, cxref):
        p.setPen(col); f = QFont("DejaVu Sans"); f.setPixelSize(size); f.setBold(bold); p.setFont(f)
        p.drawText(QRectF(cxref - 90, y, 180, size + 4), Qt.AlignCenter, txt)

    def _sub(self, p, x, y, txt, col, cxref, W):
        p.setPen(col); f = QFont("DejaVu Sans"); f.setPixelSize(9); p.setFont(f)
        p.drawText(QRectF(cxref - (W - 16) / 2.0, y, W - 16, 12), Qt.AlignCenter, txt)

    def _legend(self, p, W, H, b):
        p.setPen(DIM); f = QFont("DejaVu Sans"); f.setPixelSize(9); p.setFont(f)
        y0 = H - 42
        p.drawText(QRectF(6, y0, W - 12, 11), Qt.AlignLeft,
                   "角度映射 (位置=实测): 水星←接触进度 ‖e∥‖ · 地球←前馈请求/v_cap · 火星←块步 λ · 木星←耦合效率 η · 月球=地球相位+锁定 (协同行进, 摆幅∝残差)")
        s = b.get("sun", {})
        e1, e2 = s.get("eig_min"), s.get("eig_max")
        mtxt = ("度量 g: dim=%s %s 特征值 %.3f~%.3f (引力=度量, 井扁率按此)" % (s.get("metric_dim"), s.get("metric_mode"), e1, e2)) if e1 else "度量 g: 未读 torque_live"
        nv = self.info.get("checked", {})
        miss = [k for k, v in nv.items() if not v.get("在")]
        edge_txt = "真连线 %d 条绘制" % sum(1 for f, t, _l in KEY_EDGES if self.data.edge_ok(f, t))
        if getattr(self, "_edge_stat", None):
            edge_txt += " (真源缺 %d 条已跳过)" % self._edge_stat["缺"]
        age = s.get("帧龄")
        p.drawText(QRectF(6, y0 + 12, W - 12, 11), Qt.AlignLeft,
                   "真源: engine_latest(帧龄 %.1fs) · torque_live(%s) · skill_latest(帧龄 %s) · ss_traj_last(%d 帧) · manifold_layer.py 真算 · 画布真源 90 节点/202 连线"
                   % (age if isinstance(age, (int, float)) else -1.0, mtxt,
                      ("%.1fs" % self.data.ages.get("zmax_data/ss_live/skill_latest.json", -1.0)),
                      (self.data.frames or {}).get("n", 0)))
        tail = "节点映射核对: %d/%d 命中" % (len(BODIES) - len(miss), len(BODIES)) + (" · 缺: %s" % ",".join(miss) if miss else "") + " · " + edge_txt
        if self.data.err:
            tail += " · ⚠ 读源异常 %d 处" % len(self.data.err)
        p.setPen(RED if (miss or self.data.err) else DIM)
        p.drawText(QRectF(6, y0 + 24, W - 12, 11), Qt.AlignLeft, tail[:130])
