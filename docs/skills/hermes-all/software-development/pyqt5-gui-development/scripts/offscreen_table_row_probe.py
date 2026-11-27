#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离屏构造**真控件**，把它内部表格逐行打出来 —— 验"某行/某列到底有没有"的唯一可信办法。

为什么不用手搓流水线: 真实 UI 常有 topic 前缀映射、二次过滤、固定行/滚动两套 fill 函数，
手工把 key→归属→策略 串一遍会漏条件，于是"我验过了"而用户屏幕上看不到。

用法:
  QT_QPA_PLATFORM=offscreen python offscreen_table_row_probe.py \\
      --sys-path src --sys-path tools/gui --sys-path tools \\
      --module dds_canoe --build build_view \\
      --refresh _fill_trace_fixed --table tb \\
      --columns 1,2,3,7,8 --grep 安全 --png /tmp/rows.png

判据: 打印里能读到目标行 ⇒ 表格层面是有的; 读不到 ⇒ 继续往归属/白名单/上限里查（见 SKILL.md 四道闸门）。
--png 出来的图是**离屏渲染**，交付给用户时要写明"不是你的屏幕"。
"""
import argparse
import importlib
import os
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sys-path", action="append", default=[], help="额外的 sys.path，可重复")
    ap.add_argument("--module", required=True, help="含控件工厂的模块名，如 dds_canoe")
    ap.add_argument("--build", required=True, help="工厂函数名，如 build_view")
    ap.add_argument("--refresh", default="", help="刷新函数名（会尝试传 force=True），如 _fill_trace_fixed")
    ap.add_argument("--table", default="tb", help="表控件属性名，默认 tb")
    ap.add_argument("--columns", default="", help="要打印的列索引，逗号分隔（空=全部列）")
    ap.add_argument("--grep", default="", help="只关心含该关键词的行（仍会打印总行数与命中行号）")
    ap.add_argument("--png", default="", help="把表 grab 成 PNG 存到这里")
    ap.add_argument("--size", default="1900x1200", help="控件尺寸 WxH")
    args = ap.parse_args()

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    for p in args.sys_path:
        sys.path.insert(0, p)

    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])
    mod = importlib.import_module(args.module)
    w = getattr(mod, args.build)(None)
    if args.size:
        try:
            ww, hh = (int(x) for x in args.size.lower().split("x"))
            w.resize(ww, hh)
        except Exception:                                                    # noqa: BLE001
            pass

    if args.refresh:
        fn = getattr(w, args.refresh, None)
        if fn is None:
            print("[warn] 没有 %s" % args.refresh)
        else:
            try:
                fn(force=True)
            except TypeError:
                fn()
            except Exception as e:                                           # noqa: BLE001
                print("[warn] %s 抛错: %r" % (args.refresh, e))
    app.processEvents()

    tb = getattr(w, args.table)
    rows = tb.rowCount()
    cols = [int(x) for x in args.columns.split(",") if x.strip()] or list(range(tb.columnCount()))
    print("行数=%d 列=%s 表=%s" % (rows, cols, args.table))

    hits = []
    for i in range(rows):
        vals = []
        for c in cols:
            it = tb.item(i, c)
            vals.append(it.text() if it else "")
        hit = (not args.grep) or any(args.grep in v for v in vals)
        if hit:
            hits.append(i)
            print("%4d  %s" % (i, " | ".join(vals)))

    if args.grep:
        print("命中 %d/%d 行 (%s): %s" % (len(hits), rows, args.grep, hits[:20]))

    if args.png:
        if hits:
            try:
                tb.verticalScrollBar().setValue(max(0, hits[0] - 3) * max(18, tb.verticalHeader().defaultSectionSize()))
                app.processEvents()
            except Exception:                                                # noqa: BLE001
                pass
        pix = tb.grab()
        pix = pix.scaled(pix.width() * 2, pix.height() * 2)
        pix.save(args.png, "PNG")
        print("证据图: %s (离屏渲染, 不是用户屏幕)" % args.png)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
