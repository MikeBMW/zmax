# Frozen 路径多候选探测 (2026-08-26 v3.2.2-v3.2.5 实测)

**坑**: PyInstaller exe 运行时 `__file__` 指向解压目录 (Windows `AppData\Local\...`, Mac `Contents/Frameworks`),
`__file__` 上溯三级拼相对路径 → `C:\Users\Admin\AppData\Local\src\...` / `/Applications/Z-MAX_Console.app/Contents/Frameworks/tools` 不存在 → FileNotFoundError。
**任何用 `__file__` 上溯定位仓库资源/动态加载 .py 的代码, exe 下必炸。**

## 修复模式 (多候选探测, 找到含标志文件为止)

```python
def _find_dir(rel, marker):
    cands = []
    env = os.environ.get("ZMAX_REPO_ROOT")          # ① env 显式指定
    if env and os.path.isdir(env):
        cands.append(os.path.join(env, rel))
    if getattr(sys, "frozen", False):
        cands.append(os.path.join(getattr(sys, "_MEIPASS", ""), rel))  # ② _MEIPASS
    cands.append(os.path.join(                          # ③ __file__ 上溯三级 (源码)
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), rel))
    d = os.path.dirname(os.path.abspath(__file__))      # ④ 逐级向上探测仓库根
    while True:
        cands.append(os.path.join(d, rel))
        parent = os.path.dirname(d)
        if parent == d: break
        d = parent
    for c in cands:
        if os.path.isfile(os.path.join(c, marker)):
            return c
    raise FileNotFoundError(f"未找到 {marker} (已探测: {'; '.join(dict.fromkeys(cands))})")
```

- 标志文件选稳定存在的 (如 `perception.py`、目录存在性)
- `ZMAX_REPO_ROOT` env 兜底: Linux/跨机部署显式指定仓库根
- **importlib 动态加载的 .py 不会被 PyInstaller 自动收集** → 打包必须 `--add-data` 含整个源码目录 (如 `src/lerobot/policies/left_right`)

## 源树里的软链, 打包后变成**两份独立拷贝** ⇒ 写的和读的不是同一个文件

**症状**: 打包版打开「工程/配置」类文件后, 界面里内容是空的(实测: 工程文件里明明 94 个节点 222 条连线,
打开后画布 **0 项**), 而源码模式完全正常; 也没有任何报错。

**根因**: 仓库里为了保证「唯一依据」常用软链, 例如
`flows/state_space_obs.json -> ../src/lerobot/engineering/flows/state_space_obs.json -> data/database/zmax/sources/canvas/…`。
`--add-data "flows;flows"` 与 `--add-data "src/lerobot/engineering;…"` 各拷一份 ⇒ 包里是**两个真文件**。
写盘走的探测表(`config_import.canvas_path()` 之类)命中 `_MEIPASS/src/...`, 读盘走的另一张表
(`_flows_path()` 只查 `_MEIPASS/flows/`)命中旧那份 ⇒ 写了个没人读的副本, 界面永远空。

**判别(三步, 别猜)**:
1. 在目标机上找**最近被写过**的那份: 按 mtime 列所有同名候选
   `Get-ChildItem <root> -Recurse -File -Include '<name>' | ? { $_.LastWriteTime -gt (Get-Date).AddMinutes(-40) }`
   —— 写盘目标现身, 通常和读盘路径不同。
2. 把写出来的那份**拉回本地用 Python 解析**, 确认内容是对的(节点数/关键字段) ⇒ 排除「写盘失败」。
3. 直接看读盘函数的候选表(`grep -n "def _flows_path" -A15`), 比它和写盘候选的第一条是否同一个文件。

**修法(按顺序都做)**:
- 代码: 冻结态候选表把**可写的那份放第一位**, 兜底才是旧位置:
  `cands = [join(_MEIPASS,"src",...,"flows",name), join(_MEIPASS,"flows",name)]`;
  根治是**只保留一个真源**(打包时把软链目标作为唯一 `--add-data`, 别再同时带 flows/ 与 src/…/flows/)。
- 线上救急(用户正在用): 把写出来的那份 `Copy-Item` 到读盘位置(所有候选根都放一份),
  让他点一次触发重载即可, 不必重启 GUI; 判定靠程序自己的 trace 行(如「画布场景项=N」)从 0 变正数。
- 凡是源树里出现 `find . -type l` 命中的数据文件, 都要在打包后核一遍「读路径 == 写路径」。

## exe 运行时其他坑 (同批次实测)

- 无 `.venv`/GPU → 视频生成等重负载功能 frozen 守卫跳过, 提示"需 4060/ECS 生成后放回" (`if getattr(sys,"frozen",False): return False, "..."`)
- 运行后自动弹出的窗口 (3D 视图等) 若 `WindowStaysOnTopHint` 置顶 → **盖住主界面看起来黑屏** → 自动弹出用 `on_top=False`, 手动点按钮才置顶
- Mac 无 GPU/EGL → metaworld 渲染子进程跳过 (`sys.platform == "darwin"`)
- exe 内置视频名与代码查找名不一致 → frozen 分支优先找打包名 (`mlp_insert_success_final.mp4` 等), 再 fallback 源码名

## Mac 黑屏诊断法

用户报"启动后黑屏返回主页"时: 在构造函数关键段写文件打点
(`/tmp/zmax_simulink_init.log`: START → pre-_build → post-_build), 缺失哪行 = 崩在哪段,
不依赖 GUI 就能定位构造崩溃点。源码模式启动脚本应带 `QT_OPENGL=software` +
`LIBGL_ALWAYS_SOFTWARE=1` 兜底 (3D GLViewWidget 在 Mac OpenGL 上下文失败会黑屏)。
