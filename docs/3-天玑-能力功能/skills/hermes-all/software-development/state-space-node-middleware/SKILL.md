---
name: state-space-node-middleware
description: Use when 状态空间节点要包成模块接 DDS 总线。
---

# 状态空间节点中间件 (src/lerobot/middleware)

工程 JSON 是唯一真源; 节点模块、端口、路由全部从它派生。改动前先读
`src/lerobot/middleware/README.md` (契约 + 命令)。

## 结构

```
bus.py        数据总线: DDS(550B) / 共享内存(550A·550C) / 进程内
spec.py       工程 JSON → NodeSpec; 端口 = 连线推出的 f_port/t_port
node.py       Node: pull(总线) → compute(模块) → push(总线 + 按连线路由)
loader.py     load_project: Tarjan SCC 排序 + 连线路由表 + 模块自愈
project.py    Project.step/inject/io_table/stats
open_target.py 右键落点 (先节点模块, 再真实现)
nodes/n_<单词>.py 每节点一个模块 (tools/gen_middleware_nodes.py 生成; 文件名用 NODE NAME 不用 id)
```

## 硬规则

- 模块文件名 = **一个英文单词**, 真源 `src/lerobot/middleware/node_names.json` (id→word);
  不许中文、不许用 id。改单词 → 跑 `gen_middleware_nodes.py` 自动重命名+删旧文件。
  Python 3 允许中文模块名 (实测可 import), 但老倪要求全英文单词。

- 端口不许手写: 加/删连线后跑 `tools/gen_middleware_nodes.py`，
  `--check` 必须 exit 0 (幂等)。
- 排序不能当纯 DAG: 画布有 L2→L3→L4 回灌 (实测一个大 SCC 41 节点 + 一个 3 节点)。
  用 SCC + 分量拓扑序 + 分量内按 (y,x); 环内值靠总线**下一拍**闭合。
  千万别退回 Kahn + "剩下按坐标补末尾" —— 会把下游排到上游前面。
- 连线即路由: `push()` 除了发自己的 out 话题, 还要转发到下游 in 话题,
  否则下游的 in 话题永远是空 (协议上"输入到总线"就没落地)。
- `PURE = False` 是红线默认值: act 类节点不许自动执行实现 (8793 授权才动设备)。
- DDS 档位: 只 550B (comm=dds 且 topics=all); A/C 走 shm。
  本机 cyclonedds 的 QoS 策略在 `cyclonedds.core.Policy`, **不在** `cyclonedds.qos`
  (踩过: AttributeError: module 'cyclonedds.qos' has no attribute 'Reliability')。

## 话题名 & 工程库

- 话题 = `ss.node.<node_id>.<port>` (`bus.TOPIC_PREFIX` / `bus.topic()`), 端口来自连线。
- **落库真源**: `mw_topic` (表在 `data/database/zmax/zmax_engineering.db`), 由 `db.sync()` 写入,
  `load_project(source="auto")` 按画布 sha256 判是否同源: 一致走库, 不一致重解析并回写。
- 判据 `tools/verify_mw_db.py` 7 项: 其中两条是铁证 —— ①改 `mw_topic` 一行话题名 → 重新 load →
  `Node.topic()` 立刻变; ②画布改名 → sha 变 → 库判过期并自动回写。
- 别把话题名硬编码在节点实现里: 一律 `Node.topic(port)` / `bus.topic_map`。

## 判据 (交付前必须 10/10)

```bash
PYTHONPATH=src ./gui-venv311/bin/python tools/verify_middleware.py
```
① 加载数=真源 ② 每节点端口=JSON ③ 注入→上游发总线→下游从总线读
④ DDS 只对 550B 开 ⑤ shm 跨进程 ⑥ 右键落点=节点模块 ⑦ 550B 真 DDS ⑧ A/C 非 DDS

数据面探针要挑"干净连线": 源节点对应输入口**没有上游写者**(注入不被覆盖)、
下游该口只有这一个写者、且源在序里先于目标 (反序边属闭环反馈, 单拍看不到值)。

## GUI 挂点

- `SimulinkModule._mw_build_project(flow)`: `load_flow` 末尾调用, 形成 `self.mw_project`。
- `SimNodeItem.paint` → `_paint_core` + `_mw_badge`: 右下角 ◉DDS/◉内存 + tooltip。
  徽标必须加在 paint 包装层, 只加在 `_paint_internal` 只覆盖 Z700 分支 (实测渲染不到普通节点)。
- `open_in_vscode(node, target=...)`: **必须显式传 target**。`"node"`(默认)=中间件节点
  `nodes/n_<单词>.py` 停在 PORTS_IN 行看输入输出; `"impl"`=模块真实实现符号行。
- `open_node_source()` = 打开源代码(实现) → `target="impl"`; `open_middleware_node()` = 打开 node → `target="node"`。

## 右键菜单契约 (2026-10-17 老倪定稿)

节点右键只留「打开源代码 (模块实现)」「打开 node (中间件 · 输入输出)」「节点参数」，
其余「跑一下 / 看面板」类全删：

| 菜单项 | 落点 |
|---|---|
| 打开源代码 (模块实现) | `params.source` / 注册表符号行 |
| 打开 node (中间件 · 输入输出) | `middleware/nodes/n_<单词>.py` 的 PORTS_IN 行 |
| 节点参数 | 参数对话框 |

已删：查看/编辑节点逻辑 (双击替代)、查看数据集、运行节点 (画布 ⏭/▶ 替代)、打开 VSCode 调试。
节点特有面板入口 (AOI 终端/标定表格/验证层/VLM/可视化/数据源切换/导出) 保留 —— 没有别的入口。

验证探针 `probe_ctx_menu_slim.py`: 截 `QMenu.exec_` 拿菜单项，落点读 `_log` 的「已定位 path:line」。
VSCode 是 `systemd-run`/`os.spawnv` 起的，截 `subprocess.Popen` **抓不到**命令。
