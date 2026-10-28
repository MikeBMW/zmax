# 右上角三色状态灯 + 控制台重启 (2026-10-15 老倪定的口径)

## 1. 三灯语义 = 可证伪的真状态 (不是装饰)

老倪原话: 「那三个状态指示灯，保留，绿色表示功能正常(可以随时进行模型推理，且所有模型可以数据闭环全流程工作)，
黄色灯光默认保持现状，工作时要以1秒为周期闪烁，表示训练正在进行(且GPU负荷平均大于50%)，红色灯光默认也是保持现状，
工作时要以1秒为周期闪烁，表示正处于真机器联调且随时可以进行机械臂操作；你来同步功能，要保证功能的准确实时显示。」

| 灯 | 亮法 | 成立的判据 (全部满足才亮/闪) |
|----|------|------------------------------|
| 🟢 绿 | 实心常亮 | ① 8790/health==200 (随时可推理) ② models/active_models.json 的 L2/L3/L4+extra 指针全部解析得到真实文件 ③ 闭环全流程入口在位: 采集台账 zmax_data/stable-wm-cache/datasets/zmax_datasets.json 有条目 · 训练 tools/joint_train_all.py · 部署 tools/model_autoload.py |
| 🟡 黄 | **1s 周期闪** (0.5s 亮/0.5s 灭)，否则空心不闪(默认保持现状) | ① 训练进程在场: 口径同 tools/gpu_load_guard.py `/proc/*/cmdline` 匹配 `lerobot[_-]train|joint_train_all|yolo_annot_train|train_*.py|auto_loop` ② GPU 利用率**滑窗平均**>50% (zmax_data/status_lights_gpu.jsonl 近 20s, ≥3 样本; 单点不算平均) |
| 🔴 红 | 同上 1s 周期闪，否则空心不闪 | ① 真机联调中: 位姿唯一依据 zmax_data/rokae_sdk/tcp_out/latest.json 帧龄 ≤2s 且非全 0 ② 随时可操作: zmax_data/ctl_auth.json `until` > now (真动授权 armed) |

- **唯一依据单一出处**: `tools/status_lights.py` (CLI 自证: `./gui-venv311/bin/python tools/status_lights.py`，`--json` 给 GUI)。
  改灯语义只改这一个文件 + studio.py 的 tooltip 文案，别在两处各写一份判据。
- GUI 接线: `_StatusLightFetcher`(QThread, 2s 采样 `status_lights.py --json`) → `_on_light_state` 只存数据；
  `_render_lights`(250ms QTimer) 只算相位贴样式。阻塞 I/O 全在后台线程，GUI 线程不冻结。
- 取不到数据必须**明标失效**，不许当现状: tooltip 首行 `⚠ 状态源已静止 Ns`，绿灯同时灭。
  (老倪的显示诚实性铁律: 任何标"当前"的量都要过源新鲜度判据。)
- 判据: `tools/verify_status_lights.py` — 14/14，含**唯一依据交叉核对**(8790 直连 / nvidia-smi 直读 / 两位姿+授权唯一依据直读)
  与**真类闪烁两相位真跑**(桩 self + 覆盖 `time.monotonic` 到 0.0s/0.6s 看样式由实心转透明)。

## 2. 控制台重启: 绝不能用 `systemctl --user restart`

`tools/gui/launch_studio.sh` 里有单实例检查 —— 已有实例就只写 `/tmp/zmax_nav_cmd` + 激活旧窗口 + `exit 0`。
重启瞬间旧进程可能还在 ⇒ 新实例被挡掉 ⇒ **服务报"启动成功"、窗口是旧的、代码是旧的(假绿)**；
实测还有一次旧进程退掉+新实例没起 ⇒ **窗口直接没了**。

⇒ 用 `bash tools/gui/restart_studio.sh` (停 → 等旧进程真死 → 起 → 必须确认新 pid + 'XSpace ZMAX' 窗口才 rc=0，日志 /tmp/zmax_studio_restart.log)。

⚠️ **单实例检查必须锚定整条 cmdline，不能用子串**: `pgrep -f "gui-venv311/bin/python studio.py"` 会命中
**任何 cmdline 里含这串字的进程** —— 包括我自己在终端里跑的那条诊断命令 ⇒ 启动脚本以为“已有实例”直接 `exit 0`
⇒ **服务报启动成功、实际一个窗口都没有** (连带现象: 后续按空几何截图会报负偏移之类噪声)。
两处统一用 `PAT='^[^ ]*gui-venv311/bin/python studio\.py$'` (`tools/gui/launch_studio.sh` + `tools/gui/restart_studio.sh`)。
同类规则: 凡用 `pgrep -f`/`pkill -f` 判“某进程在不在”，先问一句“我自己这条命令的 cmdline 里有没有这串字”。

## 3. 关窗口时进程 abort (exit -6) — 已修, 别再退回 `sys.exit(app.exec_())`

现象: 关掉控制台窗口, 日志末尾 `QThread: Destroyed while thread is still running` +
`Fatal Python error: Aborted`, 退出码 -6 并留 core。历史日志里能数出多条同样堆栈 —— 不是新毛病。

机制: `sys.exit(app.exec_())` 返回后解释器进入 finalize, 信号页回放 / 3D / 看门狗这些 QThread 还没停
就被析构 ⇒ qFatal abort。Qt 事件循环已经退出, 本来就不需要 Python 再清理。

修法 (与 SIGTERM 通道同款): `_rc = app.exec_()` 之后 flush 两个流, 再 `os._exit(int(_rc))` 跳过 finalize。

验收要在**真屏**做, 看 Fatal 计数而不是看退出码:

```bash
B=$(grep -c 'Fatal Python error' /tmp/studio_launch.log)
DISPLAY=:0 wmctrl -ic "$(DISPLAY=:0 wmctrl -l | grep 'XSpace ZMAX' | awk '{print $1}')"
sleep 8; echo "进程数 $(ps -eo args | grep -c '[s]tudio.py') · Fatal $B → $(grep -c 'Fatal Python error' /tmp/studio_launch.log)"
```

Fatal 数不变 + 进程 0 + 日志尾没有堆栈 = 干净退出。

## 4. 重启/关停的权限边界

**不许自主重启控制台** —— 用户明确制止过 (「你不要自己重启啊」)。他的窗口可能正在调试/录屏/目检,
我 kill + 拉起会把状态、断点、正在看的页面一起弄丢, 而且他分不清是崩了还是被我重启了。

- 改完代码只给命令: `bash tools/gui/launch_studio.sh` (或 VSCode F5), 由他决定何时重启。
- 为了自己验收而起的实例, 验完**立刻 kill 自己那一个**, 并在回复里说明「我起的那个已停」。
- 必要时先问一句再动; 宁可多等一轮, 不要自主重启。
- **他会几秒内自己按 F5**: 我拉起脚本后 ~7s 他也重启了一次 ⇒ 桌面上两个控制台。识别办法:
  `ps -eo pid,lstart,args | grep '[s]tudio.py'` —— 带 `/home/ubuntu/.vscode/extensions/ms-python.debugpy…`
  那一对是他的 F5 调试进程, 纯 `gui-venv311/bin/python studio.py` 是我起的; 只 kill 后者。
- 判断“他现在有没有控制台”: 不光看进程, 还要看窗口 `/proc/<pid>/cwd` +
  `DISPLAY=:0 wmctrl -l | grep 'XSpace ZMAX'` —— 窗口才是他在用的那个。


## 5. 验证界面的取证坑 (踩过的)

- **截图区域别用 `wmctrl -lG` 的 y 当客户区顶** —— 实测该 y 比真实客户区顶低 ~48px，
  按它裁出来正好从菜单栏下方开始: 会以为"菜单栏/品牌/三灯没渲染"。
  可靠做法: 多留边裁(如 `scrot -o -a "x-20,y-60,w+40,h+120"`)，再**按菜单栏底色 #161b22 在截图里定位行带**
  (该带 36px 高，品牌小字与三灯都在带内；三灯 14x14 圆点，绿实心≈132px、黄/红空心≈44px)。
- 判据脚本里做"源码里不许出现某文案"时**只判非注释行**: studio.py 顶部有巨量 changelog 注释，
  历史文案留在注释里是正常的，整文件断言会假红。
- 采样线程的异常必须落盘 (`/tmp/zmax_light_fetcher.log`): 本次 `dirname(dirname(__file__)) + "tools/status_lights.py"`
  拼成 `tools/tools/...` → rc=2，被 try/except 静默吞掉 ⇒ 三灯全灭还不报错。**静默失败 = 最贵的失败。**
- QThread 的 signal 连到主线程槽需要主线程事件循环在跑；离线单测里不给 `app.processEvents()` 会"收到 0 轮"。
