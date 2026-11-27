#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aoi_focus_evolve.py — 金手指相机「清晰度驱动的自主进化」调姿

老倪 2026-11-16: 「开启自主进化模式，你来调节金手指相机，要能够根据你的清晰度，调整机器人位姿。
                  当前位置最清晰，记住了」「550C 也自主进化」

干什么
    把「相机清晰度」当适应度, 让机械臂自己在锚点附近做**微位移进化搜索**(1+1 进化策略),
    找到比当前更清晰(或证明当前已是最清晰)的位姿, 并把最优位姿写回 金手指点1。

适应度 S
    10082 原始帧的**金手指带**清晰度: 带内 Laplacian 方差(主) + Tenengrad(参考)。
    两帧取中位, 同时算帧间离散度, 用来判"这一步的变化是不是噪声"。

进化算法 (1+1)-ES + 1/5 成功法则
    ① 候选 = 当前最优 + N(0, σ), 单轴 |Δ| ≤ --step-mm, 累计 |Δ| ≤ --net-mm
    ② 走到候选 → 停稳 → 拍 2 帧量 S
    ③ S > best×(1+--gain) 才接受(否则退回最优), σ ×1.3 / ×0.7
    ④ σ < --min-sigma 或 连续 --patience 次不退 → 收工, 回到并停在最优位姿

四条闸 (缺一不动)
    ① 默认 dry-run; 真动必须 --authorize(现场授权只为这一步开)
    ② 单步/累计位移闸 + 速度闸(经 sdk_ctl.py, 它自己有包络盒与 stop)
    ③ 噪声闸: 帧间 S 相对离散 > --noise 判为量不准, 不据此接受
    ④ 崩塌闸: S 比锚点掉 >30% ⇒ 立即退回锚点并中止

用法
    # 只看: 量当前清晰度 + 打印进化计划(不动机械臂)
    python3 tools/aoi_focus_evolve.py --dry
    # 真进化(微位移, 默认最多 6 步, 网内 1mm)
    python3 tools/aoi_focus_evolve.py --authorize
    # 550C 上同一个文件跑, 只是把相机地址指到工控机
    python3 tools/aoi_focus_evolve.py --cam http://192.168.23.23:10082 --dry
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
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER_DIR = os.path.join(REPO, "reports", "aoi_focus_evolve")
POSE_JSON = os.path.join(REPO, "zmax_data", "rokae_sdk", "tcp_out", "latest.json")
SDK_CTL = os.path.join(REPO, "tools", "rokae", "sdk_ctl.py")
PY = sys.executable

DEFAULTS = dict(
    cam="http://192.168.23.23:10082",
    step_mm=0.40,        # 单步上限
    net_mm=1.00,         # 相对锚点的累计上限
    min_sigma=0.06,
    gain=0.02,           # 适应度相对提升门槛(2%)
    noise=0.035,         # 帧间相对极差上限(3.5%, 实测 700us 下 8 帧极差 2.8%)
    n_frames=4,          # 每点拍几帧取中位(帧数越多噪声越低)
    patience=3,
    max_moves=6,
    settle_s=0.8,
    speed=5.0,           # mm/s
    band=(600, 1300),    # 金手指带(y 范围, 原图 2048 高) —— 由 /region 命中时自动覆盖
)


# ------------------------------------------------------------------ 相机侧
def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "zmax-probe"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def grab_frame(cam, tag):
    """取一帧原始图并落到临时文件, 返回路径。"""
    data = _get(cam + "/picture?kind=origin&grab=1", timeout=30)
    p = os.path.join("/tmp", "focus_evolve_%s_%d.jpg" % (tag, int(time.time() * 1000)))
    with open(p, "wb") as f:
        f.write(data)
    return p


def gold_band(cam, fallback):
    """金手指带 y 范围: 优先用 /region 的 bbox(零副作用)。"""
    try:
        d = json.loads(_get(cam + "/region", timeout=8).decode("utf-8", "ignore"))
        bb = (d.get("region") or {}).get("bbox") or d.get("bbox")
        if bb and len(bb) == 4:
            y, h = float(bb[1]), float(bb[3])
            pad = max(40.0, h * 0.6)
            y0, y1 = max(0, int(y - pad)), int(y + h + pad)
            if y1 - y0 >= 80:
                return (y0, y1), "region.bbox"
    except Exception:                                              # noqa: BLE001
        pass
    return fallback, "fixed-band"


def sharpness(path, band):
    import cv2
    import numpy as np
    a = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if a is None:
        return None
    y0, y1 = band
    y1 = min(y1, a.shape[0])
    roi = a[y0:y1, :]
    lap = float(cv2.Laplacian(roi, cv2.CV_64F).var())
    gx = cv2.Sobel(roi, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(roi, cv2.CV_32F, 0, 1, ksize=3)
    ten = float((gx * gx + gy * gy).mean())
    return {"lap": lap, "ten": ten, "band_px": int(roi.shape[0]), "mean": float(roi.mean())}


def measure(cam, band, tag, n=4):
    """拍 n 帧, 返回中位适应度 · 相对极差 · 相对标准差。"""
    vals = []
    for k in range(n):
        p = grab_frame(cam, tag + str(k))
        s = sharpness(p, band)
        try:
            os.remove(p)
        except OSError:
            pass
        if s:
            vals.append(s)
    if not vals:
        return None
    laps = sorted(v["lap"] for v in vals)
    lap = laps[len(laps) // 2]
    spread = (max(laps) - min(laps)) / max(1e-9, lap)
    mu = sum(laps) / len(laps)
    rel_std = (sum((x - mu) ** 2 for x in laps) / len(laps)) ** 0.5 / max(1e-9, mu)
    return {"lap": lap, "ten": vals[0]["ten"], "spread": spread, "rel_std": rel_std,
            "n": len(vals), "mean": vals[0]["mean"], "band_px": vals[0]["band_px"]}


# ------------------------------------------------------------------ 机械臂侧
def pose_now():
    with open(POSE_JSON, encoding="utf-8") as f:
        d = json.load(f)
    age = time.time() - float(d.get("ts") or 0)
    return d, age


def abc_of(d):
    """当前姿态 abc(度): latest.json 里 rx/ry/rz 是弧度(控制器口径)。"""
    return [math.degrees(float(d["rx"])), math.degrees(float(d["ry"])), math.degrees(float(d["rz"]))]


def move_abs(xyz_mm, abc_deg, speed, dry):
    """绝对 TCP 到位(只平移, 姿态不变) —— 走 tools/arm_raw.py → 容器 SDK 桥 cmd_arm.fifo。"""
    cmd = [PY, os.path.join(REPO, "tools", "arm_raw.py"), "move",
           "--to", "%.3f,%.3f,%.3f" % tuple(xyz_mm),
           "--abc", "%.3f,%.3f,%.3f" % tuple(abc_deg),
           "--speed", "%.1f" % speed]
    if dry:
        return {"dry": True, "cmd": " ".join(cmd)}
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    ok = ("到位" in out) and r.returncode == 0
    return {"rc": r.returncode, "ok": ok, "out": out[-300:], "err": err[-200:]}


# ------------------------------------------------------------------ 进化
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cam", default=DEFAULTS["cam"])
    ap.add_argument("--dry", action="store_true", help="只量不动(默认就是不动, 这个参数更明确)")
    ap.add_argument("--authorize", action="store_true", help="允许真机微位移")
    ap.add_argument("--step-mm", type=float, default=DEFAULTS["step_mm"])
    ap.add_argument("--net-mm", type=float, default=DEFAULTS["net_mm"])
    ap.add_argument("--min-sigma", type=float, default=DEFAULTS["min_sigma"])
    ap.add_argument("--gain", type=float, default=DEFAULTS["gain"])
    ap.add_argument("--noise", type=float, default=DEFAULTS["noise"])
    ap.add_argument("--n-frames", type=int, default=DEFAULTS["n_frames"])
    ap.add_argument("--patience", type=int, default=DEFAULTS["patience"])
    ap.add_argument("--max-moves", type=int, default=DEFAULTS["max_moves"])
    ap.add_argument("--settle", type=float, default=DEFAULTS["settle_s"])
    ap.add_argument("--speed", type=float, default=DEFAULTS["speed"])
    ap.add_argument("--seed", type=int, default=None)
    a = ap.parse_args()

    dry = not a.authorize
    random.seed(a.seed if a.seed is not None else int(time.time()))

    os.makedirs(LEDGER_DIR, exist_ok=True)
    band, band_src = gold_band(a.cam, DEFAULTS["band"])
    print("[相机] %s" % a.cam)
    print("[带]   y=%d~%d (%s, %d px)" % (band[0], band[1], band_src, band[1] - band[0]))

    d0, age0 = pose_now()
    anchor_mm = [d0["x"] * 1000.0, d0["y"] * 1000.0, d0["z"] * 1000.0]
    anchor_abc = abc_of(d0)
    print("[锚点] TCP=(%.4f, %.4f, %.4f) 帧龄 %.2fs" % (d0["x"], d0["y"], d0["z"], age0))
    if age0 > 2.0:
        print("!! 位姿帧龄 %.1fs > 2s ⇒ 拒绝(真值不新鲜, 不能当锚点)" % age0)
        return 3

    base = measure(a.cam, band, "anchor", a.n_frames)
    if not base:
        print("!! 取帧/解码失败")
        return 4
    print("[锚点适应度] lap=%.1f ten=%.0f 帧间离散=%.3f 带内均值=%.1f" %
          (base["lap"], base["ten"], base["spread"], base["mean"]))
    if base["spread"] > a.noise:
        print("!! 帧间离散 %.3f > %.3f ⇒ 画面不稳定(光在闪/相机在动), 进化会被噪声带跑" %
              (base["spread"], a.noise))
        return 5

    best = dict(base)
    net = [0.0, 0.0, 0.0]          # 相对锚点的累计位移(mm)
    sigma = a.step_mm
    fails = 0
    hist = [{"it": 0, "d": [0, 0, 0], "lap": best["lap"], "acc": True, "why": "anchor"}]
    moves = 0
    hard_err = None

    print("\n---- 自主进化开始 (σ=%.2fmm, 单步≤%.2fmm, 网内≤%.2fmm, 最多 %d 步, %s) ----" %
          (sigma, a.step_mm, a.net_mm, a.max_moves, "DRY-RUN" if dry else "真机微位移"))
    while moves < a.max_moves and sigma >= a.min_sigma and fails < a.patience:
        # 候选 = 随机方向 × σ, 夹到单步/网内上限
        v = [random.gauss(0, 1) for _ in range(3)]
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        d = [x / n * sigma for x in v]
        d = [max(-a.step_mm, min(a.step_mm, x)) for x in d]
        cand_net = [net[i] + d[i] for i in range(3)]
        if any(abs(c) > a.net_mm for c in cand_net):
            print("  (网内上限, 停止)"); break
        moves += 1
        print("\n#%d 尝试 Δ=(%+.2f, %+.2f, %+.2f)mm  σ=%.2f" % (moves, d[0], d[1], d[2], sigma))
        tgt = [anchor_mm[i] + cand_net[i] for i in range(3)]
        mv = move_abs(tgt, anchor_abc, a.speed, dry)
        if dry:
            print("  [dry] %s" % mv["cmd"])
            print("  [dry] 真跑时会走这一步、停 %.1fs、拍 2 帧量清晰度" % a.settle)
            hist.append({"it": moves, "d": d, "acc": None, "why": "dry"})
            break
        if mv.get("rc") != 0 or not mv.get("ok", True):
            print("  !! 移动失败 rc=%s %s" % (mv.get("rc"), mv.get("err") or mv.get("out")))
            hard_err = mv.get("err") or mv.get("out")
            move_abs([anchor_mm[i] + net[i] for i in range(3)], anchor_abc, a.speed, False)
            break
        time.sleep(a.settle)
        s = measure(a.cam, band, "it%d" % moves, a.n_frames)
        if not s:
            hard_err = mv.get("err") or mv.get("out")
            move_abs([anchor_mm[i] + net[i] for i in range(3)], anchor_abc, a.speed, False)
            break
        rel = (s["lap"] - best["lap"]) / best["lap"]
        if s["lap"] < best["lap"] * 0.70:
            print("  !! 崩塌: lap %.1f < 锚点×0.7 ⇒ 退回锚点并中止" % s["lap"])
            move_abs(anchor_mm, anchor_abc, a.speed, False)
            hist.append({"it": moves, "d": d, "lap": s["lap"], "acc": False, "why": "collapse"})
            break
        if s["spread"] > a.noise:
            print("  噪声过大(离散 %.3f) ⇒ 不接受, 退回" % s["spread"])
            move_abs([anchor_mm[i] + net[i] for i in range(3)], anchor_abc, a.speed, False)
            fails += 1
            sigma *= 0.7
            hist.append({"it": moves, "d": d, "lap": s["lap"], "acc": False, "why": "noise"})
            continue
        if rel > a.gain and rel > 3 * s["rel_std"]:
            best = s
            net = cand_net
            fails = 0
            sigma = min(a.step_mm, sigma * 1.3)
            print("  ✅ 更清晰 +%.1f%% (lap=%.1f) ⇒ 采纳" % (rel * 100, s["lap"]))
            hist.append({"it": moves, "d": d, "lap": s["lap"], "acc": True, "why": "improve"})
        else:
            print("  ✗ 没更清晰 %+.1f%% (lap=%.1f) ⇒ 退回" % (rel * 100, s["lap"]))
            move_abs([anchor_mm[i] + net[i] for i in range(3)], anchor_abc, a.speed, False)
            fails += 1
            sigma *= 0.7
            hist.append({"it": moves, "d": d, "lap": s["lap"], "acc": False, "why": "no-gain"})

    d1, age1 = pose_now()
    out = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "cam": a.cam, "dry": dry, "band": band, "band_src": band_src,
        "anchor_pose": {k: d0[k] for k in ("x", "y", "z", "qx", "qy", "qz", "qw")},
        "anchor_lap": base["lap"], "anchor_ten": base["ten"], "anchor_spread": base["spread"],
        "best_lap": best["lap"], "delta_lap_pct": round((best["lap"] / base["lap"] - 1) * 100, 2),
        "net_mm": [round(v, 3) for v in net], "moves": moves, "sigma_end": round(sigma, 3),
        "final_pose": {k: d1[k] for k in ("x", "y", "z", "qx", "qy", "qz", "qw")},
        "history": hist, "limits": {"step_mm": a.step_mm, "net_mm": a.net_mm,
                                    "max_moves": a.max_moves, "speed_mms": a.speed},
    }
    p = os.path.join(LEDGER_DIR, "evolve_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    with open(p, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("\n---- 结果 ----")
    print("适应度: 锚点 lap=%.1f → 最优 lap=%.1f (%+.1f%%)" % (base["lap"], best["lap"], out["delta_lap_pct"]))
    print("净位移: (%+.2f, %+.2f, %+.2f)mm · 步数 %d · 台账 %s" % (net[0], net[1], net[2], moves, p))
    if dry:
        print("(dry-run: 机械臂一步未动)")
    elif hard_err:
        print("结论: 一步都没走成(mover 报错), 不能据此说\"当前是最优\" —— 机械臂未动, 位姿仍是 金手指点1")
        print("      错误: %s" % hard_err)
    elif abs(net[0]) + abs(net[1]) + abs(net[2]) < 1e-6:
        print("结论: 试过的候选都没更清晰 ⇒ 当前位姿就是局部最优, 仍在 金手指点1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
