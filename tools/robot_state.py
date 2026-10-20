#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""robot_state.py — 机器人状态机 (单一真源 → 信号分析 / AR 页面 / 任何要"现在机器人什么状态"的地方)

老倪 2026-10-20: 「AR 场景, 是需要接上机器人的, 你把机器人的状态机接上, 可以直接看到**是否在插拔**」

真源 (全部只读, 一个都不新造):
  · 控制器三查 + 位姿  `zmax_data/rokae_sdk/tcp_out/state.json` / `latest.json`
      (tools/rokae/tcp_direct_sampler.py 直连珞石 xCoreSDK 落的; 帧龄 >CONN_MAX_S 判"未连接")
  · 当前阶段           `zmax_data/ss_live/skill_dispatch.json` (stage, chunk_pipeline 每拍写)
                        → 备路 `skill_gate.json` (引擎内联闸的 stage)
  · 执行器受理的技能    `zmax_data/ss_live/exec_state.json` (l2_daemon: skill/phase/pos)
  · 任务               `zmax_data/ss_live/engine_latest.json` (task_id / task_name)

状态机 (code 与含义绑定, 改含义必须同步改这里和 ar_aoi_signals 的 unit 说明):
  0 未连接      控制器/位姿文件都陈旧 (网卡不在位、采样器没跑、控制器没上电)
  1 急停/报警    控制器报急停 或 有未恢复报警
  2 未使能      伺服没开 (power=off: 控制器连着、位姿能来, 但电机没出力)
  3 手动         mode = manual (含拖动示教)
  4 自动待机     automatic 且 没在动
  5 自动运行     automatic 且 在动 (TCP 速度 > MOVE_EPS_MM_S 或控制器 op != idle)

「是否在插拔」= 当前阶段 ∈ {插入, 拔出, 插拔} 或 执行技能名含 insert/pull/插入/拔出。
**未知就说未知**: 未连接时 inserting=None, 不冒充"非插拔"(那会让人以为机器人好好站着)。

用法:
  gui-venv311/bin/python tools/robot_state.py            # 一行 JSON (给页面/总线)
  gui-venv311/bin/python tools/robot_state.py --text     # 一行人话
  gui-venv311/bin/python tools/robot_state.py --watch -i 1
"""
from __future__ import annotations

import argparse
import json
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "zmax_data", "rokae_sdk", "tcp_out", "state.json")
TCP = os.path.join(ROOT, "zmax_data", "rokae_sdk", "tcp_out", "latest.json")
DISP = os.path.join(ROOT, "zmax_data", "ss_live", "skill_dispatch.json")
GATE = os.path.join(ROOT, "zmax_data", "ss_live", "skill_gate.json")
EXEC = os.path.join(ROOT, "zmax_data", "ss_live", "exec_state.json")
ENG = os.path.join(ROOT, "zmax_data", "ss_live", "engine_latest.json")
CACHE = os.path.join(ROOT, "zmax_data", "ss_live", "_robot_speed_cache.json")
# 当前三态 (power/mode/op) 由 ft_direct_sampler 每帧用 SDK enum 直读落盘 —— **当前态**;
# state.json 里的 last_estop/n_err_recent 只是**历史报警表**, 不能拿来判"现在急停"(2026-10-20 实测栽过)。
FT = os.path.join(ROOT, "zmax_data", "rokae_sdk", "ft_out", "latest.json")

CONN_MAX_S = 5.0        # 控制器三查/位姿超过这么久没更新 = 没连上
STAGE_MAX_S = 3.0       # 阶段文件超过这么久 = 阶段未知(不拿旧阶段冒充当前)
MOVE_EPS_MM_S = 1.0     # TCP 速度超过它就判"在动"

STAGES = ("接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成")
INSERT_STAGES = ("插入", "拔出", "插拔")
INSERT_SKILL_HINTS = ("insert", "pull", "插入", "拔出", "插拔")

CODE_TEXT = {0: "未连接", 1: "急停/伺服报警", 2: "未使能(伺服off)", 3: "手动", 4: "自动待机", 5: "自动运行"}
OP_TXT = {"idle": "停", "moving": "运动", "drag": "拖动", "jog": "点动", "jogging": "点动中",
          "rtControlling": "实时控制", "rlProgram": "RL程序", "demo": "演示",
          "frictionIdentify": "摩擦辨识", "dynamicIdentify": "动力学辨识", "loadIdentify": "负载辨识"}
MOVE_OPS = ("moving", "jog", "jogging", "rtControlling", "rlProgram", "demo", "drag")  # drag=人在拖, 也确算在动
ESTOP_POWER = ("estop", "gstop")


def _j(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:                                                                  # noqa: BLE001
        return {}


def _age_of(p, ts=None):
    """文件写龄: 优先用文件里的 ts (与采样时刻同源), 没有就用 mtime。"""
    if ts is not None:
        try:
            return max(0.0, time.time() - float(ts))
        except Exception:                                                              # noqa: BLE001
            pass
    try:
        return max(0.0, time.time() - os.path.getmtime(p))
    except Exception:                                                                  # noqa: BLE001
        return None


def _speed_mm_s(x, y, z, ts):
    """TCP 真值相邻两帧差分 (mm/s)。缓存上一帧, dt 用真实 Δt; 断流不硬算。"""
    prev = _j(CACHE) if os.path.exists(CACHE) else {}
    v = None
    try:
        if prev and float(prev.get("ts") or 0) > 0:
            dt = float(ts) - float(prev["ts"])
            if 0.002 <= dt <= 2.0:
                dx = x - float(prev["x"])
                dy = y - float(prev["y"])
                dz = z - float(prev["z"])
                v = (dx * dx + dy * dy + dz * dz) ** 0.5 / dt * 1000.0
    except Exception:                                                                  # noqa: BLE001
        v = None
    try:
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump({"ts": float(ts), "x": x, "y": y, "z": z}, f)
    except Exception:                                                                  # noqa: BLE001
        pass
    return v


def _current_stage():
    """当前阶段 = 派发器 stage (最新) → 备路 闸 stage; 都陈旧 ⇒ ("", None, "")。"""
    for p in (DISP, GATE):
        d = _j(p)
        if not d:
            continue
        age = _age_of(p, d.get("ts"))
        if age is not None and age <= STAGE_MAX_S:
            st = str(d.get("stage") or "")
            if st:
                return st, age, os.path.relpath(p, ROOT)
    return "", None, ""


def snapshot():
    """→ dict (JSON 友好)。所有字段都有出处; 拿不到就 None / 空字符串, 不编。"""
    now = time.time()
    st = _j(STATE)
    tcp = _j(TCP)
    eng = _j(ENG)
    ex = _j(EXEC)

    a_state = _age_of(STATE, st.get("ts"))
    a_tcp = _age_of(TCP, tcp.get("ts"))
    connected = bool((a_state is not None and a_state <= CONN_MAX_S) or
                     (a_tcp is not None and a_tcp <= CONN_MAX_S))

    # —— 当前三态: 优先 ft_out (ft_direct_sampler 每帧 SDK enum 直读), 否则退回 state.json ——
    ft = _j(FT)
    a_ft = _age_of(FT, ft.get("ts"))
    _ft_ok = bool(a_ft is not None and a_ft <= 2.0 and ft.get("power"))
    src_now = "ft_direct_sampler/SDK enum" if _ft_ok else "state.json"
    power = str((ft.get("power") if _ft_ok else st.get("power")) or "").lower() or None
    mode = str((ft.get("mode") if _ft_ok else st.get("mode")) or "").lower() or None
    op = str((ft.get("op") if _ft_ok else st.get("op")) or "").lower() or None
    # 急停 = **当前**伺服态 (PowerState.estop/gstop); 历史 last_estop 只当记录, 不再据此判故障
    estop = power in ESTOP_POWER
    alarm = st.get("last_alarm") or {}
    alarm_n = 0
    try:
        alarm_n = int(st.get("n_err_recent") or 0)
    except Exception:                                                                  # noqa: BLE001
        alarm_n = 0

    # 在动? 优先 TCP 差分的**实测速度**; 差分不可用再退回控制器 op
    speed = None
    try:
        if tcp.get("x") is not None and tcp.get("ts"):
            speed = _speed_mm_s(float(tcp["x"]), float(tcp["y"]), float(tcp["z"]), float(tcp["ts"]))
    except Exception:                                                                  # noqa: BLE001
        speed = None
    if op in MOVE_OPS:
        moving = True
    elif speed is not None and a_tcp is not None and a_tcp <= CONN_MAX_S:
        moving = speed > MOVE_EPS_MM_S
    else:
        moving = (op not in (None, "idle", "idling", "stop")) if connected else False

    stage, a_stage, stage_src = _current_stage()
    if not stage:
        # 派发器没在跑 ⇒ 看执行器受理的技能 (exec_state 里的 skill 常是 L2.xxx)
        sk = str(ex.get("skill") or "")
        if sk and (_age_of(EXEC, ex.get("t") or ex.get("t_pub")) or 1e9) <= 30.0:
            stage = ""
            exec_skill = sk
        else:
            exec_skill = ""
    else:
        exec_skill = str(ex.get("skill") or "")

    _ins_txt = (stage + " " + exec_skill).lower()
    if stage:
        # 阶段是**任务流水线自己的真值**(派发器/引擎闸每拍写, 3s 内算新鲜) ⇒ 在插拔与否据此定,
        # 与"控制器连没连上"是两件事: 连不上时也要能看出流水线正处在哪一步。
        inserting = bool(stage in INSERT_STAGES or any(h in _ins_txt for h in INSERT_SKILL_HINTS))
    elif connected:
        inserting = False
    else:
        inserting = None           # 阶段都没有 ⇒ 不知道, 不冒充"非插拔"

    code = 0
    if connected:
        if estop:
            code = 1
        elif power != "on":
            code = 2
        elif mode and mode not in ("automatic", "auto"):
            code = 3
        elif moving:
            code = 5
        else:
            code = 4

    stage_idx = STAGES.index(stage) if stage in STAGES else -1
    txt = _text_of(code, mode, stage, inserting, speed, eng, a_state, a_tcp, op=op)
    return {"ts": round(now, 3),
            "code": code, "state": CODE_TEXT.get(code, "?"),
            "connected": connected, "power": power, "mode": mode, "op": op,
            "estop": estop, "alarm_n": alarm_n, "alarm_id": alarm.get("id"),
            "alarm_hist": {"n": alarm_n, "last": alarm.get("ts"), "last_txt": (alarm.get("content") or "")[:60]},
            "state_src": src_now, "op_txt": OP_TXT.get(op or "", op or ""),
            "moving": bool(moving), "speed_mm_s": (round(speed, 3) if speed is not None else None),
            "stage": stage, "stage_idx": stage_idx, "stage_age_s": (round(a_stage, 3) if a_stage else None),
            "stage_src": stage_src, "exec_skill": exec_skill,
            "inserting": inserting,
            "inserting_txt": ("插拔中" if inserting else ("非插拔" if inserting is False else "未知(未连接)")),
            "task_id": str(eng.get("task_id") or ""), "task_name": str(eng.get("task_name") or ""),
            "state_age_s": (round(a_state, 2) if a_state is not None else None),
            "tcp_age_s": (round(a_tcp, 2) if a_tcp is not None else None),
            "text": txt,
            "src": {"state": os.path.relpath(STATE, ROOT), "tcp": os.path.relpath(TCP, ROOT),
                    "stage": stage_src, "exec": os.path.relpath(EXEC, ROOT),
                    "engine": os.path.relpath(ENG, ROOT)}}


def _text_of(code, mode, stage, inserting, speed, eng, a_state, a_tcp, op=""):
    """一行人话 (给页面/日志): 状态 · 模式 · 阶段 · 速度 · 是否插拔 · 任务。"""
    _mode = {"automatic": "自动", "auto": "自动", "manual": "手动"}.get(mode or "", mode or "")
    _ins = {True: "插拔中", False: "非插拔", None: "插拔未知"}[inserting]
    _code_txt = CODE_TEXT.get(code, "?")
    parts = ["🤖 " + _code_txt]
    if _mode and _mode != _code_txt:       # 状态码已经是"手动"时不再重复
        parts.append(_mode)
    _op = {"drag": "拖动示教"}.get(op or "", OP_TXT.get(op or "", op or ""))
    if _op and _op != _mode:            # 手动 + 拖动 时不重复写"手动"
        parts.append(_op)
    parts.append(("阶段 " + stage) if stage else "阶段未知")
    if speed is not None:
        parts.append("%.1f mm/s" % speed)
    parts.append(_ins)
    if eng.get("task_id"):
        parts.append("任务 " + str(eng["task_id"]))
    if code == 0:
        parts.append("状态帧龄 %s" % ("—" if a_state is None else "%.1fs" % a_state))
    return " · ".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", action="store_true", help="只打一行人话")
    ap.add_argument("--watch", action="store_true", help="常驻打印")
    ap.add_argument("-i", "--interval", type=float, default=1.0)
    a = ap.parse_args()
    while True:
        s = snapshot()
        print(s.get("text") if a.text else json.dumps(s, ensure_ascii=False), flush=True)
        if not a.watch:
            return 0
        time.sleep(max(0.2, a.interval))


if __name__ == "__main__":
    raise SystemExit(main())
