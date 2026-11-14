---
name: l2-node-signal-linkage
description: "Use when 要证明画布节点信号真联通(不是画布画着、实际空口), 或节点点了崩/下游读不到值。"
version: 1.0.0
author: Hermes Agent
license: private
metadata:
  hermes:
    tags: [canvas, dds, registry, port, verification, zmax, l2]
    related_skills: [algorithm-middleware-layer-separation, dispatch-chain-integrity, integration-level-audit]
---

# L2 节点信号真联通核验 (画布声明 ≠ 实现交出)

## 比空口更隐蔽的一类：端口有值但读错字段

空口 = 端口是 None（能扫出来）。真难找的是：下游**确实调了** `ctx.get("in5")`，但 `_pick("in5", ("contact_p","p","score"))` 的候选键和上游载荷对不上 ⇒ 取不到 ⇒ 等于没接，且验证器看到"端口有值"会判 OK。

**排查手法**：不要只看边有没有值，要看**下游拿它当什么用**。做法：对每条入边，把上游真实 payload 的键集合与下游 `_pick`/`ctx.get(...).get(...)` 的候选键做**集合差**；交集为空 = 伪接通。

实例：`ssaoi.out1 → sssched.in5` 画布标签「质量门」，`safety_limit_impl` 却当 `contact_p` 读 —— AOI 载荷里根本没这三个键。修法不是补字段，是**按语义重写这条边的消费方**（质量门 → 硬否决）。

**第二类伪接通：包装假设错（`.get("value")` 取到 None）**
端口载荷有两种合法形状：`{"value": X}` 包装，或直接是业务字典 `{"kind":"u_ff","u_ff":[...]}`。
消费方写 `v = pv.get("value")` 时，业务字典返回 `None` ⇒ 后面 `if isinstance(v, dict)` 整段跳过 ⇒
`u_ff` 读不到 ⇒ 走「缺前馈 ⇒ 直通」的兜底分支 ⇒ **下游 `decide()` 一次都没被调用**（日志刷 1,520 条
「调制器未生效」，而断点永远不进）。
- 修法：`v = pv.get("value", pv) if isinstance(pv, dict) else pv`（有包装取包装，没包装用本身）。
- 判定顺序必须是「先证函数被调用，再谈断点行」：在函数体**第一条语句**数调用计数/放自停锚，
  计数为 0 ⇒ 断点行永远不会命中，别去挪断点。修后取证：`out1.kind=modulator · u_sat=[...] · 技能 clamp 真执行`。

## 全图验收 (L1~L5 + 执行层)

`python tools/verify_l2_linkage.py --engine --all` 跑画布全部 94 节点 / 222 边。
**分层归属不要靠节点名猜**，用 `engineering/{l1_robot,l2_basic,l3_advanced,l4_expert,l5_human_sync}`
各自 `__init__.py` 里的 `NODES` 表（ast.literal_eval 取每个 tuple 第一项）。

### 引擎侧两个致命前提
1. **必须先 `eng.fit(obs_all)`**：引擎默认 `z_source` 是「内建 PCA 对当前状态拟合」，
   单帧拟合 = 单样本 ⇒ 方差 0 ⇒ `z` 恒全零。GUI 点 ▶ 是先 fit 全轨迹再逐帧 step。
2. **`ManifoldEngine(homeostasis=False)`**：常驻 `tools/ss_engine_loop.py`（10Hz）会写
   `zmax_data/ss_live/manifold_homeostasis.json`，两个引擎抢同一个 `.tmp` ⇒
   `os.replace` FileNotFoundError。

### 验证器自身的两个假阳性
- **`__pycache__` 陈旧**：改了实现但验证器仍报「返回 bool」——清 `impl/__pycache__` 重跑。
  （判断法：单跑该节点看真实返回类型，与验证器报告对比。）
- **同端口多上游**：引擎 `_collect_inputs` 是 `ins[port] = src`「最后一条覆盖」，
  验证器若也只看最后一条会把有值的边判空口。判定要用**任一非空**，
  同时单独报「N 条上游 / M 条有值 ⚠️ 有信号被覆盖」——这本身就是真缺陷（如 ssdec.in5）。

### 断点根因四分类（别混）
| 现象 | 根因 | 处理 |
|---|---|---|
| 返回 bool / tuple | 算完不交（值在局部变量或 `_SS_STATE`） | 构造 payload + out1..outN |
| 返回 dict 无 out 键 | `_NodeOut(扁平dict)` | 包 `{"outN": dict(_rb), **_rb}` |
| 无绑定 | 注册别名不含画布真名（改名后没跟） | `_reg` 别名补画布现名 |
| 空口但代码 OK | 真值缺失（无相机帧 / 无引擎轨迹 / 模型未训练） | **如实标注 note，不假造** |

**显示层节点不产出数据**：如 `ssz700`（Z700 真机信号窗）只开窗看图，画布却给它连了 6 条
「真机帧/位姿」出边 ⇒ 这是**画布连线错位**，不该给它补端口，应改接到真值节点。

## When to Use

- 要说「链路通了」但只在画布上看到连线；
- 节点点 ▶ 报错 / 静默返回 / 下游读到 None；
- 用户追问「信号真的联通吗，不要骗我」；
- 节点迁文件、删模块、改注册表之后。

场景: 老倪「你要保证这些 L2 的节点, 信息, 信号是真正联通的, 不要骗我」。
静态读代码不算数 —— 画布上 222 条边看着都在, 实测真联通率可能只有 35%。

## 判定口径 (三态, 不许含糊)

| 状态 | 含义 | 判据 |
|---|---|---|
| OK | 上游 outN 有值 **且** 下游 inM 拿到 | both non-None |
| 空口 | 上游该端口是 None | 节点没交出结果 |
| 崩 | 节点执行抛异常 | 转调缺失/依赖不全 |
| 未送达 | 上游有值但下游 ctx 里是 None | **多为成环一拍延迟, 不是断** |

## 必须跑两拍

状态空间是**有环**的 (sslimit→n_exec→ssinnov→sssched→sslimit; ssobs↔sssensor)。
只跑一拍会把 5 条环上边误报成「未送达」。第一拍产出跨拍累积, 第二拍再按拓扑序执行一遍,
拿第二拍的 got 判边。不跑两拍 = 误报, 会被当成链路故障去修空气。

## 解析链: 画布节点 → 执行函数

```python
from lerobot.middleware.nodes.impl import shared_runtime   # 触发全部 _reg
from lerobot.engineering.registry import NODE_LOGIC, match_node
key = match_node(node["name"])              # 最长关键字匹配
fn  = NODE_LOGIC[key]["fn"]
```
- `NODE_LOGIC[key] = {match, fn, doc, module, file, line}`; `register()` 同 key **覆盖**。
- `engineering/l2_basic/__init__.py::NODES` 还有一张 (画布id, 名称, key, 文件, 函数) 表,
  它会在之后注册并**覆盖** shared_runtime 里的绑定 ⇒ 改 shared_runtime 的 `_reg` 可能白改。
  遇到「我改完还绑旧函数」先查这张表。
- `_EXTERNAL_LOC` **只用于右键看源码**(VSCode 打开), 不是执行入口。看见它指向存在的文件
  不代表节点能跑。

## 三类真断点 (按出现频率)

### ① 只写 `_SS_STATE`, 端口全空 (最普遍)
节点 `return True` 或返回扁平 dict, 值全进进程内共享 `_SS_STATE`。
同进程下「能用」, 但画布声明的 out 端口读到 None —— 跨进程/跨线程/被别的节点按端口读就断。
**修法**: 在 return 前组装端口 dict, 字段名对齐下游 `_pick` 候选。
```python
return {"out1": {"kind": ..., "u_fb": [...], "residual": [...]}, "out2": {...}, "ok": True}
```
下游 `_pick("in8", ("u_fb","residual","res","err","u"))` 六个候选挨个试 —— 容错但掩盖契约不一致,
补端口时优先按**第一个候选名**给。

### ② 转调壳指向不存在的文件
`def node_x(ctx): from .ss_y import ...` 而 `impl/ss_y.py` 全仓不存在 ⇒ ModuleNotFoundError。
实测一次扫出 5 个(ss_est/ss_correct/ss_world/sssk8/ss_mani_p), 全在「执行链外迁」时漏建。
**扫描法**: 正则抓 `def (node_\w+)\(ctx\):` 后紧跟的 `from \.(\w+) import`, 逐个 os.path.exists。

### ③ 源码丢失只剩 pyc (如 `_single_thread.py`)
`impl/_single_thread.py` 没了但 `engineering/nodes/__pycache__/` 里有 pyc,
而 6 个节点 `from ._single_thread import brk` ⇒ 3 个 L2 节点直接崩。
**恢复法** (别猜, 反汇编还原):
```python
import dis, marshal, types
code = marshal.loads(open(pyc, 'rb').read()[16:])   # 跳过 16 字节头
for c in code.co_consts:
    if isinstance(c, types.CodeType):
        print(c.co_name, c.co_varnames[:c.co_argcount])
        dis.dis(c)
```
- 必须用**与 pyc 同版本**的 python 反汇编（3.11 的 pyc 用 3.11 dis，3.14 dis 会 IndexError）。
- 先 `importlib.util.spec_from_file_location` 加载 pyc 跑一遍验证接口可用, 再按反编译写源码。
- 快路径: `cp x.pyc impl/x.pyc` 可作 sourceless import 临时救急, 但仓库里不许长期留 pyc。

## 复合节点的分流约定

一个入口函数承载多个画布节点是**合法设计**, 不是错绑:
- `ss_ff.py::node_ss_s2` 内 `if "估计" in name:` → 状态估计器分支, else → 前馈加速器
- `state_correct_impl.run` 内 `if "校正" in name:` → 状态校正器, else → 先验动力学
- `ss_limit.py::node_ss_s3` 同时服务「动作调制器」和「安全执行边界」
改之前先看有没有 name 分流; 判「错绑」的唯一依据是 `engineering/l2_basic` 那张表。

## 修复顺序 (按依赖, 不是按文件顺序)

1. 缺失文件 (① 类崩) —— 不补, 后面全是空转
2. 主干的第一环: `ssobs` (6 个下游全吃它) / `sssensor`
3. 预测-校正链: `ssest` → `sspred` → `ssinnov`
4. 收口: `sssched` → `sslimit` → `n_exec` → `ssact`
5. 旁路: `ssaoi` / `n_geoplan` / `ss_mani_eng`

## 验证器骨架 (可复用)

`tools/verify_l2_linkage.py`: 读画布真源 → 取子图 → 拓扑排序(成环节点排最后) → 两拍真调 →
逐边判 OK/空口/未送达/崩 → 汇总真联通率。
- 每节点 `signal.setitimer` 超时保护 (AOI 要 2.5s, 引擎投影要几秒)。
- `ctx = {"log": 收集器, "params": 画布 params, "name": 画布节点名}` —— name 必须传,
  否则复合节点的分流走错分支, 验证结果全错。
- 结果: 修前 12/34 (35.3%), 修后 33/34 (97.1%); 剩 1 条是「无相机帧 ⇒ 不产 3D」的真值缺失,
  不是链路断 (看 log 确认, 别算成失败)。

## 铁律

- 「画布上连了」≠「信号通了」。判据只认实测：上游 outN 与下游 ctx[inM] 同时非空。
- 报联通率必须给分母和逐条明细, 不许只说「都通了」。
- 真值缺失（无帧/无标定/无授权）与链路断开要分开报 —— 前者不是 bug。
