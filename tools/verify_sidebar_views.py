#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🗂 画布右侧栏 三页契约 判据 (老倪 2026-10-15)

老倪原话: 「画布右侧栏, 保留 主参数：对应流形引擎； 数据总线：对应数据空间的 Trace;
参数中心：对应数据库服务的所有参数；删除 运行开关。」

判据 (每条可复核; 离屏真建 ModelTreeDock):
  ① 下拉 3 行, 文案与键一一对应: 主参数 M → 流形引擎 / 数据总线 → 数据空间 Trace / 参数中心 → 数据库服务
  ② 三页真切换: 切到哪页只有哪页可见 (另两页不显示)
  ③ **参数中心真读数据库服务**: 独立 HTTP 取 127.0.0.1:8798/params 的 total, 与页面表行数逐一对上;
     服务不可达 ⇒ 页面必须走**诚实空态**(报"未响应"), 不许显示 0/旧值
  ④ 撤下下拉的两页 (🎛 标定真源 / 🔧 运行开关) 对象仍在 (没删) 且切遍下拉都不会显示
  ⑤ 6 个运行开关**还是同一批控件对象** (module.chk_* is dock.run_cfg._cks[k]) + 引擎读法未变 (self.chk_ 计数 > 0)
  ⑥ 引擎侧栏判定口零改动: view_is(表驱动) 真判当前页 (切 bus ⇒ view_is("bus")=True / view_is("mparam")=False)
  ⑦ 工程存档的 available_views 与 VIEW_KEYS **同源同序** (project_file 写死过一份, 漂移即红)
  ⑧ 眼睛能看到的证据: 三页各出一张截图 (reports/ui_shots/sidebar_*.png)

用法: cd /home/ubuntu/zmax && QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/verify_sidebar_views.py
"""
from __future__ import annotations

import io
import json
import os
import sys
import urllib.request

ROOT = "/home/ubuntu/zmax"
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication                       # noqa: E402
import simulink_module as SM                                   # noqa: E402
import model_tree as MT                                        # noqa: E402
import project_file as PF                                      # noqa: E402

CANVAS = os.path.join(ROOT, "src/lerobot/engineering/flows/state_space_obs.json")
SHOTS = os.path.join(ROOT, "reports", "ui_shots")
rows = []


def chk(tag, ok, ev):
    rows.append((tag, bool(ok), ev))
    print("  %s %s  %s" % ("✅" if ok else "❌", tag, ev))
    return bool(ok)


def api_params():
    """独立取数据库服务 (判据不借页面的嘴 —— 自己去 HTTP 拿一遍)"""
    try:
        with urllib.request.urlopen("http://127.0.0.1:8798/params", timeout=5) as r:
            d = json.loads(r.read().decode("utf-8"))
        return (d.get("data") or {}).get("total"), (d.get("data") or {}).get("by_cat") or {}
    except Exception as e:                                                 # noqa: BLE001
        return None, {"err": str(e)[:60]}


def main() -> int:
    print("═══ 画布右侧栏 三页契约 判据 (主参数 / 数据总线 / 参数中心; 删 运行开关) ═══")
    app = QApplication(sys.argv)
    m = SM.SimulinkModule(); m.resize(2400, 1400); m.show()
    m.load_flow_file(CANVAS); app.processEvents()
    d = m.model_tree
    assert d is not None, "ModelTreeDock 没建起来"

    # ① 下拉 3 行
    items = [d.cmb_view.itemText(i) for i in range(d.cmb_view.count())]
    chk("① 下拉 3 行且文案对应",
        d.cmb_view.count() == 3 and list(d.VIEW_KEYS) == ["mparam", "bus", "param_center"]
        and items[0].endswith("主参数 M") and items[1].endswith("数据总线") and items[2].endswith("参数中心"),
        "items=%s · VIEW_KEYS=%s" % (items, list(d.VIEW_KEYS)))

    # ② 三页真切换
    seen = {}
    ok2, ev2 = True, []
    for key, w in (("mparam", d.mparam), ("bus", d.bus), ("param_center", d.pc_side)):
        d.cmb_view.setCurrentIndex(list(d.VIEW_KEYS).index(key)); app.processEvents()
        vis = {k2: w2.isVisible() for k2, w2 in
               (("mparam", d.mparam), ("bus", d.bus), ("pc_side", d.pc_side))}
        good = vis[key if key != "param_center" else "pc_side"] and sum(1 for v in vis.values() if v) == 1
        ok2 = ok2 and good
        ev2.append("%s→%s" % (key, vis))
        seen[key] = vis
    chk("② 三页真切换 (一次只有一页可见)", ok2, " ".join(ev2))

    # ③ 参数中心真读数据库服务
    total, cats = api_params()
    d.cmb_view.setCurrentIndex(list(d.VIEW_KEYS).index("param_center")); app.processEvents()
    n_tbl = d.pc_side.tbl.rowCount()
    cnt_txt = d.pc_side.lbl_cnt.text()
    if total is None:
        chk("③ 参数中心 ↔ 数据库服务 (服务未起时的诚实空态)",
            "未响应" in d.pc_side.lbl_src.text() and n_tbl == 0 and "0 条" in cnt_txt,
            "服务不可达 ⇒ 页面: %s" % d.pc_side.lbl_src.text().replace("\n", " / ")[:70])
    else:
        chk("③ 参数中心 ↔ 数据库服务 (逐条对上)",
            n_tbl == total and str(total) in cnt_txt and all(str(v) in cnt_txt for v in cats.values()),
            "服务 total=%d · 页面表 %d 行 · 计数行「%s」" % (total, n_tbl, cnt_txt[:80]))
        chk("③b 标定类数字在参数中心里 (替代原「标定真源」页)",
            "标定 %d" % cats.get("calib", -1) in cnt_txt,
            "服务 by_cat.calib=%s" % cats.get("calib"))

    # ④ 撤下的两页对象仍在, 且永不显示
    ever = []
    for i in range(d.cmb_view.count()):
        d.cmb_view.setCurrentIndex(i); app.processEvents()
        ever.append((d.calib.isVisible(), d.run_cfg.isVisible()))
    chk("④ 标定真源/运行开关两页: 对象在, 永不显示",
        isinstance(d.calib, MT.CalibTruthView) and isinstance(d.run_cfg, MT.RunConfigWidget)
        and not any(a or b for a, b in ever),
        "两对象在 · 切遍 %d 页可见性=%s" % (d.cmb_view.count(), ever))

    # ⑤ 6 个开关还是同一批对象 + 引擎读法未变
    KEYS = [k for k in ("chk_engine_demo", "chk_l3_full", "chk_mani_yaw", "chk_intact_exec",
                        "chk_l4_dit", "chk_l2_compat") if hasattr(m, k)]
    same = [k for k in KEYS if d.run_cfg._cks.get(k) is getattr(m, k, None)]
    src = io.open(os.path.join(ROOT, "tools", "gui", "simulink_module.py"), encoding="utf-8").read()
    n_read = src.count("self.chk_") + src.count("getattr(self, 'chk_")
    chk("⑤ 6 个开关同一对象 + 引擎读法未变", len(KEYS) == 6 and len(same) == 6 and n_read > 1,
        "同一对象 %d/6 (%s) · 引擎里 self.chk_* 读点 %d 处" % (len(same), ",".join(KEYS), n_read))

    # ⑥ 引擎侧栏判定口 (表驱动) 零改动
    d.cmb_view.setCurrentIndex(1); app.processEvents()
    ok6 = d.view_is("bus") and not d.view_is("mparam")
    d.cmb_view.setCurrentIndex(2); app.processEvents()
    ok6 = ok6 and d.view_is("param_center") and not d.view_is("bus")
    chk("⑥ view_is 表驱动仍准确 (数据总线页喂数据靠它)", ok6,
        "切 bus ⇒ bus=True/mparam=False; 切参数中心 ⇒ param_center=True/bus=False")

    # ⑦ 工程存档的 available_views 与 VIEW_KEYS 同源
    panel = PF.collect_panel(sim=m, page=0)
    avail = panel.get("available_views")
    chk("⑦ 工程存档 available_views == VIEW_KEYS", list(avail or []) == list(d.VIEW_KEYS),
        "存档里 %s vs 实际 %s" % (avail, list(d.VIEW_KEYS)))

    # ⑧ 出截图 (三页各一张, 眼睛能看到的证据)
    os.makedirs(SHOTS, exist_ok=True)
    saved = []
    for key in ("mparam", "bus", "param_center"):
        d.cmb_view.setCurrentIndex(list(d.VIEW_KEYS).index(key)); app.processEvents()
        d.setFixedWidth(430)
        p = os.path.join(SHOTS, "sidebar_%s.png" % key)
        d.grab().save(p)
        saved.append(os.path.basename(p))
    chk("⑧ 三页截图落盘", all(os.path.getsize(os.path.join(SHOTS, f)) > 3000 for f in saved),
        " · ".join("%s %.1fKB" % (f, os.path.getsize(os.path.join(SHOTS, f)) / 1024) for f in saved))

    n = sum(1 for _t, o, _e in rows if o)
    print("\n═══ 判据 %d/%d 通过 ═══" % (n, len(rows)))
    return 0 if n == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
