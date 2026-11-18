#!/usr/bin/env python3
"""跑批期间采五流形实况 (只读): 每 2s 拉一次 8815 /api/se3, 落 jsonl 作证据。
判定依据: A(位置) 在动 · B(轴)/D(滚转) 变化 · E(相位 s) 单调推进 · 帧龄 <2s。
"""
import json
import time
import urllib.request

OUT = time.strftime("zmax_data/se3_layers/live_run_%m%d_%H%M.jsonl")


def get(url, timeout=3.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    n = 0
    t_end = time.time() + 3600
    while time.time() < t_end:
        try:
            d = get("http://127.0.0.1:8815/api/se3")
            ne = d.get("nearest") or {}
            st = get("http://127.0.0.1:8797/api/arm/step_traj/status")
            rec = {"ts": round(time.time(), 3), "age_s": d.get("age_s"),
                   "A_mm": d.get("tcp_mm"), "n": d.get("n"), "phi_deg": d.get("phi_deg"),
                   "i": ne.get("i"), "dist_mm": ne.get("dist_mm"), "s": ne.get("s"), "s_mm": ne.get("s_mm"),
                   "axis_err_deg": d.get("axis_err_deg"),
                   "running": st.get("running"), "cursor": st.get("cursor"),
                   "start": st.get("start"), "done": st.get("done")}
            with open(OUT, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
            if not st.get("running") and n > 3 and int(st.get("cursor") or 0) >= 215:
                print("[done] cursor=%s after %d samples" % (st.get("cursor"), n), flush=True)
                break
        except Exception as e:                                              # noqa: BLE001
            print("[warn]", str(e)[:80], flush=True)
        time.sleep(2.0)
    print("[se3 sampler] samples=%d → %s" % (n, OUT), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
