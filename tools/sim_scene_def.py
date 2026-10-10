#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sim_scene_def.py — 仿真场景真源 (画布 3D 视图里那条「插拔光模块」场景) (老倪 2026-10-10)

老倪: 「之前做好的 simulink 画布的 3D 视图的插拔光模块的场景，也需要在场景管理功能区，
       用户可以选择编辑并运行」

为什么需要这个文件 (单一真源):
  这条仿真场景的几何原本**散在三处**、靠人工同步 (技能 zmax-scene-engineering 已记此坑):
    ① tools/gen_l4_demo_video.py  的 TURNTABLE_XY / TURNTABLE_Z / COUPLER_XY / AOI_FOCUS
    ② tools/gen_l4_demo_scene.py  写进 XML 的 <body name="turntable" pos="..."> / coupler / cp_stage_b
    ③ metaworld 资产 XML 里的台面/光模块/夹具尺寸 (sawyer_peg_insertion_side.xml)
  改一处不同步 = 物理与视觉不一致 (老倪最恨的"实际怎么执行的")。
  ⇒ 本文件把它们收成**一份 JSON 真源**, 两个生成器都从这里读; 场景管理功能区编辑 = 改这份真源。

真源文件: data/scene/sim/sim_scenes.json   (由 default() 首次落盘; 数值全部来自上面三处实测值)
用法:
  sim_scene_def.py --show              打印真源
  sim_scene_def.py --check             校验: 真源 ↔ 两个生成器 ↔ metaworld XML 是否一致
  sim_scene_def.py --set turntable.pos '[0.42,0.60,0.0255]'   改一项 (带备份)
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import numpy as np
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "data", "scene", "sim", "sim_scenes.json")
BACKUP = os.path.join(ROOT, "data", "scene", "_backup_registry")

GEN_VIDEO = os.path.join(ROOT, "tools", "gen_l4_demo_video.py")
GEN_SCENE = os.path.join(ROOT, "tools", "gen_l4_demo_scene.py")


def default() -> dict:
    """首次落盘的默认真源 — 每个数都有出处 (不编造)。"""
    return {
        "format": "zmax-sim-scenes", "version": "1.0",
        "coord": "世界系 m (metaworld sawyer_xyz; 台面顶 z=0, +Y 朝臂, +X 右)",
        "note": "画布 3D 视图那条「插拔光模块」仿真场景的几何真源; 生成器与场景管理都读这里",
        "scenes": {
            "SIM-PEG-L4": {
                "name": "插拔光模块 · 仿真场景 (画布 3D 视图)",
                "kind": "sim", "level": "L4",
                "env": "sawyer_peg_insertion_side_l4",
                "desc": "①来料转台→②姿态适配抓取→③治具校直回正→④标准抓取→⑤插入 49mm→⑥拔出→⑦AOI 检测→⑧光耦合",
                # 与画布 L4 档的导出调用**逐字对齐** (simulink_module.py:14728 那段):
                #   python tools/gen_l4_demo_video.py --also-latest, cwd=tools, env MUJOCO_GL=egl +
                #   MUJOCO_EGL_DEVICE=0 + PYTHONIOENCODING + ZMAX_L4_ROOT
                "runner": {"tool": "tools/gen_l4_demo_video.py", "args": ["--also-latest"],
                           "alt": "tools/gui/state_space_sim_real.py (画布 ▶运行, 同引擎)",
                           "cwd": "tools", "env": {"MUJOCO_GL": "egl", "MUJOCO_EGL_DEVICE": "0",
                                                   "PYTHONIOENCODING": "utf-8", "ZMAX_L4_ROOT": "<ROOT>"},
                           "note": "--seed 默认 (与画布 L4 档同一条 episode); --tt-deg 60~120 可改转台角做泛化",
                           "eta_s": 180, "product": "reports/ss_episode_latest.mp4"},
                "objects": [
                    {"name": "工作台面", "center": [0.0, 0.0, -0.027], "size": [0.8, 0.8, 0.054],
                     "source": "metaworld table.xml: box size .4 .4 .027 @ z=-0.027 (台面顶 z=0)"},
                    {"name": "来料转台 (外力旋转90°)", "center": [0.42, 0.60, 0.005], "size": [0.15, 0.15, 0.010],
                     "source": "gen_l4_demo_scene XML: body turntable @ 0.42 0.60 0 · cylinder r=0.075 h=0.005"},
                    {"name": "光模块 (peg)", "center": [0.0, 0.60, 0.03], "size": [0.03, 0.03, 0.24],
                     "source": "sawyer_peg_insertion_side.xml: body peg @ 0 0.6 0.03 · box size .015 .015 .12"},
                    {"name": "夹具体 (带插孔)", "center": [-0.3, 0.60, 0.10], "size": [0.19, 0.20, 0.20],
                     "source": "peg_block.xml 碰撞盒 x±0.095 y±0.1 z0~0.2 · body 同 XML @ -0.3 0.6 0"},
                    {"name": "光耦合压电台底座", "center": [0.55, 0.42, 0.01], "size": [0.34, 0.11, 0.020],
                     "source": "gen_l4_demo_scene XML: cp_base box size .17 .055 .010 @ z=0.010"},
                    {"name": "x/y 压电微动载物台", "center": [0.55, 0.42, 0.048], "size": [0.34, 0.11, 0.008],
                     "source": "gen_l4_demo_scene XML: cp_stage box size .17 .055 .004 @ 0.55 0.42 0.044+0.004"},
                ],
                "markers": [
                    {"name": "AOI 镜头对焦点", "pos": [0.12, 0.62, 0.10], "type": "检查点", "radius_m": 0.08,
                     "source": "gen_l4_demo_video AOI_FOCUS=(0.12,0.62,0.10) · AOI_HOVER=0.08"},
                    {"name": "光纤头耦合基准", "pos": [0.42, 0.42, 0.067], "type": "工位", "radius_m": 0.02,
                     "source": "gen_l4_demo_scene XML: cp_fiber/cp_ref site @ -0.13 0 0.067 (coupler 系)"},
                    {"name": "来料位 (转台中心)", "pos": [0.42, 0.60, 0.0255], "type": "工位", "radius_m": 0.05,
                     "source": "TURNTABLE_XY(0.42,0.60) + TURNTABLE_Z=0.0255 (peg 坐盘面)"},
                    {"name": "放置位 (压电台上方)", "pos": [0.55, 0.42, 0.052], "type": "工位", "radius_m": 0.04,
                     "source": "cp_stage_top site @ 0.55 0.42 0.044+0.008"},
                ],
                "fences": [
                    {"name": "仿真作业区围栏 (臂可达区)", "center": [0.2, 0.5, 0.15], "size": [0.95, 0.75, 0.30],
                     "source": "推导: 覆盖 6 个对象的 bbox 外扩 100mm (手工写入, 供 3D 视图/管理用)"},
                ],
                "trajectories": [
                    {"name": "L4 插入链 (转台→抓取→治具→插入→AOI→耦合)", "waypoints": [
                        [0.42, 0.60, 0.16], [0.42, 0.60, 0.0255], [0.0, 0.60, 0.12],
                        [-0.30, 0.60, 0.20], [0.0, 0.60, 0.10], [0.55, 0.42, 0.115],
                        [0.55, 0.42, 0.052], [0.55, 0.42, 0.115], [0.12, 0.62, 0.10],
                        [0.55, 0.42, 0.115]],
                     "source": "推导: 8 段演示的工艺位姿 (转台→光模块→夹具→耦合台→AOI→耦合基准)"},
                ],
                "peg": {"insert_depth_m": 0.050, "hole_depth_m": 0.066, "note": "孔深 0.066 留安全余量 (技能: 插入 49mm)"},
            }
        },
    }


def load() -> dict:
    if not os.path.exists(PATH):
        d = default()
        save_raw(d)
        return d
    with open(PATH, encoding="utf-8") as f:
        return json.load(f)


def save_raw(d: dict) -> None:
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    if os.path.exists(PATH):
        os.makedirs(BACKUP, exist_ok=True)
        shutil.copy2(PATH, os.path.join(BACKUP, "sim_scenes.json.%s.bak" % time.strftime("%H%M%S")))
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, PATH)


def get(d: dict, key: str):
    """取真源项, 支持 'turntable.pos' 点路径 (在默认场景 SIM-PEG-L4 内)。"""
    sc = d["scenes"]["SIM-PEG-L4"]
    cur = sc
    for part in key.split("."):
        if isinstance(cur, list):
            return cur
        cur = cur[part]
    return cur


def geometry() -> dict:
    """给生成器用的几何 —— **以 MuJoCo 真模型为准** (2026-10-10 老倪: 场景要对齐 metaworld 渲染)。

    取值口径: 转台/压电台/微动台从 MuJoCo 模型导出的 geom (转台盘面 tt_disc / 压电台基座 cp_base /
    微动载物台面 cp_stage) 世界系中心与尺寸算出; 语义常量 (peg 坐盘面的 feed_z、插入深度) 仍走真源标量,
    每个都带出处 —— 这样"生成器常量 == 真模型"由 check() 逐条核, 避免手写值与模型跑偏
    (实测曾把台面写 0.8×0.8 实为 1.4×0.8、光模块按方截面写成 40×40 实为 40×16)。
    """
    sc = load()["scenes"]["SIM-PEG-L4"]
    mk = {str(m["name"]): m for m in sc["markers"]}
    exp = export_mujoco_truth("SIM-PEG-L4", write=False)
    objs = exp["objects"] if exp.get("ok") else []

    def _g(nm):
        for o in objs:
            if nm in str(o.get("source", "")) or str(o.get("name")) == nm:
                return o
        raise KeyError("MuJoCo 导出里没有 %s" % nm)

    tt, cp, st = _g("geom=tt_disc"), _g("geom=cp_base"), _g("geom=cp_stage")
    site = {m["name"]: m for m in (exp.get("markers") or [])}
    return {
        "turntable": {"xy": [float(tt["center"][0]), float(tt["center"][1])],
                      "pos": [float(v) for v in tt["center"]],
                      "r": float(tt["size"][0]) / 2.0,
                      "z_top": float(tt["center"][2]) + float(tt["size"][2]) / 2.0,
                      # TURNTABLE_Z 语义 = peg 坐盘面 (生成器常量, 真源标量; 盘顶由 MuJoCo 真模型算)
                      "feed_z": float(sc.get("const", {}).get("feed_z", 0.0255))},
        "coupler": {"xy": [float(cp["center"][0]), float(cp["center"][1])],
                    "pos": [float(v) for v in cp["center"]],
                    # ⚠️ XML <body cp_stage_b pos="x y Z"> 的 Z 是 body 原点; 载物台盒在其内局部 z=+0.004,
                    #    MuJoCo 导出的是台面世界中心 ⇒ body Z = 台面中心 − 0.004 (物理不变)
                    "stage_z": round(float(st["center"][2]) - 0.004, 4),
                    "stage_center_z": float(st["center"][2]),
                    "ref": site.get("site:cp_ref", {}).get("pos")},
        "aoi_focus": [float(x) for x in sc.get("const", {}).get("aoi_focus", [0.12, 0.62, 0.10])],
        "aoi_hover": float(sc.get("const", {}).get("aoi_hover_m", 0.08)),
        "insert_depth_m": float(sc["peg"]["insert_depth_m"]),
        "objects_by_name": {str(o["name"]): o for o in sc["objects"]}, "markers_by_name": mk,
    }



# ══════════════════════════════════════════════════════════════════════════════════════════
# 🧩 摆盘场景 SS-TRAY-PLACE (老倪 2026-10-10):
#   「将摆盘的场景，AOI相机，换成料盘，料盘是装光模块的黑色塑料盒子，没有盖，就是个托盘，
#     里面放着3个光模块；将插孔换成另一个 tray盘，tray盘与料盘的区别是，tray盘里面有固定的
#     槽位，正好可以对应3个光模块，光模块可以正好落进这三个槽子里」
#   ⇒ 料盘落在原 AOI 相机工位 (0.12, 0.62); tray盘落在原插孔 (带孔盒) 位置 (-0.2645, 0.4623)。
# ══════════════════════════════════════════════════════════════════════════════════════════
TRAY_SCENE = "SS-TRAY-PLACE"
_TRAY_BLACK = [0.10, 0.10, 0.11]          # 黑色塑料 (料盘/tray盘)
_TRAY_GOLD = [0.92, 0.74, 0.24]           # 光模块 (金色)

# 光模块 + 盘几何 (m): 光模块 52×20×12mm; 槽位间距 30mm; 盘壁 6mm
_TRAY_MW, _TRAY_MD, _TRAY_MH = 0.052, 0.020, 0.012
# 🩹 2026-10-10 摆盘实测: 隔板厚 10mm(半长, 即 20mm 实厚) + 节距 30mm ⇒ 凹槽开口只有 10~15mm,
#    而光模块宽 20mm ⇒ **物理上放不进去** (件只能骑在隔板棱上, 落座高 3.6mm, 单边偏 2.5mm)。
#    改: 节距 30→38mm, 隔板 10→5mm(实厚 10mm) ⇒ 开口 28mm, 单边留 4mm 余量; 3D 视图同源自动跟。
_TRAY_GAP = 0.038
_TRAY_WW, _TRAY_WH, _TRAY_BH = 0.005, 0.024, 0.008     # 🩹 2026-10-10: 6→10mm 壁厚, 14→24mm 壁高, 底 6→8mm
                                                       #   (原尺寸太小: 视觉核对只能认出"一片深色", 第二个盘/槽位认不出)
_TRAY_FLOOR = [0.30, 0.30, 0.33]           # 盘内底 (中灰) —— 黑壁+灰底 才看得出"槽位是凹下去的"
_TRAY_PW = _TRAY_MW + 4 * _TRAY_WW + 0.010                 # 盘外廓 x
_TRAY_PH = 3 * _TRAY_GAP + 2 * _TRAY_WW                    # 盘外廓 y
_TRAY_LP = (0.058, 0.560)        # 料盘中心 (原 AOI 相机工位) —— y 0.62→0.56: 往台面里挪, 完整入画
_TRAY_TP = (-0.235, 0.560)       # tray盘中心 (原插孔/带孔盒位置) —— 与料盘同排, x 间距 0.35m 不叠
                                 #   (实测原 (0.12,0.62)/(-0.2645,0.4623): 后者被台沿遮, 前者大半出画)


def _tray_layout() -> dict:
    """摆盘工位: 料盘 (黑塑料托盘, 无盖无槽位, 装 3 个光模块) + tray盘 (3 个固定槽位)。"""
    LX, LY = _TRAY_LP
    TX, TY = _TRAY_TP
    PW, PH, WW, WH, BH = _TRAY_PW, _TRAY_PH, _TRAY_WW, _TRAY_WH, _TRAY_BH
    objs, marks = [], []

    def _o(nm, c, sz, col, src=""):
        objs.append({"name": nm, "center": [float(x) for x in c], "size": [float(v) for v in sz],
                     "color": list(col), "source": src, "editable": True, "sim": True})

    def _walls(prefix, cx, cy, src):
        _o(prefix + "·底板", (cx, cy, BH / 2), (PW, PH, BH), _TRAY_BLACK, src)
        _o(prefix + "·壁X-", (cx - PW / 2 + WW / 2, cy, BH + WH / 2), (WW, PH, WH), _TRAY_BLACK, src)
        _o(prefix + "·壁X+", (cx + PW / 2 - WW / 2, cy, BH + WH / 2), (WW, PH, WH), _TRAY_BLACK, src)
        _o(prefix + "·壁Y-", (cx, cy - PH / 2 + WW / 2, BH + WH / 2), (PW, WW, WH), _TRAY_BLACK, src)
        _o(prefix + "·壁Y+", (cx, cy + PH / 2 - WW / 2, BH + WH / 2), (PW, WW, WH), _TRAY_BLACK, src)
        # 🔎 内底: 中灰面 (比黑壁亮) —— 黑壁围出的"凹槽"才看得出来; 光模块/隔板都落在这面上
        _o(prefix + "·内底", (cx, cy, BH + 0.001), (PW - 2 * WW, PH - 2 * WW, 0.002), _TRAY_FLOOR, src)

    _walls("料盘", LX, LY, "摆盘: 装光模块的黑色塑料托盘 (没有盖, 就是个托盘)")
    for _i, _dy in enumerate((-_TRAY_GAP, 0.0, _TRAY_GAP)):
        _o("光模块 %d (在料盘里)" % (_i + 1), (LX, LY + _dy, BH + _TRAY_MH / 2),
           (_TRAY_MW, _TRAY_MD, _TRAY_MH), _TRAY_GOLD, "摆盘: 料盘里的 3 个光模块")
    marks.append({"id": "tray_mk_01", "name": "料盘 (装光模块的黑色塑料托盘)", "pos": [LX, LY, BH + WH],
                  "type": "工位", "radius_m": 0.02,
                  "source": "原 AOI 相机工位 → 料盘 (老倪 2026-10-10)"})

    _walls("tray盘", TX, TY, "摆盘: 带 3 个固定槽位的 tray盘 (光模块正好落进槽里)")
    for _i, _dy in enumerate((-_TRAY_GAP / 2, _TRAY_GAP / 2)):
        _o("tray盘·隔板 %d" % (_i + 1), (TX, TY + _dy, BH + WH / 2),
           (PW - 2 * WW, WW, WH), _TRAY_BLACK, "摆盘: 槽位隔板 (3 槽 = 3 个光模块位)")
    for _i, _dy in enumerate((-_TRAY_GAP, 0.0, _TRAY_GAP)):
        marks.append({"id": "tray_mk_%02d" % (_i + 2), "name": "tray盘 槽位 %d (光模块落位)" % (_i + 1),
                      "pos": [TX, TY + _dy, BH + WH], "type": "检查点", "radius_m": 0.012,
                      "source": "摆盘: 固定槽位 ↔ 光模块 (正好落进)"})
    return {"objects": objs, "markers": marks}


def _tray_objects3d() -> dict:
    """摆盘场景对象: 台面/护栏/机器人 (沿用) + 料盘 + tray盘 + 3 个光模块; 不含插拔夹具。"""
    t = episode_truth()
    _sc = load()["scenes"].get(TRAY_SCENE) or {}
    objs = []
    for i, o in enumerate(_sc.get("objects") or []):
        nm = str(o.get("name") or "")
        if any(k in nm for k in ("光模块", "夹具", "孔座", "peg")):
            continue                                   # 插拔的孔座/夹具/单根光模块 → 换成摆盘盘件
        d = {"id": o.get("id") or ("tr_ob_%02d" % (i + 1)), "name": nm,
             "center": [float(x) for x in o["center"]], "size": [float(x) for x in o["size"]],
             "source": o.get("source", ""), "editable": True}
        for k in ("color", "part"):
            if o.get(k) is not None:
                d[k] = o[k]
        objs.append(d)
    L = _tray_layout()
    for j, o in enumerate(L["objects"]):
        d = dict(o)
        d["id"] = "tray_ob_%02d" % (j + 1)
        objs.append(d)
    return {"format": "zmax-scene-objects3d", "version": "1.0", "scene_id": TRAY_SCENE,
            "coord": "世界系 m (metaworld sawyer_xyz)", "sim": True, "kind": "tray",
            "source": "摆盘工位: 料盘(装 3 个光模块, 无盖) + tray盘(3 个固定槽位) — 机器人/台面沿用 episode 真值",
            "scene_name": _sc.get("name"), "truth": _sc.get("truth"),
            "episode": ({"npz": os.path.relpath(t["npz"], ROOT), "step_count": t["steps"]} if t.get("ok") else None),
            "objects": objs, "markers": L["markers"], "fences": _sc.get("fences") or [],
            "trajectories": []}


def _tray_overlay() -> dict:
    """摆盘场景叠加层: 标记 = 料盘 + 3 个槽位; 没有插拔的孔口/插入终点 (那是插拔的语义)。"""
    _sc = load()["scenes"].get(TRAY_SCENE) or {}
    L = _tray_layout()
    fens = [{"id": "tray_fn_01", "kind": "box", "shape": {"center": [0.0, 0.6, 0.12], "size": [1.4, 0.8, 0.24]},
             "name": "作业区 (台面上方)", "source": "场景台面 1.4×0.8"}]
    return {"format": "zmax-scene-overlay-spec", "version": "1.0", "scene_id": TRAY_SCENE,
            "sim": True, "kind": "tray", "scene_name": _sc.get("name"),
            "run": _sc.get("runner"), "seed": _sc.get("seed"), "edit": _sc.get("edit"),
            "source": "摆盘工位几何 (料盘 + 带槽位 tray盘)", "markers": L["markers"],
            "fences": fens, "trajectories": []}


def to_objects3d(scene_id: str = "SIM-PEG-L4") -> dict:
    if scene_id == TRAY_SCENE:
        return _tray_objects3d()
    if scene_id == EPI_SCENE:
        return _epi_objects3d()
    sc = load()["scenes"][scene_id]
    objs = []
    for i, o in enumerate(sc["objects"]):
        _d = {"id": "sim_ob_%02d" % (i + 1), "name": o["name"], "center": [float(x) for x in o["center"]],
              "size": [float(x) for x in o["size"]], "source": o.get("source", ""), "editable": True}
        for _k in ("color", "part"):          # 机器人本体的颜色/类别要透传到场景目录文件
            if o.get(_k) is not None:
                _d[_k] = o[_k]
        objs.append(_d)
    return {"format": "zmax-scene-objects3d", "version": "1.0", "scene_id": scene_id,
            "coord": "世界系 m (metaworld sawyer_xyz)", "source": "data/scene/sim/sim_scenes.json (仿真场景真源)",
            "scene_name": sc["name"], "sim": True, "env": sc.get("env"), "level": sc.get("level"),
            "objects": objs}


def to_overlay(scene_id: str = "SIM-PEG-L4") -> dict:
    import copy as _copy
    if scene_id == TRAY_SCENE:
        return _tray_overlay()
    if scene_id == EPI_SCENE:
        return _epi_overlay()
    sc = load()["scenes"].get(scene_id)
    if sc is None:
        return {"format": "zmax-scene-overlay-spec", "version": "1.0", "scene_id": scene_id,
                "source": "缺失", "markers": [], "fences": [], "trajectories": []}
    # 回放/复刻场景 (含摆盘副本) 与 episode 同结构 ⇒ 直接复用它的 overlay 组装
    if (sc.get("truth") or {}).get("episode") or sc.get("copied_from"):
        _d = load()
        _keep = _d["scenes"].get(EPI_SCENE)
        try:
            _d["scenes"][EPI_SCENE] = sc
            return _epi_overlay()
        finally:
            if _keep is not None:
                _d["scenes"][EPI_SCENE] = _keep
    mk = []
    for i, m in enumerate(sc["markers"]):
        mk.append({"id": "sim_mk_%02d" % (i + 1), "name": m["name"], "type": m.get("type", "自定义"),
                   "pos": [float(x) for x in m["pos"]], "radius_m": float(m.get("radius_m", 0.05)),
                   "source": m.get("source", ""), "editable": True})
    fn = []
    for i, f in enumerate(sc["fences"]):
        _sh = f.get("shape") if isinstance(f.get("shape"), dict) else {}
        _c = f.get("center") or _sh.get("center") or [0, 0, 0]
        _s = f.get("size") or _sh.get("size") or [0.2, 0.2, 0.2]
        c = [float(x) for x in _c]
        s = [float(x) for x in _s]
        fn.append({"id": "sim_fn_%02d" % (i + 1), "name": f["name"], "kind": "box", "enabled": True,
                   "shape": {"center": c, "size": s}, "source": f.get("source", ""), "editable": True})
    tj = []
    for i, t in enumerate(sc["trajectories"]):
        tj.append({"id": "sim_tj_%02d" % (i + 1), "name": t["name"], "kind": "示教",
                   "waypoints": [[float(x) for x in w] for w in t["waypoints"]],
                   "derived_from": t.get("source", ""), "editable": True})
    return {"format": "zmax-scene-overlay-spec", "version": "1.0", "scene_id": "SIM-PEG-L4",
            "source": "data/scene/sim/sim_scenes.json (仿真场景真源)", "sim": True,
            "run": sc.get("runner"), "markers": mk, "fences": fn, "trajectories": tj}


# ───────────────── 与生成器的同源校验 (改一处不同步 = 老倪最恨的假一致) ─────────────────
def check() -> int:
    bad, g = [], geometry()
    if not os.path.exists(PATH):
        return _rep(["真源文件不存在: %s" % PATH])
    # ① gen_l4_demo_video.py 的常量是否与真源一致
    if os.path.exists(GEN_VIDEO):
        src = open(GEN_VIDEO, encoding="utf-8").read()

        def _num(name):
            m = re.search(r"^%s\s*=\s*(?:np\.)?array\((\[.*?\])\)" % name, src, re.M) or \
                re.search(r"^%s\s*=\s*([-\d.]+)" % name, src, re.M)
            if not m:
                return None
            t = m.group(1)
            return [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", t)] if t.startswith("[") else float(t)

        _tt, _cp, _aoi = _num("TURNTABLE_XY"), _num("COUPLER_XY"), _num("AOI_FOCUS")
        _ttz = _num("TURNTABLE_Z")
        _wired = "import sim_scene_def as _SSD" in src
        _notes = []
        for nm, got, want in (("TURNTABLE_XY", _tt, g["turntable"]["xy"]),
                              ("COUPLER_XY", _cp, g["coupler"]["xy"]),
                              ("AOI_FOCUS", _aoi, g["aoi_focus"])):
            if got is None:
                bad.append("gen_l4_demo_video.py 找不到常量 %s" % nm)
            elif [round(float(x), 4) for x in got] != [round(float(x), 4) for x in want]:
                # 已接真源 ⇒ 字面常量只是回退值, 运行时以真源为准 (编辑后必然会不同, 不算错)
                (_notes if _wired else bad).append(
                    "%s 字面=%s ≠ 真源=%s%s" % (nm, got, want, " (已接真源, 仅回退值)" if _wired else " (改一处没同步)"))
        for _n in _notes:
            print("   ℹ️  %s" % _n)
        if _wired:
            for _k in ("TURNTABLE_XY", "TURNTABLE_Z", "COUPLER_XY", "AOI_FOCUS", "INSERT_DEPTH"):
                if not re.search(r"^%s = " % _k, src, re.M):
                    bad.append("override 块未接管 %s (运行时读不到真源)" % _k)
        # TURNTABLE_Z 的语义是"peg 坐盘面" (盘顶 z + peg 半厚) — 真源标量 const.feed_z
        _feed_z = float(g["turntable"]["feed_z"])
        if _ttz is not None and abs(float(_ttz) - _feed_z) > 1e-4:
            bad.append("TURNTABLE_Z 生成器=%.4f ≠ 真源 const.feed_z=%.4f" % (float(_ttz), _feed_z))
        # 真源接入证据: 生成器里必须有 override 块 (否则上面的常量与真源只是"恰好相等", 编辑不生效)
        if "import sim_scene_def as _SSD" not in src:
            bad.append("gen_l4_demo_video.py 未接真源 (缺 import sim_scene_def override 块)")
    else:
        bad.append("缺 tools/gen_l4_demo_video.py")
    # ② gen_l4_demo_scene.py 写进 XML 的坐标是否与真源一致
    if os.path.exists(GEN_SCENE):
        if "_sim_geom()" not in open(GEN_SCENE, encoding="utf-8").read():
            bad.append("gen_l4_demo_scene.py 未接真源 (缺 _sim_geom 填充)")
        # 直接看**实际会注入 XML 的字符串** (EXTRA 已由真源填好) —— 比读源码文本强
        try:
            sys.path.insert(0, os.path.join(ROOT, "tools"))
            import importlib
            import gen_l4_demo_scene as _GS
            _GS = importlib.reload(_GS)          # 真源可能刚被改过 ⇒ 必须重载 (否则用缓存旧 EXTRA)
            ext = getattr(_GS, "EXTRA", "")
        except Exception as e:                                              # noqa: BLE001
            ext, bad = "", bad + ["导入 gen_l4_demo_scene 失败: %r" % (e,)]
        for nm, key in (("turntable", "turntable"), ("coupler", "coupler"), ("cp_stage_b", "coupler")):
            m = re.search(r'<body name="%s" pos="([-\d.]+) ([-\d.]+) ([-\d.]+)"' % nm, ext or "")
            if not m:
                bad.append("XML 注入串里找不到 <body name=\"%s\">" % nm)
                continue
            got = [float(m.group(i)) for i in (1, 2, 3)]
            want = ([g[key]["xy"][0], g[key]["xy"][1], 0.0] if nm != "cp_stage_b"
                    else [g["coupler"]["xy"][0], g["coupler"]["xy"][1], g["coupler"]["stage_z"]])
            if [round(x, 4) for x in got] != [round(x, 4) for x in want]:
                bad.append("XML 注入 %s pos=%s ≠ 真源 %s" % (nm, got, want))
    _check_episode(bad, _notes)
    return _rep(bad, "✅ 仿真场景真源 ↔ 生成器 ↔ XML 注入 三处一致 (%s)"
                % os.path.relpath(PATH, ROOT))


def _check_episode(bad, notes) -> None:
    """SS-EPI-CORNER 判据: 场景几何必须是 episode 真值的派生 (改一处不同步立刻报错)。"""
    t = episode_truth()
    if not t.get("ok"):
        bad.append("同源 episode 读不到: %s" % t.get("msg"))
        return
    if "自洽" not in str(t.get("why")):
        bad.append("同源对不自洽 (npz/mp4 不是同一次运行): %s" % t.get("why"))
    o = to_objects3d(EPI_SCENE)
    ov = to_overlay(EPI_SCENE)
    objs = {x["name"]: x for x in o.get("objects", [])}
    _model = "metaworld 模型导出" in str(o.get("source", ""))
    n_robot = len([x for x in o.get("objects", []) if x.get("part") == "robot"])
    if _model:
        # 按 episode 自己的模型导出的口径: 必须有机器人本体 + 台面 + 工件
        if n_robot < 15:
            bad.append("回放场景缺机器人本体 (只 %d 个构件)" % n_robot)
        _tb = [v for k, v in objs.items() if "工作台面" in k]
        if not _tb:
            bad.append("回放场景缺工作台面")
        peg = [v for k, v in objs.items() if "光模块" in k or "peg" in k.lower()]
        if not peg:
            bad.append("回放场景缺光模块")
        # 严格同源: 导出的**模型状态**必须就是 episode 那一帧 (pegGrasp site == meta.peg0, hand == tr['x'][0])
        _an = ((o.get("truth") or {}).get("anchors") or {})
        for _k, _want, _lab in (("site_pegGrasp", [float(v) for v in t["peg0"]], "pegGrasp site vs meta.peg0"),
                                ("body_hand", [float(v) for v in t["hand0"]], "hand body vs tr['x'][0]")):
            _got = _an.get(_k)
            if not _got:
                bad.append("回放场景 truth 缺锚点 %s" % _k)
                continue
            _dd = max(abs(float(a) - float(b)) for a, b in zip(_got, _want))
            if _dd > 1e-3:
                bad.append("回放场景非同一帧: %s 差 %.4fm (%s vs %s)" % (_lab, _dd, _got, _want))
    else:
        peg = [v for k, v in objs.items() if "光模块" in k]
        if not peg:
            bad.append("派生对象里没有 光模块")
        else:
            p0 = [float(v) for v in t["peg0"]]
            if max(abs(a - b) for a, b in zip(peg[0]["center"], p0)) > 1e-6:
                bad.append("光模块初始位 %s ≠ episode 真值 peg0 %s" % (peg[0]["center"], p0))
    mks = {m["name"]: m for m in ov.get("markers", [])}
    mm = [v for k, v in mks.items() if "孔口" in k]
    gg = [v for k, v in mks.items() if "插入终点" in k]
    cc = [v for k, v in mks.items() if "corner2" in k]
    for nm, arr, key in (("孔口", mm, "hole_mouth"), ("插入终点", gg, "goal"), ("corner2 机位", cc, "cam_pos")):
        if not arr:
            bad.append("派生标记缺 %s" % nm)
            continue
        want = [float(v) for v in t[key]]
        if max(abs(a - b) for a, b in zip(arr[0]["pos"], want)) > 1e-6:
            bad.append("标记 %s %s ≠ episode 真值 %s %s" % (nm, arr[0]["pos"], key, want))
    n_wps = sum(len(x.get("waypoints") or []) for x in ov.get("trajectories", []))
    if n_wps < 20:
        bad.append("末端轨迹抽稀点太少 (%d)" % n_wps)
    if abs(float(o["episode"].get("cam_fovy", 0)) - float(t.get("cam_fovy", 0))) > 1e-6:
        bad.append("相机 fovy 与 episode 真值不一致")
    notes.append("episode 场景: %s · %d 帧 · seed=%s · success=%s · 机器人构件 %d · 相机 fovy=%s · 轨迹 %d 点 (帧龄 %.1fh)"
                 % (os.path.basename(t["npz"]), t["steps"], t.get("seed"), t.get("success"), n_robot,
                    t.get("cam_fovy"), n_wps, t["age_s"] / 3600))


def _rep(bad, ok_msg="") -> int:
    if bad:
        print("⛔ 仿真场景真源不一致:")
        for b in bad:
            print("  - %s" % b)
        return 1
    print(ok_msg)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="仿真场景真源 (画布 3D 视图的插拔光模块场景)")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--set", nargs=2, metavar=("KEY", "JSON"))
    ap.add_argument("--set-seed", type=int, metavar="N", help="episode 场景 (SS-EPI-CORNER) 的布局 seed")
    ap.add_argument("--export-episode", action="store_true", help="按 episode 自己的 metaworld 模型导出该场景 (含机器人)")
    ap.add_argument("--force", action="store_true", help="连同手工编辑一起覆盖 (配 --export-episode)")
    a = ap.parse_args()
    ensure_episode_scene()
    if a.export_episode:
        r = export_episode_truth(force=bool(a.force))
        print(("✅ " if r.get("ok") else "⛔ ") + str(r.get("msg")))
        return 0 if r.get("ok") else 1
    if a.set_seed is not None:
        r = set_seed(a.set_seed)
        print("✅ %s\n   重跑: %s" % (r["msg"], r["cmd"]))
        return check()
    if a.set:
        key, val = a.set
        d = load()
        sc = d["scenes"]["SIM-PEG-L4"]
        parts = key.split(".")
        cur = sc
        for p in parts[:-1]:
            cur = cur[int(p)] if (isinstance(cur, list) and p.isdigit()) else cur[p]
        last = parts[-1]
        newv = json.loads(val)
        if isinstance(cur, list) and last.isdigit():
            cur[int(last)] = newv
        else:
            cur[last] = newv
        save_raw(d)
        print("✅ 已写 %s = %s (备份在 %s)" % (key, newv, os.path.relpath(BACKUP, ROOT)))
        return check()
    if a.check:
        return check()
    d = load()
    sc = d["scenes"]["SIM-PEG-L4"]
    print("🧭 %s  (%s / %s / env=%s)" % (sc["name"], sc["kind"], sc["level"], sc.get("env")))
    print("   对象 %d · 标记 %d · 围栏 %d · 轨迹 %d   真源: %s"
          % (len(sc["objects"]), len(sc["markers"]), len(sc["fences"]), len(sc["trajectories"]),
             os.path.relpath(PATH, ROOT)))
    for o in sc["objects"]:
        print("   对象 %-24s c=%-22s s=%s" % (str(o["name"])[:24], o["center"], o["size"]))
    for m in sc["markers"]:
        print("   标记 %-24s pos=%s" % (str(m["name"])[:24], m["pos"]))
    print("   运行: %s %s" % (sc["runner"]["tool"], " ".join(sc["runner"]["args"])))
    return 0



# ─────────────── 场景管理器的写路径: 改的就是这份真源 (不是只改产物目录) ───────────────
_LIST = {"objects": "objects", "markers": "markers", "fences": "fences", "trajectories": "trajectories"}


def _find(sc: dict, kind: str, ident: str):
    for i, it in enumerate(sc.get(_LIST[kind]) or []):
        if str(it.get("name")) == str(ident) or str(it.get("id")) == str(ident):
            return i, it
    return None, None


def regen_scene_dir(scene_dir: str) -> None:
    """用真源重写场景目录文件 (供场景管理/3D 视图读)。"""
    os.makedirs(scene_dir, exist_ok=True)
    sid = os.path.basename(os.path.normpath(scene_dir))
    for fn, obj in (("objects3d.json", to_objects3d(sid)), ("overlay_spec.json", to_overlay(sid))):
        tmp = os.path.join(scene_dir, fn + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, os.path.join(scene_dir, fn))


def apply_patch(kind: str, ident: str, patch: dict, scene_id: str = "SIM-PEG-L4") -> dict:
    """把编辑器改动落到**真源**并重建场景目录。⇒ {"ok","msg","backup","entity"}"""
    d = load()
    sc = d["scenes"].get(scene_id)
    if sc is None:
        return {"ok": False, "msg": "真源里没有场景 %s" % scene_id}
    if kind not in _LIST:
        return {"ok": False, "msg": "不支持的类别 %r" % kind}
    i, it = _find(sc, kind, ident)
    if it is None:
        return {"ok": False, "msg": "真源里找不到 %s[%s]" % (kind, ident)}
    for k, v in (patch or {}).items():
        if kind == "fences" and k == "shape":
            sh = dict(it.get("shape") or {})
            sh.update(v or {})
            it["shape"] = sh
        elif k == "center" and kind == "fences":
            sh = dict(it.get("shape") or {})
            sh["center"] = v
            it["shape"] = sh
        else:
            it[k] = v
    save_raw(d)
    regen_scene_dir(os.path.join(ROOT, "data", "scene", "scenes", scene_id))
    if scene_id == EPI_SCENE:            # 手工改过就留痕: 之后再按模型重导不得静默覆盖
        sc["user_edited"] = True
        sc["user_edited_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        save_raw(d)
    return {"ok": True, "msg": "已写仿真场景真源 %s[%s]" % (kind, ident),
            "backup": os.path.relpath(BACKUP, ROOT), "entity": it}


def add_item(kind: str, data: dict, scene_id: str = "SIM-PEG-L4") -> dict:
    d = load()
    sc = d["scenes"].get(scene_id)
    if sc is None:
        return {"ok": False, "msg": "真源里没有场景 %s" % scene_id}
    lst = sc.setdefault(_LIST[kind], [])
    if any(str(x.get("name")) == str(data.get("name")) for x in lst):
        return {"ok": False, "msg": "真源里已有同名 %s" % data.get("name")}
    if kind == "fences":
        data = dict(data)
        c = data.pop("center", [0, 0, 0])
        sz = data.pop("size", [0.3, 0.3, 0.3])
        data["shape"] = {"center": c, "size": sz}
    if kind == "markers":
        data.setdefault("type", "自定义")
        data.setdefault("radius_m", 0.05)
    if kind == "trajectories":
        data.setdefault("kind", "自定义")
        if len(data.get("waypoints") or []) < 2:
            return {"ok": False, "msg": "轨迹至少 2 个航点"}
    lst.append(data)
    save_raw(d)
    regen_scene_dir(os.path.join(ROOT, "data", "scene", "scenes", scene_id))
    return {"ok": True, "msg": "真源新增 %s[%s]" % (kind, data.get("name")), "entity": data}


def del_item(kind: str, ident: str, scene_id: str = "SIM-PEG-L4") -> dict:
    d = load()
    sc = d["scenes"].get(scene_id)
    if sc is None:
        return {"ok": False, "msg": "真源里没有场景 %s" % scene_id}
    i, it = _find(sc, kind, ident)
    if it is None:
        return {"ok": False, "msg": "真源里找不到 %s[%s]" % (kind, ident)}
    sc[_LIST[kind]].pop(i)
    save_raw(d)
    regen_scene_dir(os.path.join(ROOT, "data", "scene", "scenes", scene_id))
    return {"ok": True, "msg": "真源删除 %s[%s]" % (kind, ident)}


def is_sim_scene(scene_id) -> bool:
    if not scene_id:
        return False
    try:
        return str(scene_id) in (load().get("scenes") or {})
    except Exception:                                                          # noqa: BLE001
        return False


def run_cmd(scene_id: str = "SIM-PEG-L4"):
    """⇒ (tool, args, eta_s, product, cwd, env) 运行这条仿真场景。"""
    sc = load()["scenes"][scene_id]
    r = sc.get("runner") or {}
    cwd = r.get("cwd") or "."
    env = {k: (ROOT if v == "<ROOT>" else v) for k, v in (r.get("env") or {}).items()}
    return (r.get("tool"), list(r.get("args") or []), int(r.get("eta_s") or 180),
            r.get("product"), os.path.join(ROOT, cwd), env)

# ══════════════════════════════════════════════════════════════════════════════
# 第二条仿真/回放场景: 状态空间 3D 分层视图 —— 与操作视频同源 (metaworld corner2 视角)
#   老倪 2026-10-10: 「状态空间3D分层视图 与操作视频同源 metaworld corner 视角, 这个场景哪去了?
#                     你能看到我正在运行的这个场景么? 把这个场景做进可编辑场景」
#   这条场景的几何**不另存一份**, 而是从同源 episode 对 (npz+mp4) 的真值派生 ——
#   派生即同源: episode 一换 (重跑/换 seed), 场景跟着变, 不存在"画的和跑的不是一条"。
#   `reports/ss_episode_latest.mp4` 这个别名是**两个跑法共用**的 (同源生成器 + L4 演示 --also-latest),
#   所以挑对时先认 latest, 错位 (>30s) 就退到自洽的带时间戳对 (与 ss_dreamview.resolve_episode_npz 同一口径)。
# ══════════════════════════════════════════════════════════════════════════════
EPI_SCENE = "SS-EPI-CORNER"
EPI_TOOL = "tools/gen_ss_metaworld_episode.py"
EPI_CAM = "corner2"
# metaworld 夹具 (peg_block.xml) 外廓: x ±0.095 / y ±0.1 / z 0~0.2 ⇒ 中心 (0,0,0.1)
BLOCK_HALF = (0.095, 0.10, 0.10)


def episode_scene_def() -> dict:
    """SS-EPI-CORNER 的场景定义 (真源里的第二条; 几何 from episode)。"""
    return {
        "name": "状态空间 3D 分层视图 · 与操作视频同源 (metaworld corner2 视角)",
        "kind": "episode",
        "level": "L3/L4",
        "env": "metaworld peg-insert-side-v3 · 状态空间六层直驱 (同源 episode)",
        "camera": {"name": EPI_CAM, "source": "episode meta 真值 (cam_pos/fwd/right/up/fovy; 视频相机外参精确对齐)",
                   "yaw_deg": 328.4, "elev_deg": 28.9,
                   "note": "视频相机 = metaworld corner2 (probe_video_view.py 实测换算)"},
        "derive": {"from": "reports/ss_episode_*.npz (同源对, 自动挑自洽的一对)",
                   "objects": "台面/光模块/夹具 由 episode 真值 (peg0/hole_mouth/goal) + metaworld 几何推得",
                   "trajectory": "episode 末端轨迹 tr['x'] 抽稀 (每 20 帧 → 约 42 点)",
                   "why": "派生即同源: 不另存一份几何, episode 换 → 场景跟着变"},
        "runner": {"tool": EPI_TOOL, "args": ["--seed", 0],
                   "alt": "画布(C) → 🧭 3D 视图 (同一个窗口实时看这条 episode)",
                   "cwd": "tools",
                   "env": {"MUJOCO_GL": "egl", "MUJOCO_EGL_DEVICE": "0", "PYTHONIOENCODING": "utf-8",
                           "ZMAX_L4_ROOT": "<ROOT>"},
                   "note": "重跑同源对 (npz+mp4 同一次运行写出) ⇒ 3D 分层视图与操作视频永远同源",
                   "eta_s": 120, "product": "reports/ss_episode_latest.npz"},
        "edit": {"seed": {"label": "布局 seed (metaworld 随机化布局的唯一真旋钮)",
                          "effect": "改它 → 下一轮 episode 的 peg/孔位真的变 (实测 seed 0/1 的 peg0 不同)"},
                 "objects": {"effect": "只改回放视图的显示位置; 下一轮由 episode 真值覆盖 (不谎报生效)"}},
        "seed": 0,
        "source": "tools/gen_ss_metaworld_episode.py (状态空间六层直驱 metaworld, 一条 episode 出 trace+mp4)",
        "objects": [], "markers": [], "fences": [], "trajectories": [],   # 几何是派生的, 不存这里
    }


def ensure_episode_scene() -> bool:
    """把 SS-EPI-CORNER 补进真源 (幂等); ⇒ 是否新写入。"""
    d = load()
    if EPI_SCENE in d["scenes"]:
        return False
    d["scenes"][EPI_SCENE] = episode_scene_def()
    save_raw(d)
    return True


def _pair_age(p: str) -> float:
    m = os.path.splitext(p)[0] + ".mp4"
    return abs(os.path.getmtime(p) - os.path.getmtime(m)) if os.path.isfile(m) else 1e9


def resolve_episode_pair() -> tuple:
    """同源 episode 对 (与 ss_dreamview.resolve_episode_npz 同口径, 但不 import Qt)
    ⇒ (npz 路径, 说明); 找不到返回 (None, 原因)。"""
    rep = os.path.join(ROOT, "reports")
    lat = os.path.join(rep, "ss_episode_latest.npz")
    if os.path.isfile(lat) and _pair_age(lat) <= 30:
        return lat, "latest 别名对 (自洽)"
    cand = [p for p in sorted(glob.glob(os.path.join(rep, "ss_episode_*.npz")))
            if os.path.basename(p) != "ss_episode_latest.npz" and _pair_age(p) <= 30]
    if cand:
        return max(cand, key=os.path.getmtime), "自洽的带时间戳对 (latest 别名被别的跑法覆盖了)"
    return (lat if os.path.isfile(lat) else None), "没有自洽的 npz+mp4 对"


def episode_truth() -> dict:
    """读同源 pair 的真值 → dict(pair, npz, mp4, meta..., traj)。"""
    npz, why = resolve_episode_pair()
    if not npz or not os.path.isfile(npz):
        return {"ok": False, "msg": why}
    try:
        z = np.load(npz, allow_pickle=True)
        meta = dict(z["meta"][0])
        traj = np.asarray(z["x"], float) if "x" in z.files else np.zeros((0, 3))
        out = {"ok": True, "why": why, "npz": npz, "mp4": os.path.splitext(npz)[0] + ".mp4",
               "steps": int(len(traj)), "traj": traj}
        for k in ("seed", "success", "stage_final", "cam_pos", "cam_fwd", "cam_right", "cam_up", "cam_fovy",
                  "peg0", "hole_mouth", "goal", "qpos", "box_center", "table_center"):
            if k in meta:
                out[k] = meta[k]
        out["age_s"] = max(0.0, time.time() - os.path.getmtime(npz))
        out["hand0"] = [float(v) for v in (traj[0] if len(traj) else (0, 0, 0))]   # tr['x'][0] = 手爪 body 位
        return out
    except Exception as e:                                                  # noqa: BLE001
        return {"ok": False, "msg": "读 %s 失败: %r" % (os.path.basename(npz), e)}


def _epi_layout(t: dict) -> dict:
    """从 episode 真值派生几何: 光模块(初始位)/孔口/插入终点/夹具(由孔口+夹具外廓推得)。"""
    peg0 = [float(v) for v in t.get("peg0", [0, 0, 0])]
    mouth = [float(v) for v in t.get("hole_mouth", [0, 0, 0])]
    goal = [float(v) for v in t.get("goal", [0, 0, 0])]
    # 光模块 (metaworld peg 本体: box 0.03×0.03×0.24 半尺寸见 XML geom size="0.015 0.015 0.12")
    # 插入沿 -x (goal.x < mouth.x) ⇒ 夹具近端面 = 孔口, 中心 = 孔口 ∓ 半宽
    sgn = -1.0 if goal[0] <= mouth[0] else 1.0
    blk = [mouth[0] - sgn * BLOCK_HALF[0], mouth[1], BLOCK_HALF[2]]
    return {"peg0": peg0, "mouth": mouth, "goal": goal, "block": blk, "sgn": sgn}


def _epi_objects3d() -> dict:
    t = episode_truth()
    _sc = (load()["scenes"].get(EPI_SCENE) or {})
    if t.get("ok") and (_sc.get("objects") or []):
        # 已按 metaworld 模型导出过 (含机器人本体) ⇒ 直接透传, 不再用 meta 三件套
        objs = []
        for i, o in enumerate(_sc["objects"]):
            d = {"id": o.get("id") or ("ep_ob_%02d" % (i + 1)), "name": o["name"],
                 "center": [float(x) for x in o["center"]], "size": [float(x) for x in o["size"]],
                 "source": o.get("source", ""), "editable": True}
            for k in ("color", "part"):
                if o.get(k) is not None:
                    d[k] = o[k]
            objs.append(d)
        return {"format": "zmax-scene-objects3d", "version": "1.0", "scene_id": EPI_SCENE,
                "coord": "世界系 m (metaworld sawyer_xyz)", "sim": True, "kind": "episode",
                "source": "按 episode 自己的 metaworld 模型导出 (与 3D 分层视图/操作视频同一模型)",
                "scene_name": _sc.get("name"), "truth": _sc.get("truth"),
                "episode": {"npz": os.path.relpath(t["npz"], ROOT), "step_count": t["steps"],
                            "seed": t.get("seed"), "success": bool(t.get("success")),
                            "stage_final": t.get("stage_final"), "age_s": round(t["age_s"], 1),
                            "why": t["why"], "camera": [float(v) for v in t.get("cam_pos", [0, 0, 0])],
                            "cam_fovy": float(t.get("cam_fovy", 60.0))},
                "objects": objs, "markers": _sc.get("markers") or [],
                "fences": _sc.get("fences") or [], "trajectories": _sc.get("trajectories") or []}
    if not t.get("ok"):
        return {"format": "zmax-scene-objects3d", "version": "1.0", "scene_id": EPI_SCENE,
                "error": t.get("msg"), "objects": []}
    L = _epi_layout(t)
    objs = [
        {"id": "epi_ob_01", "name": "工作台面 (metaworld table)", "center": [0.0, 0.0, -0.027],
         "size": [0.8, 0.8, 0.054], "source": "metaworld table.xml (顶面 z=0)", "editable": True},
        {"id": "epi_ob_02", "name": "光模块 (peg · 初始位)", "center": L["peg0"],
         "size": [0.03, 0.03, 0.24], "source": "episode meta.peg0 (真值)", "editable": True},
        {"id": "epi_ob_03", "name": "夹具/孔座 (peg_block)", "center": L["block"],
         "size": [2 * BLOCK_HALF[0], 2 * BLOCK_HALF[1], 2 * BLOCK_HALF[2]],
         "source": "孔口真值 hole_mouth − 夹具外廓半宽 0.095 (推得)", "editable": True},
    ]
    cam = [float(v) for v in t.get("cam_pos", [0, 0, 0])]
    return {"format": "zmax-scene-objects3d", "version": "1.0", "scene_id": EPI_SCENE,
            "coord": "世界系 m (metaworld sawyer_xyz)", "sim": True, "kind": "episode",
            "source": "同源 episode 真值派生: %s" % os.path.basename(t["npz"]),
            "scene_name": load()["scenes"].get(EPI_SCENE, episode_scene_def())["name"],
            "episode": {"npz": os.path.relpath(t["npz"], ROOT), "step_count": t["steps"], "seed": t.get("seed"),
                        "success": bool(t.get("success")), "stage_final": t.get("stage_final"),
                        "age_s": round(t["age_s"], 1), "why": t["why"], "camera": cam,
                        "cam_fovy": float(t.get("cam_fovy", 60.0))},
            "objects": objs}


def _epi_overlay() -> dict:
    t = episode_truth()
    if not t.get("ok"):
        return {"format": "zmax-scene-overlay-spec", "version": "1.0", "scene_id": EPI_SCENE, "markers": []}
    L = _epi_layout(t)
    cam = [float(v) for v in t.get("cam_pos", [0, 0, 0])]
    mk = [
        {"id": "epi_mk_01", "name": "孔口 (hole_mouth)", "pos": L["mouth"], "type": "检查点", "radius_m": 0.012,
         "source": "episode meta 真值"},
        {"id": "epi_mk_02", "name": "插入终点 (goal)", "pos": L["goal"], "type": "检查点", "radius_m": 0.010,
         "source": "episode meta 真值 (孔深 0.066 ⇒ 终点比孔口深)"},
        {"id": "epi_mk_03", "name": "corner2 相机机位 (操作视频视角)", "pos": cam, "type": "工位", "radius_m": 0.02,
         "source": "episode meta.cam_pos (与 mp4 同源)"},
    ]
    tr = t["traj"]
    wps = [{"pos": [float(x) for x in p]} for p in tr[::20]] if len(tr) else []
    trajs = [{"id": "epi_tr_01", "name": "episode 末端轨迹 (抽稀 20×)", "kind": "示教",
              "waypoints": wps, "source": "episode tr['x'] 每 20 帧取 1 (共 %d 帧 → %d 点)" % (len(tr), len(wps))}]
    fens = [{"id": "epi_fn_01", "kind": "box",
             "shape": {"center": [0.0, 0.0, 0.1], "size": [0.8, 0.8, 0.2]},
             "name": "作业区 (台面上方)", "source": "metaworld 台面 0.8×0.8"}]
    _sc = load()["scenes"].get(EPI_SCENE) or episode_scene_def()
    return {"format": "zmax-scene-overlay-spec", "version": "1.0", "scene_id": EPI_SCENE,
            "sim": True, "kind": "episode", "scene_name": _sc.get("name"),
            "run": _sc.get("runner"),                      # 场景管理读它决定 ▶ 能不能点/跑什么
            "seed": _sc.get("seed"), "edit": _sc.get("edit"),
            "source": "同源 episode 真值派生", "markers": mk, "fences": fens, "trajectories": trajs}


def set_seed(seed: int) -> dict:
    """改 episode 场景的布局 seed (真旋钮: 下一轮 episode 的布局真的跟着变)。"""
    d = load()
    sc = d["scenes"].get(EPI_SCENE)
    if sc is None:
        d["scenes"][EPI_SCENE] = episode_scene_def()
        sc = d["scenes"][EPI_SCENE]
    old = sc.get("seed")
    sc["seed"] = int(seed)
    (sc.setdefault("runner", {}))["args"] = ["--seed", int(seed)]
    sc["runner"]["note"] = ("重跑同源对 (npz+mp4 同一次运行写出); 布局由 seed=%d 决定" % int(seed))
    save_raw(d)
    regen_scene_dir(os.path.join(ROOT, "data", "scene", "scenes", EPI_SCENE))
    return {"ok": True, "old": old, "new": int(seed),
            "cmd": "cd %s && %s %s" % (os.path.join(ROOT, "tools"), EPI_TOOL, "--seed %d" % int(seed)),
            "msg": "seed %s → %d (下一轮 episode 布局随之改变)" % (old, int(seed))}



# ══════════════════════════════════════════════════════════════════════════════
# 真几何导出: 插拔场景对齐 metaworld 真模型 (2026-10-10 老倪: 「你的场景，需要对齐 metaworld 的
# 场景渲染…做成可编辑的场景；现在已有的场景是插拔场景，和上下料场景；其它场景先不用搞」)
#   手写几何会跟模型跑偏 (实测两处真错: 台面我写 0.8×0.8 实为 1.4×0.8 且中心在 y=0.6;
#   光模块我按 metaworld stock 写 40×40 方截面, 实际模型是 40×16mm 矩形截面) ⇒
#   改成**从 MuJoCo 模型直接导出**: 遍历 geom, 取 body_pos+geom_pos 与 2×geom_size, 单位 m。
#   机械臂本体 (shoulder/upper_arm/forearm/wrist/hand/gripper/pedestal...) 不进场景对象;
#   场景设备 (台面/护栏/光模块/夹具/转台/压电台/微动台) 全进, 名字用真实 body+geom 名, 标中文别名。
# ══════════════════════════════════════════════════════════════════════════════
# 只滤掉"不是场景内容"的东西 (世界/地面/动作捕捉标记); **机器人本体一律保留** —— 老倪:
# 「为什么你现在的场景，没有机器人呢？metaworld 的场景都是有机器人的，增加机器人」(2026-10-10)
_MJ_SKIP = ("world", "floor", "mocap")
_MJ_ROBOT = {                     # 机器人本体: body 名前缀 → 中文名 (Sawyer 7 自由度 + 平行夹爪)
    "pedestal_feet": "机器人·底座脚", "pedestal": "机器人·立柱", "torso": "机器人·躯干",
    "controller_box": "机器人·控制箱", "screen": "机器人·示教屏", "head": "机器人·头部",
    "right_arm_base_link": "机器人·臂基座", "right_l0": "机器人·肩部", "right_l1": "机器人·大臂",
    "right_l2": "机器人·肘/小臂", "right_l3": "机器人·腕1", "right_l4": "机器人·腕2",
    "right_l5": "机器人·腕3", "right_l6": "机器人·手", "right_hand": "机器人·腕法兰",
    "hand": "机器人·腕部导轨", "rightclaw": "机器人·夹爪右", "rightpad": "机器人·夹爪垫右",
    "leftclaw": "机器人·夹爪左", "leftpad": "机器人·夹爪垫左",
}
_MJ_ROBOT_RGBA = [0.82, 0.84, 0.87]      # Sawyer 浅灰 (与台面/工件的青绿/金区分开)
_MJ_ALIAS = {"tablelink": "工作台面", "RetainingWall": "台面护栏", "peg": "光模块 (peg)",
             "box": "夹具/孔座 (peg_block)", "turntable": "来料转台 (外力旋转90°)",
             "coupler": "光耦合压电台底座", "cp_stage_b": "x-y 压电微动载物台",
             "tt_disc": "转台盘面", "tt_ring": "转台刻度环", "tt_mark1": "转台十字刻度",
             "cp_base": "压电台基座", "cp_pzt_a": "压电陶瓷 A", "cp_pzt_b": "压电陶瓷 B",
             "cp_fiber": "光纤头耦合基准", "cp_stage": "微动载物台面", "cp_scale": "位移标尺"}
_MJ_TIP = ("对齐 metaworld 真模型: 从 MuJoCo 模型 (sawyer_peg_insertion_side_l4.xml) 导出 geom "
           "位置/尺寸 (单位 m, size=2×geom_size); 与 ▶运行 时物理世界逐字同源")


def export_episode_truth(scene_id: str = EPI_SCENE, seed=None, write: bool = True, force: bool = False) -> dict:
    """把「3D 分层视图 / 与操作视频同源」那条场景**按它自己的物理模型**导出 (含机器人本体)。

    老倪 2026-10-10: 「你先把当前我运行的场景，先复制过来，一模一样的」+「为什么没有机器人? metaworld 的
    场景都是有机器人的」 ⇒ 不再只派生 3 个对象, 而是建**同一个 metaworld 环境** (同 seed ⇒ 同布局),
    mj_forward 后遍历 geom 取世界系 AABB (机器人本体保留) —— 模型与 3D 视图/操作视频逐字同源。
    """
    t = episode_truth()
    if not t.get("ok"):
        return {"ok": False, "msg": "同源 episode 读不到: %s" % t.get("msg")}
    if seed is None:
        seed = int(t.get("seed", 0) or 0)
    try:
        os.environ.setdefault("MUJOCO_GL", "egl")
        import metaworld
        import mujoco
    except Exception as e:                                                      # noqa: BLE001
        return {"ok": False, "msg": "metaworld/mujoco 不可用: %r" % e}
    try:
        # ⚠️ 必须走 episode 生成器的**同一条建环境路径** (metaworld 的随机布局吃全局 np.random,
        #    自建 env 会因 RNG 消耗顺序不同而给出**另一个布局** —— 实测差 5cm 以上)。
        import train_full_pipeline as _TFP          # noqa: F401  (其 import 期就建了一次 env, 顺序要对齐)
        from train_full_pipeline import make_env
        env = make_env(seed)
        m, d = env.model, env.data
        # ⚠️ 回放 episode **首帧的模型状态** (meta.qpos): metaworld 的随机化布局吃全局 np.random,
        #    重新 make_env 得到的是**另一个布局** (实测 peg 差 5~7cm) ⇒ 必须用存下来的 qpos 复原,
        #    这样光模块/孔座/机器人位形与视频首帧逐字一致 ("一模一样"必须是同一帧, 不是"同一个 seed")。
        _q = list(t.get("qpos") or [])
        _replay = bool(_q) and len(_q) == int(m.nq)
        if _replay:
            d.qpos[:] = [float(v) for v in _q]
            d.qvel[:] = 0.0
        mujoco.mj_forward(m, d)
    except Exception as e:                                                      # noqa: BLE001
        return {"ok": False, "msg": "建 metaworld 环境失败: %r" % e}
    objs, seen = [], {}
    MESH = int(mujoco.mjtGeom.mjGEOM_MESH)
    for g in range(m.ngeom):
        b = int(m.geom_bodyid[g])
        bn = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, b) or ""
        gn = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, g) or ""
        if any(bn.startswith(x) for x in _MJ_SKIP):
            continue
        R = np.asarray(d.geom_xmat[g]).reshape(3, 3)
        xp = np.asarray(d.geom_xpos[g], float)
        if int(m.geom_type[g]) == MESH and int(m.geom_dataid[g]) >= 0:
            mid = int(m.geom_dataid[g])
            va, vn = int(m.mesh_vertadr[mid]), int(m.mesh_vertnum[mid])
            pts = (R @ np.asarray(m.mesh_vert[va:va + vn], float).T).T + xp
        else:
            sz = [float(v) for v in m.geom_size[g]]
            tt = int(m.geom_type[g])
            if tt == 2:
                hx = hy = hz = sz[0]
            elif tt in (3, 5):
                hx, hy, hz = sz[0], sz[0], sz[1]
            else:
                hx, hy, hz = sz[0], sz[1], sz[2]
            pts = (R @ np.array([[-hx, -hy, -hz], [hx, hy, hz]], float).T).T + xp
        lo, hi = pts.min(0), pts.max(0)
        pos = [float(v) for v in (lo + hi) / 2]
        size = [float(v) for v in (hi - lo)]
        if max(size) > 1.0 and pos[2] < -0.1:
            continue
        _rb = next((v for k, v in _MJ_ROBOT.items() if bn.startswith(k)), None)
        nm = _rb or _MJ_ALIAS.get(gn) or _MJ_ALIAS.get(bn) or ("夹具/孔座 (peg_block)" if not bn else bn)
        _c = seen.get(nm, 0) + 1
        seen[nm] = _c
        if _c > 1:
            nm = "%s #%d" % (nm, _c)
        o = {"id": "ep_ob_%02d" % (len(objs) + 1), "name": nm, "center": [round(v, 4) for v in pos],
             "size": [round(max(0.004, v), 4) for v in size], "editable": True,
             "source": "metaworld 环境实测 (seed=%d body=%s geom=%s)" % (seed, bn or "(无名)", gn or "-")}
        if _rb:
            o["color"] = list(_MJ_ROBOT_RGBA)
            o["part"] = "robot"
            o["source"] = "metaworld 环境实测 · 机器人本体 (seed=%d body=%s)" % (seed, bn)
        objs.append(o)
    sites = []
    for i in range(m.nsite):
        sn = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_SITE, i) or ""
        if sn:
            sites.append({"name": sn, "pos": [round(float(v), 4) for v in d.site_xpos[i]]})
    keep = ("hole", "pegGrasp", "goal", "cp_ref")
    mk = [{"id": "ep_mk_%02d" % (i + 1), "name": "site:%s" % st["name"], "type": "检查点",
           "pos": st["pos"], "radius_m": 0.012, "source": "metaworld 环境 site 真值 (seed=%d)" % seed}
          for i, st in enumerate([x for x in sites if x["name"] in keep])]
    cam = [float(v) for v in t.get("cam_pos", [0, 0, 0])]
    if cam:
        mk.append({"id": "ep_mk_cam", "name": "corner2 相机机位 (操作视频视角)", "type": "工位", "pos": cam,
                   "radius_m": 0.02, "source": "episode meta.cam_pos (与 mp4 同源)"})
    # 轨迹: episode 末端 tr['x'] 抽稀 (3D 视图里那条线的同源数据)
    tr = t["traj"]
    wps = [{"pos": [float(x) for x in p]} for p in tr[::20]] if len(tr) else []
    trajs = [{"id": "ep_tr_01", "name": "episode 末端轨迹 (抽稀 20×)", "kind": "示教", "waypoints": wps,
              "source": "episode tr['x'] %d 帧 → %d 点" % (len(tr), len(wps))}] if wps else []
    fens = [{"id": "ep_fn_01", "kind": "box", "shape": {"center": [0.0, 0.6, 0.1], "size": [1.4, 0.8, 0.2]},
             "name": "作业区 (台面上方)", "source": "metaworld 台面 1.4×0.8 (中心 y=0.6)"}]
    if write:
        d2 = load()
        sc = d2["scenes"].setdefault(scene_id, episode_scene_def())
        if sc.get("user_edited") and not force:
            # ⚠️ 手工编辑过的对象不允许被"模型重导"静默覆盖 (否则老倪改完一重建就没了)
            return {"ok": False, "msg": "3D场景已被手工编辑过 (%s), 未覆盖 —— 要按模型重导请加 --force"
                                        % str(sc.get("user_edited_at") or "")[:19]}
        sc["objects"], sc["markers"], sc["fences"], sc["trajectories"] = objs, mk, fens, trajs
        _aux = {}
        for _bn in ("peg", "hand", "box"):
            _i = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_BODY, _bn)
            if _i >= 0:
                _aux["body_" + _bn] = [round(float(v), 6) for v in d.xpos[_i]]
        for _sn in ("pegGrasp", "hole", "goal", "pegHead", "pegEnd"):
            _i = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_SITE, _sn)
            if _i >= 0:
                _aux["site_" + _sn] = [round(float(v), 6) for v in d.site_xpos[_i]]
        sc["truth"] = {"from": "metaworld peg-insert-side-v3 环境 (seed=%d, 与 3D 分层视图/操作视频同一模型)" % seed,
                       "episode": os.path.basename(t["npz"]), "n_objects": len(objs),
                       "n_robot": len([o for o in objs if o.get("part") == "robot"]), "anchors": _aux,
                       "qpos_replayed": bool(_replay),
                       "camera": {"name": EPI_CAM, "fovy": float(t.get("cam_fovy", 60.0)), "pos": cam,
                                  "note": "视频/3D 视图相机 = corner2 (外参取自 episode meta)"}}
        sc["seed"] = seed
        save_raw(d2)
        regen_scene_dir(os.path.join(ROOT, "data", "scene", "scenes", scene_id))
    return {"ok": True, "seed": seed, "objects": objs, "markers": mk, "n_robot": len([o for o in objs if o.get("part") == "robot"]),
            "msg": "%d geom → %d 对象 (机器人 %d) · %d 标记 · 轨迹 %d 点 (seed=%d, 首帧状态回放=%s)"
                   % (m.ngeom, len(objs), len([o for o in objs if o.get("part") == "robot"]), len(mk), len(wps),
                      seed, "✅" if _replay else "❌ (meta 无 qpos)")}


def l4_xml_path() -> str:
    """找到 L4 场景 XML (画布 ▶运行 用的同一份; 先按 metaworld 包位置找, 再兜底常见路径)。"""
    cands = []
    try:
        import metaworld
        cands.append(os.path.join(os.path.dirname(metaworld.__file__), "assets", "sawyer_xyz",
                                  "sawyer_peg_insertion_side_l4.xml"))
    except Exception:                                                           # noqa: BLE001
        pass
    cands += [os.path.join(ROOT, "gui-venv311/lib/python3.11/site-packages/metaworld/assets/sawyer_xyz",
                           "sawyer_peg_insertion_side_l4.xml")]
    for c in cands:
        if os.path.isfile(c):
            return c
    return ""


def export_mujoco_truth(scene_id: str = "SIM-PEG-L4", write: bool = True) -> dict:
    """从 MuJoCo 真模型导出场景几何 → 真源 objects/markers; ⇒ dict(ok, xml, objects, markers, msg)。"""
    xml = l4_xml_path()
    if not xml:
        return {"ok": False, "msg": "找不到 L4 场景 XML (先跑 tools/gen_l4_demo_scene.py 生成)"}
    try:
        os.environ.setdefault("MUJOCO_GL", "egl")
        import mujoco
    except Exception as e:                                                      # noqa: BLE001
        return {"ok": False, "msg": "mujoco 不可用: %r" % e}
    m = mujoco.MjModel.from_xml_path(xml)
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)                                  # 正运动学 ⇒ d.geom_xpos 是**世界系**坐标
    objs, seen = [], {}
    MESH = int(mujoco.mjtGeom.mjGEOM_MESH)
    for g in range(m.ngeom):
        b = int(m.geom_bodyid[g])
        bn = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_BODY, b) or ""
        gn = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, g) or ""
        if any(bn.startswith(x) for x in _MJ_SKIP):
            continue
        R = np.asarray(d.geom_xmat[g]).reshape(3, 3)
        xp = np.asarray(d.geom_xpos[g], float)
        if int(m.geom_type[g]) == MESH and int(m.geom_dataid[g]) >= 0:
            mid = int(m.geom_dataid[g])
            va, vn = int(m.mesh_vertadr[mid]), int(m.mesh_vertnum[mid])
            V = np.asarray(m.mesh_vert[va:va + vn], float)
            pts = (R @ V.T).T + xp
        else:
            sz = [float(v) for v in m.geom_size[g]]
            t = int(m.geom_type[g])
            if t == 2:                                       # sphere: size=[r]
                hx = hy = hz = sz[0]
            elif t in (3, 5):                                # capsule/cylinder: size=[r, half-length]
                hx, hy, hz = sz[0], sz[0], sz[1]
            else:                                            # box: size=[hx,hy,hz]
                hx, hy, hz = sz[0], sz[1], sz[2]
            sx = np.array([[-hx, -hy, -hz], [hx, hy, hz]])
            pts = (R @ sx.T).T + xp
        lo, hi = pts.min(0), pts.max(0)
        pos = [float(v) for v in (lo + hi) / 2]
        size = [float(v) for v in (hi - lo)]
        if max(size) > 1.0 and pos[2] < -0.1:      # 台面以下的台体大块 (从上看不见, 不必进场景)
            continue
        _rb = next((v for k, v in _MJ_ROBOT.items() if bn.startswith(k)), None)
        nm = _rb or _MJ_ALIAS.get(gn) or _MJ_ALIAS.get(bn) or ("夹具/孔座 (peg_block)" if not bn else bn)
        _c = seen.get(nm, 0) + 1              # ⚠️ 按**名字**去重: 同名会让编辑器按名查找打到别人身上
        seen[nm] = _c
        if _c > 1:
            nm = "%s #%d" % (nm, _c)
        o = {"id": "mj_%02d" % (len(objs) + 1), "name": nm, "center": [round(v, 4) for v in pos],
             "size": [round(max(0.004, v), 4) for v in size],
             "source": "MuJoCo 模型实测 (body=%s geom=%s · 世界系 AABB)" % (bn or "(夹具内部无名体)", gn or "-"),
             "editable": True}
        if _rb:
            o["color"] = list(_MJ_ROBOT_RGBA)
            o["part"] = "robot"
            o["source"] = "MuJoCo 模型实测 · 机器人本体 (body=%s geom=%s)" % (bn, gn or "-")
        objs.append(o)
    # site 真值 → 标记 (孔口/抓取点/目标) — 物理世界就在这些点上做插入
    sites = []
    for i in range(m.nsite):
        sn = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_SITE, i) or ""
        if not sn:
            continue
        pos = [round(float(v), 4) for v in d.site_xpos[i]]
        sites.append({"name": sn, "pos": pos})
    keep = ("hole", "pegGrasp", "goal", "insert", "cp_ref", "cp_stage_top", "tt_top")
    mk = []
    for i, st in enumerate([x for x in sites if x["name"] in keep]):
        mk.append({"id": "mj_mk_%02d" % (i + 1), "name": "site:%s" % st["name"], "type": "检查点",
                   "pos": st["pos"], "radius_m": 0.012, "source": "MuJoCo site 真值"})
    if write:
        d = load()
        sc = d["scenes"].setdefault(scene_id, default()["scenes"]["SIM-PEG-L4"])
        sc["objects"] = objs
        _keep = [m for m in (sc.get("markers") or []) if "AOI" in str(m.get("name", ""))]
        sc["markers"] = mk + _keep
        sc["truth"] = {"from": "MuJoCo 模型 %s" % os.path.basename(xml), "n_objects": len(objs),
                       "tip": _MJ_TIP}
        save_raw(d)
        regen_scene_dir(os.path.join(ROOT, "data", "scene", "scenes", scene_id))
    return {"ok": True, "xml": xml, "objects": objs, "markers": mk,
            "msg": "%d 个 geom → %d 个场景对象 · %d 个 site 标记 (从 %s)"
                   % (m.ngeom, len(objs), len(mk), os.path.basename(xml))}


if __name__ == "__main__":
    sys.exit(main())
