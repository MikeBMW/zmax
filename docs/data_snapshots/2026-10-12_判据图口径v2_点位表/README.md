# 2026-10-12 判据图口径 v2 + 配置中心点位表(空间点1~8)

本次改动涉及的真源(config/ 是 data/database/zmax/sources/config 的软链, 不在 git 里 ⇒ 快照到这里):

- ss_task_binding.json — TASK-07-AOI 目标里的判据图口径改成 914x348 等比(真实金手指 ROI x226~1143 · y299~638)
- tasks.json — 由 tools/task_build.py 重新生成: overrides 新增 pt.空间点1~8 / pt.space_dir(真源 data/skills/l2_atomic/space_points.json)

代码侧(在 git 里): tools/task_build.py(teach_point_overrides 加空间点只读摊平) · tools/gui/veh6_config_page.py(_pt_rank 排序 + 卡片副标题标两个真源) · flows/scenes_5jobs.json(判据图目标文案)

校验: tools/engineering_db.py check 全绿 · tools/audit_console_consistency.py 文案与真值不符 0 处
