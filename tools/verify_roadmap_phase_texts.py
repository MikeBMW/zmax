#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🗺✏️ Phase 卡文案 判据 (老倪 2026-10-15)

老倪原话: 「Phase 0 这个标签页, 这些黑灰字体的描述 原子技能...这些, 与 L2 层要对应上, 再次检查, 更新;
鼠标点开的区域, 要可以变成可编辑区域, 可以保存更新; Phase 1, Phase 2 3 4 同理可以可编辑修改」

判据 (每一条都能自己复核, 不看印象):
  ① 库行一一对应: PHASE_ROW_SHORT[sysN] 的键集合 == 工程库 functions 里该 system_id 的功能行集合
     (少了/多了都红 ⇒ 库里改行而代码不跟 = 判据红, 逼着同步)
  ② 卡片文本 = 库真值: Phase 0/1/3 的描述由 _phase_desc() 生成 → 里面的「功能 N」== 库 COUNT(*),
     「MCD x/y/z」== 库 mcd 表, 每组名都能在 PHASE_ROW_SHORT 里找到 (无自由发挥的组)
  ③ 弹窗库真值块: _phase_db_ref() 行数 == 库组数+1, 且每组 [N 项] 之和 == 功能总数
  ④ 编辑闭环**真跑**(离屏真类): 建 ProductRoadmapWidget → 取卡上文字 → save_roadmap_phase_text 写人工改写
     → 回读文件确认落盘 → _rebuild() → 卡上文字 == 改写文本 且出现「✏️ 人工改写」标记
     → clear_roadmap_phase_text → _rebuild() → 卡上文字**逐字回到库真值** → 文件里该键消失
  ⑤ 判据自己不留痕: 跑完 config/roadmap_phase_texts.json 必须回到跑之前的状态

用法: cd /home/ubuntu/zmax && ./gui-venv311/bin/python tools/verify_roadmap_phase_texts.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "database", "zmax", "zmax_engineering.db")
STORE = os.path.join(ROOT, "config", "roadmap_phase_texts.json")

rows: list[tuple[str, bool, str]] = []


def chk(tag, ok, ev):
    rows.append((tag, bool(ok), ev))
    print("  %s %s  %s" % ("✅" if ok else "❌", tag, ev))
    return bool(ok)


def db_rows(sid):
    con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    r = list(con.execute("SELECT row_name, COUNT(*) FROM functions WHERE system_id=? GROUP BY row_name", (sid,)))
    con.close()
    return r


def main() -> int:
    print("═══ Phase 卡文案 判据 (对应 L2/L3/L4 层 + 可编辑保存) ═══")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
    from PyQt5.QtWidgets import QApplication, QLabel
    import studio
    app = QApplication.instance() or QApplication(sys.argv[:1])

    # ① 库行一一对应
    for sid in ("sys0", "sys1", "sys2"):
        dbr = {r for r, _n in db_rows(sid)}
        tb = set(studio.PHASE_ROW_SHORT[sid])
        chk("① 库行一一对应 %s" % sid, dbr == tb,
            "库 %d 行 · 表 %d 条 · 缺 %s · 多 %s" % (len(dbr), len(tb), sorted(dbr - tb) or "无", sorted(tb - dbr) or "无"))

    # ② 卡片文本 = 库真值
    _F = studio._roadmap_facts()
    for sid, pid in (("sys0", "Phase 0"), ("sys1", "Phase 1"), ("sys2", "Phase 3")):
        mm = _F[sid]["mcd"]
        mcd = "/".join(p for p in (("M%d" % mm[0]) if mm[0] else "", ("C%d" % mm[1]) if mm[1] else "",
                                   ("D%d" % mm[2]) if mm[2] else "") if p) or "—"
        desc = studio._phase_desc(sid, _F[sid]["fn"], mcd)
        con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
        n_db = con.execute("SELECT COUNT(*) FROM functions WHERE system_id=?", (sid,)).fetchone()[0]
        mcd_db = con.execute("SELECT m,c,d FROM mcd WHERE scope='system' AND scope_id=?", (sid,)).fetchone()
        con.close()
        # 库里 MCD 是三元组, 卡上按"非零才显示"的同一口径比对 (sys1 库 0/0/8 ⇒ 卡上 D8)
        mcd_db_s = "/".join(p for p in (("M%d" % mcd_db[0]) if mcd_db[0] else "",
                                        ("C%d" % mcd_db[1]) if mcd_db[1] else "",
                                        ("D%d" % mcd_db[2]) if mcd_db[2] else "") if p) if mcd_db else "—"
        known = all(bool(studio.PHASE_ROW_SHORT[sid].get(r)) for r, _n in db_rows(sid))
        ok = (("功能 %d" % n_db) in desc) and (("MCD %s" % mcd) in desc) and (mcd == mcd_db_s) and known
        chk("② 卡文本=库真值 %s" % pid, bool(ok),
            "功能 %d(库 %d) · MCD %s(库 %s) · 组名对照 %s" % (_F[sid]["fn"], n_db, mcd, mcd_db_s,
                                                              "全有" if known else "有缺"))

    # ③ 弹窗库真值块
    for sid in ("sys0", "sys1", "sys2"):
        ref = studio._phase_db_ref(sid)
        lines = ref.split("\n")
        dbr = db_rows(sid)
        want = "(%s · %d 组 · %d 功能)" % (sid.upper(), len(dbr), sum(n for _r, n in dbr))
        ok = want in lines[0] and len(lines) == len(dbr) + 1
        chk("③ 弹窗库真值块 %s" % sid, ok, "%s ｜ 明细 %d 行 (+表头)" % (lines[0], len(lines) - 1))

    # ④ 编辑闭环真跑
    before = None
    if os.path.exists(STORE):
        before = open(STORE, encoding="utf-8").read()
    w = studio.ProductRoadmapWidget()
    w.resize(1400, 320); w.show(); app.processEvents()   # 真排版 ⇒ ⑦ 量到的是真实行位置 (非 0)
    cards = w.findChildren(studio.PhaseCardButton)
    chk("④a 建出 5 张 Phase 卡", len(cards) == 5, "实建 %d 张" % len(cards))

    def card_desc(pid):
        for c in w.findChildren(studio.PhaseCardButton):
            if c.phase_data["phase"] == pid:
                ls = [l.text() for l in c.findChildren(QLabel)]
                return "\n".join(ls)
        return ""

    base = card_desc("Phase 0")
    lib0 = studio._phase_desc("sys0", _F["sys0"]["fn"], "/".join(
        p for p in (("M%d" % _F["sys0"]["mcd"][0]), ("C%d" % _F["sys0"]["mcd"][1]), ("D%d" % _F["sys0"]["mcd"][2]))))
    # ⚠️ 老倪会自己改卡 (实测 2026-10-15 11:33~11:38 他连改 5 张) ⇒ 有人工改写覆盖时,
    #    "卡上文字"当然不等于库真值, 这是**正确**的: 判据改断「卡上文字 == 人工改写文本」,
    #    库真值本身仍由 ② 独立核对 (② 比的是代码生成串 vs 工程库, 不走卡片)。
    _ov0 = (studio.roadmap_text_overrides().get("Phase 0") or {})
    if _ov0.get("desc"):
        _w = _ov0["desc"].split("\n")[0]
        chk("④b 卡上文字 == 库生成文本", _w in base,
            "Phase 0 有人工改写覆盖 ⇒ 断「卡上 == 人工改写」: %s" % _w[:60])
    else:
        chk("④b 卡上文字 == 库生成文本", lib0.split("\n")[0] in base and lib0.split("\n")[1] in base,
            "卡上含: %s" % lib0.replace("\n", " ／ "))

    # ⚠️ 判据自测文本本身不许含被禁词 (否则是自测文本把'人工改写'带进卡上, 判据自己把自己弄红)
    mark = "✏️ 试改一行 (判据自测)"
    ok_save, msg_save = studio.save_roadmap_phase_text("Phase 0", {"desc": mark})
    on_disk = json.load(open(STORE, encoding="utf-8")) if os.path.exists(STORE) else {}
    chk("④c 保存落盘 + 回读一致", ok_save and (on_disk.get("phases", {}).get("Phase 0", {}).get("desc") == mark),
        msg_save)

    w._rebuild()
    after = card_desc("Phase 0")
    # 老倪 2026-10-15: 「产品迭代的 phase 标签页, 不要显示 人工改写 点开可改 可恢复真值 这几个字, 太显眼」
    #   ⇒ 判据断: 卡上有 ✏️ 标记 + 改写文本, 且**那几个字一个都不许再出现** (写回去就立刻红)。
    _banned = [w for w in ("人工改写", "点开可改", "可恢复", "恢复库真值") if w in after]
    chk("④d 卡当场刷新成改写文本 + ✏️ 标记 (不打那行字)",
        mark in after and "✏️" in after and not _banned,
        "卡上文字: %s ｜ 违规词 %s" % (after.replace("\n", " ／ ")[:110], _banned))

    ok_clr, msg_clr = studio.clear_roadmap_phase_text("Phase 0")
    w._rebuild()
    back = card_desc("Phase 0")
    disk_now = json.load(open(STORE, encoding="utf-8")) if os.path.exists(STORE) else {}
    chk("④e 恢复库真值 (文字逐字回退 + 覆盖已删)",
        ok_clr and "Phase 0" not in (disk_now.get("phases") or {})
        and lib0.split("\n")[0] in back and lib0.split("\n")[1] in back and mark not in back,
        "%s ｜ 卡上回到: %s" % (msg_clr, back.replace("\n", " ／ ")[:80]))

    # ⑤ 判据不留痕: 现场快照 → 跑完原地还原 (判据不许把自己写的东西留在真源里)
    #    注意: 老倪自己会改卡(人工改写覆盖是他写的), 所以"不留痕"= 与跑前**逐字节一致**
    #    且 phases 集合与跑前完全相同 (不能多、也不能少) —— 不是"phases 必须为空"。
    _before_phases = set((json.loads(before).get("phases") or {})) if before else set()
    if before is None:
        if os.path.exists(STORE):
            os.remove(STORE)
    else:
        with open(STORE, "w", encoding="utf-8") as _f:
            _f.write(before)
    now = open(STORE, encoding="utf-8").read() if os.path.exists(STORE) else None
    resid = set((json.loads(now).get("phases") or {}) if now else {})
    chk("⑤ 判据不留痕 (现场快照逐字节还原, 你的改写一条不少)",
        now == before and resid == _before_phases,
        "store 与跑前逐字节一致=%s · phases 跑前 %s → 跑后 %s" % (now == before, sorted(_before_phases), sorted(resid)))

    # ⑥ 主指标(KPI)口径 + 位置一致 (老倪 2026-10-15: 「右下角主指标 … phase 0 速度反馈延迟 ≤ 10ms;
    #    phase 1 对位残差 ≤ 0.5mm; phase2 成功率 ≥ 97%; phase 3 稳定恢复时间 ≤ 1s; 字体排列/位置要一致, UI要优美整齐」)
    want_kpi = {"Phase 0": "速度反馈延迟 ≤ 10ms", "Phase 1": "对位残差 ≤ 0.5mm",
                "Phase 2": "成功率 ≥ 97%", "Phase 3": "稳定恢复时间 ≤ 1s"}
    # 判据口径: 默认文本必须 == 老倪指定; 但**他手改过的**以他写的为准 (人写的优先级高于默认),
    # 只断「卡上文字 == 人工改写文本」并在明细里标注哪些是人工改写。
    _ovs = studio.roadmap_text_overrides()
    got = {}
    for c in w.findChildren(studio.PhaseCardButton):
        got[c.phase_data["phase"]] = c.phase_data["kpi"]
    bad_kpi, human_kpi = {}, {}
    for k, v in want_kpi.items():
        _o = (_ovs.get(k) or {}).get("kpi")
        if _o:
            if got.get(k) != _o:
                bad_kpi[k] = ("人工改写 %s" % _o, got.get(k))
            else:
                human_kpi[k] = _o
        elif got.get(k) != v:
            bad_kpi[k] = (v, got.get(k))
    chk("⑥ 主指标文本 (默认=老倪指定 / 已改写=以改写为准)", not bad_kpi,
        " ｜ ".join("%s: %s" % (k, v) for k, v in want_kpi.items())
        + (" ｜ ✏️人工改写: %s" % human_kpi if human_kpi else "")
        + (" ｜ 偏差 %s" % bad_kpi if bad_kpi else ""))

    geo = {}
    for c in w.findChildren(studio.PhaseCardButton):
        kl = [l for l in c.findChildren(QLabel) if l.text() == c.phase_data["kpi"]]
        if kl:
            g = kl[0].geometry()
            geo[c.phase_data["phase"]] = (g.y(), g.y() + g.height(), kl[0].font().pointSize(), c.height())
    top = {v[0] for v in geo.values()}
    bot = {v[1] for v in geo.values()}
    fsz = {v[2] for v in geo.values()}
    hgt = {v[3] for v in geo.values()}
    chk("⑦ KPI 位置/字号/卡高一致", len(top) == 1 and len(bot) == 1 and len(fsz) == 1 and len(hgt) == 1,
        "上沿 %s · 下沿 %s · 字号 %s · 卡高 %s" % (sorted(top), sorted(bot), sorted(fsz), sorted(hgt)))

    # ⑧ 五条主指标都必须**单行放完** (老倪: 字体排列/位置要一致 ⇒ 谁折成两行, 那一行就比别的卡多一行、看着不齐)。
    #    按实机宽度量: 真窗 1400 − 侧栏/边距 ⇒ roadmap 实宽 1108 (实测值), 重新排版后逐条量文本宽 vs 标签宽。
    from PyQt5.QtGui import QFontMetrics
    w.resize(1108, 320); app.processEvents()
    over, over_human = [], []
    for c in w.findChildren(studio.PhaseCardButton):
        kl = [l for l in c.findChildren(QLabel) if l.text() == c.phase_data["kpi"]]
        if kl:
            need = QFontMetrics(kl[0].font()).horizontalAdvance(kl[0].text())
            if need > kl[0].width():
                # 老倪自己写长的 ⇒ 折行是他的选择, 只提醒不算失败; 默认文本折行才是 UI 缺陷
                _t = (c.phase_data["phase"], need, kl[0].width())
                ((over_human if (_ovs.get(c.phase_data["phase"]) or {}).get("kpi") else over)).append(_t)
    chk("⑧ 五条主指标单行放得下", not over,
        (("全部单行 (卡内宽 %dpx)" % 176) if not over else "超宽折行: %s" % over)
        + (" ｜ ✏️人工改写超宽(提醒, 非失败): %s" % over_human if over_human else ""))

    nbad = [r for r in rows if not r[1]]
    print("─── %d/%d %s" % (len(rows) - len(nbad), len(rows), "全绿 PASS" if not nbad else "FAIL"))
    return 0 if not nbad else 1


if __name__ == "__main__":
    sys.exit(main())
