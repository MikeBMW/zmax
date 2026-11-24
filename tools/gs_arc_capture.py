#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gs_arc_capture.py — 恒定 z 纯平移弧线扫场（给 3DGS 采多视角）

设计依据: skill real-arm-motion-control/references/capture-trajectory-constant-z.md
  · z 恒定（不升降）→ 撞不到上方 AOI 相机/横梁，也碰不到台面
  · 姿态恒定（四元数一个字节不改）→ 纯平移，不触发 50102 奇异 / 50113 姿态阈值
  · 绕目标半径恒定 → 目标尺度一致，不会越走越近

逐点闸门（任一不过即 /stop 并中止，绝不重发/不补偿）:
  ① 起点真值距第一路点 ≤ 80mm
  ② 每点先 dry 预演, 桥返回的 delta_mm 必须与计划位移对上（≤2mm）
  ③ 真下发后轮询真值: 到位 ≤2mm 且 jointVel < 0.02
  ④ 任何一步超时/偏差超限 → POST /stop → 退出码 5

用法:
  python3 tools/gs_arc_capture.py --plan <arc_pts.json> [--speed 80] [--dry] [--max-pts N]
  arc_pts.json: {"center_mm":[x,y],"z_mm":Z,"r_mm":R,"n":N,"quat":[x,y,z,w],"pts":[{"i","deg","pos_mm"}]}
"""
import argparse
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:39071"
TOL_MM = 2.0
TIMEOUT_S = 45.0
START_TOL_MM = 80.0


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=8) as r:
        return json.loads(r.read().decode())


def post(path, obj, timeout=40):
    req = urllib.request.Request(BASE + path, data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def pose():
    st = get("/status")["status"]
    e = st["endInRef"]
    return [float(e[0]), float(e[1]), float(e[2])], st


def dmm(a, b):
    return [round((a[i] - b[i]) * 1000.0, 2) for i in range(3)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--speed", type=float, default=80.0, help="mm/s")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--max-pts", type=int, default=0)
    a = ap.parse_args()

    plan = json.load(open(a.plan, encoding="utf-8"))
    pts = [{"deg": p["deg"], "p": [v / 1000.0 for v in p["pos_mm"]]} for p in plan["pts"]]
    if a.max_pts:
        pts = pts[:a.max_pts]
    q = [float(x) for x in plan["quat"]]

    p0, st0 = pose()
    print(json.dumps({"ev": "pre", "power": st0.get("powerState"), "mode": st0.get("operateMode"),
                      "tcp_mm": [round(v * 1000, 1) for v in p0],
                      "plan_pts": len(pts), "speed_mm_s": a.speed,
                      "dist_to_first_mm": dmm(p0, pts[0]["p"])}, ensure_ascii=False))
    if "on" not in str(st0.get("powerState")).lower() or "automatic" not in str(st0.get("operateMode")).lower():
        print(json.dumps({"ev": "ABORT", "why": "非上电/非自动模式"}, ensure_ascii=False))
        return 3
    if max(abs(x) for x in dmm(p0, pts[0]["p"])) > START_TOL_MM:
        print(json.dumps({"ev": "ABORT", "why": "起点离第一路点太远(先手动/小步靠近)"}, ensure_ascii=False))
        return 3

    for k, pt in enumerate(pts):
        tgt = pt["p"]
        prev, _ = pose()
        want = dmm(tgt, prev)
        dry = post("/move_pose", {"p": tgt, "q": q, "speed": a.speed, "dry": True})
        dm = (dry.get("result") or {}).get("plan", {}).get("delta_mm")
        ok_dry = dm is not None and max(abs(dm[i] - want[i]) for i in range(3)) <= 2.0
        print(json.dumps({"ev": "dry", "i": k, "deg": pt["deg"], "delta_mm": dm, "want": want,
                          "ok": ok_dry}, ensure_ascii=False))
        if not ok_dry:
            print(json.dumps({"ev": "ABORT", "at": k, "why": "dry 预演与计划不符"}, ensure_ascii=False))
            return 4
        if a.dry:
            continue

        t_send = time.time()
        res = post("/move_pose", {"p": tgt, "q": q, "speed": a.speed, "dry": False})
        p_end, st, stable = None, None, False
        while time.time() - t_send < TIMEOUT_S:
            time.sleep(0.2)
            try:
                p_end, st = pose()
            except Exception:  # noqa: BLE001
                continue
            err = max(abs(x) for x in dmm(p_end, tgt))
            vel = max(abs(float(v)) for v in (st.get("jointVel") or [0]))
            if err <= TOL_MM and vel < 0.02:
                stable = True
                break
        err = max(abs(x) for x in dmm(p_end or prev, tgt))
        print(json.dumps({"ev": "pt_done", "i": k, "deg": pt["deg"], "took_s": round(time.time() - t_send, 2),
                          "err_mm": err, "tcp_mm": [round(v * 1000, 1) for v in (p_end or prev)],
                          "ok": stable}, ensure_ascii=False))
        if not stable:
            try:
                post("/stop", {})
            except Exception:  # noqa: BLE001
                pass
            print(json.dumps({"ev": "ABORT", "at": k, "why": "未到位/未停稳, 已 stop"}, ensure_ascii=False))
            return 5

    p1, _ = pose()
    print(json.dumps({"ev": "final", "pts_done": len(pts),
                      "tcp_mm": [round(v * 1000, 1) for v in p1]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
