# Windows 主机没开机时的离线两阶段载荷

反向通道(hub/计划任务)只在**目标机已开机且已登录**时存在。目标机休眠、装了双系统、或用 LiveUSB 起的 Linux 时,
你唯一的通道是"把东西放到一块 Windows 也看得见的分区上, 让它自己跑"。本文是可复用的落地形状。

## 1. 先判现场(只读)

```bash
lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT     # 根是 /dev/cow 覆盖层 + /cdrom 来自 U 盘分区 ⇒ LiveUSB 会话
sudo efibootmgr -v                            # BootOrder 里 USB 常排第一 ⇒ 重启会回到 U 盘
sudo mkdir -p /mnt/c && sudo mount -o ro /dev/<C盘分区> /mnt/c
ls -l /mnt/c/hiberfil.sys /mnt/c/pagefile.sys  # hiberfil 存在(数 GB)= 休眠/快速启动状态
ls /mnt/c/Users                                # 有哪些 profile、哪个最大(du -sh)
```

判据: **hiberfil.sys 在 ⇒ 这个 NTFS 是休眠态, 从 Linux 挂 rw 写入有把系统写坏的风险**。
⇒ 破坏性操作一律交给 Windows 自己(脚本 + 它自己的 API), 不在休眠卷上离线改 SAM/注册表。
只读挂载取证后用 `sudo umount` 撤掉, 别留 rw 挂载给后来的人用。

## 2. 投递介质: U 盘的 FAT32 分区(不为写 NTFS 冒险)

LiveUSB 的 FAT32 分区在 Windows 里就是一个盘符, 且从 Linux 写它没有任何 hibernation 风险:

```bash
sudo mount -o remount,rw /cdrom            # 常见初始是 ro
sudo mkdir -p /cdrom/<PAYLOAD> && sudo cp -f setup_win.ps1 SETUP_WIN.cmd CHECK_WIN.cmd README.txt /cdrom/<PAYLOAD>/
sudo sync && md5sum setup_win.ps1 /cdrom/<PAYLOAD>/setup_win.ps1   # 逐位核对
```

载荷四件套:

| 文件 | 作用 |
| --- | --- |
| `SETUP_WIN.cmd` | 双击入口: `net session` 判权 → `Start-Process -Verb RunAs` 自提权 → 调 ps1 `-Stage stage1` |
| `setup_win.ps1` | 两阶段主体(`param([ValidateSet('stage1','stage2','check')]$Stage='stage1')`) |
| `CHECK_WIN.cmd` | **只读体检**: 账户清单/profile 体积/C 盘可用/自动登录值/目标软件是否已装/联网可达 —— 先给他看现状再动 |
| `README.txt` | 不可逆清单 + 操作三步 + 怎么关自动登录 + 日志路径 |

## 3. stage1(用户双击, 1 分钟, 只做"能立刻验证"的事)

1. `reg save HKLM\SAM|SECURITY|SYSTEM` → `C:\_zmax_setup\reg_backup\*.hiv`(**先留旧环境**, 出事可离线恢复)。
2. 账户: 内置管理员按 SID 找, 不按名字。
   ```powershell
   $builtin = Get-LocalUser | Where-Object { $_.SID.Value -like '*-500' }
   Rename-LocalUser -Name $builtin.Name -NewName 'admin'      # 已有同名账户则直接复用
   Enable-LocalUser -Name 'admin'
   Set-LocalUser -Name 'admin' -Password (ConvertTo-SecureString 'admin' -AsPlainText -Force) -PasswordNeverExpires $true
   $grp = (Get-LocalGroup | Where-Object { $_.SID.Value -eq 'S-1-5-32-544' }).Name   # 组也按 SID, 中文系统名字不可靠
   Add-LocalGroupMember -Group $grp -Member 'admin'
   ```
   RID 500 的价值: 默认 UAC 不降权(`FilterAdministratorToken=0`), 后面计划任务拿得到真正的管理员令牌。
3. 自动登录(HKLM Winlogon 四键, 顺手删 AutoLogonCount):
   `AutoAdminLogon=1` / `DefaultUserName=<账号>` / `DefaultPassword=<口令>` / `DefaultDomainName=%COMPUTERNAME%`。
   交付时必须给关闭方法(`netplwiz` 取消"必须输入用户名和密码")。
4. 把自己拷到固定位置再注册下一阶段(**U 盘随时可能被拔**):
   ```powershell
   Copy-Item $PSCommandPath 'C:\_zmax_setup\setup_win.ps1' -Force
   schtasks /create /tn '<名>' /tr 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\_zmax_setup\setup_win.ps1" -Stage stage2' `
            /sc ONLOGON /ru admin /rp admin /rl HIGHEST /f
   ```
   `ONLOGON + /rl HIGHEST + /ru <新管理员>` 保证"换账号后的第一次登录"就跑, 且是提权上下文。
   用 `schtasks /query /tn <名>` 回读确认注册成功再继续。
5. 删其它账户 `foreach ($u in Get-LocalUser) { if ($keep -contains $u.Name) {continue}; try { Remove-LocalUser $u.Name } catch { 记日志留给 stage2 } }`。
   保留 `DefaultAccount` / `WDAGUtilityAccount` / `Guest` 等系统保留账户 —— 它们删不掉也不该删, 交付时说明。
6. 写报告 + 告诉他"重启后自动进新账号, 第二次登录时继续"。

## 4. stage2(新管理员首登自动跑, 重活+装软件)

- 幂等: 跑完写 `C:\_zmax_setup\stage2.done`, 开头见到就退出; 末尾 `schtasks /delete /tn <名> /f`。
- **当前登录用户删不掉** ⇒ stage1 删不掉的账户、以及它的 profile 目录, 全部延到 stage2(此时已换账号)。
- 删 profile(实测 31GB 那种):
  ```powershell
  takeown /f <path> /r /d Y /a;  icacls <path> /grant "*S-1-5-32-544:(OI)(CI)F" /t /c /q
  Remove-Item <path> -Recurse -Force -ErrorAction SilentlyContinue
  if (Test-Path <path>) { cmd /c rd /s /q "<path>" }      # 兜底
  Get-ChildItem C:\Users -Directory | Where-Object { $_.Name -notin @('Public','Default','<新账号>') } | % { 同上 }
  ```
  授权用 `*S-1-5-32-544`(SID 字面量), 别硬编码 `Administrators`。
- 清孤儿: `HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList` 下 `ProfileImagePath` 指向已不存在目录的项删掉(跳过新账号)。
- 装软件走官方安装器的一次性入口, 别手搓解压: 例 `iex (irm https://hermes-agent.nousresearch.com/install.ps1)` 的等价脚本块调用
  `& ([scriptblock]::Create((Invoke-RestMethod <url> -UseBasicParsing))) -NonInteractive -HermesHome <dir>`,
  并把数据目录固化(机器级 `HERMES_HOME`)。
- 装完**回读验证**而不是只报"已安装": `hermes --version`、`hermes config get model`、`Get-LocalUser` 清单、`C:\Users` 现存目录、C 盘可用空间, 全写进 `REPORT.txt` 并 `Start-Process notepad <report>`。

## 5. 交付前的离线校验(不校验就是让用户替你试错)

1. **语法**: 在 Linux 上装一个 pwsh 只用来解析:
   ```bash
   curl -sL -o pwsh.tgz https://github.com/PowerShell/PowerShell/releases/download/v7.4.6/powershell-7.4.6-linux-x64.tar.gz
   mkdir -p pwsh && tar xzf pwsh.tgz -C pwsh && chmod +x pwsh/pwsh
   # [Parser]::ParseFile(<ps1>,[ref]$tokens,[ref]$errs) → 打印 $errs 为空才算过
   ```
   PS7 解析器足够抓 PS 5.1 的语法错(引号/嵌套/花括号); 它抓不到的是 cmdlet 语义, 那部分靠"只用长期存在的 API"。
2. **目标安装器的参数名**: 下载并解析它的 param block, 确认你真在用 `-NonInteractive`/`-HermesHome` 这类参数, 而不是凭记忆写。
3. **CLI 键名本机实测**: 同一套 CLI 在本机跑一次 `config get <key>` 再写进脚本 —— 例如配置里是顶层 `model:`,
   写 `config set model.default` 会被拒。
4. **编码**: ps1 用 **UTF-8 BOM + CRLF**(PS 5.1 无 BOM 读中文会乱码); `.cmd` 只用 ASCII + CRLF(cmd 不吃 BOM)。
   交付后 `file` 一遍确认。

## 6. 引导顺序坑

LiveUSB 把 `EFI USB Device` 排在 BootOrder 首位 ⇒ 用户重启又回到 U 盘, 而载荷还在 U 盘上 ⇒ 死循环。
```bash
sudo efibootmgr -o <WindowsEntry>,2001,<LinuxEntry>,<USBEntry>   # 把 Windows Boot Manager 提到首位
sudo efibootmgr | grep BootOrder                                # 回读
```
U 盘仍留在 F12 启动菜单里, 交付话术写"正常重启进 Windows, 要用 U 盘就 F12"。

## 7. 交付时要写明的三件事

1. **不可逆清单**(删哪些账户、删哪些目录、多少 GB)+ **不动清单**(系统本身、其它数据盘、系统保留账户)。
2. **回滚点**: hive 备份路径; 以及"自动登录怎么关"。
3. **密钥卫生**: 脚本里内嵌的 API key 在 FAT32 上是明文 ⇒ 装完让用户删掉 U 盘上的载荷目录。
