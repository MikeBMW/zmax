# 2-天璇 · 作业任务

本层管**"这道工序现场怎么干"**：任务定义、工位、状态机、AOI/AR 作业流程。

## 文档分组

| 主题 | 文件 |
|---|---|
| 产线全景 | `光模块产线-全流程12工位场景定义.md` · `光模块产线-机器人场景设计.md` |
| 插拔作业 | `Z-MAX-插拔状态机.md` · `ss_task_binding_20261009.md` |
| AOI 金手指（10082） | `AOI_GOLD_DETECTION_CHAIN_20261012.md` · `AOI_GOLD_FRAME_V2_20261012.md` · `aoi_gold_servo.md` · `AOI_POINT_DANGER.md` |
| AOI 表面（10083） | `AOI_SURFACE_V20_1_20261012.md` · `AOI_SURFACE_EXPOSURE_20261012.md` |
| AOI 质量头/控制台 | `aoi_quality_head_and_console_20260924.md` |
| AR / 相机 / L5 | `AR_CAMS_L5_20261012.md` · `AR_AOI_TRAY_20261011.md` |
| 抓取放置 | `orin-grasp-place-workflow.md` · `orin-pipeline-kb.md` · `orin-workflow-analysis.md` |
| 界面 | `sidebar_3views_20261015.md` · `ui_slim_toolbar_menu_20261009.md` |

## 作业口径（三条）

1. **AOI 两条线不能混**：金手指 10082（工控机判决）/ 表面 10083（本机重算），端口禁用 84/85。
2. **参数错的帧上不谈缺陷**：取像不健康时质量门不据此判工件（见 `1-天枢-产品边界/patents/`）。
3. **真机动作要授权**：动作授权只从 8793 来，代发前先授权。

## 出口

- 这些能力怎么实现 → `3-天玑-能力功能/` / `4-天权-模型算法/`
- 节拍与达标 → `5-玉衡-指标验收/`
