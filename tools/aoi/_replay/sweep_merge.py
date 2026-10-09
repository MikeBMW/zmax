# -*- coding: utf-8 -*-
"""参数扫描: 只改模块级常量, 复放点2/前视序列, 看 n_keys/宽度/pitch 是否恒定。"""
import sys, os, glob, importlib
import numpy as np, cv2
sys.path.insert(0, "/home/ubuntu/zmax/tools/aoi/_replay")
import _loader

SRC = "/home/ubuntu/zmax/tools/aoi/_wip/cam_finger_10082_work_v26.py"

def run(M, seq, rounds=2):
    paths = sorted(glob.glob(os.path.join(seq, "*.png"))) or sorted(glob.glob(os.path.join(seq, "*.jpg")))
    fr = [cv2.imread(p, cv2.IMREAD_COLOR) for p in paths]
    rows = []
    for rep in range(rounds):
        for bgr in fr:
            img, met = M.render_judge(bgr); j = met.get("judge") or met
            rects = [(int(a), int(b)) for a, b in (j.get("rects") or [])]
            ws = [b - a + 1 for a, b in rects]
            cen = sorted((a + b) / 2.0 for a, b in rects)
            dd = np.diff(cen) if len(cen) > 1 else np.array([])
            rows.append((j.get("n_keys"), sorted(set(ws)),
                         round(float(np.median(dd)), 1) if dd.size else 0.0,
                         j.get("v26b_pitch"), img is not None))
    st = rows[len(fr):] if rounds > 1 else rows
    ns = [r[0] for r in st]; wss = [tuple(r[1]) for r in st]; ps = [r[2] for r in st]
    return dict(n=ns, wsets=wss, pitches=ps,
                const_n=len(set(ns)) == 1, const_w=len(set(wss)) == 1,
                const_p=len(set(ps)) == 1, all_ok=all(r[4] for r in st))

SEQS = {
    "pt2_frames": "/home/ubuntu/.hermes/cache/scratch/pt2_frames",
    "aoi_frozen": "/home/ubuntu/.hermes/cache/scratch/aoi_frozen",
    "aoi_frozen2": "/home/ubuntu/.hermes/cache/scratch/aoi_frozen2",
    "aoi_frozen3": "/home/ubuntu/.hermes/cache/scratch/aoi_frozen3",
    "aoi_frozen4": "/home/ubuntu/.hermes/cache/scratch/aoi_frozen4",
    "front_liveF": "/home/ubuntu/.hermes/cache/scratch/liveF_glob",
}

def main():
    merge_vals = [float(x) for x in (sys.argv[1:] or [40])]
    for mv in merge_vals:
        M = _loader.load(SRC, "msw_%s" % mv)
        M._V26_FF_MERGE = mv
        print("################ _V26_FF_MERGE = %g ################" % mv)
        for name, seq in SEQS.items():
            if name == "front_liveF":
                fr = [cv2.imread(p) for p in sorted(glob.glob("/home/ubuntu/.hermes/cache/scratch/liveF*.png"))]
                rows = []
                for rep in range(2):
                    for bgr in fr:
                        img, met = M.render_judge(bgr); j = met.get("judge") or met
                        rows.append((j.get("n_keys"), img))
                st = rows[len(fr):]
                print("  %-12s const_n=%s n=%s" % (name, len({r[0] for r in st}) == 1, [r[0] for r in st]))
                continue
            r = run(M, seq)
            print("  %-12s const_n=%-5s n=%-24s const_w=%-5s wsets=%s pitch=%s" % (
                name, r["const_n"], str(r["n"])[:24], r["const_w"], str(r["wsets"])[:40], r["pitches"]))

main()
