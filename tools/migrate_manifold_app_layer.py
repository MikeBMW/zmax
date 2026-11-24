#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""migrate_manifold_app_layer.py — 流形目录第二刀: 运行时工具→engine/, 业务编排→app/workcell/

原则(与第一刀相同): **只搬不改逻辑**; 老路径留兼容壳(≤12 行, sys.modules 别名, 同一对象)。

分派依据(看谁 import 它, 而不是看文件名好不好听):
    capacity_stack / health / prime_structure / flight   ← 被 engine_loop、runtime、节点共用,
        是运行时协调工具 ⇒ 放 manifold/engine/ (engine 内部依赖, 不再跨层)
    aoi_dispatch / aoi_manifold / localization_mapping / daynight/
        ← 工位业务(检测派发、定位建图、夜间训练), 只被节点/GUI/工具调 ⇒ app/workcell/
"""
from __future__ import annotations

import os
import re
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MANI = os.path.join(ROOT, "src", "lerobot", "manifold")
ENGINE = os.path.join(MANI, "engine")
APP = os.path.join(ROOT, "src", "lerobot", "app", "workcell")

TO_ENGINE = ["capability_stack.py", "health.py", "prime_structure.py", "flight.py"]
TO_APP = ["aoi_dispatch.py", "aoi_manifold.py", "localization_mapping.py"]
APP_DIRS = ["daynight"]

SHIM = '''# -*- coding: utf-8 -*-
"""[兼容壳 · 2026-11-24 分层归位] 真身已移到 {rel}

只做 sys.modules 别名 (同一模块对象, isinstance/模块级全局不分裂), 不要再往这里加逻辑。
"""
import sys as _sys

from {mod} import *          # noqa: F401,F403
import {mod} as _real

_sys.modules[__name__] = _real
'''


def _tracked(rel: str) -> bool:
    r = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=ROOT,
                       capture_output=True, text=True)
    return r.returncode == 0


def move(src: str, dst: str) -> None:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    rel_src = os.path.relpath(src, ROOT)
    if os.path.isdir(src):
        subprocess.run(["git", "mv", rel_src, os.path.relpath(dst, ROOT)], cwd=ROOT, check=False) \
            if _tracked(rel_src) else subprocess.run(["mv", src, dst], check=True)
        return
    if _tracked(rel_src):
        subprocess.run(["git", "mv", rel_src, os.path.relpath(dst, ROOT)], cwd=ROOT, check=False)
    else:
        os.replace(src, dst)


def shim(old_path: str, mod: str) -> None:
    rel = mod.replace(".", "/") + ".py"
    with open(old_path, "w", encoding="utf-8") as f:
        f.write(SHIM.format(rel="src/" + rel, mod=mod))


def main() -> int:
    os.makedirs(APP, exist_ok=True)
    moved = []
    for name in TO_ENGINE:
        src = os.path.join(MANI, name)
        if os.path.exists(src):
            move(src, os.path.join(ENGINE, name))
            shim(src, "lerobot.manifold.engine." + name[:-3])
            moved.append((name, "engine/"))
    for name in TO_APP:
        src = os.path.join(MANI, name)
        if os.path.exists(src):
            move(src, os.path.join(APP, name))
            shim(src, "lerobot.app.workcell." + name[:-3])
            moved.append((name, "app/workcell/"))
    for d in APP_DIRS:
        src = os.path.join(MANI, d)
        if os.path.isdir(src):
            move(src, os.path.join(APP, d))
            moved.append((d + "/", "app/workcell/"))

    # __init__ 补齐 (app / app/workcell)
    for pkg, doc in ((os.path.join(ROOT, "src/lerobot/app"), "app 层: 业务编排 (工位/产线), 可依赖 engine 与 policies"),
                     (APP, "workcell 层: 工位业务 (AOI 派发 / 定位建图 / 夜间训练)")):
        init = os.path.join(pkg, "__init__.py")
        if not os.path.exists(init):
            with open(init, "w", encoding="utf-8") as f:
                f.write('# -*- coding: utf-8 -*-\n"""%s"""\n' % doc)

    # 跨层 import 改绝对包名: 被搬走的模块在别人的 `from . import X` / `from .X import`
    for base in (MANI, ENGINE, APP):
        for dp, _dn, fn in os.walk(base):
            if "__pycache__" in dp:
                continue
            for f in fn:
                if not f.endswith(".py"):
                    continue
                p = os.path.join(dp, f)
                s = open(p, encoding="utf-8").read()
                o = s
                for name in [x[:-3] for x in TO_ENGINE + TO_APP]:
                    tgt = ("lerobot.manifold.engine." + name) if (name + ".py") in TO_ENGINE \
                        else ("lerobot.app.workcell." + name)
                    s = re.sub(r"(?m)^(\s*)from \.%s import " % re.escape(name), r"\1from %s import " % tgt, s)
                    s = re.sub(r"(?m)^(\s*)from \. import %s\b" % re.escape(name), r"\1from %s import " % tgt, s)
                if s != o:
                    open(p, "w", encoding="utf-8").write(s)

    print("搬移 %d 项:" % len(moved))
    for n, d in moved:
        print("   %-28s → %s" % (n, d))
    print("老路径兼容壳已生成; app/workcell 包已建")
    return 0


if __name__ == "__main__":
    sys.exit(main())
