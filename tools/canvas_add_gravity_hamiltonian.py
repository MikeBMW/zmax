#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🌍 canvas_add_gravity_hamiltonian.py — 把「万有引力 · SE(3) 几何阻抗 + H=K+U」节点接进状态空间画布

老倪 2026-10-25:
  「按照你的建议来，增加万有引力节点。要保证所有层都能受控于这个力，因为力场才是空间的本质。
    我要基于万有引力，计算状态空间的动能和势能 … 要不改成哈密顿力学？H=K+U，你来设计公式和用户 UI」

位置语义（不是肉眼挑的）:
  · 它必须站在 **Flow-Matching 输出之后、MoveIt 之前**（FM 给名义动作, 阻抗按力场修正, 再进规划）；
  · 它必须**收全所有层的动作**（L2/L3/L4/L5 + 安全边界 + 真值），所以入边来自各层代表节点；
  · 它的量纲与下游不同（N/N·m vs m/s），因此**独占一条到收口的力/力矩边**，不与 action 边混用。

硬断言（全部程序化，不靠肉眼）:
  ① 新节点 x 落在满足 "所有入边前向 + 出边到 n_moveit 前向" 的可行区间内；
  ② 与既有节点零重叠、落在既有行带内、坐标全 int；
  ③ 入边数 == 层数(4) + 安全 + 真值，出边 2 条，全前向、无重复；
  ④ 幂等（已存在则跳过）。

用法（**必须先停 studio**，否则 GUI 会把内存版画布写回覆盖）:
    ./gui-venv311/bin/python tools/canvas_add_gravity_hamiltonian.py --apply
"""
from __future__ import annotations

import argparse
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOW = os.path.join(ROOT, "flows", "state_space_obs.json")

NID = "ss_grav_h"
NAME = "🌍 万有引力 · SE(3) 几何阻抗 + H=K+U (力场仲裁)"
W, H = 300, 130

# 入边：四层各一个代表 + 安全边界 + 真值 ⇒ 「所有层受控于这个力」
INPUTS = [
    ("ssvlm",    "L5 意图/条件 → 势场边界"),
    ("ssintact", "L4 自主决策 → 名义位姿 g_d"),
    ("ssdec",    "L3 Flow-Matching → 名义动作 (ξ_d)"),
    ("sssched",  "L2 动作调制 → 技能动作 a"),
    ("sslimit",  "安全边界 → 力/力矩限幅"),
    ("ssz700",   "真机真值 tcp_pose(50Hz) → ξ 实测"),
]
# 出边：名义动作继续走规划；力/力矩单开一条进收口（不与 action 混用）
OUTPUTS = [
    ("n_moveit", "修正后动作 (力场裁剪) → MoveIt"),
    ("n_exec",   "u(6)=[F;M] 力/力矩 → L2 收口 (默认关)"),
]

PARAMS = {
    "state_space": True,
    "gravity_field": True,
    "kind": "real",
    "role": "全层力场仲裁 — 势能 U 决定允许方向, 动能 K 决定代价, H=K+U 判被动性",
    # 公式（与源码逐式对应）
    "formula_U": "U = ½·ξ_eᵀ K ξ_e + Σ_l ½·s_l·ξ_eᵀ K ξ_e  (Σ_l s_l = 1) + U_grav",
    "formula_K": "K = ½·ξᵀ Λ ξ,  Λ = diag(m,m,m,Ix,Iy,Iz)",
    "formula_H": "H = K + U ;  ξ̇ = Λ⁻¹(F − Bξ) ;  Ḣ = −ξᵀBξ ≤ 0 (交叉项精确抵消)",
    "formula_F": "F_l = s_l·K ξ_e  (逐层力) ;  Σ_l F_l = K ξ_e (恒等式)",
    "K_diag": "平移 [k_lat,k_lat,k_ax]=[80,80,400] N/m · 旋转 [2,2,10] N·m/rad",
    "layer_share": "L2 0.30 · L3 0.25 · L4 0.30 · L5 0.15 (Σ=1)",
    "mass_kg": 3.643,
    "inertia": "[0.020,0.020,0.012] kg·m² (DEFAULT, 真机标定后由 config/calib/hamiltonian.json 覆盖)",
    "alpha": 0.15,
    "gravity_G": "未配置 ⇒ U_grav 记 0 (不造数)",
    "source": "src/lerobot/manifold/state_space_energy.py",
    "source_symbol": "class StateSpaceHamiltonian",
    "reuse": "se3_impedance.py(potential/pose_error/K_INSERT) · se3_gravity_provider.py(_rpy_to_T) · lie_intent.py(se3_exp/log)",
    "measured": "12/12 判据 PASS: U(2cm)=0.080000J · K(0.1m/s)=0.018215J · H 1200 步单调不增 7.999e-02→8.006e-10 · Ḣ 解析 vs 数值 相对差 0.070% · 末端残余 0.0013mm",
    "spec_target": "Ḣ≤0 (被动) · ΣF_l=F 残差<1e-12 · 层动作横向>60° veto",
    "caveat": "惯量/质量为默认标定值(DEFAULT, 非真机实测); 无 G 配置时引力项=0; 力矩通道默认关, 需 L2 显式授权",
    "desc": "万有引力=势场: 每层动作只保留沿 −∇U 的分量(横向>60°否决), 输出 u=[F;M] 与能量 H=K+U; 被动性由 Ḣ=−ξᵀBξ 结构保证",
}


def band_of(y, bands):
    for b in bands:
        if b["y"] <= y <= b["y"] + b.get("h", 0):
            return b
    return None


def free_slot(nodes, bands, x_lo, x_hi):
    """在 [x_lo,x_hi] × 各行带内找 (x,y) 使 300×130 与既有节点零重叠, 且贴近 n_moveit。"""
    mv = next(n for n in nodes if n["id"] == "n_moveit")
    best = None
    for b in bands:
        for y in range(int(b["y"]) + 12, int(b["y"] + b.get("h", 0)) - H - 4, 10):
            for x in range(int(x_lo), int(x_hi) - W + 1, 10):
                hit = False
                for n in nodes:
                    if n.get("type") == "row_bg":
                        continue
                    if x < n["x"] + n["w"] and n["x"] < x + W and y < n["y"] + n["h"] and n["y"] < y + H:
                        hit = True
                        break
                if hit:
                    continue
                # 目标: 右缘尽量贴近 n_moveit.x, 纵向尽量贴近 n_moveit.y
                score = (abs((x + W) - mv["x"]), abs(y - mv["y"]))
                if best is None or score < best[0]:
                    best = (score, x, y, b)
    return best


def next_port(links, node, side):
    used = {str(L.get("f_port" if side == "out" else "t_port"))
            for L in links if (L["f"] if side == "out" else L["t"]) == node}
    for k in range(1, 40):
        p = f"{'out' if side == 'out' else 'in'}{k}"
        if p not in used:
            return p
    return "in1"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    d = json.load(open(FLOW, encoding="utf-8"))
    nodes, links = d["nodes"], d["links"]
    ids = {n["id"] for n in nodes}
    if NID in ids:
        print(f"⏭ {NID} 已存在 → 幂等跳过")
        return 0
    for sid, _ in INPUTS + OUTPUTS:
        assert sid in ids, f"引用了不存在的节点 {sid}"

    xof = {n["id"]: n for n in nodes}
    # ① 可行 x 区间：所有入边前向 (f.x+f.w <= X) 且出边前向 (X+W <= t.x)
    x_lo = max(xof[s]["x"] + xof[s]["w"] for s, _ in INPUTS) + 10
    x_hi = min(xof[t]["x"] for t, _ in OUTPUTS)
    assert x_lo + W <= x_hi, f"无可行横向区间: 入边前沿 {x_lo} / 出边前沿 {x_hi}"
    print(f"① 可行区间: x ∈ [{x_lo}, {x_hi - W}]  (入边前沿 {x_lo} · 出边前沿 {x_hi})")

    bands = [n for n in nodes if n.get("type") == "row_bg"]
    slot = free_slot(nodes, bands, x_lo, x_hi)
    assert slot, "没有可放的空位"
    _, X, Y, band = slot
    print(f"② 选位: ({X}, {Y}) 落在行带 [{band['name'][:30]}] · 与既有节点零重叠")

    node = {"id": NID, "type": "model", "name": NAME, "x": int(X), "y": int(Y),
            "w": int(W), "h": int(H), "icon": "🌍", "color": "#ffd479",
            "params": PARAMS, "inputs": [f"in{i+1}" for i in range(len(INPUTS))],
            "outputs": [f"out{i+1}" for i in range(len(OUTPUTS))], "actions": []}
    nodes.append(node)

    new_links = []
    for sid, lab in INPUTS:
        new_links.append({"id": f"lk1025_{sid}_{NID}", "f": sid, "t": NID,
                          "f_port": next_port(links + new_links, sid, "out"),
                          "t_port": next_port(links + new_links, NID, "in"), "label": lab})
    for tid, lab in OUTPUTS:
        new_links.append({"id": f"lk1025_{NID}_{tid}", "f": NID, "t": tid,
                          "f_port": next_port(links + new_links, NID, "out"),
                          "t_port": next_port(links + new_links, tid, "in"), "label": lab})
    xy = {n["id"]: n["x"] for n in nodes}          # 含新节点 (已 append)
    for L in new_links:
        fw = next(n["w"] for n in nodes if n["id"] == L["f"])
        assert xy[L["f"]] + fw <= xy[L["t"]], f"非前向连线 {L['f']}→{L['t']}"
        assert not any(x["f"] == L["f"] and x["t"] == L["t"] for x in links), f"重复连线 {L}"
    links.extend(new_links)
    print(f"③ 接线: 入 {len(INPUTS)} 条 (L5/L4/L3/L2/安全/真值) + 出 {len(OUTPUTS)} 条 = {len(new_links)} 条 (全前向 · 无重复)")

    for n in nodes:
        for k in ("x", "y", "w", "h"):
            assert isinstance(n[k], int), f"非 int 坐标 {n['id']}.{k}={n[k]}"
    if not a.apply:
        print("(dry-run; 加 --apply 落地)")
        return 0
    d["nodes"], d["links"] = nodes, links
    json.dump(d, open(FLOW, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"✅ 已写入: 节点 {len(nodes)} · 连线 {len(links)}")
    print("CANVAS_GRAV_H_DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
