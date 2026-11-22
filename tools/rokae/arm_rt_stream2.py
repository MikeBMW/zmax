#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""arm_rt_stream2.py —— 真 RT 流式回放 215 点轨迹 (按录制时间基准, 1kHz 回调)

2026-11-21 的实测突破(推翻了 11-20 的"7Hz 死路"结论):
  · 回调频率低是因为 useStateDataInLoop=False (自由跑线程被饿) —— 实测 7Hz
  · 必须 setRtNetworkTolerance(0-100) 在切 RT **之前** 设, 否则 19-kInstabilityDetection
  · useStateDataInLoop=True 前必须 startReceiveRobotState(1ms, q_m), 否则
    "rtState: Not start receiving data"
  ⇒ 修好这三条后实测回调 1009.6Hz (p50 gap 1.00ms), 已足够做伺服流

本脚本: 每拍按 frames 的录制时间戳做关节空间线性插值下发 (rate=1.0 = 录制速度 42.85s)
安全闸:
  ① 下发前先 NRT 归位到 frames[0] (分段 ≤18°/段, 精确停)
  ② 每拍增量受 ZMAX_RT_VMAX (deg/s) 限制 ⇒ 任何异常都不会出现大跳变
  ③ 只回放 [I0, I1) 子段, 便于先小段验证
  ④ 结束时保持末位姿几拍再退; stopLoop 卡死则 3s 后硬退出(控制器保持最后指令)
  ⑤ 收尾必须跑 rt_back_nrt.py (实测 RT 会话不能靠 disconnect 自动退)

用法:
  bash tools/rokae_sdk_run.sh --script arm_rt_stream2.py            # 全程 rate=1.0
  ZMAX_RT_I1=30 bash tools/rokae_sdk_run.sh --script arm_rt_stream2.py   # 先跑前 30 点
  ZMAX_RT_RATE=0.5 bash ...                                        # 半速对照
环境变量:
  ZMAX_RT_RATE     播放倍率(1.0=录制速度) 默认 1.0
  ZMAX_RT_I0/I1    帧区间 [I0,I1) 默认 0..全部
  ZMAX_RT_VMAX     关节速度钳制 deg/s 默认 170 (录制峰值 140.6)
  ZMAX_RT_TOL      包丢失阈值 默认 100
  ZMAX_RT_HOLD_TICKS 结束后保持拍数 默认 300 (0.3s)
  ZMAX_RT_DRY=1    只算路径不连机器人
"""
from __future__ import annotations

import bisect
import json
import math
import os
import socket
import sys
import threading
import time

sys.path.insert(0, os.environ.get("ZMAX_SDK_DIR", "/sdk"))
import xcoresdk_python as x  # noqa: E402

IP = os.environ.get("ZMAX_ROBOT_IP") or "192.168.23.160"
TRAJ = os.environ.get("ZMAX_REPLAY_TRAJ") or "/sdk/real_traj_joints.json"
LOGDIR = os.environ.get("ZMAX_RT_LOGDIR") or "/sdk/logs"

RATE = float(os.environ.get("ZMAX_RT_RATE") or 1.0)
VMAX = float(os.environ.get("ZMAX_RT_VMAX") or 120.0)
ACC_MAX = float(os.environ.get("ZMAX_RT_ACC") or 600.0)      # 指令加速度上限 °/s²(消力矩尖峰)
LAG_ABORT_DEG = float(os.environ.get("ZMAX_RT_LAG") or 8.0)  # 命令-实测差超此值即中止(防假成功)
TOL = int(os.environ.get("ZMAX_RT_TOL") or 100)
HOLD_TICKS = int(os.environ.get("ZMAX_RT_HOLD_TICKS") or 300)
MS = int(os.environ.get("ZMAX_RT_INTERVAL") or 1)
DRY = os.environ.get("ZMAX_RT_DRY") == "1"
PREP_SEG_DEG = 18.0
TOL_DEG = float(os.environ.get("ZMAX_RT_ALIGN_TOL") or 1.5)


def out(**kw):
    print(json.dumps(kw, ensure_ascii=False, default=str), flush=True)


def local_ip(dst):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((dst, 9))
        return s.getsockname()[0]
    finally:
        s.close()


def load_path():
    d = json.load(open(TRAJ, encoding="utf-8"))
    fr = d.get("frames") or []
    ts = [float(f["t"]) for f in fr]
    js = [[float(v) for v in f["j"][:6]] for f in fr]
    i0 = int(os.environ.get("ZMAX_RT_I0") or 0)
    i1 = int(os.environ.get("ZMAX_RT_I1") or len(fr))
    i1 = max(i0 + 2, min(i1, len(fr)))
    ts = [t - ts[i0] for t in ts[i0:i1]]
    js = js[i0:i1]
    return fr, ts, js, i0, i1


def interp(ts, js, t):
    if t <= 0:
        return list(js[0])
    if t >= ts[-1]:
        return list(js[-1])
    i = bisect.bisect_right(ts, t) - 1
    i = min(max(i, 0), len(ts) - 2)
    a, b = ts[i], ts[i + 1]
    u = 0.0 if b <= a else (t - a) / (b - a)
    return [js[i][k] + (js[i + 1][k] - js[i][k]) * u for k in range(6)]


def build_play_blend(js, ts, rate, budget_deg, smooth_ms, amax_deg, vmax):
    """墙钟 1ms 表 + 拐点圆弧过渡(预算内) + 速度规划 —— 治"抖"的正解。

    三个振动源一次解决:
      ① 表按**墙钟**建(不是录制时间轴): 慢放时表项不会被重复取 6~7 拍 ⇒ 没有 150Hz 台阶抖动;
      ② 拐点做二次贝塞尔过渡, 修剪长度按**显式预算** budget_deg 反算(偏离 ≤ budget, 报进 plan);
      ③ 速度用录制节奏 × rate, 再做箱式低通 + 前后向加速度限幅 ⇒ 进拐点自动减速, 出来再加速。
    位置始终在"录制折线 + 预算内过渡"上, 不是抹圆轨迹(那会偏几十度, 已撞过)。
    """
    n = len(js)
    keep = [0]
    for i in range(1, n):
        if max(abs(js[i][c] - js[keep[-1]][c]) for c in range(6)) > 1e-9:
            keep.append(i)
    W = [js[i] for i in keep]
    TW = [ts[i] for i in keep]
    nw = len(W)
    if nw < 3:
        dense, pv, pa = build_path_speed(js, ts[-1] / rate, smooth_ms, vmax)
        return dense, pv, pa, ts[-1] / rate

    lens, dirs = [], []
    for i in range(nw - 1):
        d = [W[i + 1][c] - W[i][c] for c in range(6)]
        L = math.sqrt(sum(x * x for x in d))
        lens.append(L)
        dirs.append([x / L if L > 1e-12 else 0.0 for x in d])

    eps = math.radians(max(0.0, budget_deg))
    trim = [0.0] * nw
    cusp = [False] * nw
    for i in range(1, nw - 1):
        cv = max(-1.0, min(1.0, sum(dirs[i - 1][c] * dirs[i][c] for c in range(6))))
        th = math.acos(cv)                       # 方向改变角
        if th > math.radians(150.0):
            # 🔴 近 180° 反向(取放点的"进-退"): 圆弧过渡没有意义, 硬做会在表里出现
            #    0.003° 量级的来回 ⇒ 1kHz 下就是"抖一下"。这里必须**停住再反向**。
            cusp[i] = True
            continue
        om = 1.0 - math.cos(th / 2.0)            # 贝塞尔中点偏离 = d·om/2 ⇒ d = 2ε/om
        if om < 1e-9 or eps <= 0:
            continue
        trim[i] = min(2.0 * eps / om, 0.45 * lens[i - 1], 0.45 * lens[i])

    # ── 弯道过渡后的路径: 每段直线 + 每个顶点二次贝塞尔, 按弧长均匀采样 ──
    STEP = 0.002                                  # rad/样本 ≈ 0.115°
    BL = []                                       # (pos, u_rec)  u_rec = 录制弧长坐标
    cusp_idx = []
    ub = [0.0]
    for i in range(nw - 1):
        ub.append(ub[-1] + lens[i])
    tot_rec = ub[-1]

    def push(p, u):
        # 🔴 直线段末端与贝塞尔起点是同一点: 直接 append 会产生零长段 ⇒ 速度在那一拍掉一下再跳回,
        #    1ms 表里就是一个几 °/s 的台阶(实测 45 处)。这里合并同点, 只更新录制坐标。
        if BL and max(abs(p[c] - BL[-1][0][c]) for c in range(6)) < 1e-9:
            BL[-1] = (p, u)
            return
        BL.append((p, u))

    push(W[0], 0.0)
    cur_u = 0.0
    for i in range(nw - 1):
        a0 = trim[i] if i > 0 else 0.0
        a1 = trim[i + 1] if i + 1 < nw - 1 else 0.0
        L = lens[i]
        if a0 + a1 > 0.9 * L:
            a0 = a1 = 0.45 * L
        P0 = [W[i][c] + dirs[i][c] * a0 for c in range(6)]
        P1 = [W[i + 1][c] - dirs[i][c] * a1 for c in range(6)]
        straight = max(1e-6, L - a0 - a1)
        k = max(1, int(straight / STEP))
        for j in range(1, k + 1):
            f = j / float(k)
            p = [P0[c] + (P1[c] - P0[c]) * f for c in range(6)]
            push(p, ub[i] + a0 + straight * f)
        if cusp[i + 1]:
            cusp_idx.append(len(BL) - 1)
        # 顶点 i+1 的过渡(除首尾)
        if i + 1 < nw - 1 and trim[i + 1] > 0:
            d = trim[i + 1]
            A = [W[i + 1][c] - dirs[i][c] * d for c in range(6)]
            V = W[i + 1]
            B = [W[i + 1][c] + dirs[i + 1][c] * d for c in range(6)]
            m = 20
            for j in range(1, m + 1):
                t = j / float(m)
                p = [(1 - t) ** 2 * A[c] + 2 * t * (1 - t) * V[c] + t * t * B[c] for c in range(6)]
                push(p, ub[i + 1] + d * (2 * t - 1))
    push(W[-1], tot_rec)

    # ── 每条样本的录制速度(保留录制节奏: 插入段慢、空移段快) ──
    def v_rec_at(u):
        u = min(max(u, 0.0), tot_rec)
        lo, hi = 0, nw - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if ub[mid] <= u:
                lo = mid
            else:
                hi = mid
        dt = TW[lo + 1] - TW[lo]
        return lens[lo] / dt if dt > 1e-9 else 1.0

    v = [rate * v_rec_at(u) for _, u in BL]        # rad per wall-second
    w = max(1, int(round(smooth_ms)))
    for _ in range(2):
        ext = [v[0]] * w + v + [v[-1]] * w
        acc = sum(ext[:w])
        nxt = []
        for i2 in range(len(v)):
            nxt.append(acc / w)
            acc += ext[i2 + w] - ext[i2]
        v = nxt
    vlim = math.radians(vmax)
    v = [min(x, vlim) for x in v]
    for ci in cusp_idx:
        if 0 <= ci < len(v):
            # 反向点限到 2°/s 慢爬(不是 0: 0 会让积分时间爆炸, 也不必要地停死)
            v[ci] = min(v[ci], math.radians(2.0))

    # 弧长 & 加速度限幅(前后向)
    S = [0.0]
    for i2 in range(len(BL) - 1):
        S.append(S[-1] + math.sqrt(sum((BL[i2 + 1][0][c] - BL[i2][0][c]) ** 2 for c in range(6))))
    a = math.radians(amax_deg)
    for _ in range(40):
        ch = 0
        for i2 in range(1, len(S)):
            dsv = S[i2] - S[i2 - 1]
            nv = min(v[i2], math.sqrt(max(0.0, v[i2 - 1] ** 2 + 2 * a * dsv)))
            if nv < v[i2] - 1e-12:
                v[i2] = nv
                ch += 1
        for i2 in range(len(S) - 2, -1, -1):
            dsv = S[i2 + 1] - S[i2]
            nv = min(v[i2], math.sqrt(max(0.0, v[i2 + 1] ** 2 + 2 * a * dsv)))
            if nv < v[i2] - 1e-12:
                v[i2] = nv
                ch += 1
        if ch == 0:
            break

    # ── 积分成墙钟 1ms 表 ──
    dur_play = 0.0
    for i2 in range(len(v) - 1):
        dsv = S[i2 + 1] - S[i2]
        dur_play += dsv / max(v[i2], 1e-9)
    ntab = max(2, min(int(round(dur_play * 1000.0)), 3600 * 1000))
    dense = []
    j = 0
    s_now = 0.0
    dt_ms = 1.0 / 1000.0
    for k in range(ntab):
        s_t = 0.0
        # 目标: 按当前速度推进 dt_ms
        if k > 0:
            s_t = s_now + v[min(j, len(v) - 1)] * dt_ms
        while j < len(S) - 2 and (S[j + 1] - S[j] <= 1e-12 or S[j + 1] < s_t):
            j += 1
        dsv = S[j + 1] - S[j]
        f = 0.0 if dsv <= 1e-12 else (s_t - S[j]) / dsv
        f = min(max(f, 0.0), 1.0)
        dense.append([BL[j][0][c] + (BL[j + 1][0][c] - BL[j][0][c]) * f for c in range(6)])
        s_now = s_t
        if s_now >= S[-1]:
            dense[-1] = list(W[-1])
            break
    while len(dense) < 2:
        dense.append(list(W[-1]))

    peak_v = 0.0
    peak_a = 0.0
    for i2 in range(1, len(dense)):
        peak_v = max(peak_v, math.sqrt(sum((dense[i2][c] - dense[i2 - 1][c]) ** 2 for c in range(6))) * 1000.0)
    for i2 in range(1, len(dense) - 1):
        for c in range(6):
            peak_a = max(peak_a, abs(dense[i2 + 1][c] - 2 * dense[i2][c] + dense[i2 - 1][c]) * 1e6)
    return dense, math.degrees(peak_v), math.degrees(peak_a), len(dense) / 1000.0


def build_path_speed(js, dur, smooth_ms, vmax):
    """路径保真 + 速度规划: 位置永远落在录制折线上(偏离 0), 只让"快慢"变平滑。

    🔴 为什么需要: 录制轨迹是折线, 拐点处速度方向瞬间改变。逐点复现位置的流式下发
       在拐点必然要"瞬间换速" ⇒ 臂顿一下/抖一下(实测 0.5x 时明显)。之前用位置平滑
       抹平它, 但那样会离开录制路径(实测最大偏 54°) ⇒ 撞机。
       正确做法: 保持路径不动, 把**速度曲线**做低通, 再按弧长重新采样位置。
       这样拐点处自动减速-再加速, 位置一个点都不改。
    """
    n = len(js)
    ntab = max(int(round(dur * 1000.0)), n)
    P = []
    for k in range(ntab):
        u = (n - 1) * k / (ntab - 1)
        i = min(int(u), n - 2)
        f = u - i
        P.append([js[i][c] + (js[i + 1][c] - js[i][c]) * f for c in range(6)])

    L = [0.0]
    for k in range(1, ntab):
        L.append(L[-1] + math.sqrt(sum((P[k][c] - P[k - 1][c]) ** 2 for c in range(6))))
    tot = L[-1]

    v = [L[k + 1] - L[k] for k in range(ntab - 1)]
    w = max(1, int(round(smooth_ms)))

    def _box(x, n):
        ext = [x[0]] * n + list(x) + [x[-1]] * n
        acc = sum(ext[:n])
        res = []
        for i in range(len(x)):
            res.append(acc / n)
            acc += ext[i + n] - ext[i]
        return res

    for _ in range(2):
        v = _box(v, w)
    lim = math.radians(vmax) / 1000.0
    v = [min(x, lim) for x in v]

    S = [0.0]
    for x in v:
        S.append(S[-1] + x)
    scale = (tot / S[-1]) if S[-1] > 0 else 1.0

    dense = []
    idx = 0
    for k in range(ntab):
        s = min(S[k] * scale, tot)
        while idx < ntab - 2 and L[idx + 1] < s:
            idx += 1
        seg = L[idx + 1] - L[idx]
        f = 0.0 if seg <= 0 else (s - L[idx]) / seg
        dense.append([P[idx][c] + (P[idx + 1][c] - P[idx][c]) * f for c in range(6)])
    dense[0] = list(js[0])
    dense[-1] = list(js[-1])

    vmax_seen = 0.0
    acc_seen = 0.0
    for i in range(1, len(dense)):
        dv = math.sqrt(sum((dense[i][c] - dense[i - 1][c]) ** 2 for c in range(6))) * 1000.0
        vmax_seen = max(vmax_seen, dv)
    for i in range(1, len(dense) - 1):
        for c in range(6):
            acc_seen = max(acc_seen, abs(dense[i + 1][c] - 2 * dense[i][c] + dense[i - 1][c]) * 1e6)
    return dense, math.degrees(vmax_seen), math.degrees(acc_seen)


def build_dense(js, dur, smooth_ms, vmax, uniform=True):
    """把帧序列变成 1ms 网格上的平滑位置序列(播放时间轴), 供回调按索引取。

    🔴 为什么要平滑: 录制的帧时间戳有抖动 (实测有一段 47ms/6.6° ⇒ 141°/s 的尖峰),
       按原始时间戳直接回放会在那一拍给出位置阶跃 ⇒ 控制器判 kCollision 掉电 (已实测)。
       做法: 均匀时间基 (i/(n-1)*dur) → 两次箱式滤波(=三角核) → 逐拍限速 → 两端各 100ms 混合。
       两端混合保证: 第一拍 = 臂当前实际位姿(无阶跃), 最后一拍 = 帧末位姿(精确到位)。
    """
    n = len(js)
    ntab = max(int(round(dur * 1000.0)), n)
    base = []
    for k in range(ntab):
        t = dur * k / (ntab - 1)
        if uniform:
            u = t / dur * (n - 1) if dur > 0 else 0.0
            i = min(int(u), n - 2)
            f = u - i
            base.append([js[i][c] + (js[i + 1][c] - js[i][c]) * f for c in range(6)])
        else:
            base.append(interp([dur * i / (n - 1) for i in range(n)], js, t))

    w = max(1, int(round(smooth_ms)))
    if smooth_ms <= 0:
        # 🔴 不平滑 = 逐点严格等于录制路径(时间缩放只改快慢, 不改位置)
        dense = [list(p) for p in base]
    else:
        # ── 在「速度域」做平滑, 再积分回位置 (⚠️ 会偏离录制路径! 见 plan_dense 的
        #    path_dev_deg 字段: 实测 40ms→8.1°, 150ms→29.9°, 150ms+VMAX40→54.2°)
        v = [[base[k + 1][c] - base[k][c] for c in range(6)] for k in range(len(base) - 1)]
        for _ in range(2):
            pad_l = [list(v[0])] * w
            pad_r = [list(v[-1])] * w
            ext = pad_l + v + pad_r
            nxt = []
            acc = [0.0] * 6
            for x in ext[:w]:
                for c in range(6):
                    acc[c] += x[c]
            for i in range(len(ext) - w):
                nxt.append([acc[c] / w for c in range(6)])
                xo = ext[i]
                xi = ext[i + w]
                for c in range(6):
                    acc[c] += xi[c] - xo[c]
            v = nxt

        lim = math.radians(vmax) / 1000.0
        for k in range(len(v)):
            for c in range(6):
                if abs(v[k][c]) > lim:
                    v[k][c] = math.copysign(lim, v[k][c])

        pos = [list(base[0])]
        for k in range(len(v)):
            pos.append([pos[-1][c] + v[k][c] for c in range(6)])
        p0, p1 = list(js[0]), list(js[-1])
        err = [p1[c] - pos[-1][c] for c in range(6)]
        nmax = max(1, len(pos) - 1)
        for k in range(len(pos)):
            f = k / float(nmax)
            pos[k] = [pos[k][c] + err[c] * f for c in range(6)]
        pos[0] = p0
        pos[-1] = p1
        dense = pos
    vmax_seen = 0.0
    acc_seen = 0.0
    for i in range(1, len(dense)):
        v = max(abs(dense[i][c] - dense[i - 1][c]) for c in range(6)) * 1000.0
        vmax_seen = max(vmax_seen, v)
    for i in range(1, len(dense) - 1):
        for c in range(6):
            a = abs((dense[i + 1][c] - 2 * dense[i][c] + dense[i - 1][c])) * 1e6
            acc_seen = max(acc_seen, a)
    return dense, math.degrees(vmax_seen), math.degrees(acc_seen)


def path_dev(dense, base):
    """dense 相对录制折线的**真实距离**(不是同下标比, 同下标比会把"时间相位差"误算成偏离)。

    做法: 在 1ms 精细折线 base 上对每个 dense 点找最近点(单调推进 + 局部窗口)。
    """
    n = len(base)
    worst = 0.0
    at = 0
    j = 0
    for k in range(len(dense)):
        best = float("inf")
        bestj = j
        j0 = max(0, j - 200)
        j1 = min(n - 1, j + 1200)
        for jj in range(j0, j1 + 1, 8):
            d = (dense[k][0] - base[jj][0]) ** 2 + (dense[k][1] - base[jj][1]) ** 2 \
                + (dense[k][2] - base[jj][2]) ** 2 + (dense[k][3] - base[jj][3]) ** 2 \
                + (dense[k][4] - base[jj][4]) ** 2 + (dense[k][5] - base[jj][5]) ** 2
            if d < best:
                best, bestj = d, jj
        j = bestj
        dv = math.degrees(math.sqrt(best))
        if dv > worst:
            worst, at = dv, k
    return round(worst, 2), round(at / 1000.0, 2)


def opstate(r):
    return str(r.operationState({}))


def align_to(r, target, speed=100.0, label="pre"):
    cur = [float(v) for v in list(r.jointPos({}))[:6]]
    jump = max(abs(math.degrees(b - a)) for a, b in zip(cur, target))
    if jump <= TOL_DEG:
        return {"aligned": True, "jump_deg": round(jump, 2), "moved": False}
    k = max(1, int(math.ceil(jump / PREP_SEG_DEG)))
    for t in range(1, k + 1):
        pj = [cur[m] + (target[m] - cur[m]) * (t / float(k)) for m in range(6)]
        r.moveReset({})
        ec = {}
        r.moveAppend([x.MoveAbsJCommand(x.JointPosition([float(v) for v in pj]), speed, -1)],
                     x.PyString("%s%d" % (label, t)), ec)
        if ec.get("ec", 0) != 0:
            raise RuntimeError("归位 %d/%d append 被拒: %s" % (t, k, ec))
        r.moveStart({})
        t0 = time.time()
        while time.time() - t0 < 60.0:
            time.sleep(0.1)
            if "idle" in opstate(r).lower():
                break
        else:
            raise RuntimeError("归位 %d/%d 超时" % (t, k))
    return {"aligned": True, "jump_deg": round(jump, 2), "moved": True, "n_seg": k}


def main() -> int:
    fr, ts, js, i0, i1 = load_path()
    # 🔴 ph 必须是**整条 215 点轨迹**的绝对相位, 不是本段内部进度:
    #    否则只跑 0→9 时页面显示 100%(段末), 而臂其实才走到全路径 4%, 用户看到"相位不变/乱跳"
    N_TOTAL = max(2, len(fr))
    SPAN = max(1, (i1 - 1) - i0)
    # ph 必须与页面/API 的 s(弧长归一) 同一口径: 帧号均匀 ≠ 弧长均匀(大跳帧会把两者拉开 1%)
    try:
        _tp = json.load(open(os.path.join(os.path.dirname(TRAJ), "traj_phase.json"), encoding="utf-8"))
        SS = [float(f["s"]) for f in _tp["frames"]]
        SS_END = SS[-1] if SS and SS[-1] > 0 else 1.0
        SS.append(SS[-1])
    except Exception:
        SS, SS_END = [], 1.0
    dur = ts[-1] / RATE
    SMOOTH = float(os.environ.get("ZMAX_RT_SMOOTH") or 0.0)
    MODE = os.environ.get("ZMAX_RT_MODE") or "blend"
    BUDGET = float(os.environ.get("ZMAX_RT_BUDGET") or 0.15)
    AMAX = float(os.environ.get("ZMAX_RT_AMAX") or 300.0)
    if MODE == "blend":
        # 墙钟表 + 拐点过渡(预算内) + 速度规划: 治抖, 偏离有上界
        dense, peak_v, peak_a, dur_tab = build_play_blend(
            js, ts, RATE, BUDGET, SMOOTH or 120.0, AMAX, VMAX)
        dur = dur_tab
    elif MODE == "path":
        # 路径保真 + 速度规划(录制时间轴): 位置严格在录制折线上
        dense, peak_v, peak_a = build_path_speed(js, ts[-1] / RATE, SMOOTH or 120.0, VMAX)
    else:
        dense, peak_v, peak_a = build_dense(js, ts[-1], SMOOTH, VMAX)
    # ◆ 在"方向明显改变"的停留点上原地停一下(默认 #9/#19/#135/#176, 几何判据算出来的)
    #   做法: 在这几帧的姿态处向 1ms 表里插 hold_ms 条同姿态 —— 位置不变, 只是不走
    HOLD_AT = [int(x) for x in (os.environ.get("ZMAX_RT_HOLD_AT") or "").split(",") if x.strip()]
    HOLD_MS = int(os.environ.get("ZMAX_RT_HOLD_MS") or 2500)
    hold_log = []
    if HOLD_AT and HOLD_MS > 0:
        base_n = len(dense)
        _off = int(os.environ.get("ZMAX_RT_I0") or 0)   # 🔴 段跑时 js 只装 [I0,I1), 停点帧号是绝对值
        for fi in sorted(set(HOLD_AT)):
            _fl = fi - _off
            if not (0 <= _fl < len(js)):
                continue
            pose = js[_fl]
            k = min(range(len(dense)),
                    key=lambda q: max(abs(dense[q][c] - pose[c]) for c in range(6)))
            dev_fi = math.degrees(max(abs(dense[k][c] - pose[c]) for c in range(6)))
            dense[k:k] = [list(dense[k]) for _ in range(HOLD_MS)]
            hold_log.append({"i": fi, "at_ms": k, "dev_deg": round(dev_fi, 3)})
        dur += len(HOLD_AT) * HOLD_MS / 1000.0
        out(step="holds", n=len(hold_log), hold_ms=HOLD_MS, detail=hold_log,
            dense_n_base=base_n, dense_n=len(dense), dur_s=round(dur, 2))
    HOLD_MASK = None
    HOLD_FI = None
    if hold_log:
        HOLD_MASK = bytearray(len(dense))
        HOLD_FI = [-1] * len(dense)
        for _h in hold_log:
            for _q in range(_h["at_ms"], min(len(dense), _h["at_ms"] + HOLD_MS)):
                HOLD_MASK[_q] = 1
                HOLD_FI[_q] = _h["i"]
    ref, _, _ = build_dense(js, ts[-1], 0.0, 1e9)     # 严格录制路径(只做时间缩放)
    dev, dev_at = path_dev(dense, ref)
    out(step="plan", i0=i0, i1=i1, n=i1 - i0, rate=RATE, dur_s=round(dur, 2), mode=MODE,
        smooth_ms=SMOOTH, vmax_cap=VMAX, budget_deg=BUDGET, amax_deg_s2=AMAX,
        plan_peak_deg_s=round(peak_v, 1),
        plan_peak_acc_deg_s2=round(peak_a, 1), dense_n=len(dense),
        path_dev_deg=dev, path_dev_at_s=dev_at,
        first_deg=[round(math.degrees(v), 2) for v in js[0]],
        last_deg=[round(math.degrees(v), 2) for v in js[-1]],
        dense_first_deg=[round(math.degrees(v), 2) for v in dense[0]],
        dense_last_deg=[round(math.degrees(v), 2) for v in dense[-1]])
    if DRY:
        out(ok=True, note="dry: 未连机器人")
        return 0

    os.makedirs(LOGDIR, exist_ok=True)
    logpath = os.path.join(LOGDIR, "rt_stream2_%d.jsonl" % int(time.time()))
    fd = os.open(logpath, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)

    r = x.xMateRobot()
    r.connectToRobot(IP, local_ip(IP))
    out(step="connect", state={"power": str(r.powerState({})), "op": opstate(r)}, log=logpath)

    try:
        # 🔴 上次 RT 会话被中断会残留 rtControlling ⇒ NRT 上电/运动全被拒, 先退回 Nrt
        if "rt" in opstate(r).lower():
            ecr = {}
            r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, ecr)
            time.sleep(0.8)
            out(step="back_nrt_on_entry", ec=ecr, op=opstate(r))
        if "on" not in str(r.powerState({})).lower():
            ec = {}
            r.setPowerState(True, ec)
            time.sleep(0.5)
        if "on" not in str(r.powerState({})).lower():
            out(ok=False, why="上电失败")
            return 2
        out(step="align", **align_to(r, js[0], speed=100.0, label="p"))

        st8 = {"n": 0, "last_t": None, "t0": None, "done": False, "max_dv": 0.0,
               "cmd": list(js[0]), "hold": 0, "err": None, "idx": 0,
               "wall": (MODE == "blend"), "meas_n": 0,
               "max_step": max(1, int(round(MS * (1.0 if MODE == "blend" else RATE) * 1.5)) + 1)}

        # ── 实测关节位置高频采样(ZMAX_RT_MEAS=1): 回调内读状态缓冲(不抢 RCI 锁) ──
        meas_fd = None
        meas_vec = None
        mpath = ""
        if os.environ.get("ZMAX_RT_MEAS"):
            mpath = os.path.join(LOGDIR, "meas_%d.jsonl" % int(time.time()))
            meas_fd = os.open(mpath, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
            try:
                meas_vec = x.PyTypeVectorDouble([0.0] * 6)
            except Exception:                                             # noqa: BLE001
                meas_vec = None
            out(step="meas_on", path=mpath, have_vec=bool(meas_vec))

        def cb():
            now = time.monotonic()
            if st8["t0"] is None:
                st8["t0"] = now
                st8["last_t"] = now
            if st8.get("abort"):
                st8["hold"] += 1
                return x.JointPosition([float(v) for v in st8["cmd"]])
            t_play = (now - st8["t0"]) * (1.0 if st8["wall"] else RATE)
            idx_t = int(t_play * 1000.0)
            if idx_t >= len(dense):
                tgt = dense[-1]
                st8["hold"] += 1
            else:
                # 🔴 禁止"追帧跳变": 回调被调度延迟时若按墙上时间直接跳索引,
                #    一拍能跳 1.5°+ ⇒ 控制器报 32006 位置指令大跳变 / 13053 关节过速.
                #    这里把每拍前进量钳在名义值的 1.5 倍, 宁可整体慢一点, 也不跳。
                idx = min(idx_t, st8["idx"] + st8["max_step"])
                st8["idx"] = idx
                # 亚毫秒插值: 表项之间线性插, 否则(慢放时)同一项被重复取几拍 ⇒ 台阶式抖动
                fsub = max(0.0, min(1.0, t_play * 1000.0 - idx))
                nxt = dense[min(idx + 1, len(dense) - 1)]
                tgt = [dense[idx][k] + (nxt[k] - dense[idx][k]) * fsub for k in range(6)]
            dt = min(max(now - st8["last_t"], 1e-4), 0.005)   # 🔴 上限=命令周期量级, 否则 32006
            lim = math.radians(VMAX) * dt
            cur = st8["cmd"]
            new = []
            dv = 0.0
            for k in range(6):
                d = tgt[k] - cur[k]
                if abs(d) > lim:
                    d = math.copysign(lim, d)
                dv = max(dv, abs(d))
                new.append(cur[k] + d)
            st8["cmd"] = new
            st8["last_t"] = now
            st8["n"] += 1
            if meas_fd is not None and (st8["n"] % 10) == 0:
                try:
                    if r.getStateData(x.RtSupportedFields.jointPos_m, meas_vec, 6) >= 0:
                        vals = meas_vec.content()
                        st8["meas_n"] += 1
                        # 🔴 跟随性闸门: 控制器拒指令时(碰撞判定/限制)实测会越落越远,
                        #    旧代码照旧把 idx 推到末尾并报 err_deg=0.0 ⇒ "假成功"。
                        _lag = max(abs(float(vals[k]) - new[k]) for k in range(6)) * 57.2958
                        if _lag > LAG_ABORT_DEG and not st8.get("abort"):
                            st8["abort"] = True
                            st8["abort_why"] = "跟丢 %.1f° (idx %d)" % (_lag, st8["idx"])
                        os.write(meas_fd, (json.dumps({
                            "t": round(time.time(), 5),
                            "ph": round(min(1.0, max(0.0, (SS[min(len(SS) - 1, int(round(i0 + SPAN * (st8["idx"] / max(1, len(dense) - 1)))))] / SS_END) if SS else ((i0 + SPAN * (st8["idx"] / max(1, len(dense) - 1))) / (N_TOTAL - 1)))), 5),
                            "phl": round(min(1.0, st8["idx"] / max(1, len(dense) - 1)), 5),
                            "h": (1 if (HOLD_MASK is not None and st8["idx"] < len(HOLD_MASK)
                                       and HOLD_MASK[st8["idx"]]) else 0),
                            "hi": (HOLD_FI[st8["idx"]] if (HOLD_FI is not None
                                   and st8["idx"] < len(HOLD_FI)) else -1),
                            "q": [round(float(z), 7) for z in vals[:6]],
                            "c": [round(float(z), 7) for z in new],
                        }) + "\n").encode())
                except Exception:                                     # noqa: BLE001
                    pass
            if HOLD_FI is not None and st8["idx"] < len(HOLD_FI):
                _fi = HOLD_FI[st8["idx"]]
                if _fi >= 0 and st8.get("hold_seen") != _fi:
                    st8["hold_seen"] = _fi
                    out(step="hold_start", i=_fi, t_s=round(t_play, 2))
            st8["max_dv"] = max(st8["max_dv"], dv / dt)
            if st8["n"] % 200 == 0:
                os.write(fd, (json.dumps({"n": st8["n"], "t": round(t_play, 3),
                                          "ph": round(min(1.0, st8["idx"] / max(1, len(dense) - 1)), 5),
                                          "hold": st8["hold"],
                                          "vmax_seen": round(st8["max_dv"], 1)},
                                         ensure_ascii=False) + "\n").encode())
            return x.JointPosition([float(v) for v in new])

        ec = {}
        r.setRtNetworkTolerance(TOL, ec)
        out(step="tolerance", pct=TOL, ec=ec)
        import datetime as _dt
        r.startReceiveRobotState(_dt.timedelta(milliseconds=MS), [x.RtSupportedFields.jointPos_m])
        out(step="start_recv_state", interval_ms=MS)

        ec = {}
        r.setMotionControlMode(x.MotionControlMode.RtCommandMode, ec)
        out(step="switch_rt", ec=ec, op=opstate(r))

        rt = r.getRtMotionController()
        ld = os.environ.get("ZMAX_RT_LOAD") or ""
        if ld:
            q = [float(v) for v in ld.split(",")]
            mass = q[0]
            cog = (q[1:4] + [0.0, 0.0, 0.0])[:3]
            iner = (q[4:7] + [0.0, 0.0, 0.0])[:3] if len(q) >= 7 else [0.0, 0.0, 0.0]
            ec = {}
            try:
                rt.setLoad(x.Load(mass, cog, iner), ec)
                out(step="set_load", mass_kg=mass, cog_m=cog, inertia=iner, ec=ec)
            except Exception as e:                                            # noqa: BLE001
                out(step="set_load_exc", why="%s: %s" % (type(e).__name__, e))
        filt = os.environ.get("ZMAX_RT_FILTER") or ""
        if filt:
            f3 = [float(v) for v in filt.split(",")]
            while len(f3) < 3:
                f3.append(f3[-1])
            ec = {}
            try:
                rt.setFilterFrequency(f3[0], f3[1], f3[2], ec)
                out(step="filter", hz=f3, ec=ec)
            except Exception as e:                                            # noqa: BLE001
                out(step="filter_exc", why="%s: %s" % (type(e).__name__, e))
        col = os.environ.get("ZMAX_RT_COLLISION") or ""
        if col:
            th = [float(v) for v in col.split(",") if v.strip()]
            ec = {}
            try:
                rt.setCollisionBehaviour(th, ec)
                out(step="collision_thresholds", N=th, ec=ec)
            except Exception as e:                                            # noqa: BLE001
                out(step="collision_thresholds_exc", why="%s: %s" % (type(e).__name__, e))
        rt.setControlLoopJoi(cb, 0, True)
        rt.startMove(x.RtControllerMode.jointPosition)
        rt.startLoop(False)
        t_wall = time.time()
        out(step="start_loop", expect_s=round(dur, 2))

        tlim = [float(v) for v in (os.environ.get("ZMAX_RT_TLIM")
                                   or "85,85,-1,17.5,-1,-1").split(",")]
        while True:
            time.sleep(0.05)          # 🔴 一次长睡: 2ms 一醒会跟 RT 回调抢 GIL(实测回调掉到 8Hz)
            if st8["hold"] >= HOLD_TICKS:
                break
            if not st8.get("abort"):
                try:
                    import urllib.request as _u
                    with _u.urlopen("http://127.0.0.1:39071/status", timeout=0.4) as _r:
                        _t = json.loads(_r.read())["status"].get("jointTorque") or []
                    for _i in range(min(6, len(_t), len(tlim))):
                        if tlim[_i] > 0 and abs(_t[_i]) >= tlim[_i]:
                            st8["abort"] = True
                            out(step="torque_abort", joint=_i + 1, Nm=round(_t[_i], 1),
                                limit=tlim[_i], ticks=st8["n"])
                            break
                except Exception:                                             # noqa: BLE001
                    pass
            if time.time() - t_wall > dur * 1.6 + 20.0:
                out(step="watchdog_timeout", n=st8["n"], hold=st8["hold"])
                break
        if meas_fd is not None:
            os.close(meas_fd)
            out(step="meas_off", samples=st8["meas_n"], path=mpath)

        el = time.time() - t_wall
        fin = {"ticks": st8["n"], "elapsed_s": round(el, 2), "hold": st8["hold"],
               "vmax_seen_deg_s": round(st8["max_dv"], 1),
               "abort_why": st8.get("abort_why") or "",
               "err_deg": round(max(abs(math.degrees(b - a))
                                    for a, b in zip(st8["cmd"], js[-1])), 2)}
        out(step="run_done", **fin)
        os.write(fd, (json.dumps({"final": fin}, ensure_ascii=False) + "\n").encode())
        os.fsync(fd)

        if os.environ.get("ZMAX_RT_NO_STOPLOOP", "1") != "0":
            # 🔴 实测(两次): 这种会话里 stopLoop() 会永久阻塞 ⇒ 直接退出,
            #    控制器由下面的 rt_back_nrt / 外部 rt_back_nrt.py 收尾 (臂保持最后指令位)
            out(step="hard_exit", why="跳过 stopLoop(已知阻塞), 收尾用 rt_back_nrt.py")
            os._exit(0)                                                       # noqa: SLF001

        th = threading.Thread(target=rt.stopLoop, daemon=True)
        th.start()
        th.join(3.0)
        out(step="stop_loop", joined=not th.is_alive())
        try:
            rt.stopMove()
        except Exception as e:                                                # noqa: BLE001
            out(step="stop_move_exc", why=str(e))
        os.close(fd)
        if th.is_alive():
            out(step="hard_exit", why="stopLoop 卡死 ⇒ 硬退出, 收尾用 rt_back_nrt.py")
            os._exit(0)                                                       # noqa: SLF001
        return 0
    except Exception as e:                                                    # noqa: BLE001
        out(ok=False, why="%s: %s" % (type(e).__name__, e))
        return 1
    finally:
        try:
            r.stopReceiveRobotState()
        except Exception:                                                     # noqa: BLE001
            pass
        try:
            ecf = {}
            r.setMotionControlMode(x.MotionControlMode.NrtCommandMode, ecf)
            out(step="back_nrt", ec=ecf, op=opstate(r))
        except Exception as e:                                                # noqa: BLE001
            out(step="back_nrt_exc", why="%s: %s" % (type(e).__name__, e))


if __name__ == "__main__":
    sys.exit(main())
