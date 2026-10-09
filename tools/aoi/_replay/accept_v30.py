# -*- coding: utf-8 -*-
"""v30 验收证据台: a) 16帧逐帧表  b) 前视逐位(np.array_equal)  c) 层①原始帧均值恒定 d) extra/missing e) sha/wc
每个 (模块,视角) 在**独立子进程**里复放。
"""
import subprocess, sys, os, json, hashlib, glob
import numpy as np, cv2

P = "/home/ubuntu/.hermes/cache/scratch/aoi310/bin/python"
REP = "/home/ubuntu/zmax/tools/aoi/_replay"
C = "/home/ubuntu/.hermes/cache/scratch"
V27 = "/home/ubuntu/zmax/tools/aoi/cam_finger_10082_work_v27.py"          # 在役基线(=IPC v20, judge v28)
V30 = "/home/ubuntu/zmax/zmax_data/aoi_v4/cam_finger_10082_work_v30.py"   # 候选
SEQ = C + "/aoi_l3_frames"
FRONT = C + "/liveF*.png"


def run(args):
    r = subprocess.run([P] + args, capture_output=True, text=True)
    return r.stdout + r.stderr


def seq_table(mod, frames):
    """在自己的子进程里复放一个模块, 返回每帧 (n, width, pitch, band, centers)."""
    code = r'''
import sys, glob, json
sys.path.insert(0, "%s")
import _loader, numpy as np, cv2
M=_loader.load("%s","seqx")
out=[]
for p in sorted(glob.glob("%s/*.png")):
    bgr=cv2.imread(p,cv2.IMREAD_COLOR)
    img,met=M.render_judge(bgr,deskew_deg=0.0)
    j=met.get("judge") or met
    cen=[(int(a)+int(b))/2 for a,b in (j.get("rects") or [])]
    out.append(dict(f=__import__("os").path.basename(p)[:-4], n=j.get("n_keys"),
        w=j.get("width_uniform_px"), pitch=round(float(np.median(np.diff(cen))),1) if len(cen)>1 else None,
        band=j.get("key_row_span"), cl=j.get("v24_claims_span"),
        split=j.get("v30_split_blocks"), first=round(cen[0]) if cen else None,
        last=round(cen[-1]) if cen else None))
print(json.dumps(out))
''' % (REP, mod, frames)
    txt = run(["-c", code])
    line = [l for l in txt.splitlines() if l.strip().startswith("[")][-1]
    return json.loads(line)


print("=" * 78)
print("v30 验收证据台  (基线=%s)" % os.path.basename(V27))
print("=" * 78)

# ---------- a) 16 帧逐帧表 ----------
tb = seq_table(V27, SEQ)
tv = seq_table(V30, SEQ)
print("\n[a] 16 帧冻结序列逐帧表 (独立进程复放, render_judge, deskew=0)")
print("%-5s | %-26s | %-40s" % ("frame", "基线 v27 (n/band/mode)", "候选 v30 (n/width/pitch/band/center)"))
for x, y in zip(tb, tv):
    print("%-5s | n=%-3s %-14s | n=%-3s w=%-3s p=%-5s band=%-13s c=%s..%s" % (
        x["f"], x["n"], str(x["band"]),
        y["n"], y["w"], y["pitch"], str(y["band"]), y["first"], y["last"]))
print("v27 n_keys seq =", [x["n"] for x in tb])
print("v30 n_keys seq =", [x["n"] for x in tv])

# ---------- b) 前视逐位 ----------
os.system("rm -rf /tmp/acc_base /tmp/acc_v30")
run([REP + "/dump_render.py", V27, FRONT, "/tmp/acc_base"])
run([REP + "/dump_render.py", V30, FRONT, "/tmp/acc_v30"])
ib = json.load(open("/tmp/acc_base/_index.json"))
iv = json.load(open("/tmp/acc_v30/_index.json"))
print("\n[b] 前视零回退 (liveF0-7, 每模块独立进程渲染 + np.array_equal)")
allok = True
for x, y in zip(ib, iv):
    a = cv2.imread("/tmp/acc_base/%s.png" % x["frame"])
    b = cv2.imread("/tmp/acc_v30/%s.png" % y["frame"])
    eq = bool(np.array_equal(a, b))
    allok &= eq
    print("   %-8s base_n=%-3s v30_n=%-3s np.array_equal=%s" % (x["frame"], x["n"], y["n"], eq))
print("   → 前视逐位相同: %s (8/8)" % allok)

# ---------- c) 层① 原始帧均值恒定 ----------
print("\n[c] 层① 相机未复发自动曝光: 16 帧原始图统计 (kind=origin 冻结帧)")
ms = []
for p in sorted(glob.glob(SEQ + "/*.png")):
    g = cv2.imread(p, 0).astype(np.float32)
    ms.append((os.path.basename(p)[:-4], float(g.mean()), float(np.median(g)), float((g >= 250).mean())))
print("   mean  : %.1f ~ %.1f (极差 %.1f%%)" % (min(m[1] for m in ms), max(m[1] for m in ms),
      100 * (max(m[1] for m in ms) - min(m[1] for m in ms)) / np.mean([m[1] for m in ms])))
print("   p50   : %d ~ %d" % (min(m[2] for m in ms), max(m[2] for m in ms)))
print("   sat≥250: %.3f ~ %.3f" % (min(m[3] for m in ms), max(m[3] for m in ms)))

# ---------- d) extra/missing ----------
print("\n[d] extra/missing (真值 = 槽 0..18) 相对基线 v27")
print("   %-5s %-24s %-24s" % ("frame", "v27 (extra/missing)", "v30 (extra/missing)"))


def em(cl):
    if not cl:
        return "no-span"
    s = set(range(int(cl[0]), int(cl[1]) + 1)); t = set(range(0, 19))
    return "extra=%s miss=%s" % (sorted(s - t), sorted(t - s))


for x, y in zip(tb, tv):
    print("   %-5s %-24s %-24s" % (x["f"], em(x["cl"]), em(y["cl"])))

# ---------- e) sha / wc ----------
print("\n[e] 新文件")
for p in (V30, "/home/ubuntu/zmax/tools/aoi/_wip/cam_finger_10082_work_v30.py"):
    h = hashlib.sha256(open(p, "rb").read()).hexdigest()
    n = sum(1 for _ in open(p, "rb"))
    print("   %s" % p)
    print("      sha256=%s  lines=%d  bytes=%d" % (h, n, os.path.getsize(p)))
