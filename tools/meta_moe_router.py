# -*- coding: utf-8 -*-
"""meta_moe_router.py — 元数据MOE门控路由 (原「阶段专家MOE门控路由」, 老倪 2026-10-13 改名定稿)。

老倪口径 (原话):
  「数据源来源于全局数据空间, **元数据是整个系统的数据库根服务**; 再次检查数据一致性; 确保每个元数据都是
   系统的基础核心组成, **类似标准原子模型的玻色子或费米子**, 而**数据空间的每个 topic, 类似各种原子, 分子,
   有机物**等; 映射关系, **全息系统**, 这些逻辑, 都在**阶段专家MOE门控路由**这个节点代码实现,
   同时这个节点改名为 **元数据MOE门控路由**。」

三层一一对应 (本文件的实现口径):
  ① 元数据 = 基础核心组成 (根服务)          →  META_PRIMITIVES: 玻色子型(场/连续量) + 费米子型(离散实体)
  ② topic  = 由元数据组合成的"原子/分子/有机物" →  COMPOSE: 每个 topic 的基元组合 (显式规则表, 可复核)
  ③ 映射关系 + 全息系统                     →  INCIDENCE 矩阵 P(topic×基元) + 全息重构算子 (真线性代数)
  ④ 门控路由 (硬先验, 可复核)               →  ROUTE: 阶段 → 专家 1:1 (单射), 路由熵 0

真源: zmax_data/dataspace/busdb.json (节点/信号/报文) + config/calib/*.json ; 数值全部真算, 缺就报缺。
CLI: python3 tools/meta_moe_router.py report | holography | route
"""
from __future__ import annotations

import argparse
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUSDB = os.path.join(ROOT, "zmax_data", "dataspace", "busdb.json")

# ── ① 元数据: 基础核心组成 (根服务)。标准原子模型类比: 玻色子型=传递相互作用的场量; 费米子型=构成物质的实体。
#    要求: 每条都是**完整定义**, 且**禁算法词** (老倪: 能力特征从能力角度定义, 不写实现算法)。
BANNED_WORDS = ("conv", "attention", "transformer", "mlp", "loss", "训练", "梯度",
                "卷积", "注意力", "sigmoid", "softmax", "embedding", "token", "LSTM", "diffusion")

META_PRIMITIVES = [
    # kind: B=玻色子型(场/连续量)  F=费米子型(离散实体/可数)
    dict(id="m_pos",  kind="B", name="位置",   unit="m",     def_="物体在作业坐标系中的三维坐标 (x,y,z), 描述'在哪里'"),
    dict(id="m_rot",  kind="B", name="姿态",   unit="rad",   def_="物体朝向的四个数表示 (quaternion), 描述'朝哪边'"),
    dict(id="m_vel",  kind="B", name="速度",   unit="m/s",   def_="位置随时间的变化率, 描述'动得多快'"),
    dict(id="m_w",    kind="B", name="角速度", unit="rad/s", def_="姿态随时间的变化率, 描述'转得多快'"),
    dict(id="m_force",kind="B", name="力",     unit="N",     def_="相互作用的推拉量 (含力矩 N·m), 描述'使了多大力'"),
    dict(id="m_time", kind="B", name="时间",   unit="s",     def_="事件发生的时刻与间隔 (含帧龄), 描述'什么时候'"),
    dict(id="m_conf", kind="B", name="置信度", unit="1",     def_="一个观测/判断成立的可信程度 (0~1), 描述'有多大把握'"),
    dict(id="m_health",kind="B",name="健康度", unit="1",     def_="整个系统当前好坏的一个数 H=(1/κ)·λmin, 描述'系统还好不好'"),
    dict(id="m_metric",kind="B",name="主参数M",unit="1",     def_="度量张量 g_ij(x)=M·G_ij(x): 距离与方向怎么算, 描述'几何尺度与形状'"),
    dict(id="m_flux", kind="B", name="通量",   unit="1/s",   def_="单位时间通过的数据量/速率 (hz), 描述'流淌得多快'"),
    dict(id="m_node", kind="F", name="节点",   unit="-",     def_="一个可执行的处理单元 (画布节点), 描述'谁在做'"),
    dict(id="m_topic",kind="F", name="话题",   unit="-",     def_="一条有名字的数据通道, 描述'数据从哪条路走'"),
    dict(id="m_layer",kind="F", name="层级",   unit="-",     def_="处理所处的能力层 (L2 检测/L3 调度/L4 认知/L5 规划), 描述'在哪一层'"),
    dict(id="m_stage",kind="F", name="阶段",   unit="-",     def_="工序处于的步骤 (接近/对位/下降/抓取/抬起/转移/插入), 描述'进行到哪一步'"),
    dict(id="m_skill",kind="F", name="技能",   unit="-",     def_="可复用的原子动作条目, 描述'用哪一手'"),
    dict(id="m_msg",  kind="F", name="报文",   unit="-",     def_="一段有类型名的结构化数据集合, 描述'这一包是什么东西'"),
    dict(id="m_scene",kind="F", name="场景",   unit="-",     def_="任务所处的工况 (插拔/摆盘/AR), 描述'在什么场合'"),
    dict(id="m_task", kind="F", name="任务",   unit="-",     def_="一件被指派的工作 (含工单号), 描述'要干哪件活'"),
]

# ── ② 映射关系: topic 由哪些基元组合而成 (显式规则表; 每条规则可在 busdb 里复核)
#    规则字段: 命中条件 (topic 名/报文类型/连线标签/层) → 基元 id 列表
COMPOSE_RULES = [
    (r"(pose|tcp|xyz|position|loc)",      ["m_pos", "m_rot"]),
    (r"(joint|angle|quat|rot|yaw)",       ["m_rot"]),
    (r"(vel|speed|action|u_|cmd)",        ["m_vel", "m_w"]),
    (r"(force|torque|contact|tactile)",   ["m_force"]),
    (r"(hz|fps|rate|flux|kbps)",          ["m_flux", "m_time"]),
    (r"(监控|信号|波形|scope|总线|数据空间|流|video|视频|live|实时)", ["m_flux", "m_time"]),
    (r"(ts|time|age|latency|tick)",       ["m_time"]),
    (r"(conf|score|prob|verdict|qual)",   ["m_conf"]),
    (r"(health|state|status|估计|健康|监测|监控)", ["m_health", "m_conf"]),
    (r"(定位|姿|camera|相机|标定|calib)",   ["m_pos", "m_rot"]),
    (r"(速度|加速|前馈|速度场|流形|群)",    ["m_vel"]),
    (r"(力|接触|触觉|夹爪|夹持|抓取)",      ["m_force"]),
    (r"(场景|工况|插拔|摆盘|AR-)",         ["m_scene"]),
    (r"(任务|工单|order|task|TASK-)",      ["m_task"]),
    (r"(调度|规划|planner|sched|技能序列|状态机)", ["m_stage", "m_skill"]),
    (r"(旋转|朝向|yaw|roll|pitch)",        ["m_rot"]),
    (r"(mani|metric|homeo|geom|calib)",   ["m_metric", "m_pos"]),
    (r"(link|topic|bus|msg|report)",      ["m_topic", "m_msg"]),
    (r"(detect|yolo|seg|aoi|inspect)",    ["m_conf", "m_pos"]),
    (r"(skill|atomic|muscle|memory)",     ["m_skill"]),
    (r"(task|order|work)",                ["m_task"]),
]
LAYER_RE = re.compile(r"^L[2-5]$")
STAGES = ("接近", "对位", "下降", "抓取", "抬起", "转移", "插入")


def load_busdb(path=None) -> dict:
    with open(path or BUSDB, encoding="utf-8") as f:
        return json.load(f)


def _layer_of(sig: dict) -> str:
    return str(sig.get("layer") or "").upper() if LAYER_RE.match(str(sig.get("layer") or "").upper()) else ""


def topic_catalog(db: dict | None = None) -> list[dict]:
    """全局数据空间里的全部 topic (含合成) + 它们的结构信息 (组合映射的输入)。"""
    db = db or load_busdb()
    nodes = db.get("nodes") or {}

    def _nm(nid):
        n = nodes.get(nid) or {}
        return " ".join(str(x) for x in (n.get("name") or "", n.get("icon") or ""))

    out, seen = [], {}
    for s in (db.get("signals") or []):
        if not isinstance(s, dict):
            continue
        key = s.get("key") or s.get("topic") or ""
        if not key:
            continue
        if key in seen:
            seen[key]["links"].append({"src": s.get("src"), "dst": s.get("dst"),
                                       "label": s.get("label"), "layer": s.get("layer")})
            _extra = " ".join([_nm(s.get("src")), _nm(s.get("dst"))]).strip()
            if _extra and _extra not in (seen[key].get("names") or ""):
                seen[key]["names"] = ((seen[key].get("names") or "") + " " + _extra).strip()
            if s.get("layer") and not seen[key]["layer"]:
                seen[key]["layer"] = s.get("layer")
            continue
        ent = {"topic": key, "node_id": s.get("node_id") or s.get("src") or "",
               "layer": s.get("layer") or "", "synth": bool(s.get("synth")),
               "kind": s.get("kind") or "",
               "names": " ".join([_nm(s.get("src")), _nm(s.get("dst"))]),
               "links": [{"src": s.get("src"), "dst": s.get("dst"),
                          "label": s.get("label"), "layer": s.get("layer")}]}
        seen[key] = ent
        out.append(ent)
    for k, m in (db.get("messages") or {}).items():
        t = m.get("topic") or k
        if t in seen:
            seen[t]["msg_type"] = m.get("type") or ""
            seen[t]["qos"] = m.get("qos") or ""
            continue
        ent = {"topic": t, "node_id": m.get("producer") or "", "layer": "", "synth": False, "kind": "typed",
               "msg_type": m.get("type") or "", "qos": m.get("qos") or "",
               "names": str(m.get("name") or m.get("desc") or ""), "links": []}
        seen[t] = ent
        out.append(ent)
    return out


def compose(topic_entry: dict, prim_ids: set | None = None) -> list[str]:
    """一个 topic ← 哪些元数据基元 (显式规则; 无命中则只给通用基元, 并如实标 generic)。"""
    prim_ids = prim_ids or {p["id"] for p in META_PRIMITIVES}
    hay = " ".join([str(topic_entry.get("topic") or ""), str(topic_entry.get("msg_type") or ""),
                    str(topic_entry.get("names") or ""),      # 源/宿节点能力名 (语义主源)
                    topic_entry.get("kind") or "",
                    " ".join(str(l.get("label") or "") for l in (topic_entry.get("links") or []))]).lower()
    got = []
    for pat, ids in COMPOSE_RULES:
        if re.search(pat, hay, re.I):
            for i in ids:
                if i in prim_ids and i not in got:
                    got.append(i)
    lay = str(topic_entry.get("layer") or "").upper()
    if LAYER_RE.match(lay) and "m_layer" in prim_ids:
        got.append("m_layer")
    if topic_entry.get("synth") and "m_node" in prim_ids:
        got.append("m_node")                     # 合成 topic 直接挂在其产出节点上
    if topic_entry.get("links") and "m_topic" in prim_ids and "m_topic" not in got:
        got.append("m_topic")
    if any(x in (topic_entry.get("topic") or "") for x in ("task", "order")) and "m_task" in prim_ids:
        got.append("m_task")
    for st in STAGES:
        if st in hay and "m_stage" in prim_ids:
            got.append("m_stage")
            break
    if not got:
        got = [i for i in ("m_topic", "m_msg") if i in prim_ids]     # generic: 仍是核心组成, 不硬凑
    return got


def incidence(db: dict | None = None):
    """映射关系矩阵: rows=topic, cols=元数据基元 (0/1)。全息系统的载体。"""
    db = db or load_busdb()
    cats = topic_catalog(db)
    prims = [p["id"] for p in META_PRIMITIVES]
    idx = {p: i for i, p in enumerate(prims)}
    P = []
    rows = []
    for t in cats:
        comp = compose(t)
        v = [0] * len(prims)
        for c in comp:
            if c in idx:
                v[idx[c]] = 1
        P.append(v)
        rows.append({"topic": t["topic"], "primitives": comp})
    return {"topics": [t["topic"] for t in cats], "primitives": prims, "P": P, "rows": rows}


# ── ③ 全息系统: 整体编码在每一部分里 —— 任意足够大的 topic 子集都能重构出整体签名 ──────────────
def holography(db: dict | None = None, n_trials: int = 200, seed: int = 0) -> dict:
    """真线性代数: 全息系统 = 任意足够大的 topic 子集都编码**同一个**整体算子。

    映射关系矩阵 A (rows=topic, cols=元数据基元)。行空间投影算子 Pr = pinv(A)·A 是"整体"的可计算表达。
    全息性 = 从任意子集 S 算出的 Pr_S 与 Pr_full 一致 (差为 0) ⇒ 部分真的携带整体。
    诚实边界: 未被任何 topic 使用的基元**不在**行空间里 ⇒ 不可重构 (报不可重构基元清单 + 不可约残差),
    绝不把它粉饰成"全息成立"。
    """
    import random

    inc = incidence(db)
    prims, P = inc["primitives"], inc["P"]
    if not P:
        return {"ok": False, "why": "无 topic (busdb 为空)"}
    try:
        import numpy as np
    except Exception as e:                                                          # noqa: BLE001
        return {"ok": False, "why": "numpy 不可用: %r" % (e,)}
    A = np.array(P, dtype=float)
    n_t, n_p = A.shape
    rank = int(np.linalg.matrix_rank(A))
    if rank == 0:
        return {"ok": False, "why": "映射矩阵全零"}
    Pr_full = np.linalg.pinv(A) @ A                      # 行空间投影算子 (整体)
    used = [prims[i] for i in range(n_p) if float(np.linalg.norm(A[:, i])) > 0]
    unused = [prims[i] for i in range(n_p) if float(np.linalg.norm(A[:, i])) == 0]

    rng = random.Random(seed)
    s = np.array([rng.random() for _ in range(n_p)], dtype=float)
    resid = float(np.linalg.norm(s - Pr_full @ s))       # 不可约残差 (落在行空间外)
    rel = float(resid / max(1e-12, float(np.linalg.norm(s))))

    # 实证: 随机子集规模 m → 撑起整体行空间 (秩 == rank) 的比例; 取比例 ≥0.9 的最小 m
    def _rate(m, trials=60, seed0=12345):
        r2 = random.Random(seed0)
        hit = 0
        for _ in range(trials):
            S = sorted(r2.sample(range(n_t), min(m, n_t)))
            hit += int(int(np.linalg.matrix_rank(A[S, :])) == rank)
        return hit / trials

    rate_curve, k_whole_90 = {}, None
    for m in sorted({min(x, n_t) for x in (rank, rank + 2, rank + 4, rank + 6, rank + 8,
                                           int(0.15 * n_t), int(0.3 * n_t), int(0.5 * n_t), n_t)}):
        rate_curve[m] = _rate(m)
        if k_whole_90 is None and rate_curve[m] >= 0.9:
            k_whole_90 = m
    k_use = k_whole_90 or n_t
    errs, rank_ok = [], []
    for _ in range(n_trials):
        S = sorted(rng.sample(range(n_t), min(k_use, n_t)))
        A_S = A[S, :]
        Pr_S = np.linalg.pinv(A_S) @ A_S
        errs.append(float(np.max(np.abs(Pr_S - Pr_full))))     # 算子一致性
        rank_ok.append(int(np.linalg.matrix_rank(A_S)) == rank)
    # 退化反证: 比 k_min 少一个 topic ⇒ 应出现不一致
    deg = None
    if k_use > 1:
        worst = 0.0
        for _ in range(30):
            S = sorted(rng.sample(range(n_t), k_use - 1))
            A_S = A[S, :]
            worst = max(worst, float(np.max(np.abs((np.linalg.pinv(A_S) @ A_S) - Pr_full))))
        deg = worst
    return {"ok": True, "n_topics": n_t, "n_primitives": n_p, "rank": rank,
            "primitives_used": len(used), "primitives_unused": unused,
            "k_topics_for_whole_90pct": k_use, "subset_rank_rate_curve": rate_curve, "trials": n_trials,
            "max_op_err": max(errs), "mean_op_err": sum(errs) / len(errs),
            "subset_rank_ok_rate": sum(1 for x in rank_ok if x) / len(rank_ok),
            "degraded_op_err_at_k_minus_1": deg,
            "holographic": bool(max(errs) < 1e-9),
            "irreducible_residual": resid, "irreducible_residual_rel": rel,
            "note": "不可约残差来自未被任何 topic 使用的基元 (它们没有落到数据里); 全息成立范围 = 行空间 rank 维",
            "seed": seed}


# ── ④ 门控路由: 硬先验 (阶段 → 专属专家 1:1) + 单射性/熵 ────────────────────────────────
def route_table() -> dict:
    """硬先验门控路由表 (可复核): 7 阶段 → 7 专家, 一一对应 (单射)。"""
    return {st: i for i, st in enumerate(STAGES)}


def route(stage_prob: list | dict | None = None) -> dict:
    """门控: 硬先验 — 由阶段概率 (skill_ctx dim13:20) 取 argmax ⇒ 唯一专家; 单射性/路由熵真算。"""
    import math
    if isinstance(stage_prob, dict):
        p = [float(stage_prob.get(s, 0.0)) for s in STAGES]
    elif isinstance(stage_prob, (list, tuple)) and len(stage_prob) == len(STAGES):
        p = [float(x) for x in stage_prob]
    else:
        p = [1.0 if i == 0 else 0.0 for i in range(len(STAGES))]      # 缺输入: 取首阶段 (明确而非随机)
    tot = sum(p) or 1.0
    p = [x / tot for x in p]
    k = max(range(len(p)), key=lambda i: p[i])
    ent = -sum(x * math.log(x + 1e-12) for x in p)
    return {"stage": STAGES[k], "expert": k, "argmax_p": p[k], "entropy": ent,
            "routing": "prior" if p[k] >= 0.999 else "argmax-of-input"}


def report(db: dict | None = None) -> dict:
    """节点用的一页报告: 元数据/组合覆盖/全息/路由 (全部真值)。"""
    db = db or load_busdb()
    cats = topic_catalog(db)
    inc = incidence(db)
    comp = {r["topic"]: r["primitives"] for r in inc["rows"]}
    covered = sum(1 for r in inc["rows"] if r["primitives"])
    generic = sum(1 for r in inc["rows"] if r["primitives"] == ["m_topic", "m_msg"])
    bose = [p["id"] for p in META_PRIMITIVES if p["kind"] == "B"]
    fermi = [p["id"] for p in META_PRIMITIVES if p["kind"] == "F"]
    used = sorted({x for r in inc["rows"] for x in r["primitives"]})
    return {"primitives": len(META_PRIMITIVES), "bose": len(bose), "fermi": len(fermi),
            "primitives_used": len(used), "primitives_unused": [p for p in [x["id"] for x in META_PRIMITIVES] if p not in used],
            "topics": len(cats), "topics_covered": covered, "topics_generic_only": generic,
            "coverage_pct": round(100.0 * covered / max(1, len(cats)), 1),
            "holography": holography(db), "route_prior": route_table(),
            "stage_injective": len(set(route_table().values())) == len(STAGES) == len(route_table()),
            "sample": {k: comp[k] for k in list(comp)[:5]}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="report", choices=("report", "holography", "route"))
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    if a.cmd == "report":
        r = report()
        print(json.dumps({k: v for k, v in r.items() if k != "holography"}, ensure_ascii=False, indent=1))
        print("holography:", json.dumps(r["holography"], ensure_ascii=False))
    elif a.cmd == "holography":
        print(json.dumps(holography(seed=a.seed), ensure_ascii=False, indent=1))
    else:
        print(json.dumps({**route(), "table": route_table()}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
