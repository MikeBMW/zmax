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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from l2_node_prose import PROSE as _PROSE
from l2_node_ar import AR_PROSE as _AR                            # noqa: E402

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
C_SUB = RGBColor(0x44, 0x51, 0x60)


def _rect(s, x, y, w, h, fill, line=None, shape=MSO_SHAPE.RECTANGLE):
    sh = s.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    sh.fill.solid()
    sh.fill.fore_color.rgb = fill
    if line is None:
        sh.line.fill.background()
    else:
        sh.line.color.rgb = line
        sh.line.width = Pt(1)
    sh.shadow.inherit = False
    return sh
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


# 🔧 手工页序锚点 (老倪 2026-11-02: 「动力学约束放到 05/31, 重排 PPT」)
#   自动排序按信号流主线走; 但"物理可行闸"必须排在技能支线之前呈现 (技能是它的上游, 但表现形式是旁支)。
#   锚点只搬指定节点, 其余节点保持相对顺序不变 ⇒ 不改别人的先后, 只钉这一个位置。
PIN_POS = {"ssphys": 5,
           "sssk1": 6, "sssk2": 7, "sssk3": 8, "sssk4": 9,
           "sssk5": 10, "sssk6": 11, "sssk7": 12, "sssk8": 13,
           # 2026-11-02 老倪: 「万有引力节点提前到 16/31, 其它节点顺延」
           "ss_grav_h": 16,
           # 2026-11-02 老倪: 「前馈加速器提前到 17/31」
           "ssff": 17,
           # 2026-11-02 老倪: 「状态校正器提到 18/31」
           "ssinnov": 18,
           # 2026-11-02 老倪: 「先验动力学预测提到 19/31」
           "sspred": 19,
           # 2026-11-02 老倪: 「自适应状态估计器放到 20/31, 其它节点顺延」
           "ssest": 20,
           # 2026-11-02 老倪: 「测地线规划引导放到 21/31」
           "n_geoplan": 21,
           # 2026-11-02 老倪: 「统一状态空间放到 22/31」
           "ssobs": 22}

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
    return _apply_pins(order), out_l2, in_l2


def _apply_pins(order):
    """按 PIN_POS 把指定节点搬到 1-based 目标位, 其余相对顺序不变。"""
    for nid, pos in sorted(PIN_POS.items(), key=lambda kv: kv[1]):
        if nid not in order:
            continue
        order.pop(order.index(nid))
        order.insert(max(0, min(len(order), int(pos) - 1)), nid)
    return order


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
        size = size * 0.80
    elif tot > 18:
        size = size * 0.90
    size = max(size, 9.6)                    # 盒子里最小 9.6pt: 再挤就换行/截字, 不许缩到看不清
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
        r.font.size = Pt(size if bold else max(size - 1.0, 9.0))
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


def _port_cn(port):
    """端口名换成人话: in1 -> 输入1, out2 -> 输出2 (其它原样)。"""
    t = str(port or "")
    if t.startswith("in"):
        return "输入" + t[2:]
    if t.startswith("out"):
        return "输出" + t[3:]
    return t


def _strip_icon(name):
    """去掉节点名前面的图标与标点, 供叙述文字里直接念出名字。"""
    t = str(name or "")
    i = 0
    while i < len(t) and not (t[i].isalnum() or ("\u4e00" <= t[i] <= "\u9fff")):
        i += 1                      # 只跳图标与标点; 碰到字母/数字/汉字就停 —— "YOLO 目标检测" 不许被削成 "目标检测"
    return t[i:].strip() or t


def _io_prose(ins, outs, nodes):
    """把上下游接成一句人话: 谁给它什么、它把结果交给谁。"""
    def _names(keys):
        out = []
        for kk in keys:
            nm = _strip_icon(nodes.get(kk, {}).get("name") or kk)
            if nm and nm not in out:
                out.append(nm)
        return out
    up = _names([k.get("f") for k in ins])
    dn = _names([k.get("t") for k in outs])
    s = "在整条链上，它上游接着 %d 路信号" % len(ins)
    if up:
        s += "，主要来自%s%s" % ("、".join(up[:3]), ("等 %d 个节点" % len(up)) if len(up) > 3 else "")
    s += "；下游把结果交给"
    s += ("%s%s。" % ("、".join(dn[:3]), ("等 %d 个节点" % len(dn)) if len(dn) > 3 else "")) if dn else "（无下游）。"
    return s


_LOOP_TRACE = None


def _loop_trace():
    """常驻循环最近一拍里每个节点的实际状态与耗时 (读不到就返回空表)。"""
    global _LOOP_TRACE
    if _LOOP_TRACE is not None:
        return _LOOP_TRACE
    _LOOP_TRACE = {}
    try:
        d = json.load(open(os.path.join(ROOT, "zmax_data/ss_live/canvas_loop.json"), encoding="utf-8"))
        for t in d.get("traces") or []:
            _LOOP_TRACE[t.get("id")] = (t.get("status") or "", t.get("ms"))
    except Exception:                                                   # noqa: BLE001
        pass
    return _LOOP_TRACE


# 少数节点的"算没算"不能只看实现开关: 真正的计算发生在别处, 逐页如实写
LIVE_OVERRIDE = {
    "n_exec": ("运行实况：授权核对、逐段闸门与到位判断都在常驻执行进程里完成；"
               "画布上的这一页只读取执行回执（段号、到位、残差）再交给下游，自身不下发动作。"),
}


def _side_sentence(keys, nodes, head):
    """把上游/下游列成一句: 接哪几个节点、几条连线 (名字取自画布, 不写端口代号)。"""
    names = []
    for kk in keys:
        nm = _strip_icon(nodes.get(kk, {}).get("name") or kk)
        if nm and nm not in names:
            names.append(nm)
    if not names:
        return head % 0 + "（无连线）。"
    shown = "、".join(names[:4])
    more = (" 等 %d 个节点" % len(names)) if len(names) > 4 else ""
    return head % len(keys) + shown + more + "。"


def _live_prose(nid, pure):
    """如实说明这一拍算没算: 有实测读实测, 没实测按实现开关说清。"""
    if nid in LIVE_OVERRIDE:
        return LIVE_OVERRIDE[nid]
    st, ms = _loop_trace().get(nid, ("", None))
    cost = ("实测 %.2f 毫秒，约占 100 毫秒控制周期的 %.1f%%" % (ms, ms / 1.0)) if isinstance(ms, (int, float)) else None
    ran = "实现执行" in st or "理想" in st
    if pure is True and ran:
        return "运行实况：这一拍真实执行了内部算法" + ("，" + cost if cost else "") + "，不构成节拍瓶颈。"
    if pure is True and not ran:
        return "运行实况：内部算法已实现，本拍未进入常驻循环的调度清单（测量时该拍未排到它）。"
    if pure is False and ran:
        return ("运行实况：这一拍只做数据转发" + ("，耗时 " + cost.replace("实测 ", "") if cost else "")
                + "；内部算法在这一环尚未启用。")
    return "运行实况：内部算法尚未接入常驻循环，这一环目前只按连线把数据交给下游。"


def _moveit_status():
    """运动规划页的真源行: 容器里 MoveIt 最近一轮规划 + 节点会不会用它 (与 plan_impl 同一判据)。"""
    try:
        if os.path.join(ROOT, "src") not in sys.path:
            sys.path.insert(0, os.path.join(ROOT, "src"))
        from lerobot.engineering.nodes import moveit_backend as _MB
        s = _MB.snapshot() or {}
        return s
    except Exception as _e:                                              # noqa: BLE001
        return {"ok": False, "why": "读不到 moveit_backend (%s)" % type(_e).__name__}


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
         "🎛 与画布同一对开关 · 状态取自 zmax_data/ss_live/exec_switches.json（%s）"
         % ("新鲜" if st["fresh"] else "⚠ 已过期/读不到"), size=9.6, bold=True, color=C_ACC)
    rows = [
        ("AR 场景开关", st["ar"], "开 ⇒ 页面进 AR 模式: 双臂按 ar_cmd_chain 的 exec 分区走帧(exec_src=ssact, 10Hz) · 可与真机开关同时开",
         "关 ⇒ 页面退出 AR 模式(不再消费渲染指令) · 真机通路不受它影响"),
        ("真机开关", st["real"], "开 ⇒ 8793 授权窗口打开, 指令真下发（画布每拍绝不自动发; 与 AR 开关互不互斥）",
         "关 ⇒ 零下发：与配置项 real_send=false 一致, 只算不发"),
    ]
    for i, (lab, on, tx_on, tx_off) in enumerate(rows):
        yy = y0 + 0.38 + i * 0.44
        _toggle(s, 0.70, yy, on)
        _txt(s, 1.50, yy - 0.03, 1.5, 0.24, lab, size=9.4, bold=True)
        _txt(s, 2.98, yy - 0.03, 0.5, 0.24, "开" if on else "关", size=9.4, bold=True,
             color=C_ON if on else C_WARN)
        _txt(s, 3.52, yy - 0.02, 9.15, 0.26, _cut(tx_on if on else tx_off, 56), size=9.2,
             color=C_TXT if on else C_DIM)
    _txt(s, 0.66, y0 + 1.30 - 0.02, 11.9, 0.20,
         "开关状态时间 %s · 来源 %s · 刷新龄 %s · 两开关独立, 可同时开"
         % (st["t_str"] or "-", st["src"],
            ("%.0f s" % st["age"]) if st["age"] is not None else "-"), size=9.0, color=C_DIM)


# ── 节点在 300 件/小时里的角色: 分类来自链路结构 + 常驻循环实测, 不是形容词
UPH_KEY = {"ssworld", "ssact", "n_exec", "n_moveit", "ssphys", "sslimit", "ssched",
           "ss_grav_h", "ssff", "ssest", "n_geoplan", "ssobs"}
UPH_SKILL = {"sssk1", "sssk2", "sssk3", "sssk4", "sssk5", "sssk6", "sssk7", "sssk8"}
UPH_MEM = {"ss_mem_l2", "n_l2_muscle"}
UPH_SENSE = {"sssensor", "ssaoi", "ssyolo", "ss2d3d", "ss_seg", "sstactile"}
UPH_SIDE = {"ssinnov", "sspred"}


def _uph_note(nid, ms=None, tact=11.468):
    """一句话说清这个节点跟 300 件/小时的关系: 关键路径 / 记忆直通 / 感知泛化 / 旁路校核。"""
    if nid in UPH_KEY:
        if isinstance(ms, (int, float)):
            return ("节拍角色：关键路径。每拍实测 %.2f 毫秒，占 100 毫秒控制周期的 %.0f%%；"
                    "单件 11.47 秒由段表决定，它不额外加时，但省不掉。" % (ms, ms))
        return "节拍角色：关键路径。每拍都在算，单件时间由段表决定，它不额外加时。"
    if nid in UPH_SKILL:
        return ("节拍角色：固定轨迹的一段。记忆直通时按段表回放，不查视觉；"
                "八段动作串起来就是 11.47 秒一件。")
    if nid in UPH_MEM:
        return ("节拍角色：300 件/小时的地板。没有感知时靠它按标杆直通走完全程"
                "（按段表 11.49 秒/件 = 每小时 313 件）。")
    if nid in UPH_SENSE:
        return ("节拍角色：不进记忆路径。换件、来料偏位、姿态超差时才由它接管，"
                "代价是台账每件 17.17 秒；没有它这条线只能干一种件。")
    return ("节拍角色：旁路校核。参与上一拍的残差与预测，不进快通道，不占单件时间；"
            "它的作用体现在换件后的收敛速度上。")


def _elbow(s, x0, y0, x1, y1, xb, color=C_ACC, w=1.0, arrow=True):
    """折线连接: 水平出 → 竖直走 → 水平进, 每条连线一根, 不用母线合并。"""
    _line(s, x0, y0, xb, y0, w=w, color=color)
    _line(s, xb, y0, xb, y1, w=w, color=color)
    _line(s, xb, y1, x1, y1, w=w, color=color, arrow=arrow)


def _iface_items(keys, nodes, side):
    """把一端连线写成「上游名 · 标签」的接口清单, 供页面左下/右下说明。"""
    out = []
    for k2 in keys:
        other = k2.get("f") if side == "in" else k2.get("t")
        nm = _cut(_upname(other, nodes), 10)
        lab = _cut(k2.get("label") or "", 12)
        out.append("%s·%s" % (nm, lab) if lab else nm)
    return out


SKIP_IDS = set()   # 画册统一屏蔽的节点 id (由 l345_pages.NO_PAGE 注入)


def node_page(pr, nid, k, total, nodes, l2, links, out_l2, in_l2,
              layer="基础层", prose=None, ar=None, uph=None, skip=None):
    """节点页 v4（老倪 2026-11-02 定版）:

        上: 功能描述（做什么 / 怎么算, 11~12pt）
        中: 功能框图 —— 左输入、右输出、中间本节点；**每个输入一根线**, 扇入到节点左沿的独立锚点
        下: 左下 = 输入接口描述, 右下 = 输出接口描述（名称·标签, 9.5pt）
    """
    n = nodes[nid]
    mod, mi = _mod_info(nid)
    name = re.sub(r"^L\d\s*·\s*", "", _strip_icon(str(mi.get("NAME") or n.get("name") or nid))).strip()
    params = mi.get("PARAMS") or (n.get("params") or {})
    ins = [k2 for k2 in links if k2.get("t") == nid]
    outs = [k2 for k2 in links if k2.get("f") == nid]
    # 注: NO_PAGE/SKIP_IDS 只控制"是否单独出页"; 上下游连线照实画 ——
    # 抹掉引用会让下游页变成"输入 0 条"的孤页, 反而失真。
    st, ms = _loop_trace().get(nid, ("", None))

    s = _slide(pr)
    _rect(s, 0, 0, 0.12, 7.5, C_ACC, shape=MSO_SHAPE.RECTANGLE)
    _txt(s, 0.82, 0.24, 11.7, 0.24, "%s · 第 %d / %d 位 · 输入 %d 条 / 输出 %d 条"
         % (layer, k, total, len(ins), len(outs)), size=10.5, bold=True, color=C_ACC)
    _txt(s, 0.82, 0.48, 11.7, 0.46, _cut(name, 44), size=21, bold=True)
    _rect(s, 0.82, 1.10, 1.5, 0.05, C_ACC, shape=MSO_SHAPE.RECTANGLE)
    _rect(s, 2.32, 1.12, 10.2, 0.012, RGBColor(0xD3, 0xD9, 0xE1), shape=MSO_SHAPE.RECTANGLE)

    role, method = (prose or _PROSE).get(nid, ("", ""))
    if not role:
        role = _cut((params.get("desc") if isinstance(params, dict) else "")
                    or (n.get("params") or {}).get("desc") or "", 150)
    AR = (ar or _AR).get(nid, "")

    # ── 上: 功能描述（压到 1.6 in 以内, 给框图让出 2.9 in）
    _txt(s, 0.82, 1.18, 11.7, 0.56, role, size=11.5, spacing=1.20)
    if method:
        _txt(s, 0.82, 1.78, 11.7, 0.56, method, size=10.5, spacing=1.18, color=C_SUB)
    _txt(s, 0.82, 2.38, 11.7, 0.22, (uph or {}).get(nid) or _uph_note(nid, ms), size=9.6, color=C_DIM)

    # ── 中: 功能框图（左输入 / 中节点 / 右输出, 每根线单独画）
    TOP, BOT = 2.90, 5.72
    CX, CW2 = 4.90, 3.45                     # 中间节点框
    cy = (TOP + BOT) / 2
    NH = 1.30
    _box(s, CX, cy - NH / 2, CW2, NH, _cut(name, 18), "第 %d 位 · 共 %d 个" % (k, total), "",
         size=11.0, fill=RGBColor(0xDF, 0xEE, 0xF6), line=C_ACC)

    def column(items, side):
        """画一侧的盒子并逐根接到中间节点: 水平出 → 阶梯竖直 → 水平入 (三段正交, 不斜扎成扇)。"""
        if not items:
            yy = cy - 0.14
            _txt(s, (0.86 if side == "in" else 9.14), yy, 3.2, 0.24,
                 "（没有%s）" % ("输入" if side == "in" else "输出"), size=9.6, color=C_DIM)
            return
        n_i = len(items)
        band = BOT - TOP
        pitch = min(0.52, band / n_i)
        bh = min(0.34, pitch * 0.78)
        fs = max(9.2, min(10.0, bh * 72 * 0.58))
        x0 = 0.86 if side == "in" else 9.10
        w0 = 3.30
        spread = min(NH - 0.12, max(0.30, 0.175 * n_i))   # 节点左/右沿上的独立锚点, 最小 12.6pt 间隔
        step = 0.055                                       # 阶梯间距: 同侧多根竖线错开, 不叠成一条
        for i2, k2 in enumerate(items):
            y = TOP + pitch * (i2 + 0.5) - bh / 2
            nm = _cut(_upname(k2.get("f") if side == "in" else k2.get("t"), nodes), 18)
            _box(s, x0, y, w0, bh, nm, "", "", size=fs,
                 fill=C_UP_FILL if side == "in" else C_DN_FILL, line=RGBColor(0xC2, 0xCC, 0xD6))
            ay = cy - spread / 2 + (spread * (i2 + 0.5) / max(n_i, 1))
            yc = y + bh / 2
            if side == "in":
                xm = CX - 0.26 - step * (n_i - 1 - i2)
                _line(s, x0 + w0, yc, xm, yc, color=C_ACC, w=1.0)
                _line(s, xm, yc, xm, ay, color=C_ACC, w=1.0)
                _line(s, xm, ay, CX, ay, arrow=True, color=C_ACC, w=1.0)
            else:
                xm = CX + CW2 + 0.26 + step * (n_i - 1 - i2)
                _line(s, CX + CW2, ay, xm, ay, color=C_ACC, w=1.0)
                _line(s, xm, ay, xm, yc, color=C_ACC, w=1.0)
                _line(s, xm, yc, x0, yc, arrow=True, color=C_ACC, w=1.0)

    column(ins, "in")
    column(outs, "out")
    _txt(s, 0.86, TOP - 0.24, 3.3, 0.2, "输入 · %d 条" % len(ins), size=9.4, bold=True, color=C_ACC)
    _txt(s, 9.10, TOP - 0.24, 3.3, 0.2, "输出 · %d 条" % len(outs), size=9.4, bold=True, color=C_ACC)

    # ── 下: 左下输入接口 / 右下输出接口
    def iface(x, lab, items, side):
        _txt(s, x, 5.80, 5.6, 0.22, "%s接口（%d 条）" % (lab, len(items)), size=9.8, bold=True,
             color=C_ACC)
        if not items:
            _txt(s, x, 6.04, 5.6, 0.22, "没有%s连线。" % lab, size=9.2, color=C_DIM)
            return
        txts = _iface_items(items, nodes, side)
        head = "、".join(txts[:8])
        if len(txts) > 8:
            head += " 等 %d 条" % len(txts)
        _txt(s, x, 6.02, 5.6, 0.60, head, size=9.2, spacing=1.18, color=C_TXT)

    iface(0.82, "输入", ins, "in")
    iface(6.86, "输出", outs, "out")

    _txt(s, 0.82, 6.66, 11.7, 0.22, "AR 验证：%s" % _cut(AR, 96), size=9.4, color=C_SUB)
    _txt(s, 0.82, 6.92, 11.7, 0.20,
         "计算代码 %s 中的 %s · %s" % (_cut(mi.get("SOURCE") or "（尚未绑定实现文件）", 50),
                                     mi.get("SOURCE_SYMBOL") or "对应函数",
                                     _live_prose(nid, mi.get("PURE"))[:52]),
         size=9.0, color=C_DIM)
    _txt(s, 0.82, 7.16, 10.4, 0.20, "Z-MAX · %s %d/%d · %s" % (layer, k, total, nid),
         size=9.0, color=C_DIM)
    return s


# ───────────────────────────────────────────── 技能页「记忆输入 / 补偿」面板
SK_NODES = ("sssk1", "sssk2", "sssk3", "sssk4", "sssk5", "sssk6", "sssk7", "sssk8")
_MEMC, _CORD, _CHMD, _MSHA = {}, None, None, ""


def _mem_db():
    """读 L2 记忆库 (corridors / champs / sha) —— 页面上的通道与标杆全部来自这里, 不在建页时造数。"""
    global _CORD, _CHMD, _MSHA
    if _CORD is None:
        from lerobot.memory import l2_store as _S
        _CORD = _S.corridors()
        _CHMD = _S.champs()
        st = _S.stats()
        _MSHA = (st.get("sha") or {}).get("corridors") or "-"
    return _CORD, _CHMD


def _mem_stats():
    """从实测日志尾部聚合每段通道偏差与削因 (真值; 日志 GB 级 ⇒ 只读尾 4MB)。"""
    if _MEMC:
        return _MEMC
    p = os.path.join(ROOT, "zmax_data/ss_live/skill_calls.log")
    agg = {}
    try:
        size = os.path.getsize(p)
        with open(p, "rb") as f:
            f.seek(max(0, size - (4 << 20)))
            lines = f.read().decode("utf-8", "ignore").splitlines()[1:]
        for ln in lines:
            if '"stage"' not in ln:
                continue
            try:
                d = json.loads(ln)
            except Exception:                                        # noqa: BLE001
                continue
            st = str(d.get("stage") or "")
            if not st:
                continue
            a = agg.setdefault(st, {"n": 0, "dev": [], "out": 0, "why": {}})
            a["n"] += 1
            cor = d.get("cor") or {}
            dv = cor.get("dev_mm")
            if dv is not None:
                a["dev"].append(float(dv))
                if cor.get("in") is False:
                    a["out"] += 1
            w = str(d.get("why") or "")
            for t in ("速度", "加速度", "加加速度", "动量/质量率", "位移", "通道"):
                if t in w:
                    a["why"][t] = a["why"].get(t, 0) + 1
    except Exception:                                                # noqa: BLE001
        pass
    for st, a in agg.items():
        dv = sorted(a["dev"])
        a["dev_p50"] = dv[len(dv) // 2] if dv else None
        a["dev_max"] = dv[-1] if dv else None
        a["dev_n"] = len(dv)
    _MEMC.update(agg)
    return _MEMC


def _mem_panel(s, x, y, w, h, mi):
    """技能页下方横带: 左=记忆输入 (通道/标杆/点位), 右=补偿 (偏差回中/物理闸削/去向/回填)。"""
    cor, ch = _mem_db()
    params = mi.get("PARAMS") or {}
    stage = str((params.get("skill") or {}).get("stage") or "")
    if not stage:
        return
    sh = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    sh.adjustments[0] = 0.03
    sh.fill.solid()
    sh.fill.fore_color.rgb = RGBColor(0xF7, 0xFB, 0xF7)
    sh.line.color.rgb = RGBColor(0x9C, 0xC9, 0x9C)
    sh.line.width = Pt(0.9)
    sh.shadow.inherit = False
    tf = sh.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0.08)
    tf.margin_top = tf.margin_bottom = Inches(0.05)

    def row(txt, size=7.6, col=C_TXT, bold=False):
        par = tf.paragraphs[0] if not tf.paragraphs[0].runs else tf.add_paragraph()
        par.alignment = PP_ALIGN.LEFT
        par.line_spacing = 0.98
        r = par.add_run()
        r.text = txt
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.color.rgb = col

    real = [v for v in cor.values() if v.get("stage") == stage and v.get("kind") == "real"]
    geom = [v for v in cor.values() if v.get("stage") == stage and v.get("kind") == "geom"]
    # 代表条目按**技能语义**挑形状: 抓取系=槽→槽, 转移=槽→孔, 对位/插入/完成=孔→孔
    #   (不按 n_poly 最大挑: 接近 在计划里既有"槽上悬停"也有"飞到孔上方", 用后者会让人以为 SK01 是搬运)
    _SHAPE = {"接近": ("槽", "槽"), "下降": ("槽", "槽"), "抓取": ("槽", "槽"), "抬起": ("槽", "槽"),
              "转移": ("槽", "孔"), "对位": ("孔", "孔"), "插入": ("孔", "孔"), "完成": ("孔", "孔")}
    _ps, _pe = _SHAPE.get(stage, ("槽", "槽"))

    def _match(v):
        fr, to = str(v.get("from") or ""), str(v.get("to") or "")
        return fr.startswith(_ps) and (to.startswith(_pe) or to == "-")

    _pool = [v for v in real if _match(v)] or [v for v in geom if _match(v)] or real or geom
    best = max(_pool, key=lambda v: (v.get("kind") == "real", v.get("n_poly") or 0)) if _pool else None
    ckeys = [k for k in ch if k.endswith("|" + stage)]
    n_ok = sum(int((ch.get(k) or {}).get("n_ok") or 0) for k in ckeys)
    mt = _mem_stats().get(stage) or {}

    row("🧠 记忆输入（L2 记忆库 · 通道 sha %s）" % _MSHA, 8.2, C_OK, True)
    if best:
        ax = best.get("axis") or []
        row("通道 %s（%s）· r=%smm · L=%smm · 单拍≤%smm · 轴速≤%.3fm/s · 节拍%.2fs"
            % (best.get("key"), "实跑" if best.get("kind") == "real" else "几何推导",
               best.get("r_mm"), best.get("L_mm"), best.get("s_tick_mm"),
               float(best.get("v_along_cap") or 0), float(best.get("tact_s") or 0)))
        if ax:
            row("　轴 %s → %s · 本阶段通道 %d 条（实跑 %d / 几何 %d）· 标杆 %d 桶命中 %d · 点位 71 带 quat / 容差 2mm"
                % (_pt(ax[0]), _pt(ax[-1]), len(real) + len(geom), len(real), len(geom), len(ckeys), n_ok),
                size=7.2, col=C_DIM)
    else:
        row("通道: 本阶段在记忆库无条目（缺失, 不许当 0）", 7.6, C_WARN)
        row("　标杆 %d 桶命中 %d · 点位 71 带 quat" % (len(ckeys), n_ok), 7.2, C_DIM)

    row("━━ 补偿 ━━", 7.8, RGBColor(0x22, 0x66, 0x88), True)
    if mt.get("dev_n"):
        _msg = ("通道: 偏差 p50 %.1fmm · max %.1fmm · 越界 %d/%d 拍 ⇒ 向外归零 + 补回中（不是等比缩）"
                % (mt["dev_p50"], mt["dev_max"], mt["out"], mt["dev_n"]))
        if (mt["dev_p50"] or 0) > 100:
            _msg += "　⚠️>100mm 多为坐标系不同源(仿真 trace vs 基座通道), 按 dev>max(100,8r) 判串系并跳过"
        row(_msg)
    else:
        row("通道: 本轮实测日志尾部无该段记录（不填假数）", 7.6, C_DIM)
    why = (mt.get("why") or {})
    top = " · ".join("%s %d 拍" % (k, v) for k, v in sorted(why.items(), key=lambda kv: -kv[1])[:3])
    row("物理闸: %s" % (top or "本轮无削") + "　｜　去向: 小偏差→🧪 状态校正器(out2) · ‖e‖>50mm→📡 融合定位(out3)")
    row("姿态: 段表 quat 逐段下发 · 到位判据 位置≤2mm 且 姿态≤0.5° 连续两次 · 姿态真值缺 ⇒ 不认到位",
        size=7.2, col=C_DIM)
    row("回填: 每次实跑 end_err / 节拍 → 标杆 n_ok 与台账（越跑越准）", size=7.2, col=C_DIM)


def _upname(nid, nodes):
    n = nodes.get(nid) or {}
    return str(n.get("name") or nid)


# ───────────────────────────────────────────── 实际段表块 (运动规划页)
SEG_SNAP = os.path.join(ROOT, "zmax_data/runtime/plan/plan_sample_nmoveit.json")


def _nfmt(v):
    """坐标数字压缩: 1 位小数, 整数不带 .0 (段表要在一行里放得下)。"""
    try:
        s = "%.1f" % float(v)
    except Exception:                                                # noqa: BLE001
        return str(v)
    return s[:-2] if s.endswith(".0") else s


def _pt(p):
    return "(%s)" % ",".join(_nfmt(x) for x in (p or [])[:3])


def _seg_table(s, x, y, w):
    """运动规划页的「实际段表」块: 读实跑快照 (plan_impl.run() 产物), 不在这里造数。

    老倪 2026-11-02「把实际段表在运动规划这页写出来」—— 段表是这页唯一真正的输出物,
    所以贴真值: 段号/类型/起点→终点/长度, 首尾 + 截断事实, 全部来自快照文件。
    版面: 贴在 out 箭头下方空白区 (输出侧), 不压 n_moveit 框也不压页脚; 每行固定高度, 禁折行叠字。
    """
    try:
        with open(SEG_SNAP, encoding="utf-8") as f:
            sn = json.load(f)
    except Exception as e:                                           # noqa: BLE001
        _txt(s, x, y, w, 0.3, "实际段表: 快照缺失 (%s)" % type(e).__name__, size=7.2, color=C_WARN)
        return
    segs = sn.get("segs") or []
    if not segs:
        _txt(s, x, y, w, 0.3, "实际段表: 快照为空", size=7.2, color=C_WARN)
        return
    lim = sn.get("limits") or {}
    _panel(s, x - 0.05, y - 0.05, w + 0.10, 2.02, fill=RGBColor(0xF7, 0xFA, 0xFC), line=RGBColor(0xC2, 0xCC, 0xD6))
    # L1 标题
    _txt(s, x, y, w, 0.20,
         "实际段表 · 实跑快照 %s · %s · %d 段 / %.1f mm"
         % (str(sn.get("t_str") or "")[5:], sn.get("backend") or "-", len(segs), float(sn.get("total_mm") or 0)),
         size=7.6, bold=True, color=C_OK)
    y += 0.21
    # L2 起点 → 目标 (来源写清: 真机真值 / AR 虚拟末端)
    _ps = "AR虚拟末端" if str(sn.get("pose_src") or "").startswith("sim") else "真机真值"
    _txt(s, x, y, w, 0.17,
         "起点 %s %s → %s %s" % (_pt(segs[0].get("a")), _ps,
                                 sn.get("goal_name") or "目标", _pt(sn.get("goal"))),
         size=6.8, color=C_DIM)
    y += 0.18
    # L3 约束 + 时长口径
    _txt(s, x, y, w, 0.17,
         "单步≤%.0f / 向下≤%.0f mm · 上限 %d 段 · t 全落 0.12 s 地板 ⇒ AR 回放 %.2f s"
         % (lim.get("step_mm", 50), lim.get("down_mm", 20), lim.get("max_segs", 40),
            sum(float(g.get("t") or 0) for g in segs)),
         size=6.8, color=C_DIM)
    y += 0.19
    # 表头
    for cx, cw, h in ((x, 0.26, "段"), (x + 0.26, 0.50, "类型"),
                      (x + 0.76, 2.36, "起点 → 终点 (mm)"), (x + 3.12, 0.68, "长度mm")):
        _txt(s, cx, y, cw, 0.17, h, size=6.8, bold=True, color=C_ACC)
    y += 0.18
    show = segs[:2] + segs[-2:] if len(segs) > 4 else segs
    rowh = 0.17
    for i, sg in enumerate(show):
        if len(segs) > 4 and i == 2:            # 中间省略标记 (独立一行, 不与表头抢位)
            _txt(s, x, y, w, 0.16, "… 共 %d 段 (%s)" % (len(segs), _kinds(segs)), size=6.6, color=C_DIM)
            y += rowh
        for cx, cw, val, colr in ((x, 0.26, str(sg.get("i")), C_TXT),
                                  (x + 0.26, 0.50, str(sg.get("kind")), C_TXT),
                                  (x + 0.76, 2.36, "%s→%s" % (_pt(sg.get("a")), _pt(sg.get("b"))), C_TXT),
                                  (x + 3.12, 0.68, _nfmt(sg.get("len_mm")), C_DIM)):
            _txt(s, cx, y, cw, 0.16, val, size=7.0, color=colr)
        y += rowh
    # 姿态 (2026-11-02 起段表不再只有位置): 四元数 + 来源 + 判据
    y += 0.03
    _q1 = segs[0].get("quat")
    if _q1 and len(_q1) == 4:
        _txt(s, x, y, w, 0.16,
             "每段 quat=[%s] · 源 %s"
             % (",".join("%.3f" % float(v) for v in _q1), sn.get("quat_src") or "-"),
             size=6.4, color=C_OK)
        y += 0.155
    _txt(s, x, y, w, 0.28,
         "判据: 位置≤2mm 且 姿态≤0.5° 连续两次; 姿态真值缺 ⇒ 不认到位",
         size=6.2, color=C_DIM)
    y += 0.20
    # 截断事实 (红): 目标没到就直说
    if sn.get("truncated"):
        _txt(s, x, y, w, 0.17,
             "⛔ 上限 %d 段截断：目标 z=%s 未到达, 止于 z=%s"
             % (lim.get("max_segs", 40), _nfmt((sn.get("goal") or [0, 0, 0])[2]),
                _nfmt((segs[-1].get("b") or [0, 0, 0])[2])),
             size=6.8, color=C_WARN)


def _kinds(segs):
    c = {}
    for g in segs:
        c[g.get("kind")] = c.get(g.get("kind"), 0) + 1
    return " · ".join("%s %d" % (k, v) for k, v in sorted(c.items(), key=lambda kv: -kv[1]))


# ───────────────────────────────────────────── 节拍测试报告页
def tact_page(pr):
    import l2_uph_measure as U
    import l2_uph_closure as K
    from lerobot.memory import l2_store as S
    r = U.run_l2(104)
    live = json.load(open(os.path.join(ROOT, "data/memory/ar_muscle.json"), encoding="utf-8"))
    # 冻结: 页面数字与自检读同一份台账快照 (台账是活数据, 不冻结就会"值变了文案没变")
    S.put_ledger({k: {"n": v.get("n"), "mean_t": v.get("mean_t"), "plan_t": v.get("plan_t"),
                      "labels": v.get("labels") or {},
                      "ratio": (round(v["mean_t"] / v["plan_t"], 3) if (v.get("mean_t") and v.get("plan_t")) else None)}
                  for k, v in (live.get("kinds") or {}).items()}, writer="ss_mem_l2", src=live.get("src", ""))
    c = U.compute(led=live.get("kinds") or {})
    k = K.analyse(d=U.plan_from_api(), led=live.get("kinds") or {})
    tp, tm, st, sm = c["plan_tact"], c["meas_tact"], c["uph_plan"], c["uph_meas"]
    st_i, sm_i = round(st), round(sm)
    rows = c["rows"]
    need = ["接近", "对位", "下降", "抓取", "抬起", "转移", "插入"]
    miss = [x for x in need if x not in r["stages"]]
    lv = k["levers"]
    cm = {x["name"]: x for x in k["combos"]}
    c123 = cm["C1+C2+C3"]
    c1234 = cm["C1+C2+C3+C4"]
    fmo = k["fit_move"] or {}
    ok_all = r["done"] and not miss

    s = _slide(pr)
    _rect(s, 0, 0, 0.12, 7.5, C_ACC, shape=MSO_SHAPE.RECTANGLE)
    _txt(s, 0.82, 0.26, 11.7, 0.24, "节拍测试 · 基础层独立运行", size=10.5, bold=True, color=C_ACC)
    _txt(s, 0.82, 0.52, 11.7, 0.9,
         "基础层自己就能跑完一件：按段表 %.2f 秒/件，按台账 %.2f 秒/件" % (tp, tm),
         size=23, bold=True, spacing=1.15)
    _rect(s, 0.82, 1.46, 1.5, 0.05, C_ACC, shape=MSO_SHAPE.RECTANGLE)
    _rect(s, 2.32, 1.48, 10.2, 0.012, RGBColor(0xD3, 0xD9, 0xE1), shape=MSO_SHAPE.RECTANGLE)

    items = [("%d" % r["steps"], "步", "一轮跑完", "随机种子 104"),
             ("%d" % r["mm_hits"], "帧", "快通道接管", "肌肉记忆直通"),
             ("%.2f" % tp, "秒 / 件", "按段表计时", "每小时 %d 件" % st_i),
             ("%.2f" % tm, "秒 / 件", "按台账实测", "每小时 %d 件" % sm_i)]
    w = (11.69 - 3 * 0.24) / 4
    for i2, (val, unit, lab, note) in enumerate(items):
        x = 0.82 + i2 * (w + 0.24)
        _rect(s, x, 1.72, w, 1.24, RGBColor(0xF2, 0xF5, 0xF9), shape=MSO_SHAPE.RECTANGLE)
        _rect(s, x, 1.72, 0.05, 1.24, C_ACC, shape=MSO_SHAPE.RECTANGLE)
        _txt(s, x + 0.22, 1.82, w - 0.36, 0.44, val, size=26, bold=True)
        _txt(s, x + 0.22, 2.26, w - 0.36, 0.22, unit, size=10.5, bold=True, color=C_ACC)
        _txt(s, x + 0.22, 2.48, w - 0.36, 0.22, lab, size=10.5, bold=True)
        _txt(s, x + 0.22, 2.70, w - 0.36, 0.22, note, size=9.5, color=C_DIM)

    y = 3.18
    lines = [
        "七段动作一步不缺：%s，%s。不接上层编排，基础层自己也能走完整件取放。"
        % (" → ".join(r["stages"]), "全部走完" if ok_all else "缺 %s" % "、".join(miss)),
        "两本账差 %+.3f 秒/件：按段表 %.3f 秒/件（每小时 %d 件，达标），把台账实测代回是 %.3f 秒/件（每小时 %d 件，未达标）。"
        % (c["gap"], tp, st_i, tm, sm_i),
        "差在哪：每个段边界的加减速固定多花 %.2f 秒（等效 %.0f 毫米/秒），外观检测独占 %.2f 秒/件（%d 段检测）。不是机械臂慢。"
        % (fmo.get("c_s") or 0, fmo.get("v_mm_s") or 0, k["ao_s"], k["ao_n"] // c["n_mod"]),
        "三条收口后 %.2f 秒/件 = 每小时 %d 件（仍差 %+.2f 秒）；再加抬升加速度到 %.2f 秒/件 = 每小时 %d 件，"
        "这一条需要先确认控制器加速度上限，真机还没验证，不写进承诺。"
        % (c123["tact_s"], round(c123["uph"]), c123["tact_s"] - 12.0,
           c1234["tact_s"], round(c1234["uph"])),
    ]
    for t in lines:
        _txt(s, 0.82, y, 0.22, 0.3, "•", size=12, bold=True, color=C_ACC)
        _txt(s, 1.06, y, 11.4, 0.56, t, size=11.5, spacing=1.24)
        y += 0.66
    _txt(s, 0.82, 6.30, 11.7, 0.24,
         "30 个基础节点的节拍角色：关键路径 %d 个（每拍实测毫秒）· 固定轨迹 %d 段 · 记忆 %d 个（无感知直通的地板）"
         "· 感知 %d 个（换件才接管）· 旁路校核 %d 个 —— 逐页写在每个节点页的「节拍角色」一栏。"
         % (len(UPH_KEY), len(UPH_SKILL), len(UPH_MEM), len(UPH_SENSE), len(UPH_SIDE)),
         size=10.0, color=C_TXT)
    _txt(s, 0.82, 6.62, 11.7, 0.24,
         "数据来源：基础层档位独立实跑（种子 104）+ 段表接口 %d 段 + 台账同动作标签实测（命中 %d/%d 段）"
         % (c["n_seg"], c["label_hit"], c["n_seg"]), size=9.5, color=C_DIM)
    _txt(s, 0.82, 6.92, 11.7, 0.22, "Z-MAX · 5.50.C-R5 · 节拍测试报告", size=9.0, color=C_DIM)
    return s


def add_block(pr, verbose=True):
    """在 验收页 之前插入: N 个节点页 (末端→上游) + 1 个节拍报告页。返回统计。"""
    nodes, l2, links = l2_nodes()
    order, out_l2, in_l2 = chain_order(l2, links)
    n0 = len(pr.slides._sldIdLst)
    # 验收页 = 现存最后一页 (总览里也提到"验收口径", 不能按关键词搜)
    accept_idx = n0 - 1
    _first = [sh.text_frame.text for sh in pr.slides[accept_idx].shapes if sh.has_text_frame]
    if not any("验收方式 · 数字复核" in t for t in _first):
        accept_idx = None
        for i, s in enumerate(pr.slides):
            if any(sh.has_text_frame and sh.text_frame.text.startswith("验收口径 · 复核方式")
                   for sh in s.shapes):
                accept_idx = i

    if SKIP_IDS:                       # 画册不展示的节点: 基础层也不为它单独出页
        order = [x for x in order if x not in SKIP_IDS]
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
