# -*- coding: utf-8 -*-
"""表面 10083 —— 本机重算 (AOI 算法层)。

与金手指不同: 表面这一路是**同一份 surface_judge 在本机重算** ——
取工控机 10083 的同一帧 → 搜矩形刚体 → 摆正(保留整块模块·长边水平·零插值) → 量光学质量。
实现同源: policies/yolo_3d/surface_optical.py → tools/aoi_surface_rect.py
(与交付判据图同一个 surface_judge, 绝不另写一套口径)。

🔴 ROI 口径: 模块摆正后单独统计, **不看整帧 mean** —— 黑背景会把整帧 mean 拉到 16,
   而模块本身仍在过曝(实测 5000us: 整帧 mean 16.25/暗部 94.7%, 模块 mean 153.9/死白 16.68%)。
"""
from __future__ import annotations

import os
import time as _t

_DOWN_UNTIL = 0.0
PORT = 10083


def surface_bypass(log=None, cache=None, publish=None, host=None):
    """取 10083 一帧 → 本机判据 → dict + 话题。10083 不可达只降级, 不影响金手指那一路。"""
    global _DOWN_UNTIL
    try:
        import socket as _sock
        if cache is None:
            cache = {}
        if _t.time() < _DOWN_UNTIL:
            _c = {"ok": False, "verdict": "unavailable",
                  "why": "10083 已知不可达 (冷却中, 不重复探)", "cached_down": True}
            cache["surface_aoi"] = _c
            return _c
        _host = host or os.environ.get("ZMAX_AOI_SURFACE_HOST", "192.168.23.23")
        try:
            _sock.create_connection((_host, PORT), timeout=0.25).close()
        except OSError as _e:
            _DOWN_UNTIL = _t.time() + 60.0
            _c = {"ok": False, "verdict": "unavailable",
                  "why": f"{_host}:{PORT} 不可达 ({type(_e).__name__}), 60s 内不再探",
                  "cached_down": True}
            cache["surface_aoi"] = _c
            if log:
                log(f"🌑 表面 {PORT} 旁路: {_c['why']} — 金手指主路不受影响")
            return _c
        from lerobot.policies.yolo_3d.surface_optical import SurfaceOpticalQuality
        sq = SurfaceOpticalQuality()
        sres = sq.run()
        cache["surface_aoi"] = sres
        ssig = sq.signals(sres)
        if ssig and publish:
            publish(ssig, log)
        if log:
            _m = {"ok": "✅", "too_dark": "🌑", "overexposed": "🔴", "shape_fail": "❔"}.get(
                sres.get("verdict"), "❔")
            _mod = sres.get("module") or {}
            _full = sres.get("full") or {}
            _rect = sres.get("rect") or {}
            if sres.get("ok"):
                log(f"{_m} 表面 {PORT} 旁路: {sres.get('verdict')} — {sres.get('verdict_why')}")
                log(f"   模块摆正 {sres.get('judge_shape')} 水平={_mod.get('long_edge_horizontal')} "
                    f"长宽比={_mod.get('aspect')} 倾角={_rect.get('angle')} 矩形度={_rect.get('fill')}")
                log(f"   ROI 口径: 模块 mean={_mod.get('mean')} 死白={_mod.get('sat_pct')}% "
                    f"清晰度={_mod.get('sharpness')}  |  整帧 mean={_full.get('mean')} "
                    f"死白={_full.get('sat_pct')}% 暗部={_full.get('dark_pct')}% (整帧会被黑背景拉低, 判决看 ROI)")
            else:
                log(f"{_m} 表面 {PORT} 旁路: 未出图 — {sres.get('why')}")
            if ssig:
                log(f"   表面光学话题已发出 ({len(ssig)} 个): "
                    + " · ".join("%s=%g" % (k.split(".")[-1], v) for k, v in sorted(ssig.items())))
        return sres
    except Exception as e:                                            # noqa: BLE001
        if log:
            log(f"⚠️ 表面 {PORT} 旁路失败 (不影响金手指): {type(e).__name__}: {e}")
        return None
