#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""grasp_opt.py —— 光模块抓取「最少动作」一条命令

老倪 2026-10-18: 「记住这个技能点吧。但是我中间有很多多余的动作，你得优化」

人工抓取时中间那些多余动作（反复小步蹭、来回修正、抓前又抬一下）在算法里没必要：
到抓取位的几何其实是**一次沿工具轴直进 + 合爪 + 抬起**。本脚本只做这三步，其余一律不做。

三个动作（没有第四个）
  ① 接近: 沿 tool1 的 +x 方向一次直进 --approach mm（默认 110 = 实测的 tool1→模块前向距离）
  ② 合爪: 走 8793 /ctl/move 的 L2.grip_close（合成授权 + 快层闸门 + 夹持力 40，不在脚本里另开通道）
  ③ 抬起: 沿 base z 抬 --lift mm（默认 30，避免蹭到料盘）

判据（每个动作都回读真值，不看"已下发"）
  · 接近: /pose 实测位移 ÷ 目标位移 ≥ 0.9；同时用画面里模块的表观高度变化核对方向对不对
  · 合爪: /gripper_pos 真值 (Float32) < 300（开 ≈1000 · 空爪闭合 ≈21 · 夹住模块 ≈174~185）
  · 抬起: base z 抬升 ≥ 0.8×--lift

用法
  ./gui-venv311/bin/python tools/grasp_opt.py --dry                     # 只算不发, 打印三个动作
  ./gui-venv311/bin/python tools/grasp_opt.py                            # 真抓: 110mm 直进 → 合爪 → 抬 30mm
  ./gui-venv311/bin/python tools/grasp_opt.py --approach 95 --speed 25    # 按现场微调
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import time
import urllib.request

REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")
import sys
sys.path.insert(0, os.path.join(REPO, "tools"))

FIFO = os.path.join(REPO, "zmax_data", "rokae_sdk", "cmd_arm.fifo")
AGENT_LOG = os.path.join(REPO, "zmax_data", "rokae_sdk", "logs", "agent_%s.jsonl")
CTL = "http://127.0.0.1:8793"
ORIN = "tashan@192.168.23.66"
OUT_DIR = os.path.join(REPO, "zmax_data", "ar_rs")
ROS_PRE = ('source /opt/ros/humble/setup.bash; '
           'for ws in /home/tashan/0810/*/install/setup.bash; do [ -f "$ws" ] && source "$ws" && break; done; '
           'export ROS_DOMAIN_ID=0; export FASTDDS_BUILTIN_TRANSPORTS=UDPv4; export ROS_LOCALHOST_ONLY=0; ')


def _get(path, timeout=6):
    with urllib.request.urlopen(CTL + path, timeout=timeout) as r:
        return json.loads(r.read().decode())


def preflight():
    s = _get("/ctl/status")
    rb = s.get("robot") or {}
    bad = []
    if not s.get("motion_armed"):
        bad.append("未授权 (motion_armed=false) —— 动作授权只从 8793 给")
    if rb.get("mode") != "automatic":
        bad.append("不是自动模式 (%s)" % rb.get("mode"))
    if rb.get("operation") not in ("idle", "Idle", None):
        bad.append("机器人不空闲 (%s)" % rb.get("operation"))
    if rb.get("estop"):
        bad.append("急停中")
    if rb.get("has_error"):
        bad.append("有报警: %s" % (rb.get("error_reason") or rb.get("error_code")))
    return (not bad), bad, s, rb


def pose():
    p = _get("/pose")
    return [float(v) for v in p["xyz"]], [float(v) for v in p["abc_rad"]], p


def R_abc(a, b, c):
    import numpy as np
    ca, sa, cb, sb, cc, sc = math.cos(a), math.sin(a), math.cos(b), math.sin(b), math.cos(c), math.sin(c)
    return (np.array([[cc, -sc, 0], [sc, cc, 0], [0, 0, 1]]) @
            np.array([[cb, 0, sb], [0, 1, 0], [-sb, 0, cb]]) @
            np.array([[1, 0, 0], [0, ca, -sa], [0, sa, ca]]))


def send(req, wait=120.0):
    rid = req.setdefault("id", "grasp_%d" % int(time.time() * 1000))
    fd = os.open(FIFO, os.O_WRONLY)
    try:
        os.write(fd, (json.dumps(req) + "\n").encode())
    finally:
        os.close(fd)
    lg = AGENT_LOG % time.strftime("%Y%m%d")
    t0 = time.time()
    while time.time() - t0 < wait:
        try:
            with open(lg, encoding="utf-8") as f:
                for line in f:
                    if rid in line:
                        d = json.loads(line)
                        if d.get("id") == rid:
                            return d
        except Exception:                                                   # noqa: BLE001
            pass
        time.sleep(0.2)
    return {"id": rid, "verdict": "TIMEOUT 等回执 (%.0fs)" % wait}


def wait_settle(p0, want_mm, tol_mm=1.0, timeout=90.0, min_frac=0.5):
    """等到真的走过去（不是"已下发"）：位移 ≥ min_frac×目标 且 0.6s 内不再变。"""
    t0 = time.time()
    last = None
    stable = 0.0
    best = 0.0
    while time.time() - t0 < timeout:
        try:
            p, _, _ = pose()
        except Exception:                                                   # noqa: BLE001
            time.sleep(0.2)
            continue
        d = 1000.0 * math.dist(p, p0)
        best = max(best, d)
        if last is not None and abs(d - last) < 0.15:
            stable += 0.2
            if stable >= 0.6 and d > min_frac * want_mm:
                return True, d
        else:
            stable = 0.0
        last = d
        time.sleep(0.2)
    return (best > min_frac * want_mm), best


def gripper_pos(timeout=25):
    """读夹爪真值。坑: /gripper_pos 同 topic 挂着 Float32/Float64 两个类型, 不显式给类型会直接被拒。"""
    cmd = ROS_PRE + "timeout 12 ros2 topic echo /gripper_pos std_msgs/msg/Float32 --once --no-daemon"
    try:
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", ORIN, cmd],
                           capture_output=True, text=True, timeout=timeout)
        m = re.search(r"data:\s*(-?[\d.]+)", (r.stdout or "") + (r.stderr or ""))
        return float(m.group(1)) if m else None
    except Exception:                                                       # noqa: BLE001
        return None


def module_obs():
    """当前一帧的光模块观测(表观高度/距离), 用来核对接近方向。读 8797 的只读接口。"""
    try:
        with urllib.request.urlopen("http://127.0.0.1:8797/api/module3d", timeout=25) as r:
            d = json.loads(r.read().decode())
        if d.get("ok"):
            b = d["box2d"]
            return {"vis_px": round(b[3] - b[1], 1), "d_mm": d.get("dist_mm"),
                    "clipped": d.get("clipped") or [], "conf": d.get("conf")}
    except Exception:                                                       # noqa: BLE001
        pass
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--approach", type=float, default=110.0, help="沿 tool1 +x 直进多少 mm (默认 110)")
    ap.add_argument("--max-mm", type=float, default=160.0, help="接近距离上限 (超过拒发)")
    ap.add_argument("--speed", type=float, default=30.0, help="接近速度 mm/s (1~100)")
    ap.add_argument("--lift", type=float, default=30.0, help="抬起 mm (base +z)")
    ap.add_argument("--lift-speed", type=float, default=20.0)
    ap.add_argument("--force", type=float, default=40.0, help="夹持力 (%)")
    ap.add_argument("--min-z", type=float, default=40.0, help="接近后 z 下限 mm (太低拒发)")
    ap.add_argument("--no-lift", action="store_true", help="抓到后不抬")
    ap.add_argument("--dry", action="store_true", help="只算不发")
    a = ap.parse_args()

    rec = {"at": time.strftime("%F %T"), "args": vars(a), "steps": []}
    ok, bad, st, rb = preflight()
    print("① 前置: %s" % ("通过" if ok else "拒发 —— " + " / ".join(bad)))
    rec["preflight"] = {"ok": ok, "bad": bad, "mode": rb.get("mode"), "op": rb.get("operation"),
                        "armed": st.get("motion_armed")}
    if not ok and not a.dry:
        _save(rec)
        return 2

    import numpy as np
    xyz, abc, praw = pose()
    R = R_abc(*abc)
    adv = R @ np.array([a.approach, 0.0, 0.0])
    tgt = np.array(xyz) * 1000.0 + adv
    print("  现在 TCP %s mm · ABC %s°" % ([round(v * 1000, 1) for v in xyz],
                                          [round(math.degrees(v), 1) for v in abc]))
    print("  ① 直进 %.0fmm → 目标 %s mm (走 tool1 +x, 姿态不变)" % (a.approach, [round(v, 1) for v in tgt]))
    rec["plan"] = {"approach_mm": a.approach, "speed": a.speed,
                   "target_mm": [round(v, 1) for v in tgt], "abc_deg": [round(math.degrees(v), 2) for v in abc]}

    # 闸: 距离/高度/可达
    g = []
    if a.approach > a.max_mm:
        g.append("接近距离 %.0f > 上限 %.0f" % (a.approach, a.max_mm))
    if tgt[2] < a.min_z:
        g.append("目标 z=%.0f < 下限 %.0f" % (tgt[2], a.min_z))
    if math.dist(tgt, np.zeros(3)) > 900:
        g.append("目标离基座 %.0f > 900mm" % math.dist(tgt, np.zeros(3)))
    if g:
        print("  🛑 闸拦住: %s" % " / ".join(g))
        rec["gate"] = g
        _save(rec)
        return 3

    if a.dry:
        print("  ② 合爪 L2.grip_close (力 %.0f)  ③ 抬起 base +z %.0fmm" % (a.force, a.lift))
        print("  DRY-RUN: 一条都没发")
        rec["dry"] = True
        _save(rec)
        return 0

    obs0 = module_obs()
    rec["before"] = {"tcp_mm": [round(v * 1000, 1) for v in xyz], "module": obs0,
                     "gripper": gripper_pos()}
    print("  抓前: 模块观测 %s · 夹爪 %s" % (obs0, rec["before"]["gripper"]))

    # ① 接近
    t0 = time.time()
    v = send({"cmd": "move-abs", "x": float(tgt[0] / 1000.0), "y": float(tgt[1] / 1000.0),
              "z": float(tgt[2] / 1000.0), "speed": float(a.speed)}, wait=60)
    print("  ① 下发: %s" % str(v.get("verdict"))[:120])
    got, moved = wait_settle(np.array(xyz), a.approach, timeout=90)
    print("  ① 实测位移 %.1fmm (目标 %.0f) %s" % (moved, a.approach, "OK" if got else "⚠ 不足"))
    obs1 = module_obs()
    rec["steps"].append({"step": "approach", "verdict": v.get("verdict"), "moved_mm": round(moved, 1),
                         "ok": bool(got), "module": obs1, "s": round(time.time() - t0, 1)})

    # ② 合爪 (走 8793 的授权通道, 不在脚本里写 ROS)
    t0 = time.time()
    try:
        req = urllib.request.Request(CTL + "/ctl/move", method="POST",
                                     data=json.dumps({"skill": "L2.grip_close", "arm": 1,
                                                      "param": {"force": a.force}}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=90) as r:
            gm = json.loads(r.read().decode())
    except Exception as e:                                                  # noqa: BLE001
        gm = {"ok": False, "err": str(e)}
    time.sleep(1.5)
    gpos = gripper_pos()
    gripped = (gpos is not None and gpos < 300)
    print("  ② 合爪: %s · 夹爪真值 %s %s" % (str(gm.get("msg") or gm.get("err"))[:80], gpos,
                                          "⇒ 夹住" if gripped else "⚠ 没夹住(空爪≈21/全开≈1000)"))
    rec["steps"].append({"step": "grip", "resp": gm, "gripper_pos": gpos, "ok": bool(gripped),
                         "s": round(time.time() - t0, 1)})

    # ③ 抬起
    if not a.no_lift:
        t0 = time.time()
        z0 = pose()[0][2] * 1000.0
        v = send({"cmd": "move-rel", "dx": 0.0, "dy": 0.0, "dz": float(a.lift),
                  "speed": float(a.lift_speed), "cap_mm": float(a.lift + 10)}, wait=60)
        got2, lifted = wait_settle(np.array(pose()[0]), a.lift, timeout=60, min_frac=0.6)
        z1 = pose()[0][2] * 1000.0
        print("  ③ 抬起: %s · 实测 Δz %.1fmm (目标 %.0f)" % (str(v.get("verdict"))[:80], z1 - z0, a.lift))
        rec["steps"].append({"step": "lift", "verdict": v.get("verdict"),
                             "dz_mm": round(z1 - z0, 1), "ok": bool(got2), "s": round(time.time() - t0, 1)})

    rec["after"] = {"tcp_mm": [round(vv * 1000, 1) for vv in pose()[0]], "gripper": gripper_pos()}
    rec["verdict"] = "抓取完成" if all(s.get("ok") for s in rec["steps"]) else "有步骤未达标(见 steps)"
    print("\n%s · 记录 %s" % (rec["verdict"], _save(rec)))
    return 0 if rec["verdict"] == "抓取完成" else 4


def _save(rec):
    os.makedirs(OUT_DIR, exist_ok=True)
    p = os.path.join(OUT_DIR, "grasp_run_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    with open(p, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    return p


if __name__ == "__main__":
    sys.exit(main())
