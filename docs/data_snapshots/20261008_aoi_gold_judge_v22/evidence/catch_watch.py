#!/usr/bin/env python3
"""高频守"判据渲染失败"那一刻: 数频率 + 一旦失败立刻把内存原图(不 grab)捞下来存档。
用法: catch_watch.py [秒数] [间隔秒]
"""
import os, sys, json, time, urllib.request
S = "/home/ubuntu/.hermes/cache/scratch"
DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
GAP = float(sys.argv[2]) if len(sys.argv) > 2 else 0.2

def jget(p, tmo=6):
    with urllib.request.urlopen("http://192.168.23.23:10082" + p, timeout=tmo) as r:
        return r.read()

n = ok = fail = 0
caught = []
sats_ok, sats_fail = [], []
frames = set()
t_end = time.time() + DUR
while time.time() < t_end:
    try:
        c = json.loads(jget("/crop_info").decode("utf-8", "replace"))
    except Exception:
        time.sleep(GAP); continue
    j = c.get("judge") or {}
    fn = c.get("n")
    if fn is not None and fn not in frames:      # 每次新帧只统计一次
        frames.add(fn)
        n += 1
        if j.get("out") is None:                 # ✅ 正确判据: 失败时 v20 别名全是 null
            fail += 1
            sats_fail.append(j.get("sat_before"))
            try:
                raw = jget("/picture?kind=origin")
                f = os.path.join(S, "fail_%s_n%s.png" % (time.strftime("%H%M%S"), fn))
                open(f, "wb").write(raw)
                caught.append((fn, j.get("sat_before"), os.path.basename(f)))
                print("  ✗ 失败帧 n=%s sat_before=%s → %s" % (fn, j.get("sat_before"), os.path.basename(f)))
            except Exception as e:
                print("  ✗ 失败帧 n=%s 但取图失败: %s" % (fn, e))
        else:
            ok += 1
            sats_ok.append(j.get("sat_before"))
    time.sleep(GAP)
print("采样新帧 %d | 成功 %d | 失败 %d (失败率 %.1f%%)" % (n, ok, fail, 100.0 * fail / max(1, n)))
if sats_ok:
    print("正常帧 sat_before 范围 %.3f~%.3f" % (min(sats_ok), max(sats_ok)))
if sats_fail:
    print("失败帧 sat_before: %s" % sats_fail)
print("抓到 %d 帧失败原图: %s" % (len(caught), caught))
