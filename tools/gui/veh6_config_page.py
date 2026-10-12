# -*- coding: utf-8 -*-
"""VEH.6 配置中心 · 页面 (主要工程配置 = 任务配置)

老倪 2026-10-09: 「主要工程配置, 例如 上下料的任务配置」⇒ 任务配置是首屏。
结构: 左五域树 + 右工作区(页签, 首屏=任务配置) + 底部结果面板(点了必出结果)。

本文件只依赖 PyQt5 + json, **不 import studio** (颜色由 studio 传进来), 保证可离屏单测。
每个按钮都调用 tools/config_center.py 的同一份函数 (一份逻辑两处用), 输出抓到面板里。
"""
from __future__ import annotations

import glob
import io
import json
import os
import sys
import time
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOLS = os.path.join(ROOT, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

from PyQt5.QtCore import Qt, QSettings, QTimer  # noqa: E402
from PyQt5.QtGui import QColor, QFont  # noqa: E402
from PyQt5.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel,  # noqa: E402
                             QPushButton, QSizePolicy, QSplitter, QTableWidget, QTableWidgetItem,
                             QComboBox, QTabWidget, QTextEdit, QTreeWidget, QTreeWidgetItem,
                             QVBoxLayout, QWidget)

TASKS_J = os.path.join(ROOT, "config", "tasks", "tasks.json")
MCD_J = os.path.join(ROOT, "config", "mcd", "zmax_mcd.json")
MATCH_J = os.path.join(ROOT, "config", "mcd", "match_matrix.json")
ORDERS_D = os.path.join(ROOT, "config", "orders")
BIND_J = os.path.join(ROOT, "config", "ss_task_binding.json")

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


# ── 三份交付文档 (2026-10-10): 与 config_center.py 同一份真源, 点了必出结果 ──
DOC_SCRIPTS = {
    "bundle":    ("三件套导出 (立项文档 + SOR + 协议)", "docs_bundle.py", []),
    "project":   ("项目立项文档 (Word)", "project_doc_export.py", []),
    "sor":       ("供应商 SOR 需求规格说明书 (Word)", "sor_export.py", []),
    "agreement": ("机器人数据平台合作与模型授权协议 (Word)", "agreement_export.py", []),
    "bom":       ("BOM / 成本 / ROI 算账 (不出文档)", "project_doc_export.py", ["--check"]),
}
DOC_DIRS = ["outputs/docs_bundle", "outputs/project_docs", "outputs/sor", "outputs/agreements"]


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
    """🆕 2026-10-11 老倪: 「任务7 …场景就对应 AR」—— 任务表新增「场景」列 (短标签 · 场景ID)。

    🥽 2026-10-12 老倪: 「信号分析也用 绿色/蓝色/紫色 代表对应不同的场景」⇒ 配置中心这一列**同色**,
    颜色/映射单一真源 = tools/ss_scene_switch.py(插拔#2e8b57 绿 · 摆盘#1f6feb 蓝 · AR#8957e5 紫), 一致到像素。
    """
    sid = t.get("scene_ref") or "—"
    sc = _scenes_index().get(sid) or {}
    st = _SCENE_SHORT.get(sc.get("scene_type"), sc.get("scene_type") or "")
    return ("%s · %s" % (st, sid)) if st else str(sid)


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
        sp.addWidget(self.tabs)
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

    def showEvent(self, ev):
        """每次显示时再扫一遍(有的页内容是后填的, 构造时还不宽)。"""
        super().showEvent(ev)
        try:
            self._wrap_wide_labels(self.tabs)
        except Exception:                                                       # noqa: BLE001
            pass

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
        chars = d.get("CHARACTERISTIC", [])
        doms = []
        for dom in ("模型配置", "工程配置", "功能配置", "性能配置"):
            cs = [c for c in chars if c.get("domain") == dom]
            rd = sum(1 for c in cs if c.get("ready"))
            doms.append((f"{dom}  {rd}/{len(cs)}", "⛔" if rd < len(cs) else "✅",
                         [c["id"] for c in cs if not c.get("ready")]))
        # 文档配置 (2026-10-10): 三份外发/立项文档 + 一致性核对
        dm = [_doc_mark(k) for k in ("sor", "project", "agreement")]
        # 计数是"文档份数", 第 4 项是一致性核对视图 ⇒ 提示里写清, 免得看成"子项数对不上"
        self._doc_group_tip = ("文档 3/3 = 三份文档 (供应商外发 SOR / 项目立项文档 / 合作协议) 全部就绪且与当前真源一致;\n"
                               "第 4 项『一致性核对』是核对视图, 不计入份数。")
        self._doc_group_tip_on = True
        doms.append((f"文档配置  文档 {sum(1 for m in dm if m == '✅')}/3", "⛔" if "⛔" in dm else "✅",
                     ["供应商外发 SOR", "项目立项文档", "合作协议", "一致性核对"]))
        doms.append((f"工艺·工单  任务 {len(tk.get('tasks', []))}",
                     "⛔" if (tk.get("tasks") and any(t.get("blocked_by_site") for t in tk["tasks"])) else "✅",
                     [t["task_id"] for t in tk.get("tasks", [])]))
        self.tree.clear()
        for label, mark, kids in doms:
            it = QTreeWidgetItem([f"{mark} {label}"])
            if label.startswith("文档") and getattr(self, "_doc_group_tip_on", False):
                it.setToolTip(0, self._doc_group_tip)
            for k in kids:
                QTreeWidgetItem(it, [f"   {k}"])
            self.tree.addTopLevelItem(it)
            it.setExpanded(label.startswith("工艺") or label.startswith("文档"))

    # ── 域过滤: 点左树域节点 → 右侧切到对应页并只筛该域的行; 点参数 ID → 直接定位该行 ──
    def _install_state_combos(self):
        """活跃列 (第 9 列) 每行一个下拉: ★ 活跃 / ○ 未激活 / — 无配置。"""
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
                t.setCellWidget(r, 8, cb)
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

    def _reload_task_states(self):
        """重算全表活跃列 + 表头计数 (改一个状态, 全表跟着动: 旧活跃会自动变未激活)。"""
        import ss_task_state as _ts
        bind = _j(BIND_J, {}) or {}
        self._act_now = bind.get("active_task")
        ids = getattr(self, "_task_rows", None) or []
        for tid in ids:
            cb = (getattr(self, "_state_cbs", {}) or {}).get(tid)
            if cb is None:
                continue
            cur = _ts.cell(tid, self._act_now)
            cb.blockSignals(True)
            cb.setCurrentText(cur if cur in _STATE_ITEMS else "— 无配置")
            cb.blockSignals(False)
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

    def _filter_fpm(self, dom=None, param=None):
        """功能/性能/模型三域合页: dom=None 显示全部; 否则只留该域; param 再精确定位到行。"""
        idx = self._tab_index_by_title("功能·性能")
        if idx >= 0:
            self.tabs.setCurrentIndex(idx)
        t = self.tab3_table
        shown, sel = 0, -1
        for r in range(t.rowCount()):
            d, pid = self.fpm_rows[r] if r < len(self.fpm_rows) else ("", "")
            ok = (dom is None or d == dom) and (param is None or pid == param)
            t.setRowHidden(r, not ok)
            if ok:
                shown += 1
                if param and pid == param:
                    sel = r
        if sel >= 0:
            t.selectRow(sel)
            t.scrollToItem(t.item(sel, 0))
        self.tab3_head.setText(("仅显示: %s%s" % (dom or "全部", (" / " + param) if param else ""))
                               + " · %d 项" % shown)

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

    def _on_tree(self, item, _col):
        txt = item.text(0)
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
        if "任务配置" in txt or "工艺" in txt:
            self.tabs.setCurrentIndex(0)
        self._run_into("tasks" if "TASK" in txt.upper() else "overview")

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
            ["任务ID", "类型", "场景", "工艺步骤", "适用段", "粒度", "启用节点", "禁用节点",
             "档位(开)", "模型", "活跃", "状态"],
            [[t["task_id"], t["recipe_type"], _scene_cell(t),
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
        # 🆕 2026-10-11 老倪: 「配置中心的活跃属性列, 增加新功能, 用户可以自主调整 活跃/未激活 等状态, 用下拉菜单」
        #   设计: 活跃列每行一个下拉 (★ 活跃 / ○ 未激活 / — 无配置) —— 选「★ 活跃」= 真激活该任务 (走 ss_task_bind --activate,
        #   写绑定真源 + 台账, 回读校验); 选「未激活/无配置」= 记手选台账 (当前活跃任务不许直接取消; 有运行证据的不许降级)。
        #   改完立刻重算全表 + 表头计数, 动作与结果都写进下方日志 (失败照实说, 不假成功)。
        # 🆕 场景/模型列的完整说明放 tooltip (单元格只放短标签, 完整口径不截断)
        try:
            for _i, _t in enumerate(tk.get("tasks", [])):
                for _c, _tip in ((2, _scene_tip(_t)), (9, _model_tip(_t)), (0, _points_tip(_t))):
                    _it = self.tasks_table.item(_i, _c)
                    if _it is not None:
                        _it.setToolTip(_tip)
                # 🥽 2026-10-12: 场景列按三色上色 (插拔绿/摆盘蓝/AR紫) —— 与 3D 场景按钮、信号分析同色同源
                _col = _scene_color(_t)
                _it2 = self.tasks_table.item(_i, 2)
                if _it2 is not None and _col:
                    from PyQt5.QtGui import QColor as _QC, QBrush as _QB
                    _it2.setForeground(_QB(_QC(_col)))
                    _it2.setToolTip((_it2.toolTip() or "") + "\n场景色 %s (与 3D 场景按钮 / 信号分析 同一套色)" % _col)
        except Exception:                                                       # noqa: BLE001
            pass
        self._task_rows = [t["task_id"] for t in tk.get("tasks", [])]
        self._act_now = act
        self._install_state_combos()
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
        row.addStretch()
        l.addLayout(row); l.addWidget(self.tasks_table, 1)
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

        # 3) 功能·性能·模型 (参数表)
        cs3 = [c for c in d.get("CHARACTERISTIC", []) if c.get("domain") in ("功能配置", "性能配置", "模型配置")]
        t3 = _mk_table(["域", "参数", "级", "权限", "真源", "值", "判据"],
                       [[c["domain"], c["id"], c["grade"], c["perm"], str(c["src"]).split("#")[0],
                         ("缺失 ⛔" if c.get("value") is None else str(c.get("value"))[:20]),
                         str(c["judge"])[:48]] for c in cs3], th)
        self.tab3_table = t3
        self.fpm_rows = [(c["domain"], c["id"]) for c in cs3]
        self.tab3_domains = ["功能配置", "性能配置", "模型配置"]
        w3 = QWidget(); l3 = QVBoxLayout(w3); l3.setContentsMargins(6, 6, 6, 6)
        self.tab3_head = QLabel("点左侧「功能配置 / 性能配置 / 模型配置」只筛该域; 点具体参数名直接定位到行")
        self.tab3_head.setFont(QFont("Consolas", 10))
        self.tab3_head.setStyleSheet(f"color:{th['C_GRAY']};background:transparent;")
        l3.addWidget(self.tab3_head)
        r3b = QHBoxLayout()
        for dom in self.tab3_domains:
            b = _btn("🔎 " + dom, th)
            b.clicked.connect(lambda _, d=dom: self._filter_fpm(d))
            r3b.addWidget(b)
        b_all3 = _btn("显示全部", th)
        b_all3.clicked.connect(lambda: self._filter_fpm(None))
        r3b.addWidget(b_all3)
        r3b.addStretch(); l3.addLayout(r3b)
        l3.addWidget(t3, 1)
        self.tabs.addTab(w3, "🧩 功能·性能·模型")

        # 4) 工单
        rows = []
        for f in sorted(glob.glob(os.path.join(ORDERS_D, "BS_*.json"))):
            b = _j(f, {}) or {}
            i, r = b.get("identity", {}), b.get("readiness", {})
            rows.append([i.get("order_no", ""), i.get("name", ""), len(b.get("bom", [])),
                         len(b.get("process", [])), f"{r.get('site_ok', '?')}/9",
                         "⛔ 站点几何" if r.get("site_missing") else "✅"])
        t4 = _mk_table(["工单号", "场景", "BOM", "步骤", "站点就绪", "状态"], rows, th)
        w4 = QWidget(); l4 = QVBoxLayout(w4); l4.setContentsMargins(6, 6, 6, 6)
        r4 = QHBoxLayout()
        b4 = _btn("📋 工单列表", th); b4.clicked.connect(lambda: self._run_into("orders")); r4.addWidget(b4)
        r4.addStretch(); l4.addLayout(r4); l4.addWidget(t4, 1)
        self.tabs.addTab(w4, "🎯 工单")

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
        for key in ("bundle", "project", "sor", "agreement", "bom"):
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
        self.tabs.addTab(w7, "📄 文档交付")

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

        # 🆕 2026-10-12: 记住上次看的那一页 —— 老倪在「工程配置」页干活时, 任何重启后回来还是这一页(不用再点一遍)
        try:
            _mk = os.path.join(ROOT, "zmax_data", "cc_last_tab.txt")
            if os.path.exists(_mk):
                _i = int(open(_mk, encoding="utf-8").read().strip() or 0)
                if 0 <= _i < self.tabs.count():
                    self.tabs.setCurrentIndex(_i)

            def _remember(_idx):
                try:
                    os.makedirs(os.path.dirname(_mk), exist_ok=True)
                    with open(_mk, "w", encoding="utf-8") as f:
                        f.write(str(int(_idx)))
                except Exception:                                               # noqa: BLE001
                    pass
            self.tabs.currentChanged.connect(_remember)
        except Exception:                                                       # noqa: BLE001
            pass

    # ── 文档配置: 预览 + 一致性 (2026-10-10 老倪) ──
    def _pv_tab_index(self):
        for i in range(self.tabs.count()):
            if "文档预览" in self.tabs.tabText(i):
                return i
        return -1

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

    def _run_selected(self, fn, use_sel=False, **kw):
        """按钮入口: use_sel=True 时取表格选中行的任务ID传进去。"""
        if use_sel:
            tid = self._selected_task()
            if not tid:
                self.out.setPlainText("⛔ 先在任务表里选一行 (点一下任务ID那个格子)")
                return
            kw["arg"] = tid
        self._run_into(fn, **kw)

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
