# VSCode 工作区(多根) · Source Control · 进程纪律

（用户把工程搬进 VSCode 开发界面时用；控制台本体侧的键给 zmax-console 其余文件）

## 多根工作区 (`ZMAX.code-workspace`)

- 默认 4 个根: 框架 `src/lerobot` · 控制台 `tools/gui` · 文档 `docs` · 工程 = 仓库根 `.`。
- **根名必须带路径**（老倪会追问「路径你得显示啊」，只写 `docs`/`lerobot` 不算数）：格式 `名称  (路径)`。
  仓库根写完整绝对路径 `/home/ubuntu/zmax`；其余根用 `~/zmax/...` 省字符 —— 名字总长压到 ~25 字符以内，
  否则侧栏截断（老倪明确不许可截断）。要显示完整绝对路径就得把侧栏拖宽，先说明代价再改。
- **嵌套根会重复显示**：挂了 `src/lerobot` 就不要再挂 `src/lerobot/policies`（多根不去重，侧栏出现两遍）。
  用户点名列举一串子目录时，先合并成能覆盖它们的父目录，并说明「已包含」。
- 只挂聚焦根会让人以为「代码不见了」—— 老倪问「原来的代码怎么都看不到了」就是工作区没把目录挂进来，
  不是文件丢了：先解释清楚，再按他给的清单改。
- 标题栏显示当前文件路径：工作区 settings `"window.title": "${activeEditorLong}${separator}${appName}"`。
  **`${activeEditorLong}` 会把家目录缩成 `~`**，拿不到纯 `/home/ubuntu/...`；改之前先说明这一点，别等他问。
- 改完必回读验证（VSCode 会自己重载工作区，无需重启）：
  ```bash
  node -e "const w=JSON.parse(require('fs').readFileSync('ZMAX.code-workspace','utf8'));console.log(w.folders)"
  wmctrl -l | grep -i "visual studio"   # 标题会跟着 window.title 变
  ```
- 打开方式三选一：桌面 `Z-MAX工程.desktop`（`Exec=/usr/bin/code <abs>/ZMAX.code-workspace`，加 `chmod +x` + 信任）·
  `code <abs-file>` · 文件 → 打开最近。工作区文件删了工作区就没了，别清理掉。
- 数十万条目的大仓必须配 `files.watcherExclude` / `search.exclude`（reports·zmax_data·external·models·大文件类型），
  否则 watcher + 搜索会把编辑器拖到崩。

## Source Control (git 面板)

**面板认不到仓库 / 改了文件不刷新** ⇒ 先查这两条是否被关过（为防大仓崩溃关掉它们，副作用就是面板废掉）：
```jsonc
"git.autoRepositoryDetection": true,   // openEditors ⇒ 没打开文件时面板是空的
"git.autorefresh": true,               // false ⇒ 改了文件也不显示变更
```
开 `autorefresh` 的前提是同时保留 `files.watcherExclude` 大排除，否则每次变更都全仓扫描。

一组好用的值：`detectSubmodules=false` + `ignoreSubmodules=true`（防止借开在 `external/` 下的独立仓混进面板）·
`allowForcePush=false` · `enableSmartCommit=true` · `postCommitCommand="none"`（提交后不自动联网推，大仓自动 fetch 会卡）·
`countBadge="all"` · `ignoreLimitWarning` · `scm.diffDecorations="all"`。

**✓ 提交按钮灰色 = 没有「已暂存更改」。** 两条路：
1. 在「Changes」里点文件行（或 `Changes` 标题行）的 **+** 暂存 → 文件挪到「Staged Changes」→ ✓ 才亮；
2. `git.enableSmartCommit=true` 可免暂存提交，**但该设置要 Reload Window 才被 git 扩展读到** ——
   刚写进 settings 就发现「按钮还是灰的」，是没重载，不是设置写错。

核对推送真伪**只看服务器**（面板显示成功不算）：
```bash
git branch -vv                                           # 上游是谁
git rev-list --left-right --count main...origin/main     # 左=本地没推, 右=远端没拉
git ls-remote origin main                                # 直接问服务器, SHA == git rev-parse HEAD 才算推上去
```

查分支/身份/远端要从配置真源读：
```bash
git config --list --show-origin | grep -E "user\.|remote\.origin|branch\.main"   # 值 + 来自哪个文件
git branch -vv ; git status -sb
```
- 身份通常写在**仓库级** `<repo>/.git/config` 的 `[user]`，**不在** `~/.gitconfig`（那里一般只有 `credential.helper=store`）。
  老倪问「在哪检查」时直接把文件+行号给他。
- `.vscode/` 常被仓库 `.gitignore` 忽略 ⇒ 工作区设置/调试配置**只在本机生效、不进版本库**；汇报时要说清，别让他以为已入库。
- 用户在侧栏看不到 `.git` 是正常的：`files.exclude` 默认隐藏 `**/.git`（想常显就 `"**/.git": false`，不推荐）。
  要给他看内容就直接开文件：`code -r <repo>/.git/config`，或集成终端 `ls -la <repo>/.git/`。
  另外 `.git/`（版本库元数据）与 `.github/`（仓库内容：workflows/ISSUE_TEMPLATE）是两码事，别混着解释。

## 起停 VSCode 的进程纪律

- 杀 VSCode 用 `pgrep -x code`（**精确进程名**）拿 pid 再 `kill`。
  **绝不要** `pkill -f "<含路径的串>"`：该模式串就写在你自己这条命令行里，`-f` 会连自己一起匹配 ⇒
  命令中途被 SIGTERM 掐死、后续步骤全没执行（亲眼踩过）。同理禁 `ps | grep <名字>`。
- 从控制台里起 VSCode 要走 `systemd-run --user --scope --no-block --collect --unit=zmax-vscode-<ts>`，
  否则落在 `zmax-studio.service` 的 cgroup 里，控制台一停/一崩就被连坐收走（用户看到的就是「VSCode 卡住」）。
- 改 `.vscode/argv.json`（如硬件加速开关）**必须重启 VSCode 才生效**；改前备份原文件，并说明这是反向对照实验。
- 重启前先确认没有未保存内容：崩过的实例常留着主进程但窗口为 0，别据此判「实例还活着」。
- 探活证据：`wmctrl -l | grep -i "visual studio"` · exthost 日志激活记录 · 自建扩展的自证日志。
