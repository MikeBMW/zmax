#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🌐 L4 潜表示 · 常驻提供器 (VLM 视觉编码器 → 黎曼度规约束 → 16 维潜坐标)

老倪 2026-10-14: 「VLM 通用视觉编码器是输入，流形引擎根据黎曼度规加约束，INTACT 负责意图解码」

为什么不是每周期现算: 实测视觉塔 **~0.8s/帧** (24 帧实测 792ms, 4060) —— 10Hz 回路里现算会把
回路拖垮。所以本提供器**独立线程按自己的节拍**抓帧→编码→约束投影, 引擎每周期只读**最新**潜坐标,
并带**帧龄**; 超期(stale) 就返回 None ⇒ 引擎回退内建 PCA 并明写 (不静默)。
"""
from __future__ import annotations

import os
import sys
import threading
import time
import urllib.request

import numpy as np

ROOT_DEFAULT = "/home/ubuntu/zmax"
FRAME_URL_DEFAULT = "http://127.0.0.1:8791/snapshot/local2.jpg"


def fetch_frame(url: str, timeout: float = 4.0):
    req = urllib.request.Request(url, headers={"User-Agent": "zmax-l4/1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:      # noqa: S310
        raw = r.read()
    if len(raw) < 512:
        raise RuntimeError("帧太小 (%d B) ⇒ 视为取不到" % len(raw))
    import io                                                    # noqa: PLC0415
    from PIL import Image                                        # noqa: PLC0415
    return Image.open(io.BytesIO(raw)).convert("RGB")


class L4LiveProvider:
    """真实相机帧 → VLM 特征 → 黎曼度规约束潜坐标 (常驻线程, 引擎只读最新值 + 帧龄)。"""

    def __init__(self, root: str = ROOT_DEFAULT, frame_url: str = FRAME_URL_DEFAULT,
                 interval: float = 1.0, stale_s: float = 8.0, latent_dim: int = 16) -> None:
        self.root = root
        self.frame_url = frame_url
        self.interval = max(0.2, float(interval))
        self.stale_s = max(1.0, float(stale_s))
        self.latent_dim = int(latent_dim)
        self.z: np.ndarray | None = None
        self.z_ts = 0.0
        self.n_ok = 0
        self.n_fail = 0
        self.last_ms = 0.0
        self.last_err = ""
        self.note_base = ""
        self._th: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> tuple:
        sys.path.insert(0, os.path.join(self.root, "src"))
        try:
            from lerobot.manifold.encoder_vlm import VLMVisionEncoder        # noqa: PLC0415
            from lerobot.manifold.l4_latent import L4LatentSpace              # noqa: PLC0415
        except Exception as e:                                               # noqa: BLE001
            return False, "L4 模块导入失败: %s: %s" % (type(e).__name__, e)
        self._enc = VLMVisionEncoder()
        ok, why = self._enc.available()
        if not ok:
            return False, why
        self._space = L4LatentSpace(self.root, self.latent_dim)
        try:
            self._space.load()
        except Exception as e:                                               # noqa: BLE001
            return False, "L4 标定读不到 (models/l4_latent_calib.json): %s" % str(e)[:90]
        self.note_base = ("L4 潜空间 (VLM 视觉编码器 → 黎曼度规约束 %d 维 · 标定 n=%d 帧)"
                          % (self.latent_dim, int(self._space.calib.get("n_frames") or 0)))
        self._th = threading.Thread(target=self._loop, name="l4-live", daemon=True)
        self._th.start()
        return True, why

    def _loop(self) -> None:
        while not self._stop.is_set():
            t0 = time.time()
            try:
                fr = fetch_frame(self.frame_url)
                z, _note = self._space.project(self._enc.encode(fr))
                self.z = np.asarray(z, float)[:self.latent_dim]
                self.z_ts = time.time()
                self.last_ms = (time.time() - t0) * 1e3
                self.n_ok += 1
                self.last_err = ""
            except Exception as e:                                           # noqa: BLE001
                self.n_fail += 1
                self.last_err = "%s: %s" % (type(e).__name__, str(e)[:80])
            dt = self.interval - (time.time() - t0)
            if dt > 0:
                self._stop.wait(dt)

    # ── 引擎 provider 接口: callable() → z 或 None (超期=没新鲜输入) ──
    def __call__(self):
        if self.z is None:
            return None
        if (time.time() - self.z_ts) > self.stale_s:
            return None
        return self.z

    def age_s(self) -> float:
        return (time.time() - self.z_ts) if self.z_ts else float("inf")

    def note(self) -> str:
        if self.z is None:
            return "%s · ⏳ 还没有潜表示 (成功 %d / 失败 %d: %s)" % (
                self.note_base, self.n_ok, self.n_fail, self.last_err or "等待首帧")
        return "%s · 帧龄 %.1fs · %.0fms/次 · 成功 %d/失败 %d" % (
            self.note_base, self.age_s(), self.last_ms, self.n_ok, self.n_fail)

    def stop(self) -> None:
        self._stop.set()
