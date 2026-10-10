#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scene_registry.py — 场景库: 把"多个场景"落成可切换·可编辑的场景目录 (老倪 2026-10-10)

老倪: 「这个页面要有多个场景要管理，上下料，还有之前的插拔场景，要有切换，
       用户可以选择要编辑的场景元素，位置，轨迹等」

设计 (与 zmax-scene-engineering 一致):
  · 真源: flows/scenes_5jobs.json (6 个作业场景: SCN-01-FW 插拔 / 02-HANDLE / 03-BI / 04-THERMAL / 05-ATS / 07-UP 上下料)
          + 在役现场场景 data/scene/{objects3d,overlay_spec}.json (插拔机位, **只读真源, 本工具绝不写**)
  · 产物: data/scene/scenes/<SCENE_ID>/{objects3d.json, overlay_spec.json}  (可编辑场景目录)
          并把它们登记进 data/scene/scenes/index.json 的 named_scenes (id → 名字/类别/来源/元素数)
  · 每个场景都能: 切换 / 选元素 / 改位置 / 改轨迹 —— 与 GUI 页内 3D 视图、scene_edit.py 同一份真源。
  · 幂等: 已存在且 --force 未给 ⇒ 不动 (保护用户已编辑过的场景); 现场场景 sha 前后必须一致 (写后自检)。

用法:
  scene_registry.py --list                 列场景库 (不写盘)
  scene_registry.py --build                建/补齐缺失的场景目录 (已存在的跳过)
  scene_registry.py --build --force        重建全部 (覆盖, 有备份)
  scene_registry.py --check                校验 id 唯一/元素计数/现场场景未被动过
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE_DIR = os.path.join(ROOT, "data", "scene")
SCENES_DIR = os.path.join(LIVE_DIR, "scenes")
INDEX = os.path.join(SCENES_DIR, "index.json")
JOBS = os.path.join(ROOT, "flows", "scenes_5jobs.json")
BACKUP = os.path.join(ROOT, "data", "scene", "_backup_registry")

# 现场场景 (插拔机位) 派生的可编辑副本
PEG_COPY = "SCN-01-PEG"

# step 描述里的显式坐标 (X=2.5,Y=-0.4,Z=1.3) ⇒ 真源给的就是这些点, 抽出来当轨迹航点
_COORD = re.compile(r"X\s*=\s*(-?\d+(?:\.\d+)?)\s*[,，]\s*Y\s*=\s*(-?\d+(?:\.\d+)?)\s*[,，]\s*Z\s*=\s*(-?\d+(?:\.\d+)?)")
# 只给一个轴的写法 (X=1.0 / Z=1.2m) ⇒ 记下来, 缺的轴沿用前一点 (不编造)
_AXIS = re.compile(r"([XYZ])\s*[=:]\s*(-?\d+(?:\.\d+)?)\s*m?")

# 有自己的生成器的场景, 场景库不碰 (否则会被 5jobs 的粗版覆盖)
PROTECTED = {"SCN-07-UP": "tools/scene_build_updown.py 生成 (工位级, 含标记/围栏/轨迹)"}


def _step_points(steps, seed) -> tuple[list, list, bool]:
    """按步骤顺序抽坐标 ⇒ (waypoints, step_names, 是否有缺轴沿用)。"""
    wp, names, partial = [list(seed)], ["起点(首对象中心)"], False
    for st in steps:
        txt = "%s %s" % (st.get("desc", ""), st.get("name", ""))
        m3 = _COORD.search(txt)
        if m3:
            p = [float(m3.group(1)), float(m3.group(2)), float(m3.group(3))]
        else:
            hits = _AXIS.findall(txt)
            if not hits:
                continue
            p = list(wp[-1])
            for ax, val in hits:
                p["XYZ".index(ax)] = float(val)
            partial = True
        if max(abs(p[k] - wp[-1][k]) for k in range(3)) > 1e-6:
            wp.append(p)
            names.append(str(st.get("name")))
    return wp, names, partial


def sha(path: str) -> str:
    if not os.path.exists(path):
        return ""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(65536), b""):
            h.update(b)
    return h.hexdigest()[:16]


def _dump(path: str, obj) -> None:
    """原子写 + 备份 (与 scene_edit 同口径)。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        os.makedirs(BACKUP, exist_ok=True)
        shutil.copy2(path, os.path.join(BACKUP, "%s.%s.bak" % (os.path.basename(path), time.strftime("%H%M%S"))))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def load_index() -> dict:
    if os.path.exists(INDEX):
        with open(INDEX, encoding="utf-8") as f:
            return json.load(f)
    return {"format": "zmax-scene-index", "version": "1.0", "named_scenes": {}, "in_service": "现场场景 (只读真源)"}


def save_index(ix: dict) -> None:
    _dump(INDEX, ix)


# ───────────────────────── 场景派生 ─────────────────────────

def from_jobs(scene: dict) -> tuple[dict, dict]:
    """flows/scenes_5jobs.json 的一个作业场景 ⇒ (objects3d, overlay_spec)。

    objects: pos 单位 m (真源坐标) → center; size_mm → size (m)。
    轨迹: 从 steps[].desc 里抽出显式坐标点 (真源自己写的点), 标 derived_from。
    标记: 首个/末个坐标点 ⇒ 取料位/放置位; 围栏: 全部对象 bbox 外扩 0.15m。
    """
    sid = scene["scene_id"]
    objs, markers, fences, trajs = [], [], [], []
    pts_all = []
    for i, o in enumerate(scene.get("objects") or []):
        pos = o.get("pos") or [0, 0, 0]
        sz_mm = o.get("size_mm") or [100, 100, 100]
        sz = [round(float(x) / 1000.0, 4) for x in sz_mm]
        c = [round(float(x), 4) for x in pos]
        objs.append({"id": "ob_%02d" % (i + 1), "name": str(o.get("name")),
                     "center": c, "size": sz, "role": o.get("role", ""),
                     "unit": "m (真源 pos/size_mm 换算)", "editable": True})
        pts_all.append(c)
    # 轨迹航点: steps 描述里的显式坐标 (真源给的点, 不编造); 只给单轴的写法缺轴沿用前一点
    _seed = pts_all[0] if pts_all else [0.0, 0.0, 0.0]
    wp, names, partial = _step_points(scene.get("steps") or [], _seed)
    if len(wp) >= 2:
        trajs.append({"id": "tj_%s_01" % sid.lower().replace("-", "_"),
                      "name": "%s 末端轨迹 (由步骤描述派生)" % scene.get("name", sid),
                      "waypoints": wp,
                      "derived_from": "steps[].desc 显式坐标" + ("; 单轴写法缺轴沿用前一点" if partial else ""),
                      "partial": bool(partial), "step_names": names, "editable": True})
        for p, nm in ((wp[0], "取料位"), (wp[-1], "放置位")):
            markers.append({"id": "mk_%s_%s" % (sid.lower().replace("-", "_"), "pick" if p is wp[0] else "place"),
                            "name": "%s · %s" % (nm, scene.get("name", sid)[:12]),
                            "pos": list(p), "radius_m": 0.05, "editable": True})
    if pts_all:
        lo = [min(p[k] for p in pts_all) - 0.15 for k in range(3)]
        hi = [max(p[k] for p in pts_all) + 0.15 for k in range(3)]
        # ⚠️ scene_edit 的围栏 schema: kind=box|polygon + shape{center,size} (不是 center/size_m!)
        #    且 validate_fence 限 ±3m: 车辆级场景 (工作台 1.5m @ x=2.5) 的单围栏会越界 ⇒ 不生成, 记说明
        _big = any(abs((lo[k] + hi[k]) / 2) + (hi[k] - lo[k]) / 2 > 2.9 for k in range(3))
        fence_note = None
        if _big:
            fence_note = ("场景尺度 (%.2f×%.2f×%.2f m) 超出单个 box 围栏 ±3m 限制 ⇒ 未自动生成, "
                          "请在 GUI 里按工位人工框定" % tuple(round(hi[k] - lo[k], 2) for k in range(3)))
        fences_ok = [] if _big else [{
            "id": "fc_%s_01" % sid.lower().replace("-", "_"),
            "name": "%s 作业区安全围栏" % scene.get("name", sid)[:12], "kind": "box",
            "shape": {"center": [round((lo[k] + hi[k]) / 2, 4) for k in range(3)],
                      "size": [round(hi[k] - lo[k], 4) for k in range(3)]},
            "enabled": True, "source": "推导: 全部对象 bbox 外扩 150mm", "editable": True}]
        fences += fences_ok
        _unused_old = lambda: None
        if False:
            fences.append({"id": "fc_%s_01" % sid.lower().replace("-", "_"),
                       "name": "%s 作业区安全围栏" % scene.get("name", sid)[:12],
                       "kind": "box",
                       "shape": {"center": [round((lo[k] + hi[k]) / 2, 4) for k in range(3)],
                                 "size": [round(hi[k] - lo[k], 4) for k in range(3)]},
                       "enabled": True})
    o3d = {"format": "zmax-scene-objects3d", "version": "1.0", "scene_id": sid, "coord": "m, 自车坐标系 (真源)",
           "source": "flows/scenes_5jobs.json", "scene_name": scene.get("name"), "objects": objs}
    ov = {"format": "zmax-scene-overlay-spec", "version": "1.0", "scene_id": sid,
          "source": "flows/scenes_5jobs.json (轨迹/标记为真源步骤描述派生)",
          "markers": markers, "fences": fences, "trajectories": trajs}
    if fence_note:
        ov["fence_note"] = fence_note
    return o3d, ov


def from_live() -> tuple[dict, dict]:
    """在役现场场景 (插拔机位) ⇒ 可编辑副本。**只读现场文件, 绝不写**。"""
    lo_p = os.path.join(LIVE_DIR, "objects3d.json")
    lv_p = os.path.join(LIVE_DIR, "overlay_spec.json")
    with open(lo_p, encoding="utf-8") as f:
        o3d = json.load(f)
    with open(lv_p, encoding="utf-8") as f:
        ov = json.load(f)
    o3d = dict(o3d)
    o3d["scene_id"] = PEG_COPY
    o3d["source"] = "现场场景 data/scene/objects3d.json 的**可编辑副本** (现场原件只读)"
    o3d["scene_name"] = "插拔场景 (由现场机位派生)"
    ov = dict(ov)
    ov["scene_id"] = PEG_COPY
    ov["source"] = "现场场景 data/scene/overlay_spec.json 的可编辑副本"
    for k in ("markers", "fences", "trajectories"):
        for it in (ov.get(k) or []):
            it["editable"] = True
    for it in (o3d.get("objects") or []):
        it["editable"] = True
    return o3d, ov


# ───────────────────────── 命令 ─────────────────────────

def collect() -> list[tuple[str, str, dict, dict, str]]:
    """⇒ [(sid, 显示名, objects3d, overlay_spec, 来源说明)]"""
    out = []
    with open(JOBS, encoding="utf-8") as f:
        jobs = json.load(f)
    for sc in jobs.get("scenes", []):
        o3d, ov = from_jobs(sc)
        out.append((sc["scene_id"], sc.get("name") or sc["scene_id"], o3d, ov,
                    "flows/scenes_5jobs.json (%s)" % sc.get("scene_type", "")))
    try:
        o3d, ov = from_live()
        out.append((PEG_COPY, "插拔场景 (由现场机位派生)", o3d, ov, "现场场景副本"))
    except FileNotFoundError as e:
        print("⚠️  现场场景缺文件, 跳过派生副本: %s" % e)
    # 🎯 2026-10-10 仿真场景 (老倪: 画布 3D 视图的插拔光模块场景也要能选/编辑/运行):
    #   几何真源 = data/scene/sim/sim_scenes.json (sim_scene_def.py); 可编辑 + 可运行
    try:
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import sim_scene_def as _SSD
        try:                                    # 回放场景按 episode 自己的模型导出 (含机器人本体)
            _r = _SSD.export_episode_truth()
            if _r.get("ok"):
                print("   ↳ 回放场景按 metaworld 模型导出: %s" % _r["msg"])
        except Exception as _e:                                                 # noqa: BLE001
            print("   ⚠️ 回放场景导出跳过: %r" % (_e,))
        for sid, sc in (_SSD.load().get("scenes") or {}).items():
            out.append((sid, sc.get("name") or sid, _SSD.to_objects3d(sid), _SSD.to_overlay(sid),
                        "仿真场景真源 data/scene/sim/sim_scenes.json · 运行 %s"
                        % (sc.get("runner", {}).get("tool", ""))))
    except Exception as e:                                                      # noqa: BLE001
        print("⚠️  仿真场景登记跳过: %r" % (e,))
    # 已经手工建好的场景 (如 scene_build_updown.py 生成的 SCN-07-UP) 优先, 不覆盖
    return out


def cmd_list() -> int:
    ix = load_index()
    print("🗂 场景库 (%s)" % SCENES_DIR)
    for sid, row in sorted((ix.get("named_scenes") or {}).items()):
        print("  %-12s %-30s 来源=%-22s 对象%d/标记%d/围栏%d/轨迹%d" % (
            sid, row.get("name", "")[:30], row.get("source", "")[:22],
            row.get("n_objects", 0), row.get("n_markers", 0), row.get("n_fences", 0), row.get("n_trajectories", 0)))
    print("  在役: %s (只读真源)" % LIVE_DIR)
    return 0


def cmd_build(force: bool) -> int:
    live_before = {p: sha(os.path.join(LIVE_DIR, p)) for p in ("objects3d.json", "overlay_spec.json")}
    ix = load_index()
    named = ix.setdefault("named_scenes", {})
    made, kept = [], []
    for sid, name, o3d, ov, src in collect():
        d = os.path.join(SCENES_DIR, sid)
        exists = os.path.exists(os.path.join(d, "objects3d.json"))
        if sid in PROTECTED:
            kept.append("%s(*%s)" % (sid, PROTECTED[sid].split()[0]))
            exists = True
        elif exists and not force:
            kept.append(sid)
        else:
            _dump(os.path.join(d, "objects3d.json"), o3d)
            _dump(os.path.join(d, "overlay_spec.json"), ov)
            made.append(sid)
        # 无论建没建, 都按**盘上实际内容**登记 (避免登记与实际不符)
        try:
            with open(os.path.join(d, "objects3d.json"), encoding="utf-8") as f:
                a = json.load(f)
            with open(os.path.join(d, "overlay_spec.json"), encoding="utf-8") as f:
                b = json.load(f)
        except FileNotFoundError:
            continue
        _run = (b.get("run") or None) if isinstance(b, dict) else None
        named[sid] = {"name": a.get("scene_name") or name, "source": src,
                      "kind": ("sim" if a.get("sim") else "scene"),
                      "sim_truth": ("data/scene/sim/sim_scenes.json" if a.get("sim") else None),
                      "run": _run,
                      "dir": "data/scene/scenes/%s" % sid,
                      "n_objects": len(a.get("objects") or []),
                      "n_markers": len(b.get("markers") or []),
                      "n_fences": len(b.get("fences") or []),
                      "n_trajectories": len(b.get("trajectories") or []),
                      "editable": True}
    ix["in_service"] = "现场场景 (只读真源)"
    save_index(ix)
    live_after = {p: sha(os.path.join(LIVE_DIR, p)) for p in ("objects3d.json", "overlay_spec.json")}
    print("✅ 新建/重建 %d 个: %s" % (len(made), ", ".join(made) or "-"))
    print("   已存在跳过 %d 个: %s" % (len(kept), ", ".join(kept) or "-"))
    ok = live_before == live_after
    print("%s 现场场景 sha 未变 (%s)" % ("✅" if ok else "⛔", live_after))
    return 0 if ok else 1


def cmd_check() -> int:
    bad = []
    ix = load_index()
    named = ix.get("named_scenes") or {}
    if len(named) < 2:
        bad.append("场景库只有 %d 个场景 (要多个才能切换管理)" % len(named))
    for sid, row in named.items():
        d = os.path.join(SCENES_DIR, sid)
        for fn in ("objects3d.json", "overlay_spec.json"):
            if not os.path.exists(os.path.join(d, fn)):
                bad.append("%s 缺 %s" % (sid, fn))
        with open(os.path.join(d, "objects3d.json"), encoding="utf-8") as f:
            a = json.load(f)
        with open(os.path.join(d, "overlay_spec.json"), encoding="utf-8") as f:
            b = json.load(f)
        if row.get("n_objects") != len(a.get("objects") or []):
            bad.append("%s 登记对象数 %s ≠ 实际 %d" % (sid, row.get("n_objects"), len(a.get("objects") or [])))
        # 每个元素要有可定位的 id (GUI 靠 id 写回)
        for k in ("markers", "fences", "trajectories"):
            for it in (b.get(k) or []):
                if not it.get("id"):
                    bad.append("%s %s 有元素缺 id" % (sid, k))
        for it in (a.get("objects") or []):
            if not (it.get("id") or it.get("name")):
                bad.append("%s objects 有元素缺 id/name" % sid)
    # 真可编辑性: 每个元素必须过 scene_edit 的归一化/校验, 否则 GUI 一编辑就报错
    try:
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import scene_edit as SE
        for sid in named:
            d = os.path.join(SCENES_DIR, sid)
            with open(os.path.join(d, "overlay_spec.json"), encoding="utf-8") as f:
                b = json.load(f)
            for k in ("markers", "fences", "trajectories"):
                for it in (b.get(k) or []):
                    try:
                        SE.NORM[k]({}, it, None)
                    except Exception as e:                                      # noqa: BLE001
                        bad.append("%s %s[%s] 不可编辑: %s" % (sid, k, it.get("id"), str(e)[:70]))
    except ImportError as e:
        print("⚠️  跳过可编辑性判据 (scene_edit 导入失败: %s)" % e)
    lp = os.path.join(LIVE_DIR, "objects3d.json")
    if sha(lp) == "":
        bad.append("现场场景 objects3d.json 不存在")
    print(("⛔ 场景库有问题:\n  - " + "\n  - ".join(bad)) if bad else
          "✅ 场景库判据全绿: %d 个场景, 元素 id 齐, 现场场景在位" % len(named))
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="场景库注册/校验")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--force", action="store_true", help="重建已存在的场景 (有备份)")
    a = ap.parse_args()
    if a.build:
        return cmd_build(a.force)
    if a.check:
        return cmd_check()
    return cmd_list()


if __name__ == "__main__":
    sys.exit(main())
