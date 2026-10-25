---
name: trajectory-loop-execution
description: "Use when 要让一条多段轨迹「点一次全走完」(规划→一次性下发→真值取证), 或出现只走一段/段间被拦。"
version: 1.0.0
author: hermes-agent
license: proprietary
tags: [robot, trajectory, fifo, safety-gate, forensics]
platforms: [linux]
metadata:
  hermes:
    tags: [robot, trajectory, fifo, safety-gate, forensics]
    related_skills: [real-arm-motion-control, robot-pose-truth-chain, dispatch-chain-integrity]
---

# 多段轨迹闭环：规划 → 一次性下发 → 真值取证

## When to Use
- 用户要「1 2 3 4 步一次性发过去、点执行就全执行、中间不能停顿」或提到「执行轨迹 / 旁路控制」
- 轨迹点下去**只走了一段**、段间卡住，或报 `起点已变 Nmm > 5mm`
- 要回答“这条轨迹是不是运动规划器给的”，或重规划后形状变了要解释
- 改 `traj_plan.py` / `traj_exec.py` / `/api/traj/*` 任一环

现场要求形如「1 2 3 4 步一次性发到运动节点，点执行就全执行，中间不停顿」。
这里只讲这条链的执行语义和取证；单步/多阶段技能的守卫与授权见 `real-arm-motion-control`，
位姿真值来源分级见 `robot-pose-truth-chain`。

## 数据流（唯一执行收口不变，不新开写入口）

```
traj_plan.py → zmax_data/runtime/traj/plan.json   （tcp0_mm 起点 + 段表 + 预检结果）
traj_exec.py → 一次性写 N 行 JSON 进 l2_daemon FIFO（不逐段等位）
l2_daemon    → 唯一执行收口（授权 / 守卫 / 安全闸都在它这一层）
```

FIFO 一行一条：`{"skill":"L2.lift","d_mm":60,"auth_epoch":N,"src":"traj_exec","note":"..."}`。

## 下发：全部段一次写完，然后只观察

```python
with open(FIFO, "w", encoding="utf-8") as f:
    for s in segs:
        f.write(json.dumps({"skill": s["skill"], "d_mm": float(s["d_mm"]),
                            "auth_epoch": epoch, "src": "traj_exec"}, ensure_ascii=False) + "\n")
        f.flush()
        time.sleep(0.12)      # 只为给 FIFO 读端呼吸，不是等位
```

写完后**不再由脚本决定节奏**：只轮询真值记每段残差，用于汇报/取证。
「发第 1 段 → 等到位 → 再发第 2 段」在慢速真机上等于每段之间停十几秒，不是用户要的。

## 到位判据：只认控制器真值，**绝不等执行器的 phase**

执行器可能把动作真做完（日志已有 `ROS: response: TargetPose_Response(...)`、臂已到位），
而 `exec_state.json` 的 `phase` 一直停在 `accepted` 永不写 `done` —— 它靠**日志文本匹配**推进状态机，
某类技能的收尾行不匹配任何规则。上层若等 `phase==done` 就永远等不到，卡死在段间。

```python
_q, _tcp, _age = read_joints()          # 控制器直出，见 robot-pose-truth-chain
if dist(_tcp, to_mm) <= ARRIVE_TOL_MM and _age <= 5.0:   # ARRIVE_TOL_MM = 8.0
    ...
```

`phase` 只用来读 `blocked`（被闸拦 ⇒ 立即中止余下所有段），**不用来判到位**。

## 执行前的四道闸（都 fail-closed，缺一条别发）

1. **规划新鲜度**：`age > PLAN_MAX_AGE(30min)` 拒发 —— 位姿早就变了，轨迹含义已变。
2. **预检**：`plan.precheck.ok` 必须 True 并报最差净空；**拿不到实时真值就拒检**，绝不用旧位姿算净空。
3. **起点闸**：`|当前TCP − plan.tcp0_mm| > 5mm` ⇒ 拒发「这条相对段轨迹含义已变」。
   🔴 **只在第一段之前校验一次**。段间再拿「规划起点」比对，等于把自己走完第一段的正常位移
   判成「人手挪过臂」⇒ 第 2 段必被拦（日志 `起点已变 Nmm > 5mm`，现场看到的就是“只走了第一段”）。
   段间要校验就校验「当前 ≈ 上一段目标」的容差。
4. **执行锁**：`fcntl.flock(LOCK_EX|LOCK_NB)`，第二个实例直接拒。
   两个执行器并发会把两条轨迹交替写进同一条 FIFO，在途指令互相覆盖目标位姿。

## 连续性有物理上限（汇报时先说清，别承诺做不到的）

`/move_pose`(`TargetPose`) 请求字段只有 `speed` + `joint_state`，**没有 blend / zone / 队列标志**。
每条命令被控制器当成独立点到点运动，走到位停住再接下一段 ⇒ 软件层零等待，**拐点仍有一次减速停顿**（约 0.3~1s）。
要机器人层面真连续（画方框不掉速）必须换控制器连续轨迹接口：xCoreSDK moveLine 队列，或 ROS
`FollowJointTrajectory` 一次下发整条关节轨迹。先探接口支持哪种再谈“不停顿”。

## 诊断「怎么只执行了一段」（按这个顺序，别猜）

1. `zmax_data/runtime/traj/exec_stdout.log` 尾：有 `已下发 L2.xxx` = 真发出去了；
   有 `🛑 起点已变` = 段间被起点闸拦。
2. `exec_state.json` 的 `phase`/`skill`/`t`：停在 `accepted` 不推进 = 状态机不写 done。
3. 执行进程是否还在：`/proc/<pid>/wchan` = `hrtimer_nanosleep` + `State: S` = 在 sleep 轮询一个永不来的条件。
4. 真值是否已到第一段目标：到了就证明**动作成功、问题在判定不在下发**。

## 坑

- 🔴 **别用 `pkill -f traj_exec.py` 收尾**：自己的命令行含同一串 ⇒ SIGKILL 掉整个 shell，后续步骤全不执行。
  按 `/proc/<pid>/cmdline` 精确匹配，或把模式串写进脚本文件再执行。
- 🔴 **页面/API 里的执行状态是上一次失败留下的**：`traj_state.json` 可能是几小时前某个 `blocked`，
  用户看到的是那行旧文案。报原因前先看它的 mtime，别把旧 `blocked_by` 当本次病因。
- 🔴 **规划脚本每次按当前 TCP 重算** ⇒ 臂移动过后形状/位置必然变。用户问「怎么跟之前不一样了」时，
  先答“起点变了多少、是不是上一份是续走版”，再谈重规划；别拿新图去解释旧图。
- 轨迹是**直线段拼接 + 净空采样**，不是运动规划器输出。被问「是不是规划出来的」要直说不是；
  真规划要起 MoveIt 容器后把两条线同画对比。
