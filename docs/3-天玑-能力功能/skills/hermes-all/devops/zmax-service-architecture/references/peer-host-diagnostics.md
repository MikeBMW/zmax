# 从 Windows 侧诊断 Intel / Orin 等对端主机

场景：本机是 Windows 工位机，要在 Intel 550C（Ubuntu）、Orin 上查服务、翻文件、重启进程。

## 连上去

- 没有 `sshpass` / `plink`，用 **paramiko**。装的时候用**有 pip 的系统 Python**
  （`C:\Program Files\Python312\python.exe -m pip install paramiko`），
  Hermes 自带的 venv 没有 pip。
- 密码不要写进命令行长驻：从环境变量读（`ZMAX_INTEL_PW`），脚本只跑一次。
- 主机可能有两张网卡（产线网 `192.168.23.x` + corp wifi `10.163.x`），
  两条都可达时选和本机同网段的那条，不依赖 USB 产线网卡。

## 两个会把脚本挂死的坑

1. **后台进程会占住 SSH 通道**。`setsid nohup cmd > log 2>&1 &` 之后去 `stdout.read()`，
   paramiko 会一直等不到 EOF（后台进程继承了 stderr 管道），报 `PipeTimeout` / `TimeoutError`。
   解法：用子 shell 彻底脱离 `(setsid cmd > /tmp/x.log 2>&1 &)`，然后**另起一次 `exec_command`**
   去查日志和状态；不要在同一次调用里既启动又读输出。
   **`nohup ... &` 不加 `</dev/null` 仍然会挂** —— stdin 也没断开。完整写法：
   `cmd </dev/null > /tmp/x.log 2>&1 &`（三个方向全部重定向，缺一个就可能卡在 read）。
2. **`pkill -f '<含端口的串>'` 会杀掉自己**。执行的 shell 自己的命令行里也带着那个串
   （`pkill -f 'port 8893'`），命中后整条命令直接被砍，表现为"没有任何输出"。
   改用 `fuser -k 8893/tcp`，或先 `ss -ltnp` 拿到 pid 再 `kill <pid>`。
3. **复杂的 shell 不要塞进 `exec_command` 的单行字符串**。远端 shell 会再解析一遍，
   `curl -w '%{http_code}'` 的 `%{}`、`python -c "..."` 里的引号、`for` 里的 `$(...)`
   都会被吃掉或提前展开 —— 实测输出字面量 `%{http_code}`，或直接
   `bash: -c: line 1: syntax error near unexpected token '::'`，看起来像命令没写对，
   其实是被套了两层。超过一条管道的活儿改用 **SFTP 传脚本再执行**：

   ```python
   sftp = cli.open_sftp(); sftp.put(r"C:\...\probe.py", "/tmp/probe.py"); sftp.close()
   i, o, e = cli.exec_command("/usr/bin/python3 /tmp/probe.py", timeout=90)
   ```

   远端用**显式绝对路径解释器**（`/usr/bin/python3`、`<venv>/bin/python`），
   脚本内部把结论打印成一行，别把整段 JSON 原样打回来。

## 探活

```bash
# 端口（不需要 nc）
for p in 22 8797 8816 39061; do (timeout 2 bash -c "</dev/tcp/HOST/$p" 2>/dev/null \
  && echo "open $p") || echo "closed $p"; done

# 谁在听、pid 多少
ss -ltnp 2>/dev/null | grep -E ':(8797|8816|39061)\b'

# 服务在跑但外部连不上 ⇒ 可能只 bind 了 127.0.0.1
systemctl is-active <unit>; systemctl show -p ExecStart --value <unit>
```

**ICMP 通 ≠ 服务可用**：对端 ARP 可达、ping 通，但目标端口全 closed 就是服务没开，
别再换脚本试；从同网段另一台机器复测一遍可排除本机防火墙。

## 判断“是不是同一台机器”

两个 IP 指向同一端点时，**比响应体是否逐字节相同**，不要去比 MAC/主机名（可能查不到）：

```bash
curl -s http://A:8810/health | md5sum; curl -s http://B:8810/health | md5sum
```

实测 `192.168.23.70` 与 `10.163.149.123` 的 `/health` 完全相同 ⇒ 同一台机器双网卡。

## 读运行期真相

- **systemd 服务的环境变量在 `/proc/<pid>/environ`**：
  `tr '\0' '\n' < /proc/<pid>/environ | grep KEY`，空输出 = 跑的是脚本默认值。
- **进程死活看 `/proc/<pid>/stat`**：僵尸态是 `Z`。状态文件里写着 `running: true`
  而 pid 已是 `Z`（或不存在）时，所有后续任务会被永久判成 busy。
- 巡检看 `ss -ltnp`，**不要 `ps | grep 名字`** —— 会把自己的命令行和包装 shell 一起算进去，
  看起来像“多开了好几个实例”。

## 往 Intel 部署/修服务：改配置，不要整体覆盖

Intel 上那套（`/home/intel/zmax_550c/tools/` 等）是**Ubuntu 适配版**，不是 Windows 侧的副本：
路径、设备名、`sudo docker run --network host`、`xcoresdk_python.*.so`、20+ 个 systemd unit
都按 Linux 写。把 `D:\ZMAX\tools\` 或新 `server/` 整包盖过去，会把这 20 多个在跑的服务一起弄挂，
比现状更糟。**判据**：对端已有等价 harness（systemd unit + 本地路径适配）时，只做**配置级**修复。

配置级修复的标准手法（改环境变量，不动代码）：

```bash
sudo cp /etc/systemd/system/<unit>.service{,.bak-$(date +%Y%m%d)}
sudo sed -i 's|^Environment=ANCHOR=...$|Environment=ANCHOR=...\nEnvironment=KEY=VALUE|' \
  /etc/systemd/system/<unit>.service
sudo systemctl daemon-reload && sudo systemctl restart <unit>
systemctl show -p Environment --value <unit> | tr ' ' '\n' | grep KEY   # 确认生效
```

实测：Intel 的 8797 是 `zmax-traj-ar.service`，原来**没有** `ZMAX_ORIN_SDK_URL`，
默认连 `127.0.0.1:19061`（本机 ECS 隧道，常年不存在）⇒ `/api/tcp` 一直吐 `latest.json`
里冻了 9 天的值（`stale: true`、`age_s 781163`）。补上
`Environment=ZMAX_ORIN_SDK_URL=http://192.168.23.66:39061/status` 后才走 Orin 桥。

改配置前先找对 unit：`grep -rl '<脚本名>' /etc/systemd/system/*.service`，
不要凭服务名猜（8797 的 unit 叫 `zmax-traj-ar`，不叫 `zmax-ar`）。

**配置改对不等于数据会好**：源本身在抖时，对端照样拿不到稳定位姿。
先把源头稳定性坐实，再谈“办公室远程控制”。

## 核对“服务是不是真的都迁过去了”

“对端看起来跑了很多 zmax 服务”和“28 项标准服务都在”是两件事。三步核清：

**1. 按 `server/services.json` 的端口列，与对端 `ss -ltn` 求差集**

```bash
ss -ltn | awk 'NR>1{print $4}' | grep -oE '[0-9]+$' | sort -n -u
```

差集里还要剥掉"本来就不该在那台机器上"的端口（AOI 10082/10083 在工控机、不在 Intel）。

**2. 对差集里的脚本名逐个 `find` —— 区分"没迁"和"没起"**

```bash
for s in cam_live_stream.py agent_hub.py arm_yolo_stream.py ...; do
  f=$(find /home/intel -maxdepth 4 -name "$s" 2>/dev/null | head -1)
  [ -n "$f" ] && echo "HAVE  $s -> $f" || echo "MISS  $s"
done
```

实测 13 项"缺"里 8 项的代码已经在 `/home/intel/zmax_sync/tools/` 下，只是没有 systemd unit、
服务没起；只有 2 项是真的没代码。**结论要分两层报**："代码在但没起"≠"没迁"，
前者可以我今天启动，后者得先送代码。

**3. 启动前先确认解释器和依赖**

Intel 上的服务不跑系统 `python3`，各套着自己的 venv（`gsxpu-venv` / `venv550c` /
`train_venv` / `gs-venv`）。用错解释器会栽在 import 上：

```bash
/home/intel/gsxpu-venv/bin/python -c 'import cv2,numpy,flask; print(cv2.__version__, numpy.__version__)'
```

## 启动了 ≠ 用户能看到 —— 按 `/stats` 逐路验，不要看端口和页面

从 Windows 迁到 Intel 的服务是**另一份 fork**，不是同一份代码：
`/home/intel/zmax_sync/tools/cam_live_stream.py` 比 Windows 版旧，但**已经支持 7 路**，
起来后 `ss -ltn` 有 8793、`curl /` 回 200、`/stats` 也正常返回 —— 但两路画面是空的：

```
[arm]   等帧中… /home/ubuntu/zmax/zmax_data/ss_live/cam_rs.png 不存在
[local] /dev/video0 无法打开（USB2.0 Camera）
```

- **路径写死了 `/home/ubuntu/`**（Ubuntu 双系统的家目录），Intel 是 `/home/intel/` ⇒ 永远取不到帧。
- **`/dev/video0` 在 Intel 上没有** ⇒ 本地那路永远 off。
- 只有 `aoi_gold` 是活的，因为那一路是 ``GET 工控机 10082``，Intel 能连上产线网。

所以**判据必须是 `/stats` 里每一路的 `online` / `fps`**，不是端口在听、也不是页面能打开：

```bash
curl -s http://127.0.0.1:8793/stats    # 每路: online / fps / kb_per_frame / age_s
```

第二个坑：**同一份 fork 里的 `station.html` 可能是旧版**。实测页面标题是
「Z-MAX 旁路调试 · 实时视频流（压缩）」，里面只有 `arm` / `local` 两格，**没有 AOI 格**。
结果就是"`/stats` 说 `aoi_gold` 在线、`/snapshot/aoi_gold.jpg` 也能拿到 25KB 图，
但用户浏览器里怎么也看不到金手指"。

**报结论时必须把这两个层面分开说**：数据通了（给端点 + 字节数）≠ 页面能看（要换 html）。
只说"已启动"会让用户对着旧界面以为没生效。

## 间歇 503：先怀疑服务在重启

同一个 URL 前几分钟 200、现在 503，**先怀疑对端服务在重启**，不是这条链路坏了。

```bash
for i in 1 2 3; do curl -s -m5 -o /dev/null -w '%{http_code} ' URL; sleep 2; done
curl -s URL/health      # 看 calls / sdk / err 三个字段
```

判据：`/health` 的 **`calls` 计数器归零或大幅回退**（实测 195130 → 268 → 514）
= 进程重启过；`conn_ts` 同步刷新 = 重新建连。这期间的 503，等几秒再测，别翻代码。

**短 timeout 会把“服务慢”误报成“网络不通”**：`urllib` 用 `timeout=1.5` 时实测
`URLError: [Errno 113] No route to host`（0.52s 就放弃），放到 5s 才拿到真实的
`503`。看到 `No route to host` 而 ping 正常，先把 timeout 放大复测，再判网络。

## 整机"响应饥饿"：ping 通、端口全超时，但不是 OOM

症状：`ping` 0ms、TCP 能建连，但**所有** HTTP/SSH 都超时或空回复，`/health` 拿不到，
连 nginx 都慢到秒级。直觉是"内存打满被 OOM 杀了"，但这个结论必须先用日志证伪：

```bash
sudo journalctl -k --since "HH:MM" --no-pager | grep -iE "out of memory|oom-kill|killed process"
sudo journalctl -k --since "HH:MM" --no-pager | grep -iE "blocked for more than|hung_task"
```

**两条都空 ⇒ 不是 OOM、也不是 IO 挂死**，是用户态调度饥饿：内存贴到 free 二三百 MB 时
每次分配都要同步回收页缓存（direct reclaim），同时 load 24~40 远超核数，
进程既抢不到 CPU 也等不到干净内存。
判据组合：`load` 常年是核数的 1.6~2.8 倍 · `available` 只剩几百 MB · **swap 为 0**
（既没缓冲，也没有"换出去慢慢跑"的中间态）。

处置顺序：

1. `stop` **+ `disable`** 那几个只读旁路的重计算服务（影子推理 / 进化搜索）。
   判据是 unit 描述里写着"只观察 / 零指令 / 不回灌"之类。实测停三个一次释放 8~13G 内存、
   load 从 37 掉到 15。
2. 降完立刻复测 `available` 与 1 分钟 load，**把前后数字一起报**给用户。
3. 别急着重启机器。负载与内存回落、端点恢复毫秒级之后，重启的唯一收益只是清残留进程，
   代价是打断在跑的训练 —— 把判断依据摆给用户让他定。
4. 真要重启前确认 **`ssh.socket`** 的 enabled 状态，而不是 `ssh.service`：
   Ubuntu 上常见 `ssh.service=disabled` 但 `ssh.socket=enabled`，靠 socket 激活照样能连。
   只看 service 就报"重启后会失联"是误报。

**监控不要用 SSH 轮询**：负载高时 paramiko 每次握手都要等 banner（实测连败三次），
而同一台机器上的 HTTP 状态口 60ms 就回。优先找服务自带的 `/health`。

## 看门狗脚本的三个坑

- **基线只能打一次**：用哨兵值（`last = "__INIT__"`）而不是 `None`。
  会话为空时 `last` 不更新，`None` 会让每轮都重打基线，一次任务刷出几十条噪声通知。
- **watch pattern 有节流和生命周期上限**（同一 pattern 之间至少间隔十几秒，命中到顶后
  整条进程降级成"只在退出时通知"）。所以轮询脚本的目标是**变化通知**，不是心跳日志。
- **失败要静默到状态翻转**：连续失败只在第一次和恢复时各报一条，中间不刷。
  同时把 paramiko 的日志压掉 —— `logging.getLogger("paramiko").setLevel(logging.CRITICAL)`，
  否则每次握手失败都打印整段 traceback，把有用的那条通知淹没。

## 往锁死的对端送文件（无 SMB / 无 RDP / 无 WinRM / 无 U 盘）

对端是产线 Windows 工控机、445/135 假 open（TCP 能连、协议层超时）、
3389/5985/22 全 closed 时，**由源机当 HTTP 服务器、对端用浏览器或
`Invoke-WebRequest` 来拉** —— 这是唯一不需要在对端改配置的方向。

四步，缺一步就会“本机自测好好的、对端下不到”。

**1. 只放要送的文件，不要拿仓库根当根目录**

```bash
mkdir -p /d/ZMAX/_aoi_drop && cp AOI_README.md AOI_check.ps1 AOI_check.bat _aoi_drop/
```

`--directory` 指到仓库根会把整个 git 仓库（含 `.git`、密钥、`zmax_data`）暴露成
目录列表，任何人打开就全看得到。隔离目录还有一个好处：事后删一个目录就清干净。

**2. 绑产线网那个 IP，不要 `0.0.0.0`**

```bash
cd /d/ZMAX/_aoi_drop && python -m http.server 8891 --bind 192.168.23.100 \
  --directory "D:/ZMAX/_aoi_drop"
```

`0.0.0.0` 会让服务同时出现在 WLAN / 公网侧。绑具体 IP 等于自带一层收敛。
端口别用 8890 —— 本机常有别的 `http.server` 或服务占着；先
`Get-NetTCPConnection -LocalPort N -State Listen` 确认空闲。

**3. 防火墙按子网放行，不是 `-Profile Any` 裸放**

```powershell
if (-not (Get-NetFirewallRule -DisplayName "ZMAX-AOI-drop-8891" -ErrorAction SilentlyContinue)) {
  New-NetFirewallRule -DisplayName "ZMAX-AOI-drop-8891" -Direction Inbound `
    -LocalPort 8891 -Protocol TCP -Action Allow -RemoteAddress 192.168.23.0/24 -Profile Any
}
```

Windows 默认 Block 入站，不加规则时本机 `127.0.0.1` 通、对端连不上 ——
这个差异最容易误判成“对端防火墙挡住了”。

**4. 从第三台机器验证，不要只在本机 curl**

```bash
# SSH 到 Intel（同网段另一台），curl 源机
curl -s -m 6 -o /dev/null -w 'http=%{http_code} bytes=%{size_download}\n' \
  http://192.168.23.100:8891/AOI_check.bat
# 期望: http=200 bytes=117
```

本机自测走 loopback，**绕过防火墙规则**，证不了对端可达；同网段另一台机器
证得了。150 字节左右的小文件就能证明链路通，不必等大文件。

**交付给对端**：浏览器开 `http://<源IP>:<port>/` 点下载；对端没有顺手的浏览器时
用 PowerShell 一把拉完：

```powershell
New-Item -ItemType Directory -Force C:\AOI_check | Out-Null; cd C:\AOI_check
@("AOI_README.md","AOI_check.ps1","AOI_check.bat") | ForEach-Object {
  Invoke-WebRequest "http://192.168.23.100:8891/$_" -OutFile $_ }
ls
```

**收尾**：用户确认拿到后，停掉那个 `http.server` 进程并
`Remove-NetFirewallRule -DisplayName "ZMAX-AOI-drop-8891"`。
别留一个长期对外开放的端口 —— 它不会自己关。

**验证坑**：`curl -o /dev/null -w '%{size_download}'` 在 MSYS 下可能恒报 0，
`200 + 0 字节`看着像空响应。要确认内容就真取一次
（`curl -s URL/file | head -3`）或看响应头里的 `Content-Length`。

**方向判据**：对端能出不能进时，永远是“让对端来拉”，不要花时间在
往对端写上面 —— 推送需要 SMB/WinRM/RDP 之一，这三样恰恰是最容易被
厂商锁掉的。
