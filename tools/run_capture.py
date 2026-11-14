#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🏃 运行中采数据: 轨迹在跑的时候, 抓「相机帧 + 位姿 + 关节」落盘(只读, 不下发任何指令)。

用途: 给 3DGS / 视觉评测留一份"运行中"的真值数据 —— 事后能对照"这一刻臂在做什么、画面里是什么"。
落盘: zmax_data/run_capture/<时间戳>/frames/NNNN.jpg + manifest.jsonl

用法: python3 tools/run_capture.py [--sec 300] [--hz 2]
"""
import argparse
import json
import os
import time
import urllib.request

REPO = os.path.expanduser("~/zmax")
POSE = os.path.join(REPO, "zmax_data", "rokae_sdk", "tcp_out", "latest.json")
STATE = os.path.join(REPO, "zmax_data", "rokae_sdk", "traj_step_state.json")
OUTROOT = os.path.join(REPO, "zmax_data", "run_capture")
# 相机源(按顺序试第一个通的): D435 在 Orin:8794(真源); 4060:8791 只是代理
CAMS = [
    ("arm_d435", "http://192.168.23.66:8794/frame.jpg"),
    ("local", "http://127.0.0.1:8791/snapshot/local.jpg"),
    ("local2", "http://127.0.0.1:8791/frame.jpg"),
]


def _get(url, t=2.0):
    try:
        with urllib.request.urlopen(url, timeout=t) as r:
            if r.status != 200:
                return None
            b = r.read()
            return b if len(b) > 2000 else None
    except Exception:                                                       # noqa: BLE001
        return None


def _load(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                       # noqa: BLE001
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sec", type=float, default=300.0)
    ap.add_argument("--hz", type=float, default=2.0)
    a = ap.parse_args()

    stamp = time.strftime("%Y%m%d_%H%M%S")
    out = os.path.join(OUTROOT, stamp)
    os.makedirs(os.path.join(out, "frames"), exist_ok=True)
    man = open(os.path.join(out, "manifest.jsonl"), "w", encoding="utf-8")

    cam_name, cam_url = None, None
    for n, u in CAMS:
        if _get(u):
            cam_name, cam_url = n, u
            break
    if not cam_url:
        print("❌ 没有可用相机源")
        return 1
    print("📷 相机: %s (%s) · 落盘 %s · %.1f Hz · 最多 %.0fs"
          % (cam_name, cam_url, out, a.hz, a.sec), flush=True)

    t0 = time.time()
    n_ok = n_fail = 0
    last_cursor = None
    last_progress_t = time.time()
    while time.time() - t0 < a.sec:
        st = _load(STATE)
        cur = st.get("cursor")
        # 🐛 2026-11-14: 原判据 `not running` 会在**轮与轮之间的空档**误判成"轨迹结束"
        #    （实测 19:36 只采到 13 帧就退出了，而那时游标还在 173→183 往前走）。
        #    改成: 只有"既没在跑、游标也 25 秒没动"才算真结束。
        if st.get("running") or cur != last_cursor:
            last_progress_t = time.time()
        elif n_ok > 5 and (time.time() - last_progress_t) > 25.0:
            print("⏹ 轨迹已结束(running=false 且游标 25s 未动) ⇒ 停止采集", flush=True)
            break
        img = _get(cam_url)
        if not img:
            n_fail += 1
            time.sleep(1.0 / max(a.hz, 0.1))
            continue
        ts = time.time()
        fn = "%05d.jpg" % n_ok
        with open(os.path.join(out, "frames", fn), "wb") as fh:
            fh.write(img)
        pose = _load(POSE)
        rec = {
            "i": n_ok, "file": "frames/" + fn, "t": round(ts, 3),
            "t_str": time.strftime("%H:%M:%S", time.localtime(ts)),
            "bytes": len(img), "cam": cam_name,
            "pose_mm": [round(float(pose.get("x", 0)) * 1000, 2),
                        round(float(pose.get("y", 0)) * 1000, 2),
                        round(float(pose.get("z", 0)) * 1000, 2)],
            "pose_age_s": round(ts - float(pose.get("ts") or 0), 3),
            "joint_deg": [round(float(v) * 57.29577951308232, 3) for v in (pose.get("joint") or [])[:6]],
            "cursor": st.get("cursor"), "running": bool(st.get("running")),
        }
        man.write(json.dumps(rec, ensure_ascii=False) + "\n")
        man.flush()
        n_ok += 1
        if st.get("cursor") != last_cursor:
            last_cursor = st.get("cursor")
            print("  %s 帧%05d  %s · 游标 %s" % (rec["t_str"], n_ok, rec["pose_mm"], last_cursor), flush=True)
        time.sleep(1.0 / max(a.hz, 0.1))

    man.close()
    print("✅ 采集完成: %d 帧成功 / %d 次失败 · %s" % (n_ok, n_fail, out), flush=True)
    print("   manifest: %s/manifest.jsonl" % out, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
