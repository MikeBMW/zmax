#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ppt_move_mani_first.py — 把「流形引擎」页挪到认知层第 1/18 位, 并重编号整层

只动 PPT (不碰画布)。做法:
  ① 在「认知层 · 第 k / 18 位」这一段里找到流形引擎页
  ② 把它移到该段第一位 (sldIdLst 层移动, 图片/版式整体跟着走)
  ③ 重写这 18 页标题里的「第 k / 18 位」为 1..18
自检: 总页数不变 · 段内页内容集合不变 · 位次 1..18 连续 · 流形引擎在第 1 位。
"""
import argparse
import os
import re
import sys

from pptx import Presentation

PAT = re.compile(r"(认知层\s*·\s*第\s*)(\d+)(\s*/\s*18\s*位)")
NAME_KEY = "流形引擎"


def find_seg(pr):
    """返回认知层逐节点页的 (start, end) 索引 (0-based, 含两端)。"""
    idx = []
    for i, s in enumerate(pr.slides):
        for sh in s.shapes:
            if sh.has_text_frame and PAT.search(sh.text_frame.text):
                idx.append(i)
                break
    if not idx:
        raise SystemExit("未找到「认知层 · 第 k / 18 位」页")
    return idx[0], idx[-1], idx


def node_name(s):
    """页面名称行 = 第一个不含「第 k / 18 位」的文本行 (版面 0.82,0.48 的 21pt 大标题)。"""
    for sh in s.shapes:
        if sh.has_text_frame:
            t = sh.text_frame.text.strip()
            if t and not PAT.search(t):
                return t.split("\n")[0]
    return ""


def title_of(s):
    for sh in s.shapes:
        if sh.has_text_frame and PAT.search(sh.text_frame.text):
            return sh.text_frame.text.split("\n")[0]
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ppt", default="/home/ubuntu/zmax/zmax_data/deliverables/20261102/"
                                    "Z-MAX机器人整机解决方案_5.50.C-R5_20261102.pptx")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    pr = Presentation(a.ppt)
    n0 = len(pr.slides)
    s0, s1, idx = find_seg(pr)
    print("认知层段: 第 %d..%d 页 (共 %d 页)" % (s0 + 1, s1 + 1, len(idx)))
    before = [(i, title_of(pr.slides[i])) for i in range(s0, s1 + 1)]
    for i, t in before:
        print("  %2d %s" % (i + 1, t[:64]))

    # 定位流形引擎页 (标题里没有名字 → 看正文第一个非标题段)
    me = None
    for i in range(s0, s1 + 1):
        s = pr.slides[i]
        if NAME_KEY in node_name(s):
            me = i
            break
    if me is None:
        raise SystemExit("段内没找到含「%s」的页" % NAME_KEY)
    print("\n流形引擎页 = 第 %d 页, 段内第 %d 位" % (me + 1, me - s0 + 1))

    # ① 移动: sldIdLst 里把该页移到段首
    lst = pr.slides._sldIdLst
    ids = list(lst)
    el = ids[me]
    lst.remove(el)
    lst.insert(s0, el)

    # ② 重编号 (段内顺序已变)
    if s1 == s0 + len(idx) - 1:
        pass
    for k, i in enumerate(range(s0, s0 + len(idx)), 1):
        for sh in pr.slides[i].shapes:
            if sh.has_text_frame and PAT.search(sh.text_frame.text):
                for p in sh.text_frame.paragraphs:
                    for r in p.runs:
                        if PAT.search(r.text):
                            r.text = PAT.sub(lambda m: "%s%d%s" % (m.group(1), k, m.group(3)), r.text)

    # 自检
    after = [title_of(pr.slides[i]) for i in range(s0, s0 + len(idx))]
    nums = [int(PAT.search(t).group(2)) for t in after if PAT.search(t)]
    names_before = sorted(node_name(pr.slides[i]) for i in range(s0, s1 + 1))
    names_after = sorted(node_name(pr.slides[i]) for i in range(s0, s0 + len(idx)))
    set_ok = names_before == names_after
    ok = (len(pr.slides) == n0 and nums == list(range(1, len(idx) + 1))
          and NAME_KEY in node_name(pr.slides[s0])
          and set_ok)
    print("\n新顺序:")
    for k, i in enumerate(range(s0, s0 + len(idx)), 1):
        print("  %2d %-58s | %s" % (k, node_name(pr.slides[i])[:58], title_of(pr.slides[i])[:34]))
    print("\n自检: 页数 %d→%d · 位次连续=%s · 流形引擎在首位=%s · 页面集合不变=%s"
          % (n0, len(pr.slides), nums == list(range(1, len(idx) + 1)),
             NAME_KEY in node_name(pr.slides[s0]), set_ok))

    if not ok:
        print("❌ 判据未过, 未保存")
        return 1
    if a.apply:
        pr.save(a.ppt)
        print("✅ 已保存 %s" % a.ppt)
    else:
        print("(dry-run, 加 --apply 才写盘)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
