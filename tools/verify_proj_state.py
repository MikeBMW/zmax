#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据: 调试状态自动存档到 .proj + 打开工程时自动恢复 (收尾保持老倪当前配置: 摆盘场景 + TASK-06-TRAY)"""
import importlib.util as ilu, json, os, subprocess, sys
ROOT = "/home/ubuntu/zmax"
sys.path[:0] = [ROOT + "/tools", ROOT + "/tools/gui", ROOT + "/src"]
FAIL = []
def chk(c, m):
    print(("  \u2705 " if c else "  \u2717 ") + m)
    if not c: FAIL.append(m)
def load(p, n):
    s = ilu.spec_from_file_location(n, p); m = ilu.module_from_spec(s); s.loader.exec_module(m); return m

ps = load(ROOT + "/tools/proj_state.py", "proj_state")
ts = load(ROOT + "/tools/ss_task_state.py", "ss_task_state")
BIND, LED, MAN = (ROOT + "/config/ss_task_binding.json", ROOT + "/config/task_state_ledger.json",
                  ROOT + "/config/task_state_manual.json")
snap = {p: (open(p, "rb").read() if os.path.exists(p) else None) for p in (BIND, LED, MAN)}
PROJ = ps.DEFAULT_PROJ

cap = ps.capture()
print("  capture:", {k: cap[k] for k in ("active_task", "src_state", "scene_id", "canvas_md5")})
chk(cap["active_task"] == "TASK-06-TRAY" and cap["src_state"] == "摆盘场景" and cap["scene_id"] == "SS-TRAY-PLACE",
    "① 捕获的调试状态 == 你设的现状 (TASK-06-TRAY · 摆盘场景 · SS-TRAY-PLACE)")

pre = json.load(open(PROJ, encoding="utf-8")) if os.path.exists(PROJ) else {}
r = ps.save(reason="判据复跑")
chk(r.get("ok") and r.get("readback") and r.get("others_unchanged"), "② 存档成功: %s" % os.path.basename(r.get("path") or ""))
post = json.load(open(PROJ, encoding="utf-8"))
ds = post.get("debug_state") or {}
chk(ds.get("active_task") == "TASK-06-TRAY" and ds.get("scene_id") == "SS-TRAY-PLACE" and ds.get("src_state") == "摆盘场景",
    "② debug_state 段内容对: 任务 %s · 数据源 %s · 场景 %s" % (ds.get("active_task"), ds.get("src_state"), os.path.basename(ds.get("scene_dir") or "")))
chk({k: v for k, v in post.items() if k not in ("debug_state", "_prev_debug_state")} ==
    {k: v for k, v in pre.items() if k not in ("debug_state", "_prev_debug_state")},
    "② 工程文件其他段一字未动 (schema=%s · canvas/calibration/master_param/tasks 原样)" % post.get("schema"))
chk("canvas" in post and "task_binding" in post and len((post.get("canvas") or {}).get("nodes") or []) == 89,
    "② 工程文件真身完整: 段 = %s (canvas 89 节点)" % list(post.keys()))
chk((post.get("task_binding") or {}).get("active_task") == "TASK-06-TRAY",
    "② 工程文件里任务绑定段也带对了活跃任务: task_binding.active_task = %s"
    % (post.get("task_binding") or {}).get("active_task"))

# 模拟「下次打开」: 清场景真源 + 把任务改回 TASK-01-FW, 再用工程文件恢复
os.environ.pop("ZMAX_SCENE_DIR", None)
ok_sw, why_sw, _ = ts.set_state("TASK-01-FW", "★ 活跃")
print("  (模拟走开: 清掉场景真源 + 任务切回 TASK-01-FW → %s)" % why_sw[:60])
chk(ok_sw and json.load(open(BIND, encoding="utf-8"))["active_task"] == "TASK-01-FW", "③ 模拟现场已改变 (TASK-01-FW 活跃, 无 ZMAX_SCENE_DIR)")
rr = ps.restore(PROJ)
print("  restore:", json.dumps(rr.get("applied"), ensure_ascii=False))
chk(rr.get("ok") and os.environ.get("ZMAX_SCENE_DIR", "").rstrip("/").endswith("SS-TRAY-PLACE"),
    "④ 恢复场景真源: ZMAX_SCENE_DIR → %s" % os.path.basename(os.environ.get("ZMAX_SCENE_DIR") or ""))
chk(json.load(open(BIND, encoding="utf-8"))["active_task"] == "TASK-06-TRAY", "④ 恢复活跃任务: 存档里的 TASK-06-TRAY")

src = {p: open(ROOT + p, encoding="utf-8").read() for p in
       ("/tools/gui/simulink_module.py", "/tools/gui/veh6_config_page.py", "/tools/gui/project_file.py")}
chk(all("proj_state" in v for v in src.values()), "⑤ 三处自动钩子都接了 (数据源切换 / 活跃属性下拉 / 打开工程文件)")

for p, b in snap.items():                       # 收尾: 真源字节还原 (保持老倪现在的配置)
    if b is None:
        if os.path.exists(p):
            os.remove(p)
    else:
        open(p, "wb").write(b)
final = {r2["task_id"]: r2["state"] for r2 in ts.build(write=False)["tasks"]}
chk(final["TASK-06-TRAY"] == "★ 活跃" and final["TASK-01-FW"] == "○ 未激活", "⑥ 收尾: 仍是你的配置 (TASK-06-TRAY 活跃 / TASK-01-FW 未激活)")
print("\n%s  (%d 项失败)" % ("PROJ-STATE PASS" if not FAIL else "PROJ-STATE FAIL", len(FAIL)))
sys.exit(0 if not FAIL else 1)
