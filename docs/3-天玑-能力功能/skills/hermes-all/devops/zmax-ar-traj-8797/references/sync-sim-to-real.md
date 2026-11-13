# 「仿真先走→真机逐点走」链路 (2026-11-13 现场)

页面 `syncStepPlay()` = 仿真平滑走过去 → 走完调 `syncArmRun(n, start)` 发 `POST /api/arm/step_traj {n,start}`。

## 🔴 真机一点没动、连 POST 都没有 ⇒ 先看勾选框，不是网络
`syncArmRun` 原来是：
```js
var cb=document.getElementById('cSyncArm');
if(!cb||!cb.checked) return;      // 静默退出: 仿真照走, 真机零下发, 8797 日志里连 POST 都没有
```
现场表现 = 「仿真动了，真机没动，也不知道为什么」。已改成红字/黄字显式提示未勾选。
判据链（按顺序）：① `sudo tail /var/log/zmax-traj-ar.log` 有没有 `POST /api/arm/step_traj`
② 没有 → 前端就没发（勾选框 / 旧 JS / 前一次播放仍 `SYNC.playing` 使首次点击变成“停止”）
③ 有 POST 但 `ok:false` → 看 `stage/err`（`stage=jump` 见下）。

## 防瞬移闸：`stage=jump` + `near` 就是「你其实在第 N 点」
`POST` 拿 `frames[start]` 与当前关节真值比，>30° 直接拒发，回 `{"ok":false,"stage":"jump","near":69,...}`。
`near` = 最接近的帧下标 ⇒ **正确动作是把 start 挪到 near 再走**，不是把臂掰回 start。
实测：轨迹会自我重叠——第 1~3 点与第 70 点物理上是同一处（到第 4 点差 33.7°，到第 70 点差 0.13°）。

## 批量口径
- `start` 是被真正使用的（`frames[_start:_start+_n]`），`n` 不越过末端；响应里 `start` 回显实际起点。
- 215 点 / 速度 20% ⇒ 约 25 分钟；**授权只在开跑那一刻校验一次**，中途到期不打断。
- 授权窗口 2026-11-13 起 30 分钟：`ctl_auth.DEFAULT_WINDOW=1800`，且落盘 `ctl_auth.json` 的 `window` 也要改
  （已 armed 的窗口以文件里的 `until` 为准，光改代码不会延长当前那次）。
