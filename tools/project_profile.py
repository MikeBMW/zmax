#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""project_profile.py — 项目档案: 「根据配置, 适配不同项目」(老倪 2026-10-10)

一个项目 = 一份 overlay (`config/platform/projects/<PID>.json`), 叠在平台基线真源上:
    基线: config/platform/zmax_project_bom.json   (平台/BOM/人力/商务/ROI/市场 全量)
    覆盖: config/platform/projects/<PID>.json     (该项目改写的字段 + 该项目特有的项)
    合并: 逐键深合并 (dict 递归, list 整体替换), 输出**单一 bom 字典**给各导出器

设计纪律 (老倪零容忍):
  · **不编数字**: 项目档案里取不到的项显式写 "待确认" 并进 gaps 汇总; 不给"看起来合理"的默认值。
  · **同源可查**: 每次合并返回 provenance(base sha / overlay sha / pid / merged sha), 文档 manifest 记录它,
    改任一份 ⇒ merged sha 变 ⇒ 文档一致性判据抓得到 (与三件套同源判据同一套机制)。
  · **不改基线**: 覆盖只发生在内存里的合并结果; 基线文件永不被项目档案改写。
  · 记录当前生效项目: config/platform/active_project.json (仅一个 pid 字段, 供 GUI/工具默认取用)。

用法:
    python3 tools/project_profile.py --list                 # 有哪些项目
    python3 tools/project_profile.py --show PROJ-TH-TRAY     # 看某项目合并结果 + 缺口
    python3 tools/project_profile.py --use PROJ-LOAD-UNLOAD  # 设为当前生效项目
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.join(ROOT, "config", "platform", "zmax_project_bom.json")
PDIR = os.path.join(ROOT, "config", "platform", "projects")
ACTIVE = os.path.join(ROOT, "config", "platform", "active_project.json")
DEFAULT_PID = "PROJ-TH-TRAY"


def _j(p, d=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return d if d is not None else {}


def _sha(p):
    try:
        return hashlib.sha256(open(p, "rb").read()).hexdigest()
    except Exception:  # noqa: BLE001
        return ""


def list_projects():
    out = []
    if os.path.isdir(PDIR):
        for fn in sorted(os.listdir(PDIR)):
            if fn.endswith(".json"):
                d = _j(os.path.join(PDIR, fn), {}) or {}
                out.append({"pid": d.get("pid") or fn[:-5], "name": d.get("name"),
                            "file": "config/platform/projects/" + fn, "note": d.get("note")})
    return out


def active_pid():
    return (_j(ACTIVE, {}) or {}).get("pid") or os.environ.get("ZMAX_PROJECT") or DEFAULT_PID


def _merge(a, b):
    """逐键深合并: dict 递归, 其它 (list/标量) 整体替换。不改原对象。"""
    if isinstance(a, dict) and isinstance(b, dict):
        out = copy.deepcopy(a)
        for k, v in b.items():
            out[k] = _merge(out[k], v) if k in out else copy.deepcopy(v)
        return out
    return copy.deepcopy(b)


def load(pid=None):
    """返回 (merged_bom, provenance)。pid 为 None 时用当前生效项目。"""
    pid = pid or active_pid()
    base = _j(BASE, {}) or {}
    pf = os.path.join(PDIR, "%s.json" % pid)
    overlay = _j(pf, {})
    if not overlay:
        merged = base
        prov = {"pid": pid, "overlay": None, "warning": "项目档案不存在, 用平台基线"}
    else:
        merged = _merge(base, overlay)
        prov = {"pid": pid, "overlay": "config/platform/projects/%s.json" % pid,
                "overlay_sha256": _sha(pf)[:16]}
    # 项目档案可用 _append_bom_items 追加本项目特有 BOM 项 (避免在档案里整份复制基线 items ⇒ 无重复漂移)
    extra = merged.pop("_append_bom_items", None)
    if extra:
        b = merged.setdefault("bom", {})
        b["items"] = list(b.get("items") or []) + list(extra)
        prov["appended_bom_items"] = [e.get("id") for e in extra]
    merged.setdefault("project", {})
    merged["project"]["pid"] = pid
    prov.update({"base": "config/platform/zmax_project_bom.json", "base_sha256": _sha(BASE)[:16],
                 "merged_sha256": hashlib.sha256(
                     json.dumps(merged, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]})
    return merged, prov


def gaps(bom):
    """取不到的项汇总 (值为 待确认/None/空串 的叶子)。"""
    out = []

    def walk(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, path + [str(k)])
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, path + [str(i)])
        elif node is None or (isinstance(node, str) and (node.strip() in ("", "待确认") or node.startswith("待确认"))):
            out.append("/".join(path))
    walk(bom, [])
    return out


def use(pid):
    _b, prov = load(pid)
    if not os.path.exists(os.path.join(PDIR, "%s.json" % pid)):
        return None
    tmp = ACTIVE + ".tmp"
    json.dump({"pid": pid, "since": time.strftime("%F %T"),
               "by": "tools/project_profile.py --use"}, open(tmp, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    os.replace(tmp, ACTIVE)
    return _j(ACTIVE, {}) or {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--show", metavar="PID")
    ap.add_argument("--use", metavar="PID")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.use:
        r = use(a.use)
        if not r:
            print("⛔ 没有项目档案 config/platform/projects/%s.json (看 --list)" % a.use)
            return 2
        print("✅ 当前生效项目 = %s (%s)" % (r["pid"], r["since"]))
        return 0
    if a.list:
        cur = active_pid()
        print("项目档案 (config/platform/projects/):")
        for p in list_projects():
            print("  %s %-18s %-38s" % ("▶" if p["pid"] == cur else " ", p["pid"], str(p["name"])[:38]))
            print("      %s" % p["file"])
        print("  基线: config/platform/zmax_project_bom.json (平台全量; 项目档案只做覆盖)")
        return 0
    if a.show:
        bom, prov = load(a.show)
        g = gaps(bom)
        if a.json:
            print(json.dumps({"bom": bom, "provenance": prov, "gaps": g}, ensure_ascii=False, indent=1))
            return 0
        prj = bom.get("project", {})
        print("项目 %s · %s" % (prov["pid"], prj.get("name")))
        print("  客户/现场: %s / %s" % (prj.get("customer_block") or "待确认", prj.get("site") or "待确认"))
        print("  基线 sha %s · 覆盖 sha %s · 合并 sha %s"
              % (prov["base_sha256"], prov.get("overlay_sha256") or "—", prov["merged_sha256"]))
        print("  BOM 项 %d · 缺口 %d" % (len((bom.get("bom") or {}).get("items", []) or []), len(g)))
        for x in g[:14]:
            print("     缺口: %s" % x)
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
