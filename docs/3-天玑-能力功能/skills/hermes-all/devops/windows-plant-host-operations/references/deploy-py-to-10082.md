# 把单个 .py 部署到工控机 10082 并重启服务（实测跑通的路线）

适用于 `D:\xspace\ultralytics_AOI\cam_finger_10082_work_v*.py` 这类「只在工控机上、本机没有副本」的服务脚本。

## 1. 上传：本机 HTTP + 工控机拉取（别用 base64 通道）

`tools/win_cmd.py` 的 PowerShell 通道对**超长回执**只回 tag（15B），base64 传文件必然丢内容。定式：

```bash
# 本机（/tmp 里放待传文件），必须用 background=true 起，否则前台 `( ... &)` 会被杀
cd /tmp && python3 -m http.server 8899 --directory /tmp
```
```powershell
# 工控机：拉取 + 立刻回 sha256
Invoke-WebRequest -Uri http://192.168.23.50:8899/up_v20.py -OutFile D:\xspace\ultralytics_AOI\cam_finger_10082_work_v20.py -UseBasicParsing;
(Get-FileHash D:\xspace\ultralytics_AOI\cam_finger_10082_work_v20.py -Algorithm SHA256).Hash.ToLower()
```
本机 `sha256sum` 与回读值**必须逐字符相同**再往下走。

## 2. 解释器路径：从**在跑进程**的命令行取，不要猜

`C:\Program Files\Python310\python.exe` 在这台机上**不存在**（踩过：直接拿它 `py_compile` 得到的是
`COMPILE_FAIL`/`CommandNotFoundException`，看着像代码坏了，其实是解释器路径错）。

```powershell
$c = Get-NetTCPConnection -LocalPort 10082 -State Listen -ErrorAction SilentlyContinue
$p = $c.OwningProcess
(Get-CimInstance Win32_Process -Filter "ProcessId=$p").CommandLine
# 实测：C:\Users\admin\AppData\Local\Programs\Python\Python310\python.exe cam_finger_10082_work_v20.py
```

`Get-Command python` 在该会话里可能是空的（PATH 没配），所以**只认进程命令行**。

## 3. 编译校验 → 杀监听 pid → 等保活拉起

```powershell
& "C:\Users\admin\AppData\Local\Programs\Python\Python310\python.exe" -m py_compile D:\xspace\ultralytics_AOI\cam_finger_10082_work_v20.py;
if ($?) {"COMPILE_OK"} else {"COMPILE_FAIL"}
# 通过后再杀：
$c = Get-NetTCPConnection -LocalPort 10082 -State Listen -ErrorAction SilentlyContinue
if ($c) { Stop-Process -Id $c.OwningProcess -Force; "KILLED" }
```

- **杀掉后由 `ZMAX_AOI_KeepAlive` 计划任务拉起**，实测恢复 **30~65s**（不是秒级）——用
  `for i in $(seq 1 20); do sleep 5; curl -s http://192.168.23.23:10082/param && break; done` 轮询，别只看一次。
- **不要先 `Stop-Process` 再编译**：编译失败时服务已经停了，白丢一次产线检测。
- 报错要看正文时用 `2>&1 | Select-Object -Last 4 | Out-String`；不带 `2>&1` 只会回一句 `COMPILE_FAIL`。

## 4. 验收（缺一不算成功）

```
GET /param          → 现场档位原值还在（如 700us / 16.38dB；重启会按 persist 复原）
GET /picture?kind=origin&grab=1 → 真图尺寸/均值正常（不是全黑 0 字节）
改动对应的能力端点 → 回读新行为（例：/region、判据图尺寸）
```

## 5. 定式教训

- **改完不等重启就验证 = 验的是旧进程**：`/param` 之类只读端点会立刻回 200，很容易误判“已生效”。
- **先备份再覆盖**：`Copy-Item ... .bak_<日期>_<标记>`，回滚只需一条命令。
- **`pkill -f <pattern>` 会杀掉自己那条 shell**（命令行里含同一串）——按端口/pid 定位（`ss -ltnp`）再 kill。
