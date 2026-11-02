#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给画布上「未绑定实现」的节点补上前端展示用的 source 字段。

只写 params.source / params.source_symbol, 不动节点、不动连线、不动名称。
每条都按真实函数所在文件写, 不猜: 先 grep 到 `def <symbol>` 再落。
"""
import json
import os
import shutil
import subprocess
import time

ROOT = "/home/ubuntu/zmax"
CANVAS = ROOT + "/flows/state_space_obs.json"

# 节点 id → (函数名, 期望所在文件)
MAP = {
    "ssaoi": ("node_ss_aoi", "src/lerobot/engineering/nodes/library.py"),
    "ss_mem_l2": ("node_ss_mem_l2", "src/lerobot/memory/mem_nodes.py"),
    "ss_mem_l3": ("node_ss_mem_l3", "src/lerobot/memory/mem_nodes.py"),
    "ss_mem_l4": ("node_ss_mem_l4", "src/lerobot/memory/mem_nodes.py"),
    "ss_mem_share": ("node_ss_mem_share", "src/lerobot/memory/mem_nodes.py"),
    "n_l2_muscle": ("node_n_l2_muscle", "src/lerobot/engineering/nodes/library.py"),
    "sscap": ("node_ss_cap", "src/lerobot/engineering/nodes/library.py"),
    "ss_l5": ("node_l5_loop", "src/lerobot/engineering/nodes/library.py"),
    "ssvideo": ("node_ss_scope", "src/lerobot/engineering/nodes/library.py"),
    "ssvideo2": ("node_ss_video", "src/lerobot/engineering/nodes/library.py"),
    "ssmode": ("node_mode_switch", "src/lerobot/engineering/nodes/library.py"),
    "n_realscene": ("node_realscene_live", "src/lerobot/engineering/nodes/library.py"),
    "ssdata": ("node_metaworld_data", "src/lerobot/engineering/nodes/library.py"),
}


def main():
    d = json.load(open(CANVAS, encoding="utf-8"))
    byid = {n["id"]: n for n in d["nodes"]}
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak_dir = ROOT + "/data/database/zmax/sources/canvas/_archive"
    os.makedirs(bak_dir, exist_ok=True)
    bak = os.path.join(bak_dir, "state_space_obs_before_bind_source_%s.json" % ts)
    shutil.copy2(CANVAS, bak)

    done, skip = [], []
    for nid, (sym, want) in MAP.items():
        n = byid.get(nid)
        if n is None:
            skip.append((nid, "画布上没有这个节点"))
            continue
        # 先用 grep 确认函数真实所在文件, 与期望不一致就按实际的写
        out = subprocess.run(["grep", "-rln", "def %s" % sym, "--include=*.py", ROOT + "/src", ROOT + "/tools"],
                             capture_output=True, text=True).stdout.split()
        real = out[0].replace(ROOT + "/", "") if out else ""
        if not real:
            skip.append((nid, "找不到 def %s" % sym))
            continue
        if want and real != want:
            skip.append((nid, "期望 %s, 实际 %s" % (want, real)))
        p = n.setdefault("params", {})
        p["source"] = "%s · %s" % (real, sym)
        p["source_symbol"] = sym
        done.append(nid)

    json.dump(d, open(CANVAS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("补写 %d 个节点: %s" % (len(done), done))
    if skip:
        print("跳过 %d 个: %s" % (len(skip), skip))
    print("备份:", bak)


if __name__ == "__main__":
    main()
