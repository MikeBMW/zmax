#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""arm_step_traj.py —— 真机「按真实轨迹一个点一个点走」(同步操作的真机腿)

老倪 2026-11-13: 「同步操作 我输入 10, 则右臂仿真先走10个点, 然后驱动真实右臂走10个点」

口径(与仿真侧同源): 输入帧 = tools/web/real_traj_joints.json 的 frames[0:N].j
  —— 6 轴**关节角真值**(录制里 SDK 直读), 所以姿态/翻面一起保真, 不走笛卡尔 IK。

为什么用 MoveAbsJ(关节绝对目标) 而不是 move_line:
  · 逐点走本来就是一停一走, 不需要直线插补; 关节空间避开 50102/50120 奇异与 50113 姿态阈值
  · 绝对目标 ⇒ 每点独立, 不累积漂移(相对运动走 N 点的滚雪球误差实测有过 27mm)

安全(缺一不下发):
  ① ctl_auth.json 已授权(执行器同一真源, 由调用方先校验)
  ② 前置 power=on + operation=idle + 非 drag
  ③ 单点关节跳变 > MAX_JUMP_DEG 拒发(防跨段瞬移)
  ④ 逐点等到位(关节角误差 ≤ tol_deg 且 operationState=idle); 任一点失败 **立即停, 不重发不补偿**

用法(本机容器内, 由 rokae_sdk_run.sh 挂载):
  bash tools/rokae_sdk_run.sh --script arm_step_traj.py            # 读 /sdk/traj_step_cmd.json 真走
  bash tools/rokae_sdk_run.sh --script arm_step_traj.py --dry      # 只算不down发
"""
from __future__ import annotations

import json
import math
import os
import sys
import time

sys.path.insert(0, os.environ.get("ZMAX_SDK_DIR", "/sdk"))
import xcoresdk_python as x  # noqa: E402

IP = os.environ.get("ZMAX_ROBOT_IP", "192.168.23.160")
CMD = os.environ.get("ZMAX_STEP_CMD", "/sdk/traj_step_cmd.json")
MAX_JUMP_DEG = 30.0          # 单点关节跳变上限(真机一次转 >30° 有撞/绕线风险)
TOL_DEG = 0.6                # 到位判据(关节角)
POINT_TIMEOUT_S = 60.0       # 单点等待上限


def joints(r):
    v = r.jointPos({})
    if isinstance(v, dict):
        for k in ("jointPos", "joint", "values", "data"):
            if k in v:
                v = v[k]
                break
        else:
            v = list(v.values())[0]
    return [float(t) for t in list(v)[:6]]


def opstate(r):
    return str(r.operationState({}))


def main() -> int:
    dry = "--dry" in sys.argv
    if not os.path.isfile(CMD):
        print(json.dumps({"ok": False, "why": "缺少指令文件 %s" % CMD}, ensure_ascii=False))
        return 2
    spec = json.load(open(CMD, encoding="utf-8"))
    frames = spec.get("frames") or []
    n = int(spec.get("n") or len(frames))
    frames = frames[:n]
    speed = float(spec.get("speed") or 5.0)
    dwell_ms = int(spec.get("dwell_ms") or 0)
    if not frames:
        print(json.dumps({"ok": False, "why": "指令里没有关节角帧"}, ensure_ascii=False))
        return 2

    out = {"ok": False, "dry": dry, "n_req": n, "n_frames": len(frames),
           "speed": speed, "ip": IP, "steps": []}

    r = x.xMateRobot()
    try:
        r.connectToRobot(IP)
    except Exception as e:                                                   # noqa: BLE001
        out["why"] = "连不上控制器 %s: %s: %s" % (IP, type(e).__name__, e)
        print(json.dumps(out, ensure_ascii=False))
        return 2

    st = {"power": str(r.powerState({})), "op": opstate(r)}
    out["state_before"] = st
    power_ok = "on" in st["power"].lower()
    op_ok = "idle" in st["op"].lower() or "automatic" in st["op"].lower()
    if not (power_ok and op_ok):
        out["why"] = ("前置不满足: power=%s(op=on 才行) · operation=%s(idle 才行; "
                      "drag=示教器要关拖动, manual=要切自动)" % (st["power"], st["op"]))
        print(json.dumps(out, ensure_ascii=False))
        return 2

    cur = joints(r)
    out["joints_before_deg"] = [round(math.degrees(v), 2) for v in cur]

    if dry:                                                                  # 只算目标与跳变, 零运动
        prev = cur
        for i, j in enumerate(frames):
            jt = [float(v) for v in j]
            jump = max(abs(math.degrees(b - a)) for a, b in zip(prev, jt))
            out["steps"].append({"i": i, "target_deg": [round(math.degrees(v), 2) for v in jt],
                                 "max_jump_deg": round(jump, 2),
                                 "ok": jump <= MAX_JUMP_DEG, "sent": False})
            prev = jt
        out["ok"] = all(s["ok"] for s in out["steps"])
        out["note"] = "dry: 只算目标与关节跳变, 未下发"
        print(json.dumps(out, ensure_ascii=False))
        try:
            r.disconnectFromRobot({})
        except Exception:                                                    # noqa: BLE001
            pass
        return 0 if out["ok"] else 1

    print(json.dumps({"start": True, "n": len(frames), "speed": speed,
                      "joints_now_deg": [round(math.degrees(v), 2) for v in cur]}, ensure_ascii=False), flush=True)
    prev = cur
    for i, j in enumerate(frames):
        jt = [float(v) for v in j]
        jump = max(abs(math.degrees(b - a)) for a, b in zip(prev, jt))
        rec = {"i": i, "target_deg": [round(math.degrees(v), 2) for v in jt],
               "max_jump_deg": round(jump, 2)}
        if jump > MAX_JUMP_DEG:
            rec.update({"ok": False, "why": "关节跳变 %.1f° > 上限 %.0f°, 拒发(防瞬移)" % (jump, MAX_JUMP_DEG)})
            out["steps"].append(rec)
            out["why"] = "第 %d 点跳变超限, 已停" % i
            break
        if "idle" not in opstate(r).lower():
            rec.update({"ok": False, "why": "上一点还没停稳(operationState=%s)" % opstate(r)})
            out["steps"].append(rec)
            out["why"] = "第 %d 点前设备非 idle, 已停" % i
            break
        t0 = time.time()
        try:
            bj = joints(r)
            ec = {}
            r.moveReset({})
            cmd = x.MoveAbsJCommand(x.JointPosition([float(v) for v in jt]), speed, -1)
            r.moveAppend([cmd], x.PyString("step%d" % i), ec)
            if ec.get("ec", 0) != 0:
                rec.update({"ok": False, "why": "moveAppend 被拒: %s" % (ec,)})
                out["steps"].append(rec)
                out["why"] = "第 %d 点被控制器拒绝, 已停" % i
                break
            r.moveStart({})
        except Exception as e:                                               # noqa: BLE001
            rec.update({"ok": False, "why": "%s: %s" % (type(e).__name__, e)})
            out["steps"].append(rec)
            out["why"] = "第 %d 点下发异常, 已停" % i
            break
        # 等到位: 关节角收敛 + idle
        ok = False
        aj = bj
        while time.time() - t0 < POINT_TIMEOUT_S:
            time.sleep(0.12)
            aj = joints(r)
            err = max(abs(math.degrees(b - a)) for a, b in zip(jt, aj))
            if err <= TOL_DEG and "idle" in opstate(r).lower():
                ok = True
                break
        err = max(abs(math.degrees(b - a)) for a, b in zip(jt, aj))
        rec.update({"ok": ok, "err_deg": round(err, 2), "secs": round(time.time() - t0, 2),
                    "joints_after_deg": [round(math.degrees(v), 2) for v in aj]})
        out["steps"].append(rec)
        # 📡 增量进度: 页面轮询 status 时靠这行看逐点走到哪(不带它就只能等全跑完)
        print(json.dumps({"progress": i + 1, "n": len(frames), "step": rec}, ensure_ascii=False), flush=True)
        prev = aj
        if not ok:
            out["why"] = ("第 %d 点未到位(误差 %.2f° > %.1f°, 用时 %.1fs) —— 已停, 不重发"
                          % (i, err, TOL_DEG, time.time() - t0))
            break
        if dwell_ms:
            time.sleep(dwell_ms / 1000.0)

    done = sum(1 for s in out["steps"] if s.get("ok"))
    out["n_done"] = done
    out["ok"] = (done == len(frames))
    out["state_after"] = {"power": str(r.powerState({})), "op": opstate(r)}
    try:
        out["joints_after_final_deg"] = [round(math.degrees(v), 2) for v in joints(r)]
    except Exception:                                                        # noqa: BLE001
        pass
    if out["ok"]:
        out["why"] = "全部 %d 点走到位" % done
    print(json.dumps(out, ensure_ascii=False))
    try:
        r.disconnectFromRobot({})
    except Exception:                                                        # noqa: BLE001
        pass
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
