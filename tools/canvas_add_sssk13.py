#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""canvas_add_sssk13.py — 往状态空间画布加「⑬ 自动翻转 · SK13」节点 + 5 条连线 (幂等)。

两份 JSON 都写 (画布工程改动的硬要求):
  data/database/zmax/sources/canvas/state_space_obs.json   ← 写盘真源
  flows/state_space_obs.json                               ← GUI 打开工程时读 (软链, 写实体会断链)

用法:
  ./gui-venv311/bin/python tools/canvas_add_sssk13.py --dry     # 只断言, 不写
  ./gui-venv311/bin/python tools/canvas_add_sssk13.py --apply   # 备份 + 写 + 回读校验
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data/database/zmax/sources/canvas/state_space_obs.json")
ALT = os.path.join(ROOT, "flows/state_space_obs.json")

NID = "sssk13"
NODE = {
    "id": NID, "type": "model", "name": "⑬ 自动翻转 · SK13", "icon": "🔄", "color": "#b98cff",
    "x": 8210, "y": 6086, "w": 280, "h": 110,
    "inputs": ["in1", "in2", "in3", "in4"], "outputs": ["out1", "out2"], "actions": [],
    "params": {
        "state_space": True, "skill_layer": True, "ondemand": True,
        "skill": {"template": "SK13", "stage": "翻转"},
        "desc": "[按需·分段小模型] 原子技能 ⑬ 自动翻转 (SK13): 拉环/模块朝向与目标朝向相反 ⇒ 抬净空 30mm, "
                "绕工具轴每拍 ≤5° 分 36 拍翻 180°, 再回落; 平移到 0.10 m/s、角速度 0.5 rad/s; "
                "不进 8/13 段主链 (判据触发)",
        "source": "src/lerobot/policies/left_right/state_space/skills/atomic_skills.py",
        "source_symbol": "class SK13Flip", "cap_level": "L2",
    },
}

LINKS = [
    {"id": "lk_sslimit_sssk13_in1", "f": "sslimit", "t": NID, "f_port": "out1", "t_port": "in1",
     "label": "🛡 限幅后控制 → ⑬ 自动翻转 · SK13"},
    {"id": "lk_ssskill_sssk13_in2", "f": "ssskill", "t": NID, "f_port": "out1", "t_port": "in2",
     "label": "L3 技能序列 → 按需翻转"},
    {"id": "lk_ssmem_sssk13_in3", "f": "ss_mem_l2", "t": NID, "f_port": "out1", "t_port": "in3",
     "label": "🧠 记忆赋能: 本段通道 + 标杆"},
    {"id": "lk_geoplan_sssk13_in4", "f": "n_geoplan", "t": NID, "f_port": "out1", "t_port": "in4",
     "label": "🎯 目标位姿 → 朝向判据 (相反才翻)"},
    {"id": "lk_sssk13_moveit_out1", "f": NID, "t": "n_moveit", "f_port": "out1", "t_port": "in2",
     "label": "翻转序列 → MoveIt 规划/执行"},
    {"id": "lk_phys_g13", "f": NID, "t": "ssphys", "f_port": "out2", "t_port": "in8",
     "label": "⚖ 技能动作 → 动力学约束"},
]


def check(d, tag):
    nodes = {n["id"]: n for n in d["nodes"]}
    print("[%s] nodes=%d links=%d" % (tag, len(d["nodes"]), len(d["links"])))
    # 位置不重叠 (跳过 row_bg 容器与自身)
    if NID in nodes:
        me = nodes[NID]
        for n in d["nodes"]:
            if n["id"] == NID or n.get("type") == "row_bg":
                continue
            ox = abs(n.get("x", 0) - me["x"]) < (n.get("w", 280) + me["w"]) / 2 - 6
            oy = abs(n.get("y", 0) - me["y"]) < (n.get("h", 110) + me["h"]) / 2 - 6
            assert not (ox and oy), "✗ 位置与 %s(%s) 重叠" % (n["id"], n.get("name"))
    # 连线: 端点存在、x 严格递增、端口存在
    for l in d["links"]:
        if l.get("f") != NID and l.get("t") != NID:
            continue
        f, t = nodes.get(l["f"]), nodes.get(l["t"])
        assert f and t, "✗ 悬空连线 %s" % l
        assert f["x"] < t["x"], "✗ 连线 x 非递增 %s (%s→%s)" % (l["id"], f["x"], t["x"])
        # 老节点(如 ss_mem_l2)没有显式端口表 ⇒ 端口无法校验, 只查端点与 x 顺序
        if f.get("outputs"):
            assert l["f_port"] in f["outputs"], "✗ 源端口不存在 %s" % l["id"]
        if t.get("inputs"):
            assert l["t_port"] in t["inputs"], "✗ 目标端口不存在 %s" % l["id"]
    return nodes.get(NID)


def add(d):
    nodes = {n["id"] for n in d["nodes"]}
    if NID in nodes:
        n = next(x for x in d["nodes"] if x["id"] == NID)
        n.update({k: v for k, v in NODE.items() if k != "id"})
    else:
        d["nodes"].append(dict(NODE))
    have = {l.get("id") for l in d["links"]}
    for l in LINKS:
        if l["id"] in have:
            continue
        # 同 (f,t,port) 已存在则不重复
        if any(x.get("f") == l["f"] and x.get("t") == l["t"] and x.get("t_port") == l["t_port"] for x in d["links"]):
            continue
        d["links"].append(dict(l))
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if not (a.dry or a.apply):
        print("用 --dry 或 --apply")
        return 2

    d = json.load(open(SRC, encoding="utf-8"))
    d = add(d)
    check(d, "sources")
    if a.dry:
        print("DRY OK · 未写盘")
        return 0

    ts = time.strftime("%Y%m%d_%H%M")
    for p in (SRC, ALT):
        if os.path.exists(p) and not os.path.islink(p):
            shutil.copy2(p, p + ".bak-%s" % ts)
    json.dump(d, open(SRC, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    # flows/ 是软链(指向 sources), 直接写会断链; 不是软链才单独写
    if os.path.islink(ALT):
        print("flows/state_space_obs.json 是软链 → 已随真源更新:", os.path.realpath(ALT))
    else:
        json.dump(d, open(ALT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    back = json.load(open(SRC, encoding="utf-8"))
    check(back, "回读")
    ids = [l.get("id") for l in back["links"] if l.get("f") == NID or l.get("t") == NID]
    print("sssk13 连线 %d 条: %s" % (len(ids), ids))
    print("✅ 写盘完成 · 备份后缀 .bak-%s" % ts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
