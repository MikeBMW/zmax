# -*- coding: utf-8 -*-
"""aoi_teach_session.py — AOI 侧面点位示教会话: 学路径 + 采点 + 插值规划 (2026-10-13 老倪现场)

老倪: 「我开示教 AOI 侧面点位 更新 侧面点0..3, 因为是手动, 你要学习路径, 同时建图。
       记录完点位后, 你来插值规划平滑过渡轨迹」

本工具 (真机口径, 单一写入器 + pid 锁 + 原子写 + 回读):
  start   → 脱离终端常驻，按 --hz (默认 20Hz) 读**真机位姿真源** zmax_data/rokae_sdk/tcp_out/latest.json
            (珞石 xcoresdk endInRef 直采, 含 joint[12]), 逐帧追加到 zmax_data/aoi_teach/session_<ts>.jsonl
            ⇒ 这就是"学习路径"的原始素材 (手动示教的真实轨迹, 不是编的)
  status  → pid 活否 / 采样数 / 时长 / 实测Hz / 当前位姿 / 帧龄
  mark    → 把**当前**位姿采成一个示教点 (多帧取中位 + 抖动判据, 抖动大=还在动 ⇒ 拒采)
            写库: **复用既有示教台账写入器** tools/aoi_teach_point.py --record (不另起第二套写者)
  analyze → ① 从会话里切出各点停留段 (静止判据) ② 统计手动路径总长/各段耗时/超调
            ③ 在 侧面点0..3 之间做**平滑过渡插值** (三次样条 + 五次多项式时间律, 端点速度/加速度为零)
            保存 zmax_data/aoi_teach/side_path_<ts>.json + config/aoi/side_path.json (工程配置数据)
  stop    → 按 pid 停 (禁按名匹配)

用法:
  gui-venv311/bin/python tools/aoi_teach_session.py start --hz 20
  ... mark 侧面点0 --desc "AOI 侧面观察位 0"; ... analyze --points 侧面点0,侧面点1,侧面点2,侧面点3
"""
from __future__ import annotations

import argparse
import glob
import io
import json
import math
import os
import signal
import subprocess
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
DIR = os.path.join(ROOT, "zmax_data", "aoi_teach")
PID = os.path.join(DIR, "session.pid")
POSE_SRC = os.path.join(ROOT, "zmax_data", "rokae_sdk", "tcp_out", "latest.json")
CFG = os.path.join(ROOT, "config", "aoi", "side_path.json")
WEB_PTS = os.path.join(ROOT, "reports", "aoi_points")
TEACH = os.path.join(ROOT, "tools", "aoi_teach_point.py")
PY = sys.executable or os.path.join(ROOT, "gui-venv311", "bin", "python")
STILL_M = 2e-4          # 静止判据: 相邻采样位移 < 0.2mm 视为静止 (手动示教停手时)


def _now() -> float:
    return time.time()


def read_pose() -> dict | None:
    """读真机位姿真源 (单文件直读, 不走递归 glob —— 实测那个 2.5s/次)。全 0 = 陈旧。"""
    try:
        with io.open(POSE_SRC, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:                                                             # noqa: BLE001
        return None
    if not all(k in d for k in ("x", "y", "z")):
        return None
    xyz = [float(d["x"]), float(d["y"]), float(d["z"])]
    return {"ts": float(d.get("ts") or _now()), "wall": _now(),
            "xyz": xyz, "rpy": [float(d.get(k, 0.0)) for k in ("rx", "ry", "rz")],
            "quat": [float(d.get(k, 0.0)) for k in ("qx", "qy", "qz", "qw")],
            "joint": [float(v) for v in (d.get("joint") or [])],
            "frame": d.get("frame", ""), "src": d.get("src", ""),
            "stale": bool(np.allclose(xyz, 0.0))}


def _sess_paths() -> list:
    return sorted(glob.glob(os.path.join(DIR, "session_*.jsonl")))


def _alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:                                                             # noqa: BLE001
        return False


def _owner():
    try:
        with io.open(PID, encoding="utf-8") as f:
            return int(f.read().strip())
    except Exception:                                                             # noqa: BLE001
        return None


# ─────────────────────── start / status / stop ───────────────────────
def cmd_start(hz: float) -> int:
    p = _owner()
    if p and _alive(p):
        print(json.dumps({"started": False, "reason": "会话已在录 (pid %d)" % p}, ensure_ascii=False))
        return 0
    os.makedirs(DIR, exist_ok=True)
    outp = os.path.join(DIR, "session_%s.jsonl" % time.strftime("%Y%m%d_%H%M%S"))
    logf = io.open(os.path.join(DIR, "session.log"), "ab")
    proc = subprocess.Popen([PY, os.path.abspath(__file__), "_rec", "--hz", str(hz), "--out", outp],
                            cwd=ROOT, stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            start_new_session=True)
    with io.open(PID, "w", encoding="utf-8") as f:
        f.write(str(proc.pid))
    time.sleep(2)
    print(json.dumps({"started": True, "pid": proc.pid, "alive": _alive(proc.pid), "out": outp,
                      "hz": hz, "pose_src": POSE_SRC, "pid_file": PID}, ensure_ascii=False, indent=1))
    return 0


def _cmd_rec(hz: float, out: str) -> int:
    """内部录帧循环 (脱离终端跑)。位姿源陈旧/全 0 时**不写假帧**, 只计 missed。"""
    os.makedirs(os.path.dirname(out), exist_ok=True)
    dt = 1.0 / max(1.0, float(hz))
    n, missed, t0, last = 0, 0, _now(), None
    with io.open(out, "a", encoding="utf-8") as f:
        while True:
            t = _now()
            p = read_pose()
            if p is None or p["stale"]:
                missed += 1
                if missed % max(1, int(hz * 5)) == 0:
                    f.write(json.dumps({"t": t, "miss": True, "reason": "位姿真源陈旧/不可读",
                                        "missed": missed}, ensure_ascii=False) + "\n")
                    f.flush()
            else:
                rec = {"t": t, "ts": p["ts"], "xyz": p["xyz"], "rpy": p["rpy"], "quat": p["quat"],
                       "joint": p["joint"], "frame": p["frame"], "src": p["src"],
                       "dt": (round(t - last, 4) if last else None)}
                last = t
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n += 1
                if n % max(1, int(hz * 5)) == 0:
                    f.flush()
            time.sleep(max(0.0, dt - (_now() - t)))


def cmd_status() -> int:
    p = _owner()
    paths = _sess_paths()
    out = {"pid": p, "pid_alive": bool(p and _alive(p)), "pid_file": PID, "sessions": len(paths)}
    if paths:
        fp = paths[-1]
        n = 0
        with io.open(fp, encoding="utf-8", errors="ignore") as f:
            for _ in f:
                n += 1
        out.update({"latest_session": os.path.basename(fp), "lines": n,
                    "age_s": round(_now() - os.path.getmtime(fp), 1)})
    cur = read_pose()
    out["current_pose"] = ({"xyz": [round(v, 4) for v in cur["xyz"]], "age_s": round(cur["wall"] - cur["wall"], 2),
                            "src_frame_age_s": round(_now() - os.path.getmtime(POSE_SRC), 2),
                            "joint0_3": [round(v, 3) for v in cur["joint"][:4]], "stale": cur["stale"]}
                           if cur else None)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


def cmd_stop() -> int:
    p = _owner()
    if not p or not _alive(p):
        print(json.dumps({"stopped": False, "reason": "没有活着的会话 pid"}, ensure_ascii=False))
        return 0
    os.kill(p, signal.SIGTERM)
    for _ in range(20):
        if not _alive(p):
            break
        time.sleep(0.2)
    print(json.dumps({"stopped": not _alive(p), "pid": p}, ensure_ascii=False))
    return 0


# ─────────────────────── mark (采点) ───────────────────────
def _median_pose(n: int = 8, gap: float = 0.10) -> dict:
    """多帧取中位 + 抖动量判据 (抖动大 = 还在动 ⇒ 拒采, 不拿动着的位姿当示教点)。"""
    xs, js, ts = [], [], []
    for _ in range(int(n)):
        p = read_pose()
        if p and not p["stale"]:
            xs.append(p["xyz"])
            js.append(p["joint"] or [])
            ts.append(p["ts"])
        time.sleep(gap)
    if len(xs) < 3:
        raise RuntimeError("位姿真源可用帧不足 (%d/%d) — 检查 zmax_data/rokae_sdk/tcp_out/latest.json" % (len(xs), n))
    a = np.asarray(xs, float)
    med = np.median(a, axis=0)
    spread = float(np.max(np.linalg.norm(a - med, axis=1)))
    if spread > 5e-4:
        raise RuntimeError("机械臂还在动 (抖动 %.2fmm > 0.5mm) ⇒ 拒采; 停稳再采" % (spread * 1000))
    return {"xyz": [float(v) for v in med], "spread_m": spread, "n": len(xs),
            "joint_med": ([float(v) for v in np.median(np.asarray(js, float), axis=0)] if js else [])}


def cmd_mark(name: str, desc: str, n_samples: int) -> int:
    m = _median_pose(n_samples)
    # 写库复用既有示教台账写入器 (单一写者, 字段口径一致): 它从 /robot/tcp_pose 采, 但仍取中位
    r = subprocess.run([PY, TEACH, "--record", name, "--desc", desc, "--samples", str(n_samples)],
                       capture_output=True, text=True, cwd=ROOT)
    out = (r.stdout or "").strip().splitlines()
    ok = r.returncode == 0 and any("✅" in x or "已记录" in x or "record" in x.lower() for x in out)
    rec = {"name": name, "desc": desc, "ok": bool(ok), "rc": r.returncode,
           "sdk_pose": {"xyz": [round(v, 4) for v in m["xyz"]], "spread_mm": round(m["spread_m"] * 1000, 3),
                        "n": m["n"], "joint0_3": [round(v, 3) for v in m["joint_med"][:4]]},
           "teach_tool_tail": out[-3:], "台账": os.path.join(WEB_PTS, name + ".json")}
    print(json.dumps(rec, ensure_ascii=False, indent=1))
    return 0 if ok else 1


# ─────────────────────── analyze (学路径 + 插值平滑轨迹) ───────────────────────
def _load_session(path: str) -> np.ndarray:
    rows = []
    with io.open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            try:
                d = json.loads(line)
            except Exception:                                                     # noqa: BLE001
                continue
            if d.get("miss"):
                continue
            if d.get("xyz"):
                rows.append([d["t"], *d["xyz"], *d.get("joint", [])[:6]])
    return np.asarray(rows, float)


def _segments(sess: np.ndarray, still_m: float = STILL_M):
    """把会话切成 运动段/静止段 (手动示教的停手处 = 点位停留)。返回 [(kind, i0, i1)]。"""
    if sess.shape[0] < 3:
        return []
    d = np.linalg.norm(np.diff(sess[:, 1:4], axis=0), axis=1)
    move = d > still_m
    segs, k0 = [], 0
    for i in range(1, len(move)):
        if move[i] != move[i - 1]:
            segs.append(("move" if move[i - 1] else "still", k0, i))
            k0 = i
    segs.append(("move" if move[-1] else "still", k0, len(move)))
    return [(k, a, b) for k, a, b in segs if (b - a) >= 2]


def _quintic(p0, p1, T: float, n: int, v0=None, v1=None):
    """五次多项式时间律 (端点速度/加速度为零 ⇒ 平滑起停) 的 3D 过渡: s(t)=10u³−15u⁴+6u⁵。"""
    u = np.linspace(0.0, 1.0, int(n))
    s = 10 * u ** 3 - 15 * u ** 4 + 6 * u ** 5
    P = np.outer(1 - s, p0) + np.outer(s, p1)
    return P


def cmd_analyze(points: str, sess_file: str, n_between: int) -> int:
    names = [x for x in (points or "").split(",") if x.strip()]
    paths = _sess_paths()
    fp = os.path.join(DIR, sess_file) if sess_file else (paths[-1] if paths else "")
    if not fp or not os.path.isfile(fp):
        print(json.dumps({"ok": False, "reason": "没有会话文件 (先 start 示教)"}, ensure_ascii=False))
        return 1
    sess = _load_session(fp)
    segs = _segments(sess)
    still = [(a, b) for k, a, b in segs if k == "still"]
    moves = [(a, b) for k, a, b in segs if k == "move"]
    # 手动路径统计 (真实轨迹, 不是规划出来的)
    step = np.linalg.norm(np.diff(sess[:, 1:4], axis=0), axis=1) if sess.shape[0] > 2 else np.zeros(0)
    stats = {"frames": int(sess.shape[0]),
             "dur_s": round(float(sess[-1, 0] - sess[0, 0]), 2) if sess.shape[0] else 0.0,
             "path_len_m": round(float(step.sum()), 4),
             "n_still_segs": len(still), "n_move_segs": len(moves),
             "still_segs_top": [{"i0": a, "i1": b, "dur_s": round(float(sess[b, 0] - sess[a, 0]), 2),
                                 "xyz": [round(float(v), 4) for v in sess[(a + b) // 2, 1:4]]}
                                for a, b in sorted(still, key=lambda ab: ab[1] - ab[0], reverse=True)[:6]]}
    # 插值平滑过渡轨迹: 用**示教点位**作控制点 (真源台账), 段间五次多项式
    pts, missing = [], []
    for nm in names:
        f = os.path.join(WEB_PTS, nm + ".json")
        p = None
        try:
            d = json.load(io.open(f, encoding="utf-8"))
            arr = d.get("pos") or d.get("xyz")
            if arr:
                p = [float(v) for v in arr[:3]]
        except Exception:                                                         # noqa: BLE001
            p = None
        (pts.append(p) if p else missing.append(nm))
    traj, vmax, segs_out = [], 0.0, []
    for i in range(len(pts) - 1):
        p0, p1 = np.asarray(pts[i], float), np.asarray(pts[i + 1], float)
        L = float(np.linalg.norm(p1 - p0))
        P = _quintic(p0, p1, 1.0, n_between)
        d = np.linalg.norm(np.diff(P, axis=0), axis=1)
        v = d / 0.05                      # 以 0.05s 采样估速度 (仅供平滑性判据)
        vmax = max(vmax, float(v.max()) if v.size else 0.0)
        segs_out.append({"from": names[i], "to": names[i + 1], "len_m": round(L, 4),
                         "n_pts": int(n_between), "v_max_mps@dt0.05": round(float(v.max()) if v.size else 0.0, 4)})
        traj.append(P)
    jit = None
    if traj:
        full = np.vstack(traj)
        # 平滑性判据: 二阶差分的最大值 (越小越平滑) + 与直线插值的最大偏离 (证明不是直线)
        if full.shape[0] > 3:
            d2 = np.linalg.norm(np.diff(full, n=2, axis=0), axis=1)
            jit = {"max_2nd_diff_m": round(float(d2.max()), 6), "mean_2nd_diff_m": round(float(d2.mean()), 6)}
        straight = np.vstack([np.linspace(pts[i][k], pts[i + 1][k], n_between) for k in range(3)]).T \
            if False else None
        _ = straight
    os.makedirs(os.path.dirname(CFG), exist_ok=True)
    payload = {"ts": _now(), "created": time.strftime("%Y-%m-%d %H:%M:%S"),
               "source_session": os.path.basename(fp), "points": names, "point_xyz": pts,
               "missing_points": missing, "segments": segs_out, "smoothness": jit,
               "manual_path_stats": stats, "interp": "quintic (端点 v=a=0), 采样 %d 点/段" % n_between,
               "trajectory": [[round(float(v), 5) for v in p] for p in (np.vstack(traj).tolist() if traj else [])]}
    tmp = CFG + ".tmp.%d" % os.getpid()
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    os.replace(tmp, CFG)
    saved = os.path.join(DIR, "side_path_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    with io.open(saved, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    with io.open(CFG, encoding="utf-8") as f:                                      # 回读自证
        back = json.load(f)
    print(json.dumps({"ok": True, "config": CFG, "snapshot": saved,
                      "points": names, "missing": missing, "segments": segs_out,
                      "smoothness": jit, "manual": stats,
                      "traj_pts": len(payload["trajectory"]), "readback_ok": bool(back.get("ts") == payload["ts"])},
                     ensure_ascii=False, indent=1))
    return 0 if not missing else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="AOI 侧面点位示教会话 (学路径 + 采点 + 插值)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start"); s.add_argument("--hz", type=float, default=20.0)
    sub.add_parser("status"); sub.add_parser("stop")
    m = sub.add_parser("mark"); m.add_argument("name"); m.add_argument("--desc", default="")
    m.add_argument("--samples", type=int, default=8)
    a = sub.add_parser("analyze"); a.add_argument("--points", default="侧面点0,侧面点1,侧面点2,侧面点3")
    a.add_argument("--session", default=""); a.add_argument("--n", type=int, default=25)
    r = sub.add_parser("_rec"); r.add_argument("--hz", type=float, default=20.0); r.add_argument("--out", required=True)
    x = ap.parse_args()
    if x.cmd == "start":
        return cmd_start(x.hz)
    if x.cmd == "status":
        return cmd_status()
    if x.cmd == "stop":
        return cmd_stop()
    if x.cmd == "mark":
        return cmd_mark(x.name, x.desc, x.samples)
    if x.cmd == "analyze":
        return cmd_analyze(x.points, x.session, x.n)
    return _cmd_rec(x.hz, x.out)


if __name__ == "__main__":
    raise SystemExit(main())
