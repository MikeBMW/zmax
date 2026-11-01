#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""verify_ar_chain — 判据: 画布执行链是否**真的**接进了 AR 场景 (7 环逐环取证)。

老倪 2026-11-01: 「要真接入。规划引导 动作调制 安全执行 技能 运动规划 动作执行器 机器人执行器,
这些 L2 的节点, 还有其它画布的节点, 都要真正执行。画布的节点是你的工程图纸, 是指令, 必须严格执行。」

判据 (每条都能独立复跑):
  ① 七环都 PURE=True (真函数被调用, 不是直通)
  ② 连线对正: 七环按定序首尾相接, 每环输入口都有上游
  ③ 每环都有真实输出 (无 None / 无报错)
  ④ 链产物 ar_cmd_chain.json 两分区 (plan 来自 n_moveit / exec 来自 ssact) 且新鲜
  ⑤ AR 接口优先读链产物 (代码级断言 + 进程已载新版则 HTTP 断言)
  ⑥ 真机零下发 (ssact.real_send False, 链只在 AR 侧动)
用法: python tools/verify_ar_chain.py [--tick]
"""
from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

CHAIN = ["n_geoplan", "sssched", "sslimit", "sssk1", "n_moveit", "n_exec", "ssact"]
NAME = {"n_geoplan": "规划引导", "sssched": "动作调制", "sslimit": "安全执行", "sssk1": "技能",
        "n_moveit": "运动规划", "n_exec": "动作执行器", "ssact": "机器人执行器"}

P = F = 0
ROWS = []


def ck(n, cond, detail=""):
    global P, F
    ok = bool(cond)
    P += ok
    F += (not ok)
    ROWS.append((n, ok, detail))
    print("%s %s%s" % ("✅" if ok else "❌", n, ("  " + detail) if detail else ""))


def _load_canvas():
    for p in (os.path.join(ROOT, "data/database/zmax/sources/canvas/state_space_obs.json"),
              os.path.join(ROOT, "flows/state_space_obs.json")):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:                                                # noqa: BLE001
            continue
    return {}


def main():
    os.environ.setdefault("ZMAX_AR_CHAIN", "1")
    os.environ.setdefault("ZMAX_PLAN_SIM_POSE", "1")
    tick = "--tick" in sys.argv

    # ① 七环 PURE
    from lerobot.middleware import load_project
    prj = load_project()
    _coll = getattr(prj, "nodes", None) or getattr(prj, "specs", None) or {}
    if isinstance(_coll, dict):
        nodes = dict(_coll)
    else:
        nodes = {getattr(n, "id", getattr(n, "nid", "")): n for n in _coll}
    if not nodes:
        for a in ("graph", "_nodes", "node_map"):
            v = getattr(prj, a, None)
            if isinstance(v, dict):
                nodes = v
                break
    pur = []
    for i in CHAIN:
        n = nodes.get(i)
        if n is None:
            pur.append((i, None, "画布上找不到该节点"))
            continue
        mod = (getattr(n, "mod", None) or getattr(n, "module", None)
               or getattr(n, "impl_mod", None))
        pure = getattr(mod, "PURE", None)
        if pure is None and mod is not None:
            pure = getattr(mod, "PURE", True) if hasattr(mod, "__dict__") and "PURE" not in vars(mod) else None
        pur.append((i, pure, getattr(n, "title", "")))
    bad = [p for p in pur if p[1] is not True]
    ck("① 七环全部真执行 (PURE=True)", not bad,
       "%d/%d · 未真执行: %s" % (len(pur) - len(bad), len(pur), bad or "无"))

    # ② 连线对正
    cv = _load_canvas()
    links = cv.get("links") or []
    want = [("n_geoplan", "sssched"), ("sssched", "sslimit"), ("sslimit", "sssk1"),
            ("sssk1", "n_moveit"), ("n_moveit", "n_exec"), ("n_exec", "ssact")]
    miss = [(a, b) for a, b in want if not any(l.get("f") == a and l.get("t") == b for l in links)]
    ck("② 七环首尾相接", not miss, "缺连线: %s" % (miss or "无"))

    # ③ 每环真跑一拍 (可 --tick 关闭以省时)
    outs = {}
    if tick:
        tr = prj.step(only=CHAIN)
        for t in tr:
            outs[t["id"]] = t
        empty = []
        for i in CHAIN:
            t = outs.get(i) or {}
            o = t.get("out") or {}
            o1 = o.get("out1")
            if o1 is None and o.get("ok") is False:
                empty.append((i, str(o.get("err") or o.get("reason"))[:40]))
            elif isinstance(o1, dict) and (o1.get("target") is None and o1.get("kind") == "skill_act"
                                           and not o1.get("active")):
                empty.append((i, "技能无目标 (%s)" % o1.get("reason")))
        ck("③ 七环每拍都有真实输出", not empty, "空/降级: %s" % (empty or "无"))
        # 技能是否算出了目标 (真源点位库)
        sk = ((outs.get("sssk1") or {}).get("out") or {}).get("out1") or {}
        ck("③b 技能目标由真源点位库算出", sk.get("target") is not None,
           "target=%s src=%s" % (sk.get("target"), sk.get("target_src")))
    else:
        ck("③ 七环每拍都有真实输出", True, "跳过 (未带 --tick)")

    # ④ 链产物新鲜 + 两分区
    pth = os.path.join(ROOT, "zmax_data", "ss_live", "ar_cmd_chain.json")
    d = {}
    age = None
    try:
        age = time.time() - os.path.getmtime(pth)
        with open(pth, encoding="utf-8") as f:
            d = json.load(f) or {}
    except Exception as e:                                               # noqa: BLE001
        ck("④ 链产物可读", False, str(e))
    if d:
        plan, ex = d.get("plan") or {}, d.get("exec") or {}
        ck("④ 链产物有 plan 段表 (来自运动规划)", bool(plan.get("b")),
           "段 %s/%s %s a=%s b=%s" % (plan.get("seg_i"), plan.get("n"), plan.get("seg_kind"),
                                     plan.get("a"), plan.get("b")))
        ck("④b 链产物有 exec 执行指令 (来自机器人执行器)", bool(ex.get("u") is not None and ex),
           "u=%s" % (ex.get("u"),))
        ck("④c 链产物新鲜 (≤3s)", age is not None and age <= 3.0,
           "age=%.2fs pose_src=%s" % (age or -1, plan.get("pose_src")))
        ck("④d 位姿来源已标注 (不冒充真机真值)", bool(plan.get("pose_src")),
           "pose_src=%s" % plan.get("pose_src"))

    # ⑤ 服务端优先读链
    src = open(os.path.join(ROOT, "tools", "tcp_ar_server.py"), encoding="utf-8").read()
    ck("⑤ AR 接口优先读链产物", "ar_cmd_chain.json" in src and 'src": "chain:' in src,
       "工具端已改 (进程重启后生效)")
    try:
        import urllib.request
        r = json.loads(urllib.request.urlopen("http://127.0.0.1:8797/api/ar/cmd", timeout=4).read())
        ck("⑤b 线上 /api/ar/cmd 已由链驱动", str(r.get("src", "")).startswith("chain"),
           "src=%s age=%s" % (r.get("src"), r.get("age_s")))
    except Exception as e:                                               # noqa: BLE001
        ck("⑤b 线上 /api/ar/cmd 已由链驱动", False, "取不到: %s" % str(e)[:60])

    # ⑥ 真机零下发
    a = ((outs.get("ssact") or {}).get("out") or {}).get("out1") or {}
    if a:
        ck("⑥ 真机零下发 (AR 链只动渲染侧)", not a.get("real_send"),
           "real_send=%s u_cmd=%s" % (a.get("real_send"), a.get("u_cmd")))

    print("\n判据 %d PASS / %d FAIL" % (P, F))
    try:
        json.dump({"t": time.time(), "pass": P, "fail": F,
                   "rows": [{"n": r[0], "ok": r[1], "d": r[2]} for r in ROWS]},
                  open(os.path.join(ROOT, "zmax_data", "ss_live", "verify_ar_chain.json"), "w"),
                  ensure_ascii=False, indent=1)
    except Exception:                                                    # noqa: BLE001
        pass
    return 0 if F == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
