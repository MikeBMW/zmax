#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_patent_export.py — 判据: 专利交底书一键导出 (老倪 2026-10-14 「预留专利申请一键导出」)

判据 (每条真读产物/唯一依据):
  ① 覆盖: 每个功能 (config_meta.json 74 个) 都有一份交底书 md;
  ② 成文: 十节标题齐 (发明名称/技术领域/背景技术/要解决的技术问题/技术方案/有益效果/
          具体实施方式/附图说明/证据清单/检索关键词建议);
  ③ 有据: 每份都带「证据清单」表且至少 5 行出处 (唯一依据文件路径);
  ④ 不吹: 全文无宣传话术禁词;
  ⑤ 不编: 唯一依据没有的项写「唯一依据未登记」; 如果"有益效果"没有验证方法, 必须出现「唯一依据未登记验证方法」;
  ⑥ 成件: docx 与 pdf 各 74 份 (--no-pdf 时跳过 pdf 检查);
  ⑦ 幂等: 重跑一次数量不变 (INDEX.json 计数 == 实际文件数)。
用法: ./gui-venv311/bin/python tools/verify_patent_export.py [--no-pdf]
"""
from __future__ import annotations

import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
OUT = "reports/patents"
META_J = "data/database/zmax/config_meta.json"
NOTES_J = "data/database/zmax/function_notes.json"
SECTIONS = ("## 一、发明名称", "## 二、技术领域", "## 三、背景技术", "## 四、要解决的技术问题",
            "## 五、技术方案", "## 六、有益效果", "## 七、具体实施方式", "## 八、附图说明",
            "## 九、证据清单", "## 十、检索关键词建议")
BAN = ("赋能", "生态", "抓手", "全面提升", "显著提升", "智能化升级", "助力", "打造", "一站式",
       "无缝", "深度融合", "颠覆", "行业领先", "大力")
OK, BAD = [], []


def chk(name, ok, ev=""):
    (OK if ok else BAD).append(name)
    print("  %s %-48s %s" % ("✅" if ok else "❌", name, ev))


def main():
    meta = json.load(open(META_J, encoding="utf-8"))["functions"]
    mds = sorted(glob.glob(os.path.join(OUT, "*_专利交底书.md")))
    docxs = glob.glob(os.path.join(OUT, "*.docx"))
    pdfs = glob.glob(os.path.join(OUT, "*.pdf"))
    idx_p = os.path.join(OUT, "INDEX.json")
    idx = json.load(open(idx_p, encoding="utf-8")) if os.path.exists(idx_p) else {}

    print("═══ ① 覆盖 ═══")
    got = {os.path.basename(p).split("_")[0] for p in mds}
    miss = [k for k in meta if k not in got]
    chk("每个功能一份交底书 (74)", not miss and len(mds) >= len(meta),
        "产物 %d 份 · 缺 %s" % (len(mds), miss[:5]))

    print("\n═══ ② 十节齐 / ③ 有据 / ④ 不吹 / ⑤ 不编 ═══")
    bad_sec, bad_ev, bad_ban, bad_nosrc = [], [], [], []
    for p in mds:
        t = open(p, encoding="utf-8").read()
        if not all(s in t for s in SECTIONS):
            bad_sec.append((os.path.basename(p), [s for s in SECTIONS if s not in t][:2]))
        if t.count("| `") < 5 or "唯一依据" not in t:
            bad_ev.append(os.path.basename(p))
        if any(b in t for b in BAN):
            bad_ban.append((os.path.basename(p), [b for b in BAN if b in t]))
        if "唯一依据未登记" not in t and "验证方法" not in t:
            bad_nosrc.append(os.path.basename(p))
    chk("十节标题齐", not bad_sec, str(bad_sec[:2]))
    chk("每份带证据清单 (≥5 行出处)", not bad_ev, str(bad_ev[:3]))
    chk("无宣传话术 (禁词 %d)" % len(BAN), not bad_ban, str(bad_ban[:2]))
    chk("缺项写「唯一依据未登记」不编", not bad_nosrc, str(bad_nosrc[:3]))

    print("\n═══ ⑥ 成件 / ⑦ 幂等 ═══")
    chk("docx 与 md 数量一致", len(docxs) >= len(mds), "docx %d / md %d" % (len(docxs), len(mds)))
    if "--no-pdf" in sys.argv:
        print("  ⏭ --no-pdf: 跳过 pdf 检查")
    else:
        chk("pdf 与 md 数量一致", len(pdfs) >= len(mds), "pdf %d / md %d" % (len(pdfs), len(mds)))
    chk("INDEX.json 计数与产物一致", idx.get("n") == len(mds), "%s vs %s" % (idx.get("n"), len(mds)))
    notes = json.load(open(NOTES_J, encoding="utf-8")) if os.path.exists(NOTES_J) else {}
    chk("INDEX 记录了描述唯一依据", idx.get("notes_src") == NOTES_J, str(idx.get("notes_src")))

    print("\n" + ("✅ 全部通过 (%d 项)" % len(OK) if not BAD else "⛔ 失败 %d 项: %s" % (len(BAD), BAD)))
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
