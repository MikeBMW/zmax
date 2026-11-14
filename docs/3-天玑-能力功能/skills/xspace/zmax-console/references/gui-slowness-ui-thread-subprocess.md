# GUI 慢/卡顿: UI 线程里的同步子进程（不是负载）

## 症状
点画布节点（右键菜单）、翻页一顿一顿；但 `curl http://127.0.0.1:8799/` 仍然 <1ms。
⇒ **不是服务慢、也不是机器不行**，是 Qt 事件循环被堵住。用户此时问“GUI 怎么还是这么慢”，不要拿负载数字回他。

## 判据（两条一起看）
```bash
sudo py-spy dump --pid $(pgrep -f '/gui-venv311/bin/python studio.py')
# 主线程栈: select (selectors.py) ← _communicate ← communicate ← run (subprocess.py:550)
#           ← _poll_train_state ← _poll_ext_log ← _show_node_menu ← mousePressEvent
# ⇒ UI 线程正在等一个子进程
ps -eo pcpu,pid,args --sort=-pcpu | head
# 同时有 GUI 拉起的长命令在吃 CPU（实测 `du -sm /home/ubuntu/zmax` 占 106%）
```

## 机制
点击路径 `mousePressEvent → _show_node_menu → _poll_ext_log → _poll_train_state` 里：
- 每次调用 `subprocess.run(["pgrep", "-f", "lerobot_train"], timeout=5)`，同步等最长 5s；
- 点一次就重读一遍日志文件；
- 子进程一慢（`du` 扫大目录）整个窗口冻住 ⇒ 用户感知为“GUI 越用越慢”。

## 修法（三件缺一不可）
1. **检测类工作绝不在 UI 线程 spawn 子进程**：改纯 `/proc` 扫描取 cmdline。
   287 进程全扫实测 ≈17ms，直接放点击路径仍可感 ⇒ 必须再加 **缓存 + daemon 线程刷新**
   （TTL 5s，stale 起后台线程，busy 标记防排队），UI 侧只读缓存 = 0 等待。
2. 点击路径上的轮询加 **0.3s 节流**，不要每次点击都读文件。
3. 磁盘体积统计（`du -sm`）一律不进 UI 路径。

## 验收
- 改前 `/8799` 35ms + 点节点整窗卡死；改后 0.9ms + 点节点不顿。
- GUI 重启取证三件：新 pid · `wmctrl -l` 有窗口 · `curl /8799` 200。
- 启动口径照 `tools/gui/launch_studio.sh`（`cwd=tools/gui`、`DISPLAY=:0`、`QT_QPA_PLATFORM=xcb`，
  先 `unset` 再 `export`；否则继承的 offscreen 会“进程活着、没窗口”）。

## 降真实负载（可选，别当第一招）
先证 GUI 自己不再堵，再动服务：`cam_live_stream --fps 30→15 --quality 72→64` 实测 311%→119%（省 ~1.9 核）；
同轮对照 load 14.9→12.2、idle 47%→74%、cs 186k→88k/s。

## 边界
用户说「你都重启好」= 授权重启 GUI 与该流服务；但 **8797 / 8793 挂着真动授权和 AR 页面，不要顺手重启**。
