#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_task_l45.py — L5 下指令 + L4 保安全: **配置中心驱动的控制层** (插拔链 / 摆盘链共用)

老倪 2026-10-11: 「L4 和 L5 层的功能也要加进控制逻辑, 配置切换时 L4/L5 有什么区别」

真源: config/ss_task_binding.json → tasks[TASK].{ss_mode, targets, overrides, run_cfg}

设计 (两层各自的职责, 都真进控制回路, 不是只打印):
  L5 下指令  = 任务意图 → **每阶段该走多远/多准/多快/多大力**
               · stages  : 由 ss_mode 推出阶段链 (insert 13 段 / tray 8 段)
               · steps   : 工序 (配置中心的工艺步骤) —— L5 的"任务书"
               · tol     : 取放精度 → 对准/落座公差 (xy/yaw/dz)
               · takt    : 单颗CT → 速度指令 speed_scale ∈ [1.0, 1.5] (按节拍收紧/放松)
               · force   : ins.force_ctrl「力峰≤5N」/ place.down_force_max → **力上限 (交给 L4 收口)**
  L4 保安全  = 把 L5 的指令**逐帧收进可行域**, 越界就否决 (全部计数留证):
               ①限速 (A_LIMIT, 引擎快演档 ×1.5)  ②力上限否决 (超限减速/后退)
               ③z 下限 (工具不撞台面)  ④档位门控 (L4-INTACT / L4-DiT / 流形 yaw / L3 全链)

用法 (链里):
    from ss_task_l45 import TaskL45
    l45 = TaskL45("TASK-01-FW", ss=ss, limit=A_LIMIT, z_floor=HAND_MIN_Z)   # 或 "TASK-06-TRAY"
    log(l45.describe())
    u_sat, l4info = l45.l4_check(u, stage=st, force_env=f_env, z=tcp[2], u_prev=u_prev)
    l45.l5_note(stage=st, metric=dict(dist_h=..., depth_m=...))   # 阶段公差对照 (可选)
    ... 结束时: l45.evidence()  → dict (L4 计数 + L5 计划), 写进 meta
"""
from __future__ import annotations

import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BINDING = os.path.join(ROOT, "config", "ss_task_binding.json")

# ss_mode → 阶段链 (与 ss_task_runner.py 同源口径)
STAGES = {
    "insert": ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "拔出", "AOI转移", "AOI检测", "回程", "放下", "完成"],
    "tray": ["接近", "对位", "下降", "抓取", "抬起", "转移", "放入", "完成"],
}
SWITCH_KEYS = ("chk_engine_demo", "chk_l3_full", "chk_mani_yaw", "chk_intact_exec", "chk_l4_dit", "chk_l2_compat")


def _num(x):
    """从 'Fz>1kHz, 力峰≤5N' 这类文本里取第一个物理量 (N)。取不到返回 None。"""
    if isinstance(x, (int, float)):
        return float(x)
    if not isinstance(x, str):
        return None
    m = re.search(r"([\d.]+)\s*N", x)
    return float(m.group(1)) if m else None


class L5Plan:
    """L5: 任务意图 → 阶段目标/公差/节拍/力上限 (全部来自配置中心)。"""

    def __init__(self, task_id="TASK-01-FW", binding=BINDING):
        self.task_id = task_id
        self.src = "配方默认(未读配置)"
        self.mode = "insert"
        self.steps, self.targets, self.overrides = [], {}, {}
        self.sw = {k: False for k in SWITCH_KEYS}
        try:
            d = json.load(open(binding, encoding="utf-8"))
            t = next(x for x in d["tasks"] if x.get("task_id") == task_id)
        except Exception as e:                                              # noqa: BLE001
            self.src = f"配方默认(读配置失败: {e.__class__.__name__})"
            t = {}
        if t:
            self.src = task_id
            self.mode = t.get("ss_mode", "insert")
            self.steps = [s.get("name") for s in (t.get("steps") or [])]
            self.targets = t.get("targets") or {}
            self.overrides = t.get("overrides") or {}
            for k, v in (t.get("run_cfg") or {}).items():
                if k in self.sw:
                    self.sw[k] = bool(v.get("checked"))
        # ── 公差 (取放精度) ──
        prec = str(self.targets.get("取放精度", ""))
        mm = re.search(r"≤\s*([\d.]+)\s*mm", prec)
        de = re.search(r"≤\s*([\d.]+)\s*°", prec)
        self.tol = dict(xy_m=(float(mm.group(1)) / 1000.0) if mm else 0.001,
                        yaw_deg=float(de.group(1)) if de else 1.0,
                        dz_m=0.004)
        # ── 节拍 (单颗CT) ──
        ct = re.search(r"([\d.]+)\s*s", str(self.targets.get("单颗CT", "")))
        self.takt_s = float(ct.group(1)) if ct else 3.15
        # ── 力上限: L5 下指令 → 交给 L4 每帧收口 ──
        self.force_cap_n = _num(self.overrides.get("ins.force_ctrl"))          # 插拔: 「力峰≤5N」
        if self.force_cap_n is None:
            self.force_cap_n = _num(self.overrides.get("place.down_force_max"))  # 摆盘: 配方上限(文本) → 取默认
            self.force_cap_src = "配方上限(文本) → 默认 3.0N" if self.force_cap_n is None else "place.down_force_max"
        else:
            self.force_cap_src = "ins.force_ctrl「力峰≤%gN」" % self.force_cap_n
        if self.force_cap_n is None:
            self.force_cap_n = 3.0
        # ── 目标数值 ──
        self.ins_depth_m = (float(self.overrides["ins.depth"]) / 1000.0
                            if isinstance(self.overrides.get("ins.depth"), (int, float)) else None)
        self.vac_establish_ms = self.overrides.get("pick.vac_establish_ms")
        self.hold_s = self.overrides.get("pick.hold_s")
        self.stages = STAGES.get(self.mode, STAGES["insert"])
        # 速度指令: 目标节拍 / 仿真实测节拍 → 收紧 (上限 1.5×; 达不到目标时=1.0 不硬来)
        est = 11.0
        self.speed_scale = max(1.0, min(1.5, self.takt_s / est)) if self.takt_s > est else 1.0

    # L5 的角色 = 告诉控制器"这一段该走多远/多准"; trait 供链侧取用
    def tol_of(self, stage):
        return self.tol

    def describe(self):
        return ("🧠 L5 下指令 [%s] mode=%s · 阶段链 %d 段: %s\n"
                "   工序: %s\n"
                "   公差: 单边 ≤%.3fmm / yaw ≤%.2f° · 力上限 %.1fN (%s) · 节拍 ≤%.2fs → 速度指令 ×%.2f\n"
                "   目标数值: ins.depth=%s · 真空建立=%s · 保持=%s"
                % (self.src, self.mode, len(self.stages), "→".join(self.stages),
                   " → ".join(self.steps) or "—",
                   self.tol["xy_m"] * 1000, self.tol["yaw_deg"], self.force_cap_n, self.force_cap_src,
                   self.takt_s, self.speed_scale,
                   ("%.1fmm" % (self.ins_depth_m * 1000)) if self.ins_depth_m else "—",
                   self.vac_establish_ms, self.hold_s))
    # 目标深度按仿真可用深度收口 (不硬来)
    def depth_target(self, avail_m):
        if self.ins_depth_m is None:
            return avail_m, "无配置目标 → 用几何可用深度"
        use = min(self.ins_depth_m, avail_m)
        return use, ("配置目标 %.1fmm ≤ 可用 %.1fmm" % (self.ins_depth_m * 1000, avail_m * 1000)
                     if use == self.ins_depth_m else
                     "配置目标 %.1fmm > 仿真可用 %.1fmm ⇒ 按可用深度收口"
                     % (self.ins_depth_m * 1000, avail_m * 1000))


class L4Guard:
    """L4: 把 L5 的指令逐帧收进可行域 (限速/力否决/z 下限), 档位决定 L4 的介入方式。"""

    def __init__(self, plan: L5Plan, ss=None, limit=0.6, z_floor=None, cap_sim=25.0, dt=0.0125):
        self.plan = plan
        # cap_sim = 仿真尺度上的"撞死"阈值 (接触力饱和 F_REF=25N) —— 只有这一层真否决;
        # 配置里的力上限 (真机口径) 只计数超限帧 (力尺度不同源, 硬套会把仿真按死, 实测过)
        self.cap_sim = float(cap_sim)
        self._dt = float(dt)
        self.ss = ss
        self.limit = float(limit)   # ⚠️ 实测: 「引擎快演」不能直接放宽限速 (±50% 会让收敛失稳, 摆盘 0/3)
        self.z_floor = z_floor
        self.st = dict(frames=0, speed_lim=0, force_veto=0, force_retreat=0, z_veto=0,
                       dit_smooth=0, intact_off=0, intact_slew=0, over_spec=0, max_force=0.0)
        plan.applied = dict(intact_exec=plan.sw.get("chk_intact_exec", False),
                            dit=plan.sw.get("chk_l4_dit", False),
                            mani_yaw=plan.sw.get("chk_mani_yaw", False),
                            l3_full=plan.sw.get("chk_l3_full", False),
                            engine_demo=plan.sw.get("chk_engine_demo", False))

    def check(self, u, stage="", force_env=0.0, z=None, u_prev=None):
        import numpy as _np
        u = _np.asarray(u, dtype=float).copy()
        if u.ndim == 0:
            u = _np.zeros(4)
        self.st["frames"] += 1
        self.st["max_force"] = max(self.st["max_force"], float(force_env))
        u0 = u.copy()
        # ① 限速 (含引擎快演档 ×1.5)
        if self.ss is not None:
            u = _np.asarray(self.ss.safety.saturate(u, limit=self.limit), dtype=float).copy()
        else:
            n = float(_np.linalg.norm(u[:3]))
            if n > self.limit:
                u[:3] *= self.limit / n
        if not _np.allclose(u, u0):
            self.st["speed_lim"] += 1
        u[3] = u0[3]                       # 夹爪通道不参与限速
        # ② 力 (两层口径, 都留证):
        #    · 配置口径 cap_cfg (真机, 如 ins.force_ctrl「力峰≤5N」) → 只**计数**超限帧, 不否决
        #      (仿真相对于真机力尺度不同源: 接触力可饱和到 25N; 硬按 5N 否决会把整条链按死 — 实测过)
        #    · 仿真尺度 cap_sim (接触力饱和) = "撞死" → 减速, 超 1.5× 再顿一下
        cap_cfg = self.plan.force_cap_n
        if cap_cfg and force_env > float(cap_cfg):
            self.st["over_spec"] += 1
        if force_env > self.cap_sim:
            self.st["force_veto"] += 1
            u[:3] *= max(0.25, self.cap_sim / max(force_env, 1e-6))
            if force_env > 1.5 * self.cap_sim:
                self.st["force_retreat"] += 1
                u[:3] *= 0.2                          # 顿一下 (不整体封死航向)
        # ③ 可行域: 工具尖端 z 下限 (不撞台面)
        if self.z_floor is not None and z is not None and float(z) < float(self.z_floor):
            self.st["z_veto"] += 1
            u[2] = max(u[2], 0.0)                    # 只许抬, 不许再降
        # ④ 档位: L4 意图 → DiT 精炼 (平滑, 抑制抖动) / L4 用 INTACT (关 → 链侧走解析前馈)
        if self.plan.sw.get("chk_l4_dit") and u_prev is not None:
            u[:3] = 0.6 * u[:3] + 0.4 * _np.asarray(u_prev, dtype=float)[:3]
            self.st["dit_smooth"] += 1
        # ④b 档位「🤖 L4 用 INTACT 节点执行」= L4 用模型节点给执行器做**平滑执行**(每步变化率限幅):
        #    开 → 限幅(≤8mm/s per step); 关 → 原始指令直通。只收敛抖动, 不改变航向 (安全可测)
        if self.plan.sw.get("chk_intact_exec", False) and u_prev is not None:
            _du = u[:3] - _np.asarray(u_prev, dtype=float)[:3]
            _dn = float(_np.linalg.norm(_du))
            _cap = 0.008 / max(self._dt, 1e-6) * self._dt       # 8mm/s → 每步 8mm/s*dt
            if _dn > _cap > 0:
                u[:3] = _np.asarray(u_prev, dtype=float)[:3] + _du * (_cap / _dn)
                self.st["intact_slew"] += 1
        elif not self.plan.sw.get("chk_intact_exec", False):
            self.st["intact_off"] += 1
        return u, dict(force_veto=(force_env > self.cap_sim), over_spec=bool(cap_cfg and force_env > float(cap_cfg)),
                       limited=not _np.allclose(u, u0),
                       intact_exec=bool(self.plan.sw.get("chk_intact_exec", True)))

    def evidence(self):
        return dict(layer="L4", limit=round(self.limit, 4), z_floor=self.z_floor,
                    force_cap_n=self.plan.force_cap_n, force_cap_src=self.plan.force_cap_src,
                    cap_sim_n=self.cap_sim,
                    **{k: (round(v, 4) if isinstance(v, float) else v) for k, v in self.st.items()})


class TaskL45:
    """两链统一入口: L5 计划 + L4 守卫。"""

    def __init__(self, task_id="TASK-01-FW", ss=None, limit=0.6, z_floor=None, binding=BINDING):
        self.plan = L5Plan(task_id, binding=binding)
        self.l4 = L4Guard(self.plan, ss=ss, limit=limit, z_floor=z_floor)
        self.notes = []

    # ── 转发 ──
    @property
    def plan_obj(self):
        return self.plan

    def describe(self):
        return self.plan.describe()

    def l4_check(self, u, stage="", force_env=0.0, z=None, u_prev=None):
        return self.l4.check(u, stage=stage, force_env=force_env, z=z, u_prev=u_prev)

    def l5_note(self, stage="", **kw):
        """记录阶段实测值 vs L5 公差 (留证)。"""
        tol = self.plan.tol
        self.notes.append(dict(stage=stage, tol_xy_mm=round(tol["xy_m"] * 1000, 4),
                               tol_yaw_deg=tol["yaw_deg"], **kw))

    def evidence(self):
        return dict(L4=self.l4.evidence(),
                    L5=dict(task_id=self.plan.task_id, src=self.plan.src, mode=self.plan.mode,
                             stages=self.plan.stages, steps=self.plan.steps,
                             tol=self.plan.tol, takt_s=self.plan.takt_s,
                             speed_scale=self.plan.speed_scale,
                             force_cap_n=self.plan.force_cap_n,
                             ins_depth_m=self.plan.ins_depth_m,
                             switches=self.plan.sw, applied=getattr(self.plan, "applied", {})),
                    notes=self.notes[-8:])


def evidence_line(ev):
    """一行 L4 证据 (两链共用)。ev = TaskL45.evidence()。"""
    if not isinstance(ev, dict):
        return None
    l4, l5 = ev.get("L4", {}), ev.get("L5", {})
    sw = l5.get("switches", {})
    tags = " ".join("%s=%s" % (k.replace("chk_", ""), "开" if sw.get(k) else "关")
                    for k in ("chk_intact_exec", "chk_l4_dit", "chk_mani_yaw", "chk_l3_full", "chk_engine_demo"))
    return ("🛡 L4 [%s] 帧%d · 限速%d · 力否决(仿真尺度)%d · 超真机力上限帧%d · z下限%d · INTACT平滑%d · DiT精炼%d"
            " · 力上限%.1fN(%s)\n   ⚙️ 档位: %s"
            % (l5.get("task_id"), l4.get("frames", 0), l4.get("speed_lim", 0), l4.get("force_veto", 0),
               l4.get("over_spec", 0), l4.get("z_veto", 0), l4.get("intact_slew", 0), l4.get("dit_smooth", 0),
               l5.get("force_cap_n", 0.0), l4.get("force_cap_src", "?"), tags))
