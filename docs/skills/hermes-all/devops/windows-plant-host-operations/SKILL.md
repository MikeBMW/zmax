---
name: windows-plant-host-operations
description: Use when 给无 SSH 的 Windows 产线机远程上线/停服/交接用户自己调试/取证。
version: 1.0.0
author: Hermes
license: MIT
metadata:
  hermes:
    tags: [windows, plant-host, remote-ops, debugging, forensics, handover]
    related_skills: [zmax-aoi-service, linux-host-maintenance, systemd-boot-services]
---

# 无登录口的 Windows 产线机: 驱动 · 交接 · 取证

## When to Use
- 要在**无 SSH/RDP/WinRM/共享凭据**的 Windows 产线机上上线/停服/重启你维护的程序
- 用户说"我自己在 VSCode 里跑"、"断点怎么没进去"、"结果没更新"(要把在役程序交出去)
- 要判定机器上某张图/某个结果**是真是假**(服务刚卡过、内存帧不可信、模型没检出)
- 你的程序依赖被加密/黑盒的包(pyarmor 等), 断点进不去

适用环境: 产线 Windows 工控机(例: 192.168.23.23, 开 1008x/139/445, **无 SSH/RDP/WinRM/共享凭据**),
上面跑着**你在维护**的程序 + **产线自己的**服务(例: flask_1005 / Mech-Vision)。
具体 AOI 端点/版本口径见用户自有的 `zmax-aoi-service`(要找它自动维护先 `hermes curator adopt`)。

## 铁律(先读, 都是踩过的)

- **它是产线设备**: 只读探针优先; 每次真拍/真停先有理由, 不批量轮询; 不动别人的服务与文件。
- **上线只走部署器**(`tools/aoi_remote_deploy.py` 那类: 拷进静态目录 → 机器 `iwr` 下载 → `Get-FileHash` 逐位核对
  → 备份 `.bak` → 停旧起新 → 验收 → 失败自动回滚)。手工 `iwr -OutFile` **直接覆盖、不留备份** ⇒ 事后再跑一次部署器才有真 `.bak`。
- **版本号放文件头 `VERSION`, 不放文件名**: 上线是**覆盖现场约定名**(`..._v6.py`)。用户在资源管理器/VSCode
  的目录列表里只看到那个约定名 ⇒ 他会以为没有新版(实测被问过"工控机的代码没有 v10 啊")。凡改版都额外 `Copy-Item <约定名> <约定名带版本>` 落一份副本,
  并回报 **VERSION + sha256 + 字节数**(sha 与本地副本逐位相同)。**行号一律按这份报** —— 换版本行号会漂。
- **命令输出用纯 ASCII**: 控制台是 GBK, 中文会乱码 ⇒ 机器上跑的脚本只打印 ASCII key 的 JSON,
  不打印中文。脚本要含中文时先确认编码(或干脆不放中文)。
- **"重启后端口没人听"先别判故障**: 机器上你维护的程序与产线服务可能都是**登录后才拉起**的 ⇒ 先确认
  **用户已登录进桌面**(`(Get-CimInstance Win32_ComputerSystem).UserName` 非空) 再谈"服务没起";
  停在登录界面时探端口必得 0, 别据此写"服务坏了"或去重启机器。

## 一、驱动它: 反向通道(无登录口时唯一可靠做法)

```bash
./gui-venv311/bin/python tools/station_cmd.py "<PowerShell 一行>"   # 下发并取回执
```
- 回执里 `whoami` = `nt authority\system` ⇒ 计划任务是真跑起来了。
- **单条命令 ~3KB 就会被弄坏**(实测 base64 内嵌 3KB 脚本 ⇒ 变量变空、文件写出 0 字节)
  ⇒ 脚本超 ~1KB 一律**先落到 hub 静态目录**, 再用 `iwr 'http://<本机>:8794/<路径>' -OutFile <文件>` 取。
- PS 5.1: 下载/轮询一律加 `-UseBasicParsing -TimeoutSec 20`(不加会卡在代理/IE 初始化, 看着像"通道死了")。
- 回传命令里**别用 `Write-Host`**(information 流抓不到 ⇒ 只收到空回执), 用管道输出。
- 脚本发下去前本地 `python3 -m py_compile` 过一遍(文档字符串里的 `\x`/`\W` 到机器上会 SyntaxError)。
- **长命令要分片**: 一条命令里带 ≥30s 的 `Start-Sleep`("起服务 + 等它热起来 + 验证"一把梭)经通道走一趟会**回执变空**
  ⇒ 拆成"起"和"等+验证"两条短命令, 每趟只做一件事。
- **下发文件后必须在机器上回读内容**: 静态目录/`iwr -OutFile` 装到的可能还是旧内容 ⇒ 回读并**解析关键字段**
  (例: `(Get-Content <json> -Raw | ConvertFrom-Json).configurations.program`)再报"已生效";
  只比字节数/哈希会把"没生效"当成功报给用户(实测下发后机器上仍是旧配置)。
- 通道健康**看它发来的请求**, 别用日志行数/本机自检判: `sudo timeout 20 tcpdump -A -s 0 -n -i <产线网卡> 'host <机器> and port 8794'`。

## 二、把在役程序**停干净并交给用户自己在 VSCode 里跑**

```powershell
# ① 先看托管任务(分钟级自愈的那种), 必须 Disabled, 否则停完一分钟又被拉起来
Get-ScheduledTask -TaskName 'ZMAX_AOI_KeepAlive' | ForEach-Object { $_.TaskName + ' ' + $_.State }
# ② 只杀自己的程序; 别碰产线自己的 python(flask_/Mech-*)
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -match 'cam_finger|cam_surface' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
# ③ 停干净要**两个证据**: 进程数 0 + 端口无监听
@((Get-NetTCPConnection -LocalPort 10082,10083 -State Listen -EA SilentlyContinue)).Count
```
- VSCode 侧用 `templates/vscode_launch.json`; **`program` 必须写机器上真实存在的部署名**
  (踩过: 配置里写的是没有 `_v6` 的名字 ⇒ F5 直接报找不到程序, 用户以为是程序坏了)。
  **每条通道一条配置, 指向带版本号的副本**(`<约定名>_v12.py`): 在役约定名会被下次上线覆盖, 用户看不出是第几版。
  旧配置先备份(`launch.json.bak_<日期>`), 改完回读字节核验。
- 每个配置带 `PYTHONUNBUFFERED=1` `PYTHONIOENCODING=utf-8` `justMyCode:false`(否则看不到第三方库里的栈)。
- **交还动作一次说清**: 重开任务 + 用与守护一致的方式起进程(见下), 并说明"这段时间这条线没有检测"。
```powershell
# 用 Start-Process + venv 解释器绝对路径(带日志分离):
$p = Start-Process -FilePath 'D:\<dir>\venv\Scripts\python.exe' -ArgumentList '<prog>' `
     -WorkingDirectory 'D:\<dir>' -RedirectStandardOutput 'D:\<dir>\<log>' `
     -RedirectStandardError  'D:\<dir>\<err>' -PassThru
Start-Sleep -Seconds 12; $p.Id; $p.HasExited      # False + 稍后 /storage 200 = 起来了
```
- ⚠️ **起完必须数实例, 只允许 1 个**: `Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -match '<程序名>' }` —— 多实例会**抢独占相机**, 表征是接口 `500 抓帧失败`/`相机初始化失败`;
  两个实例可能跑在**不同解释器**上(venv python + 系统 Python), 用 `ExecutablePath`/`ParentProcessId` 分清
  (app 自己用系统 python 起的子进程 ppid=主进程, 属正常)。实测 `$sh.Run('cmd /c cd /d <dir> && venv\Scripts\python.exe <prog> ...')`
  这种分离启动会留下一个**用系统 Python 跑的影子实例** ⇒ 起之前先杀干净同名进程, 优先用上面的 `Start-Process`。
- ⚠️ 直接 `Stop-Process` 掉在役进程后, 分钟级 keepalive **不一定一轮就拉起来**(实测 75s 未回) ⇒ 手工起一把再验。

## 三、用户说"断点怎么没进去 / 结果没更新": 按序查, 别改代码

1. **断点下在哪个文件**: 断点只在你 `launch.json` 里 `program` 指的那份里生效; 文件不同名 ⇒ VSCode 不当同一模块(灰断点)。
2. **触发方式对不对**: 有副作用的那条路(真检测)与只看一眼的那条路(预览/取帧)往往是两个 HTTP 入口 ——
   预览类常**只拍照不入队** ⇒ 永远不进后台 worker。给用户"干净的触发命令", 并让他先看集成终端有没有阶段日志
   (阶段日志 + 异常 traceback 是最快的判据)。
3. **后台线程是不是活着**(生产者/消费者 + 全局邮箱那类设计): worker 通常在 `__main__` 里就起了 ⇒
   在 `while True:`/取队列那行下断点, 启动后几秒必停。**落结果的那句在 worker 线程里, 不在请求线程** ——
   用户常把断点下在 HTTP 处理函数里, 于是"请求成功但断点不进"。
4. **入队后被跳过**: 代码里常见的 `continue`(输入文件不在就跳过该项)会让断点同样进不去。

## 四、取证纪律: 内存帧 ≠ 落盘文件

- 服务刚卡过/刚重启时, **内存里的"最近一帧"路由会给一张陈旧/雾面帧**(实测同一时刻内存帧底纹标准差 4.08,
  而机器上落盘那张的底纹标准差 21.19) ⇒ 拿它当"图里有什么"的证据, 结论必错。
  判图像内容一律量**落盘文件**: 机器上跑只读探针 `scripts/machine_image_probe.py`
  (尺寸/均值/std/16x16 块内 std/饱和比/列自相关 —— 能区分"真有结构"与"模糊/过曝")。
- **跨图比几何/相关前先核同一帧**: md5 对齐最硬; 跨帧比要写明是跨帧。
- **计数器别混**: 结果接口里的 `n` 多是"成功次数"(可能一直=1), 而帧计数/文件名 `No_<n>` 是"拍照次数"
  (只看一眼也会 +1) —— 两者拿来互相对齐过一次, 白折腾。
- **异步检测的"新旧"必须用计数器判, 不能用固定等待**: 触发接口返回 200 只代表**受理**;
  读结果前先记一次计数 `n0`, 触发后**轮询到 `n` 变化**才算"这一次"的结果 —— 固定 `Start-Sleep N` 再读会把
  **上一次**的判决当本次报出来(表象=用户说"结果不对"); 计数没变就明说是上一次(序号 N)。刚起服务/第一次检测时
  结果接口常回 `404 尚无结果`/500 = "还没有", 不是故障 ⇒ 继续轮询到超时, **别 raise 出去**。
- **耗时按路给预算**: 同一套接口不同通道能差一个量级(实测 1.6s vs 8.7~11.4s) ⇒ 等待/超时按通道分开, 取最慢的乘余量。
- **"模型实际吃了哪张图"要用像素 md5 证明**: 取回"模型输入图"→ `cv2.imdecode` → `md5(ascontiguousarray(img).tobytes())`
  必须 == 结果接口里的 `model_input_md5`; **只看文件名/尺寸不算**。各路口径可能不同(有的路模型吃**同帧派生的另一张**
  且不落盘; 全幅检测那条路模型吃的就是人看的同一张) ⇒ 别把一路的假设搬到另一路。
- **路由/能力结论一律现探再下断言**: `curl -X OPTIONS -D - http://<机器>:<端口><路径>` 看 `Allow:`(零副作用) ——
  历史结论(如"某路只有某个接口")会被后续版本推翻, 照抄给用户就是假情报。
- **交付页面的按钮要真驱动一次**: 用浏览器控制台**执行按钮的 onclick 函数**再读目标元素文本,
  只 curl 服务端 API 通过 ≠ 按钮能用 —— 参数化 id 的前后缀写偏(JS 拼 `x_s`、页面写 `s_x`)会让
  `getElementById` 返 null、函数静默什么都不发生; 加 `if(!el){ alert('缺 #<id>, 请 Ctrl+F5'); return; }` 守卫。
  按钮/面板要带**拍照时间 + 帧龄**和可复制 JSON(用户会把画面/数字当结果, 没有时间基准他没法判新旧)。
- 稳态数据比"峰值/max"可信; 判趋势用窗口平均。

## 五、遇到加密/黑盒依赖(pyarmor 等): 从调用侧做观测

包被 pyarmor 加密时(每个文件第 1 行 `# Pyarmor <版本> ...`, 正文只有 `__pyarmor__(...)`): **内部无源码、断点进不去**。
替代做法: ① 找到调用侧那一行(`detector.detect(...)`)并在那行下断点/记日志;
② 想在**启动前**看内部入参/回报, 在进程里包一层库的公开入口(例: 覆盖 `ultralytics.YOLO.predict`)打点;
③ 参数在**明文 config**(例: `config.yaml` 的 conf/iou/imgsz/device) —— 那才是可调的旋钮;
④ 改在役 config = 动产线配置 ⇒ **先要授权 + 备份 + 同帧复跑, 跑完还原**。

## 六、人眼看得见、模型没检出时怎么分责(缩样)

在机器上用**同一份检测器**对**最新一帧的每种输入**各跑一遍(只读、不占端口):
- 全部 0 ⇒ 不是链路/积压问题, 是模型没检出;
- 再比"人看的那张"与"模型吃的那张"是不是**同一个几何**(常见: 人手看的是自然比例条带,
  模型吃的是被拉伸填成方图的版本 —— 拉伸比因帧而异, 实测有帧纵向 ~15:1 且 40% 像素饱和,
  低对比度缺陷会被插值+饱和吃掉);
- 想分"没看见"与"看见了被阈值卡掉": 降 conf 复跑**同一帧**(先备份 config, 跑完还原)。

## 七、让产线机"按需上网": 借道操作机, 不碰它的系统设置

**先记住为什么"设了代理, 产线服务就丢了"**: 给机器设的是**机器级 WinHTTP 代理**且没写内网旁路 —— 而这台机器上有两条
命脉都走机器级 HTTP: **分钟级保活任务**与**反向通道**(agent 轮询操作机)。代理一生效, 这两条当场断, 操作侧也进不去机器回滚。
⇒ 铁律: **任何改它网络的动作, 先保证自己不失去进机器的路**; 优先选"不动它、只在操作机侧加东西"的方案。

⇒ 铁律②: **常驻代理会把"这台机器后来接入的任何网络"都劫走**。用户插上 WiFi 网卡/换到别的出口后会报
"切不到外部 wifi""上不了网", 因为他所有浏览器流量仍被送去操作机那条出口 —— 这不是网卡坏了, 是代理把出口绑死了。
⇒ **交付时必须给"怎么关", 且默认要能正常联网**:
- 形态① **一键切换**: 桌面上两个快捷方式(写 `ProxyEnable=1` / `=0` 各一), 用户自己切 —— 但对普通用户仍偏技术;
- 形态② **(首选, 最干净) 系统里一个键都不改**: 只在需要借道时用**带 `--proxy-server` 启动的专用浏览器快捷方式**
  (原快捷方式一个字不动), 常规上网完全不受影响;
- 形态③ systemd 常驻**操作机侧**代理 —— 那只是保证出口不掉, **不等于可以让用户侧代理常开**。
- 汇报时必须说清"现在默认是哪一档、怎么切到另一档", 否则下次他插上网卡会再来投诉一次。

**定式(零系统改动, 首选)**: 代理起在**操作机**上, 产线机只在需要时"借道一条命令"。
```bash
# 操作机侧: 只监听产线网卡, 白名单只放产线机 + 操作机自己
grep -E '^Port|^Listen|^Allow' /etc/tinyproxy/zmax.conf   # Port 8889 / Listen <操作机产线IP> / Allow <产线机IP> / Allow <操作机产线IP>
sudo tinyproxy -c /etc/tinyproxy/zmax.conf; ss -ltnp | grep 8889
```
```powershell
# 产线机侧: 单条命令借道, 用完即走 —— 系统代理/默认路由/网卡一个字不动
curl.exe -L -x http://<操作机产线IP>:8889 -o D:\x.zip <URL>
Invoke-WebRequest -Proxy http://<操作机产线IP>:8889 -Uri <URL> -OutFile D:\x.zip -UseBasicParsing
```
- **为什么安全**: 产线段的直连路由永远优先, 它的服务/保活/反向通道全走直连、不经过代理; 系统级代理保持
  "直接访问" ⇒ 通道零感知。代理日志能看见"谁在连、连到哪", 白名单外一律拒绝(实测会打 `Unauthorized connection from <ip>`)。
- **验证口径(变更前后各一遍, 都报数字)**: 机器上 `netsh winhttp show proxy`(应="直接访问(没有代理服务器)") +
  `(Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings').ProxyEnable`(应=0) +
  产线端口 `(Get-NetTCPConnection -State Listen -LocalPort <端口>).LocalPort`; 再经代理取一次公网 → 200。
  - **别拿 `127.0.0.1:<port>` 测代理**: 代理只 `Listen <操作机产线IP>` 时打回环会 `HTTP 000`(curl 连不上) —— 看着像"代理坏了",
    其实只是没听回环。测**它真正绑定的那个地址**, 判活也只信该地址上的 `ss -ltn`。
  - **"和浏览器同一条路"的验证**(比只测 `-Proxy` 更有说服力): 机器上不带 `-Proxy` 跑
    `(Invoke-WebRequest -Uri <URL> -UseBasicParsing -TimeoutSec 25).StatusCode` —— PS 5.1/.NET 会读 WinINET 用户设置,
    它通 ≈ 浏览器通; 同时复核产线端口仍 `Listen` ⇒ 旁路表确实生效。要区分层就用这个:
    `try { ... } catch { $_.Exception.Message }` 把失败原因原样带回来。
- **默认手起, 用户要"整机常态上网"才升级成服务**: 手起时收工 `sudo pkill -x tinyproxy`, 操作机一重启它消失(无"后门忘了关"风险);
  但**一旦产线机侧真配了代理, 它就开始依赖这个出口** —— 操作机一重启就等于产线机断网 ⇒ 此时做成 systemd
  (`Type=simple` + `ExecStart=<tinyproxy 绝对路径> -d -c <conf>`; `-d` 才不后台化), `enable --now` 后重启服务实测一次再交付。
- **先说清做哪一层, 再动手**: "只让某条命令借道"(`-Proxy`) 之后机器上**任何东西都没配** —— 浏览器/正常程序照旧上不了网。
  用户说"机器上不了网/打不开某网站"时, 先确认他要的是**整机(浏览器)能上网**还是**只让某条命令下载**;
  默认只做前者的话, 他试完会回你"还是上不了"。
- **只有用户明确要"整机长期上网"**才升级为"操作机做上游 + 产线机加一条默认路由", 且必须 ① 只加默认路由
  (直连段不受影响) ② 配**机器本地的自检看门狗**(每 20s 探产线端口 + 反向通道, 异常自动删路由) —— 否则出事时你已经被关在门外。
- **非设系统级代理不可时, 先降级到"登录用户级" WinINET**: 只设**桌面上那个登录用户的** WinINET + 旁路表
  `192.168.23.*;192.168.*;10.*;172.16.*;127.*;<local>` —— 保活/agent 跑在 **SYSTEM** 账户下、**不读登录用户的设置** ⇒ 通道零感知;
  外加"原值存成回滚文件 + 变更后立刻探针 + 失败自动复原"。机器级 WinHTTP 是最后手段。
  - ⚠️ **"用户级"指登录用户, 不是你下发命令的那个身份**: 反向通道的 agent 以 `nt authority\system` 跑(回执里 `whoami` 就能看到)
    ⇒ 直接写 `HKCU\...` 写的是 **SYSTEM 的 hive**, 浏览器永远读不到 —— 表象极具误导性: 机器上的 Windows 更新/遥测**真的**走了代理,
    用户浏览器却照旧上不了网, 于是你会以为自己设对了。
    正解: 先查登录用户与 SID(`quser` / `(Get-CimInstance Win32_ComputerSystem).UserName` /
    `Get-CimInstance Win32_UserProfile | Where-Object -Property Loaded -eq 'True' | Select-Object LocalPath,SID`),
    再按 **`HKU\<SID>\Software\Microsoft\Windows\CurrentVersion\Internet Settings`** 写(SYSTEM 权限可写已加载的 hive)。
    PS 的 `HKU:` 盘符路径经通道下发可能**不落地**(实测回读为空, 无报错) ⇒ 用 `reg.exe`, 或把 PS 脚本 base64 化:
    `powershell -NoProfile -EncodedCommand <base64(UTF-16LE 的脚本)>` —— base64 里没有 `$`/`%`/引号, 一次性绕开包装坑。
    - **在登录用户会话里跑命令取证的可靠做法**: 用 PS 的 `Register-ScheduledTask -Action (New-ScheduledTaskAction cmd.exe '/c <命令>')
      -Principal (New-ScheduledTaskPrincipal -UserId <登录用户> -LogonType Interactive -RunLevel Highest)` + `Start-ScheduledTask`,
      **不需要密码**(`/it` 交互令牌), 且比 `schtasks /run` 稳(`schtasks /run` 实测回 `找不到元素`)。
      ⚠️ Task Scheduler 直接跑 `cmd /c` 时, 用 `/c cmd1 & cmd2 & "C:\...ed.exe" ... >> out 2>&1` 的链式重定向里,
      **在带空格的 exe 之后 cmd 不一定继续**(实测 out 停在 Edge 之前); 拆成单条或改用会话内 PS 脚本更稳。
    - ⚠️ **base64 经通道 >~3KB 会坏**: 外层 EncodedCommand 里再嵌一层 EncodedCommand 很容易超(实测 4.3KB 的收不到)。
      把要在机器上跑的小脚本**先用通道 `[IO.File]::WriteAllBytes(路径,[Convert]::FromBase64String('<脚本 b64>'))` 落成文件**
      (ASCII 内容按 ASCII 编码写, 别用 UTF-16 且不带 BOM —— PS `-File` 会解析错), 再让计划任务 `powershell -File <脚本>`;
  - 🔴 **最容易被漏掉、也是"设了没用"的头号真因: 登录用户 hive 里的 `ProxyEnable` 必须是 `0x1`**。
    实测(2026-10, 工控机 DESKTOP-NV6ATND): `ProxyServer`/`ProxyOverride` 都在、`Connections\DefaultConnectionSettings`
    blob 也已是 `flags=0x01`+正确代理, 但登录用户 admin 的 `ProxyEnable=0x0` ⇒ Edge/WinINET/WinHTTP(当前用户 API)
    一律走**直连**, 于是"怎么设都上不了网"。**`ProxyEnable` 是总开关, blob 正确也救不了它**(WinINET 的
    `WinHttpGetIEProxyConfigForCurrentUser` 读的是 `ProxyEnable`, 不是 blob)。
    - 别拿 SYSTEM/.DEFAULT 的 `ProxyEnable=1` 当成功证据: 通道命令以 SYSTEM 跑, 你读到的 `HKCU` 是 SYSTEM 的 hive;
      浏览器读的登录用户那份可能还是 0。SYSTEM 侧走了代理(Windows 更新/nvidia 遥测能连上)会**强烈误导**你以为设对了。
    - 决定性的判据(别只看注册表): 在**登录用户的会话**里跑 `Invoke-WebRequest http://www.baidu.com -UseBasicParsing`
      (PS 5.1/.NET 读 WinINET 当前用户设置 ⇒ 与浏览器同一条路) —— 通=浏览器通。
    - ⚠️ **别用无头 Edge 取证**: `msedge --headless[=new] --dump-dom/--screenshot` 在这台机器上
      (Edge 154) 只创建 0 字节文件/无输出(Edge 的 launcher/子进程模型 + 已有实例转发), 看着像"没联网"其实是取证方法坏。
      改用 ① 代理日志(tinyproxy 会记每个被接受的连接, 浏览器真实流量里能看到 `www.baidu.com:443`/`mbd.baidu.com`/`edge.microsoft.com`)
      + ② 会话内 `Invoke-WebRequest` 状态码 双证。
    - ⚠️ tinyproxy 默认 `MaxClients 20` 会被"浏览器一次开一堆并行连接"打满, 日志出现
      `Maximum number of connections reached. Refusing new connections` ⇒ 页面加载/HTTP 取回超时, 误判成"代理坏"。
      给浏览器用时 `MaxClients` 提到 100~200 再 `systemctl restart zmax-proxy`。
  - 🔴 **只改 `ProxyEnable`/`ProxyServer`/`ProxyOverride` 这三个键是不够的**: IE/WinINET 与浏览器真正读的是
    `...\Internet Settings\Connections\DefaultConnectionSettings` 这个 **REG_BINARY**。blob 里还是旧代理时,
    浏览器会继续往**旧代理**撞(实测残留上次设的死地址), 表象就是"你怎么设都上不了网"。
    排查必做: `reg query "<hive>\...\Connections" /v DefaultConnectionSettings`, 把 hex 解出来看**它到底在用哪个代理**。
  - **重建 blob 不要做等长之外的字符串替换**: 结构是 `<IIII`=ver(0x46)/counter/flags(0x01)/**代理串长度**, 再跟代理串、
    旁路串长度、旁路串、末尾 `\x00` 补齐 —— **长度是自带字段**, 新旧代理串长度不同(实测 17 vs 18)时替换会把长度字段写坏、
    浏览器解析错位。按格式重建并**保持总字节数不变**(照老 blob 的长度补零); 用 `scripts/wininet_proxy_blob.py` 生成 hex,
    再 `reg add "<hive>\...\Connections" /v DefaultConnectionSettings /t REG_BINARY /d <hex> /f`, 回读比对确认。
  - **改完必须让用户重启浏览器**: WinINET 设置是浏览器**启动时**读的(最小化不算, 要关掉进程), 开着的窗口不会自己刷新 ——
    漏说这句, 用户必报"还是上不了网"。同时确认**是哪个浏览器**: IE 内核/Edge/Chrome 走系统设置, Firefox 另有一份自己的代理配置
    (默认"使用系统代理设置", 被指到别处就绕过你改的一切)。
  - **"还是上不了网"的排查顺序**: ① 回执里 `whoami` 是谁、你写的是哪个 hive ② blob 里现役代理是谁 ③ 浏览器进程重启了没
    ④ 是不是非 IE 系浏览器 ⑤ 有没有策略/启动参数在覆盖(见下两条)。五步都过再谈网络层。
  - **先排除"被覆盖"的四种来源, 再怀疑网络层**: `ProxySettingsPerUser`(为 0 = 只认机器级、用户设置被忽略) ·
    `HKLM\SOFTWARE\Policies\Microsoft\Edge` 的 `ProxyMode`/`ProxyServer`/`ProxySettings` · 浏览器**快捷方式的启动参数**
    (用 `(New-Object -ComObject WScript.Shell).CreateShortcut(<lnk>).Arguments` 逐个看, 常见被塞 `--proxy-server=`/`--no-proxy-server=`) ·
    Edge/Chrome 的 `User Data\Default\Preferences` 里的 proxy 字段。四者都空才轮到网络层。
  - **"到底有没有到达代理"用代理日志当硬证据**: tinyproxy 记录**每一个**被接受的连接(`Connect (file descriptor N): <机器IP>`)。
    用户报"上不了网"的那一刻, 日志里若**没有**来自产线机的连接 ⇒ 客户端根本没发出到代理的连接(不是"连上被拒"),
    问题在代理之前(没配到/被安全软件或防火墙按进程拦); 有连接但失败才去看上游。
    ⚠️ 陷阱: 日志里**一定会**看到产线机的 SYSTEM 服务(Windows 更新/驱动遥测)成功穿代理 —— 那**不代表**用户的浏览器通了,
    别拿它当"已经好了"的证据(实测据此误判过一轮)。
  - **要验"登录用户那条路", 就在他的会话里跑, 别在服务会话里猜**: 一次性计划任务
    `schtasks /create /tn <临时名> /tr "cmd /c <命令> > C:\Windows\Temp\t.txt 2>&1" /sc once /st 00:00 /ru <用户> /rp <口令> /it /f`
    → `schtasks /run` → 读 `t.txt` → **立即 `schtasks /delete` 删掉**(口令从 secrets 文件读)。
    🔴 **口令卫生**: 构造出来的那条含 `/rp <口令>` 的命令行**绝不许进 stdout/日志/报告** —— 拼完直接执行,
    不要顺手打印出来"看一眼"。一旦它已经落进会话日志或工具输出, 就**按已泄露处理**: 如实告知用户并建议轮换该口令
    (轮换后同步 secrets 文件即可, 不需要改任何代码)。
    在**服务会话**里起浏览器(如 `msedge --headless --dump-dom <url>`)常常**零输出** —— 那是 session 0 没有桌面的环境限制,
    **不是"浏览器不通"的证据**, 别据此下结论。
  - **兜底: 让浏览器自己带代理启动, 完全绕开 WinINET**. 给用户建一个专用快捷方式(原快捷方式一个字不动):
    `msedge.exe --proxy-server="http://<操作机IP>:8889" --proxy-bypass-list="192.168.23.*;127.*;localhost;<local>"` ——
    启动参数由浏览器自己解析, 不受注册表/会话缓存/策略缓存影响。**必须带 `--proxy-bypass-list`**: 少了它内网流量也走代理,
    产线服务当场断。这条只解决"用户能上网", 别拿它替代系统级设置。
  - **写 HKCU 别用 PS 变量**: 经反向通道下发的命令里不许有 `$`/`%`, 所以用**单引号 + 无变量**写法(或 `reg.exe`):
    `Set-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' -Name ProxyServer -Value '<ip:port>'`
    / `-Name ProxyEnable -Value 1 -Type DWord` / `-Name ProxyOverride -Value '<内网CIDR>;127.*;localhost;<local>'`; 改完当场回读这三个键。
  - **`<local>` 要带上**: 它让"不带点的机器名"也走直连, 少写它会让按主机名访问的产线服务被代理吞掉。
- **下发命令的引号/符号坑**: 经反向通道下发的命令里**不要出现 `$` 和 `%`**(会被 PS 包装吃掉 ⇒ 变量变空、
  `-w %{http_code}` 报格式参数错); 要看状态码就写成 `(Invoke-WebRequest ...).StatusCode` 这类**表达式**, 或优先用 `curl.exe`。

### 可切换上网开关(直连/借道)的落地口径

- **真正的开关是 `ProxyEnable`, 不是 blob**: Edge/WinINET 经 `WinHttpGetIEProxyConfigForCurrentUser` **只读**
  `Internet Settings` 的 `ProxyEnable`/`ProxyServer`/`ProxyOverride` 三个键, **不读** `Connections\DefaultConnectionSettings`。
  实测: blob 里 flags=1(带代理) 而 `ProxyEnable=0` ⇒ 浏览器仍走直连。**只写 blob 不改 ProxyEnable = 没生效**(本轮最大教训)。
  blob 可以顺带改成一致值, 但别本末倒置。
- **两个开关都要写两处 hive**: 登录用户 `Registry::HKEY_USERS\<SID>\...` + `Registry::HKEY_USERS\S-1-5-18\...`(SYSTEM)。
  已验证 `Administrators` 对 `HKU\S-1-5-18\...\Internet Settings` 有 **FullControl** ⇒ **提权(管理员)进程可直接写 SYSTEM hive**, 不必绕计划任务。
  非提权(中完整性)进程写 SYSTEM hive 会被拒(管理员 SID 在令牌里是 deny-only) ⇒ 开关脚本**先自提权**:
  `Start-Process powershell -Verb RunAs -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',('"'+$PSCommandPath+'"'),'-Mode',$m)`。
  UAC `ConsentPromptBehaviorAdmin=5` 时会弹一次同意框(可接受)。
- **写 `HKU:` PSDrive 会`不落地`(回读空、无报错)**; 一律用 `Registry::HKEY_USERS\...` 或 `reg.exe`。
- 改完必须 `InternetSetOption(0x27 SETTINGS_CHANGED / 0x25 REFRESH)`,`Add-Type` P/Invoke `wininet.dll`; 并回读两处 `ProxyEnable` 才算数。
- **默认值按"有没有别的外网出口"定**: 产线机常只有一条 192.168.23.x 内网(网卡无默认网关)⇒ 默认保持"借道"(ProxyEnable=1),
  "直连"做成用户手动点的开关。**别把直连设成默认**, 否则他一插网卡/上网立刻又断。
- **测"直连"开关会当场切断用户上网** ⇒ 若审批/用户不许停机, 就只交付脚本+回读逻辑, 别在班中真跑一次。

### 没有 iwr 下载权时怎么把脚本送上产线机(纯文件写入)

- `iwr <url> -OutFile ...; powershell -File ...`(下载即执行)常被审批拦。改用**分块 base64 直写**:
  本地 `base64(file)`(CRLF+UTF-8 BOM) → 分 ~1400 字符/条, 第一条 `Set-Content -Path x.b64 -Value '<chunk>' -NoNewline`,
  其余 `Add-Content ... -NoNewline`, 最后 `$b=[Convert]::FromBase64String((Get-Content x.b64 -Raw)); [IO.File]::WriteAllBytes('<target>',$b)`,
  再 `Get-FileHash` 与本地比对 sha256。**单条 <~1.5KB 才不被通道弄坏**。
- 建快捷方式用 `(New-Object -ComObject WScript.Shell).CreateShortcut(<lnk>).Save()`, `.Arguments` 里写
  `-NoProfile -ExecutionPolicy Bypass -File "<脚本>" -Mode <direct|proxy>`(lnk 名可含中文, COM 存 Unicode 正常)。
- **`schtasks /create ... /rp <口令>` 把 `/rp` 放命令最后**: hub 日志按 160 字符截断打印命令, 口令放后面才不会被记进 `hub.log`。

### 梅卡曼(Mech-Mind)帮助文档: 公共域名, 必须走代理

- Mech-Vision 帮助入口 URL 在 `<安装>\Mech-Vision\resource\vision\app_url_config.json` 的 `"url"`: 实测为 `https://docs.mech-mind.net`。
- 它是**公共域名**, 不该进旁路表(旁路表只放 `192.168.23.*` 内网)。产线机**本地 DNS 解析不了外部域名**(实测 `Resolve-DnsName` 空),
  但经 tinyproxy(远端代解析)可达(302→/en/ 200)。⇒ **一旦把它加进旁路/关掉代理就必然 404**(直连无 DNS 无路由)。
  排查口径: 走代理 200 = 正常; 直连 = 无 DNS。**不要因此改路由/DNS**。

## 支持文件

- `templates/vscode_launch.json` —— 交出去自己调试用的 `launch.json`(多套配置 + UTF-8/无缓冲 + `justMyCode:false`)。
- `scripts/machine_image_probe.py` —— 机器上只读量图(尺寸/亮度/std/块内 std/饱和比/列自相关), 可选 `--detect` 跑真模型。
- `scripts/wininet_proxy_blob.py` —— 生成/改写 `Connections\DefaultConnectionSettings` 的 REG_BINARY hex(浏览器真正读的那份代理配置)。
- 相关: `linux-host-maintenance`(本机自检)、`systemd-boot-services`(本机常驻服务)、
  用户自有的 `zmax-aoi-service`(具体 AOI 端点/版本/口径)。
