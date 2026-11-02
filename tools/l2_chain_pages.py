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
from pptx.enum.text import PP_ALIGN                                 # noqa: E402
from pptx.enum.shapes import MSO_SHAPE                              # noqa: E402

CANVAS = os.path.join(ROOT, "data/database/zmax/sources/canvas/state_space_obs.json")
C_TXT = RGBColor(0x1F, 0x2A, 0x37)
C_DIM = RGBColor(0x5B, 0x6B, 0x7C)
C_ACC = RGBColor(0x1F, 0x6F, 0x8B)
C_BG = RGBColor(0xEE, 0xF4, 0xF8)
C_WARN = RGBColor(0xB0, 0x3A, 0x2E)
C_OK = RGBColor(0x1E, 0x7A, 0x46)


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


def chain_order(l2, links):
    """末端优先: SCC 压缩成 DAG → 按「离源头最远」分层 → 同层按画布 y/x 排。
    反馈边 (回路) 落在同一 SCC 内, 不再破坏顺序。"""
    nodes, _, _ = l2_nodes()
    out_l2 = {n: set() for n in l2}
    in_l2 = {n: set() for n in l2}
    for k in links:
        f, t = k.get("f"), k.get("t")
        if f in l2 and t in l2:
            out_l2[f].add(t)
            in_l2[t].add(f)

    comps = _scc(l2, out_l2)
    cid = {v: i for i, c in enumerate(comps) for v in c}
    cout = {i: set() for i in range(len(comps))}
    for v, ws in out_l2.items():
        for w in ws:
            if cid[v] != cid[w]:
                cout[cid[v]].add(cid[w])

    # 最长路径深度 (源 = 无入边的分量, 深度 0)
    cin = {i: set() for i in range(len(comps))}
    for i, ws in cout.items():
        for w in ws:
            cin[w].add(i)
    depth = {i: 0 for i in range(len(comps))}
    changed = True
    while changed:                                    # DAG 上松弛即可
        changed = False
        for i in sorted(cout):
            d = max([depth[j] + 1 for j in cin[i]], default=depth[i])
            if d != depth[i]:
                depth[i] = d
                changed = True
    order_comps = sorted(range(len(comps)), key=lambda i: (-depth[i], -min(nodes[v]["y"] for v in comps[i])))
    order = []
    for i in order_comps:
        order.extend(sorted(comps[i], key=lambda v: (-nodes[v]["y"], -nodes[v]["x"])))
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


def node_page(pr, nid, k, total, nodes, l2, links, out_l2, in_l2):
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
    _txt(s, 0.5, 0.16, 12.3, 0.34, "L2 链路 %02d/%d · %s · %s" % (k, total, _cut(name, 40), nid),
         size=15, bold=True)
    _txt(s, 0.5, 0.52, 12.3, 0.26,
         "%s · %s/%s · 执行口径 %s / PURE=%s · 端口 in %d / out %d · 画布连线 in %d / out %d"
         % (nid, (mi.get("LAYER") or "L2"), (mi.get("TYPE") or n.get("type") or "-"),
            (mi.get("EXEC_MODE") or "-"), ("真算" if pure else ("直通" if pure is False else "无实现")),
            len(ports_in), len(ports_out), len(ins), len(outs)),
         size=7.8, color=C_DIM)

    # 左: 功能定义 + 参数
    _panel(s, 0.5, 0.86, 6.25, 3.55)
    _txt(s, 0.65, 0.94, 5.95, 0.24, "功能定义（节点 PARAMS['desc'] 原文）", size=9, bold=True, color=C_ACC)
    desc = params.get("desc") if isinstance(params, dict) else None
    desc = desc or (n.get("params") or {}).get("desc") or "（该节点无 desc，见实现文件头）"
    _txt(s, 0.65, 1.20, 5.95, 3.10, _cut(desc, 700), size=8.2, spacing=1.18)

    _panel(s, 0.5, 4.52, 6.25, 2.30)
    _txt(s, 0.65, 4.60, 5.95, 0.24, "参数 / 实现位置", size=9, bold=True, color=C_ACC)
    kv = []
    if isinstance(params, dict):
        for kk, vv in params.items():
            if kk in ("desc",):
                continue
            if isinstance(vv, (dict, list)):
                kv.append("%s = <%s %d 项>" % (kk, type(vv).__name__, len(vv)))
            else:
                kv.append("%s = %s" % (kk, _cut(vv, 46)))
            if len(kv) >= 9:
                break
    impl = "%s:%s" % (_cut(mi.get("SOURCE") or "（无实现文件绑定）", 58), mi.get("SOURCE_SYMBOL") or "")
    kv.append("实现 = " + _cut(impl, 76))
    kv.append("话题 = ss.node.%s.<port>" % nid)
    _txt(s, 0.65, 4.86, 5.95, 1.86, "\n".join("· " + x for x in kv), size=7.6, spacing=1.14)

    # 右: 输入 / 输出
    _panel(s, 6.95, 0.86, 5.88, 3.55)
    _txt(s, 7.10, 0.94, 5.6, 0.24, "输入（%d 条连线 · 端口 ← 上游）" % len(ins), size=9, bold=True, color=C_ACC)
    lines = []
    for k2 in ins[:13]:
        up = k2.get("f")
        lines.append("[%s] ← %s · %s%s" % (k2.get("t_port") or "-", _cut(_upname(up, nodes), 26),
                                          _layer_of(up, nodes, l2), (" · " + _cut(k2.get("label"), 12)) if k2.get("label") else ""))
    if len(ins) > 13:
        lines.append("… 另 %d 条" % (len(ins) - 13))
    _txt(s, 7.10, 1.20, 5.6, 3.12, "\n".join("· " + x for x in lines) or "· （无输入连线）", size=7.6, spacing=1.16)

    _panel(s, 6.95, 4.52, 5.88, 2.30)
    _txt(s, 7.10, 4.60, 5.6, 0.24, "输出（%d 条连线 · 端口 → 下游）" % len(outs), size=9, bold=True, color=C_ACC)
    ols = []
    for k2 in outs[:12]:
        dn = k2.get("t")
        ols.append("[%s] → %s · %s" % (k2.get("f_port") or "-", _cut(_upname(dn, nodes), 24),
                                       _layer_of(dn, nodes, l2)))
    if len(outs) > 12:
        ols.append("… 另 %d 条" % (len(outs) - 12))
    _txt(s, 7.10, 4.86, 5.6, 1.86, "\n".join("· " + x for x in ols) or "· （无输出连线 · 末端节点）",
         size=7.6, spacing=1.14)

    _txt(s, 0.5, 6.92, 12.3, 0.34,
         "链路位置：逆序第 %d 位（1 = 最后输出端） · L2 内上游 %d / 下游 %d · 本节点在 L2 %d 个节点里"
         % (k, len(in_l2[nid]), len(out_l2[nid]), total),
         size=7.8, color=C_DIM)
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
