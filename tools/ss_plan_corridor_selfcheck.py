#!/usr/bin/env python3
"""技能约束通道 · plan 节点接入自检 (真有效判据, 不是"画了条线")。

跑法:  cd ~/zmax && ./gui-venv311/bin/python tools/ss_plan_corridor_selfcheck.py

判据 (全绿才算接进去了):
  ① 真源接上      plan 段 (kind,label) → 8 个技能通道, 覆盖率 = 392/392 段有通道
  ② 名义轨迹在管内 每条真实段端点 dev ≤ r (通道是从这些段建的 ⇒ 必须 ≈0)
  ③ 注入越界真被夹  把 b 横向外移 3r ⇒ 发布 b 被拉回管壁 (dev ≤ r), excess/moved 有数, cut=True
  ④ 每拍点真被核   起点/终点都贴壁的段, 逐拍发布点 dev ≤ r; 人为抬 u 也不许出管
  ⑤ 关闸零回归     ZMAX_PLAN_CORRIDOR=0 ⇒ 不夹、dev=None, 段端点逐位等于原值
  ⑥ 算法同源       用的是 state_space/corridor.py (clamp_into), 不是第二套
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import subprocess
import sys

ROOT = os.path.expanduser("~/zmax")
PLAN = os.path.join(ROOT, "src", "lerobot", "engineering", "nodes", "plan_long_impl.py")
COR = os.path.join(ROOT, "zmax_data", "ss_live", "skill_corridors.json")

OK, BAD = "✅", "❌"
_fail = []


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


_checks = [0]


def judge(tag, cond, detail=""):
    _checks[0] += 1
    print(("  %s %s %s" % (OK if cond else BAD, tag, detail)).rstrip())
    if not cond:
        _fail.append(tag)
    return cond


def main():
    P = load(PLAN, "plan_long_selfcheck")
    C = load(os.path.join(ROOT, "src", "lerobot", "policies", "left_right",
                          "state_space", "corridor.py"), "zmax_skill_corridor_sc")
    print("plan 通道真源:", P._COR_PATH)
    judge("真源文件在盘", os.path.isfile(COR), COR if os.path.isfile(COR) else "缺失")

    # ── ① 覆盖率: 每段都能落到一个通道 (运动段=技能通道, 零位移检测段=保持点通道) ──
    P.run({})
    segs = list(P._S.get("segs") or [])
    stage_n, covered, miss = {}, 0, []
    for i, s in enumerate(segs):
        P._S["i"] = i
        fit = P._cor_fit({"kind": s.get("kind"), "label": s.get("label"),
                          "a": s.get("a"), "b": s.get("b"), "seq": i})
        if fit:
            covered += 1
            st = fit[2]["stage"]
            stage_n[st] = stage_n.get(st, 0) + 1
        else:
            miss.append((i, s.get("kind"), s.get("label")))
    print("\n① 段 → 通道覆盖: %d/%d 段" % (covered, len(segs)))
    print("   " + " · ".join("%s %d" % (k, v) for k, v in sorted(stage_n.items())))
    if miss:
        print("   未覆盖样例:", miss[:5])
    judge("392 段全部有通道", covered == len(segs), "%d 段" % covered)

    # ── ② 名义轨迹 (真实段端点) 在管内 ──────────────────────────────────
    print("\n② 名义段端点偏差 (通道就是这些段建的 ⇒ 应 ≈0):")
    devs, cut_n, worst = {}, 0, (0.0, None)
    for i, s in enumerate(segs):
        P._S["i"] = i
        fit = P._cor_fit({"kind": s.get("kind"), "label": s.get("label"),
                          "a": s.get("a"), "b": s.get("b"), "seq": i})
        if not fit:
            continue
        a2, b2, info, _corr = fit
        st = info["stage"]
        d = devs.setdefault(st, {"n": 0, "dev_max": 0.0, "r": info["r_mm"], "cut": 0})
        d["n"] += 1
        d["dev_max"] = max(d["dev_max"], float(info["dev_a"]), float(info["dev_b"]))
        if info["cut"]:
            d["cut"] += 1
            cut_n += 1
            if float(info["moved_mm"]) > worst[0]:
                worst = (float(info["moved_mm"]), (i, st, info["why"], info["moved_mm"]))
    for st, d in sorted(devs.items()):
        print("   %-4s n=%-4d r=%.1fmm  dev_max=%.3fmm  夹回 %d 段" % (st, d["n"], d["r"], d["dev_max"], d["cut"]))
    judge("名义轨迹全部在管内", cut_n == 0, "被夹 %d 段 %s" % (cut_n, worst[1] or ""))

    # ── ③ 注入越界: 目标点外移 ⇒ 真被夹回管壁 (夹回量 = 超出量, 逐位可算) ──
    print("\n③ 故障注入 (转移技能): 把目标 b 移到通道外, 看它怎么被夹回来")
    tgt = next((i for i, s in enumerate(segs) if P._skill_stage(s.get("kind"), s.get("label")) == "转移"), None)
    if tgt is None:
        judge("找到 转移 段", False)
    else:
        s = segs[tgt]
        corr = P._cor("转移")
        r = float(corr["r_mm"])
        u_ax = C._unit(C._sub([float(x) for x in s["b"]], [float(x) for x in s["a"]]))
        e1, _e2 = C._perp_basis(u_ax)
        cases = [("横向 3r", [float(s["b"][k]) + e1[k] * 3 * r for k in range(3)]),
                 ("上抬 3000mm", [float(s["b"][0]), float(s["b"][1]), float(s["b"][2]) + 3000.0])]
        for name, bad_b in cases:
            dev_before = C.closest_on_polys(corr["polys"], bad_b)[0]
            P._S["i"] = tgt
            a2, b2, info, _c = P._cor_fit({"kind": s.get("kind"), "label": s.get("label"),
                                           "a": s["a"], "b": bad_b, "seq": 900000 + hash(name) % 1000})
            dev_after = C.closest_on_polys(corr["polys"], b2)[0]
            moved = float(info["moved_mm"])
            print("   [%s] 注入后 dev_before=%.1fmm (r=%.1f)" % (name, dev_before, r))
            print("            夹回后 b=%s dev_after=%.3fmm 回中 %.1fmm (=超出的 %.1fmm) why=%s"
                  % ([round(float(x), 1) for x in b2], dev_after, moved, dev_before - r, info["why"]))
            judge("%s: 越界被识别并夹回管内" % name,
                  bool(info["cut"]) and dev_after <= r + 1e-6, "cut=%s dev_after=%.3f≤%.1f"
                  % (info["cut"], dev_after, r))
            judge("%s: 回中量 = 偏差−半径" % name,
                  abs(moved - (dev_before - r)) < 1e-3, "moved=%.3f 期望=%.3f" % (moved, dev_before - r))

    # ── ④ 每拍核点: 人为把 u 抬到 1.0, 发布点也不许出管 ─────────────────
    print("\n④ 每拍发布点核验 (真实段, u=0.37/0.71/1.0):")
    if tgt is not None:
        s = segs[tgt]
        P._S["i"] = tgt
        fit = P._cor_fit({"kind": s.get("kind"), "label": s.get("label"),
                          "a": s["a"], "b": s["b"], "seq": 0})
        a2, b2, info, corr = fit
        bad = 0
        for u in (0.37, 0.71, 1.0):
            u2, t = P._cor_pub({"seq": 0}, corr, a2, b2, u)
            p = [a2[i] + (b2[i] - a2[i]) * u2 for i in range(3)]
            dev = C.clamp_into(corr, p)[1]
            print("   u=%.2f → u_pub=%.4f  dev=%.3fmm  in=%s  cut=%s"
                  % (u, u2, dev["dev_mm"], dev["in_channel"], t.get("cut")))
            if not dev["in_channel"]:
                bad += 1
        judge("每拍发布点都在管内", bad == 0, "越界 %d 拍" % bad)

    # ── ③b 保持段 (AOI 检测) 也不许飘 ────────────────────────────────────
    print("\n③b 保持段 (AOI 检测, 零位移) 漂移夹回:")
    hold = next((i for i, s in enumerate(segs)
                 if not P._skill_stage(s.get("kind"), s.get("label"))
                 and abs(float(s["a"][0]) - float(s["b"][0])) < 1e-6), None)
    if hold is None:
        judge("找到保持段", False)
    else:
        s = segs[hold]
        P._S["i"] = hold
        r_h = float((P._gate_info(hold) or {}).get("r_mm") or 0.0)
        drift = [float(s["a"][0]) + 2.5 * r_h, float(s["a"][1]), float(s["a"][2])]
        fit = P._cor_fit({"kind": s.get("kind"), "label": s.get("label"),
                          "a": s["a"], "b": s["b"], "seq": 800001})
        a_h, b_h, info_h, corr_h = fit
        p_out, i_out = C.clamp_into(corr_h, drift)
        print("   保持点 %s · r=%.1fmm · 漂移点 %s" % (
            [round(float(x), 1) for x in s["a"]], r_h, [round(x, 1) for x in drift]))
        print("   漂移 dev=%.1fmm → 夹回后 dev=%.1fmm 回中 %.1fmm (%s)"
              % (i_out["dev_mm"], C.clamp_into(corr_h, p_out)[1]["dev_mm"],
                 i_out["moved_mm"], i_out["why"]))
        judge("保持段有通道且漂移被夹回", bool(info_h["stage"] == "保持")
              and C.clamp_into(corr_h, p_out)[1]["dev_mm"] <= r_h + 1e-6, "")

    # ── ⑦ 发布路径端到端: 走真 _pub_ar (写临时 ar_cmd, 不动现场文件) ───────
    print("\n⑦ 发布路径端到端 (_pub_ar, 临时 ar_cmd):")
    if tgt is not None:
        import tempfile
        s = segs[tgt]
        P._S["i"] = tgt
        P._AR_PUB = True
        os.environ["ZMAX_AR_OWNER"] = "plan"
        tmpf = os.path.join(tempfile.mkdtemp(dir="/home/ubuntu/.hermes/cache/scratch"), "ar_cmd_t.json")
        P._AR_CMD = tmpf
        o1 = {"kind": s.get("kind"), "label": s.get("label"), "a": s["a"], "b": s["b"],
              "seq": tgt, "task_id": "selfcheck", "mod": "sim"}
        P._pub_ar(o1, 0.5, 0.3, 0.15)
        d = json.load(open(tmpf))
        cor = (d.get("gate") or {}).get("cor") or {}
        print("   名义发布: a==原起点 %s · b==原终点 %s · gate.cor.dev_b=%.3f · tick.dev=%.3f · in=%s"
              % (d["a"] == [float(x) for x in s["a"]], d["b"] == [float(x) for x in s["b"]],
                 float(cor["dev_b"]) if "dev_b" in cor else -1.0, float((cor.get("tick") or {}).get("dev_mm", -1.0)),
                 (cor.get("tick") or {}).get("in")))
        judge("名义发布逐位不变 (a/b 未被乱改)",
              d["a"] == [float(x) for x in s["a"]] and d["b"] == [float(x) for x in s["b"]],
              "b_raw=%s" % ("有(误夹)" if "b_raw" in d else "无(正确)"))
        judge("发布里带通道取证 gate.cor", bool(cor) and "r_mm" in cor and "tick" in cor,
              "src=%s" % str(cor.get("src"))[:44])
        # 实际起点漂移 3r ⇒ 发布 a 必须被夹回管内
        r = float(P._cor("转移")["r_mm"])
        u_ax = C._unit(C._sub([float(x) for x in s["b"]], [float(x) for x in s["a"]]))
        e1, _e2 = C._perp_basis(u_ax)
        a_eff = [float(s["a"][k]) + e1[k] * 3 * r for k in range(3)]
        P._pub_ar(dict(o1, seq=tgt + 100000), 0.5, 0.3, 0.15, a_eff=a_eff)
        d2 = json.load(open(tmpf))
        corr = P._cor("转移")
        a_dev = C.clamp_into(corr, d2["a"])[1]
        print("   起点漂移 %.1fmm ⇒ 发布 a=%s dev=%.3fmm in=%s · 原起点留在 a_raw=%s"
              % (3 * r, [round(float(x), 1) for x in d2["a"]], a_dev["dev_mm"],
                 a_dev["in_channel"], d2.get("a_raw") == [float(x) for x in s["a"]]))
        judge("实际起点漂移被夹回管内 (发布点真被约束)", a_dev["in_channel"],
              "dev=%.1f ≤ r=%.1f" % (a_dev["dev_mm"], r))
        judge("原始起点保真在 a_raw", d2.get("a_raw") == [float(x) for x in s["a"]], "")

    # ── ⑤ 关闸零回归 ──────────────────────────────────────────────────
    print("\n⑤ 关闸 A/B (ZMAX_PLAN_CORRIDOR=0):")
    code = ("import importlib.util,os,json;os.environ['ZMAX_PLAN_CORRIDOR']='0';"
            "spec=importlib.util.spec_from_file_location('p2','%s');m=importlib.util.module_from_spec(spec);"
            "spec.loader.exec_module(m);m.run({});segs=m._S['segs'];"
            "fit=m._cor_fit(segs[0]);print(json.dumps({'on':m._COR_ON,'fit':fit is None,"
            "'n':len(segs),'a':segs[0].get('a'),'b':segs[0].get('b')},ensure_ascii=False))" % PLAN)
    out = subprocess.run([os.path.join(ROOT, "gui-venv311/bin/python"), "-c", code],
                         capture_output=True, text=True, cwd=ROOT).stdout.strip().splitlines()[-1]
    d0 = json.loads(out)
    s0 = segs[0]
    judge("关闸后不夹点", d0["fit"] is True and d0["on"] is False, "fit=None 段数=%d" % d0["n"])
    judge("关闸后段表逐位不变", d0["a"] == s0.get("a") and d0["b"] == s0.get("b"), "")

    # ── ⑥ 算法同源 ────────────────────────────────────────────────────
    print("\n⑥ 算法同源:")
    m_on = P._corridor_mod()
    judge("plan 用的是 state_space/corridor.py", os.path.realpath(getattr(m_on, "__file__", "")) == os.path.realpath(
        os.path.join(ROOT, "src/lerobot/policies/left_right/state_space/corridor.py")),
        getattr(m_on, "__file__", "?"))
    judge("同一函数 clamp_into 供技能侧共用", callable(getattr(m_on, "clamp_into", None)) and callable(
        getattr(m_on, "project_stage", None)), "clamp_into/project_stage 均在")

    print("\n%s %d 项判据, 失败 %d 项 %s" % (OK if not _fail else BAD, _checks[0], len(_fail),
                                            ("← " + ", ".join(_fail)) if _fail else "全绿"))
    return 0 if not _fail else 1


if __name__ == "__main__":
    sys.exit(main())
