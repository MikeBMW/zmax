#!/usr/bin/env python3
"""端侧 IR 推理 + 与 torch 参考结果对比: 证明 OpenVINO IR 不是"跑得快但不准"。
Intel 侧: 用 IR 跑图, 导出 JSON (手工 letterbox + v8 decode + NMS, 不依赖 ultralytics/torch)。
用法: python edge_yolo_infer.py <xml> <图片目录或文件...> --out result.json [--device NPU]
"""
import argparse
import json
import os
import time

import cv2
import numpy as np
import openvino as ov

IMGSZ = 640
PAD = 114


def letterbox(img, size=IMGSZ):
    h, w = img.shape[:2]
    r = min(size / h, size / w)
    nh, nw = int(round(h * r)), int(round(w * r))
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((size, size, 3), PAD, dtype=np.uint8)
    top, left = (size - nh) // 2, (size - nw) // 2
    canvas[top:top + nh, left:left + nw] = resized
    return canvas, r, (left, top)


def preprocess(img):
    lb, r, pad = letterbox(img)
    x = lb[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0
    return np.ascontiguousarray(x), r, pad


def postprocess(out, r, pad, conf_th=0.25, iou_th=0.45):
    p = out[0] if out.ndim == 3 and out.shape[0] == 1 else out
    if p.shape[0] < p.shape[1]:
        p = p.transpose(1, 0)          # (8400, 4+nc)
    boxes, scores, cls = [], [], []
    for row in p:
        cls_scores = row[4:]
        c = int(np.argmax(cls_scores))
        s = float(cls_scores[c])
        if s < conf_th:
            continue
        cx, cy, w, h = row[:4]
        boxes.append([float(cx - w / 2), float(cy - h / 2), float(w), float(h)])
        scores.append(s)
        cls.append(c)
    if not boxes:
        return []
    idx = cv2.dnn.NMSBoxes([[b[0], b[1], b[2], b[3]] for b in boxes], scores, conf_th, iou_th)
    idx = np.array(idx).flatten().tolist() if len(idx) else []
    res = []
    for i in idx:
        x, y, w, h = boxes[i]
        res.append({
            "cls": cls[i], "conf": round(scores[i], 4),
            "xyxy": [round((x - pad[0]) / r, 1), round((y - pad[1]) / r, 1),
                     round((x - pad[0] + w) / r, 1), round((y - pad[1] + h) / r, 1)],
        })
    return sorted(res, key=lambda d: -d["conf"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("xml")
    ap.add_argument("images", nargs="+")
    ap.add_argument("--out", default="ir_result.json")
    ap.add_argument("--device", default="NPU")
    ap.add_argument("--iters", type=int, default=30)
    a = ap.parse_args()

    files = []
    for p in a.images:
        if os.path.isdir(p):
            files += [os.path.join(p, f) for f in sorted(os.listdir(p)) if f.lower().endswith((".jpg", ".png"))]
        else:
            files.append(p)
    files = files[:8]

    core = ov.Core()
    cm = core.compile_model(core.read_model(a.xml), a.device)
    out_port = cm.output(0)
    rows = []
    for f in files:
        img = cv2.imread(f)
        if img is None:
            continue
        x, r, pad = preprocess(img)
        y = cm(x)[out_port]  # warmup
        t = time.perf_counter()
        for _ in range(a.iters):
            y = cm(x)[out_port]
        infer_ms = (time.perf_counter() - t) * 1000.0 / a.iters
        dets = postprocess(y, r, pad)
        rows.append({"file": os.path.basename(f), "shape": list(img.shape), "infer_ms": round(infer_ms, 2), "dets": dets})
        print("%-28s %4dx%-4d %6.2f ms  %d 个框 %s" % (os.path.basename(f), img.shape[1], img.shape[0], infer_ms,
                                                       len(dets), [(d["cls"], d["conf"]) for d in dets[:3]]), flush=True)
    with open(a.out, "w") as fp:
        json.dump({"device": a.device, "imgsz": IMGSZ, "rows": rows}, fp, ensure_ascii=False, indent=2)
    print("写出", a.out)


if __name__ == "__main__":
    main()
