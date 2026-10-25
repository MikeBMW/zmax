#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""同一条 4 段闭环规划 · 连续模式 (多点一次 moveStart, 不停车) —— 比分段快

分段(首跑): 4 段各自 下发→停稳→对账, 60mm/s 实测 7.32s
连续(本脚本): 4 点一次性 append 进同一队列 + zone 转角圆滑, 只 moveStart 一次 ⇒ 目标 ~2s

必须在 Orin 上跑 (只有 Orin 到控制器 192.168.23.160)。
  python3 exec_plan_fast_via_orin.py --speed 200
  python3 exec_plan_fast_via_orin.py --speed 300 --zone 8

闸门 (任一不过即 /stop, 不重发不补偿):
  ① /health sdk=true
  ② 当前 TCP 距规划起点 ≤3mm  (不在起点就拒, 绝不在未知位置起步)
  ③ dry 预演目标点与规划点位逐点一致 (≤0.5mm)
  ④ 真下发后轮询: 到末点 ≤2mm 且 jointVel<0.02; 超时 30s 判失败
  ⑤ 末点必须回到起点 (≤3mm)
"""
import argparse
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:39061"
START_MM = [535.3432, 306.0598, 161.9456]
DELTAS_MM = [[0, 0, 60], [-80, 0, 0], [0, 0, -60], [80, 0, 0]]
EXPECT_MM = [[535.34, 306.06, 221.95], [455.34, 306.06, 221.95],
             [455.34, 306.06, 161.95], [535.34, 306.06, 161.95]]


def post(path, body, timeout=30):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def status():
    with urllib.request.urlopen(BASE + "/status", timeout=10) as r:
        return json.loads(r.read().decode())["status"]


def tcp_mm(st):
    return [round(v * 1000, 2) for v in st["endInRef"][:3]]


def still(st):
    return max(abs(v) for v in st["jointVel"]) < 0.02


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--speed", type=float, default=200.0)
    ap.add_argument("--zone", type=float, default=5.0)
    ap.add_argument("--timeout", type=float, default=30.0)
    a = ap.parse_args()

    h = json.loads(urllib.request.urlopen(BASE + "/health", timeout=8).read().decode())
    if not (h.get("ok") and h.get("sdk")):
        print("ABORT /health:", h)
        return 2

    st = status()
    here = tcp_mm(st)
    off = [round(here[i] - START_MM[i], 2) for i in range(3)]
    print("预检: 当前 TCP %s mm | 距规划起点 %s mm | 速度 %s mm/s zone %s mm" % (here, off, a.speed, a.zone))
    if max(abs(v) for v in off) > 3:
        print("ABORT 不在规划起点 —— 不猜位置, 不起步")
        return 3

    plan = post("/path", {"points": DELTAS_MM, "speed": a.speed, "zone": a.zone, "dry": True})["result"]["plan"]
    got = [[round(v * 1000, 2) for v in t] for t in plan["targets"]]
    bad = [(i, g, EXPECT_MM[i]) for i, g in enumerate(got)
           if max(abs(g[k] - EXPECT_MM[i][k]) for k in range(3)) > 0.5]
    print("dry 目标点:", got)
    if bad:
        print("ABORT dry 与规划不一致:", bad)
        return 4

    t0 = time.time()
    r = post("/path", {"points": DELTAS_MM, "speed": a.speed, "zone": a.zone, "dry": False})["result"]
    print("下发 ok=%s why=%s append_ec=%s start_ec=%s" % (
        r.get("ok"), r.get("why"), r.get("sent", {}).get("append_ec"), r.get("sent", {}).get("moveStart_ec")))
    if not r.get("ok"):
        post("/stop", {})
        print("ABORT 下发被拒, 已 /stop")
        return 5

    last = here
    moved_max = 0.0
    while time.time() - t0 < a.timeout:
        st = status()
        last = tcp_mm(st)
        moved_max = max(moved_max, max(abs(last[i] - START_MM[i]) for i in range(3)))
        # 🔴 闭环末点 == 起点 ⇒ 只判"到末点"会立刻成立(假 DONE, 实测 0.19s 报完成)
        #    必须**先看见真的走出去**(偏离起点 >30mm), 再判回位停稳
        if moved_max > 30 and still(st) and max(abs(last[i] - EXPECT_MM[-1][i]) for i in range(3)) <= 2.0:
            break
        time.sleep(0.2)
    took = time.time() - t0
    err = max(abs(last[i] - EXPECT_MM[-1][i]) for i in range(3))
    if moved_max <= 30:
        print("FAIL 控制器收下了命令(ec=0)但臂没动: %.2fs 内偏离起点最大 %.1fmm" % (took, moved_max))
        print("     实测坑: 多点 append + 单次 moveStart 会被静默忽略(5 个 ec=0 却 3.2s 零位移)")
        print("     改用分段模式: exec_plan_via_orin.py (单点 /move_pose, 200mm/s 每段 ~1.0s)")
        return 7
    ok = err <= 3.0 and still(status())
    print("连续 %d 点 | 总耗时 %.2fs | 末点 %s | 残差 %.2fmm | %s" % (
        len(DELTAS_MM), took, last, err, "DONE 回到起点" if ok else "FAIL"))
    if not ok:
        post("/stop", {})
    return 0 if ok else 6


if __name__ == "__main__":
    sys.exit(main())
