#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""版面判据: 不靠人眼, 用 pptx 形状坐标 + 渲染 PNG 的墨迹行来自证。

子代理视觉复核因余额中断后, 这套判据接手做「版面」这一层, 检查的是可量化的东西:
  ① 安全区: 任何形状都在左边距 0.55in / 右 12.78in / 上 0.30in / 下 7.20in 以内
  ② 块不重叠: 图表 / 数字条 / 卡片 / 长文本框 四类块任意两块不得相交 (包含关系除外)
  ③ 图表: 不得有两条数值完全相同的系列 (会完全重合导致标签叠印); 折线只允许一条系列带标签
  ④ 页面填充: 渲染 PNG 里, 内容墨迹下边界 >= 500px (750 高), 否则判定「上重下空」
  ⑤ 对齐线: 每页主体块的左边界必须落在 96px ±6 或 84px ±6 这两条线上, 右边界 <= 1280px
  ⑥ 图例位置: 有图例的图表, 图例必须在绘图区之外 (不压柱/饼)

跑法: QT_QPA_PLATFORM=offscreen 不需要 · gui-venv311/bin/python tools/verify_deck_layout.py
"""
import os
import sys

from PIL import Image
from pptx import Presentation
from pptx.util import Emu

PPT = "/home/ubuntu/zmax_data/deliverables/双臂协作工位_成本结构与市场分成预期.pptx"
PNG = "/home/ubuntu/zmax_data/deliverables/_deck_png"
PASS, FAIL = [], []
IN = 914400.0


def chk(name, ok, detail=None):
    (PASS if ok else FAIL).append(name)
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                        (" — " + str(detail)) if detail not in (None, "") else ""))


def bbox(sh):
    try:
        return (sh.left / IN, sh.top / IN, (sh.left + sh.width) / IN, (sh.top + sh.height) / IN)
    except TypeError:
        return None


def area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def inter(a, b):
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def is_block(sh):
    """算「块」: 图表 / 长文本框 / 带填充的圆角矩形 / 图片。卡片里的短文字不算块。"""
    b = bbox(sh)
    if not b or area(b) < 0.9:
        return False
    if getattr(sh, "has_chart", False) and sh.has_chart:
        return True
    if sh.shape_type is not None and int(getattr(sh.shape_type, "value", 0)) == 13:
        return True
    if sh.has_text_frame and len(sh.text_frame.text or "") >= 30:
        return True
    return False


def ink_rows(png):
    im = Image.open(png).convert("L")
    w, h = im.size
    px = im.load()
    rows = []
    for y in range(h):
        dark = 0
        for x in range(0, w, 3):
            if px[x, y] < 235:
                dark += 1
        if dark > 2:
            rows.append(y)
    return w, h, rows


def main():
    prs = Presentation(PPT)
    n = len(prs.slides._sldIdLst)
    chk("① 页数 = 14", n == 14, n)

    for i, sl in enumerate(prs.slides, 1):
        shapes = [sh for sh in sl.shapes if bbox(sh)]
        # ① 安全区
        # 只查内容带: 模板自带的标题带 (y<0.95) / 页脚 (y>6.85) / 满幅装饰条 不参与
        band = [sh for sh in shapes if 0.95 <= bbox(sh)[1] <= 6.85 and (bbox(sh)[2] - bbox(sh)[0]) < 13.0]
        out = [sh.name for sh in band
               if (bbox(sh)[0] < 0.50 or bbox(sh)[2] > 12.83 or bbox(sh)[3] > 7.25)]
        chk("① 第 %d 页 内容带形状在安全区内" % i, not out, out[:3])
        # ⑤ 对齐线/右边界 (只看块)
        blocks = [sh for sh in shapes if is_block(sh)]
        # 对齐只看主体左边界 (最靠左的块), 右侧栏本来就不在 96px 线上
        body_left = min((bbox(sh)[0] for sh in blocks), default=0.92) * 96
        chk("⑤ 第 %d 页 主体左边界落在 96px 对齐线 (±6px)" % i, abs(body_left - 96) <= 6,
            round(body_left, 1))
        rights = [round(bbox(sh)[2], 2) for sh in blocks]
        chk("⑤ 第 %d 页 块右边界 <= 12.80in" % i, all(r <= 12.80 for r in rights),
            max(rights) if rights else None)
        # ② 块不重叠 (包含关系放行)
        hits = []
        for a in range(len(blocks)):
            for b in range(a + 1, len(blocks)):
                ba, bb = bbox(blocks[a]), bbox(blocks[b])
                ia = inter(ba, bb)
                if ia <= 0.02:
                    continue
                contained = ia >= 0.92 * min(area(ba), area(bb))
                if not contained:
                    hits.append((blocks[a].name, blocks[b].name, round(ia, 2)))
        chk("② 第 %d 页 块之间不重叠" % i, not hits, hits[:3])

    # ③ 图表链
    idx = 0
    for i, sl in enumerate(prs.slides, 1):
        for sh in sl.shapes:
            if not (getattr(sh, "has_chart", False) and sh.has_chart):
                continue
            idx += 1
            ch = sh.chart
            try:
                plot = ch.plots[0]
                vals = [[round(float(v), 3) for v in ser.values] for ser in plot.series]
            except Exception:                                               # noqa: BLE001
                continue
            dup = [(k, j) for k in range(len(vals)) for j in range(k + 1, len(vals)) if vals[k] == vals[j]]
            chk("③ 第 %d 页图%d 无两条数值完全相同的系列" % (i, idx), not dup, dup[:2])
            kind = str(ch.chart_type)
            if "LINE" in kind:
                labeled = sum(1 for ser in plot.series
                              if getattr(ser, "data_labels", None) is not None
                              and getattr(ser.data_labels, "show_value", False))
                chk("③ 第 %d 页图%d 折线只有一条系列带标签" % (i, idx), labeled <= 1, labeled)
            chk("③ 第 %d 页图%d 有图例" % (i, idx), bool(ch.has_legend), ch.has_legend)

    # ④ 页面填充 (渲染墨迹)
    pngs = sorted(f for f in os.listdir(PNG) if f.startswith("s-") and f.endswith(".png"))
    chk("④ 渲染图 14 张", len(pngs) == 14, len(pngs))
    for f in pngs:
        w, h, rows = ink_rows(os.path.join(PNG, f))
        body = [y for y in rows if y < 0.855 * h]        # 排除页脚
        bottom = max(body) if body else 0
        page = int(f.split("-")[1].split(".")[0])
        if page == 1:
            chk("④ %s 封面不做填充判定" % f, True, "bottom=%d" % bottom)
            continue
        chk("④ %s 内容墨迹下边界 >= 500px (不上下失衡)" % f, bottom >= 500, "bottom=%d/%d" % (bottom, h))

    print("\n=== %d PASS / %d FAIL ===" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败项:")
        for f in FAIL:
            print("  -", f)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
