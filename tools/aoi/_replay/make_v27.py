# -*- coding: utf-8 -*-
"""把 v26 的平场齿列切分(_v26_teeth_cols 核心段)换成 v27 稳健版 + 齿列栅格锁。
只在 scratch 副本上做, 验证通过后再落到两处正式文件。
用法: python make_v27.py <src> <dst>"""
import sys, io

SRC, DST = sys.argv[1], sys.argv[2]
s = io.open(SRC, "r", encoding="utf-8").read()

# ── 1) 新增常量 ──
anchor = "_V26_FF_MERGE = 40          # 平场峰合并间距(px): 比它近的峰视为同一根齿的裂峰, 取更高者"
assert anchor in s, "anchor const not found"
new_consts = anchor + """
# 🆕 v27 (2026-10-09 点2 逐根恒定): 实测(aoi_frozen 10 帧)旧版三个量逐帧翻 ——
#   ① 合并门 40px 正好骑在"齿+耳"裂峰(40~42px)边界 ⇒ merged 22↔23;
#   ② 节距取"相邻峰间距中位"被耳峰/左端边缘峰污染 ⇒ 70.5↔72;
#   ③ 齿宽取"全体亮run中位"被边缘run污染 ⇒ 21↔22; 相位锚 peaks[0](噪声峰) ⇒ 整条栅格逐帧平移。
#   修: 节距迭代裁剪中位 + 按"实测节距比例"合并裂峰 + 最长规则链定节距(长基线) + 相位锚链首 +
#       齿宽只取含栅格中心的run并量化; 再加【齿列栅格锁】(与已上线的键行带锁 _V21_BAND_PREV 同法)。
_V26_FF_EAR = 0.55       # v27: 齿+耳 裂峰合并比(×实测节距)
_V26_FF_WQ = 2           # v27: 齿宽量化步(px)
_V26_LAT_LOCK_ON = True  # v27: 齿列栅格锁开关(False = 纯单帧, 用于对照)
_V26_LAT_LOCK = {}       # v27: {(视角签名): (m, ph, x_lo, x_hi, w)}
_V26_LAT_LOCK_KEEP = 4   # 最多保留几个视角桶"""
s = s.replace(anchor, new_consts, 1)

# ── 2) 视角签名 helper ──
reg_anchor = "def _v26_reg_of(segs):"
assert reg_anchor in s
s = s.replace(reg_anchor, """def _v26_lat_sign(x0, x1):
    \"\"\"齿列栅格锁的"视角签名" = 条带宽粗桶。前视条带 ~1500(桶11)vs 点2 满幅 ~2448(桶19) ⇒ 天然分开;
    不同的点2 姿态条带都满幅(同桶) ⇒ 靠"绝对 x 重叠"判同/异(异姿态 ⇒ 不重叠 ⇒ 自动重锁)。安全。\"\"\"
    try:
        return int((int(x1) - int(x0)) // 128)
    except Exception:                                                       # noqa: BLE001
        return None


""" + reg_anchor, 1)

# ── 3) 替换核心段 ──
old = """    # 合并过近的峰(取更高者), 再用节距栅格滤掉离格峰
    peaks = [p for p in peaks if xa < p < xb]
    if len(peaks) < 5:
        return [], {"v26b": False, "v26b_note": "too few flat-field peaks (%d)" % len(peaks)}
    peaks.sort()
    merged = []
    for p in peaks:
        if merged and p - merged[-1] < _V26_FF_MERGE:
            if nrm[p] > nrm[merged[-1]]:
                merged[-1] = p
        else:
            merged.append(p)
    peaks = merged
    if len(peaks) < 5:
        return [], {"v26b": False, "v26b_note": "too few flat-field peaks after merge"}
    d = np.diff(peaks)
    m = float(np.median(d))
    if not (_V26_FF_PMIN <= m <= _V26_FF_PMAX):
        return [], {"v26b": False, "v26b_note": "implausible pitch %.1f" % m}
    lat = _v26_lattice(peaks, m)
    if len(lat) < 5:
        return [], {"v26b": False, "v26b_note": "lattice collapsed"}
    dl = np.diff(lat)
    reg = float(np.mean((dl >= 0.6 * m) & (dl <= 1.5 * m)))
    # 缺格补齐: [首齿..末齿] 之间按实测节距/相位逐格补(细金手指连续, 中间不该空格)
    pk0 = float(lat[0])
    ph = float(np.median([p - round((p - pk0) / m) * m for p in lat]))
    k0 = int(np.round((lat[0] - ph) / m))
    k1 = int(np.round((lat[-1] - ph) / m))
    centers = [ph + k * m for k in range(k0, k1 + 1)]
    # 齿宽 = 本帧实测的「亮run宽」中位, 夹在 0.30~0.66×节距(防相邻粘连, 量纲自适应)
    runs_w = [b - a + 1 for a, b in runs]
    runs_w = [w for w in runs_w if w >= 3]
    w_tooth = int(round(min(max(float(np.median(runs_w)) if runs_w else 0.5 * m, 0.30 * m), 0.66 * m)))
    w_tooth = max(3, w_tooth)
    segs = []
    for c in centers:
        a = int(round(c - w_tooth / 2.0))
        segs.append((int(a + x0), int(a + w_tooth - 1 + x0)))
    info = {"v26b": True, "v26b_pitch": round(m, 1), "v26b_reg": round(reg, 2),
            "v26b_n": len(segs), "v26b_tooth_w": w_tooth, "v26b_bg_k": _V26_FF_BG_K,
            "v26b_thr": round(float(thr), 4), "v26b_rows": _nkept,
            "v26b_note": "flat-field(non-sat rows) + adaptive pitch lattice"}
    return segs, info"""

new = '''    # ── v27: 稳健节距/相位 + 齿列栅格锁 (全部用"本帧实测", 不写死前视几何) ──────────
    #   ① 节距: 相邻间距迭代裁剪中位(剔掉 0.75× 以下的"耳"间距); ② 合并 <0.55×节距 的裂峰(齿+耳);
    #   ③ 最长规则链两端跨度/(格数-1) 当节距(长基线抗噪); ④ 相位锚规则链首; 峰按栅格对齐(|残差|≤0.30×节距)定跨度;
    #   ⑤ 齿宽只取"含栅格中心"的亮run中位并量化; ⑥ 齿列栅格锁 ⇒ 单帧噪声撑不动整列齿; 估计失败时用锁救回。
    peaks = [p for p in peaks if xa < p < xb]
    _vsign = _v26_lat_sign(x0, x1)
    _lock = _V26_LAT_LOCK.get(_vsign)

    def _v26_w_of(centers, mm):
        wr = []
        for _a, _b in runs:
            for _c in centers:
                if _a - 1 <= _c <= _b + 1:
                    wr.append(_b - _a + 1)
                    break
        wr = [w for w in wr if w >= 3]
        wmed = float(np.median(wr)) if wr else 0.5 * mm
        ww = int(round(wmed / _V26_FF_WQ)) * _V26_FF_WQ
        return max(3, int(min(max(ww, 0.30 * mm), 0.66 * mm)))

    def _v26_robust(pk):
        """稳健齿列: 返回 (m, ph, k0, k1, w_tooth, reg) 或 None。"""
        pk = sorted(int(p) for p in pk)
        if len(pk) < 5:
            return None
        dd = np.diff(pk).astype(np.float64)
        dd = dd[(dd >= _V26_FF_PMIN) & (dd <= _V26_FF_PMAX)]
        if dd.size < 3:
            return None
        m0 = float(np.median(dd))
        for _ in range(5):
            core = dd[(dd >= 0.75 * m0) & (dd <= 1.30 * m0)]
            if core.size < 3:
                break
            nm = float(np.median(core))
            if abs(nm - m0) < 0.05:
                m0 = nm
                break
            m0 = nm
        merged = []
        for p in pk:
            if merged and p - merged[-1] < _V26_FF_EAR * m0:
                if nrm[p] > nrm[merged[-1]]:
                    merged[-1] = p
            else:
                merged.append(p)
        if len(merged) < 5:
            return None
        b_i = b_j = 0
        i = 0
        while i < len(merged):
            jj = i
            while jj + 1 < len(merged) and 0.72 * m0 <= merged[jj + 1] - merged[jj] <= 1.28 * m0:
                jj += 1
            if (jj - i) > (b_j - b_i):
                b_i, b_j = i, jj
            i = (jj + 1) if jj > i else i + 1
        run = merged[b_i:b_j + 1]
        if len(run) < 4:
            return None
        mm = (run[-1] - run[0]) / float(len(run) - 1)
        if not (_V26_FF_PMIN <= mm <= _V26_FF_PMAX):
            return None
        ph = float(run[0])
        onlat = [p for p in merged if abs((p - ph) - round((p - ph) / mm) * mm) <= 0.30 * mm]
        if len(onlat) < 4:
            return None
        k0 = int(round((onlat[0] - ph) / mm))
        k1 = int(round((onlat[-1] - ph) / mm))
        _re = np.diff(run).astype(np.float64)
        reg = float(np.mean((_re >= 0.72 * mm) & (_re <= 1.28 * mm))) if _re.size else 0.0
        ww = _v26_w_of([ph + k * mm for k in range(k0, k1 + 1)], mm)
        return (float(mm), float(ph), int(k0), int(k1), int(ww), float(reg))

    _c = _v26_robust(peaks)
    _used_lock = False
    _rescued = False
    _reg = 0.0
    if _c is not None:
        m, ph, k0, k1, w_tooth, _reg = _c
        _c_lo, _c_hi = ph + k0 * m, ph + k1 * m
        if _V26_LAT_LOCK_ON and _lock is not None:
            _lm, _lph, _llo, _lhi, _lw = _lock
            _ov = min(_c_hi, _lhi) - max(_c_lo, _llo)
            _mn = min(_c_hi - _c_lo, _lhi - _llo)
            if _mn > 0 and _ov >= 0.5 * _mn and abs(m - _lm) <= 1.5:
                m, ph, _c_lo, _c_hi, w_tooth = _lm, _lph, _llo, _lhi, _lw
                _used_lock = True
        if not _used_lock:
            if len(_V26_LAT_LOCK) >= _V26_LAT_LOCK_KEEP:
                _V26_LAT_LOCK.clear()
            _V26_LAT_LOCK[_vsign] = (float(m), float(ph), float(_c_lo), float(_c_hi), int(w_tooth))
        k0 = int(round((_c_lo - ph) / m))
        k1 = int(round((_c_hi - ph) / m))
        centers = [ph + k * m for k in range(k0, k1 + 1)]
    elif _V26_LAT_LOCK_ON and _lock is not None:
        # 稳健估计失败(键行带翻到另一区/对比太低) ⇒ 本视角已有锁就沿用(救回出图, 不端空图/不塌成3根)
        m, ph, _c_lo, _c_hi, w_tooth = _lock
        _used_lock = True
        _rescued = True
        k0 = int(round((_c_lo - ph) / m))
        k1 = int(round((_c_hi - ph) / m))
        centers = [ph + k * m for k in range(k0, k1 + 1)]
    else:
        return [], {"v26b": False, "v26b_note": "no robust tooth lattice"}
    segs = []
    for c in centers:
        a = int(round(c - w_tooth / 2.0))
        segs.append((int(a + x0), int(a + w_tooth - 1 + x0)))
    info = {"v26b": True, "v26b_pitch": round(m, 1), "v26b_reg": round(_reg, 2),
            "v26b_n": len(segs), "v26b_tooth_w": int(w_tooth), "v26b_bg_k": _V26_FF_BG_K,
            "v26b_lat_lock": bool(_used_lock), "v26b_rescued": bool(_rescued), "v26b_vsign": _vsign,
            "v26b_thr": round(float(thr), 4), "v26b_rows": _nkept,
            "v26b_note": "flat-field(non-sat rows) + robust pitch/lattice + lock"}
    return segs, info'''

assert old in s, "core block not found"
assert s.count(old) == 1, "core block not unique: %d" % s.count(old)
s = s.replace(old, new, 1)

io.open(DST, "w", encoding="utf-8").write(s)
print("wrote", DST, len(s), "bytes")
