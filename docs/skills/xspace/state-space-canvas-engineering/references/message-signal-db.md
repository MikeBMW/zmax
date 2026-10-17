# 画布 → 工程库: 报文/信号注册表 (CANoe 口径)

用户口径:「数据空间的显示要根据配置中心的参数中心的**数据库**实际配置」;
「状态空间工程的所有连接关系, 那个可以保存的 json 文件, 保存到状态空间的工程数据库」。
一句话: **画布 JSON 是人编辑的真源, 工程库是给系统查的注册表, 两者必须同一个写口。**

## 1. 概念映射

| CANoe | 本系统 | 表 (`data/database/zmax/zmax_engineering.db`) |
|---|---|---|
| Database (DBC) | 状态空间工程库 | `mw_project` |
| ECU / Node | 画布功能节点 | `mw_node` (+`mw_port`) |
| Message | **一个输出端口的一帧** = `ss.node.<node>.<port>` | `mw_topic` (dir=out) |
| Signal | 报文 payload 里的扁平字段 `a.b.c` | `mw_signal` |
| Signal 单位/量程 | 参数中心 `params` (unit/min/max) | `mw_signal.param_id` |
| Sender / Receiver | 连线两端 | `mw_link.f/t` |

节点输入 topic = 上游节点的报文; 输出 topic = 本节点的报文。一个端口恒等于一条报文
⇒ **报文身份跟着画布走, 不许在代码里另起名字**。

## 2. 单一写口

```
flows.save_canvas()  (写盘唯一入口)
  └─ os.replace(tmp, realpath) 成功后 → db.sync(specs, links, path)
       写 mw_project/mw_node/mw_port/mw_link/mw_topic/mw_signal
```

- 库写失败**不回滚画布** (画布已原子落盘), 但必须 `print` 留痕, 不许静默 `except: pass`。
- 不在 GUI 里另开写库路径: 双写口必然漂移。

## 3. 三个已踩过的坑

1. **只看 sha 会漏派生表**: 新加 `mw_signal` 后老库 sha 仍与画布一致 ⇒ `ensure_synced()` 直接
   返回"已同源", 信号表永远是空 (实测 113 个输出端口 / 0 条信号)。
   同源判据要带派生表: `COUNT(mw_signal) >= COUNT(mw_port WHERE dir='out')` 才算同源。
2. **占位信号不许参与参数匹配**: 未声明时写 `signal='value'` 占位; 若拿 `value` 去 `LIKE
   params.param_id`, 会乱命中(`value` → `calib:plane_z.value`), **凑出来的单位比空着更坏**。
   规则: 占位名或没有 node/impl 前缀时直接返回空, 页面显式标「端口整体值(未声明)」。
3. **报文必须带层**: 层 = 端口所属节点的 `layer` (空则回落
   `lerobot.engineering.nodes.by_level.LEVELS_INDEX`)。否则 150+ 条报文平铺, 用户找不到
   (「按 L1~L5 分类, 要不不好找」)。本工程不存在 L1 ⇒ **不硬造空组**, 根节点 tooltip 写"本工程未用"。

## 4. 信号从哪来 (优先级)

1. 节点模块/画布 params 里 `_signals = {port: [{name,unit,min,max,dtype}]}` (声明) —— 首选;
2. `live.json` 的 `topics[*].fields` (实测运行时) —— 补齐, 标 `src=实测`, **不覆盖声明**;
3. 参数中心 `params` 按 `<node>.<port>.<signal>` / `<impl_key>.<signal>` 补 unit/min/max;
4. 都没有 → 页面显 `—`, 不猜、不造。

## 5. 下游消费者

- `lerobot.dataspace.busdb.build()` 真源 = 工程库 (库不可用才回落画布 JSON)。
- 报文的下游 = `mw_link` 里 `f==node & f_port==port` 的 `t`: 这是 UI 里 Tx/Rx 两列的**唯一来源**,
  不要在显示层另算一遍 (两处算法必然漂)。
- 改库一行再重新 `load_project()` → `Node.topic()` 立刻变 = 话题名确实走库 (判据见
  `tools/verify_mw_db.py`, 7 项)。

## 6. 保存流程探针 (不动真源画布)

```bash
PYTHONPATH=src ./gui-venv311/bin/python tools/verify_mw_db.py          # 7 项
PYTHONPATH=src ./gui-venv311/bin/python -m lerobot.dataspace.busdb --build
```
写盘探针用**独立工程名** `flows.save_canvas(d, name="probe_xxx.json")` → 查三张表行数 →
删探针工程与文件。直接拿真源画布跑探针会把存档/库一起改动。
