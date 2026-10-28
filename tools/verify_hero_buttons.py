#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""首页 hero 卡「右上角按钮排」判据 (老倪 2026-10-15)

老倪原话: 「主控制台, 右上角的 按钮 smolvla_lew, 升级等, 就保留一个分享功能, 其余按钮都删掉
           (如果功能还有用, 则备份一下)」

判据 (离屏建真控件树, 读真控件, 不是 grep 印象):
  ① hero 行右侧**只剩** 📱 分享 —— 逐个 QPushButton 文本枚举, 必须等于 ['📱 分享']
  ② 被删的 7 个按钮文本在 hero 卡里一个都不许出现 (含子串匹配, 防换名复活)
  ③ 📱 分享 的 clicked 有接收者 (不是删剩的死按钮)
  ④ 被删功能的"去向"可达: 源码里 assert 替代入口存在
     · smolvla_lew 仓库 → 菜单「关于 → 🧪 GUI 工程仓库 (smolvla_lew)」
     · 其余各功能另有入口 (同步到GitHub/检查更新/官网/版本同步/解决方案文档/品牌注册材料PPT)
  ⑤ 备份件在位且逐字含被删的 7 个按钮 (可贴回)

用法: cd /home/ubuntu/zmax && ./gui-venv311/bin/python tools/verify_hero_buttons.py
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))

from PyQt5.QtWidgets import QApplication, QPushButton  # noqa: E402

import studio  # noqa: E402

REMOVED = ["smolvla_lew", "同步到GitHub", "升级", "Z-MAX", "版本同步", "解决方案v1.0.4", "PPT汇报"]
KEEP = "📱 分享"
BAK = os.path.join(ROOT, "zmax_data", "backups", "studio_hero_buttons_20261015.py")

rows: list[tuple[str, bool, str]] = []


def chk(tag: str, ok: bool, ev: str) -> None:
    rows.append((tag, ok, ev))
    print("  %s %s  %s" % ("✅" if ok else "❌", tag, ev))


def main() -> int:
    print("═══ 首页 hero 右上角按钮判据 ═══")
    app = QApplication(sys.argv[:1])
    w = studio.HomeWidget()
    hero = w._hero()
    btns = [b for b in hero.findChildren(QPushButton) if b.isVisibleTo(hero)]
    texts = [b.text() for b in btns]
    print("  hero 行按钮实况: %s" % texts)

    chk("① 只剩 📱 分享", texts == [KEEP], "实测 %d 个: %s" % (len(texts), texts))

    leftover = [t for t in texts for k in REMOVED if k in t]
    chk("② 被删按钮一个都不在", not leftover, "残留 %s" % (leftover or "无"))

    share = next((b for b in btns if b.text() == KEEP), None)
    connected = bool(share is not None and share.receivers(share.clicked) > 0)
    chk("③ 📱 分享 有接线 (不是死按钮)", connected,
        "receivers=%s" % (share.receivers(share.clicked) if share is not None else "无按钮"))

    src = open(os.path.join(ROOT, "tools", "gui", "studio.py"), encoding="utf-8").read()
    anchors = {
        "smolvla_lew 仓库→关于菜单": 'act_lew_repo = QAction("🧪 GUI 工程仓库 (smolvla_lew)"',
        "同步到GitHub→菜单": '_menu_sync_to_github',
        "升级→菜单检查更新": 'act_update = QAction("🔄 检查更新"',
        "官网→首页产品大屏卡": '"website"',
        "版本同步→首页卡": '("version",  "🔄", "版本同步"',
        "解决方案文档→文档菜单(v1.0.6)": "L2-Z-MAX解决方案-v1.0.6.md",
        "品牌注册材料PPT→文档菜单": "BRAND-品牌注册材料.pptx",
    }
    missing = [k for k, v in anchors.items() if v not in src]
    chk("④ 7 个功能的替代入口都在", not missing, "缺 %s" % (missing or "无 (7/7 可达)"))

    if os.path.exists(BAK):
        bak = open(BAK, encoding="utf-8").read()
        miss_bak = [k for k in REMOVED if k not in bak]
        chk("⑤ 备份件在位且含全部被删按钮", not miss_bak,
            "%s (%d B) 缺 %s" % (os.path.relpath(BAK, ROOT), os.path.getsize(BAK), miss_bak or "无"))
    else:
        chk("⑤ 备份件在位", False, "缺文件 %s" % BAK)

    bad = [r for r in rows if not r[1]]
    print("─── %d/%d %s" % (len(rows) - len(bad), len(rows), "全绿 PASS" if not bad else "FAIL"))
    # ⚠️ HomeWidget 的构造会拉起硬件采集 QThread (_HwFetcher) ⇒ 正常退出会等它 join 阻塞;
    #    判据已全部打印, 直接 os._exit 收工 (离屏探针, 不写任何唯一依据)。
    sys.stdout.flush()
    os._exit(0 if not bad else 1)


if __name__ == "__main__":
    sys.exit(main())
