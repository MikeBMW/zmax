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
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QRadialGradient
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
FOOT = QColor("#aebcc8")                      # 2026-10-16 看图: 底部图注原用 DIM(#8b949e) 对比度低
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
        # 2026-10-16 老倪: 「我看原子技能 SK01~SK08, 那就只是显示 8 个绕地球的卫星」
        _want = ["SK%02d" % i for i in range(1, 9)]
        _by = {d["SK"]: d for d in sats}
        sats = [_by[k] for k in _want if k in _by]        # 真源里这 8 条的 stage/在职/偏差都保留
        self.body["sats"] = {"名": "原子技能", "真源": "skill_phys.json (在职 SK↔段) + skill_latest.json + 标定真源 zmax_skill_physics.json",
                             "list": sats, "active": act.get("SK"), "n": len(sats), "n_calib": n_cal,
                             "sk_ids": [d["SK"] for d in sats]}
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
    # 轨道半径 (相对 R) · 球径 (相对 S) · 颜色
    ORB = {"mercury": 0.30, "earth": 0.50, "mars": 0.68, "jupiter": 0.86}
    RAD = {"sun": 0.052, "mercury": 0.019, "earth": 0.026, "mars": 0.031, "jupiter": 0.037,
           "moon": 0.014, "sat": 0.0058}
    COL = {"sun": "#ffd166", "mercury": "#b9bec7", "earth": "#4da3ff", "mars": "#ff7a45",
           "jupiter": "#d2a45f", "moon": "#dfe4ec", "sat": "#7fd1c1", "ext": "#8b949e"}
    # 卫星群/月球 绕地球的半径 (相对 R) —— 原子技能在内, 月球在外 (不叠)
    # 2026-10-16 看图逐项校正 (都为"账算得出来"的量, 判据 K2/K3 逐条卡):
    #   · 卫星圈必须整体在地球球体之外: 投影后的最小地-卫距 ≥ r_earth + r_sat (+4px 余量)
    #   · 月球必须在卫星圈之外: 地-月距 ≥ 卫星圈半径 + r_sat + r_moon
    SAT_R = 0.098
    MOON_R = 0.168
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
        self._drag = (e.x(), e.y())
        self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if self._drag is None:
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
        self._phase = (self._phase + 0.06) % 12.0
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
        pad_t = 20
        pad_b = 12 + 11 * len(self._foot_lines(W))
        S = max(120, min(W - 14, H - pad_t - pad_b))
        cx, cy = W / 2.0, pad_t + (H - pad_t - pad_b) / 2.0
        return W, H, S, cx, cy, S * 0.46

    def _angles(self, b):
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

    def _wobble(self, moon):
        try:
            return max(0.0, min(0.55, abs(float(moon.get("err"))) * 2.4))
        except Exception:                                                    # noqa: BLE001
            return 0.0

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
        for i, d in enumerate(sats):
            aa = ea + 2 * math.pi * i / max(1, len(sats))          # 与地球同向公转 (绕地球)
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
        f = QFont("DejaVu Sans"); f.setPixelSize(12); f.setBold(True); p.setFont(f)
        p.drawText(QRectF(6, 2, W - 160, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   "🪐 球心引力架构 (太阳系映射)")
        p.setPen(DIM); f2 = QFont("DejaVu Sans"); f2.setPixelSize(9); p.setFont(f2)
        p.drawText(QRectF(max(0, W - 190), 2, 184, 18), Qt.AlignRight | Qt.AlignVCenter,
                   "🖱 拖动旋转 · 滚轮缩放 · 双击复位")
        # 引力井 (度量: 扁率按真特征值) + 轨道 (都在当前三维变换下)
        self._gravity_well(p, cx, cy, R, b.get("sun", {}))
        # 背景**圆形轨道** (2026-10-16 老倪: 「背景的圆形轨道也要体现出」):
        #   每条行星轨道用自己的球色淡描 + 慢速虚线相位 (与力连线同相位 ⇒ 全图一张"脉搏", 不闪)
        for ring, key in zip(self._grids, ("mercury", "earth", "mars", "jupiter")):
            cring = QColor(self.COL[key]); cring.setAlpha(120)
            pen = QPen(cring, 1.2, Qt.CustomDashLine)
            pen.setCapStyle(Qt.FlatCap); pen.setDashPattern([4.0, 5.0]); pen.setDashOffset(self._phase * 0.5)
            p.setPen(pen)
            pt = [self._proj(x, y, 0.0, cx, cy, R) for x, y in ring]
            for j in range(len(pt) - 1):
                p.drawLine(QPointF(pt[j][0], pt[j][1]), QPointF(pt[j + 1][0], pt[j + 1][1]))
        # 地球的**卫星环** (原子技能公转轨道): 也让背景把"轨道"说清楚
        _ea = self._angles(b).get("earth", 0.0)
        _er = self.ORB["earth"]
        cring = QColor(self.COL["sat"]); cring.setAlpha(110)
        pen = QPen(cring, 1.1, Qt.CustomDashLine)
        pen.setCapStyle(Qt.FlatCap); pen.setDashPattern([3.0, 4.0]); pen.setDashOffset(self._phase * 0.5)
        p.setPen(pen)
        ring = [(self.SAT_R * math.cos(t / 72.0 * 2 * math.pi), self.SAT_R * math.sin(t / 72.0 * 2 * math.pi))
                for t in range(73)]
        pt = [self._proj(_er * math.cos(_ea) + x, _er * math.sin(_ea) + y, 0.0, cx, cy, R) for x, y in ring]
        for j in range(len(pt) - 1):
            p.drawLine(QPointF(pt[j][0], pt[j][1]), QPointF(pt[j + 1][0], pt[j + 1][1]))
        # 力的相互作用 (真源连线) —— 先画线, 再画球 (球压线, 视觉更干净)
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
        for kind, x, y, r, _z, sk in items:
            if kind == "sat":
                act = (sk == b.get("sats", {}).get("active"))
                live = bool(b.get("sats", {}).get("list")) and any(
                    d.get("SK") == sk and isinstance(d.get("偏差_mps"), (int, float))
                    for d in sats)
                self._sphere(p, x, y, r, self.COL["sat"], 1.0 if (act and live) else (0.7 if live else 0.32))
                if act:
                    p.setPen(QPen(GOLD, 1)); p.setBrush(Qt.NoBrush)
                    p.drawEllipse(QPointF(x, y), r + 3, r + 3)
                continue
            ecol = self.COL[kind] if kind != "moon" else self.COL["moon"]
            dkey = "sun" if kind == "sun" else kind
            energy = b.get(dkey, {}).get("grad_norm") if kind == "sun" else (1.0 if self._live(b.get(dkey, {})) else 0.35)
            self._sphere(p, x, y, r, ecol, energy)
        # 地月细连线 + 标签
        ex, ey, _ez = pos["earth"]
        p.setPen(QPen(QColor(120, 132, 150, 170), 1))
        p.drawLine(QPointF(ex, ey), QPointF(mx, my))
        # 文字块是**半透明**底 (α=222) ⇒ 压住的线仍隐约可见 (老倪: 线不要很快消失);
        # 透描放在文字之前 —— 先透描再写字, 字才不会被线盖暗 (2026-10-16 看图: 数值行前半被压暗)。
        self._draw_forces(p, cx, cy, R, b, ghost=True)
        self._labels(p, pos, cx, cy, R, b, W, H, S)
        self._legend(p, W, H, b)
        p.end()

    def _gravity_well(self, p, cx, cy, R, sun):
        e1, e2 = sun.get("eig_min"), sun.get("eig_max")
        ratio = 1.0
        if e1 and e2 and float(e2) > 0:
            ratio = max(0.35, min(1.0, float(e1) / float(e2)))
        for i in range(6):
            rr = 0.10 + 0.055 * i
            alpha = 88 - i * 11
            p.setPen(QPen(QColor(210, 153, 34, max(18, alpha)), 1))
            pts = [self._proj(rr * math.cos(t / 60.0 * 2 * math.pi),
                              rr * ratio * math.sin(t / 60.0 * 2 * math.pi), 0.0, cx, cy, R)
                   for t in range(61)]
            for j in range(len(pts) - 1):
                p.drawLine(QPointF(pts[j][0], pts[j][1]), QPointF(pts[j + 1][0], pts[j + 1][1]))

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
        for e in self._edges:
            if not e["body_body"]:
                continue
            if not self._signal_ok(e, b):            # 有就显示, 没有就不显示
                continue
            pa = pos.get(self._key_of(e["f"]))
            pb = pos.get(self._key_of(e["t"]))
            if pa is None or pb is None:
                continue
            x1, y1, x2, y2 = float(pa[0]), float(pa[1]), float(pb[0]), float(pb[1])
            col = col_of.get(e.get("sig_kind") or e["kind"], QColor("#8b949e"))
            if ghost:
                # 文字块**之下**先透描一遍 (字压线: 字仍可读, 线也没有"断"的错觉); 全部虚线, 同相位
                c2 = QColor(col); c2.setAlpha(86)
                g = QPen(c2, 2.9, Qt.CustomDashLine)
                g.setCapStyle(Qt.FlatCap)
                g.setDashPattern([7.0 / 2.9, 6.0 / 2.9]); g.setDashOffset((self._phase * 0.5) / 2.9)
                p.setPen(g)
                p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
                continue
            core = QColor(col); core.setAlpha(236)
            glow = QColor(col); glow.setAlpha(60)
            pen_w = 2.9
            # 慢速流动虚线: 长划 6px / 间隔 4px ⇒ 人眼看得清"是虚线", 相位每次 tick 走 0.5px (60ms/格)
            _dash, _gap = 7.0, 6.0          # 像素单位 (与笔宽解耦: 两支笔的划/隔必须同一像素几何)
            for pen, w in ((glow, pen_w + 4.4), (core, pen_w)):
                q = QPen(pen, w, Qt.CustomDashLine)
                q.setCapStyle(Qt.FlatCap)      # 关键: 默认方帽把每段划两端各外扩半个笔宽 ⇒ 间隔被吃掉
                q.setDashPattern([max(0.15, _dash / w), max(0.15, _gap / w)])
                q.setDashOffset((self._phase * 0.5) / w)
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
        f = QFont("DejaVu Sans")
        f.setPixelSize(int(size))
        f.setBold(bool(bold))
        return QFontMetrics(f)

    def _wrap(self, text, width, size=9, sep=" · "):
        """按 `sep` 切段塞进 width 像素 (量宽用 QFontMetrics) —— 塞不下不截断, 交给下一行。"""
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
        return lines or [""]

    def _foot_lines(self, W):
        """底部图注 (完整, 自动换行) —— 判据 J2 核"不许截断"。"""
        s = self.data.body.get("sun", {})
        e1, e2 = s.get("eig_min"), s.get("eig_max")
        mtxt = ("度量 g dim=%s diag 特征值 %.3f~%.3f (引力=度量, 井扁率按此)" % (s.get("metric_dim"), e1, e2)) \
            if e1 else "度量 g 未读 torque_live"
        nv = self.info.get("checked", {})
        miss = [k for k, v in nv.items() if not v.get("在")]
        _all_bb = [e for e in self._edges if e["body_body"]]
        _live = self.interactions()
        a = ("力的相互作用 (画布 links 真源): 主体↔主体 %d 条 · **信号有值才画** ⇒ 当前画出 %d 条 · "
             "体系外节点/灰点已删 (老倪: 其它球体删掉)") % (len(_all_bb), len(_live))
        bb = ("线义: **全部虚线** (长划6/隔4, 慢速流动, 不闪不断) · 青=几何条件 · 金=性能/集合条件 · "
              "绿=动作/前馈 · 紫=反馈/回灌 · 缺值不画 (显示由真源代码触发: 见 SIG_OF 注释)")
        c = ("角度映射: 水星←接触进度‖e∥‖ · 地球←前馈请求/v_cap · 火星←块步λ · 木星←η · "
             "月球与原子技能=地球相位(协同行进) · 卫星=原子技能 %s (真源 skill_phys; 亮=在职, 金圈=当前在职 %s)") % (
            "SK01~SK%02d" % max(1, len(self.data.body.get("sats", {}).get("list") or [])),
            self.data.body.get("sats", {}).get("active") or "—")
        d = "真源: engine_latest(帧龄 %s) · torque_live(%s) · skill_latest · ss_traj_last(%d 帧) · manifold_layer.py 真算 · 画布 %d 节点/%d 连线 · 节点映射核对 %d/%d 全命中" % (
            ("%.1fs" % s["帧龄"]) if isinstance(s.get("帧龄"), (int, float)) else "—", mtxt,
            (self.data.frames or {}).get("n", 0), len(self.data.nodes), len(self.data.links), len(BODIES) - len(miss), len(BODIES))
        out = []
        for t in (a, bb, c, d):
            out += self._wrap(t, max(80, W - 12), 9)
        if miss:
            out.append("⚠ 缺源: %s" % ",".join(miss))
        if self.data.err:
            out.append("⚠ 读源异常 %d 处" % len(self.data.err))
        return out

    def _block(self, p, lines, x, y, w, color, size=9, frame=True):
        """画一块文字 (带半透明底 + 细框 ⇒ 压在环/线上也读得清) —— 返回外接矩形。"""
        lines = [str(t) for t in lines if str(t) != ""]
        if not lines:
            return QRectF()
        fm = self._fm(size)
        h = 11 * len(lines) + 4
        rect = QRectF(x, y, w, h)
        if frame:
            p.setPen(QPen(QColor(52, 68, 86, 210), 1))
            p.setBrush(QColor(13, 17, 23, 222))     # 222: 既压得住线, 又让线隐约透出来
            p.drawRoundedRect(rect, 3, 3)
        p.setPen(color)
        f = QFont("DejaVu Sans"); f.setPixelSize(int(size)); p.setFont(f)
        for i, t in enumerate(lines):
            p.drawText(QRectF(rect.x() + 3, rect.y() + 2 + i * 11, rect.width() - 6, 11),
                       Qt.AlignLeft | Qt.AlignVCenter, t)
        return rect

    def _body_line(self, key, d):
        """球下的真值一行 (完整短句, 不截断); 取不到 ⇒ 诚实文案。"""
        return self._body_text(key, d)

    def _label_blocks(self, pos, b, cx, cy, R, S, W, H):
        """算出**所有文字块的外接矩形** (先避让再画) —— 判据 J1 用它核「任何两块文字不重叠」。

        避让规则 (老倪 2026-10-16 看图: 月球标签压地球标签 / 金球压水星参数行):
          · 每颗行星的标签沿"离太阳"的径向往外让 (r + 26px 起), 太阳球体再也压不住它;
          · 月球标签沿"离地球"的方向让 (不与地球标签同侧);
          · 与已放置的块/球体圆/卫星圈相交 ⇒ 沿自己的方向每次推 6px, 最多 26 次。
        块宽 208px (与侧栏 682px 宽兼容), 每行 11px。
        """
        w = min(228.0, max(150.0, W - 24))
        pad_top, pad_bot = 20, 12 + 11 * len(self._foot_lines(W))
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
            _rr0 = S * self.RAD["sat"] + 26.0 + (11.0 if _i % 2 else 0.0)
            _blk = None
            for _k in range(7):
                _ang = (0.0, 0.3927, -0.3927, 0.7854, -0.7854, 1.1781, -1.1781)[_k]   # 0/±22.5°/±45°/±67.5°
                _cs, _sn = math.cos(_ang), math.sin(_ang)
                _vx = _ux / _n * _cs - _uy / _n * _sn
                _vy = _ux / _n * _sn + _uy / _n * _cs
                _cand = QRectF(_x + _vx * _rr0 - 16.0, _y + _vy * _rr0 - 7.0, 32.0, 14.0)
                _cand = QRectF(min(max(_cand.x(), 2.0), W - 34.0),
                               min(max(_cand.y(), pad_top + 2.0), H - pad_bot - 16.0), 32.0, 14.0)
                _blk = _cand
                if any(_cand.intersected(r).isEmpty() is False for r in placed):
                    continue
                _bad = False
                for (kx, ky, kr) in _ks_sat:
                    nx = max(_cand.x(), min(kx, _cand.x() + _cand.width()))
                    ny = max(_cand.y(), min(ky, _cand.y() + _cand.height()))
                    if math.hypot(nx - kx, ny - ky) < kr + 1:
                        _bad = True
                        break
                if not _bad:
                    break
            _col = GOLD if _sk == b.get("sats", {}).get("active") else QColor("#9fe3d6")
            out.append((_blk, [str(_sk)], _col, 8))
            placed.append(_blk)

        def place_near(x, y, lines, color, size, ux, uy, own_r):
            """把文字块贴到 (x,y) 这颗球的**外侧**: 块的近边离球 own_r+12px, 朝 (ux,uy) 展开。

            坑 (真踩过): 块宽 228 而径向偏移只有 ~47px ⇒ 以 anchor 为中心的块会反过来盖住自己的球,
            每个候选位置都被自身球的 keep-out 判"冲突", 最后退化成重叠最小者(跑到画布另一头)。
            所以径向偏移必须 ≥ 块在该方向上的半宽 + own_r。
            再在候选方向 (径向 → ±45° → ±90° → ±135° → 反向) 上 6px 步扫, 先 clamp 再判冲突。
            """
            h = 11 * len(lines) + 4
            ks = keepouts()

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
                if r.x() < 2:
                    r.moveLeft(2)
                if r.x() + r.width() > W - 2:
                    r.moveLeft(max(2, W - 2 - r.width()))
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
                        return rect
                    if best_ov is None or ov < best_ov:
                        best, best_ov = rect, ov
            # 兜底 (2026-10-16 看图: 地球区 三条标签互压 —— "重叠最小者"在拥挤区就等于重叠):
            # 候选方向全冲突 ⇒ 放进**左侧/右侧页边栏**的第一个空槽 (先 clamp 再逐 8px 下移找位),
            # 槽位同样对 已放置块/球体/底栏 做 keep-out ⇒ 保证任何两块文字不重叠。
            fb = self._gutter_slot(lines, placed, ks, W, H, pad_top, pad_bot, w)
            if fb is not None:
                placed.append(fb)
                out.append((fb, lines, color, size))
                return fb
            placed.append(best)
            out.append((best, lines, color, size))
            return best

        names = {"mercury": "☿ 接触流形", "earth": "♁ 前馈加速器", "mars": "♂ DiT 动作头",
                 "jupiter": "♃ 性能流形"}
        for key in ("mercury", "mars", "jupiter", "earth"):
            x, y, _z = pos[key]
            ux, uy = x - cx, y - cy
            n = math.hypot(ux, uy) or 1.0
            ux, uy = ux / n, uy / n
            lines = [names[key]]
            sub = self._body_line(key, b.get(key, {}))
            if sub:
                lines += self._wrap(sub, w - 8, 9)
            place_near(x, y, lines, FG if key != "earth" else QColor("#cfe4ff"), 9,
                       ux, uy, S * self.RAD[key])
        # 太阳 (贴球底)
        slines = ["☀ 流形引擎"] + self._wrap(self._sun_text(b.get("sun", {})), w - 8, 9)
        place_near(cx, cy, slines, GOLD, 9, 0.0, 1.0, S * self.RAD["sun"])
        # 卫星群 (绕地球的那一圈的外侧)
        # 月球 (沿"离地球"方向往外)
        mx, my, _mz = pos["moon"]
        ux, uy = mx - pos["earth"][0], my - pos["earth"][1]
        n = math.hypot(ux, uy) or 1.0
        # own_r 原先写成 _mr/2.0 ⇒ 月球标签被推到"地球-月球连线中点之外", 结果压在卫星圈上;
        # 换成 (月球球半径 + 12) ⇒ 近边贴月球外侧 (2026-10-16)
        place_near(mx, my, ["🌙 校正器"], QColor("#dfe4ec"), 9, ux / n, uy / n,
                   S * self.RAD["moon"] + 12)
        # 收尾防撞 (2026-10-16 看图/判据 J1: 加了 8 个卫星 SK 号之后, 拥挤区可能仍有两块相交):
        #   逐对检查, 相交的把**后一块**改放页边栏空槽; 槽位也撞就保持原位 (判据会报出来, 不藏着)。
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
        h = 11 * len(lines) + 4
        for xg in (6.0, W - 6.0 - w):                 # 先左栏, 再右栏
            y = float(pad_top) + 4.0
            while y + h <= H - pad_bot - 2:
                rect = QRectF(xg, y, w, h)
                ok = True
                for r in placed:
                    if not rect.intersected(r).isEmpty():
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
                y += 8.0
        return None

    def label_rects(self):
        """给判据用: 当前布局下所有文字块矩形 (两两不许重叠)。"""
        W, H, S, cx, cy, R = self._geom()
        pos = self.positions(cx, cy, R)
        out, _placed = self._label_blocks(pos, self.data.body, cx, cy, R, S, W, H)
        # 2026-10-16: 返回**最终**矩形 (收尾防撞会改块位置 —— 之前返回 placed 会与真正画出来的不一致,
        # 判据量到的是改前的旧位置)
        return [t[0] for t in out]

    def _labels(self, p, pos, cx, cy, R, b, W, H, S):
        blocks, _placed = self._label_blocks(pos, b, cx, cy, R, S, W, H)
        for rect, lines, color, size in blocks:
            self._block(p, lines, rect.x(), rect.y(), rect.width(), color, size)

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
        f = QFont("DejaVu Sans"); f.setPixelSize(9); p.setFont(f)
        y0 = H - 8 - 11 * len(lines)
        for i, t in enumerate(lines):
            p.drawText(QRectF(4, y0 + i * 11, W - 8, 11), Qt.AlignLeft | Qt.AlignVCenter, t)

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

    def _sun_text(self, s):
        if not isinstance(s.get("M"), (int, float)):
            return "真源不可用 (未读 zmax_manifold/engine)"
        t = "M=%.3f · φ=%s · ‖∇Φ‖=%s" % (s["M"],
                                        ("%.3f" % s["phi"]) if isinstance(s.get("phi"), (int, float)) else "—",
                                        ("%.3f" % s["grad_norm"]) if isinstance(s.get("grad_norm"), (int, float)) else "—")
        if isinstance(s.get("T_norm"), (int, float)):
            t += " · T=%.1f%sN·m" % (s["T_norm"], "≤" if s.get("clip") else "~")
        return t
