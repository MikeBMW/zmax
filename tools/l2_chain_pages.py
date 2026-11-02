#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L2 逐节点页 + 节拍测试报告页 (老倪 2026-11-02)

「L2 层独立运行, 每个节点的功能定义/输入输出都追加到解决方案, 要有节拍测试报告, 保证 300 UPH;
 从最后输出节点开始, 依次向前序节点增加 PPT 页, 每个点一页。」

做法:
  · 节点集合/名称/连线 = 画布真源 (data/database/zmax/sources/canvas/state_space_obs.json)
  · 功能定义/端口/参数/实现位置 = 节点实现文件 (src/lerobot/middleware/nodes/<mod>.py, 经 _index.NODE_MODULES)
  · 顺序 = 从「无下游」的输出节点起, 沿画布 links 反向 BFS, 末端编号 1
  · 节拍页 = tools/l2_uph_measure.py 现算 (引擎 cap=l2 真跑 + 段表计划/实测两口径)

用法: 由 tools/build_solution_deck.py 调用; 也可单独:
      ./gui-venv311/bin/python tools/l2_chain_pages.py <deck.pptx>
"""
from __future__ import annotations

import importlib
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))

from pptx.util import Inches, Pt                                    # noqa: E402
from pptx.dml.color import RGBColor                                 # noqa: E402
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR                       # noqa: E402
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR               # noqa: E402
from pptx.oxml.ns import qn                                          # noqa: E402

CANVAS = os.path.join(ROOT, "data/database/zmax/sources/canvas/state_space_obs.json")
C_TXT = RGBColor(0x1F, 0x2A, 0x37)
C_DIM = RGBColor(0x5B, 0x6B, 0x7C)
C_ACC = RGBColor(0x1F, 0x6F, 0x8B)
C_BG = RGBColor(0xEE, 0xF4, 0xF8)
C_WARN = RGBColor(0xB0, 0x3A, 0x2E)
C_OK = RGBColor(0x1E, 0x7A, 0x46)
C_UP_FILL = RGBColor(0xF1, 0xF4, 0xF7)
C_DN_FILL = RGBColor(0xF1, 0xF4, 0xF7)
C_BOXLINE = RGBColor(0xC2, 0xCC, 0xD6)
C_ON = RGBColor(0x2E, 0xA0, 0x4E)
C_OFF = RGBColor(0x9A, 0xA4, 0xAE)


def _canvas():
    with open(CANVAS, encoding="utf-8") as f:
        return json.load(f)


def _mod_info(nid):
    """节点实现信息: 名称/端口/参数/实现位置/PURE。取不到就给空壳 (页面照样出, 标'无实现文件')。"""
    try:
        from lerobot.middleware.nodes._index import NODE_MODULES
        mod = NODE_MODULES.get(nid)
        if not mod:
            return None, {}
        m = importlib.import_module(mod)
        return mod, {k: getattr(m, k, None) for k in
                     ("NAME", "LAYER", "TYPE", "EXEC_MODE", "PORTS_IN", "PORTS_OUT",
                      "PARAMS", "PURE", "SOURCE", "SOURCE_SYMBOL", "IMPL_KEY", "LAST_STATUS")}
    except Exception:                                               # noqa: BLE001
        return None, {}


def l2_nodes():
    """L2 节点 = 画布上 7 条 L2 带 (row_mem_l2/ssbg0..4/ssbg_skill) 带内的节点 (与 L2 连线页同一口径)。"""
    import l2_wiring as LW
    d = _canvas()
    nodes = {n["id"]: n for n in d["nodes"] if n.get("type") not in ("row_bg", "band", "bg", "group")}
    c = LW.load_canvas()
    return nodes, set(c["l2"]), d["links"]


def _scc(nodes_set, out):
    """Tarjan 强连通分量 (画布有反馈回路, 不能直接拓扑排)。"""
    idx, low, on, st, comp = {}, {}, set(), [], []
    counter = [0]

    def visit(v):
        idx[v] = low[v] = counter[0]
        counter[0] += 1
        st.append(v)
        on.add(v)
        for w in sorted(out.get(v) or ()):
            if w not in idx:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], idx[w])
        if low[v] == idx[v]:
            c = []
            while True:
                w = st.pop()
                on.discard(w)
                c.append(w)
                if w == v:
                    break
            comp.append(c)

    for v in sorted(nodes_set):
        if v not in idx:
            visit(v)
    return comp


_MAIN_POS = ("动作命令", "真下发", "段表", "plan → exec", "到位", "命令")
_SIDE_NEG = ("只喂渲染", "旁路", "回显", "上网通道", "默认关", "proxy", "AR 场景")


def _link_score(k):
    """主信号流优先: in1 主线 + 动作/真下发/段表 ⇒ 加分; 只喂渲染/旁路/可选项 ⇒ 减分。"""
    lab = str(k.get("label") or "")
    sc = 0
    if k.get("t_port") == "in1":
        sc += 2
    if any(x in lab for x in _MAIN_POS):
        sc += 3
    if any(x in lab for x in _SIDE_NEG):
        sc -= 3
    return sc


def chain_order(l2, links):
    """逆序主链优先: 从末端(无 L2 下游)出发, 每步先走「主输入」, 再走旁支。

    老倪 2026-11-02: 「机器人执行器之前, 应该是动作执行器」—— 也就是页序必须按**信号流主线**排
    (物理世界 ← 机器人执行器 ← 动作执行器 ← 运动规划 ← …), 不许按坐标/深度把技能支线插进来。
    画布 y/x 只做主输入的并列 tie-break; 一个节点都没漏: 主链走完再补旁支(同规则 DFS)。
    """
    nodes, _, _ = l2_nodes()
    out_l2 = {n: set() for n in l2}
    in_l2 = {n: set() for n in l2}
    for k in links:
        f, t = k.get("f"), k.get("t")
        if f in l2 and t in l2:
            out_l2[f].add(t)
            in_l2[t].add(f)

    # 深度 = 离源头最长路径 (SCC 压缩, 回路不参与分层) —— 只用来选「从哪开始」和补旁支顺序
    comps = _scc(l2, out_l2)
    cid = {v: i for i, c in enumerate(comps) for v in c}
    cout = {i: set() for i in range(len(comps))}
    for v, ws in out_l2.items():
        for w in ws:
            if cid[v] != cid[w]:
                cout[cid[v]].add(cid[w])
    cin = {i: set() for i in range(len(comps))}
    for i, ws in cout.items():
        for w in ws:
            cin[w].add(i)
    dep = {i: 0 for i in range(len(comps))}
    for _ in range(len(comps)):
        for i in sorted(cout):
            dep[i] = max([dep[j] + 1 for j in cin[i]], default=dep[i])

    ups = {}
    for k in links:
        f, t = k.get("f"), k.get("t")
        if f in l2 and t in l2:
            ups.setdefault(t, []).append(k)

    def _key(k):
        v = k.get("f")
        return (-_link_score(k), -(nodes[v]["y"] if v in nodes else 0),
                -(nodes[v]["x"] if v in nodes else 0))

    order, seen = [], set()

    def _walk(n):
        if n in seen:
            return
        seen.add(n)
        order.append(n)
        for k in sorted(ups.get(n, []), key=_key):
            _walk(k.get("f"))

    # ① 主链起点 = 「最后输出端」: L2 下游只剩反馈边(↩ 观测反馈)的节点 (= 物理世界)
    fb_only = []
    for n in l2:
        downs = [k for k in links if k.get("f") == n and k.get("t") in l2]
        if all(("反馈" in str(k.get("label") or "")) or str(k.get("label") or "").startswith("↩")
               for k in downs):
            fb_only.append(n)
    starts = sorted(fb_only, key=lambda v: (-dep[cid[v]], -(nodes[v]["y"] if v in nodes else 0), v))
    starts += sorted([v for v in l2 if v not in fb_only],
                     key=lambda v: (-dep[cid[v]], -(nodes[v]["y"] if v in nodes else 0), v))
    for n in starts:
        _walk(n)
    return order, out_l2, in_l2


# ───────────────────────────────────────────── 画页小工具
def _slide(pr):
    return pr.slides.add_slide(pr.slide_layouts[6])


def _txt(s, x, y, w, h, text, size=8, bold=False, color=C_TXT, spacing=1.12, align=None):
    tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0.03)
    tf.margin_top = tf.margin_bottom = 0
    for i, line in enumerate(str(text).split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.line_spacing = spacing
        if align is not None:
            p.alignment = align
        r = p.add_run()
        r.text = line
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.color.rgb = color
        r.font.name = "Microsoft YaHei"
    return tb


def _panel(s, x, y, w, h, fill=C_BG, line=None):
    sh = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    sh.adjustments[0] = 0.04
    sh.fill.solid()
    sh.fill.fore_color.rgb = fill
    if line is None:
        sh.line.fill.background()
    else:
        sh.line.color.rgb = line
        sh.line.width = Pt(0.75)
    sh.shadow.inherit = False
    return sh


def _cut(t, n):
    t = str(t or "")
    return t if len(t) <= n else t[:n - 1] + "…"


def _layer_of(nid, nodes, l2):
    n = nodes.get(nid) or {}
    nm = str(n.get("name") or nid)
    if nid in l2:
        return "L2"
    for tag in ("L5", "L4", "L3", "L2", "L1"):
        if nm.startswith(tag):
            return tag
    return "层外"


def _box(s, x, y, w, h, head, sub="", port="", size=7.4, fill=None, line=None, head_color=C_TXT):
    """方框 = 一个节点 (块图里的一个块)。head=节点名, sub=连线说明, port=端口名。"""
    sh = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    sh.adjustments[0] = 0.10
    sh.fill.solid()
    sh.fill.fore_color.rgb = fill or C_BG
    if line is None:
        sh.line.fill.background()
    else:
        sh.line.color.rgb = line
        sh.line.width = Pt(0.9)
    sh.shadow.inherit = False
    tf = sh.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0.05)
    tf.margin_top = tf.margin_bottom = Inches(0.01)
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    parts = [("  ".join(x for x in (port, head) if x), head_color, True),
             (sub, C_DIM, False)]
    tot = len(port) + len(head) + 2          # 首行字数: 超框就缩字号, 不截断名字
    if tot > 24:
        size = size * 0.74
    elif tot > 18:
        size = size * 0.86
    first = True
    for txt, col, bold in parts:
        if not txt:
            continue
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.line_spacing = 1.0
        p.alignment = PP_ALIGN.CENTER
        r = p.add_run()
        r.text = txt
        r.font.size = Pt(size if bold else size - 1.0)
        r.font.bold = bold
        r.font.color.rgb = col
        r.font.name = "Microsoft YaHei"
    return sh


def _line(s, x1, y1, x2, y2, arrow=False, color=None, w=1.0):
    """连线: 直线 (块图的母线/支线), arrow=True 时末端加三角箭头。"""
    conn = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    conn.line.color.rgb = color or RGBColor(0x6B, 0x7A, 0x8C)
    conn.line.width = Pt(w)
    if arrow:
        ln = conn.line._get_or_add_ln()
        end = ln.makeelement(qn("a:tailEnd"), {"type": "triangle", "w": "sm", "len": "sm"})
        ln.append(end)
    return conn


def _switch_state():
    """两个开关的真值: 优先画布开关写出的 zmax_data/ss_live/exec_switches.json (5 分钟内算新鲜),
    否则回落画布节点 params (ar_scene / real_auth)。"""
    f = os.path.join(ROOT, "zmax_data/ss_live/exec_switches.json")
    try:
        import time as _t
        d = json.load(open(f, encoding="utf-8"))
        age = _t.time() - float(d.get("t") or 0)
        return {"ar": bool(d.get("ar_scene")), "real": bool(d.get("real_auth")),
                "age": age, "t_str": d.get("t_str"), "src": d.get("src") or "exec_switches.json",
                "fresh": age < 1800, "from": "exec_switches.json"}
    except Exception as _e:                                              # noqa: BLE001
        return {"ar": False, "real": False, "age": None, "t_str": "-",
                "src": "读不到 (%s)" % type(_e).__name__, "fresh": False, "from": "none"}


def _toggle(s, x, y, on, w=0.68, h=0.26):
    """拨杆开关: 胶囊 + 白色圆钮 (开=绿钮在右, 关=灰钮在左)。"""
    pill = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    pill.adjustments[0] = 0.5
    pill.fill.solid()
    pill.fill.fore_color.rgb = C_ON if on else C_OFF
    pill.line.fill.background()
    pill.shadow.inherit = False
    kd = h - 0.05
    kn = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x + (w - kd - 0.025) if on else x + 0.025),
                            Inches(y + 0.025), Inches(kd), Inches(kd))
    kn.fill.solid()
    kn.fill.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    kn.line.fill.background()
    kn.shadow.inherit = False


def _switch_band(s, y0, params):
    """画布 🤖 机器人执行器 上那对开关 (AR 场景 / 真机), 状态不手填: 读 exec_switches.json。"""
    st = _switch_state()
    _panel(s, 0.5, y0, 12.33, 1.36)
    _txt(s, 0.66, y0 + 0.07, 11.9, 0.22,
         "🎛 与画布同一对开关 · 真源 zmax_data/ss_live/exec_switches.json（%s）"
         % ("新鲜" if st["fresh"] else "⚠ 已过期/读不到"), size=8.4, bold=True, color=C_ACC)
    rows = [
        ("AR 场景开关", st["ar"], "开 ⇒ 页面进 AR 模式: 双臂按 ar_cmd_chain 的 exec 分区走帧(exec_src=ssact, 10Hz) · 可与真机开关同时开",
         "关 ⇒ 页面退出 AR 模式(不再消费渲染指令) · 真机通路不受它影响"),
        ("真机开关", st["real"], "开 ⇒ 8793 授权窗口打开, 指令真下发（画布每拍绝不自动发; 与 AR 开关互不互斥）",
         "关 ⇒ 零下发：与 out1.real_send=false 一致, 只算不发"),
    ]
    for i, (lab, on, tx_on, tx_off) in enumerate(rows):
        yy = y0 + 0.38 + i * 0.44
        _toggle(s, 0.70, yy, on)
        _txt(s, 1.50, yy - 0.03, 1.5, 0.24, lab, size=9.4, bold=True)
        _txt(s, 2.98, yy - 0.03, 0.5, 0.24, "开" if on else "关", size=9.4, bold=True,
             color=C_ON if on else C_WARN)
        _txt(s, 3.52, yy - 0.02, 9.15, 0.24, _cut(tx_on if on else tx_off, 64), size=8.0,
             color=C_TXT if on else C_DIM)
    _txt(s, 0.66, y0 + 1.30 - 0.02, 11.9, 0.20,
         "开关状态时间 %s · 来源 %s · 刷新龄 %s · 两开关独立, 可同时开"
         % (st["t_str"] or "-", st["src"],
            ("%.0f s" % st["age"]) if st["age"] is not None else "-"), size=7.0, color=C_DIM)


def node_page(pr, nid, k, total, nodes, l2, links, out_l2, in_l2):
    """节点页: 一句话功能 + 输入输出块图 (块 = 节点, 线 = 画布连线, 箭头指向数据流向)。"""
    n = nodes[nid]
    mod, mi = _mod_info(nid)
    name = str(mi.get("NAME") or n.get("name") or nid)
    pure = mi.get("PURE")
    ports_in = mi.get("PORTS_IN") or []
    ports_out = mi.get("PORTS_OUT") or []
    params = mi.get("PARAMS") or (n.get("params") or {})

    ins = [k2 for k2 in links if k2.get("t") == nid]
    outs = [k2 for k2 in links if k2.get("f") == nid]

    s = _slide(pr)
    _txt(s, 0.5, 0.14, 12.3, 0.34, "L2 链路 %02d/%d · %s · %s" % (k, total, _cut(name, 40), nid),
         size=15, bold=True)
    desc = (params.get("desc") if isinstance(params, dict) else None) \
        or (n.get("params") or {}).get("desc") or "（该节点无 desc，见实现文件头）"
    _txt(s, 0.5, 0.48, 12.3, 0.26, _cut(desc, 70), size=9.2)
    _txt(s, 0.5, 0.74, 12.3, 0.22,
         "%s · %s/%s · 执行口径 %s · PURE %s · 端口 in %d / out %d"
         % (nid, (mi.get("LAYER") or "L2"), (mi.get("TYPE") or n.get("type") or "-"),
            (mi.get("EXEC_MODE") or "-"), ("真算" if pure else ("直通" if pure is False else "无实现")),
            len(ports_in), len(ports_out)), size=7.4, color=C_DIM)

    # ── 块图几何 (三列: 上游 | 本节点 | 下游); 带开关的节点(机器人执行器)下方留开关带
    SW = bool(isinstance(params, dict) and params.get("ar_real_sw"))
    A0, A1 = 1.28, (4.55 if SW else 6.28)
    UX, UW = 0.55, 3.75                     # 上游列
    NX, NW = 4.80, 3.55                     # 本节点
    DX, DW = 8.82, 3.95                     # 下游列
    BUS_L, BUS_R = 4.55, 8.58               # 两条母线
    cap = 8                                 # 每侧最多画 8 个块, 其余折成一行文字
    _txt(s, UX, A0 - 0.24, UW, 0.22, "输入（%d 条连线 · 端口 ← 上游）" % len(ins), size=8.6, bold=True, color=C_ACC)
    _txt(s, DX, A0 - 0.24, DW, 0.22, "输出（%d 条连线 · 端口 → 下游）" % len(outs), size=8.6, bold=True, color=C_ACC)

    def _col(items, x, w, side):
        """画一列的块 + 支线, 返回 (每块中心 y 列表, 末块下方 y)。"""
        ys = []
        n_show = min(len(items), cap)
        if not items:
            _txt(s, x + 0.1, (A0 + A1) / 2 - 0.12, w - 0.2, 0.24, "（无连线）", size=7.2, color=C_DIM)
            return ys, A0
        slot = (A1 - A0) / max(n_show + (1 if len(items) > cap else 0), 1)
        bh = min(0.62, slot - 0.06)
        for i, k2 in enumerate(items[:cap]):
            cy = A0 + slot * (i + 0.5)
            ys.append(cy)
            if side == "up":
                up = k2.get("f")
                port = k2.get("t_port") or ""
                _box(s, x, cy - bh / 2, w, bh, _cut(_upname(up, nodes), 22),
                     _cut(k2.get("label") or "", 16), port, fill=C_UP_FILL, line=RGBColor(0xC2, 0xCC, 0xD6))
                _line(s, x + w, cy, BUS_L, cy, w=0.9)
            else:
                dn = k2.get("t")
                port = k2.get("f_port") or ""
                _box(s, x, cy - bh / 2, w, bh, _cut(_upname(dn, nodes), 24),
                     _cut(k2.get("label") or "", 16), port, fill=C_DN_FILL, line=RGBColor(0xC2, 0xCC, 0xD6))
                _line(s, BUS_R, cy, x, cy, w=0.9)
        if len(items) > cap:
            _txt(s, x + 0.1, A0 + slot * (cap + 0.5) - 0.11, w - 0.2, 0.22,
                 "… 另 %d 条" % (len(items) - cap), size=7.0, color=C_DIM)
        return ys, A0 + slot * len(ys)

    up_y, up_end = _col(ins, UX, UW, "up")
    dn_y, dn_end = _col(outs, DX, DW, "dn")

    cy_mid = (A0 + A1) / 2
    nh = 1.55
    _box(s, NX, cy_mid - nh / 2, NW, nh, _cut(name, 26), "L2 · %s" % (mi.get("TYPE") or n.get("type") or "-"),
         nid, size=10.5, fill=RGBColor(0xDF, 0xEE, 0xF6), line=C_ACC)
    # 两侧母线 + 箭头 (汇入本节点 / 从本节点发出)
    if up_y:
        _line(s, BUS_L, min(up_y), BUS_L, max(up_y), w=1.2, color=C_ACC)
        _line(s, BUS_L, cy_mid, NX, cy_mid, arrow=True, w=1.4, color=C_ACC)
    if dn_y:
        _line(s, BUS_R, min(dn_y), BUS_R, max(dn_y), w=1.2, color=C_ACC)
        _line(s, NX + NW, cy_mid, BUS_R, cy_mid, arrow=True, w=1.4, color=C_ACC)
    _txt(s, BUS_L - 0.34, cy_mid - 0.34, 0.32, 0.22, "in", size=7.0, color=C_DIM, align=PP_ALIGN.RIGHT)
    _txt(s, NX + NW + 0.02, cy_mid - 0.36, 0.32, 0.22, "out", size=7.0, color=C_DIM)

    # ── 页脚: 实现位置 + 参数 (只留能核对的几项)
    if SW:
        _switch_band(s, A1 + 0.12, params)
        FY = 6.12
    else:
        FY = A1 + 0.10
    kv = []
    if isinstance(params, dict):
        for kk, vv in params.items():
            if kk in ("desc", "source", "source_symbol"):
                continue
            kv.append("%s=%s" % (kk, _cut(vv, 22) if not isinstance(vv, (dict, list)) else "<%d 项>" % len(vv)))
            if len(kv) >= 3:
                break
    _txt(s, 0.5, FY, 12.3, 0.24,
         "实现 = %s:%s · 话题 = ss.node.%s.<port>%s"
         % (_cut(mi.get("SOURCE") or "（无实现文件绑定）", 58), mi.get("SOURCE_SYMBOL") or "",
            nid, (" · 参数 " + " · ".join(kv)) if kv else ""), size=7.2, color=C_DIM)
    _txt(s, 0.5, FY + 0.26, 12.3, 0.24,
         "链路位置：逆序第 %d 位（1 = 最后输出端） · L2 内上游 %d / 下游 %d · L2 共 %d 个节点"
         % (k, len(in_l2[nid]), len(out_l2[nid]), total), size=7.2, color=C_DIM)
    return s


def _upname(nid, nodes):
    n = nodes.get(nid) or {}
    return str(n.get("name") or nid)


# ───────────────────────────────────────────── 节拍测试报告页
def tact_page(pr):
    import l2_uph_measure as U
    import l2_uph_closure as K
    from lerobot.memory import l2_store as S
    r = U.run_l2(104)
    live = json.load(open(os.path.join(ROOT, "data/memory/ar_muscle.json"), encoding="utf-8"))
    # 口径冻结: 页面数字与自检读同一份台账快照 (台账是活数据, 不冻结就会"值变了文案没变")
    # labels 必须一起冻结 —— 实测口径用逐段同 label 的实测均值, 只冻 kind 均值就对不上了
    S.put_ledger({k: {"n": v.get("n"), "mean_t": v.get("mean_t"), "plan_t": v.get("plan_t"),
                      "labels": v.get("labels") or {},
                      "ratio": (round(v["mean_t"] / v["plan_t"], 3) if (v.get("mean_t") and v.get("plan_t")) else None)}
                  for k, v in (live.get("kinds") or {}).items()}, writer="ss_mem_l2", src=live.get("src", ""))
    c = U.compute(led=live.get("kinds") or {})
    k = K.analyse(d=U.plan_from_api(), led=live.get("kinds") or {})
    tp, tm, st, sm = c["plan_tact"], c["meas_tact"], c["uph_plan"], c["uph_meas"]
    st_i, sm_i = round(st), round(sm)        # 页内整数 UPH 与自检 round() 同一取整, 不许一个截断一个四舍五入
    rows = c["rows"]
    need = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入"]
    miss = [x for x in need if x not in r["stages"]]
    lv = k["levers"]
    cm = {x["name"]: x for x in k["combos"]}
    c123 = cm["C1+C2+C3"]
    c1234 = cm["C1+C2+C3+C4"]
    fmo = k["fit_move"] or {}

    s = _slide(pr)
    _txt(s, 0.5, 0.16, 12.3, 0.34, "L2 节拍测试报告 · 独立运行%s · 300 UPH：计划口径达标 / 实测口径未达标" % ("通过" if (r["done"] and not miss) else "未通过"), size=15, bold=True)
    _txt(s, 0.5, 0.52, 12.3, 0.26,
         "真源：引擎 cap=l2 实跑（seed 104，不带 L3 编排）+ 段表 GET /api/sim_insert（%d 段）+ AR 台账逐 label 实测（建页时冻结快照，命中 %d/%d）"
         % (c["n_seg"], c["label_hit"], c["n_seg"]), size=7.8, color=C_DIM)

    _panel(s, 0.5, 0.86, 5.05, 2.05)
    _txt(s, 0.65, 0.94, 4.8, 0.24, "① L2 独立运行（七段闭环）", size=9, bold=True, color=C_ACC)
    _txt(s, 0.65, 1.20, 4.8, 1.6,
         "· done = %s · %d 步 · 快通道接管 %d 帧\n· 阶段：%s\n· 判据：七段全走 %s\n· 语义：无 L3 编排也能跑完整件循环"
         % (r["done"], r["steps"], r["mm_hits"], " → ".join(r["stages"]),
            "（缺 %s）" % miss if miss else "✅"),
         size=8.4, spacing=1.22)

    _panel(s, 5.75, 0.86, 7.08, 2.05)
    _txt(s, 5.9, 0.94, 6.8, 0.24, "② 节拍两口径（同一份段表 · 每件 %d 段）" % (c["n_seg"] // c["n_mod"]), size=9, bold=True, color=C_ACC)
    _txt(s, 5.9, 1.20, 6.8, 1.6,
         "· 计划口径（段表 t）：%.3f s/件 → %d UPH  %s\n· 实测口径（逐段同 label 台账 mean_t）：%.3f s/件 → %d UPH  %s\n· 目标 300 UPH ⇒ ≤ 12.000 s/件；实测口径差 %+.3f s/件\n· 段表原值：%.3f s / %s 件（tact_s %.3f）"
         % (tp, st_i, "✅" if st >= 300 else "❌", tm, sm_i, "✅" if sm >= 300 else "❌",
            c["gap"], c["loop"].get("dur", 0), c["loop"].get("mods", 0), c["loop"].get("tact_s", 0)),
         size=8.4, spacing=1.22)

    _panel(s, 0.5, 3.05, 12.33, 2.24)
    _txt(s, 0.65, 3.13, 12.0, 0.24, "③ 余量归因（每件增量，按吃掉节拍的多少排序）", size=9, bold=True, color=C_ACC)
    y = 3.42
    for xx, ww, hh in ((0.70, 1.5, "段类"), (2.20, 1.6, "计划/件 (s)"), (3.85, 1.6, "实测/件 (s)"),
                       (5.50, 1.4, "增量 (s)"), (6.95, 1.3, "段数/件"), (8.30, 2.6, "台账 mean_t (s)"),
                       (10.95, 1.7, "实测/计划")):
        _txt(s, xx, y, ww, 0.2, hh, size=7.6, bold=True, color=C_DIM)
    for i, row in enumerate(rows[:7]):
        yy = y + 0.24 + i * 0.205
        col = C_WARN if row["delta"] > 0.5 else C_TXT
        _txt(s, 0.70, yy, 1.4, 0.2, row["kind"], size=7.4, color=col)
        _txt(s, 2.20, yy, 1.6, 0.2, "%.3f" % row["plan_per_pc"], size=7.4, color=col)
        _txt(s, 3.85, yy, 1.6, 0.2, "%.3f" % row["meas_per_pc"], size=7.4, color=col)
        _txt(s, 5.50, yy, 1.4, 0.2, "%+.3f" % row["delta"], size=7.4, color=col)
        _txt(s, 6.95, yy, 1.3, 0.2, "%.1f" % row["segs_per_pc"], size=7.4, color=col)
        _txt(s, 8.30, yy, 2.6, 0.2, "%.3f" % (row["mean_t"] or 0), size=7.4, color=C_DIM)
        _txt(s, 10.95, yy, 1.7, 0.2, "×%.2f" % row["ratio"], size=7.4, color=col)

    _panel(s, 0.5, 5.38, 12.33, 1.80, fill=RGBColor(0xFD, 0xF3, 0xF1), line=C_WARN)
    _txt(s, 0.65, 5.46, 12.0, 0.24, "④ 结论与保 300 UPH 的收口路径（数字全部现算，不是估百分比）", size=9, bold=True, color=C_WARN)
    _txt(s, 0.65, 5.72, 12.0, 1.42,
         "· L2 能独立运行（七段闭环 %s）；300 UPH 只在计划口径成立（%d UPH），按台账同 label 实测代回是 %d UPH，差 %+.2f s/件。\n"
         "· 余量不在「臂慢」：move 每段固定开销 %.2f s 是段边界加减速（等效速度 %.0f mm/s），检测独占 %.2f s/件（%d 段 AOI）。\n"
         "· 三条收口：C1 段间连续化 −%.2f（每件 %.0f 处×%.2f s）、C2 双相机并检 −%.2f、C3 插拔提速 −%.2f ⇒ %.2f s/件 = %d UPH，仍差 %+.2f。\n"
         "· 再做到 C4 抬升加速度（up/down 每件 %.0f 段×0.20 = −%.2f）⇒ %.2f s/件 = %d UPH；C4 需先确认控制器加速度上限，真机未验证。复现：tools/l2_uph_closure.py"
         % ("✅" if (r["done"] and not miss) else "❌", st_i, sm_i, c["gap"],
            fmo.get("c_s") or 0, fmo.get("v_mm_s") or 0, k["ao_s"], k["ao_n"] // c["n_mod"],
            lv["C1_连续化"]["save"], lv["C1_连续化"]["n"], (fmo.get("c_s") or 0) * 0.6,
            lv["C2_检测并行"]["save"], lv["C3_插拔提速"]["save"], c123["tact_s"], round(c123["uph"]),
            c123["tact_s"] - 12.0, lv["C4_抬升加速度"]["n"], lv["C4_抬升加速度"]["save"],
            c1234["tact_s"], round(c1234["uph"])),
         size=7.4, spacing=1.16)
    return s


def add_block(pr, verbose=True):
    """在 验收页 之前插入: N 个节点页 (末端→上游) + 1 个节拍报告页。返回统计。"""
    nodes, l2, links = l2_nodes()
    order, out_l2, in_l2 = chain_order(l2, links)
    n0 = len(pr.slides._sldIdLst)
    # 验收页 = 现存最后一页 (总览里也提到"验收口径", 不能按关键词搜)
    accept_idx = n0 - 1
    _first = [sh.text_frame.text for sh in pr.slides[accept_idx].shapes if sh.has_text_frame]
    if not any("验收口径 · 复核方式" in t for t in _first):
        accept_idx = None
        for i, s in enumerate(pr.slides):
            if any(sh.has_text_frame and sh.text_frame.text.startswith("验收口径 · 复核方式")
                   for sh in s.shapes):
                accept_idx = i

    made = []
    for k, nid in enumerate(order, 1):
        node_page(pr, nid, k, len(order), nodes, l2, links, out_l2, in_l2)
        made.append(nid)
    tact_page(pr)

    # 重排: 新页插到 验收页 之前
    total = len(pr.slides._sldIdLst)
    new_ids = list(range(n0, total))
    if accept_idx is None:
        order_ids = list(range(0, total))
    else:
        order_ids = list(range(0, accept_idx)) + new_ids + [accept_idx] + \
                    list(range(accept_idx + 1, n0))
    _reorder(pr, order_ids)
    if verbose:
        print("L2 逐节点页 %d 页 (末端→上游) + 节拍报告 1 页 · 起始 %s" % (len(order), order[0]))
        print("   顺序: %s" % " ← ".join("%d.%s" % (i, n) for i, n in enumerate(order[:6], 1)))
    return {"nodes": len(order), "order": order, "pages_added": len(order) + 1}


def _reorder(pr, order):
    sldIdLst = pr.slides._sldIdLst
    ids = list(sldIdLst)
    for e in ids:
        sldIdLst.remove(e)
    for i in order:
        sldIdLst.append(ids[i])


def main(argv=None):
    argv = argv or sys.argv[1:]
    if not argv:
        print("用法: l2_chain_pages.py <deck.pptx>")
        return 2
    from pptx import Presentation
    pr = Presentation(argv[0])
    info = add_block(pr)
    pr.save(argv[0])
    print("→ %s (%d 页)" % (argv[0], len(pr.slides._sldIdLst)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
