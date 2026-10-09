# -*- coding: utf-8 -*-
"""Cross-process pixel compare: two modules over a set of sequences, np.array_equal per frame.
Each (module,view) rendered in its own subprocess (per-view independent process, red line)."""
import subprocess, os, sys, glob, tempfile
import numpy as np

PY = "/home/ubuntu/.hermes/cache/scratch/aoi310/bin/python"
R = "/home/ubuntu/zmax/tools/aoi/_replay"
S = "/home/ubuntu/.hermes/cache/scratch"
MOD_A, MOD_B = sys.argv[1], sys.argv[2]
gated = "--gated" in sys.argv
SEQS = [("l3", S + "/aoi_l3_frames"), ("pt2", S + "/pt2_frames/*.png"),
        ("frozen", S + "/aoi_frozen"), ("frozen2", S + "/aoi_frozen2"),
        ("frozen3", S + "/aoi_frozen3"), ("frozen4", S + "/aoi_frozen4"),
        ("liveF", S + "/liveF[0-9].png"), ("live18", S + "/aoi_live_frames")]
tmp = tempfile.mkdtemp(prefix="v34cmp_")
allok = True
for name, seq in SEQS:
    fa, fb = os.path.join(tmp, name + "_A.npy"), os.path.join(tmp, name + "_B.npy")
    extra = ["--gated"] if gated else []
    subprocess.run([PY, R + "/_v34_dump_npy.py", MOD_A, seq, fa] + extra, check=True,
                   stdout=subprocess.DEVNULL)
    subprocess.run([PY, R + "/_v34_dump_npy.py", MOD_B, seq, fb] + extra, check=True,
                   stdout=subprocess.DEVNULL)
    A = np.load(fa, allow_pickle=True); B = np.load(fb, allow_pickle=True)
    assert len(A) == len(B)
    eq = [bool(np.array_equal(a, b)) for a, b in zip(A, B)]
    n_eq = sum(eq)
    tag = "OK" if n_eq == len(eq) else "DIFF"
    if name != "live18":
        allok = allok and (n_eq == len(eq))
    print("%-9s np.array_equal %d/%d  %s   diff_frames=%s" % (
        name, n_eq, len(eq), tag, [i for i, e in enumerate(eq) if not e]))
print("ALL_REFERENCES_EQUAL:", allok)
