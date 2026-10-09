#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""config_meta.py — 🧬 配置中心「元数据层」(每个功能的字段/范围/单位/依赖/验证)  2026-10-10

老倪:
  「左侧栏的配置中心, 我可以定义元数据; 所有功能, 要通过功能模块的 配置中心 修改, 要可以配置所有的功能」
  「系统架构要根据实际情况同步修改 … 你要表现出系统层即, 功能配置, 参数数值的关系」

本模块 = 功能的**元数据真源**: 把工程库里 74 个功能 (functions 表, FN-SYSx-N) 各配一份元数据,
说清每个功能的: 字段(输入/输出/参数清单) · 枚举/取值范围/单位/默认值 · 归属子系统与层(L2~L5) ·
依赖的功能/参数 · 验证方法。它是 GUI「配置中心」页面 (tools/gui/config_meta_panel.py) 的数据面,
与 param_registry.py (数字面) 互补: 数字面答「这个数改成多少」, 元数据面答「这个功能有哪些字段、能配什么」。

数据落点 (二选一, 本模块选 **JSON 真源**):
  ─ data/database/zmax/config_meta.json   ← 本模块 build 的产物 (人可编真源)
  理由 (为何不用工程库新表 config_meta):
    ① 元数据是**人工定义/可编的真源** (老倪原话「我可以定义元数据」), 与既有的参数元数据真源
       config/platform/param_spec.json 同类; param_registry 也是把『真源留 JSON, 库表是快照』——
       照此规矩, 元数据真源就该是 JSON, 而不是塞进库里当又一张表。
    ② engineering_db.py 被冻结 (本轮红线): 它的 build 用固定 SCHEMA 重建库、check 比对真源哈希。
       只在库外新加一张表, build/check 都不认它 ⇒ 一次全新 build 就可能让该表静默消失、且没有判据看住它
       (那就是一条「说已存在其实会丢」的谎)。JSON 真源跨 build 稳定、可 git diff、随 data/database/zmax
       数据包一起迁移 (老倪「迁移我的工程数据」的 tar 口径), 对 18 条 check 判据零风险。
    ③ 结论: 元数据 = JSON 真源 (可人编) + 每次可重建 (从工程库 + param_registry 派生), 不引入库内孤儿表。

真值来源 (全部真读, 不猜):
  · 工程库 functions / fn_axes(配置 cfg·标定 cal·诊断 dia 三轴) / params / param_links / product_features /
    capability_dbc / modules / links  → 功能清单、三轴、参数、能力、依赖、验证方法
  · tools/param_registry.py registry() → 每个参数的 当前值/默认/min/max/单位/档位枚举 (数字面真值)

参数→功能 的挂接规则 (每条都有据, 不是"全都挂"):
  S1 画布节点参数:  param_id 前缀 canvas:<节点名>  且 <节点名> == 功能名        (58 个功能)
  S2 代码常量参数:  param 的 source 文件 == 功能声明的 source 文件             (14 个功能)
  S3 平台 KPI 参数: 功能名 ∈ 该产品特征的 module_refs → platform:PF-… 的数     (15 个功能)
  S4 库内直挂:      param_links.kind='功能' 且 target 恰为该 fn_id             (FN-SYS0-59, MoveIt)
  G  通用标定模板:  功能 cal 轴文字里出现的标定段 (camera/plane_z/control_tcp/…) —— 属**通用模板**, 单列
  ✗ 不含糊: 只有 G (通用标定模板) 而无 S1~S4 任一 = 该功能没有"专属字段" ⇒ 判不完整, 如实列出。

完整性 (complete) 的 6 个维度 (全部满足才算完整):
  ① subsys_layer 归属子系统 + 层(L2~L5)  ② specific_params 专属参数(S1~S4 至少一类)
  ③ ranges 该功能所有有效数值参都有 min/max (或档位枚举)  ④ units 每个参数都声明 unit 字段
  ⑤ deps 依赖 (有模块/参数依赖)          ⑥ verification ≥1 条验证方法 (取自诊断 dia 轴)
  (unit 只查「字段是否声明」; 物理单位是否真给出另计 → coverage.physical_unit_ratio, 不含糊)

用法:
  python3 tools/config_meta.py build [--db PATH] [--json PATH] [--force]   # 从工程库+param_registry 生成
  python3 tools/config_meta.py list  [--func FN-XXX] [--json]              # 列功能元数据
  python3 tools/config_meta.py check [--json]                             # 完整性体检 (缺的如实列出)
  python3 tools/config_meta.py coverage                                   # 覆盖率一行汇总
"""
import argparse
import collections
import json
import os
import re
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_DEFAULT = os.path.join(ROOT, "data", "database", "zmax", "zmax_engineering.db")
JSON_OUT = os.path.join(ROOT, "data", "database", "zmax", "config_meta.json")
PARAM_SPEC = os.path.join(ROOT, "config", "platform", "param_spec.json")

# 通用标定模板段 (出现在功能 cal 轴文字里即为"该标定参数影响此功能", 但属共享模板)
CAL_ROOTS = ["camera", "plane_z", "control_tcp", "manifold_engine",
             "tool_payload", "depth_scale", "cell_geometry", "robot"]

SCHEMA_TAG = "zmax-config-meta/1.0"

# ── 人工可编的元数据补充 (老倪「我可以定义元数据」) ─────────────────────────────
# 键 = fn_id; 值是覆盖/补充字段。build 时并入派生结果 (人工字段优先, 标 author=human)。
# 留空 = 完全自动派生。示例 (可自行增删):
SEED = {
    # "FN-SYS0-37": {"inputs": ["相机 RGB-D 帧"], "outputs": ["检测框 peg/hole/hand + 置信度"],
    #                "notes": "conf 不得写死 0.99 (老倪红线: 未检出诚实标 None)"},
}


# ══════════════════════════════════════════════════════════════════════════════
# 读真值
# ══════════════════════════════════════════════════════════════════════════════
def _rel(p):
    try:
        return os.path.relpath(p, ROOT)
    except Exception:                                                          # noqa: BLE001
        return p


def load_db(db=DB_DEFAULT):
    """从工程库读功能/三轴/参数/依赖/能力 (只读)。"""
    if not os.path.exists(db):
        raise FileNotFoundError("工程库不存在: %s (先跑 tools/engineering_db.py build)" % db)
    con = sqlite3.connect(db)
    cur = con.cursor()
    out = {}
    out["functions"] = [dict(zip(("fn_id", "system_id", "name", "layer", "kind",
                                  "row_name", "module_ref", "params", "source"), r))
                        for r in cur.execute(
        "SELECT fn_id,system_id,name,layer,kind,row_name,module_ref,params,source "
        "FROM functions ORDER BY system_id,fn_id")]
    out["subsystems"] = {r[0]: dict(zip(("system_id", "name", "level", "role"), r))
                         for r in cur.execute("SELECT system_id,name,level,role FROM subsystems")}
    axes = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in cur.execute("SELECT fn_id,axis,item FROM fn_axes ORDER BY fn_id,axis,idx"):
        axes[r[0]][r[1]].append(r[2])
    out["fn_axes"] = axes
    out["params"] = [dict(zip(("param_id", "cat", "cn", "value", "default_val", "min", "max",
                               "unit", "kind", "choices", "source", "sys_id"), r))
                     for r in cur.execute(
        "SELECT param_id,cat,cn,value,default_val,min,max,unit,kind,choices,source,sys_id FROM params")]
    out["param_links"] = [dict(zip(("param_id", "kind", "target"), r))
                          for r in cur.execute("SELECT param_id,kind,target FROM param_links")]
    out["product_features"] = [dict(zip(("pf_id", "product_id", "title", "capability_ref", "kpi",
                                         "status", "descr", "subsys", "module_refs"), r))
                               for r in cur.execute("SELECT * FROM product_features")]
    out["capabilities"] = {r[0]: dict(zip(("bo_id", "grp", "name", "dirs", "brief", "explain",
                                           "iface", "inputs", "outputs"), r))
                           for r in cur.execute(
        "SELECT bo_id,grp,name,dirs,brief,explain,iface,inputs,outputs FROM capability_dbc")}
    out["modules"] = {r[0]: r[1] for r in cur.execute("SELECT name,params FROM modules")}
    out["links"] = [dict(zip(("src_type", "src_id", "dst_type", "dst_id", "kind"), r))
                    for r in cur.execute("SELECT src_type,src_id,dst_type,dst_id,kind FROM links")]
    con.close()
    return out


def load_registry():
    """数字面真值 (tools/param_registry.py)。失败返回 None (元数据仍可从库派生)。"""
    try:
        if os.path.join(ROOT, "tools") not in sys.path:
            sys.path.insert(0, os.path.join(ROOT, "tools"))
        import param_registry as pr
        reg = pr.registry()
        return {p["param_id"]: p for p in reg["params"]}
    except Exception as e:                                                     # noqa: BLE001
        sys.stderr.write("[config_meta] param_registry 不可用 (%r), 单位/枚举改用库内值\n" % (e,))
        return None


# ══════════════════════════════════════════════════════════════════════════════
# 派生
# ══════════════════════════════════════════════════════════════════════════════
def _fn_source_file(fn):
    try:
        return json.loads(fn.get("params") or "{}").get("source", "") or ""
    except Exception:                                                          # noqa: BLE001
        return ""


def _fn_flags(fn):
    try:
        d = json.loads(fn.get("params") or "{}")
    except Exception:                                                          # noqa: BLE001
        return {}
    drop = {"source", "source_symbol", "desc", "_port_labels"}
    return {k: v for k, v in d.items() if k not in drop}


def _to_num(v):
    if v is None:
        return None
    s = str(v).strip()
    if s in ("", "null", "None"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _param_view(p, reg):
    """参数统一视图: 合并库内行 + 数字面真值 (min/max/unit/choices/default/当前值)。"""
    rp = (reg or {}).get(p["param_id"], {})
    mn = p.get("min")
    mx = p.get("max")
    unit = p.get("unit")
    dv = p.get("default_val")
    val = p.get("value")
    choices = None
    status = None
    if rp:
        mn = rp.get("min", mn)
        mx = rp.get("max", mx)
        unit = rp.get("unit", unit) or unit
        dv = rp.get("default", dv)
        val = rp.get("value", val)
        choices = rp.get("choices")
        status = rp.get("status")
    if choices in (None, "null", "None", ""):
        ch = p.get("choices")
        choices = None if ch in (None, "null", "None", "") else ch
    if isinstance(choices, str):
        try:
            choices = json.loads(choices)
        except Exception:                                                      # noqa: BLE001
            choices = None
    return {
        "id": p["param_id"],
        "cn": rp.get("cn") or p.get("cn") or p["param_id"],
        "cat": p.get("cat"),
        "kind": p.get("kind") or ("enum" if choices else "numeric"),
        "value": val,
        "default": dv,
        "min": _to_num(mn),
        "max": _to_num(mx),
        "unit": (unit or "").strip(),
        "choices": choices,
        "source": p.get("source"),
        "status": status,
    }


def derive(db=DB_DEFAULT, reg=None):
    """从工程库 + param_registry 派生全部功能元数据。返回完整 meta dict。"""
    D = load_db(db)
    if reg is None:
        reg = load_registry()
    pby = {p["param_id"]: p for p in D["params"]}

    # 索引
    canvas = collections.defaultdict(list)      # 节点名 -> [param_id]
    code = collections.defaultdict(list)        # 源文件 -> [param_id]
    plat = collections.defaultdict(list)        # pf_id  -> [param_id]
    calib = []
    for p in D["params"]:
        pid = p["param_id"]
        if pid.startswith("canvas:"):
            canvas[pid.split(":", 1)[1].split("#")[0]].append(pid)
        elif pid.startswith("code:"):
            code[p.get("source") or ""].append(pid)
        elif pid.startswith("platform:"):
            plat[pid.split(":", 1)[1].split("#")[0]].append(pid)
        elif pid.startswith("calib:"):
            calib.append(p)

    pf_refs = {}
    for pf in D["product_features"]:
        try:
            refs = json.loads(pf.get("module_refs") or "[]")
        except Exception:                                                      # noqa: BLE001
            refs = []
        pf_refs[pf["pf_id"]] = (pf, refs)

    # 库内直挂 (param_links.kind=功能 且 target 恰为 fn_id)
    fn_ids = {f["fn_id"] for f in D["functions"]}
    fnlink = collections.defaultdict(list)
    for lk in D["param_links"]:
        if lk["kind"] == "功能" and lk["target"] in fn_ids:
            fnlink[lk["target"]].append(lk["param_id"])

    # 功能→模块 links / 模块→代码
    fn_mod = {}
    for lk in D["links"]:
        if lk["src_type"] == "function" and lk["kind"] == "对应模块":
            fn_mod[lk["src_id"]] = lk["dst_id"]

    out = {}
    for fn in D["functions"]:
        fid = fn["fn_id"]
        sysx = D["subsystems"].get(fn["system_id"], {})
        src_file = _fn_source_file(fn)
        axes = D["fn_axes"].get(fid, {})
        cal_txt = " ".join(axes.get("cal", []))

        # ── S1 画布节点专属参数 ──
        s1 = list(canvas.get(fn["name"], []))
        # ── S2 代码常量专属参数 (同源文件) ──
        s2 = list(code.get(src_file, [])) if src_file else []
        # ── S3 平台 KPI (该功能所属产品特征) ──
        s3, pf_list = [], []
        for pf_id, (pf, refs) in pf_refs.items():
            if fn["name"] in refs:
                pf_list.append(pf_id)
                s3 += plat.get(pf_id, [])
        # ── S4 库内直挂 ──
        s4 = list(fnlink.get(fid, []))
        specific_ids = list(dict.fromkeys(s1 + s2 + s3 + s4))
        # ── G 通用标定模板 ──
        generic_ids = []
        for p in calib:
            root = re.split(r"[.[]", p["param_id"].split(":", 1)[1])[0]
            if root in CAL_ROOTS and root in cal_txt:
                generic_ids.append(p["param_id"])
        generic_ids = list(dict.fromkeys(generic_ids))

        all_ids = list(dict.fromkeys(specific_ids + generic_ids))
        params = [_param_view(pby[i], reg) for i in all_ids if i in pby]

        # ── 字段: 输入/输出 (优先真实来源) ──
        inputs, outputs = [], []
        for pf_id in pf_list:
            cap = pf_refs[pf_id][0].get("capability_ref") or ""
            for m in re.findall(r"\b([A-H]\d)\b", cap):
                c = D["capabilities"].get(m)
                if not c:
                    continue
                for tok in re.split(r"[；;]", c.get("inputs") or ""):
                    tok = tok.strip()
                    if tok and tok not in inputs:
                        inputs.append(tok)
                for tok in re.split(r"[；;]", c.get("outputs") or ""):
                    tok = tok.strip()
                    if tok and tok not in outputs:
                        outputs.append(tok)
        flags = _fn_flags(fn)

        # ── 依赖: 功能 (共享参数/同模块组) + 参数 + 产品特征 ──
        dep_fns = []
        for other in D["functions"]:
            if other["fn_id"] == fid:
                continue
            if other["name"] in canvas and (set(canvas[other["name"]]) & set(s1)):
                dep_fns.append(other["name"])   # 共享画布参数的节点
        dep_fns = list(dict.fromkeys(dep_fns))[:12]
        dep = {
            "functions": dep_fns,
            "params": specific_ids[:40],
            "generic_baseline_params": generic_ids[:20],
            "product_features": pf_list,
            "module": fn_mod.get(fid) or fn["module_ref"],
        }

        # ── 验证方法 (取自诊断 dia 轴, 真数据) ──
        methods = list(axes.get("dia", []))
        verification = {"methods": methods, "count": len(methods),
                        "level": fn.get("layer")}

        # ── 完整性 6 维 ──
        num_params = [p for p in params if p["kind"] != "enum" and p["value"] not in (None, "null")]
        ranges_ok = bool(num_params) or any(p["choices"] for p in params)
        ranges_ok = all((p["min"] is not None and p["max"] is not None) or p["choices"]
                        for p in num_params) if num_params else bool(params)
        units_ok = bool(params) and all((p["unit"] or "").strip() != "" for p in params)
        dims = {
            "subsys_layer": bool(fn["system_id"] and fn["layer"]),
            "specific_params": bool(specific_ids),
            "ranges": ranges_ok,
            "units": units_ok,
            "deps": bool(dep["module"]) and (bool(dep_fns) or bool(specific_ids)),
            "verification": bool(methods),
        }
        missing = [k for k, v in dims.items() if not v]
        complete = not missing

        # 人工 SEED 覆盖
        seeded = dict(SEED.get(fid, {}))
        rec = {
            "fn_id": fid,
            "name": fn["name"],
            "system_id": fn["system_id"],
            "subsystem": sysx.get("name", fn["system_id"]),
            "layer": fn["layer"],
            "kind": fn["kind"],
            "row_name": fn["row_name"],
            "module_ref": fn["module_ref"],
            "code_file": src_file,
            "fields": {
                "inputs": seeded.get("inputs", inputs),
                "outputs": seeded.get("outputs", outputs),
                "declared_flags": flags,
                "parameters": params,
            },
            "enums": {p["id"]: p["choices"] for p in params if p["choices"]},
            "ranges": [{"id": p["id"], "min": p["min"], "max": p["max"],
                        "unit": p["unit"], "default": p["default"],
                        "choices": p["choices"]} for p in params],
            "deps": dep,
            "verification": ({"methods": seeded["verification"], "count": len(seeded["verification"]),
                              "level": fn.get("layer")} if seeded.get("verification") else verification),
            "meta_axes": {ax: list(axes.get(ax, [])) for ax in ("cfg", "cal", "dia")},
            "completeness": {"dims": dims, "missing": missing, "complete": complete,
                             "specific_param_count": len(specific_ids),
                             "generic_param_count": len(generic_ids)},
        }
        if seeded.get("notes"):
            rec["notes"] = seeded["notes"]
            rec["completeness"]["author"] = "human"
        out[fid] = rec

    # 覆盖率
    total = len(out)
    complete = sum(1 for r in out.values() if r["completeness"]["complete"])
    incomplete = [{"fn_id": r["fn_id"], "name": r["name"], "system_id": r["system_id"],
                   "missing": r["completeness"]["missing"]}
                  for r in out.values() if not r["completeness"]["complete"]]
    # 物理单位覆盖率 (参数里 unit 字段真给出物理单位, 非 '-')
    all_params = [p for r in out.values() for p in r["fields"]["parameters"]]
    phys = [p for p in all_params if (p["unit"] or "").strip() not in ("", "-")]
    meta = {
        "schema": SCHEMA_TAG,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "sources": {
            "engineering_db": _rel(db),
            "param_registry": "tools/param_registry.py",
            "param_spec": _rel(PARAM_SPEC),
        },
        "definition": {
            "complete": "6 维全满足: subsys_layer + specific_params + ranges + units + deps + verification",
            "specific_params": "功能专属参数 (S1 画布节点 / S2 代码同源 / S3 平台KPI / S4 库内直挂)",
            "generic_params": "G 通用标定模板 (共享, 不计入 specific)",
            "units_dim": "仅查 unit 字段是否声明; 物理单位真实覆盖率另见 coverage.physical_unit_ratio",
        },
        "coverage": {
            "total": total,
            "complete": complete,
            "complete_ratio": round(complete / total, 4) if total else 0.0,
            "incomplete": incomplete,
            "params_total": len(all_params),
            "params_with_physical_unit": len(phys),
            "physical_unit_ratio": round(len(phys) / len(all_params), 4) if all_params else 0.0,
        },
        "functions": out,
    }
    return meta


# ══════════════════════════════════════════════════════════════════════════════
# 原子操作
# ══════════════════════════════════════════════════════════════════════════════
def build(db=DB_DEFAULT, out=JSON_OUT, force=False, quiet=False):
    meta = derive(db)
    if os.path.exists(out) and not force:
        # 合并: 保留人工在既有 JSON 里加的字段 (author=human / notes)
        try:
            old = json.load(open(out, encoding="utf-8"))
            for fid, rec in (old.get("functions") or {}).items():
                if rec.get("completeness", {}).get("author") == "human" and fid in meta["functions"]:
                    meta["functions"][fid]["notes"] = rec.get("notes")
                    meta["functions"][fid]["completeness"]["author"] = "human"
        except Exception:                                                      # noqa: BLE001
            pass
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    if not quiet:
        c = meta["coverage"]
        print("✅ 生成 %s" % _rel(out))
        print("   功能 %d 个 · 完整 %d · 不完整 %d (物理单位覆盖 %.1f%%)" %
              (c["total"], c["complete"], len(c["incomplete"]), c["physical_unit_ratio"] * 100))
        if c["incomplete"]:
            print("   不完整(缺哪些维度):")
            for r in c["incomplete"]:
                print("     %-12s %-40s 缺: %s" % (r["fn_id"], r["name"][:40], ",".join(r["missing"])))
    return meta


def load(out=JSON_OUT):
    if not os.path.exists(out):
        return build(quiet=True)
    with open(out, encoding="utf-8") as f:
        return json.load(f)


def check(out=JSON_OUT):
    meta = load(out)
    c = meta["coverage"]
    print("🧬 配置元数据完整性体检 (%s)" % meta["schema"])
    print("   来源: %s + %s" % (meta["sources"]["engineering_db"], meta["sources"]["param_registry"]))
    print("   功能总数: %d · 完整: %d · 不完整: %d" % (c["total"], c["complete"], len(c["incomplete"])))
    print("   参数行: %d · 带物理单位: %d (%.1f%%)" %
          (c["params_total"], c["params_with_physical_unit"], c["physical_unit_ratio"] * 100))
    dims_fail = collections.Counter()
    for r in c["incomplete"]:
        for m in r["missing"]:
            dims_fail[m] += 1
    if dims_fail:
        print("   缺维度统计: %s" % dict(dims_fail))
    for r in c["incomplete"]:
        print("   ❌ %-12s %-42s 缺: %s" % (r["fn_id"], r["name"][:42], ",".join(r["missing"])))
    print("   %s" % ("✅ 全部功能元数据完整" if not c["incomplete"] else
                     "⚠️ %d 个功能元数据不完整 (如上, 未把未定义的算作已定义)" % len(c["incomplete"])))
    return 0 if not c["incomplete"] else 1


def coverage(out=JSON_OUT):
    c = load(out)["coverage"]
    print("元数据覆盖率: %d/%d 完整 (%.1f%%) · 不完整: %s" %
          (c["complete"], c["total"], c["complete_ratio"] * 100,
           ", ".join(r["fn_id"] for r in c["incomplete"]) or "无"))
    return c


def _print_fn(rec):
    print("─" * 78)
    print("%s  %s" % (rec["fn_id"], rec["name"]))
    print("  归属: %s (%s) · 层: %s · 模块: %s" %
          (rec["subsystem"], rec["system_id"], rec["layer"], rec["module_ref"]))
    if rec.get("code_file"):
        print("  代码: %s" % rec["code_file"])
    f = rec["fields"]
    print("  输入: %s" % ("; ".join(f["inputs"]) or "(未定义)"))
    print("  输出: %s" % ("; ".join(f["outputs"]) or "(未定义)"))
    print("  参数 (%d):" % len(f["parameters"]))
    for p in f["parameters"][:14]:
        rng = ("[%s, %s]" % (p["min"], p["max"])) if p["min"] is not None else (
            (p["choices"] or "") if p["choices"] else "范围未定义")
        print("     %-46s = %-10s 默认 %-8s %s %s %s" %
              (p["id"][:46], str(p["value"])[:10], str(p["default"])[:8],
               rng, p["unit"] or "-", ("<%s>" % p["cat"]) if p["cat"] else ""))
    if len(f["parameters"]) > 14:
        print("     … 另 %d 个" % (len(f["parameters"]) - 14))
    d = rec["deps"]
    print("  依赖功能: %s" % ("; ".join(d["functions"][:8]) or "(无)"))
    print("  依赖产品特征: %s · 模块: %s" % (", ".join(d["product_features"]) or "-", d["module"]))
    print("  验证方法 (%d): %s" % (rec["verification"]["count"],
                                  "; ".join(rec["verification"]["methods"][:4]) or "(无)"))
    cc = rec["completeness"]
    print("  完整性: %s%s" % ("✅ 完整" if cc["complete"] else "❌ 缺 " + ",".join(cc["missing"]),
          " (专属参数 %d · 通用标定 %d)" % (cc["specific_param_count"], cc["generic_param_count"])))


def main(argv=None):
    ap = argparse.ArgumentParser(description="配置中心元数据层 (每个功能的字段/范围/单位/依赖/验证)")
    sub = ap.add_subparsers(dest="cmd")
    b = sub.add_parser("build", help="从工程库+param_registry 生成元数据")
    b.add_argument("--db", default=DB_DEFAULT)
    b.add_argument("--json", default=JSON_OUT)
    b.add_argument("--force", action="store_true")
    l = sub.add_parser("list", help="列功能元数据")
    l.add_argument("--func", default=None)
    l.add_argument("--json", action="store_true")
    c = sub.add_parser("check", help="完整性体检")
    c.add_argument("--json", action="store_true")
    sub.add_parser("coverage", help="覆盖率一行")
    a = ap.parse_args(argv)

    if a.cmd == "build":
        build(a.db, a.json, a.force)
        return 0
    if a.cmd == "list":
        meta = load()
        if a.func:
            rec = meta["functions"].get(a.func)
            if not rec:
                sys.stderr.write("找不到功能: %s\n" % a.func)
                return 2
            if a.json:
                print(json.dumps(rec, ensure_ascii=False, indent=1))
            else:
                _print_fn(rec)
            return 0
        if a.json:
            print(json.dumps(meta, ensure_ascii=False, indent=1))
        else:
            for fid in sorted(meta["functions"], key=lambda k: (meta["functions"][k]["system_id"], k)):
                r = meta["functions"][fid]
                print("%-12s %-4s %-9s %2d参 %s %s" %
                      (fid, r["system_id"], r["layer"], len(r["fields"]["parameters"]),
                       "✅" if r["completeness"]["complete"] else "❌", r["name"]))
        return 0
    if a.cmd == "check":
        if a.json:
            print(json.dumps(load()["coverage"], ensure_ascii=False, indent=1))
            return 0
        return check()
    if a.cmd == "coverage":
        coverage()
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
