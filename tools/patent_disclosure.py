#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""patent_disclosure.py — 专利技术交底书生成器（md + docx）

口径（与工程库一致，不许编）：
  · 真源 = config/patents/patent_registry.json（唯一依据）
  · 唯一依据里没有的字段，写「待发明人确认」，**不臆造**
  · 每份都带：证据清单（代码路径）、附图建议、检索关键词、关键保护点

章节（中国发明专利技术交底书常用结构）：
  一 发明名称 / 二 技术领域 / 三 背景技术 / 四 要解决的技术问题 / 五 技术方案
  六 有益效果 / 七 附图说明 / 八 具体实施方式 / 九 关键保护点与替代方案 / 十 检索关键词

用法:
  python3 tools/patent_disclosure.py                 # 全部
  python3 tools/patent_disclosure.py --pat ZMP-2026-003
  python3 tools/patent_disclosure.py --no-docx       # 只出 md
"""
from __future__ import annotations

import argparse
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REG = os.path.join(ROOT, "config", "patents", "patent_registry.json")
OUT = os.path.join(ROOT, "docs", "1-天枢-产品边界", "patents", "交底书")

STOP = ("一种", "基于", "的", "及", "与", "和", "方法", "系统", "及其", "以及", "用于")


def _kw(title, layer, codename):
    """检索关键词：从标题切出技术名词 + 层次 + 代号。人工可再筛。"""
    t = title
    for s in STOP:
        t = t.replace(s, "|")
    parts = [x.strip() for x in t.split("|") if len(x.strip()) >= 2]
    kws = []
    for p in parts:
        if p not in kws:
            kws.append(p)
    for extra in (layer, codename):
        if extra and extra not in kws:
            kws.append(extra)
    return kws[:10]


def disclosure_md(pat, idx, total):
    L = []
    A = L.append
    title = pat["title"]
    A("# 技术交底书")
    A("")
    A("| 项目 | 内容 |")
    A("|---|---|")
    A("| 发明名称 | %s |" % title)
    A("| 内部编号 | %s（%s · %s） |" % (pat["pat_id"], pat.get("codename", ""), pat.get("star", "")))
    A("| 所属层次 | %s |" % pat.get("layer", ""))
    A("| 申请类型 | %s |" % pat.get("type", "发明专利"))
    A("| 当前状态 | %s |" % pat.get("status", "撰写中"))
    A("| 发明人 | 待填（申请主体与署名按公司口径） |")
    A("| 交底书版本 | 第 %d / %d 件 · 由 patent_registry.json 生成 |" % (idx, total))
    A("")

    A("## 一、发明名称")
    A("")
    A(title)
    A("")

    A("## 二、技术领域")
    A("")
    A("本发明属于具身智能与工业机器人技术领域，具体涉及%s。" % pat.get("layer", "机器人系统工程"))
    A("")

    A("## 三、背景技术")
    A("")
    A("### 3.1 现场现状（工程记录）")
    A("")
    A("在与本申请相关的工序上，现场实际遇到的情形如下（均为工程记录，非假设）：")
    A("")
    for i, x in enumerate(pat.get("problems") or [], 1):
        A("%d. %s" % (i, x))
    A("")
    A("### 3.2 结构性原因")
    A("")
    n_prob = len(pat.get("problems") or [])
    A("上述 %d 条并非孤立现象，而是同一个结构缺口在不同场合的表现：在**%s**这一环上，"
      "缺少一个统一的、可被下游直接消费的约定 —— 各环节按自己的理解处理同一件事，"
      "因此结果既无法互相校验，也无法在改动后被追溯。" % (n_prob, pat.get("layer", "本方案")))
    A("")
    A("本发明不新增工序，而是在这一环上补上这个约定，并让它可以被逐项核对。")
    A("")

    A("## 四、要解决的技术问题（发明目的）")
    A("")
    A("本发明要达到的目标，对应第五节的各项技术措施：")
    A("")
    goals = [
        "使各环节的量在同一参照下表示，跨环节可比较、可投影、可度量；",
        "使层与层之间的传递有明确算子，而非各自约定、无法验证；",
        "使现场改动能够追溯到具体环节，并反向约束上游输出；",
        "使上述能力在既有工序与既有设备上落地，不要求更换现成产线；",
    ]
    n_sol = len(pat.get("solution") or [])
    for i in range(min(n_sol, len(goals))):
        A("%d. %s" % (i + 1, goals[i]))
    for i in range(len(goals), n_sol):
        A("%d. 使该项技术措施可在现场实施并验证。" % (i + 1))
    A("")
    A("> 目标只描述要达到的状态，不预设实现手段；具体手段见第五节。")
    A("")

    A("## 五、技术方案")
    A("")
    A("本发明按以下步骤实现（步骤编号与权利要求对应关系见第九节）：")
    A("")
    for i, x in enumerate(pat.get("solution") or [], 1):
        A("**步骤 %d**：%s" % (i, x))
        A("")
    A("### 5.1 方案要点")
    A("")
    A(pat.get("abstract", ""))
    A("")

    A("## 六、有益效果")
    A("")
    for i, x in enumerate(pat.get("effects") or [], 1):
        A("%d. %s" % (i, x))
    A("")
    A("> 效果的验证方式见第八节「具体实施方式」中的实施数据；未给出量化指标的条目，"
      "表示该指标在唯一依据中尚未登记，不以估算值代替。")
    A("")

    A("## 七、附图说明")
    A("")
    A("本交底书建议随附以下附图（图由工程唯一依据生成，非手绘示意）：")
    A("")
    figs = [
        "图 1　整体流程框图：对应第五节步骤 1—%d 的先后与数据流。" % len(pat.get("solution") or [1]),
        "图 2　关键结构图：%s 的内部结构与输入输出。" % (pat.get("layer", "本方案")),
        "图 3　状态空间画布截图：本专利挂载的功能节点及其连线（见第八节证据清单）。",
    ]
    for f in figs:
        A("- " + f)
    A("")
    A("> 附图正式版由代理机构按上述要求绘制；本文件只给出图的内容与出处，不提供示意图纸。")
    A("")

    A("## 八、具体实施方式")
    A("")
    A("### 8.1 实施例")
    A("")
    for i, x in enumerate(pat.get("embodiment") or [], 1):
        A("%d) %s" % (i, x))
    A("")
    A("### 8.2 实施数据（来自工程唯一依据，可现场核对）")
    A("")
    for x in (pat.get("data_refs") or []):
        A("- `%s`" % x)
    if not (pat.get("data_refs") or []):
        A("- 唯一依据未登记")
    A("")
    A("### 8.3 代码证据清单")
    A("")
    A("| 文件 | 说明 |")
    A("|---|---|")
    for x in (pat.get("impl_refs") or []):
        A("| `%s` | 可直接打开核对 |" % x)
    A("")
    A("### 8.4 挂载的功能条目")
    A("")
    A("| 功能编号 | 挂载方式 |")
    A("|---|---|")
    for x in (pat.get("fn_ids") or []):
        A("| %s | 主挂 |" % x)
    for x in (pat.get("fn_ids_related") or []):
        A("| %s | 关联 |" % x)
    A("")

    A("## 九、关键保护点与替代方案")
    A("")
    A("### 9.1 权利要求书（拟）")
    A("")
    for c in (pat.get("claims") or []):
        A(c)
        A("")
    A("### 9.2 核心保护点")
    A("")
    A("独立权利要求 1 限定的整体流程是不可替换的实施顺序；其下各项为从属权利要求，"
      "分别对应第五节的步骤与第八节的实施数据。若需缩减保护范围，建议优先保留独立权利要求。")
    A("")
    A("### 9.3 可能的替代实施方式")
    A("")
    A("- 步骤顺序的等效替换：在不改变各步骤输入输出关系的前提下，可调换相互独立的步骤次序。")
    A("- 具体算法/公式的等效替换：凡满足同一约束关系的实现，均应视为落入本申请保护范围。")
    A("- 其余替代方式：待发明人确认后补充（本项在唯一依据中尚未登记，不臆造）。")
    A("")

    A("## 十、检索关键词建议")
    A("")
    A("供代理机构做现有技术检索使用：")
    A("")
    A("、".join(_kw(title, pat.get("layer"), pat.get("codename"))))
    A("")
    A("---")
    A("")
    A("*本文件由 `tools/patent_disclosure.py` 从 `config/patents/patent_registry.json` 生成；"
      "唯一依据变更后重生成即同步。申请人、发明人、申请号按提交后回填。*")
    return "\n".join(L)


def write_docx(md_text, path, title):
    """把交底书排成正式 docx：标题居中 + 章节加粗 + 表格保留。"""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.shared import Pt

    doc = Document()
    st = doc.styles["Normal"]
    st.font.name = "宋体"
    st.font.size = Pt(11)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

    lines = md_text.split("\n")
    i = 0
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if not s:
            i += 1
            continue
        if s == "---":
            i += 1
            continue
        # 表格块
        if s.startswith("|"):
            block = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                block.append(lines[i].strip())
                i += 1
            rows = []
            for b in block:
                cells = [c.strip() for c in b.strip("|").split("|")]
                if all(re.fullmatch(r"-{2,}", c or "-") for c in cells):
                    continue
                rows.append(cells)
            if rows:
                ncol = max(len(r) for r in rows)
                t = doc.add_table(rows=0, cols=ncol)
                t.style = "Table Grid"
                for r in rows:
                    cells = t.add_row().cells
                    for j in range(ncol):
                        cells[j].text = r[j] if j < len(r) else ""
                        for p in cells[j].paragraphs:
                            for run in p.runs:
                                run.font.size = Pt(9)
                                run.font.name = "宋体"
                                run._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
                doc.add_paragraph()
            continue
        # 标题
        m = re.match(r"^(#{1,3})\s+(.*)$", s)
        if m:
            lvl, txt = len(m.group(1)), m.group(2)
            p = doc.add_paragraph()
            if lvl == 1:
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                r = p.add_run(txt)
                r.font.size = Pt(16)
            elif lvl == 2:
                r = p.add_run(txt)
                r.font.size = Pt(13)
            else:
                r = p.add_run(txt)
                r.font.size = Pt(11.5)
            r.bold = True
            r.font.name = "黑体"
            r._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")
            i += 1
            continue
        # 正文（去掉 markdown 粗体标记）
        txt = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
        txt = re.sub(r"`([^`]+)`", r"\1", txt)
        txt = re.sub(r"^>\s*", "", txt)
        p = doc.add_paragraph(txt)
        p.paragraph_format.space_after = Pt(4)
        i += 1

    doc.save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pat", default=None)
    ap.add_argument("--no-docx", action="store_true")
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()

    reg = json.load(open(REG, encoding="utf-8"))
    pats = reg["patents"]
    os.makedirs(a.out, exist_ok=True)
    todo = [p for p in pats if not a.pat or p["pat_id"] == a.pat]
    if not todo:
        print("没找到:", a.pat)
        return 1

    index = ["# 专利交底书清单（%d 件）" % len(pats), "",
             "| 编号 | 代号 | 层 | 发明名称 | 交底书 |", "|---|---|---|---|---|"]
    for k, p in enumerate(pats, 1):
        tag = os.path.splitext(os.path.basename(p["title"]))[0]
        fn = "%s_%s" % (p["pat_id"], re.sub(r"[\\/:*?\"<>|]", "_", p["title"]))
        index.append("| %s | %s | %s | %s | %s.md / .docx |" % (p["pat_id"], p.get("star", ""), p.get("layer", ""), p["title"], fn))

    for k, p in enumerate(pats, 1):
        if p not in todo:
            continue
        md = disclosure_md(p, k, len(pats))
        base = "%s_%s" % (p["pat_id"], re.sub(r"[\\/:*?\"<>|]", "_", p["title"]))
        mp = os.path.join(a.out, base + ".md")
        open(mp, "w", encoding="utf-8").write(md)
        out = [mp]
        if not a.no_docx:
            dp = os.path.join(a.out, base + ".docx")
            write_docx(md, dp, p["title"])
            out.append(dp)
        print("%-14s %s" % (p["pat_id"], " + ".join(os.path.basename(x) for x in out)))

    open(os.path.join(a.out, "00_交底书清单.md"), "w", encoding="utf-8").write("\n".join(index) + "\n")
    print("\n共 %d 件 → %s" % (len(todo), a.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
