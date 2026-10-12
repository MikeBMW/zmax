#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""判据: 流形引擎**主参数 M = 度量张量 g_ij(x)** (老倪 2026-10-12 设计口径)。

老倪: 「流形引擎的主参数是一个张量 —— 随状态变化的度量张量 g_ij(x); 大小 n×n, 独立分量 n(n+1)/2;
        联络/曲率/梯度/测地线都是从它导出的。你来设计主参数 M」

本判据查 7 条 (每条都真算, 不空转):
 ① 独立分量数 = n(n+1)/2 (3→6 · 6→21 · 16→136 · 43→946)
 ② 度量对称正定 + 形状 det G = 1 (尺度/形状可分辨)
 ③ **零回归**: 各向同性 (G=I) ⇒ Γ ≡ 0、测地线 = 欧氏直线、a = F/M (与旧标量语义逐字一致)
 ④ 解析对照: 2D 度量 g = diag(1, h(x¹)) 的 Γ²₁₂ = h'/(2h) (数值 vs 解析)
 ⑤ 真曲率: 常度量 ⇒ ‖R‖=0; 弯曲度量 ⇒ ‖R‖>0 (够区分)
 ⑥ 配置真源: config/calib/zmax_manifold.json 的 metric 段可读、可写、写后回读一致 (且非正定被拒写)
 ⑦ 真跑节点: 「标定诊断测量 · 主参数 M」节点运行会报出度量口径 (dim/mode/独立分量/正定性/测地线偏离)

用法: QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_metric_main_param.py
"""
import json
import os
import sys

import numpy as np

ROOT = "/home/ubuntu/zmax"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

from lerobot.manifold.metric_field import (MetricField, MODE_FULL, MODE_ISOTROPIC,  # noqa: E402
                                           _normalize_det, analytic_check_g22, independent_components)

_ok = _bad = 0


def ck(name, cond, ev=""):
    global _ok, _bad
    if cond:
        _ok += 1
        print("  ✅ %s%s" % (name, ("   ← %s" % ev) if ev else ""))
    else:
        _bad += 1
        print("  ❌ %s%s" % (name, ("   ← %s" % ev) if ev else ""))
    return bool(cond)


class Curved2(MetricField):
    """判据用的弯曲度量: 2D g = diag(1, h(x¹)), h(x)=1+x² (解析 Γ 可对照)。"""

    def shape(self, x):
        x = np.asarray(x, dtype=float).ravel()
        return _normalize_det(np.diag([1.0, 1.0 + float(x[0]) ** 2]))


print("═══ 判据: 主参数 M = 度量张量 g_ij(x) ═══")
print("① 独立分量数 n(n+1)/2")
for n, want in ((3, 6), (6, 21), (16, 136), (43, 946)):
    ck("n=%d ⇒ %d 个独立分量" % (n, want), independent_components(n) == want, "实测 %d" % independent_components(n))

print("② 对称正定 + 形状 det(G)=1")
rng = np.random.default_rng(7)
comps = list(rng.normal(size=independent_components(4)))
f4 = MetricField(4, scale=2.5, mode=MODE_FULL, comps=comps)
g = f4.g(np.zeros(4))
ck("度量对称 (‖g−gᵀ‖<1e-12)", float(np.abs(g - g.T).max()) < 1e-12, "%.2e" % float(np.abs(g - g.T).max()))
okp, mn, det = f4.is_positive_definite()
ck("随机形状仍正定 (Cholesky 成功)", bool(okp), "min_eig=%.4g" % mn)
ck("形状 det G = 1 (尺度全归 M)", abs(float(np.linalg.det(f4.shape(np.zeros(4)))) - 1.0) < 1e-9,
   "det G=%.12f" % float(np.linalg.det(f4.shape(np.zeros(4)))))
ck("尺度 M 真进入度量 (g = M·G)", abs(float(np.linalg.det(g)) - 2.5 ** 4) < 1e-6, "det g=%.6f (=M^4)" % float(np.linalg.det(g)))

print("③ 零回归: 各向同性 ⇒ Γ≡0 / 测地线=直线 / a=F/M")
f_iso = MetricField(3, scale=1.0, mode=MODE_ISOTROPIC)
Gam = f_iso.christoffel(np.array([0.3, -1.2, 0.7]))
ck("Γ ≡ 0 (‖Γ‖<1e-9)", float(np.linalg.norm(Gam)) < 1e-9, "%.2e" % float(np.linalg.norm(Gam)))
x0, v0 = np.array([0.1, 0.2, 0.3]), np.array([1.0, 0.0, 0.0])
geo = f_iso.geodesic_curve(x0, v0, steps=5, dt=0.05)[-1]
lin = x0 + v0 * 0.25
ck("测地线 = 欧氏直线 (与解析 ≤1e-12)", float(np.linalg.norm(geo - lin)) < 1e-12,
   "偏离 %.2e" % float(np.linalg.norm(geo - lin)))
F = np.array([2.0, 0.0, 0.0])
f_m4 = MetricField(3, scale=4.0, mode=MODE_ISOTROPIC)
a = f_m4.accel(x0, v0, F)
ck("a = F/M (旧标量语义逐字一致)", float(np.linalg.norm(a - F / 4.0)) < 1e-12, "a=%s" % np.round(a, 6).tolist())

print("④ 解析对照: 2D 度量 g=diag(1,h(x¹)), Γ²₁₂ = h'/(2h)")
fc = Curved2(2)
x1 = 0.7
Gc = fc.christoffel(np.array([x1, 0.0]))
# 注意: 本场是**单位行列式**度量 g̃ = diag(a, 1/a), a = h^{-1/2} (det g̃ = 1 归一化后)。
#   解析 (由 Christoffel 定义直接推): Γ¹₁₁ = −h'/(4h), Γ²₁₂ = +h'/(4h), Γ¹₂₂ = −h'/4, 其余 = 0
h_, dh = 1.0 + x1 ** 2, 2 * x1
want = np.zeros((2, 2, 2))                                             # 解析 Γ^k_ij (含 i↔j 对称)
_vals = {(1, 1, 1): -dh / (4 * h_), (2, 1, 2): dh / (4 * h_), (2, 2, 1): dh / (4 * h_), (1, 2, 2): -dh / 4.0}
for (k, i, j), val in _vals.items():
    want[k - 1, i - 1, j - 1] = want[k - 1, j - 1, i - 1] = val
_err = float(np.abs(Gc - want).max())
ck("数值 Γ 张量对上单位行列式度量的解析式 (逐分量 <1e-6)", _err < 1e-6,
   "最大偏差 %.2e (例 Γ²₁₂ 数值 %.6f vs 解析 %.6f)" % (_err, Gc[1, 0, 1], want[1, 0, 1]))
ck("其余 Γ 分量为 0 (无 off-diagonal 度量项)", float(np.abs(Gc - want).max()) < 1e-6, "%.2e" % _err)
ck("单位行列式度量的无迹关系 Γ¹₁₁ + Γ²₁₂ = 0", abs(Gc[0, 0, 0] + Gc[1, 0, 1]) < 1e-9,
   "%.2e" % float(abs(Gc[0, 0, 0] + Gc[1, 0, 1])))

print("⑤ 曲率: 常度量 ⇒ ‖R‖=0; 弯曲度量 ⇒ ‖R‖>0")
c_flat = f_iso.curvature_report(np.zeros(3))
ck("常度量 ‖R‖ = 0 (平直)", float(c_flat["‖R‖_F"]) < 1e-6, "%.2e" % float(c_flat["‖R‖_F"]))
c_curv = fc.curvature_report(np.array([x1, 0.0]))
ck("弯曲度量 ‖R‖ > 0 (真曲率)", float(c_curv["‖R‖_F"]) > 1e-3, "‖R‖=%.4g" % float(c_curv["‖R‖_F"]))

print("⑥ 配置真源 (config/calib/zmax_manifold.json 的 metric 段)")
import tools.zmax_params as ZP                                                          # noqa: E402
mp = ZP.manifold_metric()
ck("metric 段可读 (dim/mode/独立分量)", mp["dim"] >= 3 and mp["mode"] in ("isotropic", "diag", "full"),
   "dim=%s mode=%s 独立分量=%s" % (mp["dim"], mp["mode"], mp["independent_components"]))
w = ZP.write_manifold_metric()                     # 同值回写 (幂等)
ck("同值回写可回读", bool(w.get("ok")), str({k: w.get("metric", {}).get(k) for k in ("dim", "mode")}))
cnt_p = os.path.join(ROOT, "config/calib/zmax_manifold.json")
_before = json.load(open(cnt_p, encoding="utf-8"))
bad = ZP.write_manifold_metric(mode="full", dim=3, comps=[1.0, 0.0, 0.0, -5.0, 0.0, 0.0])   # 非正定组合
ck("非正定形状被拒写 (不污染真源)", not bad.get("ok"),
   str(bad.get("why") or bad.get("metric")))
json.dump(_before, open(cnt_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)      # 还原

print("⑦ 真跑节点: 主参数 M 节点报度量口径")
from lerobot.engineering.nodes import library as L                                       # noqa: E402
_lines = []
try:
    r = L.node_ss_calib_mani({"log": lambda m: _lines.append(str(m)), "params": {}, "module": None})
    err = ""
except Exception as e:                                                                  # noqa: BLE001
    r, err = {}, repr(e)
ck("节点运行无异常", not err, err or ("返回 %s" % str(r)[:60]))
_txt = " ".join(_lines)
ck("节点日志报出度量 (dim/mode/独立分量)", ("度量张量" in _txt) and ("独立分量" in _txt),
   next((x for x in _lines if "度量张量" in x), "")[:110])
ck("节点日志报出正定性/曲率", ("正定" in _txt) and ("曲率" in _txt), next((x for x in _lines if "正定" in x), "")[:110])
ck("节点日志报出测地线 vs 直线 (零回归证据)", "测地线" in _txt, next((x for x in _lines if "测地线" in x), "")[:110])

print()
print("判据结论: %s   (%d 通过 / %d 失败)" % ("✅ PASS" if _bad == 0 else "❌ FAIL", _ok, _bad))
raise SystemExit(0 if _bad == 0 else 1)
