# 📈 实时监控页 — 信号源口径与 Orin 实时链

## 删成组功能的取证姿势 (2026-10-11 教训)

* **不要**用「def A 到 def B 整段删」: 同一区间里常夹着别的顶层 `def`。实测
  `_start_dummy_monitor` 到 `_gen_pusht_rrd` 之间还夹着 7 个方法, 一次误删连带吞掉
  `_refresh_topic_node_list`/`_fetch_topic_node_list`/`_show_topic_node_lists`/`_update_live_display` 等合法方法。
  正确顺序: 先列出区间内**所有 4 空格缩进的 `def `** → 逐个判定该删该留 → 再自下而上删。
* 删完必须**真构造页体验证**, 不能只看 diff: `QT_QPA_PLATFORM=offscreen` 起 QApplication, 真 `MonitorModule()`,
  真切信号源、真点「▶ 启动」。本次正是这步抓出: ① `_refresh_topic_node_list` 被吞 ⇒ 构造即 AttributeError
  (整页起不来); ② `_mlog` 函数体被截断(`mon_log.append` 掉进 `_show_inline_data`) ⇒ 全页日志静默 +
  点「启动」时 `ts/msg` NameError。
* 判"有没有关联"落到运行期证据: 页面上每个值都要追得到真话题/真进程。硬编码的假关节力数(J1~J6/Fx~Fz)、
  无发布者的话题、只打一行日志的按钮都算无关联 —— 要么接真源, 要么如实报缺。

## 保留口径 (2026-10-11 老倪: 没有关联的功能都删掉)

* 信号源只留 2 路: **回放数据**(真 ReplayEngine 会话) / **实时数据**(Orin 真 ROS2 信号)。
* 删掉的 4 路与其专属方法: 仿真数据(`_mon_use_sim`+`_gen_sim_rrd`) / 演示动画(`_gen_rrd_demo`+`_stream_demo`) /
  离线仿真(`_start_dummy_monitor`) / PushT数据(`_gen_pusht_rrd`), 以及 Rerun worker 里的 `_stream_sim`/`_stream_demo` 两分支。
* 这批方法只服务假数据, 与其它功能无交叉引用 ⇒ 删净后 `studio.py` 里这几个符号应 0 命中。
* 卡面文案原为「训练曲线 · GPU状态 / 推理延迟 · 力控曲线」(从没实现) → 改为「远程同源实采 · Orin 状态 / 回放会话 · Rerun/RViz」。

## Orin 实时链的可用 ssh 环境 (照抄在役位姿采样 pid 8790)

```
ssh -o ConnectTimeout=3 tashan@192.168.23.66 \
  'source /opt/ros/humble/setup.bash &&
   for w in /home/tashan/0810/*/install/setup.bash; do [ -f "$w" ] && source "$w" && break; done;
   export ROS_DOMAIN_ID=0 FASTDDS_BUILTIN_TRANSPORTS=UDPv4 ROS_LOCALHOST_ONLY=0;
   echo "##gripper_pos"; timeout 3 ros2 topic echo --once /gripper_pos std_msgs/msg/Float32 2>/dev/null'
```

* **缺 `FASTDDS_BUILTIN_TRANSPORTS=UDPv4` 就发现不到发布者**: 实测 `ros2 topic info /robot/tcp_pose` 会把
  Publisher count 报成 0(Subscriber 却有 53), `ros2 topic list` 只剩 2 条 —— 看着像"话题没数据", 其实是传输层没配。
* **域号必须是 0**: `ROS_DOMAIN_ID=23` → 2 topics / 0 nodes; `=0` → 15 topics / 8 nodes(实测)。
* **`/gripper_pos` 有两种类型** ⇒ 必须显式给 `std_msgs/msg/Float32`, 否则报
  `Cannot echo topic '/gripper_pos', as it contains more than one type`。
* **每路单独 `timeout N`**: 无发布者的话题会一直阻塞, 不给 timeout 会把整轮 ssh 拖死(subprocess 误报断开)。
* **分段用 `echo '##<名字>'` 标签, 不要按位置切**: 少一个分隔符整列标签就错位一行(实测 emergency_stop 的
  WARNING 挂到了 tower_light 名下)。解析时再滤掉 `---` 与 `WARNING` 行。
* 哪些话题真有数据随机器状态变: 实测 `/gripper_pos` 有发布者(值 `data: 174.0`), 而 `/robot/joint_states`、
  `/robot/status`、`/robot/force_torque` 当时 Publisher count = 0 ⇒ 面板里不出现是**诚实**的, 不是 bug。

## 离线取证模板

```
QT_QPA_PLATFORM=offscreen 起 QApplication;
studio.MonitorModule() 真构造;
m.src_live.setChecked(True)  → 循环 processEvents 40s 等一轮;
断言 topic_list_view 有 'Topics (15)'/'Nodes (8)', mon_data_preview 出现 'gripper_pos' 且有值,
     'WARNING' 不出现在面板;
m.grab().save('/tmp/mon_after.png') 留图。
```

## 同源遗留问题 (未动)

* `HardwareModule`(硬件工具箱页) 还有 5 处 `ROS_DOMAIN_ID=23`(gripper 服务、tactile、joint_states echo、robot_stop),
  域号同样错 ⇒ 那些按钮当前不真起作用。属另一个页面 + 真机动作路径, 改前单独确认。
