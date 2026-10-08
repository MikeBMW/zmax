#!/usr/bin/env python3
"""test_gold_judge_rect_v21.py -- self test + before/after comparison generator
for tools/aoi/gold_judge_rect_v21.py.

Run with the cv2-enabled interpreter:
    cd /home/ubuntu/zmax
    ./gui-venv311/bin/python tools/aoi/test_gold_judge_rect_v21.py

For every input it renders
  BEFORE = the in-service renderer (tools/aoi/judge_render.render_judge), i.e.
           what the shop floor sees today,
  AFTER  = gold_judge_rect_v21.render_judge_v21,
writes a stacked before/after comparison PNG with the metrics burned in to
/home/ubuntu/zmax/zmax_data/aoi_v21_rect_probe/, prints a metrics table and
asserts the acceptance criteria of the request.

Pure ASCII only.
"""

from __future__ import annotations

import glob
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import judge_render as JR                                              # noqa: E402
import gold_judge_rect_v21 as V21                                       # noqa: E402

OUTDIR = "/home/ubuntu/zmax/zmax_data/aoi_v21_rect_probe"
PANEL_W = 1400                       # both panels are scaled to this width

INPUTS = [
    ("/tmp/gold_origin_now.png", "field_frame"),
    ("/tmp/gold_judge_now.png", "inservice_judge"),
]
INPUTS += [(p, "sample_" + os.path.basename(p)) for p in
           sorted(glob.glob("/home/ubuntu/zmax/zmax_data/aoi_v4/goldfinger_images/"
                            "Finger_Image_*.png"))]
INPUTS += [(p, "sample_" + os.path.basename(p)) for p in
           sorted(glob.glob("/home/ubuntu/zmax/zmax_data/aoi_v4/goldfinger_images/"
                            "\u91d1\u624b\u6307_origin*.png"))]
INPUTS += [(p, "sample_" + os.path.basename(p)) for p in
           sorted(glob.glob("/home/ubuntu/zmax/zmax_data/release_20260924_aoi/opt_view/"
                            "\u91d1\u624b\u6307_origin*.png"))]


def _fit_scale(img, w):
    if img is None:
        return None
    sc = w / float(max(1, img.shape[1]))
    return cv2.resize(img, (w, max(2, int(round(img.shape[0] * sc)))),
                      interpolation=cv2.INTER_AREA if sc < 1.0 else cv2.INTER_LINEAR)


def _panel(img, title, w=PANEL_W):
    """Scaled picture + a title band, padded to a fixed height."""
    body = _fit_scale(img, w)
    if body is None:
        body = np.zeros((120, w, 3), np.uint8)
        cv2.putText(body, "NO IMAGE", (w // 2 - 70, 60),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)
    band = np.zeros((24, w, 3), np.uint8)
    cv2.putText(band, title, (6, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
    return np.vstack([band, body])


def _txt(lines, w, h):
    out = np.zeros((h, w, 3), np.uint8)
    y = 15
    for ln in lines:
        cv2.putText(out, ln, (6, y), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (210, 225, 255), 1)
        y += 14
        if y > h - 3:
            break
    return out


def _luma(img):
    b = img.astype(np.float32)
    return 0.114 * b[:, :, 0] + 0.587 * b[:, :, 1] + 0.299 * b[:, :, 2]


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    rows = []
    for path, tag in INPUTS:
        img = cv2.imread(path)
        if img is None:
            print("SKIP (unreadable): %s" % path)
            continue
        if tag == "inservice_judge":
            before = img.copy()
            btag = "BEFORE = in-service judge image (as captured by the line)"
        else:
            before, _ = JR.render_judge(img, deskew_deg=0.0)
            btag = "BEFORE = in-service render_judge (judge_render.py)"
        after, meta = V21.render_judge_v21(img)

        bg = _luma(before) if before is not None else np.zeros((8, 8), np.float32)
        b_sat, b_mean = float((bg >= 250).mean()), float(bg.mean())

        left = _panel(before, btag)
        right = _panel(after, "AFTER = render_judge_v21 (keys only / upright / black)")
        hh = max(left.shape[0], right.shape[0])
        for p in (left, right):
            if p.shape[0] < hh:
                p.resize((hh, p.shape[1], 3), refcheck=False)
        comp = np.hstack([left, np.full((hh, 10, 3), 45, np.uint8), right])

        if meta.get("ok"):
            lines = [
                "file %s   src %s  mean %.1f" % (os.path.basename(path),
                                                 meta.get("src_size"), meta.get("src_mean")),
                "key row span %s   key rows %s (%d rows)" % (meta.get("key_row_span"),
                                                             meta.get("key_rows"),
                                                             meta.get("n_key_rows")),
                "keys %s  pitch %s px  width mean %s px (median %s)  regular %s" % (
                    meta.get("n_keys"), meta.get("pitch_px"), meta.get("width_mean_px"),
                    meta.get("key_width_median_px"), meta.get("n_regular_keys")),
                "bar rows dropped %s (bright %s)   bar gate %s" % (
                    meta.get("bar_rows_dropped"), meta.get("bar_rows_bright"),
                    meta.get("bar_bright_gate")),
                "strip cols %s (right_edge_x %s, cut %s px = %.1f%% of width)" % (
                    meta.get("strip_cols"), meta.get("right_edge_x"),
                    meta.get("cut_right_px"), 100.0 * (meta.get("cut_right_frac") or 0)),
                "edge@cut %s  bright@cut %s  band y %s" % (
                    meta.get("edge_at_cut"), meta.get("bright_at_cut"),
                    meta.get("strip_col_band_y")),
                "left cut %s px (%.1f%%)  tilt %.3f deg  rot %.3f deg" % (
                    meta.get("cut_left_px"), 100.0 * (meta.get("cut_left_frac") or 0),
                    meta.get("tilt_deg"), meta.get("rot_deg")),
                "out %s  scale %s  black %.3f  non-black frac %.3f" % (
                    meta.get("out_size"), meta.get("resize_scale_xy"),
                    meta.get("black_frac"), meta.get("nonblack_frac")),
                "mean %.1f  non-black mean %.1f  median %.1f  sat>=250 %.4f" % (
                    meta.get("strip_mean"), meta.get("nonblack_mean"),
                    meta.get("strip_median"), meta.get("strip_sat_frac")),
                "tenengrad %.0f  dynamic range %s  clip(raw) %.3f" % (
                    meta.get("tenengrad"), meta.get("dynamic_range"),
                    meta.get("clip_frac_raw")),
                "|dI/dy| src %.2f -> geo %.2f (gate %.1f)   |dI/dx| geo %.2f" % (
                    meta.get("edge_hy_src"), meta.get("edge_hy_geo"),
                    meta.get("edge_gate_min"), meta.get("edge_vx_geo")),
                "gain %.3f gamma %.3f (auto %s, json %s)" % (
                    meta.get("gain"), meta.get("gamma"), meta.get("exposure_auto"),
                    meta.get("exposure_from_json")),
                "BEFORE: sat %.3f  mean %.1f" % (b_sat, b_mean),
                "right_src %s" % (meta.get("right_edge_src") or "")[:120],
                "texture_gate %s" % (meta.get("texture_gate") or ""),
            ]
            rows.append({
                "file": os.path.basename(path), "tag": tag, "ok": True,
                "n_keys": meta.get("n_keys"), "pitch": meta.get("pitch_px"),
                "width": meta.get("width_mean_px"), "tilt": meta.get("tilt_deg"),
                "black": meta.get("black_frac"), "mean": meta.get("strip_mean"),
                "nb_mean": meta.get("nonblack_mean"),
                "sat": meta.get("strip_sat_frac"), "gain": meta.get("gain"),
                "gamma": meta.get("gamma"), "rd_x": meta.get("right_edge_x"),
                "cutR": meta.get("cut_right_px"), "bars": meta.get("bar_rows_dropped"),
                "hy_src": meta.get("edge_hy_src"), "out": meta.get("out_size"),
                "src_w": (meta.get("src_size") or [0])[0],
                "b_mean": round(b_mean, 1), "b_sat": round(b_sat, 4),
                "hy_geo": meta.get("edge_hy_geo") or 0.0,
                "why": meta.get("why"),
            })
        else:
            lines = ["file %s" % os.path.basename(path), "RENDER FAILED",
                     "why: %s" % meta.get("why")]
            rows.append({"file": os.path.basename(path), "tag": tag, "ok": False,
                         "why": meta.get("why")})

        strip = _txt(lines, PANEL_W, 240)
        comp = np.vstack([comp, np.full((6, comp.shape[1], 3), 45, np.uint8),
                          np.hstack([strip, np.full((240, 10, 3), 45, np.uint8),
                                     np.zeros_like(strip)])])
        cv2.imwrite(os.path.join(OUTDIR, "cmp_%s.png" % tag), comp)

    # ---------------- table ----------------
    hdr = ("%-34s %-4s %5s %6s %6s %8s %7s %8s %8s %6s %6s %6s"
           % ("file", "ok", "keys", "pitch", "width", "tilt_deg", "black",
              "nonblkM", "mean", "satA", "gain", "cutR"))
    print("=" * len(hdr))
    print("METRICS (keys = vertical lines kept, pitch/width in px, tilt_deg = fit of"
          " the kept key tops, black = black_frac, nonblkM = mean of the kept pixels,"
          " satA = sat>=250 after, cutR = px cut on the right)")
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        if not r.get("ok"):
            print("%-34s %-4s FAILED: %s" % (r["file"][:34], "NO", (r.get("why") or "")[:60]))
            continue
        print("%-34s %-4s %5s %6s %6s %8s %7s %8s %8s %6s %6s %6s" % (
            r["file"][:34], "yes", r["n_keys"], r["pitch"], r["width"], r["tilt"],
            r["black"], r["nb_mean"], r["mean"], r["sat"], r["gain"], r["cutR"]))
    print("=" * len(hdr))

    # ---------------- acceptance ----------------
    print("\nACCEPTANCE")
    checks = []

    def chk(name, cond, detail=""):
        checks.append((name, bool(cond)))
        print("  [%s] %s %s" % ("PASS" if cond else "FAIL", name, detail))

    ok_rows = [r for r in rows if r.get("ok")]
    chk("all inputs produced an image", len(ok_rows) == len(rows) and rows,
        "%d/%d" % (len(ok_rows), len(rows)))
    by = {r["tag"]: r for r in rows}

    f = by.get("field_frame")
    if f and f.get("ok"):
        chk("field frame: found a real key row (>= 20 keys)", f["n_keys"] >= 20,
            "n_keys=%s pitch=%s width=%s" % (f["n_keys"], f["pitch"], f["width"]))
        chk("field frame: pitch within the plausible range",
            f["pitch"] is not None and 40 <= f["pitch"] <= 120, "pitch=%s" % f["pitch"])
        chk("field frame: the grey block on the right is cut", f["cutR"] >= 200,
            "right_edge_x=%s cutR=%s" % (f["rd_x"], f["cutR"]))
        chk("field frame: the solid bar rows are dropped", f["bars"] >= 1,
            "bar_rows_dropped=%s" % f["bars"])
        chk("field frame: background dominant (black)", f["black"] >= 0.50,
            "black=%.3f" % f["black"])
        chk("field frame: not over-exposed", f["sat"] <= 0.02, "sat=%.4f" % f["sat"])
        chk("field frame: upright (|tilt| <= 0.3 deg)", abs(f["tilt"]) <= 0.30,
            "tilt=%.3f" % f["tilt"])
        chk("field frame: pads still legible (non-black mean 80..230)",
            80 <= f["nb_mean"] <= 230, "nonblack_mean=%s" % f["nb_mean"])

    g = by.get("inservice_judge")
    if g and g.get("ok"):
        chk("in-service judge: grey block cut", g["cutR"] >= 100,
            "right_edge_x=%s cutR=%s" % (g["rd_x"], g["cutR"]))
        chk("in-service judge: keys found", g["n_keys"] >= 8, "n_keys=%s" % g["n_keys"])
        chk("in-service judge: dimmed vs before", g["mean"] < g["b_mean"],
            "before %.1f -> after %.1f" % (g["b_mean"], g["mean"]))

    for r in ok_rows:
        chk("%s: saturation within target (<= 2%%)" % r["tag"], r["sat"] <= 0.02,
            "sat=%.4f" % r["sat"])
        chk("%s: key texture preserved / source gate" % r["tag"],
            (r["hy_src"] >= 3.5) if r["src_w"] >= 1600
            else (r["hy_geo"] >= 0.5 * r["hy_src"]),
            "src_w=%s |dI/dy|_src=%.2f geo=%.2f" % (r["src_w"], r["hy_src"], r["hy_geo"]))

    n_fail = sum(1 for _, c in checks if not c)
    print("\n%d/%d checks passed" % (len(checks) - n_fail, len(checks)))
    print("comparison images ->", OUTDIR)
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
