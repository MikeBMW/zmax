#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hil_local_api.py — 🙋 HIL 人机在环 · **局域网本地 API** (手机 APP / 工位现场页用)

为什么要有它 (2026-09-27 老倪: 「veh.5.010 状态空间的 HIL 人机在环节点, 接入我的手机 APP,
从这个点我要通过 APP 跟状态空间交互, 人机在环」):
  原来的 HIL 链路是绕公网的: 桥每 N 秒 POST https://datadrive.world/api/relay/hil/state,
  网页 hil.html 读它、写回的指示再由桥取回。手机在现场连的是**局域网**, 再绕一圈公网没有意义;
  现场页(8791/room)需要本地就能读到状态、本地就能把人的指示交给**同一个大脑**。

**同一个大脑(关键)**: 本服务直接 import state_space/hil_bridge 的 build_snapshot / handle_instruction
  ⇒ 画布 n_hil 节点、datadrive 的 hil.html、手机 APP 三处看到的是**同一份状态**、**同一套指示处理**,
    红线也一并在同一个地方生效: 动作类指示一律拒答(只记为待授权), 真动只走 /ctl/* 那套两步授权+限时。

接口(只有 GET/POST, 只产出判读/建议/记录, 不产生任何机械臂动作):
  GET  /hil/state  → {"ok":1, "snapshot":{…}, "pause":bool, "instructions":[最近N条]}
  POST /hil/say    {"text":"…"} → {"ok":1, "reply":"…", "verdict":"…"}
  GET  /health     → {"ok":1, "hil":…}

终端接口 (静静/Hermes; 头 X-Zmax-Term: <token>, 仅回环/192.168.23.*/10.163.146.*;
  token 存 zmax_data/secrets/hil_term.token, 首启自动生成 0600):
  GET  /hil/term/state          → 一行现状(hint)+分层+画布+peers+最近指示+可用动词
  POST /hil/term/say   {"text","from","seq"} → 原样走 HB.handle_instruction; 动作类 refused_motion
  GET  /hil/term/log?n=20       → 最近 N 条指示 (读 reports/hil_instructions.jsonl)
  POST /hil/term/peer  {"name","kind","pid","note"}  ·  GET /hil/term/peers → 在线 peer(TTL 30s)
"""
import importlib.util
import hmac
import json
import os
import secrets
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = "/home/ubuntu/zmax"

# ⚠️ 必须按**文件路径**加载核心模块: 若直接 `import hil_bridge`, 从 tools/ 起进程时会先命中
#   tools/hil_bridge.py(只是 CLI 壳, 没有 build_snapshot/handle_instruction) ⇒ 运行时 AttributeError。
#   核心模块是纯 stdlib ⇒ 按路径加载最稳最快, 不用把 torch/lerobot 那条包 import 链拉起来。
_CORE = os.path.join(ROOT, "src/lerobot/policies/left_right/state_space/hil_bridge.py")
_spec = importlib.util.spec_from_file_location("zmax_hil_core", _CORE)
HB = importlib.util.module_from_spec(_spec)
sys.modules["zmax_hil_core"] = HB
_spec.loader.exec_module(HB)

PORT = int(os.environ.get("ZMAX_HIL_LOCAL_PORT", "8795"))
REPORTS = HB.REPORTS
INSTR_LOG = os.path.join(REPORTS, "hil_instructions.jsonl")
PAUSE_FLAG = os.path.join(REPORTS, "hil_pause.flag")
_LOCK = threading.Lock()
_LAST = {"ts": 0.0, "snap": None}

# ───────────────────── /hil/term/* 终端接口 (静静/Hermes) 门控 ─────────────────────
# 老倪要求(2026-10-09): 终端代理要能便宜读·带裁决写·可审计; 只在**同一个大脑**上加一层,
# 不另造一套 HIL。token 门控 + 网段限制; token 只在 zmax_data/secrets 下 (绝不入代码/日志)。
SECRETS_DIR = os.path.join(ROOT, "zmax_data", "secrets")
TERM_TOKEN_FILE = os.path.join(SECRETS_DIR, "hil_term.token")
TERM_TTL = 30.0                                       # peer 在线 TTL(秒)
ALLOWED_NET_PREFIX = ("192.168.23.", "10.163.146.")   # 回环另判
VERBS = ["状态", "停", "继续", "看画面", "标注", "去<点>", "计划<点>"]
_TOKEN_CACHE = {"v": None}


def _term_token():
    """读终端 token (只读, 绝不打印)。不存在 → ""。"""
    if _TOKEN_CACHE["v"]:
        return _TOKEN_CACHE["v"]
    try:
        with open(TERM_TOKEN_FILE, encoding="utf-8") as f:
            t = f.read().strip()
        if t:
            _TOKEN_CACHE["v"] = t
            return t
    except Exception:                                                    # noqa: BLE001
        pass
    return ""


def _term_token_ensure():
    """启动时调用一次: token 不存在则生成 32B hex 写 0600。返回是否就绪。

    刻意与鉴权分离 ⇒ 未带/错 token 的请求**绝不**触发任何写(连 token 都不生成)。
    """
    if _term_token():
        return True
    try:
        os.makedirs(SECRETS_DIR, mode=0o700, exist_ok=True)
        t = secrets.token_hex(32)                                        # 32 bytes → 64 hex
        fd = os.open(TERM_TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(t)
        _TOKEN_CACHE["v"] = t
        return True
    except Exception:                                                    # noqa: BLE001
        return False


def _ip_allowed(ip):
    """回环 + 指定局域网网段放行; 其它一律不放行"""
    if not ip:
        return False
    if ip in ("::1", "::ffff:127.0.0.1") or ip.startswith("127."):
        return True
    if ip.startswith("::ffff:"):
        ip = ip[len("::ffff:"):]
    return any(ip.startswith(p) for p in ALLOWED_NET_PREFIX)


def _instr_size():
    try:
        return os.path.getsize(INSTR_LOG)
    except OSError:
        return -1


def _term_hint(snap, paused, peers):
    """一行中文现状 (给终端直接念给用户)"""
    st = snap.get("stage") or "未上报"
    age = snap.get("frame_age_s")
    try:
        agetxt = ("%.0fs 前" % float(age)) if float(age) >= 0 else "无真机帧"
    except Exception:                                                    # noqa: BLE001
        agetxt = "无真机帧"
    ly = snap.get("layers") or {}
    off = [k for k, v in ly.items()
           if str((v or {}).get("status") if isinstance(v, dict) else v) != "active"]
    pn = ", ".join(str(p.get("name")) for p in peers) or "无"
    return ("阶段=%s · 真机帧 %s · 分层%s · 在线 peer: %s · %s"
            % (st, agetxt, ("全绿" if not off else ("离线:" + "/".join(off))), pn,
               ("已暂停" if paused else "运行中")))


def _term_layers(snap):
    """把 snapshot.layers 的 dict 压成 {L2:"active", ...} (终端要一眼看懂的形态)"""
    out = {}
    for k, v in (snap.get("layers") or {}).items():
        out[k] = (v.get("status") if isinstance(v, dict) else v)
    return out


def _snapshot(force=False):
    """带 2s 缓存的快照 (手机上页面 2~3 秒刷一次, 不必每次重算)"""
    with _LOCK:
        if not force and _LAST["snap"] and (time.time() - _LAST["ts"]) < 2.0:
            return _LAST["snap"]
    try:
        snap = HB.build_snapshot()["snapshot"]
    except Exception as e:                                          # noqa: BLE001
        snap = {"error": "%s: %s" % (type(e).__name__, str(e)[:160])}
    with _LOCK:
        _LAST["snap"] = snap
        _LAST["ts"] = time.time()
    return snap


def _recent_instructions(n=20):
    out = []
    try:
        with open(INSTR_LOG, encoding="utf-8") as f:
            lines = f.readlines()[-n:]
        for ln in lines:
            try:
                out.append(json.loads(ln))
            except Exception:                                       # noqa: BLE001
                pass
    except Exception:                                               # noqa: BLE001
        pass
    return out


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "zmax-hil-local/1.0"

    def log_message(self, format, *args):  # noqa: A002                                  # 静音
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Zmax-Term")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _q(self):
        try:
            return urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        except Exception:                                            # noqa: BLE001
            return {}

    def _term_guard(self):
        """终端接口门控: 网段 + token。放行返回 True; 否则已回 403(且**未改任何状态**)。

        顺序: 先判来源网段, 再判 token。任一不过 → 403, 不做任何写/计算副作用。
        """
        ip = (self.client_address[0] if self.client_address else "") or ""
        if not _ip_allowed(ip):
            self._send({"ok": 0, "err": "forbidden: source %s not allowed" % ip}, 403)
            return False
        tok = self.headers.get("X-Zmax-Term") or ""
        want = _term_token()
        if not want or not tok or not hmac.compare_digest(tok, want):
            self._send({"ok": 0, "err": "forbidden: bad or missing X-Zmax-Term"}, 403)
            return False
        return True

    def do_OPTIONS(self):                                            # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):                                                # noqa: N802
        p = self.path.split("?")[0].rstrip("/") or "/"
        if p == "/health":
            return self._send({"ok": 1, "hil": "local", "port": PORT, "reports": REPORTS})
        if p in ("/", "/hil/state", "/hil"):
            s = _snapshot()
            return self._send({"ok": 1, "ts": time.strftime("%F %T"),
                               "pause": os.path.isfile(PAUSE_FLAG),
                               "instructions": _recent_instructions(),
                               "snapshot": s})
        # ───────── 终端接口 (需要 token + 网段) ─────────
        if p == "/hil/term/state":
            if not self._term_guard():
                return
            s = _snapshot()
            paused = os.path.isfile(PAUSE_FLAG)
            peers = HB.peers_alive(TERM_TTL)
            return self._send({
                "ok": True, "ts": time.strftime("%F %T"),
                "stage": s.get("stage"), "frame_age_s": s.get("frame_age_s"),
                "layers": _term_layers(s), "canvas": s.get("canvas") or {},
                "paused": paused, "peers": peers,
                "last_instructions": _recent_instructions(5),
                "verbs": VERBS,
                "hint": _term_hint(s, paused, peers),
            })
        if p == "/hil/term/log":
            if not self._term_guard():
                return
            try:
                n = int((self._q().get("n") or ["20"])[0])
            except Exception:                                        # noqa: BLE001
                n = 20
            n = max(1, min(n, 200))
            items = _recent_instructions(n)
            return self._send({"ok": True, "n": len(items), "items": items,
                               "source": "reports/hil_instructions.jsonl"})
        if p == "/hil/term/peers":
            if not self._term_guard():
                return
            return self._send({"ok": True, "ttl": TERM_TTL, "peers": HB.peers_alive(TERM_TTL)})
        return self._send({"ok": 0, "err": "no route %s" % p}, 404)

    def do_POST(self):                                               # noqa: N802
        p = self.path.split("?")[0].rstrip("/") or "/"
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n).decode() or "{}")
        except Exception:                                           # noqa: BLE001
            body = {}
        if p in ("/hil/say", "/say"):
            text = (body.get("text") or "").strip()
            if not text:
                return self._send({"ok": 0, "err": "空指示"}, 400)
            snap = _snapshot()
            try:
                reply, verdict = HB.handle_instruction(text, snap)
            except Exception as e:                                  # noqa: BLE001
                return self._send({"ok": 0, "err": "%s: %s" % (type(e).__name__, str(e)[:160])}, 500)
            return self._send({"ok": 1, "ts": time.strftime("%F %T"), "text": text,
                               "reply": reply, "verdict": verdict})
        # ───────── 终端接口 (需要 token + 网段) ─────────
        if p == "/hil/term/say":
            if not self._term_guard():
                return
            text = (body.get("text") or "").strip()
            if not text:
                return self._send({"ok": 0, "err": "空指示"}, 400)
            seq = body.get("seq", 0)
            frm = str(body.get("from") or "hermes")
            snap = _snapshot()
            before = _instr_size()
            try:
                reply, verdict = HB.handle_instruction(text, snap)     # 原样调用(红线在服务端)
            except Exception as e:                                  # noqa: BLE001
                return self._send({"ok": 0, "err": "%s: %s" % (type(e).__name__, str(e)[:160])}, 500)
            # 动作类: handle_instruction 已返回 refused_motion 并记账; 其它裁决(如 status)大脑不落盘
            # ⇒ 此处补一条终端台账, 保证"每次终端 say 都留流水"。仅补, 不覆盖大脑记录。
            if _instr_size() <= before:
                app = getattr(HB, "_append_instruction", None)
                if callable(app):
                    app({"ts": time.strftime("%F %T"), "text": text, "verdict": verdict,
                         "from": frm, "seq": seq, "via": "term"})
            return self._send({"ok": True, "verdict": verdict, "reply": reply, "seq": seq,
                               "wrote_to": os.path.relpath(INSTR_LOG, ROOT)})
        if p == "/hil/term/peer":
            if not self._term_guard():
                return
            name = (body.get("name") or "").strip()
            if not name:
                return self._send({"ok": 0, "err": "缺 name"}, 400)
            rec = HB.register_peer(name, body.get("kind") or "", pid=body.get("pid"),
                                   note=body.get("note") or "", ttl=TERM_TTL)
            return self._send({"ok": True, "peer": rec, "peers": HB.peers_alive(TERM_TTL)})
        return self._send({"ok": 0, "err": "no route %s" % p}, 404)


def main():
    _ready = _term_token_ensure()                       # 启动即确保 token 就绪(鉴权请求永不触发写)
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    print("🙋 HIL 本地 API 在听 0.0.0.0:%d (同一个大脑: %s)" % (PORT, HB.__file__), flush=True)
    print("🔑 终端门控 token: %s (%s; 取值: cat 该文件 · 绝不入日志)"
          % (os.path.relpath(TERM_TOKEN_FILE, ROOT),
             "0600 已就绪" if _ready else "⚠️ 生成失败"), flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
