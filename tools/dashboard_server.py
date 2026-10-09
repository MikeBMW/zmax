#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dashboard_server.py — 本机只读静态服务(默认 :8799), 给「统一 web 页 + 数据 + 交付 APK」一个稳定下载/打开入口。

为什么单开一个端口: 现场主服务 (cam_live_stream.py :8791) 是在役推流服务, 改它要重启 ⇒ 会打断
正在看的画面。本服务只读、零依赖、可随时起停, 与在役链路互不影响。

暴露(白名单, 只读):
  GET /                    → tools/web/unified_app.html      (统一大屏页)
  GET /unified_app.html    → 同上
  GET /dashboard.json      → tools/web/dashboard.json        (与大屏页同目录, 供 fetch)
  GET /dash.json           → 同上
  GET /dl/<file>           → tools/web/dl/<file>             (交付件下载, 含 APK)
其余路径一律 404(不目录遍历)。

用法: python3 tools/dashboard_server.py [--port 8799] [--host 0.0.0.0]
红线: 只读; 不打印/不外泄任何凭据(这里本就不读凭据)。
"""
from __future__ import annotations

import argparse
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(_HERE, "web")
DL = os.path.join(WEB, "dl")

CT = {".html": "text/html; charset=utf-8", ".json": "application/json; charset=utf-8",
      ".apk": "application/vnd.android.package-archive", ".png": "image/png",
      ".js": "application/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}


def _ctype(path: str) -> str:
    return CT.get(os.path.splitext(path)[1].lower(), "application/octet-stream")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, ctype, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:                                                       # noqa: BLE001
            pass

    def do_GET(self):
        p = self.path.split("?", 1)[0]
        if p in ("/", "/unified_app.html", "/dash", "/dash.html"):
            fp = os.path.join(WEB, "unified_app.html")
        elif p in ("/dashboard.json", "/dash.json"):
            fp = os.path.join(WEB, "dashboard.json")
        elif p.startswith("/dl/"):
            fn = os.path.basename(p[len("/dl/"):])         # basename ⇒ 路径穿不出去
            fp = os.path.join(DL, fn)
        else:
            self._send(404, "text/plain; charset=utf-8", b"not found")
            return
        if not os.path.isfile(fp):
            self._send(404, "text/plain; charset=utf-8", ("missing: %s" % os.path.basename(fp)).encode())
            return
        try:
            with open(fp, "rb") as fh:
                self._send(200, _ctype(fp), fh.read())
        except Exception as e:                                                  # noqa: BLE001
            self._send(500, "text/plain; charset=utf-8", str(e).encode())


def main():
    ap = argparse.ArgumentParser(description="只读大屏静态服务")
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--host", default="0.0.0.0")
    a = ap.parse_args()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print("dashboard_server: http://%s:%d/  (web=%s)" % (a.host, a.port, WEB), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
