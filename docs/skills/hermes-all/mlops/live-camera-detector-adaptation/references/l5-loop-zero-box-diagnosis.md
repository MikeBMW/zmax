# L5 闭环 0 有效框：三类真因 + 报错口径坑

判据（红线，保持）：supervision 阶段 `mapped_boxes == 0` ⇒ 判失败、不继续训练。但**原因必须分类**，绝不能一句「相机离线」。

## 三类真因（用本阶段真有的量判）
1. `n_frames == 0` / 各路 `ok=false` ⇒ 流没起、相机离线
2. 有帧但 `objects == 0`（latency 极大）⇒ VLM 返回空或超时、图过暗
3. VLM 标了框但全不在训练类别表 ⇒ **本批画面里没有可训练目标**（不是相机/流的问题）

原因串里必须带证据：各路 ok 数 · 帧数 · `skipped_labels` 明细 · VLM 的 `scene` 描述。

## 已修的坑
失败原因判定读 `r["summary"]["n_ok"]`，而 `stage_supervision` 从不设置该键 ⇒ 恒为 0 ⇒ 无论真因都报「①所有相机都没拿到帧（相机离线）」，与现场矛盾。**判原因只能用本阶段真有的量**：`n_frames` / 各路 json 的 `ok` / `objects` 数 / `latency_s` / `skipped_labels` / `scene`。

## 口径
L2 训练类别表只有 `peg` / `OPT_Gold`；VLM 常标「插槽/托盘槽位、夹爪、线缆、手」⇒ 全被 skip 是**正确行为**，不要为了“验证通过”去扩类别表。

## 排查顺序
1. 看批次目录里每路 json：`cam / ok / n_obj / latency_s / scene`
2. 看 phase 统计：`mapped_boxes / skipped_boxes / skipped_labels / images_written / frames_no_box`
3. 全黑帧（`scene` 写「曝光为零/全黑」）= 相机问题，与标注链无关
4. 真验证通过的前提是画面里**有工件**：对准工件、或 `--cams` 只留有目标的路、或 `--batch-dir` 复用有目标的批次

## 编排纪律
控制台可派生该闭环（studio.py 起 `tools/l5_annotate_train_loop.py --run`）。单实例锁按 pid 判活，陈旧锁自动接管；报「已有编排在跑」= 旧进程**还活着**（被调试器断在异常里也算活着）⇒ 先 Shift+F5 停掉。
