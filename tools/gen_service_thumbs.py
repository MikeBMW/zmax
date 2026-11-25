#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""服务缩略图生成器 —— 用本机 chromium 的 CDP 真截每个服务页面。

为什么不用 `chromium --screenshot`: snap 版 chromium 只能写 $HOME/snap/<pkg>/common,
且老 headless 的 --screenshot 与 --virtual-time-budget 共存时对有 setInterval 的页面不落盘。
CDP 方案可控制"等多久再截", 3D/图表页也能出图。

用法:
  python3 tools/gen_service_thumbs.py                 # 截 registry.json 里所有 web 服务
  python3 tools/gen_service_thumbs.py --only 8797 8810
  python3 tools/gen_service_thumbs.py --list          # 只打印会截哪些

产物: services/web/thumbs/<name>.png (1280x800)
"""
import argparse
import base64
import json
import os
import os.path as osp
import socket
import struct
import subprocess
import sys
import time
import urllib.request

ROOT = osp.dirname(osp.dirname(osp.abspath(__file__)))
REG = osp.join(ROOT, "services", "registry.json")
OUT = osp.join(ROOT, "services", "web", "thumbs")
UD = osp.expanduser("~/snap/chromium/common/zthumb-ud")
PORT = 9333


# ---------- 最小 WebSocket 客户端 (stdlib, 不引第三方) ----------
def ws_connect(url, timeout=10):
    host_port, path = url[5:].split("/", 1)
    path = "/" + path
    host, port = host_port.split(":")
    s = socket.create_connection((host, int(port)), timeout=timeout)
    key = base64.b64encode(os.urandom(16)).decode()
    s.sendall((
        "GET %s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
        "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (path, host_port, key)
    ).encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        c = s.recv(4096)
        if not c:
            raise IOError("ws 握手无响应")
        buf += c
    if b"101" not in buf.split(b"\r\n")[0]:
        raise IOError("ws 握手失败: %r" % buf.split(b"\r\n")[0])
    return s


def ws_send(s, obj):
    payload = json.dumps(obj).encode()
    hdr = bytearray([0x81])
    n = len(payload)
    if n < 126:
        hdr.append(0x80 | n)
    elif n < 65536:
        hdr.append(0x80 | 126)
        hdr += struct.pack(">H", n)
    else:
        hdr.append(0x80 | 127)
        hdr += struct.pack(">Q", n)
    mask = os.urandom(4)
    hdr += mask
    s.sendall(bytes(hdr) + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))


def _recv_exact(s, n):
    d = b""
    while len(d) < n:
        c = s.recv(n - len(d))
        if not c:
            raise EOFError("ws 断开")
        d += c
    return d


def ws_recv(s):
    """返回一条完整消息 (拼接分片)。"""
    chunks = []
    while True:
        h = _recv_exact(s, 2)
        fin = h[0] & 0x80
        op = h[0] & 0x0F
        masked = h[1] & 0x80
        ln = h[1] & 0x7F
        if ln == 126:
            ln = struct.unpack(">H", _recv_exact(s, 2))[0]
        elif ln == 127:
            ln = struct.unpack(">Q", _recv_exact(s, 8))[0]
        if masked:
            m = _recv_exact(s, 4)
            data = bytes(b ^ m[i % 4] for i, b in enumerate(_recv_exact(s, ln)))
        else:
            data = _recv_exact(s, ln)
        if op == 0x8:
            raise EOFError("ws 关闭帧")
        chunks.append(data)
        if fin:
            return b"".join(chunks)


class CDP:
    def __init__(self, ws_url):
        self.s = ws_connect(ws_url)
        self.i = 0
        self.send("Page.enable")

    def send(self, method, **params):
        self.i += 1
        ws_send(self.s, {"id": self.i, "method": method, "params": params})
        return self.i

    def call(self, method, timeout=20, **params):
        mid = self.send(method, **params)
        t0 = time.time()
        while time.time() - t0 < timeout:
            msg = json.loads(ws_recv(self.s).decode("utf-8", "replace"))
            if msg.get("id") == mid:
                if "error" in msg:
                    raise IOError("%s -> %s" % (method, msg["error"]))
                return msg.get("result") or {}
        raise TimeoutError("%s 超时" % method)

    def close(self):
        try:
            self.s.close()
        except Exception:                                          # noqa: BLE001
            pass


def http_json(url, method="GET", timeout=5):
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def chrome_up():
    for _ in range(40):
        try:
            return http_json("http://127.0.0.1:%d/json/version" % PORT)
        except Exception:                                          # noqa: BLE001
            time.sleep(0.25)
    return None


def start_chrome():
    os.makedirs(UD, exist_ok=True)
    p = subprocess.Popen([
        "chromium", "--headless", "--no-sandbox", "--disable-gpu",
        "--enable-unsafe-swiftshader", "--hide-scrollbars",
        "--user-data-dir=" + UD, "--remote-debugging-port=%d" % PORT,
        "--window-size=1280,800", "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not chrome_up():
        p.kill()
        raise RuntimeError("chromium CDP 没起来 (端口 %d)" % PORT)
    return p


def shot(cdp_page_ws, url, out_png, wait_s=8.0, w=1280, h=800):
    cdp = CDP(cdp_page_ws)
    try:
        cdp.call("Emulation.setDeviceMetricsOverride", width=w, height=h,
                 deviceScaleFactor=1, mobile=False)
        cdp.call("Page.navigate", url=url)
        time.sleep(wait_s)                    # 给 3D/图表/轮询渲染留时间
        r = cdp.call("Page.captureScreenshot", timeout=40, format="png",
                     captureBeyondViewport=False)
        data = base64.b64decode(r["data"])
        with open(out_png, "wb") as f:
            f.write(data)
        return len(data)
    finally:
        cdp.close()


def pick_urls(only=None):
    reg = json.load(open(REG, encoding="utf-8"))
    out = []
    for s in reg["services"]:
        if only and str(s["port"]) not in only and s["name"] not in only:
            continue
        # 只截有 HTML 页面的服务: 帧源 (8802=framepng) / 纯 JSON 端点在列表里标 web=false 时跳过
        if s.get("thumb") is False:
            continue
        out.append((s["name"], "http://127.0.0.1:%d%s" % (s["port"], s.get("path") or "/")))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--wait", type=float, default=8.0)
    a = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    items = pick_urls(a.only)
    if a.list:
        for n, u in items:
            print("%-14s %s" % (n, u))
        return 0

    started = time.time()
    proc = start_chrome()
    ok, fail = [], []
    try:
        for name, url in items:
            try:
                t = http_json("http://127.0.0.1:%d/json/new?about:blank" % PORT, method="PUT")
                ws = t["webSocketDebuggerUrl"]
                out = osp.join(OUT, name + ".png")
                n = shot(ws, url, out, wait_s=a.wait)
                ok.append((name, n))
                print("  ✅ %-14s %6dB  %s" % (name, n, url), flush=True)
                try:
                    http_json("http://127.0.0.1:%d/json/close/%s" % (PORT, t["id"]))
                except Exception:                                  # noqa: BLE001
                    pass
            except Exception as e:                                 # noqa: BLE001
                fail.append((name, repr(e)))
                print("  ❌ %-14s %r" % (name, e), flush=True)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except Exception:                                          # noqa: BLE001
            proc.kill()
    print("\n%d 成功 / %d 失败 · %.1fs · 产物 %s" % (len(ok), len(fail), time.time() - started, OUT))
    for n, e in fail:
        print("   失败 %-14s %s" % (n, e))
    return 0 if not fail else 2


if __name__ == "__main__":
    sys.exit(main())
