#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""l5_defect_check.py — L5(本地 SmolVLM) 指导 L2 旁路做**表面缺陷检查** + 自主标注积累

链路 (全部跑在 4060 本机, 不动工控机):
  ① L2 旁路取图: GET 10083 /picture?kind=origin&grab=1
  ② L2 摆正: tools/aoi_surface_rect.py::surface_judge (保留整块 · 长边水平 · 零插值)
  ③ L5 理解: 本地 SmolVLM (zmax_data/models/l5_vlm_merged_*) 看摆正后的模块图 → 小 JSON
  ④ 合并判决: L2 的 ROI 光学指标 (死白/清晰度) ⊕ L5 的缺陷语义 ⇒ 一条记录
  ⑤ 自主进化: 追加 data/memory/l5_defect_log.jsonl (每行=一帧的图+指标+VLM标注), 供日后训 L2 缺陷头

口径提醒 (老倪 2026-10-19 教训): 判决看**摆正后模块 ROI**, 不看整帧 mean。
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from aoi_surface_rect import surface_judge                              # noqa: E402
from lerobot.policies.yolo_3d.surface_optical import SurfaceOpticalQuality   # noqa: E402

MODEL = os.environ.get("ZMAX_LOCAL_VLM",
                       os.path.join(ROOT, "zmax_data/models/l5_vlm_merged_20261009_231339"))
OUTD = os.path.join(ROOT, "data/deliver")
LOGF = os.path.join(ROOT, "data/memory/l5_defect_log.jsonl")
STAMP = time.strftime("%Y%m%d_%H%M%S")

# 500M 级小模型给 JSON schema 会**照抄模板** (实测原文复读 '"type": "scratch|stain|chip|none"...'),
# ⇒ 改成分步二选一 + 一个开放描述; 解析按 yes/no 归一, 拿不准就记 unparsed 不猜。
QUESTIONS = [
    ("scratch", "Look at this optical module surface photo. Is there any visible scratch or line mark? "
                "Answer with one word only: yes or no."),
    ("stain", "Look at this optical module surface photo. Is there any stain, dirt or discoloration? "
              "Answer with one word only: yes or no."),
    ("chip", "Look at this optical module surface photo. Is any piece chipped, cracked or missing? "
             "Answer with one word only: yes or no."),
]
DESCRIBE = ("Describe in one short sentence what you actually see on this module surface "
            "(shape, brightness, any mark). Do not use JSON.")

_VLM = {}


def load_vlm():
    if _VLM:
        return _VLM
    import torch
    from transformers import AutoProcessor
    # transformers 5.x 改名: AutoModelForVision2Seq → AutoModelForImageTextToText (4.x 仍是旧名)
    try:
        from transformers import AutoModelForImageTextToText as _AM
    except ImportError:
        from transformers import AutoModelForVision2Seq as _AM
    t0 = time.time()
    proc = AutoProcessor.from_pretrained(MODEL)
    try:
        mdl = _AM.from_pretrained(MODEL, dtype=torch.float16, device_map="cuda")
    except TypeError:                                   # 老版 transformers 用 torch_dtype
        mdl = _AM.from_pretrained(MODEL, torch_dtype=torch.float16, device_map="cuda")
    mdl.eval()
    _VLM.update(proc=proc, model=mdl, load_s=round(time.time() - t0, 1))
    print("  VLM 就绪 %s (%.1fs)" % (os.path.basename(MODEL), _VLM["load_s"]))
    return _VLM


def _ask(v, img, question, max_new=24):
    """问一次, 返回 (text, ms)。"""
    import torch
    msgs = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": question}]}]
    chat = v["proc"].apply_chat_template(msgs, add_generation_prompt=True)
    inputs = v["proc"](text=chat, images=[img], return_tensors="pt").to("cuda")
    t0 = time.time()
    with torch.no_grad():
        out = v["model"].generate(**inputs, max_new_tokens=max_new, do_sample=False)
    ms = round((time.time() - t0) * 1000, 1)
    txt = v["proc"].batch_decode(out[:, inputs["input_ids"].shape[1]:], skip_special_tokens=True)[0].strip()
    return txt, ms


def _yes_no(txt):
    """严格归一: 只认开头的 yes/no (小模型常补一句解释)。认不出返回 None。"""
    t = (txt or "").strip().lower()
    if not t:
        return None
    head = t[:40]
    has_yes = "yes" in head
    has_no = re.search(r"\bno\b", head) is not None
    if has_yes and not has_no:
        return True
    if has_no and not has_yes:
        return False
    return None


def vlm_inspect(bgr):
    """摆正后的模块图 → 逐项二选一 + 开放描述。返回 (dict|None, raw_text, ms_total)。"""
    import torch                                                  # noqa: F401
    from PIL import Image as _Image
    v = load_vlm()
    img = _Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    res, raws, total = {}, [], 0.0
    for key, q in QUESTIONS:
        txt, ms = _ask(v, img, q, 24)
        total += ms
        yn = _yes_no(txt)
        res[key] = yn
        raws.append("%s=%s«%s»" % (key, {True: "yes", False: "no", None: "?"}[yn], txt[:40]))
    desc, ms2 = _ask(v, img, DESCRIBE, 64)
    total += ms2
    raws.append("desc«%s»" % desc[:120])
    judged = [v2 for v2 in res.values() if v2 is not None]
    out = {"defect": any(judged) if judged else None,
           "type": next((k for k, v2 in res.items() if v2 is True), "none"),
           "where": "unknown", "confidence": None,
           "per_item": res, "describe": desc}
    raw = " | ".join(raws)
    return (out if judged else None), raw, round(total, 1)


def main(grab=True, expand=True):
    os.makedirs(OUTD, exist_ok=True)
    os.makedirs(os.path.dirname(LOGF), exist_ok=True)

    # ① + ② L2 旁路取图与摆正
    sq = SurfaceOpticalQuality()
    expo = sq.exposure()
    im = sq.capture(grab=grab)
    if im is None:
        print("❌ 取帧失败 (10083 不可达)"); return 1
    ok_img, why = SurfaceOpticalQuality.usable(im)
    if not ok_img:
        print("❌ %s" % why); return 1
    crop, overlay, meta = surface_judge(im, out_long=1400, expand=expand)
    if crop is None:
        print("❌ 没搜到矩形刚体: %s" % meta.get("why")); return 1

    ch, cw = crop.shape[:2]
    l2_roi = SurfaceOpticalQuality.metrics(crop)
    l2_full = SurfaceOpticalQuality.metrics(im)
    l2_v, l2_why = SurfaceOpticalQuality.verdict(l2_roi)
    print("① L2 摆正: %dx%d 水平=%s 长宽比=%.2f 倾角=%.2f° 矩形度=%.3f no_stretch=%s"
          % (cw, ch, cw >= ch, max(cw, ch) / float(min(cw, ch)), float(meta.get("angle", 0)),
             float(meta.get("fill", 0)), meta.get("no_stretch")))
    print("② L2 ROI 光学: mean=%.1f 死白=%.2f%% 暗部=%.1f%% 清晰度=%.1f ⇒ %s"
          % (l2_roi["mean"], l2_roi["sat_pct"], l2_roi["dark_pct"], l2_roi["sharpness"], l2_v))
    print("   (整帧对照: mean=%.1f 暗部=%.1f%% — 黑背景会拉低整帧, 判决用 ROI)"
          % (l2_full["mean"], l2_full["dark_pct"]))

    # ③ L5 VLM 理解 (放大 2x 让 500M 模型看得清)
    up = cv2.resize(crop, (cw * 2, ch * 2), interpolation=cv2.INTER_CUBIC) if cw < 700 else crop
    png = os.path.join(OUTD, "l5_defect_roi_%s.png" % STAMP)
    cv2.imwrite(png, up)
    print("③ L5 VLM 看 %s (%dx%d)…" % (os.path.basename(png), up.shape[1], up.shape[0]))
    j, raw, vms = vlm_inspect(up)
    print("   VLM %sms → %s" % (vms, raw[:170] if raw else "(空)"))

    # ④ 合并判决: 光学硬指标 vs VLM 语义
    vlm_defect = bool((j or {}).get("defect")) if isinstance(j, dict) else None
    optics_bad = l2_v in ("overexposed", "too_dark")
    if vlm_defect is None:
        final = {"verdict": "vlm_unparsed", "why": "VLM 没给出可解析 JSON ⇒ 只报光学指标, 不编缺陷"}
    elif vlm_defect:
        final = {"verdict": "defect_suspect",
                 "why": "VLM 报 %s@%s conf=%.2f; 光学=%s"
                        % ((j or {}).get("type"), (j or {}).get("where"),
                           float((j or {}).get("confidence") or 0), l2_v)}
    else:
        final = {"verdict": "optics_blocked" if optics_bad else "ok",
                 "why": ("VLM 未见缺陷, 但光学不达标(%s ⇒ %s) ⇒ 不能判合格" % (l2_v, l2_why))
                        if optics_bad else "VLM 未见缺陷且光学达标"}

    rec = {"ts": STAMP, "expo": expo, "src": "L2表面旁路 + L5本地SmolVLM(4060)",
           "rect": {k: meta.get(k) for k in ("angle", "fill", "crop_size", "out_size",
                                             "no_stretch", "expand_px", "same_pixel_mean_diff")},
           "l2_roi": l2_roi, "l2_full": l2_full, "l2_verdict": l2_v, "l2_why": l2_why,
           "l5_model": os.path.basename(MODEL), "l5_raw": raw, "l5_json": j, "l5_ms": vms,
           "final": final, "roi_png": png}
    with open(LOGF, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print("④ 合并判决: %s — %s" % (final["verdict"], final["why"]))
    print("⑤ 已记入 %s (自主标注积累, 每行一帧)" % os.path.relpath(LOGF, ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main(grab="--nograb" not in sys.argv))
