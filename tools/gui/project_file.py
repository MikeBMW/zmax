#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""状态空间工程存档文件 (.proj; 旧 .zmaxproj 仍可读) —— v2 全量存档 (2026-10-09)

老倪: 「需要保存 状态空间工程的所有配置，包括画布的模型，右侧侧面栏的所有配置，标定，测量，
       以及主参数，都要有相应的文件，你来设计一下工程存档文件」

## 存档格式 (一个自包含 JSON, 拿走一个文件就能在别处复原这次调试)

```
schema        "zmax.statespace.project/2"
① canvas      画布模型: 真源全文 + md5 + 节点/连线数          ← flows.canvas_json() 的真源
② panel       右侧栏所有配置: 当前视图/页签 + 6 个运行开关 + 画布栈索引
③ calibration 标定: config/calib/*.json **全文快照** + 每文件 sha256/mtime + 未标定项 + 现场标定命令
④ master_param 主参数: M / inertia / 范围 / 单位 / 流形含义 + 画布 M 节点 7 段快照 + sha256
⑤ measure     测量: M 节点的 measure_view (9 测量量/源/判据/命令) + 数据总线配置(模式/固定格式映射)
⑥ tasks       任务/工单/绑定 (沿用 v1: config/ss_task_binding.json 全文)
⑦ fingerprints 指纹表 (每个真源文件 sha256+mtime) —— **用来判定"存档与现场是否同源"**
```

## 🔴 真源唯一 (这是本格式的核心设计, 别改成"存档即真相")

* 真源永远是这些文件: 画布 `flows/state_space_obs.json` · 标定 `config/calib/*.json` ·
  任务绑定 `config/ss_task_binding.json`。存档只是**某时刻的快照 + 指纹**。
* `load_project()` **默认只回填画布 + 面板态**; 标定/主参数**一律不覆盖真源**, 只回报"漂移报告"
  (哪一段、哪个键、存档值 vs 现场值)。
* 要真的把标定/主参数按存档恢复, 必须走 `restore_calibration(yes=True)`: 逐文件 --备份→写→**回读
  比对 sha256** -- 这是老倪定的三段纪律; 面板上不提供这个按钮。
* 画布写入永远只经 `flows.save_canvas()`(自带校验 + 自动备份到 flows/_archive/), 本模块绝不自己
  `os.replace` 到软链上。
"""
import hashlib
import json
import os
import shutil
import sys
import time

SCHEMA = "zmax.statespace.project/2"
SCHEMA_V1 = "zmax.statespace.project/1"
COMPAT = (SCHEMA, SCHEMA_V1)
EXT = ".proj"                       # 🗂 2026-10-09 老倪: 工程文件后缀就该是 .proj
LEGACY_EXTS = (".zmaxproj",)        # 老档案照旧能读 (内容识别, 不看后缀)

# 画布页工具栏那 6 个运行档位 (属性名, 界面文字) —— 与 simulink_module.py 逐字对应
RUN_CHECKS = (
    ("chk_engine_demo", "⚡引擎快演"),
    ("chk_l3_full", "🚀 L3 全链(插拔+AOI)"),
    ("chk_mani_yaw", "🧠 流形 yaw 执行"),
    ("chk_intact_exec", "🤖 L4 用 INTACT 节点执行"),
    ("chk_l4_dit", "🎯 L4 意图 → DiT 精炼"),
    ("chk_l2_compat", "🧩 L2 兼容 (前馈 MLP + YOLO)"),
)

# 存档要抓的真源文件 (相对仓库根)
TRUTH_FILES = ("config/calib/zmax_calib.json", "config/calib/zmax_manifold.json",
               "config/ss_task_binding.json", "config/mcd/zmax_mcd.json")


# ══════════════ 基础 ══════════════
def repo_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _flows():
    """延迟导入工程包 (GUI 之外也能用, 例如命令行自检): 先确保 <repo>/src 在 sys.path"""
    import sys
    src = os.path.join(repo_root(), "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    from lerobot.engineering import flows
    return flows


def _ver():
    try:
        from update_checker import CURRENT_VERSION
        return "v%s" % CURRENT_VERSION.lstrip("v")
    except Exception:                                                            # noqa: BLE001
        return "?"


def sha256_file(path):
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for blk in iter(lambda: f.read(1 << 20), b""):
                h.update(blk)
        return h.hexdigest()
    except Exception:                                                            # noqa: BLE001
        return ""


def sha256_json(obj):
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def canvas_md5(d):
    """画布内容指纹 (键序无关, 便于判断"工程里的画布与当前画布是否同一份")"""
    return hashlib.md5(json.dumps(d, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _mtime(path):
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(path)))
    except Exception:                                                            # noqa: BLE001
        return ""


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ══════════════ ① 画布 ══════════════
def canvas_status():
    """当前画布: (数据, 校验问题列表, md5, 统计)"""
    flows = _flows()
    d, probs = flows.load_canvas()
    return d, list(probs or []), canvas_md5(d), flows.stats()


# ══════════════ ② 面板 (右侧栏) ══════════════
def collect_run_cfg(sim):
    """从画布窗口读 6 个档位勾选状态; sim 为 None(画布还没建) 时返回 {}"""
    out = {}
    for attr, label in RUN_CHECKS:
        w = getattr(sim, attr, None) if sim is not None else None
        if w is None:
            continue
        try:
            out[attr] = {"label": label, "checked": bool(w.isChecked())}
        except Exception:                                                        # noqa: BLE001
            pass
    return out


def apply_run_cfg(sim, cfg):
    """把工程文件里的勾选状态写回界面; 返回 (写回项数, 跳过项说明)"""
    done, skip = [], []
    if sim is None or not isinstance(cfg, dict):
        return 0, list(cfg or {}) if isinstance(cfg, dict) else []
    for attr, label in RUN_CHECKS:
        item = cfg.get(attr)
        if not isinstance(item, dict):
            continue
        w = getattr(sim, attr, None)
        if w is None:
            skip.append("%s(界面里没有这个勾选框)" % label)
            continue
        try:
            w.setChecked(bool(item.get("checked")))
            done.append(label)
        except Exception as e:                                                   # noqa: BLE001
            skip.append("%s(%s)" % (label, e))
    return len(done), skip


def collect_panel(sim=None, page=None):
    """右侧侧边栏的所有配置: 视图/页签 + 6 运行开关 + 画布栈索引"""
    out = {"run_switches": collect_run_cfg(sim), "canvas_stack_index": page}
    dock = getattr(sim, "model_tree", None) if sim is not None else None
    if dock is not None:
        try:
            idx = dock.cmb_view.currentIndex()
            keys = list(getattr(dock, "VIEW_KEYS", ()))
            out["view_index"] = idx
            out["view"] = keys[idx] if 0 <= idx < len(keys) else None
            out["view_label"] = dock.cmb_view.currentText()
        except Exception:                                                        # noqa: BLE001
            pass
        hub = getattr(dock, "measure", None)
        if hub is not None and hasattr(hub, "_cur_key"):
            try:
                out["measure_tab"] = hub._cur_key()
            except Exception:                                                    # noqa: BLE001
                pass
    out["available_views"] = ["mparam", "bus", "calib", "run_cfg"]
    if sim is None:
        out["note"] = ("控制台没打开 (命令行存档): 运行开关/当前视图没读到 —— "
                       "在控制台里用「文件 → 💾 保存工程文件」存, 这三项会自动带上")
    return out


# ══════════════ ③ 标定 ══════════════
def collect_calibration(with_content=True):
    """config/calib/*.json 全量快照 + 指纹 + 未标定项 + 现场标定命令"""
    root = repo_root()
    files, uncal, miss = {}, [], []
    for p in ("config/calib/zmax_calib.json", "config/calib/zmax_manifold.json"):
        ap = os.path.join(root, p)
        if not os.path.exists(ap):
            miss.append(p)
            continue
        item = {"sha256": sha256_file(ap), "mtime": _mtime(ap), "bytes": os.path.getsize(ap)}
        if with_content:
            try:
                item["content"] = _load_json(ap)
            except Exception as e:                                               # noqa: BLE001
                item["error"] = "%s: %s" % (type(e).__name__, e)
        files[p] = item
        if p.endswith("zmax_calib.json") and with_content and isinstance(item.get("content"), dict):
            for k, v in item["content"].items():
                if k.startswith("_") or not isinstance(v, dict):
                    continue
                if v.get("value", v.get("points", v)) is None:
                    uncal.append(k)
    return {"files": files, "missing": miss, "uncalibrated": uncal, "fix_cmds": fix_cmds()}


def fix_cmds():
    """未标定项的现场标定命令 (从面板类取, 取不到就用内置兜底)"""
    try:
        import model_tree as _mt
        return dict(getattr(_mt.CalibTruthView, "FIX", {}) or {})
    except Exception:                                                            # noqa: BLE001
        return {"cell_geometry": "gui-venv311/bin/python tools/ss_geom_calib.py --record peg_head|goal|aoi",
                "T_base_cam": "gui-venv311/bin/python tools/board_handeye_solve.py",
                "plane_z": "# 现场用夹爪或塞尺量一次台面高度 → 写 config/calib/zmax_calib.json 的 plane_z.value"}


# ══════════════ ④ 主参数 M ══════════════
def find_m_node(canvas=None):
    """画布上的「🧮 标定诊断测量 · 主参数 M」节点 (id 会因另存为重编, 故名字/语义兜底)"""
    if canvas is None:
        canvas, _ = _flows().load_canvas()
    for n in (canvas or {}).get("nodes", []) or []:
        p = n.get("params", {}) or {}
        if n.get("id") == "n_calib_mani" or p.get("manifold_calib") is True:
            return n
    for n in (canvas or {}).get("nodes", []) or []:
        if "主参数" in (n.get("name") or ""):
            return n
    return None


def collect_master_param(canvas=None):
    root = repo_root()
    node = find_m_node(canvas)
    p = (node or {}).get("params", {}) or {}
    mp = os.path.join(root, "config/calib/zmax_manifold.json")
    raw = _load_json(mp) if os.path.exists(mp) else {}
    return {
        "M": raw.get("M", p.get("M")),
        "inertia": raw.get("inertia", p.get("inertia")),
        "range": raw.get("_range", p.get("M_range")),
        "unit": raw.get("_unit", p.get("M_unit")),
        "flow": raw.get("_flow", p.get("M_info")),
        "struct_src": raw.get("_src", ""),
        "zero_regression": raw.get("zero_regression", p.get("zero_regression")),
        "sha256": sha256_file(mp),
        "node": {"id": (node or {}).get("id"), "name": (node or {}).get("name"),
                 "params": {k: v for k, v in p.items()
                            if k in ("cfg_role", "cfg_entries", "cfg_snapshot", "measure_view",
                                     "calib_view", "diagnose_view", "task_layer",
                                     "M", "M_range", "inertia", "manifold_calib")}} if node else None,
    }


# ══════════════ ⑤ 测量 ══════════════
def collect_measure(canvas=None, sim=None):
    node = find_m_node(canvas)
    p = (node or {}).get("params", {}) or {}
    out = {"measure_view": p.get("measure_view") or {},
           "diagnose_view": p.get("diagnose_view") or {},
           "source": "画布 M 节点 (由 tools/ss_node_sync.py 从真源同步)"}
    bus = getattr(getattr(sim, "model_tree", None), "bus", None) if sim is not None else None
    if bus is not None:
        try:
            out["bus"] = {"mode": bus.cmb_mode.currentText(),
                          "mode_index": bus.cmb_mode.currentIndex(),
                          "fixed_map": {("%s|%s|%s" % k if isinstance(k, tuple) else str(k)): v
                                        for k, v in (getattr(bus, "_fix_map", {}) or {}).items()},
                          "rows": bus.table.rowCount()}
        except Exception:                                                        # noqa: BLE001
            pass
    else:
        out["bus"] = {"mode": "(控制台未打开, 只存默认)", "mode_index": 0, "fixed_map": {}, "rows": 0}
    return out


# ══════════════ ⑥ 任务 ══════════════
def collect_tasks():
    ap = os.path.join(repo_root(), "config/ss_task_binding.json")
    try:
        return {"file": "config/ss_task_binding.json", "sha256": sha256_file(ap),
                "content": _load_json(ap)}
    except Exception:                                                            # noqa: BLE001
        return {}


# ══════════════ ⑦ 指纹表 ══════════════
def collect_fingerprints():
    root = repo_root()
    fp = {}
    for p in TRUTH_FILES + ("src/lerobot/engineering/flows/state_space_obs.json",):
        ap = os.path.join(root, p)
        if os.path.exists(ap):
            fp[p] = {"sha256": sha256_file(ap), "mtime": _mtime(ap), "bytes": os.path.getsize(ap)}
    return fp


# ══════════════ 存 / 读 ══════════════
def save_project(path, sim=None, page=None, note="", with_calib=True):
    """把"现在的状态空间工程"存成一个自包含工程文件 (v2 全量)。返回摘要 dict。"""
    flows = _flows()
    d, probs, md5, stats = canvas_status()
    if probs:
        raise ValueError("当前画布有 %d 处问题, 先修好再存 (前 3 条): %s" % (len(probs), probs[:3]))
    proj = {
        "schema": SCHEMA,
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "saved_by": "Z-MAX 控制台 · 文件 → 💾 保存工程文件",
        "zmax_version": _ver(),
        "note": note or "",
        "host": os.uname().nodename if hasattr(os, "uname") else "",
        "canvas_source": flows.canvas_path(),
        "canvas_fingerprint": {"md5": md5, "stats": stats},
        "canvas": d,                                                    # ①
        "panel": collect_panel(sim, page),                               # ②
        "calibration": collect_calibration(with_content=with_calib),     # ③
        "master_param": collect_master_param(d),                         # ④
        "measure": collect_measure(d, sim),                              # ⑤
        "tasks": collect_tasks(),                                        # ⑥
        "fingerprints": collect_fingerprints(),                          # ⑦
    }
    proj["run_cfg"] = proj["panel"]["run_switches"]      # v1 兼容键
    proj["ui"] = {"canvas_stack_index": page}            # v1 兼容键
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(proj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, str(path))                      # path 是用户选的普通文件(不是软链), 安全
    return {"path": os.path.abspath(str(path)), "md5": md5, "stats": stats,
            "run_cfg": proj["run_cfg"], "bytes": os.path.getsize(str(path)),
            "version": proj["zmax_version"], "saved_at": proj["saved_at"],
            "schema": SCHEMA,
            "sections": {"canvas": "%s 节点/%s 连线" % (stats.get("nodes"), stats.get("links")),
                         "panel": "%d 开关 · 视图 %s" % (len(proj["panel"]["run_switches"]),
                                                         proj["panel"].get("view")),
                         "calibration": "%d 文件 · 未标定 %d" % (len(proj["calibration"]["files"]),
                                                                 len(proj["calibration"]["uncalibrated"])),
                         "master_param": "M=%s inertia=%s" % (proj["master_param"]["M"],
                                                              proj["master_param"]["inertia"]),
                         "measure": "%d 项测量量" % len((proj["measure"]["measure_view"] or {}).get("源") or []),
                         "tasks": "%d 任务" % len(((proj["tasks"].get("content") or {}).get("tasks") or {})),
                         "fingerprints": "%d 个真源文件" % len(proj["fingerprints"])}}


def _read(path):
    with open(str(path), encoding="utf-8") as f:
        proj = json.load(f)
    if not isinstance(proj, dict) or proj.get("schema") not in COMPAT:
        raise ValueError("不是 Z-MAX 工程文件 (schema=%s)"
                         % (proj.get("schema") if isinstance(proj, dict) else type(proj).__name__))
    return proj


def read_summary(path):
    """只读工程文件摘要 (加载前给用户看"这文件里是什么"), v1/v2 都收"""
    proj = _read(path)
    d = proj.get("canvas")
    cal = proj.get("calibration") or {}
    mp = proj.get("master_param") or {}
    return {"schema": proj.get("schema"), "kind": proj.get("kind"), "name": proj.get("name"),
            "integrated": proj.get("integrated"),
            "saved_at": proj.get("saved_at"), "note": proj.get("note"),
            "version": proj.get("zmax_version"), "canvas_source": proj.get("canvas_source"),
            "fingerprint": proj.get("canvas_fingerprint") or {},
            "canvas_ok": isinstance(d, dict) and bool(d),
            "run_cfg": proj.get("panel", {}).get("run_switches") or proj.get("run_cfg") or {},
            "ui": proj.get("ui") or {},
            "panel": proj.get("panel") or {},
            "calibration": {"files": sorted((cal.get("files") or {}).keys()),
                            "uncalibrated": cal.get("uncalibrated") or [],
                            "missing": cal.get("missing") or []},
            "master_param": {k: mp.get(k) for k in ("M", "inertia", "range", "unit")},
            "measure": proj.get("measure") or {},
            "tasks": {"active": ((proj.get("tasks", {}).get("content") or {}).get("active_task")
                                 or ((proj.get("tasks", {}).get("content") or {}).get("active"))),
                      "n": len(((proj.get("tasks", {}).get("content") or {}).get("tasks") or {}))}}


# ══════════════ 漂移报告 (核心: 存档 vs 现场) ══════════════
VOLATILE_KEYS = ("_meta", "generated_at", "updated_at", "saved_at", "_generated_at")
# 画布节点上"由工具从真源同步进来的配置快照"字段 (含 canvas_md5 等派生值, 会随写盘次数漂)
CFG_SNAPSHOT_KEYS = ("cfg_role", "cfg_entries", "cfg_snapshot", "measure_view", "calib_view",
                     "diagnose_view", "task_layer")


def _strip_cfg(node):
    """节点去配置快照字段后的**结构+参数**表示 (用于画布漂移判定: 只看真结构/真参数)"""
    nn = dict(node)
    pr = dict(nn.get("params") or {})
    for k in CFG_SNAPSHOT_KEYS:
        pr.pop(k, None)
    nn["params"] = pr
    return json.dumps(nn, sort_keys=True, ensure_ascii=False)


def _semantic(obj):
    """做漂移比对前先剥掉"每次写都会变"的时间戳/元信息 (值没变就不该报漂移)"""
    if isinstance(obj, dict):
        return {k: _semantic(v) for k, v in obj.items() if k not in VOLATILE_KEYS}
    if isinstance(obj, list):
        return [_semantic(x) for x in obj]
    return obj


def drift_report(proj):
    """逐段比对"存档里的"与"现在现场的"。返回 {段: {"status", "detail": [...]}}。

    只读不写 —— 用它回答"这个存档跟现场还对得上吗? 哪一段漂了?"
    """
    if not isinstance(proj, dict):
        proj = _read(proj)
    out = {}

    # ① 画布
    try:
        cur, probs, md5, stats = canvas_status()
        saved = proj.get("canvas") or {}
        smd5 = canvas_md5(saved) if saved else ""
        det = []
        if smd5 != md5:
            sn = {n.get("id"): n for n in saved.get("nodes", []) or []}
            cn = {n.get("id"): n for n in cur.get("nodes", []) or []}
            added, gone = [k for k in cn if k not in sn], [k for k in sn if k not in cn]
            # 比结构/参数时**剔除 M 节点那类「配置快照派生字段」** (cfg_*/…_view/task_layer):
            # 它们由工具从真源同步进来, 含 canvas_md5 等派生值, 会随写盘次数漂 —— 不算画布结构漂移。
            changed = [k for k in cn if k in sn and _strip_cfg(sn[k]) != _strip_cfg(cn[k])]
            snap_only = [k for k in cn if k in sn and _strip_cfg(sn[k]) == _strip_cfg(cn[k])
                         and json.dumps(sn[k], sort_keys=True, ensure_ascii=False)
                         != json.dumps(cn[k], sort_keys=True, ensure_ascii=False)]
            det.append("节点 %s→%s · 新增 %d / 删除 %d / 改动 %d" % (
                (proj.get("canvas_fingerprint") or {}).get("stats", {}).get("nodes"),
                stats.get("nodes"), len(added), len(gone), len(changed)))
            if added:
                det.append("新增: %s" % [cn[k].get("name") for k in added[:5]])
            if gone:
                det.append("删除: %s" % [sn[k].get("name") for k in gone[:5]])
            if changed:
                det.append("改动: %s" % [cn[k].get("name") for k in changed[:5]])
            if snap_only:
                det.append("仅配置快照派生字段变(不算结构漂移): %s"
                           % [cn[k].get("name") for k in snap_only[:3]])
        out["canvas"] = {"status": "一致" if (smd5 == md5 or not changed) else "漂移",
                         "detail": det or ["md5 与现场相同"]}
    except Exception as e:                                                       # noqa: BLE001
        out["canvas"] = {"status": "无法比对", "detail": ["%s: %s" % (type(e).__name__, e)]}

    # ③ 标定 (逐文件 sha256)
    det, bad = [], 0
    for p, item in ((proj.get("calibration") or {}).get("files") or {}).items():
        ap = os.path.join(repo_root(), p)
        cur_h = sha256_file(ap) if os.path.exists(ap) else ""
        if not cur_h:
            det.append("%s: 现场没有这个文件" % p)
            bad += 1
        elif cur_h != item.get("sha256"):
            det.append("%s: 漂移 (%s → %s)" % (os.path.basename(p), (item.get("sha256") or "")[:12],
                                              cur_h[:12]))
            bad += 1
        else:
            det.append("%s: 一致" % os.path.basename(p))
    out["calibration"] = {"status": ("一致" if det and not bad else ("漂移" if bad else "无数据")),
                          "detail": det or ["存档里没有标定段 (v1 老文件)"]}

    # ④ 主参数
    mp = proj.get("master_param") or {}
    try:
        cur_mp = collect_master_param()
        det = []
        for k in ("M", "inertia"):
            if mp.get(k) != cur_mp.get(k):
                det.append("%s: 存档 %s → 现场 %s" % (k, mp.get(k), cur_mp.get(k)))
        if mp.get("sha256") != cur_mp.get("sha256"):
            det.append("zmax_manifold.json sha256 不同 (%s → %s)"
                       % ((mp.get("sha256") or "")[:12], (cur_mp.get("sha256") or "")[:12]))
        out["master_param"] = {"status": "一致" if not det else "漂移", "detail": det or ["M/inertia 与现场相同"]}
    except Exception as e:                                                       # noqa: BLE001
        out["master_param"] = {"status": "无法比对", "detail": ["%s: %s" % (type(e).__name__, e)]}

    # ⑤ 测量 (与画布 M 节点快照比)
    try:
        node = find_m_node()
        cur_mv = ((node or {}).get("params", {}) or {}).get("measure_view") or {}
        s_mv = (proj.get("measure") or {}).get("measure_view") or {}
        same = sha256_json(s_mv) == sha256_json(cur_mv)
        out["measure"] = {"status": "一致" if same else ("漂移" if s_mv else "无数据"),
                          "detail": ["measure_view 与画布 M 节点相同" if same
                                     else "measure_view 不同 (存档 %d 源 → 现场 %d 源)"
                                     % (len(s_mv.get("源") or []), len(cur_mv.get("源") or []))]}
    except Exception as e:                                                       # noqa: BLE001
        out["measure"] = {"status": "无法比对", "detail": ["%s: %s" % (type(e).__name__, e)]}

    # ⑥ 任务 (语义比对: 忽略 _meta/generated_at 这类每次写都会变的时间戳)
    try:
        cur_t = collect_tasks().get("content") or {}
        s_t = (proj.get("tasks") or {}).get("content") or {}
        same = sha256_json(_semantic(s_t)) == sha256_json(_semantic(cur_t))
        det = ["任务绑定相同 (已忽略 _meta/generated_at 时间戳)" if same else
               "任务绑定不同 (存档活跃 %s → 现场 %s)"
               % (s_t.get("active_task") or s_t.get("active"),
                  cur_t.get("active_task") or cur_t.get("active"))]
        if not same:
            sid = {t.get("id") for t in (s_t.get("tasks") or []) if isinstance(t, dict)}
            cid = {t.get("id") for t in (cur_t.get("tasks") or []) if isinstance(t, dict)}
            if sid != cid:
                det.append("任务清单不同: 存档 %d 个 / 现场 %d 个" % (len(sid), len(cid)))
        out["tasks"] = {"status": "一致" if same else ("漂移" if s_t else "无数据"), "detail": det}
    except Exception as e:                                                       # noqa: BLE001
        out["tasks"] = {"status": "无法比对", "detail": ["%s: %s" % (type(e).__name__, e)]}

    # ⑦ 面板 (需要控制台窗口; 没窗口就只能报"存档里的值")
    pn = proj.get("panel") or proj.get("run_cfg") or {}
    rs = pn.get("run_switches") or {}
    out["panel"] = {"status": "存档值 (比对需控制台打开)",
                    "detail": ["视图 %s · 开关勾选 %s" % (pn.get("view") or pn.get("view_label") or "?",
                                                      [v.get("label") for v in rs.values()
                                                       if isinstance(v, dict) and v.get("checked")])]}
    return out


def drift_lines(rep):
    """漂移报告 → 可读文本行 (界面/CLI 共用)"""
    lines = []
    for sec, item in (rep or {}).items():
        mark = {"一致": "✅", "漂移": "⚠️"}.get(item.get("status"), "◻︎")
        lines.append("%s %s: %s" % (mark, sec, item.get("status")))
        for d in item.get("detail") or []:
            lines.append("     · %s" % d)
    return lines


# ══════════════ 加载 (默认只回填画布 + 面板) ══════════════
def load_project(path, with_calib=False, yes=False):
    """把工程文件写回: **默认只写画布**(自动备份) —— 标定/主参数只比对不覆盖。

    要按存档恢复标定/主参数: `with_calib=True, yes=True` (逐文件备份→写→回读 sha256)。
    返回摘要 + drift 报告 + 需要写回界面的东西。
    """
    flows = _flows()
    proj = _read(path)
    d = proj.get("canvas")
    if not isinstance(d, dict) or not d:
        raise ValueError("工程文件里没有画布数据 (canvas 段是空的)")
    probs = list(flows.validate_canvas(d) or [])
    if probs:
        raise ValueError("工程文件里的画布校验不过, 拒绝写盘 (前 3 条): %s" % probs[:3])
    rep = drift_report(proj)                       # 写盘前先算漂移 (画布还没被替换)
    _, _, cur_md5, _ = canvas_status()
    new_md5 = canvas_md5(d)
    p, bak = flows.save_canvas(d, reason="project_load")     # 唯一写盘点: 校验 + 备份 + 原子替换
    out = {"path": os.path.abspath(str(path)), "written": p, "backup": bak,
           "same_as_before": new_md5 == cur_md5, "md5": new_md5, "schema": proj.get("schema"),
           "stats": flows.stats(), "run_cfg": (proj.get("panel") or {}).get("run_switches")
           or proj.get("run_cfg") or {},
           "ui": proj.get("ui") or {}, "panel": proj.get("panel") or {},
           "saved_at": proj.get("saved_at"), "version": proj.get("zmax_version"),
           "note": proj.get("note"), "drift": rep, "drift_lines": drift_lines(rep),
           "calib_restored": None}
    if with_calib:
        out["calib_restored"] = restore_calibration(proj, yes=yes)
    return out


def restore_calibration(proj, yes=False):
    """按存档恢复标定 + 主参数: 逐文件 --备份→写→回读 sha256 -- (三段纪律)。

    必须 yes=True 才动手; 返回 {"files": {path: {"backup", "sha256_before", "sha256_after", "ok"}}}。
    """
    if not yes:
        return {"skipped": "未确认 (需要 yes=True): 标定/主参数属现场标定资产, 默认不覆盖"}
    root = repo_root()
    res = {}
    for p, item in ((proj.get("calibration") or {}).get("files") or {}).items():
        content = item.get("content")
        if content is None:
            res[p] = {"ok": False, "why": "存档里没带全文 (存档时 with_calib=False)"}
            continue
        ap = os.path.join(root, p)
        os.makedirs(os.path.dirname(ap), exist_ok=True)
        before = sha256_file(ap)
        bak = ""
        if os.path.exists(ap):
            bak = "%s.bak_%s" % (ap, time.strftime("%Y%m%d_%H%M%S"))
            shutil.copy2(ap, bak)
        tmp = ap + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(content, f, ensure_ascii=False, indent=1)
        os.replace(tmp, ap)                        # 只写这个目标文件, 不整表 sync
        after = sha256_file(ap)
        res[p] = {"ok": after == item.get("sha256"), "backup": bak,
                  "sha256_before": before[:12], "sha256_after": after[:12],
                  "archive_sha256": (item.get("sha256") or "")[:12]}
    return {"files": res, "all_ok": all(v.get("ok") for v in res.values()) if res else False}


# ══════════════ v1 → v2 升级 (老存档不用重存也能看新段) ══════════════
def upgrade_v1(path, out=None):
    """把 v1 老工程文件就地/另存升级为 v2 (补 panel/calibration/master_param/measure/tasks/指纹)。"""
    proj = _read(path)
    if proj.get("schema") == SCHEMA:
        return {"upgraded": False, "why": "已经是 v2"}
    d = proj.get("canvas") or {}
    proj["schema"] = SCHEMA
    proj["upgraded_from"] = SCHEMA_V1
    proj["upgraded_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    proj.setdefault("panel", {})["run_switches"] = proj.get("run_cfg") or {}
    proj["panel"]["canvas_stack_index"] = (proj.get("ui") or {}).get("canvas_stack_index")
    proj["panel"]["available_views"] = ["mparam", "bus", "calib", "run_cfg"]
    proj["calibration"] = collect_calibration(with_content=True)
    proj["master_param"] = collect_master_param(d)
    proj["measure"] = collect_measure(d)
    proj["tasks"] = collect_tasks()
    proj["fingerprints"] = collect_fingerprints()
    target = out or path
    tmp = str(target) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(proj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, str(target))
    return {"upgraded": True, "path": os.path.abspath(str(target)),
            "note": "标定/主参数/测量段是按**当前现场**补的 (老存档里本来没有), 画布与面板保持原样"}


def project_dir(root=None):
    """工程文件默认目录: <仓库根>/data/database/zmax (标准产品数据路径: data/database/<产品>/)"""
    root = root or os.path.expanduser("~/zmax")
    d = os.path.join(root, "data", "database", "zmax")
    os.makedirs(d, exist_ok=True)
    return d


# ══════════════ 🗂 总工程 (zmax_space) —— 一个文件承载整个状态空间工程 ══════════════
# 老倪 (2026-10-09): 「增加新功能, 每次打开工程, 要从工程文件打开… 你来定义一个 zmax_space 工程,
#   将所有状态空间工程文件、标定、配置、主参数等, 都整合进这个总工程文件, 通过主窗口的
#   文件 → 打开/加载工程 的方式, 集成式打开; 不像现在, 还得手动加载, 太散乱了。」
#
# 设计: 总工程 = 同一个 .proj 格式 + kind="zmax_space" 标记。区别只在**打开时的语义**:
#   · 普通存档 (snapshot): 默认只回填画布+面板, 标定/主参数只核对不覆盖 (安全)
#   · 总工程 (zmax_space): **集成式打开** —— 画布/标定/主参数/任务/面板一次全回填,
#     每一步都先备份再写再回读 (三段纪律), 并给一页"恢复了什么"的报告。
KIND_SPACE = "zmax_space"
KIND_SNAPSHOT = "snapshot"
SPACE_NAME = "zmax_space.proj"
INTEGRATED_SECTIONS = ("canvas", "calibration", "master_param", "tasks", "panel")


def space_path_legacy(root=None):
    """旧的 .zmaxproj 总工程 (没迁名时兜底找到它)"""
    root = root or os.path.expanduser("~/zmax")
    return os.path.join(project_dir(root), "zmax_space.zmaxproj")


def find_space(root=None):
    """总工程文件: 优先新后缀 .proj, 退回旧 .zmaxproj, 都没有则返回新路径 (供保存用)"""
    n = space_path(root)
    if os.path.exists(n):
        return n
    o = space_path_legacy(root)
    return o if os.path.exists(o) else n


def space_path(root=None):
    """总工程文件路径 (默认 data/database/zmax/zmax_space.proj, 稳定不变)"""
    return os.path.join(project_dir(root), SPACE_NAME)


def is_space(proj):
    """这个工程文件是不是"总工程" (集成式)"""
    if not isinstance(proj, dict):
        try:
            proj = _read(proj)
        except Exception:                                                        # noqa: BLE001
            return False
    return proj.get("kind") == KIND_SPACE


def save_space(path=None, sim=None, page=None, note=""):
    """把当前整个状态空间工程存成**总工程** (集成式: 7 段 + kind 标记)。"""
    path = path or space_path()
    r = save_project(path, sim=sim, page=page, note=note, with_calib=True)
    proj = _read(path)
    proj["kind"] = KIND_SPACE
    proj["integrated"] = list(INTEGRATED_SECTIONS)
    proj["name"] = "Z-MAX 状态空间总工程"
    proj["saved_by"] = "Z-MAX 控制台 · 文件 → 🗂 保存总工程 (zmax_space)"
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(proj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, str(path))
    r["space"] = True
    r["path"] = os.path.abspath(str(path))
    r["bytes"] = os.path.getsize(str(path))
    return r


def _apply_tasks(proj, sim=None, force=False):
    """集成式打开: 把总工程里的"活跃任务"写回绑定真源 (走 tools/ss_task_bind.py --activate)。
    force=True 时**即使活跃任务没变也重写一遍** —— 绑定真源里带 `project.canvas_md5`,
    画布刚被回填后必须重绑, 否则文件里记的还是打开前的画布 md5 (diff 会报 tasks 漂移)。"""
    tk = ((proj.get("tasks") or {}).get("content") or {})
    want = tk.get("active_task") or tk.get("active")
    if not want:
        return {"ok": True, "why": "存档里没有活跃任务, 跳过"}
    cur_file = os.path.join(repo_root(), "config/ss_task_binding.json")
    try:
        cur = (_load_json(cur_file).get("active_task")) if os.path.exists(cur_file) else None
    except Exception:                                                            # noqa: BLE001
        cur = None
    if cur == want and not force:
        return {"ok": True, "why": "活跃任务已是 %s, 无需改" % want, "active_task": want}
    tool = os.path.join(repo_root(), "tools", "ss_task_bind.py")
    if not os.path.exists(tool):
        return {"ok": False, "why": "找不到 tools/ss_task_bind.py"}
    import subprocess
    try:
        r = subprocess.run([sys.executable, tool, "--activate", str(want)], capture_output=True,
                           text=True, timeout=180, cwd=repo_root())
        back = ""
        try:
            back = _load_json(cur_file).get("active_task") or ""
        except Exception:                                                        # noqa: BLE001
            pass
        return {"ok": back == want, "why": (r.stdout or "").strip().splitlines()[-1:] or "",
                "active_task": back, "from": cur}
    except Exception as e:                                                       # noqa: BLE001
        return {"ok": False, "why": "%s: %s" % (type(e).__name__, e)}


def integrated_apply(proj, sim=None, page=None, yes=False):
    """**集成式打开**: 画布 + 标定 + 主参数 + 任务 + 面板, 一次全回填 (每步先备份再写再回读)。

    返回 {"ok", "steps": [...], "canvas": {...}, "panel": {...}, "lines": [...]} —— 给界面一页报告。
    """
    if not yes:
        return {"ok": False, "skipped": "集成式打开需要确认 (yes=True)",
                "steps": [], "lines": ["◻︎ 未确认: 集成式打开会回填画布/标定/主参数/任务"]}
    if not isinstance(proj, dict):
        proj = _read(proj)
    steps, lines = [], []

    # ① 标定 + 主参数 (先内容后画布: 画布里的 M 节点快照与标定同源)
    cr = restore_calibration(proj, yes=True)
    for p, v in (cr.get("files") or {}).items():
        steps.append({"what": "calibration:%s" % os.path.basename(p), "ok": bool(v.get("ok")),
                      "detail": "%s → %s (存档 %s) 备份 %s" % (v.get("sha256_before"),
                                                            v.get("sha256_after"),
                                                            v.get("archive_sha256"),
                                                            os.path.basename(v.get("backup") or "-"))})
        lines.append("%s 标定 %s: %s" % ("✅" if v.get("ok") else "❌", os.path.basename(p),
                                         steps[-1]["detail"]))
    mp = proj.get("master_param") or {}
    try:
        now = collect_master_param()
        ok = (now.get("M") == mp.get("M")) and (now.get("inertia") == mp.get("inertia"))
        steps.append({"what": "master_param", "ok": ok,
                      "detail": "M=%s inertia=%s (回读确认)" % (now.get("M"), now.get("inertia"))})
        lines.append("%s 主参数: M=%s inertia=%s 回读%s" % ("✅" if ok else "❌", now.get("M"),
                                                         now.get("inertia"),
                                                         "一致" if ok else "不一致"))
    except Exception as e:                                                       # noqa: BLE001
        steps.append({"what": "master_param", "ok": False, "detail": str(e)})
        lines.append("❌ 主参数回读失败: %s" % e)

    # ② 任务 (活跃任务 → 绑定真源)
    tr = _apply_tasks(proj, sim)
    steps.append({"what": "tasks", "ok": bool(tr.get("ok")), "detail": str(tr.get("why"))})
    lines.append("%s 任务: %s" % ("✅" if tr.get("ok") else "❌", tr.get("why")))

    # ③ 画布 (唯一写盘点: flows.save_canvas 自带校验 + 备份)
    cv = _write_canvas(proj, sim=sim, page=page)
    steps.append({"what": "canvas", "ok": bool(cv.get("written")), "detail": json.dumps(
        cv.get("stats") or {}, ensure_ascii=False)})
    lines.append("%s 画布: %s (备份 %s)" % ("✅" if cv.get("written") else "❌",
                                          json.dumps(cv.get("stats") or {}, ensure_ascii=False),
                                          os.path.basename(cv.get("backup") or "-")))

    # ③b 任务重绑定 (必须在画布落地之后): 绑定真源里带 `project.canvas_md5`,
    #     若只在画布前绑定, 文件里记的是"打开前那块画布"的 md5 ⇒ 总工程 diff 报 tasks 漂移 (2026-10-09 判据集实测)。
    if cv.get("written"):
        tr2 = _apply_tasks(proj, sim, force=True)
        for s in steps:
            if s.get("what") == "tasks":
                s["ok"], s["detail"] = bool(tr2.get("ok")), str(tr2.get("why"))
        if not tr2.get("ok"):
            lines.append("❌ 任务重绑定(对齐新画布): %s" % tr2.get("why"))

    # ④ 面板 (界面态: 由调用方 apply_run_cfg + 切视图)
    pn = proj.get("panel") or {}
    steps.append({"what": "panel", "ok": True,
                  "detail": "视图 %s · %d 个开关" % (pn.get("view"), len(pn.get("run_switches") or {}))})
    lines.append("✅ 面板: 视图 %s · 运行开关 %d 项 (界面侧回填)"
                 % (pn.get("view") or pn.get("view_label"), len(pn.get("run_switches") or {})))
    return {"ok": all(s["ok"] for s in steps), "steps": steps, "lines": lines,
            "canvas": cv, "panel": pn, "run_cfg": pn.get("run_switches") or {},
            "ui": proj.get("ui") or {}, "saved_at": proj.get("saved_at"),
            "version": proj.get("zmax_version"), "note": proj.get("note"),
            "calib_restored": cr}


def _write_canvas(proj, sim=None, page=None):
    """只写画布真源 (校验 + 备份), 返回 load_project 同款摘要 (不做标定)"""
    flows = _flows()
    d = proj.get("canvas")
    if not isinstance(d, dict) or not d:
        raise ValueError("工程文件里没有画布数据 (canvas 段是空的)")
    probs = list(flows.validate_canvas(d) or [])
    if probs:
        raise ValueError("工程文件里的画布校验不过, 拒绝写盘 (前 3 条): %s" % probs[:3])
    _, _, cur_md5, _ = canvas_status()
    p, bak = flows.save_canvas(d, reason="space_open")
    return {"written": p, "backup": bak, "same_as_before": canvas_md5(d) == cur_md5,
            "md5": canvas_md5(d), "stats": flows.stats()}


def open_space(path=None, sim=None, page=None, yes=False):
    """**从总工程打开**: 集成式回填 (画布/标定/主参数/任务/面板)。返回报告。"""
    path = path or space_path()
    proj = _read(path)
    proj.setdefault("kind", KIND_SPACE)
    return integrated_apply(proj, sim=sim, page=page, yes=yes)


if __name__ == "__main__":                       # 命令行自检: python project_file.py
    import sys
    print("schema=%s ext=%s 档位=%d 个" % (SCHEMA, EXT, len(RUN_CHECKS)))
    d, probs, md5, stats = canvas_status()
    print("画布真源: %s" % _flows().canvas_path())
    print("md5=%s · stats=%s · 校验问题=%s" % (md5, stats, probs or "无 ✅"))
    print("标定: %s" % collect_calibration(with_content=False)["files"].keys())
    print("主参数: %s" % {k: v for k, v in collect_master_param().items() if k in ("M", "inertia")})
    print("默认工程目录: %s" % project_dir(sys.argv[1] if len(sys.argv) > 1 else None))
