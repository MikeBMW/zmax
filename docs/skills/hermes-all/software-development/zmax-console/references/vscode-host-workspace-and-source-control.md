# 🖥 VSCode 宿主工作区 · Source Control (2026-10-17 老倪定稿)

## 打开方式

* 桌面图标 `~/Desktop/Z-MAX工程.desktop`(Exec=`/usr/bin/code /home/ubuntu/zmax/ZMAX.code-workspace`)。
* 命令行 `code /home/ubuntu/zmax/ZMAX.code-workspace`; 或 VSCode `文件 → 打开最近 → ZMAX (Workspace)`。
* 工作区定义文件 `ZMAX.code-workspace` **别删** —— 删了工作区就没了; 改根/标题/排除都改它。

## 根与命名 (老倪逐条定过)

| 侧栏显示 | 路径 |
|---|---|
| `框架  (~/zmax/src/lerobot)` | src/lerobot |
| `控制台  (~/zmax/tools/gui)` | tools/gui |
| `文档  (~/zmax/docs)` | docs |
| `工程  (/home/ubuntu/zmax)` | `.` (整仓) |

* 根名**必须带路径** (老倪: 「路径你得显示啊」); `~` 缩写是为了不被侧栏截断 (他要求不截断), 但 `工程` 写全绝对路径。
* 同一父子的目录别同时挂 (如 src/lerobot + src/lerobot/policies) ⇒ 侧栏会出现两遍。挂父目录即可。
* 早期曾把名字写成"(整仓)"/"精简多根" —— 他当面否掉, 别再用这类自造词。

## 标题显示当前文件路径

* 工作区 settings: `"window.title": "${activeEditorLong}${separator}${appName}"` ⇒ 标题跟着打开的文件走, 例: `~/zmax/tools/gui/studio.py - Visual Studio Code`。
* VSCode 会把家目录缩写成 `~`, **给不了纯 `/home/ubuntu/...`** —— 对老倪如实说, 别硬凑。
* `settings.window.title` 也会**改写窗口标题** ⇒ `wmctrl -l | grep "Visual Studio Code"` 找不到窗口, 别据此判"窗口没了"。

## Source Control (git 面板)

* 面板要能用, 工作区必须: `git.autoRepositoryDetection: true` + `git.autorefresh: true`。
  **防 SIGTRAP 时把这两条关成 false/openEditors 的代价 = 面板认不到仓库 + 改了文件不刷新**(本次"面板像没配置"的真因)。
* 另配: `git.detectSubmodules=false` + `ignoreSubmodules=true` (external 下有独立仓, 别混进面板) ·
  `allowForcePush=false` · `postCommitCommand=none` (提交后不自动联网推) · `countBadge=all` ·
  `ignoreLimitWarning` · `repositoryScanMaxDepth=1` · `scm.diffDecorations=all`。
* **✓ 提交按钮灰着 = 没有已暂存更改** —— VSCode 只在 `Staged Changes` 非空时亮。两条路:
  ① 点文件行 / `Changes` 标题行的 `+` 先暂存;
  ② 设 `git.enableSmartCommit: true` **并 Reload Window** —— 设置改了不重载, **已打开的窗口读不到**, 按钮照样灰(本次就卡在这)。
* 身份/远端真源 = **仓库级** `/home/ubuntu/zmax/.git/config` (`user.name`/`user.email`/`remote.origin.url`/`branch.main.*`);
  全局 `~/.gitconfig` 只有 `credential.helper = store`(口令在 `~/.git-credentials`, 内含 github.com/ghproxy.net/ghfast.top)。
  查证用 `git config --list --show-origin | grep -E "user\.|remote\.origin|branch\.main"` / `git branch -vv` / `git status -sb`。
* 🔴 **打印凭证时只截主机名**: `grep -oE 'https://[^/]+' ~/.git-credentials` 仍会带出 `用户名:token@` 整段 —— 本次踩到。要脱敏就 `sed 's#//[^@]*@#//***@#'`。

## 两个容易混的隐藏目录

* `.git/` = 版本库元数据 (62M), 侧栏看不到是**正常**(`files.exclude` 默认 `**/.git: true`)。要看就集成终端或直接打开文件;
  **别**把 `files.exclude` 关掉。`.vscode/` 被仓库 `.gitignore` 忽略 ⇒ `settings.json`/`launch.json` **只在本机生效、不进库**, 要入库得 `git add -f`。
* `.github/` = GitHub 平台功能目录 (`workflows/` · ISSUE_TEMPLATE · PR 模板), 是仓库内容、要提交, 与 `.git/` 无关。
