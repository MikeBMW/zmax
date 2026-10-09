# -*- coding: utf-8 -*-
"""模型 × 工程配置 匹配器 (契约求交) —— 回答"这么多模型, 配置怎么区分/怎么对上工程"。

原理 (对标 ASAM: A2L 描述随 ECU 走, 整车/变体配置归车辆):
    · 模型侧 = **模型包自带契约** (输入/输出/域/归一化/依赖的工程项) —— 随模型走, 可携带
    · 工程侧 = **站点事实** (坐标系/几何/相机/工具/机器人) —— 随现场走, 与模型无关
    · 匹配   = 契约求交: 模型 declare 的 requires ∩ 站点 available ⇒ OK / 缺项 / 不适用
    · 结果   = 兼容矩阵 + 组配建议; 组配(binding) 才是"一次运行到底用哪套"的落盘单元

真源 (只读):
    src/lerobot/engineering/models_manifest.json   模型版本真源 (在役/候选/未训)
    models/active_models.json                      在役指针真源 (L2/L3/L4)
    config/calib/zmax_calib.json                   站点工程配置真值
    feature.dbc                                    能力 ID 合法性 (capabilities 必须存在)
    docs/third_party_model_spec.md                 模型包 manifest v1 (理想真源: 每个模型包自带)

输出:
    config/mcd/match_matrix.json                   兼容矩阵 (机器可读)
用法:
    python3 tools/model_site_match.py [--json]     打印矩阵; --json 只出 JSON
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "src", "lerobot", "engineering", "models_manifest.json")
ACTIVE = os.path.join(ROOT, "models", "active_models.json")
CALIB = os.path.join(ROOT, "config", "calib", "zmax_calib.json")
DBC = os.path.join(ROOT, "feature.dbc")
OUT = os.path.join(ROOT, "config", "mcd", "match_matrix.json")

# ── 模型侧契约 (本表 = 模型包 manifest 的"期望字段"; declared_by 标出证据强度) ──
# requires: 该模型要吃哪些**站点工程配置项** (G3/G2 类现场事实)
# domain:   训练/运行域 — metaworld(仿真) / real(真机) / board(板坐标) / cloud
MODELS = [
    dict(id="L2.yolo_peg", layer="L2", family="YOLO 检测", domain="real",
         in_spec="图像 640x480 RGB", out_spec="检测框+3D 点 (hand/peg/hole)",
         requires=["cam.K", "cam.dist"], normalization="—(检测类无动作归一化)",
         artifact="models/yolo_peg_live.pt (软链指针)", declared_by="active_models.json#L2",
         capabilities=["B1", "B5"]),
    dict(id="L2.skill_mlp", layer="L2", family="分段控制小模型 (前馈/估计/预测/校正)", domain="engine",
         in_spec="obs 43D", out_spec="u_ff 4D (dx,dy,dz,grip)",
         requires=[], normalization="per-dim (训练集 stats)",
         artifact="models/ss_left_brain.npz 等", declared_by="state_space 画布 L2 行 (设计推定)",
         capabilities=["B4", "C1"]),
    dict(id="L3.smolvla_lew", layer="L3", family="SmolVLA+LEW (VLM+DiT)", domain="metaworld",
         in_spec="图像 640x480 + obs 39D", out_spec="动作块 4D (chunk 100)",
         requires=["cam.K"], normalization="per-dim · 必须与 ckpt 训练集同源",
         artifact="outputs/train/smolvla_lew_v10_1h/checkpoints/004000/pretrained_model",
         declared_by="active_models.json#L3 (env_override SS_L3_CK)", capabilities=["B1", "B2", "C1", "C2"]),
    dict(id="L4.intact", layer="L4", family="INTACT-JEPA 意图-动作", domain="real",
         in_spec="图像 + 观测 (自适应)", out_spec="意图→动作 chunk",
         requires=["cam.K", "T_base_cam", "plane_z", "cell_geometry.points"],
         normalization="官方口径 · 按 ckpt 训练集同源反归一化",
         artifact="zmax_data/stable-wm-cache/checkpoints/intact_l4_current",
         declared_by="active_models.json#L4", capabilities=["B1", "B2", "C1", "C2", "C3"]),
    dict(id="L5.deepseek_vl", layer="L5", family="DeepSeek 视觉语言 (场景理解主路)", domain="cloud",
         in_spec="图像 + 提示词", out_spec="结构化 JSON (判读/建议)",
         requires=[], normalization="—(语言侧无动作归一化)",
         artifact="src/lerobot/policies/left_right/state_space/scene_vlm.py",
         declared_by="models_manifest.json#L5", capabilities=["D3", "E1"]),
    # ── Model Zoo 画布上的其它家族 (每条一行; 未在役的 state=untrained/未接) ──
    dict(id="MZ.act", layer="—", family="ACT (ResNet18+Transformer)", domain="metaworld",
         in_spec="图像 480x640", out_spec="动作块 4D (chunk 100)",
         requires=["cam.K"], normalization="per-dim",
         artifact="outputs/train/**/act*", declared_by="flows/model_zoo.json (设计推定)",
         capabilities=["B1", "C1"]),
    dict(id="MZ.vla_touch", layer="—", family="VLA-Touch (DINOv2+Marker 触觉)", domain="metaworld",
         in_spec="图像 + 触觉 4D", out_spec="动作块 4D",
         requires=["cam.K"], normalization="per-dim",
         artifact="outputs/train/**/vla_touch*", declared_by="flows/model_zoo.json (设计推定)",
         capabilities=["B1", "B3", "C1"]),
    dict(id="MZ.awe", layer="—", family="AWE (SigLIP 视触觉 + zFlow)", domain="metaworld",
         in_spec="图像 + 触觉 + 潜空间", out_spec="动作块 4D",
         requires=["cam.K"], normalization="per-dim",
         artifact="outputs/train/**/awe*", declared_by="flows/model_zoo.json (设计推定)",
         capabilities=["B1", "B3", "D1"]),
    dict(id="MZ.expert", layer="—", family="官方专家基准 / 专家蒸馏", domain="metaworld",
         in_spec="obs 39D", out_spec="动作 4D",
         requires=[], normalization="—(解析控制律)",
         artifact="src/lerobot/policies/… (规则/专家)",
         declared_by="flows/model_zoo.json (设计推定)", capabilities=["C1"]),
    dict(id="MZ.l2_muscle", layer="L2", family="肌肉记忆 (标杆回放)", domain="real",
         in_spec="阶段 + 标杆模板", out_spec="动作 4D (直通)",
         requires=["control_tcp.offset_xyz_m"], normalization="—(模板回放)",
         artifact="data/skills/l2_atomic/taught_points.json + 标杆库",
         declared_by="画布 n_l2_muscle / ss_mem_l2", capabilities=["C1", "C4"]),
]

# ── 站点侧: 工程配置项 → 取值 (None = 未标定/未示教) ──
SITE_KEYS = ["cam.K", "cam.dist", "T_base_cam", "plane_z", "depth_scale",
             "cell_geometry.points", "robot.dof", "tool_payload.mass_kg",
             "control_tcp.offset_xyz_m"]
MASK = {"cam.K": "camera.K", "cam.dist": "camera.dist", "T_base_cam": "T_base_cam.value",
        "plane_z": "plane_z.value", "depth_scale": "depth_scale.value",
        "cell_geometry.points": "cell_geometry.points", "robot.dof": "robot.dof",
        "tool_payload.mass_kg": "tool_payload.mass_kg",
        "control_tcp.offset_xyz_m": "control_tcp.offset_xyz_m"}
# 真值下界: 站点事实的"该不该有"——dof 之类本就有值的用 NULL_OK 标注不适用
NULL_OK = {"robot.dof"}


def _dig(d, path):
    cur = d
    for k in str(path).split("."):
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def read_site():
    try:
        calib = json.load(open(CALIB, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        calib = {}
    site, missing = {}, []
    for k in SITE_KEYS:
        v = _dig(calib, MASK[k])
        ok = v is not None
        site[k] = {"value": v, "available": ok,
                   "reason": _dig(calib, MASK[k].split(".")[0] + "._reason") if not ok else None}
        if not ok and k not in NULL_OK:
            missing.append(k)
    return site, missing


def read_caps():
    caps = set()
    if os.path.isfile(DBC):
        for ln in open(DBC, encoding="utf-8"):
            m = re.match(r"BO_\s+(\S+)\s+", ln.strip())
            if m:
                caps.add(m.group(1))
    return caps


def match(site, caps):
    rows = []
    for m in MODELS:
        cells = {}
        for k in SITE_KEYS:
            req = k in [r for r in m["requires"]]
            avail = site[k]["available"]
            cells[k] = ("OK" if (req and avail) else
                        "缺项" if (req and not avail) else
                        "不适用")
        bad_caps = [c for c in m.get("capabilities", []) if c not in caps]
        miss = [k for k, v in cells.items() if v == "缺项"]
        rows.append({"model": m["id"], "layer": m["layer"], "family": m["family"], "domain": m["domain"],
                     "artifact": m["artifact"], "declared_by": m["declared_by"],
                     "in_spec": m["in_spec"], "out_spec": m["out_spec"], "normalization": m["normalization"],
                     "requires": m["requires"], "cells": cells,
                     "missing": miss, "bad_capabilities": bad_caps,
                     "usable_now": (not miss and not bad_caps),
                     "verdict": ("✅ 可用" if (not miss and not bad_caps)
                                 else f"⛔ 缺 {len(miss)} 项: {', '.join(miss)}" if miss
                                 else f"⛔ 能力 ID 不在库里: {bad_caps}")})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    site, site_missing = read_site()
    caps = read_caps()
    rows = match(site, caps)
    usable = [r for r in rows if r["usable_now"]]

    out = {"_meta": {"schema": "zmax-model-site-match/1.0", "generated_at": time.strftime("%F %T"),
                     "doc": "模型 × 站点工程配置 兼容矩阵 (契约求交)。只读真源, 不改任何配置值。",
                     "sources": {"models_manifest": os.path.relpath(MANIFEST, ROOT),
                                 "active_models": os.path.relpath(ACTIVE, ROOT),
                                 "site_calib": os.path.relpath(CALIB, ROOT),
                                 "capability_lib": "feature.dbc"},
                     "site_keys": SITE_KEYS},
           "SITE": site, "SITE_MISSING": site_missing,
           "MODELS": rows,
           "SUMMARY": {"models": len(rows), "usable_now": len(usable),
                       "blocked": len(rows) - len(usable),
                       "by_layer": {l: sum(1 for r in rows if r["layer"] == l)
                                    for l in sorted({r["layer"] for r in rows})},
                       "site_missing": site_missing}}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0 if not site_missing else 0

    w = max(len(r["model"]) for r in rows) + 1
    print(f"站点工程配置: 就位 {len(SITE_KEYS)-len(site_missing)}/{len(SITE_KEYS)}"
          f" · 缺: {', '.join(site_missing) or '无'}")
    print(f"能力库: feature.dbc BO_ {len(caps)} 条")
    print()
    hdr = "model".ljust(w) + "".join(k.split('.')[0][:6].ljust(7) for k in SITE_KEYS) + "  判定"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        line = r["model"].ljust(w)
        for k in SITE_KEYS:
            v = r["cells"][k]
            line += ("✅" if v == "OK" else "⛔" if v == "缺项" else "·").ljust(7)
        print(line + "  " + r["verdict"])
    print()
    print(f"可用 {out['SUMMARY']['usable_now']}/{len(rows)} · 受阻 {out['SUMMARY']['blocked']}"
          f" · 按层 {out['SUMMARY']['by_layer']}")
    print(f"→ {os.path.relpath(OUT, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
