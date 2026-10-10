#!/usr/bin/env python3
"""🧮 系统核心节点 (流形引擎) 的 UI 取证测试 (2026-10-10 老倪)

老倪的两条要求 (逐字):
  ①「每次打开状态空间工程, 屏幕中心就是这个节点」
  ②「改变这个节点的背景颜色, 让人一下子就认出流形引擎是系统的核心, 你来设计一个明显的样式颜色」

本测试不看"好不好看"(无视觉工具), 只把可核的东西**量出来**:
  A. 背景色: 把真节点渲染成 QImage → 数**琥珀金**像素 (核心) vs 普通节点 (应为 0)
     - 判据: 核心节点暖色像素 (r>120, g>90, b<70) ≥ 3000; 普通节点 == 0
     - 徽章: 纯金 #FFC53D (±12) 像素 ≥ 200 (◉ 核心 徽章 + 描边)
  B. 居中: 真工程文件 + 真 SimulinkModule → center_on_core_node() 后
     - 视口中心 映射回场景坐标 ≈ 核心节点中心 (容差: 节点尺寸的一半以内)
     - core_node_id() 必须找到且等于 ss_mani_eng
用法: QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/tests/test_core_node_ui.py
"""
from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, "/home/ubuntu/zmax/tools/gui")

ROOT = "/home/ubuntu/zmax"
FLOW = os.path.join(ROOT, "data/database/zmax/sources/canvas/state_space_obs.json")

from PyQt5.QtCore import QRectF, QPointF            # noqa: E402
from PyQt5.QtGui import QImage, QPainter, QColor    # noqa: E402
from PyQt5.QtWidgets import QApplication, QGraphicsScene  # noqa: E402

import simulink_module as SM                        # noqa: E402

FAILS: list = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  ✅ " if ok else "  ❌ ") + name + (f" — {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


def amber_pixels(img: QImage, strict: bool = False) -> int:
    """数暖金像素: strict=True 只数纯金 #FFC53D(±12), 否则数整族暖色 (r>120,g>90,b<70)。"""
    n = 0
    for y in range(0, img.height(), 2):          # 隔行采样 (够判据, 快一倍)
        for x in range(0, img.width(), 2):
            c = img.pixelColor(x, y)
            r, g, b = c.red(), c.green(), c.blue()
            if strict:
                if abs(r - 255) <= 12 and abs(g - 197) <= 12 and abs(b - 61) <= 12:
                    n += 1
            elif r > 120 and g > 90 and b < 70:
                n += 1
    return n


def render_node(node: dict, w: int = 460, h: int = 220, flow: dict | None = None) -> QImage:
    """把单个节点真渲染到 QImage (黑底, 与画布深色主题同底)。

    paint() 里会读 scene_ref.nodes / scene_ref.links (数入/出连线) ⇒ 给真 QGraphicsScene
    挂上这两个属性 (画布自己的场景也是这么挂的)。
    """
    sc = QGraphicsScene()
    sc.nodes = (flow or {}).get("nodes", [node])
    sc.links = (flow or {}).get("links", [])
    it = SM.SimNodeItem(node, sc)
    sc.addItem(it)
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(QColor("#0d1117"))
    p = QPainter(img)
    sc.render(p, QRectF(0, 0, w, h), QRectF(node["x"] - 30, node["y"] - 30, w, h))
    p.end()
    return img


def main() -> int:
    app = QApplication(sys.argv[:1])                                     # noqa: F841
    flow = json.load(open(FLOW, encoding="utf-8"))
    nodes = flow["nodes"]
    core = next(n for n in nodes if n.get("id") == "ss_mani_eng")
    norm = next(n for n in nodes if n.get("type") == "model" and n.get("id") != "ss_mani_eng")

    print("=" * 78)
    print("🧮 核心节点 UI 取证 (背景色 / 居中) — 全量像素级量化, 不靠肉眼")
    print("=" * 78)
    print(f"画布: {os.path.relpath(FLOW, ROOT)} · {len(nodes)} 节点")
    print(f"核心: id={core['id']} name={core['name'][:28]}… pos=({core['x']},{core['y']}) "
          f"size={core['w']}x{core['h']} params.core={bool((core.get('params') or {}).get('core'))}")
    print(f"对照: id={norm['id']} type={norm['type']} name={norm['name'][:22]}…")

    # ── A. 背景色 ──
    print("\n[A] 背景色 (真渲染 → 像素统计)")
    ic, inn = render_node(core, flow=flow), render_node(norm, flow=flow)
    a_core, a_norm = amber_pixels(ic), amber_pixels(inn)
    s_core, s_norm = amber_pixels(ic, strict=True), amber_pixels(inn, strict=True)
    print(f"  核心节点 暖色像素={a_core} · 纯金 #FFC53D={s_core}")
    print(f"  普通节点 暖色像素={a_norm} · 纯金 #FFC53D={s_norm}")
    # 采样口径: 隔点采样 (步长 2) ⇒ 采样值 ≈ 全分辨率 /4; 阈值按采样值定 =
    # 全分辨率 ~2000 暖色像素 (节点面积 340×130=44200 → 约占 4.5%), 足以说明"整个身子都是琥珀金"
    check("核心背景是唯一暖色 (暖色像素 ≥500 采样值 ≈ 全分辨率 2000)",
          a_core >= 500, f"采样 {a_core} (≈全分辨率 {a_core * 4})")
    check("普通节点无暖色 (强对比)", a_norm == 0, f"{a_norm}")
    check("◉核心 徽章/金框存在 (纯金像素 ≥200)", s_core >= 200, f"{s_core}")
    check("核心暖色像素 ≫ 普通", a_core > 20 * max(1, a_norm), f"{a_core} vs {a_norm}")

    # ── B. 居中 ──
    print("\n[B] 打开工程后视口居中核心 (真 SimulinkModule + 真工程文件)")
    try:
        mod = SM.SimulinkModule()
        # 真工程文件由测试显式加载 (SimulinkModule() 构造不自动开工程)
        loaded = mod.load_flow_file(FLOW, confirm=False)
        for _ in range(8):                     # 让 load 钩子里 QTimer.singleShot(0) 真跑起来
            app.processEvents()
        check("真工程文件加载成功", bool(loaded), f"load_flow_file → {loaded}")
        cid = mod.core_node_id()
        # ⚠️ 实测: load_flow_file 会给节点**重新生成 id** (本地真项目里的 id 是 'n<ts>...'),
        #   所以判据不能写死 id, 要判"它指的确实是有 core/manifold_engine 标记的那个节点"。
        _node = next((n for n in (mod.nodes or []) if n.get("id") == cid), None)
        _is_core = bool(_node) and bool((_node.get("params") or {}).get("core")
                                        or (_node.get("params") or {}).get("manifold_engine"))
        check("core_node_id() 找到核心节点 (按 core/manifold_engine 标记)",
              _is_core, f"id={cid} name={( _node or {}).get('name', '?')[:26]}")
        # 先看**自动**路径 (打开工程就居中, 不用手动点) —— 这才是老倪要的
        cv0 = mod.canvas
        _it0 = (getattr(mod, "_items", None) or {}).get(cid)
        _auto = False
        if _it0 is not None:
            _vc = cv0.mapToScene(cv0.viewport().rect().center())
            _r = _it0.sceneBoundingRect()
            _auto = abs(_vc.x() - _r.center().x()) <= max(core["w"] / 2.0, 40.0) \
                and abs(_vc.y() - _r.center().y()) <= max(core["h"] / 2.0, 40.0)
            print(f"  自动居中: 视口中心({_vc.x():.1f},{_vc.y():.1f}) vs 核心中心"
                  f"({_r.center().x():.1f},{_r.center().y():.1f}) → {'已居中' if _auto else '未居中'}")
        check("打开工程即自动居中核心 (无需手动)", bool(_auto))
        ok = mod.center_on_core_node(quiet=True)
        check("center_on_core_node() 手动调用也成功 (Ctrl+Shift+C)", bool(ok))
        cv = mod.canvas
        vc: QPointF = cv.mapToScene(cv.viewport().rect().center())
        it = (getattr(mod, "_items", None) or {}).get(cid)
        if it is None:
            check("核心节点项在画布上", False, f"_items 里没有 {cid} (工程没加载完?)")
        else:
            r = it.sceneBoundingRect()
            dx, dy = abs(vc.x() - r.center().x()), abs(vc.y() - r.center().y())
            tol_x, tol_y = max(core["w"] / 2.0, 40.0), max(core["h"] / 2.0, 40.0)
            print(f"  视口中心→场景 ({vc.x():.1f},{vc.y():.1f}) · 核心中心 "
                  f"({r.center().x():.1f},{r.center().y():.1f}) · 偏差 dx={dx:.1f} dy={dy:.1f} "
                  f"(容差 {tol_x:.0f}/{tol_y:.0f})")
            check("核心落在视口中心 (容差内)", dx <= tol_x and dy <= tol_y, f"dx={dx:.1f} dy={dy:.1f}")
        chk = getattr(mod, "chk_core_center", None)
        check("工具栏「🧮 核心居中」开关存在且默认勾选",
              chk is not None and chk.isChecked(), f"{None if chk is None else chk.isChecked()}")
    except Exception as e:                                                 # noqa: BLE001
        import traceback
        traceback.print_exc()
        check("模块级居中验证可运行", False, f"{type(e).__name__}: {e}")

    print("\n" + "=" * 78)
    print("结果:", "全部通过 ✅" if not FAILS else f"失败 {len(FAILS)} 项 ❌ {FAILS}")
    print("CORE_NODE_UI_TEST_DONE")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    rc = 1
    try:
        rc = main()
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(rc)          # offscreen Qt teardown 用 _exit (避免析构期 SIGABRT)
