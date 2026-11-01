#!/usr/bin/env python3
# 只读位姿录制器 — 轮询 SDK 桥 /status 采真值, 不发任何运动指令
# 用法: python3 arm_pose_recorder.py <seconds> [rate_hz] [tag]
# 环境: ZMAX_BRIDGE_URL 默认 http://127.0.0.1:39061/status ; ZMAX_REC_DIR 默认 ~/.zmax/arm/rec
import json, os, sys, time, urllib.request

SECS = float(sys.argv[1]) if len(sys.argv) > 1 else 1800
RATE = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0
TAG = sys.argv[3] if len(sys.argv) > 3 else "move"
URL = os.environ.get("ZMAX_BRIDGE_URL", "http://127.0.0.1:39061/status")
OUT = os.environ.get("ZMAX_REC_DIR", os.path.expanduser("~/.zmax/arm/rec"))
os.makedirs(OUT, exist_ok=True)
path = os.path.join(OUT, "rec_%s_%s.jsonl" % (TAG, time.strftime("%Y%m%d_%H%M%S")))
lat = os.path.join(OUT, "latest.json")

dt = 1.0 / RATE
t_end = time.time() + SECS
t_start = time.time()
ok = fail = 0
lo, hi = {}, {}
f = open(path, "w", buffering=1)
f.write(json.dumps({"type": "header", "rate_hz": RATE, "src": URL,
                    "note": "read-only via SDK bridge; no motion command"}) + "\n")
while time.time() < t_end:
    t0 = time.time()
    try:
        with urllib.request.urlopen(URL, timeout=2.0) as r:
            st = (json.loads(r.read().decode()) or {}).get("status") or {}
        rec = {"ts": round(t0, 4), "wall": time.strftime("%H:%M:%S", time.localtime(t0))}
        rec.update(st)
        f.write(json.dumps(rec) + "\n")
        ok += 1
        try:                      # latest 走 tmp+replace, 读者永远读到完整 JSON
            with open(lat + ".tmp", "w") as lf:
                json.dump(rec, lf)
            os.replace(lat + ".tmp", lat)
        except Exception:
            pass
        for key in ("endInRef", "flangeInBase", "jointPos"):
            v = st.get(key)
            if isinstance(v, (list, tuple)):
                for i, x in enumerate(v):
                    if isinstance(x, (int, float)):
                        k = "%s[%d]" % (key, i)
                        lo[k] = min(lo.get(k, x), x)
                        hi[k] = max(hi.get(k, x), x)
    except Exception as e:
        fail += 1
        if fail <= 5:
            f.write(json.dumps({"ts": round(t0, 4), "error": str(e)[:200]}) + "\n")
    el = time.time() - t0
    if el < dt:
        time.sleep(dt - el)
span = max(time.time() - t_start, 1e-6)
summary = {"type": "summary", "path": path, "samples_ok": ok, "samples_fail": fail,
           "span_s": round(span, 1), "rate_hz_actual": round(ok / span, 2),
           "range": {k: [round(lo[k], 6), round(hi[k], 6)] for k in lo}}
f.write(json.dumps(summary) + "\n")
f.close()
with open(os.path.join(OUT, "last_summary.json"), "w") as sf:
    json.dump(summary, sf, indent=1)
print(json.dumps({k: summary[k] for k in ("path", "samples_ok", "samples_fail", "span_s", "rate_hz_actual")}))
