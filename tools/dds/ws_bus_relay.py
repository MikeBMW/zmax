#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🌐 zmax WS-Bus 中继 (纯标准库, 无第三方依赖) —— DDS 跨网转发的 web 一层

为什么要有它 (老倪 2026-10-25 选 B 方案):
  550B(4060, 10.163.x) 与 550C(intel, 192.168.23.x) 之间**只有 SSH**, DDS 的 UDP 没有路;
  ECS 上原生 DDS 也扛不了公网。所以把"跨网"这一段换成 web:
      对端 A 本地 DDS ⇄ 本中继(wss 443) ⇄ 对端 B 本地 DDS
  中继本身**不懂 DDS, 也不解析业务**, 只按 channel 名做 fan-out —— 换话题、换载荷都不用改它。

协议 (JSON 文本帧, 一帧一条):
  客户端 → 中继:
    {"op":"sub","ch":["hw_state","train_prog"]}         订阅
    {"op":"pub","ch":"hw_state","seq":12,"ts":1699.1,"src":"550C","payload":{...}}
    {"op":"ping"}
  中继 → 客户端:
    {"op":"msg","ch":"hw_state","seq":12,"ts":...,"src":"550C","payload":{...},"relay_ts":...}
    {"op":"hello","subs":[...],"clients":N}
    {"op":"pong","ts":...}
    {"op":"err","msg":"..."}

用法:
  python3 ws_bus_relay.py --host 127.0.0.1 --port 39064 --token xxx
  python3 ws_bus_relay.py --selftest          # 自己起服务 + 两个客户端互通自检
nginx: location /ws/bus/ { proxy_pass http://127.0.0.1:39064/; Upgrade/Connection 头 }
"""
import argparse
import base64
import hashlib
import json
import os
import socket
import ssl
import struct
import sys
import threading
import time

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
OP_CONT, OP_TEXT, OP_BIN, OP_CLOSE, OP_PING, OP_PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA


# ─────────────────────────── 帧编解码 (RFC6455, 双向共用) ───────────────────────────
def encode_frame(payload, opcode=OP_TEXT, mask=False):
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    n = len(payload)
    b1 = 0x80 | opcode
    if n < 126:
        head = struct.pack("!BB", b1, (0x80 if mask else 0) | n)
    elif n < 65536:
        head = struct.pack("!BBH", b1, (0x80 if mask else 0) | 126, n)
    else:
        head = struct.pack("!BBQ", b1, (0x80 if mask else 0) | 127, n)
    if not mask:
        return head + payload
    key = os.urandom(4)
    return head + key + bytes(b ^ key[i % 4] for i, b in enumerate(payload))


class SocketClosed(Exception):
    pass


def _read_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise SocketClosed()
        buf += chunk
    return buf


def read_frame(sock):
    """返回 (opcode, payload_bytes); 处理分片与掩码"""
    data, opcode = b"", None
    while True:
        h = _read_exact(sock, 2)
        fin = h[0] & 0x80
        op = h[0] & 0x0F
        masked = h[1] & 0x80
        ln = h[1] & 0x7F
        if ln == 126:
            ln = struct.unpack("!H", _read_exact(sock, 2))[0]
        elif ln == 127:
            ln = struct.unpack("!Q", _read_exact(sock, 8))[0]
        key = _read_exact(sock, 4) if masked else None
        body = _read_exact(sock, ln) if ln else b""
        if key:
            body = bytes(b ^ key[i % 4] for i, b in enumerate(body))
        if op in (OP_CLOSE, OP_PING, OP_PONG):
            return op, body
        if op != OP_CONT:
            opcode = op
        data += body
        if fin:
            return opcode or OP_TEXT, data


def accept_key(key):
    return base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()


# ─────────────────────────────── 中继 (fan-out) ───────────────────────────────
class Client:
    def __init__(self, sock, addr):
        self.sock = sock
        self.addr = addr
        self.subs = set()
        self.lock = threading.Lock()
        self.alive = True
        self.sent = 0

    def send_json(self, obj):
        if not self.alive:
            return False
        try:
            with self.lock:
                self.sock.sendall(encode_frame(json.dumps(obj, ensure_ascii=False)))
            self.sent += 1
            return True
        except Exception:                                                       # noqa: BLE001
            self.alive = False
            return False

    def close(self):
        self.alive = False
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except Exception:                                                       # noqa: BLE001
            pass
        try:
            self.sock.close()
        except Exception:                                                       # noqa: BLE001
            pass


class Relay:
    def __init__(self, token="", verbose=True, require_sub=True):
        self.token = token
        self.verbose = verbose
        self.require_sub = require_sub      # True: 只发给声明订阅的客户端(默认)
        self.clients = set()
        self.lock = threading.Lock()
        self.stat = {"in": 0, "out": 0, "drop": 0, "ch": {}}

    def log(self, *a):
        if self.verbose:
            print(time.strftime("[%H:%M:%S]"), *a, flush=True)

    def broadcast(self, ch, frame):
        with self.lock:
            targets = [c for c in self.clients if c.alive and (ch in c.subs or not self.require_sub)]
        ok = 0
        for c in targets:
            if c.send_json(frame):
                ok += 1
            else:
                self.stat["drop"] += 1
                with self.lock:
                    self.clients.discard(c)
        self.stat["out"] += ok
        self.stat["ch"][ch] = self.stat["ch"].get(ch, 0) + 1
        return ok

    def handle(self, conn, addr):
        c = Client(conn, addr)
        with self.lock:
            self.clients.add(c)
        self.log("+ 接入 %s:%s (在线 %d)" % (addr[0], addr[1], len(self.clients)))
        c.send_json({"op": "hello", "ts": time.time(), "require_sub": self.require_sub})
        try:
            while c.alive:
                op, body = read_frame(conn)
                if op == OP_CLOSE:
                    break
                if op == OP_PING:
                    with c.lock:
                        conn.sendall(encode_frame(body, OP_PONG))
                    continue
                if op == OP_BIN:
                    continue
                try:
                    msg = json.loads(body.decode("utf-8"))
                except Exception:                                               # noqa: BLE001
                    c.send_json({"op": "err", "msg": "bad json"})
                    continue
                o = msg.get("op")
                if o == "sub":
                    chs = msg.get("ch") or []
                    if isinstance(chs, str):
                        chs = [chs]
                    c.subs.update(str(x) for x in chs)
                    c.send_json({"op": "hello", "subs": sorted(c.subs), "ts": time.time()})
                elif o == "ping":
                    c.send_json({"op": "pong", "ts": time.time()})
                elif o == "pub" or "ch" in msg:
                    ch = str(msg.get("ch") or "")
                    if not ch:
                        c.send_json({"op": "err", "msg": "no ch"})
                        continue
                    self.stat["in"] += 1
                    frame = {"op": "msg", "ch": ch, "seq": msg.get("seq"),
                             "ts": msg.get("ts"), "src": msg.get("src"),
                             "payload": msg.get("payload"), "relay_ts": time.time()}
                    self.broadcast(ch, frame)
                else:
                    c.send_json({"op": "err", "msg": "unknown op %r" % (o,)})
        except SocketClosed:
            pass
        except Exception as e:                                                  # noqa: BLE001
            self.log("! %s:%s 异常 %s" % (addr[0], addr[1], e))
        finally:
            with self.lock:
                self.clients.discard(c)
            c.close()
            self.log("- 断开 %s:%s (在线 %d)" % (addr[0], addr[1], len(self.clients)))

    def serve(self, host, port, ssl_cert=None, ssl_key=None):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((host, port))
        srv.listen(64)
        ctx = None
        if ssl_cert and ssl_key:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(ssl_cert, ssl_key)
        self.log("ws-bus 中继 listening on %s:%d%s token=%s" %
                 (host, port, " (tls)" if ctx else "", "on" if self.token else "OFF"))
        while True:
            conn, addr = srv.accept()
            try:
                conn.settimeout(30)
                req = b""
                while b"\r\n\r\n" not in req:
                    chunk = conn.recv(4096)
                    if not chunk:
                        raise SocketClosed()
                    req += chunk
                head = req.split(b"\r\n\r\n")[0].decode("latin-1")
                lines = head.split("\r\n")
                path = lines[0].split(" ")[1] if len(lines[0].split(" ")) > 1 else "/"
                hdrs = {}
                for ln in lines[1:]:
                    if ":" in ln:
                        k, v = ln.split(":", 1)
                        hdrs[k.strip().lower()] = v.strip()
                if "websocket" not in hdrs.get("upgrade", "").lower():
                    conn.sendall(b"HTTP/1.1 426 Upgrade Required\r\nContent-Length: 0\r\n\r\n")
                    conn.close()
                    continue
                if self.token:
                    q = path.split("?", 1)[1] if "?" in path else ""
                    tok = ""
                    for kv in q.split("&"):
                        if kv.startswith("token="):
                            tok = kv.split("=", 1)[1]
                    if tok != self.token and hdrs.get("x-zmax-token", "") != self.token:
                        conn.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
                        conn.close()
                        continue
                key = hdrs.get("sec-websocket-key", "")
                resp = ("HTTP/1.1 101 Switching Protocols\r\n"
                        "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                        "Sec-WebSocket-Accept: %s\r\n\r\n" % accept_key(key))
                conn.sendall(resp.encode())
                conn.settimeout(None)
                if ctx:
                    conn = ctx.wrap_socket(conn, server_side=True)
                threading.Thread(target=self.handle, args=(conn, addr), daemon=True).start()
            except SocketClosed:
                try:
                    conn.close()
                except Exception:                                               # noqa: BLE001
                    pass
            except Exception as e:                                              # noqa: BLE001
                self.log("! 握手失败 %s: %s" % (addr, e))
                try:
                    conn.close()
                except Exception:                                               # noqa: BLE001
                    pass


def selftest():
    """本文件自带自检: 起中继 → 两个客户端 (A 订阅 hw_state, B 发 hw_state) 互通"""
    r = Relay(token="t", verbose=False)
    threading.Thread(target=r.serve, args=("127.0.0.1", 39099), daemon=True).start()
    time.sleep(0.5)
    got = []

    def listener():
        s = socket.create_connection(("127.0.0.1", 39099), 5)
        s.sendall(("GET /ws/bus?token=t HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\n"
                   "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
                   "Sec-WebSocket-Version: 13\r\n\r\n" % base64.b64encode(os.urandom(16)).decode()).encode())
        while b"\r\n\r\n" not in s.recv(4096):
            pass
        s.sendall(encode_frame(json.dumps({"op": "sub", "ch": ["hw_state"]}), mask=True))
        t0 = time.time()
        while time.time() - t0 < 4:
            op, body = read_frame(s)
            if op == OP_TEXT:
                got.append(json.loads(body.decode()))
        s.close()

    threading.Thread(target=listener, daemon=True).start()
    time.sleep(0.6)
    s = socket.create_connection(("127.0.0.1", 39099), 5)
    s.sendall(("GET /ws/bus?token=t HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\n"
               "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
               "Sec-WebSocket-Version: 13\r\n\r\n" % base64.b64encode(os.urandom(16)).decode()).encode())
    while b"\r\n\r\n" not in s.recv(4096):
        pass
    for i in range(3):
        s.sendall(encode_frame(json.dumps({"op": "pub", "ch": "hw_state", "seq": i,
                                           "ts": time.time(), "src": "selftest",
                                           "payload": {"node": "550C", "i": i}}), mask=True))
        time.sleep(0.15)
    time.sleep(0.8)
    msgs = [m for m in got if m.get("op") == "msg"]
    print("自检: 订阅端收到 %d 条 → %s" % (len(msgs), "✅ 中继可用" if len(msgs) >= 3 else "❌ 不通"))
    for m in msgs[:3]:
        print("   ch=%s seq=%s src=%s payload=%s" % (m["ch"], m["seq"], m["src"], m["payload"]))
    return 0 if len(msgs) >= 3 else 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=39064)
    ap.add_argument("--token", default=os.environ.get("ZMAX_WS_BUS_TOKEN", ""))
    ap.add_argument("--cert"), 
    ap.add_argument("--key")
    ap.add_argument("--allow-unsubscribed", action="store_true",
                    help="不要求订阅也转发(默认只发给已 sub 的客户端)")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    Relay(token=a.token, verbose=not a.quiet, require_sub=not a.allow_unsubscribed).serve(
        a.host, a.port, a.cert, a.key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
