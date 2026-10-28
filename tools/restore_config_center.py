#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🚑 恢复配置中心 UI: 把 ss_task_binding.json 的 run_cfg 还原成 UI 认的格式

事故 (2026-10-28):
  tools/ar300_config.py 往 TASK-07-AOI 的 run_cfg 里写了裸值
  (uph_target: 300 / tact_s: 12.0 / arm_roles: {...} / scene: "AR" / real_cmd: false),
  而配置中心 UI (tools/gui/veh6_config_page.py:3015) 对 run_cfg 的每个值直接取 v["checked"]:

      sum(1 for v in bmap[t["task_id"]]["run_cfg"].values() if v["checked"])

  ⇒ TypeError: 'int' object is not subscriptable ⇒ ConfigCenterPage 构建失败 ⇒ 北斗七星阵整页不显示。

修复:
  ① run_cfg 只保留 {"label": str, "checked": bool} 的复选开关 (与原状逐键一致)
  ② AR 300UPH 的参数搬到独立键 task["ar300"], UI 不读它, 不影响布局
  ③ active_task 恢复 TASK-01-FW (AR 链不依赖它: plan_long_impl 固定 task_id=TASK-07-AOI)
"""
import json
import os
import shutil
import sys
import time

P = "/home/ubuntu/zmax/data/database/zmax/sources/config/ss_task_binding.json"
TASK = "TASK-07-AOI"

# UI 认的键值必须是这种形状
ORIG_RUN_CFG = {
    "chk_engine_demo": {"label": "⚡引擎快演", "checked": True},
    "chk_l3_full": {"label": "🚀 L3 全链(插拔+AOI)", "checked": True},
    "chk_mani_yaw": {"label": "🧠 流形 yaw 执行", "checked": False},
    "chk_intact_exec": {"label": "🤖 L4 用 INTACT 节点执行", "checked": False},
    "chk_l4_dit": {"label": "🎯 L4 意图 → DiT 精炼", "checked": False},
    "chk_l2_compat": {"label": "🧩 L2 兼容 (前馈 MLP + YOLO)", "checked": True},
}


def main():
    b = json.load(open(P, encoding="utf-8"))
    t = [x for x in b["tasks"] if x.get("task_id") == TASK][0]
    cur = t.get("run_cfg") or {}

    # ① 拆出被污染的非复选键
    bad = {k: v for k, v in cur.items() if not isinstance(v, dict) or "checked" not in v}
    good = {k: v for k, v in cur.items() if isinstance(v, dict) and "checked" in v}

    # ② 复选键保住"用户当前勾选", 缺失的用原值补齐
    fixed = dict(ORIG_RUN_CFG)
    for k, v in good.items():
        if k in fixed:
            fixed[k]["checked"] = bool(v.get("checked"))
        else:
            fixed[k] = {"label": v.get("label", k), "checked": bool(v.get("checked"))}
    t["run_cfg"] = fixed

    # ③ 裸值搬到独立键 ar300 (UI 不读)
    if bad:
        ar = dict(t.get("ar300") or {})
        ar.update({k: v for k, v in bad.items() if k not in ("real_cmd",)})
        ar.setdefault("scene", "AR")
        ar.setdefault("real_cmd", False)
        ar.setdefault("uph_target", 300)
        ar.setdefault("tact_s", 11.42)
        ar.setdefault("arm_roles", {"left": "摆盘", "right": "插拔+AOI"})
        ar["_note"] = "AR 300UPH 场景参数 (2026-10-28); UI 不读此键, 不影响配置中心布局"
        t["ar300"] = ar

    # ④ active_task 恢复
    old_active = b.get("active_task")
    b["active_task"] = "TASK-01-FW"

    bak = P + ".fix_" + time.strftime("%H%M%S")
    shutil.copy2(P, bak)
    json.dump(b, open(P, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # ⑤ 判据: run_cfg 每个值都是 {label, checked}
    ok = all(isinstance(v, dict) and "label" in v and "checked" in v for v in t["run_cfg"].values())
    print("① run_cfg 还原: %d 个复选开关 (拆出裸值 %d 个 → ar300)" % (len(fixed), len(bad)))
    for k, v in fixed.items():
        print("   %-18s %-28s checked=%s" % (k, v["label"], v["checked"]))
    print("② ar300 键: %s" % json.dumps(t.get("ar300"), ensure_ascii=False)[:150])
    print("③ active_task: %s → %s" % (old_active, b["active_task"]))
    print("④ 判据 run_cfg 形状: %s" % ("✅ 通过" if ok else "❌ 失败"))
    print("   备份: %s" % os.path.basename(bak))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
