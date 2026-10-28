#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aoi_surface_rect.py — 侧面(10083)判据图「本机口径」: 搜索矩形刚体 → 转角度摆正 → 按真实尺寸裁剪

为什么要有这一层(2026-10-13 老倪: 「判据图还是显示原图, 不对」):
  工控机 10083 `GET /picture?kind=judge` 会**退化**: 程序没在画面里找到模块时, 它回的是
  `Surface_Letterbox_W1280_H1280_No_<n>.png` = 整幅 letterbox 规范图(而且可能是几小时前的旧图)。
  页面那格直通显示它 ⇒ 看起来就是"判据图=原图"。
  ⇒ 本机从 `kind=origin`(2448×2048 原图) 自己搜矩形 + 摆正 + 裁剪, 判据图口径由我们保证。

口径(与 `workpiece-crop-and-rectify` 技能一致):
  · 搜索: CLAHE(2.0,(8,8)) → GaussianBlur(5,5) → Otsu(前景>60% 时改 p80 分位保障)
          → close(15×15) + open(25×25) → 逐轮廓 得分=面积占比×矩形度(contourArea/minAreaRect面积)
          → 面积闸 [0.5%, 75%] → 择优 minAreaRect(boxPoints 天然平行)
  · 摆正: **纯旋转** getRotationMatrix2D(scale=1.0) + warpAffine + getRectSubPix(按检出真实尺寸)
          ⇒ 输出尺寸 == 检出尺寸(硬证没拉伸)
  · 宁缺勿假: 矩形度 < min_fill(默认 0.45) 或尺度不合理 ⇒ 不出图(返回 None + why), 由调用方回落原样,
          并把 why 写在图上(ASCII) —— 工件不在位时**不伪造**一块"规整矩形"充当判据图。

自检(每次返回都带, 可复核): 矩形度 / 面积占比 / 倾角 / 检出尺寸 / 输出尺寸 / 同像素亮度差。
"""
from __future__ import annotations

import cv2
import numpy as np

__all__ = ["surface_roi", "surface_judge", "overlay_box"]


def _prep(gray):
    clahe = cv2.createCLAHE(2.0, (8, 8))
    return cv2.GaussianBlur(clahe.apply(gray), (5, 5), 0)


def surface_roi(bgr, area_lo=0.005, area_hi=0.75, min_fill=0.45, keep_top=4, aspect_min=2.5):
    """在整幅画面里**搜索**矩形刚体(位置/角度每帧变, 不预先固定坐标)。

    返回 (rect, meta): rect = dict(cx,cy,w,h,angle,fill,area_frac) 或 None。
    """
    if bgr is None or bgr.size == 0:
        return None, {"ok": False, "why": "空帧"}
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
    H, W = g.shape[:2]
    e = _prep(g)
    thr, th = cv2.threshold(e, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    fg = float(np.mean(th > 0))
    mode = "otsu"
    if fg > 0.60:                       # 前景占多数 ⇒ Otsu 失效(把背景当工件) → p80 分位保障
        pv = float(np.percentile(e, 80))
        th = (e >= pv).astype(np.uint8) * 255
        mode = "p80"
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    th = cv2.morphologyEx(th, cv2.MORPH_OPEN, np.ones((25, 25), np.uint8))
    # 2026-10-20 侧面点2 实测: 光模块右端**插进右侧夹具**, 两者亮度相近且 x 相邻 ⇒ 轮廓粘成
    #   2080x1303 一块(aspect 1.70), 被 aspect 闸全挡掉 ⇒ n_cand=0, 判据图回退整幅(不水平+带夹具)。
    #   可分的物理特征: 夹具是**整列贯穿**(列亮>800px, 占 2048 高的 60%+), 模块只有 ~440px 高。
    #   ⇒ 按"贯穿列"找到夹具左界, 把 ROI 截到模块侧。好帧(o_sync)没有贯穿列 ⇒ 行为完全不变。
    _col = (g >= 180).astype(np.uint8).sum(axis=0)
    _below = _col > int(0.39 * H)
    _run = 0; _xc = W
    for _x in range(W):
        if _below[_x]:
            _run += 1
            if _run >= 60:                       # 连续 60 列都贯穿才算夹具(单个高光条不算)
                _xc = _x - _run + 1
                break
        else:
            _run = 0
    if _xc < W:
        # 截断后必须**换成严格阈值**重算: Otsu(91) 下模块与夹具连成整块, 光靠切 x 切不开;
        #   g>=180 只留金属高光, 模块独立成 1500x210 的长条(实测 asp 7.2 / fill 0.70, 全过闸)。
        th = ((g >= 180).astype(np.uint8) * 255)[:, :_xc]
        th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        th = cv2.morphologyEx(th, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        th = cv2.copyMakeBorder(th, 0, 0, 0, W - _xc, cv2.BORDER_CONSTANT, value=0)
    cs, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cands = []
    for c in cs:
        a = cv2.contourArea(c)
        af = a / float(H * W)
        if af < area_lo or af > area_hi:
            continue
        (_cx, _cy), (w, h), ang = cv2.minAreaRect(c)
        if w * h <= 0:
            continue
        fill = a / float(w * h)
        # 2026-10-20 搜索漂移修正: 光模块是**扁长**的(实测 5.97~6.82:1), 而台面/夹具接近方形(实测 1.88:1)。
        #   不加这道闸时, 48000us 下会搜到 2394x1274 的台面当刚体 ⇒ 摆正对着台面转, 判据图全错。
        asp = max(w, h) / float(max(1e-6, min(w, h)))
        if aspect_min > 0 and asp < aspect_min:
            # 2026-10-20 侧面点3 实测: 工件**竖着且顶部出画**时, 完整矩形搜不到;
            #   但"贴边竖条"本身很规整(minAreaRect fill 0.95, 长边 599, 短边 395)。
            #   ⇒ 不直接丢, 记成 vertical 候选; 只有主搜索全空时才启用, 摆正时自动转 90° 成水平。
            if fill >= 0.85 and min(w, h) >= 200 and max(w, h) >= 450:
                cands.append((0.0, dict(cx=float(_cx), cy=float(_cy), w=float(w), h=float(h),
                                        angle=float(ang), fill=float(fill), area_frac=float(af),
                                        aspect=float(asp), vertical=True)))
            continue
        cands.append((af * fill, dict(cx=float(_cx), cy=float(_cy), w=float(w), h=float(h),
                                      angle=float(ang), fill=float(fill), area_frac=float(af),
                                      aspect=float(asp))))
    cands.sort(key=lambda t: -t[0])
    meta = {"ok": False, "mode": mode, "n_cand": len(cands), "fg_frac": round(fg, 3), "shape": [int(H), int(W)],
            "bright_frac": round(float(np.mean(g >= 250)), 4), "p99": int(np.percentile(g, 99))}
    if not cands:
        meta["why"] = ("搜索不到候选矩形(面积闸 0.5%%~75%% + 长宽比≥%.1f 全不过) ⇒ 工件不在位/画面全暗"
                       % aspect_min)
        return None, meta
    best = cands[0][1]
    meta.update(best)
    if best["fill"] < min_fill:
        meta["why"] = "最优候选矩形度 %.2f < %.2f ⇒ 不是工件刚体(不画框/不出判据图)" % (best["fill"], min_fill)
        meta["top"] = [round(c[1]["fill"], 2) for c in cands[:keep_top]]
        return None, meta
    meta["ok"] = True
    return best, meta


def _profile_extent(gray, x0, x1, y0, y1, k=2.5, cap=0.40, band=None):
    """🔍 把检出框沿剖面**扩到刚体真实边界** —— 专治"少了光模块的头部"。

    真因(实测 2026-10-13): Otsu 只把**足够亮**的部分当刚体, 光模块头部/金属壳偏暗(实测剖面 39~50,
    背景电平 4) ⇒ 被切掉。

    门限**分轴**(实测教训: 一个 bg+2.5σ 门限会沿短轴把背景辉光也吃进来, 高度从 172 涨到 308):
      · 长轴(沿刚体长边) 用**相对门限** `bg + 0.08·(core−bg)` ⇒ 收得进偏暗的头部;
      · 短轴(横跨刚体) 用**高门限** `bg + 0.25·(core−bg)` ⇒ 只认刚体本身, 不吃辉光;
      · 每边扩展上限: 长轴 ≤25% 边长, 短轴 ≤15% 边长。
    core = 检出框内中位亮度。自检: 返回每边扩多少 px + 两个门限 + 背景/核心电平。
    """
    h, w = gray.shape[:2]
    x0, x1, y0, y1 = int(x0), int(x1), int(y0), int(y1)
    colp = gray[y0:y1, :].mean(axis=0)
    rowp = gray[:, x0:x1].mean(axis=1)
    core = float(np.median(gray[max(0, y0):y1, max(0, x0):x1]))
    out_c = np.r_[colp[:max(0, x0 - 60)], colp[min(w, x1 + 60):]]
    out_r = np.r_[rowp[:max(0, y0 - 60)], rowp[min(h, y1 + 60):]]
    bg = float(np.median(out_c)) if out_c.size else 0.0
    sd = float(np.std(out_c)) if out_c.size else 0.0
    thr_long = max(6.0, bg + 0.08 * (core - bg), bg + 2.0 * sd * 0.5)
    thr_short = max(8.0, bg + 0.25 * (core - bg), bg + k * sd)
    cw, ch = x1 - x0, y1 - y0
    dl = dr = dt = db = 0
    cap_lr = max(4, int(0.25 * cw))
    cap_tb = max(3, int(0.15 * ch))
    while dl < cap_lr and x0 - dl - 1 >= 0 and colp[x0 - dl - 1] > thr_long:
        dl += 1
    while dr < cap_lr and x1 + dr + 1 < w and colp[x1 + dr + 1] > thr_long:
        dr += 1
    while dt < cap_tb and y0 - dt - 1 >= 0 and rowp[y0 - dt - 1] > thr_short:
        dt += 1
    while db < cap_tb and y1 + db + 1 < h and rowp[y1 + db + 1] > thr_short:
        db += 1
    return dl, dr, dt, db, {"bg": round(bg, 1), "bg_std": round(sd, 1), "core": round(core, 1),
                            "thr_long": round(thr_long, 1), "thr_short": round(thr_short, 1),
                            "grow_px": [dl, dr, dt, db], "grow_cap_px": [cap_lr, cap_lr, cap_tb, cap_tb]}


def surface_judge(bgr, out_long=None, min_fill=0.45, return_overlay=True, expand=True):
    """搜索 → **纯旋转摆正** → 按真实像素尺寸裁剪。返回 (crop|None, overlay|None, meta)。

    overlay = 原图 + 绿框 + 四角 A/B/C/D + `crop area: WxH tilt θ°` (ASCII), 供"整板原图"那格对照。
    """
    rect, meta = surface_roi(bgr, min_fill=min_fill)
    ov = overlay_box(bgr, rect, meta) if return_overlay else None
    if rect is None:
        return None, ov, meta
    h, w = bgr.shape[:2]
    ang = rect["angle"]
    # 统一把 minAreaRect 的尺寸/角度写成「宽>=高」
    bw, bh, a = rect["w"], rect["h"], ang
    if bw < bh:
        bw, bh = bh, bw
        a += 90.0
    M = cv2.getRotationMatrix2D((rect["cx"], rect["cy"]), a, 1.0)          # scale=1.0 ⇒ 零拉伸
    rot = cv2.warpAffine(bgr, M, (w, h), flags=cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
    cw, ch = int(round(bw)), int(round(bh))
    ecx, ecy = float(rect["cx"]), float(rect["cy"])
    if expand:                     # 🆕 扩到刚体真实边界(治"少了头部": 暗的头部被 Otsu 切掉)
        _rg = cv2.cvtColor(rot, cv2.COLOR_BGR2GRAY) if rot.ndim == 3 else rot
        dl, dr, dt, db, einfo = _profile_extent(_rg, ecx - cw / 2.0, ecx + cw / 2.0,
                                                ecy - ch / 2.0, ecy + ch / 2.0)
        meta["expand"] = einfo
        if dl or dr or dt or db:
            nw, nh = cw + dl + dr, ch + dt + db
            ecx += (dr - dl) / 2.0
            ecy += (db - dt) / 2.0
            cw, ch = nw, nh
    crop = cv2.getRectSubPix(rot, (cw, ch), (ecx, ecy))
    if crop is None:
        meta["why"] = "旋转后取图失败"
        meta["ok"] = False
        return None, ov, meta
    # 自检: 同帧同像素 (把裁剪区在原图上按矩形取回, 比亮度)
    try:
        box = cv2.boxPoints(((rect["cx"], rect["cy"]), (rect["w"], rect["h"]), rect["angle"]))
        mask = np.zeros((h, w), np.uint8)
        cv2.fillPoly(mask, [np.int32(box)], 255)
        src = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        d = float(np.mean(src[mask > 0])) - float(np.mean(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)))
        meta["same_pixel_mean_diff"] = round(d, 3)
    except Exception:                                                             # noqa: BLE001
        meta["same_pixel_mean_diff"] = None
    meta["crop_size"] = [cw, ch]
    # 🔧 2026-10-19 老倪「保留整块模块」: 旧判据 `cw == round(rect.w|h)` 把"扩暗头"误判成拉伸
    #   (扩的像素是 thr_long 阈值判定属于模块、getRectSubPix 1:1 取出的真实像素, 没有插值)。
    #   真拉伸只发生在 resize 时 ⇒ 判据改为「输出尺寸 == 裁剪尺寸」; 扩了多少单列 expand_px。
    meta["out_size"] = [int(crop.shape[1]), int(crop.shape[0])]
    meta["crop_size_raw"] = [cw, ch]
    meta["no_stretch"] = bool(meta["out_size"] == [cw, ch] and "resize" not in str(meta.get("notes", "")))
    meta["expand_px"] = [cw - int(round(rect["w"])), ch - int(round(rect["h"]))]
    if out_long and max(crop.shape[:2]) > out_long:
        s = out_long / float(max(crop.shape[:2]))
        crop = cv2.resize(crop, (int(crop.shape[1] * s), int(crop.shape[0] * s)), interpolation=cv2.INTER_AREA)
        meta["scaled_to"] = [int(crop.shape[1]), int(crop.shape[0])]
        meta["no_stretch"] = False      # 走了 resize ⇒ 有插值, 这才是真拉伸
    return crop, ov, meta


def overlay_box(bgr, rect, meta=None):
    """原图 + 搜索到的矩形(绿框 + 四角 + ASCII 标注)。找不到则只写原因。"""
    out = bgr.copy()
    h, w = out.shape[:2]
    font, fs, col = cv2.FONT_HERSHEY_SIMPLEX, max(0.7, max(h, w) / 2200.0), (0, 255, 0)
    if rect is not None:
        box = cv2.boxPoints(((rect["cx"], rect["cy"]), (rect["w"], rect["h"]), rect["angle"]))
        pts = np.int32(box)
        cv2.polylines(out, [pts], True, col, 4)
        for i, p in enumerate(box):
            cv2.circle(out, tuple(int(v) for v in p), 9, (0, 200, 255), -1)
            cv2.putText(out, "ABCD"[i], (int(p[0]) + 12, int(p[1]) - 12), font, fs, (0, 200, 255), 3)
        cv2.putText(out, "crop area: %dx%d tilt %.1f deg  fill %.2f  area %.1f%%" % (
            int(round(rect["w"])), int(round(rect["h"])), rect["angle"], rect["fill"],
            100 * rect["area_frac"]), (40, 70), font, fs, col, 3)
    else:
        why = (meta or {}).get("why", "no rectangle found")
        cv2.putText(out, "NO RECT: %s" % str(why)[:70].encode("ascii", "ignore").decode(), (40, 70), font, fs,
                    (0, 165, 255), 3)
    return out


if __name__ == "__main__":
    import sys

    _KEYS = ("ok", "why", "fill", "area_frac", "angle", "crop_size", "out_size",
             "no_stretch", "same_pixel_mean_diff", "n_cand", "mode")
    for f in sys.argv[1:]:
        im = cv2.imread(f)
        cr, ov, m = surface_judge(im, out_long=1400)
        print("%s ⇒ %s" % (f, {k: v for k, v in m.items() if k in _KEYS}))
