# VSCode 工作区 · Source Control · 调试 速查 (2026-10-17)

## 打开
- 桌面图标「Z-MAX 工程」→ `/usr/bin/code /home/ubuntu/zmax/ZMAX.code-workspace`
- 命令行: `code /home/ubuntu/zmax/ZMAX.code-workspace`
- 工作区 4 个根: 框架(`src/lerobot`) · 控制台(`tools/gui`) · 文档(`docs`) · 工程(仓库根 `/home/ubuntu/zmax`)
- 标题栏显示当前文件路径: `window.title = ${activeEditorLong}${separator}${appName}`

## Source Control (源代码管理)
- 面板: 左侧活动栏第 3 个图标, 或 `Ctrl+Shift+G`; 图标上的数字 = 变更数
- 流程: 改文件 → 面板里点文件看 diff → 在「消息」框写提交信息 → `Ctrl+Enter` 提交
- 推送: 面板右上角「同步更改」= pull + push (配置 `postCommitCommand=none` ⇒ 提交后不自动推)
- 分支: 窗口左下角状态栏点分支名 = 切换 / 新建
- 设置唯一依据: `/home/ubuntu/zmax/.vscode/settings.json` (git.* 21 条)。注意 `.vscode/` 被 `.gitignore` 忽略 ⇒ 只在本机生效、不进库
- 身份/远端唯一依据: `/home/ubuntu/zmax/.git/config` (user.name=MikeBMW · remote=github.com/MikeBMW/zmax)

## 调试 (F5)
- 配置: `.vscode/launch.json` 共 15 条; 常用「🚀 全新调试进程 (studio.py)」(`gui-venv311`) 与「🔌 Attach 现有控制台 (5678)」
- 起调试前先停常驻控制台: `systemctl --user stop zmax-studio`; 调完 `systemctl --user start zmax-studio`
- 断点必停四前提: 550B 档 + 勾「INTACT 节点执行」/「模型执行」· 必须 F5/attach 启动(直接 `python studio.py` 不行) ·
  断点打在函数真身第一行 · 改码后重启调试会话
- 「断点空心(灰环)」三类根因: 技能 `zmax-console/references/vscode-debug-breakpoints.md`

## 已知坑
- `.git` 目录在 VSCode 侧栏不显示 (`files.exclude` 的 `**/.git: true`) —— 正常, 用集成终端或直接打开文件看
- Linux 下 VSCode 默认 `keyboard.dispatch=code`, 脚本合成的按键无效 ⇒ 验收靠自证日志/窗口标题
- 控制台里起 VSCode 走 `systemd-run --user --scope` (与 zmax-studio 的 cgroup 解耦), 见 `tools/gui/simulink_module.py`
