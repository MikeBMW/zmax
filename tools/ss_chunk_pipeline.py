#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_chunk_pipeline.py — 🧩 动作块 (chunk action) 流水线: 引擎出块 → 前馈序列 → 加权 → 逐拍调制 → 安全 → 技能派发。

老倪 2026-10-15: 「Flow Matching Action Head 的输出, 是个 chunk action, 预测 [a_t,…,a_{t+H-1}], 一次推理管多步,
轨迹更平滑, 便于异步执行, 对不? 应该有输出 topic, 在信号分析里显示。这个 chunk action 序列里的 action 动作,
应该给前馈加速器输出的 action 加权; 前馈加速器发出的 action 也应该是一个序列, 由动作调制器调制后继续执行;
调制后输出的也应该是序列 action, 最后从安全执行器输出后, 给到每个技能, 由肌肉记忆的每个技能 接近 对位 下降等,
选取最新的动作执行, 实时执行。最后的技能, 应该通过一个循环服务, 快速流转到具体的技能。」

本模块把这条链**写成真代码** (每个量都是算出来的, 不是图上的箭头):

  ① 出块 chunk[H,4]: 流形引擎**一次求解**的测地线规划 (eng.navigator.compute_geodesic(p_now, goal, H))
     → 每个流形点用引擎自己的 ridge 解码器 (带动作界限幅) 解成动作 ⇒ [a_t … a_{t+H-1}]。
     为什么用测地线: 测地线是流形上**最省力**的路 ⇒ 逐步转角逐段最小 (平滑 = 可测的性质, 见 smooth/turn)。
     ⚠️ 如实口径: Flow-Matching 动作头**本类**支持 chunk_size (默认 7), 但在役实例是 chunk_size=1
        (tools/gui/state_space_sim_real.py:1591) ⇒ 头自己出不了多步。要"头直接出块"须按 H 重训该头
        (训练入口 tools/train_intent_line_predictor.py / joint_train_real_v2.py)。
        本模块给出的是**引擎侧真实可得**的块 (测地线规划), 不是拿未训练权重凑出来的假块。
  ② 前馈序列 u_ff[H,4]: 前馈加速器 (训练左脑 MLP models/ss_left_brain.npz, 真权重) 在**当前 obs** 出 u_ff_now;
     若给了动力学预测器 (dyn), 则用 u_ff 滚出未来 obs 再逐拍过 MLP ⇒ 逐拍真实前馈;
     没有 dyn 时退化为 hold (每步=当前 u_ff), 并在 note 里写明 "ff=hold" (不静默冒充预测)。
  ③ 加权: u_seq[i] = (1-λ_i)·u_ff[i] + λ_i·chunk[i], λ_i = λ_max·(i+1)/H
     (近步信"当下观测出来的前馈", 远步信"引擎规划", 越远权重越大 —— 单调, 可查)。
  ④ 逐拍调制: 动作调制器 decide() 逐步过 (阶段限速只削幅 / 残差否决 / 🧾元任务门控) ⇒ u_mod_seq。
  ⑤ 逐拍安全: 安全执行边界 saturate(u, POS_LIMIT) ⇒ u_safe_seq。
  ⑥ 技能派发: 8 个技能 (接近/对位/下降/抓取/抬起/转移/插入/完成) 各取**本技能最新的那一拍**动作 (实时执行),
     由常驻循环服务 tools/ss_skill_dispatch.py 以高频流转到具体技能 (/dev/shm/zmax_ss_engine/skill_*.json)。

唯一依据落盘 (守护/信号页/技能服务都读它):
  zmax_data/ss_live/chunk_latest.json   最新一块 (话题 zmax/ss_action_chunk 的载荷)
  zmax_data/ss_live/skill_dispatch.json 每技能最新动作 + 帧龄 + 派发计数
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(REPO, "src"), os.path.join(REPO, "tools", "gui")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
LIVE = os.path.join(REPO, "zmax_data", "ss_live")

STAGES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]
ACTION_DIM = 4
W_LAMBDA_MAX = 0.85          # 最远一步的块权重上限 (留 15% 给前馈修正)


def _atomic_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


class ChunkPipeline:
    """块流水线 (无状态, 每周期调一次; 引擎实例由调用方传入)。"""

    def __init__(self, h: int | None = None, lam_max: float = W_LAMBDA_MAX):
        self.h = int(h if h is not None else os.environ.get("ZMAX_CHUNK_H", "8"))
        self.lam_max = float(lam_max)
        self.accel = None
        self.mod = None
        self.sat = None
        self.n = 0
        self.last = None
        self.ff_mode = "none"
        self._load()

    def _load(self):
        from lerobot.policies.left_right.state_space.parallel import FeedforwardAccelerator   # noqa: PLC0415
        from lerobot.policies.left_right.state_space.cognition import ActionModulator         # noqa: PLC0415
        from lerobot.policies.left_right.state_space.safety import saturate                   # noqa: PLC0415
        self.accel = FeedforwardAccelerator()          # 训练左脑 MLP (真权重; 缺权重会自己警告)
        self.mod = ActionModulator()
        self.sat = saturate
        self.ff_mode = "mlp" if getattr(self.accel, "loaded", False) else "analytic(守卫/未加载)"

    # ── ① 出块 ──────────────────────────────────────────────────────────────
    def _chunk(self, eng, p_now):
        """引擎一次求解 → H 步测地线规划 → 逐点解码成动作块 [H,4]。"""
        goal = getattr(eng, "goal_point", None)
        if goal is None or p_now is None:
            return None, "引擎无目标点/project 未建立 ⇒ 出不了块 (如实返回 None)"
        nav = eng.navigator.compute_geodesic(np.asarray(p_now, float).ravel(),
                                             np.asarray(goal, float).ravel(), self.h)
        path = np.asarray(nav["path"], float)                       # [H, latent]
        act = []
        for p in path:
            if getattr(eng, "readout", None) is not None:
                a = np.asarray(p, float) @ eng.readout + eng.readout_b
                if getattr(eng, "action_lo", None) is not None:
                    a = np.clip(a, eng.action_lo, eng.action_hi)     # 硬限幅 (与 step() 同口径)
            else:
                a = np.asarray(p, float)[:ACTION_DIM]
            act.append(np.asarray(a, float).ravel()[:ACTION_DIM])
        return np.asarray(act, float), ("测地线规划 %s · 长度 %.4f · %s"
                                       % (nav.get("geodesic_kind"), float(nav.get("length") or 0),
                                          "ridge 解码(限幅)" if getattr(eng, "readout", None) is not None
                                          else "占位解码(未标定)"))

    # ── ② 前馈序列 ──────────────────────────────────────────────────────────
    def _ff_seq(self, obs, dyn=None, latent=None, h=None):
        h = int(h or self.h)
        u0 = np.asarray(self.accel.forward(obs), float).ravel()[:ACTION_DIM]
        seq, mode = [u0], "hold(单拍前馈保持)"
        if dyn is not None and latent is not None:
            try:
                lat = np.asarray(latent, float).ravel()
                for _ in range(h - 1):
                    lat = np.asarray(dyn.predict(lat, np.concatenate([seq[-1][:3], [0.0]])), float).ravel()
                    o2 = np.asarray(obs, float).copy()
                    o2[:3] = lat[:3] if lat.size >= 3 else o2[:3]        # 只滚位置维 (与先验动力学同口径)
                    seq.append(np.asarray(self.accel.forward(o2), float).ravel()[:ACTION_DIM])
                mode = "rollout(先验动力学滚 future obs 后逐拍过 MLP)"
            except Exception as e:                                       # noqa: BLE001
                mode = "hold(rollout 失败: %s)" % type(e).__name__
        else:
            seq = [u0] * h
        return np.asarray(seq, float), mode

    # ── ③ 加权 ──────────────────────────────────────────────────────────────
    def _blend(self, ff, chunk):
        h = len(chunk)
        lam = np.array([self.lam_max * (i + 1) / h for i in range(h)], float)
        u = (1.0 - lam)[:, None] * ff + lam[:, None] * chunk
        return u, lam

    # ── 主入口 ──────────────────────────────────────────────────────────────
    def step(self, eng, obs, state=None, stage_idx=0, meta=None, u_fb=None, contact_p=0.0,
             residual=0.0, dyn=None, latent=None, u_prev=None, write=True):
        t0 = time.perf_counter()
        obs = np.asarray(obs, float).ravel()
        pr = eng.project(np.asarray(state, float).ravel() if state is not None else obs[:8])
        p_now = pr.get("p")
        chunk, csrc = self._chunk(eng, p_now)
        if chunk is None:
            return {"ok": False, "reason": csrc}
        ff, fmode = self._ff_seq(obs, dyn=dyn, latent=latent)
        u_seq, lam = self._blend(ff, chunk)
        # ④ 逐拍调制 (阶段限速/否决/元任务门控) —— 同步过一遍, 阶段按步序推 (第 i 步属第 stage_idx+i 段, 封顶)
        u_mod, tags = [], []
        for i in range(len(u_seq)):
            st_i = min(len(STAGES) - 1, int(stage_idx) + (0 if i == 0 else 0))   # 同一块内阶段不跳 (由调度器换块)
            uu, tag = self.mod.decide(u_seq[i], (np.zeros(ACTION_DIM) if u_fb is None
                                                 else np.asarray(u_fb, float).ravel()[:ACTION_DIM]),
                                      float(contact_p), float(residual), meta=meta)
            u_mod.append(np.asarray(uu, float).ravel()[:ACTION_DIM])
            tags.append(tag)
        u_mod = np.asarray(u_mod, float)
        # ⑤ 逐拍安全边界
        u_safe = np.asarray([np.asarray(self.sat(u), float).ravel()[:ACTION_DIM] for u in u_mod], float)
        # ⑥ 技能派发: 每个技能取"本技能最新的那一拍" —— 块内第 0 拍就是当前阶段的实时动作, 其余提供给后续技能
        skills = {}
        for i, a in enumerate(u_safe):
            sidx = min(len(STAGES) - 1, int(stage_idx) + i)
            skills[STAGES[sidx]] = {"action": [round(float(x), 6) for x in a],
                                    "step": i, "norm": round(float(np.linalg.norm(a[:3])), 6),
                                    "age_s": round(float(i) * 0.1, 3)}
        out = {
            "ok": True, "ts": time.time(), "cycle": self.n, "h": int(len(chunk)),
            "stage": STAGES[min(len(STAGES) - 1, int(stage_idx))], "stage_idx": int(stage_idx),
            "chunk": [[round(float(x), 6) for x in a] for a in chunk],
            "ff": [[round(float(x), 6) for x in a] for a in ff],
            "u": [[round(float(x), 6) for x in a] for a in u_safe],
            "lam": [round(float(x), 4) for x in lam],
            "chunk_src": csrc, "ff_mode": fmode, "mod_tags": tags,
            # 平滑性: 逐段转角 (测地线应≈0) 与二阶差分 (越小越平滑)
            "turn_max_deg": round(float(np.max(_turn_deg(chunk))), 3) if len(chunk) > 2 else 0.0,
            "turn_mean_deg": round(float(np.mean(_turn_deg(chunk))), 3) if len(chunk) > 2 else 0.0,
            "step_delta": round(float(np.mean(np.linalg.norm(np.diff(chunk[:, :3], axis=0), axis=1))), 6)
            if len(chunk) > 1 else 0.0,
            "jerk": round(float(np.mean(np.linalg.norm(np.diff(chunk[:, :3], n=2, axis=0), axis=1))), 6)
            if len(chunk) > 2 else 0.0,
            "u_norm0": round(float(np.linalg.norm(u_safe[0][:3])), 6),
            "skills": skills,
            "ms": round((time.perf_counter() - t0) * 1e3, 3),
        }
        self.n += 1
        self.last = out
        if write:
            _atomic_json(os.path.join(LIVE, "chunk_latest.json"), out)
            _atomic_json(os.path.join(LIVE, "skill_dispatch.json"),
                         {"ts": out["ts"], "stage": out["stage"], "h": out["h"], "src": "chunk_pipeline",
                          "skills": {k: dict(v, ts=out["ts"]) for k, v in skills.items()}})
        return out

    # 轨迹键 (喂 engine_trace.json → 信号分析直接画)
    def trace_keys(self, d):
        if not d or not d.get("ok"):
            return {}
        ks = {"chunk.H": d["h"], "chunk.平滑_转角_deg": d["turn_mean_deg"],
              "chunk.步间差": d["step_delta"], "chunk.二阶差分": d["jerk"],
              "chunk.首个动作_mps": d["u_norm0"], "chunk.块耗时_ms": d["ms"]}
        for i, a in enumerate(d["chunk"]):
            ks["chunk.块步%d_mps" % i] = round(float(np.linalg.norm(np.asarray(a)[:3])), 6)
        for i, x in enumerate(d["lam"]):
            ks["chunk.λ%d" % i] = float(x)
        for k, v in (d.get("skills") or {}).items():
            ks["skill.%s.最新_mps" % k] = float(v["norm"])
        return ks


def _turn_deg(seq):
    """逐段转角 (度): 相邻两段的夹角。测地线 (slerp/直线) 应≈0 ⇒ 无折角。"""
    s = np.asarray(seq, float)
    if len(s) < 3:
        return np.array([0.0])
    v = np.diff(s[:, :3], axis=0)
    out = []
    for i in range(len(v) - 1):
        n1, n2 = np.linalg.norm(v[i]), np.linalg.norm(v[i + 1])
        if n1 < 1e-9 or n2 < 1e-9:
            out.append(0.0)
            continue
        c = float(np.clip(np.dot(v[i], v[i + 1]) / (n1 * n2), -1.0, 1.0))
        out.append(float(np.degrees(np.arccos(c))))
    return np.asarray(out, float)


# ── CLI: 单独跑一块 (自检/取证) ────────────────────────────────────────────────
def _build_engine():
    """与常驻回路同口径建引擎 (真标定文件 + 真轨迹唯一依据)。"""
    sys.path.insert(0, os.path.join(REPO, "tools"))
    import ss_engine_loop as L                                                    # noqa: PLC0415
    traj = L.read_traj(os.path.join(L.LIVE_DIR, "traj_latest.json")) or L._j(L.TRAJ, None)
    if not traj:
        traj = L.read_traj(os.path.join(REPO, "zmax_data", "ss_live", "traj_latest.json"))
    if not traj:
        raise SystemExit("拿不到轨迹唯一依据 (先跑 tools/ss_engine_loop.py seed 或控制台 ▶ 运行状态空间)")
    M, _src = L.read_M()
    eng, note, traj = L.build_engine(traj, M, False)
    # 🎯 目标点: build_engine 那份因为 traj["obs"] 是 list (JSON 原样) 会 TypeError ⇒ 这里按同口径补上
    #   (目标 = 轨迹末帧收敛态; 没有目标点就出不了块 —— 不编块)
    if getattr(eng, "goal_point", None) is None:
        try:
            O = np.asarray(traj["obs"], float)
            eng.goal_point = np.asarray(eng.project(O[-1, :43])["p"], float).ravel()
            note = note.replace(" ⚠️ 目标未设(TypeError)", " · 目标=轨迹末帧(本模块补设)")
        except Exception as e:                                                    # noqa: BLE001
            note += " · 目标补设失败(%s)" % type(e).__name__
    return eng, note, traj


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--h", type=int, default=None)
    ap.add_argument("--stage", type=int, default=2)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--idx", type=float, default=0.6, help="用轨迹第 idx 比例那一帧当'现在' (0~1; 末帧=已在目标 ⇒ 块退化)")
    a = ap.parse_args()
    eng, note, traj = _build_engine()
    pipe = ChunkPipeline(h=a.h)
    print("引擎: %s" % note)
    print("前馈: %s · 块长 H=%d · 目标点 %s" % (pipe.ff_mode, pipe.h, "有" if getattr(eng, "goal_point", None)
                                            is not None else "无"))
    O = np.asarray(traj["obs"], float)
    _i = int(max(0, min(len(O) - 1, round(a.idx * (len(O) - 1)))))
    obs = O[_i]
    print("当前帧: 轨迹 %d/%d (idx=%.2f) · 目标=末帧 ⇒ 块应有位移" % (_i + 1, len(O), a.idx))
    d = None
    for _ in range(max(1, a.repeat)):
        d = pipe.step(eng, obs, state=obs[:43], stage_idx=a.stage)
    print(json.dumps({k: v for k, v in d.items() if k != "skills"}, ensure_ascii=False, indent=1)[:2000])
    print("技能派发:" if d.get("skills") else "技能派发: 无")
    for k, v in (d.get("skills") or {}).items():
        print("   %-4s 步%-2d ‖a‖=%.5f  age=%.1fs" % (k, v["step"], v["norm"], v["age_s"]))
    print("轨迹键:"); print(json.dumps(pipe.trace_keys(d), ensure_ascii=False, indent=1)[:1200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
