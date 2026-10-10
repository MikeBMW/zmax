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
import json
import os
import re
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
                "runner": {"tool": "tools/gen_l4_demo_video.py", "args": ["--seed", "104"],
                           "alt": "tools/gui/state_space_sim_real.py (画布 ▶运行, 同引擎)",
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
    """给生成器用的几何 (与老常量同名, 便于最小改动接入)。"""
    sc = load()["scenes"]["SIM-PEG-L4"]
    by = {str(o["name"]): o for o in sc["objects"]}
    mk = {str(m["name"]): m for m in sc["markers"]}

    def _obj(sub):
        return [o for o in sc["objects"] if sub in str(o["name"])][0]

    tt, cp, st = _obj("转台"), _obj("压电台底座"), _obj("微动载物台")
    return {
        "turntable": {"xy": [float(tt["center"][0]), float(tt["center"][1])],
                      "pos": [float(tt["center"][0]), float(tt["center"][1]), float(tt["center"][2])],
                      "r": float(tt["size"][0]) / 2.0,
                      "z_top": float(tt["center"][2]) + float(tt["size"][2]) / 2.0,
                      # TURNTABLE_Z 语义 = peg 坐盘面 = 标记「来料位」的 z
                      "feed_z": float(mk["来料位 (转台中心)"]["pos"][2])},
        "coupler": {"xy": [float(cp["center"][0]), float(cp["center"][1])],
                    "pos": [float(cp["center"][0]), float(cp["center"][1]), float(cp["center"][2])],
                    # ⚠️ XML <body cp_stage_b pos="x y Z"> 的 Z 是 body 原点; 载物台盒在其内局部 z=+0.004,
                    #    真源记的是台面中心 ⇒ body Z = 台面中心 − 0.004 (物理不变)
                    "stage_z": round(float(st["center"][2]) - 0.004, 4),
                    "stage_center_z": float(st["center"][2]),
                    "ref": mk["光纤头耦合基准"]["pos"]},
        "aoi_focus": [float(x) for x in mk["AOI 镜头对焦点"]["pos"]],
        "aoi_hover": float(mk["AOI 镜头对焦点"]["radius_m"]),
        "insert_depth_m": float(sc["peg"]["insert_depth_m"]),
        "objects_by_name": by, "markers_by_name": mk,
    }


def to_objects3d() -> dict:
    sc = load()["scenes"]["SIM-PEG-L4"]
    objs = []
    for i, o in enumerate(sc["objects"]):
        objs.append({"id": "sim_ob_%02d" % (i + 1), "name": o["name"], "center": [float(x) for x in o["center"]],
                     "size": [float(x) for x in o["size"]], "source": o.get("source", ""), "editable": True})
    return {"format": "zmax-scene-objects3d", "version": "1.0", "scene_id": "SIM-PEG-L4",
            "coord": "世界系 m (metaworld sawyer_xyz)", "source": "data/scene/sim/sim_scenes.json (仿真场景真源)",
            "scene_name": sc["name"], "sim": True, "env": sc.get("env"), "level": sc.get("level"),
            "objects": objs}


def to_overlay() -> dict:
    sc = load()["scenes"]["SIM-PEG-L4"]
    mk = []
    for i, m in enumerate(sc["markers"]):
        mk.append({"id": "sim_mk_%02d" % (i + 1), "name": m["name"], "type": m.get("type", "自定义"),
                   "pos": [float(x) for x in m["pos"]], "radius_m": float(m.get("radius_m", 0.05)),
                   "source": m.get("source", ""), "editable": True})
    fn = []
    for i, f in enumerate(sc["fences"]):
        c = [float(x) for x in f["center"]]
        s = [float(x) for x in f["size"]]
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
        # TURNTABLE_Z 的语义是"peg 坐盘面"(盘顶 z + peg 半厚)，对应真源标记「来料位」的 z
        _feed_z = g["markers_by_name"]["来料位 (转台中心)"]["pos"][2]
        if _ttz is not None and abs(float(_ttz) - float(_feed_z)) > 1e-4:
            bad.append("TURNTABLE_Z 生成器=%.4f ≠ 真源 来料位 z=%.4f" % (float(_ttz), float(_feed_z)))
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
    return _rep(bad, "✅ 仿真场景真源 ↔ 生成器 ↔ XML 注入 三处一致 (%s)"
                % os.path.relpath(PATH, ROOT))


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
    a = ap.parse_args()
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


if __name__ == "__main__":
    sys.exit(main())

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
    for fn, obj in (("objects3d.json", to_objects3d()), ("overlay_spec.json", to_overlay())):
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
    """⇒ (tool, args, eta_s, product) 运行这条仿真场景。"""
    sc = load()["scenes"][scene_id]
    r = sc.get("runner") or {}
    return (r.get("tool"), list(r.get("args") or []), int(r.get("eta_s") or 180), r.get("product"))
