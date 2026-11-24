#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_manifold_after_move.py — 搬完 manifold 分层后, 把跨层 import 改成完整包名

为什么必须做: 这些文件原来都住在 src/lerobot/manifold/ 一层, 靠 `sys.path.insert(manifold)`
裸 `import health / import su2 / import pose_caliper` 就能跑。搬进 core/ engine/ 后裸名必
ModuleNotFoundError —— 且只在真 import 时炸, 静态检查看不出来。

🔴 实现红线: 一律用 re.sub + 回调**单遍替换**。上一版用 finditer 记录的 start/end 偏移去切片,
前面替换一变长度, 后面偏移就错位 —— 实测把
`from .lie_intent import se3_log` 写成 `from ... import rom .lie_intent import se3_log`,
整个模块 SyntaxError。偏移式批量改写本身是错的, 不是笔误。
"""
from __future__ import annotations

import os
import re
import subprocess

ROOT = "/home/ubuntu/zmax"
MANI = os.path.join(ROOT, "src/lerobot/manifold")
LEGACY = os.path.join(ROOT, "src/lerobot/policies/left_right/state_space")

CORE = {"metric_field", "se3_chain", "s3_chain", "fiber_bundle", "lie_intent",
        "manifold10d", "manifold_layer", "energy_manifold", "pose_caliper", "su2"}
ENGINE = {"engine_loop", "manifold_engine", "se3_engine", "realtime_map", "hjepa_model",
          "hjepa_manifold", "hjepa_manifold_provider", "hjepa_m3", "hjepa_mr_layers",
          "hjepa_state", "hjepa_live", "encoder_model", "encoder_vlm"}
INJECT = {"geodesic_inject", "inject_cfg", "metric_inject", "wm_adapter", "wm_verify"}


def pkg_of(name: str) -> str | None:
    if name in CORE:
        return "lerobot.manifold.core"
    if name in ENGINE:
        return "lerobot.manifold.engine"
    if name in INJECT:
        return "lerobot.manifold.engine.inject"
    if (os.path.exists(os.path.join(MANI, name + ".py"))
            or os.path.isdir(os.path.join(MANI, name))):
        return "lerobot.manifold"
    return None


def move_upstream() -> None:
    """pose_caliper / su2 是纯 numpy 几何工具, 原住在 policies/left_right/state_space __
    归 core; 老位置留壳。"""
    for name in ("pose_caliper", "su2"):
        src = os.path.join(LEGACY, name + ".py")
        dst = os.path.join(MANI, "core", name + ".py")
        if os.path.exists(dst) or not os.path.exists(src):
            continue
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch", src],
                                 cwd=ROOT, capture_output=True).returncode == 0
        if tracked:
            subprocess.run(["git", "mv", src, dst], cwd=ROOT, check=True)
        else:
            os.replace(src, dst)
        with open(src, "w", encoding="utf-8") as fh:
            fh.write('# -*- coding: utf-8 -*-\n"""兼容壳 (2026-11-24 归位): 真身 = '
                     'lerobot.manifold.core.%s"""\nimport importlib as _il\nimport sys as _sys\n\n'
                     '_sys.modules[__name__] = _il.import_module("lerobot.manifold.core.%s")\n'
                     % (name, name))
        print("搬 %s.py → core/ (+壳)" % name)


def fix_file(path: str) -> tuple[int, int]:
    s = open(path, encoding="utf-8").read()
    n = [0, 0]

    def _rel(m: re.Match) -> str:
        ind, mod = m.group("ind"), m.group("mod")
        pk = pkg_of(mod)
        if not pk:
            return m.group(0)
        n[1] += 1
        return "%sfrom %s.%s import " % (ind, pk, mod)

    def _rel_multi(m: re.Match) -> str:
        ind, mod, alias = m.group("ind"), m.group("mod"), m.group("alias")
        pk = pkg_of(mod)
        if not pk:
            return m.group(0)
        n[1] += 1
        return "%sfrom %s import %s as %s" % (ind, pk, mod, alias)

    def _bare(m: re.Match) -> str:
        ind, mod = m.group("ind"), m.group("mod")
        alias, tail = m.group("alias") or "", m.group("tail") or ""
        pk = pkg_of(mod)
        if not pk:
            return m.group(0)
        n[0] += 1
        return "%sfrom %s import %s%s%s" % (ind, pk, mod, alias, tail)

    s = re.sub(r"^(?P<ind>[ \t]*)from \.(?P<mod>[a-z_][a-z0-9_]*) import ", _rel, s, flags=re.M)
    s = re.sub(r"^(?P<ind>[ \t]*)from \. import (?P<mod>[a-z_][a-z0-9_]*) as (?P<alias>\w+)",
               _rel_multi, s, flags=re.M)
    s = re.sub(r"^(?P<ind>[ \t]*)import (?P<mod>[a-z_][a-z0-9_]*)(?P<alias> as [A-Za-z_]\w*)?"
               r"(?P<tail>[ \t]*(?:#.*)?)$", _bare, s, flags=re.M)
    if n[0] or n[1]:
        open(path, "w", encoding="utf-8").write(s)
        print("  修 %-52s 裸 %d / 相对 %d" % (os.path.relpath(path, ROOT), n[0], n[1]))
    return n[0], n[1]


def main() -> int:
    move_upstream()
    files = []
    for d in ("core", "engine", "engine/inject"):
        files += [os.path.join(MANI, d, f) for f in sorted(os.listdir(os.path.join(MANI, d)))
                  if f.endswith(".py")]
    a = b = 0
    for p in files:
        x, y = fix_file(p)
        a, b = a + x, b + y
    # 语法总闸: 任一文件语法错就停
    bad = []
    for p in files:
        try:
            compile(open(p, encoding="utf-8").read(), p, "exec")
        except SyntaxError as e:
            bad.append("%s:%s %s" % (os.path.relpath(p, ROOT), e.lineno, e.msg))
    print("完成: 裸 %d / 相对 %d · 语法错 %d" % (a, b, len(bad)))
    for x in bad:
        print("  ✗", x)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
