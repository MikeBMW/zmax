#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔌🧩 评估分析页 · 迭代路线图区块「插拔/摆盘 场景 × Phase 0→4 全流程迭代」判据 (老倪 2026-10-15)

老倪原话: 「在评估分析页的迭代路线图面板里加上「插拔/摆盘 场景 × Phase 0→4 全流程迭代元任务组合」视图
          (组合迭代 / 迭代验证 / 对比分析), 读 zmax_data/eval/scene_phase_iteration.json, 离屏截图取证」

判据 (每条都能自己复核, 不看印象; 真起控件 + 真读真源比对):
  ① 真内嵌: 真起 studio.EvalModule → 评估分析页里真有 IterationRoadmapPanel, 且第 4 个标签页 = ScenePhaseIterationView
  ② 默认场景 = 当前激活任务对应场景 (config/ss_task_binding.json 的 active_task), 且两个场景按钮互斥选中态一致
  ③ 场景切换真生效: 切 TRAY ⇒ 表内容 == TRAY 真源 (逐阶段逐字段); 切回 FW 同理
  ④ 三子视图读数 == 真源 JSON 逐条核对 (combo / 配置核验 / 实测判定 / 矩阵 / 达标率 / 组合增量 / 与基线)
  ⑤ 颜色语义: 达标=绿 · 未达标=红 · 未测=灰 (抽样真源里出现的判定)
  ⑥ 缺失真源 ⇒ 三个子视图都显「尚未生成」且 0 行, 不崩 (绝不假 0)
  ⑦ 坏真源 (非法 JSON) ⇒ 显真实读取错误, 不崩
  ⑧ 折叠行真交互: expand_all ⇒ 明细行可见 & 行高够高; 再点收回 ⇒ 隐藏
  ⑨ 重跑按钮: 真 subprocess 调 tools/scene_phase_iteration.py, 界面状态 == **真实退出码**
  ⑩ 重跑失败路径: 工具不存在 ⇒ 界面显「工具不存在」真实原因 (不静默)
  ⑪ 复制 / 导出: 当前视图文本 / Markdown (含场景迭代段) / CSV (tab3 出 scene_phase_iteration_*.csv)
  ⑫ 不留痕: 判据自己不改真源 (除 ⑨ 由工具重新生成真源; 前后**语义字段**必须一致)

用法: cd /home/ubuntu/zmax && ./gui-venv311/bin/python tools/verify_scene_phase_iteration_panel.py
      [--shot-dir docs/data_snapshots/<dir>]   # 顺手出离屏真渲染截图
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JSON = os.path.join(ROOT, "zmax_data", "eval", "scene_phase_iteration.json")
BIND = os.path.join(ROOT, "config", "ss_task_binding.json")
TOOL = os.path.join(ROOT, "tools", "scene_phase_iteration.py")
SCENE_OF_TASK = {"TASK-01-FW": "FW", "TASK-06-TRAY": "TRAY"}

rows: list = []


def chk(tag, ok, ev):
    rows.append((tag, bool(ok), ev))
    print("  %s %s  %s" % ("✅" if ok else "❌", tag, ev))
    return bool(ok)


def jload(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]


VOLATILE = ("ts", "age_s")        # 每次重跑必变的: 生成时间 + 帧龄 (证据源到现在的秒数, 随时钟走)


def sem(obj):
    """语义指纹: 去掉 ts / age_s (volatile) 后的结构化内容 — 其余字段必须逐字一致。"""
    def strip(o):
        if isinstance(o, dict):
            return {k: strip(v) for k, v in o.items() if k not in VOLATILE}
        if isinstance(o, list):
            return [strip(x) for x in o]
        return o
    return hashlib.sha256(json.dumps(strip(obj), ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def cell(t, r, c):
    it = t.item(r, c)
    return it.text() if it is not None else ""


def main(argv) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--shot-dir", default=None, help="离屏截图输出目录 (默认不出图)")
    ap.add_argument("--skip-rerun", action="store_true", help="跳过 ⑨ 真重跑 (省时间)")
    args = ap.parse_args(argv)

    print("═══ 🔌🧩 场景迭代面板 判据 (插拔/摆盘 × Phase 0→4) ═══")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv[:1])

    import studio
    import iteration_roadmap_panel as irm

    if not chk("⓪ 真源存在", os.path.exists(JSON), "真源 %s" % os.path.relpath(JSON, ROOT)):
        return 1
    src = jload(JSON)
    sha0, sem0 = sha(JSON), sem(src)
    scen = {s.get("scene"): s for s in (src.get("scenes") or [])}

    # ── ① 真内嵌评估分析页 ──
    ev = studio.EvalModule()
    ev.resize(1500, 1000)
    ev.show()
    app.processEvents()
    panel = getattr(ev, "irm_panel", None)
    chk("① 评估分析页内嵌迭代路线图面板", panel is not None,
        "EvalModule.irm_panel = %s" % type(panel).__name__)
    sv = getattr(panel, "scene_view", None)
    ok1b = sv is not None and type(sv).__name__ == "ScenePhaseIterationView"
    chk("①b 第 4 个标签页 = 场景迭代控件", ok1b and panel.tabs.count() == 4
        and "场景迭代" in panel.tabs.tabText(3),
        "tabs=%d 第4页='%s' 控件=%s" % (panel.tabs.count(), panel.tabs.tabText(panel.tabs.count() - 1),
                                        type(sv).__name__ if sv is not None else "无"))

    # ── ② 默认场景 = 激活任务对应场景 ──
    act = (jload(BIND).get("active_task") or "").strip() if os.path.exists(BIND) else ""
    want = SCENE_OF_TASK.get(act, "")
    got = str(sv.scene).upper()
    chk("② 默认场景 == 激活任务对应场景", (want == "" ) or (got == want),
        "active_task=%s ⇒ 期望 %s · 界面 %s" % (act or "—", want or "—(映射未知)", got))
    chk("②b 场景按钮互斥选中态一致",
        all(b.isChecked() == (k == got) for k, b in sv.btns.items()),
        "选中: %s" % [k for k, b in sv.btns.items() if b.isChecked()])

    # ── ③④ 两个场景 × 三子视图 逐条对真源 ──
    for key in ("FW", "TRAY"):
        s = scen.get(key)
        if not s:
            chk("③ 场景 %s 在真源里" % key, False, "真源 scenes 里没有 %s" % key)
            continue
        sv.set_scene(key)
        app.processEvents()
        phs = sorted(s.get("phases") or [], key=lambda p: p.get("phase"))
        # (a) 组合迭代
        nrow = sv.ctab.rowCount()
        chk("④%s(a) 组合迭代 行数 = 阶段数×2 (主行+折叠明细)" % key, nrow == len(phs) * 2,
            "界面 %d 行 · 真源 %d 阶段" % (nrow, len(phs)))
        bad = []
        prev = None
        for i, p in enumerate(phs):
            r = i * 2
            cb = p.get("combo") or {}
            tot = cb.get("total")
            delta = ("%+d" % (tot - prev)) if (isinstance(tot, (int, float)) and isinstance(prev, (int, float))) else None
            exp = [p.get("phase") or "", p.get("name") or "—", str(len((p.get("verification") or {}).get("metrics") or [])),
                   str(tot), ("— (首阶段)" if prev is None else (delta or "尚未生成"))]
            g = [cell(sv.ctab, r, c) for c in (0, 1, 2, 4, 5)]
            if g[:2] != exp[:2] or g[3] != exp[3] or g[4] != exp[4]:
                bad.append("%s: 界面 %s ≠ 真源 %s" % (p.get("phase"), g, exp))
            if isinstance(tot, (int, float)):
                prev = tot
        chk("④%s(b) 组合迭代 阶段/主题/总数量/增量 == 真源" % key, not bad, bad[0] if bad else
            "5 阶段逐行一致 (carried/added/upgraded 由 _combo_short 现算)")
        # (b) 迭代验证
        nk = sv.ktab.rowCount()
        chk("④%s(c) 配置核验行数 = 阶段数" % key, nk == len(phs), "界面 %d · 真源 %d" % (nk, len(phs)))
        bad2 = []
        for i, p in enumerate(phs):
            cc = p.get("config_check") or {}
            run = p.get("run") or {}
            g = [cell(sv.ktab, i, 0), cell(sv.ktab, i, 1), cell(sv.ktab, i, 2), cell(sv.ktab, i, 3)]
            e = [p.get("phase") or "", str(cc.get("enabled_nodes")), str(cc.get("combo_mapped")), str(cc.get("coverage"))]
            if g != e:
                bad2.append("%s: %s ≠ %s" % (p.get("phase"), g, e))
            if str(run.get("mode") or "") not in cell(sv.ktab, i, 7):
                bad2.append("%s: run.mode 格缺 %s" % (p.get("phase"), run.get("mode")))
            if ("可作改配置依据" in cell(sv.ktab, i, 6)) == (cc.get("pass") is not True):
                bad2.append("%s: 可作改配置依据口径与 pass=%s 不符" % (p.get("phase"), cc.get("pass")))
        chk("④%s(d) 配置核验 (启用节点/组合映射/coverage/run.mode/能否作依据) == 真源" % key, not bad2,
            bad2[0] if bad2 else "5 阶段逐行一致")
        mets = [m for p in phs for m in ((p.get("verification") or {}).get("metrics") or [])]
        chk("④%s(e) 迭代验证行数 == 真源指标条数" % key, sv.vtab2.rowCount() == len(mets),
            "界面 %d · 真源 %d" % (sv.vtab2.rowCount(), len(mets)))
        cnt_src = {"达标": 0, "未达标": 0, "未测": 0, "样本不足": 0}
        for m in mets:
            if m.get("verdict") in cnt_src:
                cnt_src[m["verdict"]] += 1
        cnt_ui = {"达标": 0, "未达标": 0, "未测": 0, "样本不足": 0}
        for r in range(sv.vtab2.rowCount()):
            v = cell(sv.vtab2, r, 5)
            if v in cnt_ui:
                cnt_ui[v] += 1
        chk("④%s(f) 判定计数 界面 == 真源" % key, cnt_src == cnt_ui, "真源 %s · 界面 %s" % (cnt_src, cnt_ui))
        # (c) 对比分析
        cm = src.get("comparison") or {}
        chk("④%s(g) 场景×阶段矩阵行数 == 真源" % key, sv.mtab.rowCount() == len(cm.get("matrix") or []),
            "界面 %d · 真源 %d" % (sv.mtab.rowCount(), len(cm.get("matrix") or [])))
        m0 = (cm.get("matrix") or [{}])[0]
        g0 = [cell(sv.mtab, 0, 0), cell(sv.mtab, 0, 4), cell(sv.mtab, 0, 9), cell(sv.mtab, 0, 13)]
        e0 = [m0.get("name"), str(irm._fnum((m0.get("FW") or {}).get("p1"))),
              str(irm._fnum((m0.get("TRAY") or {}).get("p1"))), m0.get("verdict")]
        chk("④%s(h) 矩阵首行 FW p1/TRAY p1/判定 == 真源" % key, g0 == e0, "界面 %s · 真源 %s" % (g0, e0))
        pr = (cm.get("pass_rate") or {}).get(key) or []
        bad3 = []
        for i in range(sv.ptab.rowCount()):
            if i >= len(pr):
                break
            if cell(sv.ptab, i, 0) != pr[i].get("phase"):
                bad3.append("第%d行阶段 %s ≠ %s" % (i, cell(sv.ptab, i, 0), pr[i].get("phase")))
        chk("④%s(i) 逐阶段达标率阶段列 == 真源" % key, not bad3, bad3[0] if bad3 else
            "界面 %d 行 (达标/总数/达标率由 pass·total 现算)" % sv.ptab.rowCount())
        cd = (cm.get("combo_delta") or {}).get(key) or {}
        rr = {"FW": 0, "TRAY": 1}[key]
        chk("④%s(j) 组合增量 (added/upgraded) == 真源" % key,
            cell(sv.dtab, rr, 1) == str(cd.get("added")) and cell(sv.dtab, rr, 2) == str(cd.get("upgraded")),
            "界面 added=%s upgraded=%s · 真源 %s/%s"
            % (cell(sv.dtab, rr, 1), cell(sv.dtab, rr, 2), cd.get("added"), cd.get("upgraded")))
        vb = (cm.get("vs_baseline") or {}).get(key) or {}
        chk("④%s(k) 与基线 (提升/持平/回退) == 真源" % key,
            [cell(sv.btab2, rr, c) for c in (1, 2, 3)] == [str(vb.get("improved")), str(vb.get("flat")),
                                                           str(vb.get("regressed"))],
            "界面 %s · 真源 %s" % ([cell(sv.btab2, rr, c) for c in (1, 2, 3)],
                                   [vb.get("improved"), vb.get("flat"), vb.get("regressed")]))
        chk("④%s(l) 头部标了生成时间 + 基线版本" % key,
            irm._ts_str((src.get("meta") or {}).get("ts")) in sv.lb_scene.text()
            and str((src.get("meta") or {}).get("baseline")) in sv.lb_scene.text(),
            sv.lb_scene.text()[:150])

    # ── ⑤ 颜色语义 ──
    seen = {}
    for r in range(sv.vtab2.rowCount()):
        v = cell(sv.vtab2, r, 5)
        it = sv.vtab2.item(r, 5)
        if it is not None and v not in seen:
            seen[v] = it.foreground().color().name()
    expcol = {"达标": irm.C_GREEN, "未达标": irm.C_RED, "未测": irm.C_GRAY, "样本不足": irm.C_GRAY}
    badc = ["%s=%s(应 %s)" % (k, v, expcol[k]) for k, v in seen.items() if k in expcol and v != expcol[k]]
    chk("⑤ 判定色 (达标绿/未达标红/未测·样本不足灰)", not badc,
        "抽样 %s%s" % (seen, ("  ❌ " + "; ".join(badc)) if badc else ""))

    # ── ⑧ 折叠行真交互 ──
    sv.set_scene("FW")
    sv.expand_all()
    app.processEvents()
    det = sv._det_of_main.get(0)
    h = sv.ctab.rowHeight(det)
    chk("⑧ 展开明细行真可见且高度足够", det is not None and not sv.ctab.isRowHidden(det) and h >= 36,
        "明细行 %s 可见=%s 行高=%dpx" % (det, (not sv.ctab.isRowHidden(det)) if det is not None else "—", h))
    sv._on_combo_click(0, 3)
    app.processEvents()
    chk("⑧b 再点收回 ⇒ 明细行隐藏", sv.ctab.isRowHidden(det),
        "明细行 %s 隐藏=%s · 摘要 '%s'" % (det, sv.ctab.isRowHidden(det), cell(sv.ctab, 0, 3)))

    # ── ⑪ 复制 / 导出 ──
    txt = sv._view_text()
    chk("⑪ 复制当前视图文本有内容", len(txt) > 200 and "Phase 0" in txt, "%d 字符" % len(txt))
    md = panel._md()
    chk("⑪b 面板 Markdown 含场景迭代段", "## 🔌🧩 场景迭代" in md and "#### 组合迭代" in md
        and "#### ① 场景 × 阶段矩阵" in md, "%d 字符" % len(md))
    panel.tabs.setCurrentIndex(3)                       # tab3 ⇒ 导出的是场景迭代 CSV (当前子视图)
    sv.sub.setCurrentIndex(0)
    sv._render_sub()
    app.processEvents()
    csvf = panel.export_csv()
    first = open(csvf, encoding="utf-8").readline().strip()
    chk("⑪c tab3 导出 CSV = 场景迭代表头", os.path.basename(csvf).startswith("scene_phase_iteration")
        and first.startswith("场景,阶段"), "%s ｜ %s" % (os.path.basename(csvf), first[:90]))
    # ── ⑥ 缺失真源 ──
    keep = sv.JSON
    sv.JSON = os.path.join(ROOT, "zmax_data", "eval", "__no_such_scene_iter__.json")
    sv.reload()
    app.processEvents()
    ok6 = (sv.data is None and sv.read_err == "尚未生成" and "尚未生成" in sv.lb_status.text()
           and sv.ctab.rowCount() == 0 and sv.ktab.rowCount() == 0 and sv.vtab2.rowCount() == 0
           and sv.mtab.rowCount() == 0 and "尚未生成" in sv.lb_combo_hint.text())
    chk("⑥ 缺失真源 ⇒ 尚未生成 + 0 行, 不崩", ok6, "read_err=%s ｜ 横幅: %s" % (sv.read_err, sv.lb_status.text()[:110]))

    # ── ⑦ 坏真源 ──
    badp = os.path.join(ROOT, "zmax_data", "eval", "__bad_scene_iter__.json")
    try:
        with open(badp, "w", encoding="utf-8") as fh:
            fh.write("{ 这不是 JSON")
        sv.JSON = badp
        sv.reload()
        app.processEvents()
        chk("⑦ 坏真源 ⇒ 显真实读取错误, 不崩", "读取失败" in sv.read_err and sv.data is None,
            "read_err=%s ｜ 横幅: %s" % (sv.read_err[:80], sv.lb_status.text()[:110]))
    finally:
        try:
            os.remove(badp)
        except OSError:
            pass
    sv.JSON = keep
    sv.reload()

    # ── ⑩ 重跑失败路径 (工具真退出码 ≠ 0) ──
    fake = os.path.join(ROOT, "tools", "__fake_scene_tool__.py")
    keep_tool = irm.SCENE_TOOL
    try:
        with open(fake, "w", encoding="utf-8") as fh:
            fh.write("import sys\nsys.stderr.write('boom: 采集口径不可达\\n')\nsys.exit(3)\n")
        irm.SCENE_TOOL = fake
        rc10 = sv.rerun()
        app.processEvents()
        chk("⑩ 重跑失败 ⇒ 显**真实退出码 + stderr**, 不静默",
            rc10 == 3 and "退出码 3" in sv.lb_status.text() and "boom" in sv.lb_status.text(),
            "真实 rc=%s ｜ 界面: %s" % (rc10, sv.lb_status.text()[:130]))
    finally:
        irm.SCENE_TOOL = keep_tool
        try:
            os.remove(fake)
        except OSError:
            pass
    # ⑩b 工具不存在
    irm.SCENE_TOOL = os.path.join(ROOT, "tools", "__no_such_scene_tool__.py")
    rc10b = sv.rerun()
    app.processEvents()
    chk("⑩b 工具不存在 ⇒ 显「工具不存在」真实原因", rc10b == "NO_TOOL"
        and "工具不存在" in sv.lb_status.text(), "rc=%s ｜ %s" % (rc10b, sv.lb_status.text()[:120]))
    irm.SCENE_TOOL = keep_tool
    sv.reload()

    # ── ⑨ 真重跑 (subprocess, 界面状态 == 真实退出码) ──
    if not args.skip_rerun:
        rc = sv.rerun()
        app.processEvents()
        txt9 = sv.lb_status.text()
        ok9 = (str(rc) in txt9) and ((rc == 0 and "退出码 0" in txt9) or (rc != 0 and "失败" in txt9))
        chk("⑨ 重跑按钮: 界面状态 == 真实退出码", ok9, "真实 rc=%s ｜ 界面: %s" % (rc, txt9[:130]))
        if os.path.exists(JSON):
            sem1 = sem(jload(JSON))
            chk("⑫ 重跑只刷新 ts/age_s (帧龄), 其余语义字段逐一不变", sem1 == sem0,
                "语义指纹 (剔除 ts·age_s) 跑前 %s ⇒ 跑后 %s  (字节 sha %s ⇒ %s ⇒ 变的只有生成时间与帧龄)"
                % (sem0, sem1, sha0, sha(JSON)))

    # ── 截图 (离屏真渲染) ──
    if args.shot_dir:
        d = args.shot_dir if os.path.isabs(args.shot_dir) else os.path.join(ROOT, args.shot_dir)
        os.makedirs(d, exist_ok=True)
        shots = [("00_评估分析页整页_场景迭代页签", 3, 0, "FW", 0, False, "ev"),
                 ("01_评估分析页_迭代路线图区块(场景迭代页签)", 3, 0, "FW", 0, False, "panel"),
                 ("02_组合迭代_FW_展开", 3, 0, "FW", 0, True, "sv"),
                 ("03_组合迭代_TRAY", 3, 0, "TRAY", 0, False, "sv"),
                 ("04_迭代验证_FW", 3, 1, "FW", 0, False, "sv"),
                 ("05_迭代验证_TRAY", 3, 1, "TRAY", 0, False, "sv"),
                 ("06_对比分析_并列FW+TRAY", 3, 2, "FW", 0, False, "sv"),
                 ("07_对比分析_只看FW", 3, 2, "FW", 1, False, "sv")]
        for name, tab, subtab, scene, mode, expand, target in shots:
            panel.tabs.setCurrentIndex(tab)
            sv.set_scene(scene)
            sv.sub.setCurrentIndex(subtab)
            sv._render_sub()
            sv.cmode.setCurrentIndex(mode)
            if expand:
                sv.expand_all()
            app.processEvents()
            w = {"ev": ev, "panel": panel, "sv": sv}[target]
            p = os.path.join(d, "%s.png" % name)
            w.grab().save(p)
            print("  📷 %s" % os.path.relpath(p, ROOT))
        # 缺失真源用例也留一张
        sv.JSON = os.path.join(ROOT, "zmax_data", "eval", "__no_such_scene_iter__.json")
        sv.reload()
        sv.sub.setCurrentIndex(1)
        sv._render_sub()
        app.processEvents()
        p = os.path.join(d, "08_真源缺失_尚未生成.png")
        sv.grab().save(p)
        print("  📷 %s" % os.path.relpath(p, ROOT))
        sv.JSON = keep
        sv.reload()
        # FW 组合迭代折叠态 (清掉展开记忆 ⇒ 真折叠, 不是"记忆恢复")
        exp = getattr(sv, "_expanded", None)
        if exp is not None:
            exp.clear()
        sv.sub.setCurrentIndex(0)
        sv.set_scene("FW")
        sv._render_sub()
        app.processEvents()
        p = os.path.join(d, "09_组合迭代_FW_折叠(默认).png")
        sv.grab().save(p)
        print("  📷 %s" % os.path.relpath(p, ROOT))
        # 重跑失败横幅 (真实退出码 3 + 真 stderr)
        fake = os.path.join(ROOT, "tools", "__fake_scene_tool__.py")
        keep_tool2 = irm.SCENE_TOOL
        try:
            with open(fake, "w", encoding="utf-8") as fh:
                fh.write("import sys\nsys.stderr.write('boom: 采集口径不可达\\n')\nsys.exit(3)\n")
            irm.SCENE_TOOL = fake
            sv.rerun()
            app.processEvents()
            p = os.path.join(d, "10_重跑失败_真实退出码3.png")
            sv.grab().save(p)
            print("  📷 %s" % os.path.relpath(p, ROOT))
        finally:
            irm.SCENE_TOOL = keep_tool2
            try:
                os.remove(fake)
            except OSError:
                pass
            sv.reload()

    npass = sum(1 for _t, ok, _e in rows if ok)
    print("\n═══ 结果: %d/%d PASS ═══" % (npass, len(rows)))
    for t, ok, e in rows:
        if not ok:
            print("  ❌ %s  %s" % (t, e))
    return 0 if npass == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
