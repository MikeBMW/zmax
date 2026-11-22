---
name: demo-cycle-replay
description: Use when 要把现场手工走的一圈演示轨迹在真机上逐段复现，或把人工点动学成工序段表。
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [robot, rokae, replay, teach, trajectory, safety]
    related_skills: [real-arm-motion-control, live-state-web-page, rokae-sdk-motion-semantics]
---

# 演示轨逐段回放 + 示教动作学习

## When to Use

- 用户说「按刚才那一圈回放」「再走一次槽2」「继续（下一段）」「我要去槽2，你记录、学习」。
- 要把现场手走的一圈（抓取→扫码→插入→检测→放料）变成可重复的段表并真机复现。

分工：本技能管**段表怎么来、怎么一段一段走**；单条动作的下发闸门/示教点/力矩/碰撞恢复看 `real-arm-motion-control`；
页面跟着跳行看 `live-state-web-page`。

## 流程

1. **取真源**：`zmax_data/rokae_sdk/real_traj_joints_demo.json`(帧位姿) + `phase_states_demo.json`(段表 i0/i1/name)
   + `traj_phase_demo.json`(弧长) + `traj_hopf_demo.json`。段表由 `tools/build_demo_cycle.py` 从原始采集重建
   （等弧长重采样 + 停留检测），改完重启 `zmax-se3-geom.service` 才上页。
2. **命名按他的词**：所有转移段一律 `移动→X`，只有「插入到底→等待位」叫 `后退→等待检测`；
   第一个状态必须是 `初始点`（不是“搬运→槽2”）。他纠正过的名字只读，自动推断不许覆盖。
3. **一段一次**：`ZMAX_SEG_NAME="<段名>" ZMAX_SEG_SPEED=<mm/s> bash tools/rokae_sdk_run.sh --script replay_demo_seg.py`。
   脚本自己会补 `移动→/后退→` 前缀去段表里找，**传段名时不要再带前缀**（会拼成 `移动→移动→X` 找不到）。
4. **夹爪时序要显式**：抓取后夹紧 → 扫码/插入保持 → 钩拉环前**全开 1000** → 放料后张开。
   整圈串联用 `tools/run_demo_cycle.py`（`--list/--dry/--from <段>`），它把夹爪动作写在段前。
5. **学回来**：只读录 `zmax_data/teach/teach_*.jsonl`（10Hz 位姿流），`tools/learn_from_teach.py`
   按「连续 ≥0.35s 且位移 <2.5mm」切停留、用 `config/points/*.json` + 演示相位最近点（≤25mm）命名，
   认不出的写成 `未知N` 并**如实请他命名**，别自己编点名。

## 硬规则

- 🔴 **一条一段、人在旁边**。整圈无人值守连跑是事故配方：带大翻转的转移段没人看就会扫到横梁/工装。
  用户说「你别动」「你看着」= 停手等指令，不是换个方式继续跑。
- 🔴 **bash 串联必须 `set -o pipefail`**：`cmd | tail -N` 之后退出码是 `tail` 的 0，`set -e` 静默失效，
  前段失败后后面各段照跑（实测撞完还在继续走）。逐段显式判 rc，失败即停、不补偿、不重发。
- 🔴 **`rokae_sdk_run.sh` 只透传白名单 env**（`ZMAX_SEG_NAME/SPEED/TRAJ/STATES/MAXDEG/MAXMM`、`ZMAX_BOX_ZMAX`）。
  新加的环境变量不改脚本 `-e` 列表，容器里就读不到 —— 症状是“脚本用的还是默认值”（曾被默认包络 z≤720 拦掉整段）。
- 🔴 **回放前先量该段的位移/姿态步长与 z 范围并报出来**。演示轨迹本身可能超安全包络（人工把臂抬到 z≈1000mm 避工装），
  照搬就是撞：实测 J4 力矩 22.001 > 22.000 Nm + J2 RSC 碰撞停止。超包络就停下问他，**别顺手放开 `ZMAX_BOX_ZMAX`**。
- **逐点插值**：相邻点拆成位移 ≤15~25mm、姿态 ≤4~5°/步。
  **姿态用 rpy 线性插值（带折角回绕 `atan2(sin,cos)`），不要四元数 slerp** —— SDK 的 rpy 轴序与自算四元数
  不一致时，10° 小步会被插成 **178° 翻转**（实测 P01 Δ178.75°）。
- **控制器排队**：`moveStart` 回 `-20 robot state (moving)` = 上一条还没停稳 ⇒ 退避重试 0.5/1/2/4s（至 ~12s）；
  非 `-20` 立即失败停。`-3 EStop` **不重试**，直接停并报“须示教器复位”（软件清不掉）。
- 🔴 **`moveStart` 回执里没有 `ec` 字段 ≠ 成功**：看起来没报错、臂却一步没动，然后空等到超时（实测白等 300s）。
  判成功只能看**动作是否真的发生**：启动后 2s 内关节角变化 >0.05°（或位姿变化 >0.5mm），否则判“未启动”并停，别靠回执。
- **“前段失败”守卫别删**：段首距当前位姿 >15mm 就 `✗ 前段失败, 不动`（曾因段名错配差 501mm），这是最后一道防呆；
  要跨段先人工把臂带到段首附近。
- **“已下发”≠ 生效**：夹爪读数只认真值日志的**新**行，下发同一瞬间读到的是上一条（实测刚夹紧仍读到 1000）。
- **段表单位**：文件名带 `demo` 的表是**毫米**，v2 表是**米**；投影/换算处按量级判，别一律 ×1000。

## 关节空间回放（MoveAbsJ）—— 笛卡尔过不去时换这条

症状：某一段 MoveL 走到一半就停住，控制器 `idle`、无告警、`moveStart` 也不报错。
别怀疑队列：先打当前位姿，若落在**手腕奇异区**（pitch ≈ ±90°，`ZMAX_MOVE_TYPE=J` 也一样停）就是这条。

1. **不要再试 IK 绕**。仓库里的 `zmax_robot_spec.json` 是**仿真模型**：按它建链 FK 与真机差 235~261mm，
   64 种关节符号组合都对不上 ⇒ 解出来的关节角不能发真机。
2. **示教时同时记关节角**：`tools/rokae/log_joints_teach.py` 10Hz 写 `{j, p, rpy}`（只读、不下发）。
3. **从关节日志建轨迹**：`tools/build_absj_from_joints.py` → `real_traj_absj.json`（`frames[].j` + `p` + `rpy`）。
   取圈口径：**以 HOME 常量为锚**找相邻 home 帧，取路径长度 **3~9m** 的那一段 —— 日志末帧常是高位停放（z≈999），
   把它当 home 会把 2~3 圈拼成 5000 帧 / 14813mm 的怪物。
4. **分批下发**：`tools/rokae/replay_absj.py`，`ZMAX_REPLAY_BATCH=40`、批间 `wait_idle`、批末核关节差。
   - 续跑按**关节角**找最近帧，不要按 TCP：示教轨迹自交多，TCP 在交叉处不唯一（会接错圈）。
   - 新旧批用小批量先试（40 帧 / 40mm/s），批末关节差应在 0.1~0.3°；超 1° 就停下来查，不要硬顶。
5. **实测效果（可直接当验收基线）**：278 帧 / 5898mm 单圈，7 批，关节到位误差 0.10~0.24°，
   奇异区与高位翻转（z≈999）全程通过；同一条轨迹用 MoveL 则必停在 pitch −88.5° 那一帧。

代价：关节插值不保证末端走直线，段内路径与他手走的略有差异 —— 视觉/碰撞上要按“大致同路”把关，
报告里把这点写清，不要说成“完全复现”。

## 复现事故现场时

- 碰撞后先停：kill 回放进程 → `bash tools/rokae_sdk_run.sh --script arm_stop.py`（`moveReset` 清队列）→
  只读报位姿 + 控制器告警原文（`dump_controller_log.py`，看 13036/30400 力矩 vs 人为急停）。
- 状态复位后再动：`tools/rokae/check_state.py` 只读查 power/operation/mode + tcp，**不下发任何动作**。
