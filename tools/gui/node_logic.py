# -*- coding: utf-8 -*-
"""⚠️ 兼容壳 (compat shim) —— 节点逻辑已整体迁到 `src/lerobot/engineering/` (2026-09-28)。

本文件**不再包含任何节点逻辑**, 只把包命名空间转发给老调用方, 保证
`import node_logic` / `from node_logic import execute_node_logic, match_node, NODE_LOGIC ...`
这些历史写法继续可用 (控制台 studio.py / simulink_module.py / 各 tools 脚本)。

    · 逻辑真源   : src/lerobot/engineering/nodes/library.py   (141 条节点逻辑, 147 个注册 key)
    · 注册表     : src/lerobot/engineering/registry.py        (key ↔ 节点名关键字 ↔ 函数 ↔ 文件)
    · 执行派发   : src/lerobot/engineering/runtime.py         (execute_node_logic / trace / 演示)
    · 源码定位   : src/lerobot/engineering/sourceview.py      (查看/改逻辑/恢复默认)
    · 画布 JSON  : src/lerobot/engineering/flows/state_space_obs.json   (+ 备份/校验 flows.py)
    · 档位契约   : src/lerobot/engineering/levels.py          (L2/L3/L4/L5 必须还能干的事 + check())

新增或修改节点逻辑: 请改包里那份 (同一处), **不要写回 GUI 目录**。
新代码请直接:  sys.path.insert(0, "<repo>/src");  from lerobot.engineering import execute_node_logic
"""
import os
import sys


def _src_candidates():
    """工程根 (`<repo>/src`) 的候选表 —— 冻结包与源码两种布局都要能命中。

    🔴 2026-10-08 定因 (老倪 Windows 版起不来): 冻结包里 `__file__` = `_MEIPASS/node_logic.py`,
       老写法 `dirname(__file__)/../../src` 指到**临时目录的父级** → `import lerobot` 抛
       `ModuleNotFoundError: No module named 'lerobot'`, 而这条导入在 studio.py 启动第 258 行,
       整个控制台**双击即崩**(不是某个按钮坏)。CI 已用 --add-data 把 `src/lerobot/engineering`
       放进 `_MEIPASS/src/...`, 所以冻结时按候选表找, 不再靠相对上溯。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    meipass = getattr(sys, "_MEIPASS", "") or ""
    cands = []
    if getattr(sys, "frozen", False):
        cands += [os.path.join(here, "src"),                       # --add-data 与本地模块同级
                  os.path.join(meipass, "src"),                    # 标准冻结布局
                  os.path.join(meipass, "..", "src"),
                  os.path.abspath(os.path.join(here, "..", "..", "src"))]
    else:
        cands.append(os.path.abspath(os.path.join(here, "..", "..", "src")))
    env = os.environ.get("ZMAX_SRC_DIR")
    if env:                                                        # 现场兜底: 手动指定工程根
        cands.insert(0, env)
    return cands


def _pick_src():
    for c in _src_candidates():
        if c and os.path.isdir(os.path.join(c, "lerobot", "engineering")):
            return c
    return _src_candidates()[0]


_SRC = _pick_src()
if _SRC not in sys.path:
    sys.path.append(_SRC)        # 追加而非插最前: 不改动 tools/gui 既有的模块解析顺序

try:
    import lerobot.engineering as _E  # noqa: E402
except ModuleNotFoundError as _e:
    raise ModuleNotFoundError(
        "控制台缺少工程包 lerobot.engineering (141 条节点逻辑 + 画布真源都在里面)。\n"
        f"  尝试过的工程根: {_src_candidates()}\n"
        "  · 源码运行: 确认仓库内存在 src/lerobot/engineering/\n"
        "  · 打包版 (exe/.app): 当前包是用**旧打包配置**构建的 (未随包附带 src/lerobot/engineering)\n"
        "    → 请升级到修复版 exe (打包已加 --add-data src/lerobot/engineering)\n"
        f"  原始错误: {_e}"
    ) from _e

for _n in dir(_E):
    if not _n.startswith("__"):
        globals()[_n] = getattr(_E, _n)

LOGIC_HOME = _E.paths.LOGIC_FILE          # 逻辑真源路径 (提示/VSCode 打开用)
CANVAS_JSON = _E.paths.canvas_json()      # 画布 JSON 真源
__all__ = [n for n in dir(_E) if not n.startswith("_")]
