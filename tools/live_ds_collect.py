#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""live_ds_collect.py —— 机器人正在跑的时候**只读**采数据 (不碰机器人、不下发、不改任何机器状态)。

采的东西 (每拍一行, 与 3DGS/策略训练同口径):
    ts                 采样时刻
    pose[7]            真机 TCP 真值 x y z (mm) + 四元数 qx qy qz qw   ← tcp_out/latest.json
    joints[6]          关节角 (deg)                                  ← 同上 joint[0:6]
    pose_age_s         真值帧龄
    act_src/act_pose   执行器当时认的 action (src/位姿)               ← ss_live/action.json
    act_i              215 派单游标 (若在跑 traj215)
    grip_last         最近一次夹爪事件 {t, act, mm}                   ← rokae_sdk/grip_events.jsonl
    frame              frames/XXXXXX.jpg 相对路径 (取不到就是 null)
    frame_err          取图失败原因 (调试用)

用法:
    python3 tools/live_ds_collect.py                 # 默认 10Hz 图 / 20Hz 状态, 自动收尾
    python3 tools/live_ds_collect.py --out DIR --secs 1800 --hz 10
收尾条件: 真值 90s 没变化 · 或跑满 --secs · 或收到 SIGTERM。只落盘到 --out。
"""
import argparse
import json
import os
import signal
import sys
import time
import urllib.request

ROOT = os.path.expanduser("~/zmax")
TCP = os.path.join(ROOT, "zmax_data/rokae_sdk/tcp_out/latest.json")
ACTION = os.path.join(ROOT, "zmax_data/ss_live/action.json")
STEP = os.path.join(ROOT, "zmax_data/rokae_sdk/traj_step_state.json")
GRIP = os.path.join(ROOT, "zmax_data/rokae_sdk/grip_events.jsonl")
CAMS = [u.strip() for u in (os.environ.get("DS_CAM_URLS") or
                            "http://192.168.23.66:8794/frame.jpg").split(",") if u.strip()]

_STOP = False


def _sig(_s, _f):
    global _STOP
    _STOP = True


def _jload(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                       # noqa: BLE001
        return None


def _grip_last():
    """最后一条夹爪事件 (文件小, 只读尾部 4KB)。"""
    try:
        with open(GRIP, "rb") as f:
            f.seek(0, 2)
            n = f.tell()
            f.seek(max(0, n - 4096))
            tail = f.read().decode("utf-8", "replace").strip().split("\n")
        for ln in reversed(tail):
            ln = ln.strip()
            if ln.startswith("{"):
                try:
                    return json.loads(ln)
                except Exception:                                           # noqa: BLE001
                    continue
    except Exception:                                                       # noqa: BLE001
        pass
    return None


def _grab(url, timeout=2.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.read(), None
    except Exception as e:                                                  # noqa: BLE001
        return None, "%s: %s" % (type(e).__name__, str(e)[:60])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="")
    ap.add_argument("--hz", type=float, default=20.0, help="状态采样率")
    ap.add_argument("--img_hz", type=float, default=10.0, help="取图上限")
    ap.add_argument("--secs", type=float, default=1800.0, help="最长跑多久")
    ap.add_argument("--idle_s", type=float, default=90.0, help="真值多久不动就收尾")
    a = ap.parse_args()
    out = a.out or os.path.join(ROOT, "zmax_data/datasets/live_%s" % time.strftime("%m%d_%H%M%S"))
    os.makedirs(os.path.join(out, "frames"), exist_ok=True)
    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)
    fpath = os.path.join(out, "steps.jsonl")
    meta = {"out": out, "hz": a.hz, "img_hz": a.img_hz, "cams": CAMS,
            "started": time.strftime("%Y-%m-%d %H:%M:%S"), "readonly": True}
    with open(os.path.join(out, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print("[ds] 开始采集 → %s" % out, flush=True)
    print("[ds] 只读: 读位姿真值/action/夹爪/相机, 不向机器人写任何东西", flush=True)

    n = 0
    n_img = 0
    last_ts = None
    last_move = time.time()
    t_img = 0.0
    t0 = time.time()
    gripev = None
    with open(fpath, "a", encoding="utf-8") as fs:
        while not _STOP and (time.time() - t0) < a.secs:
            now = time.time()
            tcp = _jload(TCP)
            if not tcp or tcp.get("ts") == last_ts:
                # 还没采到第一帧时不算"静默" —— 允许先挂着等机器人动起来
                if last_ts is not None and now - last_move > a.idle_s:
                    print("[ds] 真值 %.0fs 没动 → 收尾" % a.idle_s, flush=True)
                    break
                time.sleep(1.0 / max(a.hz, 1.0))
                continue
            last_ts = tcp.get("ts")
            last_move = now
            age = now - last_ts if isinstance(last_ts, (int, float)) else None
            joint = tcp.get("joint") or []
            j6 = [round(float(v) * 57.29577951308232, 4) for v in joint[:6]] if len(joint) >= 6 else None
            act = _jload(ACTION) or {}
            st = _jload(STEP) or {}
            g = _grip_last()
            if g and g != gripev:
                gripev = g
            rel = None
            if now - t_img >= 1.0 / max(a.img_hz, 1.0):
                t_img = now
                body, err = _grab(CAMS[0])
                if body:
                    rel = "frames/%06d.jpg" % n_img
                    with open(os.path.join(out, rel), "wb") as fi:
                        fi.write(body)
                    n_img += 1
                else:
                    rel = None
            row = {"ts": round(now, 4),
                   "pose": [round(float(tcp.get(k, 0.0)) * 1000.0, 3) for k in ("x", "y", "z")] +
                           [round(float(tcp.get(k, 0.0)), 6) for k in ("qx", "qy", "qz", "qw")],
                   "joints": j6, "pose_age_s": (round(age, 3) if age is not None else None),
                   "act_src": act.get("src"), "act_i": act.get("i"),
                   "act_pose": ([act.get("x"), act.get("y"), act.get("z")] if act.get("x") is not None else None),
                   "act_grip": act.get("grip_mm") or act.get("grip_state"),
                   "step_running": st.get("running"), "step_cursor": st.get("cursor"),
                   "grip_last": gripev, "frame": rel}
            fs.write(json.dumps(row, ensure_ascii=False) + "\n")
            fs.flush()
            n += 1
            if n % 100 == 0:
                print("[ds] %d 拍 · %d 张图 · %.0fs" % (n, n_img, now - t0), flush=True)
    print("[ds] 结束: %d 拍 / %d 图 / 用时 %.0fs → %s" % (n, n_img, time.time() - t0, fpath), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
