#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据: 配置中心「📋 任务配置」点 TASK-xx ⇒ ① 任务级元任务表换成该任务的 ② 功能级元任务表对应过滤。
老倪 2026-10-28: 「TASK-07-AOI 任务的元任务要有对应关系, 点击 TASK0-7 下面的元任务要对应变化」
"""
import os, sys
import json
ROOT = "/home/ubuntu/zmax"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "tools", "gui"))
from PyQt5.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
import veh6_config_page as V

PASS, FAIL = [], []
def chk(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))

p = V.ConfigCenterPage()
tt, mt, tl, sg = p.tasks_table, p.meta_table, p.tl_table, p.seg_table
print("任务 %d 行 / 功能级元任务 %d 行 / 任务级元任务 %d 行" % (tt.rowCount(), mt.rowCount(), tl.rowCount()))
print("首屏 任务级头部:", p.tl_head.text())

base = sum(1 for i in range(mt.rowCount()) if not mt.isRowHidden(i))
chk("功能级全表 77 条可见", base == 77, f"{base}")

seen = {}
for r in range(tt.rowCount()):
    tid = tt.item(r, 0).text()
    tt.clearSelection(); tt.selectRow(r); app.processEvents()
    vis = sum(1 for i in range(mt.rowCount()) if not mt.isRowHidden(i))
    tlrows = tl.rowCount()
    first = tl.item(0, 1).text() if tlrows else "—"
    ids = [tl.item(i, 1).text() for i in range(min(6, tlrows))]
    seen[tid] = (vis, tlrows, tuple(ids))
    print(f"{tid:14s} 功能级可见 {vis:2d} | 任务级 {tlrows:2d} 条 {ids} | 首行 {first[:20]}")
    chk(f"{tid} 功能级有过滤({vis}<77)", vis < 77, f"{vis}/77")
    chk(f"{tid} 任务级元任务非空且随任务变", tlrows > 0)
    chk(f"{tid} 头部写明该任务", tid in p.meta_head.text() and tid in p.tl_head.text())

uniq = len({v[2] for v in seen.values()})
chk("8 个任务的元任务序列互不相同", uniq == len(seen), f"{uniq}/{len(seen)} 种")

# TASK-07-AOI 专项: 必须是 tasks.json 登记的 7 条, 且带手别/时空窗/目标对象 + 段级明细
p._filter_meta_tasks("TASK-07-AOI"); app.processEvents()
aoi_ids = [tl.item(i, 0).text() for i in range(tl.rowCount())]
aoi_names = [tl.item(i, 1).text() for i in range(tl.rowCount())]
aoi_hands = [tl.item(i, 2).text() for i in range(tl.rowCount())]
print("\nTASK-07-AOI 任务级元任务:")
for i in range(tl.rowCount()):
    print("  ", [tl.item(i, c).text() if tl.item(i, c) else "" for c in range(tl.columnCount())])
chk("TASK-07-AOI 元任务 7 条 (右手5 + 左手1 + 双手1)",
    aoi_ids == ["MT-01", "MT-02", "MT-03", "MT-04", "MT-05", "MT-06", "MT-07"]
    and aoi_hands == ["右手"] * 5 + ["左手", "双手"], "%s / %s" % (aoi_ids, aoi_hands))
chk("TASK-07-AOI 含 AOI 五点检测", any("AOI" in n or "五点" in n for n in aoi_names), str(aoi_names))
chk("名称写全 (含被操作的槽/孔/点位)", any("孔" in n for n in aoi_names) and any("金手指" in n for n in aoi_names))
chk("真源标注 = tasks.json meta_tasks", "meta_tasks" in p.tl_src.text(), p.tl_src.text())
hdr2 = [tl.horizontalHeaderItem(c).text() for c in range(tl.columnCount())]
chk("任务级表有『手别』列", "手别" in hdr2, " | ".join(hdr2))
chk("任务级表有『时空窗』与『目标对象』列", "时空窗" in hdr2 and "目标对象" in hdr2)
twin = [tl.item(i, hdr2.index("时空窗")).text() for i in range(tl.rowCount())]
tgt = [tl.item(i, hdr2.index("目标对象")).text() for i in range(tl.rowCount())]
chk("右手 5 条都有实测时空窗 (0→2.83s 等)", all("→" in twin[i] and "s" in twin[i] for i in range(5)), str(twin[:5]))
chk("左/右手目标对象具体 (槽/孔/金手指点/侧面点/下料盘/废料盘)",
    any("槽" in t for t in tgt) and any("孔" in t for t in tgt) and any("下料盘" in t for t in tgt), str(tgt))
# 段级明细联动: 点 MT-03 ⇒ 10 段 5 个点; 点 MT-01 ⇒ 9 段
def _pick(i):
    tl.selectRow(i); app.processEvents(); app.processEvents()
    return [[sg.item(r, c).text() if sg.item(r, c) else "" for c in range(sg.columnCount())] for r in range(sg.rowCount())]
rows3 = _pick(2)
chk("段级明细: MT-03 = 10 段", len(rows3) == 10, "%d 段" % len(rows3))
chk("段级明细: MT-03 覆盖 金手指点 + 侧面点0..3",
    sorted({r[2] for r in rows3 if "点" in r[2]}) == ["侧面点0", "侧面点1", "侧面点2", "侧面点3", "金手指点"],
    str(sorted({r[2] for r in rows3})))
rows1 = _pick(0)
chk("段级明细: MT-01 = 9 段 (取料→插入)", len(rows1) == 9, "%d 段" % len(rows1))
chk("段级明细: MT-01 时间累计递增", [float(r[5].rstrip("s")) for r in rows1 if r[5].endswith("s")] ==
    sorted(float(r[5].rstrip("s")) for r in rows1 if r[5].endswith("s")))
chk("段级明细: 手别列 = 该元任务手别", all(r[3] == "右手" for r in rows1), str({r[3] for r in rows1}))
rows6 = _pick(5)
chk("段级明细: MT-06 (左臂摆盘) 5 段 手别=左手", len(rows6) == 5 and all(r[3] == "左手" for r in rows6),
    "%d 段 / %s" % (len(rows6), {r[3] for r in rows6}))
print("AOI 头部:", p.meta_head.text().replace("\n", " "))
print("AOI 说明:", p.tl_head.text())

# 归属列存在且口径正确
hdr = [mt.horizontalHeaderItem(c).text() for c in range(mt.columnCount())]
chk("功能级表有『归属』列", "归属" in hdr, " | ".join(hdr))
ci = hdr.index("归属")
vals = {}
for i in range(mt.rowCount()):
    v = mt.item(i, ci).text()
    vals[v] = vals.get(v, 0) + 1
print("归属分布:", vals)
chk("归属分档 (全 8 共用 / N 任务共用 / 无任务)", "全 8 任务共用" in vals and "— 无任务接入" in vals, str(vals))

# 恢复全部 + 再看别人 (回归)
p._filter_meta_tasks(None); app.processEvents()
chk("显示全部恢复 77", sum(1 for i in range(mt.rowCount()) if not mt.isRowHidden(i)) == 77)

# 像素证据: 选中 TASK-07-AOI 的整页截图 (老倪会把画面当结果)
try:
    for r in range(tt.rowCount()):
        if tt.item(r, 0).text() == "TASK-07-AOI":
            tt.selectRow(r)
    app.processEvents()
    p.resize(1700, 1200)
    p.show()                      # 不 show() 时布局是陈旧的, 截出来不是真实画面
    for _ in range(8):
        app.processEvents()
    out = os.path.join(ROOT, "docs/eval/task_meta_link_TASK-07-AOI.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    i = p._tab_index_by_title("任务配置")
    p.tabs.setCurrentIndex(i)
    app.processEvents()
    p.tabs.widget(i).grab().save(out)
    chk("AOI 截图已生成", os.path.exists(out) and os.path.getsize(out) > 20000, out)
except Exception as e:                                                          # noqa: BLE001
    chk("AOI 截图已生成", False, repr(e))

# 根因回归: task_build.py 整份重写 tasks.json 时必须**保留**手写元任务 (2026-10-28 修复)
try:
    import subprocess
    tkj = os.path.join(ROOT, "config", "tasks", "tasks.json")
    before = json.load(open(tkj, encoding="utf-8"))
    b7 = next(t for t in before["tasks"] if t["task_id"] == "TASK-07-AOI").get("meta_tasks") or []
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "task_build.py")],
                       cwd=ROOT, capture_output=True, text=True)
    after = json.load(open(tkj, encoding="utf-8"))
    a7 = next(t for t in after["tasks"] if t["task_id"] == "TASK-07-AOI").get("meta_tasks") or []
    chk("task_build 重跑后 meta_tasks 仍在 (根因已堵)", a7 and [m["id"] for m in a7] == [m["id"] for m in b7],
        "重跑前 %d 条 / 重跑后 %d 条" % (len(b7), len(a7)))
    chk("task_build 重跑不丢 long_horizon",
        bool(next(t for t in after["tasks"] if t["task_id"] == "TASK-07-AOI").get("long_horizon")))
    rc = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "task_build.py"), "--check"],
                        cwd=ROOT, capture_output=True, text=True).returncode
    chk("task_build --check 与真源一致", rc == 0, "rc=%d" % rc)
except Exception as e:                                                          # noqa: BLE001
    chk("task_build 重跑后 meta_tasks 仍在 (根因已堵)", False, repr(e))

print("\n=== %d PASS / %d FAIL ===" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
