#!/usr/bin/env python3
"""3DGS 资产网页查看器 (同源四件套, 按 robot-3dgs-scene-asset/references/splat-web-viewer.md 的定式):

  /gsview            → tools/web/gs_view.html (热读, 改页面不用重启)
  /gs/list           → 资产清单 JSON (名 · 字节 · mtime · 留出 PSNR · 高斯数)
  /gs/latest.splat   → mtime 最新的 <资产>/gs.splat
  /gs/<名>.splat     → 定点资产 (名字白名单 + realpath 限定在资产根目录内)
  /lib/...           → tools/web/lib/... (查看器 JS, 白名单静态)

用法: ./gui-venv311/bin/python tools/gs_view_serve.py --port 8795
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO = os.path.expanduser("~/zmax")
ASSET_ROOT = os.path.join(REPO, "zmax_data", "gs_assets")
WEB = os.path.join(REPO, "tools", "web")
NAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,80}$")
LIB_EXT = {".js", ".css", ".png", ".jpg", ".svg", ".wasm", ".json", ".html", ".mjs"}


def assets():
    out = []
    try:
        names = os.listdir(ASSET_ROOT)
    except OSError:
        return out
    for n in names:
        p = os.path.join(ASSET_ROOT, n, "gs.splat")
        if not os.path.isfile(p):
            continue
        st = os.stat(p)
        rep = {}
        rp = os.path.join(ASSET_ROOT, n, "train_report.json")
        if os.path.isfile(rp):
            try:
                rep = json.load(open(rp, encoding="utf-8"))
            except Exception:                                           # noqa: BLE001
                rep = {}
        out.append({"name": n, "bytes": st.st_size, "mtime": st.st_mtime,
                    "mtime_s": time.strftime("%F %T", time.localtime(st.st_mtime)),
                    "psnr_holdout_db": rep.get("psnr_holdout_db"),
                    "psnr_train_db": rep.get("psnr_train_db"),
                    "n_gaussians": rep.get("n_gaussians") or (st.st_size // 32)})
    out.sort(key=lambda a: -a["mtime"])
    return out


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *a):                                     # noqa: A003
        pass

    def _send(self, code, body=b"", ctype="application/json; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body:
            try:
                self.wfile.write(body)
            except BrokenPipeError:
                pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _file(self, path, ctype):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            return self._send(404, b"not found", "text/plain; charset=utf-8")
        self._send(200, data, ctype)

    def do_GET(self):                                                   # noqa: N802
        p = self.path.split("?")[0]
        if p in ("/", "/gsview", "/gsview.html", "/gs"):
            return self._file(os.path.join(WEB, "gs_view.html"), "text/html; charset=utf-8")
        if p == "/gs/list":
            return self._json({"assets": assets(), "root": ASSET_ROOT})
        if p == "/gs/latest.splat":
            a = assets()
            if not a:
                return self._send(404, b"no asset", "text/plain")
            return self._file(os.path.join(ASSET_ROOT, a[0]["name"], "gs.splat"),
                              "application/octet-stream")
        m = re.match(r"^/gs/([^/]+)\.splat$", p)
        if m:
            name = m.group(1)
            if not NAME_RE.match(name):
                return self._send(404, b"bad name", "text/plain")
            path = os.path.realpath(os.path.join(ASSET_ROOT, name, "gs.splat"))
            if not path.startswith(os.path.realpath(ASSET_ROOT) + os.sep) or not os.path.isfile(path):
                return self._send(404, b"not found", "text/plain")
            return self._file(path, "application/octet-stream")
        if p.startswith("/lib/"):
            rel = p[len("/lib/"):]
            path = os.path.realpath(os.path.join(WEB, "lib", rel))
            base = os.path.realpath(os.path.join(WEB, "lib")) + os.sep
            if not path.startswith(base) or not os.path.isfile(path):
                return self._send(404, b"not found", "text/plain")
            if os.path.splitext(path)[1].lower() not in LIB_EXT:
                return self._send(404, b"bad ext", "text/plain")
            ct = {".js": "application/javascript", ".mjs": "application/javascript",
                  ".css": "text/css", ".html": "text/html; charset=utf-8",
                  ".json": "application/json"}.get(os.path.splitext(path)[1].lower(),
                                                   "application/octet-stream")
            return self._file(path, ct + "; charset=utf-8" if ct.startswith("text") or "javascript" in ct or ct == "application/json" else ct)
        return self._send(404, b"not found", "text/plain; charset=utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8795)
    a = ap.parse_args()
    srv = ThreadingHTTPServer(("0.0.0.0", a.port), H)
    print("3DGS 查看器: http://127.0.0.1:%d/gsview  (资产根 %s, 共 %d 份)"
          % (a.port, ASSET_ROOT, len(assets())))
    srv.serve_forever()


if __name__ == "__main__":
    main()
