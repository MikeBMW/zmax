#!/usr/bin/env python3
"""v22 离线验收(在工控机同款数值栈下跑):
 ① 零回退: v21 成功的帧, v22 输出**逐位一致** (md5) 且走第 1 遍(不多跑)
 ② 失败救回: 注入"多一个过曝窗把合并带撑开"的失败(现场故障的成因), v21 失败 → v22 必须救回并过验收闸
 ③ 失败绝不端错图: 有上一张好图 ⇒ 端那张(900x332)+红条, 不再是 960x960 旧口径
 ④ 有界取证: 失败时只落 2 个固定文件, 重复失败不增长
 ⑤ 模型输入未变: crop_goldfinger_regular / warp_goldfinger_topview 源码与 v21 逐字一致
用法: <python> verify_v22.py
"""
import os, sys, glob, types, importlib.util, hashlib, json, time
import numpy as np

HERE = "/home/ubuntu/zmax/zmax_data/aoi_v4"
S = "/home/ubuntu/.hermes/cache/scratch"
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "_stub"))   # 工控机才有的 SciCam SDK: 仓库自带 stub
os.environ.setdefault("TEMP", os.path.join(S, "_rend_tmp"))
os.makedirs(os.environ["TEMP"], exist_ok=True)
import cv2

yd = types.ModuleType("yolo_detector")
class _YD:
    def __init__(s, *a, **k): pass
    def detect(s, *a, **k): return {"detections": [], "saved_incoming": None}
yd.YoloDetector = _YD
sys.modules["yolo_detector"] = yd



def load(name, path):
    sp = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(sp)
    sys.modules[name] = m
    sp.loader.exec_module(m)
    return m


V21 = load("aoiv21", os.path.join(HERE, "cam_finger_10082_work_v21.py"))
V22 = load("aoiv22", os.path.join(HERE, "cam_finger_10082_work_v22.py"))
print("env py%s cv2 %s np %s" % (sys.version.split()[0], cv2.__version__, np.__version__))
print("ver21=%s  ver22=%s" % (getattr(V21, "_V21_VER", "(none)"), getattr(V22, "_V22_VER", "(none)")))

files = []
for pat in (S + "/frames/*.png", S + "/burst/*.png", S + "/failframes/*.png",
            S + "/live_grab_origin.png", S + "/judge_live_origin.png"):
    files += sorted(glob.glob(pat))
print("候选帧 %d" % len(files))
fails = []


def md5(a):
    return hashlib.md5(np.ascontiguousarray(a).tobytes()).hexdigest()


# ---------------- ① 零回退 ----------------
n_ok = n_mismatch = n_fail21 = n_fail22 = 0
mismatch = []
for f in files:
    im = cv2.imread(f)
    if im is None:
        continue
    o1, m1 = V21.render_judge(im, deskew_deg=0.0)
    o2, m2 = V22.render_judge(im, deskew_deg=0.0)
    if o1 is None:
        n_fail21 += 1
        if o2 is None:
            n_fail22 += 1
            fails.append((os.path.basename(f), "both-fail", m1.get("why"), m2.get("why")))
        continue
    n_ok += 1
    same = (o2 is not None) and md5(o1) == md5(o2)
    same_meta = all(m1.get(k) == m2.get(k) for k in ("n_keys", "out", "kept_rows", "sat_before", "fix_hw"))
    fast = int(m2.get("attempt") or 0) == 1
    if not (same and same_meta and fast):
        n_mismatch += 1
        mismatch.append((os.path.basename(f), md5(o1)[:8], (md5(o2)[:8] if o2 is not None else "None"),
                         same_meta, fast, m2.get("attempt"), m2.get("attempts_note")))
print("\n① 零回退: v21成功帧 %d | v22 逐位一致且走第1遍 %d | 不一致 %d | v21失败 %d(v22也失败 %d)"
      % (n_ok, n_ok - n_mismatch, n_mismatch, n_fail21, n_fail22))
for r in mismatch[:6]:
    print("   ✗", r)

# ---------------- ② 失败救回(注入过曝窗) ----------------
TESTF = None
for cand in (S + "/live_grab_origin.png", S + "/judge_live_origin.png") + tuple(sorted(glob.glob(S + "/burst/*.png"))):
    if os.path.exists(cand):
        TESTF = cand
        break
frame = cv2.imread(TESTF)
real_hits = V22._v21_key_windows(V22._v21_luma(frame), V22._V21_BRIGHT_LEVEL)
extra = None
for y in range(760, 1010, 10):          # 白色外壳所在行(过曝区): 找一个"真能过窗测试"的窗
    lvl = V22._V21_BRIGHT_LEVEL
    cf = (V22._v21_luma(frame)[y:y + V22._V21_WIN_H, :] >= lvl).mean(axis=0)
    segs = V22._v21_segments(cf >= V22._V21_CF_BRIGHT_COL, V22._V21_COL_MERGE_GAP, V22._V21_MIN_SEG_W)
    med, mad = V22._v21_pitch_stats(segs)
    if len(segs) >= V22._V21_MIN_KEYS and med is not None and V22._V21_PITCH_MIN <= med <= V22._V21_PITCH_MAX \
            and mad < V22._V21_PITCH_JITTER_K * med:
        extra = {"y0": int(y), "y1": int(y + V22._V21_WIN_H - 1), "n_seg": int(len(segs)),
                 "pitch_px": round(med, 1), "jitter_px": round(mad, 1), "synthetic": False}
        break
if extra is None:                        # 兜底: 手工造一个"过曝区里的窗"
    extra = {"y0": 800, "y1": 849, "n_seg": 9, "pitch_px": 62.0, "jitter_px": 3.0, "synthetic": True}
print("\n② 注入过曝窗: %s  real_hits=%d  注入=%s (synthetic=%s)"
      % (os.path.basename(TESTF), len(real_hits), (extra["y0"], extra["y1"]), extra["synthetic"]))


def patched(hits_list):
    def f(g, lvl):
        return list(hits_list) + [extra]
    return f


V21._v21_key_windows = patched(real_hits)
V22._v21_key_windows = patched(real_hits)
o1b, m1b = V21.render_judge(frame, deskew_deg=0.0)
o2b, m2b = V22.render_judge(frame, deskew_deg=0.0)
print("   v21: %s  why=%s  合并带=%s sat_before=%s"
      % ("失败(现场现象)" if o1b is None else "居然成功了(注入有效性待查)", m1b.get("why"),
         m1b.get("key_row_span"), m1b.get("sat_before")))
print("   v22: %s  attempt=%s  band_used=%s gate=%s n_keys=%s sat_before=%s black=%s"
      % ("救回 ✓" if o2b is not None else "仍失败 ✗", m2b.get("attempt"), m2b.get("band_used"),
         m2b.get("gate_used"), m2b.get("n_keys"), m2b.get("sat_before"), m2b.get("black_frac")))
print("   v22 说明: %s" % m2b.get("attempts_note"))
if o2b is not None:
    cv2.imwrite(os.path.join(S, "v22_recovered_judge.png"), o2b)
V21._v21_key_windows = V21.__dict__["_v21_key_windows"]
V22._v21_key_windows = V22.__dict__["_v21_key_windows"]

# ---------------- ③ 失败绝不端错图 ----------------
fake960 = cv2.resize(frame, (960, 960), interpolation=cv2.INTER_LINEAR)
t = types.SimpleNamespace()
V22._LAST_GOOD_JUDGE["img"] = None
imgA, stA = V22._v22_judge_fail_view(fake960, {"err": "too few keys after detection (1)"}, 375)
V22._v22_remember_good(cv2.imread(S + "/v22_recovered_judge.png") if os.path.exists(S + "/v22_recovered_judge.png")
                       else cv2.resize(fake960, (900, 332)), 374)
imgB, stB = V22._v22_judge_fail_view(fake960, {"err": "too few keys after detection (1)"}, 375)
print("\n③ 失败时的画面: 无好图→ state=%s shape=%s(应=960方图) | 有好图→ state=%s shape=%s(应=900x332, 不是960)"
      % (stA, imgA.shape, stB, imgB.shape))
print("   红条存在: A=%s B=%s" % (tuple(imgA[3, 5].tolist()), tuple(imgB[3, 5].tolist())))
cv2.imwrite(os.path.join(S, "v22_failview_lastgood.png"), imgB)
cv2.imwrite(os.path.join(S, "v22_failview_nogood.png"), imgA)

# ---------------- ④ 有界取证 ----------------
V22.SAVE_ROOT_DIR = os.path.join(S, "_dbg")
os.makedirs(V22.SAVE_ROOT_DIR, exist_ok=True)
for _ in range(3):
    V22._v22_dump_fail(frame, {"err": "too few keys after detection (1)", "_hits": real_hits,
                               "why": "too few keys after detection (1)", "src_size": [frame.shape[1], frame.shape[0]]}, 375)
dbg = sorted(os.listdir(V22.SAVE_ROOT_DIR))
ok_png = md5(cv2.imread(os.path.join(V22.SAVE_ROOT_DIR, V22._V22_DBG_PNG))) == md5(frame)
rec = json.load(open(os.path.join(V22.SAVE_ROOT_DIR, V22._V22_DBG_JSON), encoding="utf-8"))
print("\n④ 取证: 连跑 3 次后目录=%s (应 2 个文件) 输入帧一致=%s json.hits=%d ver=%s"
      % (dbg, ok_png, len(rec.get("hits") or []), rec.get("ver")))

# ---------------- ⑤ 模型输入未变 ----------------
import re
def src_of(mod, fn):
    s = open(mod.__file__, encoding="utf-8").read()
    i = s.index("def %s(" % fn)
    j = s.find("\ndef ", i + 10)
    return s[i:j if j > 0 else len(s)]
for fn in ("crop_goldfinger_regular", "warp_goldfinger_topview"):
    same = hashlib.md5(src_of(V21, fn).encode()).hexdigest() == hashlib.md5(src_of(V22, fn).encode()).hexdigest()
    print("⑤ %s 源码逐字一致=%s" % (fn, same))
print("\n结论: ①不一致=%d  ②%s  ③%s  ④%s" % (
    n_mismatch,
    "救回" if o2b is not None else "未救回",
    "端上一张好图" if (stB == "stale_lastgood" and imgB.shape[:2] == (332, 900)) else "异常",
    "2 文件有界" if len(dbg) == 2 and ok_png else "异常"))
