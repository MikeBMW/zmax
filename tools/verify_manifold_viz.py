#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据: 流形引擎可视化 (老倪 2026-10-16「可视化球面 + 轨迹显示方式 → 画布右侧主参数 M 侧边栏」)。

口径 (老倪原话): 「能看到投影后的球…球面上有运动的状态点, 状态点处有度量椭球, 球面上有大圆测地线。
将这个可视化球面, 轨迹显示方式, 做到画布右侧的主参数M的侧面栏窗口」+「四个面板共享同一时间轴, 同步更新」。

判据分五组 (全部只读, 离屏):
  A 几何真源 (sphere.py 立体投影: 极点/往返/批量/不返回 inf)
  B 数据真源 (engine_latest · ss_traj_last · zmax_manifold · su2 引擎同源映射; 只读不改)
  C 几何量正确性 (单位范数 / 测地距离交叉核对 / 大圆端点与弧长 / 切空间性)
  D 控件契约 (四面板 · 共享时间轴 · 播放暂停 · 空态诚实 · 帧龄标注)
  E 接线与取证 (画布右侧 M 页真接线 · 四面板真出图 · 单真源无重复公式)
用法: QT_QPA_PLATFORM=offscreen python3 tools/verify_manifold_viz.py
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "tools", "gui")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np                                     # noqa: E402
from PyQt5.QtWidgets import QApplication               # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "src"))
from lerobot.manifold import sphere as SP              # noqa: E402

R = []
def chk(cid, claim, got, ok, expect="", note=""):
    R.append({"id": cid, "claim": claim, "got": got, "ok": bool(ok), "expect": expect, "note": note})
    print("%s %-4s %s\n        got=%s  expect=%s %s" % ("✅" if ok else "❌", cid, claim,
          got, expect, ("— " + note) if note else ""))


def sha(p):
    try:
        with open(p, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:16]
    except Exception:
        return "-"


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    import manifold_viz as MV

    # ─────────── A 几何真源: 立体投影 ───────────
    south = np.array([0.0, 0.0, 0.0, -1.0])
    x, m = SP.stereographic_project(south)
    chk("A1", "S³ 南极点 → R³ 原点 (老倪: 南极点投到原点)", list(np.round(x, 12)), bool(np.allclose(x, 0)),
        "[0,0,0]")
    north = np.array([0.0, 0.0, 0.0, 1.0])
    xn, mn = SP.stereographic_project(north)
    chk("A2", "北极点 → 截断到有限值并标记 clipped (不返回 inf)",
        {"x": [round(float(v), 3) for v in xn], "clipped": mn["clipped"]},
        bool(mn["clipped"] and np.all(np.isfinite(xn))), "clipped=True, 有限值")
    rng = np.random.default_rng(7)
    v = rng.normal(size=4)
    p0 = v / np.linalg.norm(v)
    proj, _ = SP.stereographic_project(p0)
    back = SP.stereographic_inverse(proj)
    chk("A3", "投影↔逆投影 往返逐位一致 (‖p−inverse(project(p))‖ < 1e-12)",
        "%.3e" % float(np.linalg.norm(p0 - back)), float(np.linalg.norm(p0 - back)) < 1e-12, "<1e-12")
    bats = rng.normal(size=(9, 4))
    bats = bats / np.linalg.norm(bats, axis=1, keepdims=True)
    Xb, mb = SP.stereographic_project(bats)
    Xs = np.asarray([SP.stereographic_project(b)[0] for b in bats])
    chk("A4", "批量投影 == 逐点投影 (轨迹整条投影用批量路径, 不能各写一套)",
        "max|Δ|=%.3e" % float(np.max(np.abs(Xb - Xs))), float(np.max(np.abs(Xb - Xs))) < 1e-12, "0")
    chk("A5", "逆投影结果恒在单位球上 (‖p‖=1)",
        "max|‖p‖−1|=%.3e" % float(np.max(np.abs(np.linalg.norm(
            np.asarray([SP.stereographic_inverse(z) for z in Xb]), axis=1) - 1.0))),
        float(np.max(np.abs(np.linalg.norm(np.asarray([SP.stereographic_inverse(z) for z in Xb]), axis=1) - 1.0))) < 1e-12,
        "<1e-12")
    xp, _ = SP.stereographic_project(p0, pole="north")
    xpn, _ = SP.stereographic_project(np.array([p0[0], p0[1], p0[2], -p0[3]]), pole="south")
    chk("A6", "pole='north' 与 'south' 是镜像语义 (换哪一极投到原点)",
        "%.3e" % float(np.max(np.abs(xp - xpn))), float(np.max(np.abs(xp - xpn))) < 1e-12, "<1e-12")

    # ─────────── B 数据真源 (只读) ───────────
    files = [os.path.join(ROOT, "zmax_data", "ss_live", "engine_latest.json"),
             os.path.join(ROOT, "data", "database", "zmax", "sources", "canvas", "ss_traj_last.json"),
             os.path.join(ROOT, "config", "calib", "zmax_manifold.json")]
    before = {f: sha(f) for f in files}

    d = MV.ManifoldData(ROOT)
    s = d.summary()
    chk("B1", "实时状态真源 engine_latest.json 的 p 是单位四元数 (‖p‖=1)",
        "‖p‖=%.9f" % float(np.linalg.norm(d.live_p)) if d.live_p is not None else "无",
        d.live_p is not None and abs(float(np.linalg.norm(d.live_p)) - 1.0) < 1e-6, "1.0")
    chk("B2", "轨迹真源 ss_traj_last.json 帧数 > 0 且时间单调",
        {"n": d.n, "t0": round(float(d.t[0]), 3), "t1": round(float(d.t[-1]), 3)},
        d.n > 0 and bool(np.all(np.diff(d.t) >= 0)), "n>0, t 单调不减")
    chk("B3", "状态映射与引擎同源 (su2.encode_obs43, L2 执行层 obs43→SU(2))",
        s.get("state_src", ""), "encode_obs43" in (s.get("state_src") or ""), "su2.encode_obs43 ...")
    M_true = json.load(open(files[2], encoding="utf-8")).get("M")
    chk("B4", "主参数 M 取**标定真源**(不是画布节点默认值)",
        {"M": d.M, "src": d.M_src, "节点 M": d.M_node}, abs(float(d.M) - float(M_true)) < 1e-12,
        "= config/calib/zmax_manifold.json::M", "画布节点 M=%s (快照, 不作准)" % d.M_node)
    chk("B5", "度量 (dim/mode/diag) 取自标定真源",
        d.metric, int(d.metric.get("dim") or 0) == 6 and d.metric.get("mode") == "diag"
        and len(d.metric.get("diag") or []) == 6, "dim=6, mode=diag, 6 个对角分量")
    # B7 恶劣环境回归: sys.path 前面塞一个「有 lerobot.manifold 但没 sphere.py」的假包 (复现控制台 fork 遮蔽),
    #    可视化必须仍加载**工程真源**算子 (按路径加载), 不许退化成空态。
    import importlib
    with tempfile.TemporaryDirectory() as _td:
        _fake = os.path.join(_td, "lerobot", "manifold")
        os.makedirs(_fake)
        open(os.path.join(_td, "lerobot", "__init__.py"), "w").close()
        open(os.path.join(_fake, "__init__.py"), "w").close()
        _saved = [m for m in list(sys.modules) if m == "lerobot" or m.startswith("lerobot.")]
        _mods = {m: sys.modules.pop(m) for m in _saved}
        sys.path.insert(0, _td)
        try:
            _m2 = importlib.reload(MV)
            _ok7 = (_m2.SP is not None) and hasattr(_m2.SP, "stereographic_project")
            _got7 = {"SP": None if _m2.SP is None else os.path.basename(getattr(_m2.SP, "__file__", "?")),
                     "有立体投影": bool(_m2.SP is not None and hasattr(_m2.SP, "stereographic_project")),
                     "SU2": None if _m2.SU2 is None else bool(hasattr(_m2.SU2, "encode_obs43")),
                     "err": (_m2._SP_ERR or "")[:60]}
        finally:
            sys.path.remove(_td)
            sys.modules.update(_mods)
            importlib.reload(MV)
        chk("B7", "恶劣 sys.path (fork 的 lerobot 在前, 无 sphere.py) 仍加载工程真源算子 —— 按路径加载, 不退回空态",
            _got7, _ok7, "SP=src/lerobot/manifold/sphere.py · 有 stereographic_project · SU2 有 encode_obs43")

    # E5 命令通道直达 (2026-10-16 老倪「找不到」定式): 控制台里 `echo mparam > /tmp/zmax_nav_cmd`
    #    就能跳到画布页 + 侧栏切到「主参数 M」;  `mparam_shot` 从控制台**进程内部**抓该页真窗口
    #    (X11 全屏抓图在被遮挡时会抓到压在上面的窗口 —— 这个坑本轮真踩到过)
    with open(os.path.join(ROOT, "tools", "gui", "studio.py"), encoding="utf-8") as _fst:
        _st = _fst.read()
    _nav = {}
    for k, pat in (("分支 mparam", 'elif line == "mparam":'),
                   ("分支 mparam_shot", 'elif line == "mparam_shot":'),
                   ("执行体 _goto_mparam_cmd", "def _goto_mparam_cmd(self):"),
                   ("执行体 _mparam_shot_cmd", "def _mparam_shot_cmd(self):"),
                   ("切页真调 cmb_view", 'dock.cmb_view.setCurrentIndex(idx)'),
                   ("抓图真调 grab()", "pm = page.grab()")):
        _nav[k] = pat in _st
    chk("E5", "命令通道 mparam/mparam_shot 真接线 (跳画布页 + 切主参数 M 页 + 进程内抓该页真窗口)",
        _nav, all(_nav.values()), "六处都在: 两个分支 + 两个执行体 + setCurrentIndex + page.grab()")
    # E6 在役控制台内抓图 (存在则核四象限都真有内容; 不存在不假装通过)
    _shot = os.path.join(ROOT, "reports", "ui_shots", "live_mparam_sidebar.png")
    if os.path.isfile(_shot):
        from PIL import Image
        _im = Image.open(_shot).convert("RGB")
        _a = __import__("numpy").asarray(_im).astype(int)
        _H, _W = _a.shape[0], _a.shape[1]
        _q = {}
        for _name, (_y0, _y1, _x0, _x1) in (("左上", (0, _H // 2, 0, _W // 2)), ("右上", (0, _H // 2, _W // 2, _W)),
                                            ("左下", (_H // 2, _H, 0, _W // 2)), ("右下", (_H // 2, _H, _W // 2, _W))):
            _b = _a[_y0:_y1, _x0:_x1]
            _q[_name] = int((__import__("numpy").abs(_b - __import__("numpy").array([13, 17, 23])).sum(axis=2) > 40).sum())
        chk("E6", "在役控制台内抓图 (live_mparam_sidebar.png) 四象限都真有内容 —— 不是空页/空态",
            {"尺寸": [_W, _H], "四象限非背景像素": _q}, min(_q.values()) > 1200, "四象限各自 > 1200 非背景像素")
    else:
        chk("E6", "在役控制台内抓图 (存在才核; 缺图不假装通过)", {"有图": False}, None,
            "跑 echo mparam_shot > /tmp/zmax_nav_cmd 后重现此判据")

    after = {f: sha(f) for f in files}
    # 静态: 可视化源码里没有任何写操作的语句 (真源只读 = 代码里就不能有写口)
    vizsrc = open(os.path.join(ROOT, "tools", "gui", "manifold_viz.py"), encoding="utf-8").read()
    wr = [t for t in ('"w"', "'w'", "np.save", "json.dump(", "os.replace", "shutil") if t in vizsrc]
    # 运行时: 静态真源 (轨迹/标定) 前后 sha 逐位不变; 实时文件由 10Hz 引擎在写 (帧龄即证据)
    stat = [f for f in files if "engine_latest" not in os.path.basename(f)]
    chk("B6", "真源只读: 源码无写口 + 静态真源 sha 逐位不变 (实时文件由 10Hz 引擎写, 非本工具)",
        {"源码写操作": wr,
         "静态真源 sha": {os.path.basename(f): (before[f] == after[f]) for f in stat},
         "engine_latest 外部更新": before[files[0]] != after[files[0]],
         "帧龄(s)": round(float(d.live_age), 2) if d.live_age is not None else None},
        (not wr) and all(before[f] == after[f] for f in stat), "无写口 + 轨迹/标定不变",
        "engine_latest.json 每 100ms 被引擎刷新 ⇒ 前后必然不同, 属外部写入")

    # ─────────── C 几何量正确性 ───────────
    nrm = np.linalg.norm(d.Q, axis=1)
    chk("C1", "S³ 上每个轨迹状态都是单位四元数",
        "max|‖q‖−1|=%.3e" % float(np.max(np.abs(nrm - 1.0))), float(np.max(np.abs(nrm - 1.0))) < 1e-9, "<1e-9")
    i = max(1, d.n // 3)
    dd = float(SP.distance(d.Q[i], d.Q[-1]))
    alt = float(np.arccos(max(-1.0, min(1.0, float(np.dot(d.Q[i], d.Q[-1]))))))
    chk("C2", "面板测地距离 == sphere.distance == 内积反余弦 (三口径一致)",
        {"sphere.distance": round(dd, 12), "arccos⟨p,q⟩": round(alt, 12), "面板 dist[i]": round(float(d.dist[i]), 12)},
        abs(dd - alt) < 1e-12 and abs(dd - float(d.dist[i])) < 1e-12, "三处一致", "容差 1e-12")
    chk("C3", "大圆路径端点 == 轨迹起点/终点",
        {"首": bool(np.allclose(d.geo[0], d.Q[0], atol=1e-12)),
         "末": bool(np.allclose(d.geo[-1], d.Q[-1], atol=1e-12))},
        bool(np.allclose(d.geo[0], d.Q[0], atol=1e-12) and np.allclose(d.geo[-1], d.Q[-1], atol=1e-12)),
        "逐位一致")
    chk("C4", "大圆弧长 == 起点终点测地距离 (弧长是逐段求和, 不是弦长)",
        {"弧长": round(d.geo_len, 12), "θ=dist": round(d.geo_theta, 12)},
        abs(d.geo_len - d.geo_theta) < 1e-9 and abs(d.geo_theta - float(SP.distance(d.Q[0], d.Q[-1]))) < 1e-12,
        "弧长==θ==distance", "warn: 面板几何用自己的实现就露馅了")
    tang = [float(np.dot(d.v[k], d.Q[k])) for k in range(0, d.n, 40)]
    chk("C5", "速度向量真在切空间 (⟨v,p⟩=0)",
        "max|⟨v,p⟩|=%.3e" % float(np.max(np.abs(tang))), float(np.max(np.abs(tang))) < 1e-9, "<1e-9")
    chk("C6", "力 = M·a 用标定 M (真源 3.643), 不是 1.0",
        {"M": d.M, "‖F‖max": round(float(np.max(d.force)), 6)},
        abs(float(d.M) - 3.643) < 1e-9, "M=3.643")

    # ─────────── D 控件契约 ───────────
    viz = MV.ManifoldViz(ROOT)
    viz.resize(1180, 760)
    viz.show()
    app.processEvents()
    panels = {"左上 S³球": viz.p_ball, "右上 切空间": viz.p_tan, "左下 度量场": viz.p_met, "右下 时间序列": viz.p_ser}
    chk("D1", "四面板齐 (S³ 立体投影球 / 切空间 / 度量场 / 时间序列)",
        list(panels), len(panels) == 4 and all(isinstance(w, MV.QWidget) for w in panels.values()), "4 个面板")
    k = max(0, d.n // 2)
    viz.set_frame(k)
    app.processEvents()
    idx = {nm: int(w.i) for nm, w in panels.items()}
    chk("D2", "共享同一时间轴: 一次 set_frame(k) 四个面板同步到同一帧",
        idx, all(v == k for v in idx.values()), "四面板 i 都 == %d" % k, "老倪: 四个面板共享同一时间轴, 同步更新")
    chk("D3", "时间游标量程 = 真实帧数 (0..n−1)",
        {"range": [viz.sld.minimum(), viz.sld.maximum()], "n": d.n},
        viz.sld.maximum() == max(0, d.n - 1), "max == n−1")
    viz.resize(420, 900)                        # 窄栏 (侧栏拖窄 / 窄屏) ⇒ 应自动转单列, 不压扁
    app.processEvents()
    _narrow = {"cols": getattr(viz, "_cols", None), "min_h": viz.minimumHeight()}
    viz.resize(1180, 760)
    app.processEvents()
    chk("D7", "侧栏变窄 ⇒ 四面板自动转单列 (老倪: 不许挤/不许截断)",
        {"窄 420px": _narrow, "恢复宽 1180px": {"cols": getattr(viz, "_cols", None), "min_h": viz.minimumHeight()}},
        _narrow["cols"] == 1 and getattr(viz, "_cols", None) == 2, "420px→1 列, 1180px→2 列")
    viz.toggle_play()
    started = viz._timer.isActive()
    viz.toggle_play()
    stopped = not viz._timer.isActive()
    chk("D4", "播放/暂停 真控制定时器 (▶/⏸ 不是装饰)", {"start": started, "stop": stopped},
        bool(started and stopped), "起 → 停")
    txt = viz.lbl_src.text()
    tip = viz.lbl_src.toolTip()
    chk("D5", "底栏如实标注 数据源 + 帧龄 (可见行短; 完整路径在悬浮提示, 界面极简不丢信息)",
        {"可见": txt[:110], "提示长度": len(tip)},
        ("帧龄" in txt) and ("engine_latest" in txt) and ("ss_traj_last" in txt)
        and ("engine_latest.json" in tip) and ("ss_traj_last.json" in tip) and ("zmax_manifold.json" in tip),
        "可见含 帧龄/源名; 提示含完整路径")
    # 空态: 临时 root (无真源) ⇒ 不崩 + 面板不画假点
    with tempfile.TemporaryDirectory() as td:
        d0 = MV.ManifoldData(td)
        viz0 = MV.ManifoldViz(td)
        viz0.resize(600, 460)
        viz0.show()
        app.processEvents()
        ok_paint = True
        try:
            for w in (viz0.p_ball, viz0.p_tan, viz0.p_met, viz0.p_ser):
                w.grab()
        except Exception as e:
            ok_paint = str(e)
        chk("D6", "真源缺失 ⇒ 空态 (n=0 且如实报错, 面板不崩、不画假点)",
            {"n": d0.n, "err": d0.err[:2], "paint": ok_paint},
            d0.n == 0 and bool(d0.err) and ok_paint is True, "n=0, err 非空, 出图不抛异常")

    # ─────────── E 接线与取证 ───────────
    shots = os.path.join(ROOT, "reports", "ui_shots")
    os.makedirs(shots, exist_ok=True)
    viz.set_frame(max(0, d.n - 1))
    app.processEvents()
    from PIL import Image
    stats = {}
    for nm, w in (("ball", viz.p_ball), ("tangent", viz.p_tan), ("metric", viz.p_met), ("series", viz.p_ser)):
        fp = os.path.join(shots, "manifold_panel_%s.png" % nm)
        w.grab().save(fp)
        a = np.asarray(Image.open(fp).convert("RGB")).astype(int).reshape(-1, 3)
        nb = int(np.sum(np.abs(a - np.array([13, 17, 23])).sum(axis=1) > 30))
        stats[nm] = {"px": nb, "bytes": os.path.getsize(fp)}
    big = os.path.join(shots, "manifold_viz_offscreen.png")
    viz.grab().save(big)
    chk("E1", "四面板真出图 (非背景像素 > 2000, 文件落 reports/ui_shots/)",
        stats, all(v["px"] > 2000 for v in stats.values()), "每面板 >2000 像素")
    a = np.asarray(Image.open(os.path.join(shots, "manifold_panel_ball.png")).convert("RGB")).astype(int).reshape(-1, 3)
    def cnt(rgb, tol=60):
        return int(np.sum(np.abs(a - np.array(rgb)).sum(axis=1) < tol))
    colors = {"青(状态点/目标)": cnt([0x39, 0xc5, 0xcf]), "白(当前状态)": cnt([255, 255, 255]),
              "橙(时间终点色)": cnt([0xd2, 0x99, 0x22]), "蓝系(时间起点色)": int(np.sum((a[:, 2] > 180) * (a[:, 0] < 120)))}
    chk("E2", "球面板真画出 状态点 + 时间着色轨迹 (起点蓝→终点橙)",
        colors, colors["白(当前状态)"] > 20 and colors["蓝系(时间起点色)"] > 20 and colors["橙(时间终点色)"] > 20,
        "三色系都在")
    src = open(os.path.join(ROOT, "tools", "gui", "model_tree.py"), encoding="utf-8").read()
    chk("E3", "画布右侧「主参数 M」页真接线 (ManifoldViz 实例化 + addWidget)",
        {"import": "manifold_viz import ManifoldViz" in src or "from manifold_viz import ManifoldViz" in src,
         "add": "lay.addWidget(self.viz" in src,
         "refresh": "_refresh_viz" in src},
        ("ManifoldViz" in src) and ("lay.addWidget(self.viz" in src) and ("_refresh_viz" in src),
        "三处都在")
    vizpy = open(os.path.join(ROOT, "tools", "gui", "manifold_viz.py"), encoding="utf-8").read()
    tree = ast.parse(vizpy)
    defs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    dup = [f for f in defs if f in ("normalize", "exp_map", "log_map", "geodesic_slerp", "great_circle_path",
                                   "parallel_transport", "distance", "stereographic_project", "stereographic_inverse")]
    need_ops = ("stereographic_project", "stereographic_inverse", "log_map", "distance",
                "great_circle_path", "parallel_transport", "tangent_project")
    used_ops = [o for o in need_ops if ("SP.%s" % o) in vizpy]
    chk("E4", "几何公式单真源: 可视化里**没有**重写球面算子, 关键算子全调 sphere.py",
        {"重复定义": dup, "调用的真源算子": used_ops},
        (not dup) and len(used_ops) == len(need_ops), "无重复定义 + 7 个算子全走 SP.*")

    ok = sum(1 for r in R if r["ok"])
    print("\n═══ 判据 %d 条: PASS %d · FAIL %d ═══" % (len(R), ok, len(R) - ok))
    outp = os.path.join(ROOT, "zmax_data", "eval", "manifold_viz_verify.json")
    os.makedirs(os.path.dirname(outp), exist_ok=True)
    with open(outp, "w", encoding="utf-8") as f:
        json.dump({"judge": "manifold_viz", "n": len(R), "pass": ok, "fail": len(R) - ok,
                   "at": __import__("time").strftime("%F %T"), "items": R,
                   "data": s, "shots": stats}, f, ensure_ascii=False, indent=1)
    print("📄 落盘: %s" % outp)
    return 0 if ok == len(R) else 1


if __name__ == "__main__":
    sys.exit(main())
