# -*- coding: utf-8 -*-
"""3D 场景 ↔ 原子技能位姿 一致性判据 (给全局数据空间 QoS 报警用)。

老倪 2026-10-17: 「L2 原子技能 SK01~SK08, 每个发出的信号, 尤其是位姿 x y z a b c,
   结合 3D 插拔场景一个一个检查, 每个信号如果与 3D 动画不符合, 都要在全局数据空间 QoS 报警」

口径 (都可复核):
  · 场景真值 = trace_live.json 的 末端_x/y/z (m ⇒ ×1000 mm), 这是 3D 动画**同一拍**用的数
  · 技能位姿 = skill_phys.json skills.SKxx.x/y/z (mm, 由 ss_skill_dispatch 发布)
  · 偏差 > tol_mm ⇒ fail 报警 (数据/链路错); > tol_mm/2 ⇒ warn (抖动/一拍差)
  · 姿态 a/b/c: 3D 出口**不含姿态** (ss_dreamview 3757), tap 停更时只能是 -1
    ⇒ 不下发假姿态, 改为一条 warn「姿态不可观测」, 恢复后自动消失
"""
from __future__ import annotations

AXES = ("x", "y", "z")
ATT = ("a", "b", "c")


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def scene_xyz(tl):
    """3D 场景末端 (mm)。缺一轴就返回 None —— 不拿 0 冒充。"""
    if not isinstance(tl, dict):
        return None
    ex, ey, ez = tl.get("末端_x"), tl.get("末端_y"), tl.get("末端_z")
    if not all(_num(v) for v in (ex, ey, ez)):
        arr = tl.get("末端")
        if isinstance(arr, (list, tuple)) and len(arr) >= 3 and all(_num(v) for v in arr[:3]):
            ex, ey, ez = arr[0], arr[1], arr[2]
        else:
            return None
    return (float(ex) * 1000.0, float(ey) * 1000.0, float(ez) * 1000.0)


def check(tl, sp, tol_mm=5.0):
    """→ [(level, object, msg)] ; level ∈ fail/warn/info。"""
    out = []
    ref = scene_xyz(tl)
    skills = (sp or {}).get("skills") or {}
    if ref is None:
        out.append(("warn", "3D 场景", "trace_live 没有末端 x/y/z ⇒ 无法比对技能位姿"))
        return out
    if not skills:
        out.append(("warn", "原子技能", "skill_phys 没有 skills ⇒ 无法比对"))
        return out
    _att_reported = False
    for code in sorted(skills):
        if not str(code).startswith("SK"):
            continue
        rec = skills[code]
        if not isinstance(rec, dict):
            continue
        stage = rec.get("stage") or ""
        _bad = []
        for ax, rf in zip(AXES, ref):
            v = rec.get(ax)
            if not _num(v) or float(v) == -1.0:
                _bad.append("%s=无值" % ax)
                continue
            d = abs(float(v) - rf)
            if d > tol_mm:
                out.append(("fail", "%s %s · %s" % (code, stage, ax),
                            "与 3D 场景不符: 信号 %.2f mm vs 场景 %.2f mm (Δ%.2f > %.1f)"
                            % (float(v), rf, d, tol_mm)))
            elif d > tol_mm / 2.0:
                out.append(("warn", "%s %s · %s" % (code, stage, ax),
                            "与 3D 场景有偏差: Δ%.2f mm (阈值 %.1f)" % (d, tol_mm)))
        if _bad and len(_bad) == 3:
            out.append(("fail", "%s %s" % (code, stage), "位置三轴全无值 (%s)" % ",".join(_bad)))
        if not _att_reported:
            vals = [rec.get(k) for k in ATT]
            if any((not _num(v)) or float(v) == -1.0 for v in vals):
                src = rec.get("pose_src") or ""
                out.append(("warn", "姿态 a/b/c",
                            "姿态不可观测: 3D 场景出口不含姿态, tap 位姿源%s ⇒ a/b/c 不做假值 (源: %s)"
                            % ("停更" if "trace_live" in src else "未提供", src or "—")))
                _att_reported = True
    return out
