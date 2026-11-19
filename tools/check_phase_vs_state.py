#!/usr/bin/env python3
"""E 相位 ↔ 状态 对账 (只读; 跑完一轮后执行)。

三个判据:
  ① 停留点: 日志里到点时刻的相位 s 与 SEC.stops 参考值是否一致 (误差 <1% 相位 / <80mm 弧长)
  ② 状态: 用 8815 的 sectors 反查该相位属于哪个状态, 是否等于预期状态 (抓取/金手指AOI/表面AOI/放置)
  ③ 实况: 采样里 s 单调推进 (排除自交导致 dist>25mm 的投影跳点)

用法: python3 tools/check_phase_vs_state.py [run_log] [live_jsonl]
"""
import glob
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPECT = {(9, "close"): ("抓取", 0.0467), (125, "aoi10082"): ("金手指", 0.5723),
          (151, "aoi10082"): ("金手指", 0.7337), (172, "aoi10083"): ("表面", 0.8491),
          (205, "open"): ("放置", 0.9764)}


def get(url, timeout=4.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def main() -> int:
    log = sys.argv[1] if len(sys.argv) > 1 else open("/tmp/flow_log_path").read().strip()
    live = (sys.argv[2] if len(sys.argv) > 2 else
            sorted(glob.glob(os.path.join(ROOT, "zmax_data/se3_layers/live_run_*.jsonl")))[-1])
    blocks, events = [], []
    for line in open(log, encoding="utf-8"):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if "progress" in d:
            blocks.append(d["step"])
        elif d.get("grip_due"):
            events.append(("grip", d["i"], d.get("act")))
        elif "aoi" in json.dumps(d)[:40].lower():
            events.append(("aoi", d.get("i"), json.dumps(d, ensure_ascii=False)[:80]))
    if not blocks:
        print("[fail] 日志里没有 progress 块:", log)
        return 1

    def s_at(i: int):
        for b in blocks:
            if b["i"] <= i <= b["i1"]:
                f = 0.0 if b["i1"] == b["i"] else (i - b["i"]) / float(b["i1"] - b["i"])
                return b["s0"] + f * (b["s1"] - b["s0"])
        return None

    sec = get("http://127.0.0.1:8815/api/se3")
    sectors = (sec.get("sectors") or {}).get("blocks") or []
    L_mm = float((sec.get("summary") or {}).get("L_open_mm") or 0) or 1.0

    def state_of(s):
        for x in sectors:
            if x.get("s0", 0) <= s <= x.get("s1", 1):
                return x.get("state") or "-"
        return "?"

    def state_hit(want, s):
        """期望状态词是否落在该相位的状态里 (sectors 的 state 带后缀如 '抓取(合爪)')。"""
        return want in (state_of(s) or "")

    print("=== ① 停留点相位")
    print("  %-6s %-10s %8s %8s %8s %8s  %s" % ("点", "动作", "参考s", "日志s", "Δ相位", "Δmm", "状态(反查)"))
    ok_pts = 0
    for (i, act), (want_state, s_ref) in EXPECT.items():
        s = s_at(i)
        if s is None:
            continue
        d = abs(s - s_ref)
        hit = state_hit(want_state, s)
        ok = d < 0.01 and hit
        ok_pts += int(ok)
        print("  #%-5d %-10s %8.4f %8.4f %8.4f %8.1f  %s %s"
              % (i, act, s_ref, s, d, d * L_mm, state_of(s), "✓" if ok else "✗"))
    print("  停留点一致 %d/%d (判据 Δs<1%%)" % (ok_pts, len(EXPECT)))

    print("=== ② 状态带 (按相位反查 → 与停留点预期比对)")
    for st in sorted({v[0] for v in EXPECT.values()}):
        bands = [x for x in sectors if st in (x.get("state") or "")]
        cov = sum(max(0.0, x["s1"] - x["s0"]) for x in bands)
        print("  %-10s 段数 %2d · 相位覆盖 %5.1f%%" % (st, len(bands), cov * 100))

    rec = [json.loads(l) for l in open(live, encoding="utf-8") if l.strip()]
    ss = [r for r in rec if r.get("s") is not None]
    clean = [r for r in ss if (r.get("dist_mm") or 0) <= 25.0]
    ds = [clean[i]["s"] - clean[i - 1]["s"] for i in range(1, len(clean))]
    tiny = sum(1 for d in ds if -0.003 < d < -1e-4)         # 静置抖动(投影噪声, 可忽略)
    back = sum(1 for d in ds if -0.02 < d <= -0.003)        # 可疑回退(真异常)
    jump = sum(1 for d in ds if d <= -0.02)                 # 自交处投影换分支(已知)
    err = [abs(r["s"] - (s_at(int(r["i"])) or r["s"])) for r in clean if r.get("i") is not None]
    err_mm = [e * L_mm for e in err]
    print("=== ③ 实况采样 %d 条 (剔除自交跳点 %d 条)" % (len(ss), len(ss) - len(clean)))
    print("  s 范围 %.4f→%.4f · 静置抖动 %d · 可疑回退 %d · 投影换分支 %d · 帧内相位误差 中位 %.4f (%.1f mm) / P95 %.4f (%.1f mm)"
          % (min(r["s"] for r in clean), max(r["s"] for r in clean), tiny, back, jump,
             sorted(err)[len(err) // 2], sorted(err_mm)[len(err) // 2],
             sorted(err)[int(len(err) * 0.95)], sorted(err_mm)[int(len(err) * 0.95)]))
    verdict = (ok_pts == len(EXPECT) and back == 0)
    print("=== 结论: %s" % ("E 相位与状态对得上" if verdict else "有偏差, 见上表"))
    return 0 if verdict else 2


if __name__ == "__main__":
    raise SystemExit(main())
