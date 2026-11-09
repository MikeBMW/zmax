# -*- coding: utf-8 -*-
"""🧩 统一状态空间 · 理想 43D 观察量 (状态空间发理想的值)

老倪 2026-11-01: 「现在继续向前接入统一状态空间，先让状态空间发出理想的值，你来保证 300UPH」

位置: ssobs(🧩 SU(2) 统一状态空间) 的 out1 就是 43D 统一状态向量。
本模块只负责**按理想工艺动作生成这一帧的 43D** —— 不给下游塞假数据, 而是把
「工艺动作表」(geo_plan_impl.build_ideal_plan: 112 步 · 45.05s/4件 · 320 UPH) 的
当前步翻译成观察量语义:

    43D 通道划分 (su2.py::obs43_geometry 认定的唯一口径)
      [0:3]   手位置 (m)
      [3]     夹爪开度 (0 张 / 1 夹)
      [4:7]   光模块位置 (m)          —— 夹着时跟手, 否则留在来源槽/孔里
      [7:11]  光模块四元数 (w,x,y,z)
      [11:18] pad ×7
      [18:36] 上一帧 18D
      [36:39] 孔位 / 目标点 (m)
      [39:43] 触觉 (grasp, contact, dir_x, dir_z)

单位统一 **米** (与 su2.py 一致; 段表是毫米, 这里 /1000)。
几何误差 e = (光模块头 − 孔位) 由 su2.obs43_geometry 现算, 本模块不碰。
"""
from __future__ import annotations

import math
import os
import time

import numpy as np

DIM = 43
CARRY_KINDS = ("grip", "pull", "insert", "release", "up")     # 这些段手里有货
CONTACT_KINDS = ("insert", "pull", "release")


def _quat_from_dir(d):
    """把方向(3,)转成四元数 (w,x,y,z): 用最短弧把 +z 转到 d。"""
    v = np.asarray(d, dtype=float)
    n = float(np.linalg.norm(v))
    if n < 1e-9:
        return [1.0, 0.0, 0.0, 0.0]
    v = v / n
    z = np.array([0.0, 0.0, 1.0])
    dot = float(np.clip(np.dot(z, v), -1.0, 1.0))
    if dot > 0.999999:
        return [1.0, 0.0, 0.0, 0.0]
    if dot < -0.999999:
        return [0.0, 1.0, 0.0, 0.0]
    axis = np.cross(z, v)
    axis = axis / np.linalg.norm(axis)
    ang = math.acos(dot)
    s = math.sin(ang / 2.0)
    return [float(math.cos(ang / 2.0)), float(axis[0] * s), float(axis[1] * s), float(axis[2] * s)]


def build_obs43(step, u, prev18=None):
    """按一步工艺动作 (step=build_ideal_plan() 的 seg, u=步内进度 0~1) 生成 43D 观察量 (m)。"""
    a = np.asarray(step["a"], dtype=float) / 1000.0
    b = np.asarray(step["b"], dtype=float) / 1000.0
    hand = a + (b - a) * float(max(0.0, min(1.0, u)))
    kind = str(step.get("kind") or "move")
    carry = kind in CARRY_KINDS
    # 光模块位置: 夹着 ⇒ 跟手; 否则留在来源端 (a 点 = 本段起点, 也就是它所在的位置)
    module = hand.copy() if carry else a.copy()
    direction = (b - a)
    quat = _quat_from_dir(direction) if float(np.linalg.norm(direction)) > 1e-6 else [1.0, 0.0, 0.0, 0.0]

    o = np.zeros(DIM, dtype=float)
    o[0:3] = hand
    o[3] = 1.0 if carry else 0.0
    o[4:7] = module
    o[7:11] = quat
    o[11:18] = 0.0                                   # pad×7 (本档无压力垫读数, 不用假值)
    o[18:36] = (np.asarray(prev18, dtype=float) if prev18 is not None and len(prev18) == 18
                else np.concatenate([o[0:18]]))
    o[36:39] = b                                     # 目标 = 本步终点 (孔位/槽位/检测点)
    o[39] = 1.0 if carry else 0.0                    # grasp
    o[40] = 1.0 if kind in CONTACT_KINDS else 0.0    # contact
    o[41] = float(direction[0] / (np.linalg.norm(direction) + 1e-9))
    o[42] = float(direction[2] / (np.linalg.norm(direction) + 1e-9))
    return o


def ideal_on(ctx=None):
    """理想档开关: ctx.params.ideal 或环境 ZMAX_SS_IDEAL=1。"""
    try:
        pr = (ctx or {}).get("params") or {}
        if str(pr.get("ideal")).lower() in ("1", "true", "on", "yes"):
            return True
    except Exception:                                                   # noqa: BLE001
        pass
    return os.environ.get("ZMAX_SS_IDEAL", "0").strip().lower() in ("1", "true", "on", "yes")


def frame(plan_doc, t=None):
    """按循环时钟取当前步 → (obs43, meta)。plan_doc = geo_plan_impl.build_ideal_plan() 的结果。"""
    t = time.time() if t is None else t
    cyc = float(plan_doc["cycle_s"])
    el = t % max(1e-6, cyc)
    cur = plan_doc["segs"][-1]
    for s in plan_doc["segs"]:
        if el <= s["t0"] + s["t"]:
            cur = s
            break
    u = 0.0 if cur["t"] <= 0 else min(1.0, max(0.0, (el - cur["t0"]) / cur["t"]))
    obs = build_obs43(cur, u)
    meta = dict(step_i=cur["i"], step_n=plan_doc["n_seg"], action=cur["kind"],
                label=cur.get("label"), u=round(u, 4), t_str=time.strftime("%H:%M:%S"),
                cycle_s=cyc, tact_s=plan_doc["tact_s"], uph=plan_doc["uph"],
                ok300=plan_doc["ok300"], tcp_mm=[round(float(x) * 1000, 2) for x in obs[0:3]],
                target_mm=[round(float(x) * 1000, 2) for x in obs[36:39]],
                src="ssobs 理想档 (工艺动作 → 43D)")
    return obs, meta
