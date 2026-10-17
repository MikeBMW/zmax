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


def _repo_root():
    """仓库根 —— 按标记向上找 (2026-10-17 从 tools/gui 归位到 src/ 后, 写死 dirname×3 会指错)。"""
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        if os.path.isdir(os.path.join(d, "src", "lerobot")) and os.path.isdir(os.path.join(d, "tools")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


import json
import os
import sqlite3

ROOT = _repo_root()
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


# ══════════════════════════════════════════════════════════════════════════════
# 🧠 层模型 (L2/L3/L4/L5) ←→ 功能配置 映射
#   老倪 2026-10-15: 「模型配置, 要映射功能配置和 L2 L3 L4 L5层模型, 这是主要信息。你来同步全局数据」
#   真源两处, 都不许手抄:
#     ① 各层在役模型 → `models/active_models.json` (人可编指针; 换模型只改这里, 模型引擎窗口也读它)
#     ② 功能清单+层标签 → 单一工程库 `functions` 表 (layer 字段: L2 / L3 / L4/L5 / PLAT)
# ══════════════════════════════════════════════════════════════════════════════
ACTIVE_MODELS_J = os.path.join(ROOT, "models", "active_models.json")

# 层的短职责 (界面标签; 真职责串在 active_models.json 的 role 字段)
LAYER_ROLE = {
    "L5": "认知/规划/记忆 · 慢决策",
    "L4": "意图-动作 · 世界模型",
    "L3": "策略执行 (动作输出)",
    "L2": "检测/感知 (2D→3D 输入)",
    "PLAT": "平台支撑 (工具链/接口)",
}
LAYER_ORDER = ("L5", "L4", "L3", "L2")


def short_model_name(name):
    """显示短名: 去掉行首 `L5 · ` 前缀 + 去掉尾部括号限定词 (完整名始终留给 tooltip/复制)。"""
    import re as _re
    s = _re.sub(r"^L\d\s*[·:：]\s*", "", str(name or "").strip())
    s = _re.sub(r"\s*[（(][^）)]*[）)]\s*$", "", s).strip()
    return s or "—"


_MATRIX_CACHE = {"t": 0.0, "v": None}


def matrix_columns(timeout=60):
    """主控制台「模型配置矩阵」的四层列 —— `tools/model_config_matrix.py --json` 的 columns[]。

    老倪 2026-10-15: 「你来同步全局数据」⇒ 本页四层的「在役模型/版本」必须和**主控制台那份矩阵同一条**,
    不能各读一半 (实测 model_inventory 单独跑会把 L5 报成 SmolVLM, 而主控制台报 DeepSeek 视觉规划 —— 两边打架)。
    300s 进程内缓存; 取不到返回 {} (界面写"取不到", 不猜)。
    """
    import subprocess
    import time as _time
    if _MATRIX_CACHE["v"] is not None and (_time.time() - _MATRIX_CACHE["t"]) < 300:
        return _MATRIX_CACHE["v"]
    out = {}
    try:
        r = subprocess.run([os.path.join(ROOT, "gui-venv311", "bin", "python"),
                            os.path.join(ROOT, "tools", "model_config_matrix.py"), "--json"],
                           capture_output=True, text=True, timeout=timeout, cwd=ROOT)
        for c in ((json.loads(r.stdout or "{}") or {}).get("columns") or []):
            ly = str(c.get("layer") or "").strip()
            if ly:
                out[ly] = {"name": c.get("在役模型") or "", "version": c.get("版本") or "",
                           "state": c.get("状态") or ""}
    except Exception:                                                           # noqa: BLE001
        out = {}
    _MATRIX_CACHE["t"], _MATRIX_CACHE["v"] = _time.time(), out
    return out


_INV_CACHE = {"t": 0.0, "v": None}


def _inventory_models(timeout=60):
    """`tools/model_inventory.py --json` 的 models[] (与「模型引擎」窗口/主控制台同一命令)。

    只当**兜底**: active_models.json 里没登记主指针的层 (如 L5) 用它补; 60s 进程内缓存 (子进程不便宜)。
    取不到就返回 [] —— 界面写"取不到", 不猜。
    """
    import subprocess
    import time as _time
    if _INV_CACHE["v"] is not None and (_time.time() - _INV_CACHE["t"]) < 60:
        return _INV_CACHE["v"]
    out = []
    try:
        r = subprocess.run([os.path.join(ROOT, "gui-venv311", "bin", "python"),
                            os.path.join(ROOT, "tools", "model_inventory.py"), "--json"],
                           capture_output=True, text=True, timeout=timeout, cwd=ROOT)
        out = (json.loads(r.stdout or "{}") or {}).get("models") or []
    except Exception:                                                           # noqa: BLE001
        out = []
    _INV_CACHE["t"], _INV_CACHE["v"] = _time.time(), out
    return out


def active_models():
    """各层在役模型 (真源 models/active_models.json; 按 mtime 缓存, 读不到写"取不到"不回退)。"""
    key = _mtime(ACTIVE_MODELS_J)
    if _CACHE.get("am_key") == key and _CACHE.get("am") is not None:
        return _CACHE["am"]
    d = _j(ACTIVE_MODELS_J, {}) or {}
    _extra_all = d.get("extra_in_service") or {}          # 顶层键: 每层**多条**在役 (基座 + 适配层/技能包)
    inv = _inventory_models()                             # 兜底真源: model_inventory --json (与模型引擎窗口同源)
    mx = matrix_columns()                                 # **优先**: 主控制台模型矩阵 (全局同名, 避免两边打架)
    layers = {}
    for ly in LAYER_ORDER:
        e = d.get(ly) or {}
        extra = _extra_all.get(ly) or []
        _m = mx.get(ly) or {}
        _name = (_m.get("name") or "").strip()
        _src = "tools/model_config_matrix.py (与主控制台同一份)" if _name else ""
        _ver, _st = _m.get("version") or "", _m.get("state") or ""
        if not _name:                                     # 矩阵取不到 → 退回指针真源
            _name = e.get("name") or ""
            _src = "models/active_models.json" if _name else ""
        if not _name:                                     # 还没有 → 引擎清单里的在役行兜 (如 L5)
            for m in (inv or []):
                if str(m.get("layer") or "").strip() == ly and m.get("active") and m.get("name"):
                    _name, _src = m.get("name"), "tools/model_inventory.py"
                    break
        layers[ly] = {
            "name": _name or "取不到",
            "short": short_model_name(_name) if _name else "取不到",
            "kind": e.get("kind") or "",
            "path": e.get("path") or "",
            "role": e.get("role") or "",
            "note": e.get("note") or "",
            "pointer": bool(e.get("pointer")),
            "primary_src": _src,                          # 主模型名字是从哪个真源读到的 (界面要能看出来)
            "version": _ver, "state": _st,                # 版本/在役状态 (矩阵给的; 主控制台同值)
            "extra": [{"name": x.get("name") or "", "short": short_model_name(x.get("name")),
                       "path": x.get("path") or "", "role": x.get("role") or ""} for x in extra],
        }
    v = {"layers": layers, "schema": d.get("schema") or "", "note": d.get("note") or "",
         "src": os.path.relpath(ACTIVE_MODELS_J, ROOT), "mtime": key,
         "missing": [ly for ly in LAYER_ORDER if not (d.get(ly) or {}).get("name")],
         "inventory_rows": len(inv or [])}
    _CACHE["am_key"], _CACHE["am"] = key, v
    return v


def function_layer_map():
    """功能配置 ←→ L2/L3/L4/L5 层模型 的**全量映射** (工程库 functions.layer × active_models.json)。

    返回 rows: 每个功能一行 —— {fn_id, name, sys, layer('L4/L5'), layers[], models[], model_text, module, role}
    · layer 里是斜杠组合 (如 'L4/L5') 时两条模型都列, 不许只取一条;
    · layer=PLAT (平台支撑) 明写"不归属层模型", 不许静默丢;
    · 某层在 active_models.json 里没登记 → 显示 '<层> 未登记 (真源缺项)', 不退回别的模型名。
    """
    am = active_models()["layers"]
    fns = platform_page_data()["functions"]
    rows = []
    for f in fns:
        ly = (f["layer"] or "").strip()
        lys = [x.strip() for x in ly.split("/") if x.strip()] if ly else []
        mds, roles = [], []
        for l in lys:
            if l.upper().startswith("PLAT"):
                mds.append("平台支撑 (不归属层模型)")
                roles.append(LAYER_ROLE.get("PLAT", ""))
                continue
            e = am.get(l)
            if e and e.get("name") != "取不到":
                mds.append(e["short"])
                roles.append(e.get("role") or LAYER_ROLE.get(l, ""))
            else:
                mds.append("%s 未登记" % l)
                roles.append(LAYER_ROLE.get(l, ""))
        if not lys:
            mds, roles = ["层未登记"], [""]
        rows.append({
            "fn_id": f["fn_id"], "name": f["name"], "sys": f["sys"], "layer": ly or "未登记",
            "layers": lys, "models": mds, "model_text": " + ".join(mds),
            "module": f.get("module") or "", "role": " / ".join(r for r in roles if r),
        })
    return {"rows": rows, "src": os.path.relpath(ACTIVE_MODELS_J, ROOT),
            "src_functions": "工程库 functions 表", "total": len(rows)}


def layer_summary():
    """四层一行 (界面/复制用): 层 · 短职责 · 在役模型短名 · 额外在役条目 · 权重指针 · 承载功能数 · 功能示例。

    计数与示例都从 function_layer_map() 现算 (改真源自动跟着变)。
    """
    am = active_models()
    m = function_layer_map()
    out = []
    for ly in LAYER_ORDER:
        e = am["layers"].get(ly) or {}
        _mine = [r for r in m["rows"] if ly in (r["layers"] or [])]
        out.append({
            "layer": ly, "role": LAYER_ROLE.get(ly, ""),
            "model": e.get("short") or "取不到", "model_full": e.get("name") or "取不到",
            "src": e.get("primary_src") or "取不到",
            "version": e.get("version") or "取不到", "state": e.get("state") or "",
            "extra": [x["short"] for x in (e.get("extra") or [])],
            "path": e.get("path") or "取不到", "role_full": e.get("role") or "",
            "fn_count": len(_mine),
            "fn_examples": [("%s %s" % (r["fn_id"], r["name"])) for r in _mine[:3]],
        })
    _plat = [r for r in m["rows"] if "PLAT" in (r["layers"] or []) or r["layer"].upper().startswith("PLAT")]
    out.append({"layer": "PLAT", "role": LAYER_ROLE["PLAT"], "model": "平台支撑 (不归属层模型)", "src": "工程库 functions 表",
                "model_full": "", "extra": [], "path": "", "role_full": "", "version": "—", "state": "—",
                "fn_count": len(_plat), "fn_examples": [("%s %s" % (r["fn_id"], r["name"])) for r in _plat[:3]]})
    return {"rows": out, "src": am["src"], "missing": am["missing"], "total_fn": m["total"]}


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
