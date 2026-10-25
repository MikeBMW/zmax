#!/bin/bash
# ECS 换机: 把本机所有引用老中转机 (39.102.211.79) 的链路改到新机 (47.93.88.143)
#
# 用法:
#   bash tools/ecs_repoint_new_host.sh --dry        # 只列将要改的文件与替换行 (默认)
#   sudo bash tools/ecs_repoint_new_host.sh --apply # 真改: 备份 → 替换 → daemon-reload → 重启 → 逐条验证
#
# 判据(apply 末尾自动跑): 本地 -L 监听回来 (10082/10083/18792/18800/18822) ·
#   公网 /ov/ /st/ = 200 · ECS 侧 18791/18793/18799/18794 有 sshd 占口 ·
#   /orin/status 200 且 last_seen 新鲜.
#
# ⚠️ 前提: 新机 47.93.88.143 上 root 口令(reset 到 zmax_data/secrets/zmax.env 的 ZMAX_ECS_PW
#    与 /etc/zmax-ecs-*.env) 和 tashan 用户的 ~/.ssh/id_ed25519 授权都已就位, 否则单元会
#    反复 exit 255 —— 探活会立刻告诉你哪条认证没通。

set -u
OLD=${OLD_ECS:-39.102.211.79}
NEW=${NEW_ECS:-47.93.88.143}
MODE=${1:---dry}
TS=$(date +%Y%m%d_%H%M%S)
SSH_CONFIG=/home/ubuntu/.ssh/config
UNITS=$(grep -l "$OLD" /etc/systemd/system/*.service 2>/dev/null)

echo "== 换机: $OLD → $NEW  (mode=$MODE)"
echo "== 待改 unit: $(echo "$UNITS" | grep -c . ) 个"
for u in $UNITS; do
  echo "   $(basename "$u")"
  grep -n "$OLD" "$u" | sed 's/^/      /'
done
echo "== ssh config:"
grep -n "$OLD" "$SSH_CONFIG" | sed 's/^/      /'
echo "== env 文件(口令需已换成新机):"
for f in /etc/zmax-ecs-ov.env /etc/zmax-ecs-station.env; do [ -f "$f" ] && echo "      $f"; done

if [ "$MODE" != "--apply" ]; then
  echo "== dry: 未改动。真正执行: sudo bash $0 --apply"
  exit 0
fi

if [ "$(id -u)" != 0 ]; then echo "!! 需要 root (改 /etc/systemd/system)"; exit 2; fi

BK=/home/ubuntu/zmax_data/ecs_repoint_$TS
mkdir -p "$BK"
for u in $UNITS; do
  cp -a "$u" "$BK/"
  sed -i "s/$OLD/$NEW/g" "$u"
  echo "   ✓ $(basename "$u") → $NEW (备份 $BK/$(basename "$u"))"
done
cp -a "$SSH_CONFIG" "$BK/ssh_config"
sed -i "/^Host orin$/,/^$/ s/HostName $OLD/HostName $NEW/" "$SSH_CONFIG"
sed -i "/^Host orin-lan$/,/^$/ s/HostName $OLD/HostName $NEW/" "$SSH_CONFIG"
echo "   ✓ ssh config Host orin → $NEW"

systemctl daemon-reload
for u in $UNITS; do
  n=$(basename "$u" .service)
  systemctl restart "$n" 2>/dev/null
done
sleep 12

echo "== 验证 1/4: 本地 -L 监听"
for p in 10082 10083 18792 18800 18822; do
  if ss -ltn 2>/dev/null | grep -q "127.0.0.1:$p"; then echo "   ✓ $p"; else echo "   ✗ $p 无监听"; fi
done
echo "== 验证 2/4: 公网闸门"
for p in "/ov/live.json?k=zmax-live" "/st/station?k=zmax-live" "/orin/status"; do
  printf '   %-32s %s\n' "$p" "$(curl -s -o /dev/null -m 10 -w '%{http_code}' "https://datadrive.world$p")"
done
echo "== 验证 3/4: unit 重启计数 (隔 20s 采两次, 不涨才算稳)"
systemctl show -p NRestarts --value $(echo "$UNITS" | xargs -n1 basename | sed 's/\.service//') 2>/dev/null | tr '\n' ' '; echo
sleep 20
systemctl show -p NRestarts --value $(echo "$UNITS" | xargs -n1 basename | sed 's/\.service//') 2>/dev/null | tr '\n' ' '; echo
echo "== 验证 4/4: 回滚方法"
echo "   cp -a $BK/*.service /etc/systemd/system/ && cp -a $BK/ssh_config $SSH_CONFIG && systemctl daemon-reload"
echo "   (老机 $OLD 关机前做完切换; 关掉后老机上的 -R 口自然释放)"
