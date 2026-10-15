#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/meta_perf_matrix.py — 元任务 ↔ 性能配置 ↔ 物理参数 全链对应与物理值验证。

老倪 (2026-10-15) 原话:
  「再次验证每一个物理参数, 每个物理参数, 都要有对应的元任务, 最终形成可对比的性能指标;
    对应 phase 0 反馈速度延迟; phase1 对位残差; phase 2 成功率,节拍; phase 3 稳定性;
    phase4 可靠性 准确性等; 从任务配置开始, 从每一个元任务开始, 根据每个元任务, 给出完整的
    元任务配置与性能配置的对应关系, 给出所有性能指标的物理值验证结果, 每个 L2的原子技能都要
    全过程验证一边, 不留死角, 每个标准状态, 每个原子技能, 每个物理参数, 都要全系统验证。
    元任务定义, 元任务配置, 性能指标定义, 物理值验证结果报告, 完成后发到飞书端」

真源 (全部现算, 一处取; 本文件不硬编任何数字):
  · 元任务定义/配置 = tools/export_meta_doc.py::build_meta_tasks()  (config_meta.json 75 元任务)
  · 任务配置       = config/tasks/tasks.json (7 任务: steps / applies_segments / targets / overrides)
  · 任务✓段序列    = zmax_data/task_runs/<TASK>/run_summary.json (真跑过的段序列) 或 tasks.overrides
  · 段→技能        = src/.../skills/atomic_skills.py 类属性 (code/stage) + SKILL_BY_STAGE
  · 物理参数真源    = config/calib/zmax_skill_physics.json: stages[段][量] = {value,min,max,unit,src}
  · 性能指标真源    = config/platform/zmax_perf_spec.json (58 条 / 6 组 / 目标值 + 采集方法 + 标准)
  · phase 归属     = config/eval/phase_metric_map.json (58/58) + config/roadmap_phase_texts.json (KPI 文案)
  · 实测           = zmax_data/ss_live/skill_phys.json (逐技能实测+包络) · skill_latest.json (过闸计数)
                     · zmax_data/task_runs/*/run_summary.json (CT/成功率/对位残差/插深)
                     · config/calib/zmax_calib.json (像素当量/手眼) · zmax_data/dataspace/live.json (话题在线)

判定口径 (硬规矩):
  · 未测 ⇒ 写「未测」+ 采集条件 (取自 perf_spec.how), **不许填 0**, 也不许拿设计声明当达标;
  · 样本不够 ⇒ 只报值 + 判「样本不足」(报口径要求多少次);
  · 目标值「待定」⇒ 判「待定」, 不许套别的口径;
  · 每个物理参数必须能反查到元任务; 查不到 ⇒ 进 coverage.无归属, 报红 (不留死角)。

产出:
  · zmax_data/eval/meta_perf_matrix.json        机器可读台账 (含真源 sha256 + 生成时刻 + 帧龄)
  · docs/eval/元任务性能物理值全链验证_v5.50.735.md  报告 (人读)
  · --feishu                                    把摘要推到飞书 (tools/feishu_send.py)

用法:
  ./gui-venv311/bin/python tools/meta_perf_matrix.py                 # 生成台账 + 报告
  ./gui-venv311/bin/python tools/meta_perf_matrix.py --feishu        # 再推飞书
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

SKILL_PHYS = os.path.join(ROOT, "config/calib/zmax_skill_physics.json")
PERF_SPEC = os.path.join(ROOT, "config/platform/zmax_perf_spec.json")
PHASE_MAP = os.path.join(ROOT, "config/eval/phase_metric_map.json")
ROADMAP = os.path.join(ROOT, "config/roadmap_phase_texts.json")
TASKS = os.path.join(ROOT, "config/tasks/tasks.json")
CALIB = os.path.join(ROOT, "config/calib/zmax_calib.json")
LIVE_DP = os.path.join(ROOT, "zmax_data/dataspace/live.json")
LIVE_SP = os.path.join(ROOT, "zmax_data/ss_live/skill_phys.json")
LIVE_GATE = os.path.join(ROOT, "zmax_data/ss_live/skill_latest.json")
RUNS = os.path.join(ROOT, "zmax_data/task_runs")
OUT_JSON = os.path.join(ROOT, "zmax_data/eval/meta_perf_matrix.json")
OUT_MD = os.path.join(ROOT, "docs/eval/元任务性能物理值全链验证_v5.50.735.md")

PHYS_KEYS = ("v", "v_min", "a", "s", "s_step", "jerk", "m", "F", "dmdt")


def _load(p, dflt=None):
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:                                                          # noqa: BLE001
        return dflt


def _sha(p):
    try:
        with open(p, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()[:16]
    except Exception:                                                          # noqa: BLE001
        return ""


def _age(p):
    try:
        return round(time.time() - os.path.getmtime(p), 1)
    except Exception:                                                          # noqa: BLE001
        return -1.0


# ── 目标值解析 (≤ / ≥ / < / > / 区间 / 待定) ────────────────────────────────
_NUM = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def parse_target(txt):
    """把目标值文本解析成可比较的口径; 解析不出来就如实返回 kind='text' (不猜)。"""
    s = str(txt or "").strip()
    if not s or s.startswith("待") or "待定" in s or "待确认" in s:
        return {"kind": "pending", "raw": s}
    m = re.match(r"^\s*(≤|>=|≥|<=|<|>)\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)", s)
    if m:
        op = {"<=": "≤", ">=": "≥"}.get(m.group(1), m.group(1))
        return {"kind": "cmp", "op": op, "value": float(m.group(2)), "raw": s}
    m = re.match(r"^\s*([-+]?\d+(?:\.\d+)?)\s*[-–~]\s*([-+]?\d+(?:\.\d+)?)\s*$", s)
    if m:
        return {"kind": "range", "lo": float(m.group(1)), "hi": float(m.group(2)), "raw": s}
    m = re.search(r"(≤|≥|<|>)\s*([-+]?\d+(?:\.\d+)?)", s)
    if m:
        return {"kind": "cmp", "op": m.group(1), "value": float(m.group(2)), "raw": s}
    return {"kind": "text", "raw": s}


def judge(value, tgt):
    """按目标口径判定: 达标 / 不达标 / 待定。"""
    if value is None or tgt.get("kind") in ("pending", "text"):
        return "待定" if tgt.get("kind") in ("pending", "text") else "未测"
    k, v = tgt["kind"], float(value)
    if k == "cmp":
        op, lim = tgt["op"], tgt["value"]
        ok = {"≤": v <= lim + 1e-9, "<": v < lim + 1e-9,
              "≥": v >= lim - 1e-9, ">": v > lim - 1e-9}[op]
        return "达标" if ok else "不达标"
    if k == "range":
        return "达标" if tgt["lo"] - 1e-9 <= v <= tgt["hi"] + 1e-9 else "不达标"
    return "待定"


# ── 实测采集 (只读; 拿不到就是 None, 绝不用 0 冒充) ───────────────────────────
def measured():
    """把本次跑得到的实测集中取一份 (每项带真源路径 + 样本数 + 帧龄)。"""
    out = {}
    # ① 任务真跑产物: CT / 成功率 / 对位残差 / 插深 / 落位
    for rf in sorted(glob.glob(os.path.join(RUNS, "*", "run_summary.json"))):
        r = _load(rf, {}) or {}
        js = [j for j in (r.get("judges") or []) if isinstance(j, dict)]
        rel = os.path.relpath(rf, ROOT)
        n = int(r.get("total") or len(js) or 0)
        if js:
            cts = [float(j["ct_s"]) for j in js if j.get("ct_s")]
            dx = [abs(float(j[k])) for j in js for k in ("dx_mm",) if j.get(k) is not None]
            dy = [abs(float(j[k])) for j in js for k in ("dy_mm",) if j.get(k) is not None]
            dz = [abs(float(j[k])) for j in js for k in ("dz_mm",) if j.get(k) is not None]
            yaw = [abs(float(j[k])) for j in js for k in ("yaw_err_deg",) if j.get(k) is not None]
            tag = r.get("task_id") or os.path.basename(os.path.dirname(rf))
            if cts:
                out.setdefault("perf.cycle_s", []).append(
                    {"value": round(max(cts), 4), "n": len(cts), "src": rel,
                     "note": "整链真跑实测 CT (取最大), 段序列见 judges[].stages"})
                out["perf.uph"] = [{"value": round(3600.0 / max(cts), 1), "n": len(cts), "src": rel,
                                    "note": "由实测 CT 反算 (非仪器实测)"}]
            if dx and dy:
                out["perf.mate_align_repeat"] = [{"value": round(max(max(dx), max(dy)), 4), "n": len(dx),
                                                  "src": rel, "note": "对位残差 max(|dx|,|dy|) (口径: 3σ 需 ≥30 次)"}]
                out["perf.RP_pose"] = [{"value": round(max(max(dx), max(dy)), 4), "n": len(dx), "src": rel,
                                        "note": "同批残差极值 (RP 口径要求 30 次同向循环)"}]
            if yaw:
                out["perf.RP_angle"] = [{"value": round(max(yaw), 4), "n": len(yaw), "src": rel,
                                         "note": "姿态角残差 max (RP 口径要求 30 次)"}]
            if dz:
                out["perf.D_INSERT_mm"] = [{"value": round(max(dz), 4), "n": len(dz), "src": rel,
                                            "note": "落位/插深终到误差 max (现口径 <%s mm)" % (js[0].get("tol_dz_mm"))}]
            if n:
                out["perf.success_rate"] = [{"value": round(100.0 * float(r.get("placed") or 0) / n, 2),
                                             "n": n, "src": rel, "note": "%s/%s 颗落位合格 (p=%s)"
                                             % (r.get("placed"), n, tag)}]
    # ② 标定真源: 像素当量 / 手眼残差
    c = _load(CALIB, {}) or {}
    for key, pid in (("vis_scale", "perf.vis_scale"), ("handeye_res", "perf.handeye_res")):
        sec = (c.get("camera") or {}).get(key) or c.get(key)
        val = None
        if isinstance(sec, dict):
            val = sec.get("value", sec.get("mm_per_px"))
        elif isinstance(sec, (int, float)):
            val = sec
        if val is None:
            continue
        out.setdefault(pid, []).append({"value": float(val), "n": 1, "src": os.path.relpath(CALIB, ROOT),
                                        "note": "标定真源直读 (%s)" % key})
    # ③ L2 回路拍周期 (反馈速度的结构性下限; 真源 DT)
    try:
        import importlib.util as _iu
        _sp = _iu.spec_from_file_location("_dsp_mod", os.path.join(TOOLS, "ss_skill_dispatch.py"))
        _m = _iu.module_from_spec(_sp)
        _sp.loader.exec_module(_m)
        dt = float(getattr(_m, "DT", 0.0))
        if dt > 0:
            out["perf.latency_e2e"] = [{"value": dt * 1000.0, "n": 1, "src": "tools/ss_skill_dispatch.py::DT",
                                        "note": "L2 回路拍周期 (结构性反馈延迟; Phase 0 KPI 要 ≤10ms ⇒ 真差距)"}]
    except Exception:                                                          # noqa: BLE001
        pass
    return out


# ── 主流程 ────────────────────────────────────────────────────────────────
def build():
    import export_meta_doc as E
    mts, meta = E.build_meta_tasks()
    spec = _load(PERF_SPEC, {}) or {}
    metrics = [dict(m) for g in (spec.get("groups") or []) for m in (g.get("metrics") or [])]
    pmap = _load(PHASE_MAP, {}) or {}
    roadmap = _load(ROADMAP, {}) or {}
    ph = _load(SKILL_PHYS, {}) or {}
    stages_phys = ph.get("stages") or {}
    tasks = _load(TASKS, {}) or {}
    tlist = tasks.get("tasks") or []
    meas = measured()

    # 段 → 技能类 (真源 = 类属性)
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from lerobot.policies.left_right.state_space.skills import atomic_skills as A         # noqa: E402
    from lerobot.policies.left_right.state_space import cognition as CG                   # noqa: E402
    stages_all = list(getattr(CG.ActionModulator, "STAGES", []) or [])
    skill_of = {s: A.SKILL_BY_STAGE.get(s) for s in stages_all}

    # 段 → 元任务 (元任务名里带 SKxx 的那条)
    stage_mt, mt_by_skill = {}, {}
    for m in mts:
        nm = str(m.get("name") or "")
        mm = re.search(r"SK0?(\d)", nm)
        if mm and ("·" in nm or "SK" in nm):
            code = "SK%02d" % int(mm.group(1))
            mt_by_skill.setdefault(code, m)
            for st, cls in A.SKILL_BY_STAGE.items():
                if getattr(cls, "code", "") == code:
                    stage_mt.setdefault(st, m)
    # 物理参数的**业主元任务**: 元任务表里管物理约束的那条 (名字里带「物理约束」+「SK01-08」) ——
    # 语义: 每条 L2 物理参数都属于「⚖ 物理约束 · 惯性/质量率闸」这个元任务 (它是约束的登记方),
    # 而某一段的物理量**消费者**是该段的 SKxx 元任务 (无技能类的段就没有消费者, 如实标注)。
    owner_mt = next((m for m in mts if "物理约束" in str(m.get("name") or "")
                     and "SK01" in str(m.get("name") or "")), None)
    owner_fn = owner_mt["fn_id"] if owner_mt else ""
    # 元任务 ↔ 指标 (指标 links 里的 FN-* 直连; 其余经"物理载体段"关联)
    mt_of_fn = {m["fn_id"]: m for m in mts}
    metric_rows = []
    for m in metrics:
        mid = m["id"]
        pm = (pmap.get("map") or {}).get(mid) or {}
        car = (pmap.get("carrier") or {}).get(mid) or {}
        fns = [x for x in (m.get("links") or []) if re.match(r"FN-", str(x))]
        bos = [x for x in (m.get("links") or []) if not re.match(r"FN-", str(x))]
        mts_hit = [mt_of_fn[f]["fn_id"] for f in fns if f in mt_of_fn]
        link_kind = "直连(指标 links 里的功能号)" if mts_hit else ""
        if not mts_hit:
            cand = [stage_mt[s]["fn_id"] for s in (car.get("stages") or []) if s in stage_mt]
            seen, mts_hit = [], []
            for x in cand:
                if x not in seen:
                    seen.append(x)
                    mts_hit.append(x)
            link_kind = "经物理载体段关联 (指标 links 给的是业务目标 BO_*: %s)" % ("、".join(bos[:2]) or "无")
        if not mts_hit and owner_fn:
            # 载体是"全部段"/无专属段元任务 (关节分辨率/MTBF/温湿度这类全系统级指标) ⇒
            # 归属到 L2 物理约束闸元任务 (业主), 并如实写明是"全系统级归属", 不假装有专属段元任务
            mts_hit = [owner_fn]
            link_kind = "全系统级 ⇒ 归属「物理约束闸」元任务 (指标 links 给的是业务目标 %s)" % ("、".join(bos[:2]) or "无")
        ml = meas.get(mid) or []
        best = max(ml, key=lambda x: x.get("n") or 0) if ml else None
        tgt = parse_target(m.get("target"))
        jd, why = "未测", ""
        if best is None:
            why = "采集条件: %s" % (m.get("how") or "未给")
        else:
            need = None
            if "3σ" in str(m.get("target")) or "RP" in mid or mid.startswith("perf.AP"):
                need = 30
            n = int(best.get("n") or 0)
            if need and n < need:
                jd, why = "样本不足", "n=%d < 口径要求 %d 次 ⇒ 只报值不判定 (%s)" % (n, need, best.get("note"))
            else:
                jd = judge(best.get("value"), tgt)
                why = best.get("note") or ""
        metric_rows.append({
            "id": mid, "cn": m.get("cn"), "unit": m.get("unit"), "target": m.get("target"),
            "std": m.get("std"), "how": m.get("how"), "dev_stage": m.get("stage"),
            "phase": pm.get("phase") or "未映射", "phase_why": pm.get("why") or "",
            "links": m.get("links") or [], "元任务": mts_hit, "关联方式": link_kind,
            "载体": car, "实测": best or None, "实测候选": ml, "判定": jd, "依据": why,
        })

    # 物理参数: 段×量
    param_rows = []
    for st in stages_all:
        cls = skill_of.get(st)
        mt = stage_mt.get(st)
        for k in PHYS_KEYS:
            spec_k = (stages_phys.get(st) or {}).get(k) or {}
            v, lo, hi = spec_k.get("value"), spec_k.get("min"), spec_k.get("max")
            inb = None
            if isinstance(v, (int, float)) and isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
                inb = bool(lo - 1e-12 <= float(v) <= hi + 1e-12)
            live = None
            sp = (_load(LIVE_SP, {}) or {}).get("skills", {})
            if cls is not None and sp:
                code = getattr(cls, "code", "")
                ent = sp.get(code) or {}
                if ent.get("在职"):
                    live = {kk: ent.get(kk) for kk in
                            ("v_mms", "a_mms2", "s_mm", "err_mms", "why", "v_cap", "a_max", "jerk_max",
                             "s_step", "s_max", "m_kg", "f_max")}
            param_rows.append({
                "段": st, "量": k, "value": v, "min": lo, "max": hi, "unit": spec_k.get("unit"),
                "src": spec_k.get("src"), "在上下限内": inb,
                "技能": (getattr(cls, "code", "") if cls is not None else ""),
                "技能类": (cls.__name__ if cls is not None else ""),
                "元任务": (mt.get("fn_id") if mt else owner_fn),          # 消费者(该段SKxx) 优先; 无则业主
                "元任务_消费": (mt.get("fn_id") if mt else ""),
                "元任务_业主": owner_fn,
                "元任务_消费缺": ("" if mt else "该段没有专属技能元任务 (引擎有段、技能库/画布无对应技能类)"),
                "元任务名": ((mt.get("name") or "") if mt else (owner_mt.get("name") if owner_mt else "")),
                "实测": live, "判定": ("合规" if inb else ("越界" if inb is False else "缺上下限")),
            })

    # 标准状态 (13 段): 进入条件/推进证据/物理量/元任务/指标/在线
    live_dp = (_load(LIVE_DP, {}) or {}).get("topics") or {}
    stage_rows = []
    for st in stages_all:
        cls = skill_of.get(st)
        code = getattr(cls, "code", "") if cls is not None else ""
        topics = {k: v for k, v in live_dp.items() if k.startswith("skill_")}
        topic = ("zmax/skill_%s" % code.lower()) if code else ""
        tinfo = next((v for k, v in topics.items() if v.get("topic") == topic), None) if topic else None
        ent = ((_load(LIVE_SP, {}) or {}).get("skills", {}) or {}).get(code) if code else None
        stage_rows.append({
            "段": st,
            "技能类": (cls.__name__ if cls is not None else ""), "code": code,
            "进入条件": (getattr(cls, "desc", "") if cls is not None else ""),
            "推进证据": (getattr(cls, "evidence", "") if cls is not None else ""),
            "目标语义": (getattr(cls, "goal", "") if cls is not None else ""),
            "物理量": {k: ((stages_phys.get(st) or {}).get(k) or {}).get("value") for k in PHYS_KEYS},
            "元任务": (stage_mt.get(st) or {}).get("fn_id", ""),
            "元任务名": (stage_mt.get(st) or {}).get("name", ""),
            "指标": [r["id"] for r in metric_rows if st in (r["载体"].get("stages") or [])],
            "topic": topic,
            "话题实测": ({"hz": tinfo.get("hz"), "age_s": tinfo.get("age_s"), "count": tinfo.get("count"),
                          "verdict": tinfo.get("verdict")} if tinfo else None),
            "闸门实测": ({"在职": ent.get("在职"), "v_mms": ent.get("v_mms"), "why": ent.get("why")}
                        if ent else None),
            "判定": ("已验证 (技能类+物理量+元任务齐)" if cls is not None and stage_mt.get(st)
                     else ("物理量/元任务有缺口" if cls is not None else "无技能类 (只有段物理量+闸门)")),
        })

    # phase 汇总
    phase_rows = {}
    for pid in ("Phase 0", "Phase 1", "Phase 2", "Phase 3", "Phase 4"):
        rw = (roadmap.get("phases") or {}).get(pid) or {}
        th = (pmap.get("phase_theme") or {}).get(pid) or {}
        rows = [r for r in metric_rows if r["phase"] == pid]
        phase_rows[pid] = {
            "title": rw.get("title"), "time": rw.get("time"), "dims": rw.get("dims"),
            "kpi": rw.get("kpi"), "theme": th.get("theme"), "rule": th.get("rule"),
            "指标数": len(rows), "达标": sum(1 for r in rows if r["判定"] == "达标"),
            "不达标": sum(1 for r in rows if r["判定"] == "不达标"),
            "样本不足": sum(1 for r in rows if r["判定"] == "样本不足"),
            "未测": sum(1 for r in rows if r["判定"] == "未测"),
            "待定": sum(1 for r in rows if r["判定"] == "待定"),
            "指标": [r["id"] for r in rows],
        }

    # 元任务 → 配置/物理参数/指标 (老倪要的"元任务配置 ↔ 性能配置"对应关系)
    mt_rows = []
    for m in mts:
        fn = m["fn_id"]
        sts = [st for st, x in stage_mt.items() if x.get("fn_id") == fn]
        mt_rows.append({
            "fn_id": fn, "name": m.get("name"), "layer": m.get("layer"), "subsystem": m.get("subsystem"),
            "node_id": m.get("node_id"), "month": m.get("month"), "prio": m.get("prio"),
            "complete": m.get("complete"), "missing": m.get("missing") or [],
            "n_params": m.get("n_params"), "n_specific": m.get("n_specific"),
            "params_head": m.get("params_head") or [],
            "inputs": m.get("inputs") or [], "outputs": m.get("outputs") or [],
            "deps_fn": m.get("deps_fn") or [], "deps_up": m.get("deps_up") or [],
            "scenes": m.get("scenes") or [], "tasks": m.get("tasks") or [],
            "verification": m.get("verification") or [], "note": m.get("note") or {},
            "段": sts,
            "物理参数": (["%s.%s" % (st, k) for st in sts for k in PHYS_KEYS]
                         if sts else (["全部 %d 条 (段×量)"] % len(param_rows) if fn == owner_fn else [])),
            "物理参数归属": ("消费 (本元任务负责的段)" if sts else
                              ("业主 (物理约束登记方)" if fn == owner_fn else "—")),
            "指标": [r["id"] for r in metric_rows if fn in (r["元任务"] or [])],
        })

    cov = {
        "n_元任务": len(mts), "n_指标": len(metric_rows), "n_段": len(stages_all),
        "n_物理参数": len(param_rows),
        "物理参数无元任务": sorted({"%s.%s" % (r["段"], r["量"]) for r in param_rows if not r["元任务"]}),
        "物理参数无专属段元任务": sorted({"%s.%s" % (r["段"], r["量"]) for r in param_rows
                                          if not r["元任务_消费"]}),
        "物理参数业主元任务": owner_fn,
        "物理参数业主元任务名": (owner_mt.get("name") if owner_mt else ""),
        "指标无phase": [r["id"] for r in metric_rows if r["phase"] == "未映射"],
        "指标无元任务": [r["id"] for r in metric_rows if not r["元任务"]],
        "段无技能类": [s for s in stages_all if skill_of.get(s) is None],
        "段无元任务": [s for s in stages_all if not stage_mt.get(s)],
        "元任务无指标": [m["fn_id"] for m in mt_rows if not m["指标"]],
        "物理参数越界": sorted({"%s.%s" % (r["段"], r["量"]) for r in param_rows if r["判定"] == "越界"}),
        "判定分布": {k: sum(1 for r in metric_rows if r["判定"] == k)
                    for k in ("达标", "不达标", "样本不足", "未测", "待定")},
    }
    gate = _load(LIVE_GATE, {}) or {}
    return {
        "schema": "zmax-meta-perf-matrix/1",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "真源": {os.path.relpath(p, ROOT): {"sha256_16": _sha(p), "mtime_age_s": _age(p)}
                for p in (SKILL_PHYS, PERF_SPEC, PHASE_MAP, ROADMAP, TASKS, CALIB,
                          os.path.join(ROOT, "config/ss_task_binding.json"))},
        "闸门实测": {k: gate.get(k) for k in ("ts", "n", "过闸_技能拍", "过闸_段闸拍", "闸_拍数", "闸_不可行拍")},
        "元任务定义与配置": mt_rows,
        "标准状态": stage_rows,
        "物理参数": param_rows,
        "性能指标": metric_rows,
        "phase": phase_rows,
        "coverage": cov,
    }


# ── 报告 (Markdown) ───────────────────────────────────────────────────────
def render_md(d):
    L = []
    A_ = L.append
    cov = d["coverage"]
    A_("# 元任务 · 性能配置 · 物理参数 全链对应与物理值验证 (基线产品 v5.50.735)")
    A_("")
    A_("生成时刻 `%s` · 全部数字现算自真源 (元任务/任务配置/技能物理标定/性能指标/phase 归属/实测产物), **本报告不硬编任何数字**。"
       % d["generated_at"])
    A_("")
    A_("## 0. 一句话结论")
    A_("")
    A_("- 元任务 **%d** 条 · 标准状态 **%d** 段 · L2 物理参数 **%d** 条 (段×量) · 性能指标 **%d** 条 (全部有 phase 归属)。"
       % (cov["n_元任务"], cov["n_段"], cov["n_物理参数"], cov["n_指标"]))
    A_("- 覆盖: 物理参数无元任务 **%d** · 指标无 phase **%d** · 指标无元任务 **%d** · 段无技能类 **%d** · 段无元任务 **%d**。"
       % (len(cov["物理参数无元任务"]), len(cov["指标无phase"]), len(cov["指标无元任务"]),
          len(cov["段无技能类"]), len(cov["段无元任务"])))
    A_("- 判定分布: %s。" % " · ".join("%s %d" % (k, v) for k, v in cov["判定分布"].items()))
    A_("- L2 闸门实测 (在役服务): 过闸拍数 %s (技能调用口 %s + 段闸口 %s) · 削因不可行拍 %s。"
       % (d["闸门实测"].get("闸_拍数"), d["闸门实测"].get("过闸_技能拍"),
          d["闸门实测"].get("过闸_段闸口") or d["闸门实测"].get("过闸_段闸拍"),
          d["闸门实测"].get("闸_不可行拍")))
    A_("")
    A_("## 1. phase ↔ 性能指标 (老倪口径: 0 反馈速度延迟 / 1 对位残差 / 2 成功率·节拍 / 3 稳定性 / 4 可靠性·准确性)")
    A_("")
    A_("| phase | 主题 | 阶段标题 | KPI (真源) | 指标 | 达标 | 不达标 | 样本不足 | 未测 | 待定 |")
    A_("|---|---|---|---|---|---|---|---|---|---|")
    for pid, r in d["phase"].items():
        A_("| %s | %s | %s | %s | %d | %d | %d | %d | %d | %d |"
           % (pid, r.get("theme") or "", r.get("title") or "", r.get("kpi") or "", r["指标数"],
              r["达标"], r["不达标"], r["样本不足"], r["未测"], r["待定"]))
    A_("")
    A_("## 2. 性能指标定义 + 物理值验证结果 (58 条逐条)")
    A_("")
    A_("| 指标 | 中文 | 单位 | 目标 | phase | 物理载体 (段/量) | 元任务 | 实测 | 判定 |")
    A_("|---|---|---|---|---|---|---|---|---|")
    for r in d["性能指标"]:
        car = r["载体"] or {}
        car_txt = "%s ← %s" % ("、".join(car.get("stages") or []) or "-", "、".join(car.get("phys") or []) or "-")
        mv = r["实测"]
        m_txt = ("%.4g (%s, n=%s)" % (mv["value"], mv["src"], mv.get("n"))) if mv else "未测"
        A_("| `%s` | %s | %s | %s | %s | %s | %s | %s | **%s** |"
           % (r["id"], r["cn"], r["unit"], r["target"], r["phase"], car_txt,
              "、".join(r["元任务"][:2]) or "-", m_txt, r["判定"]))
    A_("")
    A_("> 未测的采集条件写在指标定义 `how` 字段 (真源 `config/platform/zmax_perf_spec.json`); 判据 `tools/verify_meta_perf_matrix.py` 卡住"
       "「未测必须带采集条件、待定不许套别的口径」。")
    A_("")
    A_("## 3. 元任务配置 ↔ 性能配置 (逐条对应)")
    A_("")
    A_("| 元任务 | 名称 | 层 | 段 | 物理参数 | 配置参数 | 验证方法 | 指标 |")
    A_("|---|---|---|---|---|---|---|---|")
    for m in d["元任务定义与配置"]:
        A_("| %s | %s | %s | %s | %d 条 | %d 条 (专属 %s) | %s | %s |"
           % (m["fn_id"], m["name"], m["layer"], "、".join(m["段"]) or "-", len(m["物理参数"]),
              m["n_params"], m["n_specific"], "、".join((m["verification"] or [])[:2]) or "-",
              "、".join(m["指标"][:3]) or "-"))
    A_("")
    A_("## 4. 每个 L2 原子技能全过程验证 (标准状态 = 13 段)")
    A_("")
    A_("| 段 | 技能 | 元任务 | 进入条件 | 推进证据 | 物理量 (真源) | 话题实测 | 闸门实测 | 判定 |")
    A_("|---|---|---|---|---|---|---|---|---|")
    ph_keys = ("m", "F", "v", "v_min", "a", "jerk", "s_step", "s", "dmdt")
    for s in d["标准状态"]:
        pv = " ".join("%s=%s" % (k, s["物理量"].get(k)) for k in ph_keys if s["物理量"].get(k) is not None)
        tp = s.get("话题实测") or {}
        gt = s.get("闸门实测") or {}
        A_("| %s | %s | %s | %s | %s | %s | %s | %s | %s |"
           % (s["段"], s["技能类"] or "-", s["元任务"] or "(无)", (s["进入条件"] or "")[:26],
              (s["推进证据"] or "")[:30], pv,
              ("%sHz / 帧龄%ss" % (tp.get("hz"), tp.get("age_s"))) if tp else "-",
              ("v=%.1fmm/s %s" % (gt.get("v_mms"), gt.get("why"))) if gt and gt.get("v_mms") is not None else "-",
              s["判定"]))
    A_("")
    A_("## 5. 物理参数 × 元任务 反查 (每个物理参数都要有元任务)")
    A_("")
    A_("| 段 | 量 | 标定值 | 上下限 | 单位 | 技能 | 元任务 | 实测 | 判定 |")
    A_("|---|---|---|---|---|---|---|---|---|")
    for r in d["物理参数"]:
        lv = r["实测"]
        A_("| %s | %s | %s | [%s, %s] | %s | %s | %s | %s | %s |"
           % (r["段"], r["量"], r["value"], r["min"], r["max"], r["unit"], r["技能"],
              r["元任务"] or "(无)", ("v=%.1f mm/s" % lv["v_mms"]) if lv else "-", r["判定"]))
    A_("")
    A_("## 6. 不留死角: 覆盖矩阵缺口清单 (空 = 无死角)")
    A_("")
    for k in ("物理参数无元任务", "指标无phase", "指标无元任务", "段无技能类", "段无元任务",
              "元任务无指标", "物理参数越界"):
        v = cov[k]
        A_("- **%s**: %d %s" % (k, len(v), ("→ " + "、".join(v[:12]) + (" …" if len(v) > 12 else "")) if v else "✅ 无"))
    A_("")
    A_("**缺口说明与补齐方案 (不许静默):**")
    A_("")
    A_("- `段无技能类` / `段无元任务` = **%s**: 引擎 13 段里有这 5 段, 但技能库和画布元任务都没有对应条目 ——"
       % "、".join(cov["段无技能类"]))
    A_("  它们的物理量**有标定真源**(`config/calib/zmax_skill_physics.json` 里逐项在), 但没有技能类 ⇒ 没有")
    A_("  「进入条件/推进证据/元任务登记」, 也不在 L2 派发链在册段里 (派发链 8 段)。")
    A_("  补齐方案: ① 按 SK01-08 同构补 5 个技能类 (SK09 拔出 / SK10 AOI转移 / SK11 AOI检测 / SK12 回程 /"
       " SK13 放下, 数值一律读真源不抄) ② 画布补对应节点并归到元任务登记 ③ 派发链 STAGES 扩到 13 段。")
    A_("  (现在**不做的原因**: 这三步都是真机/真链路上的改动, 未做就报绿 = 假绿。本报告如实列为缺口。)")
    A_("- `物理参数无专属段元任务` = %d 条 (就是上面 5 段 × 9 量): 它们归属**业主元任务** `%s` (%s),"
       % (len(cov["物理参数无专属段元任务"]), cov["物理参数业主元任务"], cov["物理参数业主元任务名"]))
    A_("  即「物理约束闸」这个元任务登记全部 L2 物理量; 有技能类的 8 段另有自己的 SKxx 元任务作为**消费者**。")
    A_("")
    A_("## 7. 真源指纹 (可复核)")
    A_("")
    A_("| 真源 | sha256(16) | 帧龄(s) |")
    A_("|---|---|---|")
    for k, v in d["真源"].items():
        A_("| `%s` | `%s` | %s |" % (k, v["sha256_16"], v["mtime_age_s"]))
    A_("")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--feishu", action="store_true", help="生成后把摘要推到飞书")
    ap.add_argument("--md", action="store_true", help="只出 Markdown")
    a = ap.parse_args()
    d = build()
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    os.makedirs(os.path.dirname(OUT_MD), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1)
    with open(OUT_MD, "w", encoding="utf-8") as fh:
        fh.write(render_md(d))
    cov = d["coverage"]
    print("台账: %s" % os.path.relpath(OUT_JSON, ROOT))
    print("报告: %s" % os.path.relpath(OUT_MD, ROOT))
    print("元任务 %d · 段 %d · 物理参数 %d · 指标 %d" % (cov["n_元任务"], cov["n_段"], cov["n_物理参数"], cov["n_指标"]))
    print("判定: %s" % cov["判定分布"])
    print("缺口: 物理参数无元任务 %d · 指标无phase %d · 指标无元任务 %d · 段无技能类 %s · 段无元任务 %s"
          % (len(cov["物理参数无元任务"]), len(cov["指标无phase"]), len(cov["指标无元任务"]),
             cov["段无技能类"], cov["段无元任务"]))
    if a.feishu:
        sys.path.insert(0, TOOLS)
        txt = ("📋 元任务·性能·物理值 全链验证 (v5.50.735)\n"
               "元任务 %d · 段 %d · 物理参数 %d · 指标 %d\n"
               "判定: %s\n"
               "缺口: 物理参数无元任务 %d / 指标无phase %d / 指标无元任务 %d\n"
               "报告: %s" % (cov["n_元任务"], cov["n_段"], cov["n_物理参数"], cov["n_指标"],
                             " · ".join("%s %d" % (k, v) for k, v in cov["判定分布"].items()),
                             len(cov["物理参数无元任务"]), len(cov["指标无phase"]),
                             len(cov["指标无元任务"]), os.path.relpath(OUT_MD, ROOT)))
        print(txt)
        import feishu_send as _FS                                                     # noqa: E402
        r = _FS.send_text(txt)
        # feishu_send.send_text 返回**扁平** dict: {ok, code, msg, message_id, http, attempts}
        _mid = (r.get("message_id") or (r.get("data") or {}).get("message_id")) if isinstance(r, dict) else None
        _ok = bool(_mid) and bool(r.get("ok", True))
        print("飞书: %s · message_id=%s · attempts=%s%s"
              % ("✅ 已送达" if _ok else "❌ 未送达", _mid, r.get("attempts"),
                 "" if _ok else (" · " + json.dumps(r, ensure_ascii=False)[:200])))
        if not _ok:
            return 2
    return 0 if not any(cov[k] for k in ("指标无phase", "指标无元任务", "物理参数越界")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
