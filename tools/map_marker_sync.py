#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""map_marker_sync.py — 建图产物 ↔ 现场标记 的「地图同步」工具 (2026-10-10 老倪)

老倪原话: 「也要能够通过建图，VR，AR 等虚拟现实技术，给真实的现场环境添加标记，同步地图等」。

本工具把**建图产物**扫出来, 与场景里的**现场标记 / 对象 / 空间点**做对齐同步, 让每个标记
能溯源到它属于**哪次建图**、在**哪个坐标系**、是否**已过期**。

建图产物 (真源, 只读):
  · zmax_data/gs_assets/<资产>/ gs.ply · gs.splat · cameras.json (T_cam2world, base_link) · images/
  · zmax_data/gs_scan/<会话>/   frames/*.jpg · frames.jsonl (逐帧 pose, frame=base_link)
  · zmax_data/gs_map/status.json  在役建图会话状态
  · data/scene/{objects3d,overlay_spec}.json  场景真源 (ts / mtime)

对齐对象 (标记/对象/空间点):
  · overlay_spec.json markers[]  —— 现场标记 (经 tools/scene_edit.py list --json 读)
  · objects3d.json   objects[]   —— 场景对象
  · data/skills/l2_atomic/space_points.json  points —— 空间点

接口:
  python3 tools/map_marker_sync.py                # 人读表: 地图资产 / 标记 / 绑定关系 / 新鲜度
  python3 tools/map_marker_sync.py --json         # 机器可读
  python3 tools/map_marker_sync.py sync --dry     # 只报将写什么 (不落盘)
  python3 tools/map_marker_sync.py sync --apply   # 经 tools/scene_edit.py 写 markers[].map_ref
  python3 tools/map_marker_sync.py check          # 地图资产存在性 / 绑定完整性

纪律 (硬约束):
  · **绝不自己写 JSON**: sync --apply 一律经 tools/scene_edit.py 的写路径 (备份/原子写/回读/回滚)。
  · 只读建图产物, 不发真机动作。
  · 缺什么 ⇒ 如实报 (missing/coord_only/none), 不假装绑定成功。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# ── 路径 (环境变量可重定向 ⇒ 测试在沙箱副本上真跑, 不碰在役文件) ──
REPO = Path(os.environ.get("ZMAX_REPO", Path(__file__).resolve().parents[1]))
SCENE_DIR = Path(os.environ.get("ZMAX_SCENE_DIR", REPO / "data" / "scene"))
OBJECTS3D = SCENE_DIR / "objects3d.json"
OVERLAY = SCENE_DIR / "overlay_spec.json"
GS_ASSETS = Path(os.environ.get("ZMAX_GS_ASSETS", REPO / "zmax_data" / "gs_assets"))
GS_SCAN = Path(os.environ.get("ZMAX_GS_SCAN", REPO / "zmax_data" / "gs_scan"))
GS_MAP = Path(os.environ.get("ZMAX_GS_MAP", REPO / "zmax_data" / "gs_map"))
SPACE_POINTS = Path(os.environ.get("ZMAX_SPACE_POINTS",
                                   REPO / "data" / "skills" / "l2_atomic" / "space_points.json"))
SCENE_EDIT = REPO / "tools" / "scene_edit.py"
PY = os.environ.get("ZMAX_PY", sys.executable)

BIND_MAX_M = 1.2          # 标记 → 最近视点距离 ≤ 此值才算"视点可证"绑定 (m)
VIEW_SAMPLE = 240         # 每个资产的视点采样上限 (防大 cameras.json 拖慢)
STALE_DAYS = 2.0          # 标注早于最新建图产物 > N 天 → 判定已过期
PLY_MIN_BYTES = 100_000   # gs.ply 小于此值视为空壳 (实测有 4 B 的占位文件)


# ══════════════════════ 小工具 ══════════════════════
def _mtime(p: Path):
    try:
        return p.stat().st_mtime if p.exists() else None
    except OSError:
        return None


def _iso(epoch):
    if epoch is None:
        return None
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(epoch)))
    except Exception:                                                          # noqa: BLE001
        return None


def _read_json(p: Path) -> dict:
    try:
        return json.loads(Path(p).read_text(encoding="utf-8")) or {}
    except Exception:                                                          # noqa: BLE001
        return {}


def _parse_dt(s):
    """'2026-10-08 13:19:51' → epoch; 失败返回 None。"""
    if not s or not isinstance(s, str):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return time.mktime(time.strptime(s.strip(), fmt))
        except Exception:                                                      # noqa: BLE001
            continue
    return None


def _sample(lst, n=VIEW_SAMPLE):
    if not lst:
        return []
    if len(lst) <= n:
        return lst
    step = max(1, len(lst) // n)
    return lst[::step][:n]


def _dist(a, b):
    return sum((float(x) - float(y)) ** 2 for x, y in zip(a, b)) ** 0.5


# ══════════════════════ ① 扫建图产物 ══════════════════════
def _cameras_views(cam_json: Path):
    """cameras.json → 视点位置列表 (T_cam2world 平移, base_link)。"""
    d = _read_json(cam_json)
    out = []
    for fr in (d.get("frames") or []):
        pos = fr.get("pos")
        if isinstance(pos, list) and len(pos) == 3:
            out.append([float(x) for x in pos])
    coord = "base_link" if d.get("convention") else "base_link"
    return out, coord, len(d.get("frames") or []), d.get("convention")


def _jsonl_views(jsonl: Path):
    """frames.jsonl → 视点位置 (每行 pose_before.x/y/z, frame=base_link)。"""
    out = []
    frame = None
    try:
        with open(jsonl, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    o = json.loads(ln)
                except Exception:                                              # noqa: BLE001
                    continue
                pb = o.get("pose_before") or {}
                if frame is None:
                    frame = pb.get("frame")
                if all(k in pb for k in ("x", "y", "z")):
                    out.append([float(pb["x"]), float(pb["y"]), float(pb["z"])])
    except Exception:                                                          # noqa: BLE001
        pass
    return out, (frame or "base_link")


def scan_map_assets():
    """返回所有建图资产/会话/在役状态的清单 (每个含 kind/路径/产物/视点/mtime)。"""
    assets = []
    # ── gs_assets/<资产> (3DGS 产物) ──
    if GS_ASSETS.is_dir():
        for d in sorted(GS_ASSETS.iterdir()):
            if not d.is_dir():
                continue
            ply, splat = d / "gs.ply", d / "gs.splat"
            cam = d / "cameras.json"
            views, coord, ncam, conv = ([], "base_link", 0, None)
            if cam.exists():
                views, coord, ncam, conv = _cameras_views(cam)
            imgs = d / "images"
            n_images = len(list(imgs.glob("*"))) if imgs.is_dir() else 0
            ply_b = ply.stat().st_size if ply.exists() else 0
            real = ply.exists() and ply_b >= PLY_MIN_BYTES
            mt = max([m for m in (_mtime(ply), _mtime(splat), _mtime(cam), _mtime(d)) if m],
                     default=None)
            if not (ply.exists() or splat.exists() or cam.exists() or n_images):
                continue                      # 空目录不算资产
            assets.append({
                "id": "gs_assets/" + d.name, "path": str(d), "kind": "3dgs_asset",
                "has_ply": ply.exists(), "ply_bytes": ply_b, "real": bool(real),
                "has_splat": splat.exists(),
                "splat_bytes": splat.stat().st_size if splat.exists() else 0,
                "cameras_n": ncam, "images": n_images,
                "views": _sample(views), "n_views": len(views), "coord": coord,
                "mtime": mt, "mtime_iso": _iso(mt),
            })
    # ── gs_scan/<会话> (扫场帧) ──
    if GS_SCAN.is_dir():
        for d in sorted(GS_SCAN.iterdir()):
            if not d.is_dir():
                continue
            fr = d / "frames"
            jl = d / "frames.jsonl"
            n_frames = len(list(fr.glob("*.jpg"))) if fr.is_dir() else 0
            views, coord = ([], "base_link")
            if jl.exists():
                views, coord = _jsonl_views(jl)
            mt = max([m for m in (_mtime(jl), _mtime(fr), _mtime(d)) if m], default=None)
            if not (n_frames or jl.exists()):
                continue
            assets.append({
                "id": "gs_scan/" + d.name, "path": str(d), "kind": "scan_session",
                "has_ply": False, "ply_bytes": 0, "real": bool(n_frames > 0),
                "has_splat": False, "splat_bytes": 0,
                "cameras_n": 0, "images": n_frames,
                "views": _sample(views), "n_views": len(views), "coord": coord,
                "mtime": mt, "mtime_iso": _iso(mt),
                "session_meta": _read_json(d / "session_meta.json"),
            })
    # ── gs_map (在役建图状态) ──
    st = GS_MAP / "status.json"
    if st.exists():
        s = _read_json(st)
        mt = _mtime(st)
        sess = s.get("session")
        views = []
        if sess and Path(sess).is_dir():
            jl = Path(sess) / "frames.jsonl"
            if jl.exists():
                views, _c = _jsonl_views(jl)
        assets.append({
            "id": "gs_map(live)", "path": str(GS_MAP), "kind": "live_map",
            "has_ply": False, "ply_bytes": 0, "real": True,
            "has_splat": False, "splat_bytes": 0, "cameras_n": 0, "images": 0,
            "views": _sample(views), "n_views": len(views), "coord": "base_link",
            "mtime": _mtime(st), "mtime_iso": _iso(mt),
            "status": s,
        })
    return assets


# ══════════════════════ ② 扫场景侧实体 (标记/对象/空间点) ══════════════════════
def _scene_edit_list():
    """经 tools/scene_edit.py list --json 读场景真源 (与 GUI 同一条读路径)。"""
    try:
        r = subprocess.run([PY, str(SCENE_EDIT), "list", "--json"],
                           cwd=str(REPO), capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and (r.stdout or "").strip():
            return json.loads(r.stdout)
    except Exception:                                                          # noqa: BLE001
        pass
    # 退路: 直接读文件 (只读, 不写)
    ov = _read_json(OVERLAY)
    o3 = _read_json(OBJECTS3D)
    return {"ok": True, "objects": o3.get("objects") or [],
            "markers": ov.get("markers") or [], "fences": ov.get("fences") or [],
            "trajectories": ov.get("trajectories") or []}


def scan_entities():
    """标记 / 对象 / 空间点 —— 统一成 [{kind,id,name,pos,coord,created_at,...}]。"""
    view = _scene_edit_list()
    ents = []
    for m in (view.get("markers") or []):
        if isinstance(m, dict) and isinstance(m.get("pos"), list) and len(m["pos"]) == 3:
            ents.append({"kind": "marker", "id": m.get("id"), "name": m.get("name"),
                         "pos": [float(x) for x in m["pos"]], "coord": "base",
                         "created_at": m.get("created_at"), "type": m.get("type"),
                         "map_ref": m.get("map_ref")})
    for o in (view.get("objects") or []):
        if isinstance(o, dict) and isinstance(o.get("center"), list) and len(o["center"]) == 3:
            ents.append({"kind": "object", "id": o.get("name"), "name": o.get("name"),
                         "pos": [float(x) for x in o["center"]], "coord": o.get("coord", "base"),
                         "created_at": None, "type": "object",
                         "map_ref": o.get("map_ref")})
    sp = _read_json(SPACE_POINTS)
    for name, p in (sp.get("points") or {}).items():
        pos = (p or {}).get("pos")
        if isinstance(pos, list) and len(pos) == 3:
            ents.append({"kind": "space_point", "id": name, "name": name,
                         "pos": [float(x) for x in pos], "coord": sp.get("frame", "base_link"),
                         "created_at": p.get("recorded_at"), "type": "space_point",
                         "map_ref": None})
    return ents, view


# ══════════════════════ ③ 绑定 + 新鲜度 ══════════════════════
def _scene_ts():
    """场景**编辑**真源时间 (epoch): 用 objects3d.json 的语义 ts (人工/示教编辑时刻)。

    ⚠️ 不能用 overlay_spec.json 的 ts/mtime —— 它被在役 L5 感知环每秒重写, 其时间恒 = now,
    拿它当"场景 ts"会让所有建图产物都被误判过期。overlay 的实时时间另存 scene_live_ts 供展示。"""
    d = _read_json(OBJECTS3D)
    if isinstance(d.get("ts"), (int, float)):
        return float(d["ts"])
    return _mtime(OBJECTS3D)


def _scene_live_ts():
    """在役感知环写入时间 (仅展示用, 不参与过期判定)。"""
    d = _read_json(OVERLAY)
    v = d.get("ts")
    return float(v) if isinstance(v, (int, float)) else _mtime(OVERLAY)


def _newest_map_mtime(assets):
    return max([a["mtime"] for a in assets if a.get("mtime")], default=None)


def bind_entity(ent, assets, scene_ts, newest_map=None):
    """给一个实体算 map_ref: 归属哪次建图 / 坐标系 / 新鲜度。

    scene_ts = 场景编辑真源时间 (objects3d.ts); newest_map = 最新建图产物 mtime。"""
    pos = ent["pos"]
    best, best_d = None, None
    for a in assets:
        for v in a["views"]:
            d = _dist(pos, v)
            if best_d is None or d < best_d:
                best_d, best = d, a
    if newest_map is None:
        newest_map = _newest_map_mtime(assets)
    reasons = []
    if best is None:
        bind = "none"
        reasons.append("无任何建图视点可绑定 (无 cameras.json / frames.jsonl)")
    elif best_d is not None and best_d <= BIND_MAX_M:
        bind = "nearest_viewpoint"
    else:
        bind = "coord_only"
        reasons.append("最近视点 %.2fm > %.1fm (仅坐标系一致, 无视点覆盖)" % (best_d, BIND_MAX_M))
    ent_epoch = _parse_dt(ent.get("created_at"))
    # ① 绑定资产本身无效
    if best is not None and not best.get("real", True):
        reasons.append("绑定资产无真产物 (gs.ply 缺失/过小=空壳)")
    # ② 绑定到旧图 (存在更新的建图产物)
    if (best is not None and best.get("mtime") and newest_map
            and best["mtime"] < newest_map - 3600):
        reasons.append("绑定到较旧建图 (最新建图晚 %.1fh)" % ((newest_map - best["mtime"]) / 3600.0))
    # ③ 标注早于最新建图 > STALE_DAYS 天
    if newest_map and ent_epoch and (newest_map - ent_epoch) > STALE_DAYS * 86400:
        reasons.append("标注早于最新建图 %.1f天 > %.0f天" %
                       ((newest_map - ent_epoch) / 86400.0, STALE_DAYS))
    # ④ 最新建图早于场景编辑真源 (地图没跟上场景改动)
    if newest_map and scene_ts and newest_map < scene_ts - 60:
        reasons.append("最新建图早于场景编辑真源 %.1fh" % ((scene_ts - newest_map) / 3600.0))
    stale = bool(reasons)
    return {
        "coord": ent.get("coord", "base"),
        "asset": best["id"] if best else None,
        "asset_kind": best["kind"] if best else None,
        "asset_path": best["path"] if best else None,
        "asset_mtime": best["mtime_iso"] if best else None,
        "bind": bind,
        "dist_m": round(best_d, 3) if best_d is not None else None,
        "calib": "handeye TSAI (cam→base_link)" if best and best.get("n_views") else None,
        "stale": stale,
        "reasons": reasons,
        "synced_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def build_report():
    assets = scan_map_assets()
    ents, view = scan_entities()
    scene_ts = _scene_ts()
    newest_map = _newest_map_mtime(assets)
    bindings = []
    for e in ents:
        mr = bind_entity(e, assets, scene_ts, newest_map)
        bindings.append({"entity": e, "map_ref": mr})
    return {"assets": assets, "entities": ents, "bindings": bindings,
            "scene_ts": scene_ts, "scene_ts_iso": _iso(scene_ts),
            "scene_live_ts_iso": _iso(_scene_live_ts()),
            "newest_map_iso": _iso(newest_map),
            "view": view}


# ══════════════════════ 输出 ══════════════════════
def _fmt_table(r):
    out = []
    A, E, B = r["assets"], r["entities"], r["bindings"]
    out.append("地图同步  ·  建图产物 ↔ 现场标记  (%s)" % time.strftime("%Y-%m-%d %H:%M:%S"))
    out.append("=" * 78)
    out.append("场景编辑真源时间(objects3d.ts): %s" % (r.get("scene_ts_iso") or "-"))
    out.append("最新建图产物: %s   ·   在役感知环写入: %s"
               % (r.get("newest_map_iso") or "-", r.get("scene_live_ts_iso") or "-"))
    out.append("")
    out.append("【① 地图资产】%d 个" % len(A))
    for a in A:
        flag = {"3dgs_asset": "🧊", "scan_session": "📷", "live_map": "🛰"}.get(a["kind"], "·")
        real = "真产物" if a.get("real") else "空壳/无产物"
        out.append("  %s %-34s %-12s 视点%4d 帧%6d ply=%s %s  mtime=%s"
                   % (flag, a["id"], a["kind"], a.get("n_views", 0), a.get("images", 0),
                      ("%.1fMB" % (a["ply_bytes"] / 1e6)) if a.get("has_ply") else "—",
                      real, a.get("mtime_iso") or "-"))
    out.append("")
    out.append("【② 标记 / 对象 / 空间点】%d 个" % len(E))
    if not E:
        out.append("  (无 —— overlay_spec.json 无 markers, objects3d/space_points 也空)")
    for e in E:
        out.append("  [%s] %-16s pos=%s coord=%s" %
                   (e["kind"], str(e["name"])[:16],
                    [round(x, 3) for x in e["pos"]], e.get("coord")))
    out.append("")
    out.append("【③ 绑定关系】(标记 → 哪次建图 / 坐标系)")
    for b in B:
        e, mr = b["entity"], b["map_ref"]
        out.append("  %-16s → %s (%s) dist=%s" %
                   (str(e["name"])[:16], mr["asset"] or "无", mr["bind"],
                    mr["dist_m"] if mr["dist_m"] is not None else "-"))
    out.append("")
    out.append("【④ 新鲜度】")
    n_stale = sum(1 for b in B if b["map_ref"]["stale"])
    out.append("  过期/存疑: %d / %d" % (n_stale, len(B)))
    for b in B:
        mr = b["map_ref"]
        if mr["stale"]:
            out.append("  ⚠ %-16s %s" % (str(b["entity"]["name"])[:16], "; ".join(mr["reasons"])))
    return "\n".join(out)


def _emit_json(r):
    print(json.dumps({
        "ok": True, "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "scene_ts": r.get("scene_ts"), "scene_ts_iso": r.get("scene_ts_iso"),
        "scene_live_ts_iso": r.get("scene_live_ts_iso"),
        "newest_map_iso": r.get("newest_map_iso"),
        "assets": [{k: a.get(k) for k in
                    ("id", "path", "kind", "real", "has_ply", "ply_bytes", "has_splat",
                     "splat_bytes", "cameras_n", "images", "n_views", "coord", "mtime_iso")}
                   for a in r["assets"]],
        "entities": r["entities"],
        "bindings": [{"kind": b["entity"]["kind"], "id": b["entity"]["id"],
                      "name": b["entity"]["name"], "map_ref": b["map_ref"]} for b in r["bindings"]],
        "stale_count": sum(1 for b in r["bindings"] if b["map_ref"]["stale"]),
    }, ensure_ascii=False, indent=1))


# ══════════════════════ 命令 ══════════════════════
def cmd_all(a):
    r = build_report()
    if a.json:
        _emit_json(r)
    else:
        print(_fmt_table(r))
    return 0


def _target_kinds(a):
    ks = (getattr(a, "kinds", None) or "markers")
    return {k.strip() for k in str(ks).split(",") if k.strip()}


def cmd_sync(a):
    r = build_report()
    kinds = _target_kinds(a)
    grp = {"marker": "markers", "object": "objects"}      # 实体 kind(单数) → 归组
    todo = []
    for b in r["bindings"]:
        e = b["entity"]
        if e["kind"] == "space_point":
            continue                       # 空间点是只读引用, 不写回
        g = grp.get(e["kind"])
        if g is None or g not in kinds:
            continue
        eid = e["id"] or e["name"]
        if eid is None:
            continue
        todo.append((e, b["map_ref"], g))
    if a.apply:
        return _do_apply(todo, r)
    # --dry (或默认 sync 无 --apply) → 只报将写什么
    print("[dry] 地图同步 · 将写入 %d 个%s 的 map_ref (经 tools/scene_edit.py, 未落盘)"
          % (len(todo), "/".join(sorted(kinds))))
    if not todo:
        print("  (无可写实体 —— 场景里没有对应标记/对象)")
        return 0
    for e, mr, kind in todo:
        print("  %s [%s] %s" % (kind, e["id"] or e["name"], e["name"]))
        print("    + map_ref = %s" % json.dumps(mr, ensure_ascii=False))
    return 0


def _do_apply(todo, r):
    print("地图同步 · --apply (经 tools/scene_edit.py 写路径)")
    if not todo:
        print("  (无可写实体, 未写入)")
        return 0
    n_ok = 0
    for e, mr, kind in todo:
        eid = e["id"] or e["name"]
        data = json.dumps({"map_ref": mr}, ensure_ascii=False)
        try:
            rr = subprocess.run([PY, str(SCENE_EDIT), "update", "--kind", kind,
                                 "--id", str(eid), "--data", data, "--json"],
                                cwd=str(REPO), capture_output=True, text=True, timeout=30)
            payload = json.loads((rr.stdout or "{}").strip() or "{}")
        except Exception as ex:                                                # noqa: BLE001
            payload = {"ok": False, "msg": str(ex)}
        ok = bool(payload.get("ok"))
        n_ok += int(ok)
        print("  %s %-16s %s" % ("✓" if ok else "✗", str(e["name"])[:16],
                                 ("backup=%s" % payload.get("backup")) if ok
                                 else ("err=%s" % payload.get("msg"))))
    print("  → %d/%d 写入成功 (备份+原子写+回读由 scene_edit 负责)" % (n_ok, len(todo)))
    return 0 if n_ok == len(todo) else 1


def cmd_check(a):
    r = build_report()
    A, B = r["assets"], r["bindings"]
    missing, unbound = [], []
    real_all = [x for x in A if x.get("real")]
    if not real_all:
        missing.append("无任何含真产物的建图资产 (gs.ply 全空壳/缺失)")
    for b in B:
        if b["map_ref"]["bind"] == "none":
            unbound.append(b["entity"]["name"])
    ok = (not missing) and (not unbound)
    payload = {
        "ok": ok, "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "assets_total": len(A), "assets_real": len(real_all),
        "assets_shell": [x["id"] for x in A if not x.get("real")],
        "entities": len(B), "unbound": unbound, "missing": missing,
        "stale_count": sum(1 for b in B if b["map_ref"]["stale"]),
    }
    if a.json:
        print(json.dumps(payload, ensure_ascii=False, indent=1))
        return 0 if ok else 1
    print("地图同步体检  (%s)" % payload["generated_at"])
    print("=" * 60)
    print("地图资产: 共 %d 个 · 含真产物 %d 个 · 空壳 %d 个"
          % (payload["assets_total"], payload["assets_real"], len(payload["assets_shell"])))
    print("绑定: %d 个实体 · 未绑定 %d · 过期/存疑 %d"
          % (payload["entities"], len(unbound), payload["stale_count"]))
    if missing:
        print("✗ 缺失: %s" % "; ".join(missing))
    if unbound:
        print("✗ 未绑定实体: %s" % ", ".join(str(u) for u in unbound[:20]))
    if ok:
        print("✓ 建图资产存在 · 绑定完整")
    return 0 if ok else 1


# ══════════════════════ CLI ══════════════════════
def build_parser():
    ap = argparse.ArgumentParser(prog="map_marker_sync.py",
                                 description="建图产物 ↔ 现场标记 地图同步")
    ap.add_argument("--json", action="store_true", help="机器可读 JSON 输出")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("sync", help="把标记归集到 markers[].map_ref (经 scene_edit)")
    p.add_argument("--dry", action="store_true", help="只报将写什么, 不落盘")
    p.add_argument("--apply", action="store_true", help="真写 (经 tools/scene_edit.py)")
    p.add_argument("--kinds", default="markers",
                   help="要同步的实体类, 逗号分隔 (默认 markers; 可选 objects)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_sync)

    p = sub.add_parser("check", help="建图资产存在性 / 绑定完整性")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("report", help="人读表 (同默认)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_all)
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    if not getattr(a, "fn", None):
        a.fn = cmd_all
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
