#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""step_gold_pt2_split.py — 两段式到达『金手指点2』(段1 原地转身 + 段2 平移)。

=================================== 安全纪律 (硬约束) ===================================
 1. 绝不抬升: 计划里任何一段 Δz>0 一律拒绝整条计划(本脚本不含任何抬升逻辑; 也不修改 daemon)。
 2. 授权只从 8793: --go 前必须 GET <ctl>/ctl/status, 确认 auth.armed 且剩余窗口 > AUTH_MIN_LEFT_S;
    未授权 / 已过期 / 只剩演练 => **直接拒绝, 绝不下发**。
 3. 移动前先响警报: 确认 tools/motion_beep.py 常驻在跑(没跑就拉起 tools/motion_beep_start.sh)。
 4. 命令超时 CMD_TIMEOUT_S(30s); 超时/失败**绝不自动重发**(重发 = 叠加运动)。
    每条腿跑完必须回读真值位姿并与目标比残差; 残差超限立即停, 不进下一条腿。
 5. 无自动循环; 参数写死在文件顶部 CONFIG, 便于审阅。--dry-run 默认开(只有显式 --go 才真发)。
 6. 本脚本**不写** tools/l2_daemon.py(运动/安全代码一字不动); --go 只用**幂等注册器**写
    data/skills/l2_atomic/{registry.json, ctl_abs_skills.json}(runtime state, 与既有 register_*.py 同套)。
========================================================================================

真发路径 (写了但默认不执行):
    报警声 -> 段1(原地转身, **服务步逐段调 /move_pose**)  -> 回读位姿 + 残差判据
           -> 段2(平移,   一个多阶段技能, 走 /move_line)  -> 回读位姿 + 残差判据
    任一步: 请求超时 / 受理失败 / 残差超限 => 立即打印现场可读结论(含残差数字)并停止, **不重发**。

------------------------------------------------------------------------------
【改动 A · 段1 走 /move_pose —— 可执行形态 (2026-10-09)】
------------------------------------------------------------------------------
要求: 段1(138° 原地转身)改走本仓已有的 /move_pose 路线。逐行读 l2_daemon.py 后:

  · `/move_pose` 的**直接**发出点只有三处:
      - `plan_stage` 里多阶段固定 `/move_line`(:868, **无服务选择分支**);
      - `run_rot_chunks` → `/move_pose`(:403), 技能 `ros=="pose_rot"`, **只绕工具 X/Y/Z 轴**(:716-719 硬拒 steps);
      - `run_j6_rot` → `/move_pose`(:549), 技能 `ros=="j6_rot"`, **只绕第 6 轴**(:720-722 硬拒 steps)。
      - `dispatch` 里 `_srv="/move_pose" if _rot else "/move_line"`(:1377) 是**死代码**: `_rot` 全文件只在
        :1340 被赋 `None`,`if _rot:` 永不成立。
    ⇒ **多阶段"运动步"发不出 /move_pose**; 而能发它的 pose_rot/j6_rot 只能绕工具轴/第6轴, 本条 138° 转身的
      相对轴是 base(-0.343,0.143,0.928), 与任一工具轴差 40~78° ⇒ **单轴绕不过去**。
    ⇒ 所以**不能**用"运动步 + /move_pose"这条路(那样必须改 plan_stage:868 —— 属 daemon 运动代码, 禁区别动)。

  · ✅ **可执行形态 = 用 daemon 早已支持的「服务步」(`op:"service"`)**, 它就是 /move_pose 的本仓既有路线:
      - `run_stages` 遇 `op=="service"` → `_service_call(st)`(:1140-1147) → `_service_cmd`(:594-597) 拼出
        `timeout N ros2 service call <srv> <type> "<args>"` 并 **ssh 同步执行**(:617-618), 看真实回执。
      - 该机制**已在生产用**(`L2.lissa_insert` 的力控步就是这么发出 `interfaces/srv/LissajousForceSearch`)。
      - 给服务步填 `srv="/move_pose"` + `type="interfaces/srv/TargetPose"` + `args={speed, joint_state, pose}`,
        执行器就**逐字下发 `/move_pose`**, 且**走 POST /ctl/move → 授权闸(_service_call 里 _auth_guard :609)**。
      ⇒ 段1 = 一个多阶段技能, 其 N 个阶段**全是 `op:"service"` 的 /move_pose 调用**(每步一个绝对位姿目标)。

  · ⚠️ 现役执行腿是 **SDK**(`zmax_data/move_transport.json={"transport":"sdk"}`): 服务步**不走 SDK 腿**
    (`_service_call` 直接 ssh→Orin `ros2 service call`), 它需要 **Orin 侧 robot_driver /move_pose 服务在线**。
    当前 Orin ROS 栈未提供 /move_line|/move_pose(见 l2_daemon 日志行: 位姿源是 `rokae_direct(SDK)`) ⇒
    /move_pose 路线**要现场把 Orin 那套栈起起来才真能走**; 若改回 ros 腿, 段2 的 /move_line 同此依赖。

------------------------------------------------------------------------------
【改动 B · wait_arrive 只比位置(风险③)· 段1 的处理】
------------------------------------------------------------------------------
`l2_daemon.wait_arrive`(:875-892) 只对 pos 的 x/y/z 取 max 比容差, **完全不看姿态** —— 段1 位置不动,
若段1 用"运动步", 每步会被**立即**判"到位"(只看位置), daemon 只 `sleep(dwell_s)`(:1179) 就快速连发,
N 段 1s 一条灌进控制器排队(现场=滞后/串味合成动作)。daemon 侧修它要改运动代码(禁区), 所以**段1 改用服务步**:
  · 服务步**根本不进 `wait_arrive`** —— `run_stages` 对 `op=="service"` 只调 `_service_call`(:1142),
    而 `_service_call` 里的 `ros2 service call /move_pose ...` 是**同步阻塞**的(:617-618): 服务返回(即动作
    做完或到 `timeout N`)才继续 ⇒ **每步天然串行, 不依赖位置判据**。
  · 步与步之间另有 `time.sleep(float(st.get("dwell_s", ...)))`(:1147) 兜底间隔。
  · 段2 **位置在变**, 其"运动步"用 daemon 的 wait_arrive(位置)是**有效**判据 ⇒ 段2 保持多阶段运动步。
  · 脚本层再各留一道**姿态**残差终检 `_residual`(见下), 作为整段收尾的双轴核对。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO = "/home/ubuntu/zmax"
LATEST = os.path.join(REPO, "zmax_data/rokae_sdk/tcp_out/latest.json")
POINTS = os.path.join(REPO, "data/skills/l2_atomic/taught_points.json")
REGISTRY = os.path.join(REPO, "data/skills/l2_atomic/registry.json")
OVERLAY = os.path.join(REPO, "data/skills/l2_atomic/ctl_abs_skills.json")
DAEMON_LOG = os.path.join(REPO, "zmax_data/l2_daemon_stdout.log")
CTL_BASE = "http://127.0.0.1:8793"        # 可被 --ctl-base 覆盖(仅便于**安全演练**; 默认仍是真 8793)
MOVE_POSE_SRV = "/move_pose"
MOVE_POSE_TYPE = "interfaces/srv/TargetPose"

# -------------------------------- CONFIG (写死便于审阅) --------------------------------
ROT_STEP_DEG = 10.0          # 段1 每步旋转上限 (2026-10-09 改: 30→10; 减小单条姿态指令的关节摆幅, 硬上限仍 30)
TRANS_STEP_MM = 2.0          # 段2 每步平移上限 (2026-10-09 改: 20→2, 与事故先例(2mm)一致)
SPEED = 8.0                  # 相对速度档 (先例 step1_rotb27.sh 用的也是 8)
SPEED_MAX = 20.0             # 技能级封顶 (l2_daemon: speed_max, 收口在执行层)
MAX_ROT_STEP_DEG = 30.0      # 硬校验: 每段旋转 <=30° (技能文档铁律)
MAX_TRANS_STEP_MM = 20.0     # 硬校验: 每段平移 <=20mm (--trans-step-mm 覆盖时的上限)
ROT_DWELL_S = 1.0            # 段1 服务步之间的停顿 (daemon _service_call 已同步阻塞, 这是兜底)
MIN_ANG_DEG = 0.05           # 转角小于此值视为"已是目标姿态" => 段1 不发
MIN_DIST_MM = 0.05           # 位移小于此值视为"已是目标位置" => 段2 不发
RESID_TOL_MM = 5.0           # 每条腿跑完的位置残差上限
RESID_TOL_DEG = 3.0          # 每条腿跑完的姿态残差上限
CMD_TIMEOUT_S = 30           # HTTP 命令超时 (秒)
SEG_WAIT_CAP_S = 900         # 等一条腿跑完的硬上限(仅等待, 不是重发)
AUTH_MIN_LEFT_S = 30.0       # --go 要求授权窗至少剩这么多秒
START_TOL_MM = 15.0          # --go 要求当前位姿接近"假定起点"
START_TOL_DEG = 4.0
ROT_SKILL = "L2.gold_pt2_split_rot"     # 段1: 一个多阶段技能, N 个服务步, 每步调 /move_pose
TRANS_SKILL = "L2.gold_pt2_split_trans"  # 段2: 一个多阶段技能(位置在变 ⇒ 位置等到位有效), 走 /move_line
TARGET_DEFAULT = "金手指点2"
POS_DEC = 6                  # 位置打印精度

OLD_PT2 = {"pos": [0.588737, 0.142627, 0.641534],
           "quat": [0.348887, 0.000794, 0.936505, 0.035146]}
PT1_NAME = "金手指点1"


# -------------------------------- 小工具 (纯 python, 无 numpy) --------------------------------
def qn(q):
    n = math.sqrt(sum(float(v) * float(v) for v in q)) or 1.0
    return [float(v) / n for v in q]


def qdot(a, b):
    return sum(float(x) * float(y) for x, y in zip(a, b))


def qslerp(a, b, t):
    a, b = qn(a), qn(b)
    d = qdot(a, b)
    if d < 0.0:
        b = [-v for v in b]
        d = -d
    if d > 0.9995:
        return qn([a[i] + t * (b[i] - a[i]) for i in range(4)])
    th = math.acos(max(-1.0, min(1.0, d)))
    s = math.sin(th)
    w0 = math.sin((1.0 - t) * th) / s
    w1 = math.sin(t * th) / s
    return qn([a[i] * w0 + b[i] * w1 for i in range(4)])


def qangle_deg(a, b):
    return math.degrees(2.0 * math.acos(max(-1.0, min(1.0, abs(qdot(qn(a), qn(b)))))))


def vdist(a, b):
    return math.dist([float(x) for x in a], [float(x) for x in b])


def fmt_pos(p):
    return "[%s]" % ", ".join(("%." + str(POS_DEC) + "f") % float(v) for v in p)


def fmt_quat(q):
    q = qn(q)
    return "[%.7f, %.7f, %.7f, %.7f]" % (q[0], q[1], q[2], q[3])


def _stage_timeout(st, lin_mm, speed):
    """复刻 l2_daemon._stage_timeout (l2_daemon.py:895) —— dry-run 里给的是真会写进指令的那个数。"""
    base = float(st.get("timeout_s", 40.0))
    if not st.get("timeout_dynamic", True):
        return base
    cap_nom = 30.0
    v = min(float(speed or 30), cap_nom / 0.0935)
    eff = max(0.00935 * v, 0.35)
    return max(base, round(15.0 + lin_mm / eff * 1.6, 1))


def _rot_timeout(deg):
    """段1 单步旋转的等待上限: 复刻 daemon J6 口径 max(90, 20+|deg|*6) (l2_daemon.py:548/1378)。"""
    return int(max(90, 20 + abs(float(deg)) * 6))


def _args_to_yaml(a):
    """复刻 l2_daemon._args_to_yaml (l2_daemon.py:579-591), 逐字 —— 让 dry-run 打的服务调用 = 执行器真发的字节。"""
    def val(v):
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, int):
            return str(v)
        if isinstance(v, float):
            return repr(v)
        if isinstance(v, (list, tuple)):
            return "[" + ", ".join(val(x) for x in v) + "]"
        return str(v)
    return "{" + ", ".join("%s: %s" % (k, val(v)) for k, v in a.items()) + "}"


def _service_cmd(st):
    """复刻 l2_daemon._service_cmd (l2_daemon.py:594-597)。"""
    return 'timeout %d ros2 service call %s %s "%s"' % (
        int(float(st.get("timeout_s", 60)) + 10), st["srv"], st["type"], _args_to_yaml(st.get("args") or {}))


def move_pose_args(pos, quat, speed):
    """服务步 args: TargetPose 请求体(字段顺序 = 执行器会打印的顺序)。"""
    return {"speed": float(speed),
            "joint_state": {"name": [], "position": []},
            "pose": {"position": {"x": float(pos[0]), "y": float(pos[1]), "z": float(pos[2])},
                     "orientation": {"x": float(quat[0]), "y": float(quat[1]),
                                     "z": float(quat[2]), "w": float(quat[3])}}}


def _move_line_call(pos, quat, speed, lin_mm, timeout_s):
    """复刻 l2_daemon 阶段(运动步)下发字节 (l2_daemon.py:868-870), 逐字 —— 段2 用 /move_line。"""
    st = {"timeout_s": timeout_s}
    to = int(_stage_timeout(st, lin_mm, speed) + 10)
    return ('timeout %d ros2 service call /move_line interfaces/srv/TargetPose '
            '"{speed: %s, joint_state: {name: [], position: []}, pose: {position: '
            '{x: %s, y: %s, z: %s}, orientation: {x: %s, y: %s, z: %s, w: %s}}}"'
            % (to, speed, pos[0], pos[1], pos[2], quat[0], quat[1], quat[2], quat[3]))


# -------------------------------- IO (只读) --------------------------------
def read_live_pose():
    with open(LATEST, encoding="utf-8") as f:
        d = json.load(f)
    pos = [float(d["x"]), float(d["y"]), float(d["z"])]
    quat = [float(d["qx"]), float(d["qy"]), float(d["qz"]), float(d["qw"])]
    try:
        age = time.time() - os.path.getmtime(LATEST)
    except OSError:
        age = -1.0
    return pos, quat, d.get("t"), age


def read_point(name):
    with open(POINTS, encoding="utf-8") as f:
        pts = (json.load(f) or {}).get("points") or {}
    if name not in pts:
        raise SystemExit("点位 %r 不在点位库 %s" % (name, POINTS))
    p = pts[name]
    return [float(v) for v in p["pos"]], [float(v) for v in p["quat"]], p


def get_status():
    try:
        with urllib.request.urlopen(CTL_BASE + "/ctl/status", timeout=8) as r:
            return json.load(r)
    except Exception as e:                                            # noqa: BLE001
        return {"_err": str(e)}


def http_post(path, payload, timeout):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(CTL_BASE + path, data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:                              # 403 授权拒绝等
        try:
            return json.load(e)
        except Exception:                                            # noqa: BLE001
            return {"ok": False, "http": e.code, "msg": str(e)}
    except Exception as e:                                           # noqa: BLE001
        return {"ok": False, "msg": str(e)}


# -------------------------------- 计划计算 --------------------------------
def build_plan(start_pos, start_q, tgt_pos, tgt_q, rot_step, trans_step):
    start_pos, start_q = list(map(float, start_pos)), qn(start_q)
    tgt_pos, tgt_q = list(map(float, tgt_pos)), qn(tgt_q)
    ang = qangle_deg(start_q, tgt_q)
    dvec = [tgt_pos[i] - start_pos[i] for i in range(3)]
    dist = math.dist(start_pos, tgt_pos)

    # 段1: 原地转身 (位置不动, 姿态 slerp 到目标) —— 每步一个 /move_pose 服务步
    n_rot = int(math.ceil(ang / rot_step)) if ang > MIN_ANG_DEG else 0
    rot_steps = []
    for i in range(1, n_rot + 1):
        t = i / float(n_rot)
        rot_steps.append({"k": i, "n": n_rot, "pos": list(start_pos), "quat": qslerp(start_q, tgt_q, t),
                          "step_deg": qangle_deg(qslerp(start_q, tgt_q, (i - 1) / float(n_rot)),
                                                 qslerp(start_q, tgt_q, t)),
                          "from_start_deg": qangle_deg(start_q, qslerp(start_q, tgt_q, t)),
                          "dpos_mm": 0.0, "dz_mm": 0.0})

    # 段2: 平移 (保持目标姿态, 位置线性到目标) —— 每步一个 /move_line 运动步
    n_tr = int(math.ceil(dist * 1000.0 / trans_step)) if dist * 1000.0 > MIN_DIST_MM else 0
    tr_steps = []
    prev = start_pos
    for j in range(1, n_tr + 1):
        t = j / float(n_tr)
        p = [start_pos[i] + dvec[i] * t for i in range(3)]
        tr_steps.append({"k": j, "n": n_tr, "pos": p, "quat": list(tgt_q),
                         "dpos_mm": vdist(p, prev) * 1000.0, "dz_mm": (p[2] - prev[2]) * 1000.0,
                         "from_start_mm": vdist(p, start_pos) * 1000.0})
        prev = p

    # 校验
    checks = []
    plan_noop_rot = (n_rot == 0)
    plan_noop_tr = (n_tr == 0)
    mx_rot = max([s["step_deg"] for s in rot_steps], default=0.0)
    mx_tr = max([s["dpos_mm"] for s in tr_steps], default=0.0)
    checks.append(("段1 单步旋转 <= %.0f°" % MAX_ROT_STEP_DEG, mx_rot <= MAX_ROT_STEP_DEG + 1e-6,
                   "max=%.3f°" % mx_rot))
    checks.append(("段2 单步平移 <= %.0fmm" % MAX_TRANS_STEP_MM, mx_tr <= MAX_TRANS_STEP_MM + 1e-6,
                   "max=%.3fmm" % mx_tr))
    # 步步不回退 (单调递进)
    rot_mono = all(rot_steps[i]["from_start_deg"] >= rot_steps[i - 1]["from_start_deg"] - 1e-9
                   for i in range(1, len(rot_steps)))
    tr_mono = all(tr_steps[i]["from_start_mm"] >= tr_steps[i - 1]["from_start_mm"] - 1e-9
                  for i in range(1, len(tr_steps)))
    checks.append(("段1 姿态步步递进(不回退)", rot_mono, "slerp 夹角单调"))
    checks.append(("段2 位移步步递进(不回退)", tr_mono, "线性参数单调"))
    # 无抬升
    lift_rot = [s for s in rot_steps if s["dz_mm"] > 1e-6]
    lift_tr = [s for s in tr_steps if s["dz_mm"] > 1e-6]
    checks.append(("全程无抬升(Δz<=0)", (not lift_rot) and (not lift_tr),
                   "段1 Δz=0; 段2 单步最大 Δz=%+.3fmm" % (max([s["dz_mm"] for s in tr_steps] or [0.0]))))
    # 终态到达
    end_q_ok = qangle_deg(rot_steps[-1]["quat"], tgt_q) < 1e-6 if rot_steps else True
    end_p_ok = vdist(tr_steps[-1]["pos"], tgt_pos) * 1000 < 1e-6 if tr_steps else True
    checks.append(("段1 末段姿态 = 目标姿态", end_q_ok, "slerp t=1"))
    checks.append(("段2 末段位置 = 目标位置", end_p_ok, "线性 t=1"))
    # 整段净位移/转角再确认(无动作时视为一致)
    _rot_sum = sum(s["step_deg"] for s in rot_steps)
    _tr_sum = sum(s["dpos_mm"] for s in tr_steps)
    checks.append(("总转角/总位移与真值一致",
                   (abs(ang - _rot_sum) < 1e-6 or plan_noop_rot) and
                   (abs(dist * 1000 - _tr_sum) < 1e-6 or plan_noop_tr),
                   "转 %.3f° · 移 %.3fmm" % (ang, dist * 1000)))

    return {"ang": ang, "dist_mm": dist * 1000, "dvec_mm": [v * 1000 for v in dvec],
            "n_rot": n_rot, "n_tr": n_tr, "rot_steps": rot_steps, "tr_steps": tr_steps,
            "checks": checks, "start_pos": start_pos, "start_q": start_q,
            "tgt_pos": tgt_pos, "tgt_q": tgt_q}


def make_skill(skill_id, label, steps, note=None):
    return {
        "id": skill_id, "name": label, "icon": "\U0001f3af", "ros": "line_abs",
        "group": "金手指点2 两段式(脚本临时)",
        "speed_max": SPEED_MAX,
        "param": {},
        "guard": {"max_lin_mm": 120.0, "dz_down_limit_mm": 25},
        "steps": steps,
        "note": note or ("由 tools/step_gold_pt2_split.py 幂等注册(可覆盖重建); "
                         "不含任何抬升步骤; 绝对目标, 免相对漂移。"),
    }


def rot_skill_steps(plan):
    """段1 的 N 个**服务步**: 每步调 /move_pose(绝对位姿: 位置不动 + 姿态 slerp 到该步)。
    服务步由 run_stages 走 _service_call → 同步 `ros2 service call /move_pose`(见文件头【改动 A/B】)。"""
    out = []
    for s in plan["rot_steps"]:
        out.append({"stage": s["k"], "op": "service",
                    "srv": MOVE_POSE_SRV, "type": MOVE_POSE_TYPE,
                    "args": move_pose_args(s["pos"], s["quat"], SPEED),
                    "timeout_s": _rot_timeout(s["step_deg"]), "dwell_s": ROT_DWELL_S,
                    "to_label": "goldpt2_split_rot_%d" % s["k"],
                    "note": "段1 第%d/%d步 原地转身 %.2f° (调 /move_pose, 位置不动)"
                            % (s["k"], s["n"], s["step_deg"])})
    return out


def trans_skill_steps(plan):
    out = []
    for s in plan["tr_steps"]:
        out.append({"stage": s["k"], "to_pos": [round(v, 9) for v in s["pos"]],
                    "to_label": "goldpt2_split_trans_%d" % s["k"],
                    "quat": [round(v, 9) for v in plan["tgt_q"]],
                    "guard": {"dz_down_limit_mm": 25}, "tol_mm": 1.0,
                    "timeout_s": 120, "dwell_s": 1.0,
                    "note": "段2 平移 %.2fmm(#%d/%d, 姿态保持目标)" % (s["dpos_mm"], s["k"], s["n"])})
    return out


def plan_skills(plan):
    """→ [(skill_dict, label), ...] (段1 一个服务步技能 + 段2 一个运动步技能)。"""
    return [
        (make_skill(ROT_SKILL, "\U0001f3af 金手指点2(段1转身·/move_pose)", rot_skill_steps(plan),
                    note="段1 用**服务步**逐步调 /move_pose(l2_daemon 服务步机制): 位置不动 + 姿态 slerp; "
                         "同步阻塞 ⇒ 不依赖只看位置的 wait_arrive; 无抬升。"),
         "\U0001f3af 金手指点2(段1转身·/move_pose)"),
        (make_skill(TRANS_SKILL, "\U0001f3af 金手指点2(段2平移)", trans_skill_steps(plan),
                    note="段2 用**运动步**走 /move_line(位置在变 ⇒ 位置等到位有效): 姿态保持目标; 无抬升。"),
         "\U0001f3af 金手指点2(段2平移)"),
    ]


def render(plan, src_desc):
    L = []
    A = L.append
    A("=" * 92)
    A("【--dry-run 计划】两段式到达『%s』 · 起点=%s" % (TARGET_DEFAULT, src_desc))
    A("=" * 92)
    A("起点位姿 pos=%s" % fmt_pos(plan["start_pos"]))
    A("         quat=%s" % fmt_quat(plan["start_q"]))
    A("目标位姿 pos=%s" % fmt_pos(plan["tgt_pos"]))
    A("         quat=%s" % fmt_quat(plan["tgt_q"]))
    A("整段: 旋转 %.3f° · 直线位移 %.3fmm · Δ=(%+.1f, %+.1f, %+.1f)mm"
      % (plan["ang"], plan["dist_mm"], *plan["dvec_mm"]))
    A("总步数: 段1 %d 步(每步 <=%.0f°, 服务步 /move_pose) + 段2 %d 步(每步 <=%.1fmm, 运动步 /move_line) = **%d 步**"
      % (plan["n_rot"], ROT_STEP_DEG, plan["n_tr"], TRANS_STEP_MM, plan["n_rot"] + plan["n_tr"]))
    A("路线: 段1 = 一个多阶段技能(含 %d 个 op:service 步, 每步调 /move_pose · 同步阻塞) · 段2 = 一个多阶段技能(/move_line)"
      % plan["n_rot"])
    A("")
    A("--- 段1 原地转身 (位置不动, 姿态 slerp; %d 步, 每步一条 /move_pose 服务步) ---" % plan["n_rot"])
    if plan["n_rot"] == 0:
        A("    (起点姿态已等于目标姿态 ⇒ 段1 无动作)")
    for s in plan["rot_steps"]:
        A("  #%02d/%d  op=service srv=%s  timeout_s=%d" % (s["k"], s["n"], MOVE_POSE_SRV, _rot_timeout(s["step_deg"])))
        A("        起 pos=%s quat=%s" % (fmt_pos(plan["start_pos"]),
                                         fmt_quat(plan["start_q"] if s["k"] == 1 else plan["rot_steps"][s["k"] - 2]["quat"])))
        A("        止 pos=%s quat=%s" % (fmt_pos(s["pos"]), fmt_quat(s["quat"])))
        A("        本步 %6.3f°  累计 %7.3f°  位置漂移 0.000mm  Δz=%+.3fmm"
          % (s["step_deg"], s["from_start_deg"], s["dz_mm"]))
    A("")
    A("--- 段2 平移 (姿态保持目标, 位置线性; %d 步, 一个多阶段技能) ---" % plan["n_tr"])
    if plan["n_tr"] == 0:
        A("    (起点位置已等于目标位置 ⇒ 段2 无动作)")
    for s in plan["tr_steps"]:
        A("  #%03d/%d  pos=%s  本步 %6.3fmm  累计 %7.3fmm  Δz=%+.3fmm"
          % (s["k"], s["n"], fmt_pos(s["pos"]), s["dpos_mm"], s["from_start_mm"], s["dz_mm"]))
    A("")
    A("--- 校验 (每段旋转<=30°, 平移<=20mm, 步步不回退, 无抬升) ---")
    allok = True
    for name, ok, detail in plan["checks"]:
        allok = allok and ok
        A("  [%s] %s  (%s)" % ("PASS" if ok else "FAIL", name, detail))
    A("  => 校验总判定: %s" % ("全部通过 ✅" if allok else "有不通过项 ❌ (计划拒绝)"))
    A("")
    return "\n".join(L), allok


def render_commands(plan):
    L = []
    A = L.append
    A("--- 计划发下的命令 (逐字; 经 POST /ctl/move, 与页面按钮同一条链) ---")
    if plan["n_rot"]:
        A("  段1: POST %s/ctl/move  %s" % (CTL_BASE,
          json.dumps({"skill": ROT_SKILL, "speed": SPEED, "arm": 1}, ensure_ascii=False)))
        A("       (一条 POST 触发技能内 %d 个服务步; 每步由执行器同步下发 /move_pose —— 见下逐字)" % plan["n_rot"])
    else:
        A("  段1: (无动作, 不发)")
    if plan["n_tr"]:
        A("  段2: POST %s/ctl/move  %s" % (CTL_BASE,
          json.dumps({"skill": TRANS_SKILL, "speed": SPEED, "arm": 1}, ensure_ascii=False)))
    else:
        A("  段2: (无动作, 不发)")
    A("  (dry-run: 上面 arm=1 的形态只是**计划**; 本次一律以 arm=0 演练, 或干脆不发 HTTP)")
    A("")
    A("--- 执行器内部将逐字下发的 ros2 调用 ---")
    if plan["n_rot"]:
        A("  段1 逐字(每步一条; 由 _service_call → `ros2 service call /move_pose` 发, 字节口径=执行器真发):")
        for s in plan["rot_steps"]:
            st = {"srv": MOVE_POSE_SRV, "type": MOVE_POSE_TYPE,
                  "timeout_s": _rot_timeout(s["step_deg"]),
                  "args": move_pose_args(s["pos"], s["quat"], SPEED)}
            A("    #%02d/%d  %s" % (s["k"], s["n"], _service_cmd(st)))
    if plan["n_tr"]:
        s0 = plan["tr_steps"][0]
        A("  段2 样张(第1步; 其后每步只有 position 变化, 服务名/格式逐字相同, 走 /move_line):")
        A("    " + _move_line_call(s0["pos"], plan["tgt_q"], SPEED, s0["dpos_mm"], 120))
    A("")
    return "\n".join(L)


# -------------------------------- 真发路径 (写了; 默认不执行) --------------------------------
def _ensure_beep():
    try:
        r = subprocess.run(["pgrep", "-f", "tools/motion_beep.py"], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            print("  [警报] motion_beep.py 常驻在跑 (pid=%s) ✅" % r.stdout.split()[0])
            return True
    except Exception:                                                 # noqa: BLE001
        pass
    print("  [警报] motion_beep.py 没在跑 -> 拉起 tools/motion_beep_start.sh")
    try:
        subprocess.run(["bash", os.path.join(REPO, "tools/motion_beep_start.sh")], timeout=20)
        return True
    except Exception as e:                                            # noqa: BLE001
        print("  [警报] 拉起失败: %s (报警是硬要求, --go 中止)" % e)
        return False


def _register_skills(plan, dry=False):
    """幂等注册段1/段2 两个多阶段技能 + 加白名单覆盖层 (备份 + 原子写 + 语法自检, 与 register_*.py 同套)。"""
    defs = [d for d, _lbl in plan_skills(plan)]
    with open(REGISTRY, encoding="utf-8") as f:
        reg = json.load(f)
    skills = reg["skills"]
    assert isinstance(skills, list), "registry.skills 不是 list, 本脚本不处理该形态"
    ids = {s["id"]: i for i, s in enumerate(skills)}
    for sk in defs:
        if sk["id"] in ids:
            skills[ids[sk["id"]]] = sk
        else:
            skills.append(sk)
    with open(OVERLAY, encoding="utf-8") as f:
        ov = json.load(f)
    ov.setdefault("skills", {})
    for sk, lbl in plan_skills(plan):
        ov["skills"][sk["id"]] = lbl
    if dry:
        print("  [注册] (dry) 将写入 %d 个技能到 %s + %s (未写盘)"
              % (len(defs), os.path.basename(REGISTRY), os.path.basename(OVERLAY)))
        return
    ts = time.strftime("%Y%m%d_%H%M%S")
    shutil.copyfile(REGISTRY, REGISTRY + ".bak_goldpt2split_" + ts)
    tmp = REGISTRY + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=2)
    json.load(open(tmp, encoding="utf-8"))
    os.replace(tmp, REGISTRY)
    tmp2 = OVERLAY + ".tmp"
    with open(tmp2, "w", encoding="utf-8") as f:
        json.dump(ov, f, ensure_ascii=False, indent=2)
    json.load(open(tmp2, encoding="utf-8"))
    os.replace(tmp2, OVERLAY)
    print("  [注册] 已写 %d 个技能(%s, 备份 .bak_goldpt2split_%s) + %s (daemon 注册表 mtime 热加载)"
          % (len(defs), os.path.basename(REGISTRY), ts, os.path.basename(OVERLAY)))


def _log_off():
    try:
        return os.path.getsize(DAEMON_LOG)
    except OSError:
        return 0


def _tail_from(off):
    try:
        with open(DAEMON_LOG, encoding="utf-8", errors="replace") as f:
            f.seek(off)
            return f.read()
    except OSError:
        return ""


def _wait_segment(n_stages, off, tag):
    """等执行器把这条腿跑完 (看日志终态行)。**只等待, 绝不重发。** 超上限 => 返回 ('timeout', tail)。"""
    t0 = time.time()
    while time.time() - t0 < SEG_WAIT_CAP_S:
        txt = _tail_from(off)
        if ("✅ 全部 %d 阶段完成" % n_stages) in txt:
            return "done", txt
        for bad in ("🛑", "拒绝", "未在", "被拦", "拒发", "服务失败"):
            if bad in txt:
                return "abort", txt
        time.sleep(2.0)
    return "timeout", _tail_from(off)


def _residual(target_pos, target_q, tag):
    p, q, t, age = read_live_pose()
    ep = vdist(p, target_pos) * 1000.0
    eq = qangle_deg(q, target_q)
    ok = (ep <= RESID_TOL_MM) and (eq <= RESID_TOL_DEG)
    print("  [%s 回读] pos=%s (残差 %.3fmm) · quat=%s (残差 %.3f°) · 帧龄 %.2fs => %s"
          % (tag, fmt_pos(p), ep, fmt_quat(q), eq, age, "OK ✅" if ok else "超限 ❌"))
    return ok, ep, eq


def run_go(plan, args):
    print("\n==================== --go 真发路径 (需 8793 已授权) ====================")
    st = get_status()
    if "_err" in st:
        raise SystemExit("拒绝: 读不到 8793 状态(%s) => 未授权, 不下发" % st["_err"])
    auth = st.get("auth") or {}
    left = float(auth.get("left_s") or 0.0)
    if not auth.get("armed"):
        print("🛑 拒绝执行: 未授权真动 / 授权窗已过期。")
        print("   当前 8793 授权状态: armed=%s · left_s=%.1f · epoch=%s · ip=%s · revoked_at=%s"
              % (auth.get("armed"), left, auth.get("epoch"), auth.get("ip"), auth.get("revoked_at")))
        print("   => 请先在 8793 工位总览点『🔓 授权真动』并二次确认(现场确认无人), 再重跑 --go。")
        return 2
    if left < AUTH_MIN_LEFT_S:
        print("🛑 拒绝执行: 授权窗只剩 %.1fs (< %.0fs), 不够跑完两段。 (armed=%s epoch=%s)"
              % (left, AUTH_MIN_LEFT_S, auth.get("armed"), auth.get("epoch")))
        return 2
    print("🔐 8793 授权状态: armed=True · left_s=%.1f · epoch=%s · ip=%s ✅"
          % (left, auth.get("epoch"), auth.get("ip")))
    # 起点必须与"假定起点"一致 (否则第一段会变成大跳, 直接拒)
    p0, q0, t0, age0 = read_live_pose()
    dp, dq = vdist(p0, plan["start_pos"]) * 1000.0, qangle_deg(q0, plan["start_q"])
    if dp > START_TOL_MM or dq > START_TOL_DEG:
        print("🛑 拒绝执行: 当前位姿与假定起点不符 (pos 差 %.1fmm > %.1fmm 或 姿态差 %.2f° > %.1f°)。"
              % (dp, START_TOL_MM, dq, START_TOL_DEG))
        print("   当前 pos=%s quat=%s ; 假定起点 pos=%s" % (fmt_pos(p0), fmt_quat(q0), fmt_pos(plan["start_pos"])))
        return 2
    print("    当前位姿≈假定起点 (pos 差 %.2fmm, 姿态差 %.2f°) ✅" % (dp, dq))
    if not _ensure_beep():
        return 2
    _register_skills(plan, dry=False)
    time.sleep(1.0)

    # 段1: 服务步(/move_pose), 同步逐段; 不依赖只看位置的 wait_arrive
    if plan["n_rot"]:
        print("\n--- 段1 原地转身: 下发 %s (%d 个 /move_pose 服务步) ---" % (ROT_SKILL, plan["n_rot"]))
        off = _log_off()
        resp = http_post("/ctl/move", {"skill": ROT_SKILL, "speed": SPEED, "arm": 1}, CMD_TIMEOUT_S)
        print("  受理: %s" % json.dumps(resp, ensure_ascii=False)[:400])
        if not resp.get("ok"):
            print("🛑 段1 受理失败 => 停止, 不重发。现场结论: %s" % resp.get("msg"))
            return 3
        res, tail = _wait_segment(plan["n_rot"], off, "段1")
        print("  段1 终态: %s" % res)
        ok, ep, eq = _residual(plan["tgt_pos"], plan["tgt_q"], "段1")
        if res != "done" or not ok:
            print("🛑 段1 %s (位置残差 %.3fmm / 姿态残差 %.3f°) => 停止, 不进段2, 不重发。" % (res, ep, eq))
            print("   执行器尾部:\n" + "\n".join("     " + l for l in tail.strip().splitlines()[-8:]))
            return 3
    else:
        print("\n--- 段1: 无动作, 跳过 ---")

    # 段2: 运动步(/move_line), daemon 位置等到位有效
    if plan["n_tr"]:
        print("\n--- 段2 平移: 下发 %s (%d 步) ---" % (TRANS_SKILL, plan["n_tr"]))
        off = _log_off()
        resp = http_post("/ctl/move", {"skill": TRANS_SKILL, "speed": SPEED, "arm": 1}, CMD_TIMEOUT_S)
        print("  受理: %s" % json.dumps(resp, ensure_ascii=False)[:400])
        if not resp.get("ok"):
            print("🛑 段2 受理失败 => 停止, 不重发。现场结论: %s" % resp.get("msg"))
            return 3
        res, tail = _wait_segment(plan["n_tr"], off, "段2")
        print("  段2 终态: %s" % res)
        ok, ep, eq = _residual(plan["tgt_pos"], plan["tgt_q"], "段2")
        if res != "done" or not ok:
            print("🛑 段2 %s (位置残差 %.3fmm / 姿态残差 %.3f°) => 停止, 不重发, 不自动找回。" % (res, ep, eq))
            print("   执行器尾部:\n" + "\n".join("     " + l for l in tail.strip().splitlines()[-8:]))
            return 3
    else:
        print("\n--- 段2: 无动作, 跳过 ---")

    okp, ep, eq = _residual(plan["tgt_pos"], plan["tgt_q"], "终点")
    print("\n✅ 两段完成并回读核验: 终点位置残差 %.3fmm · 姿态残差 %.3f°" % (ep, eq))
    return 0


# -------------------------------- main --------------------------------
def parse_start(arg, live):
    if arg == "current":
        return list(live[0]), list(live[1]), "current(实时位姿 %s)" % (live[2] or "?")
    if arg == "oldpt2":
        return list(OLD_PT2["pos"]), list(OLD_PT2["quat"]), "oldpt2(历史点2)"
    if arg == "pt1":
        p, q, _ = read_point(PT1_NAME)
        return p, q, "pt1(点位库 %s)" % PT1_NAME
    parts = arg.replace(",", " ").split()
    if len(parts) == 7:
        v = [float(x) for x in parts]
        return v[:3], qn(v[3:7]), "自定义七元组"
    raise SystemExit("--from 只认 current|oldpt2|pt1|'x,y,z,qx,qy,qz,qw' (收到 %r)" % arg)


def main():
    global SPEED, CTL_BASE
    ap = argparse.ArgumentParser(description="两段式到达『金手指点2』(段1 原地转身 /move_pose + 段2 平移 /move_line)")
    ap.add_argument("--from", dest="src", default="current",
                    help="起点: current(默认)|oldpt2|pt1|x,y,z,qx,qy,qz,qw")
    ap.add_argument("--to", dest="tgt", default=TARGET_DEFAULT, help="目标点名(默认 %s)" % TARGET_DEFAULT)
    ap.add_argument("--rot-step-deg", type=float, default=ROT_STEP_DEG)
    ap.add_argument("--trans-step-mm", type=float, default=TRANS_STEP_MM)
    ap.add_argument("--speed", type=float, default=SPEED)
    ap.add_argument("--ctl-base", default=CTL_BASE,
                    help="控制服务基址(默认 %s); 仅便于**安全演练**(指向假状态服务, 验证拒绝路径)" % CTL_BASE)
    ap.add_argument("--dry-run", action="store_true", help="默认即演练; 显式给出更明确")
    ap.add_argument("--go", action="store_true", help="真发(必须 8793 已授权; 本脚本默认不真发)")
    ap.add_argument("--probe-daemon", action="store_true",
                    help="额外做一次**零运动**探测: arm=0 干跑既有 L2.goto_gold_pt2, 核对执行器算出的目标位姿")
    args = ap.parse_args()
    SPEED = float(args.speed)
    CTL_BASE = args.ctl_base

    live = read_live_pose()
    print("读实时位姿(只读 %s): pos=%s quat=%s 帧龄=%.2fs"
          % (os.path.relpath(LATEST, REPO), fmt_pos(live[0]), fmt_quat(live[1]), live[3]))

    s_pos, s_q, s_desc = parse_start(args.src, live)
    t_pos, t_q, t_meta = read_point(args.tgt)
    print("目标点位 %r = %s (记录于 %s)" % (args.tgt, fmt_pos(t_pos), t_meta.get("recorded_at")))

    plan = build_plan(s_pos, s_q, t_pos, t_q, args.rot_step_deg, args.trans_step_mm)
    plan["start_desc"] = s_desc

    txt, allok = render(plan, s_desc)
    txt += render_commands(plan)
    print(txt)

    # 安全评估 (只读)
    st = get_status()
    if "_err" in st:
        print("%s 状态: 读不到 (%s)" % (CTL_BASE, st["_err"]))
    else:
        a = st.get("auth") or {}
        print("%s 授权: armed=%s left_s=%.1f epoch=%s ip=%s" %
              (CTL_BASE, a.get("armed"), float(a.get("left_s") or 0), a.get("epoch"), a.get("ip")))
    if args.probe_daemon:
        print("\n[零运动探测] arm=0 干跑 L2.goto_gold_pt2 (不下发运动), 核对执行器目标位姿:")
        r = http_post("/ctl/move", {"skill": "L2.goto_gold_pt2", "speed": 8, "arm": 0}, 20)
        print("  " + json.dumps(r, ensure_ascii=False)[:600])

    if not allok:
        print("\n❌ 计划未通过校验 => 拒绝执行(即使 --go)。")
        return 2
    if args.go and not args.dry_run:
        return run_go(plan, args)
    print("(--dry-run 模式: 未发任何 HTTP 请求真动; 未注册技能; 未下发运动)")
    if args.src == "current" and plan["n_rot"] == 0 and plan["n_tr"] == 0:
        print("提示: 默认起点=current 且当前已在目标点 ⇒ 计划为空。要看真实的 138°/大位移拆分, 用:")
        print("      python3 tools/step_gold_pt2_split.py --from oldpt2")
    return 0


if __name__ == "__main__":
    sys.exit(main())
