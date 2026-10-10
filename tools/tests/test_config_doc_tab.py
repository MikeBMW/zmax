#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""取证: 配置中心「📄 文档交付」页 —— 真建页面 + 真点按钮 + 真出文档 (2026-10-10)

判据 (不靠目测, 全部打印实测值):
  1. 页签存在: tabs 里有「文档交付」, 且页内有 5 个导出按钮 + 3 个工具按钮
  2. 点「📦 三件套导出」真的产出: 面板日志含「同源一致」, 且 outputs/docs_bundle/<新目录>/ 有 3 个 .docx
  3. 产物清单给的是**绝对路径**且文件真实存在 (逐个 os.path.exists)
  4. 点「🧮 BOM/成本/ROI 算账」面板含「回收期」与「关联与对账全通过」
用法: QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/tests/test_config_doc_tab.py
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GUI = os.path.join(ROOT, "tools", "gui")
sys.path.insert(0, GUI)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from PyQt5.QtWidgets import QApplication, QPushButton  # noqa: E402

import veh6_config_page as vp  # noqa: E402

FAIL = []
def check(name, ok, detail=""):
    print(("  ✅ " if ok else "  ⛔ ") + name + ("   " + str(detail) if detail else ""))
    if not ok:
        FAIL.append(name)

def main():
    app = QApplication.instance() or QApplication(sys.argv)
    page = vp.build_config_center(None, None)
    page.resize(1400, 900)

    print("═══ 1) 页签与按钮存在性 ═══")
    titles = [page.tabs.tabText(i) for i in range(page.tabs.count())]
    print("  页签: " + " | ".join(titles))
    check("存在『文档交付』页签", any("文档交付" in t for t in titles))
    idx = [i for i, t in enumerate(titles) if "文档交付" in t][0]
    w = page.tabs.widget(idx)
    btns = [b.text() for b in w.findChildren(QPushButton)]
    print("  按钮: " + " | ".join(btns))
    for need in ("三件套导出", "项目立项文档", "供应商 SOR", "协议", "BOM"):
        check("按钮含 " + need, any(need in b for b in btns))
    check("工具有复制路径按钮", any("复制产物路径" in b for b in btns))
    check("顶栏有『文档导出』入口", any("文档导出" in b.text() for b in page.findChildren(QPushButton)))

    print("\n═══ 2) 真点『📦 三件套导出』═��═")
    before = vp._newest_out_dir("outputs/docs_bundle")
    t0 = time.time()
    hit = [b for b in w.findChildren(QPushButton) if "三件套" in b.text()][0]
    hit.click()                              # 走真实按钮 → _run_doc → 真跑导出器
    app.processEvents()
    dt = time.time() - t0
    log = page.out.toPlainText()
    print("  耗时 %.1fs · 面板日志 %d 字符" % (dt, len(log)))
    print("  " + "\n  ".join(log.strip().splitlines()[-6:]))
    check("面板日志含『同源一致』", "同源一致" in log)
    check("面板日志给了包目录绝对路径", "outputs/docs_bundle/" in log)
    check("面板无异常字样", "⛔" not in log, [l for l in log.splitlines() if "⛔" in l][:2])
    after = vp._newest_out_dir("outputs/docs_bundle")
    check("产物目录是新生成的", after and after != before, after)
    if after:
        docx = [f for f in os.listdir(after) if f.endswith(".docx")]
        print("  包内文件: " + " | ".join(sorted(os.listdir(after))[:8]))
        check("包内 ≥3 份 Word", len([d for d in _all(after) if d.endswith('.docx')]) >= 3,
              len([d for d in _all(after) if d.endswith('.docx')]))

    print("\n═══ 3) 产物清单 = 绝对路径且真实存在 ═══")
    inv = page.docs_out.toPlainText()
    paths = [l.split()[-1] for l in inv.splitlines() if "/home/" in l]
    print("  清单行数 %d · 路径 %d 条" % (len(inv.splitlines()), len(paths)))
    for p in paths[:5]:
        print("    " + p)
    check("清单给绝对路径", all(p.startswith("/home/") for p in paths) and paths)
    check("每条路径文件真实存在", all(os.path.exists(p) for p in paths))

    print("\n═══ 4) 真点『🧮 BOM/成本/ROI 算账』═══")
    b2 = [b for b in w.findChildren(QPushButton) if "BOM" in b.text()][0]
    b2.click()
    app.processEvents()
    log2 = page.out.toPlainText()
    print("  " + "\n  ".join(log2.strip().splitlines()[-5:]))
    check("日志含『回收期』", "回收期" in log2)
    check("日志含『关联与对账全通过』", "关联与对账全通过" in log2)

    print("\n═══ 5) 复制路径按钮真的进了剪贴板 ═══")
    bc = [b for b in w.findChildren(QPushButton) if "复制产物路径" in b.text()][0]
    bc.click()
    app.processEvents()
    cb = QApplication.clipboard().text()
    check("剪贴板含绝对路径", "/home/ubuntu/zmax/outputs/" in cb, cb.splitlines()[0] if cb else "(空)")

    print("\n" + ("✅ 全部通过 (%d 项)" % (0, ) if not FAIL else "⛔ 失败 %d 项: %s" % (len(FAIL), FAIL)))
    return 1 if FAIL else 0


def _all(d):
    out = []
    for r, _ds, fs in os.walk(d):
        for f in fs:
            out.append(os.path.join(r, f))
    return out


if __name__ == "__main__":
    sys.exit(main())
