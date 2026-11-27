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
- 同时报出**目标位姿数值**与**文件龄**，两者都要能对上现场。
- 只有 `cache` 就说明直读仍坏（缓存可能是几小时前的旧值，且守卫会拿它算 Δ）。

## 坑
- 🔴 **绝不用文件龄 >10s 的位姿算 Δ**：陈旧值与真值可以差 450mm 量级，按它算出的目标会把臂开错地方。
- 🔴 **页面显示“有位姿”不等于位姿新鲜**：页面读的就是同一个文件，文件冻住时页面照旧画点。
- 🔴 **容器重启循环本身就是证据**：`docker ps` 里 `Restarting (N)` + 日志尾 `network: network connection`
  ⇒ 不要再去查代码/SDK 版本，先按上面的链路判别走。
- 🔴 **别为了恢复链路去重启产线机器人主机上的生产栈**：跳板宿主只用来“读”，不启停任何服务。
