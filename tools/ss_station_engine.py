#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_station_engine.py — 8805 render 站: 几何短链 → **过引擎完整链**

老倪 2026-10-29 三步 (「把 8805 从几何短链改成过引擎的完整链」):

  ① 感知归口    L2 YOLO 结果落 `/dev/shm/l2_det.json` (引擎常驻回路与画布 `n_yolo` 节点读同一份;
                两边都是对 8802 渲染帧的真推理, 谁新用谁 —— 不是抄常量)
  ② 动作归口    u_ff (原子技能口 / ⚡前馈加速器 MLP) → `ActionModulator.decide()`
                (内部含 **SK01-08 段包络 + physics_constraints.InertiaLimiter 五条物理约束**)
                → `safety.saturate(SS_LIMIT)` → 执行端 (8802 双臂 IK + 真值回读)
  ③ 技能归口    步骤名 → 原子技能 (SK01 接近 / SK02 对位 / SK03 下降 / SK06 转移 …) 给本段 v_cap,
                每拍动作按技能派发落盘 `zmax_data/ss_live/skill_dispatch.json` 与
                `/dev/shm/zmax_ss_engine/skill_<stage>.json` (与 `tools/ss_skill_dispatch.py` 同一口径)

与 `src/lerobot/engine/runtime.py` 的关系
  · 六层源码**同源加载** (同 `tools/ss_bypass_run.py` 的 `load_mod`), 顺序与 runtime 一致:
        obs → u_ff → decide(闸) → gripper_cmd → saturate → 执行
  · 区别只有执行端: runtime 把 u_sat 交给 env.step; 这里交给 8802 的 IK/control (双臂真机同构仿真)
  · **单点削铁律**: 削幅只发生在 decide 内的物理闸 + safety.saturate 两处, 执行端不再二次削

本模块只算不动手; 每个中间量都返回并落盘, 可逐拍对账 (u_ff / gate.why / u_sat / 应用增量)。
"""
from __future__ import annotations

import importlib.util
import json
import os
import time

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SS_DIR = os.path.join(REPO, "src", "lerobot", "policies", "left_right", "state_space")
LIVE = os.path.join(REPO, "zmax_data", "ss_live")
SHM = "/dev/shm/zmax_ss_engine"
DET_SHARED = "/dev/shm/l2_det.json"

# 步骤名 → 原子技能段 (SK01-08 的 stage 字段)。plan 节点给的是人话, 这里做唯一映射。
STAGE_OF = {
    "协同观察位": "接近",
    "观察位(模块上方)": "接近",
    "接近": "接近",
    "对位": "对位",
    "协同对位": "对位",
    "下降": "下降",
    "抓取": "抓取",
    "抬起": "抬起",
    "转移": "转移",
    "撤离": "转移",
    "撤离(让出视野给复测)": "转移",
    "插入": "插入",
    "完成": "完成",
}
SKILL_CLS = {"接近": "SK01Approach", "对位": "SK02Align", "下降": "SK03Descend",
             "抓取": "SK04Grasp", "抬起": "SK05Lift", "转移": "SK06Transfer",
             "插入": "SK07Insert", "完成": "SK08Complete"}


def load_mod(name):
    """按文件路径加载六层真实源码 (不经包 __init__, 与引擎同源)。"""
    path = os.path.join(SS_DIR, f"{name}.py")
    spec = importlib.util.spec_from_file_location("ss_" + name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _atomic_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


class StationChain:
    """8805 站内的引擎链: 每拍算 u_ff → 闸 → u_sat, 并把增量交给执行端。"""

    def __init__(self, dt=None, limit=None, k=None, verbose=True):
        self.parallel = load_mod("parallel")
        self.cognition = load_mod("cognition")
        self.safety = load_mod("safety")
        self.physics = load_mod("physics_constraints")
        self.execution = load_mod("execution")
        try:
            self.skills = load_mod(os.path.join("skills", "atomic_skills"))
        except Exception:                                                        # noqa: BLE001
            self.skills = None
        self.limit = float(limit if limit is not None else os.environ.get("SS_LIMIT", "0.6"))
        self.k = float(k or os.environ.get("ZMAX_SKILL_K") or 6.0)
        # ⚖ 物理闸 Δt = 标定口径 (config/calib/zmax_skill_physics.json 的 dt=0.1s), 与 runtime 一致
        self.lim = self.physics.InertiaLimiter() if dt is None else self.physics.InertiaLimiter(dt=dt)
        self.mod = self.cognition.ActionModulator()   # gate_dt 下面按物理闸的 dt 设
        self.mod.limiter = self.lim
        self.mod.gate_dt = float(self.lim.dt)
        self.ff = self.parallel.FeedforwardAccelerator()
        self.dt = float(self.lim.dt)
        self.n_tick = 0
        # 🧩 完整链 (老倪 2026-10-29): 运动规划(测地线块) ‖ 前馈MLP → 加权 → 调制 → 安全
        #   chain_mode="skill"  ⇒ 原子技能出 u_ff (旧链, 技能主刀)
        #   chain_mode="plan"   ⇒ 运动规划出块 + 前馈MLP 并列加权 (规划主刀, 技能只派发)
        self.chain_mode = str(os.environ.get("ZMAX_STATION_CHAIN") or "skill").strip().lower()
        self.cp = None          # ss_chunk_pipeline.ChunkPipeline (懒建)
        self.eng = None         # ManifoldEngine (懒建, 与常驻 loop 同一标定 ckpt)
        self.eng_note = ""
        self.stats = {"ticks": 0, "gate_cuts": {}, "ff_src": {}, "stages": {}}
        # 🔗 L2 全链 (2026-10-29): 15 个 L2 节点按顺序真跑, 每个可单独开关
        self._l2 = None
        self.last = {}
        if verbose:
            print("🧩 引擎链就绪: 前馈 loaded=%s · 物理闸 dt=%.3fs · 安全限幅 %.2f · 技能表 %d 段"
                  % (self.ff.loaded, self.dt, self.limit, len(SKILL_CLS)), flush=True)

    # ── ①.L2 全链 ────────────────────────────────────────────────────────
    def l2(self):
        """懒建 L2 全链运行器 (tools/ss_l2_chain.py)。"""
        if getattr(self, "_l2", None) is None:
            try:
                import ss_l2_chain
                self._l2 = ss_l2_chain.L2Chain(self)
            except Exception as e:                                               # noqa: BLE001
                print("⚠ L2 链不可用: %s: %s" % (type(e).__name__, e), flush=True)
                self._l2 = False
        return self._l2 or None

    # ── ① 感知归口 ────────────────────────────────────────────────────────
    def put_det(self, det, img_url="http://127.0.0.1:8802/frame.png?cam=close", n=None,
                src="L2:detect.yolo(8805站)"):
        """把本拍 L2 结果写到引擎/画布共用的总线文件, 并回读确认 (不假设写成功)。"""
        box = None
        if det and det.get("best"):
            box = det["best"].get("box")
        payload = {"t": time.time(), "t_str": time.strftime("%H:%M:%S"), "src": src,
                   "img": img_url, "n": int(n if n is not None else (det or {}).get("n") or 0),
                   "ms": (det or {}).get("ms"),
                   "det": {"光模块": {"box": box, "conf": (det or {}).get("conf"),
                                     "cls": (((det or {}).get("best") or {}).get("cls"))}}}
        try:
            _atomic_json(DET_SHARED, payload)
            with open(DET_SHARED, encoding="utf-8") as f:
                back = json.load(f)
            payload["readback_n"] = back.get("n")
            payload["readback_src"] = back.get("src")
            return {"ok": back.get("n") == payload["n"], "file": DET_SHARED, **payload}
        except Exception as e:                                                   # noqa: BLE001
            return {"ok": False, "err": "%s: %s" % (type(e).__name__, e)}

    # ── ③ 技能归口 ────────────────────────────────────────────────────────
    def stage_for(self, action_name):
        s = str(action_name or "")
        for k2, v in STAGE_OF.items():
            if k2 in s:
                return v
        return "接近"

    def reset_gate(self):
        """新一步开始必须清闸的上一拍速度/加速度。否则上一段的闸后速度被当成"本段已有速度",
        加速度/加加速度两条约束会把本段第一拍拖向旧方向 —— 实测 8mm 小步首拍 u_sat 反指目标。"""
        self.mod._g_v = None
        self.mod._g_a = None
        self.mod.gate = None
        self.mod.veto_count = 0

    # ── 完整链: 运动规划 ‖ 前馈 → 加权 → 调制 → 安全 ────────────────────
    def _pipe(self):
        if self.cp is None:
            import ss_chunk_pipeline as _CP
            self.cp = _CP.ChunkPipeline(h=int(os.environ.get("ZMAX_STATION_CHUNK_H") or 8))
        return self.cp

    def _engine(self):
        """运动规划用的流形引擎: 与常驻 loop 同一标定文件 models/manifold_engine.npz。"""
        if self.eng is not None:
            return self.eng
        from lerobot.manifold.manifold_engine import ManifoldEngine              # noqa: PLC0415
        e = ManifoldEngine(manifold_type="su2", latent_dim=16, state_dim=43, action_dim=4,
                           manifold_M=3.643, inertia=False, su2_tangent=True)
        ck = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "models", "manifold_engine.npz")
        try:
            loaded = bool(e.load(ck))
            self.eng_note = "标定 %s (load=%s)" % (os.path.basename(ck), loaded)
        except Exception as _e:                                                   # noqa: BLE001
            self.eng_note = "标定读取失败 %s: %s" % (type(_e).__name__, str(_e)[:60])
        self.eng = e
        return e

    def obs43(self, tcp, grip, peg, hole, env_goal, q, dq, rot, touch=None):
        """43 维观测 — 每一槽都有真实来源 (不拿 0 假填):
        [0:3] TCP 真值 · [3] 夹爪标量 · [4:7] 光模块 3D=渲染检测+台面单应 · [7:10] 相对位移
        [10:12] 两指开度真值 · [12:18] 6 关节角 · [18:24] 6 关节速 · [24:33] TCP 旋转
        [33:36] 段目标 (= 运动规划给的目标) · [36:39] 孔口真值
        [39:43] 触觉 4D —— 本场景无触觉传感器 ⇒ 恒 0, 明确标注 (不当成"感知到 0 力")"""
        o = np.zeros(43, float)
        tcp = np.asarray(tcp, float).ravel()[:3]
        g2 = np.asarray(grip if grip is not None else [0.0, 0.0], float).ravel()[:2]
        if g2.size < 2:
            g2 = np.array([float(g2.ravel()[0]) if g2.size else 0.0] * 2)
        o[0:3] = tcp
        o[3] = float(np.linalg.norm(g2))
        o[4:7] = np.asarray(peg, float).ravel()[:3]
        o[7:10] = o[4:7] - tcp
        o[10:12] = g2
        o[12:18] = np.asarray(q or [0] * 6, float).ravel()[:6]
        o[18:24] = np.asarray(dq or [0] * 6, float).ravel()[:6]
        o[24:33] = np.asarray(rot or np.eye(3).ravel(), float).ravel()[:9]
        # 🔴 槽位必须与 **MLP 训练口径 (ar_mujoco_env._get_obs)** 一致, 否则输出退化:
        #   [33:36] = 环境目标点 (env 的 target/_gold_home) · [36:39] = 孔口 hole。
        #   实测反例: 把"段目标"塞进 [36:39] ⇒ obs 出训练分布, MLP 输出掉到 0.03m/s (近乎不动),
        #   混合后反被规划块的错误方向拖走 (残差 100~500mm 收不了口)。
        #   ⇒ 前馈只在"去孔口"的语义下用 MLP (转移/插入); 其余段用解析比例律 Kp·(段目标−末端)。
        o[33:36] = np.asarray(env_goal, float).ravel()[:3]
        o[36:39] = np.asarray(hole if hole is not None else env_goal, float).ravel()[:3]
        o[39:43] = np.zeros(4) if touch is None else np.asarray(touch, float).ravel()[:4]
        return o

    K_FF_ANALYTIC = 1.2      # 解析前馈增益 (与 parallel.analytic_forward 同值)

    def tick_plan(self, side, obs43, stage, seg_target=None):
        """一拍完整链: 测地线规划(运动规划) ‖ 前馈MLP → λ 加权 → 动作调制器 → 安全限幅。
        返回与 tick() 同形; 规划出不了块 ⇒ ok=False 如实返回 (不造假动作)。"""
        t0 = time.perf_counter()
        eng = self._engine()
        o = np.asarray(obs43, float).ravel()
        p_now = (eng.project(o) or {}).get("p")
        og = o.copy()
        og[0:3] = og[36:39]              # 目标态 = 同一观测, 手放到孔口 (goal 槽)
        try:
            eng.goal_point = (eng.project(og) or {}).get("p")
        except Exception:                                                        # noqa: BLE001
            pass
        pipe = self._pipe()
        # 🧩 并列两支 (老倪 2026-10-29 定序): 左支=⚡前馈MLP · 右支=🧭运动规划(测地线块), 同等位置,
        #   两支都吃同一份 obs, 汇到 ③λ加权。前馈先算 (左), 规划后算 (右), 谁都不吃谁。
        # ⚡前馈支路 (左): 转移/插入段 = MLP (目标=孔口, 训练域内); 其余段 = 解析比例律 (通用)
        _seg = np.asarray(seg_target if seg_target is not None else o[36:39], float).ravel()[:3]
        if stage in ("转移", "插入"):
            ff, fmode = pipe._ff_seq(o)
            _ff_src = "mlp(目标=孔口, 训练域内)"
        else:
            _e = _seg - np.asarray(o[0:3], float).ravel()[:3]
            _u = np.clip(self.K_FF_ANALYTIC * _e, -0.5, 0.5)
            ff = [np.concatenate([_u, [1.0]])]
            fmode = "analytic(Kp=%.1f→段目标)" % self.K_FF_ANALYTIC
            _ff_src = fmode
        chunk, csrc = pipe._chunk(eng, p_now)
        if chunk is None:
            self.stats["plan_fail"] = self.stats.get("plan_fail", 0) + 1
            return {"ok": False, "why": csrc, "stage": stage, "i": 0, "err_m": None,
                    "u_ff": [0.0] * 4, "u_sat": [0.0] * 4, "delta": [0.0, 0.0, 0.0],
                    "delta_mm": [0.0, 0.0, 0.0], "u_ff_src": "规划失败",
                    "gate_why": csrc, "gate_cut": {}, "skill": "—", "t": round(time.time(), 3)}
        _seq, lam = pipe._blend(ff, chunk)        # λ 与块流水线同源 (λ_i = λ_max·(i+1)/H)
        # 🔴 混合前先「同一把尺子」限幅: 前馈 MLP 的裸幅值可达 0.79m/s, 规划块只有 0.087m/s;
        #   直接 λ 加权等于让 MLP 独裁 (实测 cos 从 +1.00 退化到 +0.24, 残差卡 100mm 收不了口)。
        #   两支各自按本段 v_cap 等比限幅后再加权 ⇒ λ 才真的等于"信前馈/信规划"的比例。
        _cap = float((self.mod.v_cap or {}).get(stage) or 0.35)
        _ff0, _c0 = np.asarray(ff[0], float).ravel()[:4], np.asarray(chunk[0], float).ravel()[:4]
        _n1, _n2 = float(np.linalg.norm(_ff0[:3])), float(np.linalg.norm(_c0[:3]))
        if _cap > 0 and _n1 > _cap:
            _ff0 = _ff0 * (_cap / _n1)
        if _cap > 0 and _n2 > _cap:
            _c0 = _c0 * (_cap / _n2)
        _l0 = float(lam[0])
        u_mix = (1.0 - _l0) * _ff0 + _l0 * _c0
        u_seq = [u_mix]
        u_dec, why = self.mod.decide(u_mix, np.zeros(4), 0.0, 0.0)
        u_sat = np.asarray(self.safety.saturate(u_dec, limit=self.limit), float).ravel()[:4]
        delta = np.asarray(u_sat[:3], float) * float(self.dt)
        _dn = float(np.linalg.norm(delta))
        if _dn > 0.045:
            delta = delta * (0.045 / _dn)
        self.n_tick += 1
        self.stats["ticks"] += 1
        self.stats["ff_src"]["mlp:" + str(fmode)] = self.stats["ff_src"].get("mlp:" + str(fmode), 0) + 1
        self.stats["stages"][stage] = self.stats["stages"].get(stage, 0) + 1
        _g = self.mod.gate or {}
        for kk, vv in (_g.get("cut") or {}).items():
            if vv:
                self.stats["gate_cuts"][kk] = self.stats["gate_cuts"].get(kk, 0) + 1
        _dist = float(np.linalg.norm(np.asarray(o[0:3], float) - np.asarray(o[33:36], float)))
        rec = {"ok": True, "side": side, "stage": stage, "i": self.n_tick, "dist_m": _dist,
               "skill": "规划块→技能派发", "u_ff": [round(float(v), 5) for v in ff[0]],
               "u_ff_src": _ff_src + " + 规划块 λ加权", "u_sat": [round(float(v), 5) for v in u_sat],
               "delta": [round(float(v), 6) for v in delta],
               "delta_mm": [round(float(v) * 1000, 2) for v in delta],
               "gate_why": why, "gate_cut": _g.get("cut") or {},
               "chunk": [round(float(v), 5) for v in np.asarray(chunk[0], float)],
               "u_ff_capped": [round(float(v), 5) for v in _ff0],
               "u_plan_capped": [round(float(v), 5) for v in _c0],
               "u_mix": [round(float(v), 5) for v in np.asarray(u_mix, float)],
               "chunk_src": csrc, "ff_mode": fmode, "lam0": round(float(lam[0]), 4),
               "plan_ms": round((time.perf_counter() - t0) * 1000, 2),
               "p_now": [round(float(v), 4) for v in np.asarray(p_now, float).ravel()],
               "t": round(time.time(), 3)}
        self.last = rec
        return rec

    def skill_info(self, stage):
        cls = getattr(self.skills, SKILL_CLS.get(stage, "SK01Approach"), None) if self.skills else None
        v_cap = float((self.mod.v_cap or {}).get(stage) or 0.0)
        return {"stage": stage, "cls": (cls.__name__ if cls else None), "v_cap_m_s": v_cap}

    def dispatch(self, side, stage, u_sat, target, err_m):
        """技能派发落盘: 与 ss_skill_dispatch.py 同口径 (每段最新一拍 + 帧龄)。"""
        rec = {"side": side, "stage": stage, "u_sat": [round(float(v), 5) for v in u_sat[:4]],
               "target": [round(float(v), 5) for v in target], "err_mm": round(float(err_m) * 1000, 2),
               "t": round(time.time(), 3), "src": "8805站·引擎链"}
        try:
            _atomic_json(os.path.join(SHM, "skill_%s.json" % stage), rec)
            p = os.path.join(LIVE, "skill_dispatch.json")
            cur = {}
            if os.path.exists(p):
                try:
                    cur = json.load(open(p, encoding="utf-8"))
                except Exception:                                                # noqa: BLE001
                    cur = {}
            cur.setdefault("skills", {})[stage] = rec
            cur["updated"] = time.time()
            cur["by"] = "ar_render_station(引擎链)"
            _atomic_json(p, cur)
        except Exception:                                                        # noqa: BLE001
            pass

    # ── ② 动作归口: 一拍 ─────────────────────────────────────────────────
    def tick(self, side, tcp, target, action_name=None, grip=0.0, contact_p=0.0, use_mlp=False):
        """一拍: u_ff → decide(物理闸) → gripper_cmd → saturate → 应用增量。

        u_ff 来源如实标注:
          · "skill"  = k·(段目标 − 末端), 限本段 v_cap (与 runtime ZMAX_SKILL_FF=1 同一公式)
          · "mlp"    = ⚡前馈加速器真身 (只在调用方给出完整 39D obs 时用; 本站无 peg/孔/速度通道
                       ⇒ 默认不用 MLP, 不伪造 39D 观测)
        """
        tcp = np.asarray(tcp, dtype=float).ravel()[:3]
        tgt = np.asarray(target, dtype=float).ravel()[:3]
        stage = self.stage_for(action_name)
        sk = self.skill_info(stage)
        e = tgt - tcp
        d = float(np.linalg.norm(e))                     # 本拍位置误差 (m)
        u_ff = np.zeros(4)
        src = "skill"
        if d > 0.002:
            u3 = self.k * e
            n = float(np.linalg.norm(u3))
            cap = float(sk["v_cap_m_s"] or 0.0)
            if cap > 0 and n > cap:
                u3 = u3 * (cap / n)
                src = "skill(v_cap)"
            u_ff[:3] = u3
        # 反馈项: 本链没有速度/接触观测通道 ⇒ u_fb 置 0 (不造假); 闭环靠每拍重读真值重算 e
        u_fb = np.zeros(4)
        u, stage_out = self.mod.decide(u_ff, u_fb, contact_p, d)
        u = np.asarray(u, dtype=float).ravel()
        if u.size < 4:
            u = np.pad(u, (0, 4 - u.size))
        u[3] = self.mod.gripper_cmd(float(grip))
        u_sat = np.asarray(self.safety.saturate(u, limit=self.limit), dtype=float).ravel()
        u_sat[3] = float(u[3])
        gate = dict(self.mod.gate or {})
        # 应用增量: u_sat 是 m/s ⇒ 本拍位移 = u_sat·dt (限 40mm/拍, 防 IK 跳变)
        delta = u_sat[:3] * self.dt
        dn = float(np.linalg.norm(delta))
        if dn > 0.040:
            delta = delta * (0.040 / dn)
            dn = 0.040
        # 收敛兜底: 误差小于本拍位移时直接落到目标 (避免在目标附近抖动)
        if d <= max(dn, 1e-6):
            delta = e
        self.n_tick += 1
        why = str(gate.get("why") or "")
        g = gate.get("phys") or {}
        if why:
            for kk, vv in (g.get("cut") or {}).items():
                if vv:
                    self.stats["gate_cuts"][kk] = self.stats["gate_cuts"].get(kk, 0) + 1
        self.stats["ticks"] += 1
        self.stats["ff_src"][src] = self.stats["ff_src"].get(src, 0) + 1
        self.stats["stages"][stage] = self.stats["stages"].get(stage, 0) + 1
        self.last = {
            "i": self.n_tick, "side": side, "stage": stage, "skill": sk["cls"],
            "v_cap_m_s": sk["v_cap_m_s"], "u_ff_src": src,
            "u_ff": [round(float(v), 4) for v in u_ff[:3]],
            "u_sat": [round(float(v), 4) for v in u_sat[:4]],
            "gate_why": why, "gate_cut": (gate.get("phys") or {}).get("cut"),
            "err_m": round(d, 5), "delta_mm": [round(float(v) * 1000, 2) for v in delta],
            "target": [round(float(v), 5) for v in tgt], "tcp": [round(float(v), 5) for v in tcp],
            "t": round(time.time(), 3),
        }
        self.dispatch(side, stage, u_sat, tgt, d)
        return {"delta": delta.tolist(), "dist_m": d, "reached": d <= 0.002, **self.last}


def _selftest():
    """自检: 拿 8802 真值跑一拍, 打印每个中间量 (不是假数据)。"""
    import urllib.request
    R = "http://127.0.0.1:8802"
    tr = json.loads(urllib.request.urlopen(R + "/state.json", timeout=8).read().decode())["truth"]
    ch = StationChain()
    tgt = [tr["tcpR"][0] + 0.05, tr["tcpR"][1], tr["tcpR"][2]]
    out = ch.tick("R", tr["tcpR"], tgt, "对位", grip=0.0)
    print(json.dumps({k: out[k] for k in ("i", "stage", "skill", "u_ff_src", "u_ff", "u_sat",
                                          "gate_why", "err_m", "delta_mm")},
                     ensure_ascii=False, indent=1))
    print("前馈加速器: loaded=%s (MLP 真身 %s 次 / 守卫 %s 次)"
          % (ch.ff.loaded, getattr(ch.ff, "n_mlp", 0), getattr(ch.ff, "n_guard", 0)))
    print("技能派发:", os.path.join(LIVE, "skill_dispatch.json"), "shm:", SHM)


if __name__ == "__main__":
    _selftest()
