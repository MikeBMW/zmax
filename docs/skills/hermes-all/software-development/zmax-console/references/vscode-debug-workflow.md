# 在 VSCode 里调试 Z-MAX (控制台 / 状态空间引擎 / 六层节点)

触发: 用户问「怎么 debug 状态空间工程 / 控制台 / 引擎」「F5 起不来」「断点不停/不进」, 或要新增调试配置。
真源: 仓库 `.vscode/launch.json` (十几条配置) + `tools/gui/studio.py` 里历次修断点的注释。

## 1. 选哪条配置 (按「要调什么」选, 不是按方便)
| 要调什么 | 配置 | 前提 |
|---|---|---|
| 整机 (画布+引擎同进程) | `🚀 全新调试进程 (studio.py)` (gui-venv311, justMyCode:false) | **先 `systemctl --user stop zmax-studio.service`** (两个实例抢相机/端口/引擎; 调完 `systemctl --user start …` 恢复) |
| 不动正在跑的实例 | `🔌 Attach 现有控制台 (5678)` | **只有带 `ZMAX_DEBUG=1` 起的实例才 listen 5678** (桌面/服务启动默认不开) —— 先 `ss -ltn | grep 5678`, 空 ⇒ attach 不上, 别赖配置 |
| 只调引擎 (日常首选) | `🌀 流形引擎 · 常驻循环 · 单轮取证 (once)` / `🌀 … · 自检 (step 断点必停)` | 常驻那条要**先停常驻服务**, 否则两套引擎抢 DDS/共享内存 |
| 六节点单步 (流形引擎/专家/接触/性能/DiT/加速器) | `tools/node_debug.py` (`--step` 回车单步 · `--pdb` 进源码 · `--src` 打印绝对路径+行号) | 档位门: **只有 550B 允许深调试** (A/C 档 exit=2 拒绝并说明) |
| L4 模型侧 | `🎯 INTACT L4 · policy 层调试` / `🔬 模型侧单步 (INTACT venv)` / `🌍 光模块插拔链` | 见第 4 节跨 venv |
| 配置层 | `🧮 配置导入 · 真源+工程库读` / `--node n_calib_mani` 写回画布节点 | — |

## 2. 断点不停的五条铁律 (按顺序查)
1. **档位 + 勾选**: L4 档必须勾「🤖INTACT 节点执行」或「🧠模型执行」—— 纯演示档走 L4Demo 独立链, 链上没有目标类, 断点当然不命中。
2. **必须 F5 / attach 启动**: 直接 `python studio.py` 跑 = 非调试模式, 断点永不进。
3. **断点打在函数真身首行** (如 `obs = np.asarray(...)`), 不打 `def` 行或 docstring 行。
4. **改码后重启调试会话** (Shift+F5 → F5): 跑着的被调试进程是旧代码, 只保存文件不会生效; 引擎侧每次运行 importlib 重载六层源码, GUI 主进程有缓存。
5. **断点所在模块必须先被这个进程 import 过**: 惰性 import 的模块 (只在某个节点/CLI 执行时才 import) 在启动期不在进程里 ⇒ 断点显示空心/Unbound, 按多少次 F5 都不停。修法 = 在启动流程里**主动预读一次**该模块 (见 `config-import-node.md` 的「启动期预读」), 不是在节点里翻来覆去找。

## 3. 「没执行」vs「绑定失败」分诊
- 先看引擎进度行末尾 `· 前馈 MLP真身 N/守卫 M`: `N>0` 但不停 ⇒ 绑定/位置问题; `N=0` ⇒ 真没执行 (档位/勾选)。
- 硬停开关 (不依赖断点绑定, 用来区分两者): `ZMAX_DEBUG_BREAK=1` (与画布右键同口径)、`SS_FF_BREAK=1` (前馈真身必停, 仅 debugpy 已连接时触发)。
- 不用 VSCode 也能调: `tools/node_debug.py --pdb` 直接进 pdb。
- **绑定失败的根因**: 引擎 `_load()` 若用 `spec_from_file_location` 加载六层模块, debugpy 断点**不绑定**; 现方案 = `exec(compile(src, 绝对路径))` + 注入 `__file__`/`__name__` + 注册 `sys.modules` ⇒ **新加模块必须照这个加载方式**, 否则同样不停。
- 界面全死但鼠标能动能 ⇒ 是断点挂起 (不是死机), 放行或删断点。
- 播放帧数 < 节点数 ⇒ 后排节点永不执行 (历史坑)。

## 4. 跨 venv / 跨进程 (最容易吃亏)
- 控制台 `gui-venv311` · lerobot 工具 `venvs/lerobot-venv` · INTACT 模型 `external/INTACT-JEPA/.venv` (py3.10)。
- **debugpy 只停它自己启动的那个进程**: INTACT 在正式路径上是跨 venv 子进程桥 ⇒ 在 GUI 调试会话里打 INTACT 仓库的断点**永不命中**, 必须换「模型侧单步」那条配置 (in-process Runtime)。
- 真输入不造假: `INTACT_KEEP_INPUT=1` 把 worker 收到的真输入留档到 `reports/intact_last_input.npz`, 单步配置重放它。

## 5. 断点里想看真值 (别猜)
画布每帧喂引擎的 I/O `zmax_data/ss_live/ss_traj_last.json` · 引擎快照 `engine_latest.json` · 权重 `models/manifold_engine.npz`。

## 6. 陷阱
- **画布右键「打开 VSCode」会重写 `.vscode/launch.json`** (模板在 `tools/gui/simulink_module.py::open_in_vscode`): 新增/改配置必须同步改模板, 否则下次右键被抹掉; 已有回归测试 (打桩 Popen 断言配置全在)。
- 节点 → 源码映射: 先 `params.source` + `source_symbol` 定位到符号行; 没写 source 的退回 `tools/gui/node_logic.py` 的映射表。
- 调真机下发链路 (8793 授权 → `l2_cmd.fifo` → l2_daemon → Orin `/move_pose`) 时先用**影子模式** (只算不发, 下发计数=0); 真要动走两步授权, `rt` 之后务必下电。
