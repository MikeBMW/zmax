# 手机远程操作 (公网) — 链路与开关

> 2026-10-01 老倪:「远程控制app检查一下, 要实现手机远程操作」。
> 结论先行: 改之前手机(APP/网页)在公网**只能看不能动** —— 闸门对 POST 一律 403、`/room` 页也不在放行清单;
> 现在: 闸门加一个开关(`--allow-ctl`)放行**三个控制端点 + 控制页**, 机械臂仍受 8793 的两步授权 + 10 分钟失效约束。

## 1. 链路

```
手机 APP (com.zmax.room v1.2)
  ├─ 公网优先: https://datadrive.world/st/room?k=zmax-live
  │     └─ ECS nginx ─ /st/* ─▶ 反隧道 18793 ─▶ 工控机 127.0.0.1:8893
  │                              (zmax-station-gate = tunnel_proxy.py --mode station)
  │                                       │  白名单放行只读页 + (开了 --allow-ctl 时) /room 与三个控制 POST
  │                                       ▼
  │                                 127.0.0.1:8793  (cam_live_stream.py; 页面 + /ctl/*)
  │                                       ▼
  │                                 真机执行链 (授权闸门 → 规划 → 珞石控制器)
  └─ 产线网兜底: http://10.163.146.78:8791/room  (手机在厂内时直连, 最快)
```

## 2. 开关(默认关)

```bash
# 打开手机远程操作(改 unit 的 ExecStart 加 --allow-ctl 并重启闸门)
bash tools/station_gate_remote_ctl.sh on
# 关掉, 回到"公网只读"
bash tools/station_gate_remote_ctl.sh off
```

## 3. 放行清单(极窄)

| 类别 | 内容 | 备注 |
|---|---|---|
| 页面(GET) | `/room` · `/room.html` | 手机控制页, 与 `/station` 同等待遇 |
| 控制(POST) | `/ctl/arm`(授权/撤销) · `/ctl/move`(运动) · `/ctl/gs_map`(L5 指导选点建图) | 必须带口令 |
| 只读(GET) | `/station` · `/snapshot/*.jpg` · `/*.mjpg` · `/ctl/status` · `/motion` · `/stats` · `/dl/*` … | 与改动前一致 |

**永不放行(与开不开远程无关)**: `/gen` `/tap` `/api/aoi/*` `/api/ctl/*` `/api/relay/*` `/api/train*`
`/cmd` `/skill` `/teach` `/hil/*` `/agent/*`。

## 4. 安全不变量

1. **口令**: 无 `?k=<token>`(或 cookie)一律 403 —— 实测无口令 POST/GET 都是 403。
2. **真动仍要 8793 的授权**: 未授权时 `/ctl/move` 返回 `演练(未下发): 未授权真动`, **机械臂不动**(实测)。
3. **10 分钟自动失效** + 每次授权/撤销都进 8793 的审计(`events`); 闸门另外把**每个放行的控制 POST**
   打进 `/var/log/zmax-station-gate.log`(时间 · 路径 · 字节 · 来源 IP)。
4. **页面两步确认**: 控制页第 1 次点击只是本地确认提示(6 秒内要点第 2 次才发 POST),
   服务端收到的是**一次** `POST /ctl/arm {on:true, note}`。
   ⇒ 服务端没有"第二把钥匙", 谁能发这个 POST 谁就能授权(局域网页一直是这个口径)。
   若要"必须现场有人配合"(例如现场屏幕显示一次性码、手机上输入)需要另加服务端二次因子。

## 5. 页面口径(https vs http)

`tools/web/room.html` 里:

```js
const SECURE = location.protocol === "https:";
const BASE = SECURE ? location.pathname.replace(/\/room(\.html)?$/, "") : ""; // 公网 = /st
const API = SECURE ? BASE : ("http://" + H + ":8791");   // 公网: 同源相对路径(不撞混合内容)
const HIL = SECURE ? ""   : ("http://" + H + ":8795");   // 公网: 不开放(如实提示)
```

公网下 HIL 聊天与 AOI 拍照**如实提示不可用**(不放假装能发的按钮)。

## 6. 实测(从公网 curl, 2026-10-01)

```
GET  /st/room                     → 200 (26KB, 含控制按钮)
POST /st/ctl/arm  {on:false}      → 200 (all" armed" 状态回包; 撤销可用)
POST /st/ctl/move {skill:...}     → 200 "演练(未下发): 未授权真动" ⇒ 通道开, 未授权不动臂
POST /st/ctl/move (不带口令)       → 403
GET  /st/room     (不带口令)       → 403
POST /st/cmd · /skill · /teach · /gen · /api/aoi/capture · /api/ctl/move → 403
GET  /st/station · /ov/overlay · /state-3d.html → 200 (无回归)
GET  /st/dl/ZMAX-Site.apk         → 200; sha256 == 页面校验串 == 3e387ef5d57e…
```

## 7. APP

包名 `com.zmax.room`(「Z-MAX 现场」), v1.2 / versionCode 3, 与旧版同签名(可直接覆盖安装)。
候选地址: 公网 → `http://10.163.146.78:8791/room` 兜底, 主框架失败自动换; 长按屏幕可手改地址。
打包: `bash tools/app/room/build_room_apk.sh`(自动投递到 `tools/web/dl/ZMAX-Site.apk` 并把哈希写回页面)。

## 8. 授权链两个真 bug 与修法 (2026-10-02)

老倪「授权远程」后实测暴露的两个问题, **都在我们自己的服务端**(不在 ECS、不需要 frp):

### 8.1 页面显示「授权IP 127.0.0.1」—— 真实 IP 没透传
链路是 `手机 → ECS nginx → ssh -R 隧道 → 本机闸门(8893) → 8793`, 闸门转发时**只当了 TCP 中继**,
上游 8793 看到的是 `127.0.0.1` ⇒ 授权审计丢了"谁授的权"。
修: `tools/tunnel_proxy.py` 新增 `_real_ip()`, 把 nginx 放进来的 `X-Real-IP` / `X-Forwarded-For`
在 **GET/POST 两条转发路径**都带给上游; `tools/cam_live_stream.py` 同样加 `_real_ip()`,
`/ctl/arm` 记录授权 IP 时用它。
安全边界: **只在本机回环 peer(127.0.0.1/::1)上采信这两个头** —— 产线网里别的机器直连时头可伪造,
一律回退真实 peer。
实测: 本地带 `X-Real-IP: 203.0.113.77` ⇒ 记到 `203.0.113.77`; 公网 `/st/ctl/arm` ⇒ 记到
**221.224.165.74**(本机真实公网出口), 事件表尾部可见 `127.0.0.1 → 221.224.165.74` 的变化。

### 8.2 现场页「✅ 记为该号位 / 清点位」走公网必 403
这两个按钮 POST 的是 `/ctl/record_point` / `/ctl/clear_point`, 而闸门的放行清单只列了
`/ctl/arm · /ctl/move · /ctl/gs_map` ⇒ 页面点了没反应(403 是闸门给的, 不是 8793)。
修: 两个端点加进 `ALLOW_POST_CTL`。**依据**: 它们不下发任何运动(record_point 只把当前 TCP 真值
写进示教点库, 服务端另有 slot1~7/space1~7 名字白名单 + 静置判据), 真正能动臂的仍然只有
`/ctl/arm` + `/ctl/move` 且要两步确认。

### 8.3 顺带挖出的第三个 bug(与远程无关, 但同样致命): 号位记录**任何入口都失败**
`/ctl/record_point` 修好后仍报「采样不足 (1 帧)」。真因: `rokae_tcp_sampler` 容器
**在启动那一刻就定死文件名** `tcp_direct_<启动日>.jsonl`, 跨天后继续往旧名字里写(现场那个文件
已 212MB 还在长); 而 `tools/record_l2_point.py` 用 `time.strftime("%Y%m%d")` 拼"今天"的名字
⇒ 找不到文件 ⇒ 快路必抛 ⇒ 退回 SSH 慢路(十几秒只采到 1 帧) ⇒ 记录失败。
修: 新增 `_newest_truth_jsonl()` 挑**最新**的那个文件(新鲜度仍由"帧龄 >2s 拒用"把关)。
实测: `record_l2_point.py space7 --dry` ⇒ **采样 6 帧 / 0 ms / 极差 1e-6 m**(之前 1 帧失败)。

### 8.4 最要命的一个: 手机上「授权成功了, 方向键却是灰的点不动」
**口径不一致**: `/station/status` 返回的授权状态**嵌在 `ctl.auth` 里**
(`{armed, left_s, window_s, ip, ...}`), 而手机页 `room.html` 的 `applyCtl()` 只读顶层
`a.armed` ⇒ 永远 `undefined` ⇒ `ARMED=false` ⇒ `button[data-sk]` 全部 `disabled`
(顺带授权IP 也显示不出来)。
实测对照: 服务端 `armed=true`、`/ctl/arm` 回 `{"armed": true, "left_s": 600, "ip": "221.224.165.74"}`,
页面却仍显示"🔒 未授权/🔒 只看不动"。
修: `applyCtl()` 改成 `const au = a.auth || a;` 再取 `au.armed/au.left_s/au.ip`
(兼容两种口径, 老服务端平铺也认)。
实测(公网页): 两步授权后 `ARMED=true` · 横幅「🔓 已授权真动 —— 剩 538s … · 授权IP 221.224.165.74」·
`#ctlMeta`「✅ 可动 · 剩 538s」· 6 个方向键 `disabled` 全为 `false` ✓
注: `station.html` 走的是 `applyAuth(s.auth)` ✅ 本来就对, 只有手机页错。
