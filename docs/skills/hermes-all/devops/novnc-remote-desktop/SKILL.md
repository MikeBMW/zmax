---
name: novnc-remote-desktop
description: Use when 要浏览器/手机远程看+操作 Linux 桌面或 websockify 转发 VNC 失败.
---

# noVNC 远程桌面 (X 桌面 → 公网浏览器)

给不在同一网络的用户提供「网页里实时看 + 真实鼠标操作」远程桌面。数据流:
**浏览器 → nginx(https) → WebSocket bridge → 反向隧道 → x11vnc(本机 :0)**

## 架构总览
```
手机浏览器
  → https://datadrive.world/novnc/vnc.html   (nginx 直服务静态文件)
  → wss://datadrive.world/novnc/websockify    (nginx 仅代理此路径)
  → ECS 127.0.0.1:6080  [自定义 asyncio bridge 或 websockify]
  → ECS 127.0.0.1:5900  (sshd 反向隧道 -R)
  → 本机 5900  x11vnc -display :0 -nopw
```

## 关键步骤
1. **本机 x11vnc**（无密码模式最省事）:
   `XAUTHORITY=$(tr '\0' '\n' < /proc/<gnome-shell-pid>/environ | grep ^XAUTHORITY | cut -d= -f2-)`
   `x11vnc -display :0 -nopw -forever -shared -noxdamage -bg`
   验证: python3 `socket.create_connection(('127.0.0.1',5900))` → recv 应见 `RFB 003.008`
2. **反向隧道**（ECS 5900 → 本机 5900）:
   `sshpass -p <pw> ssh -N -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes -R 5900:localhost:5900 root@datadrive.world`
   隧道断了要**先杀 ECS 侧占用 5900 的 sshd 转发进程**再重建: `ss -tlnp | grep :5900` 取 pid kill。
3. **WebSocket bridge**: ⚠️ 不要用 stock websockify 转发 VNC——见下方 bug。用 `scripts/vnc_ws_bridge.py`（ECS 上 systemd 常驻 `/etc/systemd/system/vncbridge.service`, `Restart=always`）。ECS 起服务用 `setsid ... &` 或 systemd，ssh 会话内 `nohup &` 会被杀。
4. **nginx**: 静态文件与 WebSocket 必须分开两个 location（bridge 不服务静态文件; 全代理会让 vnc.html 都 426）:
   - `location ^~ /novnc/` → `alias /www/wwwroot/datadrive.world/novnc/; try_files $uri $uri/ /novnc/vnc.html;` + 内嵌 `location /novnc/websockify { proxy_pass http://127.0.0.1:6080/websockify; proxy_http_version 1.1; proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection "upgrade"; proxy_set_header Origin $http_origin; }`
   - 去掉密码: 删 `auth_basic`/`auth_basic_user_file` 两行。
   - reload 用 BT 面板路径 `/etc/init.d/nginx reload`（`nginx -s reload` 因 PID 文件错位常失败）。
5. **验证全链路**（python websocket-client）: 连 `wss://datadrive.world/novnc/websockify` → recv RFB → send `RFB 003.008\n` → recv 安全类型 `\x01\x01`(None) / `\x01\x02`(VNC auth)。见 `scripts/verify_ws.py`。

## 手机 URL
`https://datadrive.world/novnc/vnc.html?autoconnect=1&resize=scale&reconnect=1`
- `resize=scale` 自动缩放适配手机; 用户也可在 ⚙️ → Scaling Mode → Local Scaling。
- 手机: 单指移动鼠标/点击, 双指滚动。

## ⚠️ Pitfalls
- **websockify 转发空字节的 bug 是版本/链路相关的, 别一概否定 websockify**: 症状 = RFB 版本能收到、安全类型字节永远为空(0B), x11vnc 日志 `rfbProcessClientProtocolVersion: client gone`(ECS 公网链路上实测)。
  但**同一台机器上, 本机 `127.0.0.1` 路径的 stock websockify 实测转发正常** ⇒ 遇到空字节先换链路复现(本机 ↔ 公网)再判是 websockify 还是链路;
  真坏了再用自写 asyncio bridge(scripts/, 实测公网全通)。
- **`websockify` 没有 `--listen` 选项**(实测报 `no such option: --listen`): 只绑本机要写**位置参数** `host:port` ——
  `websockify --web=/usr/share/novnc 127.0.0.1:6080 127.0.0.1:5900`。漏了地址段它会监听 `0.0.0.0`(局域网都能看你桌面),
  判据: `ss -ltn | grep 6080` 必须只有 `127.0.0.1`。
- **转发通不通的判据是 WebSocket 握手 + RFB 首帧**, 不是 `curl vnc.html` 200: 手写握手应收 `101 Switching Protocols`,
  且第一帧 payload 是 `RFB 003.008`(websockify 该版本不发 `Sec-WebSocket-Protocol: binary` 时也能连上)。
- **websockets 库报 "invalid Origin header: multiple values"** → nginx 加 `proxy_set_header Origin $http_origin;` 规范化; bridge 侧 `process_request` 返回 None 忽略校验。
- **noVNC 静态资源 404/页面 426**: 分清「静态文件由谁服务」; vnc.html 是 ES module 页, 资源缺一个 UI 就白屏。逐个 curl 200 检查 app/ui.js core/rfb.js core/util/*.js。
- **ssh 会话杀后台进程**: ECS 上 `nohup cmd &` 在 ssh 断开后被杀 → 用 `setsid ... < /dev/null &` 或 systemd。
- **x11vnc -ncache 与协议**: 排查问题时去掉 `-ncache` 减少变量。

## 本机就地用: 只要"看+操作某个窗口", 不需要 ECS/nginx
把 VNC 当**本机 GUI 的另一种承载形式**(例: 在 VSCode 编辑器标签页里嵌一个 PyQt 桌面程序的原界面)时,
全程只跑本机两个进程, 不要引隧道:
```bash
# ① 只共享那一个窗口, 不是整个桌面 —— -clip 用窗口几何(xdotool 取), 画面大、看得清
W=$(DISPLAY=:0 xdotool search --onlyvisible --name "<窗口标题>" | head -1)
eval "$(DISPLAY=:0 xdotool getwindowgeometry --shell $W)"      # → X Y WIDTH HEIGHT
x11vnc -display :0 -auth /run/user/$(id -u)/gdm/Xauthority -clip ${WIDTH}x${HEIGHT}+${X}+${Y} \
       -nopw -forever -shared -localhost -rfbport 5900 -bg
# ② 转网页(只本机)
websockify --web=/usr/share/novnc 127.0.0.1:6080 127.0.0.1:5900
```
- ⚠️ **`-clip` 是启动时快照的区域, 不跟随窗口**: 窗口挪动/改大小后要重起 x11vnc(封装成 `--restart` 的幂等脚本);
  想整轮桌面用就 `ZMAX_VNC_CLIP=screen`。先启动目标程序再起 VNC, 否则拿不到窗口几何。
- 消费端可以就是 VSCode 编辑器标签页: `vscode.commands.executeCommand('simpleBrowser.show', 'http://127.0.0.1:6080/vnc.html?autoconnect=1&resize=scale')`
  (兜底链 `simpleBrowser.show` → `simpleBrowser.api.open` → `vscode.env.openExternal`); 见 `zmax-vscode-extension`。
- **排查桌面"卡"时不要先怀疑 x11vnc**: 实测它常驻 **0.0% CPU**(即使正在被 noVNC 拉流) —— 桌面卡先量按进程的 GPU sm%(见 `linux-host-maintenance` §1b)。

## 相关文件
- `scripts/vnc_ws_bridge.py` — 干净的 asyncio WebSocket↔TCP 双向透传 bridge（替代坏 websockify）
- `scripts/verify_ws.py` — 公网 VNC 握手验证脚本
