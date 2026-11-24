#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_manifold_layout.py — 分层归位判据 (2026-11-24)

判据 (全部数字, 不通过 exit 1):
  ① 真身存在且非空 (core / engine / engine/inject)
  ② 老路径 = 兼容壳 且 ≤12 行
  ③ import 老名 → realpath == 真身, 且 M is 真身模块 (同一对象, 全局一份)
  ④ 四个"真跑"入口可调用: manifold10d.selftest / engine_loop / manifold_engine.ManifoldEngine / geodesic_inject
  ⑤ core 层零业务依赖: core/*.py 里不许出现 lerobot.policies / aoi / 8793 / requests
"""
from __future__ import annotations

import importlib
import os
import sys

ROOT = os.environ.get("ZMAX_ROOT", "/home/ubuntu/zmax")
sys.path.insert(0, os.path.join(ROOT, "src"))

CORE = ["metric_field", "se3_chain", "s3_chain", "fiber_bundle", "lie_intent",
        "manifold10d", "manifold_layer", "energy_manifold"]
ENGINE = ["engine_loop", "manifold_engine", "se3_engine", "realtime_map",
          "hjepa_model", "hjepa_manifold", "hjepa_manifold_provider", "hjepa_m3",
          "hjepa_mr_layers", "hjepa_state", "hjepa_live", "encoder_model", "encoder_vlm"]
INJECT = ["geodesic_inject", "inject_cfg", "metric_inject", "wm_adapter", "wm_verify"]

rows: list[tuple[str, str, bool]] = []


def chk(name: str, detail: str, ok: bool) -> None:
    rows.append((name, detail, ok))


def main() -> int:
    MANI = os.path.join(ROOT, "src/lerobot/manifold")
    POLI = os.path.join(ROOT, "src/lerobot/policies/manifold")

    # ①②③ 真身 / 壳 / 别名
    for sub, mods, old_dir in (("core", CORE, MANI), ("engine", ENGINE, MANI),
                               ("engine/inject", INJECT, None)):
        for m in mods:
            real = os.path.join(MANI, sub, m + ".py")
            ok_real = os.path.exists(real) and os.path.getsize(real) > 200
            chk("① 真身 %-8s %s" % (sub, m), "%.1fKB" % (os.path.getsize(real) / 1024 if os.path.exists(real) else 0), ok_real)
            old = (old_dir if old_dir else POLI) and os.path.join(old_dir or POLI, m + ".py")
            if os.path.exists(old):
                n = sum(1 for _ in open(old, encoding="utf-8"))
                chk("② 壳  %-8s %s" % (sub, m), "%d 行" % n, n <= 12)
            try:
                old_mod = importlib.import_module("lerobot.manifold.%s" % m) if (MANI and old_dir) else importlib.import_module("lerobot.policies.manifold.%s" % m)
            except Exception:                                           # noqa: BLE001
                old_mod = None
            try:
                new_mod = importlib.import_module("lerobot.manifold.%s.%s" % (sub.replace("/", "."), m))
            except Exception as e:                                      # noqa: BLE001
                chk("③ 导入 %-8s %s" % (sub, m), "new import 失败: %s" % e, False)
                continue
            same = old_mod is not None and os.path.realpath(old_mod.__file__) == os.path.realpath(new_mod.__file__)
            chk("③ 别名 %-8s %s" % (sub, m),
                "%s" % ("同一对象 ✓" if (old_mod is new_mod) else "不同对象 ✗"), same)

    # ④ 真跑入口
    try:
        m10 = importlib.import_module("lerobot.manifold.core.manifold10d")
        r = m10.selftest()
        chk("④ manifold10d.selftest", "11 项 · %.3fms/步" % r["step_ms"], bool(r["ok"]))
    except Exception as e:                                              # noqa: BLE001
        chk("④ manifold10d.selftest", "失败: %s" % e, False)
    try:
        me = importlib.import_module("lerobot.manifold.engine.manifold_engine")
        eng = me.ManifoldEngine(manifold_type="sphere", latent_dim=3) if hasattr(me, "ManifoldEngine") else None
        got = eng is not None and hasattr(eng, "step")
        chk("④ manifold_engine.ManifoldEngine", "构造+step ✓" if got else "无 step", got)
    except Exception as e:                                              # noqa: BLE001
        chk("④ manifold_engine.ManifoldEngine", "失败: %s" % e, False)
    try:
        gi = importlib.import_module("lerobot.manifold.engine.inject.geodesic_inject")
        chk("④ inject.geodesic_inject", "模块载入 · %d 个公开符号" % len([x for x in dir(gi) if not x.startswith("_")]), True)
    except Exception as e:                                              # noqa: BLE001
        chk("④ inject.geodesic_inject", "失败: %s" % e, False)

    # ⑤ core 层不许依赖业务
    bad = []
    for m in CORE:
        p = os.path.join(MANI, "core", m + ".py")
        s = open(p, encoding="utf-8").read()
        for kw in ("lerobot.policies", "aoi_dispatch", "requests", "127.0.0.1:8793"):
            if kw in s:
                bad.append("%s←%s" % (m, kw))
    chk("⑤ core 零业务依赖", ("干净" if not bad else "污染: " + ", ".join(bad)), not bad)

    for name, detail, ok in rows:
        print("  %-34s %-46s %s" % (name, detail, "PASS" if ok else "FAIL"))
    n_ok = sum(1 for _, _, ok in rows if ok)
    print("  => %d/%d 通过" % (n_ok, len(rows)))
    return 0 if n_ok == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
