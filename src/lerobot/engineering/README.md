# Z-MAX · 分层与目录契约 (lerobot.engineering)

> 2026-11-10 老倪定调：
> **`policies/` = 算法** · **`middleware/` = 通讯中间件** · **`engineering/` = L1~L5 分层；它是算法和节点中间件之间的桥梁。**
> 这三句是判断"代码该放哪"的唯一依据，下面所有规则都从它推出来。

## 1. 一个节点落在三处，不是一处

一个画布节点不是一个文件，而是**契约 / 实现 / 算法**三层叠起来的：

```
src/lerobot/
├── policies/                        ① 算法       纯计算：模型、几何、控制律。
│   └── yolo_3d/yolo_state_aligner.py            不知道节点名、不知道端口、不碰总线
│
├── middleware/                      ② 通讯中间件  总线 + 传输 + 节点 (契约 + 实现)
│   ├── bus.py                         publish / latest / 订阅
│   └── nodes/
│       ├── n_yolo.py                  契约：PORTS_IN/OUT、话题 ss.node.ssyolo.<port>、
│       │                              EXEC_MODE / PURE 闸、把 ctx 交给 registry
│       └── impl/ss_yolo.py            实现：取数 → 调算法 → 打标 (共享运行时 impl/shared_runtime.py)
│
└── engineering/                     ③ 分层设计 (L1~L5)  —— 没有 nodes/ 目录
    ├── layers/by_level.py            L2/L3/L4/L5 各有哪些节点 (生成物)
    ├── levels.py                     L2/L3/L4/L5 各自"必须还能干的事" + check()
    ├── registry.py                   key → 实现函数 + 文件/行号
    ├── runtime.py                    按拓扑序派发
    ├── sourceview.py                 源码定位 (get_node_location / get_node_triple)
    ├── flows/state_space_obs.json    画布真源
    └── node_map.json                 一节点三处 (生成物)
```

以 YOLO 为例，`sourceview.get_node_triple("ssyolo")` 直接给出三处：

```json
{"contract": "src/lerobot/middleware/nodes/n_yolo.py:1",
 "impl":     "src/lerobot/middleware/nodes/impl/ss_yolo.py:22",
 "algo":     "src/lerobot/policies/yolo_3d/yolo_state_aligner.py:1",
 "layer": "L2", "impl_key": "ss_yolo", "ports_in": ["in1"], "ports_out": ["out1"]}
```

右键"打开源码"过去只给一处（契约），实现藏在 registry 里、算法藏在 PARAMS['source'] 里，
于是看上去像"代码丢了 / 两套 node"。现在三处一起给。

## 2. 各层能写什么、不能写什么

| 层 | 可以写 | 不许写 |
|---|---|---|
| `policies/` | 纯函数/类：输入张量或数组，输出结果 | 读总线、写文件、知道节点名、`import lerobot.middleware` |
| `middleware/nodes/` | 端口清单、话题、`PURE` 执行口径、`manifest()` | 业务算法、状态缓存、模型推理 |
| `middleware/nodes/impl/` | 取数、调用 `policies`、结果打标、节点级缓存 | 直接开 socket、直接 `mj_step`、自己拼端口名 |
| `engineering/{levels,registry,runtime,flows}` | 分层契约、注册、派发、画布读写 | 任何算法 |

判断方法：**这段代码换个机器人还能用 → policies；换个传输协议要改 → middleware；
只是把两者接起来并留下证据 → middleware/nodes/impl。engineering 里不放节点。**

## 3. 节点实现按节点名分文件（2026-11-10）

历史上 125 个 `node_*` 全塞在 `nodes/library.py`（7245 行、上千全局），registry 的 key 全指它 ⇒
不管点哪个节点，"打开源码"都落到同一个大文件。

现在：**一个节点一个文件，文件名 = 画布节点 key**，`library.py` 只剩两样东西：

* 共享运行时（`_SS_STATE`、缓存、通用取帧/打标辅助）
* 薄壳函数（同名转调，老的 `from ...library import node_ss_yolo` 照旧可用）

```
library.py                        7245 → 4794 行
by_level 里指向 library.py 的节点  57 → 0
registry                          157 key · 0 个不可调用
```

拆分工具 `tools/node_split.py`：AST 精确切段 → 按自由变量生成**显式 import**（不做 globals 注入）
→ 原位置留薄壳 → `impl_manifest.json` 登记 → 拆完立刻自检（整包导入 + 全 key 可调用），
失败自动回滚。用了 `global` 的实现（`ss_ff_hist`）人工迁移：全局归节点自己，不污染 library。

## 4. 生成物清单（别手改）

| 文件 | 生成器 | 内容 |
|---|---|---|
| `nodes/by_level.py` | `tools/gen_by_level_index.py` | 档位 → (画布 id, 名称, key, 文件, 函数) |
| `middleware/nodes/n_*.py` + `_index.py` | `tools/gen_middleware_nodes.py` | 节点契约（端口/话题/实现绑定） |
| `engineering/node_map.json` | `tools/gen_node_map.py` | 一节点三处：contract / impl / algo |
| `nodes/impl_manifest.json` | `tools/node_split.py` | key → 实现模块（收尾重注册 registry 用） |

## 5. 改东西的规矩

1. 算法只写 `policies/`；契约只改 `middleware/nodes/`；**不要**在契约里写业务逻辑。
2. 节点实现写 `middleware/nodes/impl/<node_key>.py`，不要再往 `shared_runtime.py` 里加函数。
3. 新增节点：①`policies/` 写算法 → ②`middleware/nodes/impl/<key>.py` 写实现并 `_reg(key, [...], doc, fn)`
   → ③`tools/gen_middleware_nodes.py` 生成契约 → ④画布 JSON 加节点/连线 → ⑤重生成 `node_map.json`。
4. 路径一律从 `paths.py` 取，不要 `dirname(__file__)` 上溯。
5. 改完必跑：
   `gui-venv311/bin/python tools/verify_engineering.py`（架构自检）
   `gui-venv311/bin/python tools/canvas_level_audit.py`（每个节点落实到什么程度）
   `gui-venv311/bin/python tools/gen_node_map.py`（三处位置表）

## 6. 当前已知缺口（别当成已实现）

* `ss_moe`（元数据 MOE 门控路由）：**画布上有、没有执行注册** —— `levels.check()` 因此报
  "L2 档位可执行 ❌ / 档位契约无问题 ❌"。
* `impl/shared_runtime.py` (原 library.py) 里仍有 81 个非画布内部 key（`sw_*` 开关、训练/部署/评估类），未按节点名分文件。
* `verify_engineering.py` 的 "壳转发到包" 一项在无 `ZMAX_SINGLE_THREAD` 时被单线程横幅污染 stdout
  而误报 ❌；手动核对为 157 key / True / runtime。

## 7. 历史（保留，避免重复踩）

* 2026-09-28：节点逻辑从 `tools/gui/node_logic.py`（5129 行）整体搬进本包；
  `tools/gui/node_logic.py` 只剩兼容壳（33 行），`import node_logic` 照旧可用。
* 2026-11-01：修掉"实现返回 ndarray/float 被当非 dict 丢掉" ⇒ 65 个节点里只有 6 条连线真有值。
* 2026-11-10：按节点名拆分（见 §3），补齐 `node_map.json` 三处定位。
