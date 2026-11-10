# 5-玉衡 · 指标验收

本层管**"多少秒、多少毫米、达标没有"**。只放可复现的数字，不放形容词。

## 文档分组

| 主题 | 文件 | 结论 |
|---|---|---|
| 300UPH 主证据 | `zmax_300uph_verification.md` | 仿真闭环 314 件/时（11.47s/件） |
| 300UPH 模型 IO | `zmax_300uph_model_io.md` | 模型输入输出口径（含 `l4_cond_injected` 历史缺口） |
| 300UPH 全局分析 | `zmax_300uph_global_analysis.md` | 瓶颈分解 |
| 300UPH 收口 | `zmax_l2_300uph_closure.md` · `l2_300uph_closure_20261102.json` | L2 侧收口判据 |
| 流形引擎 AB | `zmax_mani_engine_ab_test.md` | 引擎开关对照 |
| LoRA 对齐 AB | `lora_align_ab_20260924.md` | 合并前后对照 |
| L4 运行时证据 | `l4_runtime_evidence_matrix_20260922.md` · `l4_stats_caliber_fix_20260922.md` | 口径修正记录 |
| 负样本 | `zmax_gold_detector_negative_result.md` | **不写成功也写失败**：证明不了的如实记 |
| 正式测试报告 | `test-reports/` | ⚠️ `MASTER-TEST-REPORT.md` / `F03-orin-inference-test.md` 被 `src/lerobot/verification/verification_layer.py` 按路径校验，**缺文件即 FAIL** |

## 判据四条

1. 每个数字必须带**同口径对照**（基线 vs 改动后）
2. 每个数字必须带**复现命令**
3. 说不清的写「未测」，不写「大约 / 差不多」
4. 负结果也是结果 —— 进了默认档的东西必须有"有提升"的证据，不能只有"不回退"

## 出口

- 数字背后的模型 → `4-天权-模型算法/`
- 数字怎么测的 → `6-开阳-工程落地/`
