"""m3 进化器 CPU vs XPU 单代耗时对比（在 Intel 550C 上跑）。

判据：同一份超参、同一 seed，只换设备，比 evaluate() 墙钟。
"""
import os
import sys
import time

sys.path.insert(0, "/home/intel/hjepa_m3/tools")
sys.path.insert(0, "/home/intel/hjepa_m3/src")
sys.path.insert(0, "/home/intel/hjepa_m3")

import hjepa_m3_evolver_intel as E   # noqa: E402

try:
    base = E.default_hp()
except AttributeError:
    base = {"seed": 7, "d_e": 32, "n_layers": 3, "lr": 0.0125, "steps": 42,
            "batch": 64, "tau": 0.12, "lam_align": 0.18, "lam_g2i": 0.3}

print("超参:", {k: base[k] for k in sorted(base)})

res = {}
for dev in ("cpu", "xpu"):
    os.environ["SS_M3_DEV"] = dev
    h = dict(base)
    t0 = time.perf_counter()
    r = E.evaluate(h)
    dt = time.perf_counter() - t0
    res[dev] = dt
    line = "%-4s 单次 evaluate = %6.2fs  ok=%s  device=%s" % (
        dev, dt, r.get("ok"), r.get("device"))
    if r.get("ok"):
        line += "  rank=%s/%s  adv=%s" % (
            r.get("eff_rank_vis"), r.get("eff_rank_geo"),
            (round(r["adv"], 4) if r.get("adv") is not None else None))
    else:
        line += "  ERR: " + str(r.get("why"))[:110]
    print(line)

if res.get("cpu") and res.get("xpu"):
    sp = res["cpu"] / res["xpu"]
    print("加速比: %.2fx  (CPU %.2fs -> XPU %.2fs)" % (sp, res["cpu"], res["xpu"]))
