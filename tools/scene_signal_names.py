#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔤 场景信号命名真源 —— 同一根通道, 摆盘/插拔两场景的**显示名不同**

老倪 2026-10-13: 「摆盘场景的实时监控信号, 蓝色信号, 还有夹爪? 不是吸盘么」

取证(可复核, 不是猜测):
  · 摆盘 episode 跑在 `sawyer_tray_place.xml` (meta.mode='tray'), 记录的通道名沿用插拔底座
    (gripper / peg / mouth), 但**物理执行器是真空吸盘**:
  · 通道 `gripper` 取值集合 = {0.0, 0.9}, 0.9 就是**吸附建立证据**
    (tools/gen_tray_place_video.py: `grip_ev = 0.9 if (vac and not released) else gripper_raw`);
    episode history 原文也写「抬起: 夹持建立 gripper=0.90」。
  · ⇒ 摆盘里把这条通道叫「夹爪」是**通道沿用旧名造成的错标**, 不是摆盘真有夹爪。
    (实测 >1.5mm 的摩擦夹持在仿真里必滑脱, 摆盘链全程 u[3]=-1 指爪张开, 走吸附。)

本模块是取名**唯一真源**: 只改显示名, **不动通道 / 数值 / 口径** ——
3D 里看到的动作与「实时监控」的波形因此一一对应 (看到吸盘吸附 ⇔ 波形上是 真空吸持)。

用法:
    from scene_signal_names import name, hint, rename
    name("夹爪", "tray")        -> "真空吸持"
    name("夹爪", "plug")        -> "夹爪"
    hint("夹爪", "tray")        -> "(0.9=吸附建立)"
"""
from __future__ import annotations

TRAY = "tray"
PLUG = "plug"

# 通道键(稳定, 不随场景变) → {摆盘名, 插拔名}
NAME_MAP = {
    "夹爪":            {TRAY: "真空吸持",       PLUG: "夹爪"},
    "抓住":            {TRAY: "吸住",           PLUG: "抓住"},
    "夹持":            {TRAY: "吸附力",         PLUG: "夹持"},
    "夹持力":          {TRAY: "吸附力",         PLUG: "夹持力"},
    "光模块头到孔_mm":  {TRAY: "吸嘴到槽位_mm",  PLUG: "光模块头到孔_mm"},
    "光模块头到孔":     {TRAY: "吸嘴到槽位",     PLUG: "光模块头到孔"},
    "光模块头→孔":      {TRAY: "吸嘴→槽位",      PLUG: "光模块头→孔"},
    "gripper_pos":     {TRAY: "吸盘状态",       PLUG: "夹爪开合"},
    "grip_lock":       {TRAY: "吸附锁",         PLUG: "夹持锁"},
}

# 括号里的口径注解(页面/HUD 直接跟在数值后面)
HINT_MAP = {
    "夹爪":            {TRAY: "(0.9=吸附建立)", PLUG: "(1=闭合)"},
    "抓住":            {TRAY: "(1=已吸住)",     PLUG: "(1=已抓住)"},
    "夹持":            {TRAY: "(吸附保持力 N)", PLUG: "(夹持力 N)"},
    "光模块头到孔_mm":  {TRAY: "(吸嘴→槽位)",   PLUG: "(头→孔口)"},
    "光模块头到孔":     {TRAY: "(吸嘴→槽位)",   PLUG: "(头→孔口)"},
}


def mode_of(scene_mode: str | None) -> str:
    """把场景判定 (tray / plug / None) 归一成本模块的两种语义模式。"""
    return TRAY if str(scene_mode) == TRAY else PLUG


def name(key: str, mode: str) -> str:
    """通道键 → 该场景下的显示名 (无映射则原样返回, 不装)。"""
    m = NAME_MAP.get(str(key))
    if not m:
        return str(key)
    return m.get(mode_of(mode)) or str(key)


def hint(key: str, mode: str) -> str:
    h = HINT_MAP.get(str(key))
    if not h:
        return ""
    return h.get(mode_of(mode)) or ""


def rename(key: str, mode: str) -> str:
    """同 name(), 语义别名 —— 用在「把快照字段名按场景改名」的调用点。"""
    return name(key, mode)


def rename_keys(keys, mode: str):
    return [name(k, mode) for k in keys]


def rename_payload(d: dict, mode: str) -> dict:
    """快照 dict 的键按场景改名 (值原样搬走, 顺序保持)。"""
    out = {}
    for k, v in (d or {}).items():
        _m = NAME_MAP.get(str(k))
        out[(name(k, mode) if _m else k)] = v
    return out


def scene_label(scene_mode: str | None) -> str:
    return "摆盘场景(真空吸盘)" if mode_of(scene_mode) == TRAY else "插拔场景(两指夹爪)"
