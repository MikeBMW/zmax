#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""usb_cam_live.py — 本机 USB 上的 RealSense(D435) 实时预览 (彩色 + 深度)

背景 (2026-10-13 老倪): 「笔记本，现在的 USB 接的是 realsense 相机，你可以显示，用 USB 通道」
口径: **走 USB 直读(V4L2)**, 不依赖 librealsense/pyrealsense2(本机没装), 也不动 8791 那套在线推流服务
(它按卡名 \"USB2.0 Camera\" 找 USB 相机 ⇒ 匹配不到 RealSense, 且改它要重启=打断用户在看的东西)。

设备 (本机实测):
  · 彩色 /dev/video10  YUYV 640x480@30   (D435 的 RGB 节点)
  · 深度 /dev/video6   Z16  640x480      (raw 深度; 不是 millimeter —— 换算要靠 librealsense 标定,
                                          这里只做**可视化**(近亮远暗), 不当尺度用)
  · 红外 /dev/video8   GREY
取流用 ffmpeg 管道(rawvideo): 实测 v4l2-ctl/ffmpeg 都能出流, 而 OpenCV 按 index 无法打开这两个节点。

页面: http://<本机IP>:8788/  · 端点: /color.jpg /depth.jpg /color.mjpg /depth.mjpg /health /snap
用法: python3 tools/usb_cam_live.py [--port 8788] [--color /dev/video10] [--depth /dev/video6] [--no-depth]
"""
from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
FFMPEG = os.environ.get("ZMAX_FFMPEG") or "/home/ubuntu/.hermes/tools/ffmpeg-9.0.1-linux-x64/bin/ffmpeg"
ST = {"color": b"", "depth": b"", "t_color": 0.0, "t_depth": 0.0,
      "n_color": 0, "n_depth": 0, "err": "", "fps": 0.0}
LOCK = threading.Lock()
RUN = True


def _pump(kind: str, dev: str, w: int, h: int, fmt: str, fps: int, colorize: bool):
    """一个设备一个 ffmpeg 管道 → 最新一帧 JPEG 放 ST[kind]。断了自动重连。"""
    global RUN
    import numpy as np
    import cv2
    while RUN:
        cmd = [FFMPEG, "-loglevel", "error", "-f", "v4l2", "-input_format", fmt,
               "-video_size", "%dx%d" % (w, h), "-framerate", str(fps), "-i", dev,
               "-f", "rawvideo", "-pix_fmt", ("gray16le" if colorize else "bgr24"), "-"]
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10 ** 7)
        except Exception as e:                                              # noqa: BLE001
            with LOCK:
                ST["err"] = "%s: 起 ffmpeg 失败 %s" % (kind, e)
            time.sleep(3)
            continue
        npx = 1 if colorize else 3
        nbytes = w * h * 2 if colorize else w * h * 3
        t0 = time.time()
        while RUN:
            buf = p.stdout.read(nbytes)
            if not buf or len(buf) < nbytes:
                break
            arr = np.frombuffer(buf, dtype=np.uint16 if colorize else np.uint8)
            if colorize:
                d = arr.reshape(h, w)
                # 近亮远暗: 取 2%~98% 分位做归一(量程随场景自动跟)
                lo, hi = np.percentile(d, 2), np.percentile(d, 98)
                g = np.clip((d.astype("float32") - lo) / max(hi - lo, 1.0), 0, 1) * 255.0
                img = cv2.applyColorMap(255 - g.astype("uint8"), cv2.COLORMAP_TURBO)   # 近=亮(红)
            else:
                img = arr.reshape(h, w, 3)
            ok, jb = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
            if ok:
                with LOCK:
                    ST[kind] = jb.tobytes()
                    ST["t_" + kind] = time.time()
                    ST["n_" + kind] += 1
                    ST["fps"] = round(ST["n_color"] and (ST["n_color"] / max(time.time() - t0, 1e-6)), 1) if kind == "color" else ST["fps"]
        p.terminate()
        with LOCK:
            if not ST["err"]:
                ST["err"] = "%s: 流断了(设备被拔/被占?) 3s 后重连" % kind
        time.sleep(3)


PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>USB RealSense 实时</title><style>
body{margin:0;background:#0d1117;color:#c9d1d9;font:13px/1.5 -apple-system,Segoe UI,sans-serif}
.h{padding:8px 12px;background:#161b22;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
img{width:100%%;display:block;background:#000}
.g{display:grid;grid-template-columns:1fr 1fr;gap:2px}@media(max-width:760px){.g{grid-template-columns:1fr}}
.b{padding:2px 8px;border-radius:6px;background:#21262d}
button{background:#238636;border:0;color:#fff;padding:6px 12px;border-radius:6px;font-size:13px}
a{color:#58a6ff}
</style>
<div class=h><b>🔌 USB RealSense D435 实时(走 USB 直读)</b>
<span class=b id=s>加载中…</span>
<button onclick="location.href='/snap'">⬇ 存两张图</button>
<span class=b><a href="/color.jpg" target=_blank>彩色单帧</a></span>
<span class=b><a href="/depth.jpg" target=_blank>深度单帧</a></span></div>
<div class=g><div><img id=c src="/color.mjpg"><div style="padding:4px 10px;color:#8b949e">彩色 YUYV 640x480 (/dev/video10)</div></div>
<div><img id=d src="/depth.mjpg"><div style="padding:4px 10px;color:#8b949e">深度 Z16 raw (近=红/亮, 仅可视化·非毫米)</div></div></div>
<script>setInterval(async()=>{try{const j=await (await fetch('/health')).json();
document.getElementById('s').textContent=`彩色 ${j.fps} fps · 帧龄 ${j.age_color}s · 深度帧龄 ${j.age_depth}s${j.err?' · ⚠ '+j.err:''}`}catch(e){}},1000)</script>
"""


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):        # 静音
        pass

    def _send(self, code, ct, body, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _mj(self, kind):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        last, t0, n = None, time.time(), 0
        while RUN:
            with LOCK:
                b = ST[kind]
            if b and b is not last:
                last = b
                try:
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(b))
                    self.wfile.write(b)
                    self.wfile.write(b"\r\n")
                except (BrokenPipeError, ConnectionResetError):
                    return
                n += 1
                fps = n / max(time.time() - t0, 1e-6)
                if fps > 30:
                    time.sleep(0.033)
            else:
                time.sleep(0.01)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p in ("/", "/index.html"):
            return self._send(200, "text/html; charset=utf-8", PAGE.encode())
        if p == "/health":
            with LOCK:
                now = time.time()
                d = {"fps": ST["fps"], "err": ST["err"],
                     "age_color": round(now - ST["t_color"], 2) if ST["t_color"] else None,
                     "age_depth": round(now - ST["t_depth"], 2) if ST["t_depth"] else None,
                     "n_color": ST["n_color"], "n_depth": ST["n_depth"]}
            return self._send(200, "application/json", json.dumps(d, ensure_ascii=False).encode())
        if p in ("/color.jpg", "/depth.jpg"):
            k = "color" if "color" in p else "depth"
            with LOCK:
                b = ST[k]
            if not b:
                return self._send(503, "text/plain; charset=utf-8", b"no frame yet")
            return self._send(200, "image/jpeg", b)
        if p in ("/color.mjpg", "/depth.mjpg"):
            return self._mj("color" if "color" in p else "depth")
        if p == "/snap":
            ts = time.strftime("%H%M%S")
            out = "/home/ubuntu/zmax/zmax_data/usb_snap_%s.jpg" % ts
            with LOCK:
                cb, db = ST["color"], ST["depth"]
            try:
                open(out, "wb").write(cb)
                dep = out.replace("usb_snap", "usb_snap_depth")
                open(dep, "wb").write(db)
            except OSError as e:
                return self._send(500, "text/plain", str(e).encode())
            return self._send(200, "text/plain; charset=utf-8",
                              ("已存:\n%s\n%s\n" % (out, dep)).encode())
        return self._send(404, "text/plain", b"404")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8788)
    ap.add_argument("--color", default="/dev/video10")
    ap.add_argument("--depth", default="/dev/video6")
    ap.add_argument("--w", type=int, default=640)
    ap.add_argument("--h", type=int, default=480)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--no-depth", action="store_true")
    a = ap.parse_args()
    th = [threading.Thread(target=_pump, args=("color", a.color, a.w, a.h, "yuyv422", a.fps, False), daemon=True)]
    if not a.no_depth:
        th.append(threading.Thread(target=_pump, args=("depth", a.depth, a.w, a.h, "gray16le", a.fps, True), daemon=True))
    for t in th:
        t.start()
    for _ in range(200):                       # 等第一帧
        with LOCK:
            if ST["color"]:
                break
        time.sleep(0.1)
    srv = ThreadingHTTPServer(("0.0.0.0", a.port), H)
    print("USB RealSense 预览: http://0.0.0.0:%d/  · 彩色 %s · 深度 %s" % (a.port, a.color, a.depth), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
