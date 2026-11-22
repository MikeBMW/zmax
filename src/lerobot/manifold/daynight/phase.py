#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""昼夜相位机 —— 状态空间"白天采集 / 夜间沉淀"的唯一状态源。

设计口径(老倪 2026-11-21):
    白天 = 在线推理: 高维观测 → 降维投影到潜空间 → 用旧模型应对噪声世界 → 落"噪声日志"
    夜间 = 离线对齐: 切断外部输入 → 用日志对齐高维真实先验 → 剔除噪声/提取泛化/更新权重

本模块只做一件事: 把"现在处于哪个相位、用的是哪个模型版本、为什么切换"落成**唯一**的原子文件,
白天进程只读、夜间进程只写。任何在线服务不得自行改相位(与 ss_engine_loop 同一条纪律)。
"""
from __future__ import annotations

import json
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))
DN_DIR = os.path.join(ROOT, "zmax_data", "daynight")
STATE = os.path.join(DN_DIR, "state.json")

PHASES = ("day", "night")


def _ensure() -> None:
    os.makedirs(DN_DIR, exist_ok=True)


def read_state() -> dict:
    _ensure()
    try:
        with open(STATE, encoding="utf-8") as f:
            s = json.load(f)
    except Exception:                                             # noqa: BLE001
        s = {}
    d = {
        "phase": s.get("phase") or "idle",
        "since": s.get("since") or 0.0,
        "day_id": s.get("day_id") or "",
        "night_id": s.get("night_id") or "",
        "model_ver": s.get("model_ver") or "v0",
        "epoch": int(s.get("epoch") or 0),
        "reason": s.get("reason") or "init",
        "writer": s.get("writer") or "daynight.phase",
    }
    return d


def write_state(st: dict, why: str = "") -> dict:
    """原子写: 先写 .tmp 再 rename, 避免写一半被在线进程读到。"""
    _ensure()
    st = dict(st)
    st["since"] = st.get("since") or time.time()
    st["writer"] = "daynight.phase"
    if why:
        st["reason"] = why
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, STATE)
    return st


def start_day(scope: str = "", why: str = "") -> dict:
    st = read_state()
    st.update({"phase": "day", "since": time.time(),
               "day_id": st.get("day_id") or time.strftime("D%Y%m%d_%H%M%S"),
               "scope": scope})
    if why or st.get("phase") != "day":
        st["day_id"] = st["day_id"] if st.get("day_id") else time.strftime("D%Y%m%d_%H%M%S")
    return write_state(st, why or "白天开始: 在线观测/推理")


def start_night(why: str = "") -> dict:
    st = read_state()
    if st["phase"] == "night":
        return st
    st.update({"phase": "night", "since": time.time(),
               "night_id": time.strftime("N%Y%m%d_%H%M%S")})
    return write_state(st, why or "夜间开始: 离线对齐/固化")


def end_night(gate_passed: bool, model_ver: str = "", why: str = "") -> dict:
    st = read_state()
    st.update({"phase": "idle", "since": time.time(), "epoch": int(st.get("epoch") or 0) + 1})
    if gate_passed and model_ver:
        st["model_ver"] = model_ver
    return write_state(st, why or ("夜间结束: 闸门%s" % ("通过→已切换" if gate_passed else "未过→保留旧版")))


def is_night() -> bool:
    return read_state()["phase"] == "night"


def guard_online(action: str) -> None:
    """在线动作的相位闸: 夜间不许下发在线动作(与安全闸同级)。"""
    st = read_state()
    if st["phase"] == "night":
        raise RuntimeError("相位闸: 当前是夜间(离线固化), 拒绝在线动作 `%s`" % action)
