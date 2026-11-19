#!/usr/bin/env python3
"""盯现场状态变化 (老倪 2026-11-19「你看着」): 控制器上电/模式切换/真值断流/开始动/闭环。
只在"变化"时打一行, 到关键态就退出并 notify。

退出码: 0 = 控制器就绪(power on + automatic + idle, 可下发) / 2 = 真值连续陈旧>60s
       3 = 开始动起来(点增长) 后 90s 无闭环仍退出 / 1 = 超时
用法: python3 -u tools/watch_station_state.py [--mins 60]
"""
import argparse
import json
import time
import urllib.request


def get(url, t=4.0):
    with urllib.request.urlopen(url, timeout=t) as r:
        return json.loads(r.read().decode())


def pick(d):
    c = d.get("ctl") or {}
    r = c.get("robot") or {}
    return {"power": r.get("power"), "mode": r.get("mode"), "op": r.get("operation"),
            "estop": r.get("estop"), "err": r.get("has_error"), "armed": c.get("motion_armed")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mins", type=float, default=60.0)
    a = ap.parse_args()
    t_end = time.time() + a.mins * 60
    prev = None
    stale_run = 0
    moving_since = None
    last_pts = None
    while time.time() < t_end:
        line = []
        try:
            st = pick(get("http://127.0.0.1:8793/station/status"))
            key = (st["power"], st["mode"], st["op"], st["estop"], st["err"])
            if key != prev:
                line.append("控制器 power=%s mode=%s op=%s estop=%s err=%s armed=%s" % (
                    st["power"], st["mode"], st["op"], st["estop"], st["err"], st["armed"]))
                prev = key
                if st["power"] == "on" and st["mode"] == "automatic" and st["op"] == "idle":
                    print(" | ".join(line), flush=True)
                    print("[ready] 控制器就绪 (power=on automatic idle) ⇒ 可下发", flush=True)
                    return 0
        except Exception as e:                                                # noqa: BLE001
            line.append("控制器不可读 %s" % str(e)[:40])
        try:
            t = get("http://127.0.0.1:8797/api/tcp")
            age = t.get("age_s") or 0
            if age > 30:
                stale_run += 1
                if stale_run == 1:
                    line.append("真值陈旧 %.0fs" % age)
                if stale_run >= 20:       # 3s×20 = 60s
                    print(" | ".join(line) or "真值连续陈旧", flush=True)
                    print("[stale] 真值 >60s 不新鲜 ⇒ 退出监视", flush=True)
                    return 2
            else:
                stale_run = 0
        except Exception as e:                                                # noqa: BLE001
            line.append("真值不可读 %s" % str(e)[:40])
        try:
            f = get("http://127.0.0.1:8817/api/follow")
            n = f["route"]["n_pts"]
            if last_pts is not None and n > last_pts and moving_since is None:
                moving_since = time.time()
                line.append("开始记录 (点 %d → %d)" % (last_pts, n))
            if f["route"].get("closed") and f["route"].get("shape") != "retrace":
                line.append("闭环 shape=%s L=%.0fmm" % (f["route"].get("shape"), f["E"].get("L_mm") or 0))
            last_pts = n
        except Exception:                                                     # noqa: BLE001
            pass
        if line:
            print("%s %s" % (time.strftime("%H:%M:%S"), " | ".join(line)), flush=True)
        time.sleep(3)
    print("[timeout] %.0f 分钟到" % a.mins, flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
