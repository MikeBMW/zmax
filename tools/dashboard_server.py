#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dashboard_server.py — 本机只读静态服务(默认 :8799), 给「统一 web 页 + 数据 + 交付 APK」一个稳定下载/打开入口。

为什么单开一个端口: 现场主服务 (cam_live_stream.py :8791) 是在役推流服务, 改它要重启 ⇒ 会打断
正在看的画面。本服务只读、零依赖、可随时起停, 与在役链路互不影响。

暴露(白名单, 只读):
  GET /                    → tools/web/unified_app.html      (统一大屏页)
  GET /unified_app.html    → 同上
  GET /dashboard.json      → tools/web/dashboard.json        (与大屏页同目录, 供 fetch)
  GET /dash.json           → 同上
  GET /dl/<file>           → tools/web/dl/<file>             (交付件下载, 含 APK)
  GET /api/services        → 标准服务汇总 (端口探活 + 本机实跑端口; 页面首屏表格用)
其余路径一律 404(不目录遍历)。

/api/services 设计口径 (老倪: 「8799 不是总的产品服务么? 怎么没有汇总?」):
  · 清单是**内置常量** (不改目录结构, 不读别的脚本), 只描述「谁该在哪个端口上」;
  · 真伪靠**实探**: TCP 连通 = 在跑, 再补一个 HTTP GET 取 http_code / version / uptime;
  · 并发探测, 每项 ≤1.5s, 整体 ≤4s (ThreadPoolExecutor + 独立 deadline);
  · 对端 (Intel 550C / Orin / 工控机) 与「本机」分开统计, 页面汇总行才能区分
    「未起」和「对端不可达」。

用法: python3 tools/dashboard_server.py [--port 8799] [--host 0.0.0.0]
红线: 只读; 不打印/不外泄任何凭据(这里本就不读凭据); 探测只发 GET, 不发任何写请求。
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
WEB = os.path.join(_HERE, "web")
DL = os.path.join(WEB, "dl")

CT = {".html": "text/html; charset=utf-8", ".json": "application/json; charset=utf-8",
      ".apk": "application/vnd.android.package-archive", ".png": "image/png",
      ".jpg": "image/jpeg", ".svg": "image/svg+xml",
      ".js": "application/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}


def _ctype(path: str) -> str:
    return CT.get(os.path.splitext(path)[1].lower(), "application/octet-stream")


# ═════════════════ 标准服务清单 (端口 → 脚本 → 所在机器) ═════════════════
# 只描述「应该有什么」, 不代表「现在活着」—— 活没活由 _probe() 实探。
# 机器表: local=本机, intel=Intel 550C 192.168.23.70, orin=Orin 192.168.23.66,
#         ipc=工控机 192.168.23.23
MACHINES = {
    "local": {"label": "本机", "short": "本机", "ip": "127.0.0.1"},
    "intel": {"label": "Intel 550C (192.168.23.70)", "short": "Intel .70", "ip": "192.168.23.70"},
    "orin": {"label": "Orin (192.168.23.66)", "short": "Orin .66", "ip": "192.168.23.66"},
    "ipc": {"label": "工控机 (192.168.23.23)", "short": "工控 .23", "ip": "192.168.23.23"},
}

# (名称, 端口, 脚本, 机器, 探活路径, 依赖硬件, 说明)
SERVICES = [
    # ── 本机 ──
    ("相机主推流 / media 基址", 8791, "cam_live_stream.py", "local", "/", True,
     "现场主推流, 与 8793 同一进程"),
    ("工位总览 / 相机", 8793, "cam_live_stream.py", "local", "/station/status", True,
     "工位页 + 多路相机总览"),
    ("AR 3D / 位姿", 8797, "tcp_ar_server.py", "local", "/", True,
     "AR 三维页 + 机械臂位姿"),
    ("产品大屏 (本页)", 8799, "dashboard_server.py", "local", "/dashboard.json", False,
     "只读静态大屏 + 服务汇总"),
    ("AR 场景渲染", 8802, "ar_scene_render_server.py", "local", "/video", False,
     "3D 场景 / 双臂渲染"),
    ("agent_hub", 8794, "agent_hub.py", "local", "/agent/log", False,
     "指令队列 / 智能体入口"),
    ("HIL 本地 API", 8795, "hil_local_api.py", "local", "/hil/state", False,
     "人机在环状态与指示"),
    ("相机小服务", 8789, "rs_service.py", "local", "/health", True,
     "RealSense 独占取流"),
    ("本地推理", 8790, "ss_local_infer_server.py", "local", "/health", False,
     "L2 本地推理"),
    ("peg 位姿", 8896, "peg_pose_server.py", "local", "/health", True,
     "D405 手眼位姿解算"),
    ("手臂 YOLO", 8898, "arm_yolo_stream.py", "local", "/healthz", True,
     "手臂相机 + 光模块框"),
    ("SE(3) 几何", 8815, "se3_geom_server.py", "local", "/", False,
     "分层几何看板"),
    ("CY 切面", 8810, "cy_slice_server.py", "local", "/", False,
     "六维 CY 切面看板"),
    ("L2 监视", 8820, "l2_watch_server.py", "local", "/", False,
     "L2 看板"),
    ("ws 聊天", 8765, "ws_chat_server.py", "local", "/", False,
     "网页聊天通道"),
    # ── 对端 ──
    ("3DGS 渲染", 8816, "gs_render_stream_intel.py", "intel", "/", True,
     "高斯泼溅渲染 (Intel)"),
    ("cam relay", 8901, "cam relay (Intel)", "intel", "/", True,
     "相机中继 (Intel)"),
    ("Orin 取流", 8792, "orin_mjpeg_server.py", "orin", "/status", True,
     "臂上 D405 取流 (Orin)"),
    ("AOI 金手指", 10082, "工控机 AOI 服务", "ipc", "/last_result", True,
     "金手指检测触发 (工控机)"),
    ("AOI 表面", 10083, "工控机 AOI 服务", "ipc", "/last_result", True,
     "表面检测触发 (工控机)"),
]

# 本机「清单外实跑端口」的扫描范围 (发现没登记的监听者, 只做 TCP 连通判断)
SCAN_RANGES = [(8760, 8831), (8890, 8901)]

PROBE_TIMEOUT = 1.5      # 单项总预算 (TCP 连通 + HTTP 取码)
API_TTL = 2.0            # /api/services 结果缓存秒数 (页面 15s 刷一次, 防抖)

_cache = {"ts": 0.0, "payload": None}
_cache_lock = threading.Lock()


# ═════════════════ 探活小工具 (只用 socket, 不引第三方库) ═════════════════
def _tcp_open(ip: str, port: int, timeout: float) -> bool:
    """TCP 是否可连 —— 判定「在跑」的唯一依据 (不依赖 HTTP 语义)。"""
    try:
        with socket.create_connection((ip, port), timeout):
            return True
    except OSError:
        return False


def _http_get(ip: str, port: int, path: str, timeout: float):
    """极简 HTTP/1.0 GET: 返回 (code, body)。只读前 8KB, 流式端点也能立刻断开。"""
    if not path.startswith("/"):
        path = "/" + path
    req = ("GET %s HTTP/1.0\r\nHost: %s:%d\r\nUser-Agent: zmax-dash-probe\r\n"
           "Accept: */*\r\nConnection: close\r\n\r\n" % (path, ip, port))
    s = socket.create_connection((ip, port), timeout)
    buf = b""
    try:
        s.sendall(req.encode("latin-1"))
        while len(buf) < 8192:
            try:
                chunk = s.recv(4096)
            except (socket.timeout, OSError):
                break
            if not chunk:
                break
            buf += chunk
    finally:
        try:
            s.close()
        except OSError:
            pass
    head, _, body = buf.partition(b"\r\n\r\n")
    code = 0
    parts = head.split(b"\r\n", 1)[0].split()
    if len(parts) >= 2 and parts[1].isdigit():
        code = int(parts[1])
    return code, body


def _human_dur(sec: float) -> str:
    """>=秒 → 人读时长 (3h12m / 45m / 12s)。"""
    try:
        sec = int(float(sec))
    except (TypeError, ValueError):
        return "?"
    if sec < 0:
        return "?"
    if sec < 60:
        return "%ds" % sec
    if sec < 3600:
        return "%dm%02ds" % (sec // 60, sec % 60)
    if sec < 86400:
        return "%dh%02dm" % (sec // 3600, (sec % 3600) // 60)
    return "%dd%02dh" % (sec // 86400, (sec % 86400) // 3600)


def _json_hints(body: bytes):
    """从小 JSON (/health · /status) 里挖 version / uptime。非 JSON 就返回 (None, None)。"""
    ver = up = None
    if not body.lstrip()[:1] == b"{":
        return ver, up
    try:
        d = json.loads(body.decode("utf-8", "ignore").rstrip("\x00 \r\n"))
    except (ValueError, UnicodeDecodeError):
        return ver, up
    if not isinstance(d, dict):
        return ver, up
    for k in ("version", "ver", "build", "app_version"):
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            ver = v.strip()
            break
    for k in ("uptime_s", "uptime", "uptime_sec", "up_s"):
        v = d.get(k)
        if isinstance(v, (int, float)):
            up = "已运行 " + _human_dur(v)
            break
    if up is None:
        for k in ("started_at", "start_ts", "start_time"):
            v = d.get(k)
            if v:
                up = "起于 %s" % v
                break
    return ver, up


def _local_version():
    """本机部署版本 (VERSION.txt 首行, 如 v5.50.785)。只给「本机」服务兜底用。"""
    try:
        with open(os.path.join(ROOT, "VERSION.txt"), encoding="utf-8", errors="ignore") as fh:
            first = fh.readline().strip()
        return first.split()[0] if first else None
    except OSError:
        return None


# ═════════════════ 单项探测 ═════════════════
def _probe(svc: dict, local_ver: "str | None" = None, pid=None) -> dict:
    """探一个服务: TCP 连通 → (若通) HTTP 取码/版本/uptime。单项总耗时 ≤ PROBE_TIMEOUT。"""
    t0 = time.time()
    ip, port = svc["ip"], svc["port"]
    listening = _tcp_open(ip, port, PROBE_TIMEOUT)
    code, ver, up = None, None, None
    if listening:
        remain = max(0.3, PROBE_TIMEOUT - (time.time() - t0))
        try:
            code, body = _http_get(ip, port, svc.get("probe") or "/", remain)
            ver, up = _json_hints(body)
        except OSError:
            code = None          # 能连上但不说 HTTP (裸 TCP 端点) ⇒ 只报「在跑」
    is_local = svc["machine"] == "local"
    if ver is None and is_local:
        ver = local_ver            # 本机服务都出自同一份部署, 兜底用 VERSION.txt
    if up is None and is_local and pid:
        st = _proc_start_epoch(pid)                 # 服务自己不报 uptime ⇒ 用进程启动时刻算
        if st:
            up = "已运行 " + _human_dur(time.time() - st)
    item = {
        "name": svc["name"],
        "port": port,
        "script": svc["script"],
        "machine": svc["machine_label"],
        "machine_short": svc["machine_short"],
        "host_ip": ip,
        "is_local": is_local,
        "listening": bool(listening),
        "state": "up" if listening else "down",
        "pid": pid if listening else None,
        "http_code": code,
        "version": ver,
        "uptime_hint": up,
        "depends_on_hardware": bool(svc["depends_on_hardware"]),
        "note": svc["note"],
        "probe_path": svc.get("probe"),
        "discovered": False,
    }
    return item


def _catalog():
    """把 SERVICES 常量展开成带机器标签的 dict 列表。"""
    out = []
    for name, port, script, mkey, probe, hw, note in SERVICES:
        m = MACHINES.get(mkey, MACHINES["local"])
        out.append({"name": name, "port": port, "script": script, "machine": mkey,
                    "machine_label": m["label"], "machine_short": m["short"],
                    "ip": m["ip"], "probe": probe, "depends_on_hardware": hw, "note": note})
    return out


def _netstat_listeners(ports):
    """本机 LISTENING 端口 → pid (netstat 快照)。给「在监听但 TCP 连不上」的端口做交叉验证。
    Windows/Linux 都认 (GREP 用 'LISTENING' / 'LISTEN')。失败返回 {}。"""
    out = {}
    try:
        import subprocess
        _si = None
        if os.name == "nt":
            _si = subprocess.STARTUPINFO()
            _si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            _si.wShowWindow = 0
        txt = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True,
                             timeout=2.0, text=True, errors="ignore",
                             creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0),
                             startupinfo=_si).stdout
    except Exception:                                                 # noqa: BLE001
        return out
    for line in txt.splitlines():
        f = line.split()
        if len(f) < 4 or not (f[-2] == "LISTENING" or "LISTEN" in f):
            continue
        local = f[1]
        if ":" not in local:
            continue
        try:
            port = int(local.rsplit(":", 1)[1])
        except ValueError:
            continue
        if port in ports:
            pid = f[-1] if f[-1].isdigit() else None
            out[port] = pid
    return out


def _proc_start_epoch(pid):
    """本机进程启动时刻 (epoch 秒) —— ctypes 直取, 不引 psutil、不起子进程。失败返回 None。"""
    if not pid or sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, int(pid))       # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return None
        try:
            ct, et, kt, ut = (wintypes.FILETIME() for _ in range(4))
            if not k32.GetProcessTimes(h, ctypes.byref(ct), ctypes.byref(et),
                                       ctypes.byref(kt), ctypes.byref(ut)):
                return None
            ticks = (ct.dwHighDateTime << 32) | ct.dwLowDateTime
            return ticks / 1e7 - 11644473600.0             # FILETIME(1601) → Unix epoch
        finally:
            k32.CloseHandle(h)
    except Exception:                                                  # noqa: BLE001
        return None


def _scan_extra(known_ports, listen_ports=None, local_ip="127.0.0.1"):
    """本机「清单外实跑端口」: 只捞监听中的, 标 discovered。
    ① TCP 能连上 ⇒ 未登记服务; ② netstat 说在监听但连不上 ⇒ 记「挂起」, 供排障。"""
    cand = []
    for lo, hi in SCAN_RANGES:
        cand.extend(p for p in range(lo, hi) if p not in known_ports)

    def chk(p):
        return p if _tcp_open(local_ip, p, 0.35) else None

    found, alive = [], set()
    if cand:
        with ThreadPoolExecutor(max_workers=48) as ex:
            for p in ex.map(chk, cand):
                if p:
                    alive.add(p)
    if listen_ports is None:
        listen_ports = _netstat_listeners(set(cand)) if cand else {}
    else:
        cs = set(cand)
        listen_ports = {p: v for p, v in listen_ports.items() if p in cs}   # 只留清单外候选

    def mk(p, note, up, state="up"):
        return {
            "name": "未登记服务 (自动发现)",
            "port": p,
            "script": "?",
            "machine": MACHINES["local"]["label"],
            "machine_short": MACHINES["local"]["short"],
            "host_ip": local_ip,
            "is_local": True,
            "listening": state == "up",
            "state": state,
            "http_code": None,
            "version": None,
            "uptime_hint": up,
            "depends_on_hardware": False,
            "note": note,
            "probe_path": None,
            "discovered": True,
        }

    for p in sorted(alive):
        pid = listen_ports.get(p)
        found.append(mk(p, "清单外监听端口, 建议登记到 SERVICES",
                        ("pid %s" % pid) if pid else None))
    for p, pid in sorted(listen_ports.items()):
        if p in alive:
            continue
        found.append(mk(p, "端口在监听但 TCP 连不上 (accept 挂起 / 防火墙)",
                        ("pid %s" % pid) if pid else None, state="wedged"))
    return found


def build_services_payload():
    """汇总: 清单全量 + 本机实跑端口, 并发探测 (整体 ≤4s)。2s 内复用缓存。"""
    now = time.time()
    with _cache_lock:
        if _cache["payload"] and (now - _cache["ts"]) < API_TTL:
            return _cache["payload"]

    t0 = time.time()
    local_ver = _local_version()
    cat = _catalog()
    # 一次 netstat 快照: 拿本机「端口→pid」(给 uptime 与「在监听但连不上」用), 约 150ms
    scan_ports = {p for lo, hi in SCAN_RANGES for p in range(lo, hi)}
    pid_map = _netstat_listeners(scan_ports | {s["port"] for s in cat if s["machine"] == "local"})
    items = []
    with ThreadPoolExecutor(max_workers=max(8, len(cat))) as ex:
        futs = [ex.submit(_probe, s, local_ver, pid_map.get(s["port"]) if s["machine"] == "local" else None)
                for s in cat]
        for f in futs:
            try:
                items.append(f.result(timeout=PROBE_TIMEOUT + 1.0))
            except Exception as e:                                    # noqa: BLE001
                items.append({"name": "?", "port": 0, "script": "?", "listening": False,
                              "state": "down", "machine": "本机", "machine_short": "本机",
                              "is_local": True, "pid": None,
                              "http_code": None, "version": None, "uptime_hint": None,
                              "depends_on_hardware": False, "note": "探测异常: %s" % e,
                              "probe_path": None, "discovered": False})

    # 本机清单外实跑端口 (预算 1.2s, 扫不到就跳过, 不拖累整体)
    try:
        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(_scan_extra, {i["port"] for i in items if i.get("is_local")}, pid_map)
            items.extend(fut.result(timeout=1.2))
    except Exception:                                                 # noqa: BLE001
        pass

    items.sort(key=lambda it: (0 if it.get("is_local") else 1, it["port"]))

    up = sum(1 for it in items if it.get("state") == "up")
    wedged = sum(1 for it in items if it.get("state") == "wedged")
    down_local = sum(1 for it in items if it.get("state") == "down" and it.get("is_local"))
    remote_down = sum(1 for it in items if it.get("state") == "down" and not it.get("is_local"))
    payload = {
        "schema": "zmax-services/1",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "generated_at_epoch": time.time(),
        "elapsed_ms": int((time.time() - t0) * 1000),
        "local_version": local_ver,
        "summary": {
            "total": len(items),
            "listening": up,
            "wedged": wedged,
            "down_local": down_local,
            "remote_unreachable": remote_down,
        },
        "items": items,
    }
    with _cache_lock:
        _cache["ts"] = time.time()
        _cache["payload"] = payload
    return payload


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def handle(self):
        """浏览器关标签/超时会把 keep-alive 连接掐掉 ⇒ BaseHTTPRequestHandler 会刷一屏
        ConnectionAbortedError 堆栈。这里吞掉这三种「对端正常断开」的噪声, 别的异常照常抛。"""
        try:
            super().handle()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            self.close_connection = True

    def _send(self, code, ctype, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:                                                       # noqa: BLE001
            pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._send(code, "application/json; charset=utf-8", body)

    def do_GET(self):
        p = self.path.split("?", 1)[0]
        if p in ("/api/services", "/api/services.json"):
            try:
                self._json(build_services_payload())
            except Exception as e:                                              # noqa: BLE001
                self._json({"schema": "zmax-services/1", "error": str(e)}, 500)
            return
        if p in ("/", "/unified_app.html", "/dash", "/dash.html"):
            fp = os.path.join(WEB, "unified_app.html")
        elif p in ("/dashboard.json", "/dash.json"):
            fp = os.path.join(WEB, "dashboard.json")
        elif p.startswith("/dl/"):
            fn = os.path.basename(p[len("/dl/"):])         # basename ⇒ 路径穿不出去
            fp = os.path.join(DL, fn)
        else:
            self._send(404, "text/plain; charset=utf-8", b"not found")
            return
        if not os.path.isfile(fp):
            self._send(404, "text/plain; charset=utf-8", ("missing: %s" % os.path.basename(fp)).encode())
            return
        try:
            with open(fp, "rb") as fh:
                self._send(200, _ctype(fp), fh.read())
        except Exception as e:                                                  # noqa: BLE001
            self._send(500, "text/plain; charset=utf-8", str(e).encode())


def main():
    ap = argparse.ArgumentParser(description="只读大屏静态服务")
    ap.add_argument("--port", type=int, default=8799)
    ap.add_argument("--host", default="0.0.0.0")
    a = ap.parse_args()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print("dashboard_server: http://%s:%d/  (web=%s)" % (a.host, a.port, WEB), flush=True)
    print("dashboard_server: /api/services 就绪 (清单 %d 项)" % len(SERVICES), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
