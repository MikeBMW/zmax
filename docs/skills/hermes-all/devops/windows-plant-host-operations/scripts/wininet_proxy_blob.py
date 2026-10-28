#!/usr/bin/env python3
"""生成/改写 WinINET 的 Connections\\DefaultConnectionSettings REG_BINARY 内容。

为什么需要它
------------
IE/WinINET 与 Windows 上的浏览器真正读的是这个二进制 blob, **不是**
`Internet Settings` 下的 `ProxyEnable`/`ProxyServer` 两个键。只改键值时, 浏览器会继续
用 blob 里的旧代理(实测残留一个早已下线的地址) —— 表象是"你怎么设都上不了网"。

blob 结构(小端):

    off  0 : 4B version   = 0x46 (70)
    off  4 : 4B counter     (每次写入 +1, 用于通知变更)
    off  8 : 4B flags       (0x01 = 启用代理; 实测带代理的机器上就是 1)
    off 12 : 4B 代理串字节数 (不含结尾 NUL)
    off 16 :    代理串, 如 192.168.23.50:8889
    之后   : 4B 旁路串字节数, 再跟旁路串, 如 192.168.23.*;localhost;127.0.0.1;<local>
    末尾   : \x00 补齐到原有总长(实测 124)

因为**长度是自带字段**, 换代理地址时不能做等长之外的字符串替换, 必须按格式重建,
并保持总字节数不变。

用法
----
    # 推荐: 以机器上现有的 blob 为基准(counter+1, 总长/ver/flags 沿用)
    python3 wininet_proxy_blob.py --old-hex "460000002A000000..." \
        --proxy 192.168.23.50:8889 --bypass '192.168.23.*;localhost;127.0.0.1;<local>'

    # 从零构造
    python3 wininet_proxy_blob.py --proxy 192.168.23.50:8889 \
        --bypass '192.168.23.*;127.*;localhost;<local>' --total 124

输出一行 hex, 直接喂给:

    reg add "HKU\\<SID>\\Software\\Microsoft\\Windows\\CurrentVersion\\Internet Settings\\Connections" \\
        /v DefaultConnectionSettings /t REG_BINARY /d <hex> /f

改完必须回读 `reg query ... /v DefaultConnectionSettings` 比对, 并让用户**关掉浏览器进程再打开**。
"""
import argparse
import struct
import sys

VER = 0x46
FLAG_PROXY = 0x01
DEFAULT_TOTAL = 124  # 实测机器上的总长; 用 --old-hex 时自动沿用


def parse(hexstr: str):
    raw = bytes.fromhex(hexstr.strip())
    ver, counter, flags, plen = struct.unpack_from("<IIII", raw, 0)
    proxy = raw[16:16 + plen]
    off = 16 + plen
    (blen,) = struct.unpack_from("<I", raw, off)
    bypass = raw[off + 4:off + 4 + blen]
    return dict(ver=ver, counter=counter, flags=flags, proxy=proxy, bypass=bypass, total=len(raw))


def build(proxy: str, bypass: str, ver: int = VER, counter: int = 1,
          flags: int = FLAG_PROXY, total: int = DEFAULT_TOTAL) -> bytes:
    p, b = proxy.encode("ascii"), bypass.encode("ascii")
    out = struct.pack("<IIII", ver, counter, flags, len(p)) + p
    out += struct.pack("<I", len(b)) + b
    if len(out) > total:
        total = len(out)  # 串太长就放宽总长, 但绝不截断
    return out + b"\x00" * (total - len(out))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--proxy", required=True, help="如 192.168.23.50:8889")
    ap.add_argument("--bypass", default="192.168.23.*;127.*;localhost;<local>",
                    help="必须含内网 CIDR 与 <local>, 否则产线服务会被代理吞掉")
    ap.add_argument("--old-hex", help="机器上现有的 blob hex; 给出则沿用 ver/flags/总长并把 counter+1")
    ap.add_argument("--total", type=int, default=DEFAULT_TOTAL)
    a = ap.parse_args()

    if a.old_hex:
        o = parse(a.old_hex)
        print("# 旧 blob: counter=%d flags=0x%02x 代理=%s 旁路=%s 总长=%d"
              % (o["counter"], o["flags"], o["proxy"].decode("ascii", "replace"),
                 o["bypass"].decode("ascii", "replace"), o["total"]), file=sys.stderr)
        blob = build(a.proxy, a.bypass, ver=o["ver"], counter=o["counter"] + 1,
                     flags=o["flags"], total=o["total"])
    else:
        blob = build(a.proxy, a.bypass, total=a.total)

    c = parse(blob.hex())
    assert c["proxy"].decode() == a.proxy and c["bypass"].decode() == a.bypass, "自检失败"
    print("# 总长=%d 代理=%s(%d) 旁路=%s(%d)"
          % (len(blob), c["proxy"].decode(), len(c["proxy"]),
             c["bypass"].decode(), len(c["bypass"])), file=sys.stderr)
    print(blob.hex().upper())
    return 0


if __name__ == "__main__":
    sys.exit(main())
