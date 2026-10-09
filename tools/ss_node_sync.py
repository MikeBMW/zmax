#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把配置清单写进状态空间工程的「标定诊断测量 · 主参数 M」节点 (老倪 2026-10-09)

节点: n_calib_mani  ← 原「🧮 流形引擎标定 · 主参数 M」, 改名为「🧮 标定诊断测量 · 主参数 M」
它成为 **配置中心 ←→ 状态空间工程 的唯一收口口**: 测量 / 标定 / 诊断 三视图 + 主参数 M。

写进去的是什么 (只写摘要 + 文件指针, 文件本身仍是真源):
    params.cfg_role        该节点在配置体系里的角色
    params.cfg_entries     所有配置文件路径 (MCD 描述/注册表/匹配矩阵/任务/绑定/工单/工程文件/calib/manifold)
    params.cfg_snapshot    当前配置状态快照 (参数就绪度/缺口/任务数/活跃任务/断言/模型匹配/站点缺口/工程指纹)
    params.measure/calib/diagnose   三视图各自的摘要

🔴 铁律 (来自技能 state-space-canvas-engineering):
  ① 画布只经 `flows.save_canvas()` 写 (校验 + 自动备份到 _archive)
  ② **只动这一个节点**: 写盘前后比对"除该节点外"的整幅画布指纹, 必须逐位相同
  ③ id / 端口 / 连线一律不动 (改 id 会断线)

用法:
    python3 tools/ss_node_sync.py            # 写入 + 回读核验 (自动备份)
    python3 tools/ss_node_sync.py --check    # 只比对, 不写 (幂等)
    python3 tools/ss_node_sync.py --json
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
NODE_ID = "n_calib_mani"
NEW_NAME = "🧮 标定诊断测量 · 主参数 M (状态空间结构参数 · 等效惯量)"

MCD = os.path.join(ROOT, "config", "mcd", "zmax_mcd.json")
REG = os.path.join(ROOT, "config", "mcd", "param_registry.json")
MATCH = os.path.join(ROOT, "config", "mcd", "match_matrix.json")
TASKS = os.path.join(ROOT, "config", "tasks", "tasks.json")
BIND = os.path.join(ROOT, "config", "ss_task_binding.json")
ORDERS = os.path.join(ROOT, "config", "orders")
PROJ = os.path.join(ROOT, "reports", "projects", "SS_主工程_任务配置.zmaxproj")


def _j(p, d=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return d


def _dd(b):
    for x in list(b.values()):
        yield x
        if isinstance(x, list):
            yield from _dd({"i": i} for i in x)
    return


def _canvas():
    from lerobot.engineering import flows
    d, probs = flows.load_canvas()
    return d, list(probs or []), flows


def _fingerprint_excl(d):
    """除目标节点外的整幅画布指纹 (写盘前后必须一致 ⇒ 证明只动了这一个节点)"""
    other = [dict(n) for n in (d.get("nodes") or []) if n.get("id") != NODE_ID]
    blob = json.dumps({"nodes": other, "links": d.get("links") or [],
                       "meta": {k: v for k, v in d.items() if k not in ("nodes", "links")}},
                      ensure_ascii=False, sort_keys=True)
    return hashlib.md5(blob.encode()).hexdigest()


def build_snapshot():
    mcd = _j(MCD, {}) or {}
    reg = _j(REG, {}) or {}
    mat = _j(MATCH, {}) or {}
    tk = _j(TASKS, {}) or {}
    bd = _j(BIND, {}) or {}
    meta = mcd.get("_meta", {})
    chars = mcd.get("CHARACTERISTIC", [])
    gaps = [c["id"] for c in chars if not c.get("ready")]
    by_domain = {c["domain"]: 0 for c in chars}
    for c in chars:
        by_domain[c["domain"]] = by_domain.get(c["domain"], 0) + 1
    site = [g for g in gaps if g in ("T_base_cam", "plane_z", "cell_geometry.points")]
    blocked = [r["model"] for r in mat.get("MODELS", []) if not r["usable_now"]]
    ords = sorted(glob.glob(os.path.join(ORDERS, "BS_*.json")))
    meas = mcd.get("MEASUREMENT", [])
    diag = mcd.get("DIAGNOSTICS", {})
    return {
        "entries": {
            "mcd_描述": "config/mcd/zmax_mcd.json",
            "参数注册表": "config/mcd/param_registry.json",
            "模型×工程匹配": "config/mcd/match_matrix.json",
            "任务配置": "config/tasks/tasks.json",
            "任务绑定": "config/ss_task_binding.json",
            "工单目录": "config/orders/ (BS_*.json)",
            "工程文件": "reports/projects/SS_主工程_任务配置.zmaxproj",
            "站点标定": "config/calib/zmax_calib.json",
            "流形标定": "config/calib/zmax_manifold.json",
        },
        "snapshot": {
            "mcd_schema": meta.get("schema"), "mcd_generated_at": meta.get("generated_at"),
            "params_total": len(chars), "params_ready": len(chars) - len(gaps), "params_gap": len(gaps),
            "by_domain": by_domain, "gaps": gaps,
            "tasks": len(tk.get("tasks", [])), "active_task": bd.get("active_task"),
            "orders": len(ords), "assertions": diag.get("assertions_total"),
            "assertions_auto": diag.get("assertions_auto"), "by_level": diag.get("by_level"),
            "models_matched": f"{mat.get('SUMMARY', {}).get('usable_now')}/{mat.get('SUMMARY', {}).get('models')}",
            "models_blocked": blocked, "site_missing": site,
            "project": {"file": os.path.relpath(PROJ, ROOT), "canvas_md5": (bd.get("project") or {}).get("canvas_md5"),
                        "nodes": (bd.get("project") or {}).get("nodes"),
                        "links": (bd.get("project") or {}).get("links")},
            "node_readback_at": None,  # 易变字段: 不写入 (保持 --check 幂等)
        },
        "measure": {"视图": "测量 Measurement (只读)", "测量量": len(meas),
                    "源": [m.get("src") for m in meas][:6],
                    "判据": "帧龄 <2s · 真源在且值非空",
                    "命令": "python3 tools/config_center.py list 工程配置"},
        "calib": {"视图": "标定 Calibration (可写)", "可标参数": sum(1 for c in chars if c["perm"] in ("auth", "field")),
                  "主参数M": "M (G0 结构参数, 非自由拟合) · 范围 [0,8] · inertia 开关",
                  "真源": "config/calib/zmax_manifold.json → tools/zmax_params.py::write_manifold_M()",
                  "命令": "python3 tools/config_center.py show M"},
        "diagnose": {"视图": "诊断 Diagnosis (判得了)", "断言": diag.get("assertions_total"),
                     "故障码": [c.get("code") for c in (diag.get("codes") or [])],
                     "站点缺口": site,
                     "命令": "python3 tools/config_center.py check"},
        "task_layer": {"任务数": len(tk.get("tasks", [])), "活跃": bd.get("active_task"),
                       "段覆盖": (bd.get("coverage") or {}).get("covered_by_segments"),
                       "命令": "python3 tools/ss_task_bind.py",
                       "口径": "一个状态空间工程承载全部任务; 任务=配方段子集+参数覆盖"},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    d, probs, flows = _canvas()
    if probs:
        print("⛔ 画布校验不过, 拒绝写入: %s" % probs[:3]); return 2
    node = next((n for n in d["nodes"] if n.get("id") == NODE_ID), None)
    if node is None:
        print(f"⛔ 画布上没有节点 {NODE_ID}"); return 2
    snap = build_snapshot()
    before_fp = _fingerprint_excl(d)
    old_name = node.get("name")
    want = {"cfg_role": "配置中心 ←→ 状态空间工程 的唯一收口口 (测量/标定/诊断 三视图 + 主参数 M)",
            "cfg_entries": snap["entries"], "cfg_snapshot": snap["snapshot"],
            "measure_view": snap["measure"], "calib_view": snap["calib"],
            "diagnose_view": snap["diagnose"], "task_layer": snap["task_layer"]}
    cur = {k: (node.get("params") or {}).get(k) for k in want}
    same = (old_name == NEW_NAME and cur == want)

    if a.json:
        print(json.dumps({"node": NODE_ID, "name_now": old_name, "name_want": NEW_NAME,
                          "params_want": want, "in_sync": same}, ensure_ascii=False, indent=1))
        return 0 if same else 2
    if a.check:
        print(f"  {'✅' if same else '❌'} 节点 {NODE_ID}")
        print(f"     名称: {old_name!r}" + ("  ✅" if old_name == NEW_NAME else f"\n     应为: {NEW_NAME!r}"))
        bad = [k for k in want if cur.get(k) != want[k]]
        print(f"     配置段: {'✅ 全部一致' if not bad else '❌ 需更新: ' + ', '.join(bad)}")
        print(f"     快照: 参数 {snap['snapshot']['params_ready']}/{snap['snapshot']['params_total']}"
              f" · 任务 {snap['snapshot']['tasks']} · 活跃 {snap['snapshot']['active_task']}"
              f" · 工单 {snap['snapshot']['orders']}")
        return 0 if same else 2

    if same:
        print(f"✅ 节点 {NODE_ID} 已是目标状态, 无需改写 (名称/配置段逐位一致)")
        return 0

    # 只改这一个节点的 name + 指定 params 键 (其余键、id、端口、连线一律不动)
    node["name"] = NEW_NAME
    node.setdefault("params", {})
    node["params"].update(want)
    node["params"]["desc"] = ("配置中心(测量/标定/诊断) ←→ 状态空间工程 的唯一收口口; 主参数 M 为唯一主标定标量; "
                              "双击/右键真跑两臂对比 (M>0 有惯性 vs M→0 过阻尼)")
    p, bak = flows.save_canvas(d, reason="cfg_node_sync")

    # 回读核验 (写盘不算完成)
    d2, probs2, flows2 = _canvas()
    n2 = next((n for n in d2["nodes"] if n.get("id") == NODE_ID), None)
    fp_ok = _fingerprint_excl(d2) == before_fp
    cnt_ok = (len(d2["nodes"]), len(d2.get("links") or [])) == (len(d["nodes"]), len(d.get("links") or []))
    st_ok = flows2.stats(d2)
    p2 = n2.get("params") or {}
    ok = (n2.get("name") == NEW_NAME and all(p2.get(k) == v for k, v in want.items())
          and fp_ok and cnt_ok and not probs2)
    print(f"{'✅' if ok else '❌'} 节点已写入 {p}  (备份: {os.path.basename(bak) if bak else '无'})")
    print(f"   名称: {n2.get('name')}")
    print(f"   配置段: {', '.join(k for k in want)}  ({len(want)} 段)")
    print(f"   画布: {st_ok['nodes']} 节点 / {st_ok['links']} 连线 · 除本节点外指纹一致: {'✅' if fp_ok else '❌'}"
          f" · 节点/连线数不变: {'✅' if cnt_ok else '❌'} · 校验: {'✅' if not probs2 else probs2}")
    s = snap["snapshot"]
    print(f"   快照: 参数 {s['params_ready']}/{s['params_total']} (缺 {s['params_gap']}) · 任务 {s['tasks']}"
          f" · 活跃 {s['active_task']} · 工单 {s['orders']} · 断言 {s['assertions']}")
    print(f"   还原命令: 见上方 ↩️ (flows.save_canvas 自动备份到 flows/_archive/)")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
