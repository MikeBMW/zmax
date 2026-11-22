#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""record_manual.py —— 示教/手动走轨迹时**只读**记录(不下发任何运动)

老倪口径: 「我重新走一遍, 你看着, 记录」
  - 纯读 jointPos + cartPosture, 30Hz, 不碰控制器状态、不发指令
  - 实时追加 JSONL(zmax_data/rokae_sdk/rec_manual_<ts>.jsonl), 断了也不丢
  - 收到 SIGINT/SIGTERM 时把 JSONL 转成 real_traj_joints.json 同构的 JSON:
      {"n_frames":N, "dur_s":T, "frames":[{"i","t","j"(rad),"p"(m),"rpy"(rad)}]}
  - 转换脚本也可单独跑: python3 record_manual.py --convert <jsonl>

用法(docker 内):
    python3 record_manual.py --rate 30 --secs 0          # 一直录, Ctrl-C/SIGTERM 收尾
    python3 record_manual.py --convert /sdk/rec_manual_x.jsonl
"""
from __future__ import annotations

import json
import math
import os
import signal
import sys
import time

sys.path.insert(0, os.environ.get("ZMAX_SDK_DIR", "/sdk"))

IP = os.environ.get("ZMAX_ROBOT_IP", "192.168.23.160")
SDK = os.environ.get("ZMAX_SDK_DIR", "/sdk")
RATE = float(os.environ.get("ZMAX_REC_RATE") or 30.0)
SECS = float(os.environ.get("ZMAX_REC_SECS") or 0.0)
OUTDIR = os.environ.get("ZMAX_REC_DIR") or os.path.join(SDK, "rec")

_stop = {"flag": False}


def out(**kw):
    print(json.dumps(kw, ensure_ascii=False), flush=True)


def joints(r):
    v = r.jointPos({})
    if isinstance(v, dict):
        for k in ("jointPos", "joint", "values", "data"):
            if k in v:
                v = v[k]
                break
        else:
            v = list(v.values())[0]
    return [float(t) for t in list(v)[:6]]


def posture(r, x):
    ec = {}
    cp = r.cartPosture(x.CoordinateType.endInRef, ec)
    return [float(v) for v in cp.trans], [float(v) for v in cp.rpy]


def convert(jsonl_path: str) -> str:
    rows = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:                                            # noqa: BLE001
                continue
    if not rows:
        return ""
    t0 = rows[0]["t"]
    frames = []
    for k, r in enumerate(rows):
        _p = list(r["p"] or [0, 0, 0])          # cartPosture 直接给 m; >20 才当 mm
        if max(abs(v) for v in _p) > 20.0:
            _p = [v / 1000.0 for v in _p]
        frames.append({"i": k, "t": round(r["t"] - t0, 4),
                       "j": [round(v, 6) for v in r["j"]],
                       "p": [round(v, 6) for v in _p],
                       "rpy": [round(v, 6) for v in (r.get("rpy") or [0, 0, 0])]})
    data = {"n_frames": len(frames), "dur_s": round(frames[-1]["t"], 3),
            "src": os.path.basename(jsonl_path), "frames": frames}
    dst = jsonl_path.replace(".jsonl", ".json")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return dst


def main() -> int:
    if "--convert" in sys.argv:
        p = sys.argv[sys.argv.index("--convert") + 1]
        d = convert(p)
        out(ok=bool(d), json=d)
        return 0 if d else 2

    import xcoresdk_python as x  # noqa: E402

    os.makedirs(OUTDIR, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(OUTDIR, "rec_manual_%s.jsonl" % ts)

    r = x.xMateRobot()
    try:
        r.connectToRobot(IP)
    except Exception as e:                                               # noqa: BLE001
        out(ok=False, why="连不上 %s: %s" % (IP, e))
        return 2

    def _sig(_s, _f):
        _stop["flag"] = True
    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    dt = 1.0 / max(1.0, RATE)
    t0 = time.monotonic()
    n = 0
    f = open(path, "w", encoding="utf-8")
    out(ok=True, step="recording", file=path, rate=RATE, secs=SECS,
        power=str(r.powerState({})), note="只读记录, 不发任何运动指令")
    last_err = None
    while not _stop["flag"]:
        if SECS > 0 and time.monotonic() - t0 >= SECS:
            break
        t = time.monotonic()
        try:
            j = joints(r)
            p, rpy = posture(r, x)
        except Exception as e:                                           # noqa: BLE001
            last_err = "%s: %s" % (type(e).__name__, e)
            time.sleep(0.2)
            continue
        f.write(json.dumps({"t": round(t, 4), "j": [round(v, 6) for v in j],
                            "p": [round(v, 3) for v in p],
                            "rpy": [round(v, 5) for v in rpy]}) + "\n")
        n += 1
        if n % int(max(1, RATE * 10)) == 0:
            out(step="tick", n=n, t_s=round(t - t0, 1),
                j_deg=[round(math.degrees(v), 2) for v in j],
                tcp=[round(v, 1) for v in p])
        sl = dt - (time.monotonic() - t)
        if sl > 0:
            time.sleep(sl)
    f.close()
    dur = time.monotonic() - t0
    dst = convert(path)
    out(ok=True, step="done", n=n, dur_s=round(dur, 2), jsonl=path, json=dst,
        err=last_err or "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
