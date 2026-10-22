#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🧠 hjepa_state.py — H-JEPA 三层潜空间的**引擎内联通道** (老倪 2026-10-22 A)

为什么不做成"主编码器": 实测 (tools/verify_hjepa_engine.py 记录)
  · 这份权重对**画面几乎不敏感**: 8 张真帧 v_enc 输出余弦 = 1.00000, |v| 变化 < 0.5% ⇒ 图像支路近似常数项;
  · 对 state7 的 ±0.3 扰动余弦 ≈ 0.995 ⇒ 潜表示方向近乎刚性 (欠训练特征)。
  ⇒ 它能接、能逐帧真跑, 但**不能假装是看图编码器**; 主潜表示仍走 PCA / INTACT,
    H-JEPA 作为**世界模型通道** (三层潜范数 + 每层能量 + 预测残差) 进 `engine.step()` 的 `rec["hjepa"]`。

引擎侧接口与 `manifold_engine.set_hjepa_provider` 对齐: callable() → dict(ok/z1/z2/z3/z_concat/energy/ms)。
"""
from __future__ import annotations

import os
import time

import numpy as np

try:                                                                        # noqa: SIM105
    from .hjepa_model import ROOT_DEFAULT, HJEPAModel
    from .hjepa_live import _imread_any
except Exception:                                                            # noqa: BLE001
    from hjepa_model import ROOT_DEFAULT, HJEPAModel                        # type: ignore
    from hjepa_live import _imread_any                                      # type: ignore


class HJEPAStateProvider:
    """state7 → H-JEPA 三层潜表示 (每步真前向, 无相机依赖)。

    图像输入: `frame` (HWC ndarray) 或 `frame_path` (真帧文件) 复用同一帧 —— 因为实测该权重的
    图像支路近似常数; 都没给就用零图, 并在 note 里明写"图像=零输入"。
    """

    def __init__(self, root: str = ROOT_DEFAULT, state_fn=None, frame=None,
                 frame_path: str = "", every: int = 1, img_size: int = 64) -> None:
        self.root = root
        self.state_fn = state_fn
        self.every = max(1, int(every))
        self.model = HJEPAModel(root=root, img_size=img_size)
        self.note_base = ""
        self.frame = None
        self.frame_src = "零输入"
        if frame is not None:
            self.frame = np.asarray(frame)
            self.frame_src = "调用方给的帧"
        elif frame_path and os.path.isfile(frame_path):
            self.frame = _imread_any(frame_path)
            self.frame_src = os.path.basename(frame_path) if self.frame is not None else "零输入"
        if self.frame is None:
            self.frame = np.zeros((img_size, img_size, 3), np.uint8)
        self.last = {}
        self.n_ok = 0
        self.n_fail = 0
        self.last_err = ""
        self._n = 0

    def start(self) -> tuple:
        ok, why = self.model.available()
        if not ok:
            return False, why
        if self.state_fn is None:
            return False, "缺 state7 源 (state_fn=None)"
        self.note_base = ("H-JEPA 三层潜空间 · 每步真前向 · 图像=%s · state7=引擎当前 obs"
                          % self.frame_src)
        out = self._run()
        if not out.get("ok"):
            return False, "首步前向失败: %s" % out.get("why")
        return True, "首步就绪 · %.1f ms · |z₁|=%.2f/%s · %s" % (
            out["ms"], float(np.linalg.norm(out["z1"])), "640 维拼接",
            ("图像=零输入 (该权重图像支路实测不敏感)" if self.frame_src == "零输入" else "图像=" + self.frame_src))

    def _run(self) -> dict:
        s = self.state_fn() if self.state_fn is not None else None
        if s is None:
            self.n_fail += 1
            self.last_err = "state_fn 返回 None"
            return {"ok": False, "why": self.last_err}
        self._n += 1
        if self.every > 1 and (self._n % self.every) != 0 and self.last:
            return self.last                                    # 抽帧: 复用上次真值 (note 里带 ms)
        out = self.model.infer(self.frame, np.asarray(s, float).ravel()[:7])
        if out.get("ok"):
            self.n_ok += 1
            self.last_err = ""
            self.last = out
        else:
            self.n_fail += 1
            self.last_err = str(out.get("why"))[:160]
        return out

    def __call__(self):
        return self._run()

    def note(self) -> str:
        if not self.n_ok:
            return "%s · 未出值 (%s)" % (self.note_base, self.last_err or "等待")
        return "%s · ok %d/失败 %d · %.1fms%s" % (
            self.note_base, self.n_ok, self.n_fail, float(self.last.get("ms") or 0),
            (" · 最近错误 " + self.last_err) if self.last_err else "")

    def stop(self) -> None:
        return None


if __name__ == "__main__":
    import glob
    import json
    root = os.environ.get("ZMAX_ROOT") or "/home/ubuntu/zmax"
    traj = os.path.join(root, "data/database/zmax/sources/canvas/ss_traj_last.json")
    obs = np.asarray(json.load(open(traj, encoding="utf-8"))["obs"], float)
    fr = sorted(glob.glob(os.path.join(root, "zmax_data/eval_frames/live_1010_073927/*.png")))
    p = HJEPAStateProvider(root=root, state_fn=lambda: obs[-1][:7], frame_path=(fr[3] if fr else ""))
    ok, why = p.start()
    print(("✅ " if ok else "❌ ") + str(why))
    if ok:
        zs = []
        for i in range(4):
            o = p()
            zs.append(o["z_concat"])
            print("  step%d ok=%s ms=%.1f |z1|,|z2|,|z3|=%s energy=%s" % (
                i, o.get("ok"), float(o.get("ms") or 0),
                [round(float(np.linalg.norm(o[k])), 2) for k in ("z1", "z2", "z3")],
                [round(float(e), 3) for e in (o.get("energy") or [])]))
        Z = np.stack(zs)
        print("  相邻帧 cos:", [round(float(Z[i] @ Z[i + 1] / (np.linalg.norm(Z[i]) * np.linalg.norm(Z[i + 1]))), 6)
                            for i in range(len(Z) - 1)])
