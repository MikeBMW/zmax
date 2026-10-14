#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据: 配置中心「📋 任务配置」首屏能不能导出元任务开发计划的 Word/PDF。

老倪 2026-10-14: 「这些元任务, 要由配置中心可以在任务配置里可以导出 word 和 pdf 文档」

离屏真起 ConfigCenterPage(不碰老倪正在用的控制台), 逐条核:
  ① 「📋 任务配置」页存在且在首屏
  ② 该页上有「📄 元任务计划 (Word/PDF)」按钮
  ③ 该按钮接的是 _run_doc('metaplan')
  ④ 'metaplan' 在 DOC_SCRIPTS 里, 指向 tools/export_meta_doc.py, 且脚本文件真存在
  ⑤ 真点一次: 产出 .md/.docx/.pdf 三个文件, 且都比点击前新
  ⑥ 底部结果面板给出产物绝对路径 (点了必出结果)
用法: QT_QPA_PLATFORM=offscreen python3 tools/verify_meta_doc_export.py
"""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))

OUT = os.path.join(ROOT, "docs/deliverables")
BASE = "元任务开发计划_2026-10_2027-12"
FILES = [os.path.join(OUT, BASE + e) for e in (".md", ".docx", ".pdf")]
PASS, FAIL = [], []


def chk(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


from PyQt5.QtWidgets import QApplication, QPushButton  # noqa: E402

app = QApplication.instance() or QApplication([])
import veh6_config_page as V  # noqa: E402

print("=== ① 起真页面 ===")
page = V.ConfigCenterPage()
tabs = page.tabs if hasattr(page, "tabs") else None
chk("ConfigCenterPage 构造成功", page is not None)
if tabs is None:
    print("⛔ 页面没有 tabs 属性, 后续无法核")
    sys.exit(1)
tabtexts = [tabs.tabText(i) for i in range(tabs.count())]
chk("「📋 任务配置」页存在", any("任务配置" in t for t in tabtexts), " | ".join(tabtexts))
idx_task = next((i for i, t in enumerate(tabtexts) if "任务配置" in t), -1)
chk("任务配置在首屏(tab 0)", idx_task == 0, f"index={idx_task}")

print("\n=== ② 该页上的按钮 ===")
task_w = tabs.widget(idx_task) if idx_task >= 0 else None
btns = task_w.findChildren(QPushButton) if task_w else []
names = [b.text() for b in btns]
print("   任务配置页按钮:", " | ".join(names))
mt_btns = [b for b in btns if "元任务计划" in b.text()]
chk("任务配置页有「元任务计划 (Word/PDF)」按钮", bool(mt_btns))
if mt_btns:
    chk("按钮提示写明产物路径", "docs/deliverables" in (mt_btns[0].toolTip() or ""),
        (mt_btns[0].toolTip() or "")[:60].replace("\n", " "))

print("\n=== ③④ 注册表接线 ===")
chk("DOC_SCRIPTS 有 metaplan", "metaplan" in V.DOC_SCRIPTS,
    str(V.DOC_SCRIPTS.get("metaplan")))
if "metaplan" in V.DOC_SCRIPTS:
    label, script, args = V.DOC_SCRIPTS["metaplan"]
    chk("指向 tools/export_meta_doc.py 且文件真存在",
        script == "export_meta_doc.py" and os.path.exists(os.path.join(ROOT, "tools", script)),
        f"tools/{script}")

print("\n=== ⑤ 真点一次按钮 ===")
before = {f: (os.path.getmtime(f) if os.path.exists(f) else 0) for f in FILES}
t0 = time.time()
if mt_btns:
    mt_btns[0].click()
    app.processEvents()
    for _ in range(90):                      # 最多等 180s (导出含 LibreOffice 两趟转换)
        app.processEvents()
        time.sleep(2)
        if all(os.path.exists(f) and os.path.getmtime(f) > before[f] for f in FILES):
            break
dt = time.time() - t0
for f in FILES:
    ext = os.path.splitext(f)[1]
    fresh = os.path.exists(f) and os.path.getmtime(f) > before[f]
    size = os.path.getsize(f) if os.path.exists(f) else 0
    chk(f"产出 {ext} 且是本次新生成", fresh, f"{size:,} bytes")
chk("导出耗时合理(<200s)", dt < 200, f"{dt:.1f}s")

print("\n=== ⑥ 底部结果面板 ===")
out = getattr(page, "out", None)
txt = out.toPlainText() if out is not None else ""
chk("结果面板给出产物绝对路径", ("docs/deliverables" in txt) or ("元任务开发计划" in txt),
    (txt or "")[:120].replace("\n", " "))
chk("结果面板含一致性结论", "一致性" in txt or "PASS" in txt or "通过" in txt,
    " ".join([ln for ln in txt.split("\n") if "一致" in ln or "PASS" in ln][:1]))

print(f"\n{'='*54}\nPASS {len(PASS)} / FAIL {len(FAIL)}")
if FAIL:
    print("FAIL 项: " + "; ".join(FAIL))
sys.exit(1 if FAIL else 0)
