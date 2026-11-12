# 删一个云端出口 (域名 + 云主机) 的三层做法与验收

用户说「把这个云端功能删了 / 全删云端出口」时, **停服务单元只是第一层**。只做这一层的话:
代码里的外呼和界面按钮还在, 每次白等一个超时, 而用户看到的是"删了但按钮还点了没反应"。

## 0. 先盘落点 (最容易漏的是"已经在连的进程")
```bash
systemctl list-unit-files '<前缀>*' --no-pager                 # 隧道/转发单元
sudo grep -rl '<IP 或域名>' /etc/systemd/system/*.service       # 还有哪些单元提到它
crontab -l | grep -i '<域名或 IP>'
sudo ss -tnp | grep '<IP>'                                     # ★ 当下真在连它的进程: python 一串 SYN-SENT = 代码外呼
```
`ss` 那一步给出 pid → `tr '\0' ' ' < /proc/<pid>/cmdline`, 才知道要改哪几个模块。**不盘这层删不干净**。

## 1. 链路层: 单元 + 环境文件
```bash
Q=~/zmax_quarantine/<feature>_removed_$(date +%Y%m%d_%H%M%S); mkdir -p $Q
for u in <单元...>; do sudo systemctl stop $u; sudo systemctl disable $u
  sudo cp -a /etc/systemd/system/$u.service $Q/ && sudo rm -f /etc/systemd/system/$u.service; done
for f in /etc/<feature>-*.env; do sudo cp -a "$f" $Q/ && sudo rm -f "$f"; done
sudo systemctl daemon-reload; sudo systemctl reset-failed
```
- **靠同一条链路吃饭的转发/网关单元要一起 disable**(经该主机跳板的 fwd、`wss://<域名>/…` 的 hub),
  否则它们一直 `activating` 空转。
- 单元文件移到 `~/zmax_quarantine/<ts>/` 而不要直接 `rm`: 可回滚, 且回答得了"原来长什么样"。

## 2. 出口层: 域名 + 裸 IP 两道闸
```bash
sudo cp -a /etc/hosts /etc/hosts.bak_$(date +%Y%m%d_%H%M%S)
printf '\n127.0.0.1 <域名>\n127.0.0.1 www.<域名>\n' | sudo tee -a /etc/hosts
sudo iptables -C OUTPUT -d <IP> -j REJECT 2>/dev/null || \
  sudo iptables -I OUTPUT -d <IP> -j REJECT --reject-with icmp-port-unreachable
```
- **hosts 只管域名**: 代码里用裸 IP 的 `scp`/`POST` 会完全绕过它 ⇒ 必须再加 iptables 那条。
- iptables 不自持久: 建开机幂等 oneshot(`Type=oneshot` + `RemainAfterExit=yes` +
  `ExecStart=/bin/sh -c 'iptables -C … || iptables -I …'`), `enable --now`, 单元副本入库以便追溯。

## 3. 代码/界面层
按 `zmax-console/references/bulk-edits-in-huge-gui-files.md` 的"删一个打开外部页面/上传到外部的功能"做:
按钮、`clicked.connect`、handler、URL 常量、节点文案、日志里打印链接的行一起清;
能本地产出的改成"复制 / 存本地 + 绝对路径"; 只能开外页的改指本机在役页并**先探活再打开**。

## 验收 (四件都要量, 缺一就是没删干净)
```bash
sudo ss -tnp | grep -c '<IP>'            # 必须 0 —— 是"没有任何连接尝试", 不只是"没在跑"
curl -s -o /dev/null -w '%{http_code} %{time_total}s\n' --max-time 5 https://<域名>   # 0.0x 秒失败(原 10~15s 超时)
systemctl --failed --no-pager | tail -1                 # 0 loaded units
systemctl list-unit-files '<前缀>*' --no-pager          # 0 unit files
```
- 报给用户就报这三行数: 连接 0 条 · 外呼 0.0x 秒被拒(原 N 秒超时) · failed 0。
- **仍指向该主机的"数据路由"要点名**: 那是功能路径(拉数据/状态探测/采集端点),
  改成局域网直连必须等现场链路在位才能定地址 —— 不许现在瞎填一个; 如实说"出站已封, 点了 0.01s 失败并回退"。
