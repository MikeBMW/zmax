#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aoi_task_landing.py — 配置中心「任务7 = AOI」落库 (场景真源 + 配方计划 + 任务配置)

老倪 2026-10-11 指令 (逐字):
    「在配置中心，增加任务7,对应 AOI 任务，场景就对应 AR, 模型对应 Automated Optical Inspection
      自动光学检测 的 L5 自主进化程序」

链路 (与 tools/task_build.py 同源, 不另造一份真源):
    flows/scenes_5jobs.json  ← 新增场景 SCN-07-AOI (scene_type=ar_aoi, 场景=AR)
                             ← 同时**补回** SCN-06-TRAY (2026-08 被 SCN-07-UP 顶掉, 而 tasks.json 里
                                一直是任务6 ⇒ 「生成器与真源不一致」的根因; 不补, 一重生成任务6就消失)
    tools/task_build.py      ← 新增 PLAN["ar_aoi"] (任务类型/适用段/覆盖参数/model_ref = L5 自主进化程序)
                             ← 无配方计划(PLAN)的场景**不再静默套 ATS 配方**, 改为跳过并打印提示
    config/tasks/tasks.json  ← 由 task_build 真生成器重写: 任务1..6 逐字节不变 + 任务7 = TASK-07-AOI

判据 (硬): ① 任务1..6 生成结果与旧文件逐字节一致 ② 任务7 = TASK-07-AOI ③ `task_build.py --check` ✅
用法: python3 tools/aoi_task_landing.py [--check]   (--check = 只核验, 不写任何文件)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
SCENES = os.path.join(ROOT, "flows", "scenes_5jobs.json")
TASKS = os.path.join(ROOT, "config", "tasks", "tasks.json")
TASK_BUILD = os.path.join(ROOT, "tools", "task_build.py")

# ─────────────────────────── 场景 6: 光模块摆盘 (补回, 真源 = 现 tasks.json 任务6 + data/scene/SS-TRAY-PLACE) ───
TRAY_SCENE = {
    "scene_id": "SCN-06-TRAY",
    "scene_type": "tray_filling",
    "name": "光模块摆盘 (周转盘 → 上料 Tray 盘)",
    "desc": "满料周转盘 → 上料 Tray 盘单颗取放 (真空吸盘); 与产线摆盘工艺同口径",
    "goal": "摆盘取放 + 单颗 CT ≤3.15s (PVT)",
    "targets": {
        "单颗CT": "≤3.15s (PVT)",
        "成功率": "≥99% (PVT)",
        "取放精度": "单边 ≤1mm / ≤1°",
        "连续": "≥12 盘周转盘",
    },
    "objects": [
        {"name": "光模块单颗", "pos": [0.9, -0.3, 0.82], "size_mm": [18, 9, 4],
         "role": "物料单颗·100G/400G/800G · 12+ 型号"},
    ],
    "steps": [
        {"t": 0.0, "dur": 2.0, "name": "定位识别",
         "desc": "全局定位相机识别满料周转盘位置与堆叠层数、空 Tray 盘位置、工装位置; 取 1 盘周转盘到作业工装"
                 "并二次拍照, 识别盘内光模块数量与坐标、Tray 空槽数量与坐标", "force": None},
        {"t": 2.0, "dur": 0.6, "name": "取件",
         "desc": "腕部相机对准目标光模块, 末端下降至吸附位, 真空建立(≤200ms)后抬起离盘", "force": None},
        {"t": 2.6, "dur": 1.0, "name": "转运对位",
         "desc": "沿安全轨迹转移至目标 Tray 槽位上方, 姿态对准槽口方向, 粗定位后 XYZ/姿态微调", "force": None},
        {"t": 3.6, "dur": 0.8, "name": "放入",
         "desc": "下降到放置面, 断真空释放光模块; 放置下压不超过配方上限, 姿态偏差 ≤1°", "force": None},
        {"t": 4.4, "dur": 0.3, "name": "判态循环",
         "desc": "判断周转盘是否空、Tray 盘是否满; 未满且盘未空则回到取件; 触发上报则暂停待人工补料/下料",
         "force": None},
    ],
    "performance": {"force_limit": 2.0, "tact_time": 3.15, "positioning_accuracy": 0.001,
                    "vacuum_establish_ms": 200, "place_angle_tol_deg": 1.0},
}

# ─────────────────────────── 场景 7: AR 光学质量检测 (新, 老倪 2026-10-11) ───
# 坐标全部取自真源: 示教点位 reports/aoi_points/*.json (ROKAE SDK 直读); 相机/深度/判决 = AR 服务 :8797 实测
AR_SCENE = {
    "scene_id": "SCN-07-AOI",
    "scene_type": "ar_aoi",
    "name": "AR 光学质量检测 (AOI 联合检查)",
    "desc": "AR 场景: RealSense D435 实拍为底图, 叠加三层虚拟信息 (工控机 AOI 联合检查 10082/10083 · "
            "光模块检测在役权重 · 相机系 3D 位姿); 判据图可导出",
    "goal": "把 AOI 光学质量检测落到 AR 实拍画面上, 与产线 AOI (10082 金手指 / 10083 表面) 同口径",
    "targets": {
        "缺陷检出": "与产线 AOI 同口径 (10082 金手指 / 10083 表面)",
        "判决": "PASS/FAIL + 缺陷数 (工控机 /capture_detect → GET /last_result)",
        "金手指矩形": "位置/尺寸/倾角 (实测 363.8×17.5px · 倾角 1.75°)",
        "侧边位置修正": "Δx = +4.0px (实测, 一次给全)",
        "位置精修": "手眼 TSAI 闭环 1.74mm",
        "判据图": "900×332 可导出 (reports/aoi_console_state.json 留痕)",
    },
    "objects": [
        {"name": "光模块单颗", "pos": None, "size_mm": [18, 9, 4],
         "role": "物料单颗·AR 实拍视野内 (基座系位置待标定; RealSense 工作区距离实测 1.000m · 有效深度 93.7%)"},
        {"name": "金手指点1 (示教位姿)", "pos": [0.489774, 0.1473783, 0.4054162], "size_mm": None,
         "role": "示教点位·金手指 (真源 reports/aoi_points/金手指点1.json · ROKAE SDK 直读 endInRef)"},
        {"name": "侧面点0 (表面检测观察位)", "pos": [0.3897588, -0.4181877, 0.4869425], "size_mm": None,
         "role": "示教点位·侧面观察位 (真源 reports/aoi_points/侧面点0.json)"},
        {"name": "安全点1", "pos": [0.377606, 0.0423738, 0.3621157], "size_mm": None,
         "role": "示教点位·安全 (真源 reports/aoi_points/安全点1.json · 距金手指点1 159.6mm)"},
    ],
    "steps": [
        {"t": 0.0, "dur": 0.5, "name": "AR 取像",
         "desc": "RealSense D435 实拍 640×480 作 AR 底图 (深度 1mm 尺度 · 工作区有效深度 93.7% · 自动曝光)",
         "force": None},
        {"t": 0.5, "dur": 1.8, "name": "AOI 联合检查",
         "desc": "工控机 AOI 10082 (金手指) 触发拍照检测 → 判据图 + 金手指矩形搜索 (位置/尺寸/倾角) + "
                 "侧边位置修正 Δx 一次拿全; 10083 (表面) 同口径", "force": None},
        {"t": 2.3, "dur": 0.4, "name": "光模块检测",
         "desc": "在役权重 models/yolo_peg_live.pt 在 AR 帧上检测 (conf/imgsz 可调, 检出即给像素坐标)",
         "force": None},
        {"t": 2.7, "dur": 0.3, "name": "位姿叠加",
         "desc": "相机系 3D 位姿: 深度反投影 + 平面拟合 (RMS 留痕), 虚拟坐标架画回实拍; 手眼 TSAI 闭环 1.74mm",
         "force": None},
        {"t": 3.0, "dur": 0.3, "name": "判决与上报",
         "desc": "判决 PASS/FAIL + 缺陷数; 判据图导出; AOI 全部话题经 ar_aoi_bus 发到信号分析页 (来源 ar.)",
         "force": None},
    ],
    "performance": {"tact_time": 3.6, "positioning_accuracy": 0.001, "depth_valid_ratio": 0.937,
                    "plane_rms_mm": 101.39, "aoi_infer_ms": 1715},
}

PLAN_ENTRY = '''    "ar_aoi": dict(
        task_type="光学质量检测",
        # 检测型任务: 只用到 来料状态/识别对接/分拣回位/节拍 四段 (取件/姿态/插拔不适用)
        applies=["0 料源与来料状态", "3 识别与工位对接", "6 分拣与回位", "7 节拍与循环"],
        excluded=["1 取件", "2 姿态准备", "4 放置/插入", "5 拔出/取回"],
        overrides={"aoi.port_gold": 10082, "aoi.port_surface": 10083,
                   "aoi.cam": "RealSense D435 (AR 底图 · 独占 :8797)",
                   "aoi.weights": "models/yolo_peg_live.pt (在役软链)",
                   "aoi.side_fix": "侧边位置修正 Delta x 一次给全",
                   "aoi.judge_png": "判据图 900x332 可导出",
                   "sort.rule": "AOI 判决 PASS/FAIL 累计→NG"},
        trigger="AR 场景就位 (RealSense 有帧) / 工控机 AOI 就绪信号",
        loop="单件循环; 判决 + 判据图落盘后进入下一件",
        orders_rule="1 件 = 1 条记录 (判据图 + 判决 + 时间戳)",
        # 老倪: 「模型对应 Automated Optical Inspection 自动光学检测 的 L5 自主进化程序」
        model_ref={"layer": "L5",
                   "program": "Automated Optical Inspection 自动光学检测 · L5 自主进化程序",
                   "entry": "tools/l5_plan_and_gen.py + tools/aoi_link.py (工控机 10082/10083 客户端)",
                   "charter": "docs/L5_AUTONOMOUS_EVOLUTION.md",
                   "node": "🔍 光学质量检测 (画布节点 · 发出 AOI 全部话题)",
                   "capability": "BO_ B5 光学质量检测"},
        note="AOI: AR 实拍底图 + 工控机 AOI 联合检查 (金手指 10082 / 表面 10083) + 光模块检测 + 相机系 3D 位姿; "
             "不涉及取件/姿态/放置/拔出 ⇒ 配方段 1/2/4/5 不适用; 模型 = L5 自主进化程序"),
'''


def _load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _dump(d):
    return json.dumps(d, ensure_ascii=False, indent=1) + "\n"


def patch_task_build(check=False):
    """给 task_build.py 加 PLAN['ar_aoi'] + 无计划场景不再静默套 ATS 配方。返回 (changed, msgs)"""
    src = open(TASK_BUILD, encoding="utf-8").read()
    msgs, changed = [], False
    if '"ar_aoi": dict(' not in src:
        anchor = "\n}\n\nTIER = {"
        assert anchor in src, "task_build.py 的 PLAN 结尾锚点没找到"
        src = src.replace(anchor, "\n" + PLAN_ENTRY + "}\n\nTIER = {", 1)
        msgs.append("PLAN += ar_aoi (任务类型 光学质量检测 + model_ref L5 自主进化程序)")
        changed = True
    old_build = '''def build(scene, calib, i):
    p = PLAN.get(scene["scene_type"], PLAN["ats_test"])'''
    new_build = '''def build(scene, calib, i):
    p = PLAN.get(scene["scene_type"])
    if p is None:
        # 🚫 无配方计划(PLAN)的场景**不再静默套 ATS 配方** —— 那会造出一条"类型/段/覆盖全错"的任务。
        #    场景照旧留在 scenes_5jobs.json (只读真源), 只是不入任务清单; 要建任务 = 在 PLAN 里加一条。
        return None'''
    if old_build in src:
        src = src.replace(old_build, new_build, 1)
        msgs.append("build(): PLAN 缺失 → 跳过 (原: 静默回落 ATS 配方)")
        changed = True
    old_map = '''    tasks = [build(s, calib, int(s["scene_id"].split("-")[1])) for s in sc]'''
    new_map = '''    tasks, skipped = [], []
    for s in sc:
        t = build(s, calib, int(s["scene_id"].split("-")[1]))
        (tasks.append(t) if t else skipped.append("%s (%s)" % (s["scene_id"], s["scene_type"])))
    if skipped:
        print("⏭ 无配方计划(PLAN), 未入任务清单: " + " · ".join(skipped)
              + "  —— 要建任务请在 tools/task_build.py 的 PLAN 里加一条")'''
    if old_map in src:
        src = src.replace(old_map, new_map, 1)
        msgs.append("main(): 打印被跳过的场景 (不再静默)")
        changed = True
    if '"model_ref": p["model_ref"]' not in src:
        old_ret = '''        "blocked_by_site": gaps, "_note": p["note"],
    }'''
        new_ret = '''        "blocked_by_site": gaps, "_note": p["note"],
    }
    if p.get("model_ref"):            # 任务绑定的模型 (老倪: 任务7 AOI → L5 自主进化程序)
        out["model_ref"] = p["model_ref"]
    return out'''
        assert old_ret in src, "build() 返回块锚点没找到"
        src = src.replace(old_ret, new_ret, 1)
        src = src.replace('''            "tasks": tasks}''', '''            "tasks": tasks}''')
        # 把 return {...} 改成 out = {...}
        src = src.replace('''    return {
        "task_id": f"TASK-{i:02d}-{scene['scene_id'].split('-', 2)[2]}",''',
                          '''    out = {
        "task_id": f"TASK-{i:02d}-{scene['scene_id'].split('-', 2)[2]}",''', 1)
        msgs.append("build(): 支持 model_ref 落库 (无 model_ref 的任务输出不变)")
        changed = True
    if check:
        return changed, msgs, src
    if changed:
        shutil.copy2(TASK_BUILD, TASK_BUILD + ".bak_%s" % time.strftime("%Y%m%d_%H%M%S"))
        with open(TASK_BUILD, "w", encoding="utf-8") as f:
            f.write(src)
    return changed, msgs, src


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    doc = _load(SCENES)
    scenes = doc["scenes"]
    ids = [s["scene_id"] for s in scenes]
    print("场景真源: %s (%d 个) → %s" % (os.path.relpath(SCENES, ROOT), len(scenes), ", ".join(ids)))

    # 1) 场景 6 摆盘补回 (真源被 SCN-07-UP 顶掉 ⇒ 任务6 一重生成就丢)
    if "SCN-06-TRAY" not in ids:
        scenes.insert(5, TRAY_SCENE)
        print("  + 补回场景 SCN-06-TRAY (光模块摆盘) @ index 5")
    # 2) 场景 7 = AR/AOI (老倪的「任务7」)
    if "SCN-07-AOI" not in ids:
        scenes.append(AR_SCENE)
        print("  + 新增场景 SCN-07-AOI (AR 光学质量检测) @ 末位")
    if a.check:
        print("--check: 只核验, 未写盘。")
    else:
        shutil.copy2(SCENES, SCENES + ".bak_%s" % time.strftime("%Y%m%d_%H%M%S"))
        with open(SCENES, "w", encoding="utf-8") as f:
            f.write(_dump(doc))

    # 3) 配方计划
    changed, msgs, _src = patch_task_build(check=a.check)
    for m in msgs:
        print("  * task_build.py:", m)
    if not msgs:
        print("  * task_build.py: 已是目标状态 (幂等)")

    # 4) 重新生成任务配置, 并逐字节核验任务1..6 不变
    old = _load(TASKS)
    import importlib
    import task_build
    importlib.reload(task_build)
    if not a.check:
        rc = task_build.main()
        if rc not in (0, None):
            print("❌ task_build 返回 %s" % rc)
            return rc
    new = _load(TASKS)
    ob = {t["task_id"]: json.dumps(t, ensure_ascii=False, sort_keys=True) for t in old["tasks"]}
    nb = {t["task_id"]: json.dumps(t, ensure_ascii=False, sort_keys=True) for t in new["tasks"]}
    same = [k for k in ob if k in nb and ob[k] == nb[k]]
    diff = [k for k in ob if k in nb and ob[k] != nb[k]]
    gone = [k for k in ob if k not in nb]
    added = [k for k in nb if k not in ob]
    print("\n核验 (任务配置 %d → %d 条):" % (len(ob), len(nb)))
    print("  逐字节不变: %s" % (", ".join(sorted(same)) or "—"))
    print("  ❗变化: %s" % (", ".join(sorted(diff)) or "—"))
    print("  ❗丢失: %s" % (", ".join(sorted(gone)) or "—"))
    print("  + 新增: %s" % (", ".join(sorted(added)) or "—"))
    aoi = [t for t in new["tasks"] if t["task_id"] == "TASK-07-AOI"]
    if aoi:
        t = aoi[0]
        print("\n任务7 = %s · %s · 场景 %s · 类型 %s · 段 %d · 覆盖 %d"
              % (t["task_id"], t["name"], t["scene_ref"], t["recipe_type"],
                 len(t["applies_segments"]), len(t["overrides"])))
        mr = t.get("model_ref") or {}
        print("  模型: %s · %s" % (mr.get("layer"), mr.get("program")))
    ok = (not diff and not gone and "TASK-07-AOI" in [t["task_id"] for t in new["tasks"]]
          and len(same) == len(ob))
    print("\n判据:", "PASS" if ok else "FAIL")
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
