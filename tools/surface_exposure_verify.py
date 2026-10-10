#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""surface_exposure_verify.py — 用**真检测**验证表面相机曝光: 每档真抓真判, 打表。

为什么不用 aoi_surface_exposure_sweep.py 的结论直接拍板:
  那个工具量的是 `GET /picture?kind=origin&grab=1` 的**实时帧** —— 而现场照明是
  检测时才闪的, 实时帧常常是**灯灭**状态 ⇒ 扫出来的"暗"不代表检测时暗
  (实测: 80ms 时整幅判据图 mean 143/饱和 15.6%, 但实时帧扫出来 40ms 只有 34.8)。
  ⇒ 唯一可信的判据是**真跑一次检测**, 看工控机自己的 judge 结论。

判据(按重要性):
  1) judge.ok == True 且 judge_mode == 'crop'  ← 判据图真是"切出来的模块"
  2) 判据图饱和(>=250) ≤5% 且 60 <= mean <= 200
用法: ./gui-venv311/bin/python tools/surface_exposure_verify.py --cands 80000,50000,30000,20000,12000
"""
import argparse
import json
import time
import urllib.error
import urllib.request

import cv2
import numpy as np

BASE = "http://192.168.23.23:10083"


def req(url, method="GET", timeout=60):
    r = urllib.request.Request(url, method=method, headers={"User-Agent": "zmax-verify"})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:                                   # noqa: BLE001
        return 0, str(e).encode()


def set_exp(us, gain=1.8):
    st, raw = req("%s/exposure?us=%g&gain=%g" % (BASE, us, gain), "POST", 20)
    try:
        return json.loads(raw)
    except Exception:                                        # noqa: BLE001
        return {"raw": raw[:80].decode("utf-8", "replace")}


def detect(tries=3):
    for _ in range(tries):
        st, raw = req(BASE + "/capture_detect", "POST", 90)
        if st == 200:
            break
        time.sleep(3)
    time.sleep(1.5)
    st, raw = req(BASE + "/crop_info", timeout=20)
    try:
        ci = json.loads(raw)
    except Exception:                                        # noqa: BLE001
        ci = {}
    jd = ci.get("judge") or {}
    st, raw = req(BASE + "/picture?kind=judge&grab=1", timeout=40)
    stat = {}
    if st == 200 and len(raw) > 5000:
        g = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
        if g is not None:
            stat = {"mean": round(float(g.mean()), 1), "sat250": round(float((g >= 250).mean() * 100), 2),
                    "shape": list(g.shape)}
    return {"judge_ok": jd.get("ok"), "mode": ci.get("judge_mode"), "bbox": ci.get("judge_bbox"),
            "bright_frac": ci.get("bright_frac"), "why": (jd.get("why") or "")[:60], **stat}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cands", default="80000,50000,30000,20000,12000")
    ap.add_argument("--gain", type=float, default=1.8)
    ap.add_argument("--apply-best", action="store_true")
    a = ap.parse_args()
    st, raw = req(BASE + "/exposure", timeout=15)
    print("起点: %s" % raw[:200].decode("utf-8", "replace"))
    rows = []
    for us in [float(x) for x in a.cands.split(",") if x.strip()]:
        r = set_exp(us, a.gain)
        time.sleep(1.5)
        d = detect()
        rows.append((us, d))
        print("us=%-7g ok=%-5s → judge_ok=%-5s mode=%-18s bbox=%-16s 判据图 mean=%s sat=%s%%  (why=%s)"
              % (us, r.get("ok"), d.get("judge_ok"), d.get("mode"), str(d.get("bbox")),
                 d.get("mean"), d.get("sat250"), d.get("why")))
    good = [(u, d) for u, d in rows
            if d.get("judge_ok") and d.get("mode") == "crop" and (d.get("sat250") or 99) <= 5.0
            and 60 <= (d.get("mean") or 0) <= 200]
    if good:
        pick = min(good, key=lambda t: abs(t[1]["mean"] - 130.0))[0]
        print("\n合格档: %s" % ", ".join("us=%g" % u for u, _ in good))
    else:
        scored = sorted(rows, key=lambda t: (0 if (t[1].get("mode") == "crop") else 1,
                                             t[1].get("sat250") if t[1].get("sat250") is not None else 99))
        pick = scored[0][0]
        print("\n无合格档 ⇒ 取判据最好者 us=%g" % pick)
    print("★ 建议 us=%g" % pick)
    if a.apply_best:
        print("已应用: %s" % json.dumps(set_exp(pick, a.gain), ensure_ascii=False)[:180])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
