#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""evolve_se3_l2l4.py — L4→L3 条件 + L2 真实 action 的**自主进化**闭环 (550C XPU)。

一轮 = 变异 → 训练 → 同口径评估 → 只采纳有提升的 → 台账。

三件事都在这里落:
  L4  → SE(3) 条件: 驱动 trainer 的 --step/--noise (条件噪声与测地线跳步)
  L3  → flow-matching 预测下一状态 (train_se3_flow_cond.py, XPU)
  L2  → **真实 action**: 用采纳模型把 (当前真值 → 下一状态) 解码成 7 维动作
        a = [Δx,Δy,Δz (mm), Δrx,Δry,Δrz (deg), grip], 由 state_truth.jsonl 的
        真值位姿与夹爪列直接算, 不编、不取平均。

判据 (同口径, 按时间块 5 折):
  候选必须**同时**优于 persist(保持不动) 与 linear(线性外推), 且 A_mm 相对改善 ≥ MARGIN;
  否则不采纳, 只记台账 (老倪铁律: 有提升才进默认档)。

用法:
  python3 tools/evolve_se3_l2l4.py --gens 3 --epochs 400 --folds 3          # 夜间: 训练+择优
  python3 tools/evolve_se3_l2l4.py --gens 1 --epochs 60  --folds 2 --dry    # 冒烟
  python3 tools/evolve_se3_l2l4.py --action                               # 出 L2 真实 action
  python3 tools/evolve_se3_l2l4.py --status                               # 看台账
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
V2 = ROOT / "zmax_data/_v2"
LEDGER = ROOT / "zmax_data/se3_evolve/ledger.jsonl"
OUTDIR = ROOT / "zmax_data/se3_evolve"
TRAINER = HERE / "train_se3_flow_cond.py"
DATA = V2 / "real_traj_joints_v2q.json"
LAYERS = V2 / "layers_239.json"

# 变异表: 每个维度都是 trainer 真吃的参数, 不是装饰
MUT = {
    "hidden": [128, 192, 256, 320],
    "epochs": [200, 400, 800],
    "lr": [3e-4, 1e-3, 2e-3],
    "folds": [3],
}
MARGIN = 0.05          # A_mm 相对改善 5% 才算提升


def _now() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def _day_night() -> str:
    h = time.localtime().tm_hour
    return "day" if 7 <= h < 21 else "night"


def _ledger(rec: dict) -> None:
    OUTDIR.mkdir(parents=True, exist_ok=True)
    with open(LEDGER, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _train(cfg: dict, tag: str) -> dict:
    out = OUTDIR / tag
    cmd = [sys.executable, str(TRAINER), "--data", str(DATA), "--layers", str(LAYERS),
           "--device", "xpu", "--epochs", str(cfg["epochs"]), "--folds", str(cfg["folds"]),
           "--hidden", str(cfg["hidden"]), "--out", str(out)]
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=7200)
    js = sorted(out.glob("train_*.json"))
    if not js:
        raise SystemExit("训练没出 json:\n" + (p.stdout[-800:] + p.stderr[-800:]))
    rep = json.loads(js[-1].read_text())
    rep["_wall_s"] = round(time.time() - t0, 1)
    rep["_cfg"] = cfg
    rep["_log_tail"] = p.stdout.strip().splitlines()[-2:]
    return rep


def _score(rep: dict) -> dict:
    b = rep["baselines"]
    m, pz, ln = b["model"], b["persist"], b["linear"]
    return {"model_A": round(m["A_mm"], 3), "persist_A": round(pz["A_mm"], 3),
            "linear_A": round(ln["A_mm"], 3),
            "model_B": round(m["B_deg"], 3), "persist_B": round(pz["B_deg"], 3),
            "model_C": round(m["C_deg"], 3), "persist_C": round(pz["C_deg"], 3),
            "model_E": round(m["E_pct"], 3),
            "gain_vs_persist_pct": round((pz["A_mm"] - m["A_mm"]) / max(pz["A_mm"], 1e-9) * 100, 2),
            "gain_vs_linear_pct": round((ln["A_mm"] - m["A_mm"]) / max(ln["A_mm"], 1e-9) * 100, 2)}


def _adopt_ok(s: dict) -> bool:
    return (s["model_A"] < s["persist_A"] * (1 - MARGIN)
            and s["model_A"] < s["linear_A"] * (1 - MARGIN))


def cmd_evolve(a) -> int:
    if not DATA.exists() or not LAYERS.exists():
        raise SystemExit("缺状态真值: %s / %s" % (DATA, LAYERS))
    phase = _day_night()
    best, best_rep = None, None
    gens = []
    for g in range(a.gens):
        cfg = {k: random.choice(v) for k, v in MUT.items()}
        cfg["epochs"] = a.epochs or cfg["epochs"]
        cfg["folds"] = a.folds or cfg["folds"]
        tag = "g%02d_%s" % (g, _now())
        print("[gen %d] %s" % (g, cfg), flush=True)
        try:
            rep = _train(cfg, tag)
        except SystemExit as e:
            print("[gen %d] 训练失败: %s" % (g, e), flush=True)
            _ledger({"ts": _now(), "phase": phase, "gen": g, "cfg": cfg, "ok": False,
                     "why": str(e)[:400]})
            continue
        s = _score(rep)
        ok = _adopt_ok(s)
        rec = {"ts": _now(), "phase": phase, "gen": g, "tag": tag, "cfg": cfg,
               "wall_s": rep["_wall_s"], "score": s, "adopt": bool(ok),
               "verdict": rep.get("verdict"), "frames": rep.get("frames"),
               "samples": rep.get("samples")}
        _ledger(rec)
        gens.append(rec)
        print("   -> %s | vs persist %+0.2f%% | vs linear %+0.2f%% | 采纳=%s"
              % (s["model_A"], s["gain_vs_persist_pct"], s["gain_vs_linear_pct"], ok), flush=True)
        if ok and (best is None or s["model_A"] < best["model_A"]):
            best, best_rep = s, rep

    if best_rep is not None and best is not None:
        dst = OUTDIR / "adopted.json"
        json.dump({"ts": _now(), "phase": phase, "cfg": best_rep["_cfg"], "score": best,
                   "from": best_rep.get("_cfg")}, open(dst, "w"), ensure_ascii=False, indent=1)
        # 采纳 = 把权重指针写成当前默认 (不进默认档的领域, 只标 ready)
        print("[adopt] %s  (A=%s mm, 优于 persist/linear 且过 MARGIN)" % (dst, best["model_A"]), flush=True)
        code = 0
    else:
        print("[adopt] 本批无候选同时优于 persist 与 linear ⇒ 全部留影子, 不进默认档", flush=True)
        code = 3
    json.dump({"phase": phase, "gens": gens, "adopted": best_rep is not None},
              open(OUTDIR / ("run_%s.json" % _now()), "w"), ensure_ascii=False, indent=1)
    return code


def _read_truth(src: str = "auto"):
    """真机状态真值: live=接口采的 jsonl / traj=239 点真值表 / auto=有 live 且真在动就用 live。"""
    live = ROOT / "zmax_data/se3_evolve/state_truth.jsonl"
    rows = []
    if src == "traj":
        live = Path("/nonexistent")
    if live.exists():
        for ln in live.read_text().splitlines()[-4000:]:
            try:
                rows.append(json.loads(ln))
            except Exception:
                pass
    if rows:
        return rows, str(live)
    fr = json.loads(DATA.read_text())["frames"]
    return [{"x": f["p"][0] * 1000, "y": f["p"][1] * 1000, "z": f["p"][2] * 1000,
             "rpy": f["rpy"], "t": f.get("t", 0.0)} for f in fr], str(DATA)


def cmd_action(a) -> int:
    """L2 真实 action: 真值位姿差分 + 夹爪 → 7 维动作 (mm / deg / 0-1)。"""
    rows, src = _read_truth(getattr(a, "src", "auto"))
    if len(rows) < 3:
        raise SystemExit("真值不足")
    out = []
    grip = 1.0
    for p, q in zip(rows, rows[1:]):
        d = [q["x"] - p["x"], q["y"] - p["y"], q["z"] - p["z"]]
        r0, r1 = p.get("rpy") or [0, 0, 0], q.get("rpy") or [0, 0, 0]
        dr = [math.degrees(r1[i] - r0[i]) for i in range(3)]
        out.append({"i": len(out), "act": [round(v, 4) for v in d + dr] + [grip],
                    "src": "真值位姿差分(mm/deg)+grip", "dt": round(q.get("t", 0) - p.get("t", 0), 4)})
    path = OUTDIR / "l2_action.json"
    OUTDIR.mkdir(parents=True, exist_ok=True)
    json.dump({"src": src, "n": len(out), "dim": 7,
               "note": "L2 真实 action = 真值 pose 差分 + 夹爪; 只在有真值时出",
               "samples": out[:200]}, open(path, "w"), ensure_ascii=False, indent=1)
    print(json.dumps({"ok": True, "n": len(out), "src": src, "out": str(path),
                      "first3": [o["act"] for o in out[:3]]}, ensure_ascii=False))
    return 0


def quat_to_rpy(q) -> list:
    """xyzw → rpy(rad), 与 se3_engine 的 Rz@Ry@Rx 同口径 (往返验过)。"""
    import numpy as np
    x, y, z, w = [float(v) for v in q]
    R = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    ry = math.asin(max(-1.0, min(1.0, -R[2, 0])))
    rx = math.atan2(R[2, 1], R[2, 2])
    rz = math.atan2(R[1, 0], R[0, 0])
    return [rx, ry, rz]


def cmd_collect(a) -> int:
    """白天采集: 真机状态真值 (8797 /api/tcp) → state_truth.jsonl。只读, 零下发。"""
    import urllib.request
    OUTDIR.mkdir(parents=True, exist_ok=True)
    path = ROOT / "zmax_data/se3_evolve/state_truth.jsonl"
    url = a.url
    t0, n, bad, still = time.time(), 0, 0, 0
    _last = None
    with open(path, "a") as f:
        while time.time() - t0 < a.secs:
            try:
                d = json.loads(urllib.request.urlopen(url, timeout=3).read().decode())
                if d.get("stale") or (d.get("age_s") or 9) > 2:
                    bad += 1
                else:
                    # 🔴 /api/tcp 没有 rpy 键 (只有 quat xyzw) —— 直接取 rpy 会全 0,
                    #    L2 action 的旋转 3 维就恒为 0 (看着有值其实是空)。这里由 quat 现算。
                    _q = d.get("quat")
                    _rpy = quat_to_rpy(_q) if _q else [0.0, 0.0, 0.0]
                    rec = {"ts": _now(), "x": round(d["x"] * 1000, 3), "y": round(d["y"] * 1000, 3),
                           "z": round(d["z"] * 1000, 3), "quat": _q,
                           "rpy": [round(float(v), 5) for v in _rpy],
                           "t": round(float(d.get("age_s") or 0), 3), "src": "8797 /api/tcp"}
                    # 🔴 臂静止时采到的是**同一个死点** (实测 8s 36 条全是 664.87,-29.15,295.68),
                    #    拿它训练等于复制粘贴。只记"真在动"的帧, 静止帧单独计数。
                    _mv = 9e9 if _last is None else (
                        abs(rec["x"] - _last["x"]) + abs(rec["y"] - _last["y"]) + abs(rec["z"] - _last["z"])
                        + 50 * sum(abs(rec["rpy"][k] - _last["rpy"][k]) for k in range(3)))
                    if _mv < a.min_move:
                        still += 1
                    else:
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                        n += 1
                    _last = rec
            except Exception:
                bad += 1
            time.sleep(a.hz and 1.0 / a.hz or 0.2)
    print(json.dumps({"ok": True, "collected": n, "still_skipped": still, "bad": bad,
                      "note": "只记真在动的帧 (min_move=%.2f)" % a.min_move, "out": str(path)},
                     ensure_ascii=False))
    return 0


def cmd_status(a) -> int:
    if not LEDGER.exists():
        print("无台账"); return 0
    rows = [json.loads(l) for l in LEDGER.read_text().splitlines() if l.strip()]
    print("台账 %d 代 · 采纳 %d 代" % (len(rows), sum(1 for r in rows if r.get("adopt"))))
    for r in rows[-8:]:
        s = r.get("score") or {}
        print(" %s %s g%s A=%s (persist %s / linear %s) 采纳=%s"
              % (r["ts"], r["phase"], r["gen"], s.get("model_A"), s.get("persist_A"),
                 s.get("linear_A"), r.get("adopt")))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gens", type=int, default=3)
    ap.add_argument("--epochs", type=int, default=0)
    ap.add_argument("--folds", type=int, default=0)
    ap.add_argument("--action", action="store_true")
    ap.add_argument("--src", default="auto", choices=["auto", "live", "traj"])
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--collect", action="store_true", help="白天: 采真机状态真值")
    ap.add_argument("--secs", type=int, default=60)
    ap.add_argument("--hz", type=float, default=5.0)
    ap.add_argument("--min-move", type=float, default=0.3, dest="min_move",
                    help="位移(mm)+50×转角(rad) 低于此值当作静止, 不入库")
    ap.add_argument("--url", default="http://192.168.23.50:8797/api/tcp")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    if a.collect:
        return cmd_collect(a)
    if a.status:
        return cmd_status(a)
    if a.action:
        return cmd_action(a)
    if a.dry:
        a.epochs, a.folds, a.gens = 60, 2, 1
    random.seed(1234)
    return cmd_evolve(a)


if __name__ == "__main__":
    raise SystemExit(main())
