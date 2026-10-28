# 原子技能 topic 清单 (所有场景)

老倪 2026-10-15: 「所有的原子技能, 例如 接近, 对位, 都要有 topic 输出, 且在实时监控信号分析窗口都有对应的信号;
你来给出所有场景的原子技能 topic, 我要在信号分析窗口看到实际的物理模型, x y z v a 等距离、速度、角度等物理值;
要实际发出来; 所有原子技能, 而且 vscode 要有对应代码。」

**本文件是生成物**: `./gui-venv311/bin/python tools/topics_list_skill.py --md` 从唯一依据
`src/lerobot/dataspace/topics.py`(话题) + `.../skills/atomic_skills.py`(技能号↔阶段) 渲染 —— 别手改, 改了会被覆盖。

## 一、已上线: 真发布 + 有实测值 + 信号分析可见 (8 个原子技能)

| topic | 技能 | 阶段 | 场景 | 类型 | 频率 | 遥测档 |
|---|---|---|---|---|---|---|
| `zmax/skill_sk01` | SK01 | 接近 | 插拔场景(绿) | `zmax::SSSkillPhys` | 10 Hz | diag/calib/test |
| `zmax/skill_sk02` | SK02 | 对位 | 插拔场景(绿) | `zmax::SSSkillPhys` | 10 Hz | diag/calib/test |
| `zmax/skill_sk03` | SK03 | 下降 | 插拔场景(绿) | `zmax::SSSkillPhys` | 10 Hz | diag/calib/test |
| `zmax/skill_sk04` | SK04 | 抓取 | 插拔场景(绿) | `zmax::SSSkillPhys` | 10 Hz | diag/calib/test |
| `zmax/skill_sk05` | SK05 | 抬起 | 插拔场景(绿) | `zmax::SSSkillPhys` | 10 Hz | diag/calib/test |
| `zmax/skill_sk06` | SK06 | 转移 | 插拔场景(绿) | `zmax::SSSkillPhys` | 10 Hz | diag/calib/test |
| `zmax/skill_sk07` | SK07 | 插入 (摆盘链同号 = 放入) | 插拔场景(绿) / 摆盘场景(蓝) 同号两支 (插入 ↔ 放入) | `zmax::SSSkillPhys` | 10 Hz | diag/calib/test |
| `zmax/skill_sk08` | SK08 | 完成 | 插拔场景(绿) / 摆盘场景(蓝) | `zmax::SSSkillPhys` | 10 Hz | diag/calib/test |

## 二、每个 topic 携带的信号 (信号分析窗口里一行一条; 每技能 18 条)

| 分类 | 信号 | 单位 | 说明 |
|---|---|---|---|
| 实测 | x / y / z | mm | 末端位置 (真机 tap; 位姿停更 ⇒ -1) |
| 实测 | v | mm/s | 速度 = ‖实际下发动作‖ |
| 实测 | a | mm/s² | 加速度 = 块间速度变化率 (保留到下一块, 不做 16ms 尖峰) |
| 实测 | s | mm | 本段累计行程 (物理闸 InertiaLimiter.travel) |
| 实测 | angle | deg | 末端姿态角 (真机 tap 四元数 2·acos|w|) |
| 实测 | err | mm/s | 被物理闸削出来的偏差 ‖u_req − u‖ |
| 包络 | v_cap | m/s | 限速 (标定唯一依据) |
| 包络 | a_max | m/s² | 加速度上限 = F/m |
| 包络 | jerk_max | m/s³ | 加加速度上限 |
| 包络 | s_step | m | 单拍位移上限 |
| 包络 | s_max | m | 段行程上限 |
| 包络 | m_kg | kg | 运动质量 |
| 包络 | f_max | N | 力上限 |
| 元 | in_service / step / frame_age_s / why | — | 在职 / 块内拍号 / 源帧龄 / 本拍被哪条约束削 |

> 信号分析窗口里的行名 = `<topic>.<SK号> <阶段> · <信号> <单位>`, 例如
> `skillphys.SK07 插入 · v 速度 mm/s`; 实测曲线与 v_cap/a_max 包络线**同图叠**即"看到物理模型"。

## 三、场景 ↔ 技能号

| 场景 | 颜色 | 技能号 | 阶段 | topic |
|---|---|---|---|---|
| 插拔场景 TASK-01-FW | 绿 `#2e8b57` | SK01..SK08 | 接近/对位/下降/抓取/抬起/转移/插入/完成 | `zmax/skill_sk01` … `sk08` |
| 摆盘场景 TASK-06-TRAY | 蓝 `#1f6feb` | SK01..SK08 | 接近/对位/下降/抓取/抬起/转移/**放入**/完成 | 同上 (同号两支: SK07=放入) |
| AR场景 TASK-07-AOI | 紫 `#8957e5` | — 无技能类 | AOI转移/AOI检测/回程 | 待建 (见第四节) |

## 四、已登记但**没有生产者**的 5 段 (诚实标注, 不假装有数)

引擎 13 段 (cognition.STAGES) 里这 5 段在技能库里**没有类** ⇒ 目前没有实测产出;
v/a/s 包络在标定唯一依据里是齐的, 补生产者的做法 = 与 SK01..08 同一条链接进派发服务。

| topic | 段 | 场景 | 状态 |
|---|---|---|---|
| `zmax/stage_pullout` | 拔出 | 插拔场景(绿) | 已登记 · 待接生产者 (技能库 atomic_skills.py 无对应类 ⇒ 目前没有实测产出; v/a/s 包络在标定唯一依据里是齐的) |
| `zmax/stage_aoi_move` | AOI转移 | AR场景(紫) | 已登记 · 待接生产者 (技能库 atomic_skills.py 无对应类 ⇒ 目前没有实测产出; v/a/s 包络在标定唯一依据里是齐的) |
| `zmax/stage_aoi_inspect` | AOI检测 | AR场景(紫) | 已登记 · 待接生产者 (技能库 atomic_skills.py 无对应类 ⇒ 目前没有实测产出; v/a/s 包络在标定唯一依据里是齐的) |
| `zmax/stage_return` | 回程 | AR场景(紫) | 已登记 · 待接生产者 (技能库 atomic_skills.py 无对应类 ⇒ 目前没有实测产出; v/a/s 包络在标定唯一依据里是齐的) |
| `zmax/stage_place` | 放下 | 摆盘场景(蓝) | 已登记 · 待接生产者 (技能库 atomic_skills.py 无对应类 ⇒ 目前没有实测产出; v/a/s 包络在标定唯一依据里是齐的) |

## 五、代码位置 (VSCode 直接打开; 绝对路径见下)

| 作用 | 仓库相对路径 |
|---|---|
| 话题登记 (唯一依据) | `src/lerobot/dataspace/topics.py` |
| DDS 消息类型 | `dds/ss_types.py → class SSSkillPhys` |
| 类型/QoS 注册 | `dds/zmax_node.py → _SS_TOPICS / QOS_CLASS` |
| 实测值生产 (每拍过物理闸) | `tools/ss_skill_dispatch.py → cycle() → zmax_data/ss_live/skill_phys.json` |
| 真发布 (DDS) | `tools/dds/ss_daemon.py → pub_skills()` |
| 信号分析窗口取信号 | `tools/gui/canoe_graphic.py → HOST_SOURCES + HostJsonSource.run` |
| 场景色标 | `tools/sig_scene_tags.py → tag()` |
| 物理包络唯一依据 (改数用 CLI) | `config/calib/zmax_skill_physics.json ← tools/skill_physics_calib.py` |
| 判据 (26 条全链) | `tools/verify_skill_topics.py` |

仓库根 = `/home/ubuntu/zmax` (e.g. `/home/ubuntu/zmax/tools/dds/ss_daemon.py`)。

