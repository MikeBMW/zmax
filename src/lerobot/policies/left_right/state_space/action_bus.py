"""🎯 action 总线 — 状态空间工程的最终输出(唯一一份)

老倪 2026-11-14:
    「把这个(位置/欧拉/四元数/关节) 作为 action, 最终输出, 然后后端使用这个值操作机器人。
      我要监控这个 action 变量。这里(现在)是 215 个真实轨迹 —— action 之前, 可以直接回放 215 个点。
      你加一个判断, 这么改造。action 理论上是状态空间工程的输出, 现在是用 215 真点进行调试。」

口径(不许改字段名, 页面/调试器/后端都按这个读):
    action = {
      src       "traj215" = 直接用 215 点真值(调试/回退) | "ss" = 状态空间算出来的
      x y z     mm      (base_link, 与机器人读数同格式)
      a b c     deg     (XYZ 欧拉, 口径 tools/pt_pose.py)
      qx qy qz qw       同一姿态的四元数
      j1..j6    deg     (关节角; src=ss 且没有 IK 时 = 当前实测关节, 并标 joints_src)
      i         215 点序号(仅 src=traj215)
      why       人话原因(为什么是这个 src)
      ts        写入时刻
    }

铁律:
  ① 每拍只写一份(原子替换), 后端/页面只读这一份 —— 不再各算各的
  ② src 只可能二选一, 缺真值/校验不过 ⇒ 一律 traj215(绝不输出算不出的位姿)
  ③ 本模块不驱动任何运动: 写文件 + 返回 dict, 真发仍走 8797 轨迹 / daemon move_pose
"""
from __future__ import annotations

import json
import math
import os
import time

_REPO = None


def _repo() -> str:
    global _REPO
    if _REPO:
        return _REPO
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        if (os.path.isdir(os.path.join(d, "zmax_data"))
                and os.path.isdir(os.path.join(d, "src", "lerobot"))):
            _REPO = d
            return d
        d = os.path.dirname(d)
    _REPO = "/home/ubuntu/zmax"
    return _REPO


OUT = os.path.join(_repo(), "zmax_data", "ss_live", "action.json")
TRAJ_JSON = os.path.join(_repo(), "tools", "web", "real_traj_joints.json")
TRAJ_STATE = os.path.join(_repo(), "zmax_data", "rokae_sdk", "traj_step_state.json")
LATEST = os.path.join(_repo(), "zmax_data", "rokae_sdk", "tcp_out", "latest.json")

KEYS = ("src", "x", "y", "z", "a", "b", "c", "qx", "qy", "qz", "qw",
        "j1", "j2", "j3", "j4", "j5", "j6", "i", "why", "ts",
        "grip_mm", "grip_act", "grip_state", "grip_src", "grip_meas_mm", "grip_meas_age_s")

# 夹爪: 0mm=合(夹住) 70mm=开(松开) —— 与 8797 的 _grip_send 同一口径
GRIP_PLAN = os.path.join(_repo(), "tools", "web", "real_traj_grip.json")
GRIP_LOG = os.path.join(_repo(), "zmax_data", "rokae_sdk", "grip_events.jsonl")
GRIP_OPEN_MM = float(os.environ.get("ZMAX_GRIP_OPEN_MM", "70"))


def _abc_deg(quat):
    try:
        import importlib.util as _ilu
        p = os.path.join(_repo(), "tools", "pt_pose.py")
        spec = _ilu.spec_from_file_location("_pt_pose_ab", p)
        m = _ilu.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m.abc_deg(quat)
    except Exception:                                          # noqa: BLE001
        return None


def _frames():
    try:
        return json.load(open(TRAJ_JSON, encoding="utf-8")).get("frames") or []
    except Exception:                                          # noqa: BLE001
        return []


def cursor215():
    """8797 当前走到第几点(0 基)。取不到 ⇒ 0。"""
    try:
        return int(json.load(open(TRAJ_STATE, encoding="utf-8")).get("cursor") or 0)
    except Exception:                                          # noqa: BLE001
        return 0


def from_traj215(cursor=None, why="215 点真值回放"):
    """src=traj215: 直接取 215 点当前点的位姿+关节。取不到 ⇒ None。"""
    fr = _frames()
    if not fr:
        return None
    i = cursor215() if cursor is None else int(cursor)
    i = max(0, min(i, len(fr) - 1))
    f = fr[i]
    p = f.get("p") or []
    q = f.get("q") or [0, 0, 0, 0]
    j = f.get("j") or []
    if len(p) != 3 or len(j) != 6:
        return None
    abc = _abc_deg(q) or [None, None, None]
    act = {"src": "traj215", "x": round(p[0] * 1000, 2), "y": round(p[1] * 1000, 2),
           "z": round(p[2] * 1000, 2), "a": abc[0], "b": abc[1], "c": abc[2],
           "qx": round(float(q[0]), 6), "qy": round(float(q[1]), 6),
           "qz": round(float(q[2]), 6), "qw": round(float(q[3]), 6),
           "i": i, "why": why, "ts": time.time(), "joints_src": "215点轨迹"}
    for k in range(6):
        act["j%d" % (k + 1)] = round(math.degrees(float(j[k])), 4)
    return _with_grip(act, grip_at(i, len(fr)))


def from_ss(u, dt=0.1, pose_now=None, joints_now=None, why="状态空间输出"):
    """src=ss: 当前位置 + u*dt 得目标位姿; 关节暂无 IK ⇒ 用实测关节并标注。"""
    if pose_now is None:
        pose_now = read_pose()
    if pose_now is None:
        return None
    v = [float(x) for x in (u if hasattr(u, "__len__") else [u])][:3]
    if len(v) != 3 or any(not math.isfinite(x) for x in v):
        return None
    act = {"src": "ss",
           "x": round(pose_now["x"] + v[0] * 1000.0 * dt, 2),
           "y": round(pose_now["y"] + v[1] * 1000.0 * dt, 2),
           "z": round(pose_now["z"] + v[2] * 1000.0 * dt, 2),
           "a": pose_now.get("a"), "b": pose_now.get("b"), "c": pose_now.get("c"),
           "qx": pose_now.get("qx"), "qy": pose_now.get("qy"),
           "qz": pose_now.get("qz"), "qw": pose_now.get("qw"),
           "i": cursor215(), "why": why, "ts": time.time(),
           "joints_src": ("实测" if joints_now else "缺")}
    for k in range(6):
        act["j%d" % (k + 1)] = (round(math.degrees(float(joints_now[k])), 4)
                                if joints_now and len(joints_now) > k else None)
    # 状态空间档: 夹爪不由 u 决定(4 维的 u[3] 还没接过来) ⇒ 保持实测状态, 明确标注
    _m, _ = grip_meas()
    _keep = {"grip_mm": _m, "grip_act": "hold",
             "grip_state": (None if _m is None else ("开" if _m > 1.0 else "合")),
             "grip_src": "保持实测(ss 档暂无夹爪通道)"}
    return _with_grip(act, _keep)


def grip_plan():
    """215 点夹爪计划 [(i, act, hold_ms, target_mm)]。读不到 ⇒ []。"""
    try:
        d = json.load(open(GRIP_PLAN, encoding="utf-8"))
        out = []
        for ev in (d.get("grip") or []):
            out.append((int(ev.get("i", 0)), str(ev.get("act") or ""),
                        int(ev.get("hold_ms") or 0),
                        GRIP_OPEN_MM if ev.get("act") == "open" else 0.0))
        return out
    except Exception:                                          # noqa: BLE001
        return []


def grip_at(i, total=None):
    """第 i 点应有的夹爪状态: 起点默认已夹住(0mm), 之后按计划事件推进。"""
    plan = grip_plan()
    n = total or len(_frames()) or 1
    mm, act, src = 0.0, "close", "默认=起点已夹住"
    applied = None
    for (idx, a, hold, tgt) in plan:
        j = idx if idx >= 0 else n + idx
        if i >= j:
            mm, act, applied = tgt, a, (j, a, hold)
    if applied:
        src = "215点夹爪计划 i=%d %s(hold %dms)" % (applied[0], applied[1], applied[2])
    return {"grip_mm": mm, "grip_act": act,
            "grip_state": ("开" if mm > 1.0 else "合"), "grip_src": src}


def grip_meas():
    """夹爪实测位置: 取 grip_events.jsonl 最后一条的 pos_after/pos_before + 帧龄。"""
    try:
        if not os.path.exists(GRIP_LOG):
            return None, None
        last = None
        with open(GRIP_LOG, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    last = line
        if not last:
            return None, None
        ev = json.loads(last)
        pos = ev.get("pos_after")
        if pos is None:
            pos = ev.get("pos_before")
        try:
            age = time.time() - time.mktime(time.strptime(ev.get("t"), "%Y-%m-%d %H:%M:%S"))
        except Exception:                                      # noqa: BLE001
            age = None
        return (None if pos is None else round(float(pos), 2)), age
    except Exception:                                          # noqa: BLE001
        return None, None


def _with_grip(act, grip):
    if grip:
        act.update(grip)
    _mm, _age = grip_meas()
    act["grip_meas_mm"] = _mm
    act["grip_meas_age_s"] = (None if _age is None else round(_age, 1))
    return act


def read_pose():
    """机器人当前位姿(与 action 同格式的位姿部分)。"""
    try:
        if time.time() - os.path.getmtime(LATEST) > 2.0:
            return None
        d = json.load(open(LATEST, encoding="utf-8"))
        x, y, z = float(d["x"]) * 1000, float(d["y"]) * 1000, float(d["z"]) * 1000
        if (x, y, z) == (0.0, 0.0, 0.0):
            return None
        abc = _abc_deg([d.get("qx"), d.get("qy"), d.get("qz"), d.get("qw")]) or [None] * 3
        return {"x": round(x, 2), "y": round(y, 2), "z": round(z, 2),
                "a": abc[0], "b": abc[1], "c": abc[2],
                "qx": round(float(d.get("qx") or 0), 6), "qy": round(float(d.get("qy") or 0), 6),
                "qz": round(float(d.get("qz") or 0), 6), "qw": round(float(d.get("qw") or 0), 6)}
    except Exception:                                          # noqa: BLE001
        return None


def publish(act) -> bool:
    """原子写 action.json(每拍一次, 后端/页面只读这份)。"""
    if not act:
        return False
    try:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        tmp = OUT + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(act, f, ensure_ascii=False)
        os.replace(tmp, OUT)
        return True
    except Exception:                                          # noqa: BLE001
        return False


def read():
    try:
        return json.load(open(OUT, encoding="utf-8"))
    except Exception:                                          # noqa: BLE001
        return None


def from_action(act, deny=""):
    """把执行器返回的 action(位姿口径)摊平成 action.json 的字段表 —— **唯一出口**。

    act: execution.Action(dict) —— src / pose{x,y,z,a,b,c,qx..qw} / joints_deg[6] / joints_src / grip_* / i / why
    deny: 护栏未放行的原因(只写进 why, 不改数值)
    """
    if not act:
        return None
    pose = act.get("pose") or {}
    out = {"src": act.get("src"), "i": act.get("i"),
           "x": pose.get("x"), "y": pose.get("y"), "z": pose.get("z"),
           "a": pose.get("a"), "b": pose.get("b"), "c": pose.get("c"),
           "qx": pose.get("qx"), "qy": pose.get("qy"), "qz": pose.get("qz"), "qw": pose.get("qw"),
           "joints_src": act.get("joints_src"),
           "why": act.get("why"), "ts": act.get("ts") or time.time()}
    _j = act.get("joints_deg") or []
    for _k in range(6):
        _v = _j[_k] if len(_j) > _k else None
        out["j%d" % (_k + 1)] = (None if _v is None else round(float(_v), 4))
    for _k in ("grip_mm", "grip_act", "grip_state", "grip_src",
               "grip_meas_mm", "grip_meas_age_s"):
        if _k in act:
            out[_k] = act.get(_k)
    if deny:
        out["why"] = ("%s · %s" % (out.get("why") or "", deny)).strip(" ·")
    _mm, _age = grip_meas()
    out.setdefault("grip_meas_mm", _mm)
    out.setdefault("grip_meas_age_s", (None if _age is None else round(_age, 1)))
    return out


def decide(src_ss_allowed: bool, u=None, dt=0.1, joints_now=None, why_deny="", pose_now=None):
    """加的那道判断: 允许走状态空间 ⇒ src=ss; 否则(默认) ⇒ 215 点真值。"""
    if src_ss_allowed:
        a = from_ss(u, dt=dt, pose_now=pose_now, joints_now=joints_now,
                    why="状态空间输出(护栏已放行)")
        if a is not None:
            return a
        why_deny = why_deny or "ss 位姿取不到"
    a = from_traj215(why=("215 点回放" + (" · " + why_deny if why_deny else "")))
    return a


def summary(act=None):
    """一行给人看: action x y z a b c + 来源。"""
    a = act or read() or {}
    if not a:
        return "action: (无)"
    return ("action[%s] x=%.2f y=%.2f z=%.2f a=%.2f b=%.2f c=%.2f · %s"
            % (a.get("src"), a.get("x") or 0, a.get("y") or 0, a.get("z") or 0,
               a.get("a") or 0, a.get("b") or 0, a.get("c") or 0, a.get("why")))
