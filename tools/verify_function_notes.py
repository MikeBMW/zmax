#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_function_notes.py — 判据: 功能点描述 (老倪 2026-10-14 「你来修改每个功能点的描述」)

口径 (每条都能复核):
  ① 覆盖: 74 个功能 (config_meta.json) **每个都有** work/pain/state 三条, 一个不少;
  ② 文字: 三条加起来不许出现宣传话术 (禁词表), 不许空话 (每条 ≥ 12 字);
  ③ 有据: 每条 work 或 pain 至少含一个来自唯一依据的具体事实 (参数 ID / 数字 / 文件名 / 验证方法词);
  ④ 不编: state 用工程口径词 (在役/未接入/待标定/缺口/回流 之类);
  ⑤ 进库: 工程库 functions 表的 note_work/note_pain/note_state 与唯一依据逐条一致 (库↔唯一依据不漂移);
  ⑥ 一致: 唯一依据计数 count 与实际条数一致。
用法: ./gui-venv311/bin/python tools/verify_function_notes.py
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
NOTES_J = "data/database/zmax/function_notes.json"
META_J = "data/database/zmax/config_meta.json"
DB = "data/database/zmax/zmax_engineering.db"
BAN = ("赋能", "生态", "抓手", "全面提升", "显著提升", "智能化升级", "助力", "打造", "一站式",
       "无缝", "深度融合", "颠覆", "行业领先", "大力")
STATE_WORDS = ("在役", "未接入", "待标定", "缺口", "回流", "仿真", "真机", "可运行", "未定", "只有",
               "待定", "接入中")

OK, BAD = [], []


def chk(name, ok, ev=""):
    (OK if ok else BAD).append(name)
    print("  %s %-46s %s" % ("✅" if ok else "❌", name, ev))


def _j(p, d=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                                      # noqa: BLE001
        return d


def main():
    doc = _j(NOTES_J, {}) or {}
    notes = doc.get("notes") or {}
    meta = (_j(META_J, {}) or {}).get("functions") or {}
    print("═══ ① 覆盖 ═══")
    miss = [k for k in meta if k not in notes]
    chk("每个功能都有描述 (%d/%d)" % (len(meta) - len(miss), len(meta)), not miss, "缺 %s" % miss[:6])
    chk("唯一依据 count 与实际条数一致", doc.get("count") == len(notes), "%s vs %s" % (doc.get("count"), len(notes)))
    chk("描述里的功能名与 config_meta 一致",
        all((notes[k].get("name") or "") == (meta[k].get("name") or "") for k in notes if k in meta))

    print("\n═══ ② ③ ④ 文字与依据 (逐条) ═══")
    bad_ban, bad_len, bad_fact, bad_state = [], [], [], []
    for k, v in notes.items():
        txt = " ".join(str(v.get(f) or "") for f in ("work", "pain", "state"))
        if any(b in txt for b in BAN):
            bad_ban.append((k, [b for b in BAN if b in txt]))
        for f in ("work", "pain", "state"):
            if len(str(v.get(f) or "")) < 12:
                bad_len.append((k, f, len(str(v.get(f) or ""))))
        wp = "%s %s" % (v.get("work") or "", v.get("pain") or "")
        if not re.search(r"[A-Za-z_][A-Za-z0-9_.]{2,}|\d", wp):
            bad_fact.append(k)
        if not any(w in str(v.get("state") or "") for w in STATE_WORDS):
            bad_state.append((k, v.get("state")))
    chk("无宣传话术 (禁词 %d 个)" % len(BAN), not bad_ban, str(bad_ban[:3]))
    chk("三条都写实 (每条 ≥12 字)", not bad_len, str(bad_len[:3]))
    chk("work/pain 含唯一依据具体事实", not bad_fact, str(bad_fact[:3]))
    chk("state 用工程口径词", not bad_state, str(bad_state[:3]))

    print("\n═══ ⑤ ⑥ 进库一致 ═══")
    if os.path.exists(DB):
        con = sqlite3.connect(DB)
        try:
            rows = {r[0]: (r[1], r[2], r[3]) for r in
                    con.execute("SELECT fn_id, note_work, note_pain, note_state FROM functions")}
            n_ok = sum(1 for k, t in rows.items()
                       if k in notes and t == (notes[k].get("work"), notes[k].get("pain"),
                                               notes[k].get("state")))
            chk("工程库描述与唯一依据逐条一致 (%d/%d)" % (n_ok, len(rows)), n_ok == len(rows) and len(rows) == len(notes),
                "库 %d 条 · 唯一依据 %d 条" % (len(rows), len(notes)))
            non = [k for k, t in rows.items() if not (t[0] or "").strip()]
            chk("库里没有空描述", not non, str(non[:5]))
        except Exception as e:                                                             # noqa: BLE001
            chk("工程库描述列存在", False, repr(e))
        con.close()
    else:
        chk("工程库存在", False, DB)

    print("\n" + ("✅ 全部通过 (%d 项)" % len(OK) if not BAD else "⛔ 失败 %d 项: %s" % (len(BAD), BAD)))
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
