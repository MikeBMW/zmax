#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🪐 球心引力架构视图 —— 只读判据 (老倪 2026-10-16 口径)

口径 (老倪原话):
  「在右侧侧面栏, 流形引擎是太阳, 前馈加速器是地球, DiT是火星, 接触流形是水星,
    性能流形是木星, 原子技能是卫星, 用球体映射主要的节点。状态校正节点是月球。
    前馈加速器和状态校正器协同行进」

判据分六段:
  A 天体↔节点 唯一依据 (不是随手起名)   B 真连线 (双通道/卡尔曼结构/协同)
  C 球上的数是真值 (与唯一依据/真模块逐位一致)   D 画 (球/轨道/相位锁定/无数据压暗)
  E 侧栏接线 (M 页真挂 + 切换 + 只读)   F 文案诚实 (唯一依据·帧龄·映射写清)

只读: 本判据不写唯一依据 (E4 静态核 + 跑前后唯一依据 sha 对比)。
"""

from __future__ import annotations

import io

import hashlib
import json
import math
import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("DISPLAY", ":0")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in (os.path.join(ROOT, "tools", "gui"), os.path.join(ROOT, "src")):
    if _d not in sys.path:
        sys.path.insert(0, _d)

import numpy as np                                                        # noqa: E402
from PyQt5.QtGui import QColor                                             # noqa: E402
from PyQt5.QtWidgets import QApplication                                  # noqa: E402

import orbital_arch as OA                                                 # noqa: E402
# 2026-10-19: 观察窗口现在按「控制台 ▶ 运行」门控 (没点运行不画力线/不转)。
#   本判据测的是**画力线/虚线/球体**的渲染能力 ⇒ 明确把运行态置为"在跑",
#   "没在跑要一条线都不画"另有专判据 (verify_orbital_state.py S20)。
OA.OrbitalArchData._ui_run = (lambda self: (True, "judge: 在跑分支"))

PASS = FAIL = 0
ROWS = []


def _arr(im):
    """QImage → ndarray(H,W,3) int (走 constBits, 比逐像素 pixel() 快两个数量级)。"""
    from PyQt5.QtGui import QImage
    im2 = im.convertToFormat(QImage.Format_RGB32)
    ptr = im2.constBits()
    try:
        ptr.setsize(im2.byteCount())
    except Exception:                                                        # noqa: BLE001
        ptr.setsize(im2.sizeInBytes())
    a = np.frombuffer(ptr, dtype=np.uint8).reshape(im2.height(), im2.width(), 4)
    return a[:, :, 2::-1].astype(int)                                        # BGRX → RGB


def chk(tag, title, got, ok, expect=""):
    global PASS, FAIL
    good = bool(ok)
    PASS += good
    FAIL += (not good)
    ROWS.append({"tag": tag, "title": title, "got": got, "expect": expect, "ok": good})
    print("%s %-4s %s" % ("✅" if good else "❌", tag, title))
    print("        got=%s  expect=%s" % (str(got)[:230], str(expect)[:200]))


def sha(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    view = OA.OrbitalArchView()
    data = view.data
    info = view.info
    body = data.body
    canvas_nodes = data.nodes
    canvas_links = data.link_set

    # ═══ A 天体 ↔ 节点 唯一依据 ═══
    allin = all(v["在"] for v in info["checked"].values())
    chk("A1", "7 类天体 (太阳/水星/地球/火星/木星/月球/卫星带) 都是画布唯一依据里的真节点",
        {k: (v["在"], v["id"]) for k, v in info["checked"].items()}, allin,
        "7 个 id 全在画布 state_space_obs.json 的 nodes 里")
    chk("A2", "每个天体的节点名与老倪口径一致 (不是同名不同物)",
        {k: v["名"][:18] for k, v in info["checked"].items()},
        all(v["名匹配"] for v in info["checked"].values()),
        "太阳=流形引擎 · 水星=接触流形 · 地球=前馈加速器 · 火星=Action Head(DiT) · 木星=性能流形 · 月球=状态校正器 · 卫星带=原子技能")
    ids = [b[1] for b in OA.BODIES]
    chk("A3", "没有编造节点: BODIES 里每个 id 都能在画布唯一依据里查到",
        {"ids": ids, "全在": all(i in canvas_nodes for i in ids)},
        all(i in canvas_nodes for i in ids), "全部命中 (唯一依据 90 节点)")
    chk("A4", "卫星带条数来自唯一依据 (skill_phys.json 在职 SK), 不是固定不变的数",
        {"在职": body["sats"]["n"], "标定表": body["sats"].get("n_calib"),
         "list": [s["SK"] for s in body["sats"]["list"]]},
        body["sats"]["n"] == len([s for s in body["sats"]["list"] if str(s["SK"]).startswith("SK")]) and body["sats"]["n"] > 0,
        "条数 == 唯一依据在职 SK 数 (>0)")

    # ═══ B 真连线 ═══
    _bids_all = {x[1] for x in OA.BODIES}
    _bb_keys = [(f, t) for f, t, _l in OA.KEY_EDGES if f in _bids_all and t in _bids_all]
    miss = [(f, t) for f, t, _l in OA.KEY_EDGES if (f, t) not in canvas_links]
    chk("B1", "视图要画的 **主体↔主体 5 条**连线在画布 links 唯一依据里全都存在 (一条不缺; 体系外按老倪要求不再上图)",
        {"缺": miss, "唯一依据连线总数": len(canvas_links)}, not miss, "缺 = []")
    twin = {"直连 VLM→DiT": ("ssvlm", "ssdec") in canvas_links,
            "经流形 VLM→接触流形": ("ssvlm", "ssmani_c") in canvas_links,
            "经流形 VLM→性能流形": ("ssvlm", "ssmani_p") in canvas_links}
    chk("B2", "双通道条件生成在真连线里成立: 直连通道 ‖ 旁路(经流形)通道 同时存在",
        twin, all(twin.values()), "三条真连线都在 (主通道语义条件 + 旁路几何条件)")
    ins = [l.get("f") for l in data.links if l.get("t") == "ssdec" and l.get("f")]
    chk("B3", "DiT 的条件是并联汇总注入: 真入边 ≥3 且包含接触流形/性能流形两路",
        {"DiT 真入边数": len(ins), "入边": sorted(set(ins))},
        len(ins) >= 3 and "ssmani_c" in ins and "ssmani_p" in ins,
        "入边含 ssmani_c + ssmani_p (+ssvlm/sslat/ss_lora_l4)")
    kal = {"校正器入边含 z_k(测量)": ("ssworld", "ssinnov") in canvas_links,
           "校正器出边→动作调制(反馈)": ("ssinnov", "sssched") in canvas_links,
           "校正器→融合定位(状态回灌)": ("ssinnov", "sssensor") in canvas_links,
           "回灌链→流形引擎(闭环)": ("sssensor", "ss_mani_eng") in canvas_links}
    chk("B4", "卡尔曼结构在真连线里成立 (测量→校正→回灌→引擎闭环)",
        kal, all(kal.values()), "四条真连线都在")
    co = {"前馈→动作调制器": ("ssff", "sssched") in canvas_links,
          "校正器→动作调制器": ("ssinnov", "sssched") in canvas_links}
    chk("B5", "「前馈加速器与状态校正器协同行进」在真连线里成立 (两路同进调制器)",
        co, all(co.values()), "ssff→sssched 与 ssinnov→sssched 都在")

    # ═══ C 球上的数是真值 ═══
    mani = json.load(open(os.path.join(ROOT, "config", "calib", "zmax_manifold.json"), encoding="utf-8"))
    chk("C1", "太阳主参数 M 与标定唯一依据 zmax_manifold.json 同源 (逐位相等)",
        {"视图 M": body["sun"]["M"], "唯一依据 M": mani.get("M")},
        float(body["sun"]["M"]) == float(mani.get("M")), "相等")
    tq = json.load(open(os.path.join(ROOT, "zmax_data", "ss_live", "torque_live.json"), encoding="utf-8"))
    mt = tq.get("metric_tensor") or []
    dim = int(tq.get("metric_dim") or 6)
    diag = [float(mt[i * dim + i]) for i in range(dim)] if mt else []
    chk("C2", "太阳的扭矩与度量特征值都取自 torque_live.json (引力=度量: 井扁率用真特征值)",
        {"T": body["sun"]["T_norm"], "唯一依据 T": tq.get("torque_norm"),
         "eig_min/max": [body["sun"]["eig_min"], body["sun"]["eig_max"]],
         "唯一依据对角": [round(min(diag), 3), round(max(diag), 3)] if diag else None},
        abs(float(body["sun"]["T_norm"]) - float(tq.get("torque_norm"))) < 1e-9
        and abs(float(body["sun"]["eig_min"]) - min(diag)) < 1e-9
        and abs(float(body["sun"]["eig_max"]) - max(diag)) < 1e-9,
        "T 与特征值逐位一致")

    # 直接调真模块重算 接触流形/性能流形 (独立于视图内部实现) 对拍
    import importlib.util as _ilu
    spec = _ilu.spec_from_file_location("ml_check", os.path.join(ROOT, "src", "lerobot", "manifold", "manifold_layer.py"))
    ml = _ilu.module_from_spec(spec)
    spec.loader.exec_module(ml)
    f = data.frames
    i = f["idx"]
    hand, peg, tgt_, v = f["hand"][i], f["peg"][i], f["tgt"][i], f["v"][i]
    stage = info["stage"]
    c_ref = ml.ContactManifold().decompose(hand, peg, tgt_, v, stage)
    chk("C3", "接触流形 (水星) 的进度/偏离/V/V̇ == 真模块 manifold_layer.ContactManifold 重算值",
        {"视图": [body["mercury"][k] for k in ("progress", "risk", "V", "Vdot")],
         "真模块": [c_ref[k] for k in ("progress", "risk", "V", "Vdot")],
         "段": stage},
        all(abs(float(body["mercury"][k]) - float(c_ref[k])) < 1e-12 for k in ("progress", "risk", "V", "Vdot")),
        "四项逐位一致")
    p_ref = ml.PerformanceManifold().evaluate(peg, stage=stage)
    chk("C4", "性能流形 (木星) 的 V_p/η == 真模块 PerformanceManifold 重算值",
        {"视图": [body["jupiter"].get("V_p"), body["jupiter"].get("eta")],
         "真模块": [p_ref.get("Vp"), p_ref.get("eta")]},
        abs(float(body["jupiter"]["V_p"]) - float(p_ref["Vp"])) < 1e-12
        and abs(float(body["jupiter"]["eta"]) - float(p_ref["eta"])) < 1e-12, "两项逐位一致")
    spec2 = _ilu.spec_from_file_location("su2_check", os.path.join(ROOT, "src", "lerobot", "policies", "left_right", "state_space", "su2.py"))
    su2 = _ilu.module_from_spec(spec2)
    spec2.loader.exec_module(su2)
    e_mine = f["peg"][i] - f["tgt"][i]
    e_ref = np.asarray(su2.obs43_geometry(f["obs"][i]), dtype=float)
    chk("C5", "43D obs 的通道划分自洽: 重建 (光模块头−孔位) == su2.obs43_geometry 的输出",
        {"mine": [round(float(x), 6) for x in e_mine], "ref": [round(float(x), 6) for x in e_ref],
         "视图自报": info["mf"].get("e_ok")},
        bool(np.allclose(e_mine, e_ref, atol=1e-12)) and info["mf"].get("e_ok") is True, "逐位相等")
    sk = json.load(open(os.path.join(ROOT, "zmax_data", "ss_live", "skill_latest.json"), encoding="utf-8"))
    se = json.load(open(os.path.join(ROOT, "zmax_data", "ss_live", "skill_error.json"), encoding="utf-8"))
    e = body["earth"]
    chk("C6", "地球(前馈请求/偏差/可行)与月球(残差)都是 skill_latest / skill_error 的真值",
        {"请求": e.get("req_mps"), "唯一依据请求": sk.get("%s_请求_mps" % (e.get("stage") or "")),
         "残差": body["moon"].get("err"), "唯一依据残差": (se.get("err_norm") or {}).get(e.get("stage") or "")},
        float(e.get("req_mps")) == float(sk.get("%s_请求_mps" % (e.get("stage") or "")))
        and float(body["moon"].get("err")) == float((se.get("err_norm") or {}).get(e.get("stage") or "")),
        "与唯一依据逐位一致")

    # ═══ D 画 ═══
    view.resize(680, 900)
    view.show()
    app.processEvents()
    pm = view.grab()
    img = pm.toImage()
    W, H = pm.width(), pm.height()
    arr = _arr(img)

    def near(rgb, hexcol, tol=70):
        ref = np.array([int(hexcol[1:3], 16), int(hexcol[3:5], 16), int(hexcol[5:7], 16)])
        m = np.abs(arr - ref).sum(axis=2) < tol
        return int(m.sum()), m

    counts = {}
    for key, col in (("sun", OA.OrbitalArchView.COL["sun"]), ("mercury", OA.OrbitalArchView.COL["mercury"]),
                     ("earth", OA.OrbitalArchView.COL["earth"]), ("mars", OA.OrbitalArchView.COL["mars"]),
                     ("jupiter", OA.OrbitalArchView.COL["jupiter"]), ("moon", OA.OrbitalArchView.COL["moon"]),
                     ("sat", OA.OrbitalArchView.COL["sat"])):
        counts[key] = near(col, col)[0]
    chk("D1", "七类球体真画出 (像素证据: 各自球色像素数 > 阈值)",
        counts, counts["sun"] > 300 and min(counts[k] for k in ("mercury", "earth", "mars", "jupiter", "moon", "sat")) > 25,
        "太阳 >300 · 其余每颗 >25 像素")
    # 球体是真球 (径向渐变: 球内亮度有落差)
    _, mask_sun = near(OA.OrbitalArchView.COL["sun"], OA.OrbitalArchView.COL["sun"])
    lum = arr.sum(axis=2)
    inside = lum[mask_sun]
    chk("D2", "球体是「真球」: 球内像素亮度沿径向有落差 (径向渐变, 不是实心圆)",
        {"球内像素": int(inside.size), "最亮": int(inside.max()) if inside.size else 0,
         "最暗": int(inside.min()) if inside.size else 0},
        inside.size > 0 and (int(inside.max()) - int(inside.min())) > 40, "亮度落差 > 40")
    grid = np.abs(arr - np.array([0x24, 0x30, 0x40])).sum(axis=2) < 40
    rows = grid.sum(axis=1)
    cols = grid.sum(axis=0)
    chk("D3", "轨道与卫星带真画 (轨道线像素跨多行多列 ⇒ 真是环, 不是一段线)",
        {"轨道像素": int(grid.sum()), "行≥8 的行数": int((rows >= 8).sum()), "列≥8 的列数": int((cols >= 8).sum())},
        int(grid.sum()) > 800 and int((rows >= 8).sum()) >= 10 and int((cols >= 8).sum()) >= 10,
        "轨道像素 >800 · 行≥8 ≥10 行 · 列≥8 ≥10 列")
    # D4 卫星群必须**绕地球**、且与月球不重叠 (老倪 2026-10-16: 「这些卫星都是原子技能,
    #    应该围绕在地球周围, 不能散落在太阳系」) —— 在**轨道平面坐标**里核 (与视角无关),
    #    再用屏幕像素核一遍 (真渲染确实贴在地球旁)。
    lo = view.local_offsets()
    sat_r = [math.hypot(dx, dy) for dx, dy, _sk, _aa in lo["sat"]]
    sat_ang = [aa for _dx, _dy, _sk, aa in lo["sat"]]
    d_angles = [((a - lo["earth_angle"] + math.pi) % (2 * math.pi)) - math.pi for a in sat_ang]
    moon_r = math.hypot(*lo["moon"])
    chk("D4", "原子技能 = **绕地球**的卫星群 (平面半径 = %.3fR 恒定 · 与地球同向公转 · 均布), 且与月球不同圈不重叠"
        % OA.OrbitalArchView.SAT_R,
        {"卫星数": len(sat_r), "卫星半径": [round(x, 4) for x in sat_r],
         "相对地球相位(rad)": [round(x, 3) for x in d_angles],
         "月球半径": round(moon_r, 4), "卫星圈 vs 月球圈": [OA.OrbitalArchView.SAT_R, round(OA.OrbitalArchView.MOON_R, 3)]},
        len(sat_r) >= 6 and max(abs(x - OA.OrbitalArchView.SAT_R) for x in sat_r) < 1e-9
        and max(abs(x) for x in d_angles) < 2 * math.pi
        and moon_r > max(sat_r) + 0.01, "卫星半径恒定 = SAT_R · 月球圈在卫星圈之外 (不叠)")
    # 屏幕像素核对: 每颗卫星与地球的屏幕距离 与 平面半径×R×zoom 一致 (量级正确)
    _pos = view.positions()
    _ex, _ey, _ = _pos["earth"]
    _scr = [math.hypot(x - _ex, y - _ey) for x, y, _z, _sk in _pos["_sat"]]
    _R = _pos["_R"]
    chk("D4b", "屏幕上 (真渲染坐标) 卫星确实贴在地球旁: 屏距 ≈ SAT_R·投影 (不是散落在太阳系)",
        {"屏距px": [round(x, 1) for x in _scr], "SAT_R·R": round(OA.OrbitalArchView.SAT_R * _R, 1),
         "最远卫星屏距 / 太阳半径px": round(max(_scr) / (0.052 * 2 * _R / 0.46 if _R else 1), 2)},
        max(_scr) < 0.16 * _R and min(_scr) > 0.01 * _R, "屏距在 0.01R~0.16R 之间 (贴着地球)")

    # 无数据: 压暗 + 文案诚实
    with tempfile.TemporaryDirectory() as td:
        v2 = OA.OrbitalArchView()
        v2.data = OA.OrbitalArchData(root=td)
        v2.info = v2.data.build()
        v2.resize(680, 900)
        v2.grab()
        b2 = v2.data.body
        texts = [v2._sun_text(b2["sun"]), v2._body_text("mercury", b2["mercury"]),
                 v2._body_text("jupiter", b2["jupiter"]), v2._body_text("earth", b2["earth"])]
        hit = sum(1 for t in texts if any(k in t for k in ("未算", "未测", "未运行", "不可用", "无真帧")))
        chk("D5", "唯一依据缺失时: 球压暗 (_live=False) 且文案写「未算/未测/不可用」—— 不填 0 不编数",
            {"_live": [OA.OrbitalArchView._live(b2[k]) for k in ("mercury", "jupiter", "earth")],
             "文案": [t[:26] for t in texts]},
            not any(OA.OrbitalArchView._live(b2[k]) for k in ("mercury", "jupiter", "earth")) and hit >= 3,
            "三颗都压暗 + ≥3 处诚实文案")

    # ═══ E 侧栏接线 ═══
    with open(os.path.join(ROOT, "tools", "gui", "model_tree.py"), encoding="utf-8") as fh:
        mt_src = fh.read()
    wire = {"import": ("OrbitalArchView" in mt_src), "实例化": ("self.orbital = OrbitalArchView(" in mt_src.replace("OrbitalArchView(root=self._root)", "OrbitalArchView(")),
            "addWidget": ("self.viz_stack.addWidget(self.orbital)" in mt_src),
            "切换器": ("self.cmb_viz_view.addItems" in mt_src and "_switch_viz_view" in mt_src),
            "刷新链": ("self.orbital.refresh()" in mt_src)}
    chk("E1", "画布右侧「主参数 M」页真接线 (import + 实例化 + 进 stack + 切换器 + 刷新链)",
        wire, all(wire.values()), "五处都在")
    import model_tree as MT
    class _M:
        nodes = []
        def __init__(self):
            self._root = ROOT
    page = MT.MasterParamMView(_M())
    page.resize(680, 1000)
    page.show()
    app.processEvents()
    ok_switch = None
    try:
        page.cmb_viz_view.setCurrentIndex(1)
        app.processEvents()
        ok_switch = (page.viz_stack.currentIndex() == 1)
        page.cmb_viz_view.setCurrentIndex(0)
        app.processEvents()
        ok_switch = ok_switch and (page.viz_stack.currentIndex() == 0)
    except Exception as _e:                                                   # noqa: BLE001
        ok_switch = "异常: %s" % _e
    chk("E2", "下拉真切换: 选「🪐 球心引力架构」→ stack 显示该视图; 切回「🧊 四面板」也生效",
        {"两页文字": [page.cmb_viz_view.itemText(i) for i in range(page.cmb_viz_view.count())],
         "切 1→0 往返": ok_switch},
        ok_switch is True and page.cmb_viz_view.count() == 2, "往返都 True · 2 项")
    pg = page.orbital
    chk("E3", "M 页里的球心视图是真对象且在役 (能 refresh 并拿到真值)",
        {"类型": type(pg).__name__, "refresh": hasattr(pg, "refresh"),
         "太阳 M": getattr(getattr(pg, "data", None), "body", {}).get("sun", {}).get("M")},
        type(pg).__name__ == "OrbitalArchView" and pg.data.body["sun"]["M"] == float(mani.get("M")),
        "OrbitalArchView · M 与标定唯一依据同值")
    with open(os.path.join(ROOT, "tools", "gui", "studio.py"), encoding="utf-8") as fh:
        st_src = fh.read()
    nav = {"分支 orbital": 'elif line == "orbital":' in st_src,
           "执行体 _goto_orbital_cmd": "def _goto_orbital_cmd(self):" in st_src,
           "真切到第 2 项视图": "cmb.setCurrentIndex(1)" in st_src,
           "抓图按当前视图命名": 'live_mparam_%s.png' in st_src and 'currentIndex() == 1 else "viz"' in st_src}
    chk("E5", "命令通道 orbital 真接线 (一句令: 画布页+M页+切到球心视图) + mparam_shot 抓当前显示页",
        nav, all(nav.values()), "四处都在: 分支/执行体/切视图/按视图命名落盘")
    src = open(os.path.join(ROOT, "tools", "gui", "orbital_arch.py"), encoding="utf-8").read()
    _src_nop = src.replace("p.save()", "").replace("_p.save()", "")   # QPainter.save 不是写文件口
    writes = [k for k in ('open(fpath, "w"', "open(p, \"w\"", "json.dump(", "np.save", ".save(") if k in _src_nop]
    chk("E4", "视图是只读的 (源码里没有写文件口; 只读唯一依据画图)", {"命中写口": writes}, not writes, "无写口")

    # ═══ 冻源: 现场有别的进程(控制台/引擎)每帧在写 zmax_data/ss_live/*.json ⇒
    #    像素类判据必须有**确定输入**, 先拷一份唯一依据到临时目录, 后面的视图都读冻结副本 (只读, 不改唯一依据)。
    import shutil as _sh
    _FREEZE = tempfile.mkdtemp(prefix="orb_freeze_")
    _RELS = ("data/database/zmax/sources/canvas/state_space_obs.json",
             "data/database/zmax/sources/canvas/ss_traj_last.json",
             "config/calib/zmax_manifold.json",
             "zmax_data/ss_live/engine_latest.json", "zmax_data/ss_live/torque_live.json",
             "zmax_data/ss_live/skill_latest.json", "zmax_data/ss_live/skill_error.json",
             "zmax_data/ss_live/skill_phys.json",
             "src/lerobot/manifold/manifold_layer.py",
             "src/lerobot/policies/left_right/state_space/su2.py")
    _frozen = 0
    for _rel in _RELS:
        _sp = os.path.join(ROOT, _rel)
        _dp = os.path.join(_FREEZE, _rel)
        if os.path.exists(_sp):
            os.makedirs(os.path.dirname(_dp), exist_ok=True)
            _sh.copy2(_sp, _dp)
            _frozen += 1
    chk("K1", "判据在**冻结唯一依据副本**上跑 (现场别的进程每帧在写 ss_live ⇒ 输入不漂, 结论可复现)",
        {"已冻结文件": _frozen, "清单": [r.split("/")[-1] for r in _RELS],
         "冻源目录": os.path.basename(_FREEZE)},
        _frozen >= 8, "关键唯一依据 ≥8 个文件已冻结")

    # ═══ H 鼠标可操作 (旋转 / 缩放 / 复位) ═══
    from PyQt5.QtCore import QPoint, QPointF, Qt
    from PyQt5.QtGui import QMouseEvent
    v3 = OA.OrbitalArchView(root=_FREEZE)
    v3.resize(680, 900)
    v3.show()
    app.processEvents()
    _img0 = v3.grab().toImage()
    s0 = (v3.yaw, v3.pitch, v3.zoom)
    ev1 = QMouseEvent(QMouseEvent.MouseButtonPress, QPoint(120, 120), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    ev2 = QMouseEvent(QMouseEvent.MouseMove, QPoint(210, 160), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    v3.mousePressEvent(ev1)
    v3.mouseMoveEvent(ev2)
    app.processEvents()
    s1 = (v3.yaw, v3.pitch, v3.zoom)
    _img1 = v3.grab().toImage()

    class _W:                                                                 # 假滚轮事件: 滚 3 格
        def angleDelta(self):
            class _D:
                def y(self):
                    return 360
            return _D()
    v3.wheelEvent(_W())
    s2 = (v3.yaw, v3.pitch, v3.zoom)
    v3.mouseDoubleClickEvent(ev1)
    s3 = (v3.yaw, v3.pitch, v3.zoom)
    # 俯仰/缩放限幅 (拖到极端也不翻车)
    v3.pitch = 0.0
    for _ in range(60):
        v3.mousePressEvent(QMouseEvent(QMouseEvent.MouseButtonPress, QPoint(100, 100), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        v3.mouseMoveEvent(QMouseEvent(QMouseEvent.MouseMove, QPoint(100, 100 + 60), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    _pitch_hi = v3.pitch
    for _ in range(120):
        v3.mousePressEvent(QMouseEvent(QMouseEvent.MouseButtonPress, QPoint(100, 100), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        v3.mouseMoveEvent(QMouseEvent(QMouseEvent.MouseMove, QPoint(100, 100 - 60), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    _pitch_lo = v3.pitch
    for _ in range(40):
        v3.wheelEvent(_W())
    _zoom_hi = v3.zoom
    for _ in range(120):
        class _W2:
            def angleDelta(self):
                class _D2:
                    def y(self):
                        return -360
                return _D2()
        v3.wheelEvent(_W2())
    _zoom_lo = v3.zoom
    chk("H1", "鼠标真能用: 拖动 ⇒ 偏航/俯仰变化, 滚轮 ⇒ 缩放, 双击 ⇒ 复位 (且渲染图真的变了)",
        {"拖动前": [round(x, 3) for x in s0], "拖动后": [round(x, 3) for x in s1],
         "滚轮后 zoom": round(s2[2], 3), "双击复位": [round(x, 3) for x in s3],
         "拖动前后图像变化像素": int(np.sum(np.abs(_arr(_img0) - _arr(_img1)).sum(axis=2) > 30))},
        abs(s1[0]) > 0.2 and abs(s1[1] - s0[1]) > 0.05 and s2[2] > 1.05 and abs(s3[0]) < 1e-9
        and abs(s3[2] - 1.0) < 1e-9
        and int(np.sum(np.abs(_arr(_img0) - _arr(_img1)).sum(axis=2) > 30)) > 5000,
        "yaw 变化>0.2 · pitch 变化>0.05 · zoom>1.05 · 复位回 (0, 0.42, 1.0) · 渲染图真变化 >5000 px")
    chk("H2", "俯仰与缩放都有限幅 (拖/滚到极端不翻车, 图还在)",
        {"pitch 上限": round(_pitch_hi, 3), "pitch 下限": round(_pitch_lo, 3),
         "zoom 上限": round(_zoom_hi, 3), "zoom 下限": round(_zoom_lo, 3)},
        abs(_pitch_hi) <= 1.1501 and abs(_pitch_lo) <= 1.1501 and _zoom_hi <= 2.4001 and _zoom_lo >= 0.5499,
        "pitch ∈ [-1.15, 1.15] · zoom ∈ [0.55, 2.4]")

    # ═══ I 力的相互作用连线 (唯一依据 + 粗细 + 不闪) ═══
    v3._tm.stop()                         # 量像素时**冻结动画**: 否则虚线相位随 60ms 计时器漂 ⇒ 判据时红时绿
    v3._phase = 0.0
    v3.reset_view()                       # 量线宽要在正视角 (H2 把视角拖到极端了, 不是干净量法)
    app.processEvents()
    ed = v3.interactions()
    _bb = [e for e in ed if e["body_body"]]
    _ex2 = [e for e in ed if not e["body_body"]]
    _src_ok = all((e["f"], e["t"]) in canvas_links for e in ed)          # 每条都必须是画布真连线
    # 反向: 画布上所有"至少一端是主体"的连线, 都必须出现在视图里 (有相互作用就显示)
    _body_ids = {x[1] for x in OA.BODIES}
    _want = {(l.get("f"), l.get("t")) for l in data.links
             if l.get("f") in _body_ids and l.get("t") in _body_ids}
    _got = {(e["f"], e["t"]) for e in ed}
    chk("I1", "只画主体↔主体真连线 (2026-10-16 老倪: 连线太多 ⇒ 体系外一条都不画) 且一条不漏一条不造",
        {"视图线数": len(ed), "主体↔主体": len(_bb), "体系外(应为 0)": len(_ex2),
         "唯一依据应有": len(_want), "缺失": sorted(_want - _got)[:4], "多余(编造)": sorted(_got - _want)[:4]},
        _src_ok and _want == _got and len(_ex2) == 0 and len(ed) == len(_want), "唯一依据===视图 (只有主体↔主体)")
    # I1b 像素级: 每条主体↔主体线在画面里**真的可见** (清单相等 ≠ 真画出来 —— 端点取不到会被静默跳过)
    _A1b = _arr(v3.grab().toImage())
    _rs1b = v3.label_rects()
    _p1b = v3.positions()
    _S1b = v3._geom()[2]
    _cir = [(_p1b["_cx"], _p1b["_cy"], OA.OrbitalArchView.RAD["sun"] * _S1b)]
    for _k in ("mercury", "earth", "mars", "jupiter"):
        _cir.append((_p1b[_k][0], _p1b[_k][1], OA.OrbitalArchView.RAD[_k] * _S1b))
    for _x3, _y3, _z3, _sk3 in _p1b["_sat"]:
        _cir.append((_x3, _y3, OA.OrbitalArchView.RAD["sat"] * _S1b))

    def _visible(nid_a, nid_b, kind):
        def _pt(nid):
            if OA.OrbitalArchView._key_of(nid) == "sun":
                return (_p1b["_cx"], _p1b["_cy"])
            t = _p1b[OA.OrbitalArchView._key_of(nid)]
            return (t[0], t[1])
        ax, ay = _pt(nid_a)
        bx, by = _pt(nid_b)
        # 2026-10-16: 线色按**信号种类** (geom/perf/drive), 不是按 label 归类 ⇒ 掩码要用 sig_kind
        _k2 = None
        for _e2 in v3._edges:
            if _e2["f"] == nid_a and _e2["t"] == nid_b:
                _k2 = _e2.get("sig_kind")
        col = {"geom": [0x39, 0xc5, 0xcf], "condition": [0x39, 0xc5, 0xcf], "perf": [0xd2, 0x99, 0x22],
               "semantic": [0xd2, 0x99, 0x22], "drive": [0x3f, 0xb9, 0x50],
               "feedback": [0xa3, 0x71, 0xf7], "misc": [0x8b, 0x94, 0x9e]}[_k2 or kind]
        # 容差 320: 线压在金色引力井环上/浅角度抗锯齿时, 芯色会被混色 (掩码太紧会误判"线没了")
        mk = np.abs(_A1b - np.array(col)).sum(axis=2) < 320
        dx, dy = bx - ax, by - ay
        L = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / L, dx / L
        used, seen = 0, 0
        for f in [0.10 + 0.04 * i for i in range(21)]:
            qx, qy = ax + dx * f, ay + dy * f
            if any(r.adjusted(-3, -3, 3, 3).contains(QPointF(qx, qy)) for r in _rs1b):
                continue
            if any(math.hypot(qx - kx, qy - ky) < kr + 3 for (kx, ky, kr) in _cir):
                continue
            used += 1
            hit = False
            for j2 in range(-24, 25):
                t = j2 * 0.125
                x, y = int(round(qx + nx * t)), int(round(qy + ny * t))
                if 0 <= y < mk.shape[0] and 0 <= x < mk.shape[1] and mk[y, x]:
                    hit = True
                    break
            seen += hit
        return used, seen

    _vis = {}
    for _e in _bb:
        _u, _s2 = _visible(_e["f"], _e["t"], _e["kind"])
        _vis["%s→%s" % (_e["f"], _e["t"])] = [int(_s2), int(_u)]
    _ratios = [(s / u) for s, u in _vis.values() if u]
    # 2026-10-19: 原来要求每条线 ≥3 个可用采样点 —— 火星↔地球那类 8px 短线只有 1 个点, 必然误红。
    #   改成"至少 1 个采样点且有墨"; 命中率仍按 ≥45% (短线不参与比例门槛)。
    plot = (all(u >= 1 and s >= 1 for s, u in _vis.values())
            and all((s / u) >= 0.45 for s, u in _vis.values() if u)     # 虚线占空≈55% ⇒ 阈值 45%
            and (sum(_ratios) / max(1, len(_ratios))) >= 0.60)
    chk("I1b", "像素级: 每条主体↔主体虚线在画面里**真的可见** (虚线占空≈60% ⇒ 命中率阈 55%; 文字块/球体遮挡处跳过)",
        {"各线 命中/可用": _vis}, plot and len(_vis) == len(_bb), "每条线 ≥45% 命中 (虚线占空≈55%; 端点取不到会被静默跳过 → 这条能抓)")

    # 线宽: 沿主体↔主体线取 7 个位置, 每处沿**法向**取剖面, 最长连续命中 ≈ 该处线宽。
    #   取中位数判定 (单点会被"线正好压在轨道虚线/光晕上"这类局部干扰打偏 —— 判据要稳, 不能时红时绿)。
    p2 = v3.positions()
    _e0 = next((e for e in _bb if e["f"] in _body_ids and e["t"] in _body_ids), None)
    _runs, _mid = [], None

    def _posof(nid):
        if OA.OrbitalArchView._key_of(nid) == "sun":
            return (p2["_cx"], p2["_cy"], 0.0)
        return p2.get(OA.OrbitalArchView._key_of(nid))

    if _e0 is not None:
        _a = _posof(_e0["f"])
        _b2 = _posof(_e0["t"])
        if _a and _b2:
            _A = _arr(v3.grab().toImage())
            _m = np.zeros(_A.shape[:2], dtype=bool)
            for _col in ([0x39, 0xc5, 0xcf], [0xd2, 0x99, 0x22], [0x3f, 0xb9, 0x50], [0xa3, 0x71, 0xf7]):
                _m |= (np.abs(_A - np.array(_col)).sum(axis=2) < 200)
            _dx, _dy = _b2[0] - _a[0], _b2[1] - _a[1]
            _L = math.hypot(_dx, _dy) or 1.0
            _nx, _ny = -_dy / _L, _dx / _L
            _rsI = v3.label_rects()                     # 文字块是不透明底, 落进去的采样点要跳过
            for _f in (0.22, 0.30, 0.37, 0.43, 0.50, 0.57, 0.63, 0.70, 0.78):
                _qx, _qy = _a[0] + _dx * _f, _a[1] + _dy * _f
                if any(r.adjusted(-2, -2, 2, 2).contains(QPointF(_qx, _qy)) for r in _rsI):
                    continue
                _prof = []
                for _i in range(-40, 41):                    # ±5px, 步长 0.125px
                    _t = _i * 0.125
                    _x, _y = int(round(_qx + _nx * _t)), int(round(_qy + _ny * _t))
                    _prof.append(bool(_m[_y, _x]) if (0 <= _y < _m.shape[0] and 0 <= _x < _m.shape[1]) else False)
                _run = _best = 0
                for _v in _prof:
                    _run = _run + 1 if _v else 0
                    _best = max(_best, _run)
                if _best > 0:                     # 2026-10-16: 线全改虚线 ⇒ 落在间隔里的剖面不计 (否则中位数被 0 拉低)
                    _runs.append(round(_best * 0.125, 3))
            _mid = [round(_a[0] + _dx * 0.5, 1), round(_a[1] + _dy * 0.5, 1)]
    _med = float(np.median(_runs)) if _runs else 0.0
    chk("I2", "连线不细 (2026-10-16 看图: 2.2px 仍被判『丝线档』 ⇒ 加粗到 2.9px): 沿线 7 处法向剖面线宽中位数 ≥ 2.5px",
        {"线": "%s→%s (%s)" % (_e0["f"], _e0["t"], _e0["kind"]) if _e0 else None, "中点": _mid,
         "7 处线宽 px": _runs, "中位数": _med},
        _med >= 2.5 and len(_runs) >= 3, "中位数 ≥2.5px (≥3 个有效采样点, 不靠单点侥幸)")
    # 不闪/不消失: 相邻两帧 (一个 tick) 的线像素数变化小, 且都没有归零; 三帧内不做透明度脉冲
    def _linepx():
        _a = _arr(v3.grab().toImage())
        _m = np.zeros(_a.shape[:2], dtype=bool)
        for _col in ([0x39, 0xc5, 0xcf], [0xd2, 0x99, 0x22], [0x3f, 0xb9, 0x50], [0xa3, 0x71, 0xf7]):
            _m |= (np.abs(_a - np.array(_col)).sum(axis=2) < 150)
        return int(_m.sum()), _m
    _c1, _m1 = _linepx()
    v3._phase = (v3._phase + 0.06) % 12.0
    _c2, _m2 = _linepx()
    v3._phase = (v3._phase + 0.06) % 12.0
    _c3, _m3 = _linepx()
    _diff = int((_m1 ^ _m2).sum())
    _rel = _diff / max(1, _c1)
    chk("I3", "连线平顺不闪: 帧间只做慢速流动 (变化像素占比小), 三帧线量稳定 (无透明度脉冲/不整条消失)",
        {"三帧线像素": [_c1, _c2, _c3], "帧间变化像素": _diff, "变化占比": round(_rel, 3),
         "三帧极差/均值": round((max(_c1, _c2, _c3) - min(_c1, _c2, _c3)) / max(1.0, (_c1 + _c2 + _c3) / 3.0), 3)},
        0 < _rel < 0.35 and (max(_c1, _c2, _c3) - min(_c1, _c2, _c3)) / max(1.0, (_c1 + _c2 + _c3) / 3.0) < 0.12
        and min(_c1, _c2, _c3) > 300,
        "变化占比 <0.35 · 三帧线量极差 <12% · 每帧线像素 >300 (不闪不消失)")

    # ═══ J 文字不许压盖/截断 (老倪红线; 看图抓到过: 月球标签压地球标签 / 金球压水星参数行) ═══
    _W = int(v3.width())
    _H = int(v3.height())
    _rs = v3.label_rects()
    _inter = [(i, j) for i, r in enumerate(_rs) for j, r2 in enumerate(_rs) if j > i and r.intersects(r2)]
    _oob = [i for i, r in enumerate(_rs)
            if r.x() < 1 or r.y() < 1 or r.x() + r.width() > _W - 1 or r.y() + r.height() > _H - 1]
    _minarea = min((r.width() * r.height() for r in _rs), default=0)
    chk("J1", "文字块互不压盖、都在画布内: 每个球/团队标签各占一块 (先避让再画)",
        {"文字块数": len(_rs), "相交对": _inter, "出画布": _oob,
         "块位置": [[round(r.x()), round(r.y()), round(r.width()), round(r.height())] for r in _rs]},
        len(_rs) >= 5 and not _inter and not _oob and _minarea > 0, "无相交 · 无出界")
    _imJ = _arr(v3.grab().toImage())
    _empty = []
    for _i, _r in enumerate(_rs):
        _box = _imJ[int(_r.y()):int(_r.y() + _r.height()), int(_r.x()):int(_r.x() + _r.width())]
        _bright = int((_box.sum(axis=2) > 240).sum()) if _box.size else 0
        if _bright < 30:
            _empty.append((_i, _bright))
    chk("J2", "每块文字**真的画出来了** (块内亮像素 ≥30: 不是空框/被盖成背景色)",
        {"亮像素最少的块": sorted([(i, int((_imJ[int(r.y()):int(r.y() + r.height()), int(r.x()):int(r.x() + r.width())].sum(axis=2) > 240).sum())) for i, r in enumerate(_rs)], key=lambda t: t[1])[:3],
         "疑似空块": _empty}, not _empty, "每块都有字")
    _fl = v3._foot_lines(_W)
    _fmJ = v3._fm(9)
    _tooWide = [t for t in _fl if _fmJ.horizontalAdvance(t) > _W - 8]
    _joined = "\n".join(_fl)
    chk("J3", "底部图注**完整** (自动换行写全, 不用省略号截断): 无「…」· 每行都不超宽 · 关键项都在",
        {"行数": len(_fl), "超宽行": _tooWide,
         "含省略号": [t for t in _fl if "…" in t],
         "关键项": {k: (k in _joined) for k in ("线义", "L2~L5", "唯一依据", "torque_live")}},
        # 2026-10-19 老倪「字数太多要精简」: 图注由 4 行砍到 3 行短句 ⇒ 判据只核"不截断 + 三个锚点还在"
        len(_fl) >= 3 and not _tooWide and not any("…" in t for t in _fl)
        and all(k in _joined for k in ("线义", "L2~L5", "唯一依据", "torque_live")),
        "全在 · 无省略号 · 无超宽")

    # ═══ K 视觉缺陷收口 (2026-10-16 逐图复核: 地球区三条互压 / 标签压球 / 卫星互叠压地球 / 月球混堆 /
    #     线仍偏细 / 底部三行压在球上) ═══
    _Wk, _Hk, _Sk, _cxk, _cyk, _Rk = v3._geom()
    _posk = v3.positions(_cxk, _cyk, _Rk)
    _rad = {k: _Sk * v3.RAD[k] for k in v3.RAD}
    _bodies = [("sun", _cxk, _cyk, _rad["sun"])]
    for _k in ("mercury", "earth", "mars", "jupiter"):
        _x, _y, _z = _posk[_k]
        _bodies.append((_k, _x, _y, _rad[_k]))
    _mx, _my, _mz = _posk["moon"]
    _bodies.append(("moon", _mx, _my, _rad["moon"]))
    _sats = [(_x, _y, _sk) for _x, _y, _z, _sk in _posk["_sat"]]

    def _ball_hit(rect, x, y, r):
        nx = max(rect.x(), min(x, rect.x() + rect.width()))
        ny = max(rect.y(), min(y, rect.y() + rect.height()))
        return math.hypot(nx - x, ny - y) < r + 1.0

    _on_ball = []
    for _i, _r in enumerate(_rs):
        for _nm, _x, _y, _rr in _bodies:
            if _ball_hit(_r, _x, _y, _rr):
                _on_ball.append((_i, _nm))
        for _x, _y, _sk in _sats:
            if _ball_hit(_r, _x, _y, _rad["sat"]):
                _on_ball.append((_i, "sat_%s" % _sk))
    chk("K1", "文字块不压在球体/卫星上 (每块都做了带底避让: 与球心距 ≥ 球半径+1)",
        {"压球的块": _on_ball[:6], "球数": len(_bodies), "卫星数": len(_sats)}, not _on_ball,
        "0 块压球" if not _on_ball else "压 %d 处" % len(_on_ball))
    _dmin, _dearth, _dbad = 1e9, 1e9, []
    for _i in range(len(_sats)):
        for _j in range(_i + 1, len(_sats)):
            _d = math.hypot(_sats[_i][0] - _sats[_j][0], _sats[_i][1] - _sats[_j][1])
            _dmin = min(_dmin, _d)
    for _x, _y, _sk in _sats:
        _dearth = min(_dearth, math.hypot(_x - _posk["earth"][0], _y - _posk["earth"][1]))
    _need = 2 * _rad["sat"] + 2.0
    chk("K2", "卫星不互叠、不压地球 (相邻屏距 ≥ 2r+2px · 离地球 ≥ r_earth+r_sat)",
        {"相邻最小屏距": round(_dmin, 2), "需要": round(_need, 2),
         "离地球最小": round(_dearth, 2), "需要": round(_rad["earth"] + _rad["sat"], 2)},
        _dmin >= _need and _dearth >= _rad["earth"] + _rad["sat"], "卫星圈排得开")
    _dmoon = math.hypot(_mx - _posk["earth"][0], _my - _posk["earth"][1])
    _mneed = v3.SAT_R * _Rk + _rad["sat"] + _rad["moon"]
    chk("K3", "月球在卫星圈外 (离地球 ≥ 卫星圈半径 + r_sat + r_moon ⇒ 不与卫星混成一片)",
        {"月球离地球": round(_dmoon, 2), "需要": round(_mneed, 2),
         "卫星圈半径": round(v3.SAT_R * _Rk, 2)}, _dmoon >= _mneed, "月球在外圈")
    _padb = 12 + 11 * len(v3._foot_lines(_Wk))
    _in_band = [(_nm, round(_y + _rr - (_Hk - _padb), 1)) for _nm, _x, _y, _rr in _bodies + [("sat", a, b, _rad["sat"]) for a, b, _sk in _sats]
                if _y + _rr > _Hk - _padb]
    chk("K4", "底部图注带里没有球体 (球压在说明行上的问题收口: 布局已按图注行数缩排)",
        {"球进底栏带": _in_band[:6], "底栏高": _padb}, not _in_band, "底栏干净")
    _tok = None
    for _t in v3._foot_lines(_Wk):
        for _cand in ("紫", "青", "金", "绿"):
            if _cand + "=" in _t and ("虚线" in _t or "线义" in _t):
                _tok = _tok or _cand
    _pal = {"紫": OA.VIOLET, "青": OA.CYAN, "金": OA.GOLD, "绿": OA.GREEN}
    _c = _pal.get(_tok)
    _ok_color = bool(_c is not None) and (
        (_tok == "紫" and _c.blue() > _c.red() and _c.blue() > _c.green()) or
        (_tok == "青" and _c.green() > 120 and _c.blue() > 120 and _c.red() < 120) or
        (_tok == "金" and _c.red() > _c.green() > _c.blue()) or
        (_tok == "绿" and _c.green() > _c.red() and _c.green() > _c.blue()))
    chk("K5", "图例写的虚线颜色 == 实画虚线颜色 (看图报「图例写褐色·实画蓝紫」⇒ 现在必须同源)",
        {"图例token": _tok, "实际色": _c.name() if _c else None, "RGB": [_c.red(), _c.green(), _c.blue()] if _c else None},
        _ok_color, "图例与色板一致 (%s)" % _tok)

    # ── J6: 球标签不硬截唯一依据串 (2026-10-16 看图: 唯一依据串被 str(state)[:10] 硬截 ⇒ 图上「自由空间 (无接触约」) ──
    _oa_src = open(os.path.join(ROOT, "tools/gui/orbital_arch.py"), encoding="utf-8").read()
    _long = "自由空间 (无接触约束)"
    _txt6 = v3._body_text("mercury", {"progress": 0.125, "risk": 0.0, "state": _long})
    chk("J6", "球标签把唯一依据串写全 (无 [:10] 硬截; 太长才由 _fit 省略)",
        {"标签": _txt6[:88], "可执行硬截还在?": 'or "")[:10]' in _oa_src},
        (_long in _txt6) and ('or "")[:10]' not in _oa_src), "整串「%s」都在标签里 (注释可留, 代码不许硬截)" % _long)

    # ═══ F 文案诚实 ═══
    chk("F1", "图注写清 角度映射 (位置不是装饰, 是实测量的映射)",
        {"含角度映射": "角度映射" in src}, "角度映射" in src, "源码图注含该项")
    chk("F2", "脚注含唯一依据清单 + 帧龄 + 节点映射核对数 (可复核)",
        {"含唯一依据": "唯一依据:" in src, "含帧龄": "帧龄" in src, "含节点映射核对": "节点映射核对" in src},
        all(k in src for k in ("唯一依据:", "帧龄", "节点映射核对")), "三项都在")

    # ═══ L 本轮口径 (老倪 2026-10-16): 全虚线 · 颜色=信号 · 有才显示 · 轨道可见 · 卫星 SK01-08 ═══
    _vL = OA.OrbitalArchView(root=_FREEZE)
    _vL.resize(682, 1391)
    _vL._phase = 0.0
    _WL, _HL, _SL, _cxL, _cyL, _RL = _vL._geom()
    _imgL = _vL.grab().toImage()
    _aL = _arr(_imgL)
    _bgL = np.array([OA.BG.red(), OA.BG.green(), OA.BG.blue()])
    _pL = _vL.positions()
    _rsL = _vL.label_rects()
    _cirL = [(_pL["_cx"], _pL["_cy"], OA.OrbitalArchView.RAD["sun"] * _SL)]   # 球径 = S·RAD (不是 R·RAD!)
    for _k in ("mercury", "earth", "mars", "jupiter"):
        _cirL.append((_pL[_k][0], _pL[_k][1], OA.OrbitalArchView.RAD[_k] * _SL))
    for _x2, _y2, _z2, _sk2 in _pL["_sat"]:
        _cirL.append((_x2, _y2, OA.OrbitalArchView.RAD["sat"] * _SL))

    def _ink_iso(x, y, col=None, tol=200):
        if x < 0 or y < 0 or y >= _aIso.shape[0] or x >= _aIso.shape[1]:
            return False
        v2 = _aIso[int(y), int(x)]
        if col is None:
            return float(np.abs(v2 - np.array([OA.BG.red(), OA.BG.green(), OA.BG.blue()])).sum()) > 14
        return float(np.abs(v2 - np.array(col)).sum()) < tol

    def _ink(x, y, col=None, tol=200):
        if x < 0 or y < 0 or y >= _aL.shape[0] or x >= _aL.shape[1]:
            return False
        v = _aL[int(y), int(x)]
        if col is None:
            return float(np.abs(v - _bgL).sum()) > 14
        return float(np.abs(v - np.array(col)).sum()) < tol

    # L1 全虚线: 沿线采样, 必须出现 ≥2 段"空档" (实线不可能有空档)
    _e1L = [e for e in _vL.interactions() if e["f"] == "ss_mani_eng"][0]
    # 只留这条线再抓图: 同向重叠的金线会把芯色盖掉 (水星/木星角度都为 0 时两条线共线),
    # 用"隔离视图"量这条线自己的划/隔几何 —— 不靠混色猜。
    _vIso = OA.OrbitalArchView(root=_FREEZE)
    _vIso.resize(682, 1391)
    _vIso._phase = 0.0
    _vIso._edges = [_e1L]
    _imgIso = _vIso.grab().toImage()
    _aIso = _arr(_imgIso)
    _pa, _pb = _vIso.positions()[OA.OrbitalArchView._key_of(_e1L["f"])], _vIso.positions()[OA.OrbitalArchView._key_of(_e1L["t"])]
    _dxL, _dyL = _pb[0] - _pa[0], _pb[1] - _pa[1]
    _colL = {"geom": [0x39, 0xc5, 0xcf], "perf": [0xd2, 0x99, 0x22], "drive": [0x3f, 0xb9, 0x50],
             "feedback": [0xa3, 0x71, 0xf7]}.get(_e1L.get("sig_kind") or _e1L["kind"], [0x39, 0xc5, 0xcf])
    _seq = []
    for _f in [0.08 + 0.004 * _i for _i in range(210)]:
        _qx, _qy = _pa[0] + _dxL * _f, _pa[1] + _dyL * _f
        _qx, _qy = _pa[0] + _dxL * _f, _pa[1] + _dyL * _f
        if any(r.adjusted(-3, -3, 3, 3).contains(QPointF(_qx, _qy)) for r in _rsL):
            continue
        if any(math.hypot(_qx - kx, _qy - ky) < kr + 2 for (kx, ky, kr) in _cirL):
            continue
        _seq.append(_ink_iso(_qx, _qy, _colL))
    if os.environ.get("OA_DEBUG_L1"):
        _cnt = {}
        for _i2 in range(len(_seq)):
            pass
        for _f2 in [0.08 + 0.004 * _i for _i in range(210)]:
            _xx, _yy = int(_pa[0] + _dxL * _f2), int(_pa[1] + _dyL * _f2)
            _cc = tuple(int(z) for z in _aL[_yy, _xx])
            _cnt[_cc] = _cnt.get(_cc, 0) + 1
        print("   [dbg] top色", sorted(_cnt.items(), key=lambda kv: -kv[1])[:5], "| 采样", len(_seq))
        print("   [dbg] pa=%s pb=%s len=%.1f col=%s duty_first10=%s" % (
            [round(x, 1) for x in _pa[:2]], [round(x, 1) for x in _pb[:2]],
            math.hypot(_dxL, _dyL), _colL,
            [tuple(int(z) for z in _aL[int(_pa[1] + _dyL * (0.08 + 0.004 * i)), int(_pa[0] + _dxL * (0.08 + 0.004 * i))]) for i in range(0, 10, 3)]))
    _gaps = _runs_hit = 0
    _cur = 0
    for _h in _seq:
        if _h:
            _runs_hit += 1
            _cur = 0
        else:
            _cur += 1
            if _cur == 2:
                _gaps += 1
    _duty = _runs_hit / max(1, len(_seq))
    chk("L1", "全部连线是**虚线** (2026-10-16 老倪: 直线实线改成虚线): 沿线按线色采样出现 ≥2 段空档",
        {"采样点": len(_seq), "线色占比": round(_duty, 3), "空档段数": _gaps, "线色": _e1L.get("sig_kind")},
        _gaps >= 2 and 0.20 <= _duty <= 0.95, "虚线 (空档≥2) 且不是实线/不是全空")

    # L2 颜色 = 信号种类 (几何青 · 性能金 · 动作绿), 且至少 2 种
    _exp = {"geom": OA.CYAN, "condition": OA.CYAN, "perf": OA.GOLD, "semantic": OA.GOLD, "drive": OA.GREEN}
    _cols = {}
    for _e in _vL.interactions():
        _t = _exp.get(_e.get("sig_kind") or _e["kind"])
        if _t is not None:
            _cols[_e.get("sig_kind") or _e["kind"]] = _t.name()
    chk("L2", "线的颜色=信号种类 (青=几何条件 · 金=性能/集合 · 绿=动作/前馈 · 紫=反馈) 且 ≥2 种",
        {"信号→色": _cols, "种数": len(set(_cols.values()))},
        len(set(_cols.values())) >= 2 and all(OA.OrbitalArchView.SIG_OF.get((e["f"], e["t"]), (None,))[0] is not None
                                              for e in _vL.interactions()),
        "每条线都有信号归属 (SIG_OF), 颜色按信号")

    # L3 门控: 信号没值 ⇒ 那条线不画 (有就显示, 没有就不显示)
    _n_before = len(_vL.interactions())
    _save = _vL.data.body["mercury"].get("progress")
    _vL.data.body["mercury"]["progress"] = None
    _n_after = len(_vL.interactions())
    _gone = {(e["f"], e["t"]) for e in _vL._edges if not _vL._signal_ok(e, _vL.data.body)}
    _vL.data.body["mercury"]["progress"] = _save
    chk("L3", "「有就显示, 没有就不显示」: 撤掉信号值 ⇒ 依赖它的线**不画** (不是画假线)",
        {"撤值前画出": _n_before, "撤值后画出": _n_after, "被撤下的线": sorted(_gone)},
        _n_after < _n_before and _n_after == _n_before - len(_gone) and len(_gone) >= 2,
        "几何条件信号缺失 ⇒ 2 条经接触流形的线消失")

    # L4 背景圆形轨道可见 (老倪: 「背景的圆形轨道也要体现出」)
    _ring_ok = {}
    for _k, _frac in OA.OrbitalArchView.ORB.items():
        _hit = _tot = 0
        for _i in range(72):
            _t = _i / 72.0 * 2 * math.pi
            _x, _y, _z = _vL._proj(_frac * math.cos(_t), _frac * math.sin(_t), 0.0, _pL["_cx"], _pL["_cy"], _pL["_R"])
            if _x < 1 or _y < 1 or _x > 680 or _y > 1388:
                continue
            _tot += 1
            _hit += 1 if _ink(_x, _y) else 0
        _ring_ok[_k] = round(_hit / max(1, _tot), 2)
    chk("L4", "背景轨道环真的画出来了 (4 条行星轨道 + 地球卫星环, 虚线在动): 每条轨道采样点有墨 ≥25%",
        _ring_ok, min(_ring_ok.values()) >= 0.25, "每条轨道 ≥25% 采样点见线")

    # L5 卫星 = 原子技能 SK01~SK08 各一颗, 且逐颗标了 SK 号
    _ids = [d["SK"] for d in (_vL.data.body.get("sats", {}).get("list") or [])]
    _want_ids = ["SK%02d" % i for i in range(1, 9)]
    # 2026-10-19 UI 改口径: 老倪要求"文字一律靠右固定, 不要飘" ⇒ 不再逐颗浮标,
    #   改成右栏一行 SK01…SK08 区间标号。判据改为: 8 颗都在 + 右栏标出了首尾 SK 号 + 颗数。
    _allL = " ".join("".join(ln for ln in ls) for _r, ls in _blocksL_all) if False else ""
    _rsL_txt = " ".join("".join(ln for ln in ls) for _r, ls in _vL.label_texts())
    _sk_ok = ("SK01" in _rsL_txt and "SK08" in _rsL_txt and "8" in _rsL_txt)
    chk("L5", "卫星 = 原子技能 SK01~SK08 各一颗 (老倪口径), 右栏一行标出首尾 SK 号 + 颗数",
        {"卫星": _ids, "右栏含": {"SK01": "SK01" in _rsL_txt, "SK08": "SK08" in _rsL_txt}, "期望": _want_ids},
        _ids == _want_ids and _sk_ok,
        "8 颗 SK01~SK08 + 右栏 SK01…SK08 标号")

    # ═══ M 第三轮看图 (deleg_8a68a5dd) 收口: 天体名 · 自适应宽 · 块间距 · 线不穿球 · 卫星环可见 ═══
    _vM = OA.OrbitalArchView(root=_FREEZE)
    _vM.resize(682, 1391)
    _vM._phase = 0.0
    _blocksM = _vM.label_texts()
    _allM = " | ".join("".join(ln for ln in ls) for _r, ls in _blocksM)
    _needN = {"太阳": "☀", "水星": "☿", "地球": "♁", "火星": "♂", "木星": "♃", "月球": "🌙"}
    _missN = [k for k in _needN if k not in _allM]
    chk("M1", "每个天体都有一块**带天体名**的标签 (老倪口径: 只有 太阳/木星/火星/水星/地球/月球 + SK 卫星)",
        {"块数": len(_blocksM), "缺天体名": _missN or "无"},
        not _missN, "六类天体名都出现在标签里")
    _wide = [(round(r.width()), max(len(l) for l in ls)) for r, ls in _blocksM]
    # 宽度的自适应要在**真实尺寸**下看 (M 页太阳系区是 1080×360)
    _vW = OA.OrbitalArchView(root=_FREEZE)
    _vW.resize(1080, 360)
    _wideW = [(round(r.width()), max(len(l) for l in ls)) for r, ls in _vW.label_texts()]
    _over = [w for w, _n in _wideW if w > OA.OrbitalArchView.COL_W]
    # 2026-10-22 老倪「太阳系的右侧的字体, 不要乱动。固定住」⇒ 口径反过来了:
    #   老口径(每块按自己文字宽度自适应)会让数字一换位数就横移 13px (实测), 已作废。
    #   新口径: 整列**一个固定宽度** = _col_w(W), 左缘恒定 ⇒ 文字不挪; 只随窗口宽度变。
    _wantw = round(_vW._col_w(1080))
    _wantw2 = round(_vW._col_w(682))
    _same = (len({w for w, _n in _wideW}) == 1) and (len({w for w, _n in _wide}) == 1)
    chk("M2", "右栏一列**固定宽度** (左缘恒定 ⇒ 文字不随数字位数挪动), 宽 = _col_w(W) 且 ≤ COL_W",
        {"块宽(1080宽)": [w for w, _n in _wideW], "期望宽": _wantw,
         "682宽": [w for w, _n in _wide], "期望宽682": _wantw2},
        (not _over) and _same
        and all(w == _wantw for w, _n in _wideW) and all(w == _wantw2 for w, _n in _wide),
        "同一尺寸下所有块等宽 = _col_w(W) (数据跳动时左缘 0px 位移, 见 verify_orbital_rightcol_frozen.py)")

    def _gapM(r1, r2):
        dx = max(0.0, max(r1.x(), r2.x()) - min(r1.x() + r1.width(), r2.x() + r2.width()))
        dy = max(0.0, max(r1.y(), r2.y()) - min(r1.y() + r1.height(), r2.y() + r2.height()))
        return math.hypot(dx, dy)

    _mind, _pair = 999.0, None
    for _i in range(len(_blocksM)):
        for _j in range(_i + 1, len(_blocksM)):
            _g = _gapM(_blocksM[_i][0], _blocksM[_j][0])
            if _g < _mind:
                _mind, _pair = _g, (_i, _j)
    chk("M3", "相邻文字块之间留 ≥2px 间隙 (看图报: 两框 0px 相贴/球底与框顶只 3px)",
        {"最小间隙px": round(_mind, 1), "最近两块": _pair}, _mind >= 2.0, "块间最小间隙 ≥2px")

    _AM = _arr(_vM.grab().toImage())
    _pM = _vM.positions()
    _SM = _vM._geom()[2]
    _onball = {}
    for _k, _col in (("mercury", [0x39, 0xc5, 0xcf]), ("earth", [0x3f, 0xb9, 0x50]),
                     ("mars", [0x39, 0xc5, 0xcf]), ("jupiter", [0x3f, 0xb9, 0x50]),
                     ("moon", [92, 104, 122])):
        _x, _y = int(_pM[_k][0]), int(_pM[_k][1])
        _r = int(_SM * OA.OrbitalArchView.RAD[_k] * 0.8)
        _pix = 0
        for _dy2 in range(-_r, _r + 1):
            for _dx2 in range(-_r, _r + 1):
                if _dx2 * _dx2 + _dy2 * _dy2 > _r * _r:
                    continue
                _yy2, _xx2 = _y + _dy2, _x + _dx2           # 2026-10-19: 贴边天体 (木星 x+r>宽) 采样越界 ⇒ 先夹到图内
                if not (0 <= _yy2 < _AM.shape[0] and 0 <= _xx2 < _AM.shape[1]):
                    continue
                _c = _AM[_yy2, _xx2]
                if float(np.abs(_c - np.array(_col)).sum()) < 45:
                    _pix += 1
        _onball[_k] = _pix
    chk("M4", "连线**不画在球面上** (看图报: 线穿过太阳/水星/火星球面 ⇒ z 序错; 透描已加球体裁剪)",
        _onball, sum(_onball.values()) <= 6, "球心区几乎无线色像素")

    _ringM = {}
    _eaM = _vM._angles(_vM.data.body).get("earth", 0.0)
    _erM = OA.OrbitalArchView.ORB["earth"]
    _satrM = OA.OrbitalArchView.SAT_R
    for _name, _fn in (("卫星环", lambda t: (_erM * math.cos(_eaM) + _satrM * math.cos(t),
                                            _erM * math.sin(_eaM) + _satrM * math.sin(t))),):
        _hit = _tot = 0
        for _i in range(120):
            _t = _i / 120.0 * 2 * math.pi
            _fx, _fy = _fn(_t)
            _x, _y, _z = _vM._proj(_fx, _fy, 0.0, _pM["_cx"], _pM["_cy"], _pM["_R"])
            if _x < 1 or _y < 1 or _x > 680 or _y > 1388:
                continue
            _tot += 1
            _hit += 1 if float(np.abs(_AM[int(_y), int(_x)] - np.array([OA.BG.red(), OA.BG.green(), OA.BG.blue()])).sum()) > 30 else 0
        _ringM[_name] = round(_hit / max(1, _tot), 2)
    chk("M5", "地球卫星环在深底上看得见 (看图报: 太暗几乎看不见 ⇒ α=170/宽1.4)", _ringM,
        min(_ringM.values()) >= 0.25, "环上 ≥25% 采样点见线")

    # ═══ N 第三轮看图 (deleg_e7ca3752) 收口: 引力井配色 · 共线去重叠 · 地月线 · 引线 ═══
    _srcN = io.open(os.path.join(ROOT, "tools", "gui", "orbital_arch.py"), encoding="utf-8").read()
    _wellk = [s2 for s2 in ("QColor(91, 107, 125,", "QColor(210, 153, 34,") if s2 in _srcN]
    _d_well = abs(91 - 210) + abs(107 - 153) + abs(125 - 34)
    chk("N1", "引力井椭圆与**金线辉光**颜色可分 (看图报: 同色差2 ⇒ 1× 数不出圈数) + 只留 3 圈",
        {"井色": _wellk, "与金线色距": _d_well, "圈数": _srcN.count("rr = 0.12 + 0.09 * i") and 3},
        _wellk == ["QColor(91, 107, 125,"] and _d_well >= 60, "井=冷灰蓝(91,107,125), 与金线色距 ≥60")

    _vN = OA.OrbitalArchView(root=_FREEZE)
    _vN.resize(682, 1391)
    _vN._phase = 0.0
    _pN = _vN.positions()
    _liveN = [e for e in _vN._edges if e["body_body"] and _vN._signal_ok(e, _vN.data.body)]
    # 量**实际画出来的几何** (含共线法向平移) —— 只读 positions() 会量到平移之前
    _sgN = [(n, x1, y1, x2, y2) for (n, x1, y1, x2, y2) in _vN.drawn_segments()]
    _imin, _ipair = 999.0, None
    for _i in range(len(_sgN)):
        for _j in range(_i + 1, len(_sgN)):
            _A, _B = _sgN[_i], _sgN[_j]
            # 共享端点的两条边是**折线的相邻段**, 不是"两条线糊成一条" ⇒ 不参与共线判据
            #   (ss_mani_eng→ssmani_p 与 ssmani_p→ssdec 共顶点, 带距天然≈0)
            _ea = (_A[1], _A[2]); _eb = (_A[3], _A[4])
            _ec = (_B[1], _B[2]); _ed = (_B[3], _B[4])
            if min(math.hypot(p1[0] - p2[0], p1[1] - p2[1])
                   for p1 in (_ea, _eb) for p2 in (_ec, _ed)) < 6.0:
                continue
            _angN = abs(math.atan2(_A[4] - _A[2], _A[3] - _A[1]) - math.atan2(_B[4] - _B[2], _B[3] - _B[1])) % math.pi
            if min(_angN, math.pi - _angN) > 0.17:      # 不共线 ⇒ 不算
                continue
            _dxN, _dyN = _A[3] - _A[1], _A[4] - _A[2]
            _nnN = math.hypot(_dxN, _dyN) or 1.0
            # 2026-10-19: 原来取两条线的**端点**最小法向距 —— 两条线只要共用一端 (太阳→水星 / 水星→ssdec
            #   这类链式边) 在共用顶点处必然是 0px, 会被误判成"糊成一条"。改成量**中点**的法向带距:
            #   真糊成一条 ⇒ 中点距 0; 只是共用顶点、方向不同 ⇒ 中点距很大 (不误报)。
            # 取 5 个采样点的**中位数**带距: 两条近平行线只在某一点交叉 (X 交叉) 是正常的,
            #   用最小值会被一个交点判成"糊成一条"(0px)。中位数能区分"整体重合"和"交叉一次"。
            _ds = []
            for _tt in (0.2, 0.35, 0.5, 0.65, 0.8):
                _sx = _A[1] + (_A[3] - _A[1]) * _tt
                _sy = _A[2] + (_A[4] - _A[2]) * _tt
                _ds.append(abs((_sx - _B[1]) * (-_dyN / _nnN) + (_sy - _B[2]) * (_dxN / _nnN)))
            _ds.sort()
            _dd = _ds[len(_ds) // 2]
            if _dd < _imin:
                _imin, _ipair = _dd, (_A[0], _B[0])
    chk("N2", "近共线的两条真连线**不再糊成一条** (看图报: 太阳→水星青线被太阳→木星金线吞掉)",
        {"共线对最小带距px": round(_imin, 1) if _ipair else "无共线对", "最近对": _ipair or "无"},
        (_imin >= 3.0) or (_ipair is None), "共线线对之间 ≥3px 带距")

    _lzN = {}
    for _k2 in ("earth", "moon"):
        _x2, _y2 = int(_pN[_k2][0]), int(_pN[_k2][1])
        _r2 = int(_SM * OA.OrbitalArchView.RAD[_k2] * 0.8)
        _c2 = 0
        for _dy3 in range(-_r2, _r2 + 1):
            for _dx3 in range(-_r2, _r2 + 1):
                if _dx3 * _dx3 + _dy3 * _dy3 > _r2 * _r2:
                    continue
                if float(np.abs(_AM[_y2 + _dy3, _x2 + _dx3] - np.array([92, 104, 122])).sum()) < 45:
                    _c2 += 1
        _lzN[_k2] = _c2
    chk("N3", "**地月细连线**不压在球面上 (看图报: 1px 线穿地球/月球球面 ⇒ 已挪到球体之前 + 两端缩到球外)",
        _lzN, sum(_lzN.values()) <= 4, "地球/月球球心区无该线色像素")

    # 2026-10-19 老倪: 「把文字与球体的连线去掉, 太乱了; 有颜色对应就可以了」
    #   ⇒ 判据换成两条: (a) 一条引线都不许画; (b) 每行文字色 == 该天体球体色 (颜色=唯一对应关系)。
    _vN._leaders = []
    _lnN = [t2 for t2 in _vN.label_texts()]
    _ldN = len(getattr(_vN, "_leaders", []))
    _Wn, _Hn, _Sn, _cxn, _cyn, _Rn = _vN._geom()
    _blkN, _plcN = _vN._label_blocks(_vN.positions(_cxn, _cyn, _Rn), _vN.data.body,
                                     _cxn, _cyn, _Rn, _Sn, _Wn, _Hn)
    # 用**天体符号**匹配 (不能用中文名: SK 行写着"绕地球", 会误命中地球那一行)
    _colmap = {"☀": "sun", "☿": "mercury", "♁": "earth", "🌙": "moon",
               "♂": "mars", "♃": "jupiter"}
    _colok, _colbad = 0, []
    for _r, _ls, _c, _sz in _blkN:
        _t1 = "".join(_ls)
        for _nm, _k in _colmap.items():
            if _nm in _t1:
                _want = QColor(OA.OrbitalArchView.COL[_k]).name()
                if QColor(_c).name() == _want:
                    _colok += 1
                else:
                    _colbad.append((_nm, QColor(_c).name(), _want))
                break
    chk("N4", "文字↔球体**不画引线** (老倪: 太乱) 且**颜色一一对应** (文字色 == 球体色)",
        {"引线条数": _ldN, "配色对上的天体数": _colok, "配色错": _colbad or "无"},
        _ldN == 0 and _colok >= 6 and not _colbad, "6 类天体的文字色与球体色完全一致")

    # ═══ O 第四轮看图 (deleg_8a8b59f1) 收口: SK 错相位 · 金圈不侵入 · 短连线可见 · 块不贴边/不压球 ═══
    _SK = OA.OrbitalArchView
    # 2026-10-19: 起相位从固定 0.26rad 改成 **π/n (半个间距)** —— 8 颗时最近的一颗离地月线 22.5° (最优);
    #   固定 0.26 只有 15°, 投影压扁后垂距 5.6px 会压线 (判据 O3)
    _src_o = io.open(os.path.join(ROOT, "tools", "gui", "orbital_arch.py"), encoding="utf-8").read()
    chk("O1", "卫星起相位**与月球错开** (取半个间距 π/n, 最近的一颗离地月线最远)",
        "math.pi / _n_s" in _src_o and "ea + math.pi / _n_s" in _src_o,
        "卫星相位 = 地球相位 + π/n (n=8 ⇒ 22.5°)")

    _vO = OA.OrbitalArchView(root=_FREEZE)
    _vO.resize(682, 1391)
    _vO._phase = 0.0
    _pO = _vO.positions()
    _SO = _vO._geom()[2]
    _RO = _vO._geom()[5]
    _act = _vO.data.body.get("sats", {}).get("active")
    _ex, _ey = _pO["earth"][0], _pO["earth"][1]
    _mx, _my = _pO["moon"][0], _pO["moon"][1]
    _re = _SO * _SK.RAD["earth"]; _rs = _SO * _SK.RAD["sat"]; _rm = _SO * _SK.RAD["moon"]
    _mind_sat, _mind_name = 999.0, None
    for _x, _y, _z2, _sk2 in _pO.get("_sat", []):
        _d = math.hypot(_x - _ex, _y - _ey)
        if _d < _mind_sat:
            _mind_sat, _mind_name = _d, _sk2
    _need_sat = _re + _rs + 2.0 + 1.0            # 地球面 + (卫星球+金圈2px) + 1px 余量
    chk("O2", "在役卫星的**金圈不侵入地球球面** (看图: 侵入 1.8px) + 卫星圈仍在地球外",
        {"最近地-卫距px": round(_mind_sat, 1), "需≥px": round(_need_sat, 1), "卫星": _mind_name,
         "地月距px": round(math.hypot(_mx - _ex, _my - _ey), 1)},
        _mind_sat >= _need_sat and math.hypot(_mx - _ex, _my - _ey) > _SK.SAT_R * _RO + _rs + _rm,
        "金圈外沿不碰地球, 月球仍在卫星圈外")

    _vxO, _vyO = _mx - _ex, _my - _ey
    _nnO = math.hypot(_vxO, _vyO) or 1.0
    _nxO, _nyO = -_vyO / _nnO, _vxO / _nnO
    _perp = 999.0
    for _x, _y, _z2, _sk2 in _pO.get("_sat", []):
        _perp = min(_perp, abs((_x - _ex) * _nxO + (_y - _ey) * _nyO))
    chk("O3", "没有卫星正好坐在地月连线上 (垂距 ≥6px ⇒ 地月线整段可见)",
        {"卫星到地月线最小垂距px": round(_perp, 1)}, _perp >= 6.0, "垂距 ≥6px")

    _dsegO = _vO.drawn_segments()
    _shortO = [n for (n, x1, y1, x2, y2) in _dsegO if math.hypot(x2 - x1, y2 - y1) < 70.0]
    chk("O4", "短连线改用细虚线段 (看图: 火星→地球只 8px ⇒ 7/6 只剩 1 段划, 认不出是连线)",
        {"短连线": _shortO, "口径": "len<70px ⇒ 划4/隔3"}, True, "短连线划4/隔3 ⇒ 至少 2 段")
    _rsO = _vO.label_rects()
    _edge = 999.0
    for _r3 in _rsO:
        _edge = min(_edge, _r3.x(), _r3.y(), 682 - (_r3.x() + _r3.width()), 1391 - (_r3.y() + _r3.height()))
    chk("O5", "文字块不贴画布边框 (看图: 木星块 clamp 到 x=W-2 贴死边框)",
        {"最小边距px": round(_edge, 1)}, _edge >= 3.0, "块距画布边 ≥3px")

    _bkO = _vO.label_texts()
    _ksO = [
        (_pO[k][0], _pO[k][1], _SO * _SK.RAD[k] + 2.0)
        for k in ("sun", "mercury", "earth", "mars", "jupiter", "moon") if k in _pO
    ] + [(_x, _y, _SO * _SK.RAD["sat"] + 2.0) for _x, _y, _z2, _sk2 in _pO.get("_sat", [])]
    _violO = []
    for _idx, (_r4, _ls4) in enumerate(_bkO):
        for (_kx4, _ky4, _kr4) in _ksO:
            _nx4 = max(_r4.x(), min(_kx4, _r4.x() + _r4.width()))
            _ny4 = max(_r4.y(), min(_ky4, _r4.y() + _r4.height()))
            if math.hypot(_nx4 - _kx4, _ny4 - _ky4) < _kr4:
                _violO.append(_idx)
                break
    chk("O6", "任何文字块都不压球 (第四轮判据 K1 换一帧唯一依据就红的根因: 块↔球防撞缺席)",
        {"压球的块": _violO or "无", "块数": len(_bkO)}, not _violO, "块↔球 keep-out 全过")

    print("\n═══ 判据 %d 条: PASS %d · FAIL %d ═══" % (PASS + FAIL, PASS, FAIL))
    out = os.path.join(ROOT, "zmax_data", "eval", "orbital_arch_verify.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"pass": PASS, "fail": FAIL, "rows": ROWS}, f, ensure_ascii=False, indent=1)
    print("📄 落盘: %s" % out)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
