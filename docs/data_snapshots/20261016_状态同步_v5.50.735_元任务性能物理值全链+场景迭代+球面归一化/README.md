# 数据快照 2026-10-16 · 状态同步 (当前版本 v5.50.735)

老倪原话 (2026-10-16): 「同步飞书端的记忆，技能，以及飞书端完成的场景叠加任务，保存数据，同步信息。发送给 dataworld」

本轮全部数字 = 当场实测 (判据原始输出 / HTTP 回读 / sha256 逐条在本目录)。

| 项 | 结果 (实测) |
|---|---|
| 记忆同步 | MEMORY.md 本地与仓库备份 **sha256 完全相同** `3a1b4b21…0bf5ab` · 逐行比对 **无差异** · USER.md 同样 `946ca343…0c935ec` (一点没丢) |
| 技能同步 | 本地技能 **227** · `docs/skills/hermes-all` 全量镜像 **227** · `docs/skills/xspace` 关键镜像 **31** · **缺失项 0** (本轮新增 `mlops/manifold-sphere-geometry` 已入镜像) |
| 飞书端「场景叠加任务」(公网通道) | 端到端实测通: `/ov/overlay?k=zmax-live` **200 · 47235B** · `/ov/wall.jpg?k=zmax-live` **200 · 9283B** · `/ov/live.json` 无口令 **403** (只读闸门) · POST **403** · 带口令 live.json **1395B**: 3 相机 (arm 臂D405 / local 笔记本 / local2 MAXHUB) + 4 类流 (三相机拼图 **2fps ~56KB/s** / 单路原始 / 单张快照 / **场景契约(叠加框·位姿)**) |
| 场景迭代面板 | 判据 **41/41 PASS** (GUI 真跑: 重跑按钮的界面状态 == 真实退出码 rc=0; 语义指纹跑前跑后 `b708a800c9543f60` 不变, 只动 ts/帧龄) |
| 归一化球面 S^n | 判据 **20/20 PASS** (`sphere.py` 单真源 + 引擎 exp/log/平行移动 + 可微投影层/球面损失/长度正则) |
| 元任务 ↔ 性能配置 ↔ 物理参数 全链 | 判据 **24/24 PASS**: 元任务 **75** · 标准状态 **13 段** · L2 物理参数 **117** (13×9) · 性能指标 **58** 全部有 phase 归属 (P0 反馈速度延迟 11 / P1 对位残差 18 / P2 成功率·节拍 13 / P3 稳定性 4 / P4 可靠性·准确性 12) · 物理参数**无归属 0** |
| L2 原子技能「速度反馈延迟」(Phase 0) | 逐技能全测 (n=219): **P50 9.81 ms ≤ 目标 10 ms ✅ · P95 16.95 ms ✗** · 腿① 引擎→块 P50 **100.14 ms** (n=4808) · 腿③ 派发→反馈 P50 **16.77 ms** (n=35744) · **物理腿不可采** (位姿真值帧龄 53176 s ⇒ 停更, 按规矩标未测不填 0) |
| 原子技能物理约束 | 标定 11/11 · **真调用 12/12** (类体内真调 + 每拍过闸 129796 拍 == 闸计数, 无一拍绕过) |
| 工程库一致性 | check 发现漂移 `['project']` → `engineering_db.py build` 重建 → **✅ 判据全绿** (参数 817 · 链接 1988 · MCD 产品 M9/C88/D57) |
| 状态同步到公网 | `publish_status.py` 推送 **7474B** → 回读 `https://datadrive.world/zmax_status.json` **HTTP 200 · 7474B** · ts 新鲜 · last_training L5 v1014-2302 |
| 版本 / 真源点 | v5.50.735 · 见 `git_ref.txt` |

文件: `memory_skills_sync.txt` (记忆/技能 sha+计数+缺失) · `memory_diff.txt` (逐行比对) ·
`overlay_channel_verify.txt` + `overlay_live_public.json` (公网叠加通道取证) ·
`judge_scene_phase_panel.txt` / `judge_sphere_manifold.txt` / `judge_meta_perf_matrix.txt` / `judge_skill_physics_calls.txt` / `judge_skill_physics_calib.txt` (判据原始输出) ·
`engineering_db_check.txt` + `zmax_engineering.db` (工程库) · `publish_status.txt` + `zmax_status_public.json` (公网状态) ·
报告: `元任务性能物理值全链验证_v5.50.735.md` · `Phase0_L2速度反馈延迟_全测_v5.50.735.md` · `归一化球面实现方案_落地_v5.50.735.md` · `评估分析页_场景迭代面板_v5.50.735.md` · `hermes-jingjing-memory-2026-10-16.md`

未关项 (如实, 未修):
① 物理腿 (位姿/速度真反馈) **不可采** —— 网卡不在位 ⇒ Orin 与位姿真值不可达 (拒发动作、不拿旧位姿冒充);
② 磁盘 `/` used **303G** 超 300G 红线 **3G** —— 三条待批路径 (删 cube_single_expert.h5 94.9G / l5_gen_1010_big.h5 6.7G / 改 lerobot 历史 ~4G);
③ 5 段 (拔出/AOI转移/AOI检测/回程/放下) 引擎有段、物理量有标定, 但技能库/画布无对应条目 ⇒ 物理参数只有 owner 元任务、无 consumer (补齐方案已写在全链报告里)。
