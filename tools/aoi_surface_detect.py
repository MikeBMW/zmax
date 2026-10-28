#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aoi_surface_detect.py — 触发工控机 10083 的 YOLO(housing) 真检测, 拿**这一次**的缺陷结果 + 出图

为什么不能只看 /last_result: 它是"最后一次"结果 —— 不触发时读到的是上一轮(几小时前的也有)。
   老倪/技能都踩过: 点「请求检测」报的实际是上一帧的判决。
   本脚本以 `t`(结果时间戳) 变化为唯一新旧判据, 等不到就明说"没等到新结果", 不冒充。

工控机输出口径 (实测字段):
   verdict / count / defects[] / detect_type=housing / ms / judge_ok / judge_why
   model_input(模型吃的那张 1280 校验图) / origin(2448x2048 原图) / saved_incoming
⚠️ verdict=OK & count=0 **不等于合格**: judge_ok=False(找不到过曝亮条/工件不在位) 时检测本身不可信。
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = os.environ.get("ZMAX_SURFACE_AOI_URL", "http://192.168.23.23:10083").rstrip("/")
UA = {"User-Agent": "zmax-probe"}
OUTD = os.path.join(ROOT, "data/deliver")


def jget(path, t=20):
    return json.loads(urllib.request.urlopen(urllib.request.Request(BASE + path, headers=UA), timeout=t).read())


def post(path, t=40):
    return json.loads(urllib.request.urlopen(
        urllib.request.Request(BASE + path, method="POST", headers=UA), timeout=t).read())


def get_bytes(path, t=30):
    return urllib.request.urlopen(urllib.request.Request(BASE + path, headers=UA), timeout=t).read()


def detect(wait_s=70.0):
    """触发一次新检测并以 t 变化确认为"这一次"。返回 (result|None, note)。"""
    try:
        old = jget("/last_result")
        old_t = float(old.get("t") or 0)
    except Exception:                                              # noqa: BLE001
        old_t, old = 0.0, {}
    expo = jget("/exposure")
    print("  当前曝光 us=%s gain=%s | 旧结果 t=%s verdict=%s count=%s"
          % (expo.get("us"), expo.get("gain"), old_t or "—", old.get("verdict"), old.get("count")))

    try:
        acc = post("/capture_detect")
        print("  已受理: %s" % json.dumps(acc, ensure_ascii=False)[:80])
    except Exception as e:                                         # noqa: BLE001
        return None, "受理失败 %s: %s" % (type(e).__name__, str(e)[:60])

    t0 = time.time()
    while time.time() - t0 < wait_s:
        try:
            d = jget("/last_result", 12)
            nt = float(d.get("t") or 0)
            if nt > old_t + 1e-6:
                return d, "新结果 (等待 %.1fs, t %.1f → %.1f)" % (time.time() - t0, old_t, nt)
        except Exception:                                          # noqa: BLE001
            pass
        time.sleep(2.0)
    return None, "%.0fs 内没等到新结果 (推理约 8.7s, 也可能这轮没拍成)" % wait_s


def main():
    os.makedirs(OUTD, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    print("=" * 74)
    print("工控机 10083 YOLO(housing) 真检测 — %s" % BASE)
    print("=" * 74)

    res, note = detect()
    print("  %s" % note)
    if res is None:
        print("\n⇒ 没拿到这一次的结果。不拿旧结果冒充。")
        return 1

    verdict, count, defects = res.get("verdict"), res.get("count"), res.get("defects") or []
    judge_ok, judge_why = res.get("judge_ok"), res.get("judge_why") or ""
    print("\n  判决      : %s · 缺陷 %s · 推理 %sms · detect_type=%s"
          % (verdict, count, res.get("ms"), res.get("detect_type")))
    print("  判据      : judge_ok=%s%s" % (judge_ok, (" — " + str(judge_why)[:70]) if judge_why else ""))
    print("  模型输入  : %s" % res.get("model_input"))
    print("  原图      : %s" % res.get("origin"))
    print("  缺陷明细  : %s" % (json.dumps(defects, ensure_ascii=False)[:300] if defects else "[] (无)"))

    # ── 出图: 原图 (缺陷框若有) + 判据/模型输入图 ──
    shots = {}
    for kind, tag in (("origin", "原图"), ("judge", "判据图")):
        try:
            raw = get_bytes("/picture?kind=%s" % kind, 30)
            im = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
            if im is not None:
                shots[tag] = im
        except Exception as e:                                     # noqa: BLE001
            print("  ⚠️ 取 %s 失败 %s" % (kind, type(e).__name__))

    # 缺陷框: defects 里若有 bbox/xyxy 就画到原图上
    if defects and "原图" in shots:
        im = shots["原图"]
        h, w = im.shape[:2]
        n_drawn = 0
        for i, d in enumerate(defects, 1):
            bb = d.get("bbox") or d.get("xyxy") or d.get("box")
            if isinstance(bb, (list, tuple)) and len(bb) >= 4:
                x1, y1, x2, y2 = [float(v) for v in bb[:4]]
                if max(x1, y1, x2, y2) <= 1.5:            # 归一化坐标
                    x1, x2 = x1 * w, x2 * w
                    y1, y2 = y1 * h, y2 * h
                cv2.rectangle(im, (int(x1), int(y1)), (int(x2), int(y2)), (0, 0, 255), 3)
                cv2.putText(im, "%s %.2f" % (str(d.get("cls") or d.get("name") or i),
                                             float(d.get("conf") or d.get("score") or 0)),
                            (int(x1), max(18, int(y1) - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
                n_drawn += 1
        shots["原图"] = im
        print("  已画缺陷框: %d 个" % n_drawn)

    out = os.path.join(OUTD, "surface_yolo_detect_%s.png" % stamp)
    for tag, im in shots.items():
        p = os.path.join(OUTD, "surface_yolo_%s_%s.png" % ("origin" if tag == "原图" else "judge", stamp))
        cv2.imwrite(p, im)
        print("  %s → %s (%dx%d)" % (tag, os.path.relpath(p, ROOT), im.shape[1], im.shape[0]))

    rec = {"ts": stamp, "expo": {"us": res.get("exposure_us")},
           "verdict": verdict, "count": count, "defects": defects,
           "judge_ok": judge_ok, "judge_why": judge_why, "ms": res.get("ms"),
           "detect_type": res.get("detect_type"), "model_input": res.get("model_input"),
           "origin": res.get("origin"), "saved_incoming": res.get("saved_incoming"),
           "note": note}
    with open(os.path.join(ROOT, "data/memory/l2_yolo_detect_log.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print("\n结论:")
    if count and count > 0:
        print("  🔴 工控机 YOLO 报 %d 处缺陷 — 这些是**模型真检出**的, 不是统计候选" % count)
    elif judge_ok is True:
        print("  ✅ 0 缺陷 且 判据通过 ⇒ 这一帧可信")
    else:
        print("  ⚠️ 0 缺陷 但 判据未通过 (judge_ok=%s) ⇒ **不能当合格**: 找不到过曝亮条通常意味着"
              "工件不在位/曝光不对, 此时 0 缺陷没有意义" % judge_ok)
    return 0


if __name__ == "__main__":
    sys.exit(main())
