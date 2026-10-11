#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_aoi_task7.py — 判据: 配置中心「任务7 = AOI」+ 画布节点改名「光学质量检测」+ AOI 话题/AR 空间点位

老倪 2026-10-11 指令 (逐字):
    「在配置中心，增加任务7,对应 AOI 任务，场景就对应 AR, 模型对应 Automated Optical Inspection
      自动光学检测 的 L5 自主进化程序, 现在的 状态空间工程，外观质量检测 节点，改名成 光学质量检测，
      发出 AOI 相关的所有 topic, 信号分析对应 AR 场景下的所有空间点位置」

八组判据 (全部真跑, 不假装):
  ① 任务配置: 7 条; 任务7 = TASK-07-AOI (场景 SCN-07-AOI · 类型 光学质量检测 · model_ref = L5 自主进化程序)
               且 任务1..6 与上一版 git 版逐字节一致
  ② 场景真源: SCN-06-TRAY(摆盘) 补回 + SCN-07-AOI(ar_aoi) 新增; 场景名 == 任务名
  ③ 配置中心真渲染 (offscreen 起 ConfigCenterPage): 任务表 7 行, 有「场景」「模型」两列,
               任务7 那行 = 场景含 AR · 模型含 L5 自主进化程序 (tooltip 带全称)
  ④ 节点改名全链: 画布真源 / 注册匹配 / 数据总线 MODULE_ORDER / simulink 映射 / 功能清单 / MCD / feature.dbc
  ⑤ AOI 话题真发出: 真跑画布节点 🔍 光学质量检测 → 信号总线 live 出现 光学质量检测.* ≥8 个键 (值来自本轮真算)
  ⑥ AR 空间点位: 信号总线 ar. 键 ≥20 (示教点位台账 + 空间点 + TCP 真值 + RealSense 相机系)
  ⑦ 信号分析接线: HOST_SOURCES 含 ar 源; 显示名去前缀; 组名来自注册表
  ⑧ 生成器一致: task_build.py --check ✅ (重算与盘上逐字节一致)
用法: python3 tools/verify_aoi_task7.py   (exit 0 = 全过; 2 = 有 FAIL)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

OK, FAIL = [], []


def ck(name, cond, ev=""):
    (OK if cond else FAIL).append(name)
    print("  %s %s%s" % ("✅" if cond else "❌", name, ("   ← " + str(ev)[:220]) if ev else ""))
    return bool(cond)


def _j(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _git_show(rel):
    try:
        out = subprocess.run(["git", "-C", ROOT, "show", "HEAD:" + rel],
                             capture_output=True, text=True, timeout=60)
        return json.loads(out.stdout) if out.returncode == 0 else None
    except Exception:                                                           # noqa: BLE001
        return None


def main():
    print("=== ① 任务配置 (config/tasks/tasks.json) ===")
    tk = _j(os.path.join(ROOT, "config", "tasks", "tasks.json"))
    tasks = tk["tasks"]
    ids = [t["task_id"] for t in tasks]
    ck("任务 7 条", len(tasks) == 7, ids)
    aoi = next((t for t in tasks if t["task_id"] == "TASK-07-AOI"), None)
    ck("任务7 = TASK-07-AOI 存在", aoi is not None)
    if aoi:
        ck("任务7 场景 = SCN-07-AOI (AR)", aoi.get("scene_ref") == "SCN-07-AOI", aoi.get("scene_ref"))
        ck("任务7 类型 = 光学质量检测", aoi.get("recipe_type") == "光学质量检测", aoi.get("recipe_type"))
        mr = aoi.get("model_ref") or {}
        ck("任务7 模型层 = L5", mr.get("layer") == "L5", mr.get("layer"))
        prog = str(mr.get("program") or "")
        ck("任务7 模型程序 = Automated Optical Inspection 自动光学检测 · L5 自主进化程序",
           "Automated Optical Inspection" in prog and "自动光学检测" in prog and "L5 自主进化程序" in prog, prog)
    old = _git_show("config/tasks/tasks.json")
    if old:
        ob = {t["task_id"]: json.dumps(t, ensure_ascii=False, sort_keys=True) for t in old["tasks"]}
        nb = {t["task_id"]: json.dumps(t, ensure_ascii=False, sort_keys=True) for t in tasks}
        same = [k for k in ob if nb.get(k) == ob[k]]
        ck("任务1..6 与上一版逐字节一致 (%d/%d)" % (len(same), len(ob)),
           len(same) == len(ob) and len(tasks) == len(old["tasks"]) + 1, "旧 %s" % sorted(ob))
    else:
        print("  ⏭ 跳过 git 对比 (HEAD 里没有该文件)")

    print("=== ② 场景真源 (flows/scenes_5jobs.json) ===")
    sc = {s["scene_id"]: s for s in _j(os.path.join(ROOT, "flows", "scenes_5jobs.json"))["scenes"]}
    ck("SCN-06-TRAY 补回 (tray_filling)", sc.get("SCN-06-TRAY", {}).get("scene_type") == "tray_filling")
    ck("SCN-07-AOI 新增 (ar_aoi)", sc.get("SCN-07-AOI", {}).get("scene_type") == "ar_aoi")
    if aoi:
        ck("场景名 == 任务名", sc.get("SCN-07-AOI", {}).get("name") == aoi.get("name"),
           sc.get("SCN-07-AOI", {}).get("name"))

    print("=== ③ 配置中心真渲染 (offscreen ConfigCenterPage) ===")
    try:
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        import veh6_config_page as V
        pg = V.ConfigCenterPage()
        t = pg.tasks_table
        nrow, ncol = t.rowCount(), t.columnCount()
        head = [t.horizontalHeaderItem(c).text() for c in range(ncol)]
        ck("任务表 7 行", nrow == 7, "行=%d 列=%d %s" % (nrow, ncol, head))
        ck("表头含「场景」与「模型」", "场景" in head and "模型" in head, head)
        i = head.index("任务ID")
        r = next((r for r in range(nrow) if t.item(r, i) and t.item(r, i).text() == "TASK-07-AOI"), -1)
        ck("任务7 行在表内", r >= 0)
        if r >= 0:
            scell = t.item(r, head.index("场景"))
            mcell = t.item(r, head.index("模型"))
            ck("任务7 场景列含 AR", scell is not None and "AR" in scell.text(),
               scell.text() if scell else None)
            ck("任务7 模型列含 L5 自主进化程序", mcell is not None and "L5 自主进化程序" in mcell.text(),
               mcell.text() if mcell else None)
            tip = mcell.toolTip() if mcell else ""
            ck("模型 tooltip 带全称 (Automated Optical Inspection 自动光学检测)",
               "Automated Optical Inspection" in tip and "自动光学检测" in tip, tip[:80])
        del pg
        app.processEvents()
    except Exception as e:                                                      # noqa: BLE001
        ck("配置中心真渲染", False, "%s: %s" % (type(e).__name__, e))

    print("=== ④ 节点改名全链 (外观质量检测 → 光学质量检测) ===")
    from lerobot.engineering import flows
    d, errs = flows.load_canvas()
    node = next((n for n in d["nodes"] if "质量检测" in (n.get("name") or "")), None)
    ck("画布真源节点名 = 🔍 光学质量检测", node is not None and node["name"] == "🔍 光学质量检测",
       node["name"] if node else None)
    ck("画布 89 节点未变", len(d["nodes"]) == 89, len(d["nodes"]))
    from lerobot.engineering import registry
    ck("注册匹配 🔍 光学质量检测 → ss_aoi", registry.match_node("🔍 光学质量检测") == "ss_aoi")
    ck("旧名仍可匹配 (向后兼容)", registry.match_node("🔍 外观质量检测") == "ss_aoi")
    import data_world
    ck("数据总线 MODULE_ORDER 含新名", "🔍 光学质量检测" in data_world.MODULE_ORDER
       and "🔍 外观质量检测" not in data_world.MODULE_ORDER)
    src = open(os.path.join(ROOT, "tools", "gui", "simulink_module.py"), encoding="utf-8").read()
    ck("simulink 映射含新名", '"🔍 光学质量检测": "🔍 光学质量检测"' in src)
    nft = open(os.path.join(ROOT, "src", "lerobot", "verification", "node_func_tree.py"), encoding="utf-8").read()
    ck("功能清单 (node_func_tree) 含新名且无旧名", "🔍 光学质量检测" in nft and "外观质量检测" not in nft)
    mcd = open(os.path.join(ROOT, "config", "mcd", "zmax_mcd.json"), encoding="utf-8").read()
    ck("MCD 能力名已改 (光学 5 / 外观 0)", mcd.count("光学质量检测") == 5 and mcd.count("外观质量检测") == 0,
       "光学=%d 外观=%d" % (mcd.count("光学质量检测"), mcd.count("外观质量检测")))
    dbc = open(os.path.join(ROOT, "data", "database", "zmax", "sources", "feature.dbc"), encoding="utf-8").read()
    ck("feature.dbc BO_ B5 = 光学质量检测", "BO_ B5 光学质量检测" in dbc and "BO_ B5 外观质量检测" not in dbc)

    print("=== ⑤ AOI 话题真发出 (真跑画布节点) ===")
    from lerobot.engineering.nodes import library as L
    ctx = {"log": lambda *a, **k: None}
    L.node_ss_aoi(ctx)
    import ar_aoi_bus as B
    live = os.path.join(ROOT, "zmax_data", "ar_live", "ar_aoi_live.json")
    doc = _j(live)
    keys = {k: v for k, v in (doc.get("s") or {}).items() if k.startswith("光学质量检测.")}
    ck("节点发出的 AOI 话题 ≥8 个 (live 回读)", len(keys) >= 8, sorted(keys))
    ck("判决话题有真值 (0/1)", keys.get("光学质量检测.判决") in (0.0, 1.0), keys.get("光学质量检测.判决"))
    ck("缺陷数 = 划伤+污点 (自洽)", abs(keys.get("光学质量检测.缺陷数", -1)
       - (keys.get("光学质量检测.划伤数", 0) + keys.get("光学质量检测.污点数", 0))) < 1e-6,
       "%s = %s + %s" % (keys.get("光学质量检测.缺陷数"), keys.get("光学质量检测.划伤数"),
                         keys.get("光学质量检测.污点数")))
    spec = _j(os.path.join(ROOT, "config", "topics", "ar_aoi_signals.json"))
    ck("注册表组数 ≥5 且含 光学质量检测 组", len(spec.get("groups") or {}) >= 5
       and any("光学质量检测" in g for g in (spec.get("groups") or {})), list((spec.get("groups") or {}).keys()))

    print("=== ⑥ AR 场景空间点位 (信号分析来源 ar.) ===")
    # 总线 live 文件里的键**不带**来源前缀 (前缀 ar. 是信号分析页按 HOST_SOURCES 加的)
    ar = [k for k in (doc.get("s") or {}) if not k.startswith("光学质量检测.")]
    pts = [k for k in ar if k.split(".")[0] in
           ("金手指点1", "金手指点2", "侧面点0", "侧面点1", "侧面点2", "侧面点3",
            "准备点", "安全点1", "末端", "GUI测试点")]
    spaces = [k for k in ar if k.startswith("空间点")]
    cams = [k for k in ar if k.startswith("相机.")]
    ck("AR 空间点位信号 ≥20 条", len(ar) >= 20, "共 %d" % len(ar))
    ck("示教点位/末端 三维齐 (≥10 条)", len(pts) >= 10, sorted(pts)[:6])
    ck("空间点 1..7 在 (≥21 条 xyz)", len(spaces) >= 21, "空间点键 %d" % len(spaces))
    ck("相机系 (RealSense) 键在 (≥5)", len(cams) >= 5, sorted(cams)[:5])
    ck("组名齐全 (≥6 组)", len(doc.get("groups") or {}) >= 6, list((doc.get("groups") or {}).keys()))

    print("=== ⑦ 信号分析页接线 ===")
    cg = open(os.path.join(ROOT, "tools", "gui", "canoe_graphic.py"), encoding="utf-8").read()
    ck("HOST_SOURCES 含 ar 源 (ar_llive.json)" if False else
       "HOST_SOURCES 含 ar 源 (ar_aoi_live.json)", '("ar", "zmax_data/ar_live/ar_aoi_live.json")' in cg)
    ck("显示名去 ar. 前缀 + 来源提示", 'for pre in ("sstrace.", "ds.", "ar.")' in cg
       and 'return "🥽 AR/AOI 信号总线 · "' in cg)
    ck("AR 分组树 (组名来自注册表)", "_ar_groups" in cg and "🥽 AR 场景 · 空间点位 / AOI 话题" in cg)

    print("=== ⑧ 生成器一致 (task_build --check) ===")
    p = subprocess.run([PY, os.path.join(ROOT, "tools", "task_build.py"), "--check"],
                       capture_output=True, text=True, timeout=300, cwd=ROOT)
    ck("task_build.py --check ✅", p.returncode == 0, (p.stdout or "").strip()[-160:])

    print("\n" + "=" * 72)
    print("判据: %d PASS / %d FAIL" % (len(OK), len(FAIL)))
    if FAIL:
        print("❌ FAIL: " + " · ".join(FAIL))
    return 0 if not FAIL else 2


if __name__ == "__main__":
    sys.exit(main())
