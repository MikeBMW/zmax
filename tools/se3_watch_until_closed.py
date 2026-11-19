#!/usr/bin/env python3
"""盯新轨迹: 每 2s 拉 8817, 闭环/跳变/超时就退出并打印终态 (给一次知情回报用)。
用法: python3 tools/se3_watch_until_closed.py [--mins 30]
"""
import argparse
import json
import time
import urllib.request


def get(url, t=4.0):
    with urllib.request.urlopen(url, timeout=t) as r:
        return json.loads(r.read().decode())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mins", type=float, default=30.0)
    ap.add_argument("--url", default="http://127.0.0.1:8817/api/follow")
    a = ap.parse_args()
    t_end = time.time() + a.mins * 60
    last = None
    while time.time() < t_end:
        try:
            d = get(a.url)
            r, e, A = d["route"], d["E"], d["A"]["mm"]
            line = ("点%-5d 弧长%8.1fmm 跨度%5.0f/%5.0f/%5.0f 跳变%-2d | A %7.1f %7.1f %7.1f | %s%s" % (
                r["n_pts"], r["cum_mm"], r["span_mm"][0], r["span_mm"][1], r["span_mm"][2],
                r["jumps"], A[0], A[1], A[2], e["mode"],
                (" s=%.4f 圈%d" % (e["s"], e.get("laps") or 0)) if e.get("mode") == "closed" else ""))
            if line != last:
                print(line, flush=True)
                last = line
            if r.get("closed") and r.get("shape") != "retrace":
                print("[closed] 闭环成立 · L=%.1fmm" % (e.get("L_mm") or 0), flush=True)
                return 0
            if r.get("closed") and r.get("shape") == "retrace" and not locals().get("_rt_done"):
                _rt_done = True
                print("[retrace] 首尾重合但回程贴着去程 (%.1fmm) ⇒ 往返, 不是闭环; 继续盯" % (
                    r.get("retrace_mm") or -1), flush=True)
            if (r.get("jumps") or 0) > 0:
                print("[jump] 跳变 %s 次 (最新 %.0fmm)" % (r["jumps"], r.get("last_jump_mm") or 0), flush=True)
                return 2
        except Exception as ex:                                              # noqa: BLE001
            print("[warn]", str(ex)[:70], flush=True)
        time.sleep(2)
    print("[timeout] %.0f 分钟未闭环, 最后: %s" % (a.mins, last), flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
