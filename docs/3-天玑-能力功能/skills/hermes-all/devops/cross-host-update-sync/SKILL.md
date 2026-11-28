---
name: cross-host-update-sync
description: "Use when 一台机器改了功能要同步到另一台(增量清单·不改无关项·技能库合并)。"
version: 1.0.0
author: Hermes Agent
license: MIT
tags: [sync, rsync, ssh, incremental, skills, zmax]
platforms: [linux]
metadata:
  hermes:
    tags: [sync, rsync, ssh, incremental, skills, zmax]
    related_skills: [zmax-peer-jingjing-sync, zmax-agent-sync, cross-host-asset-transfer, zmax-engineering-repo]
---

# 跨机增量同步: 别人在另一台机上改了功能

## When to Use
- 老倪说「刚才在 windows/另一台机更新了很多功能, 通过 X 全面同步」。
- 要判断「哪几台机之间能通」而不是猜某台机器挂了。
- 要拉一个**大型工程树里的几十个文件**, 而不是整树镜像。
- 同步回来的资产包含 `~/.hermes/skills`, 而安装脚本是替换语义。

## 0. 铁律
1. **先只读摸链路, 再决定拉什么。** 产线口不通 ≠ 机器失联 —— 换 corp/办公网地址再试一次, 结论完全不同。
2. **不整树拉。** 几十 G 的工程根里找「最近改的文件」用 mtime, 不用 diff 全量。
3. **同步前先读源侧的改动记录(CHANGELOG)**, 里面「不要互相覆盖」的清单是硬约束: 同名不同物的文件盖了不会报错, 只会让服务行为悄悄变。
4. **判据是内容对齐(md5 + 语法解析), 不是 rsync 的退出码。**
5. **`git status` 看不到的 ≠ 没落地** —— 仓库 `.gitignore` 常挡 `config/`, 用 mtime + 解析判落地。

## 1. 找地址: 从它自己发的 URL 反推

机器自报的下载/服务 URL 里就是它的地址(如 `install.sh` 打印的 `来源 : http://<IP>:8888`, 或服务站首页里的直连链接)。
拿到后一条命令认身份: `ssh <user>@<IP> 'hostname; ls'` —— 立刻返回即通。

广扫网段只在地址完全未知时做: 扫 22 端口, 逐台 `hostname` 认身份(比 ping 可靠 —— ICMP 常被设备禁而 SSH 开着)。

排查顺序(每次先排除一层):

| 探针 | 结论 |
|---|---|
| `ip -br addr` 里有没有 UP 的有线口 | 没有 ⇒ 产线网整体不可达, 换 WiFi/corp 地址 |
| `ssh -o ConnectTimeout=6 <host>` | 通 ⇒ 直接用, 不要绕跳板 |
| 目标服务端口 `/dev/tcp/<h>/<p>` | 只有 22 开 = 只能 ssh, 不能 HTTP 拉包 |

## 2. 找增量: mtime 窗口 + 分类

```bash
find <远端工程根> -newermt "-36 hours" -type f \
  \( -name '*.py' -o -name '*.js' -o -name '*.json' -o -name '*.sh' -o -name '*.md' -o -name '*.html' \) \
  -not -path '*/.hermes/*' -not -path '*/node_modules/*' -not -path '*/data/*' \
  -not -path '*/zmax_data/*' -not -path '*/__pycache__/*' -not -path '*/logs/*' -not -path '*/.git/*' \
  | sed 's|<远端工程根>/||' | sort
```

判读两条, 决定拉多少:
- 命中里**技能/文档占绝大多数** ⇒ 这次是「配置/技能型」更新, 代码几个文件而已(实测 79 命中里非 `.hermes` 只有 19 个)。
- 命中里**源码成片** ⇒ 先看版本号文件与 `git log`, 可能只是别人整树重新落盘, 真改的没几个。

## 3. 拉: rsync --files-from 精确清单

```bash
cat > "$TMPDIR/sync_list.txt" <<'EOF'
config/unified_framework.json
config/space_intents.json
tools/space_intent_daemon.py
tools/web/station.html
src/lerobot/app/workcell/space_intent.py
EOF

rsync -av --dry-run --files-from="$TMPDIR/sync_list.txt" user@host:<远端根>/ <本地根>/   # 先看清单
rsync -av          --files-from="$TMPDIR/sync_list.txt" user@host:<远端根>/ <本地根>/
```

- 清单路径**相对工程根**, 两侧目录结构同构才成立; 结构不同就逐条映射, 别硬套。
- 拉前先判本机有没有: `[ -f f ] && echo EXIST || echo MISSING` —— MISSING 是新功能, EXIST 是要覆盖的旧版, 两类都要记进报告(老倪问「改了什么」时直接答)。
- 远端**不展开花括号**: `rsync ...:'a/{b,c}'` 报 `link_stat ... failed`; 改逐行清单或逐条 scp。
- 本地 git 干净时直接拉 + 一次 commit 最省事; 脏就先 stash。

## 4. 验收 (缺一项不算完成)

```bash
python3 -m py_compile <每个 .py> && echo COMPILE_OK
for f in <每个 .json>; do python3 -c "import json;json.load(open('$f'));print('$f OK')"; done
# 逐文件与远端比内容, 不看 rsync 输出
for f in <关键文件>; do echo "$f $(md5sum "$f" | cut -c1-8)"; done
cd <本地根> && git add -A && git commit -m 'sync: <来源> 增量' && git log -1 --format='%h %s'
```

- 报告要给三类数: 拉了几个文件/多大、哪些是新增 vs 覆盖、提交号。
- `SyntaxWarning: invalid escape sequence` 多是历史注释里的 Windows 路径, 不是这次引入的 —— 别当新问题报。

## 5. 技能库: 安装脚本是替换语义

`install.sh` / 打包脚本会把 `~/.hermes/skills` **整个换掉**(实测 30 分类 → 14, 某分类 76 个技能掉到 2 个)。
「从 `skills.bak.<ts>` 捞回来」不够 —— 直接 `cp -a` 会把包里新带的技能丢掉。定式: 备份全量做底 + 只补本机没有的 + 同名保留本机版。

```bash
cd ~/.hermes; B=$(ls -d skills.bak.* | tail -1)
python3 - "$B" <<'PY'
import os,shutil,sys
B=sys.argv[1]; I,T='skills','skills.merge_tmp'
idx=lambda r:{os.path.basename(d):d for d,_,f in os.walk(r) if 'SKILL.md' in f}
shutil.rmtree(T,ignore_errors=True); shutil.copytree(B,T)      # ① 全量备份做底
b,i=idx(B),idx(I)
for k in [k for k in i if k not in b]:                         # ② 只补缺失
    rel=os.path.relpath(i[k],I); dst=os.path.join(T,rel)
    os.makedirs(os.path.dirname(dst),exist_ok=True); shutil.copytree(i[k],dst)
print('added',[k for k in i if k not in b])                    # ③ 同名保留本机版
PY
mv skills skills.installed.<ver> && mv skills.merge_tmp skills
find skills -name SKILL.md | wc -l                             # 必须 ≥ 覆盖前
```

- **同名冲突一律保留本机版**: 包里那些上游再分发的通用技能(agent 框架 / 编码代理 / 文档工具)常是别人的口径,
  覆盖会静默换掉本机调好的工作流。真正要收的是包**新带**的(本机 `comm` 比出来的新技能名)。
- 判据: 技能数只增不减, 分类数回到原值。
- 装完顺手核对它没动别的: `find ~ -maxdepth 2 -newermt '-90 minutes' \( -name '*.bashrc*' -o -name '*.profile' \)` + `crontab -l` + `ls -lt /etc/systemd/system/*.service`。
- 用 `comm` 比技能名集合(不是比目录数): 两侧都 `find . -name SKILL.md | sed 's|/SKILL.md$||' | sort`, 再
  `comm -13 本地 远端` = 本机缺的。**别用 `maxdepth` 数技能** —— 技能在 `<分类>/<技能>/SKILL.md`, 深度算错会把 300 个报成 12 个。

## 6. 不要覆盖的清单 (同步前在源侧找改动记录)

源侧通常留了 `<工程>/tmp_sync/<日期>_<来源>/CHANGELOG_<日期>.md`, 其中「未同步 / 平台特定(不要互相覆盖)」一节是硬约束:

| 类别 | 判据 |
|---|---|
| 平台专属配置 | nginx 配置、systemd unit / drop-in、docker 镜像 —— 只有一侧有 |
| **同名不同物** | 同名文件但行数/职责差一倍(如服务汇总 27KB vs 静态服务 3.6KB) ⇒ 永不互盖 |
| 各机自生成 | 含 `_meta.root` / 本机绝对路径的快照(如 `cc_snapshot.json`) |
| 原件 vs 执行副本 | SDK/驱动类目录: 一侧是源, 另一侧是搬运副本, 不回流 |

**先读 CHANGELOG 再定清单。** 不读就盖, 现象是「服务还在跑但行为变了」——最难查的一类。

## Pitfalls
| 坑 | 症状 | 修法 |
|---|---|---|
| 产线口不通就判「机器失联」 | 白白等、或去现场找网线 | 换 corp/办公网地址再 ssh 一次(§1) |
| 整树 rsync 一个大工程根 | 几小时 + 磁盘爆 | 先 `find -newermt` 出清单再 `--files-from`(§2) |
| 用 `git status` 判是否落地 | `config/*.json` 永远不显示 | `.gitignore` 常挡 `config/`; 用 mtime + `json.load` |
| 覆盖同名不同物 | 服务照跑但行为变了 | 先读源侧 CHANGELOG 的排除清单(§6) |
| 直接 `cp -a skills.bak.* skills` | 包里新技能全丢 | 合并脚本: 备份做底 + 只补缺失(§5) |
| 用 `find -maxdepth 2 -name SKILL.md` 数技能 | 300 个报成 12 个 | 不设 maxdepth, 按 `/SKILL.md$` 去后缀比集合 |
| rsync 远端路径带 `{a,b}` | `link_stat ... failed`, 部分文件静默没传 | 逐行清单文件, 别用花括号 |
| 只看 rsync 退出码就宣布完成 | 文件在但内容是旧的 | md5 逐文件对 + `py_compile`/`json.load` |
| 把位姿/链路断了当成本次同步失败 | 报告里混两件事 | 同步判据只看文件内容; 链路另算(见 related skill) |
