---
name: systemd-boot-services
description: "Use when 把脚本做成开机自启/常驻服务, 或 unit 起不来要排查。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [systemd, boot, autostart, service, sysctl, verification, linux]
    related_skills: [linux-host-maintenance, linux-network-perf-boot, zmax-console]
---

# 把本机能力落地成"开机就跑 / 常驻"的服务 (落地 + 核验 + 坑)

## When to Use
- 用户说"以后每次开机都要做 X / 做成常驻 / 开机自启 / 加个服务"。
- 要把一次性的脚本(优化、监听、采集、推图、巡检)变成**不需要人记得跑**的东西。
- 服务起不来、日志是空的、`systemctl start` 没反应 —— 排查口径见 §4/§5。

## 1. 先选形态 (别把一次性的事做成常驻, 也别把常驻的事塞进开机脚本)
| 需求 | 形态 | 说明 |
|---|---|---|
| 内核参数/网络旋钮 | `/etc/sysctl.d/99-<名>.conf` | systemd-sysctl 开机自动应用, **不用写 unit**; 文件里写清"为什么留这条" |
| 开机跑一次就完(优化/预热/体检/台账) | unit `Type=oneshot` + `RemainAfterExit=yes` | `WantedBy=multi-user.target`, `After=network-online.target` |
| 长期在跑(监听/推流/守护) | unit `Type=simple` + `Restart=always` + `RestartSec=10` | 例子: AOI 裁减图实时推飞书 |
| 需要桌面/窗口/X 会话 | unit `Type=simple` + `Restart=no` | **GUI 只人工启动** (用户明确口径, 见 §5); 开机拉起用一次性启动脚本 + 存活盯, 不靠 Restart |

## 2. 三件套 (幂等, 可回滚)
```
/etc/sysctl.d/99-<名>.conf          # 只有内核参数才需要
<repo>/tools/<名>.sh                # 真逻辑: 应用 + 断言生效值 + 体检 + 落台账; 支持 --quick 等开关
/etc/systemd/system/<名>.service    # 薄壳: 只 ExecStart 调脚本, 不写业务逻辑
```
- **单一真源**: `ExecStart` 指向**仓库里的脚本**(git 可追溯)。不要再拷一份到 `/usr/local/bin` —— 两份副本必然漂移; 真要部署副本, 就在技能里写明"改完要重跑安装器"。
- 安装器做成脚本(可重复跑): `install -m644` / `install -m755` → `systemctl daemon-reload` → `enable --now` → **语法预检 `bash -n`** → 打印 `is-enabled/is-active`。
- 回滚一条命令写进 SKILL.md 交付说明: `systemctl disable --now X && rm /etc/sysctl.d/99-X.conf && sysctl --system`。

## 3. 核验 = 四件事都要有 (缺一件就是"看起来起了")
```bash
systemctl is-enabled <name>.service      # 开机会不会自动跑
systemctl is-active  <name>.service      # 现在活着吗
sudo tail -5 /var/log/<name>.log         # 它自己说了什么 (不是"我以为")
journalctl -u <name>.service -n 20 --no-pager   # 起不来时的真原因
ls -lt <repo>/reports/<名>_*.jsonl       # 真产物: 每跑一次追加一行台账
```
**手工复跑必须走同一代码路径**(`systemctl restart <name>` 而不是手动 `bash 脚本`)—— 否则你验证的不是开机那条路。
一键核验: `scripts/verify_service.sh <unit名> [日志路径] [台账glob]`。

## 4. Pitfalls (全是实测踩过的)
| 坑 | 症状 | 修法 |
|---|---|---|
| 脚本没有可执行位 | unit `status=203/EXEC`, 无日志 | `chmod 755 <脚本>` (write_file 落地默认不是 +x) |
| `RemainAfterExit=yes` 时 `start` 不重跑 | 改了脚本, `systemctl start` 却没有任何新日志 | 用 `systemctl restart` |
| Python 输出被缓冲 | 日志文件**空的**, 但进程明明在跑 | unit 里 `Environment=PYTHONUNBUFFERED=1` (print/watch 型脚本必须) |
| 日志不知道去哪 | `journalctl` 里没有业务输出 | 显式 `StandardOutput=append:/var/log/<名>.log` + `StandardError=append:...` |
| 开机竞态 | unit 起来了但网还没好, 首轮全失败 | `After=network-online.target` + `Wants=network-online.target`, 脚本内每步带超时且失败不阻塞开机 |
| 失败拖死开机 | 机器卡在启动 | oneshot 脚本只做"尽力而为"(`|| true` + 单项超时), 用 `SuccessExitStatus=0 1` 兜住非致命退出 |
| GUI 被"自动重启"骚扰 | 关掉窗口 5s 又弹回来 | GUI unit 一律 `Restart=no` (用户 2026-09-17 定档: 控制台只人工启动) |
| 改完 sysctl 不核验 | 以为生效 | 脚本里改完立刻 `sysctl -n` 打印真值, 并写进台账 |
| 目标路径写死机器名/临时目录 | 换机器就崩 | 路径全部绝对且来自仓库根 |
| **常驻守护的真逻辑放 `/tmp`** | 重启/清理后脚本与进程一起没了, 下游数据**静默冻结**很久才被发现 | 常驻逻辑一律进**仓库 + unit**(`ExecStart` 指仓库路径); `/tmp` 只准放一次性临时脚本, 且仓库留档一份 |
| **unit 里写死了命令行开关** | 改了脚本默认值, 重启后行为**没变** | `ExecStart` 的参数**覆盖**脚本默认值 ⇒ 改前先 `grep` 单元里那个开关, 改**单元** + `daemon-reload` + `restart`; 只改代码默认值等于没改。**同类但更隐蔽的一种: 单元带 `Restart=always`** ⇒ 杀掉那个散跑的裸进程**不会换档**, systemd 立刻按 `ExecStart` 把旧档拉回来(观感=「改完开关重启后行为没变」, `ps` 里新进程 ppid=1 像什么都没发生)。换档唯一路径 = 改单元文件 → `daemon-reload` → `restart`；仓库模板 `<repo>/tools/systemd/<unit>` 与已安装的 `/etc/systemd/system/<unit>` 是**两份**, 先 `diff -q` 再一起改, 否则改了模板而真正生效的是旧安装件。**`Environment=` 里的变量值是同一个病**: 只改文件 + `restart` 不生效 —— `Restart=always` 会拿**内存里的旧 Environment** 把进程拉回来, 现象与"改了没生效"一模一样。判据必须读 `/proc/<pid>/environ` 里那一项的值(`tr '\0' '\n' < /proc/<pid>/environ | grep '^KEY='`), **不是看 unit 文件**; 对不上就是漏了 `daemon-reload`。同理, 下游脚本自己的 `export` 优先级可能高于单元 —— 三处(启动脚本 / unit / 代码缺省)同口径才对 |
| **依赖写成 `Requires=`** | 重启被依赖方会**连带重启**依赖方 | `Requires=` 是双向生命线(停/重启都传播)。若依赖方的"身份"是**启动时才生成**的(内网穿透的公网 URL、会话级地址/端口、一次性 token), 硬依赖会把它换掉 ⇒ 已发出去的链接、已烧进客户端的地址**全部失效**。定式: 用 `Wants=`(软依赖), 只有确实要"被依赖方死了我也停"时才用 `Requires=`。排查症状: 服务全 `active`、本地直连正常、而**经中间那条链路稳定失败** |
| **停掉一个被守护驱动的负载时只调了它自己的 API** | 停完几秒它自己又回来了(`on=true`、fps 恢复), 看上去"停不掉/自己重启" | 那类负载常由**另一个 unit 定期 `POST /start` 拉起**。定式 = `systemctl stop+disable <驱动 unit>` → 再停进程内的任务 → **间隔 ≥3s 连查 3 次**状态都是停的才算停; 只看一次 stop 的返回体就报"已停"必翻车(先 `systemctl list-units | grep -i <关键字>` 把驱动找出来) |
| 用 `ps -o pcpu` 判断"谁在抢 CPU" | 早已空转的进程仍显示 130%+, 结论整个反过来 | `ps` 的 `%CPU` 是**进程生命周期均值**, 不是瞬时值 ⇒ 换成 `uptime` 的 load、`top -bn1 | head`、或服务自己 `/health` 的 duty/fps; 报告里别拿均值当"现在在吃" |
| 只测一条链路就下结论 | 本地 ok / 经代理失败 | 本地与服务状态都绿时, **先查中间层自己的状态**(隧道日志里的当前 URL、代理日志里的拒绝原因)——中间层会自己换地址/自己拒绝, 不是被服务的错 |
| **见到 `failed (Result: timeout)` 就赶紧重启** | 其实活已经干完了, 重启白折腾还把在跑的东西拆掉; 或反过来把 failed 当成"服务挂了"报给用户 | 超时判 failed ≠ 没干成: 长链 oneshot(起容器 + `docker exec` 拉常驻进程 + `systemctl restart` 别的单元)最容易在**最后一步**撞 start 超时被 TERM, 而前面几步的产物全在。先取证真实产物 `docker ps` + `docker exec <容器> ps -eo pid,etime,cmd \| grep <目标进程>`, 在跑 ⇒ 只 `sudo systemctl reset-failed <unit>` 清状态即可(**reset-failed 不重启任何东西**)。报"单元全绿/没有故障"之前也要跑这一步, 否则会把清理态当故障、或把 failed 当成已修 |

## 4b. 在别人的设备上装 unit: 本体放项目隐藏目录, `/etc` 只放软链

用户要求「不要在 X 上新建文件, 所有文件都放项目那一个隐藏目录」时, 仍能正经开自启:

```bash
# 脚本 + unit 本体全在那个隐藏目录 (例: /home/<user>/.zmax/{rs,systemd,logs})
sudo systemctl link /home/<user>/.zmax/systemd/<svc>.service    # /etc/systemd/system/ 下只生成一个 symlink
sudo systemctl enable --now <svc>.service
ls -l /etc/systemd/system/<svc>.service                        # 确认是 → .zmax/... 的链接, 不是拷贝
```

- `systemctl link` + `enable` = 开机会起 (`multi-user.target.wants/` 里出现链接), 而实体文件不在系统目录 ——
  满足"单一路径"要求; **报告时把这条说清楚** (systemd 强制要求在 `/etc/systemd/system` 有个入口, 软链不算放文件)。
- 🔴 **`is-enabled` 回 `linked` 不等于开机会起**: `linked` 只表示 unit 文件是软链、**还没装进 `*.wants/`**,
  这种单元 `is-active` 会一直是 `inactive`, 而 `list-unit-files` 里却能看到它 —— 极易被当成"服务存在, 只是暂时停了"。
  实测一个相机发布件就这样 12 小时没人拉, 下游“采集链”一直拿旧帧。定式三连:
  `is-enabled` 要 `enabled`(**不是** `linked/disabled`) + `is-active` 要 `active` + `ls /etc/systemd/system/multi-user.target.wants/ | grep <svc>` 有链接;
  修法 = `systemctl link` 之后再 `systemctl enable --now <svc>`(link 自己不会 enable)。
- **没有上游就不空转用 `Requires=`**: 汇总/转发类服务 `Requires=<数据源服务>` + `After=`, 源死它也停
  (实测 D405 发布件被 kill 时, 转发件跟着停, 不会挂着个 8792 回空)。
- 🔴 **`systemctl disable` 一个 `link` 进来的单元会删掉 `/etc` 里那条软链**(实体在隐藏目录里没丢, 但
  `/etc/systemd/system/<svc>.service` 不见了, 之后 `is-enabled` 直接报 `No such file or directory`, 很像"unit 被删了")。
  两个互斥单元要换档时定式 = `systemctl stop <旧的>`(需要彻底禁就 `disable`, 但先 `cp` 一份内容) →
  `link` 新的 → `daemon-reload` → `enable --now` → `ls -l /etc/systemd/system/<svc>.service` 确认是链接。
- 🔴 **独占设备的服务换档要先"放设备"**: 相像这类独占 USB 设备的发布件, 只 `kill` 进程没用 ——
  `Restart=always` 会把它拉回来抢设备; 新进程当场报 `Input/output error`(errno=5)。定式 = `systemctl stop`
  → 等 **10~12s** 设备释放(必要时 `sudo fuser -v /dev/video*` 看还有谁占着) → 再起新件。
- 🔴 **用密码喂 `sudo` 时, 不要把 heredoc 和 `printf <pw> | sudo -S` 写在同一句**: 两者的 stdin 会打架,
  heredoc 的内容根本进不了 `tee`, 而密码被当成文件内容写进去(实测 unit 文件里只剩 `ts123`)。
  定式 = 以目标用户用 heredoc 写文件 → `sudo` 只用于 `systemctl link`/`daemon-reload`/`restart`;
  写完后 `cat` 回读文件头两行验明没写错东西。
- 🔴 **一条命令里每个 `sudo` 都要带 `-S`，漏一个就静默不写**: 非交互 ssh 下 `sudo tee`/`sudo mkdir`/`sudo cp` 报
  `sudo: a terminal is required to read the password`；若它排在 `;`/`&&` 链中间，**文件根本没写成，而后面那句
  `printf pw | sudo -S systemctl restart` 照样成功** ⇒ 服务拿**旧配置**重启了，现象与“改了没生效”一模一样。
  判据: 重启后**回读落盘文件**(`cat` 那个 drop-in) + 看进程真实生效值(`systemctl show -p Environment` 或
  `/proc/<pid>/environ`)；更快的旁证 = **服务自己的报错文案里还是旧参数**(实测仍报打不开 `/dev/video2`，而目标是 video3)。
  另: drop-in 目录 `…service.d/` 不存在时 `tee` 同样失败 ⇒ 先 `mkdir -p` 再用 `sudo -S` 写。
- **自愈要当场验**, 不要只写 `Restart=always`: `pkill -f '<脚本>'` → `sleep 6` → `systemctl is-active` +
  端口 `curl` 回 200 + 新 pid 存活 = 真自愈。不能重启整机验开机时, 用 `is-enabled` + `wants/` 链接存在作开机证据。
- **目标机刚重启过、原来那套栈没自启时, 先量三样再动手**: `ros2 topic list | wc -l` (=0 就是没发布者)、
  `ss -ltn | grep <端口>`、`systemctl list-units | grep -i <关键字>`。别急着改自己的消费者代码。
- **缺发布者时用直采补件, 别去装 ROS 包**: 相机这类用 `pyrealsense2` 直采 + `sensor_msgs/Image` 发到原话题名
  (20 行脚本, 与原有转发件同住隐藏目录), 再用 `lsusb` 确认硬件在位 (例 `8086:0b5b` = Intel RealSense)。
  注意 `python3 -c 'import rclpy'` 要 source 过 ROS 才通; 找不到 `realsense2_camera` 包是常态, 不影响这条路。

## 4c. 「看着在重启」时先读**退出码**, 它直接告诉你是哪一类病

`systemctl is-active` 只会说 `activating (auto-restart)` —— 但这一个态对应好几种完全不同的病因,
`systemctl status -n 3` 那行 `(code=exited, status=NNN/XXX)` 才是证据:

| 退出码 | 真因 | 修法 |
|---|---|---|
| `209/STDOUT` | systemd **打不开 `StandardOutput=append:<路径>`** (父目录不存在/无权限) | 先 `mkdir -p` 那个日志目录再 `restart`。注意: 这时日志文件里**一个字都没有**, 应用自己的报错根本不会出现 —— 别去代码里找 bug |
| `1/FAILURE` + 日志只有一行 fail-closed 提示 | 脚本自己拒跑: 常见是**secrets 文件在这台机上压根不存在**(新迁过来的机器只同步了 unit, 没同步 `zmax_data/secrets/`), 而 unit 的 `Environment=` 只带了间隔/token 以外的参数 | `mkdir -p <repo>/zmax_data/secrets && umask 077` 写文件 → `chmod 600` → `restart`; token 值从原机 secrets 里取, **不要写进 unit 正文**(会漏进日志与 git) |
| `1/FAILURE` + 日志尾部 `OSError: [Errno 98] Address already in use` | **两个 unit 的 `ExecStart` 一模一样**，先起的那个已占端口 ⇒ 后起的永远绑不上，`NRestarts` 能涨到几千。现象不仅是“服务挂了”：依赖它的页面/按钮**也一起没响应**（请求落在刚起/刚死的进程上） | `systemctl cat A B \| grep ExecStart` 对比 + `ss -ltnp \| grep :<port>` 看是哪个 unit 在听 ⇒ `systemctl disable --now` 掉重复的那个。journal 里只有 `Started …` / `status=1/FAILURE`，**真因只在 unit 自己 `StandardOutput=append:` 那个文件尾部** |
| `203/EXEC` | 脚本无可执行位 / 路径不存在 | `chmod 755`, 或看 unit 里路径是否指向旧 checkout |
| `255` | 隧道类 unit: 远端拒绝/端口被占 | 见 §7 |
| `75` + `RestartForceExitStatus=75` + 每 5s 一轮 | **user 与 system 两个作用域装了同名 unit**, user 那个一启动就 exit 75, 而 `RestartForceExitStatus` 把它当"需要重启的退出"⇒ 无限重启, `NRestarts` 涨到几十、每轮烧 1s+ CPU, 而真正的服务在 system 作用域里好好跑着 | `systemctl --user list-units \| grep <名>` + `systemctl list-units \| grep <名>` 两边都查(**只看一边会以为它坏了/好了**); 保留在跑的那个作用域, 卸掉另一个(`systemctl --user disable --now` / 卸载命令), 卸完确认 `--user` 侧 `inactive` 且**原 pid 未变** |

验收固定三样, 缺一不算修好: `is-active` = `active` · `NRestarts` 隔 20s 两次**不涨** · 日志末尾出现业务自带的那行成功提示
(例: `📡 实况推送 → https://<domain>/xxx.php (每 1.0s)`)。只看到 `active` 就报“修好了”会在下一轮重启时打回原形。

### 跨 Python 版本往远端 venv 补包 (实测坑)

远端 venv 与手边解释器版本不一致时, **不能拷 site-packages** —— 带编译产物的包(如 `cyclonedds`)是 `cp3XX` ABI 绑定的,
`3.11` 拷到 `3.12` 只会 `ModuleNotFoundError`, 看起来像“装了但没生效”。也不要指望远端能上 PyPI(内网常被禁)。
定式 = 在手边机器上**下载目标版本 + 目标平台的 wheel**, 再离线装到远端:
```bash
# 远端: python3 -V 拿到 3.12 → 手边下载 cp312 / manylinux2014_x86_64
python3 -m pip download <pkg> -d /tmp/w --no-deps --only-binary :all: \
  --python-version 3.12 --platform manylinux2014_x86_64 --implementation cp --abi cp312
scp /tmp/w/*.whl <远端>:/tmp/
# 远端: 用**目标 venv 自己的 pip** 离线装, 再用“导入 + 建对象”验, 不看 pip 退出码
<venv>/bin/pip install -q --no-index /tmp/<pkg>-*.whl
<venv>/bin/python -c "from cyclonedds.domain import DomainParticipant; print('ok')"
```
装之前先确认那个 venv 的版本 (`<venv>/bin/python -V`) —— 猜错 ABI 只会得到一样的 `ModuleNotFoundError`。

🔴 **不要逐包 `--no-deps` 扒**: 那样拿到的只是你点名的那几个包, 依赖闭包(以及包之间的版本约束)全靠猜,
实测会撞 `Could not find a version that satisfies the requirement huggingface-hub<2.0,>=1.5.0` 这类错 ——
因为手边缓存的 hub 版本是新的, 而旧 `transformers` 不许。定式: **整条闭包一起下**(不加 `--no-deps`, 只加目标版本/平台/abi),
让 pip 按**目标解释器**求解一遍:
```bash
pip download --only-binary :all: --python-version 3.12 --implementation cp --abi cp312 -d /tmp/w transformers
# 目标机: pip install --no-index --find-links /tmp/w transformers
```
验收不能只看安装退出码: `python -c 'import <包>; print(<入口类>)'` + 真实用一次(如从本地目录 `local_files_only` 加载权重)都要过。

## 5. 交付口径 (用户拿它当结果看)
- 报告只写四样: **磁盘上的文件路径** · **`is-enabled/is-active` 真值** · **日志/台账一行真输出** · **回滚一条命令**。
- 不许写"已配置完成/已优化"而无数字; 未实测的东西标明"未证明"。
- 需要每次开机都跑的东西, 明确回答"重启后会不会自动跑"(=is-enabled), 而不是"我手动跑过了"。

## 6. 非 systemd 的目标机 (Windows 工控机/产线设备)
同口径落到**计划任务**: 开机常驻 = `/sc onstart /ru SYSTEM /rl highest`, 分钟级保活/自愈 = `/sc minute /mo 1`;
脚本用纯 ASCII (PS 5.1 读无 BOM 的 UTF-8 会把中文解析成乱码), 启动一律 `WScript.Shell.Run("cmd /c cd /d <dir> && <python> <脚本> > <日志> 2>&1", 0, $false)` 分离启动。
看门狗/独占设备/无人升级的完整口径见 `references/production-device-service-pattern.md`。

## 常驻脚本在 agent 会话里起的坑 (2026-09-27 实测)

- **别用 `grep` / `pkill -f` 匹配自己的命令行**：`for p in /proc/*; do grep -q "<脚本名>" ...; done` 会匹配到**执行这条命令的 shell 自身**(argv 里就含那个串) ⇒ 把自己 kill 掉(exit -15)。
  `pkill -f 'ssh.*<端口>'` 同样会自杀——命令行里就写着那个端口号, 它会先杀掉自己所在的 shell(SIGTERM)。
  修法①判据写拼接串(`P="vl_safety""_monitor.py"`)；修法②把循环/kill 放进**独立脚本文件**再执行(它的 argv 只有路径)。
  🔴 **"操作成功一半、工具报被自己 SIGTERM"时先怀疑自杀式匹配, 不要以为服务真挂了。**
- 🔴 **反方向也会错: 模式串对不上真 argv ⇒ 假阴性**(判活脚本报「没有 X 进程」, 而 `systemctl is-active` 明明是 `active`)。
  wrapper 类服务(Python CLI、`python -I -c runpy…` 启动器、带 venv 前缀的入口)的真实 argv 与业务名不一致,
  `pgrep -af '<业务名>'` 一个都匹配不到。定式: 先用 `systemctl show -p MainPID` 或 pidfile 拿 pid,
  再 `tr '\0' ' ' < /proc/<pid>/cmdline` 取**一次真 argv** 才写模式; 日常判活优先 `is-active` / 端口 / pidfile,
  不要用 `pgrep -f <业务名>` 当唯一判据。

## 7. `ssh -R` 反向隧道做 unit: 两个必踩的坑

把内网服务/另一台机器暴露出去时, `ssh -R` 隧道写成 unit 有两个坑会让你以为"密钥不行"或"服务起不来":

| 坑 | 症状 | 修法 |
|---|---|---|
| **`ssh -N` 不会 fork** | `Type=simple` 下长驻前台进程被判启动异常, `status=9/KILL` 反复重试(前面几轮可能还夹着别的错) | `Type=forking` + 命令行加 `-f`(`-f -N`), 让 ssh 自己后台化 |
| **systemd 访不到 ssh-agent** | 你在 shell 里 `ssh root@host` 能免密, unit 里却 `Permission denied (publickey)` | 登录 shell 能连很可能**只是 agent 里有一把合适的 key**, 而 `~/.ssh/id_rsa`/`id_ed25519` **根本不在对端 authorized_keys 里**(用 `-i <那把>` + `IdentitiesOnly=yes` 手测就会再现失败)。正解: `ssh-keygen -t ed25519 -f ~/.ssh/id_<用途> -N ''` 生成专用密钥 → 追到对端 `authorized_keys` → unit 里 `-i` 显式指它。不要依赖 agent |

| **对端端口有监听 ≠ 隧道活着** | 对端 `ss -ltn` 能看到 `0.0.0.0:<port>` 在听, 从外面连却只拿到半开连接/超时; unit 一 `restart` 就 `status=255` 秒退 | 那个监听是**上一条隧道死掉后留下的 sshd 转发残骸**, 新连接被 `ExitOnForwardFailure=yes` 直接劝退。判活要打**真协议**(`exec 3<>/dev/tcp/<IP>/<port>; head -c 40 <&3` 看 SSH banner, 或 `curl` 看 HTTP 码), 不能只看 `ss`。修法: 对端 `ss -ltnp \| grep :<port>` 找 pid 清掉 → 再 `restart` 本机 unit; 起完核 `is-enabled`(常见 `active` 但 `disabled`, 重启后不恢复) |

别的必备项(同样实测): `Environment=HOME=/home/<user>`(systemd 下 HOME 与登录 shell 不同),
`ServerAliveInterval=20 ServerAliveCountMax=3`(不掉长连接)、`ExitOnForwardFailure=yes`(端口被占就别假装成功)、
`Restart=always` + `RestartSec=10`。

🔴 **隧道 unit 的 `ExecStart` 写死远端地址 ⇒ 改 ssh 别名救不了它**:
症状: `ssh <别名>` 手测通、unit `is-active` 绿, 但**本地转发端口 closed**; `journalctl` 里是
`Timeout, server <旧IP> not responding` → `status=255` + Restart 循环。
根因: unit 里写的是 `-p <旧端口> user@<旧网关IP>`, 与 `~/.ssh/config` 的别名是**两条独立路径**。
定式:
1. 隧道 unit 一律写**直连目标** + 显式密钥, 不写别名:
   `ExecStart=/usr/bin/ssh -NT -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 -o StrictHostKeyChecking=no \
      -i /home/<user>/.ssh/id_ed25519 -L <本地端口>:127.0.0.1:<远端端口> user@<直连IP>`(加 `User=` 明确跑的用户)。
2. 换链路时先 `systemctl cat <unit>` 看 ExecStart 到底指向谁 —— 别假设它跟着 ssh config 走。
3. **验收用端口不听服务**: `for p in 19061 8792 8816; do (echo > /dev/tcp/127.0.0.1/$p) 2>/dev/null && echo "$p open" || echo "$p closed"; done`。
   一条链路常摊成 3~4 个隧道 unit(位姿/相机/推流各一个), 逐个验; **`is-active` 全绿而端口全 closed 是常态**。
4. 公网跳板只做**兜底别名**(`Host <名字>-ecs` 指向公网 IP+端口), 主别名叫直连内网 IP ⇒ 中间层挂掉不拖垮内网链路。

🔴 **手测成功≠unit 会成功**: 三者环境不同(HOME / agent / PATH)。失败先看 `journalctl -u <unit> -n 20` 里
究竟是 `Permission denied`(密钥) 还是 `9/KILL`(进程模型), 两种错治法完全不同 —— 别一上来就改密钥。

远端端口诊断顺序与"安全组 vs 本机防火墙"的判定, 见 `references/reverse-tunnel-diagnosis.md`。
- **agent 会话里 `nohup/setsid ... &` 起的常驻进程会随会话清理一起死**(终端工具也直接拒这类包装)：要用 `background=true` 交给 Hermes，或交给 **cron keepalive 每分钟探测+拉起**才算真脱离会话。
- 🔴 **经 paramiko `exec_command` 起后台进程会把通道挂到超时, 而超时不等于没起**: `setsid nohup bash run.sh > log 2>&1 &`
  照样 `PipeTimeout` —— `exec_command` 等的是**通道关闭**, 只要子进程继承了 stdout/stderr 就会把通道顶住(实测两次各挂 40s+)。
  三重修法: ① 三个 fd 全重定向 `> log 2>&1 < /dev/null` 并 `& disown`; ② **启动与核查拆成两次调用**,
  第二次才 `ps -eo pid,etime,cmd | grep <脚本> | grep -v grep` + 数产物行数; ③ 常驻的根本别用 nohup ——
  落成 unit 后启动就一句 `systemctl restart`(立即返回)。
  判据: 本次超时但下一次 `ps` 里进程在、产物在增长 ⇒ **当成起成功了**, 别再起第二份(两进程抢设备/日志交错, 比没起更难排)。
- **改完代码必须重启进程**：长驻守护跑的是内存里的旧代码 —— 本轮磁盘上改了 `timeout`/常量但没重启，误报又持续 2 小时。核验要对比 `ps` 启动时间 vs 文件 mtime。

## 支持文件
- `templates/unit-oneshot.service` — 开机一次性场景的 unit 骨架(含超时/台账注释)
- `templates/unit-daemon.service` — 常驻监听场景的 unit 骨架(PYTHONUNBUFFERED + Restart=always)
- `scripts/verify_service.sh` — 一键四件套核验
- `references/local-units.md` — 本机(4060 工位机)已落地的 unit 清单与各自口径
- `references/production-device-service-pattern.md` — 在别人的产线设备上放常驻服务: 硬约束/部署清单 + **看门狗指纹、独占设备去重、无人升级验收、版本取证**
- `references/self-exiting-service-chains.md` — 「自己会退」的常驻链(定时 `--seconds` · 跨 `docker exec` · 页面按钮打另一个端口): 必须托管 + 心跳可视 + 删除/清除按钮的真实语义 + 四步自检
- `references/reverse-tunnel-diagnosis.md` — 「外面连不进来」五层定位(监听 vs 本地通 vs ufw vs **云安全组**) + 安全组不可改时的 `ssh -R` + nginx 80/443 反代方案 + nginx 反代四坑 + 动手前盘点已有隧道
