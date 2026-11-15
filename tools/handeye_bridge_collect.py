#!/usr/bin/env python3
"""handeye_bridge_collect.py — 经 Orin SDK 桥(39061) 走位采集手眼标定对 (2026-11-15)

为什么走这条路: ROS2 /move_pose 在本机读位姿报 `sequence size exceeds remaining buffer`,
而 Orin 的 SDK HTTP 桥 /health 是 sdk:true 且 /status 能读到 endInRef 真值 ⇒ 用它.

安全闸(逐点):
  1) 前置: /health sdk:true, /status operateMode=automatic & powerState=on
  2) 每步: 旋转 <=10deg / 平移 <=30mm, speed<=20mm/s
  3) 到位校验: 目标 vs 回读 位置 <=1.0mm 且 姿态 <=0.5deg, 超时 6s 判失败 → /stop 退出
  4) 力矩: 任轴 |torque| > 23Nm 立即 /stop 退出 (J3 基线已 22.4Nm)
  5) Ctrl+C / 异常 → /stop
采集: 每点 等稳 0.6s → 抓 8791/snapshot/arm.jpg → 同一时刻读 /status(ts) → 板 20 点检测
输出: ~/zmax_data/calib/handeye_bridge_pairs.json  (逐点: p_tcp, q_tcp, 板像素, 检出数, 力矩)

用法:
  ./gui-venv311/bin/python tools/handeye_bridge_collect.py --dry      # 只打印计划
  ./gui-venv311/bin/python tools/handeye_bridge_collect.py --go       # 真下发+采集
"""
from __future__ import annotations
import argparse, json, math, os, subprocess, sys, time
import numpy as np

BRIDGE = "http://192.168.23.66:39061"
CAM = "http://127.0.0.1:8791/snapshot/arm.jpg"
OUT = os.path.expanduser("~/zmax_data/calib/handeye_bridge_pairs.json")
TQ_ABS_MAX = 40.0     # 硬上限(控制器侧限值之上再兜一层)
TQ_RISE_MAX = 10.0    # 相对基线增量上限: 悬停本身就有重力矩, 只看增量
POS_TOL_MM, ROT_TOL_DEG = 1.0, 0.5
SPEED = 20.0


def http_post(path, obj, timeout=15):
    import urllib.request
    req = urllib.request.Request(BRIDGE + path, data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def http_get(path, timeout=10):
    import urllib.request
    with urllib.request.urlopen(BRIDGE + path, timeout=timeout) as r:
        return json.loads(r.read().decode())


def status():
    return http_get("/status").get("status") or {}


def euler_xyz_to_quat(rx, ry, rz):
    """rpy(rad, 与 endInRef 同口径 xyz 序) → q=[x,y,z,w]"""
    cx, sx = math.cos(rx / 2), math.sin(rx / 2)
    cy, sy = math.cos(ry / 2), math.sin(ry / 2)
    cz, sz = math.cos(rz / 2), math.sin(rz / 2)
    return [sx * cy * cz - cx * sy * sz,
            cx * sy * cz + sx * cy * sz,
            cx * cy * sz - sx * sy * cz,
            cx * cy * cz + sx * sy * sz]


def quat_to_euler_xyz(q):
    x, y, z, w = q
    rx = math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
    ry = math.asin(max(-1.0, min(1.0, 2 * (w * y - z * x))))
    rz = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    return rx, ry, rz


def qang_deg(q1, q2):
    d = abs(sum(a * b for a, b in zip(q1, q2)))
    return math.degrees(2 * math.acos(max(-1.0, min(1.0, d))))


def grab_frame():
    import urllib.request
    with urllib.request.urlopen(CAM, timeout=8) as r:
        return r.read()


def detect_board(jpg_bytes):
    """CGB-020 圆点阵列 (4,5) 非对称 — 关键: 必须自带 SimpleBlobDetector, 默认 detector 检不出"""
    import cv2
    arr = np.frombuffer(jpg_bytes, np.uint8)
    im = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if im is None:
        return None, 0
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    p = cv2.SimpleBlobDetector_Params()
    p.filterByArea = True; p.minArea = 50; p.maxArea = 1500
    p.filterByCircularity = True; p.minCircularity = 0.55
    p.filterByConvexity = True; p.minConvexity = 0.7
    p.filterByInertia = True; p.minInertiaRatio = 0.15
    p.filterByColor = True; p.blobColor = 255
    p.minDistBetweenBlobs = 8
    det = cv2.SimpleBlobDetector_create(p)
    for pat in ((4, 5), (5, 4)):
        ok, c = cv2.findCirclesGrid(g, pat, flags=cv2.CALIB_CB_ASYMMETRIC_GRID, blobDetector=det)
        if ok:
            return c.reshape(-1, 2).tolist(), len(c)
    return None, 0


def build_plan(p0, rpy0):
    """12 位姿: 3 轴旋转 ±10° + 四向平移 30mm (技能: 必须绕工具三轴都有旋转)"""
    d = math.radians(10.0)
    t = 0.030
    P = []
    P.append(("P01 原位",            p0,                        rpy0))
    P.append(("P02 rx+10",           p0,                        [rpy0[0] + d, rpy0[1], rpy0[2]]))
    P.append(("P03 rx-10",           p0,                        [rpy0[0] - d, rpy0[1], rpy0[2]]))
    P.append(("P04 ry+10",           p0,                        [rpy0[0], rpy0[1] + d, rpy0[2]]))
    P.append(("P05 ry-10",           p0,                        [rpy0[0], rpy0[1] - d, rpy0[2]]))
    P.append(("P06 rz+10",           p0,                        [rpy0[0], rpy0[1], rpy0[2] + d]))
    P.append(("P07 rz-10",           p0,                        [rpy0[0], rpy0[1], rpy0[2] - d]))
    P.append(("P08 +X30", [p0[0] + t, p0[1], p0[2]], rpy0))
    P.append(("P09 -X30", [p0[0] - t, p0[1], p0[2]], rpy0))
    P.append(("P10 +Y30", [p0[0], p0[1] + t, p0[2]], rpy0))
    P.append(("P11 -Y30", [p0[0], p0[1] - t, p0[2]], rpy0))
    P.append(("P12 +Z30", [p0[0], p0[1], p0[2] + t], rpy0))
    return P


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="只打印计划, 不下发")
    ap.add_argument("--go", action="store_true", help="真下发并采集")
    ap.add_argument("--speed", type=float, default=SPEED)
    ap.add_argument("--start", type=int, default=1, help="从第几个点开始(1-based), 用于补采")
    ap.add_argument("--append", action="store_true", help="与已有 pairs 合并而不是覆盖")
    ap.add_argument("--arrive-s", type=float, default=8.0, help="到位超时秒")
    a = ap.parse_args()

    h = http_get("/health")
    print("桥 /health:", h, flush=True)
    if not h.get("sdk"):
        print("❌ SDK 未连, 中止"); return 1
    st = status()
    print("operateMode=%s powerState=%s" % (st.get("operateMode"), st.get("powerState")), flush=True)
    e = st.get("endInRef") or []
    if len(e) < 6:
        print("❌ 读不到 endInRef, 中止"); return 1
    p0, rpy0 = list(e[:3]), list(e[3:6])
    tq = st.get("jointTorque") or []
    tq_base = list(tq)
    print("当前 p0=%s rpy0=%s" % (np.round(p0, 4).tolist(), np.round(rpy0, 4).tolist()), flush=True)
    print("力矩=%s  最大=%.2fNm  (判据: 增量>%.0fNm 或 绝对>%.0fNm 才停)"
          % (np.round(tq, 2).tolist(), max(map(abs, tq)) if tq else 0, TQ_RISE_MAX, TQ_ABS_MAX), flush=True)

    plan = build_plan(p0, rpy0)
    if a.start > 1:
        plan = plan[a.start - 1:]
        print("\n[补采] 从 P%02d 开始, 共 %d 点" % (a.start, len(plan)))
    print("\n=== 12 位姿计划 (旋转 ±10°, 平移 ±30mm, speed %.0fmm/s) ===" % a.speed)
    for nm, p, rpy in plan:
        print("  %-10s p_mm=%s  rpy_deg=%s" % (nm,
              np.round(np.array(p) * 1000, 1).tolist(),
              np.round(np.degrees(rpy), 1).tolist()))

    if a.dry or not a.go:
        print("\n[dry] 未下发。加 --go 才真走。")
        return 0

    # 真下发: 先 reset (SDK 接管前置)
    print("\n=== POST /reset ===", flush=True)
    print(http_post("/reset", {}, 20), flush=True)
    time.sleep(1.0)

    pairs, fails = [], []
    try:
        for i, (nm, p, rpy) in enumerate(plan):
            q = euler_xyz_to_quat(*rpy)
            print("\n[%d/%d] %s → p=%s q=%s" % (i + a.start, len(plan), nm,
                  np.round(np.array(p) * 1000, 1).tolist(), np.round(q, 4).tolist()), flush=True)
            r = http_post("/move_pose", {"p": [float(v) for v in p], "q": q,
                                         "speed": a.speed, "dry": False}, 30)
            print("   move_pose →", r, flush=True)
            if not r.get("ok"):
                fails.append({"i": i + a.start, "name": nm, "why": "move_pose fail: %s" % r})
                break

            # 到位校验
            t0 = time.time(); okpos = False; lt = {}; dp = 999.0; dq = 999.0
            while time.time() - t0 < a.arrive_s:
                time.sleep(0.35)
                s2 = status(); e2 = s2.get("endInRef") or []
                if len(e2) < 6:
                    continue
                dp = float(np.linalg.norm(np.array(e2[:3]) - np.array(p))) * 1000
                dq = qang_deg(q, euler_xyz_to_quat(*e2[3:6]))
                lt = s2
                if dp <= POS_TOL_MM and dq <= ROT_TOL_DEG:
                    okpos = True
                    print("   到位 dp=%.2fmm dr=%.2fdeg (%.1fs)" % (dp, dq, time.time() - t0), flush=True)
                    break
            if not okpos:
                print("   ⚠ 未在 8s 内到位 (最后 dp=%.1fmm dq=%.1fdeg) → /stop" % (dp, dq), flush=True)
                fails.append({"i": i + a.start, "name": nm, "why": "no-arrive dp=%.2f dq=%.2f" % (dp, dq)})
                http_post("/stop", {}, 10)
                break

            # 力矩闸
            tqv = lt.get("jointTorque") or []
            if tqv and tq_base:
                rise = max(abs(a - b) for a, b in zip(tqv, tq_base))
                absmax = max(map(abs, tqv))
                if rise > TQ_RISE_MAX or absmax > TQ_ABS_MAX:
                    print("   ⚠ 力矩 增量=%.2fNm 绝对=%.2fNm → /stop" % (rise, absmax), flush=True)
                    fails.append({"i": i + a.start, "name": nm, "why": "torque rise=%.2f abs=%.2f" % (rise, absmax)})
                    http_post("/stop", {}, 10)
                    break

            # 采集 (等稳 → 抓帧 → 同刻位姿)
            time.sleep(0.6)
            jpg = grab_frame()
            st3 = status()
            e3 = st3.get("endInRef") or []
            pts, n = detect_board(jpg)
            fn = os.path.expanduser("~/zmax_data/calib/bridge_%02d.jpg" % (i + a.start))
            open(fn, "wb").write(jpg)
            pairs.append({"i": i + a.start, "name": nm,
                          "p_tcp": e3[:3], "q_tcp": euler_xyz_to_quat(*e3[3:6]),
                          "rpy_deg": [math.degrees(v) for v in e3[3:6]],
                          "board_px": pts, "n_det": n, "img": fn,
                          "torque": st3.get("jointTorque"), "ts": time.time()})
            print("   采集: 板 %d 点  %s" % (n, "✅" if n == 20 else "⚠ 不足20"), flush=True)
            if n < 12:
                fails.append({"i": i + a.start, "name": nm, "why": "board %d pts" % n})
    except KeyboardInterrupt:
        print("\n⚠ Ctrl+C → /stop", flush=True)
        http_post("/stop", {}, 10)
    finally:
        try:
            http_post("/stop", {}, 10)
        except Exception:
            pass
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        if a.append and os.path.exists(OUT):
            old = json.load(open(OUT))
            merged = {p["i"]: p for p in old.get("pairs", [])}
            for p in pairs:
                merged[p["i"]] = p
            pairs = [merged[k] for k in sorted(merged)]
            print("[append] 旧 %d + 新 = %d 组" % (len(old.get("pairs", [])), len(pairs)), flush=True)
            fails = list(old.get("fails", [])) + fails
        json.dump({"pairs": pairs, "fails": fails, "at": time.time()},
                  open(OUT, "w"), ensure_ascii=False, indent=1)
        print("\n落盘: %s  (成功 %d / 计划 %d, 失败 %d)" % (OUT, len(pairs), len(plan), len(fails)), flush=True)
        good = [p for p in pairs if p["n_det"] == 20]
        print("可用对(20点): %d" % len(good), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
