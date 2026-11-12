# 节点代码拆分 (library.py → 一节点一文件) 与三层定位

适用: 往一个 7000 行、上百个 `node_*` 的注册表大文件里加/改节点, 或用户抱怨
"右键打开的代码不是真正跑的代码" / "一会儿 library 一会儿 node" / "怎么设计的".

## 0. 先答清楚三层, 再动手

一个画布节点 = 契约 + 实现 + 算法三处:

| 处 | 文件 | 判据 |
|---|---|---|
| 契约 | `src/lerobot/middleware/nodes/n_<id>.py` | 只有 `PORTS_IN/OUT`、话题名、`PURE` 闸、`manifest()` |
| 实现 | `src/lerobot/engineering/nodes/<node_key>.py` | 取数 → 调 `policies` → 打标 |
| 算法 | `src/lerobot/policies/...` | 纯计算, 不知道节点名 |

`sourceview.get_node_triple("<node_id>")` 一次返回三处绝对路径+行号 (:1 表示文件头)。
`get_node_location(key)` 只看实现位置; 用户说"代码不见了"时先跑 triple 再答, 别猜。

生成链: 画布 JSON → `tools/gen_middleware_nodes.py` (契约 + `_index.py`) ·
`tools/gen_by_level_index.py` (档位索引) · `tools/gen_node_map.py` (三处表) ·
`tools/node_split.py` (拆分 + `impl_manifest.json`)。**五份都是生成物, 手改会在下次重生成时丢。**

## 1. 机器拆分一个节点 (安全顺序)

```bash
python tools/node_split.py --list                 # 还指向 library.py 的 (节点key, 函数)
python tools/node_split.py --key ss_yolo --dry     # 只算不写
python tools/node_split.py --key ss_yolo           # 写: 备份 + 新文件 + 薄壳 + manifest + 自检
python tools/node_split.py --all [--limit N]        # 批量, 每个拆完立刻自检, 失败回滚这一个
```

每一步做的事 (照抄, 别自己发明):
1. `ast.get_source_segment` 精确切函数源码, **一字不改**;
2. 遍历函数里 Load 名的自由变量, 与 library 模块级名字求交 → 生成**显式** `from .library import (...)`;
   不许用 `globals().update(vars(library))` —— 函数里的赋值/`global` 会落到错误命名空间;
3. 原位置换同名薄壳 `def f(ctx): from .<key> import f as _impl; return _impl(ctx)` (老 import 不断);
4. `impl_manifest.json` 记 `{key: {func, module, file}}`;
5. 自检 = 新进程整包导入 + registry 里所有 key 可调用 (`BAD 0`), 任一失败 `cp 备份 library.py` 回滚。

## 2. 四个静默坑 (都实测踩过)

1. **library 里的 `NODE_LOGIC` 可能不是 registry 那张表** —— 实测 `L.NODE_LOGIC` 是空 dict(0 条),
   真表在 `registry.NODE_LOGIC`(157 条)。重注册/查表一律 `from .. import registry as _rg` 直接问 registry,
   别用本模块的同名变量, 否则"重注册"静默 0 条、什么都不报错。
2. **多个 key 共用一个函数** (如 SK02~SK08 → `node_ss_atomic`, `ss_world`→`node_ss_exec`):
   第二个 key 切出来只是一段转调壳。定式 = **合并到主文件**: 删掉壳文件, manifest 里把该 key 指到主模块
   同一函数; 链式引用 (A→B→C) 要**扁平化到最后那个真实文件**, 否则 by_level/registry 指向已删文件。
3. **函数里有 `global X`**: 程序化迁移会把全局留成两份(模块各一)。人工迁: 在节点模块顶部初始化
   `X = None`, 保留原 `global X` —— 全局归节点自己, 不再污染 library。
4. **生成器的文件名占位符**: 模块名不等于 `n_<id>.py` (`ssyolo` → `n_yolo.py`)。占位符必须在**写盘时**
   用真实 `basename` 替换, 不能在 `render()` 里按 id 拼, 否则契约头写着 `n_ssyolo.py` 而这个文件不存在。

## 3. 收尾与验证

```bash
gui-venv311/bin/python tools/gen_by_level_index.py   # 档位索引重生成
gui-venv311/bin/python tools/gen_node_map.py         # 三处表重生成 (应"三层都齐, 缺 0")
gui-venv311/bin/python tools/canvas_level_audit.py   # 节点落实到 R1~R5 的程度
```

验收口径 (数字, 别只说"拆完了"): by_level 里指向 `library.py` 的节点 **57 → 0**; registry key 数不变且
`BAD 0`; 随机抽一个节点从 registry 调用能返回非 None; `get_node_triple` 三处都存在。

`verify_engineering.py` 的两处已知误报不要当成拆分造成的: ①`ss_moe` 画布上有、无执行注册 (真缺口);
②"壳转发到包"在无 `ZMAX_SINGLE_THREAD` 时被单线程横幅污染 stdout, 手动跑 `tools/gui/node_logic.py`
比对是 157/True/runtime 即正常。
