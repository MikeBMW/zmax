#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L2 观测窗 —— 浏览器里看 "YOLO 感知节点此刻正在看的那一帧"。

为什么要这个代理: 8802 的 /frame.png 不回 CORS 头, 直接做本地 html 打开的话
fetch('/cam.json') 会被浏览器拦; 这里把页面 + 帧 + 相机参数收到同一 origin,
页面就能同时显示 帧/字节/相机/帧龄, 且 **与 YOLO 拉的是同一个 URL**。

用法:
    ./gui-venv311/bin/python tools/l2_watch_server.py          # 起在 8820
    ./gui-venv311/bin/python tools/l2_watch_server.py --open   # 起并自动开浏览器

浏览器: http://127.0.0.1:8798/            (你的机器)
        http://192.168.1.7:8798/          (别人看你的机器)
参数:   ?cam=close|ar3d  ?hz=1..10  ?base=http://其它主机:8802
"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, urlencode

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = os.path.join(ROOT, "tools", "web", "l2_watch.html")
UPSTREAM_DEFAULT = os.environ.get("ZMAX_AR_RENDER", "http://127.0.0.1:8802")


def _proxy(url, timeout=6.0):
    req = urllib.request.Request(url, headers={"User-Agent": "zmax-l2-watch"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.headers.get("Content-Type", "application/octet-stream"), r.read()


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    upstream = UPSTREAM_DEFAULT

    def log_message(self, fmt, *a):                                    # 静音: 4Hz 拉帧不刷屏
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")           # 页面就同源, 这条是给别人嵌 iframe
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):                                                  # noqa: N802
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if u.path in ("/", "/index.html", "/l2_watch.html"):
            try:
                with open(PAGE, encoding="utf-8") as f:
                    self._send(200, f.read().encode("utf-8"), "text/html; charset=utf-8")
            except OSError as e:
                self._send(500, ("页面缺失: %s" % e).encode(), "text/plain; charset=utf-8")
            return
        # 🎯 YOLO 本拍的检测结果 (文件真源, 页面用来画框)
        if u.path in ("/vision_points.json", "/vp.json"):
            fp = os.path.join(ROOT, "zmax_data", "ss_live", "vision_points.json")
            try:
                with open(fp, encoding="utf-8") as f:
                    self._send(200, f.read().encode("utf-8"), "application/json; charset=utf-8")
            except OSError as e:
                self._send(404, ('{"ok":false,"why":"%s"}' % e).encode(), "application/json")
            return
        if u.path in ("/frame.png", "/depth.png", "/cam.json", "/status.json", "/joints.json"):
            q = dict(qs)
            q.pop("_", None)
            url = "%s%s%s" % (self.upstream, u.path, ("?" + urlencode(q, doseq=True)) if q else "")
            try:
                code, ctype, body = _proxy(url)
                self._send(code, body, ctype)
            except urllib.error.HTTPError as e:
                self._send(e.code, (e.read() or b""), "text/plain; charset=utf-8")
            except Exception as e:                                     # noqa: BLE001
                self._send(503, ("上游取帧失败 %s: %s" % (url, e)).encode(), "text/plain; charset=utf-8")
            return
        self._send(404, b"only / /frame.png /depth.png /cam.json /joints.json /status.json /vision_points.json", "text/plain")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8820)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--upstream", default=UPSTREAM_DEFAULT)
    ap.add_argument("--open", action="store_true")
    a = ap.parse_args()
    H.upstream = a.upstream
    srv = None
    _port = a.port
    for _try in range(10):                       # 端口被占 (已有实例在跑) ⇒ 顺延, 别甩 traceback
        try:
            srv = ThreadingHTTPServer((a.host, _port), H)
            break
        except OSError as e:
            if getattr(e, "errno", None) not in (98, 48):
                raise
            # 已经有一份在监听同一个口 ⇒ 直接开那个, 不再起第二份
            try:
                import urllib.request as _u
                _u.urlopen("http://127.0.0.1:%d/" % _port, timeout=2).read(1)
                url = "http://127.0.0.1:%d/" % _port
                print("👁  已在运行: %s  (直接用它; 要换端口加 --port)" % url)
                if a.open:
                    webbrowser.open(url)
                return
            except Exception:                                             # noqa: BLE001
                _port += 1
                continue
    if srv is None:
        raise SystemExit("❌ 端口 %d..%d 都被占用" % (a.port, a.port + 9))
    url = "http://127.0.0.1:%d/" % _port
    print("👁  L2 观测窗: %s   (上游 %s · 与 YOLO 同一个 /frame.png?cam=close)" % (url, a.upstream))
    if a.open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
