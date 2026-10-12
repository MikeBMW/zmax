#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""判据: 流形引擎闭环 + 健康度 (老倪 2026-10-12 设计口径)。

老倪: 「流形引擎是状态空间工程的核心 … 完整闭环反馈状态空间; 健康度 H=(1/κ)·λ_min …」

本判据查 5 条 (每条都真跑真 trace, 不空转):
  ① **闭环完整性**: L5/L4/L3/L2 五层都真跑过 (计数>0) + 每步记录 H/κ/τ/动作/记忆齐 +
     L5 的指挥更新**真改变了**层增益 (对比 apply_updates on/off: on 变 / off 不动 ⇒ 反馈闭合)
  ② **记忆上行与回写真发生**: L2→L3→L4→L5 上行计数=帧数 + 真源 muscle_memory 文件被写且固化
     (n_ok≥3 · champ_u 非空)
  ③ **L4 监督真拦过违规动作**: 真 trace 上 L4 否决>0 (真实力否决帧 + L4提案超力上限帧),
     且**被否动作没进执行** (否决帧 nav_applied=False 且执行在限内)
  ④ **H 序列与阈值判定一致**: 逐帧独立重算 status(H) 与记录 status 100% 一致; 另用状态相关度量
     造出 H 变化 (min<max) 证明分级真会跟着动
  ⑤ **零回归**: 各向同性 ⇒ Γ≡0 · 测地线=欧氏直线 · τ=‖F‖/M · a=F/M (逐位); 且引擎在
     各向同性+零增益+不更新下执行动作 == 原始 L2 动作 (逐位) ⇒ 与旧标量 M 行为一致

用法: QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_engine_loop.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

import numpy as np

ROOT = "/home/ubuntu/zmax"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

from lerobot.manifold.engine_loop import ManifoldEngineLoop, L4Proposal, STAGES      # noqa: E402
from lerobot.manifold.health import HealthThresholds, HealthMonitor, health_from_metric  # noqa: E402
from lerobot.manifold.metric_field import MetricField, MODE_ISOTROPIC, MODE_DIAG     # noqa: E402

EP = os.path.join(ROOT, "reports", "ss_episode_latest.npz")

_ok = _bad = 0


def ck(name, cond, ev=""):
    global _ok, _bad
    if cond:
        _ok += 1
        print("  ✅ %s%s" % (name, ("   ← %s" % ev) if ev else ""))
    else:
        _bad += 1
        print("  ❌ %s%s" % (name, ("   ← %s" % ev) if ev else ""))
    return bool(cond)


def _frames(path, limit=None):
    d = np.load(path, allow_pickle=True)
    meta = dict(d["meta"][0])
    n = len(d["t"]) if limit is None else min(limit, len(d["t"]))
    goal = meta.get("goal")
    if goal is None and "target" in d.files:
        goal = np.asarray(d["target"][-1], float).tolist()
    fr = []
    for i in range(n):
        fr.append({"t": float(d["t"][i]), "x": np.asarray(d["x"][i], float).tolist(),
                   "stage": str(d["stage"][i]), "force": float(d["force"][i]),
                   "l4_f": float(d["l4_f"][i]) if "l4_f" in d.files else 0.0,
                   "l4_veto": float(d["l4_veto"][i]) if "l4_veto" in d.files else 0.0,
                   "u_exec": np.asarray(d["u_exec_vec"][i], float).tolist()[:3],
                   "u_ff": float(d["u_ff"][i]) if "u_ff" in d.files else 0.0})
    meta["goal"] = goal
    return fr, meta, d


print("═══ 判据: 流形引擎闭环 + 健康度 ═══")

frames, meta, raw = _frames(EP)
seed = int(meta.get("seed", 0))
success = bool(meta.get("success", True))
print(f"[真数据] {os.path.relpath(EP, ROOT)} · {len(frames)} 帧 · seed={seed} · success={success}")

# ═══ ① 闭环完整性 ═══
print("① 闭环完整性 (五层真跑 + 每步记录 + L5 指挥真改增益)")
muscle_tmp = os.path.join(tempfile.gettempdir(), "verify_engine_muscle_%d.json" % os.getpid())
if os.path.exists(muscle_tmp):
    os.remove(muscle_tmp)
eng = ManifoldEngineLoop(metric=MetricField.from_config(), meta=dict(meta), muscle_path=muscle_tmp,
                         apply_updates=True)
for r in range(3):
    eng.run_episode(frames, seed=seed, success=success, feed_muscle=True, tag="verify#%d" % r)
s = eng.summary()
ck("L5/L4/L3/L2 四层都被真跑过 (计数>0)", all(v > 0 for v in s["layer_calls"].values()), str(s["layer_calls"]))
ck("层计数 == 帧数×3 (每帧每层都跑)", all(v == len(frames) * 3 for v in s["layer_calls"].values()),
   f"{s['layer_calls']} vs {len(frames) * 3}")
_rec_keys = ("H", "kappa", "tau", "u_exec", "memory", "stage", "status")
ck("每步记录 H/κ/τ/动作/记忆齐", all(k in eng.records[0] for k in _rec_keys), str(list(eng.records[0].keys())))
# 反馈闭合: apply_updates on 会改变增益, off 不动
eng_off = ManifoldEngineLoop(metric=MetricField.from_config(), meta=dict(meta),
                             muscle_path=muscle_tmp + ".off", apply_updates=False)
eng_off.run_episode(frames, seed=seed, success=success, feed_muscle=False)
g_on = s["gains_final"]
g_off = eng_off.summary()["gains_final"]
ck("L5 指挥真改变层增益 (on 变 / off 不动)", (abs(g_on["L4_nav_gain"] - 0.30) > 1e-6
   and abs(g_off["L4_nav_gain"] - 0.30) < 1e-12),
   f"on={g_on} · off={g_off}")

# ═══ ② 记忆上行与回写真发生 ═══
print("② 记忆上行 + 回写真发生")
me = s["memory_events"]
nz = len(frames) * 3
ck("记忆上行 L2→L3→L4→L5 计数 == 帧数", all(me[k] == nz for k in ("L2_to_L3", "L3_to_L4", "L4_to_L5", "L5_writeback")),
   str(me))
ck("四级记忆总线都非空", all(len(v) > 0 for v in eng.memory.values()),
   str({k: len(v) for k, v in eng.memory.items()}))
# 真源 muscle_memory 文件被写 + 固化
mfile = os.path.isfile(muscle_tmp)
doc = json.load(open(muscle_tmp, encoding="utf-8")) if mfile else {}
any_champ = any(v.get("champ_u") for v in doc.values())
max_nok = max([v.get("n_ok", 0) for v in doc.values()] or [0])
ck("真源 muscle_memory 文件已写", mfile, muscle_tmp)
ck("记忆固化真发生 (n_ok≥3 且有 champ_u)", bool(any_champ and max_nok >= 3),
   f"n_ok_max={max_nok} · 桶={list(doc.keys())[:4]}")

# ═══ ③ L4 监督真拦过违规动作 ═══
print("③ L4 监督真拦违规动作")
real_veto_frames = int((raw["l4_veto"] > 0).sum())
vetoed = [r for r in eng.records if r["l4_veto"]]
ck("真 trace 上 L4 否决 > 0", s["veto_total"] > 0, f"引擎否决 {s['veto_total']} 帧 · 真 trace l4_veto 帧 {real_veto_frames}×3")
ck("否决原因含真实信号 (trace力否决 / L4提案超力上限)",
   any(k in s["l4_veto_reasons"] for k in ("trace力否决", "L4提案超力上限")), str(s["l4_veto_reasons"]))
ck("被否动作没进执行 (否决帧 nav_applied=False)",
   bool(vetoed) and all(r["nav_applied"] is False for r in vetoed), f"否决帧 {len(vetoed)}")
ck("所有帧执行都在安全限内 (exec_in_bounds)", all(r["exec_in_bounds"] for r in eng.records),
   f"越限帧 {sum(1 for r in eng.records if not r['exec_in_bounds'])}")

# ═══ ④ H 序列与阈值判定一致 ═══
print("④ H 序列与阈值判定一致")
th = HealthThresholds.from_config()
mismatch = sum(1 for r in eng.records if th.status(r["H"]) != r["status"])
ck("引擎记录 status 与阈值判定 100% 一致", mismatch == 0, f"不一致 {mismatch}/{len(eng.records)}")
# 状态相关度量 ⇒ H 真的变化 (分级跟着动)
gb = np.zeros((3, 3, 3))                       # 每轴一张灵敏度矩阵 (对称)
gb[0] = np.diag([0.35, -0.20, -0.20])
gb[1] = np.diag([-0.15, 0.30, -0.15])
gb[2] = np.diag([-0.10, -0.10, 0.25])
vary_metric = MetricField(3, scale=1.0, mode=MODE_DIAG, diag=[1, 1, 1], gain=gb)
mon = HealthMonitor(thresholds=th)
for i in range(40):
    x = np.array([0.4 * np.sin(i / 5.0), 0.4 * np.cos(i / 7.0), 0.05 * i])
    mon.evaluate(vary_metric.g(x))
vs = mon.stats()
ck("状态相关度量下 H 真变化 (min<max)", vs["H_min"] < vs["H_max"],
   f"H min={vs['H_min']:.4f} max={vs['H_max']:.4f} · status={vs['status_counts']} · trend={vs['trend']}")
ck("变化序列的分级也随阈值判定一致",
   all(health_from_metric(vary_metric.g(np.array([0.4 * np.sin(i / 5.0), 0.4 * np.cos(i / 7.0), 0.05 * i])),
                          th).status == th.status(mon.history[i]) for i in range(40)),
   f"σ(H)={np.std(mon.history):.4f}")

# ═══ ⑤ 零回归 (各向同性 == 旧标量 M) ═══
print("⑤ 零回归: 各向同性引擎行为 == 旧标量 M")
M = 2.0
iso = MetricField(3, scale=M, mode=MODE_ISOTROPIC)
ck("Γ ≡ 0 (各向同性无曲率)", float(np.linalg.norm(iso.christoffel(np.array([0.1, 0.6, 0.15])))) < 1e-9, "")
x0, v0 = np.array([0.1, 0.6, 0.15]), np.array([1.0, 0.0, 0.0])
geo = iso.geodesic_curve(x0, v0, steps=8, dt=0.05)[-1]
ck("测地线 = 欧氏直线 (逐位 ≤1e-12)", float(np.linalg.norm(geo - (x0 + v0 * 0.4))) < 1e-12, "")
# τ = ‖F‖/M, a = F/M 逐帧
eng_iso = ManifoldEngineLoop(metric=iso, meta=dict(meta), muscle_path=muscle_tmp + ".iso",
                             nav_gain0=0.0, flow_gain0=0.0, apply_updates=False)
eng_iso.run_episode(frames, seed=seed, success=success, feed_muscle=False)
tau_err, a_err, exec_eq = 0.0, 0.0, 0
arity = eng_iso.metric.dim
for r, fr in zip(eng_iso.records, frames):
    F = np.asarray(eng_iso.force_vector(fr, np.asarray(fr["x"], float)), float)
    tau_ref = float(np.linalg.norm(F)) / M
    tau_err = max(tau_err, abs(r["tau"] - tau_ref))
    a_err = max(a_err, float(np.linalg.norm(np.asarray(eng_iso.metric.ginv_mul(
        eng_iso._embed(np.asarray(fr["x"], float), arity), eng_iso._embed(F, arity))) - eng_iso._embed(F / M, arity))))
    if np.allclose(r["u_exec"], r["u_l2"], atol=0.0, rtol=0.0):
        exec_eq += 1
# τ 经 g⁻¹ (Cholesky 求解) 得到 ⇒ 允许 float 舍入 (相对 <1e-8); a 直接用同一 g⁻¹ 对照 ⇒ 逐位
ck("各向同性 τ == ‖F‖/M (相对误差 <1e-8, Cholesky 舍入)", tau_err < 1e-8, f"max|Δτ|={tau_err:.2e}")
ck("各向同性 a == F/M (逐位 ≤1e-12)", a_err < 1e-12, f"max|Δa|={a_err:.2e}")
ck("零增益+不更新下 执行动作 == 原始 L2 动作 (逐帧逐位)", exec_eq == len(eng_iso.records),
   f"{exec_eq}/{len(eng_iso.records)} 帧逐位相等")

print()
print("判据结论: %s   (%d 通过 / %d 失败)" % ("✅ PASS" if _bad == 0 else "❌ FAIL", _ok, _bad))
raise SystemExit(0 if _bad == 0 else 1)
