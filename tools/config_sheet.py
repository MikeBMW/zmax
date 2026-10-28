#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""config_sheet.py — 发布「配置单」: 某个任务(默认活跃任务)在当前状态空间工程里的**全套配置参数**

老倪 2026-10-12: 「你要发布一个配置单，可以从配置清单导出。带出所有的配置参数。
                  先给出当前插拔项目的所有配置参数。」

一次导全 8 段 (每段都标唯一依据, 可复核):
  ① 任务/场景/站点 ② 工艺步骤 ③ 适用段/不适用段 ④ 六档位(run_cfg)
  ⑤ 参数覆盖(overrides) ⑥ 画布(工程/节点/连线/md5 + 该任务启用节点的节点参数)
  ⑦ 全量参数注册表(162: 标定/画布/代码/平台/档位, 每个带 值/范围/单位/状态)
  ⑧ 标定唯一依据 + 点位台账 (sha256/mtime)

用法:
  gui-venv311/bin/python tools/config_sheet.py                      # 活跃任务
  gui-venv311/bin/python tools/config_sheet.py --task TASK-01-FW
  gui-venv311/bin/python tools/config_sheet.py --task TASK-01-FW --out outputs/config_sheets
  gui-venv311/bin/python tools/config_sheet.py --task TASK-01-FW --json-only
输出: <out>/配置单_<TASK>_<YYYYmmdd_HHMM>.md 与 .json (同时留一份 _latest 副本)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, ROOT)

CANVAS = os.path.join(ROOT, "flows", "state_space_obs.json")
CALIB_DIR = os.path.join(ROOT, "config", "calib")
CALIB_FILES = ["zmax_calib.json", "handeye_result.json", "zmax_manifold.json",
               "plane_z.json", "camera_K.json", "zmax_params.json"]
POINT_FILES = [("示教点位(号位)", "data/skills/l2_atomic/taught_points.json"),
               ("空间点 1..8", "data/skills/l2_atomic/space_points.json"),
               ("AOI 示教点", "reports/aoi_points")]


def _sha(p: str) -> str:
    try:
        with open(p, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except Exception:                                                           # noqa: BLE001
        return "—"


def _git_rev() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True).stdout.strip() or "—"
    except Exception:                                                           # noqa: BLE001
        return "—"


def _mtime(p: str) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(p)))
    except Exception:                                                           # noqa: BLE001
        return "—"


def collect(task_id: str = "") -> dict:
    import ss_task_bind as sb
    import ss_scene_switch as ssw
    import param_registry as pr

    doc = sb.build()
    tid = task_id or doc.get("active_task") or ""
    t = next((x for x in doc["tasks"] if x["task_id"] == tid), None)
    if t is None:
        raise SystemExit("⛔ 无此任务: %s (可选: %s)" % (tid, ", ".join(x["task_id"] for x in doc["tasks"])))

    canvas = json.load(open(CANVAS, encoding="utf-8"))
    nodes = {n.get("id"): n for n in canvas.get("nodes", [])}

    # ⑥ 启用节点的节点参数 (该任务真正会用到的节点)
    node_params = []
    for nid in t.get("enabled_nodes", []):
        n = nodes.get(nid)
        if not n:
            continue
        ps = {k: v for k, v in (n.get("params") or {}).items()
              if k not in ("row_bg", "bg")}
        node_params.append({"id": nid, "name": n.get("name"), "type": n.get("type"),
                            "params": ps, "n_params": len(ps)})
    disabled = [{"id": nid, "name": (nodes.get(nid) or {}).get("name")}
                for nid in t.get("disabled_nodes", [])]

    # ⑦ 全量参数注册表
    reg = pr.registry()
    params = reg.get("params", []) if isinstance(reg, dict) else []
    by_group: dict = {}
    for p in params:
        by_group.setdefault(p.get("group", "?"), []).append(p)

    # ⑧ 标定 + 点位
    calib = []
    for fn in CALIB_FILES:
        p = os.path.join(CALIB_DIR, fn)
        if os.path.isfile(p):
            calib.append({"file": "config/calib/" + fn, "sha256_16": _sha(p),
                          "mtime": _mtime(p), "bytes": os.path.getsize(p)})
    points = []
    for label, rel in POINT_FILES:
        p = os.path.join(ROOT, rel)
        if os.path.isdir(p):
            fs = [x for x in os.listdir(p) if x.endswith(".json")]
            points.append({"label": label, "file": rel + "/", "count": len(fs),
                           "sha256_16": "—", "mtime": _mtime(p),
                           "files": sorted(fs)[:12]})
            continue
        if os.path.isfile(p):
            try:
                d = json.load(open(p, encoding="utf-8"))
                inner = d.get("points") if isinstance(d, dict) and "points" in d else d
                n = len(inner) if hasattr(inner, "__len__") else 0
            except Exception:                                                   # noqa: BLE001
                n = 0
            points.append({"label": label, "file": rel, "count": n,
                           "sha256_16": _sha(p), "mtime": _mtime(p)})

    scen = {}
    try:
        scen = ssw.TASK_SCENE.get(tid, {}) or {}
    except Exception:                                                           # noqa: BLE001
        pass

    return {
        "_meta": {
            "schema": "zmax.config.sheet/1",
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "generator": "tools/config_sheet.py",
            "git": _git_rev(),
            "唯一依据": {"任务配置": "config/tasks/tasks.json", "绑定": "config/ss_task_binding.json",
                     "画布": "flows/state_space_obs.json", "参数注册表": "tools/param_registry.py",
                     "场景/色": "tools/ss_scene_switch.py"},
        },
        "任务": {
            "task_id": t["task_id"], "name": t.get("name"), "recipe_type": t.get("recipe_type"),
            "scene_ref": t.get("scene_ref"), "site": t.get("site"),
            "场景": scen.get("scene"), "场景色": scen.get("color"), "SCN": scen.get("scn"),
            "trigger": t.get("trigger"), "loop": t.get("loop"), "targets": t.get("targets"),
            "safety": t.get("safety"), "ss_mode": t.get("ss_mode"),
            "orders_rule": t.get("orders_rule"), "blocked_by_site": t.get("blocked_by_site"),
            "适用段": t.get("applies_segments"), "不适用段": t.get("excluded_segments"),
            "档位": t.get("run_cfg"), "参数覆盖": t.get("overrides"),
            "工艺步骤": t.get("steps"),
        },
        "画布": {"工程": doc.get("project", {}).get("name"),
                 "文件": "flows/state_space_obs.json",
                 "节点": doc.get("project", {}).get("nodes"),
                 "连线": doc.get("project", {}).get("links"),
                 "md5": doc.get("project", {}).get("canvas_md5"),
                 "启用节点数": len(t.get("enabled_nodes", [])),
                 "禁用节点": disabled,
                 "启用节点参数": node_params},
        "参数注册表": {"总数": len(params),
                       "分组计数": {k: len(v) for k, v in sorted(by_group.items())},
                       "分组": by_group},
        "标定唯一依据": calib,
        "点位台账": points,
        "活跃任务": doc.get("active_task"),
    }


def _fmt_val(v):
    if isinstance(v, float):
        return ("%.6g" % v)
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def to_md(d: dict) -> str:
    L = []
    m, t = d["_meta"], d["任务"]
    L.append("# 配置单 · %s — %s" % (t["task_id"], t.get("name") or ""))
    L.append("")
    L.append("> 生成 %s · by `%s` @ `%s` · 唯一依据: 任务配置/绑定/画布/参数注册表/场景映射 (见 JSON `_meta.唯一依据`)"
             % (m["generated_at"], m["generator"], m["git"]))
    L.append("")
    L.append("## ① 任务 / 场景 / 站点")
    L.append("")
    L.append("| 项 | 值 |")
    L.append("| --- | --- |")
    for k, v in (("任务", t["task_id"]), ("名称", t.get("name")), ("配方类型", t.get("recipe_type")),
                 ("场景", "%s (%s)" % (t.get("场景"), t.get("场景色"))), ("场景 SCENE", t.get("SCN")),
                 ("站点", t.get("site")), ("触发", t.get("trigger")), ("循环/停机", t.get("loop")),
                 ("判据/目标", _fmt_val(t.get("targets"))), ("安全", _fmt_val(t.get("safety"))),
                 ("状态空间模式", t.get("ss_mode")), ("工单规则", _fmt_val(t.get("orders_rule"))),
                 ("站点缺口", _fmt_val(t.get("blocked_by_site")))):
        L.append("| %s | %s |" % (k, _fmt_val(v)))
    L.append("")
    L.append("## ② 工艺步骤 (%d 步)" % len(t.get("工艺步骤") or []))
    L.append("")
    L.append("| # | 步骤 | 时长(s) | 描述 | 力 |")
    L.append("| --- | --- | --- | --- | --- |")
    for i, s in enumerate(t.get("工艺步骤") or [], 1):
        L.append("| %d | %s | %s | %s | %s |" % (i, s.get("name"), s.get("dur", "—"),
                                                 (str(s.get("desc") or "")).replace("|", "/"),
                                                 s.get("force", "—")))
    L.append("")
    L.append("## ③ 适用段 / 不适用段")
    L.append("")
    L.append("* 适用段 (%d): %s" % (len(t.get("适用段") or []), " · ".join(t.get("适用段") or [])))
    L.append("* 不适用段: %s" % (" · ".join(t.get("不适用段") or []) or "无"))
    L.append("")
    L.append("## ④ 六档位 (状态空间运行开关)")
    L.append("")
    L.append("| 档位 | 状态 |")
    L.append("| --- | --- |")
    for k, v in (t.get("档位") or {}).items():
        L.append("| %s | %s |" % (v.get("label", k), "开" if v.get("checked") else "关"))
    L.append("")
    L.append("## ⑤ 参数覆盖 (overrides — 该任务对工程默认值的覆盖)")
    L.append("")
    ov = t.get("参数覆盖") or {}
    if not ov:
        L.append("(无)")
    else:
        L.append("| 参数 | 值 |")
        L.append("| --- | --- |")
        for k, v in ov.items():
            L.append("| `%s` | %s |" % (k, _fmt_val(v)))
    L.append("")
    c = d["画布"]
    L.append("## ⑥ 画布 (状态空间工程)")
    L.append("")
    L.append("* 工程: %s · %s 节点 / %s 连线 · md5 `%s`" % (c["工程"], c["节点"], c["连线"], c["md5"]))
    L.append("* 该任务启用 **%d** 个节点 · 禁用 %d 个" % (c["启用节点数"], len(c["禁用节点"])))
    if c["禁用节点"]:
        L.append("* 禁用: " + " · ".join("%s(%s)" % (x["name"], x["id"]) for x in c["禁用节点"]))
    L.append("")
    L.append("### 启用节点的节点参数 (只列非空)")
    L.append("")
    L.append("| 节点 | 类型 | 参数 |")
    L.append("| --- | --- | --- |")
    for n in c["启用节点参数"]:
        if not n["params"]:
            continue
        ps = " · ".join("`%s`=%s" % (k, _fmt_val(v)) for k, v in n["params"].items())
        L.append("| %s | %s | %s |" % (n["name"], n["type"], ps))
    L.append("")
    p = d["参数注册表"]
    L.append("## ⑦ 全量参数注册表 (%d 项 · 分组: %s)" % (
        p["总数"], " · ".join("%s %d" % (k, v) for k, v in p["分组计数"].items())))
    L.append("")
    for g, items in p["分组"].items():
        L.append("### %s (%d)" % (g, len(items)))
        L.append("")
        L.append("| 参数 ID | 名称 | 值 | 范围 | 单位 | 状态 | 唯一依据 |")
        L.append("| --- | --- | --- | --- | --- | --- | --- |")
        for it in items:
            rng = "—"
            if it.get("min") is not None or it.get("max") is not None:
                rng = "%s..%s" % (it.get("min"), it.get("max"))
            L.append("| `%s` | %s | %s | %s | %s | %s | `%s` |" % (
                it.get("param_id"), it.get("cn") or it.get("name"), _fmt_val(it.get("value")),
                rng, it.get("unit", "—"), it.get("status", "—"), it.get("source", "—")))
        L.append("")
    L.append("## ⑧ 标定唯一依据 + 点位台账")
    L.append("")
    L.append("| 标定文件 | sha256(16) | 修改时间 | 字节 |")
    L.append("| --- | --- | --- | --- |")
    for x in d["标定唯一依据"]:
        L.append("| `%s` | `%s` | %s | %s |" % (x["file"], x["sha256_16"], x["mtime"], x["bytes"]))
    L.append("")
    L.append("| 点位台账 | 文件 | 条数 | sha256(16) | 修改时间 |")
    L.append("| --- | --- | --- | --- | --- |")
    for x in d["点位台账"]:
        L.append("| %s | `%s` | %s | `%s` | %s |" % (x["label"], x["file"], x["count"],
                                                     x["sha256_16"], x["mtime"]))
    L.append("")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="")
    ap.add_argument("--out", default=os.path.join(ROOT, "outputs", "config_sheets"))
    ap.add_argument("--json-only", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    d = collect(a.task)
    os.makedirs(a.out, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    base = "配置单_%s_%s" % (d["任务"]["task_id"], ts)
    jp = os.path.join(a.out, base + ".json")
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    for alias in (os.path.join(a.out, "配置单_%s_latest.json" % d["任务"]["task_id"]),):
        with open(alias, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
    out = [jp]
    if not a.json_only:
        mp = os.path.join(a.out, base + ".md")
        open(mp, "w", encoding="utf-8").write(to_md(d))
        open(os.path.join(a.out, "配置单_%s_latest.md" % d["任务"]["task_id"]), "w",
             encoding="utf-8").write(to_md(d))
        out.append(mp)
    if not a.quiet:
        t = d["任务"]
        print("✅ 配置单已发布: %s" % t["task_id"] + (" — " + str(t.get("name"))))
        print("   场景 %s (%s) · 站点 %s · 配方 %s · 步骤 %d"
              % (t.get("场景"), t.get("场景色"), t.get("site"), t.get("recipe_type"),
                 len(t.get("工艺步骤") or [])))
        print("   适用段 %d · 启用节点 %d · 禁用 %d · 六档位 %d · 参数覆盖 %d"
              % (len(t.get("适用段") or []), d["画布"]["启用节点数"],
                 len(d["画布"]["禁用节点"]), len(t.get("档位") or {}), len(t.get("参数覆盖") or {})))
        print("   参数注册表 %d 项 (%s)" % (d["参数注册表"]["总数"],
                                       " · ".join("%s %d" % (k, v)
                                                  for k, v in d["参数注册表"]["分组计数"].items())))
        print("   标定 %d 文件 · 点位台账 %d 份" % (len(d["标定唯一依据"]), len(d["点位台账"])))
        for p in out:
            print("   → %s (%d B)" % (p, os.path.getsize(p)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
