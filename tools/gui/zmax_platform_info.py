#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""zmax_platform_info.py — Z-MAX 平台描述/计数的**单一读取口** (主控制台左侧卡面 ↔ 配置中心·产品配置页)。

为什么要它: 老倪 2026-10-15 —— 「产品配置页面, 对应主控制台左侧 Z-MAX 平台描述, 你同步信息」。
两侧原来各写各的字符串 ('Z700 精细 · Z100 通用' 硬写在 studio 的卡面上), 改一处另一处不动 ⇒ 界面互相矛盾。
这里把**描述串与计数**都收成一处, 两边都调这里, 想改只能改这一处 (改完两侧同时变)。

真源 (不改数据库; 库是生成物):
  · 平台/产品描述 → `config/platform/zmax_platform.json` (人可编·进 git): platform.name / products[].name+category
  · 特征/系统/功能/参数计数 → 单一工程库 `data/database/zmax/zmax_engineering.db` (与 studio._live_counts 同口径)
  · 产品档位 (550A/B/C) → `config/platform/zmax_product.json`

用法:
    from zmax_platform_info import zmax_platform_info
    info = zmax_platform_info()
    info["short"]        # 'Z700 精细 · Z100 通用'
    info["full"]         # 'Z700 精细操作机器人 · Z100 通用操作机器人'
    info["name"]         # 'Z-MAX 具身智能机器人平台'
    info["counts"]       # {'特征': .., '系统': .., '功能': .., '参数': ..}
    info["lines"]        # 配置页上那三行 (可直接打印/复制)
"""
from __future__ import annotations

import json
import os
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PLATFORM_J = os.path.join(ROOT, "config", "platform", "zmax_platform.json")
PRODUCT_J = os.path.join(ROOT, "config", "platform", "zmax_product.json")
DB = os.path.join(ROOT, "data", "database", "zmax", "zmax_engineering.db")

_CACHE: dict = {"key": None, "v": None}


def _mtime(p):
    try:
        return os.path.getmtime(p)
    except OSError:
        return -1.0


def _j(p, default=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                           # noqa: BLE001
        return default


def _counts():
    """工程库三轴计数 (与 studio._live_counts 同一张表/同一条 SQL; 库不在就给 None, 不猜)。"""
    out = {"特征": None, "系统": None, "功能": None, "参数": None}
    if not os.path.exists(DB):
        return out
    try:
        con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
        for k, tbl in (("特征", "product_features"), ("系统", "subsystems"),
                       ("功能", "functions"), ("参数", "params")):
            try:
                out[k] = con.execute("select count(*) from %s" % tbl).fetchone()[0]
            except Exception:                                                   # noqa: BLE001
                out[k] = None
        con.close()
    except Exception:                                                           # noqa: BLE001
        pass
    return out


def _jstr(v):
    """库里存的可能是 JSON 文本 (kpi) —— 能解析就返回 dict, 不能就原样。"""
    if v is None:
        return {}
    try:
        out = json.loads(v)
        return out if isinstance(out, dict) else {"_": out}
    except Exception:                                                           # noqa: BLE001
        return {"_": v}


def _jlist(v):
    """库里存的可能是 JSON 数组文本 (subsys / module_refs) —— 解析失败返回空表, 不猜。"""
    if not v:
        return []
    try:
        out = json.loads(v)
        return out if isinstance(out, list) else [out]
    except Exception:                                                           # noqa: BLE001
        return []


def _db_rows(sql):
    """只读工程库取行 (库不在/表不在 → 空表, 不猜)。"""
    if not os.path.exists(DB):
        return []
    try:
        con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
        rows = list(con.execute(sql))
        con.close()
        return rows
    except Exception:                                                           # noqa: BLE001
        return []


def platform_page_data():
    """主控制台「🏭 Z-MAX 平台」页**同一批**真源 (platform / products / product_features / functions)。

    老倪 2026-10-15: 「产品配置页面, 要复用 Z-MAX 平台的页面描述, 里面有产品特性」;
    同一天: 「功能配置, 要包括 系统1 系统2 系统0 的所有功能, 还有功能清单的汇总」。
    都从单一工程库读 (库是生成物; 人可编真源是 config/platform/zmax_platform.json)。
    """
    p = _db_rows("select platform_id, name, positioning, architecture, data_contract from platform")
    prods = _db_rows("select product_id, name, category, positioning, kpi from products")
    feats = _db_rows("select pf_id, product_id, title, capability_ref, kpi, status, subsys, module_refs"
                     " from product_features")
    fns = _db_rows("select fn_id, system_id, name, layer, kind, module_ref, params from functions")
    return {
        "platform": ({"platform_id": p[0][0], "name": p[0][1], "positioning": p[0][2],
                      "architecture": p[0][3], "data_contract": p[0][4]} if p else {}),
        "products": [{"id": r[0], "name": r[1], "category": r[2], "positioning": r[3], "kpi": _jstr(r[4])}
                     for r in prods],
        "features": [{"pf_id": r[0], "product": r[1], "title": r[2], "capability": r[3], "kpi": r[4],
                      "status": r[5], "subsys": _jlist(r[6]), "modules": _jlist(r[7])} for r in feats],
        "functions": [{"fn_id": r[0], "sys": r[1], "name": r[2], "layer": r[3], "kind": r[4],
                       "module": r[5], "params": r[6]} for r in fns],
    }


def function_summary(fns=None):
    """功能清单汇总: 按系统分组条数 (系统2/系统1/系统0/平台支撑) + 合计 —— 功能配置页用。"""
    fns = fns if fns is not None else platform_page_data()["functions"]
    order = (("sys2", "系统 2"), ("sys1", "系统 1"), ("sys0", "系统 0"), ("plat", "平台支撑"))
    by = {}
    for f in fns:
        by[f["sys"]] = by.get(f["sys"], 0) + 1
    parts = ["%s %d" % (cn, by.get(sid, 0)) for sid, cn in order if by.get(sid, 0)]
    for sid, n in sorted(by.items()):                # 兜底: 没见过的 system_id 不许吞掉
        if sid not in [x[0] for x in order]:
            parts.append("%s %d" % (sid, n))
    return {"by": by, "total": len(fns), "text": " · ".join(parts) + " · 合计 %d 条" % len(fns)}


def zmax_platform_info():
    """平台描述 + 计数 + 产品档位 (按真源 mtime 缓存, 改真源自动失效)。"""
    key = (_mtime(PLATFORM_J), _mtime(DB), _mtime(PRODUCT_J))
    if _CACHE["key"] == key and _CACHE["v"] is not None:
        return _CACHE["v"]
    pj = _j(PLATFORM_J, {}) or {}
    plat = pj.get("platform", {}) or {}
    prods = pj.get("products", []) or []
    short = " · ".join("%s %s" % (p.get("product_id", "?"), (p.get("category") or "")[:2]) for p in prods) or "取不到"
    full = " · ".join(p.get("name") or p.get("product_id") or "?" for p in prods) or "取不到"
    pr = _j(PRODUCT_J, {}) or {}
    cnt = _counts()
    miss = [k for k, v in cnt.items() if v is None]
    v = {
        "name": plat.get("name") or "取不到",
        "positioning": (plat.get("positioning") or "").strip(),
        "short": short,
        "full": full,
        "products": [(p.get("product_id"), p.get("name"), p.get("category")) for p in prods],
        "counts": cnt,
        "counts_missing": miss,          # 空 = 全部取到; 非空 = 缺哪几项 (界面要写明"取不到")
        "active_product": pr.get("active_product") or pr.get("active") or "",
        "product_mtime": _mtime(PRODUCT_J),
        "src": os.path.relpath(PLATFORM_J, ROOT),
    }
    v["lines"] = [
        "🏭 %s (与主控制台左侧同源: %s)" % (v["name"], v["src"]),
        v["full"],
        "%s | 产品档位 %s" % (
            " · ".join("%s %s" % (k, v["counts"][k]) for k in ("特征", "系统", "功能", "参数")),
            v["active_product"] or "取不到"),
    ]
    if miss:
        v["lines"][2] += " (取不到: %s)" % "/".join(miss)
    _CACHE["key"], _CACHE["v"] = key, v
    return v


if __name__ == "__main__":
    import pprint
    i = zmax_platform_info()
    pprint.pprint({k: i[k] for k in ("name", "short", "full", "counts", "active_product", "src")})
    for ln in i["lines"]:
        print("   " + ln)
