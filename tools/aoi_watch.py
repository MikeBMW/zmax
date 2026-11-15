#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aoi_watch.py — 跟着 215 点回放跑，在臂进入 AOI 视野时抓检测结果

老倪 2026-11-15: "继续重新回放动作，我已经回位了，这次夹爪抓住光模块了，AOI检测要有结果"

做法:
  每 INTERVAL 秒对 10082(金手指)/10083(表面) 各做一次:
    1. 先读 /picture (不带 grab, 8~11ms 拿旧图) 看画面亮度/过曝条够不够
    2. 过曝条足够 OR 亮度明显升高 ⇒ 才触发 /picture?grab=1 (约 0.6s, 会跑判据)
    3. 读 /last_result, 记录 judge_ok / count / defects / judge_why
  这样不会一直狂调 grab 拖垮 AOI 服务, 又能在臂真到位时第一时间抓到结果。

输出:
  zmax_data/reports/aoi_watch/<ts>.jsonl   每次采样一行
  zmax_data/reports/aoi_watch/<ts>.summary.json  结束时汇总(有结果的场次)

判据"有结果"的定义(任一):
  · count > 0                     检出缺陷
  · defects 非空                  缺陷清单非空
  · judge_ok is True              判据过了(模块边界定住了)
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

import cv2
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTDIR = os.path.join(REPO, "zmax_data", "reports", "aoi_watch")
HOST = "192.168.23.23"
CAMS = {10082: "gf(金手指)", 10083: "housing(表面)"}
INTERVAL = float(os.environ.get("AOI_WATCH_INTERVAL", "3.0"))
DURATION = float(os.environ.get("AOI_WATCH_DURATION", "900"))   # 默认看 15 分钟
BAR_P99_MIN = float(os.environ.get("AOI_WATCH_P99", "180"))    # 过曝条判据: p99 高于这个才抓


def _get(url, timeout=12):
    return urllib.request.urlopen(url, timeout=timeout).read()


def _img_stat(buf):
    im = cv2.imdecode(np.frombuffer(buf, np.uint8), cv2.IMREAD_COLOR)
    if im is None:
        return None
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    return {"wh": [int(g.shape[1]), int(g.shape[0])], "mean": round(float(g.mean()), 1),
            "p99": int(np.percentile(g, 99)),
            "over250": round(float((g >= 250).mean() * 100), 2)}


def probe(port):
    rec = {"port": port, "cam": CAMS[port], "ts": time.time()}
    try:
        # 🔴 必须 grab=1 强制新拍: /picture 不带 grab 是缓存图, md5 两次完全一样,
        #    用缓存判断 hot 永远 False ⇒ 监控形同虚设(踩过一次)。
        g = _img_stat(_get("http://%s:%d/picture?grab=1" % (HOST, port), 45))
        rec["grab"] = g
        rec["hot"] = bool(g and (g["p99"] >= BAR_P99_MIN or g["over250"] >= 1.0))
        lr = json.loads(_get("http://%s:%d/last_result" % (HOST, port), 10).decode("utf-8"))
        rec["judge_ok"] = lr.get("judge_ok")
        rec["count"] = lr.get("count")
        rec["defects"] = lr.get("defects") or []
        rec["judge_why"] = str(lr.get("judge_why") or "")[:160]
        rec["judge"] = lr.get("judge") or lr.get("judge_file")
        rec["result_keys"] = sorted(lr.keys())
        # 热的时候把图和完整结果一起落盘 —— 这就是"AOI 有结果"的实证
        if rec["hot"]:
            stamp = time.strftime("%m%d_%H%M%S")
            jp = os.path.join(OUTDIR, "grab_%d_%s.jpg" % (port, stamp))
            try:
                with open(jp, "wb") as gf:
                    gf.write(_get("http://%s:%d/picture?grab=1" % (HOST, port), 45))
                rec["saved_img"] = jp
            except Exception:                                            # noqa: BLE001
                pass
            rp = os.path.join(OUTDIR, "result_%d_%s.json" % (port, stamp))
            with open(rp, "w", encoding="utf-8") as rf:
                json.dump(lr, rf, ensure_ascii=False, indent=2)
            rec["saved_result"] = rp
        # 🔴 10082 金手指的结论字段是 verdict(OK/NG), 没有 judge_ok —— 只看 judge_ok 会漏掉它
        rec["verdict"] = lr.get("verdict")
        rec["has_result"] = bool((lr.get("count") or 0) > 0 or (lr.get("defects") or [])
                                or lr.get("judge_ok") is True
                                or lr.get("verdict") in ("OK", "NG"))
    except Exception as e:                                               # noqa: BLE001
        rec["err"] = "%s: %s" % (type(e).__name__, e)
    return rec


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    ts = time.strftime("%m%d_%H%M%S")
    jl = os.path.join(OUTDIR, "%s.jsonl" % ts)
    print("aoi_watch → %s  每 %.1fs, 看 %.0fs (p99>=%.0f 才 grab)" % (jl, INTERVAL, DURATION, BAR_P99_MIN), flush=True)
    t0 = time.time()
    hits = []
    n = 0
    with open(jl, "w", encoding="utf-8") as f:
        while time.time() - t0 < DURATION:
            for port in CAMS:
                rec = probe(port)
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
                n += 1
                tag = ""
                if rec.get("hot"):
                    tag = " 🔥grab cnt=%s ok=%s" % (rec.get("count"), rec.get("judge_ok"))
                if rec.get("has_result"):
                    tag += " ✅有结果"
                    hits.append(rec)
                    print("  [%5.1fs] %s%s" % (time.time() - t0, rec["cam"], tag), flush=True)
                elif rec.get("hot"):
                    print("  [%5.1fs] %s%s" % (time.time() - t0, rec["cam"], tag), flush=True)
            time.sleep(INTERVAL)
    summ = {"ts": ts, "samples": n, "seconds": round(time.time() - t0, 1),
            "hits": len(hits), "hit_records": hits[-20:],
            "jsonl": jl}
    sp = os.path.join(OUTDIR, "%s.summary.json" % ts)
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(summ, f, ensure_ascii=False, indent=2)
    print("\n汇总: 采样 %d 次, 有结果 %d 次 → %s" % (n, len(hits), sp), flush=True)


if __name__ == "__main__":
    main()
