# -*- coding: utf-8 -*-
"""place_cell — 位置细胞的工程实现 (群体编码 + 模式补全 + 重映射检测)。

老倪 2026-11-10: 「那融合定位节点, 需要实现位置细胞的功能, 对不?」

为什么融合节点需要的不是「定位」而是「表征与校验」:
  人要有位置细胞, 是因为**没有外部真值** —— 只能靠自己积分 + 地标, 误差必须靠位置细胞
  的群体编码来降噪、靠重映射来发现"我进错房间了"。
  我们机器人有编码器真值(零漂移), 所以"我在哪"这件事不需要位置细胞 —— 那是更低层的
  本体感觉做到的。真正缺的是位置细胞的另外三件事:

    ① 群体编码 (population code): 位置不是一个点, 是一群细胞的加权激活
       ⇒ 好处: 单点抖动被冗余摊平, 且能表达"我不确定"
    ② 模式补全 (pattern completion): 只看到部分线索也能认出"我在哪一段"
       ⇒ 好处: 相机丢了/被遮了, 靠部分区域线索仍能锚定
    ③ 重映射 (remapping): 同一物理位置, 表征突变 ⇒ 说明环境变了(或真值漂了)
       ⇒ 好处: 这是我们目前**完全没有**的异常检测

实现口径 (不引入新传感器, 全部用现有真源):
  place field = 50mm 网格上的高斯核 (O'Keefe 的位置野就是高斯型)
  激活强度   = exp(-d²/2σ²), σ = 100mm (覆盖约 ±2 格)
  相似度     = 两次激活向量的余弦
  重映射判据 = 同一网格两次经过, 激活相似度 < 0.5 且位姿距离 < 100mm
              ⇒ 同一个"物理地点"却激活了不同的细胞群 = remapping 或真值漂移

这条判据的实际用途: 它能**独立于编码器**发现"机器人以为自己在 A 点, 但视觉看到的是 B"。
"""

from __future__ import annotations

import json
import math
import os
from typing import Any, Dict, List, Optional, Tuple

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))))
ENV_MODEL = os.path.join(REPO, "zmax_data", "env_model.json")

CELL_MM = 50.0          # 网格边长
SIGMA_MM = 100.0        # 位置野半径
REMAP_MIN_DIST_MM = 100.0   # 两次样本的物理距离小于这个才叫"同一个地点"
REMAP_SIM_THR = 0.5     # 激活相似度低于这个 = 重映射


def _load_envelope(path: str = ENV_MODEL) -> Dict[str, List[float]]:
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    return d.get("envelope") or {"x": [0.3, 0.85], "y": [-0.5, 0.7], "z": [0.05, 0.72]}


def cell_id(p_m: Tuple[float, float, float]) -> Tuple[int, int, int]:
    """物理位置 → 所在网格 (place cell 编号)。"""
    return tuple(int(math.floor(v * 1000.0 / CELL_MM)) for v in p_m)  # type: ignore


def cell_center(cid: Tuple[int, int, int]) -> Tuple[float, float, float]:
    return tuple((c + 0.5) * CELL_MM / 1000.0 for c in cid)  # type: ignore


def place_code(p_m: Tuple[float, float, float],
               radius_cells: Optional[int] = None,
               sigma_mm: float = SIGMA_MM) -> Dict[Tuple[int, int, int], float]:
    """位置 → 群体编码: 邻近网格的高斯加权激活 (稀疏)。

    radius 必须自适应: 只覆盖 ±2 格而 σ=100mm 时高斯被截断, 质心解码偏 13.6mm (实测)。
    按 3σ 覆盖 ⇒ radius = ceil(3σ/CELL), 解码才能自洽。
    """
    if radius_cells is None:
        radius_cells = max(2, int(math.ceil(3.0 * sigma_mm / CELL_MM)))
    base = cell_id(p_m)
    code: Dict[Tuple[int, int, int], float] = {}
    for dx in range(-radius_cells, radius_cells + 1):
        for dy in range(-radius_cells, radius_cells + 1):
            for dz in range(-radius_cells, radius_cells + 1):
                cid = (base[0] + dx, base[1] + dy, base[2] + dz)
                c = cell_center(cid)
                d = math.sqrt(sum((p_m[i] - c[i]) ** 2 for i in range(3))) * 1000.0
                a = math.exp(-0.5 * (d / sigma_mm) ** 2)
                if a > 1e-3:
                    code[cid] = a
    return code


def similarity(a: Dict, b: Dict) -> float:
    """两个群体编码的余弦相似度 (模式补全的程度: 1=完全同一群细胞, 0=完全不同)。"""
    if not a or not b:
        return 0.0
    keys = set(a) | set(b)
    dot = sum(a.get(k, 0.0) * b.get(k, 0.0) for k in keys)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def centroid(code: Dict) -> Optional[Tuple[float, float, float]]:
    """从群体编码反解位置 (群体向量解码) —— 部分细胞缺失时仍可用 = 模式补全。"""
    if not code:
        return None
    tot = sum(code.values())
    out = [0.0, 0.0, 0.0]
    for cid, a in code.items():
        c = cell_center(cid)
        for i in range(3):
            out[i] += c[i] * a
    return tuple(v / tot for v in out)  # type: ignore


class PlaceCellMap:
    """跨时间的位置细胞地图: 记录每次经过某网格时的表征与上下文, 检出重映射。

    融合定位节点接这块的方式 (只读, 不改 fuse_sensors 的数值):
        pc = PlaceCellMap()
        ev = pc.observe(p_tcp, ctx={"zone": zone, "cam": "arm", "src": "tcp"})
        # ev = {"cell", "sim_best", "remap", "n_seen", "code_n"}
    """

    def __init__(self) -> None:
        self.nodes: Dict[Tuple[int, int, int], List[Dict[str, Any]]] = {}
        self.events: List[Dict[str, Any]] = []

    def observe(self, p_m: Tuple[float, float, float],
                ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """记录一次到达, 检出重映射。

        🔴 关键认知 (实测教训): 只用位置的群体编码**物理上不可能**检出重映射 ——
           同一位置必然产生同样的 code (相似度恒 1.0, 实测 0/15 全漏)。
           真正的重映射是「同一物理地点, 不同的环境/上下文」, 所以判据必须带上下文:
             a) 同一地点 (<100mm) + 上下文不同  ⇒ remap (换场)
             b) 同一地点 + 上下文相同 + 激活相似度骤低 ⇒ remap (编码异常/真值抖)
           并且要比对**邻域**样本, 不能只比同一个网格 —— 真值偏 200mm 时格子早换了。
        """
        cid = cell_id(p_m)
        code = place_code(p_m)
        ctx = ctx or {}
        ctx_key = ctx.get("ctx_key")

        # 邻域搜索: ±2 格内的所有历史样本 (偏 200mm = 4 格, 已超出正常漂移范围)
        best_sim, best, best_d = 0.0, None, 1e9
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                for dz in range(-2, 3):
                    for prev in self.nodes.get((cid[0] + dx, cid[1] + dy, cid[2] + dz), []):
                        d_mm = math.sqrt(sum((p_m[i] - prev["p"][i]) ** 2 for i in range(3))) * 1000.0
                        if d_mm > REMAP_MIN_DIST_MM:
                            continue
                        s = similarity(code, prev["code"])
                        if d_mm < best_d or (abs(d_mm - best_d) < 1.0 and s > best_sim):
                            best_d, best_sim, best = d_mm, s, prev

        remap, why = False, ""
        if best is not None:
            prev_ctx_key = (best.get("ctx") or {}).get("ctx_key")
            if ctx_key is not None and prev_ctx_key is not None and ctx_key != prev_ctx_key:
                remap, why = True, "同一地点(%0.1fmm) 上下文变了: %s → %s" % (
                    best_d, prev_ctx_key, ctx_key)
            elif best_sim < REMAP_SIM_THR:
                remap, why = True, "同一地点(%0.1fmm) 激活相似度骤低 %.3f" % (best_d, best_sim)

        ev = {"cell": cid, "p": [round(v, 4) for v in p_m],
              "sim_best": round(best_sim, 3), "dist_mm": round(best_d, 1) if best else None,
              "remap": remap, "why": why,
              "n_seen": len(self.nodes.get(cid, [])),
              "code_n": len(code), "ctx": ctx}
        if remap:
            ev["prev_ctx"] = best.get("ctx") if best else None
            self.events.append(dict(ev, kind="remap"))
        self.nodes.setdefault(cid, []).append({"p": list(p_m), "code": code, "ctx": ctx})
        return ev

    def status(self) -> Dict[str, Any]:
        return {"cells": len(self.nodes), "samples": sum(len(v) for v in self.nodes.values()),
                "remaps": len(self.events), "events": self.events[-5:]}
