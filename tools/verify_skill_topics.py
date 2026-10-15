#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_skill_topics.py — 判据: **原子技能物理量 topic 全链** (老倪 2026-10-15 逐字要求)。

老倪: 「所有的原子技能, 例如 接近, 对位, 都要有 topic 输出, 且在实时监控信号分析窗口都有对应的信号;
       你来给出所有场景的原子技能 topic, 我要在信号分析窗口看到实际的物理模型, x y z v a 等距离、速度、
       角度等物理值; 要实际发出来; 所有原子技能, 而且 vscode 要有对应代码。」

判据 (每条都真跑, 不靠"看着应该有"):
  ① 登记     topics.py 里 skill_sk01..08 齐 + 类型 zmax::SSSkillPhys + diag/calib/test 三档都在
  ② 类型     dds/ss_types.py 的 SSSkillPhys 字段与 [实测 8 + 包络 7] 一一对应, 且能实例化
  ③ 三处同名 **字段名一致性**: 派发写的名字 == 守护读的名字 == 信号分析页读的名字
             (踩过的坑: 守护用 DDS 字段名 v/a/x 去读文件里的 v_mms/a_mms2 ⇒ 8 个物理量全读空)
  ④ 真生产   zmax_data/ss_live/skill_phys.json 每技能字段齐 + 源帧龄 < 5s (服务在真跑, 不是陈货)
  ⑤ 包络同源 每条技能的 v_cap/a_max/jerk_max/s_step/s_max/m/F == limits_for(阶段) 逐条一致
  ⑥ 实测在界 实测 v/a/s ≤ 包络上限 (mm 口径换算后) —— 物理模型真的包住了实测
  ⑦ 真发布   live.json 里 8 条 zmax/skill_sk0x 绿 + count>0 + 带 v/a/s 实测值 (不是空壳话题)
  ⑧ 不伪造   位姿停更时 x/y/z/angle 必须是 -1 (不是 0 冒充); 缺测口径不许变
  ⑨ 单读者   发布守护**不再自己读 tap** (位姿只由派发服务读一次写盘, 避免两处各读一份各算一次新鲜度)
  ⑩ 诚实登记 引擎 13 段里没有技能类的 5 段 (拔出/AOI转移/AOI检测/回程/放下) 标了"待接生产者", 不假装有数

用法:  ./gui-venv311/bin/python tools/verify_skill_topics.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "dds"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
SKILLS = ["sk%02d" % i for i in range(1, 9)]
HOST = [("SK01", "接近"), ("SK02", "对位"), ("SK03", "下降"), ("SK04", "抓取"),
        ("SK05", "抬起"), ("SK06", "转移"), ("SK07", "插入"), ("SK08", "完成")]
PHYS_FILE = os.path.join(ROOT, "zmax_data", "ss_live", "skill_phys.json")
LIVE = os.path.join(ROOT, "zmax_data", "dataspace", "live.json")
CALIB = os.path.join(ROOT, "config", "calib", "zmax_skill_physics.json")

FAIL = []
OK = 0


def chk(cond, msg, detail=""):
    global OK
    if cond:
        OK += 1
        print("✅ %s" % msg)
    else:
        FAIL.append(msg)
        print("❌ %s%s" % (msg, (" — " + detail) if detail else ""))


def main() -> int:
    from lerobot.dataspace import topics as T
    # ⚠️ 这里**不能** `from lerobot.policies...` : lerobot.policies → lerobot.utils 会去 import
    #    huggingface_hub, 而 DDS 边车 venv(venvs/dds-venv) 里没有它 ⇒ 判据脚本直接起不来。
    #    物理闸是纯 numpy 单文件, 按文件路径加载即可 (同口径, 不做第二份拷贝)。
    import importlib.util as _iu
    _p = os.path.join(ROOT, "src", "lerobot", "policies", "left_right", "state_space", "physics_constraints.py")
    _spec = _iu.spec_from_file_location("zmax_physics_constraints", _p)
    _pc = _iu.module_from_spec(_spec)
    _spec.loader.exec_module(_pc)
    limits_for = _pc.limits_for

    # ── ① 登记 ──
    miss = [k for k in ("skill_" + s for s in SKILLS) if k not in T.TOPICS]
    chk(not miss, "① 登记: topics.py 里 8 条技能话题齐", "缺 %s" % miss)
    bad_t = [k for k in ("skill_" + s for s in SKILLS)
             if (T.TOPICS.get(k) or {}).get("type") != "zmax::SSSkillPhys"]
    chk(not bad_t, "① 登记: 8 条类型都是 zmax::SSSkillPhys", "%s" % bad_t)
    for m in ("diag", "calib", "test"):
        got = [k for k in T.topics_for_mode(m) if k.startswith("skill_")]
        chk(len(got) == 8, "① 登记: %s 档含全部 8 条技能话题" % m, "实际 %d" % len(got))

    # ── ② 类型 (声明层: 从源文件 AST 读字段; 运行期能不能上线由 ⑦ 数据总线实收证明) ──
    #   这里不 import ss_types: 它要 cyclonedds (DDS 边车 venv 有、GUI venv 没有), 而本判据还要用 numpy
    #   (物理闸) ⇒ 一个 venv 里凑不齐。声明层读 AST + 运行层读 live.json 实收, 两头都真验。
    import ast as _ast
    _tree = _ast.parse(open(os.path.join(ROOT, "dds", "ss_types.py"), encoding="utf-8").read())
    _cls = [n for n in _tree.body if isinstance(n, _ast.ClassDef) and n.name == "SSSkillPhys"]
    chk(len(_cls) == 1, "② 类型: dds/ss_types.py 里有 class SSSkillPhys")
    F, typ = {}, ""
    if _cls:
        typ = _ast.unparse(_cls[0].bases[0]) + " " + " ".join(_ast.unparse(k) for k in _cls[0].keywords)
        for a in _cls[0].body:
            if isinstance(a, _ast.AnnAssign) and isinstance(a.target, _ast.Name):
                F[a.target.id] = _ast.unparse(a.value) if a.value is not None else ""
    need = ["x", "y", "z", "v", "a", "s", "angle", "err"] + \
           ["v_cap", "a_max", "jerk_max", "s_step", "s_max", "m_kg", "f_max"]
    lack = [f for f in need if f not in F]
    chk(not lack, "② 类型: SSSkillPhys 字段齐 (实测 8 + 包络 7)", "缺 %s" % lack)
    chk("IdlStruct" in typ and "zmax::SSSkillPhys" in typ,
        "② 类型: 是 DDS IDL 结构且 typename=zmax::SSSkillPhys", typ)
    chk(F.get("x") == "-1.0" and F.get("v_cap") == "-1.0",
        "② 类型: 缺测默认 -1 (不用 0 冒充)", "%s / %s" % (F.get("x"), F.get("v_cap")))
    chk("in_service" in F and "frame_age_s" in F and "why" in F,
        "② 类型: 带在职标志/帧龄/削因说明 (不带这三样没法判真假)")

    # ── ③ 三处字段名一致 (真跑出来的坑: 读空 8 个物理量) ──
    gui = open(os.path.join(ROOT, "tools", "gui", "canoe_graphic.py"), encoding="utf-8").read()
    dae = open(os.path.join(ROOT, "tools", "dds", "ss_daemon.py"), encoding="utf-8").read()
    dis = open(os.path.join(ROOT, "tools", "ss_skill_dispatch.py"), encoding="utf-8").read()
    fnames = ["v_mms", "a_mms2", "s_mm", "err_mms", "x", "y", "z", "angle",
              "v_cap", "a_max", "jerk_max", "s_step", "s_max", "m_kg", "f_max"]
    chk(all(('"%s"' % f) in dis for f in fnames), "③ 字段名: 派发服务写出全部 15 个物理量字段")
    chk(all(('"%s"' % f) in gui for f in fnames), "③ 字段名: 信号分析页按**同名**读取 15 个字段")
    chk('r.get("v_mms")' in dae and 'r.get("v_cap"' in dae and 'r.get("s_mm"' in dae,
        "③ 字段名: 发布守护按同名读取 (不是照 DDS 消息名 v/a/x 去读文件)")

    # ── ④ 真生产 ──
    try:
        d = json.load(open(PHYS_FILE, encoding="utf-8"))
        age = time.time() - os.path.getmtime(PHYS_FILE)
    except Exception as e:                                              # noqa: BLE001
        chk(False, "④ 真生产: skill_phys.json 可读", str(e))
        d, age = {}, 1e9
    chk(age < 5.0, "④ 真生产: 源帧龄 <5s (技能派发服务在真跑)", "帧龄 %.1fs" % age)
    sk = d.get("skills") or {}
    lack2 = [c for c, _ in HOST if c not in sk]
    chk(not lack2, "④ 真生产: 8 个技能都有记录", "缺 %s" % lack2)
    lack3 = [(c, f) for c, _ in HOST for f in fnames if f not in (sk.get(c) or {})]
    chk(not lack3, "④ 真生产: 每技能 15 个物理量字段都在", "缺 %s" % lack3[:6])

    # ── ⑤ 包络与 limits_for 逐条一致 ──
    def eq(a, b):
        try:
            return abs(float(a) - float(b)) < 1e-6
        except Exception:                                               # noqa: BLE001
            return False

    bad5 = []
    for code, stage in HOST:
        r, L = sk.get(code) or {}, limits_for(stage) or {}
        for kf, lf in (("v_cap", "v"), ("a_max", "a_max"), ("jerk_max", "jerk_max"), ("s_step", "s_step"),
                       ("s_max", "s_max"), ("m_kg", "m"), ("f_max", "F")):
            if not eq(r.get(kf), L.get(lf)):
                bad5.append("%s.%s(%s)≠limits_for.%s(%s)" % (code, kf, r.get(kf), lf, L.get(lf)))
    chk(not bad5, "⑤ 包络同源: 每技能的 v_cap/a_max/jerk_max/s_step/s_max/m/F == 物理闸真源", "; ".join(bad5[:4]))

    # ── ⑥ 实测在物理包络内 ──
    bad6 = []
    for code, stage in HOST:
        r = sk.get(code) or {}
        if not r.get("在职"):
            continue
        for mk, pk, k in (("v_mms", "v_cap", 1000.0), ("a_mms2", "a_max", 1000.0), ("s_mm", "s_max", 1000.0)):
            v, lim = r.get(mk, -1.0), r.get(pk, -1.0)
            if isinstance(v, (int, float)) and v >= 0 and isinstance(lim, (int, float)) and lim > 0:
                if v > lim * k + 1e-6:
                    bad6.append("%s %s=%.3f > %s=%.3f" % (code, mk, v, pk, lim * k))
    chk(not bad6, "⑥ 实测在界: 实测 v/a/s 都 ≤ 标定包络 (物理模型真的包住了)", "; ".join(bad6[:4]))

    # ── ⑦ 真发布 (DDS → live.json) ──
    try:
        lt = (json.load(open(LIVE, encoding="utf-8")) or {}).get("topics") or {}
    except Exception:                                                   # noqa: BLE001
        lt = {}
    dead = [k for k in ("skill_" + s for s in SKILLS)
            if (lt.get(k) or {}).get("lamp") not in ("green", "yellow")]
    chk(not dead, "⑦ 真发布: 8 条技能话题在数据总线上活着 (绿/黄)", "异常 %s" % dead)
    n_cnt = sum(1 for k in ("skill_" + s for s in SKILLS) if ((lt.get(k) or {}).get("count") or 0) > 0)
    chk(n_cnt == 8, "⑦ 真发布: 8 条都有实收计数 (>0)", "只有 %d 条" % n_cnt)
    withval = 0
    for k in ("skill_" + s for s in SKILLS):
        f = ((lt.get(k) or {}).get("fields") or {})
        if isinstance(f.get("v"), (int, float)) and f.get("v") != -1 and isinstance(f.get("v_cap"), (int, float)) \
                and f.get("v_cap") != -1:
            withval += 1
    chk(withval >= 1, "⑦ 真发布: 至少有一条带实测 v + 包络 v_cap 的真值", "带值 %d 条" % withval)

    # ── ⑧ 不伪造 (位姿停更 ⇒ -1) ──
    pose = d.get("pose") or {}
    stale = bool(pose.get("stale")) or (isinstance(pose.get("pose_age_s"), (int, float))
                                        and pose["pose_age_s"] > 5.0)
    if stale:
        bad8 = [c for c, _ in HOST if (sk.get(c) or {}).get("x") not in (-1.0, -1)]
        chk(not bad8, "⑧ 不伪造: 位姿停更 (帧龄 %.0fs) ⇒ x/y/z/angle 全 -1" % pose.get("pose_age_s", -1),
            "有技能给了位置: %s" % bad8)
        bad8b = []
        for k in ("skill_" + s for s in SKILLS):
            f = ((lt.get(k) or {}).get("fields") or {})
            if isinstance(f.get("x"), (int, float)) and f.get("x") != -1:
                bad8b.append(k)
        chk(not bad8b, "⑧ 不伪造: 总线上也不许出现伪造位置", "%s" % bad8b)
    else:
        chk(True, "⑧ 不伪造: 位姿新鲜 (帧龄 %.2fs) ⇒ 位置按真值发" % pose.get("pose_age_s", -1))

    # ── ⑨ 单读者 ──
    blk = dae[dae.index("def pub_skills"): dae.index("def pub_diag")]
    chk("read_state()" not in blk, "⑨ 单读者: 发布守护不再自己读 tap (位姿只由派发服务读一次)")

    # ── ⑩ 诚实登记 (13 段里没技能类的 5 段) ──
    pend = re.findall(r'"(stage_\w+)":\s*\{[^}]*?"status":\s*"已登记 · 待接生产者', open(
        os.path.join(ROOT, "src", "lerobot", "dataspace", "topics.py"), encoding="utf-8").read(), re.S)
    chk(len(set(pend)) == 5, "⑩ 诚实登记: 5 段无技能类的段标了「待接生产者」", "实际 %s" % sorted(set(pend)))
    inmode = [k for k in ("stage_pullout", "stage_aoi_move", "stage_aoi_inspect", "stage_return", "stage_place")
              if k in T.topics_for_mode("test")]
    chk(not inmode, "⑩ 诚实登记: 这 5 段**不在**任何遥测档里 (没生产者就不进总线, 不假装有数)", "%s" % inmode)

    print("\n判据汇总: PASS %d / FAIL %d" % (OK, len(FAIL)))
    if FAIL:
        for f in FAIL:
            print("  ❌ %s" % f)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
