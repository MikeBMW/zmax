# -*- coding: utf-8 -*-
"""点2 逐帧内部量 dump: 键行带/裁列/v26b 平场切分/合并/认领/输出。
用法: python pt2_dump.py <mod> <seq> [frame_idx]"""
import sys, os, glob, json
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _loader

MOD = {"v25": "/home/ubuntu/zmax/zmax_data/aoi_v4/cam_finger_10082_work_v25.py",
       "v26": "/home/ubuntu/zmax/tools/aoi/_wip/cam_finger_10082_work_v26.py"}

KEYS = ["n_keys", "key_row_span", "kept_rows", "strip_cols", "strip_x",
        "v26b", "v26b_pitch", "v26b_old_reg", "v26b_reg", "v26b_n", "v26b_tooth_w",
        "v26b_note", "v26b_thr", "v26b_rows", "raw_segs", "merged_segs", "n_merged",
        "width_median_detected_px", "widths_detected", "pitch_median_px",
        "outlier_flags", "outlier_dropped", "kept_segs",
        "lattice_pitch_px", "lattice_phase_px", "lattice_added_vs_kept", "lattice_note",
        "v24_claims_span", "v24_rejected_edge_segs", "v25_vote", "centers", "rects",
        "width_uniform_px", "err", "why"]

def main():
    mod = sys.argv[1] if len(sys.argv) > 1 else "v26"
    seqarg = sys.argv[2] if len(sys.argv) > 2 else "/home/ubuntu/.hermes/cache/scratch/pt2_frames"
    M = _loader.load(MOD.get(mod, mod), "m_%s" % mod)
    paths = sorted(glob.glob(os.path.join(seqarg, "*.png")))
    for p in paths:
        bgr = cv2.imread(p, cv2.IMREAD_COLOR)
        img, met = M.render_judge(bgr)
        j = met.get("judge") or met
        print("== %s ==" % os.path.basename(p))
        for k in KEYS:
            if k in j:
                v = j[k]
                s = json.dumps(v, ensure_ascii=False)
                print("   %-22s %s" % (k, s[:300]))

main()
