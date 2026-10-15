#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/iteration_roadmap.py — 产品迭代路线 Phase 0→4 的**可验证迭代路线引擎**。

老倪 (2026-10-15) 原话:
  「按照控制台的产品迭代 roadmap phase 0 开始 到 phase 4, 通过元任务的升级组合, 逐步实现每个阶段的
    主要性能指标…我要你的迭代路线图, 在评估分析功能区, 迭代验证, 对比分析」
  「对应 phase 0 反馈速度延迟; phase1 对位残差; phase 2 成功率,节拍; phase 3 稳定性; phase4 可靠性
    准确性等; 从任务配置开始, 从每一个元任务开始, 根据每个元任务, 给出完整的元任务配置与性能配置的
    对应关系, 给出所有性能指标的物理值验证结果」

一句话口径: 把「Phase 0→4 逐步实现主要性能指标」做成一件事 —— 每阶段 = 一组**主要性能指标**
(从唯一真源现算) + 一组**元任务升级组合** (基线组合 vs 本阶段新增/升级, 从真源推导) + **逐步实现
路径** (本阶段用这些元任务去推哪些指标、目标值多少, 目标值一律读真源); 再叠上**实测验证**与
**对基线产品的对比分析**。全程零硬编: 指标名/目标值/归属/采集值全部现取现算。

真源 (全部现读; 本文件不硬编任何指标名/目标值/数字):
  · 指标定义唯一真源   = config/platform/zmax_perf_spec.json (58 条 / 6 组 A-F; 目标值+采集方法+标准)
  · phase 归属唯一真源 = config/eval/phase_metric_map.json (58/58; map=归属, carrier=物理载体段/量)
  · phase KPI 文案     = config/roadmap_phase_texts.json (各 phase title/time/dims/desc/kpi)
  · 采集口径唯一真源   = tools/eval_probes.py::run_all()  (证据类 mode: 实测/标定·配置/推导/未测)
                         —— **直接 import 调 run_all(), 绝不另写采集逻辑**
  · 判定/基线对比唯一真源 = tools/eval_analysis.py::verdicts() (阈值达标 + 基线对比; 样本不足不出判定)
  · 指标↔物理量↔元任务 = tools/meta_perf_matrix.py::build() (指标 links FN-* / 载体段→SKxx→元任务)
  · 元任务定义         = tools/export_meta_doc.py::build_meta_tasks() (config_meta.json 75 元任务; complete=配置是否齐)
  · 基线锁             = config/eval/baseline_v<版本>.json (冻结)

元任务升级组合 (从真源推导, 定义见 _derive_combo):
  · baseline  = 本 phase 指标所挂元任务 ∩ 「配置已齐」(complete=True)      —— 基线产品已具备的组合
  · added     = 本 phase 指标所挂元任务 − 「配置已齐」                      —— 本阶段要新增/补齐的元任务
  · upgraded  = 本 phase 指标所挂元任务 ∩ 更早 phase 的组合并集              —— 跨阶段复用, 在本阶段被升级
    (baseline 与 upgraded 允许重叠: 升级是对基线组合的强化; 出处注释写在每阶段 derive 字段)

判定口径 (硬规矩, 与 eval_probes/eval_analysis 一致):
  · 未测 ⇒ verdict=未测 (绝不用 0 或设计声明冒充实测); 设计声明(BOM) 也是未测, mode_raw 留痕;
  · 样本不足 ⇒ verdict=样本不足, **不出判定**; 目标「待定」⇒ 未测;
  · 升级准入三条硬闸 (与 eval_analysis 同口径): ① 零回退 ② 至少 1 项净提升 ③ 全局一致性零冲突。

产出:
  · config/eval/iteration_roadmap.json        路线定义 (phases[0..4]: name/target_metrics/entry_criteria/meta_combo)
  · defaults/config/eval/iteration_roadmap.json  同上的**可版本控制镜像** (config/ 是 data/ 下软链, 被 gitignore)
  · zmax_data/eval/iteration_roadmap.json     运行台账 (定义 + verification + vs_baseline + entry + comparison)
  · zmax_data/eval/iteration_roadmap.md       同内容 Markdown (评估分析区迭代验证用)
  · docs/eval/迭代路线图_v<版本>.md            同内容 Markdown (仓库惯例的人读报告落点, 可版本控制)

用法:
  ./gui-venv311/bin/python tools/iteration_roadmap.py            # 生成 定义 + 台账 + 报告
  ./gui-venv311/bin/python tools/iteration_roadmap.py --verify   # 自检 (a-e), 打 PASS/FAIL, 退出码说明结果
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import eval_probes as EP                                                        # noqa: E402
import eval_analysis as EA                                                      # noqa: E402
import meta_perf_matrix as MPM                                                  # noqa: E402

PERF_SPEC = os.path.join(ROOT, "config/platform/zmax_perf_spec.json")
PHASE_MAP = os.path.join(ROOT, "config/eval/phase_metric_map.json")
ROADMAP = os.path.join(ROOT, "config/roadmap_phase_texts.json")
BASELINE = os.path.join(ROOT, "config/eval/baseline_%s.json" % EA.VERSION.replace(".", "_"))
DEF_OUT = os.path.join(ROOT, "config/eval/iteration_roadmap.json")
OUT_JSON = os.path.join(ROOT, "zmax_data/eval/iteration_roadmap.json")
OUT_MD = os.path.join(ROOT, "zmax_data/eval/iteration_roadmap.md")
# 可版本控制的镜像 (config/ 是 data/ 下的软链, 被 .gitignore 覆盖 ⇒ 定义另存一份进 defaults/;
# 人读报告按仓库惯例落在 docs/eval/, 与 meta_perf_matrix/eval_analysis 同处)
MIRROR_DEF = os.path.join(ROOT, "defaults/config/eval/iteration_roadmap.json")
DOC = os.path.join(ROOT, "docs/eval/迭代路线图_v%s.md" % EA.VERSION.lstrip("v"))

GENERATED_BY = "tools/iteration_roadmap.py"


def _load(p, d=None):
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:                                                           # noqa: BLE001
        return d


def _atomic(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _phases_ordered():
    """phase 顺序 (从真源 key 排, 不硬编): 'Phase 0'..'Phase 4'"""
    pm = _load(PHASE_MAP, {}) or {}
    keys = list((pm.get("phase_theme") or {}).keys()) or list(((pm.get("map") or {}) and
                 {v.get("phase") for v in pm["map"].values()}) or [])
    return sorted(keys, key=lambda s: int("".join(ch for ch in str(s) if ch.isdigit()) or 0))


# ── 证据类/判定归一 (对齐契约枚举) ────────────────────────────────────────────
def _mode_enum(mode):
    m = str(mode or "")
    if m == "实测":
        return "实测"
    if m == "标定·配置":
        return "标定·配置"
    if m == "推导":
        return "推导"
    return "未测"                                                                # 含 设计声明(BOM)/未标定/None


def _verdict_enum(v):
    return {"达标": "达标", "不达标": "未达标", "样本不足": "样本不足"}.get(str(v or ""), "未测")


def _basecmp_enum(v):
    return {"提升": "提升", "持平": "持平", "回退": "回退"}.get(str(v or ""), "未测")


# ── 元任务升级组合 (从真源推导) ───────────────────────────────────────────────
def _derive_combo(combo_fns, fn_meta, prior_union):
    """按「配置是否齐 (complete) + 跨阶段复用」把本阶段元任务拆成 baseline/added/upgraded。

    真源: fn_meta 来自 export_meta_doc.build_meta_tasks()['complete']; prior_union = 更早 phase 组合并集。
    · baseline = 配置已齐 (complete=True)   —— 基线产品已具备
    · added    = 配置未齐 (complete=False)  —— 本阶段新增/补齐
    · upgraded = 命中更早阶段组合          —— 跨阶段复用, 本阶段升级 (与 baseline 可重叠, 语义: 强化)
    """
    base, add, upg = [], [], []
    for fn in combo_fns:
        m = fn_meta.get(fn) or {}
        row = {"fn_id": fn, "name": m.get("name") or ""}
        if m.get("complete") is False:
            add.append(row)
        else:
            base.append(fn)
        if fn in prior_union:
            upg.append(row)
    return base, add, upg


# ── 主构建 ────────────────────────────────────────────────────────────────
def build():
    spec_idx = EP.metric_index()                     # id -> {cn,unit,target,how,std,stage,links,gid,gname}
    pm = _load(PHASE_MAP, {}) or {}
    roadmap = _load(ROADMAP, {}) or {}
    probes = EP.run_all()                            # 唯一采集口径
    base = _load(BASELINE, {}) or {}
    base_metrics = base.get("metrics") or {}
    base_version = str(base.get("version") or EA.VERSION).lstrip("v")

    mpm = MPM.build()                                # 指标 ↔ 物理量 ↔ 元任务 (现算)
    mpm_rows = {r["id"]: r for r in (mpm.get("性能指标") or [])}

    import export_meta_doc as E                                                     # noqa: E402
    MT, _ = E.build_meta_tasks()
    fn_meta = {m["fn_id"]: m for m in MT}

    # 全局一致性 (三条硬闸之三的来源: perf.sys_consistency)
    cons = probes.get("perf.sys_consistency") or {}
    n_conf = len(((cons.get("extra") or {}).get("冲突")) or [])

    phases_out = []
    prior_union = set()
    for pid in _phases_ordered():
        theme = (pm.get("phase_theme") or {}).get(pid) or {}
        rw = (roadmap.get("phases") or {}).get(pid) or {}
        name = str(theme.get("theme") or "").split("(")[0].strip() or str(rw.get("title") or pid)

        rows = [mpm_rows[mid] for mid in mpm_rows if mpm_rows[mid].get("phase") == pid]
        rows.sort(key=lambda r: list(spec_idx).index(r["id"]) if r["id"] in spec_idx else 999)

        # 该 phase 指标所挂元任务并集 (顺序稳定)
        combo_fns = []
        for r in rows:
            for fn in (r.get("元任务") or []):
                if fn not in combo_fns:
                    combo_fns.append(fn)
        baseline_fns, added, upgraded = _derive_combo(combo_fns, fn_meta, prior_union)
        prior_union |= set(combo_fns)

        target_metrics = []
        for r in rows:
            d = spec_idx.get(r["id"]) or {}
            target_metrics.append({
                "id": r["id"], "name": d.get("cn") or r.get("cn"),
                "unit": d.get("unit"), "target": d.get("target"),
                "group": d.get("gname") or d.get("group") or "",
            })

        # ── 实测验证 (verification) ──
        vrows, n_pass, n_fail, n_unt, n_short = [], 0, 0, 0, 0
        b_items, n_up, n_flat, n_down = [], 0, 0, 0
        for r in rows:
            mid = r["id"]
            d = spec_idx.get(mid) or {}
            m = probes.get(mid) or {}
            bval = (base_metrics.get(mid) or {}).get("value")
            vd = EA.verdicts(m, bval)
            verdict = _verdict_enum(vd.get("达标"))
            if verdict == "达标":
                n_pass += 1
            elif verdict == "未达标":
                n_fail += 1
            elif verdict == "样本不足":
                n_short += 1
            else:
                n_unt += 1
            vrows.append({
                "id": mid, "name": d.get("cn"), "value": m.get("value"), "unit": m.get("unit"),
                "target": d.get("target"), "verdict": verdict, "mode": _mode_enum(m.get("mode")),
                "mode_raw": m.get("mode"), "src": m.get("src"), "age_s": m.get("age_s"), "n": m.get("n"),
                "note": vd.get("说明") or m.get("note") or "",
            })
            bcmp = _basecmp_enum(vd.get("基线对比"))
            cur = m.get("value")
            delta = (round(float(cur) - float(bval), 6)
                     if isinstance(cur, (int, float)) and isinstance(bval, (int, float)) else None)
            if bcmp == "提升":
                n_up += 1
            elif bcmp == "持平":
                n_flat += 1
            elif bcmp == "回退":
                n_down += 1
            b_items.append({"id": mid, "name": d.get("cn"), "baseline": bval, "current": cur,
                            "delta": delta, "verdict": bcmp})

        entry = {
            "gate1_zero_regress": n_down == 0,
            "gate2_net_gain": n_up >= 1,
            "gate3_consistency": n_conf == 0,
            "open": (n_down == 0 and n_up >= 1 and n_conf == 0),
            "note": ("升级准入三闸 (与 eval_analysis 同口径): ①零回退 回退 %d · ②至少1项净提升 提升 %d · "
                     "③全局一致性零冲突 (全局 冲突 %d)。gate3 为全局口径, 各 phase 相同。" % (n_down, n_up, n_conf)),
        }

        phases_out.append({
            "phase": pid, "name": name, "time": rw.get("time"), "title": rw.get("title"),
            "kpi": rw.get("kpi"), "theme": theme.get("theme"), "rule": theme.get("rule"),
            "n_metrics": len(rows),
            "target_metrics": target_metrics,
            "entry_criteria": {
                "kpi": rw.get("kpi"), "time": rw.get("time"), "dims": rw.get("dims"),
                "rule": theme.get("rule"),
                "note": "进入本阶段的口径 = 前一阶段三条硬闸通过 (零回退/净提升/零冲突) 且本阶段指标可采。",
            },
            "meta_combo": {"baseline": baseline_fns, "added": added, "upgraded": upgraded,
                           "derive": ("baseline=本阶段指标所挂元任务∩配置已齐(complete=True); "
                                      "added=所挂元任务−配置已齐 (本阶段新增/补齐); "
                                      "upgraded=所挂元任务∩更早阶段组合并集 (跨阶段复用⇒本阶段升级)。"
                                      "元任务↔指标映射来源 = meta_perf_matrix.build() 元任务字段 "
                                      "(指标 links FN-* 直连, 否则经物理载体段→SKxx→元任务)。")},
            "verification": {"pass": n_pass, "fail": n_fail, "unmeasured": n_unt,
                             "insufficient": n_short, "metrics": vrows},
            "vs_baseline": {"improved": n_up, "flat": n_flat, "regressed": n_down, "items": b_items},
            "entry": entry,
        })

    # ── comparison (对比分析) ──
    trend = []
    for mid, d in spec_idx.items():
        phase_of = (mpm_rows.get(mid) or {}).get("phase") or "未映射"
        pmap_val = {}
        for p in phases_out:
            hv = next((x for x in p["verification"]["metrics"] if x["id"] == mid), None)
            pmap_val[p["phase"]] = hv.get("value") if hv else None
        verdict = next((x["verdict"] for p in phases_out for x in p["verification"]["metrics"]
                        if x["id"] == mid), "未测")
        trend.append({
            "id": mid, "name": d.get("cn"), "unit": d.get("unit"),
            "phase": phase_of, "target": d.get("target"),
            "p0": pmap_val.get("Phase 0"), "p1": pmap_val.get("Phase 1"), "p2": pmap_val.get("Phase 2"),
            "p3": pmap_val.get("Phase 3"), "p4": pmap_val.get("Phase 4"),
            "verdict": verdict,
        })

    per_phase = [{"phase": p["phase"], "pass": p["verification"]["pass"], "total": p["n_metrics"]}
                 for p in phases_out]

    meta = {"version": EA.VERSION, "baseline": base_version, "ts": int(time.time()),
            "ts_str": time.strftime("%F %T"), "generated_by": GENERATED_BY,
            "n_phases": len(phases_out), "n_metrics": len(spec_idx)}

    return {
        "meta": meta,
        "phases": phases_out,
        "comparison": {
            "phases": [p["phase"] for p in phases_out],
            "trend": trend,
            "summary": {"per_phase_pass_rate": per_phase,
                        "note": ("trend 每行一个指标 (共 %d 条), p0..p4 列 = 该指标在其归属 phase 的采集值 "
                                 "(非归属 phase 一律 null); verdict = 阈值判定 (达标/未达标/样本不足/未测)。"
                                 % len(trend))},
        },
        "_definition": {   # 路线定义 (phases[0..4] 子集, 供 config/eval/iteration_roadmap.json)
            "schema": "zmax-iteration-roadmap/1",
            "meta": meta,
            "phases": [{"phase": p["phase"], "name": p["name"], "target_metrics": p["target_metrics"],
                        "entry_criteria": p["entry_criteria"], "meta_combo": p["meta_combo"]}
                       for p in phases_out],
        },
    }


# ── Markdown ──────────────────────────────────────────────────────────────
def render_md(data):
    L = []
    A = L.append
    m = data["meta"]
    A("# 产品迭代路线 Phase 0→4 · 迭代验证与对比分析 (基线产品 v%s)" % m["baseline"])
    A("")
    A("生成 `%s` · 由 `%s` 现算 · **零硬编**: 指标名/目标值/归属/采集值全部取真源。" % (m["ts_str"], m["generated_by"]))
    A("")
    cov = data["comparison"]["summary"]["per_phase_pass_rate"]
    A("- phase 数 **%d** · 指标 **%d** 条 · 各阶段达标率: %s" %
      (m["n_phases"], m["n_metrics"],
       " · ".join("%s %d/%d" % (c["phase"], c["pass"], c["total"]) for c in cov)))
    A("")
    for p in data["phases"]:
        v = p["verification"]
        A("## %s · %s (%s)" % (p["phase"], p["name"], p.get("time") or ""))
        A("")
        A("- 阶段标题: %s ｜ 真源 KPI: %s" % (p.get("title") or "-", p.get("kpi") or "-"))
        A("- 主要性能指标 **%d** 条 ｜ 实测判定: 达标 %d · 未达标 %d · 样本不足 %d · 未测 %d"
          % (p["n_metrics"], v["pass"], v["fail"], v["insufficient"], v["unmeasured"]))
        cb, cv = p["vs_baseline"], p["entry"]
        A("- 对比基线: 提升 %d · 持平 %d · 回退 %d ｜ 升级准入: ①零回退=%s ②净提升=%s ③零冲突=%s ⇒ **%s**"
          % (cb["improved"], cb["flat"], cb["regressed"], cv["gate1_zero_regress"], cv["gate2_net_gain"],
             cv["gate3_consistency"], "开闸" if cv["open"] else "未开闸"))
        mc = p["meta_combo"]
        A("- 元任务升级组合: 基线 %d · 本阶段新增 %d · 升级(跨阶段复用) %d" %
          (len(mc["baseline"]), len(mc["added"]), len(mc["upgraded"])))
        if mc["added"]:
            A("  - 新增: " + "、".join("%s %s" % (x["fn_id"], x["name"]) for x in mc["added"]))
        if mc["upgraded"]:
            A("  - 升级: " + "、".join("%s %s" % (x["fn_id"], x["name"]) for x in mc["upgraded"]))
        A("")
        A("| 指标 id | 指标名 | 单位 | 目标 | 采集值 | 判定 | 证据 | 基线 | 对比 |")
        A("|---|---|---|---|---|---|---|---|---|")
        bit = {b["id"]: b for b in p["vs_baseline"]["items"]}
        for r in v["metrics"]:
            b = bit.get(r["id"]) or {}
            A("| `%s` | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                r["id"], r["name"], r["unit"], str(r["target"])[:26],
                ("%.4g" % r["value"]) if isinstance(r["value"], (int, float)) else "未测",
                r["verdict"], r["mode"],
                ("%.4g" % b["baseline"]) if isinstance(b.get("baseline"), (int, float)) else "-",
                b.get("verdict") or "未测"))
        A("")
    A("## 对比分析 (trend: 每指标在其归属 phase 的采集值)")
    A("")
    A("| 指标 id | 指标名 | 单位 | target | P0 | P1 | P2 | P3 | P4 | verdict |")
    A("|---|---|---|---|---|---|---|---|---|---|")
    for t in data["comparison"]["trend"]:
        cells = " | ".join(("%.4g" % t[k]) if isinstance(t[k], (int, float)) else "-"
                            for k in ("p0", "p1", "p2", "p3", "p4"))
        A("| `%s` | %s | %s | %s | %s | %s |" % (t["id"], t["name"], t["unit"] or "", str(t["target"])[:22],
                                                 cells, t["verdict"]))
    A("")
    A("> 未测 = 本机无采集条件或属设计声明 (非实测); 样本不足 = 只报值不判定。逐条原因见 JSON `note` 字段。")
    A("")
    return "\n".join(L) + "\n"


# ── 自检 ──────────────────────────────────────────────────────────────────
def verify(data):
    spec_idx = EP.metric_index()
    import export_meta_doc as E                                                     # noqa: E402
    MT, _ = E.build_meta_tasks()
    fn_all = {m["fn_id"] for m in MT}

    checks = []

    def add(name, ok, detail):
        checks.append((name, ok, detail))

    # (a) 每 phase 指标数 > 0
    bad_a = [p["phase"] for p in data["phases"] if not p["target_metrics"]]
    add("(a) 每 phase 指标数 > 0", not bad_a, ", ".join(bad_a) or "全部 > 0")

    # (b) 每指标能在 perf_spec 找到定义
    miss_b = [t["id"] for p in data["phases"] for t in p["target_metrics"] if t["id"] not in spec_idx]
    add("(b) 每指标都能在 perf_spec 找到定义", not miss_b, ", ".join(miss_b) or "全部命中")

    # (c) 各 phase 指标集合不重不漏, 并为全集
    seen, dup = set(), []
    for p in data["phases"]:
        for t in p["target_metrics"]:
            if t["id"] in seen:
                dup.append(t["id"])
            seen.add(t["id"])
    all_spec = set(spec_idx)
    miss = sorted(all_spec - seen)
    extra = sorted(seen - all_spec)
    add("(c) phase 指标不重不漏, 并为 perf_spec 全集",
        not dup and not miss and not extra,
        "重复 %s · 缺失 %d 条 %s · 越界 %d 条 %s (全集 %d / 覆盖 %d)" %
        (dup or "无", len(miss), miss[:6], len(extra), extra[:6], len(all_spec), len(seen)))

    # (d) 元任务组合里的 fn_id 都能在 build_meta_tasks() 找到
    miss_d = []
    for p in data["phases"]:
        mc = p["meta_combo"]
        for fn in mc["baseline"]:
            if fn not in fn_all:
                miss_d.append(fn)
        for row in (mc["added"] + mc["upgraded"]):
            if row["fn_id"] not in fn_all:
                miss_d.append(row["fn_id"])
    add("(d) 元任务组合 fn_id 均在 build_meta_tasks() 找得到", not miss_d,
        ", ".join(sorted(set(miss_d))) or "全部命中 (共 %d 元任务)" % len(fn_all))

    # (e) 对比分析表行数 == 指标数
    nt = len(data["comparison"]["trend"])
    add("(e) 对比分析 trend 行数 == 指标数", nt == len(all_spec),
        "trend %d 行 / 指标 %d 条" % (nt, len(all_spec)))

    return checks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="自检 (a-e) 并列 PASS/FAIL")
    ap.add_argument("--md", action="store_true", help="只出 Markdown (仍落盘)")
    a = ap.parse_args()

    data = build()

    # 落盘
    _atomic(DEF_OUT, data["_definition"])
    _atomic(MIRROR_DEF, data["_definition"])
    runtime = {k: v for k, v in data.items() if k != "_definition"}
    _atomic(OUT_JSON, runtime)
    md = render_md(data)
    os.makedirs(os.path.dirname(OUT_MD), exist_ok=True)
    with open(OUT_MD, "w", encoding="utf-8") as fh:
        fh.write(md)
    os.makedirs(os.path.dirname(DOC), exist_ok=True)
    with open(DOC, "w", encoding="utf-8") as fh:
        fh.write(md)

    print("路线定义: %s" % os.path.relpath(DEF_OUT, ROOT))
    print("  (镜像): %s" % os.path.relpath(MIRROR_DEF, ROOT))
    print("运行台账: %s" % os.path.relpath(OUT_JSON, ROOT))
    print("报告:     %s" % os.path.relpath(OUT_MD, ROOT))
    print("  (文档): %s" % os.path.relpath(DOC, ROOT))
    m = data["meta"]
    print("phase %d · 指标 %d · 基线 %s · 版本 %s" % (m["n_phases"], m["n_metrics"], m["baseline"], m["version"]))
    for p in data["phases"]:
        v = p["verification"]
        print("  %s %-12s 指标 %2d | 达标 %d 未达标 %d 样本不足 %d 未测 %d | 升/平/退 %d/%d/%d | 准入 %s"
              % (p["phase"], p["name"][:12], p["n_metrics"], v["pass"], v["fail"], v["insufficient"],
                 v["unmeasured"], p["vs_baseline"]["improved"], p["vs_baseline"]["flat"],
                 p["vs_baseline"]["regressed"], "开闸" if p["entry"]["open"] else "未开闸"))
    print("对比分析 trend %d 行" % len(data["comparison"]["trend"]))

    if a.verify:
        print("\n=== --verify 自检 ===")
        checks = verify(data)
        for name, ok, detail in checks:
            print("[%s] %s -> %s" % ("PASS" if ok else "FAIL", name, detail))
        allok = all(ok for _, ok, _ in checks)
        n_pass = sum(1 for _, ok, _ in checks if ok)
        print("自检: %d/%d PASS %s" % (n_pass, len(checks), "✅ 全绿" if allok else "❌ 有 FAIL"))
        return 0 if allok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
