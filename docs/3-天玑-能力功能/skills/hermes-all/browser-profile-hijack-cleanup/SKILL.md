---
name: browser-profile-hijack-cleanup
description: Use when 浏览器一开就跳导航/主页要删掉它.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [windows, chrome, edge, homepage, hijack, cleanup, browser-profile]
    related_skills: [windows-plant-host-operations, linux-host-maintenance]
---

# 浏览器主页/导航劫持清理 (Windows · Chrome/Edge)

## When to Use
- 用户丢一个导航 URL(2345/hao123/360 之类)进来说"把这个主页删掉"。
- 用户说"每次打开浏览器就跳 XX"、"新标签页被改了"。

## 第一步: 先分清它是「主页设置」还是「被恢复的标签」

**这个判断决定后续所有动作; 搞反了就会删了一堆配置, 下次开浏览器它还在。** 按序看四处:

1. **主页/启动页真源** `<User Data>\<Profile>\Preferences`(JSON):
   `homepage` · `homepage_is_newtabpage` · `session.startup_urls` · `session.restore_on_startup`。
   全是 `None`/空 ⇒ 它**不是**主页设置。另外看 `profile.exit_type` —— `Crashed` = 上次非正常退出,
   Chrome 下次会自动恢复旧标签(`Normal` 才不会)。
2. **快捷方式** 桌面 / 公共桌面 / 开始菜单 / `...\Quick Launch\User Pinned\TaskBar`: 用
   `(New-Object -ComObject WScript.Shell).CreateShortcut($lnk)` 读 `TargetPath + Arguments`,
   劫持常把 URL 塞在启动参数里(快捷方式目标看着完全正常)。
3. **策略/注册表/开机项**: `HKCU|HKLM\Software\Policies\{Google\Chrome, Microsoft\Edge}` ·
   `...\Internet Explorer\Main\Start Page` · `...\CurrentVersion\Run` · hosts · 计划任务/服务的命令行。
4. 以上都干净 ⇒ 查**历史**: 把 `<Profile>\History`(`sqlite`) **copy 到临时目录再读**(浏览器开着也能读副本),
   取该 URL 的 `last_visit_time`, 与 `Get-Process chrome | StartTime` 比:
   访问落在启动后 1~2 秒 ⇒ 是"启动/恢复"带出来的, 不是用户点的。

## 第二步: 清理(必须先关浏览器)

History 是浏览器独占的 sqlite, 开着改会锁库/被回写。

```powershell
# 优雅关闭: CloseMainWindow 会让 Chrome 自己写 exit_type=Normal; 5s 还在再强杀
Get-Process chrome | ForEach-Object { $_.CloseMainWindow() | Out-Null }
Start-Sleep 5; Get-Process chrome -ErrorAction SilentlyContinue | Stop-Process -Force
```

关掉后按序做(每步都先 `Copy-Item` 备份 `History` / `Preferences` / `Favicons` 到 scratch 目录):

1. `History`: 删 `urls` 里匹配的 URL 行 + 对应 `visits` 行; 结尾 `VACUUM INTO '<新文件>'` 再 `os.replace`
   回原路径 —— 否则旧串留在空闲页里, 以后 grep 还会"命中"。
2. `Favicons`: `delete from icon_mapping where page_url like '%<域名>%'`。
3. `Preferences`: 删 `profile.content_settings.exceptions.media_engagement` 里那个键;
   把 `profile.exit_type` 设 `Normal`、`exited_cleanly` 设 `true`。
4. `<Profile>\Sessions\*`: 含该 URL 的会话/Tabs 文件**删掉**(只删命中的, 别清空目录)。

## 坑

- 🔴 **别用 `CAST(col AS TEXT) LIKE '%2345%'` 扫全表**: 数字 id / 时间戳会命中, 造出"还有 2 条"的假阳性。
  先用 URL 列精确 LIKE, 再谈逐表兜底; 报数字前把命中的行打出来看。
- 🔴 **`taskkill //IM chrome.exe` 在 git-bash 里报 `无效参数`**(MSYS 把 `//` 当路径/选项)。用 PowerShell
  的 `CloseMainWindow()` / `Stop-Process`, 或 `cmd //c "taskkill /IM chrome.exe"`。
- **`profile.exit_type` 不改成 Normal, 删了历史也白搭**: 崩溃标记会让下次启动又把整批旧标签拉起来。
- **用户规则: 只可停不可起** —— 关完浏览器要**让用户自己重新打开**, 别替他起 GUI; 并主动说明他原来的标签
  不会自动恢复了(退出状态已被改成正常)。
- **结论分两句说**: ① "它不是主页设置——配置里压根没有, 快捷方式/策略/hosts 也没有"; ② "它是因为恢复上次会话
  反复出现的, 已经把历史条目和会话文件清掉了"。只说"已删除"而不说清机制, 下次从别的入口(书签/收藏栏)回来他还会找你。
- 只清**这一个域名**; 顺手"清空所有历史"会抹掉用户的工作记录(他常把工位页/AR 页留在历史里当入口)。

## 验收

- `History` 里 `select count(*) from urls where url like '%<域名>%'` = 0;
- `Preferences` 的 `homepage`/`startup_urls` 仍为空、`exit_type` = `Normal`;
- `Sessions\` 里没有含该 URL 的文件;
- 让用户打开浏览器再确认一次(这是唯一能证伪"又回来了"的判据)。
