---
name: windows-host-slimming-disk-merge
description: Use when 清理Windows垃圾/把C D E并入一个盘瘦身。
version: 1.0.0
author: hermes-agent
license: private
metadata:
  hermes:
    tags: [windows, cleanup, diskpart, disk-merge, slim]
    related_skills: [windows-plant-host-operations, linux-host-maintenance]
---

# Windows 主机瘦身 / 多盘合并为一个 C 盘

## When to Use
- 老倪说"清理系统垃圾""全面瘦身""把 C/D/E 合成一个盘"
- C 盘紧张、D/E 空着没用、装过 Linux 后又不要了
- 需要清 "没用的程序"（其实程序文件已删，只剩快捷方式/服务/卸载登记）

## 0. 主机拓扑（本机实测 11-08）
- 小静静 = 本机 Windows 11，192.168.1.6，SSH 22 开，Hermes gateway 在 8019（非 HTTP，curl 会 connection reset）
- 隔壁 4060 机 = 192.168.1.7（hostname ubuntu，ssh ubuntu/密码见老倪口述）：另一套 Hermes v0.21.5，gateway 只听 127.0.0.1:35781（所以局域网扫不到），飞书 connected；同时跑 Z-MAX 服务 8791/8793/8794/8797/8799/8802/8804/8805/8888(代理)
- 192.168.1.2/3/4/5 = 路由器 / ESP32 / 两部手机，无服务

## 1. 先量，再删
```bash
df -h /c ; powershell -NoProfile -Command "Get-Volume | ft DriveLetter,@{n='GB';e={[math]::Round(\$_.Size/1GB,1)}},@{n='Free';e={[math]::Round(\$_.SizeRemaining/1GB,1)}}"
# 分区布局（判断能不能扩）
Get-Disk | ft Number,FriendlyName,PartitionStyle
Get-Partition | ft DiskNumber,PartitionNumber,DriveLetter,@{n='GB';e={[math]::Round(\$_.Size/1GB,1)}},Type,GptType
```
- C 只能扩进**紧邻其后的未分配空间**：C 后面每夹一个分区都得先删。
- GptType 认类型：`ebd0a0a2…`=NTFS 数据盘，`de94bba4…`=恢复分区，`0fc63daf…`=Linux 数据分区（Windows 下无盘符、`ls`/`du` 看不到）。
- 占用调查用 PowerShell（`Get-ChildItem -Recurse | Measure Length -Sum`）或 `timeout 45 du -sm` 逐个目录；**别对整盘/大目录直接 du**，小文件一多必超时。

## 2. 垃圾清理（实测收益 ~3.5GB + 组件库）
```bash
find "$LOCALAPPDATA/Temp" -mindepth 1 -maxdepth 1 -exec rm -rf {} +   # 用户临时
find "C:/Windows/Temp" -mindepth 1 -maxdepth 1 -exec rm -rf {} +      # 系统临时（需管理员）
find "C:/Windows/SoftwareDistribution/Download" -mindepth 1 -maxdepth 1 -exec rm -rf {} +  # 更新缓存
rm -rf "$LOCALAPPDATA/hermes/cache/uv" "$LOCALAPPDATA/hermes/cache/partials"  # Hermes 包缓存（会重下）
rm -rf "$LOCALAPPDATA/pip/cache" ; npm cache clean --force
find "C:/*/\$Recycle.Bin"/*/ -mindepth 1 -exec rm -rf {} +              # 回收站（Clear-RecycleBin 常常清不动，直接删 $R*）
find "C:/Windows/Logs" -type f \( -name '*.cab' -o -name '*.etl' -o -name '*.dmp' \) -mtime +2 -delete
DISM.EXE /Online /Cleanup-Image /StartComponentCleanup                 # 组件库（实测省 3.19GB）
```
- 大件参考：hiberfil.sys≈内存大小（6.4GB/16G 内存），关休眠才省（`powercfg /h off`，代价是丢快速启动）——空间够就别动。

## 3. 清"没用的程序"残留（文件早删、壳还在）
1. 死快捷方式：`WScript.Shell.CreateShortcut` 取 TargetPath，**目标不存在才删**，顺便把搬家后的目标改对（如飞书→`C:\Programs\Feishu\app\Feishu.exe`）。
2. 死服务：`Get-CimInstance Win32_Service | ? PathName -match '^"?[DE]:'` → `sc.exe delete <Name>`。
3. PATH / JAVA_HOME：`[Environment]::SetEnvironmentVariable` 里剔掉指向已删盘符的项（机器级）。
4. 卸载登记项：`…\CurrentVersion\Uninstall\*` 中 InstallLocation 指向已删盘符的整键删掉。

## 4. 合并分区（不可逆，先拿到老倪确认）
1. **停占用进程**：`Get-Process | ? Path -match '^[DE]:'`——实测会被 Feishu(13 进程)、QiyiService、银行证书 certd 顶着；不停就删不动分区。
2. **迁移内容**：`robocopy D:\Programs\Feishu C:\Programs\Feishu /E /R:1 /W:1`；`rc=1` 表示"已复制成功"，不是失败。用日志尾部的 字节 行核对，别用 du 复核（超时）。
3. **恢复分区先确认**：`ReAgentc.exe /info`——若已是 Disabled（被一键还原替掉），1.2GB WinRE 分区直接删，不影响。
4. **diskpart 从高编号往低删**（编号会重排，顺序错了会删错盘）：
```
select disk 0
select partition 9 / delete partition override
... 依次 8,7,6,5,4 ...
select partition 3 / extend / list partition
```
   保护类型（Recovery/Linux）必须带 `override`，否则拒绝。
5. **清死启动项**：`bcdedit /delete {guid} /f`。注意中文版 bcdedit 的键名是「标识符」，用英文 `identifier` 正则匹配**取不到 GUID**（不会误删但也删不掉）；先打印 block 再取 `\{([0-9a-fA-F-]+)\}`，确认是 `\EFI\ubuntu\shimx64.efi` 那条再删，Windows Boot Manager 与 Windows 11 条目要仍在。
6. 收尾验证：`df -h /c`、`ls /d /e` 应报不存在、`git --version`（Hermes 自带 git 在 `~/AppData/Local/hermes/tools/git-*`，删 D 盘不影响）、被迁移程序的可执行文件在位。

## 5. 顺手：设 Chrome 默认页（必须 Chrome 已退出，否则退出时被覆写）
`User Data/Default/Preferences` 里改：`homepage="https://www.bing.com/"`、`homepage_is_newtabpage=false`、`browser.show_home_button=true`、`session.restore_on_startup=4`、`session.startup_urls=[...]`、`newtab_page_location_override=...`；先备份 Preferences。默认搜索引擎由 HMAC 签名保护，改文件无效，只能走设置页。

## 坑
- **把当前 shell 所在的目录搬走/删掉后，后面每条 `terminal` 调用都会先 `cd` 到那个已不存在的路径而整条命令失败**（报 `line N: cd: <path>: No such file or directory`，exit 126，连 `python -c` 都跑不到）。搬完目录立刻给后续调用带 `workdir=C:/Users/<user>`，别指望 `cd ~ &&` 能救——cd 发生在它之前。
- `Clear-RecycleBin` 常报完成但空间不放，直接删 `$Recycle.Bin/<SID>/$R*`。
- 托管 venv 常常没有 pip；需要 Python 库（paramiko 之类）时**先补 pip 再装**：`python -m ensurepip --upgrade && python -m pip install <pkg>`（实测 paramiko 5.x 装得上，之后密码 SSH/SFTP 传文件都不用再靠 pty 硬敲）。装包失败才退回系统自带二进制或 PowerShell。
- 杀 GUI（Feishu/微信）属"只可停不可起"：停下后告诉老倪自己双击启动，并先把快捷方式/Run 项指到新路径。
- 一次删多个注册表键会触发审批；批处理里先干不可逆的活，注册表清理留到最后单独做。
