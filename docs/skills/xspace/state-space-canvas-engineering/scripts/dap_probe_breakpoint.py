#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🥇 DAP 断点实探: attach 到已 listen 的 debugpy, 在指定文件:行设断点, 证明它真的停住。

为什么需要它: 「断点不进」时人只能在 IDE 里手点, 而你能不能交付取决于你有没有客观证据。
这个探针不依赖 IDE、不依赖人点, 一条命令回答三件事:
  ① 断点被接受了吗 (verified=true / false)
  ② 真停住了吗 (event stopped, reason=breakpoint)
  ③ 停的时候调用栈是谁在调它 (证明这条链真被执行, 不是看到的假象) + 现场变量值

前置: 被测进程必须已用 `python -m debugpy --listen 127.0.0.1:5678 <script>` 启动
     (scripts/run_canvas_loop_debug.sh 是这个形态的现成模板)。

用法:
  ./gui-venv311/bin/python scripts/dap_probe_breakpoint.py \
      --path /abs/repo/src/.../execution.py --line 111 [--port 5678] [--expr u.tolist()]

判读:
  verified=false          → 文件路径/行号不对 (多半行号漂了或是 def 行, 见 references §11)
  25s 无 stopped          → 断点所在代码这段没被执行 (进程错位, 见 references §10)
  stopped 但 evaluate 报错 → 变量在这一行还没赋值 (def 行/首句之前), 换行号
"""
import argparse
import json
import socket
import sys
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", required=True, help="被断文件的绝对路径 (必须与 co_filename 逐字相同)")
    ap.add_argument("--line", type=int, required=True, help="函数体第一行可执行语句的行号")
    ap.add_argument("--port", type=int, default=5678)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--wait", type=float, default=25.0, help="等断点命中的秒数")
    ap.add_argument("--expr", action="append", default=None,
                    help="停住后要求值的表达式 (可多次给; 默认 u.tolist() / self.max_rate)")
    a = ap.parse_args()

    exprs = a.expr or ["u.tolist()", "self.max_rate"]
    s = socket.create_connection((a.host, a.port), timeout=20)
    buf = b""
    seq = [0]

    def send(cmd, args):
        seq[0] += 1
        body = json.dumps({"seq": seq[0], "type": "request", "command": cmd,
                           "arguments": args}).encode()
        s.sendall(b"Content-Length: %d\r\n\r\n" % len(body) + body)
        return seq[0]

    def recv():
        nonlocal buf
        while b"\r\n\r\n" not in buf:
            d = s.recv(65536)
            if not d:
                return None
            buf += d
        head, rest = buf.split(b"\r\n\r\n", 1)
        n = int([ln for ln in head.split(b"\r\n")
                 if ln.lower().startswith(b"content-length")][0].split(b":")[1])
        while len(rest) < n:
            d = s.recv(65536)
            if not d:
                return None
            rest += d
        body, buf = rest[:n], rest[n:]
        return json.loads(body)

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

    # DAP 顺序: initialize → attach → setBreakpoints → configurationDone
    # 🔴 attach 的 response 会**晚于** setBreakpoints/configurationDone 才回来 (实测),
    #    不要因为 attach 暂时无响应就判定失败并退出 —— 继续往下发, 命中事件才算数。
    rid = send("initialize", {"adapterID": "python", "pathFormat": "path",
                              "linesStartAt1": True, "columnsStartAt1": True,
                              "supportsVariableType": True, "clientID": "dap-probe"})
    print("initialize  →", (wait_response(rid) or {}).get("success"))
    send("attach", {"justMyCode": False})
    rid = send("setBreakpoints", {"source": {"path": a.path},
                                  "breakpoints": [{"line": a.line}]})
    resp = wait_response(rid) or {}
    bps = (resp.get("body") or {}).get("breakpoints") or []
    print("setBkpts    →", resp.get("success"), bps)
    if not bps or not bps[0].get("verified"):
        print("❌ 断点未被接受: 路径或行号不匹配 (行号可能漂了; def 行参数未绑定, 要打函数体首句)")
        s.close()
        return 1
    send("configurationDone", {})

    print("⏳ 等命中 (最多 %.0fs) …" % a.wait)
    stopped, t0 = None, time.time()
    while time.time() - t0 < a.wait:
        m = recv()
        if m is None:
            break
        if m.get("type") == "event" and m.get("event") == "stopped":
            stopped = m
            break
    if not stopped:
        print("❌ 未命中: 这段代码在这个进程里没有执行 (先查进程错位, references §10)")
        s.close()
        return 2

    body = stopped.get("body") or {}
    tid = body.get("threadId")
    print("✅ 停住 · reason=%s · threadId=%s" % (body.get("reason"), tid))

    rid = send("stackTrace", {"threadId": tid, "startFrame": 0, "levels": 10})
    frames = ((wait_response(rid) or {}).get("body") or {}).get("stackFrames") or []
    print("--- 调用栈 (谁在调它) ---")
    for f in frames:
        src = (f.get("source") or {}).get("path") or (f.get("source") or {}).get("name")
        print("  %-28s %s:%s" % (f.get("name"), src, f.get("line")))

    if frames:
        # 🔴 DAP 的 StackFrame 字段名是 "id", 不是 "frameId" (后者只是 evaluate 的参数名)。
        fid = frames[0].get("id")
        for e in exprs:
            rid = send("evaluate", {"expression": e, "frameId": fid, "context": "watch"})
            r = wait_response(rid) or {}
            bd = r.get("body") or {}
            print("  %-16s = %s" % (e, bd.get("result") if r.get("success") else
                                     "<未定义/本行还没赋值>"))

    # 🔴 必须显式 disconnect(terminateDebuggee=False), 否则进程可能**停在断点上不恢复**,
    #    活真源(如 ar_cmd.json)停止更新, 用户看到的是「页面卡住了」。
    try:
        send("disconnect", {"terminateDebuggee": False})
        time.sleep(0.5)
    finally:
        s.close()
    print("✅ 探针退出 (被测进程继续跑)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
