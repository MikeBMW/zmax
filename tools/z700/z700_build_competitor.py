#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""z700_build_competitor.py —— 生成《Z700 竞品分析报告》Word

数据来源 outputs/z700/competitor_data.json (由调研结果写入), 字段:
  competitor_table_md   竞品横向对比表(md 表格)
  profiles_md           各家定位描述
  threats_md            对 Z700 的威胁与机会
  optical_module_spec_md 光模块规格与插拔力量级
  sources               [url, ...]
  standards_table_md    标准清单(可选, 会写成 standards_rows.json 供其它文档用)

若 json 不存在, 退化为用 outputs/z700/competitor.md 的纯文本渲染。
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from z700_docx import OUT, Doc                                # noqa: E402


def md_table(txt):
    """把 md 表格块解析成 (headers, rows)。"""
    lines = [l.strip() for l in txt.strip().split("\n") if l.strip().startswith("|")]
    if len(lines) < 2:
        return None, None
    cells = lambda l: [c.strip() for c in l.strip().strip("|").split("|")]   # noqa: E731
    hdr = cells(lines[0])
    body = []
    for l in lines[1:]:
        if re.match(r"^\|[\s:\-|]+\|?$", l):
            continue
        c = cells(l)
        if len(c) == len(hdr):
            body.append(c)
    return hdr, body


def emit_md(d, txt, table_max_w=5.0):
    """把 markdown 渲染进 docx: 标题/表格/列表/段落。"""
    blocks = re.split(r"\n\s*\n", txt.strip())
    for b in blocks:
        b = b.strip()
        if not b:
            continue
        if b.startswith("|"):
            hdr, body = md_table(b)
            if hdr and body:
                n = len(hdr)
                w = min(15.0 / n, table_max_w)
                d.TABLE(hdr, body, widths=[w] * n, size=8)
            continue
        lines = [l for l in b.split("\n") if l.strip()]
        if all(l.strip().startswith(("#", "-", "*", "•")) for l in lines):
            for l in lines:
                s = l.strip()
                if s.startswith("#"):
                    d.H3(s.lstrip("# ").strip())
                else:
                    d.BULLET(s.lstrip("-*• ").strip(), size=10)
            continue
        if b.startswith("#"):
            d.H2(b.lstrip("# ").strip())
            continue
        d.P(b.replace("\n", " "))


def build():
    d = Doc(code="ZMAX-PD-Z700-CMP-5.50.E-R1",
            title="Z700 精细操作机器人\n竞品分析报告",
            subtitle="光模块精细操作赛道 · 竞品横向对标与差异化定位")
    d.cover()

    jp = os.path.join(OUT, "competitor_data.json")
    mp = os.path.join(OUT, "competitor.md")

    if os.path.exists(jp):
        data = json.load(open(jp, encoding="utf-8"))
    elif os.path.exists(mp):
        data = {"profiles_md": open(mp, encoding="utf-8").read()}
    else:
        data = {}

    # 1 结论先行
    d.H1("结论先行")
    thr = data.get("threats_md", "").strip()
    if thr:
        emit_md(d, thr)
    else:
        d.P("竞品调研数据尚未写入，本节内容待填充。")

    # 2 横向对比
    d.H1("竞品横向对比")
    ct = data.get("competitor_table_md", "").strip()
    if ct:
        emit_md(d, ct, table_max_w=3.2)
        d.NOTE("表内参数以厂商公开规格与公开报道为准；未公开项标「未公开」，未做推测填充。")
    else:
        d.P("（对比表待填充）")

    # 3 光模块规格与力量级
    om = data.get("optical_module_spec_md", "").strip()
    if om:
        d.H1("作业对象：光模块规格与插拔力量级")
        emit_md(d, om)

    # 4 各家定位
    pf = data.get("profiles_md", "").strip()
    if pf:
        d.H1("各家定位与强弱")
        emit_md(d, pf)

    # 5 对 Z700 的启示
    d.H1("从竞品看 Z700 的位置")
    d.P("把上面的对比收敛成三句话：")
    d.BULLET("在「臂」这个零件上，Z700 没有优势。协作臂已经是成熟品类，负载 5kg / 臂展 800mm "
             "是标准配置，用户可以从多家买到，价格透明。靠臂赢不了。")
    d.BULLET("在「力控 + 判据」这个能力上，胜负手在能不能给出可复核的证据。"
             "行业里多数方案能插进去，但说不清「插到什么程度算到位」——"
             "而这恰恰是工厂愿意付钱的地方，因为它决定了能不能验收、能不能交接。")
    d.BULLET("在「节拍」上，Z700 的差异化是异步看管（1 机 2 台）而不是单机速度。"
             "把单机速度推到极限会被物理规律挡住，把机台利用率翻倍不会。")
    d.NOTE("所以竞争策略不是「比别人快」，而是「比别人说得清」。"
           "165 条功能清单、三阶段判据、每条挂国标与证据来源——这套东西本身就是护城河，"
           "因为它让采购方有了可以写进合同的验收依据。")

    d.H1("风险：竞品会在哪里发起攻击")
    d.TABLE(["攻击方向", "对手可能的做法", "Z700 的应对"], [
        ["价格", "用低价协作臂 + 通用夹爪做「够用版」，打掉 30-40 万的价格带",
         "把价格战让出去，守住「有判据」的高价值工位；用 RaaS/按颗计费降低客户决策门槛"],
        ["单机速度", "用直线模组或专用机构把单颗节拍做到 3-4s",
         "不跟单机速度；讲异步看管的综合 UPH 与人工替代率"],
        ["生态绑定", "与测试机/MES 厂商深度绑定，做成整套方案",
         "坚持开放接口（REST/文件），不和客户系统对抗"],
        ["数据叙事", "宣称有自己的大模型 / VLA",
         "不拼参数量，拼「端侧 635K 可跑 + 每帧真被调用 + 有可验证证据」"],
    ], widths=[2.6, 6.4, 6.2])

    # 6 来源
    src = data.get("sources") or []
    d.H1("资料来源")
    if src:
        for i, u in enumerate(src, 1):
            d.P("%d. %s" % (i, u), size=9, indent=False)
    else:
        d.P("（来源待补充）", size=9, indent=False)
    d.NOTE("本报告只使用可溯源的公开信息。凡厂商未公开的参数，一律标注「未公开」，不做估算。"
           "对比结论基于公开规格与公开报道，不代表实测结论；"
           "如需实测对标，应安排同场景 A/B 试机。")

    p = os.path.join(OUT, "03_Z700_竞品分析报告.docx")
    d.save(p)

    # 若带标准表, 顺便落成 standards_rows.json 供解决方案/Excel 复用
    st = data.get("standards_table_md", "").strip()
    if st:
        hdr, body = md_table(st)
        if hdr and body and len(hdr) >= 5:
            rows = [[r[0], r[1], r[2], r[3], r[4]] for r in body]
            with open(os.path.join(OUT, "standards_rows.json"), "w", encoding="utf-8") as f:
                json.dump(rows, f, ensure_ascii=False, indent=1)
    return p


if __name__ == "__main__":
    p = build()
    print(json.dumps({"ok": True, "out": p,
                      "size_kb": round(os.path.getsize(p) / 1024)}, ensure_ascii=False))
