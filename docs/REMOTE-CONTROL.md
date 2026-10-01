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
