#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按 origin 清叠加规格里的图层 —— 主要用来清"历史的分割图"。

老倪 2026-10-07: 「历史的分割图怎么一直在画布上?」
根因: 按需分割的掩膜写进 overlay_spec.json 后没有过期机制, 推流服务**每帧热读**照画 ⇒ 一直挂着。
现在渲染侧已有"掩膜绑帧"闸(scene_overlay: 画面变了就不画), 本工具负责**把旧数据真删掉**。

用法:
    python3 tools/scene_clear_origin.py --list                      # 只列各 origin 条数(只读)
    python3 tools/scene_clear_origin.py --origin seg                # 空跑: 打印将要删什么
    python3 tools/scene_clear_origin.py --origin seg --apply        # 真删(先自动备份 spec)
    python3 tools/scene_clear_origin.py --origin seg,det --cam local --apply

纪律:
  · 只动指定的 origin, **不碰别家**(sim/vlm/det/meas/plan/trace/guide/l5live) —— 走 scene_overlay.merge_origin
  · 默认空跑; 真删前把 spec 备份到 data/scene/_archive/ 并打印还原命令
  · 不写 deleted 清单 —— deleted 的语义是"给大模型说不要再给", 拿去当清层工具会让同名实例被静默吞掉
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import scene_overlay as SO                                                            # noqa: E402


def counts(spec: dict) -> dict:
    out = {}
    for cam, cc in (spec.get("cameras") or {}).items():
        c = {}
        for b in (cc.get("boxes") or []):
            c[b.get("origin", "?")] = c.get(b.get("origin", "?"), 0) + 1
        out[cam] = c
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--origin", default="seg", help="要清的 origin(逗号分隔), 默认 seg")
    ap.add_argument("--cam", default="all", help="相机(逗号分隔: arm,local,local2), 默认 all")
    ap.add_argument("--apply", action="store_true", help="真删(不加=空跑)")
    ap.add_argument("--list", action="store_true", help="只列各 origin 条数, 什么都不改")
    a = ap.parse_args()

    spec = SO.load_spec()
    spec_path = Path(str(SO.SPEC_PATH))
    print("规格: %s" % spec_path)
    print("文件 mtime: %s" % time.strftime("%Y-%m-%d %H:%M:%S",
                                           time.localtime(spec_path.stat().st_mtime)))
    cnt = counts(spec)
    print("各相机 origin 条数:")
    for cam, c in cnt.items():
        print("  %-7s %s" % (cam, ", ".join("%s=%d" % (k, v) for k, v in sorted(c.items())) or "(空)"))
    if a.list:
        return 0

    origins = [x.strip() for x in a.origin.split(",") if x.strip()]
    cams = list(cnt.keys()) if a.cam == "all" else [x.strip() for x in a.cam.split(",") if x.strip()]
    todo = []
    for cam in cams:
        for o in origins:
            n = (cnt.get(cam) or {}).get(o, 0)
            if n:
                todo.append((cam, o, n))
    if not todo:
        print("没有可清的: 这些 origin 本来就没有框")
        return 0
    print("将清:")
    for cam, o, n in todo:
        print("  %-7s origin=%-7s %d 条" % (cam, o, n))
    if not a.apply:
        print("(空跑; 加 --apply 才真删)")
        return 0

    bak = spec_path.parent / "_archive" / ("overlay_spec_before_clear%s_%s.json"
                                           % ("_".join(origins), time.strftime("%Y%m%d_%H%M%S")))
    bak.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(spec_path, bak)
    print("已备份: %s" % bak)
    print("还原命令: cp %s %s" % (bak, spec_path))

    for cam in cams:
        for o in origins:
            if (cnt.get(cam) or {}).get(o, 0):
                spec = SO.merge_origin(spec, cam, o, [])
    SO.save_spec(spec)
    new = counts(SO.load_spec())
    print("清后 origin 条数:")
    ok = True
    for cam, c in new.items():
        print("  %-7s %s" % (cam, ", ".join("%s=%d" % (k, v) for k, v in sorted(c.items())) or "(空)"))
        for o in origins:
            if c.get(o):
                ok = False
    others_before = {(cam, k): v for cam, cc in cnt.items() for k, v in cc.items() if k not in origins}
    others_after = {(cam, k): v for cam, cc in new.items() for k, v in cc.items() if k not in origins}
    same = others_before == others_after
    print("✓ 目标 origin 已清: %s" % ok)
    print("✓ 其它 origin 未被动: %s %s" % (same, "" if same else
                                          "(前 %s → 后 %s)" % (others_before, others_after)))
    return 0 if (ok and same) else 1


if __name__ == "__main__":
    sys.exit(main())
