#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把当前 TCP 真值记成「金手指点1」，同时写 L2 技能库 + AOI 台账(配置中心·工程配置的唯一依据)。

为什么不用 tools/record_point_sdk.py: 它读 ~/zmax/zmax_data/rokae_sdk/tcp_out/latest.json,
而本机 rokae_tcp_sampler 容器常年不起(2026-11-25 备注已记录), 那个文件根本不存在 ⇒ 直接报
"读不到真值源"。这里改从 8793/pose 取真值(它已经回退到 Orin 珞石桥 39061, endInRef 同口径),
再按台账 schema 落盘, 口径与 record_point_sdk.py 一致。
"""
import json
import math
import os
import shutil
import time
import urllib.request

ROOT = r"D:\ZMAX"
NAME = "金手指点1"
POSE_URL = "http://127.0.0.1:8793/pose"
TAUGHT = os.path.join(ROOT, "data/skills/l2_atomic/taught_points.json")
LEDGER_DIR = os.path.join(ROOT, "reports/aoi_points")
LEDGER = os.path.join(LEDGER_DIR, NAME + ".json")
HIST = os.path.join(LEDGER_DIR, NAME + ".history.jsonl")


def euler_quat_zxy(rx, ry, rz):
    sr, cr = math.sin(rx * 0.5), math.cos(rx * 0.5)
    sp, cp = math.sin(ry * 0.5), math.cos(ry * 0.5)
    sy, cy = math.sin(rz * 0.5), math.cos(rz * 0.5)
    return (cy * cp * sr - sy * sp * cr,
            sy * cp * sr + cy * sp * cr,
            sy * cp * cr - cy * sp * sr,
            cy * cp * cr + sy * sp * sr)


def main():
    with urllib.request.urlopen(POSE_URL, timeout=6) as r:
        d = json.loads(r.read().decode("utf-8", "ignore"))
    if d.get("stale"):
        print("❌ 位姿陈旧(stale)，拒绝记录")
        return 1
    xyz = [float(v) for v in (d.get("xyz") or [])]
    abc = [float(v) for v in (d.get("abc_rad") or [])]
    if len(xyz) != 3 or len(abc) != 3:
        print("❌ 位姿不完整:", xyz, abc)
        return 1
    quat = [round(v, 7) for v in euler_quat_zxy(*abc)]
    pos = [round(v, 7) for v in xyz]
    ts = time.strftime("%Y-%m-%d %H:%M:%S")

    os.makedirs(LEDGER_DIR, exist_ok=True)

    # ① AOI 台账(配置中心·工程配置读的就是这份)
    old = None
    if os.path.exists(LEDGER):
        try:
            old = json.load(open(LEDGER, encoding="utf-8"))
        except Exception:
            old = None
        shutil.copy2(LEDGER, LEDGER + ".bak")
    entry = {
        "point": NAME,
        "recorded_at": ts,
        "pos": pos,
        "quat": quat,
        "source": "ROKAE SDK 直读 endInRef (8793/pose ← Orin 39061 桥, 页面同源)",
        "desc": "金手指点1 — 689 现场记录(配置中心·工程配置); abc_deg=%s"
                % [round(math.degrees(a), 3) for a in abc],
    }
    with open(LEDGER, "w", encoding="utf-8") as f:
        json.dump(entry, f, ensure_ascii=False, indent=1)

    # ② 历史留痕
    with open(HIST, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": ts, "action": "replaced" if old else "created",
                            "old": old, "new": entry}, ensure_ascii=False) + "\n")

    # ③ L2 技能库
    tk = {"pos": pos, "quat": quat,
          "desc": entry["desc"],
          "recorded_at": ts,
          "source": entry["source"],
          "n_samples": 1, "spread_pos_m": 0.0,
          "abc_deg": [round(math.degrees(a), 3) for a in abc]}
    store = json.load(open(TAUGHT, encoding="utf-8"))
    pts = store.setdefault("points", {})
    had = NAME in pts
    if had:
        shutil.copy2(TAUGHT, TAUGHT + ".bak")
    pts[NAME] = tk
    store["updated_at"] = ts
    with open(TAUGHT, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=1)

    print(json.dumps({"ok": True, "name": NAME, "pos": pos, "quat": quat,
                      "abc_deg": tk["abc_deg"], "recorded_at": ts,
                      "overwrote": had,
                      "ledger": LEDGER, "taught_points": TAUGHT,
                      "total_points": len(pts)}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
