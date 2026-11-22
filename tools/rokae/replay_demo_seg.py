#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""replay_demo_seg.py — 回放现场演示里的一段 (默认 槽2抓取), 笛卡尔逐点 MoveL。

为什么是 MoveL 逐点: 采集只有末端位姿(pose7), **没有关节角**, 没法 MoveAbsJ 复现关节轨迹。
所以按演示轨迹的重采样点逐点走直线, 复现的是"路径"而不是"关节运动/加减速"。

安全:
  · 起点先与轨迹首点比对, 差 >15mm 就先单点过去(不硬插队)
  · 每点核验到位 |Δ|<2.0mm 姿态差<1.5°, 任一失败立即停, 不继续
  · 速度默认 40mm/s (ZMAX_SEG_SPEED 可调), 工作域越界一律拒绝
用法: ZMAX_SEG_NAME="槽2抓取" bash tools/rokae_sdk_run.sh --script replay_demo_seg.py
"""
from __future__ import annotations

import json
import math
import os
import sys
import time

sys.path.insert(0, "/sdk")
import xcoresdk_python as x          # noqa: E402

IP = os.environ.get("ZMAX_ROBOT_IP", "192.168.23.160")
SPEED = float(os.environ.get("ZMAX_SEG_SPEED") or 40)
SEG = os.environ.get("ZMAX_SEG_NAME") or "槽2抓取"
# 🐳 容器里仓库挂在 /repo, 数据挂在 /sdk —— 用宿主绝对路径会 FileNotFoundError(实测)
# 容器里这些变量会被 run 脚本透传成**空串**, 所以必须用 or 兜默认值(不能用 get 的第二参数)
TRAJ = os.environ.get("ZMAX_SEG_TRAJ") or "/sdk/real_traj_joints_demo.json"
STATES = os.environ.get("ZMAX_SEG_STATES") or "/sdk/phase_states_demo.json"
D_MAX, R_MAX = 2.0, 1.5
# 包络上限可用 ZMAX_BOX_ZMAX 抬(默认 720mm); 演示里"金手指检测点2"这段人工把臂抬到 z≈1000mm
# 来避开 AOI 工装, 要照搬轨迹就得放开 z —— 但 11-22 在这条高路径上撞过(J2/J4 力矩), 慎用。
BOX = dict(x=(380, 900), y=(-450, 620),
           z=(95, float(os.environ.get("ZMAX_BOX_ZMAX") or 720.0)))


def R_of(a, b, c):
    ca, sa, cb, sb, cc, sc = math.cos(a), math.sin(a), math.cos(b), math.sin(b), math.cos(c), math.sin(c)
    return [[ca * cb, ca * sb * sc - sa * cc, ca * sb * cc + sa * sc],
            [sa * cb, sa * sb * sc + ca * cc, sa * sb * cc - ca * sc],
            [-sb, cb * sc, cb * cc]]


def rpy_err(a, b):
    A, B = R_of(*a), R_of(*b)
    tr = sum(A[i][j] * B[i][j] for i in range(3) for j in range(3))
    return math.degrees(math.acos(max(-1.0, min(1.0, (tr - 1) / 2.0))))


def _q_of(rpy):
    a, b, c = rpy
    ca, sa, cb, sb, cc, sc = math.cos(a/2), math.sin(a/2), math.cos(b/2), math.sin(b/2), math.cos(c/2), math.sin(c/2)
    # rpy(ZYX) → 四元数
    return [ca*cb*cc + sa*sb*sc, sa*cb*cc - ca*sb*sc, ca*sb*cc + sa*cb*sc, ca*cb*sc - sa*sb*cc]  # x,y,z,w


def _rpy_of(q):
    x, y, z, w = q
    # 四元数 → rpy(ZYX), 与 SDK 的 CartesianPosition(rpy) 同序
    r = math.atan2(2*(w*x + y*z), 1 - 2*(x*x + y*y))
    s = math.asin(max(-1.0, min(1.0, 2*(w*y - z*x))))
    t = math.atan2(2*(w*z + x*y), 1 - 2*(y*y + z*z))
    return [r, s, t]


def _slerp(q0, q1, u):
    d = sum(a*b for a, b in zip(q0, q1))
    if d < 0:
        q1 = [-v for v in q1]; d = -d
    if d > 0.9995:
        q = [a + u*(b-a) for a, b in zip(q0, q1)]
    else:
        th = math.acos(max(-1.0, min(1.0, d)))
        s0 = math.sin((1-u)*th)/math.sin(th); s1 = math.sin(u*th)/math.sin(th)
        q = [s0*a + s1*b for a, b in zip(q0, q1)]
    n = math.sqrt(sum(v*v for v in q)) or 1.0
    return [v/n for v in q]


def _wrap(a):
    return math.atan2(math.sin(a), math.cos(a))


def expand(pts, max_deg=5.0, max_mm=25.0):
    """把相邻点插值成"每步姿态 ≤5°、位移 ≤25mm"的小步 —— 大翻转段(MoveL 带 100°+ 姿态差)
    会被控制器以 50113 拒, 或者途中扫掠撞工装(11-22 金手指检测点2 那次)。"""
    out = [pts[0]]
    for k in range(1, len(pts)):
        p0, r0 = pts[k-1]; p1, r1 = pts[k]
        # ⚠️ 不用四元数 slerp: rpy 的轴序与 SDK 不一致时, 10° 的小步会被插成 178° 的翻转
        #    (实测 P01 Δ178.75°)。相邻点差分本来就 ≤4°, 直接按 rpy 线性插值(带折角回绕)最稳。
        dd = math.dist(p0, p1)
        _d = [_wrap(b - a) for a, b in zip(r0, r1)]
        dr = max(abs(v) for v in _d)
        n = max(1, int(math.ceil(max(dr/max_deg, dd/max_mm))))
        for i in range(1, n+1):
            u = i/n
            p = [a + (b-a)*u for a, b in zip(p0, p1)]
            r = r1 if i == n else [a + dv*u for a, dv in zip(r0, _d)]
            out.append((p, r))
    return out


def main() -> int:
    traj = json.load(open(TRAJ))
    st = json.load(open(STATES))["states"]
    fr = traj["frames"]
    # 取"搬运到该点"的整段 + 该点位本身
    i0 = i1 = None
    for s in st:
        # 转移段前缀: 搬运→ / 后退→(插入到底→等待位) / 移动→(等待检测→钩拉环)
        if s["name"] in ("搬运→" + SEG, "后退→" + SEG, "移动→" + SEG):
            i0 = s["i0"] if i0 is None else i0        # 取第一次出现(演示里同名段会重跑)
        if s["name"] == SEG and i1 is None:
            i1 = s["i1"]                              # 该点本身(第一个出现)
    if i0 is None and i1 is not None:
        i0 = i1          # 只给一个点名(如"初始点"/"槽2抓取")⇒ 直接去那一点, 不从别处搬
    if i0 is None or i1 is None:
        print("✗ 状态表里找不到 %s 段" % SEG)
        return 2
    pts = [(f["p"], f["rpy"]) for f in fr[i0:i1 + 1]]
    _raw = len(pts)
    if os.environ.get("ZMAX_SEG_SPLIT", "1") != "0":
        pts = expand(pts, float(os.environ.get("ZMAX_SEG_MAXDEG") or 5.0),
                     float(os.environ.get("ZMAX_SEG_MAXMM") or 25.0))
        print("插值: %d 点 → %d 小步(每步 ≤5°/25mm)" % (_raw, len(pts)), flush=True)
    print("段 %s: 点 %d 个 · 从 %s 到 %s" % (SEG, len(pts), pts[0][0], pts[-1][0]), flush=True)

    r = x.xMateRobot()
    r.connectToRobot(IP)
    pw, md, op = str(r.powerState({})), str(r.operateMode({})), str(r.operationState({}))
    print("自检: %s %s %s" % (pw, md, op), flush=True)
    if "on" not in pw or "automatic" not in md or "idle" not in op:
        print("✗ 前置不满足, 不动")
        return 3

    def pose():
        cp = r.cartPosture(x.CoordinateType.endInRef, {})
        return [float(v) * 1000.0 for v in cp.trans], [float(v) for v in cp.rpy]

    def go(p, rpy, name):
        if not all(BOX[k][0] <= v <= BOX[k][1] for k, v in zip("xyz", p)):
            print("  ✗ 越界 %s" % name)
            return False
        r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, {})
        r.moveReset({})
        ec = {}
        r.moveAppend(x.MoveLCommand(x.CartesianPosition([v / 1000.0 for v in p], [float(v) for v in rpy]),
                                    SPEED, -1), x.PyString(name), ec)
        if isinstance(ec, dict) and ec.get("ec", 0) not in (0, None):
            print("  ✗ 下发失败 %s %s" % (name, ec))
            return False
        # 控制器在"上一条还没停稳"时回 -20 robot state (moving) unsupported operation
        # ⇒ 退避重试(0.5/1/2/4s, 共 ~12s), 而不是一次就放弃
        _ok = False
        for _try, _wait in enumerate((0.0, 0.5, 1.0, 2.0, 4.0, 4.0)):
            if _wait:
                time.sleep(_wait)
                r.moveReset({})
                r.moveAppend(x.MoveLCommand(x.CartesianPosition([v / 1000.0 for v in p], [float(v) for v in rpy]),
                                            SPEED, -1), x.PyString(name), {})
            _ec2 = {}
            r.moveStart(_ec2)
            _e = _ec2.get("ec", 0) if isinstance(_ec2, dict) else 0
            if _e in (0, None):
                _ok = True
                break
            if _e != -20:
                print("  ✗ moveStart 拒发 %s" % _ec2, flush=True)
                return False
            print("  ⋯ 控制器还在动(-20), 第 %d 次退避 %.1fs" % (_try + 1, _wait or 0), flush=True)
        if not _ok:
            print("  ✗ 连续 -20, 放弃本点(不硬顶)", flush=True)
            return False
        t0 = time.time()
        near = 0
        p0_cur = pose()[0]
        _tmo = max(40.0, 20.0 + math.dist(p0_cur, p) / max(1.0, SPEED * 0.09) * 1.6)
        while time.time() - t0 < _tmo:
            time.sleep(0.1)
            cur = pose()[0]
            near = near + 1 if math.dist(cur, p) < 1.0 else 0
            if near >= 2 and time.time() - t0 > 0.6:
                break
        time.sleep(0.15)
        p2, r2 = pose()
        dp, dr = math.dist(p, p2), rpy_err(rpy, r2)
        ok = dp < D_MAX and dr < R_MAX
        print("  %s %-14s Δ%.2fmm %.2f°" % ("✓" if ok else "✗", name, dp, dr), flush=True)
        return ok

    if os.environ.get("ZMAX_ROT_IN_PLACE") == "1":
        # 原地翻转: 保持当前位置, 只用 ≤5°/步 把姿态转到该段终点姿态。
        # 用于"金手指检测点2"这种演示轨迹本身把臂抬到 z≈1000mm(高过横梁)的段 ——
        # 照搬轨迹会撞梁(11-22 实测 J2/J4 碰撞停止), 而真正要的只是"把件转过来"。
        _cp, _cr = pose()
        _tr = pts[-1][1]
        _d = rpy_err(_cr, _tr)
        _n = max(1, int(math.ceil(_d / 5.0)))
        print("原地翻转: %.1f° → %d 步(≤5°) · 位置保持 %.1f,%.1f,%.1f"
              % (_d, _n, *_cp), flush=True)
        _q0, _q1 = _q_of(_cr), _q_of(_tr)
        for _k in range(1, _n + 1):
            _rk = _tr if _k == _n else _rpy_of(_slerp(_q0, _q1, _k / _n))
            if not go(_cp, _rk, "R%02d" % _k):
                print("✗ 第 %d 步翻转失败, 停在当前姿态" % _k, flush=True)
                return 5
            if _k % 5 == 0 or _k == _n:
                print("  · %d/%d" % (_k, _n), flush=True)
        print("完成: 原地翻转 %.1f°" % _d, flush=True)
        return 0

    p0, r0 = pose()
    print("当前 %.1f,%.1f,%.1f  rpy %.3f,%.3f,%.3f" % (*p0, *r0), flush=True)
    d0 = math.dist(p0, pts[0][0])
    print("与段首点距离 %.1fmm" % d0, flush=True)
    if d0 > 15.0:
        if not go(pts[0][0], r0, "S0_到段首"):
            print("✗ 前段失败, 不动")
            return 1
    for k, (p, rpy) in enumerate(pts):
        if not go(p, rpy, "P%02d" % k):
            print("✗ 中断于第 %d 点, 后续不执行" % k, flush=True)
            return 1
    p9, r9 = pose()
    print("完成: 末点 %.1f,%.1f,%.1f · 与目标 %s 差 %.2fmm"
          % (*p9, pts[-1][0], math.dist(p9, pts[-1][0])), flush=True)
    print("OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
