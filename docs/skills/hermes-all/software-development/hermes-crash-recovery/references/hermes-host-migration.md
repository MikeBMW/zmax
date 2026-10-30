# 把 Hermes 搬到另一台主机（完整配方）

适用: 用户说"把 web/小静/某分身迁到 B 机"，B 机可能是边缘盒、工控机、另一台服务器。
**与灾后恢复的区别**: 源机还活着、可以随时回滚，所以能双向对账；难点在"旧的要停、新的要真收消息"。

## 0. 先定边界: 到底在搬什么

一次"迁移"常被当成一件事，实际是几件不同的事，混在一起会得出错误的"完成"结论:

| 对象 | 典型体量 | 是否阻塞上线 |
|---|---|---|
| agent 运行时 + 技能 + 记忆 + 状态库 | 十几 MB | **是**（搬完就能对话） |
| 平台凭据（飞书/Telegram app） | 几行 | **是**（且必须独占） |
| 网站静态资源 + 后端服务 | GB 级 | 否，取决于有没有公网入口 |

先跟用户确认搬到的是"能对话的分身"还是"整站"。整站往往缺一个对外入口，搬完也上不了线。

## 1. 新机装运行时

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash -s -- --non-interactive
```

国内机器常见现象: 只有**部分域名**解析失败（`pypi.org` 通、`files.pythonhosted.org` 不通、`github.com` 不通）。
这不是 DNS 配错，是域名级阻断 —— **用国内镜像绕开，不要去改 resolv.conf 折腾**。

`✗ pm install failed` + `cause: client error (Connect)` / `operation timed out` = 依赖环境未提交，不是装坏了:

```bash
printf '[[index]]\nurl = "https://mirrors.ustc.edu.cn/pypi/simple"\ndefault = true\n' > ~/.config/uv/uv.toml
printf '[global]\nindex-url = https://mirrors.ustc.edu.cn/pypi/simple\ntrusted-host = mirrors.ustc.edu.cn\n' > ~/.config/pip/pip.conf
cd ~/.hermes/hermes-agent && ./.hermes/bin/hermes pm repair
```

`pm install` 失败时 `hermes` 不在 PATH，但安装树里已有 `.hermes/bin/hermes` —— 直接用它，别等 PATH。

git 拉不动时把上游 remote 指向代理（只影响这一台机器）:
```bash
cd ~/.hermes/hermes-agent && git remote set-url origin https://gh-proxy.com/https://github.com/NousResearch/hermes-agent.git
git ls-remote --heads origin main     # 返回 sha 才算通
```

## 2. 凭据: 拷 .env，不是 auth.json

模型 key 常在 `.env`（`auth.json` 的 `providers` 可能为空）。拷 `.env` 时**必须剔掉平台凭据**，
否则新老两台会同时用同一个 app 抢事件:

```bash
grep -vE '^(FEISHU_|SLACK_|TELEGRAM_|GATEWAY_ALLOW)' ~/.hermes/.env > /tmp/env_for_new_host
```

平台凭据要去源机的 `config.yaml` 里取（`platforms.<p>.app_id/app_secret`），单独写进新机配置。

## 3. 状态库: 只能热拷

🔴 直接 `scp` 活库会得到"大小对、打不开"的文件，报 `file is not a database` / `structural corruption`。

```bash
# 源机: 一致性快照（不需要停 gateway，.backup 走事务）
python3 -c "
import sqlite3
s=sqlite3.connect('/root/.hermes/state.db'); d=sqlite3.connect('/tmp/state_clean.db')
s.backup(d); d.close(); s.close()"
# 两侧都验：
python3 -c "import sqlite3;c=sqlite3.connect('/tmp/state_clean.db');\
print(c.execute('pragma integrity_check').fetchone()[0], c.execute('select count(*) from sessions').fetchone()[0])"
```

装到新机前先备份新机自己的库；**装完必须移走 `state.db-shm` / `state.db-wal` / `state.db.*.lock`**，
否则旧的锁与 WAL 会让报错继续，看起来像"换了库还是坏的"。

跨小版本（如 v0.19 → v0.22）能自动迁移，但迁移后要再跑一次 `integrity_check` + 对账 sessions 行数。

残留 gateway 卡在 `draining` 时（`gateway_state.json` 里 `"gateway_state": "draining"`），
新会话会报 `Gateway draining: not_ready`：`kill -9 <pid>` 后删 `gateway.lock` + `gateway_state.json`。

## 4. 平台切换: 独占 + 常驻 + 放行

1. **停老的**（若是 `systemctl --user` 管的，kill 会被拉回来）:
   ```bash
export XDG_RUNTIME_DIR=/run/user/0
systemctl --user disable --now hermes-gateway.service   # disable 会删 wants 软链
systemctl --user is-active hermes-gateway               # 期望 failed / inactive
```
2. **起新的，装成服务**（临时 `gateway run` 会在 `unmanaged_idle_exit_seconds`=600s 后自己退出）:
   ```bash
hermes gateway install      # 用户级 unit + 自动 enable linger
hermes gateway status       # Active: active (running) + enabled
```
3. **配入站允许名单**（漏了就是"收到也丢"）:
   ```bash
echo 'FEISHU_ALLOWED_USERS=<user_id>,<user_id_alt>' >> ~/.hermes/.env
hermes gateway restart
```

## 5. 验收三层

| 层 | 怎么验 | 通过判据 |
|---|---|---|
| 出站 | 用 `tenant_access_token` 调 `im/v1/messages` 往群里发 | 返回 message_id |
| 入站 | 看该平台的对话数 / `gateway.log` 的 receive 行 | 数在涨（**需真人发一条**，机器人收不到自己发的） |
| 能力 | `hermes -z "回答两个字：正常"` | 有真实文本输出 |

常见误判: `Channel directory built: 0 target(s)` 看着像故障，其实正常（聊天在首条消息后才发现）；
`✓ feishu connected` 只证明 websocket 通了，不证明入站放行。

## 6. 关源机前: 审隐藏依赖

```bash
pgrep -af "ssh -R|autossh|frpc"     # 实测会有一条 ssh -R 把本机 nginx 端口挂到源机
ss -tnp | grep <源机IP>
echo $XDG_RUNTIME_DIR; systemctl --user list-units | grep -i hermes
```

隧道命中时还要去源机看 nginx 是否 `proxy_pass 127.0.0.1:<隧道端口>` —— 命中的话，
"源机关机"会连带断掉那条对外链路，属于交付时必须单独说清的风险项。

清单式交付口径:
- 不依赖源机的: 平台对话（出站到平台服务器）、同网段 SSH、本机端口直连。
- 依赖源机的: 反向隧道暴露的服务、源机 nginx 代理的入口、源机的域名解析。
- 进行中的大文件传输 **会被关机打断**，先传完再关。
