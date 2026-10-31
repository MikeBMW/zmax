#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""physics_constraints.py — ⚖ 原子技能的**物理惯性 / 质量变化率**约束 (老倪 2026-10-15)

老倪: 「每个 L2 层的原子技能, 都有肌肉记忆, 其中是否能够执行前馈加速器发出的 action, 主要取决于真实的物理定律,
即有质量的惯性; 每个技能, 都清楚的知道自己动作的惯性, 例如 接近动作的速度与加速度的关系, 位置与速度的导数关系等;
所有 L2 层的原子动作, 都要有物理质量变化率的约束 … 确保进入原子技能的 action 能够符合物理定律, 确保最终发出的动作
都是物理上可以平顺执行的。如果不能执行, 可以发出偏差 error … 反馈给状态校正节点 … 如果误差太大, 则可以通过
融合定位节点, 将大偏差先直接反馈给流形引擎节点, 从而改变顶层结构, 修复补偿偏差。」

本模块 = 每个原子技能进入执行前的**物理闸**。物理量全部来自真源 (不是编的):
  m     运动质量   真源 execution.py::ARM_SEGMENTS / HARDWARE_SPEC (末端夹爪 1.2 kg · 光模块 0.15 kg ⇒ 1.35 kg)
  F_max 力上限     真源 safety.py::FORCE_LIMIT=5N · 夹爪最大夹持力 12 N · 金手指保护 ≤2 N (过盈/插入段)
  v_cap 速度上限   真源 atomic_skills.SK0x.ctrl.v_cap (= cognition.ActionModulator.STAGE_V_CAP)
  a_max 加速度上限 = F_max / m        (牛顿第二定律; 也 = 速度对时间的导数上限)
  jerk_max 加加速度上限 = 15 m/s³ × (v_cap/0.35)   ← 15 m/s³ = **真机轨迹实测 P99** (357 帧 u_exec_vec 二阶差分)
  dmdt_max 质量变化率上限 = 0.5 kg/s (抓取建立/释放期 0.15 kg / 0.30 s) · 其它段 0.1 kg/s

四条约束 (全部向量化, 逐条可追溯; 削幅只削"超出物理可行"的那部分, 改动方向不翻转):
  ① 速度:      ‖v‖ ≤ v_cap
  ② 加速度:    ‖Δv‖ ≤ a_max·dt                     (位置←速度←加速度 的导数关系)
  ③ 加加速度:  ‖Δa‖ ≤ jerk_max·dt                  (平顺性: 不许阶跃, 真机伺服带宽有限)
  ④ 动量/质量率: ‖m·Δv + v·Δm‖ ≤ F_max·dt          (物理质量变化率约束: 夹起来/放下的瞬间动量变化要付得起)
  ⑤ 位移:      ‖v‖·dt ≤ s_step 且 段累计行程 ≤ s_max  (位置是速度的积分: 单拍位移与整段行程都封顶)
被约束削掉的部分 = **偏差 error**; ‖error‖ 大过阈值 ⇒ big=1 (该走融合定位 → 流形引擎的顶层补偿, 而不是就地校正)。

🧮 参数可标定 + 物理上下限 (老倪 2026-10-15):
  所有物理量 (v/v_min/a/s/s_step/jerk/m/F/dmdt) 的**标定真源** =
  config/calib/zmax_skill_physics.json (每项写成 {value,min,max,unit,src});
  写 = tools/skill_physics_calib.py --set (越界直接拒绝) · 读 = 本模块 limits_for()。
  本模块加载真源后把运行期取值**夹**在 [min,max] 内, 越界记进 p["clamps"] (取证)。
  真源缺失/损坏 ⇒ 回退下面的内置 PHYS 表 (行为与旧版逐位相同, 不因缺文件而崩)。

用法:
    lim = InertiaLimiter(dt=0.1)
    r = lim.limit("接近", u_req, v_prev=v_prev, a_prev=a_prev)
    r["u"]     # 物理可行动作 (真正下发给技能的)
    r["err"]   # 偏差 (u_req − u), 给状态校正器
    r["big"]   # 1 = 大偏差 ⇒ 走融合定位 → 流形引擎
    r["why"]   # 被哪几条约束削了 (速度/加速度/加加速度/动量质量率/位移)
"""
from __future__ import annotations

import json
import os

import numpy as np

# ── 物理参数表 (每技能一行; 数值真源见文件头) ─────────────────────────────────
#   m: 运动质量 kg · F: 力上限 N · v: 速度上限 m/s (技能自带) · dmdt: 质量变化率 kg/s
PHYS = {
    # 技能           m      F     v      dmdt   来源说明
    "接近":   dict(m=1.20, F=5.0,  v=0.35, dmdt=0.10, src="未夹持(只剩夹爪 1.2kg) · F=FORCE_LIMIT 5N"),
    "对位":   dict(m=1.20, F=5.0,  v=0.12, dmdt=0.10, src="未夹持 · F=FORCE_LIMIT 5N"),
    "下降":   dict(m=1.20, F=5.0,  v=0.09, dmdt=0.10, src="未夹持 · F=FORCE_LIMIT 5N (触到即停)"),
    "抓取":   dict(m=1.28, F=12.0, v=0.04, dmdt=0.50, src="夹持建立 m 1.20→1.35 · F=夹爪最大夹持力 12N"),
    "抬起":   dict(m=1.35, F=5.0,  v=0.30, dmdt=0.10, src="已夹持 1.35kg · F=FORCE_LIMIT 5N"),
    "转移":   dict(m=1.35, F=5.0,  v=0.35, dmdt=0.10, src="已夹持 · 平移 · F=FORCE_LIMIT 5N"),
    "插入":   dict(m=1.35, F=2.0,  v=0.085, dmdt=0.10, src="已夹持 · **金手指保护 ≤2N** (过盈段力控)"),
    "完成":   dict(m=1.35, F=2.0,  v=0.02, dmdt=0.10, src="已夹持 · 保持 · ≤2N"),
    "放入":   dict(m=1.35, F=2.0,  v=0.06, dmdt=0.50, src="摆盘链第7段 · 触底开爪释放 · ≤2N 不压伤"),
}
JERK_REF = 15.0          # m/s³ — 真机轨迹实测 P99 (357 帧 u22 阶差分 14.84)
JERK_V_REF = 0.35        # 参考速度 (接近/转移 的 v_cap)
BIG_ERR = float(os.environ.get("ZMAX_SKILL_BIG_ERR", "0.05"))   # 大偏差阈值 m/s (50 mm/s)


# ── 🧮 物理参数**标定真源** 加载器 (老倪 2026-10-15: v/a/s 要可标定, 带物理上下限) ──────
#   真源 = config/calib/zmax_skill_physics.json (写: tools/skill_physics_calib.py --set/--check)
#   每项 {value,min,max,unit,src}; 本模块读它并把运行期取值夹在 [min,max] 内 (越界→clamps 取证)。
#   缺文件/坏 JSON ⇒ 返回 None, 调用方回退内置 PHYS 表 (不因缺文件而崩, 也不静默改数)。
def _find_root(start):
    p = os.path.abspath(start)
    for _ in range(8):
        p = os.path.dirname(p)
        if os.path.isdir(os.path.join(p, "config", "calib")) and os.path.isdir(os.path.join(p, "tools")):
            return p
    return None


_SKILL_PHYS_JSON = os.environ.get("ZMAX_SKILL_PHYS_JSON") or os.path.join(
    _find_root(__file__) or "", "config", "calib", "zmax_skill_physics.json")
_CALIB_CACHE = {"key": None, "data": None}


def load_skill_physics(path=None):
    """读标定真源 (带 (路径, mtime) 缓存); 缺文件/坏 JSON ⇒ None (调用方回退内置表)。"""
    p = path or _SKILL_PHYS_JSON
    if not p or not os.path.isfile(p):
        return None
    try:
        key = (p, os.path.getmtime(p))
    except OSError:
        return None
    c = _CALIB_CACHE
    if c["key"] == key and c["data"] is not None:
        return c["data"]
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d.get("stages"), dict):
            return None
    except Exception:                                                       # noqa: BLE001
        return None
    c["key"], c["data"] = key, d
    return d


def calib_values(stage, path=None):
    """某技能的标定项 {param: {value,min,max,unit,src}}; 无真源/无此段 ⇒ {}。"""
    d = load_skill_physics(path)
    if not d:
        return {}
    st = d["stages"].get(str(stage))
    return st if isinstance(st, dict) else {}


def _clamp(name, val, spec, clamps):
    """把运行期取值夹进物理上下限 [min,max]; 越界记 clamps (老倪: 上下限要真的拦得住)。"""
    if not isinstance(spec, dict):
        return val
    lo, hi = spec.get("min"), spec.get("max")
    if lo is None or hi is None:
        return val
    if float(val) < float(lo) - 1e-12 or float(val) > float(hi) + 1e-12:
        v2 = float(min(max(float(val), float(lo)), float(hi)))
        clamps.append("%s %.6g→%.6g ∉ [%s, %s]" % (name, float(val), v2, lo, hi))
        return v2
    return val


def bounds_for(stage):
    """给界面/审计用: 该技能每个物理量的 [下限, 上限] + 单位。"""
    cal = calib_values(stage)
    return {k: {"min": v.get("min"), "max": v.get("max"), "unit": v.get("unit")}
            for k, v in cal.items() if isinstance(v, dict)}


def limits_for(stage, dt=0.1, override=None):
    """取某技能的物理上限 (含由 F/m 推出的 a_max 与按速度缩放的 jerk_max)。

    真源 config/calib/zmax_skill_physics.json 优先 —— v/v_min/a/s/s_step/jerk/m/F/dmdt 全带
    物理上下限, 运行期取值一律夹在 [min,max] 内 (越界 → p["clamps"])。
    """
    st = str(stage)
    p = dict(PHYS.get(st, PHYS["接近"]))
    cal = calib_values(st)
    clamps = []
    # ⚠️ 未知段名: 原来静默套用「接近」的物理量 (段名一改就悄悄换了一套惯性/力, 看不出来)。
    #    现在标成 unknown_stage 并计数, 由调用方/判据/审计看得见 —— 静默降级是老倪零容忍项。
    unknown = 0 if (st in PHYS or cal) else 1
    p["unknown_stage"] = unknown
    if unknown:
        p["unknown_stage_fallback"] = "接近"
    if cal:
        for k in ("v", "m", "F", "dmdt", "jerk", "s", "s_step", "v_min"):
            spec = cal.get(k)
            if isinstance(spec, dict) and spec.get("value") is not None:
                p[k] = _clamp(k, float(spec["value"]), spec, clamps)
        if isinstance(cal.get("a"), dict) and cal["a"].get("value") is not None:
            p["a_cal"] = _clamp("a", float(cal["a"]["value"]), cal["a"], clamps)
        p["bounds"] = {k: [v.get("min"), v.get("max")] for k, v in cal.items() if isinstance(v, dict)}
        p["calib_src"] = _SKILL_PHYS_JSON
        p["calib_src_kind"] = "真源(config/calib/zmax_skill_physics.json)"
    else:
        p["calib_src"] = "内置 PHYS 表"
        p["calib_src_kind"] = "内置 PHYS 表 (真源文件缺失, 已回退)"
        p["bounds"] = {}
    if override:
        p.update(override)
    m = max(1e-6, float(p["m"]))
    # a_max 两种口径都在真源留痕: 有标定 a 用标定 a, 否则牛顿二定律 F/m
    p["a_max"] = float(p.get("a_cal") or (float(p["F"]) / m))
    p["jerk_max"] = float(p.get("jerk") or (JERK_REF * max(0.15, min(1.0, float(p["v"]) / JERK_V_REF))))
    p["s_step"] = float(p.get("s_step") or (float(p["v"]) * float(dt)))     # 单拍位移上限
    p["s_max"] = float(p.get("s") or 0.0)                                   # 本段行程上限
    p["clamps"] = clamps
    p["dt"] = float(dt)
    return p


# ── 🧭 运动学约束 / ⚖ 动力学约束 分工 (2026-10-31 老倪: 「接近、对位这些技能要符合运动学约束;
#    物理约束这个要改成动力学约束; 都要真正调用」) ─────────────────────────────────────────
#   🧭 运动学 = 只与几何/时间有关, 与质量力无关: ①速度 ②加速度 ③加加速度 ⑤位移(速度的积分)
#   ⚖ 动力学 = 与质量/力/动量有关: ④动量/质量变化率 |m·Δv + v·Δm| ≤ F_max·dt (F_max 按段取, 金手指 ≤2N)
#   两条闸**每拍各调一次**(各自计数 n / n_cut, dispatch 逐拍对账), 由 InertiaLimiter 按 ①②③④⑤
#   原序编排 ⇒ 输出与拆分前**逐位相同**(回归判据 tools/verify_kin_dyn_split.py)。
KIN_CUTS = ("速度", "加速度", "加加速度", "位移")
DYN_CUTS = ("动量/质量率",)


def _skip_env():
    """消融开关 (默认空集 = 全开, 行为逐位不变): ZMAX_GATE_SKIP="加加速度,位移"。"""
    return {s.strip() for s in os.environ.get("ZMAX_GATE_SKIP", "").split(",") if s.strip()}


class KinematicLimiter:
    """🧭 运动学约束闸: ①速度 ②加速度 ③加加速度 ⑤单拍位移/段累计行程 (不看 m / F)。"""

    def __init__(self, dt=0.1):
        self.dt = float(dt)
        self.n = 0                                   # 本闸被调用拍数
        self.n_cut = {k: 0 for k in KIN_CUTS}
        self.travel = {}                             # 各段累计行程 m (换段清零)
        self._travel_stage = None
        self.n_over = 0                              # 行程超上限拍数 (只报不杀)
        self.last = None
        self.skip = _skip_env()

    def reset_stage(self, stage=None):
        if stage is None:
            self.travel = {}
            self._travel_stage = None
        else:
            self.travel.pop(str(stage), None)

    def limit(self, stage, v_req, v_prev=None, a_prev=None, p=None, dt=None):
        """①②③ 速度/加速度/加加速度。返回 (v, why, p, v0); p 由调用方给则与动力学共用同一份上限。"""
        p = p if p is not None else limits_for(stage, dt=dt or self.dt)
        v = np.asarray(v_req, dtype=float).ravel().copy()
        v0 = (np.zeros(3) if v_prev is None else np.asarray(v_prev, dtype=float).ravel()[:3].copy())
        a0 = (np.zeros(3) if a_prev is None else np.asarray(a_prev, dtype=float).ravel()[:3].copy())
        why = []
        # ① 速度上限
        n = float(np.linalg.norm(v))
        if "速度" not in self.skip and n > p["v"] > 0:
            v = v * (p["v"] / n)
            why.append("速度")
        # ② 加速度上限 (a_max = F/m 或标定 a)
        dv = v - v0
        a_lim = p["a_max"] * p["dt"]
        n_dv = float(np.linalg.norm(dv))
        if "加速度" not in self.skip and n_dv > a_lim > 0:
            v = v0 + dv * (a_lim / n_dv)
            why.append("加速度")
        # ③ 加加速度上限 (平顺性: 本拍不能把加速度整个翻过来)
        a_new = (v - v0) / p["dt"]
        da = a_new - a0
        j_lim = p["jerk_max"] * p["dt"] * float(os.environ.get("ZMAX_GATE_JERK_X") or 1.0)
        n_da = float(np.linalg.norm(da))
        if "加加速度" not in self.skip and n_da > j_lim > 0:
            a_new = a0 + da * (j_lim / n_da)
            v = v0 + a_new * p["dt"]
            why.append("加加速度")
        self.n += 1
        for w in why:
            self.n_cut[w] = self.n_cut.get(w, 0) + 1
        self.last = {"v": [float(x) for x in v], "why": "+".join(why) or "可行"}
        return v, why, p, v0

    def displace(self, stage, v, p):
        """⑤ 位移: ‖v‖·dt ≤ s_step (单拍封顶) + 段累计行程 ≤ s_max (只报不杀)。返回 (v, why, over, s)。"""
        why = []
        s_step = float(p.get("s_step") or 0.0)
        if s_step > 0:
            d_now = float(np.linalg.norm(v)) * p["dt"]
            if "位移" not in self.skip and d_now > s_step * (1.0 + 1e-12):
                v = v * (s_step / max(d_now, 1e-12))
                why.append("位移")
        _key = str(stage)
        if _key != self._travel_stage:
            self._travel_stage = _key
            self.travel[_key] = 0.0
        self.travel[_key] = self.travel.get(_key, 0.0) + float(np.linalg.norm(v)) * p["dt"]
        s_max = float(p.get("s_max") or 0.0)
        over = int(s_max > 0 and self.travel[_key] > s_max * (1.0 + 1e-9))
        if over:
            self.n_over += 1
        for w in why:
            self.n_cut[w] = self.n_cut.get(w, 0) + 1
        return v, why, over, float(self.travel[_key])

    def stats(self):
        return {"n": self.n, "n_cut": dict(self.n_cut), "dt": self.dt,
                "travel_m": {k: round(v, 6) for k, v in self.travel.items()},
                "n_over_travel": self.n_over}


class DynamicLimiter:
    """⚖ 动力学约束闸: ④ |m·Δv + v·Δm| ≤ F_max·dt (抓取/释放时质量在变; F_max 按段取)。"""

    def __init__(self, dt=0.1):
        self.dt = float(dt)
        self.n = 0
        self.n_cut = {k: 0 for k in DYN_CUTS}
        self.n_force = 0          # 力需求峰值超 F_max 的拍数 (诊断, 与削拍同源)
        self.last = None
        self.skip = _skip_env()

    def reset_stage(self, stage=None):
        return None

    def limit(self, stage, v, v0, p, dmdt=None, dt=None):
        """返回 (v, why, f_need_norm)。只动前 3 维 (平移), 第 4 维夹爪不是动力学量。"""
        _dt = float(p.get("dt") or dt or self.dt)
        _dmdt = float(p.get("dmdt") if dmdt is None else dmdt)
        v = np.asarray(v, dtype=float).ravel().copy()
        v0 = np.asarray(v0, dtype=float).ravel()[:3].copy()
        f_lim = p["F"] * _dt
        f_need = p["m"] * (v - v0) + v * (_dmdt * _dt)
        n_f = float(np.linalg.norm(f_need))
        why = []
        if "动量/质量率" not in self.skip and n_f > f_lim > 0:
            v = v0 + (v - v0) * (f_lim / max(n_f, 1e-9))
            why.append("动量/质量率")
            self.n_cut["动量/质量率"] += 1
        if n_f > f_lim > 0:
            self.n_force += 1
        self.n += 1
        self.last = {"f_need_N": round(n_f, 6), "F_max_N": float(p["F"]), "why": "+".join(why) or "可行"}
        return v, why, n_f

    def stats(self):
        return {"n": self.n, "n_cut": dict(self.n_cut), "n_force_over": self.n_force, "dt": self.dt}


class InertiaLimiter:
    """⚖ 技能动作总闸: 🧭 运动学(①②③⑤) + ⚖ 动力学(④) 按 ①②③④⑤ 原序编排, 每拍两条闸都真调。"""

    def __init__(self, dt=0.1, big_err=None):
        self.dt = float(dt)
        self.big_err = float(big_err if big_err is not None else BIG_ERR)
        self.kin = KinematicLimiter(dt=self.dt)       # 🧭 运动学约束 (v/a/jerk/位移)
        self.dyn = DynamicLimiter(dt=self.dt)         # ⚖ 动力学约束 (动量/质量率/力)
        self.n = 0
        self.n_cut = {k: 0 for k in ("速度", "加速度", "加加速度", "动量/质量率", "位移")}
        self.last = None
        self.travel = self.kin.travel                 # 与运动学闸共用同一份段行程 (单点记账)
        self._travel_stage = None
        self.n_over = 0
        self.n_clamp = 0
        self.n_unknown = 0
        self.n_kin = 0                                # 🧭 运动学闸实际调用次数
        self.n_dyn = 0                                # ⚖ 动力学闸实际调用次数
        self.skip = self.kin.skip

    def reset_stage(self, stage=None):
        """手动清某段 (或全部) 累计行程。"""
        self.kin.reset_stage(stage)
        self.dyn.reset_stage(stage)
        self._travel_stage = self.kin._travel_stage

    def limit(self, stage, u_req, v_prev=None, a_prev=None, m=None, dmdt=None, dt=None):
        """把请求动作裁成**物理可行**的动作, 并给出被裁掉的偏差。

        🧭 运动学闸先削 ①②③, ⚖ 动力学闸再削 ④, 🧭 运动学闸收尾 ⑤ —— 与拆分前同一顺序、同一算式。
        只动前 3 维 (x,y,z 平移速度); 第 4 维 (夹爪 0/1) 原样透传 (它不是运动学量)。
        """
        p = limits_for(stage, dt=dt or self.dt)
        if m is not None:
            p["m"] = float(m)
            p["a_max"] = float(p["F"]) / max(1e-6, float(p["m"]))
        _dmdt = float(p["dmdt"] if dmdt is None else dmdt)
        u = np.asarray(u_req, dtype=float).ravel().copy()
        # ① ② ③ —— 🧭 运动学约束
        v, why, p, v0 = self.kin.limit(stage, u[:3], v_prev=v_prev, a_prev=a_prev, p=p)
        self.n_kin += 1
        # ④ —— ⚖ 动力学约束
        v, why_f, _n_f = self.dyn.limit(stage, v, v0, p, dmdt=_dmdt)
        self.n_dyn += 1
        why = why + why_f
        # ⑤ —— 🧭 运动学约束 (位移是速度的积分)
        v, why_s, over, s_travel = self.kin.displace(stage, v, p)
        why = why + why_s
        self.n_over = self.kin.n_over
        self._travel_stage = self.kin._travel_stage
        u[:3] = v
        err = np.asarray(u_req, dtype=float).ravel()[:3] - v
        e_norm = float(np.linalg.norm(err))
        self.n += 1
        if p.get("clamps"):
            self.n_clamp += 1
        if p.get("unknown_stage"):
            self.n_unknown += 1
        for w in why:
            self.n_cut[w] = self.n_cut.get(w, 0) + 1
        out = {"u": [float(x) for x in u],
               "v_req": [float(x) for x in np.asarray(u_req, dtype=float).ravel()[:3]],
               "err": [float(x) for x in err], "err_norm": round(e_norm, 8),
               "big": int(e_norm > self.big_err), "why": "+".join(why) or "可行",
               "kin_why": "+".join(why[:len(why) - len(why_s)]) or "可行",
               "dyn_why": "+".join(why_f) or "可行",
               "phys": {"m": round(float(p["m"]), 4), "F_max": float(p["F"]), "v_cap": float(p["v"]),
                        "v_min": float(p.get("v_min") or 0.0),
                        "a_max": round(float(p["a_max"]), 4), "jerk_max": round(float(p["jerk_max"]), 3),
                        "dmdt_max": _dmdt, "s_step": float(p.get("s_step") or 0.0),
                        "s_max": float(p.get("s_max") or 0.0),
                        "dt": float(p["dt"]), "src": p["src"],
                        "calib": p.get("calib_src_kind"), "bounds": p.get("bounds") or {},
                        "clamps": p.get("clamps") or [],
                        "unknown_stage": int(p.get("unknown_stage") or 0)},
               "s_travel": round(float(s_travel), 6), "over_travel": over,
               "unknown_stage": int(p.get("unknown_stage") or 0)}
        self.last = out
        return out

    def audit(self):
        """盘查表: 每个技能是否带惯性约束 + 具体物理上限 + 标定上下限 (给审计/报告用)。"""
        rows = []
        for st, p in PHYS.items():
            q = limits_for(st)
            rows.append({"技能": st, "m_kg": p["m"], "F_max_N": p["F"], "v_cap_mps": p["v"],
                         "v_min_mps": q.get("v_min", 0.0),
                         "a_max_mps2": round(q["a_max"], 4), "jerk_max_mps3": round(q["jerk_max"], 3),
                         "dmdt_max_kg_s": p["dmdt"],
                         "s_step_m": q.get("s_step"), "s_max_m": q.get("s_max"),
                         "标定真源": q.get("calib_src_kind", ""), "上下限": q.get("bounds") or {},
                         "运行期夹回": q.get("clamps") or [],
                         "段名登记": ("已登记" if not q.get("unknown_stage") else "❌ 未登记(静默降级)"),
                         "运动学约束": "①速度 ②加速度 ③加加速度 ⑤位移",
                         "动力学约束": "④动量/质量率 (F_max 按段)",
                         # 兼容既有判据/报告 (它们按这一条字符串查 ①②③④)
                         "约束": "①速度 ②加速度 ③加加速度 ④动量/质量率 ⑤位移",
                         "真源": p["src"]})
        return rows

    def bounds(self, stage):
        """某技能每个物理量的 [下限, 上限] (给标定界面/接口用)。"""
        return bounds_for(stage)

    def stats(self):
        return {"n": self.n, "n_cut": dict(self.n_cut), "big_err": self.big_err, "dt": self.dt,
                "travel_m": {k: round(v, 6) for k, v in self.travel.items()},
                "n_over_travel": self.n_over, "n_clamp": self.n_clamp,
                "n_unknown_stage": self.n_unknown,
                "运动学闸": self.kin.stats(), "动力学闸": self.dyn.stats(),
                "n_gate_kin": self.n_kin, "n_gate_dyn": self.n_dyn,
                "calib_src": limits_for("接近").get("calib_src_kind")}


if __name__ == "__main__":
    lim = InertiaLimiter()
    rows = lim.audit()
    print("=== ⚖ 原子技能物理惯性/质量变化率盘查 (%d 个技能) ===" % len(rows))
    print("    标定真源: %s" % rows[0].get("标定真源", "?"))
    for r in rows:
        print("  %-3s m=%.2fkg F≤%.1fN v≤%.3fm/s ⇒ a≤%.2fm/s² jerk≤%.1fm/s³ dm/dt≤%.2fkg/s · "
              "单拍位移≤%.4fm 段行程≤%.3fm"
              % (r["技能"], r["m_kg"], r["F_max_N"], r["v_cap_mps"], r["a_max_mps2"],
                 r["jerk_max_mps3"], r["dmdt_max_kg_s"], r["s_step_m"], r["s_max_m"]))
        print("      约束: %s\n      真源: %s" % (r["约束"], r["真源"]))
    print("\n=== 闸门自检 1: 请求一个物理上跟不上的动作 ===")
    r = lim.limit("接近", [1.2, 0.0, 0.0, 0.0], v_prev=[0.0, 0.0, 0.0])
    print("  请求 1.2 m/s → 可行 %.4f m/s · 削因 %s · 偏差 %.4f m/s · big=%d"
          % (r["u"][0], r["why"], r["err_norm"], r["big"]))
    r2 = lim.limit("插入", [0.5, 0.0, 0.0, 1.0], v_prev=[0.05, 0.0, 0.0], dmdt=0.5)
    print("  插入请求 0.5 m/s ⇒ 可行 %.4f m/s · 削因 %s · 偏差 %.4f m/s · big=%d (金手指 ≤2N 兜住)"
          % (r2["u"][0], r2["why"], r2["err_norm"], r2["big"]))
    print("\n=== 闸门自检 2: ⑤ 位移约束 (段累计行程) ===")
    lim2 = InertiaLimiter()
    q = limits_for("接近")
    v_fast = [float(q["v"]), 0.0, 0.0, 0.0]              # 顶在速度上限上跑
    n_step, rr = 0, {"over_travel": 0}
    while n_step < 500:
        rr = lim2.limit("接近", v_fast)                  # v_prev=None ⇒ 每拍都给满速 (只测位移闸)
        n_step += 1
        if rr["over_travel"]:
            break
    print("  接近段: 段行程上限 %.3f m · 单拍位移 %.4f m → 第 %d 拍累计 %.4f m 触上限 (over_travel=%d)"
          % (q["s_max"], q["s_step"], n_step, lim2.travel["接近"], rr["over_travel"]))
    lim3 = InertiaLimiter()
    r3 = lim3.limit("抓取", [0.9, 0.0, 0.0, 0.0])
    print("  抓取段: 请求 0.9 m/s → 可行 %.4f m/s · 削因 %s (s_step=%.4f m 由 ①速度 兜住, ⑤ 只在标定收紧时才咬)"
          % (r3["u"][0], r3["why"], limits_for("抓取")["s_step"]))
    print("\n  闸门统计: %s" % lim3.stats())
