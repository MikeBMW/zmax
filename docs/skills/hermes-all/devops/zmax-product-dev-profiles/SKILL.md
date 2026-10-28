---
name: zmax-product-dev-profiles
description: "Use when 改/查 550A/550B/550C 产品档位或产品开关。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [zmax, product, profiles, 550A, 550B, 550C, topics, shm, vscode]
    related_skills: [zmax-console, state-space-canvas-engineering, dds-messaging]
---

# Z-MAX 三产品开发分工 (550A / 550B / 550C)

## When to Use
- 用户提到 550A/550B/550C 的差异、产品档位、要在某档开关某功能。
- 要新增一个“只对某档生效”的能力 (话题 / 通讯 / 界面 / 算法准入)。
- 现场报“某个功能在产线上不该开”“为什么这台机器不发 topic”。

## 老倪 2026-10-15 定的分工 (原话口径, 不改写)
| 档 | 定位 | 关键开关 |
|---|---|---|
| **550A** | 开发版: 新技能 / 新算法 / 逻辑最多 (允许不稳) | `new_algorithms=on` · `logic_depth=max` · topics=core |
| **550B** | 调试版: 所有 TOPIC 全开 + 最大化 debug + 允许 VSCode 联调 | `topics=all` · `vscode_debug=true` · 信号分析/3D 全开 |
| **550C** | 量产版: 稳定性优先 | 未验证算法**全关**(只放 `verified_algorithms`) · `comm=shm`(**不发序列化 topic**, 共享内存直传) · 信号分析**不开** · 3D 场景**不开** · 只留**远程旁路**(远程运行 + 真机部署) · vscode_debug=false |

## 选档即部署 (chip 点击 = 真动作, 2026-10-21)

老倪: 「左下角选 550C, 则自动切换到 intel 运行部署模式, 显示 intel 硬件信息; 选 550B, 自动打开 vscode,
对应一种 debug 模式, 自动运行单线程模式, 推理如果有 intel 默认就在 intel, 如果没有硬件自动调回 4060;
550A 自动启动 4060 全模型训练模式, 如果算力不足, 启用所有能获得的计算资源」。

⇒ 决策全在 `tools/zmax_compute_mode.py` (唯一口, 零依赖, 可命令行复核):

```bash
./gui-venv311/bin/python tools/zmax_compute_mode.py --show                 # 当前档的决策 (只读)
./gui-venv311/bin/python tools/zmax_compute_mode.py --apply 550C           # 写档+拉隧道+探活
./gui-venv311/bin/python tools/zmax_compute_mode.py --apply 550A --train-steps 2   # 有界验证训练链
```

| 档 | 自动做的事 | 推理落点 | 线程 |
|---|---|---|---|
| 550C | 拉 `zmax-orin-intel-fwd.service` (18800) + 探 intel `/health`; 界面用 edge.hw 显 intel 硬件 | intel (不通则**显式回退** 4060) | 2 |
| 550B | 起 VSCode 状态空间工程 (复用窗口/关 GPU/禁重型扩展) | intel 优先, 无则 4060 | 1 (`ZMAX_SINGLE_THREAD=1`) |
| 550A | 起 `joint_train_all.py --only L4,L3,L2` (独立会话+日志+去重) | 挪 intel 腾卡, 无 intel 共用 4060 | all |

接线三处: `status_panel.switch_profile()` → `_apply_compute_async()` 后台执行 (不冻结界面);
`status_hub.collect_compute()` 把同一次 edge 采集提供给 `policy(edge=...)` → `/status/all.compute`;
tooltip 显示「算力用法 / 推理→哪台+原因 / 训练 / 本次动作」。

铁律:
1. **写档和做事分开**: 写档走 `status_hub.set_profile` (唯一写路径), 起 VSCode/训练/隧道是 `apply()` 的事;
   `apply` 里再调 `set_product` 会先读唯一依据, 同档就不重复写 (否则每次点 chip 多一个 .bak)。
2. **无硬件必须显式回退**: `policy()` 的 `infer.fallback=True` + why 写明原因; 判据可用
   `ZMAX_EDGE_ONLY=1 ZMAX_EDGE_URL=http://127.0.0.1:1/health` 做负控, 三档都要落到 4060。
3. **训练不许重复起**: `train_running()` 查 pid 再决定; 新进程 `start_new_session=True` + 日志落 `reports/profile_550A_train_*.log`,
   stdin=DEVNULL (否则 GUI 线程里会阻塞)。
4. **systemd scope 里的进程 /proc/<pid>/environ 可能读不到** (权限/硬化) ⇒ 验证单线程口径走
   `vscode_launch.launch_env('550B')` 打印实际会传的 env (OMP/MKL/OPENBLAS/TORCH=1), 别拿 /proc 读不到当没设。
5. **550C 的算力在远端**: `hardware_ok()` 对 C 档永远 True (本机只是操作端), intel 通不通看 `compute.intel_online`;
   550A/550B 挂在 intel 上才是真缺口 (判据 ⑤ 用 `ZMAX_HOST_HW=intel` 钉住)。

## 档位↔硬件绑定 (2026-10-21 老倪定稿)

老倪原话: 「550C 的硬件对应 intel, 550A 对应 4060, 550B 对应 vscode; 相当于 550B 是桥梁, 是状态空间工程、
各种 tool 的总配置模式; 550A 是 4060 计算资源的核心载体; 550C 是运行在 intel 上的部署」。

⇒ 三档不是三台机器, 是**三种算力用法**, 硬件绑定写进唯一依据, 不再放在界面里硬编码:

```
唯一依据 products[<档>].hardware = {"key":"4060"|"intel", "label":..., "usage":...}
读取口 tools/zmax_profile.py → hardware(key) / host_hardware() / hardware_ok(key)
         status_hub.profile_hardware(key) / host_hardware()  (界面与 /status/all 共用)
```

| 档 | hardware.key | 角色 | chip |
|---|---|---|---|
| 550A | 4060 | 4060 计算资源核心载体 (训练/新算法) | `550A·4060` |
| 550B | 4060 | **桥梁**: 状态空间工程 / 全 tool / VSCode 标定, 可观察所有硬件 | `550B·4060` |
| 550C | intel | 运行在 intel 上的部署 | `550C·Intel` |

铁律:
1. **active_product 是实例级字段**: 4060 工程机写 550B(或 550A), **intel 上那份唯一依据必须写 550C**。
   把工程机的唯一依据原样拷到 intel 会让 intel 以为自己是 550B —— 拷贝时只改 active_product 一个字面值。
2. **档位与本机硬件不符要显性告警**: `/status/all.profile` 带 `host_hardware/hw_ok/hw_warn`, 不符时 chip 灯转黄
   + fact 前缀 `⚠ 档位≠本机硬件`。曾经的真事故: 4060 上挂着 550C, 界面显示 `550C·Intel` 却是 `topics=none comm=shm`,
   工程机把信号分析/3D/VSCode 全关了还不知道为什么。
3. 判据 `verify_product_dev_profiles.py` ⑤ 段钉住: 唯一依据三档 hardware、读取口取值、本机探测、不符判定自检。
4. intel 端最小集 = `config/platform/zmax_product.json` + `tools/zmax_profile.py` (它没有整个仓库);
   部署命令: `sshpass -p intel scp -J orin <本机json> intel@192.168.23.70:/home/intel/zmax/config/platform/`。
   唯一依据两份会漂移 —— 改完档位记得同步, 并在 intel 上跑 `python3 tools/zmax_profile.py` 回读三行。

## 唯一依据 / 读取口 / 判据 (改任何一条都动这三处)
```
唯一依据   config/platform/zmax_product.json → products[<档>].dev_profile   (人可编·进 git)
读取口 tools/zmax_profile.py  → topics_mode() / comm_mode() / gui_on('signal_analysis'|'scene_3d')
                               / vscode_ok() / remote_bypass_ok() / algo_policy() / algo_allowed(name)
                               / dds_topics_allowed(topics) / summary(档)
判据   tools/verify_product_dev_profiles.py (①唯一依据逐条对上老倪原话 ②读取口三档取值 ③**四处真接线** ④子进程实测)
```
`ZMAX_PRODUCT=550C` 环境变量可**覆盖**当前档做验证 (不碰唯一依据、不动现场)。

## 已接线的四处 (加了新开关就在这里接)
| 开关 | 接在哪 | 行为 |
|---|---|---|
| 信号分析开合 | `tools/gui/studio.py` MonitorModule 建 tab 处 | C 档不建波形页, 给一行说明 + 指向共享内存目录 |
| 3D 场景开合 | `tools/gui/simulink_module.py::open_ss_3d` | C 档拒绝并说明 (不静默) |
| VSCode 联调 | `tools/gui/simulink_module.py::open_in_vscode` | 只有调试档放行 |
| DDS 序列化话题 | `tools/dds/ss_daemon.py::allowed()` | 档位**只能收窄**运行模式的集合: C 档全拒 (走共享内存), A 档核心集, B 档全开 |

## 底部状态带最左侧显示当前档 (2026-10-21 落地, 5.50.750+)

老倪: 「最下面有硬件和模型运行状态指标; 要在最左侧也显示 Intel 或者 4060 这样的字样」→ 补一句
「550C 部署到 intel 上; 550A 在 4060 上开发训练; 550B 对应 VSCode 标定配置模式, 且可以连接观察所有硬件」
⇒ 三档 = 三种算力用法, 状态带最左那颗 chip 就是**当前档**, 点它可换档。

| 档 | chip 文字 | 4 个指标槽 (含义随档变) |
|---|---|---|
| 550A | `550A·4060` | GPU / CPU / 内存 / 磁盘 (本机开发训练) |
| 550B | `550B·标定` | 相机 n/m / 机械臂 / 端侧 2/2 / 栈 (观察全硬件) |
| 550C | `550C·Intel` | NPU 推理ms / CPU / 内存 / 温度 (端侧部署) |

灯色: 青=端侧推理中 · 绿=在线 · 黄=部分掉线 · 灰=不通; chip 右侧 `⟳` = **已写进唯一依据但未重启控制台**。

真接线三处 (改任一处必须同步):
1. `src/lerobot/engineering/status_hub.py`: `collect_profile()` (用 importlib 按路径加载 `tools/zmax_profile.py`, **不复制判档逻辑**)
   + `set_profile(key)` + `collect_cams()` + `collect_orin()` + `collect_edge()`, 全部挂进 `/status/all` (8796)。
2. `tools/gui/status_panel.py`: `modes()` 定义三档的槽, `current()` 取唯一依据, `mousePressEvent` 左 96px → QMenu → `switch_profile()`。
3. 唯一依据 `config/platform/zmax_product.json` —— **只改 active_product 一个字段的字面值** (正则替换 + 回读校验),
   其余字节原样保留; 同时写 `.bak_<ts>` (同秒内重名自动加序号) 与 `~/.zmax/config/product_switch_log.jsonl`。

铁律:
- **换档 ≠ 立即生效**: 各处档位开关多在 import/建界面时读 ⇒ 写盘后 chip 立刻变, 但真能力要**重启控制台**;
  所以界面必须显 `⟳` 并在 tooltip 写明, 不许假装已生效。
- `set_profile` 不许整文件 json.dump 重写 (实测会多一个尾换行/洗格式, 唯一依据进 git 就成噪音) —— 正则改值 + `json.loads` 回读 + `cmp` 验证切回后**逐字节一致**。
- 状态带只做**显示与换档**, 不做推理路由: 哪台算力跑推理仍由各链路自己决定。

验收实测: `ZMAX_PRODUCT` 或改唯一依据后 `/status/all.profile` 三档正确; 渲染三档 chip 分别 `550A·4060 / 550B·标定 / 550C·Intel`,
槽位 `相机 5/6 · 机械臂 通 · 端侧 2/2 · 栈 2/2`; `set_profile('550A') → '550B'` 往返后 `cmp` 逐字节一致; `verify_product_dev_profiles.py` 全过。

## 铁律 (踩过的坑)
1. **档位只能收窄, 不能放宽**: `allowed()` 先按运行模式判, 再用产品档收一道。反过来会把现场能力悄悄放开。
2. **配置写了没人读 = 假接线**: 每加一个开关, 必须落一处**真调用点**并在判据③里 grep 钉住。
3. **读取失败一律按“全开”保障**, 但**必须打印一行** (不许静默变成“无法打开”)。
4. **C 档“未验证算法全关”要有 `verified_algorithms` 名单才站得住**: 名单是老倪签字的地方, 不许自己往里加。
5. **共享内存不是新东西**: 引擎已在写 `/dev/shm/zmax_ss_engine/engine_default.jsonl`; C 档只是关掉 DDS、让信号走这条路。
6. **不要为了让某个档“干净”去删别的档的能力**: 三档是同一套代码的三种配置, 差异只在 `dev_profile`。

## 验收命令
```bash
./gui-venv311/bin/python tools/gen_dev_profiles.py             # 重新写 dev_profile (改完唯一依据后)
./gui-venv311/bin/python tools/verify_product_dev_profiles.py  # 判据 (含子进程实测)
./gui-venv311/bin/python tools/zmax_profile.py 550C           # 一行摘要看某档现在是什么
```
