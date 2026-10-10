#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scene_build_updown.py — 生成「上下料」场景 (SCN-07-UP), 并让它**在场景功能区可可视化编辑**

老倪 2026-10-10: 「你要再做一个上下料场景，验证指标；上下料场景，在场景功能区可以可视化编辑」

上下料 = 一个完整循环:  取料 (料仓/料盘) → 上料 (装进工位夹具/治具) → 卸料 (取下) → 回收 (放回料盘)
与既有场景的区别: SCN-02-HANDLE 是搬运, SCN-06-TRAY 是摆盘; 本场景是**工位级上下料**,
指标验证重点是 对位重复性 / 插入到位 / 端面与力 的可复现性 (而不是节拍吞吐)。

真源优先, 假设明标:
  · 坐标取自 `data/scene/objects3d.json` (现场示教 + 深度实测) 与 `data/skills/l2_atomic/space_points.json`
    (真机 /robot/tcp_pose 实测 7 点) —— 凡抄自真源的, source 字段写明出处。
  · 工位夹具/上料口等**现场未示教**的位姿按父场景几何 + 安全偏置推导, source 明写「推导(待现场示教)」。
  · 不编造"现场实测"字样; 位姿单位 m (base_link), 尺寸 mm。

产出 (可被 tools/scene_edit.py 编辑 ⇒ 场景功能区可视化编辑):
  · data/scene/scenes/SCN-07-UP/objects3d.json   (场景对象表)
  · data/scene/scenes/SCN-07-UP/overlay_spec.json (现场标记 markers / 保护围栏 fences / 上下料轨迹 trajectories)
  · 登记进 data/scene/scenes/index.json 的 named_scenes (场景功能区下拉即可选中)

幂等: 同输入 ⇒ 同输出 (内容不含墙上时钟, 除非 --wallclock)。
用法:
    python3 tools/scene_build_updown.py            # 生成/刷新
    python3 tools/scene_build_updown.py --show     # 只看 (不写)
    python3 tools/scene_build_updown.py --scene SCN-07-UP   # 场景 id (默认 SCN-07-UP)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENE = os.path.join(ROOT, "data", "scene")
PARENT_O3D = os.path.join(SCENE, "objects3d.json")
PARENT_OVERLAY = os.path.join(SCENE, "overlay_spec.json")
SPACE_POINTS = os.path.join(ROOT, "data", "skills", "l2_atomic", "space_points.json")
PLATFORM = os.path.join(ROOT, "config", "platform", "zmax_platform.json")
INDEX = os.path.join(SCENE, "scenes", "index.json")


def _j(p, d=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return d if d is not None else {}


def _sha(p):
    try:
        return hashlib.sha256(open(p, "rb").read()).hexdigest()
    except Exception:  # noqa: BLE001
        return ""


def _finding(title):
    """在父场景里按关键词找对象 (现场示教对象优先)。"""
    for o in _j(PARENT_O3D, {}).get("objects", []) or []:
        if title in str(o.get("name", "")):
            return o
    return None


def build(scene_id="SCN-07-UP"):
    pj = _j(PLATFORM, {})
    sp = (_j(SPACE_POINTS, {}) or {}).get("points", {}) or {}
    parent_meta = {k: v for k, v in (_j(PARENT_O3D, {}) or {}).items() if k != "objects"}
    slot1 = _finding("槽位1")
    slot2 = _finding("槽位2")
    hole = _finding("插孔")
    fixture = _finding("治具") or _finding("工位")

    def center_of(o, fallback, why):
        if o and isinstance(o.get("center"), list) and len(o["center"]) == 3:
            return [float(x) for x in o["center"]], "真源: " + str(o.get("source", "objects3d.json"))
        return [float(x) for x in fallback], why

    c_feed, s_feed = center_of(slot1, [0.6488, 0.4983, 0.1104], "推导(待现场示教): 取料位暂借父场景槽位1")
    c_load, s_load = center_of(hole, [0.7575, 0.2279, 0.1901], "推导(待现场示教): 上料位暂借父场景插孔位")
    # 下料位 = 上料位 + 安全偏置 (同工位另一侧), 回收位 = 取料位 (料盘循环)
    c_unload = [c_load[0], c_load[1] + 0.06, c_load[2]]
    c_recycle = list(c_feed)
    sp_pt = sp.get("space1", {})
    if isinstance(sp_pt.get("pos"), list) and len(sp_pt["pos"]) == 3:
        c_home = [float(x) for x in sp_pt["pos"]]
        s_home = "真源: space_points.json#space1 (真机 tcp_pose 实测)"
    else:
        c_home, s_home = [0.42, 0.36, 0.52], "推导(待现场示教): 待机位暂用臂可达中心"

    def obj(name, center, size, source, note, kind=None):
        d = {"name": name, "center": [round(v, 5) for v in center], "size": size,
             "coord": "base", "source": source, "note": note}
        if kind:
            d["kind"] = kind
        return d

    objects = [
        obj("上下料·取料位 (料仓/料盘)", c_feed, [140.0, 140.0, 40.0], s_feed,
            "上下料循环起点: 从料仓/料盘取件; 与 SCN-06 摆盘的料盘同源几何", "feed"),
        obj("上下料·上料位 (工位夹具)", c_load, [60.0, 60.0, 30.0], s_load,
            "工件装入工位夹具/治具的位置 (插入方向 +Z), 指标验证重点在此: 对位重复性/插入到位", "load"),
        obj("上下料·下料位 (工位取出)", c_unload, [60.0, 60.0, 30.0],
            "推导(待现场示教): 上料位 +60mm 偏置 (同工位夹爪让位)",
            "卸料工位: 从上料夹具取出工件; 偏置为抓取让位量, 待现场确认", "unload"),
        obj("上下料·回收位 (空盘位)", c_recycle, [140.0, 140.0, 40.0], s_feed,
            "工件回收: 与取料位同盘位 (空盘循环), 用于往返成功率统计", "recycle"),
        obj("上下料·待机位 (臂 home)", c_home, [40.0, 40.0, 40.0], s_home,
            "每循环起始/结束的等待位; 由实测空间点给出 (非推导)", "home"),
    ]
    if slot2 and isinstance(slot2.get("center"), list):
        objects.append(obj("上下料·备用料位 (双工位)", [float(x) for x in slot2["center"]], [22.0, 18.0, 12.0],
                           "真源: " + str(slot2.get("source", "objects3d.json")),
                           "双工位切换/低料位告警位 (现场示教槽位2)", "spare"))

    markers = [
        {"id": "mk_feed", "name": "取料位", "kind": "工位", "pos": [round(v, 5) for v in c_feed],
         "source": s_feed, "note": "上下料循环起点"},
        {"id": "mk_load", "name": "上料位", "kind": "工位", "pos": [round(v, 5) for v in c_load],
         "source": s_load, "note": "指标验证主工位"},
        {"id": "mk_unload", "name": "下料位", "kind": "工位", "pos": [round(v, 5) for v in c_unload],
         "source": "推导(待现场示教)", "note": "上料位 +60mm 偏置"},
        {"id": "mk_safe", "name": "上下料安全区", "kind": "危险区", "pos": [round(v, 5) for v in c_load],
         "radius_m": 0.25, "source": "推导: 上料位半径 250mm",
         "note": "上下料作业时禁止人工进入 (安全红线只读)"},
    ]
    fences = [{"id": "fn_updown", "name": "上下料工位保护围栏", "kind": "box",
               "center": [round((c_feed[0] + c_load[0]) / 2, 5), round((c_feed[1] + c_load[1]) / 2, 5), 0.2],
               "size_m": [0.62, 0.52, 0.40], "source": "推导: 覆盖取料位与上料位的外包络 +100mm 余量",
               "note": "保护围栏 (scene_edit 会做合法性校验)"}]
    trajectories = [
        {"id": "tr_load", "name": "上料轨迹 (取料位 → 上料位)", "kind": "规划轨迹",
         "waypoints": [[round(v, 5) for v in c_home], [round(v, 5) for v in c_feed],
                       [round(v, 5) for v in c_load]], "source": "由场景位姿派生 (waypoints 可引用空间点)",
         "note": "取件 → 上位 → 插入夹具"},
        {"id": "tr_unload", "name": "下料轨迹 (上料位 → 下料位 → 回收位)", "kind": "规划轨迹",
         "waypoints": [[round(v, 5) for v in c_load], [round(v, 5) for v in c_unload],
                       [round(v, 5) for v in c_recycle], [round(v, 5) for v in c_home]],
         "source": "由场景位姿派生", "note": "取出 → 让位 → 回收 → 回待机"},
    ]
    o3d = {"objects": objects, "coord": "base", "source": "scene_build_updown.py (上下料场景 SCN-07-UP)",
           "handeye": parent_meta.get("handeye"), "tcp": parent_meta.get("tcp"),
           "parent": {"file": "data/scene/objects3d.json", "sha256": _sha(PARENT_O3D)},
           "meta": {"scene_id": scene_id,
                    "name": "上下料 (工位级: 取料 → 上料 → 卸料 → 回收)",
                    "cycle": ["取料", "上料(插入夹具)", "卸料(取出)", "回收(放回料盘)"],
                    "metric_scope": ["perf.mate_align_repeat", "perf.mate_angle_repeat", "perf.D_INSERT_mm",
                                     "perf.insert_depth_res", "perf.force_res", "perf.force_overshoot",
                                     "perf.success_rate", "perf.cycle_s"],
                    "note": "位姿真源优先; 未示教位姿来源标'推导(待现场示教)'"}}
    ov = {"mode": "updown", "source": "scene_build_updown.py", "handeye_ok": parent_meta.get("handeye") == "TSAI",
          "cameras": (_j(PARENT_OVERLAY, {}) or {}).get("cameras", {}),
          "scene": "上下料工位: 取料位/上料夹具/下料位/回收位 + 保护围栏 + 上下料轨迹 (SCN-07-UP)",
          "markers": markers, "fences": fences, "trajectories": trajectories, "deleted": {},
          "meta": {"scene_id": scene_id, "editable": "tools/scene_edit.py --scene " + scene_id}}
    return scene_id, o3d, ov


def write(scene_id, o3d, ov):
    d = os.path.join(SCENE, "scenes", scene_id)
    os.makedirs(d, exist_ok=True)
    for fn, data in (("objects3d.json", o3d), ("overlay_spec.json", ov)):
        p = os.path.join(d, fn)
        if os.path.exists(p):
            shutil.copy2(p, p + ".bak_%s" % __import__("time").strftime("%Y%m%d_%H%M%S"))
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
    # 登记进 index.json 的 named_scenes
    idx = _j(INDEX, {}) or {}
    ns = idx.get("named_scenes") or {}
    ns[scene_id] = {"dir": "data/scene/scenes/%s" % scene_id,
                    "name": o3d["meta"]["name"], "objects": len(o3d["objects"]),
                    "markers": len(ov["markers"]), "fences": len(ov["fences"]),
                    "trajectories": len(ov["trajectories"]),
                    "objects3d_sha256": _sha(os.path.join(d, "objects3d.json")),
                    "edit": "tools/scene_edit.py --scene %s" % scene_id}
    idx["named_scenes"] = ns
    tmp = INDEX + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=1)
    os.replace(tmp, INDEX)
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", default="SCN-07-UP")
    ap.add_argument("--show", action="store_true", help="只看, 不写")
    a = ap.parse_args()
    sid, o3d, ov = build(a.scene)
    print("═" * 74)
    print("场景 %s · %s" % (sid, o3d["meta"]["name"]))
    print("  循环: %s" % " → ".join(o3d["meta"]["cycle"]))
    print("  指标验证: %s" % ", ".join(o3d["meta"]["metric_scope"]))
    for o in o3d["objects"]:
        print("   · %-28s %s  [%s]" % (o["name"], o["center"], o["source"][:44]))
    print("  标记 %d · 围栏 %d · 轨迹 %d" % (len(ov["markers"]), len(ov["fences"]), len(ov["trajectories"])))
    if a.show:
        return 0
    d = write(sid, o3d, ov)
    print("  ✅ 写入 %s (可被 scene_edit 编辑 ⇒ 场景功能区可视化编辑)" % os.path.relpath(d, ROOT))
    print("     编辑: python3 tools/scene_edit.py --scene %s list" % sid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
