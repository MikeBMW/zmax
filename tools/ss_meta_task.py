#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_meta_task.py — 「根据任务输出元任务」的运行时派生器 (老倪 2026-10-14)

口径 (技能 zmax-meta-task-planning): **元任务 = 一个功能(FN-SYSx-N) + 该功能全部配置参数 + 依赖
+ 验证方法 + 归属层**。它是**登记表派生件**, 不是意图, 也不是技能:

    任务(TASK-xx) ──enabled_nodes──> 画布节点(node_id) ──name──> 功能(module_ref) ──fn_id──> 元任务

⇒ 内容只能由唯一依据现算 (config_meta.json 74 功能 + ss_task_binding.json 任务×节点 + 画布节点/连线),
   **不能从意图直读** (🔮 意图直读/ss_intent_direct 是 Δz→技能 kNN, 输出的是**技能ID**, 没有功能登记/
   参数/验证/层)。意图/任务只决定**选哪一批**(哪个任务 → 哪些元任务)。

用途 (三处同一份, 一处取):
  · 运行时话题 zmax/ss_meta_task (5s, 与「已加载配置名」同一个出口 = 主参数节点 n_calib_mani)
  · 落盘 zmax_data/ss_live/meta_tasks.json (画布/控制台/大屏读)
  · 复用 tools/export_meta_doc.py 的 build_meta_tasks() (文档与运行时**同一条映射链**, 不重写)

CLI:
    --task TASK-07-AOI   指定任务 (默认取唯一依据 ss_task_binding.json 的 active_task)
    --json               打印 JSON (给守护/订阅器/脚本)
    --write              落盘 zmax_data/ss_live/meta_tasks.json
    --selftest           判据: 74/74 映射命中 + 各任务元任务数 == 该任务 enabled_nodes 数
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
DB = os.path.join(ROOT, "data", "database", "zmax")
SRC = os.path.join(DB, "sources", "config")
LIVE = os.path.join(ROOT, "zmax_data", "ss_live", "meta_tasks.json")
BINDING = os.path.join(ROOT, "config", "ss_task_binding.json")

if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)


def _sha(p: str) -> str:
    try:
        with open(p, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()[:12]
    except OSError:
        return "缺"


def _read_binding() -> dict:
    try:
        with open(BINDING, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def active_task() -> str:
    """活跃任务唯一依据: config/ss_task_binding.json → active_task (读不到就明说, 不猜)。"""
    return str(_read_binding().get("active_task") or "")


def build(task_id: str | None = None, write: bool = False) -> dict:
    """任务 → 元任务清单 (唯一依据现算)。返回 dict; write=True 时同时落盘。"""
    import export_meta_doc as EM                                       # noqa: PLC0415  (同一条映射链)

    sb = _read_binding()
    tid = str(task_id or sb.get("active_task") or "")
    tmeta = {}
    for t in (sb.get("tasks") or []):
        if t.get("task_id") == tid:
            tmeta = t
            break
    MT, ctx = EM.build_meta_tasks()
    if not tid:
        items = MT
        note = "未指定任务且唯一依据没有 active_task ⇒ 给全量 %d 个 (如实标)" % len(MT)
    elif not tmeta:
        items = []
        note = "任务 %s 不在唯一依据 ss_task_binding.json 里 ⇒ 0 个 (不猜)" % tid
    else:
        items = [m for m in MT if tid in (m.get("tasks") or [])]
        note = "按任务启用节点现算"
    by_layer: dict = {}
    for m in items:
        by_layer[m.get("layer") or "?"] = by_layer.get(m.get("layer") or "?", 0) + 1
    prio: dict = {}
    for m in items:
        prio[m.get("prio") or "?"] = prio.get(m.get("prio") or "?", 0) + 1
    out = {
        "schema": "zmax.ss_meta_task/1",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "ts": time.time(),
        "task_id": tid or None,
        "task_name": tmeta.get("name"),
        "scene_ref": tmeta.get("scene_ref"),
        "site": tmeta.get("site"),
        "n": len(items),
        "n_all": len(MT),
        "enabled_nodes": len(tmeta.get("enabled_nodes") or []),
        "by_layer": by_layer,
        "by_prio": prio,
        "note": note,
        "sources": {
            "config_meta.json": _sha(os.path.join(DB, "config_meta.json")),
            "ss_task_binding.json": _sha(BINDING),
            "state_space_obs.json": _sha(os.path.join(
                ROOT, "src", "lerobot", "engineering", "flows", "state_space_obs.json")),
        },
        "items": [{
            "mt_id": m.get("mt_id"), "fn_id": m.get("fn_id"), "name": m.get("name"),
            "layer": m.get("layer"), "node_id": m.get("node_id"), "prio": m.get("prio"),
            "n_params": m.get("n_params"), "params_head": m.get("params_head"),
            "verification": m.get("verification"), "deps_up": m.get("deps_up"),
            "tasks": m.get("tasks"), "month": m.get("month"),
        } for m in items],
    }
    if write:
        os.makedirs(os.path.dirname(LIVE), exist_ok=True)
        tmp = LIVE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, LIVE)
    return out


def selftest() -> int:
    """判据: 映射链 74/74 + 各任务元任务数 == 该任务 enabled_nodes 数。"""
    import export_meta_doc as EM                                       # noqa: PLC0415

    MT, ctx = EM.build_meta_tasks()
    ok = 0
    print("① 功能 module_ref → 画布节点: %d/%d" % (len(MT) - len(ctx["bad"]), len(MT)))
    ok += (len(MT) - len(ctx["bad"])) == len(MT)
    sb = _read_binding()
    bad = 0
    print("② 各任务元任务数 == enabled_nodes 数:")
    for t in (sb.get("tasks") or []):
        tid = t["task_id"]
        n_meta = len([m for m in MT if tid in (m.get("tasks") or [])])
        n_en = len(t.get("enabled_nodes") or [])
        same = n_meta == n_en
        bad += 0 if same else 1
        print("     %-14s 元任务 %3d / enabled_nodes %3d  %s" % (tid, n_meta, n_en, "OK" if same else "❌"))
    ok += bad == 0
    d = build()
    print("③ 活跃任务派生: active_task=%s · 元任务 %d 个 (全量 %d) · 层分布 %s"
          % (d["task_id"], d["n"], d["n_all"], d["by_layer"]))
    ok += d["n"] > 0
    print("判据 %d/3 %s" % (ok, "PASS" if ok == 3 else "FAIL"))
    return 0 if ok == 3 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="任务 → 元任务 运行时派生器 (唯一依据现算)")
    ap.add_argument("--task", default=None, help="任务ID (默认取唯一依据 active_task)")
    ap.add_argument("--json", action="store_true", help="打印 JSON")
    ap.add_argument("--write", action="store_true", help="落盘 zmax_data/ss_live/meta_tasks.json")
    ap.add_argument("--selftest", action="store_true", help="判据 (74/74 + 各任务计数)")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    d = build(a.task, write=a.write)
    if a.json:
        print(json.dumps(d, ensure_ascii=False))
        return 0
    print("🧾 元任务派生 (任务→功能→参数/依赖/验证/层) · 唯一依据现算")
    print("   任务: %s %s · 场景 %s · 站点 %s"
          % (d["task_id"] or "—", d["task_name"] or "—", d["scene_ref"] or "—", d["site"] or "—"))
    print("   元任务 %d 个 (全量 %d · 任务启用节点 %s) · 层分布 %s · 优先级 %s"
          % (d["n"], d["n_all"], d["enabled_nodes"], d["by_layer"], d["by_prio"]))
    print("   唯一依据: config_meta.json %s · ss_task_binding.json %s · 画布 %s"
          % (d["sources"]["config_meta.json"], d["sources"]["ss_task_binding.json"],
             d["sources"]["state_space_obs.json"]))
    for m in d["items"][:12]:
        print("     %-8s %-10s %-30s %-4s %-6s params=%s"
              % (m["mt_id"] or "—", m["fn_id"], (m["name"] or "")[:30], m["layer"],
                 m["prio"], m["n_params"]))
    if d["n"] > 12:
        print("     … 其余 %d 个 (--json 看全)" % (d["n"] - 12))
    if a.write:
        print("   落盘: %s" % os.path.relpath(LIVE, ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
