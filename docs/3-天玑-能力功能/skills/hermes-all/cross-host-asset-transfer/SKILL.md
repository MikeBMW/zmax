---
name: cross-host-asset-transfer
description: Use when 把大权重/依赖/数据推到另一台主机 (选链路·按目标 Python 抓轮子·三证验收)。
version: 1.0.0
author: Hermes Agent
license: Apache-2.0
metadata:
  hermes:
    tags: [transfer, rsync, wheels, offline, edge, network]
---

# 把大文件与依赖送到另一台主机

## When to Use
- 要把权重/数据集/轮子包推到另一台机器(边缘机、工控机、无外网主机), 而目标机 Python 版本与本机不同。
- 跨机传输很慢/反复断, 要判断该走局域网直连还是公网中转。
- 目标机 `pip install` 报 `from versions: none` 或依赖区间冲突, 要一次把依赖树搬全。

适用: 权重/数据集/轮子包要从本机到一台**边缘机或工控机**(可能无外网、Python 版本与本机不同、没有 GPU)。
目标不是"拷过去了", 而是**那台机器上真能 import / 真能前向**。

## 0. 通道没通先建通道(对端未知 / 本机无键)

搬家前先把三件事坐实: **对端是谁 / 从哪进 / 谁是真源**。跳过这三步就会把"本机没私钥"当网络故障查。

```bash
ip route | head -3                       # 先认当前网段(换环境后网段会变, 别沿用记忆里的 IP)
python3 scripts/find_peer_hermes.py      # 并发扫 22 口 + 抓 banner + 端口指纹, 不需要 nmap
curl -s http://<ip>:8793/ | head -c 200  # 服务页标题是最快的身份指纹
ls -l --time-style=+%F_%T <两边同一文件>  # 谁新谁是真源
```

- **无键不等于能口令登录**: 只带应用目录(如 `~/.hermes`)的介质/新机里根本没有 `~/.ssh` 私钥,
  出站必报 `Permission denied (publickey)`。修法 = 本机 `ssh-keygen -t ed25519 -N ''` 生成一对,
  **公钥可贴聊天、私钥不离本机**, 让对端跑一行 `mkdir -p ~/.ssh && echo '<pub>' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys`。
- **口令不跨机复用**: 云主机 / 跳板 / 边缘机各有一份口令, 拿 A 机的口令试 B 机只会白耗轮次
  (还可能触发失败锁定)。要么一次性公钥授权, 要么向用户点名要**这台机**的口令,
  用 `sshpass -p ... ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no` 并禁公钥。
- **判身份只认端口指纹, 不认单个 22 口**: 陌生机开 22 只说明"有台 Linux"; 同版本 Ubuntu
  的 SSH banner 也只能当旁证。本环境指纹: `8791 + 8793 + 8797` 同开 = Z-MAX 工位机(550A/4060),
  8793 页面标题为旁路调试实时视频流; 产线设备各走自己的专口, 不要按 22 口去猜。
- **把"同一个 agent 的大脑"当资产同步时**: 目录里 `memories/ skills/ cron/jobs.json config.yaml auth.json sessions/`
  是文本类, 可增量合并; `state.db*` 走 `sqlite3.backup()` 快照, 绝不 rsync 活库。
  先拉到 staging 目录再合并, 不要 `rsync --delete` 直接盖正在跑的 `~/.hermes`;
  合并完**不重启在跑的服务**(重启须用户点名), 让新记忆/技能在下一轮自然生效。
- **只差记忆/技能时不要搬整棵树**: 体积大头是 venv / 权重 / 会话库, 先 `du -sh */ | sort -h`
  确认要传的只是几十 MB 的文本类, 避免为一个几 MB 的改动拉 9GB。
- **记忆/技能 tar 不包含项目产物**(画布 json、配置、flows), 用户说「同步记忆」时那部分会静默分叉:
  搬完顺手比一下关键 json 的 md5(本机 `flows/` 常常是指向 `data/.../sources/canvas/` 的软链,
  要拿**真源那份**去比), 分叉就两个位置都推、各留 `.bak` 备份, 推完两侧 md5 必须相同。
- 🔴 **目标地址是 DHCP 分配时要先核身份再写**: 同一 IP 会被别的机器/换机后复用, 写脑文件到错机器 = 污染别人的 `~/.hermes`。
  三件套: `hostname` · `cut -c1-60 /proc/cmdline`(介质特有标记, 如 `casper ... persistent`) · `findmnt -no SOURCE ~/.hermes`(应指向那份镜像)。
  任一对不上就**停 rsync**, 重扫网段或问人; 不要用"上次就是这个 IP"当理由。
- 🔴 **"定时同步在跑"要看日志里的 rc, 不是 timer active**: 对端换网段后源机没有到那网段的路由, 每轮只写一行 skip 退出 0 ——
  `systemctl list-timers` 依然显示上次/下次很漂亮, 增量却一点也没过去。判据 = 用 `read_file` 读同步日志、确认里面有 `上行rc=0 下行rc=0`;
  只有 skip 行就是真没同步。双向验收固定用探针: 两侧各写一个文件, 跑一轮后**两边都该看到两个**。
- **对端只有 wifi、目标网段只有有线时不通用**: `ip -o link` 只有 `wlp*` / `lspci` 只有无线控制器 ⇒ 网线插不进去, 必须插 USB 转 RJ45 (插上才会出现 `enx*`)。
  给有线口加静态地址时**不要设默认网关**, 让原 wifi 继续当默认路由 (同步/外网不断): `ip addr add <ip>/24 dev enxXXXX && ip link set enxXXXX up`。

## 1. 先选链路, 再传

按实测速率选, 不要按"哪条现成"选:

| 链路 | 实测 | 判据 |
|---|---|---|
| 同网段直连(产线网卡/同交换机) | 3.4GB / 30s ≈ **106MB/s** | 首选, 一到位就把中转任务停掉 |
| 经云主机中转(ssh 隧道 / 公网回传) | ≈ **1.1MB/s**, 3.4GB 约 50min | 只在没有局域网时用 |

- 直连判定: 三个对端全 ping 通 **且** 原上网链路地址未变(别把默认路由抢走)。
- 中转链路普遍有对端周期性 `Connection closed by remote host`, 大文件会被拦半途; 一旦直连可用立即切换,
  否则白等一小时。
- 传之前先确认大小与目标盘剩余空间(`df -h`), 权重 3GB 级别不算小。

### 从 GitHub Release 拉大产物: 单流 curl 会被掐到 30KB/s

同一条代理链接(如 `ghfast.top` 前缀): `curl` 单流实测 **33KB/s** 且常在 90% 处 stall 到超时;
`aria2c -x8 -s8` 实测 **~1MB/s** —— 169MB 从「要 80 分钟」变成 1.5 分钟。慢的根因是**每条连接被限速**, 不是带宽。

```bash
aria2c -x8 -s8 -k1M -c --max-tries=10 --retry-wait=3 --console-log-level=warn \
  -d /tmp/rel -o app.zip "https://ghfast.top/https://github.com/<o>/<r>/releases/download/<tag>/<asset>"
sha256sum /tmp/rel/app.zip        # 与 Release API 的 assets[].digest 逐位对
```

- 🔴 **同 tag 重建过资产时必须先删旧文件再下**: 文件名不变、内容变了, `-c` 续传会把新旧字节拼在一起 ⇒
  sha256 永远对不上(而且 size 可能刚好等于新包, 看着「已下完」)。重建版发布后旧包一律先 `rm`。
- **下载放本机, 再用局域网送过去**: 目标 Windows/边缘机直连 GitHub 实测 0 B/s; 本机下完 `scp` 过 LAN
  实测 169MB / ~5s。顺序是「本机 aria2c → LAN scp」, 不是「目标机直接 curl」。
- 完成判据只有一条: `sha256sum` == `GET /repos/<o>/<r>/releases/tags/<tag>` 中该资产的 `digest`;
  文件大小对不等于内容对(半截续传也一样大)。
- 目标机是 Windows 时解压用自带的 bsdtar (`tar -xzf`), 不必找 7z。

### 方向: 让"要收的那台"主动去拉, 不要反向往里推

公司/产线网的**入站**连接会触发安全检查, 出站不会。所以搬数据时让目标机出站直连源机的公网地址:
```bash
# 目标机生成密钥; 公钥从"有源机权限的那台机器"追加进源机 authorized_keys(不用两边直连)
ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519
# 目标机主动拉: 出站, 不进站
rsync -a --partial --inplace -e "ssh -i ~/.ssh/id_ed25519" root@<src-ip>:/path/f ./
```
- **别为此架反向隧道(frp / `ssh -R`)**: 那会让源机的连接反向穿进内网, 既是安全问题又白搭一层。
  源机有公网 IP 时, 目标机出站 SSH 直连就够了 —— 先测 `timeout 8 bash -c 'cat < /dev/null > /dev/tcp/<src-ip>/22'` 再谈方案。
- 速率上限 = **源机出网带宽**, 不是链路质量。实测云主机出网 0.38MB/s(≈3Mbps), 2.2GB 需 ~95 分钟 ——
  按实测速率报 ETA, 别按"局域网的 100MB/s"承诺。
- 长传输用 `setsid nohup rsync ... < /dev/null > log 2>&1 &` 脱离会话, 否则跑它的会话一结束就断。

## 2. 依赖必须按"目标机的 Python 版本"抓

在有外网的那台机器上把**整棵依赖树**抓成轮子, 目标机只做 `--no-index` 安装:

```bash
pip download --only-binary :all: --python-version 3.12 --implementation cp --abi cp312 \
    <pkg>==<ver> -d /tmp/wheels312          # 不带 --no-deps
rsync -a /tmp/wheels312/ host:/home/x/wheels312/
ssh host 'pip install --no-index --find-links /home/x/wheels312 <pkg>'
```

三个反复咬人的错法:
- **`--no-deps`**: 只抓直接依赖, 到目标机上一轮报一个缺(pyyaml → typer → …), 每轮都要重传。
- **abi/python-version 与目标机不一致**: 轮子文件名里的 `cp311` 对不上目标机 3.12 ⇒
  `Could not find a version that satisfies X (from versions: none)`。看到 "from versions: none" 先查轮子文件名, 不是查镜像源。
- **包本身的依赖区间与源侧缓存冲突**(如 `huggingface-hub<2.0,>=1.5` vs 缓存里 2.3.0): 让同一条 `pip download`
  的 resolver 自己选, 不要手改版本号, 也不要把不兼容的那个旧轮子跟着推过去(会先被选中再报冲突)。

### 目标机可能已经有 wheel 库 —— 先找, 再决定要不要下载
- 边缘机上常留有预先铺好的轮子目录(实测 `/home/intel/sam3_wheels`(cp310-abi3 + py3-none) ·
  `sam3_wheels312`(cp312) · `whl550c`(draccus/mergedeep 等)) ⇒ 先
  `find /home/<user> -maxdepth 2 -type d -iname '*wheel*'` + `ls <dir> | grep -i <pkg>`,
  命中就直接 `pip install --no-index --find-links=<dir> --no-deps <pkg>==<ver>`, 不用回本机 `pip download` 再传。
  **`--no-index` 必须显式给**: 不给自己会去连源/DNS, 在无外网的机器上白等到超时。
  cp310-abi3 的轮子在 3.12 上可以直接用, abi 号不同也照用, 不必重下。
- **只缺一两个包时, `--no-deps` 定向补比推整棵树安全**: 目标 venv 如果是**训练环境**,
  按整棵树装会顺手把 torch/transformers 升级 ⇒ 复现性毁了。口径: 装前 `pip freeze` 存快照,
  只装缺的(`--no-deps`), 装后逐字核 `torch`/`transformers` 版本未变。
- 依赖链会**一串一串**冒(实测 `draccus` → `mergedeep` → `typing_inspect` → `mypy_extensions`):
  逐个补、逐个 `import` 验证, 别一次只报一个就停, 也别因为链长就改回抓全树。
- 端侧 torch 跑大视觉模型的性价比要**实测再下结论**: SAM3 1008px 在 Intel Arc B390 首次 **92.9s**
  (含权重搬 XPU) vs 本机 4060 热推理 **742ms**, 同图同结果(都 13 个实例) ⇒ 这类模型端侧该走
  ONNX→IR(OpenVINO); 补 venv 只用于"能跑起来同口径比对一次", 不是上线方案。

## 3. 验收三证 (少一条不算完成)

1. **逐文件校验, 不信 rsync 退出码**: 源侧给了 `MD5SUMS.txt` 就逐条对账; 被中断过的 rsync 会留下
   **大小看着正常、内容已损坏**的半截文件(实测 24MB 包 MD5 不符, 且 rsync 自己没报错)
   ⇒ 只删那一个文件重拉, 不要整批重传。没有清单时至少 `stat -c %s` 对齐字节数。
2. **import**: 目标机跑 `python -c 'import <pkg>; from <pkg> import <关键类>; print(<pkg>.__version__)'`。
3. **真跑**: 喂一份真数据跑一次, 记录耗时与输出数值(例: 参数规模 / 加载秒数 / 单次推理秒数)。
   只说"跑通了"不算证据; 目标是给出能让别人复核的数。

**清单对账本身也会骗人**(取数环节的坑, 与传输无关):
- **`tee file | head` 会静默截断 file**: `head` 读够行数就关管道, `tee` 吃 SIGPIPE 提前退出,
  落盘清单只剩前几十行 ⇒ 拿它比会报出成百上千个「缺失文件」(实测 2157 行只存了 46 行, 差点报「2113 个缺失」)。
  要预览就 `> file` 之后再 `head file`, 别在链子上接 head。
- **文件数相等 ≠ 内容对应**: 远端 `dir /s /b /a:-d <dir>` / `find <dir> -type f` **整行落盘**,
  本地 `tr -d '\r' | sed 's|.*<dir>[/\\]||' | tr '\\' '/' | sort` 归一化后与本地清单
  `comm -23 / -13` 比**名字集合**, 两侧 0/0 才算齐, 再抽 4~5 个关键文件逐位比 md5。
  别用 `grep -oE` 加多层转义去抠路径 —— 引用被吃掉时会静默数出 0。
- **软链路径的 mtime 是链接自己的**, 和目标文件不是一个时间(两侧 md5 相同却一个显示旧日期),
  拿 mtime 判新旧必错; 判新旧只认 md5/字节数。

在验收报告里把这三条都写出来, 并明写**性能结论**: 目标机若无 GPU, 同一模型可能是秒级→十秒级,
"能用"和"能实时"是两件事, 必须分开说。实测锚点: 840M 参数视觉模型在 CPU(8 线程, 640×480)上
**单次 43~64s**, 同模型在 4060 上是 0.4s 级 —— 无 GPU 目标机的结论只能是"静态/离线可用",
要实时必须换量化/NPU 后端, 别把"跑通了"说成"能上线"。

## 4. 自动补齐单元的四个静默坑 (资产"看起来已齐"代价最高)

- 🔴 **"已齐"判据必须看内容, 不能 `test -d`**: 对**空目录**也成立 ⇒ 补齐服务每轮报「资产已齐, 无需动作」,
  而目标机上那个目录是空的。判据改成 `ls <dir>/* >/dev/null` + 关键文件名/大小, 或直接 sha256 对账。
- 🔴 **systemd 单元没写 `User=` 就以 root 跑**: root 上通常没有目标机的 authorized_key ⇒ 每轮
  `Permission denied (publickey,password)`, 而同一台机上普通用户 ssh 是通的。判据 = 同一条 ssh 命令
  普通用户过、`sudo` 不过。修法 `User=<有密钥的用户>` + `Group=` + `Environment=HOME=/home/<user>`,
  **别给 root 装 key**(换机就丢)。另外把日志文件 `chown` 给该用户, 否则 `tee` 报 Permission denied。
- 🔴 **`push "$(dirname "$FILE")"` 会推整个目录**: 只想推一个权重却把整个 checkpoints 目录(实测 12.16GB/355 文件)
  全送过去。推单文件用 `rsync -a <file> host:<dir>/`, 推目录才带尾斜杠。
- 🔴 **别人(含子代理/旧工单)报「缺某权重」先自己 ls+du+sha 复核**: 按文件时间戳判断是否早已在位
  (实测被报缺的两份权重分别是一个月前/三天前就在目标机上), 误判会让你重复推 GB 级数据。
- `/health` 200 只证明**服务在**, 不证明**资产齐**(进程起来了、模型文件没到位也照样 ok) —— 两件事分开报。

## 搬到可启动介质(离线交付一台能自己起的主机)

场景: 要交付的不是"文件已在目标机", 而是一块插到**任何一台机器**就能自己开机、联网、起服务、可远程接管的介质(随身盘/Live 系统)。验收标准是"开机后没人碰它也能被接上", 不是"拷完了"。

1. **解释器可能不在应用目录里** — venv 的 python 经常是软链到用户级托管解释器(`~/.local/share/uv/python/cpython-X.Y.Z-.../bin/python3.11`)。只同步 `~/.hermes` 这类应用目录 ⇒ 软链断 ⇒ 无声起不来。先 `readlink -f <venv>/bin/python` 读出版本号, 再把整个托管解释器目录同版本 rsync 过去。
2. **ABI 在本机先验, 别留到目标机现场** — 直接拿介质里那份解释器二进制跑, 把复制过去的 site-packages 手动插到 `sys.path` 试 import 核心依赖(pydantic/openai/aiohttp/httpx), 能导入才算 ABI 对。机器不能先开机的情况也能这样验证。
3. **缺包不一定是传坏** — numpy/tiktoken 之类 import 失败先 `ls site-packages` 比对源 venv; 源本来就没装就是正常现象, 拿它下结论会去修一个不存在的 bug。
4. **网络和远程接管要预置** — 现场没人帮你敲命令: wifi 预先存成 NetworkManager keyfile(`/etc/NetworkManager/system-connections/<SSID>.nmconnection`, 600 root, 不要 pin 网卡名, 也不要把 netplan yaml 直接拷进去),
   sshd 加进 `multi-user.target.wants` 并塞入己方公钥, 主机名设成可识别名字, 配了 mDNS 就用 `<name>.local` 定位。
5. **写镜像/overlay 层的两条铁律**: ① 写前 `findmnt -no OPTIONS <mnt>` 确认是 rw —— 前置只读探针留下的 ro 挂载会让整批写入报 EROFS, 而脚本自己的 echo 看着像成功; ② 用**绝对**路径 —— `.../home/ubuntu/../etc` 归一化是 `.../home/etc`(多一层), 写完必须 `stat` 落点, 错了 `mv` 回正位并删掉误建的目录树。
6. **活库用快照拷, 不直接 rsync** — sqlite 在服务运行时被写, WAL 下直接拷会得到抱页库; 用 `sqlite3.backup()`(或 `python -c` 同 API) 落一致性快照, 拷完 `PRAGMA integrity_check` 必须 ok。
7. **开机后的接管三核**: 真正挂上的是副本而不是本地空壳目录(`findmnt -no SOURCE,FSTYPE <挂载点>`)、一条只有源数据里才有的具体内容能对上(暗号校验)、服务 unit 真在跑。

## 收尾

- 旧链路上的传输任务(中转脚本/后台 rsync)按 **PID** 停: `pgrep -af` 看清父子再 `kill -TERM <pid>`。
  `pkill -f <脚本名>` 会匹配到执行它的那条 shell 命令行(名字就在里面), 把自己一起 SIGTERM 掉
  (表现为 exit -15 且后续命令全未执行)。
- 大文件不入 git: 权重/压缩包留数据盘或目标机, 仓库里只放清单与校验和。

## 6. 部署一个子系统(代码 + unit)到另一台主机

目标不是"push 完", 而是目标机上的服务真按新代码跑。顺序固定:

1. **先摸目标机版本与路径**: `sha256sum`/`git log -1` 与本地比。目标可能是几天前的旧基线
   (整个文件都不一样 ⇒ 整文件覆盖, 别硬套 patch), 也可能是 `~/zmax` → `~/zmax_550c` 这类软链 ——
   软链存在时代码里 `expanduser("~/zmax")` 才安全, 否则改用仓库根解析 (env → 包位置 → 向上找 `src/lerobot` + `tools`)。
2. **先备份目标机原文件**: `tar czf <bak>/pre_deploy_$(date +%H%M).tgz <这些文件>`, 回滚靠它。
3. **逐文件传 + `sudo install`**: `rsync -a <file> host:/tmp/_deploy/` 再
   `sudo install -o <user> -g <user> -m 644 /tmp/_deploy/<file> <目标路径>`。
   直接 `rsync --delete` 进工作树会把属主/权限变成调用者, 还可能误删目标机独有文件。
4. **逐文件 sha256 对账** (源 vs 目标), 不信 rsync 退出码。
5. **systemd drop-in 单独装, 别用 `cp A || install B` 的 fallback 链**: 源路径写错时 fallback 会拿一个
   截断/只剩几行的临时文件把原 drop-in 覆盖掉 —— 服务照样 active, 但 env 静默回落到 base 值
   (白名单/开关全丢)。正确做法: 一次 `install -m 644 <完整 conf>` 进 drop-in 目录, 再
   `daemon-reload` + `systemctl show <unit> -p Environment | tr ' ' '\n' | grep <KEY>` **逐条核 env**, 最后 restart。
   `is-active`=active 不能证明新 env 生效: base 单元的值也让服务 active。
6. **加节点/加服务的验收**: 看运行态台账里的节点数、逐节点状态 (`实现执行` vs `直通`)、单拍耗时预算,
   以及新台账文件在不在长 —— 进程起来不算完成。
7. **部署前确认这台机没有该链路的执行消费者**: `grep -rl <输出文件> tools/ src/` + 看 `actuator_calls.log`
   是否存在/在长。否则"部署一个规划器"可能等于"开始给机器人下指令"。

### 6b. 目标机**没有 git**、只有活的代码树: 只更新"两边都有"的文件, 再证明生效

判据: `ls -d ~/zmax/.git` 不存在, 但 `~/zmax/tools`、`~/zmax_map/tools` 下有一堆进程正跑着
(边缘机常见两棵活树: 一棵状态空间/页面链, 一棵建图/进化链 ⇒ 同步要**分别对两棵**做)。

1. 备份先做: `tar czf <home>/backup/tools_<ts>.tgz -C <home> <tree1>/tools <tree2>/tools`。
2. diff 必须带 **`--existing`**: 目标树是本机的子集, 不加它时凡"只在本机存在"的文件全被列成差异
   (实测 134 条, 真正不同的只有 ~30 条) ⇒ 会误判成整树都旧、进而把子集树灌成整树。
   同时排 `__pycache__`/`*.pyc`(字节永远不同, 噪声最大)。
3. 真同步同参数 + 备份后缀:
   `rsync -a -c --existing --exclude '__pycache__' --exclude '*.pyc' --backup --suffix=.bak_pre<标签> tools/ host:<tree>/tools/`
   —— `--existing` 保证**目标机独有的文件一个不删**。
4. 验收两条: 远端逐文件 `python3 -m py_compile` 关键的(实测 4/4 OK) + **再跑一次 `-n -c --existing` 应回 0 条**。
5. 🔴 **写到盘上 ≠ 已生效**: 常驻服务内存里跑的是旧代码, 不 restart 等于白同步。默认**不自动重启**,
   报"同步完成 · 服务没动, 生效需重启 X/Y", 让用户点名。

## 7. 整站 web 迁到内网主机(nginx+php+mysql+多服务+反向隧道)

目标机在内网 NAT 后、源站有公网 IP 时, 拓扑固定为: 公网 nginx 只做 TLS 终结 + 反代到隧道,
站点与所有后端服务搬进内网机。判据是**逐条 URL 对拍**, 不是"传完了"。

- **先取"现网基线"再动手**: 迁移前把现网 URL 的状态码+字节数记下来。否则会把源站本来就有的
  故障(实测 `/index.php/z-max/` 500, 原因是插件缺文件, 两侧 `class_exists` 都 false)误判成迁移引入。
  对拍表里"两侧同为 500/404"就是合格。
- **传输没完成前不许判"页面通了"**: 半截 rsync 的 WP 会 500,
  报 `wp-settings.php` 里某个 `require` 打不开(实测缺 `wp-includes/pomo/mo.php`) ⇒ 等 `SITE_DONE` 再验。
- **安全组只开 22/80/443 时不要用 frp 7000**: 用 `ssh -N -R 127.0.0.1:<port>:127.0.0.1:<本地端口>`
  做反向隧道, 绑 127.0.0.1 不用改 `GatewayPorts`; 写成 `Restart=always` 的 unit, 加
  `ServerAliveInterval=15` + `ExitOnForwardFailure=yes`。判活看云端 `ss -tnp | grep <port>`,
  出现 CLOSE-WAIT 就是隧道断了(curl 000), 要连隧道一起纳入自愈。
- **nginx 装完必须 reload**: vhost 是在 nginx 启动之后才 install 的, 不 reload 不监听新端口
  (现象: `ss -ltn` 有 80 没有 8081, curl 000)。改完配置 `nginx -t && systemctl reload nginx`;
  reload 不生效时 `restart`。
- **403 先查目录穿越权限**: 站点放 `/home/<user>/web` 时, `www-data` 需要父目录 `o+x`
  (`chmod o+x /home/<user>`), 否则整站 403 而 error.log 只写 Permission denied。
- **php-fpm socket 名必须取自 pool 真值**: vhost 里写 `php8.3-fpm.sock`、pool 实际 listen
  `/run/php/php-fpm.sock` ⇒ fastcgi 000/502。`grep ^listen /etc/php/*/fpm/pool.d/www.conf` 后再 sed vhost。
- **WordPress 的 home/siteurl 若是 http, 内网直测会 302 到 https**: 预验时带 `-H "X-Forwarded-Proto: https"`,
  或直接在公网入口验。别把 302 当故障。
- **切流脚本自带自检+回滚**: `nginx -t` 不过或站点根 ≠200 就 `cp` 回旧配置 + reload, 旧的另存 `.bak`;
  验收后大文件(模型/视频)可留源站直出(单独的 `location ^~ /models/` root 本地), 免得为 2GB 等几小时隧道。
- **数据面也要搬**: MySQL 用同库名同账号(密码从目标应用的配置里取, 不回显), 导入后 `select count(*)` 对账;
  文件服务的归档目录(如 relay 的 archive/data)只搬脚本会得到空数据, 要单独报"接口 200 但内容空"。
