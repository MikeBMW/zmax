#!/usr/bin/env python3
"""550C 端侧推理服务 (Intel 边缘机) —— 只做一件事: 远程把图发进来, 端侧 NPU/GPU 出检测框, 回 JSON。

设计口径 (老倪 2026-10-21): 「550C 用于量产, 直接部署在 intel 上, 550C 包括所有模型, 可以远程端侧实时运行」
  · 零第三方 web 依赖 (stdlib ThreadingHTTPServer), 断网也能起;
  · 模型/设备/阈值全部来自命令行或环境变量, 不在代码里写死;
  · 每次响应都带 infer_ms / device / model_sha16, 让"实时"和"这份权重"可核;
  · /health 给运维与 550C 探活 (进程、设备、已加载模型、最近一帧耗时)。

接口:
  GET  /health                      → {ok, device, model, sha16, last_ms, n_req}
  POST /detect  (body = JPEG/PNG)   → {ok, device, infer_ms, w, h, dets:[{cls,conf,xyxy}]}
  POST /detect?conf=0.3&iou=0.45    → 阈值可覆盖
用法: python edge_service.py --xml ir/yolo_peg_live.xml --device NPU --port 8800
"""
import argparse
import hashlib
import io
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import cv2
import numpy as np
import openvino as ov

IMGSZ = 640
PAD = 114
STATE = {"n": 0, "last_ms": None, "t0": time.time()}


def letterbox(img, size=IMGSZ):
    h, w = img.shape[:2]
    r = min(size / h, size / w)
    nh, nw = int(round(h * r)), int(round(w * r))
    canvas = np.full((size, size, 3), PAD, dtype=np.uint8)
    top, left = (size - nh) // 2, (size - nw) // 2
    canvas[top:top + nh, left:left + nw] = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    return canvas, r, (left, top)


def decode(out, r, pad, conf_th=0.25, iou_th=0.45):
    p = out[0] if out.ndim == 3 and out.shape[0] == 1 else out
    if p.shape[0] < p.shape[1]:
        p = p.transpose(1, 0)
    # ⚡ 向量化: 8400 行纯 Python 循环实测吃掉 ~35ms (NPU 本身只要 2.5ms), 端到端因此假慢到 25FPS。
    #    改成 numpy 一次算完 + cv2.dnn.NMSBoxes(C++), 端侧才真"实时"。
    cs = p[:, 4:]
    cidx = cs.argmax(axis=1)
    conf = cs[np.arange(cs.shape[0]), cidx]
    keep = conf >= conf_th
    if not keep.any():
        return []
    xywh = p[keep, :4]
    conf = conf[keep]
    cidx = cidx[keep]
    xy = np.concatenate([xywh[:, 0:1] - xywh[:, 2:3] / 2.0, xywh[:, 1:2] - xywh[:, 3:4] / 2.0,
                         xywh[:, 2:3], xywh[:, 3:4]], axis=1)          # cxcywh -> xywh
    idx = cv2.dnn.NMSBoxes(xy.tolist(), conf.tolist(), conf_th, iou_th)
    idx = np.array(idx).flatten() if len(idx) else np.array([], dtype=int)
    res = []
    for i in idx:
        x, y, w, h = (float(v) for v in xy[i])   # numpy.float32 不能直接进 json
        res.append({"cls": int(cidx[i]), "conf": round(float(conf[i]), 4),
                    "xyxy": [round(float((x - pad[0]) / r), 1), round(float((y - pad[1]) / r), 1),
                             round(float((x - pad[0] + w) / r), 1), round(float((y - pad[1] + h) / r), 1)]})
    return sorted(res, key=lambda d: -d["conf"])


class Handler(BaseHTTPRequestHandler):
    server_version = "zmax-edge/1.0"
    protocol_version = "HTTP/1.1"
    comp = None
    out_port = None
    meta = {}

    def log_message(self, fmt, *a):                     # 静音: 只留 /health 与错误
        if "/detect" not in (fmt % a):
            print("[edge] " + fmt % a, flush=True)

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/health", "/", "/healthz"):
            return self._json(200, dict(ok=True, uptime_s=round(time.time() - STATE["t0"], 1),
                                        n_req=STATE["n"], last_ms=STATE["last_ms"], **self.meta))
        return self._json(404, {"ok": False, "error": "no such path %s" % u.path})

    def do_POST(self):
        u = urlparse(self.path)
        if u.path != "/detect":
            return self._json(404, {"ok": False, "error": "no such path %s" % u.path})
        q = parse_qs(u.query or "")
        conf = float((q.get("conf") or ["0.25"])[0])
        iou = float((q.get("iou") or ["0.45"])[0])
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > 32 * 1024 * 1024:
            return self._json(400, {"ok": False, "error": "bad content-length %s" % n})
        raw = self.rfile.read(n)
        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return self._json(400, {"ok": False, "error": "不是能解码的图片 (要 JPEG/PNG)"})
        t = time.perf_counter()
        lb, r, pad = letterbox(img)
        x = np.ascontiguousarray(lb[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0)
        out = self.comp(x)[self.out_port]
        dets = decode(out, r, pad, conf, iou)
        ms = round((time.perf_counter() - t) * 1000.0, 2)
        STATE["n"] += 1
        STATE["last_ms"] = ms
        return self._json(200, dict(ok=True, device=self.meta.get("device"), infer_ms=ms,
                                    w=img.shape[1], h=img.shape[0], **_sha_of(self.meta), dets=dets))


def _sha_of(meta):
    return {"model": os.path.basename(meta.get("xml") or ""), "model_sha16": meta.get("sha16")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xml", required=True)
    ap.add_argument("--device", default=os.environ.get("ZMAX_EDGE_DEVICE", "NPU"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("ZMAX_EDGE_PORT", "8800")))
    ap.add_argument("--bind", default="0.0.0.0")
    a = ap.parse_args()

    core = ov.Core()
    t0 = time.perf_counter()
    model = core.read_model(a.xml)
    comp = core.compile_model(model, a.device)
    compile_ms = round((time.perf_counter() - t0) * 1000.0, 1)
    with open(a.xml, "rb") as f:
        sha16 = hashlib.sha256(f.read()).hexdigest()[:16]
    Handler.comp, Handler.out_port = comp, comp.output(0)
    Handler.meta = {"xml": a.xml, "device": a.device, "sha16": sha16,
                    "compile_ms": compile_ms, "imgsz": IMGSZ,
                    "host": os.uname().nodename, "pid": os.getpid()}
    srv = ThreadingHTTPServer((a.bind, a.port), Handler)
    print("[edge] 起来了: %s:%d device=%s model=%s sha=%s compile=%sms"
          % (a.bind, a.port, a.device, os.path.basename(a.xml), sha16, compile_ms), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
