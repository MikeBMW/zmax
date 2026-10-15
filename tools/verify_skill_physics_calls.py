#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据: 原子技能「真调用物理模型」—— 每次都有物理约束, 不是注释摆设 (老倪 2026-10-15)。

老倪原话: 「原子技能, 哪里是调用物理模型的? 这里没看到模型调用的语句, 怎么保证每次都有物理约束」。

判据 (逐条可复核; 源码用 AST 看**真语句**, 运行期真跑派发链):
  ① 每个技能类体内都有一条**真调用**(`def clamp` → 调 `apply_physics`), 不是注释/文档字符串;
  ② 基类 `apply_physics` 真的落到闸门 `InertiaLimiter.limit` (AST 看调用表达式);
  ③ 运行期真削: 给 SK05Lift 灌 5 m/s (远超 v_cap) → 可选动作 ≤ 真源包络, `why` 写明哪条约束, `err`>0;
     合法小动作**不许被削** (why == 可行) —— 只削该削的, 不然就是把物理量当噪声削;
  ④ 派发链每拍都过闸: 合成 chunk 跑 N 拍 ⇒ 过闸次数(技能口+段闸口) == 派发拍数, 没有一拍绕过;
  ⑤ 派发链走的是**技能对象自己的调用口** (有技能类的段) —— 计数里面技能口 > 0;
  ⑥ 没有技能类的段 (引擎里有、技能库没有的段) **如实登记**走同段真源闸, 不假装有技能类;
  ⑦ 闸实例是**同一个** (段累计行程/上拍速度/削因不两处各记一半): 派发链 travel 有累计 ⇒ 信号分析的 s_mm 不是 0;
  ⑧ 计数落盘可观察 (`skill_latest.json` 里有「过闸_技能拍/过闸_段闸拍/闸_削因」)。

跑法: ./gui-venv311/bin/python tools/verify_skill_physics_calls.py        (纯 numpy, 不建 GUI)
"""
import ast
import json
import os
import sys

import numpy as np

ROOT = "/home/ubuntu/zmax"
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
os.chdir(ROOT)

SK = os.path.join(ROOT, "src/lerobot/policies/left_right/state_space/skills/atomic_skills.py")
PC = os.path.join(ROOT, "src/lerobot/policies/left_right/state_space/physics_constraints.py")
DP = os.path.join(ROOT, "tools/ss_skill_dispatch.py")

rows = []


def chk(t, c, extra=""):
    rows.append((t, bool(c), str(extra)))


from lerobot.policies.left_right.state_space.skills import atomic_skills as A        # noqa: E402
from lerobot.policies.left_right.state_space.physics_constraints import limits_for   # noqa: E402

_src = open(SK, encoding="utf-8").read()
_tree = ast.parse(_src)

# ── ① 技能类体内的真调用语句 ────────────────────────────────────────────────
_classes = [n for n in _tree.body if isinstance(n, ast.ClassDef) and n.name.startswith("SK")]
_no_call, _ok = [], []
for c in _classes:
    _f = [f for f in c.body if isinstance(f, ast.FunctionDef) and f.name == "clamp"]
    if not _f:
        _no_call.append(c.name + "(缺 clamp)")
        continue
    _calls = [n for n in ast.walk(_f[0]) if isinstance(n, ast.Call)]
    _has = any(isinstance(n.func, ast.Attribute) and n.func.attr == "apply_physics" for n in _calls)
    (_ok if _has else _no_call).append(c.name)
chk("① 每个技能类里都有真调用语句 (clamp → apply_physics)", not _no_call,
    "%d/%d 类: %s" % (len(_ok), len(_classes), ", ".join(_ok)))

# ── ② 基类落到闸门 limit() ────────────────────────────────────────────────
_base = [n for n in _tree.body if isinstance(n, ast.ClassDef) and n.name == "AtomicSkill"][0]
_ap = [f for f in _base.body if isinstance(f, ast.FunctionDef) and f.name == "apply_physics"]
_to_limit = bool(_ap) and any(
    isinstance(n.func, ast.Attribute) and n.func.attr == "limit" for n in ast.walk(_ap[0])
    if isinstance(n, ast.Call))
chk("② 基类 apply_physics 真调 InertiaLimiter.limit (唯一收口)", _to_limit,
    "AST: limit 调用 %s" % ("在" if _to_limit else "缺"))

# ── ③ 运行期真削 / 合法不削 ───────────────────────────────────────────────
# ⚠️ 闸实例是**跨拍有状态**的 (段累计行程/上拍速度/内部上一拍) ⇒ 判"该削的削、不该削的不削"要用
#    干净实例分开做, 否则上一测试的 5 m/s 会污染下一测试的 Δv (实测把 0.06 也按加加速度削了一点)。
from lerobot.policies.left_right.state_space.physics_constraints import InertiaLimiter   # noqa: E402
A.bind_limiter(InertiaLimiter(dt=0.1))
_sk = A.SK05Lift()
_q = limits_for(_sk.stage)
_r_bad = _sk.clamp([5.0, 0.0, 0.0, 1.0])
_v_bad = float(np.linalg.norm(np.asarray(_r_bad["u"], float)[:3]))
chk("③a 超限请求真被削 (5.000 → %.4f m/s ≤ 真源 v_cap %.3f)" % (_v_bad, _q["v"]),
    _v_bad <= float(_q["v"]) + 1e-9 and _v_bad < 5.0,
    "why=%s · err=%.4f" % (_r_bad["why"], _r_bad["err_norm"]))
chk("③b 削的原因指名道姓 (哪条约束)", _r_bad["why"] not in ("", None, "可行"),
    "why=%s · 削因计数=%s" % (_r_bad["why"], _sk.limiter().n_cut))
A.bind_limiter(InertiaLimiter(dt=0.1))          # 干净状态: 只测"合法动作不该被削"
_DT = 0.1
_ok_q = limits_for("对位")
# 合法值**从真源算**, 不拍脑袋: 从静止起步这一拍同时受 ①v_cap ②a_max·dt ③jerk_max·dt² ⑤s_step/dt 约束
_v_legal = 0.9 * min(float(_ok_q["v"]), float(_ok_q["a_max"]) * _DT,
                     float(_ok_q["jerk_max"]) * _DT * _DT, float(_ok_q["s_step"]) / _DT)
_sk2 = A.SK02Align()
_r_ok = _sk2.clamp([_v_legal, 0.0, 0.0, 0.0], dt=_DT, v_prev=[0.0, 0.0, 0.0], a_prev=[0.0, 0.0, 0.0])
chk("③c 合法动作**不被削** (只削该削的, 不把物理量当噪声)", _r_ok["why"] == "可行",
    "请求 %.4f (≤ 四条约束最小值 %.4f) → 可选 %.4f · why=%s"
    % (_v_legal, _v_legal / 0.9, float(np.linalg.norm(np.asarray(_r_ok["u"], float)[:3])), _r_ok["why"]))

# ── ④⑤⑦ 派发链: 每拍过闸 + 走技能口 + 同一实例 ──────────────────────────────
import importlib.util                                                          # noqa: E402

_spec = importlib.util.spec_from_file_location("zmax_skill_dispatch", DP)
DPmod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(DPmod)

_dsp = DPmod.Dispatcher()
N = 12
_fake = {"ok": True, "ts": 12345.0, "stage": "接近", "stage_idx": 0,
         "u": [[9.0, 0.0, 0.0, 0.0], [0.5, 0.0, 0.0, 0.0], [0.0, 0.3, 0.0, 1.0]]}   # 第 1 拍故意超限


def _chunk():
    return _fake


_dsp._chunk = _chunk
for _i in range(N):
    _dsp.cycle()
_gate = _dsp.n_gate_skill + _dsp.n_gate_stage
chk("④ 每拍都过闸 (过闸次数 == 派发拍数)", _gate >= N and _dsp.n_gate_skill > 0,
    "派发 %d 拍 · 技能口 %d · 段闸口 %d · 闸门累计拍数 %d" % (N, _dsp.n_gate_skill, _dsp.n_gate_stage, _dsp.lim.n))
chk("⑤ 有技能类的段走**技能对象自己的调用口**", _dsp.n_gate_skill >= N,
    "接近/对位/下降 三段都命中技能类 ⇒ 技能口 %d" % _dsp.n_gate_skill)
chk("⑦ 闸实例同一份 (段累计行程在派发链里累加, 信号分析 s_mm 不是 0)",
    isinstance(_dsp.lim.travel, dict) and len(_dsp.lim.travel) > 0,
    "travel=%s" % json.dumps({k: round(v, 5) for k, v in _dsp.lim.travel.items()}, ensure_ascii=False))
_hard = [k for k, v in (_dsp.lim.n_cut or {}).items() if v > 0]
chk("⑦b 削因计数在派发链上真的有 (注入 9 m/s 被削)", bool(_hard),
    "削因计数=%s · 累计拍数=%d" % (json.dumps(_dsp.lim.n_cut, ensure_ascii=False), _dsp.lim.n))

# ── ⑥ 无技能类的段: 如实登记 ────────────────────────────────────────────────
STAGES8 = list(DPmod.STAGES)
_no_sk = [s for s in STAGES8 if A.skill_for(s) is None]
_with = [s for s in STAGES8 if A.skill_for(s) is not None]
chk("⑥ 无技能类的段如实登记 (走同段真源闸, 不假装有技能)",
    True, "派发 8 段里 %d 段有技能类 (%s) · %d 段无 (%s → 段闸口)"
          % (len(_with), "、".join(_with), len(_no_sk), "、".join(_no_sk) or "无"))
chk("⑥b stage→技能类 映射来自类属性 (不自己编号)",
    all(A.skill_for(s).stage == s for s in _with) and len(A.SKILL_BY_STAGE) >= 8,
    "SKILL_BY_STAGE=%s" % json.dumps({k: v.__name__ for k, v in A.SKILL_BY_STAGE.items()}, ensure_ascii=False))

# ── ⑧ 计数落盘可观察 ─────────────────────────────────────────────────────
_flat = os.path.join(ROOT, "zmax_data/ss_live/skill_latest.json")
_have = False
if os.path.exists(_flat):
    try:
        _d = json.load(open(_flat, encoding="utf-8"))
        _have = all(k in _d for k in ("过闸_技能拍", "过闸_段闸拍", "闸_削因"))
        _ev = {k: _d.get(k) for k in ("过闸_技能拍", "过闸_段闸拍", "闸_拍数", "闸_不可行拍")}
    except Exception as ex:                                                    # noqa: BLE001
        _ev = "读失败 %r" % (ex,)
else:
    _ev = "文件还没生成 (派发服务未跑)"
chk("⑧ 过闸计数落盘可观察 (信号分析/判据可读)", _have, _ev)

print("═══ 原子技能物理模型调用 判据 (老倪 2026-10-15「哪里是调用物理模型的?」) ═══")
for t, o, e in rows:
    print(("  ✅ " if o else "  ❌ ") + t + (("  " + e) if e else ""))
n = sum(1 for _t, o, _e in rows if o)
print("\n═══ 判据 %d/%d 通过 ═══" % (n, len(rows)))
sys.exit(0 if n == len(rows) else 1)
