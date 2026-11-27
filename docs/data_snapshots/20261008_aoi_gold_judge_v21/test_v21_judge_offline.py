#!/usr/bin/env python3
"""test_v21_judge_offline.py -- offline proof for the v21 10082 deliverable.

Runs with the cv2 interpreter:
    cd /home/ubuntu/zmax/zmax_data/aoi_v4
    /home/ubuntu/zmax/gui-venv311/bin/python test_v21_judge_offline.py

PART A  source equality: crop_goldfinger_regular / GrabAndSaveImage / every route
        handler / _region_payload / get_cropper are AST-identical between v20 and v21.
PART B  runtime equality: on the same real frame, v20 and v21 crop_goldfinger_regular
        return pixel-identical arrays (max|diff| reported).  This is the hard proof that
        the MODEL INPUT PATH is untouched.
PART C  v21 judge picture: render both /tmp/gold_origin_now.png and /tmp/gold_judge_now.png,
        write them to zmax_data/aoi_v21_rect_probe/deploy_v21_*.png and print the metrics
        table (key count / per-key widths (all equal) / median width / median pitch /
        key row range / dropped bar rows + range / right edge x + basis / black fraction /
        kept-region mean / sat>=250 fraction / tilt / gain*gamma).

Pure ASCII only.
"""
import ast
import glob
import hashlib
import importlib.util
import os
import sys
import types

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "_stub"))
sys.path.insert(0, HERE)
TMP = os.path.join(HERE, "_v21test_tmp")
os.makedirs(TMP, exist_ok=True)
os.environ.setdefault("TEMP", TMP)
os.environ.setdefault("TMP", TMP)

# stub the vendor detector (the real one loads an encrypted model)
yd = types.ModuleType("yolo_detector")


class _YD:
    def __init__(self, *a, **k):
        pass

    def detect(self, *a, **k):
        return {"detections": [], "saved_incoming": None}


yd.YoloDetector = _YD
sys.modules["yolo_detector"] = yd

import cv2                                                              # noqa: E402

V20 = os.path.join(HERE, "cam_finger_10082_work_v20.py")   # byte-identical (sha c82a0299...)
V20_REF = "/home/ubuntu/zmax/docs/deliver/v6/cam_finger_10082_work_v20.py"
V21 = os.path.join(HERE, "cam_finger_10082_work_v21.py")
OUTDIR = "/home/ubuntu/zmax/zmax_data/aoi_v21_rect_probe"

CRITICAL = ["crop_goldfinger_regular", "GrabAndSaveImage", "get_cropper",
            "_region_payload", "_enc_jpg", "_mem_put", "_mem_get",
            "capture_detect_api", "picture_api", "last_result_api", "crop_info_api",
            "region_api", "storage_api", "prune_api", "run_flask",
            "_enqueue_detect", "_detect_worker_loop", "_ensure_detect_worker",
            "_resolve_detect_type_by_channel", "warp_goldfinger_topview"]


def _srcs(path):
    txt = open(path, encoding="utf-8").read()
    tree = ast.parse(txt)
    out = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = ast.get_source_segment(txt, node)
    return out


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    fails = []

    print("=" * 78)
    print("PART A  source equality of the model path + every route (AST)")
    print("=" * 78)
    s20, s21 = _srcs(V20), _srcs(V21)
    _ha = hashlib.sha256(open(V20, "rb").read()).hexdigest()
    _hb = hashlib.sha256(open(V20_REF, "rb").read()).hexdigest()
    _hc = hashlib.sha256(open(V21, "rb").read()).hexdigest()
    print("  v20 baseline sha256 : %s" % _ha)
    print("  v20 (deliver) sha256: %s  identical=%s" % (_hb, _ha == _hb))
    print("  v21 sha256          : %s" % _hc)
    for fn in CRITICAL:
        a, b = s20.get(fn), s21.get(fn)
        same = (a is not None and a == b)
        print("  [%s] %-32s %s" % ("SAME" if same else "DIFF", fn,
                                   "" if same else "MISSING/CHANGED"))
        if not same:
            fails.append("PART A %s" % fn)
    changed = sorted(set(s21) - set(s20))
    print("  functions only in v21: %s" % (changed or "none"))

    print()
    print("=" * 78)
    print("PART B  runtime pixel equality of crop_goldfinger_regular (model input path)")
    print("=" * 78)
    m20 = load(V20, "cf_v20")
    m21 = load(V21, "cf_v21")
    for img_p in ["/tmp/gold_origin_now.png", "/tmp/gold_judge_now.png"]:
        im = cv2.imread(img_p)
        if im is None:
            print("  SKIP %s (unreadable)" % img_p)
            continue
        c20, i20 = m20.crop_goldfinger_regular(im)
        c21, i21 = m21.crop_goldfinger_regular(im)
        a = np.ascontiguousarray(c20)
        b = np.ascontiguousarray(c21)
        md = int(np.abs(a.astype(np.int32) - b.astype(np.int32)).max()) if a.shape == b.shape else -1
        h20 = hashlib.md5(a.tobytes()).hexdigest()
        h21 = hashlib.md5(b.tobytes()).hexdigest()
        ok = (a.shape == b.shape) and md == 0 and h20 == h21
        print("  %-28s shape v20=%s v21=%s max|diff|=%d md5 v20=%s v21=%s -> %s"
              % (os.path.basename(img_p), a.shape, b.shape, md, h20[:12], h21[:12],
                 "IDENTICAL" if ok else "MISMATCH"))
        method_same = (i20.get("method") == i21.get("method"))
        print("      crop method v20=%s v21=%s -> %s"
              % (i20.get("method"), i21.get("method"), "same" if method_same else "DIFF"))
        if not ok:
            fails.append("PART B %s" % img_p)
        if not method_same:
            fails.append("PART B method %s" % img_p)

    print()
    print("=" * 78)
    print("PART C  v21 judge picture + metrics")
    print("=" * 78)
    for img_p in ["/tmp/gold_origin_now.png", "/tmp/gold_judge_now.png"]:
        im = cv2.imread(img_p)
        if im is None:
            print("  SKIP %s (unreadable)" % img_p)
            continue
        out, met = m21.render_judge(im)
        tag = os.path.basename(img_p).replace(".png", "")
        if out is None:
            print("  %s -> RENDER FAILED: %s" % (tag, met.get("why")))
            fails.append("PART C %s render" % tag)
            continue
        dst = os.path.join(OUTDIR, "deploy_v21_%s.png" % tag)
        cv2.imwrite(dst, out)
        widths = [b - a + 1 for a, b in (met.get("rects") or [])]
        uniq = sorted(set(widths))
        print()
        print("  --- %s  (src %s) ---" % (img_p, met.get("src_size")))
        print("  output file                : %s  %dx%d" % (dst, out.shape[1], out.shape[0]))
        print("  key count                  : %d" % met.get("n_keys"))
        print("  per-key widths (px)        : %s" % widths)
        print("  -> all equal?              : %s  (distinct widths %s)"
              % (len(uniq) == 1, uniq))
        print("  median detected width (px) : %s" % met.get("width_median_detected_px"))
        print("  uniform width used (px)    : %s" % met.get("width_uniform_px"))
        print("  median pitch (px)          : %s" % met.get("pitch_median_px"))
        print("  key row range              : %s  (%s rows)"
              % (met.get("key_rows"), met.get("n_key_rows")))
        print("  key-row window span        : %s" % met.get("key_row_span"))
        print("  bar rows dropped / range   : %s / %s"
              % (met.get("bar_rows_dropped"), met.get("bar_rows_range")))
        print("  bar rule                   : %s" % met.get("bar_rule"))
        print("  right edge x / basis       : %s / %s"
              % (met.get("right_edge_x"), met.get("right_edge_src")))
        print("  outlier dropped / skipped  : %s / %s  (%s)"
              % (met.get("outlier_dropped"), met.get("outlier_skipped"),
                 met.get("outlier_note")))
        print("  outlier flags              : %s" % met.get("outlier_flags"))
        print("  black fraction             : %s" % met.get("black_frac"))
        print("  kept-region mean           : %s" % met.get("strip_mean_content"))
        print("  whole-frame mean           : %s" % met.get("strip_mean"))
        print("  sat>=250 fraction          : %s   (raw frame band %s)"
              % (met.get("strip_sat_frac"), met.get("sat_before")))
        print("  tilt (deg)                 : %s" % met.get("tilt_deg"))
        print("  gain x gamma               : %s x %s  (auto=%s)"
              % (met.get("gain"), met.get("gamma"), met.get("exposure_auto")))
        print("  v20 meta aliases           : out=%s kept_rows=%s kept_h=%s "
              "dropped_sat_rows=%s dropped_pct=%s x_span=%s fix_hw=%s deskew_deg=%s"
              % (met.get("out"), met.get("kept_rows"), met.get("kept_h"),
                 met.get("dropped_sat_rows"), met.get("dropped_pct"),
                 (met.get("x_trim") or {}).get("x_span"), met.get("fix_hw"),
                 met.get("deskew_deg")))
        # acceptance
        if len(uniq) != 1:
            fails.append("PART C %s widths not uniform" % tag)
        if out.shape[1] != 900 or out.shape[0] != 332:
            fails.append("PART C %s size" % tag)
        if met.get("black_frac", 0) < 0.35:
            fails.append("PART C %s black_frac" % tag)
        if met.get("strip_sat_frac", 1) > 0.02:
            fails.append("PART C %s sat" % tag)
        if met.get("outlier_dropped") and not met.get("outlier_skipped"):
            pass

    print()
    print("=" * 78)
    if fails:
        print("RESULT: %d FAILURE(S): %s" % (len(fails), fails))
    else:
        print("RESULT: ALL CHECKS PASSED")
    print("images -> %s" % OUTDIR)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
