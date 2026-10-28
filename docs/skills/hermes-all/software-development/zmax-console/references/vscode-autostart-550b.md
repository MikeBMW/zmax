# 550B 标定档 · 打开工程后自动起 VSCode (省资源 · 单线程 debug)

老倪 2026-10-21: 「550B 标定版，选择后，从 文件，打开工程，你要自动启动 vscode 的状态空间工程，
要注意节约资源，因为 vscode 每次启动后，机器都显得很慢；标定配置版本，不需要那么多并行逻辑、多线程，
要保持稳定的，面向清晰单线程逻辑的 debug 模式。」

## 单一实现 (改这里, 别在 studio 里另写一套)
`tools/gui/vscode_launch.py`
- `AUTOSTART_PRODUCTS = ("550B",)` 产品档唯一真源 = `config/platform/zmax_product.json::active_product`
- `GUI_FLAGS = ("--reuse-window", "--disable-gpu")` —— **只放 `code --help` 实测存在的参数**。
  未知参数会被 code 当成"要打开的文件"，所以 `--skip-welcome` / `--disable-workspace-trust` 这类
  (本机版本没有) 一律不许塞命令行，关欢迎页/信任/自动更新改用 `.vscode/settings.json`。
- `DISABLE_EXTENSIONS`: 关 pylance / containers / remote-containers / python-envs（实测 pylance 单进程 920 MB）。
  只留 ms-python.python + ms-python.debugpy ⇒ F5/断点照常。
- `SINGLE_THREAD_ENV`: OMP/MKL/OPENBLAS/NUMEXPR/VECLIB/TORCH = 1 + MALLOC_ARENA_MAX=2 +
  ZMAX_SINGLE_THREAD=1 / ZMAX_DEBUG_MODE=1 / ZMAX_PRODUCT=550B —— 这是单线程口径**唯一真源**，
  `.vscode/launch.json` 的「🅱 550B 标定版 · 单线程 debug」和 `_vscode_launch_cfg` 模板必须与它逐键相同。
- `--goto <root>/tools/gui/simulink_module.py:1` + workspace 路径: 一进来就落在状态空间工程代码上，
  不会停在「Welcome」页（用户会当成"没打开工程"）。
- 起进程走 `systemd-run --user --scope --unit=zmax-vscode-<ts>`：脱离控制台 cgroup，关/崩控制台不带走它。
- 自证日志 `~/.cache/zmax/vscode_autostart.log`；CLI `python tools/gui/vscode_launch.py [--dry-run] [--product 550A]`。

## 接线
`studio.py::StudioMainWindow._vscode_autostart_after_open(entry)` 在两条打开路径末尾各调一次：
`打开总工程`、`加载工程文件`。方法内永不抛（打开工程是主线），只如实回一行状态栏 + 一行信息窗；
非 550B 也要明确报「未自动起 — 当前 xxx 不是标定档」。

## 实测数字 (本机, 2026-10-21)
- 放开全部扩展直接开：15 进程 / **3760 MB** / 306 线程
- 关 pylance+containers+remote+python-envs、--disable-gpu：14 进程 / **2578~2813 MB** / 282 线程（省 ~1.2 GB）
- 仍剩下的 ~2.6 GB 是 Electron 基线（renderer 800 MB 级 + extension host + 若干 node 服务）；
  再往下压只能收窄 workspace（只开 tools/gui + src/lerobot + flows），当前未做。

## 判据
`tools/verify_vscode_autostart.py`（24 项）：只有 550B 起（550A/550C 临时真源验 False）、
CLI 参数都在 `code --help` 里、env 与 `SINGLE_THREAD_ENV` 逐键相等、systemd-run 隔离、
注入 spawn 替身真跑调用链（全程不真起进程，pgrep 前后一致）、studio 两处接线 + 真调方法回报、
launch.json 与 `_vscode_launch_cfg` 模板同源、settings 资源开关在位、日志有记录。

## 坑
- `pkill -f "/usr/share/code/code"` 会**杀掉自己这条 shell**（命令行里含同样字符串，-f 全匹配）⇒
  用锚定模式 `pgrep -f '^/usr/share/code/code'` 再 xargs kill。
- `launch.json` 是 JSONC（有 `//` 注释）：任何 `json.load` 都会炸 ⇒ 解析前 `re.sub(r"^\s*//.*$", "", s, flags=re.M)`。
  历史上 `check_debug_cfg.py` / `verify_console_title_product.py` 就因此长期假红。
- 判据脚本 `chk()` 若只有 2 个参数，别给它传证据串（TypeError 会被后续 Qt 退出盖成 "Aborted (core dumped)"，
  看着像 DDS 崩溃，其实是自己传参错了）。
