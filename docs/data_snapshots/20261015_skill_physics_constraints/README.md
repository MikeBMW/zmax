# 现场数据快照 · ⚖ 原子技能物理惯性/质量变化率约束 (2026-10-15, for v5.50.735)

老倪原话 (2026-10-15):
> 「每个 L2 层的原子技能, 都有肌肉记忆 … 每个技能都清楚的知道自己动作的惯性, 例如 接近动作的速度与加速度的关系,
> 位置与速度的导数关系等; 所有 L2 层的原子动作, 都要有物理质量变化率的约束, 你来整体盘查所有原子技能, 是否用
> 这样的惯性约束, 确保进入原子技能的 action 能够符合物理定律, 确保最终发出的动作都是物理上可以平顺执行的。
> 如果不能执行, 可以发出偏差 error, 这个 error 可以反馈给状态校正节点, 修正误差; 如果误差太大, 则可以通过
> 融合定位节点, 将大偏差先直接反馈给流形引擎节点, 从而改变顶层结构, 修复补偿偏差。」

## 文件是什么

| 文件 | 内容 |
|---|---|
| `audit_skill_inertia.log` | **盘查表** (9 个技能的 m/F_max/v_cap/a_max/jerk_max/dm·dt⁻¹ + 四条约束 + 物理量唯一依据) + 画布口径一致性 + 现场闸门统计 |
| `verify_physics_constraints.log` | 判据 8 组 34 条 (盘查自洽 / 闸门拦得住 / 现场在跑 / 偏差→校正器 / 大偏差→融合定位→顶层补偿 / 画布连线 / 轨迹键 / 零回归) |
| `skill_error.sample.json` | 现场闸门唯一依据样本 (由 `zmax-ss-skill-dispatch` 每拍写): 每技能 请求/可行/偏差/削因/大偏差 + 累计统计 |
| `chunk_latest.sample.json` | 同一时刻的 🧩 动作块唯一依据 (H=8 · 平滑性 · 技能派发清单), 便于对齐"块 → 闸"的口径 |

## 当天实测数字 (可复核)

* 盘查: **9 个 L2 原子技能全部带 4 条约束** (①速度 ②加速度 ③加加速度 ④动量/质量变化率); 每个技能 `a_max == F_max/m` 自洽。
  物理量唯一依据: `execution.py` 臂段质量 (整机 24.5kg / 末端夹爪 1.2kg / 抓取后 1.35kg) + `safety.py::FORCE_LIMIT=5N`
  + 插入/放入段金手指保护 **≤2N**; `jerk_max = 15 m/s³ × (v_cap/0.35)` (15 系轨道实测 P99 加加速度)。
* 技能派发闸: 过闸累计 **15.3 万次**; 削因计数 `{速度: 87330, 加速度: 4, 加加速度: 222, 动量/质量率: 0}`。
  最近一拍: 转移/接近/对位/抬起 **原样可行** (偏差 0); 插入 请求 0.112 → 可行 0.085 (**偏差 62 mm/s, 大偏差**);
  完成 偏差 **100 mm/s (大偏差)**; 下降 偏差 30 mm/s; 抓取 偏差 80 mm/s (大偏差)。
* 顶层补偿机制自检 (离散验证, 见判据⑤): 定位帧龄 >2s ⇒ **拒绝**改顶层; 定位新鲜但仅 1/2 拍 ⇒ 等持续;
  连续第 3 拍 ⇒ 补偿 **2mm** (方向 = 偏差方向) 且引擎 `goal_point` 真被改; 累计到 **20mm** 封顶 ⇒ 停手待人工/重标定。
* 现场真值帧龄: 融合定位真值 `zmax_data/rokae_sdk/tcp_out/latest.json` 当前 **~10 小时陈旧** (机器人不在位)
  ⇒ 现场口径下顶层补偿**按设计被拒** (`🚫 融合定位帧龄 > 2s ⇒ 不改顶层`) —— 这是正确行为, 不是故障。
* 画布: 90 节点 / 202 连线 (新增 ⚖物理约束闸 节点 + 12 条连线), 渲染判据 ✅ (201/202, 差 1 系既有去重)。

## 根因 / 关联

* **缺口**: 原 `safety.py` 只有 `saturate()` (幅值限幅), `atomic_skills.py` 各技能 `ctrl` 只有 `v_cap`/`v_min`
  ⇒ **没有任何加速度/加加速度/质量变化率约束**, 动作能否被执行完全没查。本轮补齐。
* **为什么用"从静止一脚踩到 5 m/s 只能先到 0.15 m/s"**: 加加速度约束 (15 m/s³ × 0.1s 控制周期) 先绑住 ——
  物理上不可能瞬启, 与实测轨迹 P99 加速度 0.976 m/s² 吻合 (未超任何一条上限)。
* 关联代码: `src/lerobot/policies/left_right/state_space/physics_constraints.py` (新) ·
  `cognition.py::state_correction(err=,w_err=)` · `tools/ss_skill_dispatch.py` (每拍过闸) ·
  `tools/ss_engine_loop.py::_top_compensate()` · `tools/canvas_wire_skill_physics.py` (画布连线) ·
  `tools/audit_skill_inertia.py` · `tools/verify_physics_constraints.py`。

## 副产物: 功能点描述唯一依据 / 配置元数据 错位修正 (同一根因)

* **根因**: `function_notes.json` (功能点描述唯一依据) 与 `config_meta.json` (配置元数据) 都按 `fn_id` = `FN-<系统>-<序号>`
  存放, 而 **fn_id 是行内位置号**。本轮往三行里各插了一个节点 (⚖物理约束闸 → FN-SYS0-60 · 📦metaworld 数据源 →
  FN-PLAT-63 · 🧾元任务预测 → FN-SYS2-24) ⇒ 该行**后面所有节点的号整体前移一位**, 每个描述被挂到了"下一个节点"上
  (实测 16 条搬号 + 2 条空缺; `engineering_db check` 只看得见"空描述"2 条 —— **错挂看不出来**)。
* **修法**: `tools/fix_function_notes_align.py` 按**节点名**重新挂号 (精确名 → 前缀 14 字改名 → 新写/孤儿),
  `tools/config_meta.py build` 从库重建元数据。判据: `tools/verify_function_notes.py` 9 项全过 (75/75 逐条一致,
  描述里的功能名与库一致) + `engineering_db check` ✅ 判据全绿。
* 本目录 `function_notes.json` / `config_meta.json` 就是修后的唯一依据副本 (运行唯一依据在 `data/` 下, 不入库)。

## 发布口径: 三档 550A/550B/550C 随包 (老倪「三产品同步发布」)

* **实捉缺口**: 平台/实例解耦后实例唯一依据 `config/platform/` 不进仓库 (data/ 被 gitignore) ⇒ Windows/macOS/Linux
  安装包里**没有产品档唯一依据** ⇒ 全新安装只能"保障=调试档全开", 三档选不出来。
* **修**: ① 出厂骨架 `defaults/config/platform/zmax_product.json` (三档 dev_profile 全带) 进仓库
  ② 读侧回落 `实例唯一依据 → 仓库 defaults → 冻结包 _MEIPASS/defaults` (`tools/zmax_profile.py::product_json()`
  + `studio.py::_product_json_path()`) ③ 打包 job (Windows/macOS) 带 `--add-data defaults` 并断言三档在。
* **判据**: `tools/verify_product_release_factory.py` 20 条全过 —— 含**真回落**验证 (隔离目录只放 defaults、
  故意不建 config/, 起子进程读三档: 550A=on/core/dds · 550B=debug/all/dds · 550C=off/none/shm)。
