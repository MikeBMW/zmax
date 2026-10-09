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
- 跑长任务前想把机器状态摸一遍(服务在不在、盘够不够、GPU 有没有空转)。
- 磁盘吃紧 → **磁盘红线部分走 skill `disk-redline-guard`**, 本文管"系统层缓存/服务/性能"。

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
局域网设备通常**没有 PTR**(`getent hosts 192.168.x.x` 空 = 正常, 不是故障)。

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
5. **提交纪律**: `git add <显式列文件>`, **默认别用 `git add -A`** (会吸进运行态 churn + 别人的未完成改动)。
   要用 `-A` 得先**三证**: `git status --short` 只剩本轮自己的改动 + 双闸全绿(`repo_guard.py --staged` /
   `secret_scan.py`) + `.gitignore` 已封 `reports/ outputs/ 权重/交付件`。
   暂存后必看 `git diff --cached --stat`, 并对每个文件核大小 (最大应 <1MB; 出现 .pt/.safetensors/视频 → 漏加了 ignore, 先修 .gitignore)。
6. **push + tag**: `git commit` → `git tag vv<X.Y.Z>` (**每版新 tag, 已发布过的 tag 不许移动**) →
   `git push origin <分支>` + `git push origin <tag>` (tag 触发云端 CI 出包, 与本地关机无关, 可以放心打)。
7. **写交接/留档** (两份都要, 都在库里):
   · `reports/关机交接_<日期>.md` — ①关机前状态 (终态/缺口/产物路径/GPU 空闲) ②**开机后需手动恢复的**
     (自启单元里没有的手工进程 —— 如取流服务完整命令行; 远端取流/相机/工控机接口) ③待办优先级 ④本轮代码改动清单。
   · `docs/关机前状态留档_<日期>.md` — 仓库里的**五节**版(**照上一版抄结构**): ①本轮做完的(每条带实证路径)
     ②没做完的(下轮第一件) ③数据清单(表格: 位置/内容, 大件在此登记) ④环境/机器状态(关机前核过的数字:
     磁盘/GPU/单元数/端口/时钟) ⑤**下轮启动顺序**(可直接照抄的 bash 块)。只写"做了什么+根因+证据在哪",
     不复述过程 —— 第④⑤节才是下轮"开机就知道干嘛"的原因。
   **重启后按 §9 逐项核验**；手工进程没自己起来时先读 §10（守护早退），再查服务本身。
8. **收尾核对**: `sync` → `df -h` → `systemctl --failed`(应 0) → `git status --short` (应 0 待推) → `git log --oneline -1`。
9. **清空转进程, 但不碰 GUI**: 起过却没输入的循环进程(外设缺/流断, 如相机不在位时仍 `--loop` 的检测循环)
   要 `kill`, 并在留档"机器状态"里写"已停 pid X"; **控制台 GUI 留给用户自己关**(反复重启 GUI 被投诉过)。

**新增生成物顺手加 .gitignore**: 每次训练动态生成的 `config_*_lora_*.yaml`、
`reports/joint_train_*/` (内含 .pt) 这类必须显式 ignore, 否则下次 `add` 就会把权重拖进库。
临时脚本写在 `/tmp/*.sh` 再跑, 别塞巨型内联命令。

## 9. 重启后核验：链路自愈了没有（用户说「重启了 / 回来了 / 元气恢复」先跑这个）

这类话要的是**最简现状**：哪些自愈了、哪些还缺、缺在哪一层。一条命令跑完只读清点：
```bash
date; uptime
systemctl --failed --no-pager
for s in $(systemctl list-unit-files 'zmax-*' 'aoi-*' --no-pager | awk '/enabled/{print $1}'); do printf '%-28s %s\n' $s $(systemctl is-active $s); done
ss -ltnp | grep -E '8791|8793|8790|8891|8893'      # 8793=工位总览=动作授权唯一入口, 不可省
pgrep -af '<手工进程名>'                            # 自启单元管不到的手工进程(推流/采样/桥)
python3 tools/cam_dev_resolve.py                    # 相机按卡名实测解析(重启后设备号会变)
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
  一次不通就**隔 60~90s 复采一次**再下结论 —— 两次都在位才是真缺失。
- **本机那 5 个手工进程一律走官方复原脚本，别手敲命令行**（幂等，已在跑的不重拉）：
  `bash tools/boot_restore.sh check` 先看清点 → `bash tools/boot_restore.sh local` 补齐
  （cam_live_stream 8791+8793 / l5_live_mark / vl_safety_monitor / l2_daemon / studio）；它自己按
  `tools/cam_dev_resolve.py` 解析相机设备号并在末尾复核 `8793/station→200`。手搓 `cam_live_stream.py` 会写死设备号串线/近黑。
  ⚠️ 它**管不到** `tools/hil_local_api.py`(8795, 手起) 和 MoveIt 单元(`systemctl start zmax-moveit-plan`, oneshot ~3min) ——
  这两个要单独拉，且按 §9e① **单独一条短命令**（跟长动作串在同一条里会被超时一起带走）。
- **「有进程」≠「在役」**：端口没在监听就是没在服务。逐个 `ss -ltnp | grep <端口>` + 一次 HTTP 探活，双证后才敢说「起来了」。
  探活判据要认得**合法拒绝**：闸门不带 `?k=<token>` 给 403、HIL 终端口不带 token 给 403 —— 有响应码就是「在役」，不是故障。
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

## 9c. 自启的反向隧道 `activating`/崩溃循环 = ECS 侧端口被**僵死 sshd** 占着

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
  2026-10-07 实测该故障复现: ECS 侧 `ss -ltnp | grep 1879` 只看到 18793 被一个 sshd 占着(18791 那路客户端已死但口没回收),
  kill 后 + **补上 ECS sshd 保活** (`ClientAliveInterval 30`/`ClientAliveCountMax 3`/`TCPKeepAlive yes` → `sshd -t && systemctl reload ssh`),
  复核本机闸门/公网 200 + POST 403, NRestarts 稳定在 4 不再涨。
- 别自己另起端口写 nginx —— nginx 里 `proxy_pass` 的端口是固定的, 换口等于通道全废。

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

**③ 产线网卡不在位时, 这一批会跟着"合理"地全倒** (不是独立故障, 别逐个当 bug 修):
`ss-remote-tap` 单元 `start-pre` 超时→崩溃循环("No such container") ⇒ 深度格 stalled;
`zmax-proxy`(tinyproxy `Listen 192.168.23.50`) 每 3s 一次 `Could not create listening sockets` 崩溃循环(NRestarts 分钟级+百);
Orin/工控机/珞石位姿真值/arm 取流全 0。判据: `ip -br a` 里没有 `192.168.23.x` + `lsusb` 无 USB 网卡,
**开机 5min 与 10min 两次复采都在** 才算真缺失(§9 的 1~2min 规矩)。网卡插回后这些会各自恢复, 不用手工拉。

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
- **守护进程名唯一时, 最简安全形式是 `pgrep -x <可执行名>`**(只按可执行名精确匹配, 不含参数与路径 ⇒
  不可能命中调用它的那条 shell; `pgrep -f` 才需要 `^...$` 锚定)。实测
  `pgrep -x tinyproxy | while read p; do sudo kill "$p"; done` 一次干净停掉、不再自杀;
  收尾复核"再跑一次应为空 + 端口/探活为准"。
- 同一类坑还有: 内联的长命令会被工具层拦或截断 —— 脚本化写到 `/tmp/*.sh` 再跑。

## Pitfalls
| 坑 | 症状 | 修法 |
|---|---|---|
| 把"有进程"当"在役" | 报"服务正常"但链路其实没数据 | 逐个 `systemctl is-active` + 端口/HTTP 探活, 双证 |
| 探活脚本乱传参数 | 兜底通知脚本把 `--probe` 当**正文**发进群里 | 先 `read` 脚本用法; 别拿"发条测试消息"当探活(会污染群) |
| 清完不复核 | 删了在役权重的旁支文件 | 必扫保护清单 + `find -xtype l` 断链检查 |
| `sudo du` 挂在超大目录 | 命令超时/卡住 | 限定路径 + `timeout`, 别 `du /` 全盘 |
| 汇报 governor"提升 X%" | 单轮先 A 后 B 的顺序效应 | 交错多轮取中位; 带宽瓶颈负载不能用来测频率 |
| 顺手删备份件 | 用户其实还要那份镜像归档 | 备份/归档件**只列不删**, 让用户点头 |
| `ls -l <真源> && python3 -c "解析" \|\| echo "无 <真源>"` | **解析器报错被当成"文件不存在"** —— 把在位的真源报成缺失(实测把在刷的位姿真值误报成"无 latest.json", 据此下了错结论) | 存在性探测与解析**分开写**: `[ -e f ] \|\| echo 缺 f;` 之后单独解析并让失败打印**真实异常**; 断言性结论只能由"读到的内容"下, 不能由 shell 的 `\|\|` 分支下 |
| 老目录整理完又冒出来 | 代码扫干净了却仍重建 `~/<老名>` | 查**仓库外**工具的全局配置(`~/.config/Ultralytics/settings.json` 的 `runs_dir/weights_dir/datasets_dir` 等): 不在仓库里, 五种路径写法全扫不到, 但工具每次都按它落盘 ⇒ 备份后改到工程内 → 把已落错地方的产物**合并回来** → 空目录才 `rmdir`; 判据是"跑一次那个工具看产物落在哪", 不是 grep |

> 📄 2026-09-24 完整实测数字/命令/产出路径: `references/2026-09-24-baseline.md`
