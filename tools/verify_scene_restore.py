#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""judge: restart-scene-restore (canvas src_state -> ZMAX_SCENE_DIR on import)"""
import os, subprocess, sys
ROOT = "/home/ubuntu/zmax"
P = "/home/ubuntu/.hermes/cache/scratch/scene_probe.py"
FAIL = []
def chk(c, m):
    print(("  OK  " if c else "  X   ") + m)
    if not c:
        FAIL.append(m)
def run(extra):
    env = {k: v for k, v in os.environ.items() if k != "ZMAX_SCENE_DIR"}
    env.update(extra)
    r = subprocess.run([ROOT + "/gui-venv311/bin/python", P], capture_output=True, text=True, env=env, cwd=ROOT)
    blob = r.stdout + r.stderr
    line = [l for l in blob.splitlines() if "SCENE=" in l]
    return (line[-1] if line else "(no output)"), blob
out, full = run({})
print("  clean-boot ->", out)
chk("SS-TRAY-PLACE" in out and "MODE=tray" in out, "1) restart: scene truth source restored from canvas -> tray (SS-TRAY-PLACE)")
chk("\\u573a\\u666f\\u771f\\u6e90\\u6309\\u753b\\u5e03\\u6570\\u636e\\u6e90\\u81ea\\u6062\\u590d" in full, "1) log names the source")
out2, _ = run({"ZMAX_SCENE_DIR": ROOT + "/data/scene/scenes/SS-EPI-CORNER"})
chk("SS-EPI-CORNER" in out2 and "MODE=plug" in out2, "2) explicit env wins (peg scene kept)")
print("")
print(("SCENE-RESTORE PASS" if not FAIL else "SCENE-RESTORE FAIL") + "  (%d failures)" % len(FAIL))
sys.exit(0 if not FAIL else 1)
