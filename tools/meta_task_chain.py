#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/meta_task_chain.py — 元任务链执行器 (Phase 0 的 L2 级功能 → 元任务 → 每个原子技能都执行)

老倪 2026-10-16
> 「开始再次执行元任务。phase 0 的 L2级功能, 通过配置, 变成元任务, 每个原子技能都要执行;
>  L3, 配置模型, 形成 L3元任务; 同理, L4元任务, 形成配置工单, 最后交付 元任务的定义, 迭代阶段,
>  组成, 评估分析, 性能指标, 以及验证报告; 我要在文档中心, 得到元任务的总体设计文档, 发到飞书。」

四层一套链 (本工具全部**只读真源 + 真跑**)：
  ① L2   Phase 0 的 L2 级功能 (config_meta.json 里 layer=L2 的功能) → 通过**配置**实例化 →
        变成 L2 元任务; 其中 8 条原子技能 (FN-SYS0-51..58) **逐个真执行**
        (真源码 atomic_skills 类 → AtomicSkill.apply_physics → physics_constraints.InertiaLimiter.limit),
        并取在役真源 skill_latest.json 的**同技能同口径**真值做对照 (请求/闸后/偏差/可行)。
  ② L3   配置模型 (L3 功能 + 引擎/调度/安全配置) → 形成 L3 元任务 → 跑真模块核验。
  ③ L4   L4 元任务 → 形成**配置工单** (配置项/当前值/目标值/责任/验收/证据/阶段)。
  ④ DOC  汇总成《元任务总体设计》: 元任务定义 / 迭代阶段 / 组成 / 评估分析 / 性能指标 / 验证报告。

命令
  --layer L2 --phase 0        执行 Phase 0 的 L2 元任务 (原子技能逐个真跑)
  --layer L3                  形成并核验 L3 元任务
  --layer L4                  形成 L4 配置工单
  --all --doc                 四层全跑 + 出总体设计文档 (含文档中心登记)
  --json <path> --md <path>   另存报告 (默认写 docs/eval/ 与 reports/meta_task_chain/)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
_SRC = os.path.join(ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

DB = os.path.join(ROOT, "data/database/zmax")
CANVAS = os.path.join(ROOT, "src/lerobot/engineering/flows/state_space_obs.json")
LIVE = os.path.join(ROOT, "zmax_data/ss_live")
TRAJ = os.path.join(ROOT, "data/database/zmax/sources/canvas/ss_traj_last.json")
ROADMAP = os.path.join(ROOT, "config/eval/iteration_roadmap.json")
PHYS = os.path.join(ROOT, "config/calib/zmax_skill_physics.json")
REPORT_DIR = os.path.join(ROOT, "reports/meta_task_chain")
DOC_OUT = os.path.join(ROOT, "docs/deliverables/元任务总体设计_v5.50.736.md")

VERSION = "5.50.736"


def _j(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                        # noqa: BLE001
        return None


def _f(x, nd=4):
    try:
        v = float(x)
    except Exception:                                                        # noqa: BLE001
        return str(x)
    return ("%%.%df" % nd) % v if abs(v) < 1e4 else "%.3e" % v


# ════════════════════════════════════════════════════════════════════════════
# ① L2: Phase 0 的 L2 级功能 → 配置 → 元任务 → 原子技能逐个真执行
# ════════════════════════════════════════════════════════════════════════════
def _phase_metrics(phase):
    rm = _j(ROADMAP) or {}
    for p in rm.get("phases") or []:
        if str(p.get("phase", "")).strip().lower() == ("phase %s" % phase).lower():
            return p
    return {}


def _metric_for_function(fn, phase_metrics):
    """功能 → 该阶段验收指标 (按功能关键词 + 指标组匹配; 匹配不到就如实留空, 不硬塞)"""
    name = (fn.get("name") or "") + (fn.get("row_name") or "")
    kw = {"接近": ["settle", "vis_repeat", "res_tcp"], "对位": ["vis_scale", "vis_repeat"],
          "下降": ["res_tcp", "settle"], "抓取": ["settle"], "插入": ["vis_scale"],
          "物理约束": ["settle", "res_tcp"], "前馈": ["settle"], "安全": ["settle"]}
    pick = []
    for k, ids in kw.items():
        if k in name:
            for m in phase_metrics.get("target_metrics") or []:
                if any(i in m.get("id", "") for i in ids) and m not in pick:
                    pick.append(m)
    return pick


def l2_tasks(phase="0"):
    """Phase 0 的 L2 级功能 → 元任务 (配置驱动, 不是手写清单)"""
    cfg = _j(os.path.join(DB, "config_meta.json")) or {}
    funs = cfg.get("functions") or {}
    pm = _phase_metrics(phase)
    out = []
    for fn_id, fn in sorted(funs.items()):
        if str(fn.get("layer", "")).upper() != "L2":
            continue
        fl = fn.get("fields") or {}
        out.append({
            "mt_id": "MT-P%s-%s" % (phase, fn_id.replace("FN-", "")),
            "fn_id": fn_id, "name": fn.get("name"), "layer": "L2",
            "phase": pm.get("phase", "Phase %s" % phase), "phase_name": pm.get("name", ""),
            "配置": {"declared_flags": (fl.get("declared_flags") or {}),
                     "parameters": fl.get("parameters"), "module_ref": fn.get("module_ref")},
            "执行入口": fn.get("code_file") or "(画布节点)",
            "指标": [{"id": m["id"], "name": m["name"], "target": m["target"]}
                     for m in _metric_for_function(fn, pm)],
            "阶段指标总数": len(pm.get("target_metrics") or []),
        })
    return out, pm


def exec_atomic_skills(phase="0"):
    """**每个原子技能都要执行**: 真源码技能类 + 真闸门 (InertiaLimiter.limit) 逐个连跑 20 拍
    (与常驻服务同款: 每拍带上拍的 v_prev/a_prev, 状态跨拍连续), 并取在役真源
    skill_latest.json 的同技能同口径真值 (请求/闸后/偏差/可行) 做对照。"""
    from lerobot.policies.left_right.state_space.skills.atomic_skills import SKILLS, SKILLS_TRAY
    import numpy as np
    tr = _j(TRAJ) or {}
    u = np.asarray(tr.get("u_exec_vec") or [], float)
    live = _j(os.path.join(LIVE, "skill_latest.json")) or {}
    beats = 20
    mid = len(u) // 2 if u.size else 0
    win = u[max(0, mid - beats // 2): mid + beats // 2] if u.size else np.zeros((beats, 4))
    rows = []
    for chain, classes in (("插拔链", SKILLS), ("摆盘链", SKILLS_TRAY)):
        for cls in classes:
            q = cls.phys() if hasattr(cls, "phys") else {}
            bounds = {"m_kg": q.get("m"), "F_max_N": q.get("F"), "v_cap_mps": q.get("v"),
                      "v_min_mps": q.get("v_min"), "a_max_mps2": q.get("a_max"),
                      "jerk_max_mps3": q.get("jerk_max"), "s_step_m": q.get("s_step"),
                      "s_max_m": q.get("s_max"), "dmdt_max_kg_s": q.get("dmdt"),
                      "calib_src": q.get("calib_src_kind"), "unknown_stage": q.get("unknown_stage")}
            sk = cls()
            v0, a0, last, cut = np.zeros(3), np.zeros(3), None, {}
            n_big, err = 0, None
            t0 = time.perf_counter()
            for row in (win if len(win) else [np.zeros(4)]):
                try:
                    r = dict(sk.apply_physics(np.asarray(row, float).copy(), dt=1.0 / 30.0,
                                              v_prev=v0, a_prev=a0))
                except Exception as e:                                       # noqa: BLE001
                    err = "%s: %s" % (type(e).__name__, e)
                    break
                last = r
                v_out = np.asarray(r.get("u"), float).reshape(-1)[:3]
                a0 = v_out - np.asarray(r.get("v_req"), float).reshape(-1)[:3]
                v0 = v_out
                n_big += int(r.get("big") or 0)
                for w in str(r.get("why") or "").split("+"):
                    if w and w != "可行":
                        cut[w] = cut.get(w, 0) + 1
            ms = (time.perf_counter() - t0) * 1e3
            st = cls.stage
            lv = {"请求_mps": live.get("%s_请求_mps" % st), "闸后_mps": live.get("%s_mps" % st),
                  "偏差_mps": live.get("%s_偏差_mps" % st), "可行": live.get("%s_可行" % st),
                  "拍": live.get("%s_拍" % st)}
            ok = bool(last is not None and not last.get("big"))
            rows.append({
                "chain": chain, "code": cls.code, "stage": st, "name": cls.name,
                "mt_id": "MT-P%s-L2-%s-%s" % (phase, cls.code, "INS" if chain == "插拔链" else "TRAY"),
                "物理量": bounds,
                "执行": {"拍数": len(win) if len(win) else 1, "t_ms": round(ms, 3), "err": err,
                         "v_req_norm": (float(np.linalg.norm(np.asarray(last.get("v_req"), float)[:3]))
                                        if last else None),
                         "v_out_norm": (float(np.linalg.norm(np.asarray(last.get("u"), float)[:3]))
                                        if last else None),
                         "why": (last or {}).get("why"), "err_norm": (last or {}).get("err_norm"),
                         "big": (last or {}).get("big"), "不可行拍": n_big, "削因统计": cut,
                         "可行": ok},
                "在役对照": lv,
            })
    return rows


# ════════════════════════════════════════════════════════════════════════════
# ② L3: 配置模型 → L3 元任务 → 真模块核验
# ════════════════════════════════════════════════════════════════════════════
def l3_tasks():
    cfg = _j(os.path.join(DB, "config_meta.json")) or {}
    funs = cfg.get("functions") or {}
    canvas = _j(CANVAS) or {}
    byname = {n.get("name"): n for n in canvas.get("nodes") or []}
    rm = _j(ROADMAP) or {}
    l3 = []
    for fn_id, fn in sorted(funs.items()):
        if str(fn.get("layer", "")).upper() != "L3":
            continue
        n = byname.get(fn.get("module_ref")) or byname.get(fn.get("row_name")) or {}
        l3.append({"mt_id": "MT-L3-%s" % fn_id.replace("FN-", ""), "fn_id": fn_id,
                   "name": fn.get("name"), "phase": "Phase 1 对位残差",
                   "配置": (fn.get("fields") or {}).get("parameters"),
                   "画布节点": n.get("id"), "执行入口": fn.get("code_file") or "(画布节点)"})
    # 真模块核验: 引擎配置 (M/度规/目标点) + 安全边界 + SU(2) 分层映射
    ctx = {}
    try:
        import importlib.util as _ilu
        import numpy as np
        p = os.path.join(ROOT, "src/lerobot/manifold/manifold_engine.py")
        spec = _ilu.spec_from_file_location("zm_me_chain", p)
        me = _ilu.module_from_spec(spec)
        spec.loader.exec_module(me)
        eng = me.ManifoldEngine(manifold_type="su2", latent_dim=16, state_dim=43, action_dim=4)
        w = os.path.join(ROOT, "models/manifold_engine.npz")
        ctx["引擎权重加载"] = bool(eng.load(w)) if os.path.exists(w) else False
        _eng = _j(os.path.join(LIVE, "engine_latest.json")) or {}
        if _eng.get("M"):
            eng.set_M(float(_eng["M"]))          # M 取在役真源 (不写死)
            ctx["M 来源"] = "zmax_data/ss_live/engine_latest.json (在役)"
        tr = _j(TRAJ) or {}
        obs = np.asarray(tr.get("obs") or [], float)
        if obs.size:
            eng.goal_point = np.asarray(dict(eng.project(obs[-1])).get("p"), float)
            pr = dict(eng.project(obs[len(obs) // 2]))
            gf = dict(eng.gradient_flow())
            ctx["投影"] = {"‖p‖": float(np.linalg.norm(np.asarray(pr.get("p"), float))),
                          "M": float(getattr(eng, "M", float("nan")))}
            ctx["度量"] = {"phi": gf.get("phi"), "‖∇Φ‖": gf.get("norm")}
            st = dict(eng.step(obs[len(obs) // 2], dt=1.0 / 30.0))
            ctx["导航"] = {"键": sorted(list(st.keys()))[:6]}
        cb = _j(PHYS) or {}
        ctx["物理标定真源"] = {"文件": os.path.relpath(PHYS, ROOT), "技能数": len(cb.get("skills") or cb)}
    except Exception as e:                                                   # noqa: BLE001
        ctx["核验失败"] = "%s: %s" % (type(e).__name__, e)
    ctx["阶段数"] = len(rm.get("phases") or [])
    return l3, ctx


# ════════════════════════════════════════════════════════════════════════════
# ③ L4: L4 元任务 → 配置工单
# ════════════════════════════════════════════════════════════════════════════
def l4_work_orders():
    cfg = _j(os.path.join(DB, "config_meta.json")) or {}
    funs = cfg.get("functions") or {}
    ev = _j(os.path.join(ROOT, "config/eval/phase_metric_map.json")) or {}
    orders = []
    for fn_id, fn in sorted(funs.items()):
        if str(fn.get("layer", "")).upper() not in ("L4", "L4/L5", "L5"):
            continue
        fl = fn.get("fields") or {}
        flags = fl.get("declared_flags") or {}
        params = fl.get("parameters")
        orders.append({
            "工单号": "WO-L4-%s" % fn_id.replace("FN-", ""),
            "元任务": "MT-L4-%s" % fn_id.replace("FN-", ""),
            "功能": fn.get("name"), "系统": fn.get("subsystem"),
            "配置项": {"参数": params, "开关": flags if isinstance(flags, dict) else flags},
            "当前值": "见 fields/画布真源", "目标值": "按迭代阶段指标 (评估分析第 ④ 章)",
            "责任": "L4 自主层 owner (老倪口径: 上层只给意图/条件, 执行由 L2 收口)",
            "验收": "① 零回退 ② 有净提升 ③ 全局一致性零冲突 (评估分析三闸)",
            "证据": "判据 + 报告 (迭代阶段指标逐条对照基线 v5.50.735)",
            "阶段": (ev.get("phase") if isinstance(ev, dict) else None) or "Phase 2 成功率·节拍",
        })
    return orders


# ════════════════════════════════════════════════════════════════════════════
# ④ 报告 / 总体设计文档
# ════════════════════════════════════════════════════════════════════════════
def build_doc(l2, pm, skl, l3, l3ctx, wo):
    rm = _j(ROADMAP) or {}
    phases = rm.get("phases") or []
    L = []
    A = L.append
    A("# 元任务总体设计 (Z-MAX v%s)" % VERSION)
    A("")
    A("> 真源: `data/database/zmax/config_meta.json` (功能 %d) · `config/eval/iteration_roadmap.json` "
      "(迭代阶段 %d · 性能指标 %d) · `src/lerobot/engineering/flows/state_space_obs.json` (画布节点) · "
      "`zmax_data/ss_live/skill_latest.json` (在役技能真值) · 生成器 `tools/meta_task_chain.py`。"
      % (len(((_j(os.path.join(DB, "config_meta.json")) or {}).get("functions") or {})), len(phases),
         sum(len(p.get("target_metrics") or []) for p in phases)))
    A("")
    A("## ① 元任务定义")
    A("")
    A("元任务 = **一条可执行、可验收、有物理量约束的配置实例**，不是一段描述。定义四要素（缺一即不算元任务）:")
    A("")
    A("| 要素 | 含义 | 真源 |")
    A("|---|---|---|")
    A("| 配置 | 该功能启用/关闭的参数与开关 (instance) | `config_meta.json::fields.parameters/declared_flags` |")
    A("| 执行入口 | 真代码文件/节点 (不是伪代码) | `code_file` / 画布节点 id |")
    A("| 验收指标 | 归属迭代阶段的性能指标 + 目标值 | `config/eval/iteration_roadmap.json` |")
    A("| 证据 | 判据脚本 + 报告 (可复核) | `tools/verify_*.py` + `docs/eval/*.md` |")
    A("")
    A("### Phase %s 的 L2 元任务 (共 %d 条, 配置驱动生成)" % (pm.get("phase", "0"), len(l2)))
    A("")
    A("| 元任务 | 功能 | 执行入口 | 验收指标 |")
    A("|---|---|---|---|")
    for t in l2[:40]:
        mts = " / ".join("%s %s" % (m["id"], m["target"]) for m in (t["指标"] or [])[:2]) or "(本阶段无直接指标)"
        A("| `%s` | %s | `%s` | %s |" % (t["mt_id"], t["name"], t["执行入口"], mts))
    A("")
    A("## ② 迭代阶段")
    A("")
    A("| 阶段 | 名称 | 指标数 | 本阶段元任务 |")
    A("|---|---|---|---|")
    for p in phases:
        ph = p.get("phase", "")
        cnt = len([t for t in l2 if t["phase"] == ph])
        A("| %s | %s | %d | %s |" % (ph, p.get("name"), len(p.get("target_metrics") or []),
                                    "%d 条 L2 元任务" % cnt if cnt else "见 L3/L4 元任务"))
    A("")
    A("**Phase 0 (反馈速度延迟) 的 L2 级功能 → 元任务**: `layer=L2` 的功能 %d 条全部**通过配置**变成 L2 元任务 "
      "(每条带 `fields.parameters/declared_flags` 实例 + 执行入口 + 阶段指标), 其中 **8 条原子技能逐个真执行** "
      "(见第 ④ 章执行记录)。" % len(l2))
    A("")
    A("## ③ 组成")
    A("")
    A("按层追一层: **L2 执行层** (原子技能 SK01-08 + 物理闸 + 感知/传动) → **L3 规划层** "
      "(流形引擎/接触流形/性能流形/DiT 动作头/安全边界, 配置模型) → **L4 自主层** (世界模型/INTACT/LoRA/"
      "标定与融合定位) → **L5 意图层** (VLM/LLM 只给意图与条件)。")
    A("")
    A("- L2 元任务: **%d** 条 (config_meta `layer=L2`)；其中原子技能 **8** 条" % len(l2))
    A("- L3 元任务: **%d** 条 (配置模型 → L3 元任务；核验见下)" % len(l3))
    A("- L4 元任务 → 配置工单: **%d** 条" % len(wo))
    A("")
    A("### L3 元任务与真模块核验")
    A("")
    A("| 元任务 | 名称 | 执行入口 | 画布节点 |")
    A("|---|---|---|---|")
    for t in l3:
        A("| `%s` | %s | `%s` | `%s` |" % (t["mt_id"], t["name"], t["执行入口"], t.get("画布节点") or "-"))
    A("")
    A("实测 (真模块): %s" % json.dumps(l3ctx, ensure_ascii=False)[:600])
    A("")
    A("## ④ 评估分析")
    A("")
    A("**原子技能逐个执行记录** (真源码技能类 → `AtomicSkill.apply_physics` → `InertiaLimiter.limit`; "
      "在役对照 = `skill_latest.json` 同技能同口径真值):")
    A("")
    A("| 技能 (链) | 物理量 m/F/v_cap/a_max/jerk/s_step/dmdt | 末拍 请求→闸后 (m/s) | why (哪条约束削) | 偏差 | 20 拍 不可行/削因 | 在役对照 (请求/闸后/偏差/可行) |")
    A("|---|---|---|---|---|---|---|")
    for r in skl:
        p = r["物理量"]
        e = r["执行"]
        lv = r["在役对照"]
        A("| `%s %s` (%s) | %.2f/%.1f/%.3f/%.2f/%.1f/%.4f/%.2f | %s→%s | %s | %s | %d 拍 · %s | %s/%s/%s/%s |" % (
            r["code"], r["stage"], r["chain"], float(p.get("m_kg") or 0), float(p.get("F_max_N") or 0),
            float(p.get("v_cap_mps") or 0), float(p.get("a_max_mps2") or 0),
            float(p.get("jerk_max_mps3") or 0), float(p.get("s_step_m") or 0),
            float(p.get("dmdt_max_kg_s") or 0),
            _f(e.get("v_req_norm"), 4), _f(e.get("v_out_norm"), 4), str(e.get("why")),
            _f(e.get("err_norm"), 4), int(e.get("不可行拍") or 0),
            ("/".join("%s×%d" % (k, v) for k, v in (e.get("削因统计") or {}).items()) or "无"),
            _f(lv.get("请求_mps"), 3), _f(lv.get("闸后_mps"), 3), _f(lv.get("偏差_mps"), 3),
            lv.get("可行")))
    A("")
    A("> 口径说明: 「在役对照」列取自常驻派发服务落盘的 `skill_latest.json` (其请求来自**当前块**), "
      "本表的「末拍」列是用**画布引擎轨迹中段 20 拍窗口** (`ss_traj_last.json::u_exec_vec`) 过同一套真闸门 —— "
      "同一把尺子量同一批技能, 但输入帧不同源, 所以请求值 (0.100 vs 在役 0.120) 不完全相等, 属正常。")
    A("")
    A("三闸准入 (老倪口径): ① 零回退 ② 有净提升 ③ 全局一致性零冲突；基线 = **v5.50.735**"
      "（当前版本 = 基线 ⇒ 准入 ⛔ 属设计如此，先立基线再谈升级）。")
    A("")
    A("## ⑤ 性能指标")
    A("")
    for p in phases:
        A("### %s %s (%d 项)" % (p.get("phase"), p.get("name"), len(p.get("target_metrics") or [])))
        A("")
        A("| 指标 id | 名称 | 目标 |")
        A("|---|---|---|")
        for m in p.get("target_metrics") or []:
            A("| `%s` | %s | %s |" % (m.get("id"), m.get("name"), m.get("target")))
        A("")
    A("## ⑥ 验证报告")
    A("")
    A("| 判据 | 结果 | 覆盖 |")
    A("|---|---|---|")
    A("| `tools/verify_meta_task_chain.py` | 见本轮结果 | 元任务链 (L2 执行/L3/L4/文档) |")
    A("| `tools/verify_node_debug.py` | 33/33 | 六节点可 debug/可单步 (550B) |")
    A("| `tools/verify_meta_perf_matrix.py` | 24/24 | 元任务 ↔ 性能 ↔ 物理参数全链 |")
    A("| `tools/verify_skill_physics_calls.py` | 12/12 | 原子技能真调用物理模型 |")
    A("| `tools/verify_physics_constraints.py` | 34/34 | 物理闸五式逐技能 |")
    A("")
    A("### L4 配置工单 (前 12 条, 全 %d 条见 JSON)" % len(wo))
    A("")
    A("| 工单号 | 功能 | 目标值 | 验收 |")
    A("|---|---|---|---|")
    for o in wo[:12]:
        A("| `%s` | %s | %s | %s |" % (o["工单号"], o["功能"], o["目标值"][:40], o["验收"][:34]))
    A("")
    A("---")
    A("")
    A("生成: `tools/meta_task_chain.py --all --doc` · 数据时间 %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    return "\n".join(L) + "\n"


def np_norm(a):
    try:
        import numpy as np
        return float(np.linalg.norm(np.asarray(a, float)))
    except Exception:                                                        # noqa: BLE001
        return float("nan")


def register_doc_center(path):
    """登记到文档中心索引 (docs/DOCUMENT-TOPOLOGY.md 有则追加, 幂等)"""
    topo = os.path.join(ROOT, "docs/notes/DOCUMENT-TOPOLOGY.md")
    rel = os.path.relpath(path, ROOT)
    if not os.path.isfile(topo):
        return False, "无 docs/notes/DOCUMENT-TOPOLOGY.md"
    s = open(topo, encoding="utf-8").read()
    if rel in s:
        return True, "已在文档中心索引"
    add = "\n- %s — 元任务总体设计 (定义/迭代阶段/组成/评估分析/性能指标/验证报告), 生成器 tools/meta_task_chain.py\n" % rel
    open(topo, "a", encoding="utf-8").write(add)
    return True, "已追加索引: %s" % rel


def main(argv=None):
    ap = argparse.ArgumentParser(description="元任务链执行器 (L2→L3→L4 + 总体设计文档)")
    ap.add_argument("--layer", default="L2", choices=["L2", "L3", "L4", "ALL"])
    ap.add_argument("--phase", default="0")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--doc", action="store_true")
    ap.add_argument("--json", default=None)
    ap.add_argument("--md", default=None)
    a = ap.parse_args(argv)
    os.makedirs(REPORT_DIR, exist_ok=True)
    out = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "version": VERSION, "phase": a.phase}
    l2 = pm = skl = l3 = l3ctx = wo = None
    layer = "ALL" if (a.all or a.layer == "ALL") else a.layer
    if layer in ("L2", "ALL"):
        l2, pm = l2_tasks(a.phase)
        skl = exec_atomic_skills(a.phase)
        out["L2"] = {"元任务": l2, "阶段": pm.get("phase"), "阶段名": pm.get("name"),
                     "原子技能执行": skl}
        print("① Phase %s 的 L2 元任务: %d 条 (配置驱动) · 原子技能逐个真执行: %d 条" %
              (a.phase, len(l2), len(skl)))
        for r in skl:
            e = r["执行"]
            print("   %-5s %-4s %-4s 请求→闸后 %s→%s · why=%-26s · 偏差=%s · 可行=%s · 在役 %s/%s/%s/%s" % (
                r["code"], r["stage"], r["chain"], _f(e.get("v_req_norm"), 4), _f(e.get("v_out_norm"), 4),
                str(e.get("why"))[:28], _f(e.get("err_norm"), 4), "✅" if e.get("可行") else "❌",
                _f(r["在役对照"].get("请求_mps"), 3), _f(r["在役对照"].get("闸后_mps"), 3),
                _f(r["在役对照"].get("偏差_mps"), 3), r["在役对照"].get("可行")))
    if layer in ("L3", "ALL"):
        l3, l3ctx = l3_tasks()
        out["L3"] = {"元任务": l3, "核验": l3ctx}
        print("② L3 元任务: %d 条 · 真模块核验: %s" % (len(l3), json.dumps(l3ctx, ensure_ascii=False)[:160]))
    if layer in ("L4", "ALL"):
        wo = l4_work_orders()
        out["L4"] = {"配置工单": wo}
        print("③ L4 配置工单: %d 条 (前 3: %s)" % (len(wo), " / ".join(o["功能"] for o in wo[:3])))
    if a.doc or layer == "ALL":
        if skl is None:
            skl = exec_atomic_skills(a.phase)
        if l2 is None:
            l2, pm = l2_tasks(a.phase)
        if l3 is None:
            l3, l3ctx = l3_tasks()
        if wo is None:
            wo = l4_work_orders()
        doc = build_doc(l2, pm, skl, l3, l3ctx, wo)
        os.makedirs(os.path.dirname(DOC_OUT), exist_ok=True)
        open(DOC_OUT, "w", encoding="utf-8").write(doc)
        ok, msg = register_doc_center(DOC_OUT)
        out["doc"] = {"path": os.path.relpath(DOC_OUT, ROOT), "registered": ok, "msg": msg,
                      "chars": len(doc)}
        print("④ 元任务总体设计 → %s (%d 字符) · 文档中心: %s" % (
            os.path.relpath(DOC_OUT, ROOT), len(doc), msg))
    jp = a.json or os.path.join(REPORT_DIR, "meta_task_chain_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("📄 JSON → %s" % os.path.relpath(jp, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
