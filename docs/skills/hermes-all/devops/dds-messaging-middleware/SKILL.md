---
name: dds-messaging-middleware
description: Use when 多端要互通遥测/指令, 用 DDS 做中间件, 或 DDS 收不到。
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [dds, cyclonedds, pubsub, telemetry, middleware, multi-host, qos]
    related_skills: [http-relay-service, systemd-boot-services, cross-venv-model-canvas-node]
---

# 多端消息中间件（DDS 发布/订阅）

## When to Use
- **多台机器**（工位机 / 备份端 Mac / 公网云 / 边缘盒子）之间要持续交换**遥测或指令**
- 现在用 HTTP 轮询 / relay 中转，想换成**发布/订阅 + QoS**（免轮询、天然多方、可靠/尽力可分级）
- 现场已有 ROS 2（其底层就是 DDS）→ 想用同一套中间件打通**非 ROS 节点**
- 症状：**发布端日志显示在发，订阅端 0 条**（见「多网卡」一节，最高频的坑）
- 想让 UI/APP 显示**别的机器的**硬件资源（GPU/MPS/CPU/内存/磁盘）

## 技术选型
**Eclipse Cyclone DDS**（OMG DDS 标准实现）· pip 可装 · Linux/Mac/Windows 通用。
```bash
python3 -m venv ~/dds-venv
~/dds-venv/bin/pip install -i https://mirrors.aliyun.com/pypi/simple/ cyclonedds
```
> 放**独立 venv**，别污染训练/业务环境。

## 话题与 QoS 设计（按用途分级，别一刀切）
| 话题用途 | QoS | 为什么 |
|---|---|---|
| 状态快照（硬件/进度）| RELIABLE · KEEP_LAST(1) · **TRANSIENT_LOCAL** | 新订阅者一上线**立刻**拿到最新值，不用等下一轮 |
| 指令（部署/回滚）| RELIABLE · **KEEP_ALL** | 指令**不许丢** |
| 心跳/存活 | **BEST_EFFORT** · KEEP_LAST(1) | 丢一两个无所谓，别为它重传拖累总线 |

**显示口径：QoS 要写成 DDS 标准策略名，不要暴露内部简写。** 内部 `beat/state/cmd` 与库里的
`reliable/transient_local` 只是别名；UI/日志/导出一律翻成 `BEST_EFFORT|RELIABLE · KEEP_LAST(n)|KEEP_ALL ·
VOLATILE|TRANSIENT_LOCAL`。非 DDS 后端 (shm / 单步调试) 明确标「非 DDS」，解析不了写 `❌ 未知: <原值>`。
一个 `middleware/qos_names.py` (`standard()/valid()`) 供所有入口共用 —— 在表格里各拼一份，必然出现
同一话题两处 QoS 写法不同。

**约定：未测到的量 = `-1.0`，不用 0 冒充。** 0 是合法实测值（GPU 真空闲）；把"测不到"写成 0
会让下游把"没数据"当"真的零负载"。字段名带单位（`util_pct` / `mem_used_mb` / `power_w`）。

## 🔴 多网卡主机：必须用单播配置（否则"发了收不到"）
DDS 默认靠**多播**做发现。多网卡主机（lo + 有线 + WiFi + docker0）上，多播可能挂在**错误的网卡**
（典型：docker0），于是**发布端一切正常、订阅端 0 条、配对数为 0**。

**症状三连**：发布端日志正常打印 → 订阅端 `get_matched_publications() == 0` → `wait_for_match` 超时。
**修法**：关多播 + 显式列单播 Peers。可用配置见 `templates/cyclonedds_unicast.xml`。
```bash
export CYCLONEDDS_URI=file://$PWD/dds/cyclonedds_unicast.xml
# 或脚本化: --cfg dds/cyclonedds_unicast.xml
```
> 这同时是**跨公网**的必要条件（多播过不了公网/多数交换机）。若一开始就用单播配置，
> 本机自测 + 内网 + 公网三种场景都不必改配置 → **把它设为默认**，别等踩坑再加。

## Cyclone DDS Python 绑定踩坑（11.0.1 实测）
细节与可抄代码见 `references/cyclonedds-python-api-notes.md`。速览：
1. `from cyclonedds.idl.types import string` **不存在** → IDL string 用 Python 内置 `str`
2. `Policy` 各子类 API **不一致**：`Reliability.Reliable(n)` / `History.KeepLast(n)` 可调用，
   但 `BestEffort` / `Durability.TransientLocal` **不可调用**（传类本身）→ 用 try/except 兜底
3. 消息对象的 `__dict__` 含 DDS 的 `SampleInfo`（不是 IDL 字段）→ `json.dump` 报
   `Object of type SampleInfo is not JSON serializable` → **按话题白名单提取字段**
4. XML 里 `<Interfaces><NetworkInterface name="auto"/>` 与 `<General><Ports>` 会让
   `DomainParticipant` 初始化直接 `DDS_RETCODE_ERROR`（该版本不接受）；
   `<LeaseDuration>` 必须放 `<Discovery>`（放 `<Internal>` 只告警）

## 标准拓扑：DDS 采集层 + 零依赖展示层（解耦）
```
各端节点(dds-venv) --DDS--> 桥(dds-venv) --JSON 落盘--> Web UI / APP(系统 python, 零依赖)
```
**为什么要桥**：DDS 绑定只装在 venv 里，而展示端(标准库 http.server 等)不该被 DDS 依赖绑架。
桥只做一件事：订阅 → 按节点名聚合「每节点只留最新」→ 写一个 JSON（带 `recv_ts`/`age_s`/`stale`）。
UI 读 JSON。**两端互不污染，任一端可单独重启。**

## 验证纪律（不验就是"看起来有、实际没通"）
1. **先自检栈**：同进程 pub → sub 往返（`scripts/dds_pubsub_selftest.py`）
2. **等配对再发**：DDS 发现是**异步**的，刚建 writer 立刻发，消息会丢给"还没发现"的 reader
   → 发前 `wait_for_match(topic, n, timeout)`
3. **端到端双进程验**：A 进程发、B 进程收，**打印收到的实际值**（不是打印"已发送"）
4. **新鲜度必须显示**：UI 上每个节点带 `age_s` 与 `stale`（超时未更新 → 明确标"停 X 秒"），
   否则读者会把几小时前的旧值当成现在
5. 诊断 route/模式类参数时：**发布与订阅的配置必须一致**，否则测的不是真实行为

## 数据质量: 告警必须判**值**, 不判心跳

只统计 QoS/频率/丢包/配对数的"告警"本质是心跳监视: 总线安静时表里空着,
于是"真的没故障"和"根本没接上"长得一模一样。真告警要面向**物理量**:

```
超上限 / 低于下限   声明量程 (signal meta → 参数中心); 无声明时按物理规律兜底
物理规律           概率/比例∈[0,1] · 百分比≤100 · 质量/刚度/阻尼≥0 · 温度≥-273.15°C ·
                  压力≥0 · 角度|x|≤720 · 速度|x|≤1000
数值有效性         NaN / inf / 非数值 —— **只对实测数值**; 占位/信封行与 "—" 属于"无实测",
                  不是"非数值故障", 必须在喂判据前剔除
单位               有值无单位 ⇒ warn (物理量不许裸数; 推断单位要加 * 标明)
跳变               相邻帧 Δ > 量程×10 或 >1e6 ⇒ warn (多为单位错/串帧)
```

- 告警事件要带 `rule` id + **实际值/限值/依据** (`range_high: 999 > 720 deg (物理规律)`),
  "越界"两个字不构成告警; 级别只留 fail / warn / info。
- 空告警表必须显式输出一行 info 列出判据清单, 否则用户无法分辨"无告警"与"未接入";
  计数只算 fail/warn。
- **验证靠注入越界帧**, 不是靠页面能打开: 造 `{grasp_prob:1.4, joint1_deg:999}` 必须出两条 fail,
  正常帧必须零告警 (不造假警)。同一条判据所有入口共用一份 `quality.py`, 否则一个页面改了另一个还是旧逻辑。
- 覆盖缺口如实报: 端口信号还是占位 (0 单位/0 量程) 时只能靠物理规律 —— 要按设计量程报警,
  先在节点模块里声明 `SIGNALS`, 别把推断讲成设计判据。

界面侧的落地规则 (Trace 一行一个信号带 Unit/Phys、空表 info 行、页签计数) 见 `zmax-console` 技能中
数据空间那份参考的 §9。

## 跨公网额外事项
- 安全组/防火墙：未固定端口时需放行 **UDP 动态端口段**；若现场只能开固定端口，
  该版本的 `Ports` 配置不可用 → 需换实现（Fast DDS）或升级版本，**别硬凑**
- 跨公网心跳/租约放松（高延迟下避免误判掉线）
- 公网暴露面：只允许指定来源访问（见 `http-relay-service` 的 IP 白名单章节）

## 全局数据空间发布守护 (2026-09-26 实测 16/16 通过)

**形态**: 一个常驻守护把**所有真实数据源**接上 DDS, 由**遥测模式**开关控制 (老倪口径: topic 只用于测试/标定/诊断, 量产关闭)。

```
模式文件 ~/.zmax_telemetry_mode   (env ZMAX_TELEMETRY > 运行时 > 文件 > prod)
prod=空 · diag=[hw_state,heartbeat,ss_infer,train_prog,ss_diag] · calib=+ss_state,ss_action,ss_calib
test/dev=全量 14 话题
守护 `tools/dds/ss_daemon.py` (仓库根; 早期副本 `/home/ubuntu/zmax_dds_ss_daemon.py` 已不作为执行体)
· service zmax-dds-ss.service (User=ubuntu) · 类型真源 `dds/ss_types.py` + `dds/zmax_node.py` (TOPICS+QoS)
取证 /home/ubuntu/zmax_dds_ss_verify.py  (四档 × 话题 × 真值, 16 条断言)
真源 /home/ubuntu/zmax_dds/{ss_types.py 9 类型 · zmax_node.py TOPICS+QoS} · 仓库镜像 dds/
```
真实源映射 (全只读): ss_state←真机 tap `~/zmax_ss_remote/state_*.jsonl`(tcp/jpos/gripper/prod_stage) ·
ss_action←`proposal_*.jsonl`(推理服务对真机帧的 6 关节输出) · ss_infer←`127.0.0.1:8790/health` ·
ss_calib←**多候选目录**找标定 json (handeye/real_cam_calib/align/gate) · ss_diag←延时/帧龄/服务健康/吞吐 ·
ss_test←最近 `reports/verify_*.json` 的 passed/total。

### 全局守护专属坑 (全部实测踩过)
| 坑 | 症状 | 修法 |
|---|---|---|
| **类型字段不能想当然** | `SSAction.__init__() got an unexpected keyword argument 'note'` → tick 抛异常 → **它后面的话题全都不发**(calib/test 假失败) | 写前 `grep -n '^    [a-z_]* *:' ss_types.py` 核对字段; 元信息塞已有字段(如 gate_reason) |
| **BEST_EFFORT 首发必丢** | beat 话题(ss_state/ss_action)只发一次 → 订阅端 0 条; state 话题(RELIABLE+TRANSIENT_LOCAL)却收得到 | 每个允许话题**每轮都发**(别低频话题每 5 轮才发); 取证窗口 ≥20s |
| **prod 必须真零开销** | 量产机不该装 cyclonedds/开端口 | prod 分支在 `ensure_node()` **之前** return, 连 import 都不发生; 日志只留一行"允许 0 话题" |
| **负帧龄必须拒发** | 源停了还在发旧值 = 假数据 | 源 mtime 龄 >5s 不发状态/动作, 只发 `ss_diag(kind=frame_age, level=warn)` |
| **多检出/多目录** | 路径单写 → 检出切分支后标定文件"消失", 通道静默空转 | 源/报告/标定路径给**候选列表**遍历 |
| **root 写仓库文件** | 守护以 root 跑 → `reports/*.json` 变 root 属主, 用户态工具写不动 | systemd 加 `User=ubuntu` |

**判据 (必须四档全测)**: prod 订阅端 0 条且守护无参与者 · diag 收到 ss_diag/ss_infer 且值 ≠ -1 且**裁剪掉** ss_state/ss_calib · calib 收到 ss_calib(来自真文件)+ss_state · test 收到 ss_state(dim>0 且 pos≠-1)+ss_action(6 关节)+ss_test。

### 加一个新遥测话题: 五处登记, 漏一处就静默不发
顺序固定 (全是"登记表", 漏一处 = `allowed(topic)` 为假或 writer 建不起来, 表现是订阅端 0 条而不是报错):
1. `dds/ss_types.py` — `@dataclass class SSxxx(IdlStruct, typename="zmax::SSxxx")`; **字段只加不改成必填**, 字符串字段用内置 `str`
2. `dds/zmax_node.py` — import 该类型 + `_SS_TOPICS["ss_xxx"] = SSxxx` + `QOS_CLASS["ss_xxx"]`
   (状态型/latch 选 `state`, 高频流选 `beat`; 状态型让新订阅者立刻拿到最新一份)
3. `tools/dds/ss_daemon.py` — `MODE_TOPICS` **三档都要加** (diag/calib/test) + `read_xxx()` (只读真源, 不猜不编)
   + `pub_xxx()` (字段写前先 `grep -n '^    [a-z_]* *:' ss_types.py` 核对) + tick/线程里调用
4. `src/lerobot/dataspace/topics.py` — `TOPICS` 条目 (type/rate_hz/qos/producer/modes/key_fields/quality/provenance)
   + `MODE_TOPICS` + `PRODUCERS[守护]["publishes"]`
5. `tools/gui/zmax_telemetry.py::MODE_TOPICS` — 控制台读侧的同一张表 (不登记则控制台/数据空间页看不到)
验证: 重启 `zmax-dds-ss` 后 `--status` 应把新话题列进 allowed_topics; 再跑订阅脚本实测。

### 周期型话题: **别挂在主 tick 上, 开专用节拍线程**
- 实测主 tick 一次耗时 **17~26s** (read_state/read_calibs/services_health 都在里面, 远端读很慢) ⇒
  写在 tick 里的 "5s 门控" 实际退化成 ~20s (实测相邻两条间隔 21.0s), 用户看到的就是"周期不对"。
- 修法: `threading.Thread(target=self._cfg_thread, daemon=True)` + `Event.wait(max(0.05, period - 耗时))`,
  run() 退出时 `_stop.set()`; `--once` 那条单独直接发一次。改完实测相邻 ts 间隔 5.0s×4 ✓
- 订阅脚本必须打印**相邻 ts 间隔**(不能只报条数), 并去重: latch/state 型话题会把同一条重复给新样本 ⇒ 只认新 ts。
- 载荷口径: 只发用户要的那一件事 (例: 配置**名称**串), **不塞路径/哈希/计数**; 另带一个 `loaded_at` 供判帧龄,
  源头记录陈旧时在 `note` 里**写明陈旧多少分钟**(不拿旧记录当现状), 而不是默默发旧值。

### 🔴 给已有守护加第二/第三条节拍线程: 两个并发缺陷会立刻发作
多一个发布线程 = 多一个"并发跑"的 tick, 下面两条**必然**出现 (实测都在首轮/重启后):
| 现象 | 机理 | 修法 |
|---|---|---|
| 首轮 `ModuleNotFoundError: No module named 'ss_types'` 或 `KeyError: 'cyclonedds'` | 节拍线程比主线程的 `sys.path.insert(DDS_DIR)` / `import cyclonedds` 先跑一轮 ⇒ 撞上半成品模块 | 文件头部 (stdlib import 之后) **模块级**插一次 `sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))`; 每个节拍线程开跑前先 `while self.node is None and not self._stop.is_set(): self._stop.wait(0.1)` (上限 ~10s) 再发第一帧 |
| `tick 异常: dictionary changed size during iteration` | `publish()` 会写 `self.sent[topic]=...`, 而主 tick 同时在 `for t, c in self.sent.items()` 里遍历 ⇒ 并发改写 | 遍历一律取**快照**: `list(self.sent.items())` / `sorted(list(self.sent.keys()))` |
两条都**不报错退出**, 只是丢帧 + 刷告警, 最容易被当成"网络抖动"放过 ⇒ 加完线程的第一次验证必须**翻守护日志**找这两行。
判据: 重启守护后日志里"允许 N 话题"的 N 必须比你加线程前**多出**新话题 (不涨 = 登记表漏了)。

## 话题名要落库成注册表（别只在运行时拼字符串）

**症状**: 话题名是 `"<prefix>.<node>.<port>"` 现场拼出来的, 磁盘上不存在 ⇒ 监控/CI/DDS 排查
拿不到全量话题清单, 改个命名前缀没人知道会打断谁。

**规则**
1. 话题名由**工程源**(节点/端口/连线)派生, 但必须落成注册表: 一行 = (project, node, port, dir, topic, qos, enabled),
   带唯一索引。工程文件内容 sha256 也落库 (project 行), 作为“库是否同源”的判据。
2. 加载: **库优先 + sha 守卫** —— sha 一致就从库读节点/端口/连线; 不一致就解析源文件并**回写库**
   (绝不拿过期库跑工程)。强制模式 `source=json|db` 保留给对照与 CI。
3. 运行时不用拼, 用注册表: 总线挂一个 `topic_map {(node,port): topic}`, 发布/订阅都查它,
   查不到才回落派生式 —— 否则“只改库”永远不生效, 注册表就退化成缓存。
4. 新表用 `CREATE TABLE IF NOT EXISTS` + 按 project 建索引; 抓快照/改副本要改临时文件, 别动真源。

**判据 (缺一就不算真源)**
- 改注册表里**一行**话题名 → 重新 load → 发布/订阅端立刻用新名; 改回 → 复原。
- 源文件改过 → sha 变 → 判过期并自动回写; 再 load 直接认库。
- 库读回的节点/端口 == 源文件解析结果 (逐节点比对), 两种 source 模式节点集合一致。

细节 (表结构/加载路径/CLI/七项判据) 见 `references/topic-registry-and-loading.md`。

## topic 的 type 必须是**数据语义**, 不是信封名 (2026-10-17 老倪现场纠正)

**症状**: 信号表/数据空间里 113 条报文的 Type 全叫 `zmax::SSNodePort` —— 那是 DDS 信封
(topic/ts/json 三字段), 与数据是什么毫无关系。老倪原话:「type 太随意…例如前馈加速器
你的 topic 类型是 SSNodePort, 这根本看不出有什么含义」, 并要求「与主要发送 Tx 节点关联」。

**真根因**: 类型字符串在**消费端写死** (本次是 busdb 生成报文处 + 数据空间表各一处), 与工程
结构脱钩 ⇒ 所有话题自然长同一个名字。改 UI 文案没用, 必须把类型做成**从工程派生的注册表**。

**做法** (可照抄)
1. 生成器 `tools/gen_topic_types.py` 读画布 (节点/端口/连线) + 节点模块的 `PORT_LABELS`,
   产出真源 `config/platform/dds_topic_types.json` (node → outs/ins → type/cn/consumers)。
2. 命名口径: 出口 = 主 Tx 节点语义 (`ssff.out2 → zmax::FeedforwardAction`); 一个节点多出口
   → `Stem2/Stem3` (有 PORT_LABELS 用语义词); 入口 = **唯一上游出口的类型** (同一份数据不另起名),
   多上游 fan-in 才用 `<Stem>In` 并把生产者清单记进 JSON。
3. 运行时模块 `middleware/topic_types.py` (mtime 热加载) 供 bus/DB/UI 共用; `mw_topic` 加 `type` 列,
   `db.sync()` 写入 —— 老库要 `ALTER TABLE` 补列, 且 **INSERT 必须写列名**
   (ALTER 加的列在表末尾, `INSERT INTO t VALUES(8 个)` 会把类型塞进 qos, 实测踩过)。
4. UI 侧仍以注册表为准: busdb.json 是快照, 可能还是旧类型 ⇒ 渲染时 `type = registry or snapshot`。
   非 `ss.node.*` 形态的话题 (heartbeat 等) 不要硬套注册表, **保留它自己声明的类型**,
   否则会把已知类型降级成 `Unknown` (本次 44 条)。
5. 🔴 **入口类型只能按连线解析**: 用 `db.links()` 的 `(f, f_port) → (t, t_port)` 取上游那一个
   **具体出口**的类型。只看节点级 `from` 列表 (丢失端口) 时, 多出口节点的下游会被判成"多上游语义不同"
   ⇒ 生成器狂报 fan-in, 而现场其实是一条干净的直连。生成器与审计脚本必须走**同一条**解析路径,
   两套各自算就会互相判失败 (本次先出现一波假的 33 条 fan-in 报错)。
6. 审计里比上游类型用 `w == u or w.startswith(u + ".")`: 只写前缀会漏掉"恰好等于"的情况,
   表现为"多上游 0 种"满屏报错; 只看前缀又把 `ss_a.out1` 与 `ss_a.out10` 混淆。

**判据** `tools/verify_topic_types.py` (6 项, 全绿才算完): 覆盖 (每个端口都有类型) · 出口类型唯一主 Tx ·
入口 == 上游 · 库与注册表逐条一致 · 零 `SSNodePort` · 命名 `^zmax::[A-Z][A-Za-z0-9]*$`。
改画布/连线后必须重跑生成器再验, 否则注册表过期 (加 `--check` 进 CI)。

## Signal 列不能空: 话题 → 信号清单要按证据分级加载

**症状**: Trace/信号表只有 Signal 名字却没内容, 或只显示有实时流量的少数话题 —— 老倪原话
「signal列的信号呢? 这些信号, 是每个 topic 的 signal 哪里去了?」/「L1~L5 层所有的 topic 的所有
信号, 都要加载」。根因: 端口 `mw_signal` 里 113 条全是占位 `value`(端口未声明), 而 UI 只渲染
live.json 里有流量的那 24 个话题 ⇒ 看起来"信号很少"。

**做法**: 单独一层 `middleware/signals.py`, 一个 `signals_of(topic)` 按证据强弱合并四级:
```
① 实测   live/busdb/trace.jsonl 里真实出现过的载荷字段 (程序真发过)
② 声明   工程库 mw_signal (排除端口占位 value)
③ 端口标签/实现  画布 params._port_labels 的英文标识; 从实现文件抽 return 字典的字符串键
                (单输出=端口级; 多输出归属不明 ⇒ 标 impl_node 节点级, 不假装精确)
④ 上游继承  入口 topic 按 mw_link (f,f_port)→(t,t_port) 继承上游出口信号, fan-in 取并集
⑤ 信封兜底  仍无证据的节点端口列 DDS 信封真字段 topic/ts/json, 不硬造 payload 名字
```
UI 侧同时要改**话题集合**: Trace 不能只遍历 live.json, 必须并入工程库全部话题 (含入口),
否则"没流量就等于不存在"。实测 273 话题 / 1768 信号行 / 填充 0.10s。

**判据** `tools/verify_signal_coverage.py`: 话题总数==工程库 · 每层都有 · 0 个只剩占位 ·
信号数≥1000 · 四级来源分级 · 中文名≤5 · 英文名是合法程序变量 · 入口有上游继承。
反模式: 静态抽取时把实现里**所有** dict 键都收进来(会把 path/size/mtime 等无关键混进来) ——
只认 `return {...}` 与惯用返回变量, 并保留 src 让用户能追溯。

## 信号名必须是语义名, 不是端口 id (`out1` / `in1`)

**症状**: Trace / 信号表的 Signal 列写 `out1`、`in1` —— 看不出这条线运的是什么。
**真根因**: 端口名是画布的机械名; 取名函数对"未声明字段"的端口**原样返回端口 id**。

**做法(一处收口, 三个窗口同时生效)**
1. `middleware/signal_en.py`: 加 `TYPE_SIGNAL_EN`(类型→短名: `MotionPlan→plan`、`PlanIn→plan_in`、
   `RobotActionIn→action_in`、`SceneUnderstanding→scene`、`OpticalInspection→aoi` …) +
   `type_signal_name()`(表里没有则 CamelCase→snake_case 兜底) + `port_signal(field, mtype)`
   (只对 `^(in|out)(\d+)$` 生效; 同一类型多条入口按序号区分 `plan_in` / `plan_in_2`, 不编随机后缀)。
2. `en_of_key(prefix, field, mtype=None)` / `en_of(field, mtype=None)` 透传类型; 类型真源 = `mw_topic.type`
   (`attribution.type_of_topic(topic)`), **topic 查不到时用行自带的 `type` 兜底**, 否则那几行仍是端口 id。
3. 渲染前**一次性**改名(数据空间/信号表/曲线名共用同一函数), 原始端口名留在 `raw`/tooltip 可追溯。
4. 判据 `tools/verify_signal_names.py`: 全端口 0 条裸 `^(in|out)\d+$` · Trace 每行 Signal 都不是裸端口 ·
   抽查关键口 → 目标短名(实测 272 端口 0 裸名 · Trace 413 行 0 裸名)。

**坑**
- 改名循环别复用外层 `for r, x in enumerate(rows)` 的 `x`: 内层 `for x in rows` 会把 x 覆盖成最后一行,
  整表每行渲染成同一行内容(实测 413 行全变 `out1`)。用独立变量名, 且放在渲染循环**之前**。
- 端口正则必须两个捕获组 `^(in|out)(\d+)$`; 只写一个组会在取序号时抛异常并被兜底吞掉, 静默回落成原名。
- 同一话题类型在多个入口重复出现是常态 ⇒ 序号后缀要可预测(第 1 个裸名, 其余 `_2/_3`)。

## 显示层"不动"先查 publisher 配对, 别先调刷新率

**症状**: 用户说数据/信号一直不动, 要求"实时"。先别改 Timer 间隔 —— 先证明总线在发。

```bash
# 桥/探针产物的三列就是诊断结论
python -c "import json;d=json.load(open('…/live.json'));\
print({k:(v.get('hz'),v.get('matched_pubs'),bool(v.get('fields'))) for k,v in d['topics'].items()})"
journalctl -u <bridge-unit> -n 20 | grep -E '0 条|发布端'
```
`matched_pubs == 0` + `fields` 空 ⇒ **发布端没配上** (或 mode=prod 允许 0 话题), 与 UI 刷新无关;
这时把 1.5s 改成 0.8s 只是让空白表刷新得更快。

**两个窗口必须同源时, 用共享 provider, 不要各自采集**: 如果另一个窗口 (曲线/信号分析) 已经在读
本机真值文件并且是活的, 就让新窗口读**同一批文件** (`middleware/live_signals.py` 之类 0.25s 缓存,
带 `ts/age_s`), 按话题覆盖字段; 两边是同一拍数据的两个视图, 数值天然相等, 不存在漂移。
判据: 两边读的文件路径逐一相同 · provider 与文件逐信号相等 · 1.3s 内 ≥10 个信号在变 · 帧龄 <3s。

**边界要说清**: 换文件源只让**显示**实时, DDS 若仍 0 发布者, 要单独查 daemon 话题登记/配对
(单播配置、mode、QoS 兼容性), 不能把"显示动了"当成"DDS 通了"。

## Pitfalls 汇总
```
✗ 多网卡下不配单播 → 发得出去收不到（最高频, 且日志完全正常, 极易误判成"代码逻辑没问题"）
✗ 建 writer 后立刻 write → 首条消息丢（发现未完成）
✗ json.dump(msg.__dict__) → SampleInfo 不可序列化
✗ 把"测不到"写成 0 → 下游把缺数据当零负载
✗ 只在同一进程自测就宣布"两端通了" → 必须双进程 + 双机
✗ 加节拍线程后不翻守护日志 → 首轮 import 竞态 / self.sent 并发改写被漏掉(丢帧不报错)
✗ 手改 .vscode/launch.json 或画布 JSON 而不改生成器 → 下次"打开 VSCode"/保存画布被整体重写抹掉
✗ 状态类话题不用 TRANSIENT_LOCAL → 订阅者后上线要干等下一个周期
✗ 把 DDS 装进业务 venv → 依赖互相绑架; 用独立 venv + JSON 桥解耦
✗ 显示不动就去调刷新 Timer → 真因多是 matched_pubs=0 / mode 允许 0 话题, 先查发布端
✗ 占位/"—" 行喂给物理判据 → 一次刷出上千条假 fail, 真告警被淹没
```

## 相关文件
- `references/topic-registry-and-loading.md` — 话题注册表 + 库优先加载 (表结构/sha 守卫/CLI/判据)
- `references/cyclonedds-python-api-notes.md` — API 细节与可抄代码
- `templates/cyclonedds_unicast.xml` — 实测可用的单播/跨网配置（含"勿回退"注释）
- `scripts/dds_pubsub_selftest.py` — 同进程 pub→sub 自检
