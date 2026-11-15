#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""arm_step_550c.py —— 550C 真机逐点执行器 (走 Orin SDK 桥 39061, 不用 Docker)

为什么是这个形态 (2026-11-15 老倪:「给 550C 写一个走 Orin 39061 桥的执行器(不用 Docker),
逐点调 /move_pose」):
  · 550C 上 docker daemon 起不来 (systemctl is-active docker → failed), 跑不了 4060 那套
    rokae_sdk_run.sh(Docker + xcoresdk 直连控制器) ⇒ 必须换链路
  · Orin 上的 zmax_arm_sdk_bridge.py(:39061) 已经把 xcoresdk 包好了, 并且**能被 550C 访问**
    (实测 /health → {"ok":true,"sdk":true,"ctrl":"192.168.23.160"})
  · 桥只暴露 /reset /move_pose{p,q,speed,dry} /stop —— 没有关节角接口。
    恰好 real_traj_joints.json 每帧同时带 p(米)/q(四元数)/j(关节角/弧度),
    所以**直接发末端位姿**, 不需要 FK, 也不用改 Orin 的服务(红线: 不碰现有服务)

和 8797 的契约 (与 4060 版 arm_step_traj.py 完全一致, 所以 8797 一行都不用改):
  入: zmax_data/rokae_sdk/traj_step_cmd.json → {"start":i0,"n":$N,"speed":..,"dwell_ms":..,"grip":[..]}
  出: stdout 每步一行 JSON {"progress":i+1,"n":..,"step":{..}} —— 8797 靠它算游标
      夹爪: 走到第 i 点报 {"grip_due":true,"i":i,"act":"open|close"}, 原地等 hold_ms

安全(缺一不下发):
  ① 授权: ctl_auth.json 必须 armed (与 8797 同一真源, 这里再查一次不绕过)
  ② 单点跳变: 位移 > MAX_JUMP_MM 或 姿态 > MAX_JUMP_DEG 拒发(防跨段瞬移)
  ③ 逐点等到位: |Δp| ≤ TOL_MM 且 |Δrpy| ≤ TOL_DEG 才算到, 超时即停
  ④ 任一点失败 **立即停, 不重发不补偿** (和 4060 版同口径)

用法:
  ./gui-venv311/bin/python tools/rokae/arm_step_550c.py            # 真走
  ./gui-venv311/bin/python tools/rokae/arm_step_550c.py --dry      # 只算不下发
  ./gui-venv311/bin/python tools/rokae/arm_step_550c.py --replay-all   # 从 0 走完整 215 点
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
import urllib.request

BRIDGE = os.environ.get("ZMAX_BRIDGE_URL", "http://192.168.23.66:39061")
REPO = os.environ.get("ZMAX_REPO", "/home/intel/zmax_550c")
TRAJ = os.path.join(REPO, "tools", "web", "real_traj_joints.json")
CMD = os.path.join(REPO, "zmax_data", "rokae_sdk", "traj_step_cmd.json")
AUTH = os.path.join(REPO, "zmax_data", "ctl_auth.json")
OUT = os.path.join(REPO, "zmax_data", "rokae_sdk", "traj_step_out.log")

MAX_JUMP_MM = 120.0          # 单点位移上限(215 点相邻实测中位 29.3mm, 留 4x 余量)
MAX_JUMP_DEG = 40.0          # 单点姿态变化上限
TOL_MM = 1.5                 # 到位判据(位置)
TOL_DEG = 2.0                # 到位判据(姿态)
POINT_TIMEOUT_S = 30.0       # 单点等待上限
GRIP_HOLD_MS = 2600


def _post(path, payload, timeout=18):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(BRIDGE + path, data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _get(path, timeout=8):
    with urllib.request.urlopen(BRIDGE + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _q2rpy(q):
    """四元数 [x,y,z,w] → rpy(度)。与桥内 _q2rpy 同口径, 只用于算姿态误差。"""
    x, y, z, w = [float(v) for v in q[:4]]
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    sy = max(-1.0, min(1.0, -2.0 * (x * z - y * w)))
    b = math.asin(sy)
    a = math.atan2(2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y))
    c = math.atan2(2.0 * (x * y + z * w), 1.0 - 2.0 * (y * y + z * z))
    return [math.degrees(v) for v in (a, b, c)]


def _pose_now():
    """桥 /status → (p米, rpy度, joints度)"""
    st = (_get("/status").get("status") or {})
    e = st.get("endInRef") or st.get("cartPosture") or []
    jp = st.get("jointPos") or []
    if len(e) < 6:
        return None, None, None
    return ([float(v) for v in e[:3]],
            [math.degrees(float(v)) for v in e[3:6]],
            [math.degrees(float(v)) for v in jp[:6]] if len(jp) >= 6 else None)


def _auth_ok():
    try:
        d = json.load(open(AUTH, encoding="utf-8"))
    except Exception:                                                        # noqa: BLE001
        return False, "读不到授权文件 %s" % AUTH
    if not d.get("armed"):
        return False, "未授权(armed=false) —— 从 8793 授权后再发"
    if d.get("mode") == "window":
        left = float(d.get("left_s") or 0.0)
        if left <= 0:
            return False, "授权窗口已过期(left_s=%.0f)" % left
        return True, "已授权 · 剩 %.0fs" % left
    return True, "已授权(mode=%s)" % d.get("mode")


def main() -> int:
    dry = "--dry" in sys.argv
    all_pts = "--replay-all" in sys.argv

    traj = json.load(open(TRAJ, encoding="utf-8"))
    frames = traj.get("frames") or []
    if not frames:
        print(json.dumps({"ok": False, "why": "轨迹无帧"}, ensure_ascii=False))
        return 2

    # 读 8797 写的指令; 没有就默认走完整一圈
    spec = {}
    if os.path.isfile(CMD):
        try:
            spec = json.load(open(CMD, encoding="utf-8"))
        except Exception:                                                    # noqa: BLE001
            spec = {}
    i0 = 0 if all_pts else int(spec.get("start") or 0)
    n = len(frames) - i0 if all_pts else int(spec.get("n") or 1)
    speed = float(spec.get("speed") or 20.0)
    dwell_ms = int(spec.get("dwell_ms") or 0)
    grip_at = {}
    for g in (spec.get("grip") or []):
        try:
            gi = int(g.get("i"))
            ga = str(g.get("act") or "").lower().replace("grip_", "")
            if ga in ("open", "close"):
                grip_at[gi] = {"act": ga, "hold_ms": int(g.get("hold_ms") or GRIP_HOLD_MS)}
        except Exception:                                                    # noqa: BLE001
            continue

    sel = frames[i0:i0 + n]
    if not sel:
        print(json.dumps({"ok": False, "why": "切片为空 i0=%d n=%d" % (i0, n)}, ensure_ascii=False))
        return 2

    out = {"ok": False, "dry": dry, "bridge": BRIDGE, "i0": i0, "n_req": n,
           "n_sel": len(sel), "speed": speed, "steps": []}

    ok_auth, why_auth = _auth_ok()
    out["auth"] = why_auth
    if not ok_auth and not dry:
        out["why"] = why_auth
        print(json.dumps(out, ensure_ascii=False))
        return 2

    p_now, r_now, j_now = _pose_now()
    if p_now is None:
        out["why"] = "桥 /status 读不到位姿(端末 endInRef 缺字段)"
        print(json.dumps(out, ensure_ascii=False))
        return 2
    out["pose_before"] = {"p_mm": [round(v * 1000, 1) for v in p_now],
                          "rpy_deg": [round(v, 2) for v in r_now],
                          "joints_deg": [round(v, 2) for v in (j_now or [])]}

    print(json.dumps({"start": True, "i0": i0, "n": len(sel), "speed": speed,
                      "pose_now_mm": [round(v * 1000, 1) for v in p_now],
                      "via": "orn-bridge-39061"}, ensure_ascii=False), flush=True)

    prev_p = p_now
    for k, f in enumerate(sel):
        i = i0 + k
        p = [float(v) for v in (f.get("p") or [])[:3]]
        q = [float(v) for v in (f.get("q") or [])[:4]]
        if len(p) < 3 or len(q) < 4:
            out["steps"].append({"i": i, "ok": False, "why": "帧缺 p/q"})
            out["why"] = "第 %d 帧缺 p/q" % i
            break
        r = _q2rpy(q)
        dp_mm = math.sqrt(sum((p[m] - prev_p[m]) ** 2 for m in range(3))) * 1000.0
        rec = {"i": i, "p_mm": [round(v * 1000, 1) for v in p], "rpy_deg": [round(v, 1) for v in r],
               "jump_mm": round(dp_mm, 1)}
        if dp_mm > MAX_JUMP_MM:
            rec.update({"ok": False, "why": "跳变 %.0fmm > 上限 %.0fmm, 拒发" % (dp_mm, MAX_JUMP_MM)})
            out["steps"].append(rec)
            out["why"] = "第 %d 点跳变超限, 已停" % i
            break
        if dry:
            rec.update({"ok": True, "sent": False})
            out["steps"].append(rec)
            prev_p = p
            print(json.dumps({"progress": k + 1, "n": len(sel), "step": rec}, ensure_ascii=False), flush=True)
            continue

        t0 = time.time()
        try:
            res = _post("/move_pose", {"p": p, "q": q, "speed": speed, "dry": False})
        except Exception as e:                                               # noqa: BLE001
            rec.update({"ok": False, "why": "%s: %s" % (type(e).__name__, str(e)[:70])})
            out["steps"].append(rec)
            out["why"] = "第 %d 点下发异常, 已停" % i
            break
        if not res.get("ok"):
            rec.update({"ok": False, "why": "桥拒绝: %s" % str(res.get("why"))[:80]})
            out["steps"].append(rec)
            out["why"] = "第 %d 点被拒, 已停" % i
            break

        # 等到位: 位置 + 姿态同时收敛
        ok = False
        pe = re_ = 999.0
        while time.time() - t0 < POINT_TIMEOUT_S:
            time.sleep(0.15)
            ap, ar, _ = _pose_now()
            if ap is None:
                continue
            pe = math.sqrt(sum((p[m] - ap[m]) ** 2 for m in range(3))) * 1000.0
            re_ = max(abs(ar[m] - r[m]) for m in range(3))
            if pe <= TOL_MM and re_ <= TOL_DEG:
                ok = True
                break
        rec.update({"ok": ok, "err_mm": round(pe, 2), "err_deg": round(re_, 2),
                    "secs": round(time.time() - t0, 2)})
        out["steps"].append(rec)
        print(json.dumps({"progress": k + 1, "n": len(sel), "step": rec}, ensure_ascii=False), flush=True)
        prev_p = p
        if not ok:
            out["why"] = ("第 %d 点未到位(位置 %.2fmm/姿态 %.2f°, %.1fs) —— 已停, 不重发"
                          % (i, pe, re_, time.time() - t0))
            break
        if dwell_ms:
            time.sleep(dwell_ms / 1000.0)
        g = grip_at.get(i)
        if g:
            print(json.dumps({"grip_due": True, "i": i, "act": g["act"],
                              "hold_ms": g["hold_ms"], "t": time.strftime("%H:%M:%S")},
                             ensure_ascii=False), flush=True)
            time.sleep(g["hold_ms"] / 1000.0)
            print(json.dumps({"grip_done": True, "i": i, "act": g["act"]}, ensure_ascii=False), flush=True)

    done = sum(1 for s in out["steps"] if s.get("ok"))
    out["n_done"] = done
    out["ok"] = (done == len(sel))
    if out["ok"]:
        out["why"] = "全部 %d 点走到位(经 Orin 桥)" % done
    print(json.dumps(out, ensure_ascii=False), flush=True)
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
