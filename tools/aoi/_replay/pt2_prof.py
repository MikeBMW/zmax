# -*- coding: utf-8 -*-
"""复刻 _v26_teeth_cols 的内部决策, 打印每帧: 平场剖面峰(原始/合并后/栅格后)、
节距 m、相位、齿宽 w_tooth、center 序列 —— 用来定位"哪一根/哪一步在翻"。
用法: python pt2_prof.py <seq_dir> [band_y0 band_y1 x0 x1]"""
import sys, os, glob, json
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _loader

SRC = "/home/ubuntu/zmax/tools/aoi/_wip/cam_finger_10082_work_v26.py"

def main():
    seq = sys.argv[1] if len(sys.argv) > 1 else "/home/ubuntu/.hermes/cache/scratch/aoi_frozen"
    M = _loader.load(SRC, "mprof")
    paths = sorted(glob.glob(os.path.join(seq, "*.png")))
    if not paths:
        paths = sorted(glob.glob(os.path.join(seq, "*.jpg")))
    for p in paths:
        bgr = cv2.imread(p, cv2.IMREAD_COLOR)
        # 走一遍真实渲染拿带/裁窗
        img, met = M.render_judge(bgr)
        j = met.get("judge") or met
        ky0, ky1 = j["key_row_span"]; cx0, cx1 = j["strip_x"]
        g = M._v21_luma(bgr)
        ga = M._v25_norm_luma(g)
        y0, y1 = int(ky0), int(ky1)
        x0, x1 = int(cx0), int(cx1)
        nrm, nkept = M._v26_flat_profile(ga, y0, y1, x0, x1)
        W = len(nrm)
        xa = int(0.15 * W); xb = int(0.85 * W); c0 = int(0.25 * W); c1 = int(0.75 * W)
        base = float(np.median(nrm[c0:c1])); hi = float(np.percentile(nrm[c0:c1], 90))
        thr = base + M._V26_FF_THR_COEF * max(hi - base, 1e-3)
        on = nrm >= thr
        idx = np.where(on)[0]
        runs = []
        if idx.size:
            s = p0 = idx[0]
            for v in idx[1:]:
                if v == p0 + 1: p0 = v
                else: runs.append((int(s), int(p0))); s = p0 = v
            runs.append((int(s), int(p0)))
        peaks = [int(a + int(np.argmax(nrm[a:b + 1]))) for a, b in runs]
        peaks_in = [q for q in peaks if xa < q < xb]
        peaks_in.sort()
        merged = []
        for q in peaks_in:
            if merged and q - merged[-1] < M._V26_FF_MERGE:
                if nrm[q] > nrm[merged[-1]]: merged[-1] = q
            else: merged.append(q)
        d = np.diff(merged); m = float(np.median(d)) if d.size else 0.0
        lat = M._v26_lattice(merged, m) if m > 0 else merged
        dl = np.diff(lat); reg = float(np.mean((dl >= 0.6 * m) & (dl <= 1.5 * m))) if dl.size else 0.0
        runs_w = [b - a + 1 for a, b in runs if (b - a + 1) >= 3]
        wt = int(round(min(max(float(np.median(runs_w)) if runs_w else 0.5 * m, 0.30 * m), 0.66 * m))) if m > 0 else 0
        print("== %s ==  band_y=%d..%d x=%d..%d nkept=%d thr=%.4f" % (
            os.path.basename(p), y0, y1, x0, x1, nkept, thr))
        print("   原始runs=%d 峰(带内)=%d merged=%d  m=%.1f lat=%d reg=%.2f w_tooth=%d" % (
            len(runs), len(peaks_in), len(merged), m, len(lat), reg, wt))
        print("   merged peaks:", merged)
        print("   merged diffs:", [int(x) for x in d])
        print("   lattice     :", [int(x) for x in lat])
        print("   lat diffs   :", [int(x) for x in dl])
        # 左端 3 个 + 右端 3 个的剖面值
        q = merged
        if q:
            print("   左3峰 nrm:", [round(float(nrm[max(0,x-1):x+2].max()),3) for x in q[:3]],
                  " 右3峰 nrm:", [round(float(nrm[max(0,x-1):x+2].max()),3) for x in q[-3:]])
            print("   左3 runs  :", runs[:3], " 右3 runs:", runs[-3:])

main()
