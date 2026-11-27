#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧠 hjepa_live.py — H-JEPA 三层潜空间 → 流形引擎的**实时潜通道** (老倪 2026-10-22「A 真接」)

与 `l4_live.py` 同接口 (callable → z, note_base/note/start/stop), 差别只在编码器:
  L4: VLM 视觉编码器 → z16
  H-JEPA: 真帧 + state7 → z₁(256)/z₂(256)/z₃(128) 三层潜表示 + 每层 EB-JEPA 能量 + 世界模型预测残差

## 接线口径 (不假装)
  · **帧**: `frame_url` (http 快照) 或 `frames_dir` (本地真帧目录, 探针/离线用) —— 都拿不到就 `start()` 直接 False 并写明原因。
  · **state7**: 由 `state_fn` 提供 (引擎侧传"当前 obs 前 7 维")。没有 state 源 ⇒ 不接, **不拿零填充冒充**。
  · **引擎潜维**: 引擎仍用 PCA 的 16 维做几何/目标 (goal 是轨迹潜空间的概念, 换成 640 维会让 Φ 失去目标锚);
    H-JEPA 作为**第三条潜通道**进入 `engine.step()` 的观测/异常通道 (每帧真前向, 见 manifold_engine.set_hjepa_provider)。
  · `HJEPA_W` = 势场注入权重, 默认 **0.0** ⇒ 只观测、不动动作 (逐位零回归); >0 时 Φ 加一项 w·Σ能量,
    这条开关属于会改动作的档位, 必须另过闸 (默认关)。
"""
from __future__ import annotations

import io
import json
import os
import threading
import time

import numpy as np

try:                                                                        # noqa: SIM105
    from .hjepa_model import ROOT_DEFAULT, HJEPAModel
except Exception:                                                            # noqa: BLE001
    from hjepa_model import ROOT_DEFAULT, HJEPAModel                        # type: ignore

FRAME_URL_DEFAULT = "http://127.0.0.1:8791/aoi_modelin.png"


def _imread_any(src):
    """路径 → RGB ndarray (cv2 优先, 回退 PIL)。"""
    try:
        import cv2                                                          # noqa: PLC0415
        b = cv2.imread(src, cv2.IMREAD_COLOR)
        if b is not None:
            return b[:, :, ::-1].copy()                                     # BGR → RGB
    except Exception:                                                       # noqa: BLE001
        pass
    try:
        from PIL import Image                                               # noqa: PLC0415
        return np.asarray(Image.open(src).convert("RGB"))
    except Exception:                                                       # noqa: BLE001
        return None


def _fetch_http(url: str, timeout: float = 4.0):
    import urllib.request                                               # noqa: PLC0415
    with urllib.request.urlopen(url, timeout=timeout) as r:             # noqa: S310
        raw = r.read()
    if not raw:
        return None, "空响应"
    try:
        import cv2                                                          # noqa: PLC0415
        arr = np.frombuffer(raw, np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is not None:
            return img[:, :, ::-1].copy(), ""
        return None, "cv2 解码失败 (%d B)" % len(raw)
    except Exception as e:                                                  # noqa: BLE001
        return None, "解码异常 %s" % type(e).__name__


class HJEPALiveProvider:
    """真帧 + state7 → H-JEPA 三层潜表示 (后台线程按 Hz 刷新, `__call__` 返最新 z_concat)。"""

    def __init__(self, root: str = ROOT_DEFAULT, frame_url: str = "", frames_dir: str = "",
                 state_fn=None, interval: float = 0.5, stale_s: float = 8.0,
                 img_size: int = 64) -> None:
        self.root = root
        self.frame_url = frame_url
        self.frames_dir = frames_dir
        self.state_fn = state_fn
        self.interval = max(0.05, float(interval))
        self.stale_s = float(stale_s)
        self.model = HJEPAModel(root=root, img_size=img_size)
        self.note_base = ""
        self.z = None
        self.last = {}
        self.last_frame_ts = 0.0
        self.last_err = ""
        self.n_ok = 0
        self.n_fail = 0
        self.last_ms = 0.0
        self._stop = threading.Event()
        self._th = None
        self._files = []
        self._fi = 0

    # ── 帧源 ──
    def _frame_sources(self) -> list:
        srcs = []
        if self.frames_dir:
            try:
                srcs = sorted(os.path.join(self.frames_dir, f) for f in os.listdir(self.frames_dir)
                              if f.lower().endswith((".png", ".jpg", ".jpeg")))
            except Exception:                                                # noqa: BLE001
                srcs = []
        return srcs

    def _next_frame(self):
        if self.frame_url:
            img, why = _fetch_http(self.frame_url)
            if img is not None:
                return img, ""
            if not self._files:
                self._files = self._frame_sources()
            if not self._files:
                return None, "帧源取不到 (%s) 且无本地真帧目录" % why
        if not self._files:
            self._files = self._frame_sources()
        if not self._files:
            return None, "没有帧源 (frame_url 为空且 frames_dir 无图)"
        p = self._files[self._fi % len(self._files)]
        self._fi += 1
        img = _imread_any(p)
        return (img, "") if img is not None else (None, "读图失败 %s" % os.path.basename(p))

    def start(self) -> tuple:
        ok, why = self.model.available()
        if not ok:
            return False, why
        if self.state_fn is None:
            return False, "缺 state7 源 (state_fn=None): H-JEPA 的 s_proj 是 7 维输入, 不拿零填充冒充"
        if not self.frame_url and not os.path.isdir(self.frames_dir or ""):
            return False, "缺帧源: frame_url 为空且 frames_dir 不存在 (%s)" % (self.frames_dir or "-")
        self.note_base = ("H-JEPA 三层潜空间 (z₁256/z₂256/z₃128 · 每帧真前向 · "
                          "帧源 %s · state7 由引擎当前 obs 提供)"
                          % (self.frame_url or os.path.basename(self.frames_dir.rstrip("/"))))
        self._stop.clear()
        self._th = threading.Thread(target=self._loop, name="hjepa-live", daemon=True)
        self._th.start()
        t_end = time.time() + 6.0
        while time.time() < t_end:                                       # 首帧同步等 (探针要拿到真值)
            if self.n_ok > 0 or self.n_fail > 2:
                break
            time.sleep(0.05)
        if self.n_ok == 0:
            return False, "首帧前向未成功: %s" % (self.last_err or "超时")
        return True, "首帧就绪 · %.1f ms · |z₁|=%.2f" % (
            self.last_ms, float(np.linalg.norm(self.last.get("z1", np.zeros(1)))))

    def _loop(self) -> None:
        while not self._stop.is_set():
            t0 = time.time()
            try:
                s = self.state_fn() if self.state_fn is not None else None
                if s is None:
                    self.n_fail += 1
                    self.last_err = "state_fn 返回 None (obs 未就绪)"
                else:
                    img, why = self._next_frame()
                    if img is None:
                        self.n_fail += 1
                        self.last_err = why
                    else:
                        out = self.model.infer(img, s)
                        if out.get("ok"):
                            self.z = np.asarray(out["z_concat"], float)
                            self.last = out
                            self.last_ms = float(out["ms"])
                            self.n_ok += 1
                            self.last_frame_ts = t0
                            self.last_err = ""
                        else:
                            self.n_fail += 1
                            self.last_err = str(out.get("why"))[:160]
            except Exception as e:                                          # noqa: BLE001
                self.n_fail += 1
                self.last_err = "%s: %s" % (type(e).__name__, str(e)[:120])
            dt = time.time() - t0
            self._stop.wait(max(0.0, self.interval - dt))

    # ── 引擎侧接口 ──
    def __call__(self):
        if self.z is None or self.age_s() > self.stale_s:
            return None
        return self.z

    def age_s(self) -> float:
        return float("inf") if not self.last_frame_ts else (time.time() - self.last_frame_ts)

    def note(self) -> str:
        if not self.n_ok:
            return "%s · 未出帧 (%s)" % (self.note_base, self.last_err or "等待首帧")
        return "%s · 帧龄 %.2fs · %.1fms · ok %d/失败 %d%s" % (
            self.note_base, self.age_s(), self.last_ms, self.n_ok, self.n_fail,
            (" · 最近错误 " + self.last_err) if self.last_err else "")

    def stop(self) -> None:
        self._stop.set()
        if self._th is not None:
            self._th.join(timeout=2.0)
        self._th = None


if __name__ == "__main__":
    import glob
    import sys
    root = os.environ.get("ZMAX_ROOT") or "/home/ubuntu/zmax"
    d = sys.argv[1] if len(sys.argv) > 1 else sorted(glob.glob(
        os.path.join(root, "zmax_data/eval_frames/live_*")))[-1]
    traj = os.path.join(root, "data/database/zmax/sources/canvas/ss_traj_last.json")
    obs = None
    try:
        with io.open(traj, encoding="utf-8") as fh:
            obs = np.asarray(json.load(fh)["obs"], float)[-1]
    except Exception:                                                       # noqa: BLE001
        obs = np.zeros(43)
    prov = HJEPALiveProvider(root=root, frames_dir=d,
                             state_fn=lambda: obs[:7], interval=0.2, stale_s=30.0)
    ok, why = prov.start()
    print(("✅ " if ok else "❌ ") + str(why))
    if ok:
        for _ in range(3):
            z = prov()
            print("z", None if z is None else "%s |z|=%.2f" % (z.shape, float(np.linalg.norm(z))),
                  "· note:", prov.note())
            time.sleep(0.4)
    prov.stop()
