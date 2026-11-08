#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""local_services.py — 让 Windows(冻结)版自己带起本机微型服务。

老倪 2026-11-08: 「你自己安装, 自己开产品大屏服务, 自己开 ar3d 服务 … 我要一个完整功能的
windows 版本, 不能缺少功能」

为什么需要它: 这两个服务在产线上是常驻进程 (8799 产品大屏 / 8797 AR 3D), 冻结包里没有它们
⇒ 笔记本上点按钮要么打不开、要么只剩公网(已死)。冻结包自带一个真 Python 解释器
(`sys.executable` 就是控制台 exe, 入口 `_run_helper_script_if_any()` 支持 `exe <脚本.py>`),
所以可以直接把这两个 stdlib-only 脚本当子进程拉起来, 不依赖机器上装没装 Python。

用法(界面侧):
    from local_services import ensure
    ok, why = ensure("dashboard_server.py", 8799)     # 没起就起, 起完等端口
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time

__all__ = ["ensure", "find_script", "port_open", "stop", "status"]


def _meipass() -> str:
    return getattr(sys, "_MEIPASS", "") or ""


def _install_root() -> str:
    """安装根 (exe 所在目录的上一级 / 源码仓库根)。"""
    mp = _meipass()
    if mp:
        return os.path.dirname(mp)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _log_dir() -> str:
    d = os.path.join(os.path.expanduser("~"), "zmax", "zmax_data", "logs")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:                                                   # noqa: BLE001
        d = os.path.join(_install_root(), "logs")
        os.makedirs(d, exist_ok=True)
    return d


def find_script(name: str) -> str:
    """在包里 / 安装目录 / 源码仓库里找 tools/<name>。"""
    name = os.path.basename(name)
    cands = []
    mp = _meipass()
    if mp:
        cands.append(os.path.join(mp, "tools", name))
    root = _install_root()
    cands.append(os.path.join(root, "tools", name))
    cands.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "tools", name))
    cands.append(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "tools", name))
    for p in cands:
        if p and os.path.isfile(p):
            return p
    return ""


def port_open(port: int, host: str = "127.0.0.1", tmo: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=tmo):
            return True
    except Exception:                                                   # noqa: BLE001
        return False


def status(port: int) -> dict:
    return {"port": int(port), "up": port_open(port)}


def _lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:                                                   # noqa: BLE001
        return "127.0.0.1"


def station_candidates() -> list:
    """「产品大屏」= 8793 的 /station 站点页 (与主脑那台机器一模一样的那套)。

    老倪 2026-11-08: 「小静静打开的产品大屏错了, 不是 8799 服务, 应该是跟静静一样的
    http://192.168.1.7:8793/station 服务」 —— 8799 只是本机静态大屏页(无相机), 现场要看的是
    8793 的 6 路同屏 + 手动控制区, 所以默认必须走 station。

    顺序: 环境变量 ZMAX_STATION_URL / ZMAX_DASHBOARD_URL > config/ui/station_hosts.json
          > config/ui/dashboard_hosts.json > 本机 127.0.0.1:8793 > 公网。
    主机可以写 "ip:port" 或整条 URL; 路径统一补 /station。
    """
    out = []

    def _add(u: str):
        u = (u or "").strip()
        if not u:
            return
        if not u.lower().startswith("http"):
            u = "http://" + u
        _rest = u.split("//", 1)[-1]
        _has_path = "/" in _rest          # 只有"裸主机"才补 /station; 已带路径的 URL 原样用
        if not _has_path:
            u = u.rstrip("/") + "/station"
        if u not in out:
            out.append(u)

    _add(os.environ.get("ZMAX_STATION_URL", ""))
    _add(os.environ.get("ZMAX_DASHBOARD_URL", ""))
    root = os.environ.get("ZMAX_ROOT") or os.path.join(os.path.expanduser("~"), "zmax")
    for fn in ("station_hosts.json", "dashboard_hosts.json"):
        p = os.path.join(root, "config", "ui", fn)
        if not os.path.isfile(p):
            continue
        try:
            import json as _json
            with open(p, encoding="utf-8") as f:
                raw = _json.load(f)
            for h in ((raw.get("hosts") if isinstance(raw, dict) else raw) or []):
                _add(str(h))
        except Exception:                                               # noqa: BLE001
            pass
    _add("127.0.0.1:8793")
    _add("https://datadrive.world/factory-dashboard.html")
    return out


def station_url(timeout: float = 1.2, fallback: bool = True) -> str:
    """探活后返回第一个通的「产品大屏」地址。

    fallback=True: 全都不通也返回首选(让浏览器自己报错) —— 给"点了必须有点反应"的按钮用;
    fallback=False: 全都不通返回 ""(调用方自己去走下一档, 例: 本机 8799 静态页)。
    """
    cands = station_candidates()
    for u in cands:
        try:
            host = u.split("//", 1)[-1].split("/", 1)[0]
            h, _, p = host.partition(":")
            port = int(p) if p else (443 if u.startswith("https") else 80)
            with socket.create_connection((h, port), timeout=timeout):
                return u
        except Exception:                                               # noqa: BLE001
            continue
    if not fallback:
        return ""
    return cands[0] if cands else "http://127.0.0.1:8793/station"


def ensure(name: str, port: int, timeout: float = 15.0, extra=()) -> tuple:
    """确保 tools/<name> 在 port 上跑着。返回 (ok, 说明)。绝不抛异常。"""
    try:
        if port_open(port):
            return True, "已在运行 (127.0.0.1:%d)" % port
        script = find_script(name)
        if not script:
            return False, "包里没有 tools/%s" % name
        log = os.path.join(_log_dir(), "svc_%d.log" % port)
        fh = open(log, "ab", buffering=0)
        fh.write(("\n===== %s 启动 %s -> :%d =====\n"
                  % (time.strftime("%F %T"), script, port)).encode("utf-8", "replace"))
        cmd = [sys.executable, script] + [str(x) for x in extra]
        kw = dict(cwd=os.path.dirname(os.path.dirname(script)), stdin=subprocess.DEVNULL,
                  stdout=fh, stderr=subprocess.STDOUT)
        if os.name == "nt":
            kw["creationflags"] = 0x08000000          # CREATE_NO_WINDOW: 不弹黑框
        subprocess.Popen(cmd, **kw)
        t0 = time.time()
        while time.time() - t0 < float(timeout):
            if port_open(port):
                return True, "已拉起 %s (127.0.0.1:%d)" % (name, port)
            time.sleep(0.25)
        return False, "%s 起了但 %ss 内端口 %d 没通 (日志 %s)" % (name, int(timeout), port, log)
    except Exception as e:                                              # noqa: BLE001
        return False, "拉起 %s 失败: %s: %s" % (name, type(e).__name__, e)


def stop(port: int) -> tuple:
    """按端口停 (仅自己拉起的子进程场景用)。"""
    try:
        if os.name == "nt":
            out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=15).stdout
            pids = set()
            for line in out.splitlines():
                if (":%d " % int(port)) in line and "LISTENING" in line.upper():
                    pids.add(line.split()[-1])
            for p in pids:
                subprocess.run(["taskkill", "/PID", p, "/F"], capture_output=True, timeout=15)
            return True, "已停 %d (pids=%s)" % (port, ",".join(sorted(pids)) or "-")
        return False, "仅实现 Windows 侧停止"
    except Exception as e:                                              # noqa: BLE001
        return False, "停止失败: %s: %s" % (type(e).__name__, e)
