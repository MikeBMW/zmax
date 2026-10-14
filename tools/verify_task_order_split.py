#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据: 配置中心「任务配置 / 工单配置」两项拆分 + 元任务信息进任务配置 (2026-10-14 老倪)

老倪原话:
    「将元任务, 这些信息, 体现在配置中心的 任务配置;
      将原来的工艺工单任务, 拆解成 任务配置 和 工单配置 两项」

判据 (每条都真跑真源/真界面, 不看声明):
  ① 左树拆成两项: 有「📋 任务配置」「🧾 工单配置」两个顶层项, **不再**有「工艺·工单」
  ② 页签同拆: 有「📋 任务配置」「🧾 工单配置」, 不再有「🎯 工单」; 既有 7 个区一个没丢
  ③ 任务配置页的元任务表: 列 == 《元任务标准模板》七字段 + 编号/层/优先; 行数 == 真源功能数
  ④ 元任务数值可回读: 抽查元任务的 fn_id/名称 与 config_meta.json 逐条一致
  ⑤ 两表联动: 点任务表某任务 ⇒ 元任务表只剩该任务的元任务, 条数 == 真源该任务 enabled_nodes 数
  ⑥ 工单配置页: 原 6 列逐字保留 + 新维度追加在后 (增列不换列); 行数 == config/orders/BS_*.json 份数
  ⑦ 点左树工单号 ⇒ 切到工单配置页 + 底部面板摊开该工单完整配置面 (工单号/场景/配方)
  ⑧ CLI 同源: config_center.py overview 打印「任务配置」「工单配置」两行, 不再有「工艺·工单」
用法: QT_QPA_PLATFORM=offscreen gui-venv311/bin/python tools/verify_task_order_split.py
"""
import io
import json
import os
import sys
from contextlib import redirect_stdout

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from PyQt5.QtWidgets import QApplication, QTreeWidgetItem                                    # noqa: E402
import veh6_config_page as vp                                                                # noqa: E402
import config_center as cc                                                                   # noqa: E402

OK, BAD = [], []


def chk(name, ok, ev=""):
    (OK if ok else BAD).append(name)
    print("  %s %-52s %s" % ("✅" if ok else "❌", name, ev))


def _j(p, d=None):
    try:
        with io.open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                                                        # noqa: BLE001
        return d


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    pg = vp.build_config_center(None, None)
    pg.resize(1600, 950)
    pg.show()
    app.processEvents()

    tops = [pg.tree.topLevelItem(i).text(0) for i in range(pg.tree.topLevelItemCount())]
    tabs = [pg.tabs.tabText(i) for i in range(pg.tabs.count())]

    print("═══ ① 左树拆两项 ═══")
    chk("左树有「📋 任务配置」项", any("📋 任务配置" in t for t in tops), " / ".join(t.strip() for t in tops))
    chk("左树有「🧾 工单配置」项", any("🧾 工单配置" in t for t in tops))
    chk("旧的「工艺·工单」项已不再单列", not any(t.strip().startswith("工艺·工单") for t in tops))
    task_it = next((pg.tree.topLevelItem(i) for i in range(pg.tree.topLevelItemCount())
                    if "📋 任务配置" in pg.tree.topLevelItem(i).text(0)), None)
    ord_it = next((pg.tree.topLevelItem(i) for i in range(pg.tree.topLevelItemCount())
                   if "🧾 工单配置" in pg.tree.topLevelItem(i).text(0)), None)
    chk("任务配置子项 = 任务 ID (7 条)", task_it is not None and task_it.childCount() == 7,
        "子项 %s" % (task_it.childCount() if task_it else "—"))
    chk("工单配置子项 = 工单号", ord_it is not None and ord_it.childCount() == 5,
        "子项 %s" % (ord_it.childCount() if ord_it else "—"))

    print("\n═══ ② 页签同拆 + 既有区没丢 ═══")
    chk("页签有「📋 任务配置」", "📋 任务配置" in tabs, " · ".join(tabs))
    chk("页签有「🧾 工单配置」(旧「🎯 工单」改名)", "🧾 工单配置" in tabs and "🎯 工单" not in tabs)
    keep = ["📋 任务配置", "⚙️ 工程配置", "🧩 功能·性能·模型", "🧠 模型匹配", "📄 文档交付", "📄 文档预览"]
    chk("既有 6 个区一个没丢", all(k in tabs for k in keep), "缺 %s" % [k for k in keep if k not in tabs])

    print("\n═══ ③ 元任务表 (标准模板七字段) ═══")
    mt_src = _j(os.path.join(ROOT, "data/database/zmax/config_meta.json"), {}) or {}
    n_fn = len(mt_src.get("functions", {}))
    t = getattr(pg, "meta_table", None)
    chk("任务配置页有元任务表", t is not None)
    cols = [t.horizontalHeaderItem(c).text() for c in range(t.columnCount())] if t else []
    need = ["功能名称", "输入", "输出", "配置参数", "依赖关系", "验证方法", "承载场景"]
    chk("列含《元任务标准模板》七字段", all(x in cols for x in need), " / ".join(cols))
    chk("元任务行数 == 真源功能数 %d" % n_fn, bool(t) and t.rowCount() == n_fn,
        "表行数 %s" % (t.rowCount() if t else "—"))
    tip = (t.item(0, 0).toolTip() if t and t.item(0, 0) else "")
    chk("每格 tooltip 是完整标准模板 (七字段齐)", all(x in tip for x in need), tip.replace("\n", " | ")[:90])

    print("\n═══ ④ 元任务数值回读真源 ═══")
    mt = vp._meta_tasks()
    bad = [m for m in mt if (mt_src["functions"].get(m["fn_id"]) or {}).get("name") != m["name"]]
    chk("逐条: 元任务名 == config_meta.json 功能名", not bad, "不一致 %d 条" % len(bad))
    chk("每个元任务都有画布节点 (74/74)",
        all(m.get("node_id") for m in mt), "缺节点 %d" % sum(1 for m in mt if not m.get("node_id")))
    chk("依赖关系来自画布连线 (非空比例 >0)",
        sum(1 for m in mt if m.get("deps_up")) > 0,
        "有上游依赖的元任务 %d/%d" % (sum(1 for m in mt if m.get("deps_up")), len(mt)))

    print("\n═══ ⑤ 两表联动 (点任务行 ⇒ 元任务筛) ═══")
    bind = _j(os.path.join(ROOT, "config/ss_task_binding.json"), {}) or {}
    bmap = {b["task_id"]: b for b in (bind.get("tasks") or [])}
    r0 = pg._task_rows.index("TASK-01-FW") if "TASK-01-FW" in getattr(pg, "_task_rows", []) else 0
    pg.tasks_table.selectRow(r0)
    app.processEvents()
    tid = pg._task_rows[r0]
    vis = sum(1 for r in range(t.rowCount()) if not t.isRowHidden(r))
    exp = len((bmap.get(tid) or {}).get("enabled_nodes") or [])
    chk("点 %s ⇒ 元任务可见数 == 真源 enabled_nodes 数" % tid, vis == exp, "可见 %d / 期望 %d" % (vis, exp))
    chk("表头写明当前口径", tid in pg.meta_head.text(), pg.meta_head.text()[:70])
    pg._filter_meta_tasks(None)
    app.processEvents()
    vis_all = sum(1 for r in range(t.rowCount()) if not t.isRowHidden(r))
    chk("「显示全部元任务」恢复 %d 条" % n_fn, vis_all == n_fn, "可见 %d" % vis_all)

    print("\n═══ ⑥ 工单配置页: 原 6 列保留 + 增列 ═══")
    t4 = getattr(pg, "order_table", None)
    cols4 = [t4.horizontalHeaderItem(c).text() for c in range(t4.columnCount())] if t4 else []
    old6 = ["工单号", "场景", "BOM", "步骤", "站点就绪", "状态"]
    chk("原 6 列逐字保留 (增列不换列)", cols4[:6] == old6, " / ".join(cols4))
    chk("新维度追加在后 (配方/参数/变体/目标/选项)", all(k in cols4[6:] for k in ("配方", "参数")), " / ".join(cols4[6:]))
    n_bs = len([f for f in os.listdir(os.path.join(ROOT, "config/orders")) if f.startswith("BS_")])
    chk("工单行数 == 真源份数 %d" % n_bs, bool(t4) and t4.rowCount() == n_bs, "行 %s" % (t4.rowCount() if t4 else "—"))

    print("\n═══ ⑦ 点左树工单号 ⇒ 完整配置面 ═══")
    child = QTreeWidgetItem(["   BS-SCN-01-FW-0001"]) if ord_it is None else ord_it.child(0)
    pg._on_tree(child, 0)
    app.processEvents()
    txt = pg.out.toPlainText()
    chk("切到工单配置页", "工单配置" in pg.tabs.tabText(pg.tabs.currentIndex()),
        pg.tabs.tabText(pg.tabs.currentIndex()))
    chk("面板出该工单 (号/场景/配方)", ("BS-SCN-01-FW" in txt) and ("配方" in txt) and ("SCN-01-FW" in txt),
        txt[:70].replace("\n", " | "))

    print("\n═══ ⑧ CLI 同源 ═══")
    buf = io.StringIO()
    with redirect_stdout(buf):
        cc.cmd_overview(type("A", (), {"json": False})())
    out = buf.getvalue()
    chk("overview 有「任务配置」行", "任务配置" in out)
    chk("overview 有「工单配置」行", "工单配置" in out)
    chk("overview 不再有「工艺·工单」", "工艺·工单" not in out)
    chk("CLI DOMAINS 与界面同名 (2 项)",
        cc.DOMAINS[-2:] == ["任务配置", "工单配置"], str(cc.DOMAINS))

    print("\n" + ("✅ 全部通过 (%d 项)" % len(OK) if not BAD else "⛔ 失败 %d 项: %s" % (len(BAD), BAD)))
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
