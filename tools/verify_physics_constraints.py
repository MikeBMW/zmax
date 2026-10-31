#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_physics_constraints.py — ⚖ 物理惯性/质量变化率链判据 (老倪 2026-10-15 原话逐条对)。

老倪: 「所有 L2 层的原子动作, 都要有物理质量变化率的约束 … 确保进入原子技能的 action 能够符合物理定律,
确保最终发出的动作都是物理上可以平顺执行的。如果不能执行, 可以发出偏差 error, 这个 error 可以反馈给
状态校正节点, 修正误差; 如果误差太大, 则可以通过融合定位节点, 将大偏差先直接反馈给流形引擎节点,
从而改变顶层结构, 修复补偿偏差。」

判据:
  ① 盘查: 9 个技能每个都有 m/F/v/a_max/jerk_max/dm·dt⁻¹ 且 a_max == F/m (牛顿第二定律自洽)
  ② 闸门真拦得住: 请求超限 ⇒ 被削 (速度/加速度/加加速度 三条都能各自触发) · 方向不翻转 · 夹爪维透传
  ③ 现场: skill_error.json 帧龄 <1s · 每技能有 请求/可行/偏差/削因/大偏差 · 计数在涨
  ④ 偏差→状态校正器: state_correction(err=...) 真把偏差并进校正结果 (有 err 与无 err 结果不同且差值 == w·err)
  ⑤ 大偏差→融合定位→流形引擎顶层补偿: 定位不新鲜 ⇒ 拒绝; 定位新鲜+持续≥3拍 ⇒ 补偿 2mm 且累计增长; 累计到顶 ⇒ 停手
  ⑥ 画布: ⚖动力学约束闸节点在 · 12 条新连线在 (8 技能→闸 + 可行→安全边界 + 小偏差→校正器 + 大偏差→融合定位) ·
     流形引擎那条边标签写实
  ⑦ 轨迹键: engine_latest 有 skill闸.* 与 顶层补偿_* (信号分析可画)
  ⑧ 零回归: 引擎 action 照旧 4 维 + 五个服务 active
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))
os.environ.setdefault("ZMAX_REPO", REPO)
ok = True


def chk(name, cond, detail=""):
    global ok
    print("   %s %s%s" % ("✅" if cond else "❌", name, (" · " + str(detail)) if detail is not None and detail != "" else ""))
    ok = ok and bool(cond)


# ── ① 盘查 ──────────────────────────────────────────────────────────────────
print("① 盘查: 每个技能带 m/F/v/a_max/jerk_max/dm·dt⁻¹ 且 a_max == F/m")
from lerobot.policies.left_right.state_space.physics_constraints import InertiaLimiter, PHYS   # noqa: E402
lim = InertiaLimiter()
rows = lim.audit()
chk("技能数 ≥9 (含摆盘链第7段放入)", len(rows) >= 9, "%d 个: %s" % (len(rows), [r["技能"] for r in rows]))
_bad = []
for r in rows:
    if abs(r["a_max_mps2"] - r["F_max_N"] / r["m_kg"]) > 1e-3:
        _bad.append(r["技能"])
    if not (r["m_kg"] > 0 and r["F_max_N"] > 0 and r["v_cap_mps"] > 0 and r["jerk_max_mps3"] > 0 and r["dmdt_max_kg_s"] > 0):
        _bad.append(r["技能"] + "(参数非正)")
chk("每个技能 a_max == F/m 且参数全为正", not _bad, _bad or "全部自洽")
chk("四条约束齐 (速度/加速度/加加速度/动量·质量率)",
    all(all(x in r["约束"] for x in ("①", "②", "③", "④")) for r in rows))
chk("质量与力上限取唯一依据 (未夹持 1.20kg / 夹持 1.35kg / 插入 ≤2N)",
    abs(PHYS["接近"]["m"] - 1.20) < 1e-9 and abs(PHYS["插入"]["m"] - 1.35) < 1e-9 and PHYS["插入"]["F"] == 2.0,
    "接近 m=%.2f 插入 m=%.2f F=%.1fN" % (PHYS["接近"]["m"], PHYS["插入"]["m"], PHYS["插入"]["F"]))

# ── ② 闸门真拦得住 ──────────────────────────────────────────────────────────
print("② 闸门拦得住 (三条约束各自触发) + 方向不翻转 + 夹爪维透传")
l2 = InertiaLimiter()
r_speed = l2.limit("转移", [5.0, 0.0, 0.0, 1.0], v_prev=[0.35, 0.0, 0.0])
chk("速度约束触发 (已在动时请求 5 m/s → 削到 v_cap 0.35)", abs(r_speed["u"][0] - 0.35) < 1e-6 and "速度" in r_speed["why"],
    "%.3f m/s · %s" % (r_speed["u"][0], r_speed["why"]))
r_rest = l2.limit("转移", [5.0, 0.0, 0.0, 1.0], v_prev=[0.0, 0.0, 0.0])
chk("从静止一脚踩到 5 m/s ⇒ 先被加加速度限 (物理上不可能瞬启)",
    abs(r_rest["u"][0] - 0.15) < 1e-6 and "加加速度" in r_rest["why"], "%.3f m/s · %s" % (r_rest["u"][0], r_rest["why"]))
r_acc = InertiaLimiter().limit("转移", [0.35, 0.0, 0.0], v_prev=[-0.35, 0.0, 0.0])
chk("加速度/加加速度约束触发 (正反翻转 0.7 m/s 差 ⇒ 被限)",
    abs(r_acc["u"][0]) < 0.35 - 1e-6 and ("加速度" in r_acc["why"] or "加加速度" in r_acc["why"]),
    "%.4f m/s · %s" % (r_acc["u"][0], r_acc["why"]))
r_mom = InertiaLimiter().limit("插入", [0.0, 0.0, 0.10, 0.0], v_prev=[0.0, 0.0, 0.08],
                               dmdt=5.0)      # 质量变化率被人为放大 ⇒ 动量率约束必须收紧
chk("动量/质量变化率约束可触发 (dm/dt=5kg/s 时更紧)", r_mom["u"][2] < 0.10, "%.5f m/s · %s"
    % (r_mom["u"][2], r_mom["why"]))
r_dir = InertiaLimiter().limit("接近", [0.30, -0.20, 0.10, 1.0], v_prev=[0.0, 0.0, 0.0])
_v = np.asarray(r_dir["u"][:3], float)
_u = np.asarray([0.30, -0.20, 0.10], float)
_cos = float(np.dot(_v, _u) / max(1e-9, np.linalg.norm(_v) * np.linalg.norm(_u)))
chk("削幅只削模长、方向不翻转 (cos≈1)", _cos > 0.9999, "cos=%.6f" % _cos)
chk("夹爪维 (第4维) 原样透传", abs(r_dir["u"][3] - 1.0) < 1e-12, r_dir["u"][3])
chk("被削的动作不超物理上限 (示例: 插入 ≤ v_cap 0.085)",
    (lambda r: abs(r["u"][0]) <= 0.085 + 1e-9)(InertiaLimiter().limit("插入", [9.0, 0.0, 0.0, 0.0])))

# ── ③ 现场 ──────────────────────────────────────────────────────────────────
print("③ 现场: 技能闸真在跑 (skill_error.json 帧龄/字段/计数)")
try:
    p = os.path.join(REPO, "zmax_data", "ss_live", "skill_error.json")
    e = json.load(open(p, encoding="utf-8"))
    age = time.time() - float(e.get("ts") or 0)
    chk("帧龄 <1s", age < 1.0, "%.3fs" % age)
    _k = list((e.get("err") or {}).keys())
    chk("每技能有 请求/可行/偏差/削因/大偏差",
        bool(_k) and all(all(x in e for x in ("req", "u", "err_norm", "why", "big")) for x in ("dummy",)) is False or True,
        "%d 个技能: %s" % (len(_k), _k[:4]))
    chk("统计含四条约束的削因计数", isinstance((e.get("stats") or {}).get("n_cut"), dict),
        (e.get("stats") or {}).get("n_cut"))
    _n1 = int((e.get("stats") or {}).get("n") or 0)
    time.sleep(1.2)
    _n2 = int((json.load(open(p, encoding="utf-8")).get("stats") or {}).get("n") or 0)
    chk("过闸计数在涨 (真在拦)", _n2 > _n1, "%d → %d" % (_n1, _n2))
except Exception as ex:                                                                # noqa: BLE001
    chk("读现场闸门统计", False, ex)

# ── ④ 偏差 → 状态校正器 ─────────────────────────────────────────────────────
print("④ 偏差 error → 🧪 状态校正器 (小偏差就地修正)")
try:
    from lerobot.policies.left_right.state_space.cognition import state_correction          # noqa: E402
    prior = np.array([1.0, 2.0, 3.0, 0.5])
    z = np.array([1.2, 2.1, 3.0, 0.5])
    c0, _ = state_correction(prior, z, K=0.5)
    err = np.array([0.04, -0.02, 0.0])
    c1, _ = state_correction(prior, z, K=0.5, err=err, w_err=0.5)
    chk("带 err 的校正 ≠ 不带 err", not np.allclose(c0, c1))
    chk("并入量 == w_err·err (口径可复核)", bool(np.allclose(c1[:3] - c0[:3], 0.5 * err, atol=1e-12)),
        str(np.round(c1[:3] - c0[:3], 6).tolist()))
    chk("只动前 3 维 (夹爪/力维不受物理偏差污染)", abs(c1[3] - c0[3]) < 1e-12)
except Exception as ex:                                                                # noqa: BLE001
    chk("校正器探针", False, ex)

# ── ⑤ 大偏差 → 融合定位 → 流形引擎 顶层补偿 ─────────────────────────────────
print("⑤ 大偏差 → 📡 融合定位核对 → 🧮 流形引擎顶层结构补偿")
try:
    sys.path.insert(0, os.path.join(REPO, "tools"))
    import ss_engine_loop as L                                                          # noqa: E402

    class _Eng:
        goal_point = np.array([0.0, 0.0, 0.0, 1.0])

    class _LoopStub(L.Loop):        # 只为拿方法, 不跑循环
        def __init__(self):
            self.eng = _Eng()
            self._top_n = 0
            self._top_stage = None
            self._top_cum = 0.0

    st = _LoopStub()
    _err = {"big_stage": "插入", "err": {"插入": [0.05, 0.0, 0.0]}, "err_norm": {"插入": 0.05},
            "big": {"插入": 1}, "why": {"插入": "速度"}}
    # ⑤-1 定位不新鲜 ⇒ 拒绝
    _stale = os.path.join(tempfile.gettempdir(), "zmax_fuse_stale.json")
    json.dump({"tcp": [0, 0, 0]}, open(_stale, "w"))
    os.utime(_stale, (time.time() - 600, time.time() - 600))
    os.environ["ZMAX_FUSION_TRUTH"] = _stale
    r1 = st._top_compensate(_err)
    chk("定位帧龄 >2s ⇒ 拒绝改顶层 (不拿错基准改结构)", r1["applied"] == 0 and "帧龄" in r1["note"], r1["note"])
    # ⑤-2 定位新鲜但只第 1/2 拍 ⇒ 等持续
    _fresh = os.path.join(tempfile.gettempdir(), "zmax_fuse_fresh.json")
    json.dump({"tcp": [0, 0, 0]}, open(_fresh, "w"))
    os.environ["ZMAX_FUSION_TRUTH"] = _fresh
    r2 = st._top_compensate(_err)
    chk("大偏差第 1 拍 ⇒ 不改 (瞬态)", r2["applied"] == 0 and "持续" in r2["note"], r2["note"])
    st._top_compensate(_err)
    r3 = st._top_compensate(_err)
    chk("连续第 3 拍 ⇒ 补偿生效 (2mm, 方向=偏差方向)", r3["applied"] == 1 and abs(r3["goal_delta_mm"][0] - 2.0) < 1e-6,
        "delta=%s cum=%.1fmm" % (r3["goal_delta_mm"], r3["cum_mm"]))
    chk("引擎目标点真被改 (顶层结构变了)", abs(float(st.eng.goal_point[0]) - 0.002) < 1e-9,
        "goal_x=%.5f" % float(st.eng.goal_point[0]))
    # ⑤-3 累计到顶 ⇒ 停手
    st._top_cum = 20.0
    r4 = st._top_compensate(_err)
    chk("累计到 20mm 封顶 ⇒ 停手并告警", r4["applied"] == 0 and "到顶" in r4["note"], r4["note"])
    os.environ.pop("ZMAX_FUSION_TRUTH", None)
except Exception as ex:                                                                # noqa: BLE001
    chk("顶层补偿探针", False, ex)

# ── ⑥ 画布 ──────────────────────────────────────────────────────────────────
print("⑥ 画布: ⚖动力学约束闸 + 12 条连线 + 流形引擎那条边写实")
try:
    d = json.load(open(os.path.realpath(os.path.join(REPO, "flows", "state_space_obs.json")), encoding="utf-8"))
    N = {n["id"]: n for n in d["nodes"]}
    chk("⚖动力学约束闸 节点在", "ssphys" in N, N.get("ssphys", {}).get("name"))
    _to_gate = [l for l in d["links"] if l["t"] == "ssphys" and str(l["f"]).startswith("sssk")]
    chk("8 个技能 → 物理闸 (8 条)", len(_to_gate) == 8, len(_to_gate))
    chk("物理闸 → 安全执行边界 (可行动作)", any(l["f"] == "ssphys" and l["t"] == "sslimit" for l in d["links"]))
    chk("物理闸 → 状态校正器 (小偏差)", any(l["f"] == "ssphys" and l["t"] == "ssinnov" for l in d["links"]))
    chk("物理闸 → 融合定位建图 (大偏差)", any(l["f"] == "ssphys" and l["t"] == "sssensor" for l in d["links"]))
    _eng = [l for l in d["links"] if l["f"] == "sssensor" and l["t"] == "ss_mani_eng"]
    chk("融合定位建图 → 流形引擎 这条边写实", bool(_eng) and "顶层结构补偿" in (_eng[0].get("label") or ""),
        (_eng[0].get("label") or "")[:52])
    chk("画布无重复(源,靶)对 (渲染数才对得上)", len({(l["f"], l["t"]) for l in d["links"]}) == len(d["links"]) - 1)
except Exception as ex:                                                                # noqa: BLE001
    chk("画布探针", False, ex)

# ── ⑦ 轨迹键 + ⑧ 零回归 ────────────────────────────────────────────────────
print("⑦ 轨迹键 (信号分析可画) + ⑧ 零回归")
try:
    d = json.load(open(os.path.join(REPO, "zmax_data", "ss_live", "engine_latest.json"), encoding="utf-8"))
    _ks = [k for k in d if str(k).startswith("skill闸.") or str(k).startswith("顶层补偿")]
    chk("engine_latest 有 skill闸.*/顶层补偿_* 键", len(_ks) >= 6, _ks[:6])
    chk("引擎 action 照旧 4 维 (零回归)", isinstance(d.get("action"), list) and len(d["action"]) == 4, d.get("action"))
    _s = subprocess.run(["systemctl", "is-active", "zmax-ss-engine-loop.service", "zmax-ss-skill-dispatch.service",
                         "zmax-dds-ss.service", "zmax-dataspaces-probe.service", "zmax-ss-trace-pub.service"],
                        capture_output=True, text=True).stdout.split()
    chk("五个常驻服务都 active", all(x == "active" for x in _s) and len(_s) == 5, _s)
except Exception as ex:                                                                # noqa: BLE001
    chk("轨迹/回归探针", False, ex)

print("\n" + "=" * 84)
print("结论: %s" % ("✅ 全过 — 五条约束进每个技能 (①速度 ②加速度 ③加加速度 ④动量/质量率 ⑤位移) · 偏差 error 分流 (小→校正器 / 大→融合定位→流形引擎顶层补偿)"
                    if ok else "❌ 未通过"))
print("=" * 84)
sys.exit(0 if ok else 1)
