---
name: linux-host-maintenance
description: "Use when 本机自检/重启后链路核验/清缓存/DNS/网络/性能体检 (Linux 工位机)。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [linux, maintenance, dns, network, cache-cleanup, performance, self-check]
    related_skills: [disk-redline-guard, linux-wifi-troubleshooting, hermes-crash-recovery]
---

# Linux 工位机系统体检 / 清理 / 性能 (只做有证据的事)

## When to Use
- 用户说"系统自检 / 清理 DNS / 检查网络 / 清理缓存 / 清洁系统 / 提升性能"(常见于**重启后**或**关机存档之后**)。
- 用户说"**重启了 / 机器回来了 / 元气恢复 / 静静**"(开机后) ⇒ 走 §9 的链路自愈核验, 四行给最简现状; 本机没自愈起来的按 §10 恢复。
- 用户说"检查任务 / 有什么在跑 / 现在什么情况" ⇒ 走 §9h 的三处只读清点(todo · cron · 在役服务), 只回"待办为空"等于没查。
- 跑长任务前想把机器状态摸一遍(服务在不在、盘够不够、GPU 有没有空转)。
- 磁盘吃紧 → **磁盘红线部分走 skill `disk-redline-guard`**, 本文管"系统层缓存/服务/性能"。
- 用户说"**帮我装个 X / 一会开会要用 / 一会演示要用**" ⇒ 先按 §11 查"是不是早就装了"，再做**就绪核查**(外设实测 + 设备占用 + 界面状态)，别直接下安装包。

## 0. 铁律 (先立规矩再动手)
1. **保护清单先写出来**, 清理脚本里逐条核对: 训练数据盘、模型缓存根、在役仓库、数据中转目录、在役权重
   (`model.safetensors` + config + tokenizer)。删完必须复扫一遍"还在 + 无断链"。
2. **只删可再生的**(缓存/日志/转储/回收站)。备份件、镜像归档、旧数据集 → **问, 不要自己删**。
3. **指标不吹**: 拿不准的提升项就实测; 实测没差异 → **回滚**, 不留表演性设置 (实测: CPU 调频档在本机 3 组 A/B 全在噪声内)。
4. 每个动作**报数字** (前/后用量、释放量、耗时、丢包/延迟), 不许写"感觉快了"。
5. 服务启停会动到在役链路 → 长任务在跑时**只清理, 不动服务**。

## 1. 自检清单 (一次跑完, 只读)
```bash
date; uptime; uname -r; lsb_release -ds
systemctl --failed --no-pager            # 必须 0 loaded units
free -h; cat /proc/sys/vm/swappiness
df -h | grep -Ev 'tmpfs|efivarfs'
timedatectl                              # NTP synchronized: yes (负帧龄项目尤其要看)
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor; nproc
nvidia-smi --query-gpu=name,utilization.gpu,memory.used,memory.total,persistence_mode,pstate,temperature.gpu --format=csv
ps -eo pid,etime,pcpu,pmem,args --sort=-pcpu | head -15   # 谁在跑/有没有空转
for s in <在役服务名...>; do printf "%-16s %s\n" $s $(systemctl is-active $s); done
```
判读: GPU `utilization 0~3%` = 没在训练(别写成"在跑"); 桌面进程 tracker/gnome-shell 常驻是正常的。

## 1b. 「电脑卡 / 鼠标延迟 / 拖窗口要等几秒」= 先看 GPU 争用, 别先怀疑 CPU/磁盘

桌面合成(GNOME/Xorg)**自己也吃 GPU** ⇒ 一个 CUDA 常驻进程把 sm 吃到 70~80%, 整个桌面的鼠标/拖动就会一顿一顿,
而此时 `uptime` 的 load 可能只有 4(32 核)、`vmstat` 的 `wa` 是 0 ⇒ 只看 CPU/iowait 会得出"机器不忙, 不该卡"的错误结论。
```bash
nvidia-smi --query-gpu=utilization.gpu,memory.used,temperature.gpu --format=csv,noheader
nvidia-smi pmon -c 1 -s u | tail -n +3      # 按进程看 sm%: 谁在吃 + 桌面合成还剩多少 (关键)
```
实测(工位机): 状态空间引擎循环 10Hz 常驻吃 **sm 66~79%**, 桌面 `Xorg` 只剩 **3~9%** ⇒ 用户报"配置中心拖侧栏好几秒才动"。
同批还有非 GPU 的常驻大户(渲染帧服务 2Hz ≈160% CPU), 但它们不是桌面的卡因 —— GPU 那一条才是。
- **处置优先级**: ①不用时停掉那个常驻(写成一键 `pause/resume/light` 脚本, 别手敲长命令行; 恢复必须用**原参数**) ②降频率(10Hz→3Hz) ③双显卡笔记本可让**桌面走核显、CUDA 走独显**(先只读看 `xrandr --listproviders`, 换 provider 要重启 X ⇒ 属改动项, 要先说代价)。
- **报告口径**: 「谁吃 GPU / 桌面剩多少 / 停掉后 GPU 变多少」三组数字, 不写"优化了一下性能"。
- ⚠️ 别拿 `ps -eo pcpu` 的百分比当"现在正在烧"(那是生命周期均值, 见上节): GPU 只看 `pmon` 的瞬时 sm%。

## 1c. 「怎么电脑变得这么慢 / 之前也不是这么慢」⇒ 先算总账, 再定责, 最后查差量

用户问这类问题时**不是要一个自检表**, 是要「为什么现在比刚才慢」。顺序固定:

1. **总账先换算成核数**: 各进程 `/proc/<pid>/stat` 的 utime+stime 采两次求增量(别用 `ps %CPU`, 那是生命周期均值),
   求和写「合计 X% = Y 核 / N 核」。实测一次「328% = 3.3 核 / 32 核 + load 4.4」 ⇒ **机器根本没饱和**,
   此时别再拿 CPU 当解释, 往内存/GPU/单线程卡顿转 —— 报「CPU 挤满」是假诊断。
2. **把自己这条链路的进程算进账**: 排查期我自己起的 VSCode 调试宿主(GUI 在 pydevd 下能到 90%+)、
   两个 pyright 语言服务(各 ~570MB)、采样脚本、signal_store 守护 —— 这些在 `ps` 里跟业务进程长得一样。
   给用户报「谁在吃」之前先认领自己的, 否则会把自己的开销当成系统故障。
3. **差量对账**: 拿「刚重启时」的记录(load/swap/内存)跟现在逐项比, 差的那一项才是嫌疑。实测一次:
   刚重启 load 4.7 / swap **0** ⇒ 两小时后 load 6.9 / swap **3.9G** ⇒ 差在 swap, 而 swap 是**我反复重启 GUI(每次峰值 1.4~3.6GB)攒出来的**, 不是硬件。
4. **回收 swap 前先看装得下**: `awk '/MemAvailable/' /proc/meminfo` 必须 > swap 已用, 然后
   `sudo swapoff -a && sudo swapon -a` (实测 3.9G 换回内存用 15.8s, MemAvailable 18.7G→14.7G)。
   报数写「swap 已用 X G → 0」, 不写「清理了一下」。
5. **GPU 只看瞬时**: `nvidia-smi pmon -c 1 -s u`; 无 CUDA 争用时再查核显 —
   `sudo dmesg -T --since "2 hours ago" | grep -iE "i915|fence|GPU hang|reset"` 应为空(有 `Fence expiration` = 桌面停止重绘)。
6. **归属不明确时直说**: 「机器现在 3.3 核/32 核、无 GPU 故障、swap 已清零 ⇒ 剩下的卡顿不在 CPU, 需要你指一个具体动作(拖窗/切页/点按钮)我再拆」。
   比拢一堆自检项有用得多。

⚠️ **别拿后台窗口的 CPU 当降载证据**: GUI(Qt/pyqtgraph)在后台时**根本不重绘**, 同一进程后台 22%、前台 120%。
做过优化要给降幅, 必须在**同一可见页面**下前后各采一次; 拿不到就明说拿不到, 不给假数字。

## 1d. load 很高但 CPU 大量空闲 ⇒ 账不在算力, 在「半死连接 + fork churn」

**先看空闲率再定责**: `uptime` 给 load 14, 而 `top` 的 `%Cpu(s)` 显示 `71~82 id` ⇒ 没有任何进程在算, 问题是
**调度/进程churn**, 此时去查 GPU、磁盘、调频全是白查。按序取四个数(全只读):
```bash
uptime; grep procs_running /proc/stat                 # load 与"同时可运行"的进程数
awk '/^processes/{print $2}' /proc/stat              # 隔 3s 两次差 = 进程/线程创建速率
awk '/^ctxt/{print $2}' /proc/stat                   # 隔 3s 两次差 = 上下文切换速率
ss -tan | grep -E ":<端口>" | grep CLOSE-WAIT        # 服务端半关闭连接: 客户端已断, 处理函数没收摊
ps -eo pid,ppid,pcpu,stat,etime,args --no-headers | awk '$2==<服务pid>'   # 它的 fork 子进程谁还在烧
```
实测形态(AR 服务 8797): load **14.4** / CPU 空闲 **71%** / 创建 **452 次每秒** / 切 **88k 每秒** /
两条 `CLOSE-WAIT` 各对应一个 fork 子进程、**各 38% CPU 空转 7 分钟**。
- 判读: fork-per-connection 服务里, **每条 CLOSE-WAIT 就是一个还没收摊的子进程**; 它同时占一个 `max_children`
  名额 ⇒ 名额满则新连接被拒/排队, 表象是「打开页面白屏好久」, 而不是「机器算不动」。
- 处置顺序: ①`kill <僵尸子进程 pid>`(只断已经死掉的流, 不碰在役连接) ②改服务端让它有收摊条件
  (硬上限时长 + 每块 flush + `finally close_connection`, 配方在 `low-latency-camera-streaming`)
  ③复核 `CLOSE-WAIT` 计数归 0 + load 在 5 分钟内回落。
- **报告口径**: 报 "load 14.4 → 12.5 / CLOSE-WAIT 2 → 0 / procs_running 67 → 2 / tcp_ar 260% → 个位数",
  不写「优化了一下性能」。

## 1e. 「界面卡 / 滚轮没反应 / 点了没反应」但页面本身是好的 ⇒ py-spy 抓 GUI 主线程栈

先分清楚**是页面还是宿主**: 在浏览器/页面里验一遍功能(滚轮就 `document.documentElement.scrollHeight` vs
`innerHeight`, 再往 `view.focusProxy()` 注 `QWheelEvent` 读 `scrollY`) —— 实测滚轮 0→60 有效 ⇒ 代码没问题,
卡在**宿主 GUI 主线程**。此时 `top` 看到 GUI 进程 100% CPU、`ps %CPU` 又是均值 ⇒ 不要靠猜, 直接抓栈:
```bash
sudo <venv>/bin/py-spy dump --pid $(pgrep -f 'studio[.]py' | head -1) 2>&1 | head -40
```
实测栈形: `main → _step → _realize_pending → _realize_page → <某页>.__init__ → subprocess.run(ssh …)`
⇒ **惰性建页机制把同步子进程放在了页构造函数里**: 后台建页泵每 0.8s 真建一个页, 建到那个页就整窗卡
2s(子进程 timeout), 期间点击/滚轮/重绘事件全丢 —— 用户看到的是「卡住了/滚轮没反应」, 而不是「开慢了」。
- **定式**: Qt 页面构造函数里的**任何同步 `subprocess.run` / 网络探测 / ssh 预连**都必须挤到后台线程
  (`threading.Thread(target=…, daemon=True).start()`), 并给子进程加 `ConnectTimeout`, 别让 timeout 决定帧时间。
- **排查顺序**: ①先证页面功能本身可行(页面内自证) ②`py-spy dump` 看主线程是不是在 `_wait/communicate`
  ③再去改动 —— 不抓栈去改事件处理/重写 UI 都是改错地方。
- 这类修复改的是 `.py` ⇒ **要重启 GUI 才生效**, 当场能给的只是“下次启动生效”, 如实说。

## 2. DNS "清理"
```bash
resolvectl status | grep -E "Current DNS|DNS Servers"      # 先看解析链 (127.0.0.53 → 上游)
sudo resolvectl statistics | head                          # 清前 cache size (查询监控 socket 需 root; 不加 sudo 报 Permission denied)
sudo resolvectl flush-caches
for h in www.baidu.com open.feishu.cn github.com registry.npmmirror.com hf-mirror.com pypi.org; do
  printf "%-24s " $h; ( /usr/bin/time -f "%es" getent hosts $h >/dev/null ) 2>&1 | tail -1; done
```
口径: 用**逐域解析耗时的清前/清后对照**当证据 (实测 0.02~0.17s → 0.00~0.02s; 复跑: 冷 4~31ms / 热 2~21ms,
清掉的都是长尾域 `hf-mirror` 538ms、`pypi` 177ms)。
- **计时别包成 shell 函数再用 `$( )` 取值**: 调用点写成 `probe >/dev/null` 时重定向作用于**整个函数** ⇒ 命令替换拿到空串,
  每个域都打印成"失败", 看着像全网 DNS 挂了。要函数化就在**函数内部**用 `date +%s%N` 前后差算毫秒再 echo
  (分辨率也比 `/usr/bin/time -f %e` 的 0.01s 好用)。
- **重启后 (<10min) 缓存本就接近冷态** ⇒ 清 DNS 的真实收益只剩长尾项, 如实写"本轮无整体加速, 只清掉两条长尾",
  别把重启后的新气象记成清理收益。
复跑(2026-09-28, 重启后 ~15min 清): cache size 18 → 清前 hf-mirror **1294ms** / dataworld.world **1163ms** /
npmmirror 173ms / github 170ms / open.feishu.cn 110ms / baidu 32ms / pypi 10ms ⇒ flush 后冷解析
hf-mirror 11ms · dataworld 13ms · github 19ms · feishu 35ms · pypi 5ms, 复跑热 4~17ms。
同一时刻现场连通: 工控机 0.62ms · Orin 0.16ms · 产线口(无网关) 0.04ms, 全 0% 丢包。
⇒ 口径照旧: **只记“清掉两条长尾”, 不声称整体加速** (pypi/baidu 清前就只有 10~32ms)。
快栈: 一行出全部数字的脚本按本机实际写 /tmp/*.sh 再跑 (巨型内联命令行会被 Hermes 硬线拦, 不是命令本身的问题)。
局域网设备通常**没有 PTR**(`getent hosts 192.168.x.x` 空 = 正常, 不是故障`)。

**量远端带宽别另起一个下载去测**: `pip download <大包>` 是**整包**下载(实测为了测速把 860MB 拉到 `/tmp/x`,
还跟正在跑的真安装抢带宽和锁, 两边都变慢); 而“查镜像页/取少量字节”会因为 404 页只有 2~15KB 得出荒谬的 48KB/s。
定式: ①速率直接读**正在跑的那个任务的临时文件增长**: `lsof -p <pip_pid> | grep '\.whl'` 或
`sudo find /tmp -name '*.whl' -newermt '-30 min'`, 隔 20s 两次 `stat -c %s` 算 `KB/s`, 顺手给出 `(总大小-已下)/速率` 的 ETA;
②要单独测就用**真实存在的 URL + `curl -r 0-8000000`**(先 `grep` 目录页确认真文件名), 且与在跑的任务**不要同时**做;
③镜像站先看它到底有没有那个文件(列目录 + 校验体积), 只看 `http_code=200` 会把目录页当成可下载源。

## 3. 网络连接检查 (一定要含"产线设备可达性")
```bash
ip -br a; ip route
GW=$(ip route | awk '/default/{print $3; exit}'); ping -c3 -W2 $GW        # 网关丢包/延迟
ping -c3 -W2 <局域网 DNS IP>
for t in 223.5.5.5 1.1.1.1; do ping -c3 -W2 $t | tail -1; done           # 公网
ping -c2 -W2 <工控机IP>; ping -c2 -W2 <Orin/设备IP>                       # 现场设备
iw dev <wlan> link | grep -E "SSID|signal|bitrate|freq"                   # WiFi 强度/协商速率
ss -s | head -4
```
真值参考(2026-09-24 工位机): 网关 3ms · 局域网 DNS 1.7ms · 公网 14.8/1.7ms · 工控机 0.9ms ·
WiFi -42dBm/573Mbit/s = 满速档。含 5GHz HE-MCS11/NSS2 才算"好"。
复跑(2026-09-27, 双活: 办公 WiFi + 产线口 192.168.23.50/24 无网关): 网关 2.27ms · 集团 DNS 2.38/2.46ms ·
223.5.5.5 14.9ms / 1.1.1.1 2.6ms · Orin 0.26ms · 工控机 1.10ms, 全 0% 丢包。
判读: WiFi 信号掉了(-42→-59dBm)但 **tx 协商速率没掉(573Mbit/s)+ 0 丢包 ⇒ 不用处理**, 只记数字别当故障报。

## 4. 缓存清理矩阵 (可再生 → 直接删; 曾实测释放)
| 目标 | 命令 | 实测 |
|---|---|---|
| journal | `journalctl --vacuum-size=200M` | ~1.1G |
| 轮转日志 | `rm /var/log/{syslog.1,kern.log.1} /var/log/*.gz` + installer 目录 | ~126M |
| apt | `apt-get clean && apt-get autoclean` | ~135M |
| 转储 | `rm -rf /var/crash/*` | ~7M |
| pip/uv | `rm -rf ~/.cache/pip/* ~/.cache/uv/*` | ~438M |
| 桌面/GL | thumbnails / tracker3 / mesa_shader_cache / gnome-desktop-thumbnailer | ~176M |
| IM 客户端 | `~/.cache/<客户端>` (先确认客户端**没在运行**) | 929M |
| snap 应用 | `~/snap/{firefox,snap-store,chromium,thunderbird}/common/.cache/*` | ~183M |
| 回收站 | `~/.local/share/Trash/{files,info}/*` — **先列文件名再删** | 546M |
| HF 模型缓存 | 只删**零引用**格式导出, 见 §5 | **4.02G** |

总量口径: 上表一轮实测 **7.18GB** (274G→267G)。清理脚本写成 `/tmp/*.sh` 文件再跑 (别塞内联长命令),
并落**台账 JSON**(每项前/后 MB + 总量) 到项目 `reports/`。

## 4b. 用户说「这个路径怎么那么多图片, 没用的删掉, 有用的整理分类」⇒ 先分「散图」与「数据集」

这类诉求听着像清垃圾, 实际九成是**把采集/训练帧当成了杂图**。顺序固定, 别一上来 walk 全盘:

1. **先浅层盘点**: 全盘统计会把训练帧算进“那么多图片”(实测 `~/` 下 39.2 万张 / 30.4 GB, 99.9% 是数据集)。
   口径: `depth<=2` 且排除 `zmax_data external snap .local .config .cache node_modules gui-venv* toolchains`,
   按目录聚合「张数 + MB」; 另单列数据集目录的 `du -sh`。
2. **能不能删只看两条硬判据**, 任一成立 ⇒ 只出清单让用户点头: ① 被代码/配置/glob 引用
   (`grep -rl --include=*.py --include=*.sh --include=*.json <目录名>`，别漏 glob 消费如 `--parts 'X_part*'`);
   ② 在役在写(视觉安全监视帧这类正被常驻进程追加)。每条清单带一句「删了影响什么 / 能不能重建」。
3. **散图一律移不删**: 建 `~/图片库/{01_设备与现场照片, 02_界面与产品截图, 03_架构与设计图,
   04_验收证据, 05_归档_待确认}`, 文件名改成能自解释的(`绿框修复_前/后`, `工艺卡_九步卡片_v3`)。
   移前查重(同名/同 md5 是否已在 `archive/`、`reports/`); **每个动作记 `~/图片库/_清理记录_<日期>.txt`**
   (动作|原路径|目标|字节) —— 用户回问「我的图呢」时直接给这份台账。
4. **只删能自证是垃圾的**: 被新版取代的旧截图 · `~/.trash_*` · 自己调试的截图(`~/.hermes/cache/scratch`) ·
   App 可再生缓存(微信 `xwechat_files/<id>/cache/`, 删完自重建、不必重登)。
   ⚠️ 聊天记录/文档一个不碰: `xwechat_files/*/msg/`、`db_storage/`、`Documents/` 下的 pdf/pptx/docx。
   验收类证据图(前后对照那种)不要删, 挪进 `04_验收证据/` —— 它同时是之后被追问时的唯一凭据。
5. **归档目录先确认被 git 忽略** (`git check-ignore -v <dir>`): 未忽略就先补 ignore 再往里放大图/Word,
   否则下一轮提交把大件带进库。
6. **验收给数字**: 家目录浅层图片张数(前→后) · 释放 MB · `~/图片库` 逐类文件数 · 盘 used/total,
   并把「数据集清单(大小 + 一句删了影响什么)」单独一段。**禁止把 30G 数据集说成“已清理”**。
7. **用户说「没有这个文件夹」⇒ 多半同类目有两份路径**: 先并列打印候选(`ls -ld ~/<类目>` 与
   `ls -ld ~/<repo>/<类目>`; 本项目家目录 `~/zmax_data` 与真源 `~/zmax/zmax_data` 并存), 再
   `ln -sfn <真源> <另一位置>/<类目>` + `DISPLAY=:0 xdg-open <dir>` 在他屏上开个定位窗口。
   只把绝对路径再念一遍 = 他再问一次。
8. **删测试占位文件时顺手清应用锁文件**: LibreOffice 留下的 `.~lock.<文件名>#` 看着像文件还在,
   也可能挡后续写入 ⇒ 先关自己开的那个窗口(`wmctrl -i -c <winid>`, 别动用户自己开的文档窗), 再 `rm -f '.~lock.*#'`。

## 5. HF 缓存瘦身 (最大那一笔, 也能最危险)
先分形态再动手: `du -sh <模型目录>/blobs <模型目录>/snapshots` + 逐个 `du -Lh` 列 snapshot 里的符号链接。
- 本机代码 `grep -rn "onnx" --include=*.py tools/ .hermes/scripts` **零加载引用** ⇒ `onnx/*` 导出可删
  (实测 SmolVLM2-500M 的 12 个 onnx 变体 4.02GB, 而运行时只吃 `model.safetensors` 2.03GB)。
- 删法两条: ①先删 snapshot 里的 onnx 符号链接 ②再删"已无任何 snapshot 引用"的 blob → **不留断链**
  (扫 `find <目录> -xtype l` 应为空)。脚本: `scripts/hf_prune_onnx.py <模型目录> [--dry]`。
- 删后必须核对 `model.safetensors`/config/tokenizer 仍在且可解析; 记下重下命令
  `hf download <repo_id> --include 'onnx/*'`。**.incomplete 残留**永远可以直接删。

## 6. 性能: 先测, 再决定, 没收益就回滚
**协议**(照做, 否则得出的都是噪声):
1. 交错 A/B (A,B,A,B…≥3 轮), 每轮多次取中位数 —— 不要"先全 A 后全 B"。
2. **负载要选对**: 带宽瓶颈型 (大矩阵 matmul) 对调频档不敏感; 频率敏感型要用**缓存驻留**的计算密集负载。
3. 同一次会话里至少换 2 种负载; 差异落在噪声内 ⇒ 如实写"无可测影响"。

实测(2026-09-24 工位机, powersave vs performance): 2048³ 带宽型 0.90× · 2048³ 8 线程 1.013× ·
384³ 缓存驻留 0.997× ⇒ **CPU 调频档无收益 → governor/电源档全部回滚**(驱动 intel_pstate, EPP 本就偏性能档)。

**真正落地/确认过、能拿数字说话的 4 项** (2026-09-26 复跑全部确认在位):
1. GPU `sudo nvidia-smi -pm 1` → persistence_mode=Enabled (反复起停 CUDA 进程时省驱动重初始化)。实测 Disabled→Enabled 一步生效。
2. 关掉桌面索引器: `systemctl --user mask --now tracker-miner-fs-3.service`(+`tracker3 daemon -k`);
   恢复 `systemctl --user unmask --now tracker-miner-fs-3.service`。实测 → masked/inactive。
3. `fstrim.timer` enabled+active (NVMe TRIM); 未开就 `systemctl enable --now fstrim.timer`。实测本轮 `fstrim -v /` = **105.3 GiB trimmed**。
4. journal 封顶 + 缓存清理 = 降后台 I/O 与写放大。实测 journal **438MB→151MB**。
**2026-09-26 一轮清理实测 (脚本 /tmp/sys_clean_full.sh, 台账 reports/sys_cleanup_*.json)**: 合计 **835MB**
(apt 列表 271 + journal 287 + uv 254 + pip 11 + 日志轮转 5 + misc 7); DNS flush 后冷解析 0.00~0.03s、热解析 5/5=0.00s;
网络旋钮(bbr/fq/rmem32M/ssai=0/fastopen3)全部在效; 远端单流 4.27/4.49/5.36MB/s(中位 4.49, 与基线 4.30 同噪声带 → 不重复声明增益)。
新增 A/B 反例记录: **`tcp_tw_reuse` 关掉会慢 3.7%(3/3 轮), 但 1 vs 出厂 2 无差异 → 保持出厂不动** (见 `linux-network-perf-boot`)。
**如实结论**: 系统旋钮给不出"魔法加速"; 算力提升要走 GPU/训练口径 (batch、像素进 RAM、BLAS 后端)。
**网络旋钮单独成技能**: 开机自动优化网络性能(交错 A/B 实证 + systemd unit + 台账) → 见 `linux-network-perf-boot`。

## 7. 交付格式 (用户会拿它当结果看)
- 报告落项目 `reports/sys_maintenance_<日期>.md`: ①自检表 ②DNS/网络实测数字 ③清理明细表(每项 MB + 合计)
  ④性能(测了什么、结论、回滚了什么) ⑤保护清单复核 ⑥遗留待决项(备份件这类要人点头的)。
- 终端回复用纯文本分行, 数字在前, 结论一句话; 不写"已优化"这种没有数字的句子。

## 进度/占用口径：`ps %CPU` 是**生命周期均值**，不是现状
实测 `ps -eo pcpu` 报 100% 的推流服务，同一 PID 用 1 秒差分采样只有 **~45%**
（该值 = 累计 CPU 时间 ÷ 存活时长；跑了 9 小时的服务会把历史尖峰一直背在身上）。
⇒ 报"某进程吃满一个核"之前**必须做一次差分采样**（读 `/proc/<pid>/task/*/stat` 的 utime+stime，隔 1s 再读），
顺便就能定位是哪个线程在烧（`wchan` 能看出是 socket 轮询还是 nanosleep）；只看 `ps` 会把"9 小时均值"当"当前负载"汇报成夸大数字。

## 磁盘大象：先问再动，并且别让用户以为能腾出几十G
本机 285G 已用里真正的头是**训练缓存**，不是系统缓存：`/home/ubuntu/stable-wm-cache` ≈ **151G**
（datasets 137G + checkpoints 14G），其中单个 `datasets/cube_single_expert.h5` 就 **95G**。
它被 `INTACT-JEPA/config/train/*.yaml` 引用 ⇒ **属在用数据**，只能列清单问用户，不能自己删。
而系统层缓存（journal/apt/转储/日志轮转/用户缓存）一轮实测只能清出 **~280MB** ——
用户说"清理系统"时先把这句说清楚，别让对方以为能腾出几十G；真正的空间决策要指向大文件清单 + 用户点头。
**找大象的固定顺序**(别一上来 `du /`, 会挂): `df -h /` 看缺口 → 一级目录逐个加超时扫
`for d in /home /var /opt /usr /snap /root /srv; do timeout 90 sudo du -sh $d; done | sort -rh` →
对最大的那几个 `du -sh <dir>/* | sort -rh | head` 逐层下钻(实测 4 次下钻即定位到单个 95G 文件)。
每层都**同时查引用**: `grep -rn "<目录名>" --include=*.yaml --include=*.py <训练仓库>` ——
被训练配置引用的数据集属"在用", 只能列清单问用户, 绝不能自己删。

## 8. 关机前存档 / 交接 (用户说"保存数据, 小版本迭代, 准备关机")

**先跑一键判定**: `bash tools/preflight_shutdown.sh` —— 只读, 出 🟢「可以下电」/🔴 列出红项
(判据: 臂 idle + 无真动授权(读 `ctl_auth.json` 的 `until`) + 无采集/训练在写 + `~` 顶层只剩 zmax + 仓库干净 + 资源正常 + 关键服务/端口)。
红项先处理再往下走。

**绿灯 ≠ 全知 —— 报告里必须补的三句**:
- **「臂 idle」可能是个空判据**: 它读的是位姿真值的**新鲜度**; 产线网卡不在位 / 控制器不可达时真值早就过期,
  这条只能写"真值帧龄 N 分钟, 臂状态**不可核实**, 最后已知位姿 (x,y,z)" —— **不许写"臂 idle"**。
  真正支撑"下电无风险"的是: 无授权 + 无下发 + 真动链路未通(位姿真值停更恰恰是链路不通的副产品)。
- **控制器 crash-loop 的容器在绿灯里只占一行 ✅**(采样器/SDK 代理连不上控制器时一直 `Restarting`) ⇒
  要写清"上电插回网卡会自愈", 否则下轮被当成新故障重新排查。
- **NTP 回拨 8h 仍在时**, 真值 `t` 字段与宿主时间不一致是已知现象, 别在交接里写成"时钟异常"。

**「准备关机」≠ 授权 `poweroff`**: 绿灯后**问一句**再执行 —— 远端开不回来(得现场按电源键), 关之前确认一下成本极低。

**顺序固定跑, 每步留证据**:

1. **停 / 确认无在跑任务** (别在训练中途关机):
   `pgrep -af 'train|joint_train|annotate|yolo_annot'` 应为空; `nvidia-smi --query-gpu=utilization.gpu,memory.used`
   应 <10% 且显存 <1G (实测空闲 = 9% / 464MiB)。有活先停干净 (: 如 L5 编排 `--status` 确认终态再 pkill)。
2. **产物归集 (小文件入库, 权重只留清单)** —— 把运行产物快照到 `~/zmax_data/<环>/artifacts_<日期>/`:
   ⚠️ **权重文件不能直接拷** (单文件 1.29GB): 只生成 `WEIGHTS_MANIFEST.txt` =
   `md5sum + stat -c%s + 路径` 逐行; 小文件 (summary.json / *.jsonl / *.log / 配置 yaml) 才真拷。
   这样"权重在哪、哪个版本、多大"可追溯, 库里不涨一个字节。
   **本机当场产生的证据** (控制台截图/掩膜图/结果 json/运行日志/报告 json) 统一进 `artifacts_<日期>/evidence/`;
   **大件** (回合 npz/mp4、训练产物) 留在 `reports/` 与 `stable-wm-cache/`, 只在留档表格里登记路径 ——
   别为了"归档"把大件拷两份。
3. **状态文件一起备份**: 编排的 `state.json` (含终态/缺口/每阶段 ok) → 快照目录。
4. **小版本迭代**: 写一份变更说明文件 → `tools/bump_version.py --to <X.Y.Z> --from <当前版本> --summary-file <f>`
   (它会改 studio.py 品牌位+changelog / update_checker / version_sync / docs_sync / integrity_check / VERSION.md 历史行;
   **`--from` 显式给** —— 自动探测会探到 changelog 里的历史老号)。
   ⚠️ **判据是它自己打印的 `旧命中 N → 新命中 M`: 任一处 N=0 就是"一个都没改到"** —— 记法/锚点对不上时
   它**静默不报错, 看着像成功**(如品牌位已改成双 v `vv5.16.35` 而工具还在按单 v 拼死串) ⇒
   先把工具的匹配改成"**认版本号不认记法**"的正则(`v{1,2}<ver>`、从 `QLabel("Z-MAX …")` 取当前号)再跑;
   改完逐文件回读 `grep -c <新串>` ≥1, 最后 `tools/ci/integrity_check.py` 要报"五处一致"。
   五处完整清单 + 文件间记法差异 + `VERSION.md` 历史行规范: 见 `pyqt5-distribution` 的 Version Bump Checklist。
4b. **归档本轮产物** (本仓既有约定: 照上一版 `tools/archive_release_<x_y_z>.sh` 抄结构):
   `bash tools/archive_release_<x_y_z>.sh` → `~/zmax/zmax_data/release_<ver>_<YYYYMMDD>/`, 分区固定
   `{tools,gui,src,config,canvas,docs,evidence,reports}`, 末尾出 `MANIFEST.md` + `sha256sums.txt`。
   **“保存数据”不等于“提交代码”**: 归档必须带**生成物真源**(本轮产出的 `config/{mcd,tasks,orders,ss_task_binding.json,calib}` 这类)
   + **画布真源**(`flows/state_space_obs.json`) **及其 `_archive/` 里那份改动前备份**(回滚面) + 用户要加载的工程文件(.zmaxproj)
   + 实测证据。权重/大件不进归档, 只留清单(见本节步骤 2)。
   ⚠️ `reports/` 被 `.gitignore` 排除 ⇒ 证据文件**只存在于归档里**, 别以为 push 过就留档了。
   `git add reports/...` 会直接报 `The following paths are ignored` 并 exit 1 ⇒ 关机交接写进 reports/ 就**别试提交**,
   入仓的那份放 `docs/notes/` (见步骤 7)。
5. **提交纪律**: `git add <显式列文件>`, **默认别用 `git add -A`** (会吸进运行态 churn + 别人的未完成改动)。
   要用 `-A` 得先**三证**: `git status --short` 只剩本轮自己的改动 + 双闸全绿(`repo_guard.py --staged` /
   `secret_scan.py`) + `.gitignore` 已封 `reports/ outputs/ 权重/交付件`。
   暂存后必看 `git diff --cached --stat`, 并对每个文件核大小 (最大应 <1MB; 出现 .pt/.safetensors/视频 → 漏加了 ignore, 先修 .gitignore)。
6. **push + tag**: `git commit` → `git tag vv<X.Y.Z>` (**每版新 tag, 已发布过的 tag 不许移动**) →
   `git push origin <分支>` + `git push origin <tag>` (tag 触发云端 CI 出包, 与本地关机无关, 可以放心打)。
6b. **tag 之后复核"CI 真跑起来了"** —— 本地没装 gh 也能查(公开仓库只读 REST):
   `curl -s 'https://api.github.com/repos/<owner>/<repo>/actions/runs?per_page=3'` 交给 `python3 -c` 打印
   `name/head_branch/status/conclusion`; 刚推的 tag 应出现 `in_progress`, 上一版应是 `completed/success`。
   判据是这条 run 的存在与结论 —— 写"已发布"前面必须看过它。
   ⚠️ **`gh` 本机没装** (2026-10-10 实测 `gh: command not found`) ⇒ 只能用 REST。库是**公开**的,
   **匿名 curl 就能查** (实测 200); 需要 token 时从 `~/.git-credentials` (`credential.helper=store`) 取。
   ⚠️ **别传空的 `Authorization: Bearer `** —— 会从 200 变 `{"message":"Bad credentials"}`, 看着像仓库私有/权限没了。
7. **写交接/留档** (两份都要, 都在库里):
   · `reports/关机交接_<日期>.md` — ①关机前状态 (终态/缺口/产物路径/GPU 空闲) ②**开机后需手动恢复的**
     (自启单元里没有的手工进程 —— 如取流服务完整命令行; 远端取流/相机/工控机接口) ③待办优先级 ④本轮代码改动清单。
   · **五节留档** — 放 `docs/notes/<YYYY-MM-DD>_handoff[_晚].md` (**本仓真实约定**, 可用
     `git log --diff-filter=A --name-only --pretty=%h -- 'docs/*handoff*'` 自查; 文档里写的 `docs/关机前状态留档_<日期>.md`
     是旧写法, 仓里一份都没有)。五节(**照上一版抄结构**): ①本轮做完的(每条带实证路径)
     ②没做完的(下轮第一件) ③数据清单(表格: 位置/内容, 大件在此登记) ④环境/机器状态(关机前核过的数字:
     磁盘/GPU/单元数/端口/时钟) ⑤**下轮启动顺序**(可直接照抄的 bash 块)。只写"做了什么+根因+证据在哪",
     不复述过程 —— 第④⑤节才是下轮"开机就知道干嘛"的原因。
   **重启后按 §9 逐项核验**；手工进程没自己起来时先读 §10（守护早退），再查服务本身。
8. **收尾核对**: `sync` → `df -h` → `systemctl --failed`(应 0) → `git status --short` (应 0 待推) → `git log --oneline -1`。
9. **清空转进程, 但不碰 GUI**: 起过却没输入的循环进程(外设缺/流断, 如相机不在位时仍 `--loop` 的检测循环)
   要 `kill`, 并在留档"机器状态"里写"已停 pid X"。
   **控制台 GUI 的规矩是「不许反复重启」, 不是「不许关」**: 收尾时把控制台 graceful 退出(`kill -TERM <pid>`)是正规动作 ——
   它是**用户级 systemd 单元**(`~/.config/systemd/user/zmax-studio.service`), 下次登录自起, 不必手工重开;
   要禁的是"用户还在看的时候替他把 GUI 重启一遍"。关完复核 `pgrep -af 'studio\.py'` 为空。

## 8b. 停守护 ≠ 停住: 先查 keepalive, 否则「已停」一分钟内被推翻

本机的常驻守护**几乎都有看护在拉**: `crontab -l` 里的 `* * * * *` / `*/5 * * * *` 保活行(tunnel_keepalive ·
cam_stream_guard · ar_server_guard · vl_safety_keepalive · l2_daemon_keepalive)+ `@reboot` 行 + 系统级/用户级 systemd 单元。
⇒ **停之前先列看护**: `crontab -l | grep -vE '^\s*#'` 过滤 `keepalive|guard|sentinel|tunnel`; 再
`systemctl list-units --state=running 'zmax*'` 与 `systemctl --user list-units 'zmax*'`。
- 停法固定: **先停 keepalive/包装 shell, 再停被守护的进程**; 只停后者等于没停 —— 实测 15 个守护停掉后 ~1 分钟内被拉回 9 个,
  且新实例正处在**加载模型**阶段(CPU 28~37%, 白烧)。
- **报告口径**: 不写"守护已全部停止"。写「停了什么 / 什么会被看护拉回 / 拉回对关机有无风险」——
  这些守护写的是**追加型** jsonl/日志(断电最多丢最后一行), 且开机由 `@reboot`+cron 自动恢复 ⇒ 结论仍可是「可安全下电」。
- **逐条复核并报残留**: TERM 后仍活着的单独列出(实测有一个推送守候 TERM 连 KILL 之后仍存活、状态 `Ss`、0% CPU、
  不持写句柄) —— 「停不掉的」和「停掉的」都要写, 否则用户以为全场静止。
- **有意不停的一类**: 对外/隧道单元(`zmax-ecs-*` · `zmax-tunnel-*`)—— 提前停只会让站点早一点失联, 与本机写盘无关, 交给 systemd 收尾。
- 可直接用: `scripts/stop_writers_safe.sh [--dry] [--pat '<正则>']`(排除调用它的这条 shell, 先停 keepalive 再停其余, 末尾逐条复核)。

## 8c. “可以下电”的证据集 (四件, 缺一件就不说这句话)

1. **库无待写**: `PRAGMA wal_checkpoint(TRUNCATE)` 回 `(0,-1,-1)`(无 WAL 可并) + `PRAGMA quick_check` = ok + 无 `-wal/-shm` 残留。
2. **状态文件无半写**: 逐个 `json.load` 关键状态(实时数据/总线/任务绑定/报告) + 逐条 jsonl **末行可解析**(行数与字节数一起报)。
3. **端口与进程层**: 数据面端口已释放(`ss -ltnp | grep <端口>` 空) + 剩余 running 单元逐个列出并带**为什么留着**。
4. **产物层**: `git status --short` = 0 · 归档目录在且 MANIFEST 计数对得上(见 4b) · `sync` 已跑。
把这份快照写成 `evidence/shutdown_prep_<ts>.md` 落进归档目录 —— 给用户的回复仍是"停了什么/核过哪些数/还剩什么"三行, 快照是底账。

**顺手体检要算增速, 不只看 `df` 百分比**: 有的 tap 是 10Hz 无轮转 jsonl(实测 306MB/129k 行 ≈ **2.0GB/天**) ——
`df` 87%/余 51G 看着安全, 实际约 25 天吃满 ⇒ 报告给「MB/千行 · GB/天 · 剩余天数」并建议按天轮转/降采样,
比只贴一个百分比有用得多。

**新增生成物顺手加 .gitignore**: 每次训练动态生成的 `config_*_lora_*.yaml`、
`reports/joint_train_*/` (内含 .pt) 这类必须显式 ignore, 否则下次 `add` 就会把权重拖进库。
临时脚本写在 `/tmp/*.sh` 再跑, 别塞巨型内联命令。

## 9. 重启后核验：链路自愈了没有（用户说「重启了 / 回来了 / 元气恢复」先跑这个）

> 跳板/公网入口断了怎么自愈（22022 是**哪一端**用 -R 建的 · 端口能连但 SSH 不握手 · unit active 但转发已半开 ·
> LAN 直连↔公网跳板 双模式自动切换 · 换 ECS 时 EIP 决定多少硬编码要改）：
> 见 `references/remote-access-tunnel.md` 的「跳板恢复」与「迁移」两节。

这类话要的是**最简现状**：哪些自愈了、哪些还缺、缺在哪一层。一条命令跑完只读清点：
（**重启后必看 cron ticker 心跳** —— 偏钟下它会静默卡死, 13 个守护任务一起哑, 见 §9g。）
**可直接跑 `scripts/reboot_verify.sh`** —— 只读, 一条出齐下列全部数字(含开机满 10min 的两点网络复采、cron 心跳双向判活、
帧号递增双采), 输出就是四行汇报的底稿; **换过 WiFi/热点后要报"能打开的链接"就跑 `scripts/net_entries.sh`**
(取当前 IP + 逐个页面 `curl -sL` 探活, 跟跳转 ⇒ 302 不算坏); 以下为它覆盖的同款命令, 手工跑也行:
（每条命令都是实测过的, 但**脚本本身是这组命令的首次组装** ⇒ 第一次跑先通读输出再采信, 发现哪段不合本机实际就直接改脚本）
```bash
date; uptime
systemctl --failed --no-pager
for s in $(systemctl list-unit-files 'zmax-*' 'aoi-*' --no-pager | awk '/enabled/{print $1}'); do printf '%-28s %s\n' $s $(systemctl is-active $s); done
ss -ltnp | grep -E '8791|8793|8790|8891|8893'      # 8793=工位总览=动作授权唯一入口, 不可省
pgrep -af '<手工进程名>'                            # 自启单元管不到的手工进程(推流/采样/桥)
./gui-venv311/bin/python tools/cam_dev_resolve.py   # 相机按卡名实测解析(重启后设备号会变)
                                                    # ⚠️ **必须用 venv python**: 系统 python3 无 cv2 ⇒
                                                    #   每个候选 alive=false "探测异常 ModuleNotFoundError" ⇒ 全 -1
                                                    #   (实测 2026-10-25: 据此回落 --local-dev 0, 而重启后 video0
                                                    #    已不存在 ⇒ 推流 40s 后冻在 1839 帧); 且**推流在跑时**
                                                    #   被占用的那路会报"打不开(被占用)"⇒ 解析要在起流之前跑
ls -l /home/ubuntu/zmax/zmax_data/rokae_sdk/tcp_out/latest.json   # 位姿真值(全 0/读不到=会话陈旧)
                                                    # ⚠️ 家目录整合后的真实路径 = `~/zmax/zmax_data/...` (**不是** `~/zmax_data/...`):
                                                    #   按老家目录路径探会得到"缺 latest.json" ⇒ 误报"真值没在刷"(实测踩过);
                                                    #   容器内 t 字段比宿主早 8h(NTP回拨), 只看文件龄不看 t
ip -br a; ping -c1 -W2 <Orin>; curl -s -o /dev/null -w '%{http_code}' http://<工控机>:10082/last_result
nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader; df -h /
```
判读口径：
- **本机链路 与 外设/网络在不在位，分两层报**：产线网卡不在位 ⇒ Orin / AOI 端口 / 珞石位姿真值**全不可达是环境缺失，不是服务故障**
  （珞石采样容器会一直 `Restarting`，属预期）。但**不许拿它当挡箭牌** —— 本机该起的服务没起，必须单独列出来说。
- **开机后头 1~2 分钟别下「产线网卡不在位」的结论**：USB 网卡(`enx*`)比 WiFi 晚枚举, `ip -br addr` 起初只有 `wlp*`、
  `lsusb | grep -i ethernet` 也还看不到它, 此时 `ping Orin` 会经默认路由报 `No route to host` ⇒ 据此报
  「环境缺失 ⇒ 拒发动作」是**假警报**(实测开机 1min 时判定缺失、90s 后网卡就位且 Orin/工控机全通)。
  判据: `ip -br addr` 里真出现 `192.168.23.x` + `ping -c1 -W2 <Orin>` 通才算「网卡在位」;
  一次不通就**隔 60~90s 复采一次**再下结论 —— **两次采样都查不到**才判真缺失(实操口径见 §9e③: 开机 5min 与 10min 两个点)。
  ○ **ping 通 ≠ 链路在位 (实测 2026-10-28)**: 本机 WiFi 换到 `Corp-Office 10.163.146.78/23` 后,
  `ping 192.168.43.19` 3/3 通 —— 但 TCP 22/39061/8792 **全部 Connection refused**, 且 `ttl=117` + `rtt≈98ms`(mdev 45)
  ⇒ 那是路径上别的设备回的公网/跨网段包, 不是 Orin。判据只认 `</dev/tcp/` 端口通 + `ssh` 真能握手;
  RTT 数十毫秒 + TTL≈117 就是「不在同一网段」的硬信号, 别拿 ICMP 给用户报「Orin 在线」。
  ⇒ 换了网段要同步改 `~/.ssh/config` 的 `Host orin`(实测仍指着已弃 ECS `39.102.211.79:22022`),
  否则 legs/tunnel 单元每 ~5s 空转重启, 日志刷满。
  ⚠️ **产线网卡不在位时 `zmax-proxy.service` 会无限重启**: 它 `Listen 192.168.23.50` ⇒
  `Could not create listening sockets` + `status=71/OSERR`(实测 NRestarts 140/6min)。这是环境缺失的正常表现,
  别当故障修; 要静音就加 `ConditionPathExists=/sys/class/net/<产线口>`, 不要改 Listen 地址。
 ⚠️ **判据只认「能通」，不认「有 IP」**：netplan 里产线口写死成某个 `enx<MAC>` 名字时，换一根 dongle
 (接口名就变) 就不匹配 ⇒ 没有 192.168.23.50; 反过来, 把匹配改成 `enx*` 通配后, **机载/扩展坞的 USB 网口
 也会拿到这个 IP** ⇒ `ip -br a` 看到 192.168.23.x 但 `RX bytes=0`、ARP 全 INCOMPLETE、ping 全丢。
 所以「产线网在位」= `ping -c1 <Orin>` 通 **或** 该接口 `RX packets > 0`; 只有 IP 不算。
 ⇒ 两种写法都不对的**正解 = 按 MAC 匹配**(`match: macaddress: "00:e0:4c:0c:32:a0"`): 真网卡的 MAC 稳定，
 而且 `enx<MAC>` 的名字里就写着它; 而手机 USB 共享 / 机载摄像头的 RNDIS 口(`ethtool -i` = `rndis_host`)
 用的是**随机本地 MAC、每次枚举都变**(名字也跟着变) ⇒ 按 MAC 写只命中真网卡，换 dongle / 重插都不受影响。
 一行排掉干扰口: `for i in /sys/class/net/enx*; do echo $i $(ethtool -i $(basename $i)|awk '/driver/{print $2}'); done`
 （`r8152`/`cdc_ncm` = 真网卡; `rndis_host` = 手机/摄像头，不是产线口）。
 - 🔴 **动 netplan 前先记下 WiFi 的 IP**：`netplan apply` 会重启 NetworkManager、WiFi 可能跳到另一个 SSID ⇒
  本机 IP 换网段; 而用户手里的页面链接/二维码是 **IP 形式**的，他会直接报「某某页面打不开」——
  先 `ip -4 -br addr show wlp*` 对一眼是不是 IP 变了，别急着查服务/日志。恢复用 `nmcli con up <原SSID>`，
  防再跳设 `nmcli con mod <办公SSID> connection.autoconnect-priority 20` + 访客/热点网设 `0`。
  探活页面要**跟跳转**: `.../ar` 返回 302 是**正常**(它跳 8797/ar)，用 `curl -sL` 得 200 才算页面在。
🔴 **老倪常态是远程办公**：他不在现场时**没有插产线 USB 网卡是预期状态**, 不是故障 ——
 不要把「Orin/工控机/珞石位姿/AOI 全不可达」当问题修, 更不要去查网线/交换机；
 一句话报「远程模式 ⇒ 产线链路天然不通, 机器人/550C/AOI 本轮不可达」即可。
  ⚠️ **「等开机满 N 分钟再复采」必须用 `/proc/uptime` 计时, 不要用 `date -d` 做相对算术**:
  `date -d "$(uptime -s) + 10 minutes"` 里 GNU date 把 `+ 10` 读成**时区偏移**(UTC+10:00) ⇒ 算出比现在**早 2 小时**的时间戳,
  于是 `while [ now -lt target ]; do sleep 10; done` **第一轮就退出**, 第二点采样其实离开机只有 4 分钟, 却打印"已满10min" ——
  **凭空造出"两次复采一致 ⇒ 真缺失"的结论**(这条比采样本身更危险: 它让"两点复采"这条防线静默失效)。
  定式: `while [ "$(awk '{print int($1)}' /proc/uptime)" -lt 600 ]; do sleep 10; done`;
  `scripts/reboot_verify.sh --wait` 已按这个计时写好。
  🔴 **但这个等待循环不要在"用户正等着回复"的时候拿前台跑**: 它要静默几分钟, 用户看到的是"静静卡死了"(实测被直接追问)。
  定式: ①先做别的检查(服务/帧号/手动进程/资源), 把第 1 点网络采样报出去, 明说"第二点在开机满 10min 再采";
  ②真要等就 `background=true` 跑、随后 poll, 或者干脆下个回合再采 —— **别用一个阻塞 sleep 循环占住整轮对话**;
  ③只在"两点都缺、且必须当场定缺席"时才值得阻塞等待。
- **本机那 5 个手工进程一律走官方复原脚本，别手敲命令行**（幂等，已在跑的不重拉）：
  `bash tools/boot_restore.sh check` 先看清点 → `bash tools/boot_restore.sh local` 补齐
  （cam_live_stream 8791+8793 / l5_live_mark / vl_safety_monitor / l2_daemon / studio）；它自己按
  `tools/cam_dev_resolve.py` 解析相机设备号并在末尾复核 `8793/station→200`。手搓 `cam_live_stream.py` 会写死设备号串线/近黑。
  ⚠️ 它**管不到** `tools/hil_local_api.py`(8795, 手起) 和 MoveIt 单元(`systemctl start zmax-moveit-plan`, oneshot ~3min) ——
  这两个要单独拉，且按 §9e① **单独一条短命令**（跟长动作串在同一条里会被超时一起带走）。
- **「有进程」≠「在役」**：端口没在监听就是没在服务。逐个 `ss -ltnp | grep <端口>` + 一次 HTTP 探活，双证后才敢说「起来了」。
  探活判据要认得**合法拒绝**：闸门不带 `?k=<token>` 给 403、HIL 终端口不带 token 给 403 —— 有响应码就是「在役」，不是故障。
- **开机后先读 `hermes cron list` 的 `Last run` 会看到**重启前**那一轮的记录 —— 连上一轮的 `error` 一起**:
  实测开机 6min 时读到的 `Last run` 全部早于开机时刻, 「工位推流守护 error: Script exited with code 1」是**上电前**那轮的,
  同一任务开机后下一轮就是 ok。⇒ 判读只认**开机之后发生**的 run; 不足一个调度周期就等一轮, 或 `hermes cron tick` 补火后再读,
  否则会把已被取代的失败当当前故障报给用户(反向同理: 上一轮的 ok 也不代表本轮跑过)。
- `systemctl is-active` 给 `activating` + 反复计数 ⇒ `journalctl -u <unit> -n 20` 看真实原因，不要因为「单元存在」就报正常。
- 汇报按「本机已起 / 本机还缺 / 外设缺失 / 资源(GPU·磁盘)」四行给，一眼能看完，不写「已恢复正常」。

**重启后只中两条、且守门脚本一次能全修（2026-10-08 晚实测）**：① 深度格 `dead=true`(源文件停更 hours 级, 因为容器重启后 `ros_depth_stream` 没自起)；
② 推流源错配（站台「换源」选了 USB，进程却跑默认内置 ⇒ local 出全黑帧 `uniform=1.0 lap=0`, 视觉安全闸 fail-closed 判 unsafe）。
两者都**别手动杀/手搓命令行**，直接跑一次官方守卫即可双修：
```bash
bash ~/.hermes/scripts/cam_stream_guard.sh   # 退出码 0 = 全好; 深度分支会按官方用法在容器内拉起
```
复核口径（必须做）：`8793/stats` 逐格帧号**隔 10s 两采递增** + 深度源 `ss_live/zmax_scene/depth_raw.npy` 文件龄 <1s
+ `vl_safety_fast.json` `safe` 回 true。实测: 深度 0→2.0fps、local 内置黑帧→USB2.0 15fps、local2 MAXHUB 30fps、arm D405 29.8fps。

## 9a. 深度格(🌈 D405 深度图)长时间 stalled：先量落盘节拍, 再定上游还是本机

实测(2026-10-07 重启后): 8793 深度格 `fps=0.0, age_s 35→49, stalled=true, dead=true`, 30s 只 +1 帧。
判据链 (只读, 从下游往上游走):
```bash
# ① 落盘节拍 (真判据: 20s 内 mtime 变几次) —— 8793 的 age 有时来自上一次成功读取, 不能只用它
python3 - <<'PY'
import os,time
p='/home/ubuntu/zmax/zmax_data/ss_live/zmax_scene/depth_raw.npy'; last=None; n=0; t0=time.time()
while time.time()-t0<20:
    m=os.path.getmtime(p)
    if m!=last: n+=1; last=m
    time.sleep(0.5)
print('20s 更新次数', n)
PY
cat /home/ubuntu/zmax/zmax_data/ss_live/zmax_scene/depth_meta.json   # 自带 frames/fps/w/h/depth_scale/valid_pct
# ② 落盘进程在不在 / 有几份 (≥2 份=重复拉起, 见 §10)
python3 -c "import os,time;print(time.time()-os.path.getmtime('/home/ubuntu/zmax/zmax_data/ss_live/zmax_scene/depth_raw.npy'))"
sudo docker exec ss-remote-tap bash -lc 'pgrep -af ros_depth_stream; tail -3 /tmp/depth_stream.log'
# ③ 上游发布者 (注意: 话题真名是 /realsense/depth/image_rect_raw, 不是 /camera/...)
sudo docker exec ss-remote-tap bash -lc 'source /opt/ros/humble/setup.bash; export ROS_DOMAIN_ID=0; ros2 topic info -v /realsense/depth/image_rect_raw | head -12'
```
坑: **`ros2 topic hz <话题>` 在本机/Orin/tap 里都打不出任何输出(连彩色 30Hz 的话题也是空的) ⇒ 它不是可信探针, 别据此报"话题没消息"**。
改用三件套: 落盘 mtime 节拍 + `depth_meta.json` 的 frames/fps + `ros2 topic info -v` 的 Publisher count/节点名。
判读: `Publisher count: 1 / Node name: realsense_source` 且**彩色同相机 30Hz 正常** ⇒ 是 **Orin 侧深度流降级**(上游), 本机 take 流/守护都不是根因;
本机 `ros_depth_stream` 恰好 1 份且日志在写 ⇒ 不要按 §10 再拉起。修上游要在 Orin 上重启 `realsense_source`
(Orin 只读政策: 重启相机源允许, **禁装包**)。

## 9b. 推流某一格「进程活着但不吐帧」= v4l2 卡死, 按官方启动器重启即可

实测(2026-09-30 重启后): `8793/stats` 里 `local online=true, fps=0.0, age_s=137.6, stalled=true, frames_served=14`;
进程在、`/dev/video0` 被它占着(`fuser -v`)、dmesg 无 uvc 报错、`ffprobe` 打不开(Device busy) —— 但相机就是不再出新帧。
⇒ 这类「设备被占 + 帧龄单调增长 + 内核无错」不是硬件掉线, 是取流进程里的 v4l2 抓帧线程卡住。
**处置: 跑官方启动器换号重启**(它会按端口找旧 pid 先停、再按卡名解析设备):
```bash
cd /home/ubuntu/zmax && bash tools/start_station_stream.sh            # 正常重启
cd /home/ubuntu/zmax && bash tools/start_station_stream.sh --check    # 只看现状(不清)
```
复核两格帧号**持续递增** + `8793/station=200`; 实测重启后 `local 15fps frames=3003`(重启前 14 帧冻结)。
注意 `MAXHUB 顶视相机` 没枚举时 `local2=-1/frames=0` 属**硬件缺失**, 重启无用, 如实报缺。

### 9b-2. 「换源选了 USB 但那格还是不显示」= 卡名关键字没命中, 不是相机坏 (2026-10-14 实测)
站台 local 格的 [内置|USB] 选择落在 `zmax_data/cam_local_src.json`, 而设备是按**卡名关键字**扫出来的 ——
关键字在三处各有一份, **改一处不算改**: `cam_dev_resolve.py`(`--usb-name`) · `cam_live_stream.py`(`_USBCFG` **和** `--usb-name` 的 argparse 默认值, 后者会在启动时覆盖前者) · `cam_stream_guard.py`(`USB_KEY`, 它用它判"这格对不对")。
- 现场症状: 外接 **Intel RealSense D435** 已插好(`lsusb` 有 `8086:0b07`), 页面选了 USB, 但那格一直显示内置/不出图 ——
  当时关键字只有 `USB2.0 Camera`, D435 的卡名是 `Intel(R) RealSense(TM) Depth Camera` ⇒ 解析器 `USB=-1`,
  进程回落到内置(日志话术"上次选的是 USB …, 现在没扫到 ⇒ 先按内置起"), 守卫还把它当"相机不在位"跳过。
- 两个必须同时做的修法: ①关键字改成**逗号分隔多关键字**(任一命中): `USB2.0 Camera,RealSense`;
  ②多节点相机(**D435 一台就 7 个 `/dev/video*`**: video0=Z16 深度 · video3=GREY/Y12I 红外 · video5=YUYV 彩色 · 其余 metadata 列不出格式)
  必须**按彩色格式挑节点**; 老代码"有像素格式就兜底"会挑到 `/dev/video0` 深度节点 ⇒ 进程活着但 `fps=0 frames=0`
  (彩色判据 = 含 `MJPG/JPEG/YUYV`; `Z16/GREY/UYVY/Y12I` 都不算).
- 修完的复核三证(缺一不算好): ① `python3 tools/cam_dev_resolve.py` 出 `USB=<n>`(且 `--json` 里挑中的是彩色那路);
  ② 官方启动器打印 `local 🔌 USB Intel(R) RealSense…`; ③ `/stats` 帧号**三次采样递增** + `/snapshot/local.jpg` 200 且不是黑帧
  (实测 640x480 / 37KB / mean 108 / std 43.6)。再跑一次守卫只读判定必须 ✅ —— 关键字没同步改时, 守卫每 5 分钟按老关键字判 ❌ 白重启一次。
- ⚠️ "进程在 + 端口 200" 不能证明那一格好: 唯一判据是**帧号递增**。(本条与 §9b 的 v4l2 卡死区分开: 那条是设备被占着不再出新帧, 这条是**挑错了设备节点**。)

### 9b-3. 推流某格「帧号在涨但画面纯黑」= 相机被 EC/UVC 隐私开关关掉, 不是取流代码 (2026-10-14 实测)

症状与 §9b 的 v4l2 卡死**要分开判**: 那条是帧号冻住; 这条是 **frames_served 正常递增(实测 5fps)而画面全黑**。
判据按顺序量三个数:
```bash
# ① 画面本身(别只看字节数): 纯黑 = mean≈0 且 std≈0
ffmpeg -hide_banner -loglevel error -f v4l2 -i /dev/video2 -frames:v 8 -y /tmp/x.jpg   # 挑一个空闲节点, 绕开推流进程
<venv>/bin/python -c "import cv2;im=cv2.imread('/tmp/x.jpg');print(im.mean(),im.std(),im.max())"   # 实测 0.0/0.0/0
# ② 相机电源(联想 ideapad_acpi): 0 = 关着
cat /sys/bus/platform/devices/VPC2004:00/camera_power
# ③ UVC 隐私开关: value=1 + flags=read-only = 硬件侧关着
v4l2-ctl -d /dev/videoN --list-ctrls | grep -i privacy
```
- **更快的取证口 (优先用它)**: 直接取推流服务自己的快照再算 mean/std ——
  `curl -s -o /tmp/x.jpg http://127.0.0.1:8793/snapshot/local.jpg` 再 `cv2.imread` 打印 `(shape, mean, std)`。
  不抢设备、不碰在役进程, 而且与用户屏幕上看到的是**同一帧**(实测黑帧 mean 5.0 / std 0.9; 真画面 mean 两位数)。
  只有需要绕开推流进程、确认设备原始输出时才用 ffmpeg 抓一个空闲节点。
- **两个软件口都改不动** ⇒ 就是硬件/EC 层: `echo 1 > camera_power` 返回 0 却**读回仍是 0**(EC 拒收);
  `v4l2-ctl -c privacy=0` 直接 `Permission denied`(read-only)。此时**不要再去重启推流/换源** —— 换源/重启都不出图
  (实测重启后帧号涨、图还是 mean 2.7)。
- 处置 = **现场一个物理动作**: 按相机开关热键(F4/F8 那类带相机图标的键) 或拨开物理挡片; 之后 `privacy` 应回 0、
  `camera_power` 变 1, 抓帧 mean 会跳到两位数。**在报「某格黑」时把这条物理动作直接写给用户**, 别说成服务故障。
- ⚠️ 视觉安全闸会因此 `degraded_cams=[local]` + `blocked/no_signal` (§视觉闸 fail-closed) ⇒ 真机动作被拦是这条的下游, 同源处理。
- 同类白瞎功: 换源(内置↔USB)只切设备, **不解除隐私开关**; D435 没插时选 USB 只会回落到「内置+黑帧」。
- **两因叠加时把因分开写**: `cam_local_src.json` 选 `usb` 而 `cam_dev_resolve.py` 给 `USB=-1`(外接相机没插) ⇒ 回落内置;
  内置又被 privacy 开关关着 ⇒ 帧号照涨(实测 5fps)、画面全黑。报告里「选源落空」与「隐私开关关着」各占一条,
  只报其中一条, 用户会以为换源或重插相机就能救。

### 9c. 自启的反向隧道 `activating`/崩溃循环 = ECS 侧端口被**僵死 sshd** 占着

实测(2026-10-07 重启后): `zmax-ecs-ov` / `zmax-ecs-station` 报 `activating` 且 `NRestarts` 每秒涨;
`/var/log/zmax-ecs-*.log` 满屏 `Error: remote port forwarding failed for listen port 18791`;
公网 `https://datadrive.world/ov/...` `/st/...` 全部无响应(curl 15s 超时 = nginx 反代挂在一个没人转发的端口上)。
- 根因: ECS 侧 `18791/18793` 还被**上一次的 sshd 会话**占着(客户端已死, sshd 没回收), `-o ExitOnForwardFailure=yes`
  让新隧道立刻退出 ⇒ systemd 无限重启。ECS 上 `ss -ltnp | grep 1879` 能看到持有者, `ss -tnp` 看对端 IP
  (**对端 IP 可能就是本机上一次的出口, 别因为"不像自己的 IP"就以为是别人的隧道 —— 公网探活超时即证它已死**) 。
- 处置(两步都要):
  ```bash
  # ① 放端口(在 ECS 上)
  for pid in $(ss -ltnp | grep -E '1879[13]' | grep -oP 'pid=\K[0-9]+' | sort -u); do kill $pid; done
  # ② 上保活(治本, 否则下次客户端猝死还会永久占口)
  #    /etc/ssh/sshd_config: ClientAliveInterval 30 / ClientAliveCountMax 3 / TCPKeepAlive yes → sshd -t && reload ssh
  ```
  口令取本机 `/etc/zmax-ecs-*.env` 里的 `SSHPASS`, 用 `sshpass -e` 别把它打进命令行/日志。
- 复核三证 (**口径: 闸门要带口令, 不带 `?k=<token>` 一律 403 —— 403 不是故障, 是"你没带口令"**;
  别再拿 `/overlay` 当探活路径, 它不是闸门的合法路径):
  ```bash
  curl -s -o /dev/null -w '%{http_code}\n' 'http://127.0.0.1:8891/live.json?k=zmax-live'   # 本机闸门 200
  curl -s -o /dev/null -w '%{http_code}\n' 'https://datadrive.world/ov/live.json?k=zmax-live'  # 公网 200
  curl -s -o /dev/null -w '%{http_code}\n' -X POST 'https://datadrive.world/ov/live.json?k=zmax-live'  # 403
  ```
  另: `systemctl show -p NRestarts --value` 要**隔 20s 采两次**确认不再涨 (=真自愈); 单次 active 可能是刚重启的假象。
  ⚠️ **开机头 10~15 分钟内别动 ECS 侧的端口**: 启动期 WiFi/公网抖动会让两个隧道各重启十几次(`NRestarts` 实测涨到 13/11),
  期间公网探活夹杂 000(fail2pass: "Connection ... closed by remote host" / "not responding"), 而**复采一两次(隔 30~60s)就会自己回到 200**。
  实测 2026-10-14 开机: 06:15 探活 /st/=000 → 清掉 ECS 侧占口 sshd + 重启单元 → 06:23:/ov/ 与 /st/ 双双 200、NRestarts 冻住不再涨。
  定式: **先隔 30~60s 复采两轮, 仍是 000 才走本节 ECS 清口**(过早 kill 只会把刚建起来的隧道一起打断)。
  2026-10-07 实测该故障复现: ECS 侧 `ss -ltnp | grep 1879` 只看到 18793 被一个 sshd 占着(18791 那路客户端已死但口没回收),
  kill 后 + **补上 ECS sshd 保活** (`ClientAliveInterval 30`/`ClientAliveCountMax 3`/`TCPKeepAlive yes` → `sshd -t && systemctl reload ssh`),
  复核本机闸门/公网 200 + POST 403, NRestarts 稳定在 4 不再涨。
- 别自己另起端口写 nginx —— nginx 里 `proxy_pass` 的端口是固定的, 换口等于通道全废。
- 🔴 **公网 502 时先对齐"域名解析到哪台"和"隧道落地到哪台", 再决定要不要清 ECS 端口**:
  本机闸门 200 + 公网 502, 不代表隧道坏了 —— 域名 A 记录可能指着另一台机器(站点首页在那边也是 200, 只有 `/ov/` `/st/` 502)。
  ```bash
  dig +short datadrive.world A; dig +short NS datadrive.world | head -1   # 权威记录才是真的
  curl -s -o /dev/null -w '%{http_code}\n' -k --resolve datadrive.world:443:<A记录IP> https://datadrive.world/ov/live.json?k=zmax-live
  curl -s -o /dev/null -w '%{http_code}\n' -k --resolve datadrive.world:443:<隧道落地IP> https://datadrive.world/ov/live.json?k=zmax-live
  ```
  两边不一致 ⇒ 根因是"域名换了主机、隧道没跟着换", 处置是**迁移隧道目标或改 A 记录**(要人点头),
  **不是**去对端 kill sshd —— 按 §9c 清口只会白折腾一轮, 隧道本身是通的。判据: 对端 loopback 上
  `curl 127.0.0.1:18791/…` = 200(说明反向转发好好的), 而公网仍 502。
  域名相关的结论一律报"A 记录 = X(权威 TTL N)", 别只说"公网不通"; 换主机后证书也会换
  (`openssl s_client -connect <IP>:443 -servername <域名>` 看 issuer/签发日), 可作为"这台是不是新机"的旁证。

## 9d. "前几天是不是内核 panic 了?" — 硬停/死机取证 (先摆证据, 再下结论)

用户问"为什么 panic 了/为什么自己重启"时, 按下面顺序**只读**取证, **不要顺着他的话认"panic"**:
```bash
journalctl --list-boots --no-pager | tail -6      # 上一轮开机起止 + 中间空档
last -x reboot | head -6
sudo journalctl -b -1 -o short-iso --no-pager | tail -25            # 断在哪里
sudo journalctl -b -1 --no-pager | grep -iE "Shutting down|systemd-shutdown|Reached target (Reboot|Power-Off)"  # 有=干净, 无=硬停
sudo journalctl -b -1 --no-pager | grep -iE "Kernel panic|Oops|call trace|soft/hard lockup|Out of memory|oom-kill|mce"
sudo journalctl -b -1 -o short-iso --no-pager | grep -c "Write-error on swap-device"   # 风暴判据
sudo journalctl -b -1 -o short-iso --no-pager | grep "Write-error on swap-device" | cut -c1-13 | sort | uniq -c
ls -l /sys/fs/pstore/ ; grep -o 'crashkernel=[^ ]*' /proc/cmdline ; lsmod | grep -E "pstore|ramoops"   # 有没有留下证据的能力
cat /proc/swaps ; readlink -f /sys/block/loop*/loop/backing_file   # 同一个文件被启了两次?
```
判读口径:
- **"日志里没有 panic" ≠ "没 panic"**: panic 现场内核来不及回盘, journald 也刷不下去; pstore 空 + 无 `crashkernel=` ⇒
  **谁都抓不到**。只能说"没有留存证据", 并给出"下次怎么抓"(加 `crashkernel=512M` + kdump-tools, 或 ramoops)。
- **硬停判据**: 日志戛然而止在同一秒 + 全无关机序列 + 无电源键/ACPI/热关机事件。笔记本有电池也只是"不会被拔电停",
  **假死(死锁/OOM 式卡死)一样要靠长按电源** ⇒ 硬停常伴随"swap 写错误风暴"这类内核先兆。
- **一个 swap 文件只许启用一次**(2026-10-02 工位机实测): `fstab` 的 `/swapfile none swap sw` + LiveUSB 遗留的
  `zmax-swapfile.service`(`losetup -f --show /swapfile && swapon $LOOP`)会**对同一个文件的物理块启用两个 swap 设备**(未定义行为;
  实测 12h 内 8872 条 `Write-error on swap-device`, **全部在 loop 那一路**, 直连那一路 0 条 ⇒ 强指向它)。
  处置: `sudo swapoff /dev/loopN && sudo losetup -d /dev/loopN && sudo systemctl disable --now zmax-swapfile.service`;
  **容量要补回就另建一个 `dd` 实块的独立文件**(实测: `/swapfile2` 8G + fstab `sw,pri=-3`, 两块 inode 不同 ⇒ 映射的是两份物理块;
  验证用 `swapoff -a` → `swapon -a` 走一遍开机路径), **千万别对同一个文件再来一次**。

**要把"下次崩了有证据"变成事实**(Ubuntu 24.04 实测口径, 需**一次重启**生效):
```bash
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y linux-crashdump
  # ⇒ kdump-tools + kexec-tools + makedumpfile + crash; 包自带 /etc/default/grub.d/kdump-tools.cfg
  #    (crashkernel=2G-4G:320M,4G-32G:512M,… 本机 31G ⇒ 512M)
sudo tee /etc/default/grub.d/99-zmax-crash.cfg   # 卡死也走 panic(只靠 panic 关键字抓不到"卡死")
  # GRUB_CMDLINE_LINUX_DEFAULT="$GRUB_CMDLINE_LINUX_DEFAULT panic=10 softlockup_panic=1 hardlockup_panic=1"
sudo sed -i 's|^#KDUMP_NUM_DUMPS=.*|KDUMP_NUM_DUMPS=2|' /etc/default/kdump-tools   # 不限份数会吃光盘
sudo update-grub
sudo /etc/kernel/postinst.d/kdump-tools $(uname -r)   # 预先建好迷你 initrd ⇒ /var/lib/kdump/ (免首启现建/失败)
sudo grep -o 'crashkernel=[^ ]*\|panic=10\|lockup_panic=1' /boot/grub/grub.cfg | sort -u   # 生成物复核
```
重启后核验: `sudo kdump-config show` 要 `ready to kdump` + `cat /sys/kernel/kexec_crash_size` > 0。
再配一条 `@reboot` 留痕(`tools/boot_crashcheck.sh`: 记 kdump 就绪状态, 发现 `/var/crash` 有转储就推一条通知)
—— 否则崩后重启又是"什么都查不到"。注意 `nmi_watchdog` 要为 1, `hardlockup_panic` 才真能触发。

### 9d-2. 「屏幕不动了 / 整机卡死」先分三层: 内核 · 显示栈 · 用户会话

三种外观都是"死机", 处置完全不同。只读取证按顺序取:
```bash
journalctl -b -1 --no-pager | grep -iE "Kernel panic|Oops|oom-kill|Killed process|Xid|fence expiration|i915"
journalctl -b -1 --no-pager | grep -iE "Power key pressed|will power off now|Reached target poweroff|Session .* logged out|Stopped gnome-session-manager"
journalctl -b -1 --no-pager | grep "user@1000.service: Consumed"            # 会话内存峰值 + swap 峰值
```
判读:
- **`The system will power off now!` + `Reached target poweroff` + journal 一直记到关机** ⇒ 干净关机, 是**电源键**触发的,
  不是内核死机 (长按 5s 硬断不会留下这段完整关机序列)。先看 `logind` 的 `Power key pressed short`, 再决定要不要往 panic 方向查。
  若同段里还有 `gnome-shell[…]: endSessionDialog: No XDG_SESSION_ID, fetched from logind` ⇒ 是**桌面关机菜单点的**(人手动关的),
  与电源键、与崩溃都不同 ⇒ 报告写"有人从桌面关机", 不要写成"崩溃/自动重启"。
- **`oom-kill` 行要连着读完**: 它自带 `task_memcg=<slice>/<scope>`(哪个终端窗口/单元起的进程) 与
  `anon-rss=X shmem-rss=Y`。`shmem-rss` 很大(实测 6.5G)说明吃的是**共享内存/显存驻留缓冲**, 不是普通堆泄漏 ——
  别照着 anon 一路去查 malloc; 先按 `task_memcg` 找到是哪个会话起的, 再问它当时在干什么。
- **`Fence expiration time out i915-...`** = Intel 核显 fence 超时: 桌面合成停止重绘, 系统还活着 ⇒ 用户看到"冻屏、键鼠没反应",
  这类既能自愈也会反复; 查清后才是 kill 那个吃 GPU 的应用, 不要去重建会话。
- **`user@1000.service ... memory peak`** 接近 `mem_total` 且 swap 峰值贴满 ⇒ 它是"卡顿 / 新窗口合不出"的放大器;
  报结论前先算峰值占比 (例: 26.5G/30G + swap 13.1G/15G), 别只写"内存有点高"。
- **`Session N logged out` / `Stopped gnome-session-manager`** ⇒ 会话已经掉了, 屏幕上就是登录界面 —— 不是崩溃,
  是"桌面重来一遍"; 在这之后按电源键当然是干净关机。

**禁止用 `killall -3 gnome-shell` 救不映射的窗口**: SIGQUIT 是最快的合成器重启, 但它会把整个用户会话一起带走
(实测紧接着 `gnome-session-manager` 停止 → 掉登录界面), 在用户眼里等于"你把机器搞死了"。
窗口 `IsUnMapped` 时先查应用**自己**是不是在崩 (`grep -c "Fatal Python error" <应用日志>` 看 `Segmentation fault`/`Aborted`),
只按 pid 杀那个应用再起一份; 同刻只留一个实例 (每个 GUI 实例常驻 1G+ 且会连内存一起吃)。

**用户说"你怎么卡死了"时, 三端都要查(第三端最常被漏)**:
① 机器端 = 上面三段; ② 我这一端 = `grep -aE "APITimeoutError|ConnectTimeout" ~/.hermes/logs/errors.log | tail`
(模型接口超时的表现正好也是"长时间一个字都不出", 而机器完全正常);
③ **我自己造成的那一端 = 一条阻塞等待/长命令**(等开机满 10min 的 `while … sleep`、`systemctl start` 一个 3min 的 oneshot、
`du /` 全盘扫描)在前台跑几分钟不出字, 工具会把它转后台而用户只看到沉默。
⇒ 回答时**先把这一条认领掉**(说清那条命令在等什么、还要多久、已转后台), 再给机器侧的三个数; 别把它混进"机器卡"或"接口超时"。
三类都要能给判据: 机器端 load/单元数、我这一端 errors.log 的时间戳、第三端"我当时在跑哪条命令"。

## 9e. 开机自愈的两个"假好"陷阱 (2026-10-09 重启后实测)

**① 把后台进程和耗时长的 `sudo systemctl start` 写进同一条 terminal 命令 ⇒ 超时被工具杀掉时, 后台子进程一起死。**
实测: 一条命令里先 `setsid nohup` 起 8795 HIL API + 实时标注器(打印了"✓ 已拉起 pid …"), 紧接着
`sudo systemctl start zmax-moveit-plan`(该 oneshot 要跑 ~3min), 命令在 300s 被工具超时终止 ⇒
**两个 setsid 的进程全没了**, 端口 8795 也没在听 —— 而日志里那句"✓ 已拉起"还留着, 看着像成功。
判据/做法: 起后台进程的那条命令要**立即返回**(脚本里 `setsid nohup … &` 后只 `sleep 3~5` 复核一次,
不做任何长动作); 耗时的 `systemctl start` 单独一条命令跑(或 `background=true`)。
复核实证用 `ss -ltnp | grep <端口>` + 一次 HTTP 探活, **不看"已拉起"的打印**。

**② `boot_restore.sh` 的深度源自检在容器不可达时误报"已在跑"。**
它的判据是 `[ "$(sudo -n docker exec ss-remote-tap … grep -c '[r]os_depth_stream.py')" != "0" ]`;
容器处于 `activating`/不存在时 `docker exec` 返回**空串**, 而 `"" != "0"` 为真 ⇒ 打印"深度源已在跑",
实测同一时刻 8793 深度格 `frames_served=1 / age 800+s / stalled=true`。
⇒ 别信这一行: 先判容器状态(`systemctl is-active ss-remote-tap` 或 docker inspect), 只有 `running` 才继续判进程;
**落盘节拍(§9a 的 20s mtime 计数)才是真判据**。

**②b 同一个脚本的 ① 进程行也会假绿 (2026-10-15 重启后实测)。** `check` 报 `✓ l5_live_mark pid 60798`,
2 分钟后该 pid 已不存在、`pgrep -af l5_live_mark` 为空、`zmax_data/l5live/l5_live_mark.out` **根本不存在**(启动器从没跑过)
⇒ `check` 的 ✓ 只能读成"取样那一刻有进程", 复核一律用**现场 `pgrep -af` + 输出文件 mtime/存在性**双证。
(好事是 `local` 分支里的 `pgrep -f "[l]5_live_mark_run.sh"` 判重是准的: 缺了就 `bash tools/boot_restore.sh local` 一句补回,
实测补后守护 shell + `tools/l5_live_mark.py` 双进程在跑。)
**本机那 5 个手工进程(含 l5_live_mark)没有任何 cron keepalive**, 只有 `@reboot` 的 l2/vl 两条 ⇒ 重启后不自愈,
靠 `boot_restore.sh local` 补; 它内部 `nohup … &` 而工具层拦的是**命令行里**的 nohup ⇒ 用 `bash tools/boot_restore.sh local`
这种脚本形态起, 不要自己手搓 `setsid nohup`。

**③ 产线网卡不在位时, 这一批会跟着"合理"地全倒** (不是独立故障, 别逐个当 bug 修):
`ss-remote-tap` 单元 `start-pre` 超时→崩溃循环("No such container") ⇒ 深度格 stalled;
`zmax-proxy`(tinyproxy `Listen 192.168.23.50`) 每 3s 一次 `Could not create listening sockets` 崩溃循环(NRestarts 分钟级+百);
Orin/工控机/珞石位姿真值/arm 取流全 0。判据: `ip -br a` 里没有 `192.168.23.x` + `lsusb` 无 USB 网卡,
**开机 5min 与 10min 两次复采都在** 才算真缺失(§9 的 1~2min 规矩)。网卡插回后这些会各自恢复, 不用手工拉。

## 9f. 2026-10-09 重启后复采: 四个"看着像故障其实不是"的点

**① 开机 2min 时 8791/8793 端口空 ⇒ 不要手搓拉起, 守护 5 分钟内会自己起。**
实测: up 2min 时 `ss -ltnp` 无 8791/8793、`curl 8793/station` = 000; up 5min 再采, `cam_stream_guard`(cron)
已在 21:10 拉起 pid 14240, `8793/station` 与 `8791/` 双 200。判据: 先看 `stat -c %y /tmp/cam_stream_guard.log`
有没有刚写过, 再决定要不要 `boot_restore.sh local`。
**用户此刻报「某页面打不开」时先对开机时长**: 开机 1~3 分钟内的 000 就是这段补齐窗口(实测 8793/8797 在 up 2min 时
全 000、up 3min 后 200), 复采即可, 别去动服务; 同时**「IP 没变」是正常答案** —— 重启不改 DHCP 租约,
IP 变只发生在换 SSID / `netplan apply` 之后; 报页面前用 `curl -sL` 跟跳转(`/ar` 302→8797/ar 才算在役)。

**② ECS 反向隧道的判活不能看日志 tail —— 日志里永远留着历史 `Error: remote port forwarding failed` 行。**
实测重启后 `zmax-ecs-ov/station` 显示 `activating` + NRestarts 从 2→4, 但那是**开机头 90s 的短暂循环**;
判据取三证: ①`ActiveEnterTimestamp` = 21:10:00 且 `NRestarts` 隔 20s 两次**不再涨**(冻在 4)
②`stat -c %y /var/log/zmax-ecs-*.log` 停更(21:09:50) ③公网探活 `https://datadrive.world/ov/live.json?k=…` 与 `/st/station?k=…` 双 200。
三证齐 = 隧道已通, **不要去 ECS 上 kill sshd**(那是 §9c 的处置, 只在真的长时间抢不到口时用)。
若非要去 ECS 上看: 占口的 `sshd` 用 `ps -o etimes` 看**存活秒数**可作**辅助**, **但不能当唯一判据** ——
见下面 2026-10-11 的反例。

**⚠️ 反例: `etimes` 看着"很新"的占口 sshd 也可能是坏的那一段 (2026-10-11 重启后实测)。**
现象: 开机 ~3min 时 `zmax-ecs-ov/station` 都是 `activating (auto-restart)`、`ExitOnForwardFailure` exit 255,
日志刷 `remote port forwarding failed for listen port 18791/18793` + `Timeout, server … not responding`;
ECS 侧占口的两个 `sshd: root` 的 etimes 只有 **196s / 20s** —— 按 §9f② 的"秒数小=自己人"会被误判成"活隧道, 别动",
但公网 `https://datadrive.world/ov/live.json?k=…` 与 `/st/station?k=…` 全是 **000(curl 10s 超时, 已连上 TLS 但 nginx 那头等不到响应)**。
判据修正: **判死活的唯一硬证据是"本机闸门 200 + 公网 200 + POST 403"三连**; `etimes`/日志 tail 都可能骗人
(客户端在 `-R` 建口之后立刻死掉时, ECS 侧留下的 sshd 也是"刚建的")。
处置与 §9c 同(ECS 上 `kill` 掉 1879x 的持有者 → 本机 `systemctl restart` 两个隧道单元), 实测 kill 后重启
**公网 ov/st 双双回到 200、POST 403、NRestarts 冻在 4 不再涨**。注意 ECS 的 sshd 保活(`ClientAliveInterval 30` 等)
必须生效 —— `ClientAliveInterval 30`/`ClientAliveCountMax 3`/`TCPKeepAlive yes` **前后各有一份**(该文件里被注释的那三行仍在),
判断时要看**未注释**的那份。

**③ 8795 `hil_local_api.py` 是手工进程, 且工具层会拦 `nohup/setsid`。**
写 `setsid nohup … &` 会被 Hermes 直接拒(`Foreground command uses shell-level background wrappers`) ⇒
改用 `terminal(background=true, persist_on_release=true, command="cd <ROOT> && exec ./gui-venv311/bin/python tools/hil_local_api.py")`,
再单独一条命令复核 `ss -ltnp | grep 8795` + `curl 127.0.0.1:8795/health` = 200。

**④ 深度格慢是 Orin 上游的固有限制, 不是重启回归。**
本机侧证据(`depth_raw.npy` 20s 更新 3 次 / `depth_meta.json` fps 0.5 / 8793 `depth.fps≈0.2`)只能说明"慢",
要定责必须在 **Orin 上直接量话题节拍**: 传一个 rclpy 探针(12s 窗口, BEST_EFFORT 订阅)数消息,
实测 **depth 0.17Hz / color 0.17Hz**(同一时刻 `rs_fast_node` 直读设备仍 30fps ⇒ 厂商节点是按需/低频发布, 不是掉线)。
历史留档同样口径: 09-29 夜 0.24fps"慢但不死"、10-07 "源文件龄常 20s"、10-08 1.77fps ⇒ **属长期已知项**,
别为此去重启 `realsense_source`(`ros2 topic hz` 依旧不可信, 用订阅计数)。Orin 侧只读探针可 `scp` 脚本到 `/tmp` 再跑, 不必装任何包。

**⑤ 两个"假缺失"清单项**: `boot_restore.sh check` 里的 `demo_recorder` 早已不存在(全仓只有 boot_restore 自己提到它)
⇒ 每次开机都报一行 ✗, 属陈旧项不用管; `local2`(MAXHUB 顶视)不在位时 `cam_dev_resolve.py` 给 `LOCAL2=-1`,
是**硬件缺失**(`/dev/video*` 里根本没有它的卡名), 不是串线。
另: 列"启用单元"别用 `awk '/enabled/'` —— 它会连 `disabled` 一起匹配(实测把 disabled 的 `zmax-moveit-plan`、`zmax-swapfile` 报成自启项); 要 `systemctl is-enabled` 逐个判。

## 9g. 时钟被回拨(开机 RTC 快 8h)会把「时间戳判活」全打成假象 —— cron ticker 会静默卡死

**判活一律不许只看 age/`max(0, now - t)`。** 2026-10-13 实录: 开机时 RTC 比真实时间快 8h, 内核先按 RTC 置钟,
NTP 约 30s 后才拨正 ⇒ **在回拨前写下的任何时间戳(文件 mtime / 心跳 epoch / 台账 t 字段)都落在"未来 8h"**。
而 `age = max(0, now - t)` 会把负值夹成 **0 秒 = 永远"新鲜"** ⇒ 死了也报活。
- 判活要**分开判 两种坏**: `t - now > 120s`(在未来 = 时钟被回拨污染) 和 `now - t > STALE`(真过期)。
  只判后者 = 这一整类故障**永远不会被发现**。
- 典型现场(同一分钟里同时中招): cron 心跳 `ticker_heartbeat` 冻在回拨前的 epoch(看着新鲜)、
  反向通道取回执的逻辑用 `max(mtime)` 恒选到那几个"未来 mtime"的陈旧回执(每次误报"通道死了")、
  `hermes cron status` 误报 `✗ No gateway is running`(pid 文件被按"陈旧"清掉)。

**cron 看门狗不能靠 cron 自己看着自己。** 这次网关在偏钟下起(01:51:57), cron ticker 只写了**一次**心跳就再没动过:
`next_run` 早过点的 13 个任务(磁盘红线 · 推流守护 · AOI 两路看门狗 · 运动警报 · 阶梯哨兵 · 4060 同步)全线静默,
而 `ps`/心跳/py-spy 都显示 ticker 线程还好好地在它的 `stop_event.wait()` 里 —— **静默、无报错、无告警**。
处置与固化:
```bash
hermes cron status                      # ✗ No gateway is running 时别照它下结论(见上)
systemctl is-active hermes-gateway      # host 级单元; 不要用 pgrep -f 'gateway run' 判活(见 §9i①)
hermes cron tick                        # 不依赖网关 ticker, 立刻把"过点"的任务点一遍(补火)
hermes gateway restart                  # 让 ticker 在正时钟下重起 —— 实测重启后 60s 一次, 恢复正常
```
- **独立哨兵**(装在 systemd user timer 里, 不在 cron 里): `~/.hermes/scripts/cron_ticker_watchdog.sh`
  + `~/.config/systemd/user/hermes-cron-ticker-watchdog.{service,timer}`(每 5 分钟, `loginctl Linger=yes` 才随开机起)。
  三条判据任一命中就重启 gateway(30 分钟限流): ①心跳过期 >600s ②心跳在"未来" >120s ③有 enabled 任务的
  `next_run_at` 过点 >300s。健康时**一个字都不打**; 出动作才写 `~/.hermes/logs/cron_ticker_watchdog.log`。
  两个分支都要真跑一遍验证(用一个假心跳文件 + 改掉副本里的路径 + `HERMES=/bin/true` 的副本试, 别拿真脚本试重启)。
- `@reboot` 的重算脚本(`~/.hermes/scripts/hermes_cron_reclock.sh`)只重排 `next_run`, **修不了已经卡死的 ticker**;
  现在它在末尾量一次开机时钟偏差, 偏了(>60s)就调上面那个哨兵复核。
- **重排 `next_run` 会吃掉"当前就过点"的那一次**(重排 = now + interval)。补火用 `hermes cron tick`, 不是重跑 reclock。

**反向通道取回执: 用"文件名集合差", 不要用 `max(mtime)`。** `tools/station_cmd.py` 原先按 mtime 找最新回执,
回拨后 18 分钟里**每一次调用**都误报"N 秒内没等到回执(通道死了?)", 而 `hub.log` 同一秒就写着回执已落盘(443 字节)。
改成"入队前记一次 `os.listdir` 集合, 之后找新出现的名字"(文件名 = 落地时的 epoch 秒) 后, 通道秒答。
⇒ 凡是"等一个新文件出现"的逻辑, 都用集合差/内容指纹, **mtime 是会被时钟跳变污染的**。

**钉死哈希的哨兵会随版本过期而喊假警报。** `tools/aoi_channel_sentinel.sh` 钉的是 `cam_surface_10083_work_v6.py`
+ `636AC7854C947943`, 而 2026-10-12 已上线 v20(v6 文件在工控机上早删了) ⇒ 通道一醒就报
"文件损坏且无可用副本"。修法两层: ①把 `F`/`WANT` 更新到在役版; ②**当"钉的文件名在盘上根本不存在"时单独报
【哨兵钉的版本已过期】并列出在役 `cam_*_work_v*.py` 文件名** —— 与"文件真损坏"区分开, 否则下次升版本又是一场假警报。
更根本: 版本号从部署真源取(`tools/aoi_remote_deploy.py` 的 `FILENAME_10082/FILENAME_10083`), 别在启动/恢复脚本里硬编码
(实测 `tools/start_aoi_v6.py`、`tools/boot_restore.sh` 的 aoi 段都还钉着 v6 ⇒ 会"成功地"起两个不存在的文件)。

**这一轮的实测时间线**(口径照抄): 17:52:09 网关起 → ticker 唯一一次心跳 → 17:54:24 一条 4060 同步因
GitHub 连不上(135s 超时)失败 → 17:54:28 之后再无任何 tick → 18:10 `hermes cron tick` 手工补火 4 个任务 →
18:15:17 `hermes gateway restart`(PID 79899) → 心跳回到 60s 一次、incident 清零、8791/8793/8797/8798 全 200。

## 9h. 「检查任务」= 三处只读清点, cron 的 error 要按**产物**对账

用户一句"检查任务"要的是**现状**, 不是待办列表。按序三处(全只读, 顺序别换):
1. **待办**: `todo_list` —— 空是很常见的结果, 只报它等于没查。
2. **定时任务**: `cronjob_manage list` —— 看 count 与逐条 `last_status`/`next_run_at`; 同时报 gateway 是否在跑
   (`systemctl is-active hermes-gateway` —— system 级 host 单元, cron 在网关里 tick; **别用 `pgrep -f 'gateway run'` 判活**, 见 §9i①)。
3. **在役服务**: `ss -ltnp` 逐个端口 + 一次 HTTP 探活 + `systemctl --failed`(=0)。
   "端口在听"只说明有进程, 探活码才是"在役"(闸门口 403 属合法拒绝, 不算坏)。

**`last_status: error` ≠ 现在坏了 —— 回读它交付的产物再定性 (本节最值钱的一条)**:
- 例: 硬件同步任务报 `unable to access … GnuTLS recv error`; 判据不是再跑一遍脚本, 而是读**它本该更新的那份东西**:
  `git log -1 --format='%ci %s' origin/<分支>` + `git show origin/<分支>:<数据文件>` 里自报的 `*_updated` 时间戳。
  产物时间就在几分钟前 ⇒ 上一轮成功、这一轮网络抖动 ⇒ 报"瞬时失败, 已自愈", 不动它。
- 反向也成立: 产物时间是 days 级 ⇒ 任务"看着 ok 其实早不出货", 这才是要查的。**结论永远由产物下, 不由 last_status 下。**
- 开机头一个调度周期内读到的 `last_status` 可能是**重启前那一轮**的(见 §9), 与产物对账能一起排掉这个误读。

**本机 `127.0.0.1:10082/10083` 在听 ≠ 产线直连可达 (本机常靠隧道)**:
- 读到 listener 先看它是谁: `tr '\0' ' ' < /proc/<pid>/cmdline` —— 实测本机这两口是 systemd 单元 **`zmax-orin-aoi-fwd`**
  的 `ssh -NT … -L 127.0.0.1:10082:192.168.23.23:10082 … tashan@<ECS>:22022`。
- 同时 `ip -br addr` 没有 `192.168.23.x`、`ping` 也不通 ⇒ 结论是"**直连缺失, 只能经 ECS 隧道**", 报告里必须写明这条通路,
  别写成"工控机在线"(网卡插回后自动回到直连, 不用改配置)。
- 隧道 flap 判据: `journalctl -u zmax-orin-aoi-fwd -b | grep -c 'Scheduled restart'` 与 `Timeout, server … not responding` 行;
  开机头几分钟 flap 一次很常见(ping 通、端口开、探活 200 就别动) —— 只有**长期拿不到口/探活持续 000** 才按 §9c 去对端清 sshd。
  复采隔 30~60s 两轮再下结论(§9c/§9f 同一口径)。

**汇报形状**(用户要看结果, 不看成篇): 任务(空/几条, 哪条异常+已核产物) · 服务(端口+探活码) · 通路(直连 or 隧道)
· 资源(GPU 利用率/显存 · 磁盘) · 写好但未上线的交付件 · 需要人决定的一条。数字在前, 不写"一切正常"。

## 9i. 网关本身出问题: 双单元空转(exit 75) · 判活认 systemd 不认 pgrep

**① `pgrep -f 'gateway run'` 判不到活着的网关 —— 它的 argv 是 python 包装。**
网关主进程 cmdline 实为 `python3 -I -c "import sys, runpy; … runpy.run_module('hermes_cli.main', run_name='__main__', alter_sys=True)"`,
里面**没有** `gateway run` 字样 ⇒ pgrep 空 ⇒ 报「无 gateway 进程」是**假警报**(同一刻心跳在动、cron 按点跑)。
判活只认两项: `systemctl is-active hermes-gateway`(host 级) + ticker 心跳年龄。`scripts/reboot_verify.sh` 已按此改。

**② user 与 system 两个 gateway 单元同时装着 ⇒ 每 5s 空转重启, NRestarts 爬到几十。**
形态: `systemctl --user is-active` 给 `activating (auto-restart)`, `journalctl --user -u hermes-gateway` 每 5s 一行
`✓ The host gateway already serves profile 'default' — nothing to start.  PID <host gateway>`;单元带 `RestartForceExitStatus=75`
⇒ 「已在跑」这个退出码被当成需要重启 ⇒ 无限循环, 每实例烧 ~1.3s CPU、restart counter 直线涨。
- 判据: `hermes gateway status` 头一行就写 **Both user and system gateway services are installed**。
- 处置 = **保留在跑的那个, 卸掉另一个**(别两个都动):
  ```bash
  systemctl is-active hermes-gateway; systemctl show -p ExecMainPID,NRestarts --value hermes-gateway   # 在跑的
  hermes gateway uninstall          # 卸 user 级; 反过来用 sudo hermes gateway uninstall --system
  ```
- 复核三件: user 单元文件已不存在 · 在跑那个的 `ExecMainPID` **未变**(没被顺带杀掉) · 心跳仍按 ~60s 继续写。
- ⚠️ 只 `stop` 不 `uninstall` 无效: 单元 `enabled` + `Restart=always`, 下次开机照旧循环。

**③ 目标机整台不可达 ≠ 端口被占(§9c)。** 本机互联网正常(baidu 200、网关 ~15ms)而目标 **ping 100% 丢 + 22/22022/80/443 全 timeout**
⇒ 是那台机器/安全组的事, 不是隧道配置、也不是对端 sshd 抢口 —— 按 §9c 去对端 kill sshd 是白折腾。
报告只写「本机互联网正常, X 整台不可达(实例/安全组), 本机侧修不了」并给一条要人点头的动作; 用户改走手机热点/局域直连时, 这整条通路不用修。

## 10. 守护脚本的早退会吞掉它后面所有自愈(重启后最常中的一条)

一个守护里有多条自愈分支、又写成 `if bad: … return` 时，**排在前面的那条一坏，后面的自愈永远不执行**。
实测：`tools/cam_stream_guard.py` 的深度源分支（容器/源文件龄）直接 `return 1`，而「推流没跑就拉起」排在它后面
⇒ 深度容器早就不在时，脚本每 5 分钟都在深度分支退出，推流那一支**一次都没跑过**；表现就是重启后 8793 工位总览一直没人拉，
而 cron 日志里只看得到一行深度失败（看着像「守护在工作」）。
- **立即恢复**：跑那条**官方启动器**，不要手搓命令行 ——
  `cd /home/ubuntu/zmax_rel && bash tools/start_station_stream.sh`（它自己按卡名解析设备、抬 fd 上限、末尾复核 `8793/station → 200`）。
  手搓 `cam_live_stream.py` 会因为设备号写死串线/近黑。
- **治本**（2026-09-30 已在 `tools/cam_stream_guard.py` 落地并实测）：把每一项自愈都跑完再汇总上报
  （收集式 `notes.append(...)` 代替中途 `return`），只有全好才静默；退出码 = 有失败项才非 0。
- **守护判「环境缺失 vs 服务故障」**：先 `docker inspect -f {{.State.Status}} <容器>` 定容器状态，
  `running/exited/created` 才值得手动救；`restarting`（docker 自己正在拉起）与 `absent`（不在位）**只跳过**——
  否则每 5 分钟去 `docker exec`/`docker restart` 一遍，纯刷屏且无用（产线网卡不在位时 tap 容器
  一直在 netwait、珞石采样容器一直 crash-loop，都属预期）。
  ⚠️ **docker 新版报错是小写** `error: no such object: <name>`（实测 docker 28）——按 `"No such"` 做
  大小写敏感匹配会漏判成「查不了」→ 该跳过的自愈反而去瞎折腾。判「容器不在位」要用 `.lower()`。
- **改完必须真跑一遍故障路径**：`kill <8791 pid>` → 跑守护 → 复核 `8793/station=200` + `/stats` 帧号递增，
  这才证明「深度分支不再吃掉了推流分支」（自测开关 `--cmdline/--expect/--stats-json` 只验 judge 纯函数，验不到分支顺序）。
- **排查定式**：守护「确实每 N 分钟都在动、但目标服务就是不活」⇒ **先定位它从哪个分支返回的**，别先去怀疑被守护的服务本身。
- **"源文件不新鲜"不等于"进程不在"**（2026-10-07 实测）：深度源分支原来把「文件龄 > 20s」也当成需要拉起 ⇒
  上游相机一停，守护每 5 分钟再拉一个 `ros_depth_stream`，一夜堆到 **10 个进程**（都订阅同一话题互相抢，
  Orin 的 `ros2 node list` 里都看得到重复节点）。判据要拆开：**只有"进程不在/查不到"才拉起**；
  "进程在跑但文件旧" = 上游(相机/话题)问题，**只报告 + 指明上游节点名**，重复拉起治不了还会放大故障。
  改完两条分支都要真跑：缺进程→必须拉起 1 个；进程在 + 人为 `touch -d '10 minutes ago' <源文件>` → 必须**不**再多起。
- **复核与判定必须用同一组参数**（2026-10-08 实测）：`cam_stream_guard.py` 的 `restart()` 复核时调
  `judge(proc_cmdline(), resolve_devs(), stats())` 而**漏传** `local_expected()` ⇒ 判定走的是"用户换源选择"
  (站台有「内置 ↔ USB」换源, 选择落盘在 `zmax_data/cam_local_src.json`)、复核却回落到默认的 "Integrated RGB"。
  后果: 用户选了 USB 之后, **每一次合法重启的复核都打出假 ❌ (exit 1)**，日志里看着"串线一直没治好"，
  而实际服务是好的(主流程的 `judge(...)` 是传了的, 所以不会真循环重启)。
  教训: 一个判据函数被两处调用时,**默认参数会在其中一处偷偷变口径** —— 复核路径要把与主路径**逐字相同**的参数传进去;
  改完用自测口验**两个方向**: 期望 USB 且拿到 USB → ✅; 期望 USB 却拿到 Integrated → 仍 ❌(真串线照样抓得到)。
- **用户选的那路设备不在位 = 环境缺失 ⇒ 跳过重启, 别每 5 分钟白重启一次** (2026-10-08 实测):
  站台「换源」落盘选了 USB 相机, 而机器上**根本没插** (`cam_dev_resolve.py` → `USB=-1`),
  守卫却按"用户选的那台"去判 label ⇒ 判定永远 ❌ ⇒ **每 5 分钟重启一次推流纠正**, 复核也永远 ❌
  (实测 10 分钟内推流换了 4 个 pid, `8793/station` 与公网 `/st/` 反复短暂 000/502),
  **而且这个循环永远修不好** —— 相机没插回来就无解。
  修法: 在判 label **之前**先判"期望设备在不在位"(`user_src_absent()`), 不在位 ⇒ 判环境缺失、
  不校验那格卡名、不重启, 只报告一行; 相机插回后下一轮自动回到正常判定。
  同时把判定与复核收口到**同一个入口函数** (`judge_now()`) —— "两处用同一组参数"不要靠人记。
  验收两步都要跑: ①实际环境(相机不在位) 真跑一次 → 一行说明 + 退出码 0 + **pid 未变**;
  ②反向 `kill` 掉被守护的进程再跑 → 必须照样拉起(新 pid + 端口 200 + 帧号递增)。

## 10b. 停/重启常驻进程: 用锚定的精确 `pgrep` + PID, 不要裸 `pkill -f <模式串>`

`pkill -f` / `pgrep -f` 匹配的是**整条命令行**; 而命令是包在一个 shell 里执行的, 那条 shell 的 cmdline 里
**就含有你刚写下的整条命令** ⇒ 模式串必然命中它自己, 表现是“命令跑到一半我自己的 shell 被杀了”(exit -15)。
实测连中三次: 有一次把服务停掉之后**后续步骤全没执行**(服务停在停机态), 对外却是“已经重启过了”。
**通过 ssh 远程停进程时症状会伪装成"主机挂了"**: `ssh host 'pkill -f "pip install torch"'` 的模式串命中**远端那条
`bash -c` 本身** ⇒ 会话被自己杀掉, 本地看到的是 `exit 255` / `Connection closed`, 很容易误报成网络或对端失联。
远程一律先 `ps -eo pid,etime,cmd | grep <锚定模式> | grep -v grep` 取 pid 再 `kill <pid>`, 不要 `pkill -f 串`。

定式(幂等、可复核):
```bash
# ① 把模式锚定成“整条命令行”(^...$) —— 只可能命中那个进程本身
pgrep -af '^/home/ubuntu/zmax/gui-venv311/bin/python tools/l2_daemon\.py$'
# ② 确认仅剩目标 → 取 pid 杀(必要时 kill -9)
pgrep -f '^/abs/python /abs/script\.py$' | xargs -r kill
# ③ 重启一律走官方保活/启动脚本(自带探针+复核), 不手敲长命令
```
- **杀与拉分成两条命令时最容易出事**: 第一条把自己杀了 ⇒ 第二条永不执行。要么一条命令里“先杀后拉”, 要么杀完
  先**单独确认**“确实没了”, 再单独拉。
- 复核口径: 再跑一次那条锚定 `pgrep -af` 应为空; 服务是否回来**以端口/HTTP 探活为准**(`ss -ltnp` / 探活码),
  不看“脚本退出码 0”。
- 更稳的做法: 常驻进程启动时写 pid 文件, 之后一律按 pid 文件杀。
- **脚本里的 `pgrep -f <py名>` 会命中"另一条正在执行的命令"的 shell**: 那条 shell 的 cmdline 里可能恰好含
  同一个串(哪怕你自己写的是 `gui/studio.py`、脚本里写的是 `studio[.]py`, 方括号只防自己那一条命令行),
  于是脚本的 `kill $(pgrep ...)` 把**正在调用它的 shell**一起杀掉 ⇒ 命令 `exit -15`, 后续步骤全没执行,
  而用户看到的是"窗口闪一下没了"。定式: **按 comm 过滤, 只留解释器进程**:
  ```bash
  _pids() { for p in $(pgrep -f "gui/studio[.]py"); do
              case "$(cat /proc/$p/comm 2>/dev/null)" in python*) echo "$p";; esac; done; }
  ```
  杀完必须复核 `[ -n "$(_pids)" ]` 为空才算停掉; 起新实例用 `setsid nohup … &` 后 `sleep 6` 再取 pid 复核(不要用 `$!`,
  `setsid` 的 pid 不是解释器的)。
- **守护进程名唯一时, 最简安全形式是 `pgrep -x <可执行名>`**(只按可执行名精确匹配, 不含参数与路径 ⇒
  不可能命中调用它的那条 shell; `pgrep -f` 才需要 `^...$` 锚定)。实测
  `pgrep -x tinyproxy | while read p; do sudo kill "$p"; done` 一次干净停掉、不再自杀;
  收尾复核"再跑一次应为空 + 端口/探活为准"。
- 同一类坑还有: 内联的长命令会被工具层拦或截断 —— 脚本化写到 `/tmp/*.sh` 再跑。
- 🔴 **同一 GUI 会有多份实例, 而模式串常常只认其中一种 argv**: 实测 `pgrep -f "gui/studio[.]py"`
  匹配 `tools/gui/studio.py`, **漏掉 cwd=tools/gui 时以裸 `studio.py` 启动**的那份(IDE F5 / 手工起)
  ⇒ 脚本每次"重启"都是再起一份、旧的那份连起六次都没被杀; 两份额外各占 1.3~1.8GB + 各吃一份 CPU,
  而用户眼前的窗口恰恰属于旧的那份(他看到的永远是旧代码, 于是"改了没用")。
  定式: 候选用宽松模式 `pgrep -f "studio[.]py"` → 三重过滤(`comm` 是 python · `readlink /proc/<pid>/cwd`
  在本工程目录 · 不命中自己这条 shell) → 杀完复核"只剩一份";
  复核他看的是不是新实例用 `wmctrl -l -p`(窗口→pid) + `ps -o lstart=` 比提交时间, 不看进程个数。

## 12. 某进程 RSS 只增不减(把整机拖到 thrash)⇒ 段级 diff + bpftrace 抓分配者

**别靠读代码猜泄漏点。** 三步定死, 顺序不要跳:
```bash
free -m; ps -eo pid,etime,rss,nlwp,args --sort=-rss | head -5      # 谁在涨 + 跑了多久 + 几个线程
sudo grep -E "Private_Dirty|Anonymous|Rss" /proc/<pid>/smaps_rollup  # 匿名堆=自己的分配; 大额 file 映射=数据集/模型
```
① **哪一类映射在涨**(两次快照 diff): `sudo python3 scripts/probe_rss_seg.py --pid <pid> --wait 120` ——
  `[anon]` 涨 = numpy 大数组/GL 缓冲/线程栈; `[heap]` 涨 = 小对象; **56~72MB 段反复"新映射" = glibc arena**;
  **128KB~1MB 段高频新增 = CPython pymalloc arena**(`_PyObject_ArenaMmap` 每次 256KB)。
② **谁在分配**(决定性, 别停在推测):
```bash
P=$(pgrep -f '<脚本名>[.]py' | head -1)
sudo bpftrace -e 'tracepoint:syscalls:sys_enter_mmap /pid == '"$P"'/ { @u[ustack(5)] = count(); }
                  interval:s:40 { exit(); }' > /tmp/s.txt 2>&1   # 最大栈在最后, 别 head
grep -A6 '@u\[' /tmp/s.txt | tail -40                                # 或用 python 正则聚合 count
```
  栈里出现 `_PyObject_ArenaMmap ← _PyObject_Malloc ← PyDict_SetItem ← scan_once_unicode` = **高频 json 解析**;
  出现 `_PyUnicode_New`/`dict_merge` = 高频拼字符串/建字典; 出现 `sysmalloc_mmap ← _int_malloc ← __libc_malloc` = C 侧大块 malloc。
  顺带看尺寸分布 `@sz[args->len] = count()`: 非 2 的幂的怪尺寸(147456/512000…)都是 4096 的倍数 = malloc 的 mmap 路径。
③ **修法与判据** 见 `references/process-rss-growth-forensics.md`。核心定式: **轮询读取按 `(mtime_ns, size)` 缓存**
  (文件没变 = 零解析, 只刷新帧龄/age 这类随墙钟变的字段)。

⚠️ **判据只认"增速掉下来"**: 改完重启, 采 5/10/20 分钟三点算 GB/h 与前值对比; 单点 RSS 变小不算数(启动缓存会骗人)。
   只降一部分就如实报剩余 GB/h+"未定位", **不写"已根治"**。
⚠️ **别只调 `MALLOC_ARENA_MAX`**: 它治 glibc arena, 治不了 CPython pymalloc arena(高频小对象那类才是多数)。
   要加就**启动器与 IDE launch 配置两处都加**, 否则换成 F5 启动就失效。
⚠️ **杀掉这类 GUI 进程后必须自动拉起**(看门狗里 `subprocess.Popen(["bash", restart.sh])`), 否则用户看到的是
   "程序自己没了"却不知道为什么; 阈值按实测增速算(1.5GB 起 + 5GB/h ⇒ 8GB 阈值要 1.3h 才动作, 想早兜就压到 3~4GB)。
⚠️ **拉起前先 `sleep 3` 再查残留**: SIGTERM 生效有延迟, 立刻复查会把刚杀的实例判成"还在跑" ⇒ 再起一份,
   两份叠加反而更早撞阈值。判据是"二次复查为空才 Popen"。

## 11. 「帮我装个 X / 一会要用」⇒ 先查已装, 再做就绪核查

**先查, 别先下载**:
```bash
dpkg -s <pkg> | grep -E "^Version|^Status"     # 已装会直接给版本
which <bin>; ls /usr/share/applications | grep -i <名>
apt-cache policy <pkg>                         # 只有 dpkg 来源(无 repo) ⇒ 升级只能下官网 deb
```
国产桌面客户端(会议/微信/飞书这类)在本机**往往早就装过** ⇒ 这类请求的真实内容通常是「启动 + 就绪核查」，不是安装。
起 GUI 应用: `background=true` + `persist_on_release=true`(前景 + `nohup/setsid/&` 会被工具拦)；
复核看**窗口**不看进程: `wmctrl -l` / `xdotool search --name "<标题>"` —— 进程在而窗口没起 = 没成功。

**就绪核查（开会/演示前逐项实测, 每项给数字）**:

| 项 | 命令 | 判据 |
|---|---|---|
| 音频服务 | `pactl info` · `pactl list short sinks` | Server=PulseAudio/PipeWire; 空闲 sink `SUSPENDED` 属正常 |
| 麦克风 | `arecord -D default -f S16_LE -r 16000 -c 1 -d 3 /tmp/mic.wav` + python `wave` 算 peak/RMS | **RMS>60 才算通**; 峰值贴 32767 = 环境太吵, 不是故障 |
| 扬声器 | `speaker-test -t sine -f 440 -l 1 -p 1`(自己结束) · `pactl get-sink-mute @DEFAULT_SINK@` | 能跑完 + 未静音; 别用 `&` 后台(工具会拦) |
| 摄像头 | `v4l2-ctl -d /dev/videoN --all`(看 Card type) · `ffmpeg -f v4l2 -i /dev/videoN -frames:v 1 out.jpg` | 抽到帧 ≥ 十几 KB; 同模组常给多个 `/dev/videoN`(RGB/IR/metadata) |
| 网络 | `curl -s -o /dev/null -w '%{http_code}' https://<服务域>/` | 200 即可达 |

**设备占用冲突（本机最容易误判成"硬件坏了"的一条）**:
生产服务会长期占着 `/dev/video*`(推流/取流), 会议软件再打开同一台 UVC 时**内核允许 open, 但同时只有一个能真正推流**
⇒ 表现就是"会议里摄像头黑屏/打不开"。先取证再下结论:
```bash
sudo fuser -v /dev/video*          # 谁占着
sudo lsof /dev/video*              # 占用者的完整命令行(能看出是哪个工具/哪一路)
```
处置: **报告冲突 + 给让出方案**(在页面里关掉那一格 / 停那一路), 由用户点头 ——
生产推流正被用户盯着看, 不要自己停; 停一路正在推流的相机还会连带让视觉安全闸 fail-closed。

**没有看图工具时可读界面状态**: 截图(`import -window <id> out.png` / `gnome-screenshot -f`) +
`tesseract out.png - -l chi_sim+eng` 抓关键字(登录/扫码/失败/会议号)判断卡在哪一步。
OCR 会把同屏其它窗口的文字一起抓进来 ⇒ 只能说"抓到 X 字样", **不要据此断言确切界面状态**;
截图尺寸 = 整屏分辨率 ⇒ 那个窗口已最大化。

**赶时间时的兜底**: 会议类软件基本都有网页版(浏览器打开 → 加入会议, 输会议号+昵称), 不用装也不用登录 ——
客户端起不来或登录态坏了先给这条, 别让对方卡在安装上。

## Pitfalls
| 坑 | 症状 | 修法 |
|---|---|---|
| 把"有进程"当"在役" | 报"服务正常"但链路其实没数据 | 逐个 `systemctl is-active` + 端口/HTTP 探活, 双证 |
| 用**本机** `ss -ltn` 查**远端**设备端口 (AOI/Orin/工控机) | 远端服务被判 DOWN 而实际是网卡不在位; 本机同名端口在听时又会把远端判成活着 | 判活三件套按序: `ip -br addr` 里真有对应网段(**没有 = 网卡不在位 = 环境缺失, 不是服务故障**) → `ping -c1 -W1 <ip>` → `timeout 3 bash -c 'echo > /dev/tcp/<ip>/<port>'` (或 `curl --max-time`)。本机 `ss` 永远只回答本机, | 报"某设备端口挂了"之前必须已经过了前两步 |
| 只回"待办为空"或只读 cron 的 `last_status` 就下结论 | 用户问"检查任务"拿到一句空的, 或把上一轮 error 当当前故障 | 走 §9h: todo + cron + 端口/探活三处; cron 异常必回读它交付的**产物时间戳**再定性 |
| 探活脚本乱传参数 | 兜底通知脚本把 `--probe` 当**正文**发进群里 | 先 `read` 脚本用法; 别拿"发条测试消息"当探活(会污染群) |
| 清完不复核 | 删了在役权重的旁支文件 | 必扫保护清单 + `find -xtype l` 断链检查 |
| `sudo du` 挂在超大目录 | 命令超时/卡住 | 限定路径 + `timeout`, 别 `du /` 全盘 |
| 汇报 governor"提升 X%" | 单轮先 A 后 B 的顺序效应 | 交错多轮取中位; 带宽瓶颈负载不能用来测频率 |
| 顺手删备份件 | 用户其实还要那份镜像归档 | 备份/归档件**只列不删**, 让用户点头 |
| `ls -l <真源> && python3 -c "解析" \|\| echo "无 <真源>"` | **解析器报错被当成"文件不存在"** —— 把在位的真源报成缺失(实测把在刷的位姿真值误报成"无 latest.json", 据此下了错结论) | 存在性探测与解析**分开写**: `[ -e f ] \|\| echo 缺 f;` 之后单独解析并让失败打印**真实异常**; 断言性结论只能由"读到的内容"下, 不能由 shell 的 `\|\|` 分支下 |
| 用户说"帮我装 X"就直接下安装包 | 装了第二份/版本冲突, 其实早就装过 | 先 `dpkg -s` + `which` + 桌面入口查; 已装 ⇒ 直接启动 + 就绪核查 |
| 拿"进程在"当"应用可用" | 报成功但窗口根本没起 | 复核窗口(`wmctrl -l` / `xdotool search --name`), 不是 `pgrep` |
| 设备被生产服务占着却报"硬件坏了" | 误判摄像头/串口故障 | `sudo fuser -v /dev/*` + `lsof` 找占用者 + `v4l2-ctl -d <dev> --info` 认卡名; 报冲突并请示, 不擅停生产服务; **让出 + 防再占的定式见 `zmax-live-video-stream` 的「显式关闭档」节**(停止服务很可能是白停: cron 守卫每 5 分钟会把它拉回来) |
| 用户说"电脑卡/鼠标延迟"就只查 CPU + 磁盘 | 报"机器不忙、没到瓶颈"却解释不了拖动卡 | 查 `nvidia-smi pmon -c 1 -s u` 的按进程 sm% —— CUDA 常驻吃满时桌面合成只剩个位数 (见 §1b) |
| 用 `ps -eo pcpu` 报"谁在吃 CPU" | 数值是生命周期均值, 刚重启的实例被低估、老进程历史尖峰一直背着 | 采两次 `/proc/<pid>/stat` 的 utime+stime 求增量, 总和换算成核数(见 §1c) |
| 拿后台窗口的 CPU 当优化前后对比 | GUI 在后台不重绘, 同一进程 22% vs 前台 120%, 降幅是假的 | 同一可见页面下前后各采一次; 判据 `xdotool getactivewindow getwindowname`; 拿不到就明说 |
| 整机变慢先怀疑硬件/系统旋钮 | 实际差量是"我反复重启 GUI 攒出的 swap 3.9G" | 先与刚重启时的 load/swap 对账, 再 `swapoff -a && swapon -a` 回收(先验 MemAvailable > swap 已用) |
| load 14 但 CPU 空闲 70%+ 还去查算力 | 实际是断开的流子进程空转 + 每秒数百次 fork/线程创建 | 取 `ss ... CLOSE-WAIT` + `/proc/stat` 的 processes/ctxt 增量(见 §1d); 杀僵尸子进程后给服务端加流时长上限 |
| 老目录整理完又冒出来 | 代码扫干净了却仍重建 `~/<老名>` | 查**仓库外**工具的全局配置(`~/.config/Ultralytics/settings.json` 的 `runs_dir/weights_dir/datasets_dir` 等): 不在仓库里, 五种路径写法全扫不到, 但工具每次都按它落盘 ⇒ 备份后改到工程内 → 把已落错地方的产物**合并回来** → 空目录才 `rmdir`; 判据是"跑一次那个工具看产物落在哪", 不是 grep |
| 停守护只停被守护的进程, 没停 keepalive | 汇报"守护已全部停止", 一分钟后它们全回来了(且正加载模型烧 CPU) | 先 `crontab -l` 找保活/guard 行 → 先停 keepalive 再停守护 → 报告写"会被拉回哪些"(追加型文件 ⇒ 下电无风险) |
| 下电结论只看 `df` 百分比 | 87%/余 51G 看着安全, 10Hz 无轮转 tap 约 25 天就吃满 | 报盘耗增速(MB/千行 · GB/天 · 剩余天数)+ 轮转建议; 百分比给不出"还剩几天" |
| 停完不复核就报"全场静止" | 有个别守护 TERM/KILL 后仍活着 | 逐条复核并列出残留(状态/CPU/是否持写句柄), 「停不掉的」也要写 |
| 用户说"死机了"就顺着认死机 | 电源键触发的干净关机被写成 panic/内核崩溃 | 先取三件套: power key+poweroff 序列 · `fence expiration i915` · `Session logged out`(见 §9d-2), 再定层 |
| 窗口不映射就去重启窗口管理器 | `killall -3 gnome-shell` 把整个会话带走, 外观=整机死机 | 先看应用自己是否 segfault, 只按 pid 杀那个应用; 合成器不动 |

> 📄 2026-09-24 完整实测数字/命令/产出路径: `references/2026-09-24-baseline.md`
