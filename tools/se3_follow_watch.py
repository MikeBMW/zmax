#!/usr/bin/env python3
"""跟随期留痕: 每 5s 记一次 /api/follow, 出现闭环/跳变/相位切换时打一行。
只读, 不干扰 se3_follow 本身。用法: python3 tools/se3_follow_watch.py [--secs 3600] [--every 5]
"""
import argparse
import json
import os
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "zmax_data", "se3_follow")


def get(url, t=3.0):
    with urllib.request.urlopen(url, timeout=t) as r:
        return json.loads(r.read().decode())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--secs", type=float, default=7200)
    ap.add_argument("--every", type=float, default=5.0)
    ap.add_argument("--url", default="http://127.0.0.1:8817/api/follow")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    fp = os.path.join(OUT, "progress_%s.jsonl" % time.strftime("%m%d_%H%M"))
    prev = {}
    t_end = time.time() + a.secs
    n = 0
    while time.time() < t_end:
        try:
            d = get(a.url)
            r, e = d.get("route") or {}, d.get("E") or {}
            rec = {"ts": round(time.time(), 2), "age_s": d.get("age_s"),
                   "A_mm": (d.get("A") or {}).get("mm"), "n": (d.get("B") or {}).get("n"),
                   "theta_deg": (d.get("C") or {}).get("theta_deg"),
                   "phi_deg": (d.get("D") or {}).get("phi_deg"),
                   "n_pts": r.get("n_pts"), "cum_mm": r.get("cum_mm"), "closed": r.get("closed"),
                   "jumps": r.get("jumps"), "span_mm": r.get("span_mm"),
                   "E_mode": e.get("mode"), "s": e.get("s"), "cum_lbl": e.get("cum_mm")}
            with open(fp, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
            if prev.get("closed") is False and r.get("closed") is True:
                print("[closed] 闭环成立 · L=%.1fmm · 相位 s=%.4f" % (e.get("L_mm") or 0, e.get("s") or 0), flush=True)
            if (r.get("jumps") or 0) > (prev.get("jumps") or 0):
                print("[jump] 累计跳变 %s 次 (最新 %.0f mm)" % (r.get("jumps"), r.get("last_jump_mm") or 0), flush=True)
            if prev and e.get("mode") != prev.get("E_mode"):
                print("[E] 模式切换 %s → %s" % (prev.get("E_mode"), e.get("mode")), flush=True)
            prev = {"closed": r.get("closed"), "jumps": r.get("jumps"), "E_mode": e.get("mode")}
        except Exception as ex:                                              # noqa: BLE001
            print("[warn]", str(ex)[:80], flush=True)
        time.sleep(a.every)
    print("[watch] %d 条 → %s" % (n, fp), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
