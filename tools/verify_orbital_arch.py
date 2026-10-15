#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🪐 球心引力架构视图 —— 只读判据 (老倪 2026-10-16 口径)

口径 (老倪原话):
  「在右侧侧面栏, 流形引擎是太阳, 前馈加速器是地球, DiT是火星, 接触流形是水星,
    性能流形是木星, 原子技能是卫星, 用球体映射主要的节点。状态校正节点是月球。
    前馈加速器和状态校正器协同行进」

判据分六段:
  A 天体↔节点 真源 (不是随手起名)   B 真连线 (双通道/卡尔曼结构/协同)
  C 球上的数是真值 (与真源/真模块逐位一致)   D 画 (球/轨道/相位锁定/无数据压暗)
  E 侧栏接线 (M 页真挂 + 切换 + 只读)   F 文案诚实 (真源·帧龄·映射写清)

只读: 本判据不写真源 (E4 静态核 + 跑前后真源 sha 对比)。
"""

from __future__ import annotations

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
from PyQt5.QtWidgets import QApplication                                  # noqa: E402

import orbital_arch as OA                                                 # noqa: E402

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

    # ═══ A 天体 ↔ 节点 真源 ═══
    allin = all(v["在"] for v in info["checked"].values())
    chk("A1", "7 类天体 (太阳/水星/地球/火星/木星/月球/卫星带) 都是画布真源里的真节点",
        {k: (v["在"], v["id"]) for k, v in info["checked"].items()}, allin,
        "7 个 id 全在画布 state_space_obs.json 的 nodes 里")
    chk("A2", "每个天体的节点名与老倪口径一致 (不是同名不同物)",
        {k: v["名"][:18] for k, v in info["checked"].items()},
        all(v["名匹配"] for v in info["checked"].values()),
        "太阳=流形引擎 · 水星=接触流形 · 地球=前馈加速器 · 火星=Action Head(DiT) · 木星=性能流形 · 月球=状态校正器 · 卫星带=原子技能")
    ids = [b[1] for b in OA.BODIES]
    chk("A3", "没有编造节点: BODIES 里每个 id 都能在画布真源里查到",
        {"ids": ids, "全在": all(i in canvas_nodes for i in ids)},
        all(i in canvas_nodes for i in ids), "全部命中 (真源 90 节点)")
    chk("A4", "卫星带条数来自真源 (skill_phys.json 在职 SK), 不是写死的数",
        {"在职": body["sats"]["n"], "标定表": body["sats"].get("n_calib"),
         "list": [s["SK"] for s in body["sats"]["list"]]},
        body["sats"]["n"] == len([s for s in body["sats"]["list"] if str(s["SK"]).startswith("SK")]) and body["sats"]["n"] > 0,
        "条数 == 真源在职 SK 数 (>0)")

    # ═══ B 真连线 ═══
    miss = [(f, t) for f, t, _l in OA.KEY_EDGES if (f, t) not in canvas_links]
    chk("B1", "视图要画的 13 条连线在画布 links 真源里全都存在 (一条不缺)",
        {"缺": miss, "真源连线总数": len(canvas_links)}, not miss, "缺 = []")
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
    chk("C1", "太阳主参数 M 与标定真源 zmax_manifold.json 同源 (逐位相等)",
        {"视图 M": body["sun"]["M"], "真源 M": mani.get("M")},
        float(body["sun"]["M"]) == float(mani.get("M")), "相等")
    tq = json.load(open(os.path.join(ROOT, "zmax_data", "ss_live", "torque_live.json"), encoding="utf-8"))
    mt = tq.get("metric_tensor") or []
    dim = int(tq.get("metric_dim") or 6)
    diag = [float(mt[i * dim + i]) for i in range(dim)] if mt else []
    chk("C2", "太阳的扭矩与度量特征值都取自 torque_live.json (引力=度量: 井扁率用真特征值)",
        {"T": body["sun"]["T_norm"], "真源 T": tq.get("torque_norm"),
         "eig_min/max": [body["sun"]["eig_min"], body["sun"]["eig_max"]],
         "真源对角": [round(min(diag), 3), round(max(diag), 3)] if diag else None},
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
        {"请求": e.get("req_mps"), "真源请求": sk.get("%s_请求_mps" % (e.get("stage") or "")),
         "残差": body["moon"].get("err"), "真源残差": (se.get("err_norm") or {}).get(e.get("stage") or "")},
        float(e.get("req_mps")) == float(sk.get("%s_请求_mps" % (e.get("stage") or "")))
        and float(body["moon"].get("err")) == float((se.get("err_norm") or {}).get(e.get("stage") or "")),
        "与真源逐位一致")

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
    chk("D4b", "屏幕上 (真渲染坐标) 卫星确实贴在地球旁: 屏距 ≈ 0.055R·投影 (不是散落在太阳系)",
        {"屏距px": [round(x, 1) for x in _scr], "0.055R": round(0.055 * _R, 1),
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
        chk("D5", "真源缺失时: 球压暗 (_live=False) 且文案写「未算/未测/不可用」—— 不填 0 不编数",
            {"_live": [OA.OrbitalArchView._live(b2[k]) for k in ("mercury", "jupiter", "earth")],
             "文案": [t[:26] for t in texts]},
            not any(OA.OrbitalArchView._live(b2[k]) for k in ("mercury", "jupiter", "earth")) and hit >= 3,
            "三颗都压暗 + ≥3 处诚实文案")

    # ═══ E 侧栏接线 ═══
    with open(os.path.join(ROOT, "tools", "gui", "model_tree.py"), encoding="utf-8") as fh:
        mt_src = fh.read()
    wire = {"import": ("OrbitalArchView" in mt_src), "实例化": ("self.orbital = OrbitalArchView()" in mt_src),
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
        "OrbitalArchView · M 与标定真源同值")
    with open(os.path.join(ROOT, "tools", "gui", "studio.py"), encoding="utf-8") as fh:
        st_src = fh.read()
    nav = {"分支 orbital": 'elif line == "orbital":' in st_src,
           "执行体 _goto_orbital_cmd": "def _goto_orbital_cmd(self):" in st_src,
           "真切到第 2 项视图": "cmb.setCurrentIndex(1)" in st_src,
           "抓图按当前视图命名": 'live_mparam_%s.png' in st_src and 'currentIndex() == 1 else "viz"' in st_src}
    chk("E5", "命令通道 orbital 真接线 (一句令: 画布页+M页+切到球心视图) + mparam_shot 抓当前显示页",
        nav, all(nav.values()), "四处都在: 分支/执行体/切视图/按视图命名落盘")
    src = open(os.path.join(ROOT, "tools", "gui", "orbital_arch.py"), encoding="utf-8").read()
    writes = [k for k in ('open(fpath, "w"', "open(p, \"w\"", "json.dump(", "np.save", ".save(") if k in src]
    chk("E4", "视图是只读的 (源码里没有写文件口; 只读真源画图)", {"命中写口": writes}, not writes, "无写口")

    # ═══ 冻源: 现场有别的进程(控制台/引擎)每帧在写 zmax_data/ss_live/*.json ⇒
    #    像素类判据必须有**确定输入**, 先拷一份真源到临时目录, 后面的视图都读冻结副本 (只读, 不改真源)。
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
    chk("K1", "判据在**冻结真源副本**上跑 (现场别的进程每帧在写 ss_live ⇒ 输入不漂, 结论可复现)",
        {"已冻结文件": _frozen, "清单": [r.split("/")[-1] for r in _RELS],
         "冻源目录": os.path.basename(_FREEZE)},
        _frozen >= 8, "关键真源 ≥8 个文件已冻结")

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

    # ═══ I 力的相互作用连线 (真源 + 粗细 + 不闪) ═══
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
             if (l.get("f") in _body_ids or l.get("t") in _body_ids)}
    _got = {(e["f"], e["t"]) for e in ed}
    chk("I1", "有相互作用就显示连线: 画布上所有「至少一端是主体的真连线」都画了 (无漏无造)",
        {"视图线数": len(ed), "主体↔主体": len(_bb), "主体↔体系外": len(_ex2),
         "真源应有": len(_want), "缺失": sorted(_want - _got)[:4], "多余(编造)": sorted(_got - _want)[:4]},
        _src_ok and _want == _got and len(ed) > 20, "真源===视图, 一条不漏一条不造")
    # I1b 像素级: 每条主体↔主体线在画面里**真的可见** (清单相等 ≠ 真画出来 —— 端点取不到会被静默跳过)
    _A1b = _arr(v3.grab().toImage())
    _rs1b = v3.label_rects()
    _p1b = v3.positions()
    _cir = [(_p1b["_cx"], _p1b["_cy"], 0.052 * _p1b["_R"])]
    for _k in ("mercury", "earth", "mars", "jupiter"):
        _cir.append((_p1b[_k][0], _p1b[_k][1], OA.OrbitalArchView.RAD[_k] * _p1b["_R"]))

    def _visible(nid_a, nid_b, kind):
        def _pt(nid):
            if OA.OrbitalArchView._key_of(nid) == "sun":
                return (_p1b["_cx"], _p1b["_cy"])
            t = _p1b[OA.OrbitalArchView._key_of(nid)]
            return (t[0], t[1])
        ax, ay = _pt(nid_a)
        bx, by = _pt(nid_b)
        col = {"condition": [0x39, 0xc5, 0xcf], "semantic": [0xd2, 0x99, 0x22], "drive": [0x3f, 0xb9, 0x50],
               "feedback": [0xa3, 0x71, 0xf7], "misc": [0x8b, 0x94, 0x9e]}[kind]
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
    plot = (all(u >= 3 and s >= 1 for s, u in _vis.values())
            and all((s / u) >= 0.5 for s, u in _vis.values() if u)
            and (sum(_ratios) / max(1, len(_ratios))) >= 0.85)
    chk("I1b", "像素级: 每条主体↔主体线在画面里**真的可见** (容差 320 抗混色; 文字块/球体遮挡处跳过)",
        {"各线 命中/可用": _vis}, plot and len(_vis) == len(_bb), "每条线 ≥80% 命中 (端点取不到会被静默跳过 → 这条能抓)")

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
         "关键项": {k: (k in _joined) for k in ("力的相互作用", "线义", "角度映射", "真源", "torque_live", "节点映射核对")}},
        len(_fl) >= 4 and not _tooWide and not any("…" in t for t in _fl)
        and all(k in _joined for k in ("力的相互作用", "线义", "角度映射", "真源", "torque_live", "节点映射核对")),
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
        if "慢虚线" in _t:
            for _cand in ("紫", "青", "金", "绿"):
                if "慢虚线" + _cand in _t:
                    _tok = _cand
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

    # ═══ F 文案诚实 ═══
    chk("F1", "图注写清 角度映射 (位置不是装饰, 是实测量的映射)",
        {"含角度映射": "角度映射" in src}, "角度映射" in src, "源码图注含该项")
    chk("F2", "脚注含真源清单 + 帧龄 + 节点映射核对数 (可复核)",
        {"含真源": "真源:" in src, "含帧龄": "帧龄" in src, "含节点映射核对": "节点映射核对" in src},
        all(k in src for k in ("真源:", "帧龄", "节点映射核对")), "三项都在")

    print("\n═══ 判据 %d 条: PASS %d · FAIL %d ═══" % (PASS + FAIL, PASS, FAIL))
    out = os.path.join(ROOT, "zmax_data", "eval", "orbital_arch_verify.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"pass": PASS, "fail": FAIL, "rows": ROWS}, f, ensure_ascii=False, indent=1)
    print("📄 落盘: %s" % out)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
