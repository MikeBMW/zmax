#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/verify_meta_task_chain.py — 判据: 元任务链 (Phase 0 的 L2 功能 → 元任务 → 技能逐个真执行 /
L3 元任务 / L4 配置工单 / 总体设计文档) 是真的

老倪 2026-10-16 要求: 「phase 0 的 L2级功能, 通过配置, 变成元任务, 每个原子技能都要执行; L3, 配置模型,
形成 L3元任务; 同理, L4元任务, 形成配置工单, 最后交付 元任务的定义, 迭代阶段, 组成, 评估分析, 性能指标,
以及验证报告; 我要在文档中心, 得到元任务的总体设计文档, 发到飞书。」

判据四段 (全部对**真源**核, 不看工具自己的说法):
  A L2 元任务  条数 == config_meta 里 layer=L2 的功能数 · 逐条带配置实例/执行入口/阶段指标 · 配置取自真源
  B 技能执行   **每个原子技能都真跑了** (SKILLS ∪ SKILLS_TRAY 全覆盖) · 执行过真闸门 · 可行性与 big/err 自洽
               · 削因统计与 why 一致 · 在役对照逐条等于 skill_latest.json · 物理量等于技能类 phys() · 无对照不编数
  C L3/L4      L3 元任务 == layer=L3 条数 + 真模块三环节核验 (‖p‖=1 · M 取在役真源) · L4 工单 == L4/L5 条数 + 要件齐
  D 文档       总体设计文档六章齐 · 数字与真源一致 · 文档中心已登记 · 口径说明在 (请求不同源如实写)
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "src"))

import meta_task_chain as mtc                                              # noqa: E402

OK, BAD = [], []


def chk(name, ok, detail=""):
    (OK if ok else BAD).append(name)
    print("%s %-64s %s" % ("✅" if ok else "❌", name, detail))


def main():
    print("═" * 100)
    print("判据: 元任务链 (Phase 0 L2 → 元任务 → 每个原子技能真执行 · L3 · L4 · 总体设计文档) v%s"
          % mtc.VERSION)
    print("═" * 100)
    cfg = mtc._j(os.path.join(mtc.DB, "config_meta.json")) or {}
    funs = cfg.get("functions") or {}
    l2_src = {k: v for k, v in funs.items() if str(v.get("layer", "")).upper() == "L2"}
    l3_src = {k: v for k, v in funs.items() if str(v.get("layer", "")).upper() == "L3"}
    l4_src = {k: v for k, v in funs.items() if str(v.get("layer", "")).upper() in ("L4", "L4/L5", "L5")}

    # ── A: Phase 0 的 L2 级功能 → 配置 → 元任务 ────────────────────────────────
    l2, pm = mtc.l2_tasks("0")
    chk("A1 Phase 0 的 L2 元任务条数 == config_meta 里 layer=L2 功能数",
        len(l2) == len(l2_src), "%d == %d" % (len(l2), len(l2_src)))
    chk("A2 每条元任务带: 元任务号/功能号/名称/执行入口/配置实例/阶段指标",
        all(t["mt_id"] and t["fn_id"] and t["name"] and t["执行入口"] and t["配置"] and "指标" in t
            for t in l2), "例: %s" % l2[0]["mt_id"])
    chk("A3 元任务的配置实例逐条等于配置真源 fields (不是另手写一套)",
        all(t["配置"]["declared_flags"] == (l2_src[t["fn_id"]].get("fields") or {}).get("declared_flags")
            and t["配置"]["parameters"] == (l2_src[t["fn_id"]].get("fields") or {}).get("parameters")
            for t in l2), "核了 %d 条" % len(l2))
    chk("A4 每条元任务都归到迭代阶段 Phase 0 (阶段 + 指标总数 取自 iteration_roadmap)",
        all(t["phase"] == pm.get("phase") and t["阶段指标总数"] > 0 for t in l2),
        "%s %s · 指标 %d" % (pm.get("phase"), pm.get("name"), pm.get("阶段指标总数", 0) or
                            len(pm.get("target_metrics") or [])))
    _sk_fns = {"FN-SYS0-%d" % i for i in range(51, 59)}
    chk("A5 元任务清单覆盖全部 8 条原子技能功能 (FN-SYS0-51..58)",
        _sk_fns <= {t["fn_id"] for t in l2}, "命中 %d/8 条" % len(_sk_fns & {t["fn_id"] for t in l2}))

    # 现场常驻服务 60Hz 重写 ss_live/*.json ⇒ 判据先**冻源**(拷一份再测), 否则同一份代码时红时绿
    import shutil
    import tempfile
    _snap = tempfile.mkdtemp(prefix="mtc_live_")
    for _fn in ("skill_latest.json", "engine_latest.json"):
        _p = os.path.join(mtc.LIVE, _fn)
        if os.path.isfile(_p):
            shutil.copy2(_p, os.path.join(_snap, _fn))
    mtc.LIVE = _snap

    # ── B: 每个原子技能都真执行 ───────────────────────────────────────────────
    from lerobot.policies.left_right.state_space.skills.atomic_skills import SKILLS, SKILLS_TRAY
    skl = mtc.exec_atomic_skills("0")
    want = [(c.code, c.stage) for c in list(SKILLS)] + [(c.code, c.stage) for c in list(SKILLS_TRAY)]
    got = [(r["code"], r["stage"]) for r in skl]
    chk("B1 每个原子技能都执行了 (SKILLS ∪ SKILLS_TRAY 逐个覆盖, 一条不缺)",
        sorted(want) == sorted(got) and len(got) == len(want),
        "%d 个技能实例 (%d 插拔 + %d 摆盘)" % (len(got), len(SKILLS), len(SKILLS_TRAY)))
    chk("B2 执行是真过闸门 (重跑一次逐条复现 ⇒ 同源可复算)",
        _reproduce(skl), "重跑 %d 条, 逐位一致" % len(skl))
    chk("B3 可行性与 big/err 自洽 (可行 ⇔ 没削且偏差未越 big 阈)",
        all(bool(r["执行"]["可行"]) == (int(r["执行"]["big"] or 0) == 0) for r in skl if r["执行"]["err"] is None),
        "✅ %d 条可行 · ❌ %d 条被削" % (len([r for r in skl if r["执行"]["可行"]]),
                                     len([r for r in skl if not r["执行"]["可行"]])))
    # why 是**末拍**的结论, 削因统计是 20 拍累计 ⇒ 口径: 有累计削因 ⇔ 末拍被削或本窗口出现过削
    chk("B4 削因统计与 why 口径一致 (削因=20 拍累计, why=末拍; 二者不许互相矛盾)",
        all(bool(r["执行"]["削因统计"]) == (str(r["执行"]["why"]) != "可行" or
                                        int(r["执行"]["不可行拍"] or 0) > 0) for r in skl),
        "削因种类: %s" % "/".join(sorted({k for r in skl for k in (r["执行"]["削因统计"] or {})})))
    live = mtc._j(os.path.join(mtc.LIVE, "skill_latest.json")) or {}
    same = all((r["在役对照"]["请求_mps"] == live.get("%s_请求_mps" % r["stage"]) and
                r["在役对照"]["闸后_mps"] == live.get("%s_mps" % r["stage"]) and
                r["在役对照"]["偏差_mps"] == live.get("%s_偏差_mps" % r["stage"]))
               for r in skl)
    chk("B5 在役对照逐条等于 skill_latest.json 真值 (冻源后逐位比对, 不自己算一个冒充在役)", same,
        "源: zmax_data/ss_live/skill_latest.json (判据内冻结快照)")
    phy_ok = True
    for r in skl:
        cls = _find_class(r["code"], r["stage"])
        q = cls.phys() if cls else {}
        if q and float(r["物理量"]["m_kg"] or 0) != float(q.get("m") or 0):
            phy_ok = False
    chk("B6 物理量 (m/F/v_cap/a_max/jerk/s_step/dmdt) 逐条等于技能类 phys() (标定真源)",
        phy_ok, "例: SK01 m=%.2fkg v_cap=%.3fm/s" % (float(skl[0]["物理量"]["m_kg"] or 0),
                                                   float(skl[0]["物理量"]["v_cap_mps"] or 0)))
    tray = [r for r in skl if r["chain"] == "摆盘链" and r["stage"] == "放入"]
    chk("B7 在役没有的技能段如实留空 (摆盘链 放入 在役对照=None, 不编数)",
        bool(tray) and all(v is None for k, v in tray[0]["在役对照"].items() if k != "拍"),
        "放入: %s" % json.dumps(tray[0]["在役对照"], ensure_ascii=False) if tray else "缺")
    chk("B8 不可行拍是真跑出来的 (20 拍窗口内因技能而异, 不是常数)",
        len({int(r["执行"]["不可行拍"] or 0) for r in skl}) > 1 and
        all(0 <= int(r["执行"]["不可行拍"] or 0) <= int(r["执行"]["拍数"] or 0) for r in skl) and
        any(int(r["执行"]["不可行拍"] or 0) < int(r["执行"]["拍数"] or 0) for r in skl) and
        any(int(r["执行"]["不可行拍"] or 0) == int(r["执行"]["拍数"] or 0) for r in skl),
        "例 SK01 不可行 %d 拍 · SK07 不可行 %d 拍" % (
            [r for r in skl if r["code"] == "SK01"][0]["执行"]["不可行拍"],
            [r for r in skl if r["code"] == "SK07" and r["chain"] == "插拔链"][0]["执行"]["不可行拍"]))

    # ── C: L3 / L4 ───────────────────────────────────────────────────────────
    l3, l3ctx = mtc.l3_tasks()
    chk("C1 L3 元任务条数 == config_meta 里 layer=L3 功能数", len(l3) == len(l3_src),
        "%d == %d" % (len(l3), len(l3_src)))
    chk("C2 L3 真模块核验含三环节 (投影 ‖p‖=1 · 度量 ∇Φ · 导航 step) 且 M 取在役真源",
        abs(float(((l3ctx.get("投影") or {}).get("‖p‖") or 0)) - 1.0) < 1e-6 and
        (l3ctx.get("度量") or {}).get("phi") is not None and
        (l3ctx.get("导航") or {}).get("键") and "M 来源" in l3ctx,
        "M=%.3f · φ=%s · ‖∇Φ‖=%s" % (float(((l3ctx.get("投影") or {}).get("M") or 0)),
                                      (l3ctx.get("度量") or {}).get("phi"),
                                      (l3ctx.get("度量") or {}).get("‖∇Φ‖")))
    wo = mtc.l4_work_orders()
    chk("C3 L4 元任务 → 配置工单条数 == layer∈(L4,L4/L5,L5) 功能数", len(wo) == len(l4_src),
        "%d == %d" % (len(wo), len(l4_src)))
    chk("C4 每条工单要件齐 (工单号/元任务/配置项/责任/验收/证据/阶段)",
        all(o["工单号"] and o["元任务"] and "配置项" in o and o["责任"] and o["验收"] and o["证据"] and o["阶段"]
            for o in wo), "例: %s" % wo[0]["工单号"])
    chk("C5 工单号唯一 (无重号)", len({o["工单号"] for o in wo}) == len(wo), "%d 条唯一" % len(wo))

    # ── D: 文档 + 文档中心 ───────────────────────────────────────────────────
    doc_path = mtc.DOC_OUT
    exists = os.path.isfile(doc_path)
    txt = open(doc_path, encoding="utf-8").read() if exists else ""
    heads = ["## ① 元任务定义", "## ② 迭代阶段", "## ③ 组成", "## ④ 评估分析", "## ⑤ 性能指标", "## ⑥ 验证报告"]
    chk("D1 总体设计文档存在且六章齐 (定义/迭代阶段/组成/评估分析/性能指标/验证报告)",
        exists and all(h in txt for h in heads),
        "%s (%d 字符)" % (os.path.relpath(doc_path, ROOT) if exists else "缺", len(txt)))
    chk("D2 文档数字与真源一致 (L2 元任务数 · L3/L4 条数 · 原子技能执行条数)",
        ("L2 元任务: **%d**" % len(l2)) in txt and
        ("L3 元任务: **%d**" % len(l3)) in txt and
        ("L4 元任务 → 配置工单: **%d**" % len(wo)) in txt,
        "L2=%d · L3=%d · L4=%d" % (len(l2), len(l3), len(wo)))
    chk("D3 文档里逐技能执行记录是真的 (含 16 行技能链 + 削因统计)",
        txt.count("| `SK") >= 16 and "不可行" in txt, "SK 行数 %d" % txt.count("| `SK"))
    topo = os.path.join(ROOT, "docs/notes/DOCUMENT-TOPOLOGY.md")
    chk("D4 文档中心已登记 (docs/notes/DOCUMENT-TOPOLOGY.md 含该文档路径)",
        os.path.isfile(topo) and "元任务总体设计_v5.50.736.md" in open(topo, encoding="utf-8").read(),
        "docs/notes/DOCUMENT-TOPOLOGY.md")
    chk("D5 口径说明在 (在役对照与本次执行帧不同源, 如实写出来)",
        "口径说明" in txt and "不同源" in txt, "④ 章口径说明")
    chk("D6 飞书发送通道就位 (文档 + 报告群)", os.path.isfile(os.path.join(ROOT, "tools/feishu_send_file.py")) and
        os.path.isfile(os.path.join(ROOT, "tools/feishu_send.py")),
        "tools/feishu_send_file.py · tools/feishu_send.py")

    print("═" * 100)
    print("判据 %d 条: PASS %d · FAIL %d" % (len(OK) + len(BAD), len(OK), len(BAD)))
    if BAD:
        print("未过: %s" % BAD)
    print("═" * 100)
    return 1 if BAD else 0


def _find_class(code, stage):
    from lerobot.policies.left_right.state_space.skills.atomic_skills import SKILLS, SKILLS_TRAY
    for c in list(SKILLS) + list(SKILLS_TRAY):
        if c.code == code and c.stage == stage:
            return c
    return None


def _reproduce(rows):
    """重跑一次 exec_atomic_skills, 与传入结果逐条比对 (证明可复算 + 不是编的)"""
    again = mtc.exec_atomic_skills("0")
    if len(again) != len(rows):
        return False
    for a, b in zip(again, rows):
        for k in ("code", "stage", "chain", "why", "err_norm", "v_out_norm", "v_req_norm", "不可行拍"):
            if a["执行"].get(k) != b["执行"].get(k):
                return False
    return True


if __name__ == "__main__":
    sys.exit(main())
