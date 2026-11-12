---
name: module-relocation-shims
title: "Module Relocation with Alias Shims"
description: "Use when 搬模块到新包且老 import 不断。"
version: 1.0.0
author: Hermes Agent
license: MIT
trigger: "Use when 核心逻辑混在 GUI/工具目录要搬到 src/, 或搬完出现 ImportError、路径错、功能静默失效, 或要写同一对象类的分层判据。"
metadata:
  hermes:
    tags: [refactor, relocation, imports, packaging, verification]
    related_skills: [zmax-console, pyqt5-distribution, integration-level-audit]
---

# 模块归位 + 别名 shim (老 import 一行不改)

## When to Use
- 某目录(典型 `tools/gui`)被当默认堆放处: 零 GUI 依赖的引擎/服务/特征模块与界面代码混在一起。
- 已搬完但出现 `ImportError`、路径指错、功能“静默没生效”。
- 要写“搬得对不对”的判据(真身/别名/分层)。

## 步骤

### 1. 先审计, 再动手
```bash
for f in <dir>/*.py; do printf '%6s %s\n' "$(wc -l < $f)" "$f"; done | sort -rn | head -20
md5sum <dir>/*.py | sort | awk '{print $1}' | uniq -d      # 逐字节重复文件
grep -rln --include=*.py --include=*.sh "<mod>" . | grep -v -e docs/ -e reports/   # 引用方
```
- 逐字节重复的大文件、零引用孤儿文件: **直接 `git rm`**, 不搬。
- 判“被引用”只查代码区; `docs/ reports/` 里的是留痕, 不是引用。

### 2. 判定搬迁资格
- 搬 = **零 GUI 依赖 + 是逻辑不是画面**(引擎运行时/服务端/特征/中间件/工具)。
- 依赖 GUI 模块的先进 allowlist 并**写明理由**, 别为了搬得干净去硬拆(会引入循环 import)。

### 3. `git mv` + 原地留 ≤40 行 shim
```bash
git mv <dir>/<mod>.py src/<pkg>/<域>/<mod>.py     # 保留历史; 新目录要 __init__.py
```
shim 模板见 `templates/shim.py`。四个要点缺一不可:
1. 原文件若有 `from __future__`, shim 里**必须仍是第一行**(路径探测放前面 = `SyntaxError`)。
2. 路径探测要兼容冻结包: `hasattr(sys, "_MEIPASS")` 时真身在 `<_MEIPASS>/src`。
3. 仓库根**不按层数**, 按目录标记上溯(见模板)。
4. 最后 `sys.modules[__name__] = <真身模块>`, 塞的是**模块对象**, 不是包; 这样模块级全局只有一份,
   `isinstance` / `is` 判断不失效, 老 import 一行不改。

### 4. 迁完必改的三类引用
| 类别 | 症状 | 做法 |
|---|---|---|
| 仓库根推导 | 数据/工具路径全指到 `src/<pkg>` | `dirname×N(__file__)` → `_repo_root()`: 向上找“同时含 `src/<pkg>` 与 `tools`”的那层 |
| 模块级执行顺序 | 只在某些 import 顺序下 `NameError` | helper 必须先定义再被模块级调用; `sys.path.insert` 不能写在 helper 之后 |
| 工具链/打包硬编码 | 版本升级静默 no-op、冻结包缺包 | 改版本脚本/完整性判据/文档同步/CI `--add-data`; 扫 `grep -rn "<dir>/<mod>.py" tools/ .github/` |

### 4b. 单体拆分: 一个文件 N 个函数 → 一符号一文件 (同一套 shim 思路)

仓库里常见「注册表大文件」(上千行、上百个 `node_*`/`handle_*`), 所有注册 key 的 file/line 都指它 ⇒
不管点哪个功能, 「打开源码」都落到同一个大文件, 用户会认为代码丢了或存在两套实现。定式:

1. `ast.get_source_segment` 精确切函数源码 (**一字不改**, 不要重新格式化);
2. 遍历函数内 Load 名的自由变量 ∩ 原模块的模块级名 → 生成**显式** `from .<原模块> import (...)`;
   **不要** `globals().update(vars(orig))`: 函数内的赋值/`global` 会落到错误的命名空间, 且快照会过期;
3. 原位置留同名薄壳转调 (`def f(*a): from .<新模块> import f as _i; return _i(*a)`) ⇒ 老调用方与老 import 不断;
4. **重注册到真身**: 注册表通常用 `inspect.getsourcefile(fn)` 记录位置, 所以壳注册仍指壳文件。
   在注册完之后用真身再 `register(key, …, 真身函数)` 覆盖一次 (幂等), 「打开源码」才会落到符号自己的文件;
5. 拆完立刻自检: 新进程整包导入 + **全部注册 key 可调用**; 任一失败 `cp` 回滚这一个, 不要带着坏状态继续。

拆一符号就验一次, 不要拆 50 个才跑一次 —— 失败时你分不清是哪一个把包弄坏的。

**拆分类陷阱**
- **本模块的同名全局可能不是真源表**: 实测 `module.NODE_LOGIC` 是空 dict, 真表在 `registry.NODE_LOGIC`。
  重注册/查表一律直接问注册表模块, 别用本模块变量, 否则「重注册成功」其实 0 条且不报错。
- **多个 key 共用一个实现**: 第二个 key 切出来只是转调壳 ⇒ 合并到主文件, 其余 key 直接指向同一模块同一函数;
  链式引用 (A→B→C) 要**扁平化到最终真文件**, 否则会指向已删除的中间壳。
- **函数里有 `global X`**: 机械迁移会把全局变成两份。人工迁: 在新模块顶部 `X = None`, 保留原 `global X` —— 全局归符号自己。
- **生成物的文件名占位符**: 模块名常不等于 `<id>.py` (`ssyolo` → `n_yolo.py`)。占位符要在**写盘时**按真实 basename 替换,
  不能在渲染函数里按 id 拼 —— 否则文件头写着不存在的文件名。
- **验收要比数字**: 「指向大文件的符号数 N → 0」· 注册 key 数不变 · 不可调用 key == 0 · 随机抽一个 key 真调用返回非 None。

### 5. 判据(写成脚本进仓库, 别靠肉眼)
| 判据 | 做法 |
|---|---|
| 真身在位 | 每个登记模块的真身文件存在且非空 |
| shim 够薄 | 每个 shim ≤40 行 |
| **别名正确** | `import <old> as M` 后 `os.path.realpath(M.__file__) == 真身路径` |
| 同一对象 | `M is importlib.import_module("<pkg>.<域>.<mod>")` |
| 零 GUI 依赖 | 真身 `grep -c PyQt` == 0 |
| 不许堆放 | 目录里未登记的零 Qt 大块逻辑 ⇒ 失败; allowlist 每条带理由 |
| 死文件确实没了 | 删掉的文件不存在 |

## Pitfalls
1. **“import 成功”不是别名正确的判据** —— shim 指到包的 `__init__` 也照样 import 成功, 拿到的是空模块,
   功能整体静默失效。一律比 `M.__file__` / realpath / `M is 真身`。
2. **按层数推仓库根必错**: 搬完 `__file__` 深了两层, `dirname×3` 指到包里 ⇒ 数据目录/工具路径无声错位。
   改成按目录标记上溯, 并把这类写法当成搬迁必修项扫一遍。
3. **判据脚本取子进程输出的最后一行**: 模块 import 时可能已打印日志, 只有末行是判据结论。
4. **模块名解析要用完整路径**: 生成 shim 的脚本里, `from <pkg> import <mod>` 的落点必须解析成 `<mod>` 的
   文件路径; 图省事取 `pkg.__file__` 会给出一批“假别名”。
   **重新生成时不要以已有 shim 的 import 行为输入** —— 上一次生成的坏 shim 会被原样再生成一遍
   (`from <pkg> import <mod>` 被当成包 `pkg.mod`), 看着“修过了”其实没变。真源只有一个: 登记表里的**真身文件路径**
   → 反推模块全名 (`src/a/b/c.py` → `a.b.c`)。
5. **跨平台打包**: 新包要在 Windows/macOS/Linux 的 `--add-data` 里都列上, shim 的路径探测要能走 `_MEIPASS`;
   否则源码树里全绿、冻结包里 import 不到。
6. **已经在跑的进程仍握着旧代码**: 搬完/修完必须让用户重启他们的实例(不替用户重启正在调试的实例),
   并用“进程启动时间 vs 修复提交时间”对比说明他当前看到的是什么。

## 收益与代价
- 收益: 依赖方向理清(GUI → src, 不再反向依赖工具目录), 三平台打包共用一份 add-data 清单。
- 代价: 模块改以真名进 `sys.modules` ⇒ 调试器断点能绑上(`spec_from_file_location` 不注册是“断点空心”的
  一类根因); 但一次性大面积搬迁必须配判据, 否则靠人眼永远查不出“假别名”。
