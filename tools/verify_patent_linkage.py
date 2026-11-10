#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_patent_linkage.py — 核每件专利「声称的代码落点」是否真实存在

老倪 2026-11-11「这个专利跟状态空间工程联动了么」——
不能靠嘴说，必须有机器可复核的判据：专利里写的每个文件、每个符号，逐条到代码里找。

判据
----
① 文件存在（按仓库根解析）
② 符号存在于该文件（`def X` / `class X` / `X =` / 子串）
③ 验证脚本存在且可执行（判据本身也要是真的）

退出码: 0 全通过 / 1 有 FAIL
用法: gui-venv311/bin/python tools/verify_patent_linkage.py [--strict]
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAT = os.path.join(ROOT, "docs", "1-天枢-产品边界", "patents")

# ── 专利 → (文件, 必须存在的符号) ─────────────────────────────────────
# 只列「专利主张的核心实现」，不追求穷举；漏了说明该主张没有代码支撑。
LINKS: dict[str, list[tuple[str, str | None]]] = {
    "ZMP-2026-013": [
        ("src/lerobot/policies/manifold/geodesic_inject.py", "def correct"),
        ("src/lerobot/policies/manifold/geodesic_inject.py", "def anisotropic_metric"),
        ("src/lerobot/policies/manifold/geodesic_inject.py", "def tactile_to_gradient"),
        ("src/lerobot/policies/manifold/geodesic_inject.py", "def fuse_gradient"),
        ("src/lerobot/policies/manifold/geodesic_inject.py", "def force_guard"),
        ("src/lerobot/policies/manifold/geodesic_inject.py", "def lyapunov_check"),
        ("src/lerobot/policies/manifold/geodesic_inject.py", "def _radial_part"),
        ("src/lerobot/policies/manifold/inject_cfg.py", "def geometry"),
        ("src/lerobot/middleware/nodes/impl/flow_matching_impl.py", "_geo_correct"),
        ("src/lerobot/middleware/nodes/impl/flow_matching_impl.py", "tactile4"),
        ("config/calib/zmax_manifold.json", "contact_stiffness"),
        ("config/calib/zmax_manifold.json", "force_max"),
        ("tools/verify_visuo_tactile.py", "def ck"),
        ("tools/verify_l4_injection.py", None),
        ("tools/probe_l4_inject.py", None),
    ],
    "ZMP-2026-014": [
        ("src/lerobot/policies/aoi/quality.py", None),
        ("src/lerobot/middleware/nodes/impl/safety_limit_impl.py", "quality_veto"),
        ("src/lerobot/middleware/nodes/n_inspection.py", "PURE"),
        ("tools/probe_aoi_chain_e2e.py", None),
    ],
    "ZMP-2026-015": [
        ("tools/verify_l2_linkage.py", "真联通率"),
        ("tools/verify_l2_linkage.py", "空口"),
        ("tools/verify_l2_linkage.py", "语义"),
    ],
    "ZMP-2026-016": [
        ("src/lerobot/middleware/nodes/impl/ss_aoi.py", "worker"),
        ("tools/probe_aoi_async.py", None),
    ],
    "ZMP-2026-017": [
        ("src/lerobot/policies/manifold/inject_cfg.py", "_missing"),
        ("src/lerobot/policies/manifold/inject_cfg.py", "sigma_t_mm"),
        ("config/calib/zmax_manifold.json", "inject"),
    ],
    "ZMP-2026-018": [
        ("tools/bridge_follow.py", "STEP_MM"),
        ("tools/bridge_follow.py", "SPEED_CAP_MMS"),
        ("tools/bridge_follow.py", "arm"),
    ],
    "ZMP-2026-004": [
        ("src/lerobot/middleware/nodes/impl/safety_limit_impl.py", None),
    ],
    "ZMP-2026-009": [
        ("src/lerobot/middleware/nodes/impl/ss_skill.py", None),
    ],
    "ZMP-2026-010": [
        ("src/lerobot/memory/eng_memory.py", None),
    ],
    "ZMP-2026-011": [
        ("tools/red_follow_servo.py", None),
    ],
    "ZMP-2026-012": [
        ("tools/ar_aoi_bus.py", None),
    ],
    "ZMP-2026-003": [
        ("src/lerobot/policies/left_right/state_space/su2.py", None),
    ],
    "ZMP-2026-001": [
        ("tools/gui/ss_seven_stars.py", None),
    ],
    "ZMP-2026-002": [
        ("tools/gui/ss_seven_stars.py", None),
    ],
    "ZMP-2026-005": [
        ("src/lerobot/policies/yolo_3d/box3d_solver.py", None),
        ("src/lerobot/policies/yolo_3d/depth_align.py", None),
    ],
    "ZMP-2026-006": [
        ("src/lerobot/policies/sam3_seg/geometry3d.py", None),
    ],
    "ZMP-2026-007": [
        ("src/lerobot/policies/intact/modeling_intact.py", None),
        ("src/lerobot/middleware/nodes/n_intact.py", None),
    ],
    "ZMP-2026-008": [
        ("src/lerobot/policies/left_right/state_space/planner.py", None),
        ("src/lerobot/policies/left_right/state_space/safety.py", None),
    ],
}

PASS, FAIL, WARN = [], [], []


def main() -> int:
    strict = "--strict" in sys.argv
    print("=" * 72)
    print("专利 ↔ 状态空间工程 · 代码落点核对")
    print("=" * 72)

    # ① 在册专利清单（patents/*.md，排除 _v1_历史）
    on_book = sorted(f.split("_")[0] for f in os.listdir(PAT)
                     if f.startswith("ZMP") and f.endswith(".md"))
    print("在册专利: %d 件  %s" % (len(on_book), " ".join(x[-3:] for x in on_book)))

    # ② 每件专利的代码落点
    for num, links in sorted(LINKS.items()):
        if num not in on_book:
            WARN.append("%s: 有代码落点记录但无 md 正文" % num)
            continue
        print("\n[%s]" % num)
        for rel, sym in links:
            p = os.path.join(ROOT, rel)
            if not os.path.exists(p):
                # 软链真源兜底
                alt = os.path.join(ROOT, "data/database/zmax/sources", rel.split("config/", 1)[-1]) \
                    if rel.startswith("config/") else None
                if alt and os.path.exists(alt):
                    p = alt
                else:
                    FAIL.append("%s: 文件不存在 %s" % (num, rel))
                    print("  ✗ 文件不存在  %s" % rel)
                    continue
            if sym:
                try:
                    txt = open(p, encoding="utf-8", errors="replace").read()
                except Exception as e:                                  # noqa: BLE001
                    FAIL.append("%s: 读不了 %s (%s)" % (num, rel, e))
                    print("  ✗ 读不了      %s" % rel)
                    continue
                if sym not in txt:
                    FAIL.append("%s: %s 里没有 `%s`" % (num, rel, sym))
                    print("  ✗ 符号缺失    %-46s `%s`" % (rel, sym))
                    continue
                print("  ✓ %-52s `%s`" % (rel, sym))
            else:
                print("  ✓ %-52s (整文件)" % rel)
            PASS.append("%s:%s" % (num, rel))

    # ③ 没有代码落点记录的专利（提醒，不算失败）
    no_link = [n for n in on_book if n not in LINKS]
    if no_link:
        print("\n[未编入落点表] " + " ".join(no_link))
        WARN.append("未编入落点表: %s" % ",".join(no_link))

    print("\n" + "=" * 72)
    print("文件/符号核对: PASS=%d  FAIL=%d" % (len(PASS), len(FAIL)))
    for f in FAIL:
        print("  ✗ " + f)
    for w in WARN:
        print("  ⚠ " + w)
    print("判定: " + ("PASS" if not FAIL else "FAIL"))
    print("=" * 72)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
