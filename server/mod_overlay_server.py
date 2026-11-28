#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mod_overlay_server.py —— 虚拟光模块长方体实时叠加服务 (:8796)

用途: 当手臂经过金手指/表面检测相机视野时，在画面上能看到"一个光模块"。
      本服务只做可视化叠加，不碰 8791 的采集进程、不下发动作、不改任何真值。

路由:
  GET /mod.jpg?cam=arm          臂相机 + 虚拟光模块长方体(默认)
  GET /mod.jpg?cam=arm&along=-z 换延伸方向
  GET /mod.jpg?cam=arm&real=1   改用 /api/module3d 的真实检测框(有检出时更贴合)
  GET /status                   JSON: 位姿年龄/深度/框范围/来源

设计约束(踩坑结论，见 tools/mod_proj.py docstring):
  · 臂相机装在腕上 ⇒ 光模块在画面上像素固定，不随位姿变 ⇒ 不需要实时位姿
  · 手眼 T_cam2tool 里的 "tool" 就是 tool1，不要再乘 URDF tool0→tool1
  · 纯几何投影比实际模块头偏上 ~130px，用 /api/module_spec 实测的 shift=(-24,+130) 补偿
  · 8797 的 align_shift_px 只在 YOLO 检出时非零，无检出时是 [0,0]，不能当通用修正

⚠️ AOI 相机(aoi_gold/aoi_surface)暂不支持: 它们与 base 的外参没有标定过,
   光模块在它们画面里的位置需要外参才能算 —— 见 /status 的 aoi_ready 字段。
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mod_proj as MP                                                    # noqa: E402

PORT = int(os.environ.get("ZMAX_MOD_PORT", "8796"))
CAM_URL = "http://127.0.0.1:8791/snapshot/%s.jpg"
# module_spec 实测: tool1 几何投影(333,40) → 实际模块头中心(309,170)
SHIFT = (float(os.environ.get("ZMAX_MOD_SHIFT_X", "-24.0")),
         float(os.environ.get("ZMAX_MOD_SHIFT_Y", "130.0")))


def _fetch(url, timeout=8):
    return urllib.request.urlopen(url, timeout=timeout).read()


def _grab(cam):
    return cv2.imdecode(np.frombuffer(_fetch(CAM_URL % cam), np.uint8), cv2.IMREAD_COLOR)


def _real_boxes(cam="arm"):
    """8797 的真实 3D 检测(/api/module3d) —— 有检出时比虚拟框贴合。"""
    try:
        d = json.loads(_fetch(MP.AR_BASE + "/api/module3d", 8).decode())
        if d.get("ok") and d.get("corners_px"):
            return d
    except Exception:                                                    # noqa: BLE001
        pass
    return None


def build(cam="arm", along="+z", offset=0.0, use_real=False):
    img = _grab(cam)
    if img is None:
        raise RuntimeError("取不到相机图: %s" % cam)
    meta = {"cam": cam, "along": along, "offset_mm": offset, "ts": time.time()}

    if use_real:
        d = _real_boxes()
        if d:
            uv = np.array(d["corners_px"], float)
            out, n = MP.draw(img, uv, color=(80, 255, 120))
            cv2.putText(out, "REAL %s %.2f" % (d.get("class", "?"), float(d.get("conf") or 0)),
                        (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (80, 255, 120), 2, cv2.LINE_AA)
            meta.update({"mode": "real", "class": d.get("class"), "conf": d.get("conf"),
                         "dist_mm": d.get("dist_mm"), "edges": n})
            return out, meta

    uv, P_cam, _ = MP.project(None, along, offset, shift=SHIFT)
    out, n = MP.draw(img, uv)
    ok = ~np.isnan(uv[:, 0])
    if ok.any():
        x0, x1 = uv[ok, 0].min(), uv[ok, 0].max()
        y0, y1 = uv[ok, 1].min(), uv[ok, 1].max()
        cv2.putText(out, "virtual OPT %s  L=%.1fmm  %dx%dpx" % (along, MP.MOD_H_MM, x1 - x0, y1 - y0),
                    (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 220, 255), 1, cv2.LINE_AA)
        meta.update({"mode": "virtual", "edges": n, "px": [float(x0), float(y0), float(x1), float(y1)],
                     "dist_mm": float(P_cam[:, 2].mean())})
    else:
        meta.update({"mode": "virtual", "edges": 0, "px": None})
    return out, meta


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):                                           # 静音
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):                                                    # noqa: N802
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path in ("/mod.jpg", "/mod"):
                cam = q.get("cam", "arm")
                img, meta = build(cam, q.get("along", "+z"), float(q.get("offset", 0)),
                                  q.get("real") in ("1", "true", "yes"))
                body = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 88])[1].tobytes()
                self._send(200, body, "image/jpeg")
                return
            if u.path == "/status":
                T, he = MP.handeye()
                _, _, note = MP.align_shift()
                self._send(200, json.dumps({
                    "ok": True, "port": PORT,
                    "mod_spec": {"L": MP.MOD_H_MM, "W": MP.MOD_W_MM, "T": MP.MOD_T_MM},
                    "handeye": {"t_mm": he.get("t_mm"), "rpy_deg": he.get("rpy_deg"),
                                "resid_mm": he.get("resid_trans_mm_rms"),
                                "resid_deg": he.get("resid_rot_deg_rms"), "views": len(he.get("views") or [])},
                    "shift_px": list(SHIFT), "shift_src": "module_spec 实测(固定)",
                    "toolframe_shift": note,
                    "cams": ["arm", "local", "local2"],
                    "aoi_ready": False,
                    "aoi_note": "aoi_gold/aoi_surface 与 base 的外参未标定, 光模块位置算不出",
                    "routes": ["/mod.jpg?cam=arm", "/mod.jpg?cam=arm&real=1", "/mod.jpg?cam=arm&along=-z", "/status"],
                }, ensure_ascii=False).encode())
                return
            self._send(404, b'{"ok":false,"err":"not found"}')
        except Exception as e:                                           # noqa: BLE001
            self._send(500, json.dumps({"ok": False, "err": "%s: %s" % (type(e).__name__, e)},
                                       ensure_ascii=False).encode())


def main():
    print("虚拟光模块叠加服务 :%d  (shift=%s)" % (PORT, SHIFT), flush=True)
    print("  http://127.0.0.1:%d/mod.jpg?cam=arm" % PORT, flush=True)
    print("  http://127.0.0.1:%d/status" % PORT, flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()


if __name__ == "__main__":
    main()
