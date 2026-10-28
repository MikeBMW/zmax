#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_analysis.py — 系统评估分析 (基线产品 5.50.735 → 有提升才准升级)。

老倪 2026-10-15: 「在主界面的 评估分析 功能页, 要做系统的评估分析, 当前 5.50.735 版本是基线产品, 以后要从
这个版本评估分析后, 有性能提升才能升级; 在配置中心, 所有的性能指标, 都要科学的与基线版本做对比。」

评测纪律 (与 eval_probes.py 同口径):
  · 指标定义唯一依据 = config/platform/zmax_perf_spec.json (58 条) + 评测补充指标 4 条 (明确标注)
  · 采集口径唯一依据 = tools/eval_probes.py (每条带证据类: 实测/标定·配置/推导/未测)
  · 基线锁 = config/eval/baseline_v<版本>.json (**冻结**; 锁定后不许改, 要改必须写理由 relock)
  · 判定: 阈值达标 (target 里的 ≤/≥) + 基线对比 (提升/持平/回退); 样本不足/未测 ⇒ 不出判定
  · 升级准入 (三条硬闸): ① 零回退 ② 至少 1 项净提升 ③ 全局一致性零冲突。未测项单列, **不算达标**

用法:
  ./gui-venv311/bin/python tools/eval_analysis.py                 # 评估 → 落报告 (zmax_data/eval/eval_report.json)
  ./gui-venv311/bin/python tools/eval_analysis.py --lock          # 首次锁定基线 (当前 = 基线产品)
  ./gui-venv311/bin/python tools/eval_analysis.py --md            # 同时出 Markdown 报告
  ./gui-venv311/bin/python tools/eval_analysis.py --table         # 只打表
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import eval_probes as EP                                                    # noqa: E402

EVAL_DIR = os.path.join(ROOT, "zmax_data", "eval")
REPORT = os.path.join(EVAL_DIR, "eval_report.json")
HISTORY = os.path.join(EVAL_DIR, "eval_history.jsonl")
BASE_DIR = os.path.join(ROOT, "config", "eval")
VERSION = "v5.50.735"                    # 版本号不自主升级 (老倪指定); 基线 = 本版
BASELINE = os.path.join(BASE_DIR, "baseline_%s.json" % VERSION.replace(".", "_"))
DOC = os.path.join(ROOT, "docs", "eval", "评估分析报告_%s.md" % VERSION)

# 证据面板 (老倪点名的四件工具 + 唯一依据帧龄)
EV = {
    "信号分析": (os.path.join(ROOT, "zmax_data", "dataspace", "live.json"), ["n_topic_alive", "lamp_tally"]),
    "3D场景": (os.path.join(ROOT, "zmax_data", "ss_live", "trace_live.json"),
             ["帧", "阶段", "估计误差_mm", "估计抖动_mm每步", "接触概率"]),
    "元任务": (os.path.join(ROOT, "zmax_data", "ss_live", "meta_pred.json"), ["n_meta", "task_id", "trained"]),
    "主参数M": (os.path.join(ROOT, "config", "calib", "zmax_manifold.json"), ["metric", "_updated_at"]),
    "L2物理参数": (os.path.join(ROOT, "zmax_data", "ss_live", "skill_phys.json"), ["skills"]),
}


def _load(p, d=None):
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:                                                        # noqa: BLE001
        return d


def _atomic(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _threshold(target):
    """从 target 文本里抠出阈值与方向: (方向, 值) —— 方向 1=越大越好, -1=越小越好, 0=无阈值"""
    t = str(target or "")
    m = re.search(r"[≤<]\s*([0-9]+(?:\.[0-9]+)?)", t)
    if m:
        return -1, float(m.group(1))
    m = re.search(r"[≥>]\s*([0-9]+(?:\.[0-9]+)?)", t)
    if m:
        return 1, float(m.group(1))
    return 0, None


def verdicts(metric, base_val):
    """出判定: {达标, 基线对比, 说明} —— 样本不足/未测 不出判定。"""
    v, note = metric.get("value"), metric.get("note") or ""
    ex = metric.get("extra") or {}
    dirn, thr = _threshold(metric.get("target"))
    out = {"达标": "", "基线对比": "", "说明": ""}
    if str(metric.get("mode") or "").startswith("设计声明"):
        # 🔴 声明 ≠ 实测: BOM/厂商/设计要求值一律不许当达标 (老倪: 零容忍假数据)
        #    即使声明里带数字, 也只是"设计值", 没量过 ⇒ 达标列写「待现场实测」, 不写「达标」
        out["达标"] = "待现场实测"
        out["基线对比"] = "待现场实测"
        out["说明"] = (note or "")[:180]
        return out
    if v is None:
        out["达标"] = "未测"
        out["基线对比"] = "未测"
        out["说明"] = note or "无采集条件"
        return out
    if ex.get("样本不足"):
        out["达标"] = "样本不足"
        out["基线对比"] = "样本不足"
        out["说明"] = "样本量 %s < 判定所需 ⇒ 只报值 (不拿少样本当结论)" % metric.get("n")
        return out
    if thr is None:
        out["达标"] = "无阈值 (待现场定)"
    else:
        ok = (v >= thr) if dirn > 0 else (v <= thr)
        out["达标"] = "达标" if ok else "不达标"
        out["说明"] = "阈值 %s%s%s" % ("≥" if dirn > 0 else "≤", thr, "" if ok else " · 差距 %.4g" %
                                       (abs(v - thr)))
    if base_val is None:
        out["基线对比"] = "无基线"
    else:
        d = v - float(base_val)
        eps = max(1e-9, abs(float(base_val)) * 0.005)        # 0.5% 容差内算持平
        if abs(d) <= eps:
            out["基线对比"] = "持平"
        else:
            better = (d > 0) if (dirn >= 0) else (d < 0)
            out["基线对比"] = "提升" if better else "回退"
        out["说明"] += " · 基线 %s → 当前 %s (Δ%+.4g)" % (base_val, v, d)
    return out


def evidence_panel():
    out = {}
    for name, (p, keys) in EV.items():
        d = _load(p)
        try:
            age = time.time() - os.path.getmtime(p)
        except OSError:
            age = -1.0
        item = {"唯一依据": os.path.relpath(p, ROOT), "帧龄_s": round(age, 2), "在": bool(d)}
        if isinstance(d, dict):
            for k in keys:
                if k in d:
                    v = d[k]
                    if isinstance(v, dict):
                        v = ("%d 项" % len(v)) if len(v) > 6 else json.dumps(v, ensure_ascii=False)[:120]
                    elif isinstance(v, list):
                        v = v[:6]
                    item[k] = v
        out[name] = item
    return out


def evaluate(lock=False, relock_reason=""):
    res = EP.run_all()
    idx = EP.metric_index()
    base = _load(BASELINE, None)
    rows, n_up, n_same, n_down, n_ok, n_bad, n_unt, n_short, n_wait = [], 0, 0, 0, 0, 0, 0, 0, 0
    for mid, m in res.items():
        b = None
        if isinstance(base, dict) and mid in (base.get("metrics") or {}):
            b = (base["metrics"][mid] or {}).get("value")
        vd = verdicts(m, b)
        row = {"id": mid, "cn": m.get("cn"), "unit": m.get("unit"), "target": m.get("target"),
               "group": m.get("group"), "stage": m.get("stage"), "mode": m.get("mode"),
               "value": m.get("value"), "baseline": b, "达标": vd["达标"], "基线对比": vd["基线对比"],
               "说明": vd["说明"], "src": m.get("src"), "age_s": m.get("age_s"), "n": m.get("n"),
               "how": m.get("how"), "extra": m.get("extra"), "extra_metric": bool(m.get("extra_metric"))}
        rows.append(row)
        if row["达标"] == "未测":
            n_unt += 1
        elif row["达标"] == "待现场实测":
            n_wait += 1
        elif row["达标"] == "样本不足":
            n_short += 1
        elif row["达标"] == "达标":
            n_ok += 1
        elif row["达标"] == "不达标":
            n_bad += 1
        if row["基线对比"] == "提升":
            n_up += 1
        elif row["基线对比"] == "持平":
            n_same += 1
        elif row["基线对比"] == "回退":
            n_down += 1
    consistency = next((r for r in rows if r["id"] == "perf.sys_consistency"), None)
    n_conf = len(((consistency or {}).get("extra") or {}).get("冲突") or []) if consistency else 0
    has_base = isinstance(base, dict) and bool(base.get("metrics"))
    conds = {
        "① 零回退": {"过": n_down == 0, "值": n_down},
        "② 有净提升": {"过": n_up >= 1, "值": n_up},
        "③ 全局一致性零冲突": {"过": n_conf == 0, "值": n_conf},
    }
    allowed = all(c["过"] for c in conds.values())
    reasons = []
    if not has_base:
        allowed = False
        reasons.append("基线未锁定 ⇒ 先跑 --lock 把 5.50.735 锁成基线")
    if n_bad:
        reasons.append("%d 项指标不达标 (阈值口径): %s" % (n_bad, ", ".join(r["id"] for r in rows if r["达标"] == "不达标")[:160]))
    if n_unt:
        reasons.append("%d 项未测 (无采集条件; 不算达标, 升级前须现场采)" % n_unt)
    if n_short:
        reasons.append("%d 项样本不足 (只报值不判定)" % n_short)
    rep = {
        "schema": "zmax.eval/1", "ts": time.time(), "ts_str": time.strftime("%F %T"),
        "version_current": VERSION, "version_baseline": (base or {}).get("version") or "(未锁定)",
        "baseline_locked_at": (base or {}).get("locked_at"),
        "n_metrics": len(rows), "n_measured": len(rows) - n_unt, "n_untested": n_unt,
        "verdicts": {"达标": n_ok, "不达标": n_bad, "样本不足": n_short, "未测": n_unt, "待现场实测": n_wait,
                     "提升": n_up, "持平": n_same, "回退": n_down},
        "gate": {"upgrade_allowed": allowed, "conditions": conds, "reasons": reasons},
        "consistency": {"冲突数": n_conf, "明细": ((consistency or {}).get("extra") or {}).get("冲突") or []},
        "evidence": evidence_panel(),
        "metrics": rows,
    }
    if lock:
        if os.path.exists(BASELINE) and not relock_reason:
            print("⛔ 基线已存在 (%s) —— 基线是**冻结**的, 要改必须 --relock \"理由\"。" % BASELINE)
            return rep
        _atomic(BASELINE, {"schema": "zmax.eval.baseline/1", "version": VERSION,
                           "locked_at": time.strftime("%F %T"), "relock_reason": relock_reason or "",
                           "note": "基线产品锁定: 以后各版本与此对比, 有净提升且零回退才准升级。",
                           "metrics": {r["id"]: {"value": r["value"], "mode": r["mode"], "unit": r["unit"],
                                                "target": r["target"], "cn": r["cn"], "src": r["src"],
                                                "n": r["n"]} for r in rows}})
        print("🔒 基线已锁定: %s (%d 条指标, 其中 %d 条有实测值)" %
              (BASELINE, len(rows), sum(1 for r in rows if r["value"] is not None)))
        # 锁完当次就按新基线重算判定 (否则首轮报告全是"无基线")
        base = _load(BASELINE, None)
        for r in rows:
            bv = ((base or {}).get("metrics") or {}).get(r["id"], {}).get("value")
            r["baseline"] = bv
            m = res[r["id"]]                       # 采集结果本身就带 note/extra/n/target
            vd2 = verdicts(m, bv)
            r.update({"达标": vd2["达标"], "基线对比": vd2["基线对比"], "说明": vd2["说明"]})
        n_up = sum(1 for r in rows if r["基线对比"] == "提升")
        n_same = sum(1 for r in rows if r["基线对比"] == "持平")
        n_down = sum(1 for r in rows if r["基线对比"] == "回退")
        rep.update({"version_baseline": VERSION, "baseline_locked_at": base.get("locked_at")})
        rep["gate"]["conditions"]["① 零回退"]["值"] = n_down
        rep["gate"]["conditions"]["② 有净提升"]["值"] = n_up
        rep["verdicts"].update({"提升": n_up, "持平": n_same, "回退": n_down})
        rep["gate"]["reasons"] = [x for x in rep["gate"]["reasons"] if "基线未锁定" not in x]
        rep["gate"]["upgrade_allowed"] = all(c["过"] for c in rep["gate"]["conditions"].values())
    _atomic(REPORT, rep)
    os.makedirs(EVAL_DIR, exist_ok=True)
    with open(HISTORY, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": rep["ts"], "ts_str": rep["ts_str"], "version": VERSION,
                             "verdicts": rep["verdicts"], "upgrade_allowed": allowed,
                             "n_measured": rep["n_measured"]}, ensure_ascii=False) + "\n")
    return rep


def table(rep, only_measured=False):
    L = []
    L.append("评估分析 · 基线 %s · 当前 %s · 指标 %d (有值 %d / 未测 %d)" %
             (rep["version_baseline"], rep["version_current"], rep["n_metrics"], rep["n_measured"], rep["n_untested"]))
    L.append("判定汇总: %s" % json.dumps(rep["verdicts"], ensure_ascii=False))
    g = rep["gate"]
    L.append("升级准入: %s ｜ %s" % ("✅ 允许" if g["upgrade_allowed"] else "⛔ 不允许",
                                     " ".join("%s=%s" % (k, v["值"]) for k, v in g["conditions"].items())))
    for r in g["reasons"]:
        L.append("   · %s" % r)
    L.append("")
    L.append("%-26s %-11s %-9s %-9s %-8s %-9s %s" % ("指标", "当前", "基线", "达标", "基线对比", "证据", "备注"))
    for row in rep["metrics"]:
        if only_measured and row["value"] is None:
            continue
        L.append("%-26s %-11s %-9s %-8s %-9s %-9s %s" % (
            (row["cn"] or row["id"])[:24], ("-" if row["value"] is None else ("%.4g" % row["value"])),
            ("-" if row["baseline"] is None else ("%.4g" % row["baseline"])),
            row["达标"], row["基线对比"], str(row["mode"])[:9],
            (row["说明"] or "")[:70]))
    return "\n".join(L)


def to_md(rep):
    L = ["# 评估分析报告 · 基线产品 %s" % rep["version_baseline"], "",
         "- 当前版本: **%s** · 基线锁: %s (%s)" % (rep["version_current"], rep["version_baseline"],
                                             rep.get("baseline_locked_at") or "未锁定"),
         "- 指标总数 **%d**, 有采集结果 **%d**, 未测 **%d**" % (rep["n_metrics"], rep["n_measured"], rep["n_untested"]),
         "- 判定: %s" % json.dumps(rep["verdicts"], ensure_ascii=False),
         "- **升级准入: %s**" % ("✅ 允许 (有净提升 + 零回退 + 零一致性冲突)" if rep["gate"]["upgrade_allowed"]
                              else "⛔ 不允许"), ""]
    if rep["gate"]["reasons"]:
        L += ["## 为什么现在不能升级"] + ["- %s" % r for r in rep["gate"]["reasons"]] + [""]
    L += ["## 一、指标对比 (有采集结果的)", "",
          "| 指标 | 分组 | 单位 | 目标 | 基线 %s | 当前 | 达标 | 基线对比 | 采集方式 | 证据唯一依据 |" % rep["version_baseline"],
          "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rep["metrics"]:
        if r["value"] is None:
            continue
        L.append("| %s | %s | %s | %s | %s | **%s** | %s | %s | %s | `%s` |" % (
            r["cn"], (r["group"] or "")[:12], r["unit"] or "", str(r["target"])[:26],
            ("-" if r["baseline"] is None else "%.4g" % r["baseline"]), "%.4g" % r["value"],
            r["达标"], r["基线对比"], r["mode"], os.path.relpath(r["src"], ROOT) if r["src"] else ""))
    L += ["", "## 二、未测指标 (无采集条件 —— 不算达标, 升级前须现场采)", "",
          "| 指标 | 分组 | 目标 | 采集条件 |", "|---|---|---|---|"]
    for r in rep["metrics"]:
        if r["value"] is not None:
            continue
        L.append("| %s | %s | %s | %s |" % (r["cn"], (r["group"] or "")[:12], str(r["target"])[:30],
                                            (r["说明"] or r["how"] or "")[:70]))
    L += ["", "## 三、证据面板 (工具唯一依据帧龄)", "", "| 工具 | 唯一依据 | 帧龄(s) | 关键量 |", "|---|---|---|---|"]
    for k, v in rep["evidence"].items():
        kv = " · ".join("%s=%s" % (kk, str(vv)[:40]) for kk, vv in v.items() if kk not in ("唯一依据", "帧龄_s", "在"))
        L.append("| %s | `%s` | %s | %s |" % (k, v["唯一依据"], v["帧龄_s"], kv))
    L += ["", "## 四、全局数据一致性", "",
          "- 冲突数: **%d**" % rep["consistency"]["冲突数"],
          "- 明细: %s" % (rep["consistency"]["明细"] or "无冲突"), ""]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lock", action="store_true", help="锁定当前为基线产品")
    ap.add_argument("--relock", default="", help="重新锁基线 (必须写理由)")
    ap.add_argument("--md", action="store_true", help="出 Markdown 报告")
    ap.add_argument("--table", action="store_true", help="只打表")
    ap.add_argument("--all", action="store_true", help="表里连未测一起打")
    a = ap.parse_args()
    rep = evaluate(lock=a.lock or bool(a.relock), relock_reason=a.relock)
    if a.md:
        os.makedirs(os.path.dirname(DOC), exist_ok=True)
        with open(DOC, "w", encoding="utf-8") as fh:
            fh.write(to_md(rep))
        print("📄 报告: %s" % DOC)
    print(table(rep, only_measured=not a.all))
    return 0 if rep["gate"]["upgrade_allowed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
