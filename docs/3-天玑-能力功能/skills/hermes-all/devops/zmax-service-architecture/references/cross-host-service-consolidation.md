# 把所有标准服务收拢到一台主机（控制台即服务站）

用户诉求形如「服务要集中，全部常驻到 Intel 550C，变成标准框架」时用这套配方。
前提：对端（Intel/Orin）有 SSH 且能跑 paramiko（见 `peer-host-diagnostics.md`）。

## 第 0 步：分类，不是先动手

`server/services.json` 每条服务都有 `hw` 字段，它就是分类依据。

```python
import json
svcs = json.load(open('server/services.json', encoding='utf-8'))['services']
NET_KW = ('Orin', '珞石', '控制器', '工控机', 'Intel', '网络')
pure, network, local_hw = [], [], []
for s in svcs:
    hw = s.get('hw') or []
    if not hw:
        pure.append(s)                                    # A: 纯软件
    elif all(any(k in str(h) for k in NET_KW) for h in hw):
        network.append(s)                                 # B: 只要网络
    else:
        local_hw.append(s)                                # C: 本地硬件
```

分类结果要**报给用户并说明 C 类为什么搬不动**。实测比例：A 11 / B 7 / C 10。

## 第 1 步：查目标主机已有的

```bash
# 目标主机上
systemctl list-units --type=service --all --no-pager | grep -i zmax | awk '{print $1,$3,$4}'
ss -ltn | awk 'NR>1{print $4}' | grep -oE '[0-9]+$' | sort -n -u | tr '\n' ' '
```

与 `services.json` 求差集后**再剥两类**：

- 本来就不该在这台机器的（AOI 10082/10083 在工控机）
- `host` 字段写着别处的（8792 的 `host: "orin"`，脚本字段直接是空的）

差集里逐项 `find` 脚本，区分「真没代码」和「代码在但没 unit」—— 多数是后者。

## 第 2 步：起 A/B 类，端口必须显式指定

迁移过来的脚本默认端口几乎全对不上清册，而且会撞已占用的号：

| 脚本 | 默认端口 | 清册端口 | 撞车风险 |
|---|---|---|---|
| `mod_overlay_server.py` | 8796 | 8808 | 撞 Orin 位姿中继 |
| `cy_slice_server.py` | 8810 | 8805 | 对端 8810 常被自己的服务占 |
| `se3_geom_server.py` | 8815 | 8804 | — |
| `l2_watch_server.py` | 8820 | 8807 | — |

两种改法，按脚本写法选：argparse 的给 `--port`，读环境变量的给 `Environment=`。

缺依赖模块时，**先判断是「缺文件」还是「缺 PYTHONPATH」**：

```bash
# 报 No module named 'lerobot.manifold.core' → 包在对面但路径没进 sys.path
ZMAX_CY_PORT=8805 PYTHONPATH=/home/intel/zmax_sync/src python tools/cy_slice_server.py
# 报 No module named 'mod_proj' → 真的缺文件, 从源机 SFTP 上去
sftp.put(r"D:\ZMAX\tools\mod_proj.py", "/home/intel/zmax_sync/tools/mod_proj.py")
```

## 第 3 步：写成 systemd unit，不用 nohup

nohup 起的服务重启就没了，用户要的是「常驻」。但在写 unit 之前，**先在 nohup 下试跑一遍**
确认能跑通（看端口是否 LISTEN + 日志尾部报错），比直接装 unit 再 debug 快得多。

**用 paramiko 起后台进程必须写全 `</dev/null >/tmp/x.log 2>&1 &`**。只加 `&` 时
`exec_command` 会一直等 stdout EOF，表现为"命令超时"，而服务其实已经起来了 ——
下一步再去查会看到进程在、端口在听，容易误判成"上次没发出去"而重复启动。
先把旧进程 `pkill` 掉再继续。

模板：

```ini
[Unit]
Description=Z-MAX <名称> (<端口>)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=intel
WorkingDirectory=<工作目录>
Environment=KEY=VALUE
ExecStart=<venv python> tools/<脚本>.py --port <端口>
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

装法注意两点：

- **用 SFTP 写 `/tmp/x.service` 再 `sudo cp`**，不要用 heredoc 拼多行 ini —— 引号转义很容易把配置拼坏。
- **先 `pkill` 掉 nohup 版本**再 `enable --now`，否则端口冲突、systemd 起来就退出。

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now <unit>
systemctl is-enabled <unit>; systemctl is-active <unit>   # 两个都要有值
```

## 第 4 步：C 类用 nginx 反代

目标主机上往往已经有 nginx（`which nginx` + `systemctl is-active nginx`）。
先看它已经占了哪些端口，别抢：`sudo ss -ltnp | grep nginx`。

写 `/etc/nginx/conf.d/zmax-proxy.conf`，一段一个服务：

```nginx
server {
    listen 10082;                     # 与原机同号，用户看到的端口不变
    server_name _;
    access_log /var/log/nginx/zmax_aoi_gold.log;
    location / {
        proxy_pass http://192.168.23.23:10082;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_buffering off;          # MJPEG/流必须关，否则画面卡住
        proxy_read_timeout 300s;
        proxy_connect_timeout 10s;
    }
}
```

- **`proxy_buffering off` 不是可选优化**：不关它 nginx 会攒包，MJPEG 流看起来「连上了但不动」。
- 装完必须 `sudo nginx -t` 再 `sudo systemctl reload nginx`（reload 不中断现有站点）。
- 验证看**新端口出现在监听表里**，并且 `curl` 的结果与原机一致（含 404/500 也算通，
  那是源头的路由问题，不是代理没工作）。

## 第 5 步：统一入口 + 管理脚本

- 管理脚本：`templates/zmaxctl.sh` → `sudo cp` 到 `/usr/local/bin/zmaxctl` + `chmod +x`。
  提供 `status` / `health` / `start|stop|restart` / `log` / `ports`，短名自动补 `zmax-` 前缀。
  脚本内的 unit 清单和代理清单要和实际部署同步维护 —— 那是这份脚本唯一需要手改的地方。
- 控制台页：静态 HTML + JS 轮询，**不要做成需要后端的东西**（后端挂了页面就白）。

**控制台页里所有服务地址必须用 `location.hostname` 拼，不能写死 IP**：

```js
const BASE = 'http://' + location.hostname + ':';
```

目标主机通常双网卡（产线网 + corp wifi），写死其中一个 IP，从另一条网访问时
整页卡片全红 —— 而这种「看起来服务全挂」的假象排查起来极费时间。

跨端口的探活要用 `mode:'no-cors'`（只能判断通/不通，读不到内容，够用）：

```js
fetch(BASE + port + path, {mode:'no-cors', cache:'no-store', signal: ctl.signal})
  .then(() => 'alive').catch(() => 'dead');
```

nginx 给控制台开一个独立端口（`conf.d/zmax-console.conf` + `root /home/intel/zmax_web/console`），
与业务反代分开配置文件，改一个不会连带另一个。

- **静态页改完必须配 `no-store`**，否则 nginx 回 304、浏览器拿缓存，用户看到的是旧页，
  会直接判成「你没改对」。在 console 的 `server{}` 里加
  `add_header Cache-Control "no-store, must-revalidate" always;` 与 `Pragma: no-cache`。
- **一个端口只能有一个主**：要让 nginx 接管某个号（拿反代替掉旧 dashboard），
  必须先 `systemctl disable --now <旧unit>`。只 `stop` 的话它 `Restart=always`
  或下次开机会抢回去，nginx 反而起不来。
- **卡片状态的 key 必须用 host+port 组合，不能只用 port**：同一页会同时列 Intel 的 8793
  和 Windows 的 8793，只用 port 做 key 两边状态互相覆盖，表现为「绿的显红、红的显绿」，
  而且看上去很像探测逻辑坏了，极难联想到 key 冲突。同理 `state[port]` 改成 `state[host+':'+port]`。
- **一页列多台机器时，组信息要能一眼分辨**：远端条目在名称列前缀 IP、给一个独立徽章
  （本地 / 代理 / Windows），否则用户会说「不对，这应该是 X 上的服务」。

**要把对端的 systemd 单元也列进同一张汇总页时，不要在请求里 SSH 过去查。**
在对端跑一个只读小服务，把 `systemctl` 结果缓存成 JSON 供本机拉：

```bash
systemctl list-units --type=service --all --no-pager --no-legend --output=json   # systemd 255
```

- 只挑 `zmax*` 加几个关键系统单元（nginx / mysql / ssh / docker / 自建 relay），
  255 个全列出来对现场没用，先把分母做大只会让人看不到异常。
- **缓存 TTL 给 60s，别给 20s**：每次 `systemctl list-units` 都要 fork 一次，
  在 load 30+ 的机器上是实打实的负担。
- 本机合并时**不要把单元直接混进端口清单**：单元没有 port，`port` 为 `None` 会让
  `items.sort(key=lambda it: it["port"])` 抛 `TypeError`。排序键写成
  `(0 if is_local else 1, kind == "unit", port or 0, name)`。
- 探测对端端口前先用**一个用户态 HTTP 端口**（8888 / 80）判整机可达并把结果缓存 20s；
  不可达就整批直接标 down。否则对端一卡，整页每个远端端口各等满 1.5s 超时，
  汇总接口从 2 秒变 7 秒，用户会以为页面坏了。

## 第 6 步：验收标准

1. `zmaxctl status` 里每个单元 `active`、每个代理端口有 HTTPS 码
2. `systemctl is-enabled` 全部 `enabled`（否则重启就没了）
3. 从**第三台机器**（不是本机 loopback）打开控制台页，卡片是绿的
4. C 类的服务：明确告诉用户「进程不在目标机，请求被转发」

第 3、4 条最容易被跳过。本机 curl 通只证明服务活着，不证明用户那条网络到得了。

## 第 7 步：重启验收 —— 「常驻」的唯一硬证据

`systemctl enable` 只说明配置写对了，**不证明开机自启**。要证明只能真重启一次。
agent 自己执行不了（`systemctl reboot` 在 Hermes 无条件黑名单里），把命令给用户。

重启后逐项核对，缺一项都不算通过：

```bash
uptime -s                                            # ① 它真的重启了吗
for s in <unit 清单>; do printf '%-24s %s %s\n' $s \
  "$(systemctl is-active $s)" "$(systemctl is-enabled $s)"; done   # ② 全 active+enabled
systemctl --failed --no-pager | grep -i zmax         # ③ 应为空
sudo ss -ltnp | grep nginx | awk '{print $4}' | sort -u            # ④ 反代端口全在
curl -s -m 10 http://127.0.0.1:<业务端口>/health      # ⑤ 业务数据是实时的
```

**① 是最容易漏也最毁结论的一条**：用户说"重启了"、而 `uptime -s` 与之前一致
（比如一直显示 `up 2 hours`）就说明根本没重启。此时报告"自启验证通过"是错的，
那只是手动 `start` 留下的现场。先核实，再下结论。

**④ 值得单列**：nginx 读 `conf.d/`，重启后自动生效，不需要谁去 reload。
如果反代端口重启后消失了，才是配置文件放错位置或被别的 site 挤掉。

**⑤ 别在刚重启的那一刻判**：`load average` 会很高（服务在初始化），
等 30~60 秒再采，否则会把"还在起"当成"起不来"。
