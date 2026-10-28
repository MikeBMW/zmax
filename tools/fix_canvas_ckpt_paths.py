#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_canvas_ckpt_paths.py — 修画布两个节点里**写错的 ckpt 路径** (唯一依据一致性)

2026-10-14 排查发现 (功能点描述核查副产物):
  · `ss_moe`      params.ckpt = `checkpoints/stage_moe/moe.pt (351MB)`
  · `ss_lora_l4`  params.ckpt = `checkpoints/intact_goal_optical_insert_v6lora_200`
两条都按**仓库根相对路径**写, 而仓库根下没有 `checkpoints/` 目录 (实测不存在) —— 谁照着
拷贝/加载都会失败。实物在 `zmax_data/stable-wm-cache/checkpoints/` 下 (moe.pt 351,492,675 B;
v6lora_200 是目录, 内有 config.json 等)。

本脚本只改这两个 params.ckpt 字符串, 走官方 `flows.load_canvas/save_canvas` (带校验 + 自动备份),
不动节点/连线/其他参数。`--dry` 只看不改。改完请跑 engineering_db build + 画布判据。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from lerobot.engineering import flows                                                       # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REL = "zmax_data/stable-wm-cache/checkpoints"
FIX = {
    "ss_moe": ("checkpoints/stage_moe/moe.pt (351MB)",
               REL + "/stage_moe/moe.pt (351MB)", REL + "/stage_moe/moe.pt"),
    "ss_lora_l4": ("checkpoints/intact_goal_optical_insert_v6lora_200",
                   REL + "/intact_goal_optical_insert_v6lora_200",
                   REL + "/intact_goal_optical_insert_v6lora_200"),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="只看不改")
    a = ap.parse_args()

    d, errs = flows.load_canvas()                                                            # (data, errors)
    if errs:
        print("⛔ 画布本身校验不过, 不写入: %s" % (list(errs)[:3],))
        return 2
    nodes = {n.get("id"): n for n in (d.get("nodes") or [])}
    changed, problems = {}, []
    for nid, (old, new, real) in FIX.items():
        n = nodes.get(nid)
        if not n:
            problems.append("画布上找不到节点 %s" % nid)
            continue
        cur = (n.get("params") or {}).get("ckpt")
        if not os.path.exists(os.path.join(ROOT, real)):
            problems.append("%s 的目标实物不存在: %s" % (nid, real))
        if cur == new:
            changed[nid] = "已是最新, 不动"
            continue
        if cur != old:
            problems.append("%s 现值与预期不符 (现值 %r), 不盲改" % (nid, cur))
            continue
        changed[nid] = "%r → %r" % (old, new)
        n["params"]["ckpt"] = new

    for k, v in changed.items():
        print("  %-12s %s" % (k, v))
    if problems:
        print("⛔ 拒绝写入:")
        for p in problems:
            print("   -", p)
        return 2
    if a.dry:
        print("--dry: 未写入")
        return 0
    if all(v == "已是最新, 不动" for v in changed.values()):
        print("无需写入")
        return 0
    p, bak = flows.save_canvas(d, reason="fix_canvas_ckpt_paths")
    rb, _e2 = flows.load_canvas()                                                            # 回读
    ok = all(({n.get("id"): n for n in rb.get("nodes") or []}[k].get("params") or {}).get("ckpt")
             == FIX[k][1] for k in FIX)
    print("已写入 %s · 备份 %s · 回读一致: %s" % (os.path.relpath(p, ROOT), os.path.basename(bak or ""), ok))
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
