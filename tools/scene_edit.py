#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""场景编辑器后端 —— 对"运行中的仿真场景 + 真机场景"做可视化编辑的数据层 (GUI 调它)。

真源 (只碰这三个, 绝不写 scene_state.json):
  · data/scene/objects3d.json    —— 3D 对象表 (objects[])
  · data/scene/overlay_spec.json —— 叠加规范 (markers[] / fences[] / trajectories[] / deleted 黑名单)
  · data/scene/traj_display.json —— 轨迹显示开关 (show)

四类实体:
  objects      增/删/改 objects3d.json 的 objects; 隐藏/显示 = 同步 overlay_spec 的 deleted 黑名单
  markers      现场标记 (工位/危险区/检查点/自定义) → overlay_spec["markers"]
  fences       保护围栏 box / polygon → overlay_spec["fences"]  (带合法性校验)
  trajectories 自定义/示教/规划轨迹 → overlay_spec["trajectories"] (waypoints 可引用空间点名)

纪律 (硬约束):
  · 每次写先备份 (带时间戳) → 原子写 (唯一 .tmp + os.replace) → 回读核对 → 失败回滚
  · 保留文件里自己不认识的其他键 (load-modify-dump; 绝不整体重写)
  · 绝不发真机运动指令; 绝不写 scene_state.json (只读)
  · 从不修改别家进程在用的 ts / updated_at (保持与外部写者的 key 级 diff 干净)

用法:
    python3 tools/scene_edit.py list [--kind objects|markers|fences|trajectories] [--json]
    python3 tools/scene_edit.py add    --kind markers --data '<json>' [--json] [--dry]
    python3 tools/scene_edit.py update --kind X --id ID --data '<json>' [--json] [--dry]
    python3 tools/scene_edit.py rm     --kind X --id ID [--json] [--dry]
    python3 tools/scene_edit.py show|hide --kind objects --id/--name NAME [--cam arm] [--json] [--dry]
    python3 tools/scene_edit.py set --json-delete <path> [--json] [--dry]
    python3 tools/scene_edit.py set --traj-show on|off    [--json]
    python3 tools/scene_edit.py check [--json]
    python3 tools/scene_edit.py path  [--json]
"""
from __future__ import annotations

import argparse
import copy
import fcntl
import json
import os
import shutil
import sys
import time
from pathlib import Path

# ── 路径 (可用环境变量重定向 ⇒ 单元测试在副本上真跑, 不碰在役文件) ──
REPO = Path(os.environ.get("ZMAX_REPO", Path(__file__).resolve().parents[1]))
SCENE_DIR = Path(os.environ.get("ZMAX_SCENE_DIR", REPO / "data" / "scene"))
OBJECTS3D = SCENE_DIR / "objects3d.json"
OVERLAY = SCENE_DIR / "overlay_spec.json"
TRAJDISPLAY = SCENE_DIR / "traj_display.json"
SPACE_POINTS = Path(os.environ.get("ZMAX_SPACE_POINTS",
                                   REPO / "data" / "skills" / "l2_atomic" / "space_points.json"))
SCENE_STATE = SCENE_DIR / "scene_state.json"          # 只读, 绝不写

# kind → (文件, 顶层键)
KIND_FILE = {"objects": OBJECTS3D, "markers": OVERLAY, "fences": OVERLAY, "trajectories": OVERLAY}
KIND_KEY = {"objects": "objects", "markers": "markers", "fences": "fences", "trajectories": "trajectories"}
KINDS = ("objects", "markers", "fences", "trajectories")

LIMIT = 3.0                      # 坐标 ±3m 内
MARKER_TYPES = ("工位", "危险区", "检查点", "自定义")
TRAJ_KINDS = ("自定义", "示教", "规划")

_LOCK_FH = None


# ══════════════════════ 文件读写 (并发安全 + 原子) ══════════════════════
def _ts() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def acquire_lock(timeout: float = 5.0):
    """跨进程互斥 (advisory flock)。外部进程 (l5_live_mark 等) 不用这把锁 ⇒ 只能缩小窗口,
    真保证靠"唯一 tmp + 原子 replace + 写后回读重试"。"""
    global _LOCK_FH
    try:
        SCENE_DIR.mkdir(parents=True, exist_ok=True)
        fh = open(SCENE_DIR / ".scene_edit.lock", "a+")
        end = time.time() + timeout
        while True:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                _LOCK_FH = fh
                return
            except OSError:
                if time.time() >= end:
                    raise TimeoutError("场景编辑锁被占用 (%.1fs)" % timeout)
                time.sleep(0.05)
    except Exception:
        _LOCK_FH = None            # 锁文件建不了也不阻塞 (退化为无锁 + 回读重试)


def release_lock():
    global _LOCK_FH
    if _LOCK_FH is not None:
        try:
            fcntl.flock(_LOCK_FH.fileno(), fcntl.LOCK_UN)
            _LOCK_FH.close()
        except Exception:                                                      # noqa: BLE001
            pass
        _LOCK_FH = None


def load_json(path: Path, retries: int = 20) -> dict:
    """读 JSON; 在役文件被别家进程原子替换时偶发读到半截 ⇒ 重试。"""
    last = None
    for _ in range(retries):
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8")) or {}
        except Exception as e:                                                 # noqa: BLE001
            last = e
            time.sleep(0.02)
    raise RuntimeError("读取 %s 失败: %s" % (path, last))


def dump_atomic(path: Path, obj: dict) -> None:
    """原子写: 每进程/每次唯一 tmp (绝不共用), 再 os.replace。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("%s.tmp.%d.%d" % (path.name, os.getpid(), time.time_ns() % 1000000))
    try:
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:                                                          # noqa: BLE001
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def backup(path: Path) -> Path:
    """带时间戳备份到同目录 (与既有 .bak_* 命名一致)。"""
    bak = path.with_name("%s.bak_edit_%s" % (path.name, _ts()))
    if bak.exists():                                                           # 同秒二次
        bak = path.with_name("%s.bak_edit_%s_%d" % (path.name, _ts(), time.time_ns() % 1000))
    shutil.copy2(path, bak) if path.exists() else bak.write_text("{}", encoding="utf-8")
    return bak


# ══════════════════════ 实体工具 ══════════════════════
def entity_id(e: dict, kind: str):
    """统一 id 解析: 优先显式 id, 否则退回 name (objects3d 既有条目没有 id, 用 name 当 id)。"""
    if not isinstance(e, dict):
        return None
    return e.get("id", e.get("name"))


def find_entity(items: list, key) -> int:
    if key is None:
        return -1
    for i, e in enumerate(items):
        if not isinstance(e, dict):
            continue
        if e.get("id") == key or e.get("name") == key:
            return i
    return -1


def _isnum(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _vec3(v) -> bool:
    return isinstance(v, list) and len(v) == 3 and all(_isnum(x) for x in v)


def _unique_id(items: list, base: str) -> str:
    ids = {entity_id(e, "") for e in items if isinstance(e, dict)}
    if base not in ids:
        return base
    k = 2
    while "%s-%d" % (base, k) in ids:
        k += 1
    return "%s-%d" % (base, k)


# ── 校验/规范化: objects ──
def norm_object(data: dict, existing: dict | None = None) -> dict:
    d = dict(existing or {})
    d.update(data or {})
    errs = []
    if not d.get("name"):
        errs.append("objects 必须有 name")
    if not _vec3(d.get("center")):
        errs.append("objects.center 必须是 3 个数字 [x,y,z] (base 系, m)")
    if not (isinstance(d.get("size"), list) and len(d["size"]) == 3 and all(_isnum(x) for x in d["size"])):
        errs.append("objects.size 必须是 3 个数字 [mm,mm,mm]")
    d.setdefault("coord", "base")
    if d.get("coord") != "base":
        errs.append("objects.coord 目前只支持 'base'")
    d.setdefault("source", "scene_edit")
    if "color" in d and not (isinstance(d["color"], str) or isinstance(d["color"], list)):
        errs.append("objects.color 必须是字符串或 [r,g,b]")
    if errs:
        raise ValueError("; ".join(errs))
    # 保持字段顺序: name/center/size/coord/source/color/note
    out = {"name": d["name"], "center": [round(float(x), 6) for x in d["center"]],
           "size": [float(x) for x in d["size"]], "coord": d["coord"], "source": d["source"]}
    if "color" in d:
        out["color"] = d["color"]
    if "note" in d:
        out["note"] = d["note"]
    for k, v in d.items():                    # 保留用户给的额外键
        out.setdefault(k, v)
    return out


# ── 校验/规范化: markers ──
def norm_marker(data: dict, existing: dict | None = None, items: list | None = None) -> dict:
    d = dict(existing or {})
    d.update(data or {})
    errs = []
    if not d.get("name"):
        errs.append("markers 必须有 name")
    if d.get("type", "自定义") not in MARKER_TYPES:
        errs.append("markers.type 必须是 %s 之一" % "/".join(MARKER_TYPES))
    if not _vec3(d.get("pos")):
        errs.append("markers.pos 必须是 3 个数字 [x,y,z] (base 系)")
    else:
        for i, v in enumerate(d["pos"]):
            if abs(v) > LIMIT:
                errs.append("markers.pos 第%d 轴 %.3f 超出 ±3m" % (i, v))
    if "quat" in d and d["quat"] is not None and not (isinstance(d["quat"], list) and len(d["quat"]) == 4):
        errs.append("markers.quat 必须是 4 个数字 [x,y,z,w]")
    if errs:
        raise ValueError("; ".join(errs))
    if not d.get("id"):
        d["id"] = _unique_id(items or [], "mk_" + str(d["name"]))
    d.setdefault("type", "自定义")
    d.setdefault("desc", "")
    d.setdefault("created_at", time.strftime("%Y-%m-%d %H:%M:%S"))
    out = {k: d[k] for k in ("id", "name", "type", "pos") if k in d}
    if d.get("quat") is not None:
        out["quat"] = d["quat"]
    out["desc"] = d.get("desc", "")
    out["created_at"] = d.get("created_at")
    for k, v in d.items():
        out.setdefault(k, v)
    return out


# ── 校验/规范化: fences ──
def _poly_area(pts: list) -> float:
    a = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i][0], pts[i][1]
        x2, y2 = pts[(i + 1) % n][0], pts[(i + 1) % n][1]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def validate_fence(f: dict) -> list:
    """返回错误列表 (空=合法)。越界/退化/结构错即拒。"""
    errs = []
    kind = f.get("kind")
    if kind not in ("box", "polygon"):
        return ["fence.kind 必须是 box|polygon (收到 %r)" % (kind,)]
    shape = f.get("shape")
    if not isinstance(shape, dict):
        return ["fence.shape 必须是对象"]
    if kind == "box":
        c, s = shape.get("center"), shape.get("size")
        c_ok = isinstance(c, list) and len(c) == 3 and all(_isnum(x) for x in c)
        s_ok = isinstance(s, list) and len(s) == 3 and all(_isnum(x) for x in s)
        if not c_ok:
            errs.append("box.shape.center 必须是 3 个数字 [x,y,z]")
        if not s_ok:
            errs.append("box.shape.size 必须是 3 个数字 [sx,sy,sz]")
        if isinstance(c, list) and isinstance(s, list) and c_ok and s_ok:
            if any(float(x) <= 0 for x in s):
                errs.append("box.size 每轴必须 >0")
            if float(s[0]) * float(s[1]) * float(s[2]) <= 0:
                errs.append("box 体积必须 >0")
            for i in range(3):
                ci, si = float(c[i]), float(s[i])
                if abs(ci) > LIMIT:
                    errs.append("box.center 第%d 轴 %.3f 超出 ±3m" % (i, ci))
                if abs(ci) + si / 2.0 > LIMIT:
                    errs.append("box 第%d 轴 半边 %.3f 使围栏超出 ±3m" % (i, abs(ci) + si / 2.0))
    else:                                              # polygon prism
        pts, zmin, zmax = shape.get("points"), shape.get("z_min"), shape.get("z_max")
        pts_ok = (isinstance(pts, list) and len(pts) >= 3
                  and all(isinstance(p, list) and len(p) == 2 and all(_isnum(x) for x in p) for p in pts))
        if not (isinstance(pts, list) and len(pts) >= 3):
            errs.append("polygon.points 至少 3 个点 (收到 %s)" %
                        (len(pts) if isinstance(pts, list) else type(pts).__name__))
        if isinstance(pts, list) and len(pts) >= 3 and pts_ok:
            for p in pts:
                if abs(float(p[0])) > LIMIT or abs(float(p[1])) > LIMIT:
                    errs.append("polygon 点 (%.3f, %.3f) 超出 ±3m" % (p[0], p[1])); break
        z_ok = _isnum(zmin) and _isnum(zmax)
        if not z_ok:
            errs.append("polygon.z_min/z_max 必须是数字")
        elif isinstance(zmin, (int, float)) and isinstance(zmax, (int, float)):
            if not (zmin < zmax):
                errs.append("polygon 必须 z_min < z_max (收到 %.3f / %.3f)" % (zmin, zmax))
            if abs(zmin) > LIMIT or abs(zmax) > LIMIT:
                errs.append("polygon z_min/z_max 超出 ±3m")
            if pts_ok and isinstance(pts, list) and z_ok:
                area = _poly_area(pts)
                if area <= 1e-9:
                    errs.append("polygon 面积=0 (点在一条线上, 退化)")
                elif area * (float(zmax) - float(zmin)) <= 0:
                    errs.append("polygon 体积必须 >0")
    return errs


def norm_fence(data: dict, existing: dict | None = None, items: list | None = None) -> dict:
    d = dict(existing or {})
    d.update(data or {})
    d.setdefault("kind", (d.get("shape") or {}).get("kind", "box") if isinstance(d.get("shape"), dict) else "box")
    d.setdefault("enabled", True)
    if not d.get("name"):
        raise ValueError("fences 必须有 name")
    if not d.get("id"):
        d["id"] = _unique_id(items or [], "fence_" + str(d["name"]))
    errs = validate_fence(d)
    if errs:
        raise ValueError("围栏非法: " + "; ".join(errs))
    d.setdefault("desc", "")
    out = {k: d[k] for k in ("id", "name", "kind", "shape", "desc", "enabled")}
    for k, v in d.items():
        out.setdefault(k, v)
    return out


# ── 校验/规范化: trajectories ──
def _space_point(name: str):
    try:
        sp = load_json(SPACE_POINTS)
        p = (sp.get("points") or {}).get(name)
        if p and _vec3(p.get("pos")):
            return [round(float(x), 6) for x in p["pos"]]
    except Exception:                                                          # noqa: BLE001
        pass
    return None


def _resolve_wp(wp):
    """waypoint 可以是 [x,y,z] / 'space1' / {'ref':'space1'}。返回 ([x,y,z] | None, ref | None)。"""
    if isinstance(wp, str):
        pos = _space_point(wp)
        return pos, (wp if pos else None)
    if isinstance(wp, dict):
        ref = wp.get("ref") or wp.get("point")
        if ref:
            pos = _space_point(ref)
            return pos, (ref if pos else None)
        c = wp.get("pos") or wp.get("xyz")
        if _vec3(c):
            return [float(x) for x in c], None
    if isinstance(wp, list) and len(wp) == 3 and all(_isnum(x) for x in wp):
        return [float(x) for x in wp], None
    return None, None


def norm_trajectory(data: dict, existing: dict | None = None, items: list | None = None) -> dict:
    d = dict(existing or {})
    d.update(data or {})
    errs = []
    if not d.get("name"):
        errs.append("trajectories 必须有 name")
    if d.get("kind", "自定义") not in TRAJ_KINDS:
        errs.append("trajectories.kind 必须是 %s 之一" % "/".join(TRAJ_KINDS))
    wps = d.get("waypoints")
    if not (isinstance(wps, list) and len(wps) >= 2):
        errs.append("trajectories.waypoints 至少 2 个点")
        wps = []
    if errs:
        raise ValueError("; ".join(errs))
    resolved, refs = [], []
    for i, wp in enumerate(wps):
        pos, ref = _resolve_wp(wp)
        if pos is None:
            raise ValueError("waypoints[%d] 无法解析 (%r): 既不是 [x,y,z], 也不是已知空间点名" % (i, wp))
        resolved.append([round(float(x), 6) for x in pos])
        refs.append(ref)
    d.setdefault("kind", "自定义")
    d.setdefault("speed_hint", None)
    d.setdefault("desc", "")
    if not d.get("id"):
        d["id"] = _unique_id(items or [], "traj_" + str(d["name"]))
    out = {k: d[k] for k in ("id", "name", "kind") if k in d}
    out["waypoints"] = resolved
    if any(refs):
        out["waypoint_refs"] = refs
    out["speed_hint"] = d.get("speed_hint")
    out["desc"] = d.get("desc", "")
    for k, v in d.items():
        out.setdefault(k, v)
    return out


NORM = {"objects": norm_object, "markers": norm_marker, "fences": norm_fence, "trajectories": norm_trajectory}


# ══════════════════════ 事务写 (备份→原子写→回读→失败回滚) ══════════════════════
def commit(changes: list, action: str, dry: bool = False) -> dict:
    """changes: [{'path':Path, 'new':obj, 'keys':[top键], 'before':obj}]"""
    # --dry: 只打印将写入的 diff
    if dry:
        diffs = []
        for ch in changes:
            for k in ch["keys"]:
                b = json.dumps((ch["before"] or {}).get(k), ensure_ascii=False)
                a = json.dumps(ch["new"].get(k), ensure_ascii=False)
                if b != a:
                    diffs.append("  %s [%s]\n    - %s\n    + %s" %
                                 (ch["path"].name, k, b[:600], a[:600]))
        print("[dry] 将写入 %d 个文件:" % len({str(c["path"]) for c in changes}))
        print("\n".join(diffs) if diffs else "  (无变化)")
        return {"ok": True, "action": action, "dry": True, "changed_keys": [],
                "backup": None, "readback_ok": True, "msg": "空跑: 未写入"}

    acquire_lock()
    backups = {}
    try:
        # 1) 以锁内最新内容为基准重新落 changes 的目标键 (防止锁外写者丢更新)
        for ch in changes:
            cur = load_json(ch["path"])
            # 合并: 把我们在最新内容上只改自己的键
            merged = dict(cur)
            for k in ch["keys"]:
                if k in ch["new"]:
                    merged[k] = ch["new"][k]
                else:
                    merged.pop(k, None)
            ch["merged"] = merged
        # 2) 备份 + 原子写
        written = []
        for ch in changes:
            if ch["path"].exists():
                b = backup(ch["path"])
                backups[str(ch["path"])] = str(b)
            dump_atomic(ch["path"], ch["merged"])
            written.append(ch)
        # 3) 回读核对 (外部写者可能覆盖 ⇒ 重试)
        readback_ok = True
        missing = []
        for _try in range(6):
            missing = []
            for ch in changes:
                got = load_json(ch["path"])
                for k in ch["keys"]:
                    if (k in ch["new"]) and (got.get(k) != ch["new"][k]):
                        missing.append((ch["path"], k))
                    if (k not in ch["new"]) and (k in got):
                        missing.append((ch["path"], k))
            if not missing:
                break
            time.sleep(0.05)
            # 被别家覆盖 ⇒ 只补自己的键再写一次
            for ch in changes:
                cur = load_json(ch["path"])
                m = dict(cur)
                for k in ch["keys"]:
                    if k in ch["new"]:
                        m[k] = ch["new"][k]
                    else:
                        m.pop(k, None)
                dump_atomic(ch["path"], m)
        if missing:
            readback_ok = False
        changed_keys = ["%s:%s" % (ch["path"].name, k) for ch in changes for k in ch["keys"]]
        res = {"ok": bool(readback_ok), "action": action,
               "backup": "; ".join(backups.values()) or None,
               "changed_keys": changed_keys, "readback_ok": bool(readback_ok)}
        if not readback_ok:
            # 回滚
            for p, b in backups.items():
                try:
                    shutil.copy2(b, p)
                except Exception:                                              # noqa: BLE001
                    pass
            res["msg"] = "回读不符, 已从备份回滚"
        return res
    except Exception as e:                                                     # noqa: BLE001
        for p, b in backups.items():                                           # 回滚
            try:
                shutil.copy2(b, p)
            except Exception:                                                  # noqa: BLE001
                pass
        return {"ok": False, "action": action, "backup": "; ".join(backups.values()) or None,
                "changed_keys": [], "readback_ok": False, "msg": "写入失败, 已回滚: %s" % e}
    finally:
        release_lock()


# ══════════════════════ 视图 ══════════════════════
def read_view() -> dict:
    o3 = load_json(OBJECTS3D)
    ov = load_json(OVERLAY)
    td = load_json(TRAJDISPLAY)
    deleted_map = ov.get("deleted") or {}
    deleted_flat = sorted({x for v in deleted_map.values() if isinstance(v, list) for x in v})
    return {
        "objects": o3.get("objects") or [],
        "markers": ov.get("markers") or [],
        "fences": ov.get("fences") or [],
        "trajectories": ov.get("trajectories") or [],
        "deleted_map": deleted_map,
        "deleted_flat": deleted_flat,
        "traj_show": bool(td.get("show")),
    }


def cmd_list(a) -> int:
    v = read_view()
    kinds = [a.kind] if a.kind else list(KINDS)
    if a.json:
        out = {"ok": True, "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
               "objects": v["objects"], "markers": v["markers"],
               "fences": v["fences"], "trajectories": v["trajectories"],
               "visibility": {"deleted": v["deleted_flat"], "deleted_map": v["deleted_map"],
                              "traj_show": v["traj_show"]}}
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    print("场景编辑总览  (%s)" % time.strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 70)
    if "objects" in kinds:
        print("\n[objects] %d 个 (objects3d.json)" % len(v["objects"]))
        for o in v["objects"]:
            c = o.get("center") or []
            hid = "  [隐藏]" if ("sim|%s" % o.get("name")) in v["deleted_flat"] else ""
            print("  - %-14s center=%s size=%s%s" % (o.get("name"), c, o.get("size"), hid))
    if "markers" in kinds:
        print("\n[markers] %d 个 (overlay_spec.json)" % len(v["markers"]))
        for m in v["markers"]:
            print("  - %-16s id=%-14s type=%-4s pos=%s" % (m.get("name"), m.get("id"), m.get("type"), m.get("pos")))
    if "fences" in kinds:
        print("\n[fences] %d 个 (overlay_spec.json)" % len(v["fences"]))
        for f in v["fences"]:
            en = "启用" if f.get("enabled", True) else "停用"
            print("  - %-16s id=%-14s kind=%-7s %s" % (f.get("name"), f.get("id"), f.get("kind"), en))
    if "trajectories" in kinds:
        print("\n[trajectories] %d 条 (overlay_spec.json)" % len(v["trajectories"]))
        for t in v["trajectories"]:
            print("  - %-16s id=%-14s kind=%-4s %d 点" %
                  (t.get("name"), t.get("id"), t.get("kind"), len(t.get("waypoints") or [])))
    if not a.kind:
        print("\n[visibility] 隐藏(deleted) %d 项 · 轨迹显示 show=%s"
              % (len(v["deleted_flat"]), v["traj_show"]))
    return 0


def _emit(res: dict, a) -> int:
    if getattr(a, "json", False):
        print(json.dumps(res, ensure_ascii=False))
    else:
        print("%s %s | changed=%s | readback=%s | backup=%s"
              % ("✓" if res.get("ok") else "✗", res.get("action"),
                 res.get("changed_keys"), res.get("readback_ok"), res.get("backup")))
        if res.get("msg"):
            print("  " + res["msg"])
    return 0 if res.get("ok") else 1


# ══════════════════════ 命令: add ══════════════════════
def cmd_add(a) -> int:
    kind = a.kind
    if kind not in KINDS:
        return _emit({"ok": False, "action": "add", "msg": "未知 kind %r" % kind}, a)
    try:
        data = json.loads(a.data)
        if not isinstance(data, dict):
            raise ValueError("--data 必须是 JSON 对象")
    except Exception as e:                                                     # noqa: BLE001
        return _emit({"ok": False, "action": "add", "msg": "解析 --data 失败: %s" % e}, a)
    path = KIND_FILE[kind]
    key = KIND_KEY[kind]
    doc = load_json(path)
    items = list(doc.get(key) or [])
    try:
        ent = NORM[kind](data, None, items)
    except Exception as e:                                                     # noqa: BLE001
        return _emit({"ok": False, "action": "add", "msg": str(e)}, a)
    eid = entity_id(ent, kind)
    if find_entity(items, eid) >= 0:
        return _emit({"ok": False, "action": "add", "msg": "id/name 已存在: %s" % eid}, a)
    items.append(ent)
    new = dict(doc)
    new[key] = items
    res = commit([{"path": path, "new": new, "keys": [key], "before": doc}], "add:%s:%s" % (kind, eid), a.dry)
    res["entity"] = ent
    return _emit(res, a)


# ══════════════════════ 命令: update ══════════════════════
def cmd_update(a) -> int:
    kind = a.kind
    if kind not in KINDS:
        return _emit({"ok": False, "action": "update", "msg": "未知 kind %r" % kind}, a)
    try:
        data = json.loads(a.data)
        if not isinstance(data, dict):
            raise ValueError("--data 必须是 JSON 对象")
    except Exception as e:                                                     # noqa: BLE001
        return _emit({"ok": False, "action": "update", "msg": "解析 --data 失败: %s" % e}, a)
    path = KIND_FILE[kind]
    key = KIND_KEY[kind]
    doc = load_json(path)
    items = list(doc.get(key) or [])
    i = find_entity(items, a.id)
    if i < 0:
        return _emit({"ok": False, "action": "update", "msg": "找不到 id/name=%s" % a.id}, a)
    try:
        ent = NORM[kind](data, items[i], items)
    except Exception as e:                                                     # noqa: BLE001
        return _emit({"ok": False, "action": "update", "msg": str(e)}, a)
    ent["id"] = ent.get("id") or entity_id(items[i], kind)
    items[i] = ent
    new = dict(doc)
    new[key] = items
    res = commit([{"path": path, "new": new, "keys": [key], "before": doc}],
                 "update:%s:%s" % (kind, entity_id(ent, kind)), a.dry)
    res["entity"] = ent
    return _emit(res, a)


# ══════════════════════ 命令: rm ══════════════════════
def cmd_rm(a) -> int:
    kind = a.kind
    if kind not in KINDS:
        return _emit({"ok": False, "action": "rm", "msg": "未知 kind %r" % kind}, a)
    path = KIND_FILE[kind]
    key = KIND_KEY[kind]
    doc = load_json(path)
    items = list(doc.get(key) or [])
    i = find_entity(items, a.id)
    if i < 0:
        return _emit({"ok": False, "action": "rm", "msg": "找不到 id/name=%s" % a.id}, a)
    removed = items.pop(i)
    new = dict(doc)
    if kind in ("markers", "fences", "trajectories") and not items:
        new.pop(key, None)            # 原文件没有这个键 ⇒ 清空后一并移除, 回到原键集
    else:
        new[key] = items
    changes = [{"path": path, "new": new, "keys": [key], "before": doc}]
    # objects 删除: 顺手清掉它在 deleted 黑名单里的残留 (同名)
    if kind == "objects":
        ov = load_json(OVERLAY)
        del_map = copy.deepcopy(ov.get("deleted") or {})
        hit = "sim|%s" % removed.get("name")
        touched = False
        for cam, lst in list(del_map.items()):
            if isinstance(lst, list) and hit in lst:
                del_map[cam] = [x for x in lst if x != hit]
                touched = True
        if touched:
            nov = dict(ov)
            nov["deleted"] = del_map
            changes.append({"path": OVERLAY, "new": nov, "keys": ["deleted"], "before": ov})
    res = commit(changes, "rm:%s:%s" % (kind, entity_id(removed, kind)), a.dry)
    res["entity"] = removed
    return _emit(res, a)


# ══════════════════════ 命令: show / hide (objects 显隐) ══════════════════════
def _toggle_visible(a, hide: bool) -> int:
    kind = getattr(a, "kind", "objects")
    if kind != "objects":
        return _emit({"ok": False, "action": "hide" if hide else "show",
                      "msg": "show/hide 只支持 --kind objects (显隐黑名单语义)"}, a)
    name = a.name or a.id
    o3 = load_json(OBJECTS3D)
    objs = o3.get("objects") or []
    i = find_entity(objs, name)
    if i < 0:
        return _emit({"ok": False, "action": "hide" if hide else "show",
                      "msg": "对象不存在: %s" % name}, a)
    objname = objs[i].get("name")
    cam = a.cam or "arm"
    ov = load_json(OVERLAY)
    del_map = copy.deepcopy(ov.get("deleted") or {})
    cur = list(del_map.get(cam) or [])
    hit = "sim|%s" % objname
    if hide:
        if hit not in cur:
            cur.append(hit)
    else:
        cur = [x for x in cur if x != hit]
    del_map[cam] = sorted(set(cur))
    nov = dict(ov)
    nov["deleted"] = del_map
    res = commit([{"path": OVERLAY, "new": nov, "keys": ["deleted"], "before": ov}],
                 ("hide" if hide else "show") + ":objects:%s" % objname, a.dry)
    res["visibility"] = {"cam": cam, "deleted": del_map[cam]}
    return _emit(res, a)


def cmd_show(a):
    return _toggle_visible(a, False)


def cmd_hide(a):
    return _toggle_visible(a, True)


# ══════════════════════ 命令: set ══════════════════════
def cmd_set(a) -> int:
    if a.json_delete:
        try:
            data = json.loads(Path(a.json_delete).read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not all(isinstance(v, list) for v in data.values()):
                raise ValueError("期望 {cam: [ids...], ...}")
        except Exception as e:                                                 # noqa: BLE001
            return _emit({"ok": False, "action": "set:json-delete", "msg": "读取失败: %s" % e}, a)
        ov = load_json(OVERLAY)
        nov = dict(ov)
        nov["deleted"] = data
        res = commit([{"path": OVERLAY, "new": nov, "keys": ["deleted"], "before": ov}],
                     "set:json-delete", a.dry)
        return _emit(res, a)
    if a.traj_show is not None:
        td = load_json(TRAJDISPLAY)
        ntd = dict(td)
        ntd["show"] = (a.traj_show == "on")
        res = commit([{"path": TRAJDISPLAY, "new": ntd, "keys": ["show"], "before": td}],
                     "set:traj-show:%s" % a.traj_show, a.dry)
        return _emit(res, a)
    return _emit({"ok": False, "action": "set", "msg": "要 --json-delete <path> 或 --traj-show on|off"}, a)


# ══════════════════════ 命令: check ══════════════════════
def _range(vals):
    vals = [v for v in vals if _isnum(v)]
    return (min(vals), max(vals)) if vals else (None, None)


def cmd_check(a) -> int:
    v = read_view()
    files = {"objects3d.json": OBJECTS3D, "overlay_spec.json": OVERLAY,
             "traj_display.json": TRAJDISPLAY, "space_points.json": SPACE_POINTS,
             "scene_state.json(只读)": SCENE_STATE}
    fstat = {n: (p.exists(), (p.stat().st_size if p.exists() else 0)) for n, p in files.items()}
    # 坐标范围
    o_c = [x for o in v["objects"] for x in (o.get("center") or []) if _isnum(x)]
    m_c = [x for m in v["markers"] for x in (m.get("pos") or []) if _isnum(x)]
    t_c = [x for t in v["trajectories"] for wp in (t.get("waypoints") or []) for x in wp if _isnum(x)]
    ranges = {"objects.center": _range(o_c), "markers.pos": _range(m_c), "trajectories.waypoints": _range(t_c)}
    # 围栏合法性
    fence_bad = {}
    for f in v["fences"]:
        errs = validate_fence(f)
        if errs:
            fence_bad[entity_id(f, "fences")] = errs
    out_of_range = []
    for o in v["objects"]:
        for i, x in enumerate(o.get("center") or []):
            if _isnum(x) and abs(x) > LIMIT:
                out_of_range.append("object %s center[%d]=%.3f" % (o.get("name"), i, x))
    for m in v["markers"]:
        for i, x in enumerate(m.get("pos") or []):
            if _isnum(x) and abs(x) > LIMIT:
                out_of_range.append("marker %s pos[%d]=%.3f" % (m.get("name"), i, x))
    out = {"ok": not fence_bad, "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
           "counts": {"objects": len(v["objects"]), "markers": len(v["markers"]),
                      "fences": len(v["fences"]), "trajectories": len(v["trajectories"]),
                      "deleted": len(v["deleted_flat"])},
           "traj_show": v["traj_show"], "coord_ranges_m": ranges,
           "fence_invalid": fence_bad, "out_of_range": out_of_range,
           "files": {n: {"exists": e, "bytes": b} for n, (e, b) in fstat.items()}}
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    print("场景数据体检  (%s)" % out["generated_at"])
    print("=" * 60)
    print("文件:")
    for n, (e, b) in fstat.items():
        print("  %-22s %s %s" % (n, "✓存在" if e else "✗缺失", "%d B" % b if e else ""))
    print("条数: objects=%d markers=%d fences=%d trajectories=%d (隐藏 %d)"
          % (len(v["objects"]), len(v["markers"]), len(v["fences"]),
             len(v["trajectories"]), len(v["deleted_flat"])))
    print("轨迹显示 show=%s" % v["traj_show"])
    print("坐标范围 (m):")
    for k, (lo, hi) in ranges.items():
        print("  %-22s %s .. %s" % (k, ("%.3f" % lo) if lo is not None else "-",
                                    ("%.3f" % hi) if hi is not None else "-"))
    print("围栏合法性: %s" % ("全部合法" if not fence_bad else "✗ %d 个非法" % len(fence_bad)))
    for fid, errs in fence_bad.items():
        print("   ✗ %s: %s" % (fid, "; ".join(errs)))
    print("坐标越界(±3m): %s" % ("无" if not out_of_range else out_of_range))
    return 0 if not fence_bad else 1


# ══════════════════════ 命令: path ══════════════════════
def cmd_path(a) -> int:
    d = {"objects3d.json": str(OBJECTS3D.resolve()),
         "overlay_spec.json": str(OVERLAY.resolve()),
         "traj_display.json": str(TRAJDISPLAY.resolve()),
         "space_points.json": str(SPACE_POINTS.resolve())}
    if a.json:
        print(json.dumps(d, ensure_ascii=False, indent=1))
    else:
        for k, p in d.items():
            print("%-20s %s" % (k, p))
    return 0


# ══════════════════════ CLI ══════════════════════
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="scene_edit.py", description="场景编辑器后端 (数据层)")
    ap.add_argument("--json", action="store_true", help="机器可读 JSON 输出")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="机器可读 JSON 输出")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="列出四类实体", parents=[common])
    p.add_argument("--kind", choices=list(KINDS))
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("add", help="新增", parents=[common])
    p.add_argument("--kind", required=True, choices=list(KINDS))
    p.add_argument("--data", required=True, help="实体 JSON")
    p.add_argument("--dry", action="store_true")
    p.set_defaults(fn=cmd_add)

    p = sub.add_parser("update", help="按 id/name 改", parents=[common])
    p.add_argument("--kind", required=True, choices=list(KINDS))
    p.add_argument("--id", required=True)
    p.add_argument("--data", required=True)
    p.add_argument("--dry", action="store_true")
    p.set_defaults(fn=cmd_update)

    p = sub.add_parser("rm", help="按 id/name 删", parents=[common])
    p.add_argument("--kind", required=True, choices=list(KINDS))
    p.add_argument("--id", required=True)
    p.add_argument("--dry", action="store_true")
    p.set_defaults(fn=cmd_rm)

    for name, fn in (("show", cmd_show), ("hide", cmd_hide)):
        p = sub.add_parser(name, help="objects 显示/隐藏 (deleted 黑名单)", parents=[common])
        p.add_argument("--kind", default="objects", choices=["objects"])
        p.add_argument("--id")
        p.add_argument("--name")
        p.add_argument("--cam", default="arm")
        p.add_argument("--dry", action="store_true")
        p.set_defaults(fn=fn)

    p = sub.add_parser("set", help="整体设置: --json-delete / --traj-show", parents=[common])
    p.add_argument("--json-delete", dest="json_delete", default=None)
    p.add_argument("--traj-show", dest="traj_show", choices=["on", "off"], default=None)
    p.add_argument("--dry", action="store_true")
    p.set_defaults(fn=cmd_set)

    p = sub.add_parser("check", help="数据体检", parents=[common])
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("path", help="打印真源文件绝对路径", parents=[common])
    p.set_defaults(fn=cmd_path)
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    try:
        return a.fn(a)
    finally:
        release_lock()


if __name__ == "__main__":
    sys.exit(main())
