# -*- coding: utf-8 -*-
"""统一模块加载器 —— **正常 import 优先**，spec 兜底 (老倪 2026-10-31: 每个节点 return 处都要能进断点)

为什么必须走正常 import:
    pydevd 只在 `builtins.__import__` 这条路上埋钩子; 用
    `spec_from_file_location(...).loader.exec_module(m)` 直装的模块**绕开导入钩子** ⇒ 该文件里的
    断点静默不绑定 (本机 debugpy 又没编 _pydevd_frame_eval, 对已加载模块运行时补绑也不行)。
    ⇒ 现象: 红点在、代码在跑、永远不停, 且不报任何错。

用法（原 spec 三行替换成一行）:
    from lerobot.engineering.modload import load as _load_mod
    m = _load_mod("lerobot.manifold.manifold_layer", path)      # 名字按包路径给
    m = _load_mod("tools.intact_sw_optical_bridge", path)       # tools/ 下的脚本也支持

保证:
    · 名字已存在且指向同一文件 ⇒ 直接复用 (不重复执行模块体)；
    · 正常 import 拿到的文件与 path 不一致 / 失败 ⇒ 退回原来的 spec 加载，并在终端留一行原因
      (绝不静默, 也不改任何调用方行为)。
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# 走 spec 兜底的模块 (真实路径): 这些文件里的断点 pydevd 绑不上, 验证工具据此判定
SPEC_LOADED: set = set()


def mark_spec(path) -> None:
    try:
        SPEC_LOADED.add(os.path.realpath(str(path)))
    except Exception:
        pass


def is_spec(path) -> bool:
    try:
        return os.path.realpath(str(path)) in SPEC_LOADED
    except Exception:
        return False


def _log(msg: str) -> None:
    print("[modload] " + msg, flush=True)


def _rel(p: str) -> str:
    p = str(p)
    return p[len(ROOT) + 1:] if p.startswith(ROOT) else p


def _candidates(name: str, path: str) -> list:
    """[(sys.path 根, 模块名)] —— 能把这个文件按**正常 import** 拿到的所有走法。

    关键: 调用方给的 name 常常≠文件名 (如 "zmax_board_frame_module" ← board_frame_module.py),
    这时按文件名反推包路径; 包目录一层层往上找 (带 __init__.py 的都算), 拿到
        src/ + lerobot.policies.left_right.state_space.skills.atomic_skills
    这种真实包名 —— 这正是 pydevd 认的名字。
    """
    real = os.path.realpath(path)
    stem = os.path.splitext(os.path.basename(real))[0]
    out = []

    def _add(root, modname):
        t = (os.path.realpath(root), modname)
        if root and t not in out:
            out.append(t)

    # ① 按调用方给的名字 (名字对得上文件名的情况)
    if name.split(".")[-1] == stem:
        if name.startswith("lerobot."):
            _add(os.path.join(ROOT, "src"), name)
        d = os.path.dirname(real)
        for _ in range(max(0, len(name.split(".")) - 1)):
            d = os.path.dirname(d)
        _add(d, name)
        if name.split(".")[0] in ("tools", "tool"):
            _add(ROOT, name)

    # ② 按文件名反推真包名 (src/lerobot/... 这种)
    parts, d = [stem], os.path.dirname(real)
    while os.path.isfile(os.path.join(d, "__init__.py")):
        parts.insert(0, os.path.basename(d))
        d = os.path.dirname(d)
    _add(d, ".".join(parts))                     # 顶层包 (如 lerobot.policies...)

    # ③ 裸文件名 (tools/ 下的独立脚本)
    _add(os.path.dirname(real), stem)
    return out


def load(name: str, path: str, quiet: bool = False):
    """取模块: 优先 importlib (pydevd 可绑断点), 失败退回 spec (旧行为)。"""
    real = os.path.realpath(path)
    m = sys.modules.get(name)
    if m is not None and os.path.realpath(getattr(m, "__file__", "") or "") == real:
        return m
    last = None
    for root, modname in _candidates(name, path):
        if root not in sys.path:
            sys.path.insert(0, root)
        try:
            mod = importlib.import_module(modname)
        except Exception as e:                                          # noqa: BLE001
            last = "%s: %s" % (type(e).__name__, e)
            continue
        if os.path.realpath(getattr(mod, "__file__", "") or "") == real:
            if modname != name:                     # 兼容旧名 (调用方后面还用 name 取)
                sys.modules.setdefault(name, mod)
            if not quiet:
                _log("正常 import %s%s ← %s (断点可绑)"
                     % (modname, "" if modname == name else " (别名 %s)" % name, _rel(real)))
            return mod
        last = "同名模块指向别的文件: %s" % _rel(getattr(mod, "__file__", "") or "?")
    try:
        spec = importlib.util.spec_from_file_location(name, real)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        mark_spec(real)
        if not quiet:
            _log("⚠️ spec 兜底 %s ← %s (此文件断点绑不上; 原因: %s)" % (name, _rel(real), last))
        return mod
    except Exception as e:                                              # noqa: BLE001
        _log("✖ 加载失败 %s ← %s: %s: %s" % (name, _rel(real), type(e).__name__, e))
        raise
