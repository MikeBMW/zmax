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
```

## 相关文件
- `references/cyclonedds-python-api-notes.md` — API 细节与可抄代码
- `templates/cyclonedds_unicast.xml` — 实测可用的单播/跨网配置（含"勿回退"注释）
- `scripts/dds_pubsub_selftest.py` — 同进程 pub→sub 自检
