#!/usr/bin/env python3
"""find_peer.py - 扫本网段找对端静静 (开 22 端口的主机)。

对端 IP 会随网段漂移 (公司网 192.168.1.7 / 热点网 192.168.43.181 ...),
每次都手搓 /dev/tcp 循环既慢又容易漏, 用这个。

用法:
  python3 find_peer.py                       # 扫本机 /24
  python3 find_peer.py --prefix 192.168.43   # 指定网段 (可给多个)
  python3 find_peer.py --verify              # 顺带 ssh 认身份 (9.6G ~/.hermes + 270G ~/zmax = 静静)

只用 stdlib + 系统 ssh; Windows / Linux 通用 (不解析 ipconfig 的 GBK 输出)。
"""
import argparse
import concurrent.futures as cf
import socket
import subprocess
import sys

KEY = "~/.ssh/id_ed25519"


def local_prefix():
    """UDP connect 拿主网卡 IP, 避开 ipconfig/GBK 解析。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    finally:
        s.close()
    return ".".join(ip.split(".")[:3])


def probe(ip, port=22, timeout=0.6):
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect((ip, port))
        return ip
    except Exception:
        return None
    finally:
        s.close()


def verify(ip, user="ubuntu"):
    cmd = [
        "ssh", "-i", KEY, "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=6",
        f"{user}@{ip}",
        "hostname; du -sh ~/.hermes ~/zmax 2>/dev/null",
    ]
    try:
        r = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=25)
    except Exception as e:
        return f"ssh failed: {e}"
    out = r.stdout.decode("utf-8", "replace").strip()
    err = r.stderr.decode("utf-8", "replace").strip().splitlines()
    return out or ("ssh rc=%d " % r.returncode + (err[-1] if err else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", action="append", default=[],
                    help="网段前缀, 如 192.168.43; 缺省用本机主网卡 /24")
    ap.add_argument("--port", type=int, default=22)
    ap.add_argument("--verify", action="store_true", help="ssh 连上认身份")
    ap.add_argument("--user", default="ubuntu", help="认身份用的账号, 默认 ubuntu")
    a = ap.parse_args()

    prefixes = a.prefix or [local_prefix()]
    self_ip = local_prefix()
    hits = []
    for pre in prefixes:
        ips = [f"{pre}.{i}" for i in range(1, 255)]
        with cf.ThreadPoolExecutor(64) as ex:
            hits += [r for r in ex.map(lambda ip: probe(ip, a.port), ips) if r]

    print("prefix=%s self=%s port=%d" % (",".join(prefixes), self_ip, a.port))
    if not hits:
        print("no host with port %d open" % a.port)
        return 1
    for ip in hits:
        tag = " (self)" if ip == self_ip else ""
        print("  %s%s" % (ip, tag))
        if a.verify and ip != self_ip:
            print("    " + verify(ip, a.user).replace("\n", " | "))
    others = [h for h in hits if h != self_ip]
    if len(others) == 1:
        print("\n候选对端: %s" % others[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
