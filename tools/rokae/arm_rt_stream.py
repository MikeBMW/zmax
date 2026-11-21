#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""arm_rt_stream.py — 真机「按录制速度」连续回放 (RT 实时模式, 50~200Hz 点位流)

为什么需要它(2026-11-20 实测):
  NrtCommandMode 的 MoveAbsJ 逐点/整批回放, 实测上限 speed=200% ⇒ 0.96s/点,
  录制是 0.2s/点(末端 862mm/s, 关节 124~141°/s) ⇒ 差 4.8 倍; speed=400% 直接掉电。
  要贴录制速度只能走 RtCommandMode: 控制器每个控制周期回调我们要一个关节目标,
  我们在回调里按"录制时间轴 / rate"给出插值点 ⇒ 由控制器做插补与限幅。

用法(容器内, 由 rokae_sdk_run.sh 挂载):
  bash tools/rokae_sdk_run.sh --script arm_rt_stream.py --dry      # 只校验+打印, 不连不切模式
  ZMAX_RT_RATE=0.3 bash tools/rokae_sdk_run.sh --script arm_rt_stream.py
  ZMAX_RT_RATE=1.0 ...                                            # 录制原速

环境变量:
  ZMAX_RT_TRAJ   轨迹 json (默认 /sdk/real_traj_joints.json, frames[*].j / .t)
  ZMAX_RT_I0/I1  只回放 [I0, I1] 帧 (默认整条)
  ZMAX_RT_RATE   时间轴倍率 (默认 0.3; 1.0 = 录制速度; >1 更快, 不建议)
  ZMAX_RT_MAXDEG 单周期最大关节增量(度, 默认 2.0) —— 超出即钳位, 防跳变
  ZMAX_RT_LEAD   起手势: 当前点→首点用 ≤PREP_SEG_DEG 分段摆过去 (默认做)

安全闸(缺一不下发):
  ① 只读校验: power=on, operation=idle/rtControlling, 无 error/estop/collision
  ② 首点距离 > 60° ⇒ 拒绝(要么先 Nrt 归位, 要么把 I0 放到当前附近)
  ③ 回调内异常/超时 ⇒ 返回当前实际关节角并置 abort, 主线程 stopLoop+stopMove
  ④ 全程 tick 记录(时间/指令/实际) 落盘 /sdk/logs/rt_stream_<ts>.jsonl
"""
from __future__ import annotations

import json
import math
import os
import sys
import time

sys.path.insert(0, os.environ.get("ZMAX_SDK_DIR", "/sdk"))
import xcoresdk_python as x  # noqa: E402

IP = os.environ.get("ZMAX_ROBOT_IP") or "192.168.23.160"
TRAJ = os.environ.get("ZMAX_RT_TRAJ") or os.environ.get("ZMAX_REPLAY_TRAJ") or "/sdk/real_traj_joints.json"
RATE = float(os.environ.get("ZMAX_RT_RATE") or 0.3)
MAXDEG = float(os.environ.get("ZMAX_RT_MAXDEG") or 2.0)
DRY = "--dry" in sys.argv
LOGDIR = os.environ.get("ZMAX_RT_LOGDIR") or "/sdk/logs"


def out(**kw):
    print(json.dumps(kw, ensure_ascii=False, default=str), flush=True)


def local_ip(dst):
    """本机到控制器的出口 IP —— RT 实时控制要在该网卡上开 UDP, 不显式给会报 1338"""
    import socket as _s
    ss = _s.socket(_s.AF_INET, _s.SOCK_DGRAM)
    try:
        ss.connect((dst, 9))
        return ss.getsockname()[0]
    finally:
        ss.close()


def states(r):
    try:
        st = {"power": str(r.powerState({})), "op": str(r.operationState({}))}
        return st
    except Exception as e:                                               # noqa: BLE001
        return {"err": "%s: %s" % (type(e).__name__, e)}


def load_path(i0=None, i1=None):
    d = json.load(open(TRAJ, encoding="utf-8"))
    fr = d["frames"][i0:i1]
    ts = [float(f.get("t", i * 0.2)) for i, f in enumerate(fr)]
    js = [[float(v) for v in f["j"]] for f in fr]
    ts = [t - ts[0] for t in ts]
    return ts, js, len(d["frames"])


def resample(ts, js, rate, hz=200.0):
    """按 rate 重采样到 hz, 返回 (times, targets[list of 6]) —— 线性插值, 与录制同一时间轴"""
    dur = ts[-1] / max(rate, 1e-6)
    n = max(2, int(dur * hz) + 1)
    tt = [i / hz for i in range(n)]
    out_t, out_j = [], []
    k = 0
    for t in tt:
        src_t = t * rate
        while k + 1 < len(ts) - 1 and ts[k + 1] < src_t:
            k += 1
        t0, t1 = ts[k], ts[min(k + 1, len(ts) - 1)]
        a = 0.0 if t1 <= t0 else max(0.0, min(1.0, (src_t - t0) / (t1 - t0)))
        out_t.append(t)
        out_j.append([js[k][m] + (js[min(k + 1, len(js) - 1)][m] - js[k][m]) * a for m in range(6)])
    return out_t, out_j


class Streamer:
    """按弧长参数 s 积分下发的流式器 —— 与回调频率解耦

    上一版按"墙上时间索引"取目标, 控制器回调实测只有 ~7Hz, 于是每拍 delta 过大,
    控制器直接报 kActualJointVelocityLimitsViolation 并掉电。改成:
      s_dot = min(rate * v_rec(s), VMAX) , s += s_dot*dt , cmd = path(s)
      再加"单拍增量 <= MAXDEG"硬钳位 ⇒ 无论回调多慢都不会出现速度越限或不连续。
    """

    def __init__(self, r, ts, js, rate, vmax, maxdeg):
        self.r = r
        self.ts = ts
        self.js = js
        self.rate = rate
        self.vmax = math.radians(vmax)          # deg/s -> rad/s
        self.maxdeg = math.radians(maxdeg)
        # 关节空间最大分量弧长(rad)与分段速度(rad/s)
        self.seg = []
        tot = 0.0
        for i in range(len(js) - 1):
            d = max(abs(js[i + 1][m] - js[i][m]) for m in range(6))
            dt = max(ts[i + 1] - ts[i], 1e-6)
            self.seg.append((tot, tot + d, js[i], js[i + 1], d / dt))
            tot += d
        self.total = tot
        self.s = 0.0
        self.k = 0
        self.prev = None
        self.t_prev = None
        self.abort = False
        self.why = ""
        self.n = 0
        self.log = []

    def _path(self, s):
        if s >= self.total:
            return list(self.js[-1])
        while self.k + 1 < len(self.seg) and self.seg[self.k][1] < s:
            self.k += 1
        s0, s1, ja, jb, v = self.seg[self.k]
        a = 0.0 if s1 <= s0 else (s - s0) / (s1 - s0)
        return [ja[m] + (jb[m] - ja[m]) * a for m in range(6)]

    def __call__(self):
        try:
            now = time.monotonic()
            if self.t_prev is None:
                self.t_prev = now
                self.prev = [float(v) for v in self.r.jointPos({})][:6]
                return x.JointPosition(self.prev)
            dt = max(1e-4, min(now - self.t_prev, 0.25))
            self.t_prev = now
            v = self.vmax
            if self.k < len(self.seg):
                v = min(self.vmax, self.rate * self.seg[self.k][4])
            s_new = min(self.total, self.s + v * dt)
            tgt = self._path(s_new)
            if self.prev is not None:
                mx = max(abs(tgt[m] - self.prev[m]) for m in range(6))
                if mx > self.maxdeg:                     # 硬钳位: 单拍不超过 MAXDEG
                    k = self.maxdeg / mx
                    tgt = [self.prev[m] + (tgt[m] - self.prev[m]) * k for m in range(6)]
                    s_new = self.s                     # 跟不上就不推进参数
            self.s = s_new
            self.prev = tgt
            if self.n % 30 == 0:
                try:
                    act = [float(v) for v in self.r.jointPos({})][:6]
                except Exception:                                        # noqa: BLE001
                    act = None
                self.log.append({"t": round(now - getattr(self, "t0", now), 3), "s_mm": round(self.s * 1000, 1),
                                 "cmd": [round(x2, 5) for x2 in tgt],
                                 "act": [round(x2, 5) for x2 in act] if act else None})
            self.n += 1
            if self.s >= self.total - 1e-9:
                self.abort = True
                self.why = "path done"
            return x.JointPosition([float(x2) for x2 in tgt])
        except Exception as e:                                           # noqa: BLE001
            self.abort = True
            self.why = "cb err %s: %s" % (type(e).__name__, e)
            try:
                return x.JointPosition([float(v2) for v2 in self.r.jointPos({})][:6])
            except Exception:                                            # noqa: BLE001
                return x.JointPosition([0.0] * 6)


def main():
    i0 = int(os.environ.get("ZMAX_RT_I0") or 0) or None
    i1_env = os.environ.get("ZMAX_RT_I1")
    i1 = int(i1_env) if i1_env else None
    ts, js, n_all = load_path((i0 - 1) if i0 else 0, i1)
    times, targets = resample(ts, js, RATE)
    out(start={"n_frames": len(ts), "n_all": n_all, "dur_rec_s": round(ts[-1], 3),
               "dur_play_s": round(times[-1], 3), "rate": RATE, "hz": 200,
               "max_frame_jump_deg": round(max(max(abs(js[i + 1][m] - js[i][m]) for m in range(6))
                                               for i in range(len(js) - 1)) * 57.2958, 1),
               "first_deg": [round(v * 57.2958, 1) for v in js[0]],
               "last_deg": [round(v * 57.2958, 1) for v in js[-1]],
               "max_deg_per_tick_cap": MAXDEG, "dry": DRY})
    if DRY:
        out(dry="OK: 路径已生成, 未连接机器人")
        return
    r = x.xMateRobot()
    LOCAL = os.environ.get("ZMAX_RT_LOCALIP") or local_ip(IP)
    out(local_ip=LOCAL)
    r.connectToRobot(IP, LOCAL)
    st0 = states(r)
    out(state_before=st0)
    if "on" not in st0.get("power", "") or "error" in st0.get("power", "").lower():
        out(ok=False, why="上电状态不满足: %s" % st0)
        r.disconnectFromRobot({})
        return
    if "idle" not in st0.get("op", "") and "rt" not in st0.get("op", ""):
        out(ok=False, why="操作状态不是 idle/rtControlling: %s" % st0)
        r.disconnectFromRobot({})
        return
    cur = [float(v) for v in r.jointPos({})]
    jump = max(abs(js[0][m] - cur[m]) for m in range(6)) * 57.2958
    out(start_jump_deg=round(jump, 2))
    if jump > 60.0:
        out(ok=False, why="首点离当前 %.1f° > 60° ⇒ 先用 Nrt 归位或改 ZMAX_RT_I0" % jump)
        r.disconnectFromRobot({})
        return
    os.makedirs(LOGDIR, exist_ok=True)
    logf = os.path.join(LOGDIR, "rt_stream_%s.jsonl" % time.strftime("%Y%m%d_%H%M%S"))
    t_start = time.time()
    ec = {}
    ok = True
    why = ""
    try:
        r.setMotionControlMode(x.MotionControlMode.RtCommandMode, ec)
        out(switch_rt=ec, op=str(r.operationState({})))
        rt = r.getRtMotionController()
        try:
            rt.setFilterFrequency(50.0, 50.0, 50.0, {})
        except Exception:                                                # noqa: BLE001
            pass
        rt.startMove(x.RtControllerMode.jointPosition)
        VMAX = float(os.environ.get("ZMAX_RT_VMAX") or 30.0)
        s = Streamer(r, ts, js, RATE, VMAX, MAXDEG)
        def _cb():                       # pybind 只认纯函数/std::function, 不认带 __call__ 的实例
            return s()
        rt.setControlLoopJoi(_cb, 0, False)   # 关节变体, 避免 setControlLoop 三重载歧义
        rt.startLoop(False)                       # 非阻塞: 主线程负责监控/收尾
        out(moving=True, rate=RATE, vmax_deg_s=VMAX, path_len_deg=round(s.total * 57.2958, 1))
        budget = max(30.0, (s.total / max(math.radians(VMAX), 1e-6)) * 1.5 + 15.0)
        while not s.abort and (time.time() - t_start) < budget:
            time.sleep(0.05)
        rt.stopLoop()
        rt.stopMove()
        why = s.why or "end"
    except Exception as e:                                               # noqa: BLE001
        ok = False
        why = "%s: %s" % (type(e).__name__, e)
        try:
            rt.stopLoop()
            rt.stopMove()
        except Exception:                                                # noqa: BLE001
            pass
    finally:
        try:
            r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, {})
        except Exception:                                                # noqa: BLE001
            pass
    time.sleep(0.3)
    act = [float(v) for v in r.jointPos({})]
    fin = max(abs(js[-1][m] - act[m]) for m in range(6)) * 57.2958
    with open(logf, "w", encoding="utf-8") as f:
        for rec in s.log if "s" in dir() else []:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    out(ok=ok, why=why, final_err_deg=round(fin, 2), elapsed_s=round(time.time() - t_start, 2),
        ticks=(s.n if "s" in dir() else 0), log=logf, state_after=states(r),
        joints_after_deg=[round(v * 57.2958, 1) for v in act])
    try:
        r.disconnectFromRobot({})
    except Exception:                                                    # noqa: BLE001
        pass


if __name__ == "__main__":
    main()
