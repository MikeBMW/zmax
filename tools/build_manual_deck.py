#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把三本册（整机方案 R5/R6 · 能力分级产品册 5.50.D）合成一本《总技术手册》

规则：
  1) 丢掉原封面/篇章页/结尾语，重新编排：新封面 + 导读 + 9 篇 + 结尾
  2) 每页按原章节号映射到新篇章，篇内保持原顺序并重新编号
  3) 同名页去重（去掉标点空格后比较），保留先出现的
用法: gui-venv311/bin/python tools/build_manual_deck.py [--out x.pptx]
"""
from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, "/home/ubuntu/zmax/tools")

import deck_content1, deck_content2, deck_content3, deck_content4   # noqa: E402
import deck_content5, deck_content6                                 # noqa: E402
import prod_content1, prod_content2, prod_content3                   # noqa: E402
import deck_lib as L                                                 # noqa: E402

DECK = "Z-MAX 精细操作机器人 · 总技术手册 5.50.D-M1"
OUT_DEFAULT = "/home/ubuntu/zmax/zmax_data/deliverables/20261104/Z-MAX总技术手册_5.50.D-M1.pptx"

# 篇号 → (篇名, 说明, 条目)
PARTS = {
    1: ("整机与产品定义", "这台机器怎么干活：功能总框图、55 个节点的输入输出、节点顺序、外形与轴向尺寸、节拍。"),
    2: ("能力分级与产品矩阵", "五级能力 C1-C5 的定义与判据，型号族 F1-F5 的配置、选型与交付边界。"),
    3: ("技术底座", "五层引擎、力控三段压入、世界模型接管、记忆、安全闸、三机分工与接口契约。"),
    4: ("技术史与成熟度", "1948-2026：从状态空间方程到 JEPA 与 VLA；每条路线的成熟证据与失效模式。"),
    5: ("实证", "V6 单一 autograd 图、三张消融表、引擎 A/B 接管、节拍与精度实测。"),
    6: ("真机演练与自进化", "干跑报文与红线、AR 场景色标、进化闭环一轮实测。"),
    7: ("经济性与交付", "单件成本、回本、TCO、报价结构、四件套与能力证书、验收七步。"),
    8: ("立项与路线图", "12 个月四阶段、六个里程碑、资源与预算、风险、D1-D4 决策点。"),
    9: ("附录", "能力词典、指标口径、证据索引、公式与参考文献、术语与版本记录。"),
}

# 旧章节首段 → 新篇号
MAP = {
    # R6 白皮书
    "0": 1,      # 整机方案（content5）
    "0.55": 1,   # 55 个节点方框图（content6）
    "1": 4, "2": 4,      # 技术史 / 成熟度
    "3": 3,              # 分层工程
    "4": 5,              # 实证
    "5": 6,              # 演练与自进化
    "6": 7,              # 原型与交付
    "7": 9,              # 附录
}
# 产品册（按来源模块区分，避免与上面同号冲突）
PROD_MAP = {"1": 2, "2": 2, "3": 2, "4": 3, "5": 5, "6": 7, "7": 7, "8": 8}


def _norm(t: str) -> str:
    return re.sub(r"[\s·、，。：,.:;；（）()\-—/“”\"'|]+", "", t or "")


def _first_num(ch: str, title: str):
    s = ch or title or ""
    m = re.match(r"^(\d+(?:\.\d+)?)", s)
    if m:
        return m.group(1)
    m = re.match(r"^附录\s*([A-Z])", s)
    if m:
        return "7"
    if re.match(r"^([A-Z])\s", s):
        return "7"
    return "9"


SKIP = {
    ("deck_content3", "三机分工：训练、边缘"),        # 与产品册版重复, 保留在技术底座
    ("prod_content2", "五层引擎：85 个节点"),          # 与 R6 五层分工重复
    ("prod_content2", "五层记忆：让“练过的动作”"),     # 与 R6 五层记忆重复
    ("prod_content2", "四道安全闸：从意图到关节"),      # 与 R6 分层否决重复
    ("prod_content2", "力控压入：位移为主"),            # 与 R6 三段压入/SE(3) 重复
}


def collect():
    """返回 [(part, mod_idx, old_key, entry)]"""
    out = []
    for mod_idx, (mod, is_prod) in enumerate(
            ((deck_content1, False), (deck_content5, False), (deck_content6, False),
             (deck_content2, False), (deck_content3, False), (deck_content4, False),
             (prod_content1, True), (prod_content2, True), (prod_content3, True))):
        for e in mod.CONTENT:
            if e["k"] in ("cover", "section", "quote"):
                continue
            if (e.get("ch") or "").strip() in ("导读", "结语"):
                continue
            _t = (e.get("t") or "")[:24]
            if any(mod.__name__.split(".")[-1] == m and _t.startswith(t[:24]) for m, t in SKIP):
                continue
            ch = e.get("ch") or ""
            if re.match(r"^([A-Z])\s", ch) or re.match(r"^附录", ch):
                out.append((9, mod_idx, "7", e))
                continue
            num = _first_num(ch, e.get("t", ""))
            head = num.split(".")[0]
            part = (PROD_MAP if is_prod else MAP).get(num, (PROD_MAP if is_prod else MAP).get(head, 9))
            if is_prod and num.startswith("0"):
                part = 2
            out.append((part, mod_idx, num, e))
    return out


def build(out_path: str) -> int:
    pr = L.new_deck()
    idx = 0
    entries = collect()

    # 篇内排序：按原章节号，再按出现顺序
    entries.sort(key=lambda x: (x[0], x[1], [float(p) if p.replace(".", "").isdigit() else 99.0
                                             for p in (x[2].split(".") + ["0", "0"])[:3]]))

    # 封面 + 导读
    idx += 1
    L.cover(pr, "Z-MAX 精细操作机器人",
            "总技术手册 · 整机 × 能力分级 × 技术白皮书 三本合一",
            ["版本 5.50.D-M1　编制 2026-11-04",
             "来源：整机解决方案 5.50.C-R5（82 页）、技术白皮书 5.50.C-R6（209 页）、能力分级产品册 5.50.D-R1（72 页）",
             "口径：在役 / 在研 / 规划 / 试运行四态标注；每个数字可回溯到 reports/ 与交付物。"])

    idx += 1
    L.bullets(pr, idx, DECK, "导读", "这本手册怎么读：九篇，一条从整机到立项的线",
              [("① 整机与产品定义", "第 1 篇：机器长什么样、怎么干活、节拍从哪来（含 55 个节点方框图）。"),
               ("② 能力与产品", "第 2 篇：能力分五级 C1-C5，型号分五档 F1-F5，客户按级买。"),
               ("③ 技术底座", "第 3 篇：五层引擎、力控、接管、记忆、安全闸、接口。"),
               ("④ 技术来路", "第 4 篇：七十年技术史与成熟度判定，说明为什么选潜空间预测。"),
               ("⑤ 证据", "第 5-6 篇：消融、A/B、节拍精度、演练与自进化，全部带出处。"),
               ("⑥ 生意与立项", "第 7-8 篇：成本与回本、交付验收、12 个月路线与决策点。")],
              sub="读者可以只读第 2 篇（选型）或第 5 篇（要看证据时），但结论都回扣到第 1 篇的整机定义",
              note="页码连续；篇内编号为“篇.序”，与原三本册的章节号不同，原文引用以标题为准。")

    used = set()
    cur_part = None
    seq = 0
    for part, mod_idx, num, e in entries:
        title = e.get("t") or e.get("title") or ""
        if part == 9 and mod_idx >= 6:            # 产品册的附录, 与白皮书附录区分
            title = "产品册｜" + title
        key = _norm(title)
        if key in used:
            continue
        used.add(key)
        if part != cur_part:
            cur_part = part
            seq = 0
            name, desc = PARTS[part]
            idx += 1
            L.section(pr, part, name, desc,
                      [f"{p:02d} · {t}" for p, t in sorted(PARTS.items()) if p == part][:1]
                      + [x for x in ()])
        seq += 1
        ch = f"{part}.{seq:02d}"
        idx += 1
        k = e["k"]
        if k == "bullets":
            L.bullets(pr, idx, DECK, ch, title, e["items"], sub=e.get("sub", ""),
                      note=e.get("note", ""), size=e.get("size", 15))
        elif k == "formula":
            L.formula(pr, idx, DECK, ch, title, e["lines"], sub=e.get("sub", ""), note=e.get("note", ""))
        elif k == "table":
            L.table(pr, idx, DECK, ch, title, e["headers"], e["rows"], sub=e.get("sub", ""),
                    note=e.get("note", ""), col_w=e.get("col_w"), size=e.get("size", 12))
        elif k == "timeline":
            L.timeline(pr, idx, DECK, ch, title, e["events"], sub=e.get("sub", ""), note=e.get("note", ""))
        elif k == "layers":
            L.layers(pr, idx, DECK, ch, title, e["rows"], sub=e.get("sub", ""), note=e.get("note", ""))
        elif k == "cards":
            L.cards(pr, idx, DECK, ch, title, e["items"], sub=e.get("sub", ""),
                    note=e.get("note", ""), cols=e.get("cols", 2))
        elif k == "bigstat":
            L.bigstat(pr, idx, DECK, ch, title, e["stats"], sub=e.get("sub", ""), note=e.get("note", ""))
        elif k == "figures":
            L.figures(pr, idx, DECK, ch, title, e["items"], sub=e.get("sub", ""),
                      note=e.get("note", ""), cols=e.get("cols", 2))
        elif k == "funcmap":
            L.funcmap(pr, idx, DECK, ch, title, e["rows"],
                      left_title=e.get("left_title", "输入"), left_items=e.get("left_items", ()),
                      right_title=e.get("right_title", "输出"), right_items=e.get("right_items", ()),
                      sub=e.get("sub", ""), note=e.get("note", ""))
        elif k == "nodeblock":
            L.nodeblock(pr, idx, DECK, ch, title, e["name"], e["ins"], e["outs"],
                        desc=e.get("desc", ""), tick=e.get("tick", ""), code=e.get("code", ""),
                        sub=e.get("sub", ""))
        else:
            raise SystemExit(f"unknown kind: {k}")

    idx += 1
    L.quote(pr, idx, DECK, "",
            "把“能干什么”说清楚，再把“凭什么说能干”举证清楚——这本手册的两个动作，也是产品的两个动作。",
            "Z-MAX 精细操作机器人 · 总技术手册 5.50.D-M1")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    pr.save(out_path)
    print(f"SAVED {out_path} pages={idx}")
    return idx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT_DEFAULT)
    n = build(ap.parse_args().out)
    print(f"PAGES {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
