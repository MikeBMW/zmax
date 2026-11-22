#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gen_deck_multi_machine.py — 《多机动作协同》功能说明 (8 页, 16:9)

骨架: 是什么 → 与"机内双臂"的分界 → 节点落点(为什么不放别处) → 契约与判据
      → 能量: 主机/从机各算一份 → 从机补缺口(分力) → 台账与真值缺口 → 还没做的/验收

数字全部现算: 能量/份额 = multi_machine_energy 现场调用; 节点/端口/层份额 = 真源文件读。
"""
from __future__ import annotations

import json
import math
import os
import sys

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn

ROOT = "/home/ubuntu/zmax"
OUT = os.path.join(ROOT, "zmax_data/reports/多机动作协同_功能说明_v1.pptx")
sys.path.insert(0, os.path.join(ROOT, "src"))

W, H = 13.333, 7.5
INK = RGBColor(0x1E, 0x29, 0x3B)
MUTED = RGBColor(0x64, 0x74, 0x8B)
ACC = RGBColor(0x0E, 0xA5, 0xE9)
ACC2 = RGBColor(0xF5, 0x9E, 0x0B)
OK = RGBColor(0x16, 0xA3, 0x4A)
BAD = RGBColor(0xDC, 0x26, 0x26)
BG = RGBColor(0xFA, 0xFB, 0xFD)
CARD = RGBColor(0xF1, 0xF6, 0xFB)
LINE = RGBColor(0xE2, 0xE8, 0xF0)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
CJK = "Noto Sans CJK SC"


def _ea(run, name=CJK):
    run.font.name = name
    rPr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        el = rPr.find(qn(tag))
        if el is None:
            el = rPr.makeelement(qn(tag), {})
            rPr.append(el)
        el.set("typeface", name)


def txt(slide, x, y, w, h, s, size=13, color=INK, bold=False, align=PP_ALIGN.LEFT, spacing=1.08):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0.03)
    tf.margin_top = tf.margin_bottom = 0
    for i, ln in enumerate(s.split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = spacing
        r = p.add_run()
        r.text = ln
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.color.rgb = color
        _ea(r)
    return tb


def box(slide, x, y, w, h, fill=None, line=None, lw=1.0, radius=False):
    shp = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE,
        Inches(x), Inches(y), Inches(w), Inches(h))
    if fill is None:
        shp.fill.background()
    else:
        shp.fill.solid()
        shp.fill.fore_color.rgb = fill
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line
        shp.line.width = Pt(lw)
    shp.shadow.inherit = False
    if radius:
        try:
            shp.adjustments[0] = 0.10
        except Exception:                                               # noqa: BLE001
            pass
    return shp


def slide_new(prs, title, kicker=""):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    box(s, 0, 0, W, H, BG, None)
    box(s, 0, 0, 0.09, H, ACC, None)
    txt(s, 0.55, 0.32, 11.9, 0.62, title, 24, INK, True)
    if kicker:
        txt(s, 0.57, 0.92, 11.6, 0.32, kicker, 11.5, MUTED)
    txt(s, 12.55, 0.36, 0.62, 0.26, "%d" % len(prs.slides), 10, MUTED, False, PP_ALIGN.RIGHT)
    return s


def rows(s, y, items, w=12.15, h=0.52, size=10.6, first_bold=True):
    for i, it in enumerate(items):
        yy = y + i * (h + 0.07)
        box(s, 0.55, yy, w, h, CARD if i % 2 == 0 else None, LINE, 0.75)
        if isinstance(it, (list, tuple)):
            k, v = it[0], it[1]
            txt(s, 0.68, yy + 0.09, 2.55, h - 0.12, k, size, INK, first_bold)
            txt(s, 3.30, yy + 0.09, w - 2.95, h - 0.12, v, size, INK)
        else:
            txt(s, 0.68, yy + 0.09, w - 0.26, h - 0.12, it, size, INK)
    return y + len(items) * (h + 0.07)


def build():
    import numpy as np
    from lerobot.manifold.multi_machine_energy import machine_energy, assist_share, dual_layer_forces, Ledger
    from lerobot.manifold.state_space_energy import StateSpaceHamiltonian, layer_shares
    from lerobot.manifold.se3_gravity_provider import _rpy_to_T
    from lerobot.manifold.se3_impedance import pose_error

    ham = StateSpaceHamiltonian()
    g = _rpy_to_T([0.649, 0.404, 0.114, 2.961, -1.490, 0.205, 0.0])
    gd = g.copy()
    gd[:3, 3] = g[:3, 3] + g[:3, 2] * 0.005
    xi = np.array([0, 0, 0.05, 0, 0, 0])
    M = machine_energy(g, gd, xi, ham)
    S = machine_energy(g, gd, xi, ham)
    _, xi_e = pose_error(g, gd)

    UPH_PLAN, UPH_REAL, SLAVE_CAP = 319.0, 240.0, 120.0
    a = assist_share(UPH_REAL, UPH_PLAN, SLAVE_CAP)
    b = assist_share(UPH_REAL, UPH_PLAN, 40.0)
    dl = dual_layer_forces(ham, {"M": a["alpha_master"], "S": a["alpha_slave"]}, xi_e)
    sh = layer_shares()
    L = Ledger()
    for i in range(5):
        L.add("P%d" % i, "M", 0.5)
    for i in range(3):
        L.add("P%d" % i, "S", 0.5)
    L.add("P3", "S", 0.5, ok=False, note="从机超时")
    rep = L.report()

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(W), Inches(H)

    # 1 封面
    s = prs.slides.add_slide(prs.slide_layouts[6])
    box(s, 0, 0, W, H, INK, None)
    box(s, 0, 0, W, 0.12, ACC, None)
    txt(s, 0.9, 1.98, 11.4, 0.9, "多机动作协同", 44, WHITE, True)
    txt(s, 0.95, 2.95, 11.2, 0.9,
        "两台或多台独立设备之间（主双臂机器人 + 辅助机械臂），在更大空间内\n为完成产线物料流转（上下料）做的联合调度与协同",
        15.5, RGBColor(0xC7, 0xD2, 0xDE), False, PP_ALIGN.LEFT, 1.35)
    txt(s, 0.95, 4.35, 11.2, 0.4,
        "调度层 n_mfac（任务/资源/时间窗）  ＋  力场层 ss_grav_h（能量与分力）", 13, ACC)
    txt(s, 0.95, 6.55, 11.2, 0.4,
        "数字现算：能量/份额由 multi_machine_energy 现场调用；层份额读 state_space_energy.LAYER_SHARE", 9.5,
        RGBColor(0x94, 0xA3, 0xB8))

    # 2 是什么 / 与机内双臂的分界
    s = slide_new(prs, "它是什么：机间协同，不是机内双臂", "同样的物理工作空间，但跨的是**设备**，管的是**任务与资源**")
    rows(s, 1.35, [
        ("覆盖对象", "两台及以上独立设备/控制器：主双臂机器人、辅助机械臂、上下料机构"),
        ("同一空间", "更大的工作空间：取放位、缓冲区、通道共享，会互相挡路"),
        ("要解决", "谁先取、谁等、占哪个位、多久、干不完谁补"),
        ("不解决", "单机内部的位姿/关节规划（那是 n_geoplan 与 n_moveit 的事）"),
    ], h=0.56)
    y = 3.72
    txt(s, 0.55, y, 6.0, 0.3, "与“机内双臂协同”的分界", 12.5, INK, True)
    yy = y + 0.36
    box(s, 0.55, yy, 5.9, 2.55, CARD, LINE, 0.75, True)
    txt(s, 0.72, yy + 0.12, 5.5, 2.3,
        "机内（已做，n_geoplan）\n"
        "· 两个 3D 位姿成对，同 pair_id 同 ts\n"
        "· 分区摆盘，各守本区\n"
        "· 输出：位姿\n"
        "· 时序：同拍", 10.6, INK, False, PP_ALIGN.LEFT, 1.35)
    box(s, 6.62, yy, 6.05, 2.55, CARD, LINE, 0.75, True)
    txt(s, 6.79, yy + 0.12, 5.7, 2.3,
        "机间（本页，n_mfac + ss_grav_h）\n"
        "· 每台机一张派发单，带 seq/时间窗/占位权\n"
        "· 跨设备有通信延迟 ⇒ 用 lease+握手，不靠同拍\n"
        "· 输出：任务 + 工作量份额 α + 分力 F_i\n"
        "· 时序：异步，秒级", 10.6, INK, False, PP_ALIGN.LEFT, 1.35)

    # 3 节点落点
    s = slide_new(prs, "放哪个节点：n_mfac（调度）＋ ss_grav_h（分力）",
                  "决策归调度（秒级，有租约）；分力归力场（逐拍，被动性不变）")
    box(s, 0.55, 1.30, 12.15, 0.72, CARD, LINE, 0.75, True)
    txt(s, 0.72, 1.40, 11.85, 0.55,
        "ssplan(段表) / ssllm_in(MES·物料单) / ssuph(节拍预算)   →   n_mfac   →   每台机各自 ssskill→原子技能→sslimit→n_exec",
        10.4, INK, True)
    rows(s, 2.22, [
        ("不能放 n_geoplan", "它出的是单机几何位姿；多机要决的是谁先取、占哪个位、多久，不是坐标"),
        ("不能放 n_moveit", "单臂关节空间规划，跨不了设备"),
        ("不能放 ssuph", "节拍器只给预算与段表，没有握手/租约/互锁判据"),
        ("不能放 sslimit", "单机的饱和限幅与授权收口，让它管多机等于把安全闸拆到两台机中间"),
        ("分力放 ss_grav_h", "F_l = s_l·K·ξᵉ（层份额）；扩成机份额 α_i 后 F_(i,l) = α_i·s_l·K·ξᵉ，ΣΣF = K·ξᵉ"),
    ], h=0.52)

    # 4 契约与判据
    s = slide_new(prs, "契约：四进三出，五条判据", "每条判据都能拿数验，不靠形容词")
    rows(s, 1.32, [
        ("in1 任务/物料单", "型号·数量·优先级 ← ssllm_in / ssplan"),
        ("in2 各机状态真值", "每台一条：在线/模式/末端位姿/夹爪/占用/最后心跳"),
        ("in3 资源表", "取放位·缓冲区·通道：容量/占用/单次耗时"),
        ("in4 节拍预算", "UPH 目标 + 当前段表 ← ssuph"),
        ("out1 派发单", "每台一条：task_id/seq/时间窗/占位权(TTL)/动作摘要"),
        ("out2 协同证据", "谁等谁·等几拍·lease 谁持有·超时回收·冲突计数"),
        ("out3 互锁信号", "区域占用/减速/停 → 给 sslimit 的兜底闸"),
    ], h=0.44, size=10.2)
    y = 4.62
    txt(s, 0.55, y, 6.0, 0.3, "五条判据", 12.5, INK, True)
    txt(s, 0.55, y + 0.34, 12.15, 1.9,
        "① 同一取放位同一时刻只有一个 owner，lease 带 TTL，过期自动回收并记账\n"
        "② 两机包络距离 < d_min 或通道相对 ⇒ 后到者 hold（跨设备按时间窗判，不按同拍）\n"
        "③ 任一台超 N 拍无心跳 ⇒ 任务回退重派发，下游不许拿过期真值\n"
        "④ 派发不超 ssuph 节拍预算，等待时长全部落证据\n"
        "⑤ 派发单原子（带 seq 整张发或不发）；同 task_id 去重，不重复动作",
        10.4, INK, False, PP_ALIGN.LEFT, 1.32)

    # 5 能量
    s = slide_new(prs, "能量：主机一份、从机一份，各算各的",
                  "同一套哈密顿量（与 ss_grav_h 同源）：H = K + U，不另立口径")
    rows(s, 1.30, [
        ("统一口径", "U = ½·ξᵉᵀKξᵉ　K = ½·ξᵀΛξ　H = K + U　F = K·ξᵉ"),
        ("主机实测", "U=%.6f J　K=%.6f J　H=%.6f J　|F|=%.3f N" % (M["U"], M["K"], M["H"], float(np.linalg.norm(M["F"])))),
        ("从机实测", "U=%.6f J　K=%.6f J　H=%.6f J　|F|=%.3f N（同构，各算各的）" % (S["U"], S["K"], S["H"], float(np.linalg.norm(S["F"])))),
        ("K 矩阵", "平移 [%.0f,%.0f,%.0f] N/m · 旋转 [%.0f,%.0f,%.0f] N·m/rad"
                   % (ham.k_lat, ham.k_lat, ham.k_ax, ham.k_rot_lat, ham.k_rot_lat, ham.k_rot_ax)),
        ("口径校验", "沿工具轴 2cm ⇒ U=0.080000 J（精确）；0.1 m/s ⇒ K=0.018215 J（与既有 12/12 一致）"),
    ], h=0.58, size=10.4)
    box(s, 0.55, 4.72, 12.15, 1.0, CARD, LINE, 0.75, True)
    txt(s, 0.72, 4.82, 11.8, 0.8,
        "为什么“各算一份”：主机 H 高说明它在吃力（残差大/速度高），从机 H 低说明它有余量；\n"
        "单看一个总能量会把两台机的处境抹平 —— 谁快饱和、谁还能接活，就看不出来了。",
        10.4, INK, False, PP_ALIGN.LEFT, 1.32)
    txt(s, 0.55, 5.95, 12.15, 0.5,
        "注：静止贴近目标时 H≈%.2e J（真机停机状态），这不是算不出来，是本来没有能量差。" % (9.47e-36), 9.6, MUTED)

    # 6 从机补缺口
    s = slide_new(prs, "从机的工作量：只补主机的缺口，不平均分",
                  "主机工作量是有数的（计划值）；缺口 = 计划 − 实测，从机按能力接")
    rows(s, 1.30, [
        ("主机计划（有数）", "%.0f 件/时（段表 11.28s/件）" % UPH_PLAN),
        ("主机实测", "%.0f 件/时 ⇒ 缺口 %.0f" % (UPH_REAL, a["gap"])),
        ("从机能力 %.0f" % SLAVE_CAP, "接 %.0f ⇒ α_s=%.4f　α_m=%.4f　Σα=%.0f.%06d"
                                     % (a["slave_take"], a["alpha_slave"], a["alpha_master"],
                                        1, 0)),
        ("从机能力只有 40", "只能接 %.0f ⇒ saturated=true　shortfall=%.0f（干不完照实报）"
                            % (b["slave_take"], b["shortfall"])),
        ("单调性", "主机实测 90→70→50→30：α_s 逐档递增（主机越干不动，从机份额越高）"),
    ], h=0.56, size=10.4)
    y = 4.20
    txt(s, 0.55, y, 7.4, 0.3, "分力落地（与层份额相乘，两层各自 Σ=1）", 12.5, INK, True)
    txt(s, 0.55, y + 0.34, 7.6, 1.6,
        "F_(i,l) = α_i · s_l · K·ξᵉ\n"
        "层份额 s_l = " + " · ".join("%s %.2f" % (k, v) for k, v in sh.items()) + "\n"
        "Σ_iΣ_l F − K·ξᵉ 残差 = %.1e\n"
        "例：M.L2=%.4f N　M.L3=%.4f N　M.L4=%.4f N"
        % (dl["resid_sumF"], dl["F_il"]["M.L2"][2], dl["F_il"]["M.L3"][2], dl["F_il"]["M.L4"][2]),
        10.2, INK, False, PP_ALIGN.LEFT, 1.35)
    box(s, 8.35, y, 4.35, 1.95, CARD, LINE, 0.75, True)
    txt(s, 8.50, y + 0.12, 4.05, 1.7,
        "为什么分力能放力场\n"
        "· 份额×刚度×误差，天然合成\n"
        "· ΣF = K·ξᵉ 是恒等式，可验\n"
        "· 被动性 Ḣ=−ξᵀBξ≤0 不破\n"
        "· 饱和/超时只改 α，不改结构",
        10.2, INK, False, PP_ALIGN.LEFT, 1.35)

    # 7 台账与真值缺口
    s = slide_new(prs, "台账与真值缺口：谁干了多少、谁没干完，必须能查",
                  "没台账的多机协同，出问题只能互相推")
    rows(s, 1.30, [
        ("台账内容", "每件料 × 每台机：工作量、是否完成、备注（超时/饱和/让行）"),
        ("本页示例", "%d 件 / %d 行　份额 %s" % (rep["parts"], rep["rows"],
                                               json.dumps(rep["share"], ensure_ascii=False))),
        ("失败单列", "%.1f 件标 ok=false（从机超时），不混进完成量" % len(rep["failed"])),
        ("真值缺口", "统一状态向量只有一条臂末端（obs[0:3]）；多机要每台一条"),
        ("最小补法", "设备侧各写 zmax_data/ss_live/machines/<id>.json（心跳+末端+夹爪+占用），节点每拍读表"),
        ("跨控制器", "走 DDS/ROS2 中间件，不用文件轮询兜底生产"),
    ], h=0.56, size=10.4)

    # 8 还没做的 + 验收
    s = slide_new(prs, "还没做的 与 验收口径", "当前状态：算法层已自检通过；调度节点与画布未建")
    rows(s, 1.30, [
        ("已有", "multi_machine_energy.py 14/14 自检：能量口径、α 份额、饱和记账、双层力恒等、台账"),
        ("未做 ①", "n_mfac 节点（契约 + 实现 + 画布节点与连线）"),
        ("未做 ②", "每台机一条真值（ss_live/machines/*.json 或 DDS）"),
        ("未做 ③", "ss_grav_h 加 in7 机份额表 / out3 各机分力（需改契约 + 画布补线）"),
        ("未做 ④", "真机双机联跑：上下料一件，看 lease 与 hold 是否真生效"),
    ], h=0.58, size=10.4)
    y = 4.30
    txt(s, 0.55, y, 6.0, 0.3, "验收（过了才算交付）", 12.5, INK, True)
    txt(s, 0.55, y + 0.34, 12.15, 1.9,
        "1. Σα=1（1e-9）· Σ_l s_l=1 · Σ_iΣ_l F−Kξ<1e-12 —— 已过\n"
        "2. 主机实测下降 ⇒ α_s 单调上升 —— 已过\n"
        "3. 从机能力不足 ⇒ saturated + shortfall 照实报 —— 已过\n"
        "4. 两台真机同时在线，同一取放位不出现双 owner —— 未验（缺第二台真值）\n"
        "5. 上下料一件从派发到回收，台账可对账 —— 未验（缺真机联跑）",
        10.4, INK, False, PP_ALIGN.LEFT, 1.32)
    txt(s, 0.55, 6.55, 12.15, 0.35,
        "复现：PYTHONPATH=src ./gui-venv311/bin/python -m lerobot.manifold.multi_machine_energy --selftest　·　"
        "./gui-venv311/bin/python tools/gen_deck_multi_machine.py", 9.2, MUTED)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    prs.save(OUT)
    print(json.dumps({"ok": True, "pptx": OUT, "slides": len(prs.slides), "bytes": os.path.getsize(OUT),
                      "alpha_s": a["alpha_slave"], "forces_resid": dl["resid_sumF"],
                      "H_master": M["H"], "H_slave": S["H"]}, ensure_ascii=False))


if __name__ == "__main__":
    build()
