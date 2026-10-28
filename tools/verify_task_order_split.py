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
    # 2026-10-15 老倪: 「左侧不用显示那么多, 只显示 1..7 …… 详细信息要在配置页面显示」
    # ⇒ 左树只留 7 颗星 (序号+名称·星名), **不再有子项**; 任务 ID/工单号改在各自配置页的表里看。
    # 2026-10-17 老倪「现在太宽了」: 行里只画「序号 + 名称」, 星名在 item data(全文) 与阵图条上
    _full = [str(pg.tree.topLevelItem(i).data(0, __import__("PyQt5.QtCore", fromlist=["Qt"]).Qt.UserRole + 1) or "")
             for i in range(pg.tree.topLevelItemCount())]
    chk("左树有「2. 任务配置 · 天璇」项", any("任务配置 · 天璇" in t for t in _full), " / ".join(t.strip() for t in _full))
    chk("左树有「6. 工程配置 · 开阳」项 (2026-10-19 第六阵换名)", any("工程配置 · 开阳" in t for t in _full))
    chk("左树已无「工单配置」项 (工单并入文档配置)", not any("工单配置" in t for t in _full))
    chk("旧的「工艺·工单」项已不再单列", not any(t.strip().startswith("工艺·工单") for t in tops))
    task_it = next((pg.tree.topLevelItem(i) for i in range(pg.tree.topLevelItemCount())
                    if "任务配置" in pg.tree.topLevelItem(i).text(0)), None)
    ord_it = next((pg.tree.topLevelItem(i) for i in range(pg.tree.topLevelItemCount())
                   if "文档配置" in pg.tree.topLevelItem(i).text(0)), None)
    chk("左树七项都**没有子项** (老倪 2026-10-15 精简)", all(
        pg.tree.topLevelItem(i).childCount() == 0 for i in range(pg.tree.topLevelItemCount())),
        "子项数=%s" % [pg.tree.topLevelItem(i).childCount() for i in range(pg.tree.topLevelItemCount())])
    # 明细挪到配置页: 任务配置页的任务表行数 = 真源任务数 (2026-10 起 8 条); 工单表行数 = 真源工单数
    _tt = getattr(pg, "tasks_table", None)
    _ot = getattr(pg, "order_table", None)
    _tk_n = len((_j(os.path.join(ROOT, "config", "tasks", "tasks.json")) or {}).get("tasks") or [])
    _ord_n = len([f for f in os.listdir(os.path.join(ROOT, "config", "orders")) if f.endswith(".json")]) \
        if os.path.isdir(os.path.join(ROOT, "config", "orders")) else -1
    chk("任务明细在配置页: 任务表 %d 行 (真源任务数)" % _tk_n,
        _tt is not None and _tt.rowCount() == _tk_n,
        "行数=%s 真源=%d" % (getattr(_tt, "rowCount", lambda: "—")(), _tk_n))
    chk("工单明细在配置页: 工单表 %d 行 (真源工单数)" % _ord_n,
        _ot is not None and _ot.rowCount() == _ord_n,
        "行数=%s" % (getattr(_ot, "rowCount", lambda: "—")()))

    print("\n═══ ② 页签同拆 + 既有区没丢 ═══")
    chk("页签有「📋 任务配置」", "📋 任务配置" in tabs, " · ".join(tabs))
    # 2026-10-19 老倪: 「将工单，放到文档配置选项卡」⇒ 工单不再有独立页签, 表并进 📄 文档配置
    chk("「🧾 工单配置」页签已取消 (工单进文档配置页)", "🧾 工单配置" not in tabs and "🎯 工单" not in tabs)
    _di = pg._tab_index_by_title("文档配置")
    _dh = pg.tabs.widget(_di) if _di >= 0 else None
    chk("工单表确实挂在「📄 文档配置」页里",
        _dh is not None and getattr(pg, "order_table", None) is not None
        and (_dh.isAncestorOf(pg.order_table) or _dh is pg.order_table),
        "文档配置页=%s" % (getattr(_dh, "objectName", lambda: "?")() or "QScrollArea"))
    # 2026-10-15: 模型匹配 → 并入 🧠 模型配置 · 文档预览 → 并入 📄 文档配置 (页签取消)
    keep = ["📋 任务配置", "⚙️ 工程配置", "🧩 功能配置", "⚡ 性能配置", "🧠 模型配置", "📄 文档配置"]
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

    print("\n═══ ⑥ 工单表 (在文档配置页里): 原 6 列保留 + 增列 ═══")
    t4 = getattr(pg, "order_table", None)
    cols4 = [t4.horizontalHeaderItem(c).text() for c in range(t4.columnCount())] if t4 else []
    old6 = ["工单号", "场景", "BOM", "步骤", "站点就绪", "状态"]
    chk("原 6 列逐字保留 (增列不换列)", cols4[:6] == old6, " / ".join(cols4))
    chk("新维度追加在后 (配方/参数/变体/目标/选项)", all(k in cols4[6:] for k in ("配方", "参数")), " / ".join(cols4[6:]))
    n_bs = len([f for f in os.listdir(os.path.join(ROOT, "config/orders")) if f.startswith("BS_")])
    chk("工单行数 == 真源份数 %d" % n_bs, bool(t4) and t4.rowCount() == n_bs, "行 %s" % (t4.rowCount() if t4 else "—"))

    print("\n═══ ⑦ 定位到具体工单 ⇒ 完整配置面 ═══")
    # 2026-10-15: 左树不再有工单号子项 ⇒ 走与"点工单号"同一条处理函数 (_show_orders(工单号))
    _bs_list = vp._orders_list()                              # 真源: config/orders/BS_*.json
    _bs_no = str(((_bs_list[0].get("identity") or {}).get("order_no")) or "BS-")
    pg._show_orders(_bs_no)
    app.processEvents()
    txt = pg.out.toPlainText()
    chk("切到文档配置页 (工单块所在页)", "文档配置" in pg.tabs.tabText(pg.tabs.currentIndex()),
        pg.tabs.tabText(pg.tabs.currentIndex()))
    chk("面板出该工单 (号/场景/配方)", ("BS-SCN-01-FW" in txt) and ("配方" in txt) and ("SCN-01-FW" in txt),
        txt[:70].replace("\n", " | "))

    print("\n═══ ⑧ CLI 同源 ═══")
    buf = io.StringIO()
    with redirect_stdout(buf):
        cc.cmd_overview(type("A", (), {"json": False})())
    out = buf.getvalue()
    chk("overview 有「任务配置」行", "任务配置" in out)
    chk("overview 有「文档配置」行 (工单并入这一行)", "文档配置" in out)
    chk("overview 不再有「工艺·工单」", "工艺·工单" not in out)
    chk("CLI DOMAINS 与界面同名 (任务配置 / 文档配置 收尾)",
        cc.DOMAINS[-2:] == ["任务配置", "文档配置"], str(cc.DOMAINS))

    print("\n" + ("✅ 全部通过 (%d 项)" % len(OK) if not BAD else "⛔ 失败 %d 项: %s" % (len(BAD), BAD)))
    return 1 if BAD else 0


if __name__ == "__main__":
    sys.exit(main())
