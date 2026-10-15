---
name: atomic-skill-physics-constraints
description: "Use when 给原子技能加惯性/质量变化率约束或发偏差回流。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [robotics, physics, inertia, jerk, zmax, safety, skill-layer]
    related_skills: [real-arm-motion-control, robot-memory-layers, state-space-canvas-engineering, layered-capability-stack]
---

# 原子技能的物理惯性 / 质量变化率约束 (L2 技能层)

## When to Use
- 用户问"每个原子技能是否知道自己的惯性""进入技能的动作物理上能不能执行""要发偏差 error 反馈"。
- 给 L2 技能派发链加闸 / 复核已有闸（`saturate()` 只是幅值限幅，**不等于物理约束**）。

## 口径: 四条约束, 不是一条

每个技能自带物理量 (真源 `execution.py` 质量/力 + `safety.py` 力上限)，逐技能算上限:

| 约束 | 式子 | 物理含义 |
|---|---|---|
| ① 速度 | `|v| ≤ v_cap(技能)` | 技能工艺上限 |
| ② 加速度 | `|Δv| ≤ a_max·dt`, `a_max = F_max/m` | 牛顿二定律 (力/质量) |
| ③ 加加速度 | `|Δa| ≤ jerk_max·dt` | 平顺性 (从静止一脚踩不能瞬启) |
| ④ 动量/质量率 | `|m·Δv + v·Δm| ≤ F_max·dt` | 抓取/释放时质量在变 |

* `m` 按阶段取: 未夹持 = 夹爪质量; 已夹持 = 夹爪 + 工件; 抓取/释放段 `dm/dt` 非零。
* `F_max` 按阶段取: 通用 = `safety.FORCE_LIMIT`; **插入/放置段取保护值 (如金手指 ≤2N)**, 别拿通用力当插入力。
* `jerk_max` 可由**在轨道实测**定: 从真机/仿真轨迹算 v/a/jerk 的 P99, 再按 `jerk_max ∝ v_cap` 分档 ⇒ 比拍脑袋数字经得起质疑。

## 三条硬经验

1. **闸要放在"派发到技能"那一步**（每个技能一次），不是只放在全局安全边界: 全局限幅不知道
   "本技能能有多快", 所以它不能回答"这个动作物理上能不能执行"。
2. **偏差要分大小两路**: 小偏差就地进状态校正器 (`state_correction(..., err=, w_err=)`, 只动位置维, 别污染夹爪/力维);
   大偏差 (> 阈值, 如 50mm/s) 才是"顶层结构问题"。
3. **改顶层必须加三道保险**, 否则拿噪声改结构比不改更坏:
   ① 先过定位真值**新鲜度**核对 (帧龄阈值; 定位在漂时拒绝) ② 偏差须**持续**(连续 ≥N 拍, 单拍多为换段瞬态)
   ③ 补偿**限幅 + 累计封顶** (如 2mm/次 · 20mm 上限), 到顶就报"交人工/重标定", 不要无限补。
   四态 (拒绝/等持续/补偿/到顶) 都要落 trace, 界面上看得见"改了几次、改了多少"。

## 落地与取证 (Z-MAX)

```bash
./gui-venv311/bin/python tools/audit_skill_inertia.py            # 盘查表 (9 技能 × 四条约束 + 画布口径一致性 + 现场计数)
./gui-venv311/bin/python tools/verify_physics_constraints.py     # 判据 8 组 34 条 (含闸门各自触发/方向不翻转/夹爪维透传/四态)
./gui-venv311/bin/python tools/canvas_wire_skill_physics.py --apply   # 画布: 技能→⚖物理闸→(安全边界/状态校正器/融合定位)
```
* 代码真身 `src/lerobot/policies/left_right/state_space/physics_constraints.py` (`InertiaLimiter.limit/audit`, `PHYS` 表);
  消费侧 `tools/ss_skill_dispatch.py` (每拍过闸, 真源 `zmax_data/ss_live/skill_error.json`) 与
  `tools/ss_engine_loop.py::_top_compensate()` (大偏差→融合定位核对→改 `eng.goal_point`, trace 键 `顶层补偿_*`)。
* 离线验证顶层补偿用 `ZMAX_FUSION_TRUTH=<scratch 定位真值>` 覆盖 (现场恒为 `tcp_out/latest.json`);
  **别为了让它动起来去 touch 陈旧真值** —— 定位帧陈旧时"拒绝改顶层"本身就是正确行为。
* 报口径时要区分: `削因计数` 里哪条约束真被触发过。实测常态是速度/加加速度先绑, 动量/质量率可能长期 0 次
  ⇒ 那时要说"已实装并每拍检查, 但至今不是绑定约束", 不要暗示它拦过东西。
