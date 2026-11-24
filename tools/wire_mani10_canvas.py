#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wire_mani10_canvas.py — 把十维引擎(ss_mani10)与黎曼梯度流(ss_mani_flow)接进状态空间画布

两个 JSON 都要改 (studio 读 data/database/... 真身, 完备性判据读 flows/...):
    data/database/zmax/sources/canvas/state_space_obs.json   ← studio 实际加载 (src/.../flows/ 是软链)
    flows/state_space_obs.json                                ← tools/canvas_completeness_check.py 读这份

同时把两个既有断头接上 (相图 → 3D 视图, UPH 节拍 → 动作调制), 让完备性判据能全绿。
幂等: 已存在同名节点/连线就更新坐标与 params, 不重复插入。写盘前备份 .bak_wire_<ts>。
"""
from __future__ import annotations

import json
import os
import shutil
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LIVE = os.path.join(ROOT, "data/database/zmax/sources/canvas/state_space_obs.json")
FLOW = os.path.join(ROOT, "flows/state_space_obs.json")

X10_PARAMS = {
    "state_space": True, "kind": "real", "src_engine": "ss_mani10",
    "role": "4D 宏观(x,y,z,θ) ⊕ 6D 隐藏(力/公差/置信度) 的块对角度规; 动作走带隐藏硬约束的 active-set QP",
    "api": "build_metric() · utilization() · violation_error() · constrained_step() · step10()",
    "gate": "输出 gate.force_ok / gate.conf_ok —— L2 引擎闸(engine_gate)认这两个字段",
    "source": "src/lerobot/manifold/core/manifold10d.py",
    "source_symbol": "def step10",
    "note": "只出动作增量与门控量, 不下发运动; 下发仍走 l2_daemon + 8793 授权",
}

FLOW_PARAMS = {
    "state_space": True, "kind": "real", "src_engine": "ss_mani_flow",
    "role": "Δξ = −α·G(u(X))⁻¹∇V + 每步硬投影; Armijo 保证 V 单调下降; 速率限幅保物理可执行",
    "api": "analytic_grad() · riemannian_step() · run_flow() · selftest_flow()",
    "evidence": "解析∇V vs 有限差分 rel 7.4e-9 · 黎曼 43 步到 V=5.9e-10 · 欧氏同起点 300 步仍 4.44 · 越界 0",
    "source": "src/lerobot/manifold/core/flow10d.py",
    "source_symbol": "def run_flow",
    "note": "action6 取第一步位移(收敛后 ΔX≈0, 取末态等于不发动作)",
}


def upsert_node(nodes: list, node: dict) -> str:
    for i, n in enumerate(nodes):
        if n.get("id") == node["id"]:
            nodes[i] = {**n, **node}
            return "updated"
    nodes.append(node)
    return "added"


def upsert_link(links: list, link: dict) -> str:
    for i, l in enumerate(links):
        if l.get("id") == link["id"]:
            links[i] = {**l, **link}
            return "updated"
    links.append(link)
    return "added"


def patch(path: str) -> dict:
    d = json.load(open(path, encoding="utf-8"))
    nodes, links = d["nodes"], d["links"]
    res = {"nodes": [], "links": []}

    res["nodes"].append(("ss_mani10", upsert_node(nodes, {
        "id": "ss_mani10", "type": "model",
        "name": "🧮 十维流形引擎 (4D 宏观 ⊕ 6D 隐藏 · 块对角度规 · 隐藏量硬约束)",
        "x": 5020, "y": 1860, "w": 340, "h": 130, "icon": "🧮",
        "color": "#7bdcb5", "params": X10_PARAMS})))
    res["nodes"].append(("ss_mani_flow", upsert_node(nodes, {
        "id": "ss_mani_flow", "type": "model",
        "name": "🌀 十维黎曼梯度流 (Δξ=−αG⁻¹∇V · Armijo 单调 · 每步投影回 M6)",
        "x": 5420, "y": 1860, "w": 340, "h": 130, "icon": "🌀",
        "color": "#8f7bff", "params": FLOW_PARAMS})))

    for lk in [
        {"id": "lkw_1124_sensor_m10", "f": "sssensor", "t": "ss_mani10",
         "f_port": "out2", "t_port": "in1",
         "label": "43D 状态(位姿+力+公差) → 十维 X10 (4 宏观 + 6 隐藏)"},
        {"id": "lkw_1124_meng_m10", "f": "ss_mani_eng", "t": "ss_mani10",
         "f_port": "out1", "t_port": "in2",
         "label": "流形坐标 p / 度规 M → 十维参考点 X_ref"},
        {"id": "lkw_1124_m10_flow", "f": "ss_mani10", "t": "ss_mani_flow",
         "f_port": "out1", "t_port": "in1",
         "label": "X10 当前状态 → 沿 −G⁻¹∇V 走测地线"},
        {"id": "lkw_1124_flow_sched", "f": "ss_mani_flow", "t": "sssched",
         "f_port": "out1", "t_port": "in10",
         "label": "action6 (第一步位移, 已限幅) → 动作调制"},
        {"id": "lkw_1124_m10_phase", "f": "ss_mani10", "t": "ss_phase_corr",
         "f_port": "out2", "t_port": "in2",
         "label": "V / 利用率 / 闸门 → 相空间通道判据"},
        {"id": "lkw_1124_flow_phaseview", "f": "ss_mani_flow", "t": "ss_phase_view",
         "f_port": "out2", "t_port": "in2",
         "label": "V 轨迹 (单调下降曲线) → 相图"},
        {"id": "lkw_1124_phaseview_3d", "f": "ss_phase_view", "t": "ss3d_view",
         "f_port": "out1", "t_port": "in2",
         "label": "相图 → 3D 可视化 (接断头, 原为死端)"},
        {"id": "lkw_1124_uph_sched", "f": "ssuph", "t": "sssched",
         "f_port": "out1", "t_port": "in11",
         "label": "节拍 (UPH 循环) → 动作节拍 (接断头, 原为死端)"},
    ]:
        res["links"].append((lk["id"], upsert_link(links, lk)))

    shutil.copy2(path, "%s.bak_wire_%s" % (path, time.strftime("%H%M%S")))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    res["count"] = (len(nodes), len(links))
    return res


def main() -> int:
    for p in (LIVE, FLOW):
        if not os.path.exists(p):
            print("!! 缺文件", p)
            return 1
        r = patch(p)
        print("%s\n   节点 %d / 连线 %d · 新增 %s · 更新 %s"
              % (os.path.relpath(p, ROOT), r["count"][0], r["count"][1],
                 sum(1 for _, s in r["nodes"] + r["links"] if s == "added"),
                 sum(1 for _, s in r["nodes"] + r["links"] if s == "updated")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
