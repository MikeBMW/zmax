# -*- coding: utf-8 -*-
"""原型: 用自相关估节距 + 栅格相位拟合来定齿列, 看能否逐帧恒定。只在剖面层验证, 先不改模块。"""
import sys, os, glob
import numpy as np, cv2
sys.path.insert(0, "/home/ubuntu/zmax/tools/aoi/_replay")
import _loader
M = _loader.load("/home/ubuntu/zmax/tools/aoi/_wip/cam_finger_10082_work_v26.py", "mproto")


def prof_of(bgr):
    im, met = M.render_judge(bgr); j = met.get("judge") or met
    ky0, ky1 = j["key_row_span"]; x0, x1 = j["strip_x"]
    g = M._v21_luma(bgr); ga = M._v25_norm_luma(g)
    nrm, nk = M._v26_flat_profile(ga, int(ky0), int(ky1), int(x0), int(x1))
    return nrm, j


def acf_pitch(nrm, pmin=45, pmax=110):
    c = nrm - float(nrm.mean())
    acf = np.correlate(c, c, "full")[len(c) - 1:]
    if acf[0] <= 0: return None, None
    acf = acf / acf[0]
    lo, hi = int(pmin), int(pmax)
    seg = acf[lo:hi]
    m = lo + int(np.argmax(seg))
    return m, float(acf[m])


def lattice_slots(nrm, m, ph, w_frac=0.55):
    W = len(nrm)
    ks = np.arange(0, int((W - 1 - ph) / m) + 1)
    lvl = []
    for k in ks:
        c = ph + k * m
        a = int(round(c - w_frac * m / 2)); b = int(round(c + w_frac * m / 2))
        a = max(0, a); b = min(W, b)
        lvl.append(float(nrm[a:b].mean()) if b > a else 0.0)
    return ks.astype(int), np.array(lvl)


def best_phase(nrm, m):
    W = len(nrm)
    best = (-1.0, 0.0)
    for ph in np.arange(0.0, m, 0.5):
        ks, lvl = lattice_slots(nrm, m, ph)
        # 用"槽亮度相对本帧中位的对比"打分, 只看中段避免边缘
        n = len(lvl)
        if n < 8: continue
        s = float(np.median(lvl) + (np.percentile(lvl, 80) - np.percentile(lvl, 20)))
        if s > best[0]: best = (s, ph)
    return best[1]


def main():
    for seqname, seq in [("pt2_frames", "/home/ubuntu/.hermes/cache/scratch/pt2_frames"),
                          ("aoi_frozen", "/home/ubuntu/.hermes/cache/scratch/aoi_frozen")]:
        print("===== %s =====" % seqname)
        paths = sorted(glob.glob(os.path.join(seq, "*.png")))
        for p in paths:
            bgr = cv2.imread(p)
            nrm, j = prof_of(bgr)
            m, strength = acf_pitch(nrm)
            ph = best_phase(nrm, m)
            ks, lvl = lattice_slots(nrm, m, ph)
            med = float(np.median(lvl)); p90 = float(np.percentile(lvl, 90)); p10 = float(np.percentile(lvl, 10))
            thr = med + 0.35 * (p90 - p10)
            on = lvl > thr
            # 最长连续 run
            best = (0, 0); i = 0
            while i < len(on):
                if on[i]:
                    j2 = i
                    while j2 + 1 < len(on) and on[j2 + 1]: j2 += 1
                    if (j2 - i) > (best[1] - best[0]): best = (i, j2)
                    i = j2 + 1
                else: i += 1
            nt = best[1] - best[0] + 1 if best[1] >= best[0] and on.any() else 0
            print("  %-10s m=%d acf=%.2f ph=%.1f slots=%d thr=%.3f med=%.3f p90=%.3f n_tooth=%d span=[%d,%d]" % (
                os.path.basename(p), m, strength or 0, ph, len(lvl), thr, med, p90, nt, best[0], best[1]))

main()
