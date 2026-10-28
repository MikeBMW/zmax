# 反向隧道诊断: "外面连不进来"到底卡在哪一层

目标形如: 内网机器(工位机)上有服务, 要从公网访问; 中间用一台有公网 IP 的 ECS 做跳板。
本文件是**分层定位口径**, 免得拿"装个 frp"当万能钥匙。

---

## 1. 五层逐层量, 每层一条命令 —— 不要跳

按顺序量, **第一个断掉的层就是根因**, 后面的层不用看:

| 层 | 命令 | 判读 |
|---|---|---|
| ① 宿主可达 | `ping -c2 <公网IP>` | 丢包 ⇒ 网络/路由 |
| ② 服务在听吗 | `ssh <host> 'ss -ltnp \| grep :<port>'` | 没监听 ⇒ 服务没起/绑错地址 |
| ③ 本机能连吗 | `ssh <host> 'curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:<port>/'` | 本地通 ⇒ 服务本身没问题 |
| ④ 本机防火墙 | `ssh <host> 'ufw status numbered'` | 有该端口的 ALLOW ⇒ **ufw 不是嫌疑人** |
| ⑤ 从外网直连 | `curl --connect-timeout 5 telnet://<公网IP>:<port>` 或 `bash -c 'cat</dev/null >/dev/tcp/<IP>/<port>'` | 不通而 ②③ 都通 ⇒ **云安全组** |

🔴 **②③ 通、⑤ 不通 = 云平台安全组**, 不是 ufw、不是服务、不是密钥。
这个会话就是: `frps` 在 `*:7000` 正常监听、本地 `curl 127.0.0.1:7000` 通、ufw 里 `7000/tcp ALLOW`
早已存在, 而从外面 7000/8891/22022/18799/18793/34881 **全部不通**, 只有 22/80/443 通。

**别把 ufw 规则当成"端口已开"**: ufw 只是本机那一层。云厂商安全组是**另一层且更靠外**,
它在服务器内部改不了 —— 必须控制台操作, 这是**用户侧动作**, 如实告诉他, 不要自己在服务器上绕一天。

### 一条命令扫清"到底哪些端口真的从外面可达"
```bash
for p in 22 80 443 7000 22022 18799; do
  printf '  %-6s ' $p
  timeout 5 bash -c "cat < /dev/null > /dev/tcp/<公网IP>/$p" 2>/dev/null && echo '✅ 通' || echo '❌ 不通'
 done
```
先量出"已开的白名单", 后面所有设计都往这几个端口上靠。

---

## 2. 安全组没开时的正解: 全走已开端口 (SSH 隧道 + 80 反代)

前提先确认对端 sshd 允许绑定非 loopback:
```bash
ssh <ECS> 'grep -i gatewayports /etc/ssh/sshd_config'   # 需要 GatewayPorts yes
```
`GatewayPorts yes` ⇒ `ssh -R 0.0.0.0:<远端端口>:...` 才能绑到 0.0.0.0;
否则只绑 127.0.0.1(ECS 自己能连, 外面依然白搭)。

然后 **两条链**:
```bash
# ① 反向隧道 (只用到 22 — 一定开)
ssh -f -N -i ~/.ssh/id_<用途> -o IdentitiesOnly=yes -o ExitOnForwardFailure=yes \
    -R 127.0.0.1:18793:127.0.0.1:8793 \
    -R 0.0.0.0:22022:192.168.23.66:22 \
    root@<ECS>
# ② ECS 上用 80/443 反代 (这两个端口一定开)
#    nginx: location ^~ /st/ { proxy_pass http://127.0.0.1:18793/; }
```
结果: 公网 `http://<IP>/st/xxx` → 18793 → 工位机 8793。**不需要新开任何端口**。

- 隧道端口绑 `127.0.0.1` 还是 `0.0.0.0` **取决于下一跳是谁**: 后面还有 nginx 反代就绑 loopback(更安全),
  要公网直连(如 SSH)才绑 `0.0.0.0` —— 即使绑了 0.0.0.0, 安全组不放行照样进不来。
- **SSH 到内网另一台机器**只能靠 22022 这类端口, HTTP 反代盖不住 ⇒ 这一条**必须让用户去开安全组**。

### 替代方案对照
| 手段 | 需要开放的端口 | 适用 |
|---|---|---|
| frp (frps+frpc) | 控制口(常 7000) + 每个 remotePort | 安全组可控时最省事 |
| `ssh -R` + nginx 80/443 反代 | **0 个新端口** | 安全组改不动时的正解; 只能转发 HTTP(S) |
| `ssh -R` 裸 TCP | 每个 remotePort | 需要 SSH/数据库等非 HTTP 协议 |

---

## 3. nginx 反代的四个坑

1. 🔴 **页面用绝对路径资源 ⇒ 只反代页面本身会"页面能开、图全裂"**。先查:
   ```bash
   curl -s http://127.0.0.1:8793/station | grep -oE '(src|href)="[^"]*"' | sort -u
   ```
   出现 `/aoi_gold.mjpg` `/snapshot/arm.jpg` 这类**以 / 开头**的 ⇒ 这些路径也得反代,
   或直接用一个统一前缀把整站挂进去(见下条)。
2. **`^~` 前缀必须加**: 宝塔/PHP 站点的 `location ~ \.(jpg|png)$` 正则优先级高于普通前缀前缀,
   不加 `^~` 图片会 404。写成 `location ^~ /st/ { ... }`。
3. **MJPEG 流必须 `proxy_buffering off` + 长超时**(`proxy_read_timeout 3600s`), 否则画面卡成一帧。
4. **`server_name` 不匹配会把请求送给默认站点**: `curl http://127.0.0.1/...` 拿到 404 不代表配置错,
   带上 `-H "Host: <server_name>"` 再测。

**宝塔托管的 nginx 别用 `nginx -s reload`**: `/run/nginx.pid` 常是 0 字节 ⇒
`invalid PID number "" in "/run/nginx.pid"`。真 pid 在 `/www/server/nginx/logs/nginx.pid`,
用 `/www/server/nginx/sbin/nginx -t` + `/www/server/nginx/sbin/nginx -s reload`。

---

## 4. 动手前先盘点: 隧道很可能已经存在

这类需求会被反复重做, 机器上常已有一整套 systemd 单元与代理。**先查再建**, 否则会建出重复/冲突的服务:
```bash
systemctl list-units --all | grep -iE 'tunnel|ecs|frp'
systemctl cat <unit>   # 看真实 ExecStart: 到底哪个本地端口映射到哪个远端口
ss -ltnp | grep -E ':(8793|8799)'
ssh <ECS> 'ss -ltn | grep -E ":(1879[0-9]|22022)"'
```
🔴 **不同端口的隧道可能指向完全不同的东西**: 实测 `18791/18793` 映射的是本机的 `8891/8893`(带 token 的只读代理),
**不是** 8791/8793 —— 凭端口号猜路径会得出错误结论。一律 `systemctl cat` 看 `ExecStart` 里的 `-R` 原文。

🔴 **同一台机器可能有别的 agent/会话在并行改服务**: 本次 `systemctl restart` 报 `Job ... canceled`,
而日志里出现了自己没写过的 `zmax-ecs-dash` 单元 —— 说明有并行写者。此时**停手先做只读盘点**,
别再抢着改; 把自己的误配置(如指向不存在端口的 nginx location)撤干净, 用现有链路验收。

---

## 5. 验收口径

必须在**外网侧(不是 ECS 本地)** 打一遍真请求, 并把 HTTP 码+字节数贴出来:
```bash
curl -s -o /dev/null -H 'Host: <server_name>' -w '%{http_code} %{size_download}B\n' 'http://<公网IP>/st/station'
```
本地通("我在服务器上 curl 127.0.0.1 是 200")**不算数** —— 安全组、`server_name`、绑地址都可能在那之后把它弄死。

**带口令的只读代理要连 `?k=` 一起验**: 反代链路后面常挂一个 token 校验的只读代理, 不带口令返回 **403**。
403 不是路径配错 —— 先看现有 location 的 `proxy_pass` 和代理自身的 token 参数, 别去改 nginx。
交付时把带口令的完整 URL 作为可用地址 (`.../st/station?k=<token>`), 并写明哪些路径需要口令、哪些是裸的。
