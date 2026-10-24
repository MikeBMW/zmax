#!/usr/bin/env python3
"""USB 摄像头 → HTTP 单帧服务 (Intel 工控机, 默认 :8812)

用途: 给远程 (4060 工位总览页「中央相机」) 提供这台机器上 USB2.0 UVC 相机的画面。
口径:
  · 相机**单进程独占**, 内部一个线程连续读, 只保留最新一帧 (不排队、不抖)
  · `/snap.jpg` 返回最新 JPEG, 并带 `X-Frame-Age-S`(源端自报帧龄) —— 远程页面据此算真实延迟,
    不是"取回来的那一刻"
  · 相机读挂了不返回旧帧冒充新鲜: 超过 STALE_S 就回 503 + 明确原因
  · MJPG 优先 (640x480 MJPG 比 YUYV 省 CPU); 不支持时回退默认格式
用法:
  python3 usb_cam_http.py [--dev 0] [--port 8812] [--w 640] [--h 480] [--fps 10] [--quality 80]
"""
import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2

LATEST = {"jpg": b"", "ts": 0.0, "w": 0, "h": 0, "fourcc": "", "ok": False, "err": "", "frames": 0}
LOCK = threading.Lock()
STOP = threading.Event()


def cam_loop(dev: int, w: int, h: int, fps: float, quality: int) -> None:
    """独占相机, 连续读, 只留最新一帧。"""
    params = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
    while not STOP.is_set():
        cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
        if not cap.isOpened():
            cap = cv2.VideoCapture(dev)
            with LOCK:
                LATEST.update(ok=False, err="相机打不开 /dev/video%d" % dev)
            STOP.wait(2.0)
            continue
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
        try:
            cap.set(cv2.CAP_PROP_FPS, fps)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        fourcc = int(cap.get(cv2.CAP_PROP_FOURCC) or 0)
        fc = "".join(chr((fourcc >> (8 * i)) & 0xFF) for i in range(4)) if fourcc else "?"
        with LOCK:
            LATEST.update(ok=True, err="", fourcc=fc,
                          w=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0),
                          h=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0))
        print("[cam] 打开 /dev/video%d  %dx%d fourcc=%s 目标 %.1ffps"
              % (dev, LATEST["w"], LATEST["h"], fc, fps), flush=True)
        miss = 0
        while not STOP.is_set():
            t0 = time.time()
            ok, frame = cap.read()
            if not ok or frame is None:
                miss += 1
                if miss % 30 == 1:
                    with LOCK:
                        LATEST.update(ok=False, err="读帧失败 x%d" % miss)
                    print("[cam] 读帧失败 x%d" % miss, flush=True)
                STOP.wait(0.2)
                continue
            miss = 0
            ok2, buf = cv2.imencode(".jpg", frame, params)
            with LOCK:
                if ok2:
                    LATEST.update(jpg=buf.tobytes(), ts=time.time(), ok=True, err="",
                                  w=frame.shape[1], h=frame.shape[0],
                                  frames=LATEST["frames"] + 1)
            dt = time.time() - t0
            if fps > 0 and dt < 1.0 / fps:
                STOP.wait(1.0 / fps - dt)
        cap.release()


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    STALE_S = 3.0

    def log_message(self, *a):
        pass

    def _send(self, code, ctype, body, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Access-Control-Allow-Origin", "*")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def do_GET(self):
        p = self.path.split("?")[0].rstrip("/") or "/"
        with LOCK:
            jpg, ts, ok, err = LATEST["jpg"], LATEST["ts"], LATEST["ok"], LATEST["err"]
            w, h, fc, frames = LATEST["w"], LATEST["h"], LATEST["fourcc"], LATEST["frames"]
        age = (time.time() - ts) if ts else -1.0
        if p in ("/snap.jpg", "/snapshot", "/frame.jpg", "/"):
            if not jpg or not ok or age > self.STALE_S:
                body = json.dumps({"ok": False, "reason": err or "无新鲜帧",
                                   "age_s": round(age, 3)}, ensure_ascii=False).encode()
                self._send(503, "application/json; charset=utf-8", body,
                           {"X-Frame-Age-S": "%.3f" % age})
                return
            self._send(200, "image/jpeg", jpg,
                       {"X-Frame-Age-S": "%.3f" % age,
                        "X-Frame-Source": "usb-cam-intel"})
            return
        if p == "/health":
            body = json.dumps({"ok": bool(jpg) and ok, "w": w, "h": h, "fourcc": fc,
                               "frames": frames, "age_s": round(age, 3),
                               "stale_s": self.STALE_S, "err": err,
                               "uptime_s": round(time.time() - T0, 1)},
                              ensure_ascii=False).encode()
            self._send(200 if body else 500, "application/json; charset=utf-8", body)
            return
        self._send(404, "text/plain; charset=utf-8", b"GET /snap.jpg | /health")


T0 = time.time()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev", type=int, default=0)
    ap.add_argument("--port", type=int, default=8812)
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--w", type=int, default=640)
    ap.add_argument("--h", type=int, default=480)
    ap.add_argument("--fps", type=float, default=10.0)
    ap.add_argument("--quality", type=int, default=80)
    a = ap.parse_args()
    threading.Thread(target=cam_loop, args=(a.dev, a.w, a.h, a.fps, a.quality),
                     daemon=True, name="cam").start()
    srv = ThreadingHTTPServer((a.bind, a.port), H)
    srv.daemon_threads = True
    print("[usb-cam-http] http://%s:%d/snap.jpg  (/dev/video%d)" % (a.bind, a.port, a.dev),
          flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        STOP.set()


if __name__ == "__main__":
    main()
