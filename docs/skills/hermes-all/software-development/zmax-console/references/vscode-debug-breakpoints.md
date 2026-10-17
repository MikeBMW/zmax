# 🐞 VSCode 断点"空心"的三类根因 · 路径层数坑

来源: 老倪 2026-10-14「必须能进入这个断点 (config_import.py:142 `db = _read_db(...)`) —— 改」;
2026-10-17 实测复发: 断点仍不停, 根因是路径少一层 dirname (下面第 2 类), 已修。

## 先分清"没执行"和"没绑定"

* 断点**空心/灰环** = 该文件那一刻还没被 import 进进程 (debugpy 不知道有这行) —— **不是**代码没跑到。
* 断点**实心红点但不进** = 路没走到 / 档位开关没勾 (见下面「必停四前提」)。
* 引擎侧进度行 `· 前馈 MLP真身 N/守卫 M`: N=0 ⇒ 没执行; N>0 却不停 ⇒ 绑定问题。

## 三类根因 (每一类都能造成"永远不停")

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
3. **模块加载方式让 debugpy 绑不上** —— 引擎六层用 `importlib.util.spec_from_file_location` 加载 ⇒ 断点不绑定。
   修法: `exec(compile(src, 绝对路径, "exec"))` + 注入 `__file__`/`__name__` + 注册 `sys.modules`。

## 断点必停的四个前提 (全满足才停)

1. 档位 **550B** + 勾「🤖INTACT 节点执行」或「🧠模型执行」(纯演示档走 L4Demo 独立链, 链上没有 Accelerator)
2. 必须 **F5 / attach** 启动 (直接 `python studio.py` = 非调试模式, 断点永不进)
3. 断点打在**函数真身第一行** (如 `obs = np.asarray(...)`), 打在 `def` 行或 docstring 行不停
4. 改码后**重启调试会话** (GUI 主进程缓存旧模块)

## 取证命令 (照抄)

```bash
cd /home/ubuntu/zmax

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
