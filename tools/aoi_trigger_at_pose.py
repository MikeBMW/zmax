#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aoi_trigger_at_pose.py — 跟着 215 点回放, 走到 AOI 检测位才触发 /capture_detect

老倪 2026-11-15: "继续重新回放动作...AOI检测要有结果"

踩过的坑(写在代码里):
  ① /picture?grab=1 只拍图, 不跑检测 —— last_result 的 n 不涨, t 不变
  ② 真触发是 POST /capture_detect (GET 会 405)
  ③ 10082 金手指的结论字段是 verdict(OK/NG), 没有 judge_ok/judge_why
  ④ 臂不在 AOI 视野时触发也会出"结果", 但那是垃圾(判据找不到模块边界) ——
     所以必须按 cursor 卡位, 不在位不触发

AOI 检测位(从 215 点真值表实测):
  表面检测位 tool1=(407.7,-383.0,539.1)mm → 轨迹 #164 (p=(409.6,-388.6,533.1), 8.4mm)
  y<-200 的点: #56-60, #159-173  ⇒ 表面/金手指视野区
  金手指视野: 回放实测 cursor 149~180 期间 10082 拍到过曝条
  因此触发窗口: SURF_WIN=(156,178)  GF_WIN=(88,102) 加上 y<-200 的 #54-62

用法:
  python3 tools/aoi_trigger_at_pose.py --duration 1800
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request

HOST = "192.168.23.23"
AR = "http://127.0.0.1:8797"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTDIR = os.path.join(REPO, "zmax_data", "reports", "aoi_at_pose")

# (port, 名字, 触发窗口 cursor 区间)
WINDOWS = [
    (10083, "housing(表面)", (156, 178)),
    (10082, "gf(金手指)",    (88, 102)),
    (10082, "gf(金手指)",    (54, 62)),
    (10082, "gf(金手指)",    (159, 178)),
]


def _get(url, timeout=12):
    return urllib.request.urlopen(url, timeout=timeout).read()


def _post(url, timeout=120):
    req = urllib.request.Request(url, method="POST")
    return urllib.request.urlopen(req, timeout=timeout).read()


def cursor():
    try:
        d = json.loads(_get(AR + "/api/arm/step_traj/status", 8).decode("utf-8"))
        return d.get("cursor"), d.get("running"), d.get("done")
    except Exception:                                                    # noqa: BLE001
        return None, None, None


def result(port):
    try:
        d = json.loads(_get("http://%s:%d/last_result" % (HOST, port), 12).decode("utf-8"))
        return {"n": d.get("n"), "t": d.get("t"), "ms": d.get("ms"),
                "count": d.get("count"), "verdict": d.get("verdict"),
                "judge_ok": d.get("judge_ok"), "judge_why": str(d.get("judge_why") or "")[:140],
                "defects": d.get("defects") or [], "saved_incoming": d.get("saved_incoming"),
                "origin": d.get("origin")}
    except Exception as e:                                               # noqa: BLE001
        return {"err": str(e)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=float, default=1800)
    ap.add_argument("--interval", type=float, default=1.5)
    a = ap.parse_args()
    os.makedirs(OUTDIR, exist_ok=True)
    ts = time.strftime("%m%d_%H%M%S")
    jl = os.path.join(OUTDIR, "%s.jsonl" % ts)
    print("aoi_trigger_at_pose → %s  windows=%s" % (jl, WINDOWS), flush=True)
    fired = {}          # port → 上次触发时的 cursor
    t0 = time.time()
    last_c = None
    with open(jl, "w", encoding="utf-8") as f:
        while time.time() - t0 < a.duration:
            c, running, done = cursor()
            if c != last_c:
                print("  cursor=%s running=%s done=%s" % (c, running, done), flush=True)
                last_c = c
            if c is None:
                time.sleep(a.interval)
                continue
            for port, name, (lo, hi) in WINDOWS:
                if not (lo <= c <= hi):
                    continue
                # 同一窗口内同 port 只触发一次(避免 9 秒检测被反复排队)
                if fired.get(port) == (lo, hi, c // 3):
                    continue
                try:
                    r = json.loads(_post("http://%s:%d/capture_detect" % (HOST, port), 120).decode("utf-8"))
                except Exception as e:                                   # noqa: BLE001
                    print("  [c=%s] %s 触发失败 %s" % (c, name, e), flush=True)
                    continue
                fired[port] = (lo, hi, c // 3)
                print("  [c=%s] 🔫 %s POST /capture_detect → %s" % (c, name, json.dumps(r, ensure_ascii=False)), flush=True)
                time.sleep(11)          # 等检测跑完(表面 9s)
                res = result(port)
                rec = {"ts": time.time(), "cursor": c, "port": port, "cam": name,
                       "trigger": r, "result": res}
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
                hit = bool((res.get("count") or 0) > 0 or res.get("verdict") in ("OK", "NG"))
                print("      → n=%s count=%s verdict=%s judge_ok=%s%s" % (
                    res.get("n"), res.get("count"), res.get("verdict"), res.get("judge_ok"),
                    "  ✅有结果" if hit else ""), flush=True)
                if res.get("defects"):
                    print("      defects=%s" % json.dumps(res["defects"], ensure_ascii=False)[:220], flush=True)
                if res.get("judge_why"):
                    print("      judge_why=%s" % res["judge_why"], flush=True)
            time.sleep(a.interval)
    print("\n完成 → %s" % jl, flush=True)


if __name__ == "__main__":
    main()
