---
name: node-single-step-debug
description: Use when 节点要能单步调试或判据因活真源时红时绿。
---

# 节点单步调试 (真函数 + 真源 + 不变量) 与冻源判据

## 何时用
- 用户说“这些节点的代码 review 一下, 要能 debug、能代码单步执行、我要看到实际的代码编写”。
- 你写的判据/取证同一份代码**时红时绿**（尤其输入是 `ss_live/*.json` 这类被常驻服务每帧重写的真源）。

## 1b. 键名与真体不符 = 假接入: 留痕, 不偷改
- 节点名可能名不副实: 例 `ssdec` 名写「Flow-Matching Action Head (DiT)」, 实绑纯 MLP
  (`state_space_action_head.py`, 无 DiT/无流匹配/无权重); 真 DiT 类 `action_head.py:205
  SmolVLALewActionHead` 无任何节点引用。
- 处置三步: (1) 把**真身**也加进单步清单, 三环节真跑它 (参数数/形状/耗时都打出来);
  (2) 输出/JSON/不变量里写清「画布 X 绑 A, 真身 B 未被任何节点引用」;
  (3) 要改真链路 (节点改指真身) 先请示, 不自己接。
- 判据同时卡两件: 真身可跑 + 诚实标注出现在输出里。

## 1c. 三环节不是到处都成立
- 先核三环节是否真可分离: `ManifoldEngine` 有 (project · gradient_flow · navigate),
  但 `ContactManifold`/`PerformanceManifold` 只有 decompose/evaluate (投影+度量融合, 无导航)。
  不得为凑三环节硬编一步 —— 输出里标明那一步的真来源。

## 1. 单步调试器三条铁律
1. **每步 = 节点真正在跑的那个函数**（同名同文件），不另写一套仿制实现。先定位
   “画布薄壳入口 file:line → 算法真体 file:line”，再按环节（如 投影→度量→导航→反馈）切步。
2. **输入取真源**（轨迹落盘 / 引擎落盘 / 权重 npz），取不到就如实报“未测/未算”，不填 0 不编数。
3. **每步打印 输入→输出→真源→耗时**，收尾跑**不变量自检**（‖p‖=1 · 切空间正交 · 沿 −∇ 下降 ·
   两处重算逐位相等）。自检不过要报红，不要吞。

命令面：`--list`（任何档位可用）· `--node X --step`（回车走一步）· `--pdb`（`pdb.set_trace()`，兼容
`ZMAX_DEBUG_BREAK=1`）· `--src`（打印每环节绝对路径+行号，`code -g file:line` 直接断点）· `--all --json`。
档位门：**深调试只在调试档**（如 550B `dev_profile.vscode_debug`），其它档位跑 `--trace` 要真拦（exit≠0）。

## 1d. 断点不命中: 按"能不能重新绑定"分四类查 (2026-10-29 一次性踩全)
排查顺序固定, 每类都有实测判据, 不要凭感觉改:
1. **def 签名行 / docstring 行 / return 行都不要打断点**。这三类都不是可执行语句:
   `def step(self, ...` 在 pdb 里报 `*** Blank or comment` 或不触发; `return rec` 被 CPython
   和上一行合进同一 line table 也容易漏。实测 manifold_engine.py: 1186(def) 不进、1188(docstring)
   不进、1200(self._evolve) 能停、1302(self.history.append) 能停、1303(return rec) 不停。
   **断函数体第一条真实语句**, 用 `co_firstlineno` 只能拿到 def 行, 要再往下找。
5. **缓存/队列会让代码看起来"没被执行"**。例: SmolVLA+LEW 的 predict_action 只在
   `select_action` 的动作队列空时才跑 (modeling_smolvla_lew.py:537 `if len(self._queues[ACTION])==0`),
   `n_action_steps=7` ⇒ 一次推理管 7 拍, 之后 6 拍走 popleft。断点像"永远不进"。
   判据: 断在 select_action 入口看 `len(self._queues[ACTION])`; 要每拍真推理就清队列
   (`SS_L3_NO_CACHE=1`)。同类还有引擎轨迹缓存 `_ss_ensure_trace(force=False)`。
2. **模块必须 spec_from_file_location + 注册 sys.modules**。`exec(compile())` 造的模块
   `__spec__/__loader__` 都是 None: 首次按 co_filename 能绑, **取消断点再添加就静默失效**
   (pydevd 要按 loader 重新定位文件)。判据: `mod.__spec__ is not None and mod.__name__ in sys.modules`。
3. **这个 debugpy 版本没有编译 frame eval** (`_pydevd_frame_eval/*.so` 为空 ⇒
   PYDEVD_USE_FRAME_EVAL 只能 NO) ⇒ 对**已加载**模块运行时加断点无效。要命中的话让模块
   重新编译: 运行前清 `library._SS_MODS` + sys.modules 里的 `state_space.*`/`ss_real.*`。
4. **代码到底跑没跑, 用记账文件判定**, 不要用断点判定。在疑似被调用的函数首行 append
   一行 (时间/pid/tag) 到 `zmax_data/ss_live/*.log`, 跑一次看有没有新增。
   另有两条路径陷阱: 路径上溯层数算错(execution.py 在 state_space/ 下要 **6** 层到仓库根,
   nodes/ 下只要 5 层) + `except: pass` 会把"写日志失败"伪装成"代码没执行"。

## 1e. GUI 里 breakpoint() 会冻死整个界面
停住时 Qt 事件循环停转 ⇒ 画布点不动、新断点也点不了 (py-spy 现场:
`wait → _do_wait_suspend (pydevd.py:2268)`)。所以: 内置断点默认**只记录不停**,
要停必须显式 (文件开关 / ZMAX_DEBUG_BREAK); 要看变量用命令行 pdb 通道
(`python -m pdb -c "b <file>:<line>" -c c tools/dbg_actuator.py <节点id>`), GUI 不受影响。

## 2. 坑（都踩过）
- **参考方向不同源 ⇒ 假偏差**：自由空间段的“误差方向”是 `阶段目标−末端`，拿“工件头−孔位”当参考会把
  cos≈1.0 算成 cos≈0.56。参考必须**照抄被校函数的内部规则**（同一 `_error()`/同一行）。
- **同一物理量两套键名**（`Vp` vs `V_p`）：消费侧各取一个就各算一套 ⇒ 发现即统一（保留别名，同一份数）。
- **前置条件未设时静默给 0**：如 `goal_point=None` ⇒ 势与梯度恒 0，调用方分不清“已到目标”与“没设目标”。
  改成显式标记（`no_goal`/`note`），数值口径不变。
- **给 C++ 类方法直接赋值会让 PyQt SIGABRT**：要拦截绘制用 `QPainter` **子类**替换模块全局符号。

## 3. 冻源判据（拿活真源做断言的必做）
常驻服务会**每帧重写**真源文件 ⇒ 判据内两次读同一文件可能拿到不同值。顺序不能反：
1. 判据开头把要用的真源 `shutil.copy2` 到 `tempfile.mkdtemp()`，然后**改模块级路径变量**指向快照
   （`mod.LIVE = snap`）——后续所有调用读快照；
2. 要量渲染的先停动画（`timer.stop()` + 相位归零）；
3. 再断言。判据要**连跑 3–8 次全绿**才算稳（曾 6 次里红 2 次）。

## 4. 判据写法小账
- 断言用**真源/真函数复核**：入口 `file:line` 必须命中 `def node_*`；几何量必须逐位等于真算子输出；
  配置实例必须等于配置文件里同一字段。
- 窗口/累计类量写清口径：**末拍值 vs N 拍累计**是两件事，别拿一个验另一个。
- 文档生成器里 `%` 格式化漏参数会写出字面 `%d` —— 加一条“文档数字与真源一致”的判据就能抓到。
