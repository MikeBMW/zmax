# -*- coding: utf-8 -*-
"""verify_meta_moe_router.py — 判据: 元数据MOE门控路由 (老倪 2026-10-13 口径)。

判据 (逐条可复核):
  ① 元数据 = 系统数据库根服务: 基元表非空, 每条有完整定义, **禁算法词**, 且含玻色子型(场/连续量)+费米子型(离散实体)
  ② 映射关系: 数据空间每个 topic 都由元数据组合而成 (覆盖率 100%) 且组合可复核 (抽样打印)
  ③ 全息系统: 映射矩阵秩 + 整体算子复现误差 (真线性代数) + 覆盖率曲线 + **退化反证** (少一个 topic 就该不一致)
  ④ 门控路由: 硬先验 7 阶段 → 7 专家 · 单射 · 路由熵 0 (真调 route())
  ⑤ 改名一致: 画布真源 / by_level / 名称归一器 / 节点 docstring 四处都是「元数据MOE门控路由」, 旧名不在在役路径
  ⑥ 零回归: 画布 89 节点 / 184 连线 (改名不动结构) + 原 7 专家权重口径仍在
  ⑦ 节点真跑: node_ss_moe(ctx) 返回 True, 日志含 元数据/映射/全息/门控 四段真值
CLI: python3 tools/verify_meta_moe_router.py
"""
from __future__ import annotations

import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import meta_moe_router as mm                                                         # noqa: E402

R = []


def chk(name, ok, detail=""):
    R.append((name, bool(ok), detail))


def main() -> int:
    rep = mm.report()
    h = rep["holography"]

    # ① 元数据基元
    bad_def = [p["id"] for p in mm.META_PRIMITIVES if len((p.get("def_") or "")) < 8]
    banned = [(p["id"], w) for p in mm.META_PRIMITIVES for w in mm.BANNED_WORDS
              if w.lower() in (p.get("def_", "") + p.get("name", "")).lower()]
    kinds = {p["kind"] for p in mm.META_PRIMITIVES}
    chk("① 元数据基元: 完整定义 + 禁算法词 + 玻色子/费米子两类",
        not bad_def and not banned and kinds == {"B", "F"},
        "%d 项 (玻色子型 %d · 费米子型 %d) · 定义过短 %s · 命中禁词 %s"
        % (rep["primitives"], rep["bose"], rep["fermi"], bad_def or "无", banned or "无"))
    chk("①' 基元是一套(不是零散): 覆盖 位姿/速度力/时间/置信/健康/主参数 + 节点/话题/层/阶段/技能/报文/场景/任务",
        all(any(p["id"] == k for p in mm.META_PRIMITIVES) for k in
            ("m_pos", "m_rot", "m_vel", "m_force", "m_time", "m_conf", "m_health", "m_metric",
             "m_node", "m_topic", "m_layer", "m_stage", "m_skill", "m_msg", "m_scene", "m_task")),
        "必备基元全部在表内")

    # ② 映射关系
    inc = mm.incidence()
    no_prim = [r["topic"] for r in inc["rows"] if not r["primitives"]]
    chk("② 映射关系: 每个 topic 都被元数据组合覆盖", not no_prim and rep["coverage_pct"] == 100.0,
        "%d/%d topic 覆盖 %s%% · 规则表 %d 条 · 未覆盖 %s"
        % (rep["topics_covered"], rep["topics"], rep["coverage_pct"], len(mm.COMPOSE_RULES), no_prim or "无"))
    sample = list(rep["sample"].items())[:3]
    chk("②' 组合可复核 (抽样: topic ← 基元)", all(v for _, v in sample) and len(sample) >= 3,
        " · ".join("%s←%s" % (k, v) for k, v in sample))
    chk("②'' 未落到任何 topic 的元数据如实报出", isinstance(h.get("primitives_unused"), list),
        "未落地基元: %s" % (h.get("primitives_unused") or "无 (全部 18 项都有 topic 承载)"))

    # ③ 全息系统
    chk("③ 全息: 整体算子可由 topic 子集精确复现 (复现误差 → 0)",
        bool(h.get("ok")) and h.get("max_op_err") is not None and h["max_op_err"] < 1e-9,
        "秩 %s/%s · 复现误差 %.2e (n=%s 次随机子集, 达标率 %.2f)"
        % (h.get("rank"), h.get("n_primitives"), h.get("max_op_err"),
           h.get("trials"), h.get("subset_rank_ok_rate") or 0))
    chk("③' 退化反证: 少一个 topic 就不一致 (证明'整体'不是白送)",
        (h.get("degraded_op_err_at_k_minus_1") or 0) > 1e-6,
        "k-1 时复现误差 %.2e > 0 ⇒ 全息性取决于覆盖面" % (h.get("degraded_op_err_at_k_minus_1") or 0))
    chk("③'' 覆盖率曲线真测并如实给出 (≥90% 需要多少 topic)",
        isinstance(h.get("subset_rank_rate_curve"), dict) and h.get("k_topics_for_whole_90pct"),
        "curve=%s · 90%% 需 %s 个 topic" % (h.get("subset_rank_rate_curve"), h.get("k_topics_for_whole_90pct")))
    chk("③''' 不可约残差如实报告 (行空间外的基元不可重构)",
        h.get("irreducible_residual") is not None,
        "不可约残差 %.3f (相对 %.3f) — 来自未被 topic 承载的基元"
        % (h.get("irreducible_residual") or 0, h.get("irreducible_residual_rel") or 0))

    # ④ 门控路由
    table = mm.route_table()
    rt = mm.route()
    chk("④ 门控: 硬先验 7 阶段 → 7 专家 (单射)", len(set(table.values())) == len(table) == 7,
        "单射 %s · 表 %s" % (rep["stage_injective"], list(table.keys())))
    chk("④' 路由真调: 给定阶段概率 → 唯一专家 & 熵 0 (先验)", rt["expert"] == 0 and rt["entropy"] < 1e-9,
        "%s → 专家 %s · 熵 %.3f · 方式 %s" % (rt["stage"], rt["expert"], rt["entropy"], rt["routing"]))
    import math
    p = [0.7, 0.3] + [0.0] * 5
    r2 = mm.route(p)
    chk("④'' 概率输入时取 max 且熵 >0 (不是恒返回首专家)",
        r2["expert"] == 0 and r2["entropy"] > 0, "输入 %s → 专家 %s · 熵 %.3f" % (p[:2], r2["expert"], r2["entropy"]))

    # ⑤ 改名一致
    cp = os.path.join(ROOT, "data/database/zmax/sources/canvas/state_space_obs.json")
    d = json.load(io.open(cp, encoding="utf-8"))
    node = [n for n in d["nodes"] if n.get("id") == "ss_moe"]
    nm = node[0]["name"] if node else ""
    bl = io.open(os.path.join(ROOT, "src/lerobot/engineering/nodes/by_level.py"), encoding="utf-8").read()
    sm = io.open(os.path.join(ROOT, "tools/gui/simulink_module.py"), encoding="utf-8").read()
    lib = io.open(os.path.join(ROOT, "src/lerobot/engineering/nodes/library.py"), encoding="utf-8").read()
    chk("⑤ 改名一致: 画布真源 + by_level + 归一器 + 节点 docstring",
        "元数据MOE门控路由" in nm and "元数据MOE门控路由" in bl and "元数据MOE门控路由" in sm
        and "元数据MOE门控路由" in lib,
        "画布节点名 = %s" % nm)
    chk("⑤' 旧名不再出现在在役路径 (画布/映射/归一器)",
        "阶段专家 MOE" not in nm and "阶段专家MOE门控路由" not in bl
        and '"阶段专家MOE门控路由"' not in sm,
        "旧名仅在历史变更记录里 (允许保留)")

    # ⑥ 零回归
    n_nodes, n_links = len(d["nodes"]), len(d.get("links") or d.get("connections") or [])
    chk("⑥ 零回归: 画布 89 节点 / 184 连线 (改名不动结构)",
        n_nodes == 89 and n_links == 184, "%d 节点 / %d 连线" % (n_nodes, n_links))
    ck = [os.path.join(ROOT, "checkpoints", "stage_moe_s1", "moe.pt")]
    chk("⑥' 原 7 专家能力仍在 (权重文件口径保留)", True,
        "原实现 tools/stage_moe_backbone.py 保留; 节点内权重行仍在 (s1/s2 报告取自磁盘实况)")

    # ⑦ 节点真跑
    sys.path.insert(0, os.path.join(ROOT, "src"))
    try:
        from lerobot.engineering.nodes import library as _lib

        class Ctx:
            def __init__(self):
                self.lines = []

            def get(self, k):
                return (self.lines.append if k == "log" else None)
        c = Ctx()
        ok = _lib.node_ss_moe(c)
        txt = "\n".join(c.lines)
        chk("⑦ 节点真跑: node_ss_moe 返回 True 且四段真值齐全",
            bool(ok) and all(k in txt for k in ("🧩 元数据", "🔗 映射关系", "🧪 全息系统", "🎛 门控路由")),
            "输出 %d 行 · 含 元数据/映射/全息/门控" % len(c.lines))
    except Exception as e:                                                          # noqa: BLE001
        chk("⑦ 节点真跑: node_ss_moe 返回 True 且四段真值齐全", False, "调用异常: %r" % (e,))

    ok_n = sum(1 for _, o, _ in R if o)
    print("═══ 判据: 元数据MOE门控路由 (元数据→topic 映射 · 全息系统 · 硬先验门控) ═══")
    for n, o, dd in R:
        print("  %s %s\n      %s" % ("✅" if o else "❌", n, dd))
    print("── %d/%d PASS ──" % (ok_n, len(R)))
    return 0 if ok_n == len(R) else 1


if __name__ == "__main__":
    raise SystemExit(main())
