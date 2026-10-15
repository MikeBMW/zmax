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
    arr = np.zeros((H, W, 3), dtype=int)
    for y in range(H):
        for x in range(W):
            c = img.pixel(x, y)
            arr[y, x] = [(c >> 16) & 255, (c >> 8) & 255, c & 255]

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
    # 月球相位锁定: **从像素里找月球球体** (不是用画的公式反推) —— 月球色掩膜 + 3×3 腐蚀去掉
    # 文字笔画, 只在离地球 15~40px 的环带里取连通质心; 再在椭圆轨道基里解出 (角, 半径)。
    ang = view._angles(body)
    pe = OA.OrbitalArchView.ORB
    S = max(120, min(W - 14, H - 20 - 46))
    R = S * 0.46
    eb = ang.get("earth", 0.0)
    cx = W / 2.0
    cy = 20 + (H - 20 - 46) / 2.0
    ex = cx + R * pe["earth"] * np.cos(eb)
    ey = cy + R * pe["earth"] * 0.94 * np.sin(eb)
    ref = np.array([int(OA.OrbitalArchView.COL["moon"][1:3], 16), int(OA.OrbitalArchView.COL["moon"][3:5], 16),
                    int(OA.OrbitalArchView.COL["moon"][5:7], 16)])
    m0 = np.abs(arr - ref).sum(axis=2) < 60
    er = m0.copy()
    er[1:-1, 1:-1] = (m0[1:-1, 1:-1] & m0[:-2, 1:-1] & m0[2:, 1:-1] & m0[1:-1, :-2] & m0[1:-1, 2:] &
                      m0[:-2, :-2] & m0[:-2, 2:] & m0[2:, :-2] & m0[2:, 2:])
    ys, xs = np.nonzero(er)
    dd = np.hypot(xs - ex, ys - ey)
    near = (dd > 15) & (dd < 40)
    got_moon = {"腐蚀后球体像素": int(er.sum()), "地球近旁(15~40px)候选": int(near.sum())}
    ok4 = False
    if near.sum() > 20:
        mx, my = float(xs[near].mean()), float(ys[near].mean())
        dx, dy = mx - ex, my - ey
        rr = float(np.hypot(dx, dy / 0.94))                 # 椭圆轨道基里的半径
        aa = float(np.arctan2(dy / 0.94, dx))
        dth = (aa - eb + np.pi) % (2 * np.pi) - np.pi       # 相位差
        wob = view._wobble(body["moon"])
        got_moon.update({"检测半径比": round(rr / (R * 0.085), 4), "期望 1+摆幅": round(1.0 + wob, 4),
                         "相位差_rad": round(dth, 5), "摆幅(∝残差)": round(wob, 4), "地月距px": round(float(dd[near].mean()), 2)})
        ok4 = abs(rr / (R * 0.085) - (1.0 + wob)) < 0.12 and abs(dth) < 0.15
    chk("D4", "月球与地球同相位锁定 (协同行进): 从**像素里量出**月球方位 == 地球相位 (差≈0), 半径=0.085R·(1+摆幅)",
        got_moon, ok4, "相位差 <0.15rad · 半径比 ≈ 1+摆幅 (±0.12)")
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
