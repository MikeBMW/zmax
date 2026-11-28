---
name: multi-node-sync-hub
description: "Use when 三台以上机器要保持同一套代码/技能, 或装包把 ~/.hermes/skills 擦掉了要合并回来。"
version: 1.0.0
author: Hermes Agent
license: private
metadata:
  hermes:
    tags: [sync, hub, fleet, skills, rsync, manifest]
    related_skills: [zmax-peer-jingjing-sync, cross-host-asset-transfer, linux-host-maintenance]
---

# 多端中枢同步 (hub-and-spoke)

## When to Use

- 用户说「你们要一起同步」「保持同步」，而节点 ≥3(创作源 + 服务站 + 工控机 + 同事的机器)
- 要把某一台刚改的代码/配置铺到其它几台，且以后一直保持一致
- 装完部署包后发现本机技能库数量掉了，要合并回来

三台以上节点(创作源 Windows / 服务站 550C / 工控机 / 同事的 Mac)要保持同一套代码与技能时,
**不要两两互推** —— 定一个中枢, 只有中枢发布, 节点只读 + 上报。两两互推是 N² 条链路,
而且每台都会拿自己的改动去覆盖别人。两节点场景用 `zmax-peer-jingjing-sync` 那套就够。

## 目录形态

```
<hub>:/home/<user>/zmax_sync_hub/
  manifest.txt      同步集(相对仓库根的路径, 一行一个)
  root/             权威副本 —— 只由中枢从主仓库 rsync 进来, 节点绝不写
  state/<node>.md5  各端上报的对账清单(status 的产物)
  skills/           技能副本, 节点只用来「补缺」
  README.md         协议本身(写成对端 agent 能读的说明, 它会自己看)
```

刷新权威副本只在中枢上做:
```bash
cd <主仓库> && rsync -a --files-from=<hub>/manifest.txt ./ <hub>/root/
rsync -a .hermes/skills/ <hub>/skills/
```

## 节点脚本: 四个动作

`status`(逐文件 md5 对比) / `pull`(**默认 dry-run, `-y` 才写盘**) / `report`(上报到 `state/<node>.md5`) / `all`(cron 用)。

铁律:
1. **`pull` 默认只打印差异**, 不加 `-y` 不动文件; 脚本**不删**本地文件(不带 `--delete`)。
2. **cron 只跑 status + report, 绝不自动 pull** —— 否则本地刚改的东西十分钟后被中枢版本静默覆盖。
   漂移追加到 `~/.zmax_sync_drift.log`, 人工看过再 `pull -y`。判据是 `一致=N 不同=0 本机缺=0`。
3. **技能只补缺**: `rsync -a --ignore-existing <hub>/skills/ ~/.hermes/skills/` —— 各端技能库是自己的资产, 永不覆盖。
4. **同步集排除运行态产物**(`cc_snapshot.json` 这类每次自己变的快照): 它会让 status 永远报 DIFF,
   属于"正确差异", 留在清单里等于每轮都在报假漂移。
5. 交付三证: 逐文件 md5 一致 · 本机 git 提交(改动可回滚) · `state/` 里已有本节点文件。

## 分发通道: 借中枢的静态站

中枢一般已经跑着 8888 静态站(nignx root 如 `/home/<user>/zmax_web/console`)。把 `zmax_sync.sh` 和
`README.md` 各 cp 一份进去, 对端一条命令接入:
```bash
curl -s http://<hub>:8888/zmax_sync.sh -o ~/bin/zmax_sync.sh && chmod +x ~/bin/zmax_sync.sh
ZMAX_ROOT=$HOME/<repo> ~/bin/zmax_sync.sh status
```
不用发文件、不用先配 scp、也不要求对方持有中枢的 ssh key —— 但 `status/pull/report` 本身走 rsync over ssh,
所以**真要同步那步仍需要对中枢免密**; 没 key 的节点先让中枢把公钥写进 `authorized_keys`。
验证分发通道: `curl -s -o /dev/null -w '%{http_code} %{size_download}B\n' http://<hub>:8888/zmax_sync.sh` 要 200 且字节数对。

## 写同步脚本本身的两个坑

- 🔴 **`while read` 循环里调 `ssh` 会吃掉剩余行**: ssh 不读 stdin 时会把 heredoc/清单里的后续行吞掉 ⇒
  14 个文件只处理了第一个, 输出 `一致=1` 看着像成功。循环内所有 ssh 加 `-n`; 更好是**一次取回全部**:
  `ssh -n <hub> "cd <hub>/root && xargs -a manifest.txt md5sum"` 落到临时文件, 再本地 grep 比对。
- **md5 命令要探测**: macOS 是 `md5 -q`, Linux 是 `md5sum | cut -d' ' -f1`, 别写死 —— 写 `md5of()` 分支,
  否则脚本跑到 macOS 节点上把所有文件判成 unknown/不同。bash 也要兼容 macOS 自带的 3.2(别用关联数组)。

## 装包会整体替换 `~/.hermes/skills` —— 先合并, 别让它擦库

`curl …/install.sh | bash` 这类部署包打印「技能已装入 ~/.hermes/skills」时, 常常是把整个目录换成包自带那套
(实测一个包用 51 个技能盖掉本机 330 个, 30 个分类掉成 14 个, devops 76→2)。**装完第一件事是数数**:
```bash
find ~/.hermes/skills -name SKILL.md | wc -l
ls -d ~/.hermes/skills.bak.* 2>/dev/null        # 安装器一般留了备份
```
合并(按技能目录名取并集, **同名一律保留本机版**):
1. `cp -a skills.bak.<ts> skills.merge_tmp` —— 以备份为底
2. 遍历现 `skills/` 的每个 `SKILL.md`, **目录名不在备份里**的才 `copytree` 进 merge_tmp(= 包带来的新技能)
3. 同名但内容不同的一律**保留备份版** —— 通用技能(hermes-agent / claude-code 这类)的差异多是版本措辞,
   本机那份才是自己沉淀过的
4. `mv skills skills.installed.<ver> && mv skills.merge_tmp skills`, 再数一遍应为 `旧 + 新增`
5. 旧目录留着当回滚面, 别当场删

判据: 前后 `find … -name SKILL.md | wc -l` 的差 = 新增技能数; 同名被覆盖过的用 `diff SKILL.md` 抽查。
顺手看一眼安装器还动了什么: `crontab -l`、`ls -lt /etc/systemd/system/*.service`、家目录 rc 文件。

## 跨网段时的定责

同步链路走哪条网段要写清楚再报。中枢若同时有产线网口和办公网地址, 从办公网到中枢能通、
而产线网段整段不通时: **同步不受影响, 但位姿/真机链路断了** —— 这两件事要分开报,
别让用户以为"同步成功 = 真机链路也在"。判据只认 `</dev/tcp/` 端口通 + 实际 rsync/scp 成功, 不看 ICMP。
