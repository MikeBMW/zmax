#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_contract_pack.py — 出**供应商要求 SOR (摆盘/插拔 各一份)** + **合作协议** (机器人数据平台提供/销售 ·
解决方案采购)。同一真源渲染 md + docx, 内容块结构唯一 (md 不是第二份真相)。

真源: outputs/config_sheets/配置单_<task>_latest.json · reports/feature_io_test.json ·
      docs/deliverables/两场景验收报告_<ver>.json · engineering_db(capability_dbc/product_features) ·
      config/topics/scene_tags.json · src/lerobot/dataspace/topics.py

用法: gui-venv311/bin/python tools/delivery/gen_contract_pack.py --ver 5.50.5
产物: docs/deliverables/SOR_供应商要求_<场景>_TASK-xx_<ver>.md/.docx
      docs/deliverables/合作协议_机器人数据平台与解决方案_<ver>.md/.docx
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))
DLV = os.path.join(ROOT, "docs", "deliverables")
SCENES = {"TASK-06-TRAY": "摆盘", "TASK-01-FW": "插拔"}


def _j(p, d=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return d


def _topics():
    try:
        from lerobot.dataspace.topics import TOPICS, MODE_DESC, VERSION
        return TOPICS, MODE_DESC, VERSION
    except Exception:  # noqa: BLE001
        return {}, {}, "?"


def _first_rows_from_json(path, n=6):
    d = _j(path, {}) or {}
    for v in d.values():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return v[:n]
    return []


def blocks_sor(task, ver):
    name = SCENES[task]
    sheet = _j(os.path.join(ROOT, "outputs", "config_sheets", "配置单_%s_latest.json" % task), {}) or {}
    st = sheet.get("任务") or {}
    canvas = sheet.get("画布") or {}
    acc = (_j(os.path.join(ROOT, "docs", "deliverables", "两场景验收报告_%s.json" % ver), {}) or {}).get("sections") or {}
    io = _j(os.path.join(ROOT, "reports", "feature_io_test.json"), {}) or {}
    tray, ins, v = acc.get("perf_tray") or {}, acc.get("perf_insert") or {}, acc.get("verdict") or {}
    scn = (_j(os.path.join(ROOT, "config", "topics", "scene_tags.json"), {}) or {}).get("scenes") or []
    colors = {s["task"]: (s["scene"], s["scn"], s["color"]) for s in scn}
    TOPICS, MODE_DESC, TVER = _topics()
    c = sqlite3.connect(os.path.join(ROOT, "data", "database", "zmax", "zmax_engineering.db"))
    caps = list(c.execute("select bo_id, grp, name, dirs, brief, inputs, outputs from capability_dbc"))
    pfs = list(c.execute("select pf_id, title, capability_ref, kpi, status from product_features"))
    B = []
    B.append(("h1", "供应商要求 SOR (Statement of Requirements) · %s作业" % name))
    B.append(("p", "版本: %s　文件编号: SOR-%s-%s　生成: %s" %
              (ver, st.get("SCN") or task, ver.replace(".", ""), time.strftime("%Y-%m-%d"))))
    B.append(("p", "**明确目标 (硬指标)**: 连续动作成功率 **≥99%** · 单件节拍 **≤3.5s** "
                   "(任务目标 ≤3.15s, 3.5s 为硬上限)。未达即不予验收。"))
    B.append(("h2", "1. 项目与场景"))
    B.append(("table", (["项", "要求"], [
        ["任务", "%s (%s)" % (st.get("name"), st.get("task_id"))],
        ["配方", str(st.get("recipe_type"))],
        ["场景/场景号", "%s / %s (色 %s)" % (st.get("场景"), st.get("SCN"), st.get("场景色"))],
        ["站点", str(st.get("site"))],
        ["触发/循环", "%s；%s" % (st.get("trigger"), st.get("loop"))],
        ["适用工序段", " / ".join(st.get("适用段") or [])],
        ["不适用段", " / ".join(st.get("不适用段") or []) or "—"],
        ["工单规则", str(st.get("orders_rule"))],
    ])))
    B.append(("h2", "2. 采购范围与交付分工"))
    B.append(("table", (["交付项", "范围", "责任方", "接口/凭据"], [
        ["机器人本体 + 控制器", "六轴 + 力控 + 末端快换", "供应商", "SDK (珞石 xCore) · 关节/末端状态真值"],
        ["末端执行器", "真空吸盘 (摆盘) / 夹爪 (插拔)", "供应商", "真空建立/断真空 · 夹持状态反馈"],
        ["视觉系统", "全局定位 + 腕部相机 + 标定", "供应商 (标定由甲方提供靶标)", "相机内参 K · 手眼/板坐标系"],
        ["数据平台 (Z-MAX)", "状态空间引擎 + 数据空间 DDS + 记忆层", "平台方", "见 6. 数据平台与接口"],
        ["场景解决方案", "工艺技能编排 / 参数配方 / 集成调试", "平台方 + 供应商", "配置单 · 点位台账 · 判据脚本"],
        ["安全链", "急停/力阈值/关节限位/光幕 (站点级, 任务不可覆盖)", "供应商", "安全回路证书"],
    ])))
    B.append(("h2", "3. 性能指标要求 (可测量, 每项含判据与验证方法)"))
    tg = st.get("targets") or {}
    rows = [["%s" % k, str(v), "按判据脚本实测, 见 §7"] for k, v in tg.items()]
    rows += [["硬指标 成功率", "≥99% (连续 300 颗 0 失效, 95% 置信下限 ≥99%)", "12 盘 × 25 颗连续验收"],
             ["硬指标 节拍", "≤3.5s (目标 ≤3.15s)", "逐颗 CT 计时 (进带→锁/放置完成)"],
             ["取放/插入精度", "单边 ≤1mm · 角度 ≤1° (插拔: 头到孔底 <4mm)", "激光/视觉量测 + 日志"],
             ["过程能力", "真空建立 ≤200ms · 真空保持按配方", "真空压力曲线 (进带→锁)"]]
    B.append(("table", (["指标", "要求值", "验证方法"], rows)))
    B.append(("h2", "4. 场景作业要求 (工艺技能序列)"))
    B.append(("table", (["t(s)", "时长(s)", "工艺技能", "作业要求"], [
        [str(p.get("t")), str(p.get("dur")), str(p.get("name")), str(p.get("desc"))]
        for p in (st.get("工艺步骤") or [])])))
    B.append(("h2", "5. 功能清单与接口要求 (每个功能: 输入 topic / 输出 topic / 性能指标)"))
    B.append(("p", "功能=能力库条目。每个功能有明确输入与输出 topic, 性能指标为该功能的属性 (可测量, 可多功能共用)。"))
    en = {x.get("id") for x in ((canvas.get("启用节点参数") or [])) if x.get("id")}
    fio = {f["id"]: f for f in (io.get("functions") or [])}
    idx = {}
    for f in fio.values():
        for cap in (f.get("cap") or []):
            idx.setdefault(cap, []).append(f)
    rows = []
    for bo, grp, cname, dirs, brief, inputs, outputs in caps:
        hit = [f for f in idx.get(bo, []) if f["id"] in en]
        fo = ", ".join("`%s`" % f["out_topics"][0] for f in hit[:2]) or "—(本场景未调用)"
        fi = ", ".join("`%s`" % t for f in hit[:1] for t in f["in_topics"][:2]) or "—"
        kpi = [p[3] for p in pfs if bo in (p[2] or "") and p[3]]
        rows.append(["%s %s" % (bo, cname), dirs, (brief or "")[:70], fi, fo,
                     "；".join(kpi)[:90] or "见功能实现节点指标",
                     "调用" if hit else "未调用"])
    B.append(("table", (["功能 (能力)", "方向", "功能要求", "输入 topic", "输出 topic", "性能指标 (可测量)", "本场景"], rows)))
    B.append(("h2", "6. 数据平台与接口 (DDS 数据空间)"))
    B.append(("p", "注册话题 %d 个 (注册表 v%s); 模式: %s。每个画布功能节点另有独立输出 topic `ss/<节点id>/out` (89 个)。" %
              (len(TOPICS), TVER, " / ".join("%s=%s" % (k, vv[:14]) for k, vv in MODE_DESC.items()))))
    B.append(("table", (["话题", "类型", "设计 Hz", "QoS", "生产端", "实测"], [
        [k, (x.get("type") or "").split("::")[-1], str(x.get("rate_hz")), str(x.get("qos")),
         str(x.get("producer"))[:52],
         ("✅ %s 条 / %s Hz" % ((io.get("typed") or {}).get(k, {}).get("count"),
                                (io.get("typed") or {}).get(k, {}).get("hz")))
         if (io.get("typed") or {}).get(k, {}).get("ok") else "❌ 本刻无发布端"]
        for k, x in sorted(TOPICS.items())])))
    B.append(("p", "接口纪律: ① 全系统只用一张 DDS 配置 (单播, `AllowMulticast=false` + 显式 Peers), "
                   "禁止默认多播; ② 节点输入 topic 来源必须可追溯到上游功能节点; "
                   "③ 话题缺失/无流量必须在验收报告里如实标注, 不得以「已登记」代替「实测通过」。"))
    B.append(("h2", "7. 验收要求 (99% / 3.5s 的判定口径)"))
    measured = ([("%s s" % x) for x in (v.get("takt", {}) or {}).get("measured_s") or []]
                if task == "TASK-06-TRAY" else ["%.2f s" % (ins.get("t_span_s") or 0)])
    B.append(("table", (["验收项", "判据", "样本量", "通过条件"], [
        ["成功率", "连续 0 失效; 95% 置信下限 ≥99%", "≥300 件 (12 盘 × 25 颗)", "全部通过"],
        ["节拍", "逐件 CT ≤3.5s", "全部件次", "P95 ≤3.5s"],
        ["精度", "单边 ≤1mm / ≤1° (插拔: 头到孔底 <4mm)", "每件", "全部通过"],
        ["功能 topic 输入输出", "逐功能真收发 (收到 ≥ 发出/2)", "全部功能节点", "%d/%d 通过" %
         ((io.get("n_out_ok") or 0), (io.get("n_functions") or 0))],
        ["安全", "急停/力阈值/限位/光幕有效; 授权链路只从授权源", "每次作业", "100%"],
    ])))
    B.append(("p", "本次实测 (供应商须知): 节拍 %s; 取放精度 Δxy ≤%s mm / 姿态 ≤%s°; 插入到位残差 %s mm; "
                   "真空建立 %s ms; 现状缺口已列在验收报告 §9。" %
              (" / ".join(measured),
               max([abs(x.get("dx") or 0) for x in (tray.get("per") or [])] or ["-"]),
               max([x.get("yaw_deg") or 0 for x in (tray.get("per") or [])] or ["-"]),
               ins.get("depth_mm"), (v.get("vacuum") or {}).get("measured_ms"))))
    B.append(("h2", "8. 交付物与文档"))
    B.append(("table", (["交付物", "形式", "说明"], [
        ["本 SOR", "docx + md", "供应商要求, 含功能清单/接口/验收"],
        ["交付文档 (场景)", "docx/md", "工程配置 · 任务配置 · 功能清单 · topic 实测报告"],
        ["配置单", "md + json", "全套参数 (画布/标定/点位/参数注册表)"],
        ["验收报告", "md + json", "目标 vs 实测 vs 判定 + 判据原文"],
        ["功能 topic 输入输出测试报告", "md + json", "逐功能真 DDS 往返实测"],
        ["合作协议", "docx + md", "平台提供/销售 + 解决方案采购"],
    ])))
    B.append(("h2", "9. 待商务/待现场项 (如实列出, 不得默认已达标)"))
    site = st.get("blocked_by_site") or []
    if site:
        B.append(("p", "站位几何未标定: %s ⇒ 坐标类参数不可信, 本 SOR 中坐标类指标以「待实测」计。" % ", ".join(site)))
    B.append(("p", "测试报告与质量评估结论以《验收报告》为准; 现场硬件 (相机/位姿真值/建图) 到位后须复测。"))
    return B


def blocks_agreement(ver):
    acc = (_j(os.path.join(ROOT, "docs", "deliverables", "两场景验收报告_%s.json" % ver), {}) or {}).get("sections") or {}
    v = acc.get("verdict") or {}
    io = _j(os.path.join(ROOT, "reports", "feature_io_test.json"), {}) or {}
    sheet_t = _j(os.path.join(ROOT, "outputs", "config_sheets", "配置单_TASK-06-TRAY_latest.json"), {}) or {}
    sheet_f = _j(os.path.join(ROOT, "outputs", "config_sheets", "配置单_TASK-01-FW_latest.json"), {}) or {}
    B = []
    B.append(("h1", "合作协议 (草案) · 机器人数据平台提供/销售 · 解决方案采购"))
    B.append(("p", "版本: %s　生成: %s　适用产品: Z-MAX 具身智能机器人平台 (Z700 精细操作 / Z100 通用操作)" %
              (ver, time.strftime("%Y-%m-%d"))))
    B.append(("p", "甲方 (采购方/使用方): ____　乙方 (平台与解决方案提供方): ____　"
                   "签约地点/日期: ____ (空白项由商务填写, 本文不预填金额)"))
    B.append(("h2", "第一条 合作标的 (两部分)"))
    B.append(("table", (["部分", "标的", "内容", "形式"], [
        ["一", "机器人数据平台 (提供/销售)", "状态空间引擎 (L2/L3/L4/L5)、数据空间 DDS 总线、记忆层、"
         "能力库与配置中心、诊断/标定工具链、远程查看与升级", "软件许可 (可含源码交付, 取决于商务约定) + 服务"],
        ["二", "场景解决方案 (采购)", "光模块摆盘 / 插拔作业的场景方案: 工艺技能编排、参数配方、"
         "点位台账、标定实施、集成调试、验收与培训", "方案交付 + 现场实施服务"],
    ])))
    B.append(("h2", "第二条 技术指标与验收 (硬指标)"))
    tf = (sheet_t.get("任务") or {}).get("targets") or {}
    ff = (sheet_f.get("任务") or {}).get("targets") or {}
    B.append(("table", (["场景", "成功率", "节拍", "精度", "验收方式"], [
        ["摆盘 TASK-06-TRAY", "≥99% (连续 300 颗 0 失效, 95% 置信下限 ≥99%)", "≤3.5s (目标 %s)" % tf.get("单颗CT"),
         "%s" % tf.get("取放精度"), "同口径判据脚本 + 真跑证据 (报告/JSON)"],
        ["插拔 TASK-01-FW", "≥99%", "≤3.5s (目标 3.15s)", "头到孔底 <4mm · 对位 ≤0.5mm",
         "同口径判据脚本 + episode 真值"],
    ])))
    B.append(("p", "当前实测 (签约前须知的差距): 节拍 %s s (%.2f× 于 3.5s); 成功率证据 %d 次观测 0 失效 "
                   "(95%% 置信下限 %.1f%%, 需 ≥%d 次); 功能 topic 通道 %s/%s 通过。" %
              ((v.get("takt") or {}).get("measured_s"), (v.get("takt") or {}).get("ratio") or 0,
               (v.get("success") or {}).get("n_obs") or 0, ((v.get("success") or {}).get("ci95_lower") or 0) * 100,
               (v.get("success") or {}).get("need_n_for_99") or 0,
               io.get("n_out_ok"), io.get("n_functions"))))
    B.append(("h2", "第三条 交付与里程碑"))
    B.append(("table", (["阶段", "交付内容", "完成判据"], [
        ["M1 方案", "SOR 回应 + 方案设计 (场景/工艺技能/接口)", "SOR 逐条应答"],
        ["M2 集成", "设备与平台联调、标定实施、点位台账", "点位台账 + 标定报告合格"],
        ["M3 验收", "连续 300 颗 (摆盘 12 盘×25) 0 失效 + 逐件 CT ≤3.5s", "验收报告 + 判据脚本输出"],
        ["M4 运维", "远程查看/升级、备件与响应", "SLA 达成记录"],
    ])))
    B.append(("h2", "第四条 价格与支付"))
    B.append(("p", "平台许可费 / 首次实施费 / 年度服务费 / 解决方案采购价格: ____ (商务填写)。"
                   "付款节点建议与 M1–M4 里程碑绑定。"))
    B.append(("h2", "第五条 数据、知识产权与第三方模型"))
    B.append(("table", (["项", "约定"], [
        ["产线数据", "归属甲方; 乙方仅在授权范围内用于调试与训练, 不得外传"],
        ["平台与算法", "平台软件与算法归乙方; 甲方获得约定范围的许可使用权 (可含源码, 取决于商务约定)"],
        ["第三方模型", "按能力库 Manifest + 适配器接入, 能力契约不变; 第三方许可由提供方负责"],
        ["成果数据 (标定/点位/配方)", "随场景交付给甲方, 可复现 (sha256 登记)"],
    ])))
    B.append(("h2", "第六条 安全与运维纪律"))
    B.append(("p", "动作授权只从授权源下发; 急停/力阈值/限位/光幕为站点级, 任务不可覆盖; "
                   "高风险动作须慢速 + 警报在先; 所有下发须有回读确认与台账 (INCIDENT-INDEX)。"))
    B.append(("h2", "第七条 验收争议与复测"))
    B.append(("p", "以同一判据脚本 + 同口径证据复测为准; 环境不具备项 (相机/位姿真值/建图) 须在现场补齐后复测, "
                   "不得以「已登记/已实现」代替实测。"))
    B.append(("h2", "附录 A 交付物清单"))
    B.append(("table", (["交付物", "形式"], [
        ["供应商要求 SOR (摆盘)", "docx + md"], ["供应商要求 SOR (插拔)", "docx + md"],
        ["交付文档 (摆盘/插拔)", "docx/md + json"], ["配置单 (两场景)", "md + json"],
        ["验收报告 + 质量评估结论", "md + json"], ["功能 topic 输入输出实测报告", "md + json"],
        ["全系统配置清单", "md + json"], ["合作协议 (本文件)", "docx + md"],
    ])))
    return B


def render_md(blocks):
    L = []
    for kind, val in blocks:
        if kind == "h1":
            L += ["# %s" % val, ""]
        elif kind == "h2":
            L += ["## %s" % val, ""]
        elif kind == "p":
            L += [val, ""]
        elif kind == "table":
            head, rows = val
            L += ["| " + " | ".join(str(h) for h in head) + " |",
                  "|" + "---|" * len(head)]
            for r in rows:
                L.append("| " + " | ".join(str(x).replace("\n", " ") for x in r) + " |")
            L.append("")
    return "\n".join(L) + "\n"


def render_docx(blocks, path):
    import docx
    from docx.shared import Pt
    d = docx.Document()
    st = d.styles["Normal"]
    st.font.name = "DejaVu Sans"
    st.font.size = Pt(9)
    for kind, val in blocks:
        if kind == "h1":
            d.add_heading(str(val), level=0)
        elif kind == "h2":
            d.add_heading(str(val), level=1)
        elif kind == "p":
            d.add_paragraph(str(val))
        elif kind == "table":
            head, rows = val
            t = d.add_table(rows=1, cols=len(head))
            t.style = "Table Grid"
            for i, h in enumerate(head):
                t.rows[0].cells[i].text = str(h)
            for r in rows:
                cells = t.add_row().cells
                for i, x in enumerate(r[:len(head)]):
                    cells[i].text = str(x)
    d.save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ver", default="v5.50.5")
    a = ap.parse_args()
    os.makedirs(DLV, exist_ok=True)
    made = []
    for task, name in SCENES.items():
        B = blocks_sor(task, a.ver)
        base = os.path.join(DLV, "SOR_供应商要求_%s_%s_%s" % (name, task, a.ver))
        with open(base + ".md", "w", encoding="utf-8") as f:
            f.write(render_md(B))
        render_docx(B, base + ".docx")
        made.append(base)
    B = blocks_agreement(a.ver)
    base = os.path.join(DLV, "合作协议_机器人数据平台与解决方案_%s" % a.ver)
    with open(base + ".md", "w", encoding="utf-8") as f:
        f.write(render_md(B))
    render_docx(B, base + ".docx")
    made.append(base)
    for m in made:
        print("→ %s.md (%d B) + .docx (%d B)" %
              (m, os.path.getsize(m + ".md"), os.path.getsize(m + ".docx")))


if __name__ == "__main__":
    main()
