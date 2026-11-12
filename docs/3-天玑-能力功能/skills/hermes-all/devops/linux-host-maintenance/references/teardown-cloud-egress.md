# 彻底拆掉一条对外出口 (云中转 / 反向隧道 / 上传链路)

用户说「全删云端出口」「连按钮一起删」时, **停单元不算删** —— 出口通常有三层, 少一层就留下
死链、白等超时或自动重连的进程。按下面四层做完并用测得的延迟/连接数验收。

## 0. 先摸清这条出口都有谁
```bash
systemctl list-unit-files '<前缀>*' --no-pager
sudo grep -rl '<云端 IP>' /etc/systemd/system/          # 单元里写死的地址
crontab -l | grep -i '<域名|IP>'
sudo ss -tnp | grep '<云端 IP>'                        # 谁此刻真的在往外连 (拿 pid → 进程名)
sudo grep -rl '<域名>' /etc/systemd/system/*.service
```
`ss` 里一串 `SYN-SENT` 是典型形态: 说明**代码层**在轮询一个早就死掉的对端, 每个调用白等一个超时。
只停隧道单元治不了它 —— 必须改代码或按第 2 层在网络上封死。

## 1. 链路层: 单元隔离 (可回退, 不 rm)
```bash
Q=~/zmax_quarantine/<出口名>_removed_$(date +%Y%m%d_%H%M%S); mkdir -p $Q
for u in <单元列表>; do
  sudo systemctl stop $u; sudo systemctl disable $u
  sudo cp -a /etc/systemd/system/$u.service $Q/ && sudo rm -f /etc/systemd/system/$u.service
  for f in /etc/<前缀>-*.env; do [ -f "$f" ] && sudo cp -a "$f" $Q/ && sudo rm -f "$f"; done
done
sudo systemctl daemon-reload; sudo systemctl reset-failed
```
- **区分"直接隧道"和"依赖它的转发"**: 直接隧道删文件, 依赖它跳板的转发只 `disable` 留文件即可。
- 环境文件 (含口令) 一并移入隔离目录, 别留在 `/etc` 里被下一个 unit 读到。
- 判据: `systemctl list-unit-files '<前缀>*'` = 0 条、`list-units --all` = 0 条、`systemctl --failed` 干净。

## 2. 出口层: 域名黑洞 + 裸 IP 封禁 (代码不改也立刻止血)
```bash
sudo cp -a /etc/hosts /etc/hosts.bak_$(date +%Y%m%d_%H%M%S)
printf '\n127.0.0.1 <域名>\n127.0.0.1 www.<域名>\n' | sudo tee -a /etc/hosts
sudo iptables -C OUTPUT -d <云端 IP> -j REJECT 2>/dev/null || \
  sudo iptables -I OUTPUT -d <云端 IP> -j REJECT --reject-with icmp-port-unreachable
```
- hosts 只挡**域名**; 代码里写裸 IP 的 scp/POST 穿透 hosts ⇒ 必须再加一条 iptables OUTPUT REJECT。
- iptables 规则**重启即失**: 写成 oneshot 单元开机幂等重放 (`iptables -C … || iptables -I …`), 放仓库
  `tools/systemd/` 再 `cp` 到 `/etc/systemd/system` + `enable --now`。
- 验收要用**延迟**证明, 不是"应该失败":
```bash
/usr/bin/time -f '%es' python3 -c "import urllib.request;urllib.request.urlopen('https://<域名>/x',timeout=12)" 
/usr/bin/time -f '%es' bash -c 'curl -s -o /dev/null -m5 http://<云端 IP>/; true'
sudo ss -tnp | grep -c '<云端 IP>'     # 必须是 0
```
典型: 从 10~15s 超时 → 0.01~0.04s 直接拒。没有这个数量级的差别就是没封住。

## 3. 界面层: 按钮和入口一起删, 不许留死链
原则: **要么给本机可用的替代动作, 要么给明确说法 —— 不能点了没反应或打开 404。**
- 上传到云端的按钮 ("📤 导出到 …") → 删除按钮与其 POST/scp; 若产物本地还有用, 换成「本地生成 + 打印路径」
  或「📋 复制摘要」(剪贴板立刻有内容, 用户能验)。
- 只读云端页面的按钮 (方案介绍/3D 场景) → 有本机等价页就改指本机 (例如 AR 页 8797), 并**先探活再打开**
  (`urlopen(..., timeout=2)` 200 才开), 没起就如实说"本机未起"。
- 上报云端链接的日志 (`🔗 http://<域名>/xxx`) → 改成打印本地绝对路径, 否则用户复制到浏览器打不开。
- 部署/推送路径 ("ECS 中转 → 目标机") → 在入口处前置拦截 + 一句人能看懂的原因, 别让它探测几分钟再报错。

## 4. 收尾: 说清楚还剩什么
- `grep -c '<域名>|<IP>' <改过的文件>` 数一次: 剩下的每一处要么在注释/文档里, 要么是**必须改地址才能修**的
  活代码 —— 后者当场不要瞎改 (没有链路就没法验证地址对不对), 明确写"出站已封, 0.01s 失败并回退"。
- 收尾核对: 受影响服务仍 active、`systemctl --failed` 空、关键端口 200、`ss` 上出口连接 0。
- 界面改动**要重开 GUI 才生效**; 用户正在看的时候不得自行重启, 只提示。

## 坑
- 别只 `systemctl stop` 就宣布删完: `Restart=` 会让它 5 秒后回来, 而且 NRestarts 已经爬到十几也不报警。
- 别用 `systemctl mask` 代替删除后又忘了记在哪: 隔离目录 + `daemon-reload` 才能既生效又可回退。
- hosts 里加 `0.0.0.0 <域名>` 与加 `127.0.0.1 <域名>` 效果不同: 后者是立刻 refused (首选), 前者可能先卡一段时间。
- 站点/服务搬家后, 旧域名的按钮还在 GUI 里 ⇒ 这就是用户说"点了打不开"的来源; 搬完家就顺手改入口。
- 用户说"全删"时, 网络层封禁是**止血**, 不等于功能删干净; 要么把"代码里还剩几处"如实报出来, 要么真的逐处删。
