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
import manual_wm                                                     # noqa: E402
from speaker_notes import note_for                                    # noqa: E402
import deck_lib as L                                                 # noqa: E402

DECK = "以世界模型为核心的状态空间工程 · 技术手册 5.50.D-M2"
OUT_DEFAULT = "/home/ubuntu/zmax/zmax_data/deliverables/20261104/Z-MAX以世界模型为核心的状态空间工程_5.50.D-M2.pptx"

# 篇号 → (篇名, 说明, 条目)
PARTS = {
    1: ("整机与工位：这台机器怎么干活", "功能总框图、55 个节点的输入输出、节点顺序、外形与轴向尺寸、节拍两本账。"),
    2: ("世界模型的技术来路：1948→2026",
        "从状态空间方程、Kalman、HMM/POMDP 到 World Models、Dreamer、JEPA 与 VLA；每次跃迁解决什么、代价是什么、成熟到什么程度。"),
    3: ("世界模型对标与本工程架构（核心篇）",
        "NVIDIA/Google/OpenAI/李飞飞/Meta 五条主线的技术基因、自动驾驶的经验、八维对比表，为什么选 JEPA、为什么必须分层，H-JEPA-MR 架构与 UPH>1000 的账。"),
    4: ("状态空间工程：把世界模型落成五层",
        "五层引擎、43 维观测、SE(3) 阻抗、三段压入、八阶段状态机、L4 接管契约、势场、记忆、安全闸、三机分工与接口契约。"),
    5: ("能力分级与产品矩阵", "五级能力 C1-C5 的定义与判据，型号族 F1-F5 的配置、选型与交付边界。"),
    6: ("实证：模型到底贡献了什么", "V6 单一 autograd 图、三张消融表、引擎 A/B 接管、节拍与精度实测。"),
    7: ("真机演练与自进化", "干跑报文与红线、AR 场景色标、进化闭环一轮实测。"),
    8: ("经济性与交付", "单件成本、回本、TCO、报价结构、四件套与能力证书、验收七步。"),
    9: ("立项与路线图", "12 个月四阶段、六个里程碑、资源与预算、风险、D1-D4 决策点。"),
    10: ("附录", "能力词典、指标口径、证据索引、公式与参考文献、术语与版本记录。"),
}

# 旧章节首段 → 新篇号
MAP = {
    # R6 白皮书
    "0": 1,      # 整机方案（content5）
    "0.55": 1,   # 55 个节点方框图（content6）
    "1": 2, "2": 2,      # 技术史 / 成熟度 → 世界模型来路
    "3": 4,              # 分层工程 → 状态空间工程
    "4": 6,              # 实证
    "5": 7,              # 演练与自进化
    "6": 8,              # 原型与交付
    "7": 10,             # 附录
}
# 产品册（按来源模块区分，避免与上面同号冲突）
PROD_MAP = {"1": 5, "2": 5, "3": 5, "4": 4, "5": 6, "6": 8, "7": 8, "8": 9}


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
             (prod_content1, True), (prod_content2, True), (prod_content3, True),
             (manual_wm, False))):
        for e in mod.CONTENT:
            if e["k"] in ("cover", "section", "quote"):
                continue
            if (e.get("ch") or "").strip() in ("导读", "结语"):
                continue
            _t = (e.get("t") or "")[:24]
            if any(mod.__name__.split(".")[-1] == m and _t.startswith(t[:24]) for m, t in SKIP):
                continue
            ch = e.get("ch") or ""
            if mod.__name__.endswith("manual_wm"):      # 世界模型篇: 全部落在第 5 篇
                out.append((3, mod_idx, ch.split(" ")[0] or "9", e))
                continue
            if re.match(r"^([A-Z])\s", ch) or re.match(r"^附录", ch):
                out.append((10, mod_idx, "7", e))
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
    _cv = L.cover(pr, "以世界模型为核心的\n状态空间工程",
            "整机 × 能力分级 × 从控制论到 H-JEPA 的技术线　｜　技术手册 5.50.D-M2",
            ["版本 5.50.D-M2　编制 2026-11-04　范围：288 页，十篇",
             "来源：整机解决方案 5.50.C-R5（82 页）、技术白皮书 5.50.C-R6（209 页）、能力分级产品册 5.50.D-R1（72 页）",
             "口径：在役 / 在研 / 规划 / 试运行四态标注；每个数字可回溯到 reports/ 与交付物。"])
    _cv.notes_slide.notes_text_frame.text = note_for(0, 0, {"k": "cover"})

    idx += 1
    _dv = L.bullets(pr, idx, DECK, "导读", "这本手册的主线：世界模型是核心，状态空间是它的工程形态",
              [("① 这台机器怎么干活", "第 1 篇：功能总框图、55 个节点输入输出、外形与轴向尺寸、节拍两本账——先把世界模型要服务的对象立起来。"),
               ("② 世界模型七十年怎么走到今天", "第 2 篇：1948 控制论 → 1960 Kalman → 1990 HMM/POMDP → 2018 World Models → 2022 JEPA/H-JEPA → 2025 V-JEPA 2；每次跃迁解决什么、代价是什么。"),
               ("③ 五条路线怎么比，为什么选 JEPA 分层", "第 3 篇（核心）：Cosmos / Genie+Dreamer / Sora / World Labs / JEPA 同台，八维打分，H-JEPA-MR 架构，UPH>1000 的账。"),
               ("④ 世界模型怎么落成工程", "第 4 篇：五层状态空间、43 维观测、SE(3) 阻抗、八阶段状态机、L4 接管契约、记忆与安全闸。"),
               ("⑤ 它换来了什么能力、有什么证据", "第 5-6 篇：能力分级 C1-C5 与 F1-F5 型号，消融三张表、引擎 A/B、节拍与精度实测。"),
               ("⑥ 生意与立项", "第 7-10 篇：演练与自进化、成本回本与验收七步、12 个月路线、附录口径。")],
              sub="世界模型不是其中一章，是全册的主语：第 2 篇讲它怎么长出来，第 3 篇讲五条路线怎么选，第 4 篇讲怎么落成工程，第 5-6 篇讲它换来了什么、有没有证据。",
              note="页码连续；篇内编号为“篇.序”，与原三本册的章节号不同，原文引用以标题为准。")
    _dv.notes_slide.notes_text_frame.text = (
        "这本手册的主线一句话：世界模型是核心，状态空间是它的工程形态。"
        "讲的时候按六步走：先立对象（第 1 篇这台机器怎么干活），再讲来路（第 2 篇七十年怎么走到 JEPA），"
        "然后是核心篇（第 3 篇五条路线同台对比、为什么选 JEPA 分层），接着落到工程（第 4 篇五层怎么分），"
        "再用能力和证据说话（第 5、6 篇），最后算账和立项（第 7 到 10 篇）。"
        "时间紧就跳过第 2 篇和第 10 篇，但第 3 篇不能跳。")

    used = set()
    cur_part = None
    seq = 0
    for part, mod_idx, num, e in entries:
        title = e.get("t") or e.get("title") or ""
        if part == 10 and mod_idx >= 6:           # 产品册的附录, 与白皮书附录区分
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
            s = L.section(pr, part, name, desc,
                      [f"{p:02d} · {t}" for p, t in sorted(PARTS.items()) if p == part][:1]
                      + [x for x in ()])
            s.notes_slide.notes_text_frame.text = note_for(0, part, {"k": "section", "t": name})
        seq += 1
        ch = f"{part}.{seq:02d}"
        idx += 1
        _note = ""
        k = e["k"]
        if k == "bullets":
            s = L.bullets(pr, idx, DECK, ch, title, e["items"], sub=e.get("sub", ""),
                      note=e.get("note", ""), size=e.get("size", 15))
        elif k == "formula":
            s = L.formula(pr, idx, DECK, ch, title, e["lines"], sub=e.get("sub", ""), note=e.get("note", ""))
        elif k == "table":
            s = L.table(pr, idx, DECK, ch, title, e["headers"], e["rows"], sub=e.get("sub", ""),
                    note=e.get("note", ""), col_w=e.get("col_w"), size=e.get("size", 12))
        elif k == "timeline":
            s = L.timeline(pr, idx, DECK, ch, title, e["events"], sub=e.get("sub", ""), note=e.get("note", ""))
        elif k == "layers":
            s = L.layers(pr, idx, DECK, ch, title, e["rows"], sub=e.get("sub", ""), note=e.get("note", ""))
        elif k == "cards":
            s = L.cards(pr, idx, DECK, ch, title, e["items"], sub=e.get("sub", ""),
                    note=e.get("note", ""), cols=e.get("cols", 2))
        elif k == "bigstat":
            s = L.bigstat(pr, idx, DECK, ch, title, e["stats"], sub=e.get("sub", ""), note=e.get("note", ""))
        elif k == "figures":
            s = L.figures(pr, idx, DECK, ch, title, e["items"], sub=e.get("sub", ""),
                      note=e.get("note", ""), cols=e.get("cols", 2))
        elif k == "funcmap":
            s = L.funcmap(pr, idx, DECK, ch, title, e["rows"],
                      left_title=e.get("left_title", "输入"), left_items=e.get("left_items", ()),
                      right_title=e.get("right_title", "输出"), right_items=e.get("right_items", ()),
                      sub=e.get("sub", ""), note=e.get("note", ""))
        elif k == "nodeblock":
            s = L.nodeblock(pr, idx, DECK, ch, title, e["name"], e["ins"], e["outs"],
                        desc=e.get("desc", ""), tick=e.get("tick", ""), code=e.get("code", ""),
                        sub=e.get("sub", ""))
        else:
            raise SystemExit(f"unknown kind: {k}")
        try:
            s.notes_slide.notes_text_frame.text = note_for(seq, part, e)
        except Exception as exc:                                        # noqa: BLE001
            print("notes fail", idx, exc)

    idx += 1
    _qt = L.quote(pr, idx, DECK, "",
            "把“能干什么”说清楚，再把“凭什么说能干”举证清楚——这本手册的两个动作，也是产品的两个动作。",
            "Z-MAX 精细操作机器人 · 总技术手册 5.50.D-M1")
    _qt.notes_slide.notes_text_frame.text = note_for(0, 10, {"k": "quote"})

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
