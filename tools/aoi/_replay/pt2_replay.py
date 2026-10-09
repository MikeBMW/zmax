# -*- coding: utf-8 -*-
"""点2 基线复现 + 逐帧表。每视角独立进程: 只复放一个序列, 干净。
用法: python pt2_replay.py <mod> <seq_dir_glob> [rounds]
  mod: v25 | v26 | <abs path>
  seq: 目录(里面 *.png) 或 glob
输出: 每帧 n_keys / 宽度列表 / pitch / lattice_pitch, 并打印统计。"""
import sys, os, glob, json
import numpy as np, cv2
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _loader

MOD = {"v25": "/home/ubuntu/zmax/zmax_data/aoi_v4/cam_finger_10082_work_v25.py",
       "v26": "/home/ubuntu/zmax/tools/aoi/_wip/cam_finger_10082_work_v26.py"}

def main():
    mod = sys.argv[1] if len(sys.argv) > 1 else "v26"
    seqarg = sys.argv[2] if len(sys.argv) > 2 else "/home/ubuntu/.hermes/cache/scratch/pt2_frames"
    rounds = int(sys.argv[3]) if len(sys.argv) > 3 else 2
    path = MOD.get(mod, mod)
    M = _loader.load(path, os.path.basename(path))
    paths = sorted(glob.glob(os.path.join(seqarg, "*.png"))) if os.path.isdir(seqarg) else sorted(glob.glob(seqarg))
    if not paths:
        paths = sorted(glob.glob(os.path.join(seqarg, "*.jpg"))) if os.path.isdir(seqarg) else sorted(glob.glob(seqarg))
    frames = [(os.path.basename(p), cv2.imread(p, cv2.IMREAD_COLOR)) for p in paths]
    print("mod=%s frames=%d rounds=%d" % (mod, len(frames), rounds))
    rows = []
    for rep in range(rounds):
        for name, bgr in frames:
            img, met = M.render_judge(bgr)
            j = met.get("judge") or met
            rects = [(int(a), int(b)) for a, b in (j.get("rects") or [])]
            ws = [b - a + 1 for a, b in rects]
            cen = sorted((a + b) / 2.0 for a, b in rects)
            dd = np.diff(cen) if len(cen) > 1 else np.array([])
            pitch = float(np.median(dd)) if dd.size else 0.0
            ok = img is not None
            rows.append(dict(rep=rep, frame=name, ok=bool(ok),
                             n_keys=j.get("n_keys"), widths=ws, wset=sorted(set(ws)),
                             pitch=round(pitch, 1), lat_pitch=j.get("lattice_pitch_px"),
                             lat_note=j.get("lattice_note"), err=j.get("err"),
                             v26b=j.get("v26b"), v26b_pitch=j.get("v26b_pitch"),
                             attempt=j.get("attempt"), old_reg=j.get("v26b_old_reg")))
    for r in rows:
        print("r%d %-10s ok=%-5s n=%-3s wset=%-16s pitch=%-7s lat_pitch=%-6s v26b=%s v26b_p=%s old_reg=%s err=%s" % (
            r["rep"], r["frame"], r["ok"], r["n_keys"], str(r["wset"])[:16], r["pitch"],
            r["lat_pitch"], r["v26b"], r["v26b_pitch"], r["old_reg"], r["err"]))
    # 稳态(去掉预热第1轮)
    steady = rows[len(frames):] if rounds > 1 else rows
    ns = [r["n_keys"] for r in steady]
    wsets = [tuple(r["wset"]) for r in steady]
    print("STEADY n_keys:", ns)
    print("STEADY width-sets:", wsets)
    print("CONST n_keys=%s width=%s" % (len(set(ns)) == 1, len(set(wsets)) == 1))
    json.dump(rows, open("/tmp/pt2_rows_%s.json" % mod.replace("/", "_"), "w"), ensure_ascii=False)

main()
