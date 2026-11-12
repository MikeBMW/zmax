#!/usr/bin/env python3
"""并发扫网段: 哪些主机 ping 通, 以及指定端口在哪些机器上开着。

用法:
    python3 lan_sweep.py 192.168.23.0/24 22 8793 8799

只读探测 (ICMP + TCP connect), 不改任何远端状态。
用 python 并发而不是 bash `&`: 前台命令带 `&` 会被 Hermes 拒绝,
而且 254 个地址的 ping+端口串行要几分钟, 并发 ~10s 出结果。
输出:
    PING-UP: <ip ...>
    PORT 22: <ip ...>
    PORT 8793: ...
"""
import concurrent.futures
import socket
import subprocess
import sys


def hosts_from_cidr(cidr: str):
    base, bits = cidr.split('/')
    if bits != '24' or base.count('.') != 3:
        raise SystemExit('只支持 /24, 例: 192.168.23.0/24')
    prefix = base.rsplit('.', 1)[0]
    return [f'{prefix}.{i}' for i in range(1, 255)]


def alive(ip: str):
    r = subprocess.run(['ping', '-c1', '-W1', ip],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return ip if r.returncode == 0 else None


def port_open(ip: str, port: int, timeout: float = 1.2):
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect((ip, port))
        return ip
    except OSError:
        return None
    finally:
        s.close()


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    cidr = sys.argv[1]
    ports = [int(p) for p in sys.argv[2:]] or [22]
    ips = hosts_from_cidr(cidr)

    with concurrent.futures.ThreadPoolExecutor(64) as ex:
        up = [x for x in ex.map(alive, ips) if x]
    print('PING-UP:', ' '.join(up) if up else '(none)')

    if not up:
        return
    for port in ports:
        with concurrent.futures.ThreadPoolExecutor(64) as ex:
            open_hosts = [x for x in ex.map(lambda ip: port_open(ip, port), up) if x]
        print(f'PORT {port}:', ' '.join(open_hosts) if open_hosts else '(none)')


if __name__ == '__main__':
    main()
