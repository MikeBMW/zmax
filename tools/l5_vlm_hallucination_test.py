#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l5_vlm_hallucination_test.py — 判 VLM 的缺陷判断到底能不能信 (不是走过场)

三条判据 (缺一条都不能拿 VLM 的 yes 当缺陷依据):
 ① 空图基线: 纯黑 / 纯灰 / 纯噪声 三类"不可能有划痕"的图 ⇒ 若也报 scratch=yes 就是幻觉
 ② 反向提问一致性: 同一张图问 "Is it perfectly clean?" 与 "any scratch?" 答案应互补;
    两个都 yes (或都 no) ⇒ 模型在顺着问题说, 不可用
 ③ 重复稳定性: 同图同问 3 次, 答案应一致; 抖动 ⇒ 置信度为零
"""
from __future__ import annotations

import os
import sys

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import l5_defect_check as L                                  # noqa: E402

PASS = FAIL = 0


def ck(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  ✅ %s%s" % (name, ("  — %s" % detail) if detail else ""))
    else:
        FAIL += 1
        print("  ❌ %s%s" % (name, ("  — %s" % detail) if detail else ""))


def ask_scratch(img_bgr):
    j, raw, ms = L.vlm_inspect(img_bgr)
    return (j or {}).get("per_item", {}).get("scratch"), raw, ms


print("=" * 78)
print("VLM 缺陷判断可信度测试 (SmolVLM 500M 级)")
print("=" * 78)

# ── ① 空图基线 ──
print("\n① 空图基线 (这些图不可能有划痕):")
BLANK = {
    "纯黑": np.zeros((188, 1282, 3), np.uint8),
    "纯灰": np.full((188, 1282, 3), 128, np.uint8),
    "纯噪声": np.random.default_rng(7).integers(0, 255, (188, 1282, 3), dtype=np.uint8),
}
blank_yes = 0
for name, im in BLANK.items():
    yn, raw, _ = ask_scratch(im)
    if yn:
        blank_yes += 1
    print("   %-6s → scratch=%s  %s" % (name, {True: "yes", False: "no", None: "?"}[yn], raw[:96]))
ck("① 空图上不报划痕", blank_yes == 0, "%d/3 张空图报了划痕" % blank_yes)

# ── ② 反向提问一致性 (真图) ──
print("\n② 反向提问一致性 (同一张真模块图):")
sq = L.SurfaceOpticalQuality()
im = sq.capture(grab=False)
if im is None:
    ck("② 反向提问一致性", False, "取不到真图, 无法测")
else:
    from aoi_surface_rect import surface_judge                         # noqa: E402
    crop, _, _ = surface_judge(im, out_long=1400, expand=True)
    if crop is None:
        ck("② 反向提问一致性", False, "没搜到刚体")
    else:
        up = cv2.resize(crop, (crop.shape[1] * 2, crop.shape[0] * 2), interpolation=cv2.INTER_CUBIC)
        from PIL import Image as _I
        pil = _I.fromarray(cv2.cvtColor(up, cv2.COLOR_BGR2RGB))
        v = L.load_vlm()
        t1, _ = L._ask(v, pil, "Is there any visible scratch or line mark? Answer one word: yes or no.", 24)
        t2, _ = L._ask(v, pil, "Is this surface perfectly clean with no scratch at all? Answer one word: yes or no.", 24)
        y1, y2 = L._yes_no(t1), L._yes_no(t2)
        print("   问『有划痕吗』→ %s«%s»" % ({True: "yes", False: "no", None: "?"}[y1], t1[:40]))
        print("   问『是不是完全干净』→ %s«%s»" % ({True: "yes", False: "no", None: "?"}[y2], t2[:40]))
        consistent = (y1 is not None and y2 is not None and y1 != y2)
        ck("② 反向提问答案互补", consistent,
           "互补=可信; 两个都 yes/no ⇒ 顺着问题说" if not consistent else "有划痕=yes 且 完全干净=no")

        # ── ③ 重复稳定性 ──
        print("\n③ 重复稳定性 (同图同问 3 次):")
        reps = []
        for i in range(3):
            t, _ = L._ask(v, pil, "Is there any visible scratch or line mark? Answer one word: yes or no.", 24)
            reps.append(L._yes_no(t))
            print("   第%d次 → %s«%s»" % (i + 1, {True: "yes", False: "no", None: "?"}[reps[-1]], t[:40]))
        ck("③ 三次答案一致", len(set(reps)) == 1, "实际=%s" % [str(r) for r in reps])

print("-" * 78)
print("结果: %d/%d PASS" % (PASS, PASS + FAIL))
if FAIL:
    print("⇒ 有项没过 ⇒ VLM 的缺陷判断**不能当依据**, 只能当描述性线索; 缺陷结论须由 L2 光学指标 + 人工确认兜底")
sys.exit(0 if FAIL == 0 else 1)
