# 源码分层 + 断点/绘制两类顽固坑

## 一、核心逻辑不许留在 tools/gui（分层归位）

规则：
- 零 Qt 依赖的逻辑 → `src/lerobot/<pkg>/`（engine / serving / ops / features / skills / middleware / perception），画布生成器 → `tools/gen/`。
- `tools/gui/` 只留 GUI 本体 + **≤40 行别名 shim**，老 import 路径必须仍可用：

```python
sys.modules[__name__] = _mod     # 别名，不是复制 ⇒ 模块级全局/类身份共享
```

迁移必查（搬完就炸的四类，全踩过）：
1. `dirname×3(__file__)` / `os.path.join(here,"..","..")` 反推仓库根 → 换成按标记上溯的 `_repo_root()`（同时存在 `src/lerobot` 与 `tools`）。runtime.py 里一次有 9 处。
2. `here/../../dds` 这类相对资源路径：归位后指到 `src/lerobot/dds`，改 `_repo_root()/dds`。
3. `from __future__ import annotations` 必须是首语句：注入 helper 要插在 docstring 之后、`__future__` 之后。
4. 模块级 `sys.path.insert(0, _repo_root())` 会先用到后定义 → helper 必须定义在第一次调用之前（否则 `NameError: name '_repo_root' is not defined`）。

判据：`tools/verify_src_layering.py`（真身存在+shim≤40行 / 旧名 alias 必须解析到登记真身路径，防复制回退 / gui 不许有未登记零 Qt 大块 / 死文件确不在）、`tools/verify_engine_location.py`。

删文件前先三查：字节级重复（`md5sum` 对比，曾发现 `zmax_gui_launch.py` 与 `studio.py` 完全相同 15819 行）、全仓库 0 引用、无字符串动态 import。

## 二、VSCode 断点「进了但 Call Stack 一直跳」

根因不是断点问题：studio 进程实测 24 线程（`_HwFetcher`/`_StatusLightFetcher`/Qt 事件循环/线程池），debugpy 每收到一次其它线程的 stopped（命中断点或线程内未捕获异常）就把焦点切过去。

修法（已落地 studio.py）：
- `_dbg_attached()`：`debugpy.is_client_connected()` 或 `sys.gettrace()`，支持 `ZMAX_DEBUG_QUIET=1` 强制。
- 调试期**不启动** 2s 轮询线程（硬件轮询、状态灯采样），状态灯渲染定时器保留；实测 24 → 16 线程。
- `threading.excepthook` 接管：线程内异常写 `zmax_data/graphic_logs/thread_exc.log`，不抛回解释器（抛回就触发 stopped 抢焦点）。
- 断点只在**被调试的那个进程**生效：引擎常驻进程（`ss_engine_loop.py`）是独立进程，studio 里的断点管不到它；要给引擎 attach 或在 studio 内跑。

## 三、`return self._ff(obs)` 断点永远不进

三个叠因，按顺序查：
1. `SS_USE_MLP != "1"` ⇒ `state_space_sim_real.py` 装配时 `self.accel.forward = self.accel.analytic_forward`，整个 MLP 方法被实例属性替换 ⇒ 该行根本不存在可命中点。查 `/proc/<pid>/environ` 有没有 `SS_USE_MLP`。
2. 跑前馈的进程不是被调试进程（引擎独立进程）。
3. 模块用 `spec_from_file_location` 加载且不进 `sys.modules` ⇒ debugpy 解析不到，函数真跑但不停。修法：`exec(compile(src, 真实绝对路径, "exec"), m.__dict__)` + 注入 `__file__/__name__` + 注册 `sys.modules`（`state_space_sim._load`、`state_space_sim_real._load` 均已改）。

保底证据手段（不依赖调试器）：`SS_FF_BREAK=1` 时 forward 内 `debugpy.breakpoint()` 硬停；每 100 次打一行 `🧠 前馈加速器: MLP 真身执行 #N (域内 x · 守卫 y)` —— 这行不出现就是 MLP 路径没跑，不是断点问题。

## 四、pyqtgraph `PlotDataItem.py → dataRect → np.min` RecursionError

现象是「栈被信号级联压满后死在哪一行」，不是 np.min 自己递归。级联源：刷新时 `setData` / `setYRange` / `linkedViewChanged` 每帧互相触发，paint 又回头 `_getDisplayDataset` 扫数组。

修法（canoe_graphic.py 已落地）：
1. `item.setData(..., skipFiniteCheck=True)` —— 直接去掉 paint 期 np.min 扫数组（报错那行）。
2. `refresh()` 加重入闸 `_in_refresh`，级联不叠栈。
3. MODE_MULTI 的 `setYRange` 只在量程真变时调（缓存比对，容差 1e-9）。
4. 真复发时完整栈落 `zmax_data/graphic_logs/gui_recursion.log`（记录曲线数/模式），不吞错。

复现/验收：把 `sys.setrecursionlimit` 压到 250，1000+ 条缓冲全选、三种模式各跑 25 拍，应 0 异常。
