#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/scene_phase_iteration.py — **场景 × Phase 0→4 元任务组合逐阶段迭代引擎** (插拔 / 摆盘)。

老倪 (2026-10-15, 最高优先) 原话:
  「用插拔 摆盘场景, phase0 到 phase4 全流程迭代元任务组合」

一句话口径: 对**插拔(TASK-01-FW)** 与 **摆盘(TASK-06-TRAY)** 两个场景, 各自把 **Phase 0→4 的
元任务组合逐阶段迭代** 做成一件事 —— 每 (场景, 阶段) 给出
  ① 组合推导   = (该阶段指标 ↔ 物理量 ↔ 元任务 的映射, 现算) ∩ (该任务的元任务集合)
                 + 相对上一阶段的 carried / added / upgraded (逐个 fn_id + 名称 + 为什么)
  ② 配置完备性 = 把推导出的组合与该任务**实际启用的元任务** (ss_meta_task 口径) 逐条对比
                 → missing / extra / coverage N/N  (这是配置改动的依据; 不开闸就不改配置)
  ③ 迭代验证   = 该阶段 N 项指标的实测值 vs 目标 (调 eval_probes.run_all() 唯一采集口径)
                 → 达标/未达标/未测/样本不足 + 证据类 + 样本量 + 帧龄; 并标明「实跑 / 未跑+原因」
  ④ 对比分析   = 场景×阶段矩阵 · 两场景逐阶段达标率 · 组合增量 · 与基线 5.50.735 对比

唯一依据 (全部现读现算; 本文件不硬编任何数字/指标名/目标值):
  · 指标定义       = config/platform/zmax_perf_spec.json (58 条)
  · phase 归属     = config/eval/phase_metric_map.json (map=归属 / carrier=物理载体段·量)
  · 元任务定义     = tools/export_meta_doc.py::build_meta_tasks() (75 元任务, complete=配置是否齐)
  · 指标↔物理量↔元任务 = tools/meta_perf_matrix.py::build() (指标 links FN-* 直连, 否则经物理载体段)
  · 任务↔元任务    = tools/ss_meta_task.py::build(task) (ss_task_binding 的 enabled_nodes 口径)
  · 任务配置       = config/tasks/tasks.json · config/ss_task_binding.json
  · 场景映射       = tools/ss_scene_switch.py::TASK_SCENE (任务→场景名/色)
  · 采集口径       = tools/eval_probes.py::run_all()  (**唯一采集入口**, 直接 import 调)
  · 判定/基线对比  = tools/eval_analysis.py::verdicts() (阈值达标 + 基线对比; 样本不足不出判定)
  · 基线锁         = config/eval/baseline_v<版本>.json (冻结)

场景作用域 (本工具口径, 记在 meta/note):
  eval_probes.run_all() 是**全局**采集口径 (它把 TASK-01-FW 的流形帧与 TASK-06-TRAY 的整链 run
  分开读)。要区分两场景, 采集结果的证据唯一依据 (src) 若明确属于**另一个任务**的产物 ⇒ 判该场景"未测"
  (本场景那条链没采过), 属全局唯一依据 (标定/规格/BOM/指标定义) 的则两场景共用。判据 = src 路径里的
  TASK-xx 标记, 不给数字、不猜。

判定口径 (硬规矩, 与 eval_probes/eval_analysis 一致):
  · 未测 ⇒ verdict=未测 (绝不用 0 或设计声明冒充实测); 设计声明(BOM/规格) 也是未测;
  · 样本不足 (extra.样本不足 / n < 口径) ⇒ verdict=样本不足, **不出判定**;
  · 目标「待定」/ 无阈值 ⇒ 未测; 升级准入三闸 = ①零回退 ②至少1项净提升 ③全局一致性零冲突。

产出:
  · zmax_data/eval/scene_phase_iteration.json   台账 (契约结构: meta / scenes[] / comparison)
  · zmax_data/eval/scene_phase_iteration.md     同内容 Markdown (评估分析区逐场景迭代用)

用法:
  ./gui-venv311/bin/python tools/scene_phase_iteration.py                 # 只读报告 (两场景, 落盘 JSON+MD)
  ./gui-venv311/bin/python tools/scene_phase_iteration.py --scene FW      # 只看插拔 (TRAY 也行)
  ./gui-venv311/bin/python tools/scene_phase_iteration.py --md            # 只出 Markdown (仍落盘)
  ./gui-venv311/bin/python tools/scene_phase_iteration.py --verify        # 自检 (a-e), 打 PASS/FAIL + 退出码
  ./gui-venv311/bin/python tools/scene_phase_iteration.py --apply         # **默认关**; 本工具只读, 传入即拒绝

只读纪律: 不修改在役配置 · 不切换场景 · 不触发真机动作; 只 git add 自己的产物。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import eval_analysis as EA                                                       # noqa: E402
import eval_probes as EP                                                         # noqa: E402
import export_meta_doc as EM                                                     # noqa: E402
import meta_perf_matrix as MPM                                                   # noqa: E402
import ss_meta_task as SMT                                                       # noqa: E402
import ss_scene_switch as SSS                                                    # noqa: E402

PERF_SPEC = os.path.join(ROOT, "config/platform/zmax_perf_spec.json")
PHASE_MAP = os.path.join(ROOT, "config/eval/phase_metric_map.json")
BASELINE = os.path.join(ROOT, "config/eval/baseline_%s.json" % EA.VERSION.replace(".", "_"))
OUT_JSON = os.path.join(ROOT, "zmax_data/eval/scene_phase_iteration.json")
OUT_MD = os.path.join(ROOT, "zmax_data/eval/scene_phase_iteration.md")

GENERATED_BY = "tools/scene_phase_iteration.py"
# 老倪点名的两个场景任务 (范围由需求给定, 不是指标/目标 ⇒ 不算硬编); 场景名从 ss_scene_switch 唯一依据取
SCENE_TASKS = sorted(t for t in EM.PRIORITY_TASKS if t in SSS.TASK_SCENE)
TASK_RE = re.compile(r"(TASK-[0-9A-Za-z]+(?:-[0-9A-Za-z]+)*)")


# ── 基础 IO ───────────────────────────────────────────────────────────────
def _load(p, d=None):
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:                                                            # noqa: BLE001
        return d


def _atomic(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _phases_ordered():
    """phase 顺序 (从唯一依据 phase_theme 的 key 排, 不硬编): 'Phase 0'..'Phase 4'"""
    pm = _load(PHASE_MAP, {}) or {}
    keys = list((pm.get("phase_theme") or {}).keys())
    if not keys:
        keys = sorted({v.get("phase") for v in (pm.get("map") or {}).values() if v.get("phase")})
    return sorted(keys, key=lambda s: int("".join(ch for ch in str(s) if ch.isdigit()) or 0))


def _scene_key(task):
    return str(task).split("-")[-1]


def _scene_name(task):
    m = SSS.TASK_SCENE.get(str(task)) or {}
    return str(m.get("scene") or "").replace("场景", "")


# ── 证据类/判定归一 (对齐契约枚举) ──────────────────────────────────────────
def _mode_enum(mode):
    m = str(mode or "")
    if m == "实测":
        return "实测"
    if m == "标定·配置":
        return "标定·配置"
    if m == "推导":
        return "推导"
    return "未测"                                                                # 设计声明(BOM)/未标定/None


def _verdict_enum(v):
    return {"达标": "达标", "不达标": "未达标", "样本不足": "样本不足"}.get(str(v or ""), "未测")


def _basecmp_enum(v):
    return {"提升": "提升", "持平": "持平", "回退": "回退"}.get(str(v or ""), "未测")


def _task_of_src(src):
    m = TASK_RE.search(str(src or ""))
    return m.group(1) if m else ""


# ── 组合推导 (从唯一依据现算) ──────────────────────────────────────────────────
def _fn_why(fn, rows, pmap, fn_name, prior_phases=None):
    """为什么这个元任务进本阶段组合: 从「本阶段指标 ← 物理量」推 (逐字现算, 不编)。"""
    ids, phys, stages = [], [], []
    for r in rows:
        if fn not in (r.get("元任务") or []):
            continue
        ids.append(r["id"])
        car = (pmap.get("carrier") or {}).get(r["id"]) or {}
        for p in (car.get("phys") or []):
            if p not in phys:
                phys.append(p)
        for s in (car.get("stages") or []):
            if s not in stages:
                stages.append(s)
    core = ("名称 %s; 本阶段指标 %s 经物理量 %s (载体段 %s) 挂到此元任务"
            % (fn_name.get(fn) or fn, "、".join(ids) or "-", "、".join(phys) or "-",
               "、".join(stages) or "全部段"))
    if prior_phases:
        return "跨阶段复用: 早在 %s 已引入 ⇒ 本阶段升级/强化; %s (来源 meta_perf_matrix.build())" % \
               ("、".join(prior_phases), core)
    return "%s (来源 meta_perf_matrix.build() 的元任务映射)" % core


def _derive_combo(combo, prev_combo, union_prior):
    """按「相对上一阶段」把本阶段组合拆成 carried / added / upgraded。

    · carried  = 本阶段组合 ∩ 上一阶段组合        (连续沿用)
    · added    = 本阶段组合 − 更早各阶段组合并集   (本阶段新增)
    · upgraded = 本阶段组合 ∩ 并集 − 上一阶段组合  (断档后复用 ⇒ 本阶段升级)
    """
    prev = set(prev_combo)
    carried = [fn for fn in combo if fn in prev]
    added = [fn for fn in combo if fn not in union_prior]
    upgraded = [fn for fn in combo if fn in union_prior and fn not in prev]
    return carried, added, upgraded


def build(scene=None):
    """构建 场景 × Phase 0→4 迭代台账 (契约结构)。scene=None ⇒ 两场景; scene='FW'/'TRAY' ⇒ 单场景。"""
    spec_idx = EP.metric_index()                     # id -> {cn,unit,target,how,std,stage,links,gid,gname}
    spec_order = list(spec_idx)
    pm = _load(PHASE_MAP, {}) or {}
    carrier = pm.get("carrier") or {}
    probes = EP.run_all()                            # 唯一采集口径
    base = _load(BASELINE, {}) or {}
    base_metrics = base.get("metrics") or {}
    base_version = str(base.get("version") or EA.VERSION).lstrip("v")

    mpm = MPM.build()                                # 指标 ↔ 物理量 ↔ 元任务 (现算)
    mpm_rows = {r["id"]: r for r in (mpm.get("性能指标") or [])}
    MT, _ = EM.build_meta_tasks()
    fn_name = {m["fn_id"]: (m.get("name") or "") for m in MT}
    fn_all = set(fn_name)

    cons = probes.get("perf.sys_consistency") or {}
    n_conf = len(((cons.get("extra") or {}).get("冲突")) or [])
    phase_order = _phases_ordered()
    theme_n = {p: ((pm.get("phase_theme") or {}).get(p) or {}).get("n") for p in phase_order}

    tasks = [t for t in SCENE_TASKS if scene is None or _scene_key(t) == str(scene).upper()]
    scenes_out = []
    for task in tasks:
        smt = SMT.build(task)                        # ss_meta_task 口径 (任务 → 元任务)
        enabled_fns = [it["fn_id"] for it in (smt.get("items") or [])]
        enabled_set = set(enabled_fns)

        phases_out = []
        prev_combo = []
        union_prior = set()
        combo_by_phase = {}
        for pid in phase_order:
            theme = (pm.get("phase_theme") or {}).get(pid) or {}
            name = str(theme.get("theme") or "").split("(")[0].strip() or pid
            rows = [mpm_rows[mid] for mid in spec_order if (mpm_rows.get(mid) or {}).get("phase") == pid]

            # ① 组合推导: 本阶段指标所挂元任务 ∩ 该任务的元任务集合
            combo = []
            for r in rows:
                for fn in (r.get("元任务") or []):
                    if fn in enabled_set and fn not in combo:
                        combo.append(fn)
            carried, added_fns, upgraded_fns = _derive_combo(combo, prev_combo, union_prior)
            added = [{"fn_id": fn, "name": fn_name.get(fn) or "",
                      "why": _fn_why(fn, rows, pm, fn_name)} for fn in added_fns]
            upgraded = [{"fn_id": fn, "name": fn_name.get(fn) or "",
                         "why": _fn_why(fn, rows, pm, fn_name,
                                        prior_phases=[p for p in phase_order if fn in combo_by_phase.get(p, [])])}
                        for fn in upgraded_fns]

            # ② 配置完备性核验 (组合 vs 该任务实际启用的元任务)
            missing = [{"fn_id": fn, "name": fn_name.get(fn) or ""} for fn in combo if fn not in enabled_set]
            extra = [{"fn_id": fn, "name": fn_name.get(fn) or ""} for fn in enabled_fns if fn not in combo]
            combo_mapped = len([fn for fn in combo if fn in enabled_set])
            config_check = {
                "enabled_nodes": int(smt.get("enabled_nodes") or 0),
                "combo_mapped": combo_mapped,
                "coverage": "%d/%d" % (combo_mapped, len(combo)),
                "missing": missing,
                "extra": extra,
                "pass": len(missing) == 0,
            }

            # ③ 迭代验证 (该阶段指标实测值 vs 目标; 场景作用域见文件头 docstring)
            vrows, n_pass, n_fail, n_unt, n_short = [], 0, 0, 0, 0
            n_up, n_flat, n_down = 0, 0, 0
            ev_srcs, ran = [], False
            for r in rows:
                mid = r["id"]
                d = spec_idx.get(mid) or {}
                m = probes.get(mid) or {}
                src = m.get("src") or ""
                src_task = _task_of_src(src)
                in_scope = (src_task == "" or src_task == task)
                bval = (base_metrics.get(mid) or {}).get("value")
                n_val, age_val = (m.get("n") or 0), m.get("age_s")
                if in_scope:
                    vd = EA.verdicts(m, bval)
                    verdict = _verdict_enum(vd.get("达标"))
                    mode = _mode_enum(m.get("mode"))
                    value = m.get("value")
                    note = vd.get("说明") or m.get("note") or ""
                    if str(m.get("mode") or "").startswith("设计声明"):
                        note = (m.get("note") or note or "")[:220]
                    if mode in ("实测", "标定·配置", "推导"):
                        ran = True
                        if src and src not in ev_srcs:
                            ev_srcs.append(src)
                else:
                    verdict, mode, value = "未测", "未测", None
                    note = ("证据唯一依据属 %s (非本场景 %s) ⇒ 本场景未采; 采集条件: %s"
                            % (src_task, task, d.get("how") or "未给"))
                    vd = {"达标": "未测", "基线对比": "未测", "说明": note}
                    src, n_val, age_val = "", 0, None
                if verdict == "达标":
                    n_pass += 1
                elif verdict == "未达标":
                    n_fail += 1
                elif verdict == "样本不足":
                    n_short += 1
                else:
                    n_unt += 1
                bcmp = _basecmp_enum(vd.get("基线对比"))
                if bcmp == "提升":
                    n_up += 1
                elif bcmp == "持平":
                    n_flat += 1
                elif bcmp == "回退":
                    n_down += 1
                vrows.append({
                    "id": mid, "name": d.get("cn"), "value": value, "unit": m.get("unit") or d.get("unit"),
                    "target": d.get("target"), "verdict": verdict, "mode": mode, "src": src,
                    "n": n_val, "age_s": age_val, "note": note,
                })

            run = {
                "mode": "实跑" if ran else "未跑",
                "evidence": "; ".join(os.path.relpath(s, ROOT) if os.path.isabs(s) else s for s in ev_srcs),
                "cmd": "tools/eval_probes.py::run_all() (in-process; 唯一采集口径)",
                "note": ("本阶段 %d 项指标中 %d 项在采集里拿到真值 (证据类 实测/标定·配置/推导); 其余未测 "
                         "(本机无采集条件 或 证据唯一依据属他场景)。真机动作类需 8793 授权且产线/Orin 不可达 ⇒ 未跑。"
                         % (len(rows), sum(1 for x in vrows if x["mode"] in ("实测", "标定·配置", "推导")))),
            }

            entry = {
                "gate1_zero_regress": n_down == 0,
                "gate2_net_gain": n_up >= 1,
                "gate3_consistency": n_conf == 0,
                "open": (n_down == 0 and n_up >= 1 and n_conf == 0),
                "note": ("升级准入三闸 (与 eval_analysis 同口径): ①零回退 回退 %d · ②至少1项净提升 提升 %d · "
                         "③全局一致性零冲突 (全局 冲突 %d)。gate3 为全局口径。" % (n_down, n_up, n_conf)),
            }

            phases_out.append({
                "phase": pid, "name": name,
                "combo": {"carried": carried, "added": added, "upgraded": upgraded, "total": len(combo)},
                "config_check": config_check,
                "run": run,
                "verification": {"pass": n_pass, "fail": n_fail, "unmeasured": n_unt,
                                 "insufficient": n_short, "metrics": vrows},
                "entry": entry,
            })
            prev_combo = combo
            union_prior |= set(combo)
            combo_by_phase[pid] = combo

        last_cc = phases_out[-1]["config_check"]["coverage"] if phases_out else "0/0"
        scenes_out.append({
            "scene": _scene_key(task), "scene_name": _scene_name(task), "task": task,
            "phases": phases_out,
            "summary": {
                "pass": sum(p["verification"]["pass"] for p in phases_out),
                "fail": sum(p["verification"]["fail"] for p in phases_out),
                "unmeasured": sum(p["verification"]["unmeasured"] for p in phases_out),
                "coverage_last": last_cc,
            },
        })

    data = {
        "meta": {"ts": int(time.time()), "version": EA.VERSION, "baseline": base_version,
                 "generated_by": GENERATED_BY},
        "scenes": scenes_out,
    }
    data["comparison"] = _comparison(data, spec_idx, spec_order, phase_order)
    return data


# ── ④ 对比分析 ────────────────────────────────────────────────────────────
def _scene_phase_verdict(scene_obj, pid, mid):
    for p in (scene_obj.get("phases") or []):
        if p.get("phase") != pid:
            continue
        x = next((m for m in p["verification"]["metrics"] if m["id"] == mid), None)
        if x:
            return x.get("value"), x.get("verdict")
    return None, "未测"


def _comparison(data, spec_idx, spec_order, phase_order):
    scenes = {s["scene"]: s for s in data["scenes"]}
    keys = ("p0", "p1", "p2", "p3", "p4")
    phase_of = {}
    for s in data["scenes"]:
        for p in s["phases"]:
            for m in p["verification"]["metrics"]:
                phase_of[m["id"]] = p["phase"]

    matrix = []
    for mid in spec_order:
        d = spec_idx.get(mid) or {}
        row = {"id": mid, "name": d.get("cn"), "unit": d.get("unit"), "target": d.get("target")}
        for key, sc in (("FW", "FW"), ("TRAY", "TRAY")):
            col = {k: None for k in keys}
            so = scenes.get(sc)
            if so:
                val, _ = _scene_phase_verdict(so, phase_of.get(mid), mid)
                idx = phase_order.index(phase_of.get(mid)) if phase_of.get(mid) in phase_order else None
                if idx is not None and val is not None:
                    col[keys[idx]] = val
            row[key] = col
        _, v_fw = _scene_phase_verdict(scenes.get("FW", {}), phase_of.get(mid), mid)
        _, v_tr = _scene_phase_verdict(scenes.get("TRAY", {}), phase_of.get(mid), mid)
        row["verdict"] = "FW %s / TRAY %s" % (v_fw, v_tr)
        matrix.append(row)

    pass_rate, combo_delta, vs_base = {}, {}, {}
    for sc, so in scenes.items():
        pass_rate[sc] = [{"phase": p["phase"], "pass": p["verification"]["pass"],
                          "total": len(p["verification"]["metrics"])} for p in so["phases"]]
        combo_delta[sc] = {"added": sum(len(p["combo"]["added"]) for p in so["phases"]),
                           "upgraded": sum(len(p["combo"]["upgraded"]) for p in so["phases"])}
        vs_base[sc] = _vs_baseline(so)

    return {
        "matrix": matrix,
        "pass_rate": pass_rate,
        "combo_delta": combo_delta,
        "vs_baseline": vs_base,
        "note": ("matrix 每行一个指标 (共 %d 条)。FW/TRAY 两列 = 该指标在其归属 phase 的采集值 "
                 "(非归属 phase 一律 null)。采集口径 run_all() 为全局口径: 证据唯一依据属他场景的记 null/未测 "
                 "(场景作用域见本文件 docstring)。verdict 列给出两场景各自判定。"
                 "注: 两场景的任务元任务集合同源 (ss_task_binding 两任务同 enabled_nodes 口径) ⇒ 组合/组合增量"
                 "两场景一致; 场景差异体现在「迭代验证」的采集值 (证据唯一依据属哪个任务) 与达标率。" % len(matrix)),
    }


def _vs_baseline(scene_obj):
    base = _load(BASELINE, {}) or {}
    bm = base.get("metrics") or {}
    up = flat = down = 0
    for p in scene_obj["phases"]:
        for m in p["verification"]["metrics"]:
            if m["value"] is None or str(m.get("mode")) == "未测":
                continue
            b = (bm.get(m["id"]) or {}).get("value")
            if b is None:
                continue
            d = m["value"] - float(b)
            eps = max(1e-9, abs(float(b)) * 0.005)
            if abs(d) <= eps:
                flat += 1
            else:
                up += 1 if d > 0 else 0
                down += 1 if d < 0 else 0
    return {"improved": up, "flat": flat, "regressed": down}


# ── Markdown ──────────────────────────────────────────────────────────────
def render_md(data):
    L = []
    A = L.append
    m = data["meta"]
    A("# 场景 × Phase 0→4 元任务组合逐阶段迭代 (插拔 / 摆盘 · 基线产品 v%s)" % m["baseline"])
    A("")
    A("生成 `%s` · 由 `%s` 现算 · **零硬编**: 指标名/目标值/归属/采集值全部取唯一依据。"
      % (time.strftime("%F %T", time.localtime(m["ts"])), m["generated_by"]))
    A("")
    for so in data["scenes"]:
        A("## 场景 %s (%s · %s)" % (so["scene_name"], so["scene"], so["task"]))
        A("")
        A("- 达标汇总: 达标 **%d** · 未达标 %d · 未测 %d ｜ 末阶段配置覆盖 **%s**"
          % (so["summary"]["pass"], so["summary"]["fail"], so["summary"]["unmeasured"],
             so["summary"]["coverage_last"]))
        A("")
        for p in so["phases"]:
            v, cc, rn, c = p["verification"], p["config_check"], p["run"], p["combo"]
            A("### %s · %s" % (p["phase"], p["name"]))
            A("")
            A("- 元任务组合: 合计 **%d** ｜ carried %d · added %d · upgraded %d"
              % (c["total"], len(c["carried"]), len(c["added"]), len(c["upgraded"])))
            if c["added"]:
                A("  - **新增**: " + "、".join("%s %s" % (x["fn_id"], x["name"]) for x in c["added"]))
            if c["upgraded"]:
                A("  - **升级**: " + "、".join("%s %s" % (x["fn_id"], x["name"]) for x in c["upgraded"]))
            A("- 配置完备性: 覆盖 **%s** (enabled_nodes %d) ｜ missing **%d** · extra **%d** ｜ %s"
              % (cc["coverage"], cc["enabled_nodes"], len(cc["missing"]), len(cc["extra"]),
                 "✅ 组合全在该任务启用集内" if cc["pass"] else "⛔ 有缺口"))
            A("- 迭代验证: 达标 %d · 未达标 %d · 样本不足 %d · 未测 %d ｜ 运行 **%s**"
              % (v["pass"], v["fail"], v["insufficient"], v["unmeasured"], rn["mode"]))
            A("- 升级准入: ①零回退=%s ②净提升=%s ③零冲突=%s ⇒ **%s**"
              % (p["entry"]["gate1_zero_regress"], p["entry"]["gate2_net_gain"],
                 p["entry"]["gate3_consistency"], "开闸" if p["entry"]["open"] else "未开闸"))
            A("")
            A("| 指标 id | 指标名 | 单位 | 目标 | 采集值 | 判定 | 证据 | n | 帧龄s |")
            A("|---|---|---|---|---|---|---|---|---|")
            for r in v["metrics"]:
                A("| `%s` | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                    r["id"], r["name"], r["unit"], str(r["target"])[:26],
                    ("%.4g" % r["value"]) if isinstance(r["value"], (int, float)) else "未测",
                    r["verdict"], r["mode"], r["n"],
                    ("%.0f" % r["age_s"]) if isinstance(r["age_s"], (int, float)) and r["age_s"] >= 0 else "-"))
            A("")
        A("")
    cp = data["comparison"]
    A("## 对比分析")
    A("")
    A("- **逐阶段达标率**: " + " ｜ ".join(
        "%s %s" % (sc, " ".join("%s %d/%d" % (x["phase"], x["pass"], x["total"]) for x in cp["pass_rate"].get(sc, [])))
        for sc in ("FW", "TRAY")))
    A("- **组合增量**: " + " ｜ ".join(
        "%s added %d · upgraded %d" % (sc, cp["combo_delta"][sc]["added"], cp["combo_delta"][sc]["upgraded"])
        for sc in ("FW", "TRAY") if sc in cp["combo_delta"]))
    A("- **对比基线 v%s**: " % m["baseline"] + " ｜ ".join(
        "%s 提升 %d · 持平 %d · 回退 %d" % (sc, cp["vs_baseline"][sc]["improved"], cp["vs_baseline"][sc]["flat"],
                                        cp["vs_baseline"][sc]["regressed"])
        for sc in ("FW", "TRAY") if sc in cp["vs_baseline"]))
    A("")
    A("### 场景×阶段矩阵 (每指标 FW 的 p0..p4 vs TRAY 的 p0..p4)")
    A("")
    A("| 指标 id | 指标名 | 单位 | target | FW p0..p4 | TRAY p0..p4 | verdict |")
    A("|---|---|---|---|---|---|---|")
    for row in cp["matrix"]:
        fw = " ".join("-" if row["FW"][k] is None else "%.4g" % row["FW"][k] for k in ("p0", "p1", "p2", "p3", "p4"))
        tr = " ".join("-" if row["TRAY"][k] is None else "%.4g" % row["TRAY"][k] for k in ("p0", "p1", "p2", "p3", "p4"))
        A("| `%s` | %s | %s | %s | %s | %s | %s |"
          % (row["id"], row["name"], row["unit"] or "", str(row["target"])[:22], fw, tr, row["verdict"]))
    A("")
    A("> 未测 = 本机无采集条件 或 证据唯一依据属他场景 (非实测); 样本不足 = 只报值不判定。逐条原因见 JSON `note`。")
    A("")
    return "\n".join(L) + "\n"


# ── 自检 (a-e) ────────────────────────────────────────────────────────────
def verify(data):
    spec_idx = EP.metric_index()
    MT, _ = EM.build_meta_tasks()
    fn_all = {m["fn_id"] for m in MT}
    phases = _phases_ordered()
    theme_n = {p: ((_load(PHASE_MAP, {}) or {}).get("phase_theme") or {}).get(p, {}).get("n") for p in phases}

    checks = []

    def add(name, ok, detail):
        checks.append((name, ok, detail))

    # (a) 两场景齐
    keys = [s["scene"] for s in data["scenes"]]
    want = [_scene_key(t) for t in SCENE_TASKS]
    add("(a) 两场景齐 (%s)" % "/".join(want), sorted(keys) == sorted(want),
        "实得 %s" % (keys or "空"))

    # (b) 每场景 5 阶段齐
    bad_b = [(s["scene"], [p["phase"] for p in s["phases"]]) for s in data["scenes"]
             if [p["phase"] for p in s["phases"]] != phases]
    add("(b) 每场景 %d 阶段齐 (%s)" % (len(phases), "→".join(phases)), not bad_b,
        "全部齐" if not bad_b else str(bad_b))

    # (c) 场景内指标不重不漏 == 全集(58) 且 每阶段指标数 == phase_metric_map
    all_spec = set(spec_idx)
    seen, dup, bad_n, bad_scene = set(), [], [], []
    for s in data["scenes"]:
        sc_seen = set()
        for p in s["phases"]:
            ids = [m["id"] for m in p["verification"]["metrics"]]
            for i in ids:
                if i in sc_seen:
                    dup.append("%s:%s" % (s["scene"], i))
                sc_seen.add(i)
            if theme_n.get(p["phase"]) is not None and len(ids) != theme_n[p["phase"]]:
                bad_n.append((s["scene"], p["phase"], len(ids), theme_n[p["phase"]]))
        if sc_seen != all_spec:
            bad_scene.append((s["scene"], sorted(all_spec - sc_seen)[:4], sorted(sc_seen - all_spec)[:4]))
        seen |= sc_seen
    ok_c = (not dup) and (not bad_scene) and (seen == all_spec) and (not bad_n)
    add("(c) 每场景指标不重不漏==全集(%d) 且 每阶段指标数==phase_metric_map" % len(all_spec), ok_c,
        "并集 %d 条 · 场景内重复 %s · 场景集合偏差 %s · 阶段计数不符 %s"
        % (len(seen), dup or "无", bad_scene or "无", bad_n or "无"))

    # (d) 组合里的 fn_id 全在 build_meta_tasks
    miss_d = []
    for s in data["scenes"]:
        for p in s["phases"]:
            c = p["combo"]
            for fn in c["carried"]:
                if fn not in fn_all:
                    miss_d.append(fn)
            for row in (c["added"] + c["upgraded"]):
                if row["fn_id"] not in fn_all:
                    miss_d.append(row["fn_id"])
    add("(d) 组合 fn_id 均在 build_meta_tasks() 找得到", not miss_d,
        ", ".join(sorted(set(miss_d))) or "全部命中 (共 %d 元任务)" % len(fn_all))

    # (e) 对比矩阵行数 == 指标数
    nt = len(data["comparison"]["matrix"])
    add("(e) 对比矩阵行数 == 指标数", nt == len(all_spec), "matrix %d 行 / 指标 %d 条" % (nt, len(all_spec)))

    return checks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="自检 (a-e) 并列 PASS/FAIL + 退出码")
    ap.add_argument("--md", action="store_true", help="出 Markdown (仍落盘)")
    ap.add_argument("--scene", default=None, help="只看 FW | TRAY")
    ap.add_argument("--apply", action="store_true",
                    help="**默认关**; 本工具只读, 不改在役配置 (传入即拒绝)")
    a = ap.parse_args()

    if a.apply:
        print("⛔ --apply: 本工具**只读** (不修改在役配置 / 不切换场景 / 不触发真机动作)。"
              "配置改动须人工核验三闸后再由配置中心执行 ⇒ 拒绝。")
        return 3

    scene = a.scene.upper() if a.scene else None
    data = build(scene=None)                        # JSON 台账恒为两场景全量 (机器契约)
    _atomic(OUT_JSON, data)
    view = data if not scene else {                 # --scene 仅过滤人读输出 (Markdown/控制台)
        **data, "scenes": [s for s in data["scenes"] if s["scene"] == scene]}
    md = render_md(view)
    os.makedirs(os.path.dirname(OUT_MD), exist_ok=True)
    with open(OUT_MD, "w", encoding="utf-8") as fh:
        fh.write(md)

    print("台账: %s (恒两场景全量)" % os.path.relpath(OUT_JSON, ROOT))
    print("报告: %s%s" % (os.path.relpath(OUT_MD, ROOT), " (--scene %s)" % scene if scene else ""))
    m = data["meta"]
    print("场景 %d · 指标 %d · 基线 %s · 版本 %s"
          % (len(data["scenes"]), len(EP.metric_index()), m["baseline"], m["version"]))
    for s in view["scenes"]:
        print("─ %s (%s · %s)" % (s["scene_name"], s["scene"], s["task"]))
        for p in s["phases"]:
            v, cc, c, rn = p["verification"], p["config_check"], p["combo"], p["run"]
            print("    %-8s %-12s 指标 %2d | 达标 %d 未达标 %d 样本不足 %d 未测 %d | combo %2d(+%d/~%d) | 覆盖 %-5s miss %d | %s | 准入 %s"
                  % (p["phase"], p["name"][:12], len(v["metrics"]), v["pass"], v["fail"], v["insufficient"],
                     v["unmeasured"], c["total"], len(c["added"]), len(c["upgraded"]), cc["coverage"],
                     len(cc["missing"]), rn["mode"], "开闸" if p["entry"]["open"] else "未开闸"))
    cp = data["comparison"]
    print("对比矩阵 %d 行" % len(cp["matrix"]))
    for sc in ("FW", "TRAY"):
        if sc in cp["pass_rate"]:
            print("  %s 逐阶段达标率: %s" % (sc, " ".join("%s %d/%d" % (x["phase"], x["pass"], x["total"])
                                                        for x in cp["pass_rate"][sc])))
            print("  %s 组合增量: added %d · upgraded %d | 对比基线 %s"
                  % (sc, cp["combo_delta"][sc]["added"], cp["combo_delta"][sc]["upgraded"],
                     cp["vs_baseline"][sc]))

    if a.verify:
        print("\n=== --verify 自检 ===")
        checks = verify(data)                       # data 恒为两场景全量, 自检不受 --scene 影响
        for name, ok, detail in checks:
            print("[%s] %s -> %s" % ("PASS" if ok else "FAIL", name, detail))
        allok = all(ok for _, ok, _ in checks)
        print("自检: %d/%d PASS %s" % (sum(1 for _, ok, _ in checks if ok), len(checks),
                                     "✅ 全绿" if allok else "❌ 有 FAIL"))
        return 0 if allok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
