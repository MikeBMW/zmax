# -*- coding: utf-8 -*-
"""VEH.6 配置中心 · 页面 (主要工程配置 = 任务配置)

老倪 2026-10-09: 「主要工程配置, 例如 上下料的任务配置」⇒ 任务配置是首屏。
老倪 2026-10-14: 「将元任务, 这些信息, 体现在配置中心的 任务配置;
                  将原来的工艺工单任务, 拆解成 任务配置 和 工单配置 两项」
  ⇒ 左树原「工艺·工单」一项拆成两项, 各有一页 (拆的是**粒度**, 不是换列):
     · 📋 任务配置 = **元任务粒度**: 一个功能 (FN-SYSx-N) + 该功能全部配置参数 + 依赖 + 验证方法 + 承载场景
       (列 = 《元任务标准模板》七个字段; 真源 config_meta.json + 画布连线 + tasks.json)
     · 🧾 工单配置 = **工单实例粒度**: 一份工单 (order_no) 的身份 + 配方 + 变体 + 选项 + 目标 + 站点就绪
       (真源 config/orders/BS_*.json)
结构: 左域树 + 右工作区(页签, 首屏=任务配置) + 底部结果面板(点了必出结果)。

本文件只依赖 PyQt5 + json, **不 import studio** (颜色由 studio 传进来), 保证可离屏单测。
每个按钮都调用 tools/config_center.py 的同一份函数 (一份逻辑两处用), 输出抓到面板里;
元任务清单直接调 tools/export_meta_doc.py 的构建函数 (与 Word/PDF 导出同源, 不写第二套)。
"""
from __future__ import annotations

import glob
import io
import json
import os
import re
import sys
import time
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOLS = os.path.join(ROOT, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

from PyQt5.QtCore import Qt, QSettings, QTimer  # noqa: E402
from PyQt5.QtGui import QColor, QFont  # noqa: E402
from PyQt5.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QGridLayout, QHBoxLayout,  # noqa: E402
                             QFrame, QHeaderView, QLabel, QMenu, QPushButton, QRadioButton, QSizePolicy, QSplitter,
                             QTableWidget, QTableWidgetItem, QComboBox, QTabWidget, QTextEdit, QTreeWidget,
                             QTreeWidgetItem, QVBoxLayout, QWidget)

TASKS_J = os.path.join(ROOT, "config", "tasks", "tasks.json")
MCD_J = os.path.join(ROOT, "config", "mcd", "zmax_mcd.json")
MATCH_J = os.path.join(ROOT, "config", "mcd", "match_matrix.json")
ORDERS_D = os.path.join(ROOT, "config", "orders")
BIND_J = os.path.join(ROOT, "config", "ss_task_binding.json")
# 🏷 产品配置真源 (老倪 2026-10-13: 550A 原创版 / 550B 标定版 / 550C 量产版)
PRODUCT_J = os.path.join(ROOT, "config", "platform", "zmax_product.json")
REL_PRODUCT = "config/platform/zmax_product.json"
PRODUCT_IDS = ("550A", "550B", "550C")

# ⭐ 北斗七星阵 (2026-10-15 老倪): 「我的状态空间工程, 实际上是一个阵法, 是有完备的结构的」——
#   七类配置 = 天枢/天璇/天玑/天权/玉衡/开阳/瑶光。星名/次序/定义/关系只写在 ss_seven_stars 一处,
#   左树与每页顶部的阵图条都从这里取 (同源, 不各写一份)。
_GUI_DIR = os.path.dirname(os.path.abspath(__file__))
if _GUI_DIR not in sys.path:
    sys.path.insert(0, _GUI_DIR)
import ss_seven_stars as _ss  # noqa: E402
try:                                     # 🏭 平台描述单一真源 (与主控制台左侧卡面同源, 老倪 2026-10-15)
    from zmax_platform_info import zmax_platform_info as _zmax_platform_info
except Exception:                        # noqa: BLE001
    _zmax_platform_info = None

DEFAULT_THEME = {"C_BG": "#11151c", "C_BG2": "#161b24", "C_CARD": "#1b222c", "C_BORDER": "#2a3340",
                 "C_WHITE": "#e8edf4", "C_GRAY": "#8b98a8", "C_GREEN": "#3fbf7f", "C_RED": "#e05a5a",
                 "C_YELLOW": "#e0b64a", "C_BLUE": "#4a90e0"}


def _j(p, d=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return d


def _run(fn, **kw):
    """跑 config_center 的同名命令, 抓 stdout 成文本 (点了必出结果)。"""
    import argparse
    import config_center as cc
    a = argparse.Namespace(json=False, scene=kw.get("scene"), task=kw.get("task"),
                           cmd=kw.get("cmd", fn), arg=kw.get("arg"))
    buf = io.StringIO()
    target = getattr(cc, f"cmd_{fn}", None)
    with redirect_stdout(buf):
        if target is None:
            print(f"⛔ 未实现的命令: {fn}")
        else:
            try:
                target(a)
            except SystemExit:
                pass
            except Exception as e:  # noqa: BLE001
                print(f"⛔ 执行异常: {type(e).__name__}: {e}")
    return buf.getvalue()


# ── 元任务 (功能 + 该功能全部配置参数) —— 与 tools/export_meta_doc.py **同一份构建函数** ──────────
# 老倪 2026-10-14: 「将元任务, 这些信息, 体现在配置中心的 任务配置;
#                   将原来的工艺工单任务, 拆解成 任务配置 和 工单配置 两项」
#   任务配置 = **元任务粒度**: 一个功能 (FN-SYSx-N) + 该功能全部配置参数 + 依赖 + 验证方法 + 承载场景;
#   工单配置 = **工单实例粒度**: 一份工单 (order_no) 的身份 + 配方 + 变体 + 选项 + 目标 + 站点就绪。
# 两份都是真源派生 (config_meta.json / tasks.json / ss_task_binding.json / 画布 / config/orders/BS_*.json),
# **不在 GUI 里写第二套构建逻辑** —— 直接调导出器那一份 (一份逻辑两处用)。
_MT_SRC = (os.path.join(ROOT, "data/database/zmax/config_meta.json"),
           TASKS_J, BIND_J,
           os.path.join(ROOT, "src/lerobot/engineering/flows/state_space_obs.json"))
_MT_CACHE_SIG = None            # 真源 (mtime,size) 指纹
_MT_CACHE_MT = None             # 元任务清单缓存 (真源变了才重建)


def _meta_tasks():
    """元任务清单 (与 Word/PDF 导出器同源同口径)。真源 mtime/size 变了才重建。"""
    global _MT_CACHE_SIG, _MT_CACHE_MT
    import export_meta_doc as E
    try:
        sig = tuple((os.path.getmtime(p), os.path.getsize(p)) for p in _MT_SRC)
    except OSError:
        sig = None
    if _MT_CACHE_MT is None or (sig is not None and _MT_CACHE_SIG != sig):
        mt, _ctx = E.build_meta_tasks()
        _MT_CACHE_SIG, _MT_CACHE_MT = sig, mt
    return _MT_CACHE_MT


def _meta_task_count():
    """元任务条数 (画树用): 读不到就返回 '?', 绝不编数。"""
    try:
        return len(_meta_tasks())
    except Exception:                                                           # noqa: BLE001
        try:
            with io.open(_MT_SRC[0], encoding="utf-8") as f:
                return len(json.load(f).get("functions", {}))
        except Exception:                                                       # noqa: BLE001
            return "?"


def _orders_list():
    """工单配置真源: config/orders/BS_*.json (Build Sheet) —— 读不到的文件跳过, 不编数。"""
    out = []
    for f in sorted(glob.glob(os.path.join(ORDERS_D, "BS_*.json"))):
        d = _j(f, {}) or {}
        d["_file"] = f
        out.append(d)
    return out


def _short(v, n=3, sep=" / ", w=26):
    """列表/字符串 → 一行的短标签 (界面列只放短标签, 完整值走 tooltip/复制)。"""
    if v is None or v == "":
        return "—"
    items = [str(x) for x in v] if isinstance(v, (list, tuple)) else [str(v)]
    items = [x for x in items if x]
    if not items:
        return "—"
    head = sep.join(items[:n])
    if len(items) > n:
        head += " …(+%d)" % (len(items) - n)
    return head if len(head) <= w else head[:w - 1] + "…"


# ── 三份交付文档 (2026-10-10): 与 config_center.py 同一份真源, 点了必出结果 ──
DOC_SCRIPTS = {
    "bundle":    ("三件套导出 (立项文档 + SOR + 协议)", "docs_bundle.py", []),
    "project":   ("项目立项文档 (Word)", "project_doc_export.py", []),
    "sor":       ("供应商 SOR 需求规格说明书 (Word)", "sor_export.py", []),
    "agreement": ("机器人数据平台合作与模型授权协议 (Word)", "agreement_export.py", []),
    "bom":       ("BOM / 成本 / ROI 算账 (不出文档)", "project_doc_export.py", ["--check"]),
    # 🆕 2026-10-14 老倪: 「这些元任务, 要由配置中心可以在任务配置里可以导出 word 和 pdf 文档」
    #   元任务 = 一个功能(FN-SYSx-N) + 该功能全部配置参数 + 依赖 + 验证 + 归属层
    #   真源(config_meta.json 74 功能 / tasks.json 7 任务 / ss_task_binding.json / 画布 89 节点) →
    #   md → HTML → LibreOffice → docx + pdf; 一致性校验 4/4 内建在脚本里 (--check)
    "metaplan":  ("元任务开发计划 · 项目立项书 (Word + PDF)", "export_meta_doc.py", []),
    # 🆕 2026-10-14 老倪: 「以后每个功能, 需要独立成一个研究成果, 都可以申请专利,
    #   所以你要预留专利申请一键导出的功能」—— 一个功能点 = 一份交底书 (74 份),
    #   内容全部实读真源并标出处 (config_meta + function_notes + 画布 + 代码文件), 出 md+docx+pdf。
    "patent":    ("专利交底书 · 一键导出 (每功能一份 · Word + PDF)", "export_patent_draft.py", ["--all"]),
}
DOC_DIRS = ["outputs/docs_bundle", "outputs/project_docs", "outputs/sor", "outputs/agreements",
            "docs/deliverables"]


# ── 文档配置 (2026-10-10 老倪: 左侧栏增加文档配置, 内置窗口直接看生成的文档, 数据统一保证一致性) ──
DOCS = {
    "sor":       {"name": "供应商外发 SOR", "script": "sor_export.py", "rel": "outputs/sor"},
    "project":   {"name": "项目立项文档", "script": "project_doc_export.py", "rel": "outputs/project_docs"},
    "agreement": {"name": "合作协议", "script": "agreement_export.py", "rel": "outputs/agreements"},
}
# 文档 manifest 里记录过的真源 (键名来自各导出器); 有的用 source_db, 有的用 engineering_db
SRC_DEFS = [
    ("source_db",      "工程库 (单一真源)",       ["data/database/zmax/zmax_engineering.db"]),
    ("engineering_db", "工程库 (单一真源)",       ["data/database/zmax/zmax_engineering.db"]),
    ("bom",            "BOM/成本/ROI 真源",       ["config/platform/zmax_project_bom.json"]),
    ("feature_dbc",    "功能能力清单 feature.dbc", ["data/database/zmax/sources/feature.dbc", "feature.dbc"]),
    ("governance",     "数据治理真源",             ["config/platform/zmax_data_governance.json"]),
    ("perf_spec",      "性能指标真源",             ["config/platform/zmax_perf_spec.json"]),
]
PLATFORM_SRC = ("平台配置真源", "config/platform/zmax_platform.json")   # manifest 未记录 ⇒ 用时间戳兜底


def _sha256(p):
    import hashlib
    try:
        return hashlib.sha256(open(p, "rb").read()).hexdigest()
    except Exception:  # noqa: BLE001
        return ""


def _find_src(paths):
    for p in paths:
        fp = os.path.join(ROOT, p)
        if os.path.exists(fp):
            return p, fp
    return None, None


def _manifest_shas(mp):
    """拍平 manifest 里所有 *_sha256 (三种文档 manifest 结构不同, 递归找最稳; 60 位以上才算 sha)。"""
    j = _j(mp, {}) or {}
    out = {}
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, str) and k.endswith("sha256") and len(v) == 64:
                    out[k[:-7]] = v
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(j)
    return out


def _latest_doc(kind):
    d = _newest_out_dir(DOCS[kind]["rel"])
    if not d:
        return None
    dx = glob.glob(os.path.join(d, "*.docx"))
    if not dx:
        return None
    dx = max(dx, key=os.path.getmtime)
    mp = os.path.join(d, "manifest.json")
    return {"dir": d, "docx": dx, "manifest": mp if os.path.exists(mp) else None, "mtime": os.path.getmtime(dx)}


def _doc_state(kind):
    """文档 × 真源一致性: 逐条比对 manifest 记录的 sha 与当前真源实际 sha (对不上=过期, 不能当交付件)。"""
    st = _latest_doc(kind)
    info = {"kind": kind, "name": DOCS[kind]["name"], "doc": st, "rows": []}
    if not st:
        info.update({"stale": True, "why": "还没生成过"})
        return info
    rec = _manifest_shas(st["manifest"]) if st["manifest"] else {}
    bad = []
    for key, label, cands in SRC_DEFS:
        if key not in rec:
            continue
        rel, fp = _find_src(cands)
        if not fp:
            info["rows"].append((label, rec[key][:12], "路径未找到", "⚠️"))
            bad.append(label + "(路径缺失)")
            continue
        cur = _sha256(fp)
        ok = (cur == rec[key])
        info["rows"].append((label, rec[key][:12], cur[:12], "✅" if ok else "⛔"))
        if not ok:
            bad.append(label)
    rel, fp = _find_src([PLATFORM_SRC[1]])
    if fp and os.path.getmtime(fp) > st["mtime"] + 1:
        info["rows"].append((PLATFORM_SRC[0] + " (时间戳)", "—",
                             time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(fp))), "⚠️"))
        bad.append(PLATFORM_SRC[0])
    info["stale"] = bool(bad)
    info["why"] = ("真源已变: " + ", ".join(bad)) if bad else "与当前真源一致"
    return info


def _doc_mark(kind):
    st = _doc_state(kind)
    return "✅" if (st["doc"] and not st["stale"]) else "⛔"


def _render_docx(path, limit=300000):
    """把生成的 .docx 按正文顺序读回文本 (段落 + 表格), 让内置窗口看到**实际交付内容**。"""
    try:
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except Exception as e:  # noqa: BLE001
        return f"⛔ 读不了 docx (python-docx 缺失?): {e}"
    try:
        d = Document(path)
    except Exception as e:  # noqa: BLE001
        return f"⛔ 打不开 {path}: {e}"
    out = []
    for child in d.element.body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag == "p":
            t = Paragraph(child, d).text.strip()
            if t:
                out.append(t)
        elif tag == "tbl":
            tb = Table(child, d)
            for r in tb.rows:
                out.append("  | " + " | ".join(c.text.strip().replace("\n", " ") for c in r.cells) + " |")
            out.append("")
    txt = "\n".join(out)
    return txt[:limit] + ("\n\n… (面板截断, 完整内容见 docx)" if len(txt) > limit else "")


def _esc(t):
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")


def _render_doc_html(path):
    """把 .docx 渲染成**可读的 HTML**: 表格是真表格 (深底白字表头 + 隔行底色 + 列宽按 docx 实际比例)。

    老倪 2026-10-10: 「表格显示的非常不友好, 用眼睛看非常费劲」⇒ 预览不再用 `| a | b |` 竖线文本。
    Qt 富文本不支持 border-collapse, 用 table 的 border/cellpadding 属性 + 单元格内联色实现。
    """
    C_HEAD, C_ROW1, C_ROW2, C_TXT, C_HEAD_TXT, C_LINE = "#1F3864", "#1b222c", "#161b24", "#e8edf4", "#ffffff", "#2a3340"
    try:
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except Exception as e:  # noqa: BLE001
        return "<p>⛔ 读不了 docx (python-docx 缺失?): %s</p>" % _esc(e)
    try:
        d = Document(path)
    except Exception as e:  # noqa: BLE001
        return "<p>⛔ 打不开 %s: %s</p>" % (_esc(path), _esc(e))

    out = []
    for child in d.element.body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag == "p":
            p = Paragraph(child, d)
            txt = p.text.strip()
            if not txt:
                continue
            sty = p.style.name or ""
            if sty.startswith("Heading 1") or sty.startswith("Title"):
                out.append('<p style="font-size:14pt;font-weight:700;color:#9fc3f0;margin:16px 0 6px 0;">%s</p>' % _esc(txt))
            elif sty.startswith("Heading 2"):
                out.append('<p style="font-size:12pt;font-weight:700;color:#cfe0f5;margin:12px 0 4px 0;">%s</p>' % _esc(txt))
            elif sty.startswith("Heading"):
                out.append('<p style="font-size:11pt;font-weight:700;color:#cfe0f5;margin:10px 0 3px 0;">%s</p>' % _esc(txt))
            else:
                out.append('<p style="font-size:10pt;color:%s;margin:3px 0;">%s</p>' % (C_TXT, _esc(txt)))
        elif tag == "tbl":
            t = Table(child, d)
            ncol = len(t.rows[0].cells) if len(t.rows) else 0
            pcts = [""] * ncol
            try:
                ws = [c.width.cm if c.width else None for c in t.rows[0].cells]
                tot = sum(w for w in ws if w)
                if tot:
                    pcts = [' width="%d%%"' % max(6, int(100.0 * w / tot)) if w else "" for w in ws]
            except Exception:  # noqa: BLE001
                pass
            h = ['<table border="1" cellspacing="0" cellpadding="6" style="border-color:%s;margin:8px 0;">' % C_LINE]
            for ri, row in enumerate(t.rows):
                bg = C_HEAD if ri == 0 else (C_ROW1 if ri % 2 == 1 else C_ROW2)
                fg = C_HEAD_TXT if ri == 0 else C_TXT
                h.append("<tr>")
                for ci, c in enumerate(row.cells):
                    w = pcts[ci] if (ri == 0 and ci < len(pcts)) else ""
                    txt = _esc(c.text.strip())
                    if ri == 0 or ci == 0:
                        txt = "<b>%s</b>" % txt
                    h.append('<td%s style="color:%s;background-color:%s;">%s</td>' % (w, fg, bg, txt))
                h.append("</tr>")
            h.append("</table>")
            out.append("".join(h))
    return "".join(out) or "<p>（文档正文为空）</p>"


def _run_script(script, args=None, timeout=900):
    """真跑 tools/ 下的脚本, stdout+stderr 全抓回面板 (点了必出结果, 失败不静默)。"""
    import subprocess
    cmd = [sys.executable, os.path.join(TOOLS, script)] + list(args or [])
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return f"⛔ 超时 (>{timeout}s): {script} —— 没有结果就不要当成功"
    except Exception as e:  # noqa: BLE001
        return f"⛔ 执行异常: {type(e).__name__}: {e}"
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    if err:
        out += "\n--- stderr ---\n" + err
    if r.returncode != 0:
        out += f"\n⛔ 退出码 {r.returncode} —— 上面就是原因, 不要把这次当成功"
    return out or f"⚠️ 脚本无输出 (退出码 {r.returncode})"


def _newest_out_dir(rel):
    """最新产物目录 (按 mtime, 不能用字母序 —— 时间戳目录名字母序会排错)。"""
    ds = [d for d in glob.glob(os.path.join(ROOT, rel, "*")) if os.path.isdir(d)]
    return max(ds, key=os.path.getmtime) if ds else None


def _doc_inventory():
    """产物清单: 绝对路径 + 大小 + 时间 (老倪要可复制的绝对路径)。"""
    lines = []
    for rel in DOC_DIRS:
        d = _newest_out_dir(rel)
        if not d:
            continue
        import datetime
        mt = datetime.datetime.fromtimestamp(os.path.getmtime(d)).strftime("%m-%d %H:%M")
        lines.append(f"[{mt}] {rel}/  →  {os.path.basename(d)}")
        for f in sorted(os.listdir(d)):
            fp = os.path.join(d, f)
            if os.path.isfile(fp):
                kb = os.path.getsize(fp) / 1024.0
                lines.append(f"    {kb:8.1f} KB  {fp}")
    return "\n".join(lines) if lines else "⚠️ 还没有产物 —— 点上面任一按钮, 跑完这里就会出现绝对路径"


_STATE_ITEMS = ("★ 活跃", "○ 未激活", "— 无配置")
# 活跃属性所在列 (建表列序见 _build_tasks: 0任务ID 1类型 2工程 3=3D场景 4=实时监控 5工艺步骤
#   6适用段 7粒度 8启用节点 9禁用节点 10档位(开) 11模型 12活跃 13状态)
# 🐛 2026-10-13: 10-12 加「3D场景」「实时监控」两列后列序右移, 下拉仍写死在第 8 列(启用节点) ⇒ 下拉跑到
#   「启用节点」列、真正的活跃列只剩文字(而且重算时只更新下拉不更新文字 ⇒ 那格永远停建表那一刻)。
_ACT_COL = 12


def _task_state_cell(tid, act=None):
    """🆕 2026-10-11 老倪: 任务「活跃属性」三态 —— ★ 活跃 / ○ 未激活 / — 无配置。

    口径真源 = tools/ss_task_state.py (不手填): 活跃 = 绑定真源 active_task;
    未激活 = 该任务配置切换过或跑过验证 (激活台账 / 运行报告); 无配置 = 还没开始。
    """
    try:
        _t = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if _t not in sys.path:
            sys.path.insert(0, _t)
        import ss_task_state as _ts
        return _ts.cell(tid, act)
    except Exception as e:                                                      # noqa: BLE001
        return ("★ 活跃" if act == tid else "— 状态未知(%s)" % type(e).__name__)


_SCENES_CACHE = {}
_SCENE_SHORT = {"ar_aoi": "AR", "fw_loading": "FW Loading", "handle": "上下料",
                "bi_aging": "BI 老化", "thermal_chamber": "热海柜体", "ats_test": "ATS",
                "tray_filling": "摆盘", "updown": "上下料(工位)"}


def _scenes_index():
    """场景真源 flows/scenes_5jobs.json → {scene_id: 场景对象} (读不到就空, 不猜)。"""
    p = os.path.join(ROOT, "flows", "scenes_5jobs.json")
    try:
        mt = os.path.getmtime(p)
    except OSError:
        return {}
    if _SCENES_CACHE.get("mt") == mt:
        return _SCENES_CACHE.get("idx") or {}
    try:
        with open(p, encoding="utf-8") as f:
            sc = json.load(f).get("scenes") or []
        idx = {s.get("scene_id"): s for s in sc}
    except Exception:                                                           # noqa: BLE001
        idx = {}
    _SCENES_CACHE.update({"mt": mt, "idx": idx})
    return idx


def _scene_cell(t):
    """3D场景列 —— 老倪 2026-10-12: 「增加3D场景列, 可以看到对应的场景名字」。

    🆕 2026-10-11 老倪: 「任务7 …场景就对应 AR」—— 任务表新增场景列 (短标签 · 场景ID)。
    🥽 2026-10-12 老倪: 「信号分析也用 绿色/蓝色/紫色 代表对应不同的场景」⇒ 配置中心这一列**同色**,
    颜色/映射单一真源 = tools/ss_scene_switch.py(插拔#2e8b57 绿 · 摆盘#1f6feb 蓝 · AR#8957e5 紫), 一致到像素。
    🚀 2026-10-12 二次: 单元格改显示**场景名字**(插拔场景/摆盘场景/AR场景, 真源 config/topics/scene_tags.json)
    + 场景ID —— 与 3D 场景按钮 / 信号分析窗口的叫法一致; 没绑场景的就标未绑定, 不猜。
    """
    sid = t.get("scene_ref") or "—"
    try:
        _d, by_task, _c = _tag_index()
        name = str((by_task.get(str(t.get("task_id"))) or {}).get("scene") or "")
    except Exception:                                                                # noqa: BLE001
        name = ""
    if not name:
        sc = _scenes_index().get(sid) or {}
        name = _SCENE_SHORT.get(sc.get("scene_type"), sc.get("scene_type") or "")
    return ("%s · %s" % (name, sid)) if name else str(sid)


def _scene_color(t):
    """该任务场景对应色 (给单元格上色用); 没映射 = 空串(不上色, 不猜)。"""
    try:
        import ss_scene_switch as _ssw
        m = _ssw.TASK_SCENE.get(str(t.get("task_id")))
        return (m or {}).get("color") or ""
    except Exception:                                                             # noqa: BLE001
        return ""


_SCENE_COLOR_CACHE = {}


def _scene_tip(t):
    sc = _scenes_index().get(t.get("scene_ref")) or {}
    return "场景真源 flows/scenes_5jobs.json\nscene_id: %s\nscene_type: %s\nname: %s\n%s" % (
        t.get("scene_ref"), sc.get("scene_type"), sc.get("name"), sc.get("desc") or "")


def _proj_paths():
    """🚀 2026-10-12 老倪: 「增加工程列, 可看到 zmax 相关的名字和项目启动文件的实际名字和路径」。

    真源: 绑定真源 config/ss_task_binding.json 的 project 段 (工程名/画布/节点) +
          项目启动文件 = 工程文件 .zmaxproj (控制台启动第一步就按它的 debug_state 回填场景/数据源/活跃任务;
          默认路径真源 tools/proj_state.py)。缺就如实标缺, 不编路径。
    """
    b = _j(BIND_J, {}) or {}
    pr = b.get("project") or {}
    out = {"name": pr.get("name") or "状态空间工程 · 主工程", "canvas": pr.get("canvas_file") or "",
           "nodes": pr.get("nodes"), "links": pr.get("links"), "md5": pr.get("canvas_md5"),
           "proj_file": "", "proj_abs": "", "proj_rel": "", "proj_mtime": "",
           "proj_dir": os.path.join(ROOT, "data", "database", "zmax"),
           "db": os.path.join(ROOT, "data", "database", "zmax", "zmax_engineering.db")}
    # 🔴 2026-10-12 老倪(现场纠正): 「配置中心 状态空间的主工程, 路径不是 reports/, 一个都不对」
    #   「/home/ubuntu/zmax/data/database/zmax 主工程路径是这」—— 工程 / 工程库 / 总工程文件都在这里:
    #     data/database/zmax/zmax_space.proj      (总工程文件, 其余 9 个工具同源: tools/gui/project_file.space_path)
    #     data/database/zmax/zmax_engineering.db  (工程库, 单一真源: 库内 projects 表 = 工程名/路径)
    #   ⇒ 只认真源, 不再拿旧的 reports/projects/SS_主工程_任务配置.zmaxproj 顶替(那是 5.21 的老导出件)。
    cand = []
    try:
        import project_file as _pf                                                   # noqa: PLC0415
        cand.append(_pf.find_space(ROOT))            # 总工程 (.proj 优先, 退回旧 .zmaxproj)
        out["proj_dir"] = os.path.dirname(_pf.space_path(ROOT))
    except Exception:                                                                # noqa: BLE001
        pass
    try:
        import sqlite3 as _sq                                                        # noqa: PLC0415
        if os.path.isfile(out["db"]):
            _cn = _sq.connect(out["db"])
            for _r in _cn.execute("select path from projects"):
                if _r and _r[0]:
                    cand.append(str(_r[0]))     # 工程库登记的工程文件路径 (单一真源)
            _cn.close()
    except Exception:                                                                # noqa: BLE001
        pass
    cand.append(os.path.join(ROOT, "data", "database", "zmax", "zmax_space.proj"))
    for c in cand:
        try:
            if c and os.path.isfile(c):
                out["proj_abs"] = os.path.abspath(c)
                out["proj_file"] = os.path.basename(c)
                out["proj_rel"] = os.path.relpath(os.path.abspath(c), ROOT)
                out["proj_mtime"] = time.strftime("%F %T", time.localtime(os.path.getmtime(c)))
                try:                     # 总工程文件自带工程名 ⇒ 显示真名 (不编)
                    _d = _j(c, {}) or {}
                    if _d.get("name"):
                        out["name"] = str(_d["name"])
                except Exception:                                                    # noqa: BLE001
                    pass
                break
        except Exception:                                                            # noqa: BLE001
            continue
    return out


def _proj_cell():
    """工程列单元格: 工程名 + 项目启动文件 (真名, 相对仓库根的路径)。"""
    p = _proj_paths()
    return "%s\n📄 %s" % (p["name"], p["proj_rel"] or p["proj_file"] or "（没有工程文件: 先点「📦 导出工程文件」）")


def _proj_tip():
    p = _proj_paths()
    return "\n".join([
        "工程名: %s" % p["name"],
        "项目启动文件: %s" % (p["proj_file"] or "(缺)"),
        "启动文件绝对路径: %s" % (p["proj_abs"] or "(缺)"),
        "启动文件时间: %s" % (p["proj_mtime"] or "(缺)"),
        "工程目录: %s" % (p.get("proj_dir") or "(缺)"),
        "工程库 (单一真源): %s" % (p.get("db") or "(缺)"),
        "画布真源: %s" % (p["canvas"] or "(缺)"),
        "画布: %s 节点 / %s 连线 · md5 %s" % (p["nodes"], p["links"], str(p["md5"] or "")[:12]),
        "口径: 控制台启动第一步按该工程文件的 debug_state 回填 场景/数据源/活跃任务 (真源 tools/proj_state.py)",
    ])


def _tag_index():
    """信号打标真源 config/topics/scene_tags.json → (全文, {任务: 场景条目}, {场景: 信号条数})。"""
    d = _j(os.path.join(ROOT, "config", "topics", "scene_tags.json"), {}) or {}
    by_task = {str(x.get("task")): x for x in (d.get("scenes") or []) if isinstance(x, dict)}
    cnt = {}
    sig = d.get("signals") or {}
    if isinstance(sig, dict):
        for _v in sig.values():
            cnt[str(_v)] = cnt.get(str(_v), 0) + 1
    return d, by_task, cnt


def _monitor_cell(t):
    """实时监控列: 该任务会加载的信号**颜色** + 条数 (颜色与信号分析窗口 / 3D 场景按钮同一套, 真源 scene_tags.json)。"""
    _d, by_task, cnt = _tag_index()
    x = by_task.get(str(t.get("task_id")))
    if not x:
        return "— 未绑场景\n信号走 未分类 白 #ffffff"
    sc = str(x.get("scene") or "")
    col = str(x.get("color") or "")
    n = cnt.get(sc, 0)
    return "%s  %s ×%d\n+ 基础/未分类 白 #ffffff" % (col or "#ffffff", sc or "?", n)


def _monitor_tip(t):
    _d, by_task, cnt = _tag_index()
    x = by_task.get(str(t.get("task_id"))) or {}
    sc = str(x.get("scene") or "")
    names = [k for k, v in ((_d.get("signals") or {}) if isinstance(_d.get("signals"), dict) else {}).items()
             if str(v) == sc]
    rows = ["颜色真源: config/topics/scene_tags.json (与信号分析窗口 / 3D 场景按钮同一套色)",
            "该任务场景: %s · 颜色 %s · 注册信号 %d 条" % (sc or "(无)", x.get("color") or "-", cnt.get(sc, 0)),
            "未分类/基础信号: 白 #ffffff (三场景共用/没打标的一律白)"]
    if names:
        rows.append("前 %d 条信号: %s" % (min(12, len(names)), " · ".join(names[:12])))
        if len(names) > 12:
            rows.append("… 其余 %d 条见配置单/信号分析窗口" % (len(names) - 12))
    else:
        rows.append("（该场景当前没有注册信号帧 —— 数据源接通后这里会自动有颜色条数）")
    return "\n".join(rows)


def _model_cell(t):
    """🆕 2026-10-11 老倪: 「模型对应 Automated Optical Inspection 自动光学检测 的 L5 自主进化程序」。"""
    mr = t.get("model_ref") or {}
    if not mr:
        return "逐层 L2/L3/L4 + L5 规划"      # 未显式绑模型的任务: 走逐层选型 (binding_hint 口径)
    prog = str(mr.get("program") or "")
    short = prog.split("·")[-1].strip() if "·" in prog else prog
    layer = str(mr.get("layer") or "")
    return short if short.startswith(layer) else "%s · %s" % (layer, short)


def _model_tip(t):
    mr = t.get("model_ref") or {}
    if not mr:
        return "未显式绑模型: 逐层选型 (L2/L3/L4) + L5 规划 (见 binding_hint)"
    return "\n".join(["层: %s" % mr.get("layer"), "程序: %s" % mr.get("program"),
                       "入口: %s" % mr.get("entry"), "章程: %s" % mr.get("charter"),
                       "画布节点: %s" % mr.get("node"), "能力: %s" % mr.get("capability")])


def _pt_entries(t):
    """🥽 任务配置里的示教点位 —— 老倪 2026-10-12: 「更新记录这个 金手指点1 的位置, 要在配置中心的配置里找到这个数据」

    口径: 点位数据**已经写进任务配置**(config/tasks/tasks.json 的 overrides, 由 tools/task_build.py
    从台账 reports/aoi_points/*.json + *.history.jsonl 生成), 配置中心里能直接查到:
        pt.<点名>     = x/y/z + 记录时间 + 真源文件
        pthist.<点名> = 更新次数 + 最近一次 old→new
    """
    ov = (t or {}).get("overrides") or {}
    pts = {k[3:]: v for k, v in ov.items() if k.startswith("pt.")}
    hist = {k[7:]: v for k, v in ov.items() if k.startswith("pthist.")}
    return pts, hist


def _points_tip(t):
    """任务行 tooltip: 示教点位 + 更新记录 (没有点位配置 ⇒ 空串, 不污染别的任务)."""
    pts, hist = _pt_entries(t)
    if not pts:
        return ""
    ov = (t or {}).get("overrides") or {}
    ls = ["🥽 示教点位 (来自任务配置 overrides · 真源 %s)" % (ov.get("pt.dir") or "reports/aoi_points")]
    for k in sorted(pts):
        ls.append("  · %s   %s" % (k, pts[k]))
    for k in sorted(hist):
        ls.append("  ↻ %s   %s" % (k, hist[k]))
    return "\n".join(ls)


def _points_block():
    """底部结果面板追加段 (可选中复制): 把任务配置里的示教点位摊开, 一眼能看到金手指点1 在哪。"""
    try:
        tk = _j(TASKS_J, {}) or {}
    except Exception:                                                           # noqa: BLE001
        return ""
    rows = []
    for t in (tk.get("tasks") or []):
        pts, hist = _pt_entries(t)
        if not pts:
            continue
        rows.append("")
        rows.append("🥽 %s · %s —— 示教点位 (配置里可查 · 真源 %s)"
                    % (t.get("task_id"), t.get("task_type") or "",
                       (t.get("overrides") or {}).get("pt.dir") or "reports/aoi_points"))
        for k in sorted(pts):
            rows.append("   · %-6s %s" % (k, pts[k]))
        for k in sorted(hist):
            rows.append("   ↻ %-6s %s" % (k, hist[k]))
    return ("\n".join(rows)) if rows else ""


def _pt_parse(t):
    """把任务配置里的点位条目拆成结构化行 —— 「工程配置」页直接显示/复制/导出用。

    老倪 2026-10-12: 「我已经在配置中心的 TASK-07 激活的 AOI 任务, 现在要立刻看到 金手指点1 的实际位置数据,
    应该在工程配置里, 用户能立刻找到」⇒ 数据取自任务配置(TASK-07-AOI.overrides 的 pt.* / pthist.*,
    由 tools/task_build.py 从台账 reports/aoi_points 只读生成), 这里只做展示, 不另立真源。
    """
    import re
    ov = (t or {}).get("overrides") or {}
    hist = {k[7:]: v for k, v in ov.items() if k.startswith("pthist.")}
    # 位置 x y z + 姿态 a b c(度) + 记录时间 + 真源; abc 段**可选**(旧配置串没这段也能解析)
    pat = re.compile(r"x=(-?[\d.]+)\s+y=(-?[\d.]+)\s+z=(-?[\d.]+)\s*m"
                     r"(?:\s*·\s*a=(-?[\d.]+)\s+b=(-?[\d.]+)\s+c=(-?[\d.]+)\s*°)?"
                     r"\s*·\s*记录\s*([^·]+?)\s*·\s*(\S+)")
    rows = []
    for k, v in ov.items():
        if not k.startswith("pt."):
            continue
        m = pat.match(str(v).strip())
        if not m:
            continue
        nm = k[3:]
        h = hist.get(nm, "")
        n = (re.match(r"(\d+)\s*次更新", h or "") or [None, "—"])[1] if h else "—"
        rows.append({"name": nm, "x": m.group(1), "y": m.group(2), "z": m.group(3),
                     "a": m.group(4) or "—", "b": m.group(5) or "—", "c": m.group(6) or "—",
                     "t": (m.group(7) or "").strip(), "src": m.group(8), "n": n, "hist": h})
    rows.sort(key=lambda r: _pt_rank(r["name"]))
    return rows


def _pt_rank(name):
    """操作员视角的顺序(老倪: 金手指点1 要一眼看到; 空间点1~7 也要在) ——
    金手指点1 → 金手指点2 → 空间点1..8 → 侧面点0..3 → 准备点 → 安全点N → 其它。"""
    import re
    n = str(name or "")
    if n == "金手指点1":
        return (0, 0, n)
    if n == "金手指点2":
        return (1, 0, n)
    m = re.match(r"^空间点(\d+)$", n)
    if m:
        return (2, int(m.group(1)), n)
    if n.startswith("金手指点"):
        return (3, 0, n)
    m = re.match(r"^侧面点(\d+)$", n)
    if m:
        return (4, int(m.group(1)), n)
    if n.startswith("准备点"):
        return (5, 0, n)
    m = re.match(r"^安全点(\d+)$", n)
    if m:
        return (6, int(m.group(1)), n)
    return (7, 0, n)


def _pt_tsv(rows):
    """复制/导出用的 TSV(粘进 Excel/飞书表格即成型)。"""
    out = ["点位\tX(m)\tY(m)\tZ(m)\tA(°)\tB(°)\tC(°)\t记录时间\t更新次数\t真源文件"]
    for r in rows:
        out.append("%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s" %
                   (r["name"], r["x"], r["y"], r["z"], r.get("a", "—"), r.get("b", "—"),
                    r.get("c", "—"), r["t"], r["n"], r["src"]))
    return "\n".join(out)


def _mk_table(headers, rows, theme, widths=None):
    t = QTableWidget(len(rows), len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setFont(QFont("Consolas", 10))
    t.setStyleSheet(f"QTableWidget{{color:{theme['C_WHITE']};background:{theme['C_CARD']};"
                    f"gridline-color:{theme['C_BORDER']};border:1px solid {theme['C_BORDER']};}}"
                    f"QHeaderView::section{{background:{theme['C_BG2']};color:{theme['C_GRAY']};"
                    f"border:none;padding:6px;}}")
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            it = QTableWidgetItem(str(val))
            s = str(val)
            if s.startswith("⛔") or "缺失" in s:
                it.setForeground(QColor(theme["C_RED"]))
            elif s.startswith("✅"):
                it.setForeground(QColor(theme["C_GREEN"]))
            t.setItem(r, c, it)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    if widths:
        for i, w in enumerate(widths):
            if w:
                t.setColumnWidth(i, w)
    return t


def _btn(text, theme):
    b = QPushButton(text)
    b.setFont(QFont("Arial", 10))
    b.setStyleSheet(f"background:{theme['C_CARD']};color:{theme['C_WHITE']};"
                    f"border:1px solid {theme['C_BORDER']};border-radius:4px;padding:5px 12px;")
    return b


# ══════════════════════════════════════════════════════════════════════════════
# 🏷 产品配置 (老倪 2026-10-13) —— 产品标识 + 空间质数结构化理解能力
#   真源: config/platform/zmax_product.json (active_product / products / capability_signatures /
#         releases / fingerprints / checks / capability_divisibility)
#   纪律: 界面上每个值都是**从真源回读**的 (不在这里自算副本); 选中产品 = **原子写回** active_product;
#         prime_structure 只用来把同一批值独立回算一次做交叉核对 (对不上如实标 ❌, 不掩盖)。
# ══════════════════════════════════════════════════════════════════════════════
def _sha16(path):
    import hashlib
    try:
        return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]
    except Exception as e:                                                      # noqa: BLE001
        return "缺(%s)" % type(e).__name__


def _ps_module():
    """prime_structure 模块 (产品真源解读的唯一入口); 取不到返回 None (页面如实降级显示)。"""
    try:
        _src = os.path.join(ROOT, "src")
        if _src not in sys.path:
            sys.path.insert(0, _src)
        if TOOLS not in sys.path:
            sys.path.insert(0, TOOLS)
        from lerobot.manifold import prime_structure as _PS
        return _PS
    except Exception:                                                           # noqa: BLE001
        return None


def _cut_big(n, head=18, tail=6):
    """大整数显示口径: 前 head + … + 后 tail (N 位) —— 只影响**显示**, 完整值仍在控件/复制里。"""
    s = str(n)
    return s if len(s) <= head + tail + 3 else "%s…%s (%d 位)" % (s[:head], s[-tail:], len(s))


def _vmark(flag):
    """交叉核对标记: 真源写下的值 vs prime_structure 独立回算。None = 没核对上 (不可假成功)。"""
    return " ✅ 真源与回算一致" if flag else (" ❌ 真源与回算不一致" if flag is False else " · 未核对")


def _product_view():
    """产品配置区要显示的**回读值** —— 全部从真源 config/platform/zmax_product.json 读 (不吃内存副本)。"""
    out = {"src": REL_PRODUCT, "error": None, "ps": False}
    d = _j(PRODUCT_J, None)
    if not isinstance(d, dict):
        out["error"] = "真源读不出: %s" % PRODUCT_J
        return out
    prods = d.get("products") or {}
    pid = str(d.get("active_product") or "")
    p = prods.get(pid) or {}
    caps = list(p.get("capabilities") or [])
    rels = d.get("releases") or {}
    rk = max(rels, key=lambda k: int((rels[k] or {}).get("iteration", 0) or 0)) if rels else ""
    relv = rels.get(rk) or {}
    fpr = (d.get("fingerprints") or {}).get(rk) or {}
    out.update({
        "schema": d.get("schema"), "updated": d.get("updated"),
        "active": pid, "product_name": p.get("name"), "version_segment": p.get("version_segment"),
        "prime": p.get("prime"), "capabilities": caps, "n_caps": len(caps),
        "names": {k: ((v or {}).get("name") or k) for k, v in prods.items()},
        "cap_signature": (d.get("capability_signatures") or {}).get(pid),
        "release": rk, "release_product": relv.get("product"), "release_iteration": relv.get("iteration"),
        "release_kind": relv.get("kind"), "fingerprint": fpr.get("fingerprint"),
        "fingerprint_hex": fpr.get("hex"),
        "checks": dict(d.get("checks") or {}),
        "div": dict(d.get("capability_divisibility") or {}),
        "cont": dict(d.get("capability_containment") or {}),
        "sha16": _sha16(PRODUCT_J),
    })
    # 交叉核对: 用 prime_structure 把同一批值独立回算 (页面显示的仍是真源写下的值)
    PS = _ps_module()
    if PS is not None:
        out["ps"] = True
        try:
            prim = set(getattr(PS, "PRIMITIVE_PRIMES", {}) or {})
            stg = set(getattr(PS, "STAGE_PRIMES", {}) or {})
            out["n_prim"] = len([x for x in caps if x in prim])
            out["n_stage"] = len([x for x in caps if x in stg])
            out["cap_signature_verified"] = bool(out["cap_signature"] == PS.cap_signature_of(pid))
            out["fingerprint_verified"] = bool(
                out["fingerprint"] == PS.fingerprint(str(relv.get("product") or pid),
                                                     int(relv.get("iteration") or 1))["fingerprint"])
            sigs = {k: PS.signature(list((prods[k] or {}).get("capabilities") or []), "cap") for k in prods}
            out["div_verified"] = {k: bool(sigs.get(k.split("|")[1], 0) % max(1, sigs.get(k.split("|")[0], 1)) == 0)
                                   for k in (out["div"] or {})} or None
            fps = [v.get("fingerprint") for v in (d.get("fingerprints") or {}).values()]
            out["uniq_verified"] = bool(len(set(fps)) == len(fps))
            out["n_fingerprints"] = len(fps)
        except Exception as e:                                                  # noqa: BLE001
            out["ps_error"] = "%s: %s" % (type(e).__name__, e)
    return out


def _ss_star_tip(label):
    """左树条目的 tooltip: 该条属于哪颗星、主什么、定什么 (从阵法数据取, 不各写一份)。"""
    for _s in _ss.STARS:
        if "%s · %s" % (_s["name"], _s["star"]) in str(label):
            return ("%s、%s配置 · %s（%s）— %s\n%s\n%s  [%s]"
                    % (_s["no_cn"], _s["name"], _s["star"], _s["alias"], _s["role"],
                       _s["q"], _s["rel"], _s["bind"]))
    return ""


def _mt_str(p):
    """文件 mtime → "MM-DD HH:MM" (取不到返回 "取不到"); 显示"真源何时改的"用文件时间, 不信内部字段。"""
    try:
        return time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(p)))
    except OSError:
        return "取不到"


def _star_facts():
    """七颗星各自的**真源摘要一行** (老倪 2026-10-15: 「左侧不用显示那么多 …… 详细信息要在配置页面显示」)。

    左树只留 7 行星名; 每页顶部的阵图条 + 左树 tooltip 用这里的摘要。
    全部**现读真源**(不缓存); 读不出就写"取不到 (原因)", 不退回旧值。
    """
    f = {}
    # 1 · 天枢 产品配置
    try:
        pv = _product_view()
        f["prod"] = "当前 %s · 真源改于 %s · 三档 %s" % (
            pv.get("active") or "取不到", _mt_str(PRODUCT_J),
            " / ".join(str((pv.get("names") or {}).get(p, p)) for p in PRODUCT_IDS))
    except Exception as e:                                                      # noqa: BLE001
        f["prod"] = "取不到 (%s)" % type(e).__name__
    # 2 · 天璇 任务配置
    try:
        _tk = _j(TASKS_J, {}) or {}
        _bd = _j(BIND_J, {}) or {}
        f["task"] = "任务 %d 条 · 元任务 %d · 活跃 %s · 绑定真源改于 %s" % (
            len(_tk.get("tasks", [])), _meta_task_count(), _bd.get("active_task") or "—", _mt_str(BIND_J))
    except Exception as e:                                                      # noqa: BLE001
        f["task"] = "取不到 (%s)" % type(e).__name__
    # 3/4/5 · 天玑/天权/玉衡 (特征库三域)
    try:
        _cs = (_j(MCD_J, {}) or {}).get("CHARACTERISTIC", [])
        for _dom, _k in (("功能配置", "func"), ("模型配置", "model"), ("性能配置", "perf")):
            _l = [c for c in _cs if c.get("domain") == _dom]
            f[_k] = "%s %d/%d 就绪" % (_dom, sum(1 for c in _l if c.get("ready")), len(_l))
        f["func"] += " · 工程域 %d 项 (天玑下的子入口)" % len([c for c in _cs if c.get("domain") == "工程配置"])
    except Exception as e:                                                      # noqa: BLE001
        for _k in ("func", "model", "perf"):
            f.setdefault(_k, "取不到 (%s)" % type(e).__name__)
    # 6 · 开阳 工单配置
    try:
        f["order"] = "工单 %d 个" % len(_orders_list())
    except Exception as e:                                                      # noqa: BLE001
        f["order"] = "取不到 (%s)" % type(e).__name__
    # 7 · 瑶光 文档配置
    try:
        f["doc"] = "文档 %d/3 就绪 (SOR / 立项 / 合作)" % sum(
            1 for m in (_doc_mark(k) for k in ("sor", "project", "agreement")) if m == "✅")
    except Exception as e:                                                      # noqa: BLE001
        f["doc"] = "取不到 (%s)" % type(e).__name__
    f["__all__"] = " · ".join("%s %s" % (_ss.BY_KEY[k]["star"], f.get(k, "").split(" · ")[0])
                              for k in ("prod", "task", "func", "model", "perf", "order", "doc"))
    return f


def _current_version():
    """当前版本号真源: tools/gui/update_checker.py 的 CURRENT_VERSION → VERSION.md 首行 → ""。

    为什么要: 写回 active_product 时要把 `updated` 盖成 "日期 (版本)", 版本必须现取, 不能写死。
    """
    try:
        with io.open(os.path.join(ROOT, "tools", "gui", "update_checker.py"), encoding="utf-8") as f:
            m = re.search(r'CURRENT_VERSION\s*=\s*"([^"]+)"', f.read())
        if m:
            return m.group(1)
    except Exception:                                                           # noqa: BLE001
        pass
    try:
        with io.open(os.path.join(ROOT, "VERSION.md"), encoding="utf-8") as f:
            m = re.search(r"\*\*(v[0-9.]+)\*\*", f.read())
        if m:
            return m.group(1)
    except Exception:                                                           # noqa: BLE001
        pass
    return ""


def _write_active_product(pid):
    """把 active_product **原子写回**真源 (临时文件 + os.replace, 不留半截文件) → 回读确认。

    返回 (ok, 回读值, 错误说明)。除 active_product 一个键外, 真源其它内容逐字节保持 (读改写)。
    """
    if pid not in PRODUCT_IDS:
        return False, None, "产品号 %r 不在 %s" % (pid, list(PRODUCT_IDS))
    try:
        with io.open(PRODUCT_J, encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:                                                      # noqa: BLE001
        return False, None, "真源读不出: %r" % (e,)
    if (d.get("products") or {}) and pid not in (d.get("products") or {}):
        return False, None, "真源 products 里没有 %s" % pid
    if str(d.get("active_product")) == pid:
        return True, pid, "已是当前产品 (无需改写)"
    d["active_product"] = pid
    # 🕒 2026-10-15 实测坑: 真源里 `updated` 停在 "2026-10-13 (5.50.3)" —— 别的写入口只改了
    #    active_product 没盖时间戳 ⇒ 界面/报告显示"真源 2026-10-13"而文件其实是今天 06:30 改的。
    #    这里写回时**同一把锁内**盖上真实时间 + 版本, 让"最后改动"可核。
    try:
        d["updated"] = "%s (%s)" % (time.strftime("%Y-%m-%d"), _current_version())
    except Exception:                                                           # noqa: BLE001
        pass
    tmp = "%s.tmp.%d" % (PRODUCT_J, os.getpid())
    try:
        with io.open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)      # 与真源既有格式一致 (无多余改动, 便于 diff)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, PRODUCT_J)                    # 原子替换: 要么旧文件, 要么新文件, 无半截
    except Exception as e:                                                      # noqa: BLE001
        try:
            if os.path.isfile(tmp):
                os.remove(tmp)
        except Exception:                                                       # noqa: BLE001
            pass
        return False, None, "写盘失败: %r" % (e,)
    back = str((_j(PRODUCT_J, {}) or {}).get("active_product"))     # 回读确认 (不信内存)
    return (back == pid), back, None


class _CopyLabel(QLabel):
    """产品配置区的**可复制**值标签: 双击 / 右键菜单复制; 自动换行 ⇒ 窄窗不截断。

    · 显示文本 (text) 可以是大整数截断形式, 但 **完整值** 存在 .full_value (复制的是完整值);
    · 判据可直接读 .full_value 与真源/prime_structure 回读值比对。
    """

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.full_value = text
        self.key_text = ""
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.setWordWrap(True)                        # 窄窗换行, 字一个不丢
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.setToolTip("双击这一行 = 复制**完整值**; 也可右键 → 复制")

    def set_value(self, shown, full=None):
        """shown = 界面显示 (可截断), full = 完整值 (复制/tooltip/判据用)。"""
        self.full_value = str(full if full is not None else shown)
        self.setText(str(shown))
        self.setToolTip("完整值: %s\n(双击这一行 = 复制完整值)" % self.full_value)

    def _copy(self):
        try:
            QApplication.clipboard().setText(self.full_value)
            return True
        except Exception:                                                       # noqa: BLE001
            return False

    def _copy_pair(self):
        try:
            QApplication.clipboard().setText("%s: %s" % (self.key_text, self.full_value))
        except Exception:                                                       # noqa: BLE001
            pass

    def _menu(self, pos):
        m = QMenu(self)
        m.addAction("📋 复制值").triggered.connect(self._copy)
        m.addAction("📋 复制「字段名: 值」").triggered.connect(self._copy_pair)
        m.exec_(self.mapToGlobal(pos))

    def mouseDoubleClickEvent(self, ev):
        if self._copy():
            ev.accept()
            return
        super().mouseDoubleClickEvent(ev)


class ConfigCenterPage(QWidget):
    """左五域树 + 右工作区 (首屏=任务配置) + 底部结果面板。"""

    def __init__(self, model_page=None, theme=None):
        super().__init__()
        th = dict(DEFAULT_THEME)
        th.update(theme or {})
        self.th = th
        self.setStyleSheet(f"background:{th['C_BG']};")

        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        # ── 顶栏: 返回 + 站点 / 描述 / 授权 ──
        bar = QHBoxLayout()
        d = _j(MCD_J, {}) or {}
        meta = d.get("_meta", {})
        tk = _j(TASKS_J, {}) or {}
        self.back_btn = _btn("← 返回主窗口", th)
        self.back_btn.setToolTip("回到控制台主窗口 (等价于左侧栏「← 返回首页」)")
        self.back_btn.clicked.connect(self._back_home)
        bar.addWidget(self.back_btn)
        info = QLabel(f"站点 SITE-A.ST11 · {meta.get('schema', '缺')} @ {meta.get('generated_at', '—')}"
                      f" · 任务 {len(tk.get('tasks', []))} 条")
        info.setFont(QFont("Consolas", 10))
        # 2026-10-10: QLabel 默认按全文撑宽, 顶栏按钮会被挤出窗口右缘 (真机截图实测被截) ⇒ 允许压缩
        info.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        info.setMinimumWidth(0)
        info.setToolTip(info.text())
        info.setStyleSheet(f"color:{th['C_GRAY']};background:transparent;")
        bar.addWidget(info)
        bar.addStretch()
        b_doc = _btn("📄 文档导出", th)
        b_doc.setToolTip("三份交付文档同源导出 (项目立项文档 / 供应商 SOR / 合作协议) —— 切到「文档交付」页")
        b_doc.clicked.connect(self._goto_docs)
        bar.addWidget(b_doc)
        for txt, fn in (("🔍 全链校验", "check"), ("📋 任务配置", "tasks"), ("⚙️ 工程配置", "list")):
            b = _btn(txt, th)
            b.clicked.connect(lambda _, f=fn: self._run_into(f))
            bar.addWidget(b)
        bar.addSpacing(10)          # 2026-10-10: 右侧留边, 最后一个按钮不贴窗缘 (窄窗实测会顶到边)
        root.addLayout(bar)

        # ── 左树 + 右页签 ──
        # 2026-10-12 老倪: 「配置中心左侧栏无法更改宽度, 字体都挡住了 ⇒ 改适配宽度」
        #   真因(离屏真渲染实测): 树没设最小宽度 ⇒ splitter 在窄窗下把它压到 **71px**(文本需求 ~135px),
        #   而且 setSizes([230,1000]) 只是一次性初值, 右边 QTabWidget 的最小尺寸把左边挤没了。
        #   修法: ①按**内容实测**算需求宽度当初始值 + 最小宽度(挤不没) ②句柄加宽到 8px 好拖
        #   ③关闭"拖到 0 折叠" ④用户拖过的宽度记下来, 下次开页面沿用(只在 ≥ 需求宽度时恢复)。
        sp = QSplitter(Qt.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setFont(QFont("Arial", 10))
        self.tree.setStyleSheet(f"QTreeWidget{{color:{th['C_WHITE']};background:{th['C_CARD']};"
                                f"border:1px solid {th['C_BORDER']};}}")
        self._fill_tree(d, tk)
        # 🏷 左树「产品配置 当前 X」跟真源: 首刷一次 + 每 2s 检查 mtime (只在可见时读, 不空转)
        self._prod_mt_seen = None
        self._sync_tree_product(force=True)
        _ptmr = QTimer(self)
        _ptmr.setInterval(2000)
        _ptmr.timeout.connect(lambda: self.isVisible() and self._sync_tree_product())
        _ptmr.start()
        self._prod_timer = _ptmr
        self.tree.itemDoubleClicked.connect(self._on_tree)
        self.tree.itemClicked.connect(self._on_tree)      # 单击即生效 (双击才响应会让人以为"点了没反应")
        sp.addWidget(self.tree)

        self.tabs = QTabWidget()
        self.tabs.setFont(QFont("Arial", 10))
        self.tabs.setStyleSheet(f"QTabWidget::pane{{border:1px solid {th['C_BORDER']};}}"
                                f"QTabBar::tab{{background:{th['C_BG2']};color:{th['C_GRAY']};padding:6px 14px;}}"
                                f"QTabBar::tab:selected{{background:{th['C_CARD']};color:{th['C_WHITE']};}}")
        self._build_tabs(d, tk, model_page)
        self._wrap_wide_labels(self.tabs)         # 右侧超宽说明行改换行 ⇒ 让分割条真的拖得动(见下)
        # ⭐ 北斗七星阵 (2026-10-15 老倪: 「贯穿配置中心, 在每个配置中心打开的主页面的最上顶部, 写上这样的说明」)
        #   右工作区最顶部一条**阵图条**: 当前页是哪颗星 + 该星一句 + 定义 + 关系 + 定什么 + 七星星图(可点)。
        #   放在页签之上 ⇒ 七个页各自打开时它都在最顶部, 跟着页签自动换内容。
        self.star_banner = _ss.StarBanner(th, on_chip=self._goto_star)
        self.star_host = QWidget()
        _hv = QVBoxLayout(self.star_host)
        _hv.setContentsMargins(0, 0, 0, 0)
        _hv.setSpacing(4)
        _hv.addWidget(self.star_banner.w)
        _hv.addWidget(self.tabs, 1)
        # 一致性: 一页多星(功能·性能·模型)时, 只亮**当前点的那一颗**;
        # 换页签 = 换阵 ⇒ 清掉记忆, 按新页签默认星点亮 (老倪 2026-10-15: 点天玑时天权/玉衡跟着亮 = 错)
        self._star_focus = None
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._sync_star_banner()
        sp.addWidget(self.star_host)
        self._tree_need = self._tree_need_width()
        self.tree.setMinimumWidth(self._tree_need)
        self.tree.setToolTip("左侧栏宽度可按内容自适应, 也可直接拖分隔条调整 (宽度会记住)")
        sp.setSizes([self._tree_need, 1000])
        sp.setChildrenCollapsible(False)          # 不许把左栏拖成 0 宽(会看不见)
        sp.setHandleWidth(8)                      # 原来 4px 太细, 鼠标不好抓
        self.splitter = sp
        sp.splitterMoved.connect(self._on_tree_split_moved)
        root.addWidget(sp, 1)
        QTimer.singleShot(0, self._apply_tree_width)      # 布局完成后按"记过的宽度"或需求宽度落定

        # ── 底部结果面板 (点了必出结果) ──
        self.out = QTextEdit()
        self.out.setReadOnly(True)
        # 2026-10-10: 原来写死 168px ⇒ 总览表第 5 行被半行切掉 (真机截图复核发现)。改成按内容自适应 (120~320px),
        # 超过上限才靠滚动 —— 半行被切不是"可滚动", 是看不清。
        self.out.setFixedHeight(200)
        self.out.setFont(QFont("Consolas", 9))
        self.out.setStyleSheet(f"background:{th['C_BG2']};color:{th['C_WHITE']};"
                               f"border:1px solid {th['C_BORDER']};")
        # 🥽 老倪: 示教点位(金手指点1 等)要在配置里查得到 ⇒ 底部面板末尾摊开(可复制), 任务行 tooltip 同样给
        self.out.setPlainText(_run("overview") + _points_block())
        root.addWidget(self.out)
        self.setLayout(root)
        QTimer.singleShot(0, self._fit_out)      # 首次布局完成后按内容定高

    # ── 左侧栏宽度: 适配内容 + 可拖 + 记住 (2026-10-12 老倪「无法更改宽度, 字体都挡住了」) ──
    _TREE_W_KEY = "config_center/tree_width"

    # ── 右侧超宽说明行 ⇒ 允许换行 (2026-10-12「无法更改宽度」的真凶) ──
    #   实测(真机 192DPI): 页1「工程配置」里一条 **2621px 的单行 QLabel** 把 QTabWidget 的最小宽度顶到
    #   2653px; 加上左树需求 393 ⇒ 整页最小 3046px, 而窗口 3068px 还要减主侧栏 240px ⇒ 分割条被"顶死":
    #   左栏被挤到最小值(**字被截**), 而且**根本拖不动**(没有余量可分)。让超宽说明行换行后, 右侧最小宽度
    #   回落到表格本身, 分割条立刻有余量可拖。换行 ≠ 删字: 全文照旧显示(也照旧可复制)。
    _WRAP_MIN_PX = 520

    def _wrap_wide_labels(self, root=None):
        """把"单行撑得比窗口还宽"的说明 QLabel 改成自动换行, 返回改了几条。幂等。"""
        n = 0
        try:
            for lb in (root or self).findChildren(QLabel):
                if lb.wordWrap() or lb.minimumSizeHint().width() <= self._WRAP_MIN_PX:
                    continue
                lb.setWordWrap(True)
                lb.setMinimumWidth(0)
                n += 1
        except Exception:                                                       # noqa: BLE001
            pass
        return n

    def _bind_sig(self):
        """绑定真源指纹 (mtime_ns:size) —— 用来判断「界面建好之后真源有没有被动过」。"""
        try:
            _s = os.stat(BIND_J)
            return "%d:%d" % (_s.st_mtime_ns, _s.st_size)
        except Exception:                                                        # noqa: BLE001
            return ""

    def showEvent(self, ev):
        """每次显示时再扫一遍(有的页内容是后填的, 构造时还不宽)。"""
        super().showEvent(ev)
        try:
            self._sync_tree_product(force=True)      # 🏷 打开就按真源现算左树「产品配置 当前 X」
        except Exception:                                                         # noqa: BLE001
            pass
        try:
            self._wrap_wide_labels(self.tabs)
        except Exception:                                                       # noqa: BLE001
            pass
        try:
            # 🐛 2026-10-13: 显示时若绑定真源变了(开机自恢复/别的窗口激活了任务)就自对齐 ——
            #   否则界面停在建表那一刻, 真源说活跃、屏幕上写未激活。
            _sig = self._bind_sig()
            if _sig and _sig != getattr(self, "_bind_sig_seen", None):
                self._bind_sig_seen = _sig
                self._reload_task_states()
        except Exception:                                                       # noqa: BLE001
            pass

    def _sync_tree_product(self, force=False):
        """🏷 左树「产品配置  当前 X」**真源现算** —— 别的窗口/客户端改了 active_product 必须自动跟上。

        实测 bug (2026-10-15 老倪): 控制台 06:27 启动时真源是 550A; 06:30 在**别处**把 active_product 写成
        550B 后, 左树仍写「当前 550A」⇒ 界面与真源不一致。根因: 左树文本只在 `_fill_tree()` 建树那一刻取一次,
        之后再没人重读 (右侧「产品配置」页有 _refresh_product_view, 左树没有)。

        口径: ① mtime 变了才重解析(每 2s 检查一次, 代价≈一次 stat) ② 读到什么写什么, 读不出写「取不到」并标 ⛔,
        不退回旧值 (真源纪律) ③ 值变了才刷新右侧页, 防止读—写回环。
        """
        if getattr(self, "_prod_syncing", False):
            return
        try:
            mt = os.path.getmtime(PRODUCT_J)
        except OSError:
            mt = None
        if not force and mt is not None and mt == getattr(self, "_prod_mt_seen", None):
            return
        self._prod_syncing = True
        try:
            self._prod_mt_seen = mt
            pv = _product_view()
            err = pv.get("error")
            act = pv.get("active") or ""
            mark = "⛔" if err else "✅"
            # 「真源改于」用**文件 mtime**(改了就变, 别的写入口也瞒不过); 若真源内部 `updated` 字段与
            # mtime 不是同一天 ⇒ 如实标注它没同步 (实测坑: 06:30 改了 550B 而 updated 还写 2026-10-13)。
            _mt = _mt_day = ""
            _upd = str(pv.get("updated") or "")
            try:
                _mts = os.path.getmtime(PRODUCT_J)
                _mt = time.strftime("%m-%d %H:%M", time.localtime(_mts))
                _mt_day = time.strftime("%Y-%m-%d", time.localtime(_mts))
            except OSError:
                pass
            _stale = bool(_mt_day and _upd[:10] and _mt_day != _upd[:10])
            tail = "  取不到 (真源读不出, 不退回旧值)" if err else (
                ("  · 真源改于 %s%s" % (_mt, " ⚠️内部 updated=%s 未同步" % _upd if _stale else ""))
                if _mt else "")
            # 左树只留星名 (计数/当前值进 tooltip 与配置页) —— 2026-10-15 老倪口径
            txt = "%s %s" % (mark, _ss.star_line("prod"))
            for i in range(self.tree.topLevelItemCount()):
                it = self.tree.topLevelItem(i)
                if it is not None and "产品配置" in it.text(0):
                    it.setText(0, txt)
                    it.setToolTip(0, "%s\n\n真源 %s (%s)\n 每次读文件现算 (mtime 变了才重解析); "
                                     "任何窗口/客户端改了 active_product 都会自动跟上。"
                                     % (_ss_star_tip(_ss.star_line("prod")), REL_PRODUCT, REL_PRODUCT))
                    break
            if force or act != getattr(self, "_prod_shown_active", None):
                self._refresh_product_view(silent=True)      # 右侧页与左树同源
        except Exception as e:                                                    # noqa: BLE001
            try:
                self._log_cc("   ⚠ 产品配置同步失败: %r" % (e,))
            except Exception:                                                     # noqa: BLE001
                pass
        finally:
            self._prod_syncing = False

    def _tree_need_width(self):
        """按**内容实测**算左侧栏需求宽度: 最长条目文本 + 层级缩进 + 图标/边距/滚动条余量。

        为什么要算而不是写死: 条目文本会变(任务 ID/参数 ID/文档名), 写死一个数总会在某天把字截掉;
        而只设初始值不设最小宽度时, 窗口一窄 splitter 就把这一栏压到 70 多像素(实测)。
        """
        fm = self.tree.fontMetrics()
        ind = max(12, self.tree.indentation())
        need = 0
        stack = [(self.tree.topLevelItem(i), 0) for i in range(self.tree.topLevelItemCount())]
        while stack:
            it, d = stack.pop()
            if it is None:
                continue
            need = max(need, d * ind + fm.horizontalAdvance(it.text(0)))
            for i in range(it.childCount()):
                stack.append((it.child(i), d + 1))
        # + 展开箭头/图标(~22) + 边框(4) + 竖直滚动条(18) + 左右余量(12)
        return int(max(150, need + 22 + 4 + 18 + 12))

    def _on_tree_split_moved(self, _pos, _idx):
        """用户拖动分隔条 ⇒ 记住宽度(下次开这个页面沿用)。"""
        try:
            QSettings("ZMAX", "Console").setValue(self._TREE_W_KEY, int(self.tree.width()))
        except Exception:                                                       # noqa: BLE001
            pass

    def _apply_tree_width(self):
        """落定左栏宽度: 用过记过的值(但不得小于内容需求), 没记过就用需求宽度。"""
        try:
            saved = int(QSettings("ZMAX", "Console").value(self._TREE_W_KEY, 0) or 0)
        except Exception:                                                       # noqa: BLE001
            saved = 0
        total = max(self.width(), self.splitter.width())
        want = max(self._tree_need, saved)
        want = min(want, max(self._tree_need, int(total * 0.5)))                # 别把右栏挤没
        self.splitter.setSizes([want, max(1, total - want)])

    # ── 左侧域树 ──
    def _fill_tree(self, d, tk):
        """左树顶层 = **北斗七星阵** 七项, 从上到下 1..7 (老倪 2026-10-15)。

        次序 = 配置体系的传导次序: 天枢定边界 → 天璇定作业 → 天玑定能力 → 天权定算法 → 玉衡定指标
        → 开阳定调度 → 瑶光定记录。每项前面必须有**序号** (老倪原话: 「注意前面要显示一个序号」)。

        与原布局的差别 (如实记, 免得下次又"改回"来):
          · 原来顶层 8 项, 次序是 模型/工程/功能/性能/文档/任务/工单/产品 —— 顺序是按代码里 append 的先后来的,
            没有体系含义; 现在按阵法次序。
          · 原来「工程配置」单列顶层; 它是**特征库第 4 个域**(工程库类特征), 不是八颗星里的一颗 ⇒
            归到「天玑·功能配置(定能力)」下作子入口 (功能没删, 点它照样进工程域视图)。
        """
        chars = d.get("CHARACTERISTIC", [])
        _dom = {}
        for dom in ("模型配置", "工程配置", "功能配置", "性能配置"):
            cs = [c for c in chars if c.get("domain") == dom]
            rd = sum(1 for c in cs if c.get("ready"))
            _dom[dom] = (rd, len(cs), [c["id"] for c in cs if not c.get("ready")])
        # 文档配置 (2026-10-10): 三份外发/立项文档 + 一致性核对
        dm = [_doc_mark(k) for k in ("sor", "project", "agreement")]
        # 计数是"文档份数", 第 4 项是一致性核对视图 ⇒ 提示里写清, 免得看成"子项数对不上"
        self._doc_group_tip = ("文档 3/3 = 三份文档 (供应商外发 SOR / 项目立项文档 / 合作协议) 全部就绪且与当前真源一致;\n"
                               "第 4 项『一致性核对』是核对视图, 不计入份数。")
        self._doc_group_tip_on = True
        # 🏷 产品配置真源 (次序第 1, 现读)
        _pv, _nm, _pact, _perr = {}, {}, "—", False
        try:
            _pv = _product_view()
            _nm = _pv.get("names") or {}
            _pact = _pv.get("active") or "—"
            _perr = bool(_pv.get("error"))
        except Exception:                                                       # noqa: BLE001
            _perr = True
        _bs = _orders_list()
        _tk_all = tk.get("tasks", [])
        doms = []
        # 1 · 天枢 —— 产品配置
        doms.append((f"{_ss.star_line('prod')}  当前 {_pact}", "⛔" if _perr else "✅",
                     [_nm.get(p, p) for p in PRODUCT_IDS]))
        # 2 · 天璇 —— 任务配置 (元任务粒度)
        doms.append((f"{_ss.star_line('task')}  任务 {len(_tk_all)} · 元任务 {_meta_task_count()}",
                     "⛔" if (_tk_all and any(t.get("blocked_by_site") for t in _tk_all)) else "✅",
                     [t["task_id"] for t in _tk_all]))
        # 3 · 天玑 —— 功能配置 (特征库功能域 + 工程域子入口)
        _r3, _n3, _b3 = _dom["功能配置"]
        doms.append((f"{_ss.star_line('func')}  {_r3}/{_n3}", "⛔" if _r3 < _n3 else "✅",
                     list(_b3) + ["工程配置 · 工程库域（特征库第 4 域）"]))
        # 4 · 天权 —— 模型配置 ; 5 · 玉衡 —— 性能配置
        for _k, _d in (("model", "模型配置"), ("perf", "性能配置")):
            _r, _n, _b = _dom[_d]
            doms.append((f"{_ss.star_line(_k)}  {_r}/{_n}", "⛔" if _r < _n else "✅", list(_b)))
        # 6 · 开阳 —— 工单配置 (工单实例粒度)
        doms.append((f"{_ss.star_line('order')}  工单 {len(_bs)}",
                     "⛔" if any((b.get("readiness") or {}).get("site_missing") for b in _bs) else "✅",
                     [((b.get("identity") or {}).get("order_no") or "?") for b in _bs]))
        # 7 · 瑶光 —— 文档配置 (收束全部)
        doms.append((f"{_ss.star_line('doc')}  文档 {sum(1 for m in dm if m == '✅')}/3",
                     "⛔" if "⛔" in dm else "✅",
                     ["供应商外发 SOR", "项目立项文档", "合作协议", "一致性核对"]))
        #   记 (2026-10-14 老倪): 「任务配置」= 元任务粒度 (功能 + 配置参数) / 「工单配置」= 工单实例粒度 (一次执行)。
        #   记 (2026-10-13 老倪): 产品标识 550A 原创版 / 550B 标定版 / 550C 量产版 + 空间质数结构化理解能力。
        # 🧹 2026-10-15 老倪: 「左侧不用显示那么多, 只显示 1..7; 详细信息要在配置页面显示」
        #   ⇒ 顶层 7 行只写「序号 + 名称 · 星名」(+ 一个 ✅/⛔ 就绪符), **不带计数/当前值/子项**;
        #     计数与真源时间进 ①每页顶部阵图条「本页真源: …」 ②左树 hover tooltip (可复制原文)。
        _facts = _star_facts()
        self.tree.clear()
        for label, mark, kids in doms:
            _short = re.sub(r"\s{2,}.*$", "", label)          # 掉掉计数尾巴, 只留「N. 名称 · 星名」
            it = QTreeWidgetItem([f"{mark} {_short}"])
            _tip = _ss_star_tip(label)
            _k = _ss.key_for_label(label)
            _det = ""
            if _facts.get(_k):
                _det += "\n\n本页真源: " + _facts[_k]
            if kids:
                _det += "\n明细 (%d): %s%s" % (len(kids), " · ".join(str(x) for x in kids[:24]),
                                              " …" if len(kids) > 24 else "")
            if "文档配置" in label and getattr(self, "_doc_group_tip_on", False):
                _det += "\n\n" + self._doc_group_tip
            it.setToolTip(0, (_tip + _det).strip())
            self.tree.addTopLevelItem(it)

    # ── 域过滤: 点左树域节点 → 右侧切到对应页并只筛该域的行; 点参数 ID → 直接定位该行 ──
    def _install_state_combos(self):
        """活跃列 (第 12 列 · _ACT_COL) 每行一个下拉: ★ 活跃 / ○ 未激活 / — 无配置。"""
        t = getattr(self, "tasks_table", None)
        ids = getattr(self, "_task_rows", None)
        if t is None or not ids:
            return
        for r in range(min(t.rowCount(), len(ids))):
            if r >= len(ids):
                break
            tid = ids[r]
            cb = getattr(self, "_state_cbs", {}).get(tid) if hasattr(self, "_state_cbs") else None
            if cb is None:
                cb = QComboBox()
                cb.setFont(QFont("Consolas", 10))
                cb.addItems(list(_STATE_ITEMS))
                cb.setStyleSheet(
                    "QComboBox{background:#0d1117;color:#e6edf3;border:1px solid #30363d;"
                    "border-radius:4px;padding:2px 6px;} QComboBox QAbstractItemView{background:#0d1117;"
                    "color:#e6edf3;selection-background-color:#1f6feb;}")
                cb.setToolTip("选择该任务的活跃属性:\n★ 活跃 = 真激活 (写绑定真源 + 台账, 活跃唯一)\n"
                              "○ 未激活 = 配置就绪但不激活\n— 无配置 = 还没开始")
                cb.currentTextChanged.connect(lambda s, _t=tid: self._on_task_state_changed(_t, s))
                t.setCellWidget(r, _ACT_COL, cb)
                if not hasattr(self, "_state_cbs"):
                    self._state_cbs = {}
                self._state_cbs[tid] = cb
            cur = _task_state_cell(tid, getattr(self, "_act_now", None))
            cb.blockSignals(True)
            cb.setCurrentText(cur if cur in _STATE_ITEMS else "— 无配置")
            cb.blockSignals(False)

    def _on_task_state_changed(self, tid, label):
        """用户在下拉里改了活跃属性 → 落真源/台账 → 重算全表 + 计数 + 日志。"""
        try:
            _t = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            if _t not in sys.path:
                sys.path.insert(0, _t)
            import ss_task_state as _ts
            ok, why, extra = _ts.set_state(tid, label, by="配置中心 UI 下拉")
        except Exception as e:                                                  # noqa: BLE001
            ok, why, extra = False, "%s: %s" % (type(e).__name__, e), {}
        try:
            self._log_cc(("✅ " if ok else "⛔ ") + "%s → %s: %s" % (tid, label, why))
            if ok:
                self._act_now = (extra or {}).get("active_task") or None
                self._reload_task_states()
                try:                                                            # 💾 活跃属性一变 → 自动存档到工程文件
                    import importlib.util as _il8
                    _s8 = _il8.spec_from_file_location("proj_state", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "proj_state.py"))
                    _p8 = _il8.module_from_spec(_s8)
                    _s8.loader.exec_module(_p8)
                    _r8 = _p8.save(reason="活跃属性下拉: %s -> %s" % (tid, label))
                    _t8 = _r8.get("state") or {}
                    self._log_cc("💾 调试状态已自动存档 → 工程文件 (任务 %s · 数据源 %s)%s"
                                 % (_t8.get("active_task"), _t8.get("src_state"),
                                    "" if _r8.get("ok") else "  ⚠️ %s" % _r8.get("why")))
                except Exception as _e8:                                        # noqa: BLE001
                    self._log_cc("⚠️ 自动存档失败: %s: %s" % (type(_e8).__name__, _e8))

        except Exception:                                                       # noqa: BLE001
            pass

    # 🗂 2026-10-13 老倪: 「所有这些独立打开的窗口, 要保证与全系统的数据一致性。数据源来源于全局数据空间」
    #   口径: 独立窗口**每次打开/每次轮询都重读磁盘真源**, 不吃构造时的内存副本; 指纹用于跨窗口核验。
    _SRC_FILES = ("config/tasks/tasks.json", "config/ss_task_binding.json", "config/topics/scene_tags.json",
                  "config/platform/zmax_perf_spec.json", "config/mcd/zmax_mcd.json",
                  "config/platform/zmax_product.json",
                  "data/database/zmax/config_meta.json",      # 🆕 2026-10-14 元任务真源 (任务配置页的元任务表)
                  "data/database/zmax/zmax_engineering.db")

    def source_fingerprint(self):
        """真源指纹 (sha256 前 16 位): 独立窗口与主控制台应是同一份 ⇒ 指纹必须相同。"""
        import hashlib
        out = {}
        for rel in self._SRC_FILES:
            fp = os.path.join(ROOT, rel)
            try:
                out[rel] = hashlib.sha256(open(fp, "rb").read()).hexdigest()[:16]
            except Exception as e:                                              # noqa: BLE001
                out[rel] = "缺(%s)" % type(e).__name__
        return out

    def reload_from_source(self):
        """从磁盘真源重读并刷新本页 (独立窗口调用: 主控制台改了配置, 这里自动跟上)。"""
        self._task_cache = None if getattr(self, "_task_cache", None) else None   # 明确不吃旧副本
        try:
            self._reload_task_states()
        except Exception as e:                                                   # noqa: BLE001
            self._log_cc("   ⚠ 重读真源时任务表刷新失败: %r" % (e,))
        try:
            self._refresh_product_view(silent=True)     # 🏷 产品配置区跟着真源走 (回读, 不自算)
        except Exception as e:                                                   # noqa: BLE001
            self._log_cc("   ⚠ 重读真源时产品配置区刷新失败: %r" % (e,))
        fp = self.source_fingerprint()
        self._log_cc("   🔗 已与真源对齐: " + " · ".join("%s=%s" % (k.split("/")[-1], v[:8]) for k, v in fp.items()))
        return fp

    def _reload_task_states(self):
        """重算全表活跃列 + 表头计数 (改一个状态, 全表跟着动: 旧活跃会自动变未激活)。

        🐛 2026-10-13 修: 原来只写下拉格、不写活跃列的文字格 ⇒ 那格永远停在**建表那一刻**
        (实测: 开机自恢复把活跃任务改成 TASK-07-AOI 后, 任务7 那格还写 ○ 未激活 —— 与真源相反,
        任务6 那格反倒写 ★ 活跃)。下拉格和文字格必须同一个函数一起写, 否则界面又出现第二套口径。
        """
        import ss_task_state as _ts
        bind = _j(BIND_J, {}) or {}
        self._act_now = bind.get("active_task")
        ids = getattr(self, "_task_rows", None) or []
        _t = getattr(self, "tasks_table", None)
        _row_of = {}
        if _t is not None:                      # 行号按第 0 列的任务 ID 现查, 不假设行序
            for _r in range(_t.rowCount()):
                _it0 = _t.item(_r, 0)
                if _it0 is not None:
                    _row_of[_it0.text()] = _r
        for tid in ids:
            cur = _ts.cell(tid, self._act_now)
            cur = cur if cur in _STATE_ITEMS else "— 无配置"
            cb = (getattr(self, "_state_cbs", {}) or {}).get(tid)
            if cb is not None:
                cb.blockSignals(True)
                cb.setCurrentText(cur)
                cb.blockSignals(False)
            _r2 = _row_of.get(tid)               # 文字格一起写 (复制出来的文字读的就是它)
            if _t is not None and _r2 is not None and _ACT_COL < _t.columnCount():
                _it = _t.item(_r2, _ACT_COL)
                if _it is not None:
                    _it.setText(cur)
        try:
            self._bind_sig_seen = self._bind_sig()
        except Exception:                                                        # noqa: BLE001
            pass
        st = _ts.build(write=True)
        self._log_cc("   ↻ 全表已重算: 活跃 %d / 未激活 %d / 无配置 %d · 绑定真源 active_task=%s"
                     % (st["counts"]["活跃"], st["counts"]["未激活"], st["counts"]["无配置"], self._act_now))

    def _log_cc(self, msg):
        """配置中心页自己的日志 (打到页内日志框/状态栏; 没有就 stdout)。"""
        for attr in ("_log", "log", "txt_log", "te_log"):
            f = getattr(self, attr, None)
            if callable(f):
                try:
                    return f(msg)
                except Exception:                                               # noqa: BLE001
                    pass
        print(msg, flush=True)

    # ── ⭐ 北斗七星阵: 顶部阵图条 (跟页签走 · 点星跳页) ─────────────────────────────
    def _on_tab_changed(self, *_a):
        """换页签 = 换阵: 清掉"上一页点过哪颗星"的记忆, 按新页签默认星点亮 (一致性)。"""
        self._star_focus = None
        self._sync_star_banner()

    def _sync_star_banner(self, *_a):
        """按当前页签刷阵图条: 七星页显示**当前这一颗**星的说明, 非七星页显示阵法总览 + 如实说明。"""
        try:
            self.star_banner.set_tab(self.tabs.tabText(self.tabs.currentIndex()),
                                     focus_key=getattr(self, "_star_focus", None),
                                     facts=_star_facts())      # 「本页真源: …」现算 (左树不再显示计数)
        except Exception as e:                                                  # noqa: BLE001
            try:
                self._log_cc("   ⚠ 阵图条刷新失败: %r" % (e,))
            except Exception:                                                   # noqa: BLE001
                pass

    def _goto_star(self, key):
        """点阵图条上的星 → 切到该星的页 + 左树选中对应项 (真联动, 不是画着好看)。"""
        s = _ss.BY_KEY.get(key)
        if not s:
            return
        i = self._tab_index_by_title(s["tab"])
        if i >= 0:
            self.tabs.setCurrentIndex(i)      # 可能触发 _on_tab_changed (会清 _star_focus) ⇒ 之后再设
        self._star_focus = s["key"]           # 点哪颗就只亮哪颗 (一页多星时靠它区分)
        if s["key"] in ("func", "perf"):
            _v = self.fpm_views.get(s["name"])
            if _v is not None:
                self._press_fpm_btn(s["name"], view=_v)     # 那一页的域按钮同步按亮
        _kw = "%s · %s" % (s["name"], s["star"])
        for _i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(_i)
            if it is not None and _kw in it.text(0):
                self.tree.setCurrentItem(it)
                break
        self._sync_star_banner()
        try:
            self.out.setPlainText("⭐ %s、%s · %s（%s）· %s  [%s]\n   %s\n   %s" % (
                s["no_cn"], s["name"], s["star"], s["alias"], s["role"], s["bind"], s["q"], s["define"]))
            self._fit_out()
        except Exception:                                                       # noqa: BLE001
            pass

    def _tab_index_by_title(self, kw):
        for i in range(self.tabs.count()):
            if kw in self.tabs.tabText(i):
                return i
        return -1

    def _filter_eng(self, param=None, keep_id=None):
        """工程配置页: param=None 显示全部; 否则只留该参数行 (keep_id 用于精确高亮)。"""
        idx = self._tab_index_by_title("工程配置")
        if idx >= 0:
            self.tabs.setCurrentIndex(idx)
        t = self.tab2_table
        for r in range(t.rowCount()):
            pid = self.eng_rows[r] if r < len(self.eng_rows) else ""
            t.setRowHidden(r, bool(param) and pid != param)
        sel = -1
        if param:
            for r in range(t.rowCount()):
                if self.eng_rows[r] == param:
                    sel = r
                    break
        if sel >= 0:
            t.selectRow(sel)
            t.scrollToItem(t.item(sel, 0))
        n = len(self.eng_rows) if not param else 1
        self.tab2_head.setText(("仅显示: %s" % param) if param else "工程配置 · 全部 %d 项" % n)

    def _press_fpm_btn(self, dom=None, view=None):
        """把特征库页上的域按钮按成**单选**状态 (dom=None = 全不按; view=None = 所有特征库页)。

        与左树点星、阵图条点星同源: 点哪颗星, 那一页的按钮就亮哪一个 —— 否则会出现
        「左侧点了性能配置, 右页还显示天玑按钮亮着」的不一致 (老倪 2026-10-15 实测)。
        """
        views = [view] if view else list(getattr(self, "fpm_views", {}).values())
        for _v in views:
            for _d, _b in _v["btns"].items():
                _b.setChecked(_d == dom)

    def _apply_fpm_filter(self, view, dom, param=None):
        """在一张特征库页上落筛选 (行隐藏 + 表头文案 + 域按钮按下态)。返回显示行数。"""
        t, shown, sel = view["table"], 0, -1
        for r in range(t.rowCount()):
            dv, pid = view["rows"][r] if r < len(view["rows"]) else ("", "")
            ok = (dom is None or dv == dom) and (param is None or pid == param)
            t.setRowHidden(r, not ok)
            if ok:
                shown += 1
                if param and pid == param:
                    sel = r
        if sel >= 0:
            t.selectRow(sel)
            t.scrollToItem(t.item(sel, 0))
        view["head"].setText(("仅显示: %s%s" % (dom or "全部", (" / " + param) if param else ""))
                             + " · %d 项" % shown)
        for _d, _b in view["btns"].items():
            _b.setChecked(_d == dom)
        return shown

    def _filter_fpm(self, dom=None, param=None, view=None):
        """特征库三域: dom=None 显示全部; 否则只留该域; param 再精确定位到行。

        2026-10-15: 页签名改成配置名后, **功能配置 / 性能配置 各有一页** (同一真源、默认域不同):
          dom ∈ {功能配置, 性能配置} → 切到对应那一页筛那一域; 其它域 → 落「功能配置」那张三域总表。
        """
        if view is None:
            view = self.fpm_views.get(dom) or self.fpm_views.get("功能配置")
            if dom in self.fpm_views:
                _i = self._tab_index_by_title(view["title"])
                if _i >= 0:
                    self.tabs.setCurrentIndex(_i)
        return self._apply_fpm_filter(view, dom, param)

    def _show_domain(self, dom, param=None):
        """老倪 2026-10-10: 点『性能配置/功能配置/工程配置/模型配置』右侧必须有内容, 不能只是底部刷字。"""
        if dom == "模型配置":
            if param:
                self._filter_fpm("模型配置", param)
                return True
            i = self._tab_index_by_title("模型配置")
            if i >= 0:
                self.tabs.setCurrentIndex(i)
                return True
            self._filter_fpm("模型配置", param)
        elif dom == "工程配置":
            self._filter_eng(param)
        elif dom in ("功能配置", "性能配置", "模型配置"):
            self._filter_fpm(dom, param)
        else:
            self._run_into("overview")
        return True

    # ── 📋 任务配置 / 🧾 工单配置 两项 (2026-10-14 老倪: 「拆解成 任务配置 和 工单配置 两项」) ──────
    # 元任务表列 = 老倪文档《元任务标准模板》七个字段 (功能名称/输入/输出/配置参数/依赖关系/验证方法/承载场景) + 编号/层/优先级
    _MT_COLS = ("元任务", "功能名称", "层", "输入", "输出", "配置参数", "依赖关系", "验证方法", "承载场景", "优先")

    def _show_tasks(self, txt=""):
        """📋 任务配置页 = **元任务粒度**。点具体任务 ID ⇒ 元任务表只留该任务承载的行。"""
        i = self._tab_index_by_title("任务配置")
        if i >= 0:
            self.tabs.setCurrentIndex(i)
        m = re.search(r"(TASK-[A-Za-z0-9-]+)", txt or "")
        tid = m.group(1) if m else None
        if tid:
            self._filter_meta_tasks(tid)
        else:
            self._run_into("tasks")
        return True

    def _meta_head_text(self, tid=None, shown=None):
        mt = _meta_tasks()
        if tid:
            t = next((x for x in (_j(TASKS_J, {}) or {}).get("tasks", [])
                      if x.get("task_id") == tid), {})
            return ("元任务 (一个功能 + 该功能全部配置参数) · 承载任务 %s (%s) · %d/%d 条"
                    " · 真源 config_meta.json" % (tid, (t.get("name") or "—")[:18],
                                                 len(mt) if shown is None else shown, len(mt)))
        return ("元任务 (一个功能 + 该功能全部配置参数) · 全部 %d 条 "
                "· 真源 config_meta.json + 画布连线 + tasks.json" % len(mt))

    def _filter_meta_tasks(self, tid=None):
        """元任务表按**承载任务**过滤 (tid=None = 全部)。返回可见条数; 表头同步口径。"""
        t = getattr(self, "meta_table", None)
        if t is None:
            return 0
        shown, first = 0, -1
        for r in range(t.rowCount()):
            m = self._meta_rows[r] if r < len(self._meta_rows) else {}
            ok = (tid is None) or (tid in (m.get("tasks") or []))
            t.setRowHidden(r, not ok)
            if ok:
                shown += 1
                if first < 0:
                    first = r
        if first >= 0:
            t.selectRow(first)
        if getattr(self, "meta_head", None) is not None:
            self.meta_head.setText(self._meta_head_text(tid, shown))
        return shown

    def _meta_from_task_row(self, *_a):
        """点任务表某行 ⇒ 元任务表只留该任务的元任务 (两表联动, 一处口径)。"""
        t = getattr(self, "tasks_table", None)
        if t is None:
            return
        r = t.currentRow()
        ids = getattr(self, "_task_rows", [])
        tid = ids[r] if 0 <= r < len(ids) else None
        n = self._filter_meta_tasks(tid)
        self._log_cc("   🧩 元任务筛选: 任务 %s ⇒ %d 条" % (tid or "全部", n))

    def _copy_meta_table(self):
        """复制当前可见的元任务表 (TSV, 可直接粘 Excel) —— 复制不截断。"""
        t = getattr(self, "meta_table", None)
        if t is None:
            return
        lines = ["\t".join(self._MT_COLS)]
        for r in range(t.rowCount()):
            if t.isRowHidden(r):
                continue
            lines.append("\t".join((t.item(r, c).text() if t.item(r, c) else "") for c in range(t.columnCount())))
        try:
            QApplication.clipboard().setText("\n".join(lines))
            self._log_cc("   📋 已复制元任务表 %d 行 (TSV, 可粘 Excel)" % (len(lines) - 1))
        except Exception as e:                                                  # noqa: BLE001
            self._log_cc("   ⛔ 复制失败: %r" % (e,))

    def _meta_card_text(self, m):
        """一个元任务的**完整**标准模板文本 (老倪文档《元任务标准模板》七个字段 + 朴素工程化描述)。"""
        nt = m.get("note") or {}
        return ("元任务 %s · %s\n"
                "  干什么活 : %s\n  卡在哪   : %s\n  当前状态 : %s\n"
                "  功能名称 : %s\n  输入     : %s\n  输出     : %s\n  配置参数 : %s\n"
                "  依赖关系 : %s\n  验证方法 : %s\n  承载场景 : %s\n"
                "  画布节点 : %s · 层 %s · 优先级 %s · 计划 %s"
                % (m.get("mt_id") or "—", m.get("fn_id") or "—",
                   nt.get("work") or "—(真源未登记)",
                   nt.get("pain") or "—(真源未登记)",
                   nt.get("state") or "—(真源未登记)",
                   m.get("name") or "—",
                   " / ".join(m.get("inputs") or []) or "—(真源未登记)",
                   " / ".join(m.get("outputs") or []) or "—(真源未登记)",
                   "%d 条: %s" % (m.get("n_params", 0),
                                 " · ".join(m.get("params_head") or []) or "—"),
                   " / ".join(m.get("deps_up") or []) or "—(画布无上游)",
                   " / ".join(m.get("verification") or []) or "—",
                   " / ".join(m.get("scenes") or []) or "—(未接入任务)",
                   m.get("node_id") or "—", m.get("layer") or "—", m.get("prio") or "—",
                   m.get("month") or "—"))

    def _build_meta_block(self, layout, th):
        """任务表之下再加一张**元任务表**: 每个元任务 = 一个功能 + 该功能全部配置参数。

        列按老倪文档《元任务标准模板》落 (功能名称/输入/输出/配置参数/依赖关系/验证方法/承载场景)。
        ⚠️ 加的是**一张新表**, 上面任务表的 14 列一列没动 (只增列/增表, 不换列)。
        """
        mt = _meta_tasks()
        self._meta_rows = mt
        rows = [[m.get("mt_id") or "—", (m.get("name") or "")[:30], m.get("layer") or "—",
                 _short(m.get("inputs")), _short(m.get("outputs")), "%d 条" % m.get("n_params", 0),
                 _short(m.get("deps_up")), _short(m.get("verification")), _short(m.get("scenes")),
                 m.get("prio") or "—"] for m in mt]
        self.meta_head = QLabel(self._meta_head_text(None, len(mt)))
        self.meta_head.setFont(QFont("Consolas", 10))
        self.meta_head.setStyleSheet("color:%s;background:transparent;" % th["C_GRAY"])
        self.meta_head.setWordWrap(True)
        layout.addWidget(self.meta_head)
        rb = QHBoxLayout()
        for txt, fn in (("🔎 显示全部元任务", lambda: self._filter_meta_tasks(None)),
                        ("📌 只看选中任务", self._meta_from_task_row),
                        ("📋 复制元任务表", self._copy_meta_table),
                        ("📄 专利交底书 (选中功能)", self._patent_selected),
                        ("📄 专利交底书 (全部 74 份)", lambda: self._run_patent())):
            b = _btn(txt, th)
            b.clicked.connect(lambda _=False, f=fn: f())
            rb.addWidget(b)
        rb.addStretch()
        layout.addLayout(rb)
        t = _mk_table(list(self._MT_COLS), rows, th)
        try:
            t.verticalHeader().setDefaultSectionSize(22)
        except Exception:                                                       # noqa: BLE001
            pass
        self.meta_table = t
        for r in range(t.rowCount()):
            full = self._meta_card_text(mt[r] if r < len(mt) else {})
            for c in range(t.columnCount()):
                it = t.item(r, c)
                if it is not None:
                    it.setToolTip(full)          # 列里是短标签, 完整模板在 tooltip (不截断)
        layout.addWidget(t, 1)
        # 点任务表任意一行 ⇒ 元任务表跟着筛 (两表联动)
        try:
            self.tasks_table.itemSelectionChanged.connect(self._meta_from_task_row)
        except Exception:                                                       # noqa: BLE001
            pass

    def _show_orders(self, txt=""):
        """🧾 工单配置页 = **工单实例粒度**。点具体工单号 ⇒ 底部面板摊开这份工单的完整配置面。"""
        i = self._tab_index_by_title("工单配置")
        if i >= 0:
            self.tabs.setCurrentIndex(i)
        m = re.search(r"(BS-[A-Za-z0-9-]+)", txt or "")
        if m:
            self._show_order_detail(m.group(1))
        else:
            self._run_into("orders")
        return True

    def _show_order_detail(self, order_no):
        """一份工单 (Build Sheet) 的配置面 → 底部面板 (全部读真源 config/orders/BS_*.json, 可复制)。"""
        bs = next((b for b in _orders_list()
                   if str((b.get("identity") or {}).get("order_no", "")).startswith(order_no)), None)
        if not bs:
            self.out.setPlainText("⛔ 真源里没有工单 %s (config/orders/BS_*.json)" % order_no)
            self._fit_out()
            return False
        i, rd = bs.get("identity") or {}, bs.get("readiness") or {}
        rec = bs.get("recipe") or []
        self.out.setPlainText("\n".join([
            "🧾 工单配置 · %s" % i.get("order_no", "—"),
            "   场景       : %s (%s)" % (i.get("scene_id", "—"), i.get("name", "—")),
            "   工单目标   : %s" % (bs.get("targets") or {}),
            "   配方       : %d 段 / %d 条参数" % (len(rec), sum(len(x.get("params") or []) for x in rec)),
            "   变体对象   : %s" % _short([o.get("name") for o in (bs.get("variant") or {}).get("objects") or []],
                                        n=6, sep=" · ", w=80),
            "   选项       : %s" % _short((bs.get("options") or {}).get("selected"), n=8, sep=" · ", w=80),
            "   安全(Sys-0): %d 条 · 防错校验链 %d 步" % (len(bs.get("safety") or []), len(bs.get("poka_yoke") or [])),
            "   站点就绪   : %s/9%s" % (rd.get("site_ok", "?"),
                                      ("  ⛔ 缺 " + ", ".join(rd.get("site_missing") or [])) if rd.get("site_missing") else ""),
            "   被站点拦   : %s" % _short(rd.get("blocked_by_site"), n=8, sep=", ", w=80),
            "   真源       : %s" % bs.get("_file", "—"),
        ]))
        self._fit_out()
        return True

    def _order_from_row(self, table=None):
        """工单配置表的某一行 → 底部面板摊开该工单完整配置面 (点行 / 点按钮走同一入口)。"""
        t = table if table is not None else getattr(self, "order_table", None)
        ords = getattr(self, "order_rows", [])
        if t is None or not ords:
            return False
        r = t.currentRow()
        if not (0 <= r < len(ords)):
            self._log_cc("   ⛔ 先在「🧾 工单配置」表里点一行 (共 %d 份工单)" % len(ords))
            return False
        return self._show_order_detail(ords[r])

    def _on_tree(self, item, _col):
        txt = item.text(0)
        # ⭐ 北斗七星阵顶层项 (2026-10-15): 先按**星名**分派到各自配置页。
        #   为什么必须放最前 —— 实测 bug: 序号 "2." 里有一个点, 下面的「参数 ID 分支」把
        #   「⛔ 2. 任务配置 · 天璇」当成参数 ID, 真源里查不到就只打印一行"配置中心里没有参数…",
        #   **页面完全不动** (老倪报: 产品配置能跳, 任务配置不跳; 工单配置同理)。
        if re.search(r"·\s*(天枢|天璇|天玑|天权|玉衡|开阳|瑶光)", txt):
            _k = _ss.key_for_label(txt)
            for _dom in ("模型配置", "工程配置", "功能配置", "性能配置"):
                if _dom in txt:
                    self._show_domain(_dom, None)
                    # 功能·性能·模型 是**一页三星**: 点「5. 性能配置 · 玉衡」必须显示玉衡的按钮/描述,
                    # 不能落到本页默认星(天玑) —— 老倪 2026-10-15 实测报的。
                    self._star_focus = _k or None
                    if _k in ("func", "perf"):
                        # 点哪颗星 → 切到那一页并按下该域按钮 (单一真源: 星 → 页 → 域)
                        self._filter_fpm({"func": "功能配置", "perf": "性能配置"}[_k])
                    self._sync_star_banner()
                    return
            if "工单配置" in txt:
                self._show_orders(txt)
                return
            if "任务配置" in txt:
                self._show_tasks(txt)
                return
            if "文档配置" in txt:
                self._show_doc_config()
                return
            _i = self._tab_index_by_title("产品配置")
            if _i >= 0:
                self.tabs.setCurrentIndex(_i)
            return
        # 🏷 产品配置 (2026-10-13): 点左树 → 切到「产品配置」页 (只切页/只读, 不写真源 —— 写盘只在单选按钮上)
        if "产品配置" in txt or re.search(r"550[ABC]", txt):
            _i = self._tab_index_by_title("产品配置")
            if _i >= 0:
                self.tabs.setCurrentIndex(_i)
            if re.search(r"550[ABC]", txt):
                self.out.setPlainText(
                    "🏷 产品配置: %s\n"
                    "   切产品请在「🏷 产品配置」页的**单选按钮**上点选 (点选即原子写回真源 %s 的 active_product, "
                    "写完回读确认)。\n   本页右侧的值全部是从真源回读的, 双击/右键/📋 可复制完整值。"
                    % (txt.strip(), REL_PRODUCT))
                self._fit_out()
            return
        if "文档" in txt or "SOR" in txt or "立项" in txt or "协议" in txt or "一致性" in txt:
            if "一致性" in txt or "文档配置" in txt:
                self._show_consistency()
            elif "SOR" in txt:
                self._show_doc("sor")
            elif "立项" in txt:
                self._show_doc("project")
            else:
                self._show_doc("agreement")
            return
        # 五个域: 切页 + 筛该域
        for dom in ("模型配置", "工程配置", "功能配置", "性能配置"):
            if dom in txt:
                child = txt.strip()
                self._show_domain(dom, child if (child and "." in child) else None)
                return
        # 参数 ID 子项 (树里显示成 "   model.ckpt_l2"): 按它在哪个域定位到那一行; 找不到就明说, 不静默
        pid = txt.strip()
        if "." in pid:
            if pid in self.eng_rows:
                self._show_domain("工程配置", pid)
                return
            for r in range(self.tab3_table.rowCount()):
                if self.fpm_rows[r][1] == pid:
                    self._show_domain(self.fpm_rows[r][0], pid)
                    return
            self.out.setPlainText("⛔ 配置中心里没有参数 %s (真源里没这一项)" % pid)
            self._fit_out()
            return
        # 🆕 2026-10-14 老倪: 左树拆两项 ⇒ 点「任务配置」进**元任务粒度**页, 点「工单配置」进**工单实例粒度**页
        if "工单配置" in txt or re.search(r"\bBS-", txt):
            self._show_orders(txt.strip())
            return
        if "任务配置" in txt or "工艺" in txt or re.search(r"\bTASK-", txt.upper()):
            self._show_tasks(txt)
            return
        self._run_into("overview")

    # ── 🏷 产品配置区 (老倪 2026-10-13: 产品标识 + 空间质数结构化理解能力) ──────────────
    _PROD_ROWS = ("产品", "版本段", "产品质数", "能力数", "能力质数签名", "当前发布指纹", "质数结构自检")

    def _zmax_platform_card(self, th):
        """🏭 Z-MAX 平台信息块 —— **与主控制台左侧「🏭 Z-MAX 平台」卡面同源**。

        老倪 2026-10-15: 「产品配置页面, 对应主控制台左侧 Z-MAX 平台描述, 你同步信息」。
        两边都读 tools/gui/zmax_platform_info.py (平台/产品描述来自 config/platform/zmax_platform.json,
        计数来自单一工程库) ⇒ 改一处两侧同时变; 读不到就写「取不到」, 不回退旧值。
        内容可复制 (📋 复制 / 双击文本也复制)。
        """
        info = (_zmax_platform_info() if _zmax_platform_info else {}) or {}
        w = QFrame()
        w.setStyleSheet("QFrame{background:%s;border:1px solid %s;border-radius:6px;}"
                        % (th["C_BG2"], th["C_BORDER"]))
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(2)
        lines = info.get("lines") or ["🏭 Z-MAX 平台: 取不到 (zmax_platform_info 不可用)"]
        self.plat_lines = list(lines)
        for _i, _ln in enumerate(lines):
            lb = QLabel(_ln)
            lb.setWordWrap(True)
            lb.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
            lb.setFont(QFont("Consolas", 10 if _i == 0 else 9))
            lb.setStyleSheet("color:%s;background:transparent;border:none;"
                             % (th["C_YELLOW"] if _i == 0 else th["C_GRAY"]))
            lb.setToolTip(_ln)
            lay.addWidget(lb)
        row = QHBoxLayout()
        b_cp = _btn("📋 复制平台信息", th)
        b_cp.setToolTip("把上面三行复制到剪贴板 (给文档/飞书用)")
        b_cp.clicked.connect(lambda: QApplication.clipboard().setText("\n".join(self.plat_lines or [])))
        row.addWidget(b_cp)
        b_rl = _btn("♻️ 重读真源", th)
        b_rl.setToolTip("重读 config/platform/zmax_platform.json + 工程库 (改过真源点一下)")
        b_rl.clicked.connect(self._refresh_platform_card)
        row.addWidget(b_rl)
        row.addStretch()
        lay.addLayout(row)
        return w

    def _refresh_platform_card(self):
        """重读平台真源并刷新块内文本 (真源现算, 不缓存旧值)。"""
        info = (_zmax_platform_info() if _zmax_platform_info else {}) or {}
        lines = info.get("lines") or ["🏭 Z-MAX 平台: 取不到"]
        self.plat_lines = list(lines)
        _labels = [lb for lb in (getattr(self, "plat_card", None).findChildren(QLabel)
                                 if getattr(self, "plat_card", None) else [])]
        for _lb, _ln in zip(_labels, lines):
            _lb.setText(_ln)
            _lb.setToolTip(_ln)
        self.out.setPlainText("🏭 已重读平台真源:\n" + "\n".join("  " + x for x in lines)
                              + "\n\n真源: %s" % (info.get("src") or "取不到"))

    def _product_card(self, th):
        """🏷 产品配置区 —— 三个产品**单选** + 右侧**真源回读**值 (可复制)。

        老倪 2026-10-13: 「流形引擎节点要一眼认出是系统核心 —— 给它加产品标识 (550A/550B/550C)
        与空间质数结构化理解能力的输出」⇒ 配置中心这边给产品配置区:
          · 选中即**原子写回**真源 config/platform/zmax_product.json 的 active_product (临时文件 + os.replace);
          · 右边显示 版本段 / 产品质数 / 能力数 / 能力质数签名(截断) / 当前发布指纹(截断) /
            质数结构自检(唯一性 + 整除关系) —— 每个值都**从真源回读**, 不是界面自算的副本;
          · 显示可复制 (双击 / 右键菜单 / 📋 按钮, 复制的是**完整值**);
          · 窄窗 1280 完整可见: 值标签自动换行 (不截断), 每个字段一行 + 一个 📋 按钮。
        """
        card = QWidget()
        card.setObjectName("productConfigCard")
        card.setStyleSheet(f"background:{th['C_CARD']};border:1px solid {th['C_BORDER']};border-radius:6px;")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(10, 8, 10, 8)
        cv.setSpacing(6)

        ttl = QLabel("🏷 产品配置 —— 产品标识 (550A 原创版 / 550B 标定版 / 550C 量产版)"
                     " + 空间质数结构化理解能力")
        ttl.setFont(QFont("Consolas", 11, QFont.Bold))
        ttl.setWordWrap(True)
        ttl.setStyleSheet(f"color:{th['C_WHITE']};background:transparent;border:none;")
        cv.addWidget(ttl)
        sub = QLabel("选一个产品 = 原子写回真源 %s 的 active_product (临时文件 + 替换, 不留半截文件); "
                     "右侧每个值都是从真源**回读**的 (不是界面自算的副本), 双击/右键/📋 复制完整值。"
                     "产品标识由流形引擎节点输出 (链路缓存 mani_product.product_id)。" % REL_PRODUCT)
        sub.setFont(QFont("Consolas", 9))
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color:{th['C_GRAY']};background:transparent;border:none;")
        cv.addWidget(sub)

        # ① 三产品单选 (选中 → 写回真源 active_product)
        row = QHBoxLayout()
        row.setSpacing(10)
        self._prod_group = QButtonGroup(self)
        self._prod_group.setExclusive(True)
        self._prod_btns = {}
        for pid in PRODUCT_IDS:
            rb = QRadioButton(pid)
            rb.setObjectName("productRadio_%s" % pid)
            rb.setFont(QFont("Consolas", 10))
            rb.setStyleSheet(f"color:{th['C_WHITE']};background:transparent;border:none;spacing:6px;")
            rb.toggled.connect(lambda ck, _p=pid: self._on_product_pick(_p, ck))
            self._prod_group.addButton(rb)
            self._prod_btns[pid] = rb
            row.addWidget(rb)
        row.addStretch()
        b_rl = _btn("🔄 重新读取真源", th)
        b_rl.setToolTip("不写盘, 只把下面的只读值按真源重读一遍")
        b_rl.clicked.connect(lambda: self._refresh_product_view(silent=False))
        row.addWidget(b_rl)
        cv.addLayout(row)

        # ② 只读回读值 (每行一个字段 + 可复制标签 + 📋)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(3)
        self._prod_val = {}
        for i, k in enumerate(self._PROD_ROWS):
            lab = QLabel(k)
            lab.setFont(QFont("Consolas", 9))
            lab.setStyleSheet(f"color:{th['C_GRAY']};background:transparent;border:none;")
            val = _CopyLabel("—")
            val.key_text = k
            val.setFont(QFont("Consolas", 10))
            val.setStyleSheet(f"color:{th['C_WHITE']};background:transparent;border:none;")
            bcp = _btn("📋", th)
            bcp.setFixedWidth(36)
            bcp.setToolTip("复制「%s」的完整值" % k)
            bcp.clicked.connect(lambda _, _k=k: self._copy_field(_k))
            self._prod_val[k] = val
            grid.addWidget(lab, i, 0)
            grid.addWidget(val, i, 1)
            grid.addWidget(bcp, i, 2)
        grid.setColumnStretch(1, 1)
        cv.addLayout(grid)

        self._prod_src = QLabel("真源: —")
        self._prod_src.setFont(QFont("Consolas", 8))
        self._prod_src.setWordWrap(True)
        self._prod_src.setStyleSheet(f"color:{th['C_GRAY']};background:transparent;border:none;")
        cv.addWidget(self._prod_src)
        cv.addStretch()
        self._prod_card = card
        self._prod_shown_active = None
        self._refresh_product_view(silent=True)          # 构造即回读真源 (不显示空壳)
        return card

    def _refresh_product_view(self, silent=True):
        """按真源重读产品配置并刷新界面 (只读, 不改真源)。返回本次读到的那份 (判据/日志可查)。"""
        self._sync_tree_product()      # 🏷 左树那行必须与右侧同源 (本 UI 写回 / 别处改动都覆盖)
        v = _product_view()
        self._prod_last = v
        names = v.get("names") or {}
        for pid in PRODUCT_IDS:
            rb = (getattr(self, "_prod_btns", {}) or {}).get(pid)
            if rb is None:
                continue
            nm = str(names.get(pid) or "").strip()
            rb.setText(nm if nm.startswith(pid) else ("%s %s" % (pid, nm) if nm else pid))
            rb.blockSignals(True)                    # 程序回填不触发写盘 (防写—读回环)
            rb.setChecked(pid == v.get("active"))
            rb.blockSignals(False)
        self._prod_shown_active = v.get("active")
        vals = getattr(self, "_prod_val", {}) or {}
        if not vals:
            return v
        if v.get("error"):
            for k in self._PROD_ROWS:
                vals[k].set_value("⛔ " + str(v["error"]))
            self._prod_src.setText("真源: %s (读不出 ⇒ 如实报缺, 不造数)" % v["src"])
            return v
        vals["产品"].set_value("%s — %s" % (v.get("active"), v.get("product_name")))
        vals["版本段"].set_value(v.get("version_segment"))
        vals["产品质数"].set_value(v.get("prime"))
        n_prim, n_stage = v.get("n_prim"), v.get("n_stage")
        vals["能力数"].set_value("%s 项%s" % (v.get("n_caps"),
                                            (" (元数据基元 %s + 阶段 %s)" % (n_prim, n_stage))
                                            if n_prim is not None else ""))
        vals["能力质数签名"].set_value("%s%s" % (_cut_big(v.get("cap_signature")),
                                               _vmark(v.get("cap_signature_verified"))),
                                      v.get("cap_signature"))
        vals["当前发布指纹"].set_value(
            "%s · %s%s" % (_cut_big(v.get("fingerprint")),
                           "发布 %s (迭代 %s · %s)" % (v.get("release"), v.get("release_iteration"),
                                                       v.get("release_kind")),
                           _vmark(v.get("fingerprint_verified"))),
            v.get("fingerprint"))
        ck = v.get("checks") or {}
        dv = v.get("div") or {}
        dvv = v.get("div_verified") or {}

        def _cmp(x):
            return "一致" if x else ("不符" if x is False else "未核对")

        uniq = "唯一性 %s (%s/%s 指纹互不相等 · 回算%s)" % (
            "✅" if ck.get("all_fingerprints_distinct") else "❌",
            ck.get("n_fingerprints"), v.get("n_fingerprints"), _cmp(v.get("uniq_verified")))
        div_txt = " · ".join("%s %s%s" % (k, "✅" if dv.get(k) else "❌",
                                          "" if (not dvv or dvv.get(k) == dv.get(k)) else "(回算不符)")
                             for k in sorted(dv)) or "—"
        vals["质数结构自检"].set_value("%s · 整除 %s" % (uniq, div_txt))
        self._prod_src.setText("真源: %s · schema %s · 更新 %s · 文件 sha256[:16] %s · prime_structure 交叉回算 %s"
                               % (v["src"], v.get("schema"), v.get("updated"), v.get("sha16"),
                                  "✅ 可用" if v.get("ps") else "⚠ 不可用 (只显真源回读值)"))
        if not silent:
            self._log_cc("🏷 产品配置已按真源重读: active=%s · 产品质数 %s · 能力 %s 项 · 能力质数签名 %s · 指纹 %s"
                         % (v.get("active"), v.get("prime"), v.get("n_caps"),
                            _cut_big(v.get("cap_signature")), _cut_big(v.get("fingerprint"))))
        return v

    def _on_product_pick(self, pid, checked):
        """勾选产品 → **原子写回**真源 active_product → 回读确认 → 刷新只读值 (失败如实报)。"""
        if not checked or pid == getattr(self, "_prod_shown_active", None):
            return
        ok, back, err = _write_active_product(pid)
        if ok:
            self._log_cc("🏷 产品已切到 %s — 真源 %s 回读 active_product=%s" % (pid, REL_PRODUCT, back))
        else:
            self._log_cc("⛔ 产品切换失败 (真源未改): %s" % (err or "未知原因"))
        self._refresh_product_view(silent=True)
        try:
            self.out.append("%s 产品配置: 选中 %s → %s (真源回读 active_product=%s)"
                            % ("✅" if ok else "⛔", pid, "已写回真源" if ok else ("未写: %s" % (err or "")), back))
        except Exception:                                                       # noqa: BLE001
            pass

    def _copy_field(self, key):
        """📋 按钮: 复制某字段的**完整值** (界面显示可能截断, 复制的不截断)。"""
        lb = (getattr(self, "_prod_val", {}) or {}).get(key)
        if lb is None:
            return False
        try:
            QApplication.clipboard().setText(lb.full_value)
            self._log_cc("📋 已复制「%s」= %s" % (key, lb.full_value))
            return True
        except Exception as e:                                                  # noqa: BLE001
            self._log_cc("⛔ 复制失败: %r" % (e,))
            return False

    # ── 右侧页签 ──
    def _ar_pts_card(self, th, tk):
        """🥽 AR 场景 · 工程配置数据 (专用一块, 放「工程配置」页顶部)。

        老倪 2026-10-12: 「我已经在配置中心的 TASK-07 激活的 AOI 任务, 现在要看到 金手指点1 的实际位置数据,
        应该在工程配置里, 用户能立刻找到 —— 搞一个专门对应 AR场景的 工程配置数据」
        ⇒ 点位表(金手指点1 置顶) + 复制/导出按钮; 数据来自任务配置, 真源是 reports/aoi_points 台账。
        """
        t = next((x for x in (tk.get("tasks") or []) if str(x.get("task_id")) == "TASK-07-AOI"), {})
        rows = _pt_parse(t)
        card = QWidget()
        card.setStyleSheet(f"background:{th['C_CARD']};border:1px solid {th['C_BORDER']};border-radius:6px;")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(8, 6, 8, 6)
        cv.setSpacing(4)
        head = QHBoxLayout()
        ttl = QLabel("🥽 AR 场景 · 工程配置数据 —— 示教点位(实际位置)")
        ttl.setFont(QFont("Consolas", 11, QFont.Bold))
        ttl.setStyleSheet(f"color:{th['C_WHITE']};background:transparent;border:none;")
        head.addWidget(ttl)
        head.addStretch()
        _sdir = (t.get("overrides") or {}).get("pt.space_dir") or "data/skills/l2_atomic/space_points.json"
        sub = QLabel("任务 TASK-07-AOI(光学质量检测) · 场景 SCN-07-AOI(AR) · 单位 m(基座系) · "
                     "真源 reports/aoi_points(示教点) + %s(空间点1~8) —— 由 tools/task_build.py 只读生成" % _sdir)
        sub.setFont(QFont("Consolas", 9))
        sub.setStyleSheet(f"color:{th['C_GRAY']};background:transparent;border:none;")
        cv.addWidget(ttl)
        cv.addWidget(sub)
        # 🔴 老倪 2026-10-12: 「配置中心的点, 除了位置, 还得有 a b c, 6 个数字都要记录」
        tb = _mk_table(["点位", "X (m)", "Y (m)", "Z (m)", "A (°)", "B (°)", "C (°)", "记录时间", "更新", "真源文件"],
                       [[r["name"], r["x"], r["y"], r["z"], r["a"], r["b"], r["c"],
                         r["t"], r["n"], r["src"]] for r in rows], th)
        tb.setMinimumHeight(28 * (len(rows) + 2) + 6)
        tb.setMaximumHeight(30 * (len(rows) + 2) + 10)
        try:                                        # 金手指点1 那一行高亮(老倪要"立刻找到")
            if rows:
                from PyQt5.QtGui import QColor as _QC
                for c in range(tb.columnCount()):
                    it = tb.item(0, c)
                    if it is not None:
                        it.setForeground(_QC(th["C_GREEN"]))
                        it.setToolTip("★ 金手指点1 —— 位姿 x=%s y=%s z=%s m · a=%s° b=%s° c=%s°"
                                      " · 记录 %s\n   真源 %s\n   %s"
                                      % (rows[0]["x"], rows[0]["y"], rows[0]["z"],
                                         rows[0].get("a", "—"), rows[0].get("b", "—"), rows[0].get("c", "—"),
                                         rows[0]["t"], rows[0]["src"], rows[0].get("hist") or ""))
        except Exception:                                                       # noqa: BLE001
            pass
        cv.addWidget(tb)
        _sync = QLabel("真源同步: —")
        _sync.setFont(QFont("Consolas", 9))
        _sync.setStyleSheet(f"color:{th['C_GRAY']};background:transparent;border:none;")
        cv.addWidget(_sync)
        rb = QHBoxLayout()
        b_cp = _btn("📋 复制这张表", th)
        b_cp.setToolTip("复制成 TSV(可直接粘进 Excel / 飞书表格)")
        b_ex = _btn("📄 存 CSV", th)
        b_rl = _btn("🔄 重新读取", th)
        rb.addWidget(b_cp); rb.addWidget(b_ex); rb.addWidget(b_rl); rb.addStretch()
        cv.addLayout(rb)

        def _cp():
            try:
                from PyQt5.QtWidgets import QApplication as _QA
                _QA.clipboard().setText(_pt_tsv(rows))
                self.out.setPlainText("✅ 已复制 AR 场景示教点位表 (%d 行, TSV) —— 直接粘进表格即可\n\n%s"
                                      % (len(rows), _pt_tsv(rows)))
            except Exception as e:                                              # noqa: BLE001
                self.out.setPlainText("⛔ 复制失败: %s" % repr(e)[:120])

        def _ex():
            try:
                d = os.path.join(ROOT, "reports", "exports")
                os.makedirs(d, exist_ok=True)
                fp = os.path.join(d, "AR场景_示教点位_%s.csv" % time.strftime("%Y%m%d_%H%M%S"))
                with open(fp, "w", encoding="utf-8-sig") as f:
                    f.write(_pt_tsv(rows).replace("\t", ","))
                self.out.setPlainText("✅ 已导出: %s   (%d 行)\n\n%s" % (fp, len(rows), _pt_tsv(rows)))
            except Exception as e:                                              # noqa: BLE001
                self.out.setPlainText("⛔ 导出失败: %s" % repr(e)[:120])

        def _fill(r2, silent=False):
            # 🔴 2026-10-12: 列数要和表头一致(点位+X+Y+Z+A+B+C+时间+更新+真源)。
            #   原来这里只写 7 列(旧的"只要位置"口径) ⇒ 刷新一次就把 A/B/C 三列冲成时间/更新/真源,
            #   表格看起来"6 个数字缺 3 个"。真跑判据当场抓到(离屏真建卡回读单元格)。
            tb.setRowCount(len(r2))
            for i, r in enumerate(r2):
                for c, v in enumerate((r["name"], r["x"], r["y"], r["z"],
                                       r.get("a", "—"), r.get("b", "—"), r.get("c", "—"),
                                       r["t"], r["n"], r["src"])):
                    tb.setItem(i, c, QTableWidgetItem(str(v)))
            try:
                from PyQt5.QtGui import QColor as _QC2
                for c in range(tb.columnCount()):
                    it = tb.item(0, c)
                    if it is not None and r2:
                        it.setForeground(_QC2(th["C_GREEN"]))
            except Exception:                                                   # noqa: BLE001
                pass
            _h = os.path.getmtime(TASKS_J) if os.path.exists(TASKS_J) else 0
            _sync.setText("真源同步: %s · %d 个点位(点位一改就自动跟上, 无需点按钮)"
                          % (time.strftime("%H:%M:%S", time.localtime(_h)) if _h else "—", len(r2)))
            if not silent:
                self.out.setPlainText("🔄 已重新读取任务配置(%s) —— %d 个点位\n%s"
                                      % (time.strftime("%H:%M:%S"), len(r2), _pt_tsv(r2)))

        def _rl():
            tk2 = _j(TASKS_J, {}) or {}
            t2 = next((x for x in (tk2.get("tasks") or []) if str(x.get("task_id")) == "TASK-07-AOI"), {})
            _fill(_pt_parse(t2))

        # 🔁 2026-10-12 老倪: 「标注模式更新了金手指点1, 配置中心还是没更新; 要实时更新, 全局数据一致」
        #   ⇒ 表自己盯真源 mtime(任务配置由 task_build 从 AOI 台账重建), 变了就**静默刷新**:
        #   不用重启控制台、不用点按钮, 点位的记录/清除立刻反映到这里。
        _watch = {"m": (os.path.getmtime(TASKS_J) if os.path.exists(TASKS_J) else 0)}

        def _tick_sync():
            try:
                _m = os.path.getmtime(TASKS_J) if os.path.exists(TASKS_J) else 0
            except OSError:
                return
            if _m and _m != _watch["m"]:
                _watch["m"] = _m
                _t2 = next((x for x in ((_j(TASKS_J, {}) or {}).get("tasks") or [])
                            if str(x.get("task_id")) == "TASK-07-AOI"), {})
                _fill(_pt_parse(_t2), silent=True)

        _tmr = QTimer(card)
        _tmr.setInterval(2000)
        _tmr.timeout.connect(_tick_sync)
        _tmr.start()
        _fill(rows, silent=True)

        b_cp.clicked.connect(_cp)
        b_ex.clicked.connect(_ex)
        b_rl.clicked.connect(_rl)
        return card

    def _build_tabs(self, d, tk, model_page):
        th = self.th
        bind = _j(BIND_J, {}) or {}
        bmap = {t["task_id"]: t for t in bind.get("tasks", [])}
        act = bind.get("active_task")
        proj = bind.get("project", {})
        # 1) 任务配置 (首屏) —— 含"状态空间工程"配置清单列
        self.tasks_table = _mk_table(
            # 🆕 2026-10-11 老倪: 新增「场景」「模型」两列 (任务7 = AOI → 场景 AR · 模型 L5 自主进化程序)
            # 🚀 2026-10-12 老倪: 「增加工程列(工程名+项目启动文件真名真路径) · 增实时监控列(看加载信号的颜色)
            #   · 增3D场景列(看场景名字)」—— 原「场景」列即 3D 场景名, 改名「3D场景」不重复占列
            ["任务ID", "类型", "工程", "3D场景", "实时监控", "工艺步骤", "适用段", "粒度", "启用节点", "禁用节点",
             "档位(开)", "模型", "活跃", "状态"],
            [[t["task_id"], t["recipe_type"],
              _proj_cell(),                               # 🚀 工程列 (工程名 + 项目启动文件真名 + 路径)
              _scene_cell(t),                             # 3D场景列 (场景名字, 按场景色上色)
              _monitor_cell(t),                           # 🚀 实时监控列 (该任务加载信号的颜色 + 条数)
              " → ".join(s["name"] for s in t.get("steps", [])),
              f"{len(t['applies_segments'])}/8",
              len(t.get("variants", [])),
              (len(bmap[t["task_id"]]["enabled_nodes"]) if t["task_id"] in bmap else "—"),
              (len(bmap[t["task_id"]]["disabled_nodes"]) if t["task_id"] in bmap else "—"),
              (sum(1 for v in bmap[t["task_id"]]["run_cfg"].values() if v["checked"])
               if t["task_id"] in bmap else "—"),
              _model_cell(t),                            # 🆕 模型列 (未显式绑 = 逐层 L2/L3/L4 + L5 规划)
              _task_state_cell(t["task_id"], act),        # 🆕 活跃属性三态: ★ 活跃 / ○ 未激活 / — 无配置
              ("⛔ 缺站点几何" + str(len(t["blocked_by_site"]))) if t.get("blocked_by_site") else "✅"]
             for t in tk.get("tasks", [])], th)
        # 🚀 2026-10-12: 两行单元格 (工程/实时监控) 要够高 + 列宽按内容 (否则路径/颜色被截)
        try:
            self.tasks_table.verticalHeader().setDefaultSectionSize(46)
            _hh = self.tasks_table.horizontalHeader()
            _hh.setSectionResizeMode(QHeaderView.ResizeToContents)
            _hh.setSectionResizeMode(5, QHeaderView.Stretch)      # 工艺步骤 吃剩余宽度
            self.tasks_table.resizeRowsToContents()
        except Exception:                                                          # noqa: BLE001
            pass
        # 🆕 2026-10-11 老倪: 「配置中心的活跃属性列, 增加新功能, 用户可以自主调整 活跃/未激活 等状态, 用下拉菜单」
        #   设计: 活跃列每行一个下拉 (★ 活跃 / ○ 未激活 / — 无配置) —— 选「★ 活跃」= 真激活该任务 (走 ss_task_bind --activate,
        #   写绑定真源 + 台账, 回读校验); 选「未激活/无配置」= 记手选台账 (当前活跃任务不许直接取消; 有运行证据的不许降级)。
        #   改完立刻重算全表 + 表头计数, 动作与结果都写进下方日志 (失败照实说, 不假成功)。
        # 🆕 场景/模型列的完整说明放 tooltip (单元格只放短标签, 完整口径不截断)
        try:
            for _i, _t in enumerate(tk.get("tasks", [])):
                # 列序: 0任务ID 1类型 2工程 3=3D场景 4=实时监控 5工艺步骤 … 11模型 12活跃 13状态
                for _c, _tip in ((2, _proj_tip()), (3, _scene_tip(_t)), (4, _monitor_tip(_t)),
                                 (11, _model_tip(_t)), (0, _points_tip(_t))):
                    _it = self.tasks_table.item(_i, _c)
                    if _it is not None:
                        _it.setToolTip(_tip)
                # 🥽 2026-10-12: 3D场景列 + 实时监控列 都按场景色上色 —— 与 3D 场景按钮、信号分析同色同源
                _col = _scene_color(_t)
                for _c2 in (3, 4):
                    _it2 = self.tasks_table.item(_i, _c2)
                    if _it2 is not None and _col:
                        from PyQt5.QtGui import QColor as _QC, QBrush as _QB
                        _it2.setForeground(_QB(_QC(_col)))
                        _it2.setToolTip((_it2.toolTip() or "")
                                        + "\n场景色 %s (与 3D 场景按钮 / 信号分析 同一套色)" % _col)
        except Exception:                                                       # noqa: BLE001
            pass
        self._task_rows = [t["task_id"] for t in tk.get("tasks", [])]
        self._act_now = act
        self._install_state_combos()
        self._bind_sig_seen = self._bind_sig()
        w = QWidget(); l = QVBoxLayout(w); l.setContentsMargins(6, 6, 6, 6)
        _st_n = {k: sum(1 for t in tk.get("tasks", []) if _task_state_cell(t["task_id"], act) == k)
                 for k in ("★ 活跃", "○ 未激活", "— 无配置")}
        head = QLabel(f"状态空间工程(主工程): {proj.get('nodes', '?')} 节点 / {proj.get('links', '?')} 连线"
                      f"  ·  md5 {str(proj.get('canvas_md5', ''))[:12]}  ·  承载 {len(bind.get('tasks', []))} 个任务"
                      f"  ·  活跃 {act or '—'}"
                      # 🆕 2026-10-11 老倪: 活跃属性三态一眼看全 (★ 活跃 / ○ 未激活 / — 无配置)
                      f"  ·  状态 活跃 {_st_n['★ 活跃']} / 未激活 {_st_n['○ 未激活']} / 无配置 {_st_n['— 无配置']}")
        head.setFont(QFont("Consolas", 10))
        head.setStyleSheet(f"color:{th['C_GRAY']};background:transparent;")
        l.addWidget(head)
        row = QHBoxLayout()
        for txt, fn, kw in (("🧩 刷新绑定", "bind", {}),
                            ("📋 配置清单(选中)", "bind", {"use_sel": True}),
                            ("📋 配置单(全参数导出)", "sheet", {"use_sel": True}),
                            ("✅ 激活选中任务", "activate", {"use_sel": True}),
                            ("📦 导出工程文件", "project", {}),
                            ("📥 写入状态空间节点", "node", {"arg": "write"}),
                            ("🏷 看节点配置", "node", {}),
                            ("🔍 全链校验", "check", {}),
                            ("📄 配方", "recipe", {}),
                            ("📋 导出 JSON", "tasks", {})):
            b = _btn(txt, th)
            b.clicked.connect(lambda _, f=fn, k=kw: self._run_selected(f, **k))
            row.addWidget(b)
        # 🆕 2026-10-14 老倪: 「这些元任务, 要由配置中心可以在任务配置里可以导出 word 和 pdf 文档」
        #   任务配置首屏直接出「元任务开发计划 · 项目立项书」(md + docx + pdf),
        #   元任务 = 一个功能 + 该功能全部配置参数; 与命令行 tools/export_meta_doc.py 同一执行体。
        _b_mt = _btn("📄 元任务计划 (Word/PDF)", th)
        _b_mt.setToolTip("导出「元任务开发计划 · 项目立项书」\n"
                         "元任务 = 每个功能 + 该功能全部配置参数 (打散到可独立开发的粒度)\n"
                         "产物: docs/deliverables/元任务开发计划_2026-10_2027-12.md / .docx / .pdf\n"
                         "数据源: config_meta.json(74 功能) + tasks.json(7 任务) + "
                         "ss_task_binding.json + 画布(89 节点) —— 出文档前先跑一致性校验")
        _b_mt.setStyleSheet(_b_mt.styleSheet() + ";font-weight:bold;")
        _b_mt.clicked.connect(lambda: self._run_doc("metaplan"))
        row.addWidget(_b_mt)
        row.addStretch()
        l.addLayout(row)
        l.addWidget(self.tasks_table, 1)
        # 🚀 2026-10-12 老倪: 「右下角增加启动按钮, 用户可以同时启动工程, 信号, 和场景」
        #   右下角 = 表格之下右对齐; 执行体 = studio._open_all_cmd (与命令行 zmax_open.py step2 同一段代码)
        row2 = QHBoxLayout()
        _hint = QLabel("按选中任务确定配置 (没选 = 活跃任务) → 同源启动:")
        _hint.setStyleSheet("color:%s;background:transparent;" % th["C_GRAY"])
        _hint.setFont(QFont("Consolas", 9))
        row2.addStretch()
        row2.addWidget(_hint)
        _b_all = _btn("🚀 启动工程 · 信号 · 场景", th)
        _b_all.setToolTip("同时启动三样 (同一份真源, 顺序: 工程 → 场景 → 信号):\n"
                          "· 工程 = 状态空间画布 (按工程文件/绑定真源加载)\n"
                          "· 场景 = 3D 场景视图 (与画布同源)\n"
                          "· 信号 = 📈 实时监控 · Graphic 信号分析\n"
                          "按选中任务确定配置 (可选真激活) → 应用场景 → 统一打开。只打开/定位, 不下发任何运动指令")
        _b_all.setStyleSheet(_b_all.styleSheet() + ";font-weight:bold;")
        _b_all.clicked.connect(lambda: self._open_all_clicked())
        row2.addWidget(_b_all)
        l.addLayout(row2)
        # 🆕 2026-10-14 老倪: 「将元任务, 这些信息, 体现在配置中心的 任务配置」——
        #   任务表之下再给一张**元任务表** (每个元任务 = 一个功能 + 该功能全部配置参数),
        #   列 = 元任务标准模板; 真源同 Word/PDF 导出器 (同一份构建函数)。
        #   ⚠️ 上面任务表的列一列没动 (只增一张表, 不换列)。
        try:
            self._build_meta_block(l, th)
        except Exception as _e:                                                 # noqa: BLE001
            self.meta_table = None
            _lb = QLabel("⛔ 元任务表构建失败: %r (上面任务表照常可用)" % (_e,))
            _lb.setStyleSheet("color:%s;background:transparent;" % th["C_RED"])
            _lb.setWordWrap(True)
            l.addWidget(_lb)
        self.tabs.addTab(w, "📋 任务配置")
        try:
            self._install_state_combos()          # 表建好后再挂一次 (此时 tasks_table 已存在)
        except Exception:                                                       # noqa: BLE001
            pass

        # 2) 工程配置 (参数表三列)
        cs = [c for c in d.get("CHARACTERISTIC", []) if c.get("domain") == "工程配置"]
        t2 = _mk_table(["参数", "级", "权限", "真源", "测量: 当前值", "诊断: 判据"],
                       [[c["id"], c["grade"], c["perm"], str(c["src"]).split("#")[0],
                         ("缺失 ⛔" if c.get("value") is None else str(c.get("value"))[:22]),
                         str(c["judge"])[:60]] for c in cs], th)
        self.tab2_table = t2
        self.eng_rows = [c["id"] for c in cs]
        w2 = QWidget(); l2 = QVBoxLayout(w2); l2.setContentsMargins(6, 6, 6, 6)
        # 🆕 2026-10-12 老倪: 「搞一个专门对应 AR场景的 工程配置数据」⇒ 工程配置页顶部先给这块(点位实际位置)
        try:
            self.ar_pts_card = self._ar_pts_card(th, tk)
            l2.addWidget(self.ar_pts_card)
        except Exception:                                                       # noqa: BLE001
            self.ar_pts_card = None
        self.tab2_head = QLabel("点左侧「工程配置」只筛该域; 点具体参数名直接定位到行")
        self.tab2_head.setFont(QFont("Consolas", 10))
        self.tab2_head.setStyleSheet(f"color:{th['C_GRAY']};background:transparent;")
        l2.addWidget(self.tab2_head)
        r2b = QHBoxLayout()
        b_all2 = _btn("🔎 显示全部", th)
        b_all2.clicked.connect(lambda: self._filter_eng(None))
        r2b.addWidget(b_all2); r2b.addStretch(); l2.addLayout(r2b)
        l2.addWidget(t2, 1)
        self.tabs.addTab(w2, "⚙️ 工程配置")

        # 3) 功能配置 (天玑) + 5) 性能配置 (玉衡) —— 老倪 2026-10-15: 「功能 性能 模型 标签, 改成功能配置,
        #    即标签页的名字, 对应 1~7 配置名称」⇒ 页签名就叫配置名, 所以这里建**两个页** (同一构造器、默认域不同):
        #    🧩 功能配置 默认只筛功能域 · ⚡ 性能配置 默认只筛性能域。数据同一真源 (特征库), 不复制真相。
        self.fpm_views = {}
        self.tab3_domains = ["功能配置", "性能配置", "模型配置"]
        _v_func = self._build_fpm_view(th, d, self.tab3_domains, "功能配置", "🧩 功能配置")
        _v_perf = self._build_fpm_view(th, d, self.tab3_domains, "性能配置", "⚡ 性能配置")
        self.fpm_views["功能配置"] = _v_func
        self.fpm_views["性能配置"] = _v_perf
        # 兼容别名 (老代码/判据引用 self.tab3_* ⇒ 一律指「功能配置」那张三域总表)
        self.tab3_table, self.tab3_head = _v_func["table"], _v_func["head"]
        self.tab3_btns, self.fpm_rows = _v_func["btns"], _v_func["rows"]

        # 4) 🧾 工单配置 (2026-10-14 老倪: 「将原来的工艺工单任务, 拆解成 任务配置 和 工单配置 两项」)
        #   这一页 = **工单实例粒度** (一份工单 = 一次执行): 身份 + 配方 + 变体 + 选项 + 目标 + 站点就绪。
        #   真有据: 真源 config/orders/BS_*.json; 点工单号 (表格行/左树子项) ⇒ 底部面板摊开完整配置面。
        #   ⚠️ 原有 6 列一列没动, 新维度**追加在后面**; 页签名由「🎯 工单」改成「🧾 工单配置」(与左树同名)。
        _ords = _orders_list()
        rows4 = []
        for b in _ords:
            i, r = b.get("identity") or {}, b.get("readiness") or {}
            rec = b.get("recipe") or []
            rows4.append([i.get("order_no", ""), i.get("name", ""), len(b.get("bom", [])),
                          len(b.get("process", [])), f"{r.get('site_ok', '?')}/9",
                          "⛔ 站点几何" if r.get("site_missing") else "✅",
                          "%d 段" % len(rec),
                          "%d 条" % sum(len(x.get("params") or []) for x in rec),
                          "%d 个" % len((b.get("variant") or {}).get("objects") or []),
                          _short((b.get("targets") or {}), n=2, sep=" · ", w=18),
                          _short((b.get("options") or {}).get("selected"), n=4, sep=" · ", w=22)])
        t4 = _mk_table(["工单号", "场景", "BOM", "步骤", "站点就绪", "状态",
                        "配方", "参数", "变体对象", "目标", "选项(覆盖)"], rows4, th)
        self.order_rows = [((b.get("identity") or {}).get("order_no") or "") for b in _ords]
        self.order_table = t4
        try:
            t4.itemSelectionChanged.connect(lambda: self._order_from_row(t4))
        except Exception:                                                       # noqa: BLE001
            pass
        w4 = QWidget(); l4 = QVBoxLayout(w4); l4.setContentsMargins(6, 6, 6, 6)
        _h4 = QLabel("工单配置 = 工单实例粒度 (身份/配方/变体/选项/目标/站点就绪) · 真源 %s"
                     " · 点一行看完整配置面" % os.path.relpath(ORDERS_D, ROOT))
        _h4.setFont(QFont("Consolas", 10))
        _h4.setStyleSheet("color:%s;background:transparent;" % th["C_GRAY"])
        _h4.setWordWrap(True)
        l4.addWidget(_h4)
        r4 = QHBoxLayout()
        for txt, fn in (("📋 工单列表", lambda: self._run_into("orders")),
                        ("🧾 工单配置明细(选中)", lambda: self._order_from_row(t4))):
            b4 = _btn(txt, th)
            b4.clicked.connect(lambda _=False, f=fn: f())
            r4.addWidget(b4)
        r4.addStretch(); l4.addLayout(r4); l4.addWidget(t4, 1)
        self.tabs.addTab(w4, "🧾 工单配置")

        # 5) 模型 × 工程配置
        m = _j(MATCH_J, {}) or {}
        keys = (m.get("_meta", {}).get("site_keys") or [])
        rows5 = [[r["model"], r["layer"], r["domain"],
                  " ".join("✅" if r["cells"].get(k) == "OK" else
                           ("⛔" if r["cells"].get(k) == "缺项" else "·") for k in keys),
                  "✅" if r["usable_now"] else "⛔ " + r.get("verdict", "")[:40]]
                 for r in m.get("MODELS", [])]
        t5 = _mk_table(["模型", "层", "域", "工程配置(9 项)", "判定"], rows5, th)
        w5 = QWidget(); l5 = QVBoxLayout(w5); l5.setContentsMargins(6, 6, 6, 6); l5.addWidget(t5)
        self.tabs.addTab(w5, "🧠 模型匹配")

        # 6) 现有模型配置页 (整块搬进来, 不重写)
        if model_page is not None:
            self.tabs.addTab(model_page, "🧠 模型配置")

        # 7) 文档交付 (2026-10-10 老倪: 三份文档导出做成配置中心按钮)
        w7 = QWidget()
        l7 = QVBoxLayout(w7)
        l7.setContentsMargins(6, 6, 6, 6)
        src = QLabel("三份交付文档同一数据源: 工程库 data/database/zmax/zmax_engineering.db + 平台真源 config/platform/*.json"
                     "   ·   BOM 每项挂功能/能力   ·   成本按阶段自动核算   ·   ROI 由性能指标(节拍/成功率/人效比)算出")
        src.setWordWrap(True)
        src.setFont(QFont("Consolas", 10))
        src.setStyleSheet(f"color:{th['C_GRAY']};background:transparent;")
        l7.addWidget(src)
        row7 = QHBoxLayout()
        for key in ("bundle", "project", "sor", "agreement", "bom", "metaplan"):
            label, script, args = DOC_SCRIPTS[key]
            b = _btn(("📦 " if key == "bundle" else ("🧮 " if key == "bom" else "📄 ")) + label.split(" (")[0], th)
            b.setToolTip(f"{label}\n→ tools/{script} {' '.join(args)}\n产物落在 outputs/ 下 (跑完面板给出绝对路径)")
            b.clicked.connect(lambda _, k=key: self._run_doc(k))
            row7.addWidget(b)
        row7.addStretch()
        l7.addLayout(row7)
        row7b = QHBoxLayout()
        b_copy = _btn("📋 复制产物路径", th)
        b_copy.clicked.connect(self._copy_docs)
        b_open = _btn("📂 打开产物目录", th)
        b_open.clicked.connect(self._open_docs)
        b_ref = _btn("🔍 刷新产物列表", th)
        b_ref.clicked.connect(self._copy_docs)
        for b in (b_copy, b_open, b_ref):
            row7b.addWidget(b)
        row7b.addStretch()
        l7.addLayout(row7b)
        self.docs_out = QTextEdit()
        self.docs_out.setReadOnly(True)
        self.docs_out.setFont(QFont("Consolas", 9))
        self.docs_out.setStyleSheet(f"background:{th['C_BG2']};color:{th['C_WHITE']};"
                                    f"border:1px solid {th['C_BORDER']};")
        self.docs_out.setPlainText(_doc_inventory())
        l7.addWidget(self.docs_out, 1)
        self.tabs.addTab(w7, "📄 文档配置")

        # 8) 文档预览 (2026-10-10 老倪: 内置窗口直接看根据配置生成的文档, 数据统一/一致性)
        w8 = QWidget()
        l8 = QVBoxLayout(w8)
        l8.setContentsMargins(6, 6, 6, 6)
        self.pv_head = QLabel("文档预览 — 左侧栏「📄 文档配置」点一份文档即可在这里看到它的**实际内容**")
        self.pv_head.setWordWrap(True)
        self.pv_head.setFont(QFont("Consolas", 10))
        self.pv_head.setStyleSheet(f"color:{th['C_GRAY']};background:transparent;")
        l8.addWidget(self.pv_head)
        row8 = QHBoxLayout()
        for key, lab in (("sor", "📋 看 SOR"), ("project", "📄 看立项文档"), ("agreement", "🤝 看合作协议")):
            b8 = _btn(lab, th)
            b8.clicked.connect(lambda _, k=key: self._show_doc(k))
            row8.addWidget(b8)
        b_con8 = _btn("🔍 一致性核对", th)
        b_con8.setToolTip("三份文档记录的 工程库/BOM/能力清单/治理 真源 sha 与当前真源逐一比对")
        b_con8.clicked.connect(self._show_consistency)
        row8.addWidget(b_con8)
        b_re8 = _btn("♻️ 重新生成并预览", th)
        b_re8.setToolTip("真源改过之后必须重新生成 —— 过期文档不能当交付件")
        b_re8.clicked.connect(lambda: self._show_doc(getattr(self, "_pv_kind", "sor"), force=True))
        row8.addWidget(b_re8)
        row8.addStretch()
        l8.addLayout(row8)
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(QFont("Consolas", 9))
        self.preview.setStyleSheet(f"background:{th['C_BG2']};color:{th['C_WHITE']};"
                                   f"border:1px solid {th['C_BORDER']};")
        self.preview.setPlainText(
            "判据: 文档 manifest 里记录的 工程库/BOM/能力清单/治理 真源 sha 与当前真源**逐一比对** ——\n"
            "  对不上 = ⛔ 已过期 (老倪口径: 过期文档不能当交付件), 顶部会红字告警, 点「♻️ 重新生成并预览」。\n"
            "  三份文档同源: 都读 data/database/zmax/zmax_engineering.db + config/platform/*.json, 不手抄数字。")
        l8.addWidget(self.preview, 1)
        self.tabs.addTab(w8, "📄 文档预览")

        # 9) 🏷 产品配置 (2026-10-13 老倪: 流形引擎是系统核心 ⇒ 产品标识 550A/B/C + 空间质数结构化理解能力)
        #    加在**末尾**: 保持既有页签序号不变 (「记住上次那一页」存的是序号 zmax_data/cc_last_tab.txt)
        w9 = QWidget()
        l9 = QVBoxLayout(w9)
        l9.setContentsMargins(6, 6, 6, 6)
        try:
            try:                       # 🏭 Z-MAX 平台 (与主控制台左侧卡面同源) —— 老倪 2026-10-15
                self.plat_card = self._zmax_platform_card(th)
                l9.addWidget(self.plat_card)
            except Exception as _e9p:                                           # noqa: BLE001
                self.plat_card = None
                _lb9p = QLabel("⛔ Z-MAX 平台信息块构造失败: %r" % (_e9p,))
                _lb9p.setWordWrap(True)
                l9.addWidget(_lb9p)
            l9.addWidget(self._product_card(th))
        except Exception as _e9:                                                # noqa: BLE001
            _lb9 = QLabel("⛔ 产品配置区构造失败: %r" % (_e9,))
            _lb9.setWordWrap(True)
            l9.addWidget(_lb9)
        l9.addStretch()
        self.tabs.addTab(w9, "🏷 产品配置")
        self._apply_tab_order()          # ⭐ 页签次序 = 北斗次序 (老倪 2026-10-15)

        # 🆕 2026-10-12: 记住上次看的那一页 —— 老倪在「工程配置」页干活时, 任何重启后回来还是这一页(不用再点一遍)
        try:
            _mk = os.path.join(ROOT, "zmax_data", "cc_last_tab.txt")
            if os.path.exists(_mk):
                # 2026-10-15: 原来记的是**页序号** —— 页签次序改成北斗次序后, 同一个序号指向的是别的页
                # (回来会落在错的页)。改成记**页名**, 兼容老的纯数字文件 (按序号解释一次)。
                _v = open(_mk, encoding="utf-8").read().strip()
                _i = -1
                if _v.isdigit():
                    _i = int(_v)
                elif _v:
                    _i = self._tab_index_by_title(_v)
                if 0 <= _i < self.tabs.count():
                    self.tabs.setCurrentIndex(_i)

            def _remember(_idx):
                try:
                    os.makedirs(os.path.dirname(_mk), exist_ok=True)
                    with open(_mk, "w", encoding="utf-8") as f:
                        f.write(str(self.tabs.tabText(int(_idx))))
                except Exception:                                               # noqa: BLE001
                    pass
            self.tabs.currentChanged.connect(_remember)
        except Exception:                                                       # noqa: BLE001
            pass

    # ── 文档配置: 预览 + 一致性 (2026-10-10 老倪) ──
    def _build_fpm_view(self, th, d, domains, default_dom, tab_title):
        """建一张「特征库三域」页 (功能配置 / 性能配置 各一张, 同一真源)。

        老倪 2026-10-15: 「功能 性能 模型 标签, 改成功能配置, 即标签页的名字, 对应 1~7 配置名称」
        ⇒ 页签名就叫配置名, 所以功能配置与性能配置各要一个页签。两页读的是**同一份特征库真源**,
        只是默认筛的域不同 (页内可按别的域按钮, 也可由左树点星/顶部星图改)。
        """
        cs = [c for c in d.get("CHARACTERISTIC", []) if c.get("domain") in domains]
        t = _mk_table(["域", "参数", "级", "权限", "真源", "值", "判据"],
                      [[c["domain"], c["id"], c["grade"], c["perm"], str(c["src"]).split("#")[0],
                        ("缺失 ⛔" if c.get("value") is None else str(c.get("value"))[:20]),
                        str(c["judge"])[:48]] for c in cs], th)
        w = QWidget(); l = QVBoxLayout(w); l.setContentsMargins(6, 6, 6, 6)
        head = QLabel("点左侧「功能配置 / 性能配置 / 模型配置」只筛该域; 点具体参数名直接定位到行")
        head.setFont(QFont("Consolas", 10))
        head.setStyleSheet(f"color:{th['C_GRAY']};background:transparent;")
        l.addWidget(head)
        view = {"w": w, "table": t, "rows": [(c["domain"], c["id"]) for c in cs], "head": head,
                "btns": {}, "default": default_dom, "title": tab_title}
        row = QHBoxLayout()
        for dom in domains:
            b = _btn("🔎 " + dom, th)
            b.setCheckable(True)
            b.setStyleSheet((b.styleSheet() or "")
                            + ("QPushButton:checked{background:%s;color:#0b0f14;border:1px solid %s;}"
                               % (th["C_YELLOW"], th["C_YELLOW"])))
            b.setToolTip("只筛%s域" % dom)
            b.clicked.connect(lambda _=False, dd=dom, vv=view: self._filter_fpm(dd, None, vv))
            view["btns"][dom] = b
            row.addWidget(b)
        b_all = _btn("显示全部", th)
        b_all.clicked.connect(lambda _=False, vv=view: self._filter_fpm(None, None, vv))
        row.addWidget(b_all)
        row.addStretch(); l.addLayout(row)
        l.addWidget(t, 1)
        self.tabs.addTab(w, tab_title)
        self._apply_fpm_filter(view, default_dom)      # 本页默认就筛自己那一域
        return view

    # ⭐ 主页面(右工作区)页签次序 = 北斗次序 (老倪 2026-10-15: 「下面主页面标签的顺序也不一致,
    #   应该显示 产品配置标签, 然后是第二个任务配置, 依次顺序排列」)。非七星的视图排在七阵之后。
    _TAB_ORDER = ("产品配置", "任务配置", "功能配置", "模型配置", "性能配置", "工单配置", "文档配置",
                  "工程配置", "模型匹配", "文档预览")

    def _apply_tab_order(self):
        """按北斗次序重排页签 (moveTab, 不重建页、不动页内状态)。

        要放在所有 addTab 之后: 页签的创建次序是按代码里构造的先后 (任务/工程/功能性能模型/工单/模型匹配/
        模型配置/文档交付/文档预览/产品) —— 没有体系含义, 产品配置原来还排在最后一位。
        """
        _bar = self.tabs.tabBar()
        for _target, _kw in enumerate(self._TAB_ORDER):
            _cur = next((i for i in range(self.tabs.count()) if _kw in self.tabs.tabText(i)), None)
            if _cur is None:
                continue
            if _cur != _target:
                _bar.moveTab(_cur, _target)
        return [self.tabs.tabText(i) for i in range(self.tabs.count())]

    def _pv_tab_index(self):
        for i in range(self.tabs.count()):
            if "文档预览" in self.tabs.tabText(i):
                return i
        return -1

    def _show_doc_config(self):
        """7 · 瑶光·文档配置 → 切到「📄 文档交付」页 + 底部写一句真源摘要 (不去抢别的页)。"""
        _i = self._tab_index_by_title("文档配置")
        if _i >= 0:
            self.tabs.setCurrentIndex(_i)
        _rows = ["7 · 瑶光 · 文档配置 (定记录)"]
        for _k in ("sor", "project", "agreement"):
            try:
                _st = _doc_state(_k)
                _rows.append("   %s %s — %s" % (_doc_mark(_k), _st.get("name", _k), _st.get("why", "")))
            except Exception:                                                   # noqa: BLE001
                _rows.append("   %s %s (状态取不到)" % (_doc_mark(_k), _k))
        _rows.append("   正文预览在「📄 文档预览」页; 一致性核对在文档页最后一列。")
        self.out.setPlainText("\n".join(_rows))
        self._fit_out()

    def _show_doc(self, kind, force=False):
        """内置窗口看文档: 没有产物就先真跑生成, 再读回 .docx 实际内容; 过期给红字告警。"""
        from PyQt5.QtWidgets import QApplication
        self._pv_kind = kind
        i = self._pv_tab_index()
        if i >= 0:
            self.tabs.setCurrentIndex(i)
        if force or not _latest_doc(kind):
            self.out.setPlainText(f"▶ 生成 {DOCS[kind]['name']} … (数据源: 工程库 + 平台真源)")
            QApplication.processEvents()
            self.out.setPlainText(_run_script(DOCS[kind]["script"]))
            QApplication.processEvents()
        st = _doc_state(kind)
        if not st["doc"]:
            self.pv_head.setText(f"⛔ {st['name']}: 取不到产物 ({st['why']})")
            self.preview.setPlainText("生成失败 —— 看底部结果面板的日志 (退出码非 0 时那里有真原因)。")
            return
        mark = "⛔ 已过期" if st["stale"] else "✅ 与当前真源一致"
        self.pv_head.setText(
            f"{st['name']} · {os.path.basename(st['doc']['docx'])}"
            f" · 生成 {time.strftime('%m-%d %H:%M', time.localtime(st['doc']['mtime']))} · {mark} · {st['why']}\n"
            + "   ".join(f"{v} {l}: {r}→{c}" for l, r, c, v in st["rows"])
            + f"\ndocx 绝对路径: {st['doc']['docx']}")
        html = _render_doc_html(st["doc"]["docx"])
        if st["stale"]:
            html = ('<p style="color:#ff8a8a;font-size:11pt;font-weight:700;margin:6px 0;">'
                    '⛔ 一致性告警: %s —— 这份文档是用旧真源生成的, 不能当交付件, 点「♻️ 重新生成并预览」</p>'
                    '<hr style="border:1px solid #7a2b2b;">' % _esc(st["why"])) + html
        self.preview.setHtml(html)

    def _show_consistency(self):
        """三份文档 × 当前真源 一致性核对 (数据统一/一致性的判据视图)。"""
        i = self._pv_tab_index()
        if i >= 0:
            self.tabs.setCurrentIndex(i)
        dbp = os.path.join(ROOT, "data", "database", "zmax", "zmax_engineering.db")
        L = ["═══ 三份交付文档 × 真源 一致性核对 ═══",
             f"真源: 工程库 data/database/zmax/zmax_engineering.db  (当前 sha256 {_sha256(dbp)[:16] or '?'})", ""]
        for kind in ("project", "sor", "agreement"):
            st = _doc_state(kind)
            ok = st["doc"] and not st["stale"]
            L.append(f"[{'✅' if ok else '⛔'}] {st['name']}: " + (st["why"] if st["doc"] else "还没生成 (点下面按钮或左侧栏点它)"))
            if st["doc"]:
                L.append(f"      docx: {st['doc']['docx']}")
                for l, r, c, v in st["rows"]:
                    L.append(f"      {v} {l}: 文档记录 {r} · 当前 {c}")
            L.append("")
        L.append("── 当前真源文件 (时间 · sha256 前12 · 路径) ──")
        for key, label, cands in SRC_DEFS:
            rel, fp = _find_src(cands)
            if fp:
                L.append(f"  {time.strftime('%m-%d %H:%M', time.localtime(os.path.getmtime(fp)))}  "
                         f"{_sha256(fp)[:12]}  {rel}   ({label})")
        rel, fp = _find_src([PLATFORM_SRC[1]])
        if fp:
            L.append(f"  {time.strftime('%m-%d %H:%M', time.localtime(os.path.getmtime(fp)))}  "
                     f"{_sha256(fp)[:12]}  {rel}   ({PLATFORM_SRC[0]} · manifest 未记录, 按时间戳判)")
        L += ["", "判据: 三份文档 manifest 记录的 sha 必须 = 当前真源 sha; 任一不符即 ⛔ 过期,",
              "      重新生成后三份的 工程库 sha 必然相同 (同源) —— 这就是『数据统一』的可验证口径。"]
        self.pv_head.setText("一致性核对: 三份文档记录的 sha vs 当前真源 (对不上 = 过期, 需重新生成)")
        self.preview.setPlainText("\n".join(L))

    # ── 文档交付 (2026-10-10) ──
    def _goto_docs(self):
        for i in range(self.tabs.count()):
            if "文档" in self.tabs.tabText(i):
                self.tabs.setCurrentIndex(i)
                self._copy_docs()
                return
        self.out.setPlainText("⛔ 文档交付页签缺失 (页面构建异常)")

    def _run_patent(self, fn=None):
        """专利交底书一键导出: 传 fn 只出该功能 1 份 (快), 不传 = 74 个功能全出 (几分钟)。
        执行体 = tools/export_patent_draft.py —— 内容逐条标出处, 出 md + docx + pdf。"""
        from PyQt5.QtWidgets import QApplication
        args = ["--fn", fn] if fn else ["--all"]
        self.out.setPlainText("▶ 专利交底书导出%s …\n"
                              "   一个功能 = 一份交底书 (技术问题/技术方案/有益效果/实施例/证据清单/检索词)\n"
                              "   真源: config_meta.json + function_notes.json + 画布连线 + 代码文件行\n"
                              "   产物: reports/patents/<功能号>_<名称>_专利交底书.md / .docx / .pdf"
                              % ("（%s）" % fn if fn else "（全部 74 个功能）"))
        QApplication.processEvents()
        self.out.setPlainText(_run_script("export_patent_draft.py", args))
        self._fit_out()
        QApplication.processEvents()

    def _patent_selected(self, *_a):
        """取元任务表选中行的功能号 → 只导这一份 (没选中就明说, 不静默)。"""
        t = getattr(self, "meta_table", None)
        rows = getattr(self, "_meta_rows", [])
        if t is None or not rows:
            self._log_cc("   ⛔ 专利导出: 先在元任务表里点一行")
            return
        r = t.currentRow()
        if not (0 <= r < len(rows)):
            self._log_cc("   ⛔ 专利导出: 先在元任务表里点一行 (共 %d 条)" % len(rows))
            return
        self._run_patent(rows[r].get("fn_id"))

    def _run_doc(self, key):
        """点按钮必出结果: 真跑导出器, 面板给日志, 右侧列出可复制的绝对路径。"""
        from PyQt5.QtWidgets import QApplication
        label, script, args = DOC_SCRIPTS[key]
        self.out.setPlainText(f"▶ {label} 运行中… (数据源: 工程库 + 平台真源)")
        QApplication.processEvents()
        self.out.setPlainText(_run_script(script, args))
        self._fit_out()
        QApplication.processEvents()
        inv = _doc_inventory()
        if hasattr(self, "docs_out"):
            self.docs_out.setPlainText(inv)

    def _copy_docs(self):
        from PyQt5.QtWidgets import QApplication
        inv = _doc_inventory()
        if hasattr(self, "docs_out"):
            self.docs_out.setPlainText(inv)
        QApplication.clipboard().setText(inv)
        self.out.setPlainText("📋 产物路径已复制到剪贴板 (可直接粘到聊天/文档里):\n" + inv)

    def _open_docs(self):
        import subprocess
        d = _newest_out_dir("outputs/docs_bundle") or _newest_out_dir("outputs/project_docs")
        if not d:
            self.out.setPlainText("⚠️ 还没有产物目录 —— 先点「📦 三件套导出」")
            return
        try:
            subprocess.Popen(["xdg-open", d])
            self.out.setPlainText(f"📂 已打开: {d}")
        except Exception as e:  # noqa: BLE001
            self.out.setPlainText(f"⛔ 打不开文件管理器: {e}\n路径 (可复制): {d}")

    # ── 结果面板 ──
    def _back_home(self):
        """← 返回主窗口: 优先走控制台左侧栏的真实路径(「← 返回首页」按钮 → layer_clicked),
        退路是直接调主窗口的 _on_nav('home')。两条都不通才提示, 不静默。"""
        win = self.window()
        try:
            sb = getattr(win, "sidebar", None)
            if sb is not None:
                for b in sb.findChildren(QPushButton):
                    t = (b.text() or "")
                    if "首页" in t or "主窗口" in t:
                        b.click()                      # 走真实 UI 路径 (同步侧栏高亮 + 切栈)
                        return
        except Exception:  # noqa: BLE001
            pass
        fn = getattr(win, "_on_nav", None)
        if callable(fn):
            try:
                fn("home")
                return
            except Exception:  # noqa: BLE001
                pass
        self.out.setPlainText("⛔ 找不到主窗口的导航入口 (sidebar/_on_nav 都不在)——请直接用左侧栏「← 返回首页」")

    def _selected_task(self):
        r = self.tasks_table.currentRow()
        if r < 0:
            return None
        it = self.tasks_table.item(r, 0)
        return it.text() if it else None

    # ───────── 🚀 标准打开流程第二步: 确定配置 → 统一打开工程 (2026-10-12 老倪) ─────────
    def select_task_row(self, tid):
        """按任务ID选中任务表那一行 (给「统一打开工程」定位; 找不到返回 False, 不假装选中)。"""
        try:
            for _r in range(self.tasks_table.rowCount()):
                _it = self.tasks_table.item(_r, 0)
                if _it is not None and (_it.text() or "").strip() == str(tid).strip():
                    self.tasks_table.setCurrentCell(_r, 0)
                    self.tasks_table.selectRow(_r)
                    self.tasks_table.scrollToItem(_it)
                    return True
        except Exception:  # noqa: BLE001
            return False
        return False

    def _open_all_clicked(self):
        """🚀 统一打开工程按钮: 有主窗口回调走主窗口 (同一执行体, 不留第二套逻辑); 否则退回命令通道。"""
        from PyQt5.QtWidgets import QApplication as _QA
        _tid = (self._selected_task() or "").strip()
        _cb = getattr(self, "on_open_all", None)
        if callable(_cb):
            self.out.setPlainText("🚀 统一打开工程… 任务 = %s (真源: 绑定真源 config/ss_task_binding.json)"
                                  % (_tid or "当前活跃任务"))
            _QA.processEvents()
            try:
                _steps = _cb(task=_tid, activate=bool(_tid), page=self) or []
                self.out.setPlainText("🚀 统一打开工程 %s\n\n%s" % (
                    "完成" if all(s[1] for s in _steps) else "有失败 (逐条见下)",
                    "\n".join("  %s %s : %s" % ("✅" if o else "❌", n, d) for n, o, d in _steps)))
            except Exception as _e:  # noqa: BLE001
                self.out.setPlainText("⛔ 统一打开工程失败: %s" % _e)
            self._fit_out()
            return
        try:      # 兜底: 控制台命令通道 (控制台内部同源 _open_all_cmd)
            with open("/tmp/zmax_nav_cmd", "w", encoding="utf-8") as _f:
                _f.write("open_all\n")
            self.out.setPlainText("🚀 已把「统一打开工程」写进控制台命令通道 (/tmp/zmax_nav_cmd: open_all)\n"
                                  "   控制台会在 300ms 内执行: 状态空间画布 · 3D 场景 · 信号分析")
        except Exception as _e:  # noqa: BLE001
            self.out.setPlainText("⛔ 命令通道写入失败: %s" % _e)
        self._fit_out()

    def _run_selected(self, fn, use_sel=False, **kw):
        """按钮入口: use_sel=True 时取表格选中行的任务ID传进去。"""
        if use_sel:
            tid = self._selected_task()
            if not tid:
                self.out.setPlainText("⛔ 先在任务表里选一行 (点一下任务ID那个格子)")
                return
            kw["arg"] = tid
        self._run_into(fn, **kw)

    # ───────── 🎛 按任务ID 激活 (与用户手点「活跃属性」下拉/「激活选中任务」完全同一条路径) ─────────
    def activate_task(self, tid):
        """给命令通道用: 选中该任务的活跃属性下拉 → 置「★ 活跃」⇒ 触发 _on_task_state_changed
        (落绑定真源 + 台账 + 自动存档), 不经任何旁路。返回 (ok, msg)。"""
        tid = str(tid or "").strip()
        if not tid:
            return False, "用法: cfg_task <TASK-ID>"
        try:
            if not self.select_task_row(tid):
                return False, "任务表里没有 %s 这一行" % tid
            _r = self.tasks_table.currentRow()
            cb = self.tasks_table.cellWidget(_r, _ACT_COL)
            if cb is None:
                return False, "第 %d 行没有活跃属性下拉 (界面结构变了?)" % _r
            if str(cb.currentText()) == "★ 活跃":
                return True, "%s 已经是「★ 活跃」" % tid
            cb.setCurrentText("★ 活跃")            # ← 真触发下拉 change 信号 (不是直接调内部函数)
            return True, "已通过配置中心「活跃属性」下拉激活 %s" % tid
        except Exception as e:                                                  # noqa: BLE001
            return False, "%s: %s" % (type(e).__name__, e)

    def _fit_out(self):
        """底部面板按内容自适应高度 (老倪口径: 界面不许挤/不许截断); 超过 320px 才交给滚动条。"""
        try:
            d = self.out.document()
            d.setTextWidth(max(200, self.out.viewport().width()))
            h = int(d.size().height()) + 16
            cap = int(min(420, max(200, self.height() * 0.45)))   # 小窗口别把上方表格挤没
            self.out.setFixedHeight(max(130, min(h, cap)))
        except Exception:  # noqa: BLE001
            pass

    def _run_into(self, fn, **kw):
        self.out.setPlainText(_run(fn, **kw))
        self._fit_out()


def build_config_center(model_page=None, theme=None):
    """studio.py 调用入口: 返回配置中心新页 (失败时抛异常, 由 studio 兜底回退)。"""
    return ConfigCenterPage(model_page=model_page, theme=theme)
