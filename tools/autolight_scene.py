#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
autolight_scene.py — 把 /autoLight#c1 (光纤端面检测设备 · 待测物料缓存仓一) 构想成
Z-MAX 状态空间工程里的**真场景 + 真任务**，并做全链自检。

链路（每一步都是真源，不手改生成物）:
  flows/scenes_5jobs.json  ← 插 SCN-08-AL1 (本文件构建, 幂等)
      ↓ tools/task_build.py            (场景 × 配方 PLAN → 任务真源)
  config/tasks/tasks.json            → TASK-08-AL1
      ↓ tools/ss_task_bind.py          (任务 × 画布 → 绑定真源 + 激活)
  config/ss_task_binding.json        (active_task = TASK-08-AL1)
      ↓ tools/scene_registry.py --build(场景库: objects3d + overlay_spec)
  data/scene/scenes/SCN-08-AL1/*.json

用法:
  python tools/autolight_scene.py --check     # 只查, 不写
  python tools/autolight_scene.py --build     # 写场景真源 + 重建任务/绑定/场景库
  python tools/autolight_scene.py --build --no-activate
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
JOBS = os.path.join(ROOT, "flows", "scenes_5jobs.json")
TASKS = os.path.join(ROOT, "config", "tasks", "tasks.json")
BIND = os.path.join(ROOT, "config", "ss_task_binding.json")
SCENES = os.path.join(ROOT, "data", "scene", "scenes")

SCENE_ID = "SCN-08-AL1"
TASK_ID = "TASK-08-AL1"

# ───────────────────── 场景真源 (坐标 = /autoLight 第 1 张卡的 base 世界系, 米) ─────────────────────
SCENE = {
    "scene_id": SCENE_ID,
    "scene_type": "al1_cache",
    "name": "光纤端面检测 · 上料缓存工位 (人工上料→缓存1→缓存2→主流线)",
    "desc": ("光纤端面检测及清理自动化设备(技协 rev1.0 §2.2 第 1~3 步)的物料流转起点: "
             "人工把载具(托盘)放到人工放料位, 推料模组推入缓存1; 缓存1 满后推至缓存2; "
             "缓存2 移栽模组推入主流线缓存位, 顶升模组顶升、分离模组伸出接料"),
    "goal": "载具按序进入主流线检测位, 产品码↔载具码绑定, 缓存不堆料",
    "targets": {
        "来料": "MPO-8FC / MPO-16FC, 载具承载 1PCS/载具",
        "载具托盘缓存": "≤15PCS",
        "节拍 8-FC": "CT ≤70s / UPH ≥51 / OEE ≥85% (对焦2S+测试2S, 接头一次通过)",
        "节拍 16-FC": "CT ≤134s / UPH ≥26 / OEE ≥85% (全端面对焦2S+测试2S)",
        "定位": "定位轴套×2 + 夹具初定位销 + 磁吸板×2 自动锁附; 浮动 XY 单边 0.5mm",
        "追溯": "产品二维码 ↔ 载具二维码 (产品—载具—工位—结果)",
    },
    "objects": [
        {"name": "人工取放堆叠架 (人工放料位/人工下料位/缓存1/缓存2)",
         "pos": [-1.47, 0.0, 1.08], "size_mm": [260, 440, 440],
         "role": "料仓/料盘取件位 (真源: /autoLight#c1 场景几何)"},
        {"name": "推料模组 (气缸 + 推板)",
         "pos": [-1.32, 0.0, 1.08], "size_mm": [200, 120, 120],
         "role": "推料执行器 (推入缓存1 / 缓存1→缓存2)"},
        {"name": "载具托盘 (1PCS 载具 · 磁吸板×2 · 定位轴套×2 · 盖帽暂存位)",
         "pos": [-1.12, 0.0, 0.883], "size_mm": [300, 200, 16],
         "role": "治具/载具托盘 (浮动 XY 单边 0.5mm)"},
        {"name": "MPO-16FC 光纤 (MPO 端 + 16 FC 端)",
         "pos": [-1.20, 0.0, 0.900], "size_mm": [120, 160, 12],
         "role": "光模块单颗 (端面待检/待清洗)"},
        {"name": "缓存仓一 (待测物料)",
         "pos": [-1.06, -0.18, 0.960], "size_mm": [200, 160, 200],
         "role": "料盘缓存位 缓存1"},
        {"name": "缓存仓二 (待测物料)",
         "pos": [-0.90, -0.18, 0.960], "size_mm": [160, 160, 200],
         "role": "料盘缓存位 缓存2"},
        {"name": "载具搬运流线 (载具托盘分离组件 + 顶升组件)",
         "pos": [0.14, 0.0, 0.837], "size_mm": [2160, 150, 55],
         "role": "输送线 (为载具流转提供动力, 各工站顶升至检测位)"},
        {"name": "扫码绑定位 (产品二维码 ↔ 载具二维码)",
         "pos": [-1.30, -0.30, 1.060], "size_mm": [80, 80, 120],
         "role": "识别/扫码 (全链路追溯起点)"},
    ],
    "steps": [
        {"t": 0.0, "dur": 1.2, "name": "人工上料", "metric": "perf.load_ok", "force": None,
         "desc": "人工将载具（托盘）上料至人工放料位 (1PCS/载具)"},
        {"t": 1.2, "dur": 1.0, "name": "推入缓存1", "metric": "perf.cache_in", "force": None,
         "desc": "推料模组把载具推入缓存1, 到位传感器确认"},
        {"t": 2.2, "dur": 1.0, "name": "缓存排队", "metric": "perf.cache_q", "force": None,
         "desc": "缓存1 满后推料模组将载具推至缓存2, 等待进入主流线 (缓存 ≤15PCS)"},
        {"t": 3.2, "dur": 1.2, "name": "主流线交接", "metric": "perf.handover", "force": None,
         "desc": "缓存2 移栽模组推入主流线缓存位; 主流线顶升模组顶升, 分离模组伸出接料"},
        {"t": 4.4, "dur": 0.8, "name": "扫码绑定", "metric": "perf.bind", "force": None,
         "desc": "产品二维码与载具二维码扫码绑定 (产品—载具—工位—结果)"},
        {"t": 5.2, "dur": 1.0, "name": "节拍与循环", "metric": "perf.cycle_s", "force": None,
         "desc": "单载具循环; 8-FC CT ≤70s / 16-FC CT ≤134s; OEE ≥85%"},
    ],
    "performance": {"tact_time": 70.0, "cycle_s": 70.0, "positioning_accuracy": 0.0005,
                    "float_mm": 0.5, "cache_max": 15},
    "perf_metrics": ["perf.load_ok", "perf.cache_in", "perf.cache_q", "perf.handover",
                     "perf.bind", "perf.cycle_s"],
    "editable_scene": True,
}


def _run(args, tag=""):
    r = subprocess.run([PY] + args, cwd=ROOT, capture_output=True, text=True, timeout=1800)
    out = (r.stdout or "") + (r.stderr or "")
    print("── %s rc=%d" % (tag or " ".join(args), r.returncode))
    for ln in out.strip().splitlines()[-14:]:
        print("   " + ln)
    return r.returncode, out


def scenes_doc():
    with open(JOBS, encoding="utf-8") as f:
        return json.load(f)


def have_scene():
    return any(s.get("scene_id") == SCENE_ID for s in scenes_doc().get("scenes") or [])


def insert_scene():
    d = scenes_doc()
    if any(s.get("scene_id") == SCENE_ID for s in d.get("scenes") or []):
        # 幂等: 内容不同则原地替换
        for i, s in enumerate(d["scenes"]):
            if s.get("scene_id") == SCENE_ID:
                if s != SCENE:
                    d["scenes"][i] = SCENE
                    _write_jobs(d)
                    return "updated"
                return "unchanged"
    d.setdefault("scenes", []).append(SCENE)
    _write_jobs(d)
    return "added"


def _write_jobs(d):
    tmp = JOBS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, JOBS)


def snapshot_scenes():
    ts = time.strftime("%Y%m%d_%H%M%S")
    out = "/tmp/al_scene_bak_%s.tar.gz" % ts
    if os.path.isdir(SCENES):
        with tarfile.open(out, "w:gz") as tf:
            tf.add(SCENES, arcname="scenes")
    return out


def dir_hashes():
    h = {}
    for sid in sorted(os.listdir(SCENES)):
        p = os.path.join(SCENES, sid)
        if not os.path.isdir(p):
            continue
        for fn in sorted(os.listdir(p)):
            fp = os.path.join(p, fn)
            if os.path.isfile(fp):
                import hashlib
                h["%s/%s" % (sid, fn)] = hashlib.sha256(open(fp, "rb").read()).hexdigest()[:16]
    return h


def check():
    ok = True
    has = have_scene()
    print(("✅" if has else "❌") + " flows/scenes_5jobs.json 含 %s (%d 个场景)"
          % (SCENE_ID, len(scenes_doc().get("scenes") or [])))
    ok &= has
    if os.path.isfile(TASKS):
        t = json.load(open(TASKS, encoding="utf-8"))
        ids = [x.get("task_id") for x in t.get("tasks") or []]
        hit = TASK_ID in ids
        print(("✅" if hit else "❌") + " config/tasks/tasks.json 含 %s (共 %d 任务)" % (TASK_ID, len(ids)))
        ok &= hit
        row = next((x for x in t["tasks"] if x.get("task_id") == TASK_ID), {}) or {}
        if row:
            print("     场景=%s 类型=%s 段=%d 覆盖=%d" % (row.get("scene_ref"), row.get("recipe_type"),
                                                     len(row.get("applies_segments") or []),
                                                     len(row.get("overrides") or {})))
    if os.path.isfile(BIND):
        b = json.load(open(BIND, encoding="utf-8"))
        ids = [x.get("task_id") for x in b.get("tasks") or []]
        print(("✅" if TASK_ID in ids else "❌") + " 绑定含 %s · active_task=%s"
              % (TASK_ID, b.get("active_task")))
        ok &= TASK_ID in ids
    d = os.path.join(SCENES, SCENE_ID)
    files = sorted(os.listdir(d)) if os.path.isdir(d) else []
    print(("✅" if "objects3d.json" in files and "overlay_spec.json" in files else "❌")
          + " 场景库 %s → %s" % (SCENE_ID, files))
    ok &= "objects3d.json" in files
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--no-activate", action="store_true")
    a = ap.parse_args()
    if not a.build:
        sys.exit(0 if check() else 2)

    bak = snapshot_scenes()
    before = dir_hashes() if os.path.isdir(SCENES) else {}
    print("📦 场景库快照 → %s" % bak)

    print("① 场景真源 flows/scenes_5jobs.json : %s" % insert_scene())
    rc1, _ = _run(["tools/task_build.py"], "task_build")
    if rc1 != 0:
        print("⛔ task_build 失败"); return rc1
    rc2, _ = _run(["tools/ss_task_bind.py"] + ([] if a.no_activate else ["--activate", TASK_ID]),
                  "ss_task_bind")
    if rc2 != 0:
        print("⛔ ss_task_bind 失败"); return rc2
    rc3, _ = _run(["tools/scene_registry.py", "--build"], "scene_registry")
    if rc3 != 0:
        print("⛔ scene_registry 失败"); return rc3

    # 回滚保护: 只允许 SCN-08-AL1 与 index.json 变化
    after = dir_hashes()
    changed = [k for k, v in after.items() if before.get(k) not in (None, v) and not k.startswith(SCENE_ID)]
    if changed:
        print("⚠️ 其它场景被动改动 %d 个文件 → 从快照还原: %s" % (len(changed), changed[:5]))
        for k in changed:
            with tarfile.open(bak) as tf:
                try:
                    m = tf.getmember("scenes/" + k)
                except KeyError:
                    continue
                m.name = "scenes/" + k
                tf.extract(m, path="/tmp/_al_restore")
            src = "/tmp/_al_restore/scenes/" + k
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(SCENES, k))

    ok = check()
    print("\n%s" % ("✅ 场景/任务/绑定/场景库四件齐" if ok else "❌ 有缺失, 见上"))
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
