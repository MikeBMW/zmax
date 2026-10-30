#!/bin/bash
# 在 550C 上建与云端同名的 MySQL 账号 (密码取自云端 wp-config.php, 不回显)
set -e
PW=$(sudo ssh -i /root/.ssh/id_ed25519 -o StrictHostKeyChecking=no root@47.93.88.143 \
      "sed -n \"s/.*DB_PASSWORD'[[:space:]]*,[[:space:]]*'\(.*\)'.*/\1/p\" /www/wwwroot/datadrive.world/wp-config.php" | tr -d '\r')
if [ -z "$PW" ]; then echo "读不到 DB_PASSWORD"; exit 1; fi
sudo mysql -e "CREATE USER IF NOT EXISTS 'xSpace'@'localhost' IDENTIFIED BY '$PW'; GRANT ALL PRIVILEGES ON xSpace.* TO 'xSpace'@'localhost'; ALTER USER 'xSpace'@'localhost' IDENTIFIED BY '$PW'; FLUSH PRIVILEGES;"
echo "账号已建, 校验:"
mysql -u xSpace -p"$PW" -N -e "select concat('wp_posts=', count(*)) from xSpace.wp_posts" 2>/dev/null || sudo mysql -N -e "select concat('wp_posts=', count(*)) from xSpace.wp_posts"
