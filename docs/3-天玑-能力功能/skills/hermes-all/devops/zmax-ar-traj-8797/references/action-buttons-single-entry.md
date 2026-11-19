# 8797/ar3d 动作按钮：只留一个入口

## 现状（用户口径，别再加回来）

页面动作入口只有一个：`#bRTraj`「▶ 右臂跑真实轨迹」→ `runRealTraj()`。

- 默认档 `⚡真实回放`（`TRAJ_SPEED_MODE='real'`），点一下 = 真机从当前游标沿 215 点走到底；
  游标在末尾（`cursor>=total`）先自动 `POST {"reset":true}` 再跑。
- 速度三档 `bSpdX1/bSpdX2/bSpdReal` 只改这同一个变量，**只影响下一个下发**，不动在途动作。
- 单步 `⏭ 单步 +1 点` 固定走 `x1`：单点是检视，不给高速档。

## 已删除、不要恢复

`👻 预览动作(bPrev)` · `⟲ 同步真值(bSyncTruth)` · `🔌 插入仿真(bIns)` · `🔁 插拔全流程(bInsp)`
· `⏭ 同步操作 N 点(bSyncStep)` · `⏭⏭ 连走 +10 点(bTrajStep10)` · `↺ 回起点(bSyncReset)`。

## 规则

1. **按钮名字必须等于他点了真会发生的事。** 名字里写「跑真实轨迹」而实际只动仿真的按钮，
   现场只会得到一句「你没有动啊」，然后整页被判「太复杂」。仿真入口要么删，要么文案写死「只仿真·不动真机」。
2. **删按钮必须同步处理 JS。** `$('bX').addEventListener(...)` 一律包 `if($('bX')) …`；
   一个 null 就能让整页脚本停摆（后面所有按钮全失效，而控制台只报一行）。
3. **`cSyncArm` 不要删元素。** 单步/同步旧逻辑有 5 处读它 ⇒ 改成 `style="display:none"` + `checked`，语义恒为「真机也走」。
4. **`tPrev`/`tIns` 这类被删按钮的状态 span 保留但 `display:none`**，旧函数还在往里写。

## 验收（零运动）

浏览器控制台一次读回：
```js
({hasFn: typeof runRealTraj, mode: TRAJ_SPEED_MODE,
  gone: ['bPrev','bIns','bInsp','bSyncTruth','bSyncReset','bTrajStep10','bSyncStep']
          .filter(i=>document.getElementById(i)),
  btn: document.getElementById('bRTraj').textContent})
```
判据：`hasFn==='function'` · `gone` 为空 · 文字是「▶ 右臂跑真实轨迹」· `js_errors` 为 0。

再发一次全量演练确认服务端受理：
```bash
curl -s -X POST -d '{"n":215,"start":0,"dry":true,"speed_mode":"real"}' \
  http://127.0.0.1:8797/api/arm/step_traj
# 应回 ok=true · speed_mode=real · speed=100.0；日志 grip_plan 为 {9:close, 205:open}
```

## 「我点了，你没动」的第一条判据

`zmax_data/tcp_ar_server_restart.log` 里没有 `POST /api/arm/step_traj` ⇒ **按钮根本没发请求**
（点错按钮 / 前端被 busy 拦 / handler 报错）。有 POST 但臂不动，才是服务端闸门或执行器的问题。
先看日志再看授权，顺序反了会把「点错按钮」误诊成「授权失效」。
