#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dashboard_source.py — Z-MAX 大屏**统一数据源**(单一 JSON)。

一句话: 把散在各只读采集器里的关键字段(远程监控 / 数据资产 / 模型+算力 / 场景 / 版本同源)
聚成**一份** JSON, 既给人读摘要, 又落盘到 web 可读的位置, 供统一 web 页 / 飞书卡片直接吃。

数据来源(全部**复用现成只读工具**, 本脚本不自己乱扫盘):
  · tools/remote_monitor_aggregate.py  → 18 端点的 ok/stale/同源判定
  · tools/dataset_inventory.py         → 数据资产总量/分类/建图/报告
  · tools/model_inventory.py           → GPU 实时 + 四层模型在役/就绪 + 训练
  · tools/scene_edit.py (check 语义)    → 场景四类实体条数/围栏合法性/越界
  · tools/verify_version_sync.py       → 版本同源(本地各同步点 + 远端 tag/Release)

输出结构(单一 JSON):
  {generated_at, version, gpu, datasets, models, scene,
   remote:{endpoints_total, endpoints_ok, endpoints_err, stale[], frame_age_s, same_source[], mismatch[]},
   version_sync:{ok, canonical, remote_has_tag, release_tag, deviations}}

写盘:
  · 权威: <repo>/zmax_data/datapush/dashboard.json   (大屏/交付用)
  · web : <repo>/tools/web/dashboard.json            (与 unified_app.html 同目录, 供 fetch('./dashboard.json'))

红线(严格遵守):
  · **只读**: 只调别的只读工具的采集函数; 不写业务文件(除本脚本自己的 dashboard.json)。
  · **脱敏**: 所有输出先过 remote_monitor_aggregate 的 redact(); 落盘/打印前再 assert_no_secrets 一次。
  · 网络不通的端点在 remote 里如实记 err, 绝不编造字段。

用法:
  python3 tools/dashboard_source.py                 # 人读摘要 + 落盘
  python3 tools/dashboard_source.py --json          # 单一 JSON 到 stdout(同时落盘)
  python3 tools/dashboard_source.py --offline       # 跳过所有网络采集(远程/版本远端)
  python3 tools/dashboard_source.py --json-out p.json   # 额外落一份到指定路径
  python3 tools/dashboard_source.py --no-write       # 只打印, 不写盘
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta

# ── 让 tools/ 下的兄弟模块可 import(脚本自身目录) ──
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import dataset_inventory as _ds          # noqa: E402
import model_inventory as _mi            # noqa: E402
import remote_monitor_aggregate as _rma  # noqa: E402
import scene_edit as _se                 # noqa: E402
import verify_version_sync as _vs        # noqa: E402

ROOT = os.path.dirname(_HERE)            # …/zmax
CST = timezone(timedelta(hours=8))

PRIMARY_OUT = os.path.join(ROOT, "zmax_data", "datapush", "dashboard.json")
WEB_OUT = os.path.join(ROOT, "tools", "web", "dashboard.json")
WEB_HTML = os.path.join(ROOT, "tools", "web", "unified_app.html")
SCHEMA = "zmax-dashboard/1"
_SNAP_A = "/*DASHBOARD_SNAPSHOT_START*/"
_SNAP_B = "/*DASHBOARD_SNAPSHOT_END*/"


# ─────────────────────────── 各源 → 关键字段 (都做 None 兜底) ───────────────────────────
def _collect_remote(offline: bool) -> dict:
    if offline:
        return {"endpoints_total": None, "endpoints_ok": None, "endpoints_err": None,
                "stale": [], "stale_count": None, "frame_age_s": None,
                "same_source": [], "mismatch": [], "unreachable": [], "error": "offline: 未采远程"}
    eps = _rma._build_catalog()
    results = _rma.collect(eps)
    rep = _rma.build_report(results)
    eps_out = rep["endpoints"]
    ok = [e for e in eps_out if e["ok"]]
    stale = [e["name"] for e in eps_out if e.get("stale")]
    unreachable = [e["name"] for e in eps_out if not e["ok"]]
    # 帧龄: 取臂相机那一路(本机推流 8791 的 arm.age_s)当代表; 找不到就用各端点最小数据龄
    frame_age = None
    for e in eps_out:
        if e["name"].startswith("本机推流stats") or e["name"].startswith("本机工位状态"):
            f = e.get("fields") or {}
            v = f.get("arm.age_s")
            if isinstance(v, (int, float)):
                frame_age = round(float(v), 2)
                break
    if frame_age is None:
        ages = [e["data_age_s"] for e in eps_out if isinstance(e.get("data_age_s"), (int, float))]
        frame_age = round(min(ages), 2) if ages else None
    same = [{"fact": s["fact"], "consistent": s["consistent"],
             "tol": s.get("tol"), "note": s.get("note") or "",
             "sources": [{"name": x["name"], "value": x["value"]} for x in s.get("sources", [])]}
            for s in rep["same_source"]]
    mismatch = [s["fact"] for s in rep["same_source"] if s["consistent"] is False]
    return {"endpoints_total": len(eps_out), "endpoints_ok": len(ok),
            "endpoints_err": len(eps_out) - len(ok), "stale": stale, "stale_count": len(stale),
            "frame_age_s": frame_age, "same_source": same, "mismatch": mismatch,
            "unreachable": unreachable, "error": None}


def _collect_datasets() -> dict:
    inv = _ds.build_inventory(ROOT, _ds.DEFAULT_MAX_DEPTH)
    cats = {k: {"count": v["count"], "size_human": v["size_human"]}
            for k, v in inv["categories"].items()}
    return {"items": inv["totals"]["items"], "size_human": inv["totals"]["size_human"],
            "size_bytes": inv["totals"]["size_bytes"], "file_count": inv["totals"]["file_count"],
            "categories": cats,
            "reports_files": inv["reports_summary"]["total_files"],
            "map_items_with_ply": inv["map_summary"]["items_with_gs_ply"]}


def _collect_models() -> dict:
    d = _mi.build(reports_n=8)
    g = d["gpu"]
    gpu = {"name": g.get("name"), "util": g.get("util"),
           "mem_used": g.get("mem_used"), "mem_total": g.get("mem_total"),
           "mem_pct": g.get("mem_pct"), "temp": g.get("temp"), "power": g.get("power"),
           "procs": len(g.get("procs") or []), "error": g.get("error")}
    layers = []
    for m in d["models"]:
        layers.append({"layer": m["layer"], "name": m["name"], "active": m["active"],
                       "ready": m["ready"], "size_h": m["size_h"], "mtime": m["mtime"]})
    active_ready = sum(1 for m in d["models"] if m["active"] and m["ready"])
    return {"gpu": gpu, "count": len(layers), "layers": layers,
            "active_ready": active_ready, "training_active": len(d["training"]),
            "all_ready": all(m["ready"] for m in d["models"]) if d["models"] else False}


def _collect_scene() -> dict:
    v = _se.read_view()
    fence_bad = [k for k, _ in _iter_fence_bad(v["fences"])]
    out_of_range = []
    for o in v["objects"]:
        for i, x in enumerate(o.get("center") or []):
            if _se._isnum(x) and abs(x) > _se.LIMIT:
                out_of_range.append("object %s center[%d]" % (o.get("name"), i))
    for m in v["markers"]:
        for i, x in enumerate(m.get("pos") or []):
            if _se._isnum(x) and abs(x) > _se.LIMIT:
                out_of_range.append("marker %s pos[%d]" % (m.get("name"), i))
    return {"objects": len(v["objects"]), "markers": len(v["markers"]),
            "fences": len(v["fences"]), "trajectories": len(v["trajectories"]),
            "deleted": len(v["deleted_flat"]), "traj_show": bool(v["traj_show"]),
            "fences_valid": not fence_bad, "fence_invalid": fence_bad,
            "out_of_range": out_of_range}


def _iter_fence_bad(fences):
    for f in fences:
        errs = _se.validate_fence(f)
        if errs:
            yield _se.entity_id(f, "fences"), errs


def _collect_version(offline: bool) -> dict:
    rep = _vs.build_report(ROOT, offline)
    r = rep["remote"]
    return {"ok": bool(rep["ok"]), "canonical": rep["canonical_version"],
            "canonical_source": rep["canonical_source"],
            "remote_has_tag": r.get("remote_has_canonical_tag"),
            "release_tag": (r.get("release") or {}).get("tag_name"),
            "deviations": list(rep["deviations"])}


# ─────────────────────────── 汇总 ───────────────────────────
def build(offline: bool = False) -> dict:
    now = datetime.now(CST)
    models = _collect_models()
    data = {
        "schema": SCHEMA,
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "generated_at_epoch": round(time.time(), 2),
        "version": None,
        "gpu": models.pop("gpu"),
        "datasets": None,
        "models": models,
        "scene": None,
        "remote": None,
        "version_sync": None,
    }
    data["datasets"] = _collect_datasets()
    data["scene"] = _collect_scene()
    data["remote"] = _collect_remote(offline)
    data["version_sync"] = _collect_version(offline)
    data["version"] = data["version_sync"].get("canonical")
    return data


# ─────────────────────────── 输出 ───────────────────────────
def _redact_write(data: dict, path: str) -> tuple[bool, int, int]:
    """脱敏 → 断言 → 原子写盘。返回 (assert_ok, hits, nsec)。"""
    text = json.dumps(data, ensure_ascii=False)
    ok, hits, nsec = _rma.assert_no_secrets(text)
    if not ok:
        data = _rma.redact_obj(json.loads(_rma.redact(text)))
        text = json.dumps(data, ensure_ascii=False)
        ok, hits, nsec = _rma.assert_no_secrets(text)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp.%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(data, ensure_ascii=False, indent=2))
    os.replace(tmp, path)
    return ok, hits, nsec


def _update_html_snapshot(data: dict) -> bool:
    """把最新数据作为页内快照写进 unified_app.html 的两个标记之间 ⇒ 离线(file://)也能看真值。"""
    if not os.path.isfile(WEB_HTML):
        return False
    try:
        with open(WEB_HTML, encoding="utf-8") as fh:
            html = fh.read()
        i = html.find(_SNAP_A)
        j = html.find(_SNAP_B)
        if i < 0 or j < 0 or j < i:
            return False
        snap = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        block = "%swindow.__DASHBOARD__ = %s;%s" % (_SNAP_A, snap, _SNAP_B)
        new = html[:i] + block + html[j + len(_SNAP_B):]
        tmp = WEB_HTML + ".tmp.%d" % os.getpid()
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(new)
        os.replace(tmp, WEB_HTML)
        return True
    except Exception:                                                     # noqa: BLE001
        return False


def render_human(d: dict) -> str:
    L = []
    L.append("=" * 78)
    L.append("Z-MAX 大屏统一数据源   生成时间 %s   版本 %s" % (d["generated_at"], d["version"]))
    L.append("=" * 78)
    g = d["gpu"]
    if g.get("error"):
        L.append("[GPU ] 采集失败: %s" % g["error"])
    else:
        L.append("[GPU ] %s · util %s%% · mem %s/%s MiB (%s%%) · %sC · 进程 %s"
                 % (g.get("name"), g.get("util"), g.get("mem_used"), g.get("mem_total"),
                    g.get("mem_pct"), g.get("temp"), g.get("procs")))
    ds = d["datasets"]
    L.append("[数据] %d 条资产 %s / %d 文件 · 报告 %d 个 · 建图含 ply %d 条"
             % (ds["items"], ds["size_human"], ds["file_count"],
                ds["reports_files"], ds["map_items_with_ply"]))
    m = d["models"]
    L.append("[模型] 共 %d 条, 在役且就绪 %d · 训练中 %d · 全就绪=%s"
             % (m["count"], m["active_ready"], m["training_active"], m["all_ready"]))
    for lay in m["layers"]:
        if lay["active"]:
            L.append("        · %s 在役 就绪=%s %s @ %s"
                     % (lay["layer"], lay["ready"], lay["size_h"], lay["mtime"]))
    s = d["scene"]
    L.append("[场景] objects %d · markers %d · fences %d · trajectories %d · 隐藏 %d · 轨迹显示 %s · 围栏合法 %s · 越界 %d"
             % (s["objects"], s["markers"], s["fences"], s["trajectories"],
                s["deleted"], s["traj_show"], s["fences_valid"], len(s["out_of_range"])))
    r = d["remote"]
    if r.get("error"):
        L.append("[远程] %s" % r["error"])
    else:
        L.append("[远程] 端点 %s 个: ok %s / err %s · stale %s 个 · 臂相机帧龄 %ss"
                 % (r["endpoints_total"], r["endpoints_ok"], r["endpoints_err"],
                    r["stale_count"], r["frame_age_s"]))
        for n in r["stale"]:
            L.append("        ⏸ stale: %s" % n)
        for n in r["unreachable"]:
            L.append("        ✗ 不可达: %s" % n)
        for ss in r["same_source"]:
            tag = "一致" if ss["consistent"] is True else ("不一致 ✗" if ss["consistent"] is False else ("不可比" if ss["note"] else "样本不足"))
            L.append("        [同源] %-16s %s" % (ss["fact"], tag))
    vs = d["version_sync"]
    L.append("[版本] 同源 ok=%s · 权威 %s · 远端有 tag=%s · 最新 Release %s · 偏差 %d"
             % (vs["ok"], vs["canonical"], vs["remote_has_tag"], vs["release_tag"], len(vs["deviations"])))
    if vs["deviations"]:
        for dv in vs["deviations"]:
            L.append("        ✗ %s" % dv)
    L.append("=" * 78)
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Z-MAX 大屏统一数据源")
    ap.add_argument("--json", action="store_true", help="单一 JSON 到 stdout")
    ap.add_argument("--json-out", default="", help="额外落一份到指定路径")
    ap.add_argument("--offline", action="store_true", help="跳过所有网络采集")
    ap.add_argument("--no-write", action="store_true", help="只打印, 不写盘")
    a = ap.parse_args(argv)

    data = build(offline=a.offline)
    ok = True
    written = []
    if not a.no_write:
        for path in (PRIMARY_OUT, WEB_OUT):
            w, hits, nsec = _redact_write(data, path)
            ok = ok and w
            written.append(path)
            sys.stderr.write("[redaction] %s 断言 %s: 已知口令 %d, 命中 %d\n"
                             % (os.path.relpath(path, ROOT), "PASS" if w else "FAIL", nsec, hits))
        if _update_html_snapshot(data):
            written.append(WEB_HTML + " (页内快照)")
    if a.json_out:
        w, hits, nsec = _redact_write(data, a.json_out)
        ok = ok and w
        written.append(a.json_out)

    if a.no_write and not a.json_out:
        # 仍需打印脱敏后的 JSON
        text = json.dumps(data, ensure_ascii=False)
        w, hits, nsec = _rma.assert_no_secrets(text)
        if not w:
            data = _rma.redact_obj(json.loads(_rma.redact(text)))

    if a.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(render_human(data))
        if written:
            print("\n已写盘:")
            for p in written:
                print("  · %s" % p)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
