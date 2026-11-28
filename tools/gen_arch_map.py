#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧭 gen_arch_map.py — 生成「系统架构图」的唯一依据 arch_map.json

老倪 2026-11-26 原话:
  「根据状态空间的节点信息，建立 系统2 系统1 系统0 与所有 L1~L5 的分层映射；
    重新设计系统架构的UI，你现在系统架构页面的功能块，思想可以保留，但是UI、表现，
    要与状态空间的所有节点要映射上，simulink画布的连线逻辑，要反映到系统架构图里，
    系统 0 1 2 是一个全面的系统工程，而且要连接所有的标准服务 server」

数据来源 (全部是工程里的真源, 不编造):
  ① flows/state_space_obs.json —— 状态空间主画布 (100 节点 / 241 连线)。
     层级不是靠字段标, 是靠 row_bg「层级带」的 y 区间划分: 节点落在哪个带就属于哪一层。
  ② src/lerobot/engineering/node_map.json —— 78 个工程节点的 layer / name / 三处路径。
  ③ server/services.json —— 28 个标准服务 (端口/机器/L层归属)。

产出 server/arch_map.json:
  - systems: S2 / S1 / S0 三系统, 各自含哪些层、多少个节点、哪些服务
  - layers:  L1~L5 每层的层级带、节点清单、服务清单
  - nodes:   画布节点的真 id / 名字 / 图标 / 层 / 系统 / 坐标 (供 UI 直接摆放)
  - links:   画布连线 (f -> t, 端口), 只保留两端都在节点表里的
  - services: 标准服务 + 归属层/系统

用法: python3 tools/gen_arch_map.py [--write]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANVAS = os.path.join(ROOT, "flows", "state_space_obs.json")
NODE_MAP = os.path.join(ROOT, "src", "lerobot", "engineering", "node_map.json")
SERVICES = os.path.join(ROOT, "server", "services.json")
OUT = os.path.join(ROOT, "server", "arch_map.json")

# 层 → 系统 (老倪定的：S0 反射 / S1 快反应 / S2 慢思考)
LAYER_TO_SYSTEM = {
    "L1": "S0",
    "L2": "S1",
    "L3": "S1",
    "L4": "S2",
    "L5": "S2",
}
SYSTEM_META = {
    "S2": {"name": "系统 2 · 慢思考", "desc": "大模型 / 世界模型 / 长程规划", "cadence": "1~10 Hz", "color": "#a855f7"},
    "S1": {"name": "系统 1 · 快反应", "desc": "技能编排 / 流形 / 连续控制", "cadence": "10~100 Hz", "color": "#22d3ee"},
    "S0": {"name": "系统 0 · 反射", "desc": "执行器 / 安全限界 / 物理闭环", "cadence": "200~1000 Hz", "color": "#f59e0b"},
}
LAYER_META = {
    "L5": {"name": "L5 场景理解 + 自动标注", "desc": "大模型层 · 任务/编排/记忆中枢"},
    "L4": {"name": "L4 自主安全功能", "desc": "工作安全 · 物理世界导航 · 流形世界模型 · 筹划"},
    "L3": {"name": "L3 连续功能", "desc": "长程序列规划 · 技能编排 · 海马体记忆 · VLM+Flow-Matching"},
    "L2": {"name": "L2 基础功能", "desc": "分段感知 · 融合 · 小模型控制 · 状态机 · 原子技能 · 执行"},
    "L1": {"name": "L1 机器人接口", "desc": "执行器 · 动作收口 · 安全边界 · 物理世界"},
    "MET": {"name": "元层 · 数据/验证/可视化", "desc": "数据源 · 质量门 · 观察器（回路外）"},
}


def _load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _layer_from_text(txt):
    """从层级带的名字里认出层号

    2026-11-26 老倪口径: L1 = 机器人接口 (执行器 · 动作收口 · 安全边界 · 物理世界)
    ⇒ 画布的「执行层 (执行器 → 物理闭环)」必须归 L1/系统0, 不能因为名字里带 L2 就算 L2,
      否则系统0 在架构图上一个节点都没有, 三个系统就断了一环。
    """
    if not txt:
        return None
    if "执行层" in txt or "执行器" in txt:
        return "L1"
    m = re.search(r"\bL([1-5])\b", txt)
    if m:
        return "L" + m.group(1)
    if "大模型层" in txt:
        return "L5"
    if "数据源" in txt or "验证层" in txt or "可视化层" in txt:
        return "MET"
    return None


def build():
    canvas = _load(CANVAS)
    cnodes = canvas.get("nodes") or []
    clinks = canvas.get("links") or []

    # ---- 1. 层级带：按 y 排序，每带一个 [y0, y1) 区间 ----
    bands = []
    for n in cnodes:
        if n.get("type") != "row_bg":
            continue
        y = float(n.get("y") or 0)
        h = float(n.get("h") or 0)
        bands.append({
            "id": n.get("id"),
            "name": (n.get("name") or "").strip(),
            "layer": _layer_from_text(n.get("name") or ""),
            "y0": y,
            "y1": y + (h if h > 0 else 40),
        })
    bands.sort(key=lambda b: b["y0"])

    def band_of(y):
        for b in bands:
            if b["y0"] <= y < b["y1"]:
                return b
        # 落空则取最近的
        if bands:
            return min(bands, key=lambda b: min(abs(y - b["y0"]), abs(y - b["y1"])))
        return None

    # ---- 2. 画布节点 → 层 / 系统 ----
    nodes = []
    for n in cnodes:
        t = n.get("type")
        if t == "row_bg":
            continue
        b = band_of(float(n.get("y") or 0))
        layer = (b or {}).get("layer")
        nodes.append({
            "id": n.get("id"),
            "name": (n.get("name") or "").strip(),
            "type": t,
            "icon": n.get("icon") or "",
            "x": float(n.get("x") or 0),
            "y": float(n.get("y") or 0),
            "w": float(n.get("w") or 0),
            "h": float(n.get("h") or 0),
            "color": n.get("color") or "",
            "desc": (n.get("desc") or "")[:160],
            "band": (b or {}).get("name") or "",
            "band_id": (b or {}).get("id") or "",
            "layer": layer,
            "system": LAYER_TO_SYSTEM.get(layer or "", "S1" if t == "model" else ""),
            "ins": n.get("inputs") or [],
            "outs": n.get("outputs") or [],
        })

    ids = {n["id"] for n in nodes}

    # ---- 3. 连线（两端都在） ----
    links = []
    for l in clinks:
        f, t = l.get("f"), l.get("t")
        if f in ids and t in ids:
            links.append({
                "id": l.get("id"),
                "f": f, "t": t,
                "f_port": l.get("f_port") or "",
                "t_port": l.get("t_port") or "",
                "label": (l.get("label") or "")[:40],
            })

    # ---- 4. 工程节点表（78 个）：层以 node_map 为准 ----
    eng = []
    if os.path.exists(NODE_MAP):
        for k, v in (_load(NODE_MAP).get("nodes") or {}).items():
            lv = v.get("layer")
            eng.append({
                "id": k,
                "name": (v.get("name") or k)[:90],
                "layer": lv,
                "system": LAYER_TO_SYSTEM.get(lv or "", ""),
                "impl": (v.get("impl") or "").split(":")[0],
                "in": len(v.get("ports_in") or []),
                "out": len(v.get("ports_out") or []),
                "pure": bool(v.get("pure")),
                "on_canvas": k in ids,
            })

    # ---- 5. 标准服务 ----
    svcs = []
    if os.path.exists(SERVICES):
        sd = _load(SERVICES)
        hosts = sd.get("hosts") or {}
        for s in sd.get("services") or []:
            h = s.get("host") or "station"
            svcs.append({
                "id": s.get("id"),
                "name": s.get("name"),
                "port": s.get("port"),
                "script": s.get("script"),
                "host": h,
                "host_name": (hosts.get(h) or {}).get("name", h),
                "host_ip": (hosts.get(h) or {}).get("ip", ""),
                "system": s.get("system"),
                "layers": s.get("layers") or [],
                "hw": s.get("hw") or [],
                "note": s.get("note") or "",
            })

    # ---- 6. 汇总 ----
    def cnt(seq, key, val):
        return sum(1 for x in seq if x.get(key) == val)

    systems = {}
    for sk, meta in SYSTEM_META.items():
        layers = [lv for lv, s in LAYER_TO_SYSTEM.items() if s == sk]
        systems[sk] = dict(meta)
        systems[sk]["layers"] = layers
        systems[sk]["canvas_nodes"] = [n["id"] for n in nodes if n.get("system") == sk]
        systems[sk]["eng_nodes"] = [e["id"] for e in eng if e.get("system") == sk]
        systems[sk]["services"] = [s["id"] for s in svcs if s.get("system") == sk]
        systems[sk]["n_canvas"] = len(systems[sk]["canvas_nodes"])
        systems[sk]["n_eng"] = len(systems[sk]["eng_nodes"])
        systems[sk]["n_services"] = len(systems[sk]["services"])

    layers_out = {}
    for lv, meta in LAYER_META.items():
        layers_out[lv] = dict(meta)
        layers_out[lv]["system"] = LAYER_TO_SYSTEM.get(lv, "MET")
        layers_out[lv]["bands"] = [b["name"] for b in bands if b["layer"] == lv]
        layers_out[lv]["canvas_nodes"] = [n["id"] for n in nodes if n.get("layer") == lv]
        layers_out[lv]["eng_nodes"] = [e["id"] for e in eng if e.get("layer") == lv]
        layers_out[lv]["services"] = sorted({sid for s in svcs if lv in (s.get("layers") or []) for sid in [s["id"]]})
        layers_out[lv]["n_canvas"] = len(layers_out[lv]["canvas_nodes"])
        layers_out[lv]["n_eng"] = len(layers_out[lv]["eng_nodes"])
        layers_out[lv]["n_services"] = len(layers_out[lv]["services"])

    return {
        "schema": "zmax.archmap.v1",
        "version": "5.50.786",
        "source": {
            "canvas": "flows/state_space_obs.json",
            "node_map": "src/lerobot/engineering/node_map.json",
            "services": "server/services.json",
            "canvas_name": canvas.get("name") or "",
        },
        "systems": systems,
        "layers": layers_out,
        "bands": bands,
        "nodes": nodes,
        "links": links,
        "eng_nodes": eng,
        "services": svcs,
        "stats": {
            "canvas_nodes": len(nodes),
            "canvas_links": len(links),
            "eng_nodes": len(eng),
            "services": len(svcs),
            "bands": len(bands),
            "unlayered_canvas": sum(1 for n in nodes if not n.get("layer")),
            "eng_not_on_canvas": sum(1 for e in eng if not e["on_canvas"]),
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="写入 server/arch_map.json")
    a = ap.parse_args()
    m = build()
    if a.write:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=1)
        print("✅ 写出 %s (%d 字节)" % (OUT, os.path.getsize(OUT)))
    s = m["stats"]
    print("画布节点 %d · 连线 %d · 工程节点 %d · 标准服务 %d · 层级带 %d"
          % (s["canvas_nodes"], s["canvas_links"], s["eng_nodes"], s["services"], s["bands"]))
    print("未归层画布节点 %d · 不在画布上的工程节点 %d" % (s["unlayered_canvas"], s["eng_not_on_canvas"]))
    for sk in ("S2", "S1", "S0"):
        x = m["systems"][sk]
        print("  %s %-14s 层%s 画布%2d 工程%2d 服务%2d"
              % (sk, x["name"], "".join(x["layers"]), x["n_canvas"], x["n_eng"], x["n_services"]))
    for lv in ("L5", "L4", "L3", "L2", "L1", "MET"):
        x = m["layers"][lv]
        print("  %-4s %-22s 画布%2d 工程%2d 服务%2d 带%d"
              % (lv, x["name"], x["n_canvas"], x["n_eng"], x["n_services"], len(x["bands"])))


if __name__ == "__main__":
    sys.exit(main())
