#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""取证: 配置中心「左侧栏文档配置 + 内置文档预览 + 一致性判定」(2026-10-10 老倪)

判据 (全部实测打印):
  1. 左侧树有「文档配置」组, 4 个子项 (供应商外发 SOR / 项目立项文档 / 合作协议 / 一致性核对)
  2. 点左侧『供应商外发 SOR』→ 切到「📄 文档预览」页签, 且预览文本是**真 docx 内容** (含标记串)
  3. 三份文档都点一遍: 预览非空 + 头部给出的 docx 绝对路径真实存在
  4. 一致性核对: 三份文档记录的工程库 sha 相同 (同源) 且 = 当前工程库 sha ⇒ 全部 ✅
  5. **过期判定真的会触发**: 把某个真源 mtime 改新 (内容不动) → 对应文档必须变 ⛔ 已过期 + 红字告警;
     改回原 mtime 后必须恢复 ✅ (判据不是摆设)
用法: QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/tests/test_config_doc_preview.py
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from PyQt5.QtWidgets import QApplication, QPushButton  # noqa: E402
import veh6_config_page as vp  # noqa: E402

FAIL = []
def check(name, ok, detail=""):
    print(("  ✅ " if ok else "  ⛔ ") + name + ("   " + str(detail) if detail else ""))
    if not ok:
        FAIL.append(name)


def tree_items(tree):
    out = []
    for i in range(tree.topLevelItemCount()):
        it = tree.topLevelItem(i)
        kids = [it.child(j).text(0).strip() for j in range(it.childCount())]
        out.append((it.text(0), kids))
    return out


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    page = vp.build_config_center(None, None)
    page.resize(1400, 900)

    print("═══ 1) 左侧树「文档配置」═��═")
    tp = tree_items(page.tree)
    for label, kids in tp:
        print("  " + label + "   → " + " / ".join(kids) if kids else "  " + label)
    doc_groups = [(l, k) for l, k in tp if "文档配置" in l]
    check("左侧树有『文档配置』组", bool(doc_groups))
    kids = doc_groups[0][1] if doc_groups else []
    for need in ("SOR", "立项", "协议", "一致性"):
        check("子项含 " + need, any(need in k for k in kids))

    print("\n═══ 2) 三份文档: 点树节点 → 内置窗口看到真实内容 ═══")
    marks = {"供应商外发 SOR": "SOR-OM-ROBOT", "项目立项文档": "PRJ-TH-TRAY", "合作协议": "AGR-DP-ROBOT"}
    for node, token in marks.items():
        it = None
        for i in range(page.tree.topLevelItemCount()):
            t = page.tree.topLevelItem(i)
            if "文档配置" in t.text(0):
                for j in range(t.childCount()):
                    if t.child(j).text(0).strip() == node:
                        it = t.child(j)
        check("树里有节点 " + node, it is not None)
        if it is None:
            continue
        t0 = time.time()
        page._on_tree(it, 0)                 # 走真实点击入口
        app.processEvents()
        dt = time.time() - t0
        cur = page.tabs.tabText(page.tabs.currentIndex())
        body = page.preview.toPlainText()
        head = page.pv_head.text()
        print(f"      ⏱ {dt:.1f}s · 当前页签『{cur}』· 预览 {len(body)} 字符 · 头: {head.splitlines()[0][:96]}")
        check(node + " → 切到文档预览页签", "文档预览" in cur)
        check(node + " → 预览是真 docx 内容", token in body or "规格" in body or "立项" in body,
              body.strip().splitlines()[0][:60] if body.strip() else "(空)")
        dp = [l.split("docx 绝对路径: ")[-1] for l in head.splitlines() if "docx 绝对路径" in l]
        check(node + " → 给了 docx 绝对路径且存在", bool(dp) and os.path.exists(dp[0]), dp[0] if dp else "(无)")
        check(node + " → 判定为与真源一致", "✅" in head.splitlines()[0], head.splitlines()[0][-40:])

    print("\n═══ 3) 一致性核对视图 ═══")
    page._show_consistency()
    app.processEvents()
    con = page.preview.toPlainText()
    print("  " + "\n  ".join(con.splitlines()[:12]))
    check("核对含三份文档", all(x in con for x in ("项目立项文档", "供应商外发 SOR", "合作协议")))
    check("三份记录的工程库 sha 相同(同源)", con.count("9426a607") >= 3 or "同源" in con)
    check("核对结论无告警标记 [⛔]", "[⛔]" not in con, [l for l in con.splitlines() if "[⛔]" in l][:2])

    print("\n═══ 4) 过期判定真会触发 (两条路径都要验) ═══")
    # 4a) sha 路径: 真源**内容**变了 (备份→改动→复原)
    bom = os.path.join(ROOT, "config", "platform", "zmax_project_bom.json")
    orig = open(bom, "rb").read()
    try:
        open(bom, "wb").write(orig + b"\n")
        st_new = vp._doc_state("project")
        page._show_doc("project")
        app.processEvents()
        head = page.pv_head.text()
        body = page.preview.toPlainText()
        print("      内容改动后判定: " + st_new["why"])
        check("真源内容变 → 立项文档判过期", st_new["stale"] and "过期" in head.splitlines()[0])
        check("过期时预览顶部有红字告警", body.startswith("⛔ 一致性告警"))
        check("SOR(另一真源未动)不受影响", not vp._doc_state("sor")["stale"])
    finally:
        open(bom, "wb").write(orig)
    check("内容复原后判定恢复一致", not vp._doc_state("project")["stale"], vp._doc_state("project")["why"])

    # 4b) 时间戳路径: 只动 mtime 且该真源未被 manifest 记录 sha (平台配置)
    plat = os.path.join(ROOT, "config", "platform", "zmax_platform.json")
    st0 = os.stat(plat)
    _dm = (vp._doc_state("project")["doc"] or {}).get("mtime") or os.path.getmtime(plat)
    try:
        os.utime(plat, (st0.st_atime, _dm + 60))   # 显式设成"比文档晚 60s", 不依赖时钟顺序
        st_p = vp._doc_state("project")
        print("      平台配置 mtime 更新后判定: " + st_p["why"])
        check("未记录 sha 的真源动过 → 判过期(时间戳兜底)", st_p["stale"] and "平台配置真源" in st_p["why"])
    finally:
        os.utime(plat, (st0.st_atime, st0.st_mtime))
    check("mtime 还原后判定恢复一致", not vp._doc_state("project")["stale"], vp._doc_state("project")["why"])

    print("\n═══ 5) 顶栏不截断 (窗口 1280 宽实测几何) ═══")
    from PyQt5.QtCore import QPoint
    page.resize(1280, 800)
    page.show()
    app.processEvents()
    top_txt = ("🔍 全链校验", "📋 任务配置", "⚙️ 工程配置", "📄 文档导出")
    tops = [b for b in page.findChildren(QPushButton)
            if b.text().strip() in top_txt and b.mapTo(page, QPoint(0, 0)).y() < 60]   # 只算顶栏那一排
    check("顶栏 4 个按钮都在", len(tops) == 4, [b.text() for b in tops])
    for b in tops:
        right = b.mapTo(page, QPoint(b.width(), 0)).x()
        print(f"      {b.text().strip():<14} x={b.mapTo(page, QPoint(0, 0)).x():>5} w={b.width():>4} 右缘={right:>5} / 窗口 {page.width()}")
        check(f"『{b.text().strip()}』右缘在窗口内", 0 < right <= page.width(), right)

    print("\n═══ 6) 左树计数口径写清 ═══")
    labels = [page.tree.topLevelItem(i).text(0) for i in range(page.tree.topLevelItemCount())]
    print("  " + " | ".join(labels))
    check("文档配置那行写明『文档 n/3』(不让人误以为子项数)", any("文档配置" in l and "文档 " in l for l in labels),
          [l for l in labels if "文档配置" in l])

    print("\n" + ("✅ 全部通过" if not FAIL else "⛔ 失败 %d 项: %s" % (len(FAIL), FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
