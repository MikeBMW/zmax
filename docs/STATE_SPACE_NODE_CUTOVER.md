# 状态空间节点逐一切换 · 工作台账 (目标 300UPH · AR3D 练习场)

> 老倪 2026-10-28 指令: 「一个节点一个节点的替换，从 L2 的 plan 节点开始」「ar3d 就是练习场，目标 300UPH」
> 「感知模型要真正读视频」「所有层所有节点要真正状态空间代码执行」「不发真机指令」
> 交付: 5.50.759 → Windows/Mac 发布 → 飞书通知 → 配置中心文档/工单

## 0. 场地与边界

| 项 | 值 |
|---|---|
| 练习场 | `http://10.163.146.78:8797/ar3d`（源 `tools/web/tcp-ar.html`） |
| 真机边界 | **零指令**：本台账所有动作只写 AR 渲染指令 `zmax_data/ss_live/ar_cmd.json` |
| 引擎 | `zmax-ss-canvas-loop.service`（10Hz，`ZMAX_CANVAS_ONLY=ssplan`） |
| 画布 | `data/database/zmax/sources/canvas/state_space_obs.json`（94 节点） |
| 节拍目标 | 300 UPH = 12 s/件（稳态循环块实测 314 UPH） |

## 1. metaworld 是怎么渲染的（回答老倪）

metaworld 是 **MuJoCo** 环境（v2/v3 任务集），本机渲染路径：
`env.render()` → mujoco 离屏渲染器（`MUJOCO_GL=osmesa` 无 X11，`egl` 有 GPU 时）→ RGB ndarray。
L2 `ss_yolo` 节点就是这么拿帧的（`_yolo_capture`），再用 YOLO 推理；
真机/视频源换成 `cv2` 解码帧，**同一套节点代码、同一套契约**（`ZMAX_L2_SRC=sim|real`）。

## 2. 节点切换状态

| 节点 | 层 | 切换前 | 现在 | 证据 |
|---|---|---|---|---|
| `ssplan` 🧩 Plan | L2 | 只播放 `tools/sim_insert_plan.py` 预烤的 392 段 | **节点自算**（`cycle_plan.build()`），磁盘表降级为对拍基准 | 自算 392 段 vs 磁盘表：**逐段坐标差 0.000mm、kind/t 差异 0 处**；`plan_src=self` |
| `ss_yolo` 🎯 感知 | L2 | 只在仿真链跑，3D 不出 | 源可切 `sim|real|video`；真机权重 `yolo_peg_live.pt`；产出契约 `vision_points.json` | sim: 3 目标 conf .97/.98/.97；video(`reports/mlp_insert_success.mp4`): 扫到第 16~17 帧检出 `peg` conf 0.42，box 与 conf 写进契约 |
| `n_moveit` 🧭 运动规划 | L2 | `MoveItPlan.plan([0,0,0],[0,0,0])` 探针 | 真规划（起点真值 → 分段 抬升/横移/下落，单步≤50mm 向下≤20mm） | 真起点 663,-29,292mm → 7 段 219.4mm；`tcp_stale` 拒出段表 |
| `ssvlm` 🧠 VLM | L3 | SmolVLM2 `encode_stage()` 需真机阶段帧 | **未接 AR 场景**（缺 `ctx.module._ss_tr` 帧源） | — |
| L4 意图→action | L4 | — | 未接 | — |
| 跨层记忆共享 | 全层 | — | 未接 | — |

## 3. Plan 节点切换细则（本轮已落地）

- 新文件 `src/lerobot/engineering/nodes/cycle_plan.py`（379 行）：段表生成 **本体**，从 `tools/sim_insert_plan.py` 迁入；
  点位仍只认 `config/points/cell_points.json`（`cfg_sha` 指纹随表落盘）。
- `tools/sim_insert_plan.py` 降为薄壳 CLI（`CP.build()` + `CP.write()`），不再自己算。
- `plan_long_impl._self_plan()`：节点每次加载段表都先自算；与磁盘表 **同配置指纹** 时逐段对拍
  （段数/kind/t/端点 ≤0.01mm），不一致或自算异常 ⇒ **回退磁盘表**并如实报差异（`plan_src=disk(...)`）。
- 改配置后无需重出段表：`cfg_sha` 不同 ⇒ 直接以自算为准（`plan_src=self(配置已变)`）。

### 实测数据
- 段数 392 · 全程 159.43s · 台均 11.39 s/件 · **316 UPH**；稳态循环块（轮 2·3）45.87s/4 件 ⇒ **314 UPH**
- 现场运行 `ar_cmd.json`：30s 内 `mt_i` 3→13（10 步）⇒ 56 步/14 模块 ≈ 168s ⇒ **≈300 UPH**，帧龄 0.01s
- 回退闸实测：自算/磁盘同指纹且一致 → `self`；异常分支 → `disk(...)` + 差异文字

## 4. L2 感知（YOLO）切换细则

- 写者 = 节点 `library.node_ss_yolo`（不是 tools 脚本）；写盘口径 `engineering/nodes/vision_points.py`。
- 契约 `zmax_data/ss_live/vision_points.json`：
  `{t, ts_str, frame, units:"mm", verified, source:{kind,cam,K_src,ext_src,depth_src,gaps,video,frame_i,scan_frames}, points:{...}, det2d:{类:{box,conf}}}`
- `verified = (frame=="base_link") and not gaps` ⇒ 仿真帧永远 `false`，plan 侧 `obs_unverified` 拒收。
- 视频源 `ZMAX_L2_VIDEO=/path.mp4`：节点每次被调度 = 读下一帧（扫帧上限 `ZMAX_L2_VIDEO_SCAN=24`），
  播完自动回卷；帧号/帧率/扫描帧数全部入契约留证。

### 当前硬缺口（不是代码问题）
| 缺口 | 实测 |
|---|---|
| 手眼外参 | `config/calib/zmax_calib.json` → `T_base_cam.value = null` |
| 台面高度 | `plane_z.value = null` |
| 真机相机帧 | `zmax_data/ss_live/cam_rs.png` 已 34h 未更新 |
| TCP 真值 | Orin `192.168.23.66` 不通 ⇒ `tcp_out/latest.json` 陈旧 |

⇒ 3D 观测点出不来（`gaps` 三条如实入文件），plan 只能吃配置槽位（当前 AR 动画就是这条路，300UPH 达标）。
标定一到位，`ZMAX_L2_SRC=real` 即出真 3D 点，plan 侧一行不改。

## 5. 下一步（按序，每步都有判据）

1. **L3 VLM 接 AR 场景**：给 `ssvlm` 一个 AR 帧源（8797 快照或视频帧），跑 SmolVLM2 真前向 → 场景理解 JSON 入 `ss_live/vlm_scene.json`；判据 = 真实前向耗时 + 输出结构化 + plan/AR 侧可读。
2. **L4 意图→action**：AR 元任务（`ar_meta_tasks.json`）意图文本 → 策略/规划 → action 段（不改段表几何，只换"谁来定下一段"）；判据 = 与 plan 自算段表一致率 + 300UPH 不掉。
3. **跨层记忆共享**：L2 肌肉记忆/L3 长程/L4 世界模型/L5 语义写入统一 `ss_live/memory.json`，各层读写同一份；判据 = 同一意图第二次执行节拍改善且有据可查。
4. **双臂**：左臂由 `left_arm_speed()` 等效速度驱动 → 真按时间轴出段并叠加到 ar_cmd（当前左臂是渲染侧补的）。
5. **微调训练**：550B 调通 → 550A/4060 微调（真机域权重 `yolo_peg_live.pt` 扩展类别/精度）→ 550C 部署。
6. **发布**：版本 5.50.759 · Windows/Mac 打包 · 飞书通知 · 配置中心文档 + 工单。

## 6. 变更文件清单（本轮）

```
新增 src/lerobot/engineering/nodes/cycle_plan.py          段表生成本体 (L2 Plan 节点)
新增 src/lerobot/engineering/nodes/vision_points.py       视觉观测点契约读写 + 射线求交
改   src/lerobot/engineering/nodes/plan_long_impl.py      _self_plan() 自算+对拍+回退
改   src/lerobot/engineering/nodes/plan_impl.py           obs 输入 + verified/conf/时效 四道闸
改   src/lerobot/engineering/nodes/library.py             node_ss_yolo 发布契约; real/video 源; _det2d_and_3d
改   src/lerobot/engineering/nodes/points_source.py       vision_points 真源 + vision_doc()
重写 tools/sim_insert_plan.py                             薄壳 CLI (旧实现备份 scratch/sim_insert_plan.py.pre_node_migrate)
```

## 7. 本轮收尾 (2026-10-28 夜)

- 代码：commit `50f03a6c` 已推 `origin/main`（HEAD == origin/main）
- 飞书：成果已发 dataworld/静界 报告群（message_id `om_x100b6113e3d888a0c0f1ad1950258b8`，http 200）
- 现场缺口未变（手眼/plane_z/相机帧/Orin），**3D 观测点仍出不来**，plan 走配置槽位路径（300UPH 达标）
- 关机前状态：`zmax-ss-canvas-loop` 正常（10Hz，only ssplan，`plan_src=self`）；零真机指令
- 下次开机第一件事：`sudo systemctl status zmax-ss-canvas-loop` → 跑 `tools/sim_insert_plan.py` 确认段表与配置指纹一致 → 继续 L3 VLM 接帧源
