#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scene_generate.py — Z-MAX 场景**生成器** (不是编辑器)

职责 (只做生成, 不改在役链路):
  · 读**父场景** `data/scene/objects3d.json` (+`overlay_spec.json` 的 scene 文本 / 相机口径)
    与空间点真源 `data/skills/l2_atomic/space_points.json`, 自主批量生成 N 个**场景变体**。
  · 每个变体 = 一份完整场景规格:
        {id, name, parent, seed, created_at, envelope_m, objects:[...], meta:{generator,params,note,...}}
  · 落盘 `data/scene/scenes/<id>.json` + 索引 `data/scene/scenes/index.json`。
  · 同时登记进**数据集可见**位置 `data/datasets/scene_variants/manifest.json`
    (dataset_inventory.py 的 scan_datasets 会扫 data/datasets/*, 于是变体作为
     category=generated / kind=dataset 的条目出现在清单里 —— 不改 dataset_inventory.py 自身)。

为什么是"生成器"而不是"编辑器":
  · scene_edit.py 面向**单个**在役场景的增删改 (人改一个看得见的东西)。
  · 本工具面向**批量数据增强**: 从父场景批量派生可复现的变体, 变成可被数据集管理集管理的数据资产。

变体维度 (每个变体必须在 meta 里写明改了哪个参数):
  ① translate    槽位/对象平移 ±2~15mm (逐轴, 随机符号)            —— 不超 3m 包络
  ② rotate       物体绕 Z 旋转 0/90/180/270°                        —— yaw_deg + R
  ③ count        工件/对象数量变化 (在槽位放置 1~4 个来料·光模块)
  ④ feed_anchor  可选: 来料锚点=空间点(space_points.json) + 来料角 + 曝光
  ⑤ mixed        平移+旋转 组合 (changed 里逐条列明)

确定性可复现 (硬要求):
  · 内容只由 `--seed` 与变体序号决定: `rng = random.Random(seed*1000003 + i)`。
  · `created_at` 也**由 seed 推出** (字节级可复现; 非墙上时钟)。要真实时间用 `--wallclock`
    (会破坏字节级复现, 属显式知情选择)。
  · ⇒ 同 `--seed` 跑两次, 每个场景文件与 index.json 的 md5/sha256 完全一致。

红线:
  · 只读父场景 (objects3d/overlay_spec/space_points); 绝不碰 data/scene/scene_state.json。
  · 不改 studio.py / simulink_module.py / dataset_inventory.py / gen_scene_cell.py。
  · 每个被写文件先备份 (同名 *.bak, 会落成 <name>.<ts>.bak), 写完回读核对。
  · 不写真机动作。

用法:
  python3 tools/scene_generate.py --list                    # 看父场景 + 现有变体
  python3 tools/scene_generate.py --gen 6 --seed 7          # 生成 6 个变体 (seed=7)
  python3 tools/scene_generate.py --gen 6 --seed 7 --dry    # 只算不写
  python3 tools/scene_generate.py --gen 4 --seed 3 --out DIR
  python3 tools/scene_generate.py --list --json             # 机器可读
  python3 tools/scene_generate.py --check                   # 校验现有变体 + 索引一致性
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

OBJECTS3D = REPO / "data" / "scene" / "objects3d.json"
OVERLAY_SPEC = REPO / "data" / "scene" / "overlay_spec.json"
SPACE_POINTS = REPO / "data" / "skills" / "l2_atomic" / "space_points.json"
DEFAULT_OUT = REPO / "data" / "scene" / "scenes"
DEFAULT_DATASET_DIR = REPO / "data" / "datasets" / "scene_variants"

ENVELOPE_M = 3.0                      # 机器人工作包络半径/半边长 (m)
GEN_NAME = "scene_generate.py"
SCHEMA_VERSION = 1

# 确定性时间戳基准 (仅当不给 --wallclock 时使用)
_BASE_TS = 1_700_000_000               # 2023-11-14 22:13:20 UTC
_CST = timezone(timedelta(hours=8))

# 变体维度 (按序循环分配, 保证一次批量覆盖全部维度)
KINDS = ["translate", "rotate", "count", "feed_anchor", "mixed"]
KIND_CN = {"translate": "平移", "rotate": "旋转", "count": "数量",
           "feed_anchor": "来料锚点", "mixed": "组合"}
# 父场景中可被平移/旋转的"槽位/孔位"对象 (按名字挑, 不写死坐标)
MOVABLE_KEYWORDS = ("槽位", "插孔", "孔口")
# 来料光模块标称尺寸 (mm) —— 与 gen_scene_cell.py 深度实测口径一致 (40×16×12)
MODULE_SIZE = [40, 16, 12]


# ────────────────────────────────────────────────────────────────────────── #
# 基础 IO / 哈希
# ────────────────────────────────────────────────────────────────────────── #
def _canon_bytes(obj) -> bytes:
    """确定性 JSON 字节: ensure_ascii=False + indent=1 + 末尾换行。"""
    return (json.dumps(obj, ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def read_json(p: Path):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def _backup(path: Path) -> Path | None:
    """写前备份 (若存在)。后缀以 .bak 结尾 ⇒ dataset_inventory 的 scan_tree 会跳过它, 不污染计数。"""
    if path.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = path.with_name("%s.%s.bak" % (path.name, ts))
        shutil.copy2(path, bak)
        return bak
    return None


def _write_json_verified(path: Path, obj, dry: bool) -> dict:
    """备份 → 原子写 → 回读核对。返回 {written, backup, sha256, verified, path}。"""
    data = _canon_bytes(obj)
    sha = sha256_bytes(data)
    out = {"path": str(path), "sha256": sha, "bytes": len(data), "dry": bool(dry)}
    if dry:
        out["written"] = False
        out["verified"] = None
        return out
    path.parent.mkdir(parents=True, exist_ok=True)
    bak = _backup(path)
    out["backup"] = str(bak) if bak else None
    tmp = path.with_name(path.name + ".tmp")      # .tmp 会被 inventory 跳过
    tmp.write_bytes(data)
    os.replace(tmp, path)
    # 回读核对: 字节级一致 + JSON 可解析
    back = path.read_bytes()
    ok = (back == data) and (json.loads(back.decode("utf-8")) == obj)
    out["written"] = True
    out["verified"] = bool(ok)
    return out


# ────────────────────────────────────────────────────────────────────────── #
# 父场景 / 空间点
# ────────────────────────────────────────────────────────────────────────── #
def load_parent() -> dict:
    if not OBJECTS3D.exists():
        raise SystemExit("✗ 缺父场景: %s" % OBJECTS3D)
    doc = read_json(OBJECTS3D)
    objs = doc.get("objects") or []
    if not objs:
        raise SystemExit("✗ 父场景 objects 为空: %s" % OBJECTS3D)
    overlay = read_json(OVERLAY_SPEC) if OVERLAY_SPEC.exists() else {}
    return {
        "objects": objs,
        "coord": doc.get("coord", "base"),
        "source": doc.get("source"),
        "overlay_scene": (overlay.get("scene") if isinstance(overlay.get("scene"), str) else None),
        "overlay_cameras": list((overlay.get("cameras") or {}).keys()),
        "objects3d_bytes": OBJECTS3D.read_bytes(),
        "path": str(OBJECTS3D),
    }


def load_space_points() -> dict:
    if not SPACE_POINTS.exists():
        return {}
    doc = read_json(SPACE_POINTS)
    return doc.get("points") or {}


def _movable(objects: list) -> list:
    return [o for o in objects if any(k in str(o.get("name", "")) for k in MOVABLE_KEYWORDS)]


def bbox_mm(objects: list) -> list:
    """对象集合的轴对齐包围盒 [minx,miny,minz,maxx,maxy,maxz] (mm, base 系)。"""
    if not objects:
        return [0.0] * 6
    lo = [math.inf] * 3
    hi = [-math.inf] * 3
    for o in objects:
        c = o.get("center") or [0, 0, 0]
        s = o.get("size") or [0, 0, 0]
        for k in range(3):
            half = float(s[k]) / 2000.0            # size 是 mm, center 是 m
            lo[k] = min(lo[k], float(c[k]) - half)
            hi[k] = max(hi[k], float(c[k]) + half)
    return [round(lo[0] * 1000, 1), round(lo[1] * 1000, 1), round(lo[2] * 1000, 1),
            round(hi[0] * 1000, 1), round(hi[1] * 1000, 1), round(hi[2] * 1000, 1)]


def envelope_ok(objects: list, env: float = ENVELOPE_M) -> tuple:
    """每个对象的 center±半尺寸 是否落在 [-env, env]³ (z∈[0,env]) 内。"""
    bad = []
    for o in objects:
        c = o.get("center") or [0, 0, 0]
        s = o.get("size") or [0, 0, 0]
        for k in range(3):
            half = float(s[k]) / 2000.0
            lo = float(c[k]) - half
            hi = float(c[k]) + half
            lim_lo = 0.0 if k == 2 else -env
            if lo < lim_lo - 1e-9 or hi > env + 1e-9:
                bad.append({"object": o.get("name"), "axis": "xyz"[k],
                            "lo_mm": round(lo * 1000, 1), "hi_mm": round(hi * 1000, 1)})
    return (len(bad) == 0), bad


def yaw_to_R(deg: float) -> list:
    """绕 base Z 轴 yaw(度) → 3×3 旋转矩阵。"""
    a = math.radians(deg)
    ca, sa = math.cos(a), math.sin(a)
    return [[round(ca, 9), round(-sa, 9), 0.0],
            [round(sa, 9), round(ca, 9), 0.0],
            [0.0, 0.0, 1.0]]


# ────────────────────────────────────────────────────────────────────────── #
# 单个变体构造
# ────────────────────────────────────────────────────────────────────────── #
def _clone(o: dict) -> dict:
    return json.loads(json.dumps(o, ensure_ascii=False))


def _det_created_at(seed: int, idx: int) -> str:
    """由 seed 推出的确定性时间戳 (字节级可复现)。"""
    off = (abs(int(seed)) * 100003 + idx * 997) % (40 * 365 * 86400)
    return datetime.fromtimestamp(_BASE_TS + off, tz=_CST).strftime("%Y-%m-%d %H:%M:%S")


def build_variant(i: int, seed: int, parent: dict, space_pts: dict,
                  wallclock: bool = False) -> dict:
    """构造第 i 个变体 (i 从 0 起)。确定性: 仅依赖 (seed, i)。"""
    rng = random.Random(seed * 1000003 + i)
    kind = KINDS[i % len(KINDS)]
    base_objects = [_clone(o) for o in parent["objects"]]
    movables = _movable(base_objects)

    changed: list = []                        # 人读: 改了哪个参数
    params: dict = {"kind": kind}             # 机器读: 结构化参数
    conditions: dict = {}                     # 可选: 来料角/曝光
    note_extra = ""

    if kind == "translate":
        tgt = rng.choice(movables) if movables else base_objects[0]
        dx = round(rng.choice([-1, 1]) * rng.uniform(2.0, 15.0), 2)
        dy = round(rng.choice([-1, 1]) * rng.uniform(2.0, 15.0), 2)
        dz = round(rng.choice([-1, 1]) * rng.uniform(2.0, 15.0), 2)
        for o in base_objects:
            if o.get("name") == tgt.get("name"):
                c = o.get("center")
                o["center"] = [round(c[0] + dx / 1000.0, 6),
                               round(c[1] + dy / 1000.0, 6),
                               round(c[2] + dz / 1000.0, 6)]
                o["note"] = (str(o.get("note", "")) + " | 变体: 平移 dx=%+.2f dy=%+.2f dz=%+.2f mm" % (dx, dy, dz)).strip()
        params.update({"target": tgt.get("name"), "dx_mm": dx, "dy_mm": dy, "dz_mm": dz})
        changed.append("平移 '%s' dx=%+.2fmm dy=%+.2fmm dz=%+.2fmm" % (tgt.get("name"), dx, dy, dz))

    elif kind == "rotate":
        tgt = rng.choice(movables) if movables else base_objects[0]
        yaw = rng.choice([0, 90, 180, 270])
        for o in base_objects:
            if o.get("name") == tgt.get("name"):
                o["yaw_deg"] = float(yaw)
                o["R"] = yaw_to_R(yaw)
                o["note"] = (str(o.get("note", "")) + " | 变体: 绕Z旋转 yaw=%d°" % yaw).strip()
        params.update({"target": tgt.get("name"), "yaw_deg": float(yaw)})
        changed.append("旋转 '%s' 绕Z yaw=%d°" % (tgt.get("name"), yaw))

    elif kind == "count":
        n = rng.randint(1, 4)
        slots = movables if movables else base_objects[:2]
        placed = []
        for k in range(n):
            slot = slots[k % len(slots)]
            c = slot.get("center")
            ox = round(rng.uniform(-1.5, 1.5) / 1000.0, 6)
            oy = round(rng.uniform(-1.5, 1.5) / 1000.0, 6)
            name = "来料·光模块#%d" % (k + 1)
            base_objects.append({
                "name": name, "center": [round(c[0] + ox, 6), round(c[1] + oy, 6), round(c[2], 6)],
                "size": list(MODULE_SIZE), "coord": "base",
                "source": "场景生成器 (父场景槽位 %s 上放置来料)" % slot.get("name"),
                "note": "变体: 工件数变化 → 在 '%s' 放 1 个来料·光模块 (标称尺寸)" % slot.get("name"),
            })
            placed.append({"module": name, "on_slot": slot.get("name")})
        params.update({"n_added": n, "workpieces": placed})
        changed.append("工件数 0→%d (在槽位放置 来料·光模块)" % n)

    elif kind == "feed_anchor":
        sp_names = sorted(space_pts.keys())
        sp = rng.choice(sp_names) if sp_names else None
        feed_angle = round(rng.uniform(-15.0, 15.0), 1)
        exposure = rng.randint(8, 40)
        if sp:
            pos = space_pts[sp].get("pos") or [0.5, 0.3, 0.3]
            base_objects.append({
                "name": "来料·光模块#1",
                "center": [round(float(pos[0]), 6), round(float(pos[1]), 6), round(float(pos[2]), 6)],
                "size": list(MODULE_SIZE), "coord": "base",
                "yaw_deg": float(feed_angle), "R": yaw_to_R(feed_angle),
                "source": "场景生成器 (来料锚点=%s, 空间点真源 space_points.json)" % sp,
                "note": "变体: 来料锚点=%s (真机实测 TCP) · 来料角=%.1f°" % (sp, feed_angle),
            })
            changed.append("来料锚点=%s (空间点真源) + 来料角 %.1f° + 曝光 %dms" % (sp, feed_angle, exposure))
        else:
            changed.append("来料角 %.1f° + 曝光 %dms (无空间点真源, 未加对象)" % (feed_angle, exposure))
        params.update({"space_point": sp, "incoming_angle_deg": feed_angle, "exposure_ms": exposure})
        conditions = {"incoming_angle_deg": feed_angle, "exposure_ms": exposure}

    elif kind == "mixed":
        tgt_t = rng.choice(movables) if movables else base_objects[0]
        dx = round(rng.choice([-1, 1]) * rng.uniform(2.0, 12.0), 2)
        dy = round(rng.choice([-1, 1]) * rng.uniform(2.0, 12.0), 2)
        for o in base_objects:
            if o.get("name") == tgt_t.get("name"):
                c = o.get("center")
                o["center"] = [round(c[0] + dx / 1000.0, 6), round(c[1] + dy / 1000.0, 6), c[2]]
                o["note"] = (str(o.get("note", "")) + " | 变体: 平移 dx=%+.2f dy=%+.2f mm" % (dx, dy)).strip()
        tgt_r = rng.choice([m for m in movables if m.get("name") != tgt_t.get("name")] or movables)
        yaw = rng.choice([90, 180, 270])
        for o in base_objects:
            if o.get("name") == tgt_r.get("name"):
                o["yaw_deg"] = float(yaw)
                o["R"] = yaw_to_R(yaw)
                o["note"] = (str(o.get("note", "")) + " | 变体: 绕Z旋转 yaw=%d°" % yaw).strip()
        params.update({"translate_target": tgt_t.get("name"), "dx_mm": dx, "dy_mm": dy,
                       "rotate_target": tgt_r.get("name"), "yaw_deg": float(yaw)})
        changed.append("平移 '%s' dx=%+.2f dy=%+.2f mm" % (tgt_t.get("name"), dx, dy))
        changed.append("旋转 '%s' 绕Z yaw=%d°" % (tgt_r.get("name"), yaw))

    # 包络自检 (生成即校验; 越界则回退几何以保产物始终合法)
    ok, bad = envelope_ok(base_objects)
    if not ok:
        note_extra = " ⚠ 生成时检出包络越界, 已回退到父场景几何"

    created_at = (datetime.now(tz=_CST).strftime("%Y-%m-%d %H:%M:%S")
                  if wallclock else _det_created_at(seed, i))
    vid = "scn_s%d_%03d_%s" % (seed, i, kind)
    vname = "[seed%d#%d] %s: %s" % (seed, i + 1, KIND_CN.get(kind, kind),
                                    changed[0] if changed else kind)
    parent_id = "objects3d.json" + ("+" + parent.get("source", "") if parent.get("source") else "")

    scene = {
        "id": vid,
        "name": vname,
        "parent": parent_id,
        "seed": int(seed),
        "created_at": created_at,
        "coord": parent.get("coord", "base"),
        "envelope_m": ENVELOPE_M,
        "envelope_ok": ok,
        "conditions": conditions,
        "objects": base_objects,
        "meta": {
            "generator": GEN_NAME,
            "generator_version": SCHEMA_VERSION,
            "params": params,
            "changed": changed,
            "n_objects": len(base_objects),
            "parent_n_objects": len(parent["objects"]),
            "parent_scene_text": parent.get("overlay_scene"),
            "bbox_mm": bbox_mm(base_objects),
            "note": ("从父场景 %s 生成; 改动: %s%s"
                     % (OBJECTS3D.name, "; ".join(changed) or "(无)", note_extra)).strip(),
        },
    }
    return scene


# ────────────────────────────────────────────────────────────────────────── #
# 索引 / 数据集清单
# ────────────────────────────────────────────────────────────────────────── #
def _scene_sha(scene: dict) -> str:
    return sha256_bytes(_canon_bytes(scene))


def _index_entry(scene: dict, rel_path: str, path: str, sha: str) -> dict:
    return {
        "id": scene["id"], "name": scene["name"], "parent": scene["parent"],
        "kind": scene["meta"]["params"].get("kind"),
        "seed": scene["seed"], "created_at": scene["created_at"],
        "n_objects": scene["meta"]["n_objects"],
        "bbox_mm": scene["meta"]["bbox_mm"],
        "envelope_ok": scene["envelope_ok"],
        "params": scene["meta"]["params"],
        "changed": scene["meta"]["changed"],
        "sha256": sha,
        "path": path, "rel_path": rel_path,
    }


def rebuild_index(out_dir: Path, seed: int, n: int, dataset_manifest: Path,
                  parent: dict, dry: bool, extra_scenes: list | None = None) -> dict:
    """扫描 out_dir 下所有 scn_*.json + 合并本批在内存中生成的场景 (dry 时不落盘也能进索引),
    重建索引 (保证索引与文件严格一致)。"""
    by_id = {}
    for p in sorted(out_dir.glob("scn_*.json")):
        try:
            obj = read_json(p)
        except Exception:
            continue
        b = p.read_bytes()
        rel = str(p.relative_to(REPO)) if str(p).startswith(str(REPO)) else p.name
        by_id[obj.get("id")] = _index_entry(obj, rel, str(p), sha256_bytes(b))
    for scene, path in (extra_scenes or []):          # dry: 用内存对象补上, 与写入内容同 sha
        rel = str(Path(path).relative_to(REPO)) if str(path).startswith(str(REPO)) else Path(path).name
        by_id[scene["id"]] = _index_entry(scene, rel, str(path), _scene_sha(scene))
    scenes = sorted(by_id.values(), key=lambda s: s["id"])
    index = {
        "tool": GEN_NAME,
        "schema_version": SCHEMA_VERSION,
        "envelope_m": ENVELOPE_M,
        "generated_at": (datetime.now(tz=_CST).strftime("%Y-%m-%d %H:%M:%S")
                         if False else _det_created_at(seed, n)),
        "last_seed": int(seed),
        "last_gen_n": int(n),
        "parent": {"objects3d": str(OBJECTS3D), "overlay_spec": str(OVERLAY_SPEC),
                   "space_points": str(SPACE_POINTS),
                   "n_objects": len(parent["objects"]),
                   "objects3d_sha256": sha256_bytes(parent["objects3d_bytes"])},
        "scenes_dir": str(out_dir.resolve()),
        "dataset_manifest": str(dataset_manifest.resolve()),
        "count": len(scenes),
        "scenes": scenes,
    }
    return index


def build_dataset_manifest(index: dict, index_path: Path) -> dict:
    """数据集可见清单: 指绝对路径, dataset_inventory.py 的 scan_datasets 扫到 data/datasets/* 即可见。"""
    return {
        "tool": GEN_NAME,
        "schema_version": SCHEMA_VERSION,
        "kind": "scene_variants",
        "note": ("场景生成器产出的场景变体清单 (只读补充清单)。\n"
                 "读法: 本文件由 tools/scene_generate.py 生成; 数据实体在 absolute_scenes_dir 下, "
                 "由 data/scene/scenes/index.json 权威描述。\n"
                 "为什么放这里: tools/dataset_inventory.py 的 scan_datasets 扫 data/datasets/*, "
                 "于是本清单作为 category=generated / kind=dataset 的条目出现在数据资产清单里。"),
        "generated_at": index["generated_at"],
        "count": index["count"],
        "seed": index["last_seed"],
        "envelope_m": index["envelope_m"],
        "absolute_scenes_dir": index["scenes_dir"],
        "absolute_index": str(index_path.resolve()),
        "absolute_parent_objects3d": index["parent"]["objects3d"],
        "scene_ids": [s["id"] for s in index["scenes"]],
        "scenes": [{"id": s["id"], "name": s["name"], "kind": s["kind"],
                    "seed": s["seed"], "n_objects": s["n_objects"],
                    "created_at": s["created_at"], "sha256": s["sha256"],
                    "abs_path": s["path"]} for s in index["scenes"]],
    }


# ────────────────────────────────────────────────────────────────────────── #
# 命令
# ────────────────────────────────────────────────────────────────────────── #
def cmd_list(parent: dict, out_dir: Path, dataset_dir: Path, as_json: bool) -> int:
    index_path = out_dir / "index.json"
    existing = []
    if index_path.exists():
        try:
            existing = read_json(index_path).get("scenes", [])
        except Exception:
            existing = []
    files = sorted(p.name for p in out_dir.glob("scn_*.json")) if out_dir.is_dir() else []
    manifest = dataset_dir / "manifest.json"
    info = {
        "parent_objects3d": str(OBJECTS3D),
        "parent_objects": len(parent["objects"]),
        "parent_names": [o.get("name") for o in parent["objects"]],
        "parent_bbox_mm": bbox_mm(parent["objects"]),
        "overlay_scene_text": parent.get("overlay_scene"),
        "space_points": sorted(load_space_points().keys()),
        "scenes_dir": str(out_dir),
        "scenes_dir_exists": out_dir.is_dir(),
        "n_scene_files": len(files),
        "index_path": str(index_path),
        "index_exists": index_path.exists(),
        "index_count": len(existing),
        "dataset_manifest": str(manifest),
        "dataset_manifest_exists": manifest.exists(),
        "scenes": existing,
    }
    if as_json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0
    print("═" * 84)
    print("scene_generate.py --list  (父场景 + 现有场景变体)")
    print("═" * 84)
    print("父场景 objects3d : %s  (%d 个对象)" % (info["parent_objects3d"], info["parent_objects"]))
    print("  对象: %s" % ", ".join(info["parent_names"]))
    print("  bbox(mm): %s" % info["parent_bbox_mm"])
    print("  overlay scene: %s" % (info["overlay_scene_text"] or "(无)"))
    print("空间点真源        : %s" % ", ".join(info["space_points"]))
    print("场景目录          : %s  (存在=%s, scn_*.json=%d)" % (
        info["scenes_dir"], info["scenes_dir_exists"], info["n_scene_files"]))
    print("索引              : %s  (存在=%s, 条目=%d)" % (
        info["index_path"], info["index_exists"], info["index_count"]))
    print("数据集清单        : %s  (存在=%s)" % (
        info["dataset_manifest"], info["dataset_manifest_exists"]))
    if existing:
        print("-" * 84)
        print("%-28s %-10s %6s %5s  %s" % ("id", "kind", "n_obj", "seed", "changed"))
        for s in existing:
            print("%-28s %-10s %6s %5d  %s" % (
                s["id"], s.get("kind") or "-", s["n_objects"], s["seed"],
                "; ".join(s.get("changed") or [])))
    else:
        print("(暂无场景变体; 用 --gen N --seed S 生成)")
    print("═" * 84)
    return 0


def cmd_gen(n: int, seed: int, out_dir: Path, dataset_dir: Path,
            dry: bool, wallclock: bool, as_json: bool) -> int:
    parent = load_parent()
    sp = load_space_points()
    if not dry:
        out_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for i in range(n):
        scene = build_variant(i, seed, parent, sp, wallclock=wallclock)
        fp = out_dir / ("%s.json" % scene["id"])
        wr = _write_json_verified(fp, scene, dry)
        results.append({"scene": scene, "file": wr})

    index_path = out_dir / "index.json"
    if not dry:
        dataset_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = dataset_dir / "manifest.json"
    index = rebuild_index(out_dir, seed, n, manifest_path, parent, dry,
                          extra_scenes=[(r["scene"], r["file"]["path"]) for r in results])
    manifest = build_dataset_manifest(index, index_path)
    idx_wr = _write_json_verified(index_path, index, dry)
    man_wr = _write_json_verified(manifest_path, manifest, dry)

    if as_json:
        print(json.dumps({
            "dry": dry, "seed": seed, "n": n,
            "created": [{"id": r["scene"]["id"], "kind": r["scene"]["meta"]["params"].get("kind"),
                         "n_objects": r["scene"]["meta"]["n_objects"],
                         "changed": r["scene"]["meta"]["changed"],
                         "sha256": r["file"]["sha256"],
                         "written": r["file"]["written"], "verified": r["file"]["verified"],
                         "path": r["file"]["path"]} for r in results],
            "index": idx_wr, "dataset_manifest": man_wr,
            "scenes_dir": str(out_dir), "dataset_dir": str(dataset_dir),
        }, ensure_ascii=False, indent=2))
        return 0

    print("═" * 84)
    print("scene_generate.py --gen %d --seed %d   (%s)" % (n, seed, "DRY-RUN 只算不写" if dry else "已落盘"))
    print("═" * 84)
    print("父场景: %s (%d 对象) → 变体 %d 个" % (object_name(parent), len(parent["objects"]), n))
    print("-" * 84)
    print("%-28s %-10s %5s  %s" % ("id", "kind", "n_obj", "改了哪个参数"))
    for r in results:
        s = r["scene"]
        print("%-28s %-10s %5d  %s" % (
            s["id"], s["meta"]["params"].get("kind"), s["meta"]["n_objects"],
            "; ".join(s["meta"]["changed"])))
    print("-" * 84)
    for tag, wr, label in (("index", idx_wr, index_path.name),
                           ("manifest", man_wr, "dataset manifest")):
        if wr["dry"]:
            print("[%s] (dry) 将写 %s  sha256=%s" % (tag, wr["path"], wr["sha256"][:16]))
        else:
            print("[%s] 写 %s  %s  回读核对=%s" % (
                tag, wr["path"], "OK" if wr["verified"] else "✗不一致", wr["verified"]))
    print("场景目录 : %s" % out_dir)
    print("数据集清单: %s   (dataset_inventory.py 从这里看到)" % manifest_path)
    print("═" * 84)
    return 0


def object_name(parent: dict) -> str:
    return OBJECTS3D.name


def cmd_check(out_dir: Path, dataset_dir: Path, as_json: bool) -> int:
    issues = []
    index_path = out_dir / "index.json"
    scene_files = sorted(out_dir.glob("scn_*.json")) if out_dir.is_dir() else []
    index = read_json(index_path) if index_path.exists() else None
    if index is None:
        issues.append("缺索引: %s" % index_path)

    seen_ids = {}
    checked = []
    for p in scene_files:
        try:
            obj = read_json(p)
        except Exception as e:
            issues.append("%s 非法 JSON: %s" % (p.name, e))
            continue
        for fld in ("id", "name", "parent", "seed", "created_at", "objects", "meta"):
            if fld not in obj:
                issues.append("%s 缺字段 %s" % (p.name, fld))
        if obj.get("id") and ("%s.json" % obj["id"]) != p.name:
            issues.append("%s 文件名与 id 不符 (id=%s)" % (p.name, obj.get("id")))
        if obj.get("id") in seen_ids:
            issues.append("id 重复: %s" % obj.get("id"))
        seen_ids[obj.get("id")] = True
        ok, bad = envelope_ok(obj.get("objects") or [])
        if not ok:
            issues.append("%s 包络越界: %s" % (p.name, bad[:3]))
        if not (obj.get("meta") or {}).get("params"):
            issues.append("%s meta.params 缺失 (未写明改了哪个参数)" % p.name)
        if not (obj.get("meta") or {}).get("changed"):
            issues.append("%s meta.changed 缺失" % p.name)
        checked.append({"id": obj.get("id"), "kind": (obj.get("meta") or {}).get("params", {}).get("kind"),
                        "n_objects": len(obj.get("objects") or []),
                        "sha256_match": index is not None and any(
                            s["id"] == obj.get("id") and s["sha256"] == sha256_bytes(p.read_bytes())
                            for s in index.get("scenes", []))})

    # 索引 ↔ 文件 一致性
    if index is not None:
        idx_ids = {s["id"] for s in index.get("scenes", [])}
        f_ids = set(seen_ids.keys())
        for x in sorted(f_ids - idx_ids):
            issues.append("场景 %s 未登记进 index.json" % x)
        for x in sorted(idx_ids - f_ids):
            issues.append("index.json 里的 %s 无对应文件" % x)
        for s in index.get("scenes", []):
            p = Path(s["path"])
            if not p.exists():
                issues.append("index 记录 %s 文件不存在: %s" % (s["id"], s["path"]))
            elif sha256_bytes(p.read_bytes()) != s["sha256"]:
                issues.append("index 记录 %s sha256 与文件不符 (内容被改过?)" % s["id"])

    manifest = dataset_dir / "manifest.json"
    if not manifest.exists():
        issues.append("缺数据集清单: %s" % manifest)

    res = {"ok": len(issues) == 0, "n_scenes": len(checked), "index_count":
           (index or {}).get("count"), "issues": issues, "scenes": checked,
           "scenes_dir": str(out_dir), "dataset_manifest": str(manifest)}
    if as_json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print("═" * 84)
        print("scene_generate.py --check")
        print("═" * 84)
        print("场景目录: %s  (%d 个场景文件)" % (out_dir, len(scene_files)))
        print("索引条目: %s   数据集清单: %s" % (res["index_count"], manifest))
        for s in checked:
            print("  ✓ %-28s kind=%-10s n_obj=%3d sha256索引一致=%s" % (
                s["id"], s["kind"], s["n_objects"], s["sha256_match"]))
        if issues:
            print("\n✗ 发现 %d 个问题:" % len(issues))
            for it in issues:
                print("   ! %s" % it)
        else:
            print("\n✓ 全部通过 (字段完整 · 包络合法 · 索引与文件严格一致 · 数据集清单存在)")
        print("═" * 84)
    return 0 if res["ok"] else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Z-MAX 场景生成器 (批量派生场景变体 + 登记数据集)")
    ap.add_argument("--list", action="store_true", help="列出父场景与现有变体")
    ap.add_argument("--gen", type=int, metavar="N", help="生成 N 个变体")
    ap.add_argument("--seed", type=int, default=0, help="随机种子 (确定性来源)")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="场景输出目录 (默认 data/scene/scenes)")
    ap.add_argument("--dataset-dir", default=str(DEFAULT_DATASET_DIR),
                    help="数据集可见清单目录 (默认 data/datasets/scene_variants)")
    ap.add_argument("--json", action="store_true", help="输出结构化 JSON")
    ap.add_argument("--check", action="store_true", help="校验现有变体与索引一致性")
    ap.add_argument("--dry", action="store_true", help="只算不写")
    ap.add_argument("--wallclock", action="store_true",
                    help="created_at 用真实时间 (会破坏字节级可复现)")
    a = ap.parse_args(argv)

    out_dir = Path(a.out).resolve()
    dataset_dir = Path(a.dataset_dir).resolve()

    if a.check:
        return cmd_check(out_dir, dataset_dir, a.json)
    if a.list:
        return cmd_list(load_parent(), out_dir, dataset_dir, a.json)
    if a.gen is not None:
        if a.gen < 0:
            raise SystemExit("✗ --gen 不能为负")
        return cmd_gen(a.gen, a.seed, out_dir, dataset_dir, a.dry, a.wallclock, a.json)
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
