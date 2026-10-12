#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""判据: **配置单 → 主参数 M** 的显式映射 (可审计) + 两端节点接线 (老倪 2026-10-12)。

老倪原话:
> 配置中心的参数, 要映射到主参数 M … 这个逻辑在**主参数 M 节点**实现, 主要是映射关系;
> 主参数 M 的功能, 要由**流形引擎节点**实现, 通过一个结构, 承接要实现的功能。

七条断言 (每条都真跑, 不空转):
  ① 幂等: 同一配置单重复跑 → audit_sha 逐位相同 (3 组配置单 × 3 次)
  ② 映射依据齐全: 每条规则 (R1/R2+R3/R4/R5) 都有非空 规则文本 + 来源; 覆盖 dim/mode/scale/diag/gain;
     逐轴公差有来源; scale 每个输入有来源
  ③ 非法配置被闸门拦住: 非正定形状 (diag 负分量 / full 奇异) 被拒写, 且**真源字节不变**
  ④ 合法写盘回路: 写 M 真源 (经 zmax_params 闸门) → 回读 metric/M 与映射结果一致 (min_eig>0)
  ⑤ 节点右键源码定位到映射函数行: 画布节点 n_calib_mani 的 m_source/m_source_symbol
     解析到 tools/config_to_M.py **def compute_M(** 那一行 (与 GUI 同一规则: source 优先 + 符号定位)
  ⑥ 真跑两端节点: 主参数 M 节点 (映射) 与 流形引擎节点 (用 M 算几何/健康 H/扭矩 τ) 均无异常 +
     日志含映射依据/度量几何行; 画布结构不回归 (89 节点 / 184 连线)
  ⑦ 三组真实配置单: TASK-01-FW / TASK-06-TRAY / TASK-07-AOI → M(dim/mode/scale) 与 H/κ/τ 真跑并打印

用法: QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_config_to_M.py
"""
import hashlib
import json
import os
import sys

ROOT = "/home/ubuntu/zmax"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

import tools.config_to_M as CM                                                          # noqa: E402

MANIFOLD = os.path.join(ROOT, "config/calib/zmax_manifold.json")
CANVAS = CM.canvas_path(ROOT)
NODE_ID = "n_calib_mani"
TASKS = ["TASK-01-FW", "TASK-06-TRAY", "TASK-07-AOI"]

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


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


print("═══ 判据: 配置单 → 主参数 M 的显式映射 (可审计) + 两端节点 ═══")

# ── ① 幂等 ────────────────────────────────────────────────────────────────────
print("① 幂等 (同一配置单重复跑结果稳定)")
specs = {}
for tid in TASKS:
    shas = [CM.compute_M(tid)["audit_sha"] for _ in range(3)]
    specs[tid] = CM.compute_M(tid)
    ck("%s 三次跑 audit_sha 一致" % tid, len(set(shas)) == 1, shas[0][:16])

# ── ② 映射依据齐全 ────────────────────────────────────────────────────────────
print("② 映射依据齐全 (每条规则带来源; 覆盖 dim/mode/scale/形状/gain)")
for tid in TASKS:
    s = specs[tid]
    tbl = {r["id"]: r for r in s["mapping_table"]}
    ck("%s 规则齐 (R1/R2+R3/R4/R5)" % tid, set(tbl) == {"R1", "R2+R3", "R4", "R5"}, ",".join(sorted(tbl)))
    ok_src = all(str(r.get("rule", "")).strip() and str(r.get("source", "")).strip() for r in tbl.values())
    ck("%s 每条规则 规则+来源 非空" % tid, ok_src)
    r23 = tbl["R2+R3"]
    ck("%s 逐轴公差有来源" % tid, bool(r23.get("axis_tolerance")) and
       all(str(v).strip() for v in (r23.get("tolerance_sources") or {}).values()),
       "轴 %s" % (r23.get("axis_order")))
    ck("%s 形状可解析 (mode=%s ⇒ diag/comps 与之一致)" % (tid, s["mode"]),
       (s["mode"] == "isotropic" and not s["diag"] and not s["components"]) or
       (s["mode"] == "diag" and s["diag"]) or (s["mode"] == "full" and s["components"]),
       "diag=%s comps=%s" % (s["diag"], s["components"]))
    ck("%s scale 每个输入有来源" % tid,
       all(str(v).strip() for v in (tbl["R5"].get("input_sources") or {}).values()),
       "m_eff=%.4g v=%.3g h=%.3g" % (tbl["R5"]["m_eff_kg"], tbl["R5"]["inputs"]["v_peak_mps"],
                                     tbl["R5"]["inputs"]["stroke_m"]))
    ck("%s gain 状态 (待标定/不需要) 有交代" % tid, bool(tbl["R4"].get("status")), tbl["R4"]["status"])

# ── ③ 非法配置被闸门拦住 ──────────────────────────────────────────────────────
print("③ 非法配置被闸门拦住 (且真源字节不变)")
sha0 = sha(MANIFOLD)
bad_cases = [("diag 负分量", {"dim": 3, "mode": "diag", "diag": [1.0, 1.0, -2.0], "components": None, "scale": 2.0}),
             ("full 奇异 (det=0)", {"dim": 3, "mode": "full", "diag": None,
                                    "components": [1.0, 0.0, 0.0, -5.0, 0.0, 0.0], "scale": 1.0}),
             ("dim=6 diag 零分量", {"dim": 6, "mode": "diag", "diag": [1, 1, 1, 1, 1, 0.0],
                                    "components": None, "scale": 1.0})]
for nm, bad in bad_cases:
    r = CM.write_master_param(bad)
    ck("非正定[%s] 被拒写" % nm, not r.get("ok"), str(r.get("gate"))[:70])
ck("三次非法尝试后真源字节未变", sha(MANIFOLD) == sha0, "%s" % sha0[:16])

# ── ④ 合法写盘回路 ────────────────────────────────────────────────────────────
print("④ 合法写盘回路 (经 zmax_params 闸门 → 回读一致)")
act = CM.active_task_id(CM.load_bundle())
w = CM.write_master_param(specs[act])
ck("写 M 真源 [%s] 成功" % act, bool(w.get("ok")), str(w.get("dest")))
if w.get("ok"):
    rb = w["metric_readback"]
    ck("回读 metric 与映射一致 (dim/mode)",
       int(rb.get("dim")) == specs[act]["dim"] and rb.get("mode") == specs[act]["mode"],
       "回读 dim=%s mode=%s (映射 dim=%s mode=%s)" % (rb.get("dim"), rb.get("mode"), specs[act]["dim"], specs[act]["mode"]))
    ck("回读 M 与映射 scale 一致", abs(float(rb.get("M")) - float(specs[act]["scale"])) < 1e-9,
       "回读 M=%s scale=%s" % (rb.get("M"), specs[act]["scale"]))
    ck("闸门 min_eig > 0 (正定)", float(w.get("min_eig", -1)) > 0, "min_eig=%.4g" % w.get("min_eig", -1))
    print("     真源 sha: %s → %s (%s)" % (sha0[:16], sha(MANIFOLD)[:16], os.path.relpath(MANIFOLD, ROOT)))

# ── ⑤ 节点右键源码定位到映射函数行 ────────────────────────────────────────────
print("⑤ 节点右键源码定位到映射函数行")
d = json.load(open(CANVAS, encoding="utf-8"))
node = CM._find_node(d)
p = (node or {}).get("params") or {}
m_src = str(p.get("m_source") or "")
m_sym = str(p.get("m_source_symbol") or "")
ck("节点挂 m_source / m_source_symbol", bool(m_src) and bool(m_sym), "%s · %r" % (m_src, m_sym))
line = None
mp = os.path.join(ROOT, m_src) if m_src else ""
if os.path.isfile(mp):
    for i, ln in enumerate(open(mp, encoding="utf-8"), 1):
        if m_sym and m_sym in ln:
            line = i
            break
ck("m_source_symbol 在映射文件里解析出行号", bool(line),
   "code -g %s:%s" % (mp.replace(ROOT + "/", ""), line))
if line:
    _txt = open(mp, encoding="utf-8").read().splitlines()[line - 1]
    ck("该行确实是映射函数定义 (def compute_M)", _txt.strip().startswith("def compute_M("), _txt.strip()[:60])
ck("定位命令不含 GUI/node_logic.py", "node_logic.py" not in mp and "tools/gui" not in mp)
ck("节点仍保留配置导入 source (原判据不破)", str(p.get("source")) == "src/lerobot/engineering/config_import.py",
   str(p.get("source")))
ck("节点参数挂 m_metric (稳定段) + m_loaded_at", isinstance(p.get("m_metric"), dict) and bool(p.get("m_loaded_at")),
   "m_metric=%s" % json.dumps(p.get("m_metric"), ensure_ascii=False)[:80])

# ── ⑥ 真跑两端节点 ────────────────────────────────────────────────────────────
print("⑥ 真跑两端节点 (主参数 M 节点 = 映射; 流形引擎节点 = 用 M 实现功能)")
from lerobot.engineering.nodes import library as L                                       # noqa: E402
log1 = []
try:
    r1 = L.node_ss_calib_mani({"log": log1.append, "params": {}, "module": None})
    e1 = ""
except Exception as e:                                                                   # noqa: BLE001
    r1, e1 = None, repr(e)
t1 = " ".join(str(x) for x in log1)
ck("主参数 M 节点运行无异常", not e1, e1 or "ret=%s" % r1)
ck("节点日志有'主参数 M ← 配置单'映射块", "主参数 M ← 配置单" in t1)
ck("节点日志逐条打印映射依据 (R1/R2+R3/R4/R5)", all(("[%s]" % k) in t1 for k in ("R1", "R2+R3", "R4", "R5")))
ck("节点日志给出 来源(⇐) 行", t1.count("⇐") >= 6, "%d 条带来源" % t1.count("⇐"))
log2 = []
try:
    r2 = L.node_ss_mani_eng({"log": log2.append, "params": {}, "module": None})
    e2 = ""
except Exception as e:                                                                   # noqa: BLE001
    e2 = repr(e)
t2 = " ".join(str(x) for x in log2)
ck("流形引擎节点运行无异常", not e2, e2 or "ret=%s" % r2)
ck("引擎节点用 M 算度量几何 (g=M·G / 正定 / 曲率 κ)", ("度量 g=M·G" in t2) and ("κ (曲率)" in t2))
ck("引擎节点报健康度 H", "健康度 H" in t2, next((x for x in log2 if "健康度 H" in x), "")[:90])
ck("引擎节点报扭矩 τ", "扭矩 τ" in t2, next((x for x in log2 if "扭矩" in x), "")[:90])
d2 = json.load(open(CANVAS, encoding="utf-8"))
ck("画布结构不回归 (89 节点 / 184 连线)", len(d2["nodes"]) == 89 and len(d2.get("links") or []) == 184,
   "%d / %d" % (len(d2["nodes"]), len(d2.get("links") or [])))

# ── ⑦ 三组真实配置单 ──────────────────────────────────────────────────────────
print("⑦ 三组真实配置单 → M(dim/mode/scale) 与 H/κ/τ (真跑)")
import numpy as np                                                                       # noqa: E402
from lerobot.manifold.metric_field import MetricField                                    # noqa: E402
from lerobot.manifold.homeostasis import HomeostasisEngine                               # noqa: E402
print("     ┌ task               dim  mode       scale(M)  diag/components                       H       κ        τ")
seen = set()
for tid in TASKS:
    s = specs[tid]
    mf = MetricField(int(s["dim"]), float(s["scale"]), s["mode"], s["diag"], s["components"], s["gain"])
    okp, mn, detg = mf.is_positive_definite()
    cr = mf.curvature_report()
    kap = float(cr.get("‖R‖_F", 0.0))
    x0 = np.zeros(int(s["dim"]))
    v0 = np.zeros(int(s["dim"]))
    v0[0] = 1.0
    tau = float(s["scale"]) * float(np.linalg.norm(np.einsum("kij,i,j->k", mf.christoffel(x0), v0, v0)))
    H = (1.0 if okp and abs(float(np.linalg.det(mf.shape(x0))) - 1.0) < 1e-9 else 0.0) * \
        float((HomeostasisEngine().drive(dt=0.01) or {}).get("vitality", 1.0))
    shape = s["diag"] if s["diag"] else (s["components"] if s["components"] else "G=I")
    print("     │ %-18s %-4d %-10s %-9.4g %-34s %-7.4g %-8.4g %-8.4g"
          % (tid, s["dim"], s["mode"], s["scale"], str(shape)[:34], H, kap, tau))
    ck("%s 度量正定 (min_eig>0)" % tid, okp, "min_eig=%.4g det g=%.4g" % (mn, detg))
    seen.add((s["dim"], s["mode"], s["scale"]))
print("     └ 3 组配置单给出 %d 种不同 M(dim/mode/scale)" % len(seen))
ck("三组配置单结果互不相同 (>1 种)", len(seen) > 1, "%d 种" % len(seen))

# ── 机制自检: 常数度量 ⇒ κ=0/τ=0 (零回归); 状态相关(gain) ⇒ τ>0; 弯曲 ⇒ κ>0 ──────
print("★ 机制自检 (非配置单值): 常数度量 κ=0/τ=0 (零回归) vs 状态相关/弯曲 ⇒ τ>0 / κ>0")
from lerobot.manifold.metric_field import _normalize_det                                  # noqa: E402


class _Curved2(MetricField):
    """解析弯曲度量 g = diag(1, 1+x¹²) (与 verify_metric_main_param.py 同款, ‖R‖>0)。"""

    def shape(self, x):
        x = np.asarray(x, dtype=float).ravel()
        return _normalize_det(np.diag([1.0, 1.0 + float(x[0]) ** 2]))


def _tau(mf, v=None):
    n = mf.dim
    x0 = np.zeros(n)
    v0 = np.zeros(n) if v is None else v
    if v is None:
        v0[0] = 1.0
    return float(mf.scale) * float(np.linalg.norm(np.einsum("kij,i,j->k", mf.christoffel(x0), v0, v0)))


flat = MetricField(3, 2.0, "isotropic")
_Gk = np.zeros((3, 3, 3))
_Gk[0, 0, 0] = 0.20            # x₀ 影响 g_xx  → ∂_0 g_xx ≠ 0
_Gk[1, 2, 1] = -0.15           # x₁ 影响 g_yz  → 状态相关离对角项
state_metric = MetricField(3, 2.0, "diag", diag=[1.0, 1.0, 3.0], gain=_Gk)
curved = _Curved2(2)
kf, tf = float(flat.curvature_report()["‖R‖_F"]), _tau(flat)
ks, ts = float(state_metric.curvature_report()["‖R‖_F"]), _tau(state_metric)
kc = float(curved.curvature_report()["‖R‖_F"])
ck("常数度量 ‖R‖≈0 且 τ≈0 (配置单当前: gain 待标定 ⇒ 平坦, 零回归)", kf < 1e-6 and abs(tf) < 1e-9,
   "‖R‖=%.2e τ=%.2e" % (kf, tf))
ck("状态相关度量 (gain 到场) τ>0 (扭矩真出现)", ts > 1e-6,
   "‖Γ‖=%.4g τ=%.4g (κ=%.2e)" % (float(state_metric.curvature_report()["‖Γ‖_F"]), ts, ks))
ck("弯曲度量 ‖R‖>0 (曲率 κ 真出现)", kc > 1e-3, "‖R‖=%.4g" % kc)

print()
print("判据结论: %s   (%d 通过 / %d 失败)" % ("✅ PASS" if _bad == 0 else "❌ FAIL", _ok, _bad))
raise SystemExit(0 if _bad == 0 else 1)
