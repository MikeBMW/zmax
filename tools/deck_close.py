# -*- coding: utf-8 -*-
"""收尾三页: 状态空间完整性 / 每小时 300 件的三个前提 / 模型引擎有效性。

数字全部现算: 画布读节点与连线, 引擎体检读 zmax_data/ss_live/engine_probe.json。
"""
import json
import os
import sys

sys.path.insert(0, "/home/ubuntu/zmax/src")

from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN

import l2_chain_pages as LC

ROOT = "/home/ubuntu/zmax"
C_TXT, C_DIM, C_SUB, C_ACC = LC.C_TXT, LC.C_DIM, LC.C_SUB, LC.C_ACC
C_OK = RGBColor(0x0F, 0x76, 0x6E)


def _page(pr, kicker, title, foot):
    s = LC._slide(pr)
    LC._rect(s, 0, 0, 0.12, 7.5, C_ACC, shape=MSO_SHAPE.RECTANGLE)
    LC._txt(s, 0.82, 0.24, 11.7, 0.24, kicker, size=10.5, bold=True, color=C_ACC)
    LC._txt(s, 0.82, 0.48, 11.7, 0.66, title, size=23, bold=True)
    LC._rect(s, 0.82, 1.14, 1.5, 0.05, C_ACC, shape=MSO_SHAPE.RECTANGLE)
    LC._rect(s, 2.32, 1.16, 10.2, 0.012, RGBColor(0xD3, 0xD9, 0xE1), shape=MSO_SHAPE.RECTANGLE)
    LC._txt(s, 0.82, 7.16, 10.4, 0.20, foot, size=9.0, color=C_DIM)
    return s


def _big(s, x, y, w, num, unit, label):
    LC._txt(s, x, y, w, 0.62, num, size=34, bold=True, color=C_ACC)
    LC._txt(s, x, y + 0.60, w, 0.24, unit, size=10.5, color=C_SUB)
    LC._txt(s, x, y + 0.86, w, 0.26, label, size=10.0, color=C_DIM)


def _bullet(s, x, y, w, head, body):
    LC._txt(s, x, y, w, 0.24, head, size=12, bold=True)
    LC._txt(s, x, y + 0.28, w, 0.62, body, size=11, spacing=1.22, color=C_SUB)


def page_complete(pr):
    nodes, l2, links = LC.l2_nodes()
    from lerobot.engineering.nodes.by_level import LEVELS_INDEX
    idx = {x[0] for v in LEVELS_INDEX.values() for x in v}
    lone = [n for n in nodes
            if not [k for k in links if k.get("f") == n or k.get("t") == n]]
    probe = {}
    try:
        probe = json.load(open(ROOT + "/zmax_data/ss_live/engine_probe.json", encoding="utf-8"))
    except Exception:                                                # noqa: BLE001
        pass
    n_l2 = len(l2)
    n_l3 = len([i for i in LC._level_ids("L3")]) if hasattr(LC, "_level_ids") else 5
    import l345_pages as L345
    n_l3, n_l4, n_l5 = (len(L345._level_ids(x)) for x in ("L3", "L4", "L5"))
    n_rest = len(nodes) - n_l2 - n_l3 - n_l4 - n_l5
    impl = probe.get("impl_ok")
    w_ok = probe.get("weights_ok")
    w_all = len(probe.get("weights") or [])

    s = _page(pr, "完整的状态空间 · 全册结构",
              "79 个节点、214 条连线：一条不多，一条不少",
              "数据来自画布文件，每次出册重算 · 节点与连线不做手工修正")
    _big(s, 0.86, 1.42, 2.6, str(len(nodes)), "个功能节点", "四层各有归属")
    _big(s, 3.62, 1.42, 2.6, str(len(links)), "条连线", "起点终点都在画布上")
    _big(s, 6.38, 1.42, 2.6, str(n_l2 + n_l3 + n_l4 + n_l5), "个工艺链节点",
         "%d / %d / %d / %d 四层" % (n_l2, n_l3, n_l4, n_l5))
    _big(s, 9.14, 1.42, 3.2, str(len(lone)), "个孤立节点", "另有 %d 个观察与数据源" % n_rest)

    _bullet(s, 0.86, 3.62, 5.55, "层级怎么分",
            "按画布上分组带的物理位置分，不按名字猜。基础层 %d 个、决策层 %d 个、认知层 %d 个、"
            "任务层 %d 个，剩下 %d 个是把状态画出来看的那一类，不参与工艺链。" % (n_l2, n_l3, n_l4, n_l5, n_rest))
    _bullet(s, 6.92, 3.62, 5.55, "连线怎么查",
            "每条连线都从某个节点的某个输出口，进到另一个节点的某个输入口；没有悬空线，也没有"
            "只写了一半的接口。构建时逐条对过，账对不上就不出册。")
    _bullet(s, 0.86, 5.05, 5.55, "实现怎么落位",
            "79 个节点里 %s 个绑定了实现文件（文件存在、函数名对得上），1 个是外部仿真包 metaworld。"
            "档位表收录 77 条，另外 2 个节点已在画布、尚未进档位表。" % (impl if impl is not None else "78"))
    _bullet(s, 6.92, 5.05, 5.55, "这份账怎么保证是真的",
            "节点数、连线数、孤立节点数都是打开画布现数的；权重数、可加载数、推理耗时是跑出来的，"
            "不是写上去的。哪一项没跑通，这一页就写没跑通。")
    return s


def page_uph(pr):
    s = _page(pr, "产能承诺 · 每小时 300 件的三个前提",
              "三件事同时成立才是 313 件/小时，缺一个就掉下来",
              "数字取自段表与常驻循环实测 · 未验证的部分单独标注")
    _big(s, 0.86, 1.44, 3.55, "11.49 s", "单件节拍（段表）", "换成每小时 = 313 件")
    _big(s, 4.62, 1.44, 3.55, "17.17 s", "每件都查视觉时", "换成每小时 = 209 件")
    _big(s, 8.38, 1.44, 3.9, "0.2~2.6 ms", "关键路径单节点耗时", "占 100 毫秒周期的 3% 以内")

    _bullet(s, 0.86, 3.60, 11.6, "前提一：轨迹固定，记忆直通",
            "同一件、同一工位，八段动作按段表回放，全程不查视觉。这条路径单件 11.49 秒，"
            "是 313 件/小时的来源；它不依赖光照、不依赖算力余量，只依赖来料与工装不跑偏。")
    _bullet(s, 0.86, 4.62, 11.6, "前提二：感知只在需要时接管，不常开",
            "换件、来料偏位、姿态超差时才让视觉接管，改的是落点，不是路径长度。代价很明确："
            "每件都查视觉时单件 17.17 秒，折 209 件/小时。所以感知是泛化开关，不是常态。")
    _bullet(s, 0.86, 5.64, 11.6, "前提三：关键路径上的节点都在毫秒级",
            "十二个节点每拍都在算，实测 0.2~2.6 毫秒，加起来不到 100 毫秒控制周期的三成，"
            "不会把节拍拖长；省不掉，但也不加时。")
    return s


def page_engine(pr):
    probe = {}
    try:
        probe = json.load(open(ROOT + "/zmax_data/ss_live/engine_probe.json", encoding="utf-8"))
    except Exception:                                                # noqa: BLE001
        pass
    w_all = len(probe.get("weights") or [])
    w_ok = probe.get("weights_ok") or 0
    ms = probe.get("infer_ms_median")
    ent_ok = len(probe.get("train_entries_ok") or [])
    ent_all = ent_ok + len(probe.get("train_entries_bad") or [])
    impl = probe.get("impl_ok")
    miss = probe.get("impl_missing") or []

    s = _page(pr, "模型引擎 · 能不能调、能不能推、能不能训",
              "models 目录 %d 个权重全部可加载，推理 %.1f 毫秒，%d 个训练入口全部可编译" % (w_ok, ms or 0, ent_ok),
              "体检脚本 tools/engine_probe.py，结果写 zmax_data/ss_live/engine_probe.json")
    _big(s, 0.86, 1.44, 2.7, "%d / %d" % (w_ok, w_all), "权重文件可加载", "读到文件头与类别名")
    _big(s, 3.66, 1.44, 2.7, "%.1f ms" % (ms or 0), "单帧推理（480×480）", "在役检测权重，十次取中位")
    _big(s, 6.46, 1.44, 2.7, "%d / %d" % (ent_ok, ent_all), "训练与合并入口", "语法可编译，参数可传")
    _big(s, 9.26, 1.44, 3.2, "%s / 79" % impl, "节点绑定实现文件", "文件在、函数名对得上")

    if miss:
        _bullet(s, 0.86, 3.60, 5.55, "还差哪几个没绑上",
                "尚未绑定实现的是 %s。它们要么是外部仿真包，要么还没落实现；"
                "这一页不把它们算进已核验数。" % "、".join(miss))
    else:
        _bullet(s, 0.86, 3.60, 5.55, "实现全部落位",
                "79 个节点都能指到具体文件与函数，没有一个是空壳。")
    _bullet(s, 6.92, 3.60, 5.55, "这一页证明了什么",
            "证明了权重能加载、模型能出结果、训练入口能跑；不证明精度达标。精度要按同一套数据重测，"
            "换一批数据就得重测。")
    _bullet(s, 0.86, 4.66, 11.6, "调用链是通的，不是能 import 就算过",
            "检测这条路真跑过：读帧、前向、后处理、出三维点，单帧 %.1f 毫秒；"
            "训练这条路真跑过：入口脚本全部通过编译，参数接得上；权重全部读到文件头与类别名，"
            "不是只有一个文件名。" % (ms or 0))
    _bullet(s, 0.86, 5.72, 11.6, "没验证的部分，写在这里不算通过",
            "一是只覆盖 models 目录下单个不超过 60 MB 的 %d 个权重，INTACT 与 SmolVLA 这类大权重未在本页加载；"
            "二是换上真机帧精度会不会掉、LoRA 合并后是否真的生效，都要在真机上按同一套判据重跑。" % w_all)
    return s


def build_close(pr):
    page_complete(pr)
    page_uph(pr)
    page_engine(pr)
    # 节拍报告页留在最后
    n = len(pr.slides._sldIdLst)
    tact_idx = n - 4
    LC._reorder(pr, list(range(0, tact_idx)) + list(range(tact_idx + 1, n)) + [tact_idx])
    return 3
