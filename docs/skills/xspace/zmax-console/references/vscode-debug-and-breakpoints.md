# VSCode 调试 (studio.py / 画布节点 / 流形引擎) — 纪律与断点诊断

## 一、调试会话永远不归 studio_ctl 管
- 老倪按 F5 起的 studio.py 实例 **就是他的调试会话**。`tools/studio_ctl.sh` 的 `pids()` **必须排除 cmdline 含 `debugpy` 的进程**
  (另设 `dbg()` 只做报告), 否则 `stop/restart` 会连他的调试会话一起 kill:
  现场表现 = F5 后只打印几行「📌 工程状态自恢复」就回到提示符, **没窗口、也没报错** —— 进程是被杀的, 不是自退。
  捕获网: studio_ctl 的匹配规则是「cmdline 里同时含本工程 venv 解释器 + studio.py」, 而 debugpy 起的实例 launcher 夹在中间, 同样命中。
- 调试期间我改完控制台代码**不要自己 restart**: 让他在 VSCode 里 Stop→F5, 或先问一句。改完的代码在他那个实例里不会自动生效。
- `bash tools/studio_ctl.sh status` 应同时报两行: `running: <ctrl pid>` 与 `debug(VSCode F5): <pid> ← 不管它`。
- 认窗口属谁: 先取当前控制台 pid, 再 `xdotool search --pid <pid>` + `xprop -id <win> _NET_WM_PID` 核对
  (同名窗口会有多个/旧的)。调试实例除主窗 (MapState=IsViewable) 外还有一个 IsUnMapped 的 `studio.py` 底窗口, 属正常, 不用管。

## 二、「断点怎么没命中」标准诊断顺序 (先证代码有没有真跑, 别先改代码)
1. **查那条路径有没有执行过**。节点类代码看它 params 里**每次执行必刷**的时间戳字段:
   `write_into_node()` 里 `params["cfg_loaded_at"] = snap["loaded_at"]`, 而 `snap["loaded_at"]` 取 `time.strftime("%F %T")` —— 时间戳陈旧 ⇒ 这段代码压根没跑过。
   实例链路: 画布节点「🧮 标定诊断测量 · 主参数 M」(`n_calib_mani`, 实现 `src/lerobot/engineering/nodes/library.py::node_ss_calib_mani`)
   → `config_import.load_config()`:254 → `import_config_files()`:111 → `db = _read_db(...)`:142。只有**这个节点被运行**才会停 142。
2. **看入口覆盖到哪**: F5 起 studio.py 只到界面; 节点代码要**跑画布 / 单跑该节点**才执行。跑画布在控制台**同一进程**里, 断点能停。
3. **看进程边界**: CLI 工具即便走同一条链也是**另一个进程**, VSCode 那个 launch 会话挂不上 ⇒ 必须给它单独一条 launch 配置。
4. **别把断点下错文件**: `tools/config_to_M.py` **不经过** `config_import`(自己读 `config/calib/*`); 要停在 142 必须指向 `src/lerobot/engineering/config_import.py` 本体。

## 三、`.vscode/launch.json` 现成配置
统一口径: `python=/home/ubuntu/zmax/gui-venv311/bin/python`, `cwd=/home/ubuntu/zmax`, `console=integratedTerminal`, `justMyCode=false`, 脚本类带 `PYTHONPATH=/home/ubuntu/zmax/src`。
- `🚀 全新调试进程 (studio.py)` — 控制台本体 (画布运行/节点内断点靠它)。
- `🧮 配置导入 · 唯一依据+工程库读 (config_import.py · 断点 142 必停)` — `args:["--json"]`; 读到 `db.path/projects/tables` 即证 142 执行过。
- `🧮 配置导入 · 读+写回画布节点 (config_import.py --node)` — 走 `load_config` 并把 cfg_* 写回节点 (写盘前备份 + 写后回读)。
- `🌀 流形引擎 · 自检 / 状态快照 (--state) / 内稳态演示 (--hom-demo) / 能量层自检 (energy_manifold.py --selftest)`。
- INTACT L4 四条 (policy 层 / GUI 节点路径 / 模型侧单步 / 真物理桥)。
- `🔌 Attach 现有控制台 (5678)` 只对 `debugpy.listen(5678)` 起的实例有效。

## 四、验证「debug 模式真能跑」不依赖 VSCode
`./gui-venv311/bin/python -m debugpy --listen <port> <script> [args]` —— 不带 `--wait-for-client` 会立刻跑完并给 rc,
rc=0 才算该入口在调试器下可启动 (这就是「debug 模式好了么」的判据, 不要靠“看起来配好了”)。

## 五、截图取证坑
本机**没有 ImageMagick**: `import -window …` 静默失败 (命令找不到, 但外层 `&&` 看着像成功) ⇒ 截图一律 `scrot -u out.png` (或 `xwd`), 写完 `ls -la` 核字节数。详见 `console-popup-names-only.md`。
