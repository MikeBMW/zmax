#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""collect_live_dataset.py — 真机运行时长记「图像 + 状态真值」, 攒训练数据。

一帧 = 1 张真实相机 JPEG + 1 行状态真值 (pose 7 + joints 6), 按帧号命名, 可直接
导成 lerobot 数据集。只读, 不下发任何指令。

静止帧默认**不入库** (机械臂不动时采到的全是同一张图同一个点, 拿它训练等于复制粘贴)。

用法:
  ./gui-venv311/bin/python tools/collect_live_dataset.py --secs 1800 --hz 6
  ./gui-venv311/bin/python tools/collect_live_dataset.py --secs 60 --cam local --keep-still   # 调试
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request

ROOT = "/home/ubuntu/zmax"
CAMS = {"local": "http://127.0.0.1:8791/snapshot/local.jpg",
        "arm": "http://127.0.0.1:8791/snapshot/arm.jpg",
        "overlay_local": "http://127.0.0.1:8791/snapshot/overlay_local.jpg"}
TRUTH = "http://127.0.0.1:8797/api/tcp"


def _get(url, timeout=3):
    return urllib.request.urlopen(url, timeout=timeout).read()


# ── 低延迟取帧: 读 MJPEG 流一直收, 主循环只取"最新一帧" ─────────────────────
#   为什么不用 /snapshot/*.jpg: 每次请求要等服务端生成新帧, 实测 2.0s/张 ⇒ 只有 0.5Hz,
#   一圈 290s 只能拿 145 帧。MJPEG 是服务端持续推最新帧(旧帧丢弃), 取一帧 ≈ 0ms。
class MjpegReader:
    def __init__(self, url, quit_on_timeout=8.0):
        import threading
        self.url, self.latest, self.n, self.err = url, None, 0, None
        self._stop = False
        self._t = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._t.start(); return self

    def _run(self):
        import time as _t
        while not self._stop:
            try:
                r = urllib.request.urlopen(self.url, timeout=10)
                buf = b""
                while not self._stop:
                    chunk = r.read(4096)
                    if not chunk:
                        break
                    buf += chunk
                    s = buf.find(b"\xff\xd8"); e = buf.find(b"\xff\xd9", s + 2)
                    if s >= 0 and e > s:
                        self.latest = buf[s:e + 2]; self.n += 1; buf = buf[e + 2:]
                    elif len(buf) > 4_000_000:
                        buf = buf[-1_000_000:]
            except Exception as ex:                                        # noqa: BLE001
                self.err = "%s: %s" % (type(ex).__name__, ex)
                _t.sleep(1.0)

    def frame(self):
        return self.latest

    def stop(self):
        self._stop = True


def _snap(url, timeout=3):
    return urllib.request.urlopen(url, timeout=timeout).read()


def quat_to_rpy(q):
    import math
    x, y, z, w = q
    rx = math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
    ry = math.asin(max(-1.0, min(1.0, 2 * (w * y - z * x))))
    rz = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    return [rx, ry, rz]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--secs", type=int, default=1800)
    ap.add_argument("--hz", type=float, default=6.0)
    ap.add_argument("--cam", default="arm", choices=list(CAMS))
    ap.add_argument("--out", default=os.path.join(ROOT, "zmax_data/live_ds/episode_000000"))
    ap.add_argument("--min-move", type=float, default=0.5, dest="min_move",
                    help="位移 mm + 50×转角 rad 低于此值视为静止, 不入库")
    ap.add_argument("--keep-still", action="store_true")
    ap.add_argument("--stream", default="http://127.0.0.1:8791/arm.mjpg",
                    help="MJPEG 流地址; 传空字符串则回退 /snapshot 取图")
    a = ap.parse_args()

    MR = MjpegReader(a.stream).start() if a.stream else None
    if MR is not None:
        print(json.dumps({"stream": a.stream, "note": "MJPEG 直取最新帧"}, ensure_ascii=False), flush=True)
    img_dir = os.path.join(a.out, "images/observation.images.top")
    os.makedirs(img_dir, exist_ok=True)
    meta = os.path.join(a.out, "data"); os.makedirs(meta, exist_ok=True)
    jl = os.path.join(meta, "frames.jsonl")
    t0, n, still, bad, last = time.time(), 0, 0, 0, None
    period = 1.0 / max(a.hz, 0.5)
    print(json.dumps({"start": time.strftime("%F %T"), "cam": a.cam, "hz": a.hz,
                      "out": a.out, "note": "臂一动就自动入库"}, ensure_ascii=False), flush=True)
    with open(jl, "a") as f:
        while time.time() - t0 < a.secs:
            ts = time.time()
            try:
                d = json.loads(_get(TRUTH).decode())
                if d.get("stale") or (d.get("age_s") or 9) > 1.5:
                    bad += 1; time.sleep(period); continue
                p = [d["x"] * 1000, d["y"] * 1000, d["z"] * 1000]
                rpy = quat_to_rpy(d["quat"]) if d.get("quat") else [0, 0, 0]
                mv = 9e9 if last is None else (abs(p[0]-last[0]) + abs(p[1]-last[1]) + abs(p[2]-last[2])
                                               + 50 * sum(abs(rpy[k]-last[3][k]) for k in range(3)))
                if mv < a.min_move and not a.keep_still:
                    still += 1; time.sleep(period); continue
                jpg = (MR.frame() if MR is not None else None) or _get(CAMS[a.cam])
                if len(jpg) < 2000:
                    bad += 1; time.sleep(period); continue
                fn = "frame_%06d.jpg" % n
                with open(os.path.join(img_dir, fn), "wb") as g:
                    g.write(jpg)
                rec = {"i": n, "ts": round(ts, 3), "img": "images/observation.images.top/" + fn,
                       "pose7": [round(v, 4) for v in p + rpy] + [1.0],
                       "joints_deg": [round(v, 4) for v in (d.get("joints") or [])],
                       "src": "8797 /api/tcp + %s" % a.cam}
                f.write(json.dumps(rec, ensure_ascii=False) + "\n"); f.flush()  # 不 flush 会被缓冲, 进程一挂元数据全丢
                last = (p[0], p[1], p[2], rpy)
                n += 1
            except Exception as e:                                        # noqa: BLE001
                bad += 1
            time.sleep(max(0.0, period - (time.time() - ts)))
    print(json.dumps({"ok": True, "frames": n, "still_skipped": still, "bad": bad,
                      "out": a.out, "elapsed_s": round(time.time() - t0, 1)}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
