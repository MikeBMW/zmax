#!/usr/bin/env python3
"""find_peer_hermes.py — 在一台"陌生/新开机"主机上找已知对端主机。

用法: python3 find_peer_hermes.py [CIDR]        # 省略则取默认路由网段
只读: 仅 TCP connect + SSH banner, 不登录、不改任何远端状态。
判据: 22 口开 + 8791/8793/8797 任一开 => 疑似 Z-MAX 工位机(550A/4060)。
不需要 nmap(内网/离线机常装不上)。
"""
import concurrent.futures as cf
import re
import socket
import subprocess
import sys

PORTS = {22: "ssh", 8791: "cams", 8793: "stream", 8797: "ar"}
ZMAX = {8791, 8793, 8797}


def default_cidr() -> str:
    route = subprocess.run(["ip", "route"], capture_output=True, text=True).stdout
    dev = None
    for line in route.splitlines():
        if line.startswith("default"):
            m = re.search(r"dev (\S+)", line)
            if m:
                dev = m.group(1)
                break
    if not dev:
        sys.exit("找不到默认路由, 手动传 CIDR")
    info = subprocess.run(["ip", "-4", "-o", "addr", "show", dev], capture_output=True, text=True).stdout
    m = re.search(r"inet (\d+\.\d+\.\d+)\.\d+/(\d+)", info)
    if not m:
        sys.exit(f"{dev} 没有 IPv4 地址")
    return f"{m.group(1)}.0/{m.group(2)}"


def probe(ip: str, port: int, timeout: float = 0.6):
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect((ip, port))
        return port
    except Exception:
        return None
    finally:
        s.close()


def banner(ip: str) -> str:
    try:
        s = socket.socket()
        s.settimeout(2)
        s.connect((ip, 22))
        b = s.recv(96).decode(errors="ignore").strip()
        s.close()
        return b
    except Exception:
        return ""


def main() -> None:
    cidr = sys.argv[1] if len(sys.argv) > 1 else default_cidr()
    base = cidr.rsplit(".", 1)[0]
    print(f"扫 {base}.1-254 (port {sorted(PORTS)}) ...")
    jobs = [(f"{base}.{i}", p) for i in range(1, 255) for p in PORTS]
    hits = {}
    with cf.ThreadPoolExecutor(256) as ex:
        for ip, port in jobs:
            if ex.submit(probe, ip, port).result():
                hits.setdefault(ip, []).append(port)
    if not hits:
        print("无主机应答; 对端可能不在同网段(办公 WiFi 常开客户端隔离), 换跳板/隧道再探")
        return
    for ip, ports in sorted(hits.items(), key=lambda kv: -len(kv[1])):
        tags = ",".join(f"{p}({PORTS[p]})" for p in sorted(ports))
        verdict = "疑似 Z-MAX 工位机" if 22 in ports and ZMAX & set(ports) else "未知主机, 需再核身份"
        print(f"{ip:15s} {tags:34s} {verdict}")
        if 22 in ports:
            print(f"{'':15s} banner: {banner(ip)}")


if __name__ == "__main__":
    main()
