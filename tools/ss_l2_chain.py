# -*- coding: utf-8 -*-
"""🔗 L2 全链节点运行器 (2026-10-29 老倪: "先把所有 L2 的节点都接上, 保证所有节点都运行,
   可以每个节点按顺序打开或关闭, 对比回放 UPH 的平顺")

背景 (实测, 不是猜):
  · 画布上 L2 有 15 个节点, 但 8805 站原来只在跑 感知→obs→技能→前馈→调制→安全→执行;
    估计器/预测器/校正器/肌肉记忆/触觉/AOI 六类节点**代码里零引用** ⇒ 画布亮着但没跑。
  · 平滑度实测: 指令流单次关节变化 ≤0.7° (1464 次下发 >1.2° 的 0 次), 但真值只 16~21Hz 刷新,
    末端 350mm/s 在 62ms 一帧里就是 22mm 台阶 ⇒ 看起来一顿一顿。
    估计器(滤波)+预测器(常速度外推)在这里正好能补上"帧间连续": 指令按预测位姿走, 不再等真值。

设计:
  ① 顺序固定 = L2_ORDER, 一路 ctx 往下传 (后面节点吃前面的输出, 同一条链)
  ② 每个节点可单独开关, 开关落盘 config/platform/l2_chain_switches.json (运行时可热改)
  ③ 每个节点都记账 (calls / ms / ok / note), 供 /api/live 查"到底跑没跑"
  ④ 没有数据源的节点**不造假**: 直接 ok=False + why (例如触觉没有传感器)
  ⑤ run() 返回 {cmd_xyz, vel, stats, trace}, 执行端拿 cmd_xyz 下发
"""
from __future__ import annotations

import json
import os
import time

ROOT = os.path.expanduser("~/zmax")
SWITCH_FILE = os.path.join(ROOT, "config", "platform", "l2_chain_switches.json")

# 顺序即链路顺序 (与画布 System 0 · L2 带一致: 感知 → 融合 → 估计/预测/校正 → 前馈/规划
#   → 调制 → 安全 → 物理闸 → 技能 → 执行; 触觉/AOI/肌肉记忆是旁挂, 放在各自归属处)
L2_ORDER = [
    "ssyolo",       # 目标检测 (站外每轮跑, 这里只读结果)
    "ss2d3d",       # 2D→3D (台面单应反解结果)
    "sssensor",     # 融合定位 → 43D obs
    "ssobs",        # 统一状态空间 (43D→16D 潜空间)
    "ssest",        # 自适应状态估计器 (alpha-beta 滤波: 位置平滑 + 速度估计)
    "sspred",       # 先验动力学预测器 (常速度外推 → 帧间连续)
    "ssinnov",      # 状态校正器 (innov = 测量 − 预测)
    "sstactile",    # 触觉感知 (无数据源 ⇒ ok=False, 不造假)
    "ssaoi",        # 光学质量检测 (帧级指标, 非 AOI 检测服务)
    "ssff",         # 前馈加速器 (MLP; 无 39D 观测时用解析律 k·e)
    "n_geoplan",    # 测地线规划引导 (S 曲线轨迹 + 3D 引导位姿)
    "sssched",      # 动作调制器 (阶段限速 + 否决权)
    "sslimit",      # 安全执行边界 (saturate)
    "ssphys",       # 动力学约束闸 (前置运动学: 速度/加速度/加加速度/位移)
    "sssk",         # 原子技能 (当前段 v_cap / 目标规则)
    "ss_mem_l2",    # 肌肉记忆 (与本段模板比对)
    "ssact",        # 机器人执行器 (本拍增量)
]

_DEFAULT = {k: True for k in L2_ORDER}
# 没有数据源的先默认关, 但仍然会"跑"一次并如实报 why (打开也不造假)
_DEFAULT.update({"sstactile": False})        # 触觉无数据源; ssaoi 有帧统计 ⇒ 默认开


def load_switches():
    try:
        with open(SWITCH_FILE, encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict):
            return dict(_DEFAULT)
        out = dict(_DEFAULT)
        out.update({k: bool(v) for k, v in d.items() if k in L2_ORDER})
        return out
    except Exception:                                                           # noqa: BLE001
        return dict(_DEFAULT)


def save_switches(d):
    os.makedirs(os.path.dirname(SWITCH_FILE), exist_ok=True)
    tmp = SWITCH_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, SWITCH_FILE)
    return d


class L2Chain:
    """按 L2_ORDER 跑节点。ctx 是这一拍的数据袋; 节点写 ctx 也读 ctx。"""

    def __init__(self, chain):
        self.chain = chain                    # StationChain (拿 mod/safety/lim/skills/eng/ff)
        self.sw = load_switches()
        self.stats = {k: {"calls": 0, "ms": 0.0, "ok": None, "note": "未跑"} for k in L2_ORDER}
        self.hist = []                        # [(t, pos)]
        self.est = None
        self.vel = None
        self.last = {}

    # ── 开关 ──────────────────────────────────────────────────────────────
    def set_switch(self, name, on):
        if name not in L2_ORDER:
            return {"ok": False, "err": "未知节点 %s" % name}
        self.sw[name] = bool(on)
        save_switches(self.sw)
        return {"ok": True, "node": name, "on": bool(on)}

    def switches(self):
        return dict(self.sw)

    # ── 单个节点 ──────────────────────────────────────────────────────────
    def _node(self, name, ctx):
        """返回 (ok, note)。所有节点都在这里实现, 没有数据源的如实报 why。"""
        c = self.chain
        now = ctx.get("t") or time.time()

        if name == "ssyolo":
            l2 = ctx.get("l2") or {}
            if not l2:
                return False, "本轮无检测结果"
            ctx["det"] = l2.get("best")
            return bool(l2.get("ok")), "conf=%.2f n=%s (站内每轮真检测)" % (l2.get("conf") or 0, l2.get("n"))

        if name == "ss2d3d":
            p = ctx.get("perc") or {}
            if not p.get("ok"):
                return False, "反解失败: %s" % (p.get("err") or "无 perc")
            ctx["tgt3d"] = list(p.get("xyz") or [])
            return True, "台面单应反解 xyz=%s (对真值 %.1fmm)" % (
                [round(v, 3) for v in (p.get("xyz") or [])], float(p.get("truth_err_mm") or -1))

        if name == "sssensor":
            obs = ctx.get("obs43")
            if obs is None:
                return False, "obs43 构造失败"
            ctx["pos"] = [float(v) for v in obs[0:3]]
            return True, "融合 43D: pos=%s" % [round(float(v), 3) for v in obs[0:3]]

        if name == "ssobs":
            if c.eng is None:
                try:
                    c._engine()                       # 站内懒建 (ManifoldEngine, 同一 ckpt)
                except Exception:                                             # noqa: BLE001
                    pass
            obs = ctx.get("obs43")
            if c.eng is None or obs is None:
                return False, "引擎不可用: %s" % (c.eng_note or "无 obs")
            import numpy as np
            pr = c.eng.project(np.asarray(obs, float))
            ctx["p16"] = [round(float(v), 5) for v in (pr or {}).get("p", [])]
            return bool(ctx["p16"]), "43D→16D p[0:3]=%s" % ctx["p16"][:3]

        if name == "ssest":
            pos = ctx.get("pos")
            if not pos:
                return False, "无位置"
            import numpy as np
            pos = np.asarray(pos, float)[:3]
            if self.est is None:
                self.est = pos.copy()
                self.vel = np.zeros(3)
                ctx["est_pos"] = [float(v) for v in pos]
                ctx["est_vel"] = [0.0, 0.0, 0.0]
                return True, "初始化 est=%s" % [round(float(v), 3) for v in pos]
            dt = max(1e-3, float(ctx.get("dt") or 0.02))
            prev = self.est.copy()
            alpha, beta = 0.55, 0.18                      # alpha-beta 滤波 (位置平滑 + 速度估计)
            self.est = self.est + self.vel * dt
            r = pos - self.est
            self.est = self.est + alpha * r
            self.vel = self.vel + (beta / dt) * r
            ctx["est_pos"] = [float(v) for v in self.est]
            ctx["est_vel"] = [float(v) for v in self.vel]
            return True, "est=%s |v|=%.0fmm/s 残差 %.1fmm" % (
                [round(v, 3) for v in self.est], float(np.linalg.norm(self.vel)) * 1000,
                float(np.linalg.norm(pos - prev)) * 1000)

        if name == "sspred":
            if self.est is None or self.vel is None:
                return False, "估计器未初始化 (先开 ssest)"
            dt = float(ctx.get("dt") or 0.02)
            pred = self.est + self.vel * dt
            ctx["pred_pos"] = [float(v) for v in pred]
            return True, "预测 t+%dms → %s" % (int(dt * 1000), [round(float(v), 3) for v in pred])

        if name == "ssinnov":
            pos, pred = ctx.get("pos"), ctx.get("pred_pos")
            if not pos or not pred:
                return False, "缺 测量/预测"
            import numpy as np
            inn = (np.asarray(pos, float) - np.asarray(pred, float)) * 1000.0
            ctx["innov_mm"] = [round(float(v), 2) for v in inn]
            return True, "innov=%s mm |%.1f|" % (ctx["innov_mm"], float(np.linalg.norm(inn)))

        if name == "sstactile":
            return False, "AR 场景无触觉/力传感器数据源 (不造假)"

        if name == "ssaoi":
            img = ctx.get("frame_stat") or {}
            if not img:
                return False, "本拍没有帧统计 (取不到图 ⇒ 不编指标)"
            return True, "帧级指标 mean=%s gold_px=%s (非 AOI 检测服务)" % (img.get("mean"), img.get("gold_px"))

        if name == "ssff":
            tgt, pos = ctx.get("tgt"), ctx.get("pos")
            if not tgt or not pos:
                return False, "缺 目标/位置"
            import numpy as np
            u = np.asarray(tgt, float)[:3] - np.asarray(pos, float)[:3]
            n = float(np.linalg.norm(u))
            sk = c.skill_info(c.stage_for(ctx.get("action")))
            cap = float(sk.get("v_cap_m_s") or 0.35)
            if n > cap:
                u = u * (cap / n)
            ctx["u_ff"] = u.tolist()
            return True, "k·e → |u|=%.0fmm/s (v_cap %.2f)" % (min(n, cap) * 1000, cap)

        if name == "n_geoplan":
            from lerobot.engineering.nodes import geo_plan_impl
            tgt, pos = ctx.get("tgt"), ctx.get("pred_pos") or ctx.get("pos")
            if not tgt or not pos:
                return False, "缺 目标/起点"
            sk = c.skill_info(c.stage_for(ctx.get("action")))
            tr = geo_plan_impl.smooth_traj(pos, tgt, v_cap=float(sk.get("v_cap_m_s") or 0.35),
                                          a_max=2.0, dt=float(ctx.get("dt") or 0.02))
            if not tr.get("ok"):
                return False, tr.get("err") or "轨迹失败"
            ctx["traj"] = tr
            return True, "S曲线 T=%.2fs n=%d 峰速%.0fmm/s" % (tr["T"], tr["n"], tr["v_peak_mm_s"])

        if name == "sssched":
            import numpy as np
            u_ff = np.asarray(ctx.get("u_ff") or [0, 0, 0, 0], float)
            if u_ff.size < 4:
                u_ff = np.pad(u_ff, (0, 4 - u_ff.size))
            u_fb = np.zeros(4)
            d = float(ctx.get("err_m") or 0.0)
            u, stage = c.mod.decide(u_ff, u_fb, float(ctx.get("contact_p") or 0.0), d)
            u = np.asarray(u, float).ravel()
            if u.size < 4:
                u = np.pad(u, (0, 4 - u.size))
            ctx["u_mod"] = u.tolist()
            ctx["stage"] = stage
            return True, "modulate → 阶段「%s」 |u|=%.0fmm/s" % (stage, float(np.linalg.norm(u[:3])) * 1000)

        if name == "sslimit":
            import numpy as np
            u = np.asarray(ctx.get("u_mod") or ctx.get("u_ff") or [0, 0, 0, 0], float)
            us = c.safety.saturate(u, limit=c.limit)
            ctx["u_sat"] = np.asarray(us, float).ravel().tolist()
            return True, "saturate(%.2f) → |u|=%.0fmm/s" % (c.limit, float(np.linalg.norm(np.asarray(us)[:3])) * 1000)

        if name == "ssphys":
            import numpy as np
            u = np.asarray(ctx.get("u_sat") or [0, 0, 0, 0], float)
            st = c.stage_for(ctx.get("action"))
            v0 = getattr(c.mod, "_g_v", None)
            a0 = getattr(c.mod, "_g_a", None)
            g = c.lim.limit(st, u, v_prev=(v0 if v0 is not None else np.zeros(3)),
                            a_prev=(a0 if a0 is not None else np.zeros(3)), dt=float(ctx.get("dt") or 0.02))
            ctx["u_phys"] = np.asarray(g["u"], float).ravel().tolist()
            return True, "物理闸 why=%s cut=%s" % (g.get("why"), (g.get("cut") or {}))

        if name == "sssk":
            st = c.stage_for(ctx.get("action"))
            sk = c.skill_info(st)
            ctx["skill"] = sk
            return True, "%s v_cap=%.2f cls=%s" % (st, float(sk.get("v_cap_m_s") or 0), sk.get("cls"))

        if name == "ss_mem_l2":
            import numpy as np
            pos = ctx.get("pos")
            tmpl = ctx.get("mem_tmpl")
            if not pos or not tmpl:
                return False, "无模板/无位置"
            def _norm(t):
                a = np.asarray(t, float)[:3]
                return a / 1000.0 if float(np.linalg.norm(a)) > 10.0 else a     # 段表是 mm
            d = min(float(np.linalg.norm(np.asarray(pos, float) - _norm(t))) for t in tmpl)
            ctx["mem_mm"] = round(d * 1000, 1)
            return True, "距最近模板 %.1fmm (肌肉记忆比对)" % ctx["mem_mm"]

        if name == "ssact":
            cmd = ctx.get("cmd_xyz")
            if not cmd:
                return False, "无指令点"
            ctx["act_xyz"] = list(cmd)
            return True, "下发点 %s" % [round(v, 3) for v in cmd]

        return False, "未实现"

    # ── 整链一拍 ──────────────────────────────────────────────────────────
    def run(self, ctx):
        """顺序跑 L2_ORDER, 返回 {cmd_xyz, vel, stats, trace}。开关关掉的节点跳过 (记账为 skipped)。"""
        trace = []
        for name in L2_ORDER:
            st = self.stats.setdefault(name, {"calls": 0, "ms": 0.0, "ok": None, "note": ""})
            if not self.sw.get(name, True):
                st["note"] = "开关关闭 (跳过)"
                trace.append({"node": name, "skipped": True})
                continue
            t0 = time.perf_counter()
            try:
                ok, note = self._node(name, ctx)
            except Exception as e:                                              # noqa: BLE001
                ok, note = False, "%s: %s" % (type(e).__name__, e)
            ms = (time.perf_counter() - t0) * 1000.0
            st.update({"calls": st["calls"] + 1, "ms": round(ms, 2), "ok": bool(ok), "note": str(note)[:160]})
            st["ms_avg"] = round((st.get("ms_avg") or ms) * 0.9 + ms * 0.1, 2)
            trace.append({"node": name, "ok": bool(ok), "note": str(note)[:80], "ms": round(ms, 2)})

        # 指令点取用顺序: 预测位姿 (帧间连续) > 估计 > 实测
        cmd = ctx.get("pred_pos") or ctx.get("est_pos") or ctx.get("pos")
        self.last = {"cmd_xyz": cmd and [round(float(v), 5) for v in cmd],
                     "est_vel": ctx.get("est_vel"), "innov_mm": ctx.get("innov_mm"),
                     "n_ok": sum(1 for x in trace if x.get("ok")),
                     "n_skip": sum(1 for x in trace if x.get("skipped")),
                     "n_fail": sum(1 for x in trace if x.get("ok") is False),
                     "t": round(time.time(), 3)}
        return {"cmd_xyz": cmd, "trace": trace, "last": self.last}

    def status(self):
        return {"order": L2_ORDER, "switches": dict(self.sw), "stats": dict(self.stats),
                "last": dict(self.last)}
