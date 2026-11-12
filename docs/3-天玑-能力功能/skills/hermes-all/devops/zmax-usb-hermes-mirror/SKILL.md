---
name: zmax-usb-hermes-mirror
description: Use when U盘随身镜像/E盘数据盘bind/离家记忆 部署维护排障。静静大脑跨盘架构 (09-06)。
version: 1.0.0
author: hermes-agent
license: private
metadata:
  hermes:
    tags: [zmax, usb, mirror, bind, e-drive, memory-sync]
    related_skills: [e-drive-ubuntu-clone, multi-agent-project-recovery]
---

# Z-MAX U盘随身镜像 — 静静大脑跨盘架构

## When to Use
- 维护/排障 U盘随身镜像、E盘数据盘 bind、离家记忆同步
- U盘离开 E盘后失忆、gateway 起不来、回灌不生效
- 老倪问"U盘/E盘/飞书是不是同一个静静""记忆怎么同步"
- 扩展跨盘共享目录清单(bind 目录变更)

## 触发场景
- U盘离开 E盘(插别的机器/只插U盘开机)后记忆丢失或 gateway 起不来
- 维护/排查 E盘数据盘 bind、随身镜像同步、回家回灌
- 老倪问"U盘/E盘/飞书是不是同一个静静""记忆怎么同步"
- 新增需要跨盘共享的目录(bind 清单扩展)

## 架构一句话
静静(记忆/技能/程序/会话/飞书凭证)= ~/.hermes,唯一权威副本在 E盘 nvme0n1p5(label=ubuntu-e)。
U盘 Live 系统开机 → systemd 自动 bind E盘数据目录(读写直通);U盘还维护一份镜像 /home/ubuntu/.hermes-mirror 在自身持久层(casper-rw),离家时 bind 它当大脑。飞书 gateway 跑在"当前开机的系统"上,读同一份数据 → 三端(CLI-U盘/CLI-E盘/飞书)是同一个静静。

## 组件清单(全部已部署,2026-09-06)
| 组件 | 路径 | 作用 |
|---|---|---|
| 主挂载脚本 | /usr/local/bin/zmax-data-mount.sh (v2, 备份 .bak_*) | E盘身份校验→挂载→回家回灌→bind→后台同步镜像 |
| 兜底脚本 | /usr/local/bin/zmax-hermes-fallback.sh | 无正牌E盘时 bind 镜像 → ~/.hermes |
| 镜像同步脚本 | /usr/local/bin/zmax-hermes-mirror.sh | E盘 .hermes → /home/ubuntu/.hermes-mirror (全量,排除运行态) |
| 主服务 | /etc/systemd/system/zmax-data-mount.service | ConditionPathExists=/dev/nvme0n1p5 触发 |
| 兜底服务 | /etc/systemd/system/zmax-hermes-fallback.service | After=data-mount, enabled |
| 镜像定时 | /etc/systemd/system/zmax-hermes-mirror.{service,timer} | 开机15min + 每6h, Persistent, enabled |
| gateway 顺序 | /etc/systemd/system/hermes-gateway.service | After= 已加 zmax-data-mount + fallback |
| 日志 | /var/log/zmax-data-mount.log, zmax-hermes-fallback.log, zmax-hermes-mirror.log | 各组件运行痕迹 |

## 三种开机场景
1. 主模式(E盘在,label=ubuntu-e):挂载→回灌→bind .hermes/lerobot/Documents/Desktop/Downloads→后台镜像同步
2. 离家模式(无E盘):fallback 检测失败→bind /home/ubuntu/.hermes-mirror → ~/.hermes,记忆全,gateway 照常起
3. 陌生机器(有 nvme0n1p5 但不是 ubuntu-e):身份校验拦截,绝不挂载/写入,fallback 接管 → 安全

## 关键坑(都是实测踩过的)
- **镜像路径是平铺的**:rsync $SRC/ → $MIRROR/ 后,config.yaml 在 /home/ubuntu/.hermes-mirror/config.yaml,不是 .hermes-mirror/.hermes/config.yaml!回灌/fallback 判断都用 $MIRROR/config.yaml
- **身份校验必须有**:原脚本只认设备名 /dev/nvme0n1p5,插到别的笔记本会误挂对方硬盘。校验:blkid -s LABEL -o value == ubuntu-e
- **mirror 同步只在主模式跑**:用 findmnt -no SOURCE ~/.hermes 判断源含 nvme0n1p5,否则 skip(离家时绝不覆盖镜像上的出差增量)
- **防并发**:v1 用 $MIRROR/.syncing 标记文件,但检查+创建非原子 → 开机 nohup(06:33:29)与 timer OnBootSec=15min 同时触发双 rsync,互相 --delete 对方临时文件 → rsync rc=23(报错形如 `stat ".xxx.O8N12Z" failed` + rename 失败),镜像停在旧增量。v2 (09-07) 改 `flock -n /run/lock/zmax-hermes-mirror.lock` 原子锁,拿不到锁 log skip 退出;另加 rc=23 自动 sleep 3 重试一次(gateway 正在写的 .hermes_history 也会造成瞬时 rc=23)。日志出现 ✗与✅同秒 = 双实例跑过的铁证
- **排除项**:gateway.pid/sock/lock、*.log、*.lock、*.pid、logs/、cache/、image_cache/、audio_cache/、tmp/、.cache/
- **记忆文件名是大写**:MEMORY.md / USER.md(不是小写),检查镜像完整性别找错文件名
- **回家回灌只回文本类**:memories skills config.yaml auth.json cron hooks feishu_seen_message_ids.json,rsync -au(镜像新才覆盖,不删 E盘任何东西),在 bind 之前执行
- **gateway 竞态**:gateway Restart=always 能自愈,但已加 After= 排序,避免在空壳 .hermes 上初始化
- **U盘失忆红线**:只带 U盘不插 E盘 = 镜像还在能工作;但镜像若从未同步过(全新U盘)会失忆。离家前确保在家插 E盘开过一次机

## 双机自动同步 (本机主脑, 11-08 落地)
两台同时在网时用这一套；只有 U 盘插回本机才跑的那套 (mirror.timer) 只管"插回去"场景。
- 脚本 `/usr/local/bin/zmax-hermes-usbsync.sh` · unit `zmax-hermes-usbsync.service` (User=ubuntu) · timer `zmax-hermes-usbsync.timer` (开机 5min + 每 10min, Persistent)
- 上行回灌: `memories/` `skills/` `cron/jobs.json` `config.yaml` `auth.json` `channel_directory.json` `feishu_xiaofang.env` → `rsync --update --backup --backup-dir=~/.hermes/sync_bak/<ts>`，**较新者胜、被覆盖的留备份**（留最近 5 份）
- 下行推镜像: 本机 `~/.hermes/` → 远端 `/home/ubuntu/.hermes-mirror/`，全量 `--delete`，排除一律**锚定根** `/logs/ /cache/ /image_cache/ /audio_cache/ /tmp/ /.cache/ /sync_bak/` 与 `/*.log /*.lock /*.pid`
- **state.db 双向都不同步**（两边都在写，合并必撕裂）：会话历史各留各的；要合并会话另做导出导入，别把 2.7G 库放进 rsync
- 探活失败（不在同一 wifi / ssh 不通）就写一行 skip 退出 0，不算故障；日志 `~/.hermes/logs/zmax-usb-sync.log`
- 验收方式: 两侧各写一个 `memories/sync_probe_*.txt` → 跑一轮 → 本地与镜像**都**能看到两个探针 = 双向通；再清掉探针
- 🔴 上行会真的覆盖本机文件（实测一次捞回两侧更新过的两份 SKILL.md，同时把本机旧版打进 `sync_bak/`）；改完技能后看 `sync_bak` 里有没有同名 `.bak.<ts>`，有就是被远端版本盖了，要人工对一下
- 🔴 同步解决不了"双 gateway 抢飞书"：同一条消息落到哪台只在那台落记忆，这是策略问题，不靠文件同步补

## 从 E盘系统手动刷新 U盘镜像(唯一可靠路径, 11-08 实测)
E盘启动(auto-merge 日志只写"数据本盘无需绑定")时**没有任何镜像同步在跑**: zmax-hermes-mirror.sh 只存在于 U盘 casper 层, E盘系统没有它。U盘要离家去另一台机器跑, 必须从 E盘手动刷一遍:
```bash
sudo mount /dev/sda2 /mnt/casper-ro            # casper-rw 的 overlay upper
sudo rsync -aAX --delete \
  --exclude='gateway.pid' --exclude='gateway.sock' --exclude='gateway.lock' \
  --exclude='gateway-starts.log' --exclude='*.log' --exclude='*.lock' --exclude='*.pid' \
  --exclude='logs/' --exclude='cache/' --exclude='image_cache/' \
  --exclude='audio_cache/' --exclude='tmp/' --exclude='.cache/' \
  --exclude='state.db' --exclude='state.db-wal' --exclude='state.db-shm' \
  /home/ubuntu/.hermes/ /mnt/casper-ro/upper/home/ubuntu/.hermes-mirror/
sudo rm -f /mnt/casper-ro/upper/home/ubuntu/.hermes-mirror/state.db-{wal,shm}
python3 -c "import sqlite3;s=sqlite3.connect('file:/home/ubuntu/.hermes/state.db?mode=ro',uri=True);d=sqlite3.connect('/mnt/casper-ro/upper/home/ubuntu/.hermes-mirror/state.db');s.backup(d);d.close()"
sync && sudo umount /mnt/casper-ro
```
- **state.db 必须用 sqlite backup 快照**, 不能 rsync 拷活库(gateway 在写, WAL 会拷出撕裂库)
- 镜像路径 = `upper/home/ubuntu/.hermes-mirror`(casper-rw 里只有 upper/work/lost+found, 镜像在 upper 下)
- rc=24 属正常(cron output/日志轮转时文件消失), 不是失败; 只看 `state.db 快照 rc=0` 和落地后的 md5 抽查
- 验收: config.yaml / auth.json / memories/MEMORY.md / memories/USER.md / cron/jobs.json md5 逐一对齐 + `PRAGMA integrity_check=ok`; jobs.json 是活文件会被 cron ticker 重写, 最后补拷一次
- 镜像不能只放记忆: fallback 是把**整个** mirror bind 成 ~/.hermes, 所以 hermes-agent/bin/node/memories/skills/cron/凭证 都得齐, 否则异机起不来

## 异机运行的坑
- **启动器/运行时必须先对齐, 否则异机必报 `No module named 'pydantic_core._pydantic_core'`**: 真身 = 托管运行时 `~/.hermes/tools/python-3.14.x/` + PM 环境 `~/.hermes/installs/<id>/environments/<id>/venv`(cp314 轮子); 而旧 `hermes-agent/venv` 是 3.11(cp311 轮子)。二者混用 → 包目录找得到、扩展名对不上 → 报这个错。修法: `~/.local/bin/hermes` 必须是 3 行的 73B 版 —— `exec /home/ubuntu/.hermes/hermes-agent/.hermes/bin/hermes "$@"`(老版 159B 指向 venv/bin/python, 必坏)。systemd 网关 unit 的 ExecStart 也改成同一个托管启动器。验证: `hermes doctor` 要显示 `Python 3.14.7 / OpenAI SDK ✓`, 再 `hermes -z "只回答两个字: 就绪"` 真跑一轮模型
- **排除模式必须锚定根目录, 否则会静默挖空包**: 旧写法 `--exclude='cache/'` 匹配任意层同名目录 → 把 `lark_oapi/core/cache/` 整个排掉 → 异机报 `[Feishu] lark-oapi not installed`(包在、子模块没了)。同理 `logs/` `tmp/` 也是。正确写法一律带前导斜杠只锚定顶层: `--exclude='/cache/' --exclude='/logs/' --exclude='/tmp/' --exclude='/image_cache/' --exclude='/audio_cache/' --exclude='/.cache/'`, 文件类 `--exclude='/*.log' --exclude='/*.lock' --exclude='/*.pid'`
- **`*.lock` 不带锚定会咬掉 `hermes-agent/pm/uv.lock`** → 异机每轮刷 `source-update completion failed: pm/uv.lock 不存在` + `install out of sync`。锁排除要用 `--exclude='/*.lock'`(只排根目录), 或显式 `--include='**/uv.lock'` 放在 `--exclude='*.lock'` 前面
- **镜像里的 state.db 2.7G, USB 上首次开机网关要读 2.6G+ 才起来**, 进程处于 D(disk sleep) 属正常, 别当死机
- **双静静**: USB 在另一台机器起 gateway 会与家里/E盘的 gateway 同时连飞书 → 同一条消息两边都答。离家前或异机开机后按需停一侧
- 异机无 192.168.23.x 产线网, cron 里 AOI/推流/建图/4060 那些守护会空跑报错, 不动脑但吵; 需要安静就临时 disable 那几个 job
- 异机上若存在 label=ubuntu-e 的 nvme0n1p5(罕见) → 身份校验通过会误当数据盘, 用前先 `blkid -s LABEL -o value /dev/nvme0n1p5` 确认

## 排障命令
```bash
# 当前模式判定
findmnt -no SOURCE /home/ubuntu/.hermes        # 含 nvme0n1p5=主模式; 无输出/本地=离家? 查下面
mountpoint -q /home/ubuntu/.hermes && echo "已bind"
systemctl status zmax-data-mount zmax-hermes-fallback zmax-hermes-mirror.timer --no-pager
ls /var/log/zmax-*.log                          # 三个日志看最近行为
# 镜像健康
ls /home/ubuntu/.hermes-mirror/config.yaml && du -sh /home/ubuntu/.hermes-mirror
diff <(ls /home/ubuntu/.hermes/memories/) <(ls /home/ubuntu/.hermes-mirror/memories/)
# 手动触发一次镜像同步(主模式下)
sudo systemctl start zmax-hermes-mirror.service
# E盘身份
blkid -s LABEL -o value /dev/nvme0n1p5          # 必须 = ubuntu-e
```

## 验证方法
- 暗号测试:记忆里存一个随机词,离家重启后问,答上=镜像工作正常
- 幂等测试:sudo /usr/local/bin/zmax-data-mount.sh 重跑,不应破坏现状(已 bind 目录会跳过)
- 离家分支无法在 E盘 bind 状态下安全模拟(umount 会切断当前 .hermes)→ 只能真机拔盘验证,逻辑已 review

## 回退
- 主脚本原版: /usr/local/bin/zmax-data-mount.sh.bak_20260906_053717
- 停用离家兜底: sudo systemctl disable --now zmax-hermes-fallback.service
- 停用定时同步: sudo systemctl disable --now zmax-hermes-mirror.timer
