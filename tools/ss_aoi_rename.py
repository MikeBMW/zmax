#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ss_aoi_rename.py — 画布节点「🔍 外观质量检测」→「🔍 光学质量检测」(老倪 2026-10-11)

改的是**唯一依据** (flows.load_canvas/save_canvas; 唯一依据文件见 config/topics 或 engineering 库同步链),
不手改 .db / 不手改副本。要求: 节点数/连线数一个不差, 其余节点名字节不动。
"""
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OLD, NEW = "外观质量检测", "光学质量检测"


def main():
    from lerobot.engineering import flows
    p = flows.canvas_path()
    print("唯一依据画布:", p)
    before = json.load(open(p, encoding="utf-8"))
    nb = len(before.get("nodes", []))
    eb = len(before.get("links", before.get("edges", [])))
    hits = [n for n in before.get("nodes", []) if OLD in (n.get("name") or "")]
    print("改名节点数:", len(hits), [n.get("name") for n in hits])
    if len(hits) != 1:
        print("❌ 预期 1 个命中, 实得 %d —— 不做猜测性改名, 退出" % len(hits))
        return 2
    if "--dry" in sys.argv:
        print("dry-run: 只报告不改。")
        return 0
    bak = os.path.join(ROOT, "zmax_data", "backup", "canvas_before_aoi_rename_%s.json"
                       % time.strftime("%Y%m%d_%H%M%S"))
    os.makedirs(os.path.dirname(bak), exist_ok=True)
    shutil.copy2(p, bak)
    d, errs = flows.load_canvas()          # validate=True → (data, errors)
    if errs:
        print("❌ 原画布校验就有 %d 条错误, 先修再改: %s" % (len(errs), errs[:3]))
        return 2
    hit = None
    for n in d.get("nodes", []):
        if OLD in (n.get("name") or ""):
            hit = n
            n["name"] = n["name"].replace(OLD, NEW)
            print("节点 %s: %r → %r" % (n.get("id"), OLD, n["name"]))
    if hit is None:
        print("❌ load_canvas 里没找到 —— 退出")
        return 2
    sp, sbak = flows.save_canvas(d, reason="aoi_rename")
    print("save_canvas →", sp, "| 自动备份:", sbak)
    after = json.load(open(p, encoding="utf-8"))
    na = len(after.get("nodes", []))
    ea = len(after.get("links", after.get("edges", [])))
    print("节点 %d→%d  连线 %d→%d" % (nb, na, eb, ea))
    ok = (na == nb and ea == eb
          and sum(1 for n in after["nodes"] if OLD in (n.get("name") or "")) == 0
          and sum(1 for n in after["nodes"] if NEW in (n.get("name") or "")) == 1)
    # 其余节点名字节不动
    on_b, on_a = [n.get("name") for n in before["nodes"]], [n.get("name") for n in after["nodes"]]
    diff = [(x, y) for x, y in zip(on_b, on_a) if x != y]
    print("改名外的差异节点:", diff)
    print("备份:", bak)
    print("判据:", "PASS" if (ok and len(diff) == 1) else "FAIL")
    return 0 if (ok and len(diff) == 1) else 3


if __name__ == "__main__":
    sys.exit(main())
