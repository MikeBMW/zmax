# -*- coding: utf-8 -*-
"""Build cam_finger_10082_work_v34.py from v33 by porting v32's render-path additions.
Every insertion asserts the anchor is unique and present exactly once."""
import io, sys

SRC = "/home/ubuntu/zmax/tools/aoi/cam_finger_10082_work_v33.py"
DST = "/home/ubuntu/zmax/tools/aoi/cam_finger_10082_work_v34.py"
V32 = "/home/ubuntu/zmax/tools/aoi/_wip/cam_finger_10082_work_v32.py"

s = io.open(SRC, encoding="utf-8").read()

# ---- extract v32 blocks verbatim -----------------------------------------
v32 = io.open(V32, encoding="utf-8").read()

def slice_between(text, start, end, inclusive_end=False):
    i = text.index(start)
    j = text.index(end, i)
    return text[i: j + (len(end) if inclusive_end else 0)]

anchor_block = slice_between(v32,
    "# ═══ v32 (2026-10-09) 几何自适应取带",
    "def _v21_key_windows(g, lvl):").rstrip() + "\n"
slot_block = slice_between(v32,
    "def _v32_slot_filter(ctr, luma, ky0, ky1, pitch):",
    "def _v21_uniformize(").rstrip() + "\n"
drawbox_block = slice_between(v32,
    "def _v31_draw_boxes(img, met, hw, color=(0, 255, 0), thick=2):",
    "def _v31_overlay_banner(").rstrip() + "\n"

def ins(text, anchor, insert, after=True, occurrences=1):
    n = text.count(anchor)
    assert n == occurrences, "anchor count %d != %d for %r" % (n, occurrences, anchor[:60])
    if after:
        return text.replace(anchor, anchor + insert, 1)
    return text.replace(anchor, insert + anchor, 1)

def rep(text, old, new):
    n = text.count(old)
    assert n == 1, "replace anchor count %d for %r" % (n, old[:60])
    return text.replace(old, new, 1)

# 1) anchor-band block (consts + _v32_* funcs) after _v26_pick_band, before _v21_key_windows
s = ins(s, "def _v21_key_windows(g, lvl):",
        anchor_block + "\n\n", after=False)

# 2) _v32_slot_filter before _v21_uniformize
s = ins(s, "def _v21_uniformize(segs, cf=None, cx0=0):",
        slot_block + "\n\n", after=False)

# 3) _v21_uniformize signature + luma params
s = rep(s, "def _v21_uniformize(segs, cf=None, cx0=0):",
           "def _v21_uniformize(segs, cf=None, cx0=0, luma=None, luma_rows=None):")

# 4) slot filter call inside _v21_uniformize, just before rects build
s = ins(s,
    '        info["lattice_note"] = "no regular pitch (fewer than 2 reliable keys)"\n',
    '    # 🆕 v34 (移植 v32): 去掉"不参与节距周期"的边缘槽(连接器两端金属边条) —— 只截边, 内部不删\n'
    '    if _V32_ON and luma is not None and luma_rows is not None:\n'
    '        _ctr32, _f32 = _v32_slot_filter(ctr, luma, luma_rows[0], luma_rows[1], med_gap)\n'
    '        if _f32 is not None:\n'
    '            info["v32_slot_filter"] = _f32\n'
    '            ctr = _ctr32\n')

# 5) render_core: _v32_filt after band pick
s = ins(s,
    "            ky0, ky1 = _v26_pick_band(hits, met, thumb=_thumb)\n",
    "        # 🆕 v34 (移植 v32): 端点有效性过滤**只在显式指定带时启用**(= 两遍校验的 pass2);\n"
    "        #    pass1(band=None) ⇒ 一字不动 ⇒ 与 v33 逐位一致(参考序列零回退由结构保证)。\n"
    "        _v32_filt = bool(_V32_ON and band is not None)\n"
    "        met[\"v32_filt\"] = bool(_v32_filt)\n")

# 6) render_core: uniformize call conditional
s = rep(s,
    "        rects, uinfo = _v21_uniformize(segs, cf=cf, cx0=cx0)\n",
    "        if _v32_filt:\n"
    "            rects, uinfo = _v21_uniformize(segs, cf=cf, cx0=cx0, luma=ga, luma_rows=(ky0, ky1))\n"
    "        else:\n"
    "            rects, uinfo = _v21_uniformize(segs, cf=cf, cx0=cx0)\n")

# 7) render_judge: two-pass before return
twopass = '''    # 🆕 v34 (移植 v32 两遍校验): 只在 pass1 明显不对(数太少 <12 根, 或比 19 还多)且存在强周期锚点带时,
    #   用锚点带重渲一遍; 重渲结果**恰好 19** 才采用, 否则原样保留 ⇒ pass1 已 15~19 的视角逐位不变。
    _n1v = int(met.get("n_keys") or 0)
    if _V32_ON and _V32_TWOPASS_ON and (_n1v < _V32_ATTEMPT_LO or _n1v > _V31_N_TARGET):
        try:
            _g2 = _v25_norm_luma(_v21_luma(np.asarray(bgr)))
            _an = _v32_anchor_band(_g2)
        except Exception:                                                   # noqa: BLE001
            _an = None
        if _an is not None:
            _ay0, _ay1, _apitch, _ascore = _an
            _b0 = met.get("key_rows") or met.get("kept_rows")
            if _ascore >= _V32_AC_MIN:
                _i2, _m2 = _v21_render_core(bgr, deskew_deg=deskew_deg, hw=_hw,
                                            band=(int(_ay0), int(_ay1)))
                _m2 = dict(_m2 or {})
                if _i2 is not None and int(_m2.get("n_keys") or 0) == _V31_N_TARGET:
                    _m2["out"] = _m2.get("out_size")
                    _m2["kept_rows"] = _m2.get("key_rows")
                    _m2["kept_h"] = _m2.get("n_key_rows")
                    _m2["dropped_sat_rows"] = _m2.get("bar_rows_dropped")
                    _bh2 = max(1, int(_m2.get("band_h") or 1))
                    _m2["dropped_pct"] = round(100.0 * int(_m2.get("bar_rows_dropped") or 0) / _bh2, 1)
                    _m2["sat_after"] = _m2.get("strip_sat_frac")
                    _sx2 = _m2.get("strip_x") or [0, 0]
                    _m2["x_trim"] = {"trimmed": True, "x_span": [int(_sx2[0]), int(_sx2[1])],
                                     "dropped_cols": ([0, int(_sx2[0])] if _sx2[0] else []),
                                     "col_sat_before_max": None,
                                     "rule": "v21 strip columns (horizontal edge strength |dI/dy|)"}
                    _m2["k"] = float(k)
                    _m2["fix_hw"] = [int(_hw[0]), int(_hw[1])]
                    _m2["v32_twopass"] = {"from": _b0, "to": [int(_ay0), int(_ay1)],
                                          "score": round(float(_ascore), 3),
                                          "first_n": int(met.get("n_keys") or 0)}
                    _m2["v32_autocorr"] = {"band": [int(_ay0), int(_ay1)], "pitch": round(float(_apitch), 1),
                                           "score": round(float(_ascore), 3)}
                    _m2.setdefault("err", "")
                    img, met = _i2, _m2
    return img, met
'''
s = rep(s,
    '    met["k"] = float(k)\n    met["fix_hw"] = [int(_hw[0]), int(_hw[1])]\n    return img, met\n',
    '    met["k"] = float(k)\n    met["fix_hw"] = [int(_hw[0]), int(_hw[1])]\n' + twopass)

# 8) add _v31_draw_boxes before render_judge_gated
s = ins(s, "def render_judge_gated(bgr, deskew_deg=0.0, hw=_JUDGE_HW, k=_JR_K):",
        drawbox_block + "\n\n", after=False)

# 9) gated shown branch draws boxes
s = rep(s,
    "    if state == \"shown\" and img is not None:\n        out = img\n",
    "    if state == \"shown\" and img is not None:\n"
    "        # 🆕 v34: 19 根 ⇒ 画面 = 真判据图 + **实线框**(框住每一根金手指); 画框失败则原样返回\n"
    "        out = _v31_draw_boxes(img, met, _hw, color=(0, 255, 0), thick=2)\n")

# 10) version string
s = rep(s,
    '_JUDGE_VER = "v33-gold19-gate-keepframe-20261009"',
    '_JUDGE_VER = "v34-gold19-anchor-20261009"')
# also update the trailing comment for the version
s = rep(s,
    '   # v33: 修 v31 渲染门"整张不显示"缺陷 —— 抑制时**保留画面**+顶部横幅(绝不黑屏)',
    '   # v34: v33 + 列自相关"相位锚点"取带 + 两遍重切分(锚点带重渲, 恰好19才采用) + 端点有效性门(只切边);\n'
    '   #      v33 的 keep-frame 抑制分支保留; 19 根时画实线框')

io.open(DST, "w", encoding="utf-8").write(s)
print("wrote", DST, len(s.splitlines()), "lines")
