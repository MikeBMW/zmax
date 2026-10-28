# 断点「进不去」的通用诊断 + 启动期读配置唯一依据（老倪）

老倪原话：「必须能进入这个断点，改」——指 `src/lerobot/engineering/config_import.py:142
`db = _read_db(os.path.join(R, DB_REL))`。

## 断点不进的三层排查（按顺序，都有实测证据）
1. **文件没进进程**（最常见）——Python 断点只有在文件被 import 之后才能绑定；否则 VSCode 里是
   **空心圆（Unbound）**，按多少次运行都不会停。判：`grep -rn '<模块名>' 启动路径文件` 是否有及早 import。
   本例：`config_import` 在 studio.py/simulink_module.py 里 **0 处**，只在节点执行时
   `importlib.import_module(...)`（nodes/library.py）——即「懒加载」，而懒加载的前提是**那个节点被执行**。
2. **代码路径没被执行**（即使文件已被 import）——查该函数所在节点/入口是否在本次运行的执行集合里。
   本例：控制台「运行」跑的是实跑链（数据源→L2→L3→L4→L5→流形），**配置导入类节点不在其中**；
   证据 = 节点自带记录 `cfg_loaded_at` 未变 + 节点执行必打的日志行（`📥 配置导入: 唯一依据 8/8 …`）0 次。
3. **进程不对**——你盯的窗口不是挂着调试器的那个进程：`bash tools/studio_ctl.sh status` 会列
   `debug(VSCode F5): <pid>`；断点只在那个 pid 的进程里有效。

## 断点设在**库方法**上时：先列调用点集合，再选入口
三层排查只回答「文件进没进进程 / 这行会不会执行」；库方法还要多问一句**谁调它、在哪个进程调**。
做法：`grep -rn "\.<方法>(" --include=*.py tools/ src/` 把调用点全列出来，按**进程归属**分三类：
- **同进程**（跟着用户 F5 的那个脚本跑）：断点能停。最省事的入口常常是脚本自带的**自检/演示模式**
  —— 自检函数里就会调那个方法（实测 `manifold_engine.py` 的自检直接 `eng.step(X[0], dt=0.01, …)`）⇒
  给库方法配「跑自检」入口，比让用户去别处触发稳。
- **同一程序的另一条链路**（如画布节点执行时调）：断点也能停，但要那个节点真在本次执行集合里
  （同 §排查 2）。
- **独立进程**（常驻服务 / bench 工具 / 定时器）：在你调试的进程里**永远不停**，必须另配 launch 指向那个入口，
  或先停服务再 F5（同时提醒用户：两个发布者会抢同一个 tap/端口）。
- **根本不会走到**：旁路工具可能用别的路径算同一个量（实测真机 10Hz 扭矩总线 `tdrive_bus.py` 走
  `metric_field` 直接算 M·(−∇Φ)，**不调** `ManifoldEngine.step`）⇒ 在那个进程上给该断点下断点是白费。
  判：`grep -n '<模块名>' <那个脚本>`。

回答用户「这句怎么没进断点」时，直接给**调用点文件:行号 + 三种进法**（自检 F5 / 真跑那个节点 /
独立进程另配 launch），不要只说「没执行到」。

### 让用户自己 10 秒定性（写在回复里，别让他等你去查）
在**当前调试会话**的调试控制台（Ctrl+Shift+Y）里粘两行：
```python
import sys; print([k for k in sys.modules if k.endswith("<模块名>")])   # 空 = 文件没进进程(断点空心圆)
import importlib, numpy as np                                            # 非空 = 模块在, 只是没人调
# 再手动调一次目标函数(例: 构造引擎后 step(np.zeros(43))) ⇒ 断点立刻停 = 断点没坏, 真链路没走到
```
配套话术：停 = 断点好着、是链路没到；不停 = 你调的不是这个进程（让他发 VSCode CALL STACK 顶部文件名）。
判断“我现在在调哪个程序/哪个会话”只看 CALL STACK 面板最上面那个文件，别靠猜。

### 「哪里是周期输出」= 先给地址再解释（老倪原话「别绕了」）
问“周期输出在哪”时，先答**哪台服务 / 哪个进程 / 哪份日志**，并**贴一条实况样本**，然后才解释断点为什么进不去。
定位顺序（都实测过）：
```bash
systemctl list-units 'zmax-*' --no-pager --plain   # 常驻单元 (描述里通常写明周期与用途)
systemctl status <unit> | head -4                  # active + 起始时间
systemctl cat <unit> | grep -E 'ExecStart|Description'   # 真跑的是哪个脚本 + 参数
ps -eo pid,etime,cmd | grep <脚本> | grep -v grep  # 实际进程 (debugpy 树里会有多个, 逐个看 --file)
tail -3 /var/log/<log>                            # 抄一条实况给用户
```
- 周期体一眼看完：找 `while …:` / `dt = 1/hz` / `time.sleep(dt - …)` / 节流打印 `n % hz == 0`。
- **先证明“这条链每周期调的是谁”再谈断点**：逐行读周期体里的调用链（本例 10Hz 总线走 `MetricField`/势场，
  不碰 `ManifoldEngine.step`）⇒ 结论是“这个断点在这条链上永远不停”，而不是“断点坏了”。
- 用户期待“每周期都调 X”而实际没有 ⇒ **如实说没有**，并给最小改法选项（照已有周期线程的样子加一条 N 秒线程），
  别把“不存在”讲成“你该去别处找”。

### 用户贴出一整个类/方法，问「断点打在哪里」
直接给**类内位置表**（行号 + 停在那能看什么），而不是泛说“打在关键行”。以流形引擎 `ManifoldEngine` 为例：

| 位置 | 含义 | 能看什么 |
|---|---|---|
| `def step(...)` | 每步入口 | 输入 state、调用参数 |
| `r = self.project(state)` | 编码+投影 | 流形坐标 p/z、confidence、anomaly、编码耗时 |
| `p_new = self._evolve(r["p"], gf["descent"], dt)` | **M 生效点** | `self.M`/`self.inertia` 有没有真用上、梯度多大 |
| `rec = { … }` | 全量可观察量 | M / inertia / momentum / homeostasis —— 与画布、总线看到的数一一对应 |
| `return rec` | 出参 | 调者（节点/自检）真正拿到的记录 |
| `_evolve` 内 `if not inertia or M <= M_EPS` / `a = force / self.M` | 过阻尼(零回归支) / 二阶有惯性 | 走的是旧行为还是有惯性 |
| `set_M()` | M 写入点 | 谁在何时改了 M、返回什么 |

两条硬规则：
1. **高频路径（每步都过）上不用无条件断点** ⇒ 条件断点（例 `self.M > 3.0`）或 **logpoint**（不中断，把
   `self.M, gf["phi"], a[:3]` 打到调试控制台）。
2. 别用这些位置判“没生效”：`__init__`（只在建引擎时进一次）、`save/load`、`latency_report/spec_check` 类只读报表。

### 引擎类真机侧的对口观测点（顺带回答“周期输出在哪”）
- 真机每周期出的是 `zmax-torque-bus.service`（`tools/tdrive_bus.py run --hz 10`）写进
  `/var/log/zmax-torque.log` 的**每秒一行**：
  `[t] ‖T‖=… N·m (raw …/限幅) · Φ=… · ‖∇Φ‖=… · H=…(normal) · x=[…] · rd=True`，
  数据落 `/dev/shm/zmax_torque/torque_<场景>.jsonl` → DDS `zmax/ss_torque`（看实况优先 tail 日志）。
- 真机侧**没有** `ManifoldEngine.step` 的周期调用，也**没有**“每周期重规划”的意图 tick：规划器只在
  控制台仿真/画布节点里按需调。用户要“每周期调意图”= 新需求，按已有周期线程同构加一条 N 秒线程。

## 让断点必进的改法（老倪要的）
把「读配置唯一依据 + 工程库」**提到启动流程**：`tools/gui/studio.py` 顶部「工程状态自恢复」之后加一段
（模块级、GUI 起来之前）：
```python
import importlib as _il_boot
_src_boot = <repo>/src ; sys.path.insert(0, _src_boot)   # 与真实启动同口径
_ci_boot = _il_boot.import_module("lerobot.engineering.config_import")
_cf_boot = _ci_boot.import_config_files(verbose=False)   # ← 这一句执行 config_import.py:142
```
口径：**只读**（不调 write_into_node，启动期不动画布；节点回写仍归主参数节点）；失败不拦启动，
只如实打一行；实测耗时 0.01s（文件缓存命中），启动输出多一行
`📚 启动期配置唯一依据预读: 配置 N 项 (名称清单) · 工程库 ✅ 在位 · 实际任务 TASK-xx <任务名>`
（尾部那截 = `res["task_cfg"]` 里的活跃任务，见下节）。

### 让「用户要看的那个变量」必定可见（同一类要求的通用做法）
用户调试时会直接点名「我就是要看到记录 <业务对象> 的那个变量」。满足它的三条硬要求：
1. **在断点行之前**显式赋成有名字的变量（别让用户「跨过这行再看」）——`task_cfg = read_task_cfg(R, orders)`
   放在 `db = _read_db(...)` 上一行；后面的 `bind` / `tasks` 复用它，别重复读盘。
2. 同一份值要能从三处拿到，别只活在调试器里：函数返回值 `res["task_cfg"]`、CLI 开关
   `python src/lerobot/engineering/config_import.py --task-cfg`（打印 JSON）、启动预读行尾部。
3. **插入行会让断点行号右移** ⇒ 改完主动把新行号告诉用户（本例 142 → 186），否则 VSCode 里旧断点会
   停在别的语句上、用户以为「又进不去了」。

### 「现在在跑哪个任务」的唯一依据与查看点
- 唯一依据 `config/ss_task_binding.json::active_task`；注意 **`tasks` 是 list 不是 dict**
  （`config/tasks/tasks.json::tasks` 也是 list ⇒ `.get("tasks").values()` 会炸）。
- 界面：控制台「⚙️ 配置中心」→ 任务表 → **「活跃」列**（`veh6_config_page._ACT_COL = 12`，
  加列后列序会右移 ⇒ 动表头必须同步 `_ACT_COL`），`★ 活跃` 那行 = 当前任务。
- 另四处：启动预读行尾部、`task_cfg["active_task"]`、`--task-cfg`、`ss_torque` 载荷 identity 的
  `task_id/task_name`。
- ⚠ **同节点内可能有两个不同源的字段**：`n_calib_mani` 里既有 `cfg_snapshot.active_task`（跟着绑定唯一依据走）
  也有旧字段 `m_task`（可能是很久以前写的值）⇒ 报「当前任务」只认绑定唯一依据 / `cfg_snapshot.active_task`，
  发现不一致要**明说哪个是旧的**，不要混着当成一件事。

## 判据（必跑）
`tools/verify_cfg_db_startup.py` —— 4 项：①启动输出有预读行 ②**用 `sys.settrace` 逐行盯
config_import.py，证明启动流程真执行了断点那行**（行号现读文件取，不硬编）③预读只读（画布 sha256 不变 +
去注释后的代码里不出现 write_into_node）④启动无异常。改完 = 4/4 PASS。

### 判据自身的两个坑（我踩过）
- 用文件路径 `spec_from_file_location` 跑 studio.py 的**模块级**必须自己补 sys.path
  （`src`/`tools/gui`/`tools`/repo 根），否则报 `No module named 'version_sync'` —— 那是探针环境问题，
  不是启动真的坏了。
- 「只读」的静态检查要**先去掉注释行**再查函数名：注释里提到 `write_into_node` 会造成假失败。
- 探针结尾 `os._exit(rc)`：控制台模块级会起线程/单例，正常退出会被挂住。

## 相关：给了「必定命中」的 VSCode launch 配置
`.vscode/launch.json` 已加：`🧮 配置导入 · 唯一依据+工程库读 (config_import.py · 断点必停)` /
`🧮 配置导入 · 读+写回画布节点 (--node)`，以及 4 条流形引擎（自检 / --state / --hom-demo / energy --selftest）。
入口是 `src/lerobot/manifold/manifold_engine.py`（`tools/manifold_engine.py` 只在老版本快照里，现仓库没有）。
时间点：这段预读跑在「📌 工程状态自恢复」之后、PyQt5 等重依赖 import 之前 ⇒ `F5` 后终端里那两行相邻打印，
**窗口还没出现就停在断点**（用户视角「一跑就停」）。

### 配 launch 前先验证脚本真的调用那个函数
给「停在 X 行」的调试入口起名之前，先 `grep -n '<模块名>\|<函数名>' <脚本>` 确认调用链：
给 `tools/config_to_M.py` 配的那条曾被我标成「断点会停」，实测它**不经过** `config_import`
⇒ 名字是假的、用户按它调永远不停。确认不了就指向真正调用它的入口（`config_import.py --json/--node`）。

## 别动用户正在用的调试会话（控制台控制脚本的硬规则）
症状：用户 F5 起来后只打印几行「工程状态自恢复」就回到提示符、**没窗口也没报错**——进程是被别人杀了。
机制：`tools/studio_ctl.sh` 的 `pids()` 匹配规则是「cmdline 里同时含本工程 venv 解释器 + `studio.py`」，
而 VSCode/debugpy 起的实例 cmdline 正好也满足（debugpy 的 launcher 夹在中间）⇒ `stop/restart --force`
会把调试会话一起 kill。
规则：
- `pids()` 里加 `if any("debugpy" in a for a in argv): continue`；另设 `dbg()` 只报告不杀；
  `status` 打两行（`running: <pid>` / `debug(VSCode F5): <pid> ← studio_ctl 不管它`）。
- 改控制台代码后要生效，先问用户或让用户 Stop→F5；**不要**用 `restart --force` 替用户重启正在调试的进程。
- 杀进程用脚本、别内联命令；按端口/pid 找，别 `ps | grep 名字`（会匹配到自己）。

## 被调试器暂停的进程仍然「活着」——单实例锁不会释放
编排类脚本（L5 闭环那种）用 **pid 判活**的单实例锁。用户在 VSCode 里撞上未捕获异常时，
进程只是**暂停**在调试器上、并未退出 ⇒ 锁仍被它持有。此时任何 `--run` 重跑都会被闸门拒绝
（返回 3 / `已有编排在跑 (pid … · 阶段 …)`），用户会以为「脚本坏了」。
所以「改完让他重跑」这句话必须配一步操作：先在 VSCode 里 **Stop（Shift+F5）** 那个挂起的调试进程。
现场核对：`ps -p $(python -c "import json;print(json.load(open('<lock文件>'))['pid'])") -o pid,etime,cmd`；
锁文件自己会按 pid 判活自愈——进程真没了，下一次 `--run` 自动接管，不需要手工删锁。

**另一条路：给调试实例一个独立命名空间（优先，别动在役服务）**
常驻服务握着单写入器锁时，F5 跑同一个脚本只会打印「已有写入器在跑 (pid …)」**然后直接退出**
——一次目标函数都没调 ⇒ 断点当然不进（用户视角就是「断点还是没进」）。不要为此停服务，
给脚本加 `--instance <名字>`：实例名非 main 时，**tap 目录 / pid 文件 / 状态文件各自加后缀**
（例 `/dev/shm/<tap>_debug/` · `<pid>_debug.pid` · `<status>_debug.json`），再加 `--no-lock` 可选；
守护只读主实例的 tap ⇒ 调试实例的帧不会当成在役数据发上 DDS。
判据：服务在跑的情况下 F5 该脚本，日志应打印 `实例=debug · tap …_debug` 且周期数在涨。

## 判据结论 ≠ 崩溃（`rc≠0` 被调试器报成"Exception has occurred"）
工具/判据脚本用 `return 1` 表达**业务结论**（0 有效框 / 等确认 / 口径不符）时，末尾写
`raise SystemExit(main())` 会让 VSCode 弹 `Exception has occurred: SystemExit 1` —— 看着像代码报错，
用户就来找你"怎么报错了"。而这是**设计好的结论**，不是异常。
```python
def _finish(rc: int) -> None:      # 交付退出码: 判据结论 ≠ 崩溃
    try:
        sys.stdout.flush(); sys.stderr.flush()   # os._exit 不跑缓冲/atexit ⇒ 必须显式 flush
    except Exception:
        pass
    os._exit(int(rc))               # 退出码语义不变 (CI/脚本仍能判), 但不再抛 SystemExit

if __name__ == "__main__":
    _finish(main())
```
- 只对**顶层交付退出码**这么改; 别把异常吞掉（真异常仍照常抛，调试器该停就停）。
- `os._exit` 会跳过文件缓冲 ⇒ 写盘用 `with` 或临时文件对象（写完即释放者安全）；改成 os._exit 后
  **回读产物**验证完整（实测 record.json 落盘完整）。
- 同一个仓库里几十个工具是这同一种写法 ⇒ 用户报"某工具报错了"时，第一反应查它是**判据结论**还是**真异常**，
  并把这个修改在同类脚本上一起修（本次只修了用户点名的两个，其余按需）。
- 结论行必须自带**为什么**：单行列出逐路结果（哪路 OK/哪路 503、真值帧龄、下游是否停写），
  别只打 `ok=False`——用户拿它当现场报告。

## launch.json / 画布 JSON：只手改生成器，别手改产物
`.vscode/launch.json` 是**生成物**：控制台「打开 VSCode」会用 `tools/gui/simulink_module.py` 里的模板
整体重写它 ⇒ 手加的配置（包括断点必停那几条）下次点击就被抹掉（实测丢过）。
规则：把模板抽成模块级函数（`_vscode_launch_cfg(root)`），控制台调用它、你要补配置也改它；
需要立即生效就 `import` 该函数重新 dump 一遍 json。同理：**画布节点改名/改连线改的是画布唯一依据**
（`data/database/zmax/sources/canvas/state_space_obs.json`，`src/.../flows/*.json` 是软链），
改完必须 `ss_task_bind` 重绑 → `engineering_db.py build` → 两 check（`canvas_level_audit` 真缺口应为 0）；
改动前备份 json，并提醒用户**别在控制台里保存画布**（会用旧视图覆盖）。
