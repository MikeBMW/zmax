# 新节点要「真执行」的落地阶梯 (画布加节点 → 常驻循环里真跑)

> 先读本文件：画布节点显示 `直通 (实现未注册: )` / `直通 (实现未注册: <key>)` / 或 `✅ 但 out1 为 null`，
> 就是执行链没接上。按下面顺序逐级核，哪级断修哪级。

## 0. 改对文件

- 唯一依据 = `data/database/zmax/sources/canvas/state_space_obs.json`（`tools/ss_canvas_loop.py` 的 `CANVAS` 常量指这里）。
- `flows/state_space_obs.json` 是另一份**普通文件副本**（不一定真是软链），只改它 ⇒ 运行循环看不到。
- 写前备份、写后回读：JSON 能 parse、节点/连线数对得上、每条线的 `f`/`t` 在节点表里存在、无重复 id。
- 位置冲突断言要**跳过 `type == "row_bg"`**：行带是容器，本来就包住节点，否则加节点会被自家断言拦死。

## 1. 端口契约模块（缺它 ⇒ 空 key 直通）

每个可执行节点在 `src/lerobot/middleware/nodes/` 下有契约模块，文件名来自 `spec.module_name`，
**由节点显示名推导，不是由 node id 推导**（实测 `ss_se3_state` → `n_8815.py`、`ss_phase_corr` → `n_phase.py`）。

先查真实 slug 再建文件：

```python
from lerobot.middleware import load_project
p = load_project()
print(p.nodes['<node_id>'].spec.module_name)   # ⇒ n_xxx
```

契约模块最小形态（照 `nodes/n_dit.py`）：NODE_ID / NAME（与画布显示名逐字一致）/ LAYER / TYPE /
EXEC_MODE / PURE / PORTS_IN / PORTS_OUT / IMPL_KEY / LAST_STATUS / `_passthrough(ctx)` / `compute(ctx)`。
`PORTS_IN`、`PORTS_OUT` 必须与画布 JSON 里该节点的连线端口逐字对应，否则 step 取不到输入、发不出输出。

## 2. 注册要发生在「会被 import 的地方」

- `nodes/library.py` 的 `_reg(key, [匹配词], doc, fn)` 服务 GUI / 全量加载路径；`impl_manifest.json` 登记 key→文件供 repoint。
- **常驻循环进程未必 import 过 library** ⇒ 契约模块 `compute()` 里必须自注册：

```python
from lerobot.engineering import registry as _reg
if not _reg.get(IMPL_KEY):
    from lerobot.middleware.nodes.impl import <mod> as _impl
    _reg.register(IMPL_KEY, ['<匹配关键字>'], '<一句话>', _impl.<fn>)
info = _reg.get(IMPL_KEY) or {}
fn = info.get('fn')
if not callable(fn):
    LAST_STATUS = '直通 (实现未注册: %s)' % IMPL_KEY
    return _passthrough(ctx)
```

- 症状分辨：状态串 key 为**空** ⇒ 节点模块没找到（slug 错 / 模块不存在）；key 有值 ⇒ 模块对了、registry 里没这个 key。

## 3. `_SS_STATE` 键名要对齐

实现把结果写到 `_SS_STATE['<语义名>']`（如 `se3_state`、`phase_corr`），**不等于 `IMPL_KEY`**。
契约读 `_SS_STATE[IMPL_KEY]` 会永远拿到 `None`：节点报「✅ 已执行」但 out1 是空的。
先 `grep "_SS_STATE\[" impl/<file>.py` 抄准键名再写契约。

## 4. 验收必须走真项目路径

```python
import importlib.util, sys
spec = importlib.util.spec_from_file_location('ssloop', 'tools/ss_canvas_loop.py')
m = importlib.util.module_from_spec(spec); sys.modules['ssloop'] = m
spec.loader.exec_module(m)
prj = m.load_project()
tr = prj.step(only=['<node_id>'])
print(tr[0]['status'], tr[0]['ms'], tr[0]['out'])
```

口径：`status` 是 `✅ …`（不是 `直通`）+ `out1` 有真值（时间戳/帧龄/量纲对）+ 耗时在预算内。
只 import 实现函数跑一遍不算——那只证明算法能跑，不证明画布能调它。

## 5. 运行中循环何时吃到新节点

- 循环按 mtime 重载，日志打 `加载画布: N 节点 / N 连线`；`N` 只数可执行节点（`row_bg` 等结构性节点不计）。
- 已在跑的进程里模块 import 是缓存的：契约模块是后补的、或先前 import 失败过，`touch` 画布重载也未必生效。
- 这时不要自作主张重启（本机规矩：只可停、重启要点名），如实报「文件已就绪，需重开一次画布」。
- 反之 `touch` 目标文件即可触发无重启重载，能成就省一次重启。

## 6. 同批验收的旁证

- 分层联调 `tools/layer_e2e_verify.py --frames N`：**N 取 ≥6**。AR 渲染场景目标会阶段性离开视野，
  3 帧很容易 0/3 假失败，6 帧常 6/6；单帧 0 命中先降 conf 复核，再判接口是否真坏。
- 版本/完整性门禁报红时，先证明它是不是**本来就红**：`git show HEAD:<file>` 到临时文件，
  用同一检查函数对比 HEAD 与工作区。两边同错 = 既有漂移，如实报告，别顺手改门禁去凑绿。
