#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""位姿全程记录 —— 老倪跑流程时, 把每一拍真值位姿原样落盘 (不抽稀, 不改写)。

    ./.venv-aoi310/bin/python tools/pose_record.py start          # 后台常驻记录
    ./.venv-aoi310/bin/python tools/pose_record.py status         # 当前记了多少/在动么
    ./.venv-aoi310/bin/python tools/pose_record.py stop           # 落盘汇总 + 抽航点
    ./.venv-aoi310/bin/python tools/pose_record.py list

真源: zmax_data/rokae_sdk/tcp_out/latest.json (50Hz, 米/弧度, 带 ts 与秒级时间戳)
落盘: zmax_data/pose_records/rec_<yyyymmdd_hhmmss>/
        poses.jsonl   每拍一行 {ts,t,x,y,z,rx,ry,rz,qx,qy,qz,qw,joint,speed_mm_s,moving}
        summary.json  段/航点/路程/时长/最大速度
        meta.json     起止时刻、样本数、是否有跳变
判据: 记录期间 ts 必须连续推进; 断拍 >1s 记 gap, 不许悄悄补。
"""
from __future__ import annotations

import json
import os
import signal
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRUTH = os.path.join(ROOT, "zmax_data/rokae_sdk/tcp_out/latest.json")
BASE = os.path.join(ROOT, "zmax_data/pose_records")
LIVE = os.path.join(BASE, "_live.json")
PIDF = os.path.join(BASE, "_recorder.pid")

MOVE_MM_S = 3.0      # 判定"在动"的末端速度
GAP_S = 1.0          # 断拍判定
RDP_TOL_MM = 2.0     # 航点抽稀容差


def read_truth():
    try:
        with open(TRUTH, "r") as f:
            return json.load(f)
    except Exception:
        return None


def rec_dir(name):
    return os.path.join(BASE, name)


def latest_dir():
    if not os.path.isdir(BASE):
        return None
    ds = sorted([d for d in os.listdir(BASE)
                 if d.startswith("rec_") and os.path.isdir(os.path.join(BASE, d))])
    return os.path.join(BASE, ds[-1]) if ds else None


# ---------------- 记录 ----------------
def run_record():
    os.makedirs(BASE, exist_ok=True)
    name = "rec_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    d = rec_dir(name)
    os.makedirs(d, exist_ok=True)
    with open(PIDF, "w") as f:
        f.write(str(os.getpid()))

    stop = {"v": False}

    def _sig(signum, frame):
        stop["v"] = True

    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)

    n = gaps = 0
    last_ts = None
    prev = None
    t0 = time.time()
    max_speed = 0.0
    moving_n = 0
    last_moving = False
    path_mm = 0.0
    last_live = 0.0
    fp = open(os.path.join(d, "poses.jsonl"), "w")

    meta = {"rec": name, "started": datetime.now().isoformat(timespec="seconds"),
            "truth": TRUTH, "move_mm_s": MOVE_MM_S, "gap_s": GAP_S}

    while not stop["v"]:
        now = time.time()
        a = read_truth()
        if a and a.get("ts") and a["ts"] != last_ts:
            ts = a["ts"]
            dt = (ts - last_ts) if last_ts else 0.0
            if last_ts and dt > GAP_S:
                gaps += 1
                gaps_l = {"gap_s": round(dt, 3), "at": a.get("t")}
                fp.write(json.dumps(gaps_l, ensure_ascii=False) + "\n")
            sp = 0.0
            if prev is not None and dt > 0:
                dx = (a["x"] - prev["x"]) * 1000.0
                dy = (a["y"] - prev["y"]) * 1000.0
                dz = (a["z"] - prev["z"]) * 1000.0
                dist = (dx * dx + dy * dy + dz * dz) ** 0.5
                sp = dist / dt
                if sp < 5000:          # 跳变(位姿重连)不计路程
                    path_mm += dist
            moving = sp >= MOVE_MM_S
            if moving:
                moving_n += 1
            max_speed = max(max_speed, sp)
            row = {
                "ts": round(ts, 4), "t": a.get("t"),
                "x": a["x"], "y": a["y"], "z": a["z"],
                "rx": a.get("rx"), "ry": a.get("ry"), "rz": a.get("rz"),
                "qx": a.get("qx"), "qy": a.get("qy"), "qz": a.get("qz"), "qw": a.get("qw"),
                "joint": a.get("joint"), "src": a.get("src"),
                "speed_mm_s": round(sp, 2), "moving": moving,
            }
            fp.write(json.dumps(row, ensure_ascii=False) + "\n")
            if n % 25 == 0:
                fp.flush()
            prev = a
            last_moving = moving
            last_ts = ts
            n += 1
        if now - last_live > 0.5:
            last_live = now
            live = {"rec": name, "n": n, "elapsed_s": round(now - t0, 1),
                    "moving": last_moving,
                    "pos_mm": [round(prev["x"] * 1000, 1), round(prev["y"] * 1000, 1),
                               round(prev["z"] * 1000, 1)] if prev else None,
                    "path_mm": round(path_mm, 1), "gaps": gaps, "pid": os.getpid(),
                    "at": datetime.now().isoformat(timespec="seconds")}
            tmp = LIVE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(live, f, ensure_ascii=False)
            os.replace(tmp, LIVE)
        time.sleep(0.01)

    fp.close()
    meta.update({"ended": datetime.now().isoformat(timespec="seconds"),
                 "n_samples": n, "gaps": gaps, "elapsed_s": round(time.time() - t0, 1),
                 "path_mm": round(path_mm, 1), "max_speed_mm_s": round(max_speed, 1),
                 "moving_samples": moving_n})
    with open(os.path.join(d, "meta.json"), "w") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    summ = summarize(d)
    with open(LIVE, "w") as f:
        json.dump({"rec": name, "n": n, "stopped": True, "summary": summ}, f, ensure_ascii=False)
    try:
        os.remove(PIDF)
    except OSError:
        pass
    print(json.dumps({"ok": True, "rec": name, "n": n, "summary": summ}, ensure_ascii=False))


# ---------------- 汇总 ----------------
def _rdp(pts, eps):
    """3D Ramer–Douglas–Peucker, pts=[[x,y,z](mm)...]"""
    if len(pts) < 3:
        return list(range(len(pts)))

    def d(p, a, b):
        ax, ay, az = a
        bx, by, bz = b
        px, py, pz = p
        vx, vy, vz = bx - ax, by - ay, bz - az
        L2 = vx * vx + vy * vy + vz * vz
        if L2 == 0:
            return ((px - ax) ** 2 + (py - ay) ** 2 + (pz - az) ** 2) ** 0.5
        t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy + (pz - az) * vz) / L2))
        cx, cy, cz = ax + t * vx, ay + t * vy, az + t * vz
        return ((px - cx) ** 2 + (py - cy) ** 2 + (pz - cz) ** 2) ** 0.5

    keep = [0, len(pts) - 1]
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        best, bi = -1.0, -1
        for k in range(i + 1, j):
            dd = d(pts[k], pts[i], pts[j])
            if dd > best:
                best, bi = dd, k
        if best > eps:
            keep.append(bi)
            stack.append((i, bi))
            stack.append((bi, j))
    return sorted(set(keep))


def summarize(d):
    rows = []
    gaps = []
    with open(os.path.join(d, "poses.jsonl")) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            o = json.loads(line)
            if "gap_s" in o and "x" not in o:
                gaps.append(o)
                continue
            rows.append(o)
    if not rows:
        return {"n": 0, "note": "没有样本"}
    # 运动段: 连续 moving 或相邻样本位移 > MOVE_MM_S*dt
    segs = []
    cur = None
    for i, r in enumerate(rows):
        if r["moving"]:
            if cur is None:
                cur = {"i0": i, "i1": i}
            else:
                cur["i1"] = i
        else:
            if cur is not None:
                if cur["i1"] > cur["i0"]:
                    segs.append(cur)
                cur = None
    if cur is not None and cur["i1"] > cur["i0"]:
        segs.append(cur)

    out_segs = []
    for s in segs:
        a, b = rows[s["i0"]], rows[s["i1"]]
        pts = [[r["x"] * 1000, r["y"] * 1000, r["z"] * 1000] for r in rows[s["i0"]:s["i1"] + 1]]
        L = sum(((pts[k + 1][0] - pts[k][0]) ** 2 + (pts[k + 1][1] - pts[k][1]) ** 2 +
                 (pts[k + 1][2] - pts[k][2]) ** 2) ** 0.5 for k in range(len(pts) - 1))
        out_segs.append({
            "i": len(out_segs) + 1,
            "t0": a["t"], "t1": b["t"], "dur_s": round(b["ts"] - a["ts"], 2),
            "from_mm": [round(v * 1000, 1) for v in (a["x"], a["y"], a["z"])],
            "to_mm": [round(v * 1000, 1) for v in (b["x"], b["y"], b["z"])],
            "len_mm": round(L, 1),
            "vmax_mm_s": round(max(r["speed_mm_s"] for r in rows[s["i0"]:s["i1"] + 1]), 1),
            "n": s["i1"] - s["i0"] + 1,
        })

    pts = [[r["x"] * 1000, r["y"] * 1000, r["z"] * 1000] for r in rows]
    keep = _rdp(pts, RDP_TOL_MM)
    way = []
    for k in keep:
        r = rows[k]
        way.append({"i": k, "t": r["t"], "mm": [round(v, 1) for v in pts[k]],
                    "abc_deg": [round((r.get("rx") or 0) * 57.29578, 2),
                                round((r.get("ry") or 0) * 57.29578, 2),
                                round((r.get("rz") or 0) * 57.29578, 2)],
                    "joint": r.get("joint")})

    total = sum(((pts[k + 1][0] - pts[k][0]) ** 2 + (pts[k + 1][1] - pts[k][1]) ** 2 +
                 (pts[k + 1][2] - pts[k][2]) ** 2) ** 0.5 for k in range(len(pts) - 1)
                if ((pts[k + 1][0] - pts[k][0]) ** 2 + (pts[k + 1][1] - pts[k][1]) ** 2 +
                    (pts[k + 1][2] - pts[k][2]) ** 2) ** 0.5 < 500)
    summ = {
        "rec": os.path.basename(d), "n": len(rows),
        "t0": rows[0]["t"], "t1": rows[-1]["t"],
        "dur_s": round(rows[-1]["ts"] - rows[0]["ts"], 2),
        "path_mm": round(total, 1),
        "vmax_mm_s": round(max(r["speed_mm_s"] for r in rows), 1),
        "n_moving_samples": sum(1 for r in rows if r["moving"]),
        "segments": out_segs,
        "waypoints": way,
        "gaps": gaps,
        "start_mm": [round(v * 1000, 1) for v in (rows[0]["x"], rows[0]["y"], rows[0]["z"])],
        "end_mm": [round(v * 1000, 1) for v in (rows[-1]["x"], rows[-1]["y"], rows[-1]["z"])],
        "rdp_tol_mm": RDP_TOL_MM,
    }
    with open(os.path.join(d, "summary.json"), "w") as f:
        json.dump(summ, f, ensure_ascii=False, indent=1)
    return summ


# ---------------- CLI ----------------
def pid_alive():
    try:
        with open(PIDF) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return pid
    except Exception:
        return None


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    os.makedirs(BASE, exist_ok=True)
    if cmd == "start":
        pid = pid_alive()
        if pid:
            print(json.dumps({"ok": True, "already": pid, "live": _live()}, ensure_ascii=False))
            return 0
        print(json.dumps({"ok": True, "starting": True, "truth": TRUTH,
                          "truth_age_s": _age()}, ensure_ascii=False))
        run_record()
        return 0
    if cmd == "status":
        print(json.dumps({"ok": True, "pid": pid_alive(), "live": _live(),
                          "truth_age_s": _age()}, ensure_ascii=False))
        return 0
    if cmd == "stop":
        pid = pid_alive()
        if pid:
            os.kill(pid, signal.SIGTERM)
            for _ in range(200):
                if not pid_alive():
                    break
                time.sleep(0.05)
        d = latest_dir()
        if not d:
            print(json.dumps({"ok": False, "why": "没有录制目录"}, ensure_ascii=False))
            return 1
        print(json.dumps({"ok": True, "rec": os.path.basename(d), "summary": summarize(d)},
                         ensure_ascii=False))
        return 0
    if cmd == "list":
        ds = sorted([d for d in os.listdir(BASE) if d.startswith("rec_")]) if os.path.isdir(BASE) else []
        out = []
        for d in ds[-20:]:
            p = os.path.join(BASE, d, "summary.json")
            m = os.path.join(BASE, d, "meta.json")
            o: dict = {"rec": d}
            if os.path.exists(p):
                s = json.load(open(p))
                o.update({"n": s.get("n"), "segments": len(s.get("segments") or []),
                          "path_mm": s.get("path_mm"), "dur_s": s.get("dur_s")})
            elif os.path.exists(m):
                o.update({"partial": True})
            out.append(o)
        print(json.dumps({"ok": True, "n": len(ds), "recs": out}, ensure_ascii=False))
        return 0
    if cmd == "summary":
        d = latest_dir()
        p = os.path.join(d, "summary.json") if d else None
        print(open(p).read() if p and os.path.exists(p) else json.dumps({"ok": False}))
        return 0
    print(__doc__)
    return 2


def _live():
    try:
        return json.load(open(LIVE))
    except Exception:
        return None


def _age():
    try:
        return round(time.time() - json.load(open(TRUTH))["ts"], 2)
    except Exception:
        return None


if __name__ == "__main__":
    sys.exit(main())
