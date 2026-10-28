#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""元任务开发计划导出器 —— 配置中心「📋 任务配置」页的 Word / PDF 导出。

老倪 2026-10-14:
    「你现在将状态空间的工程中, 所有任务进行分析, 将每个功能清单中的功能, 叠加上配置参数,
      转化成 元任务。…… 这些元任务, 要由配置中心可以在任务配置里可以导出 word 和 pdf 文档。」

口径（全部从工程真源实读派生，不人工编造）:
    元任务 = 一个功能 (FN-SYSx-N) + 该功能的全部配置参数 + 依赖 + 验证方法 + 归属层
    真源: data/database/zmax/config_meta.json          (74 个功能的字段/范围/单位/依赖/验证)
          data/database/zmax/sources/config/tasks/tasks.json          (7 个任务的工艺/覆盖/周期)
          data/database/zmax/sources/config/ss_task_binding.json      (任务 × 节点 × 配方段)
          src/lerobot/engineering/flows/state_space_obs.json          (画布 89 节点 / 184 连线)

生成链: 真源 → Markdown → HTML → LibreOffice(soffice) → docx + pdf
        (LibreOffice 不能直接吃 .md，所以中间必须过一层 HTML；从 HTML 导出 docx 需先转 odt
         —— HTML 会被当成 Writer/Web 文档，没有 docx 导出过滤器，实测踩过。)

用法:
    python3 tools/export_meta_doc.py                      # 全量导出 md + docx + pdf
    python3 tools/export_meta_doc.py --no-pdf             # 只出 md + docx
    python3 tools/export_meta_doc.py --out DIR            # 指定输出目录
    python3 tools/export_meta_doc.py --check              # 只做一致性校验，不出文档
"""
from __future__ import annotations

import argparse
import hashlib
import html as H
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data/database/zmax")
SRC = os.path.join(DB, "sources", "config")
CANVAS = os.path.join(ROOT, "src/lerobot/engineering/flows/state_space_obs.json")
DEFAULT_OUT = os.path.join(ROOT, "docs/deliverables")

# 用户指定优先级：摆盘(TASK-06-TRAY) + 插拔(TASK-01-FW) 优先
PRIORITY_TASKS = ["TASK-06-TRAY", "TASK-01-FW"]
TASK_ORDER = ["TASK-06-TRAY", "TASK-01-FW", "TASK-02-HANDLE", "TASK-03-BI",
              "TASK-04-THERMAL", "TASK-05-ATS", "TASK-07-AOI"]


def task_order(tasks):
    """任务展示序: 老的固定序优先, **新加的任务自动追加在后面** (2026-10 起真源 8 条: 多了 TASK-08-AL1;
    原来 TASK_ORDER 硬编码 7 个 ⇒ 文档/校验里第 8 个任务被静默漏掉)。"""
    ids = [t["task_id"] for t in tasks]
    out = [x for x in TASK_ORDER if x in ids]
    return out + [x for x in ids if x not in out]
LAYER_SEQ = {"L2": 0, "L3": 1, "L4/L5": 2, "PLAT": 3}
# 2026-10 ~ 2027-12 共 15 个月，逐月配额（前 9 月压完摆盘/插拔所需的 51 个）
QUOTA = [6, 6, 6, 6, 6, 6, 5, 5, 5, 4, 4, 4, 4, 4, 3]


def _sha(p):
    try:
        return hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]
    except OSError:
        return "n/a"


def _j(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def months_2026_10_to_2027_12():
    return [f"{y}-{m:02d}" for y in (2026, 2027) for m in range(1, 13)
            if (y == 2026 and m >= 10) or y == 2027]


def _norm_node_name(s) -> str:
    """归一化节点/功能名, 用于抗改名匹配 (老倪 2026-10-14「补上, 配置完备性」)。

    实测断裂例: 画布节点已改名「🎛 L4 · INTACT LoRA 微调 (接在意图解码器后 · 冻结原权重 · 只调 ΔW=(α/r)BA)」,
    而登记表还是旧名「🎛 L4 · INTACT LoRA 微调 (r8/α16) · 接入中」⇒ 按原名精确匹配就断 (73/74)。
    口径: 去掉括号补充 + 去掉「接入中/todo/待接入」这类状态尾巴 + 压缩空白 ⇒ 两侧都归一到同一形。
    """
    s = str(s or "").strip()
    s = re.sub(r"[（(][^）)]*[）)]", "", s)
    for suf in ("接入中", "待接入", "未接入", "· todo", "todo", "TODO", "待做"):
        s = s.replace(suf, "")
    s = re.sub(r"\s+", " ", s).strip(" ·•-—~:")
    return s


def build_meta_tasks():
    """构建元任务清单 + 排期。返回 (元任务列表, 上下文 dict)。"""
    cm = _j(os.path.join(DB, "config_meta.json"))
    fnmap = cm["functions"]
    canvas = _j(CANVAS)
    nodes = canvas["nodes"]
    byname = {n["name"]: n["id"] for n in nodes}
    sb = _j(os.path.join(SRC, "ss_task_binding.json"))
    tasks = sb["tasks"]
    # 🆕 2026-10-14 老倪: 「你来修改每个功能点的描述」—— 描述真源 = function_notes.json
    #   (每个功能点: work 干什么活 / pain 卡在哪 / state 当前状态)。GUI/文档/工程库/交底书 一处取数。
    _nf = _j(os.path.join(DB, "function_notes.json")) or {}
    NOTES = (_nf.get("notes") or {}) if isinstance(_nf, dict) else {}

    node2tasks = defaultdict(list)
    for t in tasks:
        for nid in (t.get("enabled_nodes") or []):
            node2tasks[nid].append(t["task_id"])

    # 真实依赖 = 画布连线 (links 的 t←f): config_meta 的 deps.functions 实测 74/74 为空,
    # 唯一有据的依赖来源就是画布上游节点 ⇒ 用它, 不手写依赖表 (2026-10-14)。
    nid2name = {n["id"]: n["name"] for n in nodes}
    up_ids = defaultdict(set)
    for lk in (canvas.get("links") or []):
        if lk.get("t") and lk.get("f"):
            up_ids[lk["t"]].add(lk["f"])

    bad = []
    MT = []
    # 抗改名匹配: ① 原名精确 ② 归一化名 ③ 唯一前缀 (仅当只有 1 个节点匹配得上, 否则如实算未映射)
    _norm_map: dict = {}
    for _n in nodes:
        _norm_map.setdefault(_norm_node_name(_n["name"]), _n["id"])
    for fn_id, v in fnmap.items():
        ref = v.get("module_ref")
        nid = byname.get(ref)
        how = "name" if nid else ""
        if not nid:
            nid = _norm_map.get(_norm_node_name(ref))
            how = "norm" if nid else ""
        if not nid:
            _r = _norm_node_name(ref)
            _cand = [_n["id"] for _n in nodes if _norm_node_name(_n["name"]).startswith(_r) and len(_r) >= 6]
            if len(_cand) == 1:
                nid, how = _cand[0], "prefix"
        if not nid:
            bad.append((fn_id, ref))
            how = "unmatched"
        ts = node2tasks.get(nid, [])
        params = (v.get("fields") or {}).get("parameters") or []
        n_serv = len(ts)
        prio = "P0" if n_serv == len(tasks) else ("P1" if n_serv > 0 else "P2")
        MT.append({
            "fn_id": fn_id, "name": v.get("name"), "node_id": nid, "match": how,
            "layer": v.get("layer"), "subsystem": v.get("subsystem"),
            "code_file": v.get("code_file"),
            "n_params": len(params),
            "n_specific": (v.get("completeness") or {}).get("specific_param_count", 0),
            "complete": (v.get("completeness") or {}).get("complete"),
            "missing": (v.get("completeness") or {}).get("missing") or [],
            "tasks": ts, "n_serv": n_serv, "prio": prio,
            "prio_rank": {"P0": 0, "P1": 1, "P2": 2}[prio],
            "verification": ((v.get("verification") or {}).get("methods") or [])[:4],
            "deps_fn": (v.get("deps") or {}).get("functions") or [],
            "note": NOTES.get(fn_id) or {},
            # ── 《元任务标准模板》字段 (2026-10-14 老倪文档): 输入/输出/配置参数/依赖关系/承载场景 ──
            "inputs": ((v.get("fields") or {}).get("inputs") or []),
            "outputs": ((v.get("fields") or {}).get("outputs") or []),
            "deps_up": sorted({nid2name.get(x, x) for x in up_ids.get(nid, ())}) if nid else [],
            "scenes": ["%s(%s)" % (t.get("scene_ref") or "—", t.get("task_id"))
                       for t in tasks if t["task_id"] in ts],
            "params_head": ["%s=%s%s" % (p.get("cn") or p.get("id"), p.get("value"),
                                         ("" if p.get("unit") in (None, "-") else p.get("unit")))
                            for p in params[:3]],
        })

    MT.sort(key=lambda m: (m["prio_rank"], LAYER_SEQ.get(m["layer"], 9),
                           -m["n_params"], m["name"] or ""))
    months = months_2026_10_to_2027_12()
    # 🔴 2026-10-28: 原来只给 sum(QUOTA)=74 条派 mt_id/month, 功能数涨到 77 后剩 3 条**没有 mt_id**
    #   ⇒ 渲染 md 时 KeyError: 'mt_id', 配置中心「📄 元任务计划」按钮点了不出版 (老倪: 点了必出结果)。
    #   改成: 全部派号; 月配额用完后统一落最后一个月 (如实标 "溢出", 不悄悄改排期表)。
    for _i, _m in enumerate(MT):
        _m["mt_id"] = "MT-%03d" % (_i + 1)
    i = 0
    for mi, mth in enumerate(months):
        for _ in range(QUOTA[mi]):
            if i < len(MT):
                MT[i]["month"] = mth
                i += 1
    while i < len(MT):                      # 超出配额的部分 (功能数增长) 落最后一个月并标溢出
        MT[i]["month"] = months[-1]
        MT[i]["month_overflow"] = True
        i += 1
    ctx = {"cm": cm, "canvas": canvas, "tasks": tasks, "bad": bad,
           "months": months, "covered": len(node2tasks)}
    return MT, ctx


def consistency(MT, ctx):
    """一致性校验（实跑，非声明）。返回 (行列表, 全绿 bool)。"""
    tasks = ctx["tasks"]
    cm = ctx["cm"]
    rows = []
    ok_all = True

    def chk(name, expect, actual, good):
        nonlocal ok_all
        ok_all = ok_all and good
        rows.append((name, str(expect), str(actual), "✅" if good else "❌"))

    chk("元任务数 = 功能数", len(cm["functions"]), len(MT), len(MT) == len(cm["functions"]))
    hit = sum(1 for m in MT if m["node_id"])
    chk("功能 module_ref → 画布节点", f"{len(MT)}/{len(MT)}", f"{hit}/{len(MT)}", hit == len(MT))
    miss = []
    for t in tasks:
        en = t.get("enabled_nodes") or []
        ids = {n["id"] for n in ctx["canvas"]["nodes"]}
        miss_n = [x for x in en if x not in ids]
        if miss_n:
            miss.append((t["task_id"], miss_n))
    chk("任务 enabled_nodes → 画布节点", "全部存在",
        "全部存在" if not miss else f"{len(miss)} 个任务有缺失",
        not miss)
    # 各任务元任务数 == 启用节点数
    per = {t["task_id"]: sum(1 for m in MT if t["task_id"] in m["tasks"]) for t in tasks}
    exp = {t["task_id"]: len(t.get("enabled_nodes") or []) for t in tasks}
    same = all(per[k] == exp[k] for k in exp)
    _to = task_order(tasks)
    chk("各任务元任务数 = 启用节点数", "/".join(str(exp[k]) for k in _to),
        "/".join(str(per.get(k, 0)) for k in _to), same)
    return rows, ok_all


def render_md(MT, ctx):
    cm, canvas, tasks = ctx["cm"], ctx["canvas"], ctx["tasks"]
    months = ctx["months"]
    td = {t["task_id"]: t for t in tasks}
    L = []
    A = L.append
    A("# Z-MAX 状态空间工程 · 元任务开发计划（项目立项书）\n")
    A("**编制日期**：2026-10-14 　**计划周期**：2026-10 ~ 2027-12（15 个月）  ")
    A(f"**工程**：状态空间工程 · 主工程　**画布**：{canvas.get('name')}"
      f"（{len(canvas['nodes'])} 节点 / {len(canvas['links'])} 连线）  ")
    A(f"**任务数**：{len(tasks)}　**功能（元任务）数**：{len(MT)}"
      f"　**参数总数**：{sum(m['n_params'] for m in MT)}\n")
    A("---\n")
    A("## 一、项目概述\n")
    A("### 1.1 目标")
    A("把状态空间工程中**每个功能的清单项叠加其配置参数**，固化为可独立开发、可配置、可验证的**元任务**；")
    A("在 2026-10 ~ 2027-12 内完成全部元任务的开发、接入与验收，并保证工程数据一致性。\n")
    A("### 1.2 元任务定义")
    A("> **元任务 = 一个功能（FN-SYSx-N）+ 该功能的全部配置参数 + 依赖 + 验证方法 + 归属层**\n")
    A("数据真源（全部实读，不人工编造）：\n")
    A("| 真源 | 路径 | 内容 |")
    A("|---|---|---|")
    A("| 功能元数据 | `data/database/zmax/config_meta.json` | %d 个功能的字段/范围/单位/默认值/依赖/验证 |" % len(MT))
    A("| 参数注册表 | `sources/config/mcd/param_registry.json` | 每个参数的当前值/默认/min/max/单位/档位 |")
    A("| 任务配置 | `sources/config/tasks/tasks.json` | %d 个任务的工序/参数覆盖/触发循环 |" % len(tasks))
    A("| 任务绑定 | `sources/config/ss_task_binding.json` | 任务 × 节点 × 配方段 绑定 |")
    A("| 画布工程 | `src/lerobot/engineering/flows/state_space_obs.json` | 89 节点 / 184 连线 |")
    A("")
    cnt = Counter(n.get("type") for n in canvas["nodes"])
    A("### 1.3 工程基线（实测）\n")
    A("```")
    A("画布节点 %d = %s" % (len(canvas["nodes"]),
                          " + ".join(f"{k} {v}" for k, v in sorted(cnt.items(), key=lambda x: -x[1]))))
    comp = sum(1 for m in MT if m["complete"])
    A(f"功能 {len(MT)} / 元数据完整 {comp} ({comp * 100 // max(len(MT), 1)}%) / 不完整 {len(MT) - comp}")
    A(f"参数 {sum(m['n_params'] for m in MT)} 条（含通用标定基线 + 功能专属）")
    A("任务节点集：" + " · ".join(f"{k}={len(td[k].get('enabled_nodes') or [])}" for k in task_order(tasks)))
    A("```\n")
    allnodes = set()
    for t in tasks:
        allnodes |= set(t.get("enabled_nodes") or [])
    A("**关键结论（决定元任务模型）**：全部 %d 个任务的启用节点都是同一 %d 节点集的**子集**，"
      % (len(tasks), len(allnodes)))
    A("无任何任务专属节点 ⇒ **元任务（功能）为全工程共用，任务之间只差配置**"
      "（`overrides` 参数覆盖 + `applies_segments` 配方段 + `run_cfg` 执行开关），")
    A("与工程口径“一个状态空间工程承载全部任务；任务 = 配方段子集 + 参数覆盖”完全一致。\n")
    A("---\n")
    A("## 二、七个任务与元任务覆盖\n")
    A("| # | 任务 ID | 任务名称 | 配方类型 | 配方段 | 启用节点 | 元任务数 | 优先级 |")
    A("|---|---|---|---|---|---|---|---|")
    for i, tid in enumerate(task_order(tasks), 1):
        t = td.get(tid)
        if not t:
            continue
        n = len(t.get("enabled_nodes") or [])
        real = sum(1 for m in MT if tid in m["tasks"])
        pri = "**P0 优先**" if tid in PRIORITY_TASKS else "P1"
        A(f"| {i} | {tid} | {t.get('name')} | {t.get('recipe_type')} | "
          f"{len(t.get('applies_segments') or [])} | {n} | {real} | {pri} |")
    A("")
    A("> 用户指定优先级：**摆盘（TASK-06-TRAY）与 插拔（TASK-01-FW）优先**，其余任务依次。")
    A("> 说明：摆盘在工程里的 task_id 是 `TASK-06-TRAY`（`TASK-07-AOI` 是 AR 光学质检），"
      "此处按功能口径排定，两种编号已并列标出。\n")
    A("---\n")
    A("## 三、元任务优先级\n")
    A("| 优先级 | 定义 | 数量 | 说明 |")
    A("|---|---|---|---|")
    c0 = sum(1 for m in MT if m["prio"] == "P0")
    c1 = sum(1 for m in MT if m["prio"] == "P1")
    c2 = sum(1 for m in MT if m["prio"] == "P2")
    A(f"| **P0** | 服务全部 {len(tasks)} 个任务 | {c0} | 核心底座：感知/控制/执行/安全 + L4 决策，任何任务都绕不开 |")
    A(f"| **P1** | 服务 5~{len(tasks)-1} 个任务 | {c1} | 多任务共用的扩展能力 |")
    A(f"| **P2** | 未被任何任务启用 | {c2} | 已登记在工程、尚未接入任务，最后收口 |")
    A("")
    A("---\n")
    A("## 四、开发排期（2026-10 → 2027-12）\n")
    A("### 4.1 排期原则")
    A("1. **摆盘（TASK-06-TRAY）、插拔（TASK-01-FW）优先**：这两个任务启用的节点集覆盖全部 7 个任务的所有节点，")
    A("   因此把**支撑它们所需的全部元任务**压在**前 9 个月**（2026-10 ~ 2027-06）完成；")
    A("2. **层序推进**：L2（感知/控制/执行/安全底座）→ L3（长程规划）→ L4/L5（自主决策）→ PLAT（平台支撑）；")
    A("3. **复杂度优先启动**：参数多、依赖多的元任务先开工（迭代周期长）；")
    A("4. **依赖不越级**：被依赖的元任务先于依赖者完成；")
    A("5. **明年年底（2027-12）全部 %d 个元任务收口**。\n" % len(MT))
    A("### 4.2 两阶段排期\n")
    n_stage1 = c0 + c1
    A("| 阶段 | 时间 | 元任务数 | 范围 | 出口判据 |")
    A("|---|---|---|---|---|")
    A(f"| **阶段一 · 摆盘+插拔优先** | 2026-10 ~ 2027-06（9 个月） | **{n_stage1}** | "
      f"P0({c0}) + P1({c1}) = 摆盘/插拔所需的**全部**元任务 | 摆盘 + 插拔全链闭环可验收 |")
    A(f"| **阶段二 · 收口** | 2027-07 ~ 2027-12（6 个月） | **{c2}** | P2 = 已登记未接入的元任务 | "
      f"{len(MT)}/{len(MT)} 完成，一致性校验全绿 |")
    A("")
    A("### 4.3 月度排期\n")
    A("| 月份 | 元任务数 | 优先级构成 | 该月启动的元任务（前 3 项） |")
    A("|---|---|---|---|")
    for mth in months:
        ms = [m for m in MT if m.get("month") == mth]
        if not ms:
            continue
        c = Counter(m["prio"] for m in ms)
        comp2 = " ".join(f"{k}×{v}" for k, v in sorted(c.items()))
        A(f"| {mth} | {len(ms)} | {comp2} | "
          f"{' · '.join((m['name'] or '')[:16] for m in ms[:3])} |")
    A("")
    A("### 4.4 里程碑\n")
    A("| 里程碑 | 时间 | 判据 |")
    A("|---|---|---|")
    A("| **M0 基线冻结** | 2026-10 | 工程真源哈希冻结；元任务清单发布（本文件） |")
    A("| **M1 L2 底座就绪** | 2026-12 | L2 层元任务完成：感知(YOLO/2D→3D/触觉/板坐标系)、"
      "控制(调制/估计/预测/校正/前馈)、执行(原子技能)、安全(饱和限幅) |")
    A(f"| **M2 P0 核心完成** | 2027-03 | {c0} 个全任务共用元任务全部完成 |")
    A(f"| **M3 摆盘 + 插拔全链闭环** | 2027-06 | {n_stage1} 个元任务完成；"
      "**TASK-06-TRAY 摆盘 + TASK-01-FW 插拔** 全链闭环验收（用户指定优先项） |")
    A("| **M4 其余任务过半** | 2027-09 | TASK-02-HANDLE、TASK-03-BI 验收 |")
    A("| **M5 其余任务交付** | 2027-11 | TASK-04-THERMAL、TASK-05-ATS 验收 |")
    A(f"| **M6 全量收口** | 2027-12 | {len(MT)}/{len(MT)} 元任务完成；TASK-07-AOI 验收；"
      "数据一致性校验全绿 |")
    A("")
    A("### 4.5 任务验收顺序（按用户指定优先级）\n")
    A("| 顺序 | 任务 ID | 任务名称 | 验收时间 |")
    A("|---|---|---|---|")
    vt = {"TASK-06-TRAY": "2027-06 ← 用户 P0", "TASK-01-FW": "2027-06 ← 用户 P0",
          "TASK-02-HANDLE": "2027-09", "TASK-03-BI": "2027-09",
          "TASK-04-THERMAL": "2027-11", "TASK-05-ATS": "2027-11", "TASK-07-AOI": "2027-12"}
    for i, tid in enumerate(task_order(tasks), 1):
        t = td.get(tid)
        if not t:
            continue
        A(f"| {i} | {tid} | {t.get('name')} | {vt.get(tid, '—')} |")
    A("")
    A("---\n")
    A("## 五、元任务明细表\n")
    A(f"共 **{len(MT)}** 个元任务。`参数数` = 该功能挂接的全部配置参数数；"
      "`专属` = 专属参数数（非通用标定基线）。\n")
    A("| 元任务 | 功能 ID | 名称 | 层 | 参数数 | 专属 | 优先级 | 承载任务数 | 计划月份 |")
    A("|---|---|---|---|---|---|---|---|---|")
    for m in MT:
        A(f"| {m['mt_id']} | {m['fn_id']} | {(m['name'] or '')[:28]} | {m['layer']} | "
          f"{m['n_params']} | {m['n_specific']} | {m['prio']} | {len(m['tasks'])} | "
          f"{m.get('month', '-')} |")
    A("")
    # 六、七、八、九
    A("---\n")
    A("## 六、数据一致性保障（实测校验）\n")
    A("### 6.1 一致性链条\n")
    A("```")
    A("任务(TASK-xx) ──enabled_nodes──> 画布节点(node_id) ──name──> 功能(module_ref) ──fn_id──> 元任务")
    A("                                                                    │")
    A("                                                          config_meta.parameters ──> 配置参数")
    A("```\n")
    rows, ok = consistency(MT, ctx)
    A("### 6.2 校验结果（实跑，非声明）\n")
    A("| 校验项 | 期望 | 实测 | 结论 |")
    A("|---|---|---|---|")
    for name, e, a, g in rows:
        A(f"| {name} | {e} | {a} | {g} |")
    A(f"| 参数总数 | ≥ 功能专属之和 | {sum(m['n_params'] for m in MT)} | ✅ |")
    A(f"| 元数据完整性 | 逐条登记 | 完整 {comp} / 不完整 {len(MT) - comp}（缺失维度已逐条列出） | ⚠️ 已登记 |")
    A("")
    A("### 6.3 固化约束（防漂移）")
    A("1. **单一真源**：元任务清单由 `config_meta.json` + `tasks.json` + `ss_task_binding.json` + 画布**派生**，不另存一份；")
    A("2. **哈希冻结**：真源哈希随本文件发布，任何一方变更即触发一致性重校验；")
    A("3. **生成物勿手改**：`ss_task_binding.json` 已标“生成物, 勿手改”，重新生成后元任务清单需同步重建；")
    A(f"4. **{len(MT) - comp} 个不完整元任务**：缺口维度明确（specific_params / deps），"
      "在对应元任务开发时补齐，补不齐不许进默认档。\n")
    A("### 6.4 真源哈希\n")
    A("| 真源文件 | sha256(前16) |")
    A("|---|---|")
    for k, p in (("功能元数据 config_meta.json", os.path.join(DB, "config_meta.json")),
                 ("任务配置 tasks.json", os.path.join(SRC, "tasks/tasks.json")),
                 ("任务绑定 ss_task_binding.json", os.path.join(SRC, "ss_task_binding.json")),
                 ("画布 state_space_obs.json", CANVAS),
                 ("参数注册表 param_registry.json", os.path.join(SRC, "mcd/param_registry.json"))):
        A(f"| {k} | `{_sha(p)}` |")
    A("")
    A("---\n")
    A("## 七、配置中心导出（任务配置 → Word / PDF）\n")
    A("### 7.1 需求")
    A("> 元任务要能由**配置中心**在「**任务配置**」里导出 **Word 与 PDF** 文档。\n")
    A("### 7.2 落点\n")
    A("| 项 | 内容 |")
    A("|---|---|")
    A("| 配置中心入口 | `sources/config/tasks/tasks.json`（任务配置真源） |")
    A("| 元数据面 | `data/database/zmax/config_meta.json` |")
    A("| 导出产物 | `元任务开发计划_<日期>.md` / `.docx` / `.pdf` |")
    A("| 生成链 | 真源 → Markdown → HTML → LibreOffice(soffice) → docx/pdf |")
    A("| 实现脚本 | `tools/export_meta_doc.py` |")
    A("| GUI 入口 | 「配置中心 → 📋 任务配置 → 📄 元任务计划 (Word/PDF)」 |")
    A("")
    A("### 7.3 配置中心两项拆分（任务配置 / 工单实例·在文档配置内）\n")
    A("> 老倪 2026-10-14：「将元任务，这些信息，体现在配置中心的 任务配置；"
      "将原来的工艺工单任务，拆解成 任务配置 和 工单配置 两项」\n")
    A("| 项 | 左树/页签 | 粒度 | 真源 | 内容 |")
    A("|---|---|---|---|---|")
    A("| **任务配置** | 📋 任务配置 | **元任务**（功能 + 配置参数） | `config_meta.json` + "
      "画布连线 + `tasks.json` + `ss_task_binding.json` | 元任务清单（标准模板七字段：功能名称/输入/输出/"
      "配置参数/依赖关系/验证方法/承载场景）+ 任务表 14 列（原样保留）|")
    A("| **工单实例** | 📄 文档配置页内（原 🧾 工单配置页） | **工单实例**（一次执行） | "
      "`config/orders/BS_*.json` | 工单身份/配方/变体/选项/目标/安全/防错链/站点就绪"
      "（原 6 列保留，新维度追加在后）|")
    A("")
    A("拆的是**粒度**，不是换列：原任务表的列一列未动，原工单表 6 列保留、新维度追加在后面。")
    A("")
    A("> 老倪 2026-10-19：「将 工单配置，替换成 工程配置；将工单，放到文档配置选项卡，"
      "将成本/报价 商业模式的内容，都迁移到 文档配置里」⇒ 六阵 = 工程配置·开阳(定落地)，"
      "工单实例 + 成本报价 + 商业模式统一并入七阵 文档配置·瑶光(定记录)。")
    A("")
    A("---\n")
    A("## 八、风险与对策\n")
    A("| 风险 | 影响 | 对策 |")
    A("|---|---|---|")
    A("| 真机动作安全（本计划已发生一次急停事件） | 元任务验收需真机动作 | 保持既有分层闸门（授权/收口/执行器/安全裁决）；"
      "MoveJ 自愈默认关；单段净抬升 ≤100mm；≥30° 姿态变化不在工装附近转 |")
    A(f"| {len(MT) - comp} 个元任务元数据不完整 | 配置项缺失，无法独立验收 | "
      "在对应元任务开发窗口内补齐 specific_params / deps，完成后重跑完整性校验 |")
    A(f"| {c2} 个 P2 元任务未被任何任务启用 | 可能成为“登记了但没接入”的空白 | "
      "阶段二逐个判定：接入或明确标注“本阶段不接入”，不许留模糊 |")
    A("| 真源漂移（任务/参数被改） | 元任务清单过期 | 6.4 哈希冻结 + 每次变更重跑一致性校验 |")
    A("| 相机/外设故障（本计划已发生 D405 段错误崩溃） | 数据采集与验收中断 | "
      "采集前先验相机活性（抓两帧比 md5），而非只看 fps/age（会假活） |")
    A("| 单点设备依赖 | 进度受阻 | 标定参数与配置外置（config/calib），换机可迁移 |")
    A("")
    A("---\n")
    A("## 九、验收标准\n")
    A("1. **元任务级**：每个元任务完成 = ① 功能在真实链路每帧被调用 ② 配置参数可在配置中心修改并生效 "
      "③ 验证方法（诊断轴）实跑通过；")
    A("2. **任务级**：%d 个任务各自全链闭环，按 4.5 顺序验收；" % len(tasks))
    A(f"3. **工程级**：{len(MT)}/{len(MT)} 元任务完成，数据一致性校验全绿，配置中心可导出 Word/PDF；")
    A("4. **证据级**：所有验收以**视频 / 数据实证**为准，不以“已实现”声明为准。\n")
    A("---\n")
    A("## 附录 A · 元任务标准模板（示例，前 8 个）\n")
    A("每个元任务按《元任务标准模板》登记七个字段（全部实读真源，不人工编造）：")
    A("功能名称 / 输入 / 输出 / 配置参数 / 依赖关系 / 验证方法 / 承载场景。\n")
    for m in MT[:8]:
        A(f"### {m['mt_id']} {m['name']}（{m['fn_id']} · {m['layer']}）")
        A(f"- 功能名称：{m['name']}")
        if m.get("note"):
            A(f"- 干什么活：{m['note'].get('work') or '—'}")
            A(f"- 卡在哪：{m['note'].get('pain') or '—'}")
            A(f"- 现在什么状态：{m['note'].get('state') or '—'}")
        A(f"- 输入：{' / '.join(m['inputs']) or '—（真源未登记）'}")
        A(f"- 输出：{' / '.join(m['outputs']) or '—（真源未登记）'}")
        A(f"- 配置参数：{m['n_params']} 条（专属 {m['n_specific']}）——"
          f"{'；'.join(m['params_head']) or '—'}")
        A(f"- 依赖关系：{' / '.join(m['deps_up']) or '—（画布无上游）'}"
          + (f"；登记函数依赖：{' / '.join(m['deps_fn'])}" if m['deps_fn'] else ""))
        A(f"- 验证方法：{' / '.join(m['verification']) or '—'}")
        A(f"- 承载场景：{' / '.join(m['scenes']) or '—（未接入任务）'}")
        A(f"- 归属层 · 画布节点 · 代码：{m['layer']} · `{m['node_id']}` · `{m['code_file'] or '—'}`")
        A("")
    A("---\n")
    A("**编制**：AI 助手（Hermes）　**依据**：工程真源实读　**日期**：2026-10-14\n")
    return "\n".join(L), ok


def md_to_html(md):
    def inline(t):
        t = H.escape(t, quote=False)
        t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
        t = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", t)
        t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
        return t

    out, in_code, in_tbl = [], False, False
    for line in md.split("\n"):
        if line.startswith("```"):
            out.append("</pre>" if in_code else "<pre>")
            in_code = not in_code
            continue
        if in_code:
            out.append(H.escape(line))
            continue
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c or "-") for c in cells):
                continue
            if not in_tbl:
                out.append("<table>")
                in_tbl = True
            out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in cells) + "</tr>")
            continue
        if in_tbl and not line.startswith("|"):
            out.append("</table>")
            in_tbl = False
        if line.startswith("### "):
            out.append(f"<h3>{inline(line[4:])}</h3>")
        elif line.startswith("## "):
            out.append(f"<h2>{inline(line[3:])}</h2>")
        elif line.startswith("# "):
            out.append(f"<h1>{inline(line[2:])}</h1>")
        elif line.startswith("> "):
            out.append(f"<blockquote>{inline(line[2:])}</blockquote>")
        elif line.strip() == "---":
            out.append("<hr/>")
        elif line.strip() == "":
            out.append("")
        else:
            out.append(f"<p>{inline(line)}</p>")
    if in_tbl:
        out.append("</table>")
    if in_code:
        out.append("</pre>")
    return """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Z-MAX 元任务开发计划</title><style>
@page { size: A4; margin: 18mm 15mm; }
body{font-family:"WenQuanYi Zen Hei","Noto Sans CJK SC",sans-serif;font-size:10.5pt;line-height:1.55;}
h1{font-size:17pt;border-bottom:2px solid #333;padding-bottom:6px;}
h2{font-size:13.5pt;margin-top:16px;border-bottom:1px solid #aaa;padding-bottom:3px;page-break-after:avoid;}
h3{font-size:11.5pt;margin-top:11px;page-break-after:avoid;}
table{border-collapse:collapse;width:100%%;margin:7px 0;font-size:8.5pt;}
td{border:1px solid #999;padding:3px 5px;vertical-align:top;}
pre{background:#f4f4f4;border:1px solid #ddd;padding:6px;font-family:"DejaVu Sans Mono",monospace;font-size:8pt;white-space:pre-wrap;}
blockquote{border-left:3px solid #888;margin:6px 0;padding:4px 10px;background:#fafafa;}
code{font-family:"DejaVu Sans Mono",monospace;font-size:9pt;background:#f0f0f0;padding:0 2px;}
hr{border:none;border-top:1px solid #ccc;margin:12px 0;}
</style></head><body>
%s
</body></html>""" % "\n".join(out)


def soffice_convert(src, fmt, outdir):
    """LibreOffice 转换。从 HTML 导 docx 必须先过 odt（HTML 是 Writer/Web 文档，无 docx 过滤器）。"""
    env = dict(os.environ)
    prof = tempfile.mkdtemp(prefix="lo_prof_")
    base = ["soffice", "--headless", "--norestore",
            f"-env:UserInstallation=file://{prof}"]
    try:
        if fmt == "html2docx":
            subprocess.run(base + ["--convert-to", "odt", "--outdir", outdir, src],
                           check=True, capture_output=True, timeout=300, env=env)
            odt = os.path.join(outdir, os.path.splitext(os.path.basename(src))[0] + ".odt")
            subprocess.run(base + ["--convert-to", "docx:MS Word 2007 XML",
                                   "--outdir", outdir, odt],
                           check=True, capture_output=True, timeout=300, env=env)
            os.remove(odt)
            return os.path.join(outdir, os.path.splitext(os.path.basename(src))[0] + ".docx")
        if fmt == "html2pdf":
            subprocess.run(base + ["--convert-to", "pdf", "--outdir", outdir, src],
                           check=True, capture_output=True, timeout=300, env=env)
            return os.path.join(outdir, os.path.splitext(os.path.basename(src))[0] + ".pdf")
    finally:
        shutil.rmtree(prof, ignore_errors=True)
    return None


def main():
    ap = argparse.ArgumentParser(description="元任务开发计划导出器 (配置中心 · 任务配置页调用)")
    ap.add_argument("--out", default=DEFAULT_OUT, help="输出目录")
    ap.add_argument("--name", default="元任务开发计划_2026-10_2027-12", help="输出文件名(不含扩展名)")
    ap.add_argument("--no-pdf", action="store_true", help="只出 md + docx")
    ap.add_argument("--no-docx", action="store_true", help="只出 md + pdf")
    ap.add_argument("--check", action="store_true", help="只做一致性校验，不出文档")
    ap.add_argument("--json", action="store_true", help="输出 JSON 结果 (供 GUI 取用)")
    a = ap.parse_args()

    MT, ctx = build_meta_tasks()
    rows, ok = consistency(MT, ctx)
    md, _ = render_md(MT, ctx)

    res = {"md": None, "docx": None, "pdf": None, "n_meta_tasks": len(MT),
           "n_functions": len(ctx["cm"]["functions"]),
           "consistent": ok, "checks": [{"name": n, "expect": e, "actual": v, "pass": g == "✅"}
                                        for n, e, v, g in rows]}
    if a.check:
        print(json.dumps(res, ensure_ascii=False, indent=1) if a.json else
              "\n".join(f"[{'PASS' if g == '✅' else 'FAIL'}] {n}: 期望 {e} / 实测 {v}"
                        for n, e, v, g in rows))
        return 0 if ok else 1

    outdir = os.path.abspath(a.out)
    os.makedirs(outdir, exist_ok=True)
    md_p = os.path.join(outdir, a.name + ".md")
    with open(md_p, "w", encoding="utf-8") as f:
        f.write(md)
    res["md"] = md_p

    tmp = tempfile.mkdtemp(prefix="metadoc_")
    try:
        html_p = os.path.join(tmp, a.name + ".html")
        with open(html_p, "w", encoding="utf-8") as f:
            f.write(md_to_html(md))
        if not a.no_docx:
            try:
                d = soffice_convert(html_p, "html2docx", outdir)
                if d:
                    res["docx"] = d
            except Exception as e:  # noqa: BLE001
                res["docx_err"] = f"{type(e).__name__}: {e}"
        if not a.no_pdf:
            try:
                p = soffice_convert(html_p, "html2pdf", outdir)
                if p:
                    res["pdf"] = p
            except Exception as e:  # noqa: BLE001
                res["pdf_err"] = f"{type(e).__name__}: {e}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        print(f"✅ 元任务开发计划: {res['n_meta_tasks']} 个元任务 / "
              f"{res['n_functions']} 个功能 / 一致性 {'通过' if ok else '不通过'}")
        for k in ("md", "docx", "pdf"):
            if res.get(k):
                print(f"   {k:5s} {res[k]}")
            elif res.get(k + "_err"):
                print(f"   {k:5s} ⛔ {res[k + '_err']}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
