# 节点三件套 · 画布绑定 · 端口真输出

## 目录归属（改代码前先判这一条）

| 目录 | 放什么 | 判断 |
|---|---|---|
| `src/lerobot/policies/` | 纯算法：输入数组→输出结果，不读总线、不认识节点名 | 换个机器人还能用 |
| `src/lerobot/middleware/` | 通讯中间件：总线/传输 + 节点契约 `nodes/n_<id>.py` + 实现 `nodes/impl/<key>.py` + `impl/shared_runtime.py` | 换个传输协议要改 |
| `src/lerobot/engineering/` | L1~L5 分层 + 注册/派发/画布真源：`l1_robot/ l2_basic/ l3_advanced/ l4_expert/ l5_human_sync/`、`layers.py`、`levels.py`、`registry.py`、`runtime.py` | 只把两者接起来并留证据 |

层义固定：L1 机器人接口 · L2 基础功能 · L3 高级功能 · L4 专家功能 · L5 人机同步。
层归属唯一依据是 `levels.py` 的 `band_map()`（画布行带 + `OVERRIDE` 特例），五个层文件夹与 `layers.py` 由 `tools/gen_layers.py` 生成，不手改。

`engineering/` 里**不放节点实现**。一个节点在盘上有三处：
`middleware/nodes/n_<id>.py`（端口契约，生成物）· `middleware/nodes/impl/<key>.py`（实现：取数/调算法/打标）· `policies/...`（算法）。
`engineering/node_map.json` 与 `sourceview.get_node_triple(key)` 给出这三行；契约由 `tools/gen_middleware_nodes.py` 生成，手改会被下次生成覆盖。

## 画布节点名就是实现绑定键 —— 改名即断绑（静默）

`middleware/spec.py` 解析画布时用 `registry.match_node(节点名)` 做**最长关键字匹配**得到 `impl_key`，写进契约的 `IMPL_KEY`。
名字改了、关键字表没改 ⇒ `IMPL_KEY=''` ⇒ `compute()` 落到「实现未注册 → 直通」，`out1←in1`，实现一次都没跑，日志里只有一行状态。

- 改名/新增节点前：`grep -rn '_reg("<key>"' src/lerobot/middleware/nodes/impl/shared_runtime.py` 看匹配词表，把新名字里会出现的词补进去（或用不冲突的旧词）。
- 改完立刻验：`grep -n '^IMPL_KEY' src/lerobot/middleware/nodes/n_<id>.py` 必须非空；再 `python -c "from lerobot.engineering import registry as R; print(R.match_node('<新名字>'))"`。
- `registry` 的 key 是 ASCII（`data` / `ssyolo`），匹配词是中文短语；两条节点名字相同会按最长且首个命中决定归属，别给两个节点留同一个词。

## PURE 闸：不开它，端口永远是空的

契约里 `PURE=False` 是红线默认值，`compute()` 只做数据面直通（`outN ← inN`），**实现在总线路径上永远不会执行**。
要端口真出数据，画布节点 params 同时满足：

- `pure_verified: true`（生成器据此写 `PURE = True`）
- `impl_key: <注册 key>`（生成器读 `match_node`，params 里的 impl_key 只是兜底表述）

只给「不动设备」的节点开。`EXEC_MODE=act`、会下发运动的节点保持 `PURE=False`，由引擎在授权后执行。

## 端口真输出：实现返回 out1/out2/out3

- 实现返回 `{"out1": …, "out2": …, "out3": …}`。`compute()` 只保留键名在 `PORTS_OUT` 里的项；**一个都不匹配时把整块塞进 `out1`**（老实现的业务字典就是这样活下来的）。
- 总线路径的 `ctx` 只有端口：`in1: {"value": …}`，**不保证有** `module` / `log` / `params`。实现开头一律 `ctx.get(...)`，否则 `KeyError` 被 `compute()` 吞成「实现异常 → 直通」，表象是端口空。
- 侧信道（模块级 `_SS_STATE` / 全局缓存）只能给同进程消费者当缓存，**不能当节点输出**：画布连线上看不到它，下游换进程就断。
- 端口里必须带能判新的字段：`tick`（毫秒，整拍对齐）、`ts`、`frame`（帧名）、`bytes`、`joints_meta.fresh/age_s`。没有这些，下游只能猜数据新旧。

## 数据源切换：单一读取口 + TTL

- 数据源节点每拍把画布拨钮结果写进一个状态：`{"src": "ar"|"sim"|"real", "cam", "w","h","bytes","ts","tick"}`。
- 所有消费者（感知/理解/分割/策略/桥）只通过**一个**访问函数读它，带 TTL（10s）：画布停了就当没选过，否则会把下游死锁在某个源上。
- 每个会「自己开世界」的节点都要先问这个访问函数：仿真 env、stable-world 桥、真机旁路帧，**画布选了 AR 就一律不起**——两套世界同时跑 = 同一拍里帧不同步。
- 非选中分支也要写状态（`src=sim/real`），不然下游在 TTL 内仍按上一次的 AR 走。
- 消费者日志统一打 `frame=<帧名> tick=<tick>`，同拍可对账。

## 证明「切换真的生效」的四步配方

1. **同一节点、两次 params**：先 `src_state=AR场景`，再 `仿真`，各调一次 `compute(ctx)`，比 `out1.src / out1.frame / out1.tick`。
2. **总线回读**：`bus.publish(topic("<id>","out1"), out1)` → `bus.latest(...)`，确认 src/frame 跟着变（`make_bus()` 可能返回 tuple，取 `[0]`）。
3. **契约自检**：`IMPL_KEY` 非空 + `PURE=True` + `LAST_STATUS == "实现执行"`。
4. **跨机自证**：目标机把 exe 当解释器跑探针脚本，打印 `module.__file__`、`IMPL_KEY/PURE` 与端口里的 src/frame/tick —— 端口 200 分不出新旧代码与真假切换。

## 常见假绿

- 改了实现但契约没重新生成 ⇒ 跑的是旧契约（`tools/gen_middleware_nodes.py` 后 `--check` 无 drift）。
- 只改了模块级状态、没改返回值 ⇒ 日志有「AR 场景」但 `out1` 还是空/直通值。
- 节点改名后 `impl_key` 掉空 ⇒ 全部端口直通，下游照常 200，看不出异常。
- 用 `_SS_STATE` 当「输出」自证 ⇒ 只有本进程能看见，别的进程/进程内的另一个解释器看不到。
