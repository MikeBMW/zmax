# 控制台子进程 (cgroup 连带) 与崩溃现场取证

触发: 用户说「VSCode / 别的工具卡住了」「控制台崩了」「起不来了」, 或 `systemctl --user status` 显示
`status=11/SEGV` / `Failed with result 'core-dump'`。

> 配套读: `vscode-extension-plan.md` — VSCode 宿主升级分工 + 「把 Z-MAX 插进 VSCode 开发界面」(自研 vsix 扩展)的分阶段方案与定位红线。
> 配套读: `vscode-debug-workflow.md` — 在 VSCode 里调试控制台/状态空间引擎/六层节点: F5 配置怎么选、断点不停的四条铁律、跨 venv 断点不命中的根因、画布右键重写 launch.json 的陷阱。

## 1. 先判: 是不是控制台崩了把子进程一起收走
systemd user unit 默认 `KillMode=control-group` ⇒ 控制台**停止或崩溃时整个 cgroup 里的子进程被一起收走**。
`studio.py` 用 QProcess/subprocess 拉起来的工具 (如「打开代码」按钮的 `code -g <file>:<line>`) 就住在这个 cgroup 里。
- 判据: `systemctl --user status <unit> --no-pager | sed -n '/CGroup/,+6p'` —— 子进程 pid 挂在控制台 cgroup 下 ⇒
  那个工具「卡住/消失」很可能是**连带**, 不是它自己的毛病。别一上来就重装/重配那个工具。
- 修法: 需要长期存活的外部工具要从 cgroup 摘出去, 用 `systemd-run --user --scope <cmd>` 启动
  (裸 `subprocess.Popen` 摘不掉, `setsid` 也不够 —— 还在同一个 cgroup)。摘出去后控制台重启/崩溃不再带走它。
- 本工程落点: `tools/gui/simulink_module.py` 的「打开代码」= 唯一直接 Popen `code` 的地方 (grep `which("code")` 只有这一处),
  已改为 `["systemd-run","--user","--scope","--collect","--unit=zmax-vscode-<ts>"] + cmd`, 带 `which("systemd-run")` 探测
  + Popen 失败回退老路 (没有 systemd-run 时不静默失效)。改完 `py_compile` 自检。
- 实测锚点: 单元落在 `/user.slice/user-1000.slice/user@1000.service/app.slice/zmax-vscode-<name>.scope`;
  验解耦 = `systemctl --user status zmax-studio.service | grep -c zmax-vscode` 必须为 0。
- 手动起时加 `--no-block` (`systemd-run --user --scope --no-block ...`) 否则**前台阻塞到工具退出**;
  脚本内用 `Popen` 不需要 (Popen 本身不等待)。

## 2. 崩溃取证顺序 (先定性再动手, 别急着重启掩盖现场)
1. `/tmp/studio_launch.log` 尾部: 找 faulthandler dump (`Fatal Python error` / `Current thread` / `Extension modules`)
   + 业务侧最后几行; `grep -n "📴 收到信号" /tmp/studio_launch.log` 拿到信号号 (**15=SIGTERM, 2=SIGINT**)。
2. `systemctl --user status <unit>`: `status=<n>/<SIG>`、`Result: core-dump`、CGroup 段。
3. `journalctl --user -u <unit> --since ...`: 有 systemd 自己的 `Stopping` ⇒ 是 systemd 发的信号;
   **没有 Stopping 而进程收到 SIGTERM** ⇒ 外部 kill, 日志不留发送方 —— 如实说「来源未留痕」, 不要编造发送者。
4. core: `/var/crash/*.crash` 是 apport 文本 dump, 用
   `sudo grep -aE "^(Signal|ProcCmdline|SegvReason|StacktraceTop|Date):" <file>` 直接取关键字段(Signal 5=SIGTRAP);
   另看 `coredumpctl list`。归档按铁律**先改名不真删** → `zmax_data/backups/crash_<date>/`, 顺手清空 `/var/crash`。

## 3. 关闭路径崩 ≠ 控制台不稳
若崩溃栈含 `_watch_sig` (信号看门狗) + 关闭清理, 且日志有
`QProcess: Destroyed while process (...) is still running`, 说明是**关闭/被强拆那一刻**崩的 native 段错误,
正常使用期不受影响。别把它当「控制台很脆弱」去大改启动架构。

恢复: `systemctl --user reset-failed <unit> && systemctl --user start <unit>` —— 重启控制台要 50s 才出窗口,
先告知用户; 且控制台**禁反复 restart** (见 `status-lights-and-restart.md`)。

**杀进程的安全姿势 (踩过自伤)**: 不要用 `pkill -f <pattern>` —— 当 pattern 文本出现在你自己的命令行里时,
pkill 会**连当前 shell 一起杀**, 命令中途被 SIGTERM 打断、后续步骤全没执行 (留下一半状态的现场)。
改用 `pgrep -x code` (精确进程名) 或先取 pid 再 `kill <pid>`; 重启 GUI 优先 `systemctl --user stop <scope>`, 天然不误伤。

## 4. 伴随现象: VSCode (Electron) SIGTRAP 复发
`Signal: 5` = Electron 致命检查 (主进程 SIGTRAP), **不是内存不足** —— 先核对 `free -h` / 有无 oom-kill 再下结论。
另一种病灶是**渲染进程**崩: `~/.config/Code/logs/<ts>/main.log` 里 `CodeWindow: renderer process gone (reason: crashed, code: 132)`,
`code = 128 + N` ⇒ 132 = SIGILL(4); 同时 `sudo dmesg -T | tail` 会看到多条 `traps: ... trap invalid opcode` 同址 —— 非法指令 (JIT/软件光栅路径或内存损坏), **与 SIGTRAP 不是一回事, 别混为一谈**。
特征: 与工作区规模**相关但不充分** —— 整仓 (实测 46 万条目) 更高发, 但精简工作区也崩过 ⇒ 规模不是唯一变量。
先做只读扫描找畸形条目 (非 UTF-8 名 · FIFO/socket/设备文件 · 超长路径 · **指向自己的软链**): 自指软链 (git mode 120000 内容=自身绝对路径) 是递归遍历的毒药。
缓解按收益排序:
- `.vscode/settings.json` 把重目录同时加进 `files.watcherExclude` + `search.exclude` + `python.analysis.exclude`:
  venv、reports、数据/输出目录、**仓库里嵌套的独立 git 仓库**、models、大文件类型 (mp4/npz/pt/pth/zip/pdf/crash)
- `git.autoRepositoryDetection: "openEditors"` + `git.repositoryScanMaxDepth: 1` + `git.autorefresh: false`
  —— 打开整仓就全盘发现/索引所有 git 仓库是最吃资源的一步
- `search.followSymlinks: false`、`telemetry.telemetryLevel: "off"`
- 仍复发: 升级 VSCode 版本 (已做 1.134→1.142, 崩溃仍在 ⇒ 版本不是唯一变量)
- **绝不要用「多根工作区只挂几个子目录」当防崩手段**: 实测精简工作区照样崩, 而用户一开就以为「代码全丢了」(资源管理器里只剩那几项)。
  为未证实的稳定去削减用户可见范围 = 净损失。要做缩小范围实验, 用**另开的临时窗口**去开小目录, 别动用户日常用的工作区形态。
- 打开方式决定标题与可见范围: 打开**文件夹** `/home/ubuntu/zmax` ⇒ 标题 `zmax`、整仓全可见; 打开 `.code-workspace` ⇒ 标题带 `(Workspace)` 后缀。
  `.vscode/settings.json` 里的排除项**两种方式都生效** ⇒ 排除项写进仓库内的 settings.json, 不要只放在工作区文件里。
- 升级方式 (本机): 装的是 **deb 版** + MS 官方源(`/etc/apt/sources.list.d/vscode.sources`),
  `sudo apt-get install -y --only-upgrade code` 即到最新 (实测 1.134.0→1.142.0, 240MB/1m44s, 释放 50MB)。
  坑: 本机**同时装了 snap 版 code** (`which code` → `/usr/bin/code` = deb 版在役, snap 版没在用却占 1.8G),
  两份共存会争文件关联/扩展; 清理 = `sudo snap remove code` (回滚 `snap install code --classic`)。
- 工作区文件 (`ZMAX.code-workspace`): 用户认可的形态 = **4 个根** (`src/lerobot` · `tools/gui` · `docs` · 仓库根 `.`),
  根名按用户口径写成 `名称  (<路径>)`, 仓库根那条给**完整绝对路径**; 名字控长 (~24 字符) 否则侧栏截断, 父子目录**别同时挂根**
  (VSCode 多根不去重 ⇒ 同一目录出现两遍)。改完 folders VSCode 会**自动重载**该窗口 (标题里 `Welcome - ` 前缀消失 = 已生效)。
  **它是独立 JSON, 不含注释** (同 settings.json 的坑)。
- 标题显示**当前文件的路径**: 工作区 settings 写 `"window.title": "${activeEditorLong}${separator}${appName}"`
  (VSCode 会把它缩成 `~/…`, 没有纯 `/home/ubuntu/…` 的变量 ⇒ 别向用户承诺绝对路径)。
- 工作区桌面入口: `~/Desktop/Z-MAX工程.desktop` → `Exec=/usr/bin/code /home/ubuntu/zmax/ZMAX.code-workspace`,
  `chmod +x` + `gio set … metadata::trusted true` + `desktop-file-validate` 三步齐; 重复点击只会聚焦已有窗口, 不会开第二个。
- 用户给目录清单要**按他的命名改** (`src/lerobot`→框架 · `tools/gui`→控制台 · `docs`→文档 · 仓库根→工程), 别自造措辞。
- 通用的先问一句: 「这个改动会不会让用户看到的东西变少?」可见范围的变化对用户是一等一的破坏, 比崩溃本身更刺眼。
- 每次 `apt-get update` 报 `cdrom://... does not have a Release file` = 装机 LiveISO 残留源;
  注释 `/etc/apt/sources.list` 里的 `deb cdrom:` 行即消 (改前 `sudo cp` 备份, 注释后 `apt-get update` 复验无输出)。
- 软件渲染是 SIGILL 的可疑来源, 但**开关硬件加速是未定论的对照实验, 不是已验证的解**: 早先的缓解正是关掉它
  (`~/.vscode/argv.json` → `"disable-hardware-acceleration": true`), 而崩溃照旧 ⇒ 那条缓解本身没挡住。
  做法: `cp` 备份 argv.json → 改成 `false` → 重启 → 用 `ps -eo cmd | grep type=gpu-process | grep -o "use-gl=[a-z]*"`
  确认渲染路径真的变了 (`use-gl=disabled` = 软件渲染), 再观察是否复崩; 对用户如实说「待观察」, 不要报成已修复。

写 settings.json 的坑: VSCode 接受 JSONC 注释, 但工程的 JSON 校验闸会**拒绝带注释的写入**(写入直接失败)。
⇒ settings.json 保持纯 JSON, 归因/理由写进本 reference。
