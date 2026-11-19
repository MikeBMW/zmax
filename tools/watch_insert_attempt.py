#!/usr/bin/env python3
"""watch_insert_attempt.py — 盯一次"实际插光模块"的尝试 (力 × 位姿 同轴)。

做的事:
  · 每 2s 读跟随位姿 + 最新一帧六维力
  · 按插口②(下口) 基准算: 插入深度(mm) / 横向偏差(y) / 竖向偏差(z) / 差分接触力
  · 判"卡住": 8s 内插入深度变化 <0.3mm 且 x 不再前进 ⇒ 打一行并记一次
  · 判"停手": 20s 没有新位姿点 ⇒ 自动建数据集 + 训练, 打模型 vs 基线对照, 然后退出

退出码: 0 = 正常收尾(训练已完成) / 1 = 超时 / 3 = 真值断流
用法: python3 -u tools/watch_insert_attempt.py [--mins 40]
"""
import argparse
import glob
import json
import math
import os
import subprocess
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 插口②·下口 (8797 fence 实测): x 761.3→811.6, y 222.5→237.1, z 182.8→192.3
X0, X1, Y0, Y1, Z0, Z1 = 761.3, 811.6, 222.5, 237.1, 182.8, 192.3
CY, CZ = (Y0 + Y1) / 2, (Z0 + Z1) / 2


def get(url, t=3.0):
    with urllib.request.urlopen(url, timeout=t) as r:
        return json.loads(r.read().decode())


def ft_last():
    fs = sorted(glob.glob(os.path.join(ROOT, "zmax_data/rokae_sdk/ft_out/ft_direct_*.jsonl")))
    if not fs:
        return None
    try:
        with open(fs[-1], "rb") as f:
            f.seek(max(0, os.path.getsize(fs[-1]) - 4000))
            lines = [l for l in f.read().decode("utf-8", "ignore").splitlines() if l.strip()]
        return json.loads(lines[-1])
    except Exception:                                                        # noqa: BLE001
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mins", type=float, default=40.0)
    a = ap.parse_args()
    t_end = time.time() + a.mins * 60
    prev_n = None
    last_move = time.time()
    hist = []          # (t, depth, y, z, fx, fy, fz)
    base = None
    stalls = 0
    while time.time() < t_end:
        try:
            f = get("http://127.0.0.1:8817/api/follow")
            A = f["A"]["mm"]
            n = f["route"]["n_pts"]
            age = f.get("age_s") or 0
            if age > 10:
                print("真值陈旧 %.0fs ⇒ 不判" % age, flush=True)
                time.sleep(4)
                continue
            ft = ft_last() or {}
            depth = A[0] - X0
            row = (time.time(), depth, A[1] - CY, A[2] - CZ, ft.get("fx"), ft.get("fy"), ft.get("fz"))
            hist.append(row)
            if prev_n is not None and n > prev_n:
                last_move = time.time()
            prev_n = n
            if base is None and len(hist) == 1:
                base = (ft.get("fx"), ft.get("fy"), ft.get("fz"))
            # 差分接触力
            df = None
            if base and None not in base and ft:
                df = math.sqrt(sum((ft.get(k, 0) - b) ** 2 for k, b in zip(("fx", "fy", "fz"), base)))
            # 卡住判定: 最近 8s 深度变化
            w = [h for h in hist if h[0] > time.time() - 8]
            if len(w) >= 3:
                dd = max(h[1] for h in w) - min(h[1] for h in w)
                if dd < 0.3 and depth > 0 and (time.time() - last_move) > 6:
                    stalls += 1
                    print("%s 卡住#%d 深度 %.1f/%.1fmm · y偏差 %+.1f · z偏差 %+.1f · 差分力 %s N" % (
                        time.strftime("%H:%M:%S"), stalls, depth, X1 - X0, A[1] - CY, A[2] - CZ,
                        "%.1f" % df if df is not None else "?"), flush=True)
                    hist = hist[-3:]
            # 每 15s 打一行进度
            if int(time.time()) % 15 == 0:
                print("%s 点%d 深度%6.1fmm y%+5.1f z%+5.1f 差分力%s" % (
                    time.strftime("%H:%M:%S"), n, depth, A[1] - CY, A[2] - CZ,
                    "%.1fN" % df if df is not None else "-"), flush=True)
                time.sleep(1.2)
            # 停手 ⇒ 训练
            if (time.time() - last_move) > 20 and n and n > 2:
                print("[停手] 20s 无新位姿点 ⇒ 建数据集 + 训练", flush=True)
                r = subprocess.run(["python3", os.path.join(ROOT, "tools/ft_contact_dataset.py"), "--train"],
                                   capture_output=True, text=True, timeout=300)
                print(r.stdout[-2500:] or r.stderr[-800:], flush=True)
                return 0
        except Exception as e:                                               # noqa: BLE001
            print("[warn]", str(e)[:70], flush=True)
        time.sleep(2)
    print("[timeout] %.0f 分钟" % a.mins, flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
