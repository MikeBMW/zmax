#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
moveit_plan_req.py — 给容器里的 MoveIt plan-only 喂「真机当前状态 + 目标」请求 (宿主机侧, 只读)
────────────────────────────────────────────────────────────────────────────
老倪 2026-09-29: 「起 plan-only 的 move_group 容器，把 /plan_kinematic_path 返回的关节轨迹
                 也镜像成 DDS 一条（ss_plan），能在独立窗口里逐帧对。」

链路:
  真机只读 tap  ~/zmax/zmax_data/ss_live/state_*.jsonl  (jpos 6 关节 + tcp, 50Hz 真值)
        │  本脚本 (每 --interval 秒取最新一行)
        ▼
  ~/zmax/zmax_data/runtime/moveit_plan/plan_req.json   → 容器内 moveit_plan_live.py 逐轮规划
        ▼
  ~/zmax/zmax_data/runtime/moveit_plan/live_plan.jsonl → zmax-dds-ss 守护 → DDS topic zmax/ss_plan

安全: 只读真机 tap, 不连机械臂、不下发; 目标点来自示教点文件(data/skills/l2_atomic/taught_points.json)。

用法:
  python3 tools/moveit_plan_req.py --to slot7 --once          # 写一次请求
  python3 tools/moveit_plan_req.py --to slot7 --watch         # 常驻, 每秒刷新真机状态
  python3 tools/moveit_plan_req.py --goal-xyz 0.647 0.206 0.108 --goal-quat 0.738 0.020 0.674 0.0 --once
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time

HOME = os.path.expanduser("~")
SS_REMOTE = os.environ.get("SS_REMOTE_DIR", os.path.expanduser("~/zmax/zmax_data/ss_live"))
PLAN_DIR = os.environ.get("SS_PLAN_DIR", os.path.expanduser("~/zmax/zmax_data/runtime/moveit_plan"))
REQ = os.path.join(PLAN_DIR, "plan_req.json")
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
TAUGHT = os.path.join(_REPO, "data", "skills", "l2_atomic", "taught_points.json")


# ── 🎯 2026-10-16 技能执行口: MoveIt 的目标改由原子技能给 (老倪: 「MoveIt 怎么选实际的原子任务动作」)
#   以前: 目标只能人工给 (--to 示教点 / --goal-xyz)。现在: 技能选段 + 技能口算目标位姿
#   (点位 + 本段偏置, 与仿真/真机共用同一份规则), MoveIt 只负责把目标规划成轨迹。
#   目标来源三档: ①--goal-xyz 人工直接给 ②--stage/--auto 技能口给 ③--to 示教点 (原行为)
SKILLS_PY = os.path.join(_REPO, "src", "lerobot", "policies", "left_right", "state_space",
                         "skills", "atomic_skills.py")
GATE_F = os.path.join(SS_REMOTE, "skill_gate.json")
GATE_MAX_AGE = float(os.environ.get("SS_GATE_MAX_AGE", "10.0"))   # 段来源的时效 (秒), 超时报帧龄


def _atomic():
    """按路径加载技能库 (与引擎同一份文件; 失败返回 None, 调用方如实退回原行为)"""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("zmax_atomic_skills", SKILLS_PY)
        m = importlib.util.module_from_spec(spec)
        sys.modules["zmax_atomic_skills"] = m
        spec.loader.exec_module(m)
        return m
    except Exception as e:                                          # noqa: BLE001
        print("⚠ 技能库加载失败 (%s) → 只能用 --to/--goal-xyz" % e)
        return None


def _stage_of(a):
    """当前原子技能段: --stage 直接给; --auto 读引擎发布的 skill_gate.json (带帧龄)"""
    if a.stage:
        return str(a.stage), "cli(--stage)"
    if not a.auto:
        return None, ""
    if not os.path.exists(GATE_F):
        print("… 未找到 %s (引擎还没发布过闸/段真值) → 无法 --auto" % GATE_F)
        return None, ""
    try:
        d = json.load(open(GATE_F, encoding="utf-8"))
    except Exception as e:                                          # noqa: BLE001
        print("… %s 读不了: %s" % (GATE_F, e))
        return None, ""
    age = time.time() - float(d.get("ts") or 0)
    if age > GATE_MAX_AGE:
        print("… 段真值陈旧: %s 帧龄 %.1fs (>%.0fs) → 不猜, 退回人工 --stage/--to" % (
            d.get("stage"), age, GATE_MAX_AGE))
        return None, ""
    return str(d.get("stage") or ""), "engine(skill_gate.json, 帧龄%.1fs)" % age


def newest(pat):
    fs = glob.glob(pat)
    return max(fs, key=os.path.getmtime) if fs else None


def _sdk_frame():
    """SDK 50Hz 采样器(rokae_tcp_sampler)的当前真值: joint[:6] 真关节 + tcp + quat。

    🔴 2026-10-09 为什么必须走这条: ROS tap(state_*.jsonl) 依赖 Orin 的 ROS 发布者,
    实测 /robot/tcp_pose 的 Publisher count=0(没人发) ⇒ tap 里 tcp/jpos 恒为空 ⇒
    规划器拿假起点规划(FK起点差 399.6mm, 计划不可用)。SDK 采样器一直在采, joint 就是真 6 关节。
    """
    p = "/home/ubuntu/zmax/zmax_data/rokae_sdk/tcp_out/latest.json"
    try:
        if time.time() - os.path.getmtime(p) > 2.0:
            return None
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        jp = [float(x) for x in (d.get("joint") or [])][:6]
        tcp = [float(d[k]) for k in ("x", "y", "z")]
        if len(jp) != 6 or len(tcp) != 3:
            return None
        return {"jpos": jp, "tcp": tcp,
                "tcp_quat": [float(d[k]) for k in ("qx", "qy", "qz", "qw")],
                "t": d.get("t"), "src_file": p + " (SDK 50Hz 直采)"}
    except Exception:                                                        # noqa: BLE001
        return None


def real_state():
    """真机最新一帧: jpos(6) / tcp(3) / tcp_quat(4) / t

    优先 SDK 直采(活的); 拿不到才退回只读 tap(依赖 ROS, 常空)。
    """
    f = _sdk_frame()
    if f:
        return f
    p = newest(os.path.join(SS_REMOTE, "state_*.jsonl"))
    if not p:
        return None
    try:
        with open(p, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 200_000))
            lines = f.read().decode("utf-8", "replace").splitlines()
        for ln in reversed(lines):
            ln = ln.strip()
            if not ln:
                continue
            try:
                d = json.loads(ln)
            except Exception:
                continue
            jp = d.get("jpos")
            if isinstance(jp, list) and len(jp) == 6:
                return {"jpos": [float(x) for x in jp],
                        "tcp": [float(x) for x in (d.get("tcp") or [])][:3],
                        "tcp_quat": [float(x) for x in (d.get("tcp_quat") or [])][:4],
                        "t": d.get("t"), "src_file": p}
    except Exception as e:                                                   # noqa: BLE001
        print("读真机 tap 失败: %s" % str(e)[:120])
    return None


def taught(name):
    try:
        d = json.load(open(TAUGHT, encoding="utf-8"))
        pt = (d.get("points") or {}).get(name)
        if not pt:
            return None
        q = [float(x) for x in pt["quat"]]
        if len(q) == 3:     # ⚠️ 示教点里 quat 存了 3 个数 = 第 4 位 w≈0 被省略 (实测 slot7 |q|≈0.9997)
            q = q + [0.0]   # ⇒ 补 w=0.0 (与 moveit_plan_only 旧跑法一致)
        return [float(x) for x in pt["pos"]], q
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", default="slot7", help="示教点名(默认 slot7)")
    ap.add_argument("--goal-xyz", nargs=3, type=float, default=None, help="直接给目标位置(m)")
    ap.add_argument("--goal-quat", nargs=4, type=float, default=None, help="目标姿态 xyzw")
    ap.add_argument("--stage", default=None,
                    help="原子技能段 (接近/对位/下降/抓取/抬起/转移/插入/完成): 目标由技能口给")
    ap.add_argument("--auto", action="store_true",
                    help="当前段从引擎发布的 ss_live/skill_gate.json 取 (超时报帧龄, 不猜)")
    ap.add_argument("--state-from", default=None,
                    help="无真机时用历史状态/上一次请求文件里的 jpos 作起点 (会打印帧龄, 不假装实时)")
    ap.add_argument("--interval", type=float, default=1.0)
    ap.add_argument("--watch", action="store_true", help="常驻, 每 interval 秒刷新真机状态")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()

    st_name, st_src = _stage_of(a)
    def _resolve(st_name, st_src):
        """🎯 2026-10-18 老倪: 「引擎跑起来发布 skill_gate.json → MoveIt 目标自动切技能口」
        --auto 每拍重解一次段; 解不出返回 None (保持上一拍目标, 不猜)."""
        if a.goal_xyz and a.goal_quat:
            goal, gq = [float(x) for x in a.goal_xyz], [float(x) for x in a.goal_quat]
            gname = "cli"
        elif st_name:
            # 🎯 技能口: 目标位姿 = 示教点(--to) + 本段偏置 (与仿真/真机同一份规则)
            _sk = _atomic()
            _cls = getattr(_sk, "skill_for", lambda *_: None)(st_name) if _sk is not None else None
            if _cls is None or not getattr(_cls, "TARGET", None):
                print("✗ 段「%s」没有技能类或没声明目标规则 (拔出/AOI 等 5 段尚未接) → 用 --to/--goal-xyz" % st_name)
                return None
            _t = taught(a.to)
            if not _t:
                print("✗ 示教点不存在: %s (见 %s)" % (a.to, TAUGHT))
                return None
            _pts = {a.to: {"pos": [float(v) for v in _t[0]], "quat": [float(v) for v in _t[1]]}}
            _tg = _cls.next_target(points=_pts, spec={"point": a.to})
            if _tg is None:
                print("✗ 技能口解不出目标 (段 %s @ %s)" % (st_name, a.to))
                return None
            goal, gq = [float(v) for v in _tg["xyz"]], [float(v) for v in (_tg.get("quat") or _t[1])]
            gname = "skill:%s@%s" % (getattr(_cls, "code", "?"), a.to)
            print("🎯 段=%s (来源 %s) · 技能口参考=%s · 偏置=%s mm" % (
                st_name, st_src, _tg.get("src"),
                [round(float(v) * 1000, 1) for v in _tg.get("off", [0, 0, 0])]))
        else:
            t = taught(a.to)
            if not t:
                print("✗ 示教点不存在: %s (见 %s)" % (a.to, TAUGHT))
                return None
            goal, gq = t
            gname = a.to
        return goal, gq, gname

    _r = _resolve(st_name, st_src)
    if _r is None:
        return 2
    goal, gq, gname = _r
    os.makedirs(PLAN_DIR, exist_ok=True)
    print("🎯 目标 = 示教点 %s · xyz=%s quat=%s" % (gname, [round(v, 5) for v in goal],
                                                    [round(v, 5) for v in gq]))
    _hist = None
    if a.state_from:
        try:
            _d = json.load(open(a.state_from, encoding="utf-8"))
            _age = time.time() - float(_d.get("real_t") or _d.get("ts") or 0)
            _hist = {"jpos": _d["jpos"], "tcp": _d.get("tcp"), "tcp_quat": _d.get("tcp_quat"),
                     "t": float(_d.get("real_t") or _d.get("ts") or 0)}
            print("⚠ 起点用历史状态 %s · 帧龄 %.1fh (不是实时真机, 规划仍真实)" % (
                os.path.basename(a.state_from), _age / 3600.0))
        except Exception as e:                                       # noqa: BLE001
            print("✗ --state-from 读不了: %s" % e)
            return 2
    n = 0
    while True:
        if a.auto:                                    # 🎯 段跟着引擎走 (原来只在启动时读一次)
            _s2, _src2 = _stage_of(a)
            if _s2 and _s2 != st_name:
                _r2 = _resolve(_s2, _src2)
                if _r2 is not None:
                    st_name, st_src = _s2, _src2
                    goal, gq, gname = _r2
                    print("🎯 段切换 → %s (来源 %s) · 目标 = %s" % (st_name, st_src, gname))
        st = _hist or real_state()
        if st:
            rec = {"ts": time.time(), "goal_name": gname, "goal_xyz": goal, "goal_quat": gq,
                   "goal_src": ("skill" if str(gname).startswith("skill:") else
                                ("cli" if gname == "cli" else "taught")),
                   "goal_stage": st_name or "",
                   "jpos": st["jpos"], "tcp": st["tcp"], "tcp_quat": st["tcp_quat"],
                   "real_t": st.get("t"), "src": ("replay(history: %s)" % os.path.basename(a.state_from)) if _hist
        else "real(tap readonly)"}
            tmp = REQ + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(rec, f, ensure_ascii=False)
            os.replace(tmp, REQ)
            n += 1
            if n == 1 or n % 10 == 0:
                print("· 已写 %s (#%d) 真机关节=%s tcp=%s" % (REQ, n,
                                                            [round(v, 3) for v in st["jpos"]],
                                                            [round(v, 3) for v in st["tcp"]]))
        else:
            print("… 真机 tap 无数据 (等 ~/zmax/zmax_data/ss_live/state_*.jsonl)")
        if a.once:
            return 0 if st else 3
        time.sleep(max(0.2, a.interval))


if __name__ == "__main__":
    sys.exit(main())
