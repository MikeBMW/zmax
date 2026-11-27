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
# 🌀 s∈S¹ 相位: 弧长重参数化表(tools/se3_phase.py 生成), 与 cmd 同目录; 缺省时相位留空不臆造
_PHASE = {}


def _load_phase():
    """读 traj_phase.json → {i: s}。只读不留副作用; 没有就返回空(日志里 s 置 None)。"""
    try:
        p = os.path.join(os.path.dirname(CMD), "traj_phase.json")
        for r in json.load(open(p, encoding="utf-8"))["frames"]:
            _PHASE[int(r["i"])] = float(r["s"])
    except Exception:                                                   # noqa: BLE001
        _PHASE.clear()
    return _PHASE
MAX_JUMP_DEG = 40.0
# 2026-11-18: 块内出现 >BIG_JUMP_DEG 的相邻跳变就在那里断块 —— #19→#20 实测 31.1°,
#   它并进普通块会把整块拖超时(实测 20s 超时、误差 27.7°、停在半路)。
BIG_JUMP_DEG = 20.0          # 单点关节跳变上限(真机一次转 >40° 有撞/绕线风险; 本条轨迹相邻点实测最大 31.1°)
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
# AOI 检测服务在生产网段另一台机上(192.168.23.23), 本机 10082/10083 **不监听**。
# 2026-11-17 实测: 本机 curl 127.0.0.1:10082 => 000; 192.168.23.23:10082/last_result => {"code":404,"msg":"尚无检测结果"}
AOI_HOST = os.environ.get("ZMAX_AOI_HOST") or "192.168.23.23"
_T0_WALL = time.time()

# 甘特分段(与 tools/ss_meta_task_ar.py 的 _REPLAY_SEGS 同源同界, 便于逐段对账)
GANTRY_SEGS = [
    (0, 9, "抓取(合爪#9)"), (10, 15, "过渡/举升"), (16, 19, "扫码(对码)"),
    # 🔴 2026-11-17 老倪现场纠正动作顺序: 扫码结束后是 **抓取光模块 → 举升 → 插入 → 拔出**。
    #   原表把 20–40 标成「插入孔内」、91–113 标成「拔出模块」, 与实跑相反:
    #   游标 95 的 TCP X776.2 正落在 2# 孔插入区间 (§下口 761.3 → 插到位 811.6) ⇒ 那一段是**插入**。
    (20, 40, "抓取光模块"), (41, 90, "举升/转运"), (91, 113, "插入·松开·退回·抓环"),
    (114, 119, "拉环解锁·拽出"), (120, 144, "扫码(举高段)"),
    (145, 149, "过渡"), (150, 160, "金手指检测"), (161, 161, "过渡"),
    (162, 193, "表面检测"), (194, 197, "过渡"), (198, 204, "下放入盘"),
    (205, 205, "松开分拣(#205)"), (206, 214, "回位"),
]
# 到位即拍照: 点 -> (端口, 名称)
# 🔴 2026-11-17 老倪: 「金手指点1 要触发金手指检测」—— 金手指点1 = 第 **126** 点。
# ⚠ 这里是 **0-based 帧索引**, 人话的"第 126 点"= frames[125]。第一版写成 126, 走 126 那轮
#   拿到的 i=125 ⇒ AOI_ON_ARRIVE.get(125)=None, 静默不触发(日志里 _cap 已是新配置却没有 "aoi" 行)。
#   126(点1) → 125, 152(点2) → 151。
AOI_ON_ARRIVE = {125: (10082, "金手指"), 151: (10082, "金手指"), 172: (10083, "表面")}


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
    """到点**触发** AOI 检测, 再取判决, 最后存图。

    🔴 2026-11-17 老倪「金手指点1 要触发金手指检测, 你更改 request」:
      原来只有 `GET /picture?grab=1` —— 那只是**取图不检测**, AOI 服务端不会跑推理,
      `/last_result` 永远是上一次的结果。产线口径是 `POST /capture_detect`(触发一次真检),
      然后 `GET /last_result` 拿本次判决; 图用 `GET /picture?grab=1` 另取(10083 表面没有
      /picture 路由, 只有 /capture_detect, 所以取图失败不算错)。
      另外地址原来写死 `127.0.0.1` —— 本机 10082/10083 根本不监听(实测 000), 检测从来没触发过。
      改为 AOI_HOST(默认 192.168.23.23)。
    """
    if not CAP_ON:
        return None
    import urllib.request
    os.makedirs(CAP_DIR, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    base = "%s/aoi_i%03d_%s_%s" % (CAP_DIR, i, label, ts)
    root = "http://%s:%d" % (AOI_HOST, port)
    info = {"i": i, "port": port, "label": label, "host": AOI_HOST,
            "t_wall": time.strftime("%Y-%m-%dT%H:%M:%S")}
    # ① 触发检测 —— 这一步才是「触发」, 少了它 AOI 不跑
    try:
        req = urllib.request.Request(root + "/capture_detect", data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": "zmax-aoi-trigger"})
        with urllib.request.urlopen(req, timeout=25) as resp:
            info["trigger"] = resp.read()[:1200].decode("utf-8", "replace")
    except Exception as e:                                               # noqa: BLE001
        info["trigger_err"] = "%s: %s" % (type(e).__name__, e)
    # ② 取判决
    try:
        with urllib.request.urlopen(urllib.request.Request(root + "/last_result",
                headers={"User-Agent": "zmax-aoi-result"}), timeout=12) as resp:
            raw = resp.read()
        try:
            info["result"] = json.loads(raw.decode("utf-8", "replace") or "{}")
        except Exception:                                                # noqa: BLE001
            info["result"] = raw[:800].decode("utf-8", "replace")
        with open(base + ".result.json", "wb") as f:
            f.write(raw)
    except Exception as e:                                               # noqa: BLE001
        info["result_err"] = "%s: %s" % (type(e).__name__, e)
    # ③ 存图(10083 无 /picture)
    try:
        with urllib.request.urlopen(urllib.request.Request(root + "/picture?grab=1",
                headers={"User-Agent": "zmax-capture"}), timeout=12) as resp:
            body = resp.read()
            ctype = resp.headers.get("Content-Type", "")
        if body[:2] == b"\xff\xd8" or "image" in ctype:
            with open(base + ".jpg", "wb") as f:
                f.write(body)
            info["jpg"] = base + ".jpg"
            info["bytes"] = len(body)
        else:
            with open(base + ".json", "wb") as f:
                f.write(body)
            info["json"] = base + ".json"
    except Exception as e:                                               # noqa: BLE001
        info["pic_err"] = "%s: %s" % (type(e).__name__, e)
    print(json.dumps({"aoi": info}, ensure_ascii=False), flush=True)
    return info


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


def _send_batch_wait(r, jts, speed, tmo):
    """一次 append 多条 MoveAbsJ + 一次 moveStart, 等到最后一点。
    🕐 2026-11-18 老倪「原来的速度太慢了, 能提速么」的真因: 逐点下发时每点固定 ~1.8s 开销
    (moveReset/append/start + 每 0.12s 轮询 joints/opstate 的 SDK 往返), 215 点光开销就 >6 分钟。
    整块下发把开销摊到 N 点上, 才有机会贴住录制速度(录制 215 点 42.85s)。
    返回 (ok, err_deg, secs, why)。"""
    t0 = time.time()
    try:
        r.moveReset({})
        ec = {}
        cmds = [x.MoveAbsJCommand(x.JointPosition([float(v) for v in jt]), speed, -1) for jt in jts]
        r.moveAppend(cmds, x.PyString("bt%d" % (int(t0 * 1000) % 100000)), ec)
        if ec.get("ec", 0) != 0:
            return False, 999.0, time.time() - t0, "moveAppend 被拒: %s" % (ec,)
        r.moveStart({})
    except Exception as e:                                               # noqa: BLE001
        return False, 999.0, time.time() - t0, "%s: %s" % (type(e).__name__, e)
    jt = jts[-1]
    while time.time() - t0 < tmo:
        time.sleep(0.1)
        aj = joints(r)
        err = max(abs(math.degrees(b - a)) for a, b in zip(jt, aj))
        if err <= TOL_DEG and "idle" in opstate(r).lower():
            return True, err, time.time() - t0, ""
    aj = joints(r)
    return False, max(abs(math.degrees(b - a)) for a, b in zip(jt, aj)), time.time() - t0, "整块等待超时"


def _run_real(r, frames, out, speed, dwell_ms, grip_at, start_abs, ts, prev):
    """⚡ 真实回放: 按录制时间轴整块下发。
    - 块大小 ZMAX_REAL_CHUNK(默认 12); 遇到停留点(夹爪/AOI)必断开, 保证停在点上做事
    - 每块下发后按录制时刻对齐(能动得比录制快就 sleep 补齐) ⇒ 整轮 ≈ 录制 dur_s
    - 跳变闸/前置闸与逐点路径同口径, 任一不满足就停, 绝不重发
    """
    n = len(frames)
    stops = set(int(k) for k in grip_at.keys())
    for _a in AOI_ON_ARRIVE:
        _rel = int(_a) - int(start_abs or 0)
        if 0 <= _rel < n:
            stops.add(_rel)
    chunk = max(2, int(os.environ.get("ZMAX_REAL_CHUNK") or 12))
    out["speed_mode"] = "real"
    out["chunk"] = chunk
    out["stops_rel"] = sorted(stops)
    i = 0
    while i < n:
        j = i
        while (j + 1) < n and (j + 1 - i) < chunk:
            j += 1
            if j in stops:      # 停留点必须作为**本块终点**到达, 到点后才能做夹爪/AOI
                break
            # 🔴 2026-11-18 实测(真实档首跑): 把 #19→#20 那个 31° 大跨步并进 12 点块里,
            #   整块 20s 超时, 误差 27.7° ⇒ 停在半路。大跨步必须**单独作为块终点**,
            #   让它自己吃掉整份超时预算, 而不是和 11 个普通点抢。
            _dj = max(abs(math.degrees(b - a)) for a, b in zip(frames[j - 1], frames[j]))
            if _dj > BIG_JUMP_DEG:
                break
        jts = [[float(v) for v in f] for f in frames[i:j + 1]]
        # 跳变闸: 起点→首点 + 块内相邻点
        jump = max(abs(math.degrees(b - a)) for a, b in zip(prev, jts[0]))
        if jump > MAX_JUMP_DEG:
            out["why"] = "第 %d 点起跳 %.1f° > 上限 %.0f°, 拒发" % (i, jump, MAX_JUMP_DEG)
            print(json.dumps(out, ensure_ascii=False))
            return 1
        worst = 0.0
        for a, b in zip([prev] + jts[:-1], jts):
            worst = max(worst, max(abs(math.degrees(y - x)) for x, y in zip(a, b)))
        if worst > MAX_JUMP_DEG:
            out["why"] = "块 %d~%d 内跳变 %.1f° > 上限 %.0f°, 拒发" % (i, j, worst, MAX_JUMP_DEG)
            print(json.dumps(out, ensure_ascii=False))
            return 1
        t_target = (ts[j] - ts[i]) if (ts and len(ts) > j and ts[i] is not None) else None
        # 超时预算按**点数 + 大跨步**给, 只看录制时间不够: 实测 10 点块用 16.5s(≈1.65s/点),
        #   而 rec_dt 只有 1.7s ⇒ 旧公式 20s 只够 12 点块的 2/3, 大跨步那块必然假超时。
        tmo = max(40.0,
                  (j - i + 1) * 2.5 + (float(t_target or 0) * 2.0),
                  (worst * 0.8) + 20.0)
        ok, err, secs, why = _send_batch_wait(r, jts, speed, tmo)
        pace_slept = 0.0
        if ok and t_target and secs < t_target:
            pace_slept = t_target - secs
            time.sleep(pace_slept)
        rec = {"i": i, "i1": j, "n_pts": j - i + 1, "ok": ok,
               "err_deg": round(err, 2), "secs": round(secs, 2),
               "target_deg": [round(math.degrees(v), 2) for v in jts[-1]],
               "max_jump_deg": round(worst, 2),
               "rec_dt_s": round(float(t_target), 3) if t_target else None,
               "pace_slept_s": round(pace_slept, 2), "batch": True}
        if why:
            rec["why"] = why
        if CAP_ON:
            try:
                rec["t_wall"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                rec["t_rel"] = round(time.time() - _T0_WALL, 3)
                _tp = read_tcp(r)
                if _tp:
                    rec["tcp"] = _tp["tcp"]
                    rec["rpy"] = _tp["rpy"]
            except Exception:                                            # noqa: BLE001
                pass
        out["steps"].append(rec)
        print(json.dumps({"progress": j + 1, "n": n, "step": rec}, ensure_ascii=False), flush=True)
        if not ok:
            out["why"] = "块 %d~%d 未到位(%s, 误差 %.1f°) —— 已停, 不重发" % (i, j, why or "超时", err)
            print(json.dumps(out, ensure_ascii=False))
            return 1
        # 停留点: 到点拍照 / 夹爪开合窗口 (与逐点路径同口径)
        _aoi = AOI_ON_ARRIVE.get(j + int(start_abs or 0))
        if _aoi:
            _ci = cap_aoi(j + int(start_abs or 0), _aoi[0], _aoi[1])
            if _ci:
                rec["capture"] = _ci
        _g = grip_at.get(j)
        if _g:
            print(json.dumps({"grip_due": True, "i": j, "act": _g["act"],
                              "hold_ms": _g["hold_ms"], "t": time.strftime("%H:%M:%S")},
                             ensure_ascii=False), flush=True)
            time.sleep(_g["hold_ms"] / 1000.0)
            rec["grip"] = _g["act"]
            print(json.dumps({"grip_done": True, "i": j, "act": _g["act"]}, ensure_ascii=False), flush=True)
        if dwell_ms and not (j in stops):
            time.sleep(dwell_ms / 1000.0)
        prev = joints(r)
        i = j + 1
    return None


# ══════════════════════════════════════════════════════════════════════════════
# 🌀 flow 档 —— 沿固定轨迹的"状态抑制速度"策略(2026-11-18 老倪: 「你来设计, 用新策略,
#   沿着这个固定轨迹跑」)
#
# 口径(全部由**录制真值**推, 不猜):
#   · 方向/姿态: 直接用录制帧的关节角(等价于录制时的四元数方向), 不改几何 ⇒ 只调"多快走"
#   · 速度是**状态相关**的: 每点算 qdot_rec = max_j |Δq_j| / dt(录制时这段的真实关节速率),
#     再按安全状态给上限 qdot_cap:
#         常规 45°/s · 单点跳变>12° 的段 22°/s · 操作区(夹爪/AOI 停留点 ±3 点)15°/s
#     ⇒ speed_i = clamp(100 * qdot_cap / qdot_rec, V_MIN, 100)
#     也就是"能快的地方全速, 该慢的地方被状态压下来", 抑制不是拍脑袋, 是关节速率倒推的。
#   · 块是**动态**的: 常规 12 点; 速度<60 或临近停留点 6 点; 速度<25 4 点; 停留点必断块。
#   · 块间 S 曲线: 新块速度不允许超过上一块的 1.6 倍(避免速度阶跃 ⇒ 顿挫)。
#   · 每块前**真值重锚**: 与上一块终点比, 偏 >3° 降速 30%, >8° 直接停(绝不带病下发)。
#   · 每块后校验: err_deg > 2° ⇒ 停, 不重发。
# ══════════════════════════════════════════════════════════════════════════════
# 🔴 标定(2026-11-18 用刚跑完那轮 215 点实测反推, 不是拍的):
#   speed_cmd=100 时实测关节速率只有 **3.8 °/s**(中位 3.8 / 最大 4.6), 而录制轨迹本身是 ~40 °/s。
#   ⇒ 这台控制器的 speed 参数与"度/秒"无关, 而且每点有 ~1.1~1.5s 的固定开销(12 点最少 14s)。
#   ⇒ 结论: 在这台硬件上"把速度压到 20~40"既不会更安全(本来就 3.8°/s), 又只会把 7 分钟拖成 20 分钟。
#   所以状态抑制改在这三处做, 而不是无脑降 speed:
#     ① 操作区(停留点 ±3 点): 块缩到 3 点 + 到点 dwell ⇒ 时间上真正慢下来
#     ② 大跳变(>12°): 单独成块, speed 70(留余量给 50113 的姿态限制)
#     ③ 其余: speed 100 + 12 点/块 —— 这已经是这台控制器的上限
V_MAX = 100.0
V_BIG = 70.0
V_ZONE = 60.0
V_AXIS = 70.0        # 方向(轴)断层: S² 上单帧 >10° ⇒ 单独成块留余量
V_ROLL = 85.0        # 滚转跳变: S¹ 上单帧 >12° ⇒ 略降即可(滚转不影响插孔)
AXIS_JUMP_DEG = 10.0
ROLL_JUMP_DEG = 12.0
AXIS_ABORT_DEG = 25.0   # 块内单帧轴步长超这个 ⇒ 停(实测全轨迹 max 16.28°, 留 1.5 倍余量)


# ── 姿态 Hopf 分解(同源副本; 权威实现 tools/se3_hopf.py, 容器只挂 tools/rokae 所以不能直接 import)
#    π(q)=q·k·q̄ ∈ S² 是轴, 右乘 e^{iθk} 只改滚转不动轴(实测 1e-16)。实测 215 帧:
#    轴步长 中位 1.98° P95 9.75° max 16.28° · 滚转步长 中位 1.59° P95 13.08° max 39.10°
def _hopf(q):
    # 🔴 q 的存储顺序是 (x,y,z,w), 末位才是标量(与 real_traj_joints.json 一致, 见 tools/se3_hopf.py)
    x, y, z, w = (float(v) for v in q[:4])
    m = math.sqrt(w * w + x * x + y * y + z * z) or 1.0
    w, x, y, z = w / m, x / m, y / m, z / m
    n = (2.0 * (x * z + w * y), 2.0 * (y * z - w * x), w * w + z * z - x * x - y * y)
    k = math.sqrt(sum(c * c for c in n)) or 1.0
    return (n[0] / k, n[1] / k, n[2] / k), (2.0 * math.atan2(z, w)) % (2.0 * math.pi)


def _axis_deg(n1, n2):
    d = sum(a * b for a, b in zip(n1, n2))
    return math.degrees(math.acos(max(-1.0, min(1.0, d))))


def _roll_deg(p1, p2):
    d = math.degrees(p2 - p1)
    return (d + 180.0) % 360.0 - 180.0


def _plan_flow(frames, ts, stops, n, quats=None, scale=1.0):
    """算每点速度 + 动态分块。返回 (speeds, plan)。
    分类(优先级从高到低): 操作区 60/3点 · 关节断层 70/4点 · 轴断层 70/4点 · 滚转跳变 85/4点 · 常规 100/12点
    quats 给了就用 Hopf 把姿态拆成 轴(S²)+滚转(S¹) 再分类; 没给退回纯关节口径("轴/滚转"两列写 None)。"""
    qdot, cap, spd = [], [], []
    dn, dphi = [0.0] * n, [0.0] * n
    if quats and len(quats) >= n:
        _pn = _pp = None
        for i in range(n):
            _n, _ph = _hopf(quats[i])
            if _pn is not None:
                dn[i] = _axis_deg(_pn, _n)
                dphi[i] = _roll_deg(_pp, _ph)
            _pn, _pp = _n, _ph
    for i in range(n):
        if i + 1 < n and ts and len(ts) > i + 1:
            dt = max(float(ts[i + 1]) - float(ts[i]), 0.05)
        else:
            dt = 0.2
        dq = max(abs(math.degrees(float(b) - float(a))) for a, b in zip(frames[i], frames[min(i + 1, n - 1)]))
        qdot.append(dq / dt)
        jump = max(abs(math.degrees(float(b) - float(a))) for a, b in zip(frames[i - 1] if i else frames[i], frames[i]))
        near_stop = any(abs(i - s) <= 3 for s in stops)
        big = jump > 20.0      # 只把真正的断层(实测 #19→#20 那种 31°)单独拎出来; 12° 阈值太敏感, 会把一半块都当断层
        axis_big = dn[i] > AXIS_JUMP_DEG
        roll_big = abs(dphi[i]) > ROLL_JUMP_DEG
        cap.append(60.0 if near_stop else (100.0 if (big or axis_big) else 150.0))
        spd.append(V_ZONE if near_stop else (V_BIG if (big or axis_big) else (V_ROLL if roll_big else V_MAX)))
    speeds = spd
    plan, i = [], 0
    while i < n:
        j = i
        base = 3 if speeds[i] <= V_ZONE else (4 if speeds[i] <= V_ROLL else 12)
        while (j + 1) < n and (j + 1 - i) < base:
            j += 1
            if j in stops:
                break
            if max(abs(math.degrees(float(b) - float(a))) for a, b in zip(frames[j - 1], frames[j])) > BIG_JUMP_DEG:
                break
            if speeds[j] != speeds[i]:
                break
        seg = speeds[i:j + 1]
        if scale and abs(scale - 1.0) > 1e-9:            # 1x 慢速 = 全部分类速度乘 scale(下限 1.0)
            spd_cmd = max(1.0, round(min(seg) * float(scale), 1))
        else:
            spd_cmd = round(min(seg), 1)
        plan.append({"i": i, "j": j, "n_pts": j - i + 1,
                     "spd": spd_cmd,
                     "qdot_rec": round(max(qdot[i:j + 1]), 2),
                     "qdot_cap": round(min(cap[i:j + 1]), 1),
                     "axis_dn_max": round(max(dn[i:j + 1]) if quats else 0.0, 2),
                     "roll_dp_max": round(max((abs(v) for v in dphi[i:j + 1]), default=0.0) if quats else 0.0, 2)})
        i = j + 1
    return speeds, plan


def _run_flow(r, frames, out, dwell_ms, grip_at, start_abs, ts, prev, quats=None, scale=1.0):
    """🌀 状态抑制流动: 沿固定轨迹, 块速由状态决定, 带真值重锚与 S 曲线。"""
    n = len(frames)
    stops = set(int(k) for k in grip_at.keys())
    for _a in AOI_ON_ARRIVE:
        _rel = int(_a) - int(start_abs or 0)
        if 0 <= _rel < n:
            stops.add(_rel)
    speeds, plan = _plan_flow(frames, ts, stops, n, quats, scale)
    out["flow_scale"] = float(scale)
    out["speed_mode"] = "flow"
    out["flow_plan"] = plan
    out["stops_rel"] = sorted(stops)
    prev_speed = None
    for c in plan:
        i, j = c["i"], c["j"]
        jts = [[float(v) for v in f] for f in frames[i:j + 1]]
        cur = joints(r)
        anchor = max(abs(math.degrees(b - a)) for a, b in zip(prev, cur))
        s_cmd = float(c["spd"])
        if prev_speed is not None:
            s_cmd = min(s_cmd, round(prev_speed * 1.6, 1))       # S 曲线: 不许速度翻倍突变
        if anchor > 8.0:
            out["why"] = "块 %d~%d 前真值重锚偏 %.1f° > 8° —— 已停, 不下发" % (i, j, anchor)
            print(json.dumps(out, ensure_ascii=False))
            return 1
        if anchor > 3.0:
            s_cmd = max(V_MIN, round(s_cmd * 0.7, 1))            # 偏了就降速再走
        worst = 0.0
        for a, b in zip([prev] + jts[:-1], jts):
            worst = max(worst, max(abs(math.degrees(y - x)) for x, y in zip(a, b)))
        if worst > MAX_JUMP_DEG:
            out["why"] = "块 %d~%d 内跳变 %.1f° > 上限" % (i, j, worst)
            print(json.dumps(out, ensure_ascii=False))
            return 1
        t_target = (ts[j] - ts[i]) if (ts and len(ts) > j and ts[i] is not None) else None
        # 🔴 1x 慢速实测: 12 点块要 ~150s, 原先 2.5/scale 正好卡在 150s 边界 ⇒ 撞超时后残差 3.84°
        #   被 err>2° 闸停掉(块 #137~148, 停在 #149)。预算按 1.5 倍余量给, 并把下限抬到 60/scale。
        _sc = max(float(scale or 1.0), 0.05)
        tmo = max(60.0 / _sc, (j - i + 1) * 3.8 / _sc, ((worst * 0.8) + 20.0) / _sc)
        ok, err, secs, why = _send_batch_wait(r, jts, s_cmd, tmo)
        rec = {"i": i, "i1": j, "n_pts": j - i + 1, "ok": ok,
               "err_deg": round(err, 2), "secs": round(secs, 2),
               "speed_cmd": s_cmd, "qdot_rec": c["qdot_rec"], "qdot_cap": c["qdot_cap"],
               "anchor_deg": round(anchor, 2), "max_jump_deg": round(worst, 2),
               "axis_dn_max": c.get("axis_dn_max"), "roll_dp_max": c.get("roll_dp_max"),
               "rec_dt_s": round(float(t_target), 3) if t_target else None,
               "s0": _PHASE.get(start_abs + i), "s1": _PHASE.get(start_abs + j),
               "target_deg": [round(math.degrees(v), 2) for v in jts[-1]], "flow": True}
        if why:
            rec["why"] = why
        out["steps"].append(rec)
        print(json.dumps({"progress": j + 1, "n": n, "step": rec}, ensure_ascii=False), flush=True)
        if not ok:
            out["why"] = "块 %d~%d 未到位(%s, 误差 %.1f°) —— 已停, 不重发" % (i, j, why or "超时", err)
            print(json.dumps(out, ensure_ascii=False))
            return 1
        if (c.get("axis_dn_max") or 0.0) > AXIS_ABORT_DEG:
            out["why"] = "块 %d~%d 内单帧轴漂 %.1f° > %.0f° —— 方向断层, 已停" % (
                i, j, c["axis_dn_max"], AXIS_ABORT_DEG)
            print(json.dumps(out, ensure_ascii=False))
            return 1
        if err > 2.0:
            out["why"] = "块 %d~%d 到位误差 %.2f° > 2° —— 已停" % (i, j, err)
            print(json.dumps(out, ensure_ascii=False))
            return 1
        _aoi = AOI_ON_ARRIVE.get(j + int(start_abs or 0))
        if _aoi:
            _ci = cap_aoi(j + int(start_abs or 0), _aoi[0], _aoi[1])
            if _ci:
                rec["capture"] = _ci
        _g = grip_at.get(j)
        if _g:
            print(json.dumps({"grip_due": True, "i": j, "act": _g["act"],
                              "hold_ms": _g["hold_ms"], "t": time.strftime("%H:%M:%S")},
                             ensure_ascii=False), flush=True)
            time.sleep(_g["hold_ms"] / 1000.0)
            rec["grip"] = _g["act"]
            print(json.dumps({"grip_done": True, "i": j, "act": _g["act"]}, ensure_ascii=False), flush=True)
        if dwell_ms and not (j in stops):
            time.sleep(dwell_ms / 1000.0)
        prev = joints(r)
        prev_speed = s_cmd
    return None


def main() -> int:
    dry = "--dry" in sys.argv
    if not os.path.isfile(CMD):
        print(json.dumps({"ok": False, "why": "缺少指令文件 %s" % CMD}, ensure_ascii=False))
        return 2
    spec = json.load(open(CMD, encoding="utf-8"))
    _load_phase()                                                        # 🌀 s∈S¹ 相位表
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
    # ⚡ 真实回放(录制时间轴整块下发) —— 跳变闸与前置闸已在上面过完, 这里直接跑
    _mode = str(spec.get("speed_mode") or "").strip().lower()
    if _mode in ("real", "flow"):
        _ts = spec.get("t") or None
        _start_abs = int(spec.get("start") or 0)
        if _mode == "flow":
            _rc = _run_flow(r, frames, out, dwell_ms, grip_at, _start_abs, _ts, prev,
                            quats=spec.get("quats") or None,
                            scale=float(spec.get("flow_scale") or 1.0))
        else:
            _rc = _run_real(r, frames, out, speed, dwell_ms, grip_at, _start_abs, _ts, prev)
        if _rc is not None:
            return _rc
        # 🔴 点数≠块数: flow 档一块含 n_pts 个点, 原先 sum(1 for ...) 数的是块 ⇒ 上层游标只推进 18(块数)
        done = sum(int(s.get("n_pts") or 0) for s in out["steps"] if s.get("ok"))
        out["n_done"] = done
        out["ok"] = bool(out["steps"]) and all(s.get("ok") for s in out["steps"])
        out["why"] = ("真实回放: %d 块 / %d 点全部到位" % (len(out["steps"]), sum(s.get("n_pts") or 0 for s in out["steps"]))
                      if out["ok"] else "真实回放中断")
        out["state_after"] = {"power": str(r.powerState({})), "op": opstate(r)}
        try:
            out["joints_after_final_deg"] = [round(math.degrees(v), 2) for v in joints(r)]
        except Exception:                                                # noqa: BLE001
            pass
        print(json.dumps(out, ensure_ascii=False))
        try:
            r.disconnectFromRobot({})
        except Exception:                                                # noqa: BLE001
            pass
        return 0 if out["ok"] else 1
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
