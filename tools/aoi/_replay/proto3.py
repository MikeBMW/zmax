# -*- coding: utf-8 -*-
"""原型 v3: 稳健 pitch/phase (取自最长规则链) + 用全体合并峰定跨度, 栅格补齐。"""
import sys, os, glob
import numpy as np, cv2
sys.path.insert(0, "/home/ubuntu/zmax/tools/aoi/_replay")
import _loader
M = _loader.load("/home/ubuntu/zmax/tools/aoi/_wip/cam_finger_10082_work_v26.py", "mp3")
PMIN, PMAX, THR_COEF, EAR, QW = 45.0, 110.0, 0.12, 0.55, 2


def est(bgr):
    im, met = M.render_judge(bgr); j = met.get("judge") or met
    ky0, ky1 = j["key_row_span"]; x0, x1 = j["strip_x"]
    ga = M._v25_norm_luma(M._v21_luma(bgr))
    nrm, _ = M._v26_flat_profile(ga, int(ky0), int(ky1), int(x0), int(x1))
    W = len(nrm); xa, xb = int(0.15 * W), int(0.85 * W); c0, c1 = int(0.25 * W), int(0.75 * W)
    base = float(np.median(nrm[c0:c1])); hi = float(np.percentile(nrm[c0:c1], 90))
    thr = base + THR_COEF * max(hi - base, 1e-3)
    idx = np.where(nrm >= thr)[0]
    runs = []
    if idx.size:
        s = p0 = idx[0]
        for v in idx[1:]:
            if v == p0 + 1: p0 = v
            else: runs.append((int(s), int(p0))); s = p0 = v
        runs.append((int(s), int(p0)))
    peaks = sorted(int(a + int(np.argmax(nrm[a:b + 1]))) for a, b in runs)
    peaks = [p for p in peaks if xa < p < xb]
    if len(peaks) < 5: return None
    d = np.diff(peaks).astype(float); d = d[(d >= PMIN) & (d <= PMAX)]
    if d.size < 3: return None
    m = float(np.median(d))
    for _ in range(5):
        core = d[(d >= 0.75 * m) & (d <= 1.30 * m)]
        if core.size < 3: break
        nm = float(np.median(core))
        if abs(nm - m) < 0.05: m = nm; break
        m = nm
    m0 = m
    merged = []
    for p in peaks:
        if merged and p - merged[-1] < EAR * m0:
            if nrm[p] > nrm[merged[-1]]: merged[-1] = p
        else: merged.append(p)
    peaks = merged
    if len(peaks) < 5: return None
    # 最长规则链 -> 稳定节距
    best = (0, 0); i = 0
    while i < len(peaks):
        jj = i
        while jj + 1 < len(peaks) and 0.72 * m0 <= peaks[jj + 1] - peaks[jj] <= 1.28 * m0:
            jj += 1
        if (jj - i) > (best[1] - best[0]): best = (i, jj)
        i = (jj + 1) if jj > i else i + 1
    run = peaks[best[0]:best[1] + 1]
    if len(run) < 5: return None
    mf = (run[-1] - run[0]) / float(len(run) - 1)     # 长基线浮点节距
    # 相位: 以链首为锚, 全体峰残差中位
    pk0 = float(run[0]); ph = float(np.median([p - round((p - pk0) / mf) * mf for p in peaks]))
    # 跨度: 全体合并峰的首/末
    lo, hi2 = peaks[0], peaks[-1]
    n = int(round((hi2 - ph) / mf)) - int(round((lo - ph) / mf)) + 1
    wr = [b - a + 1 for a, b in runs if lo - 0.6 * mf <= a and b <= hi2 + 0.6 * mf and (b - a + 1) >= 3]
    wmed = float(np.median(wr)) if wr else 0.5 * mf
    wt = int(round(wmed / QW)) * QW
    wt = int(min(max(wt, 0.30 * mf), 0.66 * mf))
    return dict(mf=round(mf, 2), n=n, w=wt, span=[int(lo), int(hi2)], nmerge=len(peaks))


def main():
    for name, seq in [("pt2_frames", "/home/ubuntu/.hermes/cache/scratch/pt2_frames"),
                      ("aoi_frozen", "/home/ubuntu/.hermes/cache/scratch/aoi_frozen"),
                      ("aoi_frozen2", "/home/ubuntu/.hermes/cache/scratch/aoi_frozen2"),
                      ("aoi_frozen3", "/home/ubuntu/.hermes/cache/scratch/aoi_frozen3"),
                      ("aoi_frozen4", "/home/ubuntu/.hermes/cache/scratch/aoi_frozen4")]:
        print("===== %s =====" % name)
        paths = sorted(glob.glob(os.path.join(seq, "*.png"))) or sorted(glob.glob(os.path.join(seq, "*.jpg")))
        ns, ws, ms = [], [], []
        for p in paths:
            r = est(cv2.imread(p))
            if r is None: print("  %-12s FAIL" % os.path.basename(p)); continue
            ns.append(r["n"]); ws.append(r["w"]); ms.append(r["mf"])
            print("  %-12s n=%-3d w=%-3d mf=%-6s span=%s nmerge=%d" % (
                os.path.basename(p), r["n"], r["w"], r["mf"], r["span"], r["nmerge"]))
        print("  CONST n=%s %s w=%s %s m=%s" % (len(set(ns)) == 1, ns, len(set(ws)) == 1, ws, len(set(ms)) == 1))


main()
