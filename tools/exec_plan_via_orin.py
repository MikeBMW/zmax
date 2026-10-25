#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在 Orin 上执行 550B 的 4 段闭环规划 (逐段: dry 预演 → 真下发 → 真值对账 → 下一段)

为什么在 Orin 跑: 4060 现在没有产线路由(USB 网卡不在), 只有 Orin 能到控制器 192.168.23.160。
闸门 (逐段, 任一不过即停, 不重发不补偿):
  ① 起点真值 == 规划起点 (≤2mm)
  ② 每段先 dry=true 预演, delta_mm 必须与段表方向/幅值对上 (≤1mm 误差), 否则不发
  ③ 真下发后轮询 /status, 真值到目标 ≤2mm 且关节速度≈0 才算这一段完成; 超时 40s 判失败
  ④ 任何越界/失败立即 /stop, 打印已走/未走
输出: 每段 JSON 一行 (可复制), 最后总判定
"""
import json
import math
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:39061"
START = [0.5353432, 0.3060598, 0.1619456]        # 规划起点 (m), 来自 /api/traj/plan tcp0_mm
SEGS = [                                          # (名称, 目标点 m, 期望 delta mm)
    ("L2.lift +60Z",     [0.5353432, 0.3060598, 0.2219456], [0, 0, 60]),
    ("L2.backward -80X", [0.4553432, 0.3060598, 0.2219456], [-80, 0, 0]),
    ("L2.down -60Z",     [0.4553432, 0.3060598, 0.1619456], [0, 0, -60]),
    ("L2.forward +80X",  [0.5353432, 0.3060598, 0.1619456], [80, 0, 0]),
]
SPEED = 60.0            # mm/s (规划段口径 150~300; 首次真跑取保守 60)
TOL_MM = 2.0
TIMEOUT_S = 40.0


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=8) as r:
        return json.loads(r.read().decode())


def post(path, obj, timeout=30):
    req = urllib.request.Request(BASE + path, data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def pose():
    st = get("/status")["status"]
    e = st["endInRef"]
    return [float(e[0]), float(e[1]), float(e[2])], st


def rpy2q(rx, ry, rz):
    cr, sr = math.cos(rx / 2), math.sin(rx / 2)
    cp, sp = math.cos(ry / 2), math.sin(ry / 2)
    cy, sy = math.cos(rz / 2), math.sin(rz / 2)
    return [sr * cp * cy - cr * sp * sy, cr * sp * cy + sr * cp * sy,
            cr * cp * sy - sr * sp * cy, cr * cp * cy + sr * sp * sy]


def d(a, b):
    return [round((a[i] - b[i]) * 1000.0, 2) for i in range(3)]


def main():
    p0, st0 = pose()
    q = rpy2q(float(st0["endInRef"][3]), float(st0["endInRef"][4]), float(st0["endInRef"][5]))
    print(json.dumps({"ev": "pre", "power": st0.get("powerState"), "mode": st0.get("operateMode"),
                      "tcp_mm": [round(v * 1000, 2) for v in p0],
                      "start_err_mm": d(p0, START), "q": [round(v, 6) for v in q]}, ensure_ascii=False))
    if max(abs(x) for x in d(p0, START)) > TOL_MM:
        print(json.dumps({"ev": "ABORT", "why": "起点与规划起点不符"}, ensure_ascii=False))
        return 3
    if "on" not in str(st0.get("powerState")) or "automatic" not in str(st0.get("operateMode")):
        print(json.dumps({"ev": "ABORT", "why": "非上电/非自动模式"}, ensure_ascii=False))
        return 3

    for name, tgt, want in SEGS:
        # ② dry 预演
        dry = post("/move_pose", {"p": tgt, "q": q, "speed": SPEED, "dry": True})
        dm = (dry.get("result") or {}).get("plan", {}).get("delta_mm")
        ok_dry = dm is not None and max(abs(dm[i] - want[i]) for i in range(3)) <= 1.0
        print(json.dumps({"ev": "dry", "seg": name, "delta_mm": dm, "want": want, "ok": ok_dry},
                         ensure_ascii=False))
        if not ok_dry:
            print(json.dumps({"ev": "ABORT", "seg": name, "why": "dry 预演与段表不符"}, ensure_ascii=False))
            return 4
        # ③ 真下发
        t_send = time.time()
        res = post("/move_pose", {"p": tgt, "q": q, "speed": SPEED, "dry": False})
        print(json.dumps({"ev": "sent", "seg": name, "resp_ok": res.get("ok"),
                          "sent": (res.get("result") or {}).get("sent", {}).get("delta_mm")}, ensure_ascii=False))
        p_end, st = None, None
        stable, t_stable = False, None
        while time.time() - t_send < TIMEOUT_S:
            time.sleep(0.2)
            try:
                p_end, st = pose()
            except Exception as e:                                              # noqa: BLE001
                print(json.dumps({"ev": "poll_err", "err": str(e)[:80]}, ensure_ascii=False))
                continue
            err = max(abs(x) for x in d(p_end, tgt))
            vel = max(abs(float(v)) for v in (st.get("jointVel") or [0]))
            if err <= TOL_MM and vel < 0.02:
                stable, t_stable = True, time.time()
                break
        took = round(time.time() - t_send, 2)
        err = max(abs(x) for x in d(p_end or p0, tgt))
        print(json.dumps({"ev": "seg_done", "seg": name, "took_s": took, "err_mm": err,
                          "tcp_mm": [round(v * 1000, 2) for v in (p_end or p0)],
                          "vel_max": max(abs(float(v)) for v in ((st or {}).get("jointVel") or [0])),
                          "ok": bool(stable)}, ensure_ascii=False))
        if not stable:
            try:
                post("/stop", {})
            except Exception:                                                   # noqa: BLE001
                pass
            print(json.dumps({"ev": "ABORT", "seg": name, "why": "未到位/未停稳, 已发 stop"}, ensure_ascii=False))
            return 5

    p1, st1 = pose()
    back = d(p1, START)
    print(json.dumps({"ev": "final", "tcp_mm": [round(v * 1000, 2) for v in p1],
                      "back_to_start_mm": back, "verdict": "DONE 回到起点" if max(abs(x) for x in back) <= TOL_MM
                      else "未回到起点"}, ensure_ascii=False))
    return 0 if max(abs(x) for x in back) <= TOL_MM else 6


if __name__ == "__main__":
    sys.exit(main())
