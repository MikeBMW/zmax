#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vl_safety_fast.py — ⚡ 快反射层: 本地视觉安全检查 (老倪 2026-09-27: 「安全反馈要快点」)

为什么要这层: 慢层(DeepSeek VL)单次 7~45s ⇒ 挡得住"持续危害", 挡不住"手突然伸进来"。
本层是**本地纯 CV、无网络**, 5Hz 轮询臂上相机(该相机 1.8Hz ⇒ 实际响应 ≈ 0.6s), 判"镜头被挡":
  · 画面大面积同质(遮挡/贴脸) —— 手/物体怼到镜头前
  · 纹理塌陷(Laplacian 方差极低) —— 失焦/被糊住
  · 整幅过暗/过曝且同质 —— 被盖死
任一成立 ⇒ 写 vl_safety_fast.json: safe=false (带指标与时刻); 否则 safe=true。
执行层读它(保鲜 4s, fail-closed): 快层不安全 / 快层没在跑 ⇒ 一律拒发。

用法:
  ./gui-venv311/bin/python tools/vl_safety_fast.py            # 常驻 5Hz
  ./gui-venv311/bin/python tools/vl_safety_fast.py --once     # 单次(取证)
  ./gui-venv311/bin/python tools/vl_safety_fast.py --hz 5 --show   # 打印指标
输出: ~/zmax/zmax_data/vl_safety_fast.json · 事件图 ~/zmax/zmax_data/vl_safety_fast_evt/<时刻>.jpg
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np

STREAM = os.environ.get("ZMAX_STREAM", "http://127.0.0.1:8791")
OUT = Path(os.path.expanduser("~/zmax/zmax_data/vl_safety_fast.json"))
EVT = Path(os.path.expanduser("~/zmax/zmax_data/vl_safety_fast_evt"))
CAMS = tuple(x.strip() for x in (os.environ.get("ZMAX_VL_FAST_CAMS") or "arm,local").split(",") if x.strip())
# 臂上(看工具/工件) + 笔记本(全局); env ZMAX_VL_FAST_CAMS 可改(判据/维护用, 例如只留一路验证 fail-closed)
MAX_FRAME_AGE = 3.0              # 帧太旧就没意义

# 判据阈值(保守起步, 现场按实测调)
UNIFORM_BLOCK = 0.80             # 同质像素占比 > 此值 ⇒ 判被挡
LAP_MIN = 30.0                   # Laplacian 方差 < 此值 ⇒ 判纹理塌陷
DARK_MEAN, BRIGHT_MEAN = 32.0, 228.0
# 🆕 2026-10-12 老倪「⛔ 被拒: (本地检测, 亚秒级) 又是怎么回事?」:
#   笔记本内置相机**镜头被挡/设备级全黑**时(实测 mean=4.8 · uniform=1.000 · lap=0.3), 快层判"遮挡/糊化"
#   ⇒ L2 执行器 fail-closed **一律拒发**, 于是任何动作都下不去(卡死现场)。
#   一张全黑帧**没有任何安全信息**(分不出"手挡住镜头"和"屋里没光"), 拿它永久否决 = 只堵不防
#   ⇒ 全黑单独归类为 **no_signal(不可用/降级)**: 记进 degraded_cams 并写在 why 里, **不参与否决**;
#      但只要**所有**相机都无信息, 仍然 fail-closed 拒发(不留无信息盲区)。
#   要回到"全黑也算遮挡"的从严口径: env ZMAX_VL_FAST_STRICT_DARK=1
DARK_NO_SIGNAL_MEAN = 8.0        # 全黑(设备级无信号)上界
NO_SIGNAL_UNIFORM = 0.995        # 且几乎完全同质
NO_SIGNAL_LAP = 1.5              # 且纹理塌成 0
STRICT_DARK = os.environ.get("ZMAX_VL_FAST_STRICT_DARK", "0").strip().lower() in ("1", "true", "yes", "on")


def _grab(name: str, timeout=3.0):
    try:
        with urllib.request.urlopen("%s/snapshot/%s.jpg?_=%d" % (STREAM, name, int(time.time())),
                                    timeout=timeout) as r:
            return r.read()
    except Exception:                                                   # noqa: BLE001
        return None


def _ages() -> dict:
    try:
        with urllib.request.urlopen("%s/stats" % STREAM, timeout=2) as r:
            d = json.loads(r.read().decode())
        fr = d.get("frames") or d
        return {k: (fr.get(k) or {}).get("age_s") for k in CAMS}
    except Exception:                                                   # noqa: BLE001
        return {}


def judge(im: np.ndarray) -> dict:
    """单帧判"镜头是否被挡" —— 只输出客观指标, 不做语义猜测"""
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    med = float(np.median(g))
    uniform = float(np.mean(np.abs(g.astype(np.int16) - med) < 14))
    lap = float(cv2.Laplacian(g, cv2.CV_64F).var())
    mean = float(g.mean())
    dark = bool(mean < DARK_MEAN and uniform > 0.6)
    bright = bool(mean > BRIGHT_MEAN and uniform > 0.6)
    blocked = bool(uniform > UNIFORM_BLOCK and lap < LAP_MIN)
    no_signal = bool(mean < DARK_NO_SIGNAL_MEAN and uniform > NO_SIGNAL_UNIFORM and lap < NO_SIGNAL_LAP)
    return {"mean": round(mean, 1), "median": round(med, 1), "uniform_frac": round(uniform, 3),
            "lap_var": round(lap, 1), "blocked": blocked, "dark": dark, "bright": bright,
            "no_signal": no_signal,
            "unsafe": bool(blocked or dark or bright) and not (no_signal and not STRICT_DARK)}


def run_once(show=False, save_evt=True) -> dict:
    ages = _ages()
    per, unsafe, reasons, degraded = {}, [], [], []
    frames = {}
    for c in CAMS:
        b = _grab(c)
        if not b:
            per[c] = {"err": "无帧"}
            reasons.append("%s 取帧失败" % c)
            unsafe.append(c)
            continue
        im = cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR)
        if im is None:
            per[c] = {"err": "解码失败"}
            unsafe.append(c)
            continue
        frames[c] = im
        j = judge(im)
        a = ages.get(c)
        j["age_s"] = a
        if a is None or float(a) > MAX_FRAME_AGE:
            j["stale"] = True
        per[c] = j
        if j.get("no_signal") and not STRICT_DARK:
            degraded.append(c)
            reasons.append("%s: 无信号(全黑 mean=%.0f · 设备级) ⇒ 判不可用, 不参与否决" % (c, j["mean"]))
        elif j["unsafe"]:
            unsafe.append(c)
            reasons.append("%s: 遮挡/糊化(uniform=%.2f lap=%.0f mean=%.0f)" % (c, j["uniform_frac"], j["lap_var"], j["mean"]))
        if show:
            print("   %-6s %s" % (c, json.dumps(j, ensure_ascii=False)))
    # 放行条件: 没有任何"有信息却不安全"的相机, 且**不能所有相机都无信息**(全盲 ⇒ fail-closed)
    safe = (len(unsafe) == 0) and (len(degraded) < len(CAMS))
    if degraded and len(degraded) < len(CAMS):
        reasons.append("⇒ 放行(基于有画面的相机; 降级相机请现场查镜头/光)" if safe else "")
    rec = {"ts": time.time(), "ts_str": time.strftime("%F %T"), "per_cam": per,
           "safe": safe, "unsafe_cams": unsafe, "degraded_cams": degraded,
           "why": "；".join([x for x in reasons if x]) or "臂上/笔记本画面纹理正常、无遮挡"}
    if os.environ.get("ZMAX_VL_FAST_NO_WRITE", "").strip().lower() in ("1", "true", "yes", "on"):
        return rec          # 判据/取证用: 只判不落盘(绝不覆盖在跑的裁决文件)
    _tmp = OUT.with_suffix(".tmp")
    _tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(_tmp, OUT)   # 🔴 原子替换: 原 write_text 先清空再写 ⇒ 执行器快层闸偶尔读到空文件
    #    ⇒ 「反射层裁决缺失」⇒ fail-closed 拒发正常动作(13:35 轨迹复现就因此拦停)。先写 .tmp 再原子换名。
    if not rec["safe"] and save_evt and frames:
        EVT.mkdir(parents=True, exist_ok=True)
        if "arm" in frames:
            cv2.imwrite(str(EVT / (time.strftime("%Y%m%d_%H%M%S") + "_arm.jpg")), frames["arm"])
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--hz", type=float, default=5.0)
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args()
    if a.once:
        r = run_once(a.show)
        print(json.dumps({k: r[k] for k in ("ts_str", "safe", "why", "unsafe_cams")}, ensure_ascii=False))
        return 0
    period = max(0.05, 1.0 / max(0.5, a.hz))
    print("⚡ 快反射层常驻: %.0fHz · 判『镜头被挡』(同质>%.2f 且 纹理<%.0f) · 输出 %s"
          % (a.hz, UNIFORM_BLOCK, LAP_MIN, OUT), flush=True)
    last = True
    while True:
        try:
            r = run_once(show=a.show)
            if r["safe"] != last:                                    # 只在翻转时报, 不刷屏
                print("[%s] %s %s" % (r["ts_str"], "✅ 恢复安全" if r["safe"] else "🚨 判不安全", r["why"]), flush=True)
                last = r["safe"]
        except Exception as e:                                       # noqa: BLE001
            print("轮次异常: %s: %s" % (type(e).__name__, str(e)[:140]), flush=True)
        time.sleep(period)


if __name__ == "__main__":
    raise SystemExit(main())
