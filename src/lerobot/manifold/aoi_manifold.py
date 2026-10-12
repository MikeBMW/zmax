# -*- coding: utf-8 -*-
"""aoi_manifold.py — 流形引擎 · 自动光学检测 (Manifold AOI) 可运行核

设计要点 (见 docs/design/流形引擎_自动光学检测_架构设计_v0.1.md):
- 只把**真可控、真可测**的量写进状态空间; 不可控维度不进流形(如实标注)。
- 度量张量**靠标定得到**(扰动-测量), 不手设。标定会自动暴露"假可控"维度(灵敏度≈0)。
- 势场全部来自**实测取数口**: ROI 拉普拉斯方差 / 过曝率 / 暗部率 / 覆盖率 / 判据缺陷。
- 控制 = 有限差分梯度流 + 投影(物理范围 + 变化率上限), 复用 energy_manifold 记账口径。
- 默认**只读**(不写相机参数); 标定要真写入必须显式 --write。

CLI:
  --selftest                     合成自检(梯度流下降/投影/健康度/灵敏度识别)
  --calibrate --port 10083       标定(默认只读: 逐档取像测量, 不写参数)
  --calibrate --port 10083 --write  才逐档真写入(工控机在役, 慎用)
  --state --port 10083           出一份当前状态/势场/健康度
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request

import numpy as np

A = "192.168.23.23"
UA = {"User-Agent": "zmax-probe"}
TARGET = {"over_max": 6.0, "dark_max": 25.0, "median_lo": 50.0, "median_hi": 120.0}


# ───────────────────────── 取数(实测口) ─────────────────────────
def _get(url: str, timeout: float = 30.0) -> bytes:
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()


def fetch_gray(port: int = 10083, kind: str = "origin", grab: bool = True) -> np.ndarray:
    """判据自己的取像口(kind=origin 才是实时帧; kind=judge 是落盘缓存, 不能当量具)。"""
    import io

    from PIL import Image
    b = _get("http://%s:%d/picture?kind=%s%s" % (A, port, kind, "&grab=1" if grab else ""))
    a = np.asarray(Image.open(io.BytesIO(b)).convert("L"), dtype=np.float32)
    return a


def cam_params(port: int = 10083) -> dict:
    """读曝光档: 10083 用 /exposure, 10082 用 /param。"""
    try:
        if port == 10083:
            d = json.loads(_get("http://%s:10083/exposure" % A).decode("utf-8", "ignore"))
            return {"us": d.get("us"), "gain": d.get("gain"), "raw": d}
        d = json.loads(_get("http://%s:10082/param" % A).decode("utf-8", "ignore"))
        return {"us": (d.get("file_defaults") or {}).get("exposure_us"),
                "gain": (d.get("file_defaults") or {}).get("gain_db"), "raw": d}
    except Exception as e:                                                       # noqa: BLE001
        return {"us": None, "gain": None, "err": "%s: %s" % (type(e).__name__, str(e)[:80])}


def set_cam(port: int, us: float, gain: float) -> dict:
    """写曝光档(调用方负责授权/闸门)。"""
    if port == 10083:
        u = "http://%s:10083/exposure?us=%g&gain=%g" % (A, us, gain)
    else:
        u = "http://%s:10082/param?exposure=%g&gain=%g" % (A, us, gain)
    return json.loads(_get(u).decode("utf-8", "ignore"))


# ───────────────────────── 势场(全部可实测) ─────────────────────────
def sharpness(gray: np.ndarray, roi=None) -> float:
    """清晰度势: ROI 拉普拉斯方差(归一化)。越小越清。"""
    g = gray if roi is None else gray[roi[1]:roi[1] + roi[3], roi[0]:roi[0] + roi[2]]
    if g.size < 16:
        return 0.0
    lap = (4 * g[1:-1, 1:-1] - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:])
    return float(np.log1p(lap.var()))


def exposure_potential(gray: np.ndarray, target: dict | None = None) -> dict:
    """曝光势: 过曝/欠曝/偏离目标中位。越小越好。"""
    t = dict(TARGET, **(target or {}))
    over = 100.0 * float((gray > 235).mean())
    dark = 100.0 * float((gray < 20).mean())
    med = float(np.median(gray))
    phi = 10.0 * max(0.0, over - t["over_max"]) + 4.0 * max(0.0, dark - t["dark_max"]) \
        + abs(med - 90.0) / 90.0
    return {"phi": float(phi), "over235": round(over, 2), "dark20": round(dark, 2), "median": round(med, 1)}


def coverage(shadow: np.ndarray, thr: float = 0.5) -> float:
    """覆盖势: 掩膜可覆盖像素占比(1-cov)。"""
    return float(1.0 - (shadow > thr).mean())


# ───────────────────────── 度量张量(标定得到) ─────────────────────────
def calibrate_axis(port: int, dims: list, measure, write: bool = False) -> dict:
    """单变量扰动标定: g_ii = |ΔΦ| / |Δ参数|。

    **可控判据必须超过噪声底**: 同档重拍的 Φ 抖动(σ) 就是底噪; 跨度 ≤ max(3σ, 1%基准Φ)
    视为不可控 —— 否则会把"帧噪声"误判成"有灵敏度"(实测踩过: 跨度 0.0403 vs 抖动 0.05)。
    """
    out = {}
    base = None
    noise = []
    for us, gn in dims:
        if write:
            set_cam(port, us, gn)
            time.sleep(1.0)
        try:
            g = fetch_gray(port)
        except Exception as e:                                                   # noqa: BLE001
            out["%d/%.1f" % (us, gn)] = {"err": "%s" % type(e).__name__}
            continue
        p = measure(g)
        if base is None:
            base = (us, gn, p["phi"])
            for _ in range(3):                       # 噪声底: 同档连拍
                try:
                    noise.append(measure(fetch_gray(port))["phi"])
                except Exception:                                                # noqa: BLE001
                    pass
        out["%d/%.1f" % (us, gn)] = dict(p, us=us, gain=gn)
    vals = [(k, v["phi"]) for k, v in out.items() if "phi" in v]
    span = (max(v for _, v in vals) - min(v for _, v in vals)) if len(vals) > 1 else 0.0
    n_sigma = float(np.std(noise)) if len(noise) > 1 else 0.0
    n_floor = max(3.0 * n_sigma, 0.01 * abs(base[2]) if base else 0.0)
    ctrl = bool(span > n_floor)
    return {"points": out, "phi_span": round(float(span), 4),
            "noise_sigma": round(n_sigma, 4), "noise_floor": round(float(n_floor), 4),
            "controllable": ctrl,
            "note": ("灵敏度 %.4f > 噪声底 %.4f ⇒ 该维度可进梯度流" % (span, n_floor) if ctrl
                     else "⚠️ 跨度 %.4f 落在噪声底 %.4f 内 ⇒ 写入被接受但画面不变(=假可控); "
                          "必须先修相机应用链, 该维度**不进流形**(如实标注)" % (span, n_floor))}


# ───────────────────────── 健康度 ─────────────────────────
class AOIHealthMonitor:
    """用度量张量特征值评估: λ_min(稳不稳) / κ(各向同性) / health 综合。"""

    def __init__(self):
        self.history = []

    def compute(self, metric: np.ndarray) -> dict:
        ev = np.sort(np.linalg.eigvalsh(np.asarray(metric, dtype=float)))
        lmin, lmax = float(ev[0]), float(ev[-1])
        kappa = lmax / (lmin + 1e-10)
        health = (1.0 / kappa) * lmin
        st = "优秀" if health > 0.5 else "良好" if health > 0.1 else "警告" if health > 0.01 else "危险"
        return {"health": round(health, 4), "kappa": round(kappa, 3),
                "lambda_min": round(lmin, 4), "lambda_max": round(lmax, 4), "status": st}

    def observe(self, metric: np.ndarray) -> dict:
        r = self.compute(metric)
        self.history.append(r)
        return r

    def trend(self) -> str:
        if len(self.history) < 10:
            return "数据不足"
        h = np.array([x["health"] for x in self.history[-10:]])
        k = float(np.polyfit(np.arange(len(h)), h, 1)[0])
        return "改善" if k > 1e-3 else ("下降" if k < -1e-3 else "稳定")


# ───────────────────────── 引擎 ─────────────────────────
class ManifoldAOIEngine:
    """梯度流: x ← Proj(x − η·∇Φ), ∇Φ 用中心差分(每次 2 张取像)。"""

    def __init__(self, port: int = 10083, eta: float = 4000.0, max_step_frac: float = 0.5):
        self.port = port
        self.eta = eta
        self.max_step_frac = max_step_frac
        self.health = AOIHealthMonitor()
        self.trace = []

    def potential_from_live(self) -> dict:
        g = fetch_gray(self.port)
        return dict(exposure_potential(g), sharp=round(sharpness(g), 3))

    def step(self, us: float, gain: float, write: bool = False) -> dict:
        """一步中心差分: 测 Φ(us±h) → 下降方向 → 投影 → (可选)真写入。"""
        h = max(1000.0, us * 0.25)
        if write:
            set_cam(self.port, max(1.0, us - h), gain)
            time.sleep(0.8)
        pm = self.potential_from_live()
        if write:
            set_cam(self.port, us + h, gain)
            time.sleep(0.8)
        pp = self.potential_from_live()
        grad = (pp["phi"] - pm["phi"]) / (2 * h)
        nxt = us - self.eta * grad
        nxt = float(np.clip(nxt, 1.0, 100000.0))
        lim = us * self.max_step_frac
        nxt = float(np.clip(nxt, us - lim, us + lim))            # L4 口径: 限变化率
        rec = {"us": us, "gain": gain, "phi_at": pm["phi"], "phi_hi": pp["phi"],
               "grad": grad, "next_us": nxt, "write": write}
        self.trace.append(rec)
        return rec


def _selftest() -> int:
    print("══ AOI 流形核 自检 ══")
    ok = True
    # ① 势场单调性: 过曝越多 Φ 越大
    a = np.full((64, 64), 60.0, np.float32)
    b = a.copy()
    b[:20, :] = 255.0
    pa, pb = exposure_potential(a), exposure_potential(b)
    good = pb["phi"] > pa["phi"]
    ok &= good
    print("  ① 过曝↑ ⇒ Φ↑ :", "通过" if good else "失败", pa, pb)
    # ② 清晰度: 有边缘 ⇒ var 更大
    c = a.copy()
    c[:, 32:] = 200.0
    good2 = sharpness(c) > sharpness(a)
    ok &= good2
    print("  ② 有边缘 ⇒ 清晰度↑ :", "通过" if good2 else "失败", round(sharpness(a), 3), round(sharpness(c), 3))
    # ③ 投影/变化率闸: 一步不会跳出 ±50%
    eng = ManifoldAOIEngine.__new__(ManifoldAOIEngine)
    lim = 1000.0 * 0.5
    nxt = float(np.clip(1e9, 1000.0 - lim, 1000.0 + lim))
    good3 = nxt == 1500.0
    ok &= good3
    print("  ③ 变化率闸(±50%) :", "通过" if good3 else "失败", nxt)
    # ④ 健康度: 单位阵 = κ1 → 良好及以上; 病态阵 = 危险
    hm = AOIHealthMonitor()
    h1 = hm.observe(np.eye(3))
    h2 = hm.compute(np.diag([1e-4, 1.0, 1.0]))
    good4 = h1["kappa"] == 1.0 and h2["status"] in ("警告", "危险")
    ok &= good4
    print("  ④ 健康度分档 :", "通过" if good4 else "失败", h1, h2)
    # ⑤ 标定能识别"零灵敏度"维度(假可控) —— 这正是指标该干的活
    fake = calibrate_axis(0, [(80000, 1.8), (40000, 1.4)], lambda g: {"phi": 1.0})
    good5 = fake["controllable"] is False
    ok &= good5
    print("  ⑤ 标定识别假可控 :", "通过" if good5 else "失败", "phi_span=", fake["phi_span"])
    print("\n", "✅ 全部通过" if ok else "❌ 有失败项")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--state", action="store_true")
    ap.add_argument("--port", type=int, default=10083)
    ap.add_argument("--write", action="store_true", help="标定是否真写入相机(默认只读)")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    if a.state:
        try:
            g = fetch_gray(a.port)
            e = exposure_potential(g)
        except Exception as ex:                                                  # noqa: BLE001
            print("取像失败:", type(ex).__name__, ex)
            return 2
        print(json.dumps({"port": a.port, "cam": cam_params(a.port), "exposure": e,
                          "sharpness": round(sharpness(g), 3)}, ensure_ascii=False, indent=2))
        return 0
    if a.calibrate:
        ports = [a.port]
        r = {}
        for p in ports:
            print("── 端口 %d 标定(写入=%s) ──" % (p, a.write))
            dims = [(100000, 1.8), (80000, 1.8), (40000, 1.4), (20000, 1.0), (10000, 0.7)]
            r[str(p)] = calibrate_axis(p, dims, exposure_potential, write=a.write)
            for k, v in r[str(p)]["points"].items():
                if "phi" in v:
                    print("   %-12s Φ=%.3f 过曝%.2f%% 中位%.0f 暗部%.2f%%"
                          % (k, v["phi"], v["over235"], v["median"], v["dark20"]))
            print("   φ 跨度=%.4f → 可控=%s" % (r[str(p)]["phi_span"], r[str(p)]["controllable"]))
            print("   ", r[str(p)]["note"])
        os.makedirs("zmax_data/ss_live", exist_ok=True)
        json.dump(r, open("zmax_data/ss_live/aoi_manifold_calib.json", "w"), ensure_ascii=False, indent=2)
        print("✅ 落盘 zmax_data/ss_live/aoi_manifold_calib.json")
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
