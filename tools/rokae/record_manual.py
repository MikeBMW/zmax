#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""record_manual.py —— 示教/手动走轨迹时**只读**记录(不下发任何运动) + 相机同步采集

老倪口径: 「我重新走一遍, 你看着, 记录」
  - 纯读 jointPos + cartPosture, 30Hz, 不碰控制器状态、不发指令
  - **同步抓相机帧** (arm/local, 默认 10Hz), 与状态同一时间基准 time.monotonic()
  - 实时追加 JSONL(zmax_data/rokae_sdk/rec_manual_<ts>.jsonl), 断了也不丢
  - 帧落 frames_<ts>/<cam>_<idx>.jpg, 另有 frames_<ts>/index.json 记时间/延迟/间隙
  - 收尾把 JSONL 转成 real_traj_joints.json 同构 + 每帧带 img 路径:
      {"n_frames":N,"dur_s":T,"sync":{...},"frames":[{"i","t","j","p","rpy","img"}]}

为什么要同步采集 (2026-11-22 教训):
  11-21 那两份录制只有 j/p/rpy, 没有图像 ⇒ 到现在也没法喂 SmolVLA (缺 observation.images);
  当晚 17:03 采录制时相机帧只有 2 张 ⇒ 事后无法配准。所以图像必须与状态同一循环、同一时钟采。

用法(docker 内, --network host 可直连 8791 快照):
    python3 record_manual.py --rate 30 --secs 30            # 录 30s (夹臂+相机)
    python3 record_manual.py --cam off --secs 10            # 只要状态(旧口径)
    python3 record_manual.py --cam arm --cam-hz 15 --secs 30
    python3 record_manual.py --probe-camera                 # 只测相机链路(不用连机器人)
    python3 record_manual.py --convert /sdk/rec_manual_x.jsonl

环境变量: ZMAX_REC_RATE / ZMAX_REC_SECS / ZMAX_REC_DIR / ZMAX_REC_CAM / ZMAX_REC_CAM_HZ
"""
from __future__ import annotations

import json
import math
import os
import signal
import statistics
import sys
import threading
import time
import urllib.request

sys.path.insert(0, os.environ.get("ZMAX_SDK_DIR", "/sdk"))

IP = os.environ.get("ZMAX_ROBOT_IP", "192.168.23.160")
SDK = os.environ.get("ZMAX_SDK_DIR", "/sdk")
RATE = float(os.environ.get("ZMAX_REC_RATE") or 30.0)
SECS = float(os.environ.get("ZMAX_REC_SECS") or 0.0)
OUTDIR = os.environ.get("ZMAX_REC_DIR") or os.path.join(SDK, "rec")
CAMS = {"arm": "http://127.0.0.1:8791/snapshot/arm.jpg",
        "local": "http://127.0.0.1:8791/snapshot/local.jpg",
        # 2026-11-23 实测: 8791 的 local(笔记本内置 /dev/video2) 现在整段全黑(mean 5.7/255, std 1.1),
        # local2(中央相机, Intel USB 经 8812 隧道) 正常(mean 161.7/255) ⇒ 双视角录制用 arm,local2。
        "local2": "http://127.0.0.1:8791/snapshot/local2.jpg"}
CAM_SEL = (os.environ.get("ZMAX_REC_CAM") or "arm,local").strip()
CAM_HZ = float(os.environ.get("ZMAX_REC_CAM_HZ") or 10.0)

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


def _fetch(url: str, timeout: float = 3.0) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read()


class CamTap:
    """相机抓帧线程: 与 30Hz 状态循环**解耦**。

    实测(2026-11-22 首版同步版, 同步抓帧): 状态 28.5Hz · 帧 8.9Hz · 最大间隙 369/516ms
    ⇒ 单次抓帧慢(275ms)会把状态采样一起拖住。改成独立线程后状态恒 30Hz, 状态行按
    **最近一帧** (t_frame <= t_state) 绑定图像, 并记 img_age_ms 供配准判据用。
    """

    def __init__(self, sel: str, hz: float, outdir: str):
        self.names = [c for c in (s.strip() for s in sel.split(",")) if c in CAMS]
        self.hz = max(0.5, hz)
        self.dir = outdir
        self.enabled = bool(self.names)
        self.idx = {c: 0 for c in self.names}
        self.manifest = []
        self.lat = []
        self.last_t = {c: 0.0 for c in self.names}
        self.gaps = {c: [] for c in self.names}
        self.errors = {c: 0 for c in self.names}
        self.latest = {c: None for c in self.names}      # {cam: (t, file)}
        self._stop = threading.Event()
        self._th = None
        self._dur = 0.0
        if self.enabled:
            os.makedirs(self.dir, exist_ok=True)

    def start(self):
        if not self.enabled:
            return
        self._th = threading.Thread(target=self._run, name="cam-tap", daemon=True)
        self._th.start()

    def stop(self):
        self._stop.set()
        if self._th:
            self._th.join(timeout=3.0)
        self._dur = max(self._dur, 0.001)

    def _run(self):
        period = 1.0 / self.hz
        while not self._stop.is_set():
            t_sched = time.monotonic()
            for cam in self.names:
                self._grab(cam)
            sl = period - (time.monotonic() - t_sched)
            if sl > 0:
                self._stop.wait(sl)

    def _grab(self, cam: str):
        t0 = time.monotonic()
        try:
            raw = _fetch(CAMS[cam])
        except Exception as e:                                           # noqa: BLE001
            self.errors[cam] += 1
            if self.errors[cam] <= 3:
                out(step="cam_err", cam=cam, why="%s: %s" % (type(e).__name__, e))
            return
        lat_ms = (time.monotonic() - t0) * 1000.0
        if len(raw) < 1024:
            self.errors[cam] += 1
            return
        self.idx[cam] += 1
        name = "%s_%06d.jpg" % (cam, self.idx[cam])
        try:
            with open(os.path.join(self.dir, name), "wb") as f:
                f.write(raw)
        except OSError:
            self.errors[cam] += 1
            return
        t = time.monotonic()
        if self.last_t[cam] > 0:
            self.gaps[cam].append(round((t - self.last_t[cam]) * 1000.0, 1))
        self.last_t[cam] = t
        self.lat.append(lat_ms)
        self.latest[cam] = (t, name)
        self.manifest.append({"i": self.idx[cam], "t": round(t, 4), "cam": cam,
                              "file": name, "bytes": len(raw), "lat_ms": round(lat_ms, 1)})

    def bind(self, t_state: float) -> tuple[dict, dict]:
        """状态时刻 -> 该时刻之前最近的一帧 (不含未来帧)。"""
        imgs, ages = {}, {}
        for cam in self.names:
            v = self.latest.get(cam)
            if not v:
                continue
            t_f, name = v
            imgs[cam] = name
            ages[cam] = round((t_state - t_f) * 1000.0, 1)
        return imgs, ages

    def summary(self, dur_s: float) -> dict:
        if not self.enabled:
            return {"enabled": False}
        s = {"enabled": True, "cams": self.names, "hz": self.hz, "dir": self.dir,
             "dur_s": round(dur_s, 2), "frames": {c: self.idx[c] for c in self.names},
             "effective_hz": {c: round(self.idx[c] / dur_s, 2) if dur_s else 0 for c in self.names},
             "errors": self.errors}
        if self.lat:
            lat = sorted(self.lat)
            s["latency_ms"] = {"mean": round(statistics.fmean(lat), 1),
                               "p95": round(lat[int(0.95 * (len(lat) - 1))], 1),
                               "max": round(lat[-1], 1)}
        g = {c: (max(v) if v else None) for c, v in self.gaps.items()}
        s["gap_max_ms"] = g
        worst = max([v for v in g.values() if v is not None] or [0])
        s["steady"] = bool(worst and worst <= max(200.0, 3000.0 / self.hz))
        return s

    def write_index(self) -> str:
        if not self.enabled:
            return ""
        p = os.path.join(self.dir, "index.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"rows": self.manifest, "summary": self.summary(self._dur or 1.0)},
                      f, ensure_ascii=False)
        return p


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
        fr = {"i": k, "t": round(r["t"] - t0, 4),
              "j": [round(v, 6) for v in r["j"]],
              "p": [round(v, 6) for v in _p],
              "rpy": [round(v, 6) for v in (r.get("rpy") or [0, 0, 0])]}
        if r.get("img"):
            fr["img"] = r["img"]                # {cam: 相对路径} —— 与状态同一 tick 采的
        frames.append(fr)
    data = {"n_frames": len(frames), "dur_s": round(frames[-1]["t"], 3),
            "src": os.path.basename(jsonl_path), "frames": frames}
    idx = os.path.join(os.path.dirname(jsonl_path), "frames")
    # 找与 JSONL 同批的帧目录 (frames_<ts>), 把 index.json 的 sync 摘要带上
    cand = None
    for d in sorted(os.listdir(os.path.dirname(jsonl_path) or ".")):
        if d.startswith("frames_") and os.path.isfile(os.path.join(os.path.dirname(jsonl_path), d, "index.json")):
            cand = os.path.join(os.path.dirname(jsonl_path), d)
    if cand:
        try:
            jj = json.load(open(os.path.join(cand, "index.json"), encoding="utf-8"))
            data["sync"] = jj.get("summary", {})
            data["frames_dir"] = os.path.basename(cand)
        except Exception:                                                # noqa: BLE001
            pass
    else:
        for fr in frames:                    # 旧口径 JSONL: 无图像, 显式标出来
            fr.setdefault("img", None)
        data["sync"] = {"enabled": False, "note": "本批无同步图像 (旧口径录制)"}
    del idx
    dst = jsonl_path.replace(".jsonl", ".json")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return dst


def probe_camera(n: int = 8) -> int:
    """不连机器人, 只验相机链路: 抓 n 帧/相机, 报延迟与字节。"""
    tap = CamTap(CAM_SEL, CAM_HZ, os.path.join(OUTDIR, "probe_%s" % time.strftime("%Y%m%d_%H%M%S")))
    tap._dur = 0.0
    t0 = time.monotonic()
    tap.start()
    while min(tap.idx.values() or [n]) < n and time.monotonic() - t0 < 20:
        time.sleep(0.05)
    tap._dur = max(time.monotonic() - t0, 0.001)
    tap.stop()
    got = dict(tap.idx)
    idxp = tap.write_index()
    out(ok=all(v >= n for v in got.values()), step="probe_camera", got=got,
        index=idxp, summary=tap.summary(tap._dur))
    return 0 if all(v >= n for v in got.values()) else 2


def main() -> int:
    global CAM_SEL, CAM_HZ
    argv = sys.argv[1:]

    def opt(name, default):
        if name in argv:
            i = argv.index(name)
            if i + 1 < len(argv):
                return argv[i + 1]
            return ""
        return default

    if "--convert" in argv:
        d = convert(opt("--convert", ""))
        out(ok=bool(d), json=d)
        return 0 if d else 2
    if "--probe-camera" in argv:
        return probe_camera(int(opt("--probe-n", "8") or 8))

    CAM_SEL = opt("--cam", CAM_SEL)
    CAM_HZ = float(opt("--cam-hz", str(CAM_HZ)) or CAM_HZ)
    secs = float(opt("--secs", str(SECS)) or 0.0)
    rate = float(opt("--rate", str(RATE)) or 30.0)

    import xcoresdk_python as x  # noqa: E402

    os.makedirs(OUTDIR, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(OUTDIR, "rec_manual_%s.jsonl" % ts)
    fdir = os.path.join(OUTDIR, "frames_%s" % ts)
    tap = CamTap(CAM_SEL, CAM_HZ, fdir)

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

    dt = 1.0 / max(1.0, rate)
    t0 = time.monotonic()
    n = 0
    f = open(path, "w", encoding="utf-8")
    out(ok=True, step="recording", file=path, rate=rate, secs=secs,
        cam=CAM_SEL, cam_hz=CAM_HZ, frames_dir=(fdir if tap.enabled else ""),
        power=str(r.powerState({})), note="只读记录(状态+图像), 不发任何运动指令")
    tap.start()
    last_err = None
    while not _stop["flag"]:
        if secs > 0 and time.monotonic() - t0 >= secs:
            break
        t = time.monotonic()
        try:
            j = joints(r)
            p, rpy = posture(r, x)
        except Exception as e:                                           # noqa: BLE001
            last_err = "%s: %s" % (type(e).__name__, e)
            time.sleep(0.2)
            continue
        imgs, ages = tap.bind(t)                        # 该状态时刻之前最近一帧 (解耦线程)

        rec = {"t": round(t, 4), "j": [round(v, 6) for v in j],
               "p": [round(v, 3) for v in p],
               "rpy": [round(v, 5) for v in rpy]}
        if imgs:
            rec["img"] = imgs
            rec["img_age_ms"] = ages
        f.write(json.dumps(rec) + "\n")
        n += 1
        if n % int(max(1, rate * 10)) == 0:
            out(step="tick", n=n, t_s=round(t - t0, 1),
                j_deg=[round(math.degrees(v), 2) for v in j],
                tcp=[round(v, 1) for v in p],
                frames={c: tap.idx[c] for c in tap.names})
        sl = dt - (time.monotonic() - t)
        if sl > 0:
            time.sleep(sl)
    f.close()
    dur = time.monotonic() - t0
    tap._dur = dur
    tap.stop()
    idxp = tap.write_index()
    dst = convert(path)
    out(ok=True, step="done", n=n, dur_s=round(dur, 2), jsonl=path, json=dst,
        frames_index=idxp, sync=tap.summary(dur), err=last_err or "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
