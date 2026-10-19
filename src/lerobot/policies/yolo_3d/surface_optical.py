#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""surface_optical.py — 10083 表面相机的**旁路**光学质量检测 (跑在 4060 本机, 不动工控机程序)

为什么叫旁路 (老倪 2026-10-19: 「10083服务, 可以在4060上旁路运行」):
  工控机 192.168.23.23:10083 只管取像 + 出它自己的判据图(会退化成 fallback_letterbox)。
  本机(4060) 通过 HTTP `GET /picture?kind=origin&grab=1` 拿同一帧, 自己搜矩形刚体 → 摆正 → 量质量。
  ⇒ 不部署、不改产线、不抢相机独占; 工控机停了这边也只是取不到帧, 不影响产线。

判据图口径 (老倪逐条定过):
  · 光模块水平放置: 长边在 x 轴 (minAreaRect 后若 w<h 则再转 90°)
  · 保留整块模块: expand=True 把 Otsu 切掉的暗头按 thr_long 阈值纳回 (expand_px 单列, 不混进拉伸)
  · 零拉伸: 只 getRotationMatrix2D(scale=1.0) + getRectSubPix(真实尺寸); 只有 resize 才算拉伸
  · 亮度一致: 同一帧取几何与像素, 不跨帧
复用 `tools/aoi_surface_rect.py::surface_judge` —— 与交付图同一个实现, 不另写一套口径。
"""
from __future__ import annotations

import importlib.util
import json
import os
import time
import urllib.request

import cv2
import numpy as np

__all__ = ["SurfaceOpticalQuality", "SURFACE_URL"]

SURFACE_URL = os.environ.get("ZMAX_SURFACE_AOI_URL", "http://192.168.23.23:10083")
_UA = {"User-Agent": "zmax-surface-optical"}
_RECT_MOD = None


def _rect_mod():
    """加载 tools/aoi_surface_rect.py (与交付判据图同一个实现)。"""
    global _RECT_MOD
    if _RECT_MOD is not None:
        return _RECT_MOD
    # 向上找含 tools/aoi_surface_rect.py 的根 (不数层数, 搬目录也不会断)
    root = os.path.dirname(os.path.abspath(__file__))
    while root != os.path.dirname(root) and not os.path.exists(
            os.path.join(root, "tools", "aoi_surface_rect.py")):
        root = os.path.dirname(root)
    path = os.path.join(root, "tools", "aoi_surface_rect.py")
    if not os.path.exists(path):
        raise FileNotFoundError("找不到 tools/aoi_surface_rect.py (从 %s 向上找过)" % os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location("aoi_surface_rect", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _RECT_MOD = mod
    return mod


class SurfaceOpticalQuality:
    """10083 表面旁路: 取帧 → 摆正(保留整块·长边水平·零插值) → 光学质量指标 → 判决。"""

    URL = SURFACE_URL

    def __init__(self, url: str | None = None, timeout: float = 12.0):
        self.url = (url or self.URL).rstrip("/")
        self.timeout = timeout
        self.last = {}

    # ── 取像 ────────────────────────────────────────────────────────────
    def _get(self, path: str, timeout: float | None = None) -> bytes:
        req = urllib.request.Request(self.url + path, headers=_UA)
        return urllib.request.urlopen(req, timeout=timeout or self.timeout).read()

    def exposure(self) -> dict:
        """当前曝光/增益 (只读 GET)。"""
        try:
            d = json.loads(self._get("/exposure", 6))
            return {"us": d.get("us"), "gain": d.get("gain"), "src": d.get("src")}
        except Exception:                                            # noqa: BLE001
            return {"us": None, "gain": None, "src": "unreachable"}

    def capture(self, grab: bool = True) -> np.ndarray | None:
        """取一帧原图 (2448x2048)。grab=True 时才真拍; 第一次失败自动重试一次
        (技能: 10083 偶发 "开启采集失败", 程序自己会重连一次)。"""
        for attempt in (1, 2):
            try:
                q = "/picture?kind=origin&grab=1" if grab else "/picture?kind=origin"
                raw = self._get(q, 20)
                im = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
                if im is not None:
                    return im
            except Exception:                                        # noqa: BLE001
                if attempt == 2:
                    return None
                time.sleep(1.0)
        return None

    # ── 图像可用性 (技能铁律: 先判可用性, 再谈搜索) ─────────────────────
    @staticmethod
    def usable(bgr: np.ndarray) -> tuple[bool, str]:
        g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        m, s = float(g.mean()), float(g.std())
        if m < 3.0 or s < 2.0:
            return False, "图像不可用 (mean %.2f std %.2f) — 没拍到/全黑, 不在上面跑搜索" % (m, s)
        return True, ""

    # ── 质量指标 ────────────────────────────────────────────────────────
    @staticmethod
    def metrics(bgr: np.ndarray) -> dict:
        g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
        lap = cv2.Laplacian(g, cv2.CV_64F)
        return {
            "mean": round(float(g.mean()), 2),
            "p90": round(float(np.percentile(g, 90)), 1),
            "sat_pct": round(float((g >= 250).mean() * 100), 2),      # 死白
            "dark_pct": round(float((g < 25).mean() * 100), 2),       # 暗部
            "sharpness": round(float(lap.var()), 1),                  # 清晰度(拉普拉斯方差)
            "hw": [int(g.shape[1]), int(g.shape[0])],
        }

    @staticmethod
    def verdict(q: dict) -> tuple[str, str]:
        """取像体检: 与程序自带口径一致 (饱和≤5%, mean 60~200), 但补"太暗"与"死白残留"。"""
        sat, m, dark = q.get("sat_pct", 0), q.get("mean", 0), q.get("dark_pct", 0)
        if m < 60:
            return "too_dark", "整帧 mean %.1f < 60 ⇒ 曝光过低 (暗部 %.1f%%)" % (m, dark)
        if sat > 5.0:
            return "overexposed", "死白 %.2f%% > 5%% ⇒ 局部镜面反光, 靠曝光压不干净" % sat
        if m > 200:
            return "overexposed", "整帧 mean %.1f > 200 ⇒ 整体过曝" % m
        return "ok", "mean %.1f / 死白 %.2f%% / 暗部 %.1f%% 均在口径内" % (m, sat, dark)

    # ── 主流程 ──────────────────────────────────────────────────────────
    def run(self, grab: bool = True, expand: bool = True, out_long: int = 1400) -> dict:
        t0 = time.time()
        expo = self.exposure()
        im = self.capture(grab=grab)
        if im is None:
            self.last = {"ok": False, "why": "取帧失败 (10083 不可达或相机忙)", "exposure": expo,
                         "src": "surface_bypass"}
            return self.last

        ok_img, why_img = self.usable(im)
        if not ok_img:
            self.last = {"ok": False, "why": why_img, "exposure": expo,
                         "src": "surface_bypass", **_wrap("full", self.metrics(im))}
            return self.last

        crop, overlay, meta = _rect_mod().surface_judge(im, out_long=out_long, expand=expand)
        full_q = self.metrics(im)
        res = {"ok": bool(meta.get("ok")) and crop is not None,
               "why": "" if (crop is not None and meta.get("ok")) else str(meta.get("why") or "没搜到矩形刚体"),
               "exposure": expo, "src": "surface_bypass",
               "rect": {k: meta.get(k) for k in
                        ("angle", "fill", "area_frac", "crop_size", "out_size", "no_stretch",
                         "expand_px", "same_pixel_mean_diff", "fg_frac", "n_cand", "mode")},
               "full": full_q}
        if crop is not None:
            cq = self.metrics(crop)
            ch, cw = crop.shape[:2]
            cq["long_edge_horizontal"] = bool(cw >= ch)              # 老倪: 光模块水平放置
            cq["aspect"] = round(max(cw, ch) / float(max(1, min(cw, ch))), 3)
            res["module"] = cq
            v, w = self.verdict(cq)
            res["verdict"], res["verdict_why"] = v, w
            res["judge_shape"] = [int(cw), int(ch)]
            if overlay is not None:
                res["overlay_hw"] = [int(overlay.shape[1]), int(overlay.shape[0])]
        else:
            res["verdict"] = "shape_fail"
            res["verdict_why"] = res["why"]
        res["ms"] = round((time.time() - t0) * 1000, 1)
        self.last = res
        return res

    # ── 给信号总线 / 面板 ───────────────────────────────────────────────
    def signals(self, res: dict | None = None) -> dict:
        """表面光学话题 (键 = 信号分析页可见的名字), 值全部取自本轮实测。"""
        r = res if res is not None else self.last
        if not r:
            return {}
        sig = {}
        sig["表面光学.可用"] = 0.0 if r.get("ok") else 1.0
        vmap = {"ok": 0, "too_dark": 1, "overexposed": 2, "shape_fail": 3}
        if r.get("verdict") in vmap:
            sig["表面光学.取像体检"] = float(vmap[r["verdict"]])
        full = r.get("full") or {}
        for k, f in (("表面光学.整帧均值", "mean"), ("表面光学.整帧死白", "sat_pct"),
                     ("表面光学.整帧暗部", "dark_pct"), ("表面光学.整帧清晰度", "sharpness")):
            if isinstance(full.get(f), (int, float)):
                sig[k] = float(full[f])
        mod = r.get("module") or {}
        for k, f in (("表面光学.模块均值", "mean"), ("表面光学.模块清晰度", "sharpness"),
                     ("表面光学.模块长宽比", "aspect")):
            if isinstance(mod.get(f), (int, float)):
                sig[k] = float(mod[f])
        rc = r.get("rect") or {}
        for k, f in (("表面光学.倾角", "angle"), ("表面光学.矩形度", "fill"),
                     ("表面光学.水平", "long_edge_horizontal")):
            v = mod.get(f, rc.get(f)) if f == "long_edge_horizontal" else rc.get(f)
            if isinstance(v, (int, float)) or isinstance(v, bool):
                sig[k] = float(v)
        if (r.get("exposure") or {}).get("us"):
            sig["表面光学.曝光us"] = float(r["exposure"]["us"])
        return sig

    @classmethod
    def camera_line(cls) -> str:
        return ("表面 10083 旁路 (4060 本机): %s · 只读 kind=origin&grab=1 · 判据图口径 "
                "tools/aoi_surface_rect.py (保留整块/长边水平/零插值)" % cls.URL)


def _wrap(tag, q):
    return {tag: q}


if __name__ == "__main__":
    import sys

    sq = SurfaceOpticalQuality()
    print(cls_line := SurfaceOpticalQuality.camera_line())
    r = sq.run(grab="--nograb" not in sys.argv)
    print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    print("\n信号:", json.dumps(sq.signals(r), ensure_ascii=False, indent=2))
    sys.exit(0 if r.get("ok") else 1)
