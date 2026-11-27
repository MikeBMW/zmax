# 控制台与 VSCode 调试 (debugpy) 共存 · 断点为什么不命中

## 1. 🛑 studio_ctl 会杀掉用户的调试会话 (必守)
- `tools/studio_ctl.sh` 的 `pids()` 按 "cmdline 里含本工程 venv 解释器 + 以 studio.py 结尾" 匹配 ——
  **VSCode F5 起的实例同样满足** (debugpy 的 launcher 夹在中间) ⇒ `stop/restart --force` 会把它一起 kill。
  现场表现: 用户 F5 后只打印几行 `📌 工程状态自恢复`, 就回到提示符, **没有窗口也没有报错** (被 SIGTERM, 不是自己退)。
- 硬规则: `pids()` 必须 `continue` 掉任何 argv 含 `debugpy` 的进程; 另有 `dbg()` 只负责**报告**它。
  `bash tools/studio_ctl.sh status` 应输出两行: `running: <ctrl pid>` 与 `debug(VSCode F5): <pid> ← studio_ctl 不管它`。
- 用户正在调试时: 改完控制台代码**不要自己重启**去让改动生效 —— 先问, 或让用户 Stop→F5。
- 需要重启才生效的改动攒批一次说清 (老倪已投诉过"窗口闪来闪去")。

## 2. 断点不命中的三种真因 (按此顺序查, 别猜)
1. **那行不在启动路径里** (最常见): 断点所在文件在启动时**从未被 import**。
   查法: `grep -n "<模块名>" tools/gui/studio.py tools/gui/simulink_module.py` —— 0 处就是没 import。
   这类文件是**惰性加载**的 (画布节点里 `importlib.import_module("...")`, 执行那一瞬才进进程), 在那之前
   VSCode 显示的是空心/灰圆 = Unbound breakpoint ⇒ "刚启动什么都进不去"。
2. **路径/模块身份不对**: 同 venv 下验 `python -c "import <mod>; print(<mod>.__file__)"`,
   必须等于你打开的那个文件 (工程里有 release/staging 快照副本, 容易断在副本上)。
3. **跑的地方不对**: 模块的公开函数由谁调用要查链路 —— 节点实现 (`src/lerobot/engineering/nodes/library.py`)
   或 CLI。命令行跑的是**另一个进程**, VSCode 挂不到它身上 (要另配 launch)。

**铁律**: 给用户/给自己 label 一条 launch 或说"断点会停"之前, **先 grep 调用链**证实那个入口真的走到这一行。
例: `tools/config_to_M.py` 完全不走 `config_import.py` (grep 为 0), 把断点挂在 `import_config_files()` 第 142 行
再拿 config_to_M 当入口 = 假承诺。

## 3. launch.json 配方 (让断点必停)
必须有**入口真身**的配置, 不能只给 GUI:
```json
{"name": "🧮 <模块> · <场景>", "type": "python", "request": "launch",
 "program": "<绝对路径: 系统真走的那支脚本/模块本体>",
 "python": "/home/ubuntu/zmax/gui-venv311/bin/python",
 "cwd": "/home/ubuntu/zmax", "console": "integratedTerminal", "justMyCode": false,
 "args": ["--json"], "env": {"PYTHONPATH": "/home/ubuntu/zmax/src"}}
```
- `justMyCode:false` + `PYTHONPATH=<repo>/src` 是控制台/工程模块能单步的前提。
- 流形引擎入口是 `src/lerobot/manifold/manifold_engine.py` (`__main__`: 默认自检 / `--state` / `--hom-demo` /
  `--calibrate`), 不是历史上的 `tools/manifold_engine.py`; 能量层自检 = `src/lerobot/manifold/energy_manifold.py --selftest`。
  这几支都能被 debugpy 直接拉起跑完 (rc=0), 可作"debug 模式能跑"的最小证据。
- 命令行验证 debug 模式可用 (不必等客户端 attach):
  `python -m debugpy --listen 5679 <脚本> <args>` (不加 `--wait-for-client` 就会跑完即退)。

## 4. 取证纪律
- 说"窗口起来了/截图在"之前先验字节: `ls -la <图>`; 本机没有 ImageMagick 的 `import`,
  截图用 `scrot -u out.png` (对标错的窗口用 `_NET_WM_PID` 对准当前控制台 pid; `xwininfo -id <w> | grep Map State`
  看是否 IsViewable)。
- 用户问"这次启动是你起的么" → 用 `ps -eo pid,lstart,cmd` + `studio_ctl status` 的 debug 行回答, 别凭印象。
