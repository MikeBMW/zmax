#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""skill_physics_calib.py — ⚖ 原子技能物理参数标定 (速度 v / 加速度 a / 位移 s, 每项带物理上下限)

老倪 (2026-10-15): 「每个原子技能，应该有个物理模型 … 表示物理世界的连续性惯性约束，代码在哪里？
这些物理参数 速度 v、加速度 a、位移 s 需要可以标定，比如上限下限、最大值最小值」

分工 (单一唯一依据, 不写第二套):
  · 物理模型/闸门代码 → src/lerobot/policies/left_right/state_space/physics_constraints.py
    ①速度 ‖v‖≤v_cap ②加速度 ‖Δv‖≤a_max·dt ③加加速度 ‖Δa‖≤jerk_max·dt
    ④动量/质量率 ‖m·Δv+v·Δm‖≤F_max·dt ⑤位移 ‖v‖·dt≤s_step 且 段累计行程≤s_max
  · 参数**标定面**= 本工具 + 唯一依据文件 config/calib/zmax_skill_physics.json
    唯一依据里的每个物理量都写成 {value, min, max, unit, src} —— min/max 就是物理上下限。
  · 本工具只做四件事: 从唯一依据生成初值 / 打印标定表 / 改值(越界拒绝) / 校核。

物理上下限从哪来 (不是拍的):
  v      上限 = safety.py::VEL_LIMIT (全局速度硬上限)          · 下限 = 5 mm/s (再低是末端磨蹭)
  v_min  上限 = 该段 v_cap (下限不能高于上限)                   · 下限 = 0
  a      上限 = 夹爪最大夹持力 12 N / 最小运动质量 1.2 kg = 10 m/s² (牛顿二定律) · 下限 = 0.05
  s_step 上限 = **v_cap × dt** (单拍位移不可能超过"速度上限×拍") ⇒ 位置与速度的导数关系, 硬约束
        下限 = 0.2 mm (亚毫米级微动仍可标)
  s      上限 = safety.py::POS_LIMIT (位置/动作幅值上限 0.6 m)   · 下限 = 0.5 mm
  jerk   上限 = 60 m/s³ (实测 P99 14.84 的 4× 余量)             · 下限 = 1.0
  m      上限 = 3.0 kg (夹爪 1.2 + 光模块 0.15 + 余量)           · 下限 = 0.5
  F      上限 = 12.0 N (夹爪最大夹持力)                          · 下限 = 0.5
  dmdt   上限 = 0.5 kg/s (抓放实测 0.15 kg / 0.30 s)             · 下限 = 0

CLI:
  gui-venv311/bin/python tools/skill_physics_calib.py --init-from-sources   # 从引擎/状态机唯一依据生成唯一依据文件
  gui-venv311/bin/python tools/skill_physics_calib.py --table               # 标定表 (含上下限/是否越界)
  gui-venv311/bin/python tools/skill_physics_calib.py --set 接近 v 0.30     # 改一个值 (越界→拒绝)
  gui-venv311/bin/python tools/skill_physics_calib.py --set SK01 v 0.30     # 也可以按技能号 SK01..SK08
  gui-venv311/bin/python tools/skill_physics_calib.py --set-bound 接近 v --max 0.60
  gui-venv311/bin/python tools/skill_physics_calib.py --check               # 有越界/缺项 → 非零退出
  gui-venv311/bin/python tools/skill_physics_calib.py --json
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CALIB = os.path.join(ROOT, "config", "calib", "zmax_skill_physics.json")


def calib_path():
    """唯一依据路径 (ZMAX_SKILL_PHYS_JSON 可覆盖 —— 判据脚本用临时副本来验标定, 不动在役唯一依据)。"""
    return os.environ.get("ZMAX_SKILL_PHYS_JSON") or CALIB


CALIB_BAK_DIR = os.path.join(ROOT, "config", "calib")
COGNITION = os.path.join(ROOT, "src", "lerobot", "policies", "left_right", "state_space", "cognition.py")
PHYS_SRC = os.path.join(ROOT, "src", "lerobot", "policies", "left_right", "state_space", "physics_constraints.py")
SAFETY_SRC = os.path.join(ROOT, "src", "lerobot", "policies", "left_right", "state_space", "safety.py")
SIMREAL = os.path.join(ROOT, "tools", "gui", "state_space_sim_real.py")

DT = 0.1                       # 控制拍 (10 Hz) — 与 InertiaLimiter 默认一致
PARAMS = ("v", "v_min", "a", "s", "s_step", "jerk", "m", "F", "dmdt")

# ── 物理上下限表 (每条都注明唯一依据) ─────────────────────────────────────────────
BOUND_SRC = {
    "v":      "v ≤ safety.py::VEL_LIMIT (全局速度硬上限 1.0 m/s); v ≥ 0.005 m/s (再低=末端磨蹭)",
    "v_min":  "0 ≤ v_min ≤ 该段 v_cap (最小趋近速度, cognition.STAGE_V_MIN)",
    "a":      "a ≤ 夹爪最大夹持力 12N / 最小运动质量 1.2kg = 10 m/s² (牛顿二定律 F=m·a); a ≥ 0.05",
    "s":      "s ≤ safety.py::POS_LIMIT (位置/动作幅值上限 0.6 m); s ≥ 0.0005 m",
    "s_step": "s_step ≤ v_cap × dt (单拍位移不可能超过速度上限×拍 = 位置与速度的导数关系); s_step ≥ 0.0002 m",
    "jerk":   "jerk ≤ 60 m/s³ (真机实测 P99 14.84 的 4× 余量); jerk ≥ 1.0",
    "m":      "0.5 ≤ m ≤ 3.0 kg (末端夹爪 1.2 kg + 光模块 0.15 kg + 余量)",
    "F":      "0.5 ≤ F ≤ 12.0 N (夹爪最大夹持力; 金手指保护 ≤2 N 过盈段)",
    "dmdt":   "0 ≤ dm/dt ≤ 0.5 kg/s (抓取建立/释放实测 0.15 kg / 0.30 s)",
}
VEL_LIMIT = 1.0
POS_LIMIT = 0.6
GRIP_FORCE_MAX = 12.0
M_MIN, M_MAX = 0.5, 3.0
DMDT_MAX = 0.5
JERK_MAX_HARD = 60.0

# 技能号 ↔ 阶段 (唯一依据: atomic_skills.py 的类名/code/stage)
ATOMIC_SKILLS_PY = os.path.join(ROOT, "src", "lerobot", "policies", "left_right",
                                 "state_space", "skills", "atomic_skills.py")


def parse_skill_classes():
    """从 atomic_skills.py 解析 SK 类 (类名/code/stage) —— 技能号↔阶段 的**唯一依据**。

    老倪口径: 不许自己编编号。这里逐个类读 (SK07 在插拔链=插入、摆盘链=放入, 同号两支都保留)。
    """
    try:
        tree = ast.parse(open(ATOMIC_SKILLS_PY, encoding="utf-8").read())
    except Exception:                                                       # noqa: BLE001
        return []
    out = []
    for n in tree.body:
        if isinstance(n, ast.ClassDef) and n.name.startswith("SK"):
            code = stage = None
            for st in n.body:
                if isinstance(st, ast.Assign) and isinstance(st.targets[0], ast.Name):
                    if st.targets[0].id == "code":
                        code = _lit(st.value)
                    elif st.targets[0].id == "stage":
                        stage = _lit(st.value)
            if code and stage:
                out.append({"cls": n.name, "code": code, "stage": stage})
    return out


SKILL_CODE2STAGE = {}   # 兼容旧读取方: 由 build_from_sources() 填 (code → 第一条 stage)


def _skill_code_map():
    """code → stage (第一条; SK07 → 插入)。同号的摆盘支 (放入) 请按类名 SK07Place 引用。"""
    m = {}
    for c in parse_skill_classes():
        m.setdefault(c["code"], c["stage"])
    return m
# 各段**几何行程 s** 的唯一依据 (有常量的引常量, 没有的诚实标"待现场标定")
S_SRC = {
    "接近":  (0.60,  "safety.POS_LIMIT 安全包络 (工位跨度, 待现场标定)"),
    "对位":  (0.06,  "cognition.ActionModulator.align_xy_coarse=0.06 (粗对位窗口)"),
    "下降":  (0.05,  "state_space_sim_real.STAGE_ALIGN_H=0.05 (对位悬停→抓握点)"),
    "抓取":  (0.006, "深夹行程 ~6 mm (sim_real grasp 段)"),
    "抬起":  (0.16,  "state_space_sim_real.STAGE_LIFT=0.16"),
    "转移":  (0.60,  "safety.POS_LIMIT 安全包络 (工位跨度, 待现场标定)"),
    "插入":  (0.020, "库深 ~20 mm (cognition.py:113 注释 '孔深~20mm')"),
    "完成":  (0.002, "sim_real insert_depth 判据 0.002 (头离终点 6mm 内算完成)"),
    "拔出":  (0.045, "cognition.ActionModulator.pull_out_m=0.045"),
    "AOI转移": (0.60, "safety.POS_LIMIT 安全包络 (AOI 工位跨度, 待现场标定)"),
    "AOI检测": (0.030, "对焦伺服行程 30 mm (focus_quality.travel_mm=30)"),
    "回程":  (0.60,  "safety.POS_LIMIT 安全包络 (回程跨度, 待现场标定)"),
    "放下":  (0.060, "摆盘放下行程 ~60 mm (PULL_OUT 级)"),
}


# ───────────────────── 从唯一依据源码解析 (不在本文件里预先固定引擎值) ─────────────────────
def _lit(node):
    """字面量求值 (兼容 dict(...) 调用与 {..} 字典) — 只读源码, 不执行代码。"""
    try:
        return ast.literal_eval(node)
    except Exception:                                                       # noqa: BLE001
        pass
    if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "dict":
        d = {}
        for k in node.keywords:
            if k.arg is None:
                return None
            d[k.arg] = _lit(k.value)
        return d
    if isinstance(node, ast.Dict):
        return {_lit(k): _lit(v) for k, v in zip(node.keys, node.values)}
    return None


def _parse_dict_from_source(path, names, cls=None):
    """从 .py 源码里解析字面量 dict (AST, 不执行代码) — 保证标定初值取自唯一依据。"""
    tree = ast.parse(open(path, encoding="utf-8").read())
    out = {}
    for n in ast.walk(tree):
        if isinstance(n, (ast.Assign, ast.AnnAssign)):
            tg = n.targets[0] if isinstance(n, ast.Assign) else n.target
            nm = tg.id if isinstance(tg, ast.Name) else (tg.attr if isinstance(tg, ast.Attribute) else None)
            if nm in names:
                v = _lit(n.value)
                if isinstance(v, dict):
                    out[nm] = v
    return out


def _parse_phys_table():
    """解析 physics_constraints.PHYS (每技能 m/F/v/dmdt) + JERK_REF。"""
    tree = ast.parse(open(PHYS_SRC, encoding="utf-8").read())
    phys, ref = {}, {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name):
            nm = n.targets[0].id
            v = _lit(n.value)
            if nm == "PHYS" and isinstance(v, dict):
                phys = v
            elif nm in ("JERK_REF", "JERK_V_REF", "BIG_ERR") and v is not None:
                ref[nm] = v
    return phys, ref


def build_from_sources():
    """生成唯一依据 dict: 每个阶段 9 个物理量, 每项 {value,min,max,unit,src}。"""
    global SKILL_CODE2STAGE
    skill_classes = parse_skill_classes()
    SKILL_CODE2STAGE = _skill_code_map()
    cog = _parse_dict_from_source(COGNITION, {"STAGE_V_CAP", "STAGE_V_MIN"})
    vcap = cog.get("STAGE_V_CAP", {})
    vmin = cog.get("STAGE_V_MIN", {})
    phys, ref = _parse_phys_table()
    jerk_ref = float(ref.get("JERK_REF", 15.0))
    jerk_v_ref = float(ref.get("JERK_V_REF", 0.35))
    stages = []
    for st in list(vcap.keys()) + [s for s in phys if s not in vcap]:
        if st not in stages:
            stages.append(st)
    out = {}
    for st in stages:
        p = phys.get(st, {})
        # v: 优先状态机 STAGE_V_CAP (引擎真值); 引擎没有此段名时退回 PHYS 技能自带 v
        if st in vcap:
            v = float(vcap[st])
            v_src = "cognition.STAGE_V_CAP.%s=%s" % (st, vcap[st])
        else:
            v = float(p.get("v", 0.0))
            v_src = ("physics_constraints.PHYS[%s].v=%s (⚠️ cognition.STAGE_V_CAP 无此段名 — "
                     "引擎里可能叫别的名字, 待统一)" % (st, p.get("v")))
        m = float(p.get("m", 1.35))
        F = float(p.get("F", 5.0))
        dmdt = float(p.get("dmdt", 0.10))
        a = F / max(1e-6, m)
        s_val, s_src = S_SRC.get(st, (POS_LIMIT, "safety.POS_LIMIT (未标定段占位)"))
        s_step = v * DT
        jerk = jerk_ref * max(0.15, min(1.0, v / jerk_v_ref))
        out[st] = {
            "v":      _q(v, 0.005, VEL_LIMIT, "m/s", v_src),
            "v_min":  _q(float(vmin.get(st, 0.0)), 0.0, v, "m/s",
                         "cognition.STAGE_V_MIN.%s=%s%s" % (st, vmin.get(st, 0.0),
                                                            "" if st in vmin else " (未设 ⇒ 0, 待标定)")),
            "a":      _q(a, 0.05, GRIP_FORCE_MAX / 1.2, "m/s^2", "F/m = %.2fN/%.2fkg (牛顿二定律)" % (F, m)),
            "s":      _q(float(s_val), 0.0005, POS_LIMIT, "m", s_src),
            "s_step": _q(s_step, 0.0002, v * DT, "m", "v_cap×dt = %.3f×%.1f (单拍位移上限)" % (v, DT)),
            "jerk":   _q(jerk, 1.0, JERK_MAX_HARD, "m/s^3",
                         "实测 P99 %.2f × (v/%.2f) 缩放" % (jerk_ref, jerk_v_ref)),
            "m":      _q(m, M_MIN, M_MAX, "kg", "physics_constraints.PHYS[%s].m" % st),
            "F":      _q(F, 0.5, GRIP_FORCE_MAX, "N", "physics_constraints.PHYS[%s].F" % st),
            "dmdt":   _q(dmdt, 0.0, DMDT_MAX, "kg/s", "physics_constraints.PHYS[%s].dmdt" % st),
        }
    return {"_doc": "L2 原子技能物理参数标定唯一依据 (v/a/s + m/F/jerk/dmdt, 每项带物理上下限 min/max)。"
                    "写: tools/skill_physics_calib.py --set | 读: physics_constraints.limits_for()"
                    " (缺失时回退内置 PHYS 表)。",
            "_bounds_policy": "value 必须落在 [min,max]; CLI 越界拒绝, 运行期越界由 limiter 夹回并标 clamp。",
            "dt": DT, "skill_code2stage": SKILL_CODE2STAGE, "skills": skill_classes,
            "bounds_src": BOUND_SRC,
            "stages": out}


def _q(value, lo, hi, unit, src):
    return {"value": round(float(value), 6), "min": round(float(lo), 6), "max": round(float(hi), 6),
            "unit": unit, "src": src}


# ───────────────────────────── 读写 ─────────────────────────────
def load():
    p = calib_path()
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d.get("stages"), dict) else None
    except Exception:                                                       # noqa: BLE001
        return None


def save(d):
    p = calib_path()
    os.makedirs(os.path.dirname(p) or CALIB_BAK_DIR, exist_ok=True)
    if os.path.exists(p):
        shutil.copy2(p, p + ".bak_%s" % time.strftime("%Y%m%d_%H%M%S"))
    d["_generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1, sort_keys=False)
    with open(p, encoding="utf-8") as f:          # 回读核验 (改文件必回读)
        back = json.load(f)
    return back


def resolve_stage(key, d):
    """接受阶段名 (接近) 或技能号 (SK01)。"""
    if key in d["stages"]:
        return key
    k = str(key).upper().replace("SKILL", "SK")
    for x in (d.get("skills") or []):                  # 先按类名精确匹配 (SK07Place → 放入)
        if k == str(x.get("cls", "")).upper():
            return x["stage"]
    for code, st in d.get("skill_code2stage", {}).items():   # 再按技能号 (SK07 → 插入)
        if k == code:
            return st
    return None


def validate(d):
    """返回问题清单: 缺参/越界/上下限反了 —— 空 = 干净。"""
    bad = []
    for st, ps in d["stages"].items():
        for p in PARAMS:
            q = ps.get(p)
            if not isinstance(q, dict):
                bad.append("%s.%s 缺项" % (st, p))
                continue
            lo, hi, val = q.get("min"), q.get("max"), q.get("value")
            if lo is None or hi is None or val is None:
                bad.append("%s.%s 上下限/值缺失" % (st, p))
            elif lo > hi:
                bad.append("%s.%s 上下限反了: min=%s > max=%s" % (st, p, lo, hi))
            elif not (lo - 1e-12 <= val <= hi + 1e-12):
                bad.append("%s.%s 越界: value=%s ∉ [%s, %s] (%s)" % (st, p, val, lo, hi, q.get("unit")))
    return bad


def _dw(s):
    """显示宽度 (东亚宽字符算 2) — 中文列名不加这个会串列。"""
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in str(s))


def _col(s, w):
    s = str(s)
    return s + " " * max(0, w - _dw(s))


def table(d, only=None):
    stages = [only] if only else list(d["stages"].keys())
    W = (6, 9, 14, 9, 10, 10, 9, 7, 7, 8)
    print("═" * 96)
    print("⚖ 原子技能物理参数标定表 (唯一依据 %s)" % os.path.relpath(CALIB, ROOT))
    print("   v 速度 m/s · a 加速度 m/s² · s 段行程 m · s_step 单拍位移上限 m · jerk m/s³ · m kg · F N · dmdt kg/s")
    print("═" * 96)
    print(_col("技能", W[0]) + _col("阶段", W[1]) + _col("v≤(v_min)", W[2]) + _col("a≤", W[3]) +
          _col("s≤", W[4]) + _col("s_step≤", W[5]) + _col("jerk≤", W[6]) + _col("m", W[7]) +
          _col("F≤", W[8]) + _col("dmdt≤", W[9]))
    print("-" * 96)
    sk = d.get("skills") or [{"code": c, "stage": v} for c, v in d.get("skill_code2stage", {}).items()]
    pairs = [(x["code"], x["stage"]) for x in sk if x["stage"] in d["stages"]]
    pairs += [("—", v) for v in d["stages"] if v not in [x[1] for x in pairs]]   # 只有引擎/PHYS 名、无 SK 类的段
    for code, st in pairs:
        if only and st != only:
            continue
        ps = d["stages"][st]
        print(_col(code, W[0]) + _col(st, W[1]) +
              _col("%.3f(%.3f)" % (ps["v"]["value"], ps["v_min"]["value"]), W[2]) +
              _col("%.2f" % ps["a"]["value"], W[3]) +
              _col("%.3f" % ps["s"]["value"], W[4]) +
              _col("%.4f" % ps["s_step"]["value"], W[5]) +
              _col("%.1f" % ps["jerk"]["value"], W[6]) +
              _col("%.2f" % ps["m"]["value"], W[7]) +
              _col("%.1f" % ps["F"]["value"], W[8]) +
              _col("%.2f" % ps["dmdt"]["value"], W[9]))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="原子技能物理参数标定 (v/a/s + 上下限)")
    ap.add_argument("--init-from-sources", action="store_true", help="从引擎/状态机唯一依据生成唯一依据文件")
    ap.add_argument("--table", action="store_true", help="打印标定表")
    ap.add_argument("--stage", default=None, help="只显示某阶段")
    ap.add_argument("--set", nargs=3, metavar=("STAGE", "PARAM", "VALUE"), action="append", default=[])
    ap.add_argument("--set-bound", nargs=4, metavar=("STAGE", "PARAM", "MINMAX", "V"), default=None,
                    help="改物理上下限本身: --set-bound 接近 v max 0.60")
    ap.add_argument("--check", action="store_true", help="校核 (有问题→非零退出)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    if a.init_from_sources:
        d = build_from_sources()
        save(d)
        bad = validate(d)
        print("✅ 已从唯一依据生成 %s (%d 阶段 × %d 物理量)" % (os.path.relpath(CALIB, ROOT), len(d["stages"]), len(PARAMS)))
        print("   校核: %s" % ("干净" if not bad else "; ".join(bad)))
        table(d)
        return 0 if not bad else 1

    d = load()
    if d is None:
        print("⚠️ 唯一依据不存在: %s\n   先跑 --init-from-sources" % CALIB)
        return 2

    rc = 0
    if a.set:
        for st_key, p, val in a.set:
            st = resolve_stage(st_key, d)
            if st is None:
                print("❌ 未知技能/阶段: %s (可用: %s)" % (st_key, ", ".join(d["stages"])))
                rc = 1
                continue
            if p not in PARAMS:
                print("❌ 未知物理量: %s (可用: %s)" % (p, ", ".join(PARAMS)))
                rc = 1
                continue
            q = d["stages"][st][p]
            try:
                v = float(val)
            except ValueError:
                print("❌ 值不是数字: %s" % val)
                rc = 1
                continue
            if not (q["min"] - 1e-12 <= v <= q["max"] + 1e-12):
                print("❌ 拒绝 %s.%s = %s : 超出物理上下限 [%s, %s] %s\n   依据: %s"
                      % (st, p, v, q["min"], q["max"], q["unit"], BOUND_SRC.get(p, "")))
                rc = 1
                continue
            old = q["value"]
            q["value"] = round(v, 6)
            save(d)
            print("✅ %s.%s: %s → %s %s  (上下限 [%s, %s] · 依据 %s)" % (st, p, old, v, q["unit"], q["min"], q["max"], q["src"]))
        d = load() or d
    if a.set_bound:
        try:
            st_key, p, flag, v = a.set_bound[0], a.set_bound[1], a.set_bound[2], float(a.set_bound[3])
            st = resolve_stage(st_key, d)
            if st is None or p not in PARAMS:
                print("❌ 用法: --set-bound 接近 v --max 0.60")
                return 1
            key = "max" if flag.lstrip("-") == "max" else "min"
            d["stages"][st][p][key] = round(v, 6)
            save(d)
            print("✅ %s.%s 物理%s → %s (改的是上下限本身, 已留备份)" % (st, p, key, v))
        except Exception as e:                                              # noqa: BLE001
            print("❌ %s (用法: --set-bound 接近 v --max 0.60)" % e)
            return 1

    if a.json:
        print(json.dumps(d, ensure_ascii=False, indent=1))
    if a.table or not (a.json or a.set or a.set_bound or a.check):
        table(d, only=a.stage)
    if a.check or a.set or a.set_bound:
        bad = validate(d)
        print("\n校核: %s" % ("✅ 全部物理量在物理上下限内" if not bad else "❌ %d 项问题" % len(bad)))
        for b in bad:
            print("   - %s" % b)
        if bad:
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
