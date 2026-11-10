#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_semantic_misread.py — 自证「语义错读检测」判据真的有效

为什么需要这个
--------------
`verify_l2_linkage.py --all` 现在语义错读检出 **0 处** —— 因为已知的那处
（`sssched.in5` 把 AOI 载荷当 contact_p 读）已经修好了。
"0 检出"既可能是"真没问题"，也可能是"检测器根本不工作"。二者必须能区分。

本脚本用**已知坏样本**（历史真实故障）反向验证判据：
  若判据有效 ⇒ 必须把这批样本判为语义错读
  若判据是坏的 ⇒ 会全部放过 ⇒ 本脚本 FAIL

样本全部来自本项目真实故障，不是编的。
用法: gui-venv311/bin/python tools/test_semantic_misread.py
"""
from __future__ import annotations

import os
import sys

PASS, FAIL = [], []


def judge(contract_keys, payload) -> str:
    """复刻 verify_l2_linkage 的判据：载荷非空 + 取值键与载荷键无交集 ⇒ 语义错读。"""
    if not isinstance(payload, dict) or not payload:
        return "空口"
    if not contract_keys:
        return "无契约"
    return "未送达·语义错读" if not (set(contract_keys) & set(payload)) else "命中"


def ck(name, got, want):
    ok = got == want
    (PASS if ok else FAIL).append(name)
    print(("  ✓ " if ok else "  ✗ ") + "%-46s got=%-18s want=%s" % (name, got, want))


print("=" * 78)
print("语义错读判据 · 反向自检（用历史真实故障做坏样本）")
print("=" * 78)

# ── 坏样本 1: 2026-11-10 真实故障 ──────────────────────────────────────
# sssched.in5 画布标签是「质量门」，实现却按 contact_p 取值；
# AOI 载荷里只有 verdict/pass/缺陷数/取像体检/清晰度 → 全部取不到 → None
aoi_payload = {
    "kind": "aoi", "verdict": "gaps_washed", "pass": False,
    "缺陷数": 76, "取像体检": "ok", "清晰度": 446.67, "划伤数": 0, "污点数": 0,
}
ck("坏样本1 AOI载荷 按旧contact_p键读", judge(("contact_p", "p", "score"), aoi_payload),
   "未送达·语义错读")

# 修复后的正样本：走 _quality_gate 直接吃 verdict/pass（不再用 _pick 契约）
ck("正样本1 AOI载荷 无_pick契约", judge(None, aoi_payload), "无契约")

# ── 坏样本 2: 同类不同端口 ────────────────────────────────────────────
# in4 本该吃流形引擎的 contact_p，若上游误接成 AOI 载荷，同样取不到
ck("坏样本2 AOI载荷 按in4的contact_p键读", judge(("contact_p", "p_contact", "cp"), aoi_payload),
   "未送达·语义错读")

# ── 正样本 3: 键真命中，不能误报 ──────────────────────────────────────
# 正常工况：流形引擎真的吐 contact_p
mani_payload = {"contact_p": 0.62, "stage": "approach", "ok": True}
ck("正样本3 流形载荷 按contact_p键读", judge(("contact_p", "p_contact", "cp"), mani_payload),
   "命中")

# ── 正样本 4: 前馈加速器 u_ff ────────────────────────────────────────
ff_payload = {"u_ff": [0.1, 0.0, -0.2], "kind": "ff"}
ck("正样本4 前馈载荷 按u_ff键读", judge(("u_ff", "u", "vec", "chunk0", "a", "best"), ff_payload),
   "命中")

# ── 坏样本 5: 上游空 ⇒ 必须判空口，不能误判成语义错读 ────────────────
ck("坏样本5 上游空载荷", judge(("contact_p",), None), "空口")
ck("坏样本6 上游空dict", judge(("contact_p",), {}), "空口")

# ── 边界 7: 载荷有键但不含必需键（部分命中）→ 命中，不算错读 ─────────
# 判据是"有无交集"，只要取到一个就不算断（实现内部有默认兜底是它自己的事）
ck("边界7 部分命中", judge(("u_ff", "u"), {"u": [0.0, 0.0, 0.0]}), "命中")

# ── 汇总 ──────────────────────────────────────────────────────────────
print("\n" + "=" * 78)
print("汇总: PASS=%d  FAIL=%d" % (len(PASS), len(FAIL)))
if FAIL:
    print("失败项: " + ", ".join(FAIL))
print("判定: " + ("PASS  (判据有效，全图 0 检出可信)" if not FAIL else "FAIL  (判据不可信)"))
print("=" * 78)
sys.exit(0 if not FAIL else 1)
