#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🥇 DAP 断点实探: attach 到 5678, 在 execution.py:111 设断点, 验证真的停住并读参数。

用途: 不依赖人工在 VSCode 里点, 一条命令证明「断点能进」。
前置: tools/run_canvas_loop_debug.sh 已在跑 (debugpy --listen 127.0.0.1:5678)。

用法: ./gui-venv311/bin/python tools/dap_probe_breakpoint.py
"""
import json
import socket
import sys
import time

HOST = "127.0.0.1"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 5678
PATH = "/home/ubuntu/zmax/src/lerobot/policies/left_right/state_space/execution.py"
LINE = 111

s = socket.create_connection((HOST, PORT), timeout=20)
s.settimeout(25)
_buf = b""
_seq = [0]


def send(cmd, args):
    _seq[0] += 1
    body = json.dumps({"seq": _seq[0], "type": "request", "command": cmd,
                       "arguments": args}).encode()
    s.sendall(b"Content-Length: %d\r\n\r\n" % len(body) + body)
    return _seq[0]


def recv():
    global _buf
    while b"\r\n\r\n" not in _buf:
        d = s.recv(65536)
        if not d:
            return None
        _buf += d
    head, rest = _buf.split(b"\r\n\r\n", 1)
    n = int([ln for ln in head.split(b"\r\n")
             if ln.lower().startswith(b"content-length")][0].split(b":")[1])
    while len(rest) < n:
        d = s.recv(65536)
        if not d:
            return None
        rest += d
    body, _buf = rest[:n], rest[n:]
    m = json.loads(body)
    print("   [<-] %s %s%s" % (m.get("type"), m.get("event") or m.get("command") or "",
                               "" if m.get("success") is None else " success=%s" % m["success"]))
    return m


def wait_response(rid, timeout=40):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            s.settimeout(max(1.0, timeout - (time.time() - t0)))
            m = recv()
        except socket.timeout:
            return None
        if m is None:
            return None
        if m.get("type") == "response" and m.get("request_seq") == rid:
            return m
    return None


r = send("initialize", {"adapterID": "python", "pathFormat": "path",
                        "linesStartAt1": True, "columnsStartAt1": True,
                        "supportsVariableType": True, "clientID": "zmax-probe"})
print("initialize →", (wait_response(r) or {}).get("success"))
r = send("attach", {"justMyCode": False})
print("attach     →", (wait_response(r) or {}).get("success"))
r = send("setBreakpoints", {"source": {"path": PATH, "name": "execution.py"},
                           "breakpoints": [{"line": LINE}]})
resp = wait_response(r) or {}
bps = (resp.get("body") or {}).get("breakpoints") or []
print("setBreakpoints →", resp.get("success"), bps)
if not bps or not bps[0].get("verified"):
    print("❌ 断点未被接受 (文件路径/行号不匹配)")
    s.close()
    sys.exit(1)
r = send("configurationDone", {})
print("configurationDone →", (wait_response(r) or {}).get("success"))

print("⏳ 等断点命中 (循环 10Hz, 最多 25s) …")
stopped, t0 = None, time.time()
while time.time() - t0 < 25:
    m = recv()
    if m is None:
        break
    if m.get("type") == "event" and m.get("event") == "stopped":
        stopped = m
        break
if not stopped:
    print("❌ 25s 内没有停在 %s:%d" % (PATH, LINE))
    s.close()
    sys.exit(2)

tid = (stopped.get("body") or {}).get("threadId")
print("✅ 停住了 · reason=%s · threadId=%s" % ((stopped.get("body") or {}).get("reason"), tid))

r = send("stackTrace", {"threadId": tid, "startFrame": 0, "levels": 8})
st = (wait_response(r) or {}).get("body") or {}
frames = st.get("stackFrames") or []
print("--- 调用栈 (证明是谁在调它) ---")
for f in frames:
    print("  %-42s %s:%s" % (f.get("name"), (f.get("source") or {}).get("name"), f.get("line")))
if frames:
    fid = frames[0].get("id") or frames[0].get("frameId")
    for expr in ("u.tolist()", "self.max_rate", "self._LIMIT", "a.shape"):
        r = send("evaluate", {"expression": expr, "frameId": fid, "context": "watch"})
        b = (wait_response(r) or {}).get("body") or {}
        print("  %-16s = %s" % (expr, b.get("result")))

send("disconnect", {"terminateDebuggee": False})
time.sleep(0.5)
s.close()
print("✅ 探针退出 (调试进程继续跑)")
