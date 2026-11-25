#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Z-MAX 框架服务网关 (:8788)。

解决的问题: 状态空间工程的服务散在 8791~8898 二十多个端口上, 谁在哪、活着没、
属于哪一层、归哪个 systemd 管 —— 全靠人记。现场实施/项目经理要能一眼看全并点进去。

四个端点:
    GET  /                     分层门户 (L5/L4/L3/L2/OPS, 带实时健康灯)
    GET  /api/services         服务清单 + 实时健康 (JSON, 可 curl 可导出)
    GET  /api/health           聚合健康 (给外部监控/看门狗用)
    ANY  /go/<name>/<rest>     反向代理到该服务 (同源, 免记端口)

契约来源: services/registry.json。加服务只改 JSON, 不改这个文件。
启动: python3 services/framework_gateway.py --port 8788
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY = os.path.join(HERE, "registry.json")
CACHE_TTL_S = 3.0
_cache = {"ts": 0.0, "data": None}
_lock = threading.Lock()


def load_registry():
    with open(REGISTRY, encoding="utf-8") as f:
        return json.load(f)


def _probe(svc, timeout=2.0):
    """探一个服务: 先试声明的 health 端点, 404/405 就退到 / (多数服务只有首页)。

    实测: 8793/8797/8799/8815 等只实现 `/`, 声明 /health 会全报 404,
    健康灯全红 —— 假的"全离线"比不显示更误导。
    """
    port = svc.get("port")
    out = {"name": svc["name"], "port": port, "up": False, "ms": None,
           "code": None, "err": None, "meta": {}}
    if svc.get("self"):
        # 🔴 网关自己: 探 /api/services 会再次触发 probe_all ⇒ 无限递归/死锁。
        #    自己当然活着 (本请求就是它处理的), 直接短路。
        out["up"] = True
        out["meta"] = {"kind": "self"}
        return out
    if port is None:                      # 本机客户端 (无端口): 不算离线
        out["up"] = True
        out["client"] = True
        out["meta"] = {"kind": "client"}
        return out
    paths = []
    if svc.get("health"):
        paths.append(svc["health"])
    if "/" not in paths:
        paths.append("/")
    t0 = time.time()
    last_err = None
    for path in paths:
        try:
            req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path),
                                         headers={"User-Agent": "zmax-fw/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read(4096)
                out["code"] = r.status
                out["up"] = 200 <= r.status < 400
                out["path"] = path
                try:
                    j = json.loads(body)
                    for k in ("ok", "service", "version", "src", "gaussians", "fps",
                              "err", "busy", "phase", "loaded"):
                        if isinstance(j, dict) and k in j:
                            out["meta"][k] = j[k]
                except Exception:
                    ct = r.headers.get("Content-Type", "")
                    out["meta"]["content_type"] = ct.split(";")[0]
                    m = re.search(rb"<title>(.*?)</title>", body, re.S | re.I)
                    if m:
                        try:
                            out["meta"]["title"] = m.group(1).decode("utf-8", "ignore").strip()[:40]
                        except Exception:
                            pass
                out["ms"] = round((time.time() - t0) * 1000.0, 1)
                return out
        except urllib.error.HTTPError as e:
            last_err = "HTTP %d @%s" % (e.code, path)
            if e.code in (404, 405, 501):
                continue          # 该端点没实现, 换下一个
            out["code"] = e.code
            out["up"] = 200 <= e.code < 400
            break
        except (socket.timeout, TimeoutError):
            last_err = "timeout"
            break
        except urllib.error.URLError as e:
            last_err = type(e.reason).__name__ if hasattr(e, "reason") else "URLError"
            break
        except Exception as e:
            last_err = type(e).__name__
            break
    out["err"] = last_err
    out["ms"] = round((time.time() - t0) * 1000.0, 1)
    return out


def probe_all(reg=None):
    reg = reg or load_registry()
    with ThreadPoolExecutor(max_workers=16) as ex:
        results = list(ex.map(_probe, reg["services"]))
    by_name = {r["name"]: r for r in results}
    for svc in reg["services"]:
        svc_out = dict(svc)
        svc_out.update(by_name.get(svc["name"], {}))
        by_name[svc["name"]] = svc_out
    now = time.time()
    for v in by_name.values():
        th = os.path.join(THUMBS, v["name"] + ".png")
        v["has_thumb"] = os.path.exists(th)
        v["thumb_mtime"] = int(os.path.getmtime(th)) if v["has_thumb"] else None
        v["thumb_age_s"] = round(now - os.path.getmtime(th)) if v["has_thumb"] else None
    real = [v for v in by_name.values() if v.get("port") is not None]
    return {
        "ok": all(v["up"] for v in real),
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "n_total": len(real),
        "n_up": sum(1 for v in real if v["up"]),
        "layers": reg["layers"],
        "title": reg.get("title") or "Z-MAX 产品服务",
        "services": list(by_name.values()),
    }


def get_cached(force=False):
    with _lock:
        if not force and _cache["data"] and (time.time() - _cache["ts"]) < CACHE_TTL_S:
            return _cache["data"]
    data = probe_all()
    with _lock:
        _cache["data"], _cache["ts"] = data, time.time()
    return data


# ------------------------------------------------------------------ 门户页
# 页面本体放 services/web/portal.html —— 改文案/排版不用重启网关 (按 mtime 热读)。
WEB = os.path.join(HERE, "web")
PORTAL = os.path.join(WEB, "portal.html")
THUMBS = os.path.join(WEB, "thumbs")
_ph = {"mtime": 0, "body": b""}


def portal_html():
    try:
        mt = os.path.getmtime(PORTAL)
        if mt != _ph["mtime"] or not _ph["body"]:
            with open(PORTAL, "rb") as f:
                _ph["body"], _ph["mtime"] = f.read(), mt
        return _ph["body"]
    except Exception:
        return "<!doctype html><meta charset=utf-8><h1>portal.html missing</h1>".encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "zmax-fw/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *a):
        pass    # 静音: 常驻服务不刷屏 (老倪规矩)

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        p = u.path
        if p in ("/", "/index.html"):
            return self._send(200, portal_html(), "text/html; charset=utf-8")
        if p.startswith("/thumb/"):
            name = os.path.basename(p[7:]).split(".")[0]
            fp = os.path.join(THUMBS, name + ".png")
            if not re.match(r"^[A-Za-z0-9_-]+$", name or "-") or not os.path.exists(fp):
                return self._send(404, b"", "image/png")
            with open(fp, "rb") as f:
                return self._send(200, f.read(), "image/png")
        if p == "/api/ping":
            return self._send(200, json.dumps({"ok": True, "service": "portal"}),)
        if p == "/api/services":
            force = "force=1" in (u.query or "")
            return self._send(200, json.dumps(get_cached(force), ensure_ascii=False))
        if p == "/api/health":
            d = get_cached()
            code = 200 if d["n_up"] > 0 else 503
            return self._send(code, json.dumps({
                "ok": d["n_up"] == d["n_total"], "n_up": d["n_up"],
                "n_total": d["n_total"], "checked_at": d["checked_at"],
                "down": [s["name"] for s in d["services"] if not s["up"]],
            }, ensure_ascii=False))
        if p.startswith("/go/"):
            return self._proxy(p[4:])
        return self._send(404, json.dumps({"ok": False, "err": "not found"}, ensure_ascii=False))

    def do_POST(self):
        if urlparse(self.path).path.startswith("/go/"):
            return self._proxy(urlparse(self.path).path[4:])
        return self._send(404, json.dumps({"ok": False, "err": "not found"}))

    def _proxy(self, tail):
        """/go/<name>/<rest> -> 127.0.0.1:<port>/<rest>"""
        parts = tail.split("/", 1)
        name = parts[0]
        rest = "/" + (parts[1] if len(parts) > 1 else "")
        reg = load_registry()
        svc = next((s for s in reg["services"] if s["name"] == name), None)
        if not svc:
            return self._send(404, json.dumps({"ok": False, "err": "unknown service '%s'" % name}))
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else None
        try:
            conn = http.client.HTTPConnection("127.0.0.1", svc["port"], timeout=30)
            hdrs = {k: v for k, v in self.headers.items()
                    if k.lower() not in ("host", "connection", "accept-encoding")}
            conn.request(self.command, rest, body=body, headers=hdrs)
            r = conn.getresponse()
            data = r.read()
            self.send_response(r.status)
            for k, v in r.getheaders():
                if k.lower() in ("transfer-encoding", "connection", "content-length"):
                    continue
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            conn.close()
        except Exception as e:
            self._send(502, json.dumps({"ok": False, "err": "%s: %s" % (type(e).__name__, e)},
                                       ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8788)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        d = probe_all()
        print("服务 %d 个, 在线 %d" % (d["n_total"], d["n_up"]))
        for s in d["services"]:
            print("  %-4s %-14s %-6s %s %s" % (s["layer"], s["name"],
                                                (":%d" % s["port"]) if s.get("port") else "本机",
                                                "✅" if s["up"] else "❌",
                                                (s.get("err") or "")[:30]))
        return 0 if d["n_up"] > 0 else 1

    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    srv.daemon_threads = True
    print("Z-MAX 产品服务 · 总索引 http://%s:%d/ (%d 个服务已登记)"
          % (a.host, a.port, len(load_registry()["services"])), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
