#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deck_55d_revise.py — 把 5.50.D-M2 技术手册改成 55D 版 (M3)

做四件事, 每件都可复核:
  ① 全局口径替换   43 维/43D/四十三维 → 55 维/55D/五十五维 (含"视觉39+触觉4"补上"+预留12")
  ② 重写 4.03      「55 维观测：视觉 39 + 触觉 4 + 预留 12」
  ③ 扩 4.19 表格   加一行 obs[43:55] 预留扩展 (零初始化)
  ④ 新增 5 页      4.03a 分段表 / 4.03b 零扰动升级 / 4.03c 数值边界 / 4.03d 主从异步 / 6.10 验收
     克隆 4.03 那页的版式 (纯文本框), 保证字体/配色/页脚与全册一致
  ⑤ 版本与页码     5.50.D-M2 → 5.50.D-M3; 封面页数; 右下列页码按最终顺序重编

用法: python tools/deck_55d_revise.py [--src ...] [--out ...]
"""
from __future__ import annotations

import argparse
import copy
import os
import time

from pptx import Presentation
from pptx.oxml.ns import qn

ROOT = os.environ.get("ZMAX_ROOT", "/home/ubuntu/zmax")
SRC = os.path.join(ROOT, "zmax_data/deliverables/20261104/"
                         "Z-MAX以世界模型为核心的状态空间工程_5.50.D-M2.pptx")
OUT = os.path.join(ROOT, "zmax_data/deliverables/20261105/"
                         "Z-MAX以世界模型为核心的状态空间工程_5.50.D-M3.pptx")

REPL = [
    # 先处理带"视觉39+触觉4"的长串, 否则会被短规则吃掉
    ("43 维观测（视觉39 + 触觉4）", "55 维观测（视觉39 + 触觉4 + 预留12）"),
    ("43D 观测（视觉39 + 触觉4）", "55D 观测（视觉39 + 触觉4 + 预留12）"),
    ("43D obs：视觉39 + 触觉4", "55D obs：视觉39 + 触觉4 + 扩展12"),
    ("43D obs", "55D obs"),
    ("43 维", "55 维"),
    ("43D", "55D"),
    ("43维", "55维"),
    ("四十三维", "五十五维"),
]


def iter_text_frames(shapes):
    for sh in shapes:
        if sh.shape_type == 6 or getattr(sh, "shapes", None) is not None:      # group
            try:
                yield from iter_text_frames(sh.shapes)
                continue
            except Exception:                                                   # noqa: BLE001
                pass
        if sh.has_text_frame:
            yield sh.text_frame
        if getattr(sh, "has_table", False) and sh.has_table:
            for r in sh.table.rows:
                for c in r.cells:
                    yield c.text_frame


def replace_in_tf(tf, pairs) -> int:
    n = 0
    for p in tf.paragraphs:
        for r in p.runs:
            old = r.text
            new = old
            for a, b in pairs:
                new = new.replace(a, b)
            if new != old:
                r.text = new
                n += 1
    return n


def tf_set(tf, lines) -> None:
    """整段重写, 保留原段落的 pPr 与首个 run 的 rPr (字体/字号/颜色不变)。"""
    p0 = tf.paragraphs[0]._p
    pPr = p0.find(qn("a:pPr"))
    rPr = None
    for r in p0.findall(qn("a:r")):
        x = r.find(qn("a:rPr"))
        if x is not None:
            rPr = copy.deepcopy(x)
        break
    body = tf._txBody
    for p in list(body.findall(qn("a:p"))):
        body.remove(p)
    for ln in lines:
        p = body.makeelement(qn("a:p"), {})
        if pPr is not None:
            p.append(copy.deepcopy(pPr))
        r = body.makeelement(qn("a:r"), {})
        if rPr is not None:
            r.append(copy.deepcopy(rPr))
        t = body.makeelement(qn("a:t"), {})
        t.text = ln
        r.append(t)
        p.append(r)
        body.append(p)


def clone_slide(prs, src_idx: int):
    src = prs.slides[src_idx]
    new = prs.slides.add_slide(src.slide_layout)
    for sh in list(new.shapes):                     # 清掉占位符
        sh._element.getparent().remove(sh._element)
    sp_tree = new.shapes._spTree
    for el in src.shapes._spTree.iterchildren():
        tag = el.tag
        if tag.endswith("}nvGrpSpPr") or tag.endswith("}grpSpPr"):
            continue
        sp_tree.append(copy.deepcopy(el))
    return new


def move_slide_to(prs, from_idx: int, to_idx: int) -> None:
    lst = prs.slides._sldIdLst
    ids = list(lst)
    el = ids[from_idx]
    lst.remove(el)
    lst.insert(to_idx, el)


def shape_by_text(slide, needle: str):
    for sh in slide.shapes:
        if sh.has_text_frame and needle in sh.text_frame.text:
            return sh
    return None


def set_pagenum(slide, n: int) -> None:
    for sh in slide.shapes:
        if not sh.has_text_frame:
            continue
        t = sh.text_frame.text.strip()
        if t.isdigit() and sh.left is not None and sh.left > 11.4 * 914400 and sh.top > 6.5 * 914400:
            tf_set(sh.text_frame, [str(n)])
            return


# ── 新页内容 (与全册同一口径: 结论在前 + 数字 + 底部一句话) ───────────────────────
PAGES = {
    ("4.03", "a"): (
        "55D 分段：19 段，每一段都有名字、单位、来源",
        ["▪ 视觉与本体 0:39（10 段）  tcp_p(3) · 夹爪标量(1) · 工件xyz(3) · 相对位移(3) · 夹爪两维(2) · 关节角(6) · 关节速(6) · TCP旋转(9) · 目标位(3) · 孔位(3)",
         "▪ 触觉力觉 39:43（4 段）  grasp · contact · dir_x · dir_y —— 语义与升级前一字不动，老标定直接可用。",
         "▪ 预留扩展 43:55（5 段）  多指触觉阵列(4) · 温度(1) · 声学(1) · 电流(2) · 备用(4)，单位与来源写进分段表。",
         "▪ 取数规则  一律按名取（unified_state55.SLICE），禁止消费端自己数下标；分段表自身有判据：19 段首尾相接覆盖 0:55，断档或重名直接抛错。",
         "▪ 字段表可直接导出  同一张表同时喂页面、接口文档与训练脚本，避免三处各写一套。"],
        "为什么每个扩展通道都要有名字：匿名维三个月后就没人敢用——升级不是把 55 填满，而是把接口一次定死。"),
    ("4.03", "b"): (
        "43→55 零扰动升级：前 43 维逐位不变，12 维沉睡",
        ["▪ 三条硬约束  ① 前 43 维语义不动（老权重/老数据/老标定原样可用）② 新增 12 维在编码器里是 0 行，升级瞬间输出不变 ③ 每个扩展维有名字/单位/来源。",
         "▪ 数学依据  (x₅₅ − [μ₄₃,0]) ⊗ [W₄₃; 0ᵀ] = (x₄₃ − μ₄₃) ⊗ W₄₃ —— 是恒等，不是“差不多”。",
         "▪ 实测（verify_state55.py · 七组判据全 PASS）  前 43 维逐位相同=True；43 维引擎 vs 55 维引擎 z 最大差 0.0；扩展维填 ±100 随机数，z 差 0.0。",
         "▪ 老轨迹回填  在役轨迹仍是 43 维，读入时尾部补 0 并记 obs_dim_from=43；不因“维度不够”空转（这坑真踩过：重启后引擎空转 5 分钟）。",
         "▪ 觉醒路径  先加通道 → 采到真数据 → 只训新增 12 维的行（冻结前 43 维）→ 门禁对比 → 才允许进默认档。"],
        "升级的正确姿势是加法：先证不扰动，再谈提升；任何“升级即重训”的方案都不可回滚。"),
    ("4.03", "c"): (
        "流形引擎的数值边界：测地线与 SLERP 三处会炸的地方",
        ["▪ 测地线距离  用 2·atan2(‖v‖,|w|)，不用 2·acos(⟨q1,q2⟩)：后者在 q1≈q2 处导数发散。",
         "▪ 实测对照  q1=q2 时：atan2 形式梯度 0.0（有限）；acos 形式梯度 NaN —— 训练第一步就会炸。",
         "▪ SLERP 两个退化分支  θ→0（同姿态）取线性插值极限；θ→π（对跖）先取反 q_target 走短弧，否则系数爆炸。",
         "▪ 禁止用 where 掩盖已除零的支路  NaN 会经 0×NaN 传回梯度；正确做法是先把 θ 换成 atan2 形式、分母先加 eps 再除。",
         "▪ 验收数字  SLERP 三分支（同姿态/对跖/90°）梯度全有限，中点 ‖q‖=1（1e-7 内）；对跖分支输出等于起点，符合“走短弧=零位移”的物理含义。"],
        "这些不是理论洁癖：三条都是实测炸过的位置，写进代码就是护栏，写进手册才是可复制的经验。"),
    ("4.03", "d"): (
        "主从异步：L5 主节点，L2-L4 从节点，10 ms 拍不被阻塞",
        ["▪ 路由  L5 用交叉注意力把全局任务分给各层；L2/L3/L4 只做特征转换（MLP 联络层），不反向改任务——上层只给意图与条件，执行由底层收口。",
         "▪ 通信  L5→底层走序列化指令（低频，分钟级）；底层 L2→L5 走共享内存零拷贝（高频，10 ms 拍）。",
         "▪ 节拍账  引擎单拍实测 1.5~2.9 ms；L4 视觉编码 1124 ms/次 在独立线程按 1 Hz 跑，不入拍（入了就是 100 ms 拍）。",
         "▪ 睡眠清洗  L5 离线跑：失败样本入库 → 增量训练 → 门禁 → 候选权重；人只在否决位，脚本不碰在役权重。",
         "▪ 失败处理  任一层超时只降级本层（w=0 / 回解析链），不链式阻塞——异步的前提是“谁都不等谁”。"],
        "任何一个环节同步等待，10 ms 拍立刻变成 100 ms；分层不是画着好看，是把等待从关键路径上挪走。"),
    ("6.09", "e"): (
        "55D 升级验收：七组判据全 PASS（可复核）",
        ["▪ 布局  19 段 / 55 维 / 首尾相接覆盖 0:55（validate_layout 通过，重名或断档直接抛错）。",
         "▪ 融合  39+4+12 → 55；前 43 维与 43D 老口径逐位相同（float64 全等，不是近似）。",
         "▪ 引擎  43 维 vs 55 维 z 最大差 0.0；扩展维填 ±100 随机数，z 差 0.0（零行初始化 ⇒ 沉睡语义成立）。",
         "▪ 数值  测地线 atan2 梯度 0.0 对 acos 渐变 NaN；SLERP 三分支梯度全有限，中点 ‖q‖=1。",
         "▪ 回归  fuse_sensors() 默认仍 43（在役 L3/L4 权重口径不变）；新链路显式走 fuse_sensors55()。",
         "▪ 证据  tools/verify_state55.py · reports/state55/*.json · 引擎台账 state_dim=55 / calib_pad 43→55。"],
        "升级的验收不是“跑起来了”，是“老系统逐位不变 + 新通道可插可验”。"),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=SRC)
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()
    prs = Presentation(a.src)
    n0 = len(prs.slides)

    # ① 全局口径
    hits = 0
    for s in prs.slides:
        for tf in iter_text_frames(s.shapes):
            hits += replace_in_tf(tf, REPL)
    print("① 口径替换: %d 处" % hits)

    # ② 重写 4.03
    s403 = None
    for s in prs.slides:
        if shape_by_text(s, "4.03") is not None and shape_by_text(s, "维观测：视觉结构"):
            s403 = s
            break
    if s403 is None:
        raise SystemExit("找不到 4.03 页")
    title = shape_by_text(s403, "维观测：视觉结构")
    tf_set(title.text_frame, ["55 维观测：视觉 39 + 触觉 4 + 预留 12"])
    body = [sh for sh in s403.shapes if sh.has_text_frame and len(sh.text_frame.text) > 200][0]
    tf_set(body.text_frame, [
        "▪ 为什么是 55  18 维当前状态 + 18 维上一帧 + 3 维阶段目标 = 39；加夹爪/接触 4 维触觉 = 43；再加 12 维预留扩展 = 55。",
        "▪ 12 维预留不是占位  多指触觉阵列 4 · 温度 1 · 声学 1 · 关节电流 2 · 备用 4；每维有名字、单位与来源（见 4.03a）。",
        "▪ 为什么现在升级  多模态传感器（多指触觉/温度/声学）已经在路上；接口一次定死，后面只加数据不改形状。",
        "▪ 兼容是硬要求  前 43 维语义一字不动，老权重/老数据/老标定原样可用；新增 12 维在模型侧零行初始化，升级瞬间输出逐位不变（见 4.03b）。",
        "▪ 谁在用 55 维  引擎（state_dim=55，calib 43→55 自动补零行）、页面字段表、接口契约；在役 L3/L4 权重仍按 43 维口径吃前 43 维。",
    ])
    print("② 4.03 已重写")

    # ③ 4.19 表格加一行
    s419 = None
    for s in prs.slides:
        if shape_by_text(s, "4.19") is not None:
            s419 = s
            break
    tb = None
    for sh in s419.shapes:
        if getattr(sh, "has_table", False) and sh.has_table:
            tb = sh.table
    if tb is not None:
        last = tb.rows[len(tb.rows) - 1]._tr
        new_tr = copy.deepcopy(last)
        tb._tbl.append(new_tr)
        row = tb.rows[len(tb.rows) - 1]
        vals = ["obs[43:55]", "12", "预留扩展（多指触觉4/温度1/声学1/电流2/备用4）", "零初始化 · 有名字有单位"]
        for c, v in zip(row.cells, vals):
            tf_set(c.text_frame, [v])
        t419 = shape_by_text(s419, "维观测的字段明细")
        if t419 is not None:
            tf_set(t419.text_frame, ["55 维观测的字段明细（训练与在线必须一致）"])
        print("③ 4.19 表格 +1 行 (obs[43:55])")

    # ④ 插入新页
    idx_a = list(prs.slides).index(s403)
    order = [("4.03", "a"), ("4.03", "b"), ("4.03", "c"), ("4.03", "d")]
    ins = idx_a + 1
    for key in order:
        title_txt, lines, bottom = PAGES[key]
        s = clone_slide(prs, idx_a)
        new_i = len(prs.slides) - 1
        move_slide_to(prs, new_i, ins)
        s = prs.slides[ins]
        # 改四块文本
        sh_ref = [x for x in s.shapes if x.has_text_frame and x.text_frame.text.strip() == "4.03"][0]
        tf_set(sh_ref.text_frame, ["4.03" + key[1]])
        sh_title = [x for x in s.shapes if x.has_text_frame and "维观测：视觉 39 + 触觉 4 + 预留 12" in x.text_frame.text]
        tf_set(sh_title[0].text_frame, [title_txt])
        body_sh = [x for x in s.shapes if x.has_text_frame and x.width and x.width > 10 * 914400
                   and x.top and 1.9 * 914400 < x.top < 3.0 * 914400]
        tf_set(body_sh[0].text_frame, lines)
        sh_bot = [x for x in s.shapes if x.has_text_frame and x.top and x.top > 6.2 * 914400
                  and x.top < 6.9 * 914400]
        tf_set(sh_bot[0].text_frame, [bottom])
        ins += 1
    print("④ 插入 %d 页 (4.03a-4.03d)" % len(order))

    # ⑥.10 追加在 6.09 之后
    idx_609 = None
    for i, s in enumerate(prs.slides):
        if shape_by_text(s, "6.09") is not None:
            idx_609 = i
            break
    title_txt, lines, bottom = PAGES[("6.09", "e")]
    # 🔴 必须克隆"正文页"而不是 6.09: 6.09 是三块数字卡版式, 复用它会把正文写进整页背景矩形,
    #    三个旧数字块(10/10、w=0.3、+17.8%)还留在页面上 ⇒ 版式糊成一片 (踩过)。
    s = clone_slide(prs, 162)                        # 162 = 刚插入的 4.03a 正文页
    new_i = len(prs.slides) - 1
    move_slide_to(prs, new_i, idx_609 + 1)
    s = prs.slides[idx_609 + 1]
    sh_ref = [x for x in s.shapes if x.has_text_frame and x.text_frame.text.strip() == "4.03a"][0]
    tf_set(sh_ref.text_frame, ["6.10"])
    sh_title = [x for x in s.shapes if x.has_text_frame and "55D 分段" in x.text_frame.text]
    tf_set(sh_title[0].text_frame, [title_txt])
    body_sh = [x for x in s.shapes if x.has_text_frame and x.width and x.width > 10 * 914400
               and x.top and 1.9 * 914400 < x.top < 3.0 * 914400]
    tf_set(body_sh[0].text_frame, lines)
    sh_bot = [x for x in s.shapes if x.has_text_frame and x.top and 6.2 * 914400 < x.top < 6.9 * 914400]
    tf_set(sh_bot[0].text_frame, [bottom])
    print("⑤ 插入 6.10 验收页")

    # ⑤ 版本号 + 封面页数 + 页码
    ver_hits = 0
    for s in prs.slides:
        for tf in iter_text_frames(s.shapes):
            ver_hits += replace_in_tf(tf, [("5.50.D-M2", "5.50.D-M3"), ("5.50.D-M1", "5.50.D-M3")])
    n1 = len(prs.slides)
    for s in list(prs.slides)[:2]:
        for tf in iter_text_frames(s.shapes):
            replace_in_tf(tf, [("范围：288 页", "范围：%d 页" % n1),
                               ("编制 2026-11-04", "编制 2026-11-05")])
    for i, s in enumerate(prs.slides, start=1):
        set_pagenum(s, i)
    print("⑥ 版本号替换 %d 处 · 页数 %d → %d" % (ver_hits, n0, n1))

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    prs.save(a.out)
    print("✅ 输出 %s · %d 页 · %.1f KB" % (a.out, n1, os.path.getsize(a.out) / 1024))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
