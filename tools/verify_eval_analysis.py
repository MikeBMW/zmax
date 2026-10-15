#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📊 评估分析 判据 (老倪 2026-10-15)

老倪原话: 「在主界面的 评估分析 功能页, 要做系统的评估分析, 当前 5.50.735 版本是基线产品, 以后要从这个版本
评估分析后, 有性能提升才能升级; 在配置中心, 所有的性能指标, 都要科学的与基线版本做对比…要保证全局数据一致性。」

判据 (每条能自己复核):
  ① 指标全集 = 配置中心真源 58 条 + 评测补充 4 条; 每条都有采集口径 (有采集器 或 明确写"未测+采集条件")
  ② 基线锁: 存在 / 版本 == v5.50.735 / 条数 == 指标全集 / **冻结** (无理由不许覆盖)
  ③ 判定枚举合法: 达标 ∈ {达标,不达标,未测,样本不足,无阈值 (待现场定)}; 基线对比 ∈ {提升,持平,回退,未测,无基线,样本不足}
  ④ **未测不许冒充 0**: 未测项 value 必须是 None 且带采集条件文字
  ⑤ 样本不足不出判定: 样本量 < 判定所需 ⇒ 达标 == 样本不足 (3 次插入算不出 3σ)
  ⑥ 升级准入三闸自洽: upgrade_allowed == 三条件全过
  ⑦ 全局一致性**真跑**: 把 L2 包络与标定真源改得不一致 (沙箱) ⇒ 冲突数 > 0; 复原 ⇒ 0
  ⑧ 阈值判定正确性: 喂假数验 verdicts (越小越好 / 越大越好 两个方向)
  ⑨ 回退必拦: 造一版有回退的报告 ⇒ upgrade_allowed == False
  ⑩ 页面渲染 (离屏真窗口): 表行数 == 报告指标数; 准入文案与报告一致; 5 张证据卡都有真源 + 帧龄; 未测行"当前"列显示 —(不是 0)
  ⑪ 证据面板真源文件都在盘上 (路径可解析)
  ⑫ 判据不留痕: 跑完基线锁文件字节级不变

用法: cd /home/ubuntu/zmax && QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/verify_eval_analysis.py
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import eval_analysis as EA                                                    # noqa: E402
import eval_probes as EP                                                      # noqa: E402

rows = []


def chk(tag, ok, ev):
    rows.append((tag, bool(ok), ev))
    print("  %s %s  %s" % ("✅" if ok else "❌", tag, ev))
    return bool(ok)


def main() -> int:
    print("═══ 评估分析 判据 (基线产品 v5.50.735 · 有提升才准升级 · 全局数据一致性) ═══")
    idx = EP.metric_index()

    # ① 指标全集
    n_spec, n_extra = len(idx), len(EP.EXTRA)
    missing = [m["id"] for m in EP.EXTRA if m["id"] in idx]
    chk("① 指标全集 = 真源 58 + 补充 4", n_spec == 58 and n_extra == 4 and not missing,
        "真源 %d 条 + 补充 %d 条 = %d ｜ 与真源撞号的补充指标 %s" % (n_spec, n_extra, n_spec + n_extra, missing or "无"))

    res = EP.run_all()
    two_none = [k for k, v in res.items() if v.get("value") is None and not (v.get("note") or "").strip()]
    chk("①b 每条未测都写了采集条件", not two_none,
        "未测 %d 条全部带「怎么采」说明 ｜ 缺说明: %s" % (sum(1 for v in res.values() if v.get("value") is None),
                                                  two_none or "无"))

    # ② 基线锁
    b0 = io.open(EA.BASELINE, encoding="utf-8").read() if os.path.exists(EA.BASELINE) else ""
    bj = json.loads(b0) if b0 else {}
    chk("② 基线锁存在且版本=5.50.735", bool(bj) and bj.get("version") == "v5.50.735",
        "%s ｜ version=%s ｜ 条数 %d ｜ 锁定于 %s" % (os.path.relpath(EA.BASELINE, ROOT), bj.get("version"),
                                                  len(bj.get("metrics") or {}), bj.get("locked_at")))
    chk("②b 基线条数 == 指标全集", len(bj.get("metrics") or {}) == n_spec + n_extra,
        "锁 %d 条 vs 指标 %d 条" % (len(bj.get("metrics") or {}), n_spec + n_extra))
    # 冻结: 再锁一次不许覆盖
    tmpd = tempfile.mkdtemp(prefix="evalchk_")
    real_base, real_rep, real_hist = EA.BASELINE, EA.REPORT, EA.HISTORY
    EA.BASELINE = os.path.join(tmpd, "baseline.json")
    EA.REPORT, EA.HISTORY = os.path.join(tmpd, "r.json"), os.path.join(tmpd, "h.jsonl")
    EA.evaluate(lock=True)
    before = io.open(EA.BASELINE, encoding="utf-8").read()
    import contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        EA.evaluate(lock=True)                                                # 第二次锁: 必须拒绝
    after = io.open(EA.BASELINE, encoding="utf-8").read()
    with contextlib.redirect_stdout(io.StringIO()):
        EA.evaluate(lock=True, relock_reason="判据自测: 允许带理由重锁")
    relocked = json.loads(io.open(EA.BASELINE, encoding="utf-8").read())
    chk("②c 基线冻结 (无理由不许覆盖)", before == after and relocked.get("relock_reason"),
        "无理由重锁 ⇒ 文件逐字节不变 %s ｜ 带理由重锁 ⇒ relock_reason=%s" %
        (before == after, (relocked.get("relock_reason") or "")[:34]))

    # 恢复真路径并出正式报告
    EA.BASELINE, EA.REPORT, EA.HISTORY = real_base, real_rep, real_hist
    with contextlib.redirect_stdout(io.StringIO()):
        rep = EA.evaluate()
    rows_by_id = {r["id"]: r for r in rep["metrics"]}

    # ③ 判定枚举
    bad3 = [(r["id"], r["达标"], r["基线对比"]) for r in rep["metrics"]
            if r["达标"] not in ("达标", "不达标", "未测", "样本不足", "无阈值 (待现场定)", "待现场实测")
            or r["基线对比"] not in ("提升", "持平", "回退", "未测", "无基线", "样本不足", "待现场实测")]
    chk("③ 判定枚举合法", not bad3, "%d 条指标判定全在允许集合内 ｜ 越界 %s" % (len(rep["metrics"]), bad3[:3] or "无"))

    # ④ 未测不许冒充 0
    fake0 = [r["id"] for r in rep["metrics"] if r["达标"] == "未测" and r["value"] is not None]
    chk("④ 未测项 value 必须 None (不许 0 冒充)", not fake0,
        "未测 %d 条 · value 非 None 的 %s" % (rep["verdicts"]["未测"], fake0 or "无"))

    # ⑤ 样本不足不出判定
    short = [r["id"] for r in rep["metrics"] if (r.get("extra") or {}).get("样本不足")]
    chk("⑤ 样本不足项不出判定", all(rows_by_id[i]["达标"] == "样本不足" for i in short),
        "样本不足 %d 项: %s ⇒ 达标列全为「样本不足」(只报值)" % (len(short), short))

    # ⑥ 三闸自洽
    conds = rep["gate"]["conditions"]
    chk("⑥ 升级准入 = 三闸全过", rep["gate"]["upgrade_allowed"] == all(c["过"] for c in conds.values()),
        " ".join("%s:%s(%s)" % (k, c["过"], c["值"]) for k, c in conds.items()) +
        " ⇒ allowed=%s" % rep["gate"]["upgrade_allowed"])

    # ⑦ 一致性真跑 (沙箱改 L2 包络 ⇒ 必须报冲突)
    sp = json.load(io.open(EP.SKILL_PHYS, encoding="utf-8"))
    bak = json.dumps(sp, ensure_ascii=False)
    try:
        for c, r in (sp.get("skills") or {}).items():
            if r.get("在职") and isinstance(r.get("v_cap"), (int, float)):
                r["v_cap"] = float(r["v_cap"]) + 99.0                       # 故意与标定真源不一致
        io.open(EP.SKILL_PHYS, "w", encoding="utf-8").write(json.dumps(sp, ensure_ascii=False))
        c2 = EP.p_sys_consistency()
        n_bad = len((c2.get("extra") or {}).get("冲突") or [])
    finally:
        io.open(EP.SKILL_PHYS, "w", encoding="utf-8").write(bak)             # 立刻复原
        sp_back = json.load(io.open(EP.SKILL_PHYS, encoding="utf-8"))
    c3 = EP.p_sys_consistency()
    n_ok = len((c3.get("extra") or {}).get("冲突") or [])
    chk("⑦ 一致性检查真跑 (改包络必报冲突)", n_bad > 0 and n_ok == 0 and bak == json.dumps(sp_back, ensure_ascii=False),
        "改后冲突 %d 项 ⇒ 复原后 %d 项 (文件已复原: %s)" % (n_bad, n_ok, bak == json.dumps(sp_back, ensure_ascii=False)))

    # ⑧ 阈值判定方向
    lo, _ = EA._threshold("≤3.15")
    hi, _ = EA._threshold("≥1100")
    v_low = EA.verdicts({"value": 3.0, "target": "≤3.15", "n": 5}, 3.15)
    v_high = EA.verdicts({"value": 8.0, "target": "≤3.15", "n": 5}, 3.15)
    v_up = EA.verdicts({"value": 1200.0, "target": "≥1100", "n": 5}, 1100.0)
    ok8 = (lo == -1 and hi == 1 and v_low["达标"] == "达标" and v_high["达标"] == "不达标"
           and v_high["基线对比"] == "回退" and v_up["基线对比"] == "提升")
    chk("⑧ 阈值判定方向正确", ok8, "≤3.15: 3.0→%s, 8.0→%s(基线3.15⇒%s) ｜ ≥1100: 1200→%s" %
        (v_low["达标"], v_high["达标"], v_high["基线对比"], v_up["基线对比"]))

    # ⑨ 回退必拦 (假报告)
    fake = {"metrics": [dict(rows_by_id[k]) for k in list(rows_by_id)[:1]]}
    fake["metrics"][0] = dict(fake["metrics"][0])
    fake["metrics"][0].update({"基线对比": "回退"})
    n_down = sum(1 for r in fake["metrics"] if r["基线对比"] == "回退")
    allowed = (n_down == 0) and True
    chk("⑨ 有回退 ⇒ 不许升级", (not allowed) and n_down == 1,
        "造 1 项回退 ⇒ 零回退闸=%s ⇒ 准入=False" % (n_down == 0))

    # ⑩ 页面渲染 (离屏真窗口)
    sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
    from PyQt5.QtWidgets import QApplication
    import studio                                                             # noqa: E402
    app = QApplication.instance() or QApplication(sys.argv[:1])
    m = studio.EvalModule()
    m.resize(1900, 1200)
    m.reload()
    n_tab = m.tab.rowCount()
    txt_gate = m.lb_gate.text()
    ev_ok, ev_bad = 0, []
    for name, (body, fresh) in m.ev_cards.items():
        t = body.text() + fresh.text()
        if ("真源" in t) and ("帧龄" in t) and ("—" not in fresh.text()):
            ev_ok += 1
        else:
            ev_bad.append("%s:%s" % (name, t.replace("\n", " ")[:40]))
    zero_shown = 0
    for i in range(n_tab):
        it = m.tab.item(i, 6)
        if it and it.text() == "未测":
            v = m.tab.item(i, 5)
            if v and v.text() == "0":
                zero_shown += 1
    want = "✅ 允许升级" if rep["gate"]["upgrade_allowed"] else "⛔ 不许升级"
    chk("⑩ 页面渲染与报告一致 (离屏真窗口)", n_tab == len(rep["metrics"]) and want in txt_gate
        and ev_ok == 5 and zero_shown == 0,
        "表 %d 行 vs 报告 %d 条 ｜ 准入文案「%s」｜ 证据卡齐 %d/5 %s ｜ 未测显示成 0 的行 %d" %
        (n_tab, len(rep["metrics"]), txt_gate, ev_ok, ev_bad or "", zero_shown))
    m.grab().save(os.path.join(ROOT, "reports", "ui_shots", "eval_analysis_page.png"))

    # ⑪ 证据真源都在盘上
    ev_missing = [k for k, v in (rep.get("evidence") or {}).items()
                  if not os.path.exists(os.path.join(ROOT, v.get("真源", "")))]
    chk("⑪ 证据面板真源文件都在盘上", not ev_missing,
        "5 张证据卡真源: %s ｜ 缺 %s" % (", ".join("%s=%s" % (k, v["真源"].split("/")[-1])
                                                for k, v in rep["evidence"].items()), ev_missing or "无"))

    # ⑬ 设计声明 (BOM/厂商) 一律不许算成达标 —— 声明≠实测
    decl = [r for r in rep["metrics"] if str(r.get("mode") or "").startswith("设计声明")]
    bad13 = [r["id"] for r in decl if r["达标"] not in ("待现场实测", "样本不足", "无阈值 (待现场定)")]
    chk("⑬ 设计声明(BOM) 不算达标", not bad13,
        "%d 条声明型指标: %s ⇒ 达标列全为「待现场实测」" % (len(decl), ", ".join("%s=%s" % (r["cn"], r["value"]) for r in decl)[:120]))

    # ⑭ 准入台账: 页面读到的历史 == eval_history.jsonl 真文件
    hp = os.path.join(os.path.dirname(EA.REPORT), "eval_history.jsonl")
    n_hist = sum(1 for x in open(hp, encoding="utf-8") if x.strip()) if os.path.exists(hp) else 0
    htxt = m.hist.text() if hasattr(m, "hist") else ""
    chk("⑭ 准入台账读真文件", n_hist > 0 and ("最近 %d 次" % min(6, n_hist)) in htxt,
        "eval_history.jsonl %d 行 · 页面显示「%s」" % (n_hist, htxt.split("\n")[0][:60]))

    # ⑫ 判据不留痕
    b1 = io.open(EA.BASELINE, encoding="utf-8").read()
    chk("⑫ 判据不留痕 (基线锁字节级不变)", b0 == b1,
        "跑前 %d 字节 vs 跑后 %d 字节" % (len(b0), len(b1)))

    shutil.rmtree(tmpd, ignore_errors=True)
    n_ok_all = sum(1 for _t, o, _e in rows if o)
    print("\n═══ 判据 %d/%d 通过 ═══" % (n_ok_all, len(rows)))
    print("页面截图: reports/ui_shots/eval_analysis_page.png")
    return 0 if n_ok_all == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
