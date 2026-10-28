#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 AR 300UPH 的全部交付件归集到 zmax_data/deliverables/2026-10-28-AR300UPH/

清单 (每一件都指向仓内唯一依据, 不做第二份真相):
  01_元任务/       ar_meta_tasks.json + 元任务组合快照
  02_四类配置/     config_meta.json(77功能) / active_models.json / zmax_perf_spec.json / zmax_platform.json / ss_task_binding.json
  03_工单/         BS_SCN-07-AOI.json
  04_文档/         立项文档.docx / SOR.docx + .md / 性能对账.json + .md
  05_规划/         MODEL_PLAN_2027_2028.md + .docx (在 model_plan_2027/)
  06_迁移/         push_ar300_to_550c.sh + 生成器脚本
  DELIVERY.md      交付清单 (含 sha256 + 唯一依据路径 + 复现命令)
"""
import hashlib
import json
import os
import shutil
import time

ROOT = "/home/ubuntu/zmax"
OUT = "/home/ubuntu/zmax_data/deliverables/2026-10-28-AR300UPH"
TS = time.strftime("%Y-%m-%d %H:%M:%S")

GROUPS = {
    "01_元任务": [
        ("data/database/zmax/sources/config/tasks/ar_meta_tasks.json", "ar_meta_tasks.json"),
        ("data/database/zmax/sources/config/tasks/tasks.json", "tasks.json"),
    ],
    "02_四类配置": [
        ("data/database/zmax/config_meta.json", "config_meta_77功能.json"),
        ("models/active_models.json", "active_models.json"),
        ("data/database/zmax/sources/config/platform/zmax_perf_spec.json", "zmax_perf_spec.json"),
        ("data/database/zmax/sources/config/platform/zmax_platform.json", "zmax_platform.json"),
        ("data/database/zmax/sources/config/ss_task_binding.json", "ss_task_binding.json"),
        ("data/database/zmax/sources/canvas/state_space_obs.json", "state_space_obs.json"),
    ],
    "03_工单": [
        ("config/orders/BS_SCN-07-AOI.json", "BS_SCN-07-AOI.json"),
        ("flows/scenes_5jobs.json", "scenes_5jobs.json"),
    ],
    "06_迁移": [
        ("tools/push_ar300_to_550c.sh", "push_ar300_to_550c.sh"),
        ("tools/ar300_config.py", "ar300_config.py"),
        ("tools/ar300_workorder.py", "ar300_workorder.py"),
        ("tools/ss_meta_task_ar.py", "ss_meta_task_ar.py"),
        ("src/lerobot/engineering/nodes/plan_long_impl.py", "plan_long_impl.py"),
        ("src/lerobot/engineering/nodes/uph_tact_impl.py", "uph_tact_impl.py"),
    ],
}

DOCS = [
    ("outputs/project_docs", "*PRJ*"),
    ("outputs/sor", "SOR-*"),
]
PERF = "docs/deliverables/摆盘性能对账_5.50.758"


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()[:16]


def newest(pattern_dir, prefix):
    d = os.path.join(ROOT, pattern_dir)
    if not os.path.isdir(d):
        return []
    out = []
    for sub in sorted(os.listdir(d)):
        p = os.path.join(d, sub)
        if not os.path.isdir(p):
            continue
        for f in os.listdir(p):
            if f.startswith(prefix):
                out.append(os.path.join(p, f))
    return sorted(out, key=os.path.getmtime)[-2:]


def main():
    os.makedirs(OUT, exist_ok=True)
    rows = []
    for g, items in GROUPS.items():
        gd = os.path.join(OUT, g)
        os.makedirs(gd, exist_ok=True)
        for rel, name in items:
            src = os.path.join(ROOT, rel)
            if not os.path.exists(src):
                rows.append((g, name, "❌ 缺", rel, "-"))
                continue
            dst = os.path.join(gd, name)
            shutil.copy2(src, dst)
            rows.append((g, name, "%.1f KB" % (os.path.getsize(dst) / 1024), rel, sha(dst)))

    # 文档
    dd = os.path.join(OUT, "04_文档")
    os.makedirs(dd, exist_ok=True)
    for d, pre in DOCS:
        for p in newest(d, pre.split("*")[0]):
            dst = os.path.join(dd, os.path.basename(p))
            shutil.copy2(p, dst)
            rows.append(("04_文档", os.path.basename(p), "%.1f KB" % (os.path.getsize(dst) / 1024),
                         os.path.relpath(p, ROOT), sha(dst)))
    for ext in (".json", ".md"):
        p = os.path.join(ROOT, PERF + ext)
        if os.path.exists(p):
            dst = os.path.join(dd, os.path.basename(p))
            shutil.copy2(p, dst)
            rows.append(("04_文档", os.path.basename(p), "%.1f KB" % (os.path.getsize(dst) / 1024),
                         os.path.relpath(p, ROOT), sha(dst)))

    # 规划
    pd = os.path.join(OUT, "05_规划")
    os.makedirs(pd, exist_ok=True)
    for f in ("MODEL_PLAN_2027_2028.md", "MODEL_PLAN_2027_2028.docx", "data.json", "build_doc.py"):
        p = os.path.join("/home/ubuntu/zmax_data/deliverables/model_plan_2027", f)
        if os.path.exists(p):
            dst = os.path.join(pd, f)
            shutil.copy2(p, dst)
            rows.append(("05_规划", f, "%.1f KB" % (os.path.getsize(dst) / 1024), p, sha(dst)))

    # DELIVERY.md
    L = ["# AR 300UPH · 交付清单", "",
         "生成 %s · 产品档位 550A(本机开发) → 550C(Intel 工厂执行) · 真机零指令" % TS, "",
         "| 组 | 文件 | 大小 | 唯一依据 | sha256(16) |", "|---|---|---|---|---|"]
    for g, n, sz, src, h in rows:
        L.append("| %s | %s | %s | `%s` | %s |" % (g, n, sz, src, h))
    L += ["", "## 复现命令", "```bash",
          "python3 tools/ar300_config.py        # ① 功能/模型/性能/工程 四类配置 (幂等, 自带 5 项判据)",
          "python3 tools/ss_meta_task_ar.py     # ② 元任务组合 → TASK-07-AOI (392 段逐段校验)",
          "python3 tools/ar300_workorder.py     # ③ 场景唯一依据 → 工单 BS_SCN-07-AOI (10 项判据)",
          "python3 tools/project_doc_export.py  # ④ 立项文档 Word",
          "python3 tools/sor_export.py --task TASK-07-AOI   # ⑤ 供应商 SOR",
          "bash tools/push_ar300_to_550c.sh     # ⑥ 增量迁移 Intel 550C (19 文件 + 回读 8 项)",
          "```", "",
          "## 关键数字 (实测)", "",
          "| 项 | 值 |", "|---|---|",
          "| 一轮 | 392 段 / 14 件 / 159.43 s |",
          "| 节拍 | 11.42 s/件 (几何 315 UPH) · 目标 300 |",
          "| 元任务 | 5 模板 / 56 实例 (126+70+140+48+8) |",
          "| 功能 | 77 (新增 FN-PLAT-76 长程元任务编排 / FN-PLAT-77 UPH 节拍循环器) |",
          "| 工单 | 9 份, SCN-07-AOI 含 ar_300uph 段 |",
          "| 双臂 | 左臂摆盘 + 右臂插拔/AOI 五点 |",
          "| 真机 | real_cmd=false · 全程 AR 仿真 |"]
    open(os.path.join(OUT, "DELIVERY.md"), "w", encoding="utf-8").write("\n".join(L))

    print("✅ 归集目录: %s" % OUT)
    for g in sorted({r[0] for r in rows}):
        n = len([r for r in rows if r[0] == g])
        print("   %-10s %d 件" % (g, n))
    miss = [r for r in rows if r[2] == "❌ 缺"]
    print("   合计 %d 件, 缺 %d" % (len(rows), len(miss)))
    if miss:
        for r in miss:
            print("     ❌ %s ← %s" % (r[1], r[3]))
    return 0 if not miss else 1


if __name__ == "__main__":
    raise SystemExit(main())
