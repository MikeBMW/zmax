#!/usr/bin/env python3
"""运动学/动力学约束 验收 + 现场可观察状态  (老倪: 要可测、要可观察、要有配置参数)

三条链路:
  ① 配置链路 — 每个技能段的 v/a/jerk/通道半径都在工程配置里, 有单位有范围, 参数中心可改；
     且每个数字在 provenance 里有「真实来源」(F/m、实测 jerk P99、通道扫掠外廓)。
  ② 发布信号 — 按画布 loop 节奏驱真 plan.run(), 用全局位置 p=a+u·(b−a) 反算拍间 v/a/jerk,
     与配置上限逐拍对比; 起停段断言 a/jerk, 连续段只断言 v。
  ③ 可观察   — 结果写 zmax_data/ss_live/dyn_status.json (页面/巡检可读), --watch 直接盯。

用法:
  ./gui-venv311/bin/python tools/ss_dyn_verify.py               # 30s 采样 + 判据 + 写状态
  ./gui-venv311/bin/python tools/ss_dyn_verify.py 60            # 采样 60s
  ./gui-venv311/bin/python tools/ss_dyn_verify.py --watch       # 盯现场状态文件
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
import tempfile
import time

ROOT = os.path.expanduser("~/zmax")
CALIB = os.path.join(ROOT, "config", "calib", "zmax_calib.json")
PROV = os.path.join(ROOT, "config", "calib", "zmax_dyn_provenance.json")
STATUS = os.path.join(ROOT, "zmax_data", "ss_live", "dyn_status.json")
PLAN = os.path.join(ROOT, "src", "lerobot", "engineering", "nodes", "plan_long_impl.py")
STAGES = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入", "完成"]


def _j(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def load_plan():
    spec = importlib.util.spec_from_file_location("p", PLAN)
    P = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(P)
    P._AR_CMD = os.path.join(tempfile.mkdtemp(), "ar_cmd.json")   # 采样不碰现场 ar_cmd
    P._AR_PUB = True
    return P


# ── ① 配置链路 ───────────────────────────────────────────────────────────
def check_config():
    rows, fails = [], []
    cfg = (_j(CALIB).get("dyn_limits") or {}) if os.path.isfile(CALIB) else {}
    prov = _j(PROV) if os.path.isfile(PROV) else {}
    for st in STAGES:
        d = (cfg.get("stages") or {}).get(st) or {}
        p = prov.get(st) or {}
        ok = all(float(d.get(k) or 0) > 0 for k in ("v_cap_mm_s", "a_max_mm_s2", "jerk_max_mm_s3", "r_mm"))
        has_src = all((p.get(k) or {}).get("src") for k in ("v_cap_mm_s", "a_max_mm_s2", "jerk_max_mm_s3"))
        rows.append((st, d.get("v_cap_mm_s"), d.get("a_max_mm_s2"), d.get("jerk_max_mm_s3"),
                     d.get("r_mm"), ok, has_src))
        if not ok:
            fails.append("%s 配置缺值" % st)
        if not has_src:
            fails.append("%s 缺真实来源" % st)
    pol = cfg.get("policy") or {}
    if int(pol.get("profile_mode", -1)) != 1:
        fails.append("profile_mode≠1 (折中档未启用)")
    return rows, fails, cfg, prov


# ── ② 发布信号逐拍 ───────────────────────────────────────────────────────
def sample(P, seconds, hz):
    ticks = []
    t_end = time.time() + seconds
    seen = 0.0
    while time.time() < t_end:
        P.run({})
        st = os.stat(P._AR_CMD)
        if st.st_mtime != seen:
            seen = st.st_mtime
            d = _j(P._AR_CMD)
            g = d.get("gate") or {}
            dy = (g.get("skill") or {}).get("dyn") or {}
            u = float(d.get("u") or 0.0)
            a = [float(x) for x in (d.get("a") or [0, 0, 0])]
            b = [float(x) for x in (d.get("b") or [0, 0, 0])]
            _seg = (str(g.get("stage")),) + tuple(round(float(x), 2) for x in (a + b))
            ticks.append({"t": float(d.get("t") or 0.0), "seq": _seg, "stage": g.get("stage"),
                          "u": u, "p": [a[k] + (b[k] - a[k]) * u for k in range(3)],
                          "v_lim": float((g.get("skill") or {}).get("v_cap") or 0.0),
                          "a_lim": float(dy.get("a_cap") or 0.0), "j_lim": float(dy.get("j_cap") or 0.0),
                          "stopgo": bool(dy.get("stopgo")), "profile": dy.get("profile"),
                          "cfg": dy.get("cfg"), "dyn_on": bool(dy.get("on"))})
        time.sleep(1.0 / max(hz, 1.0))
    return ticks


def analyse(ticks):
    """逐拍反算 v/a/jerk。

    · seq 是**发布计数器**(每写一次 +1), 不能当段号 —— 只用时间连续 + 物理可实现性判同段
    · 跳变 (段切换/位置对齐) 用「本拍位移 > 3×v_lim·dt + 2mm」识别, 识别到就断链, 不计入
    """
    agg = {}
    prev = None
    for r in ticks:
        key = (r["stage"], r["stopgo"])
        d = agg.setdefault(key, {"n": 0, "v": 0.0, "a": 0.0, "j": 0.0,
                                "v_lim": r["v_lim"], "a_lim": r["a_lim"], "j_lim": r["j_lim"],
                                "v_over": 0, "a_over": 0, "j_over": 0})
        r["_v"] = r["_a"] = None
        if prev is not None:
            dt = r["t"] - prev["t"]
            jump = math.dist(r["p"], prev["p"])
            if 0.02 <= dt <= 0.5 and r["seq"] == prev["seq"]:      # 只算同一段的拍 (段切换的位移是跳变, 不是速度)
                v = jump / dt
                if prev.get("_v") is not None:
                    a = (v - prev["_v"]) / dt
                    j = (a - prev["_a"]) / dt if prev.get("_a") is not None else 0.0
                    d["n"] += 1
                    d["v"], d["a"], d["j"] = max(d["v"], v), max(d["a"], abs(a)), max(d["j"], abs(j))
                    if d["v_lim"] > 0 and v > d["v_lim"] * 1.02:
                        d["v_over"] += 1
                    if r["stopgo"] and d["a_lim"] > 0 and abs(a) > d["a_lim"] * 1.05:
                        d["a_over"] += 1
                    if r["stopgo"] and d["j_lim"] > 0 and abs(j) > d["j_lim"] * 1.10:
                        d["j_over"] += 1
                    r["_a"] = a
                r["_v"] = v
        prev = r
    return agg


def main(argv):
    if "--watch" in argv:
        while True:
            try:
                d = _j(STATUS)
                print("%s v%s a%s j%s · 起停段 %s/%s 拍 · UPH %s" % (
                    d.get("t"), d.get("verdict", {}).get("v"), d.get("verdict", {}).get("a"),
                    d.get("verdict", {}).get("j"), d.get("stopgo_ticks"), d.get("ticks"),
                    d.get("uph_model")), flush=True)
            except Exception as e:                                  # noqa: BLE001
                print("无状态: %s" % e, flush=True)
            time.sleep(2.0)
        return 0

    secs = 30.0
    for a in argv:
        try:
            secs = float(a)
        except ValueError:
            pass

    rows, fails, cfg, prov = check_config()
    print("① 工程配置 (唯一依据 %s:dyn_limits)" % os.path.relpath(CALIB, ROOT))
    print("   %-5s %10s %11s %12s %7s  %s" % ("阶段", "v_cap", "a_max", "jerk", "r", "来源"))
    for st, v, a, j, r, ok, hsrc in rows:
        print("   %-5s %10.1f %11.1f %12.1f %7.1f  %s" % (
            st, v or 0, a or 0, j or 0, r or 0, "✅实测溯源" if hsrc else "❌缺源"))
    print("   剖面 mode=%s · jerk 只限起停段=%s" % ((cfg.get("policy") or {}).get("profile_mode"),
                                              (cfg.get("policy") or {}).get("jerk_stopgo_only")))

    P = load_plan()
    ticks = sample(P, secs, 10.0)
    agg = analyse(ticks)
    print("\n② 发布信号逐拍 (%.0fs, %d 拍)" % (secs, len(ticks)))
    print("   (单位 mm/s · mm/s² · mm/s³, 与工程配置同口径; 起停段才判 a/jerk)")
    print("   %-5s %-4s %5s %14s %14s %14s" % ("阶段", "起停", "拍", "v峰/上限", "a峰/上限", "j峰/上限"))
    tot = {"n": 0, "v": 0, "vA": 0, "vJ": 0}
    for (st, sg), d in sorted(agg.items(), key=lambda kv: (kv[0][0] or "", kv[0][1])):
        if not d["n"]:
            continue
        print("   %-5s %-4s %5d %7.3f/%-6.3f %7.2f/%-6.2f %7.0f/%-6.0f%s" % (
            st, "是" if sg else "否", d["n"], d["v"], d["v_lim"], d["a"], d["a_lim"], d["j"], d["j_lim"],
            "  ⚠" if (d["v_over"] or d["a_over"] or d["j_over"]) else ""))
        tot["n"] += d["n"]
        tot["v"] += d["v_over"]
        tot["vA"] += d["a_over"]
        tot["vJ"] += d["j_over"]

    if tot["n"] < 50:                      # 采样不够就不许判绿 (0 拍也全绿 = 假绿)
        fails.append("有效拍只有 %d (<50), 采样不足, 不判合格" % tot["n"])
    v_ok = tot["v"] == 0
    a_ok = tot["vA"] == 0
    j_ok = tot["vJ"] == 0
    print("\n③ 判据: v 超限 %d 拍 %s · a 超限 %d 拍 %s · jerk 超限 %d 拍 %s (共 %d 拍)" % (
        tot["v"], "✅" if v_ok else "❌", tot["vA"], "✅" if a_ok else "❌",
        tot["vJ"], "✅" if j_ok else "❌", tot["n"]))
    for f in fails:
        print("   ❌ %s" % f)

    hold = float(P._S.get("hold_s") or 0.0)
    te = sum(float(P._S["cum_eff"][i] - (P._S["cum_eff"][i - 1] if i > 0 else 0.0))
             for i in range(len(P._S["segs"])))
    cyc = te + hold
    st = {"t": time.strftime("%F %T"), "cfg_src": "config/calib/zmax_calib.json:dyn_limits",
          "profile_mode": (cfg.get("policy") or {}).get("profile_mode"),
          "ticks": len(ticks), "stopgo_ticks": sum(v["n"] for k, v in agg.items() if k[1]),
          "hold_s": round(hold, 2), "hold_n": int(P._S.get("hold_n") or 0),
          "verdict": {"v": bool(v_ok), "a": bool(a_ok), "j": bool(j_ok), "cfg": not fails},
          "v_over": tot["v"], "a_over": tot["vA"], "j_over": tot["vJ"],
          "plan_t_s": round(te, 2), "cycle_s": round(cyc, 2),
          "uph_model": int(3600.0 / max(cyc / 16.0, 1e-9)),
          "stages": {"%s/%s" % ("stopgo" if k[1] else "cont", k[0]): {
              "n": v["n"], "v": round(v["v"], 4), "a": round(v["a"], 2), "j": round(v["j"], 1),
              "v_lim": v["v_lim"], "a_lim": v["a_lim"], "j_lim": v["j_lim"]} for k, v in agg.items()},
          "source": {k: (prov.get(k) or {}) for k in STAGES}}
    os.makedirs(os.path.dirname(STATUS), exist_ok=True)
    with open(STATUS + ".tmp", "w", encoding="utf-8") as fh:
        json.dump(st, fh, ensure_ascii=False, indent=1)
    os.replace(STATUS + ".tmp", STATUS)
    print("   状态 → %s  (UPH 模型 %d · hold 累计 %.1fs)" % (
        os.path.relpath(STATUS, ROOT), st["uph_model"], hold))
    ok = v_ok and a_ok and j_ok and not fails
    print("\n%s" % ("✅ 全绿: v/a/jerk 都在工程配置上限内 (起停段 a/jerk 受限)" if ok
                    else "❌ 有超限, 见上表"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
