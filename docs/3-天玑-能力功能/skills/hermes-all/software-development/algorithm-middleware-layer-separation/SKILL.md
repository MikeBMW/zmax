---
name: algorithm-middleware-layer-separation
description: Use when 算法写在中间件节点里要搬到算法层(含被质疑没搬)。
version: 1.0.0
author: hermes-agent
license: MIT
metadata:
  hermes:
    tags: [zmax, middleware, architecture, canvas, refactor]
    related_skills: [state-space-node-middleware, zmax-aoi-service, zmax-state-space-architecture]
---

# 算法层 / 中间件节点 / 画布真源 的分层边界 (Z-MAX)

## When to Use
- 发现检测、判据、策略、渲染这类**算法实体**被写在 `src/lerobot/middleware/nodes/` 里, 需要搬家。
- 节点输出的话题/状态字段对不上真实结论(页面永远显示"未接"/"未达"这类降级文案)。
- 手改过 `nodes/n_*.py`, 下一次重生成就被抹回去。

相关: 中间件本身的结构/端口/总线规则见 `state-space-node-middleware`; AOI 具体端点与判据见 `zmax-aoi-service`。

## 铁律

### 1. 算法在 `src/lerobot/policies/<域>/`, 节点只做薄壳
- 目录与 `policies/yolo_3d/`、`policies/sam3_seg/` 同级, 例: `policies/aoi/{quality,gold,gold_yolo,surface}.py`。
  入口函数 (`inspect_*`) 放 `quality.py` 这类主文件, 供节点与验收脚本调; 其它文件是它编排的子路。
- 节点 `n_*.py` 只做三件事: **取 context → 调 policies → 发话题**。节点里不许出现检测/判据/阈值逻辑。
- 依赖方向只有一个: **policies ← middleware** (`policies/` 永远不 import `middleware`)。
- `shared_runtime` 这类共享模块里, 搬家后**零调用方的转发直接删**(先 `grep -rn '<符号>' --include='*.py' src/` 数调用点)。
  确实还要留兼容的, 函数体只能有一行转调, 且 docstring 第一句必须写死「这不是算法, 算法在 `policies/<域>/`」——
  否则下次有人(包括老倪)打开中间件看到 `def node_xxx(ctx)`, 就直接判定"算法根本没搬"。
- 其它路径(画布节点、GUI、验证脚本)只能通过算法层入口调, 不许复制一份阈值。**要多一条口径就是多一个分歧源。**

### 2. 搬完必须实跑节点, 不只 `py_compile`
- 验收三件: ①节点真跑一次(记录耗时) ②发出的话题条数/名字 ③判据值有数(不是降级默认)。
- 只做 import/编译检查会漏掉"函数存在但返回恒定额"这类静默降级。

### 3. 节点回传的状态字段必须读真源
- 不许引用不存在的模块级变量(如 `_AOI_REMOTE`); `NameError` 被 `except` 吃掉后, 页面永远显示"未接", 而算法其实在跑。
- 从**算法层回写的缓存**读(`_YOLO_CACHE[<key>]['verdict'/'why']`), 并把 `why` 作兜底 —— 页面显示的原因要能和日志里那条对上。
- 通用判据: **节点上报的每个字段, 都能指到一处会把值写进去的代码行**; 指不到就是死字段。

### 4. 生成器写的字段改真源, 不改产物
- 画布真源 `data/database/zmax/sources/canvas/state_space_obs.json`; `nodes/n_*.py` 与 DB `mw_node` 都是**派生**。
- 真源里该节点 `layer` 为 null 时, 重生成会把 `LAYER = 'L2'` 写成 `LAYER = ''`(DB 同步变空) —— 手改 py 无效, 下次重生成照抹。
- 顺序固定: 改画布 JSON → 跑 `tools/gen_middleware_nodes.py` → 用 verify 脚本查那行(不靠眼看)。

### 5. 产线行为差异先怀疑"跑的不是这一版"
- 搬家/改完发现"线上效果没变"或"反而坏了": 先比对现场程序的文件大小 + sha 与清单(`PRODUCTION_MANIFEST.json` 的 `bytes`/`sha256`),
  再用 `OPTIONS` 探路由做指纹。**同名文件里可以是任意历史版本, 名字里的版本号不算数。**
- 确认是版本回退时, 恢复清单版再复测, 别在算法侧继续调参。

## 从节点里抽出算法的固定套路 (2026-11-10 AOI 实操)

把 `nodes/impl/<key>.py` 里的算法搬到 `policies/<域>/` 时, 按这条形状切, 不要边搬边改逻辑:

| 层 | 函数 | 内容 |
|---|---|---|
| 算法 | `xxx_signals(res) -> dict` | **话题口径**: 哪些量上总线、判决 0/1 怎么编码、派生量(如缺陷数=划伤+污点)怎么合成 |
| 算法 | `xxx_report(res, ...) -> dict` | **业务 dict**: kind/pass/verdict/items/派生字段, 字段名一次定死 |
| 算法 | `xxx_log(res, sig, log)` | 日志格式化 (数值全部来自本轮结果) |
| 算法 | `inspect_xxx(frame, log, cache, publish)` | 入口: 判定 → signals → publish → report |
| 节点 | `node_xxx(ctx)` | 只剩: 节流(拍频预算) + 取帧 + 调 inspect + 返回 |

边界判定:
- **节流留节点**, 因为它是 10Hz 拍频预算(实测单拍 1.3~3.0s), 不是检测口径。
- **话题/报告字段搬算法层**, 因为那是「一条口径一个源」—— 留在节点就是第二个分歧源。
- `policies/` 里需要缓存/发布/日志时**一律参数注入**(`cache=`, `publish=`, `log=`), 绝不 import middleware。
- 多路算法(搬运/本机推理/另一台相机)在同一包里串起来, 由一个 `inspect_*` 统一编排, 别让节点做编排。

## 源码视图三处会各指一边 (漏一个就显示旧位置)

节点「打开源码」看到三处, 三个来源**互相独立**, 搬完算法要一起改:

1. `contract` `nodes/n_<x>.py` —— 生成物, 但现场 79/79 个节点本来就与画布 JSON 漂移。
   **不要为此全量重生成** `gen_middleware_nodes.py`(会覆盖别人手改的 10+ 文件); 直接改产物, 同时改画布真源 `state_space_obs.json` 里该节点的 `params.source`, 保证下次真重生成不回退。
2. `algo` —— 来自 `src/lerobot/engineering/node_map.json`, 由 `tools/gen_node_map.py` **从 n_*.py 的 `SOURCE` 常量解析**。
   ⇒ `SOURCE` 必须是**单一文件路径**; 写成 `'src/lerobot/policies/aoi/ · a.py + b.py + c.py'` 会得到 `algo: "... · a.py + b.py:1"` 这种不可用值。细节写进 `PARAMS['source']`, 不要写进 `SOURCE`。改完跑 `gen_node_map.py` 再查 `node_map.json`。
3. `_EXTERNAL_LOC[<key>]` —— `shared_runtime.py` 里手写的 `(绝对路径, 行号, "def 符号")`。
   行号是硬编码, 搬完必须核对那一行**真是这个 def**(脚本读文件第 N 行比对), 不能只改路径。

## 右键「打开源代码」落点 (两字段写错就回到中间件)

`open_node_source` → `resolve_open_target(node)` 的优先链:
`params.source` → `spec.source` → **registry 里 impl_key 的实现函数** → node_logic 映射 → GUI 自己。

所以算法搬到 policies 后, 只要 `params.source` 没写成**能被 os.path.isfile 命中的纯路径**,
就会掍到 registry 兜底, 落到 `impl/<key>.py` 的节点入口 —— 用户看到的就是「右键打开的
还是中间件, 算法根本没搬」。(本人抽过: 写了 `'path · sym (说明)'` ⇒ 打开到 impl/ss_aoi.py:36)

两条硬规则:
1. `params.source` = **纯相对路径**, 不写 `·`/括号说明/多文件。说明写进 `PARAMS['architecture']`。
2. `params.source_symbol` = **带 `def ` 前缀** (`'def inspect_aoi'`)。行号由
   `startswith(token)` 现搜, 写裸名 `'inspect_aoi'` 永远匹配不上 ⇒ 退到第 1 行。
   生成物里的 `SOURCE_SYMBOL` 同理 (spec.source_symbol 兜底分支用它)。

判据 (不看配置, 看真命令): 打桩 `subprocess.Popen` + `shutil.which('code')`, 真建
`SimulinkModule`, 调 `open_node_source(node)` / `open_middleware_node(node)`, 捕获 `-g <file>:<line>`,
再打开该行核对是不是那个 `def`。两个入口的正确落点:
  打开源代码 → `policies/<域>/<file>.py:<def 行>`
  打开 node   → `middleware/nodes/n_<id>.py:<PORTS_IN 行>`
踩坑: `SimulinkModule()` 会把 `sys.stdout` 接到自绘终端 ⇒ 验证脚本的 print 全丢, 必须写 stderr。
改完提醒用户: GUI 里画布是**内存旧值**, 要重开工程才生效。

## 验收: 节点薄壳要看三样, 不只编译

```
① 算法层直调: inspect_xxx(合成帧) → 判据值有数 + 话题条数/名字
② 节点真跑:   ctx={"log": ...} + 注入一帧 → 返回 dict 字段齐 + 缓存回写 + 耗时
③ 节流真生效: 第二拍 <50ms、0 行日志、cached_ago_s 非 None
④ 依赖方向:  AST 扫 policies/<域>/*.py 有没有 import middleware (grep 会命中注释里的字, 别用 grep)
⑤ 残留扫描:  节点里 grep 图像算子/阈值键 (cv2./HoughLines/Canny/threshold/*_max/*_min)
```

④ 用 `ast.walk` 判 `ast.Import/ImportFrom` 的 module 字段; 用 grep 会被「本包**不 import** lerobot.middleware」这类注释骗到。

## 迁移"完成"的判据: 老层不许再读起来像算法

代码搬完 ≠ 迁移完成。老倪复核时是**按符号名和残留文案判的**, 不会去读函数体:
中间件里只要还有 `def node_xxx(ctx)`、docstring 写着「实现绑定 · xxx/library.py · node_xxx」,
他就会说"这个应该是算法, 怎么还在中间件里? AOI 算法不是迁移完成了么?" ——
这时解释"它是薄壳"没用, 得先让中间件里没有可误读的东西。

收尾四项, 每项一条命令, 别靠眼看:

1. **全 `src/` 数符号, 不只 `middleware/`**
   `grep -rn 'node_xxx' --include='*.py' src/`
   只搜 `middleware/ policies/ tools/` 会漏掉 `engineering/` —— 而用户最初抱怨的那处往往就在那儿。
2. **每个 `def` 都要定性**: 中间件里对该节点只允许 ①节点入口一处 ②注册 ③发话题回调。
   多出来的同名转发: 有调用方 → 留 + 在 docstring 写明; 零调用方 → 删。
   删前必须 grep 调用点: 验收脚本(`tools/verify_*`)常直接调 `shared_runtime.node_xxx`, 删了就断。
3. **docstring 里引用的文件必须真实存在**
   生成物 `n_*.py` 的「实现绑定」行写死的是历史路径; `engineering/nodes/library.py` 这类文件
   可能整个目录只剩 `__pycache__`。用 `search_files(target='files')` 确认存在再信, 别信文案看着合理。
4. **给用户看逐行清单**, 不是"我搬完了":
   中间件侧每个保留项一行(`文件:行` + 为什么必须在这里), 算法侧给文件数/总行数。
   老倪要的是"算法到底在哪、中间件里还剩什么"。

判据: 打开中间件文件,**看不出**算法在哪一层 —— 才算搬干净。

## 重复出现就沉淀
同一类"算法被塞进节点"的事在别的域(视觉、策略、轨迹)再出现时, 先把本条扩展成该域的小节, 不要新开文件。
