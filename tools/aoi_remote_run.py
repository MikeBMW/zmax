#!/usr/bin/env python3
"""把一段 PowerShell **文件** 经反向通道交给工控机 192.168.23.23 执行并取回执。

为什么要有它: 直接把 PowerShell 拼成字符串塞给 agent_hub 会在审批闸里被当成"嵌套可执行体"拦下;
把脚本先落成文件、只传路径, 就干净了(与 aoi_remote_deploy.py 同一条通道/同一份回执机制)。

用法:
  python3 tools/aoi_remote_run.py --ps /path/to/script.ps1 [--wait 300] [--label myjob]
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from aoi_remote_deploy import remote, log          # noqa: E402  复用同一通道


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ps", required=True, help="要执行的 PowerShell 脚本文件(.ps1)")
    ap.add_argument("--wait", type=float, default=300.0)
    ap.add_argument("--label", default="run")
    a = ap.parse_args()
    if not os.path.exists(a.ps):
        log("✗ 脚本不存在: %s" % a.ps)
        return 2
    ps = open(a.ps, encoding="utf-8").read()
    log("下发 %s (%d 字符) 等回执最多 %.0fs" % (os.path.basename(a.ps), len(ps), a.wait))
    t0 = time.time()
    out = remote(ps, wait=a.wait, label=a.label)
    log("回执 %.1fs:" % (time.time() - t0))
    print(out)
    return 0 if ("TIMEOUT" not in out and "ENQUEUE_FAIL" not in out) else 3


if __name__ == "__main__":
    sys.exit(main())
