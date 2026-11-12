# 从零给一台 Windows 机装上「会敲命令的通道 + 脑子」

适用：用户一台普通的 Windows 笔记本/台式机（可能是他随身带的那台），里面只有 Windows 本身，
你要在上面跑 Hermes、并把主脑（记忆/技能/cron/凭证）灌下去、之后自动双向同步。

## 1. 先拿到一条能执行命令的通道

Windows 默认把 ping / 22 / 445 / 3389 / 5985 全关。**探不到 ≠ 没上线**：
用户说"已经上线了"时，先要它自己的 IP（热点网关 IP / DHCP 客户表 / 他那句 `ipconfig`），
再从"它能执行命令"反推通道。

### 1.1 sshd（首选，但要先装得上）

- 可选组件常**静默失败**：`Add-WindowsCapability` 无错无输出、`Get-Service sshd` 不存在、
  能力状态仍是 `NotPresent`。它不报错 ≠ 装好了。
- 能力名的连写波浪号 `OpenSSH.Server~~~~0.0.1.0` 经粘贴链路会变 `OpenSSH.Server0.0.1.0`，命令照样"成功"但什么都没装。
  写成先取名字再用：
  ```powershell
  $cap = Get-WindowsCapability -Online | Where-Object { $_.Name -like 'OpenSSH.Server*' }
  $cap | Format-Table Name, State
  Add-WindowsCapability -Online -Name $cap.Name
  ```
- GitHub release 在国内热点上常常 504（`objects.githubusercontent.com` 被断），所以"下载 OpenSSH-Win64.zip 再
  `install-sshd.ps1`"这条备选并不稳；别把宝押在它上面。

### 1.2 WinRM（零下载，国内网络下最可靠）

```powershell
Enable-PSRemoting -Force -SkipNetworkProfileCheck
New-NetFirewallRule -DisplayName "WinRM-5985" -Direction Inbound -Protocol TCP -LocalPort 5985 -Action Allow -ErrorAction SilentlyContinue
Get-Service WinRM | Format-Table Status, StartType     # 要 Running / Automatic
```

Linux 侧：`python3 -m pip install --user pywinrm`，然后 **NTLM + 本地账号**（不需要改
`AllowUnencrypted` / `Basic`，也不用域）：

```python
import winrm
s = winrm.Session("http://<ip>:5985/wsman", auth=("<user>", "<pass>"),
                  transport="ntlm", read_timeout_sec=60, operation_timeout_sec=50)
r = s.run_ps("$env:COMPUTERNAME + '|' + $env:USERNAME")
print(r.status_code, r.std_out.decode(errors="replace"))
```

- 账号名先试裸用户名，再试 `.\user` / `MACHINE\user`。
- `COMPUTERNAME` 与热点 SSID 同名时，说明网关那台就是他这台机器本身。
- WinRM 跑的是**同一台机器上的 PowerShell**，能读 `$env:USERPROFILE`、能 `Start-Process`、能写文件——够了。

## 2. 装 Hermes（脱离会话跑，别在前台等）

通道一断，前台进程就死；安装器要 5~15 分钟。落成文件 + `Start-Process` + 轮询日志：

```powershell
$p = "C:\Users\<u>\hermes_install.ps1"
[IO.File]::WriteAllBytes($p, [Convert]::FromBase64String("<ASCII 脚本的 base64>"))
$out = "C:\Users\<u>\hermes_install.out"; $err = "C:\Users\<u>\hermes_install.err"
$proc = Start-Process powershell -ArgumentList "-NoProfile","-ExecutionPolicy","Bypass","-File",$p `
          -RedirectStandardOutput $out -RedirectStandardError $err -PassThru -WindowStyle Hidden
$proc.Id
```

脚本内容（官方一把梭）：
```powershell
$ProgressPreference='SilentlyContinue'
$sb = [scriptblock]::Create((irm 'https://hermes-agent.nousresearch.com/install.ps1' -UseBasicParsing))
& $sb -NonInteractive
```

- **`-NonInteractive` 靠 `& $sb -NonInteractive` 传**；`iex (...)` 不吃参数。
- 日志停在 `-> Building the hermes command and apps` 不动是正常的（那一步在拉组件/编译启动器），
  判据是 `C:\Users\<u>\AppData\Local\hermes\bin\hermes.exe` 出现且 `hermes --version` 能跑。
- 安装 home 是 `%LOCALAPPDATA%\hermes`（不是 `~/.hermes`）。重定向出来的 `.out/.err` 里可能有
  "Not granting the current user access ... while elevated" 之类警告，不影响可用性。

### 2.1 脚本内容规则（PS 5.1）

- 🔴 **纯 ASCII**：无 BOM 的 UTF-8 里带中文 ⇒ PS 5.1 按 ANSI 读 ⇒ 引号被吞 ⇒ `ParserError: 字符串缺少终止符`。
- 🔴 **不支持 `?.`**（null 条件运算符）⇒ `UnexpectedToken`。写 `if ($x) { $x.Length }`。
- 落文件用 `[IO.File]::WriteAllBytes` 写 **ASCII 字节**（不要 UTF-16，也不要不带 BOM 的 UTF-16）。
- 单条 WinRM/PowerShell 命令太大会被拒（`The command line is too long.`），大文件分片
  `Add-Content -NoNewline` 到 `.b64` 再一次性 `[Convert]::FromBase64String`；二进制/大文本用 **scp**。

## 3. sshd 通了之后的定式

```bash
ssh-keygen -R <ip>        # 同一 IP 换了主人 ⇒ 已知主机键变了, 先清
sshpass -p '<pass>' ssh -o StrictHostKeyChecking=accept-new \
  -o IdentitiesOnly=yes -o PubkeyAuthentication=no \
  -o PreferredAuthentications=password <user>@<ip> 'powershell -NoProfile -Command "hostname"'
```

- 首轮不加上面那几个选项会撞 `Too many authentication failures`（本地 agent 里一串 key 挨个试）。
- **远程默认 shell 是 cmd.exe**：`;` 不是分隔符。`tar -C C:/x -xf - ; echo rc` 会把 `;`、`echo`、`rc` 当成 tar 成员
  ⇒ `Not found in archive`。用 `&&`。
- **别给 Windows 路径套 POSIX 单引号**：`tar -C 'C:/Users/x' -xf -` 在 cmd 里引号会被字面传下去 ⇒ 解包失败。
- 中文输出会乱码（GBK 控制台）：命令里带 `[Console]::OutputEncoding=[Text.Encoding]::UTF8`，或只用 ASCII 输出。

### 3.1 公钥免密

- 管理员账号：`C:\ProgramData\ssh\administrators_authorized_keys`，并
  `icacls <file> /inheritance:r /grant Administrators:F /grant SYSTEM:F`。
- 普通账号：`%USERPROFILE%\.ssh\authorized_keys`。
- **两处都写一份**最省事（同一个用户可能既是管理员又走普通路径）。
- 验：`ssh -o BatchMode=yes -o IdentitiesOnly=yes -i <key> <user>@<ip> 'powershell -NoProfile -Command "hostname"'`。

## 4. 灌脑子：tar over ssh（Windows 没有 rsync）

```bash
cd ~/.hermes && tar -cf - memories skills cron config.yaml auth.json .env channel_directory.json \
  | ssh -i ~/.ssh/id_ed25519 <user>@<ip> 'tar -C C:/Users/<u>/AppData/Local/hermes -xf - && echo push-ok'
```

- 只灌这几样。路径不套引号（见上），`&& echo push-ok` 用来看解包是否真成功。
- 🔴 **`.env` 必灌**：模型 key 与 `*_BASE_URL` 在里面；缺它 agent 起来也答不了话（会去挑别的 provider、
  报 "not logged into ..." 或模型 404）。
  `config.yaml` 只在**首次建号**时灌一次（把主脑的 `model` 段带过来，再
  `hermes config set model.provider <p>` + `hermes config set model.default <model>` 固化）；
  **日常定时同步不要再推它** —— 目标机常有机器级 `ANTHROPIC_*` 环境变量，一推就把 `provider` 覆盖回默认，
  症状是“改完下一拍又 404”。
- 用管道喂 stdin（`$b=[Console]::In.ReadToEnd()`）会**改变字节**（换行/编码），md5 对不上；要动二进制/大文件一律 scp。
- 对齐只认回读：`certutil -hashfile <file> MD5` == 本地 `md5sum`。至少查 `MEMORY.md`、`config.yaml`、`.env` 三件。
- `state.db` / `sessions` / `cache` / `logs` 一律不同步（两边都在写）。

## 5. 定时双向同步（本机主脑，无 rsync 版）

本机 systemd oneshot + timer（10 分钟一拍），探活失败就写一行 skip 退出 0：

- 探活：依次试候选 IP（热点网关 IP + 它加入过的 wifi IP 都可能变），`ssh ... echo ok` 通了就用。
- 上行回灌：只捞 `memories/` 里**比本机新**的文件。远侧 mtime 取 epoch：
  `[int][double]::Parse((Get-Date $_.LastWriteTimeUtc -UFormat %s))`，本地 `stat -c %Y`，差 >60s 才算远端更新。
  覆盖前本机留 `~/.hermes/sync_bak/<ts>/`。
- 下行：`tar` 推小件（memories / cron / auth.json / .env / channel_directory.json）—— **不含 `config.yaml`**
  （推它会把目标机固化的 `model.provider` 覆盖回默认，每拍复现一次 404）。
  **`skills/` 几十 MB，只在整点后那几拍推**（`[ "$(date +%M)" -lt 10 ]`），否则每拍几十 MB 白跑。
- 覆盖前远侧备份一条 `powershell -Command` 里跑完：
  `if(Test-Path <src>){ robocopy <src> <bak> /E /NFL /NDL /NJH /NJS | Out-Null }`。
- 日志一行定论：`host=<ip> md5=same|DIFF up=<n> full=0|1 rc=<n>`；`DIFF` 时单独打 WARN 行并把两边的 md5 都写出来。

### 5.1 同步"一直在 skip"：先查候选 IP 表，再查是谁在跑

- **跳过的原文里就写着它试过的 IP**：`skip: Windows 不在网 (试过 A B C)`。目标机换网/换热点后 DHCP 会换地址，
  脚本里那张候选表就成了化石 —— 每拍重复同一行 skip，看起来像"机器没开机"，其实是地址变了。
  判据：`ip -4 addr` 看本机在哪个网段 → 探目标机 `ping` + `ssh ... echo ok` 通 → **把当前 IP 加到候选表最前面**
  （其余旧地址留着当兜底），改完 `bash -n` 过语法再跑。
- 🔴 **sudo 跑 = 假 skip**：脚本里 `KEY="$HOME/.ssh/id_ed25519"`、`LOG="$HOME/.hermes/logs/..."` 都是按 `$HOME` 算的；
  `sudo <脚本>` 会 `HOME=/root` ⇒ 找不到 ubuntu 的私钥 ⇒ 一路 skip，而且日志写进 `/root/.hermes/logs/`。
  表象极具误导性：`~/.hermes/logs/` 那份**一行没长**，你会以为脚本没执行。
  定式：`grep '^User=' /etc/systemd/system/<name>.service` 拿到属主 → `sudo -u <user> -H <脚本> --full`；
  更硬的验证是 `sudo systemctl start <name>.service` 直接走 timer 的真实路径（同样的 User、同样的 HOME），
  然后**在属主那份日志里**确认出现新行。
- 收工 `sudo cat /root/.hermes/logs/<name>.log` 看有没有被错跑出来的那份，有就说明中间曾用错身份。

### 5.2 覆盖前先 diff 两侧记忆（mtime/大小都不是内容判据）

- 同步前把远端两份文件拉到本地 scratch 目录再比：`USER.md` 常常一字不差，`MEMORY.md` 常有几行旧说法。
- **只推不回灌**的判据是**内容子集**，不是时间戳：远端可能更大（条目更啰嗦）但整篇更旧 ——
  实测远端 3401B / 本机 3390B，diff 出来远端只有 3 行旧版本（版本号、措辞），没有本机缺的事实。
  回灌规则（远端 mtime 更新才拉）本身是对的，但**先 diff 一遍再决定**，别让"大小更大"或"看起来更全"骗你覆盖。
- 拉文件一律 **scp**：`type C:/...` 走 cmd 常回 0 字节，`Get-Content -Raw` 会把无 BOM 的 UTF-8 当 GBK 读出乱码
  （满屏 `杩滅▼`）；`scp -q -i <key> <user>@<ip>:C:/Users/<u>/AppData/Local/hermes/memories/MEMORY.md <本地名>` 二进制安全。
  中文内容经 `ssh ... powershell` 回显只在"看一眼"时可用，别拿它落盘。
- 验收三件：两侧 `md5sum` vs `certutil -hashfile ... MD5` 逐位相同（MEMORY.md + USER.md 都查）· 日志一行 `md5=same` ·
  skills 条目数可比（`tar` 只增不删，远端多出来的几条是她自己写的，不是故障）。

## 6. "上不了 deepseek"：provider 判别顺序

前一步过不了就别往下猜：

1. `hermes auth list` —— 谁 `priority=0`。机器级 `ANTHROPIC_API_KEY` 这类环境变量会被自动注册成凭证且很靠前，
   这是"明明配了 A 却走 B"的头号原因。`hermes auth status <provider>` 看单个是否 `logged in`。
2. `hermes config get model` —— 顶层 `model:` 应是映射 `{default: <model>, provider: <p>}`。
   **顶层 `provider:` 是陈旧键**，`hermes doctor` 会示 `Stale root-level config keys: provider (should be under 'model:' section)`；
   正确写法 `hermes config set model.provider <p>`（`config set provider` 会存下并警告"不被识别"）。
3. **改配置修不了已有会话**：`state.db` 的 `sessions.model_config` 可能钉着旧安装/网关留下的
   `gateway_runtime: {provider: anthropic, base_url: https://api.moonshot.cn/anthropic}`。交互式会话按它走 ⇒
   配置里模型是对的、请求却发去那个 anthropic 兼容口、回 `HTTP 404: Not found the model <m>`。
   判据：**`hermes -z`（oneshot 新会话）能过，他手敲的 TUI 报 404** —— 这个"一条通一条不通"基本就是它。
   修法（Windows 上没 python/sqlite3 也没关系，用 Hermes 自带 venv 的 python：
   `C:\Users\<u>\AppData\Local\hermes\installs\*\environments\*\venv\Scripts\python.exe`）。
   **扫全表、不要按 `source='local'` 过滤**（钉旧值的会话可能十几条、source 也不一定 local），
   且要把 `provider`/`base_url` **改成目标值**，只 pop 会被别的写入方再补回旧值：
   ```python
   import json, sqlite3
   con = sqlite3.connect(r"C:\Users\<u>\AppData\Local\hermes\state.db", timeout=15)
   con.execute("PRAGMA journal_mode=WAL")
   for sid, mc in con.execute("select id, model_config from sessions").fetchall():
       d = json.loads(mc or "{}")
       gr = d.get("gateway_runtime")
       if isinstance(gr, dict) and str(gr.get("provider", "")).lower() != "deepseek":
           gr["provider"] = "deepseek"; gr["base_url"] = "https://api.deepseek.com"
           d["gateway_runtime"] = gr
           con.execute("update sessions set model_config=?, billing_provider=?, billing_base_url=NULL where id=?",
                       (json.dumps(d), "deepseek", sid))
   con.commit()
   ```
   回读口径：`select id,billing_provider,model_config from sessions order by rowid desc limit 4`，
   新区应当 `provider=deepseek @ https://api.deepseek.com`；`hermes -z` 连跑两句都要回。
   改完让他**重开会话**（旧会话进程里还认旧值；`/model` 选一次也立刻生效）。
4. 仍未解才动 `auth.json` 的凭证与**机器级**环境变量（后者影响机器上别的程序，先说再动）。

## 7. 收尾口径

- "装好了"带三证：`hermes --version` 输出、`hermes -z` 真跑一轮的回答、`MEMORY.md` 两边 md5 相同。
- 目标机上 `hermes gateway run` 在跑但 `gateway_state.json` 里 `"platforms": {}` ⇒ **没有平台连着**，
  不会跟主脑抢飞书；报"双 gateway"风险前先看这个字段。
- 用户在目标机留下的调试脚本会堆满 `C:\Users\<u>\`：**收进一个 `_hermes_setup_junk\` 子目录**（不删），
  然后报"根目录 0 个散文件"。
- Wi-Fi 漫游会把"我连的是哪张网"变掉（本机自动跳到信号更强的办公网 ⇒ 突然 `No route to host`）：
  `nmcli con mod <名> connection.autoconnect-priority 100` 钉住目标网络，并按"目标机在哪个网"决定连哪个 SSID；
  目标机自己开热点时，它的旧 wifi IP 会消失，只能走热点网关 IP。
