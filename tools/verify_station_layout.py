#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_station_layout.py — 8793/station 版面结构静态体检 (2026-10-12 老倪「一长条，太难看」之后加的判据)

老倪逐字: 「http://10.163.146.78:8793/station 侧面点的窗口，放在金手指的右边；号位点，空间点，放在下面；
          以前的样子你别乱改；恢复以前的布局；现在一长条，太难看」

真因(实测): 金手指面板末尾少一个 `</div>` ⇒ 表面检测/号位/空间点三个面板被**套进**金手指面板里
           (`.grid` 直接子元素只有 6 个而不是 9 个) ⇒ 表面掉到金手指下面、金手指被撑到 2844px 高、
           整栏变成一条长条。这类"HTML 少一个闭合标签"的 bug 用肉眼看不出来, 所以固化成本判据。

判据(全部静态解析 HTML, 不用起浏览器):
  ① div/section/main/aside 标签配平 (文件末尾 depth == 0)
  ② .grid 的直接子面板数 == 文档里所有面板数 (没有面板被套进别的面板里)
  ③ 金手指面板在 表面检测 面板**之前** (多列网格里前者在左、后者落在它右边)
  ④ 号位(#p_slots) / 空间点(#p_spaces) 两个面板排在金手指+表面之后, 且 CSS 里有 grid-column:1/-1 (整行在下)
"""
from __future__ import annotations

import os
import re
import sys
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, "tools/web/station.html")

_BOXES = ("div", "section", "main", "aside")
_fails = []


def chk(cond, msg):
    print("  %s %s" % ("✅" if cond else "❌", msg))
    if not cond:
        _fails.append(msg)
    return bool(cond)


class P(HTMLParser):
    """记录: 标签配平 + 每个 .panel 的父链 + 面板顺序与标题。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.depth = 0
        self.min_depth = 0
        self.panels = []            # [(序号, 父类名, 标题)] —— 只收 class 含 panel 的
        self.ttl = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = (a.get("class") or "")
        if tag in _BOXES:
            self.depth += 1
            self.stack.append((tag, cls, a.get("id") or ""))
            if "panel" in cls.split():
                parent = self.stack[-2][1] if len(self.stack) >= 2 else "(root)"
                self.panels.append([len(self.panels), parent, a.get("id") or "", ""])
        if "ttl" in cls.split():
            self._in_ttl = True

    def handle_endtag(self, tag):
        if tag in _BOXES:
            self.depth -= 1
            self.min_depth = min(self.min_depth, self.depth)
            if self.stack:
                self.stack.pop()

    def handle_data(self, data):
        if getattr(self, "_in_ttl", False) and data.strip():
            if self.panels and not self.panels[-1][3]:
                self.panels[-1][3] = data.strip()


def main() -> int:
    src = open(HTML, encoding="utf-8").read()
    p = P()
    p.feed(src)
    print("① 标签配平 (div/section/main/aside)")
    chk(p.depth == 0 and p.min_depth >= 0, "文件末尾 depth=%d (0 = 配平) · 最深过冲=%d" % (p.depth, p.min_depth))

    print("\n② 面板不许被套进别的面板 (.grid 直接子面板 == 全部面板)")
    total = len([x for x in p.panels])
    direct = len([x for x in p.panels if "grid" in x[1].split()])
    chk(direct == total, ".grid 直接子面板 %d / 全部面板 %d" % (direct, total))

    print("\n③ 金手指 在 表面检测 之前 (多列网格 ⇒ 表面落在金手指右边)")
    def idx_of(kw):
        for i, x in enumerate(p.panels):
            if kw in x[3]:
                return i
        return -1
    ig, isf = idx_of("金手指检测"), idx_of("表面检测")
    chk(ig >= 0 and isf >= 0, "两个面板都在: 金手指 #%d · 表面检测 #%d" % (ig, isf))
    chk(0 <= ig < isf, "顺序: 金手指(#%d) → 表面检测(#%d) ⇒ 多列时表面在金手指右边" % (ig, isf))

    print("\n④ 号位 / 空间点 在最后, 且整行在下 (grid-column:1/-1)")
    isl, isp = idx_of("号位"), idx_of("空间 1~7")
    chk(isl > isf and isp > isl, "顺序: 金手指 → 表面检测 → 号位(#%d) → 空间点(#%d)" % (isl, isp))
    for pid in ("p_slots", "p_spaces"):
        chk(re.search(r"#%s\s*\{[^}]*grid-column\s*:\s*1\s*/\s*-1" % pid, src) is not None,
            "#%s 有 grid-column:1/-1 (整行, 排在上面两块下面)" % pid)

    print("\n⑤ 点1/点2/安全点/侧面点/号位/空间点 六类按钮容器都在")
    for eid in ("goldbar", "sidebar", "spacebar"):
        chk(('id="%s"' % eid) in src, "按钮条 #%s 存在" % eid)

    print("\n════════════════════════════════════════════════")
    if _fails:
        print("❌ 失败 %d 项" % len(_fails))
        return 1
    print("✅ 全部通过 — 面板同级 / 顺序正确 / 标签配平")
    return 0


if __name__ == "__main__":
    sys.exit(main())
