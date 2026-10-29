# 🐞 VSCode 断点"空心"的三类根因 · 路径层数坑

来源: 老倪 2026-10-14「必须能进入这个断点 (config_import.py:142 `db = _read_db(...)`) —— 改」;
2026-10-17 实测复发: 断点仍不停, 根因是路径少一层 dirname (下面第 2 类), 已修。

## 先分清"没执行"和"没绑定"

* 断点**空心/灰环** = 该文件那一刻还没被 import 进进程 (debugpy 不知道有这行) —— **不是**代码没跑到。
* 断点**实心红点但不进** = 路没走到 / 档位开关没勾 (见下面「必停四前提」)。
* 引擎侧进度行 `· 前馈 MLP真身 N/守卫 M`: N=0 ⇒ 没执行; N>0 却不停 ⇒ 绑定问题。

## 根因清单 (每一类都能造成"永远不停")

1. **惰性 import** —— 模块只在某个按钮/节点被点时才 import ⇒ 启动期断点空心, 按多少次运行都不停。
   修法: 把"读真源"这一步**提到启动流程** (studio.py:87-102 那段就是 10-14 为这件事加的,
   调用链 `import_config_files()` → `_read_db()` = config_import.py:142 断点落点)。
2. **路径算错层数 ⇒ 静默失败** (2026-10-17 实际踩到, 停了老倪的验收):
   `studio.py` 在 `<repo>/tools/gui/` 下, 要拿到仓库根需要**三层** dirname。原写法两层 ⇒
   算出 `<repo>/tools/src` (不存在) ⇒ `os.path.isdir()` 为假 ⇒ 没插 `sys.path` ⇒
   `import lerobot...` 抛 `ModuleNotFoundError` ⇒ **被 `except Exception` 吞掉, 只打一行「跳过」** ⇒
   预读从未成功, 那个断点永远是空心。用户看到的就是 `启动期配置真源预读跳过: ModuleNotFoundError("No module named 'lerobot'")`。
   * 一律**实测算一遍**, 不靠眼看:
     `gui-venv311/bin/python -c "import os;print(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath('tools/gui/studio.py')))))"`
   * 同文件里 `_db_file()` / `_zmax_db_path()` 的 DB 路径是三层 —— 对照它们就能发现少一层。
   * **教训 (通用)**: 凡 `except Exception: print("跳过")` 的兜底, 必须配一条"成功时长什么样"的对照判据,
     否则"真失败"与"本来没走到"在日志上无法区分, 会一直骗自己。
3. **模块加载方式让 debugpy 绑不上** —— 用 `importlib.util.spec_from_file_location` 加载、且**不注册 `sys.modules`**
   的模块, debugpy 解析不到 ⇒ 函数真在跑、VSCode 不停。修法: `exec(compile(src, 绝对路径, "exec"))`
   + 注入 `__file__`/`__name__` + `sys.modules[mod_name] = m`。
   * 同一个仓库里可能**两套加载器只有一套修了** (引擎 real 加载器修了, 画布 ▶运行 用的老 `_load` 还是 spec) ⇒
     先 `grep -n "spec_from_file_location\|exec(compile"` 把两处都查一遍, 别只改一处。
   * 判据: 加载后 `模块名 in sys.modules == True` 且 `cls.method.__code__.co_filename` = 真实绝对路径。
4. **方法在装配期被实例属性顶替** —— 断点打在类方法里, 但运行时 `obj.forward` 已被换成另一个函数
   (例: `if os.environ.get("SS_USE_MLP") != "1": self.accel.forward = self.accel.analytic_forward`)
   ⇒ 类方法体一行都不执行, 断点永远不进。
   * 先看**现在到底绑了哪个函数**: `print(getattr(obj, "forward").__qualname__, getattr(obj, "__dict__", {}).get("forward"))`;
     实例 `__dict__` 里有同名键 = 已被顶替, 类方法不是执行体。
   * 同族陷阱: 环境变量只影响**新起的进程** —— 常驻引擎的 `/proc/<pid>/environ` 里没有那个开关,
     就算你在 shell 里 export 也不生效, 必须重启该进程再看。
5. **代码根本不在你调试的那个进程里** —— 常驻引擎/DDS/发布器是独立进程, 断点只对 F5/attach 的那个进程生效。
   * 判据: `pgrep -af "<脚本名>"` 看有没有第二个进程; `grep -l pydevd /proc/<pid>/cmdline` 判断该进程是否在调试会话里。
   * 要么给那个进程 attach, 要么把逻辑跑在被调试进程内 (画布 ▶运行 走进程内路径)。
6. **frozen modules 让 debugpy 定位断点失效** —— 表现是函数**确实被调用**却一次都不停。debugpy 自己会把原因打在 stderr:
   `Debugger warning: It seems that frozen modules are being used, which may make the debugger miss
    breakpoints. Please pass -Xfrozen_modules=off to python to disable frozen modules.`
   Python 3.11 把 importlib 等编成 frozen bytecode, 断点按"文件:行"定位就会漏。修法(launch 配置里):
   `"pythonArgs": ["-X", "frozen_modules=off"]` —— 必须是 `pythonArgs`(Python 扩展的正式字段), 写进 `args` 是传给
   **被调试程序**的, 不生效; 同时加 env `PYDEVD_DISABLE_FILE_VALIDATION=1` 关掉它的文件校验。
   * 排查入口: 调试输出里搜 `frozen modules` —— 有这行就先修它, 别再去怀疑代码。
7. **断点所在行不是可执行语句 / 路径与 `co_filename` 不同源** —— 打在 `def` 行、docstring、纯注释行时,
   调试器**不报错但也不设断点** (pdb 会明确回 `*** Blank or comment`); 用相对路径找不到的, 调试器静默
   当没这个文件。断点一律打在**函数体第一条赋值**上 (如 `a = np.asarray(u, dtype=float).ravel()`),
   路径用绝对路径。动态加载的模块 `co_filename` 就是喂给 `compile()` 的那个绝对路径, 与它逐字比对:
   `m.__file__ == m.Cls.method.__code__.co_filename`。

## 断点必停的四个前提 (全满足才停)

1. 档位 **550B** + 勾「🤖INTACT 节点执行」或「🧠模型执行」(纯演示档走 L4Demo 独立链, 链上没有 Accelerator)
2. 必须 **F5 / attach** 启动 (直接 `python studio.py` = 非调试模式, 断点永不进)
3. 断点打在**函数真身第一行可执行语句** (如 `obs = np.asarray(...)`), 打在 `def` 行 / docstring / 注释行**不报错但不设断点**
   (pdb 的原话是 `*** Blank or comment`)
4. 改码后**重启调试会话** (GUI 主进程缓存旧模块)

## 停在断点上, Call Stack 还在不断变化 (焦点被别的线程抢走)

现象: VSCode 已经停在断点, Call Stack 面板却一直刷新/换帧。不是调试器坏了 ——
debugpy 每收到一次 `stopped` (别的线程也命中同一断点, 或某线程有未捕获异常)
VSCode 就把焦点切到那个线程, 面板显示的是"当前选中线程"的栈。

* 先量: `ls /proc/<pid>/task | wc -l` + 线程名 (`cat /proc/<pid>/task/*/comm`) —— studio 常态 24 线程
  (Qt 事件循环 / `_HwFetcher` 2s 硬件轮询 / 状态灯采样 / 线程池 / DDS)。
* 正解是**让后台线程在调试期不动**:
  1) 定义 `_dbg_attached()`: `debugpy.is_client_connected()` 或 `sys.gettrace() is not None`, 加 `ZMAX_DEBUG_QUIET=1` 强制;
  2) 定时轮询类 QThread (`_HwFetcher` / 状态灯采样) 在调试期**不 start** (渲染定时器保留, UI 行为不变), 打一行「🐞 调试模式: …未启动」;
  3) `threading.excepthook` 接管: 线程内未捕获异常写日志文件, 不抛回解释器 (抛回就会触发 stopped ⇒ 抢焦点)。
  实测 24 → 16 线程后栈定住。
* 循环里的断点 (10Hz/100Hz) 即使只剩一个线程, 按继续 10ms 后又停 —— 用断点右键 **Hit Count = 1**
  或条件 `self.n_calls == 1`, 只停一次, 之后看变量/probe, 别指望"一次停住看几拍"。

## 不依赖 VSCode 的 ground truth: 让 pdb 直接停 (先自己验, 再交付)

IDE 里"到底能不能停"常常被 launch 配置、扩展版本、frozen modules 混在一起看不清。**判定的唯一硬证据是
调试器里真停住并打印出变量**。用 pdb 在**终端**跑一遍, 三分钟就能把"代码没走到"和"断点绑不上"分开 ——
这一步验证完再动 VSCode 侧配置, 否则一轮轮改配置都是在猜。

```bash
cd /home/ubuntu/zmax
# ① 写一个 headless 驱动: 只为了把目标节点/函数跑起来 (不经 GUI)
#    tools/dbg_actuator.py 这类: sys.path 插 src → load_project() → prj.step(only=['ssact'])
# ② 断在函数体第一条赋值, 路径用**绝对路径**
./gui-venv311/bin/python -m pdb \
  -c "b /home/ubuntu/zmax/src/lerobot/policies/left_right/state_space/execution.py:93" \
  -c c -c l -c "p u" -c "p self.last_check" -c q tools/dbg_actuator.py
# 能停的输出长这样 (这才是证据):
#   Breakpoint 1 at .../execution.py:93
#   > execution.py(93)execute()  ->  a = np.asarray(u, dtype=float).ravel()
#   (Pdb) p u  →  array([0., 0., 0., 0.])
# 不设断点/放错行时的输出: *** Blank or comment  /  *** 'xxx' not found
# 程序直接跑完且没有 `> file(line)func()` 行 = 断点没绑上或函数没被调用, 二者都不是"配置问题"能解释的
```

* 交互式用更省事: `-m pdb tools/dbg_actuator.py` 进去后 `b execution.py:93` → `c` → `p u` / `n` / `s` / `c`。
* pdb **不是** debugpy: `debugpy.is_client_connected()` 在 pdb 下为假 ⇒ 代码里那些只认 debugpy 的内置断点不会触发,
  此时靠 pdb 自己的 `b` 就够了。
* 想同时保留"不受 env/调试器影响"的调用留痕: 在节点实现入口 append 一行到 `zmax_data/ss_live/<x>_calls.log`
  (带时间+pid)。有这个文件更新 ⇒ 调用链通, 问题一定在断点侧; 没有 ⇒ 问题在分派侧, 别碰断点配置。

## 宣布"已修好"的证据门槛 (用户会当场核)

* 只有**调试器里真停住 + 打印出变量**才算修好。headless 里劫持 `sys.breakpointhook`、或"按代码推一遍应该会停"
  **都不算**, 拿推断当结论会让用户连着几轮空转, 直接换来"你不要说谎"。
* 交付前自己先跑出一次停住的**调用栈 + `p <变量>` 输出**, 把这两样贴进回复; 只说"改好了/应该能停了"无效。
* 说"已修"前把三件事对齐: 进程启动时间晚于文件 mtime (跑的是新码) · `/proc/<pid>/environ` 里配置真在 · 断点行是可执行语句。

## 取证命令 (照抄)

```bash
cd /home/ubuntu/zmax

# 0) 一切 import/功能自检都用**项目 venv**, 不要用系统 python3 ——
#    grpc / requests / cyclonedds 只在 gui-venv311 里, 系统解释器缺依赖会把"迁移成功"误判成失败
PY=./gui-venv311/bin/python

# 1) 层数算得对不对 —— 必须是 /home/ubuntu/zmax
./gui-venv311/bin/python -c "import os;print(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath('tools/gui/studio.py')))))"

# 2) 直接跑那段预读, 看"成功"长什么样 (成功 = 「📚 启动期配置真源预读: 配置 N 项 …」)
./gui-venv311/bin/python -c "
import sys, importlib
sys.path.insert(0, '/home/ubuntu/zmax/src')
r = importlib.import_module('lerobot.engineering.config_import').import_config_files(verbose=False)
print(len(r.get('files') or []), (r.get('db') or {}).get('exists'), (r.get('task_cfg') or {}).get('active_task'))"

# 3) 硬停开关 (用来区分"没执行"和"没绑定"): ZMAX_DEBUG_BREAK=1 · SS_FF_BREAK=1
```

## 2026-10-17 修复留痕

`tools/gui/studio.py:89` 由两层 dirname 改为三层 (并加注释说明为什么), `py_compile` 通过, 实测预读成功:

```
📚 启动期配置真源预读: 配置 8 项 (总工程文件 · 任务绑定 · 任务配置 · MCD描述 · 参数注册表 ·
模型×工程匹配 · 主参数M能量标定 · 性能指标真源) · 工程库 ✅ 在位 ·
实际任务 TASK-01-FW FW Loading + EEPROM 写/读校验
```

改后要生效必须**重启调试会话** (Shift+F5 → F5); 常驻控制台同样受影响 (unit 里并没有喂 PYTHONPATH ⇒ 同一份代码同一算错)。
