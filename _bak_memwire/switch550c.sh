#!/bin/bash
# 把 datadrive.world 从「云端本机站点」切到「经隧道由 550C 提供」
# 自带回滚: 验证不过立刻还原旧配置并 reload
set -u
CFG=/etc/nginx/sites-available/datadrive.world.conf
BAK=${CFG}.20261030.bak
THIN=/etc/nginx/sites-available/datadrive.world.thin.conf
LIN=/etc/nginx/sites-enabled/datadrive.world.conf

[ -f "$BAK" ] || cp -a "$CFG" "$BAK"

rollback() {
  echo "!! 回滚: $1"
  cp -a "$BAK" "$CFG"
  nginx -t >/dev/null 2>&1 && nginx -s reload
  sleep 1
  echo -n "回滚后站点: "; curl -s -o /dev/null -w "%{http_code}\n" --max-time 8 -H "Host: datadrive.world" http://127.0.0.1/
  exit 1
}

cp -a "$THIN" "$CFG" || rollback "拷入新配置失败"
nginx -t >/dev/null 2>&1 || rollback "nginx -t 不通过"
nginx -s reload
sleep 2

echo "== 隧道侧自检 =="
for u in / /ss3d_live.json /api/whoami; do
  printf "  %-18s " "$u"
  curl -s -o /dev/null -w "%{http_code}\n" --max-time 10 -H "Host: datadrive.world" http://127.0.0.1:18790$u
done
code_root=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 -H "Host: datadrive.world" http://127.0.0.1/)
echo "  公网入口本地自测: $code_root"
[ "$code_root" = "200" ] || rollback "站点根不是 200 (拿到 $code_root)"

echo "== 切换完成, 旧配置备份: $BAK =="
