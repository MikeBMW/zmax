# datadrive.world 迁移到 550C · 2026-10-30

## 拓扑
公网 47.93.88.143 (EIP) / 172.18.193.251
  └ nginx (TLS 终结 + 证书 + /models/ 暂留) :80 :443
      └ location / → 127.0.0.1:18790   (SSH 反向隧道, 只绑 127.0.0.1)
          └ 550C 192.168.23.70  zmax-ssh-tunnel.service
              └ nginx :8081 (server_name datadrive.world, root /home/intel/zmax_web)
                  ├ php8.3-fpm  → WordPress (DB xSpace @ localhost)
                  └ 反代到本机服务 8765 / 39053 / 39061 / 39062 / 39063 / 39064 / 8901

## 550C 上的服务 (systemd)
| unit | 端口 | 脚本 |
|---|---|---|
| zmax-ws-server   | 8765  | /home/intel/zmax_web/ws-server.py (团队聊天 WS) |
| zmax-dds-ws      | 39062 | /home/intel/zmax_web/dds_ws_gateway.py (DDS 遥测 WS) |
| zmax-bili-proxy  | 39063 | /home/intel/zmax_web/bili_proxy.py |
| zmax-cam-relay   | 8901  | /home/intel/zmax_web_svc/cam_relay.py (相机中转/live) |
| zmax-training-api| 39061 | /home/intel/zmax_web_svc/training-api.py |
| zmax-ws-bus      | 39064 | /home/intel/zmax_web_svc/zmax_ws_bus.py (总线, token 鉴权) |
| zmax-relay       | 39053 | /home/intel/zmax_relay/zmax_relay.py (relay/快照) |
| zmax-ssh-tunnel  | —     | SSH -R 18790 → 本机 8081 |

## 关键事实
- MySQL: 库 xSpace, 账号 xSpace@localhost (密码同云端 wp-config.php), 56 张表 / wp_posts 322 行
- PHP: 8.3 (云端原本 8.1), socket /run/php/php8.3-fpm.sock
- 站点根: /home/intel/zmax_web (chown www-data, /home/intel 需 o+x 允许 nginx 穿越)
- 全站无密码, 走 ANDROID_ID 设备绑定 (逻辑在 PHP/JS, 未改)
- APK keystore 不在云端 (/root/zmax-apk 不存在) —— 打包签名机不变, 与本次迁移无关
- /models/ 2.0G 暂留云端本地, 迁完后把云端该 location 删掉即可

## 回滚 (一条命令)
云端: cp /etc/nginx/sites-available/datadrive.world.conf.20261030.bak /etc/nginx/sites-available/datadrive.world.conf && nginx -t && nginx -s reload
