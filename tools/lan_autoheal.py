#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""产线网卡自动接管：插上 USB 网卡 → 自动切 LAN 直连并恢复隧道；拔掉 → 自动切回 ECS/frp。

老倪 2026-10-25: 「那一会再连上 usb 网卡，你自己搞」⇒ 不依赖人操作，30s 内自愈。

判据（必须同时满足才切 LAN，宁可不切也不把好链路切坏）：
  ① 出现有线网卡(非 wlan/docker/veth/br) 且 carrier=1
  ② 该网卡上有 192.168.23.x 地址
  ③ ping 192.168.23.66 真通

切换动作：
  - 改 ~/.ssh/config 里 Host orin 的 HostName/Port（只有这一处，隧道 unit 用别名 orin）
  - 重启位姿桥 19061 / D405 8792 / Intel 8816 / Intel 8812 四个隧道
  - 写模式标记 + 日志；模式没变时只做健康检查，不动服务
"""
import os
import re
import socket
import subprocess
import time

HOME = os.path.expanduser("~")
CFG = os.path.join(HOME, ".ssh", "config")
MODE_F = os.path.join(HOME, ".hermes", "cache", "scratch", "lan_mode")
LOG = os.path.join(HOME, ".hermes", "cache", "scratch", "lan_autoheal.log")
UNITS = ["zmax-orin-sdk-fwd.service", "zmax-orin-d405-tunnel.service",
         "zmax-intel-gsrender-tunnel.service", "zmax-intel-cam-tunnel.service"]
LAN_IP, LAN_PORT = "192.168.23.66", "22"
ECS_IP, ECS_PORT = "39.102.211.79", "22022"


def say(msg):
    line = "[%s] %s" % (time.strftime("%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def run(cmd, timeout=20):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", "timeout")


def find_lan_iface():
    for name in sorted(os.listdir("/sys/class/net")):
        if name == "lo" or name.startswith(("wl", "docker", "veth", "br", "tap", "virbr")):
            continue
        d = "/sys/class/net/" + name
        try:
            if open(os.path.join(d, "carrier")).read().strip() != "1":
                continue
        except OSError:
            continue
        r = run("ip -o -4 addr show %s" % name, 8)
        if "192.168.23." in (r.stdout or ""):
            return name
    return None


def ping_ok(ip, wait=2):
    return run("ping -c1 -W%d %s" % (wait, ip), wait + 6).returncode == 0


def port_open(port, host="127.0.0.1"):
    s = socket.socket()
    s.settimeout(2)
    try:
        s.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def set_host_orin(ip, port):
    """只改 Host orin 段里的 HostName/Port，别的 Host 一律不碰。"""
    s = open(CFG, encoding="utf-8").read()
    m = re.search(r"(?m)^Host orin\n(?P<body>(?:(?!^Host ).*\n)*)", s)
    if not m:
        return False, "找不到 Host orin 段"
    body = m.group("body")
    nb = re.sub(r"(?m)^(\s*)HostName\s+\S+", r"\g<1>HostName " + ip, body, count=1)
    nb = re.sub(r"(?m)^(\s*)Port\s+\d+", r"\g<1>Port " + port, nb, count=1)
    if nb == body:
        return False, "HostName/Port 未变"
    open(CFG, "w", encoding="utf-8").write(s[:m.start("body")] + nb + s[m.end("body"):])
    return True, "%s:%s" % (ip, port)


def main():
    iface = find_lan_iface()
    want = "lan" if (iface and ping_ok(LAN_IP)) else "remote"
    try:
        cur = open(MODE_F, encoding="utf-8").read().strip()
    except OSError:
        cur = "remote"

    if want != cur:
        ok, detail = set_host_orin(*(LAN_IP, LAN_PORT) if want == "lan" else (ECS_IP, ECS_PORT))
        if not ok:
            say("⚠ 切 %s 失败: %s (网卡=%s)" % (want, detail, iface))
            return 1
        open(MODE_F, "w", encoding="utf-8").write(want)
        say("→ 切到 %s: Host orin = %s (网卡=%s)" % (want, detail, iface or "none"))
        run("sudo systemctl daemon-reload", 30)
        r = run("sudo systemctl restart %s" % " ".join(UNITS), 90)
        if r.returncode != 0:
            say("  ⚠ 重启隧道有非零退出: %s" % (r.stderr or r.stdout)[:160].replace("\n", " "))
        time.sleep(3)

    # 健康检查（只在状态变化或心跳时记一行）
    st = {p: port_open(p) for p in (19061, 8792, 8816, 8812)}
    try:
        tcp = run("curl -s -m 5 http://127.0.0.1:8797/api/tcp", 12).stdout or ""
        stale = '"stale":true' in tcp.replace(" ", "").lower()
        age = re.search(r'"age_s":\s*([0-9.]+)', tcp)
        age_s = age.group(1) if age else "?"
    except Exception:                                                       # noqa: BLE001
        stale, age_s = True, "?"
    say("模式=%s 网卡=%s 19061=%d 8792=%d 8816=%d 8812=%d tcp_age=%ss stale=%s"
        % (want, iface or "none", st[19061], st[8792], st[8816], st[8812], age_s, stale))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
