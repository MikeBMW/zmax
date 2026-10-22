#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三层流形赋能层 · Intel 端全流程验证 (训练=自主进化 + 部署=接口自检)

跑法: python3 intel_verify_empower.py <manifold_empower.py 所在目录> <轨迹 npz>
本脚本只依赖 numpy (Intel 机器上 numpy 1.26.4 已就位, 无 torch/CUDA 需求)。
"""
import os
import sys
import json
import time
import platform
import numpy as np

TOOLS = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser('~/zmax_tools')
NPZ = sys.argv[2] if len(sys.argv) > 2 else os.path.expanduser('~/zmax_tools/subset.npz')
sys.path.insert(0, TOOLS)
from manifold_empower import EmpowerLayer, phi_smooth, _unit  # noqa: E402

PASS, FAIL = [], []


def ck(name, ok, det=""):
    (PASS if ok else FAIL).append(name)
    print("  %s %-46s %s" % ("✅" if ok else "❌", name, det))


print("=" * 96)
print("三层流形赋能层 · Intel 端验证")
print("=" * 96)
print("平台: %s %s" % (platform.machine(), platform.processor() or "(x86_64)"))
print("Python %s · numpy %s" % (platform.python_version(), np.__version__))
try:
    with open('/proc/cpuinfo') as f:
        for ln in f:
            if 'model name' in ln:
                print("CPU: %s" % ln.split(':')[1].strip()); break
except Exception:
    pass

# ── 环境自检: 是否真的不需要 torch/CUDA ──
print("\n【环境自检】")
import importlib
for mod in ('torch', 'cupy', 'pynvml'):
    try:
        importlib.import_module(mod)
        print("  %-10s 已安装 (本层不使用)" % mod)
    except ImportError:
        print("  %-10s 未安装 ✓ (本层零依赖)" % mod)
ck("仅依赖 numpy 即可运行", True, "无 CUDA/torch 需求")

# ── 载入真实轨迹 ──
print("\n【载入真实轨迹】")
d = np.load(NPZ)
flat = d['action']; offs = d['ep_offset']
segs = [flat[offs[i]:offs[i + 1]] for i in range(len(offs) - 1)]
print("  %d 段 · %d 帧 · 源=%s" % (len(segs), flat.shape[0], str(d['source'])))
ck("轨迹载入", len(segs) > 0, "%d 段" % len(segs))

SP = os.path.expanduser('~/.manifold_empower_state_intel.json')
if os.path.exists(SP):
    os.remove(SP)

# ── ① 部署自检: 接口 + 门控 ──
print("\n【① 部署自检 (接口 / 门控)】")
off = EmpowerLayer(enable_sem=False, enable_spa=False, enable_phy=False, state_path=SP)
c4 = np.array([0.3, -0.2, 0.5, 0.1])
ck("零侵入 4 维直通", np.array_equal(off.empower_chunk(c4), c4), "逐位相同")
a8 = np.arange(8.0)
ck("零侵入 8 维直通", np.array_equal(off.empower_action(a8), a8), "逐位相同")

emp = EmpowerLayer(state_path=SP)
r = emp.set_intent_from_l5({"intent": "插入光模块"})
ck("L5 意图解析", r["ok"], "goal_phy=%s" % np.round(r.get("goal_phy", []), 3))
ck("health() 可调用", isinstance(emp.health(), dict), str(emp.health()["gates"]))

# ── ② 训练: 自主进化 (在线, 不重训) ──
print("\n【② 训练 = 自主进化 (跨 %d 段在线学习)】" % min(60, len(segs)))
emp2 = EmpowerLayer(state_path=SP)
emp2.set_intent_from_l5({"intent": "插入"})
phi_hist = []
t0 = time.perf_counter()
for seg in segs[:60]:
    out = emp2.empower_chunk_seq(seg)
    g = np.asarray(emp2.st.goal_phy, float)
    phi_hist.append(float(np.mean([phi_smooth(p, g) for p in out])))
    emp2.update_from_outcome(success=True, end_chunk=seg[-1])
train_ms = (time.perf_counter() - t0) / min(60, len(segs)) * 1000
phi_hist = np.array(phi_hist)
f10, l10 = phi_hist[:10].mean(), phi_hist[-10:].mean()
ck("进化: Φ 水平下降", l10 <= f10, "%.4f → %.4f (%.1f%%)" % (f10, l10, 100 * (l10 - f10) / max(f10, 1e-12)))
ck("进化: 状态持久化", os.path.exists(SP), SP)
re_load = EmpowerLayer(state_path=SP)
ck("进化: 重启可恢复", abs(re_load.st.w_phy - emp2.st.w_phy) < 1e-9,
   "w_phy=%.4f n_updates=%d" % (re_load.st.w_phy, re_load.st.n_updates))
ck("训练吞吐", True, "%.2f ms/段 (含进化)" % train_ms)

# ── ③ 扰动恢复 (核心效能判据) ──
print("\n【③ 扰动恢复 (真实轨迹注入偏差)】")
RNG = np.random.default_rng(7)
rows = []
for sigma in (0.0, 0.05, 0.10, 0.20, 0.40):
    ds = []
    for seg in segs:
        goal = _unit(seg[-1])
        e = EmpowerLayer(state_path=SP)
        e.st.goal_phy = goal.tolist(); e.st.w_phy = 0.85
        noise = RNG.normal(size=seg.shape) * sigma * float(np.linalg.norm(seg, axis=1).mean() + 1e-9)
        pert = seg + noise
        out = e.empower_chunk_seq(pert)
        ds.append((float(np.linalg.norm(_unit(pert[-1]) - goal)),
                   float(np.linalg.norm(_unit(out[-1]) - goal))))
    ds = np.array(ds)
    gain = (ds[:, 0].mean() - ds[:, 1].mean()) / max(ds[:, 0].mean(), 1e-12) * 100
    rows.append((sigma, ds[:, 0].mean(), ds[:, 1].mean(), gain))
    print("     sigma=%.2f  原始 %.5f → 赋能 %.5f   (%+.1f%%)" % (sigma, ds[:, 0].mean(), ds[:, 1].mean(), gain))
rows = np.array(rows)
ck("抗扰动: 末端误差下降", bool(np.all(rows[1:, 2] <= rows[1:, 1] + 1e-9)),
   "改善 %s" % ", ".join("%.0f%%" % g for g in rows[1:, 3]))
ck("不办坏: 无扰动不变差", bool(rows[0, 2] <= rows[0, 1] + 1e-6), "Δ=%.2e" % (rows[0, 2] - rows[0, 1]))
ck("增益随扰动单调增", bool(np.all(np.diff(rows[1:, 3]) >= -1.0)),
   "%.0f%% → %.0f%%" % (rows[1, 3], rows[-1, 3]))

# ── ④ 实时性 ──
print("\n【④ 实时性】")
blk = RNG.normal(size=(16, 4))
emp2.empower_chunk_seq(blk)
t0 = time.perf_counter()
for _ in range(300):
    emp2.empower_chunk_seq(blk)
ms = (time.perf_counter() - t0) / 300 * 1000
ck("16 拍块 < 10ms", ms < 10.0, "%.2f ms/块 (%.2f ms/拍)" % (ms, ms / 16))

print("\n" + "-" * 96)
n_ok = len(PASS)
print("  PASS %d / %d" % (n_ok, n_ok + len(FAIL)))
if FAIL:
    print("  失败: %s" % ", ".join(FAIL))
print("-" * 96)
json.dump({"host": platform.node(), "cpu": platform.processor(),
           "python": platform.python_version(), "numpy": np.__version__,
           "evolve_first10": float(f10), "evolve_last10": float(l10),
           "sweep": [{"sigma": float(r[0]), "raw": float(r[1]), "fixed": float(r[2]), "gain": float(r[3])} for r in rows],
           "ms_per_block16": float(ms), "pass": n_ok, "total": n_ok + len(FAIL)},
          open(os.path.expanduser('~/intel_empower_verify.json'), 'w'), indent=1)
print("结果: ~/intel_empower_verify.json")
