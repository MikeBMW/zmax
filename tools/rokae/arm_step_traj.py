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
MAX_JUMP_DEG = 40.0          # 单点关节跳变上限(真机一次转 >40° 有撞/绕线风险; 本条轨迹相邻点实测最大 31.1°)
TOL_DEG = 0.6                # 到位判据(关节角)
POINT_TIMEOUT_S = 60.0       # 单点等待上限
GRIP_HOLD_MS = 2600          # 🆕 夹爪动作窗口: 报到 grip_due 后原地等一下, 让上层(8797)把开合发下去再继续


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


# ═══════════════════════════════════════════════════════════════════════════
# 🔬 数据采集 (老倪 2026-11-15「这是最后一次真实机器运行, 记录所有数据/图片/位姿/时间」)
#    每点记录: 墙钟时间 · 相对时间 · 关节角 · TCP(xyz) · RPY · 关节跳变 · 到位误差 · 耗时 · 甘特段
#    在 AOI 到位点触发相机拍照(#156 金手指 10082 / #172 表面 10083), 图片落到主机 zmax_data
#    ⚠ 采集是旁路行为: 任何一项失败只记 warning, 绝不影响运动下发与安全闸
# ═══════════════════════════════════════════════════════════════════════════
CAP_DIR = os.environ.get("ZMAX_CAP_DIR") or "/sdk/capture"      # 容器内(主机 zmax_data/rokae_sdk/capture)
CAP_ON = (os.environ.get("ZMAX_CAPTURE") or "1") != "0"
_T0_WALL = time.time()

# 甘特分段(与 tools/ss_meta_task_ar.py 的 _REPLAY_SEGS 同源同界, 便于逐段对账)
GANTRY_SEGS = [
    (0, 9, "抓取(合爪#9)"), (10, 40, "插入孔内"), (41, 90, "转运/举升"),
    (91, 113, "拔出模块"), (114, 119, "过渡"), (120, 144, "扫码(举高段)"),
    (145, 149, "过渡"), (150, 160, "金手指检测"), (161, 161, "过渡"),
    (162, 193, "表面检测"), (194, 197, "过渡"), (198, 204, "下放入盘"),
    (205, 205, "松开分拣(#205)"), (206, 214, "回位"),
]
# 到位即拍照: 点 -> (端口, 名称)
AOI_ON_ARRIVE = {156: (10082, "金手指"), 172: (10083, "表面")}


def seg_of(i):
    for i0, i1, nm in GANTRY_SEGS:
        if i0 <= i <= i1:
            return nm
    return "?"


def read_tcp(r):
    """TCP + RPY (mm/deg)。失败返回 None, 不抛。"""
    try:
        ec = {}
        cp = r.cartPosture(x.CoordinateType.endInRef, ec)
        return {"tcp": [round(float(v), 3) for v in cp.trans],
                "rpy": [round(float(v), 4) for v in cp.rpy]}
    except Exception:                                                    # noqa: BLE001
        return None


def cap_aoi(i, port, label):
    """到点拍照: 调主机 AOI /picture?grab=1 存图 + 记录响应。失败只 warning。"""
    if not CAP_ON:
        return None
    try:
        import urllib.request
        os.makedirs(CAP_DIR, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        base = "%s/aoi_i%03d_%s_%s" % (CAP_DIR, i, label, ts)
        url = "http://127.0.0.1:%d/picture?grab=1" % port
        req = urllib.request.Request(url, headers={"User-Agent": "zmax-capture"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            body = resp.read()
            ctype = resp.headers.get("Content-Type", "")
        if body[:2] == b"\xff\xd8" or "image" in ctype:
            with open(base + ".jpg", "wb") as f:
                f.write(body)
            info = {"i": i, "port": port, "label": label, "jpg": base + ".jpg",
                    "bytes": len(body), "t_wall": time.strftime("%Y-%m-%dT%H:%M:%S")}
        else:
            with open(base + ".json", "wb") as f:
                f.write(body)
            info = {"i": i, "port": port, "label": label, "json": base + ".json",
                    "bytes": len(body), "ctype": ctype,
                    "t_wall": time.strftime("%Y-%m-%dT%H:%M:%S")}
        print(json.dumps({"capture": info}, ensure_ascii=False), flush=True)
        return info
    except Exception as e:                                               # noqa: BLE001
        print(json.dumps({"capture_err": {"i": i, "port": port,
                                          "why": "%s: %s" % (type(e).__name__, e)}},
                         ensure_ascii=False), flush=True)
        return None


def _send_wait(r, jt, speed):
    """下发一条 MoveAbsJ 并等到位。返回 (ok, 最终误差°, 用时s)。"""
    t0 = time.time()
    r.moveReset({})
    ec = {}
    r.moveAppend([x.MoveAbsJCommand(x.JointPosition([float(v) for v in jt]), speed, -1)],
                 x.PyString("mv%d" % (int(t0 * 1000) % 100000)), ec)
    if ec.get("ec", 0) != 0:
        return False, 999.0, time.time() - t0
    r.moveStart({})
    while time.time() - t0 < POINT_TIMEOUT_S:
        time.sleep(0.12)
        aj = joints(r)
        err = max(abs(math.degrees(b - a)) for a, b in zip(jt, aj))
        if err <= TOL_DEG and "idle" in opstate(r).lower():
            return True, err, time.time() - t0
    aj = joints(r)
    return False, max(abs(math.degrees(b - a)) for a, b in zip(jt, aj)), time.time() - t0


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
    # 🆕 2026-11-13 老倪:「真机的轨迹, 也有夹爪开启或关闭的动作…回放的时候, 增加夹爪的开合动作」
    #   轨迹文件里只有关节角(录制时没记夹爪事件) ⇒ 夹爪动作由**计划**给出: [{"i":12,"act":"open"|"close"}]
    #   本脚本只负责"走到第 i 点后报 grip_due 并原地等 hold_ms", 真正的开合由上层 8797 统一发
    #   (同一条授权链, 不在这里绕过安全闸)。
    grip_plan = spec.get("grip") or []
    grip_hold = int(spec.get("grip_hold_ms") or GRIP_HOLD_MS)
    grip_at = {}
    for g in grip_plan:
        try:
            gi = int(g.get("i"))
            ga = str(g.get("act") or "").lower()
            if ga in ("open", "close", "grip_open", "grip_close"):
                grip_at[gi] = {"act": ga.replace("grip_", ""), "hold_ms": int(g.get("hold_ms") or grip_hold)}
        except Exception:                                                    # noqa: BLE001
            continue
    if not frames:
        print(json.dumps({"ok": False, "why": "指令里没有关节角帧"}, ensure_ascii=False))
        return 2

    out = {"ok": False, "dry": dry, "n_req": n, "n_frames": len(frames),
           "speed": speed, "ip": IP, "steps": [],
           "grip_plan": [{"i": k, "act": v["act"]} for k, v in sorted(grip_at.items())]}

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
    # 🔁 起点归位段 (2026-11-13 实测缺陷): 上一轮走完停在点 N, 再点「同步操作」是从点 1 起,
    #    |当前→点1| 可能 69° 远超 30° 闸 ⇒ 直接拒发(实测连点两次必失败)。
    #    这里按 ≤18°/段插中间点先归位到点 1, 再走正式点; 归位段单独上报, 不占 N 点。
    j0 = [float(v) for v in frames[0]]
    jump0 = max(abs(math.degrees(b - a)) for a, b in zip(prev, j0))
    if jump0 > MAX_JUMP_DEG:
        k = int(math.ceil(jump0 / (MAX_JUMP_DEG * 0.6)))
        mid = [[prev[m] + (j0[m] - prev[m]) * (t / float(k)) for m in range(6)]
               for t in range(1, k)]
        print(json.dumps({"prep": {"jump_deg": round(jump0, 1), "n_mid": len(mid),
                                   "seg_deg": round(jump0 / float(k), 1)}}, ensure_ascii=False), flush=True)
        for pi, pj in enumerate(mid):
            okp, errp, secp = _send_wait(r, pj, speed)
            print(json.dumps({"prep_progress": pi + 1, "n": len(mid), "ok": okp,
                              "err_deg": round(errp, 2), "secs": round(secp, 2)},
                             ensure_ascii=False), flush=True)
            if not okp:
                out["why"] = "归位段第 %d/%d 点未到位(误差 %.1f°), 已停 — 正式点一个没走" % (pi + 1, len(mid), errp)
                out["prep_steps"] = mid
                print(json.dumps(out, ensure_ascii=False))
                return 1
        prev = joints(r)
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
            # 🛑 人工断点(容器内没有 VSCode 调试器, 所以用旗标文件停) —— 停在**发指令之前**:
            #    触发: 存在 /sdk/stop_at_cmd (= 主机 zmax_data/rokae_sdk/stop_at_cmd, 该目录 rw 挂到 /sdk)
            #    停住时: 本点指令还没发 ⇒ 臂静止不动; 每 2s 复检, 删掉旗标即继续
            #    证据: 往 stdout(= traj_step_out.log) 打一行 JSON: 目标角/当前角/跳变/停多久
            _flag = os.environ.get("ZMAX_STOP_AT_CMD_FLAG") or "/sdk/stop_at_cmd"
            if os.environ.get("ZMAX_STOP_AT_CMD") == "1" or os.path.exists(_flag):
                _t_hold = time.time()
                print(json.dumps({"stop_at_cmd": True, "i": i,
                                  "target_deg": rec["target_deg"],
                                  "cur_deg": [round(math.degrees(v), 2) for v in bj],
                                  "max_jump_deg": rec["max_jump_deg"],
                                  "hint": "臂停在发指令前; 删掉 %s 继续" % _flag},
                                 ensure_ascii=False), flush=True)
                while os.path.exists(_flag) and (time.time() - _t_hold) < 3600:
                    time.sleep(2.0)
                print(json.dumps({"stop_at_cmd": "released", "i": i,
                                  "held_s": round(time.time() - _t_hold, 1)},
                                 ensure_ascii=False), flush=True)
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
        # 🔬 采集: 时间戳/相对时间/TCP/RPY/甘特段 —— 全部旁路, 失败不影响运动
        if CAP_ON:
            try:
                rec["t_wall"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                rec["t_rel"] = round(time.time() - _T0_WALL, 3)
                rec["seg"] = seg_of(i)
                _tp = read_tcp(r)
                if _tp:
                    rec["tcp"] = _tp["tcp"]
                    rec["rpy"] = _tp["rpy"]
            except Exception as _e:                                      # noqa: BLE001
                rec["cap_warn"] = "%s: %s" % (type(_e).__name__, _e)
        out["steps"].append(rec)
        # 📡 增量进度: 页面轮询 status 时靠这行看逐点走到哪(不带它就只能等全跑完)
        print(json.dumps({"progress": i + 1, "n": len(frames), "step": rec}, ensure_ascii=False), flush=True)
        # 📷 到点拍照(AOI 两路), 在臂停稳后立刻拍 —— 这是"到点一霎那"的真实画面
        _aoi = AOI_ON_ARRIVE.get(i)
        if _aoi and ok:
            _ci = cap_aoi(i, _aoi[0], _aoi[1])
            if _ci:
                rec["capture"] = _ci
        prev = aj
        if not ok:
            out["why"] = ("第 %d 点未到位(误差 %.2f° > %.1f°, 用时 %.1fs) —— 已停, 不重发"
                          % (i, err, TOL_DEG, time.time() - t0))
            break
        if dwell_ms:
            time.sleep(dwell_ms / 1000.0)
        # 🆕 夹爪: 正好走到这个点 ⇒ 报 grip_due(上层 8797 看到就发 L2.grip_open/close), 原地等动作窗口
        _g = grip_at.get(i)
        if _g:
            print(json.dumps({"grip_due": True, "i": i, "act": _g["act"], "hold_ms": _g["hold_ms"],
                              "t": time.strftime("%H:%M:%S")}, ensure_ascii=False), flush=True)
            time.sleep(_g["hold_ms"] / 1000.0)
            rec["grip"] = _g["act"]
            print(json.dumps({"grip_done": True, "i": i, "act": _g["act"]}, ensure_ascii=False), flush=True)

    done = sum(1 for s in out["steps"] if s.get("ok"))
    out["n_done"] = done
    out["ok"] = (done == len(frames))
    out["state_after"] = {"power": str(r.powerState({})), "op": opstate(r)}
    try:
        out["joints_after_final_deg"] = [round(math.degrees(v), 2) for v in joints(r)]
    except Exception:                                                        # noqa: BLE001
        pass
    # 📦 整轮快照落盘(最后一次真机运行的完整证据: 逐点位姿/TCP/时间/图/段)
    if CAP_ON:
        try:
            os.makedirs(CAP_DIR, exist_ok=True)
            out["_cap"] = {
                "started_wall": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(_T0_WALL)),
                "ended_wall": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "elapsed_s": round(time.time() - _T0_WALL, 2),
                "n_frames": len(frames), "n_done": done,
                "speed": speed, "dwell_ms": dwell_ms,
                "robot_ip": IP, "host": os.uname().nodename,
                "segs": [{"i0": a, "i1": b, "name": c} for a, b, c in GANTRY_SEGS],
                "aoi_on_arrive": {str(k): v for k, v in AOI_ON_ARRIVE.items()},
            }
            _snap = os.path.join(CAP_DIR, "run_%s.json" % time.strftime("%Y%m%d_%H%M%S",
                                                                       time.localtime(_T0_WALL)))
            with open(_snap, "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=1)
            out["_cap"]["snapshot"] = _snap
            print(json.dumps({"snapshot_saved": _snap, "n_steps": len(out["steps"])},
                             ensure_ascii=False), flush=True)
        except Exception as _e:                                              # noqa: BLE001
            print(json.dumps({"snapshot_err": "%s: %s" % (type(_e).__name__, _e)},
                             ensure_ascii=False), flush=True)
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
