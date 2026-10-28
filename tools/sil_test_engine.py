#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧪 sil_test_engine.py — 流形引擎**软件在环**测试 (SIL): 用**真 trace** 跑五层闭环。

老倪: 「流形引擎是状态空间工程的核心 … 必须是完整闭环反馈状态空间」+「健康度 H … 指标口径」。

本工具 (真跑, 不造数):
  ① 读真 trace: reports/ss_episode_latest.npz (插拔, 752 帧) · reports/tray_place_latest.npz (摆盘, 2708 帧)
  ② 逐帧喂 ManifoldEngineLoop (度量→健康度→动力 τ→L5/L4/L3/L2→记忆上行→L5 指挥更新)
  ③ 每个场景跑 N 轮 (默认 3, 让 L2 肌肉记忆固化: 同 seed 连续成功 ≥3 次)
  ④ 另跑一次「监督钻取」(注入越限 L4 提案) 取证 L4 监督确实拦过违规动作
  ⑤ 节拍: 同时给「用户口径 <3s」与「唯一依据 ≤3.15s (PVT, config/platform/zmax_perf_spec.json)」两个数
  ⑥ 输出 JSON (reports/sil_engine_<ts>.json) + 屏幕打印 (H/κ/τ 序列统计 · 五层计数 · 记忆/否决)

用法:
  QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/sil_test_engine.py [--repeat 3] [--scene both|insert|tray]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

ROOT = "/home/ubuntu/zmax"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

from lerobot.manifold.engine_loop import ManifoldEngineLoop, STAGES          # noqa: E402
from lerobot.manifold.metric_field import MetricField                        # noqa: E402
from lerobot.manifold.health import HealthThresholds                          # noqa: E402

EP = os.path.join(ROOT, "reports", "ss_episode_latest.npz")
TRAY = os.path.join(ROOT, "reports", "tray_place_latest.npz")
PERF = os.path.join(ROOT, "config", "platform", "zmax_perf_spec.json")


def _perf_takt() -> dict:
    """从指标唯一依据读 CT 目标 (用户口径 vs 唯一依据)。"""
    try:
        d = json.load(open(PERF, encoding="utf-8"))
        for g in d.get("groups", []):
            for m in g.get("metrics", []):
                if m.get("id") == "perf.cycle_s":
                    return {"唯一依据_target": m.get("target"), "唯一依据_stage": m.get("stage")}
    except Exception:                                                       # noqa: BLE001
        pass
    return {"唯一依据_target": "≤3.15 / ≤8 / ≤20–25 s", "唯一依据_stage": "PVT"}


def _frames_from_npz(path: str) -> tuple[list, dict]:
    """真 trace → 引擎帧序列 (逐帧 dict) + meta。字段名以真实 npz 为准。"""
    d = np.load(path, allow_pickle=True)
    meta = dict(d["meta"][0]) if "meta" in d.files else {}
    n = len(d["t"])
    goal = meta.get("goal")
    if goal is None and "target" in d.files:                                # 摆盘没有 goal 字段 ⇒ 用末帧目标
        goal = np.asarray(d["target"][-1], float).tolist()
    def col(k, default=None):
        return d[k] if k in d.files else default
    x = d["x"]
    stage = d["stage"]
    force = col("force", np.zeros(n))
    l4_f = col("l4_f", np.zeros(n))
    l4_veto = col("l4_veto", np.zeros(n))
    u_exec = col("u_exec_vec", np.zeros((n, 4)))
    u_ff = col("u_ff", np.zeros(n))
    frames = []
    for i in range(n):
        frames.append({"t": float(d["t"][i]), "x": np.asarray(x[i], float).tolist(),
                       "stage": str(stage[i]), "force": float(force[i]),
                       "l4_f": float(l4_f[i]), "l4_veto": float(l4_veto[i]),
                       "u_exec": np.asarray(u_exec[i], float).tolist()[:3],
                       "u_ff": float(u_ff[i]), "goal": goal})
    meta["_goal"] = goal
    return frames, meta


def _mk_engine(meta: dict, muscle_path: str, **kw) -> ManifoldEngineLoop:
    m = dict(meta)
    if m.get("_goal") is not None:
        m["goal"] = m["_goal"]
    return ManifoldEngineLoop(metric=MetricField.from_config(), meta=m, muscle_path=muscle_path, **kw)


def _run_scene(name: str, path: str, repeat: int, muscle_path: str) -> dict:
    frames, meta = _frames_from_npz(path)
    seed = int(meta.get("seed", 0))
    success = bool(meta.get("success", meta.get("placed", 0) == meta.get("total", 0)))
    eng = _mk_engine(meta, muscle_path)
    runs = []
    for r in range(int(repeat)):
        info = eng.run_episode(frames, seed=seed, success=success, feed_muscle=True,
                               tag=f"{name}#r{r + 1}")
        runs.append(info)
    s = eng.summary()
    out = {"scene": name, "trace": os.path.relpath(path, ROOT), "frames": len(frames),
           "seed": seed, "success_meta": success, "repeat": int(repeat),
           "runs": runs, "summary": s,
           "muscle_file": muscle_path,
           "muscle_file_exists": os.path.isfile(muscle_path)}
    print(f"\n══ 场景 {name} · {os.path.relpath(path, ROOT)} · {len(frames)} 帧 × {repeat} 轮 ══")
    print(f"  五层真跑次数 : {s['layer_calls']}")
    print(f"  健康度 H     : mean={s['H']['mean']:.4f} min={s['H']['min']:.4f} max={s['H']['max']:.4f}"
          f" · κ_mean={s['health_stats'].get('kappa_mean', float('nan')):.4f}"
          f" · status={s['health_stats'].get('status_counts')} · trend={s['health_stats'].get('trend')}")
    print(f"  动力 τ(m/s²) : mean={s['tau']['mean']:.6f} min={s['tau']['min']:.6f} max={s['tau']['max']:.6f}")
    print(f"  L4 否决总帧  : {s['veto_total']} · 原因={s['l4_veto_reasons']}")
    print(f"  收口闸       : 检查 {s['closure_gate']['checked']} 帧 · 逐轴否决 {s['closure_gate']['axis_veto_frames']} 帧")
    print(f"  记忆上行     : {s['memory_events']} · 各层条数 {s['memory_layers']}")
    print(f"  肌肉记忆     : {s['muscle_src']} · 固化状态 {json.dumps(s['muscle_status'], ensure_ascii=False)}")
    print(f"  末态增益     : {s['gains_final']} · L5 指挥 {s['L5_commands']} 次")
    return out


def _supervision_drill(muscle_path: str) -> dict:
    """监督钻取: 注入越限 L4 提案, 取证 L4 监督真的拦下违规动作 (违规不进入执行)。"""
    print("\n══ 监督钻取: 注入越限 L4 提案, 验证 L4 真拦 ══")
    eng = ManifoldEngineLoop(metric=MetricField.from_config(),
                             meta={"goal": [0.0, 0.6, 0.15]}, muscle_path=muscle_path)
    # 正常帧 (无违规) 与 违规帧 (l4_f 巨大 ⇒ u_nav 越速度上限/越界) 交替
    frames = []
    for i in range(40):
        bad = (i % 4 == 0)
        frames.append({"x": [0.30, 0.60, 0.15], "stage": STAGES[0], "force": 0.2,
                       "l4_f": (50.0 if bad else 0.1), "l4_veto": (1.0 if bad else 0.0),
                       "u_exec": [0.01, 0.0, -0.01], "u_ff": 0.1, "t": i * 0.0125})
    eng.run_episode(frames, seed=999, success=False, feed_muscle=True, tag="drill")
    vetoed = [r for r in eng.records if r["l4_veto"]]
    # 取证: 被否决帧的执行动作仍在 limiter 内 (违规动作没执行)
    cap = eng.L5.safety["speed_cap_ms"]
    exec_ok = all(float(np.max(np.abs(r["u_exec"]))) <= cap + 1e-9 for r in vetoed)
    out = {"injected_frames": 40, "bad_frames": 10, "vetoed": len(vetoed),
           "veto_reasons": dict(eng.L4.veto_reasons), "exec_within_bound_on_veto": bool(exec_ok),
           "speed_cap_ms": cap}
    print(f"  注入违规 {out['bad_frames']}/{out['injected_frames']} 帧 → L4 否决 {out['vetoed']} 帧 "
          f"· 原因={out['veto_reasons']} · 被否帧执行仍在限内={exec_ok}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=3, help="每场景重复轮数 (≥3 触发肌肉记忆固化)")
    ap.add_argument("--scene", default="both", choices=("both", "insert", "tray"))
    a = ap.parse_args()

    t0 = time.time()
    muscle_path = os.environ.get("SIL_MUSCLE_PATH") or "/tmp/sil_muscle_%d.json" % os.getpid()
    if os.path.exists(muscle_path):
        os.remove(muscle_path)                                                  # 冷口径, 可复现

    report: dict = {
        "generated_at": time.strftime("%F %T"),
        "tool": "tools/sil_test_engine.py",
        "engine": "src/lerobot/manifold/engine_loop.py",
        "metric_src": "config/calib/zmax_manifold.json",
        "threshold_src": HealthThresholds.from_config().src,
        "metric": MetricField.from_config().spec(),
        "thresholds": HealthThresholds.from_config().to_dict(),
        "scenes": {},
    }
    scenes = []
    if a.scene in ("both", "insert"):
        scenes.append(("insert(插拔)", EP))
    if a.scene in ("both", "tray"):
        scenes.append(("tray(摆盘)", TRAY))
    for name, path in scenes:
        if not os.path.isfile(path):
            print(f"⚠️ 缺 trace {path} — 跳过 (如实报, 不造数)")
            report["scenes"][name] = {"error": "missing trace", "path": path}
            continue
        report["scenes"][name] = _run_scene(name, path, a.repeat, muscle_path)

    report["supervision_drill"] = _supervision_drill(muscle_path)

    # ── 节拍 (两个口径, 别混) ──
    takt = _perf_takt()
    tray_meta = {}
    if os.path.isfile(TRAY):
        d = np.load(TRAY, allow_pickle=True)
        tray_meta = dict(d["meta"][0]) if "meta" in d.files else {}
    placed = float(tray_meta.get("placed", 0) or 0)
    total_t = 0.0
    if os.path.isfile(TRAY):
        d = np.load(TRAY, allow_pickle=True)
        total_t = float(d["t"][-1])
    per_part = (total_t / placed) if placed > 0 else None
    report["takt"] = {
        "用户口径_s": 3.0, "用户口径_note": "<3s",
        "唯一依据_s": 3.15, "唯一依据_note": "≤3.15s (PVT, " + str(takt.get("唯一依据_stage")) + ")",
        "唯一依据_target": takt.get("唯一依据_target"),
        "实测_tray_episode_total_s": total_t, "实测_tray_placed": placed,
        "实测_tray_per_part_s": per_part,
        "实测_gap_note": "实测/口径之差如实列, 不调口径凑数",
    }
    print("\n══ 节拍 (两口径并列, 不混) ══")
    print(f"  用户口径        : <3s")
    print(f"  唯一依据 (perf spec): {takt.get('唯一依据_target')} (stage={takt.get('唯一依据_stage')})")
    print(f"  实测 tray episode: {total_t:.3f}s / {placed:g} 颗 ⇒ 单颗 {per_part if per_part is None else round(per_part, 4)}s")
    report["elapsed_s"] = round(time.time() - t0, 3)

    out_path = os.path.join(ROOT, "reports", "sil_engine_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(f"\n📄 报告落盘: {os.path.relpath(out_path, ROOT)}  (墙钟 {report['elapsed_s']}s)")
    print(f"   肌肉记忆文件: {muscle_path} (存在={os.path.isfile(muscle_path)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
