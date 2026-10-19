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
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QRadialGradient, QRegion
from PyQt5.QtWidgets import QSizePolicy, QWidget

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── 字体/量宽缓存 (2026-10-18 实测: paintEvent 每次重绘都为每个文字块新建 QFont+QFontMetrics,
#    单帧几十次 ⇒ 主线程烧满一个核、界面发涩。QFont/QFontMetrics 按 (字号,粗体) 复用时结果等价。)
_FONT_CACHE = {}
_FM_CACHE = {}
_WRAP_CACHE = {}
_FM_W = {}


def _cached_font(size, bold=False):
    k = (int(size), bool(bold))
    f = _FONT_CACHE.get(k)
    if f is None:
        f = QFont("DejaVu Sans")
        f.setPixelSize(int(size))
        f.setBold(bool(bold))
        _FONT_CACHE[k] = f
    return f


def _cached_fm(size, bold=False):
    k = (int(size), bool(bold))
    fm = _FM_CACHE.get(k)
    if fm is None:
        fm = QFontMetrics(_cached_font(size, bold))
        _FM_CACHE[k] = fm
    return fm

# 配色 (与画布/侧栏同族, 暗底)
BG = QColor("#0d1117")
GRID = QColor("#243040")
FG = QColor("#e6edf3")
DIM = QColor("#8b949e")
CYAN = QColor("#39c5cf")
GREEN = QColor("#3fb950")
GOLD = QColor("#d29922")
VIOLET = QColor("#a371f7")
FOOT = QColor("#aebcc8")                      # 2026-10-16 看图: 底部图注原用 DIM(#8b949e) 对比度低
RED = QColor("#f85149")
BLUE = QColor("#4da3ff")


_QUAT_FIELD = None          # 万有引力表的 GravityField 缓存 (太阳系四元数从这里取, 不重复建)


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
    def reload(self):
        """重读全部真源 (2026-10-19 修: 原来只在 __init__ 读一次 ⇒ 500ms 刷新拿到的还是死值,
        「模型停了界面也不变」)。canvas 138KB/2ms, 整体 ≈4ms, 2Hz 重读对主线程无感。"""
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
        self.nodes = {n.get("id"): n for n in (self.canvas.get("nodes") or [])} if self.canvas else {}
        self.links = list(self.canvas.get("links") or []) if self.canvas else []
        self.link_set = {(l.get("f"), l.get("t")) for l in self.links}
        try:
            self.frames = self._frames()
        except Exception:                                                    # noqa: BLE001
            self.frames = None

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
        if not getattr(self, "_no_reload", False):
            self.reload()                     # 2026-10-19: 每拍重读真源 (判据可用 _no_reload 冻结输入)
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
        # 2026-10-16 老倪: 「我看原子技能 SK01~SK08, 那就只是显示 8 个绕地球的卫星」
        _want = ["SK%02d" % i for i in range(1, 9)]
        _by = {d["SK"]: d for d in sats}
        sats = [_by[k] for k in _want if k in _by]        # 真源里这 8 条的 stage/在职/偏差都保留
        self.body["sats"] = {"名": "原子技能", "真源": "skill_phys.json (在职 SK↔段) + skill_latest.json + 标定真源 zmax_skill_physics.json",
                             "list": sats, "active": act.get("SK"), "n": len(sats), "n_calib": n_cal,
                             "sk_ids": [d["SK"] for d in sats]}
        self._compute_state()            # 2026-10-19: 每体运行态 + L2~L5 层状态 (帧龄/在跑/输出)
        # 🔴 2026-10-19 老倪「现在没有运行, 为什么力的方向还在变化?」
        #   根因: 两份力数据每 500ms 从 trace_live/表里重算, 而后台常驻 ss_engine_loop 10Hz 一直在写文件
        #   ⇒ 没点 ▶ 运行, 力的方向照样在转。修法: **未运行一律不重算** (定格在最后一次运行的值),
        #   连 q̂ / S³ 面板 / 姿态轴一起停 —— 数不许比画面更"活"。
        self._build_tok = getattr(self, "_build_tok", 0) + 1
        self.frozen = (not self.running)
        if self.running:
            self._compute_quat()             # 每层归一四元数 (老倪「将四元数显示在太阳系」)
            self._compute_earth_forces()     # 地球的合力/四层分力 (老倪「以地球为主要观察对象」)
        elif not hasattr(self, "fE"):
            self.fE = {}
            self.quat = {}
        return {"checked": checked, "stage": stage, "mf": mf, "mf_note": mf.get("note", "")}

    def _field(self):
        """取万有引力表 (GravityField)。**每次 build 只 reload 一次** ——
        `_compute_quat` 与 `_compute_earth_forces` 共用同一拍, 谁也不许拿上一次 build 的旧表。
        (2026-10-19 老倪「运行后合力怎么没跟着变」: earth_forces 只用了模块级缓存、从不 reload,
         进程活久了合力就永远停在第一次构造的那一帧。)"""
        global _QUAT_FIELD
        import gravity_table as _gt
        _tok = getattr(self, "_build_tok", None)
        if _QUAT_FIELD is None:
            _QUAT_FIELD = _gt.GravityField()
        elif getattr(self, "_field_tok", None) != _tok:
            _QUAT_FIELD.reload()
        self._field_tok = _tok
        return _QUAT_FIELD

    def _compute_earth_forces(self):
        """地球这一刻受的力 (老倪 2026-10-19: 「地球的引力箭头应该大一些…就是前馈加速器的自己的合力,
        是主力; 而太阳力, 行星力, 都是组成地球合力的分力」)。

        口径 (全部来自万有引力表同一拍, 不另算):
          · 合力  F合 = 该行四层矢量的和 (row_resultant) —— 就是**前馈节点这一刻输出方向上的合力**;
          · 分力  L2/L3/L4/L5 = 该行每层的矢量 (L2 = 前馈/主力; L3 = DiT; L4 = 性能流形; L5 = 流形中心);
          · Δ主↔合 = 表里的 dev (°) —— 主力方向与合力方向的夹角; 一致度 = 表里的 coh。
        """
        try:
            import gravity_table as _gt
            _f = self._field()                       # 同一拍 (见 _field)
            st, _lay = _f.dominant_now()
            row = next((r for r in _f.rows if r.get("stage") == st), None) or (_f.rows[0] if _f.rows else None)
            if row is None:
                self.fE = {}
                return
            _names = {"L2": ("前馈加速器 (主力)", "earth"), "L3": ("DiT 动作头", "mars"),
                      "L4": ("性能流形", "jupiter"), "L5": ("流形中心 (太阳)", "sun")}
            comps = []
            for L in ("L5", "L4", "L3", "L2"):
                c = (row.get("cells") or {}).get(L) or {}
                v = c.get("vec")
                if not v:
                    continue
                q, _nn, _ss = _gt._qnorm(c.get("q"))
                nm, bk = _names[L]
                comps.append({"L": L, "name": nm, "body": bk, "vec": [float(x) for x in v],
                              "mag": float(c.get("mag") or 0.0), "q": q, "norm": _nn,
                              "main": (L == row.get("main"))})
            qv = row.get("vec") or [0.0, 0.0, 0.0]
            qq, _qn, _qs = _gt._qnorm(row.get("q"))
            self.arrow_px = float(getattr(_f, "arrow_px", 300.0) or 300.0)
            self.arrow_ref = float(getattr(_f, "arrow_ref", 1.0) or 1.0)
            self.arrow_max = float(getattr(_f, "arrow_max", 168.0) or 168.0)
            self.alpha = float(getattr(_f, "alpha", 1.0) or 1.0)
            self.cap_level = str(getattr(_f, "cap_level", "") or "")
            self.layers_on = dict(getattr(_f, "layers_on", {}) or {})
            self.fE = {"stage": st, "vec": [float(x) for x in qv], "mag": float(row.get("mag_res") or 0.0),
                       "q": qq, "norm": _qn, "s2": _qs, "dev": float(row.get("dev") or 0.0),
                       "coh": float(row.get("coh") or 0.0), "comps": comps,
                       "day": bool(getattr(_f, "running", False))}
        except Exception as _e:                                                  # noqa: BLE001
            self.fE = {}
            self.fE_err = str(_e)

    def _compute_quat(self):
        """每层 (L2~L5) 的**归一四元数** q̂ —— 取万有引力表该层**列合力**的力四元数再归一。

        为什么归一: 表里的"力四元数" = (|F|/u_ref, Fx/u_ref, Fy/u_ref, Fz/u_ref), 故意不归一(要能逐位
        对账); 而"状态方向"要的是 S³ 上的单位四元数 ⇒ 这里给 q̂ = q/‖q‖ (各项平方和 = 1, 矢量部分 =
        该层合力方向), ‖q‖ 另存 (那是力度, 悬停卡里给)。
        """
        try:
            import gravity_table as _gt
            _f = self._field()                       # 同一拍 (见 _field)
            self.quat = {}
            for _L in ("L5", "L4", "L3", "L2"):
                _q, _coh = _f.col_resultant(_L)
                _u, _nn, _ss = _gt._qnorm(_q)
                _ok = bool(_nn and _nn > 1e-9)
                self.quat[_L] = {"q": (_u if _ok else None), "norm": _nn, "s2": _ss,
                                 "coh": _coh, "live": bool(getattr(_f, "running", False))}
        except Exception as _e:                                                  # noqa: BLE001
            self.quat = {}
            self.quat_err = str(_e)

    # ── 2026-10-19 老倪: 「太阳系窗口是观察 L2~L5 模型的主要窗口, 要反映模型实际状态」──
    #   口径: 每体只认**它自己那一份真源**的 ts; 没有 ts 就用文件 mtime; 都没有 ⇒ 报"缺失"。
    #   不许用"引擎在跑"去冒充"这一层在跑" (那是假的: L2/L3/L4 可能根本没被调用)。
    STATE_TTL_LIVE = 2.5      # ≤2.5s = 在跑
    STATE_TTL_STALE = 60.0    # ≤60s  = 陈旧 (能看到, 但不能当实时)

    @staticmethod
    def _age_of(path):
        try:
            return max(0.0, time.time() - os.path.getmtime(path))
        except Exception:                                                    # noqa: BLE001
            return None

    @staticmethod
    def _state_of(age):
        if age is None:
            return "off", "无真源"
        if age <= OrbitalArchData.STATE_TTL_LIVE:
            return "live", "在跑"
        if age <= OrbitalArchData.STATE_TTL_STALE:
            return "stale", "陈旧"
        return "off", "离线"

    def _layers_live(self):
        """L5/L4/L3/L2 逐层: 最近一次**真调用**的 ok/src/ms + 帧龄 (真源 layer_calls.jsonl 末行)。
        这个文件是引擎每拍落一条的调用流水; 停写 ⇒ 界面必须显示"陈旧/离线", 不能拿旧数当在跑。"""
        p = os.path.join(self.root, "zmax_data", "ss_live", "layer_calls.jsonl")
        rec = None
        try:
            with open(p, "rb") as f:                       # 只读尾部 8KB, 47MB 的日志不整读
                f.seek(0, os.SEEK_END)
                n = f.tell()
                f.seek(max(0, n - 8192))
                tail = f.read().decode("utf-8", "replace").strip().split("\n")
            for line in reversed(tail):
                try:
                    rec = json.loads(line)
                    break
                except Exception:                                          # noqa: BLE001
                    continue
        except Exception:                                                  # noqa: BLE001
            rec = None
        age = None
        if rec and isinstance(rec.get("ts"), (int, float)):
            age = max(0.0, time.time() - float(rec["ts"]))
        if age is None:
            age = self._age_of(p)
        k, txt = self._state_of(age)
        out = {"age": age, "k": k, "txt": txt, "cycle": (rec or {}).get("cycle"),
               "pipe_calls": (rec or {}).get("pipe_calls"), "src": p}
        for name in ("L5", "L4", "L3", "L2"):
            d = (rec or {}).get("layers", {}).get(name) or {}
            out[name] = {"ok": d.get("ok"), "src": d.get("src"), "ms": d.get("ms")}
        return out

    def _ui_run(self):
        """(是否在跑, 说明) —— 真源 = 控制台点 ▶ 运行 时写的 zmax_data/ss_live/ui_run.json。
        为什么不用文件新鲜度: tools/ss_engine_loop.py / ss_fw_trace_pub.py 是**常驻后台**,
        engine_latest/torque_live 一直在写 ⇒ 没点运行也会"看着在跑"(老倪 2026-10-19 指出的)。
        pid 不在了也判没在跑 (崩溃/被杀不留假在跑)。"""
        p = os.path.join(self.root, "zmax_data", "ss_live", "ui_run.json")
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except Exception:                                                    # noqa: BLE001
            return False, "未点 ▶ 运行"
        if not d.get("running"):
            return False, "未运行 (没点 ▶ 运行)"
        try:
            os.kill(int(d.get("pid") or 0), 0)
        except Exception:                                                    # noqa: BLE001
            # 控制台重启过 ⇒ pid 残留; 只要 L5 闭环独立进程还在跑, 就算在跑 (档位 L5)
            try:
                _l5p = os.path.join(self.root, "zmax_data", "l5_loop", "state.json")
                if os.path.isfile(_l5p) and (time.time() - os.path.getmtime(_l5p)) < 900:
                    if str((json.load(open(_l5p, encoding="utf-8")) or {}).get("status") or "").lower() == "running":
                        return True, "运行中 (L5 闭环独立进程)"
            except Exception:                                                # noqa: BLE001
                pass
            return False, "控制台已退出 (残留标记)"
        return True, "运行中 (pid %s)" % d.get("pid")

    def _compute_state(self):
        root = self.root
        ages = {
            "engine": self._age_of(os.path.join(root, "zmax_data", "ss_live", "engine_latest.json")),
            "torque": self._age_of(os.path.join(root, "zmax_data", "ss_live", "torque_live.json")),
            "skill":  self._age_of(os.path.join(root, "zmax_data", "ss_live", "skill_latest.json")),
            "skerr":  self._age_of(os.path.join(root, "zmax_data", "ss_live", "skill_error.json")),
        }
        # 体 ← 它自己的真源 (太阳: 引擎+扭矩两条都新鲜才算在跑; 水星/木星: 吃引擎这一帧的位姿)
        src = {"sun": ("engine", "torque"), "mercury": ("engine",), "jupiter": ("engine",),
               "mars": ("engine",), "earth": ("skill",), "moon": ("skerr",), "sats": ("skill",)}
        self.running, self.run_note = self._ui_run()
        for body, keys in src.items():
            d = self.body.get(body)
            if not isinstance(d, dict):
                continue
            _ags = [ages[k] for k in keys if ages.get(k) is not None]
            age = max(_ags) if _ags else None
            k, txt = self._state_of(age)
            if not self.running:
                # 2026-10-19 老倪: 「还没点运行, 应该没有力」⇒ 一律未运行 (文件再新也是后台常驻写的)
                k, txt = "off", "未运行"
            d["st"] = {"k": k, "txt": txt, "age": age,
                       "src": " + ".join("zmax_data/ss_live/%s.json" % x for x in
                                         {"engine": ["engine_latest"], "torque": ["torque_live"],
                                          "skill": ["skill_latest"], "skerr": ["skill_error"]}[keys[0]])}
        # 驱动扭矩口径 (老倪问过: 主参数 M 与模型张量是否一致) —— 直接把口径写在视图上, 不让人猜
        tq = self.torque or {}
        self.drv = {
            "src": str(tq.get("source") or "")[:400],
            "x_source": str(tq.get("x_source") or ""),
            "clip": bool(tq.get("clipped")),
            "T": tq.get("torque_norm"), "T_max": tq.get("t_max"),
            "model_tensor": bool(tq.get("model_tensor") or tq.get("tensor_src")),
        }
        self.layers = self._layers_live()
        if not self.running:
            self.layers["k"], self.layers["txt"] = "off", "未运行 (没点 ▶ 运行)"


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
    """🪐 球心引力架构 (太阳系映射) —— QPainter 2.5D 真球体 + 可旋转可缩放 + 真源力连线。

    老倪 2026-10-16 反馈 (逐条落实):
      ① 「这些卫星都是原子技能, 应该围绕在地球周围, 不能散落在太阳系」
         ⇒ 原子技能 = **地球的卫星群** (绕地球的闭合小轨道, 与地球同相位公转); 月球(状态校正器)
            在稍外一圈 —— 也是绕地球, 两者不重叠 (内 0.055R / 外 0.085R)。
      ② 「这个图需要能够用鼠标旋转放大, 可以操作」
         ⇒ 左键拖动 = 旋转 (偏航 + 俯仰, 俯仰限幅), 滚轮 = 缩放 (0.55~2.4 倍), 双击 = 复位;
            全部是**真三维变换** (轨道平面绕 X 轴俯仰 + 绕 Z 轴偏航后正交投影), 不是画椭圆凑。
      ③ 「球与球之间的连线, 要做好规划, 相当于 模型节点之间的力的相互作用, 要能体现出,
         有相互作用, 就显示连线」
         ⇒ 连线**全部来自画布 links 真源** (画布 state_space_obs.json 的 202 条连线):
            主体↔主体 的每一条真边都画; 主体↔体系外直接邻居 的边画到外圈小星点 (不隐形、也不编造)。
            没有真连线的一律不画 (缺哪条在脚注里可核)。
      ⑤ 「现在的连线太多了, 而且实现不好看。背景的圆形轨道也要体现出, 直线实线改成虚线,
         用不同的颜色表示不同的信号, 有就显示, 没有就不显示, 注意柔顺显示。显示要映射到实际的
         代码逻辑, 每次显示都要从代码中触发。球体只保留 太阳/木星/火星/水星/地球/月球 +
         地球上绕转的原子技能 SK01~SK08 (8 颗), 其它球体删掉」(2026-10-16)
         ⇒ 本类改动: ① 只画 **主体↔主体** 的真连线 (体系外 38 条 + 外圈灰点全部删除);
            ② 轨道环单独画亮 (4 条行星轨道 + 地球卫星环), 虚线随视角一起变换;
            ③ **一条实线都不留** —— 全部虚线 (慢速相位流动, 柔顺不闪);
            ④ 线色 = 信号种类 (青=几何条件 · 金=性能/集合条件 · 绿=动作/前馈 · 紫=反馈/回灌);
            ⑤ **信号有值才画** (`_signal_ok`: 值由真节点函数当场算出, 缺值 ⇒ 那条线不画);
            ⑥ 显示与代码同源: 线集来自画布 links 真源, 每条线的"有/无"由 `body` 里对应真源键
               决定 (见 SIG_OF 的 file:line 注释), 不在视图里编一张静态表;
            ⑦ 卫星 = 真源在职技能表的 SK01~SK08 各一颗 (逐颗标 SK 号), 亮球=在职, 金圈=当前在职。

      ④ 「连线要适合人眼睛的观察, 不要太细, 不要高频率闪烁, 不要很快消失。要注意平顺柔和」
         ⇒ 每条线两遍画 (外发光 6px 半透明 + 实芯 2.2px); 反馈线用**慢速流动**虚线 (相位连续推进,
            不会闪、不会消失); 全图**不做任何透明度脉冲/闪烁动画**, 帧间只做平顺位移。
    """

    TICK_MS = 60
    LH = 27                              # 行高 (2026-10-19 第四次放大: 24→27, 右栏字号 17→20, 图注 13→14)
    # 轨道半径 (相对 R) · 球径 (相对 S) · 颜色
    ORB = {"mercury": 0.30, "earth": 0.50, "mars": 0.68, "jupiter": 0.86}
    # 2026-10-19 老倪「看不到」: 球径整体放大 ~25% (300px 高时地球只有 5px ⇒ 现在 7~8px)
    RAD = {"sun": 0.060, "mercury": 0.024, "earth": 0.032, "mars": 0.038, "jupiter": 0.045,
           "moon": 0.014, "sat": 0.0068}
    # 2026-10-19 老倪「把文字与球体的连线去掉, 太乱了; 有颜色对应就可以了」⇒ 颜色成为唯一对应关系,
    #   必须互相可区分: 水星改冷灰 (原 #b9bec7 与月球 #dfe4ec 撞), 木星改青铜 (原 #d2a45f 与太阳 #ffd166 撞)。
    COL = {"sun": "#ffd166", "mercury": "#8d99a8", "earth": "#4da3ff", "mars": "#ff7a45",
           "jupiter": "#c98f3c", "moon": "#dfe4ec", "sat": "#7fd1c1", "ext": "#8b949e"}
    # 卫星群/月球 绕地球的半径 (相对 R) —— 原子技能在内, 月球在外 (不叠)
    # 2026-10-16 看图逐项校正 (都为"账算得出来"的量, 判据 K2/K3 逐条卡):
    #   · 卫星圈必须整体在地球球体之外: 投影后的最小地-卫距 ≥ r_earth + r_sat (+4px 余量)
    #   · 月球必须在卫星圈之外: 地-月距 ≥ 卫星圈半径 + r_sat + r_moon
    SAT_R = 0.120      # 2026-10-19: 0.116→0.120, 卫星环离地月线 5.9→6.5px (判据 O3 要 ≥6)
    MOON_R = 0.182
    BASE_INCL = 0.26                     # 轨道面基础倾角 (视角立体感, 真三维变换的一部分)

    def __init__(self, parent=None, root=None):
        super().__init__(parent)
        self.root = root
        self.data = OrbitalArchData(root) if root else OrbitalArchData()
        self.info = self.data.build()
        self.yaw = 0.0                    # 偏航 (拖动左右)
        self.pitch = 0.42                 # 俯仰 (拖动上下, 限幅 ±1.15)
        self.zoom = 1.0                   # 缩放 (滚轮 0.55~2.4)
        self._drag = None
        self._phase = 0.0                 # 虚线流动相位 (连续推进, 慢)
        self._grids = []                  # 轨道圆采样 (平面坐标, 单位 R)
        for _k in ("mercury", "earth", "mars", "jupiter"):
            self._grids.append([(self.ORB[_k] * math.cos(t / 72.0 * 2 * math.pi),
                                 self.ORB[_k] * math.sin(t / 72.0 * 2 * math.pi)) for t in range(73)])
        self._ext = []                    # 2026-10-16 老倪: 体系外的球/灰点全部删掉 (只留 7 类主体)
        self._leaders = []                # 被挤远的文字块 → 引线 (归属可辨)
        self._edges = self._build_edges()
        self.setMinimumSize(300, 260)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet("background:%s;" % BG.name())
        self.setCursor(Qt.OpenHandCursor)
        self.setMouseTracking(True)
        self.setToolTip("🪐 球心引力架构 · 左键拖动=旋转 · 滚轮=缩放 · 双击=复位\n"
                        "球与球的连线全部来自画布真源 (力的相互作用: 有真连线才画)\n"
                        "太阳=流形引擎 · 水星=接触流形 · 地球=前馈加速器(+原子技能卫星群) · "
                        "火星=DiT · 木星=性能流形 · 月球=状态校正器")
        self._tm = QTimer(self)
        self._tm.timeout.connect(self._tick)
        self._tm.start(self.TICK_MS)
        # 2026-10-19 老倪: 「太阳系窗口是观察 L2~L5 模型的主要窗口, 要反映模型实际状态」
        #   原来只在 __init__ 里 self.data.build() 一次 ⇒ 屏上数字是"打开那一刻"的死值, 模型停了也不变。
        #   现在每 500ms 重读真源 (build ≈1ms), 窗口不可见时跳过。
        self._tm_data = QTimer(self)
        self._tm_data.timeout.connect(self.refresh)
        self._tm_data.start(500)

    # ── 真源: 力的相互作用 (画布 links) ──────────────────────────────────────
    @staticmethod
    def _ext_nodes():
        """2026-10-16 老倪: 「其它球体删掉」⇒ 体系外节点一律不上图 (保留空实现供旧调用)。"""
        return []

    @staticmethod
    def _kind(label):
        """按**真源连线 label** 归类 (力/条件的种类; 不猜)。"""
        t = str(label or "")
        if any(k in t for k in ("反馈", "回灌", "闭环", "z_k", "校正")):
            return "feedback"
        if any(k in t for k in ("前馈", "action", "u_ff", "标杆", "动作块", "动作指令")):
            return "drive"
        if any(k in t for k in ("潜空间 z", "语义", "VLM", "视觉")):
            return "semantic"
        if any(k in t for k in ("条件", "几何", "流形", "代价", "势能", "度规", "指令")):
            return "condition"
        return "misc"

    # 每条 主体↔主体 连线 ↔ **真源信号** (值在场上由真节点函数算出, 不在视图里编表):
    #   ss_mani_eng→ssmani_c : ContactManifold.decompose (manifold_layer.py:116) → progress
    #   ss_mani_eng→ssmani_p : PerformanceManifold.evaluate (manifold_layer.py:181) → V_p
    #   ssmani_c/ssmani_p→ssdec : 条件注入 (state_space_action_head.py:52 forward) + 动作模 action_norm
    #   ssdec→ss_ff           : 动作块 → 前馈快路径 (parallel.py:143 forward) → req_mps
    SIG_OF = {
        ("ss_mani_eng", "ssmani_c"): ("geom", (("mercury", "progress"),)),
        ("ss_mani_eng", "ssmani_p"): ("perf", (("jupiter", "V_p"),)),
        ("ssmani_c", "ssdec"): ("geom", (("mercury", "progress"), ("mars", "action_norm"))),
        ("ssmani_p", "ssdec"): ("perf", (("jupiter", "V_p"), ("mars", "action_norm"))),
        ("ssdec", "ssff"): ("drive", (("earth", "req_mps"),)),
    }

    def _signal_ok(self, e, b):
        """「有就显示, 没有就不显示」: 该线依赖的真源信号**全部有值**才画 (缺值 ⇒ 不画, 不画假线)。"""
        sig = e.get("sig") or ()
        for bk, fk in sig:
            v = (b.get(bk) or {}).get(fk)
            if not isinstance(v, (int, float)):
                return False
        return True

    def _build_edges(self):
        """**只画主体↔主体**的真连线 (2026-10-16 老倪: 连线太多/其它球体删掉)。

        每条边附 `sig` = 该相互作用依赖的真源信号键 (见 SIG_OF 的 file:line 注释),
        绘制前用 `_signal_ok` 门控 —— 有就显示、没有就不显示, 且显示由真源代码驱动。
        """
        body_ids = {b[1] for b in BODIES}
        out = []
        for l in self.data.links:
            f, t = l.get("f"), l.get("t")
            if not f or not t:
                continue
            fb, tb = f in body_ids, t in body_ids
            if not (fb and tb):                       # 体系外一律不画 (删掉其它球体)
                continue
            sig, keys = self.SIG_OF.get((f, t), (None, ()))
            out.append({"f": f, "t": t, "body_body": True, "label": str(l.get("label") or ""),
                        "kind": self._kind(l.get("label")), "sig": keys,
                        "sig_kind": sig or self._kind(l.get("label"))})
        out.sort(key=lambda e: (not e["body_body"], e["f"], e["t"]))
        # 同一对节点在画布里可能有多条重边 (不同 label) —— 力只画一次, 不叠线 (老倪: 平顺柔和)
        seen, uniq = set(), []
        for e in out:
            k = (e["f"], e["t"])
            if k in seen:
                continue
            seen.add(k)
            uniq.append(e)
        return uniq

    def interactions(self):
        """给判据/自检用: 当前**真画出来**的相互作用清单 (真源边 + 信号门控通过)。"""
        b = self.data.body
        return [e for e in self._edges if self._signal_ok(e, b)]

    # ── 交互 ────────────────────────────────────────────────────────────────
    def mousePressEvent(self, e):
        _cr = getattr(self, "_chip_rect", None)
        if _cr and _cr[0] <= e.x() <= _cr[0] + _cr[2] and _cr[1] <= e.y() <= _cr[1] + _cr[3]:
            self._focus = not getattr(self, "_focus", False)     # 🌍 地球视角 / ☀ 太阳系视角
            self.update()
            return
        self._drag = (e.x(), e.y())
        self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if self._drag is None:
            self._hover(e.x(), e.y())          # 2026-10-19: 悬停读数 (没拖动时才做, 拖动仍是旋转)
            return
        dx = e.x() - self._drag[0]
        dy = e.y() - self._drag[1]
        self._drag = (e.x(), e.y())
        self.yaw += dx * 0.012
        self.pitch = max(-1.15, min(1.15, self.pitch + dy * 0.008))
        self.update()

    def mouseReleaseEvent(self, e):
        self._drag = None
        self.setCursor(Qt.OpenHandCursor)

    def mouseDoubleClickEvent(self, e):
        self.reset_view()

    def _set_ttp(self, txt):
        """设悬停提示, **同一段文字不重复设**。

        🐛 2026-10-19 老倪「右侧有个 q合 未运行, 一直在闪烁」: `mouseMoveEvent` 每动一下就
        `setToolTip(...)` 一次 (鼠标在右栏上 = 没击中球, 也会设那句通用提示) ⇒ Qt 把提示条
        反复弹出/收回, 正好压在右栏 q̂ 那两行上, 看着就是"那行在闪"。改成同文案不重设。
        """
        if txt == getattr(self, "_ttp", None):
            return
        self._ttp = txt
        self.setToolTip(txt)

    # ── 2026-10-19: 悬停 = 读数卡 (太阳系窗口要能"看模型实际状态", 不只靠标签上的两行) ──
    def _hover(self, mx, my):
        """鼠标落在某颗球上 ⇒ 土 tooltip 给出: 名/真源/运行态/帧龄/输出量。
        数据全部来自 self.data.body (每 500ms 重读真源), 视图自己不攒数、不猜。"""
        W, H, S, cx, cy, R = self._geom()
        pos = self.positions(cx, cy, R)
        hit, best = None, 9.0
        for k in ("sun", "mercury", "earth", "mars", "jupiter", "moon"):
            x, y, _z = pos[k]
            d = math.hypot(mx - x, my - y) - S * self.RAD[k]
            if d < best:
                hit, best = k, d
        for _x, _y, _z, _sk in pos.get("_sat", []):
            d = math.hypot(mx - _x, my - _y) - S * self.RAD["sat"] - 2.0
            if d < best:
                hit, best = ("sat", _sk), d
        if hit is None:
            self._set_ttp("")          # 没击中球 ⇒ 不弹提示条 (它会盖住右栏读数)
            return
        b = self.data.body
        if isinstance(hit, tuple):
            _sk = hit[1]
            _d = next((x for x in (b.get("sats", {}).get("list") or []) if x.get("SK") == _sk), {})
            _st = (b.get("sats", {}).get("st") or {})
            self._set_ttp("🛰 %s · 原子技能\n运行态: %s (帧龄 %s)\n段: %s · 在职 %s · 可行 %s · 偏差 %s m/s\n真源: %s" % (
                _sk, _st.get("txt"), self._fmt_age(_st.get("age")), _d.get("stage"),
                _d.get("在职"), _d.get("可行"), _d.get("偏差_mps"), b.get("sats", {}).get("真源")))
            return
        d = b.get(hit, {}) or {}
        stt = d.get("st") or {}
        rows = ["%s %s" % (self._st_glyph(d), d.get("名") or hit),
                "运行态: %s · 帧龄 %s" % (stt.get("txt") or "—", self._fmt_age(stt.get("age")))]
        # 四元数 (该层的归一四元数 = 状态方向): 悬停就能拿到四个数 + ‖q‖ (力度) + 口径说明
        _Lq = {"sun": "L5", "jupiter": "L4", "mars": "L3", "earth": "L2"}.get(hit)
        if _Lq:
            _qd = (getattr(self.data, "quat", {}) or {}).get(_Lq) or {}
            _q = _qd.get("q")
            if _q:
                rows.append("q̂%s = %+.3f %+.3f %+.3f %+.3f  (单位四元数, 平方和=%.6f)" % (_Lq, _q[0], _q[1], _q[2], _q[3], _qd.get("s2") or 0.0))
                rows.append("‖q‖=%.2f (力四元数模长=力度) · 口径: 万有引力表该层列合力 → 归一 · 一致性 %.2f" % (
                    _qd.get("norm") or 0.0, _qd.get("coh") or 0.0))
            else:
                rows.append("q̂%s 未算 (该层此刻无列合力)" % _Lq)
        for k, lab in (("M", "M 主参数"), ("phi", "φ 势能"), ("grad_norm", "‖∇Φ‖"),
                       ("T_norm", "T 扭矩 N·m"), ("progress", "接触进度"), ("V", "V 接触势"),
                       ("V_p", "V_p 性能势"), ("eta", "η 效率"), ("req_mps", "前馈请求 m/s"),
                       ("action_norm", "动作范数"), ("confidence", "置信度"), ("err", "残差")):
            v = d.get(k)
            if isinstance(v, (int, float)):
                rows.append("%s: %.4g" % (lab, v))
        if d.get("state"):
            rows.append("状态: %s" % d["state"])
        _ROLE = {"sun": "流形中心 (约束由度量 M 定; 意图→势场 φ)",
                 "mercury": "几何条件通道 (接触流形)", "earth": "快响应 MLP (L2 小动作/局部微调)",
                 "mars": "动作生成器 DiT (大动作/动作块)", "jupiter": "集合条件 (性能流形 η/V_p)",
                 "moon": "状态校正 (残差/反馈)"}
        rows.append("结构对应: %s" % _ROLE.get(hit, "—"))
        rows.append("节拍: 控制环 10Hz (一拍 0.1s) · 公转相位 = 该层实测量映射, 不做时间积分")
        rows.append("真源: %s" % (d.get("真源") or "—"))
        self._set_ttp("\n".join(rows))

    @staticmethod
    def _fmt_age(a):
        if not isinstance(a, (int, float)):
            return "—"
        return ("%.1fs" % a) if a < 60 else ("%.1fmin" % (a / 60.0) if a < 3600 else "%.1fh" % (a / 3600.0))

    def wheelEvent(self, e):
        try:
            steps = e.angleDelta().y() / 120.0
        except Exception:                                                    # noqa: BLE001
            steps = 1.0
        self.zoom = max(0.55, min(2.4, self.zoom * (1.12 ** steps)))
        self.update()

    def reset_view(self):
        self.yaw, self.pitch, self.zoom = 0.0, 0.42, 1.0
        self.update()

    def refresh(self):
        self.data = OrbitalArchData(self.root) if self.root else OrbitalArchData()
        self.info = self.data.build()
        self._ext = self._ext_nodes()
        self._edges = self._build_edges()
        self.update()
        return self.info

    def _tick(self):
        # 只推进"虚线流动相位" (慢, 连续) —— 不做透明度脉冲 (老倪: 不要高频闪烁)
        import time as _t
        _now = _t.monotonic()
        _dt = min(0.25, max(0.01, _now - getattr(self, "_t_prev", _now - self.TICK_MS / 1000.0)))
        self._t_prev = _now
        self._dt = _dt
        # 2026-10-19 老倪「太阳系所有显示禁止跳跃」: 凡是跟数据走的量, 一律低通, 不许阶跃。
        #   月球轨道半径 (残差) / 连线偏移 / 连线出现消失 (透明度) / 文字块位置 全部平滑。
        # 2026-10-19 老倪: 「前馈加速模型运行 ⇒ 地球有高亮 + 柔顺闪烁; 依次类推, 每个模型推理都有对应」
        #   _live_s[key] = 该层"此刻在推理"的平滑度 (live→1 / stale→0.35 / off→0), 低通 ⇒ 不硬闪;
        #   _pulse_t = 呼吸/外扩环的时间基 (只随帧推进, 不跟数据跳)。
        if not hasattr(self, "_live_s"):
            self._live_s = {}
        for _k2, _d2 in (self.data.body or {}).items():
            if _k2 in ("sats",):
                continue
            _s2 = ((_d2 or {}).get("st") or {}).get("k")
            _tg = {"live": 1.0, "stale": 0.35}.get(_s2, 0.0)
            _cv = self._live_s.get(_k2, _tg)
            self._live_s[_k2] = _cv + (_tg - _cv) * min(1.0, _dt * 2.4)
        try:                                     # 原子技能 (卫星): 有实测偏差 ⇒ 视为在推理
            _sl = ((self.data.body.get("sats") or {}).get("list") or [])
            _tgS = 1.0 if (getattr(self.data, "running", False) and any(
                isinstance(x.get("偏差_mps"), (int, float)) for x in _sl)) else 0.0
        except Exception:                                                        # noqa: BLE001
            _tgS = 0.0
        _cvS = self._live_s.get("sat", _tgS)
        self._live_s["sat"] = _cvS + (_tgS - _cvS) * min(1.0, _dt * 2.4)
        _wt = self._wobble_raw(self.data.body.get("moon", {}))
        self._wob_s = _wt if getattr(self, "_wob_s", None) is None else \
            self._wob_s + (_wt - self._wob_s) * min(1.0, _dt * 3.0)
        if getattr(self.data, "running", False):
            self._phase = (self._phase + 0.18 * (_dt / (self.TICK_MS / 1000.0))) % 12.0
            self._pulse_t = getattr(self, "_pulse_t", 0.0) + _dt
            self._advance(self.TICK_MS / 1000.0)  # 行星连续公转 (积分, 不按数据跳相位)
        # ⏸ 未运行: 相位/公转/呼吸全部不动 —— 老倪「没运行, 为什么力的方向还在变化?」
        self.update()

    def refresh(self):
        """重读真源 (每 500ms): 天体运行态 / L2~L5 层状态 / 扭矩口径 都会跟着变。"""
        if not self.isVisible():
            return
        try:
            self.info = self.data.build()
        except Exception:                                                    # noqa: BLE001
            return
        self.update()

    # ── 3D: 平面坐标 → 屏幕 (绕 Z 偏航 + 绕 X 俯仰 + 正交投影 + 深度微缩) ────
    def _proj(self, x, y, z, cx, cy, R, incl=None):
        inc = self.BASE_INCL if incl is None else incl
        # 先按轨道面倾角把平面转进三维
        y2 = y * math.cos(inc)
        z2 = y * math.sin(inc) + z
        # 偏航 (绕 Z)
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        x3, y3 = x * c - y2 * s, x * s + y2 * c
        # 俯仰 (绕 X)
        cp, sp = math.cos(self.pitch), math.sin(self.pitch)
        y4, z4 = y3 * cp - z2 * sp, y3 * sp + z2 * cp
        sc = R * self.zoom * (1.0 + 0.10 * z4)          # 近大远小
        return cx + x3 * sc, cy + y4 * sc, z4

    def _geom(self):
        W, H = int(self.width()), int(self.height())
        # 🪐 2026-10-16 老倪: 「太阳系窗口增加高度」—— 高度由页面给, 但**图本身**还能再放大:
        #   上留白 20→8, 脚注留白 12→6, 半径系数 0.46→0.50 ⇒ 同样高度下半径 +~17% (实测直径 +~28px)。
        pad_t = 8
        # 2026-10-19 老倪「不要来回跳」: 图注行数会随数据变 (缺源多一行/少一行) ⇒ 半径 S 跟着变,
        #   整张图会"呼吸"一下。这里加滞回: 行数与上次差 ≥2 才重算, 平时钉住 ⇒ 尺度稳定。
        _n = len(self._foot_lines(W))
        _prev = getattr(self, "_foot_n", None)
        if _prev is None or abs(_n - _prev) >= 2:
            self._foot_n = _n
            _prev = _n
        pad_b = 6 + self.LH * (_prev or _n)
        # 2026-10-19 老倪「文字描述不要飘来漂去, 都靠右侧显示, 不要动」:
        #   右侧让出固定文字栏 (_col_w), 系统圆心左移 ⇒ 文字永远不进系统区, 也就不用避让/换位。
        _col_w = self._col_w(W) if self.RIGHT_COL else 0
        # 🪟 2026-10-19 老倪「合力的小窗口太小, 根本看不到」: 卡片放大到 350×168 之后必须**占位**,
        #   否则地球/火星会落在卡片底下 (实测 earth 316,293 就在卡内)。这里给左侧留走廊。
        _card = self._s3_w(W) + 16.0
        _gut = _card if self._s3_visible(W) else 0.0
        S = max(120, min(W - _col_w - _gut - 14, H - pad_t - pad_b))
        cx = _gut + (W - _col_w - _gut) / 2.0
        cy = pad_t + (H - pad_t - pad_b) / 2.0
        _R = S * 0.58
        if self.RIGHT_COL and _gut > 0:
            # 轨道左缘不许钻进左下卡 (卡是实底, 会切掉一段轨道): 先把半径压到"卡右缘↔右栏"之间放得下,
            #   再把圆心摆到卡右缘右侧 (右移而不是硬夹, 否则 R 不变时一定会压卡)
            _cl = 10.0 + self._s3_w(W) + 10.0                  # 卡右缘
            _avail = (W - _col_w - 6.0) - _cl - 10.0           # 卡右缘到右栏左缘的净宽
            _R = min(_R, max(90.0, _avail / 2.0))
            cx = _cl + _R + 5.0
        # 🔴 铁律: 球**永远不许**画进右侧文字栏 (窄窗时上面那两个约束都会失效)
        _free = (W - _col_w - _gut - 16.0) / 2.0
        if _R > _free:
            _R = max(60.0, _free)
            cx = _gut + (W - _col_w - _gut) / 2.0
        return W, H, S, cx, cy, _R      # 🪐 再放大一档 (老倪「太阳系增加高度」)

    def _angles_static(self, b):
        """角度映射 (实测量 → 公转相位, 写进图注): 水星←接触进度 · 地球←前馈请求/上限 ·
        火星←块步 λ · 木星←耦合效率 η · 月球/卫星=地球相位 (协同)。取不到 ⇒ 定点 (不假装转)。"""
        a = {}
        m = b.get("mercury", {})
        pr = m.get("progress")
        a["mercury"] = 2 * math.pi * max(0.0, min(1.0, float(pr) / 0.012)) if isinstance(pr, (int, float)) else 0.6
        e = b.get("earth", {})
        req = e.get("req_mps")
        a["earth"] = 2 * math.pi * max(0.0, min(1.0, float(req) / 0.35)) if isinstance(req, (int, float)) else 2.2
        mg = b.get("mars", {})
        lam = mg.get("lambda")
        a["mars"] = 2 * math.pi * max(0.0, min(1.0, float(lam))) if isinstance(lam, (int, float)) else 3.1
        j = b.get("jupiter", {})
        eta = j.get("eta")
        a["jupiter"] = 2 * math.pi * max(0.0, min(1.0, float(eta))) if isinstance(eta, (int, float)) else 4.4
        return a

    PH_KEYS = ("mercury", "earth", "mars", "jupiter")

    def _init_ph(self, b):
        """相位初值 = 旧的静态映射 (保证首帧位置与旧布局一致)。"""
        self._ph = dict(self._angles_static(b))
        self._om = {k: 0.0 for k in self.PH_KEYS}

    def _omega_target(self, key, b):
        """目标角速度 (rad/s): 由该层实测量定快慢, 但在跑时**恒 >0** ⇒ 一直连续转。
        (旧实现: 相位 = f(实测量), 数据一跳相位就跳 ⇒ 老倪「太阳系不要来回跳, 要连续」)"""
        d = b.get(key) or {}
        pair = {"mercury": (d.get("progress"), 0.012), "earth": (d.get("req_mps"), 0.35),
                "mars": (d.get("lambda"), 1.0), "jupiter": (d.get("eta"), 1.0)}[key]
        try:
            f = max(0.0, min(1.0, float(pair[0]) / (float(pair[1]) or 1.0)))
        except Exception:                                                    # noqa: BLE001
            f = 0.25
        return 0.25 + 1.0 * f            # 0.25 rad/s ≈ 25s 一圈 · 1.25 rad/s ≈ 5s 一圈

    def _advance(self, dt):
        b = self.data.body
        if getattr(self, "_ph", None) is None:
            self._init_ph(b)
        if not getattr(self.data, "running", False):
            for k in self.PH_KEYS:      # 没在跑: 不转、不留惯性 (老倪: 还没点运行, 不该有力)
                self._om[k] = 0.0
            return
        for k in self.PH_KEYS:
            tgt = self._omega_target(k, b)
            self._om[k] += (tgt - self._om[k]) * min(1.0, dt * 1.8)   # 平滑加速, 不突跳
            self._ph[k] = (self._ph[k] + self._om[k] * dt) % (2 * math.pi)

    def _angles(self, b):
        """当前公转相位 (连续积分量; 判据/positions 都用它)。"""
        if getattr(self, "_ph", None) is None:
            self._init_ph(b)
        return dict(self._ph)

    def _wobble_raw(self, moon):
        try:
            return max(0.0, min(0.55, abs(float(moon.get("err"))) * 2.4))
        except Exception:                                                    # noqa: BLE001
            return 0.0

    def _wobble(self, moon):
        """月球轨道半径偏置 (残差) —— 读**低通后**的值, 数据跳也不让月球跳。"""
        w = getattr(self, "_wob_s", None)
        return self._wobble_raw(moon) if w is None else w

    @staticmethod
    def _live(d):
        for k in ("progress", "eta", "action_norm", "req_mps"):
            if isinstance(d.get(k), (int, float)):
                return True
        return bool(d.get("err_all"))

    def positions(self, cx=None, cy=None, R=None):
        """当前变换下的所有球体屏幕坐标 (判据也用它核"卫星确实绕地球")。"""
        if cx is None:
            _W, _H, _S, cx, cy, R = self._geom()
        b = self.data.body
        ang = self._angles(b)
        pos = {"sun": (cx, cy, 0.0)}        # 太阳也要在表里! 否则 _draw_forces 取不到端点 ⇒ 太阳的连线全被跳过
        for key, frac in self.ORB.items():
            a = ang.get(key, 0.0)
            pos[key] = self._proj(frac * math.cos(a), frac * math.sin(a), 0.0, cx, cy, R)
        ea = ang.get("earth", 0.0)
        er = self.ORB["earth"]
        ex, ey = er * math.cos(ea), er * math.sin(ea)
        sats = (b.get("sats", {}).get("list") or [])
        pos["_sat"] = []
        # 起相位 +0.26rad (2026-10-16 看图: 卫星 i=0 与月球同取地球相位 ⇒ SK01 正好坐在地月连线上,
        #   球+金圈把 1px 地月线遮得只剩 1.5px, 看不出有连线)
        for i, d in enumerate(sats):
            # 起相位取**半个间距** (π/n): 这样"最近的那颗卫星"离地月线最远 —— 8 颗时是 22.5°
            #   (原来固定 0.26rad≈15°, 投影压扁后垂距只剩 5.6px, 判据 O3 要 ≥6)。n 变也自动最优。
            _n_s = max(1, len(sats))
            aa = ea + math.pi / _n_s + 2 * math.pi * i / _n_s        # 与地球同向公转 (绕地球)
            pos["_sat"].append(self._proj(ex + self.SAT_R * math.cos(aa),
                                          ey + self.SAT_R * math.sin(aa), 0.0, cx, cy, R) + (d.get("SK"),))
        wob = self._wobble(b.get("moon", {}))
        mr = self.MOON_R * (1.0 + wob)
        pos["moon"] = self._proj(ex + mr * math.cos(ea), ey + mr * math.sin(ea), 0.0, cx, cy, R)
        pos["_cx"] = cx
        pos["_cy"] = cy
        pos["_R"] = R
        return pos

    def local_offsets(self):
        """轨道平面内 (未投影) 的相对坐标 —— 判据用它核"卫星确实绕地球"(与视角无关)。

        返回: {"earth": (x, y) 相对太阳, "sat": [(dx, dy, SK)…] 相对地球, "moon": (dx, dy) 相对地球}
        """
        b = self.data.body
        ang = self._angles(b)
        ea = ang.get("earth", 0.0)
        er = self.ORB["earth"]
        ex, ey = er * math.cos(ea), er * math.sin(ea)
        sats = (b.get("sats", {}).get("list") or [])
        out = []
        for i, d in enumerate(sats):
            aa = ea + 2 * math.pi * i / max(1, len(sats))
            out.append((self.SAT_R * math.cos(aa), self.SAT_R * math.sin(aa), d.get("SK"), aa))
        wob = self._wobble(b.get("moon", {}))
        mr = self.MOON_R * (1.0 + wob)
        return {"earth": (ex, ey), "earth_angle": ea, "sat": out,
                "moon": (mr * math.cos(ea), mr * math.sin(ea)), "moon_radius": mr}

    # ── 画 ────────────────────────────────────────────────────────────────
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        W, H, S, cx, cy, R = self._geom()
        p.fillRect(0, 0, W, H, BG)
        b = self.data.body
        p.setPen(FG)
        p.setFont(_cached_font(15, True))
        p.drawText(QRectF(6, 2, W - 160, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   "🪐 球心引力架构 (太阳系映射)")
        p.setPen(DIM); p.setFont(_cached_font(14))
        p.drawText(QRectF(max(0, W - 190), 2, 184, 18), Qt.AlignRight | Qt.AlignVCenter,
                   "🖱 拖动旋转 · 滚轮缩放 · 双击复位")
        if not getattr(self.data, "running", False):
            # 2026-10-19: 状态必须写在脸上 —— 没点运行就别让人以为在看实时力
            p.setFont(_cached_font(11, True))
            p.setPen(QColor("#d29922"))
            p.drawText(QRectF(6, 18, max(120, W - 12), 16), Qt.AlignLeft | Qt.AlignVCenter,
                       "⏸ 未运行 (%s) —— 不显示力、不旋转; 球上的数 = 标定值/上一帧定格"
                       % (getattr(self.data, "run_note", "") or "未点 ▶ 运行"))
        # 引力井 (度量: 扁率按真特征值) + 轨道 (都在当前三维变换下)
        self._gravity_well(p, cx, cy, R, b.get("sun", {}))
        self._ecliptic(p, cx, cy, R)          # 2026-10-19: 黄道面 = 流形基准 (S³ 切片), 所有运动只在这个面里
        # 背景**圆形轨道** (2026-10-16 老倪: 「背景的圆形轨道也要体现出」):
        #   每条行星轨道用自己的球色淡描 + 慢速虚线相位 (与力连线同相位 ⇒ 全图一张"脉搏", 不闪)
        for ring, key in zip(self._grids, ("mercury", "earth", "mars", "jupiter")):
            cring = QColor(self.COL[key]); cring.setAlpha(120)
            pen = QPen(cring, 1.2, Qt.CustomDashLine)
            pen.setCapStyle(Qt.FlatCap); pen.setDashPattern([4.0, 5.0]); pen.setDashOffset(self._phase * 1.6)
            p.setPen(pen)
            pt = [self._proj(x, y, 0.0, cx, cy, R) for x, y in ring]
            for j in range(len(pt) - 1):
                p.drawLine(QPointF(pt[j][0], pt[j][1]), QPointF(pt[j + 1][0], pt[j + 1][1]))
        # 地球的**卫星环** (原子技能公转轨道): 也让背景把"轨道"说清楚
        _ea = self._angles(b).get("earth", 0.0)
        _er = self.ORB["earth"]
        cring = QColor(self.COL["sat"]); cring.setAlpha(170)      # 2026-10-16 看图: 110 太暗几乎看不见
        pen = QPen(cring, 1.4, Qt.CustomDashLine)
        pen.setCapStyle(Qt.FlatCap); pen.setDashPattern([3.0, 4.0]); pen.setDashOffset(self._phase * 1.6)
        p.setPen(pen)
        ring = [(self.SAT_R * math.cos(t / 72.0 * 2 * math.pi), self.SAT_R * math.sin(t / 72.0 * 2 * math.pi))
                for t in range(73)]
        pt = [self._proj(_er * math.cos(_ea) + x, _er * math.sin(_ea) + y, 0.0, cx, cy, R) for x, y in ring]
        for j in range(len(pt) - 1):
            p.drawLine(QPointF(pt[j][0], pt[j][1]), QPointF(pt[j + 1][0], pt[j + 1][1]))
        # 力的相互作用 (真源连线) —— 先画线, 再画球 (球压线, 视觉更干净)
        #   2026-10-19: 没点 ▶ 运行 ⇒ 一条力线都不画 (老倪: 「应该没有运行的力啊」)
        _RUN = bool(getattr(self.data, "running", False))
        if _RUN:
            self._draw_forces(p, cx, cy, R, b)
        # 球体 (按深度排序: 远的先画)
        pos = self.positions(cx, cy, R)
        sats = b.get("sats", {}).get("list") or []
        items = [("sun", cx, cy, S * self.RAD["sun"], pos.get("sun", (cx, cy, 0.0))[2], None)]
        for key in ("mercury", "jupiter", "mars", "earth"):
            x, y, z = pos[key]
            items.append((key, x, y, S * self.RAD[key], z, None))
        for i, (x, y, z, sk) in enumerate(pos["_sat"]):
            items.append(("sat", x, y, S * self.RAD["sat"] * (1.8 if sk == b.get("sats", {}).get("active") else 1.0),
                          z, sk))
        mx, my, mz = pos["moon"]
        items.append(("moon", mx, my, S * self.RAD["moon"], mz, None))
        items.sort(key=lambda t: t[4])
        # 地月细连线 (2026-10-16 看图: 原先画在球体**之后** + 端点取球心 ⇒ 1px 线压在球面上)
        #   正解: 画在球体之前, 两端各缩掉球半径+2px。
        _ex, _ey, _ez = pos["earth"]
        _vx, _vy = mx - _ex, my - _ey
        _nn = math.hypot(_vx, _vy) or 1.0
        _vx, _vy = _vx / _nn, _vy / _nn
        _r1 = S * self.RAD["earth"] + 2.0
        _r2 = S * self.RAD["moon"] + 2.0
        # 地月线颜色 2026-10-19 从 (120,132,150) 改深: 原色与月球球体自身的暗边 (约 131,135,139)
        #   在像素判据的容差内撞车 ⇒ 判据把"月球自己的阴影"误判成"线穿球面"。
        p.setPen(QPen(QColor(92, 104, 122, 190), 1))
        p.drawLine(QPointF(_ex + _vx * _r1, _ey + _vy * _r1), QPointF(mx - _vx * _r2, my - _vy * _r2))

        # 光晕先画 (在球体之下, 轨道之上): 只有"此刻在推理"的层才有, 强度=帧龄×呼吸
        for kind, x, y, r, _z, sk in items:
            if kind != "sat":
                self._infer_halo(p, kind, x, y, r)
        for kind, x, y, r, _z, sk in items:
            if kind == "sat":
                act = (sk == b.get("sats", {}).get("active"))
                live = bool(b.get("sats", {}).get("list")) and any(
                    d.get("SK") == sk and isinstance(d.get("偏差_mps"), (int, float))
                    for d in sats)
                self._infer_halo(p, "sat", x, y, r) if act else None
                self._sphere(p, x, y, r, self.COL["sat"], 1.0 if (act and live) else (0.7 if live else 0.32))
                if act:
                    self._infer_ripple(p, "sat", x, y, r)
                if act:
                    p.setPen(QPen(GOLD, 1)); p.setBrush(Qt.NoBrush)
                    p.drawEllipse(QPointF(x, y), r + 2, r + 2)      # r+3 → r+2 (看图: 金圈压进地球 1.8px)
                continue
            ecol = self.COL[kind] if kind != "moon" else self.COL["moon"]
            dkey = "sun" if kind == "sun" else kind
            # 太阳亮度不跟 ‖∇Φ‖ 走: ∇Φ 小的时候 (接近谷底) 太阳会暗到看不见 —— 中心不该"消失"。
            #   梯度大小另有表达: 引力井扁率 (度量特征值) + 标签里的 ‖∇Φ‖ + 自转弧。
            energy = 1.0 if kind == "sun" else (1.0 if self._live(b.get(dkey, {})) else 0.35)
            if getattr(self, "_focus", False) and kind != "earth":
                energy *= 0.42                                   # 地球视角: 其余天体退成背景
            self._sphere(p, x, y, r, ecol, energy)
        # 2026-10-19: 运行态环 —— 球外一圈按该体**自己真源的帧龄**上色 (绿=在跑/黄=陈旧/灰=离线)。
        #   环与球之间留 3px, 线宽 1.6px; 不做脉冲 (老倪: 不要高频闪烁)。
        for kind, x, y, r, _z, sk in items:
            if kind == "sat":
                continue
            _stt = (b.get(kind) or {}).get("st") or {}
            _LQ = {"sun": "L5", "jupiter": "L4", "mars": "L3", "earth": "L2"}.get(kind)
            if _LQ:
                self._quat_axis(p, _LQ, x, y, r, triad=(kind == "earth"))
            self._infer_ripple(p, kind, x, y, r)          # 推理外扩环 (在球外 5~18px, 不压球)
            self._state_ring(p, x, y, r, _stt.get("k"))
            if _RUN:
                self._spin(p, x, y, r, self._adj_local(kind, b))
        # 文字块是**半透明**底 (α=222) ⇒ 压住的线仍隐约可见 (老倪: 线不要很快消失);
        # 透描放在文字之前 —— 先透描再写字, 字才不会被线盖暗 (2026-10-16 看图: 数值行前半被压暗)。
        if _RUN:
            p.save()
            p.setClipRegion(self._ball_clip(p, pos, S))     # 透描不许画到球面上 (2026-10-16 看图: 线穿球面)
            self._draw_forces(p, cx, cy, R, b, ghost=True)
            p.restore()
        # 地球的力矢量 (粗=合力/细=分力) 画在连线之上、文字之下
        self._earth_force_arrows(p, pos, S, cx, cy, R)
        self._leaders = []
        self._labels(p, pos, cx, cy, R, b, W, H, S)
        self._focus_chip(p)
        self._s3_panel(p, W, H, b)
        self._legend(p, W, H, b)
        p.end()

    def _ecliptic(self, p, cx, cy, R):
        """黄道面 = 流形 (S³) 的二维基准切片。
        老倪 2026-10-19: 「黄道平面对应流形球面, 太阳对应流形中心 …… 两者都是所有运动发生的基准结构」
        ⇒ 画成**一个面**(半透明圆盘 + 细虚线边), 而不是再画一条轨道: 面=约束, 线=测地线。"""
        rr = 0.985                     # ⚠️ 单位是"R 的倍数" (不是像素): _proj 内部再乘 R,
                                       #    写成 R*0.985 会得到 1e5 量级的坐标 ⇒ 画面外, 等于没画 (实测踩过)
        poly = [self._proj(rr * math.cos(t / 90.0 * 2 * math.pi), rr * math.sin(t / 90.0 * 2 * math.pi),
                           0.0, cx, cy, R) for t in range(91)]
        path = [QPointF(x, y) for x, y, _z in poly]
        if path:
            from PyQt5.QtGui import QPolygonF
            pg = QPolygonF(path)
            p.setPen(Qt.NoPen)
            # α 太小时在 #0d1117 底上等于没画 (实测 α=16 采样点仍是纯底色) ⇒ 提到 140 的冷灰蓝:
            #   它是"基准面"的底色, 线/字都画在它**上面**, 不会被染色。
            p.setBrush(QColor(26, 44, 74, 140))
            p.drawPolygon(pg)
            p.setBrush(Qt.NoBrush)
            c = QColor(56, 139, 253, 120)
            pen = QPen(c, 1.0, Qt.CustomDashLine)
            pen.setDashPattern([2.0, 7.0]); pen.setDashOffset(self._phase * 0.6)
            p.setPen(pen)
            p.drawPolygon(pg)
        # 面标签 (贴在椭圆左下缘外侧, 避开主体与文字块)
        # 2026-10-19: 卡片放大到左下之后, 面标签会被卡压住 ⇒ 挪到椭圆**右上缘**外侧
        x, y, _z = self._proj(rr * 0.66, -rr * 0.72, 0.0, cx, cy, R)
        p.setPen(QColor(88, 166, 255, 210)); p.setFont(_cached_font(12))
        p.drawText(QRectF(x - 60, y + 2, 170, 12), Qt.AlignLeft | Qt.AlignVCenter,
                   "黄道面 = 流形基准 (S³ 切片)")

    @staticmethod
    def _adj_local(key, b):
        """局部微调量 (0~1): 太阳←‖∇Φ‖ · 水星←|V̇| · 地球←削因 · 火星←λ · 木星←η · 月球←|残差|。
        这正是"自转 = 局部微调"的可测量替身 —— 取不到的体返回 None ⇒ 不画弧。"""
        d = (b or {}).get(key) or {}
        v = None
        if key == "sun":
            v = d.get("grad_norm")
        elif key == "mercury":
            _vd = d.get("Vdot")
            v = abs(_vd) * 20 if isinstance(_vd, (int, float)) else None
        elif key == "earth":
            v = d.get("削因")
        elif key == "mars":
            v = d.get("lambda")
        elif key == "jupiter":
            v = d.get("eta")
        elif key == "moon":
            _e = d.get("err")
            v = abs(_e) * 10 if isinstance(_e, (int, float)) else None
        if not isinstance(v, (int, float)):
            return None
        return 2 * math.pi * 0.6 * max(0.0, min(1.0, float(v)))

    def _spin(self, p, x, y, r, ph):
        """自转 = 局部微调: 一小段弧, 弧角 = 该体的局部微调量 (真值归一), 不是空转动画。"""
        if not isinstance(ph, (int, float)):
            return
        span = max(0.0, min(2 * math.pi, float(ph)))
        if span <= 0.02:
            return
        c = QColor(255, 255, 255, 90)
        p.setPen(QPen(c, 1.1)); p.setBrush(Qt.NoBrush)
        rc = QRectF(x - r - 5.0, y - r - 5.0, 2 * (r + 5.0), 2 * (r + 5.0))
        p.drawArc(rc, int(math.degrees(-math.pi / 2) * 16), int(-math.degrees(span) * 16))

    # ── 2026-10-19 新增: 状态环 + L2~L5 层状态带 ────────────────────────────────
    STATE_COL = {"live": QColor("#3fb950"), "stale": QColor("#d29922"), "off": QColor("#6e7681")}

    PULSE_T = 2.0          # 呼吸/外扩环周期 (s) —— 慢, 柔顺

    @staticmethod
    def _qmat(q):
        """单位四元数 (w,x,y,z) → 3×3 旋转矩阵 (列 = 局部轴在母系里的方向)。"""
        w, x, y, z = [float(v) for v in q]
        return ((1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)),
                (2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)),
                (2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)))

    def _quat_axis(self, p, key, x, y, r, triad=False):
        """把该层的归一四元数画出来: 默认只画**转轴** (矢量部分方向, 1 根线);
        `triad=True` (地球 = 状态点) 画完整三轴 (X红/Y绿/Z蓝), 一眼看出朝向。
        6 颗球都画全三轴会太乱 ⇒ 只有状态点给三轴。"""
        qd = (getattr(self.data, "quat", {}) or {}).get(key) or {}
        q = qd.get("q")
        if not q:
            return
        m = self._qmat(q)
        _L = max(10.0, r * (1.75 if triad else 1.55))
        ox, oy = x, y

        def _tip(vx, vy, vz, ln, r0=0.0):
            """轴向端点的屏幕坐标; r0>0 时**从球面外侧**起画 (不压球面 —— 判据 M4 会抓
            "线色像素落在球心区", 三轴里那根绿轴和"动作"连线同色, 画在球上会被误判成线穿球)。"""
            _px, _py, _ = self._proj(vx * ln, vy * ln, vz * ln, ox, oy, 1.0)
            _dx, _dy = _px - ox, _py - oy
            _n = math.hypot(_dx, _dy) or 1.0
            return (ox + _dx / _n * (max(0.0, r0) + ln), oy + _dy / _n * (max(0.0, r0) + ln))


        if triad:
            self._tri_axes = []          # 判据用: 三轴投影后的实际长度 (有轴正对镜头时投影可能≈0)
            for _i, _c in enumerate(("#f85149", "#3fb950", "#4da3ff")):
                tx, ty = _tip(m[0][_i], m[1][_i], m[2][_i], _L, r + 1.0)
                self._tri_axes.append((_c, math.hypot(tx - ox, ty - oy)))
                cc = QColor(_c); cc.setAlpha(215)
                p.setPen(QPen(cc, 1.6))
                _sx, _sy = ox + (tx - ox) * (r + 1.0) / (r + 1.0 + _L), oy + (ty - oy) * (r + 1.0) / (r + 1.0 + _L)
                p.drawLine(QPointF(_sx, _sy), QPointF(tx, ty))
                p.setBrush(cc)
                p.drawEllipse(QPointF(tx, ty), 1.6, 1.6)
                p.setBrush(Qt.NoBrush)
            return
        _bk = {"L5": "sun", "L4": "jupiter", "L3": "mars", "L2": "earth"}.get(key, "")
        col = QColor(self.COL.get(_bk, "#8b949e")); col.setAlpha(190)
        tx, ty = _tip(m[0][0], m[1][0], m[2][0], _L, r + 1.0)      # 局部 X 轴 = 该层"方向"
        p.setPen(QPen(col, 1.4))
        _sx2 = ox + (tx - ox) * (r + 1.0) / (r + 1.0 + _L)
        _sy2 = oy + (ty - oy) * (r + 1.0) / (r + 1.0 + _L)
        p.drawLine(QPointF(_sx2, _sy2), QPointF(tx, ty))
        p.setBrush(col); p.drawEllipse(QPointF(tx, ty), 1.4, 1.4); p.setBrush(Qt.NoBrush)

    @staticmethod
    def _force_arrow(p, x0, y0, x1, y1, w, col, head=8.0, alpha=235):
        """画一根带箭头的力矢量 (粗=合力, 细=分力)。"""
        c = QColor(col); c.setAlpha(alpha)
        p.setPen(QPen(c, w, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(x0, y0), QPointF(x1, y1))
        _dx, _dy = x1 - x0, y1 - y0
        _L = math.hypot(_dx, _dy) or 1.0
        ux, uy = _dx / _L, _dy / _L
        # 箭头两翼
        for sgn in (-1, 1):
            _ax = x1 - ux * head + (-uy) * head * 0.5 * sgn
            _ay = y1 - uy * head + (ux) * head * 0.5 * sgn
            p.setPen(QPen(c, max(1.4, w * 0.72), Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(x1, y1), QPointF(_ax, _ay))

    def _earth_force_arrows(self, p, pos, S, cx, cy, R):
        """地球 (状态点) 上的力: **粗大箭头 = 合力 (前馈节点输出方向)**, 细箭头 = 四层分力,
        再加一条头尾相接的虚线链 (把分力一段段加起来正好落到合力箭头尖) —— 一眼看出"合力由谁组成"。
        老倪 2026-10-19: 「地球的引力箭头应该大一些, 长一些, 粗一些, 明显一些…太阳力, 行星力,
        都是组成地球合力的分力」。"""
        self._last_arrows = []          # 每帧先清空: 未运行时不画, 也不许留上一帧的账 (判据会读到假值)
        fE = getattr(self.data, "fE", None) or {}
        if not fE or not getattr(self.data, "running", False):
            return
        # 卡片区域不画箭头 (卡片是实底, 否则箭头像被砍断)
        _Wq, _Hq = int(self.width()), int(self.height())
        _cw = self._s3_w(_Wq) + 10.0
        _ch = 218.0
        _cy0 = _Hq - 14.0 - self.LH * len(self._foot_lines(_Wq)) - _ch
        _reg = QRegion(0, 0, _Wq, _Hq).subtracted(QRegion(0, int(_cy0) - 2, int(_cw), int(_ch) + 4))
        p.save()
        p.setClipRegion(_reg)
        ex, ey, _e = pos["earth"]

        def _scr(v, ln):
            px, py, _ = self._proj(v[0] * ln, v[1] * ln, v[2] * ln, ex, ey, 1.0)
            _dx, _dy = px - ex, py - ey
            _n = math.hypot(_dx, _dy) or 1.0
            return ex + _dx / _n * ln, ey + _dy / _n * ln

        # 判据用: 这一刻每根箭头的 (类, 笔宽, 像素长)
        # 🔧 绝对尺度 (老倪 2026-10-19「按建议来」): 长度 = |F| × px_per_mps (真源 force_field.json),
        #   不再"按当帧最大值归一" —— 那样帧与帧之间长度不可比, 看着忽长忽短。
        #   线性尺度在 |F| 跨 10 倍 (0.05~0.55 m/s) 时只能全线贴顶 ⇒ 用**固定参考的平方根尺度**:
        #   L = Lmax·√(|F|/F_ref), F_ref 固定 (force_field.json) ⇒ 同一 |F| 永远同样长, 跨帧可比, 不会饱和。
        _ref = float(getattr(self.data, "arrow_ref", 1.0) or 1.0)
        _lmax = float(getattr(self.data, "arrow_max", 168.0) or 168.0)
        if getattr(self, "_focus", False):
            _lmax *= 1.18

        def _plen(mag):
            _r = min(1.0, max(0.0, float(mag or 0.0)) / _ref)
            return max(9.0, _lmax * math.sqrt(_r))
        # ① 分力 (细) + 头尾链
        ox, oy = ex + 0.0, ey + 0.0
        _chain_x, _chain_y = ex, ey
        for _ci, c in enumerate(fE.get("comps") or []):
            _ln = _plen(c["mag"])
            tx, ty = _scr(c["vec"], _ln)
            _col = self.COL.get(c.get("body") or "earth", "#8b949e")
            _w2 = 3.2 if c.get("main") else 1.7
            self._force_arrow(p, ex, ey, tx, ty, _w2, _col,
                        head=7.0 if c.get("main") else 4.5, alpha=210 if c.get("main") else 165)
            self._last_arrows.append({"kind": c["L"], "w": _w2,
                                      "len": math.hypot(tx - ex, ty - ey), "main": bool(c.get("main"))})
            # 头尾链: 从上一个分力末端出发
            _nx = _chain_x + (tx - ex)
            _ny = _chain_y + (ty - ey)
            cc = QColor(_col); cc.setAlpha(110)
            p.setPen(QPen(cc, 1.0, Qt.DashLine))
            p.drawLine(QPointF(_chain_x, _chain_y), QPointF(_nx, _ny))
            _chain_x, _chain_y = _nx, _ny
        # ② 合力 (粗, 最显眼)
        _lnF = _plen(fE.get("mag") or 0.0) * 1.35      # 合力同尺度 ×1.35: 永远比分力长 (但不是靠归一张冠李戴)
        fx, fy = _scr(fE.get("vec") or [0, 0, 0], _lnF)
        self._force_arrow(p, ex, ey, fx, fy, 5.4, "#58a6ff", head=11.0, alpha=245)
        self._last_arrows.append({"kind": "F合", "w": 5.4,
                                  "len": math.hypot(fx - ex, fy - ey), "main": True})
        # 记下合力箭头的**屏幕方向角** (判据 R5 用它跟 S³ 表盘的"合"射线逐度比对)
        self._arrow_ang = math.degrees(math.atan2(fy - ey, fx - ex)) % 360.0
        # ③ 合力实时数 (贴箭头尖)
        # 潮汐项 (月球↔地球互作用): 真源里没有"月球对地球的引力", 只有状态校正器的**残差** ⇒
        #   拿残差当潮汐量, 画虚线箭并向月球方向, 标签写"潮汐(残差)", 不冒充引力。
        _me = (self.data.body.get("moon") or {}).get("err")
        if isinstance(_me, (int, float)) and not isinstance(_me, bool):
            _mx2, _my2, _ = pos["moon"]
            _dd = math.hypot(_mx2 - ex, _my2 - ey) or 1.0
            _tlen = max(10.0, min(58.0, abs(float(_me)) * 900.0))
            _tx2, _ty2 = ex + (_mx2 - ex) / _dd * _tlen, ey + (_my2 - ey) / _dd * _tlen
            _cc = QColor(223, 228, 236); _cc.setAlpha(150)
            p.setPen(QPen(_cc, 1.4, Qt.DashLine, Qt.RoundCap))
            p.drawLine(QPointF(ex, ey), QPointF(_tx2, _ty2))
            p.setPen(QColor(190, 198, 212))
            p.setFont(_cached_font(9))
            p.drawText(QRectF(_tx2 + 3, _ty2 - 11, 96, 11), Qt.AlignLeft | Qt.AlignVCenter,
                       "潮汐 |残差|%.3f" % float(_me))
        p.restore()
        _lab = "F合 %.2f m/s · Δ主↔合 %.0f°" % (fE.get("mag") or 0.0, fE.get("dev") or 0.0)
        p.setPen(QColor("#9fd0ff"))
        p.setFont(_cached_font(15, True))
        p.drawText(QRectF(fx + 8, fy - 26, 280, 22), Qt.AlignLeft | Qt.AlignVCenter, _lab)

    def _focus_chip(self, p):
        """左上角胶囊: 点一下在「🌍 地球视角」与「☀ 太阳系视角」之间切 (老倪 2026-10-19「以地球为主要观察对象」)。"""
        _on = bool(getattr(self, "_focus", False))
        _t = "☀ 太阳系视角" if _on else "🌍 地球视角"
        p.setFont(_cached_font(15, True))
        _w = 152.0
        _r = QRectF(10, 40, _w, 32)          # 标题 0~18 / 说明 19~34 ⇒ 胶囊从 40 起, 不压字
        self._chip_rect = (10.0, 40.0, _w, 32.0)
        p.setPen(QPen(QColor("#2f81f7" if _on else "#3d4757"), 1))
        p.setBrush(QColor(24, 36, 54, 200) if _on else QColor(18, 24, 34, 170))
        p.drawRoundedRect(_r, 11, 11)
        p.setPen(QColor("#9fd0ff" if _on else "#9aa4b2"))
        p.drawText(_r, Qt.AlignCenter, _t)

    def _s3_panel(self, p, W, H, b):
        """"S³ 力场总观" 小面板 (左下): 把合力与四个分力的**四元数**画成一束方向射线,
        长度 = 矢量部分模长 (方向强度), 亮度 = 标量部 w。附 Δ主↔合 与一致度。"""
        fE = getattr(self.data, "fE", None) or {}
        if not self._s3_visible(W):
            return
        _run0 = bool(getattr(self.data, "running", False))
        _h = 218.0
        _y0 = H - 14.0 - self.LH * len(self._foot_lines(W)) - _h
        x0, w0 = 10.0, self._s3_w(W)
        p.setPen(QPen(QColor(90, 110, 140, 120), 1))
        p.setBrush(QColor(9, 14, 21, 238))      # 不再透到看得见后面的轨道 ⇒ 面板要"实"
        if not fE:
            # 未运行 / 无真源: 画空骨架 (五个空盘 + 未运行), 布局不跳, 也不假装有力
            p.setPen(QPen(QColor(90, 110, 140, 120), 1))
            p.setBrush(QColor(9, 14, 21, 238))
            p.drawRoundedRect(QRectF(x0, _y0, w0, _h), 6, 6)
            p.setBrush(Qt.NoBrush)
            p.setFont(_cached_font(17, True)); p.setPen(QColor("#9aa4b2"))
            p.drawText(QRectF(x0 + 14, _y0 + 10, w0 - 28, 24), Qt.AlignLeft | Qt.AlignVCenter,
                       "S³ 力场 · ⏸ 未运行")
            _cw0 = (w0 - 28.0) / 5.0
            for _i, _nm in enumerate(("合", "L5", "L4", "L3", "L2")):
                _ccx = x0 + 14.0 + _cw0 * (_i + 0.5)
                _ccy = _y0 + 96.0
                _rad = min(34.0, _cw0 * 0.45)
                p.setPen(QPen(QColor(52, 66, 86, 160), 1.2))
                p.drawEllipse(QPointF(_ccx, _ccy), _rad, _rad)
                p.setFont(_cached_font(14, True)); p.setPen(QColor("#6e7681"))
                p.drawText(QRectF(_ccx - _cw0 / 2.0, _ccy + _rad + 2, _cw0, 18),
                           Qt.AlignHCenter | Qt.AlignTop, _nm)
            p.setFont(_cached_font(15, True))
            p.drawText(QRectF(x0 + 14, _y0 + _h - 30, w0 - 28, 22), Qt.AlignLeft | Qt.AlignVCenter,
                       "没点 ▶ 运行, 不显示力")
            return
        self._s3_rect = (x0, _y0, w0, _h)
        p.drawRoundedRect(QRectF(x0, _y0, w0, _h), 6, 6)
        p.setBrush(Qt.NoBrush)
        p.setPen(QColor("#9aa4b2"))
        p.setFont(_cached_font(17, True))
        _cap0 = str(getattr(self.data, "cap_level", "") or "")
        _ft = (("S³ 力场 · 一致度 %.2f" % (fE.get("coh") or 0.0)) + ((" · 档位 " + _cap0) if _cap0 else "")) \
            if getattr(self.data, "running", False) else "S³ 力场 · ⏸ 未运行 (定格)"
        p.setPen(QColor("#9aa4b2") if not getattr(self.data, "running", False) else QColor("#e6edf3"))
        p.drawText(QRectF(x0 + 14, _y0 + 10, w0 - 28, 24), Qt.AlignLeft | Qt.AlignVCenter, _ft)
        # 2026-10-19 看图: 五支射线共用同一原点, 中段只差 4~8px ⇒ 糊成一束。
        #   改成**五个独立小表盘** (各自原点, 各自格子), 方向一眼分得开。
        # 2026-10-19 老倪「选了 L5 却没有 L5 的力显示」: 表盘原来只画方向 (q̂ 的矢量部, 模长≈常数)
        #   ⇒ 五个盘看起来一模一样, 也**没有任何数字**。现在: 射线长 ∝ √(|F|/max) + 盘下写 |F|。
        self._s3_lens = []
        # 🔴 2026-10-19 老倪「就 L5, 力场不显示 L5 的单位圆」: 原来只遍历"有数据的层",
        #   L5 没真源(缺 L5) 时整格都不画 ⇒ 五格变四格, 位置还整体错位, 看着像"L5 被吞了"。
        #   现在: **五个格位固定** (合/L5/L4/L3/L2), 没数据的层照样画单位圆 + 层名 + "缺",
        #   只是不画射线 —— 老倪要的是"能看见它在, 且知道它为什么没数"。
        _byL = {}
        for c in (fE.get("comps") or []):
            _byL[c["L"]] = c
        self._s3_slots = ["合", "L5", "L4", "L3", "L2"]     # 五个格位固定 (判据 R4 用)
        _items = [(fE.get("q"), "#58a6ff", "合", 1.0, float(fE.get("mag") or 0.0))]
        for _L5 in ("L5", "L4", "L3", "L2"):
            _c5 = _byL.get(_L5)
            _col = self.COL.get((_c5 or {}).get("body") or "sun", "#8b949e")
            _items.append((((_c5 or {}).get("q")), _col, _L5, 1.0,
                           float((_c5 or {}).get("mag") or 0.0)))
        _mx = max([it[4] for it in _items] or [1e-9]) or 1e-9
        from PyQt5.QtGui import QPolygonF
        _dirs = []                # 已画过的 (角度, 名字): 用于给"同向层"标 ≡ (L2/L3 常常同向)
        _n_it = len(_items)
        _cw = (w0 - 28.0) / max(1, _n_it)
        _dy = _y0 + 52.0 + 44.0
        for _i, (_q, _col, _nm, _wgt, _mag) in enumerate(_items):
            if not _q:
                # 这一层没有真源 (例: L5 场景理解没跑) ⇒ 空盘 + 层名 + "缺", 位置不动
                _ccx = x0 + 14.0 + _cw * (_i + 0.5)
                _ccy = _dy
                _rad = min(34.0, _cw * 0.45)
                p.setPen(QPen(QColor(52, 66, 86, 140), 1.2, Qt.DashLine))
                p.setBrush(QColor(12, 17, 26, 200))
                p.drawEllipse(QPointF(_ccx, _ccy), _rad, _rad)
                p.setBrush(Qt.NoBrush)
                p.setPen(QColor("#6e7681"))
                p.setFont(_cached_font(14, True))
                p.drawText(QRectF(_ccx - _cw / 2.0, _ccy + _rad + 2, _cw, 18),
                           Qt.AlignHCenter | Qt.AlignTop, _nm)
                p.setFont(_cached_font(15, True))
                p.setPen(QColor("#8b949e"))
                p.drawText(QRectF(_ccx - _cw / 2.0, _ccy + _rad + 20, _cw, 16),
                           Qt.AlignHCenter | Qt.AlignTop, "缺")
                continue
            _ccx = x0 + 14.0 + _cw * (_i + 0.5)
            _ccy = _dy
            _rad = min(34.0, _cw * 0.45)
            p.setPen(QPen(QColor(52, 66, 86, 200), 1.2))
            p.setBrush(QColor(14, 20, 30, 220))
            p.drawEllipse(QPointF(_ccx, _ccy), _rad, _rad)
            p.setBrush(Qt.NoBrush)
            # 🔴 2026-10-19 老倪「力场的合力方向，与太阳系地球的 F合 方向要一致」:
            #   原来这里用的是 q 的 (x,y) 两个分量 ⇒ 那是**力在 XY 平面上的投影**;
            #   而地球那根 F合 箭头用的是 _proj() 的**屏幕投影** (带黄道倾角/偏航/俯仰)。
            #   两套投影不同 ⇒ 盘上的指针和球上的箭头方向对不上。
            #   现在: 盘上的方向也走 _proj (同一个函数, 只是原点取 0、尺度取 1) ⇒ 天然一致。
            #   长度: 盘里按单位圆封顶 (老倪「力场在单位圆里即可」), 球上的箭头照旧可以更长。
            vx, vy, _vz, ww = _q[1], _q[2], _q[3], _q[0]
            _d2x, _d2y, _ = self._proj(vx, vy, _vz, 0.0, 0.0, 1.0)
            if math.hypot(_d2x, _d2y) < 1e-9:      # 力几乎垂直于屏幕 (投影退化) ⇒ 指向正上, 不画零长
                _d2x, _d2y = 0.0, -1.0
            vx, vy = _d2x, _d2y
            _vv = math.hypot(vx, vy) or 1e-6
            # 长度按 |F| 的**对数**尺度 (2026-10-19 看图: 平方根把 5 倍压成 1.27 倍, 肉眼读不出量级)
            #   ⇒ log 分档, 最弱层 0.24r、最强层 0.92r; 尖不出环 (≤0.92r < 半径)
            _lg = lambda v: math.log10(max(1e-6, v))
            _lo = min([it[4] for it in _items if it[4] > 0] or [1e-6])
            _hi = max([it[4] for it in _items] or [1e-6])
            _u = 0.0 if _hi <= _lo * 1.0001 else (_lg(_mag) - _lg(_lo)) / (_lg(_hi) - _lg(_lo))
            _ln = max(9.0, _rad * (0.28 + 0.64 * max(0.0, min(1.0, _u))) * _wgt)
            _lens = getattr(self, "_s3_lens", None)
            if _lens is None:
                _lens = self._s3_lens = []
            _lens.append((_nm, round(_mag, 4), round(_ln, 1)))
            c = QColor(_col); c.setAlpha(int(150 + 100 * abs(ww)))
            p.setPen(QPen(c, 5.0 if _nm == "合" else 3.6, Qt.SolidLine, Qt.RoundCap))
            _px, _py = _ccx + vx / _vv * _ln, _ccy + vy / _vv * _ln
            p.drawLine(QPointF(_ccx, _ccy), QPointF(_px, _py))
            # 箭头尖 (2026-10-19 看图: 只是圆头线段 ⇒ 看不出朝向)
            _ang = math.atan2(_py - _ccy, _px - _ccx)
            _hl = 8.0 if _nm == "合" else 6.5
            p.setBrush(c)
            _tri = QPolygonF([QPointF(_px, _py),
                              QPointF(_px - _hl * math.cos(_ang - 0.42), _py - _hl * math.sin(_ang - 0.42)),
                              QPointF(_px - _hl * math.cos(_ang + 0.42), _py - _hl * math.sin(_ang + 0.42))])
            p.drawPolygon(_tri)
            p.setBrush(Qt.NoBrush)
            p.setBrush(c)
            p.drawEllipse(QPointF(_ccx, _ccy), 2.6, 2.6)
            p.setBrush(Qt.NoBrush)
            p.setPen(c)
            p.setFont(_cached_font(14, True))
            _ang_d = math.degrees(math.atan2(vy, vx)) % 360.0     # 屏幕坐标 (y 向下)
            _same = None      # 2026-10-19: 同向就写 "L2≡L3" 反而让人以为是一个层; 层名一律独立
            _dirs.append((_ang_d, _nm, _mag))
            if _nm == "合":
                self._s3_ang = _ang_d          # 表盘"合"射线的屏幕方向角 (判据 R5)
            p.drawText(QRectF(_ccx - _cw / 2.0, _ccy + _rad + 2, _cw, 18),
                       Qt.AlignHCenter | Qt.AlignTop, (_nm + "≡" + _same) if _same else _nm)
            # 盘下写这个层这一刻的力 (m/s) —— 直接回答"L5 的力是多少"
            p.setFont(_cached_font(15, True))
            p.setPen(QColor("#c9d1d9"))
            _off_layer = (not getattr(self.data, "layers_on", {}).get(_nm, True)) if _nm != "合" else False
            p.drawText(QRectF(_ccx - _cw / 2.0, _ccy + _rad + 20, _cw, 16),
                       Qt.AlignHCenter | Qt.AlignTop, "未跑" if _off_layer else ("%.3f" % _mag))
        ox, oy = x0 + 14.0, _y0 + _h - 30.0

        # S³ 角距 (老倪「用四元数表达力场总观」): 角距 = 2·acos|⟨qi,qj⟩| (大圆距离), 两行写完六对
        _qs = dict((c["L"], c.get("q")) for c in (fE.get("comps") or []))
        _qs["合"] = fE.get("q")
        def _ang(a, b):
            if not a or not b:
                return None
            _d = abs(sum(x * y for x, y in zip(a, b)))
            return math.degrees(2.0 * math.acos(min(1.0, _d)))
        _pairs = [("L2", "L3"), ("L2", "L4"), ("L2", "L5"), ("L3", "L4"), ("L3", "L5"), ("L4", "L5")]
        # 角距只留"主力↔合力"一句 (其余五对在悬停卡): 9px 两行字太小, 老倪看不清 ⇒ 不上画面
        _a = float(getattr(self.data, "alpha", 1.0) or 1.0)
        _ml = "L4" if _a > 1.0 else "L2"
        _dmain = _ang(_qs.get(_ml), fE.get("q"))
        p.setPen(QColor("#8b98a8"))
        p.setFont(_cached_font(15, True))
        p.drawText(QRectF(x0 + 14, _y0 + _h - 30, w0 - 28, 22), Qt.AlignLeft | Qt.AlignVCenter,
                   "∠主力↔合力 %.0f° · Δ合 %.0f°" % (_dmain or 0.0, fE.get("dev") or 0.0))


    def _infer_halo(self, p, key, x, y, r):
        """推理中的**柔顺光晕** (画在球体之下): 半径 2.2r 的径向渐变, 强度按
        _live_s (该层真源帧龄) × 呼吸曲线 (周期 2s, 正弦) —— 在推理就慢呼吸, 不在就自然灭掉。"""
        a = getattr(self, "_live_s", {}).get(key, 0.0)
        if a <= 0.03:
            return
        t = getattr(self, "_pulse_t", 0.0)
        _ph = (t / self.PULSE_T + (abs(hash(key)) % 97) / 97.0) % 1.0
        _b = 0.55 + 0.45 * math.sin(2 * math.pi * _ph)          # 0.10 ~ 1.00, 连续
        col = QColor(self.COL.get(key, "#8b949e"))
        g = QRadialGradient(QPointF(x, y), max(r * 2.2, r + 12.0))
        c0 = QColor(col); c0.setAlphaF(min(0.40, 0.34 * a * _b))
        c1 = QColor(col); c1.setAlphaF(0.0)
        g.setColorAt(0.0, c0); g.setColorAt(0.58, c0); g.setColorAt(1.0, c1)
        p.setPen(Qt.NoPen); p.setBrush(g)
        _rr = max(r * 2.2, r + 12.0)
        p.drawEllipse(QPointF(x, y), _rr, _rr)
        p.setBrush(Qt.NoBrush)

    def _infer_ripple(self, p, key, x, y, r):
        """推理中的**外扩环** (画在球体之外, 不压球): 两个环错半周期, 一直有环在往外走
        ⇒ 看得出来"这一颗正在算", 但既不闪也不跳 (半径/透明度都是时间连续函数)。"""
        a = getattr(self, "_live_s", {}).get(key, 0.0)
        if a <= 0.03:
            return
        t = getattr(self, "_pulse_t", 0.0)
        _ph = (t / self.PULSE_T + (abs(hash(key)) % 97) / 97.0) % 1.0
        col = QColor(self.COL.get(key, "#8b949e"))
        for _d in (0.0, 0.5):
            f = (_ph + _d) % 1.0
            al = int(135 * a * (1.0 - f) ** 1.7)
            if al <= 3:
                continue
            c = QColor(col); c.setAlpha(al)
            p.setPen(QPen(c, 1.5)); p.setBrush(Qt.NoBrush)
            rr = r + 5.0 + 13.0 * f
            p.drawEllipse(QPointF(x, y), rr, rr)

    def _state_ring(self, p, x, y, r, k):
        c = QColor(self.STATE_COL.get(k or "off"))
        c.setAlpha(235 if k == "live" else 200)
        p.setPen(QPen(c, 1.6)); p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(x, y), r + 3.0, r + 3.0)

    def _layers_strip(self, p, W, H):
        """右上角 L5→L4→L3→L2 四格: 每格 = 层名 + 状态点 + 最近一次真调用的 ms; 整条带标公共帧龄。
        真源: layer_calls.jsonl 末行 (引擎每拍一条流水)。文件停写 ⇒ 整条带变黄/灰并标"陈旧", 不冒充在跑。"""
        L = getattr(self.data, "layers", None) or {}
        if not L:
            return
        k = L.get("k")
        col = self.STATE_COL.get(k or "off")
        cw, ch, gap = 74.0, 34.0, 6.0
        x0 = W - 8 - (cw * 4 + gap * 3)
        y0 = 24.0
        p.setFont(_cached_font(12))
        _fm = p.fontMetrics()
        for i, name in enumerate(("L5", "L4", "L3", "L2")):
            d = L.get(name) or {}
            x = x0 + i * (cw + gap)
            rr = QRectF(x, y0, cw, ch)
            _bg = QColor(18, 22, 30, 232)
            p.setPen(QPen(QColor(58, 66, 80), 1)); p.setBrush(_bg)
            p.drawRoundedRect(rr, 5, 5)
            _ok = d.get("ok")
            _dc = QColor("#3fb950") if (_ok and k == "live") else (QColor("#d29922") if _ok else QColor("#f85149"))
            if k != "live":
                _dc = QColor("#d29922") if _ok else QColor("#6e7681")
            p.setPen(Qt.NoPen); p.setBrush(_dc)
            p.drawEllipse(QPointF(x + 8, y0 + 10), 3.0, 3.0)
            p.setPen(FG); p.setFont(_cached_font(11, True))
            p.drawText(QRectF(x + 14, y0 + 3, cw - 16, 14), Qt.AlignLeft | Qt.AlignVCenter, name)
            p.setPen(DIM); p.setFont(_cached_font(12))
            _ms = d.get("ms")
            _t = ("%.1f ms" % _ms) if isinstance(_ms, (int, float)) else ("—" if _ok is None else "无 ms")
            p.drawText(QRectF(x + 6, y0 + 18, cw - 10, 12), Qt.AlignLeft | Qt.AlignVCenter, _t)
        # 公共帧龄
        _age = L.get("age")
        _txt = "L2~L5 调用流水: " + (("帧龄 %.1fs · %s" % (_age, L.get("txt") or "")) if isinstance(_age, (int, float)) else "无真源")
        p.setFont(_cached_font(12)); p.setPen(col)
        p.drawText(QRectF(x0, y0 + ch + 2, cw * 4 + gap * 3, 12), Qt.AlignRight | Qt.AlignVCenter, _txt)

    def _gravity_well(self, p, cx, cy, R, sun):
        e1, e2 = sun.get("eig_min"), sun.get("eig_max")
        ratio = 1.0
        if e1 and e2 and float(e2) > 0:
            ratio = max(0.35, min(1.0, float(e1) / float(e2)))
        for i in range(3):                                        # 6 圈→3 圈 (2026-10-16 看图: 与轨道环混淆)
            rr = 0.12 + 0.09 * i
            alpha = 62 - i * 12
            # 2026-10-16 看图: 原金褐色 (210,153,34) 与金线辉光几乎同色(差2), 1× 数不出圈数 ⇒ 改冷灰蓝
            p.setPen(QPen(QColor(91, 107, 125, max(46, alpha + 40)), 1.30))   # 看图: 1× 下太淡只隐约可见
            pts = [self._proj(rr * math.cos(t / 60.0 * 2 * math.pi),
                              rr * ratio * math.sin(t / 60.0 * 2 * math.pi), 0.0, cx, cy, R)
                   for t in range(61)]
            for j in range(len(pts) - 1):
                p.drawLine(QPointF(pts[j][0], pts[j][1]), QPointF(pts[j + 1][0], pts[j + 1][1]))

    def _force_segments(self, pos, b):
        """要画的**主体↔主体**真连线 + 每条的法向平移量 (共线去重叠)。

        抽出来是给判据量"实际画出来的几何"用 —— 判据只读 positions() 会量到平移**之前**的坐标
        (2026-10-16: 判据 N2 因此误红)。
        """
        segs = []
        for _e in self._edges:
            if not _e["body_body"] or not self._signal_ok(_e, b):
                continue
            _pa = pos.get(self._key_of(_e["f"])); _pb = pos.get(self._key_of(_e["t"]))
            if _pa is None or _pb is None:
                continue
            segs.append((_e, float(_pa[0]), float(_pa[1]), float(_pb[0]), float(_pb[1])))
        offs = []
        for _i2, _a in enumerate(segs):
            shift = 0.0
            for _b2 in segs[:_i2]:
                _ang = abs(math.atan2(_a[4] - _a[2], _a[3] - _a[1])
                           - math.atan2(_b2[4] - _b2[2], _b2[3] - _b2[1])) % math.pi
                if min(_ang, math.pi - _ang) > 0.17:
                    continue
                _dx2, _dy2 = _b2[3] - _b2[1], _b2[4] - _b2[2]
                _n2 = math.hypot(_dx2, _dy2) or 1.0
                _nx, _ny = -_dy2 / _n2, _dx2 / _n2
                _sd_a = (_a[1] - _b2[1]) * _nx + (_a[2] - _b2[2]) * _ny
                _sd_b = (_a[3] - _b2[1]) * _nx + (_a[4] - _b2[2]) * _ny
                _dd2 = min(abs(_sd_a), abs(_sd_b))
                if _dd2 < 6.0:
                    # 2026-10-19: 原来固定 +4 ⇒ 汇于同一顶点的两条近共线 (太阳→水星/太阳→木星)
                    #   会被推向**靠近**对方的一侧, 局部反而贴成 0px。改成朝"离开对方"的方向推 4px。
                    _mid = _sd_a if abs(_sd_a) >= abs(_sd_b) else _sd_b
                    shift = 4.0 if _mid >= 0 else -4.0
            offs.append((_a[0], shift))
        return offs

    def drawn_segments(self):
        """判据用: [(名字, x1,y1,x2,y2)] —— **实际画出来**的线 (含共线平移)。"""
        W, H, S, cx, cy, R = self._geom()
        pos = self.positions(cx, cy, R)
        out = []
        for _e, _off in self._force_segments(pos, self.data.body):
            _pa = pos.get(self._key_of(_e["f"])); _pb = pos.get(self._key_of(_e["t"]))
            _x1, _y1, _x2, _y2 = float(_pa[0]), float(_pa[1]), float(_pb[0]), float(_pb[1])
            if _off:
                _dx3, _dy3 = _x2 - _x1, _y2 - _y1
                _n3 = math.hypot(_dx3, _dy3) or 1.0
                _x1 += -_dy3 / _n3 * _off; _y1 += _dx3 / _n3 * _off
                _x2 += -_dy3 / _n3 * _off; _y2 += _dx3 / _n3 * _off
            out.append((_e["f"] + "→" + _e["t"], _x1, _y1, _x2, _y2))
        return out

    def _ball_clip(self, p, pos, S):
        """把球体从裁剪区里挖掉 (给"文字之上透描"用: 线不许画在球面上)。"""
        from PyQt5.QtGui import QRegion
        W, H, _S2, _cx, _cy, _R = self._geom()
        reg = QRegion(0, 0, W, H)
        for key in ("sun", "mercury", "earth", "mars", "jupiter", "moon"):
            try:
                x, y = float(pos[key][0]), float(pos[key][1])
            except (KeyError, IndexError, TypeError):
                continue
            r = S * self.RAD[key] + 2.0
            reg = reg.subtracted(QRegion(int(x - r), int(y - r), int(2 * r), int(2 * r), QRegion.Ellipse))
        for x, y, _z, _sk in pos.get("_sat", []):
            r = S * self.RAD["sat"] + 2.0
            reg = reg.subtracted(QRegion(int(x - r), int(y - r), int(2 * r), int(2 * r), QRegion.Ellipse))
        return reg

    def _draw_forces(self, p, cx, cy, R, b, ghost=False):
        """力的相互作用: **只画主体↔主体**的真连线, 全部**虚线** (柔顺慢速流动), 颜色=信号种类。

        2026-10-16 老倪: 「连线太多了… 直线实线改成虚线, 用不同的颜色表示不同的信号,
        有就显示, 没有就不显示, 注意柔顺显示」。所以:
          · 体系外的线与灰点**全部删除** (只留 7 类主体之间的真边);
          · 每一条都是虚线 (CustomDashLine, 相位连续慢推 ⇒ 在动, 但绝不闪、不断);
          · 颜色按**信号种类**: 青=几何条件 · 金=性能/集合条件 · 绿=动作/前馈 · 紫=反馈/回灌;
          · `_signal_ok` 门控 —— 该相互作用依赖的真源信号没值 ⇒ **这条线不画** (不画假线)。
        """
        pos = self.positions(cx, cy, R)
        col_of = {"geom": CYAN, "condition": CYAN, "perf": GOLD, "semantic": GOLD,
                  "drive": GREEN, "feedback": VIOLET, "misc": QColor("#8b949e")}
        p.setRenderHint(QPainter.Antialiasing, True)
        # 2026-10-16 看图: 太阳→水星(青) 与 太阳→木星(金) 几乎共线 ⇒ 后画的把先画的吞成一条 8px 脏色带,
        #   看着只有一条线。正解: 检出"近共线(<10°)且带间距<6px"的一对, 把**后一条**沿法向平移 4px
        #   (两端同移, 仍落在两球之间)。两遍(透描/正画)用同一张偏移表 ⇒ 相位与位置一致。
        _seg4 = self._force_segments(pos, b)
        _offs = {id(_e): _o for (_e, _o) in _seg4}
        _dt = getattr(self, "_dt", self.TICK_MS / 1000.0)
        if not hasattr(self, "_edge_a"):
            self._edge_a, self._edge_o = {}, {}
        for e in self._edges:
            if not e["body_body"]:
                continue
            _ok = self._signal_ok(e, b)              # 有就显示, 没有就不显示
            _k = id(e)
            # 2026-10-19 老倪「不能有任何连线的跳跃」: 出现/消失走 0.3s 透明度渐变, 不硬切;
            #   近共线偏移 0↔4px 也走缓动 ⇒ 不会看到线"弹"一下。
            _a = self._edge_a.get(_k, 1.0 if _ok else 0.0)
            if ghost:
                _a += ((1.0 if _ok else 0.0) - _a) * min(1.0, _dt * 3.2)
                self._edge_a[_k] = _a
            if _a <= 0.03:
                continue
            pa = pos.get(self._key_of(e["f"]))
            pb = pos.get(self._key_of(e["t"]))
            if pa is None or pb is None:
                continue
            x1, y1, x2, y2 = float(pa[0]), float(pa[1]), float(pb[0]), float(pb[1])
            _alg = _offs.get(_k, 0.0)
            _o2 = self._edge_o.get(_k, _alg)
            if ghost:
                _o2 += (_alg - _o2) * min(1.0, _dt * 5.0)
                self._edge_o[_k] = _o2
            if abs(_o2) > 0.05:
                _dx3, _dy3 = x2 - x1, y2 - y1
                _n3 = math.hypot(_dx3, _dy3) or 1.0
                x1 += -_dy3 / _n3 * _o2; y1 += _dx3 / _n3 * _o2
                x2 += -_dy3 / _n3 * _o2; y2 += _dx3 / _n3 * _o2
            col = col_of.get(e.get("sig_kind") or e["kind"], QColor("#8b949e"))
            if ghost:
                # 文字块**之下**先透描一遍 (字压线: 字仍可读, 线也没有"断"的错觉); 全部虚线, 同相位
                # 2026-10-16 看图: 这一遍画在球体之后 ⇒ 线穿过球面(z 序错)。用 clip 把球体挖掉。
                c2 = QColor(col); c2.setAlpha(int(86 * _a))
                g = QPen(c2, 2.9, Qt.CustomDashLine)
                g.setCapStyle(Qt.FlatCap)
                g.setDashPattern([7.0 / 2.9, 6.0 / 2.9]); g.setDashOffset((self._phase * 1.6) / 2.9)
                p.setPen(g)
                p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
                continue
            core = QColor(col); core.setAlpha(int(236 * _a))
            glow = QColor(col); glow.setAlpha(int(60 * _a))
            pen_w = 2.9
            # 慢速流动虚线: 长划 6px / 间隔 4px ⇒ 人眼看得清"是虚线", 相位每次 tick 走 0.5px (60ms/格)
            _dash, _gap = 7.0, 6.0          # 像素单位 (与笔宽解耦: 两支笔的划/隔必须同一像素几何)
            _slen = math.hypot(x2 - x1, y2 - y1)
            if _slen < 70.0:                # 看图: 火星→地球只 8px ⇒ 7/6 只剩 1 段划, 认不出是线
                _dash, _gap = 4.0, 3.0
            for pen, w in ((glow, pen_w + 4.4), (core, pen_w)):
                q = QPen(pen, w, Qt.CustomDashLine)
                q.setCapStyle(Qt.FlatCap)      # 关键: 默认方帽把每段划两端各外扩半个笔宽 ⇒ 间隔被吃掉
                q.setDashPattern([max(0.15, _dash / w), max(0.15, _gap / w)])
                q.setDashOffset((self._phase * 1.6) / w)
                p.setPen(q)
                p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
            mx = x1 + (x2 - x1) * 0.62                 # 方向箭头 (虚线也标方向)
            my = y1 + (y2 - y1) * 0.62
            self._arrow(p, x1, y1, x2, y2, mx, my, core, 3.4)

    def _arrow(self, p, x1, y1, x2, y2, x, y, col, size):
        ang = math.atan2(y2 - y1, x2 - x1)
        p.setPen(QPen(col, 1.4))
        p.drawLine(QPointF(x, y), QPointF(x - size * math.cos(ang - 0.42), y - size * math.sin(ang - 0.42)))
        p.drawLine(QPointF(x, y), QPointF(x - size * math.cos(ang + 0.42), y - size * math.sin(ang + 0.42)))

    @staticmethod
    def _key_of(nid):
        for key, bid, _cn, _must in BODIES:
            if bid == nid:
                return key
        return None

    def _ext_positions(self, cx, cy, R):
        """体系外邻居: 均布在外圈球壳上 (确定性: 按 id 排序 ⇒ 每次同一位置, 不随机跳)。"""
        out = {}
        n = max(1, len(self._ext))
        for i, nid in enumerate(self._ext):
            a = 2 * math.pi * i / n + 0.35
            z = 0.34 * (1.0 if i % 2 else -1.0)                  # 交错前后, 有点立体感
            rr = 1.06
            x, y, _z = self._proj(rr * math.cos(a), rr * math.sin(a) * 0.72, z, cx, cy, R)
            out[nid] = (x, y)
        return out


    # ── 文字: 量宽 · 按分隔符换行 (宁可换行也不"…"截断) · 带底文字块 (防被线/球压) ─────
    def _fm(self, size, bold=False):
        return _cached_fm(size, bold)

    def _wrap(self, text, width, size=9, sep=" · "):
        """按 `sep` 切段塞进 width 像素 (量宽用 QFontMetrics) —— 塞不下不截断, 交给下一行。"""
        _k = (str(text), round(float(width), 1), int(size), sep)
        _hit = _WRAP_CACHE.get(_k)
        if _hit is not None:
            return list(_hit)                      # 值在变但行只跟 (文本,宽,字号) 有关 ⇒ 同帧复用
        fm = self._fm(size)
        words, lines, cur = [], [], ""
        for part in str(text).split(sep):
            words.append(part)
        for i, w in enumerate(words):
            piece = w if cur == "" else sep + w
            if fm.horizontalAdvance(cur + piece) > width and cur:
                lines.append(cur)
                cur = w
            else:
                cur += piece
        if cur:
            lines.append(cur)
        _out = lines or [""]
        if len(_WRAP_CACHE) > 3000:          # 值在变 ⇒ 键会一直新增, 必须设上限, 否则自己变成泄漏源
            _WRAP_CACHE.clear()
        _WRAP_CACHE[_k] = tuple(_out)
        return list(_out)

    def _foot_lines(self, W):
        """底部图注 (2026-10-19 老倪「不要显示那么多字, 精简」: 由 8~9 行砍到 3 行, 字号 9→11)。
        保留可复核锚点: 真源: / 帧龄 / 节点映射核对 (判据 F2) · L2~L5 (判据 S13) · 角度映射 (F1)。
        细节 (每条连线/每个角度映射到哪个量) 全在悬停卡与 tooltip 里, 不占画面。"""
        s = self.data.body.get("sun", {})
        nv = self.info.get("checked", {})
        miss = [k for k, v in nv.items() if not v.get("在")]
        _age = ("%.1fs" % s["帧龄"]) if isinstance(s.get("帧龄"), (int, float)) else "—"
        _L = getattr(self.data, "layers", {}) or {}
        def _glyph(nm):
            _d = _L.get(nm, {})
            if _d.get("ok") and _L.get("k") == "live":
                return "●"
            if _d.get("ok") and _L.get("k") == "stale":
                return "◐"
            return "○"
        _lg = " ".join("%s%s" % (nm, _glyph(nm)) for nm in ("L5", "L4", "L3", "L2"))
        _run = "" if getattr(self.data, "running", False) else " · ⏸ 未运行"
        # 2026-10-19 再精简: 4 行 → 3 行短句 (每项都留着, 只是不再写解释性长句)
        out = [
            "线义: 青=几何 金=性能 绿=动作 紫=反馈",
            "L2~L5: %s · 帧龄 %s · 球位=角度映射" % (
                _lg,
                ((" %.0fs" % _L["age"]) if isinstance(_L.get("age"), (int, float)) else "无")),
            "真源 engine/torque_live/skill · %.1fs · 核对 %d/%d%s" % (
                float(_age.rstrip("s")) if _age.endswith("s") else 0.0,
                len(BODIES) - len(miss), len(BODIES), _run),
        ]
        if miss:
            out.append("⚠ 缺源: %s" % ",".join(miss))
        return out

    def _block(self, p, lines, x, y, w, color, size=9, frame=True):
        """画一块文字 (带半透明底 + 细框 ⇒ 压在环/线上也读得清) —— 返回外接矩形。"""
        lines = [str(t) for t in lines if str(t) != ""]
        if not lines:
            return QRectF()
        fm = self._fm(size)
        h = self.LH * len(lines) + 4
        rect = QRectF(x, y, w, h)
        if frame:
            p.setPen(QPen(QColor(52, 68, 86, 210), 1))
            p.setBrush(QColor(13, 17, 23, 222))     # 222: 既压得住线, 又让线隐约透出来
            p.drawRoundedRect(rect, 3, 3)
        p.setPen(color)
        p.setFont(_cached_font(size))
        for i, t in enumerate(lines):
            p.drawText(QRectF(rect.x() + 4, rect.y() + 2 + i * self.LH, rect.width() - 8, self.LH),
                       Qt.AlignLeft | Qt.AlignVCenter, t)
        return rect

    def _body_short(self, key, d):
        """标签上只放**一行**关键量 (老倪 2026-10-19: 字少、字大)。全量在悬停卡 _hover 里。"""
        def _f(v, fmt="%.3f"):
            return (fmt % v) if isinstance(v, (int, float)) else "—"
        if key == "mercury":
            pr = d.get("progress")
            return ("%.0f%%" % (pr * 100)) if isinstance(pr, (int, float)) else "—"
        if key == "earth":
            return "%s m/s" % _f(d.get("req_mps"), "%.2f")
        if key == "mars":
            return "λ %s" % _f(d.get("lambda"), "%.2f")
        if key == "jupiter":
            return "η %s" % _f(d.get("eta"), "%.2f")
        if key == "moon":
            return "残差 %s" % _f(d.get("err"), "%.2f")
        return ""

    def _sun_text_short(self, s):
        """太阳只写两个数: M (标定) + T (在跑才有)。"""
        if not isinstance(s.get("M"), (int, float)):
            return "真源不可用"
        if not getattr(self.data, "running", False):
            return "M=%.2f 未运行" % s["M"]
        t = "M=%.2f" % s["M"]
        if isinstance(s.get("T_norm"), (int, float)):
            t += " T=%.0f%s" % (s["T_norm"], "≤" if s.get("clip") else "")
        return t

    def _body_line(self, key, d):
        """球下的真值一行 (完整短句, 不截断); 取不到 ⇒ 诚实文案。"""
        return self._body_text(key, d)

    RIGHT_COL = True          # 文字描述固定在右侧竖栏 (老倪 2026-10-19: 不要飘, 不要动)
    COL_W = 380.0             # 右侧栏最大宽度 (px)          # 文字描述固定在右侧竖栏 (老倪 2026-10-19: 不要飘, 不要动)

    def _s3_visible(self, W):
        """窗口太窄时卡片放不下 (会压住轨道/文字) ⇒ 不画; S³ 的数仍在右栏 q̂合/q̂主 两行里。"""
        _col = self._col_w(W) if self.RIGHT_COL else 0
        return (W - _col - self._s3_w(W) - 30.0) >= 200.0

    def _s3_w(self, W):
        """左下「S³ 力场」卡宽度 (放大的合力小窗): 窄窗收窄, 宽窗到 350px。"""
        return float(min(392.0, max(260.0, W * 0.32)))

    def _col_w(self, W):
        """右侧文字栏宽度 (内容自适应, 但**固定**不变 ⇒ 文字不会左右挪)。"""
        return float(min(self.COL_W, max(240, int(W * 0.36))))

    def _label_blocks_right(self, pos, b, cx, cy, R, S, W, H):
        """右侧固定文字栏 (老倪 2026-10-19: 「文字描述不要飘来漂去, 都靠右侧显示, 不要动」)。

        · 行序固定: 太阳 → 水星 → 地球 → 月球 → 火星 → 木星 → SK 群; 每行**一行字**, 不换行;
        · 位置固定: 右边缘贴 W-6, 宽度按文字自适应 (文字不变 ⇒ 位置不变), 与数据跳动无关;
        · 归属靠 1px 淡引线 (引线跟着球连续走 —— 线可以动, 字不动)。
        """
        _run_all = bool(getattr(self.data, "running", False))
        colw = self._col_w(W)
        # 老倪 2026-10-19「字太小, 字数太多, 要精简」: 角色名压到 2 个字, 详细口径全在悬停卡
        names = {"sun": "☀ 太阳·中心", "mercury": "☿ 水星·接触",
                 "earth": "♁ 地球·前馈", "moon": "🌙 月球·校正",
                 "mars": "♂ 火星·DiT", "jupiter": "♃ 木星·性能"}
        rows = []
        for key in ("sun", "mercury", "earth", "moon", "mars", "jupiter"):
            head, col = names[key], QColor(self.COL[key])
            if key == "sun":
                body = self._sun_text_short(b.get("sun", {}))
            elif not _run_all:
                body = "未运行"          # 后台常驻引擎一直在写文件 ⇒ 未运行时不许让数字继续跳
            else:
                body = self._body_short(key, b.get(key, {})) or "无真源"
            # 一行: 状态字形 + 天体/节点名 + 关键量 (详细口径在悬停卡)
            rows.append((key, "%s %s %s" % (self._st_glyph(b.get(key, {})), head, body), col))
        # 卫星: 8 颗 SK 合成一行 (逐颗浮动标号会跟着地球转 = 飘, 老倪不要)
        _sats = (b.get("sats", {}).get("list") or [])
        _ids = [str(d.get("SK") or "") for d in _sats if d.get("SK")]
        # 地球合力一行 (粗箭头那个数): 合力模长 + 主力↔合力夹角 + 一致度
        _fE = getattr(self.data, "fE", {}) or {}
        _run = bool(getattr(self.data, "running", False))
        if _run and _fE:
            rows.append((None, "F合 %.2f m/s · Δ主↔合 %.0f°"
                         % (_fE.get("mag") or 0.0, _fE.get("dev") or 0.0),
                         QColor("#58a6ff")))
        else:
            # 未运行: 行不能消失 (行数一变整列就跳), 但必须写清"未运行", 不拿后台文件冒充实时力
            rows.append((None, "F合 ⏸ 未运行" + (" (定格)" if _fE else ""), QColor("#6e7681")))
        # 四元数行: 每层一行 (q̂ = 归一四元数, 平方和=1; 颜色=该层天体色 ⇒ 一眼对应)
        # 四元数: 只留两个 —— 合力 q̂ (整个力场的方向) 与 主力 q̂ (u_ff), 其余在悬停卡里
        _qq = getattr(self.data, "quat", {}) or {}
        # 主力层: α>1 时是前馈 L4 —— **但档位没跑到 L4 时它没输出** (只跑 L2 ⇒ 主力就是 L2)
        _ql = (getattr(self.data, "quat", None) or {})
        _main_L = ("L4" if (float(getattr(self.data, "alpha", 1.0) or 1.0) > 1.0
                           and (_ql.get("L4") or {}).get("q")) else "L2")
        if not (_ql.get(_main_L) or {}).get("q"):
            _main_L = next((k for k in ("L2",) if (_ql.get(k) or {}).get("q")), _main_L)
        for _L, _nm, _k in (("合", "合", None), (_main_L, "主", "jupiter" if _main_L == "L4" else "earth")):
            _src = (_fE.get("q") if _L == "合" else ((_qq.get(_L) or {}).get("q")))
            if _src:
                _txt = "q̂%s %+.2f %+.2f %+.2f %+.2f" % (_nm, _src[0], _src[1], _src[2], _src[3])
                if not _run:
                    _txt = "⏸ " + _txt
            else:
                _txt = "q̂%s 未运行" % _nm if not _run else ("q̂%s 未算" % _nm)
            rows.append((None, _txt, QColor("#58a6ff" if _L == "合" else self.COL.get(_k, "#4da3ff"))))
        _sk_txt = ("SK%s…SK%s" % (_ids[0][-2:], _ids[-1][-2:]) if len(_ids) > 1
                   else ("SK%s" % _ids[0][-2:] if _ids else "无卫星"))
        rows.append((None, "● %s" % _sk_txt, QColor("#8ee6c8")))
        _gap = 7.0
        _h = float(self.LH + 6)      # 行高 24 + 6 = 30px/行 (17px 字不挤)
        _avail = H - 70.0 - (6 + self.LH * len(self._foot_lines(W)))   # 起点 y=46 (让出标题带) + 底边留白
        while len(rows) * (_h + _gap) - _gap > _avail and _gap > 1.0:
            _gap -= 1.0
        y = 46.0
        out, placed = [], []
        self._lead_of = {}          # 文字↔球体不画连线 (老倪 2026-10-19: 太乱), 只靠颜色对应
        for _i, (key, text, col) in enumerate(rows):
            _w = min(colw, max(150.0, self._fm(20).width(text) + 18.0))
            rect = QRectF(W - 14.0 - _w, y, _w, _h)         # 右边缘钉住 ⇒ 视觉不挪 (留 14px 不贴画布边)
            out.append((rect, [text], col, 20))
            _p = pos.get(key) if key else pos.get("earth")
            _bx, _by = float(_p[0]), float(_p[1]) if _p else cy
            self._lead_of[_i] = (_bx, _by, col)      # 只记归属 (供 hover/判据), **不画引线**
            placed.append(rect)
            y += _h + _gap
        return out, placed

    def _label_blocks(self, pos, b, cx, cy, R, S, W, H):
        """算出**所有文字块的外接矩形** (先避让再画) —— 判据 J1 用它核「任何两块文字不重叠」。

        避让规则 (老倪 2026-10-16 看图: 月球标签压地球标签 / 金球压水星参数行):
          · 每颗行星的标签沿"离太阳"的径向往外让 (r + 26px 起), 太阳球体再也压不住它;
          · 月球标签沿"离地球"的方向让 (不与地球标签同侧);
          · 与已放置的块/球体圆/卫星圈相交 ⇒ 沿自己的方向每次推 6px, 最多 26 次。
        块宽 208px (与侧栏 682px 宽兼容), 每行 11px。
        """
        if self.RIGHT_COL:
            return self._label_blocks_right(pos, b, cx, cy, R, S, W, H)
        w = min(228.0, max(150.0, W - 24))
        pad_top, pad_bot = 24, 14 + self.LH * len(self._foot_lines(W))
        placed, out = [], []

        def keepouts():
            ks = [(cx, cy, S * self.RAD["sun"] + 4)]                     # 太阳球体
            for k in ("mercury", "earth", "mars", "jupiter"):
                x, y, _z = pos[k]
                ks.append((x, y, S * self.RAD[k] + 3))
            for x, y, _z, _sk in pos["_sat"]:
                ks.append((x, y, S * self.RAD["sat"] + 4))
            mx, my, _mz = pos["moon"]                    # 2026-10-16 看图: 漏了月球 ⇒ 标签曾压在月球上
            ks.append((mx, my, S * self.RAD["moon"] + 4))
            for _blk2, _ln2, _c2, _s2 in out:             # 已放好的卫星 SK 号码也是障碍
                ks.append((_blk2.center().x(), _blk2.center().y(),
                           max(_blk2.width(), _blk2.height()) / 2.0 + 3.0))
            return ks

        # 逐颗卫星写 SK 号 (2026-10-16 老倪: 「我看原子技能 SK01~SK08, 那就只是显示 8 个绕地球的卫星」)
        #   布局是**确定性的**: 每颗号码放在该卫星的径向外侧 (环外), 半径奇偶错开 11px ⇒
        #   相邻两颗的号码不会叠; 若撞到月球/地球/行星或已有块, 就绕角度 ±22.5° 再试 (最多 4 次)。
        _ks_sat = keepouts()
        for _i, (_x, _y, _z, _sk) in enumerate(pos["_sat"]):
            _ux, _uy = _x - pos["earth"][0], _y - pos["earth"][1]
            _n = math.hypot(_ux, _uy) or 1.0
            # 环外偏移必须 ≥ 块的半宽(16) + 卫星 keepout(球半径+4) ⇒ 26px 起 (14.9px 时会差 1px 压到自己那颗卫星)
            _rr0 = S * self.RAD["sat"] + 34.0 + (17.0 if _i % 2 else 0.0)
            _blk, _clean = None, None
            for _k in range(7):
                _ang = (0.0, 0.3927, -0.3927, 0.7854, -0.7854, 1.1781, -1.1781)[_k]   # 0/±22.5°/±45°/±67.5°
                _cs, _sn = math.cos(_ang), math.sin(_ang)
                _vx = _ux / _n * _cs - _uy / _n * _sn
                _vy = _ux / _n * _sn + _uy / _n * _cs
                _cand = QRectF(_x + _vx * _rr0 - 16.0, _y + _vy * _rr0 - 7.0, 32.0, 14.0)
                _cand = QRectF(min(max(_cand.x(), 6.0), W - 38.0),      # 边距 6px (判据 O5: 不贴边框)
                               min(max(_cand.y(), pad_top + 2.0), H - pad_bot - 16.0), 32.0, 14.0)
                _blk = _cand
                # 间隙要求 ≥3px (判据 M3: 两块只隔 1px 就算"贴住")
                if any(_cand.adjusted(-3, -3, 3, 3).intersected(r).isEmpty() is False for r in placed):
                    continue
                _bad = False
                for (kx, ky, kr) in _ks_sat:
                    nx = max(_cand.x(), min(kx, _cand.x() + _cand.width()))
                    ny = max(_cand.y(), min(ky, _cand.y() + _cand.height()))
                    if math.hypot(nx - kx, ny - ky) < kr + 1:
                        _bad = True
                        break
                if not _bad:
                    _clean = _cand
                    break
            if _clean is None:
                # 7 个候选全冲突 ⇒ 兜底进页边栏空槽 (2026-10-16: 否则最后一块会与邻块只隔 1px, 判据 M3 红)
                _clean = self._gutter_slot([str(_sk)], placed, _ks_sat, W, H, pad_top, pad_bot, 32.0) or _cand
            _blk = _clean
            _col = GOLD if _sk == b.get("sats", {}).get("active") else QColor("#9fe3d6")
            out.append((_blk, [str(_sk)], _col, 8))
            placed.append(_blk)

        def _fmw(text, size=9):
            _k = (str(text), int(size))
            _w = _FM_W.get(_k)
            if _w is None:
                _w = _cached_fm(size).horizontalAdvance(str(text))
                if len(_FM_W) > 20000:
                    _FM_W.clear()
                _FM_W[_k] = _w
            return _w

        def _fit_lines(lines, size=9, cap=228.0, floor=90.0):
            """块宽自适应: 先按最长行定宽 (上限 cap), 再按这个宽把过长的行折行; 返回 (宽, 行表)。"""
            widest = max([_fmw(l, size) for l in lines] or [80])
            w0 = min(cap, max(floor, float(widest) + 14.0))
            out2 = []
            for l in lines:
                out2 += ([l] if _fmw(l, size) + 14.0 <= w0 else self._wrap(l, int(w0 - 10), size))
            widest2 = max([_fmw(l, size) for l in out2] or [80])
            return min(cap, max(floor, float(widest2) + 14.0)), out2

        def place_near(x, y, lines, color, size, ux, uy, own_r):
            """把文字块贴到 (x,y) 这颗球的**外侧**: 块的近边离球 own_r+12px, 朝 (ux,uy) 展开。

            坑 (真踩过): 块宽 228 而径向偏移只有 ~47px ⇒ 以 anchor 为中心的块会反过来盖住自己的球,
            每个候选位置都被自身球的 keep-out 判"冲突", 最后退化成重叠最小者(跑到画布另一头)。
            所以径向偏移必须 ≥ 块在该方向上的半宽 + own_r。
            再在候选方向 (径向 → ±45° → ±90° → ±135° → 反向) 上 6px 步扫, 先 clamp 再判冲突。
            """
            w, lines = _fit_lines(lines, size)
            h = self.LH * len(lines) + 4
            ks = keepouts()

            self._lead_of = getattr(self, "_lead_of", {})

            def _fin(rect):
                """块离自己的球太远 ⇒ 记一条引线 (2026-10-16 看图: 月球块孤零零挂左下角认不出归属)。
                口径按"块矩形到该球**球面**的距离", 不是块心到球心 (宽块贴球时块心本来就远)。"""
                _nx2 = max(rect.x(), min(x, rect.x() + rect.width()))
                _ny2 = max(rect.y(), min(y, rect.y() + rect.height()))
                self._lead_of[len(out)] = (float(x), float(y), color)
                _surf = max(0.0, math.hypot(_nx2 - x, _ny2 - y) - own_r)
                if _surf > 45.0:
                    self._leaders.append((rect, float(x), float(y), color))
                return rect

            def rect_at(ox, oy):
                if abs(ux) >= abs(uy):                         # 主要横向: 块的近边贴球
                    px = x + own_r + 12 if ux >= 0 else x - own_r - 12 - w
                    py = y + oy - h / 2.0
                    px += ox
                else:                                          # 主要纵向
                    px = x + ox - w / 2.0
                    py = y + own_r + 12 if uy >= 0 else y - own_r - 12 - h
                    py += oy
                r = QRectF(px, py, w, h)
                if r.x() < 6:
                    r.moveLeft(6)                                # 看图: 木星块 clamp 到 x=W-2 贴死边框
                if r.x() + r.width() > W - 6:
                    r.moveLeft(max(6, W - 6 - r.width()))
                if r.y() < pad_top:
                    r.moveTop(pad_top)
                if r.y() + r.height() > H - pad_bot:
                    r.moveTop(max(pad_top, H - pad_bot - r.height()))
                return r

            base = math.atan2(uy, ux)
            best, best_ov = None, None
            for ang in [base + d for d in (0.0, 0.7854, -0.7854, 1.5708, -1.5708, 2.3562, -2.3562, 3.1416)]:
                dx, dy = math.cos(ang), math.sin(ang)
                for k in range(0, 26):
                    rect = rect_at(dx * 6 * k, dy * 6 * k)
                    ov = 0.0
                    for r in placed:
                        inter = rect.intersected(r)
                        if not inter.isEmpty():
                            ov += inter.width() * inter.height()
                    for (kx, ky, kr) in ks:
                        nx = max(rect.x(), min(kx, rect.x() + rect.width()))
                        ny = max(rect.y(), min(ky, rect.y() + rect.height()))
                        dd = math.hypot(nx - kx, ny - ky)
                        if dd < kr:
                            ov += (kr - dd) * 60.0
                    if ov <= 0.0:
                        placed.append(rect)
                        out.append((rect, lines, color, size))
                        return _fin(rect)
                    if best_ov is None or ov < best_ov:
                        best, best_ov = rect, ov
            # 兜底 (2026-10-16 看图: 地球区 三条标签互压 —— "重叠最小者"在拥挤区就等于重叠):
            # 候选方向全冲突 ⇒ 放进**左侧/右侧页边栏**的第一个空槽 (先 clamp 再逐 8px 下移找位),
            # 槽位同样对 已放置块/球体/底栏 做 keep-out ⇒ 保证任何两块文字不重叠。
            fb = self._gutter_slot(lines, placed, ks, W, H, pad_top, pad_bot, w)
            if fb is not None:
                placed.append(fb)
                out.append((fb, lines, color, size))
                return _fin(fb)
            placed.append(best)
            out.append((best, lines, color, size))
            return _fin(best)

        # 2026-10-16 看图: 画面只有节点名, 认不出天体 ⇒ 标题带上**天体名 + 结点名**
        self._lead_of = {}
        names = {"mercury": "☿ 水星 · 接触流形", "earth": "♁ 地球 · 前馈加速器",
                 "mars": "♂ 火星 · DiT 动作头", "jupiter": "♃ 木星 · 性能流形"}
        for key in ("mercury", "mars", "jupiter", "earth"):
            x, y, _z = pos[key]
            ux, uy = x - cx, y - cy
            n = math.hypot(ux, uy) or 1.0
            ux, uy = ux / n, uy / n
            # 2026-10-19 老倪「字体太小 / 不要那么多字」⇒ 每颗球只留 2 行: 名字 + 1 行关键量
            _st = (b.get(key, {}) or {}).get("st") or {}
            _tail = "" if _st.get("k") == "live" else (" · %s" % (_st.get("txt") or ""))
            lines = ["%s %s" % (self._st_glyph(b.get(key, {})), names[key]),
                     (self._body_short(key, b.get(key, {})) or "无真源") + _tail]
            place_near(x, y, lines, FG if key != "earth" else QColor("#cfe4ff"), 12,
                       ux, uy, S * self.RAD[key])
        # 太阳 (贴球底)
        slines = ["%s ☀ 太阳 · 流形引擎" % self._st_glyph(b.get("sun", {})),
                  self._sun_text_short(b.get("sun", {}))]
        place_near(cx, cy, slines, GOLD, 12, 0.0, 1.0, S * self.RAD["sun"])
        # 卫星群 (绕地球的那一圈的外侧)
        # 月球 (沿"离地球"方向往外)
        mx, my, _mz = pos["moon"]
        ux, uy = mx - pos["earth"][0], my - pos["earth"][1]
        n = math.hypot(ux, uy) or 1.0
        # own_r 原先写成 _mr/2.0 ⇒ 月球标签被推到"地球-月球连线中点之外", 结果压在卫星圈上;
        # 换成 (月球球半径 + 12) ⇒ 近边贴月球外侧 (2026-10-16)
        place_near(mx, my, ["%s 🌙 月球 · 状态校正器" % self._st_glyph(b.get("moon", {}))], QColor("#dfe4ec"), 12,
                   ux / n, uy / n,
                   S * self.RAD["moon"] + 12)
        # 收尾防撞 (2026-10-16 看图/判据 J1: 加了 8 个卫星 SK 号之后, 拥挤区可能仍有两块相交):
        #   逐对检查, 相交的把**后一块**改放页边栏空槽; 槽位也撞就保持原位 (判据会报出来, 不藏着)。
        # 2026-10-16 第三轮看图: 判据 K1 换一帧真源就红(1 块压火星) ⇒ 块↔球也进防撞:
        #   块到任一球面(球半径+8px keep-out)不足 ⇒ 同样改放页边栏空槽。
        _ksF = keepouts()
        for _i in range(len(out)):
            _ri = out[_i][0]
            _badF = False
            for (_kx, _ky, _kr) in _ksF:
                _nx3 = max(_ri.x(), min(_kx, _ri.x() + _ri.width()))
                _ny3 = max(_ri.y(), min(_ky, _ri.y() + _ri.height()))
                if math.hypot(_nx3 - _kx, _ny3 - _ky) < _kr + 4.0:
                    _badF = True
                    break
            if not _badF:
                continue
            _rest = [t2[0] for _k2, t2 in enumerate(out) if _k2 != _i]
            _slot = self._gutter_slot(out[_i][1], _rest, _ksF, W, H, pad_top, pad_bot, _ri.width())
            if _slot is not None:
                out[_i] = (_slot, out[_i][1], out[_i][2], out[_i][3])
        for _i in range(len(out)):
            for _j in range(_i + 1, len(out)):
                _ri, _rj = out[_i][0], out[_j][0]
                if _ri.intersected(_rj).isEmpty():
                    continue
                _rest = [t2[0] for _k2, t2 in enumerate(out) if _k2 not in (_i, _j)]
                _slot = self._gutter_slot(out[_j][1], _rest, keepouts(), W, H, pad_top, pad_bot, _rj.width())
                if _slot is not None:
                    out[_j] = (_slot, out[_j][1], out[_j][2], out[_j][3])
        return out, placed

    def _gutter_slot(self, lines, placed, ks, W, H, pad_top, pad_bot, w):
        """页边栏空槽 (保证不重叠的兜底位置) —— 候选方向全冲突时用 (2026-10-16 看图: 地球区三条互压)。"""
        h = self.LH * len(lines) + 4
        for xg in (6.0, W - 6.0 - w):                 # 先左栏, 再右栏
            y = float(pad_top) + 4.0
            while y + h <= H - pad_bot - 2:
                rect = QRectF(xg, y, w, h)
                ok = True
                for r in placed:
                    if not rect.adjusted(-3, -3, 3, 3).intersected(r).isEmpty():   # 槽位也要留 ≥3px
                        ok = False
                        break
                if ok:
                    for (kx, ky, kr) in ks:
                        nx = max(rect.x(), min(kx, rect.x() + rect.width()))
                        ny = max(rect.y(), min(ky, rect.y() + rect.height()))
                        if math.hypot(nx - kx, ny - ky) < kr:
                            ok = False
                            break
                if ok:
                    return rect
                y += h + 4.0                 # 原为 8px 步进 < 块高 15 ⇒ 相邻槽位只隔 1px (判据 M3 红)
        return None

    def label_rects(self):
        """给判据用: 当前布局下所有文字块矩形 (两两不许重叠)。"""
        W, H, S, cx, cy, R = self._geom()
        pos = self.positions(cx, cy, R)
        out, _placed = self._label_blocks(pos, self.data.body, cx, cy, R, S, W, H)
        # 2026-10-16: 返回**最终**矩形 (收尾防撞会改块位置 —— 之前返回 placed 会与真正画出来的不一致,
        # 判据量到的是改前的旧位置)
        return [t[0] for t in out]

    def label_texts(self):
        """给判据用: [(矩形, 行表)] —— 核"每个天体都有带名字的块" / "块宽自适应"。"""
        W, H, S, cx, cy, R = self._geom()
        pos = self.positions(cx, cy, R)
        out, _placed = self._label_blocks(pos, self.data.body, cx, cy, R, S, W, H)
        return [(t[0], list(t[1])) for t in out]

    def _labels(self, p, pos, cx, cy, R, b, W, H, S):
        """画文字块 —— **位置低通**: 布局给的 target 会随球走/避让切换而瞬移,
        直接按 target 画就是"文字块跳一下"; 这里每帧只朝 target 走 40%
        (2026-10-19 老倪「太阳系所有显示禁止跳跃」), 引线也用平滑后的块位算, 否则引线跟块脱节。"""
        blocks, _placed = self._label_blocks(pos, b, cx, cy, R, S, W, H)
        _dt = getattr(self, "_dt", self.TICK_MS / 1000.0)
        if not hasattr(self, "_lbl_pos"):
            self._lbl_pos = {}
        _k = min(1.0, _dt * 6.0)
        _lead = getattr(self, "_lead_of", {})
        _shown = []
        for _i, (rect, lines, color, size) in enumerate(blocks):
            # key 用"去掉状态字形后的首行" —— 状态一变字形就从 ● 变 ◐/○, 若拿整行当 key
            # 会当成"新块"⇒ 直接落位 = 跳一下 (2026-10-19)
            _key = (lines[0].split(" ", 1)[-1] if lines else "") or str(_i)
            _cur = self._lbl_pos.get(_key)
            if _cur is None:
                _cur = QPointF(rect.x(), rect.y())
            else:
                # 指数逼近 + **单帧位移上限 14px**: 布局 target 从画面一侧换到另一侧 (避让切换) 时,
                #   纯指数逼近一步就能走 160px ⇒ 看着还是"跳"; 有上限就变成 1s 左右的滑动。
                _dx, _dy = rect.x() - _cur.x(), rect.y() - _cur.y()
                _d = math.hypot(_dx, _dy)
                if _d > 0.4:
                    _step = min(_d, max(2.5, min(14.0, _d * _k)))
                    _cur = QPointF(_cur.x() + _dx / _d * _step, _cur.y() + _dy / _d * _step)
                else:
                    _cur = QPointF(rect.x(), rect.y())          # 残差吸附, 免得永远差一点
            self._lbl_pos[_key] = _cur
            _r2 = QRectF(_cur.x(), _cur.y(), rect.width(), rect.height())
            self._block(p, lines, _r2.x(), _r2.y(), _r2.width(), color, size, frame=False)
            if _i in _lead:
                _shown.append((_r2, _lead[_i]))
        # 引线已按老倪要求删除 (2026-10-19: 「把文字与球体的连线去掉, 太乱了; 有颜色对应就可以了」)

    @staticmethod
    def _fit_text(p, text, width):
        try:
            return p.fontMetrics().elidedText(str(text), Qt.ElideRight, int(max(24, width)))
        except Exception:                                                    # noqa: BLE001
            return str(text)

    def _legend(self, p, W, H, b):
        """底部图注: **完整** (自动换行, 不省略号截断) —— 行数已经算进 _geom 的底栏高度。"""
        lines = self._foot_lines(W)
        p.setPen(FOOT)
        p.setFont(_cached_font(14))          # 2026-10-19 看图: 11px 太小, 与正文 20px 差太多
        y0 = H - 8 - self.LH * len(lines)
        p.setFont(_cached_font(14))
        for i, t in enumerate(lines):
            p.drawText(QRectF(4, y0 + i * self.LH, W - 8, self.LH), Qt.AlignLeft | Qt.AlignVCenter, t)

    def _sphere(self, p, x, y, r, col, energy=None):
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

    def _body_text(self, key, d):
        """每个球下方的真值一行 (取不到 ⇒ 写"未算/未测", 不填 0 不编数)。"""
        if key == "mercury":
            if not isinstance(d.get("progress"), (int, float)):
                return d.get("note") or "流形量未算 (无真帧)"
            # 2026-10-16 看图: 这里原为 str(state)[:10] 硬截 ⇒ 图上渲染成「自由空间 (无接触约」(断句,
            #   框内还空 150px)。改为**整串写全**(块宽由最长行量出, 太长才由 _fit 省略)。
            _st = str(d.get("state") or "")
            return "‖e∥‖=%.4fm · ‖e⊥‖=%.4fm · %s" % (d["progress"], d.get("risk") or 0.0, _st)
        if key == "jupiter":
            if not isinstance(d.get("eta"), (int, float)):
                return d.get("note") or "流形量未算 (无真帧)"
            return "V_p=%.3g · η=%.3f" % (d.get("V_p") or 0.0, d["eta"])
        if key == "earth":
            if not isinstance(d.get("req_mps"), (int, float)):
                return "前馈请求未测 (无在职技能)"
            return "u_ff=%.2f m/s · %s" % (d["req_mps"], "可行" if d.get("可行") else "削")
        if key == "mars":
            if not isinstance(d.get("action_norm"), (int, float)):
                return "动作头未跑"
            return "‖a‖=%.3f · 条件 %d 路" % (d["action_norm"], int(d.get("cond_n") or 0))
        return ""

    @staticmethod
    def _st_glyph(d):
        """运行态字形: ● 在跑 · ◐ 陈旧 · ○ 离线 (数据侧算的, 不是猜的)。"""
        k = ((d or {}).get("st") or {}).get("k")
        return {"live": "●", "stale": "◐"}.get(k, "○")

    @staticmethod
    def _st_line(d):
        st = ((d or {}).get("st") or {})
        if not st:
            return ""
        a = st.get("age")
        return ("%s · 帧龄 %.1fs" % (st.get("txt") or "", a)) if isinstance(a, (int, float)) \
            else (st.get("txt") or "")

    def _sun_text(self, s):
        if not isinstance(s.get("M"), (int, float)):
            return "真源不可用 (未读 zmax_manifold/engine)"
        t = "M=%.3f · φ=%s · ‖∇Φ‖=%s" % (s["M"],
                                        ("%.3f" % s["phi"]) if isinstance(s.get("phi"), (int, float)) else "—",
                                        ("%.3f" % s["grad_norm"]) if isinstance(s.get("grad_norm"), (int, float)) else "—")
        if not getattr(self.data, "running", False):
            # 没在跑: M 只是标定值, 扭矩不是这一帧推理出来的 ⇒ 不写 T (否则等于把上次的数当实时)
            return t + " · 未运行 (无实时力)"
        if isinstance(s.get("T_norm"), (int, float)):
            t += " · T=%.1f%sN·m" % (s["T_norm"], "≤" if s.get("clip") else "~")
        _drv = getattr(self.data, "drv", {}) or {}
        if _drv:
            # 2026-10-19: 口径本身就是"模型状态"的一部分 —— τ 是解析势场算的, 还是模型张量驱动的?
            if _drv.get("model_tensor"):
                t += " · τ源=模型张量"
            elif _drv.get("src") or _drv.get("x_source"):
                t += " · τ源=解析势场(未接模型张量)"
            if _drv.get("clip") and isinstance(_drv.get("T"), (int, float)):
                t += " · 已限幅(%.0f>%.0f)" % (_drv["T"], _drv.get("T_max") or 0)
        return t
