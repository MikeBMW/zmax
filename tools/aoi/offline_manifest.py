#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成离线 AOI 开发的"代码完整性清单" —— 每个文件干什么 + sha256。

    ./.venv-aoi310/bin/python tools/aoi/offline_manifest.py            # 打印
    ./.venv-aoi310/bin/python tools/aoi/offline_manifest.py --write    # 写 docs/aoi_offline_manifest.json

为什么要有: 老倪离线前要确认"代码 copy 完整"。清单里每个文件都能单独校验,
少一个就是少一个 —— 不靠记忆, 靠 sha。
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

ITEMS = [
    # (相对路径, 作用, 必需?)
    ("src/lerobot/policies/aoi/service/prod/gold_10082_prod.py", "产线金手指程序 (与工控机逐字节一致)", True),
    ("src/lerobot/policies/aoi/service/prod/surface_10083_prod.py", "产线表面程序 (与工控机逐字节一致)", True),
    ("src/lerobot/policies/aoi/service/stubs.py", "Windows SDK 桩", True),
    ("src/lerobot/policies/aoi/service/prodload.py", "加载器 + judge_gold/judge_surface", True),
    ("src/lerobot/policies/aoi/service/sources.py", "帧源 remote/cam/file/dir/corpus/push", True),
    ("src/lerobot/policies/aoi/service/app.py", "镜像服务路由", True),
    ("src/lerobot/policies/aoi/service/run.py", "服务入口", True),
    ("src/lerobot/policies/aoi/local.py", "节点侧旁路客户端", True),
    ("src/lerobot/policies/aoi/quality.py", "inspect_aoi (接本机镜像)", True),
    ("src/lerobot/policies/aoi/gold.py", "工控机判决搬运 (在线时的对照路)", True),
    ("src/lerobot/policies/aoi/surface.py", "工控机表面旁路 (在线时的对照路)", True),
    ("src/lerobot/policies/aoi/gold_yolo.py", "本机 YOLO 观测 (models/yolo_gold_v2.pt)", False),
    ("src/lerobot/middleware/nodes/impl/ss_aoi.py", "画布节点薄壳 (异步 worker)", True),
    ("tools/aoi/cam_provider.py", "工控机取图 provider (相机线只能在工控机)", True),
    ("tools/aoi/provider_ctl.py", "provider 远控 start/stop/status", True),
    ("tools/aoi/setup_aoi_venv.sh", "建产线数值栈 venv", True),
    ("tools/aoi_local_service.sh", "本机镜像起停", True),
    ("tools/verify_aoi_local_service.py", "镜像服务验收 22 项", True),
    ("tools/verify_aoi_offline.py", "离线自检 18 项", True),
    ("tests/fixtures/aoi_frames/manifest.json", "离线帧 fixture 清单", True),
]


def main():
    out = {"root": ROOT, "items": [], "missing": [], "frames": {}}
    for rel, what, need in ITEMS:
        p = os.path.join(ROOT, rel)
        row = {"path": rel, "what": what, "required": need, "exists": os.path.exists(p)}
        if row["exists"]:
            b = open(p, "rb").read()
            row.update(bytes=len(b), sha256=hashlib.sha256(b).hexdigest())
        elif need:
            out["missing"].append(rel)
        out["items"].append(row)
    fx = os.path.join(ROOT, "tests/fixtures/aoi_frames")
    if os.path.isdir(fx):
        for n in sorted(os.listdir(fx)):
            if n.lower().endswith((".jpg", ".png")):
                p = os.path.join(fx, n)
                out["frames"][n] = hashlib.sha256(open(p, "rb").read()).hexdigest()
    corp = {}
    for k in ("gold", "surface"):
        d = os.path.join(ROOT, "zmax_data", "aoi_offline", k)
        corp[k] = len([f for f in os.listdir(d) if f.lower().endswith((".jpg", ".png"))]) if os.path.isdir(d) else 0
    out["corpus_frames"] = corp
    out["venv"] = {"path": ".venv-aoi310", "pins": ["numpy==1.26.4", "opencv-python==4.10.0.84", "flask"]}

    if "--write" in sys.argv:
        dst = os.path.join(ROOT, "docs", "aoi_offline_manifest.json")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1, ensure_ascii=False)
        print("written", dst)
    print(json.dumps({k: out[k] for k in ("missing", "corpus_frames", "venv")}, ensure_ascii=False))
    for it in out["items"]:
        mark = "✅" if it["exists"] else ("❌" if it["required"] else "○")
        print(f"{mark} {it['path']:<62} {it.get('sha256','')[:16]:<17} {it['what']}")
    return 1 if out["missing"] else 0


if __name__ == "__main__":
    sys.exit(main())
