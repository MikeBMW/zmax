#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_ui_metrics.py — 📐 UI 形状/字体量化取证 (真建窗 · 离屏 · 与现场同口径)  2026-10-10

老倪:
  「你要优化UI, 现在的UI形状和字体不好看, 而且没有与全系统数据同步」
本工具把"不好看"量化成可复核的数字, 逐页真建 Qt 控件后测量 5 类指标:

  ① 字号分布 (pt → px) × DPI        —— 每页各字号(pt/px)的控件计数 + 实测屏幕 DPI
  ② 文本截断                        —— 按 QLabel 真实换行口径 (wordWrap→boundingRect 高度) 与按钮 sizeHint
                                       口径, 列出每个被裁控件 (页名/类名/文字/控件尺寸/所需尺寸/模式)
  ③ 控件高度/间距离群               —— 同类"控件型"部件高度与中位数差 >30% 者标出
  ④ 对比度 (WCAG)                   —— 前景/背景色比值, 正文 <4.5 / 大字 <3.0 列出
  ⑤ 超长 URL / 单行文本溢出         —— 被裁且含 URL 或超长(>80字符)的单行文本

自证 (negative control): 每次运行都额外测量一个**故意造缺陷**的页面 (超长单行 QLabel + 被高度裁掉的
  换行 QLabel + 低对比配色 QLabel), 若检测器没抓到它, 说明检测本身失效 —— 自证失败 = 退出码 1。
  这样"真实页面零缺陷"才有意义 (不是检测器瞎了)。

用法:
  QT_QPA_PLATFORM=offscreen QT_FONT_DPI=192 gui-venv311/bin/python tools/verify_ui_metrics.py [--json] [--dpi N]
  (--json 输出机器可读; 退出码: 有截断 或 对比度不达标 或 自证失败 = 1)
"""
import argparse
import json
import os
import statistics
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # 仓库根
SELF = os.path.abspath(__file__)
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))

# (label, module, class, ctor_kind)  ctor_kind: "plain" | "navcb" | "none_arg"
PAGE_REGISTRY = [
    ("home",          "studio",          "HomeWidget",            "plain"),
    ("dataset",       "studio",          "DatasetModule",         "plain"),
    ("training",      "studio",          "TrainingModule",        "plain"),
    ("evaluation",    "studio",          "EvalModule",            "plain"),
    ("hardware",      "studio",          "HardwareModule",        "plain"),
    ("config",        "studio",          "ConfigModule",          "plain"),
    ("monitor",       "studio",          "MonitorModule",         "plain"),
    ("plugging",      "studio",          "PluggingSceneModule",   "plain"),
    ("architecture",  "studio",          "ArchitectureModule",    "plain"),
    ("dataspace",     "studio",          "DataSpaceModule",       "none_arg"),
    ("simulink",      "simulink_module", "SimulinkModule",        "plain"),
    ("platform_spec", "platform_spec",   "PlatformSpecPage",      "navcb"),
    ("param_center",  "param_center",    "ParamCenterPage",       "plain"),
    ("config_meta",   "config_meta_panel", "ConfigMetaPanel",     "plain"),
]

# 视为"同类控件"参与高度离群检测的类 (应统一高度的交互件)
CONTROL_CLASSES = {"QPushButton", "QToolButton", "QLineEdit", "QComboBox", "QCheckBox",
                   "QRadioButton", "QSpinBox", "QDoubleSpinBox", "QAbstractSpinBox"}
TEXT_CLASSES = {"QLabel", "QPushButton", "QToolButton", "QCheckBox", "QRadioButton", "QCommandLinkButton"}
NEG_LABEL = "__negative_control__"


# ══════════════════════════════════════════════════════════════════════════════
# 颜色解析 / WCAG
# ══════════════════════════════════════════════════════════════════════════════
import re                                                                      # noqa: E402

_RE_FG = re.compile(r"(?<![-\w])color\s*:\s*([^;}\n]+)", re.I)
_RE_BG = re.compile(r"background(?:-color)?\s*:\s*([^;}\n]+)", re.I)


def _parse_color(s):
    """解析 CSS 颜色。注意: CSS 的 #RRGGBBAA 是**alpha 在后**, 而 QColor('#...') 当 #AARRGGBB 读 —
    必须自己拆, 否则 #bc8cff18 会被错读成 #8cff18。"""
    from PyQt5.QtGui import QColor
    if not s:
        return None
    s = s.strip()
    if not s or s.lower() in ("transparent", "none", "inherit"):
        return None
    if s.startswith("qlineargradient") or s.startswith("qradialgradient"):
        return None
    if s.startswith("rgba(") or s.startswith("rgb("):
        m = re.findall(r"[\d.]+", s)
        if len(m) >= 3:
            a = float(m[3]) if len(m) >= 4 else 1.0
            c = QColor(int(float(m[0])), int(float(m[1])), int(float(m[2])))
            c.setAlphaF(max(0.0, min(1.0, a)))
            return c
        return None
    m = re.match(r"^#([0-9a-fA-F]{3,8})\b", s)
    if m:
        h = m.group(1)
        try:
            if len(h) == 3:
                c = QColor(int(h[0] * 2, 16), int(h[1] * 2, 16), int(h[2] * 2, 16))
            elif len(h) == 4:                                    # #RGBA (alpha 在后)
                c = QColor(int(h[0] * 2, 16), int(h[1] * 2, 16), int(h[2] * 2, 16))
                c.setAlpha(int(h[3] * 2, 16))
            elif len(h) == 6:
                c = QColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
            elif len(h) == 8:                                    # #RRGGBBAA (alpha 在后)
                c = QColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
                c.setAlpha(int(h[6:8], 16))
            else:
                return None
            return c
        except ValueError:
            return None
    c = QColor(s.split()[0])
    return c if c.isValid() else None


def _style_color(w, rx):
    """在本控件及祖先 stylesheet 里找第一个 color/background 声明 (QSS 会继承)。"""
    node = w
    while node is not None:
        try:
            ss = node.styleSheet() or ""
        except Exception:                                                      # noqa: BLE001
            ss = ""
        if ss:
            m = rx.search(ss)
            if m:
                c = _parse_color(m.group(1))
                if c is not None:
                    return c
        node = node.parentWidget()
    return None


def _composite(top, bottom):
    from PyQt5.QtGui import QColor
    a = top.alphaF()
    r = int(round(top.red() * a + bottom.red() * (1 - a)))
    g = int(round(top.green() * a + bottom.green() * (1 - a)))
    b = int(round(top.blue() * a + bottom.blue() * (1 - a)))
    return QColor(r, g, b)


def _effective_bg(w, _depth=0):
    """解析控件真实背景: 自身 stylesheet → 祖先; 半透明者与其父背景合成。"""
    from PyQt5.QtGui import QPalette
    from PyQt5.QtWidgets import QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QAbstractSpinBox
    if w is None or _depth > 12:
        return QPalette().color(QPalette.Window)
    c = _style_color(w, _RE_BG)
    if c is None:
        pal = w.palette()
        is_input = isinstance(w, (QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QAbstractSpinBox))
        c = pal.color(QPalette.Base if is_input else QPalette.Window)
    if c.alphaF() >= 0.999:
        return c
    parent = w.parentWidget()
    if parent is None:
        return _composite(c, c)
    return _composite(c, _effective_bg(parent, _depth + 1))


def _lum(c):
    def ch(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c.red()) + 0.7152 * ch(c.green()) + 0.0722 * ch(c.blue())


def _ratio(fg, bg):
    l1, l2 = _lum(fg), _lum(bg)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


# ══════════════════════════════════════════════════════════════════════════════
# 子进程: 真建一页并测量
# ══════════════════════════════════════════════════════════════════════════════
def _label_size(text, font, cw, wordwrap, richtext):
    """精确算 QLabel 所需尺寸 (富文本走 QTextDocument, 纯文本走同一个; 比手算 advance 准)。"""
    from PyQt5.QtGui import QTextDocument
    doc = QTextDocument()
    doc.setDefaultFont(font)
    doc.setDocumentMargin(0)     # QLabel 默认无文档边距; 否则每边 +4px 造成 ~8px 系统性误报
    if richtext:
        doc.setHtml(text)
    else:
        doc.setPlainText(text)
    doc.setTextWidth(cw if wordwrap else -1)
    sz = doc.size()
    return sz.width(), sz.height()


def _measure_widget(w, page):
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QFontMetrics
    from PyQt5.QtWidgets import QLabel

    out = {"page": page, "fonts": {}, "trunc": [], "height_outliers": [],
           "contrast": [], "overflow": []}
    widgets = [w] + w.findChildren(object)
    fonts = {}
    for x in widgets:
        try:
            f = x.font()
            fm = QFontMetrics(f)
            px = fm.height()
            pt = round(f.pointSizeF(), 1)
            key = ("%gpt/%dpx" % (pt, px)) if pt > 0 else ("[px]%dpx" % px)   # px 设字的字体 pointSizeF 为 -1
            fonts[key] = fonts.get(key, 0) + 1
        except Exception:                                                      # noqa: BLE001
            continue
    out["fonts"] = fonts

    heights = {}
    for x in widgets:
        cn = type(x).__name__
        if cn not in CONTROL_CLASSES:
            continue
        try:
            if x.isVisible() and x.width() > 0 and x.height() > 0:
                heights.setdefault(cn, []).append(x)
        except Exception:                                                      # noqa: BLE001
            continue
    for cn, xs in heights.items():
        hs = [x.height() for x in xs]
        if len(hs) < 3:
            continue
        med = statistics.median(hs)
        if med <= 0:
            continue
        for x in xs:
            if abs(x.height() - med) / med > 0.30:
                out["height_outliers"].append(
                    {"class": cn, "w": x.width(), "h": x.height(), "median_h": med,
                     "text": (x.text() if hasattr(x, "text") else "")[:48]})

    for x in widgets:
        cn = type(x).__name__
        if cn not in TEXT_CLASSES:
            continue
        try:
            if not x.isVisible() or x.width() <= 0 or x.height() <= 0:
                continue
        except Exception:                                                      # noqa: BLE001
            continue
        text = ""
        try:
            text = x.text() or ""
        except Exception:                                                      # noqa: BLE001
            text = ""
        if not text.strip():
            continue
        # 装饰性单字符/旋转窄条 (如 → ↕) 跳过, 避免误报
        stripped = re.sub(r"<[^>]+>", "", text).strip()
        if len(stripped) <= 1 and not stripped.isalnum():
            continue
        if x.height() > 3 * max(1, x.width()) and len(stripped) <= 3:
            continue
        cr = x.contentsRect()
        cw, ch = max(1, cr.width()), max(1, cr.height())
        full_w = max(1, x.width())       # 单行可用宽 = 控件自身宽 (QLabel 常按内容自适宽; 减边距会系统性误报)
        trunc = None
        if cn in ("QPushButton", "QToolButton", "QCheckBox", "QRadioButton", "QCommandLinkButton"):
            try:
                sh = x.sizeHint().width()
            except Exception:                                                  # noqa: BLE001
                sh = 0
            if sh and x.width() < sh - 2:
                trunc = ("btn-width", x.width(), sh)
        else:
            wordwrap = bool(getattr(x, "wordWrap", lambda: False)())
            richtext = False
            try:
                richtext = (x.textFormat() == Qt.RichText) or ("<" in text and ">" in text)
            except Exception:                                                  # noqa: BLE001
                richtext = "<" in text and ">" in text
            nw, nh = _label_size(text, x.font(), cw, wordwrap, richtext)
            if wordwrap:
                if nh > ch + 1:
                    trunc = ("wrap-height", ch, round(nh))
            else:
                if nw > full_w + 2:
                    trunc = ("line-width", full_w, round(nw))
        if trunc:
            is_url = ("http://" in text.lower()) or ("https://" in text.lower())
            rec = {"page": page, "class": cn, "text": stripped[:90], "mode": trunc[0],
                   "have": trunc[1], "need": trunc[2], "wsize": [x.width(), x.height()],
                   "url": is_url, "long": len(stripped) > 80}
            out["trunc"].append(rec)
            if is_url or len(stripped) > 80:
                out["overflow"].append(rec)

        # 对比度 (仅在能解析到前景与背景时判)
        try:
            fg = _style_color(x, _RE_FG)
            if fg is None:
                fg = x.palette().color(x.foregroundRole())
            bg = _effective_bg(x)
            if fg is None or bg is None or bg.alpha() == 0:
                continue
            r = _ratio(fg, bg)
            # 前景≈背景 (比值≈1) 多为颜色继承/解析同一色 (控件实际可见), 不判; 其余按 WCAG 判
            if 0.98 < r < 1.02:
                continue
            fpt = x.font().pointSizeF()
            large = (fpt >= 14.0 and x.font().bold()) or fpt >= 18.0
            thr = 3.0 if large else 4.5
            if r < thr:
                out["contrast"].append(
                    {"page": page, "class": cn, "text": stripped[:48], "ratio": round(r, 2),
                     "need": thr, "fg": fg.name(), "bg": bg.name(), "pt": round(fpt, 1)})
        except Exception:                                                      # noqa: BLE001
            continue

    def _compress(items, keyf):
        agg = {}
        for it in items:
            k = keyf(it)
            if k in agg:
                agg[k]["count"] += 1
            else:
                agg[k] = dict(it)
                agg[k]["count"] = 1
        return list(agg.values())

    out["trunc"] = _compress(out["trunc"],
                             lambda t: (t["class"], t["text"][:48], t["mode"], t["have"], t["need"]))
    out["overflow"] = _compress(out["overflow"], lambda t: (t["class"], t["text"][:60]))
    out["contrast"] = _compress(out["contrast"],
                                lambda t: (t["class"], t["text"][:24], t["fg"], t["bg"], t["ratio"]))
    out["height_outliers"] = _compress(out["height_outliers"],
                                       lambda t: (t["class"], t["h"], t["text"][:30]))
    return out


def _build_page(label):
    """按 PAGE_REGISTRY 真建一页 (或造 negative control)。返回 (widget, err)。"""
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QFont
    from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget

    if label == NEG_LABEL:
        w = QWidget()
        lay = QVBoxLayout(w)
        # ① 超长单行 QLabel (会被裁)
        a = QLabel("HTTP://例" + "x" * 140)
        a.setWordWrap(False)
        a.setFixedSize(120, 22)
        lay.addWidget(a)
        # ② 被高度裁掉的换行 QLabel
        b = QLabel("这是一段足够长的会自动换行的中文说明文字" * 4)
        b.setWordWrap(True)
        b.setFixedSize(200, 18)
        lay.addWidget(b)
        # ③ 低对比配色 (中灰字 on 近黑底, 比值≈2.5 <4.5)
        c = QLabel("低对比文字")
        c.setStyleSheet("color:#555555; background:#101010;")
        lay.addWidget(c)
        return w, None
    for lab, mod, cls, kind in PAGE_REGISTRY:
        if lab != label:
            continue
        try:
            m = __import__(mod)
            C = getattr(m, cls)
            if kind == "navcb":
                try:
                    w = C(nav_cb=lambda *a: None)
                except TypeError:
                    w = C()
            elif kind == "none_arg":
                try:
                    w = C(None)
                except TypeError:
                    w = C()
            else:
                w = C()
            return w, None
        except Exception as e:                                                 # noqa: BLE001
            return None, "%s: %s" % (type(e).__name__, e)
    return None, "unknown page label: %s" % label


def _child(label, out_path, dpi):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    if dpi:
        os.environ["QT_FONT_DPI"] = str(dpi)
    from PyQt5.QtWidgets import QApplication
    app = QApplication(sys.argv[:1])
    w, err = _build_page(label)
    meta = {"label": label, "error": err, "dpi": None}
    if w is not None:
        try:
            app.setStyleSheet(_global_qss())
        except Exception:                                                      # noqa: BLE001
            pass
        # 与现场同口径: 真实主窗口是暗色底, 独立页要放进同色宿主再量 (否则对照度会拿离屏默认浅色底误判)
        from PyQt5.QtWidgets import QVBoxLayout, QWidget
        host = QWidget()
        host.setObjectName("uim_host")
        host.setStyleSheet("QWidget#uim_host{background:#0f1318; color:#e6edf3;}")
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(w)
        w = host
        w.resize(1400, 900)
        w.show()
        for _ in range(6):
            app.processEvents()
        try:
            scr = app.primaryScreen()
            meta["dpi"] = round(scr.logicalDotsPerInch(), 1) if scr else None
        except Exception:                                                      # noqa: BLE001
            pass
        meta["metrics"] = _measure_widget(w, label)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)
        f.flush()
    # 直接退出, 规避部分页面在析构时的 DDS 线程段错 (测量已完成)
    sys.stdout.write("MEASURED %s\n" % label)
    sys.stdout.flush()
    os._exit(0)


def _global_qss():
    """取 studio 的全局 QSS (与现场暗色主题同口径)。失败则空串。"""
    try:
        import studio
        return studio._build_global_qss()
    except Exception:                                                          # noqa: BLE001
        return ""


# ══════════════════════════════════════════════════════════════════════════════
# 父进程: 编排 + 汇总
# ══════════════════════════════════════════════════════════════════════════════
def _run_children(labels, dpi, tmpdir):
    results = []
    for lab in labels:
        op = os.path.join(tmpdir, "ui_%s.json" % lab.replace("/", "_"))
        if os.path.exists(op):
            os.remove(op)
        env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": ""}
        if dpi:
            env["QT_FONT_DPI"] = str(dpi)
        try:
            r = subprocess.run([sys.executable, SELF, "--measure", lab, "--out", op, "--dpi", str(dpi or "")],
                               capture_output=True, text=True, timeout=180, env=env, cwd=ROOT)
            rc = r.returncode
        except subprocess.TimeoutExpired:
            rc = "TIMEOUT"
        meta = None
        if os.path.exists(op):
            try:
                meta = json.load(open(op, encoding="utf-8"))
            except Exception:                                                  # noqa: BLE001
                meta = None
        if meta is None:
            meta = {"label": lab, "error": "子进程无输出 (rc=%s)" % rc, "metrics": None}
        meta["rc"] = rc
        results.append(meta)
    return results


def _fmt_report(results):
    lines = []
    lines.append("═" * 84)
    lines.append("📐 UI 形状/字体量化取证 (离屏真建窗, DPI=%s)" % (results and results[0].get("dpi")))
    lines.append("═" * 84)
    lines.append("%-16s %6s %7s %8s %8s %6s %6s" %
                 ("页面", "控件", "字号种", "截断", "对比不达", "高离群", "溢出"))
    lines.append("-" * 84)
    tot_trunc = tot_contrast = tot_out = 0
    for m in results:
        mt = m.get("metrics")
        if mt is None:
            lines.append("%-16s  ❌ 建窗失败: %s" % (m["label"], m.get("error")))
            continue
        nw = sum(mt["fonts"].values())
        lines.append("%-16s %6d %7d %8d %8d %6d %6d" %
                     (m["label"], nw, len(mt["fonts"]), len(mt["trunc"]), len(mt["contrast"]),
                      len(mt["height_outliers"]), len(mt["overflow"])))
        tot_trunc += sum(t.get("count", 1) for t in mt["trunc"])
        tot_contrast += sum(t.get("count", 1) for t in mt["contrast"])
        tot_out += sum(t.get("count", 1) for t in mt["overflow"])
    lines.append("-" * 84)
    lines.append("合计(按次数): 截断 %d · 对比度不达标 %d · 超长溢出 %d" % (tot_trunc, tot_contrast, tot_out))
    lines.append("")

    # ① 字号分布 (聚合, pt→px)
    agg = {}
    for m in results:
        mt = m.get("metrics")
        if not mt:
            continue
        for k, n in mt["fonts"].items():
            agg[k] = agg.get(k, 0) + n
    lines.append("── ① 字号分布 (聚合; DPI=%s; px=QFontMetrics.height, pt=pointSizeF) ──" %
                 (results[0].get("dpi") if results else "?"))
    for k, n in sorted(agg.items(), key=lambda kv: -kv[1])[:18]:
        lines.append("   %-14s ×%d" % (k, n))
    lines.append("")

    for m in results:
        mt = m.get("metrics")
        if not mt:
            continue
        if mt["trunc"]:
            lines.append("── 文本截断 · %s ──" % m["label"])
            for t in mt["trunc"][:40]:
                lines.append("   [%s] %s 「%s」 控件%dx%d 可用%s→需%s%s" %
                             (t["mode"], t["class"], t["text"][:50], t["wsize"][0], t["wsize"][1],
                              t["have"], t["need"], (" ×%d" % t["count"]) if t.get("count", 1) > 1 else ""))
            if len(mt["trunc"]) > 40:
                lines.append("   … 另 %d 类" % (len(mt["trunc"]) - 40))
        if mt["contrast"]:
            lines.append("── 对比度不达标 · %s ──" % m["label"])
            for t in mt["contrast"][:30]:
                lines.append("   %s 「%s」 fg=%s bg=%s 比值=%.2f (<%.1f) %.0fpt%s" %
                             (t["class"], t["text"][:30], t["fg"], t["bg"], t["ratio"], t["need"], t["pt"],
                              (" ×%d" % t["count"]) if t.get("count", 1) > 1 else ""))
        if mt["height_outliers"]:
            lines.append("── 高度离群 (>30%%) · %s ──" % m["label"])
            for t in mt["height_outliers"][:20]:
                lines.append("   %s h=%d (中位 %d) 「%s」%s" %
                             (t["class"], t["h"], t["median_h"], t["text"][:36],
                              (" ×%d" % t["count"]) if t.get("count", 1) > 1 else ""))
        if mt["overflow"]:
            lines.append("── 超长URL/单行溢出 · %s ──" % m["label"])
            for t in mt["overflow"][:20]:
                lines.append("   %s 「%s…」%s" % (t["class"], t["text"][:70],
                                                 (" ×%d" % t["count"]) if t.get("count", 1) > 1 else ""))
    return lines, tot_trunc, tot_contrast, tot_out


def _check_negative_control(results):
    nc = next((m for m in results if m["label"] == NEG_LABEL), None)
    if not nc or not nc.get("metrics"):
        return False, "negative control 未跑出结果 (检测器无法自证)"
    mt = nc["metrics"]
    caught_trunc = len(mt["trunc"]) >= 2
    caught_contrast = len(mt["contrast"]) >= 1
    caught_overflow = len(mt["overflow"]) >= 1
    ok = caught_trunc and caught_contrast and caught_overflow
    return ok, ("造缺陷页面被检测: 截断 %d (期望≥2) · 对比度 %d (期望≥1) · 溢出 %d (期望≥1)" %
                (len(mt["trunc"]), len(mt["contrast"]), len(mt["overflow"])))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--dpi", default="192")
    ap.add_argument("--measure", default=None, help="(内部) 子进程模式: 测一页")
    ap.add_argument("--out", default=None)
    ap.add_argument("--pages", default=None, help="逗号分隔的页面标签 (默认全部)")
    a = ap.parse_args()

    dpi = int(a.dpi) if str(a.dpi).strip() else None
    if a.measure:
        _child(a.measure, a.out, dpi)
        return 0

    import tempfile
    labels = [x.strip() for x in a.pages.split(",")] if a.pages else [p[0] for p in PAGE_REGISTRY]
    labels = labels + [NEG_LABEL]
    tmp = tempfile.mkdtemp(prefix="uimet_", dir=os.environ.get("TMPDIR", "/tmp"))
    results = _run_children(labels, dpi, tmp)

    lines, tot_trunc, tot_contrast, tot_out = _fmt_report(results)
    nc_ok, nc_msg = _check_negative_control(results)

    real = [m for m in results if m["label"] != NEG_LABEL]
    real_trunc = sum(len((m.get("metrics") or {}).get("trunc", [])) for m in real)
    real_contrast = sum(len((m.get("metrics") or {}).get("contrast", [])) for m in real)
    built = sum(1 for m in real if m.get("metrics"))
    failed = [m["label"] for m in real if not m.get("metrics")]

    if a.json:
        print(json.dumps({
            "dpi": results[0].get("dpi") if results else None,
            "pages_measured": built, "pages_failed": failed,
            "totals": {"trunc": real_trunc, "contrast": real_contrast,
                       "overflow": sum(len((m.get("metrics") or {}).get("overflow", [])) for m in real)},
            "negative_control": {"ok": nc_ok, "msg": nc_msg},
            "results": [{"label": m["label"], "error": m.get("error"), "rc": m.get("rc"),
                         "metrics": m.get("metrics")} for m in results],
        }, ensure_ascii=False, indent=1))
        return 1 if (real_trunc or real_contrast or not nc_ok) else 0

    for l in lines:
        print(l)
    print("═" * 84)
    print("🧪 自证 (negative control): %s — %s" % ("✅ 检测有效" if nc_ok else "❌ 自证失败", nc_msg))
    print("📄 建窗成功页 %d/%d%s" % (built, len(real), (" · 失败: " + ",".join(failed)) if failed else ""))
    print("真实缺陷: 截断 %d · 对比度不达标 %d → %s" %
          (real_trunc, real_contrast,
           "有缺陷 (退出码 1)" if (real_trunc or real_contrast) else "两类均无 (退出码由自证决定)"))
    if real_trunc == 0 and real_contrast == 0:
        print("   （真实页面零截断/零对比度问题; 检测有效性由自证证明: 造缺陷页被逐项抓到）")
    bad = bool(real_trunc or real_contrast) or not nc_ok
    print("退出码 = %d" % (1 if bad else 0))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
