#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""yolo_threshold_response.py — 在役 YOLO 的**阈值响应表** (报"无检出"之前必跑)。

为什么要有它 (2026-10-15 实测):
  本机真帧 (8791/local2, 1280x720, 均值 115.8) 上, 在役权重 models/yolo_peg_live.pt (peg/OPT_Gold) 实际
  **有**目标, 但最高只有 0.219 分:
      conf>=0.01 -> 12 个 · conf>=0.05 -> 2 个 · conf>=0.10 -> 1 个 · conf>=0.15 -> 1 个
      conf>=0.25 (tools/ss_meta_task_predict.py 用的阈值) -> **0 个**  ⇒ 报 "YOLO 无检出 ⇒ 定量视觉证据为空"
      conf>=0.40 (tools/ss_yolo_on_real.py 在役默认)     -> **0 个**
  ⇒ 结论: "无检出" 是**阈值口径**造成的, 不是"画面里没目标"。域偏移把分数压到 0.2 附近, 阈值 0.25/0.4 统一处理光。
  所以判"有没有目标"必须先出这张表, 并把置信度写进结论 (强 >0.4 · 弱 0.15~0.4 · 空 <0.15)。

用法:
  python3 tools/yolo_threshold_response.py --img /path/x.jpg [--weights models/yolo_peg_live.pt]
                                          [--imgsz 1280] [--json]
  python3 tools/yolo_threshold_response.py --dir zmax_data/eval_frames/live_1014_225637 --limit 6
只读: 只做推理, 不改权重、不改阈值、不写业务文件。
"""
from __future__ import annotations

import argparse
import glob
import json
import os

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRID = (0.01, 0.05, 0.10, 0.15, 0.20, 0.25, 0.40)


def _load(img: str):
    import cv2
    if img.startswith("http"):
        import urllib.request
        b = urllib.request.urlopen(img, timeout=15).read()
        return cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR)
    return cv2.imread(img)


def sweep(m, img, imgsz: int) -> dict:
    r = m.predict(np.ascontiguousarray(img), imgsz=imgsz, conf=0.01, verbose=False)[0]
    confs = [round(float(x), 4) for x in (r.boxes.conf.tolist() if r.boxes is not None else [])]
    clss = [m.names[int(k)] for k in (r.boxes.cls.tolist() if r.boxes is not None else [])]
    table = []
    for c in GRID:
        keep = [(s, k) for s, k in zip(confs, clss) if s >= c]
        table.append({"conf_th": c, "ndet": len(keep),
                      "best": (max(s for s, _ in keep) if keep else None),
                      "classes": sorted(set(k for _, k in keep))})
    top = max(confs) if confs else None
    verdict = ("空 (最高分 %.3f < 0.15 ⇒ 视为无定量视觉证据)" % top) if (top or 0) < 0.15 else (
        ("强 (最高分 %.3f ≥ 0.4)" % top) if top >= 0.4 else ("**弱非空** (最高分 %.3f ∈ [0.15,0.4) ⇒ 有目标但低置信, "
                                                             "报结论必须带 conf)" % top))
    return {"shape": list(r.orig_shape), "n_raw(conf0.01)": len(confs), "confs": confs[:12],
            "classes": clss[:12], "table": table, "top": top, "verdict": verdict}


def main() -> int:
    ap = argparse.ArgumentParser(description="在役 YOLO 阈值响应表 (报'无检出'前必跑)")
    ap.add_argument("--weights", default="models/yolo_peg_live.pt")
    ap.add_argument("--img", default="", help="单帧: 路径或 URL (如 http://127.0.0.1:8791/snapshot/local2.jpg)")
    ap.add_argument("--dir", default="", help="目录 (批处理)")
    ap.add_argument("--limit", type=int, default=6)
    ap.add_argument("--imgsz", type=int, default=1280)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    from ultralytics import YOLO
    wp = a.weights if os.path.isabs(a.weights) else os.path.join(ROOT, a.weights)
    m = YOLO(wp)
    imgs = [a.img] if a.img else sorted(
        [p for ext in ("*.jpg", "*.jpeg", "*.png", "*.bmp")
         for p in glob.glob(os.path.join(a.dir, ext))])[:a.limit]
    if not imgs:
        print("❌ 没给 --img / --dir")
        return 2
    out = {"weights": wp, "realpath": os.path.realpath(wp), "classes": m.names, "imgsz": a.imgsz, "items": []}
    for p in imgs:
        try:
            im = _load(p)
            if im is None:
                out["items"].append({"img": p, "err": "读取失败"})
                continue
            rec = sweep(m, im, a.imgsz)
            rec["img"] = p
            out["items"].append(rec)
            if not a.json:
                print("▶ %s  %s" % (p, rec["shape"]))
                for row in rec["table"]:
                    print("    conf>=%.2f  ndet=%-3s  best=%-7s  %s"
                          % (row["conf_th"], row["ndet"], row["best"], ",".join(row["classes"])))
                print("    判定: %s" % rec["verdict"])
        except Exception as e:                                                # noqa: BLE001
            out["items"].append({"img": p, "err": "%s: %s" % (type(e).__name__, str(e)[:80])})
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
