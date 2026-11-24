# 分层归位: 搬 20+ 模块到 core / engine / app 的脚本骨架

配套 SKILL.md §3c。三个脚本按顺序跑, 每一步都有可报的数字。

## 0. 先分类 (决定谁去哪一层)

| 层 | 放什么 | 硬判据 |
|---|---|---|
| `core/` | 度规/李群/算子/几何编码等纯计算 | 无业务 import、无 IO、无网络、无 GUI |
| `engine/` | 引擎主类、循环、provider、encoder、实时图 | 可依赖权重与 core, 不做业务调度 |
| `engine/inject/` | 注入/适配壳 (原寄居在业务包里的 `*_inject`, `wm_adapter`) | 只做参数注入与适配 |
| `app/<域>/` | 调度、健康、相位、建图、昼夜等编排 | 可以 import 前两层, 反向绝对禁止 |

判 core 的实操办法: 对候选文件 `grep -nE "^(from|import)"` 逐个看, 出现 `lerobot.policies`、
`requests`、具体 IP、或**裸业务模块名** ⇒ 不合格。裸名要靠 AST 扫 (§2), grep 抓不到。

一发现「core 候选者在 import 业务包里的纯工具」(实测 `s3_chain` 裸 `import pose_caliper`, 真身住在
`policies/left_right/state_space/`), 正确动作是**把那个纯工具搬进 core 并给老位置留壳**, 不是把它留在业务侧。

## 1. 搬迁脚本 (--plan / --apply)

```python
plan = ([("core", m, os.path.join(MANI, m + ".py")) for m in CORE]
        + [("engine", m, os.path.join(MANI, m + ".py")) for m in ENGINE]
        + [("engine/inject", m, os.path.join(POLI, m + ".py")) for m in INJECT])

SHIM = '''# -*- coding: utf-8 -*-
"""兼容壳 (分层归位): 真身 = {new}。"""
import importlib as _il
import sys as _sys

_sys.modules[__name__] = _il.import_module("{new}")
'''

for sub, m, src in plan:
    dst = os.path.join(MANI, sub, m + ".py")
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", src],
                             cwd=ROOT, capture_output=True).returncode == 0
    if tracked:
        subprocess.run(["git", "mv", src, dst], cwd=ROOT, check=True)
    else:                                    # 🔴 untracked: git mv 会 128
        os.replace(src, dst)
    open(src, "w", encoding="utf-8").write(SHIM.format(
        new="lerobot.manifold.%s.%s" % (sub.replace("/", "."), m)))
```

- 新目录每个都要 `__init__.py`(写一句该层的职责说明, 它就是分层约定的落点)。
- 壳一律 ≤12 行, 判据里要卡行数。
- **回滚前先列 `git status --porcelain` 与 untracked 清单**: `cp -a` 回滚整个目录会把「已搬走但未入库」
  的真身一起带走 (实测靠发布快照才捞回)。untracked 文件先另存 `/tmp/<模块>_pre_move/`。

## 2. 刷裸导入 / 相对导入 (单遍 re.sub)

```python
def pkg_of(name):                       # 目标现在住哪一层
    if name in CORE:   return "lerobot.manifold.core"
    if name in ENGINE: return "lerobot.manifold.engine"
    if name in INJECT: return "lerobot.manifold.engine.inject"
    if os.path.exists(os.path.join(MANI, name + ".py")): return "lerobot.manifold"
    return None

s = re.sub(r"^(?P<ind>[ \t]*)from \.(?P<mod>[a-z_][a-z0-9_]*) import ", _rel, s, flags=re.M)
s = re.sub(r"^(?P<ind>[ \t]*)from \. import (?P<mod>\w+) as (?P<alias>\w+)", _multi, s, flags=re.M)
s = re.sub(r"^(?P<ind>[ \t]*)import (?P<mod>[a-z_][a-z0-9_]*)(?P<alias> as [A-Za-z_]\w*)?"
           r"(?P<tail>[ \t]*(?:#.*)?)$", _bare, s, flags=re.M)
```

每个回调里: 目标不在表里就 `return m.group(0)` 原样放回; 在表里才换成 `from <pkg> import <mod>[ as X][  # 注释]`。
**不要**用 `finditer` 的 start/end 去切片 — 前一次替换变长, 后面偏移全错 (会把
`from .lie_intent import` 写成 `from ... import rom .lie_intent import`, 整模块 SyntaxError)。
改完立刻 `compile(open(p).read(), p, "exec")` 全树过一遍, 语法错 0 才往下走。

## 3. AST 扫「裸导入指向仓内模块」

```python
index = {}
for p in glob.glob(ROOT + "/src/**/*.py", recursive=True):
    index.setdefault(os.path.basename(p)[:-3], []).append(p)

for p in targets:                      # 只扫搬过的文件
    tree = ast.parse(open(p, encoding="utf-8").read())
    for n in ast.walk(tree):
        names = [a.name.split(".")[0] for a in n.names] if isinstance(n, ast.Import) else \
                ([n.module.split(".")[0]] if isinstance(n, ast.ImportFrom) and n.level == 0 and n.module else [])
        for nm in names:
            if nm in index and nm not in STD:
                print("%s:%s import %s → %s" % (p, n.lineno, nm, index[nm][0]))
```

命中数就是「靠同目录 sys.path 才能跑」的定时炸弹。实测 21 个文件里 15 处, 全部改成完整包名
(保留 `as` 别名与行尾注释)。

## 4. 整树 import 验收

```python
mods = []
for dp, dn, fn in os.walk(DIR):
    for f in fn:
        if f.endswith(".py") and f != "__init__.py":
            mods.append("lerobot.manifold." + os.path.relpath(os.path.join(dp, f), DIR)[:-3].replace("/", "."))
bad = [(m, e) for m in sorted(mods) for e in [try_import(m)] if e]
print("扫描 %d 个模块 / 失败 %d" % (len(mods), len(bad)))
```

再叠三条: ① 老名 `is` 新名 (同一模块对象); ② `realpath(老.__file__) == 真身`;
③ 注册表 key 总数不变 + `_EXTERNAL_LOC` 类落点全部存在。

## 5. 交付口径

报这些数字, 不报「都通过了」:

```
真身 28 · 壳 28 · 别名=同一对象 28
整树 import 扫描 80 / 失败 0
注册 key 162 · 落点缺失 0 · 代表节点真调 LAST_STATUS=实现执行
分层判据 82/82 (含 core 零业务依赖)
```

并明确两件后续: ① **运行中的进程仍握着旧模块**, 要重启才吃到新目录 (不替用户重启在调试的实例);
② 若中途出现过回滚事故, 直接写「哪个文件从哪个快照恢复、之后有无改动需用户补」, 不要含糊。
