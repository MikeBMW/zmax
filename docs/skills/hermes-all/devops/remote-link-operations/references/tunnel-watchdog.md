# 内网设备侧「上行隧道 watchdog」模板

目标：跳板机重启 / 隧道半开时，内网设备自己在 60s 内重建反向隧道，不依赖人发现。

## 判据
从**内网设备自己**探跳板机的反向端口。端口能连 = 隧道活着；连续 3 次连不上（≈60s）才动手，
单次抖动就重启会把好链路打断。

## `/usr/local/bin/zmax-tunnel-watchdog.sh`
```bash
#!/bin/bash
# 连续 3 次(≈60s)探不到 <jump-host>:<port> 才 restart，避免网络抖动误杀
JH="39.102.211.79"; PORT="22022"; UNIT="zmax-orin-tunnel.service"
fail=0
for i in 1 2 3; do
  if timeout 4 bash -c "echo > /dev/tcp/$JH/$PORT" 2>/dev/null; then fail=0; break; fi
  fail=$((fail+1))
  [ "$i" -lt 3 ] && sleep 20
done
if [ "$fail" -ge 3 ]; then
  logger -t zmax-tunnel-wd "$JH:$PORT unreachable x3 -> restart $UNIT"
  systemctl restart "$UNIT"
fi
```
用 bash 内建 `/dev/tcp`，不依赖设备上装没装 `nc`。

## service + timer
```ini
# /etc/systemd/system/zmax-tunnel-wd.service
[Unit]
Description=上行隧道 watchdog (跳板端口半开自愈)
[Service]
Type=oneshot
ExecStart=/usr/local/bin/zmax-tunnel-watchdog.sh
```
```ini
# /etc/systemd/system/zmax-tunnel-wd.timer
[Unit]
Description=上行隧道 watchdog · 每 60s
[Timer]
OnBootSec=90
OnUnitActiveSec=60
AccuracySec=5
[Install]
WantedBy=timers.target
```

## 装与验收
```bash
scp watchdog.sh dev:/tmp/ && ssh dev 'sudo install -m755 /tmp/watchdog.sh /usr/local/bin/' \
  && ssh dev 'sudo cp /tmp/*.service /tmp/*.timer /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now zmax-tunnel-wd.timer'
ssh dev 'systemctl is-active zmax-tunnel-wd.timer; systemctl list-timers zmax-tunnel-wd.timer --no-pager | head -2'
```
看到 `active` + `NEXT` 有下一条时间才算装上（只看 enable 成功不算）。

## 注意
- watchdog 装在**内网设备**上。跳板机整机挂了时它也无能为力（只能反复重试），所以它解决的是「隧道半开」，
  不解决「跳板机卡死」——后者要云控制台重启。
- 别用 `systemctl restart` 去重启一个**正在构建大状态**的服务；本模板只用于无状态的 ssh 隧道。
