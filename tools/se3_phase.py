"""s ∈ S¹ 相位: 弧长重参数化 (闭环)。

为什么: 之前只有整数索引 i/214 当相位 —— 索引不是弧长, 采样 dt 不等间距、速度也不均
⇒ 索引等分不等于路程等分, 相位不可比、不可环绕。这里把 215 帧 TCP 位置连成折线,
按累计弧长给 s∈[0,1), 并把首末 3.91mm 的缝也计入闭合长度 ⇒ s 真的是圆上的坐标:
  s_i = cum_i / (L + seam),   s_214 = L/(L+seam) < 1,  s_0 = 0
Δs 用环绕公式 Δs=((s2-s1+0.5) mod 1)-0.5 (跨 seam 不会跳 1.0)。
"""
import json
import math
import sys

REPO = "/home/ubuntu/zmax"
TRAJ = REPO + "/tools/web/real_traj_joints.json"
HOPF = REPO + "/zmax_data/rokae_sdk/traj_hopf.json"
OUT = REPO + "/zmax_data/rokae_sdk/traj_phase.json"


def wrap(d):
    return ((d + 0.5) % 1.0) - 0.5


def main() -> int:
    fr = json.load(open(TRAJ, encoding="utf-8"))["frames"]
    P = [[c * 1000.0 for c in f["p"]] for f in fr]
    n = len(P)
    cum = [0.0]
    for i in range(1, n):
        cum.append(cum[-1] + math.dist(P[i - 1], P[i]))
    L = cum[-1]
    seam = math.dist(P[-1], P[0])
    Lc = L + seam
    s = [c / Lc for c in cum]
    s_mm = list(cum)
    ds_mm = [cum[i] - cum[i - 1] if i else 0.0 for i in range(n)]
    rows = [{"i": i, "s": round(s[i], 6), "s_mm": round(s_mm[i], 2),
             "ds_mm": round(ds_mm[i], 2), "t": round(float(fr[i].get("t") or 0), 3)}
            for i in range(n)]
    # 关键帧自检: 环绕差
    marks = [0, 36, 108, 205, n - 1]
    chk = [{"i": i, "s": round(s[i], 4), "s_mm": round(s_mm[i], 1)} for i in marks]
    # 索引等分 vs 弧长等分的偏差(证明索引不是相位)
    dev = max(abs(s[i] - i / (n - 1)) for i in range(n))
    out = {"frames": rows,
           "summary": {"n": n, "L_open_mm": round(L, 1), "seam_mm": round(seam, 2),
                       "L_closed_mm": round(Lc, 1), "s_214": round(s[-1], 6),
                       "index_vs_arc_max_dev": round(dev, 4),
                       "wrap": "ds=((s2-s1+0.5) mod 1)-0.5", "marks": chk}}
    json.dump(out, open(OUT, "w"), ensure_ascii=False)
    # 同源补进 traj_hopf.json(唯一真值文件, 不另立山头)
    h = json.load(open(HOPF, encoding="utf-8"))
    for r in h["frames"]:
        r["s"] = s[r["i"]]
        r["s_mm"] = round(s_mm[r["i"]], 2)
    h["summary"]["L_open_mm"] = round(L, 1)
    h["summary"]["L_closed_mm"] = round(Lc, 1)
    h["summary"]["seam_mm"] = round(seam, 2)
    h["summary"]["s_on_S1"] = {"n": n, "s_214": round(s[-1], 6),
                               "index_vs_arc_max_dev": round(dev, 4),
                               "wrap": "ds=((s2-s1+0.5) mod 1)-0.5"}
    json.dump(h, open(HOPF, "w"), ensure_ascii=False)
    print(json.dumps(out["summary"], ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
