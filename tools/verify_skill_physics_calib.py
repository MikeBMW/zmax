#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_skill_physics_calib.py — 判据: 原子技能物理参数 v/a/s 真能标定吗? 上下限真拦得住吗?

老倪 (2026-10-15): 「这些物理参数 速度 v、加速度 a、位移 s 需要可以标定, 比如上限下限、最大值最小值」
本脚本**不只信真源文件写对了**, 而是端到端验: 标定 → 闸门 → 确实改变下发动作 / 越界确实被拦。

判据 (全绿才算通过):
 ① 真源完整   13 技能 × 9 物理量 全有 value/min/max/unit/src 且 min < value ≤ max
 ② 与引擎同源 真源 v/v_min 与 cognition.STAGE_V_CAP/STAGE_V_MIN 逐条一致 (不许两处打架)
 ③ CLI 拦越界 --set 一个超上限的值 ⇒ 非零退出 + 真源文件**一字节没变**
 ④ 标定生效   --set 合法值 ⇒ 回读真源是新值, 且闸门 limits_for() 立刻用新值 (端到端)
 ⑤ 闸门读真源 limits_for() 的 v/m/F/a/s/s_step 来自真源, calib_src_kind 标"真源"
 ⑥ 上下限兜底 篡改真源塞越界值 ⇒ 闸门运行期夹回 [min,max] 并留 clamps 取证 (不静默用坏值)
 ⑦ ⑤位移闸真咬 把 插入.s_step 收紧到 2mm (标定允许) ⇒ 下发动作被"位移"削, 且 ‖v‖·dt ≤ s_step
 ⑧ 偏差可回收 u + err == 请求 (削幅只削超物理部分, 不翻转方向)
 ⑨ 缺文件回退 删掉真源 ⇒ 闸门回退内置 PHYS 表, 不崩 (旧行为逐位保留)

用法: gui-venv311/bin/python tools/verify_skill_physics_calib.py   (非零退出 = 有判据 FAIL)
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

CALIB = os.path.join(ROOT, "config", "calib", "zmax_skill_physics.json")
CLI = os.path.join(ROOT, "tools", "skill_physics_calib.py")
PY = os.path.join(ROOT, "gui-venv311", "bin", "python")
PY = PY if os.path.exists(PY) else sys.executable
PARAMS = ("v", "v_min", "a", "s", "s_step", "jerk", "m", "F", "dmdt")

from lerobot.policies.left_right.state_space import physics_constraints as PC   # noqa: E402

OK, BAD = [], []


def chk(no, name, cond, detail=""):
    (OK if cond else BAD).append((no, name, detail))
    print("  %s %s %s%s" % ("✅" if cond else "❌", no, name, (" — " + detail) if detail else ""))


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16] if os.path.exists(path) else "-"


def run_cli(args, env=None):
    e = dict(os.environ)
    e.update(env or {})
    p = subprocess.run([PY, CLI] + args, capture_output=True, text=True, cwd=ROOT, env=e)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def main():
    src = json.load(open(CALIB, encoding="utf-8"))
    stages = src["stages"]
    tmp = tempfile.mkdtemp(prefix="skillphys_")
    tmp_calib = os.path.join(tmp, "zmax_skill_physics.json")
    shutil.copy2(CALIB, tmp_calib)

    print("═" * 92)
    print("🧪 原子技能物理参数标定判据 — 真源 %s" % os.path.relpath(CALIB, ROOT))
    print("═" * 92)

    # ① 真源完整
    miss, oob = [], []
    for st, ps in stages.items():
        for k in PARAMS:
            q = ps.get(k)
            if not isinstance(q, dict) or q.get("value") is None or q.get("unit") is None or not q.get("src"):
                miss.append("%s.%s" % (st, k))
                continue
            lo, hi, v = q.get("min"), q.get("max"), q["value"]
            if lo is None or hi is None:
                miss.append("%s.%s 无上下限" % (st, k))
            elif not (lo <= v <= hi):
                oob.append("%s.%s=%s ∉[%s,%s]" % (st, k, v, lo, hi))
    chk("①", "真源完整 (每技能 %d 物理量, 含 min/max/unit/src)" % len(PARAMS),
        not miss and not oob, "%d 技能 × %d 量 · 缺项 %d · 越界 %d" %
        (len(stages), len(PARAMS), len(miss), len(oob)) + (" " + ";".join((miss + oob)[:4]) if (miss or oob) else ""))

    # ② 与引擎同源 (cognition.STAGE_V_CAP / STAGE_V_MIN 不许两处打架)
    import ast
    cog = ast.parse(open(os.path.join(ROOT, "src/lerobot/policies/left_right/state_space/cognition.py"),
                         encoding="utf-8").read())
    vcap, vmin = {}, {}
    for n in ast.walk(cog):
        if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name):
            if n.targets[0].id in ("STAGE_V_CAP", "STAGE_V_MIN"):
                (vcap if n.targets[0].id == "STAGE_V_CAP" else vmin).update(ast.literal_eval(n.value))
    diff = []
    for st, v in vcap.items():
        if abs(float(stages.get(st, {}).get("v", {}).get("value", -1)) - float(v)) > 1e-9:
            diff.append("v:%s 真源%s≠引擎%s" % (st, stages.get(st, {}).get("v", {}).get("value"), v))
    for st, v in vmin.items():
        if abs(float(stages.get(st, {}).get("v_min", {}).get("value", -1)) - float(v)) > 1e-9:
            diff.append("v_min:%s 真源%s≠引擎%s" % (st, stages.get(st, {}).get("v_min", {}).get("value"), v))
    chk("②", "与引擎同源 (真源 v/v_min == cognition.STAGE_V_CAP/STAGE_V_MIN)", not diff,
        "比对 %d 段" % len(vcap) + (" · " + ";".join(diff[:3]) if diff else " · 一致"))

    # ③ CLI 拦越界 (真源一字节没变)
    h0 = sha(tmp_calib)
    rc, out = run_cli(["--set", "接近", "v", "99.0"], {"ZMAX_SKILL_PHYS_JSON": tmp_calib})
    q = json.load(open(tmp_calib, encoding="utf-8"))["stages"]["接近"]["v"]["value"]
    chk("③", "CLI 拦越界 (99 > v 上限)", rc != 0 and sha(tmp_calib) == h0 and abs(q - 0.35) < 1e-9,
        "退出码 %d · 文件 %s · 值 %s · 提示%s" % (rc, "未变" if sha(tmp_calib) == h0 else "被改了", q,
                                                "含'超出物理上下限'" if "超出物理上下限" in out else "缺提示"))

    # ④ 标定生效 (写 → 回读 → 闸门立刻用新值)
    rc, out = run_cli(["--set", "接近", "v", "0.34"], {"ZMAX_SKILL_PHYS_JSON": tmp_calib})
    back = json.load(open(tmp_calib, encoding="utf-8"))["stages"]["接近"]["v"]["value"]
    os.environ["ZMAX_SKILL_PHYS_JSON"] = tmp_calib        # 让闸门读这份"标定后"的真源
    PC._SKILL_PHYS_JSON = tmp_calib
    PC._CALIB_CACHE["key"] = None
    v_gate = float(PC.limits_for("接近")["v"])
    chk("④", "标定生效 (0.35→0.34 回读 + 闸门立刻用新值)", rc == 0 and abs(back - 0.34) < 1e-9
        and abs(v_gate - 0.34) < 1e-9, "回读 %s · 闸门 v=%s" % (back, v_gate))

    # ⑤ 闸门读真源
    q5 = PC.limits_for("插入")
    chk("⑤", "闸门读真源 (v/m/F/a/s/s_step + calib_src 标真源)",
        "真源" in str(q5.get("calib_src_kind")) and abs(float(q5["v"]) - 0.085) < 1e-9
        and abs(float(q5["F"]) - 2.0) < 1e-9 and abs(float(q5["s_step"]) - 0.0085) < 1e-9,
        "v=%s F=%s a=%s s_step=%s src=%s" % (q5["v"], q5["F"], round(q5["a_max"], 3), q5["s_step"], q5.get("calib_src_kind")))

    # ⑥ 上下限兜底: 塞一个越界值进真源 ⇒ 闸门夹回 + clamps 取证
    d = json.load(open(tmp_calib, encoding="utf-8"))
    d["stages"]["接近"]["v"]["value"] = 9.9          # 故意越界 (绕过 CLI 手改)
    json.dump(d, open(tmp_calib, "w", encoding="utf-8"), ensure_ascii=False)
    PC._CALIB_CACHE["key"] = None
    q6 = PC.limits_for("接近")
    chk("⑥", "上下限兜底 (真源被塞 9.9 ⇒ 运行期夹回上限并留 clamps)",
        abs(float(q6["v"]) - 1.0) < 1e-9 and bool(q6.get("clamps")),
        "v=%s clamps=%s" % (q6["v"], (q6.get("clamps") or [])[:1]))
    d["stages"]["接近"]["v"]["value"] = 0.35         # 还原
    json.dump(d, open(tmp_calib, "w", encoding="utf-8"), ensure_ascii=False)
    PC._CALIB_CACHE["key"] = None

    # ⑦ ⑤位移闸真咬: 把 插入.s_step 收紧到 2mm (标定允许: ≤ v_cap·dt = 8.5mm)
    d = json.load(open(tmp_calib, encoding="utf-8"))
    old_step = d["stages"]["插入"]["s_step"]["value"]
    d["stages"]["插入"]["s_step"]["value"] = 0.002
    json.dump(d, open(tmp_calib, "w", encoding="utf-8"), ensure_ascii=False)
    PC._CALIB_CACHE["key"] = None
    lim = PC.InertiaLimiter()
    r7 = lim.limit("插入", [0.085, 0.0, 0.0, 0.0])
    d_7 = abs(r7["u"][0]) * 0.1
    chk("⑦", "⑤位移闸真咬 (插入 s_step 收紧 8.5mm→2mm ⇒ 削因含'位移'且单拍位移≤s_step)",
        "位移" in r7["why"] and d_7 <= 0.002 + 1e-9,
        "请求 0.085 m/s → 可行 %.4f m/s · 单拍位移 %.4f m ≤ 0.0020 · 削因 %s" % (r7["u"][0], d_7, r7["why"]))
    d["stages"]["插入"]["s_step"]["value"] = old_step
    json.dump(d, open(tmp_calib, "w", encoding="utf-8"), ensure_ascii=False)
    PC._CALIB_CACHE["key"] = None

    # ⑧ 偏差可回收 (u + err = 请求, 方向不翻转)
    lim2 = PC.InertiaLimiter()
    req = [0.9, -1.1, 0.7, 1.0]
    r8 = lim2.limit("接近", req, v_prev=[0.0] * 3, a_prev=[0.0] * 3)
    rec = [round(r8["u"][i] + r8["err"][i], 9) for i in range(3)]
    chk("⑧", "偏差可回收 (u + err == 请求, 削幅不翻转方向)", rec == [round(x, 9) for x in req[:3]]
        and r8["u"][3] == 1.0, "u=%s err=%s ⇒ %.6f (夹爪位透传 %s)" % ([round(x, 4) for x in r8["u"][:3]],
                                                                      [round(x, 4) for x in r8["err"]], rec[0], r8["u"][3]))

    # ⑨ 缺文件回退 (旧行为保留)
    os.environ["ZMAX_SKILL_PHYS_JSON"] = os.path.join(tmp, "不存在.json")
    PC._SKILL_PHYS_JSON = os.path.join(tmp, "不存在.json")
    PC._CALIB_CACHE["key"] = None
    q9 = PC.limits_for("接近")
    r9 = PC.InertiaLimiter().limit("接近", [1.2, 0.0, 0.0, 0.0], v_prev=[0.0, 0.0, 0.0])
    chk("⑨", "缺文件回退内置 PHYS 表 (不崩, 旧行为保留)",
        "回退" in str(q9.get("calib_src_kind")) and abs(float(q9["v"]) - 0.35) < 1e-9 and r9["big"] == 1,
        "v=%s src=%s 闸门仍削 1.2→%.4f" % (q9["v"], q9.get("calib_src_kind"), r9["u"][0]))

    # ⑩ 每个技能类都能拿到**自己的**物理约束 (SK01-08/SK07Place 逐个比对真源)
    #     (⑨ 把真源指针指向了不存在的文件, 这里先指回在役真源)
    os.environ.pop("ZMAX_SKILL_PHYS_JSON", None)
    PC._SKILL_PHYS_JSON = CALIB
    PC._CALIB_CACHE["key"] = None
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from lerobot.policies.left_right.state_space.skills import atomic_skills as AS      # noqa: E402
    rows, bad10 = [], []
    for cls in list(AS.SKILLS) + list(AS.SKILLS_TRAY):
        pc_ = cls.phys_check()
        q = cls.phys()
        exp = stages.get(cls.stage, {})
        if not exp:
            bad10.append("%s 段名 %s 不在真源" % (cls.code, cls.stage))
            continue
        for k, key in (("v", "v"), ("m", "m"), ("F", "F"), ("s_step", "s_step")):
            if abs(float(q[key]) - float(exp[k]["value"])) > 1e-9:
                bad10.append("%s.%s 技能类 %s ≠ 真源 %s" % (cls.code, key, q[key], exp[k]["value"]))
        if not pc_["ok"]:
            bad10.append("%s phys_check: %s" % (cls.code, pc_["problems"]))
        # 方程必须真的在类里 (老倪: "打开 SK01 怎么没有物理方程?") —— 五式齐 + 带本段数字 + 有绑定说明
        md = cls.phys_model()
        if len(cls.EQ) != 5 or len(md["方程"]) != 5:
            bad10.append("%s 方程条数 != 5 (EQ=%d model=%d)" % (cls.code, len(cls.EQ), len(md["方程"])))
        if not getattr(cls, "phys_note", ""):
            bad10.append("%s 缺 phys_note (本段绑定说明)" % cls.code)
        if ("%.3f" % q["v"]) not in " ".join(md["方程"].values()):
            bad10.append("%s 方程里没填本段数字 (v=%.3f 找不到)" % (cls.code, q["v"]))
        # dm/dt 必须与真源一致 (曾踩: 闸门字段叫 dmdt、报告叫 dmdt_max, 取错 → 方程里印出 0.00)
        _dm = float(q.get("dmdt_max") or q.get("dmdt") or 0.0)
        if abs(_dm - float(exp["dmdt"]["value"])) > 1e-9:
            bad10.append("%s 方程 dm/dt=%s ≠ 真源 %s" % (cls.code, _dm, exp["dmdt"]["value"]))
        if abs(float(md["数值"]["dmdt_max_kg_s"]) - float(exp["dmdt"]["value"])) > 1e-9:
            bad10.append("%s phys_model 的 dmdt 取错字段" % cls.code)
        rows.append("%s[%s] a_max=%.2f jerk=%.1f 单拍位移=%.4f" % (cls.code, cls.stage, q["a_max"],
                                                                   q["jerk_max"], q["s_step"]))
    chk("⑩", "每个技能类拿到自己的物理约束 + **类里有五条方程** (EQ=5 · 方程带本段数字 · phys_note · phys() == 真源)",
        not bad10, "%d 个技能类 · %s" % (len(rows), " | ".join(rows[:3])) + (" | 问题 " + ";".join(bad10[:3]) if bad10 else " | 全部一致"))

    # ⑪ 未登记的段名不许静默套用别的段 (原来 unknown stage → 悄悄用「接近」的 m/F/v)
    q11 = PC.limits_for("不存在的段")
    lim11 = PC.InertiaLimiter()
    r11 = lim11.limit("不存在的段", [1.0, 0.0, 0.0, 0.0])
    known = PC.limits_for("接近")
    chk("⑪", "未登记段名可见 (不静默降级): unknown_stage=1 + 计数 + 盘查表标未登记",
        q11.get("unknown_stage") == 1 and r11.get("unknown_stage") == 1
        and lim11.stats()["n_unknown_stage"] == 1 and not known.get("unknown_stage"),
        "未知段 unknown_stage=%s 计数=%s · 已知段 接近 unknown_stage=%s"
        % (q11.get("unknown_stage"), lim11.stats()["n_unknown_stage"], known.get("unknown_stage")))

    # 还原进程内状态 (不影响真实运行)
    PC._SKILL_PHYS_JSON = CALIB
    PC._CALIB_CACHE["key"] = None
    os.environ.pop("ZMAX_SKILL_PHYS_JSON", None)
    shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "═" * 92)
    print("判据汇总: PASS %d / FAIL %d" % (len(OK), len(BAD)))
    for no, name, detail in BAD:
        print("   ❌ %s %s — %s" % (no, name, detail))
    print("═" * 92)
    return 0 if not BAD else 1


if __name__ == "__main__":
    sys.exit(main())
