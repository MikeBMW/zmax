#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🌀 canvas_add_phase_corridor.py — 把「SE(3)×S1 记忆流形」+「相空间安全通道」两个节点接进 L4

老倪 2026-11-20:
  ① 把昨天那条 se3 服务 (zmax-se3-state, 16 维 A–E, 5Hz) 挂到状态空间画布上, 打开就能看;
  ② 把「相空间安全通道」加进流形引擎逻辑链 (受控轨迹强跨相位线 ⇒ 用各向异性度规画安全管道)。

硬断言 (与 canvas_add_manifold_engine.py 同规矩):
  · 落在 L4 行带内; 与既有节点零重叠 (留 ≥8px 间隙); 坐标全 int;
  · 连线全前向 (源 x < 目标 x)、不重复、端点存在; 幂等 (已存在则跳过);
  · 写盘前备份 flows/_archive/, 写完回读 JSON 并复核节点/连线计数。

用法:
    ./gui-venv311/bin/python tools/canvas_add_phase_corridor.py --dry
    ./gui-venv311/bin/python tools/canvas_add_phase_corridor.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLOW = os.path.join(ROOT, "flows", "state_space_obs.json")
ARCH = os.path.join(ROOT, "flows", "_archive")

L4_BAND = ("ssbg7",)          # L4 专家自主功能行带

NODES = [
    {
        "id": "ss_se3_state",
        "name": "🔷 SE(3)×S1 记忆流形 (8815 · A位置ℝ³ · B轴S² · C四元数S³ · D滚转S¹ · E相位S¹ · 5Hz)",
        "type": "model", "icon": "🔷", "color": "#7bdcb5",
        "x": 6800, "y": 1586, "w": 280, "h": 110,
        "params": {
            "state_space": True, "kind": "real", "hz": 5,
            "role": "记忆流形入口 — 把昨天落地的 16 维 SE(3)×S1 状态 (A–E) 摆上画布, 下游相空间通道吃它",
            "source": "src/lerobot/middleware/nodes/impl/ss_se3_state.py",
            "source_symbol": "def node_ss_se3_state",
            "truth": "zmax_data/se3/se3_state_live.json (zmax-se3-state.service · 8815 /api/se3)",
            "vector16": "A_pos_mm(3) B_axis_S2(3) B_err(1) C_quat_S3(4) D_roll(1) E_s(1) E_arc_mm(1) E_i(1) M_age(1)",
            "desc": "SE(3)×S1: 位置 ℝ³ · 轴 S² · 四元数 S³ · 滚转 S¹ · 弧长相位 S¹ (只读, 不新增控制通路)",
        },
    },
    {
        "id": "ss_phase_corr",
        "name": "🌀 相空间安全通道 (SE(3)×S1 记忆 + 速度纤维 · V_phase/τ_safe · S¹ 相位门控 · 李雅普诺夫单调)",
        "type": "model", "icon": "🌀", "color": "#f5c26b",
        "x": 6820, "y": 1716, "w": 320, "h": 110,
        "params": {
            "state_space": True, "kind": "real",
            "role": "流形引擎的相空间安全通道 — 人为轨迹强跨相位线时, 用各向异性度规把状态拉回管道",
            "source": "src/lerobot/manifold/phase_corridor.py",
            "source_symbol": "class PhaseSpaceCorridor",
            "api": "compute(cur, des, axis) → V_phase · τ_safe · gate · V̇",
            "formula": "z=[e_pose/tol; e_vel/vlim]; V=½‖z‖²; τ=−α·τ_lim⊙(z_pos+z_vel); α_eff=min(α,λ/2) ⇒ V̇≤−λV",
            "metric": "径向 0.3mm / 轴向 6mm · 横向 50mm/s / 轴向 300mm/s · 载荷自适应 √(m/m_ref)",
            "gate": "S¹ 相位不一致(>15°) ⇒ 记忆匹配断裂, 注入置 0",
            "measured": "自检 24 点单调性全过; 越界 3mm 时 τ 饱和到 τ_lim 且方向不变",
            "desc": "只读: 产出 V/τ/门控给下游判据与显示, 不直接下发运动 (真动仍要 8793 授权)",
        },
    },
]

LINKS = [
    ("ss_mani_eng", "ss_phase_corr", "流形坐标 p / 度规 M → 相空间通道"),
    ("ss_se3_state", "ss_phase_corr", "SE(3)×S1 记忆 (A–E, 5Hz) → 相空间通道"),
    ("ss_phase_corr", "ssintact", "τ_safe / 通道判据 → L4 工作安全"),
]


def overlap(a, b, gap=8):
    return not (a["x"] + a["w"] + gap <= b["x"] or b["x"] + b["w"] + gap <= a["x"]
                or a["y"] + a["h"] + gap <= b["y"] or b["y"] + b["h"] + gap <= a["y"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--flow", default=FLOW, help="画布 JSON 路径 (默认 flows/, 唯一依据在 data/database/.../canvas/)")
    a = ap.parse_args()
    flow = a.flow

    d = json.load(open(flow, encoding="utf-8"))
    nodes, links = d["nodes"], d["links"]
    ids = {n["id"] for n in nodes}
    band = next((n for n in nodes if n["id"] in L4_BAND), None)
    assert band is not None, "L4 行带缺失"
    y0, y1 = band["y"], band["y"] + band.get("h", 0)

    todo = [n for n in NODES if n["id"] not in ids]
    if not todo:
        print("⏭ 两个节点都已存在 → 幂等跳过")
        return 0

    # ① 断言: 坐标 int / 落在 L4 行带 / 零重叠
    for n in todo:
        assert all(isinstance(n[k], int) for k in ("x", "y", "w", "h")), f"{n['id']} 坐标必须 int"
        assert y0 <= n["y"] and n["y"] + n["h"] <= y1, f"{n['id']} 越出 L4 行带 ({n['y']}..{n['y']+n['h']} vs {y0}..{y1})"
        for m in nodes:
            if m.get("type") == "row_bg":       # 行带是容器, 本来就包住节点
                continue
            assert not overlap(n, m), f"{n['id']} 与 {m['id']} 重叠"
    for i in range(len(todo)):
        for j in range(i + 1, len(todo)):
            assert not overlap(todo[i], todo[j]), "新节点互相重叠"

    # ② 断言: 连线前向 + 端点存在 + 不重复
    pos = {n["id"]: n for n in nodes}
    for n in todo:
        pos[n["id"]] = n
    exist = {(L["f"], L["t"]) for L in links}
    new_links = []
    for f, t, label in LINKS:
        if f not in pos or t not in pos:
            print(f"   ⚠️ 跳过连线 {f}→{t} (端点不存在)")
            continue
        if pos[f]["x"] >= pos[t]["x"]:
            print(f"   ⚠️ 跳过非前向连线 {f}→{t} ({pos[f]['x']} >= {pos[t]['x']})")
            continue
        if (f, t) in exist:
            continue
        new_links.append({"id": f"lkpf{len(new_links)+1}", "f": f, "t": t,
                          "f_port": "out1", "t_port": "in1", "label": label})

    print(f"待加节点 {len(todo)} · 待加连线 {len(new_links)}")
    for n in todo:
        print(f"   + {n['id']:16s} ({n['x']},{n['y']}) {n['w']}x{n['h']} {n['name'][:34]}")
    for L in new_links:
        print(f"   → {L['f']} ⇒ {L['t']}  «{L['label']}»")

    if a.dry or not a.apply:
        print("(dry run; 加 --apply 落盘)")
        return 0

    # ③ 备份 → 写盘 → 回读复核
    os.makedirs(ARCH, exist_ok=True)
    bak = os.path.join(ARCH, "state_space_obs_before_phase_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(flow, bak)
    n0, l0 = len(nodes), len(links)
    d["nodes"] = nodes + todo
    d["links"] = links + new_links
    tmp = flow + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, flow)

    back = json.load(open(flow, encoding="utf-8"))
    bid = {n["id"] for n in back["nodes"]}
    assert all(n["id"] in bid for n in todo), "回读缺节点"
    assert len(back["nodes"]) == n0 + len(todo), "节点数不符"
    assert len(back["links"]) == l0 + len(new_links), "连线数不符"
    for L in back["links"]:
        assert L["f"] in bid and L["t"] in bid, f"悬空连线 {L['id']}"
    print(f"✅ 已写入 {flow}")
    print(f"   节点 {n0} → {len(back['nodes'])} · 连线 {l0} → {len(back['links'])}")
    print(f"   备份 {bak}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
