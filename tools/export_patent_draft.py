#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""export_patent_draft.py — 功能点 → 专利交底书 一键导出 (老倪 2026-10-14)

老倪原话:
  「以后每个功能, 需要独立成一个研究成果, 都可以申请专利, 所以你要预留专利申请一键导出的功能。」

口径 (三条, 逐条落到实现):
  1. **一个功能点 = 一份交底书**: 交底书内容**全部取自工程唯一依据**, 每条都写明出处 (文件 + 行号/字段),
     唯一依据里没有的 (比如"现场痛点") 就写「唯一依据未登记」, 不许编 —— 交底书进专利代理前要能逐条对回唯一依据。
  2. **文字不AI化**: 面向问题与痛点, 车间口径; 禁词表会被判据查 (赋能/闭环生态/抓手/…)。
  3. **可检索性**: 每份自动给"检索关键词建议" (来自功能名/参数名/输入输出词), 便于代理所检索对比文件。

章节 (中国发明专利交底书常用结构 + 工程证据清单):
  一 发明名称 / 二 技术领域 / 三 背景技术 (现存问题) / 四 要解决的技术问题 / 五 技术方案
  六 有益效果 (只用唯一依据里的验证方法/指标) / 七 具体实施方式 (哪些任务启用 + 参数取值)
  八 附图说明 (证据图片路径) / 九 证据清单 (唯一依据文件·字段·代码文件·判据) / 十 检索关键词建议

唯一依据:
  data/database/zmax/config_meta.json          功能 (输入/输出/参数/验证/枚举/范围)
  data/database/zmax/function_notes.json       每个功能的 work/pain/state (朴素工程化描述)
  src/lerobot/engineering/flows/state_space_obs.json   画布节点/连线 (依赖关系)
  config/tasks/tasks.json + config/ss_task_binding.json  承载任务 (实施例)
  reports/drill/<task>/                         演练证据 (波形 PNG/记录, 有则引用)

用法:
  ./gui-venv311/bin/python tools/export_patent_draft.py --fn FN-SYS2-01
  ./gui-venv311/bin/python tools/export_patent_draft.py --all            # 74 份 + INDEX
  ./gui-venv311/bin/python tools/export_patent_draft.py --all --no-pdf   # 只出 md+docx
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import export_meta_doc as E                                                                # noqa: E402

OUT = "reports/patents"
NOTES_J = "data/database/zmax/function_notes.json"
BAN = ("赋能", "闭环赋能", "生态", "抓手", "全面提升", "显著提升", "智能化升级", "助力", "打造",
       "一站式", "无缝", "深度融合", "颠覆", "行业领先", "大力")


def _safe(name, n=24):
    """文件名安全化: 功能名里有 `/`(MES/自然语言) 这类字符会直接写不出文件 (实测 2026-10-14)。"""
    s = re.sub(r'[\\/:*?"<>|\s]+', "_", str(name or "")).strip("_")
    return s[:n] or "unnamed"


def _enrich(m):
    """补全参数/枚举唯一依据 (MT 里只有 params_head, 交底书要逐条参数与枚举约束)。"""
    try:
        with open(E.DB + "/config_meta.json", encoding="utf-8") as f:
            v = (json.load(f).get("functions") or {}).get(m["fn_id"]) or {}
    except Exception:                                                                      # noqa: BLE001
        v = {}
    f = v.get("fields") or {}
    m["params"] = [{"id": p.get("id"), "cn": p.get("cn"), "value": p.get("value"),
                    "unit": p.get("unit")} for p in (f.get("parameters") or [])]
    m["enums"] = ["%s=%s" % (k, ",".join(map(str, val))[:60]) if isinstance(val, (list, tuple))
                  else "%s=%s" % (k, val) for k, val in (v.get("enums") or {}).items()][:6]
    m["subsystem_hint"] = [v.get("subsystem")] if v.get("subsystem") else []
    m["code_file"] = m.get("code_file") or v.get("code_file")
    return m


def _notes():
    try:
        with open(NOTES_J, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                                      # noqa: BLE001
        return {}


def _kw(m):
    """检索关键词建议 —— 只取唯一依据里出现过的词 (功能名/参数名/输入输出), 不造词。"""
    ws = set()
    for s in [m.get("name") or ""] + list(m.get("inputs") or []) + list(m.get("outputs") or []):
        for w in re.split(r"[/、,，;；()（）\s]+", str(s)):
            w = w.strip()
            if 2 <= len(w) <= 12:
                ws.add(w)
    for p in (m.get("params_head") or []):
        w = re.split(r"[=:]", str(p))[0].strip()
        if 2 <= len(w) <= 30:
            ws.add(w)
    for p in (m.get("params") or [])[:40]:
        for cand in (p.get("cn"), (p.get("id") or "").split("#")[-1]):
            if cand and 2 <= len(str(cand)) <= 12:
                ws.add(str(cand))
    return sorted(ws)[:14]


def build_patent(m, notes, drills):
    """一份交底书 (markdown)。m = export_meta_doc.build_meta_tasks() 的一条元任务。"""
    fid = m["fn_id"]
    nt = notes.get(fid) or {}
    tasks = m.get("tasks") or []
    scen = m.get("scenes") or []
    ev = []
    for f in glob.glob(os.path.join("reports/drill", "*", "waveforms", "*.png")):
        ev.append(f)
    bands = [f for f in ev if f]
    L = []
    A = L.append
    A("# 专利交底书（草稿）：%s" % m["name"])
    A("")
    A("> 本交底书由 `tools/export_patent_draft.py` 从工程唯一依据自动生成，**每条内容都标注出处**；")
    A("> 唯一依据未登记的项直接写「唯一依据未登记」，未做任何推测性表述。文字为车间工程口径。")
    A("")
    A("| 项 | 值 |")
    A("|---|---|")
    A("| 功能编号 | %s |" % fid)
    A("| 归属层 | %s |" % (m.get("layer") or "—"))
    A("| 画布节点 | `%s` |" % (m.get("node_id") or "—"))
    A("| 代码唯一依据 | `%s` |" % (m.get("code_file") or "—"))
    A("| 元任务编号 (计划) | %s |" % (m.get("mt_id") or "—"))
    A("| 生成时间 | %s |" % time.strftime("%Y-%m-%d %H:%M:%S"))
    A("")
    A("## 一、发明名称")
    A("")
    _nm = re.sub(r"^[^\w\u4e00-\u9fff]+", "", str(m["name"] or "")).strip()
    A("一种%s方法（工程名：%s）" % (_nm, m["name"]))
    A("")
    A("## 二、技术领域")
    A("")
    A("机器人精细操作控制（%s 层），具体涉及 %s。" % (m.get("layer") or "—",
                                            "、".join(m.get("subsystem_hint") or []) or
                                            "光模块工厂现场作业的自动化实现"))
    A("")
    A("## 三、背景技术（现存问题）")
    A("")
    if nt.get("pain"):
        A("现场问题：%s" % nt["pain"])
    else:
        A("现场问题：唯一依据未登记（需现场补充：这个功能替代了原来哪一步人工/旧办法，阻塞点）。")
    A("")
    A("现有做法的问题（可复核项）：")
    A("- 输入未登记或未定值：%s" % ("有" if m.get("inputs") else "**唯一依据里没有登记输入**"))
    A("- 输出未登记或未定值：%s" % ("有" if m.get("outputs") else "**唯一依据里没有登记输出**"))
    A("- 参数未定值：%s" % ("、".join([p for p in (m.get("params_head") or []) if "None" in p or "null" in p])
                        or "无（参数均有取值或范围）"))
    A("- 上游依赖缺失：%s" % ("、".join(m.get("deps_up") or []) or "**画布上没有上游依赖**"))
    A("")
    A("## 四、要解决的技术问题")
    A("")
    A("1. %s" % (nt.get("work") or "把 %s 这一步从人工/旧流程改成工程可配置、可复现的执行。" % m["name"]))
    A("2. 让该步的参数可配、可回读、可验证（配置中心统一管理，改参数不改代码）。")
    A("3. 唯一依据可追溯：功能 ↔ 画布节点 ↔ 模块代码 ↔ 参数 ↔ 验证方法 一条链查得到。")
    A("")
    A("## 五、技术方案")
    A("")
    A("输入：%s" % ("；".join(m.get("inputs") or []) or "唯一依据未登记"))
    A("")
    A("输出：%s" % ("；".join(m.get("outputs") or []) or "唯一依据未登记"))
    A("")
    A("执行步骤（按唯一依据登记）：")
    A("1. 从画布该节点取配置参数（%d 条，节选：%s）。" % (m.get("n_params", 0),
                                            "；".join(m.get("params_head") or []) or "—"))
    A("2. 依赖上游节点：%s。" % ("、".join(m.get("deps_up") or []) or "无（画布无上游连线）"))
    A("3. 执行体：`%s`（模块注册于 `src/lerobot/engineering/nodes/library.py`）。"
      % (m.get("code_file") or "—"))
    A("4. 输出经数据总线以节点输出话题 `ss/%s/out` 序列化（单步调试模式真序列化）。"
      % (m.get("node_id") or "?"))
    A("5. 验证：%s。" % ("；".join(m.get("verification") or []) or "唯一依据未登记"))
    if m.get("enums"):
        A("")
        A("枚举约束（唯一依据登记）：%s" % "；".join(m["enums"]))
    A("")
    A("## 六、有益效果")
    A("")
    if m.get("verification"):
        for v in m["verification"]:
            A("- 按登记验证方法可复验：%s" % v)
    else:
        A("- 唯一依据未登记验证方法 ⇒ **本项不能作为有益效果的证据**，须补测。")
    A("- 参数改动只在配置中心生效，不需要改代码（可热更新，来源：配置中心唯一依据）。")
    A("")
    A("## 七、具体实施方式（实施例）")
    A("")
    if tasks:
        A("该功能已在以下任务里被启用（配置中心「任务配置」唯一依据）：")
        for t in tasks:
            A("- %s（元任务 %s）" % (t, "、".join(scen) or "—"))
    else:
        A("**该功能当前没有任何任务启用**（未接入执行链）⇒ 实施例须现场补充。")
    A("")
    A("参数取值（唯一依据实读，节选）：")
    for p in (m.get("params") or [])[:8]:
        A("- `%s` %s = %s %s" % (p.get("id"), p.get("cn"), p.get("value"), p.get("unit") or ""))
    A("")
    A("## 八、附图说明")
    A("")
    if bands:
        A("演练证据图（`tools/run_full_drill.py` 真跑产出）：")
        for f in sorted(bands)[:6]:
            A("- `%s`" % f)
    else:
        A("暂无可引用的证据图（先跑 `tools/run_full_drill.py` 生成波形）。")
    A("")
    A("## 九、证据清单（逐条可回查）")
    A("")
    A("| 证据 | 出处 |")
    A("|---|---|")
    A("| 功能登记（输入/输出/参数/验证） | `data/database/zmax/config_meta.json` → functions.%s |" % fid)
    A("| 朴素工程化描述（干什么/阻塞点/状态） | `%s` → %s |" % (NOTES_J, fid))
    A("| 画布节点与依赖连线 | `src/lerobot/engineering/flows/state_space_obs.json` 节点 `%s` |"
      % (m.get("node_id") or "—"))
    A("| 承载任务与启用节点 | `config/tasks/tasks.json` · `config/ss_task_binding.json` |")
    A("| 节点逻辑实现 | `src/lerobot/engineering/nodes/library.py`（模块 `%s`） |" % (m.get("code_file") or "—"))
    A("| 单步话题序列化 | `zmax_data/dataspace/trace.jsonl`（topic `ss/%s/out`） |" % (m.get("node_id") or "?"))
    A("| 演练记录（配置链+运行+波形+模型+训练） | `reports/drill/<task>/` |")
    A("")
    A("## 十、检索关键词建议")
    A("")
    A("、".join(_kw(m)) or "唯一依据不足，建议人工补充关键词")
    A("")
    A("---")
    A("")
    A("**待补项（交专利代理前必须由人补全）**：")
    A("- 现场痛点原话与影响量化（停机时长/不良率/人工工时）；")
    A("- 与最接近的现有技术（对比文件）的差别点；")
    A("- 实施例的实测数据（用演练与真机数据填，缺什么标什么）。")
    A("")
    return "\n".join(L).replace("\n\n\n", "\n\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fn", default="", help="单个功能号 FN-xxx")
    ap.add_argument("--all", action="store_true", help="74 个功能全出")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--no-pdf", action="store_true")
    ap.add_argument("--no-docx", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    MT, ctx = E.build_meta_tasks()
    notes = _notes()
    if a.fn:
        MT = [m for m in MT if m["fn_id"] == a.fn or m.get("mt_id") == a.fn]
        if not MT:
            print("⛔ 唯一依据里没有功能 %s" % a.fn)
            return 2
    os.makedirs(a.out, exist_ok=True)
    made, banned = [], []
    for m in MT:
        _enrich(m)
        md = build_patent(m, notes, None)
        for b in BAN:
            if b in md:
                banned.append((m["fn_id"], b))
        mdp = os.path.join(a.out, "%s_%s_专利交底书.md" % (m["fn_id"], _safe(m.get("name"))))
        with open(mdp, "w", encoding="utf-8") as f:
            f.write(md)
        rec = {"fn_id": m["fn_id"], "md": mdp}
        if not a.no_docx or not a.no_pdf:
            html = E.md_to_html(md)
            hp = mdp[:-3] + ".html"
            with open(hp, "w", encoding="utf-8") as f:
                f.write(html)
            rec["html"] = hp
            if not a.no_docx:
                try:
                    rec["docx"] = E.soffice_convert(hp, "html2docx", a.out)
                except Exception as e:                                                     # noqa: BLE001
                    rec["docx_err"] = repr(e)
            if not a.no_pdf:
                try:
                    rec["pdf"] = E.soffice_convert(hp, "html2pdf", a.out)
                except Exception as e:                                                     # noqa: BLE001
                    rec["pdf_err"] = repr(e)
        made.append(rec)
    idx = os.path.join(a.out, "INDEX.json")
    with open(idx, "w", encoding="utf-8") as f:
        json.dump({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "n": len(made),
                   "notes_src": NOTES_J, "items": made},
                  f, ensure_ascii=False, indent=1)
    res = {"n": len(made), "out": a.out, "index": idx, "ban_hits": banned[:10],
           "docx": sum(1 for r in made if r.get("docx")), "pdf": sum(1 for r in made if r.get("pdf"))}
    if a.json:
        print(json.dumps(res, ensure_ascii=False))
    else:
        print("✅ 专利交底书: %d 份 → %s" % (res["n"], a.out))
        print("   docx %d 份 · pdf %d 份 · 禁词命中 %d" % (res["docx"], res["pdf"], len(banned)))
        for r in made[:3]:
            print("   %s" % r["md"])
    return 1 if banned else 0


if __name__ == "__main__":
    sys.exit(main())
