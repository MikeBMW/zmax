#!/usr/bin/env python3
"""重启后自动恢复 + 进入监控模式 (老倪 2026-11-19「全部重启, 你看着, 一会直接进入监控模式」)。

阶段:
  A 等真值回来      latest.json 帧龄 <2s 且 8797 /api/tcp ok (最多 20 min)
  B 恢复服务        zmax-traj-ar(8797) / zmax-se3-follow(8817) / zmax-ss-engine-loop / zmax-se3-geom(8815)
                    只 start/restart 自己这几个只读服务, 不动控制器、不动 8793(cam-live-stream)
  C 报 READY        打印真值/控制器/跟随/看板一张表
  D 监控            每 10s 打一行; 闭环 / 跳变 / 真值连续陈旧 >30s / 超时 就退出 (退出码区分)
用法: python3 -u tools/post_restart_monitor.py [--wait-min 20] [--mon-min 45]
"""
import argparse
import json
import os
import subprocess
import time
import urllib.request

UNITS = ["zmax-traj-ar", "zmax-se3-follow", "zmax-ss-engine-loop", "zmax-se3-geom"]
TRUTH = os.path.expanduser("~/zmax/zmax_data/rokae_sdk/tcp_out/latest.json")


def sh(cmd, t=20):
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=t)
        return (p.stdout or "").strip(), p.returncode
    except Exception as e:                                                  # noqa: BLE001
        return str(e), 1


def get(url, t=4.0):
    with urllib.request.urlopen(url, timeout=t) as r:
        return json.loads(r.read().decode())


def truth_age():
    try:
        d = json.load(open(TRUTH))
        return time.time() - float(d.get("ts") or 0), d
    except Exception:                                                       # noqa: BLE001
        return 1e9, {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait-min", type=float, default=20.0)
    ap.add_argument("--mon-min", type=float, default=45.0)
    a = ap.parse_args()

    # A 等真值
    t_end = time.time() + a.wait_min * 60
    print("[A] 等真值回来 (latest.json 帧龄<2s)...", flush=True)
    while time.time() < t_end:
        age, d = truth_age()
        if age < 2.0:
            print("[A] 真值回来了 · 帧龄 %.2fs · TCP %.1f %.1f %.1f mm" % (
                age, d["x"] * 1000, d["y"] * 1000, d["z"] * 1000), flush=True)
            break
        time.sleep(3)
    else:
        print("[A] %.0f 分钟没等到真值 ⇒ 停 (不猜位姿)" % a.wait_min, flush=True)
        return 4

    # B 恢复服务
    print("[B] 恢复只读服务...", flush=True)
    for u in UNITS:
        state, _ = sh("systemctl is-active %s" % u, 10)
        if state != "active":
            sh("sudo systemctl enable --now %s" % u, 30)
            time.sleep(1.5)
        state2, _ = sh("systemctl is-active %s" % u, 10)
        print("    %-24s %s → %s" % (u, state, state2), flush=True)
        if u == "zmax-se3-follow" and state2 != "active":
            sh("sudo systemctl restart %s" % u, 30)
            time.sleep(2)
            print("    %-24s restart → %s" % (u, sh("systemctl is-active %s" % u, 10)[0]), flush=True)

    # C READY 表
    time.sleep(2)
    rows = []
    try:
        t = get("http://127.0.0.1:8797/api/tcp")
        rows.append("真值(8797)  TCP %.1f / %.1f / %.1f mm · 帧龄 %.2fs · %s" % (
            t["x"] * 1000, t["y"] * 1000, t["z"] * 1000, t.get("age_s") or 0, t.get("src") or t.get("source")))
    except Exception as e:                                                  # noqa: BLE001
        rows.append("真值(8797)  ✗ %s" % str(e)[:60])
    try:
        st = get("http://127.0.0.1:8793/station/status")
        c = st.get("ctl") or {}
        r = c.get("robot") or {}
        rows.append("控制器       power=%s mode=%s op=%s estop=%s collision=%s has_error=%s armed=%s" % (
            r.get("power"), r.get("mode"), r.get("operation"), r.get("estop"),
            r.get("collision"), r.get("has_error"), c.get("motion_armed")))
    except Exception as e:                                                  # noqa: BLE001
        rows.append("控制器(8793) ✗ %s" % str(e)[:60])
    try:
        f = get("http://127.0.0.1:8817/api/follow")
        rr = f["route"]
        rows.append("跟随(8817)  点%d · 弧长%.1fmm · 跳变%d · %s · 帧龄%.2fs" % (
            rr["n_pts"], rr["cum_mm"], rr["jumps"], f["E"]["mode"], f.get("age_s") or 0))
    except Exception as e:                                                  # noqa: BLE001
        rows.append("跟随(8817)  ✗ %s" % str(e)[:60])
    for port, name in ((8815, "8815 本机"),):
        code = sh("curl -s -o /dev/null -w '%%{http_code}' --max-time 3 http://127.0.0.1:%d/" % port, 8)[0]
        rows.append("%s  HTTP %s" % (name, code))
    print("[C] ===== READY =====", flush=True)
    for x in rows:
        print("    " + x, flush=True)

    # D 监控
    print("[D] 监控模式 (每 10s, 闭环/跳变/真值陈旧>30s 会退出)", flush=True)
    t_end = time.time() + a.mon_min * 60
    last = None
    stale_run = 0
    while time.time() < t_end:
        try:
            f = get("http://127.0.0.1:8817/api/follow")
            rr, e, A = f["route"], f["E"], f["A"]["mm"]
            line = "点%-5d 弧长%8.1f 跨度%5.0f/%5.0f/%5.0f 跳变%-2d | A %7.1f %7.1f %7.1f | %s%s | 帧龄%.2fs" % (
                rr["n_pts"], rr["cum_mm"], rr["span_mm"][0], rr["span_mm"][1], rr["span_mm"][2],
                rr["jumps"], A[0], A[1], A[2], e["mode"],
                (" s=%.4f" % e["s"]) if e.get("mode") == "closed" else "", f.get("age_s") or 0)
            if line.split("| A")[0] != (last or "").split("| A")[0] or (f.get("age_s") or 0) > 5:
                print(line, flush=True)
                last = line
            if rr.get("closed") and rr.get("shape") != "retrace":
                print("[closed] 闭环 · L=%.1fmm" % (e.get("L_mm") or 0), flush=True)
                return 0
            if (rr.get("jumps") or 0) > 0:
                print("[jump] 跳变 %d 次" % rr["jumps"], flush=True)
                return 2
            if (f.get("age_s") or 0) > 30:
                stale_run += 1
                if stale_run >= 3:
                    print("[stale] 真值连续 >30s 陈旧 ⇒ 退出监控", flush=True)
                    return 3
            else:
                stale_run = 0
        except Exception as ex:                                             # noqa: BLE001
            print("[warn]", str(ex)[:70], flush=True)
        time.sleep(10)
    print("[timeout] %.0f 分钟监控结束" % a.mon_min, flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
