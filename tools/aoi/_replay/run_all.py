# -*- coding: utf-8 -*-
"""对指定模块文件, 逐序列复放并报 constancy。每个序列独立子进程(lock 不跨序列污染)。"""
import sys, os, glob, subprocess

PY = "/home/ubuntu/zmax/venvs/lerobot-venv/bin/python"
REPLAY = "/home/ubuntu/zmax/tools/aoi/_replay/pt2_replay.py"
MOD = sys.argv[1]

SEQS = {
    "pt2_frames": "/home/ubuntu/.hermes/cache/scratch/pt2_frames",
    "aoi_frozen": "/home/ubuntu/.hermes/cache/scratch/aoi_frozen",
    "aoi_frozen2": "/home/ubuntu/.hermes/cache/scratch/aoi_frozen2",
    "aoi_frozen3": "/home/ubuntu/.hermes/cache/scratch/aoi_frozen3",
    "aoi_frozen4": "/home/ubuntu/.hermes/cache/scratch/aoi_frozen4",
}
print("MOD =", MOD)
for name, seq in SEQS.items():
    out = subprocess.run([PY, REPLAY, MOD, seq, "2"], capture_output=True, text=True,
                         env=dict(os.environ)).stdout
    tail = [l for l in out.splitlines() if l.startswith("STEADY") or l.startswith("CONST")]
    print("### %s" % name)
    for l in tail:
        print("   ", l)
