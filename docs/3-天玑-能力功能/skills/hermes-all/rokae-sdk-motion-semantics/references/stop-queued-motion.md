# 停止在动的真机 (MoveAbsJ 指令队列跨客户端存活)

## 现象
回放脚本被 `kill` / 容器被 `docker kill` / 页面被关掉之后，臂**还在动**，
而且 `/status` 的 TCP 一直变。停下来只有一种办法：**新开会话发 `moveReset`**。

## 为什么
`moveAppend` 下发的指令序列在**控制器内部排队**，客户端断开不会清队列。
所以：进程没了 ≠ 运动停了。

## 标准停法
```bash
bash tools/rokae_sdk_run.sh --script arm_stop.py     # 新写的小脚本, 发 moveReset
for i in 1 2 3; do curl -s http://127.0.0.1:39071/status | ...TCP; sleep 4; done
```
只有**三次 TCP 采样完全一样**才算停住（认真值，不认"进程没了"）。

## 踩过的坑
- 点 `about:blank` 只停页面自己的定时器，臂不停。
- `docker kill` / `kill -9` 掉执行体，臂**继续**走完队列。
- `tools/agent_all_stop.py` 只扫命名脚本(l2_daemon 等)，抓不到 `arm_step_traj.py` 里的 docker 执行体。
- xCoreSDK 里 `moveStop`/`movePause` 在某些版本不存在（报 `no-api`），`moveReset` 在。

## 顺带
现场页面上任何 `▶ 执行轨迹` / `▶ 右臂跑…` 按钮都按"会动真机"对待：
先读 `id` 与 handler，别按按钮文字模糊匹配去点（ar3d 的 `bRTraj` title 写"只仿真"，实际真机跑了）。
