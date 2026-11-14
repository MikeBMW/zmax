---
name: zmax-state-space-architecture
description: "Use when 状态空间画布 debug — 字段来源(预定义vs预测), 教学解析层vs真实权重, 节点源码映射."
---

# Z-MAX 状态空间画布架构与源码溯源

状态空间(状态空间仿真画布)是 left_right 双脑策略的仿真蒸馏版。用户(老倪)反复 debug
此区域, 高频问题: "某字段是预先定义还是模型预测的?" / "为什么两个模块源码一样?" /
"这是不是写死的?"。本技能是溯源方法和架构事实。

## 分层模型 (谁产生什么)
- **感知层** (state_space/perception.py, tools/gui/state_space_sim.py): 构造 obs。
  仿真里 target/孔位 = **HOLE_POS 预定义常量** (metaworld goal) + `_stage_target()` 阶段子目标,
  由感知层写进 obs[36:39]; 真机同构 (gen_insert_video.py) = `aligner.detect_3d`(YOLO 检测+3D
  反投影解算) 写 obs[36:39]。
  **obs43 的确切布局** (`fuse_sensors` = `K_obs×visual39 + tactile4`, K_obs=1.0):
  `0-2 hand xyz · 3 gripper · 4-6 v_est · 7-9 peg · 10-12 goal · 13-15/16-17 预留 0`
  `| 18-35 上一拍同一组 (18-20 hand,21 grip,22-24 v,25-27 peg,28-30 goal,31-35 预留)`
  `| 36-38 target · 39 gripper · 40 contact · 41-42 预留`。前馈 MLP **只吃前 39 维**, 触觉 4 维不进网络。
  自证三式 (随口报数前先算): `v_est ≈ (hand_cur - hand_prev)/ctrl_dt` · `goal` 当前与上一拍逐位相等 (常量) ·
  `target - peg` 的 z 偏移量 = 当前阶段悬高 (如 0.1m ⇒ 接近段)。
- **并行层** (state_space/parallel.py): FeedforwardAccelerator (obs→u_ff) + AdaptiveStateEstimator
  (递归潜状态+卡尔曼)。**只读 obs, 不产 target**。
- **认知层** (state_space/cognition.py): 调度器 u = w_ff·u_ff + (1−w_ff)·u_fb + 状态机。
- **世界模型 (右脑 RightBrainWM)**: 只预测 next_obs + contact 概率, **不产出 target**。
  target 是任务目标(先验), 世界模型是动力学 — 语义两码事, 别混淆。

## 教学解析层 vs 真实权重 (识别"模拟伪装")
- `state_space/parallel.py` 的两个类 = **画布教学解析式, 全仓库零引用** (仅画布/验证脚本用):
  前馈加速器 = 手写 Kp·(target−pos) 限幅公式 (注释自称"等价于训练后学的" = 示意, 非真);
  状态估计器 = 线性卡尔曼 A=0.95/K=0.5 (非训练 GRU)。
- **真实训练权重前馈**: `tools/gui/state_space_sim.py::ff_forward` — 从 npz 加载 W0-3/b0-3 +
  归一化参数 (sm/ss/am/astd) 做真 MLP 前向; `tools/ss_verify_trained.py` 加载 LeftBrainMLP
  权重替换 FeedforwardAccelerator 做闭环验证。
- 通用判别: 手写解析公式 + 注释声称"等价于训练后学的" = 教学/画布层; 真权重必有 npz/pt
  加载处 (outputs/rl_peg/full_pipeline.pt 或 state_space_sim npz)。

## 🏢 包分层 (2026-11-10 定调): policies=算法 · middleware=通讯 · engineering=L1~L5 编排桥梁

老倪定的三句话是判断"代码该放哪"的唯一依据 —— **一个画布节点 = 三个文件, 不是一个**:

| 层 | 目录 | 写什么 | 不许写 |
|---|---|---|---|
| 算法 | `policies/` | 纯函数/类: 模型、几何、控制律 | 读总线、知道节点名、import middleware |
| 通讯 | `middleware/nodes/n_<id>.py`(契约) + `middleware/nodes/impl/<node_key>.py`(实现) | 契约只写端口/话题/`PURE`; impl 写取数→调 policies→打标→节点级缓存 | 算法本体写进 impl、契约里写业务逻辑 |
| 编排 | `engineering/l1_robot/` … `l5_human_sync/` | 分层设计: 本层层义、必须还能干的事、节点清单(实例数据) | **放节点实现** —— `engineering/` 里不许有 `nodes/` 目录 |

判断法: **换个机器人还能用 → policies; 换个传输协议要改 → middleware(含 impl); 只把两者接起来并留证据 → middleware/nodes/impl。**

### 把算法从 impl 迁进 `policies/<域>/` 的定式 (节点只留薄壳)

用户口径「这个算法怎么能在中间件里呢? 算法在 `src/lerobot/policies` 算法路径统一管理」时, 按这几条做:

1. 新包 `policies/<域>/` 与 `yolo_3d`/`sam3_seg` 同级, 一文件一路(来源不同的并列写, 例如 `gold.py` 搬运工控机真值 /
   `gold_yolo.py` 本机推理 / `surface.py` 本机重算), `__init__.py` 里 `__all__` 导出。
2. **依赖方向只能 policies ← middleware**: 包内**不许** `import lerobot.middleware`。进程内缓存与话题发布一律
   **由调用方注入** (`fn(log, cache, publish)`), 签名里显式带 `cache/publish`。
3. 过渡期在 `shared_runtime.py` 留**注入式薄转发**(老调用点不用改), impl 里直接 `from lerobot.policies.<域> import …`。
4. 迁完必须**真跑一次节点**(`node_<key>({"log": sink})`) 再报完成: `py_compile` 与 `import` 都过不代表能跑;
   判据 = 返回 dict 里字段有真值 + 日志里每个来源都打了自己的 src 标记。
5. 🔴 **返回值里的字段名要逐个对账, 读"没定义过的全局名"不会报错**: 条件表达式 `f(globals().get("X")) if isinstance(globals().get("X"), dict) else "未接"`
   里 `X` 不存在时 False 分支直接走, 永远显示兜底文案「未接」—— 实测 `remote` 字段因此长期假报"表面未接",
   而同一轮日志里明明有 verdict。修法: 从算法层回写的缓存取真值 (`cache["surface_aoi"].verdict/why`)。
   迁移后逐一核对返回字段 == 日志里的真数, 别只看不抛异常。

```
src/lerobot/middleware/nodes/
  n_<id>.py            端口契约 (生成物, tools/gen_middleware_nodes.py)
  impl/<node_key>.py   节点实现: 一个节点一个文件, 文件名 = 画布节点 key
  impl/shared_runtime.py  所有节点共用的运行时 (原 engineering/nodes/library.py)
src/lerobot/engineering/          ← 没有 nodes/ 目录
  l1_robot/ l2_basic/ l3_advanced/ l4_expert/ l5_human_sync/   每层的层义+节点清单 (生成物)
  layers.py      汇总: LEVELS_INDEX / keys_of / funcs_of / summary
  levels.py      每层"必须还能干的事" + check()   (层归属唯一真源: band_map + OVERRIDE)
  paths.py / registry.py / runtime.py / flows.py / sourceview.py / single_thread.py
  node_map.json  一节点三处 (生成物, tools/gen_node_map.py)
```

**层义 (老倪 2026-11-10 定名, 唯一口径)**: L1 **机器人接口** · L2 **基础功能** · L3 **高级功能** ·
L4 **专家功能** · L5 **人机同步**。实测分层节点数 L1 4 / L2 26 / L3 5 / L4 19 / L5 11。
L1 原来混在"基础功能"里 (`ssact`/`n_exec`/`sslimit`/`ssworld`) —— 接口收口与算法混层会让人以为
"基础功能"同时管执行器和检测; 分出来后 L2 从 29 降到 26。

### 契约里的 `LAYER` 也是生成物 —— 层标记的真源是画布/库里那一份

`n_<id>.py` 的 `LAYER='L2'` 手改**一定会被下一次 `gen_middleware_nodes` 抹掉**: 实测一次全量重生成把
`ssaoi` 的 `LAYER='L2'` 改回 `''`, 同时 DB `mw_node.layer` 也是 `''`(画布源 `state_space_obs.json` 里该节点 `layer: null`)。
⇒ 改层归属只能改**画布真源 (+DB)** 再重生成; 判据 `grep '^LAYER' n_<id>.py` + `select layer from mw_node where node_id=…`
两处一致, 否则下游 `attribution.layer_of` / 分层审计会把该节点判成 `meta`/SYS, 整族信号不上表。
发现"登记过 L2 现在变空"时, 先查是哪个重生成动的(find 出的 git 历史里那笔一定是节点改名/重生成提交), 别在生成物上补一遍了事。

### 搬目录时必须一起改的 5 处 (少一处就 ImportError 或判据假红)
1. `engineering/paths.py`: `LOGIC_FILE` 指 `middleware/nodes/impl/shared_runtime.py`, 加 `BY_LEVEL_FILE` 指 `engineering/layers.py`。
   路径常量不动 ⇒ 写节点逻辑的工具会往已删除的路径写(静默)。
2. impl 里原来从 `engineering` 拿的模块要改成**绝对导入** (`from lerobot.engineering.modload import …`);
   `middleware/nodes/impl` 的 `..` 是 `middleware/nodes`, 相对导入必断。
3. 校验/审计脚本里写死的 `lerobot.engineering.nodes` / `engineering/nodes/library.py` 字符串 (verify_engineering、
   gen_node_map、gen_by_level_index、layer_calls、busdb) 全部要改, 否则重构后判据报 `No module named 'lerobot.engineering.nodes'`。
4. 契约头里的 `实现绑定` 由生成器写, **别手改** —— 改 `tools/gen_middleware_nodes.py` 再重生成 79 个。
5. 生成器输出路径跟着搬: `by_level` → `engineering/layers.py`; 生成后跑 `verify_engineering` + `canvas_level_audit`,
   两套数字**必须与重构前逐项一致** (实测 R1 15/R2 42/R3 12/R4 7/R5 2), 否则是搬漏不是搬好。

溯源: `get_node_triple("ssyolo")` → `{contract: middleware/nodes/n_yolo.py:1, impl: engineering/nodes/ss_yolo.py:22,
 algo: policies/yolo_3d/yolo_state_aligner.py:1, layer: L2}`。**右键只给一处(契约)会让用户以为实现丢了** ——
回答"代码在哪"一律给三处, 并说清哪处是契约(不含业务逻辑)。

- 契约文件与 `_index.py` 由 `tools/gen_middleware_nodes.py` 生成, 实现文件与 `by_level.py`/`node_map.json` 各自有生成器 ⇒ **全部别手改**, 改生成器再重生成。
- 拆/合节点的完整流程、AST 切分脚本、四个静默坑 (registry 里 NODE_LOGIC 被换绑定 / 多 key 共用一个函数 / `global` 语句 / 生成器占位符落错文件名) → `references/node-code-split-and-three-layer-map.md`。

`tools/gui/node_logic.py` = 33 行兼容壳 (转发包命名空间) · 仓库根 `flows/state_space_obs.json` = 软链。
**新增/改节点逻辑写 `middleware/nodes/impl/<node_key>.py`, 不要再写回 GUI 目录, 也不要再往 `shared_runtime.py` 里加函数。**

溯源链 (从画布节点名 → 真代码): `registry.match_node(节点名)` → key →
`sourceview.get_node_location(key)` / `registry.home_file(key)` (用 `fn.__code__.co_filename`, 所以搬完自动指对地方)。

### ✅ 「按分层重新跑一遍所有层」的验收口径 (别只报"跑过了")

`tools/layer_e2e_verify.py [--frames N] [--cam close] [--weights models/ar_yolo_v2.pt]` 一轮出
`reports/layer_e2e_<ts>.{json,md}`, 每层必须有**数字**, 不是"能导入":

| 层 | 必给的数 | 不合格的样子 |
|---|---|---|
| L1 机器人接口 | 位姿真值文件可读 + **明确写"未下发任何指令"** | 写成"已验证接口"但没说有没有动臂 |
| L2 基础功能 | 帧数/检出帧数/平均 conf/单帧 ms/**带 3D 的帧数** | 只说"YOLO 跑通了" |
| L3 高级功能 | 耗时 + 返回 JSON 的键 (目标可见/在夹爪上/朝向) | 返回 True 当证据 |
| L4 专家功能 | 意图 → 几个技能 token + token 内容 | 调不到入口就说"已就绪" |
| L5 人机同步 | 元任务条数 + task_id + 前几条名字 | 数成 0 还标 OK |

L5 元任务真源不是 `config/ar_meta_tasks.json` (没有), 而是 `data/database/zmax/sources/config/tasks/ar_meta_tasks.json`,
键名是 `meta_tasks` / `task_id` / `lanes` (不是 `tasks`)。数 0 就是读错了文件或错键。

**训练候选一律同源 A/B, 不提升不进默认档**: `tools/l2_ab_eval.py --a v2 --b v3` 把**同一帧**同时喂两个权重
(不是各跑 N 帧 —— 臂在动, 帧本来就不同), 报检出率/conf/框 IoU。实测一次: v3 (batch1/imgsz512 微调 6 epoch)
val mAP50 0.248 vs v2 0.255 · 同源 A/B 85% vs 100% ⇒ **v2 留役**, v3 只存档。显存被引擎占满时小 batch 微调
基本不会赢, 别拿它当"重训过了"交差。

### 🔴 画布上的开关/拨钮必须真实现, 不是改标签画布节点 `params.src_state` 写着什么, 节点实现里就必须有对应的分支去取那个数据源 —— "画布写着 AR场景、
代码只认 metaworld|orin" 就是假接入(用户一问"代码在哪里"就露)。落地范式(数据源节点实测):

1. 实现里按**画布参数**判定 (`src_state`/`source`), 命中选择就真去取数据并落 `_SS_STATE["data_source"]`
   (`src/cam/w/h/bytes/ts/cam_params`), 日志打实测值(分辨率·字节·相机参数·帧名)。
2. 消费方 (如 L2 YOLO) 取源优先级 = **画布 > env > 默认**: `_SS_STATE["data_source"]["src"]` 带 **10s 时效**,
   过期才回落 `ZMAX_L2_SRC` —— 无时效会把"画布停了"变成死锁在 ar。
3. 契约 `PARAMS.source`/`desc`/`source_symbol` 一并更新并重生成 —— 留旧路径 (`engineering/nodes/library.py`)
   会让人以为实现丢了。
4. 自证: **不设任何 env**, 只让画布选择生效, 看节点日志出 `📦 数据源: AR 场景 (…960×720… B…)`、
   下游出 `🎯 AR 源 (ar_frame_*.png …)` + 3D 点。只改标签也能跑, 所以判据必须是"取到了真帧"。

层义与节点数见上「层义」一节; 判据 = `levels.check()` 里每层 `no_logic_key` 为空 (`ss_moe` 这类
画布有节点无执行注册的会单独报 → 归 L2/`26` 里的缺口, 不要为了凑数把它算过)。

#### 全链路只允许一个世界 (改完数据源节点还不够)

只把「数据源节点」改真, 下游仍会各开一套世界 —— 实测三处: `intact.py` 自建 metaworld env、
`sw_ds.py` 自起 stable-world 桥、`_vlm_frame()` 的「真机旧图」分支抢先返回 (AR 已被选还读真机帧)。
定式:

1. **单一读取口**: `shared_runtime._canvas_source(ttl_th=10)` 只读 `_SS_STATE["data_source"]` (数据源节点每拍写),
   所有消费方 (yolo / vlm / seg / intact / L4 桥) 一律调它; env 变量 (`ZMAX_L2_SRC` / `ZMAX_SS_FRAME_SRC`) 只做兜底。
2. **下游不许自建世界**: 发现节点里 `MT1(` / `env.step` / 起 render 桥 / `make(`, 就在最前面判画布源;
   选中 AR 时改为**读 AR 帧并传进去** (INTACT: `run_once(obs_frame=arr, obs_source="ar(...)")`),
   或明确**跳过并留日志** (`skipped_sim_bridge=True`) —— 静默各跑各的比报错更难查。
3. **同一拍可对账**: 数据源节点写 `tick=int(time*1000)`, `_ar_frame` 把它带进 meta, yolo/vlm 日志都打
   `tick=...` + `frame=...` —— 两个不同机位 (close 检测 / ar3d 场景) 是**设备分工**, 不是不同步; 但同一机位
   必须同 tick 同帧名。
4. **审计方法 (别凭印象说"都接了")**: 从 `flows/state_space_obs.json` 取 `links` 里所有 `f == 'ssdata'` 的下游,
   用 `node_map.json` 把节点 id 映到 impl 文件, 逐个 grep `_ar_frame(` / `_vlm_frame(` / `_yolo_capture(` /
   `metaworld` / `env.step` / `fetch`, 分类成 AR / 消费上游状态 / 自建世界。实测 17 个下游里只 5 个真取帧,
   3 个是违规的 —— 不扫一遍会漏。

同类搬运的验收口径 (以后照用): ①key 集合与顺序 ②画布全量节点名→key 映射 ③每条关键字/doc 逐字
④函数源码逐字哈希; 基线 = 渲染 87/172 · 档位审计 R1 15·R2 34·R3 13·R4 7·R5 3·真缺口 0。

### ⚠️ 注册 key 重名会静默覆盖 (实测事故)
同一个 key 注册两次 ⇒ 后一条把 fn+关键字一起换掉 ⇒ 画布上那个节点**永远 match 不到逻辑**。
实例: `ss_pred` 被「先验动力学」(dynamics.py) 与「流形专家」(manifold) 重复注册,
导致「📈 先验动力学预测器」长期不可执行 (落在档位审计 R5-待建); 已拆为 `ss_dyn` + `ss_pred`。
新加节点/改关键字后, 拿画布节点名跑一遍 `match_node()` 验非 None (或直接 `levels.check()`)。
**反过来: 目标节点若已有更长匹配的 key, 你新注册的短关键字 key 永远不命中** (实测给「标定诊断测量 · 主参数 M」
另立 `cfg_import` key 毫无效果, `match_node` 仍返回既有的 `n_calib_mani`) ⇒ 要给已存在的节点加行为, **改它自己的
节点函数或它已注册的 key**, 不要另立新 key。

### ⚠️ 往 `nodes/library.py` (5000+ 行, 一个文件装 140+ 节点) 插代码: 锚点必须唯一
1. **别拿通用注释当锚点** (`# ②`、`# 第2步`): 实测插进了**另一个节点函数** (`node_flight`) 里面 —— 编译通过、
   判据静默失败 (日志里就是没有那段输出)。插完必须回验: 取插入点前最近的 `def`, 确认正是目标函数。
2. **用「docstring 行 + 函数体首行」这类唯一多行上下文**作锚点, 交给 patch 工具插 (它会回报 diff)。
3. **缩进按该函数实际层级**: 节点函数体是 **4 空格**(不是 8), `try:` 4 / body 8 / `except` 4。
   `textwrap.dedent` 去掉的是**公共前缀**(不是固定 4 空格) ⇒ 8 空格内容会被削成 0 空格、函数被截断,
   报错形如 `'return' outside function` 且位置在几百行之后, 极难定位。
4. **插在函数 `try:` 块之前时, 该块要自带 `import numpy as np` / `import os`** —— 函数里的 import 在 try 内还没执行。
5. 改坏了的恢复链: `cp -a` 备份 → `py_compile` → `git diff --stat <该文件>` 应为空(即回到已提交状态) → 重做。

## 画布节点源码展示机制 (tools/gui/node_logic.py + node_logic_dialog.py)
- **执行层可共用分派函数**: 多个节点 _reg 注册同一 node 函数, 靠 `"关键词" in name` 分派
  (ss_ff/ss_est 共用 node_ss_s2, "估计"→AdaptiveStateEstimator, 否则 FeedforwardAccelerator)。
  这是设计, 不是 bug — 但会让"看源码"看起来重复。
- **编辑器源码展示优先级**: `node_logic_dialog._load_source` 先 `get_external_source(key)`
  (_EXTERNAL_LOC 按符号截取真实类源码, 只读), 无映射才回退 `get_node_source(key)`
  (返回注册的 node 函数整段)。**每个节点 key 都应挂独立 _EXTERNAL_LOC** — 两个节点
  显示同一段 = 缺映射或映射指向同符号。验证: `get_external_source(key)` 首行应为各自类名,
  不是 `def node_ss_s2`。
- 改 node_logic.py / _EXTERNAL_LOC 后必须重启 studio.py (旧进程跑旧代码)。
- 🔴 **`get_node_location` 会用符号串自己再搜一遍并覆盖行号**: 读到 `_EXTERNAL_LOC` 后按
  `行首 startswith(symbol)` 找第一处 `def`/`class` ⇒ 只把映射行号校准到 return **完全无效**, 右键永远弹回函数头,
  用户看到的就是"右键进来的这段代码不运行"。现行口径: 映射行落在函数体内就直接用, 否则按符号找定义再取首条 return。
  自证: `sv.get_node_location(match_node(节点名))` 返回的行必须是 return 行。
- 🔴 **同一个 key 的 `_EXTERNAL_LOC` 可能写了两遍**(实测 5 个), 后者静默覆盖前者 ⇒ 改前一条是死改动。
  改之前 `grep -c '_EXTERNAL_LOC\["<key>"\]'`, 重复的只留最后一条。
- 落点/断点逐个节点的验收入口 (不再靠手工抽查):
  `tools/verify_node_breakpoints.py --write` (每节点: 打开位置、该文件是否真执行、return 命中数) ·
  `tools/fix_node_source_loc.py --apply` (用真执行行把落点改到 return) ·
  `tools/model_ledger.py` (L2~L5 每个模型真加载一行台账: 存在/大小/耗时/参数量/设备)。
  模型加载一律经 `lerobot/engineering/model_log.py::note()`, 失败也打一行带原因。

## 调试铁律
1. **"预定义还是预测"类问题 → 追字段的写入者**: 谁构造 obs / 谁写 [36:39] (感知层?
   仿真真值? YOLO?), 不是读它的 forward。forward 被动读 obs, 回答不了来源。
2. **"两个模块源码一样" → 先跑 `get_external_source(key)` 对比首行**, 再判断是缺映射还是
   共用分派函数, 别猜。
3. **画布节点"真实执行"必须完整闭环**: 分派分支里只调 predict 不调 update (卡尔曼校正没
   执行) = 名不副实 — 2026-09-02 已修 node_ss_s2 估计分支 (补 obs39 z_k 校正闭环, 日志打
   predict 与 update 两步数值; 手算验证匹配)。
4. 改完 GUI 代码必重启 studio.py; 验证逻辑用 gui-venv311/bin/python (项目无 .venv)。
5. **「这个量是模型算的还是公式算的 / 谁在算」→ 三问定源, 别从画布连线推断**: ①**哪个进程**在算 ——
   GUI 回放进程 ≠ 常驻引擎进程, 同一个量在两边由不同代码产出; ②该进程的**开关 env**
   (`tr '\0' '\n' < /proc/<pid>/environ | grep -E "^SS_|^ZMAX_"`); ③代码分支 (真权重 / 解析式 / 纯公式)。
   实测插拔 3D 场景的四层速度: `u_ff` = 模型或解析前馈 (控制台进程**没有** `SS_INTACT`/`SS_L4_INTACT`
   ⇒ 那个 `v_ff` 不是 INTACT 输出, INTACT 只在常驻引擎那侧跑), `u_fb` = 纯公式 `clip(0.5×残差EMA)`,
   `u` = `u_ff+k_fb·u_fb` + 阶段限速, `u_sat` = 饱和 + 插入段回退; 而位置/姿态/夹持/帧号这些
   **是回放 npz 真值, 不是算的**。回答"是不是只有 X 是计算输出"必须把「算出来的」与「模型算出来的」分成两问答。
6. **由速度反推位姿: 位置能、姿态不能**。位置 = 积分 (用执行量 `u_sat/u_exec` 比用 `u_ff` 准得多),
   姿态推不出来 (动作只有 3 轴线速度 + 夹爪, 无角速度); `SSPlan` 只是 MoveIt 规划结果的镜像,
   **不反推位姿**。实测误差表、量纲自证法 (拟合缩放 k, k≈1 才说明单位与 dt 对) 见
   `references/metaworld-closed-loop-contracts.md` 末节。
7. **「界面说在跑」≠「这一层在算」; 档位是意图, 在跑的子链路才是事实**: 同一轮里往往有两条真源 ——
   画布节点参数(用户点选)与子系统状态文件(实际在跑, 如 `zmax_data/l5_loop/state.json` 的 `status==running`)。
   取值必须**事实盖过意图**, 而且发布方与消费方两处都按同一优先级, 否则同一轮会得出相反的档位口径,
   用户看到的就是"运行了 L5 却没有 L5 的输出"。另一条同类红线: **归一化四元数 q̂ 的模恒为 1,
   不能用来编码强度** —— 长度/亮度要按原始 |F| 取尺度(对数尺度 + 保底), 并把数值直接写到屏上;
   量级只信数字。太阳系/S³ 面板的完整口径见 zmax-console 技能里的「力场可视化」参考文件
   (force-field-visualization.md) §8/§10。
8. **「这些力/合力/四元数是模型推理出来的吗」→ 按四级来源分级回答, 不许笼统说"模型算的"**: 界面上同一个量常同时混着
   四种性质完全不同的来源 —— ①**实时模型输出**(前馈 MLP 真身前向的 `u_ff`) ②**回放数组**(最近一集 npz)
   ③**构造量**(方向取规划、力度借别的层) ④**标定标量**(M / 度量)。回答前逐字段落到"谁写这份文件/这个键"并报单位。
   三条硬规矩:
   (a) **显示编码 ≠ 物理量**: 表里的"力四元数" `q=(|F|/u_ref, Fx/u_ref, Fy/u_ref, Fz/u_ref)` 是为**能逐位相加**
   而设的表示(所以故意不归一: q(合力)=Σq_i), 不是单位四元数、更不是姿态四元数; 屏上的 q̂ 模恒 1, 只承载方向。
   (b) **力矩那条支路必须报开关**: `τ = M·(−∇Φ + α·u_ff)` 里 α(`u_ff_gain`) 只改显示与表; 只有 `apply_to_tau=true`
   才进控制回路 —— 默认关闭时**不许**说"这些力已经变成驱动力矩"(打开后实测 |Δτ| 仅 0.283 N·m, z 轴已贴限幅)。
   (c) 姿态四元数无真源时(`tcp_pose.rx/ry/rz=None`、`plan_from_vff.rotation="未建模"`)一律写"未建模/未算",
   不拿力的方向冒充姿态。
   逐字段真源表(含单位、自查命令、"看起来像但其实不是"三条)见 `references/force-and-quaternion-provenance.md`。

9. **`PURE=False` 的直通节点要「出理想规划」时, 只能加"理想档", 不能假装它算过了**: 现场没有 obs43 落盘
   ⇒ obs43→流形→测地线那条真档返回 `ok=False`。做法 = 新增 `ideal` 分支 + 显式开关 (`params.ideal` 或环境变量)
   + **不换端口语义** (out1 位姿 / out2 chunk[H,4]), 几何取**执行器同一个段表生成器**的稳态窗口 (不另造点位),
   段内用流形测地线 (S² 大圆) 采样成 chunk, 时序换理想剖面; 报告里必须写清「理想档 = 点位+动作+时序的理想规划,
   不是从感知得来的」, 并给 UPH 判定 + 余量。**默认不自动开** —— 它会替掉原直通输出, 下游读到的语义就变了。
   配套: 硬编码的兜底参数只许写成函数默认值并留开关, 不要让常驻循环无条件跑理想档。

## 🔌 节点计算面契约: 结果被吞 / 端口取不到值 / 判"有效"的口径

三个都是**静默**故障 (日志照跑、循环照转、端口全空), 排查代价极高。改节点实现/模板前先记住:

1. **非 dict 结果被整块丢掉**: 节点模板是 `if isinstance(res, dict): … else: LAST_STATUS="实现返回非 dict → 直通"`。
   实现返回 `np.ndarray` / `float` / `bool` (如 `safety.saturate` 返回限幅后向量) ⇒ **上游算出来了, 下游永远收不到**,
   状态行只写"直通", 看着像节点没实现。修法: `if res is not None: return {PORTS_OUT[0]: res}` (全部节点模块同款一处改)。
   判据: 改完跑一拍全量, 「端口真发出非空值」的节点数必须明显上升 (本仓 6 → 30/65)。
2. **`ctx[port]` 是信封不是裸值**: 常驻循环与 Project.step 传的是
   `ctx["in1"] = {"value": …, "age_s": …, "fresh": …}`。实现里把 `ctx["in1"]` 当裸向量用 ⇒ 永远报
   "无 obs43 输入"/"缺输入", 那条链一直空转。定式取数:
   `v = ctx.get(p); if isinstance(v, dict) and "value" in v: v = v["value"]; if isinstance(v, dict): v = v.get("obs") or v.get("state")`。
3. **判"节点有效"不许用 `bool(outs)`**: 节点可以只返回端口壳子 (`{"out1": {"value": None}}`), `bool` 为真但什么也没发。
   判据 = 至少一个端口 `value` 非 None / 非空 dict / 非空 list; 数"上游真发出值的连线"也要按 value 判,**不是**按
   总线里有没有那个 key (端口壳子也算有 key ⇒ 会报出 6/171 与 161/171 两个互相矛盾的读数)。
4. **写产物先算清仓库根深度**: `src/lerobot/engineering/nodes/x.py` 要**上溯 5 层**才算到仓库根, `middleware/nodes/x.py` 同理;
   少算一层就写到 `src/zmax_data/` 这种不存在/没人读的路径 ⇒ **静默不落盘**、也不报错。写完必须回读 mtime 龄,
   别用"代码里写了 dump"当证据。

6. **契约门不满足 ⇒ 节点只做 `out1←in1` 直通, 实现一次都没跑**。三样缺一不可: ①契约 `EXEC_MODE='pure'`
   ②画布节点 params 带 `pure_verified=true` ③`impl_key` 能命中实现。缺任一项时 `compute()` 收 **只含已连线端口的 ctx**
   (`{'in1': {'from': 'canvas'}}`), 实现侧取模块/输入直接 `KeyError: 'module'`, 状态行写"直通",
   而端口仍回信封、上游帧照流、下游"一切正常" —— 这是最贵的一类假绿。
   判据(三样一起看): `registry.match_node(<画布节点名>)` 非 None · 该节点 `PURE is True` · 日志里有真实现印记
   (例 `🎯 AR 源 (ar_frame_*.png … 帧源=canvas_out1)`)。只有端口有值不算接上。
7. **改节点名必须同步补注册关键词, 否则改名=断实现**。注册表按**子串关键词**匹配, 把节点改名成
   「📦 数据源 (AR场景 ⇄ 仿真 ⇄ 真机)」后旧关键词 (`metaworld 数据`) 不再命中 ⇒ `IMPL_KEY` 变空 ⇒ 静默直通(同 6)。
   定式: `_reg("<key>", [...])` 里补新名里的**稳定短语** (实测补 `AR场景 ⇄` / `数据源 (AR场景`), 然后
   `R.match_node('<新名>')` 断言返回该 key —— 改名后不跑这一句就等于没接。
8. **端口 = `compute()` 返回 dict 的键, 不是"多出来的字段"**。返回里出现 `PORTS_OUT` 之外的键 ⇒ 整坨被塞进 `out1`,
   下游按 out2/out3 取必空。要几个出口就显式 `{'out1':…,'out2':…,'out3':…}` 且与契约 `PORTS_OUT` 逐项一致;
   实测 `ssdata` 从"out1 里一坨"拆成 帧/状态/句柄 三端口后, 下游才可能按连线各取所需。

9. **节点之间的数据面不是 out1→in1, 是「同进程 dict + 跨进程 JSON」** —— 回答"下游节点收到上游输出了么"必须分这两层答:
   · `runtime.run_node` 造的 `ctx` 只有 `{module, params, log, name, label}`, **没有 inputs / 上游 out1** ⇒ 画布连线
     只是**拓扑语义**(谁依赖谁), 不是数据管道; 节点返回的 `out1` 只进 `LAST_OUT`(给节点级 SU(2) 映射取值), 不自动喂下游。
   · 同进程节点之间靠**模块级 dict**: 实测 `yolo_align.py` 直接读 `_YOLO_CACHE.get("det2d")`, **不读** JSON。
     跨进程/对外才落 JSON 契约(`zmax_data/ss_live/vision_points.json` 等), 供 plan/画布 GUI/8797/web 页消费。
   · 所以"为什么不用共享内存"的正确回答是: **已经是共享内存**(Python 进程内 dict, 零序列化)。真跨进程共享内存段要自管
     生命周期/锁/类型约束, 而这条链 2Hz、单写多读、几百字节 ⇒ 落 JSON 换来可审计 + 任意消费者 + 进程崩了不丢, 收益更高。
   · 🔴 **隐式耦合**: 靠 `_YOLO_CACHE` 的前提是上下游在**同一进程**。先按 pid 核清谁在跑
     (`pgrep -af 'ss_engine_loop|ss_canvas_loop'`); 把 YOLO 与 2D→3D 拆到两个服务的那一刻这条链立刻断, 只能改读 JSON 契约 ——
     别以为"画布上画着线就还通"。

10. **节点「看一眼结果」的入口 = 浏览器静态页, 不是 Qt 弹窗** (老倪口径:「渲染单帧, 也用浏览器打开, 不用单独窗口」):
   · 页面放 `tools/web/dl/*.html`, 交给**已在跑的只读静态服务 8799 的 `/dl/`** 投出去 ⇒ 不新增端口/进程、改完**热生效零重启**,
     手机/局域网 `http://<lan>:8799/dl/xxx.html` 同开。
   · 引擎侧写文件、页面只读文件: 跨进程(GUI ↔ 引擎)传图**必须落盘**(固定文件名 + 原子替换), 不能靠进程内缓存。
   · 页面横幅必须带**拍照时间 + 帧龄**, 帧停了变橙写"已停" —— 否则用户会把旧图当实时。
   · 要"跟另一个页面的视角同步"用 8802 的 `frame.png?cam=ar3d&live=1`(拿 AR 页推来的相机参数**现场**渲染);
     判据 = 连拍两帧 hash 不同 + 与缓存帧(nolive)像素差很大; 固定机位 `cam=close` 不会跟随。

5. **修好「结果被吞」之后必然撞上拍子**: 以前节点全直通 (每拍 ~0ms), 一修好就真算, 一次全量 pass 实测 25.3s
   (n_decoder 9.0s · n_skills 4.0s · n_prefrontal 3.7s · n_yolo 2.1s · n_hil 卡 https/GETDNS · VLM 节点走外部 HTTP 120s),
   10Hz 循环 tick 直接冻住 (88~160s 一拍)。定式: 常驻循环**分两档** —— 核心链每拍跑
   (ssobs→n_geoplan→ssff/ssest→sssched→sslimit→ssphys→ss_grav_h→n_moveit→n_exec→ssact), 每 30 拍跑一遍全量;
   单次 >60ms 或走外网的节点置 `ZMAX_NODE_PURE_OFF` (保持直通) 并交给旁路串行推理队列 (`tools/serial_inference.py`)。
   判据: `canvas_loop.json` 的 `cost_ms` 回到 15~21ms, 且 tick 持续增长 (不涨 = 卡在某节点, py-spy 直接抓)。
   别把「不接入」当妥协: 慢节点进拍子只会拖垮 AR 节拍, 300UPH 由工艺动作表决定, 与它们无关。

全系统贯通 (L5→L4→L3→L2 由后向前, 每层先发理想值, 再验 UPH 与联通) 的做法、每层理想值的定义、
43D 理想观察量的通道口径与判定数字 → `references/full-stack-ideal-value-run.md`。

## 🧮 流形层逐帧发布闭环 (2026-09-03 老倪: "为什么流形/潜空间没有输出连线")
- 回路外元层此前只读日志、无输出 → 半吊子。闭环: 引擎 run() 每步实算流形量
  (decompose/evaluate 纯 numpy, ~0.1ms) → tr["mani_risk/progress/eta/V"] 全程序列
  + _io_snapshot 发布 3 个 channel ("🧮 接触流形"/"🧮 性能流形"/"🧮 潜空间",
  out=进度/偏离/V·状态 | δ⊥/插深/V_p/η | 潜坐标/速度场 prior−x̂₋)。
- data_world.MODULE_ORDER 14→17 键 (物理世界后 append 3); 数据总线/3D 自动带出。
- StateSpaceScopeDialog 2x2→2x3 六格 (+ 法向偏离 #ff7b72 / η #a371f7), 画布连线
  ssmani_c→ssvideo(in2)/ssmani_p(in3)/sslat(in4) + 节点 outputs=["out1"]。
- 引擎加载流形: _find_mani_file/_load_manifold (module 名 state_space_mani, 缺失不阻塞)。
- 铁律: 回路外分析节点输出必须"有去向" — 要么进数据世界逐帧发布, 要么明确只读标注;
  禁止无输入也无输出(孤立)与有输入无输出(断头)。连线不改执行 (状态空间跑引擎拓扑)。

## 🧩 验证层 (2026-09-03 老倪: 系统要能逐个验证)
- 真源: src/lerobot/verification/verification_layer.py — FEATURES 注册表 (45 项:
  35 自动 F-A01~F-F04 + 10 GUI 手动 F-G01~G10) + **FEATURE_META (v4.0.1, 并行 dict:
  fid → (基本功能|泛化功能, 感知模型|世界模型|决策控制|规划推理|安全机制|引擎|数据平台|标定工具|GUI工具, 模型特点))
  — 加在文件末尾 main() 前 (勿插 FEATURES 后: 会错位 _EXTERNAL_LOC 行号锚点 47/97)**。
  list_features() 返回 dict 列表含 kind/role/spec (GUI 对话框/Excel 导出复用)。
- VerificationLayer (t_F_* 断言, 引擎跑一次缓存 tr; 六层/标定/流形 importlib 直载)。断言全部按源码契约手算可核。
- 画布: 底部「🧩 验证层」row_bg + 🧩 Feature 功能清单 (ss_feature) / 🧪 Test 用例执行
  (ss_test) — **v4.0.1 起双击/右键 = VerificationDialog (tools/gui/verification_dialog.py):
  45 项分类表格 + ▶运行全部测试 (后台 skip_slow) + 导出 Excel (3 sheet, scp 上传)**;
  单跑 ZMAX_VERIF_ONLY=F-xx; CLI tools/ss_feature_tests.py --list/--only/--skip-slow。
  ⚠️ ssfeat/sstest 带 source 字段 → on_node_activated 的 verif 分支必须在最顶部 (0.0),
  否则被数据源切换分支抢先拦截。
- 域: A引擎闭环7 (八阶段/收敛3.08mm/速度伺服0.211/台面/夹持/接触) B六层11
  C感知4 (YOLO 真检出3类 conf~0.95) D规划3 (离线规则) E元层5 (三域/潜空间PCA 2D@95%/
  流形) F画布4 (38节点10层/_EXTERNAL_LOC 35条/io_trace 14键=MODULE_ORDER)。
- 坑: 引擎 tr["u_sat"] 标量; 画布 io 键 "🛡 安全限幅"≠节点名"安全执行边界";
  行号映射随源码增行会漂 (F-F03 校验 ±3 行容错); YOLO 用例需 DISPLAY。

## ▶运行/单步/右键 执行语义 (2026-09-03 老倪: "运行状态空间后 detect_3d 没进" 根因)
- **▶ 运行 = 引擎仿真 + demo 播放, 不执行任何节点真实函数**:
  ① `_start_state_space_sim` (simulink_module.py) 只真执行名含"数据源"的节点;
  ② `StateSpaceSim.run()` 纯 numpy 引擎 (简化世界, 无 metaworld/无图像);
  ③ `_ss_tick` 播放每节点 `execute_node_logic(demo=True)` → `_demo_node_output` 只读
  DataWorld 帧数值展示 (v3.4.8 为防 YOLO/LLM 冷加载 1.6s+ 卡播放)。
- **⏭ 单步 / 右键"运行节点" = 真实执行**: `execute_node_logic(demo=False)` →
  node_ss_yolo → `_yolo_ensure_aligner`(best.pt + metaworld env) → `_yolo_capture` →
  `aligner.detect_3d` — 断点可进 (ZMAX_DEBUG_BREAK=YOLO 只停该节点)。
- **引擎 io_trace 曾写死伪装 (老倪红线)**: state_space_sim._io_snapshot 的
  "🎯 YOLO 目标检测" out 写死 "conf 0.99"、坐标抄仿真 peg/hole、hand 抄 peg → 总线/播放
  显示假检测。2026-09-03 已改 conf "--"(引擎无 YOLO 模型, 诚实标注) + hand=末端 self.x、
  peg=独立物体 self.peg (原误用末端当 peg)。
- **真实 YOLO 采样一次 (2026-09-03 落地)**: simulink `_real_yolo_sense_once()` —
  ▶运行/单步/右键同源, 引擎跑完对 ss_yolo 节点 execute_node_logic(demo=False) 一次:
  detect_3d 断点可进 + 真实 conf/3D 日志; `_demo_node_output` 对 ss_yolo 节点优先展示
  缓存真实值 "(真实YOLO采样)"。
- **⚠️ 勿把真实采样注入 io_trace**: 引擎是简化世界 (HOLE_POS y=0.462), 真实 detect_3d 是
  metaworld seed0 世界 (hole y=0.671) — 坐标不同源, 混进同帧自相矛盾。真实值留
  _YOLO_CACHE + 日志/演示展示, 引擎帧保持自洽。
- **YoloStateAligner.detect_3d 不带 conf**: node_logic `_yolo_detect2d` (同帧同预处理
  rot90+BGR 二次 predict) 补真实 conf/框, 存 `_YOLO_CACHE["det2d"]` (det3d 存 3D)。

## 🧮 标定层三域 + 潜空间节点 (2026-09-03 老倪: 潜空间=流形地图, 世界模型=导航仪)
- 标定层从引力/斥力二分 → **三域**: ATTRACTION(动作)/REPULSION(状态预测)/
  LATENT_CALIB(潜空间 — 世界模型预测流形): latent_dim=4(位置3+预测力1)/state_dim=39/
  manifold_kind=flat-linear/flow_kind=const-vel/force_ch/prior_A=1.0(latent_dim 改维=
  重构卡尔曼, 只标定+校验不写引擎字面量; prior_A 从斥力域迁入潜空间域, 引擎写回锚点
  PriorDynamicsPredictor(A= 单源不变)。
- 画布: 标定层 row_bg 更名「🧮 标定层 · 引力/斥力/潜空间」+ 新增「🧮 潜空间 · 世界模型
  流形标定」节点 (ss_lat, node_ss_lat): 真执行 — 引擎轨迹 39D 观测 PCA → 有效维@95%/99%
  (实测 2D@95%/4D@99%: 任务路径低维嵌入, 孔/姿态常量维无方差) + 潜坐标/速度场
  (prior−x̂₋) 取 tr 真实 latent_vec/prior_vec; 校验标定潜维 vs 引擎实际。双击/右键走
  标定面板/表格 (含潜空间组: 维度 spin/力通道 checkbox/prior_A)。
- 🐛 tr["u_sat"] 是**标量范数** (float) 不是向量 — node_ss_calib/面板取速度勿 [:3]
  索引 0-d 数组 ("too many indices", 既有 bug 被 try 吞, 09-03 已修)。
- 🧮 流形层 已更名 **流形导航层** (测地线地图视角): 流形=潜空间地图, 节点=地图导航读数。

## 🧮 流形导航层 (2026-09-03 老倪: 光模块精密插拔 = 低维流形上的运动; 回路外几何元层)
- 拓扑: state_space_obs.json 底部 y≈1040 「🧮 流形层」row_bg + 两 model 节点
  (ssmani_c 接触流形 x240 / ssmani_p 性能流形 x640), 无连线, 不进引擎 io_trace。
- 源码: src/lerobot/manifold/manifold_layer.py (与 calibration/ 同级) —
  ContactManifold (L51) / PerformanceManifold (L124); 常量 HOLE_POS/HOLE_MOUTH/
  PEG_HEAD_OFF 与 state_space_sim.py 逐字同源 (别改单边)。
- 数据真源: node_ss_mani 从 module._ss_tr 当前帧取 tr["x"/"peg_head"/"target"/
  "v_vec"/"stage"] (node_ss_calib 同款 idx=_ss_round); 无轨迹 → 提示先 ▶ 运行。
- 接触流形数学: e=T−hand (x 通道=e=peg_head−HOLE_POS); 通道轴按阶段 —
  下降/抓取/抬起=z 垂直, 插入=工艺斜线 AXIS_INSERT (孔口上方悬高 2cm→孔底,
  ≈(−0.957,0,−0.29)), 完成=孔轴 x; progress=‖e∥‖, risk=‖e⊥‖, V=½‖e‖², V̇=−e·v;
  状态=risk vs RISK_TH (下降/抓取 0.03=engine 抓握接触容差, 插入/完成 6/4mm)。
- 性能流形数学: δ=销头−孔底 → V_p=½δᵀWδ (W=diag(0.4,1,1), 横向重权),
  η=exp(−V_p/σ²) σ=0.004 (高斯光束近似 — 是模型非光功率计实测, 真机标定 W/σ)。
- 实测语义 (引擎 305 步): η 全程≈0 到完成段 0.57→0.77 (没插好光路不通);
  插入段起始带 ~10mm 工艺偏离被如实标红后收敛 (引擎 D_CONTACT=2cm 提前切插入)。
- 坑: engine stage 名带推进后缀 ("下降 · 接触") → _stage_name 清洗主阶段;
  接近/对位/转移=空中自由运动归 CHANNEL_FREE (误当 z 通道会全程误报离流形)。

## 🧠 右脑 WorldModel 蒸馏接入 (2026-09-06, commits 2283efbb + 74405273)
- 训练右脑 = RightBrainWM (modeling_left_right.py): obs39(raw)+act4(raw) → next_obs + contact
  (enc 2×256 MLP, **非 GRU** — parallel.py 注释"A≈GRU W_hh"是教学类比)。角色对应链路
  世界模型/先验 (dynamics.py PriorDynamicsPredictor), 不是卡尔曼估计器 (est 是估计器)。
- 导出: tools/export_ss_right_brain.py (ckpt→npz, 自动测定 pred_next 量纲=归一化空间
  需反归一化 *ss+sm, numpy vs torch 对照 MAE 5e-8); models/ss_right_brain.npz 不入库
  (同 ss_left_brain)。**坑**: state_space lerobot 训练只优化 left action loss, 右脑
  近随机 (contact acc 0.721 无区分度近0.519/远0.511) — 导出前必实测质量!
- 重训: tools/train_ss_right_brain.py — 引擎域数据 (ss_insert_lerobot, next=同ep下一帧,
  contact=手obs[0:3]-peg obs[7:10]<5cm 自建标签) → next 位置误差 0.1cm + contact acc
  1.000 (近1.00/远0.00)。**训完直接导出 npz (同结构)**; best.pt 在 outputs/rl_peg/。
- 接入: dynamics.contact_of(obs,act) (逐通道域检 4σ + wm contact; 域外 None) → 引擎
  contact_p = max(经验残差公式, 右脑真权重) — 抓取时机由训练模型主执行, 教学公式兜底。
- **实测否决 pred_next 位置先验主执行**: 引擎纯积分动力学线性先验即最优 (u→位移精确),
  右脑 1cm 级实时残差反而加噪 (残差 0.108 vs 0.0485, 状态机卡对位)。wm 位置先验能力
  保留 (predict obs=), 待真实物理/非积分动力学场景启用; real sim 布局漂移域外
  use_wm=False (同 accel 强制解析)。验证: 引擎 8 阶段 done 无回退, 残差复原 0.048。

## 🚀 L3 扩展: 插拔+AOI 闭环任务链 (2026-09-08, commit 74ffbb95)
- 状态机 8→13 段: ActionModulator.STAGES 尾部追加 拔出/AOI转移/AOI检测/回程/放下/完成
  (插入后按 mode 分流: "insert"=直接完成 (回归默认) / "full"=插→拔→AOI→回放闭环)。
  sim_real 用 mode 参数或 SS_MODE env; GUI 默认 insert (演示基线), full 待 GUI 开关接线。
- **AOI 工位 = 台面固定标定设备** (AOI_FOCUS 常量, 3D ss_dreamview 同源常量勿改单边):
  光模块头悬停镜头对焦点保持 25 帧 = 采图; 检测报告 = **真实过程指标代理** (不造假):
  插入残余深度最小 / 接触力峰 / 回抓次数 → PASS 阈值 (深度<8mm & 力峰<1.0 & 无回接近);
  _meta 带 aoi_focus/mode/aoi_report (3D 画设备/演示消费)。光学判定留真机 AOI 接口。
- **拔出两段式**: ①沿孔轴反方向水平拉出 (depth>pull_out_m 脱孔) ②垂直抬离孔口
  (pull_clear_h → 平移不刮盒); 与插入段①同款"引擎切目标, advance 等证据"模式。
- **放件流程**: 放下段 z_stall 触台 (z_stall 统计须含"放下"段! 只算下降/抓取会永不触发
  — 09-08 实锤) → _drop_ready 开爪指令覆盖 → 观测爪开 → placed → 完成。
- 🐛 已踩: AOI转移 判据曾用"到对焦点距离<2cm"但目标是**悬停点** (focus+0.08) → 永远
  等不到卡死; 判据目标必须与 _stage_target 目标同点 (引擎几何到位事件驱动更稳)。
- 夹持回退范围 RETREAT_LO..HI = 4..10 (排除「放下」: 放件主动开爪非滑脱)。
- 画布: DiT(ssdec) y-610 回 L3 行 (v5.2.0 设计位); VLM→DiT 主输入 in1 (潜空间 z,
  接触流形让位 in3, 性能流形 in2); DiT 双下行通路 lkdc_ff→ssff (前馈=肌肉记忆固化点)
  + lkdc_act→ssact (执行端直通)。node_logic: VLM 识别 AOI 设备/报告 + DiT 双通路
  教学标注, 真实权重推理接入点 = smolvla_lew 容器/远程 (模型引擎三模式)。
- 实测: R0 mode=full seed101-104 全链闭环 4/4 (872-989 步), AOI PASS 深度 5.3-5.9mm;
  insert seed104 343 步零回归。R1 视觉 full 未验 (每步 YOLO ~1s, GUI 演示时跑)。

## 🧩 VEH.5.041 统一状态空间 = SU(2) 二阶特殊酉群 (2026-09-20 老倪升级)

**旧口径作废**: 该节点源码曾是 `perception.fuse_sensors()`(传感器融合拼接 43D) —— 老倪指出
"这是传感器融合, 不是统一状态"。统一状态空间是**群**: `SU(2) = {U∈C²ˣ²: U†U=I, det U=1}
= exp(−i·ω·σ/2)`, 全部层/全部节点数据都映进这个群, 在群里观察并理解整个场景。

- 内核: `src/lerobot/policies/left_right/state_space/su2.py`
  - `SU2Element`: 哈密顿积(群乘)/逆元/`from_rotvec`(exp)/`log`(主值分支, exp∘log 精确可逆)/
    `bloch()`(‖r‖≡1 — 群元素↔纯态, 全在 Bloch 球面 S²)/`theta()`/`visibility()`=|w|=收敛度/
    `distance_fs`/`commutator_norm`;  参数化 `U = w·I − i(x σx + y σy + z σz)`, (w,x,y,z) 单位四元数
  - **有界映射律** `ω = π·tanh(g·‖v‖)·v̂`: 任意实向量 → su(2); θ<π 永不绕圈(否则 θ 3.14 与 0 混在
    一起 = 假收敛), 方向保留, ‖v‖→0 ⇔ U→I(场景收敛)。别用 ω=g·v(会绕圈)。增益 L2=2.0/L3=3.0/L4=1.0
  - 层: L2=43D 几何误差(光模块头−孔位) / L3=流形规划(progress,dperp,rem) / L4=安全动作(u_sat,
    contact_p,1−η) / L5=大模型意图(**未接入 → 单位元, 不编造**);  `U_scene = U_L2⊗U_L3⊗U_L4⊗U_L5`
    (群不可交换 = 层序敏感), `peel_layers` 逐层左乘逆元读贡献, 全剥离残余应≈0(分解自洽)
  - 节点级全面映射 `NODE_SPECS`(17 节点): 每个节点的 io_trace 真实 out 按语义规则取向量
    (vec/slice/diff/chans/obserr; 字符串里的数值用正则提); 本帧无数值输出者 → 单位元 + 标注
- 画布: `flows/state_space_obs.json` 节点 ssobs 改名「🧩 SU(2) 统一状态空间 (二阶特殊酉群)」,
  params 带 `su2_unified_state/group/map_law/blocks/observables/viz_tools`; 43D 拼接语义归 📡传感器融合
- node_logic: `_EXTERNAL_LOC["ss_obs"]` → su2.py `class SU2UnifiedState`(右键显示群代码);
  执行函数 `node_ss_su2`(真跑 su2.py, 读 `module._ss_tr` 当前帧, 写 `_SS_STATE["su2_*"]`)
- 观测面板: `tools/gui/su2_dialog.py` — 双击节点打开(simulink `_open_su2_panel`, 分发分支
  `params.su2_unified_state` **必须在 source 分支前**, 否则被"数据源切换"抢先); 5 视图 = Bloch 球
  (QPainter 拖动旋转/滚轮缩放) · 层贡献+反演 · 层间不可交换与 FS 距离热力矩阵 · 节点映射 · 阶段轨迹;
  按钮含"可视化工具统一入口"(波形/3D/直方图/归因/视频/输入图像 → `_open_viz_node`)
- 验证/图: `tools/ss_su2_verify.py`(群公理 + 真实引擎 369 步 → `reports/su2_state_report.json`),
  `tools/plot_su2_state.py` → `reports/su2_bloch|converge|layers|node_map.png`
- 实测(引擎 接近→完成): θ_total 2.86→0.98, |w| 0.14→0.88(向恒等元收敛); 剥离残余 ≤3e-8;
  层间不可交换 L2|L4=0.587(最强); 群公理 封闭/酉/det/结合/单位/逆/exp-log/Bloch 全 ≤1e-15

**踩过的坑**
1. **数组进布尔上下文**: `float(frame.get(k) or 0.0)` 遇 ndarray → "truth value of an array is
   ambiguous" → 用 `_scalar()` 兜底(ndarray/0-d/None 全安全); `obs43_geometry` 兼容 (1,43)/列表。
2. **FakeMod 必须显式 `_trace_nodes = False`** — `__getattr__` 返回 lambda(truthy) 会让
   `execute_node_logic` 走 `_trace_exec` 逐行执行 → 节点"失败且无日志"的假象(排查浪费最久)。
3. **画布加载会重映射 node id**(id_map): 断言/查找一律按**节点名**, 不能按 json id。
4. **同一关键词只能注册一次**: `_reg("ss_su2",…)` 与 `_reg("ss_obs",…)` 关键词相同 → match_node
   歧义(返回 ss_su2 而 _EXTERNAL_LOC/画布 id 是 ss_obs) → 只保留 ss_obs 一条。
5. **工程库里的「功能」要落回画布节点, 必须两步 join**: `config_meta.json` 的每个功能带 `module_ref`(节点**显示名**)
   与 `row_name`(行背景节点名 —— 实测只 15 条 row_bg)。`module_ref` → 按 name 建的反查表 → node id。
   直接拿 `module_ref` 当 id 查字典 **全 miss 且不报错**; 拿 `row_name` 当功能则命中行背景 ⇒ 报「该功能不属于任何任务」。
   静默失配的后果不是异常而是**下游聚合整表落到同一个桶**(按优先级/按任务计数看着像业务结论)。
   定式: **join 完先断言命中数 == 期望总数**(实测 74/74), 每个任务侧再核一次(要素数 == 启用节点数,
   实测 51/42/51/51/51/51/31 逐任务相等) —— 再相信任何下游统计。
6. **任务 × 节点是「子集」不是「映射」**: 实测 7 个任务的启用节点都是**同一个 51 节点集**的子集, **无任务专属节点** ⇒
   功能/参数为全工程共用, 任务之间只差配置(`overrides` 参数覆盖 + `applies_segments` 配方段 + `run_cfg` 执行开关)。
   所以不能按「某任务独有功能」给它排期: 先看优先任务启用的并集是否等于全量启用集(实测摆盘∪插拔 = 51 = 全量),
   是就只能把它们需要的那批**整体压在时间窗前段**、后段留收口。
5. `data/` 与 `reports/*.png` 被 .gitignore → 映射表 `data/su2_mapping.json` 是**本地生成**
   (`load_mapping` 缺文件回退内置 DEFAULT_MAPPING, 不阻塞), 图不入库。
6. 扩展新层/新节点映射: 改 `NODE_SPECS`/`encode_layer` 即可(数据驱动), 不用碰画布 JSON。
7. **「YOLO 输出怎么进统一状态空间」= 三条真入口 + 一条断链, 必须分开答** (别用一句"检测进了 obs"糊过去):
   ①**画布 L2 块** `encode_obs43`(su2.py:272) 吃 43D, e = 光模块头(`[4:7]`, z+0.030) − 孔位(`[36:39]`);
   而画布 sim 的 43D 来自 `_ss_ensure_obs43`(library.py:2642) = metaworld `env._get_obs()` + 合成触觉 4D
   ⇒ **吃 env 真值, YOLO 不在其中**。
   ②**真机/AR 链** `ss_station_engine.obs43`(`[4:7]`=检测坐标 `ST["perc"].xyz`) →
   `ManifoldEngine(manifold_type="su2").project()` 取潜向量 `z[:3]` → `from_rotvec`(manifold_engine.py:309-318)
   ⇒ YOLO 真在环里, 但口径是"观测→潜空间", 与①的几何误差**不是同一把尺子**, 两条分开报。
   ③**节点级** `encode_nodes`/`NODE_SPECS`: 该节点 spec 仍按旧标签 `"peg 检测框"/"hole 检测框"` 取数, 而节点现在只发
   vision_points 契约(`points → 光模块·当前/hole`) ⇒ `node_vector` 取空 → **每帧映射成单位元**, 只在
   `detail["no_numeric_output"]` 留一行(静默失败)。判据: 拿 `zmax_data/ss_live/vision_points.json` 当帧喂
   `su2.encode_nodes`, θ 必须 ≠0; θ=0 且该节点在 `no_numeric_output` 里 = 这条映射没接上。
   ④`aligner.align()` 产出的 `_YOLO_CACHE["aligned39"]` 全仓库只有写没有读 ⇒ **不许**拿它当"检测已进 43D"的证据。
   回答前按这四分对号; 完整入口图/探针命令/两种接法见 `references/yolo-to-su2-entry-map.md`。

## 🔌 引擎 L4 注入开关盘点 (2026-09-24 血教训: A/B 前先核对链上开关默认值)

`tools/gui/state_space_sim_real.py` 的 L4 注入链上有**一串默认关**的开关; 不核对就会把"上游没开"
误判成"模型无效" (2026-09-24 实例: 因为 `SS_L4_ALIGN` 默认关, 把"注入被闸死"写成了"新 LoRA inert"):

| 开关 | 默认 | 作用 | 不设的后果 |
|---|---|---|---|
| `SS_L4_INTACT=1` | 关 | L4 直驱接入 (decoder 量纲逆运算 act×K_ACT) | 完全没有 L4 注入 |
| `SS_L4_ALIGN=1` | **关** | 施加对齐层 `models/l4_align_map.json` (锥角 cos≥`SS_L4_ALIGN_COS_MIN`(0.9) + 幅度封顶 ≤`SS_L4_ALIGN_RATIO_MAX`(1.2)×L2) | 原始提案 cos 中位 **−0.605** / 幅度比中位 **5.8×** → 被 L2 收口闸逐帧否决 (实测 0/90 通过) |
| `SS_L4_INTACT_GATE=1` | 开 | L2 收口闸 (cos<0 或幅度>1.5× 否决) | 上层越界提案直接进执行 |
| `SS_L4_INTENT_LINE=1` + `_W` | 关 | 直连线注入 (另一条注入通路) | 只有直驱一条通路 |
| `SS_INTACT=1` | 关 | 标定映射接入 (需 `models/intact_action_map.json`, R² 负 → 全拒) | 用 SS_L4_INTACT 那条 |
| `ZMAX_SKILL_FF=1` | 关 | 走技能口分支 (u_ff 过原子技能) 并**每拍落 `zmax_data/ss_live/skill_gate.json`** | 闸文件永远停在旧时刻, 读它的 `moveit_plan_req.py --auto` 只能退回示教点(不报错) |

⚠️ 这两条一起才叫“引擎在发闸”: ① env 开关 ② L4 帧源 `fw_render_server`(8799 `/frame.png`) 在跑。
帧源不在 ⇒ 引擎每拍 `safe_stop`、`‖a‖=0`, 日志照打 (看着正常), 但**闸文件不更新**。
联调顺序: 先起帧源 `tools/fw_render_server.py --port 8799 --hz 2` → 带 `ZMAX_SKILL_FF=1` 重启引擎 → 回读闸文件帧龄 <1s。

**实测 (2026-09-24, 在役 `intact_l4_current`, 90 步 direct 臂)**:
`SS_L4_ALIGN=1` ⇒ 闸门 **90/90 全过** · cos 中位 −0.605→**0.963** · 幅度比 0.86 (0 帧超标) · blend **90/90** (原 0)。
闭环 A/B 同口径 3 seed × 4 臂: **消除回退** (seed1 direct 13.6mm→27.7mm, 与解析链 30.9 同级) 但
**未证明提升** (成功数与解析链同 1/3) ⇒ 不切在役指针/不进默认档。报告 `docs/5-玉衡-指标验收/lora_align_ab_20260924.md`;
复现 `tools/diag_lora_du.py`(带闸门内部量输出) + `tools/ab_intent_line_closedloop.py`。

**判据纪律**: 任何"注入无效/零影响"的结论, 先用 `tools/diag_lora_du.py` 打**逐级计数**
(本帧提案 → 闸门 pass/方向否决/幅值否决 → blend → u_ff 逐位比对) 再下结论。

## 📤 「L4 层的输出是什么数据」— 四个出口，形状全不同，先分清是哪一个

同一套系统里有四处都叫「L4 输出」，维度/语义/是否生效都不一样。只报一组数字（尤其只看到 6 个数）
就是最常见的误读 —— 实测回答一次这个问题要翻 4 个文件，所以列在这里。

| 出口 | 形状 | 语义 | 生效条件 |
|---|---|---|---|
| 引擎 `IntactIntentDecoder.decode()` → **`u_ff`** | **(4,)** | 引擎 u 空间先验：`u[:3]=clip(act[:3],±1)×K_ACT(0.5)` **m/s**；`u[3]=±1` 夹爪（原值 >0.5 判关） | `SS_L4_INTACT=1`；量纲逆运算，**不需标定** |
| 同上 `l3_cond` | (6,) | 给 L3 的条件向量 | 需 `models/intact_l3_map.json`；未标定 ⇒ 拒绝+计数，不写死映射 |
| 同上 `l4_cond` / `m_int` | (N,) | δ=z_goal−z_t 的**单位向量**；`m_int` 是给流形专家预测器的**意图**（不是动作） | 无需标定；`m_int_weight=w` 门控，意图退化 ⇒ 0 |
| `_l4_dit_action()` | (4,) | **metaworld 动作**（真动作） | `SS_L4_DIT_BETA` 那条路，默认不在生效链 |
| `ss_local_infer_server` `POST /infer` | (6,) + yaw(2) | **流形量 `[progress, risk, V, eta, rem, dperp]`**（逐维容差 `TOL=[0.03,0.01,0.01,0.05,0.015,0.015]`）+ `dz` 抓深增量 mm / `ok` | 看返回里的 **`input_map`**：`placeholder_v0` ⇒ 模型在前向但**喂的是占位输入**，输出不能当动作 |

硬规矩：
- 🔴 **`u_ff` 是 4 维，不是 6 维**。看到「6 个数」先区分：是流形量（进度/风险/势/η/剩余/垂直偏离）
  还是服务侧动作；关节角/位姿都不在这个数里。
- 回答这类问题必须同时给 **维度 · 语义 · 单位 · 是否在生效路径** 四项。缺「是否生效」
  就会把占位输出说成真实输出（老倪红线里「假接入」的一种）。
- 探现役值：`curl -s -X POST http://127.0.0.1:8790/infer -H 'Content-Type: application/json' -d '{}'`，
  **把返回的 `input_map` 一起报出来** —— 服务自己写着 `placeholder_v0`，不伪装成标定完成。
- `u_ff` 之后还要过 L2 收口闸与调制器，所以「L4 输出」≠「实际下发动作」；实际下发看 `u_exec/u_sat`。

## 🧬 模型进引擎的**只读旁路**挂点 + 口径 (2026-09-24 实测, 换靶子前必读)

工具 `tools/moe_engine_bypass.py --model {moe,dense}` (同一套框架跑两模型, 同口径可比)。

- **挂点**: 引擎 `run()` 里唯一每步一调的物理推进点是 `env.step(act)` (行 ~2637) →
  直接 `sim.env.step = hooked` 包一层。计数必须 `== 步数` (实测 52,212 帧 / 0 失败),
  这是"每帧真调"最硬的证据; 别用 `_io_snapshot`/每 5 步的 `ss_publish_metrics` (那是节流点)。
- **口径逐项 (对不上就是白测)**:
  | 输入 | 引擎侧取法 | 训练侧同源 |
  |---|---|---|
  | obs 39D | `sim._obs39()` == `env._get_obs()[:39]` | h5 `observation` (8715,39) **同源同义** |
  | px | `sim._render_frame()` → 224×224 INTER_AREA | 采集像素即 224×224 uint8 |
  | px 归一化 MOE | `float/255` → CHW, **无** mean/std | `stage_moe_backbone` 训练侧 |
  | px 归一化 dense | `to_img()` = `/255` + `(x-0.5)/0.5` | `joint_unified_backbone` 训练侧 |
  | mem 13D | `zeros(13)` | 训练侧就是 `torch.zeros(B,13)` |
  ⚠ `tr["obs"]` 是 **43D** (`perception.fuse_sensors`) 不是 39D —— 想比 39D 必须 `[:, :39]`。
- **零回退实证法**: 同 seed 跑两次 (挂钩 / 不挂钩) → `dist` 序列 `np.array_equal` 逐位相同才算只读
  (实测 10/10 seed, 最大差 0.0mm)。冷记忆隔离 `SS_MUSCLE_PATH=/tmp/...` 否则热记忆让同 seed 漂移。

### 🎯 结论: 认知头"预测下一帧观测"= 靶子定错 (2026-09-24, 两模型同证)

| 口径 | 持久基线 | MOE | dense |
|---|---|---|---|
| 同源留出 (v6 2000 样本) | **0.002972** | 0.009894 (3.33×差) | 0.015417 (5.19×差) |
| 引擎流 (52,212 帧) | **0.00042** | 0.01214 (29×差) | 0.01665 (40×差) |

机理: 引擎每步 `|Δobs|` 均值 **0.000298** vs 采集集 **0.002966** (≈10×) → 两边"预测下一帧"难度不同源,
持久基线在引擎上天然近乎完美。⇒ **不接管**; 改法是换靶子 (多步 K=5/10 或事件级: 接触/阶段切换/残余插深),
且**一律带持久基线+平凡基线同表**。与 09-06 右脑 world model "一步预测打不过纯积分先验"同一条教训。

## 🧮 流形引擎 (Manifold Engine) — L4 核心内核 (2026-09-24 老倪架构升级)

**定义**: 高维状态空间 → 低维流形, 在流形上做 表征/投影/度量/测地线导航/梯度流/有界反馈。

- 源码 `src/lerobot/manifold/manifold_engine.py::ManifoldEngine`; 画布节点 `ss_mani_eng`
  (x=7500 y=1546, L4 专家自主功能行 **前向输入前沿 4690 与输出前沿 10016 之间**);
  三件套 = `_reg("ss_mani_eng")` + `node_ss_mani_eng`(读 `module._ss_tr` 当前帧真跑) + `_EXTERNAL_LOC`
  + 能力清单 `capability_levels.py::L4-C15`。
- 复用既有真件 (别重写!): `su2.py`(群) · `manifold/lie_intent.py`(SO3/SE3 四元数) ·
  `manifold/manifold_layer.py`(接触/性能势能 Φ) · `manifold/fiber_bundle.py`(丛提升)。
- 流形注册表 **9 种 = 7 ready + 2 planned**: ready(euclidean/sphere/torus/so3/se3/su2/latent_flat);
  planned(calabi_yau 缺 Ricci-flat 度量 / hyperbolic 缺图卡) → `project()` 对 planned **拒答**,
  只返回 status/confidence=0, **不造数** (这是本仓库的红线, 新流形没实现就别标 ready)。
- 实测 (真跑引擎 160 步, `tools/manifold_engine_bench.py`): 端到端 **0.056ms/帧** · 投影 0.019ms ·
  测地线T=16 0.24ms · 上限 ~3500Hz · **约束违例 1.1e-16** · Φ 0.96→0 (向收敛态)。
- 踩过的 5 个真 bug (都写进自检): ①潜维不足 SO(3) 静默退化成单位阵 (改补齐+标注 `latent_padded`)
  ②SE(3) 12 维点 (R9+t3) 被当 9 维 reshape → 必须 `[:9]` ③"残差"要拆成 **约束违例**(验投影器, ≈0)
  与 **投影改动量**(‖p−z‖, 做置信/异常) ④反馈残差维数 ≠ 切空间维数时必须显式对齐(截断/补零+标注)
  ⑤无界岭回归解码器**外推发散**(预测幅值 3.05 vs 真值 1.0, 全段 R² +0.561→−3.55) → 必须用训练数据的
  动作界做**硬限幅**, 并**分段报 R²**(训练段/未见段) + 逐维相关, 别只报一个聚合 R²。
- 画布接入脚本 `tools/canvas_add_manifold_engine.py`: 6 条硬断言 (居中/最大空档/零重叠/全前向/幂等/行带内),
  新增"核心内核类"节点照这个模板改 X/Y 即可。

### 🧮 主标定参数 M —— 流形引擎向标定层暴露的**唯一**结构参数 (v5.16.4)
- 口径(老倪定调): 流形引擎 = 整个工程的核心结构 ⇒ 它向标定层暴露一个主标定参数 **M**(类比发动机标定的质量), **M 是系统最主要的参数**。
  物理: 等效惯量 `a=F/M ⇒ Δx=F·dt²/M`; 信息论: 交叉熵 H(p,q) 的"单位换算/曲率尺度"(Fisher/Hessian 尺度的单标量代理)。
  **M 由流形结构导出, 不是拟合出来的自由参数** — 结构决定可能性, 质量是果不是因。
  过阻尼含义: `M→0` = 现在的一阶 GD(速度∝力, 感觉不到惯性); `M>0` ⇒ 状态带**动量** ⇒ 过渡更平滑、抑制突变。
- 落点: 引擎 `src/lerobot/manifold/manifold_engine.py`(MANIFOLD_M_DEFAULT/RANGE/UNIT + `set_M()` + 有惯性二阶分支)
  · 真源 `config/calib/zmax_manifold.json` → `tools/zmax_params.py --check | --m <v> [--inertia on|off]`
  · 标定层新域 `calibration_layer.MANIFOLD_CALIB`
  · 画布新节点 `n_calib_mani`「🧮 流形引擎标定 · 主参数 M」+ 5 条前向连线(sscalib/sslat → 本节点 → ss_mani_eng/ssmani_c/ssmani_exp)。
- **零回归红线**: 默认 `M=1.0 · inertia=false` 必须与旧一阶过阻尼**逐位相同**; 判据 = 引擎内建 selftest(M=0/关 ⇒ 与旧轨迹相等)
  + `tools/manifold_M_experiment.py`(同场同起点: 关与 M=0 逐位相同; M=1 时反转 −F 后**仍沿原方向前进** ⇒ 动量可观测)。
- 画布节点改动后**须重启控制台才可见**; 若重启前有人在画布上点了「保存」, 内存旧版可能覆盖磁盘 ⇒ 重跑 `tools/canvas_add_manifold_calib.py --apply`(幂等+六断言+自动备份)。

### 🔷 主参数 M 升级为**张量** = 度量张量 g_ij(x) = M·G_ij(x) (det G = 1)
- 老倪定调: 主参数是一个**张量** —— 随状态变化的度量张量 g_ij(x), 大小 n×n, 独立分量 n(n+1)/2;
  梯度/联络/曲率/测地线**全由它导出**。
- **必须按尺度×形状分解** `g = M·G (det G = 1)`: **M 仍是那个现场单标量**(范围 [0,8]; 各向同性 ⇒ Γ=0 ⇒
  `a = F/M` 逐字零回归), **G 是形状**(各向异性 + 随状态变化)。
- 为什么非分不可: **Γ 对度量的整体尺度不变** ⇒ 弯曲只由形状决定 ⇒ 尺度与形状**可分开标定**, 互不污染;
  不分离就会「标 M 的时候曲率跟着动」, 现场根本标不动。
- 真源实现 `src/lerobot/manifold/metric_field.py`(∇Φ=g⁻¹∂Φ 用 Cholesky 解 · Γ 中心差分 · R^i_jkl+Ric ·
  测地线半步辛积分; n>8 的曲率如实降为 3 维子空间抽样)。参数化 `isotropic / diag / full`(n(n+1)/2 独立分量:
  3→6 · 6→21 · 16→136 · 43→946) + 可选状态相关项 `G(x)=G₀+Σx_k G_k`。
- 标定接口 `tools/zmax_params.py::manifold_metric()/write_manifold_metric()`; 真源 `config/calib/zmax_manifold.json`
  的 `metric` 段; 画布节点「标定诊断测量 · 主参数 M」运行即打印 dim/mode/独立分量/正定性/‖Γ‖/‖R‖/测地线偏离。
- 判据 `tools/verify_metric_main_param.py`(7 组: 独立分量数 · 正定+det G=1 · 零回归 · 解析 Γ 张量对照 ·
  常度量 ‖R‖=0 / 弯曲 ‖R‖>0 · 配置真源读写+非正定拒写 · 真跑节点报数) ✅ 23/23 PASS。
- 公式/解析对照值/两个数值坑见 `references/metric-tensor-main-param.md`。

### 📊 健康度 H 与**尺度分离** (分级口径红线)
- `g = M·G` ⇒ 特征值 λ = M·λ̃, 而 **κ = λmax/λmin 与 anisotropy 对整体尺度不变** ⇒
  **H = (1/κ)·λ_min = M·H̃** (H̃ = (1/κ)·λ̃_min 才是尺度不变的几何健康度)。
- 🔴 **分级/阈值一律落在 H̃, 不许落在 H**: 同一套形状 M=3.643 ⇒ H=0.557/H̃=0.153(良好); M=4.423 ⇒ H=4.423/H̃=1.0(优秀)
  —— 拿 H 分级会把"物理尺度变大"读成"几何变好"。对外报数 **H 与 H̃ 两个都给**。
- 口径唯一实现 `src/lerobot/manifold/health.py`(`health_from_metric(g)`/`health_from_eigvals` → H/κ/λmin/λmax/
anisotropy/status/trend); 阈值真源 `config/calib/zmax_health.json`(现场可标定) —— 别在调用处复制阈值常量。

### 🔁 闭环引擎 · 配置单→M 映射 · 集成总线 (落点分工)
- 分工: **「标定诊断测量 · 主参数 M」节点 = 配置单→M 的映射关系** · **「流形引擎」节点 = 用 M 实现功能**。
- `tools/config_to_M.py`: 显式规则表 R1 dim / R2 mode / R3 diag·components / R4 gain(待标定) / R5 scale=M(能量标定),
  每条带来源依据; 幂等以 **`m_audit_sha`** 为准(不是文件 sha —— `_updated_at` 每次都变)。
- `src/lerobot/manifold/engine_loop.py`: 度量 → H → 动力 τ=‖g⁻¹F‖ → L5(路径/系统边界/规划) → L4(认知+监督否决)
  → L3(调度) → L2(原子技能+肌肉记忆+快速反馈) → 记忆上行 L2→L3→L4→L5 → **L5 汇总回写**(调 L4/L3 增益 + 补偿 L2)。
- 集成接口 = AOI/AR 总线: `tools/engine_bus_publish.py` 把引擎信号(含 H̃)**并进 `tools/ar_aoi_bus.py` 的同一 live 文件**, 写完回读。
- 判据: `verify_engine_loop.py`(闭环完整性) · `verify_config_to_M.py`(映射/闸门/幂等) · `sil_test_engine.py`(SIL 真 trace 重放)。
- 深度(尺度分离推导/映射规则表/SIL 数字/写盘与判据两坑)见 `references/metric-tensor-main-param.md` §8–§12。
- 🔴 **映射存在 ≠ 已落役**: `tools/config_to_M.py --task <T>` 算出的是**提案**(实测摆盘 M=4.423 · dim6 · isotropic),
  而真源 `config/calib/zmax_manifold.json` 是**在役值**(实测 M=3.283 · dim3 · full) —— 两者不一致时只能报
  "映射链在、**未落役**", 绝不说"已映射/已生效"。节点侧判据 `verify_metric_main_param.py` 23/23 PASS
  **只证明映射本身对**, 不证明作业链在用这个 M。核口径 = 真源 JSON 的 `M/dim/mode` 与 `config_to_M` 输出**逐项对照**。
- 驱动扭矩 topic: `ss_torque = M·(−∇Φ)` 由 `tools/tdrive_bus.py` 发布, 落**系统服务常驻**(`zmax-torque-bus.service`,
  10Hz; 写 `zmax_data/ss_live/torque_live.json` + `torque_<场景>.jsonl` tap)。🔴 **发布器里的场景必须现取**
  (跟 `ss_scene_switch` 的活跃场景), **不许写死 `SCN-xx`** —— 写死会让 tap 文件名与场景标签长期指错任务
  (实测手跑 120s、published/errors 全对, 却整份写进了另一个场景的 jsonl)。改完重启服务并**回读 tap 的场景字段**。
  判据口径: 逐项 PASS 里**只有依赖真录像/真相机源的那几条**在办公模式必然未过 ⇒ 如实标"待现场复跑", 不算回归。

## 🎛 GUI 安全启停 (2026-09-24 血案)

- **别用 `pkill -f studio.py` / `ps|grep studio.py`**: 你的命令行里含 "studio.py" 字样 → **匹配到自己 → 自杀**
  (实测 SIGTERM -15 中断整条命令)。用 `bash tools/studio_ctl.sh {status|stop|start|restart}` (按 /proc cmdline
  精确匹配, 判断逻辑在脚本文件里所以不会自杀)。
- **venv 在仓库根**: `/home/ubuntu/lerobot-smolvla-lew/gui-venv311/bin/python` (launch_studio.sh 硬编码),
  **不在** `tools/gui/` 下 → 按 tools/gui 路径匹配会永远报 "stopped" (假阴性, 实测踩到)。
- 启动脚本用 `nice` 包一层, 所以 **argv[1] ≠ 解释器**; 匹配要"任一段是解释器 且 任一段是 studio.py"。
- 改 `node_logic.py` / 画布 JSON 后: 先 `studio_ctl.sh stop` → 改 → `studio_ctl.sh start`;
  GUI 存活核验 `xdotool getwindowgeometry $(xdotool search --onlyvisible --name "XSpace Studio"|head -1)`。
- **同一份 live JSON 的发布器只许 1 个实例**: 两个 `ss_skill_dispatch` 同时在写 `skill_phys.json`, 老实例会把新实例
  刚加的字段覆盖没 (实测 a/b/c 周期性消失, 误判成"代码没生效")。重启脚本两件事必须同时做:
  ① 杀进程只认 `cat /proc/<pid>/comm` 以 `python` 开头 —— 宽泛 `pgrep -f <脚本名>` 会命中**自己的 bash 包装**
  (命令行里就有那个字符串) 把自己 SIGTERM 掉, 实测连杀两次; ② 起完回读实例数必须 == 1。

## 🐞 「断点打不进」的真相 = 分层生效, 不是 bug (2026-09-29 老倪现场: 跑L5时 move_pose 进不了断点)
- **画布 L5 档不下发真机动作**: `node_l5_loop`(src/lerobot/engineering/nodes/library.py:4643) 只读状态+触发 VLM 标注→训练; 节点 `n_moveit`(同文件 2990-2999) 只 `precheck()` + `MoveItPlan.plan(...)`, **一行 move_pose 都没有** ⇒ 断在 `arm_control.ArmController.move_pose`(src/lerobot/arm/arm_control.py:165) 永远不命中。上层只给意图/条件、执行由 L2 收口 —— 看到这现象先想"分层对", 别去改画布节点代码。
- **真机下发是另一个常驻进程**: GUI/CLI → `~/zmax_data/l2_cmd.fifo` → `tools/l2_daemon.py`(独立 pid) → `ros2 service call /move_pose|/move_line|/gripper_driver`(l2_daemon.py 325/518/916)。断点要 **attach 到 daemon 的 pid**(VSCode: Attach using Process ID), 不是另起的调试会话; 断在真实执行器里会暂停下发, 现场臂动着时别停太久。
- **别为了看下发去改 daemon**: `l2_daemon.py:79 maybe_reload(reg)` 会热加载 ⇒ 现场改码可能 reload。用只读镜像 `tools/l2_dispatch_watch.py`(tail l2_daemon.log → reports/l2_dispatch.jsonl, 分清 DRY-RUN/真发) 代替断点。
- **契约式退出码 ≠ 崩溃**: `raise SystemExit(main())` 得 1/2 = 工具按判据拒绝(VSCode 报成 "Exception has occurred: SystemExit")。真原因打在 traceback **上面**; 判断他跑了哪个模式看产物 mtime, 不要猜。
- **L5 槽位工具 0 框退出码**: `tools/l5_slot_tool.py --build-dataset` 默认只收 `status=已记录`; VLM 复核不一致 / 无 TCP 真值 / 深度未上线 → 一律停 `待确认` ⇒ 0 框 ⇒ exit 1(不是崩)。跑通管线用 `--include-pending`(仅供冒烟, 报告标注); 要真标签必须现场 `--record --slot N`(判据: 投影 ok + TCP≤3s + VLM 一致)。
- 现场拖动时的实时叠加三件套见 `sim-real-scene-overlay`: 50Hz 录制真关节+TCP(`tools/live_motion_recorder.py`) · 停顿点自动打点+实测轨迹层(`live_pause_marker.py`, origin=`trace` 黄) · 同源规划段(`live_plan_segment.py`, 两端真机真值, 按执行器守卫 ≤50mm/下降≤20mm/≤10°分段)。
- **断在具体某一召却不停 (上条的镜像)**: 三因按序分离 —— ①方法被**实例属性覆盖** (`self.accel.forward = analytic_forward`，门是 `SS_USE_MLP`) ②跑这段的是**另一个常驻进程** (引擎 loop 无 pydevd) ③模块是 `spec_from_file_location` 动态加载、**不进 `sys.modules`** ⇒ debugpy 解析不到。修法与自证见 `references/breakpoint-and-realization-notes.md` 末节 (含断点友好加载器、`真身执行 #N` 执行证据、`SS_FF_BREAK=1` 硬停)。

## 三级能力测试(L2/L3/L4)运行口径 (2026-09-29 实测)

```bash
xvfb-run -a ./gui-venv311/bin/python tools/ss_level_tests.py [--level L2|L3|L4]
```

- **必须 `xvfb-run`**: 不加会出现假失败(`无 DISPLAY 无法渲染真实帧` + `ModuleNotFoundError: No module named 'tools.gui'`); 加上即全过。
- 🔴 **现场机上不跑 L2/L4**: L2 里有**碰真机**的用例(`t_sssensor_real` / `t_sobs_realalign` 等 `t_*_real` 一族),
  在有人作业的现场跑会动真机、可能引发控制器报警(实测过一次)。现场要验回归只用离屏/离线手段,
  或先确认无人在场、臂处于安全位姿再跑; 要真机证据时单跑指定用例并提前告知现场。
- **节点逻辑迁 `src/lerobot/engineering/` 后验证层会假失败**: 审计/映射仍指旧壳 `tools/gui/node_logic.py`(已不含逻辑)。
  · `verification_layer._audit()` 用 `_MIGRATED_SRC` 同时扫【旧壳 ∪ 新真源】, 命中任一即过。
  · `_EXTERNAL_LOC` 行号随真源漂移, 须按真源实测校正: n_web_agent 1→93 · n_hil 1→157 · ss_test 111→123 · ssa/ssb/ssc 3900→3533 · ss_lat 58→55 · ss_moe 42→50 · ss_mani_eng 395→403。
- **L4 `t_sched_real` 必须放在子进程里跑**(已改, 否则套件内假失败): 它调 `lerobot.engine.runtime.quick_run(n_episodes=2, vision=False)`(真身; `tools/gui/state_space_sim_real.py`
  已是 27 行别名 shim, 老 import 路径照旧可用), 判据 **2 集 ≥1 完成**。
  同进程内跑过前面一堆用例后两集都折在 1000 步(❌ 0/2); **单独子进程跑 = 1/2 ✓**(完成那集只 395 步、夹持=True)。
  静机复跑仍然 ❌ ⇒ **不是资源竞争, 是同进程状态污染的顺序敏感性**。
  定式: `subprocess.run(["xvfb-run","-a",sys.executable,"-c",<跑 quick_run 并 print N_OK=>], cwd=REPO_ROOT, timeout=900)`,
  解析 `N_OK=` 判 ≥1 ⇒ 既保留"真跑/真渲染/env.step"的强度, 又消掉顺序敏感性(改后 L4 178/178 全过)。
  同类启示: 任何**带真环境/真渲染的合成断言**都优先子进程隔离, 别在同一个长套件里前后串着跑。

## 📊 数据空间 Trace ↔ 信号分析: 同源/固定行/归属/位姿 (2026-10-17)

两窗口 (`dds_canoe.py` / `canoe_graphic.py`) 用户会拿任意一行对账。铁律:

1. **同源 = 所有前缀都走 `live_signals.topics()` 一份快照**。面板自己读文件 ⇒ 差一拍 ⇒ 快变量看起来"不一致"。
   判据用**冻结快照后逐字比对**, 不要用 ±25% 容差 (那是给实时两窗口的假报警)。
2. **固定行: 行集合必须稳**。老行按上拍顺序、新行插同话题末尾、本拍缺失字段保留上一拍那行 (标陈旧 60s)
   判据走**增量路径**, `force=True` 是用户点刷新, 允许重排。
   同一份带 TTL 缓存 (0.25s) 的真源, 判据**不许 `sleep()` 跳窗口**: `a=read(); sleep(0.1); b=read()` 会随机跨边界 ⇒
   单跑必过、批量偶红 (实测), 看起来像被测代码出了问题。修法: **强制刷新一次缓存 → 紧接着连读两拍**再比。
3. **删层前先补归属**: `ss.node.<id>.<port>` 没规则 ⇒ 判 SYS ⇒ 删 SYS 时整类话题消失。
   真源 `config/platform/dds_topic_types.json -> nodes.<id>` (ins.producers/outs.consumers/layer);
   in 口 Tx=上游、out 口 Tx=本节点/Rx=下游 consumer。
   · **画布上有节点 ≠ 有层索引**: `attribution.layer_of` 看的是 `db.node_rows()` 的 layer, 它由
     `src/lerobot/engineering/nodes/by_level.py::LEVELS_INDEX` 兜底 —— 节点在画布里、但 LEVELS_INDEX 里没有这一条 ⇒
     layer 落 `meta` ⇒ `layer_of` 返回 **SYS** ⇒ Trace「SYS 不入表」⇒ 该节点**整族信号一行都不显示**
     (实测「🛡 安全执行边界」`sslimit` 一直在画布, 而 `sstrace.安全边界_*` 4 条一条都看不到)。
     修法是**补 by_level 的层索引**(按语义归 L2 —— 执行由 L2 收口), 不是改 attribution 的 `PREFIX_OWNER`:
     那里本来就有 `("sstrace.安全边界", "sslimit", "")` 映射, 是层判定把它筛掉的。
     验: 新开进程跑 `attribution.layer_of("sstrace.安全边界_mms")` 应从 SYS 变 L2、`tx_of` 给中文节点名 ⇒ 再重启控制台。
     同型指纹: 用户说「数据空间怎么没有 XX 这个 Tx 节点」⇒ 先查 `db.node_rows()` 里该节点的 `layer`, 不要先怀疑映射表。
4. **给表加列 = 所有 `verify_*.py` 的列下标位移** ⇒ 判据会读出"不一致 398 处"的假故障; 加列必须同步改下标或改成按列头名取列。
5. **元数据过滤会把"只有信封字段"的端口整行滤掉** ⇒ 兜底用端口名占一行, 不回信封、不编 payload 字段。
6. **位姿信号**: x/y/z 是当前 TCP (不是每技能规划点); tap 停更时用 `trace_live.末端_x/y/z`(m→mm) 代偿并写
   `pose_src/age`; 3D 出口无姿态 ⇒ a/b/c 发 -1 + 一条 QoS warn, 不许凑。偏差 >5mm 走 fail 报警, 判据要注错值验。
7. **"3D 里位姿谁规划的" = 没人规划**, 是回放 `reports/ss_episode_latest.npz` (蒸馏 MLP + 八阶段状态机 +
   L4 闸 + MuJoCo 积分); `n_moveit` 不在环里 (`PURE=False` 只直通)。先看 `npz['meta']` 再说结论。
   **物理引擎每步只吃 4 维动作** (3 轴笛卡尔增量 → mocap 位移 + 夹爪 ±1), 8 阶段不进物理 ——
   它只在上游给 target/限速/夹爪时序。契约与换算 (a_gain=ctrl_dt/action_scale, mocap 工作空间 clip)
   见 `references/metaworld-closed-loop-contracts.md` 末两节（含**四段动作 u_ff/u/u_sat/u_exec 的落点**：
   哪些有实时字段、哪些只有 npz、DDS Action 话题图上有但无 publisher）。

8. **没有连线就不许写来源** (老倪: 「实际上也没有连线啊, 在 Rx 里删掉…没有这个连接」): 闭环内部算出来的量
   (帧/总帧/时间_s/估计值/估计误差/估计抖动/残差/残差系统偏差/接触概率/净接触) 画布上没有任何一条线 ⇒
   Rx 返回 `—`; 同时**不许用 catch-all 前缀规则**把它们糊给某个节点 (实测 `sstrace.*` 兜底把残差/帧全判成
   「Z-MAX 引擎」)。能指到真正算它的 L2 节点就指 (估计→`ssest` · 残差/净接触→`ssinnov`), 纯簿记量指进程
   (帧/总帧/时间_s→`ss_dreamview`)。归属表里出现「(无话题)/(无节点)」这类后缀 = 编造连接的痕迹, 直接清掉。
   最终口径比逐条判断更简单: 3D 场景那族 (`sstrace.*`) **整族 Rx 全清成 `—`** (全空不辩), 取数来源表
   (`SS_TRACE_SRC`) 只作历史存档, 不参与显示; 只有真有连线的 `ss.node.<id>.<port>` 才写 Tx/Rx。

9. **工程连线 ≠ 被消费**: 回答"某节点用这个输入干什么"必须看节点函数有没有读该端口 (`ctx.get("inN")` /
   `PORTS_IN` / `compute()` 里出现), 不能凭 `dds_topic_types.json` 的 producers/consumers 答。实测
   `ssintact.in3` 声明了 `ssff.out2`(`zmax::FeedforwardAction`), 但 `node_intact(ctx)` 只用 `ctx["log"]`/`ctx.get("root")`,
   端口值一次都没被读; 而且方向是反的 —— `u_ff` 是 INTACT 的**输出**(`policies/intact/decoder.py` 用
   `act×K_ACT` 算), 引擎侧 `SS_L4_INTACT=1` 走的是 L4→L3 注入。凭连线答"在用它"就是编造: 要么如实说
   "画了线但实现不读", 要么提出删线 (flows JSON + dds_topic_types + 工程库三处一起改)。
   **删线的落地顺序与坑** (`engineering_db.py build` 不重建 `mw_*` 表、`busdb.json` 必须单独重建,
   否则数据空间 Trace 还显示旧线) 见 `references/trace-signal-panel-consistency.md` §11。
   顺带: 工程 JSON 的 consumers 常有重复项 (实测 `ssff.out1` 写了两遍) ⇒ 显示前 `dict.fromkeys` 去重,
   否则 Rx 出现 "A / A" 这种一眼假的样子。

10. **Tx / Rx / Layer 必须是同一个工程节点算出来的, 且这两个窗口只留 L2** (老倪最终口径:
   「数据空间和信号分析…只保留 L2 层的 topic, 删除其它层的 topic; 信号也只能显示 L2 层的信号,
   signal 是 topic 的组成单元; Tx Rx 节点只能是 L2 层节点, 其它层都删掉」)。
   · `layer_of(key)` 先取 `tx_of(key)` 的第一段再查层 —— 两条独立路径会出现「Tx=Z-MAX 引擎(L4) 但 Layer=L2」。
   · Tx/Rx 不许出现进程名/服务名/`.py`/总线标签/「本机真值流 (JSON)」; 没节点就 `—`; 出处只进 tooltip「来源:」。
   · 显示名统一走 `naming.unique_map` (75 节点 ↔ 75 唯一名, 判据断言单射); SK 节点库里是 meta、信号层按 L2,
     但归一化只认**名字以 `SK0x` 结尾**的阶段节点 (散着出现 "(SK01-08)" 的是「物理约束」, 仍是 meta)。
   · 真值流话题在画布上没端口 ⇒ 用显式 `PREFIX_OWNER` 前缀→node_id 表; **字段级规则优先**
     (`sstrace.前馈速度` 归前馈加速器, 不归前缀属主); 前缀映射 None = 不是总线话题 ⇒ SYS ⇒ 不进 Trace。
   · L2 口径只在 `attribution` 收一次 (`l2_names/tx_l2/rx_l2/layer_l2/topic_in_l2/show_in_l2`), 面板不各写判断;
     规则节点不是 L2 但前缀属主是 L2 ⇒ 用属主 (`sstrace.末端_*` 归状态估计, 不归 L4 Z-MAX 引擎)。
   判据 `tools/verify_layer_node_strict.py` (8 项, 含数据空间页三张表) 一轮锁死, 细节见 reference §13/§17。
   · 两个窗口的显示口径**不一样时**, 用一个谓词族而不是各写一份:
     **数据空间 Trace = Tx 与 Rx 都是 L2 节点** (`show_in_l2_link`), **信号分析 = Tx 是 L2** (`show_in_l2`, Rx 允许 `—`);
     判据就按“Trace 里横杠数 == 0、面板可以有”写, 别把两个窗口的硬约束混成一条。
   · ⚠️ 闸门放错层级会把整表清空: 把“Rx 必须非 `—`”加到**话题级**过滤 ⇒ in 口话题的 Rx 天生是 `—` ⇒ **0 行**。
     闸门只放在**信号/行级**; 话题级只判 Tx/Layer。现象指纹: 改完 Trace 一行不剩, 而过滤器看起来“很合理”。
   · SK 类信号 (`skill.*`) 的键不是节点端口键 ⇒ `rx_of` 天然解不出 ⇒ 整族被当横杠删掉。
     要用 SK 节点的**真连线**解析 (sssk*.out1 → n_moveit), 不要就地补个“—”。
   · 删完横杠行后, **跨窗口同源探针得换信号**: 原来探的 `sstrace.*` 已不在这两个窗口里,
     改成两窗口都存在的 (实测 `接近_mps`, 两窗口共用 203 个同名信号); 且显示可能带单位换算
     (m/s → 屏上 mm/s), 断言要按换算比而不是字面值。
   · 真实数字约定: Trace 413 行 / 61 话题 · Rx 横杠 0 · 数据空间页 话题 97 / 节点 29 / 报文 45;
     一次性回退判据: 横杠 > 0 或出现非 L2 名 ⇒ 口径被破坏。
11. **同源快照 ≠ 统一数据库**: 要"同一个数据库"就落 SQLite `zmax_data/dataspace/signals.db`
   (`src/lerobot/dataspace/signal_store.py` + 2Hz 守护 `tools/signal_store_daemon.py`), `live_signals.topics()`
   先读库 (新鲜 <3s), 过期才回落文件并打印一行, `ZMAX_SIGNAL_DB_OFF=1` 强制旧路。
   单源证明用「停守护 → 改库一行 → 续期 `meta.updated` → 两窗口同值 → 恢复真值」, 别只比对冻结快照。
   细节 (含为什么必须续期 meta、判据容差) 见 reference §14。
12. **每行重查全表 = 刷新卡死的隐形大坑**: `db.node_rows()` 无缓存被 1936 次调用累计 5.6s ⇒ 整表刷新 4.6s;
   按源文件 (mtime_ns, size) 做 `lru_cache` 键 (库重建自动失效, 返回副本) ⇒ **0.12s**。先 `cProfile` 再优化。
13. **"面板不实时更新"先查 refresh 有没有每拍抛异常, 别先怀疑数据源**: 实测 `dds_space.refresh()` 里用了
   `_naming`, 而它的 import 写在另一个函数的局部作用域 ⇒ 每 2s 一次 `NameError` ⇒ 页面冻在第一次内容,
   而 live.json/trace.jsonl 一直 1s 新鲜。凡 `refresh()/timer` 里用到的模块一律**模块级安全导入**
   (`try: from ... import x as _x / except: _x = None`), 并加一条判据: 连刷多拍不抛 + 「live 龄」跟着源变
   (`tools/verify_dds_space_live.py`)。
14. **取值/探针必须用界面真实的字段名口径**: Trace 行显示的是中文友好名, **原始字段名在 tooltip 第一行**
   (`话题:`/`来源:` 同行); 信号分析树的原始键在 `item.data(0, Qt.UserRole)` 且带前缀 (`sstrace.<字段>`);
   树只在 `show()` 之后才填充, 判据里要 `panel.show()` + 泵事件 3~4s 再读。探针写错名字 (`末端.x` vs `末端_x`)
   会安静地读到 `None`, 看起来像功能坏了。

15. **信号名必须表意: 端口名 (out1/in1) 不许直接上屏** (老倪: 「out1 in1 根本看不出来是什么意思」)。
   端口名是画布的机械命名, 语义在**报文类型**里 ⇒ 真源 `mw_topic.type`, 不是端口名、也不是话题名猜。
   · 名字只在**一个函数**里生成: `src/lerobot/middleware/signal_en.py::en_of_key(prefix, field, mtype)`。
     两张窗口 (Trace / 信号分析) 都走它, 别各写一份映射 —— 各写一份必分叉。
   · 规则顺序: `TYPE_SIGNAL_EN` 人工短名 (`MotionPlan→plan` · `MotionPlanIn→plan_in` · `RobotActionIn→action_in`
     · `OpticalInspection→aoi` · `MuscleSkillBank→muscle_bank`) → 表里没有就 CamelCase→snake_case 兜底;
     **拿不到类型就不编**, 保留原端口名。同一类型多条入口 (`in1/in2`) 只有第一条用裸名, 其余带序号 (`plan_in_2`)。
   · 类型查不到时用**行自带的 `type`** 兜底 (`type_of_topic()` 只对 `ss.node.<id>.<port>` 命中; 直播话题/别名不带)。
   · 改名放在**渲染前一次**, 原始端口名留在 `raw`/tooltip 可追溯; 别在每行的渲染循环里做 (会撞上变量复用坑)。
   · 判据 `tools/verify_signal_names.py`: 全端口 (272) 裸端口名 == 0 · Trace 行裸端口名 == 0 · 点名口对照
     (`n_moveit.out1→plan` / `in1→plan_in`)。回退指纹: 屏上再出现 `out1`/`in1` 就是口径被破坏。

16. **速度类信号统一 mm/s: 后缀 `_mms` + 只在一处换算** (老倪: 「以后不要出现 mps」)。
   · 键名用 `_mms`, **不要 `_mmps`** —— 后者仍含 `mps` 子串, 违反用户口径; 也别用 `_m_s`。
   · **换算点只有一个: 生产端** (`ss_dreamview.publish_trace_live` / `ss_fw_trace_pub` 写值时 m/s×1000)。
     显示层**不许再按键名后缀乘** —— 旧 `canoe_graphic` 有 `if "_mps" in k: v *= 1000`, 改名后照样命中就二次放大 1000 倍。
     规则: 单位换算不能靠"键名后缀"判定, 后缀只用于**标注** (图例/Y 轴 `(mm/s)`)。
   · **契约内部仍是 m/s**: DDS 的 `v_cap`、`gravity_table`、物理约束表这类消费端读到 mm/s 键要显式 `/1000`,
     别顺手把内部契约也改成 mm —— 改的是信号口径, 不是接口单位。
   · 注册表同步: `config/topics/scene_tags.json` 的场景信号名 (真源在 `data/database/zmax/sources/config/`, **不在 git**,
     所以 `git add config/...` 会 exit 1 —— 那是软链到工程库 source); `signals.db` 里旧 `_mps` 行要顺手清,
     否则面板新旧两套名同时存在。
   · 验收: `tools/verify_trace_sync.py` 的「速度类信号单位 = mm/s」「数值口径 ±25% 越界 0 例」两行 + 现场采 2~3 帧看值在
     **同一量级且逐帧变化** (例: 插入段 10~32 mm/s、阶段限速 85 / 350 / 120 mm/s)。数值从 0.03 直接变 30 才叫改完。
   · 还有人改口径时把旧名留在注释/文档里: 只要**键名**不再出现 `mps` 即可, 注释里解释历史可以, 但别让字符串再进注册表。

全过程 (判据代码骨架、实测数字、报警注入法、归属单链、统一库、刷新性能、**L2-only 收口与闸门顺序**) →
`references/trace-signal-panel-consistency.md` §1–§17

## 📡 「现在的状态空间数据是什么」怎么读 (现场活数据地图)

用户会边跑边问「现在当前的统一状态空间数据是什么」/「状态数据进前馈加速器了么」。这些量全在文件里,
**先读文件再回答** (帧龄是最硬的"在跑"判据), 不许凭上一轮跑完的印象:

1. **文件地图** (`zmax_data/ss_live/`, 帧龄 <1s 才算活): `engine_latest.json` 主记录
   (cycle / **p** / action / chunk / skill闸 / z_latent / confidence) · `chunk_latest.json`
   (chunk / ff / λ / u 四组) · `skill_dispatch.json` (8 段 action) · `skill_latest.json` (闸计数 + 逐段 mps) ·
   `exec_state.json` (执行端 phase/transport) · `ar_exec.json` (AR 段) · `canvas_loop.json` (本拍跑了哪些节点)。
   历史: `/dev/shm/zmax_ss_engine/engine_<场景>.jsonl` (逐周期, 十几 MB 级)。
2. **4D `p` ≠ 39D obs**: `provider=traj` 的常驻 loop 里 `p` 是 **4 维** (x,y,z,grip), 取自
   `ss_episode_latest.npz` 的**回放帧**; tap 里**没有 39D** (39D 只在 `runtime` 那条链由
   `env._get_obs()[:39]` 产生)。报"状态向量"必须先报维度, 否则等于把回放 4 维冒充 39 维观测。
3. **`canvas_loop.json` 的 `only` / `n_ran` 才是"哪些节点在跑"**: 实测 79 节点里只跑
   `ssplan/ssact/ssyolo` 三个 ⇒ 前馈/状态估计/校正那些节点**不在跑**。"画布上有这个节点"证明不了它在本拍执行。
4. **前馈在块流水线里, 不是 `parallel.py` 那个类**: 常驻 loop 用 `ManifoldEngine`(本身无 u_ff) +
   `ss_chunk_pipeline`, 前馈 = `FeedforwardAccelerator` (左脑 MLP `models/ss_left_brain.npz`, 实测 `loaded=True`)。
   读法: `ff_mode="hold(单拍前馈保持)"` ⇒ 只在当前 obs 上算一次、保持 H 拍 (没接 `dyn` 就没有逐拍滚动);
   **`u` 不等于 `(1−λ)·ff+λ·chunk`** —— 之后还过逐拍调制器 (mod_tags) + 安全限幅 (实测 xyz 模长恰 0.12、
   grip 0.6), 裸公式只用来验方向与量级。`parallel.py` 的 `u=w_ff·u_ff+(1−w_ff)·u_fb` 调度器在**另一条链**:
   回答前先确认是哪条 loop, 否则会把没跑的那个类说成"在算"。
5. **可信度要连着来源报**: `z_source` 里写着"回退内建 PCA / 本帧不是 L4 潜表示"时, `z_latent` 与
   `confidence` (实测 0.0179) / `anomaly` (1.0) 都是兜底产物 —— 不许说成"模型算出来的低置信"。
6. **检测值进状态空间有两条路, 别混着说** (YOLO 对齐契约, 对 `yolo_state_aligner.align_obs` 逐行):
   `[4:7]=光模块` + `[22:25]=上一拍光模块` + `[36:39]=hole` —— **不是** `[18:21]`(那是 prev_hand, 旧版 bug,
   源码注释已标红), 也不是 `fuse_sensors` 那份 obs43 的 `7-9`(两套张量口径不同, 先确认是哪份)。
   而 `align_obs` **只在训练/离线对齐里跑**; 在役 `runtime` 走 `_peg_cur = _vis["peg"]`
   (`detect_3d` 输出, 接近期遮挡冻结), 仿真里 obs 的 `[4:7]/[36:39]` 仍是 env 真值。
   所以「检测值进没进状态空间」必须分两答: 控制路径进了 / obs 数组没被原地替换 —— 不许笼统说"已替换 obs"。

7. **「动作调制器有作用么」→ 它是四件事, 不只是削幅** (`cognition.ActionModulator.decide`, 实测量):
   `u = u_ff + k_fb·u_fb`(**相加**, 不是凸组合) → ①**残差否决** `residual>veto_th(2.0)` ⇒ u=0,
   前 2 拍 `否决: 减速/重试`、第 `max_veto(3)` 次起 `异常: 连续否决`; ②**阶段限速**经 InertiaLimiter 五约束
   (速度/加速度/加加速度/动量质量率/位移), 实测 0.350→0.150 m/s 且 `why=加加速度`; ③**v_min 会抬速**
   (防末端磨蹭): 0.0461→0.1531 m/s —— 别只讲"削"就漏了这一半; ④夹爪归状态机锁存。
   元任务门控 `ZMAX_META_GATE=0` 默认关, 别当它在起作用。长跑口径看 `skill_latest.json` 的
   `闸_拍数/闸_不可行拍/闸_削因` (实测 55.5% 的拍被削, 削因几乎全是速度)。
   短算例里 `gate_cuts={}` 全"可行"很正常: u_ff 在技能层已按 v_cap 限过 —— 不是闸没用。
8. **闸的上一拍速度/加速度会跨步残留**: `InertiaLimiter` 拿 `mod._g_v/_g_a` 比加速度/加加速度,
   换段/新一步时它们还是旧值 ⇒ **本段第一拍被旧方向拖** (实测 8mm 小步首拍 `u_sat` 反指目标,
   看起来像 IK 解错)。规则: 每步开头清 (`mod._g_v=_g_a=None, gate=None, veto_count=0`),
   实涋前三步到位 6.9/2.9/2.4mm → 5.3/0.8/1.4mm。
9. **原子技能在链上有两个身份, 顺序不一样 —— 回答"谁在谁前面"前先分清**:
   · 身份 A = 段目标/期望速度的产出方, 在调制器**之前** (runtime: `_skill_ff()` → `sched.decide()`
     → 夹爪锁存 → `safety.saturate`);
   · 身份 B = 安全后动作的分发口, 在安全**之后** (块流水线: 规划 → 前馈 → λ加权 → 调制 → 安全 → 技能派发)。
   用户说"安全 → 原子技能"时指的是 B; 说"技能出动作"是 A。两个接口 (`skills/atomic_skills.py`):
   `next_target(ctx, points, spec, with_phys, cur)` → `{stage,ref,off,xyz,tol_m,v_cap,...}` ·
   `command(ctx, x, k, v_cap)` → `{u,target,err_m,reached,rule,src}`。
   **`ctx` 就是感知/渲染数据的入口**: `{peg, table_z, hole_mouth, head_off}`;
   ref 表: SK01/SK02 = `peg + [0,0,hover_h]` (0.09 / 0.05, v_cap 0.35 / 0.12) · SK06 = `hole_mouth + hover`(0.02)。
   即: 技能自己定义目标, plan 只出段序 —— 切换会改几何基线, 必须整轮重测。

## 🧭 「谁是总调度 / 谁指挥谁」— 先算入度出度, 再读实现实参

架构类主张（用户或外部模型给的"总调度 = 某节点"）必须用两项硬证据核，不许凭节点 `desc` 里的形容词点头：

1. **拓扑**: 从 `data/database/zmax/sources/canvas/state_space_obs.json` 的 `links`(键 `f`/`t`/`label`)算 in/out degree,
   逐条列出候选节点的输入**来源 + 端口 + label**；再 `[l for l in links if l['f']=='<id>']` 核"它到底连到谁"。
2. **实现**: 找到该节点真实现(见「节点实现路径两套并存」)，把决策函数的**实参**抄出来(阈值/循环/分支)，形容词才成立。

实测(94 节点 / 222 连线那一版)：
- `sssched` 入度 **13**(全图第一)，出度 **2**: `out1→sslimit`(「阶段切换与动作融合」)、`out2→ss_grav_h`(「L2 动作调制→技能动作 a」)。
  13 路输入: ssllm(技能Token) · ss_mem_field(−∇Φ) · ss_mem_l3 · ss_mem_l2 · ssaoi(质量门) · n_l2_muscle · ssff(前馈30%)
  · ssreason · ssinnov(u_fb) · ss_moe(阶段置信) · n_intent_direct(元任务) · ss_mani_eng(动作a) · n_geoplan(测地线)。
- `sslimit` 入 3(`sssched`/`ssphys`/`n_geoplan`) 出 **11** ⇒ **真正扇出到执行器的是它**；`n_exec` 入 3(`n_moveit`/`sslimit`/`ss_grav_h`)。
- `ssobs`(SU(2)) 7 条出边 = ssff/ssest/ssreason/ssvideo/ss_moe/ss_mani_eng/n_geoplan —— **没有直连 sssched**;
  "调度器拿到 su2 的宏观状态"是经 ssff / ss_moe(阶段置信) 的**间接**路径，回答必须说"间接"，不能写成直连。
- `sssched` 的仲裁不是形容词: `cognition.ActionModulator.decide` 真做四件事 —— 残差否决 `residual>veto_th(2.0)` 返回全零、
  连 `max_veto(3)` 次改报「异常: 连续否决」· 融合 `u=u_ff+k_fb(1.0)·u_fb`(相加，注释写明量级差 21 倍所以不用凸组合) ·
  阶段限速 `STAGE_V_CAP` 12 段(完成 0.02 / 抓取 0.04 / 插入 0.085 / 对位 0.12 / 接近·转移 0.35 m/s，只削幅不改方向) ·
  每拍 `skill_step()` 过 SK01-08 五约束闸。

对外口径(实测支撑): 三层权力 —— **语义仲裁 `sssched`**(毫秒) · **边界扇出 `sslimit`**(幅值，出 11) ·
**物理放行 = 授权/安全闸**(在图外，没授权臂一动不动); `ssobs` 是**全局相位度规**(收敛度 |w| / 层间非交换)，不是调度器。
任何"总调度压在单节点上"的说法，一查 links 就露。

`su2` 的数学主张可当场自证(`group_axiom_selftest()` 返回逐条实测误差，不是写死通过): 酉性/det/结合律/逆元 ~4e-16 ·
测地三角形不违反 · 平均对易子角 1.32 rad(≈76°) · 同四层换序 θ 差 4.05° · 不可交换矩阵 L3|L4=1.194 rad vs L2|L5=0.042 rad。

## 📁 「所有节点的 json 文件是哪个」

`data/database/zmax/sources/canvas/state_space_obs.json` —— 引擎每拍读的**现役**画布(`ss_canvas_loop.py` 的 `CANVAS`)。
干扰项一次点明，别让用户拿着快照当现役: `_archive/`(历史备份) · `sources/canvas/ss_traj_last.json`(轨迹临时文件, 0 节点) ·
`../zmax_space.proj`(快照/导出，节点在它的 `canvas` 字段) · `../config_meta.json`(参数元信息 2.8M) · `../zmax_engineering.db`(sqlite 工程库)。
报数一律「节点 N / 连线 M + mtime」；与 550C 对照要两份口齐 —— 节点数相同而连线数不同(实测 94/222 vs 94/214)就是旧版，
不能用一句"两边一样"糊过去。

## 📋 把节点清单导出成文档表（名称/功能/PURE/实现文件）

交付文档要「L2 层所有逻辑节点的功能」时不要手写清单，三步从真源拼：

1. **分层从画布坐标取**：`data/database/zmax/sources/canvas/state_space_obs.json` 里 `type=='row_bg'` 的节点给出各层带的 y 区间，节点按 (x,y) 落在哪条带归层。`ssworld`（🌍 物理世界）这类环境实体**不算逻辑节点**，计数排除并在图注写明。
2. **id → 实现模块**：`src/lerobot/middleware/nodes/_index.py` 是「画布节点 id → 模块名」映射；模块文件头带 `NAME` / `PARAMS['desc']` / `PURE` / `SOURCE`+`SOURCE_SYMBOL` / `PORTS_IN/OUT`，这就是「功能」字段的真源（`desc` 首句通常已是完整功能描述）。
3. **`SOURCE` 为空串的节点**（`ssaoi` / `n_l2_muscle` / `ss_mem_l2`）用实现键或实现文件头原文补，并在表里标注「SOURCE 未登记」，**不要编路径**。

坑：①抓 `^PURE\s*=` 必须带 `re.M`（只给 `re.S` 时全表返回空，看着像节点没登记）；②这类集合里常有 `limit=None` 的附属项（`spec['joints']` 末两个 tool 关节就是），先过滤再取字段，否则第一项就 `TypeError`；③表里同时给 `PURE=True/False` 两态 —— 用户就是用它判「真算 vs 只走数据面」。

## 🧾 回答「这个节点现在的输入输出是什么」— 四件套, 一次备齐

用户问这类问题时不要只贴契约抄一遍。按此四步，交付里同时给**路径+行号**（他要直接贴进 VSCode 打开）：

1. **定位节点**: 画布 JSON 里按**名字**找 id (`data/database/zmax/sources/canvas/state_space_obs.json`,
   例「统一状态空间」→ `ssobs`)。⚠️ 契约文件名 **不等于** id: `ssobs` 的契约是 `n_state.py`
   —— 用 `middleware/nodes/_index.py` 的 `'<id>': '<模块>'` 映射查，别去猜 `n_<id>.py`。
2. **端口真源是契约文件, 不是 links**: 画布 `links` 里的 `fport/tport` 常是 `None`（只有拓扑语义），
   端口名单只在契约 `PORTS_IN/PORTS_OUT` 里；连线只用来回答"连到谁"。
3. **一条命令拿真值当证据**（比读代码推断可信）—— 每个 impl 都导出入口函数并留 `run = 入口` 别名:
   ```python
   from lerobot.middleware.nodes.impl.ss_obs import node_ss_su2
   out = node_ss_su2({"log": lambda m: logs.append(m), "demo_light": True})
   # 返回 {'out1':…, 'out2':…, 'out3':…, 'ok': True}；out1/out2 同一份 43D obs 体, out3 = 群读数
   ```
   报字段就报返回值里的: out1 的 `tcp/peg/hole/tactile/src`, out3 的 `readout/dominant_layer/layer_peel`。
4. 🔴 **必须同时报 `PURE` 和本拍跑没跑**: 这类契约多半 `PURE=False` + `EXEC_MODE='view'` ⇒ 常驻循环/画布
   `compute()` 只做 `out1←in1` 直通，out2/out3 恒 None；真实现只在「单步 / 右键运行 / ▶运行」时执行。
   "哪些节点在本拍跑"看 `zmax_data/ss_live/canvas_loop.json` 的 `n_ran` / `fast_only`（实测常驻只跑
   ssplan/ssact/n_moveit/n_geoplan）—— 端口有值≠这条链在算。

⚠️ **两个读数的口径陷阱（报数前先想）**:
- L2 走 `quat_truth` 精确四元数时, `θ` 是**姿态角本身**（`z_pos` + `SS_TRUTH_YAW_DEG=180` ⇒ θ=180°、|w|=0），
  **不是误差角**；只有回落 43D 时 θ 才是 tanh 压缩后的误差指示器。两种 θ 不许放一起比大小。
- `demo_light=True` 时 L2 可因无 `obs43` 缓存而落单位元/记忆真值，但返回段仍会调 `_ss_ensure_obs43()`
  触发真采样（日志会有 YOLO/metaworld 加载行）—— 所以"light 档=零开销"不成立，解释时说明是缓存路径。

## 关键文件
- src/lerobot/engineering/start.py (**工程正式入口**: 状态机+策略表+钩子+单实例锁+优雅停机;
  生产 unit 的 ExecStart 指向它. 用户强调过「这不是调试程序」⇒ 别拿它当临时 runner 改, 也别把调试开关塞进入口。
  `tools/ss_canvas_loop.py` 只是执行腿/节拍器(10Hz 逐节点), 不是入口; 工程本体在它的 `load_project()` 那一刻装载。
  状态机 `state_space/scheduler_fsm.py::DispatchFSM` 做**进程级单例**(注册表挂 builtins) —— 调制器每拍 `new`
  且同一文件可能被包导入与按路径加载成两个模块对象, 不修就"状态机看着有、实际不动"。
  细节/取证/systemd drop-in → 相关技能 layered-capability-stack 里的「dispatch-fsm-entry」参考)
- src/lerobot/engine/runtime.py (闭环总装 `RealStateSpaceSim`, 4240 行零 Qt; 原 `tools/gui/state_space_sim_real.py`,
  那边现在只剩别名 shim `sys.modules[__name__] = 真身`。**三层身份别混**: 总装 runtime ≠ 流形引擎节点
  `ss_mani_eng`→`src/lerobot/manifold/manifold_engine.py` ≠ 物理积分(metaworld/MuJoCo 内建)。
  改物理保真度动 metaworld 参数与动作缩放 `a_gain`/`action_scale`; 改控制律/阶段时序才动 runtime.py)
- src/lerobot/policies/left_right/state_space/{parallel,perception,cognition,dynamics,execution,safety}.py
- tools/gui/state_space_sim.py (HOLE_POS 常量 + ff_forward 真权重 + _stage_target)
- tools/gui/node_logic.py (node_ss_s2 分派 + _EXTERNAL_LOC 映射, 行 2062-2075)
- tools/gui/node_logic_dialog.py (_load_source 源码展示优先级)
- tools/ss_verify_trained.py (训练权重替换验证)
- tools/gen_insert_video.py (真机同构: YOLO detect_3d 解算写 obs[36:39])
- 数据空间(DDS 总线)的信号表与关键词、MoveIt 规划/action 取数地图（含"域是 42""action 话题默认隐藏"
  "规划结果走 get_result 服务不走话题""`tcp_path` 只存 x y z""姿态比对只能用四元数夹角"）
  → `references/dds-bus-signal-map-and-moveit-action.md`

## SU(2) 节点级映射的真源 (2026-11-03 修)

`node_ss_su2` 曾读 `getattr(mod, "_ss_io_frame")` —— **全仓库无人写这个属性** ⇒ `encode_nodes({})`
永远空帧, 节点级映射静默落空。现在三路取数 (`library.py::_ss_node_frame`):
① `mod._ss_tr["io_trace"][_ss_round][1]` (画布引擎**当前帧** io 快照, 标签与 NODE_SPECS 同口径;
   无 `_ss_tr` 时退 `mod._tr` 末帧) →
② `runtime.LAST_OUT` (每个节点真跑完留的返回值, `runtime.run_node` 里记) → ③ `mod._ss_io_frame` 兼容。

🔴 **YOLO 输出三套标签, 只认一套就是静默单位元**: 契约 `vision_points.json`(`points`:光模块·当前/hole, mm) ·
`lerobot.engine.runtime` io 快照(`peg 3D (detect_3d)`) · `lerobot.engine.sim` io 快照(`peg 3D 坐标`)。
NODE_SPECS 用 `ptsdiff` 三路全认 (契约 mm→米 与 `obs43_geometry` 同单位; 3D 标签优先于 2D 框)。
判据: `cos(n̂, 光模块−hole)` 必须 = 1.0; `encode_nodes(detail=…)["no_numeric_output"]` 里不该再出现该节点名。

43D 侧同理: `_ss_ensure_obs43` 现**优先吃** `_YOLO_CACHE["aligned39"]`(align() 真实产出, 带
`aligned39_t` 时间戳, `SS_ALIGN_MAX_AGE_S` 默认 3s), 过期才退回 metaworld 真值; 用哪一路写进
`_SS_STATE["obs43_src"]`。改完必回读日志里“📊 43D obs 组装 (yolo/env 源)”这行。

### L5 槽 (意图) 的真供给

`state_space/l5_intent.py`(2026-11-03) 是 L5 的唯一写入方: DeepSeek 短提示 + 小 JSON
`{"intent":[x,y,z],"conf","why"}` → `frame["L5_intent"]` → `su2.encode_layer("L5")`。
· intent 语义 = **基座系期望运动方向**(单位方向, 不是位置/速度幅值); 减小误差应指向 **−e**, 所以自检用
  `cos(intent, −(peg_head−hole))` (实测 1.00 为对); 旧版写成 cos(intent, e) 会把正确动作误标 suspicious。
· **延迟实测 0.8s~133s 波动**(同 key, 关 thinking 也一样) ⇒ 必须单飞 + TTL 缓存(默认 60s, `SS_L5_TTL_S`),
  异步档**绝不阻塞 10Hz**; 冷启第一拍返回 None = L5 落单位元 + 日志说明。`SS_L5_SYNC=1` 仅调试用(会卡 1~130s)。
· 校验硬闘: JSON 必需、3 维、有限、非零、clip 到 [-1,1]; 失败就 None, **不用规则冒充大模型**。
· 调用流水 `zmax_data/l5_intent_calls.jsonl` 可恢复查每一次的 vec/why/时延。
- **末端位姿 x/y/z/a/b/c 的真源与坐标系口径**（仿真 episode 不记姿态 · 真机走 `rokae_sdk/tcp_out/latest.json`
  `frame=base_link` · 现场世界系须标定才存在 · `ss_live/trace_live.json` 是单槽会被不同任务互相覆盖）
  → 同上文件末节「末端位姿 x/y/z/a/b/c 的真源与坐标系」

## 🧮 「四元数/群元素 = 执行尺子」类主张的判据 (先量再答)

用户/评审常提「四元数把旋转映到 S³ 上一段轨迹, 一一对应, 所以算轨迹 = 执行动作」。方向对 (exp 映射
`su2.from_rotvec` 就是这个), 但**这个主张在本工程当前不成立**。回答前必须做三项检查, 每项都给数:

1. **编码是否单射** —— `ω = π·tanh(g·‖e‖)·ê` 是**压缩指示器**不是实际旋转角。实测量 `encode_obs43`:
   ‖e‖=10mm→θ 3.60° · 50mm→17.9° · 100mm→35.5° · 500mm→137.1° · 1000mm→173.5° · 5000mm→180.0°;
   角分辨率 6.28e-3 → 2.8e-5 rad/mm (**衰竭 200×**)。⇒ 大误差段多对一, 不是卡尺。判「是不是卡尺」
   就量两段不同 ‖e‖ 在 θ 上是否仍可分, 别口头断言。
2. **双覆盖要商掉** —— SU(2)→SO(3) 是 2:1; `U` 与 `−U` 是同一旋转 (实测四元数夹角 0.0°)。
   不先说「商掉 ±q」就写"一一对应"必错, 且符号跳变处会造出伪轨迹。
3. **消费者是谁 = 唯一硬判据** —— `grep -rn "su2_readout\|su2_layers\|su2_scene\|su2_nodes" src tools`:
   全仓库只命中 `tools/gui/su2_dialog.py`(面板) 与 `tools/plot_su2_state.py`(出图) ⇒ **群元素是给人看的读数层**。
   真正下发的是 `ss_station_engine.tick_plan`: `u_sat[:3] * dt` → 8802 双臂 IK/control (速度域), 没有任何一行
   把群元素/测地线转成关节或末端位姿指令。

结论口径 (现状): 统一状态空间 = **观察/分解层** (方向+幅度+层剥离+耦合强度), 执行走 **速度闭环**;
它借了四元数的数学结构, 没拿它当执行尺子。②③ 里**姿态那一步已落地但默认关** (见下节「参考姿态」);
`ZMAX_ARRIVE_TOL_DEG` 仍只做"到位验证" fail-closed, 不参与轨迹生成 —— 真正的 A/B(速度链 vs 位姿链 的
成功率/朝向误差/UPH) 还没做, 需要现场授权, 别把"入口通"说成"已提升"。

## 🧩 出口/权重/预测/参考姿态 四件套 (2026-11-12 落地, 判据 `tools/verify_su2_layers.py` + `tools/verify_pose_chain.py`)

`ssobs` 从"一份读数"升级成"分层的、会挑信源、能预测、能给参考姿态"的节点。**每件都有可复跑判据(11/11 + 7/7)**,
改这块前先跑一遍, 别凭日志感觉:

1. **out1 ≠ out2**: out1 = 43D 观测体, out2 = 四层结构体(θ/方向/可观测/权重/贡献)。
   🔴 **同一拍必须同一份 obs43**: 原来 L2 编码用一份、out1 又调 `_ss_ensure_obs43()` 重取一份(env 会重采样)
   ⇒ `same_frame_as_L2=False`, 下游拿到的和 L2 判据的不是同一帧。判据就查这个字段。
2. **权重 = 有没有数 × 时效**, 作用在**群内**(角缩放/slerp), 不是向量平均 —— 全权重=1 时与旧 compose
   **逐位相同**(零回归, B1 判据)。L5 半衰 30s、过期即 0; `w` 0→1 必须真改场景(实测 Δθ=0.367), 否则是摆设。
3. **预测先行要预测「输入」, 不许预测群元素**: 编码是 `π·tanh(g‖v‖)` 非线性 ⇒ 对群元素做等角速度外推,
   平稳段就有 3~8° 残差, 阶段突变被淹没(实测过)。改成一阶外推输入再编码 ⇒ 平稳段 **0.0°**、突变拍 4.17°。
   🔴 四元数/慢先验(**L2_quat / L5_intent**)不参与外推: 外推单位四元数会得到非单位四元数, 残差随机乱跳(实测)。
   信号饱和(contact 到 1.0 被削顶)也会被判成事件 —— 这是**特性**, 别为了让它"平稳"去改判据。
4. **参考姿态进执行链(位姿链入口)**: `ss_obs.out3.quat_ref`(xyzw) → 段表 `quat_ref` →
   `daemon._ref_quat()` → 已有"位置+姿态双判据"到位检查。默认**零变化**: 只有段表显式写 `quat:"su2"/"ref"`
   或给 `quat_ref` 才走; 坏输入(3 分量/非单位/非数值/顺序不符)一律**拒发**, 宁可不动臂。
   🔴 **分量顺序是真事故级坑**: `quat_truth`/`pose_caliper` 内部是 **(w,x,y,z)**, 执行器全链是 **(x,y,z,w)**。
   不转换时四元数仍是单位长度、校验全过, 但"工具 z 对 −z"会发成"对 +z"(**差 180°**)。
   定式: 跨模块传四元数必须显式带 `quat_ref_order="xyzw"`, 不符即拒; 判据 = 用 6 个技能轴验 `R(q)·ẑ` 与轴的夹角
   (实测 0.000e+00°)。

> 复跑: `gui-venv311/bin/python tools/verify_su2_layers.py` (11 项) / `tools/verify_pose_chain.py` (7 项,
> 零运动不写 FIFO)。两者都会把结果落 `reports/*.json`。
流形引擎那条 "测地线真驱动动作" 也不是位姿轨迹: 状态是 PCA 潜空间 `z[:3]`, 目标是 `obs[0:3]←孔位` 重投影配的。

### AR 站四层覆盖 (问「L2~L5 对 AR 有没有作用」先查这里)

AR 站 (8797) 每拍跑 17 节点 L2 全链 (`tools/ss_l2_chain.py::L2_ORDER`): ssyolo → ss2d3d → sssensor → ssobs →
ssest → sspred → ssinnov → sstactile → ssaoi → ssff → **n_geoplan** → sssched → sslimit → ssphys → sssk →
ss_mem_l2 → ssact; `tick_plan` 再把测地线块与前馈 MLP 按 λ 加权 → 调制 → `safety.saturate`。

| 层 | AR 闭环内? | 证据 |
|---|---|---|
| L2 检测/收口 | ✅ | `ss_station_engine.obs43` 的 `[4:7]` = `ST["perc"].xyz` (YoloPerception 产出) |
| L3 规划 | ✅ | `n_geoplan` 测地线 chunk 进 `tick_plan` 右支 |
| L4 执行/安全 | ✅ | `ssff` 前馈 MLP 左支 + sssched/sslimit/ssphys 三级闸 |
| L5 大模型 | ⚠️ 半 | 页面「🧠 L5 理解」按钮走 `ar_l5_understand.py`→SceneVLM(deepseek VL), 按需、不进节拍、不下发; **闭环内零命中** (grep `L5\|l5_intent` 在 ss_station_engine.py / ar_render_station.py 无结果) |

别把两套口径混成一句: AR 用的是流形引擎的 su2 **切空间**(obs43→潜空间→群), 不是 su2.py 的 L2~L5 层合成;
`l5_intent.py` 目前只喂画布「🧩 SU(2)」节点的 L5 槽。要让 L5 对 AR 真起作用, 得接进 `tick_plan` 的前馈/规划权重,
且它实测 0.8~133s/次 ⇒ 只能当慢先验。

## 四元数真值策略 (quat_truth.py, 2026-11-03)

链路: 记忆(技能轴向)→真值 q_t → 感知补偿(S³ 互补滤波, 权重=新鲜度)→q_fused → su2 L2 精确群元素
(不再 tanh) → 流形/规划/action/原子技能; 伴生 V=½kθ² 与指向真值的引力, 契约落
`zmax_data/ss_live/quat_truth_latest.json`, 流水 `quat_truth_calls.jsonl`。

判据 (必须复验): 106 条技能轴对齐 0.0; 3°/α=0.5/w=1 → 融合 1.5°; 过期或无测量 w=0 且 q_fused==q_t;
V 随误差单调; 引力方向 cos=1; `encode_layer("L2", {"L2_quat": q})` 与 q_fused 逐位一致。

坑 (都踩过):
- 四元数误差必须用 Hamilton 乘法 q_t⁻¹⊗q_f, 逐元素相乘会得到恒 180° 的假误差。
- `s3_angle` 不含 ±q 商, 直接 2×角度会出 360°; 用 `|rotvec(rel_q(a,b))|` 取物理角。
- 轴向要带符号: 只看 |e_x| vs |e_z| 会丢方向, 真值与测量差 180°; 用插入方向 d=孔位−光模块 的符号。
- 姿态不是唯一解: 同一"工具 z 对齐"约束下 24 个 yaw 里有的 0.0mm 可达、有的差 30~150mm
  (现场 URDF 数值 IK, tools/pose_offline_sim.py)。固定 yaw 写死会让整段不可达。
- 位置-only 段表按末端速度排时间 → 关节速度峰值 554°/s (10Hz 采样) 远超常规 180°/s;
  说 UPH 前必须用关节 q̇ 复核 (段表直加 313 → 补段间瞬移 292 → 按 S 曲线峰值限幅 277 → 台账实测 216)。
  三项复核的做法/工具/实测表 + 姿态可行集 (24 个 yaw 中有的 0.0mm 有的差 30~150mm)
  → `references/pose-and-takt-physical-checks.md`
- 🔴 **经 `_ss_import`(spec 按路径加载) 调入的新模块, `import 兄弟模块` 会 ModuleNotFoundError**:
  spec 加载不给 sys.path 加目录 ⇒ `import pose_caliper` 失败, 而画布节点里这异常被 try 吞掉, 节点静默落回旧路径
  (日志只一行 ⚠️)。定式: 模块顶部自补目录 `_HERE=os.path.dirname(os.path.abspath(__file__)); _HERE not in sys.path and sys.path.insert(0,_HERE)`,
  再 import 兄弟模块。判据: 用**画布节点真跑路径**(不是 `cd 目录 && python 模块.py`)验一次。
- 真值/契约落盘要能被下游查: `zmax_data/ss_live/quat_truth_latest.json`(单槽, 写临时文件再 os.replace) +
  `quat_truth_calls.jsonl`(逐次流水, 可复盘每次 err/V/w/引力)。

### 部署到 550C(intel) 的验收口径

- 🔴 **节点实现路径两套并存, 所以「三台同一份代码」要按算法文件验**: 本机(550A/550B)已重构到
  `middleware/nodes/impl/ss_<x>.py`, 而 550C 仍跑 `engineering/nodes/library.py`(`grep -rl 'def node_ss_s1'` 只在后者命中),
  两边**算法实现**是同一份(实测都走 `perception.fuse_sensors` / `state_space/map_fusion.py`)。判据 = 各机先 `grep -rl 'def node_<fn>' src`
  找真实壳, 再对算法文件(`policies/left_right/state_space/*.py`)逐个 md5 对照; 壳位置不同只是布局差异, 但**必须主动说清**——
  用户问的就是"是不是同一份", 用路径比较回答会给出错误结论。

intel 的登录用户是 `intel`(不是 ubuntu), `~/zmax` 是**同步副本不是 git 仓库** ⇒ 不能 `git pull`, 用
`rsync -a --relative <相对路径...> intel:~/zmax/`, 然后**在远端跑一遍模块自检**并与本地 `md5sum` 逐个对照;
只比时间/大小不算部署成功。intel 上的飞书凭据在 `~/.hermes/config.yaml` 的 `platforms.feishu`(它自己的应用),
别再往 `.env` 塞第二套(双源打架); gateway 存活看 `systemctl --user is-active hermes-gateway` +
日志 `✓ feishu connected`。代码同步了但服务未重启 = 未生效, 要如实报不生效。

### 补偿增益头的训练与验收 (tools/train_quat_gain.py, eval_quat_gain.py)

- **退化任务警告**: 若把记忆真值当"精确", 最优解就是忽略测量, 训练出来的头必然劣于解析基线
  (实测 v1: 头 6.50° vs 基线 1.68°)。必须有"记忆漂移"才有融合增益空间。
- 零初始化输出层 ⇒ 起点 g=0.5 恰等于解析基线, 保证"先不回退, 只在有增益处改进"。
- 实测 (600k 样本/22 epoch/4060, 106s): 总体 2.386° vs 2.898° (Δ-0.51, p95 4.54 vs 5.73);
  10-15° 噪声档 2.465 vs 3.771 (Δ-1.31); 3-6° 档 +0.115 回退 ⇒ ok=false, **不进默认档**。
- 混合门限 (|测量−记忆| ≥ 12° 才用头, 门限只在验证集选): test 2.652 vs 2.895, p95 改善 0.68,
  但 6-10° 档仍 +0.032 ⇒ 按"每档不回退"门槛依旧不上线。要上线必须真机姿态标定数据复评。
- 验收脚本必须用**独立种子**重采样, 且门限只在验证集选 —— 否则等于自评自过。

- **产物覆盖坑**: 旧训练任务在后台跑完会覆盖同名 quat_head.pt / report.json, 导致 ckpt 与报告不同源
  (实测 v1 在 09:18 覆盖了 v2 的产物)。同一输出目录只允许一个训练进程; 训完先校验 `ckpt.arch` 与 `report.task` 是否同源再验收。

### 🎯 轨迹可视化窗口 (主参数页 S³ 轨迹球 + 完全隐藏)

四元数那段「滑动轨迹」要在右侧栏**看得见**: 新视图挂在 `MasterParamMView.viz_stack` 第 3 页
(`tools/gui/su2_traj_ball.py`), S³ **立体投影 `p=(x,y,z)/(1.05−w)`** (极点放球外, 单位元不发散),
轨迹用 slerp 补点成弧, 只认 `quat_truth_calls.jsonl`, 无数据画空态。
「完全隐藏」= 隐藏控件 + **停刷新计时器** + **从下拉摘项** + QSettings 落盘 (`mparam/su2_ball`),
还原口是视图行的 🎯 小开关; 宿主用 `hiddenChanged` 统一做摘项/落盘。
离屏验收 (`QT_QPA_PLATFORM=offscreen` + `grab()` 关键颜色像素统计 + 重启态 0/1) 的判据表与
两个坑 (隐藏后 grab 仍返回旧画面; 别开第二个 GL 上下文) → `references/su2-trajectory-ball-ui.md`

#### 📐 规范化经线视图 (经度=绕哪根轴, 纬度=转了多少)
- 算法: 相对起点每步 `r = q_i ⊗ q_0⁻¹` → **转角定纬度** (窗口内最大角归一 ⇒ 赤道 0° = 起点, 北极 90° = 转到位)、
  **轴定经度** (同轴 = 同一条经线)。单轴动作画出来正好是一条赤道→北极的经线; 换轴就换经线。
  三视图循环 `S³ → S² → 经线`, 默认落在经线视图, 选择落 QSettings `mparam/su2_mode`。
- 判据 (单轴合成轨迹必须过): 绕 x 90° / y 60° / z 45° ⇒ 经度跨度 **0.0000°**、偏差 RMS **0.0000°**、
  起点 `(1,0,0)` 赤道、终点 `(0,0,1)` 北极。真数据**不设跨度上限** —— 它是读数不是合格线
  (实测混轴 8 次观测 z_pos+x_neg: 偏差 RMS 97.6° / 圆周跨度 360°, 扇面开度就是混轴程度)。
- 🔴 **角度≈0 时旋转轴是病态的** (`r≈I` ⇒ 轴方向纯噪声) ⇒ 必须继承最近的有效轴, 否则起点附近会甩出
  90° 假经度 (第一版实测就是 0.000° 期望值算出 90°)。
- 🔴 **经度是角度, 不能用 `max−min`**: 同一根经线在 ±180° 两侧各取一半 ⇒ 跨度被算成 180°(甚至 360°)。
  用圆周统计 `R=|mean(e^{iθ})|`、`circ_std=√(−2 ln R)` (第二版实测因此虚高)。numpy 数组别喂 `math.sin`,
  用 `np.sin(...).mean()` 再转 float。
- 视图设计红线 (本页同类窗口通用): **隐藏后必须有带字的恢复入口** (`🎯 显示球`, ≥78px 深底+蓝描边),
  只留一个 26px 图标用户会找不到; 字号一次只调**一档** (页面 12pt / 下拉 12px / 弹层行高 24px 为定稿档),
  下拉弹层白底白字要修 `QAbstractItemView` 而不是只改 `QComboBox`。
