#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""config_center_load.py — 📚 配置中心全量装载器 (给画布「主参数M」节点直接指导模型用)  2026-10-11

老倪原话: 「你要把配置中心的所有配置文件, 加载到 状态空间工程的 标定诊断测量 主参数M 节点,
          这个节点的代码, 要加载配置中心的数据库文件, json文件, yaml文件等, 直接指导模型工作」

装什么 (真源, 一个不落):
  · config/**/*.json          (calib/mcd/orders/tasks/platform/robot/state_machines/... + 任务绑定)
  · config/**/*.yaml|*.yml    (机器人/驱动配置)
  · config/*.db + data/database/zmax/*.db  (工程库 SQLite: 24 表 → 行数 + 关键表样本)
  · *.bak* 只登记不解析 (历史备份, 不参与引导)
导出「模型指导参数」guide (节点执行时直接喂模型):
  M / inertia (主参数, 标定真源同源) · dt (控制周期) · limits (活跃任务 safety/公差/力/速度, 原样键值)
  · task (活跃任务 · 档位开 · 启用/禁用节点) · geometry (K/手眼/plane_z) · mcd (参数就绪/缺口)
  · orders / tasks 计数 · platform · robot
产物: config/cc_snapshot.json (可审计: 每文件 md5/字节/条目 + 解析失败原因)
CLI: python tools/config_center_load.py build|show|guide|check
"""
import argparse
import glob
import hashlib
import json
import os
import re
import sqlite3
import sys
import time

ROOT = os.environ.get("ZMAX_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CFG = os.path.join(ROOT, "config")
OUT = os.path.join(CFG, "cc_snapshot.json")
DB_GLOBS = ("data/database/zmax/*.db", "config/*.db")
BAK_RE = re.compile(r"\.bak|\.tmp$|~$|待删|_old", re.I)
LIM_KW = re.compile(r"(force|torque|力|v_max|vel|速度|speed|depth|插入深度|公差|tol|limit|上限|max)", re.I)
DT_KW = re.compile(r"(dt|period|cycle|节拍|周期|time_?step|step_?t|freq)", re.I)
K_KW = re.compile(r"(^|_)(K|intrinsics|fx|fy|cx|cy|camera_matrix)($|_)|内参", re.I)
HE_KW = re.compile(r"(hand.?eye|T_cam|T_tool|ext_T|base_cam|base2cam|x2cam|外参|手眼)", re.I)


def _md5(p):
    h = hashlib.md5()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 16), b""):
            h.update(b)
    return h.hexdigest()[:16]


def _yaml_load(text):
    try:
        import yaml
        return yaml.safe_load(text)
    except Exception:                                                          # noqa: BLE001
        try:                                                                   # 退路: 极简 k: v 解析 (只读不回写)
            out = {}
            for ln in text.splitlines():
                m = re.match(r"^\s*([A-Za-z0-9_.\-]+)\s*:\s*(.+?)\s*$", ln)
                if m:
                    out[m.group(1)] = m.group(2)
            return out or None
        except Exception:                                                      # noqa: BLE001
            return None


def _count(obj):
    if isinstance(obj, dict):
        return len(obj)
    if isinstance(obj, list):
        return len(obj)
    return 1 if obj is not None else 0


def _db_read(path):
    """SQLite → {table: {rows, sample}}; 只读打开。"""
    out = {"path": os.path.relpath(path, ROOT), "tables": {}, "rows_total": 0, "err": None}
    try:
        con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
        cur = con.cursor()
        names = [r[0] for r in cur.execute("select name from sqlite_master where type='table' order by name")]
        for t in names:
            try:
                n = cur.execute('select count(*) from "%s"' % t).fetchone()[0]
            except Exception:                                                  # noqa: BLE001
                n = -1
            out["tables"][t] = n
            out["rows_total"] += max(0, n)
        con.close()
    except Exception as e:                                                     # noqa: BLE001
        out["err"] = "%s: %s" % (type(e).__name__, e)
    return out


def scan():
    """配置中心全量清单 (含 .bak 分组)。"""
    files, baks = [], []
    pats = [os.path.join(CFG, "**", "*"), os.path.join(ROOT, "config", "*")]
    seen = set()
    for pat in pats:
        for p in glob.glob(pat, recursive=True):
            if not os.path.isfile(p) or p in seen:
                continue
            seen.add(p)
            (baks if BAK_RE.search(os.path.basename(p)) else files).append(p)
    dbs = []
    for g in DB_GLOBS:
        dbs += [p for p in glob.glob(os.path.join(ROOT, g)) if os.path.isfile(p)]
    return sorted(files), sorted(baks), sorted(set(dbs))


def _parse(path):
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".json":
            with open(path, encoding="utf-8") as f:
                return json.load(f), None
        if ext in (".yaml", ".yml"):
            with open(path, encoding="utf-8") as f:
                obj = _yaml_load(f.read())
            return obj, (None if obj is not None else "YAML 解析不可用 (无 PyYAML)")
        if ext in (".txt", ".md", ".csv", ".db", ""):
            return None, None
        return None, None
    except Exception as e:                                                     # noqa: BLE001
        return None, "%s: %s" % (type(e).__name__, e)


TXT_LIM = re.compile(r"(F[xyz]|力|速度|扭矩)\s*[>≥<=]{0,2}\s*(\d+(?:\.\d+)?)\s*(N|mm|m/s|度|°)?", re.I)


def _text_limits(task):
    """safety 之类的**文本**里写死的限值 (如「力阈值 Fz>5N」) → 摘出来, 标 source=文本 (不造)。"""
    out = {}
    for sec in ("safety", "notes", "note", "循环", "loop"):
        s = (task or {}).get(sec)
        if isinstance(s, str) and s:
            for m in TXT_LIM.finditer(s):
                out["%s.文本:%s%s" % (sec, m.group(1), m.group(3) or "")] = float(m.group(2))
    return out


def _find_limits(task):
    """活跃任务的 safety/targets/overrides → 限值键值 (原样取, 不造名)。"""
    out = {}
    for sec in ("safety", "targets", "overrides"):
        v = (task or {}).get(sec)
        if isinstance(v, dict):
            for k, val in v.items():
                if isinstance(val, (int, float)) and LIM_KW.search(str(k)):
                    out["%s.%s" % (sec, k)] = val
                elif isinstance(val, dict):
                    for k2, v2 in val.items():
                        if isinstance(v2, (int, float)) and LIM_KW.search(str(k2)):
                            out["%s.%s.%s" % (sec, k, k2)] = v2
    out.update(_text_limits(task))
    return out


def build(write=True):
    files, baks, dbs = scan()
    loaded, failures = {}, {}
    docs = {}
    for p in files:
        obj, err = _parse(p)
        rel = os.path.relpath(p, ROOT)
        _b = os.path.getsize(p)
        rec = {"bytes": _b,
               # >2MB 的二进制 (URDF mesh 等) 只登记大小, 不算 md5 (装载要快, 它们不参与引导)
               "md5": (_md5(p) if _b <= 2 << 20 else None),
               "ext": os.path.splitext(p)[1].lower()}
        if err:
            rec["error"] = err
            failures[rel] = err
        else:
            rec["entries"] = _count(obj)
            docs[rel] = obj
        loaded[rel] = rec
    db_docs = {}
    for p in dbs:
        d = _db_read(p)
        db_docs[d["path"]] = d
        if d["err"]:
            failures[d["path"]] = d["err"]

    bind = docs.get("config/ss_task_binding.json") or {}
    tasks = bind.get("tasks") or []
    active = bind.get("active_task")
    at = next((t for t in tasks if t.get("task_id") == active), {}) or {}
    calib = docs.get("config/calib/zmax_calib.json") or {}
    mcd = docs.get("config/mcd/param_registry.json") or {}
    reg = mcd.get("params") if isinstance(mcd, dict) else None
    ready = len([x for x in (reg or []) if isinstance(x, dict) and (x.get("ready") or x.get("status") == "ready")]) \
        if isinstance(reg, list) else None
    run_cfg = at.get("run_cfg") or {}
    rc_on = [k for k, v in run_cfg.items() if isinstance(v, dict) and v.get("checked")]
    dt = None
    for src in (at.get("loop") or {}, bind.get("_meta") or {}, docs.get("config/dds_cycle.json") or {},
                docs.get("config/robot/zmax_sim2real.json") or {}, docs.get("config/platform/zmax_perf_spec.json") or {}):
        if not isinstance(src, dict):
            continue
        for k, v in src.items():
            if DT_KW.search(str(k)) and isinstance(v, (int, float)) and 0.0001 <= float(v) <= 1.0:
                dt = float(v)
                break
        if dt:
            break
    def _deep_keys(obj, kw, hit=None, _d=0):
        hit = hit if hit is not None else []
        if _d > 4 or len(hit) >= 6:
            return hit
        if isinstance(obj, dict):
            for k, v in obj.items():
                if kw.search(str(k)):
                    hit.append(str(k))
                _deep_keys(v, kw, hit, _d + 1)
        return hit
    _ck = _deep_keys(calib, K_KW)          # 内参 (calib.camera.K 之类)
    _hk = _deep_keys({"T_base_cam": calib.get("T_base_cam"), "control_tcp": calib.get("control_tcp")}, HE_KW) \
        if isinstance(calib, dict) else []
    guide = {
        "M": (calib.get("manifold_engine") or {}).get("M") or calib.get("manifold_M"),
        "inertia": (calib.get("manifold_engine") or {}).get("inertia"),
        "dt": dt,
        "task": {"active": active, "n_tasks": len(tasks), "run_cfg_on": rc_on, "n_run_cfg_on": len(rc_on),
                 "n_enabled_nodes": len(at.get("enabled_nodes") or []), "n_disabled_nodes": len(at.get("disabled_nodes") or []),
                 "recipe_type": at.get("recipe_type"), "scene_ref": at.get("scene_ref")},
        "limits": _find_limits(at),
        "geometry": {"has_K": bool(_ck), "K_keys": _ck[:4],
                     "has_handeye": bool(_hk), "handeye_keys": _hk[:4],
                     "T_base_cam": bool((calib or {}).get("T_base_cam")), "control_tcp": bool((calib or {}).get("control_tcp")),
                     "plane_z": calib.get("plane_z")},
        "mcd": {"file": "config/mcd/param_registry.json", "n_params": (len(reg) if isinstance(reg, list) else None),
                "n_ready": ready},
        "orders": {"n": len(glob.glob(os.path.join(CFG, "orders", "BS_*.json")))},
        "platform": sorted(os.listdir(os.path.join(CFG, "platform"))) if os.path.isdir(os.path.join(CFG, "platform")) else [],
        "robot": sorted(os.listdir(os.path.join(CFG, "robot"))) if os.path.isdir(os.path.join(CFG, "robot")) else [],
    }
    doc = {"_meta": {"note": "配置中心全量装载快照 (主参数M 节点 → 直接指导模型)",
                     "built": time.strftime("%Y-%m-%d %H:%M:%S"), "source": "tools/config_center_load.py build",
                     "root": ROOT},
           "counts": {"files": len(files), "baks": len(baks), "dbs": len(dbs), "failures": len(failures),
                      "yaml": sum(1 for r in loaded.values() if r["ext"] in (".yaml", ".yml")),
                      "json": sum(1 for r in loaded.values() if r["ext"] == ".json")},
           "files": loaded, "baks": [os.path.relpath(p, ROOT) for p in baks], "dbs": db_docs,
           "guide": guide, "failures": failures}
    if write:
        try:
            tmp = OUT + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False, indent=1)
            os.replace(tmp, OUT)
        except Exception as e:                                                 # noqa: BLE001
            print("⚠️ 写 %s 失败: %s" % (OUT, e))
    return doc


def spec(doc):
    """一行摘要 (节点日志用)。"""
    c, g = doc["counts"], doc["guide"]
    return ("配置中心: %d 文件 (json %d / yaml %d) + %d 库 · .bak %d · 失败 %d | 主参数 M=%s · dt=%s · "
            "活跃 %s (档位开 %d · 启用节点 %d) · 限值 %d 项 · 几何 K=%s 手眼=%s plane_z=%s · MCD %s/%s"
            % (c["files"], c["json"], c["yaml"], c["dbs"], c["baks"], c["failures"],
               g["M"], g["dt"], g["task"]["active"], g["task"]["n_run_cfg_on"], g["task"]["n_enabled_nodes"],
               len(g["limits"]), g["geometry"]["has_K"], g["geometry"]["has_handeye"], g["geometry"]["plane_z"],
               g["mcd"]["n_ready"], g["mcd"]["n_params"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="build", choices=["build", "show", "guide", "check"])
    a = ap.parse_args()
    doc = build(write=(a.cmd != "show"))
    if a.cmd == "guide":
        print(json.dumps(doc["guide"], ensure_ascii=False, indent=1)); return 0
    print("  " + spec(doc))
    if a.cmd in ("build", "show"):
        for rel, r in sorted(doc["files"].items()):
            print("   %-46s %7dB md5 %s %s%s" % (rel, r["bytes"], r["md5"],
                  ("%d 条" % r["entries"]) if "entries" in r else "",
                  ("  ⚠️ " + str(r["error"])[:50]) if r.get("error") else ""))
        for p, d in doc["dbs"].items():
            print("   %-46s %d 表 / %d 行 %s" % (p, len(d["tables"]), d["rows_total"], d["err"] or ""))
        if doc["failures"]:
            print("  ⚠️ 解析失败 %d: %s" % (len(doc["failures"]), list(doc["failures"])[:4]))
        print("  快照: %s" % OUT)
    if a.cmd == "check":
        ok = doc["counts"]["failures"] == 0 and doc["counts"]["files"] > 0
        print("  %s check (失败 0 且文件 > 0)" % ("✅" if ok else "❌"))
        return 0 if ok else 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
