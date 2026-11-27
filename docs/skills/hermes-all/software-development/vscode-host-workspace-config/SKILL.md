---
name: vscode-host-workspace-config
description: "Use when 配置/修 VSCode 宿主工作区、标题、Source Control 面板。"
version: 1.0.0
author: Hermes Agent
license: MIT
trigger: "Use when 用户说'工作空间怎么分的''代码看不到了''路径你得显示啊''source control 帮我设置好''VSCode 怎么打开/重启'。"
metadata:
  hermes:
    tags: [vscode, workspace, scm, git, host]
    related_skills: [zmax-console, zmax-vscode-extension, gnome-desktop-launchers]
---

# VSCode 宿主配置 (多根工作区 · 标题 · Source Control · 进程)

## When to Use
- 用户问「工作空间怎么分的」「原来的代码怎么看不到了」「路径你得显示啊」「source control 帮我设置好」
  「这个 vscode 怎么打开」「怎么重启 VSCode」。
- 要改 `ZMAX.code-workspace` / `.vscode/settings.json`, 或重启/杀 VSCode 实例, 或查 VSCode 崩溃。
- 只管**宿主**(工作区/标题/面板/进程); 自研扩展的开发与打包见 `zmax-vscode-extension`。

## 用户口径 (先立住这几条, 否则改完还得返工)
1. 界面极简: 字少 / 不挤 / **不许截断**; **路径必须看得见**(会直接说「路径你得显示啊」)。
2. **禁止为"防崩溃"擅自砍工作区根** —— 实测精简根照崩(SIGTRAP/SIGILL 与挂载范围无关),
   却立刻换来「原来的代码怎么都看不到了」。要减负就减 `files.watcherExclude` / `search.exclude`, 不减根。
3. `window.title` 里**不许写自造文字**(用户会当场问「这几个字哪来的」); 要路径就用 `${activeEditorLong}` 模板。
4. 改完必**回读 + 核窗口标题**(`wmctrl -l | grep -i "visual studio"`), 不能只说"改好了"。

## 步骤
1. 读现状: `ZMAX.code-workspace` 的 `folders`/`settings` + `.vscode/settings.json` 的 git/watcher 段 +
   `DISPLAY=:0 wmctrl -l | grep -i "visual studio"`(当前标题长什么样)。
2. 改根: 名称**带路径**; 前几个用 `~` 简写(≤约 24 字符防侧栏截断), 仓库根那个写**完整绝对路径**。
   本机口径四根: `框架 (~/zmax/src/lerobot)` / `控制台 (~/zmax/tools/gui)` / `文档 (~/zmax/docs)` / `工程 (/home/ubuntu/zmax)`。
   子目录根 + 整仓根同挂会重复显示(多根不去重) —— 用户要就给, 先说明一句。
3. 改设置: 直接抄 `references/settings-blocks.md`(工作区 + 标题 + git 面板 + 排除项, 已实测)。
4. 验证: `node -e "JSON.parse(require('fs').readFileSync('<文件>','utf8'))"` 校验;
   工作区文件的改动 VSCode 会**自动重载**, `sleep 8` 后核标题/根是否生效。
   要验标题模板可用 `code -r <某文件绝对路径>` 让活动编辑器落到该文件, 再 `wmctrl -l` 看标题含不含路径。
5. 需要重载才生效的项(如 `autoRepositoryDetection`)告诉用户自己按 `Ctrl+Shift+P` → **Reload Window**;
   **绝不在他正在调试时替他重载/杀实例** —— 会连带杀掉他的调试会话。

## 坑 (每条带机制)
1. **`.vscode/` 通常被仓库 `.gitignore` 忽略** ⇒ `git add .vscode/settings.json` 报
   `The following paths are ignored by one of your .gitignore files: .vscode`。这是仓库既有约定,
   **不要 `-f` 硬塞**; 如实说明"设置只在本地生效、不进库"(用户要入库再单独确认)。
2. **Source Control 面板"像没配置"就查两个开关**: `git.autoRepositoryDetection: "openEditors"`(没打开文件时
   认不到仓库) + `git.autorefresh: false`(改了文件面板也不刷新)。复原为 `true`。
   判"面板坏了"前先核底层三件: `git config user.name/user.email`、`credential.helper`、`git status -sb` 有无 upstream。
3. **杀实例禁止 `pkill -f "<cmdline 子串>"`** —— pkill 匹配**整条命令行**, 会连你自己这条 bash 一起匹配上
   ⇒ 自杀(exit -15)且同一行后半段命令静默不执行。用 `PIDS=$(pgrep -x code | tr '\n' ' '); kill $PIDS`,
   或 `systemctl --user stop zmax-vscode-<ts>.scope`。
4. **起独立实例**用 `systemd-run --user --scope --no-block --collect --unit=zmax-vscode-$(date +%s) /usr/bin/code <工作区>`。
   裸 `Popen` 会让它落在控制台服务的 **cgroup** 里, 控制台一停/一崩 systemd 按 cgroup 连它一起收走
   (用户看到的现象是"VSCode 卡住")。
5. **核凭证禁止 cat/grep `~/.git-credentials`** —— 随手写的正则会把 token 连用户名一起打出来
   (首尾字符也算泄露)。`git config --get credential.helper` + `git remote -v` 足够。
6. **VSCode 崩溃 ≠ 用户的工程/扩展坏了**: 先取证再下结论。入库证据 = `dmesg` 的 `trap invalid opcode`、
   VSCode 自记 `CodeWindow: renderer process gone (reason: crashed, code: 132)`、`/var/crash` 的 core;
   exthost 里那几行 `Unable to refresh tree view ...: Canceled` / `Extension host exiting with code 0`
   是渲染进程死后的**连坐记录**, 不是扩展报错。排除项还要量: 可用内存 / oom-killer / CPU 指令集。
   取证模板见 `zmax-console 技能的 references/console-child-processes-and-crash-forensics.md`。
7. `~/.vscode/argv.json` 的 `disable-hardware-acceleration: true` = 全软件渲染(历史为治 SIGTRAP 设的)。
   软件光栅/JIT 恰是 SIGILL 型崩溃的高发区 ⇒ 现象照旧时值得**反向对照一次**, 改前 `cp argv.json argv.json.bak_<原因>`,
   并如实告诉用户这是"对照实验, 结果待观察", 不要写成已修复。
8. 版本:**不自主升级** VSCode/工程版本; 宿主随官方源走 (`apt-get install -y --only-upgrade code`),
   定制全部走自研 vsix, 不碰 VSCode 源码。

## 用户接着会问的两件事 (先备好)
- **怎么打开这个工作区**: 桌面 `Z-MAX工程.desktop`(`Exec=/usr/bin/code <工作区文件>`) / `code <工作区文件>` /
  `文件 → 打开最近`。标题里的 `(Workspace)` 是 VSCode 对工作区文件的标注, 不是错误;
  想彻底去掉就让用户「打开文件夹」(排除项来自仓库内 `.vscode/settings.json`, 照样生效)。做桌面入口见 `gnome-desktop-launchers`。
- **怎么在里面调试工程**: F5 下拉已有现成配置 —— `🚀 全新调试进程 (studio.py)`(要先停常驻控制台, 否则两个实例
  抢相机/引擎/共享内存) 与 `🔌 Attach 现有控制台 (5678)`(只对带 `ZMAX_DEBUG=1` 起来的实例有效,
  桌面/服务起的默认不 listen)。断点绑定/空心的三类根因见 `zmax-console 技能的 references/vscode-debug-breakpoints.md`。
