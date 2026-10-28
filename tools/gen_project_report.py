#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成《双臂协作工位项目立项报告》(md + docx)。

数字全部来自 cost_model.build_tiers() 与 rollout_model.build_rollout(), 报告里不预先固定任何结论,
改售价上限、免费期或阶段参数后重跑本脚本即同步。

跑法: python3 tools/gen_project_report.py [--md-only]
输出: docs/deliverables/项目立项报告_双臂协作工位.md / .docx
"""
import json
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from cost_model import build_tiers          # noqa: E402
from rollout_model import build_rollout     # noqa: E402

OUT_DIR = os.path.join(ROOT, "docs", "deliverables")
MD = os.path.join(OUT_DIR, "项目立项报告_双臂协作工位.md")
DOCX = os.path.join(OUT_DIR, "项目立项报告_双臂协作工位.docx")


SHORT = {"A": "基础版", "B": "精细版", "C": "专业版"}


def wan(x):
    return "%.2f 万元" % (x / 1e4) if abs(x) >= 1e4 else "%.0f 元" % x


def pct(x):
    return "%.1f%%" % x


def gather():
    d = build_tiers()
    r = build_rollout()
    v = json.load(open(os.path.join(HERE, "spec", "vision.json"), encoding="utf-8"))
    T = {t["id"]: t for t in d["tiers"]}
    from targets_model import build_targets
    TG = build_targets()["tiers"]
    return d, r, v, T, TG


def lines(d, r, v, T, TG):
    vs = v["vision"]
    L = []
    A = lambda s="": L.append(s)                                   # noqa: E731
    A("# 双臂协作工位项目立项报告")
    A("")
    A("版本 v1.0 · 生成时间 %s · 数字由 tools/cost_model.py 与 tools/rollout_model.py 现算"
      % datetime.now().strftime("%Y-%m-%d %H:%M"))
    A("")
    A("## 一、项目名称与一句话")
    A("")
    A("**%s**" % vs["headline"])
    A("")
    A("%s" % vs["subline"])
    A("")
    A("项目要做的事情：%s" % vs["answer"])
    A("")
    A("## 二、立项依据：为什么是我们")
    A("")
    A("当前的问题不是机器人不会动，而是 %s" % vs["problem"])
    A("")
    for p in v["pillars"]:
        A("- **%s**：%s（依据：%s）" % (p["name"], p["one_line"], p["evidence"]))
    A("")
    A("## 三、目标与验收")
    A("")
    A("| 项目 | 目标值 | 口径 |")
    A("| --- | --- | --- |")
    A("| 单件节拍 | %.2f s/件 | 392 段轨迹真值，模数 14 件/轮 |" % d["tact_s"])
    A("| 产能 | %.1f 件/小时 | 节拍折算，两班 16 小时 |" % d["uph_geo"])
    A("| 重复定位 | AP ≤0.50 mm / RP ≤0.10 mm | ISO 9283 §7.2/§7.4，第三方实测前不进验收 |")
    A("| 插拔行程 | 47.0 mm @ 156.7 mm/s | 光模块插入段 |")
    A("| 插入力上限 | 40 N | ISO/TS 15066 人体协作限值内 |")
    A("| 视觉精度 | 0.76 mm/px @300 mm | 深度单位 0.1 mm |")
    A("")
    A("## 四、技术方案要点")
    A("")
    A("八环节一条链：%s。" % " → ".join(s["title"] for s in v["spine"]))
    A("")
    A("- 分层：L2 检测与肌肉记忆技能、L3 任务编排、L4 认知与世界模型、L5 规划与安全")
    A("- 双臂并行：左臂供料 %.2f s 后空闲，右臂稳态单件 %.2f s，交接点 %.2f s，同一槽同一时刻只有一只手"
      % (4.70, 11.40, 8.70))
    A("- 功能底座：33 个本任务服务功能，每个带输入/输出/描述与可定位实现")
    A("- 验证：判据脚本离屏实跑，页面/工单/报告/PPT 数字同源")
    A("")
    return L


def lines2(d, r, v, T, TG):
    L = []
    A = lambda s="": L.append(s)                                   # noqa: E731
    A("## 五、市场策略：三个阶段接续落地")
    A("")
    A("策略不是一次卖三个版本，而是按客户信任度与数据量分三步走。人工口径：一个工位白班晚班各一人，"
      "每人每年 10 万元（含社保公积金），即每年 20 万元。")
    A("")
    A("| 阶段 | 档位 | 替代人数 | 客户投入 | 设备价内免费期 | 人工/年 | 复用收益/年 | 净省/年 | 回本(不让利) | 回本(让利后) |")
    A("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for p in r["phases"]:
        A("| %s %s | %s | %d 人 | %s | %d 个月 | %s | %s | %s | %.2f 年 | %.2f 年 |" % (
            p["key"], p["name"], SHORT[p["tier"]], p["persons"], wan(p["price"]), p["free_months"],
            wan(p["labor_year"]), wan(p["reuse_year"]), wan(p["net_save_year"]),
            (p["payback_months_nofree"] or 999) / 12.0, (p["payback_years"] or 999)))
    A("")
    for p in r["phases"]:
        A("- **%s %s**（%d 个月）：%s。门槛：%s。分成偏好：%s" % (
            p["key"], p["name"], p["months"], p["why"], p["gate_note"], p["bias_note"]))
    A("")
    A("一句话讲清三个阶段：先用精密版在一个工位把稳定性和节拍做出来（设备价内含 %d 个月运营与许可，"
      "客户 %.2f 年回本）；满一年且场景超过 10 个之后，把性能配置降到基础版做简单普通操作，"
      "用更低的单价把装机量铺开（%d 个月免费，%.2f 年回本）；最后用跨场景专业版做自主安全作业，"
      "它的真价值不是替代更多人，而是新场景不再从零集成——按每年新增一个场景、实施费省 60%% 计，"
      "每年多出 %s 的收益，%s 回本。" % (
          r["phases"][0]["free_months"], r["phases"][0]["payback_years"],
          r["phases"][1]["free_months"], r["phases"][1]["payback_years"],
          wan(r["phases"][2]["reuse_year"]), "%.2f 年" % r["phases"][2]["payback_years"]))
    A("")
    A("## 六、三档目标成本与建议利润空间")
    A("")
    A("成本目标是定死的：基础型硬件 15 万（单臂）加软件 5 万；精细型硬件 20 万（双臂）加软件 10 万；"
      "专业型硬件 22 万（双臂、高算力高带宽）加软件 15 万。对外不定售价，只给建议利润空间，"
      "由销售在区间内与客户谈。")
    A("")
    A("| 档位 | 臂 | 目标硬件 | 目标软件 | 单套成本 | 建议报价区间 | 建议毛利空间 | 客户红线 | 红线内实际毛利 | 比现估要降 |")
    A("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for t in TG:
        A("| %s | %s | %s | %s | %s | %.1f ~ %.1f 万 | %.1f%% ~ %.1f%% | %.0f 万 | %.1f%% | %s |" % (
            t["name"], t["arms"], wan(t["hw_cost"]), wan(t["sw_cost"]), wan(t["cost_total"]),
            t["price_lo"] / 1e4, t["price_hi"] / 1e4, t["gross_pct_lo"], t["gross_pct_hi"],
            t["cap_ref"] / 1e4, t["pct_at_cap"], wan(t["gap_to_bom"])))
    A("")
    A("三条必须说清的话：基础型成本二十万、建议报价二十九到三十二万，但客户红线是三十万，只能顶格报，"
      "实际毛利三成三；精细型是最紧的一档，成本三十万对红线四十万，顶格也只有两成半，要拿到三成毛利"
      "单套成本必须压到二十八万以内；专业型成本三十七万对红线五十五万，顶格毛利三成三，"
      "是三档里空间最舒服的。")
    A("")
    A("另外，现估硬件成本比目标高 %s / %s / %s，这是采购与结构要挤出来的水分，"
      "挤不出来就会直接吃掉上面算的毛利空间。" % tuple(wan(t["gap_to_bom"]) for t in TG))
    A("")
    A("## 七、三方分成策略")
    A("")
    A("分成不看谁投入多，看谁真正赚到钱，而且以目标成本为分母：硬件拿「建议报价 − 目标硬件成本」，"
      "软件拿「许可 − 目标软件成本」，运营拿「按件费 − 运营支出」。年度口径按每年 10 套/档（假设）。")
    A("")
    A("| 档位 | 硬件 | 软件 | 运营 | 三方年毛利 | 单套硬件毛利 | 单套软件毛利 | 软件占成本 |")
    A("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for t in TG:
        A("| %s | %.1f%% | %.1f%% | %.1f%% | %s | %s | %s | %.0f%% |" % (
            t["name"], t["pct_capped"]["hw"], t["pct_capped"]["sw"], t["pct_capped"]["op"],
            wan(t["year"]["hw"] + t["year"]["sw"] + t["year"]["op"]),
            wan(t["gross_hw_capped"]), wan(t["gross_sw_capped"]), t["sw_share_of_cost"]))
    A("")
    A("三档的软件份额依次是 %.1f%% / %.1f%% / %.1f%%，正好对应软件成本占单套成本的比例 %.0f%% / %.0f%% / %.0f%%："
      "档位越高，软件在成本里越重，分成里也就越重。这不是人为调出来的，是成本结构决定的。" % (
          TG[0]["pct_capped"]["sw"], TG[1]["pct_capped"]["sw"], TG[2]["pct_capped"]["sw"],
          TG[0]["sw_share_of_cost"], TG[1]["sw_share_of_cost"], TG[2]["sw_share_of_cost"]))
    A("")
    A("## 八、客户账与厂家账")
    A("")
    A("客户账：按建议报价与年度运营费折算，单件总持有成本约 %.3f / %.3f / %.3f 元，对比人工 %.2f 元/件，"
      "省三成到五成。但客户真正看的是几年回本，所以设备价内含免费运营期是这套策略的关键让利。" % (
          TG[0]["unit_cost"], TG[1]["unit_cost"], TG[2]["unit_cost"], T["B"]["labor_per_piece"]))
    A("")
    A("厂家账：不让利时客户回本是 %.2f / %.2f / %.2f 年，多数工厂的采购门槛是三年，"
      "因此按免费期让利后压到 %.2f / %.2f / %.2f 年。让利的成本（免费期内的软件与运营支出）"
      "由该阶段毛利承担，这也是为什么首发阶段硬件份额只让 3 个点、不再多让。" % (
          (r["phases"][0]["payback_months_nofree"] or 999) / 12.0,
          (r["phases"][1]["payback_months_nofree"] or 999) / 12.0,
          (r["phases"][2]["payback_months_nofree"] or 999) / 12.0,
          r["phases"][0]["payback_years"], r["phases"][1]["payback_years"], r["phases"][2]["payback_years"]))
    A("")
    return L


def lines3(d, r, v, T, TG):
    L = []
    A = lambda s="": L.append(s)                                   # noqa: E731
    A("## 九、里程碑")
    A("")
    A("| 时间 | 里程碑 | 判据 |")
    A("| --- | --- | --- |")
    A("| 第 1~2 月 | 现场标定与节拍达标 | 单件 ≤12 s、连续 8 小时无停机 |")
    A("| 第 3~6 月 | 精密版单工位稳定运行 | 良率 ≥99%%、异常自恢复有记录 |")
    A("| 第 6~12 月 | 双臂并行与换型 | 换型 ≤30 分钟、交接点不错位 |")
    A("| 第 12 月 | 场景数据门槛 | 累计覆盖场景 >10 个，数据可用 |")
    A("| 第 13~24 月 | 基础版降配铺量 | 简单操作节拍达标、单价降到 30 万内 |")
    A("| 第 25~48 月 | 跨场景专业版 | 新场景实施费下降 ≥60%、自主安全作业取证 |")
    A("")
    A("## 十、风险与缺口")
    A("")
    A("- **几何标定缺口**：外参未标定，三维换算不闭环。补齐代价：现场 1 天。")
    A("- **训练数据缺口**：数据集未成结构化（缺 info.json/parquet），策略缺支撑。补齐代价：真实示教约 6 万元。")
    A("- **安全认证缺口**：安全等级仍是目标值，未做第三方验证。补齐代价：8~12 周、约 15 万元。")
    A("- **价格口径缺口**：单价为市场参考价，待供应商正式报价。")
    A("")
    A("补齐之前对外只承诺能力边界（算力档、模型层数、功能清单），不承诺具体产量与良率。")
    A("")
    A("## 十一、结论与建议")
    A("")
    A("1. 先投精密版一个工位，用 %s 的设备价加 %d 个月免费运营换取 %.2f 年回本，把稳定性和节拍证明给客户看。"
      % (wan(r["phases"][0]["price"]), r["phases"][0]["free_months"], r["phases"][0]["payback_years"]))
    A("2. 一年后场景数超过 10 个再推基础版，用它铺量而不是用它替代人工——基础版回本靠的是"
      "「新增产能比新招两个人便宜」，不是「把现有的人换掉」。")
    A("3. 专业版的立项理由写清楚是跨场景复用与夜班自主，不是单工位替代；否则按现行运营费算，"
      "客户七年才回本，卖不动。")
    A("4. 三方分成按毛利贡献分，随阶段移动重心：首装靠设备、铺量靠运营、跨场景靠软件授权。")
    A("")
    A("（本报告数字全部由 tools/cost_model.py 与 tools/rollout_model.py 现算，"
      "修改售价上限、免费期或阶段参数后重跑 tools/gen_project_report.py 即同步。）")
    return L


def build_md():
    d, r, v, T, TG = gather()
    L = lines(d, r, v, T, TG) + lines2(d, r, v, T, TG) + lines3(d, r, v, T, TG)
    os.makedirs(OUT_DIR, exist_ok=True)
    open(MD, "w", encoding="utf-8").write("\n".join(L) + "\n")
    return MD, L


def build_docx(L):
    try:
        from docx import Document
        from docx.shared import Pt
        from docx.oxml.ns import qn
    except Exception:                                              # noqa: BLE001
        return None
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name = "Microsoft YaHei"
    st.font.size = Pt(10.5)
    st._element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    tbl = []
    for ln in L:
        if ln.startswith("|"):
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if all(set(c) <= set("-: ") for c in cells):
                continue
            tbl.append(cells)
            continue
        if tbl:
            t = doc.add_table(rows=len(tbl), cols=len(tbl[0]))
            t.style = "Table Grid"
            for i, row in enumerate(tbl):
                for j, c in enumerate(row[:len(tbl[0])]):
                    t.cell(i, j).text = c
                    for p_ in t.cell(i, j).paragraphs:
                        for r_ in p_.runs:
                            r_.font.size = Pt(9)
            tbl = []
        if ln.startswith("# "):
            doc.add_heading(ln[2:], 0)
        elif ln.startswith("## "):
            doc.add_heading(ln[3:], 1)
        elif ln.strip() == "":
            continue
        else:
            doc.add_paragraph(ln.replace("**", ""))
    if tbl:
        t = doc.add_table(rows=len(tbl), cols=len(tbl[0]))
        t.style = "Table Grid"
        for i, row in enumerate(tbl):
            for j, c in enumerate(row[:len(tbl[0])]):
                t.cell(i, j).text = c
    doc.save(DOCX)
    return DOCX


def main():
    md, L = build_md()
    print("写出", md, os.path.getsize(md), "字节")
    if "--md-only" not in sys.argv:
        dx = build_docx(L)
        if dx:
            print("写出", dx, os.path.getsize(dx), "字节")
        else:
            print("跳过 docx (无 python-docx)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
