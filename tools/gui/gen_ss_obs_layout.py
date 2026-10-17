# -*- coding: utf-8 -*-
"""兼容层 · 真身已归位: tools/gen/ss_obs_layout.py

`import gen_ss_obs_layout` / `from gen_ss_obs_layout import X` 都拿到真身同一个模块对象 (sys.modules 直接换掉),
模块级全局共享, 不会出现两份状态。新代码请直接 `from ss_obs_layout import ...`。

🌍 跨平台: 源码运行时找 <仓库根>/src; PyInstaller 冻结运行时找 <_MEIPASS>/src
   (打包 job 用 --add-data 把 src/lerobot/<pkg> 放进包内), Windows/macOS/Linux 同一份逻辑。
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
_MP = getattr(sys, "_MEIPASS", "") or ""

for _p in (_ROOT, _HERE):
    for _c in (os.path.join(_p, "src"), os.path.join(_p, "tools", "gen"), _p):
        if _c and os.path.isdir(_c) and _c not in sys.path:
            sys.path.insert(0, _c)
if _MP:
    for _c in (os.path.join(_MP, "src"), _MP, os.path.join(_MP, "tools", "gen")):
        if _c and os.path.isdir(_c) and _c not in sys.path:
            sys.path.insert(0, _c)

import ss_obs_layout as _mod

sys.modules[__name__] = _mod
