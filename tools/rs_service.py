#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rs_service.py — USB RealSense D435 独占小服务 (127.0.0.1:8796, 单进程 · 线程模型)

为什么要有它 (2026-10-20 现场事故的根因):
  `tools/tcp_ar_server.py` 是 **ForkingMixIn**(每连接 fork 一个子进程)。pyrealsense 的 pipeline
  活在进程里, fork 出来的子进程**继承的是一个已经失去取帧线程的空壳**(`_ST` 是 copy-on-write 的
  老快照) ⇒ 表现:`/api/rs_info` 有内参、`frames=0`、`/snap/rs.jpg` 200 但 **0 字节**;
  多个子进程轮流开设备还会互相抢 UVC ⇒ `xioctl(VIDIOC_S_FMT) failed, errno=16 Device or resource busy`。
  再加上 8791 相机流服务(CV2)如果按卡名把 RealSense 也扫进去, 设备就被两个进程分着抢, dmesg 满屏
  `uvcvideo Non-zero status (-71)` —— 现场看到的就是「USB RealSense 不好使了」。

解法: 让**唯一一个进程**拥有 D435(本服务), 其它窗口/页面一律经 HTTP 读它。
  · 单进程 + 每请求一线程 ⇒ pipeline 的取帧线程常驻, 不会 fork 掉;
  · 设备只被一个人开 ⇒ 不会 EBUSY / -71 抢带宽;
  · 出错时**如实报 err**, 不拿旧帧冒充(帧龄一起给)。

用法:
  ./gui-venv311/bin/python tools/rs_service.py --port 8796          # 前台
  bash tools/rs_service.sh start                                    # 常驻
端点:
  GET /api/info  /api/options  /api/exposure?auto=&exposure=&gain=
  GET /api/pose?det=1&roi=x1,y1,x2,y2   /api/detect?conf=0.25&imgsz=640
  GET /api/point?u=&v=                  /snap.jpg      /rs.mjpg
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "gui"))

import numpy as np                                                   # noqa: E402

import realsense_source as RS                                        # noqa: E402


def _jpeg(frame, quality=82):
    if frame is None:
        return b""
    try:
        import cv2
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        return buf.tobytes() if ok else b""
    except Exception:                                                # noqa: BLE001
        return b""


def _options():
    try:
        d = RS.options()
        if d.get("ok"):
            flt = [o["name"] for s in d["sensors"] for o in s["options"]]
            d["has_ae_roi"] = [n for n in flt if "roi" in n.lower()]
            d["has_ae_priority"] = [n for n in flt if "priority" in n.lower()]
        return d
    except Exception as e:                                           # noqa: BLE001
        return {"ok": False, "err": "%s: %s" % (type(e).__name__, str(e)[:140])}


def _exposure(auto=None, exposure_us=None, gain=None):
    try:
        return RS.color_ctl(auto=auto, exposure_us=exposure_us, gain=gain)
    except Exception as e:                                           # noqa: BLE001
        return {"ok": False, "err": "%s: %s" % (type(e).__name__, str(e)[:140])}


def _pose(roi=None, use_last_detect=True):
    try:
        import ar_calib_module as ACM
        return ACM.pose(roi=roi, use_last_detect=use_last_detect)
    except Exception as e:                                           # noqa: BLE001
        return {"ok": False, "err": "%s: %s" % (type(e).__name__, str(e)[:160])}


def _detect(conf=0.25, imgsz=640):
    try:
        import ar_calib_module as ACM
        return ACM.detect(conf=conf, imgsz=imgsz)
    except SystemExit as e:
        return {"ok": False, "err": str(e)}
    except Exception as e:                                           # noqa: BLE001
        return {"ok": False, "err": "%s: %s" % (type(e).__name__, str(e)[:160])}


# ── D435 专用检测头 (2026-10-20 老倪选 B: 「单独给 D435 视角训一个检测头…只能给 2D 框」) ──
# 现役 models/yolo_peg_live.pt 是在**腕相机 D405** 视角/尺度上训的, 在 D435 上基本检不出
# (实测 conf=0.25 全帧 0 个; 降到 0.15 才冒出疑似框 + 台面静止杂物误检)。
# 这里跑的 `models/yolo_peg_d435.pt` 是用 D435 实拍帧单独训的 1 类(peg)小头, 只给 2D 框,
# 不做 3D/不碰 tool1 —— 那两样要 D435 的外参(未标定)。
_DET435 = {"m": None, "path": None, "res": None, "t": 0.0}


def _det435(conf=0.25, imgsz=416):
    p = os.path.join(os.path.dirname(HERE), "models", "yolo_peg_d435.pt")
    if not os.path.exists(p):
        return {"ok": False, "err": "没有 D435 检测权重: %s (先跑 tools/peg_d435_train.py)" % p}
    try:
        if _DET435["m"] is None or _DET435["path"] != p:
            from ultralytics import YOLO
            _DET435.update({"m": YOLO(p), "path": p, "res": None, "t": 0.0})
        now = time.time()
        if _DET435["res"] and now - _DET435["t"] < 0.2:              # 200ms 内复用(页面会轮询)
            return _DET435["res"]
        fr = RS.snap()
        if fr is None:
            L = RS.latest()
            return {"ok": False, "err": "此刻没有新帧", "age_s": L.get("age_s"), "n": L.get("n")}
        t0 = time.time()
        r = _DET435["m"].predict(fr, conf=conf, imgsz=imgsz, device="cpu", verbose=False)[0]
        boxes = []
        for b in r.boxes:
            x1, y1, x2, y2 = [float(v) for v in b.xyxy[0]]
            boxes.append({"xyxy": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
                          "conf": round(float(b.conf), 3),
                          "cls": r.names[int(b.cls)]})
        out = {"ok": True, "n": len(boxes), "boxes": boxes,
               "ms": int((time.time() - t0) * 1000),
               "age_s": (RS.latest() or {}).get("age_s"),
               "model": os.path.basename(p), "conf_thr": conf}
        _DET435["res"], _DET435["t"] = out, now
        return out
    except SystemExit as e:
        return {"ok": False, "err": str(e)}
    except Exception as e:                                           # noqa: BLE001
        return {"ok": False, "err": "%s: %s" % (type(e).__name__, str(e)[:160])}


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "zmax-rs/1.0"

    def log_message(self, fmt, *args):                               # 静音: 每帧都打会淹掉宿主的日志
        pass

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, code=200):
        self._send(code, "application/json; charset=utf-8",
                   json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"))

    def do_GET(self):                                                # noqa: N802
        u = urllib.parse.urlparse(self.path)
        p, qs = u.path, urllib.parse.parse_qs(u.query or "")

        def q(name, default=None):
            v = qs.get(name)
            return v[0] if v else default

        if p in ("/api/info", "/api/rs_info"):
            return self._json(RS.info())
        if p == "/api/options":
            return self._json(_options())
        if p == "/api/exposure":
            _a, _e, _g = q("auto"), q("exposure"), q("gain")
            return self._json(_exposure(
                auto=(None if _a is None else (_a not in ("0", "false", "no"))),
                exposure_us=(float(_e) if _e else None),
                gain=(float(_g) if _g else None)))
        if p == "/api/pose":
            roi = None
            if q("roi"):
                try:
                    roi = [int(float(v)) for v in str(q("roi")).split(",")][:4]
                except Exception:                                    # noqa: BLE001
                    roi = None
            return self._json(_pose(roi=roi, use_last_detect=(q("det", "1") != "0")))
        if p == "/api/detect":
            return self._json(_detect(conf=float(q("conf") or 0.25), imgsz=int(q("imgsz") or 640)))
        if p == "/api/detect_d435":                                  # D435 专用 1 类小头(只给 2D 框)
            return self._json(_det435(conf=float(q("conf") or 0.25), imgsz=int(q("imgsz") or 416)))
        if p == "/api/point":
            return self._json(RS.deproject(float(q("u") or 0), float(q("v") or 0)))
        if p in ("/snap.jpg", "/snapshot/rs.jpg", "/snap/rs.jpg"):
            b = _jpeg(RS.snap(), quality=88)
            if not b:
                L = RS.latest()
                return self._json({"ok": False, "err": "D435 此刻没有新帧",
                                   "age_s": L.get("age_s"), "n": L.get("n"),
                                   "detail": L.get("err")}, 503)
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(b)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Zmax-Age-S", "%.3f" % (RS.latest().get("age_s") or -1))
            self.end_headers()
            try:
                self.wfile.write(b)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return None
        if p == "/rs.mjpg":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            t0 = time.time()
            try:
                for part in RS.mjpeg(fps=15, quality=78):
                    if time.time() - t0 > 300:                       # 断链不许永久占线程
                        break
                    self.wfile.write(part)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:                                   # noqa: BLE001
                sys.stderr.write("[rs.mjpg] %s: %s\n" % (type(e).__name__, str(e)[:100]))
            finally:
                self.close_connection = True
            return None
        if p in ("/health", "/"):
            L = RS.latest()
            return self._json({"svc": "zmax-rs", "ok": L.get("color") is not None, "age_s": L.get("age_s"),
                               "n": L.get("n"), "err": L.get("err"),
                               "frames_served_hint": "GET /snap.jpg 取一帧"})
        return self._json({"ok": False, "err": "unknown path", "path": p}, 404)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8789)
    a = ap.parse_args()
    print("[rs] 预热 pipeline …", flush=True)
    t0 = time.time()
    L = RS.latest()                       # 触发 ensure() (幂等)
    print("[rs] 预热 %.2fs · 首帧 age=%s n=%s err=%s" %
          (time.time() - t0, L.get("age_s"), L.get("n"), (L.get("err") or "")[:90]), flush=True)
    srv = ThreadingHTTPServer((a.host, a.port), H)
    srv.daemon_threads = True
    print("[rs] 监听 http://%s:%d  (/api/info /snap.jpg /rs.mjpg …)" % (a.host, a.port), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            getattr(RS, "stop", lambda: None)()      # 模块没导出 stop 就跳过 (别为收尾再抛一次)
        except Exception:                                            # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
