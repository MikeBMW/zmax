# 现成设置块 (本机实测口径, 直接抄)

## 1. `ZMAX.code-workspace` (仓库根)

```jsonc
{
  "folders": [
    { "name": "框架  (~/zmax/src/lerobot)", "path": "src/lerobot" },
    { "name": "控制台  (~/zmax/tools/gui)", "path": "tools/gui" },
    { "name": "文档  (~/zmax/docs)", "path": "docs" },
    { "name": "工程  (/home/ubuntu/zmax)", "path": "." }
  ],
  "settings": {
    "window.title": "${activeEditorLong}${separator}${appName}",
    "breadcrumbs.enabled": true,
    "files.watcherExclude": {
      "**/.git/**": true, "**/__pycache__/**": true,
      "**/reports/**": true, "**/zmax_data/**": true,
      "**/external/**": true, "**/models/**": true
    }
  }
}
```

* 根名带路径是硬要求; 前三个 `~` 简写防截断, 仓库根写全绝对路径。
* `${activeEditorLong}` 会把家目录缩写成 `~`(VSCode 行为, 改不成纯绝对路径) —— 用户问起就这么答。
* 反例: 写过 `"window.title": "...精简多根"` ⇒ 用户当场问「这几个字哪来的」。标题里只放变量。

## 2. `.vscode/settings.json` 的 git 段 (Source Control)

```jsonc
"git.enabled": true,
"git.autoRepositoryDetection": true,   // "openEditors" ⇒ 没打开文件时面板认不到仓库
"git.autorefresh": true,               // false ⇒ 改了文件面板也不刷新
"git.autofetch": false,                // 大仓(46 万条)别自动联网
"git.repositoryScanMaxDepth": 1,
"git.detectSubmodules": false,         // external/ 下有独立仓, 别混进面板
"git.ignoreSubmodules": true,
"git.openRepositoryInParentFolders": "never",
"git.ignoreLimitWarning": true,
"git.ignoreLegacyWarning": true,
"git.enableSmartCommit": true,         // 没暂存时提交全部
"git.suggestSmartCommit": false,
"git.confirmEmptyCommits": false,
"git.confirmSync": false,
"git.postCommitCommand": "none",       // 提交后不自动推(手点右上角同步)
"git.allowForcePush": false,
"git.countBadge": "all",
"git.showPushSuccessNotification": true,
"git.branchSortOrder": "committerdate",
"git.useEditorAsCommitInput": false,
"git.terminalGitEditor": false,
"git.untrackedChanges": "mixed",
"scm.diffDecorations": "all",
"workbench.editor.decorations.badges": true,
"workbench.editor.decorations.colors": true
```

## 3. 同文件里的其它减负项 (防大仓拖死编辑器)

```jsonc
"python.analysis.diagnosticMode": "openFilesOnly",
"files.maxMemoryForLargeFilesMB": 4096,
"search.followSymlinks": false,          // 有自指软链的仓库必须关
"telemetry.telemetryLevel": "off"
```

排除项只做 "不减根" 的那种减负: `files.watcherExclude` / `search.exclude` / `python.analysis.exclude`
覆盖 reports、zmax_data、external(内含独立仓)、models、data_snapshots、backups 及大文件后缀。

## 4. 核底层再判"面板坏了"

```bash
cd <repo>
git config --get user.name; git config --get user.email
git config --get credential.helper          # store ⇒ ~/.git-credentials 已在库(别去 cat 它)
git status -sb                              # 应见 ## main...origin/main
git remote -v
```
三者齐 ⇒ SCM 面板里 commit/push/pull 直接用, 不用再输密码。

## 5. 面板操作口径 (教用户)

左侧活动栏第三个图标(岔路形) = 源代码管理, 图标数字 = 变更数 · 写提交信息 → `Ctrl+Enter` 提交 ·
右上角 🔄 = pull+push · 左下角状态栏点分支名 = 切/建分支 · 文件右键 = 暂存/放弃更改。
