---
name: zmax-agent-sync
description: Use when a machine needs the Z-MAX agent pack (skills, space points, services) or must sync to the current 5.50.78x baseline.
---

# Z-MAX Agent 同步

Z-MAX 产线工位（AOI + 机械臂 + 空间点智能体）的 agent 资产集中在一个 HTTP 服务站上，
任何机器（Windows / Ubuntu / macOS）都从同一个地方取，保证「同一个框架、同一份代码逻辑」。

## 服务端

```
http://10.163.149.123:8888/        服务站首页（含 Agent 技能 tab）
http://10.163.149.123:8888/agent/  技能包目录
```

包内包含：`.hermes/skills/`（全部技能）、`config/space_intents.json`（69 个空间点注册表）、
`config/unified_framework.json`（大一统框架清单 + 路线图）、空间智能体代码、AOI 三态与几何约束。

## 一条命令装好（推荐）

```bash
curl -sL http://10.163.149.123:8888/agent/install.sh | bash
```

装到 `~/zmax_agent`，技能进 `~/.hermes/skills`（旧技能自动备份为 `skills.bak.<ts>`）。
可覆盖：

```bash
ZMAX_AGENT_DEST=/opt/zmax HERMES_HOME=/opt/hermes bash install.sh
```

## 只同步、不重装

```bash
BASE=http://10.163.149.123:8888/agent
VER=$(curl -sL "$BASE/VERSION" | tr -d '[:space:]')
curl -sL "$BASE/zmax-agent-$VER.tar.gz" -o /tmp/za.tgz
curl -sL "$BASE/zmax-agent-$VER.tar.gz.sha256" -o /tmp/za.sha
(cd /tmp && sha256sum -c za.sha)   # macOS 用 shasum -a 256 -c
mkdir -p ~/zmax_agent && tar -xzf /tmp/za.tgz -C ~/zmax_agent
```

## 先查版本（同步前判重）

```bash
curl -sL http://10.163.149.123:8888/agent/VERSION
# 与本地比对
python3 -c "import json;print(json.load(open('$HOME/zmax_agent/zmax_agent/config/space_intents.json'))['version'])"
```

版本一致就不要重装——重装会备份并替换 `~/.hermes/skills`。

## 装完之后

```bash
# 影子模式起空间点守护（只记账，不下发指令）
python3 ~/zmax_agent/zmax_agent/tools/space_intent_daemon.py --hz 5
```

守护日志写到 `zmax_data/space_intent/space_intent_<date>.jsonl`，
每拍记录 `verdict / hit / fired / shadow / ms`，用于事后复盘「到点 ↔ 判定」的因果。

## 常见问题

- **`%{http_code}` 原样输出**：curl 的 `-w` 被 shell 吃掉 `%`，用单引号包住 `-w '%{http_code}'`。
- **MD5/SHA 不符但文件看着对**：Windows 侧用 `os.path.join` 拼 Linux 路径会混入反斜杠，
  生成 `zmax_550c\config/...` 这种怪文件名。远端拼路径一律用 `posixpath.join`。
- **装完自检报「找不到 space_intents.json」**：脚本用 `$DEST` 定位，不要在别的 cwd 下手改路径。
- **`~/.hermes/skills` 被替换后自定义技能没了**：安装前会备份成 `skills.bak.<时间戳>`，从那里捞回来。
