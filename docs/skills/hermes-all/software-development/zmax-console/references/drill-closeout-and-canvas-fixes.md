# 全链路演练收口 · 判据 · 唯一依据修正 (2026-10-14 实测)

## 1. 演练编排器三模式 (`tools/run_full_drill.py`)
```
--tasks all --steps 60 --no-train --no-feishu   # 全跑 (7 任务 ≈ 35 分钟, 约 5.5 分钟/任务)
--docs-only                                     # 只重出文档 (改模板/描述后不重跑)
--train-only --train-steps 20 --only-model-layer L4   # 只补训练 (7×21s) 并并进文档
```
- 单任务真走 9 步: 配置链7域快照 → 场景切换 → 原型单步 → 整体闭环 → 波形 PNG → 模型证据 → 有界训练 → 文档 md/docx/pdf → `engineering_db build` 后插 `drill_runs` + 跑一致性。
- **单节点必须带墙钟超时** (`NODE_TIMEOUT_S=45` + SIGALRM): 相机/服务类节点会把整个演练挂死。
- **离屏跑必须先建 QApplication** (`QT_QPA_PLATFORM=offscreen`), 否则 core dump; 但 `📦 metaworld 数据源` 节点**仍需要 GUI 上下文** —— 7 个任务各挂这 1 个 (`TypeError: NoneType not callable`), 属已知: 不是编排器问题, 是该节点依赖主窗口。
- `ss_bus_topics.publish` 返回键是 `topics[0]`(不是 `topic`), trace 载荷在 `value`, `PIPELINE_STATE.stages` 是 dict。

## 2. 训练证据的取数坑 (实证)
- `joint_train_all.py` 的 L4 段 loss 是**两行表**: 键一行 + 数值下一行 (`fit/loss:` 换行 `-3.866`), 单行 `loss[=: ]` 正则抓不到 → 会误报 `loss 点 0`。用 `_parse_losses()` (键行→向下找第一个数字行)。
- 汇总从 stdout 里的 `汇总: <path>/summary.json` 真读回来 (`_train_summary()`), 拿到层/返回码/耗时/产物名 (如 `intact_goal_optical_insert_v6lora_20`)。
- **诚实口径**: 训练入口目前**不吃「任务→训练集」映射** (唯一依据无此表), 7 次训练数据同源, 只是各执行一遍; 文档里如实写。

## 3. 场景映射的真缺口 (别掩盖)
`tools/ss_scene_switch.py` 里只有 **3 条**任务↔场景映射 (老倪口述): `任务1 FW→插拔(#2e8b57)` / `任务6 TRAY→摆盘(#1f6feb)` / `任务7 AOI→AR(#8957e5)`。
HANDLE/BI/THERMAL/ATS **唯一依据里没有场景** ⇒ `--task <tid> --check --json` 返回 `action=skipped`。文档必须写「该任务唯一依据无场景映射 ⇒ 数据源不切」, 不能记成「在插拔场景上训练」。
补 4 条映射是**设计输入** (场景名+色标+数据源节点配置), 不许自己编。

## 4. 收口判据 `tools/verify_drill_report.py` (79 项)
只认盘上证据, 不看声明: 7 目录 · 配置链 7 域 · 元任务数>0 · 单步 ok>0 · 有真 topic · 引擎闭环那行 · ≥2 张非空波形 · 模型证据 ≥2 层 · 训练 rc/loss (skipped 明标) · 文档三件 · `drill_runs` 行与盘上路径一致 · 飞书 `message_id` · INDEX 7 条。
`--allow-no-train` 时训练项标 ⏭ 待办而不是放绿。

## 5. 今日修唯一依据的两处 (画布)
- **ckpt 路径写错**: `ss_moe` / `ss_lora_l4` 的 `params.ckpt` 按仓库根相对写 (`checkpoints/...`), 而仓库根没有 `checkpoints/`; 实物在 `zmax_data/stable-wm-cache/checkpoints/` (moe.pt 351,492,675 B)。修法: `tools/fix_canvas_ckpt_paths.py` (--dry 先看, 走 `flows.load_canvas/save_canvas` 带校验+备份, 回读一致才算过)。
- **主参数 M 未回写**: 画布 `n_calib_mani` 的 `M=1.0` 是默认值, 而按当前配置单算出的 `m_scale=3.283` (audit_sha `b06fe0f4e37d8a58`, 闸门 min_eig=20, metric=full) 要落进节点 → 跑 `tools/config_to_M.py --write`。**不是算错, 是没回写**。
- 画布唯一依据实际路径: `data/database/zmax/sources/canvas/state_space_obs.json` (`flows/state_space_obs.json` 与 `src/lerobot/engineering/flows/...` 都是软链)。**改画布只走官方 API**, 不要手改 JSON。
- `flows.load_canvas()` 返回 `(data, errors)` 二元组 (`validate=False` 才只返回 data)。

## 6. 改画布后的完整收口序列 (实测)
`ss_task_bind.py` → (改画布工具) → `engineering_db.py build` → `engineering_db.py check` → `canvas_level_audit.py`。
- `engineering_db.py build` **不删 `drill_runs`** (DROP 列表里没有它) ⇒ 演练证据与飞书 `message_id` survive build; 但 build 后再插证据的工具是演练自身的 `engdb_write`。
- **预存未修**: `canvas_completeness_check.py` 断言失败 `行带外节点 ['sslimit','sssk1']` —— 实测 y=5142 自 ≥2026-10-09 快照起就没变 (ssbg3 到 5126, ssbg_skill 从 5266 起, 中间 140px 空档), 与本次改动无关; 修它要移动节点 (视觉改动), 未获授权不动。
- `canvas_level_audit.py` 报 5 条「真缺口 (端点无执行注册)」, 含 `🧬 元数据MOE门控路由 (ss_moe)` —— 同为预存状态。

## 7. 演练实测口径 (7 个任务, 2026-10-14)
- 单步: 50/51 (HANDLE 41/42, AOI 30/31) —— 每任务都挂在 `📦 metaworld 数据源` 这一个节点。
- 引擎闭环: **7 个任务数字完全相同** (`done=False · 60 步 · 最小插入距 15.5mm · L4真推理9次 · 融合0帧 · L2收口否决60/60 方向`) ⇒ 闭环与训练**都不按任务条件化**, 任务差异只体现在配置链与启用节点数 (51/42/51/51/51/51/31)。报告时必须这么说, 不许说成「7 个任务各自验证通过闭环」。
- 训练: rc=0 · 21s · 8 个 loss 点 (每个任务一样)。
- 飞书: 每任务 3 条 (文字 + docx + pdf), `reports/drill/feishu_delivery.json` 记 `message_id`, 同时写进 `drill_runs.feishu_msg_id`。

## 8. 飞书投递的三个坑 (实测)
- `tools/feishu_send_file.py --text "说明"` **单独用会报「没有要发的文件」** —— 它是「文字+文件」一次发; 纯文字要用 `tools/feishu_send.py "文本"`。
- 500KB 左右的 pdf 上传会跑到 180s 以上 → 单文件超时给 280s, 否则 subprocess 被掐断后**消息可能已发出去、但你看不到成功回执**。
- **交付以群里的消息为准**: 用 `feishu_check_messages.py --n 50` 回读群消息核验 (按 `mine_list` 的 t/brief 逐条对), 不要用 stdout 计数 (brief 形如 `file: X.docx (? B)`, 用 `endswith('.docx')` 判类型会全错)。
- 文档内容变了就要**重发** (第一轮发完后才跑的训练/描述补全 → 群里那份是旧的): 重发后把 `drill_runs.feishu_msg_id` 改成定稿那轮的 id, 交付日志里记明轮次。
