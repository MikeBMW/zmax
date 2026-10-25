#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🌉 DDS ⇄ WS 桥 (本地 DDS 一侧的接驳器) —— 配合 ws_bus_relay.py 做跨网 DDS

拓扑 (老倪 2026-10-25 B 方案):
    550C 本地 DDS  ⇄  ws_bridge --role edge  ⇄  wss://datadrive.world/ws/bus/  ⇄  ws_bridge --role hub  ⇄  4060 本地 DDS
   · 本地这一跳还是**真 DDS**(同一份 cyclonedds_unicast.xml, 127.0.0.1 单播);
   · 跨网那一跳是 web(443/TLS), 因为两台之间只有 SSH, DDS 的 UDP 没有路;
   · 中继不解析业务, 只按 channel 名 fan-out。

角色 (说白了就是"哪些话题往上发、哪些往下收"):
  edge (550C): up=hw_state,train_prog,heartbeat   down=deploy_cmd
  hub  (4060): up=deploy_cmd                       down=hw_state,train_prog,heartbeat

语义 (判据就按这些证, 不靠"看着通了"):
  · latest-wins: 每话题只发最新一帧, 背压时丢旧留新, 不排队不积压;
  · seq 单调: 每 (src,ch) 一条计数, 收端算连续性(缺号率);
  · 断线指数退避重连(1→2→4→…→30s), 恢复后只发最新;
  · 白名单: --up/--down 之外的话题一律不碰 (plan/exec 绝不挂这条线, 动作仍只走 8793 授权链)。

用法:
  python3 tools/dds/ws_bridge.py --role edge --url wss://datadrive.world/ws/bus/ --token xxx
  python3 tools/dds/ws_bridge.py --role hub  --url wss://datadrive.world/ws/bus/ --token xxx
  python3 tools/dds/ws_bridge.py --selftest            # 不起 DDS, 只验 web 来回
"""
import argparse
import base64
import dataclasses
import json
import os
import socket
import ssl
import sys
import threading
import time
import urllib.parse

# 本文件在 tools/dds/, 而 zmax_node.py 在 工程根/dds/ ⇒ 两个目录都要在 sys.path 上
_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.join(os.path.dirname(os.path.dirname(_HERE)), "dds")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

OP_CONT, OP_TEXT, OP_BIN, OP_CLOSE, OP_PING, OP_PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA
ROLES = {
    # 2026-10-25: 规划也要跨网 —— 550B(hub) 出 ss_plan, 550C(edge) 收 ss_plan
    "edge": (["hw_state", "train_prog", "heartbeat"], ["deploy_cmd", "ss_plan"]),
    "hub": (["deploy_cmd", "ss_plan"], ["hw_state", "train_prog", "heartbeat"]),
}


# ─────────────────────────────── WS 客户端 (纯标准库) ───────────────────────────────
class WSClient:
    def __init__(self, url, token="", on_msg=None, on_state=None, verbose=True):
        self.url = url
        self.token = token
        self.on_msg = on_msg
        self.on_state = on_state
        self.verbose = verbose
        self.sock = None
        self.alive = False
        self.subs = []
        self.lock = threading.Lock()
        self.stat = {"sent": 0, "recv": 0, "reconnect": 0, "send_err": 0}
        self._last_rx = 0.0
        self._stop = False

    def log(self, *a):
        if self.verbose:
            print(time.strftime("[%H:%M:%S]"), *a, flush=True)

    # —— 握手 ——
    def _connect(self):
        u = urllib.parse.urlparse(self.url)
        host = u.hostname
        port = u.port or (443 if u.scheme == "wss" else 80)
        path = (u.path or "/") + (("?" + u.query) if u.query else "")
        if self.token:
            path += ("&" if "?" in path else "?") + "token=" + urllib.parse.quote(self.token)
        raw = socket.create_connection((host, port), 10)
        if u.scheme == "wss":
            ctx = ssl.create_default_context()
            raw = ctx.wrap_socket(raw, server_hostname=host)
        key = base64.b64encode(os.urandom(16)).decode()
        req = ("GET %s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (path, host, key))
        raw.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = raw.recv(4096)
            if not chunk:
                raise ConnectionError("握手被关闭")
            buf += chunk
        status = buf.split(b"\r\n")[0].decode("latin-1")
        if "101" not in status:
            raise ConnectionError("握手失败: %s" % status)
        raw.settimeout(None)
        self.sock = raw
        self.alive = True
        self._last_rx = time.time()
        if self.subs:
            self._send({"op": "sub", "ch": list(self.subs)})

    # —— 帧 ——
    def _send(self, obj):
        if not self.alive or not self.sock:
            return False
        data = json.dumps(obj, ensure_ascii=False).encode()
        n = len(data)
        key = os.urandom(4)
        if n < 126:
            head = bytes([0x81, 0x80 | n])
        elif n < 65536:
            head = bytes([0x81, 0x80 | 126]) + n.to_bytes(2, "big")
        else:
            head = bytes([0x81, 0x80 | 127]) + n.to_bytes(8, "big")
        masked = bytes(b ^ key[i % 4] for i, b in enumerate(data))
        try:
            with self.lock:
                self.sock.sendall(head + key + masked)
            self.stat["sent"] += 1
            return True
        except Exception as e:                                                  # noqa: BLE001
            self.stat["send_err"] += 1
            self.log("! 发送失败 %s" % e)
            self.alive = False
            return False

    def sub(self, channels):
        self.subs = list(channels)
        if self.alive:
            self._send({"op": "sub", "ch": self.subs})

    def pub(self, ch, payload, seq, ts, src):
        return self._send({"op": "pub", "ch": ch, "seq": seq, "ts": ts, "src": src, "payload": payload})

    def _read_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("连接被关闭")
            buf += chunk
        return buf

    def _read_frame(self):
        h = self._read_exact(2)
        op = h[0] & 0x0F
        ln = h[1] & 0x7F
        if ln == 126:
            ln = int.from_bytes(self._read_exact(2), "big")
        elif ln == 127:
            ln = int.from_bytes(self._read_exact(8), "big")
        key = self._read_exact(4) if (h[1] & 0x80) else None
        body = self._read_exact(ln) if ln else b""
        if key:
            body = bytes(b ^ key[i % 4] for i, b in enumerate(body))
        return op, body

    def _reader(self):
        while self.alive and not self._stop:
            try:
                op, body = self._read_frame()
                self._last_rx = time.time()
                if op == OP_CLOSE:
                    raise ConnectionError("对端 close")
                if op == OP_PING:
                    with self.lock:
                        self.sock.sendall(bytes([0x8A, 0x80]) + os.urandom(4))
                    continue
                if op != OP_TEXT:
                    continue
                self.stat["recv"] += 1
                try:
                    msg = json.loads(body.decode())
                except Exception:                                               # noqa: BLE001
                    continue
                if msg.get("op") == "pong":
                    continue
                if self.on_msg:
                    self.on_msg(msg)
            except Exception as e:                                              # noqa: BLE001
                if not self._stop:
                    self.log("! 读异常 %s" % e)
                self.alive = False
                break

    def _pinger(self):
        while not self._stop:
            time.sleep(15)
            if self.alive:
                self._send({"op": "ping"})

    def run_forever(self):
        backoff = 1.0
        threading.Thread(target=self._pinger, daemon=True).start()
        while not self._stop:
            try:
                self._connect()
                backoff = 1.0
                if self.on_state:
                    self.on_state(True)
                self.log("✅ 已连上 %s (订阅 %s)" % (self.url, ",".join(self.subs) or "-"))
                self._reader()
            except Exception as e:                                              # noqa: BLE001
                self.log("! 连接失败: %s" % e)
            self.alive = False
            if self.on_state:
                self.on_state(False)
            if self._stop:
                break
            self.stat["reconnect"] += 1
            self.log("… %.0fs 后重连" % backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

    def stop(self):
        self._stop = True
        self.alive = False
        try:
            if self.sock:
                self.sock.close()
        except Exception:                                                       # noqa: BLE001
            pass


# ─────────────────────────────── IDL 结构 ⇄ dict ───────────────────────────────
def _field_names(cls):
    try:
        return [f.name for f in dataclasses.fields(cls)]
    except Exception:                                                           # noqa: BLE001
        return list(getattr(cls, "__annotations__", {}) or {})


def _default_for(t):
    n = (getattr(t, "__name__", None) or str(t)).lower()
    if "bool" in n:
        return False
    if "int" in n:
        return 0
    if "float" in n or "double" in n:
        return 0.0
    if "str" in n:
        return ""
    if "sequence" in n or "list" in n:
        return []
    return None


def to_dict(obj):
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    d = {}
    for k in _field_names(type(obj)):
        try:
            d[k] = getattr(obj, k)
        except Exception:                                                       # noqa: BLE001
            pass
    return d or dict(getattr(obj, "__dict__", {}))


def from_dict(cls, payload):
    """按 IDL 字段名裁键 + 补缺失字段的零值; 多余键丢弃(中继可能带元字段)"""
    names = _field_names(cls)
    ann = getattr(cls, "__annotations__", {}) or {}
    kw = {}
    for k in names:
        if k in payload:
            kw[k] = payload[k]
        else:
            kw[k] = _default_for(ann.get(k, ""))
    kw = {k: v for k, v in kw.items() if v is not None}
    return cls(**kw)


# ─────────────────────────────── 桥本体 ───────────────────────────────
class Bridge:
    def __init__(self, role, url, token, up, down, src_name, max_hz=20.0, verbose=True,
                 no_dds=False):
        self.role = role
        self.up = list(up)
        self.down = list(down)
        self.src = src_name
        self.max_hz = max_hz
        self.verbose = verbose
        self.no_dds = no_dds
        self.node = None
        self.TOPICS = {}
        if not no_dds:
            from zmax_node import TOPICS, Node                                 # noqa: E402
            self.TOPICS = TOPICS
            self.node = Node("ws_bridge_" + role)
        if self.node is not None:
            for ch in self.down:            # 先把下行 writer 建好, 让 DDS 发现尽早完成
                try:
                    self.node.pub(ch)
                except Exception as e:                                          # noqa: BLE001
                    self.log("! 预建 writer 失败 ch=%s: %s" % (ch, e))
        self.seq = {ch: 0 for ch in self.up}
        self.last_tx = {ch: 0.0 for ch in self.up}
        self.last_seen = {}          # (src,ch) -> seq
        self.gap = {}                # (src,ch) -> 缺号数
        self.rx = {}                 # ch -> 收数
        self.written = {}            # ch -> 写进本地 DDS 数
        self.ws = WSClient(url, token, on_msg=self._on_msg,
                           on_state=self._on_state, verbose=verbose)

    def log(self, *a):
        if self.verbose:
            print(time.strftime("[%H:%M:%S]"), *a, flush=True)

    def _on_state(self, up):
        if up:
            self.ws.sub(self.down)
            self.log("🌐 ws-bus %s | 上行 %s | 下行 %s" %
                     ("已连" if up else "断开", ",".join(self.up), ",".join(self.down) or "-"))

    def _on_msg(self, msg):
        if msg.get("op") != "msg":
            return
        ch = msg.get("ch")
        if ch not in self.down:
            return                      # 白名单: 不关心的话题直接丢
        self.rx[ch] = self.rx.get(ch, 0) + 1
        src = msg.get("src") or "?"
        sq = msg.get("seq")
        if isinstance(sq, int):
            k = (src, ch)
            prev = self.last_seen.get(k)
            if prev is not None and sq > prev + 1:
                self.gap[k] = self.gap.get(k, 0) + (sq - prev - 1)
            self.last_seen[k] = max(sq, prev if prev is not None else sq)
        if self.no_dds or not self.node:
            return
        cls = self.TOPICS.get(ch)
        if cls is None:
            return
        try:
            obj = from_dict(cls, msg.get("payload") or {})
            self.node.send(ch, obj)
            self.written[ch] = self.written.get(ch, 0) + 1
        except Exception as e:                                                  # noqa: BLE001
            self.log("! 写本地 DDS 失败 ch=%s: %s" % (ch, e))

    def pump_up(self):
        """本地 DDS → WS: 每话题只发最新一帧 (latest-wins)"""
        for ch in self.up:
            if ch not in self.TOPICS:
                continue
            try:
                samples = self.node.sub(ch).take()
            except Exception as e:                                              # noqa: BLE001
                self.log("! 读 DDS 失败 ch=%s: %s" % (ch, e))
                continue
            if not samples:
                continue
            now = time.time()
            if (now - self.last_tx[ch]) < (1.0 / self.max_hz):
                continue
            sample = samples[-1]        # 只取最新, 旧的丢
            self.seq[ch] += 1
            ok = self.ws.pub(ch, to_dict(sample), self.seq[ch], now, self.src)
            if ok:
                self.last_tx[ch] = now

    def stats_line(self):
        parts = []
        for ch in self.up:
            parts.append("↑%s:%d" % (ch, self.seq[ch]))
        for ch in self.down:
            g = sum(v for (s, c), v in self.gap.items() if c == ch)
            parts.append("↓%s:%d(写%d,缺%d)" % (ch, self.rx.get(ch, 0), self.written.get(ch, 0), g))
        return "ws sent=%d recv=%d 重连=%d | %s" % (
            self.ws.stat["sent"], self.ws.stat["recv"], self.ws.stat["reconnect"], " ".join(parts))

    def run(self):
        threading.Thread(target=self.ws.run_forever, daemon=True).start()
        time.sleep(0.5)
        for ch in self.down:               # 等下行话题配对(最多 10s): 配对前写的样本会丢
            try:
                ok = self.node.wait_for_match(ch, 1, 10.0) if self.node is not None else False
                self.log("%s 下行配对 %s" % ("✅" if ok else "⚠️", ch))
            except Exception as e:                                              # noqa: BLE001
                self.log("! wait_for_match 失败 %s: %s" % (ch, e))
        t_last = 0.0
        while True:
            try:
                self.pump_up()
            except Exception as e:                                              # noqa: BLE001
                self.log("! pump 异常: %s" % e)
            if time.time() - t_last >= 10:
                t_last = time.time()
                self.log("📊 " + self.stats_line())
            time.sleep(0.02)


# ─────────────────────────────── 自检 ───────────────────────────────
def selftest(url, token):
    """不起 DDS: 起一个本地中继 + 两个 bridge(no_dds) 验 web 来回"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from ws_bus_relay import Relay                                          # noqa: E402
    if url.startswith("ws://127.0.0.1:"):
        port = int(urllib.parse.urlparse(url).port or 39099)
        threading.Thread(target=Relay(token=token, verbose=False).serve,
                         args=("127.0.0.1", port), daemon=True).start()
        time.sleep(0.4)
    got = []

    def on_msg(m):
        if m.get("op") == "msg":
            got.append(m)

    cli = WSClient(url, token, on_msg=on_msg, verbose=False)
    cli.sub(["hw_state"])
    threading.Thread(target=cli.run_forever, daemon=True).start()
    time.sleep(1.2)
    for i in range(5):
        cli.pub("hw_state", {"node": "550C", "i": i}, i, time.time(), "selftest")
        time.sleep(0.1)
    time.sleep(1.2)
    print("web 来回: 发出 5 条 | 收到 %d 条 → %s" % (len(got), "✅" if len(got) >= 4 else "❌"))
    for m in got[:3]:
        print("   %s seq=%s src=%s %s" % (m["ch"], m["seq"], m["src"], m["payload"]))
    return 0 if len(got) >= 4 else 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--role", choices=list(ROLES), default="edge")
    ap.add_argument("--url", default=os.environ.get("ZMAX_WS_BUS_URL", "wss://datadrive.world/ws/bus/"))
    ap.add_argument("--token", default=os.environ.get("ZMAX_WS_BUS_TOKEN", ""))
    ap.add_argument("--up", default="", help="逗号分隔; 缺省按角色")
    ap.add_argument("--down", default="")
    ap.add_argument("--src", default="", help="源名 (edge=550C / hub=4060)")
    ap.add_argument("--max-hz", type=float, default=20.0)
    ap.add_argument("--no-dds", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest(a.url, a.token)
    up, down = ROLES[a.role]
    if a.up:
        up = [x for x in a.up.split(",") if x]
    if a.down:
        down = [x for x in a.down.split(",") if x]
    src = a.src or ("550C" if a.role == "edge" else "4060")
    Bridge(a.role, a.url, a.token, up, down, src, a.max_hz, not a.quiet, a.no_dds).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
