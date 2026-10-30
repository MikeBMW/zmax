# -*- coding: utf-8 -*-
"""配置中心 → 状态空间工程「标定诊断测量 · 主参数 M」节点的 **配置文件导入逻辑** (唯一真源)。

老倪 2026-10-12:
> 这个配置中心的配置数据, 要写入状态空间的 标定诊断测量 主参数M 节点,
> 我右键打开这个节点, 要直接定位到, 导入配置文件的位置, 而且要能够运行, 要有能加载配置文件的逻辑

节点用法 (三种入口, 同一个函数):
  · 画布右键「运行节点」/ ⏭单步  → 节点逻辑 register(...) 调 `import_config_files()` + `write_into_node()`
  · 画布右键「打开源码」         → 节点 params.source 指本文件 + params.source_symbol 按符号定位到导入函数
  · 命令行                      → `python src/lerobot/engineering/config_import.py --check|--write|--json`

真源 (只读真源, 不造数; 缺就如实标缺):
  · 总工程文件      data/database/zmax/zmax_space.proj          (tools/gui/project_file.space_path 同源)
  · 工程库          data/database/zmax/zmax_engineering.db      (库内 projects 表 = 工程名/路径)
  · 任务绑定        config/ss_task_binding.json                 (活跃任务/启用禁用/档位)
  · 任务配置        config/tasks/tasks.json                     (5 任务: 工艺步骤/坐标/力)
  · MCD 描述        config/mcd/zmax_mcd.json
  · 参数注册表      config/mcd/param_registry.json              (就绪/缺口)
  · 模型×工程匹配   config/mcd/match_matrix.json
  · 工单            config/orders/BS_*.json                     (Build Sheet ×5)
  · 主参数 M 能量标定 config/calib/zmax_manifold.json            (取 _energy_derivation 段)
  · 性能指标真源    config/platform/zmax_perf_spec.json
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import sqlite3
import sys
import time

_ROOT_DEFAULT = os.path.expanduser("~/zmax")

# ── 真源清单 (name → 相对仓库根路径; #frag 表示只取该子段) ────────────────────
CONFIG_FILES = {
    "总工程文件": "data/database/zmax/zmax_space.proj",
    "任务绑定": "config/ss_task_binding.json",
    "任务配置": "config/tasks/tasks.json",
    "MCD描述": "config/mcd/zmax_mcd.json",
    "参数注册表": "config/mcd/param_registry.json",
    "模型×工程匹配": "config/mcd/match_matrix.json",
    "主参数M能量标定": "config/calib/zmax_manifold.json#_energy_derivation",
    "性能指标真源": "config/platform/zmax_perf_spec.json",
}
DB_REL = "data/database/zmax/zmax_engineering.db"
NODE_ID = "n_calib_mani"
# 画布真源 (2026-10-12 老倪: 工程/工程库/画布都在 data/database/zmax):
#   data/database/zmax/sources/canvas/state_space_obs.json  ← 真源 (src/lerobot/engineering/flows/ 是它的软链)
CANVAS_CANDIDATES = ("data/database/zmax/sources/canvas/state_space_obs.json",
                     "src/lerobot/engineering/flows/state_space_obs.json",
                     "flows/state_space_obs.json")


def canvas_path(root: str | None = None) -> str:
    """画布 JSON 真源: 包内 (软链到 data/database/zmax/sources/canvas) → 旧位置兜底。"""
    R = _root(root)
    for rel in CANVAS_CANDIDATES:
        p = os.path.join(R, rel)
        if os.path.isfile(p):
            return p
    return os.path.join(R, CANVAS_CANDIDATES[-1])


CANVAS_REL = CANVAS_CANDIDATES[0]


def _root(root=None) -> str:
    return os.path.abspath(root or os.environ.get("ZMAX_REPO") or _ROOT_DEFAULT)


def _sha256(p: str) -> str:
    try:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for blk in iter(lambda: f.read(1 << 16), b""):
                h.update(blk)
        return h.hexdigest()
    except Exception:                                                           # noqa: BLE001
        return ""


def _j(p: str, d=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                           # noqa: BLE001
        return d


def _read_db(db: str) -> dict:
    """工程库 (单一真源): 只读 projects 表 + 表清单, 失败如实标错。"""
    out = {"path": db, "exists": os.path.isfile(db), "projects": [], "tables": [], "error": ""}
    if not out["exists"]:
        return out
    try:
        c = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        out["tables"] = [r[0] for r in c.execute("select name from sqlite_master where type='table'")]
        _cols = [r[1] for r in c.execute("pragma table_info(projects)")]
        if "project_id" in _cols:      # 真实列名: project_id/path/saved_at/version/canvas_md5/sha256
            for r in c.execute("select project_id, path, saved_at from projects"):
                out["projects"].append({"file": r[0], "path": r[1], "saved_at": r[2]})
        c.close()
    except Exception as e:                                                      # noqa: BLE001
        out["error"] = repr(e)
    return out


def read_task_cfg(root: str | None = None, orders: list | None = None) -> dict:
    """🧮 **实际任务配置** —— 老倪 2026-10-14: 「我就是要看到记录实际任务配置的那个变量」

    一个变量把"这次到底在按哪个任务干活"看全 (全部现读真源, 不猜不编):
      · 活跃任务绑定 `config/ss_task_binding.json`   → active_task + 该任务全字段 (tasks 是 list)
      · 任务清单     `config/tasks/tasks.json`       → tasks (list, 逐任务: 工序/变体/覆盖参数/判据)
      · 工单         `config/orders/BS_*.json`       → 计数
    返回 {active_task, active_name, recipe_type, scene_ref, site, n_tasks, task_names{id:name},
          steps[活跃任务工序名], tasks[全清单], binding, tasks_doc, orders[], n_orders, src, loaded_at}
    """
    R = _root(root)
    binding = _j(os.path.join(R, "config", "ss_task_binding.json"), {}) or {}
    tasks_doc = _j(os.path.join(R, "config", "tasks", "tasks.json"), {}) or {}
    bt = binding.get("tasks") if isinstance(binding, dict) else None
    tt = tasks_doc.get("tasks") if isinstance(tasks_doc, dict) else None
    b_list = bt if isinstance(bt, list) else []
    t_list = tt if isinstance(tt, list) else []
    names = {}
    for t in t_list:
        if isinstance(t, dict) and t.get("task_id"):
            names[str(t["task_id"])] = str(t.get("name") or "")
    aid = str((binding.get("active_task") if isinstance(binding, dict) else "") or "")
    act = {}
    for t in (b_list + t_list):
        if isinstance(t, dict) and str(t.get("task_id")) == aid:
            act = t
            break
    if orders is None:
        orders = sorted(glob.glob(os.path.join(R, "config/orders/BS_*.json")))
    return {"active_task": aid, "active_name": str(act.get("name") or names.get(aid, "")),
            "recipe_type": str(act.get("recipe_type") or ""), "scene_ref": str(act.get("scene_ref") or ""),
            "site": str(act.get("site") or ""),
            "n_tasks": len(t_list or b_list), "task_names": names,
            "steps": [str(s.get("name") or "") for s in (act.get("steps") or []) if isinstance(s, dict)],
            "tasks": (t_list or b_list), "binding": binding, "tasks_doc": tasks_doc,
            "orders": [os.path.basename(x) for x in orders], "n_orders": len(orders),
            "src": {"binding": "config/ss_task_binding.json", "tasks": "config/tasks/tasks.json",
                    "orders": "config/orders/BS_*.json"},
            "loaded_at": time.strftime("%F %T")}


# 📋 每拍调用 (n_calib_mani 在画布循环里每拍跑): 8 个文件要读+算 sha, 实测 ~85ms/拍,
#   是循环里仅次于 YOLO 的开销。文件没动就没必要重算 ⇒ 按 (路径, mtime, size) 签名 + 2s TTL 缓存。
_IMP_CACHE: dict = {"sig": None, "t": 0.0, "res": None}
_IMP_TTL = 2.0


_DB_CACHE: dict = {}             # {p: 工程库路径, t: 时间, v: 快照} —— sqlite 查询 5s TTL


def _imp_sig(R: str) -> tuple:
    sig = []
    for _n, rel in CONFIG_FILES.items():
        relf = str(rel).partition("#")[0]
        p = os.path.join(R, relf)
        try:
            st = os.stat(p)
            sig.append((relf, st.st_mtime_ns, st.st_size))
        except OSError:
            sig.append((relf, 0, 0))
    try:
        st = os.stat(os.path.join(R, DB_REL))
        # 🕒 工程库被 GUI/工单等进程频繁写, mtime 每次都变 ⇒ 原来每变就整轮重扫 (~80ms 尖峰)。
        #   这里只比大小; 真正的内容查询交给下面 _read_db_cached 的 5s TTL。
        sig.append((DB_REL, st.st_size))
    except OSError:
        sig.append((DB_REL, 0, 0))
    try:
        od = os.path.join(R, "config", "orders")
        sig.append(("orders", len(os.listdir(od)), os.path.getmtime(od)))
    except OSError:
        sig.append(("orders", 0, 0))
    return tuple(sig)


def import_config_files(root: str | None = None, verbose: bool = True) -> dict:
    """📥 **加载配置文件** (节点运行 = 这个函数)。

    返回 {ok, files[], db, summary, missing[], ms}; 不写任何东西 (写盘见 write_into_node)。
    """
    t0 = time.time()
    _R0 = _root(root)
    _sig = _imp_sig(_R0)
    if not verbose and _IMP_CACHE["res"] is not None and _IMP_CACHE["sig"] == _sig \
            and (time.time() - _IMP_CACHE["t"]) < _IMP_TTL:
        _c = dict(_IMP_CACHE["res"])
        _c["ms"] = int((time.time() - t0) * 1000)
        _c["cached"] = True
        return _c
    R = _root(root)
    files, missing = [], []
    for name, rel in CONFIG_FILES.items():
        relf, _, frag = str(rel).partition("#")
        p = os.path.join(R, relf)
        ok = os.path.isfile(p)
        d = _j(p, None) if (ok and relf.endswith(".json")) else (_j(p, None) if ok and relf.endswith((".proj",)) else None)
        n_keys, sec = None, ""
        if ok and d is not None:
            if frag:
                sec = str((d.get(frag) if isinstance(d, dict) else None) is not None)
                d = (d.get(frag) if isinstance(d, dict) else None)
            if isinstance(d, dict):
                n_keys = len(d)
            elif isinstance(d, list):
                n_keys = len(d)
        files.append({"name": name, "rel": relf, "frag": frag, "exists": ok,
                      "bytes": (os.path.getsize(p) if ok else 0),
                      "sha256": (_sha256(p)[:16] if ok else ""), "keys": n_keys,
                      "mtime": (time.strftime("%F %T", time.localtime(os.path.getmtime(p))) if ok else "")})
        if not ok:
            missing.append(relf)
    # 工单 (多文件)
    orders = sorted(glob.glob(os.path.join(R, "config/orders/BS_*.json")))
    # 🧮 **实际任务配置** (老倪 2026-10-14: 「我就是要看到记录实际任务配置的那个变量」):
    #    显式读成一个变量, 且放在**工程库读取(断点那一行)之前** ⇒ 调试停在这行时变量面板里就有它。
    task_cfg = read_task_cfg(R, orders)
    # 工程库 (5s TTL: 上面真源文件照样每拍比签名, 只把 sqlite 查询降频)
    _dbp = os.path.join(R, DB_REL)
    _dnow = time.time()
    if _DB_CACHE.get("p") == _dbp and (_dnow - float(_DB_CACHE.get("t") or 0)) < 5.0:
        db = _DB_CACHE["v"]
    else:
        db = _read_db(_dbp)
        _DB_CACHE.update({"p": _dbp, "t": _dnow, "v": db})

    # ── 摘要 (给节点 cfg_snapshot 用; 每个数都来自上面真源) ──
    bind = task_cfg["binding"]           # 🧮 实际任务配置 (上面已现读, 这里复用, 不重复读盘)
    reg = _j(os.path.join(R, "config/mcd/param_registry.json"), {}) or {}
    mcd = _j(os.path.join(R, "config/mcd/zmax_mcd.json"), {}) or {}
    tasks = task_cfg["tasks_doc"]        # 🧮 同上 (任务清单真源)
    # 参数注册表: `params` 是 list(82); 就绪/缺口在 `summary.ready` / `summary.gaps` (真源字段, 不自算)
    _prm = reg.get("params")
    _total = len(_prm) if isinstance(_prm, (list, dict)) else 0
    _sm = reg.get("summary") or {}
    _ready = int(_sm.get("ready") or 0) if str(_sm.get("ready", "")).strip() != "" else _total
    _gaps = _sm.get("gaps") or []
    _ready = _ready if _ready else max(0, _total - len(_gaps))
    _titems = tasks.get("tasks") or {}
    summary = {
        "files_total": len(files), "files_ok": sum(1 for f in files if f["exists"]),
        "orders": len(orders), "missing": missing,
        "tasks": (len(_titems) if isinstance(_titems, (dict, list)) else 0),
        "active_task": bind.get("active_task") or "",
        "params_total": _total, "params_ready": _ready, "params_gap": (len(_gaps) if _gaps else max(0, _total - _ready)),
        "mcd_schema": mcd.get("schema") or mcd.get("version") or "",
        "project": (db.get("projects") or [{}])[0].get("file") or "",
        "project_path": (db.get("projects") or [{}])[0].get("path") or "",
        "db_ok": bool(db.get("exists")) and not db.get("error"),
        "canvas": os.path.relpath(canvas_path(R), R),
    }
    res = {"ok": (not missing) and summary["db_ok"], "root": R, "files": files, "orders": [os.path.basename(x) for x in orders],
           "db": db, "summary": summary, "missing": missing, "task_cfg": task_cfg,
           "ms": int((time.time() - t0) * 1000)}
    _IMP_CACHE.update({"sig": _sig, "t": time.time(), "res": res})     # 只给"文件没动"的下一拍复用
    if verbose:
        print("📥 导入配置文件 (真源 %d 项 + 工单 %d + 工程库) — 根 %s" % (len(files), len(orders), R))
        for f in files:
            print("   %s %-14s %-46s %s" % ("✅" if f["exists"] else "❌", f["name"], f["rel"],
                                            ("%6d B · %s · 键 %s" % (f["bytes"], f["sha256"], f["keys"])) if f["exists"] else "缺"))
        print("   %s 工程库 %s  工程=%s" % ("✅" if summary["db_ok"] else "❌", DB_REL, summary["project"]))
        print("   参数注册表 %d/%d 就绪 (缺口 %d) · 任务 %d · 活跃 %s · 工单 %d"
              % (_ready, _total, summary["params_gap"], summary["tasks"], summary["active_task"], len(orders)))
        if missing:
            print("   ⚠️ 缺文件: %s" % ", ".join(missing))
        print("   用时 %d ms" % res["ms"])
    return res


def snapshot_for_node(res: dict | None = None, root: str | None = None) -> dict:
    """把导入结果压成节点 cfg_snapshot (与 tools/ss_node_sync.py 同族字段)。"""
    res = res or import_config_files(root, verbose=False)
    s = res["summary"]
    return {"loaded_at": time.strftime("%F %T"), "files_total": s["files_total"], "files_ok": s["files_ok"],
            "orders": s["orders"], "tasks": s["tasks"], "active_task": s["active_task"],
            "params_total": s["params_total"], "params_ready": s["params_ready"], "params_gap": s["params_gap"],
            "mcd_schema": s["mcd_schema"], "project": s["project"], "project_path": s["project_path"],
            "db_ok": s["db_ok"], "missing": s["missing"], "source": "src/lerobot/engineering/config_import.py"}


def write_into_node(node_id: str = NODE_ID, root: str | None = None, dry: bool = False) -> dict:
    """加载配置 → 写进画布节点 params (cfg_entries/cfg_snapshot/cfg_loaded_at/cfg_files)。

    写盘前备份, 写盘后回读校验 (老倪: 「配置数据要写入…节点」)。返回 {ok, node, written, backup, ms}。
    """
    import shutil
    R = _root(root)
    p = canvas_path(R)
    t0 = time.time()
    res = import_config_files(R, verbose=False)
    snap = snapshot_for_node(res, R)
    entries = {f["name"]: (f["rel"] + ("#" + f["frag"] if f["frag"] else "")) for f in res["files"]}
    entries["工单"] = "config/orders/BS_*.json"
    entries["工程库"] = DB_REL
    d = _j(p, None)
    if not isinstance(d, dict) or "nodes" not in d:
        return {"ok": False, "err": "画布读不到: %s" % p}
    node = None
    for n in d["nodes"]:
        pr = n.get("params") or {}
        if n.get("id") == node_id or pr.get("manifold_calib") or "标定诊断测量" in str(n.get("name", "")) \
                or "主参数 M" in str(n.get("name", "")):
            node = n
            break
    if node is None:
        return {"ok": False, "err": "画布上没有节点 %s" % node_id}
    params = node.setdefault("params", {})
    before = {k: json.dumps(params.get(k), ensure_ascii=False, sort_keys=True)
              for k in ("cfg_entries", "cfg_snapshot", "cfg_loaded_at", "cfg_files")}
    params["cfg_entries"] = entries
    params["cfg_snapshot"] = snap
    params["cfg_loaded_at"] = snap["loaded_at"]
    params["cfg_files"] = [{"name": f["name"], "rel": f["rel"], "sha256": f["sha256"], "exists": f["exists"]}
                           for f in res["files"]] + [{"name": "工单", "rel": "config/orders/BS_*.json",
                                                      "sha256": "", "exists": bool(res["orders"])}]
    params["cfg_source"] = "src/lerobot/engineering/config_import.py::import_config_files"
    def _norm(o):
        """去掉时间戳后的可比较形态 (loaded_at / cfg_loaded_at / *_at 都不算内容变化)。"""
        if isinstance(o, dict):
            return {k: _norm(v) for k, v in o.items() if k not in ("loaded_at", "cfg_loaded_at")}
        if isinstance(o, list):
            return [_norm(v) for v in o]
        return o

    _KS = ("cfg_entries", "cfg_snapshot", "cfg_loaded_at", "cfg_files")
    before_n = {k: json.dumps(_norm(json.loads(before[k])), ensure_ascii=False, sort_keys=True)
                for k in _KS}
    after_n = {k: json.dumps(_norm(params.get(k)), ensure_ascii=False, sort_keys=True)
               for k in _KS}
    # 只比"内容": cfg_loaded_at 本身是时间戳, 永远不同 ⇒ 不参与判定
    changed = [k for k in _KS if k != "cfg_loaded_at" and after_n[k] != before_n[k]]
    if dry:
        return {"ok": True, "dry": True, "node": node.get("id"), "would_write": changed, "snapshot": snap,
                "ms": int((time.time() - t0) * 1000)}
    # 🔴 2026-10-31 老倪「怎么一直在这里循环过不去」的真因:
    #   本节点在画布循环里**每拍**跑, 而 cfg_loaded_at 是时间戳 ⇒ changed 永远非空 ⇒ 每拍重写
    #   整个画布 + 拷一份 .bak_cfgimport_* ⇒ mtime 变 ⇒ ss_canvas_loop / 控制台每次都判定
    #   "画布被改" 重新 load_project (重挂配置 + 重载模型) ⇒ 表现为卡在「加载画布」反复刷。
    #   修法: **内容**(除去时间戳)没变就不写盘, 只更新内存里的 loaded_at。
    if not changed:
        _prev = before.get("cfg_loaded_at", '""')
        return {"ok": True, "node": node.get("id"), "written": [], "backup": "",
                "skipped": "配置内容未变 → 不写画布(免每拍重载)", "loaded_at": params["cfg_loaded_at"],
                "snapshot": snap, "ms": int((time.time() - t0) * 1000),
                "same_as": _prev}
    bak = p + ".bak_cfgimport_%s" % time.strftime("%Y%m%d_%H%M%S")
    try:
        shutil.copy2(p, bak)
        tmp = p + ".tmp%d" % os.getpid()
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
    except Exception as e:                                                      # noqa: BLE001
        return {"ok": False, "err": "写画布失败: %r" % (e,)}
    back = _j(p, {}) or {}
    bn = next((n for n in (back.get("nodes") or []) if n.get("id") == node.get("id")), {})
    ok = (bn.get("params") or {}).get("cfg_loaded_at") == params["cfg_loaded_at"]
    return {"ok": bool(ok), "node": node.get("id"), "written": changed, "backup": os.path.basename(bak),
            "loaded_at": params["cfg_loaded_at"], "snapshot": snap, "ms": int((time.time() - t0) * 1000)}


_PRINTED_SIG: list = [None]          # 上一次"完整打印配置块"时的文件签名


def load_config(root: str | None = None) -> dict:
    """节点运行入口 (register 注册的函数体调用它; 名字固定, 供 source_symbol 定位)。

    🔴 2026-10-31 老倪「一直卡在这里」: 本函数在画布循环里**每拍**跑, 原来无条件 verbose=True
    ⇒ 每拍刷 8 行"导入配置文件"+ 1 行写入 ⇒ 10Hz 下每秒 90 行、内容还一模一样, 终端看着就是
    "卡在同一段不往下走"。现在只在**配置文件真的变了**(签名变化)或首次时打全量块, 其余每拍
    只留一行状态 (或者什么都不打, 由循环心跳报节拍)。
    """
    R = _root(root)
    sig = _imp_sig(R)
    changed = (_PRINTED_SIG[0] != sig)
    res = import_config_files(R, verbose=bool(changed))     # 变了才打全量块
    w = write_into_node(root=root)                          # 加载后直接落到节点 (老倪: 配置数据要写入该节点)
    if changed:
        _PRINTED_SIG[0] = sig
        print("   → 写入节点 %s: %s (%s) 用时 %d ms" % (w.get("node"), "✅" if w.get("ok") else "❌",
                                                        ", ".join(w.get("written") or []) or "无变化", w.get("ms", 0)))
    return {"ok": bool(res["ok"]) and bool(w.get("ok")), "import": res["summary"], "write": w}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    root = None
    for i, a in enumerate(argv):
        if a == "--root" and i + 1 < len(argv):
            root = argv[i + 1]
    if "--write" in argv:
        print(json.dumps(write_into_node(root=root), ensure_ascii=False, indent=1))
        return 0
    if "--node" in argv:
        print(json.dumps(load_config(root), ensure_ascii=False, indent=1))
        return 0
    if "--task-cfg" in argv:
        print(json.dumps(read_task_cfg(root), ensure_ascii=False, indent=1))
        return 0
    if "--json" in argv:
        print(json.dumps(import_config_files(root, verbose=False), ensure_ascii=False, indent=1))
        return 0
    res = import_config_files(root, verbose=True)
    print("结果: %s" % ("✅ 全部真源在位" if res["ok"] else "⚠️ 有缺项: %s" % ", ".join(res["missing"])))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
