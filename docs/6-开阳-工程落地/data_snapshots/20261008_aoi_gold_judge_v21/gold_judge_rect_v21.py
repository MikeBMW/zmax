#!/usr/bin/env python3
"""gold_judge_rect_v21.py -- offline "judge image" renderer for the Z-MAX
gold-finger AOI channel (port 10082).

WHAT THE SHOP FLOOR ASKED FOR
-----------------------------
The gold finger is NOT a solid band: it is a ROW OF SMALL VERTICAL KEYS
(piano keys).  The judge picture must show exactly that row of keys, upright
and rectangular, on a pure black background, and it must not be over-exposed.
Everything else -- the background, the plastic lip, the big full-width
horizontal bar that sits under the keys, the flat grey block on the right and
the connector head on the left -- must be pure black (0,0,0).

RECIPE (validated on the field frame /tmp/gold_origin_now.png: 26 keys,
median pitch 70 px, mean key width 29 px, black fraction 61.3%)

  1. row search, data driven.  Slide a 50-row window (step 10 px) down the
     frame.  Inside a window, "bright columns" are the columns where at least
     45% of the window rows are >= 200; adjacent bright columns are merged
     (gap <= 3 px) and groups narrower than 4 px are dropped.  A window is a
     KEY ROW WINDOW when it holds >= 6 groups, the median pitch of the groups
     is 25..140 px and the pitch jitter (median absolute deviation) is below
     25% of the pitch.  That test is exactly what kills the big horizontal
     bar: a full-width bar is ONE group, so it can never hit.

  2. column range: a row band taken from the middle of the key rows is
     profiled for HORIZONTAL edge strength (mean |dI/dy| per column).  The
     metal body measures 4.4..7.2 while the flat grey block on the right
     measures 0.66..0.88, so the strip columns are where that strength clears
     EDGE_CUT.  This is what removes the grey block.

  3. second guard against the bar: inside the key row range every row that is
     >= 85% bright across the strip columns is dropped outright (measured:
     15 rows, brightness 0.94..0.95).

  4. keys: the per-window bright-column profiles are averaged; columns >= 40%
     are keys (gaps <= 4 px merged, groups < 4 px dropped).

  5. mask = bright pixels AND key rows AND key columns, decided per pixel in
     native coordinates so the camera tilt is carried by the mask, not by a
     rectangle.  The kept picture is then cropped to its bounding box + 20 px
     and rotated upright with a black border (NEAREST, to keep the texture).

  6. exposure: linear gain followed by gamma, adjustable at runtime and
     persisted to JSON next to this file.

Everything is data driven; the only fixed numbers are the tolerances above,
and every one of them is reported in the returned meta dict.

ASCII only: the shop-floor Windows hosts have trouble with non-ASCII sources.
"""

from __future__ import annotations

import json
import os

import cv2
import numpy as np

# ---------------------------------------------------------------------------
# parameters (all reported in meta)
# ---------------------------------------------------------------------------
WIN_H = 50                      # key-row search window height (px)
WIN_STEP = 10                   # ... and step
CF_BRIGHT_COL = 0.45            # a column is bright inside a window at this fraction
COL_MERGE_GAP = 3               # merge bright columns closer than this (px)
MIN_SEG_W = 4                   # drop bright groups narrower than this (px)
MIN_KEYS = 6                    # a key row window needs at least this many groups
PITCH_MIN = 25.0                # ... with a median pitch in this range
PITCH_MAX = 140.0
PITCH_JITTER_K = 0.25           # ... and a jitter below this fraction of the pitch

EDGE_CUT = 2.5                  # horizontal edge strength of the strip columns
EDGE_BAND_H = 40                # rows used for the column profile (middle of the keys)
CUT_RUN = 20                    # a cut segment must last this many columns
BORDER_IGNORE = 6               # ignore this many frame-edge columns
COL_PAD = 4                     # keep a few px past the detected end
MIN_KEEP_W = 120                # refuse if fewer columns survive

BAR_BRIGHT = 0.85               # inside the key rows: this bright -> the solid bar
CF_KEY_COL = 0.40               # a column is a key at this averaged fraction
KEY_MERGE_GAP = 4               # merge key columns closer than this (px)
MIN_KEY_W = 4                   # drop key groups narrower than this (px)

CROP_PAD = 20                   # margin around the kept content (px)
OUT_W = 1400                    # delivered width (height follows the aspect)
MAX_UPSCALE_Y = 3.0             # refuse a bigger upscale than this (the scale is
                                # uniform, and NEAREST is used above 1.0, so the
                                # texture cannot be smeared)

BRIGHT_LEVEL = 200              # upper clamp of the adaptive brightness level
BRIGHT_MIN = 60.0               # lower clamp
BRIGHT_FRAC = 0.72              # a pixel is "bright" above this much of the local p96
SAT_LEVEL = 250
EDGE_KEEP_MIN = 3.5             # the kept keys must still show this much |dI/dy|
TILT_TOL_PX = 0.30              # target residual tilt (px per 1000)

CANVAS_BG = (0, 0, 0)           # everything outside the keys is pure black

EXPOSURE_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "gold_judge_v21_exposure.json")
DEFAULT_GAIN = 0.50
DEFAULT_GAMMA = 1.00
AUTO_PEAK = 205.0               # auto gain puts the brightest kept pixel here


# ---------------------------------------------------------------------------
# runtime-adjustable exposure (mirrors the surface channel's /exposure)
# ---------------------------------------------------------------------------
def read_exposure_json(path=None):
    """-> (gain, gamma) from the JSON file, or (None, None)."""
    p = path or EXPOSURE_JSON
    try:
        with open(p, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        return float(d.get("gain", DEFAULT_GAIN)), float(d.get("gamma", DEFAULT_GAMMA))
    except Exception:                                                    # noqa: BLE001
        return None, None


def write_exposure_json(gain, gamma, path=None):
    """Persist the exposure so the next run (and the service) picks it up."""
    p = path or EXPOSURE_JSON
    try:
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({"gain": round(float(gain), 4), "gamma": round(float(gamma), 4)},
                      fh, indent=2)
        return True
    except Exception:                                                    # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _as_bgr(bgr):
    a = np.asarray(bgr)
    if a.ndim == 2:
        return cv2.cvtColor(a.astype(np.uint8), cv2.COLOR_GRAY2BGR)
    if a.ndim == 3 and a.shape[2] == 4:
        return cv2.cvtColor(a.astype(np.uint8), cv2.COLOR_BGRA2BGR)
    if a.ndim == 3 and a.shape[2] == 3:
        return a.astype(np.uint8, copy=False)
    raise ValueError("unsupported image shape %r" % (a.shape,))


def _luma(bgr):
    """BT.601 luma as float32 (matches the shop-floor gray() helper)."""
    b = bgr.astype(np.float32)
    return 0.114 * b[:, :, 0] + 0.587 * b[:, :, 1] + 0.299 * b[:, :, 2]


def _segments(on, merge_gap, min_w):
    """Group the True runs of a boolean array; merge runs closer than merge_gap."""
    idx = np.where(np.asarray(on, bool))[0]
    if idx.size == 0:
        return []
    segs = [[int(idx[0]), int(idx[0])]]
    for v in idx[1:]:
        if int(v) - segs[-1][1] <= int(merge_gap) + 1:
            segs[-1][1] = int(v)
        else:
            segs.append([int(v), int(v)])
    return [(a, b) for a, b in segs if (b - a + 1) >= int(min_w)]


def _pitch_stats(segs):
    """Median pitch and its median absolute deviation, from the segment centres."""
    if len(segs) < 2:
        return None, None
    c = np.array([(a + b) / 2.0 for a, b in segs], np.float32)
    d = np.diff(c)
    med = float(np.median(d))
    return med, float(np.median(np.abs(d - med)))


def _robust_line(xs, ys, iters=3):
    """Least squares fit with a couple of hard-outlier rejections."""
    if len(xs) < 8:
        return None
    xs = np.asarray(xs, np.float64)
    ys = np.asarray(ys, np.float64)
    keep = np.ones(xs.size, bool)
    for _ in range(iters):
        if keep.sum() < 8:
            return None
        k, c = np.polyfit(xs[keep], ys[keep], 1)
        r = np.abs(ys - (k * xs + c))
        thr = max(2.0, 2.5 * float(np.median(r[keep])))
        new = r <= thr
        if new.sum() < 8 or np.array_equal(new, keep):
            break
        keep = new
    k, c = np.polyfit(xs[keep], ys[keep], 1)
    return float(k), float(np.abs(ys[keep] - (k * xs[keep] + c)).max()), int(keep.sum())


def _rotate(bgr, deg, center):
    """Rotate with a pure black border; NEAREST keeps the pad texture."""
    h, w = bgr.shape[:2]
    m = cv2.getRotationMatrix2D(center, float(deg), 1.0)
    return cv2.warpAffine(bgr, m, (w, h), flags=cv2.INTER_NEAREST,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))


def _apply_exposure(bgr, gain, gamma):
    """out = 255 * (clip(gain * in/255)) ** (1/gamma).  0 stays 0."""
    x = bgr.astype(np.float32) / 255.0
    x = np.clip(x * float(gain), 0.0, 1.0)
    x = np.power(x, 1.0 / max(float(gamma), 1e-3))
    return np.clip(x * 255.0, 0.0, 255.0).astype(np.uint8)


def _tenengrad(g):
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1)
    return float(np.mean(gx * gx + gy * gy))


def _smooth1d(a, k=7):
    a = np.asarray(a, np.float32)
    n = a.size
    if n <= k:
        return a.copy()
    out = np.empty(n, np.float32)
    half = k // 2
    for i in range(n):
        out[i] = np.median(a[max(0, i - half):min(n, i + half + 1)])
    return out


# ---------------------------------------------------------------------------
# 1. the key row windows
# ---------------------------------------------------------------------------
def _adaptive_bright(win):
    """Brightness level that means "lit metal" for THIS window.

    An absolute level cannot work across the line: the field frames are over
    exposed (a saturated key), the archived samples are two stops darker
    (key luma 60..110).  So the level follows the window's own 96th percentile,
    clamped to a sane range."""
    return float(np.clip(BRIGHT_FRAC * float(np.percentile(win, 96)),
                         BRIGHT_MIN, BRIGHT_LEVEL))


def _key_windows(g, lvl=BRIGHT_LEVEL):
    """Slide the window and keep the ones that look like a row of keys."""
    h, w = g.shape
    mrows = g.mean(axis=1)
    bg = float(np.percentile(mrows, 20))
    gate = min(bg + 25.0, 1.35 * bg)
    hits = []
    y = 0
    while y + WIN_H <= h:
        if float(mrows[y:y + WIN_H].mean()) >= gate:
            win = g[y:y + WIN_H, :]
            cf = (win >= lvl).mean(axis=0)
            segs = _segments(cf >= CF_BRIGHT_COL, COL_MERGE_GAP, MIN_SEG_W)
            med, mad = _pitch_stats(segs)
            if (len(segs) >= MIN_KEYS and med is not None
                    and PITCH_MIN <= med <= PITCH_MAX
                    and mad < PITCH_JITTER_K * med):
                hits.append({"y0": int(y), "y1": int(y + WIN_H - 1),
                             "n_seg": int(len(segs)), "pitch_px": round(med, 1),
                             "jitter_px": round(mad, 1), "bright_level": round(lvl, 1)})
        y += WIN_STEP
    info = {"bg_level": round(bg, 1), "window_mean_gate": round(gate, 1),
            "n_windows": int(len(hits)), "bright_level": round(lvl, 1)}
    return hits, info, lvl


# ---------------------------------------------------------------------------
# 2. the strip columns (horizontal edge strength)
# ---------------------------------------------------------------------------
def _col_profiles(g_band):
    """Per column inside the band: horizontal edge strength |dI/dy| + bright frac."""
    e = np.zeros(g_band.shape[1], np.float32)
    if g_band.shape[0] >= 2:
        e[:] = np.abs(np.diff(g_band, axis=0)).mean(axis=0)
    b = (g_band >= BRIGHT_LEVEL).mean(axis=0).astype(np.float32)
    return e, b


def _strip_cols(g, ky0, ky1):
    """Left/right end of the metal body, from the horizontal edge strength."""
    h, w = g.shape
    y0 = max(0, int(ky0))
    y1 = min(h, int(ky1) + 1)
    # a narrow band in the middle of the keys is where the field measurement was
    # taken (y740..780 for keys at y640..840) and it is the most discriminative
    mid = (y0 + y1) // 2
    b0 = max(0, mid - EDGE_BAND_H // 2)
    b1 = min(h, b0 + EDGE_BAND_H)
    e, b = _col_profiles(g[b0:b1, :])
    e = _smooth1d(e, 7)
    e[:BORDER_IGNORE] = 0.0
    e[w - BORDER_IGNORE:] = 0.0
    on = e >= EDGE_CUT
    hi = np.where(on)[0]
    right = None
    rsrc = ""
    if hi.size:
        xr = int(hi.max())
        tail = e[xr + 1:]
        if len(tail) >= CUT_RUN and tail.mean() < EDGE_CUT and b[xr + 1:].mean() < 0.10:
            right = xr
            rsrc = ("the last column with |dI/dy| >= %.1f is x=%d; the %d columns "
                    "beyond it carry edge %.2f and bright %.3f -> grey block cut"
                    % (EDGE_CUT, xr, len(tail), float(tail.mean()),
                       float(b[xr + 1:].mean())))
        else:
            rsrc = ("trailing segment too short (only %d columns) or still textured "
                    "-> right end kept at x=%d" % (len(tail), xr))
    else:
        rsrc = "no column reaches the edge gate %.1f" % EDGE_CUT
    left = 0
    lsrc = ""
    if hi.size:
        xl = int(hi.min())
        head = e[:xl]
        if len(head) >= CUT_RUN and head.mean() < EDGE_CUT:
            left = xl
            lsrc = ("leading %d columns: edge %.2f (< %.1f) -> background cut at x=%d"
                    % (len(head), float(head.mean()), EDGE_CUT, xl))
        else:
            lsrc = ("left end kept (leading gate not met: edge %.2f over %d columns)"
                    % (float(head.mean()) if len(head) else 0.0, len(head)))
    return left, right, e, b, rsrc, lsrc, (b0, b1)


# ---------------------------------------------------------------------------
# 3. the keys (vertical lines)
# ---------------------------------------------------------------------------
def _key_columns(g, hits, x0, x1, lvl):
    """Average bright-column profile of the hit windows -> the key segments."""
    acc = None
    for hh in hits:
        cf = (g[hh["y0"]:hh["y1"] + 1, x0:x1] >= lvl).mean(axis=0)
        acc = cf if acc is None else acc + cf
    if acc is None:
        return [], None
    cfmean = acc / float(len(hits))
    segs = _segments(cfmean >= CF_KEY_COL, KEY_MERGE_GAP, MIN_KEY_W)
    segs = [(a + x0, b + x0) for a, b in segs]
    med, mad = _pitch_stats(segs)
    widths = [b - a + 1 for a, b in segs]
    info = {"cf_key_col": CF_KEY_COL, "key_segments": segs,
            "n_keys": len(segs),
            "pitch_px": round(med, 1) if med is not None else None,
            "pitch_jitter_px": round(mad, 1) if mad is not None else None,
            "width_mean_px": round(float(np.mean(widths)), 1) if widths else None,
            "width_min_px": int(np.min(widths)) if widths else None,
            "width_max_px": int(np.max(widths)) if widths else None}
    return segs, info


# ---------------------------------------------------------------------------
# main entry point
# ---------------------------------------------------------------------------
def render_judge_v21(bgr, gain=None, gamma=None, hw=(OUT_W, None), deskew_deg=0.0,
                     layout="box"):
    """Render the gold-finger judge picture.

    Returns (img | None, meta).  `img` is BGR uint8, width hw[0]; the height
    follows the kept content's aspect ratio unless hw[1] is given.  On any
    failure the image is None and meta['why'] says what was wrong -- a wrong
    crop is never handed out.
    """
    hw = (int(hw[0]) if hw and hw[0] else OUT_W,
          int(hw[1]) if (hw and len(hw) > 1 and hw[1]) else None)
    met = {"ok": False, "why": "", "canvas_w": int(hw[0]), "layout": layout}
    try:
        src = _as_bgr(bgr)
        if src.size == 0:
            met["why"] = "empty image"
            return None, met
        h, w = src.shape[:2]
        met["src_size"] = [int(w), int(h)]
        met["src_mean"] = round(float(_luma(src).mean()), 1)

        # stored exposure wins unless the caller overrides it
        jg, jm = read_exposure_json()
        g_use = float(gain) if gain is not None else (jg if jg is not None else None)
        gm_use = float(gamma) if gamma is not None else (jm if jm is not None else None)
        met["exposure_json"] = EXPOSURE_JSON
        met["exposure_from_json"] = bool(gain is None and jg is not None)

        g = _luma(src)

        # ---- 1. key row windows ------------------------------------------
        hits, winfo, lvl = _key_windows(g, BRIGHT_LEVEL)
        met["bright_level_used"] = round(lvl, 1)
        if not hits:
            # The validated recipe uses an absolute level of 200 (the field
            # frames are over exposed).  Two stops darker archived frames need a
            # lower level, so retry once with a level adapted to the image and
            # flag it in the meta.
            mrows = g.mean(axis=1)
            bg = float(np.percentile(mrows, 20))
            gate = min(bg + 25.0, 1.35 * bg)
            cand = [y for y in range(0, g.shape[0] - WIN_H + 1, WIN_STEP)
                    if float(mrows[y:y + WIN_H].mean()) >= gate]
            if cand:
                lvl2 = float(np.median([_adaptive_bright(g[y:y + WIN_H, :])
                                        for y in cand]))
                hits, winfo, lvl = _key_windows(g, lvl2)
                met["bright_level_used"] = round(lvl, 1)
                met["bright_level_fallback"] = True
        met.update(winfo)
        met["key_windows"] = hits[:20]
        if not hits:
            met["why"] = ("no key-row window found (needs >= %d bright groups with a "
                          "median pitch of %.0f..%.0f px and jitter < %.0f%%)"
                          % (MIN_KEYS, PITCH_MIN, PITCH_MAX, PITCH_JITTER_K * 100))
            return None, met

        # ---- 2. strip columns (kills the flat grey block on the right) -----
        ky0 = min(hh["y0"] for hh in hits)
        ky1 = max(hh["y1"] for hh in hits)
        left, right, e, b, rsrc, lsrc, band = _strip_cols(g, ky0, ky1)
        if right is None:
            right = w - 1
        cx0 = int(max(0, left - COL_PAD))
        cx1 = int(min(w, right + 1 + COL_PAD))
        met["key_row_span"] = [int(ky0), int(ky1)]
        met["strip_cols"] = [int(left), int(right)]
        met["strip_col_band_y"] = [int(band[0]), int(band[1])]
        met["right_edge_src"] = rsrc
        met["left_edge_src"] = lsrc
        met["edge_at_cut"] = [round(float(e[min(right, w - 1)]), 2),
                              round(float(e[min(right + 1, w - 1)]), 2)]
        met["bright_at_cut"] = [round(float(b[min(right, w - 1)]), 3),
                                round(float(b[min(right + 1, w - 1)]), 3)]
        met["right_edge_x"] = int(cx1)
        met["cut_right_px"] = int(w - cx1)
        met["cut_right_frac"] = round(float(w - cx1) / float(w), 4)
        met["cut_left_px"] = int(cx0)
        met["cut_left_frac"] = round(float(cx0) / float(w), 4)
        if right - left + 1 < MIN_KEEP_W:
            met["why"] = ("strip column run too narrow after the cut (%d px < %d)"
                          % (right - left + 1, MIN_KEEP_W))
            return None, met

        # ---- 3. keys ------------------------------------------------------
        segs, kinfo = _key_columns(g, hits, cx0, cx1, lvl)
        if kinfo:
            met.update(kinfo)
        if not segs:
            met["why"] = ("no key columns survived (needs >= %.0f%% averaged bright "
                          "columns)" % (CF_KEY_COL * 100))
            return None, met

        # ---- 4. key rows + the solid-bar guard ----------------------------
        keyrows = np.zeros(h, bool)
        for hh in hits:
            keyrows[hh["y0"]:hh["y1"] + 1] = True
        bf = (g[:, cx0:cx1] >= lvl).mean(axis=1)
        bar = keyrows & (bf >= BAR_BRIGHT)
        n_bar = int(bar.sum())
        keyrows = keyrows & ~bar
        kr = np.where(keyrows)[0]
        met["key_rows"] = [int(kr.min()), int(kr.max())]
        met["n_key_rows"] = int(keyrows.sum())
        met["bar_bright_gate"] = BAR_BRIGHT
        met["bar_rows_dropped"] = n_bar
        met["bar_rows_bright"] = ([round(float(bf[bar].min()), 3),
                                   round(float(bf[bar].mean()), 3),
                                   round(float(bf[bar].max()), 3)] if n_bar else None)
        if keyrows.sum() < 30:
            met["why"] = ("only %d key rows survive the bar guard (need >= 30)"
                          % int(keyrows.sum()))
            return None, met

        # ---- 5. per-pixel mask in native coordinates ----------------------
        colmask = np.zeros(w, bool)
        for a, bb in segs:
            colmask[a:bb + 1] = True
        mask = (g >= lvl) & keyrows[:, None] & colmask[None, :]
        if mask.sum() < 200:
            met["why"] = "the key mask is essentially empty (%d px)" % int(mask.sum())
            return None, met
        ys, xs = np.where(mask)
        bx0, bx1 = int(xs.min()), int(xs.max()) + 1
        by0, by1 = int(ys.min()), int(ys.max()) + 1
        met["mask_bbox"] = [bx0, by0, bx1, by1]
        met["mask_frac_of_frame"] = round(float(mask.mean()), 4)

        # tilt from the mask's own top edge (least squares, per column).
        # Only the REGULAR keys are used: the connector head makes a wide blob
        # whose top edge is much higher, and it would bias the fit badly
        # (measured: -1.7 deg with it, -0.0 deg without).
        wmed = float(np.median([b - a + 1 for a, b in segs]))
        regular = [(a, b) for a, b in segs
                   if 0.6 * wmed <= (b - a + 1) <= 1.6 * wmed]
        met["key_width_median_px"] = round(wmed, 1)
        met["n_regular_keys"] = len(regular)
        topx, topy = [], []
        for a, b in regular:
            for x in range(max(a, bx0), min(b + 1, bx1)):
                col = np.where(mask[:, x])[0]
                if col.size:
                    topx.append(x)
                    topy.append(float(col[0]))
        fit = _robust_line(topx, topy)
        if fit is None:
            met["why"] = "cannot fit the key band's top edge"
            return None, met
        tilt_deg = float(np.degrees(np.arctan(fit[0])))
        met["tilt_deg"] = round(tilt_deg, 3)
        met["tilt_src"] = "least squares on the key band top edge"
        met["tilt_fit_px"] = round(fit[1], 2)
        met["tilt_span_px"] = int(max(topx) - min(topx))

        # ---- 6. crop, rotate upright, resize ------------------------------
        px0 = max(0, bx0 - CROP_PAD)
        py0 = max(0, by0 - CROP_PAD)
        px1 = min(w, bx1 + CROP_PAD)
        py1 = min(h, by1 + CROP_PAD)
        block = src[py0:py1, px0:px1].copy()
        mk = mask[py0:py1, px0:px1]
        block[~mk] = CANVAS_BG
        met["crop"] = [int(px0), int(py0), int(px1), int(py1)]
        met["crop_pad"] = int(CROP_PAD)
        met["crop_wh"] = [int(px1 - px0), int(py1 - py0)]

        rot = tilt_deg + float(deskew_deg)
        ctr = ((px1 - px0 - 1) / 2.0, (py1 - py0 - 1) / 2.0)
        up = _rotate(block, rot, ctr)
        met["rot_deg"] = round(rot, 4)
        keep_up = (up > 0).any(axis=2)

        ow = int(hw[0])
        sc = ow / float(max(1, up.shape[1]))
        oh = int(round(up.shape[0] * sc)) if hw[1] is None else int(hw[1])
        met["resize_scale_xy"] = [round(sc, 3), round(sc, 3)]
        if hw[1] is None and sc > MAX_UPSCALE_Y:
            met["why"] = ("vertical upscale %.2f > %.1f would smear the keys -- refusing"
                          % (sc, MAX_UPSCALE_Y))
            return None, met
        interp = cv2.INTER_AREA if sc < 1.0 else cv2.INTER_NEAREST
        upm = np.where(keep_up[:, :, None], up, np.uint8(0))
        out = np.ascontiguousarray(cv2.resize(upm, (ow, oh), interpolation=interp))
        if out.shape[0] < 3 or out.shape[1] < 3:
            met["why"] = "degenerate output size %r" % (out.shape,)
            return None, met

        # ---- 7. texture gate measured on the geometry (before the gain) ----
        gpre = _luma(out)
        gm = gpre > 0
        if gm.sum() > 50:
            hy_geo = float(np.abs(np.diff(gpre, axis=0))[gm[1:]].mean())
            vx_geo = float(np.abs(np.diff(gpre, axis=1))[gm[:, 1:]].mean())
        else:
            hy_geo = vx_geo = 0.0
        band_pre = g[by0:by1, bx0:bx1]
        hy_src = (float(np.abs(np.diff(band_pre, axis=0)).mean())
                  if band_pre.shape[0] > 1 else 0.0)
        met["edge_hy_src"] = round(hy_src, 2)
        met["edge_hy_geo"] = round(hy_geo, 2)
        met["edge_vx_geo"] = round(vx_geo, 2)
        met["edge_gate_min"] = EDGE_KEEP_MIN
        met["texture_gate"] = ("absolute gate on the full resolution source"
                               if w >= 1600 else
                               "source already downscaled: absolute gate reported "
                               "only, the no-flatten ratio is enforced")
        if w >= 1600 and hy_src < EDGE_KEEP_MIN:
            met["why"] = ("the source key band only carries a horizontal edge strength "
                          "of %.2f (< %.1f) -- texture already gone, refusing"
                          % (hy_src, EDGE_KEEP_MIN))
            return None, met
        if hy_src > 0 and hy_geo < 0.5 * hy_src:
            met["why"] = ("texture flattened by the pipeline: |dI/dy| %.2f in the "
                          "source -> %.2f after crop+resize (< 50%%)"
                          % (hy_src, hy_geo))
            return None, met

        # ---- 8. exposure last (so the gain cannot look like a loss of texture)
        if g_use is None or gm_use is None:
            if g_use is None:
                kp = _luma(upm)
                kv = kp[kp > 0]
                p99 = float(np.percentile(kv, 99)) if kv.size else 255.0
                g_use = float(np.clip(AUTO_PEAK / max(p99, 1.0), 0.15, 1.0))
            if gm_use is None:
                gm_use = DEFAULT_GAMMA
            met["exposure_auto"] = True
        else:
            met["exposure_auto"] = False
        out = _apply_exposure(out, g_use, gm_use)
        out[~((out > 0).any(axis=2))] = 0
        met["gain"] = round(float(g_use), 4)
        met["gamma"] = round(float(gm_use), 4)
        write_exposure_json(g_use, gm_use)

        # ---- 9. metrics ---------------------------------------------------
        go = _luma(out)
        met["out_size"] = [int(out.shape[1]), int(out.shape[0])]
        met["black_frac"] = round(float((out == 0).all(axis=2).mean()), 4)
        met["strip_sat_frac"] = round(float((go >= SAT_LEVEL).mean()), 4)
        met["strip_mean"] = round(float(go.mean()), 1)
        met["strip_median"] = round(float(np.median(go)), 1)
        nb = go[(out > 0).any(axis=2)]
        met["nonblack_mean"] = round(float(nb.mean()), 1) if nb.size else 0.0
        met["nonblack_frac"] = round(float((out > 0).any(axis=2).mean()), 4)
        met["tenengrad"] = round(_tenengrad(go), 1)
        met["clip_frac_raw"] = round(
            float((_luma(src[by0:by1, bx0:bx1]) >= SAT_LEVEL).mean()), 4)
        met["dynamic_range"] = [round(float(np.percentile(go, 2)), 1),
                                round(float(np.percentile(go, 98)), 1)]

        # independent rectangularity check on the delivered picture
        nzm = (out > 0).any(axis=2)
        first = np.full(out.shape[1], -1.0, np.float32)
        for x in range(out.shape[1]):
            idx = np.where(nzm[:, x])[0]
            if idx.size:
                first[x] = float(idx[0])
        vx = np.where(first >= 0)[0]
        if vx.size >= 40:
            f2 = _robust_line([int(x) for x in vx], [float(first[x]) for x in vx])
            if f2 is not None:
                span = max(1.0, float(vx.max() - vx.min()))
                noise = f2[1] / span * 1000.0
                met["top_edge_slope_px_per_1000"] = round(f2[0] * 1000.0, 3)
                met["top_edge_noise_px_per_1000"] = round(noise, 3)
                met["top_edge_fit_px"] = round(f2[1], 2)
                met["rectangular"] = bool(
                    abs(f2[0] * 1000.0) <= max(TILT_TOL_PX, 2.0 * noise))
        met["ok"] = True
        return out, met
    except Exception as exc:                                             # noqa: BLE001
        met["why"] = "judge render failed: %s" % exc
        import traceback
        traceback.print_exc()
        return None, met


if __name__ == "__main__":                                               # CLI probe
    import sys
    if len(sys.argv) < 2:
        print("usage: gold_judge_rect_v21.py <image> [out.png]")
        raise SystemExit(2)
    _img = cv2.imread(sys.argv[1])
    _out, _meta = render_judge_v21(_img)
    if _out is None:
        print("FAIL:", _meta.get("why"))
        raise SystemExit(2)
    _dst = sys.argv[2] if len(sys.argv) > 2 else "/tmp/gold_judge_v21.png"
    cv2.imwrite(_dst, _out)
    print("OK ->", _dst, _out.shape[1], "x", _out.shape[0])
    for _k in ("key_row_span", "strip_cols", "right_edge_x", "cut_right_px",
               "n_keys", "pitch_px", "width_mean_px", "bar_rows_dropped",
               "tilt_deg", "rot_deg", "black_frac", "strip_mean",
               "top_edge_slope_px_per_1000", "gain", "gamma"):
        print("  %-28s %s" % (_k, _meta.get(_k)))
