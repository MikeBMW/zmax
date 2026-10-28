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

老倪 2026-10-19: 「将 工单配置，替换成 工程配置；将工单，放到文档配置选项卡，将成本/报价 商业模式的内容，
                  都迁移到 文档配置里；整体上调整原来的 北斗七星的 开阳的描述」
  ⇒ 六阵由「工单配置·定调度」改为「工程配置·定落地」(工程库/参数注册表/工程-模型匹配/AR 示教点位);
    工单实例 + 成本/报价 + 商业模式 三块并入七阵「📄 文档配置」—— 页签仍是 7 个, 正好七星。
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

from PyQt5.QtCore import Qt, QSettings, QTimer, QEvent, QSize, QRectF, QPointF  # noqa: E402
from PyQt5.QtGui import (QColor, QFont, QKeySequence, QFontMetrics, QLinearGradient,  # noqa: E402
                         QPainter, QPen, QRadialGradient, QBrush)
from PyQt5.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QGridLayout, QHBoxLayout,  # noqa: E402
                             QFrame, QHeaderView, QLabel, QLineEdit, QMenu, QPushButton, QRadioButton, QScrollArea, QSizePolicy,
                             QSplitter, QShortcut,
                             QTableWidget, QTableWidgetItem, QComboBox, QTabWidget, QTextBrowser, QTextEdit, QTreeWidget,
                             QSpinBox, QDoubleSpinBox,
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

# 🎨 产品档位卡 (老倪 2026-10-21: 「VEH.6.01 550A / VEH.6.02 550B / VEH.6.03 550C 这些配置的 UI 设计应该
#   更加绚丽一些, 现在只是一个小白点来选择配置, 不好看 —— 你来增强设计 … 要明显, 好看一些」)
#   只改**外观**: 档位语义仍是 QRadioButton 单选 (判据 _prod_btns / _prod_group / text() 全部照旧)。
#   三档各一套编号 + 主色/辉光 (开发紫 / 调试青 / 量产绿), 选中 = 主色渐变 + 辉光描边 + 「✓ 当前」胶囊。
PRODUCT_CARDS = {
    "550A": {"code": "VEH.6.01", "c": "#6E6AC8", "glow": "#B6B3E6"},
    "550B": {"code": "VEH.6.02", "c": "#3D8CA0", "glow": "#8FC0CC"},
    "550C": {"code": "VEH.6.03", "c": "#4A8F72", "glow": "#93C2AC"},
}

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


def _task_obj(tid):
    """tasks.json 里的一条任务 (真源); 没有就 None。"""
    return next((x for x in (_j(TASKS_J, {}) or {}).get("tasks", []) if x.get("task_id") == tid), None)


_LAYER_ORD = {"L2": 0, "L3": 1, "L4": 2, "L4/L5": 2, "L5": 2, "PLAT": 3}


HAND_CN = {"R": "右手", "L": "左手", "BOTH": "双手"}
HAND_COLOR = {"R": "#4a90e0", "L": "#3fbf7f", "BOTH": "#b58cf0"}


def _hand_of(text):
    """从一句中文描述里判手别 (真源里 左臂/右臂 是写明的); 判不出就 ''(未知), 不猜。"""
    t = text or ""
    l = "左臂" in t or "左手" in t
    r = "右臂" in t or "右手" in t
    if l and r:
        return "BOTH"
    if l:
        return "L"
    if r:
        return "R"
    return ""


def _task_level_meta(tid):
    """该任务**自己的**元任务 (任务级元任务 = 它跑起来的那几个执行元任务), 带手别 + 时空 + 段级明细。

    老倪 2026-10-28 两轮:
      ① 「TASK-07-AOI 任务的元任务, 要有对应关系, 点击 TASK0-7 下面的元任务要对应变化」
      ② 「只有 5 个元任务么? 名称也不全; 能对应 AR 场景的具体操作么? 左右手任务也不一样 ——
         元任务要有一列标识 左手/右手/左右, 要有时空对应关系」
    ⇒ 每条元任务给: 手别 (L/R/BOTH) · 层 · 段数 · 时空窗 (一轮里 t 起→止) · 目标对象 (槽k/孔k/金手指点/侧面点N/下料盘/废料盘)
      · 段级明细 (seq/动作/目标/手别/时长/累计, 可直接对到 AR 场景的具体操作)。
      真源 = tasks.json 的 meta_tasks (TASK-07-AOI: 7 条, 由 ss_meta_task_ar.py 从 392 段归纳);
      没登记 meta_tasks 的任务 ⇒ 用它自己的 steps 派生 (手别从 desc 里的 左臂/右臂 读, 判不出就留空)。
    返回 (items, note, src); items = [dict(id,name,hand,layer,n_seg,t_win,targets,segs,actions)]。
    """
    tk = _task_obj(tid) or {}
    lh = tk.get("long_horizon") or {}
    mts = tk.get("meta_tasks") or []
    if mts:
        items = []
        for i, m in enumerate(mts, 1):
            items.append({"id": m.get("id") or "MT-%02d" % i,
                          "name": m.get("name") or "—",
                          "hand": m.get("hand") or _hand_of(m.get("name")),
                          "layer": m.get("layer") or "—",
                          "n_seg": m.get("segments") or 0,
                          "t_win": m.get("t_win"),
                          "targets": m.get("targets") or [],
                          "actions": m.get("actions") or [],
                          "segs": m.get("segs") or [],
                          # 🧩 2026-10-28: 元任务 → 工艺段 (衔接功能配置的桥, 作者口径见 ss_meta_task_ar.MT_SEG8)
                          "seg8": m.get("seg8") or [],
                          "occ": m.get("occurrences")})
        hs = {"R": sum(1 for x in items if x["hand"] == "R"),
              "L": sum(1 for x in items if x["hand"] == "L"),
              "BOTH": sum(1 for x in items if x["hand"] == "BOTH")}
        note = ("%s 的任务级元任务 %d 条 (右手 %d / 左手 %d / 双手 %d) · 真源 tasks.json(%s.meta_tasks)"
                " · 长程: 目标 %s UPH · 一轮 %s 段 / %s s · %s 种轮模板 · 元任务执行 %s 次/轮"
                % (tid, len(items), hs["R"], hs["L"], hs["BOTH"], tid,
                   lh.get("uph_target") or "—", lh.get("segments_total") or "—",
                   lh.get("round_total_s") or "—", len(lh.get("rounds") or []), lh.get("meta_count") or "—"))
        return items, note, "tasks.json:meta_tasks"
    steps = tk.get("steps") or []
    items = []
    acc = 0.0
    for i, s in enumerate(steps, 1):
        if not isinstance(s, dict):
            items.append({"id": "S%02d" % i, "name": str(s), "hand": "", "layer": "L3",
                          "n_seg": 1, "t_win": None, "targets": [], "actions": [],
                          "segs": [{"seq": i, "label": str(s), "target": "—", "hand": "", "t": None}]})
            continue
        t0 = float(s.get("t") or acc)
        dur = s.get("dur")
        h = _hand_of((s.get("desc") or "") + (s.get("name") or ""))
        items.append({"id": "S%02d" % i, "name": s.get("name") or "—", "hand": h,
                      "layer": s.get("layer") or "L3", "n_seg": 1,
                      "t_win": [round(t0, 2), round(t0 + float(dur or 0), 2)] if dur else None,
                      "targets": [], "actions": [s.get("desc") or ""],
                      "segs": [{"seq": i, "label": s.get("name") or "—", "target": "—", "hand": h,
                                "t": dur, "t_end": round(t0 + float(dur or 0), 2) if dur else None}]})
        acc = t0 + float(dur or 0)
    hs = {"R": sum(1 for x in items if x["hand"] == "R"), "L": sum(1 for x in items if x["hand"] == "L"),
          "BOTH": sum(1 for x in items if x["hand"] == "BOTH")}
    note = ("%s 的任务级元任务 %d 条 (右手 %d / 左手 %d / 双手 %d) · **由 steps 派生** "
            "(该任务在 tasks.json 未登记 meta_tasks; 手别取自 desc 里的 左臂/右臂, 判不出就留空)"
            % (tid, len(items), hs["R"], hs["L"], hs["BOTH"]))
    return items, note, "tasks.json:steps(派生)"


def _n_tasks():
    """真源任务数 (tasks.json) —— 归属口径要用它, 不写死 8。"""
    try:
        return len((_j(TASKS_J, {}) or {}).get("tasks") or [])
    except Exception:                                                           # noqa: BLE001
        return 0


def _owner_text(m):
    """功能级元任务的服务范围 (归属): 全 N 任务共用 / N 任务共用 / 无任务接入。"""
    n = len(m.get("tasks") or [])
    tot = _n_tasks()
    if not n:
        return "— 无任务接入"
    if tot and n >= tot:
        return "全 %d 任务共用" % tot
    return "%d 任务共用" % n


# ══════════════════════════════════════════════════════════════════════════════
# 🎯 当前活跃任务 → 该任务的功能配置 (元任务编排驱动) —— 老倪 2026-10-28
#   「根据元任务的编排, 继续完成 功能配置 模型配置 性能配置; 当前激活的是 任务7, 功能上要将任务7的任务都对应上;
#    在功能配置页面, 要提示 当前的活跃任务, 随即显示当前活跃任务的功能配置」
#   真源 (三份, 都不猜):
#     config/ss_task_binding.json  → active_task / enabled_nodes / applies_segments / segment_node_map
#     config/tasks/tasks.json      → 该任务的 meta_tasks(任务级元任务 7 条) + steps
#     tools/export_meta_doc.build_meta_tasks() → 77 条功能级元任务 (含 tasks 归属/参数/验证)
# ══════════════════════════════════════════════════════════════════════════════

def _active_bind():
    """(tid, 任务对象, 该任务在绑定真源里的条目, 绑定整份) —— 活跃任务只认 active_task, 不猜。"""
    b = _j(BIND_J, {}) or {}
    tid = (b.get("active_task") or "").strip()
    tk = _task_obj(tid) or {}
    bt = next((x for x in (b.get("tasks") or []) if x.get("task_id") == tid), {}) or {}
    return tid, tk, bt, b


def _node_segments(smap):
    """节点 → 所属工艺段 (segment_node_map 是 段→节点, 这里反查)。"""
    idx = {}
    for seg, nodes in (smap or {}).items():
        for n in (nodes or []):
            idx.setdefault(n, []).append(seg)
    return idx


def _task_funcs(tid=None):
    """该任务的功能级元任务 —— 77 条 FN 里 `tasks` 命中它的那些 (TASK-07-AOI 实测 33 条)。

    每条附三样**派生**信息, 全部来自绑定真源, 不猜:
      node    该功能对应的画布节点 (功能清单 node_id)
      enabled 该节点在本任务里是 启用 / 禁用 (enabled_nodes / disabled_nodes)
      segs    该节点落在哪些工艺段 (segment_node_map 反查)
    """
    tid = tid or _active_bind()[0]
    _t, _tk, bt, bd = _active_bind()
    en = set(bt.get("enabled_nodes") or [])
    dis = set(bt.get("disabled_nodes") or [])
    seg_of = _node_segments(bd.get("segment_node_map"))
    out = []
    for m in _meta_tasks():
        if tid not in (m.get("tasks") or []):
            continue
        node = m.get("node_id") or ""
        out.append({"fn": m.get("fn_id"), "name": m.get("name"), "layer": m.get("layer"),
                    "sub": m.get("subsystem"), "node": node,
                    "n_par": m.get("n_params"), "n_spec": m.get("n_specific"),
                    "complete": bool(m.get("complete")), "missing": m.get("missing") or [],
                    "prio": m.get("prio"), "verify": (m.get("verification") or [""])[0],
                    "tasks": m.get("tasks") or [], "n_serv": m.get("n_serv"),
                    "enabled": (node in en) if (en or dis) else None,
                    "disabled": node in dis,
                    "segs": seg_of.get(node) or []})
    return out


def _task_seg_cover(tid=None):
    """工艺段 → 功能 覆盖 (该任务 applies_segments/excluded_segments 逐段算, 缺谁一目了然)。"""
    tid = tid or _active_bind()[0]
    _t, _tk, bt, bd = _active_bind()
    smap = bd.get("segment_node_map") or {}
    en = set(bt.get("enabled_nodes") or [])
    fn_of_node = {}
    for f in _task_funcs(tid):
        fn_of_node.setdefault(f["node"], []).append(f)
    rows = []
    for seg, nodes in smap.items():
        on = [n for n in (nodes or []) if n in en]
        fs = [f for n in (nodes or []) for f in fn_of_node.get(n, [])]
        rows.append({"seg": seg, "n_node": len(nodes or []), "n_on": len(on), "n_fn": len(fs),
                     "n_bad": sum(1 for f in fs if not f["complete"]),
                     "applies": seg in (bt.get("applies_segments") or []),
                     "excluded": seg in (bt.get("excluded_segments") or []),
                     "fns": fs})
    return rows


# ══════════════════════════════════════════════════════════════════════════════
# 功能定义 · 真源装配 (老倪 2026-10-28: 「功能, 应该有 功能名称, 输入, 输出, 描述, 这些信息, 对应着元任务;
#   可以是 1 个功能, 也可以由功能组成子系统。重写功能配置, 每个功能要有 function 这样的逻辑实现」)
#   四个字段各自的真源 (逐条标明来源, 别混):
#     名称/子系统/层/描述 ← zmax_engineering.db: functions(name, system_id, layer, row_name, note_work)
#     输入/输出           ← functions 所属产品特征 → capability_dbc(inputs/outputs)  ← 派生, 粒度=能力接口
#     逻辑实现 function   ← links(kind='对应模块') function→canvas节点  →  links(kind='实现') 节点→library.py:LINE
#                            + functions.params.source/source_symbol (业务逻辑文件/类)
#   校验: 文件存在 + 行号在界内 + 该行附近真是 def/class 才标 ✅ (不靠自报)。
# ══════════════════════════════════════════════════════════════════════════════
ENGR_DB = os.path.join(ROOT, "data", "database", "zmax", "zmax_engineering.db")
CONFIG_META_J = os.path.join(ROOT, "data", "database", "zmax", "config_meta.json")
_FNREG = {}
_CONFIG_META = {}


def _config_meta():
    global _CONFIG_META
    if _CONFIG_META:
        return _CONFIG_META
    try:
        _CONFIG_META = json.load(open(CONFIG_META_J, encoding="utf-8"))
    except Exception:                                                          # noqa: BLE001
        _CONFIG_META = {}
    return _CONFIG_META


FN_IO_SEED_J = os.path.join(ROOT, "tools", "spec", "fn_io_seed.json")
_FNIO = {}


def _fn_io_seed():
    global _FNIO
    if _FNIO:
        return _FNIO
    try:
        _FNIO = json.load(open(FN_IO_SEED_J, encoding="utf-8"))
    except Exception:                                                          # noqa: BLE001
        _FNIO = {}
    return _FNIO


def _eng_db():
    import sqlite3
    con = sqlite3.connect("file:%s?mode=ro" % ENGR_DB, uri=True)
    con.row_factory = sqlite3.Row
    return con


def _fn_registry():
    """一次读出 功能/模块实现/子系统, 供功能配置页用 (只读, 进程内缓存)。"""
    if _FNREG:
        return _FNREG
    try:
        con = _eng_db()
    except Exception:                                                          # noqa: BLE001
        return _FNREG
    try:
        fns = {}
        for r in con.execute("SELECT fn_id,system_id,name,layer,kind,row_name,module_ref,"
                             "params,source,note_work,note_pain,note_state FROM functions"):
            fns[r["fn_id"]] = dict(r)
        mod = {}
        for r in con.execute("SELECT module_name,logic_key,file,line,doc FROM module_code"):
            mod[r["module_name"]] = dict(r)
        fn2mod = {}
        for r in con.execute("SELECT src_id,dst_id FROM links WHERE kind='对应模块'"):
            fn2mod.setdefault(r["src_id"], r["dst_id"])
        subs = {}
        for r in con.execute("SELECT system_id,name,level,role,hardware,kpi FROM subsystems"):
            subs[r["system_id"]] = dict(r)
        # 功能 → 产品特征 → 能力接口 (输入/输出), 与 config_meta.py 同口径
        pf = {}
        for r in con.execute("SELECT src_id,dst_id FROM links WHERE kind='能力引用'"):
            pf.setdefault(r["dst_id"], []).append(r["src_id"])
        caps = {r["bo_id"]: dict(r) for r in
                con.execute("SELECT bo_id,name,inputs,outputs,brief FROM capability_dbc")}
        fn_pf = {}
        for r in con.execute("SELECT src_type,src_id,dst_id FROM links WHERE kind IN ('用到')"):
            pass
        _FNREG.update(fns=fns, mod=mod, fn2mod=fn2mod, subs=subs, caps=caps, pf=pf)
    finally:
        con.close()
    return _FNREG


def _impl_at(path, line):
    """核对: 文件在不在 / 行号在不在界内 / 该行(或往上 12 行)是不是 def/class。返回 (ok, msg)。"""
    if not path:
        return False, "未登记"
    fp = path if os.path.isabs(path) else os.path.join(ROOT, path)
    if not os.path.exists(fp):
        return False, "文件不存在"
    try:
        lines = open(fp, encoding="utf-8", errors="replace").read().splitlines()
    except Exception:                                                          # noqa: BLE001
        return False, "读不了"
    if line:
        if not (1 <= int(line) <= len(lines)):
            return False, "行号越界(%d/%d)" % (int(line), len(lines))
        for k in range(int(line) - 1, max(-1, int(line) - 13), -1):
            t = lines[k].strip()
            if t.startswith(("def ", "class ", "async def ")):
                return True, "%s:%d  %s" % (os.path.relpath(fp, ROOT), k + 1, t.split("(")[0].replace("def ", "def ").strip())
        return True, "%s:%d  (该行非 def/class, 是画布节点注册处)" % (os.path.relpath(fp, ROOT), int(line))
    return True, os.path.relpath(fp, ROOT)


def _fn_detail(fn_id):
    """单个功能的完整定义 (四个字段 + 逻辑实现 + 承载元任务)。"""
    R = _fn_registry()
    f = (R.get("fns") or {}).get(fn_id) or {}
    pj = {}
    try:
        pj = json.loads(f.get("params") or "{}")
    except Exception:                                                          # noqa: BLE001
        pj = {}
    cm0 = (_config_meta().get("functions") or {}).get(fn_id) or {}
    mname = ((R.get("fn2mod") or {}).get(fn_id) or f.get("module_ref") or cm0.get("module_ref") or "")
    mc = (R.get("mod") or {}).get(mname) or {}
    # ── 逻辑实现: ① 业务逻辑 (params.source + source_symbol) ② 画布节点注册 (library.py:LINE)
    impl = []
    src = (pj.get("source") or "").strip()
    sym = (pj.get("source_symbol") or "").strip()
    if src:
        line2 = None
        if sym:
            fp = src if os.path.isabs(src) else os.path.join(ROOT, src)
            if os.path.exists(fp):
                nm = sym.replace("class ", "").replace("def ", "").strip()
                for i, t in enumerate(open(fp, encoding="utf-8", errors="replace"), 1):
                    if t.strip().startswith(("def %s(" % nm, "class %s(" % nm, "class %s:" % nm,
                                             "async def %s(" % nm)):
                        line2 = i
                        break
        ok, msg = _impl_at(src, line2)
        impl.append({"kind": "业务逻辑", "file": src, "line": line2, "symbol": sym, "ok": ok, "msg": msg})
    if mc.get("file"):
        ok, msg = _impl_at(mc.get("file"), mc.get("line"))
        impl.append({"kind": "画布节点注册", "file": mc.get("file"), "line": mc.get("line"),
                     "symbol": mc.get("logic_key") or "", "ok": ok, "msg": msg,
                     "doc": mc.get("doc") or ""})
    # ── 输入/输出: 沿用 config_meta.py 的派生口径 (功能 → 所属产品特征 → 能力接口 inputs/outputs)
    cm = (_config_meta().get("functions") or {}).get(fn_id) or {}
    cfl = cm.get("fields") or {}
    ins = [x for x in (cfl.get("inputs") or []) if x]
    outs = [x for x in (cfl.get("outputs") or []) if x]
    pf_used = list((cm.get("deps") or {}).get("product_features") or [])
    # ── 真源没有 I/O 的: 用作者补写种子 (tools/spec/fn_io_seed.json), 标来源, 不冒充真源
    seed = (_fn_io_seed().get("items") or {}).get(fn_id) or {}
    io_ref = ("派生(参考): 产品特征能力接口 " + " / ".join(pf_used)) if (ins or outs) else ""
    io_src = ""
    if seed and (seed.get("inputs") or seed.get("outputs")):
        ins = list(seed.get("inputs") or [])
        outs = list(seed.get("outputs") or [])
        io_src = "作者整理 · 自该功能 note_work / 模块 desc (tools/spec/fn_io_seed.json)"
    elif ins or outs:
        io_src = io_ref
    desc_auto = f.get("note_work") or f.get("row_name") or ""
    name = f.get("name") or ""
    if not name or name == fn_id:
        name = mname or fn_id
    return {"fn_id": fn_id, "name": name, "system_id": f.get("system_id") or "",
            "layer": f.get("layer") or "", "row_name": f.get("row_name") or "",
            "work": desc_auto, "pain": f.get("note_pain") or "", "state": f.get("note_state") or "",
            "seed_desc": seed.get("desc") or "", "io_from_seed": bool(seed), "io_ref": io_ref,
            "module": mname, "impl": impl,
            "inputs": ins, "outputs": outs, "io_src": io_src,
            "subsystem": ((R.get("subs") or {}).get(f.get("system_id") or "") or {}).get("name") or f.get("system_id") or "",
            "n_impl": sum(1 for i in impl if i["ok"])}


# ══════════════════════════════════════════════════════════════════════════════
# 模型真源 (老倪 2026-10-28: 「继续 模型配置, 如何对应功能配置, 要用实际的模型」)
#   模型侧真源 = models/active_models.json: L2/L3/L4/L5 在役指针 + extra_in_service (多地/原语/LoRA/技能包)
#              + ar:* (AR 场景登记条目, 带 used_by 场景与功能)
#   功能侧 = function_layer_map 的 models 名称 → tools/spec/model_links.json 对齐到条目
#   所有权重/大小/时间/是否存在 全部现场 stat, 不抄不猜。
# ══════════════════════════════════════════════════════════════════════════════
ACTIVE_MODELS_J = os.path.join(ROOT, "models", "active_models.json")
MODEL_LINKS_J = os.path.join(ROOT, "tools", "spec", "model_links.json")
_MODREG = {}


def _model_links():
    try:
        return json.load(open(MODEL_LINKS_J, encoding="utf-8"))
    except Exception:                                                          # noqa: BLE001
        return {"links": {}, "external": {}}


def _models_registry():
    """扁平化 models/active_models.json → {key: entry}; entry 带 path/endpoint/used_by/scene/role/note。"""
    if _MODREG:
        return _MODREG
    try:
        am = json.load(open(ACTIVE_MODELS_J, encoding="utf-8"))
    except Exception:                                                          # noqa: BLE001
        return _MODREG
    ent = {}
    for L in ("L2", "L3", "L4", "L5"):
        e = am.get(L) or {}
        if isinstance(e, dict) and (e.get("path") or e.get("name")):
            ent[L] = dict(e, key=L, layer=L, pointer=True)
    for L, arr in (am.get("extra_in_service") or {}).items():
        if not isinstance(arr, list):
            continue
        for i, e in enumerate(arr):
            if not isinstance(e, dict):
                continue
            k = "%s#%s" % (L, e.get("kind") or ("x%d" % i))
            if k in ent:
                k = "%s#%s%d" % (L, e.get("kind") or "x", i)
            ent[k] = dict(e, key=k, layer=L, pointer=False)
    for k, e in (am.get("extra_in_service") or {}).items():
        if isinstance(e, dict):
            ent[k] = dict(e, key=k, layer=e.get("layer") or "", pointer=False, scene_entry=True)
    for k, e in ((_model_links().get("external") or {}).items()):
        ent[k] = dict(e, key=k, pointer=False, external=True)
    _MODREG.update(ent=ent, raw=am, updated=am.get("updated") or "")
    return _MODREG


def _model_disk(e):
    """→ (ok, 描述, 字节, mtime)。文件/目录/端点/云端 API 四种。"""
    import time as _t
    p = e.get("path") or ""
    if not p:
        ep = e.get("endpoint")
        if isinstance(ep, dict):
            return True, "端点 " + " · ".join("%s=%s" % (k, v) for k, v in ep.items()), 0, 0
        if e.get("external"):
            sec = os.path.join(ROOT, "zmax_data", "secrets", "zmax.env")
            txt = ""
            try:
                txt = open(sec, encoding="utf-8", errors="replace").read()
            except Exception:                                                   # noqa: BLE001
                txt = ""
            ks = e.get("env_key") or ""
            have = bool(ks) and ("%s=" % ks) in txt
            base = ""
            for line in txt.splitlines():
                if (e.get("env_base") or "") and line.strip().startswith((e.get("env_base") or "") + "="):
                    base = line.split("=", 1)[1].strip()
                if (e.get("env_model") or "") and line.strip().startswith((e.get("env_model") or "") + "="):
                    e["_model_name"] = line.split("=", 1)[1].strip()
            return have, ("云端 API · key %s%s" % ("已配" if have else "未配", (" · " + base) if base else "")), 0, 0
        return False, "无路径/端点", 0, 0
    fp = p if os.path.isabs(p) else os.path.join(ROOT, p)
    if not os.path.exists(fp):
        return False, "⛔ 路径不存在", 0, 0
    if os.path.isdir(fp):
        files = [os.path.join(r, f) for r, _, fs in os.walk(fp) for f in fs]
        if not files:
            return True, "✅ 空目录", 0, 0
        sz = sum(os.path.getsize(f) for f in files)
        mt = max(os.path.getmtime(f) for f in files)
        return True, "✅ 目录 %d 文件" % len(files), sz, mt
    return True, "✅ 文件", os.path.getsize(fp), os.path.getmtime(fp)


def _fn_real_models(fn_id):
    """功能 → 实际在役模型条目 (list of dict, 每条带 _ok/_disk/_mb/_mt)。"""
    R = _models_registry()
    ent = R.get("ent") or {}
    L = _model_links()
    out, seen = [], set()
    from zmax_platform_info import function_layer_map as _flm
    row = next((r for r in _flm()["rows"] if r["fn_id"] == fn_id), None)
    names = (row or {}).get("models") or []
    for nm in names:
        for k in (L.get("links") or {}).get(nm, []):
            if k in ent and k not in seen:
                seen.add(k)
                out.append(dict(ent[k], via=nm))
    for k, e in ent.items():                       # 登记条目里直接点名该功能的 (如 ar:L2:aoi → FN-SYS0-40)
        if fn_id in (e.get("used_by") or []) and k not in seen:
            seen.add(k)
            out.append(dict(e, via="used_by"))
    for e in out:
        ok, desc, sz, mt = _model_disk(e)
        e["_ok"], e["_desc"], e["_mb"], e["_mt"] = ok, desc, sz / 1e6, mt
    return out


_MODPARAMS = {}


def _module_params(mod_name):
    """画布节点(模块)在工程库里登记的加载物: model / skill / llm / expert / decoder / source。"""
    if mod_name in _MODPARAMS:
        return _MODPARAMS[mod_name]
    pj = {}
    try:
        con = _eng_db()
        row = con.execute("SELECT params FROM modules WHERE name=?", (mod_name,)).fetchone()
        if row and row[0]:
            pj = json.loads(row[0])
        con.close()
    except Exception:                                                          # noqa: BLE001
        pj = {}
    _MODPARAMS[mod_name] = pj
    return pj


def _file_status(path):
    fp = path if os.path.isabs(path) else os.path.join(ROOT, path)
    if not os.path.exists(fp):
        return False, 0.0, 0
    if os.path.isdir(fp):
        fs = [os.path.join(r, f) for r, _, g in os.walk(fp) for f in g]
        if not fs:
            return True, 0.0, 0
        return True, sum(os.path.getsize(f) for f in fs) / 1e6, max(os.path.getmtime(f) for f in fs)
    return True, os.path.getsize(fp) / 1e6, os.path.getmtime(fp)


def _fn_load_items(fn_id):
    """功能 → 该功能**实际加载的东西** (权重 / 技能库 / LLM / 端点 / 规则代码), 逐条带依据与现场 stat。

    依据优先级 (先具体后笼统, 谁登记得细用谁):
      a. 模块 params: model (权重名) / skill (技能库 json) / llm / expert+decoder
      b. models/active_models.json 里 used_by 点名该功能的条目 (场景登记, 如 AR 的 AOI 端点)
      c. 兜底: function_layer_map 的层模型名 (粗粒度, 明确标「层模型(粗)」)
    路径/大小/时间/是否存在 = 现场 stat。
    """
    from zmax_platform_info import function_layer_map as _flm
    R = _fn_registry()
    ent = (_models_registry().get("ent") or {})
    L = _model_links()
    mod = (R.get("fn2mod") or {}).get(fn_id) or ""
    pj = _module_params(mod) if mod else {}
    out, seen = [], set()

    def _push(name, kind, entry=None, path=None, endpoint=None, basis="", note=""):
        k = "%s|%s" % (name, path or endpoint or "")
        if k in seen:
            return
        seen.add(k)
        ok, mb, mt = _file_status(path) if path else (None, 0.0, 0)
        if entry is not None:
            ok2, desc, sz, mt2 = _model_disk(entry)
            ok = ok2
            mb = (sz or 0) / 1e6
            mt = mt2 or mt
            path = path or entry.get("path") or ""
            endpoint = endpoint or entry.get("endpoint")
        out.append({"name": name, "kind": kind, "path": path or "", "endpoint": endpoint,
                    "ok": ok, "mb": mb, "mt": mt, "basis": basis, "note": note})

    mdl = str(pj.get("model") or "").strip()
    if mdl:
        keys = (L.get("model_names") or {}).get(mdl) or []
        if not keys:
            for _k, _v in (L.get("model_names") or {}).items():
                if mdl.startswith(_k) or _k in mdl:
                    keys = _v
                    break
        if keys:
            for kk in keys:
                if kk in ent:
                    _push(ent[kk].get("name") or mdl, ent[kk].get("kind") or "权重", entry=ent[kk],
                          basis="模块登记 model=%s" % mdl)
        else:
            _push(mdl, "权重/模型名", basis="模块登记 model=%s (未登记权重路径)" % mdl)
    sk = pj.get("skill")
    if isinstance(sk, str) and ("/" in sk or sk.endswith(".json")):
        _push(os.path.basename(sk), "技能库", path=sk, basis="模块登记 skill")
    llm = str(pj.get("llm") or "").strip()
    if llm:
        keys = (L.get("model_names") or {}).get(llm.split(" ")[0]) or []
        if not keys:
            for _k, _v in (L.get("model_names") or {}).items():
                if _k in llm:
                    keys = _v
                    break
        hit = False
        for kk in keys:
            if kk in ent:
                _push(ent[kk].get("name") or llm, "LLM", entry=ent[kk], basis="模块登记 llm=%s" % llm[:24])
                hit = True
        if not hit:
            _push(llm, "LLM (可插拔)", basis="模块登记 llm")
    if str(pj.get("expert") or "").lower() == "true" or pj.get("decoder"):
        e4 = ent.get("L4")
        if e4:
            _push("INTACT-JEPA 意图-动作 (expert=%s · decoder=%s)" % (pj.get("expert"), pj.get("decoder") or "—"),
                  "权重", entry=e4, basis="模块登记 expert/decoder")
    for kk, e in ent.items():
        if fn_id in (e.get("used_by") or []):
            _push(e.get("name") or kk, e.get("kind") or "登记条目", entry=e, basis="场景登记 used_by=%s" % fn_id)
    _ov = (L.get("fn_overrides") or {}).get(fn_id) or {}
    for kk in (_ov.get("keys") or []):
        if kk in ent:
            _push(ent[kk].get("name") or kk, ent[kk].get("kind") or "层模型",
                  entry=ent[kk], basis="层模型对齐(见 model_links.json fn_overrides)")
    if not out:
        # 没有权重/技能库/LLM/端点登记 ⇒ 这个功能就是**代码/规则/数据源**, 不硬塞层模型
        d = {}
        try:
            d = _fn_detail(fn_id) or {}
        except Exception:                                                       # noqa: BLE001
            d = {}
        impl = next((i for i in (d.get("impl") or []) if i.get("ok")), None)
        if impl:
            _push("无权重 · 代码/规则实现", "规则/数据源", path=(impl.get("file") or ""),
                  basis="工程库未登记权重; 逻辑实现 %s" % (impl.get("msg") or "")[:60])
            out[-1]["ok"] = True
            out[-1]["_line"] = impl.get("msg") or ""
        else:
            _push("⚠ 未登记加载物", "未知", basis="工程库/场景登记都没写")
    return out


def _subs_list():
    """子系统清单 (老倪: 「可以是 1 个功能, 也可以由功能组成子系统」)。"""
    R = _fn_registry()
    tid = _active_bind()[0]
    funcs = _task_funcs(tid)
    out = []
    by_name = {(v.get("name") or k): k for k, v in (R.get("subs") or {}).items()}
    for sub_name in sorted({(f.get("sub") or "") for f in funcs}):
        mem = [f for f in funcs if (f.get("sub") or "") == sub_name]
        if not mem:
            continue
        sid = by_name.get(sub_name) or sub_name
        s = (R.get("subs") or {}).get(sid) or {"name": sub_name}
        out.append({"system_id": sid, "name": s.get("name") or sid, "level": s.get("level") or "",
                    "role": s.get("role") or "", "kpi": s.get("kpi") or "", "fns": mem, "n": len(mem)})
    return sorted(out, key=lambda x: (x["system_id"] != "sys0", x["system_id"]))


def _mt_funcs(tid=None):
    """元任务 → 承载功能 (老倪 2026-10-28: 「功能配置, 怎么和元任务连接呢? 看到一个列, 应该是功能」)。

    链路: 元任务 --(按动作性质)--> 工艺段(seg8) --(segment_node_map: 段→节点)--> 功能(node_id)。
    这是两边**唯一**的公共轴 (功能带 node_id, 元任务带动作段, 两者没有直接外键), 所以不做关键词猜配。
    返回每条 [dict(...任务级元任务字段..., "seg8": [...], "fns": [功能...], "n_fn": N)]。
    """
    tid = tid or _active_bind()[0]
    funcs = _task_funcs(tid)
    out = []
    for m in _task_level_meta(tid)[0]:
        seg8 = m.get("seg8") or []
        fs = [f for f in funcs if set(f["segs"]) & set(seg8)]
        out.append(dict(m, seg8=seg8, fns=fs, n_fn=len(fs)))
    return out


def _orders_list():
    """工单实例真源: config/orders/BS_*.json (Build Sheet) —— 读不到的文件跳过, 不编数。"""
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


def _steps_cell(t):
    """任务表「工艺步骤」单元格 —— 只放**一眼看完**的短标签, 完整序列一字不少进 tooltip。

    老倪 2026-10-15: 「任务配置的窗口, 太矮了, 看不到任务」的真根因之一就在这里 ——
    这一列原来把 8 段工艺全串成一行长文本 (`.join(" → ")`), 而它是**唯一的 Stretch 列** ⇒
    单元格宽度不够时文字反复折行, 每一行任务被撑到 **133~177px**; 离屏实测 7 行合计 **865px**
    (表头再加 41) ⇒ 任务表要 ~912px 才装得下, 矮窗口里自然只看得到 1 行。
    改成「前两段 → … (共 N 段)」后行高回到 2 行文本 (~67px), 7 行 ~470px 一屏可见。
    口径: 这不是静默截断 —— 省略处有显式 `… (共 N 段)` 标记, 完整序列在 tooltip 里。
    """
    names = [str(s.get("name") or "") for s in (t.get("steps") or [])]
    if not names:
        return "—"
    if len(names) <= 2:
        return " → ".join(names)
    return "%s → %s → … (共 %d 段)" % (names[0], names[1], len(names))


def _steps_tip(t):
    """工艺步骤列的 tooltip: 完整序列 (与 config/tasks/tasks.json 真源逐条一致)。"""
    names = [str(s.get("name") or "") for s in (t.get("steps") or [])]
    if not names:
        return "工艺步骤: (该任务在真源里没有 steps)"
    return ("工艺步骤 · 完整序列 (共 %d 段)\n" % len(names)
            + "\n".join("  %2d. %s" % (i + 1, n) for i, n in enumerate(names))
            + "\n真源: config/tasks/tasks.json (由 tools/task_build.py 生成)")


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


def _scrollable(w, theme=None):
    """把一页包进**可滚动**容器 —— 老倪 2026-10-15: 「显示区太小, 且不能用鼠标滚动调整, 看不到显示内容」。

    为什么必须这样: 页里的表/卡片都按"不许挤/不许截断"给了最小高度 (工程配置那张表 510px),
    QTabWidget 的最小高度 = 各页最大值 ⇒ 上方工作区把竖直空间**吃光**, 底部信息窗被压到最小值 98px,
    而且拖也拖不大 (没有余量可分), 用户就"看不到显示内容"。
    包一层 QScrollArea 后: 页面可以压到任意高度 (内容不够看就滚鼠标/滚轮), 竖直空间能真正分给信息窗。
    """
    sa = QScrollArea()
    sa.setWidgetResizable(True)                     # 视口变大 → 页面跟着变宽/变高
    sa.setFrameShape(QFrame.NoFrame)
    sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    sa.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    sa.setWidget(w)
    if theme:
        sa.setStyleSheet("QScrollArea{background:transparent;border:none;}")
    return sa


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
    # 🐛 2026-10-17: 原来这里是**裸声明** (background:...;padding:...;) 没有 QPushButton{} 包起来。
    #    下面 3581 行又在同一串后面拼 "QPushButton:checked{...}" ⇒ 裸声明后面直接跟选择器,
    #    Qt 解析失败, 每次 repolish 都刷 "Could not parse stylesheet of object QPushButton(...)"
    #    (实测 3 个按钮 功能配置/性能配置/模型配置, 5s 内 18 条)。包成规则块后拼接合法。
    b.setStyleSheet(f"QPushButton{{background:{theme['C_CARD']};color:{theme['C_WHITE']};"
                    f"border:1px solid {theme['C_BORDER']};border-radius:4px;padding:5px 12px;}}")
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


def _system_version():
    """全系统总版本号 (全系统一份, 三档共用) —— 单源: tools/gui/update_checker.CURRENT_VERSION。

    老倪 2026-10-21: 「A B C 只是产品的配置标识, 版本号全系统统一 … 都与系统总版本号
    保持同步更新」⇒ 界面**不手抄**版本号, 直接读版本真源; 读不到就如实写"取不到", 不退回旧号。
    """
    for _m in ("update_checker",):
        try:
            _mod = __import__(_m)
            v = str(getattr(_mod, "CURRENT_VERSION", "") or "").strip()
            if v:
                return v if v.lower().startswith("v") else ("v" + v)
        except Exception:                                                       # noqa: BLE001
            pass
    return "取不到"


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
        # 🎨 2026-10-21 产品档卡片底行用: 系统总版本 (全系统统一) + 定位 (开发版/调试版/量产版)
        "system_version": _system_version(),
        "segments": {k: ((v or {}).get("version_segment") or "") for k, v in prods.items()},
        "roles": {k: str((((v or {}).get("dev_profile") or {}).get("role") or "")).split("·")[0].strip()
                  for k, v in prods.items()},
        # 🖥 运行时域 (A=本地 · B=VSCode标定 · C=Intel 端侧量产全模型), 全部读真源, 界面不推断
        "runtime": dict(p.get("runtime") or {}),
        "runtimes": {k: dict((v or {}).get("runtime") or {}) for k, v in prods.items()},
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


# 🗑 2026-10-21 老倪: 「产品配置 本页真源: 当前 550B · 真源改于 10-19 15:36 · 三档 550A 原创版 / 550B 标定版 /
#   550C 量产版」这句话删掉 —— 只删**页顶阵图条那句** (产品页本身就是选三档的地方, 再念一遍当前档+三档名单是重复)。
#   数据仍在 _star_facts()["prod"]: 左树 hover tooltip / 底部信息窗 / 判据 ⑧ 照旧读得到, "真源改于" 这条证据不丢。
BANNER_FACT_HIDDEN = ("prod",)


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
    except Exception as e:                                                      # noqa: BLE001
        for _k in ("func", "model", "perf"):
            f.setdefault(_k, "取不到 (%s)" % type(e).__name__)
    # 6 · 开阳 工程配置 (2026-10-19: 由「工单配置」改为「工程配置·定落地」)
    #   真源三件: 特征库工程域 (参数注册表) · 工程-模型匹配 (九类站点能力) · AR 场景示教点位
    try:
        _cs = (_j(MCD_J, {}) or {}).get("CHARACTERISTIC", [])
        _eng = [c for c in _cs if c.get("domain") == "工程配置"]
        _mt = _j(MATCH_J, {}) or {}
        f["eng"] = "工程域 %d/%d 就绪 · 工程-模型匹配 %d 模型 · 真源改于 %s" % (
            sum(1 for c in _eng if c.get("ready")), len(_eng),
            len(_mt.get("MODELS", [])), _mt_str(MCD_J))
    except Exception as e:                                                      # noqa: BLE001
        f["eng"] = "取不到 (%s)" % type(e).__name__
    # 7 · 瑶光 文档配置 (2026-10-19: 工单 / 成本报价 / 商业模式 都收进这一阵)
    try:
        f["doc"] = "文档 %d/3 就绪 (SOR / 立项 / 合作) · 工单 %d 个 · 含 成本报价 + 商业模式" % (
            sum(1 for m in (_doc_mark(k) for k in ("sor", "project", "agreement")) if m == "✅"),
            len(_orders_list()))
    except Exception as e:                                                      # noqa: BLE001
        f["doc"] = "取不到 (%s)" % type(e).__name__
    f["__all__"] = " · ".join("%s %s" % (_ss.BY_KEY[k]["star"], f.get(k, "").split(" · ")[0])
                              for k in ("prod", "task", "func", "model", "perf", "eng", "doc"))
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


class _ProductCard(QRadioButton):
    """产品档位卡: 全部自绘 (渐变底 + 外辉光 + 编号 + 大号档名 + 定位标签 + ✓当前), 单选语义仍是 QRadioButton。

    老倪 2026-10-21: 「现在只是一个小白点来选择配置, 不好看 —— 你来增强设计 … 要明显, 好看一些」
      第 2 轮: 「550A 550B 550C 这几个数字太大了, 调小一些; 颜色太高调亮丽了, 对比度太强了, 内敛一些;
              这些字没有显示完整, 被遮挡了, 你要适配调整」
      ⇒ 档名 21pt → 16pt, 卡片 240×116 → 252×104 (字变小、卡变宽 ⇒ 一行排得下, 不再挤/遮);
        主色降到低饱和 (muted indigo/teal/green), 选中卡不再是"亮卡", 改成**深色卡 + 素白字**,
        只靠 1.8px 冷光描边 + 深色底上的浅色「✓ 当前」小标区分; 未选卡更暗一档。
    **判据不受影响**: 仍是 QRadioButton 子类, text() = 真源 products.<id>.name, isChecked()/setChecked() 照旧。
    ⚠ 版式常量 (W/H/BAND_*/PILL_*) 是判据 verify_product_card_ui 的唯一来源 —— 改这里, 判据跟着变, 别在两处抄数字。
    """

    W, H = 252, 104
    PAD_L, PAD_R = 14, 13
    BAND_CODE = (7, 22)          # 相对卡片内框 r.top() 的 y0/y1 (编号行)
    BAND_BIG = (26, 60)          # 大号档名 + 后缀
    BAND_SUB = (26, 8)           # 相对 r.bottom() 的 y0/y1 (底行: 版本号 · 定位)
    PILL_W, PILL_H = 62, 19
    SUB_PT, CODE_PT, BIG_PT, SMALL_PT = 9, 8, 16, 9

    def __init__(self, pid, code, accent, glow, parent=None):
        super().__init__(parent)
        self._pid, self._code = str(pid), str(code)
        self._accent, self._glow = QColor(accent), QColor(glow)
        self._hover = False
        self._sub = ""
        self.setText(self._pid)             # 真名由 _refresh_product_view 回填 (判据与真源 name 比对)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(self.W, self.H)
        self.setMaximumHeight(self.H)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.toggled.connect(lambda *_: self.update())
        self.setToolTip("%s · %s\n点这张卡 = 切成这一档 (写回真源 active_product)" % (code, pid))

    # ── 外部接口 (与 QRadioButton 兼容) ──
    def setText(self, t):                   # 名字变了要重画
        super().setText(str(t))
        self.update()

    def set_sub(self, text):
        """底行副标题: 版本段 + 定位 (由真源回读, 界面不自算)。"""
        self._sub = str(text or "")
        self.setToolTip("%s · %s\n%s\n点这张卡 = 切成这一档 (写回真源 active_product)"
                        % (self._code, super().text(), self._sub))
        self.update()

    def sizeHint(self):
        return QSize(self.W, self.H)

    def enterEvent(self, ev):
        self._hover = True
        self.update()
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._hover = False
        self.update()
        super().leaveEvent(ev)

    def mouseMoveEvent(self, ev):            # 只读选择, 不要拖拽选中
        ev.accept()

    def _full_line(self):
        return "%s %s (%s)" % (self._code, super().text(), self._sub) if self._sub \
            else "%s %s" % (self._code, super().text())

    def _copy(self):
        try:
            QApplication.clipboard().setText(self._full_line())
        except Exception:                                                   # noqa: BLE001
            pass

    def _menu(self, pos):
        m = QMenu(self)
        m.addAction("📋 复制档位 (%s)" % self._code).triggered.connect(self._copy)
        m.exec_(self.mapToGlobal(pos))

    def mouseDoubleClickEvent(self, ev):
        self._copy()
        ev.accept()

    # ── 绘制 ──
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        on = self.isChecked()
        a, gl = self._accent, self._glow
        r = QRectF(5.0, 5.0, self.width() - 10.0, self.height() - 10.0)
        rad = 13.0
        ink = QColor(8, 25, 30)          # 选中卡上的深墨字 (亮底 ⇒ 暗字, 对比度 ~8:1)
        _pl = self.PAD_L
        _pr = self.PAD_R
        _right = r.right() - _pr

        # ① 描边冷光 (选中才有; 内敛: 只两圈很淡的光, 不炸眼)
        if on:
            for _w, _al in ((4.5, 20), (2.8, 42)):
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QColor(gl.red(), gl.green(), gl.blue(), _al), _w))
                p.drawRoundedRect(r.adjusted(1.0, 1.0, -1.0, -1.0), rad, rad)

        # ② 底: 选中 = 低饱和深色卡 (主色压暗, 配素白字); 未选 = 更暗一档 —— 靠"描边+小标"区分, 不靠刺眼亮度
        #    2026-10-21 复审: 选中卡仍是画面里最亮的块 (中位亮度 82 vs 42/34) ⇒ 再压暗一档 (~55)
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        if on:
            g.setColorAt(0.00, QColor(a).darker(175))
            g.setColorAt(0.55, QColor(a).darker(232))
            g.setColorAt(1.00, QColor(a).darker(268))
        else:
            base = QColor(a).darker(455 if not self._hover else 390)
            g.setColorAt(0.00, QColor(base).lighter(155 if self._hover else 140))
            g.setColorAt(1.00, base)
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(r, rad, rad)

        # ②b 顶部高光 (1px 内描边, 做出卡片厚度)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 40 if on else 16), 1.0))
        p.drawLine(QPointF(r.left() + rad, r.top() + 1.4), QPointF(r.right() - rad, r.top() + 1.4))

        # ③ 未选卡右上角一点点主色微光 (选中卡靠描边就够, 不再叠光)
        if not on:
            rg = QRadialGradient(QPointF(r.right() - 24.0, r.top() + 16.0), 88.0)
            rg.setColorAt(0.0, QColor(gl.red(), gl.green(), gl.blue(), 32))
            rg.setColorAt(1.0, QColor(gl.red(), gl.green(), gl.blue(), 0))
            p.setBrush(rg)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(r, rad, rad)

        # ④ 描边 (选中: 1.8px 冷光; 未选: 主色 35%)
        p.setBrush(Qt.NoBrush)
        if on:
            p.setPen(QPen(QColor(gl.red(), gl.green(), gl.blue(), 205), 1.8))
        else:
            _al = 120 if self._hover else 85
            p.setPen(QPen(QColor(a.red(), a.green(), a.blue(), _al), 1.2))
        p.drawRoundedRect(r, rad, rad)

        # ⑤ 顶行: 编号 + (选中) 浅色「✓ 当前」小标 (深色卡上的浅标, 不刺眼)
        p.setFont(QFont("Consolas", self.CODE_PT, QFont.Bold))
        p.setPen(QColor(226, 236, 241, 228) if on else QColor(gl.red(), gl.green(), gl.blue(), 176))
        _c0, _c1 = self.BAND_CODE
        p.drawText(QRectF(r.left() + _pl, r.top() + _c0, 120, _c1 - _c0),
                   int(Qt.AlignLeft | Qt.AlignVCenter), self._code)
        if on:
            pill = QRectF(_right - self.PILL_W, r.top() + _c0 - 1, self.PILL_W, self.PILL_H)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(gl.red(), gl.green(), gl.blue(), 215))
            p.drawRoundedRect(pill, self.PILL_H / 2.0, self.PILL_H / 2.0)
            p.setPen(ink)
            p.setFont(QFont("Consolas", 8, QFont.Bold))
            p.drawText(pill, int(Qt.AlignCenter), "✓ 当前")

        # ⑥ 中间: 大号档名 + 中文后缀 (用 text() 拆: "550A 原创版")
        nm = (super().text() or self._pid).strip()
        head, _, tail = nm.partition(" ")
        head = head or self._pid
        f_big = QFont("Consolas", self.BIG_PT, QFont.Bold)
        p.setFont(f_big)
        _bw = QFontMetrics(f_big).width(head)
        _b0, _b1 = self.BAND_BIG
        p.setPen(QColor(236, 243, 246) if on else QColor(196, 210, 216))
        p.drawText(QRectF(r.left() + _pl, r.top() + _b0, _bw + 4, _b1 - _b0),
                   int(Qt.AlignLeft | Qt.AlignVCenter), head)
        if tail:
            f_sm = QFont("Consolas", self.SMALL_PT)
            f_sm.setFamily(f_big.family())
            p.setFont(f_sm)
            p.setPen(QColor(gl.red(), gl.green(), gl.blue(), 215 if on else 150))
            p.drawText(QRectF(r.left() + _pl + 4 + _bw, r.top() + _b0 + 3, r.width() - (_bw + 30), _b1 - _b0),
                       int(Qt.AlignLeft | Qt.AlignVCenter), tail)

        # ⑦ 底行: 版本号 + 定位 (全系统统一版本 · 9pt)
        if self._sub:
            p.setFont(QFont("Consolas", self.SUB_PT))
            _s0, _s1 = self.BAND_SUB
            p.setPen(QColor(203, 218, 224, 220) if on else QColor(172, 190, 198, 165))
            p.drawText(QRectF(r.left() + _pl, r.bottom() - _s0, r.width() - (_pl + _pr), _s0 - _s1),
                       int(Qt.AlignLeft | Qt.AlignVCenter), self._sub)

        # ⑧ 键盘焦点: 细虚线框
        if self.hasFocus():
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(255, 255, 255, 150), 1.0, Qt.DashLine))
            p.drawRoundedRect(r.adjusted(3.0, 3.0, -3.0, -3.0), rad - 3, rad - 3)
        p.end()


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


def _src_check(src):
    """现场核对真源引用: path:line / path#key#key / path —— 存在且行号在界内/键取得到才算 ✅"""
    if not src:
        return "⛔ 无真源"
    pth = src.split("#")[0].split(" (")[0].strip()
    line = None
    if ":" in pth and not pth.endswith(":"):
        head, _, tail = pth.rpartition(":")
        if tail.isdigit():
            pth, line = head, int(tail)
    fp = pth if os.path.isabs(pth) else os.path.join(ROOT, pth)
    if not os.path.exists(fp):
        return "⛔ 文件不存在: %s" % pth
    if line:
        try:
            n = len(open(fp, encoding="utf-8", errors="replace").read().splitlines())
        except Exception:                                                       # noqa: BLE001
            n = 0
        if n and line > n:
            return "⛔ 行号越界 %d/%d" % (line, n)
        return "✅ %s" % src
    if "#" in src:
        key = src.split("#", 1)[1]
        try:
            j = json.load(open(fp, encoding="utf-8"))
            cur = j
            for part in key.split("#"):
                cur = cur[part]
            return "✅ %s" % src
        except Exception:                                                       # noqa: BLE001
            return "⚠ 键取不到: %s" % src
    return "✅ %s" % src

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
        # 📋 2026-10-19 老倪「所有文字都可以被选中，复制」: 树/表格不是 QLabel, 没法框选 ⇒ 给 Ctrl+C + 右键复制
        self._install_copy_shortcut()
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
        # 🎯 2026-10-17 老倪二次反馈「左侧面栏还是宽」——真因 (真屏实测 192DPI):
        #   最长条目「⛔ 7. 文档配置 · 瑶光」= 246px ⇒ 内容需求 302px; 而记忆里存着 366px
        #   (旧逻辑 max(need, saved) 也吃它) ⇒ 打开就 366。现在:
        #   ① 记忆宽度**只允许更窄**(< 内容需求才用), 不许把栏开得比内容还宽
        #   ② 最小宽度放到 170px, 想拖窄就能拖窄 (字被省略号截, 全文仍在条目 tooltip)
        #   ③ 一个数就能压死: 环境变量 ZMAX_CFG_TREE_W=240 (或 QSettings 的
        #      config_center/tree_width_pin), 见 _tree_pin()/_tree_open_width()
        self.tree.setMinimumWidth(min(self._tree_need, 120))
        self.tree.setToolTip("左侧栏宽度: 可拖分隔条 (记住); 拖窄后条目用省略号, 全文在同一条目的 tooltip")
        sp.setSizes([self._tree_open_width(), 1000])
        sp.setChildrenCollapsible(False)          # 不许把左栏拖成 0 宽(会看不见)
        sp.setHandleWidth(8)                      # 原来 4px 太细, 鼠标不好抓
        self.splitter = sp
        sp.splitterMoved.connect(self._on_tree_split_moved)
        QTimer.singleShot(0, self._apply_tree_width)      # 布局完成后按"记过的宽度"或需求宽度落定

        # ── 底部信息窗 (点了必出结果) ──────────────────────────────────────────────
        # 2026-10-15 老倪: 「显示区太小, 且不能用鼠标拖动调整大小, 要可以隐藏; 选择相应的配置面时信息没有对应上」
        #   ⇒ ① 改成**竖直 QSplitter**(工作区 / 信息窗): 分隔条 8px 可拖, 拖过之后不再被自动覆盖;
        #     ② 头部一行按钮: 「↕ 自适应高度」「📋 复制」「▾ 收起/▴ 展开」(可隐藏);
        #     ③ 内容随**当前配置面**自动对应 (_sync_out_for/_page_out_text, 真源现算)。
        self.out = QTextEdit()
        self.out.setReadOnly(True)
        self.out.setMinimumHeight(56)             # 最小值给小 ⇒ 能拖到很矮; 上限交给分隔条
        self.out.setFont(QFont("Consolas", 9))
        self.out.setStyleSheet(f"background:{th['C_BG2']};color:{th['C_WHITE']};"
                               f"border:1px solid {th['C_BORDER']};")
        self.out.setPlainText(_run("overview") + _points_block())   # 首屏: 总览 + 示教点位(可复制)
        self._out_on = True                       # 显式记录显示状态 (离屏下 isVisible() 恒 False, 不可当判据)
        self._out_user_sized = False              # 用户拖过分隔条后, 不再自动改高度

        self.out_hint = QLabel("📍 信息窗 — 内容随「当前配置面」自动对应 · 拖上方分隔条调高度 · 点右侧「收起」可隐藏")
        self.out_hint.setWordWrap(True)
        self.out_hint.setFont(QFont("Consolas", 9))
        self.out_hint.setStyleSheet(f"color:{th['C_GRAY']};background:transparent;")
        self.b_out_fit = _btn("↕ 自适应高度", th)
        self.b_out_fit.setToolTip("按当前内容重给一次高度 (之后你拖过的高度不会再被覆盖)")
        self.b_out_fit.clicked.connect(self._fit_out_clicked)
        self.b_out_cp = _btn("📋 复制", th)
        self.b_out_cp.setToolTip("把信息窗内容整段复制到剪贴板")
        self.b_out_cp.clicked.connect(lambda: QApplication.clipboard().setText(self.out.toPlainText()))
        self.b_out = _btn("▾ 收起信息窗", th)
        self.b_out.setToolTip("隐藏 / 展开底部信息窗")
        self.b_out.clicked.connect(self._toggle_out)
        _oh = QHBoxLayout()
        _oh.setContentsMargins(0, 0, 0, 0)
        _oh.addWidget(self.out_hint, 1)
        for _b in (self.b_out_fit, self.b_out_cp, self.b_out):
            _oh.addWidget(_b)
        self.out_box = QWidget()
        _ov = QVBoxLayout(self.out_box)
        _ov.setContentsMargins(0, 2, 0, 0)
        _ov.setSpacing(2)
        _ov.addLayout(_oh)
        _ov.addWidget(self.out, 1)

        self.vsplit = QSplitter(Qt.Vertical)
        self.vsplit.addWidget(sp)
        self.vsplit.addWidget(self.out_box)
        self.vsplit.setHandleWidth(9)             # 分隔条加粗: 鼠标好抓
        self.vsplit.setChildrenCollapsible(False)
        self.vsplit.splitterMoved.connect(self._on_vsplit_moved)
        root.addWidget(self.vsplit, 1)
        self.setLayout(root)
        self._sync_out_for()
        QTimer.singleShot(0, self._fit_out)      # 首次布局完成后给一次合适高度 (之后以拖动为准)

        # 📋 2026-10-19 老倪: 「配置中心…应该所有文字都可以被选中, 复制。你全都改一下」
        #   真因: QLabel 默认 NoTextInteraction ⇒ 文字只能看不能框选 (例如「选一个产品 = 原子写回真源 …」那行)。
        #   做法两段: ① 建页后全量扫一遍, 现存 QLabel 全开「鼠标+键盘可选中」
        #             ② 装 app 级 eventFilter —— 之后动态新建的 QLabel (刷新/重读真源/换页加的行) 在 polish 时自动带上,
        #                不用逐个改; 独立窗口 (simulink「🗂 配置中心」) 复用同一个页面类, 一并生效。
        self._install_text_copy_all()
        self._enable_text_copy(self)

    # ── 📋 全页文字可选中 / 可复制 (2026-10-19 老倪: 「应该所有文字都可以被选中，复制」) ──
    def _enable_text_copy(self, root):
        """root 下所有 QLabel 变成可用鼠标/键盘选中 (只做 OR, 不动已有的链接/其它 flags)。"""
        n = 0
        for lb in root.findChildren(QLabel):
            try:
                _f = lb.textInteractionFlags()
                _want = _f | Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
                if _want == _f:
                    continue
                lb.setTextInteractionFlags(_want)
                lb.setCursor(Qt.IBeamCursor)          # 光标变 I 形 ⇒ 一眼看出「这里能选」
                n += 1
            except Exception:                                                   # noqa: BLE001
                pass
        return n

    def _install_text_copy_all(self):
        """app 级 eventFilter (幂等): 页面里**后建**的 QLabel 在 polish 时也自动可选中。"""
        try:
            app = QApplication.instance()
            if app is not None and not getattr(self, "_copy_filter_on", False):
                app.installEventFilter(self)
                self._copy_filter_on = True
        except Exception:                                                       # noqa: BLE001
            pass

    def eventFilter(self, obj, ev):
        """只认自己的子孙 QLabel 的 polish 事件 (别的控件/别的事件原样放过)。"""
        try:
            if ev.type() == QEvent.Polish and isinstance(obj, QLabel) and self.isAncestorOf(obj):
                _f = obj.textInteractionFlags()
                _want = _f | Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
                if _want != _f:
                    obj.setTextInteractionFlags(_want)
                    obj.setCursor(Qt.IBeamCursor)
        except Exception:                                                       # noqa: BLE001
            pass
        return super().eventFilter(obj, ev)

    # ── 📋 树/表格文字复制 (QLabel 能框选, 树条目/表格单元格不能 ⇒ Ctrl+C + 右键) ──
    def _install_copy_shortcut(self):
        """Ctrl+C: 焦点在树/表格时复制其文字; 焦点在文本编辑框时**照旧走它自己**的复制。"""
        try:
            self._copy_sc = QShortcut(QKeySequence.Copy, self)
            self._copy_sc.setContext(Qt.WidgetWithChildrenShortcut)
            self._copy_sc.activated.connect(self._copy_focus_text)
        except Exception:                                                       # noqa: BLE001
            self._copy_sc = None
        try:
            self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
            self.tree.customContextMenuRequested.connect(self._copy_menu)
        except Exception:                                                       # noqa: BLE001
            pass

    @staticmethod
    def _item_text(it):
        """条目全文: 各列用 \\t 连 (左栏是单列; 多列时一次拷全)。"""
        if it is None:
            return ""
        cols = []
        try:
            for c in range(it.columnCount()):
                t = it.text(c) or ""
                if c == 0:
                    t = t.replace("⛔ ", "").replace("✅ ", "")   # 去掉判态标记, 拷出来是干净名字
                cols.append(t)
        except Exception:                                                       # noqa: BLE001
            return it.text(0) or ""
        return "\t".join(cols).strip()

    def _tree_all_text(self):
        lines = []
        try:
            for i in range(self.tree.topLevelItemCount()):
                it = self.tree.topLevelItem(i)
                lines.append(self._item_text(it))
                for j in range(it.childCount()):
                    lines.append("  " + self._item_text(it.child(j)))
        except Exception:                                                       # noqa: BLE001
            pass
        return "\n".join(x for x in lines if x)

    def _table_sel_text(self, tbl):
        """表格选中单元格 → TSV (与 Excel 一致), 空选区 = 当前行。"""
        try:
            _rows = sorted({i.row() for i in tbl.selectedItems()})
            _cols = sorted({i.column() for i in tbl.selectedItems()})
            if not _rows:
                _rows = [tbl.currentRow()]
                _cols = list(range(tbl.columnCount()))
            out = []
            for r in _rows:
                cells = []
                for c in _cols:
                    _it = tbl.item(r, c)
                    cells.append((_it.text() if _it else "") or "")
                out.append("\t".join(cells))
            return "\n".join(out)
        except Exception:                                                       # noqa: BLE001
            return ""

    def _copy_focus_text(self):
        """Ctrl+C 落点: 树 → 条目; 表 → 选中单元格; 文本编辑框 → 它自己的 copy(); 标签 → 选中文字。"""
        w = QApplication.focusWidget()
        txt = ""
        try:
            if isinstance(w, QTextEdit):
                w.copy()
                return ""
            if isinstance(w, QLineEdit):
                w.copy()
                return ""
            if isinstance(w, QTreeWidget):
                txt = self._item_text(w.currentItem())
            elif isinstance(w, QTableWidget):
                txt = self._table_sel_text(w)
            elif isinstance(w, QLabel):
                txt = w.selectedText() or w.text()
        except Exception:                                                       # noqa: BLE001
            txt = ""
        if txt:
            QApplication.clipboard().setText(txt)
        return txt

    def _copy_menu(self, pos):
        """左树右键: 复制条目文字 / 复制全部条目 (省略号截断的条目也能拷到全文)。"""
        try:
            it = self.tree.itemAt(pos)
            m = QMenu(self.tree)
            a1 = m.addAction("📋 复制条目文字")
            a2 = m.addAction("📋 复制全部条目 (%d 条)" % self.tree.topLevelItemCount())
            a1.setEnabled(it is not None)
            _pick = m.exec_(self.tree.viewport().mapToGlobal(pos))
            if _pick is a1 and it is not None:
                QApplication.clipboard().setText(self._item_text(it))
                self._flash("已复制条目: %s" % self._item_text(it)[:40])
            elif _pick is a2:
                _all = self._tree_all_text()
                QApplication.clipboard().setText(_all)
                self._flash("已复制 %d 条左树条目" % len(_all.splitlines()))
        except Exception:                                                       # noqa: BLE001
            pass

    def _flash(self, msg):
        """一句话反馈 (不抢底部信息窗): 在鼠标旁弹 2s。"""
        try:
            from PyQt5.QtWidgets import QToolTip
            from PyQt5.QtGui import QCursor
            QToolTip.showText(QCursor.pos(), msg, self, self.rect(), 2000)
        except Exception:                                                       # noqa: BLE001
            pass

    # ── 左侧栏宽度: 适配内容 + 可拖 + 记住 (2026-10-12 老倪「无法更改宽度, 字体都挡住了」) ──
    _TREE_W_KEY = "config_center/tree_width"
    _TREE_W_SIG_KEY = "config_center/tree_width_sig"   # 记宽度时树长什么样 (树变了 ⇒ 旧记忆作废)
    _TREE_W_PIN_KEY = "config_center/tree_width_pin"   # 用户指定宽度 (0=不固定); env ZMAX_CFG_TREE_W 优先
    _TREE_W_DEF_MAX = 220                              # 默认打开宽度上限 (px) —— 老倪 10-17「太宽」

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
            # 🎯 2026-10-17 「太宽」: 行里只显示「序号+名称」, 星名进 data/tooltip (与 _fill_tree 一致)
            _txt_full = "%s %s" % (mark, _ss.star_line("prod"))
            txt = re.sub(r"\s*·\s*(天枢|天璇|天玑|天权|玉衡|开阳|瑶光).*$", "", _txt_full)
            for i in range(self.tree.topLevelItemCount()):
                it = self.tree.topLevelItem(i)
                if it is not None and "产品配置" in it.text(0):
                    it.setText(0, txt)
                    it.setData(0, Qt.UserRole, "prod")
                    it.setData(0, Qt.UserRole + 1, _txt_full)
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

    def _tree_pin(self):
        """左栏宽度的**固定值**(用户明确指定才算): 环境变量 ZMAX_CFG_TREE_W > QSettings pin。"""
        v = (os.environ.get("ZMAX_CFG_TREE_W") or "").strip()
        if v:
            try:
                return max(120, min(900, int(float(v))))
            except Exception:                                                   # noqa: BLE001
                pass
        try:
            p = int(QSettings("ZMAX", "Console").value(self._TREE_W_PIN_KEY, 0) or 0)
            return max(120, min(900, p)) if p else 0
        except Exception:                                                       # noqa: BLE001
            return 0

    def _tree_cfg_width(self):
        """🎯 用户自己改的数: config/platform/zmax_ui_layout.json 的 config_center_left_width。

        ★ 老倪 2026-10-17: 「我自己改配置中心的左侧栏宽度, 数值在哪里, 我自己改」
          ⇒ 真源落成**一个可编辑的 JSON 数值** (不是代码常量), 打开配置中心即读, 不用重启。
        返回 0 = 没配/配 0 ⇒ 表示"按内容自适应"。
        """
        try:
            _root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                 "..", ".."))
            p = os.path.join(_root, "config", "platform", "zmax_ui_layout.json")
            if os.path.isfile(p):
                with open(p, encoding="utf-8") as f:
                    d = json.load(f)
                v = d.get("config_center_left_width")
                if v is not None:
                    v = int(float(v))
                    return max(120, min(900, v)) if v else 0      # 0=自适应; 有效范围 120~900 (老倪自己填的数)
        except Exception:                                                       # noqa: BLE001
            pass
        return 0

    def _tree_open_width(self):
        """打开时左栏宽度 —— 内容需求为基准, 但**默认压到 210px** (老倪 2026-10-17「现在太宽了」)。

        口径:
            pin(ZMAX_CFG_TREE_W / QSettings pin, 用户明确给数) > 记忆宽度(且 < 需求) > min(需求, 210)
        210px 的取舍: 192DPI 下树里一条「⛔ 7. 文档配置 · 瑶光」= 246px, 210 会让尾部「· 瑶光」
        显示成省略号 —— 序号+名称(AI 判断真正要看的) 完整可见, 完整串在条目 tooltip 里;
        QTreeWidget 存的是**全文**, 省略号只在绘制层, 所以点选/分派逻辑不受影响。
        """
        need = int(getattr(self, "_tree_need", 0) or 0)
        pin = self._tree_pin()
        if pin:
            return pin
        cfg = self._tree_cfg_width()          # ★ 用户自己在 config/platform/zmax_ui_layout.json 里改的数
        if cfg:
            return cfg
        try:
            s = QSettings("ZMAX", "Console")
            saved = int(s.value(self._TREE_W_KEY, 0) or 0)
            saved_sig = str(s.value(self._TREE_W_SIG_KEY, "") or "")
        except Exception:                                                       # noqa: BLE001
            saved, saved_sig = 0, ""
        if saved and saved < need and saved_sig == self._tree_sig():
            return saved
        return min(need, self._TREE_W_DEF_MAX) if need else self._TREE_W_DEF_MAX

    def _on_tree_split_moved(self, _pos, _idx):
        """用户拖动分隔条 ⇒ 记住宽度(下次开这个页面沿用)。

        🔴 2026-10-17 老倪「配置中心打开时左侧边栏太宽」——真因: 只记宽度不记**当时树长什么样**,
        历史遗留(8 项旧树/误拖)的 254px 被当成有效值每次沿用, 而 7 颗星的文本需求只要 184px。
        现在同时记一份"树指纹"(条目数 + 最长条目像素/文本), 指纹一致才算有效记忆;
        且**记忆只有在比内容需求更窄时**才用于打开 (_tree_open_width), 拖动本身一律生效于当前窗口。
        """
        try:
            s = QSettings("ZMAX", "Console")
            s.setValue(self._TREE_W_KEY, int(self.tree.width()))
            s.setValue(self._TREE_W_SIG_KEY, self._tree_sig())
            s.setValue(self._TREE_W_PIN_KEY, 0)      # 手动拖过 ⇒ 清掉固定值, 以拖动结果为准
        except Exception:                                                       # noqa: BLE001
            pass

    def _tree_sig(self):
        """左树指纹 = 条目数 | 最长条目像素 | 最长条目文本(前 40 字)。树变了 ⇒ 旧宽度记忆作废。"""
        try:
            fm = self.tree.fontMetrics()
            longest, px, n = "", -1, 0
            stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
            while stack:
                it = stack.pop()
                if it is None:
                    continue
                n += 1
                t = it.text(0)
                w = fm.horizontalAdvance(t)
                if w > px:
                    longest, px = t, w
                stack.extend(it.child(i) for i in range(it.childCount()))
            return "%d|%d|%s" % (n, px, longest[:40])
        except Exception:                                                       # noqa: BLE001
            return ""

    def _reapply_tree_width(self):
        """重读配置并重落宽度 —— 只在 (内容需求 / 配置数 / pin) 变了时才动, 避免把手拖结果冲掉。"""
        try:
            need = self._tree_need_width()
            sig = (need, self._tree_cfg_width(), self._tree_pin())
            if getattr(self, "_tree_applied_sig", None) == sig:
                return
            self._tree_need = need
            self._tree_applied_sig = sig
            self._apply_tree_width()
        except Exception:                                                       # noqa: BLE001
            pass

    def _apply_tree_width(self):
        """落定左栏宽度 —— 内容需求 / 更窄的记忆 / 用户 pin (见 _tree_open_width)。"""
        total = max(self.width(), self.splitter.width())
        want = int(self._tree_open_width())
        want = max(min(self._tree_need, 120), min(want, max(self._tree_need, int(total * 0.5))))
        self.splitter.setSizes([want, max(1, total - want)])

    # ── 左侧域树 ──
    def _fill_tree(self, d, tk):
        """左树顶层 = **北斗七星阵** 七项, 从上到下 1..7 (老倪 2026-10-15)。

        次序 = 配置体系的传导次序: 天枢定边界 → 天璇定作业 → 天玑定能力 → 天权定算法 → 玉衡定指标
        → 开阳定落地 → 瑶光定记录。每项前面必须有**序号** (老倪原话: 「注意前面要显示一个序号」)。

        与原布局的差别 (如实记, 免得下次又"改回"来):
          · 原来顶层 8 项, 次序是 模型/工程/功能/性能/文档/任务/工单/产品 —— 顺序是按代码里 append 的先后来的,
            没有体系含义; 现在按阵法次序。
          · 2026-10-19 老倪: 「将 工单配置，替换成 工程配置」⇒ 第六阵 = 工程配置(开阳·定落地),
            工程库/参数注册表/工程-模型匹配/AR 示教点位; 工单实例搬进第七阵 文档配置(与成本报价、商业模式同页)。
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
        # 3 · 天玑 —— 功能配置 (特征库功能域)
        #   2026-10-19: 工程域**升格为第六阵**, 不再是天玑下的子入口 ⇒ 这里只留功能域本身
        _r3, _n3, _b3 = _dom["功能配置"]
        doms.append((f"{_ss.star_line('func')}  {_r3}/{_n3}", "⛔" if _r3 < _n3 else "✅",
                     list(_b3)))
        # 4 · 天权 —— 模型配置 ; 5 · 玉衡 —— 性能配置
        for _k, _d in (("model", "模型配置"), ("perf", "性能配置")):
            _r, _n, _b = _dom[_d]
            doms.append((f"{_ss.star_line(_k)}  {_r}/{_n}", "⛔" if _r < _n else "✅", list(_b)))
        # 6 · 开阳 —— 工程配置 (2026-10-19 老倪: 「将 工单配置，替换成 工程配置」)
        #   工程域参数注册表 = 这一阵的主表; 工单实例搬去第七阵文档配置
        _r6, _n6, _b6 = _dom["工程配置"]
        doms.append((f"{_ss.star_line('eng')}  {_r6}/{_n6}",
                     "⛔" if _r6 < _n6 else "✅", list(_b6)))
        # 7 · 瑶光 —— 文档配置 (收束全部: 三份文档 + 工单实例 + 成本报价 + 商业模式)
        doms.append((f"{_ss.star_line('doc')}  文档 {sum(1 for m in dm if m == '✅')}/3",
                     "⛔" if "⛔" in dm else "✅",
                     ["供应商外发 SOR", "项目立项文档", "合作协议", "一致性核对",
                      "工单实例 %d 个" % len(_bs), "成本/报价", "商业模式"]))
        #   记 (2026-10-14 老倪): 「任务配置」= 元任务粒度 (功能 + 配置参数) / 「工单配置」= 工单实例粒度 (一次执行)。
        #   记 (2026-10-13 老倪): 产品标识 550A 原创版 / 550B 标定版 / 550C 量产版 + 空间质数结构化理解能力。
        # 🧹 2026-10-15 老倪: 「左侧不用显示那么多, 只显示 1..7; 详细信息要在配置页面显示」
        #   ⇒ 顶层 7 行只写「序号 + 名称 · 星名」(+ 一个 ✅/⛔ 就绪符), **不带计数/当前值/子项**;
        #     计数与真源时间进 ①每页顶部阵图条「本页真源: …」 ②左树 hover tooltip (可复制原文)。
        _facts = _star_facts()
        self.tree.clear()
        for label, mark, kids in doms:
            _short = re.sub(r"\s{2,}.*$", "", label)          # 掉掉计数尾巴, 只留「N. 名称 · 星名」
            # 🎯 2026-10-17 老倪「现在太宽了」: 行里只显示「序号 + 名称」, 去掉尾部「· 星名」
            #   (星名在顶部阵图条与条目 tooltip 里都有)。全文仍存 QTreeWidget (只影响绘制层),
            #   并把"全文/星 key"存进 item data ⇒ 点选分派逻辑照旧按全文走, 不会因为少了星名而点不动。
            # 行文: 去掉「· 天枢/天璇/…」星名段 (及其后内容); 星名仍在阵图条与 tooltip
            _row = re.sub(r"\s*·\s*(天枢|天璇|天玑|天权|玉衡|开阳|瑶光).*$", "", _short)
            # 🆕 2026-10-21 老倪: 「左边栏的小对号, 应该打开哪个配置页面, 小对号就对应显示相应的配置」
            #   ⇒ 行首标记不再表示「真源就绪」, 而是「当前打开的是这一页」:
            #      ✅ = 当前页 · ○ = 其它页; 真源就绪状态挪进 tooltip (仍现算, 信息不丢)。
            it = QTreeWidgetItem([f"○ {_row}"])
            _k0 = _ss.key_for_label(label)
            it.setData(0, Qt.UserRole, _k0)
            it.setData(0, Qt.UserRole + 1, f"{mark} {_short}")   # 全文 (含 · 星名) —— 分派/复制用
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
            it.setToolTip(0, ("真源就绪: %s\n" % mark + _tip + _det).strip())     # 就绪符挪进 tooltip
            self.tree.addTopLevelItem(it)

        self._mark_tree_current()          # 行首 ✅ 跟着「当前打开的是哪一页」走 (2026-10-21 老倪)

    def _mark_tree_current(self, *_a):
        """左树行首标记 = **当前打开的配置页** (老倪 2026-10-21: 「打开哪个配置页面, 小对号就对应显示」)。

        ✅ = 当前页 (并加粗), ○ = 其它页; 真源就绪 (✅/⛔) 不再占行首, 挪到条目 tooltip。
        目的: 一眼知道"我现在在哪一页", 而不是把 ⛔ 误读成"这页不能用"。
        """
        try:
            _s = _ss.star_for_tab(self.tabs.tabText(self.tabs.currentIndex()))
            _cur = _s.get("key") if _s else None
        except Exception:                                                       # noqa: BLE001
            _cur = None
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            if it is None:
                continue
            _k = it.data(0, Qt.UserRole)
            _full = str(it.data(0, Qt.UserRole + 1) or "")
            _body = re.sub(r"^(?:✅|⛔|○)\s+", "", _full)          # 去掉底层就绪符
            _row = re.sub(r"\s*·\s*(天枢|天璇|天玑|天权|玉衡|开阳|瑶光).*$", "", _body)
            _on = (_k == _cur)
            it.setText(0, "%s %s" % ("✅" if _on else "○", _row))
            # 就绪符始终留在 tooltip (别的刷新路径会重写 tooltip ⇒ 这里可重入地补一次, 不叠加)
            _ready = _full[:1] if _full[:1] in ("✅", "⛔") else "—"
            _tip_now = str(it.toolTip(0) or "")
            if not _tip_now.startswith("真源就绪:"):
                it.setToolTip(0, ("真源就绪: %s\n%s" % (_ready, _tip_now)).strip())
            try:
                _f = it.font(0)
                _f.setBold(bool(_on))
                it.setFont(0, _f)
            except Exception:                                                   # noqa: BLE001
                pass

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
        """换页签 = 换阵: 清掉"上一页点过哪颗星"的记忆, 按新页签默认星点亮 (一致性)。

        2026-10-15 加: 同时把底部信息窗刷成**这一面**的信息 (老倪: 「选择相应的配置面时, 信息没有对应上」)。
        """
        self._star_focus = None
        self._sync_star_banner()
        self._sync_out_for()
        # 🆕 2026-10-21 老倪: 换页 ⇒ 左树那个小对号跟着走 (打开哪页, ✅ 就落在哪一项)
        try:
            self._mark_tree_current()
        except Exception:                                                       # noqa: BLE001
            pass

    def _sync_star_banner(self, *_a):
        """按当前页签刷阵图条: 七星页显示**当前这一颗**星的说明, 非七星页显示阵法总览 + 如实说明。

        「本页真源: …」只对没在阵图条上重复的页显示 —— 见 BANNER_FACT_HIDDEN。
        """
        try:
            self.star_banner.set_tab(self.tabs.tabText(self.tabs.currentIndex()),
                                     focus_key=getattr(self, "_star_focus", None),
                                     facts={k: v for k, v in _star_facts().items()
                                            if k not in BANNER_FACT_HIDDEN})

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
    _MT_COLS = ("元任务", "功能名称", "层", "输入", "输出", "配置参数", "依赖关系", "验证方法", "承载场景", "归属", "优先")

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
            t = _task_obj(tid) or {}
            vis = [m for m in mt if tid in (m.get("tasks") or [])]
            _tot = _n_tasks() or 8
            n_all = sum(1 for m in vis if len(m.get("tasks") or []) >= _tot)
            n_one = sum(1 for m in vis if len(m.get("tasks") or []) <= 1)
            return ("功能级元任务 (一个功能 + 该功能全部配置参数) · 承载任务 %s (%s)\n"
                    "   ▸ 该任务启用 %d 条: 仅本任务 %d · 全 %d 任务共用底座 %d · 其余多任务共用 %d"
                    "   (真源 config_meta.json + 画布连线 + tasks.json)"
                    % (tid, (t.get("name") or "—")[:22], len(vis) if shown is None else shown,
                       n_one, _tot, n_all, max(0, len(vis) - n_all - n_one)))
        return ("功能级元任务 (一个功能 + 该功能全部配置参数) · 全部 %d 条 "
                "· 真源 config_meta.json + 画布连线 + tasks.json" % len(mt))

    def _filter_meta_tasks(self, tid=None):
        """元任务表按**承载任务**过滤 (tid=None = 全部)。返回可见条数; 表头同步口径。

        老倪 2026-10-28: 点任务行 ⇒ 上面「任务级元任务」换成该任务自己的执行元任务,
        下面这张功能级表也只留该任务启用的行 (按"最专用优先"排, 底座在后)。
        """
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
        try:                                   # 任务级元任务表跟着切 (同一个 tid, 一处口径)
            self._fill_task_level(tid)
        except Exception:                                                       # noqa: BLE001
            pass
        return shown

    def _fill_task_level(self, tid=None):
        """把「任务级元任务」表刷成 tid 的 (tid=None ⇒ 用绑定真源里的活跃任务)。返回条数。"""
        t = getattr(self, "tl_table", None)
        if t is None:
            return 0
        tk = _j(BIND_J, {}) or {}
        tid = tid or tk.get("active_task") or (self._task_rows[0] if getattr(self, "_task_rows", None) else None)
        items, note, src = _task_level_meta(tid) if tid else ([], "无任务可选", "—")
        self._tl_items = items
        t.setWordWrap(False)             # 一行一条 (开了换行 + resizeRowsToContents 会把 5 行撑成 665px)
        t.setRowCount(len(items))
        for r, m in enumerate(items):
            twin = m.get("t_win")
            twin_s = ("%.2f→%.2fs" % (twin[0], twin[1])) if twin else "并行/常驻"
            tg = " / ".join(m.get("targets") or []) or "—"
            acts = m.get("actions") or []
            cells = [m.get("id") or "—", m.get("name") or "—",
                     HAND_CN.get(m.get("hand") or "", "—(真源未标)"),
                     m.get("layer") or "—",
                     ("%d" % m["n_seg"]) if m.get("n_seg") else "0(协同)",
                     twin_s, tg, (acts[0] if acts else "—")]
            for c, val in enumerate(cells):
                it = QTableWidgetItem(str(val))
                it.setToolTip("元任务 %s · %s\n手别: %s\n时空窗: %s\n目标对象: %s\n动作序列:\n  %s"
                              % (m.get("id"), m.get("name"), HAND_CN.get(m.get("hand") or "", "未标注"),
                                 twin_s, tg, "\n  ".join(acts) or "—"))
                if c == 2:                                   # 手别上色: 右蓝 / 左绿 / 双手紫
                    col = HAND_COLOR.get(m.get("hand") or "")
                    if col:
                        it.setForeground(QBrush(QColor(col)))
                t.setItem(r, c, it)
        try:                             # 行高按实际 (Consolas 10 实测 28px/行): 表高 = 表头 + 全部行, 5~9 条一屏装下
            t.verticalHeader().setDefaultSectionSize(24)
            for _r in range(t.rowCount()):
                t.setRowHeight(_r, 24)
            _need = (max(41, t.horizontalHeader().height())
                     + sum(t.rowHeight(_r) for _r in range(t.rowCount())) + 6)
            t.setMinimumHeight(min(_need, 400))
            t.setMaximumHeight(min(_need, 400))
        except Exception:                                                       # noqa: BLE001
            pass
        self._fit_meta_box()
        if getattr(self, "tl_head", None) is not None:
            self.tl_head.setText("🎯 任务级元任务 (带手别/时空窗/目标对象) · %s"
                                 "  ← 点上面任一任务行换任务; 点本表某行 ⇒ 下方摊开它的段级动作"
                                 % (note if tid else "未选中任务"))
        if getattr(self, "tl_src", None) is not None:
            self.tl_src.setText("   真源: %s" % src)
        # 段级明细: 默认摊第一条 (老倪要"能对应 AR 场景的具体操作")
        try:
            t.itemSelectionChanged.disconnect()
        except Exception:                                                       # noqa: BLE001
            pass
        try:
            t.itemSelectionChanged.connect(self._fill_seg_level)
        except Exception:                                                       # noqa: BLE001
            pass
        if items:
            t.selectRow(0)
        self._fill_seg_level()
        return len(items)

    def _fill_seg_level(self, *_a):
        """选中的元任务 ⇒ 段级明细 (seq/动作/目标/手别/时长/累计时刻)。这段是"对应 AR 场景具体操作"的实证。"""
        t, s = getattr(self, "tl_table", None), getattr(self, "seg_table", None)
        if t is None or s is None:
            return 0
        items = getattr(self, "_tl_items", []) or []
        r = t.currentRow()
        m = items[r] if 0 <= r < len(items) else {}
        segs = m.get("segs") or []
        s.setWordWrap(False)
        s.setRowCount(len(segs))
        for i, g in enumerate(segs):
            dur = g.get("t")
            end = g.get("t_end")
            cells = [str(g.get("seq") or i + 1),
                     str(g.get("label") or "—"),
                     str(g.get("target") or "—"),
                     HAND_CN.get(g.get("hand") or "", "—"),
                     ("%.3fs" % dur) if isinstance(dur, (int, float)) else "—",
                     ("%.3fs" % end) if isinstance(end, (int, float)) else "—"]
            for c, val in enumerate(cells):
                it = QTableWidgetItem(val)
                it.setToolTip("%s · 目标 %s · 手别 %s · 时长 %s · 累计 %s"
                              % (g.get("label"), g.get("target"), cells[3], cells[4], cells[5]))
                if c == 3:
                    col = HAND_COLOR.get(g.get("hand") or "")
                    if col:
                        it.setForeground(QBrush(QColor(col)))
                s.setItem(i, c, it)
        if getattr(self, "seg_head", None) is not None:
            self.seg_head.setText("↳ 段级明细 · %s %s · %d 段 · 目标对象 %s"
                                  % (m.get("id") or "—", m.get("name") or "",
                                     len(segs), " / ".join(m.get("targets") or []) or "—"))
        try:                             # 段级表按实际段数给高 (1 段就别占 287px, AOI 的 10 段一屏装全)
            s.verticalHeader().setDefaultSectionSize(24)
            for _r in range(s.rowCount()):
                s.setRowHeight(_r, 24)
            _sn = (max(41, s.horizontalHeader().height())
                   + sum(s.rowHeight(_r) for _r in range(s.rowCount())) + 6)
            s.setMinimumHeight(min(_sn, 24 * 14 + 47))
            s.setMaximumHeight(min(_sn, 24 * 14 + 47))
        except Exception:                                                       # noqa: BLE001
            pass
        self._fit_meta_box()
        return len(segs)

    def _fit_meta_box(self):
        """三张表 (任务级 / 段级 / 功能级) 同在一个舱里 ⇒ 舱最小高度 = 两张表真实需要 + 表头/按钮 + 功能级地板。

        老倪 2026-10-28: 「元任务窗口太矮」的历史根因就是"舱高是布局分剩下的"。
        这里按当前实际行数重算, 换任务/换元任务时舱高跟着变 (AOI 9 段就给 9 行, 别的任务 1 段就只给 1 行)。
        """
        box = getattr(self, "_meta_box", None)
        tl, sg = getattr(self, "tl_table", None), getattr(self, "seg_table", None)
        if box is None or tl is None or sg is None:
            return
        try:
            fixed = 470          # 两个表头行 (tl_head ≤72 / seg_head ≤44 / tl_src 20 / meta_head 60) + 按钮行 + 间距
            floor = 500          # 功能级元任务表地板 (AOI 33 行 = 767px 刚好一屏; 53 行时表内滚, 9px 分隔条可拖大)
            box.setMinimumHeight(int(tl.height() + sg.height() + fixed + floor))
        except Exception:                                                       # noqa: BLE001
            pass

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
                "  依赖关系 : %s\n  验证方法 : %s\n  承载场景 : %s\n  归属     : %s\n"
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
                   _owner_text(m),
                   m.get("node_id") or "—", m.get("layer") or "—", m.get("prio") or "—",
                   m.get("month") or "—"))

    def _build_meta_block(self, layout, th):
        """任务表之下再加一张**元任务表**: 每个元任务 = 一个功能 + 该功能全部配置参数。

        列按老倪文档《元任务标准模板》落 (功能名称/输入/输出/配置参数/依赖关系/验证方法/承载场景)。
        ⚠️ 加的是**一张新表**, 上面任务表的 14 列一列没动 (只增列/增表, 不换列)。
        """
        mt = _meta_tasks()
        # 🔴 老倪 2026-10-28: 「点 TASK0-7, 下面的元任务要对应变化」—— 功能级元任务没有一条是单任务专属,
        #   所以按"**最专用优先**"排: 服务任务数少的在前 (7 任务共用的 AOI 相关功能先露头),
        #   全 8 任务共用的底座在后; 归属列把这件事写明白, 不再让人以为"点了没变"。
        mt = sorted(mt, key=lambda m: (0 if (m.get("tasks") or []) else 9,
                                       len(m.get("tasks") or []),
                                       _LAYER_ORD.get(m.get("layer") or "", 9),
                                       str(m.get("mt_id") or "")))
        self._meta_rows = mt
        rows = [[m.get("mt_id") or "—", (m.get("name") or "")[:30], m.get("layer") or "—",
                 _short(m.get("inputs")), _short(m.get("outputs")), "%d 条" % m.get("n_params", 0),
                 _short(m.get("deps_up")), _short(m.get("verification")), _short(m.get("scenes")),
                 _owner_text(m), m.get("prio") or "—"] for m in mt]
        # ── 🎯 任务级元任务 (该任务自己的执行元任务) —— 老倪 2026-10-28 ─────────────────────
        #   这一张才是"任务 ↔ 元任务"的对应关系: 真源 tasks.json 的 meta_tasks (TASK-07-AOI 5 条),
        #   没登记的用该任务 steps 派生并标明, 点哪个任务行就换成哪个任务的 (与下面功能级表同一触发)。
        self.tl_head = QLabel("🎯 任务级元任务 · 正在加载…")
        self.tl_head.setFont(QFont("Consolas", 10))
        self.tl_head.setStyleSheet("color:%s;background:transparent;font-weight:bold;" % th["C_YELLOW"])
        self.tl_head.setWordWrap(True)
        # 🔴 2026-10-28 实测: QLabel(wordWrap=True) 默认垂直方向也 Expanding ⇒ 离屏量到 tl_head/tl_src/meta_head
        #   各吃到 480px, 把两张表挤成 222/480px (老倪那句"元任务窗口太矮"的同类根因)。标签只许按内容占高。
        self.tl_head.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.tl_head.setMaximumHeight(72)
        layout.addWidget(self.tl_head)
        self.tl_table = _mk_table(["元任务", "名称 (含手别/对象)", "手别", "层", "段数", "时空窗",
                                   "目标对象", "动作要点"], [], th)
        try:
            self.tl_table.verticalHeader().setDefaultSectionSize(24)
            self.tl_table.setMinimumHeight(28 * 4 + 47)      # 4 条地板 (少于 4 条也按 4 条给高, 免得跳)
            self.tl_table.setMaximumHeight(28 * 10 + 47)     # 10 条上限 (实测最多 9 条 steps, 一屏装下)
        except Exception:                                                       # noqa: BLE001
            pass
        layout.addWidget(self.tl_table)
        # ── ↳ 段级明细 (选中的元任务 ⇒ 逐段: 动作/目标/手别/时长/累计) ────────────────────
        #   老倪 2026-10-28: 「这些元任务能对应 AR 场景的具体操作么?」 —— 这一段就是对应关系:
        #   每条动作段直接落在 槽k/孔k/金手指点/侧面点N/下料盘/废料盘 上, 带手别与时刻。
        self.seg_head = QLabel("↳ 段级明细 · 点上面任一元任务行")
        self.seg_head.setFont(QFont("Consolas", 10))
        self.seg_head.setStyleSheet("color:%s;background:transparent;" % th["C_GRAY"])
        self.seg_head.setWordWrap(True)
        self.seg_head.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.seg_head.setMaximumHeight(44)
        layout.addWidget(self.seg_head)
        self.seg_table = _mk_table(["段号", "动作 (AR 场景)", "目标对象", "手别", "时长", "累计时刻"], [], th)
        try:
            self.seg_table.verticalHeader().setDefaultSectionSize(24)
            self.seg_table.setMinimumHeight(24 * 10 + 47)
            self.seg_table.setMaximumHeight(24 * 14 + 47)
        except Exception:                                                       # noqa: BLE001
            pass
        layout.addWidget(self.seg_table)
        self.tl_src = QLabel("   真源: —")
        self.tl_src.setFont(QFont("Consolas", 9))
        self.tl_src.setStyleSheet("color:%s;background:transparent;" % th["C_GRAY"])
        self.tl_src.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.tl_src.setMaximumHeight(20)
        layout.addWidget(self.tl_src)
        self.meta_head = QLabel(self._meta_head_text(None, len(mt)))
        self.meta_head.setFont(QFont("Consolas", 10))
        self.meta_head.setStyleSheet("color:%s;background:transparent;" % th["C_GRAY"])
        self.meta_head.setWordWrap(True)
        self.meta_head.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.meta_head.setMaximumHeight(60)
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
        # 🔴 老倪 2026-10-15 (同一条「看不到任务」): 元任务表 75 行原来**没有最小高度** ⇒ 被压到 192px
        #   (22px 行高 ⇒ 只有 8 行可见)。当时给的是 min(300, …) 的**天花板**;
        # 🔴 老倪 2026-10-15 第二轮: 「元任务 窗口, 也是太矮了, 调高适配」—— 实测(离屏 1700×1700)
        #   它只拿到 463px ⇒ 75 行里只看得到 19 行, 而且高度是布局"分剩下的", 想多看也拉不动。
        #   改法(根因是"没有可拖的边界"): 任务表 ↔ 元任务表 之间插一条 **竖直 QSplitter**(9px 可拖),
        #   这里的最小高度只当"不许被拖没"的地板(240px), 不再是天花板; 高度交给分隔条 + 老倪自己拖。
        try:
            t.setMinimumHeight(min(240, 22 * (t.rowCount() + 2) + 8))
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
        try:                     # 首屏先按**活跃任务**把任务级元任务摊开 (不必先点)
            self._fill_task_level(None)
        except Exception:                                                       # noqa: BLE001
            pass

    def _show_orders(self, txt=""):
        """🧾 工单实例页 (2026-10-19 起在「📄 文档配置」页里)。点具体工单号 ⇒ 底部面板摊开这份工单的完整配置面。"""
        i = self._tab_index_by_title("文档配置")
        if i >= 0:
            self.tabs.setCurrentIndex(i)
            # 工单块在文档配置页里靠下 ⇒ 切页后把它滚进视野 (否则"点了像没反应")
            try:
                _sa = self.tabs.widget(i)
                _sa.ensureWidgetVisible(getattr(self, "order_table", None), 0, 60)
            except Exception:                                                   # noqa: BLE001
                pass
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
            "🧾 工单实例 · %s" % i.get("order_no", "—"),
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
            self._log_cc("   ⛔ 先在「📄 文档配置」页的工单表里点一行 (共 %d 份工单)" % len(ords))
            return False
        return self._show_order_detail(ords[r])

    def _on_tree(self, item, _col):
        txt = item.text(0)
        # 🎯 2026-10-17: 行里显示的是短版 (无「· 星名」), 分派/过滤一律用存下来的**全文**
        #   (item data UserRole+1); 这样"左栏变窄"不影响任何点选语义。
        try:
            _full = item.data(0, Qt.UserRole + 1)
            if _full:
                txt = str(_full)
        except Exception:                                                       # noqa: BLE001
            pass
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
            if "工单配置" in txt:        # 2026-10-19: 旧左树行/历史会话里的叫法 —— 工单已并入文档配置
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
    # 🗑 2026-10-19 老倪: 「…这些全删掉」——产品质数 / 当前发布指纹 / 质数结构自检 / 能力质数签名 四行
    #   + 说明行 + 真源行全部下架, 只留 产品 / 版本号 / 能力数 (值仍全部从真源回读)。
    # 🏷 2026-10-21 老倪: 「版本段 改成 版本号 … 都与系统总版本号保持同步更新,
    #   即 A B C 只是产品的配置标识, 版本号全系统统一」⇒ 这一行不再是每档的 5.50.A/B/C,
    #   而是**系统总版本** (读 update_checker.CURRENT_VERSION, 全系统一份, 三档同一个号)。
    # 🏷 2026-10-21 老倪定三档运行位置: 「550A 在本地运行, 550B 用于 vscode, 550C 用于量产,
    #   直接部署在 intel 上, 550C 包括所有模型, 可以远程端侧实时运行」
    #   ⇒ 真源 products.<id>.runtime 新增运行时域 (location/label/host/host_ip/models/realtime),
    #     界面加一行「运行位置」, 卡片底行 = 系统总版本号 · 运行位置。
    _PROD_ROWS = ("产品", "版本号", "运行位置", "能力数")

    def _product_card(self, th):
        """🏷 产品配置区 —— 三个产品**单选** + 右侧**真源回读**值 (可复制)。

        老倪 2026-10-13: 「流形引擎节点要一眼认出是系统核心 —— 给它加产品标识 (550A/550B/550C)
        与空间质数结构化理解能力的输出」⇒ 配置中心这边给产品配置区:
          · 选中即**原子写回**真源 config/platform/zmax_product.json 的 active_product (临时文件 + os.replace);
          · 右边显示 版本段 / 能力数 —— 每个值都**从真源回读**, 不是界面自算的副本;
          · 显示可复制 (双击 / 右键菜单 / 📋 按钮, 复制的是**完整值**);
          · 窄窗 1280 完整可见: 值标签自动换行 (不截断), 每个字段一行 + 一个 📋 按钮。
        """
        card = QWidget()
        card.setObjectName("productConfigCard")
        card.setStyleSheet(f"background:{th['C_CARD']};border:1px solid {th['C_BORDER']};border-radius:6px;")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(10, 8, 10, 8)
        cv.setSpacing(6)

        ttl = QLabel("产品配置 —— 产品档 · 点卡片切换 (写回真源)")
        ttl.setFont(QFont("Consolas", 11, QFont.Bold))
        ttl.setWordWrap(True)
        ttl.setStyleSheet(f"color:{th['C_WHITE']};background:transparent;border:none;")
        cv.addWidget(ttl)

        # ① 三档卡片 (VEH.6.01/02/03) —— 选中 → 写回真源 active_product
        #    老倪 2026-10-21: 「只是一个小白点来选择配置, 不好看 … 更加绚丽 … 要明显, 好看一些」
        #    卡片是 QRadioButton 子类 (_ProductCard), 单选语义/判据不变; 外观全部自绘。
        row = QHBoxLayout()
        row.setSpacing(14)
        self._prod_group = QButtonGroup(self)
        self._prod_group.setExclusive(True)
        self._prod_btns = {}
        for _i, pid in enumerate(PRODUCT_IDS):
            _cf = PRODUCT_CARDS.get(pid) or {}
            rb = _ProductCard(pid,
                              _cf.get("code") or ("VEH.6.0%d" % (_i + 1)),
                              _cf.get("c") or "#8B5CF6",
                              _cf.get("glow") or "#C4B5FD")
            rb.setObjectName("productRadio_%s" % pid)
            rb.setStyleSheet("background:transparent;border:none;")   # 全部自绘, 不要 QSS 底
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
        segs = v.get("segments") or {}
        roles = v.get("roles") or {}
        for pid in PRODUCT_IDS:
            rb = (getattr(self, "_prod_btns", {}) or {}).get(pid)
            if rb is None:
                continue
            nm = str(names.get(pid) or "").strip()
            rb.setText(nm if nm.startswith(pid) else ("%s %s" % (pid, nm) if nm else pid))
            if hasattr(rb, "set_sub"):               # 🎨 卡片底行: 系统总版本号 · 运行位置
                # 2026-10-21 老倪: A=本地运行 / B=用于 VSCode / C=量产部署在 Intel(全模型·远程端侧实时)
                _rt = (v.get("runtimes") or {}).get(pid) or {}
                _where = str(_rt.get("label") or "").strip()
                if not _where:                        # 真源缺 runtime 就退回旧口径 (定位), 不编造
                    _role = str(roles.get(pid) or "").strip()
                    _suf = str(nm).split(" ", 1)[1].strip() if " " in str(nm) else ""
                    _where = "" if (_role and _role == _suf) else _role
                rb.set_sub(" · ".join([x for x in (str(v.get("system_version") or "").strip(), _where) if x]))
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
            self._log_cc("⛔ 产品真源读不出 (%s): %s — 不造数, 界面如实报缺"
                         % (v.get("src") or REL_PRODUCT, v["error"]))
            return v
        vals["产品"].set_value("%s — %s" % (v.get("active"), v.get("product_name")))
        vals["版本号"].set_value(v.get("system_version"))     # 全系统统一版本号 (不是每档的 5.50.A/B/C)
        _rt = v.get("runtime") or {}
        _where = str(_rt.get("label") or "—").strip()
        _host = str(_rt.get("host") or "").strip()
        _ip = str(_rt.get("host_ip") or "").strip()
        _mdl = str(_rt.get("models") or "").strip()
        _rtl = str(_rt.get("realtime") or "").strip()
        _full = " · ".join([x for x in (_where, _host, ("(" + _ip + ")") if _ip else "",
                                       ("模型: " + _mdl) if _mdl else "",
                                       ("实时: " + _rtl) if _rtl else "") if x])
        vals["运行位置"].set_value(_full)
        vals["运行位置"].setToolTip("真源 %s → products.%s.runtime" % (v.get("src") or REL_PRODUCT, v.get("active")))
        n_prim, n_stage = v.get("n_prim"), v.get("n_stage")
        vals["能力数"].set_value("%s 项%s" % (v.get("n_caps"),
                                            (" (元数据基元 %s + 阶段 %s)" % (n_prim, n_stage))
                                            if n_prim is not None else ""))
        if not silent:
            self._log_cc("🏷 产品配置已按真源重读: active=%s · 能力 %s 项"
                         % (v.get("active"), v.get("n_caps")))
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
    # ══════════════════════════════════════════════════════════════════════════
    # ⚙️ 工程配置 · 按性能等级 A/B/C (老倪 2026-10-28: 「根据性能等级, 进行工程配置,
    #    要有操作手册 working instruction, 保证能够工程实现」)
    #    真源: tools/spec/eng_profiles.json —— 与 docs/deliverables/工程操作手册_三档_A_B_C.md 同源
    # ══════════════════════════════════════════════════════════════════════════
    def _eng_profile_block(self, th):
        import subprocess as _sp
        PJ = os.path.join(ROOT, "tools", "spec", "eng_profiles.json")
        try:
            spec = json.load(open(PJ, encoding="utf-8"))
        except Exception:                                                       # noqa: BLE001
            spec = {"profiles": []}
        profs = spec.get("profiles") or []
        cur = {"id": (profs[0].get("id") if profs else "A")}

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 4)
        lay.setSpacing(4)
        hd = QLabel()
        hd.setTextFormat(Qt.RichText)
        hd.setText("<span style='font-size:12px;font-weight:600;color:%s'>⚙️ 工程配置 + 操作手册 (按性能等级分档)</span>"
                   "<span style='color:%s;font-size:10.5px'>&nbsp;&nbsp;档位与《性能配置》A/B/C 一一对应; "
                   "每步都能直接跑到出结果</span>" % (th["C_YELLOW"], th["C_GRAY"]))
        hd.setWordWrap(True)
        lay.addWidget(hd)

        rowb = QHBoxLayout()
        btns = {}
        for p2 in profs:
            b = _btn("%s 档 · %s" % (p2.get("id"), p2.get("name")), th)
            btns[p2.get("id")] = b
            rowb.addWidget(b)
        rowb.addStretch()
        lay.addLayout(rowb)

        desc = QLabel(); desc.setTextFormat(Qt.RichText); desc.setWordWrap(True)
        lay.addWidget(desc)

        t_hw = _mk_table(["#", "设备", "规格", "数量", "为什么"], [], th)
        t_sw = _mk_table(["服务/资产", "端口", "起法/位置"], [], th)
        t_cb = _mk_table(["标定项", "真源", "容差/判据"], [], th)
        t_wi = _mk_table(["步骤", "做什么", "在哪做", "命令 / 操作", "期望", "状态", ""], [], th)
        t_wi.verticalHeader().setDefaultSectionSize(28)
        for _c, _w2 in ((0, 48), (1, 150), (2, 92), (5, 120), (6, 54)):
            t_wi.setColumnWidth(_c, _w2)
        t_wi.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        t_wi.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)

        def _fill(pid):
            cur["id"] = pid
            prof = next((x for x in profs if x.get("id") == pid), {})
            desc.setText("<span style='color:%s;font-size:10.5px'><b>%s 档</b> · 对应性能: %s</span>"
                         % (th["C_GREEN"], pid, prof.get("perf_ref") or "—"))
            t_hw.setRowCount(0)
            for i, h in enumerate(prof.get("hardware") or [], 1):
                _r = t_hw.rowCount(); t_hw.insertRow(_r)
                for c, v in enumerate([str(i), h.get("item"), h.get("spec"), str(h.get("qty")), h.get("why")]):
                    t_hw.setItem(_r, c, QTableWidgetItem(str(v or "")))
                t_hw.setRowHeight(_r, 26)
            t_hw.setMinimumHeight(26 * max(1, len(prof.get("hardware") or [])) + 48)
            t_sw.setRowCount(0)
            for s2 in prof.get("software") or []:
                _r = t_sw.rowCount(); t_sw.insertRow(_r)
                for c, v in enumerate([s2.get("svc"), str(s2.get("port") or "—"), s2.get("how")]):
                    t_sw.setItem(_r, c, QTableWidgetItem(str(v or "")))
                t_sw.setRowHeight(_r, 24)
            t_sw.setMinimumHeight(24 * max(1, len(prof.get("software") or [])) + 48)
            t_cb.setRowCount(0)
            for c2 in prof.get("calib") or []:
                _r = t_cb.rowCount(); t_cb.insertRow(_r)
                for c, v in enumerate([c2.get("item"), c2.get("src"), c2.get("tol")]):
                    t_cb.setItem(_r, c, QTableWidgetItem(str(v or "")))
                t_cb.setRowHeight(_r, 26)
            t_cb.setMinimumHeight(26 * max(1, len(prof.get("calib") or [])) + 48)
            t_wi.setRowCount(0)
            for s3 in prof.get("wi") or []:
                _r = t_wi.rowCount(); t_wi.insertRow(_r)
                cells = [s3.get("id"), s3.get("title"),
                         {"local": "本机", "onsite": "现场", "orin": "Orin"}.get(s3.get("need"), s3.get("need")),
                         s3.get("cmd"), s3.get("expect"), "未跑", ""]
                for c, v in enumerate(cells):
                    _it = QTableWidgetItem(str(v or ""))
                    _it.setToolTip(str(s3.get("fail") or ""))
                    t_wi.setItem(_r, c, _it)
                if s3.get("need") == "local":
                    _b = QPushButton("▶ 跑")
                    _b.setFixedHeight(22)
                    _b.clicked.connect(lambda _=False, rr=_r, s4=s3: _run(rr, s4))
                    _b.setStyleSheet("QPushButton{font-size:10px;padding:0 6px;}")
                    t_wi.setCellWidget(_r, 6, _b)
                t_wi.setRowHeight(_r, 28)
            t_wi.setMinimumHeight(28 * max(1, len(prof.get("wi") or [])) + 48)
            for k, b in btns.items():
                b.setStyleSheet("QPushButton{font-weight:600;}" if k == pid else "")

        def _run(rr, s4):
            cmd = s4.get("cmd") or ""
            try:
                r = _sp.run(cmd, shell=True, cwd=ROOT, capture_output=True, text=True, timeout=90)
                out = ((r.stdout or "") + (r.stderr or "")).strip()
                ok = (s4.get("expect") or "") in out
                t_wi.item(rr, 5).setText(("✅ 过" if ok else "⛔ 不符"))
                t_wi.item(rr, 5).setForeground(QBrush(QColor(th["C_GREEN"] if ok else th["C_RED"])))
                t_wi.item(rr, 3).setToolTip(out[-600:] or cmd)
                t_wi.item(rr, 5).setToolTip(out[-600:] or "无输出")
            except Exception as _e:                                             # noqa: BLE001
                t_wi.item(rr, 5).setText("⛔ 异常")
                t_wi.item(rr, 5).setToolTip(repr(_e))

        for pid, b in btns.items():
            b.clicked.connect(lambda _=False, k=pid: _fill(k))
        _fill(cur["id"])
        lay.addWidget(t_hw)
        lay.addWidget(t_sw)
        lay.addWidget(t_cb)
        lay.addWidget(t_wi)

        br = QHBoxLayout()
        b_all = _btn("▶ 一键跑本档全部本机步骤", th)

        def _run_all():
            for _r in range(t_wi.rowCount()):
                _wd = t_wi.cellWidget(_r, 6)
                if _wd is not None:
                    _wd.click()
                    QApplication.processEvents()
        b_all.clicked.connect(_run_all)
        b_cp = _btn("📋 复制本档 WI (TSV)", th)

        def _cp():
            prof = next((x for x in profs if x.get("id") == cur["id"]), {})
            lines = ["\t".join(["步骤", "做什么", "在哪做", "命令", "期望", "失败处理"])]
            for s5 in prof.get("wi") or []:
                lines.append("\t".join([str(s5.get("id")), str(s5.get("title")), str(s5.get("need")),
                                        str(s5.get("cmd")), str(s5.get("expect")), str(s5.get("fail"))]))
            QApplication.clipboard().setText("\n".join(lines))
        b_cp.clicked.connect(_cp)
        br.addWidget(b_all); br.addWidget(b_cp); br.addStretch()
        lay.addLayout(br)

        self.eng_hw_table, self.eng_sw_table = t_hw, t_sw
        self.eng_calib_table, self.eng_wi_table = t_cb, t_wi
        self.eng_profile_tiers = [x.get("id") for x in profs]
        self.eng_cur_profile = cur
        return w

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
        # 2026-10-15: 原来按全表给最小高度 (可到 510px) ⇒ 把整页顶高、信息窗被压到 98px。
        # 现在封顶 300px (看不够用滚), 页面整体还能压 (页已包进 QScrollArea)。
        tb.setMinimumHeight(min(300, 28 * (len(rows) + 2) + 6))
        tb.setMaximumHeight(30 * (len(rows) + 2) + 10)
        # 金手指点1 行高亮 + tooltip 统一由 _fill() 写 (建卡与 2s 静默刷新同一处, 不会刷掉)
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
                # 2026-10-21: tooltip 必须在这里写 —— 原来只写在建卡那一遍, 2s 静默刷新重建单元格后
                #   就没了 (判据当场抓到"tooltip 有真源 + 更新记录"红)。行 0 = 金手指点1, 高亮 + 全信息。
                _tip0 = None
                if r2:
                    _r0 = r2[0]
                    _tip0 = ("★ %s —— 位姿 x=%s y=%s z=%s m · a=%s° b=%s° c=%s° · 记录 %s\n   真源 %s\n   %s"
                             % (_r0.get("name", "金手指点1"), _r0["x"], _r0["y"], _r0["z"],
                                _r0.get("a", "—"), _r0.get("b", "—"), _r0.get("c", "—"),
                                _r0["t"], _r0["src"], _r0.get("hist") or ""))
                for c in range(tb.columnCount()):
                    it = tb.item(0, c)
                    if it is not None and r2:
                        it.setForeground(_QC2(th["C_GREEN"]))
                        if _tip0:
                            it.setToolTip(_tip0)
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
              _steps_cell(t),                             # 🆕 2026-10-15 工艺步骤列: 短标签(前2段+共N段), 完整序列进 tooltip
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
        # 🔴 老倪 2026-10-15: 「任务配置的窗口, 太矮了, 看不到任务, 调高, 优化UI显示」
        #   根因 (离屏逐尺寸实测, tools/probe_task_cfg_height.py + tools/probe2_rows.py): 任务表**没有最小高度** ——
        #   页面被压时布局把它和「元任务表」各分一半, 实测 1480x900 / 1920x950 都只分到 **192px**
        #   (表头 41 + 视口 135 ⇒ 7 行任务里只有 **1 行**完整可见, 老倪看到的就是"看不到任务")。
        #   修法: 给任务表一个**装得下全部任务行**的最小高度 (按**真实行高**逐行相加算, 不用 defaultSectionSize
        #   —— 那一列长文本折行后行高实测 133~177px, 按 46 算会算少一半);
        #   窗口再矮也不会被压成看不见, 整页不够高时由外层 QScrollArea 滚。
        #   封顶 620px: 任务数将来变多时不许把整页顶到天上 (超出的行用表内滚动条)。
        try:
            _th_head = max(41, self.tasks_table.horizontalHeader().height())
            _th_rows = sum(self.tasks_table.rowHeight(_r) for _r in range(self.tasks_table.rowCount()))
            _th_hsb = self.tasks_table.horizontalScrollBar().sizeHint().height() or 16
            _th_need = _th_head + _th_rows + 2 * self.tasks_table.frameWidth() + _th_hsb + 4
            self.tasks_table.setMinimumHeight(min(660, _th_need))
            self.tasks_table.setToolTip(
                "任务表最小高度 = 表头 %d + %d 行真实行高合计 %d + 边框/横向滚动条 %d = %dpx\n"
                "⇒ 全部任务行都渲染在表内 (窗口再矮也不压扁; 行数再多才用表内滚动条)"
                % (_th_head, self.tasks_table.rowCount(), _th_rows,
                   2 * self.tasks_table.frameWidth() + _th_hsb + 4, _th_need))
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
                                 (5, _steps_tip(_t)),
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
        # ⚡ 2026-10-19: 这排 12 个按钮挤在一行**实测最小宽度 1472px** ⇒ 窗口 1280/1400 宽时右侧被截
        #   (判据 verify_zmax_open_flow 量到「启动按钮右边缘 1641 > 页宽 1280」; 老倪口径: 界面不许挤/不许截断)。
        #   改成网格 6 个一行: 两行各 ~740px, 1280 宽也完整可见; 宽度够时视觉上仍是两行紧凑按钮组。
        row = QGridLayout()
        row.setHorizontalSpacing(6)
        row.setVerticalSpacing(4)
        _row_btns = []
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
            _row_btns.append(b)
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
        _row_btns.append(_b_mt)
        for _k, _b in enumerate(_row_btns):
            row.addWidget(_b, _k // 6, _k % 6)
        row.setColumnStretch(6, 1)              # 右侧留白 (按钮靠左, 不拉伸)
        l.addLayout(row)
        # ⚠️ 任务表**不直接进 l** —— 它要和元任务表之间夹一条可拖的分隔条 (见本页末尾的 self.tm_split),
        #    否则两张表的高度都只能由布局"分剩下的"决定 ⇒ 元任务表 75 行只看得到 19 行, 老倪也拉不动它。
        #    (老倪 2026-10-15: 「元任务窗口也是太矮了, 调高适配」)
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
        # ⚠️ row2 (启动按钮行) **不进 l** —— 它要跟着任务表进同一个舱 (_ul, 见下面分隔条那段);
        #    两边都 addLayout 会让 Qt 只认第一个父布局 ⇒ 按钮被挤到 0 高度看不见 (实测踩过)。
        # 🆕 2026-10-14 老倪: 「将元任务, 这些信息, 体现在配置中心的 任务配置」——
        #   任务表之下再给一张**元任务表** (每个元任务 = 一个功能 + 该功能全部配置参数),
        #   列 = 元任务标准模板; 真源同 Word/PDF 导出器 (同一份构建函数)。
        #   ⚠️ 上面任务表的列一列没动 (只增一张表, 不换列)。
        # ── 任务表 ↔ 元任务表: 一条**可拖的竖直分隔条** (老倪 2026-10-15「元任务窗口太矮了, 调高适配」) ──
        #   实测根因(离屏 1700×1700): 两张表同在一个 QVBoxLayout 里, 谁都没有边界 ⇒ 元任务表只拿到 463px,
        #   75 行里看到 19 行; 老倪想多看也**拉不动**(没有可拖的控件)。改法:
        #     ① 两表各自装进一个容器, 中间夹 QSplitter(Vertical), 9px 手柄可拖;
        #     ② 初值按实测给 [552, 600]: 552 = 任务表 7 行真实行高(不能少, 少了自己那张表就要滚),
        #        剩下给元任务表 (600px ≈ 25 行可见, 原来 19 行); 想全看 75 行直接把手柄往下拖。
        #     ③ 子项不可折叠 (拖到 0 会把表藏掉, 老倪会以为"又不见了")。
        try:
            _upper = QWidget()
            _ul = QVBoxLayout(_upper)
            _ul.setContentsMargins(0, 0, 0, 0)
            _ul.setSpacing(4)
            _ul.addWidget(self.tasks_table, 1)
            _ul.addLayout(row2)
            _meta_box = QWidget()
            self._meta_box = _meta_box          # 舱引用 (2026-10-28: 三张表按实际行数重算舱高, 见 _fit_meta_box)
            _ml = QVBoxLayout(_meta_box)
            _ml.setContentsMargins(0, 0, 0, 0)
            _ml.setSpacing(4)
            self.meta_table = None
            try:
                self._build_meta_block(_ml, th)
            except Exception as _e:                                             # noqa: BLE001
                _lb = QLabel("⛔ 元任务表构建失败: %r (上面任务表照常可用)" % (_e,))
                _lb.setStyleSheet("color:%s;background:transparent;" % th["C_RED"])
                _lb.setWordWrap(True)
                _ml.addWidget(_lb)
            self.tm_split = QSplitter(Qt.Vertical)
            self.tm_split.setChildrenCollapsible(False)          # 拖不到 0 (拖没了会被当成"又看不见了")
            self.tm_split.setHandleWidth(9)
            self.tm_split.addWidget(_upper)
            self.tm_split.addWidget(_meta_box)
            # ⚠️ 关键(实测踩过): 只调 setSizes **没用** —— Qt 会按比例把它缩回去 (给 [552,600] 结果元任务表
            #   还是 464px, 和改前一样)。要让两张表都"够看", 必须把两边的**够看高度写成最小高度**:
            #     上舱 = 任务表 7 条真实行高 (self.tasks_table.minimumHeight(), 昨天刚修好不能回退) + 48px 启动按钮行;
            #     下舱 = 元任务表 (22px 行高) 尽量给到 ~638px 表高 ⇒ ≈29 行可见 (改前只有 19 行), 封顶 700。
            #   两舱最小高度之和 > 页面视口 ⇒ 页面整体要滚一点 (老倪 2026-10-15 明确接受"每页可滚动"),
            #   但两张表**表内都不滚**(任务 7/7 · 元任务 29/75), 而且中间那条 9px 手柄随时可拖着重分。
            _tneed = 552
            try:
                _tneed = max(300, int(self.tasks_table.minimumHeight()))
            except Exception:                                                   # noqa: BLE001
                pass
            #   +420 = 🎯 任务级元任务表 (≤400) 与 ↳ 段级明细表 (≤383) 都要装进下舱 (2026-10-28 第二轮)
            _mneed = 1040
            #   1040 = 任务级表 ≤400 + 段级表 ≤383 + 两个表头/说明 + 功能级元任务表地板 260
            #   (三张表同舱 ⇒ 页面整体滚动, 老倪已接受; 中间 9px 分隔条随时可拖)
            _mneed = max(360, _mneed)
            _upper.setMinimumHeight(_tneed + 48)
            _meta_box.setMinimumHeight(_mneed)
            self.tm_split.setSizes([_tneed + 48, _mneed])
            self.tm_split.setToolTip("↕ 拖这条分隔条: 上面=任务表 (7 条任务, 行高 67px) · "
                                     "下面=元任务表 (75 条元任务, 行高 22px)\n"
                                     "↓ 往下拖 = 元任务表更高 (全部 75 行要看时把上面压到最小, 表内再滚)")
            l.addWidget(self.tm_split, 1)
            try:                     # 老倪自己拖过 ⇒ 记下来, 不再被自动覆盖 (与底部信息窗同一套口径)
                self.tm_split.splitterMoved.connect(self._on_tm_split_moved)
            except Exception:                                                   # noqa: BLE001
                pass
        except Exception as _esp:                                               # noqa: BLE001
            self.tm_split = None
            l.addWidget(self.tasks_table, 1)
            _lbs = QLabel("⛔ 任务表/元任务表分隔条构建失败: %r (退回两表各占一半)" % (_esp,))
            _lbs.setStyleSheet("color:%s;background:transparent;" % th["C_RED"])
            _lbs.setWordWrap(True)
            l.addWidget(_lbs)
        self.tabs.addTab(_scrollable(w, th), "📋 任务配置")
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
            self.eng_profile_card = self._eng_profile_block(th)
            self.ar_pts_panel = QWidget(); _l2p = QVBoxLayout(self.ar_pts_panel)
            _l2p.setContentsMargins(0, 0, 0, 0); _l2p.addWidget(self.eng_profile_card)
            l2.addWidget(self.ar_pts_panel)
        except Exception as _ee:                                                # noqa: BLE001
            self.eng_profile_card = None
            l2.addWidget(QLabel("⛔ 工程配置(A/B/C)块构建失败: %r" % (_ee,)))
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
        self.tabs.addTab(_scrollable(w2, th), "⚙️ 工程配置")

        # 3) 功能配置 (天玑) + 5) 性能配置 (玉衡) —— 老倪 2026-10-15: 「功能 性能 模型 标签, 改成功能配置,
        #    即标签页的名字, 对应 1~7 配置名称」⇒ 页签名就叫配置名, 所以这里建**两个页** (同一构造器、默认域不同):
        #    🧩 功能配置 默认只筛功能域 · ⚡ 性能配置 默认只筛性能域。数据同一真源 (特征库), 不复制真相。
        self.fpm_views = {}
        self.tab3_domains = ["功能配置", "性能配置", "模型配置"]
        # 🎯 2026-10-28 老倪: 「当前激活的是 任务7, 功能上要将任务7的任务都对应上; 功能配置的UI 你再设计一下;
        #    在功能配置页面, 要提示 当前的活跃任务, 随即显示当前活跃任务的功能配置」
        #    ⇒ 功能配置页改成「活跃任务驱动」版: 活跃任务横幅 + 元任务编排 + 段→功能覆盖 + 本任务功能明细(可过滤) + 参数明细
        _v_func = self._build_func_active_view(th, d)
        try:                     # 2026-10-15 老倪: 「功能配置, 要包括 系统1 系统2 系统0 的所有功能,
            _v_func["lay"].addWidget(self._functions_block(th), 3)   # 还有功能清单的汇总」
        except Exception as _ef:                                                # noqa: BLE001
            _v_func["lay"].addWidget(QLabel("⛔ 功能清单块构建失败: %r" % (_ef,)))
        _v_perf = self._build_fpm_view(th, d, self.tab3_domains, "性能配置", "⚡ 性能配置")
        # ⚡ 性能配置也按活跃任务来 (老倪 2026-10-28「模型配置 性能配置」同一口径): 横幅 + 该任务的节拍/KPI
        try:
            _v_perf["lay"].insertWidget(0, self._active_banner(th, "性能配置"))
            # 老倪 2026-10-28: 「性能指标太多了, 就要一张表」⇒ 只留整合表, 旧的 KPI 块/三档表/能力边界块全部下线
            _v_perf["lay"].insertWidget(1, self._perf_one_table(th))
        except Exception as _ep:                                                # noqa: BLE001
            _v_perf["lay"].insertWidget(0, QLabel("⛔ 性能横幅/指标块构建失败: %r" % (_ep,)))
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
        _h4 = QLabel("工单实例 = 一次执行 (身份/配方/变体/选项/目标/站点就绪) · 真源 %s"
                     " · 点一行看完整配置面" % os.path.relpath(ORDERS_D, ROOT))
        _h4.setFont(QFont("Consolas", 10))
        _h4.setStyleSheet("color:%s;background:transparent;" % th["C_GRAY"])
        _h4.setWordWrap(True)
        l4.addWidget(_h4)
        r4 = QHBoxLayout()
        for txt, fn in (("📋 工单列表", lambda: self._run_into("orders")),
                        ("🧾 工单明细(选中)", lambda: self._order_from_row(t4))):
            b4 = _btn(txt, th)
            b4.clicked.connect(lambda _=False, f=fn: f())
            r4.addWidget(b4)
        r4.addStretch(); l4.addLayout(r4); l4.addWidget(t4, 1)
        # 🔁 2026-10-19 老倪: 「将工单，放到文档配置选项卡」⇒ 不再单开「🧾 工单配置」页签,
        #    整块 (表 + 按钮 + 点行看明细) 搬进第七阵「📄 文档配置」页里 (见下面 l7 的嵌入)。
        self._w4_orders = w4

        # 5) 模型 × 工程配置
        m = _j(MATCH_J, {}) or {}
        keys = (m.get("_meta", {}).get("site_keys") or [])
        rows5 = [[r["model"], r["layer"], r["domain"],
                  " ".join("✅" if r["cells"].get(k) == "OK" else
                           ("⛔" if r["cells"].get(k) == "缺项" else "·") for k in keys),
                  "✅" if r["usable_now"] else "⛔ " + r.get("verdict", "")[:40]]
                 for r in m.get("MODELS", [])]
        t5 = _mk_table(["模型", "层", "域", "工程配置(9 项)", "判定"], rows5, th)
        self.match_table = t5
        # 6) 🧠 模型配置 = 现有模型配置页 + 「模型 ↔ 工程配置」匹配表
        #    2026-10-15 老倪: 「取消 模型匹配, 信息合并到 模型配置页面」⇒ 不再单列页签, 一张页看全。
        w6 = QWidget(); l6 = QVBoxLayout(w6); l6.setContentsMargins(6, 6, 6, 6)
        self._th = th
        # 🎯 2026-10-28 老倪: 「根据元任务的编排, 继续完成 功能配置 模型配置 性能配置」⇒ 模型配置也挂活跃任务横幅,
        #    下面的「功能 → 层模型」映射默认只列**本任务的功能**(33 条), 一键切回 77 条全量。
        try:
            l6.addWidget(self._active_banner(th, "模型配置"))
            _mrow = QHBoxLayout()
            _b_task = _btn("仅本任务功能", th)
            _b_all = _btn("全部", th)
            _mrow.addWidget(_b_task); _mrow.addWidget(_b_all); _mrow.addStretch()
            _mlab = QLabel()
            _mlab.setFont(QFont("Consolas", 9))
            _mlab.setStyleSheet("color:%s;background:transparent;" % th["C_GRAY"])
            _mrow.addWidget(_mlab)
            l6.addLayout(_mrow)
            self._ml_filter_row, self._ml_filter_label = _mrow, _mlab

            def _ml_filter(only_task):
                """只筛显示行, 不动表内容; 条数一律按**表里真实有多少**报, 不写死 77/33。"""
                _t2, _tk2, _bt2, _ = _active_bind()
                _fn = {f["fn"] for f in _task_funcs(_t2)}
                t = getattr(self, "ml_map_table", None)
                if t is None:
                    return
                ids = [((t.item(r, 0).text() if t.item(r, 0) is not None else "")) for r in range(t.rowCount())]
                n_int = len([i for i in ids if i in _fn])          # 本任务功能里有层模型映射的
                n_all = len(ids)
                _b_task.setText("仅本任务 %d" % n_int)
                _b_all.setText("全部 %d 条" % n_all)
                n_on = 0
                for r, fid in enumerate(ids):
                    on = (not only_task) or (fid in _fn)
                    t.setRowHidden(r, not on)
                    n_on += 1 if on else 0
                t.setMinimumHeight(min(460, 28 * (min(n_on, 16) + 2) + 8))
                _miss = sorted(_fn - set(ids))
                _mlab.setText("显示 %d / %d 条 · %s%s"
                              % (n_on, n_all,
                                 ("仅活跃任务 %s 的功能" % _t2) if only_task else "全部功能",
                                 (" · ⚠ 本任务 %d 个功能里 %d 个在层模型映射表没有条目: %s (真源缺口)"
                                  % (len(_fn), len(_miss), "/".join(_miss))) if _miss else ""))

            _b_task.clicked.connect(lambda: _ml_filter(True))
            _b_all.clicked.connect(lambda: _ml_filter(False))
            # 建完映射表后再按活跃任务筛一次 (表对象在 _model_layer_block 里才创建)
            QTimer.singleShot(0, lambda: _ml_filter(True))
        except Exception as _em:                                                # noqa: BLE001
            l6.addWidget(QLabel("⛔ 模型配置活跃任务横幅构建失败: %r" % (_em,)))
        # 🧠 **本页主要信息** (老倪 2026-10-15: 「模型配置, 要映射功能配置和 L2 L3 L4 L5层模型, 这是主要信息」)
        #    —— 放在模型配置页最上面: 四层在役一行一层 + 功能↔层模型全量映射 (两个真源现算)。
        try:
            self.ml_block = self._model_layer_block(th)
            l6.addWidget(self.ml_block, 4)
        except Exception as _e6m:                                                   # noqa: BLE001
            self.ml_block = None
            _be6 = QLabel("⛔ 层模型映射块构建失败: %s" % _e6m)
            _be6.setWordWrap(True)
            l6.addWidget(_be6)
        _h6 = QLabel("模型匹配 (模型 ↔ 工程配置 9 项) —— 原「🧠 模型匹配」页, 已并入本页 (老倪 2026-10-15)")
        _h6.setWordWrap(True)
        _h6.setFont(QFont("Consolas", 10))
        _h6.setStyleSheet(f"color:{th['C_GRAY']};background:transparent;")
        l6.addWidget(_h6)
        if model_page is not None:
            l6.addWidget(model_page, 3)          # 现有模型配置页整块搬进来 (不重写)
        else:
            _lb6 = QLabel("⛔ 模型配置页未注入 (调用方没传 model_page) —— 本页只显示匹配表")
            _lb6.setWordWrap(True)
            l6.addWidget(_lb6)
        l6.addWidget(t5, 2)
        self.tabs.addTab(_scrollable(w6, th), "🧠 模型配置")

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

        # ── 以下三块: 2026-10-19 老倪「将工单，放到文档配置选项卡，将成本/报价 商业模式的内容，都迁移到 文档配置里」
        #    它们都不是独立配置面 (工单实例 = 一次执行的记录 / 成本报价 = 从配置算出来的账 /
        #    商业模式 = 从成本与配置导出的商业方案) ⇒ 统一收在第七阵 瑶光·文档配置(定记录) 之下。
        def _sec(title, tip=""):
            _s = QLabel("─" * 12 + "  " + title)
            _s.setWordWrap(True)
            _s.setFont(QFont("Consolas", 10, QFont.Bold))
            _s.setStyleSheet("color:%s;background:transparent;"
                             % th.get("C_ACCENT", th.get("C_WHITE", "#e6edf3")))
            if tip:
                _s.setToolTip(tip)
            return _s

        l7.addWidget(_sec("🧾 工单实例（原「🧾 工单配置」页）",
                          "工单 = 一次执行 (Build Sheet) · 真源 config/orders/BS_*.json · 点行看完整配置面"))
        l7.addWidget(getattr(self, "_w4_orders", QWidget()), 2)
        try:
            l7.addWidget(_sec("💰 成本/报价",
                              "算法真源 tools/cost_model.py · 参数真源 config/platform/zmax_cost_model.json"))
            l7.addWidget(self._cost_page(th))
        except Exception as _e10b:                                              # noqa: BLE001
            _lb10b = QLabel("⛔ 成本/报价块构造失败: %r" % (_e10b,))
            _lb10b.setWordWrap(True)
            l7.addWidget(_lb10b)
        try:
            l7.addWidget(_sec("🧩 商业模式",
                              "算法真源 tools/business_model.py (输入 = 成本真源 + 商业模式假设真源)"))
            l7.addWidget(self._biz_page(th))
        except Exception as _e11b:                                              # noqa: BLE001
            _lb11b = QLabel("⛔ 商业模式块构造失败: %r" % (_e11b,))
            _lb11b.setWordWrap(True)
            l7.addWidget(_lb11b)

        self.tabs.addTab(_scrollable(w7, th), "📄 文档配置")

        # 8) 文档预览 —— 2026-10-15 老倪: 「取消文档预览页面, 合并到 文档配置页面」
        #    ⇒ 不再单开页签: 预览控件直接进上面那张「📄 文档配置」页 (同一页: 上面导出/清单, 下面正文)
        l8 = l7
        # ⚠️ 2026-10-19: 原来这里是 QLabel("─" * 96) —— 96 个字宽把整页最小宽度顶到 1632px,
        #   QTabWidget 取各页最小宽度的最大值 ⇒ 窗口 1280/1400 宽时**每一页**都被撑出可视区
        #   (判据 verify_zmax_open_flow 量到「启动按钮右边缘 1641 > 页宽 1280」)。装饰线改用 QFrame,
        #   不参与最小宽度计算 (判据口径: 界面不许挤/不许截断)。
        _sep8 = QFrame()
        _sep8.setFixedHeight(1)
        _sep8.setStyleSheet(f"background:{th['C_BORDER']};border:none;")
        l8.addWidget(_sep8)
        self.pv_head = QLabel("文档正文预览 — 点一份文档按钮即可在这里看到**实际内容** "
                              "(本节原为独立「📄 文档预览」页, 已并入本页)")
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
        # 📜 专利 (老倪 2026-10-15: 「文档配置 增加专利 导出和预览功能, 通 SOR 项目立项, 等文档同级别」)
        #    —— 放在三份文档按钮之下、共用同一个预览窗: 四类文档 (SOR/立项/协议/专利) 同页同级。
        self._th = th
        try:
            self.pat_block = self._patent_block(th)
            l8.addWidget(self.pat_block)
        except Exception as _e8p:                                                   # noqa: BLE001
            self.pat_block = None
            _lb8p = QLabel("⛔ 专利文档块构造失败: %r" % (_e8p,))
            _lb8p.setWordWrap(True)
            l8.addWidget(_lb8p)
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

        # 9) 🏷 产品配置 (2026-10-13 老倪: 流形引擎是系统核心 ⇒ 产品标识 550A/B/C + 空间质数结构化理解能力)
        #    加在**末尾**: 保持既有页签序号不变 (「记住上次那一页」存的是序号 zmax_data/cc_last_tab.txt)
        w9 = QWidget()
        l9 = QVBoxLayout(w9)
        l9.setContentsMargins(6, 6, 6, 6)
        try:
            # 🗑 2026-10-19 老倪: 「(与主控制台左侧同源: config/platform/zmax_platform.json) 在主配置中心，删掉」
            #    这个 🏭 平台块与主控制台左侧卡面完全重复 ⇒ 配置中心不再挂它 (主控制台左侧照旧, 单一真源未动)。
            l9.addWidget(self._product_card(th))
            try:                   # 🏭 复用「Z-MAX 平台」页描述 + 产品特性清单 (老倪 2026-10-15)
                self.plat_page_block = self._zmax_platform_page_block(th)
                l9.addWidget(self.plat_page_block, 1)
            except Exception as _e9q:                                           # noqa: BLE001
                self.plat_page_block = None
                _lb9q = QLabel("⛔ Z-MAX 平台页描述块构造失败: %r" % (_e9q,))
                _lb9q.setWordWrap(True)
                l9.addWidget(_lb9q)
        except Exception as _e9:                                                # noqa: BLE001
            _lb9 = QLabel("⛔ 产品配置区构造失败: %r" % (_e9,))
            _lb9.setWordWrap(True)
            l9.addWidget(_lb9)
        l9.addStretch()
        self.tabs.addTab(_scrollable(w9, th), "🏷 产品配置")

        # 10) 💰 成本/报价 · 11) 🧩 商业模式 —— 2026-10-19 老倪: 「将成本/报价 商业模式的内容，都迁移到 文档配置里」
        #     ⇒ 两个**独立页签取消**, 内容整块嵌进上面「📄 文档配置」页 (l7) 的「工单实例」之后。
        #     理由 (与阵法一致, 不是随便挪): 成本/报价 = 从配置算出来的账, 商业模式 = 从成本与配置导出的方案,
        #     二者都是**记录与导出** ⇒ 归第七阵 瑶光·定记录。原页构造器 _cost_page()/_biz_page() 一行没改,
        #     仍是唯一算法入口 (tools/cost_model.py / tools/business_model.py), 不存在第二套公式。
        self._apply_tab_order()          # ⭐ 页签次序 = 北斗次序 (老倪 2026-10-15)
        # 🆕 2026-10-21 老倪: 「配置中心 打开的时候, 应该先显示 产品配置」
        #   ⇒ 初始页**固定**为第一阵「🏷 产品配置」; 「记住上次那一页」不再回放
        #     (文件照旧随浏览写, 只是不再拿它决定打开哪一页 —— 否则回来会落在随便哪一页)。
        _pi = self._tab_index_by_title("产品配置")
        if _pi >= 0:
            self.tabs.setCurrentIndex(_pi)
            # setCurrentIndex 若是"原地不动"(索引没变) 不会发 currentChanged ⇒ 左树对号不会自己刷,
            # 这里显式刷一次, 保证打开那一刻 ✅ 就落在「产品配置」行。
            try:
                self._mark_tree_current()
            except Exception:                                                   # noqa: BLE001
                pass
        # 🆕 2026-10-12: 记住上次看的那一页 (留档用; 2026-10-21 起不参与"打开哪一页")
        try:
            _mk = os.path.join(ROOT, "zmax_data", "cc_last_tab.txt")
            # ⛔ 回放已停用 (老倪 2026-10-21: 打开先看产品配置) —— 原逻辑保留注释, 免得下次"又加回来":
            #   _v = open(_mk).read().strip(); _i = ... ; if 0 <= _i < count: setCurrentIndex(_i)
            #   现在只写不读。
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
    def _functions_block(self, th):
        """🧮 功能清单 (系统 2 / 系统 1 / 系统 0 + 平台支撑 的全部功能) + 汇总。

        老倪 2026-10-15: 「功能配置, 要包括 系统1 系统2 系统0 的所有功能, 还有功能清单的汇总」。
        真源 = 单一工程库 functions 表 (与人可编真源 config/platform/zmax_platform.json 同源);
        汇总口径: 各系统条数 + 合计, 一个字都不写死。
        """
        try:
            from zmax_platform_info import platform_page_data as _ppd, function_summary as _fs
        except Exception:                                                       # noqa: BLE001
            return QLabel("⛔ 功能清单: zmax_platform_info 不可用 (取不到)", )
        _d = _ppd()
        _fns = _d.get("functions") or []
        _sm = _fs(_fns)
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(4)
        _hd = QLabel("🧮 功能清单汇总: %s  (真源: 单一工程库 functions 表 · 与主控制台「🏭 Z-MAX 平台」页同源)"
                     % (_sm["text"] if _fns else "取不到"))
        _hd.setWordWrap(True)
        _hd.setFont(QFont("Consolas", 10))
        _hd.setStyleSheet(f"color:{th['C_YELLOW']};background:transparent;")
        _hd.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(_hd)
        _cn = {"sys2": "系统 2 · 认知决策", "sys1": "系统 1 · 动作执行",
               "sys0": "系统 0 · 基石执行", "plat": "平台支撑"}
        _rows = [[_cn.get(f["sys"], f["sys"]), f["fn_id"], f["name"], f["layer"], f["kind"],
                  (f["module"] or "")[:44]] for f in _fns]
        # 老倪 2026-10-15: 「预留所有功能的专利申请渠道」⇒ 功能清单表直接带「专利渠道」列
        #   (主挂专利号 / 未挂则明写"渠渠道未闭合", 不隐藏 —— 渠道要看得见才算预留)
        _pat = {}
        try:
            import patent_center as _pcm                                                # noqa: PLC0415
            for _x in _pcm.coverage()["per_fn"]:
                _pat[_x["fn_id"]] = _x
        except Exception:                                                               # noqa: BLE001
            _pat = {}
        self.fn_pat_map = _pat
        _rows = [list(r) + [("/".join(_pat.get(r[1], {}).get("pat_primary") or [])
                             or ("关联 " + "/".join(_pat.get(r[1], {}).get("pat_related") or []))
                             or "⛔ 渠道未闭合")] for r in _rows]
        self.fn_table = _mk_table(["系统", "功能编号", "功能名称", "层", "类别", "承载模块", "专利渠道 (主挂/关联)"], _rows, th)
        # 同一类问题的预防: 74 行功能清单也要给足最小高度 (封顶 460, 约 15 行可见, 其余表内滚动),
        # 不许被上方/下方挤成"两行都看不见" (老倪 2026-10-15 报的是产品配置页, 这里是同一写法)。
        self.fn_table.setMinimumHeight(min(460, 28 * (len(_rows) + 2) + 8))
        lay.addWidget(self.fn_table, 1)
        # 📜 专利渠道 (老倪 2026-10-15: 「预留所有功能的专利申请渠道」) —— 每个功能都能一键出专利草稿
        _pr = QHBoxLayout()
        _bp1 = _btn("📜 该功能专利申请草稿 (预览)", th)
        _bp1.setToolTip("选中功能清单里的一行 → 打开它主挂专利的申请文件正文 (说明书/权利要求书/实施例)")
        _bp1.clicked.connect(self._show_function_patent)
        _bp2 = _btn("📋 复制功能↔专利渠道清单", th)
        _bp2.setToolTip("全量 74 条功能的专利渠道 (主挂/关联/真源符号) 复制到剪贴板")
        _bp2.clicked.connect(self._copy_patent_channels)
        _bp3 = _btn("📤 导出全部专利 (md+docx)", th)
        _bp3.setToolTip("12 件专利申请文件全部导出到 docs/patents/ (与 SOR/立项/协议同一交付目录体系)")
        _bp3.clicked.connect(lambda: self._export_patent(single=False))
        for _b in (_bp1, _bp2, _bp3):
            _pr.addWidget(_b)
        _pr.addStretch()
        lay.addLayout(_pr)
        return w

    # ══════════════════════════════════════════════════════════════════════════
    # 📜 专利 (老倪 2026-10-15: 「预留所有功能的专利申请渠道; 文档配置 增加专利 导出和预览功能,
    #     同 SOR 项目立项 等文档同级别; 根据现有状态空间工程, 设计专利申请的内容, 要有层次, 逻辑,
    #     要保证全局数据真实, 可靠, 能落地, 形成专有知识产权」)
    #   真源 config/patents/patent_registry.json (每件专利挂 fn_ids/fn_ids_related);
    #   覆盖核对 = 与工程库 functions 表逐条比 (74/74); 文档 = tools/patent_center.py 生成 md+docx。
    # ══════════════════════════════════════════════════════════════════════════
    def _pc(self):
        """专利中心模块 (延迟 import, 缺了不影响别的页)。"""
        try:
            if getattr(self, "_pc_mod", None) is None:
                import patent_center as _m                                             # noqa: PLC0415
                self._pc_mod = _m
            return self._pc_mod
        except Exception:                                                              # noqa: BLE001
            return None

    def _patent_block(self, th):
        """📜 专利文档块: 12 件清单 + 覆盖统计 + 预览/导出 (与 SOR/立项/合作协议 同一页同一级别)。"""
        m = self._pc()
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(4)

        def _hd(txt, color=None, size=10):
            _l = QLabel(txt)
            _l.setWordWrap(True)
            _l.setFont(QFont("Consolas", size))
            _l.setStyleSheet("color:%s;background:transparent;" % (color or th["C_YELLOW"]))
            return _l
        if m is None:
            _e = QLabel("⛔ 专利中心模块 (tools/patent_center.py) 没加载上 —— 专利页签/导出不可用")
            _e.setWordWrap(True)
            lay.addWidget(_e)
            self.pat_table = None
            return w
        try:
            cov = m.coverage()
            reg = m.load_registry()
        except Exception as _e:                                                        # noqa: BLE001
            lay.addWidget(QLabel("⛔ 读专利真源失败: %r" % (_e,)))
            self.pat_table = None
            return w
        _ch = 100.0 * cov["covered"] / max(1, cov["total_fn"])
        self.pat_cov = cov
        lay.addWidget(_hd("📜 专利文档 (与 SOR / 项目立项 / 合作协议 **同一级别**) —— 真源 %s" % cov["src"]))
        lay.addWidget(_hd("   渠道预留: 功能清单 %d 条 → 已挂专利 %d 条 (%.1f%%)%s | 专利 %d 件 (按层次: %s)"
                         % (cov["total_fn"], cov["covered"], _ch,
                            "" if not cov["uncovered"] else " · ⛔ 未挂 %d 条: %s"
                            % (len(cov["uncovered"]), ",".join(cov["uncovered"][:6])),
                            cov["n_patent"],
                            " · ".join(sorted({p.get("layer", "—") for p in reg.get("patents", [])}))),
                         th["C_GRAY"], 9))
        _rows = []
        for p in reg.get("patents", []):
            _out = os.path.join("docs", "patents")
            _base = "%s_%s" % (p["pat_id"], m._safe(p["title"])[:48])
            _md = os.path.join(ROOT, _out, _base + ".md")
            _dx = os.path.join(ROOT, _out, _base + ".docx")
            _st = ("✅ %s" % time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(_md)))) if os.path.exists(_md) else "⛔ 未生成"
            _rows.append([p["pat_id"], p["title"], p.get("layer", ""), p.get("codename", ""),
                          p.get("status", ""), "%d / %d" % (len(p.get("fn_ids") or []), len(p.get("fn_ids_related") or [])),
                          _st, ("docx ✅" if os.path.exists(_dx) else "docx ✗")])
        self.pat_table = _mk_table(["专利编号", "名称", "层次", "代号", "状态", "主挂/关联功能", "文件 (md)", "docx"], _rows, th)
        self.pat_table.setMinimumHeight(min(380, 30 * (len(_rows) + 2) + 8))
        for i, p in enumerate(reg.get("patents", [])):
            self.pat_table.item(i, 1).setToolTip(p.get("abstract", ""))
            self.pat_table.item(i, 5).setToolTip("主挂: %s\n关联: %s" % (",".join(p.get("fn_ids") or []),
                                                                        ",".join(p.get("fn_ids_related") or [])))
        self.pat_table.itemSelectionChanged.connect(lambda: self._show_patent(force=False))
        lay.addWidget(self.pat_table)
        _row = QHBoxLayout()
        _b1 = _btn("📄 预览选中专利", th)
        _b1.setToolTip("读真源生成正文 (说明书摘要/权利要求书/说明书/实施例/挂载功能/真源数据) 显示在下方预览窗")
        _b1.clicked.connect(lambda: self._show_patent(force=False))
        _b2 = _btn("📤 导出选中 (md+docx)", th)
        _b2.clicked.connect(lambda: self._export_patent(single=True))
        _b3 = _btn("📤 导出全部专利", th)
        _b3.setToolTip("12 件全部导出 md + docx + 渠道总览清单 → docs/patents/")
        _b3.clicked.connect(lambda: self._export_patent(single=False))
        _b4 = _btn("📋 复制功能↔专利渠道清单", th)
        _b4.setToolTip("74 条功能逐条的专利渠道 (主挂/关联) 复制到剪贴板 → 可直接粘进 Excel/评审表")
        _b4.clicked.connect(self._copy_patent_channels)
        _b5 = _btn("♻️ 重读真源", th)
        _b5.setToolTip("改完 config/patents/patent_registry.json 后重读 (不用重启控制台)")
        _b5.clicked.connect(self._reload_patent_block)
        for _b in (_b1, _b2, _b3, _b4, _b5):
            _row.addWidget(_b)
        _row.addStretch()
        lay.addLayout(_row)
        return w

    def _show_function_patent(self):
        """📜 按功能清单里选中的一行, 打开该功能主挂专利的申请草稿 (在文档配置页的预览窗里看)。"""
        try:
            t = getattr(self, "fn_table", None)
            fid = ""
            if t is not None and t.selectedItems():
                _c = t.item(t.selectedItems()[0].row(), 1)     # 功能编号列
                fid = _c.text() if _c is not None else ""
            if not fid:
                self.out.setPlainText("提示: 先在功能清单表里点一行 (功能编号), 再点这个按钮 —— 会打开它主挂专利的草稿。")
                return
            x = (getattr(self, "fn_pat_map", {}) or {}).get(fid) or {}
            _ps = (x.get("pat_primary") or []) + (x.get("pat_related") or [])
            if not _ps:
                self.out.setPlainText("⛔ %s 的专利渠道未闭合 (真源 config/patents/patent_registry.json 里没有挂它)"
                                      " —— 渠道预留要逐条挂上, 不许留空。" % fid)
                return
            self.out.setPlainText("📜 %s (%s) → 专利 %s (主挂 %s · 关联 %s)"
                                  % (fid, x.get("name", ""), "/".join(_ps),
                                     "/".join(x.get("pat_primary") or []) or "—",
                                     "/".join(x.get("pat_related") or []) or "—"))
            self._show_patent(_ps[0])
        except Exception as _e:                                                              # noqa: BLE001
            self.out.setPlainText("⛔ 打开功能专利草稿失败: %r" % (_e,))

    def _pat_selected(self):
        """当前选中的专利号 (没选就取第一件)。"""
        m = self._pc()
        try:
            t = getattr(self, "pat_table", None)
            if t is not None:
                it = t.selectedItems()
                if it:
                    r = it[0].row()
                    c = t.item(r, 0)
                    if c is not None:
                        return c.text()
            reg = m.load_registry() if m else {}
            ps = (reg or {}).get("patents") or []
            return ps[0]["pat_id"] if ps else ""
        except Exception:                                                              # noqa: BLE001
            return ""

    def _show_patent(self, pat_id=None, force=False):
        """📄 预览专利: 没有产物先真跑导出, 再读回正文显示在预览窗 (与三份文档共用同一个预览窗)。"""
        m = self._pc()
        if m is None:
            self.out.setPlainText("⛔ 专利中心模块没加载上 (tools/patent_center.py)")
            return
        pid = pat_id or self._pat_selected()
        if not pid:
            self.out.setPlainText("⛔ 没有专利可预览 (真源里 0 件)")
            return
        try:
            self._pv_kind = "patent"
            self.pv_head.setText("📜 专利 %s · 正在生成/读取正文 …" % pid)
            QApplication.processEvents()
            if force or not self._pat_files(pid)["md"]:
                self.out.setPlainText(_run_script("patent_center.py", ["--export", pid]))
                QApplication.processEvents()
            fs = self._pat_files(pid)
            if not fs["md"]:
                txt = m.preview(pid)        # 导出失败也要能看正文 (直接由真源现算)
                self.pv_head.setText("📜 专利 %s · ⛔ 文件未落地, 下面是真源现算正文" % pid)
            else:
                txt = open(fs["md"], encoding="utf-8").read()
                cov = getattr(self, "pat_cov", None) or m.coverage()
                self.pv_head.setText(
                    "📜 专利 %s · %s\n文件 %s (生成 %s) · 渠道覆盖 %d/%d 条功能 · 真源 %s"
                    % (pid, os.path.basename(fs["md"]), fs["md"],
                       time.strftime("%m-%d %H:%M", time.localtime(fs["mtime"])),
                       cov["covered"], cov["total_fn"], cov["src"]))
            self.preview.setPlainText(txt)
            self.out.setPlainText("📜 已预览 %s (正文见下方预览窗; 导出 md+docx 点「📤 导出选中」)" % pid)
        except Exception as _e:                                                        # noqa: BLE001
            self.out.setPlainText("⛔ 预览专利 %s 失败: %r" % (pid, _e))

    def _pat_files(self, pid):
        m = self._pc()
        out = {"md": None, "docx": None, "mtime": 0}
        try:
            reg = m.load_registry()
            for p in reg.get("patents", []):
                if p["pat_id"] == pid:
                    base = "%s_%s" % (pid, m._safe(p["title"])[:48])
                    md = os.path.join(ROOT, "docs", "patents", base + ".md")
                    dx = os.path.join(ROOT, "docs", "patents", base + ".docx")
                    if os.path.exists(md):
                        out["md"], out["mtime"] = md, os.path.getmtime(md)
                    if os.path.exists(dx):
                        out["docx"] = dx
        except Exception:                                                              # noqa: BLE001
            pass
        return out

    def _export_patent(self, single=True):
        """📤 导出: 选中一件或全部 (md+docx) —— 跑真脚本, 输出回底面板 (点了必出结果)。"""
        m = self._pc()
        if m is None:
            self.out.setPlainText("⛔ 专利中心模块没加载上")
            return
        which = self._pat_selected() if single else "all"
        self.out.setPlainText("▶ 导出专利 %s (md+docx) …" % which)
        QApplication.processEvents()
        log = _run_script("patent_center.py", ["--export", which])
        self.out.setPlainText(log)
        try:                                       # 重新读一遍覆盖/文件状态, 表格立刻反映
            self._reload_patent_block(reload_only=True)
        except Exception:                                                              # noqa: BLE001
            pass

    def _copy_patent_channels(self):
        """📋 复制 74 条功能 → 专利渠道 (TSV)。"""
        m = self._pc()
        try:
            cov = m.coverage()
            hdr = ["功能编号", "功能名称", "系统", "层", "主挂专利", "关联专利", "真源符号"]
            lines = ["\t".join(hdr)]
            for x in cov["per_fn"]:
                lines.append("\t".join([x["fn_id"], x["name"], x["sys"], x["layer"],
                                         "/".join(x["pat_primary"]) or "—", "/".join(x["pat_related"]) or "—",
                                         x["symbol"] or x["module"]]))
            QApplication.clipboard().setText("\n".join(lines))
            self.out.setPlainText("📋 已复制 %d 条功能↔专利渠道 (含表头) · 覆盖 %d/%d"
                                  % (len(cov["per_fn"]), cov["covered"], cov["total_fn"]))
        except Exception as _e:                                                        # noqa: BLE001
            self.out.setPlainText("⛔ 复制专利渠道失败: %r" % (_e,))

    def _reload_patent_block(self, reload_only=False):
        """♻️ 重读专利真源: 重建专利块 (表 + 统计)。"""
        try:
            _i = self._tab_index_by_title("文档配置")
            _host = self.tabs.widget(_i)
            _page = _host.widget() if hasattr(_host, "widget") else _host
            _lay = _page.layout()
            _old = getattr(self, "pat_block", None)
            _new = self._patent_block(self._th)
            self.pat_block = _new
            if _old is not None and _lay is not None:
                _lay.replaceWidget(_old, _new)
                _old.deleteLater()
            elif _lay is not None:
                _lay.insertWidget(max(0, _lay.count() - 2), _new)
            if not reload_only:
                self.out.setPlainText("♻️ 已重读专利真源: %d 件 · 渠道 %d/%d"
                                      % (self.pat_cov["n_patent"], self.pat_cov["covered"], self.pat_cov["total_fn"]))
        except Exception as _e:                                                        # noqa: BLE001
            self.out.setPlainText("⛔ 重读专利块失败: %r" % (_e,))

    def _model_real_blocks(self, th):
        """模型配置 · 实际在役模型 ←→ 功能 (老倪 2026-10-28: 「继续 模型配置, 如何对应功能配置, 要用实际的模型」)

        ① 功能 → 实际加载物 (本任务 33 条, 一条一条对上; 权重/技能库/LLM/端点/规则代码 分类型)
        ② 模型台账 (按实际模型聚合: 权重路径 / 端点 / 大小 · 时间 / 状态 / 服务哪些功能)
        路径/大小/时间/是否存在 全部现场 stat; 依据列写明「凭什么这么对」(模块登记 / 场景登记 / 代码实现)。
        """
        import time as _t
        from zmax_platform_info import function_layer_map as _flm2
        tid, tk, bt, bd = _active_bind()
        funcs = _task_funcs(tid)
        fl = {r["fn_id"]: r for r in _flm2()["rows"]}
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 4)
        lay.setSpacing(4)

        def _hd(txt, color=None, size=10):
            _l = QLabel(txt)
            _l.setWordWrap(True)
            _l.setFont(QFont("Consolas", size))
            _l.setStyleSheet("color:%s;background:transparent;" % (color or th["C_YELLOW"]))
            return _l

        lmap, rows = {}, []
        for f in funcs:
            its = []
            try:
                its = _fn_load_items(f["fn"]) or []
            except Exception:                                                   # noqa: BLE001
                its = []
            lmap[f["fn"]] = its
            node = f.get("node") or "—"
            seen = set()
            # (a) 层模型真源声明的模型 (function_layer_map → model_links)
            for nm in ((fl.get(f["fn"]) or {}).get("models") or []):
                for kk in ((_model_links().get("links") or {}).get(nm) or []):
                    e = (_models_registry().get("ent") or {}).get(kk)
                    if not e or kk in seen:
                        continue
                    seen.add(kk)
                    ok, desc, sz, mt = _model_disk(e)
                    act = next((x for x in its if x.get("name") == (e.get("name") or kk)), None)
                    _src_basis = ("层模型 + " + (act or {}).get("basis", "")[:18]) if act else "层模型 (真源声明)"
                    if not act and its:
                        _first = next((x["name"] for x in its if x.get("kind") != "规则/数据源"), None)
                        _src_basis += (" ⚠ 与本功能实际加载(%s)不一致" % (_first or "代码/规则"))[:38]
                    rows.append([f["fn"], f["name"], e.get("layer") or f["layer"] or "—",
                                 e.get("name") or kk, node, _src_basis,
                                 e.get("path") or "—", ("%.0fMB" % (sz / 1e6)) if sz else "—",
                                 "✅ 在位" if ok else "⛔ 缺"])
            # (b) 实际加载物 (模块登记 / 场景登记 / 对齐 / 规则代码)
            for x in its:
                key = x.get("name") or ""
                if x.get("kind") == "规则/数据源":
                    rows.append([f["fn"], f["name"], f["layer"] or "—", "无权重 · 代码/规则实现", node,
                                 x.get("basis") or "—", x.get("path") or "—", "—", "✅ 在位 (代码)"])
                    continue
                if any(r[3] == key for r in rows if r[0] == f["fn"]):
                    continue
                lyr = ""
                e2 = next((e for k2, e in (_models_registry().get("ent") or {}).items()
                           if (e.get("name") or k2) == key), None)
                if e2:
                    lyr = e2.get("layer") or ""
                szx = ("%.0fKB" % (x["mb"] * 1000)) if (x.get("mb") and x["mb"] < 1) else \
                      (("%.0fMB" % x["mb"]) if x.get("mb") else "—")
                rows.append([f["fn"], f["name"], lyr or f["layer"] or "—", key, node,
                             x.get("basis") or "—", x.get("path") or "—", szx,
                             ("✅ 在位" if x["ok"] else ("⚠ 未配置" if x["kind"] in ("api", "LLM", "llm") else "⛔ 缺"))])
        self.ml_real_table = _mk_table(
            ["功能ID", "功能名称", "层", "模型名称", "状态空间节点", "来源 (凭什么这么对)", "实际文件 / 端点", "大小", "状态"],
            rows, th)
        self.ml_real_table.setWordWrap(False)
        self.ml_real_table.verticalHeader().setDefaultSectionSize(24)
        for _c, _w2 in ((0, 92), (1, 176), (2, 52), (3, 208), (5, 168), (6, 168), (7, 66), (8, 86)):
            self.ml_real_table.setColumnWidth(_c, _w2)
        self.ml_real_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.ml_real_table.setMinimumHeight(24 * len(rows) + 48)   # 全部行撑开, 不留内滚
        for _r, _row in enumerate(rows):
            for _c in (3, 4, 5, 6):
                _it = self.ml_real_table.item(_r, _c)
                if _it is not None:
                    _it.setToolTip(_row[_c])
            _st = self.ml_real_table.item(_r, 8)
            if _st is not None and "⛔" in _row[8]:
                _st.setForeground(QBrush(QColor(th["C_RED"])))
            elif _st is not None and "⚠" in _row[8]:
                _st.setForeground(QBrush(QColor(th["C_YELLOW"])))
        _hdr1 = _hd("   ① 功能 × 模型 对应 (%d 行 = 层模型声明 + 模块/场景登记的实际加载物; 每行都有 层·状态空间节点·来源)"
                    % len(rows))
        lay.addWidget(_hdr1)
        _frow = QHBoxLayout()

        def _flt(mode):
            for _r2 in range(self.ml_real_table.rowCount()):
                _src = self.ml_real_table.item(_r2, 5).text() if self.ml_real_table.item(_r2, 5) else ""
                _show = True
                if mode == "act":
                    _show = "层模型 (真源声明)" != _src.strip()
                elif mode == "layer":
                    _show = _src.startswith("层模型")
                self.ml_real_table.setRowHidden(_r2, not _show)
            _hdr1.setText("   ① 功能 × 模型 对应 (%d 行 · 过滤: %s)" %
                          (self.ml_real_table.rowCount(), {"all": "全部", "act": "仅实际加载", "layer": "仅层模型声明"}[mode]))
        for _lab, _md in (("全部", "all"), ("仅实际加载", "act"), ("仅层模型声明", "layer")):
            _b3 = _btn(_lab, th)
            _b3.clicked.connect(lambda _=False, m=_md: _flt(m))
            _frow.addWidget(_b3)
        _frow.addStretch()
        lay.addLayout(_frow)
        lay.addWidget(self.ml_real_table)

        # ② 模型台账: 按实际条目聚合
        agg = {}
        _n_code = 0
        for fid, its in lmap.items():
            if its and all(x["kind"] == "规则/数据源" for x in its):
                _n_code += 1
                continue
            for x in its:
                if x["kind"] == "规则/数据源":
                    continue
                k = x.get("name") or x.get("path") or "?"
                a = agg.setdefault(k, {"kind": x["kind"], "layer": x.get("layer") or "", "path": x.get("path") or "",
                                       "endpoint": x.get("endpoint"), "ok": x["ok"], "mb": x["mb"],
                                       "mt": x["mt"], "fns": []})
                a["fns"].append(fid)
        rows2 = []
        for k, a in agg.items():
            if a["mb"]:
                siz = ("%.0fKB" % (a["mb"] * 1000)) if a["mb"] < 1 else ("%.0fMB" % a["mb"])
            else:
                siz = "—"
            tm = _t.strftime("%m-%d %H:%M", _t.localtime(a["mt"])) if a["mt"] else "—"
            ep = a.get("endpoint")
            if a["path"]:
                loc = a["path"]
            elif isinstance(ep, dict) and ep:
                loc = "端点 " + " , ".join("%s=%s" % (kk, vv) for kk, vv in ep.items())
            elif a["kind"] in ("api", "LLM", "llm"):
                loc = "— 未配置 (走本地兜底/规则)"
            else:
                loc = "—"
            if a["ok"] and isinstance(ep, dict):
                st = "✅ 端点在位"
            elif a["ok"]:
                st = "✅ 在位"
            elif a["kind"] in ("api", "LLM", "llm"):
                st = "⚠ 未配置"
            else:
                st = "⛔ 缺"
            _lyr = (a.get("layer") or "")
            _node = " ".join(sorted({(next((x.get("node") for x in (lmap.get(_f) or []) if x.get("node")), "") or
                                     (f.get("node") or "")) for _f in a["fns"]}))[:60] or "—"
            rows2.append([k, a["kind"], _lyr, loc, siz, tm, st, "%d" % len(a["fns"]),
                          " ".join(a["fns"][:6]) + (" …" if len(a["fns"]) > 6 else "")])
        self.ml_ledger_table = _mk_table(["实际模型 / 加载物", "类型", "层", "权重路径 / 端点", "大小", "时间", "状态",
                                          "服务功能数", "服务功能"], rows2, th)
        self.ml_ledger_table.setColumnWidth(2, 46)
        self.ml_ledger_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.ml_ledger_table.setMinimumHeight(min(24 * 10 + 48, 24 * len(rows2) + 48))
        lay.addWidget(_hd("   ② 模型台账 (按实际模型聚合: 一个模型服务哪些功能 · 权重在不在盘上; 另有 %d 个功能没有权重, 是代码/规则实现, 见①表)"
                          % _n_code))
        lay.addWidget(self.ml_ledger_table)

        # 登记了但没挂到任何功能的条目 (真源缺口, 明说)
        _used, _usedp = set(), set()
        for _its in lmap.values():
            for _x in _its:
                _used.add((_x.get("name") or "").strip())
                if _x.get("path"):
                    _usedp.add(os.path.normpath(_x["path"]))
        _orphan = []
        for _k, _e in (_models_registry().get("ent") or {}).items():
            _nm = (_e.get("name") or _k).strip()
            if _nm in _used:
                continue
            if _e.get("path") and os.path.normpath(_e["path"]) in _usedp:
                continue
            _ubs = _e.get("used_by") or []
            if any(str(u).startswith("TASK-") for u in _ubs) and not any(str(u) == tid for u in _ubs):
                continue
            _ok2, _d2, _sz2, _mt2 = _model_disk(_e)
            _orphan.append("%s [%s] %s%s" % (_k, _e.get("kind") or "—", _d2,
                                             (" · " + ((_e.get("path") or "") or "无路径")) if _e.get("path") else ""))
        if _orphan:
            lay.addWidget(_hd("   ⚠ 登记了但没挂到本任务任何功能: " + " ; ".join(_orphan), th["C_YELLOW"], 9))

        _bb = QHBoxLayout()
        _c1 = _btn("📋 复制 功能→实际模型 (TSV)", th)
        _c1.clicked.connect(lambda: QApplication.clipboard().setText(
            "\t".join(["功能ID", "功能名称", "层", "模型名称", "状态空间节点", "来源", "实际文件/端点", "大小", "状态"]) + "\n"
            + "\n".join("\t".join(str(x) for x in r) for r in rows)))
        _c2 = _btn("📋 复制 模型台账 (TSV)", th)
        _c2.clicked.connect(lambda: QApplication.clipboard().setText(
            "\t".join(["模型名称", "类型", "层", "权重路径/端点", "大小", "时间", "状态", "服务功能数", "服务功能"]) + "\n"
            + "\n".join("\t".join(str(x) for x in r) for r in rows2)))
        for _b in (_c1, _c2):
            _bb.addWidget(_b)
        _bb.addStretch()
        lay.addLayout(_bb)
        return w

    def _model_layer_block(self, th):
        """🧠 功能配置 ←→ L2/L3/L4/L5 层模型 映射 —— **模型配置页的主要信息**。

        老倪 2026-10-15: 「模型配置, 要映射功能配置和 L2 L3 L4 L5层模型, 这是主要信息。你来同步全局数据」
        真源两处 (都不手抄): ① `models/active_models.json` 各层在役指针 (L5 主指针缺 → 由
        `tools/model_inventory.py --json` 兜, 与「模型引擎」窗口同一命令) ② 工程库 `functions` 表的 layer 字段。
        两个真源改任一处, 本页与模型引擎窗口同时变 (同一函数 zmax_platform_info)。
        """
        from zmax_platform_info import layer_summary as _ls, function_layer_map as _flm, short_model_name as _smn
        ls = _ls()
        fl = _flm()
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 4)
        lay.setSpacing(4)

        def _hd(txt, color=None, size=10):
            _l = QLabel(txt)
            _l.setWordWrap(True)
            _l.setFont(QFont("Consolas", size))
            _l.setStyleSheet("color:%s;background:transparent;" % (color or th["C_YELLOW"]))
            return _l

        lay.addWidget(self._active_banner(th, "模型配置"))
        lay.addWidget(self._model_real_blocks(th))
        lay.addWidget(_hd("🧠 功能配置 ←→ L2/L3/L4/L5 层模型 —— 层视图 (改模型只改真源 %s)" % ls["src"]))
        _miss = ls.get("missing") or []
        lay.addWidget(_hd("   功能清单 %d 条 (真源 %s, layer 字段) · 层模型 %s · %s"
                          % (ls["total_fn"], fl["src_functions"], ls["src"],
                             ("主指针未登记层: %s (已用 model_inventory 兜, 见下表「模型来源」列)" % "/".join(_miss)) if _miss else "四层主指针齐全"),
                          th["C_GRAY"], 9))

        # ① 四层一行: 层 | 短职责 | 在役主模型 | 附加在役条目 | 承载功能 | 模型来源
        _L = [[r["layer"], r["role"], r["model"], r.get("version") or "—", r.get("state") or "—",
               " · ".join(r["extra"]) if r["extra"] else "—",
               "%d 条" % r["fn_count"],
               r.get("src") or "取不到"] for r in ls["rows"]]
        self.ml_layer_table = _mk_table(["层", "层职责 (干什么)", "在役主模型 (与主控制台同一份)", "版本", "状态",
                                         "附加在役 (适配层/原语/技能包)", "承载功能", "模型来源"], _L, th)
        self.ml_layer_table.setMinimumHeight(min(240, 34 * (len(_L) + 2) + 8))
        for _i, _r in enumerate(ls["rows"]):
            self.ml_layer_table.setToolTip("层模型真源: %s · 主模型全名: %s · 权重: %s\n职责: %s"
                                           % (ls["src"], _r.get("model_full") or _r["model"], _r.get("path", ""), _r.get("role_full", "")))
            self.ml_layer_table.item(_i, 2).setToolTip(str(_r.get("model_full") or _r["model"]))
            self.ml_layer_table.item(_i, 3).setToolTip("版本 %s (真源 %s)" % (_r.get("version") or "取不到", _r.get("src") or "取不到"))
            self.ml_layer_table.item(_i, 5).setToolTip("\n".join(_r["extra"]) or "—")
        lay.addWidget(_hd("   ① 四层在役 (一行一层): 主模型 = 指针/引擎清单读到的真名 · 附加 = 基座之外的适配层/原语/技能包", th["C_YELLOW"], 9))
        lay.addWidget(self.ml_layer_table)

        # ② 全量映射: 功能 → 层 → 承载模型 (74 条, 一条不漏; L4/L5 组合功能两条模型都列)
        _rows = [[r["fn_id"], _short(r["name"], n=1, sep="", w=46), r["sys"], r["layer"], r["model_text"],
                  _short(r["role"], n=1, sep="", w=44)] for r in fl["rows"]]
        self.ml_map_table = _mk_table(["功能编号", "功能名称", "系统", "层", "承载模型 (L2~L5)", "承载职责"], _rows, th)
        self.ml_map_table.setMinimumHeight(min(460, 28 * (len(_rows) + 2) + 8))
        for _i, _r in enumerate(fl["rows"]):
            self.ml_map_table.item(_i, 1).setToolTip(str(_r["name"]))
            self.ml_map_table.item(_i, 4).setToolTip(str(_r["model_text"]))
            self.ml_map_table.item(_i, 5).setToolTip(str(_r["role"]))
        lay.addWidget(_hd("   ② 全量映射 %d 条 (功能 ←→ 承载层模型; 组合层如 L4/L5 两条模型都列, 平台支撑条明写不归属)" % fl["total"],
                          th["C_YELLOW"], 9))
        lay.addWidget(self.ml_map_table, 1)

        _brow = QHBoxLayout()
        _b1 = _btn("📋 复制映射 (TSV)", th)
        _b1.setToolTip("整表 %d 条 (含表头) 复制到剪贴板, 可直接粘进 Excel/文档" % fl["total"])
        _b1.clicked.connect(lambda: QApplication.clipboard().setText(
            "\t".join(["功能编号", "功能名称", "系统", "层", "承载模型", "承载职责"]) + "\n"
            + "\n".join("\t".join(str(x) for x in r) for r in _rows)))
        _b2 = _btn("📋 复制四层在役清单 (TSV)", th)
        _b2.setToolTip("四层主模型 + 附加在役条目 + 权重 + 承载功能数, 一次复制")
        _b2.clicked.connect(lambda: QApplication.clipboard().setText(
            "\t".join(["层", "层职责", "在役主模型", "主模型全名", "版本", "状态", "权重/指针", "附加在役", "承载功能数", "模型来源"]) + "\n"
            + "\n".join("\t".join([r["layer"], r["role"], r["model"], str(r.get("model_full") or ""),
                                     str(r.get("version") or ""), str(r.get("state") or ""),
                                     str(r.get("path") or ""), " / ".join(r["extra"]), str(r["fn_count"]),
                                     str(r.get("src") or "")]) for r in ls["rows"])))
        _b3 = _btn("♻️ 重读真源", th)
        _b3.setToolTip("重新读 %s 与工程库 (改完指针/层标签不用重启)" % ls["src"])
        _b3.clicked.connect(lambda: (_reload_model_block(), None)[1])
        for _b in (_b1, _b2, _b3):
            _brow.addWidget(_b)
        _brow.addStretch()
        lay.addLayout(_brow)
        return w

    def _reload_model_block(self):
        """♻️ 重读真源: 重建层映射块 (写回同一位置, 不动其它页)。"""
        try:
            _i = self._tab_index_by_title("模型配置")
            _host = self.tabs.widget(_i)
            _page = _host.widget() if hasattr(_host, "widget") else _host
            _lay = _page.layout()
            _old = getattr(self, "ml_block", None)
            _new = self._model_layer_block(self._th)
            self.ml_block = _new
            if _old is not None:
                _lay.replaceWidget(_old, _new)
                _old.deleteLater()
            else:
                _lay.insertWidget(0, _new)
            self.out.setPlainText(self._page_out_text(self.tabs.tabText(_i)))
        except Exception as _e:                                                     # noqa: BLE001
            self.out.setPlainText("⛔ 重读层映射块失败: %s" % _e)

    def _zmax_platform_page_block(self, th):
        """🏭 「Z-MAX 平台」页那两块表: 平台产品 + **产品特征清单(产品特性)**。

        老倪 2026-10-15: 「产品配置页面, 要复用 Z-MAX 平台的页面描述, 里面有产品特性」
        ⇒ 与 tools/gui/platform_spec.py 的「🏭 Z-MAX 平台」页读同一批真源 (工程库 platform/products/
        product_features), 列也对齐, 不手抄。
        """
        try:
            from zmax_platform_info import platform_page_data as _ppd
        except Exception:                                                       # noqa: BLE001
            return QLabel("⛔ 平台页数据: zmax_platform_info 不可用 (取不到)")

        def _sec(txt):
            lb = QLabel(txt)
            lb.setWordWrap(True)
            lb.setFont(QFont("Consolas", 10))
            lb.setStyleSheet(f"color:{th['C_YELLOW']};background:transparent;")
            lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
            return lb

        _d = _ppd()
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(4)
        _p = _d.get("platform") or {}
        _lb = QLabel("🏭 平台描述 (同源: 工程库 platform 表)\n   定位: %s\n   架构: %s\n   数据契约: %s"
                     % (_p.get("positioning") or "取不到", _p.get("architecture") or "取不到",
                        _p.get("data_contract") or "取不到"))
        _lb.setWordWrap(True)
        _lb.setFont(QFont("Consolas", 9))
        _lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
        _lb.setStyleSheet(f"color:{th['C_GRAY']};background:transparent;")
        lay.addWidget(_lb)
        _pr = [[x["id"], x["name"], x["category"], (x["positioning"] or "")[:56],
                " · ".join("%s=%s" % (k, v) for k, v in list((x["kpi"] or {}).items())[:3])]
               for x in _d.get("products") or []]
        lay.addWidget(_sec("🏷 平台产品 (%d) —— 产品通过 系统2/1/0 组成的全系统实现" % len(_pr)))
        self.plat_prod_table = _mk_table(["产品", "名称", "类别", "定位", "关键指标"], _pr, th)
        # 2026-10-15 老倪: 「产品特征清单 平台产品的窗口太小了, 根本看不到」⇒ 不再用 maximumHeight 压它,
        # 给一个**够看的**最小高度 (按行数算, 封顶 200) —— 少到 2 行也要看得见表头和数据行。
        self.plat_prod_table.setMinimumHeight(min(200, 34 * (len(_pr) + 2) + 8))
        lay.addWidget(self.plat_prod_table)
        _ft = [[f["pf_id"], f["product"], f["title"], f["capability"], f["kpi"], f["status"],
                "/".join(f["subsys"] or []), "、".join((f["modules"] or [])[:2])]
               for f in _d.get("features") or []]
        _on = sum(1 for f in (_d.get("features") or []) if f["status"] == "在役")
        lay.addWidget(_sec("🎯 产品特征清单 (产品特性) 共 %d 条 · 在役 %d —— 特征 → 子系统 → 模块 → 能力"
                           % (len(_ft), _on)))
        self.plat_feat_table = _mk_table(["特征ID", "产品", "产品特征", "能力", "指标 KPI", "状态", "子系统", "模块"],
                                         _ft, th)
        # 2026-10-15 老倪「产品特征清单 平台产品的窗口太小了, 根本看不到」⇒ 给足最小高度 (当时封顶 460px);
        # 2026-10-15 第二轮 老倪「窗口也是太矮了, 调高适配, 优化UI」—— 实测 460px 只显示 **13/23 行**
        #   (30px 行高), 要一屏看全 23 行需 ≈758px ⇒ 把**天花板从 460 抬到 760** (按行数算, 不够 23 行时按实际)。
        #   代价(如实说明): 本页固定内容 124+437+平台描述/按钮 ≈ 700px, 所以页面整体要高过视口 →
        #   外层 QScrollArea 需要滚一点; 但表内 23 行**一次看全**(表内滚动条=0), 比"表矮+表内翻"强。
        self.plat_feat_table.setMinimumHeight(min(760, 30 * (len(_ft) + 2) + 8))
        lay.addWidget(self.plat_feat_table, 1)
        _rowcp = QHBoxLayout()
        _bcp = _btn("📋 复制产品特性清单 (TSV)", th)
        _bcp.setToolTip("把 %d 条产品特性整表复制到剪贴板 (可直接粘进 Excel/文档)" % len(_ft))
        _bcp.clicked.connect(lambda: QApplication.clipboard().setText(
            "\t".join(["特征ID", "产品", "产品特征", "能力", "指标 KPI", "状态", "子系统", "模块"]) + "\n"
            + "\n".join("\t".join(str(x) for x in _r) for _r in _ft)))
        _rowcp.addWidget(_bcp)
        _rowcp.addStretch()
        lay.addLayout(_rowcp)
        return w

    # ══════════════════════════════════════════════════════════════════════════
    # ⚡ 性能配置 · 唯一一张表 (老倪 2026-10-28: 「性能指标太多了, 就要一张表,
    #    保留 性能指标/值/对应的模型/对应的功能层级; 要为产品成本组成提供参考,
    #    要能看出来 基本性能、精细操作的性能、专业性能」)
    #    真源: tools/spec/perf_bands.json —— 三档 (基本A/L2 · 精细B/L2+L3 · 专业C/L2+L3+L4含L5)
    # ══════════════════════════════════════════════════════════════════════════
    def _perf_one_table(self, th):
        PJ = os.path.join(ROOT, "tools", "spec", "perf_bands.json")
        try:
            spec = json.load(open(PJ, encoding="utf-8"))
        except Exception:                                                       # noqa: BLE001
            spec = {"bands": []}
        bands = spec.get("bands") or []

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 4)
        lay.setSpacing(4)
        hd = QLabel()
        hd.setTextFormat(Qt.RichText)
        hd.setText("<span style='font-size:12px;font-weight:600;color:%s'>📊 性能指标 (一张表 · 按 基本/精细/专业 三档 · 右侧即成本挂点)</span>"
                   "<span style='color:%s;font-size:10.5px'>&nbsp;&nbsp;每行 = 指标 · 值 · 对应模型 · 功能层级; "
                   "档次列第二行就是该档成本组成</span>" % (th["C_YELLOW"], th["C_GRAY"]))
        hd.setWordWrap(True)
        lay.addWidget(hd)

        rows, spans = [], []
        for b in bands:
            br = b.get("rows") or []
            spans.append((len(rows), len(br), b))
            for r in br:
                rows.append([b.get("name") or b.get("id") or "—",
                             r.get("k") or "—", r.get("v") or "—",
                             r.get("model") or "—", r.get("layer") or "—",
                             _src_check(r.get("src"))])
        t = _mk_table(["性能档次", "性能指标", "值", "对应的模型", "功能层级", "真源校验"], rows, th)
        t.setWordWrap(True)
        t.verticalHeader().setDefaultSectionSize(30)
        for _c, _w2 in ((0, 150), (1, 170), (4, 96), (5, 104)):
            t.setColumnWidth(_c, _w2)
        t.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        t.setMinimumHeight(30 * len(rows) + 48)
        self.perf_one_table = t
        self.perf_bands = [b.get("id") for b in bands]
        for _r0, _n, _b in spans:
            if _n <= 0:
                continue
            _it = t.item(_r0, 0)
            if _it is not None:
                _it.setText("%s\n(%s)" % (_b.get("name"), _b.get("layers")))
                _it.setToolTip("%s\n成本组成: %s" % (_b.get("name"), " · ".join(_b.get("cost_items") or [])))
                _it.setBackground(QBrush(QColor("#161b22")))
                _it.setForeground(QBrush(QColor(th["C_BLUE"])))
            t.setSpan(_r0, 0, _n, 1)
        lay.addWidget(t)

        # 三档成本组成 (并成一行, 只作参考不填金额)
        for b in bands:
            lab = QLabel()
            lab.setTextFormat(Qt.RichText)
            lab.setText("<span style='color:%s;font-size:10.5px'><b>%s (%s)</b> —— %s</span>"
                        % (th["C_GRAY"], b.get("name"), b.get("layers"), b.get("cost_hint") or "—"))
            lab.setWordWrap(True)
            lay.addWidget(lab)

        br2 = QHBoxLayout()
        b1 = _btn("📋 复制 性能指标 (TSV)", th)
        b1.clicked.connect(lambda: QApplication.clipboard().setText(
            "\t".join(["性能档次", "性能指标", "值", "对应的模型", "功能层级"]) + "\n"
            + "\n".join("\t".join(r[:5]) for r in rows)))
        br2.addWidget(b1)
        br2.addStretch()
        lay.addLayout(br2)
        return w

    def _active_banner(self, th, scope, extra=""):
        """当前活跃任务提示条 —— 老倪 2026-10-28:「在功能配置页面, 要提示 当前的活跃任务, 随即显示它的功能配置」"""
        tid, tk, bt, bd = _active_bind()
        funcs = _task_funcs(tid)
        segg = _task_seg_cover(tid)
        n_en = sum(1 for f in funcs if f["enabled"])
        n_dis = sum(1 for f in funcs if f["disabled"])
        n_app = sum(1 for s in segg if s["applies"])
        box = QLabel()
        box.setTextFormat(Qt.RichText)
        box.setWordWrap(True)
        box.setText(
            "<div style='font-size:14px'><b>🎯 当前活跃任务 &nbsp;"
            "<span style='color:#58a6ff'>%s</span></b> &nbsp;"
            "<span style='color:#c9d1d9'>%s</span></div>"
            "<div style='color:#8b949e;font-size:11px;margin-top:2px'>"
            "本页（%s）显示的就是这个任务的配置 —— 任务级元任务 "
            "<b style='color:#d2a8ff'>%d</b> 条 · 工艺段 <b>%d/%d</b> 启用 · 功能 "
            "<b style='color:#3fb950'>%d</b> / 全部 77（启用节点 %d · 禁用 %d）· 场景 %s · 站点 %s%s</div>"
            "<div style='color:#6e7681;font-size:10px;margin-top:2px'>"
            "真源 config/ss_task_binding.json → active_task（换任务 = 任务配置页点该行 ★）"
            " · 功能真源 tools/export_meta_doc.build_meta_tasks()</div>"
            % (tid or "—", tk.get("name") or "—", scope, len(_task_level_meta(tid)[0]),
               n_app, len(segg), len(funcs), n_en, n_dis,
               tk.get("scene_ref") or bt.get("scene_ref") or "—",
               tk.get("site") or bt.get("site") or "—", extra))
        box.setStyleSheet("QLabel{background:#0d1a26;border:1px solid #1f6feb;border-left:4px solid #58a6ff;"
                          "border-radius:4px;padding:7px 10px;color:#e6edf3;}")
        return box

    # ══════════════════════════════════════════════════════════════════════════
    # 🧩 功能配置 (以当前活跃任务为主线重做) —— 老倪 2026-10-28
    #   「根据元任务的编排, 继续完成 功能配置; 当前激活的是 任务7, 功能上要将任务7的任务都对应上;
    #    功能配置的UI, 你再设计一下; 在功能配置页面, 要提示 当前的活跃任务, 随即显示当前活跃任务的功能配置」
    # ══════════════════════════════════════════════════════════════════════════
    def _build_func_active_view(self, th, d):
        """版面自上而下: ①活跃任务 ②元任务编排 ③工艺段→功能覆盖 ④本任务功能明细(可过滤) ⑤参数明细(特征库)"""
        tid, tk, bt, bd = _active_bind()
        funcs = _task_funcs(tid)
        segg = _task_seg_cover(tid)
        mts, mt_note, mt_src = _task_level_meta(tid)

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(7)

        def _sec(txt, hint=""):
            q = QLabel()
            q.setTextFormat(Qt.RichText)
            q.setWordWrap(False)
            q.setText("<span style='font-size:12px;font-weight:600;color:%s'>%s</span>"
                      "<span style='color:%s;font-size:10.5px'>&nbsp;&nbsp;%s</span>"
                      % (th["C_YELLOW"], txt, th["C_GRAY"], hint))
            return q

        # ① 活跃任务
        lay.addWidget(self._active_banner(th, "功能配置"))

        # ② 功能总表 —— 老倪 2026-10-28: 「每个功能, 都要有对应关系, 要有功能总表;
        #    第一个表应该是所有当前任务的所有功能, 再对应哪个元任务; 我现在看不到功能, 每个功能都要列出来」
        _det, _fnm = {}, {}
        for f in funcs:
            try:
                _det[f["fn"]] = _fn_detail(f["fn"])
            except Exception:                                                   # noqa: BLE001
                _det[f["fn"]] = {}
        for _m in _mt_funcs(tid):
            for _f in _m["fns"]:
                _fnm.setdefault(_f["fn"], []).append(_m.get("id"))
        head_ft = _sec("📋 功能总表 · 本任务 %d 个功能" % len(funcs),
                       "每个功能一行: 名称 · 输入 · 输出 · 描述 · 对应元任务 · 逻辑实现 —— 点一行右下详情跟着跳")
        lay.addWidget(head_ft)

        ft_bar = QHBoxLayout()
        ft_note = QLabel()
        ft_note.setStyleSheet("color:%s;font-size:11px;" % th["C_GRAY"])
        ft_bar.addWidget(ft_note)
        ft_bar.addStretch()
        lay.addLayout(ft_bar)

        def _ft_rows(only_task=True, mt=None):
            rr = []
            if only_task:
                pool = [(f["fn"], f.get("layer") or "", f.get("name") or f["fn"]) for f in funcs]
            else:
                pool = sorted((k, (v.get("layer") or ""), (v.get("name") or k))
                              for k, v in (_fn_registry().get("fns") or {}).items())
            for fid, lay0, nm0 in pool:
                d0 = _det.get(fid)
                if d0 is None:
                    try:
                        d0 = _fn_detail(fid) or {}
                    except Exception:                                           # noqa: BLE001
                        d0 = {}
                mts_of = _fnm.get(fid) or []
                if mt and mt not in mts_of:
                    continue
                impl = next((i for i in (d0.get("impl") or []) if i.get("ok")), None)
                _imsg = (impl.get("msg") or "") if impl else "⛔ 未登记"
                _short = _imsg
                if impl and impl.get("file"):
                    _rel = _imsg.split("  ")[0] if "  " in _imsg else _imsg
                    _short = "%s  %s" % (os.path.basename(_rel.split(":")[0]) + ":" + _rel.split(":")[1]
                                         if ":" in _rel else os.path.basename(_rel),
                                         (_imsg.split("  ", 1)[1].strip() if "  " in _imsg else ""))
                rr.append([fid, d0.get("name") or nm0,
                           " · ".join(d0.get("inputs") or []) or "⛔ 未登记",
                           " · ".join(d0.get("outputs") or []) or "⛔ 未登记",
                           (d0.get("work") or d0.get("seed_desc") or "—"),
                           " + ".join(mts_of) or ("⛔ 无" if only_task else "— 不服务本任务"),
                           _short, _imsg])
            return rr

        t_ft = _mk_table(["功能ID", "功能名称", "输入", "输出", "描述", "对应元任务",
                          "逻辑实现 (function)"], _ft_rows(True), th)
        t_ft.setWordWrap(True)
        t_ft.verticalHeader().setDefaultSectionSize(30)
        for _c, _w in ((0, 92), (1, 200), (2, 246), (3, 226), (4, 296), (5, 82)):
            t_ft.setColumnWidth(_c, _w)
        t_ft.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        t_ft.setMinimumHeight(24 * 10 + 46)
        self.fn_all_table = t_ft
        lay.addWidget(t_ft)

        def _ft_fill(only_task=True, mt=None):
            rows = _ft_rows(only_task, mt)
            t_ft.setRowCount(len(rows))
            for r, row in enumerate(rows):
                for c, val in enumerate(row[:7]):
                    it = QTableWidgetItem("" if val is None else str(val))
                    it.setToolTip(str(row[7]) if c == 6 else str(val))
                    if c in (2, 3, 4):
                        it.setForeground(QBrush(QColor(th["C_GRAY"])))
                    if c == 5 and "⛔" in str(val):
                        it.setForeground(QBrush(QColor(th["C_RED"])))
                    if c == 7 and "⛔" in str(val):
                        it.setForeground(QBrush(QColor(th["C_RED"])))
                    t_ft.setItem(r, c, it)
                t_ft.setRowHeight(r, 30 if len(str(row[4])) < 40 else 44)
            t_ft.resizeRowsToContents()
            for r in range(len(rows)):                       # 单行最多 3 行字 (58px), 全文在 tooltip
                if t_ft.rowHeight(r) > 58:
                    t_ft.setRowHeight(r, 58)
            # 老倪: 「每个功能都要列出来」 ⇒ 表本身不留内滚, 高度按全部行撑开 (页面整体滚)
            _hh = sum(t_ft.rowHeight(r) for r in range(len(rows))) + 48
            t_ft.setMinimumHeight(max(160, _hh))
            t_ft.setMaximumHeight(max(160, _hh) + 6)
            ft_note.setText("显示 %d 行%s · 输入/输出来源见右下详情" %
                            (len(rows), "" if only_task else " (全部功能, 含不服务本任务的)"))

        ft_btns = []
        for lab, mtv in [("本任务 %d" % len(funcs), None)] + [("MT-0%d" % i, "MT-0%d" % i) for i in range(1, 8)]:
            _b = _btn(lab, th)
            _b.setCheckable(True)
            _b.setChecked(mtv is None)
            ft_btns.append((_b, mtv))
            ft_bar.addWidget(_b)
        _b_all77 = _btn("全部 77", th)
        _b_all77.setCheckable(True)
        ft_bar.addWidget(_b_all77)

        def _ft_pick(mtv, only_task=True):
            for b, mv in ft_btns:
                b.setChecked(mv == mtv and only_task)
            _b_all77.setChecked(not only_task)
            _ft_fill(only_task, mtv)

        for _b, mv in ft_btns:
            _b.clicked.connect(lambda _=False, m=mv: _ft_pick(m, True))
        _b_all77.clicked.connect(lambda: _ft_pick(None, False))

        def _ft_jump(r, c):
            it = t_ft.item(r, 0)
            if it is None or not hasattr(self, "fn_tree") or self.fn_tree is None:
                return
            fid = it.text()
            for i in range(self.fn_tree.topLevelItemCount()):
                top = self.fn_tree.topLevelItem(i)
                for j in range(top.childCount()):
                    if top.child(j).data(0, Qt.UserRole) and top.child(j).data(0, Qt.UserRole)[1] == fid:
                        self.fn_tree.setCurrentItem(top.child(j))
                        return

        t_ft.cellClicked.connect(_ft_jump)
        _ft_fill(True)
        if funcs:
            pass

        # ③ 元任务编排 —— **带「功能」列** (老倪 2026-10-28: 「功能配置, 怎么和元任务连接呢?
        #    看到一个列, 应该是功能, 哪里去了?」) 连接方式 = 元任务 → 工艺段 → 画布节点 → 功能
        mfx = _mt_funcs(tid)
        n_fn_all = len({f["fn"] for m in mfx for f in m["fns"]})
        lay.addWidget(_sec("🧩 元任务编排 · %d 条 → 承载功能 %d 个 (本任务共 %d)" % (len(mfx), n_fn_all, len(funcs)),
                           "「功能」列就是元任务与功能配置的连接: 元任务 → 工艺段 → 画布节点 → 功能"))
        r2 = []
        for m in mfx:
            tw = m.get("t_win")
            twn = ("%.2f→%.2fs" % (tw[0], tw[1])) if (tw and tw[0] is not None) else "并行/常驻"
            fids = [f["fn"] for f in m["fns"]]
            ftxt = (" / ".join(fids[:3]) + ((" 等 %d 个" % len(fids)) if len(fids) > 3 else "")
                    if fids else "⛔ 无功能承载")
            nm = (m.get("name") or "").replace("右臂 · ", "").replace("左臂 · ", "").replace("双手 · ", "")
            r2.append([m.get("id"), nm, ftxt, m["n_fn"],
                       HAND_CN.get(m.get("hand") or "", "未标"),
                       " + ".join(sx.split(" ")[0] for sx in (m.get("seg8") or [])) or "—",
                       m.get("n_seg") or 0, twn,
                       " / ".join(m.get("targets") or []) or "—"])
        t2 = _mk_table(["元任务", "名称", "功能 (承载 · 经工艺段)", "功能数", "手别",
                        "工艺段", "动作段", "时空窗", "目标对象"], r2, th)
        for r, m in enumerate(mfx):
            _it = t2.item(r, 2)
            if _it is not None:
                _it.setToolTip("\n".join("%s %s" % (f["fn"], f["name"]) for f in m["fns"]) or "该元任务落在的工艺段下没有功能条目")
            _it4 = t2.item(r, 0)
            if _it4 is not None and m["n_fn"] == 0:
                _it4.setForeground(QColor(th["C_RED"]))
                _it4.setToolTip("工艺段「%s」在 段→节点 映射里没有落成本任务功能的节点 ⇒ 该元任务目前没有功能承载(真源缺口)"
                                % " / ".join(m.get("seg8") or []))
        # 反向: 功能 → 承载元任务
        fn_mts = {}
        for m in mfx:
            for f in m["fns"]:
                fn_mts.setdefault(f["fn"], []).append(m.get("id"))
        mt_of_seg = {}
        for m in mfx:
            for sx in (m.get("seg8") or []):
                mt_of_seg.setdefault(sx, []).append(m.get("id"))
        t2.setWordWrap(False)
        try:
            t2.verticalHeader().setDefaultSectionSize(22)
        except Exception:                                                       # noqa: BLE001
            pass
        t2.setMinimumHeight(24 * max(3, min(len(r2), 8)) + 46)
        lay.addWidget(t2)
        lay.addWidget(QLabel("<span style='color:%s;font-size:10px'>%s · 真源 %s</span>"
                             % (th["C_GRAY"], mt_note.replace("<", "&lt;"), mt_src)))

        # ③ 工艺段 → 功能 覆盖
        lay.addWidget(_sec("🧭 工艺段 → 功能 覆盖",
                           "本任务 applies_segments 逐段算: 节点/启用节点/落成功能/缺参数 —— 哪段没人承载一眼看到"))
        r3 = []
        for s in segg:
            mark = "✅ 启用" if s["applies"] else ("⛔ 本任务不用" if s["excluded"] else "· 未声明")
            r3.append([s["seg"], mark, " + ".join(mt_of_seg.get(s["seg"]) or []) or "⛔ 无元任务",
                       s["n_node"], s["n_on"], s["n_fn"],
                       ("⛔ %d" % s["n_bad"]) if s["n_bad"] else "✅ 0",
                       " / ".join(f["fn"] for f in s["fns"][:4]) or "—"])
        t3 = _mk_table(["工艺段", "本任务", "承载元任务", "节点数", "启用节点", "对应功能", "缺参数", "功能举例"], r3, th)
        t3.setMinimumHeight(24 * max(3, len(r3)) + 46)
        lay.addWidget(t3)

        # ④ 子系统 → 功能 (树) + 功能定义详情
        #    老倪 2026-10-28: 「功能, 应该有 功能名称, 输入, 输出, 描述, 这些信息, 对应着元任务;
        #    可以是 1 个功能, 也可以由功能组成子系统。重写功能配置, 每个功能要有 function 这样的逻辑实现」
        subs4 = _subs_list()
        head4 = _sec("🏗 子系统 → 功能 · %d 个子系统 / %d 个功能" % (len(subs4), len(funcs)),
                     "功能四件套 = 名称 · 输入 · 输出 · 描述; 再挂 承载元任务 与 逻辑实现(file:line) —— 点左边看右边")
        lay.addWidget(head4)
        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        tree = QTreeWidget()
        tree.setHeaderLabels(["子系统 / 功能", "功能ID", "层", "实现"])
        tree.setRootIsDecorated(True)
        tree.setUniformRowHeights(True)
        tree.setAlternatingRowColors(True)
        tree.setStyleSheet("QTreeWidget{background:%s;color:%s;border:1px solid %s;}"
                           "QTreeWidget::item{height:22px;}"
                           "QHeaderView::section{background:%s;color:%s;border:0;height:24px;}" %
                           (th["C_BG2"], th["C_WHITE"], th["C_BORDER"], th["C_CARD"], th["C_GRAY"]))
        try:
            tree.setColumnWidth(0, 322)
            tree.setColumnWidth(1, 96)
            tree.setColumnWidth(2, 46)
            tree.setColumnWidth(3, 40)
        except Exception:                                                       # noqa: BLE001
            pass
        _impl_of = {}
        for _f in funcs:
            try:
                _impl_of[_f["fn"]] = _fn_detail(_f["fn"])
            except Exception:                                                   # noqa: BLE001
                _impl_of[_f["fn"]] = {"impl": [], "inputs": [], "outputs": [], "io_src": ""}
        for _s in subs4:
            top = QTreeWidgetItem(["%s · %s" % (_s["name"], _s["level"]), "%d 个" % _s["n"], "", ""])
            fnt = top.font(0)
            fnt.setBold(True)
            top.setFont(0, fnt)
            top.setForeground(0, QBrush(QColor(th["C_BLUE"])))
            top.setData(0, Qt.UserRole, ("sub", _s["system_id"]))
            tree.addTopLevelItem(top)
            for _f in _s["fns"]:
                _d = _impl_of.get(_f["fn"]) or {}
                _ok = sum(1 for i in _d.get("impl") or [] if i.get("ok"))
                ch = QTreeWidgetItem([_f["name"], _f["fn"], _f["layer"] or "—",
                                      ("✅%d" % _ok) if _ok else "⛔"])
                ch.setData(0, Qt.UserRole, ("fn", _f["fn"]))
                if not _ok:
                    ch.setForeground(3, QBrush(QColor(th["C_RED"])))
                top.addChild(ch)
        tree.expandAll()

        detail = QTextBrowser()
        detail.setOpenExternalLinks(False)
        detail.setStyleSheet("QTextBrowser{background:%s;color:%s;border:1px solid %s;padding:2px;}"
                             % (th["C_BG2"], th["C_WHITE"], th["C_BORDER"]))
        dcol = QWidget()
        dlay = QVBoxLayout(dcol)
        dlay.setContentsMargins(0, 0, 0, 0)
        dlay.setSpacing(4)
        drow = QHBoxLayout()
        b_cp_spec = _btn("📋 复制功能定义", th)
        b_cp_impl = _btn("📋 复制实现路径", th)
        drow.addWidget(b_cp_spec)
        drow.addWidget(b_cp_impl)
        drow.addStretch()
        dlab = QLabel("点左侧 子系统 看由哪些功能组成 · 点 功能 看四件套 + 逻辑实现")
        dlab.setStyleSheet("color:%s;font-size:11px;" % th["C_GRAY"])
        drow.addWidget(dlab)
        dlay.addLayout(drow)
        dlay.addWidget(detail, 1)

        _cur = {"kind": "fn", "id": funcs[0]["fn"] if funcs else ""}
        _fnmap = {f["fn"]: f for f in funcs}

        def _fn_text(fid):
            d = _impl_of.get(fid) or {}
            f0 = _fnmap.get(fid) or {}
            L = ["【功能】%s  %s" % (fid, d.get("name") or ""),
                 "子系统: %s · 层 %s · 段 %s" % (d.get("subsystem") or "—", d.get("layer") or "—",
                                                " / ".join(f0.get("segs") or []) or "—"),
                 "", "描述: %s" % (d.get("work") or d.get("row_name") or d.get("seed_desc") or "—"),
                 "", "输入:"]
            L += ["  · %s" % x for x in (d.get("inputs") or ["⛔ 未登记"])]
            L.append("输出:")
            L += ["  · %s" % x for x in (d.get("outputs") or ["⛔ 未登记"])]
            L.append("")
            if d.get("io_src"):
                L.append("(输入/输出来源: %s)" % d["io_src"])
            if d.get("io_ref"):
                L.append("(%s)" % d["io_ref"])
            L += ["", "承载元任务: %s" % (" + ".join(fn_mts.get(fid) or []) or "⛔ 无"),
                  "参数: 专用 %s / 总 %s · %s · 优先级 %s" %
                  (f0.get("n_spec"), f0.get("n_par"),
                   "✅ 完整" if f0.get("complete") else "⛔ 缺 %s" % "、".join(f0.get("missing") or []),
                   f0.get("prio") or "—"),
                  "", "逻辑实现 (function):"]
            for i in (d.get("impl") or []):
                L.append("  [%s] %s  %s" % ("✅" if i.get("ok") else "⛔", i.get("kind"), i.get("msg")))
            if not (d.get("impl") or []):
                L.append("  ⛔ 未登记实现")
            L += ["", "验证方法: %s" % (", ".join(f0.get("verify") or []) or "—")]
            return "\n".join(L)

        def _fn_html(fid):
            d = _impl_of.get(fid) or {}
            f0 = _fnmap.get(fid) or {}
            red, mut, acc = th["C_RED"], th["C_GRAY"], th["C_BLUE"]
            h = ["<div style='font-size:12px;line-height:1.55'>"]
            h.append("<div style='font-size:15px;font-weight:700;color:%s'>%s</div>" %
                     (acc, d.get("name") or fid))
            h.append("<div style='color:%s;margin-bottom:6px'>%s · 子系统 %s · 层 %s · 段 %s</div>" %
                     (mut, fid, d.get("subsystem") or "—", d.get("layer") or "—",
                      " / ".join(f0.get("segs") or []) or "—"))
            h.append("<b>描述</b><br>%s<br><br>" % (d.get("work") or d.get("seed_desc") or "—"))
            h.append("<table width='100%%' cellspacing='0' cellpadding='3'><tr>"
                     "<td width='50%%' valign='top'><b>输入</b><br>%s</td>"
                     "<td width='50%%' valign='top'><b>输出</b><br>%s</td></tr></table>" %
                     ("<br>".join("· " + x for x in (d.get("inputs") or ["<span style='color:%s'>⛔ 未登记</span>" % red])),
                      "<br>".join("· " + x for x in (d.get("outputs") or ["<span style='color:%s'>⛔ 未登记</span>" % red]))))
            if d.get("io_src"):
                h.append("<div style='color:%s;font-size:11px'>输入/输出来源: %s</div>" % (mut, d["io_src"]))
            if d.get("io_ref"):
                h.append("<div style='color:%s;font-size:11px'>%s</div>" % (mut, d["io_ref"]))
            h.append("<br><b>承载元任务</b>: %s" % (" + ".join(fn_mts.get(fid) or []) or
                                                "<span style='color:%s'>⛔ 无</span>" % red))
            h.append("<br><b>参数</b>: 专用 %s / 总 %s · %s · 优先级 %s" %
                     (f0.get("n_spec"), f0.get("n_par"),
                      "✅ 完整" if f0.get("complete") else
                      "<span style='color:%s'>⛔ 缺 %s</span>" % (red, "、".join(f0.get("missing") or [])),
                      f0.get("prio") or "—"))
            h.append("<br><br><b>逻辑实现 (function)</b><br>")
            if d.get("impl"):
                for i in d["impl"]:
                    c = acc if i.get("ok") else red
                    h.append("<div style='margin:2px 0'><span style='color:%s'>%s</span> %s — "
                             "<code>%s</code></div>" % (c, "✅" if i.get("ok") else "⛔",
                                                        i.get("kind"), i.get("msg")))
            else:
                h.append("<span style='color:%s'>⛔ 未登记实现</span>" % red)
            h.append("<br><b>验证方法</b><br>%s" % ("<br>".join("· " + x for x in (f0.get("verify") or [])) or "—"))
            h.append("</div>")
            return "".join(h)

        def _sub_html(sid):
            _s = next((x for x in subs4 if x["system_id"] == sid), None)
            if not _s:
                return ""
            red, mut, acc = th["C_RED"], th["C_GRAY"], th["C_BLUE"]
            ins, outs = [], []
            for _f in _s["fns"]:
                _d = _impl_of.get(_f["fn"]) or {}
                for x in (_d.get("inputs") or []):
                    if x not in ins:
                        ins.append(x)
                for x in (_d.get("outputs") or []):
                    if x not in outs:
                        outs.append(x)
            h = ["<div style='font-size:12px;line-height:1.55'>"]
            h.append("<div style='font-size:15px;font-weight:700;color:%s'>%s</div>" % (acc, _s["name"]))
            h.append("<div style='color:%s;margin-bottom:6px'>%s · %s · 由 %d 个功能组成</div>" %
                     (mut, _s["system_id"], _s["level"], _s["n"]))
            h.append("<b>角色</b><br>%s<br><br><b>KPI</b><br><code>%s</code><br><br>" %
                     (_s.get("role") or "—", (_s.get("kpi") or "—")[:400]))
            h.append("<b>成员功能</b><br>%s<br><br>" %
                     "<br>".join("· %s %s" % (f["fn"], f["name"]) for f in _s["fns"]))
            h.append("<b>子系统输入</b> (成员功能输入并集)<br>%s<br><br>" %
                     ("<br>".join("· " + x for x in ins[:14]) or "⛔ 未登记"))
            h.append("<b>子系统输出</b> (成员功能输出并集)<br>%s" %
                     ("<br>".join("· " + x for x in outs[:14]) or "⛔ 未登记"))
            h.append("</div>")
            return "".join(h)

        def _show():
            kind, oid = _cur["kind"], _cur["id"]
            if kind == "sub":
                detail.setHtml(_sub_html(oid))
            else:
                detail.setHtml(_fn_html(oid))

        def _on_sel():
            it = tree.currentItem()
            if it is None:
                return
            dat = it.data(0, Qt.UserRole)
            if dat:
                _cur["kind"], _cur["id"] = dat[0], dat[1]
                _show()

        def _copy_spec():
            if _cur["kind"] == "func" or _cur["kind"] == "fn":
                QApplication.clipboard().setText(_fn_text(_cur["id"]))
                dlab.setText("已复制 %s 的功能定义 (名称/输入/输出/描述/元任务/实现)" % _cur["id"])
            else:
                _s = next((x for x in subs4 if x["system_id"] == _cur["id"]), None)
                if _s:
                    QApplication.clipboard().setText("【子系统】%s · %s · %d 个功能\n%s\n%s" %
                                                     (_s["name"], _s["level"], _s["n"], _s.get("role") or "",
                                                      "\n".join("%s %s" % (f["fn"], f["name"]) for f in _s["fns"])))
                    dlab.setText("已复制子系统 %s 的组成" % _s["name"])

        def _copy_impl():
            fid = _cur["id"] if _cur["kind"] == "fn" else ""
            d = _impl_of.get(fid) or {}
            paths = [i.get("msg") for i in (d.get("impl") or []) if i.get("ok")]
            if paths:
                QApplication.clipboard().setText("\n".join(paths))
                dlab.setText("已复制 %d 条实现路径 (file:line)" % len(paths))
            else:
                dlab.setText("该条目没有可复制的实现路径")

        tree.currentItemChanged.connect(lambda *_: _on_sel())
        b_cp_spec.clicked.connect(_copy_spec)
        b_cp_impl.clicked.connect(_copy_impl)
        tree.setMinimumWidth(430)
        detail.setMinimumWidth(360)
        split.addWidget(tree)
        split.addWidget(dcol)
        try:
            split.setSizes([470, 900])
        except Exception:                                                       # noqa: BLE001
            pass
        split.setMinimumHeight(420)
        self.fn_tree, self.fn_detail = tree, detail
        self.func_rows = funcs
        lay.addWidget(split, 3)
        if funcs:
            tree.setCurrentItem(tree.topLevelItem(0).child(0) if tree.topLevelItem(0).childCount() else
                                tree.topLevelItem(0))
        _show()

        # ⑤ 参数明细 (特征库 · 功能域) —— 保留原表与选中定位口径 (点参数名直接定位到行)
        cs = [c for c in d.get("CHARACTERISTIC", []) if c.get("domain") == "功能配置"]
        lay.addWidget(_sec("⚙️ 参数明细 · 特征库 功能域 %d 条" % len(cs),
                           "工程共用参数 (所有任务读同一份真源); 点左侧具体参数名会定位到这一行"))
        t5 = _mk_table(["域", "参数", "级", "权限", "真源", "值", "判据"],
                       [[c["domain"], c["id"], c["grade"], c["perm"], str(c["src"]).split("#")[0],
                         ("缺失 ⛔" if c.get("value") is None else str(c.get("value"))[:20]),
                         str(c["judge"])[:48]] for c in cs], th)
        lay.addWidget(t5, 1)

        head = QLabel("点左侧「功能配置 / 性能配置 / 模型配置」只筛该域; 点具体参数名直接定位到行")
        head.setFont(QFont("Consolas", 10))
        head.setStyleSheet("color:%s;background:transparent;" % th["C_GRAY"])
        lay.addWidget(head)

        view = {"w": w, "table": t5, "rows": [(c["domain"], c["id"]) for c in cs], "head": head,
                "btns": {}, "default": "功能配置", "title": "🧩 功能配置", "lay": lay}
        self.tabs.addTab(_scrollable(w, th), "🧩 功能配置")
        self._apply_fpm_filter(view, "功能配置")
        return view

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
                "btns": {}, "default": default_dom, "title": tab_title, "lay": l}
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
        self.tabs.addTab(_scrollable(w, th), tab_title)
        self._apply_fpm_filter(view, default_dom)      # 本页默认就筛自己那一域
        return view

    # ⭐ 主页面(右工作区)页签次序 = 北斗次序 (老倪 2026-10-15: 「下面主页面标签的顺序也不一致,
    #   应该显示 产品配置标签, 然后是第二个任务配置, 依次顺序排列」)。非七星的视图排在七阵之后。
    # 2026-10-15 老倪: 「取消 模型匹配, 信息合并到 模型配置页面; 取消文档预览页面, 合并到 文档配置页面」
    # 2026-10-19 老倪: 「将 工单配置，替换成 工程配置；将工单，放到文档配置选项卡，将成本/报价 商业模式
    #   的内容，都迁移到 文档配置里」⇒ 页签正好 = 北斗七星 (7 个), 没有非七星视图了。
    _TAB_ORDER = ("产品配置", "任务配置", "功能配置", "模型配置", "性能配置", "工程配置", "文档配置")

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

    # ══════════════════════════════════════════════════════════════════
    # 💰 成本/报价 (2026-10-19 老倪: 「从配置中心，直接预计出成本价格」)
    #   算法: tools/cost_model.py (唯一公式) · 参数: config/platform/zmax_cost_model.json
    #   页面只做 改假设 → 现算 → 可写回/导出; 派生值 (合计/回本) 一律不落盘、不手填。
    # ══════════════════════════════════════════════════════════════════
    def _cost_page(self, th):
        _w = QWidget()
        _lay = QVBoxLayout(_w)
        _lay.setContentsMargins(6, 6, 6, 6)
        try:
            import cost_model as _cm
        except Exception as _e:                                                 # noqa: BLE001
            _lb = QLabel("⛔ tools/cost_model.py 不可用: %r" % (_e,))
            _lb.setWordWrap(True)
            _lay.addWidget(_lb)
            _lay.addStretch()
            return _w
        self._cost_m = _cm
        try:
            self._cost_d = _cm.load()
        except Exception as _e:                                                 # noqa: BLE001
            _lb = QLabel("⛔ 成本真源读不到 (config/platform/zmax_cost_model.json): %r" % (_e,))
            _lb.setWordWrap(True)
            _lay.addWidget(_lb)
            _lay.addStretch()
            return _w

        _d = self._cost_d
        _gray = th.get("C_GRAY", "#8b949e")
        _acc = th.get("C_ACCENT", "#58a6ff")

        _h = QLabel("💰 成本 / 报价 · 单套投入与静态回本 (Z100Fd ｜ %s)" % _d.get("name", ""))
        _h.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        _h.setStyleSheet("color:%s;background:transparent;" % _acc)
        _lay.addWidget(_h)
        self._cost_l_src = QLabel()
        self._cost_l_src.setWordWrap(True)
        self._cost_l_src.setStyleSheet("color:%s;background:transparent;" % _gray)
        _lay.addWidget(self._cost_l_src)

        # ── BOM (逐项真源, 只读) ──
        _rows = [[str(it.get("item", "")), str(it.get("model", "")),
                  "{:,}".format(int(it.get("price") or 0)), str(it.get("status", ""))]
                 for it in (_d.get("hardware") or [])]
        _rows.append(["硬件合计", "—", "{:,}".format(int(_cm.hardware_total(_d))), "现算"])
        self._cost_bom = _mk_table(["部件", "型号", "单价 (元)", "状态"], _rows, th,
                                   widths=[150, 190, 110, 80])
        self._cost_bom.setToolTip("真源 config/platform/zmax_cost_model.json 的 hardware[]; 改价只改 price, 其余现值")
        _lay.addWidget(self._cost_bom)

        # ── 假设 (可改, 写回真源才生效) ──
        _row = QHBoxLayout()
        _lab = QLabel("产线假设:")
        _lab.setStyleSheet("color:%s;background:transparent;" % _gray)
        _row.addWidget(_lab)
        self._cost_in = {}
        _line = _d.get("line") or {}
        _labor = float((_d.get("labor") or {}).get("cost_per_person_year", 90000))
        _sw = float((_d.get("software") or {}).get("price", 160000))
        _alt = float((_d.get("alt_arm") or {}).get("saving", 45000))
        for _key, _text, _kind, _lo, _hi, _step, _val, _dec in (
                ("stations", "工位数", "int", 1, 50, 1, int(_line.get("stations", 1)), 0),
                ("shifts", "班次", "int", 1, 3, 1, int(_line.get("shifts", 2)), 0),
                ("persons", "每班人数", "int", 1, 10, 1, int(_line.get("persons_per_shift", 1)), 0),
                ("labor", "人力成本 万/人·年", "float", 4.0, 20.0, 0.5, _labor / 1e4, 1),
                ("software", "软件 万/套", "float", 0.0, 100.0, 1.0, _sw / 1e4, 1),
                ("alt", "替代臂降本 万", "float", 0.0, 30.0, 0.5, _alt / 1e4, 1)):
            _l = QLabel(_text)
            _l.setStyleSheet("background:transparent;")
            _row.addWidget(_l)
            if _kind == "int":
                _sb = QSpinBox()
                _sb.setRange(int(_lo), int(_hi))
                _sb.setSingleStep(int(_step))
                _sb.setValue(int(_val))
            else:
                _sb = QDoubleSpinBox()
                _sb.setRange(float(_lo), float(_hi))
                _sb.setSingleStep(float(_step))
                _sb.setDecimals(int(_dec))
                _sb.setValue(float(_val))
            _sb.setFixedWidth(78)
            _sb.valueChanged.connect(lambda *_: self._cost_refresh())
            _row.addWidget(_sb)
            self._cost_in[_key] = _sb
        _row.addStretch()
        _lay.addLayout(_row)

        # ── 结果 (只读, 现算) ──
        _box = QFrame()
        _box.setStyleSheet("QFrame{background:%s;border:1px solid %s;border-radius:4px;}"
                           % (th.get("C_BG2", "#161b22"), th.get("C_BORDER", "#30363d")))
        _bl = QVBoxLayout(_box)
        self._cost_l_total = QLabel()
        self._cost_l_total.setFont(QFont("Microsoft YaHei", 15, QFont.Bold))
        self._cost_l_total.setStyleSheet("background:transparent;border:none;")
        _bl.addWidget(self._cost_l_total)
        self._cost_l_annual = QLabel()
        self._cost_l_annual.setFont(QFont("Microsoft YaHei", 11))
        self._cost_l_annual.setStyleSheet("background:transparent;border:none;")
        _bl.addWidget(self._cost_l_annual)
        self._cost_l_payback = QLabel()
        self._cost_l_payback.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        self._cost_l_payback.setStyleSheet("background:transparent;border:none;color:#3fb950;")
        _bl.addWidget(self._cost_l_payback)
        self._cost_l_alt = QLabel()
        self._cost_l_alt.setWordWrap(True)
        self._cost_l_alt.setStyleSheet("background:transparent;border:none;color:%s;" % _gray)
        _bl.addWidget(self._cost_l_alt)
        _lay.addWidget(_box)

        # ── 按钮 ──
        _row2 = QHBoxLayout()
        _b_calc = _btn("🧮 重新估算", th)
        _b_calc.clicked.connect(lambda: self._cost_refresh(verbose=True))
        _row2.addWidget(_b_calc)
        _b_save = _btn("💾 写入真源", th)
        _b_save.setToolTip("把上面 6 个假设写回 config/platform/zmax_cost_model.json (自动备份 + 回读校验; 派生值不落盘)")
        _b_save.clicked.connect(self._cost_save)
        _row2.addWidget(_b_save)
        _b_copy = _btn("📋 复制结果", th)
        _b_copy.setToolTip("TSV, 直接贴 Excel / 邮件")
        _b_copy.clicked.connect(self._cost_copy)
        _row2.addWidget(_b_copy)
        _b_exp = _btn("📥 导出 JSON", th)
        _b_exp.setToolTip("落 zmax_data/cost/cost_estimate_<时间>.json (给立项文档/画布节点吃)")
        _b_exp.clicked.connect(self._cost_export)
        _row2.addWidget(_b_exp)
        _row2.addStretch()
        _lay.addLayout(_row2)

        self._cost_log = QLabel("—")
        self._cost_log.setWordWrap(True)
        self._cost_log.setStyleSheet("color:%s;background:transparent;" % _gray)
        _lay.addWidget(self._cost_log)
        _lay.addStretch()

        self._cost_refresh()            # 打开即出数 (不等用户点)
        return _w

    def _cost_inputs(self):
        g = lambda k: self._cost_in[k].value()                              # noqa: E731
        return dict(stations=int(g("stations")), shifts=int(g("shifts")),
                    persons_per_shift=int(g("persons")),
                    labor_per_person_year=float(g("labor")) * 1e4,
                    software=float(g("software")) * 1e4,
                    alt_arm_saving=float(g("alt")) * 1e4)

    def _cost_refresh(self, verbose=False):
        """按当前界面假设现算 (不发任何写操作)。"""
        if not getattr(self, "_cost_m", None) or not hasattr(self, "_cost_in"):
            return None
        try:
            e = self._cost_m.estimate(self._cost_d, **self._cost_inputs())
        except Exception as _e:                                             # noqa: BLE001
            self._cost_log.setText("⛔ 估算失败: %r" % (_e,))
            return None
        self._cost_e = e
        self._cost_l_src.setText(
            "真源 %s @ %s ｜ 算法 %s ｜ %s" % (
                e["truth"], e["truth_mtime"], "tools/cost_model.py",
                "改假设后点「🧮 重新估算」; 想长期生效点「💾 写入真源」"))
        self._cost_l_total.setText("单套投入 %.1f 万  (硬件 %.1f + 软件 %.1f)" % (
            e["total_first"] / 1e4, e["hardware"] / 1e4, e["software"] / 1e4))
        self._cost_l_annual.setText(
            "年节省 %.1f 万  ←  %d 工位 × %d 班 × %d 人/班 = %d 人 × %.1f 万/人·年" % (
                e["annual_save"] / 1e4, e["stations"], e["shifts"], e["persons_per_shift"],
                e["heads"], e["labor_per_person_year"] / 1e4))
        if e["payback_years"] is None:
            self._cost_l_payback.setText("静态回本 —  (年节省为 0, 无法回本)")
        else:
            self._cost_l_payback.setText("静态回本 %.2f 年   (%s)" % (
                e["payback_years"], e["formula"]))
        self._cost_l_alt.setText(
            "替代力控臂 (降 %.1f 万): 单套 %.1f 万 ⇒ 回本 %.2f 年 ｜ 不计折现/质量损耗/增产" % (
                e["alt_arm_saving"] / 1e4, e["total_alt"] / 1e4,
                e["payback_years_alt"] if e["payback_years_alt"] is not None else float("nan")))
        if verbose:
            self._log_cc("💰 成本估算: 单套 %.1f 万 · 年节省 %.1f 万 · 回本 %s 年" % (
                e["total_first"] / 1e4, e["annual_save"] / 1e4, e["payback_years"]))
        return e

    def _cost_save(self):
        try:
            r = self._cost_m.save_line(**self._cost_inputs())
        except Exception as _e:                                             # noqa: BLE001
            self._cost_log.setText("⛔ 写回真源失败: %r" % (_e,))
            self._log_cc("⛔ 成本假设写回失败: %r" % (_e,))
            return
        if r.get("ok"):
            self._cost_d = self._cost_m.load()      # 写后重读, 页面与真源同步
            self._cost_refresh()
            self._cost_log.setText("✅ 已写回真源 (备份 %s) · 回读校验通过: %s"
                                   % (os.path.basename(r["backup"]), r["line"]))
            self._log_cc("💰 成本假设已写回 config/platform/zmax_cost_model.json "
                         "line=%s labor=%s" % (r["line"], r["labor"]))
        else:
            self._cost_log.setText("⚠ 已写盘但回读不一致 —— 别按这个数报价, 先看真源: %s" % r["path"])
            self._log_cc("⚠ 成本假设回读不一致: %s" % (r["path"],))

    def _cost_text(self):
        e = getattr(self, "_cost_e", None)
        if not e:
            return ""
        return "\n".join([
            "项\t值",
            "方案\t%s" % e["scheme"],
            "硬件 (元)\t%d" % int(e["hardware"]),
            "软件 (元)\t%d" % int(e["software"]),
            "单套合计 (元)\t%d" % int(e["total_first"]),
            "工位数\t%d" % e["stations"],
            "班次\t%d" % e["shifts"],
            "每班人数\t%d" % e["persons_per_shift"],
            "人力成本 (元/人·年)\t%d" % int(e["labor_per_person_year"]),
            "年节省 (元)\t%d" % int(e["annual_save"]),
            "静态回本 (年)\t%s" % e["payback_years"],
            "替代臂单套 (元)\t%d" % int(e["total_alt"]),
            "替代臂回本 (年)\t%s" % e["payback_years_alt"],
        ]) + "\n"

    def _cost_copy(self):
        txt = self._cost_text()
        if not txt:
            self._cost_log.setText("⚠ 还没有可复制的结果")
            return
        QApplication.clipboard().setText(txt)
        self._cost_log.setText("📋 已复制 %d 行 TSV (可直接贴 Excel)" % (txt.count("\n") - 1))
        self._log_cc("💰 成本结果已复制到剪贴板")

    def _cost_export(self):
        e = getattr(self, "_cost_e", None)
        if not e:
            return
        try:
            _dir = os.path.join(ROOT, "zmax_data", "cost")
            os.makedirs(_dir, exist_ok=True)
            _p = os.path.join(_dir, "cost_estimate_%s.json" % time.strftime("%Y%m%d_%H%M%S"))
            with open(_p, "w", encoding="utf-8") as f:
                json.dump(e, f, ensure_ascii=False, indent=1)
            back = json.load(open(_p, encoding="utf-8"))
            _ok = abs(float(back["total_first"]) - float(e["total_first"])) < 1e-6
            self._cost_log.setText(("✅ 已导出 " if _ok else "⚠ 导出回读不一致 ") + _p)
            self._log_cc("💰 成本估算已导出: %s" % _p)
        except Exception as _e:                                             # noqa: BLE001
            self._cost_log.setText("⛔ 导出失败: %r" % (_e,))

    # ══════════════════════════════════════════════════════════════════
    # 🧩 商业模式 (2026-10-19 老倪: 「在配置中心，要有商业模式，从配置导出商业模式」)
    #   算法: tools/business_model.py (唯一公式) · 输入: 成本真源 + 商业模式假设真源
    #   页面只做 改假设 → 现算 → 复制/导出; 派生值 (回本/floor/毛利/阶段价) 一律不落盘
    # ══════════════════════════════════════════════════════════════════
    def _biz_page(self, th):
        _w = QWidget()
        _lay = QVBoxLayout(_w)
        _lay.setContentsMargins(6, 6, 6, 6)
        try:
            import business_model as _bm
        except Exception as _e:                                                 # noqa: BLE001
            _lb = QLabel("⛔ tools/business_model.py 不可用: %r" % (_e,))
            _lb.setWordWrap(True)
            _lay.addWidget(_lb)
            _lay.addStretch()
            return _w
        self._biz_m = _bm
        try:
            self._biz_d = _bm.load()
        except Exception as _e:                                                 # noqa: BLE001
            _lb = QLabel("⛔ 商业模式真源读不到 (config/platform/zmax_business_model.json): %r" % (_e,))
            _lb.setWordWrap(True)
            _lay.addWidget(_lb)
            _lay.addStretch()
            return _w

        _gray = th.get("C_GRAY", "#8b949e")
        _acc = th.get("C_ACCENT", "#58a6ff")

        _h = QLabel("🧩 商业模式 · 成本结构 → 成交区间 → 三阶段定价 (从上面各配置现算)")
        _h.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        _h.setStyleSheet("color:%s;background:transparent;" % _acc)
        _lay.addWidget(_h)
        self._biz_l_src = QLabel()
        self._biz_l_src.setWordWrap(True)
        self._biz_l_src.setStyleSheet("color:%s;background:transparent;" % _gray)
        _lay.addWidget(self._biz_l_src)

        # ── 成本结构 (固定 vs 变动) ──
        self._biz_t_struct = _mk_table(["成本结构", "值", "说明"], [], th, widths=[170, 120, 420])
        _lay.addWidget(self._biz_t_struct)

        # ── 分层口径 (客户真实回本) ──
        self._biz_l_lay = QLabel()
        self._biz_l_lay.setWordWrap(True)
        self._biz_l_lay.setFont(QFont("Consolas", 10))
        self._biz_l_lay.setStyleSheet("color:%s;background:%s;border:1px solid %s;"
                                      "border-radius:4px;padding:6px;"
                                      % (th.get("C_WHITE", "#e6edf3"), th.get("C_BG2", "#161b22"),
                                         th.get("C_BORDER", "#30363d")))
        _lay.addWidget(self._biz_l_lay)

        # ── 成交区间 + 规模阈值 ──
        self._biz_l_deal = QLabel()
        self._biz_l_deal.setWordWrap(True)
        self._biz_l_deal.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
        self._biz_l_deal.setStyleSheet("background:transparent;")
        _lay.addWidget(self._biz_l_deal)

        # ── 业务假设 (改了就现算; 写入真源才长期生效) ──
        _row = QHBoxLayout()
        _lab = QLabel("业务假设:")
        _lab.setStyleSheet("color:%s;background:transparent;" % _gray)
        _row.addWidget(_lab)
        self._biz_in = {}
        _in = (self._biz_d.get("inputs") or {})
        for _key, _text, _kind, _lo, _hi, _step, _dec in (
                ("target_margin", "目标毛利率 %", "float", 0.0, 80.0, 1.0, 0),
                ("customer_target_payback", "客户目标回本 年", "float", 1.0, 8.0, 0.5, 1),
                ("s3_units", "批量台数", "int", 1, 200, 1, 0),
                ("eta_struct", "人效结构系数", "float", 0.5, 1.0, 0.01, 2)):
            _l = QLabel(_text)
            _l.setStyleSheet("background:transparent;")
            _row.addWidget(_l)
            _v = _in.get(_key, {}).get("value", 0)
            if _kind == "int":
                _sb = QSpinBox()
                _sb.setRange(int(_lo), int(_hi))
                _sb.setSingleStep(int(_step))
                _sb.setValue(int(_v))
            else:
                _sb = QDoubleSpinBox()
                _sb.setRange(float(_lo), float(_hi))
                _sb.setSingleStep(float(_step))
                _sb.setDecimals(int(_dec))
                _sb.setValue(float(_v) * (100.0 if _key == "target_margin" else 1.0))
            _sb.setFixedWidth(78)
            _sb.valueChanged.connect(lambda *_: self._biz_refresh())
            _row.addWidget(_sb)
            self._biz_in[_key] = _sb
        _row.addStretch()
        _lay.addLayout(_row)

        # ── 三阶段定价 ──
        _t3 = QLabel("三阶段定价 (阶段一不收费 ⇒ 客户零决策压力; 阶段三用真实数据算 ROI)")
        _t3.setStyleSheet("color:%s;background:transparent;" % _gray)
        _lay.addWidget(_t3)
        self._biz_t_phase = _mk_table(["阶段", "台数", "报价", "我方承担", "客户决策"], [], th,
                                      widths=[90, 50, 110, 330, 200])
        _lay.addWidget(self._biz_t_phase)

        # ── 模式推荐 ──
        self._biz_l_rec = QLabel()
        self._biz_l_rec.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
        self._biz_l_rec.setStyleSheet("background:transparent;color:#3fb950;")
        _lay.addWidget(self._biz_l_rec)
        self._biz_t_mode = _mk_table(["模式", "报价", "毛利", "成立条件", "数字"], [], th,
                                     widths=[150, 100, 60, 250, 340])
        _lay.addWidget(self._biz_t_mode)

        # ── 改配置的量化出口 + 价值/风险 ──
        self._biz_l_conf = QLabel()
        self._biz_l_conf.setWordWrap(True)
        self._biz_l_conf.setStyleSheet("color:%s;background:transparent;" % _gray)
        _lay.addWidget(self._biz_l_conf)
        self._biz_l_split = QLabel()
        self._biz_l_split.setWordWrap(True)
        self._biz_l_split.setStyleSheet("color:%s;background:transparent;" % _gray)
        _lay.addWidget(self._biz_l_split)

        # ── 按钮 ──
        _row2 = QHBoxLayout()
        _b_calc = _btn("🧮 重新推导", th)
        _b_calc.clicked.connect(lambda: self._biz_refresh(verbose=True))
        _row2.addWidget(_b_calc)
        _b_save = _btn("💾 写入假设真源", th)
        _b_save.setToolTip("只写 4 个业务假设 (自动备份 + 回读校验; 派生值不落盘)")
        _b_save.clicked.connect(self._biz_save)
        _row2.addWidget(_b_save)
        _b_copy = _btn("📋 复制结果", th)
        _b_copy.setToolTip("TSV, 直接贴 Excel / 邮件")
        _b_copy.clicked.connect(self._biz_copy)
        _row2.addWidget(_b_copy)
        _b_exp = _btn("📥 导出 JSON+提案", th)
        _b_exp.setToolTip("落 zmax_data/business/business_model_<时间>.{json,md} (提案可直接发客户)")
        _b_exp.clicked.connect(self._biz_export)
        _row2.addWidget(_b_exp)
        _row2.addStretch()
        _lay.addLayout(_row2)

        self._biz_log = QLabel("—")
        self._biz_log.setWordWrap(True)
        self._biz_log.setStyleSheet("color:%s;background:transparent;" % _gray)
        _lay.addWidget(self._biz_log)
        _lay.addStretch()

        self._biz_refresh()             # 打开即出数 (不等用户点)
        return _w

    def _biz_inputs(self):
        g = lambda k: self._biz_in[k].value()                               # noqa: E731
        return dict(target_margin=float(g("target_margin")) / 100.0,
                    customer_target_payback=float(g("customer_target_payback")),
                    s3_units=int(g("s3_units")),
                    eta_struct=float(g("eta_struct")))

    def _biz_refresh(self, verbose=False):
        """按当前界面假设现算 (不发任何写操作)。"""
        if not getattr(self, "_biz_m", None) or not hasattr(self, "_biz_in"):
            return None
        try:
            e = self._biz_m.derive(d=self._biz_d, **self._biz_inputs())
        except Exception as _e:                                             # noqa: BLE001
            self._biz_log.setText("⛔ 推导失败: %r" % (_e,))
            return None
        self._biz_e = e
        lay, dr, th_ = e["layered"], e["deal"], e["threshold"]
        cs = e["cost_structure"]

        self._biz_l_src.setText(
            "真源 %s @ %s ＋ %s ｜ 算法 tools/business_model.py ｜ 打开即现算, 派生值不落盘"
            % (os.path.basename(e["truth"]["cost"]), e["truth"]["business_mtime"],
               os.path.basename(e["truth"]["business"])))

        rows = [
            ["变动成本 (硬件/台)", "%.1f 万" % (cs["hardware_variable"] / 1e4),
             "随学习曲线下降 (10 台乘子 %.2f, 每翻倍降 %.0f%%)"
             % (cs["lc_10"], e["inputs"]["learning_rate"] * 100)],
            ["固定成本", "%.1f 万" % (cs["fixed_total"] / 1e4),
             "软件研发 %.1f 万 + 实施 NRE %.1f 万 ⇒ 靠规模摊薄"
             % (cs["software_dev"] / 1e4, cs["nre"] / 1e4)],
            ["首台单位成本", "%.1f 万" % (cs["first_unit_cost"] / 1e4),
             "研发按计划 %d 台摊销" % int(e["inputs"]["amortize_units"])],
            ["10 台单位成本", "%.1f 万" % (cs["unit_cost_10"] / 1e4), cs["logic"]],
        ]
        self._biz_t_struct.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                self._biz_t_struct.setItem(r, c, QTableWidgetItem(str(val)))

        self._biz_l_lay.setText(
            "客户真实回本（分层口径, 只对外报 C/D）\n"
            "  A 上限   %.2f 年   售价 ÷ (heads×人力)          人效 1.0 · 零 OPEX · 零 NRE（不得当承诺）\n"
            "  B +OPEX  %.2f 年   扣维护 %.0f%%·售价 + 复训 %.1f 万 + 软件年费 %.1f 万\n"
            "  C +人效  %.2f 年   η=%.3f = 结构 %.2f × 成功率 %.2f × uptime %.2f × CT比 %.2f\n"
            "  D +NRE   %.2f 年   客户真实投入（含实施 %.1f 万）← 报价只用这一层"
            % (lay["A_payback"], lay["B_payback"], e["inputs"]["maint_rate"] * 100,
               e["inputs"]["retrain_per_year"] / 1e4, e["inputs"]["software_fee_per_year"] / 1e4,
               lay["C_payback"], lay["eta"], e["inputs"]["eta_struct"], e["inputs"]["success_rate"],
               e["inputs"]["uptime"], lay["ct_ratio"], lay["D_payback"], lay["nre"] / 1e4))
        self._biz_l_lay.setStyleSheet(self._biz_l_lay.styleSheet())

        _ok = dr["ok"]
        self._biz_l_deal.setText(
            "%s 成交区间: floor %.1f 万 %s ceiling %.1f 万（差 %+.1f 万）｜ 规模阈值 %s"
            % ("✅" if _ok else "❌", dr["floor"] / 1e4, "≤" if _ok else ">", dr["ceiling"] / 1e4,
               dr["gap"] / 1e4,
               ("%d 台" % th_["units"]) if th_ else ">500 台（改配置, 不降价）"))
        self._biz_l_deal.setStyleSheet("background:transparent;color:%s;"
                                      % ("#3fb950" if _ok else "#f85149"))

        prow = []
        for p in e["phases"]:
            price = "0（不收费）" if p["price"] == 0 else "%.1f 万" % (p["price"] / 1e4)
            if p["stage"].startswith("S3"):
                price = "%.1f 万/台 · 合计 %.1f 万" % (p["unit_price"] / 1e4, p["total"] / 1e4)
            prow.append([p["stage"], str(p["units"]), price, p["risk"], p["decision"]])
        self._biz_t_phase.setRowCount(len(prow))
        for r, row in enumerate(prow):
            for c, val in enumerate(row):
                self._biz_t_phase.setItem(r, c, QTableWidgetItem(str(val)))

        self._biz_l_rec.setText("推荐模式: %s   （%s）"
                                % (e["modes"]["recommend"], e["modes"]["rule"]))
        mrow = []
        for m in e["modes"]["options"]:
            price = ("%.1f 万" % (m["price"] / 1e4)) if m.get("price") else (
                "%.3f 元/颗" % m["per_part"] if m.get("per_part") else "—")
            margin = ("%.0f%%" % (m["margin"] * 100)) if m.get("margin") is not None else "—"
            mark = "★ " if m["mode"] == e["modes"]["recommend"] else ""
            mrow.append([mark + m["mode"], price, margin,
                         m["cond"] + ("  ✅" if m["fit"] else "  ❌"), m["note"]])
        self._biz_t_mode.setRowCount(len(mrow))
        for r, row in enumerate(mrow):
            for c, val in enumerate(row):
                it = QTableWidgetItem(str(val))
                if c == 0 and str(val).startswith("★"):
                    it.setForeground(QColor("#3fb950"))
                self._biz_t_mode.setItem(r, c, it)

        cf = e["configs"]
        oks = [r for r in cf["rows"] if r["ok"]]
        oks.sort(key=lambda r: r["ceiling"])
        self._biz_l_conf.setText(
            "改配置的量化出口（不降价）: floor %.1f 万固定, 只有 heads 足够大才进区间 ⇒ 成立 %d/%d 组；"
            "最小成立: %s"
            % (cf["floor"] / 1e4, cf["ok_count"], len(cf["rows"]),
               ("%d 工位 × %d 班 = %d 人, 上限 %.1f 万"
                % (oks[0]["stations"], oks[0]["shifts"], oks[0]["heads"], oks[0]["ceiling"] / 1e4))
               if oks else "无（需换更便宜的臂或卖软件授权）"))

        vs = e["value_split"]
        rs = e["risk_split"]
        self._biz_l_split.setText(
            "价值分配: " + " · ".join("%s %s %.1f 万" % (v["who"], v["item"],
                                                      (v["amount"] or 0) / 1e4) for v in vs if v["amount"])
            + "\n风险承担: " + " → ".join("%s 我方: %s" % (r["phase"], r["ours"]) for r in rs)
            + "\n" + e["profit_where"])

        if verbose:
            self._log_cc("🧩 商业模式: " + e["summary_line"])
        return e

    def _biz_save(self):
        try:
            r = self._biz_m.save_inputs(**self._biz_inputs())
        except Exception as _e:                                             # noqa: BLE001
            self._biz_log.setText("⛔ 写回假设真源失败: %r" % (_e,))
            self._log_cc("⛔ 商业模式假设写回失败: %r" % (_e,))
            return
        if r.get("ok"):
            self._biz_d = self._biz_m.load()
            self._biz_refresh()
            self._biz_log.setText("✅ 已写回 %s (备份 %s) · 回读校验通过 · 改动 %s"
                                  % (os.path.basename(r["path"]), os.path.basename(r["backup"]),
                                     ", ".join(r["changed"])))
            self._log_cc("🧩 商业模式假设已写回 config/platform/zmax_business_model.json: %s"
                         % ", ".join(r["changed"]))
        else:
            self._biz_log.setText("⚠ 已写盘但回读不一致 —— 别按这个数报价, 先看真源: %s" % r["path"])
            self._log_cc("⚠ 商业模式假设回读不一致: %s" % r["path"])

    def _biz_copy(self):
        e = getattr(self, "_biz_e", None)
        if not e:
            self._biz_log.setText("⚠ 还没有可复制的结果")
            return
        txt = self._biz_m.to_tsv(e)
        QApplication.clipboard().setText(txt)
        self._biz_log.setText("✅ 已复制 TSV 到剪贴板 (%d 行) —— 直接贴 Excel / 邮件" % len(txt.splitlines()))
        self._log_cc("🧩 商业模式结果已复制 (TSV)")

    def _biz_export(self):
        e = getattr(self, "_biz_e", None)
        if not e:
            self._biz_log.setText("⚠ 还没有可导出的结果")
            return
        try:
            p = self._biz_m.export(e)
            j = json.load(open(p["json"], encoding="utf-8"))
            ok = (abs(float(j["deal"]["floor"]) - float(e["deal"]["floor"])) < 1e-6
                  and len(j["phases"]) == len(e["phases"]))
            self._biz_log.setText(("✅ 已导出 " if ok else "⚠ 导出回读不一致 ") + p["json"]
                                  + "  +  " + os.path.basename(p["md"]))
            self._log_cc("🧩 商业模式已导出: %s" % p["json"])
        except Exception as _e:                                             # noqa: BLE001
            self._biz_log.setText("⛔ 导出失败: %r" % (_e,))

    def _pv_tab_index(self):
        """文档预览所在页 —— 2026-10-15 老倪: 「取消文档预览页面, 合并到 文档配置页面」
        ⇒ 预览控件现在就在「📄 文档配置」页里 (兼容旧名兜底)。"""
        i = self._tab_index_by_title("文档配置")
        if i >= 0:
            return i
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
        _rows.append("   正文预览就在本页下方 (原「📄 文档预览」页已并入); 一致性核对在文档页最后一列。")
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

    def _work_area_need(self):
        """当前配置面**装下主内容**所需的最小高度 (只算当前页; 页已包 QScrollArea)。

        老倪 2026-10-15: 「任务配置的窗口, 太矮了, 看不到任务」—— 底部信息窗原来**无条件**
        按"窗口高度的 50%"(最多 460px) 取走空间, 上方工作区只剩不到一半 ⇒ 任务表被压扁。
        这里把当前页真实的 minimumSizeHint 算出来, 给 _fit_out 当"工作区优先"的判据。
        """
        try:
            _sa = self.tabs.widget(self.tabs.currentIndex())
            if isinstance(_sa, QScrollArea):
                _inner = _sa.widget()
                _h = int(_inner.minimumSizeHint().height()) if _inner is not None else 0
                return _h + int(self.tabs.tabBar().height()) + 8 if _h > 0 else 0
        except Exception:                                                       # noqa: BLE001
            pass
        return 0

    def _fit_out(self):
        """给底部信息窗一次**按内容算**的高度 (老倪口径: 不许挤/不许截断)。

        2026-10-15 改法: 原来是 `out.setFixedHeight(...)` ⇒ 用户**根本拖不动** (老倪: 「显示区太小,
        不能用鼠标拖动调整大小」)。现在只设**竖直分隔条的初始比例** —— 之后随用户拖; 用户拖过就不再覆盖
        (`_out_user_sized`), 想再自动一次点「↕ 自适应高度」。
        2026-10-15 第二轮 (老倪: 「任务配置的窗口太矮了, 看不到任务」): 再加一条**工作区优先** ——
        先保证上方配置面装得下自己的主内容, 剩下的才给信息窗 (信息窗本身可滚/可拖/可收起)。
        """
        try:
            if getattr(self, "_out_user_sized", False) or not getattr(self, "_out_on", True):
                return
            d = self.out.document()
            d.setTextWidth(max(200, self.out.viewport().width()))
            h = int(d.size().height()) + 44                      # + 头部一行按钮
            total = max(400, self.vsplit.height() or self.height())
            # 默认给够 (老倪 2026-10-15: 「显示区太小…看不到显示内容」) —— 窗口够高时至少 220px 起,
            # 但也不许把上方工作区挤没 (上限 = 高度的 50%, 最多 460)。
            _floor = 220 if total >= 700 else 150
            cap = int(min(460, max(_floor, self.height() * 0.50)))
            want = max(_floor, min(h, cap))
            # 🔴 工作区优先: 当前页的主内容 (任务表/配置表) 至少要放得下 —— 不够就把信息窗让到 _floor。
            _need = self._work_area_need()
            if _need > 0:
                want = max(_floor, min(want, total - _need))
            self.vsplit.setSizes([max(220, total - want), want])
        except Exception:  # noqa: BLE001
            pass

    def showEvent(self, _e):
        """首次真正显示时算一次信息窗高度 (构建时窗口高度还是 0, 算不出比例; 首帧默认会被压到最小值)。"""
        super().showEvent(_e)
        if not getattr(self, "_out_first_shown", False):
            self._out_first_shown = True
            self._fit_out()                       # 立刻算 (同步, 不等事件循环): 首帧就要给够高度
            from PyQt5.QtCore import QTimer as _QT
            _QT.singleShot(0, self._fit_out)      # 布局真正落定后再校一次
        # 🆕 2026-10-15 老倪「元任务窗口太矮了, 调高适配」——
        #   分隔条现在靠**两舱的最小高度**定尺寸 (在 _build_tabs 里设的), 不依赖"显示后补算",
        #   所以这里不再需要一次性 seed; 只有"老倪自己拖过"这个标记要留着 (见 _on_tm_split_moved)。
        # 🎯 2026-10-17 老倪「宽度我改成 170 / 100 / 120 都没生效」——
        #   配置中心窗口是**复用**的 (再点不新开第二个), 宽度只在**构造**时读一次
        #   config/platform/zmax_ui_layout.json ⇒ 改完数值再点开 = 同一个 page, 不重读。
        #   这里每次显示/切回都重读一次 (数没变就不动, 保留手拖的结果)。
        try:
            from PyQt5.QtCore import QTimer as _QT2
            _QT2.singleShot(0, self._reapply_tree_width)
        except Exception:                                                       # noqa: BLE001
            pass

    def _on_tm_split_moved(self, *_a):
        """老倪自己拖过 ⇒ 记下来, 不再被自动覆盖。"""
        self._tm_user_sized = True

    def _fit_out_clicked(self):
        """「↕ 自适应高度」: 清掉"用户拖过"的标记, 再按内容给一次高度 (之后仍可自由拖)。"""
        self._out_user_sized = False
        if not getattr(self, "_out_on", True):
            self._toggle_out()
        self._fit_out()

    def _on_vsplit_moved(self, *_a):
        """用户拖动分隔条 ⇒ 记住"这是你要的高度", 不再自动覆盖。"""
        self._out_user_sized = True

    def _toggle_out(self):
        """显示/隐藏底部信息窗 (老倪 2026-10-15: 「要可以隐藏」)。"""
        self._out_on = not getattr(self, "_out_on", True)
        self.out_box.setVisible(self._out_on)
        _h = getattr(self, "out_hint", None)
        if _h is not None:
            _h.setText(("📍 信息窗 — 内容随「当前配置面」自动对应 · 拖上方分隔条调高度 · 点右侧「收起」可隐藏"
                        if self._out_on else
                        "📍 信息窗已收起 —— 点「▴ 展开信息窗」恢复 (收起后上方工作区拿回全部高度)"))
        self.b_out.setText("▾ 收起信息窗" if self._out_on else "▴ 展开信息窗")
        if self._out_on:
            _want = 240
            _total = max(400, self.vsplit.height() or self.height())
            self.vsplit.setSizes([max(220, _total - _want), _want])
            self.out.setVisible(True)

    def _page_out_text(self, tab_title=""):
        """**当前配置面**该显示的信息 (老倪 2026-10-15: 「选择相应的配置面时, 信息没有对应上」)。

        每一面一行: 是哪颗星 · 这一面是什么 · 本页真源摘要 (现算); 再补 1~2 行"真源在哪/怎么改"。
        读不到就写「取不到」, 不退回上一页的旧内容。
        """
        t = (tab_title or self.tabs.tabText(self.tabs.currentIndex())).strip()
        facts = _star_facts()
        keys = next((ks for kw, ks in getattr(_ss, "TAB_STAR_RULES", ()) if kw in t), ())
        L = ["📍 当前配置面: %s" % t,
             "   (随左侧/页签选择自动对应 · 拖上方分隔条调高度 · 点「▾ 收起信息窗」可隐藏)"]
        for k in keys:
            s = _ss.BY_KEY.get(k) or {}
            L.append("   %s %s · %s（%s） — %s" % (s.get("i_cn", ""), s.get("name", k), s.get("star", ""),
                                                 s.get("alias", ""), facts.get(k, "取不到")))
        try:
            if "产品配置" in t:
                _i = _zmax_platform_info() or {}
                L.append("   平台: " + " · ".join((_i.get("lines") or ["取不到"])[1:]))
                L.append("   真源: %s —— 单选即**原子写回** active_product (质数不动); 下面两张表 = 「🏭 Z-MAX 平台」页同源"
                         % (_i.get("src") or "取不到"))
            elif "任务配置" in t:
                _tk = _j(TASKS_J, {}) or {}
                _bd = _j(BIND_J, {}) or {}
                _ts = _tk.get("tasks", []) or []
                L.append("   任务(%d): %s" % (len(_ts), " · ".join(str(x.get("id", "?")) for x in _ts[:9])))
                L.append("   绑定真源 %s · active_task=%s"
                         % (os.path.relpath(BIND_J, ROOT), _bd.get("active_task") or "—"))
            elif "功能配置" in t:
                from zmax_platform_info import platform_page_data as _ppd, function_summary as _fs
                _f = _ppd().get("functions") or []
                L.append("   功能清单汇总: %s" % (_fs(_f)["text"] if _f else "取不到"))
                L.append("   真源: 单一工程库 functions 表 (系统 2/1/0 + 平台支撑); 本页功能表 %d 行" % len(_f))
                try:                                    # 专利渠道 (老倪: 预留所有功能的专利申请渠道)
                    import patent_center as _pcm                                        # noqa: PLC0415
                    _c = _pcm.coverage()
                    L.append("   专利渠道: %d/%d 条功能已挂 (专利 %d 件) · 真源 %s"
                             % (_c["covered"], _c["total_fn"], _c["n_patent"], _c["src"]))
                    L.append("   「📜 该功能专利申请草稿」= 选中一行功能后打开它主挂专利的申请文件正文")
                except Exception:                                                       # noqa: BLE001
                    pass
            elif "模型配置" in t:
                from zmax_platform_info import layer_summary as _ls2, function_layer_map as _flm2
                _l2, _f2 = _ls2(), _flm2()
                L.append("   功能 ←→ 层模型 映射: 全量 %d 条 (真源 %s × %s)"
                         % (_f2["total"], _l2["src"], _f2["src_functions"]))
                L.append("   四层在役: " + " | ".join(
                    "%s=%s%s" % (r["layer"], r["model"], ("(+%d 附加)" % len(r["extra"])) if r["extra"] else "")
                    for r in _l2["rows"]))
                _mt = getattr(self, "match_table", None)
                L.append("   本页还含 模型配置参数表 + 模型 ↔ 工程配置 9 项匹配表 (%s 行)"
                         % getattr(_mt, "rowCount", lambda: "—")())
                _cs = [c for c in (_j(MCD_J, {}) or {}).get("CHARACTERISTIC", []) if c.get("domain") == "模型配置"]
                L.append("   模型配置参数 %d 条 · 就绪 %d · 未就绪 %d · 真源 %s"
                         % (len(_cs), sum(1 for c in _cs if c.get("ready")),
                            sum(1 for c in _cs if not c.get("ready")), os.path.relpath(MCD_J, ROOT)))
            elif "性能配置" in t:
                _cs = [c for c in (_j(MCD_J, {}) or {}).get("CHARACTERISTIC", []) if c.get("domain") == "性能配置"]
                L.append("   性能配置参数 %d 条 · 就绪 %d · 未就绪 %d"
                         % (len(_cs), sum(1 for c in _cs if c.get("ready")),
                            sum(1 for c in _cs if not c.get("ready"))))
                L.append("   真源: %s" % os.path.relpath(MCD_J, ROOT))
            elif "文档配置" in t:
                try:                                    # 专利与 SOR/立项/合作协议 同级 (老倪 2026-10-15)
                    import patent_center as _pcm2                                       # noqa: PLC0415
                    _c2 = _pcm2.coverage()
                    L.append("   四类文档同页同级: SOR / 项目立项 / 合作协议 / **专利 (%d 件)** —— 导出+预览同一通道"
                             % _c2["n_patent"])
                    L.append("   专利渠道: %d/%d 条功能已挂 · 真源 %s · 产物 docs/patents/"
                             % (_c2["covered"], _c2["total_fn"], _c2["src"]))
                except Exception:                                                       # noqa: BLE001
                    pass
                _dm = [_doc_mark(k) for k in ("sor", "project", "agreement")]
                L.append("   三份交付文档: 项目立项 %s · 供应商 SOR %s · 合作协议 %s (✅就绪 / ⛔过期或未生成)"
                         % (_dm[1], _dm[0], _dm[2]))
                L.append("   本页 = 导出按钮 + 产物清单 + **正文预览** (原「文档预览」页已并入)")
                # 2026-10-19: 工单 / 成本报价 / 商业模式 三块迁入本页 (都在"记录与导出"这一阵)
                _bs2 = _orders_list()
                L.append("   + 工单实例 %d 份 (原「🧾 工单配置」页, 点工单号看完整配置面) · 真源 config/orders/BS_*.json"
                         % len(_bs2))
                L.append("   + 成本/报价 (tools/cost_model.py 现算) · 商业模式 (tools/business_model.py 现算) —— 均不落盘派生值")
            elif "工程配置" in t:
                _cs = [c for c in (_j(MCD_J, {}) or {}).get("CHARACTERISTIC", []) if c.get("domain") == "工程配置"]
                L.append("   第六阵 开阳·工程配置 (定落地): 工程库 / 参数注册表 / 工程-模型匹配 / AR 示教点位")
                L.append("   工程域参数 %d 条 · 真源 %s" % (len(_cs), os.path.relpath(MCD_J, ROOT)))
                _mt2 = _j(MATCH_J, {}) or {}
                L.append("   工程-模型匹配 %d 个模型 (九类站点能力) · 真源 %s"
                         % (len(_mt2.get("MODELS", [])), os.path.relpath(MATCH_J, ROOT)))
                L.append("   工单实例已移出本阵 ⇒ 见「📄 文档配置」(第七阵 瑶光·定记录)")
                L.append("   本页还带 AR 场景示教点位表 (可复制 / 导出 TSV)")
        except Exception as _e:                                                 # noqa: BLE001
            L.append("   ⛔ 本面信息取不到: %r" % (_e,))
        return "\n".join(L)

    def _sync_out_for(self, *_a):
        """选面(换页签/点左树)时把信息窗刷成**这一面**的信息; 页面内动作(导出/复制/定位)仍覆盖成它的结果。"""
        if not getattr(self, "_out_auto", True):
            return
        try:
            self.out.setPlainText(self._page_out_text())
            self._fit_out()
        except Exception:                                                       # noqa: BLE001
            pass

    def _run_into(self, fn, **kw):
        self.out.setPlainText(_run(fn, **kw))
        self._fit_out()


def build_config_center(model_page=None, theme=None):
    """studio.py 调用入口: 返回配置中心新页 (失败时抛异常, 由 studio 兜底回退)。"""
    return ConfigCenterPage(model_page=model_page, theme=theme)
