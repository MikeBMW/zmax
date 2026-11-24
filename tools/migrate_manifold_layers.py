#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""migrate_manifold_layers.py — manifold 分层归位 (2026-11-24)

做三件事, 只搬不改逻辑:
  ① manifold/core/          纯数学核 (禁业务/禁 IO)
  ② manifold/engine/        引擎运行时 + 模型适配
  ③ manifold/engine/inject/ 原 policies/manifold/* 并入
老路径留 ≤12 行兼容壳 (sys.modules 别名 ⇒ 模块级全局一份, isinstance/is 不失效)。

用法:
  python tools/migrate_manifold_layers.py --plan      # 只看清单
  python tools/migrate_manifold_layers.py --apply     # 真搬 + 生成壳
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

ROOT = os.environ.get("ZMAX_ROOT", "/home/ubuntu/zmax")
MANI = os.path.join(ROOT, "src/lerobot/manifold")
POLI = os.path.join(ROOT, "src/lerobot/policies/manifold")

CORE = ["metric_field", "se3_chain", "s3_chain", "fiber_bundle", "lie_intent",
        "manifold10d", "manifold_layer", "energy_manifold"]
ENGINE = ["engine_loop", "manifold_engine", "se3_engine", "realtime_map",
          "hjepa_model", "hjepa_manifold", "hjepa_manifold_provider", "hjepa_m3",
          "hjepa_mr_layers", "hjepa_state", "hjepa_live", "encoder_model", "encoder_vlm"]
INJECT = ["geodesic_inject", "inject_cfg", "metric_inject", "wm_adapter", "wm_verify"]

SHIM = '''# -*- coding: utf-8 -*-
"""兼容壳 (2026-11-24 分层归位): 真身 = {new}。

老 import 一行不改; 判据: import 后 realpath(__file__) == 真身, 且 is 真身模块。
"""
import importlib as _il
import sys as _sys

_sys.modules[__name__] = _il.import_module("{new}")
'''


def sh(p: str) -> None:
    subprocess.run(p, shell=True, cwd=ROOT, check=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    plan = ([("core", m, os.path.join(MANI, m + ".py")) for m in CORE]
            + [("engine", m, os.path.join(MANI, m + ".py")) for m in ENGINE]
            + [("engine/inject", m, os.path.join(POLI, m + ".py")) for m in INJECT])

    missing = [(sub, m, src) for sub, m, src in plan if not os.path.exists(src)]
    print("搬迁清单: %d 个模块" % len(plan))
    for sub, m, src in plan:
        print("  %-14s %-24s ← %s%s" % (sub, m, os.path.relpath(src, ROOT),
                                        "" if os.path.exists(src) else "   << 缺失"))
    if missing:
        print("缺 %d 个, 先停" % len(missing))
        return 1
    if a.plan or not a.apply:
        print("(只出计划; 加 --apply 执行)")
        return 0

    for d in ("core", "engine", "engine/inject"):
        os.makedirs(os.path.join(MANI, d), exist_ok=True)
        init = os.path.join(MANI, d, "__init__.py")
        if not os.path.exists(init):
            title = {"core": "纯数学核: 度规/李群/流形层 (禁业务 import, 禁 IO)",
                     "engine": "引擎运行时与模型适配 (可依赖 core 与 policies 权重)",
                     "engine/inject": "流形注入 (测地线/度量注入/世界模型适配)"}[d]
            with open(init, "w", encoding="utf-8") as fh:
                fh.write('# -*- coding: utf-8 -*-\n"""%s"""\n' % title)

    moved = 0
    for sub, m, src in plan:
        dst = os.path.join(MANI, sub, m + ".py")
        if os.path.exists(dst):
            print("  跳过(已存在): %s" % os.path.relpath(dst, ROOT))
            continue
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch", src],
                                 cwd=ROOT, capture_output=True).returncode == 0
        if tracked:
            sh("git mv '%s' '%s'" % (src, dst))
        else:                                    # 未入库的新文件: 直接搬, 稍后 git add
            os.replace(src, dst)
        new_mod = "lerobot.manifold.%s.%s" % (sub.replace("/", "."), m)
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(SHIM.format(new=new_mod))
        moved += 1
        print("  搬 %-24s → %-40s + 壳" % (m, os.path.relpath(dst, ROOT)))

    # 跨层相对 import 必须改成绝对 (engine → core)
    p = os.path.join(MANI, "engine/se3_engine.py")
    if os.path.exists(p):
        s = open(p, encoding="utf-8").read()
        if "from .se3_chain import" in s:
            s = s.replace("from .se3_chain import", "from lerobot.manifold.core.se3_chain import")
            open(p, "w", encoding="utf-8").write(s)
            print("  修相对 import: engine/se3_engine.py → core.se3_chain")

    print("完成: 搬 %d 个, 壳 %d 个" % (moved, moved))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
