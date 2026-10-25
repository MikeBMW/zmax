---
name: robot-pose-truth-chain
description: "Use when 机器人位姿真值读不到或疑似陈旧(执行器报「位姿缓存未就绪」) — 真值来源分级、链路判别、跨跳板兜底。"
version: 1.0.0
author: hermes-agent
license: proprietary
tags: [robot, telemetry, pose, ros2, ssh-tunnel, diagnosis]
platforms: [linux]
metadata:
  hermes:
    tags: [robot, telemetry, pose, ros2, ssh-tunnel, diagnosis]
    related_skills: [real-arm-motion-control, rokae-direct-control, orin-lan-direct-access]
---

# 机器人位姿真值链路：读不到 / 疑似陈旧时怎么定位与兜底

## When to Use
- 常驻运动执行器对**所有**技能一律回 `拒绝: 位姿读不到(直读失败且常驻缓存过期)` / `受理: 位姿缓存未就绪`
- 页面/文件里的 TCP 位姿与现场明显不符，或 `latest.json` 的文件龄是几小时/几天
- 要做任何按 Δ 计算的动作之前（**先证位姿是新鲜的，再谈动**）

## 真值来源分级（三条会同时死，症状一模一样）
| 级 | 来源 | 依赖 | 失效时表现 |
|---|---|---|---|
| ① | SDK 直采文件 `tcp_out/latest.json` | 本机能到控制器的 xCore 端口 | 文件龄停住；采样容器 `Restarting`，日志 `RuntimeError: network: network connection` |
| ② | 本机 docker tap 容器（`--network host`）订阅 `/robot/tcp_pose` | 本机 DDS 发现 + 到产线网段的路由 | `docker exec` 报容器不在 / `Publisher count: 0` / 全 0 |
| ③ | 状态流 `ssh <机器人主机>` + `ros2 topic echo --once` | 到主机 IP 的 22 端口 | 日志反复 `No route to host`，5s 重连一次 |
| ④ | **兜底：走跳板机的宿主 ROS CLI**（见下） | 只需一条能 ssh 到机器人主机的跳板 | 无（这条就是为了前三条全灭时用） |

## 30 秒判别（全只读，不下发任何指令）
```bash
ip -4 route | grep <产线网段>          # 空 = 本机根本没有该网段路由
ip -br link; ip -4 addr show <enx*>   # 有载波 LOWER_UP 却没地址 = 网线通、网段不对
for h in <主机> <控制器>; do ping -c1 -W2 $h; done   # 本机全灭不说明别人不行
ssh <跳板别名> 'ping -c2 <控制器>'                    # 跳板侧 alive ⇒ 死的是本机这一段
stat -c %y <真值文件>                 # 文件龄 >10s 就当没有位姿（与执行器同口径）
```
判读铁律：**跳板 alive 而本机全灭 ⇒ 问题在本机网口/布线/交换机口，不是控制器、不是执行器代码。**
给网口配上同网段地址后仍 `No route to host`（ARP 无回应）⇒ 那根线**根本不在产线网段**，
别再反复改 IP：现场换口，或直接用下面的兜底通道。

## 🔴 ROS 话题上可能挂着第二个发布者：`echo --once` 会取到错的
同一个 `/robot/tcp_pose` 上可以同时有**真机驱动(≈50Hz) 和一个残留节点**（仿真壳、旧进程、别的机器的桥）。
`ros2 topic echo --once` 取的是“谁先发”，于是同一条命令能给出相差近 200mm 的两套位姿，**而且各自都自洽**
（它读到的关节角与它读到的 TCP 互相对得上）—— 只检查“有没有数据 / 频率多少”永远发现不了。

- `ros2 topic hz` 有稳定 ~50Hz 只说明**至少有一个**活发布者，不说明你读到的是它。
- 真值以**控制器直出**为准：SDK 桥 `/status` 的 `jointPos` + `endInRef`（与页面同一个源）；ROS 话题只作兜底。
  顺序：`SDK 直采文件(新鲜时) → 控制器 SDK 桥 → 跳板 ROS 话题 → 本地文件`。
- 拿到关节后**必须 FK 复算并与 TCP 比对**，差 >15mm 直接拒检 —— 这是唯一能挡住“关节读的是 A、TCP 读的是 B”的门。
- SDK 桥拿不到时，用 `ssh <跳板别名> 'curl -s http://127.0.0.1:<桥端口>/status'` 直取，别依赖本机那条隧道（隧道会半开、返回空串）。

## 兜底通道：跳板机宿主 ROS CLI（不需要本机 DDS / 不需要 docker）
```bash
ssh <跳板别名> 'bash -lc "source /opt/ros/humble/setup.bash; \
  for ws in <工作空间通配>/install/setup.bash; do [ -f \"$ws\" ] && source \"$ws\" && break; done; \
  export ROS_DOMAIN_ID=0; timeout 6 ros2 topic echo --once /robot/tcp_pose --field pose"'
```
- 实测 3~5s 返回 7 个数（pos+quat），与 tap 同口径。
- **宿主 `ros2` 不需要 docker 权限，`docker exec` 需要 sudo** ⇒ 同等效果优先用宿主 CLI，少一层权限少一条依赖。
- 只在 `use_sim_time=false`、`ROS_DOMAIN_ID` 与产线一致时有效；不确定就先 `ros2 topic list` 确认能看到话题。

## 落地到常驻执行器的两个固定改法
1. **主机地址自动选路**：启动时探 `tcp/<robot_host>:22`（2s 超时），通就用直连地址，不通自动退 **ssh 别名**
   （别名里配 ProxyJump 走跳板）。写死在代码里的 IP 一旦网段漂走，整套运动链就全线哑掉，而日志只有一行 `No route to host`。
2. **`_pose_direct()` 增加第四条通道**：SDK 文件 → 跳板宿主 ROS 直读 → 本机 tap。顺序按“依赖越少越靠前”排，
   每条都带自己的超时并 `try/except`，失败只记一行日志、不抛。

## 验收（缺一条就会把“没修”当“修好了”）
- 干跑任意相对技能（`arm=0`），受理行必须是 **`位姿来源 direct`** —— 不是 `cache`、更不是 `位姿缓存未就绪`。
- 改完真值优先级后，**只认 `main()` 的输出**：不少工具在**模块导入时**还会跑一段旧路径的自检并打印位姿，
  `head -7` 抓到的往往就是那段旧值 ⇒ 会误判"改了没用"。要 grep 关键判定行(一致性/PASS/帧龄)或直接调 `read_joints()`。
- 同一时刻**只该有一个真值源在生效**：预检报的 TCP 若和页面 `/api/tcp` 差 >15mm，先怀疑两边读的不是同一个发布者，
  不要拿这个差去质疑机械臂位置。
- 同时报出**目标位姿数值**与**文件龄**，两者都要能对上现场。
- 只有 `cache` 就说明直读仍坏（缓存可能是几小时前的旧值，且守卫会拿它算 Δ）。

## 位姿中继：让 “活着的桥” 嗂回 “死掉的真源文件” (症状链最长的一条)

采样器容器 CrashLoop(本机无产线路由) 时, `tcp_out/latest.json` 会冻住。冻住的代价不只是“读不到”, 而是**三个下游同时静默坏掉**:

| 下游 | 表现 |
|---|---|
| 规划/执行入口 | 拒跑: `规划已 N 分钟, 位姿早变了 ⇒ 请重新规划`(页面点按钮无反应, 不弹原因) |
| 常驻执行器 | 每条命令 `拒绝: 位姿读不到(直读失败且常驻缓存过期)` ⇒ 看上去“点了不动” |
| 轨迹执行器 | 等到位观测全失效(trace/real 空), 最后报 timeout |

修法 = **中继**(不是去修采样器): 把还能读到的真值源(控制器 SDK 桥 `/status` 的 `endInRef`)按 2Hz 搬回那个文件, 字段与采样器**逐字一致**, 只把 `src` 标成中继好追溯。
```
fetch /status → [x,y,z,rx,ry,rz] → rpy→quat(ZYX) → 写 tmp → os.replace() 原子落盘
桥断了就不写    ← 宁可让文件变旧(下游按 stale 自己拒绝), 绝不用旧值刷 ts 冒充新鲜
```
验收: `age < 10s` 且数值与 `/status` 逐位相同(实测 age=0.5s, quat 与中继前完全一致)。

- 🔴 **root 跑的 systemd 里 `os.path.expanduser("~/...")` = `/root/...`**: 中继会“成功写入”到 `/root/zmax/...`,
  日志照打“已中继 N 次”, 而 `/home/<user>/...` 那份一动不动 —— 极容易当“中继没生效”去改代码。
  一律写死绝对路径或从 env 传 (`ZMAX_POSE_OUT`), 不要指望 `~`。
- 🔴 中继不能只在文件不存在时写、也不能带自己的小缓存; 真值的时间戳必须来自**本次**读到的那一帧。
- 判据顺序固定: 先 `stat` 文件龄 + `drift` 与桥比对, 再看下游日志 —— 倒着查会把中继问题当执行器问题。

## 坑
- 🔴 **绝不用文件龄 >10s 的位姿算 Δ**：陈旧值与真值可以差 450mm 量级，按它算出的目标会把臂开错地方。
- 🔴 **页面显示“有位姿”不等于位姿新鲜**：页面读的就是同一个文件，文件冻住时页面照旧画点。
- 🔴 **容器重启循环本身就是证据**：`docker ps` 里 `Restarting (N)` + 日志尾 `network: network connection`
  ⇒ 不要再去查代码/SDK 版本，先按上面的链路判别走。
- 🔴 **`age_s=0.0` 不代表数据新**：若这个龄是按“请求时间”打的，桥吐的是冻结快照也照样显示 0.0s。
  验真是**连采两次看数值变不变** + 看源侧 `conn_ts`，不是看页面那个龄。
- 🔴 **隧道 unit `active` 不代表转发活着**：反向隧道（`ssh -R`）在对端重启后会半开 —— 进程在、
  `systemctl is-active` 还是 active、日志整段静默，但端口不再可用。两头都要治：
  对端装 watchdog（连续 N 次探不到端口才 restart，单次失败会误杀），本机把隧道 unit 的目标写成 **Host 别名**，
  这样直连/跳板切换只改 ssh config 一处。
  自动切换的判据要**三条同时成立**才切：有线网卡 `carrier=1` + 该网卡上有产线网段地址 + `ping <机器人主机>` 真通；
  巡检 30s 一次就够，宁可不切也不要把好链路切坏。
- 🔴 **改 ssh config 里那个 `Host <别名>` 时, 匹配要带换行**(找 `'\nHost <别名>\n'`, 不要用子串 `'Host <别名>'`):
  文件里常有一行注释提到同一个别名, 子串匹配会命中注释 ⇒ 判定"已存在"、实际一个字节都没追加,
  然后你继续重启隧道/查 unit, 却不知道配置文件根本没变。改完 `read_file` 回读那一段再动服务。
- 🔴 **别为了恢复链路去重启产线机器人主机上的生产栈**：跳板宿主只用来“读”，不启停任何服务。
