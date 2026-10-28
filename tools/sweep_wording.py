#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工程用语清理: 把口语化、AI 腔的中文表述换成正式书面语。

老倪 2026-10-28: 「全局搜索, 整个工程, 文档, 不要出现 重新生成 唯一依据 预先固定 这样的口语, 不要有 AI 的味道」

规则按「先长后短」顺序替换, 避免短词先命中把长词拆坏。
  python3 tools/sweep_wording.py            # 只统计, 不改
  python3 tools/sweep_wording.py --apply    # 真改
"""
import os
import re
import sys

ROOTS = ["tools", "docs", "config", "web", "data/database/zmax"]
EXT = (".py", ".md", ".html", ".json", ".txt", ".sh", ".yaml", ".yml", ".csv",
       ".java", ".service", ".proj", ".xml", ".css", ".js")
SKIP_DIR = {".git", "node_modules", "__pycache__", "gui-venv311", "venv", ".venv",
            "zmax_data", "reports", "logs", "data", "_deck_png", "图片库", ".hermes"}

# (pattern, replacement) —— 逐条作用于全文, 顺序敏感
RULES = [
    # ① 老倪点名的三个表述 (先长后短)
    (r"真的重写", "重新生成"),
    (r"真的写出", "实际生成"),
    (r"唯一真源", "唯一依据"),
    (r"真源缺口", "依据缺失"),
    (r"真源未标", "依据未标注"),
    (r"真源没写", "依据未写明"),
    (r"真源", "唯一依据"),
    (r"不许写死", "不得硬编码"),
    (r"不要写死", "不得硬编码"),
    (r"不写死", "不预先固定"),
    (r"写死在", "硬编码在"),
    (r"写死的", "固定不变的"),
    (r"写死", "预先固定"),
    # ② 口语化表述
    (r"说白了", "直白地说"),
    (r"其实", "实际"),
    (r"搞定", "完成"),
    (r"活儿", "工作"),
    (r"靠谱", "可靠"),
    (r"整明白", "弄清楚"),
    (r"一刀切", "统一处理"),
    (r"兜底", "保障"),
    (r"捞出来", "取出"),
    (r"踩坑", "遇到问题"),
    (r"喂给", "提供给"),
    (r"跑一遍", "执行一遍"),
    (r"跑通", "验证通过"),
    (r"跑起来", "启动"),
    (r"卡住", "阻塞"),
    (r"打不开", "无法打开"),
    (r"看不懂", "不易理解"),
    (r"说不清", "难以说明"),
    (r"一看就", "可以直接"),
    # ③ 常见套话
    (r"值得注意", "需注意"),
    (r"需要指出的是", "需说明的是"),
    (r"换句话说", "换言之"),
    (r"本质上", "实质上是"),
    (r"可以说", "可以认为"),
    (r"干什么活", "做什么"),
    (r"卡在哪", "阻塞点"),
    (r"为啥", "为什么"),
    (r"干啥", "做什么"),
    (r"啥", "什么"),
    (r"咋", "怎么"),
    (r"非常关键", "关键"),
    (r"非常重要", "重要"),
]


def iter_files():
    for root in ROOTS:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIR]
            for fn in filenames:
                if not fn.endswith(EXT):
                    continue
                p = os.path.join(dirpath, fn)
                if fn == "sweep_wording.py" or "data_snapshots" in p or fn.endswith(".bak"):
                    continue
                try:
                    if os.path.islink(p) or os.path.getsize(p) > 4 * 1024 * 1024:
                        continue
                except OSError:
                    continue
                yield p


def main():
    apply = "--apply" in sys.argv
    counts = {pat: 0 for pat, _ in RULES}
    files_hit = 0
    total = 0
    for p in iter_files():
        try:
            src = open(p, encoding="utf-8").read()
        except Exception:                                                   # noqa: BLE001
            continue
        new = src
        local = 0
        for pat, rep in RULES:
            new, n = re.subn(pat, rep, new)
            if n:
                counts[pat] += n
                local += n
        if new != src:
            files_hit += 1
            total += local
            if apply:
                open(p, "w", encoding="utf-8").write(new)
    print("%s %d 个文件 / %d 处" % ("已修改" if apply else "待修改", files_hit, total))
    for pat, n in counts.items():
        if n:
            print("  %-14s %5d" % (pat.replace("\\", ""), n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
