#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""导出「工程操作手册 (Working Instruction)」—— 三档性能等级 A/B/C。

真源: tools/spec/eng_profiles.json (与配置中心「工程配置」页同一份数据, 不复制真相)
产出: docs/deliverables/工程操作手册_三档_A_B_C.md

用法:
    python3 tools/export_wi_doc.py            # 生成/覆盖
    python3 tools/export_wi_doc.py --check    # 只校验 (不写文件), 文档步骤数必须与真源一致
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(ROOT, "tools", "spec", "eng_profiles.json")
OUT = os.path.join(ROOT, "docs", "deliverables", "工程操作手册_三档_A_B_C.md")
OUT_DOCX = os.path.join(ROOT, "docs", "deliverables", "工程操作手册_三档_A_B_C.docx")

NEED_CN = {"local": "本机 (可直接跑)", "onsite": "现场 (需设备/产线)", "orin": "Orin/执行腿可达"}


def load():
    with open(SPEC, encoding="utf-8") as f:
        return json.load(f)


def render(d):
    L = []
    md = d.get("_meta") or {}
    L.append("# 工程操作手册 (Working Instruction) —— 按性能等级 A / B / C\n")
    L.append("> 真源 `%s` · 版本 `%s` · 生成工具 `tools/export_wi_doc.py`\n"
             % (os.path.relpath(SPEC, ROOT), md.get("schema", "-")))
    L.append("> 三档与《性能配置》一一对应: **A 基本性能 (L2) / B 精细操作性能 (L2+L3) / "
             "C 专业性能 (L2+L3+L4 含 L5)**。档位只加不换: B 含 A 的全部, C 含 B 的全部。\n")
    L.append("\n## 0. 通用约定\n")
    L.append("| 项 | 约定 |")
    L.append("|---|---|")
    L.append("| 工作目录 | `%s` (所有命令都在这里执行) |" % md.get("root", "/home/ubuntu/zmax"))
    L.append("| 命令 = 判据 | 每条命令都能直接粘, 期望输出写在同一行; 对不上就是没做完 |")
    L.append("| 不做假动作 | 参数/权重/标定只能来自真源文件, 界面看不到的东西不许手填 |")
    L.append("| 失败先停 | 任何一步 FAIL 都停下来按「失败处理」修, 不许带着问题往下走 |")
    L.append("| 凭据 | 手册只核对凭据**键名**, 任何步骤都不打印密钥值 |")
    for p in d.get("profiles") or []:
        L.append("\n---\n")
        L.append("## %s 档 · %s\n" % (p.get("id"), p.get("name")))
        L.append("**对应性能**: %s\n" % p.get("perf_ref", "-"))
        L.append("\n### %s.1 硬件清单\n" % p.get("id"))
        L.append("| # | 设备 | 规格 | 数量 | 为什么 |")
        L.append("|---|---|---|---|---|")
        for i, h in enumerate(p.get("hardware") or [], 1):
            L.append("| %d | %s | %s | %s | %s |" % (i, h.get("item"), h.get("spec"), h.get("qty"), h.get("why")))
        L.append("\n### %s.2 软件栈 (服务/权重)\n" % p.get("id"))
        L.append("| 服务/资产 | 端口 | 起法/位置 |")
        L.append("|---|---|---|")
        for s in p.get("software") or []:
            L.append("| %s | %s | `%s` |" % (s.get("svc"), s.get("port") or "—", s.get("how")))
        L.append("\n### %s.3 标定项 (不达标就停)\n" % p.get("id"))
        L.append("| 标定项 | 真源 | 容差/判据 |")
        L.append("|---|---|---|")
        for c in p.get("calib") or []:
            L.append("| %s | `%s` | %s |" % (c.get("item"), c.get("src"), c.get("tol")))
        L.append("\n### %s.4 安全要求\n" % p.get("id"))
        for x in p.get("safety") or []:
            L.append("- %s" % x)
        L.append("\n### %s.5 操作步骤 (Working Instruction)\n" % p.get("id"))
        L.append("| 步骤 | 做什么 | 在哪做 | 命令 / 操作 | 期望 | 失败处理 |")
        L.append("|---|---|---|---|---|---|")
        for w in p.get("wi") or []:
            L.append("| **%s** | %s | %s | `%s` | `%s` | %s |"
                     % (w.get("id"), w.get("title"), NEED_CN.get(w.get("need"), w.get("need")),
                        w.get("cmd"), w.get("expect"), w.get("fail")))
        L.append("\n### %s.6 交付验收 (全过才算实现)\n" % p.get("id"))
        for a in p.get("acceptance") or []:
            L.append("- [ ] %s" % a)
    L.append("\n---\n")
    L.append("## 附: 三档对比 (选档依据)\n")
    L.append("| | A 基本性能 | B 精细操作性能 | C 专业性能 |")
    L.append("|---|---|---|---|")
    L.append("| 模型 | L2 | L2+L3 | L2+L3+L4(+L5) |")
    L.append("| 节拍 | 11.42s/件 · 316.1UPH | 同 A + 双臂并行 供料4.70/交接8.70 | 同 B + 意图决策 101ms |")
    L.append("| 多任务编排 | ✗ | ✓ 技能序列可组合 | ✓ + 自主重规划 |")
    L.append("| 异常自主恢复 | ✗ | ✗ 只能按预案分支 | ✓ max_veto=3 转异常 |")
    L.append("| 安全等级 | 单机限幅 | + 序列级校验 | 目标 PL d (认证未做) |")
    L.append("| 成本项 | 工控机+相机+AOI | +推理GPU+数据采集+LoRA | +L4训练+API/3B显存+安全认证 |")
    L.append("\n> 选档规则: 只做单产品单工位节拍 ⇒ A; 要换产品/多工位靠序列 ⇒ B; "
             "要自主判断异常并担安全等级 ⇒ C。**降档可以, 跳档不行** (B 必须含 A 的全部验收)。\n")
    return "\n".join(L) + "\n"


def write_docx(md_text, path):
    """把手册 markdown 转 Word (标题/表格/列表), 供工程现场打印签字。"""
    try:
        from docx import Document
        from docx.shared import Pt
        from docx.oxml.ns import qn
    except Exception:                                                           # noqa: BLE001
        print("[WARN] 无 python-docx, 跳过 docx 导出")
        return None
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name = "Microsoft YaHei"
    st.font.size = Pt(9.5)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")

    def _set_font(par):
        for r in par.runs:
            r.font.name = "Microsoft YaHei"
            r._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")

    lines = md_text.split("\n")
    i = 0
    while i < len(lines):
        ln = lines[i].rstrip()
        if not ln.strip():
            i += 1
            continue
        if ln.startswith("|"):
            blk = []
            while i < len(lines) and lines[i].startswith("|"):
                blk.append(lines[i])
                i += 1
            rows = [[c.strip().strip("`") for c in r.strip().strip("|").split("|")] for r in blk]
            rows = [r for r in rows if not all(set(c) <= set("-: ") for c in r)]
            if not rows:
                continue
            ncol = max(len(r) for r in rows)
            t = doc.add_table(rows=0, cols=ncol)
            t.style = "Table Grid"
            for ri, r in enumerate(rows):
                cells = t.add_row().cells
                for ci in range(ncol):
                    txt = r[ci] if ci < len(r) else ""
                    txt = txt.replace("**", "").replace("`", "")
                    cells[ci].text = txt
                    for par in cells[ci].paragraphs:
                        _set_font(par)
                        for run in par.runs:
                            run.font.size = Pt(8.5)
                            if ri == 0:
                                run.bold = True
            doc.add_paragraph("")
            continue
        if ln.startswith("### "):
            h = doc.add_heading(ln[4:], level=3); _set_font(h)
        elif ln.startswith("## "):
            h = doc.add_heading(ln[3:], level=2); _set_font(h)
        elif ln.startswith("# "):
            h = doc.add_heading(ln[2:], level=1); _set_font(h)
        elif ln.startswith("> "):
            par = doc.add_paragraph(ln[2:].replace("`", ""))
            par.runs[0].italic = True
            _set_font(par)
        elif ln.startswith("- "):
            par = doc.add_paragraph(ln[2:].replace("`", ""), style="List Bullet"); _set_font(par)
        else:
            par = doc.add_paragraph(ln.replace("`", "")); _set_font(par)
        i += 1
    doc.save(path)
    return path


def main():
    d = load()
    txt = render(d)
    if "--check" in sys.argv:
        if not os.path.exists(OUT):
            print("[FAIL] 文档不存在: %s" % os.path.relpath(OUT, ROOT))
            return 1
        cur = open(OUT, encoding="utf-8").read()
        ok = True
        for p in d.get("profiles") or []:
            for w in p.get("wi") or []:
                if w.get("id") not in cur:
                    print("[FAIL] 文档缺步骤 %s" % w.get("id"))
                    ok = False
        n_wi = sum(len(p.get("wi") or []) for p in d.get("profiles") or [])
        n_doc = cur.count("| **")
        print("[%s] 步骤数 真源 %d / 文档 %d" % ("PASS" if n_wi == n_doc else "FAIL", n_wi, n_doc))
        ok = ok and (n_wi == n_doc)
        print("[%s] 三档标题 %s" % ("PASS" if all(("%s 档" % p.get("id")) in cur for p in d.get("profiles") or []) else "FAIL",
                                  [p.get("id") for p in d.get("profiles") or []]))
        print("[%s] 无密钥值泄漏 %s" % ("PASS" if ("sk-" not in cur and "API_KEY=" not in cur) else "FAIL", "已核"))
        return 0 if ok else 1
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(txt)
    dpath = write_docx(txt, OUT_DOCX)
    if dpath:
        print("写出 %s (%d 字节)" % (os.path.relpath(dpath, ROOT), os.path.getsize(dpath)))
    n_wi = sum(len(p.get("wi") or []) for p in d.get("profiles") or [])
    print("写出 %s (%d 字节, 三档 %d 步)" % (os.path.relpath(OUT, ROOT), len(txt.encode()), n_wi))
    return 0


if __name__ == "__main__":
    sys.exit(main())
