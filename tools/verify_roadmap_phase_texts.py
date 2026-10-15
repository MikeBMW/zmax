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
    chk("④b 卡上文字 == 库生成文本", lib0.split("\n")[0] in base and lib0.split("\n")[1] in base,
        "卡上含: %s" % lib0.replace("\n", " ／ "))

    mark = "✏️ 人工改写 · 试改一行 (判据自测)"
    ok_save, msg_save = studio.save_roadmap_phase_text("Phase 0", {"desc": mark})
    on_disk = json.load(open(STORE, encoding="utf-8")) if os.path.exists(STORE) else {}
    chk("④c 保存落盘 + 回读一致", ok_save and (on_disk.get("phases", {}).get("Phase 0", {}).get("desc") == mark),
        msg_save)

    w._rebuild()
    after = card_desc("Phase 0")
    chk("④d 卡当场刷新成改写文本 + 人工改写标记",
        mark in after and "人工改写" in after and "库真值" not in after.replace("恢复库真值", ""),
        "卡上文字: %s" % after.replace("\n", " ／ ")[:110])

    ok_clr, msg_clr = studio.clear_roadmap_phase_text("Phase 0")
    w._rebuild()
    back = card_desc("Phase 0")
    disk_now = json.load(open(STORE, encoding="utf-8")) if os.path.exists(STORE) else {}
    chk("④e 恢复库真值 (文字逐字回退 + 覆盖已删)",
        ok_clr and "Phase 0" not in (disk_now.get("phases") or {})
        and lib0.split("\n")[0] in back and lib0.split("\n")[1] in back and mark not in back,
        "%s ｜ 卡上回到: %s" % (msg_clr, back.replace("\n", " ／ ")[:80]))

    # ⑤ 判据不留痕: 现场快照 → 跑完原地还原 (判据不许把自己写的东西留在真源里)
    if before is None:
        if os.path.exists(STORE):
            os.remove(STORE)
    else:
        with open(STORE, "w", encoding="utf-8") as _f:
            _f.write(before)
    now = open(STORE, encoding="utf-8").read() if os.path.exists(STORE) else None
    resid = (json.loads(now).get("phases") or {}) if now else {}
    chk("⑤ 判据不留痕 (现场快照已还原, 无残留覆盖)", now == before and not resid,
        "store 内容与跑前逐字节一致=%s · 残留 phases=%s" % (now == before, list(resid) or "无"))

    # ⑥ 主指标(KPI)口径 + 位置一致 (老倪 2026-10-15: 「右下角主指标 … phase 0 速度反馈延迟 ≤ 10ms;
    #    phase 1 对位残差 ≤ 0.5mm; phase2 成功率 ≥ 97%; phase 3 稳定恢复时间 ≤ 1s; 字体排列/位置要一致, UI要优美整齐」)
    want_kpi = {"Phase 0": "速度反馈延迟 ≤ 10ms", "Phase 1": "对位残差 ≤ 0.5mm",
                "Phase 2": "成功率 ≥ 97%", "Phase 3": "稳定恢复时间 ≤ 1s"}
    got = {}
    for c in w.findChildren(studio.PhaseCardButton):
        got[c.phase_data["phase"]] = c.phase_data["kpi"]
    bad_kpi = {k: (v, got.get(k)) for k, v in want_kpi.items() if got.get(k) != v}
    chk("⑥ 主指标文本 == 老倪指定", not bad_kpi,
        " ｜ ".join("%s: %s" % (k, v) for k, v in want_kpi.items()) + (" ｜ 偏差 %s" % bad_kpi if bad_kpi else ""))

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
    over = []
    for c in w.findChildren(studio.PhaseCardButton):
        kl = [l for l in c.findChildren(QLabel) if l.text() == c.phase_data["kpi"]]
        if kl:
            need = QFontMetrics(kl[0].font()).horizontalAdvance(kl[0].text())
            if need > kl[0].width():
                over.append((c.phase_data["phase"], need, kl[0].width()))
    chk("⑧ 五条主指标单行放得下", not over,
        ("全部单行 (卡内宽 %dpx)" % 176) if not over else "超宽折行: %s" % over)

    nbad = [r for r in rows if not r[1]]
    print("─── %d/%d %s" % (len(rows) - len(nbad), len(rows), "全绿 PASS" if not nbad else "FAIL"))
    return 0 if not nbad else 1


if __name__ == "__main__":
    sys.exit(main())
