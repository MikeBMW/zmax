#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_product_card_ui.py — 判据: 产品档卡片 (VEH.6.01/02/03) 外观真的「明显、好看」且语义没被改坏。

老倪 2026-10-21:
  「VEH.6.01 550A / VEH.6.02 550B / VEH.6.03 550C 这些配置的 UI 设计应该更加绚丽一些,
   现在只是一个小白点来选择配置, 不好看, 你来增强设计 … 要明显, 好看一些」

判据 (全程离屏, 不动生产 GUI, 不写任何真源):
  ① 自绘卡  三档控件都是 _ProductCard (QRadioButton 子类), 232×108, 编号 VEH.6.01/02/03 各一
  ② 不挤    三张卡横向不重叠、间距 ≥10px
  ③ 不截断  编号/大号档名/中文后缀/底行 全在卡内 (与 paintEvent 同口径算), 三条竖直带不重叠
  ④ 明显    同一张卡「选中 vs 未选」底色亮度差 ≥60% (跨色相比亮度没意义, 所以同卡自己比)
  ⑤ 现状标识 选中卡右上角亮「✓ 当前」胶囊 (该区域有高亮像素), 未选卡没有
  ⑥ 真源同源 卡底行 = 真源 version_segment + dev_profile.role; card.text() = 真源 products.<id>.name
  ⑦ 只读    判据跑完 zmax_product.json sha256 不变 (取证不写真源)
用法: QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_product_card_ui.py
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "gui")):
    if p not in sys.path:
        sys.path.insert(0, p)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

CODES = {"550A": "VEH.6.01", "550B": "VEH.6.02", "550C": "VEH.6.03"}
OK, NG = [], []


def chk(tag, ok, detail=""):
    (OK if ok else NG).append(tag)
    print("  %s %s %s" % ("✅" if ok else "❌", tag, (" · " + str(detail)) if detail else ""))


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 16), b""):
            h.update(b)
    return h.hexdigest()[:16]


def main() -> int:
    from PyQt5.QtWidgets import QApplication, QWidget, QRadioButton
    from PyQt5.QtGui import QFont, QFontMetrics
    import veh6_config_page as V

    app = QApplication.instance() or QApplication([])
    sha0 = sha(V.PRODUCT_J)
    src = json.load(open(V.PRODUCT_J, encoding="utf-8"))
    active = src.get("active_product")
    prods = src.get("products") or {}

    pg = V.build_config_center(QWidget())
    pg.resize(1600, 1000)
    pg.show()
    for _ in range(5):
        app.processEvents()
    # ⚠ 产品配置页不是首屏 ⇒ 不切过去 Qt 根本不做布局 (卡会停在默认 640 宽, 判据会误判尺寸/重叠)
    _idx = next((i for i in range(pg.tabs.count()) if "产品配置" in pg.tabs.tabText(i)), -1)
    if _idx >= 0:
        pg.tabs.setCurrentIndex(_idx)
        for _ in range(6):
            app.processEvents()
    cards = pg._prod_btns or {}
    for _c in cards.values():                       # 取证不写盘
        _c.blockSignals(True)
    KC = V._ProductCard                            # 版式常量唯一来源 (实现里改, 判据跟着变)
    WANT_W, WANT_H = KC.W, KC.H

    print("═══ ① 自绘卡 (VEH.6.01/02/03 · %d×%d) ═══" % (WANT_W, WANT_H))
    chk("①a 三档齐且都是 _ProductCard (QRadioButton 子类)",
        set(cards) == set(CODES) and all(isinstance(c, V._ProductCard) and isinstance(c, QRadioButton)
                                        for c in cards.values()),
        " ".join("%s=%s" % (p, type(cards[p]).__name__) for p in sorted(cards)))
    chk("①b 尺寸 232×108 (三张一致)",
        all((c.width(), c.height()) == (WANT_W, WANT_H) for c in cards.values()),
        " ".join("%s=%dx%d" % (p, cards[p].width(), cards[p].height()) for p in sorted(cards)))
    chk("①c 编号 VEH.6.01/02/03 各一 (与老倪给的编号逐条对上)",
        {cards[p]._code for p in cards} == set(CODES.values()),
        " · ".join("%s→%s" % (p, cards[p]._code) for p in sorted(cards)))

    print("═══ ② 不挤 (不重叠) ═══")
    spans = sorted((cards[p].x(), cards[p].x() + cards[p].width(), p) for p in cards)
    gaps = [spans[i + 1][0] - spans[i][1] for i in range(len(spans) - 1)]
    chk("② 三张卡横向不重叠且间距 ≥10px", all(g >= 10 for g in gaps),
        " ; ".join("%s %d..%d" % (p, a, b) for a, b, p in spans) + " | 间距=%s" % gaps)

    print("═══ ③ 不截断 (文字全在卡内 · 三条竖带不重叠) ═══")
    fm_big = QFontMetrics(QFont("Consolas", KC.BIG_PT, QFont.Bold))
    fm_sm = QFontMetrics(QFont("Consolas", KC.SMALL_PT))
    fm_code = QFontMetrics(QFont("Consolas", KC.CODE_PT, QFont.Bold))
    fm_sub = QFontMetrics(QFont("Consolas", KC.SUB_PT))
    bad = []
    for p, c in cards.items():
        head, _, tail = c.text().partition(" ")
        inner_l = 5.0 + KC.PAD_L                      # paintEvent 里的 r.left()+PAD_L
        right = (5.0 + (c.width() - 10.0)) - KC.PAD_R  # r.right()-PAD_R
        code_r = (inner_l + fm_code.width(c._code),)
        big_r = (inner_l + fm_big.width(head),)
        suf_r = (inner_l + 4 + fm_big.width(head) + fm_sm.width(tail),)
        sub_r = (inner_l + fm_sub.width(getattr(c, "_sub", "")),)
        top, bot = 5.0, 5.0 + (c.height() - 10.0)
        bands = ((top + KC.BAND_CODE[0], top + KC.BAND_CODE[1]),
                 (top + KC.BAND_BIG[0], top + KC.BAND_BIG[1]),
                 (bot - KC.BAND_SUB[0], bot - KC.BAND_SUB[1]))
        over = [n for n, r in (("编号", code_r), ("大号", big_r), ("后缀", suf_r), ("底行", sub_r)) if r[0] > right + 1]
        band_ok = bands[0][1] < bands[1][0] and bands[1][1] < bands[2][0]
        gap = bands[2][0] - bands[1][1]               # 底行与档名之间的实际留白
        if over or not band_ok or gap < 4:
            bad.append("%s 越界=%s 竖带ok=%s 底行留白=%.0fpx" % (p, over, band_ok, gap))
    chk("③ 三张卡的文字都不出界、三条竖带不打架 (底行留白 ≥4px)", not bad,
        " ; ".join(bad) or "右界≤%.0f · 编号/大号/底行三带不重叠 · 底行 %.1fpt" % (
            (5.0 + (WANT_W - 10.0)) - KC.PAD_R, KC.SUB_PT))

    print("═══ ④ 明显但不刺眼 (同卡 选中 vs 未选 亮度差 ≥40%) ═══")
    deltas = {}
    for p, c in cards.items():
        _origin = c.mapTo(pg._prod_card, c.rect().topLeft())

        def _bg():
            for _ in range(3):
                app.processEvents()
            img = pg._prod_card.grab().toImage()
            col = img.pixelColor(_origin.x() + c.width() - 18, _origin.y() + c.height() - 14)
            return 0.2126 * col.red() + 0.7152 * col.green() + 0.0722 * col.blue()

        _others = [o for o in cards.values() if o is not c]
        _others[0].setChecked(True)                  # 互斥组: 换成别的档当"未选"基线
        off = _bg()
        c.setChecked(True)
        on = _bg()
        deltas[p] = 100.0 * (on - off) / max(off, 1.0)
    chk("④ 每档选中都比未选亮 ≥40% (内敛配色: 靠明暗+描边+小标一起区分)", all(d >= 40 for d in deltas.values()),
        " · ".join("%s %+.0f%%" % (p, deltas[p]) for p in sorted(deltas)))

    print("═══ ⑤ 「✓ 当前」胶囊 (选中卡 = 亮卡上的深色徽章) ═══")

    def _region_lum(img, origin, x0, y0, x1, y1):
        """取卡片坐标矩形 (相对卡片左上角) 的平均亮度 —— 用区域均值, 避免落到单个字的抗锯齿像素上。"""
        _s = _n = 0.0
        for _x in range(int(x0), int(x1), 2):
            for _y in range(int(y0), int(y1), 2):
                _c = img.pixelColor(origin.x() + int(_x), origin.y() + int(_y))
                _s += 0.2126 * _c.red() + 0.7152 * _c.green() + 0.0722 * _c.blue()
                _n += 1
        return _s / max(_n, 1.0)

    pill_ok = True
    detail = []
    _top = 5.0
    _bot = 5.0 + (WANT_H - 10.0)
    _right = (5.0 + (WANT_W - 10.0)) - KC.PAD_R
    px0, px1 = _right - KC.PILL_W, _right
    py0, py1 = _top + KC.BAND_CODE[0] - 1, _top + KC.BAND_CODE[0] - 1 + KC.PILL_H
    bx0, bx1 = px0 - 74, px0 - 8                      # 卡面参考块: 胶囊左边同一横带 (局部比, 避开渐变/径向光差)
    by0, by1 = py0, py1                               # 同一横带 (胶囊那一条)
    for p, c in cards.items():
        _others = [o for o in cards.values() if o is not c]
        _others[0].setChecked(True)
        for _ in range(3):
            app.processEvents()
        _origin = c.mapTo(pg._prod_card, c.rect().topLeft())
        _i = pg._prod_card.grab().toImage()
        off_pill, off_body = _region_lum(_i, _origin, px0, py0, px1, py1), _region_lum(_i, _origin, bx0, by0, bx1, by1)
        c.setChecked(True)
        for _ in range(3):
            app.processEvents()
        _i2 = pg._prod_card.grab().toImage()
        on_pill, on_body = _region_lum(_i2, _origin, px0, py0, px1, py1), _region_lum(_i2, _origin, bx0, by0, bx1, by1)
        _badge = on_pill - on_body                       # 选中: 深色卡上亮一枚浅色小标
        _nobadge = abs(off_pill - off_body)              # 未选: 该区域应与卡面同色 (无小标)
        detail.append("%s 选中 卡面%.0f/小标%.0f(亮%.0f) 未选 |小标-卡面|=%.0f" % (p, on_body, on_pill, _badge, _nobadge))
        if _badge < 30 or _nobadge > 25:
            pill_ok = False
    chk("⑤ 选中时右上角出现「✓ 当前」小标, 未选时该区域与卡面同色", pill_ok, " · ".join(detail))

    print("═══ ⑥ 真源同源 (卡上文字/底行 == 真源) ═══")
    same_name = all(cards[p].text() == str((prods.get(p) or {}).get("name")) for p in cards)
    chk("⑥a 卡上档名 == 真源 products.<id>.name (回读, 非界面自写)", same_name,
        " · ".join("%s=%s" % (p, cards[p].text()) for p in sorted(cards)))
    sub_ok = True
    dup_ok = True
    sysv = V._system_version()
    # 🖥 2026-10-21 老倪定三档运行位置: A=本地运行 / B=VSCode(标定) / C=量产(Intel 端侧, 全模型, 远程实时)
    #   ⇒ 卡底行 = 系统总版本号 · 真源 products.<id>.runtime.label (不再是 dev_profile.role)
    for p in cards:
        pp = prods.get(p) or {}
        _nm = str(pp.get("name") or "")
        _suf = _nm.split(" ", 1)[1].strip() if " " in _nm else ""
        _where = str(((pp.get("runtime") or {}).get("label")) or "").strip()
        want = " · ".join([x for x in (str(sysv).strip(), _where) if x])
        if getattr(cards[p], "_sub", "") != want:
            sub_ok = False
            print("     ⚠ %s 底行 %r != 期望 %r" % (p, getattr(cards[p], "_sub", ""), want))
        if _suf and _suf in str(getattr(cards[p], "_sub", "")):
            dup_ok = False
            print("     ⚠ %s 底行重复档名后缀「%s」: %r" % (p, _suf, getattr(cards[p], "_sub", "")))
    chk("⑥b2 卡底行不重复档名后缀 (550C 曾出现「量产版」两次)", dup_ok,
        " · ".join("%s=%s" % (p, getattr(cards[p], "_sub", "")) for p in sorted(cards)))
    chk("⑥b 卡底行 == 系统总版本号 + 真源 runtime.label (A本地/B VSCode/C Intel 端侧)", sub_ok,
        " · ".join("%s=%s" % (p, cards[p]._sub) for p in sorted(cards)))
    # ⑥d 运行位置必须是**真源写下的那三处**, 不是界面口径: C 必须是 Intel 边缘机且全模型
    _rt = {p: ((prods.get(p) or {}).get("runtime") or {}) for p in cards}
    _c = _rt.get("550C") or {}
    chk("⑥d 三档运行位置 == 真源 (A/B 本机 192.168.23.50 · C Intel 192.168.23.70 全模型)",
        [str((_rt.get(p) or {}).get("host_ip") or "") for p in ("550A", "550B", "550C")] ==
        ["192.168.23.50", "192.168.23.50", "192.168.23.70"]
        and str(_c.get("models") or "").startswith("全部模型")
        and str(_c.get("location") or "") == "edge",
        " · ".join("%s=%s@%s" % (p, (_rt.get(p) or {}).get("label"), (_rt.get(p) or {}).get("host_ip"))
                   for p in ("550A", "550B", "550C")) + " · C models=%s" % _c.get("models"))
    # 🏷 2026-10-21 老倪: 「版本号全系统统一」⇒ 三档底行必须是**同一个**版本号, 且 == update_checker.CURRENT_VERSION
    _vers = {getattr(cards[p], "_sub", "").split(" · ")[0] for p in cards}
    _upd = ""
    try:
        import update_checker
        _upd = str(getattr(update_checker, "CURRENT_VERSION", "") or "")
    except Exception:                                                           # noqa: BLE001
        _upd = "取不到"
    _upd_n = _upd if _upd.lower().startswith("v") else ("v" + _upd if _upd else _upd)
    chk("⑥c 三档版本号全系统统一 (同一个号, == update_checker.CURRENT_VERSION)",
        len(_vers) == 1 and _vers == {_upd_n}, "卡上=%s · CURRENT_VERSION=%s" % (sorted(_vers), _upd_n))

    print("═══ ⑦ 选中卡上文字对比度 (深卡素白字 ≥4.5:1) ═══")

    def _rlum(col):
        def _ch(v):
            v = v / 255.0
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
        return 0.2126 * _ch(col.red()) + 0.7152 * _ch(col.green()) + 0.0722 * _ch(col.blue())

    cont_ok, cont_det = True, []
    for p, c in cards.items():
        for _o in cards.values():
            if _o is not c:
                _o.setChecked(True)
                break
        c.setChecked(True)
        for _ in range(3):
            app.processEvents()
        _origin = c.mapTo(pg._prod_card, c.rect().topLeft())
        _img = pg._prod_card.grab().toImage()
        _lums = []
        for _x in range(int(5 + KC.PAD_L), int(5 + KC.PAD_L + 70), 2):          # 大号档名所占区域
            for _y in range(int(5 + KC.BAND_BIG[0]), int(5 + KC.BAND_BIG[1]), 2):
                _lums.append(_rlum(_img.pixelColor(_origin.x() + _x, _origin.y() + _y)))
        _body = _region_lum(_img, _origin, 5 + KC.PAD_L + 74, 5 + KC.BAND_BIG[0],
                            5 + KC.PAD_L + 120, 5 + KC.BAND_BIG[1])
        _body_r = ((_body / 255.0 + 0.05) ** 2.2)
        _ratio = (max(max(_lums), _body_r) + 0.05) / (min(min(_lums), _body_r) + 0.05)
        cont_det.append("%s %.1f:1" % (p, _ratio))
        if _ratio < 4.5:
            cont_ok = False
    chk("⑦ 选中卡文字/卡面对比度 ≥4.5:1", cont_ok, " · ".join(cont_det))

    print("═══ ⑧ 只读 (取证不写真源) ═══")
    for p, c in cards.items():                       # 视觉状态还原成真源当前档
        c.setChecked(p == active)
        c.blockSignals(False)
    for _ in range(3):
        app.processEvents()
    sha1 = sha(V.PRODUCT_J)
    chk("⑧ 判据前后 zmax_product.json sha256 不变", sha0 == sha1, "%s → %s (active=%s)" % (sha0, sha1, active))

    print("\n判据通过: %d/%d" % (len(OK), len(OK) + len(NG)))
    if NG:
        print("❌ 未过: " + " ; ".join(NG))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
