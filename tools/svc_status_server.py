#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""svc_status_server.py — 550C 本机 systemd 服务状态只读出口 (默认 :8818)。

给 Windows 侧 8799 的「所有服务汇总」页直接拉数据用。
只读: 仅执行 systemctl list-units, 不改任何状态。

GET /units  → {"ok":true,"host":"intel-550c","ts":epoch,"count":N,"units":[
                 {"unit":"zmax-gs-autocap.service","active":"active","sub":"running",
                  "description":"...","kind":"zmax"}, ...]}
GET /health → {"ok":true,"count":N,"ts":epoch}
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8818
TTL = 60.0
# 除 zmax-* 外, 还要一并汇报的关键系统服务
EXTRA = ("arm-pose-relay.service", "nginx.service", "mysql.service", "ssh.service",
         "docker.service", "containerd.service", "xrdp.service")

_lock = threading.Lock()
_cache = {"ts": 0.0, "units": []}


def collect():
    now = time.time()
    with _lock:
        if now - _cache["ts"] < TTL and _cache["units"]:
            return _cache["units"]
    try:
        out = subprocess.run(
            ["systemctl", "list-units", "--type=service", "--all", "--no-pager",
             "--no-legend", "--output=json"],
            capture_output=True, text=True, timeout=15,
        ).stdout
        raw = json.loads(out or "[]")
    except Exception:
        raw = []
    units = []
    for u in raw:
        name = u.get("unit") or ""
        if not name.endswith(".service"):
            continue
        if name.startswith("zmax"):
            kind = "zmax"
        elif name in EXTRA:
            kind = "system"
        else:
            continue
        units.append({
            "unit": name,
            "name": name[:-len(".service")],
            "active": u.get("active") or "",
            "sub": u.get("sub") or "",
            "description": u.get("description") or "",
            "kind": kind,
        })
    units.sort(key=lambda x: (x["kind"] != "zmax", x["name"]))
    with _lock:
        _cache["ts"] = now
        _cache["units"] = units
    return units


def payload():
    units = collect()
    return {
        "ok": True,
        "host": "intel-550c",
        "ts": time.time(),
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(units),
        "units": units,
    }


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):      # 静音
        return

    def _send(self, code, body: bytes, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def do_GET(self):
        p = self.path.split("?", 1)[0]
        if p in ("/units", "/units.json", "/api/units"):
            try:
                self._send(200, json.dumps(payload(), ensure_ascii=False).encode())
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)}).encode())
        elif p in ("/health", "/"):
            try:
                u = collect()
                self._send(200, json.dumps({"ok": True, "count": len(u), "ts": time.time()}).encode())
            except Exception as e:
                self._send(500, json.dumps({"ok": False, "error": str(e)}).encode())
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    srv.daemon_threads = True
    print("svc_status_server on :%d" % PORT, flush=True)
    srv.serve_forever()
