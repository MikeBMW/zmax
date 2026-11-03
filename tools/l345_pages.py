# -*- coding: utf-8 -*-
"""L3 / L4 / L5 逐层页 —— 层首页 + 逐节点页 (与基础层 30 页同一套版面)。

老倪 2026-11-02: 「继续将 L3 的每个节点，功能描述，输入输出，框图，追加到 PPT，
再追加 L4 的所有节点，最后 L5 的所有节点。你要保证文档的一致性。」
"""
import sys

sys.path.insert(0, "/home/ubuntu/zmax/src")

from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Inches

import l2_chain_pages as LC
import l345_prose as P

C_TXT = LC.C_TXT
C_DIM = LC.C_DIM
C_SUB = LC.C_SUB
C_ACC = LC.C_ACC

# 认知层前几位钉死: 流形引擎第 1, INTACT 意图解码器第 2 (其余保持链路拓扑序)
PIN_HEAD = {"L4": ("ss_mani_eng",      # 1 流形引擎
                   "ssintact_dec",     # 2 INTACT 意图解码器
                   "ss_lora_l4",       # 3 INTACT LoRA 微调
                   "ssmani_exp",       # 4 流形专家预测器
                   "ssmani_c",         # 5 接触流形
                   "ssmani_p")}        # 6 性能流形

LAYER_META = {
    "L3": (P.L3_NAME, "决策层：五个节点把「这一件要做什么」变成一串能执行的动作",
           "这一层不碰像素也不下发动作，只决定顺序、条件与参数。它跑在架构的最前面，"
           "错一步下面全错，所以每个节点的输出都要能在画布上逐段追到。"),
    "L4": (P.L4_NAME, "认知层：十八个节点在低维流形上算意图，给动作一个方向",
           "这一层回答「往哪走、会不会撞、要不要退」。它不产生动作轨迹，只产生意图增量与判据；"
           "轨迹仍然由基础层按段表生成，所以认知层的开销不直接压在单件节拍上。"),
    "L5": (P.L5_NAME, "任务层：十一个节点管这一批做什么，不管这一件怎么动",
           "这一层接工单、读画面、出序列、盯异常、收数据。它按批或按异常触发，"
           "不参与单件循环；它决定的是整批的走向，以及越干越准的数据从哪来。"),
}


def _level_ids(lv):
    from lerobot.engineering.nodes.by_level import LEVELS_INDEX
    nodes, _, links = LC.l2_nodes()
    return [x[0] for x in LEVELS_INDEX[lv] if x[0] in nodes]


NO_PAGE = set()   # 画布已合并这三个节点, 不再需要页级屏蔽   # 配置/汇聚类节点(能力档位·总装记忆中枢): 留在画布与链路里, 不占册子独立页
LC.SKIP_IDS = set(NO_PAGE)           # 模块导入即生效: 基础层 add_block 同样屏蔽


def _ordered(lv, ids, links):
    """层内页序: 链路拓扑序 + PIN_HEAD 钉死前几位 (层首页与逐节点页共用, 两处必须同源)。"""
    order, _, _ = LC.chain_order(set(ids), links)
    order = [x for x in order if x not in NO_PAGE]
    _pinned = [x for x in (PIN_HEAD.get(lv) or ()) if x in order]
    if _pinned:
        order = _pinned + [x for x in order if x not in _pinned]
    return order


def layer_intro_page(pr, lv):
    """层首页: 一句话结论 + 三行要点 + 节点表 (名称 / 负责什么 / 入出条数)。"""
    nodes, _, links = LC.l2_nodes()
    ids = _level_ids(lv)
    order = _ordered(lv, ids, links)
    name_cn, title, summary = LAYER_META[lv]

    s = LC._slide(pr)
    LC._rect(s, 0, 0, 0.12, 7.5, C_ACC, shape=MSO_SHAPE.RECTANGLE)
    LC._txt(s, 0.82, 0.24, 11.7, 0.24, "%s · %d 个节点 · 本层全景" % (name_cn, len(order)),
            size=10.5, bold=True, color=C_ACC)
    LC._txt(s, 0.82, 0.48, 11.7, 0.62, title, size=23, bold=True)
    LC._rect(s, 0.82, 1.14, 1.5, 0.05, C_ACC, shape=MSO_SHAPE.RECTANGLE)
    LC._rect(s, 2.32, 1.16, 10.2, 0.012, RGBColor(0xD3, 0xD9, 0xE1), shape=MSO_SHAPE.RECTANGLE)
    LC._txt(s, 0.82, 1.26, 11.7, 0.62, summary, size=11.5, spacing=1.22, color=C_SUB)

    # 表头
    hy = 2.02
    LC._txt(s, 0.82, hy, 3.60, 0.24, "节点", size=9.4, bold=True, color=C_ACC)
    LC._txt(s, 4.52, hy, 6.90, 0.24, "这个节点负责什么", size=9.4, bold=True, color=C_ACC)
    LC._txt(s, 11.62, hy, 1.30, 0.24, "输入 / 输出", size=9.4, bold=True, color=C_ACC)
    LC._rect(s, 0.82, hy + 0.30, 11.85, 0.014, RGBColor(0xD3, 0xD9, 0xE1), shape=MSO_SHAPE.RECTANGLE)

    rows = order
    top, bottom = hy + 0.42, 6.86
    pitch = min(0.30, (bottom - top) / max(len(rows), 1))
    fs = 9.3 if pitch >= 0.26 else 9.0
    for i, nid in enumerate(rows):
        y = top + i * pitch
        mi = LC._mod_info(nid)[1]
        nm = LC._strip_icon(str(mi.get("NAME") or nodes[nid].get("name") or nid))
        nm = LC._cut(nm.replace("L3 · ", "").replace("L4 · ", "").replace("L5 · ", ""), 22)
        role = (P.PROSE.get(nid) or ("", ""))[0] or ""
        ni = len([k for k in links if k.get("t") == nid])
        no = len([k for k in links if k.get("f") == nid])
        LC._txt(s, 0.82, y, 3.60, pitch, nm, size=fs, bold=True)
        LC._txt(s, 4.52, y, 6.85, pitch, LC._cut(role, 46), size=fs, color=C_TXT)
        LC._txt(s, 11.62, y, 1.30, pitch, "%d / %d" % (ni, no), size=fs, color=C_DIM)
    LC._txt(s, 0.82, 7.16, 10.4, 0.20, "Z-MAX · %s全景 · %d 个节点" % (name_cn, len(order)),
            size=9.0, color=C_DIM)
    return s


def add_layers(pr, layers=("L3", "L4", "L5"), verbose=True):
    """在节拍报告页之前追加 L3/L4/L5 的层首页与逐节点页。"""
    nodes, _, links = LC.l2_nodes()
    n0 = len(pr.slides._sldIdLst)
    tact_idx = n0 - 1                     # 节拍报告页此刻在最后
    made = {}
    for lv in layers:
        ids = set(_level_ids(lv))
        order = _ordered(lv, ids, links)
        layer_intro_page(pr, lv)
        for k, nid in enumerate(order, 1):
            LC.node_page(pr, nid, k, len(order), nodes, ids, links, None, None,
                         layer=LAYER_META[lv][0], prose=P.PROSE, ar=P.AR, uph=P.UPH,
                         skip=NO_PAGE)
        made[lv] = order
        if verbose:
            print("%s %s: %d 个节点页 + 1 层首页" % (lv, LAYER_META[lv][0], len(order)))

    total = len(pr.slides._sldIdLst)
    order_ids = list(range(0, tact_idx)) + list(range(n0, total)) + [tact_idx]
    LC._reorder(pr, order_ids)
    return made
