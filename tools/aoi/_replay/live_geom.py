# -*- coding: utf-8 -*-
"""现场 12 帧: 根数 vs 几何全量(裁列/键行/亮度/区域cx/倾角/残差), 找 16 与 19 的差别在哪。"""
import json, urllib.request, time, numpy as np, cv2
from collections import Counter
H = "http://192.168.23.23:10082"
def g(p, t=60): return json.loads(urllib.request.urlopen(H+p, timeout=t).read().decode("utf-8","ignore"))
rows = []
for i in range(12):
    try:
        ci = g("/crop_info?grab=1"); reg = g("/region")
        rw = urllib.request.urlopen(H + "/picture?kind=origin&grab=1", timeout=60).read()
        fr = cv2.imdecode(np.frombuffer(rw, np.uint8), cv2.IMREAD_COLOR)
        p50 = float(np.median(cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)))
    except Exception as e:
        print(" 帧%d 失败 %s" % (i+1, str(e)[:40])); time.sleep(1); continue
    j = ci.get("judge") or {}; rg = (reg.get("region") or {}); q = reg.get("quality") or {}
    xt = j.get("x_trim") or {}
    rows.append((j.get("n_keys"), p50, j.get("sat_before"), j.get("dropped_pct"),
                 str(xt.get("dropped_cols")), str(j.get("kept_rows")), rg.get("cx"), rg.get("angle"),
                 q.get("stripe_line_resid_px"), q.get("gold_cover"), j.get("state")))
    time.sleep(0.4)
print("根数|  p50  | sat    | drop% | 裁列      | 键行      | 区域cx | 倾角  | 残差 | 金覆盖 | state")
for r in rows:
    print("%4s| %5.1f | %6.4f | %5.1f | %-9s | %-9s | %6.1f | %5.2f | %4.2f | %5.3f | %s" % r)
print("\n根数分布:", dict(Counter(r[0] for r in rows)))
k16 = [r for r in rows if r[0] == 16]; k19 = [r for r in rows if r[0] == 19]
for tag, gset in (("16根", k16), ("19根", k19)):
    if gset:
        print("%s: p50≈%.1f  cx≈%.1f  倾角≈%.2f  残差≈%.2f  金覆盖≈%.3f  裁列=%s  键行=%s" % (
            tag, np.mean([x[1] for x in gset]), np.mean([x[6] for x in gset]), np.mean([x[7] for x in gset]),
            np.mean([x[8] for x in gset]), np.mean([x[9] for x in gset]),
            Counter(x[4] for x in gset).most_common(1), Counter(x[5] for x in gset).most_common(1)))
