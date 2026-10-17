# 状态空间中间件 middleware

状态空间 = **一条数据总线 + 每个节点一个模块**。
工程 (节点 + 连线 JSON) 是唯一真源; 代码全部从它派生或按它的端口跑。

```
flows/state_space_obs.json  (工程真源: 75 节点 / 202 连线)
        │  parse_canvas()            端口 = 连线推出的 in/out
        ▼
spec.NodeSpec ──► nodes/n_<id>.py  (每节点一个模块 · 生成物 · 打开就能看到输入输出)
        │
        ▼
loader.load_project() ──► Project (节点 + 连线路由表 + 拓扑序/SCC + 总线)
        │
        ▼
Project.step()  每拍: 节点从总线取输入 → compute(ctx) → 结果发回总线
```

## 契约 (所有节点只认这三条)

```python
bus.publish(topic, value)          # value 必须 JSON 可序列化
value, ts = bus.latest(topic)      # 没数据 → (None, 0.0)
topic = "ss.node.<节点id>.<端口>"   # 端口级话题
```

节点里:

```python
def compute(ctx):
    # ctx["in1"] = {"value": …, "age_s": …, "fresh": bool}   ← 来自总线
    return {"out1": …}                                    # → 发回总线
```

连线即路由: 上游 `out1` 发完，会按工程 JSON 的连线**转发到下游的 `in1` 话题**，
所以上下游之间没有任何内存传参 —— 换 DDS 后端后节点可以分布在别的进程/机器上。

## 总线档位 (由产品档决定, 不是随手开关)

| 档位 | comm / topics | 后端 |
|---|---|---|
| 550B 标定版 | dds / all | **DDS (Cyclone)** — 话题前缀 `zmax_mw::` |
| 550A | dds / core | 共享内存总线 `/dev/shm/zmax_mw/<ns>.bus.jsonl` |
| 550C | shm / none | 共享内存总线 |

诊断覆盖: `ZMAX_MW_BUS=dds|shm|mem`、`ZMAX_MW_DDS_DOMAIN=0`。

## 计算面开关 PURE (红线)

生成的节点模块里 `PURE = False` 是默认值 —— 只走**数据面** (outN←inN)，
**不自动执行实现**。原因: 会动设备的节点 (EXEC_MODE=act) 与未逐一验证口径的节点，
不许在无人授权时跑 (8793 授权是唯一入口)。
要开某个节点的计算面: 把模块里 `PURE = True`，并给同口径判据。

## 命令

```bash
# 工程: 加载 / 跑一拍 / 看某节点 / 只看总线门控
./gui-venv311/bin/python tools/mw_project.py load
./gui-venv311/bin/python tools/mw_project.py step
./gui-venv311/bin/python tools/mw_project.py node ssff
./gui-venv311/bin/python tools/mw_project.py bus

# 节点模块生成 (工程 JSON 变了就跑一次) + 幂等校验
./gui-venv311/bin/python tools/gen_middleware_nodes.py
./gui-venv311/bin/python tools/gen_middleware_nodes.py --check   # 有漂移 exit 3

# 判据 (10 项: 加载/端口/数据面/门控/跨进程/DDS/右键落点)
./gui-venv311/bin/python tools/verify_middleware.py
```

## 控制台里

* **画布每个节点右下角** `◉DDS` / `◉内存` = 这个节点的模块加载在哪条总线上;
  悬停 tooltip 显示模块文件、输入→输出端口、实现绑定。
* **加载工程时** 自动形成中间件工程 (`SimulinkModule._mw_build_project` → `self.mw_project`)。
* **右键「打开工程」** 先进入 `nodes/n_<id>.py` (端口/compute 都在)，日志里同时给出真实现位置。

## 加一个节点

1. 画布上连线 (端口由此产生) → 保存工程 JSON
2. `tools/gen_middleware_nodes.py` 生成/更新 `nodes/n_<id>.py`
3. 视需要把该模块 `PURE` 打开并写 `compute()`
4. `verify_middleware.py` 必须仍 10/10
