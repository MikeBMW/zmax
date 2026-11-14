---
name: zmax-real-traj-215-autorun
description: Use when 一键跑真机215点全流程或加授权时长档。
---

# 真机 215 点全流程自动执行 + 授权两档

## 链路（只有一条，别造第二条）
```
入口 src/lerobot/engineering/start.py    ZMAX_AUTO_TRAJ=1
  └─ state_space/real_traj_flow.py      RealTrajFlow.tick()  每轮 10 点
       └─ POST 8797 /api/arm/step_traj  {n, start, speed, dwell_ms, dry, grip}
       └─ GET  8797 /api/arm/step_traj/status   进度 cursor/done
```
- 轨迹真源 `tools/web/real_traj_joints.json`（215 帧关节角真值）；夹爪动作另由 `real_traj_grip.json` 计划给（录制未记夹爪事件）。
- 游标 `zmax_data/rokae_sdk/traj_step_state.json`；撞 30° 跳变闸返回 `stage=jump` ⇒ POST `{"align":true}` 把游标挪到真机最近点再继续。
- `dry:true` 时 8797 跳过授权与跳变闸，且**不推进 cursor** ⇒ 客户端必须自己按 `start+done` 推进并把 `start` 显式传回去，否则同一段会无限重发（实测刷了 33 轮才发现）。
- cursor 到末端要先 `{"reset":true}` 才能再跑整轮；`ZMAX_TRAJ_KEEP=1` = 续跑不重置。
- 驱动分工：连续档用 1Hz 守护线程 `zmax-traj-flow`（引擎一次全量 pass 几十秒，拍子带不动）；单步档必须由每拍 hook 驱动，**不许起线程**（单步模式会把线程内联成死循环）。
- 对外进度只两处：`zmax_data/ss_live/traj_flow.json` 与 8797 `GET /api/arm/traj_flow`。

## 授权两档（唯一真源 tools/ctl_auth.py）
- `mode="window"`：until=since+1800，到点自动失效；`mode="debug"`：until=0、left_s=None，无时间限制，只有 revoke 结束。`armed = debug or until>now`。
- **任何地方都别自己算 `until-now`**：调试档 until=0 会被当成未授权（8797 的 step_traj / exec_plan 就踩过）。统一走 `ctl_auth.check()` / `info()`。
- 撤销：`until=0 + revoked_at + epoch+1` ⇒ 在途/排队命令作废（命令带旧 epoch 一律拒发）。
- 8793 页面：授权按钮旁加时长下拉（⏱30 分钟 / 🔧 调试·无限制），两步确认不变；显示 `mode` 才能分清“无限”与“剩 N 分”。
- 入口第一件事打授权：`start.py::_auth_probe()` 输出 ✅/⛔ + epoch/ip/mode，并在 hook 里检测变化（撤销要当场可见）。

## 8793 / 8797 的重启姿势
- 这两个是**裸进程，不在 systemd**（用 `ss -ltnp` 拿 pid），别猜 unit 名。
- 正确重启：读 `/proc/<pid>/cmdline`+`cwd`+`environ` → SIGTERM 等退出 → `Popen(argv, cwd=..., env=env, start_new_session=True)`，这样 `--ctl-motion`、`--port 8793`、ZMAX_* 都不会丢。
- 页面是 `Cache-Control: no-store` ⇒ 改完只需普通 F5 一次；已开的 tab 不会自动换 DOM。
- 先判断是否真需要重启：改 HTML 不用；只有服务端 Python（新端点、authorize 签名、授权网关）才需要。

## 夹爪怎么"跟真轨迹一样"(录制没记夹爪事件时)
- 事实: `real_traj_joints.json` 只有关节角/`p`, 录制那段没有夹爪事件 ⇒ **动作点必须由轨迹几何给**, 不许编也不许只发一次装样子。
- 推导法定式: 拿 `frames[].p` 的 TCP 高度剖面 + 真停顿段
  ```bash
  python - <<'EOF'
  import json, numpy as np
  fr = json.load(open('tools/web/real_traj_joints.json'))['frames']
  z = np.array([f['p'][2] for f in fr]) * 1000                      # mm
  step = np.r_[0, np.linalg.norm(np.diff(np.array([f['p'] for f in fr]), axis=0), axis=1)] * 1000
  print('z min %.1f@%d  max %.1f@%d' % (z.min(), z.argmin(), z.max(), z.argmax()))
  print('停顿段', [(i, s) for i, s in enumerate(step < 2.0) if s])   # 连续几帧才动作
  EOF
  ```
  读法: 第一个最低位 = 落下夹持; 大幅抬升段 = 搬运(手里有件); 抬升后的最后一个最低位 = 放件位, 之后几帧再松。
  写进 `tools/web/real_traj_grip.json` 的 `grip`(`i` 是 0 基绝对帧号, 可负数; 服务每次启动都读, 改完即生效), 并在文件里留 `_derived` 说明推导依据。
- 🔴 **该文件里的 `grip` 可能是占位默认值**(如 `i=1 close` / `i=-2 open`, 语义上就是"开跑就夹、最后才松"), 别拿来当结论:
  按高度剖面重算并把 `_derived` 写清; 同时把 `_default_note` 里"推定默认"那类措辞跟实际值对齐, 否则下一个人会继续用旧值。
- 全程只有 1 处真停顿(`step<2mm` 连续帧)时**别指望用停顿定位**: 那份轨迹中位步长近 30mm, 基本连续运动, 判据只能是 z 剖面的极值(最低点/最高点)。
- 改这个 json 用**定点替换 + 回读**, 别整文件覆盖: 覆盖后必须 `grep -n '"i"' tools/web/real_traj_grip.json` 回读确认新值真落盘(实测出现过"写完了文件还是旧内容")。
- 分段下发不影响: 服务按 `start <= i < start+n` 把绝对帧号映射到本轮, 所以夹持点落在第几段都算得到; 臂到点后原地停 `hold_ms` 等夹爪动作完。
- **真通道自测(Orin, 必做一次再开跑)**: 只 source `/opt/ros/humble/setup.bash` 会报
  `The passed service type is invalid` —— 必须再 source **厂家工作空间** 并显式 domain:
  ```bash
  WS=/home/tashan/zl/tashan_robot_so_*/install/setup.bash
  ssh tashan@192.168.23.66 "source /opt/ros/humble/setup.bash; source $WS; export ROS_DOMAIN_ID=0; \
    ros2 service call /gripper_driver interfaces/srv/GripperSrv \
    '{target_pos: 0.0, target_speed: -1.0, target_force: 30.0, target_acc: -1.0, target_push_length: -1.0, target_push_speed: -1.0}'"
  ssh tashan@192.168.23.66 "source /opt/ros/humble/setup.bash; source $WS; export ROS_DOMAIN_ID=0; \
    ros2 topic echo /gripper_pos std_msgs/msg/Float32 --once"      # 闭=0.0 张=70.0
  ```
  `target_pos` 单位 mm(0=闭合, `ZMAX_GRIP_OPEN_MM` 默认 70)。**开跑前 `/gripper_pos` 读到 1000.0 是上电初值, 不是故障**;
  判成功只认回证到位(`|pos-target| <= max(3mm, 15% 行程)`), 服务返回 200 不算。

## 急停/中断后的复检清单(再按 F5 之前逐条读)
```
pgrep -af 'engineering/start[.]py'                 # 无输出才能启动
pgrep -af 'ss_canvas_loop[.]py'                    # 有 PPID=1 的实例 = GUI 看门狗在替你 tick, 必须清掉再启动
fuser /tmp/zmax_start.lock                         # 空 = 无人持有; 文件里残留的 pid 已死就 :> 清空
curl -s 127.0.0.1:8797/api/robot_state             # estop=False · op=idle · power=on; op=jogging/drag ⇒ 执行腿必拒发
curl -s 127.0.0.1:8797/api/arm/step_traj/status    # running/cursor/done
python -c "..."  对比 tcp_out/latest.json 的 joint 与 frames[0]['j']   # 每轴差 ≤2° 才算"已回初始位置"
```
- 🔴 **引擎可能不在你的入口里跑**: GUI 看门狗会拉起 `tools/ss_canvas_loop.py`(PPID=1), 与 `start.py` **并行** tick 同一张画布 ——
  两套 10Hz 各写各的状态, 页面上数字会跳、断点也不命中。现在两个入口共用 `flock(/tmp/zmax_start.lock)`:
  `start.py` 持锁时被拉起的引擎会打印 `⛔ 已有工程入口在运行(pid=…)` 并退出 3, 这是**正常保护**, 不是崩溃。
  顺序: 他先 F5 拿到锁 → 你再 kill 掉老的独立实例; 反过来 kill 完看门狗立刻重生, 锁还空着就又变成它在跑。
- `op=idle` 是执行腿唯一硬条件; `mode=manual` 不影响下发(建议切自动但不必拦), 报警历史里挂着上次`急停触发` 也不影响。
- 「回初始位置」= 与 `frames[0].j` 逐轴比(不是看 TCP 毫米值), 报每轴差 + 最大值; 演示器手动摇回去也算, 别自己发运动指令去"补"。
- 拒发要看真因: 日志 `state_before{power:on, op:jogging}` ⇒ 是 **op 闸**(他在示教/拖拽), 不是代码坏了; 别改代码。
- 复位三件套: `POST /api/arm/step_traj {"reset":true}` 把游标打回 0; 把 `zmax_data/ss_live/traj_flow.json` 刷成 `phase=IDLE, cursor=0`(否则页面横幅还挂着旧的"第88/215点", 他会以为在跑); 删掉 `/tmp/zmax_stop_at_<tag>` 自停触发器(留着就是每拍停=看起来卡死)。

## 验收清单
```
curl -s -o /dev/null -w '%{http_code}' 127.0.0.1:8797/api/arm/step_traj/status     # 200
curl -s 127.0.0.1:8793/ctl/arm -X POST -d '{"on":false,"note":"自检"}'            # 回 mode/debug 字段 = 新代码在跑
python tools/ctl_auth.py info                                                      # armed/left_s/mode
演练 ZMAX_AUTO_TRAJ=1 ZMAX_TRAJ_DRY=1 → ▶ 第1~10点 → 第11~20点 → … → 215/215 DONE
演练后把 traj_step_state.json 还原成原 cursor（别改现场游标）；全程确认零真机指令
```

- 🔴 **不许在他的终端前台跑 `start.py`**: 入口有单实例 `flock(/tmp/zmax_start.lock)`, 你前台跑一次就把他下一次 F5 挡成
  `⛔ 已有工程入口在运行` + `exit 2`, 他的终端还被你的输出淹没(他会说"你抢夺我的光标")。要验就只在**只读**面验
  (进程表 / `flock` 持有者 / HTTP 状态 / ss_live json), 或由他按 F5 后你再看; 真要占锁跑证明, 先确认他没在跑并当场告知。

## 与单步全链并存
- `ZMAX_STEP_MODE=1` + `ZMAX_SINGLE_THREAD=1` + OMP/MKL/TORCH_NUM_THREADS=1：`engineering/step_mode.py` 把线程改内联、拒绝节点发起的 .py 子进程并点名（`python -c` 库探针要放行，否则 metaworld/aligner 初始化被误杀）、关掉引擎快车道 ⇒ 一拍一趟，每个节点都能停。
- 节点里的死循环 worker（AOI 巡检等）必须先拆 `_xxx_once()` 单轮 + `thread_policy.spawn_or_inline`，否则“内联死循环”会挂住整拍。
