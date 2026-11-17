# 交付给「无 SSH 的 Windows 操作员」的可执行件

操作员在自己屏幕上双击运行，没有命令行、没有 SSH。交付件必须按下面的口径做，否则他点完只会说「没反应」。

## 1. 入口一律 `.bat`，绝不交 `.ps1` 当入口

Windows 双击 `.ps1` 默认用**记事本打开**，不执行 —— 双击一百次也不会有任何动作，而文件看起来完全正常。

每个 ps1 配一个 bat 薄壳（内容纯 ASCII）：

```bat
@echo off
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0X.ps1" %*
```

- `%~dp0` 让脚本在任意工作目录下都能找到同目录的 ps1（操作员可能从桌面快捷方式点）。
- `%*` 透传参数 ⇒ 远程验证能跑 `X.bat -NoPause`，走的就是他双击那条路，不是另写一条测试路径。
- `chcp 65001` 让控制台按 UTF-8 显示，否则 ps1 里的中文全是乱码。

生成方式（避免传输编码争议）：

```powershell
$s = "@echo off`r`nchcp 65001 >nul`r`npowershell -NoProfile -ExecutionPolicy Bypass -File `"%~dp0X.ps1`" %*`r`n"
[IO.File]::WriteAllText('D:\path\X.bat', $s, [Text.Encoding]::ASCII)
```

文件名也用 ASCII（`stop_AOI.bat`），中文文件名的 bat 在跨工具传输时容易出编码岔子。

操作员不知道东西装在哪时，别让他记路径 —— **桌面放三个快捷方式**（公共桌面更省事：
`[Environment]::GetFolderPath('CommonDesktopDirectory')`）：

```powershell
$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut((Join-Path $desk 'AOI-Folder.lnk')); $s.TargetPath = $dir; $s.Save()   # 打开目录
$s = $ws.CreateShortcut((Join-Path $desk 'AOI-Start.lnk'))
$s.TargetPath = (Join-Path $dir 'start_X.bat'); $s.WorkingDirectory = $dir; $s.Save()
$s = $ws.CreateShortcut((Join-Path $desk 'AOI-Stop.lnk'))
$s.TargetPath = (Join-Path $dir 'stop_X.bat');  $s.WorkingDirectory = $dir; $s.Save()
```

- 快捷方式的**名字也必须 ASCII**：经反向通道下发的命令一旦含中文，写出来的**文件名本身**就是乱码
  （回执里显示 `AOI 鍏抽棴.lnk`）—— 而 `Get-ChildItem -Filter 'AOI*'` 照样匹配得到、`Test-Path` 目标也是 True,
  于是很容易当成"只是显示问题"放过。判据同 §3：读文件名原始字节，别读显示。
- 建完**回读三样**：`CreateShortcut(<lnk>).TargetPath`、`Test-Path` 该目标、目录里 `AOI*.lnk` 的条数。
- README 第一屏要写明「文件都在 `<绝对路径>`」+ 这三个快捷方式名 —— 操作员不会自己去翻盘。

## 2. 窗口必须停住

ps1 末尾 `ReadKey` 让窗口留在原地等人按键 —— 这是**功能**不是累赘：闪退会让操作员以为没执行。
但远程/自动化调用会因此挂死 ⇒ 给 ps1 加 `[switch]$NoPause`，末尾 `if (-not $NoPause) { ... ReadKey }`。

## 3. 编码：乱码要看字节，不要看显示

回执通道里看到 `鍏抽棴` 这种，**不能**据此判断脚本输出坏了。`[Console]::OutputEncoding=UTF8` 也治不了 —— **父 PowerShell 按它自己的编码解子进程输出**，子进程设什么没用。

判据只认磁盘原始字节：

```powershell
cmd /c "X.bat > out.txt 2>&1"
$t = [IO.File]::ReadAllText('out.txt', [Text.Encoding]::UTF8)
([IO.File]::ReadAllBytes('out.txt'))[0..5] -join ','
```

中文「中」= `228,184,173` = `0xE4B8AD`。字节对 ⇒ 控制台显示正常，**别去改脚本编码**。

要验**整段中文内容**（README、配置）有没有在传输里坏掉，别逐行看乱码 —— 回传 base64、在本地解码：

```powershell
$b = [IO.File]::ReadAllBytes('<绝对路径>')
'LEN=' + $b.Length
[Convert]::ToBase64String($b[0..([Math]::Min(360,$b.Length)-1)])
```

base64 是纯 ASCII，不会被通道编码破坏；`LEN` 顺手核对字节数。这是「机器上的文件是对的、乱码只是我这边显示」
最硬的一条证据 —— 没有它就只能停在「应该是编码问题」这种不可交付的结论上。

这条与「ps1 里塞中文注释把脚本解析搞坏」是**两码事**：那个查 `nonascii count`（>0 就是元凶），这个查字节序。两个都要会分。

## 4. 反复叮嘱的操作必须写进脚本，不要只写进 README

例：一个服务有「保活/看门狗每分钟检查一次、发现没在听就拉起来」的机制，那么**停止脚本必须同时停掉那个机制并保持停用**，否则一分钟后服务自己回来，操作员会说「关了又开了」。
- 停止：`Disable-ScheduledTask` → 杀进程 → 复核端口 → 明确打印「保活已停用，不会自动回来」。
- 启动：拉起 → 等就绪判据 → 恢复 `Enable-ScheduledTask`。
- 停/启**成对交付**：只给 stop 不给 start，等于给了他一条有去无回的路。

## 5. 判据要选「服务真的能干活」的那个，不是「端口在听」

端口 LISTEN 可能是个哑进程/旧版本。就绪判据用程序自己的业务路由（如 `GET /storage` 返回 200、抓一帧图字节 > 0）。
冷启动可能要 60~90s，超时给足并在脚本里就等，别让操作员手动重试。

## 6. 脚本里的 PowerShell 坑

- `$pid` 是**保留变量**（当前进程 id），赋值会静默失败 ⇒ 一律用 `$procId`。
- 按端口找进程，不按进程名杀（`python.exe` 会误杀同机别的服务）：
  `(Get-NetTCPConnection -LocalPort $p -State Listen).OwningProcess`。
- 命令串里 `&&` 不是合法分隔符 ⇒ 用 `;`。
- 给 PS 拼字符串**绝不用 `.format()`** —— PS 的 `{ }` 会被当占位符。

## 7. 相对路径：`cd` 只改 `$PWD`，不改 .NET 的进程工作目录

反向通道把命令落成 `C:\Windows\TEMP\*.ps1` 再执行 ⇒ **进程工作目录是 `C:\Windows\system32`**。

- **PS cmdlet 认 `cd`**：`cd 'D:\xspace\x'; Invoke-WebRequest -OutFile 'a.txt'` 会落在 `D:\xspace\x\a.txt`。
- **.NET 静态方法不认**：同一个脚本里 `[IO.File]::ReadAllLines('a.txt', UTF8)` 报
  `Could not find file 'C:\Windows\system32\a.txt'` —— `cd` 改的是 `$PWD`，而 `[IO.File]` 解析的是
  `[Environment]::CurrentDirectory`（进程级，没跟着变）。

⇒ 一条脚本里混用 cmdlet 与 .NET 调用时，**.NET 那一侧一律写绝对路径**（`[IO.File]::*` / `[System.Drawing]*` /
任何 `::` 静态方法）。症状是同一个文件"前一句刚写成功、后一句读不到"，极易误判成文件没写进去。

## 8. README / 命令速查表：每条命令先在机器上跑过，示例返回用实测抓的

操作员照着 README 抄命令，一条写偏就等于没交付。定式：

- **每条命令先在机器上真跑一遍**再写进文档 —— 引号/转义写错会自己暴露。
  PS 侧统一给 `irm`（= `Invoke-RestMethod`）而不是 `curl`：
  `irm 'http://h:port/x' -Method Post -ContentType 'application/json' -Body '{"a":1}'`
  单行、不用管 cmd 与 PS 两套转义规则。
- 🔴 **只读端点的示例返回，要先触发一次真动作才有数据**：刚重启的服务 `/last_result`、`/crop_info`、`/region`
  全是 404「尚无…」，照它抄下来的示例就是一片红字。先 POST 一次真检测（会真拍照，先确认产线空闲），
  再逐个抓返回填进文档。
- 🔴 **`irm` 碰到 4xx 抛 WebException，不是返回对象**：没数据时 PowerShell 打一整屏红字，操作员会当成服务坏了。
  文档里写成 `irm '<url>' -ErrorAction SilentlyContinue`，或 `try { irm ... } catch { $_.ErrorDetails.Message }`。
- **示例必须是真抓的 JSON，长数组标「...(略)」**，关键字段后面跟 `//` 说明并标出哪些是现场该看的
  （例画质的 `gold_px` / `bright_frac` / `focus`）。别编一份"看起来像"的返回 —— 操作员会拿它当契约去写对接。
- **分清「源码兜底常量」与「现役值」**：有的接口同时回 `now` 与 `file_defaults`（例 `/param` 的 20000/8 vs 实际 8000/2.0），
  文档必须点明「看 now」，否则他按 file_defaults 排查会一路错。
- **分发前核对待发件在磁盘上的字节数**（`os.path.getsize`）：写文件那一步也要复核，
  报「写成功」而盘上仍是上一版时，整轮发出去的都是旧文 —— 靠回读 `LEN=` 才发现。
