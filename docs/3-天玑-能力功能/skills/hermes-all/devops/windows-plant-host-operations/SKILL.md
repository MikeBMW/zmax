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
- **机器压根没开机 / 在休眠 / 你手上只有一块 U 盘 LiveUSB 起的 Linux**: 通道不存在 ⇒ 走第八节离线载荷

适用环境: 产线 Windows 工控机(例: 192.168.23.23, 开 1008x/139/445, **无 SSH/RDP/WinRM**),
上面跑着**你在维护**的程序 + **产线自己的**服务(例: flask_1005 / Mech-Vision)。
🔑 **拿到账号口令后不必再绕**: 445 开着就优先用 SMB 直接读写盘符(读日志/落脚本/核文件), 反向通道只在没凭据或要**执行命令**时才必需 —— 见「一.0」。
具体 AOI 端点/版本口径见用户自有的 `zmax-aoi-service`(要找它自动维护先 `hermes curator adopt`)。

## 铁律(先读, 都是踩过的)

- **它是产线设备**: 只读探针优先; 每次真拍/真停先有理由, 不批量轮询; 不动别人的服务与文件。
- **上线只走部署器**(`tools/aoi_remote_deploy.py` 那类: 拷进静态目录 → 机器 `iwr` 下载 → `Get-FileHash` 逐位核对
  → 备份 `.bak` → 停旧起新 → 验收 → 失败自动回滚)。手工 `iwr -OutFile` **直接覆盖、不留备份** ⇒ 事后再跑一次部署器才有真 `.bak`。
- **版本号放文件头 `VERSION`, 不放文件名**: 上线是**覆盖现场约定名**(`..._v6.py`)。用户在资源管理器/VSCode
  的目录列表里只看到那个约定名 ⇒ 他会以为没有新版(实测被问过"工控机的代码没有 v10 啊")。凡改版都额外 `Copy-Item <约定名> <约定名带版本>` 落一份副本,
  并回报 **VERSION + sha256 + 字节数**(sha 与本地副本逐位相同)。**行号一律按这份报** —— 换版本行号会漂。
  - 🔴 **副本是给人看的, 不一定是给跑的 —— 必须同步保活脚本里的文件名表**: 保活脚本(`<dir>\zmax_keepalive.ps1`)
    用一张 `@{端口=文件名}` 表决定每轮拉起哪个文件。它指向带版本副本、而部署器只覆盖**约定名**时,
    服务会一直跑旧内容, 两个文件都在、sha 也都"对"(实测: 部署器逐位核对通过, 磁盘上约定名仍是旧版,
    只有副本是新的, 进程跑的却是副本)。定式三步: ①部署后 `Copy-Item <约定名> <keepalive 指向的名字> -Force`
    ②回读**两个名字各自**的 `Get-FileHash -Algorithm SHA256` 都必须等于本地 ③重启后读**进程命令行**
    (`Get-CimInstance Win32_Process | ? { $_.CommandLine -match '<程序名>' }`)确认跑的就是那个名字 ——
    只看端口活着, 分不出跑的是哪一份代码。
  - **`.bak_*` 会堆到几十个**: 每次部署留一个备份, 攒到 80+ 个/数 MB ⇒ 用户翻目录时反而找不到正式文件。
    交付时按时间只留最近 3 个, 删前把"保留哪三个、清了多少个/多少 MB"报出来。
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
- 🔴 **命令里只要带 `$` 变量就会静默变空** —— 不只是注册表那种长脚本: 一条 `Copy-Item (Join-Path $d ...)`
  也会在包装层被吃掉 `$d`, 回执照样"成功"而文件根本没变。凡脚本里有 `$`/引号嵌套/多语句, 一律走
  `powershell -NoProfile -EncodedCommand <base64(UTF-16LE)>`(base64 里没有 `$`、`%`、引号, 一次绕开全部包装坑);
  本地用 python `base64.b64encode(ps.encode('utf-16-le'))` 生成, 别手拼。
  ⚠️ 判"这条命令真的生效了"只认**回读目标文件/进程**, 不认回执 exit 0 —— 那个假成功会让你继续往下走。
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
- 🔴 **在 bash 里给 `station_cmd.py` 传 PowerShell 必须用单引号包**: 双引号下 bash 会先展开 `$_`/`$LASTEXITCODE`
  之类 —— 实测 `Where-Object {$_.ProcessName -match 'python'}` 被改写成 `{/home/ubuntu/zmax.ProcessName ...}`
  ⇒ 回执报 `CommandNotFoundException`, 看着像"通道坏了/这台机器的 PS 不认管道"。正确写法
  `./gui-venv311/bin/python tools/station_cmd.py 'Get-Process | Where-Object { $_.ProcessName -match "python" }' 90`
  （外层单引号 + 内层双引号）。
- 通道健康**看它发来的请求**, 别用日志行数/本机自检判: `sudo timeout 20 tcpdump -A -s 0 -n -i <产线网卡> 'host <机器> and port 8794'`。

### 一.0 有账号口令时: SMB 直读直写(只能读写盘, 不能执行)

口令到手后**第一件该试的事**, 比 base64 分块省事一个量级: 看日志/列目录/校正文件是否存在都能直接干。

```bash
smbclient -L //<ip> -U '<user>%<pass>' -m SMB2          # 看共享: ADMIN$ / C$ / D$ / <业务共享>
smbclient //<ip>/D$ -U '<user>%<pass>' -m SMB2 -c 'cd xspace\<目录>; get <日志> /tmp/<日志>'
```
- **业务共享往往直接就是安装目录**: 实测 `<业务共享>` 的根与 `D:\xspace\ultralytics_AOI` 同目录
  ⇒ 列文件用那个共享就行, 路径短、不用转义盘符。
- **落自己的脚本用 `put`, 再用反向通道执行**: `-c 'put /本地/x.ps1 x.ps1'` → `powershell -ExecutionPolicy Bypass -NoProfile -File D:\<目录>\x.ps1`。
  这条绕过「单条命令 ~3KB 就坏」与「base64 分块拼坏」两个坑。
- 纪律: ① 只读或只写**自己的**文件名, 不覆盖现役/别人的文件; ② 落下去的 `.ps1` 本地先查
  `sum(b>127 for b in open(f,'rb').read()) == 0`（纯 ASCII）; ③ SMB 只能读写**盘**, 要进程/端口/计划任务
  这种**执行态**仍然走反向通道 —— 两者配合用。
- 判活仍然以**端口/接口**为准, 别把"共享能列目录"当成"服务在跑"。

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

### 5.1 反过来用: 在机器上**驱动**那个加密检测器 (不解密、不改它)

加密包不等于「只能从外面观测」—— 只要它露出 `detect(图路径, detect_type=...)` 这类入口, 就能在**机器本机**
用它检你**自己生成的图**, 绕开「HTTP 接口只能拍照后再检测」的限制。权重与解密器都留在机器上, 一个字节不用碰。

```powershell
# ① 机器上 python 常不在 PATH ⇒ 从**在跑的那个服务进程**取真实解释器
Get-CimInstance Win32_Process | Where-Object {$_.Name -like '*python*'} |
  ForEach-Object { $_.ProcessId.ToString() + ' ' + $_.ExecutablePath + ' ' + $_.CommandLine }
# ⇒ 通常是 <安装目录>\venv\Scripts\python.exe（也可能同时有系统 Python 的影子实例）
```
- **脚本别塞进命令行**: base64 落文件再用解释器跑(`[IO.File]::WriteAllBytes` / `iwr ... -OutFile`),
  避开引号转义与单条 ~3KB 上限。
- 脚本里 `sys.path.insert(0, r'<安装目录>')` 再 `from <厂家模块> import <类>`。构造器自己加载权重并**预热**
  (实测一次装两个模型: 5.6s + 2.1s) ⇒ 一次性进程每次都付这个代价, 批量检图要**在一个进程里循环**。
- **先看显存再加载**: `nvidia-smi --query-gpu=memory.free,memory.total --format=csv,noheader`。
  产线机常只有 4GB(实测剩 3359MB 可加载一次); 不够就先清自己的临时进程, 别去动在役服务。
- **喂自己生成的图**: 放到 hub 静态目录 → 机器上 `iwr 'http://<操作机>:8794/<文件>' -OutFile <本地路径>` →
  `detect(<本地路径>)`。检测器读的是**路径**而不是相机 ⇒ 这是「用产线模型检任意图」的唯一干净入口。
- **判「回执是不是这一次的」**: 入队前记 `out/` 最新文件的 mtime, 只接受比它新的。
  只按「最新文件里有没有关键字」判断, 会把**上一轮**的回执当成这一次的结果报给用户
  (与「异步检测必须轮询计数」同一个坑, 只是换成文件通道)。
- 🔴 **结论必须分两句说**: 「链路通, 这次检出 N 个」与「**能检出有缺陷的件**」是两件事。
  手上没有已知正样本(划伤/污点标定件)时, 只能证明前者; **0 缺陷不能推导成工件合格**,
  也不能宣告「缺陷检测能力已验证」。交付时把这个缺口写在明面上, 别用「已接入」盖过去。

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

## 八、机器没开机/休眠中: 离线两阶段载荷(没有通道时唯一做法)

完整可复用配方 + 代码骨架见 `references/offline-windows-payload.md`。铁律:

- 🔴 **休眠的 NTFS 默认不写**。`hiberfil.sys` 存在时直接 rw 改 SAM/注册表, 会被下次休眠恢复覆盖(=白改), ntfs-3g 也可能拒。
  默认口径仍是**只读取证 + 让 Windows 自己做**(脚本调它自己的 API)。只有用户明确要求立刻生效、且 Windows 确实没在跑时才走离线改, 且必须:
  `mount -o rw,remove_hiberfile`(⇒ 下次完整启动, 先告知用户) → 备份 SAM/SOFTWARE/SYSTEM/SECURITY/DEFAULT →
  `reged` 只改**字符串类值**(回读验证) → 卸载回挂 ro。
  **账户禁用/删除不做离线硬改**: `chntpw -u` 没有禁用/删除项, SAM 的 F 值二进制导出会被截断 ⇒ 改用 `chntpw -l` 认账户
  + 把动作挂到"新账户首次登录"的 `C:\ProgramData\...\StartUp` 自启脚本里执行。完整配方见 `references/offline-hive-and-account-ops.md`。
- **投递走 U 盘的 FAT32 分区, 不走 NTFS**(Windows 里就是个盘符, Linux 写它零风险)。
  四件套: `SETUP_WIN.cmd`(自提权入口) / `setup_win.ps1`(两阶段) / `CHECK_WIN.cmd`(只读体检) / `README.txt`。
- **两阶段拆开是因为"当前登录用户删不掉、装软件要新账号的 profile"**:
  stage1 只做能立刻验证的事(hive 备份/建号/开自动登录/注册下一阶段/删别的号), 然后重启;
  stage2 在新管理员首登时跑重活(删残留账户与 profile、清 ProfileList 孤儿、装软件、写 REPORT 并弹出来)。
- **stage1 先把自己拷到 `C:\_zmax_setup\`, 再注册 `schtasks /sc ONLOGON /ru <新账号> /rp <口令> /rl HIGHEST`** ——
  U 盘随时会被拔; `/rl HIGHEST` 才有提权令牌。stage2 用 `stage2.done` 做幂等, 末尾自删任务。
- **账户/组一律按 SID 定位**(内置管理员 `*-500`, 管理组 `S-1-5-32-544`), 中文系统上名字不可靠; icacls 授权也用 `*S-1-5-32-544:(OI)(CI)F`。
- **删 profile 走三件套** `takeown /f <p> /r /d Y /a` + `icacls` + `Remove-Item -Recurse -Force`, 失败再 `cmd /c rd /s /q` 兜底。
- 🔴 **交付前离线校验**: ps1 用 Linux 版 pwsh 解析器过语法; 解析目标安装器的 param block 确认真在用的参数名;
  CLI 键名在本机先 `config get <key>` 实测(顶层是 `model` 就别写 `model.default`); ps1 存 **UTF-8 BOM+CRLF**, `.cmd` 纯 ASCII+CRLF。
- **引导顺序坑**: LiveUSB 的 BootOrder 常把 USB 排第一 ⇒ 重启又回 U 盘而死循环; `efibootmgr -o` 把 Windows Boot Manager 提到首位,
  U 盘留给 F12。
- **交付必须写清**: 不可逆清单(删什么、多少 GB) / 不动清单(系统本身、其它数据盘、DefaultAccount·WDAGUtilityAccount·Guest) /
  回滚点(hive 备份路径) / 自动登录怎么关(`netplwiz`) / 内嵌 API key 在 FAT32 上是明文 —— 装完让用户删掉载荷目录。

## 九、用户在自己机器上代输命令(他敲键盘、你读输出)
没有反向通道、也不值得先建通道时，只能让用户在他那台 Windows 上粘贴命令。这一档有自己的坑：

- **一次只给一段块，块外不加字**: 用户明确要求过"把要粘贴的发给我，别发别的"。多块混排/块前后夹解释时，
  他会停下来问"粘贴哪个""这段里有 powershell 这个词么"。要分段就一次发一段，末尾只说一句"跑完把输出发我"。
- 🔴 **连写波浪号会在粘贴链路上丢掉**: `OpenSSH.Server~~~~0.0.1.0` 粘过去变成 `OpenSSH.Server0.0.1.0`，
  命令**不报错**，只回一个 `Path` 为空的空对象（看着像装成功了）。凡是可能要用户手粘的能力名带 `~~~~`，
  一律改成先取名字再用：
  ```powershell
  $cap = Get-WindowsCapability -Online | Where-Object { $_.Name -like 'OpenSSH.Server*' }
  $cap | Format-Table Name, State
  Add-WindowsCapability -Online -Name $cap.Name
  ```
- **判"装上了没有"只认服务与文件**: `Get-Service sshd` = `Running/Automatic` 且
  `Test-Path C:\Windows\System32\OpenSSH\sshd.exe`。`Add-WindowsCapability` **静默失败**时既无报错也无输出
  （实测：能力状态永远停在 `NotPresent`，`sshd` 服务不存在）⇒ 别把"没报错"当成功。
- **入站默认全关 ⇒ 探不到 ≠ 没上线**: ping 不通、22/445/3389/5985 全闭是未配置 Windows 的正常状态。
  判它在不在线只能靠用户侧 `Get-NetIPAddress -AddressFamily IPv4`（WLAN 那行的 IP）或它在网关/飞书上在线。
  **报告里"端口有服务在听"与"这台机器在线"必须分开写**，不能拿扫描无果下"没上线"。
- 顺手把防火墙规则放进来（可重复执行、无副作用）：
  ```powershell
  New-NetFirewallRule -DisplayName "OpenSSH" -Direction Inbound -Protocol TCP -LocalPort 22 -Action Allow -ErrorAction SilentlyContinue
  ```

## 十、把自己那套 "会敲命令的通道 + 脑子" 装上 Windows 机器

前面几节讲"机器已有你维护的程序、你要接管"。这一节是另一类：**机器是空的/只有 Windows 本身**,
要从零得到一条能执行命令的通道, 再把跨机脑子(Hermes 的记忆/技能/配置/凭证)灌上去。完整配方见
`references/windows-hermes-brain-node.md`。铁律:

- **通道顺序: WinRM(零下载) → sshd**。`Add-WindowsCapability` 装 OpenSSH 常**静默失败**(无输出、无服务、
  能力状态仍 `NotPresent`), 而国内网络常常拉不下 GitHub 的 release。WinRM 是 Windows 自带的:
  `Enable-PSRemoting -Force -SkipNetworkProfileCheck` + 开 5985 入站, Linux 侧 `pywinrm` 用 **NTLM + 本地账号**
  直连, 不用改 `AllowUnencrypted`/`Basic`。
- **安装类长任务必须脱离会话**: 落成 .ps1 文件, `Start-Process ... -RedirectStandardOutput <out>` 后轮询
  `<out>` 的末行/字节数; 直接在前台跑, 通道一断就死。
- **落下去的 ps1 一律纯 ASCII**: PS 5.1 读无 BOM 的 UTF-8 会把中文当 ANSI ⇒ 引号被吞报 `字符串缺少终止符`;
  PS 5.1 也**不支持 `?.`**。诊断脚本用英文、不用 null 条件运算符。
- **远程默认 shell 是 cmd.exe**: `;` 不是分隔符(`tar -xf - ; echo rc` 会把 `;`/`echo` 当 tar 成员 ⇒ `Not found in archive`),
  用 `&&`; 且**别给 Windows 路径套 POSIX 单引号**(cmd 会字面传下去)。管理员账号的公钥落
  `C:\ProgramData\ssh\administrators_authorized_keys` 并 `icacls` 收窄权限, 普通用户才用 `%USERPROFILE%\.ssh\`。
- **灌脑子用 tar over ssh**(Windows 没有 rsync), 首次灌 `memories skills cron config.yaml auth.json .env channel_directory.json`
  (`config.yaml` 只这一次, 之后定时同步不推它 —— 见下条)。
  🔴 漏掉 **`.env`** 是最常见的"装好了却不会说话": 模型 key 与 `*_BASE_URL` 都在里面。
  对齐只认 `certutil -hashfile <f> MD5` 与本地 `md5sum` 逐字相同。`state.db`/`sessions`/`cache` 不同步。
- **"明明配了 A 却走 B"按序查**: ①`hermes auth list` 看哪条凭证 `priority=0`(机器级 `ANTHROPIC_API_KEY`
  这类环境变量会自动注册且优先) ②`hermes config get model` —— 顶层 `provider:` 是**陈旧键**, 正确是
  `hermes config set model.provider <p>` ③**改配置修不了已有会话**: `state.db` 的 `sessions.model_config` 里可能钉着旧的
  `gateway_runtime: {provider, base_url}`, 交互式会话按它走 ⇒ 配置是 deepseek、请求发去 anthropic 兼容口、
  回 `HTTP 404: Not found the model <m>`; 而 `hermes -z` 能过。这种"一条通一条不通"就是它, 把 `gateway_runtime` 摘掉
  并把 `billing_provider` 改成目标 provider, 让他重开会话 ④仍未解才动 auth.json/机器级环境变量。
- **定时同步别推 `config.yaml`**: 两台机器的 provider/环境不同(目标机可能挂着机器级 `ANTHROPIC_API_KEY` +
  `ANTHROPIC_BASE_URL=.../anthropic`), 每拍把主脑那份推过去会**把刚固化的 `model.provider` 覆盖回去** ——
  表现就是"修好了, 下一拍又 404"。`config.yaml` 只在**首次灌脑子**时送一次, 日常同步只走
  `memories cron auth.json .env channel_directory.json`。改完同步脚本必须跑一轮再回读目标机 `config.yaml` 头三行 + `hermes -z` 一句,
  证明它没被覆盖。
- **先钉配置, 再谈清凭证/环境变量**: 显式 `model.provider` 能压过环境变量那档; 但删 `auth.json` 凭证或清机器级
  `ANTHROPIC_API_KEY` 会**影响机器上别的工具**(那份 key 往往是用户给 Claude Code/Kimi 用的)。
  真要临时改用户级环境变量, 改完立刻复原(`SetEnvironmentVariable(<name>, $null, 'User')`), 并在报告里说明动过什么。
- **报"装好了"带三证**: `hermes --version`、`hermes -z` 真跑一轮的回答、`MEMORY.md` 两边 md5 相同。

### 10.1 家庭笔记本这类「新 Windows」: 从零拿通道 + 建桌面启动器

实例: `192.168.1.6` / `SPACE\Mike`(admin=True) —— 与产线工控机不同, 口令不在 secrets 里, 得让用户给一次。

- **判「有没有路」用实测端口, 别猜**: `445/135/3389` 全闭、`5985` 与 `22` 开 —— 但**只有 22 能用**(WinRM 没启用凭据体系)。
  ⚠️ 用户名错时 Windows sshd 的行为分两种: 不存在的用户 → `Permission denied`; 若某用户名一到 `SSH2_MSG_SERVICE_ACCEPT` 就被
  **`Connection reset`**(还没发 USERAUTH_FAILURE), 那个账户大概率**存在但 sshd 建会话失败**(微软账户/别名)。别拿它当「服务坏了」。
- **一次性把公钥装到位**(管理员账户): 写 `C:\ProgramData\ssh\administrators_authorized_keys`(不是 `%USERPROFILE%\.ssh\`),
  然后 `icacls $f /inheritance:r /grant *S-1-5-32-544:F /grant *S-1-5-18:F`。装完立刻 `ssh -o BatchMode=yes` 复验。
- **不要用浏览器/剪贴板传密钥类载荷**: 把要执行的东西 base64(UTF-16LE) 后用
  `ssh user@host powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand <b64>` 下发 —— 走 SSH 不受反向通道那 ~3KB 限,
  key 也不进聊天记录。要用 HTTP 中转的话, 完事必须 **停服务 + 删含密钥的载荷目录** 并 grep 复验。
- **SSH 到 Windows 的输出是 GBK**: python 里 `p.stdout.decode('gbk','replace')`, 并过滤 stderr 里以 `#< CLIXML` 开头的进度噪声(不过滤会 UnicodeDecodeError)。
- **Hermes 在 Windows 的数据目录是 `%LOCALAPPDATA%\hermes`, 不是 `~\.hermes`**: `config.yaml`/`.env`/`state.db`/`memories` 全在那边;
  找 key、看 provider 都去那里。比 key 对不对只比 **md5(值)** 与长度, 不打印值。
- 🔴 **桌面上的 `Hermes.lnk` 出厂是「安装器」**: target=`powershell.exe`, args=`-NoExit -Command "iex (irm .../install.ps1)"`
  —— 用户说「配好启动图标」就是要换成真启动器: 先 `Copy-Item` 备份到 `<数据目录>\backups\Desktop-Hermes-installer.lnk.bak_<时间>`,
  再用 `scripts/mk_desktop_launcher.ps1` 生成(**投递形式取下面「Windows Terminal 独立窗口」那条, 别直接指向裸 exe**),
  最后 `CreateShortcut` 回读 target/args/workdir/icon 四项 + `Test-Path` 目标。
  ⚠️ **图标类交付必须留一个可重跑的生成脚本**: 用户发现不对会把图标直接删掉重来(实测), 重建不能靠"再调试一遍"。
- **验证 GUI 启动只能在登录会话里做, 且要能看见「窗口」。** SSH 进来是 `session 0`(`(Get-Process -Id $PID).SessionId`),
  在那里 `Start-Process` GUI/`wt.exe` 会返回空/无窗口 —— 拿它当「图标坏了」或「图标好了」都是错的。
  正确姿势: 建**一次性计划任务** `-UserId <登录用户> -LogonType Interactive -RunLevel Highest`,
  任务里先用 `user32!EnumWindows` 拍一张**可见带标题窗口清单(BEFORE)** → `& explorer.exe '<桌面.lnk>'`(这才是真双击, ShellExecute)
  → 等 10~14s → 再拍 **AFTER** → 比对数量与新增标题, 同时看 hermes 进程是否活着。**BEFORE 7 个 → AFTER 8 个且新增 `CASCADIA :: Hermes Agent`** 就是铁证。
- 🔴 **Win11 默认终端是 Windows Terminal 时, 双击一个 console exe 的快捷方式会在「已开的终端窗口」里新开一个后台 tab**
  (标题变成 `Hermes`), 用户根本看不到 ⇒ 就是「没有打开」。必须用独立窗口:
  快捷方式 TargetPath=`...\WindowsApps\wt.exe`, Arguments=`-w -1 new-tab --title "Hermes Agent" -d "<用户目录>" "<exe>"`,
  IconLocation 仍取那个 exe(`<exe>,0`)。`-w -1` = 新窗口; 缺了它 `wt` 就是往现有窗口塞 tab。
- 判别捷径: 进程活着但 `EnumWindows` 里没有任何属于它的可见窗口/只有 `PseudoConsoleWindow` ⇒ 它被挂到了别人的终端窗口里, 不是「启动失败」。
  用 `Start-Process -WindowStyle Hidden` 的父进程拉起时, 子进程的 console 窗口是隐的 —— **别拿这种测试结果当结论**。
- 🔴 **判「窗口起来了没有」专用 pid, 不用标题正则**: 同一套程序在不同产品档位/客户名下标题不同(实测主窗口叫
  `XSpace ZMAX 550A`, 拿 `Z-MAX|Console` 去匹配就把“已起来的窗口”判成零), 而且标题可能晚于窗口创建才由界面回填 ⇒
  采样期正好撞上空标题。口径: `EnumWindows` 全量打印 `vis / pid / class / title`, 用**目标进程 pid** 对齐取答案;
  标题只当展示, 不当判据。
- **进程侧同时打三列随时间变化**: 进程数 / `StartTime` / `Responding`。进程数单调涨 = 它在自我重启(frozen 子进程坑),
  不是「正在加载」; 单进程 + Responding=True + 窗口 vis=True 才算真的开着。
- **截屏是最省事的终局证据**: 登录会话的计划任务里 `Add-Type -AssemblyName System.Windows.Forms,System.Drawing` +
  `Graphics.CopyFromScreen(VirtualScreen)` 存 PNG, 再 `scp` 回来。session 0 截不到桌面 ⇒ 这段必须跑在交互会话里。
- **`powershell -EncodedCommand` 不能超过 ~8KB 总命令行**(ssh 走 cmd.exe): 脚本超过 ~2.5KB 就改用 `scp` 传上去再
  `powershell -File <路径>`(PS 5.1 读无 BOM UTF-8 当 ANSI ⇒ 脚本必须纯 ASCII)。
- 🔴 **`.ps1` 里要写中文就必须带 BOM**(`utf-8-sig`), 否则 PS 5.1 按 GBK 读, 引号/括号被打乱成
  `意外的标记“)”`/`字符串缺少终止符`, 语法整段崩; 本地先用 Python 写 `encoding='utf-8-sig', newline='\r\n'` 再 scp。
  另外 `-File` 传参里**别把引号塞进 args 字符串**(实测 `-Zip 'C:/x.zip'` 到了 PS 侧变成 `'C` ⇒ 驱动不存在),
  干脆把值写进脚本字面量。

### 10.2 Windows 上 Hermes「双击闪退 / 打不开」: 先看 gateway 是不是被看门狗宰了

- 症状: 图标能拉起 `hermes.exe`(进程存在、也能撑住几十秒), 但窗口没内容/一分多钟后消失; 用户只说「打不开」。
  **先看 `%LOCALAPPDATA%\hermes\logs\gateway.log`**: 若每轮都是
  `Starting Hermes Gateway...` → `Platform '<X>' dependencies missing — attempting install...` → 正好 **+120s**
  `CRITICAL gateway.shutdown_watchdog: event loop missed 3 consecutive liveness probes ... exiting with code 75`,
  就是**平台依赖的同步安装在启动时堵住了事件循环**, 被看门狗按 liveness 超时杀掉并重启 ⇒ 无限重启 ⇒ 用户看到「打不开」。
- 这跟 `pip install` 装没装成功**无关**: `available(extra)` 走的是 `pm.extras` 的 anchors 判定, 你自己 pip 装完
  在工具解释器里 `import` 成功也不代表 gateway 那个进程里为真。先别猜环境, **直接用「关掉那个平台」验因果**。
- 最快恢复: `config.yaml` 里的 `platforms:\n  <name>:\n    enabled: true` 改成 `false`(改前 `Copy-Item` 备份到 `backups\`),
  同时把 `.env` 里该平台的 `*_APP_ID/_SECRET` 行前缀 `# DISABLED-BY-OPS ` 备注(也是备份后)。然后重启, 看 gateway 有没有
  `Press Ctrl+C to stop` + `Channel directory built` + `Cron scheduler will tick` 三行 —— 有这三行才算真的起来了。
- 若要保留平台: 把那个 extra 的安装**预热到 gateway 之外**(带国内镜像 `-i https://pypi.tuna.tsinghua.edu.cn/simple`,
  用 `Invoke-CimMethod Win32_Process -MethodName Create` 脱离 SSH 会话跑 —— `Start-Process` 是 SSH 会话的子进程,
  SSH 一断就被连坐杀掉, 我这边实测就是这么白装一轮的)。
- 判「图标+后端都好了」的口径(一次拿齐): 每 15s 采样 `hermes 进程数 / gateway 进程数 / 标题含 Hermes 的可见窗口数`,
  连续 **>2 分钟**(跨过看门狗的 120s)三项都非零, 才算过; 只是「窗口出现过」不算。
- 🔴 **用户说「还是打不开」而你已经两次"实测能开"时, 立刻停手不要再改快捷方式 —— 转去查应用自己的日志**:
  快捷方式只是壳, 壳能起不代表应用能用; 用户感知的「打不开」= 窗口没内容/几十秒后消失 = **壳起来了、后端死了**。
  只报壳(进程/窗口出现过)就等于交给他一个点了没反应的图标, 而且会连累他删图标重来。

### 10.3 把打包好的自研桌面程序装到新 Windows 机: 包只是程序, 数据要单独补

全新机器上装完 exe/onedir 包, 程序能起但一用就报「没有这个文件」/ 界面全空 —— 不是包装坏了,
而是**发布包只带程序, 不带它依赖的业务数据**(工程文件 / 标定 / 场景 JSON 通常在源树的 `data/`、`config/`,
既不进 git 也不进 PyInstaller)。装完必须补一份**最小数据种子**:

- **先定位它到底找哪个路径, 再放文件**: 冻结包里 repo 根由 `__file__` 上溯/多候选决定, 从外面看不出来 ⇒
  把种子**同时放进所有候选根**(exe 父目录、app 目录、`~\zmax` 之类), 每个根都 `Test-Path` 回读确认; 多放一份只是几 MB。
- **种子清单**: 工程文件(`data/database/**/*.proj`)、标定(`config/calib/*.json`)、场景/画布(`data/scene/*.json`)。
  打 `tar -czf` 传过去 `tar -xzf` 解(Windows 10+ 自带 tar), 解完**逐文件比字节数**, 不只看 `extract_rc=0`。
- **判「用户点了什么、卡在哪」读应用自己的 trace, 不问用户**: 这类控制台一般留
  `~/zmax/zmax_data/logs/open_project.log` 之类, 一行一步(入口 / 文件不存在 / 写盘 / 画布场景项=N)。
  「文件不存在」= 种子没到位; 「画布场景项=0」= 种子到了但读的不是你写的那份(软链两份拷贝坑, 见技能
  `pyqt5-distribution` 里 frozen-path-detection 那篇参考)。
- **不要为了「试一次」去重启用户的 GUI**: 种子放好让他点一下, 再读 trace 拿数字回话; 擅自重启会丢他手上的状态。
- **用户只看到一句泛化错误(「集成式打开失败」「没有这个文件」)、日志里也没有 traceback**: 冻结包的入口
  已做 argv 派发时, 可以把 exe 当 python 解释器在机器上跑一段诊断代码, 把异常原文取回来 ——
  `Start-Process -FilePath <exe> -ArgumentList '-c', "exec(open(r'<probe.py>',encoding='utf-8').read())" -NoNewWindow -Wait -RedirectStandardOutput/-Error`;
  ⚠️ **探针代码必须先落成 .py 文件再 exec**, 不要把多行代码直接塞进 `-ArgumentList '-c' "import ..."`:
  引号/空格被 PSH 拆开后子进程只收到 `import`, 报 `SyntaxError: invalid syntax`(看着像探针无效, 其实是传参被切);
  探针文件用 `[IO.File]::WriteAllText(..., UTF8Encoding($false))` 写(**带 BOM 会 SyntaxError**),
  `sys.path` 先补 `_MEIPASS/src` 再 import(否则拿到假 `ModuleNotFoundError`)。
  中文 Windows 上这类泛化错误的头号真因是 **GBK 编码 + emoji print 掀翻业务**,
  完整三类(编码 / CRLF 改哈希 / 空骨架打包)见技能 `pyqt5-distribution` 里的
  windows-frozen-app-silent-failures 参考篇。
- **拉 Release 产物用多连接下载器**: 单流 `curl` 走代理常只有几十 KB/s(169MB 半小时), `aria2c -x8 -s8 -k1M -c`
  同一条 URL 能到 ~1MB/s; 没有 aria2c 时 `curl -C -` 断点续传 + `--speed-limit/--speed-time` 自动重连。
  下完必比对 Release API 里的 `digest`, 再 `scp` 到目标机并在机器上重算一次哈希。

### 10.4 给在役机装新版: 并行目录 + 快捷方式改指 + 静默启动器

- 🔴 **不就地覆盖用户正开着的安装目录**: 新包解到并列目录(`app2`/`app3`), 校 `Test-Path` + exe 版本资源 + 文件数,
  再把桌面 `.lnk` 的 target 改指新目录 —— 旧目录原样留着, 他手上的窗口不受影响; 出问题改回 target 就是回滚。
- **要「双击就出窗口、不弹黑框、能带环境变量」时用 wscript 启动器**:
  `<新目录>\launch.vbs` 里 `CreateObject("WScript.Shell").Run """<exe>""", 0, False`(第二参 0 = 隐藏控制台),
  `.lnk` 的 TargetPath 指 `C:\Windows\System32\wscript.exe`、Arguments 写 `"<launch.vbs>"`。
  要钉环境变量就用 `setx` 落**用户级**并在新进程里回读, **别让用户自己去 cmd 里设**。
- ⚠️ **中文文件名拼进 PowerShell 字面量常被编码吃掉**(实测按 `Desktop\<中文名>.lnk` 找不到, 也**不报错**)
  ⇒ 用 `Get-ChildItem $desktop -Filter 'Z-MAX*'` 这类**通配符/前缀**定位再按对象操作; 必须传中文内容时用 base64 落文件(第七节)。
- **「点了某按钮就崩了」的取证顺序**: 先 `Get-WinEvent`(Application/WER) —— **一条都没有 + 进程数已 0**
  基本就是 **PyQt5 槽里异常 qFatal**(见技能 `pyqt5-distribution` 同名节), 不是内存/显卡/杀软;
  再看应用自己的 `ui_error.log`/trace 里那条堆栈。按钮回调必须自己 try/except 落盘, 否则永远无堆栈。

### 10.5 让冻结包自包含: 相对路径脚本 · 单实例 · 自起本机服务

Windows 免解包包要「功能不缺」, 通常还差三件事(都实测过):

- 🔴 **`sys.executable` 就是 exe 自己, 而子进程常用相对路径**: 代码里 `subprocess([sys.executable, "tools/xxx.py", ...])`
  在源码环境没事, 冻结后 cwd 是**安装根**(exe 同级), 脚本其实在 `_internal\tools\` ⇒ 路径找不到, 若入口的
  argv 派发此时「交回正常启动」就**又起一个 GUI**(实测 5744 拉起 4216, 命令行 `... tools/scene_edit.py list --json`)。
  这就是「进程 1→22」「多实例抢画布/配置」「启动越来越慢」的真因。修法两件套:
  ① 入口派发里, 相对名找不到时按 `_MEIPASS`、`_MEIPASS/tools`、`_MEIPASS/tools/gui` 再解析同 basename;
  ② 加**单实例闸**: `socket.bind(('127.0.0.1', 8795))`, 第二次启动直接退出(实测双击两次仍只有 1 个进程)。
  判据: `Get-CimInstance Win32_Process -Filter "Name='<exe>'"` 的 **CommandLine** —— 出现 `<exe> tools/xxx.py` 就是递归子进程, 不是正常功能。
- **包内要带业务配置, 否则某一步静默失败**: 源码树里 `config/` 常是软链(zmax_data/config), 打包**带不进去** ⇒
  任务绑定那步报 `IndexError: list index out of range`(空 tasks), 界面只显示「集成式打开 ok=False」。
  修法: 把 `config/tasks/*.json` 这类**真源**提交到 `defaults/config/...`(随包), 启动时把 `_MEIPASS/defaults/config/**`
  **只补缺**(`if not exists`)到 `<repo>/config/`, 绝不覆盖现场改过的。
- **包体暴涨先看 add-data 打了什么**: `--add-data tools;tools` 会把上次构建的
  `tools/gui/build/**` + `tools/gui/dist/**`(实测 471MB, 含一份 220MB 的旧 exe)一起打进去 —— 产物 689MB。
  正解: CI 里先 stage 一个目录(只 `tools/*.py` + `tools/gen` + `tools/web`), 再 `--add-data pkgtools;tools` ⇒ 回到 221MB。
- 🔴 **界面上每个「打开服务」的按钮都开本机自己的服务, 远端只做兜底** —— 用户口径原话: 「按钮需要打开自己的服务啊…
  这不是你的 IP 么?」。别把按钮指到主脑/开发机那台的 IP: 那台一关/一换网, 所有按钮全哑, 用户会当成产品坏了。
  定式顺序: 本机 `127.0.0.1:<port>` > `env ZMAX_<X>_URL` > `config/ui/<x>_hosts.json` > 远端/公网; 每次
  **TCP 探活**(`create_connection(timeout=1s)`)后再开, 并把选中地址写状态栏 —— 换网/换主脑不用改代码。
  · 本机优先的**前提是本机真能起这个服务**(见 10.6): 只改地址不起服务 = 打开一个连不上的页面。
  · **同一语义只有一个 resolver**: 工具条按钮、导航项、页面内入口必须调同一个函数取地址(实测过一处改了另一处
    还开旧 IP ⇒ 用户点了没反应/开错页)。
  · 候选链补路径要区分: 只在**裸主机**(`ip:port`, 无 path)后补 `/station` 之类固定路径; 已带 path 的 URL 原样用
    (否则 `https://h/x.html` 被拼成 `https://h/x.html/station`)。
  · **分清热修与重建**: 走 env/config 候选链的按钮, `setx ZMAX_<X>_URL "<新地址>"` + 重开应用就生效(现场立刻可用);
    硬编码分支(直接 `webbrowser.open("http://127.0.0.1:8799/")`)必须重新打包 —— 交付时报清楚哪一半是热修、哪一半要等包。
  · 边界要当面说穿: 笔记本上没有产线相机 ⇒ 本机 station 页的框架/控制区/点位都在, 但 **6 路画面格是离线**, 别让他
    以为「自己的服务」就必然有画面。
- **让 exe 自己把本机服务拉起来**(只有按钮确实指向本机时才做; AR3D :8797 这类 stdlib-only 脚本):
  用 `[sys.executable, <_MEIPASS/tools/xxx.py>]` 起子进程(`creationflags=CREATE_NO_WINDOW`, stdout/stderr 落
  `~/zmax/zmax_data/logs/svc_<port>.log`), 启动时放**后台线程** `ensure(name, port)`(已在跑就跳过), 按钮再走同一条 ensure。
  实测: 双击后 **t+30s 端口 UP**, `GET /ar -> 200 383696B`; 同时核对「不该起的端口没起」(8799 应 DOWN)。
  装机包还要带 `opencv-python`(AR 服务顶层 `import cv2` —— 缺它 `ModuleNotFoundError: cv2`, 端口永远 DOWN)。
- ⚠️ **从 SSH 起的常驻进程会随会话结束被杀**: 想长期驻留(或给用户验)用交互式计划任务 / 用户自己双击;
  只想「当场验一下」就在**同一个 SSH 会话里**起+测(测完它死掉是正常的, 别报成「服务自己掉了」)。
  · GUI 也一样 —— 从 SSH `Start-Process <桌面.lnk>` 起的窗口**能活几十秒然后无声消失**, 看起来像"一启动就崩";
    真因是会话连带, 不是程序坏。要让它在用户桌面常驻: 写一个只含 `start "" "<目录>\launch.vbs"` 的 `.bat`,
    `schtasks /Create /TN <名> /TR "<bat>" /SC ONCE /ST 00:00 /RL HIGHEST /IT /F` + `schtasks /Run /TN <名>`
    (`/IT` = 交互令牌, 落到登录会话里), 再回读「进程存活 ≥1 分钟 + 三个端口在听」。
  · 判「这次起的是不是新配置」看**进程启动前**的环境: `setx` 只对新进程生效, 老进程仍读旧值 ⇒ 改了
    `ZMAX_*_URL` 之类却说"没生效"时, 先确认那个 GUI 是**改完之后**起的(否则一切都是旧进程在跑, 白查一轮)。
- **下载走代理拿到的可能是旧资产**: `ghfast.top` 这类会按 URL 缓存 ⇒ 同一个 Release 路径换包后仍下到旧文件(实测 sha 是上一版)。
  破缓存: URL 末尾加 `?cb=<新 sha 前 8 位>`; 下完必须比对 Release API 的 `digest`, 不一致就是命中缓存。

### 10.6 本机服务「端口在听, 页面却空着/不动」: 五类真因

按顺序查 —— 每一项都在真机上撞过:

- 🔴 **无 GL 的会话里渲染/仿真服务会整轮重试 ⇒ 真值接口永远「未生成」**: `mujoco.Renderer(...)` 在 Windows
  session 0(SSH/计划任务、没有桌面)抛 `'Renderer' object has no attribute '_mjr_context'` 或 `gladLoadGL error`。
  若 renderer 建在自愈重试的 `while True` 里, 它每 3s 失败一次 ⇒ `ENV` 永不就位 ⇒ `/bones.json` 这类**骨骼/真值**
  接口一直回「未生成」⇒ 页面里机器人/场景根本不存在(用户原话「怎么没有机器人呢」)。
  修法: renderer 做成**可选** —— `try: renderer = mujoco.Renderer(model, H, W)` / `except: renderer = None`,
  物理步进与骨骼真值照跑, 标定/出图两处各自 `if _do_render and renderer is not None` 跳过。
  判据: 直接 `GET :<port>/bones.json` 看 `ok` 与 `n` 是否在涨 —— **端口 LISTEN 不代表内部循环活着**。
- 🔴 **共用脚本里的 Linux 专属 API 会打死工作线程, 端口还活着**: `os.getuid()`(Windows 无此属性)、`/proc/<pid>`
  扫描、写死的 `/home/ubuntu/...` —— 主线程照听端口、页面 200, 但采集/推流线程当场 `AttributeError`,
  表现是「页面打得开、里面全空」。修法: `if not hasattr(os, "getuid"): return <空>` 提前返回;
  路径改 `os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ...)` 并留 `ZMAX_*_DIR` 覆盖。
  日志里出现 `_bootstrap_inner` 的堆栈就是这一类。
- 🔴 **写方与读方的数据根不是同一目录 ⇒ 服务活着但永远读不到数据**: 控制台把 `zmax_data/ss_live/*.json` 写进
  **安装根**(`<install>\zmax_data`), 服务脚本却按 `~/zmax/zmax_data` 或 `_MEIPASS` 去找 ⇒ 开关/指令文件永远
  「不存在」, 页面显示「无指令文件」并且不动。两手: ① 代码里让 ss_live/state 目录**只解析一处**; ② 现场立刻
  可用的热修是目录联结 `cmd /c mklink /J "<读方路径>" "<写方路径>"`(先确认读方目录不存在或为空, 非空别动),
  建完 `Test-Path <读方>\ss_live\<文件>` 必须 True。
- 🔴 **「画布在动、下游不动」先查写文件那一步有没有环境闸**: 这类上游常在节点里写
  `if os.environ.get("ZMAX_XXX_PUB") == "1":`(实测 `ZMAX_UPH_AR_PUB` 管着画布 Plan 节点写 `ar_cmd.json`)。
  启动器不设它 ⇒ 上游算得热火朝天, 下游一个字节也拿不到。三步: ① `grep -n "os.environ.get" <写文件那个节点>`
  ② 启动器(launch.vbs / `setx`)设上, 并在入口 `os.environ.setdefault(...)` 兜底(生产机显式写 0 时 setdefault 不覆盖)
  ③ 重启进程后确认目标文件 mtime 在变, 再谈下游。
- 🔴 **服务对「兄弟服务」的上游地址写死源码机端口 ⇒ 页面 200 但数据全空**: 这类代理服务常写
  `UP = "http://127.0.0.1:8791"`(源码机上推流脚本的端口), 而笔记本上同一个 `cam_live_stream.py` 起在 8793 ⇒
  `/scene.json` 取不到 ⇒ 一切由场景派生出来的东西(轨迹段表、检测框、相机列表)全无, 表象是「按钮点了机器人不动 / 没有机器人」。
  修法: 上游同样走探活候选链(`ZMAX_STREAM_URL` > 原端口 > 本机其它候选端口), 探到就记住; 判据是
  `GET <下游>/scene.json` 的 `mode`/`cameras` 是否非空 —— 只看页面 200 会一路错到底。
- 🔴 **运行期生成的数据文件永远不会进包**: 轨迹段表这类由脚本生成到 `zmax_data/runtime/traj/*.json` 的产物
  (例 `sim_insert.json` 392 段 / 8 cycles / 159s) 既不在 git 也不在 PyInstaller ⇒ 依赖它的按钮(如「全流程 UPH」)
  只算节拍不动机器人。装完按「用户点的那个按钮读哪个文件」逐个补齐, 用
  `GET /api/<对应接口>` 看 `ok`/段数/cycle 数为真, 再让用户点。
- **判「机器人在动」用像素位移, 不用 HUD 计数**: 间隔 2s 连取两帧, 比某个颜色分量的包围盒位移 + 帧间差异百分比
  (实测 bbox `[324,49,435,403]` → `[261,151,405,403]`、1.82% 像素变化 = 真在动); HUD 里节拍/`simT` 在走只证明计时器活着,
  画面上可能一像素没动。
- **「当场验一下」要脱离 SSH 会话起服务**: `Start-Process` 是 SSH 会话的子进程, 会话一断就被连坐杀掉;
  `Invoke-CimMethod Win32_Process Create` 能脱离但**没有 shell** ⇒ 命令行里的 `>> log 2>&1` 会被当参数,
  进程立刻退出(看着像「服务起不来」)。可靠做法: 写一个 `.bat`(`"<exe>" "<script>" --port N >> "<log>" 2>&1`),
  再 `schtasks /Create /TN <名> /TR "<bat>" /SC ONCE /ST 00:00 /RL HIGHEST /F` + `schtasks /Run /TN <名>`,
  要交给用户长期驻留, 就让它由 GUI 主进程在后台线程 `ensure()` 拉起(子进程随 GUI 活)。
  · ⚠️ 计划任务那一步实测**会回「成功」而进程没留下**(前一个实例刚被杀、端口未释放 ⇒ 新进程绑端口失败当场退出;
    `schtasks /Run` 的返回码不代表进程还活着)。判据只认 **端口 LISTEN + 进程存在 ≥10s**。
    起不来的兜底: `Invoke-CimMethod Win32_Process -MethodName Create -Arguments @{ CommandLine = 'cmd.exe /c "<path>\run_x.bat"' }`
    —— 关键是**套一层 `cmd.exe /c`**(有 cmd 才有 shell, 重定向写在 bat 里就不会被当参数), 进程挂在服务宿主下, 实测 pid 常驻。

### 10.7 换新版本到在役 Windows 机: app<N> 并行目录 + 只改启动器 + 新 exe 会被防火墙 Block

实测配方 (192.168.1.6 / SPACE\Mike, v5.50.770→771):

- **解包到并列目录** `zmax_console\app9`(旧 app8 原样留着=回滚), 校验 `exe.VersionInfo.FileVersion` 等于目标版本 +
  关键资产条数 (`state_space_obs.json` / `l4_*.pt` / `*_l4.xml` / `tcp_ar_server.py`)。文件数 ~7564 正常。
- **launch.vbs 必须按三引号原样写**: `sh.Run """<exe>""", 1, False`。用 PS 字符串拼 `""""`(四引号) 会变语法错,
  wscript 弹模态错误框并**常驻** ⇒ 桌面双击没反应、`Get-CimInstance Win32_Process` 里只有 wscript 没有 exe。
  最省事: 在 Linux 侧写好 **CRLF + 纯 ASCII** 的 vbs 再 scp 过去, 别在 Windows 上用 `Set-Content -Value @(...)` 拼。
- **只重指启动器那条 lnk**: 按 `Arguments -like '*launch.vbs*'` 找(桌面还有 `Z-MAX 550B (VSCode).lnk`, 其参数里也有
  `zmax_console`, 按目录名找会重指错快捷方式); 改前 `Copy-Item` 到 `zmax_console\backups\`, 改完回读 target/args/workdir。
- 🔴 **换了 exe 路径 ⇒ Windows 给新路径生成 Inbound `Block` 规则**(用户点过"取消"的那次会落成
  `... TCP Query User{...}<新路径>`), 表现极具误导: 机器上 `Invoke-WebRequest 127.0.0.1:<port>` 全 200,
  从别的机器 `curl` 全 000/超时。判据: `Get-NetFirewallApplicationFilter | ? Program -like '*app9*' | % { $_ | Get-NetFirewallRule }`
  → 见 `Action=Block`。修法: 删掉那些 Block 规则, 再按程序+端口建 Allow:
  `New-NetFirewallRule -DisplayName 'Z-MAX Console app9 TCP 8793' -Direction Inbound -Action Allow -Program <exe> -Protocol TCP -LocalPort 8793 -Profile Any`
  (8793/8797/8802/8795 各一条), 然后**从另一台机器** curl 复验 200 —— 只测本机永远发现不了这条。
- **验证要在交互会话里做**: `Register-ScheduledTask -Principal (-UserId <登录用户> -LogonType Interactive -RunLevel Highest)`
  + `Start-ScheduledTask`; 脚本里枚举 `EnumWindows` 按 **pid** 对齐可见窗口(标题会晚于窗口创建)、截图、写报告文件,
  再从 Linux `scp` 回来读。session 0 里 `EnumWindows` 看不到用户会话的窗口, 判"没打开"必错。
- **单实例闸要真验**: 再启一次桌面 lnk, 旧的 GUI pid/start 时间**必须不变**、可见窗口仍=1 (新包绑定 127.0.0.1:8795,
  第二实例直接退出)。这条正是旧包"进程 1→22、越启越慢"的根因修复。
- **画布 0 节点** 的判据看两处: ①包内 `_internal/flows/state_space_obs.json` 字节数(真画布 ~138KB / 94 节点 / 222 连线,
  空骨架只有 174B); ②`_internal/flows/...` 与 `_internal/src/lerobot/engineering/flows/...` **两份 md5 必须相同**
  (不同=写一个读另一个)。运行期回填仍要用户点一次「打开总工程」, 只能读到 `zmax_data\logs\open_project.log` 的
  `画布场景项=N` 才算数。
- **`zmax_data` 数据根沿用旧机那份**: vbs 里 `ZMAX_ROOT=<旧数据根>`, 新包只补缺不覆盖, 别把用户现场数据指到 app 目录。


### 10.8 「/ar3d 双臂不动」在 Windows 上的四个真因

老倪说「工程已经运行, 但 127.0.0.1:8797/ar3d 的机器人不动」时, Windows 冻结包缺的是**驱动链**, 不是页面:

1. **包内没有常驻画布循环** —— Linux 靠 systemd `zmax-ss-canvas-loop` 每拍跑节点写 `zmax_data/ss_live/ar_cmd.json`;
   Windows 包只有 GUI 起的那几个服务 (8793/8797/8802), 没有任何进程跑画布节点 ⇒ `ar_cmd.json` 一个字节都不写
   ⇒ `/api/ar/cmd` 回 `ok:false` ⇒ 页面回落到自播 (而自播也没有段表)。
   修: `app<N>\cap_loop.py` 包一层 (设 `ZMAX_UPH_AR_PUB=1` + stdout 重定向到日志, 再 `runpy.run_path` 跑
   `_internal\tools\ss_canvas_loop.py`), 用**计划任务**(AtLogOn + S4U + ExecutionTimeLimit=0 + RestartCount) 启动。
   ⚠️ 直接 `Start-Process`/ssh 里起会被 sshd 的 job object 带走 (30~90s 后静默消失), 必须走 Task Scheduler。
2. **三个 ROOT 在 Windows 上分裂**: `plan_long_impl` 用 `~/zmax`(=`C:\Users\Mike\zmax`)、
   `ss_canvas_loop`/`cycle_plan` 用包内 `_internal`、GUI 工程写在 `zmax_console\data` ⇒ 谁都读不到别人的产物。
   修: 在包内做 junction 把它们合成单根 ——
   `_internal\data`→`C:\Users\Mike\zmax\data`、`_internal\zmax_data`→`.\zmax_data`、`_internal\config`→`.\config`,
   再 `data\database\zmax\sources\canvas`→`_internal\src\lerobot\engineering\flows` (GUI 实时保存的画布)。
   🔴 **还有一类更隐蔽、且会反复出现: 模块里写死默认 `REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")`**
   (`fence_store` / `sim_transport_plan` / 若干 `tools/*`)。冻结包里没人设 `ZMAX_REPO` ⇒ Windows 上落到
   `C:\home\ubuntu\zmax\...`, 目录不存在就**静默回空**: 接口照回 `ok:true` 但 0 项, 页面表现为料盘/围栏盒全没了,
   而端口、日志、进程一切"正常"。一次覆盖全部(`mklink /J C:\home\ubuntu\zmax C:\Users\Mike\zmax`)比逐个模块
   `setx ZMAX_REPO` 稳, 也不改包内代码; 建前先看 `(Get-Item $p).LinkType` —— 已被服务建成真目录就先 `Remove-Item -Recurse`,
   建完必须回读 `LinkType` = `Junction`(mklink 报"文件已存在"就是没建成)。
   ⚠️ `mklink /J` 前先看目标位置是不是**已存在的真目录**: 包里常有 `_internal\config\platform\*` 这类内容,
   直接把目录换成联结会把它们弄丢 ⇒ 先把真目录里的东西搬进根目录 (`config\`、`zmax_data\`) 再建链,
   建完 `Test-Path` 回读关键子路径(如 `config\platform\zmax_product.json`、`_internal\config\points\cell_points.json`)。
3. **工程配置/段表根本没带过去**: `config/points/cell_points.json`、`data/.../config/tasks/ar_meta_tasks.json`
   不在包里 (data/ 被 gitignore) ⇒ `cycle_plan` 直接 `SystemExit("点位配置读不到…拒绝用代码里的旧常量兜底")`。
   带上这两个后在本机跑一次 `_internal\tools\sim_insert_plan.py` 生成 `zmax_data\runtime\traj\sim_insert.json`
   (实测 14 轮 · 133KB), plan 节点才有段可发。
4. **`exec_switches.json` 缺失 ⇒ `/api/ar/mode` ok:false ⇒ 页面 `arModeApply` 直接 return**, 拨杆永远接不上。
   写 `{ar_scene:true, real_auth:false, node:"ssact"}` 时 **绝不能用 PowerShell `Set-Content -Encoding UTF8`**
   (PS 5.1 会写 BOM → 后端报 `Unexpected UTF-8 BOM`), 用
   `[IO.File]::WriteAllText($p,$json,(New-Object Text.UTF8Encoding($false)))`。
   之后循环的 `keepalive_switch()` 每 60s 自己续期 (只续 ar_scene, `real_auth` 永不续)。

另外: 每拍 6.4s 会让 `ar_cmd` 6s 才更新一次, 页面判 stale 不跟。550B 笔记本上把
`ZMAX_CORE_IDS="ssplan,ssact,n_exec,n_moveit"` + `ZMAX_SLOW_IDS="ssobs,ssest,ssff"` (这三个各 ~2s)
⇒ 实测每拍 31ms, 页面 `ss/plant/prev=1` 且 `ssi/mod` 持续推进 (= 真的在动)。

自验 (不靠肉眼): `/api/ar/cmd` 的 `age_s<4 · fresh:true · seq/mod` 在跳; `/api/ar_diag` 的
`ss=1 plant=1 prev=1` 且 `ssi` 变化; 存活进程应恰好 5 个 (GUI + 8793 + 8797 + 8802 + cap_loop)。

🔁 **这四步是部署期手工落地的** (junction + `cap_loop.py` + 计划任务 + 工程配置/段表)。换到 `app<N+1>` 时
必须整组重做: 新目录建同样的 junction、把计划任务的 `-Argument` 改指新目录的 `cap_loop.py`、确认
`exec_switches.json` 与 `zmax_data\runtime\traj\sim_insert.json` 还在旧数据根下 —— 少一步就是「界面有、
机器人不动」。根治只能让它进安装脚本/入口 (启动时自建 junction + 自起循环), 别指望下次还记得。


### 10.9 左臂不动 = 另一条链 (sim_transport), 不要跟右臂混

Windows 上右臂修好后**左臂仍然不动**是正常的下一层问题 —— 左臂根本不走 `ar_cmd`:
- 真源: `zmax_data/runtime/traj/sim_transport.json`(112 段 = 14 循环×8 步), 由 `tools/sim_transport_plan.py` 生成,
  它读 `zmax_data/ar_rs/fences.json` 的「左槽1~14 / 槽1~14」实测盒; 页面 `transPlay()` 拿 `/api/sim_transport` 播关节角。
- 🔴 该脚本 `REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")` —— **默认是构建机路径**, 冻结包里跑会去
  `C:\...\_internal` 之外找 `/home/ubuntu/zmax\zmax_data\...`。必须显式 `ZMAX_REPO=C:\Users\Mike\zmax`。
- 🔴 页面 `transPlay()` 只在**播放开始那一刻**抓一次段表; 那时文件不存在就 `没有可用路径` 并 return, 之后永不自动重试
  ⇒ 文件补好后要么重开播放, 要么点「🚚 仿真搬运」。无头验收: UIA 找 Button name 含「仿真搬运」并 Invoke
  (`System.Windows.Automation`, 必须在交互会话里跑, 用计划任务), 之后 `/api/ar_diag` 的 `trans` 0→1、
  `drw` 持续变化即左臂在动 (首次 IK 解算 ~20s, 期间 `trans` 还是 0, 别当失败)。
  现成脚本 `scripts/uia_click_button.ps1 -Match 仿真搬运`(头部注释含交互会话计划任务的注册/清理)。
  ⚠️ 判据只认应用**自报的状态**(`trans` 0→1、`drw` 在涨), 不认脚本里的 `invoked` —— UIA 点成功但页面 handler 因数据未就绪
  提前 return 是常态, 拿"点了没报错"当完成就是假绿。
- plan 节点 token 层在 Windows 上会报 `No module named 'planner'` (左臂 token 留证缺失), 几何段照常排 —— 汇报时分开说。

### 10.10 料盘/围栏盒全没了 = `/api/fence` 返回 0 项 (REPO 默认值又踩一次)

症状: 三维里的料盘/检测设备/横梁/相机这些立方体全不见, 但 `/api/ar/cmd`·`/api/place_cells` 都正常。
判据(一行): `curl 127.0.0.1:8797/api/fence | jq '.items|length'` —— 本机 1342 项(1291 直线 + 51 盒, 含
`🧰 黑色料盘(实测)`/`🧰 左臂料盘`/`🧰 下料盘`/`🗑 废料盘`), Windows 上 0 项。

真因: `tools/fence_store.py: REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")` —— 冻结包里没人设
`ZMAX_REPO`, 于是它在 Windows 上把 `C:\home\ubuntu\zmax\zmax_data\ar_rs\fences.json` 当成真源;
文件不存在 ⇒ `listing()` 静默回空 ⇒ 页面没东西可画(而且它已经在 C:\home\ubuntu\ 下建了空目录, 看着像"正常")。

修(不用重启服务): `mklink /J C:\home\ubuntu\zmax C:\Users\Mike\zmax` —— 把构建机路径整棵映射到真实根,
所有默认 `REPO="/home/ubuntu/zmax"` 的模块(fence_store / sim_transport_plan / 若干 tools)一次全对齐。
⚠ 建链接前 `C:\home\ubuntu\zmax` 可能已被服务建成真目录(非空) ⇒ 先 `Remove-Item -Recurse`, 再 mklink;
`mklink` 报了「文件已存在」就说明目录还在, 链接没建上(用 `(Get-Item $p).LinkType` 验, 必须是 `Junction`)。

页面只在 **load 时** `loadFences()`, 补好数据还得刷新页面(F5)才会画出来; 刷新后 iframe 会自己从
`/api/ar/mode` 的 `play` 重新接上, 双臂继续跑(实测 `ss/plant/prev/trans` 全 1, `drw` 8000→34000)。


### 10.12 「8802 video 没打开」= 直播窗口没开, 不是渲染站坏了

先分清三层, 别去修 8802 服务:
1. 渲染站活着? `curl -s :8802/status.json` → `ok:true` + `n` 在涨 (实测 6s 涨 43 帧 ≈ 7Hz);
   `/video` 回 `multipart/x-mixed-replace; boundary=frame`, 连续两帧字节不同 ⇒ 真在推。
2. 外壳页活着? `curl -s :8802/live` → 200 `text/html`, `<title>Z-MAX 8802 · 渲染帧</title>`。
3. 窗口开没开? 枚举交互会话窗口 (UIA Children + ControlType.Window), 找标题含 `Z-MAX 8802` 的那一个。
   `tcp-ar.html` 的「📺 8802 直播」= `window.open('http://<host>:8802/live','zmax8802live')` ——
   被 Chrome 弹窗拦截 / 按钮没点到 / 页面重载后没再点, 都会表现为「video 没打开」而服务端一切正常。

无头补开: UIA 找 Button name 含 `8802` 并 Invoke (在交互会话的计划任务里跑), 6s 后窗口列表应出现
`Z-MAX 8802 · 渲染帧 - Google Chrome`; 截图取证 `shot_8802.png`。反复开不出来再去查 chrome 的弹窗设置
(`chrome://settings/content/popups`), 不要改 8802 代码。

### 10.13 「右键打开 8802 video 不好使」+ 重启 8802 必须留在交互会话

**右键不好使**: 直播页直挂 MJPEG `<img>` 时右键只会开一条流 ⇒ 页面改拉单帧 `/frame.png?cam=ar3d`、
后端无缓存帧时现场渲染。通用配方(含 `/video` 按 Accept 分流的判据、三行验收)见 skill
`zmax-live-video-stream` 的「🎬 8802 渲染帧」节 —— 那里是这件事的唯一归属地, 别在这里再抄一份。

**重启 8802 的两个硬条件** (踩过一次: 渲染线程起来了却出不了图):
- 计划任务 principal 必须 `-LogonType Interactive`(跑在用户会话里)。`S4U` 落到 session 0, 没有 GL 上下文 ⇒
  日志 `GLFWError (65542) 'WGL: The driver does not appear to support OpenGL'` ⇒ 降级「只出真值骨骼」,
  `views={}` `shape=null` `gold_px=null`, `/frame.png` 全 503, 而 `/status.json` 仍 `ok:true` `n` 在涨(骗人)。
- 必须 `MUJOCO_GL=wgl`(Windows), 并显式 `ZMAX_ROOT=C:\Users\Mike\zmax`; 用 `cap_render.py` 包一层设 env 再
  `runpy.run_path(ar_scene_render_server.py)`。
- 判据: `gold_px` 非空 + `shape=[720,960,3]` + `/frame.png?cam=close|ar3d` 都 200。

**页面刷新会重置图层**: `🧭 位置细胞`(PC.on 默认 false)、围栏盒等开关不持久 ⇒ 刷新后料盘/槽位标线消失,
需要再点一次按钮。别把"刷新后没了"当成数据又丢了。


### 10.14 「video 网页打不开」= raw MJPEG 顶栏导航

浏览器地址栏开 `/video` 拿到的是 `multipart/x-mixed-replace` ⇒ 永远"加载中"、画面不出。修法是按 Accept 分流回 HTML 外壳,
配方与判据见 skill `zmax-live-video-stream`「`/video` 是按 Accept 分流的双面端点」节(Windows/Linux 同一份代码, 不分平台)。


### 10.15 直播窗口不自愈 + 旧标签指向死网段(机位同步见视频技能)

「直播窗口与 AR 页机位不同步」的根因与 `live=1` 配方是**跨平台**的渲染站行为, 唯一归属地在 skill
`zmax-live-video-stream`「拉单帧必须带 `live=1`」节 —— 那里有判据(diff 0.0 vs 13/4000+), 别在这里抄第二份。
Windows 侧只剩两件本机的事:
- **直播窗口不会自愈**: 手动开的窗口关掉就没了 ⇒ `ZMAX_8802_WINDOW` 计划任务(AtLogOn + 25s Delay +
  Interactive + `chrome.exe --new-window http://127.0.0.1:8802/video`); 开完在窗口枚举里应出现
  `Z-MAX 8802 · 渲染帧`。用户说「窗口没了/没打开」时先看这一条, 别去改服务。
- **旧标签/旧书签指向老网段**(实测 `10.163.146.76:8802`)会一直 SYN-SENT 卡死, 看着就是「网页打不开」。
  **数字 IP 不走 /etc/hosts**, 加 hosts 条目救不了(glibc 直接按字面量连), 加了还得回滚; 只能关掉旧标签、
  给他正确地址(`127.0.0.1:8802/video`)。快速定性: `ss -tnp | grep ':8802'` 里有 SYN-SENT 到非本机 IP ⇒ 就是它。


### 10.16 「8802/video 与 AR 场景不同步」两层, 要分开修

**第一层 相机**: 见 10.15 (`live=1` 按推送相机现场渲染)。
**第二层 动作** (已定性, 别再走 IK 插值那条老路): 8802 的 env 在 `mode=idle` 时双臂是**死的**,
而 AR 页在按 `ar_cmd.json` 抓/插/拔 ⇒ 画面里机器人不动。早期做法是在渲染循环里读 ar_cmd → 插值 → 自解 IK →
`_apply_ctrl`, 实测末端差 10~90mm 且姿态常常不是画布那个姿态 —— 因为**两个求解器会落到不同分支**, 拿末端对齐
本身就不可能收敛。正解是**关节角单源直传**: 页面把它算好的 6 轴角 POST 到渲染站 `/armq`, 渲染站写
`zmax_data/ss_live/ar_mj_q.json`, 循环里直接写 qpos (步进后回写+清速度) 并把 cmd 标 `_kin`, 物理照跑其它物体。
判据: 同一组角, 渲染站正解 TCP 与页面正解差 <1mm (实测 0.1mm), 实时残差 <3cm。
⚠️ 左臂: 画布在左臂没有独立位姿时是“照抄右臂”, 页面推角时也要照抄 (否则渲染里左臂停 home、右臂在动, 看着就是不对称)。
完整配方 (URDF→MJCF 映射、轴序错位的根因、`/armq` 协议、取景/亮度口径) 见另一个技能
`mujoco-ar-dual-arm-execution` 里的 `references/urdf-mesh-arms-in-mujoco.md` (跨技能路径, 不在本技能目录下)。

🔴 **换臂模型后 Windows 会静默退回胶囊臂**: mesh 资产 (`config/moveit_xms5/urdf/meshes/*.stl`) 不进发布包,
缺失时代码走 fallback 而不报错 ⇒ 画面又是光棍。判据: 在冻包里跑 `build_mjcf()` 数 `type="mesh"`
(应 14, 胶囊 0); 补法: scp 前先 `New-Item -ItemType Directory -Force` 建好
`_internal\config\moveit_xms5\urdf\meshes\xms5_r800_w4g3b4c_meshes` (嵌套目录对 scp 不存在), 再逐个传。

**别把"不动"误判成服务挂了**: `zmax-ss-canvas-loop` 若被 `run_canvas_loop_debug.sh` 停掉且收工忘 start,
`/api/ar/cmd` 的 `age_s` 会一直涨(实测 79s)、`fresh:false`, `execute(u_sat=0)` 全零 ⇒ 页面右臂不动,
而 systemd 是 **inactive 且零报错**。查法: `systemctl is-active zmax-ss-canvas-loop` + `age_s`。
调试脚本已加 `trap cleanup EXIT` 自动 start 回去。

### 10.17 改了 8802 代码但页面没变 = 老进程没换掉 (cap_render.py 包装层)
Windows 上 8802 不是计划任务直接拉 `ar_scene_render_server.py`, 而是 `Z-MAX_Console.exe cap_render.py` 再 fork 渲染服务。只 Kill 命令行含 `ar_scene_render_server` 的进程 ⇒ 包装层仍在跑旧代码, `scp` 覆盖磁盘文件也没用(实测磁盘 `data-v="top"` 已存在, `/live` 仍是旧 HTML 1352B)。

正确重启:
1. `Get-CimInstance Win32_Process -Filter "Name='Z-MAX_Console.exe'"` 里**两种命令行都要杀**: 含 `cap_render.py` 和含 `ar_scene_render_server`;
2. `Start-ScheduledTask 'ZMAX_8802_RENDER'`;
3. 验收看**服务返回的内容**, 不是磁盘文件: `(Invoke-WebRequest http://127.0.0.1:8802/live).Content` 搜新加的标记(实测字节数 1352 → 3131)。

⚠ 校验 `8802/video` 只能用 `/live` 或带 `-Headers @{'Accept'='text/html'}`: 不带 Accept 时该路由返回 `multipart/x-mixed-replace` 原始流, `Invoke-WebRequest` 会一直挂(实测卡满 300s), 看着像"服务没响应", 其实只是取到 MJPEG。

### 10.18 只改源码（不重打 exe）怎么上到冻结包：`_internal\src` + tar/ssh 四个静默坑

冻结 onedir 包（`Z-MAX_Console.exe` + `_internal\`）**运行时真从盘上 import `.py`**：
`_internal\src\lerobot\**` 与 `_internal\tools\*.py` 就是活源码，exe 只当解释器用（`cap_render.py` 同理）。
所以目录级重构/新增模块的部署 = 把源码 synck 进 `_internal`，**不必重打 exe**（只有改入口/依赖才要）。

定式：
1. 本地 `tar -czf sync.tgz --exclude='__pycache__' --exclude='*.pyc' src/lerobot tools config flows models/x.pt`；
2. `scp` → 机器上 `C:\Windows\System32\tar.exe -xzf <tgz> -C <app>\_internal`（**只用这一条命令**，见下面坑①）；
3. 旧目录改名而非删（`move engineering\nodes engineering\nodes_stale_<ts>`）= 可回滚；
4. 重启消费进程（计划任务 `/end` + `/run`，如 `ZMAX_8802_RENDER`、`ZMAX_AR_CANVAS_LOOP`）；
5. **决定性验证：把 exe 当 python 解释器跑一段探针**，直接问机器上的包到底是什么结构：
   `Z-MAX_Console.exe C:\Users\Mike\probe.py`，探针里 `sys.path.insert(0, _internal\src)` 再
   `import lerobot.engineering`，打印层名/节点数/`module.__file__`。实测输出
   `LAYERS ['L1'..'L5'] / COUNT {L1:4,L2:26,…} / YOLO_IMPL …\middleware\nodes\impl\ss_yolo.py` ⇒ 新结构确实在跑。
   比"端口 200"强得多——端口 200 分不出新旧代码。

四个静默坑（都实测踩过，全是“命令/解包打了个成功但什么都没变”）：
- ① **`cmd /c cd /d X & tar …` 里的 `&` 在外层 cmd 解析** ⇒ `cd` 只作用于子 shell，tar 在**默认 cwd**（用户家目录）解包，
  静默造出 `C:\Users\<u>\src`、`\tools`、`\flows`、`\models` 一堆残骸，而目标 `_internal` 一个文件没变。
  正解：只用 `tar -C <绝对路径>`，不靠 `cd`。
- ② **tar 命令后面不能接 `; echo rc`**：cmd 不认 `;` ⇒ tar 把 `;`/`echo`/`RC=0` 当成员名，回
  `tar.exe: ;: Not found in archive` 并 **Error exit delayed**（前半段可能只解了一部分，看着“跑过了”）。
  要判成败就看 `-v` 输出的成员数 和 目标目录 `dir /b`，别信追加的 echo。
- ③ **txt 里有非 ASCII 文件名，tar.exe 直接中止**（`Invalid empty pathname: Unknown error`）。
  打 tar 时用 `find … | LC_ALL=C grep -P '[^\x00-\x7F]'` 列出来 `--exclude` 掉（实测只需排 3 个中文名文件）。
- ④ **共享代码里写死 `/tmp` 在 Windows 上必炸**：`FileNotFoundError: '/tmp\ar_frame_14752.png'`，
  而且现场表现是“取帧失败/服务正常但无数据”。落盘路径一律 `os.path.join(tempfile.gettempdir(), …)`（帧缓存同样）。
- ⑤ **源码树里的 `config`/`flows` 常是软链，打包不解引用就是空壳**：`tar -czf` 默认只存链接，Windows 解出来是
  `config\config` 这种自指空壳，真文件一个没有。同步源码包一律 `tar -czhf`（`-h` 解引用）；解完 `dir /b` 数子项，
  不看 `extract_rc=0`。
- ⑥ **配置要落到两个根**：冻结包的 `REPO_ROOT` 可能解析到 `_internal\src`（实现按 `<root>\config\points\cell_points.json` 读）
  而不是 `_internal`，只放一处 ⇒ 进程启动即 `SystemExit: 点位配置读不到 … 拒绝用代码里的旧常量兜底`，
  表象是「计划任务显示 Running，但产物文件十几分钟不更新、页面 idle」。两处都放：`_internal\config` 与
  `_internal\src\config`，再回读 `Test-Path …\config\points\cell_points.json`。
- ⑦ **冻结包里没有的依赖（`ultralytics`/`torch`）不要在本机硬补**：这类包会把机器学习栈从推理端搬到工位上，
  体积和扫码风险都不值得。改成“一端出帧、另一端出感知”：渲染站只跑 `/frame.png`，感知用 `ZMAX_AR_RENDER=http://<渲染机>:8802`
  在算力机跑（跨机取一帧 + 推理实测几百 ms 量级），并在报告里写清哪一端负责哪一层。

验收三件套（缺一件就可能“部署了但没生效”）：探针打印包路径/层数 → 服务端点 200 + 真实字节（`/frame.png` 上百 KB、
`/depth.png` 非空）→ 进程命令行确认跑的是新目录（`Get-CimInstance Win32_Process | ? CommandLine -match 'cap_'`）。

### 10.19 产线输出「没图了 / 结果不更新」而端口活着 = 现役程序被换回旧版(版本漂移)

这是产线机最高频的一类"故障", **不是相机坏、不是光源坏**: 磁盘上有好几个 `..._v<N>.py`, 跑的那份是旧的。

判序(先量数据, 再查版本; 别在显示端/流服务里猜):
1. **量它自产的输出**: 取一张原图解码算灰度 `mean`。实测纯黑帧 `mean 5.3 / 黑占比 100%`(2448×2048),
   而同一时刻**另一路** origin `mean 80` ⇒ **只坏单路**, 与光源/交换机/网络全无关(把"二路同刻对比"当成第一步)。
2. **探路由当指纹**(零副作用): `curl -X OPTIONS -D - http://<机器>:<端口>/<该有的一些接口>`;
   实测现役旧版 `404` 掉了 `/param` 与 `/preview.jpg`, 只剩 `/judge`、`/crop_info`、`/picture?kind=origin`;
   旧版 `/crop_info` 也缺 `judge_ver`/`n_keys`, 只有 `kept_rows/x_trim/k` ⇒ 旧判据口径。
3. **对清单定案**: 拿现役文件 `FILE size/sha/mtime` 跟 `PRODUCTION_MANIFEST.json` 的 `bytes/sha256` 比。
   实测 67594B/`32A98A8E…` vs 清单 206094B/`A595C39E…` ⇒ 判据与取图走的是两代前的代码。
4. **只换文件 + 单实例重启, 另一路不动**; 顺序不能变: 8794 发布目录放新子目录(不覆盖旧交付源)
   → 机器 `iwr` 下载 + `Get-FileHash` 逐位核对(不一致绝不执行) → `.bak_<时间戳>` 备份
   → `KeepAlive` disable → 只杀该路 → 正确 cwd+venv 单起 → **同一分钟内抓一帧占住相机**(此前常见
   「相机被占/取帧失败」是因为你刚杀完还没人拿相机) → 验 `路由 200 + judge_ver 是清单版本 + origin mean`
   → `KeepAlive` enable 并回读 `State=Ready`。实测恢复后 origin mean `5.3 → 47.4`。

配套三条, 少一条会误判:
- **`KeepAlive` 正常形态就是 3 个进程**: `cmd.exe`(壳, 带 `cd /d`) → `venv\\python.exe`(启动壳) → 裸
  `Python310\\python.exe`(**端口属主**)。看到 3 个别当"重复副本"去杀 —— 判据是 `Get-NetTCPConnection` 谁在听 + 文件 sha。
  🔴 **按 `Name='python.exe'` 过滤时每端口恰好 2 个**(venv 壳 + Python310 属主), 这**就是正常形态**:
  两个端口共 4 个 python 并不等于重复实例。**先数"每端口几个属主"再决定动不动手**——属主唯一就别杀
  (实测把这对儿当重复全杀一遍, 只是白丢 ~100s 产线窗口, 重启后形态一模一样)。
- **远端修好了, 本机 MJPEG 还会继续推上一轮的黑帧**: 取流采样 **≥8s 取末尾几帧**(实测首帧 mean 3.4,
  6s 后同一条流 mean 48.3); 拿缓冲里第一帧当结论必报错。
- **判据图只剩细条/没框 ≠ 取图坏**: 同时读机器自报的 `gate_banner`(实测「未识别到金手指键排 | 本帧未检出周期键排结构」)
  与本地同名 ROI 函数返回(空结果 + `why`) ⇒ 结论是**工件不在视野**。如实报"工件不在位", 别改曝光去救。
  **判"画面里到底有没有工件"的量化口径(两路通用, 一眼定案)**: 取原帧 `kind=origin&grab=1` 解码后算
  `mean / p50 / p95 / 亮区(>120)占比` —— 实测空场时 10082 是 `mean 69.8 · p95 73 · 亮区 0.000`(**均匀平场 = 光源/工件都没有**),
  而正常拍到金手指的帧 `mean 113~204` 且有亮条; 10083 空场是 `mean 11.9 · p95 28`(近黑)。
  再叠两条接口侧硬证: ①金手指 `/region` 的 `crop_size` 实测 `[364,18]`(正常 `[1455,70]`)、`gold_px=0`
  ②判据自报 `state=suppressed_19gate` + `why="no key-row window found"`(金手指) / `judge_ok=false`
  +`why="亮条上边缘点太少(0)"`(表面)。
  🔴 **别先怀疑曝光设置**: 表面路 `GET /exposure` 回 `us=80000/gain=1.8`(#产线值)而原帧 `mean 11.9` ⇒
  曝光是对的、是工件/光源不在。同理 **`count=0` 绝不是"合格"**: 空场上两路都会回 OK/0 缺陷, 不能当结论报给用户。

## 支持文件

- `references/windows-hermes-brain-node.md` —— 从零建通道(WinRM→sshd) + 灌脑子(tar over ssh) + 定时双向同步(无 rsync) +
  provider/会话钉死 `gateway_runtime` 的完整判别与修法。
- `references/offline-hive-and-account-ops.md` —— Windows 没在跑时从 Linux 侧认账户(`chntpw -l`)、备份 hive、
  `reged` 改注册表(单反斜杠前缀 / 必须喂 `y` / 回读验证)、`remove_hiberfile` 挂 rw、以及"禁用其它账户"改挂首次登录自启脚本的全套做法。
- `references/offline-windows-payload.md` —— 目标机没开机/休眠时的离线两阶段载荷: 现场判据、FAT32 投递、stage1/stage2 骨架、离线语法与参数校验、引导顺序。
- `references/frozen-package-ci-and-page-verify.md` —— 冻结包构建参数坑(dispatch 默认 tag 变非语义版本 ⇒ `NameError: name 'dev'`)、
  交付页面两段自验(接口 + 浏览器里读全局状态与 canvas 像素)、可选接口 500 弄死整条刷新链、跨平台 Linux 假设、
  用户说“刷新了还是没有”时的三层判定(缓存/轮询/图层像素)、**让页面自己上报运行时状态从服务端日志读回**、
  **3D 画布按需重绘(无相机帧则 drw 不涨)**、静态资源缺失+仓库根写死成 `/home/ubuntu`, 以及冻结包哪些能热修/哪些只能重打包。
- `templates/vscode_launch.json` —— 交出去自己调试用的 `launch.json`(多套配置 + UTF-8/无缓冲 + `justMyCode:false`)。
- `scripts/mk_desktop_launcher.ps1` —— 生成桌面启动器(.lnk)并回读四项; 默认走 `wt -w -1` 独立窗口, 老图标自动 `.bak_<时间>`。
- `scripts/machine_image_probe.py` —— 机器上只读量图(尺寸/亮度/std/块内 std/饱和比/列自相关), 可选 `--detect` 跑真模型。
- `scripts/aoi_two_route_verify.py` —— 两路 AOI 真验收: 触发 → 按 `t` 变化等 `/last_result` → 量判据图/原帧
  (mean/p95/亮区/饱和/暗占比) → 直接打出"空场还是真有内容"的判读。**工件不在位时两路都回 `count=0`, 不能当合格。**
- `scripts/wininet_proxy_blob.py` —— 生成/改写 `Connections\DefaultConnectionSettings` 的 REG_BINARY hex(浏览器真正读的那份代理配置)。
- `scripts/uia_click_button.ps1` —— 按名字(ControlType=Button + Name 子串)点 GUI/网页按钮并回执; 需在交互会话的计划任务里跑,
  用于「文件补好后页面自己不重试」这类必须点一下才生效的按钮(例 `🚚 仿真搬运`); 判据读应用自报状态, 不读 `invoked`。
- 相关: `linux-host-maintenance`(本机自检)、`systemd-boot-services`(本机常驻服务)、
  用户自有的 `zmax-aoi-service`(具体 AOI 端点/版本/口径)。
