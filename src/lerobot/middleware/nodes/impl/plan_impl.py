# -*- coding: utf-8 -*-
"""🧭 运动规划 (plan) 节点 · 真实现  (registry key = n_moveit, 源码落点 = 本文件)

老倪 2026-10-28: 「运动规划节点的源代码怎么能是 library.py 呢？应该是 plan 的代码」——
  原来 node_moveit 的实现正文写在 registry 大文件 library.py 里（而且只做了"可用性探针"），
  右键「打开源代码」自然落到 library.py。本文件就是它的**真身**：
  library.node_moveit 只剩一个薄壳转调 run()，源码映射一律指向这里。

职责: 原子技能意图 + 安全限制 → **段表 (PlanSegments)**。
      只规划，永不动作：本文件不 import 任何下发接口，不写 exec 文件，不碰授权。

真源 (只读):
  起点 = zmax_data/rokae_sdk/tcp_out/latest.json   (真机 TCP 真值, 采样器 50Hz 写: x/y/z + ts)
  目标 = ctx["in1"]                                ({"tcp":[x,y,z]} / {"pos":[..]} / [x,y,z] / 点名/槽号/观测点)
  安全 = ctx["in2"]                                ({"max_step_mm":50,"max_down_mm":20,...})
  势场 = ctx["in3"]                                (ss_grav_h.out1: {"dir","mag","main","layers"})
  技能 = ctx["in4".."in11"]                         (8 个原子技能 sssk1~8.out1, ①~⑧ 一一对应)
       · 技能是 plan 的**上游** (老倪 2026-11-01 端口对正): in4 缺目标时才作目标点, in1 显式目标优先;
       · 势场力真读: |F| ≥ force_veto_mag ⇒ 拒出段表; 否则沿 −F 给目标点做有界偏置 (避高势区)。

口径 (实测过、写在台账里的那套):
  · 起点年龄 > ZMAX_PLAN_STALE_S(默认 2s) ⇒ **拒出段表**，如实报 stale —— 绝不拿旧位姿规划；
  · 后端 rule(确定性): 抬升 → 横移 → 下落 → 末端对位；绕奇异/避碰先抬 LIFT_MM；
    单步 ≤ max_step_mm，向下段 ≤ max_down_mm (与执行器守卫同一口径)；
  · moveit 后端只在 move_group 真可用时报 available，**不冒充**能规划 (MoveItPlan.plan 目前只是探针)；
  · 每段带 abs_mm (= 段终点的绝对坐标 mm) —— l2_daemon 段表要求带绝对坐标。
"""
from __future__ import annotations

import json
import os
import time

_ROOT = os.path.expanduser("~/zmax")
_TCP = os.path.join(_ROOT, "zmax_data", "rokae_sdk", "tcp_out", "latest.json")
STALE_S = float(os.environ.get("ZMAX_PLAN_STALE_S", "2.0"))
DEF_STEP = 50.0          # mm · 单步上限 (执行器守卫口径)
DEF_DOWN = 20.0          # mm · 向下单步上限
LIFT_MM = 50.0           # mm · 抬升量 (绕奇异 50102 / 避碰的安全高度增量)
MAX_SEGS = 40
MIN_CONF = float(os.environ.get("ZMAX_PLAN_MIN_CONF", "0.7"))    # 视觉观测点最低置信度
OBS_STALE_S = float(os.environ.get("ZMAX_PLAN_OBS_STALE_S", "2.0"))  # 视觉观测点最长时效

LAST_STATUS = ""


# ── 真值 / 输入 ─────────────────────────────────────────────────────────────
# 🔀 2026-11-01 死机复产 + 老倪「要真接入」: SIM_POSE 从**启动时读一次**改成**每拍读**
#    (env 优先, 其次运行期开关文件 zmax_data/ss_live/plan_mode.json 的 {"sim_pose": true})
#    原因: 常驻循环的环境变量在 systemd 单元里, 改档要重启服务; 而现场通/不通会来回切,
#    远程无产线网卡时不该让"运动规划"整条链停在第 5 环 (起点陈旧 ⇒ 不出段表 ⇒ AR 无指令)。
#    真机下发侧的授权闸/真值闸不受此开关影响, 输出仍标 pose_src(真机真值 vs AR 虚拟末端)。
def _sim_on() -> bool:
    v = os.environ.get("ZMAX_PLAN_SIM_POSE")
    if v is None:
        try:
            with open(_MODE_FILE, encoding="utf-8") as fh:
                v = (json.load(fh) or {}).get("sim_pose")
        except Exception:                                                   # noqa: BLE001
            v = None
    return str(v if v is not None else "0").strip().lower() in ("1", "true", "on", "yes")


_MODE_FILE = os.path.join(_ROOT, "zmax_data", "ss_live", "plan_mode.json")
_AR_CMD = os.path.join(_ROOT, "zmax_data", "ss_live", "ar_cmd.json")
SIM_POSE = _sim_on()         # 兼容老引用 (导入时的快照, 判据只看 _sim_on())
_POSE_SRC = "tcp(real)"     # 最近一次 _tcp_now() 实际用的位姿来源 (真机真值 / AR 虚拟末端)
_POSE_Q = None              # 最近一次 _tcp_now() 读到的起点姿态 [x,y,z,w] (归一); 读不到 None


def _sim_pose():
    """AR 场景的**虚拟末端** (来自 AR 指令文件的 b 点) —— 只在 ZMAX_PLAN_SIM_POSE=1 时用。

    🧭 2026-11-01 老倪「要真接入」: AR 场景的位姿真值是渲染侧给出的虚拟臂末端, 与真机真值
    两条独立来源。这里只在显式开 SIM_POSE 时回落, 输出里标 pose_src=sim(ar) + sim=True,
    真机下发侧 (l2_daemon) 有自己的授权闸与真值闸, 不受这个开关影响。
    """
    try:
        with open(_AR_CMD, encoding="utf-8") as fh:
            d = json.load(fh)
        b = d.get("b") or d.get("tcp")
        a = d.get("a")
        if not b:
            return None, None
        age = time.time() - float(d.get("t") or 0)
        # 🔴 2026-11-01 老倪「动作变形」真因①: 原来直接拿段的**终点** b 当"当前末端",
        #   等于把"我要去哪"当成"我在哪"。AR 页在段内走 u∈[0,1], 规划却每拍从终点起算
        #   ⇒ 起点每拍跳一次 ⇒ 段表每拍换一份(n 在 21/22/26/40 之间乱跳)。
        #   改为: 有 a 就按段内进度 u 插值 = 臂此刻真实所在的位置。
        if a and len(a) >= 3:
            try:
                _u = min(1.0, max(0.0, float(d.get("u") or 0.0)))
                return [float(a[i]) + (float(b[i]) - float(a[i])) * _u for i in range(3)], age
            except Exception:                                               # noqa: BLE001
                pass
        return [float(b[0]), float(b[1]), float(b[2])], age
    except Exception:                                                       # noqa: BLE001
        return None, None


def _tcp_now():
    """真机当前 TCP 末端的 (x,y,z, age_s)，单位统一成 **mm**；读不到给 (None, None)。

    ⚠️ latest.json 里的 x/y/z 是**米**(真机 SDK 口径)，而段表/执行器要的是 mm ⇒ 这里 ×1000。
    只读，不动臂。
    """
    try:
        with open(_TCP, encoding="utf-8") as fh:
            d = json.load(fh)
        age = time.time() - float(d.get("ts") or 0)
        p = [float(d.get("x")) * 1000.0, float(d.get("y")) * 1000.0, float(d.get("z")) * 1000.0]
        global _POSE_SRC, _POSE_Q
        _POSE_Q = _quat_ok([d.get("qx"), d.get("qy"), d.get("qz"), d.get("qw")])
        if _sim_on() and age > STALE_S:
            _p2, _a2 = _sim_pose()
            if _p2 is not None:
                _POSE_SRC = "sim(ar虚拟末端)"
                return _p2, _a2
        _POSE_SRC = "tcp(real)"
        return p, age
    except Exception:                                                       # noqa: BLE001
        if _sim_on():
            _p2, _a2 = _sim_pose()
            if _p2 is not None:
                globals()["_POSE_SRC"] = "sim(ar虚拟末端)"
                return _p2, _a2
        globals()["_POSE_SRC"] = "无"
        return None, None


def _as_point(v):
    """把裸坐标写法归一成 [x,y,z] mm；认不出给 None。"""
    if v is None:
        return None
    if isinstance(v, dict):
        for k in ("tcp", "pos", "xyz", "target", "goal", "to"):
            if k in v:
                r = _as_point(v[k])
                if r:
                    return r
        if all(k in v for k in ("x", "y", "z")):
            return [float(v["x"]), float(v["y"]), float(v["z"])]
        return None
    if isinstance(v, (list, tuple)) and len(v) >= 3:
        try:
            return [float(v[0]), float(v[1]), float(v[2])]
        except Exception:                                                   # noqa: BLE001
            return None
    return None


def _ps():
    """取 points_source (包内相对导入; 单独跑脚本时补 sys.path)。"""
    try:
        from . import points_source as PS                                      # noqa: PLC0415
    except ImportError:
        import sys                                                             # noqa: PLC0415
        sys.path.insert(0, os.path.join(_ROOT, "src"))
        from lerobot.engineering.nodes import points_source as PS              # noqa: PLC0415
    return PS


def _quat_ok(q):
    """四元数整形: 4 分量 → 归一化 [x,y,z,w]; 缺分量/全零给 None (宁可没有, 不发坏姿态)。"""
    try:
        if not isinstance(q, (list, tuple)) or len(q) != 4:
            return None
        v = [float(x) for x in q]
    except Exception:                                                       # noqa: BLE001
        return None
    n = sum(x * x for x in v) ** 0.5
    if n < 1e-6:
        return None
    return [x / n for x in v]


def _goal_quat(tgt):
    """段表要带的**目标姿态** + 来源。优先级: in1 显式 > 点位示教 > 起点真值(保持当前)。

    老倪 2026-11-02「只有位置, 能保证姿态么」—— 之前段表只有 a/b, 姿态全靠执行器
    "保持当前", 到位判定也只比位置。这里把姿态做成段表的显式字段, 让下游能判、能显示。
    """
    if isinstance(tgt, dict):
        q = _quat_ok(tgt.get("quat"))
        if q:
            return q, str(tgt.get("quat_src") or "point(示教)")
    q = _quat_ok(_POSE_Q)
    if q:
        return q, "start(起点真值·保持)"
    return None, "none"


def _target(ctx, start_frame="base_link"):
    """目标点: 优先按**工程配置里的点名/槽号**取 (§老倪 2026-10-28), 也接受裸坐标。

    认这几种写法 (ctx["in1"].value):
      {"point": "slot5"} / {"point": "槽5", "frame": "sim_base"} / {"slot": 5} / {"slot": 5, "frame":"base_link"}
      {"tcp": [x,y,z]} / [x,y,z]                    ← 裸坐标, 视为 base_link
    返回 {"pos": [mm], "frame", "src", "name", "ts"} ; 取不到给 {"error": ...}。
    """
    PS = _ps()
    v = ((ctx or {}).get("in1") or {}).get("value")
    if isinstance(v, dict):
        frame = v.get("frame") or start_frame
        _q_in = _quat_ok(v.get("quat"))            # in1 显式四元数优先 (调用方指定姿态)
        _obs = v.get("obs")
        if not _obs and isinstance(v.get("point"), str) and v["point"].startswith("obs:"):
            _obs = v["point"][4:]
        if _obs:
            p = PS.find(_obs, frame=frame)
            if not p:
                return {"error": "obs_not_found", "want": _obs, "frame": frame}
            return {"pos": p["pos_mm"], "frame": p["frame"], "src": p["src"], "name": p["name"],
                    "ts": p.get("ts"), "conf": p.get("conf"), "err_mm": p.get("err_mm"), "is_obs": True,
                    "quat": _q_in or p.get("quat"),
                    "quat_src": "in1(显式)" if _q_in else "point(示教)"}
        if v.get("point"):
            p = PS.find(v["point"], frame=frame)
            if not p:
                return {"error": "point_not_found", "want": v["point"], "frame": frame}
            return {"pos": p["pos_mm"], "frame": p["frame"], "src": p["src"],
                    "name": p["name"], "ts": p.get("ts"),
                    "quat": _q_in or p.get("quat"),
                    "quat_src": "in1(显式)" if _q_in else "point(示教)"}
        if v.get("slot") is not None:
            try:
                p = PS.slot(int(v["slot"]), frame=frame)
            except Exception:                                                # noqa: BLE001
                p = None
            if not p:
                return {"error": "slot_not_found", "want": v["slot"], "frame": frame}
            return {"pos": p["pos_mm"], "frame": p["frame"], "src": p["src"],
                    "name": p["name"], "ts": p.get("ts"),
                    "quat": _q_in or p.get("quat"),
                    "quat_src": "in1(显式)" if _q_in else "point(示教)"}
    r = _as_point(v)
    if r:
        return {"pos": r, "frame": start_frame, "src": "in1(裸坐标)", "name": None, "ts": None,
                "quat": _q_in if isinstance(v, dict) else None,
                "quat_src": "in1(显式)" if (isinstance(v, dict) and _q_in) else "none"}
    return None


def _limits(ctx):
    v = ((ctx or {}).get("in2") or {}).get("value") or {}
    if not isinstance(v, dict):
        v = {}
    return {"step": float(v.get("max_step_mm") or DEF_STEP),
            "down": float(v.get("max_down_mm") or DEF_DOWN)}


# ── 输入: 技能动作 (in4) / 势场力 (in3) ────────────────────────────────────
# 老倪 2026-11-01: 「plan 的上游是技能, 端口必须对正, 真读势场力, 真执行」——
#   此前画布把 8 个技能的 out1(动作) 接在 in1(目标点)/in2(安全) 上, 语义错位;
#   而本文件只读 in1/in2, in3(势场) 的线是装饰线。现按端口语义重新对正:
#     in1 目标点 (工程点/槽/观测点/裸坐标)   · 显式目标优先
#     in2 安全约束 ({max_step_mm, max_down_mm})
#     in3 势场力 (ss_grav_h.out1: {dir, mag, main, layers}) → 目标点安全偏置 + 力过大否决
#     in4 技能动作 (sssk*.out1: {skill, stage, active, target[mm], u, gate}) → 缺 in1 时作目标点
_CAL = os.path.join(_ROOT, "config", "calib", "zmax_calib.json")
_PCFG = {"mtime": None, "d": {}}


def _pcfg():
    """工程配置 config/calib/zmax_calib.json:plan_node (mtime 热重载, 缺段回落默认)。"""
    try:
        m = os.path.getmtime(_CAL)
    except OSError:
        return _PCFG["d"]
    if _PCFG["mtime"] != m:
        try:
            with open(_CAL, encoding="utf-8") as fh:
                _PCFG["d"] = (json.load(fh).get("plan_node") or {})
            _PCFG["mtime"] = m
        except Exception:                                                    # noqa: BLE001
            return _PCFG["d"]
    return _PCFG["d"]


SK_PORTS = ("in4", "in5", "in6", "in7", "in8", "in9", "in10", "in11")
_MV = {"t": 0.0, "v": None}


def _moveit_probe():
    """MoveIt 可用性探针 · TTL 缓存 (ZMAX_PLAN_MOVEIT_TTL_S, 默认 10s)。

    实测 MoveItPlan.plan() = 50.7ms/次 —— 探针不是规划, 每拍跑等于白吃半拍预算。
    """
    ttl = float(os.environ.get("ZMAX_PLAN_MOVEIT_TTL_S", "10") or 0)
    now = time.time()
    if _MV["v"] is not None and (now - _MV["t"]) < ttl:
        d = dict(_MV["v"])
        d["cached_age_s"] = round(now - _MV["t"], 1)
        return d
    try:
        from lerobot.arm.arm_control import MoveItPlan                    # noqa: PLC0415
        v = MoveItPlan.plan([0, 0, 0], [0, 0, 0])
    except Exception as e:                                                   # noqa: BLE001
        v = {"available": False, "note": "读不到 MoveItPlan: %s" % type(e).__name__}
    _MV.update(t=now, v=v)
    return v


def _skill_act(ctx):
    """in4..in11 = ①..⑧ 原子技能 → 选**当前生效的那一个** ({pos:[mm], stage, skill, active, u, gate})。

    为什么要按端口分线: 8 个技能如果合流到同一个 in4, 中间件"后写覆盖" ⇒ 永远只剩 ⑧ 的帧。
    分端口后每个技能有独立话题, 这里按 (active, t) 选: 先取 active=True 的, 都没有则取最新一帧。
    """
    best = None
    frames = []
    for p in SK_PORTS:
        v = ((ctx or {}).get(p) or {}).get("value")
        if not isinstance(v, dict) or v.get("kind") != "skill_act":
            continue
        frames.append((p, v))
        pos = _as_point(v.get("target")) if v.get("target") is not None else None
        item = {"pos": pos, "stage": v.get("stage"), "skill": v.get("skill"),
                "active": bool(v.get("active")), "u": v.get("u"), "gate": v.get("gate"),
                "port": p, "ts": float(v.get("t") or 0.0),
                "reason": v.get("reason"), "src": "in4..in11(技能动作)"}
        key = (1 if item["active"] else 0, item["ts"])
        if best is None or key > best[0]:
            best = (key, item)
    if best is None:
        return None
    out = dict(best[1])
    out["n_frames"] = len(frames)
    out["active_ports"] = [f[0] for f in frames if f[1].get("active")]
    return out


def _force(ctx):
    """in3: 势场力 → {"vec":[3], "mag", "main", "layers", "allow"} ; 无给 None。

    ss_grav_h.out1 = {kind:force_corrected, dir(单位向量), mag(速度当量 m/s), main, layers, allow}
    ⇒ 力度量一律取 mag, 方向取 dir; 若上游直接给 F 向量也认。
    """
    v = ((ctx or {}).get("in3") or {}).get("value")
    if not isinstance(v, dict):
        return None
    vec = v.get("F") if isinstance(v.get("F"), (list, tuple)) else None
    mag = v.get("mag")
    d = v.get("dir")
    if vec is None and isinstance(d, (list, tuple)) and len(d) >= 3:
        try:
            vec = [float(d[0]), float(d[1]), float(d[2])]
        except Exception:                                                    # noqa: BLE001
            vec = None
    if vec is not None and mag is not None:
        try:
            vec = [vec[i] * float(mag) for i in range(3)]
        except Exception:                                                    # noqa: BLE001
            pass
    if mag is None and vec is not None:
        mag = (sum(float(x) ** 2 for x in vec[:3])) ** 0.5
    if vec is None and mag is None:
        return None
    return {"vec": ([round(float(x), 6) for x in vec[:3]] if vec else None),
            "mag": (round(float(mag), 6) if mag is not None else None),
            "main": v.get("main"), "layers": v.get("layers"), "allow": v.get("allow"),
            "src": "in3(势场力 ss_grav_h.out1)"}


# ── 确定性分段 (rule 后端) ──────────────────────────────────────────────────
def _split(a, b, cap):
    """把 a→b 按长度上限 cap 均分，返回 [(起, 终), …]（不含起点的重复）。"""
    d = [b[i] - a[i] for i in range(3)]
    dist = (d[0] ** 2 + d[1] ** 2 + d[2] ** 2) ** 0.5
    if dist <= 1e-9:
        return []
    n = max(1, int(-(-dist // max(cap, 1e-6))))          # ceil
    return [([a[i] + d[i] * k / n for i in range(3)],
             [a[i] + d[i] * (k + 1) / n for i in range(3)]) for k in range(n)]


def _segments(start, goal, lim, quat=None, quat_src="none"):
    """抬升 → 横移 → 下落 → 对位。第三分量 = 高度(mm)，与段表/画布口径一致。

    每段都带 ``quat``(目标姿态 [x,y,z,w]) 与 ``quat_src`` —— 段表不再只有位置。
    """
    x0, y0, z0 = start
    x1, y1, z1 = goal
    segs = []

    def add(kind, a, b):
        segs.append({"i": len(segs) + 1, "kind": kind,
                     "a": [round(v, 2) for v in a], "b": [round(v, 2) for v in b],
                     "abs_mm": [round(v, 2) for v in b],
                     "quat": ([round(v, 6) for v in quat] if quat else None),
                     "quat_src": quat_src,
                     "len_mm": round(((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2
                                      + (b[2] - a[2]) ** 2) ** 0.5, 2)})

    flat = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
    # ① 抬到安全高度 (原地) —— 水平要走且现在不高, 就先抬; 已在安全高度以上则跳过
    h_safe = max(z0, z1) + (LIFT_MM if flat > 1.0 else 0.0)
    if h_safe - z0 > 0.5:
        for a, b in _split([x0, y0, z0], [x0, y0, h_safe], lim["step"]):
            add("lift", a, b)
    # ② 横移 (保持安全高度)
    if flat > 0.5:
        for a, b in _split([x0, y0, max(z0, h_safe)], [x1, y1, max(z0, h_safe)], lim["step"]):
            add("move", a, b)
    # ③ 下落 (向下单步受 max_down_mm 限)
    z_from = max(z0, h_safe)
    if z_from - z1 > 0.5:
        for a, b in _split([x1, y1, z_from], [x1, y1, z1], lim["down"]):
            add("down", a, b)
    return segs[:MAX_SEGS]


# ── 段表推进 (2026-11-01 老倪「动作变形」真因②) ─────────────────────────────
# 原来每次 run() 只发 segs[0] 且 u 恒 0.0 ⇒ AR 页每拍都从"第一段起点"重新拉一次臂,
# 关节被反复拉锯, 画面就是"动作变形/抽搐"。改成: 一份段表认一个 plan_id,
# 按时间推进「第几段 + 段内进度 u」, 只有目标真的变了才重规划。
_PLAN = {"id": 0, "segs": [], "goal": None, "t0": 0.0, "dur": [], "tot": 0.0}
_SEG_V = {"lift": 1000.0, "move": 1000.0, "down": 300.0, "pull": 300.0, "insert": 300.0}


def _seg_dur(s):
    """段时长(秒): MoveIt 规划自带 t (按段长分摊的参数化时长) 优先; 否则按段长/名义速度。
    零长度加工序段给 0.12s 地板。"""
    t = s.get("t")
    if t:
        return max(0.12, float(t))
    v = float(_SEG_V.get(str(s.get("kind")), 300.0))
    ln = float(s.get("len_mm") or 0.0)
    return max(0.12, (ln / v) if ln > 0 else 0.12)


def _plan_tick(segs, goal_plan, now):
    """返回 (当前段, 段序号, 段内进度 u, plan_id, 段数, 已用秒)。"""
    gl = [round(float(v), 2) for v in goal_plan]
    dgl = 0.0
    if _PLAN["goal"] is not None:
        dgl = max(abs(gl[i] - _PLAN["goal"][i]) for i in range(3))
    done = (_PLAN["segs"] and (now - _PLAN["t0"]) > _PLAN["tot"] + 0.6)
    if (not _PLAN["segs"]) or dgl > 2.0 or done:
        _PLAN.update({"id": int(_PLAN["id"]) + 1, "segs": list(segs), "goal": gl,
                      "t0": now, "dur": [_seg_dur(x) for x in segs]})
        _PLAN["tot"] = sum(_PLAN["dur"])
    S, D = _PLAN["segs"], _PLAN["dur"]
    if not S:
        return None, 0, 0.0, _PLAN["id"], 0, 0.0
    el = max(0.0, now - _PLAN["t0"])
    cum = 0.0
    idx = len(S) - 1
    for i, dd in enumerate(D):
        if el <= cum + dd:
            idx = i
            u = min(1.0, max(0.0, (el - cum) / dd)) if dd > 0 else 1.0
            return S[idx], idx + 1, u, _PLAN["id"], len(S), round(el, 3)
        cum += dd
    return S[-1], len(S), 1.0, _PLAN["id"], len(S), round(el, 3)


# ── 节点入口 (registry / middleware 都调它) ─────────────────────────────────
def run(ctx=None):
    """一个周期: 起点(真值) + 目标(意图) + 安全限制 → 段表。只规划，不下发。"""
    global LAST_STATUS
    out: dict = {"node": "n_moveit", "impl": "nodes/plan_impl.py:run"}
    start, age = _tcp_now()
    pose_src = _POSE_SRC
    if start:
        out["start"] = [round(v, 2) for v in start]
        out["pose_src"] = pose_src
        out["start_age_s"] = (round(age, 2) if age is not None else None)
    tgt = _target(ctx)
    goal = (tgt or {}).get("pos") if isinstance(tgt, dict) else None
    lim = _limits(ctx)
    out["limits"] = lim
    # 端口对正: in4 技能动作 / in3 势场力 (老倪 2026-11-01)
    skl = _skill_act(ctx)
    frc = _force(ctx)
    cfg = _pcfg()
    if skl is not None:
        out["skill"] = {"skill": skl.get("skill"), "stage": skl.get("stage"),
                        "active": skl.get("active"), "port": skl.get("port"),
                        "n_frames": skl.get("n_frames"), "active_ports": skl.get("active_ports"),
                        "reason": skl.get("reason"), "src": skl.get("src"),
                        "f_need_N": ((skl.get("gate") or {}) or {}).get("f_need_N"),
                        "u_norm": (round(float(sum(float(x) ** 2 for x in (skl.get("u") or [])[:3]) ** 0.5), 6)
                                   if isinstance(skl.get("u"), (list, tuple)) else None)}
    if frc is not None:
        out["force"] = {"mag": frc.get("mag"), "vec": frc.get("vec"), "main": frc.get("main"),
                        "layers": frc.get("layers"), "src": frc.get("src")}
    # 目标优先级: in1 显式目标点 > in4 技能 target (技能是 plan 的上游)
    if not goal and skl is not None and skl.get("pos"):
        goal = list(skl["pos"])
        tgt = {"pos": goal, "frame": "base_link", "src": "in4(技能 target)",
               "name": skl.get("skill"), "ts": None}
        out.update({"goal_src": "in4(技能 target)", "goal_frame": "base_link",
                    "goal_name": skl.get("skill")})
    if isinstance(tgt, dict) and tgt.get("pos"):
        out.update({"goal_src": tgt.get("src"), "goal_frame": tgt.get("frame"),
                    "goal_name": tgt.get("name"), "goal_ts": tgt.get("ts"),
                    "goal_conf": tgt.get("conf"), "goal_err_mm": tgt.get("err_mm")})

    # moveit 只报可用性 (MoveItPlan.plan 是探针, 不冒充能规划) —— 带 TTL 缓存:
    #   实测该探针 50.7ms/次, 10Hz 循环里每拍跑会白吃半拍预算 (画布 loop 本就 220~310ms)。
    out["moveit"] = _moveit_probe()

    # ① 起点不可用 / 陈旧 ⇒ 拒出段表 (不许拿旧位姿规划)
    if not start:
        LAST_STATUS = "无真机 TCP 真值 (%s 读不到) ⇒ 不出段表" % _TCP
        out.update({"ok": False, "reason": "no_tcp", "backend": "rule", "segments": [], "n": 0})
        print("[plan 节点] " + LAST_STATUS)
        return out
    if age is not None and age > STALE_S:
        LAST_STATUS = "起点陈旧 (%.1fs > %.1fs) ⇒ 不出段表" % (age, STALE_S)
        out.update({"ok": False, "reason": "tcp_stale", "backend": "rule", "segments": [], "n": 0})
        print("[plan 节点] " + LAST_STATUS)
        return out
    # ①b 目标点取不到 / 坐标系不符 ⇒ 拒出段表 (仿真基座系 ≠ 真机 base_link, 不许混用)
    if isinstance(tgt, dict) and tgt.get("error"):
        LAST_STATUS = ("目标点取不到 (%s: %s, frame=%s) ⇒ 不出段表"
                       % (tgt.get("error"), tgt.get("want"), tgt.get("frame")))
        out.update({"ok": False, "reason": tgt.get("error"), "backend": "rule", "segments": [], "n": 0})
        print("[plan 节点] " + LAST_STATUS)
        return out
    # 🔀 SIM/AR 档 (ZMAX_PLAN_SIM_POSE=1): 起点就是 AR 虚拟末端(sim 系), 目标也是 sim_base
    #   ⇒ 两边同系, 不算混用。真机档 (sim 关) 仍然只认 base_link, 这条豁免不生效。
    _gf = str((tgt or {}).get("frame") or "base_link")
    if goal and _gf != "base_link" and not (_sim_on() and _gf == "sim_base"):
        _ = None
    if goal and _gf != "base_link" and _sim_on() and _gf == "sim_base":
        out["frame_note"] = "SIM 档: 起点=AR 虚拟末端(sim 系) 与目标 sim_base 同系"
    if goal and str((tgt or {}).get("frame") or "base_link") != "base_link" and not (_sim_on() and _gf == "sim_base"):
        LAST_STATUS = ("目标点在 %s 系, 起点是真机 base_link ⇒ 不混用坐标系, 不出段表"
                       % (tgt or {}).get("frame"))
        out.update({"ok": False, "reason": "frame_mismatch", "backend": "rule", "segments": [], "n": 0})
        print("[plan 节点] " + LAST_STATUS)
        return out
    # ①c 视觉观测点三道闸: 未取证(verified=false) / 置信度 / 时效
    if isinstance(tgt, dict) and tgt.get("is_obs"):
        _vd = _ps().vision_doc()
        if _vd is not None and _vd.get("verified") is False:
            LAST_STATUS = ("观测点未取证 (frame=%s · gaps=%s) ⇒ 不出段表"
                           % (_vd.get("frame"), (_vd.get("source") or {}).get("gaps")))
            out.update({"ok": False, "reason": "obs_unverified", "backend": "rule",
                        "segments": [], "n": 0})
            print("[plan 节点] " + LAST_STATUS)
            return out
    # ①c' 置信度/时效两道闸: 置信度不足 / 观测超龄 ⇒ 拒出段表 (不猜, 不按旧点硬规划)
    if isinstance(tgt, dict) and tgt.get("is_obs"):
        _conf = tgt.get("conf")
        if _conf is None or float(_conf) < MIN_CONF:
            LAST_STATUS = ("观测点置信度不足 (conf=%s < %.2f, 源 %s) ⇒ 不出段表"
                           % (_conf, MIN_CONF, tgt.get("src")))
            out.update({"ok": False, "reason": "low_conf", "backend": "rule", "segments": [], "n": 0})
            print("[plan 节点] " + LAST_STATUS)
            return out
        _age = (time.time() - float(tgt.get("ts") or 0)) if tgt.get("ts") else None
        if _age is None or _age > OBS_STALE_S:
            LAST_STATUS = ("观测点超龄 (%.1fs > %.1fs, 源 %s) ⇒ 不出段表"
                           % ((_age if _age is not None else -1), OBS_STALE_S, tgt.get("src")))
            out.update({"ok": False, "reason": "obs_stale", "backend": "rule", "segments": [], "n": 0})
            print("[plan 节点] " + LAST_STATUS)
            return out
    # ② 没有目标 ⇒ 只报可用性 (与原探针行为一致, 但不假装规划了)
    if not goal:
        LAST_STATUS = "无目标(只报可用性) · 起点 %.0f,%.0f,%.0f · 真机零指令" % tuple(start)
        out.update({"ok": True, "backend": "rule", "segments": [], "n": 0,
                    "note": "in1 没给目标 ⇒ 段表为空"})
        print("[plan 节点] " + LAST_STATUS)
        return out
    # ③ 势场力: 力过大 ⇒ 否决; 否则沿合力反方向给目标点做有界安全偏置
    goal_plan = list(goal)
    if frc is not None:
        _fm = float(frc.get("mag") or 0.0)
        _veto = abs(float(cfg.get("force_veto_mag", 1.0) or 0.0))
        if _veto > 0 and _fm >= _veto:
            LAST_STATUS = ("势场力过大 (|F|=%.3f ≥ %.3f m/s 当量, 主力 %s) ⇒ 不出段表"
                           % (_fm, _veto, frc.get("main")))
            out.update({"ok": False, "reason": "force_veto", "segments": [], "n": 0,
                        "force_bias_mm": None})
            print("[plan 节点] " + LAST_STATUS)
            return out
        _sc = float(cfg.get("force_bias_mm_per_unit", 50.0) or 0.0)
        _cap = abs(float(cfg.get("force_bias_max_mm", 20.0) or 0.0))
        _vec = frc.get("vec") or [0.0, 0.0, 0.0]
        _bias = [-float(_vec[i]) * _sc for i in range(3)]
        _bn = (_bias[0] ** 2 + _bias[1] ** 2 + _bias[2] ** 2) ** 0.5
        if _bn > _cap > 0:
            _bias = [b * _cap / _bn for b in _bias]
            _bn = _cap
        goal_plan = [goal_plan[i] + _bias[i] for i in range(3)]
        out["force_bias_mm"] = {
            "bias": [round(b, 3) for b in _bias], "norm_mm": round(_bn, 3),
            "scale_mm_per_unit": _sc, "cap_mm": _cap,
            "goal_raw": [round(v, 2) for v in goal],
            "goal_biased": [round(v, 2) for v in goal_plan],
            "why": "沿势场合力反方向退让 (避高势区) · 有界", "src": "in3(势场力)"}
    # ③' 真出段表 —— 后端选择 (老倪 2026-11-02「那就用, 真接上」):
    #   ZMAX_PLAN_BACKEND=moveit|rule|auto(默认) · moveit 只在"容器里最新一轮规划新鲜 + 成功 + 绕行合理"时接管,
    #   否则回退 rule (确定性抬-移-落), 绝不拿旧规划/远路冒充。
    _gq, _gq_src = _goal_quat(tgt)          # 🧭 段表态姿: 显式 > 示教 > 起点保持
    segs = _segments(start, goal_plan, lim, quat=_gq, quat_src=_gq_src)
    _backend = "rule"
    _mv = None
    try:
        from . import moveit_backend as _mb
        _mv = _mb.snapshot()
    except Exception as _e:                                              # noqa: BLE001
        _mv = {"ok": False, "why": "moveit_backend 导入/读取失败 (%s)" % type(_e).__name__}
    _want = (os.environ.get("ZMAX_PLAN_BACKEND") or "auto").strip().lower()
    if _want == "rule":
        _mv = dict(_mv or {}, ok=False, why="ZMAX_PLAN_BACKEND=rule ⇒ 强制规则后端")
    if _mv and _mv.get("ok") and _mv.get("segs") and _want in ("auto", "moveit"):
        segs = _mv["segs"]
        # MoveIt 只给关节轨迹位置: 姿态按同一口径补齐, 缺哪段补哪段 (不覆盖已带的)
        for _sg in segs:
            if not _sg.get("quat"):
                _sg["quat"] = ([round(v, 6) for v in _gq] if _gq else None)
                _sg["quat_src"] = _gq_src
        _backend = "moveit"
    out["moveit"] = {
        "backend": _backend,
        "ok": bool(_mv and _mv.get("ok")), "why": (None if _mv is None else _mv.get("why")),
        "age_s": (None if _mv is None else _mv.get("age_s")),
        "n_points": (None if _mv is None else _mv.get("n_points")),
        "plan_time_s": (None if _mv is None else _mv.get("plan_time_s")),
        "end_err_mm": (None if _mv is None else _mv.get("end_err_mm")),
        "fk_start_diff_mm": (None if _mv is None else _mv.get("fk_start_diff_mm")),
        "total_mm": (None if _mv is None else _mv.get("total_mm")),
        "src": "zmax_data/runtime/moveit_plan/live_plan_latest.json", "probe": _moveit_probe(),
    }
    out.update({"ok": True, "backend": _backend, "goal": [round(v, 2) for v in goal_plan],
                "goal_quat": ([round(v, 6) for v in _gq] if _gq else None), "quat_src": _gq_src,
                "segments": segs, "n": len(segs),
                "total_mm": round(sum(s["len_mm"] for s in segs), 1),
                "note": ("MoveIt 规划 (RRTConnect · IK/FK · 带时间参数) · 只规划, 不动真机" if _backend == "moveit"
                         else "确定性分段(抬升→横移→下落) · 只规划, 不动真机")})
    # 🥽 2026-11-01 老倪「要真接入 AR 场景」: 段表直接进 AR 链分区 (页面/接口读它)
    try:
        from lerobot.engineering.exec import ar_bridge as _arb
        _cur, _si, _u, _pid, _nseg, _el = _plan_tick(segs, goal_plan, time.time())
        # 对外报的段表也跟推进器同一份 (否则消费者看到的 n 每拍在跳)
        if _PLAN["segs"]:
            out["segments"] = _PLAN["segs"]
            out["n"] = len(_PLAN["segs"])
            out["total_mm"] = round(sum(s.get("len_mm") or 0 for s in _PLAN["segs"]), 1)
        out["plan_id"] = _pid
        out["seg_i"] = _si
        out["u"] = round(_u, 4)
        if not os.environ.get("ZMAX_PLAN_NOWRITE"):
            _arb.update("plan", {
                "kind": "plan", "n": _nseg, "plan_id": _pid,
                "seg_i": _si, "seg_kind": (_cur or {}).get("kind"),
                "a": (_cur or {}).get("a"), "b": (_cur or {}).get("b"),
                "u": round(_u, 4), "elapsed_s": _el,
                "label": "段 %s/%s %s" % (_si, _nseg, (_cur or {}).get("kind")),
                "total_mm": out.get("total_mm"), "pose_src": pose_src,
                "quat": (_cur or {}).get("quat"), "quat_src": (_cur or {}).get("quat_src") or _gq_src,
            }, src="n_moveit")
    except Exception:                                                    # noqa: BLE001
        pass
    LAST_STATUS = ("段表 %d 段 / %.0fmm · 起点年龄 %.2fs · 单步≤%.0fmm 向下≤%.0fmm"
                   % (len(segs), out["total_mm"], (age or 0.0), lim["step"], lim["down"]))
    out["status"] = LAST_STATUS
    print("[plan 节点] " + LAST_STATUS)
    return out


def status():
    return LAST_STATUS
