#!/usr/bin/env python3
"""任务 → 场景/数据源 切换 —— 配置中心的「活跃配置」一变, 场景跟着变 (老倪 2026-10-12 逐字要求)。

老倪: 「检查配置中心的 活跃配置, 切换 任务1 FW-对应插拔场景; 任务6 TRAY 对应摆盘场景; 任务7 AOI 对应 AR场景」

单一真源: 画布数据源节点(`ssdata`, 📦 metaworld 数据源)的 `params.src_state`
  —— 经 src/lerobot/engineering/flows.py::load_canvas/save_canvas 读写真源(不手改 .db)。
映射(本文件是**唯一**映射表, UI/信号分析/3D 都从这儿取色):
  TASK-01-FW  → 插拔场景 (#2e8b57 绿)
  TASK-06-TRAY→ 摆盘场景 (#1f6feb 蓝)
  TASK-07-AOI → AR场景   (#8957e5 紫)
其余任务无映射 ⇒ 不动数据源(返回 skipped, 明说).

用法:
  ./gui-venv311/bin/python tools/ss_scene_switch.py --list              # 看映射表
  ./gui-venv311/bin/python tools/ss_scene_switch.py --task TASK-07-AOI  # 真切
  ./gui-venv311/bin/python tools/ss_scene_switch.py --task TASK-07-AOI --check   # 只看要切到哪
  ./gui-venv311/bin/python tools/ss_scene_switch.py --now               # 当前画布 src_state
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

TASK_SCENE = {
    "TASK-01-FW":   {"scene": "插拔场景", "scn": "SCN-01-FW",   "color": "#2e8b57", "name": "插拔场景(绿)"},
    "TASK-06-TRAY": {"scene": "摆盘场景", "scn": "SCN-06-TRAY", "color": "#1f6feb", "name": "摆盘场景(蓝)"},
    "TASK-07-AOI":  {"scene": "AR场景",   "scn": "SCN-07-AOI",  "color": "#8957e5", "name": "AR场景(紫)"},
}
SCENE_COLOR = {"插拔场景": "#2e8b57", "摆盘场景": "#1f6feb", "AR场景": "#8957e5", "真机": "#c9d1d9"}
SRC_NODE_HINT = ("ssdata", "数据源")


def _canvas():
    from lerobot.engineering import flows
    return flows


def _find_src_node(d: dict):
    """数据源节点: 先认 id=ssdata, 再认带 params.src_state 的节点(只有一个真源)。"""
    for n in (d.get("nodes") or []):
        if str(n.get("id")) == "ssdata":
            return n
    for n in (d.get("nodes") or []):
        if "src_state" in (n.get("params") or {}):
            return n
    return None


def now() -> dict:
    f = _canvas()
    d, errs = f.load_canvas()
    n = _find_src_node(d or {})
    st = ((n or {}).get("params") or {}).get("src_state")
    return {"ok": bool(n), "node": (n or {}).get("id"), "src_state": st,
            "color": SCENE_COLOR.get(str(st), "#c9d1d9"), "errs": errs}


def switch(task: str, dry: bool = False) -> dict:
    """按任务切数据源/场景。返回 {ok, action, task, scene, src_state, node, msg}。"""
    m = TASK_SCENE.get(str(task).strip())
    before = now()
    if not m:
        return {"ok": True, "action": "skipped", "task": task, "src_state": before.get("src_state"),
                "msg": "该任务没有场景映射(只有 任务1 FW / 任务6 TRAY / 任务7 AOI 有) ⇒ 数据源不动"}
    if before.get("src_state") == m["scene"]:
        return {"ok": True, "action": "nochange", "task": task, "scene": m["scene"], "scn": m["scn"],
                "color": m["color"], "src_state": before.get("src_state"), "node": before.get("node"),
                "msg": "已经是 %s (%s) ⇒ 不动" % (m["name"], m["scn"])}
    if dry:
        return {"ok": True, "action": "dry", "task": task, "scene": m["scene"], "scn": m["scn"],
                "color": m["color"], "was": before.get("src_state"),
                "msg": "会把数据源 %s → %s (%s)" % (before.get("src_state"), m["name"], m["scn"])}
    f = _canvas()
    d, errs = f.load_canvas()
    n = _find_src_node(d or {})
    if n is None:
        return {"ok": False, "action": "error", "task": task,
                "msg": "画布里找不到数据源节点(ssdata) ⇒ 拒绝瞎改"}
    (n.setdefault("params", {}) or {})["src_state"] = m["scene"]
    ok, info = f.save_canvas(d)
    after = now()
    good = (after.get("src_state") == m["scene"])
    return {"ok": bool(ok) and good, "action": "switch", "task": task, "scene": m["scene"], "scn": m["scn"],
            "color": m["color"], "was": before.get("src_state"), "src_state": after.get("src_state"),
            "node": after.get("node"), "saved": bool(ok), "verify": good,
            "msg": "数据源 %s → %s (%s%s)" % (before.get("src_state"), after.get("src_state"),
                                            m["scn"], "" if good else " · ⛔ 回读不一致")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="")
    ap.add_argument("--check", action="store_true", help="只算不动")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--now", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.list:
        print("任务 → 场景/数据源 映射 (单一真源 %s):" % os.path.relpath(__file__, ROOT))
        for k, v in TASK_SCENE.items():
            print("  %-14s → %-8s %-12s %s" % (k, v["scene"], v["scn"], v["color"]))
        return 0
    if a.now:
        r = now()
        print("当前画布数据源: %s (node=%s color=%s)" % (r.get("src_state"), r.get("node"), r.get("color")))
        return 0 if r.get("ok") else 1
    if not a.task:
        print("需要 --task <TASK-ID> (或 --list / --now)")
        return 2
    r = switch(a.task, dry=a.check)
    if a.json:
        print(json.dumps(r, ensure_ascii=False))
    else:
        print("%s %s" % ("✅" if r.get("ok") else "⛔", r.get("msg")))
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
