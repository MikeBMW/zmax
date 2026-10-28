#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""📋 把 AR 300UPH 的元任务组合写进工单唯一依据 SCN-07-AOI, 再重生成工单 (工单即任务)

老倪口径 (2026-10-28):
  「最后输出工单; 实际的生产目标是 300UPH, 场景就是 AR 场景的仿真机器人, 左臂摆盘, 右臂插拔和 AOI 检查。
    你要通过这一系列的配置, 能够规范地约束工厂生产, 实现工单即任务, 工单定义好了, 就可以实现真实的 300UPH」

做法:
  ① flows/scenes_5jobs.json 的 SCN-07-AOI: 补 performance(300UPH/12s/双臂) + 用 4 个元任务重写 steps
     + 挂 ar_meta_tasks 引用 (元任务组合唯一依据), 不动 objects/其他场景
  ② 备份 config/orders/ → 跑 tools/build_sheet.py 重生成 9 份工单
  ③ 校验: BS_SCN-07-AOI.json 含 uph_target=300 / 双臂角色 / 元任务步 / 节拍 12s
"""
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = "/home/ubuntu/zmax"
P_SCENES = os.path.join(ROOT, "flows/scenes_5jobs.json")
P_ORDERS = os.path.join(ROOT, "config/orders")
P_META = os.path.join(ROOT, "data/database/zmax/sources/config/tasks/ar_meta_tasks.json")
PY = os.path.join(ROOT, "gui-venv311/bin/python")


def main():
    scenes = json.load(open(P_SCENES, encoding="utf-8"))
    meta = json.load(open(P_META, encoding="utf-8"))
    mt = {m["id"]: m for m in meta["meta_tasks"]}
    lh = meta["long_horizon"]

    s = [x for x in scenes["scenes"] if x.get("scene_id") == "SCN-07-AOI"][0]

    # ── 一件的工序 = 4 个元任务 (拔 → 检 → 放 → 插), 双臂并行由 arm 字段表达 ──
    seq = [("MT-02", "right"), ("MT-03", "right"), ("MT-04", "right"), ("MT-01", "left")]
    steps, t = [], 0.0
    for mid, arm in seq:
        m = mt[mid]
        dur = float(m.get("t_s") or 0.0)
        steps.append({
            "t": round(t, 2), "dur": round(dur, 2), "name": "%s %s" % (mid, m["name"]),
            "desc": m["prompt"], "force": None, "arm": arm,
            "meta_task": mid, "segments": m["segments"],
        })
        t = round(t + dur, 2)
    # 一件 = 28 段; 实测稳态 11.42s (上面 4 个元任务合计即该节拍)
    one_piece_s = round(t, 2)

    s["steps"] = steps
    s["performance"] = {
        "uph_target": lh["uph_target"],
        "tact_s": lh.get("tact_s") or 11.42,
        "tact_target_s": 12.0,
        "one_piece_s": one_piece_s,
        "segments_per_piece": 28,
        "segments_per_round": lh["segments_total"],
        "round_total_s": lh["round_total_s"],
        "modules_per_round": lh.get("meta_count") and 14,
        "yield_target": 0.99,
        "dual_arm": {"left": "摆盘 (料盘 → 治具孔位, MT-01)",
                     "right": "插拔 + AOI 五点检测 (MT-02/03/04/05)"},
        "speed_mm_s": 625.6, "insert_mm": 47.0, "insert_force_n_max": 40.0,
        "note": "几何能力 3600/11.42 = 315 UPH; 设计目标取 300 (=12s/件)",
    }
    s["ar_meta_ref"] = {
        "task_id": "TASK-07-AOI",
        "meta_tasks_file": "data/database/zmax/sources/config/tasks/ar_meta_tasks.json",
        "meta_tasks": {k: {"name": v["name"], "segments": v["segments"],
                           "occurrences": v.get("occurrences")} for k, v in mt.items()},
        "rounds": lh.get("rounds"),
        "sequence_prompt": lh.get("sequence_prompt"),
    }
    s["goal"] = ("AR 场景双臂并行 300UPH: 左臂摆盘 + 右臂插拔与 AOI 五点检测; "
                 "一轮 %d 段 / %.2fs / 14 件, 目标 300 件/小时 (12s/件)"
                 % (lh["segments_total"], lh["round_total_s"]))
    s["_ar300_note"] = "2026-10-28 由 tools/ar300_workorder.py 写入 (元任务组合 + 300UPH), 唯一依据保持不变的其他字段"

    bak = P_SCENES + ".bak_" + time.strftime("%H%M%S")
    shutil.copy2(P_SCENES, bak)
    json.dump(scenes, open(P_SCENES, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("① 场景唯一依据已更新: SCN-07-AOI steps=%d 元任务, 一件 %.2fs, 目标 %s UPH"
          % (len(steps), one_piece_s, lh["uph_target"]))
    print("   备份: %s" % os.path.basename(bak))

    # ── 备份旧工单 → 重生成 ──
    if os.path.isdir(P_ORDERS):
        ob = P_ORDERS + "_bak_" + time.strftime("%H%M%S")
        shutil.copytree(P_ORDERS, ob)
        print("② 旧工单已备份: %s (%d 份)" % (os.path.basename(ob), len(os.listdir(P_ORDERS))))
    r = subprocess.run([PY, os.path.join(ROOT, "tools/build_sheet.py")],
                       cwd=ROOT, capture_output=True, text=True)
    print("   build_sheet: rc=%s %s" % (r.returncode, (r.stdout or r.stderr).strip().splitlines()[-1:] or ""))

    # ── 后处理: build_sheet 只搬 t/dur/name/desc/force, 双臂角色与元任务归属要补回来 ──
    p = os.path.join(P_ORDERS, "BS_SCN-07-AOI.json")
    if not os.path.exists(p):
        print("❌ 工单未生成: %s" % p)
        return 1
    w = json.load(open(p, encoding="utf-8"))
    arm_of = {x["meta_task"]: x for x in steps}
    patched = 0
    for st in (w.get("process") or []):
        for mid, x in arm_of.items():
            if str(st.get("name", "")).startswith(mid):
                st["arm"] = x["arm"]
                st["meta_task"] = mid
                st["segments"] = x["segments"]
                patched += 1
                break
    w["ar_300uph"] = {
        "uph_target": lh["uph_target"], "tact_s": lh.get("tact_s"), "tact_target_s": 12.0,
        "one_piece_s": one_piece_s, "segments_per_round": lh["segments_total"],
        "round_total_s": lh["round_total_s"], "modules_per_round": 14, "yield_target": 0.99,
        "dual_arm": {"left": "摆盘 (MT-01)", "right": "插拔 + AOI 五点检测 (MT-02/03/04/05)"},
        "meta_tasks": {k: {"name": v["name"], "segments": v["segments"], "occurrences": v.get("occurrences")}
                       for k, v in mt.items()},
        "sequence_prompt": lh.get("sequence_prompt"),
        "geometry_source": "sim_insert.json (392 段: 14 槽 / 4 孔 / 金手指点 / 4 侧面点)",
        "real_cmd": False,
        "note": ("AR 仿真链几何取自段表, 不依赖 T_base_cam/plane_z; "
                 "真机执行前必须先补该两项标定 (见 readiness.site_missing)"),
    }
    w.setdefault("targets", {})["产能 UPH"] = "300 件/h (12s/件 · 几何能力 315)"
    w.setdefault("targets", {})["双臂并行"] = "左臂摆盘 + 右臂插拔/AOI 同时动作"
    json.dump(w, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("② 工单后处理: 补回 arm/meta_task %d 步 + ar_300uph 段" % patched)

    # ── 校验工单 ──
    tgt = (w.get("targets") or {})
    a3 = w.get("ar_300uph") or {}
    steps2 = w.get("process") or []
    ck = [
        ("identity.scene_id = SCN-07-AOI", (w.get("identity") or {}).get("scene_id") == "SCN-07-AOI"),
        ("工序步骤 = 4 个元任务", len(steps2) == 4),
        ("每步带 arm (左右臂)", all(x.get("arm") in ("left", "right") for x in steps2)),
        ("每步带 meta_task 归属", all(x.get("meta_task") for x in steps2)),
        ("ar_300uph.uph_target = 300", a3.get("uph_target") == 300),
        ("ar_300uph 含 5 个元任务", len(a3.get("meta_tasks") or {}) == 5),
        ("targets 含产能条目", "产能 UPH" in tgt),
        ("safety 在", bool(w.get("safety"))),
        ("poka_yoke 在", bool(w.get("poka_yoke"))),
        ("real_cmd=false (真机零指令)", a3.get("real_cmd") is False),
    ]
    print("③ 工单校验 (%s):" % os.path.basename(p))
    ok = True
    for name, good in ck:
        print("   %s %s" % ("✅" if good else "❌", name))
        ok = ok and good
    print("   工单数: %d 份 | identity=%s" % (len([f for f in os.listdir(P_ORDERS) if f.endswith('.json')]),
                                          (w.get("identity") or {}).get("order_no")))
    print("\n结果: %s" % ("✅ 工单即任务已落地" if ok else "❌ 有项未过"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
