# 现场快照 · 媒体清单 (图不入库, 本机原路径可直接看)

口径 (老倪 Git 精简): **图/大二进制不进代码库**, 快照目录只留可复核的清单。
本文件 = 这些图的**名字 + 字节 + sha256(前16)**; 图本身仍在仓库工作区的原路径 (`.gitignore` 挡的是入库, 不是删文件)。
重建/出图命令见各快照目录的 README (本页最后一节给北斗那批的命令)。

| 文件 (相对仓库根) | 字节 | sha256(前16) |
|---|---|---|
| `docs/data_snapshots/2026-10-10_配置驱动双功能/L4L5对比表.png` | 299807 | `f957b43f8fd933a6` |
| `docs/data_snapshots/2026-10-10_配置驱动双功能/切换参数对比表.png` | 345516 | `5eaf62d9696c447f` |
| `docs/data_snapshots/2026-10-10_配置驱动双功能/切换配置证据表.png` | 157537 | `6245277fbe7d503a` |
| `docs/data_snapshots/2026-10-10_配置驱动双功能/切换验证证据图.png` | 162845 | `2c2c7719244f5719` |
| `docs/data_snapshots/2026-10-10_配置驱动双功能/四层同跑_插拔.png` | 198467 | `25c987c7923c4edf` |
| `docs/data_snapshots/2026-10-10_配置驱动双功能/四层同跑_摆盘.png` | 297600 | `67b00f1853e21d3d` |
| `docs/data_snapshots/2026-10-10_配置驱动双功能/控制台_v5430_参数表710.png` | 1208315 | `54f1e1c9a5853745` |
| `docs/data_snapshots/2026-10-10_配置驱动双功能/控制台_v5430_配置中心视图.png` | 964275 | `bc70a5768ee64687` |
| `docs/data_snapshots/2026-10-12_标准打开流程_v5.49.3/shots/matrix_TASK-01-FW.png` | 722957 | `e237840d2b0aa6b4` |
| `docs/data_snapshots/2026-10-12_标准打开流程_v5.49.3/shots/matrix_TASK-06-TRAY.png` | 722957 | `e237840d2b0aa6b4` |
| `docs/data_snapshots/2026-10-12_标准打开流程_v5.49.3/shots/matrix_TASK-07-AOI.png` | 722957 | `e237840d2b0aa6b4` |
| `docs/data_snapshots/20261008_aoi_gold_judge_v21/compare/deploy_v21_gold_judge_now.png` | 217439 | `aace08c9e08c7e20` |
| `docs/data_snapshots/20261008_aoi_gold_judge_v21/compare/deploy_v21_gold_origin_now.png` | 110660 | `b9413fca448116f8` |
| `docs/data_snapshots/20261008_aoi_gold_judge_v21/judge_live_after_clean_restart.png` | 30962 | `bde94d8d043491ae` |
| `docs/data_snapshots/20261015_config_center_seven_stars/banner_天玑_功能性能模型.png` | 47149 | `c405f16f5236fe08` |
| `docs/data_snapshots/20261015_config_center_seven_stars/config_center_full.png` | 479890 | `42cfeb998b31d0d2` |
| `docs/data_snapshots/20261015_config_center_seven_stars/console_real_064912.png` | 1145802 | `202aef711ea4f705` |
| `docs/data_snapshots/20261015_config_center_seven_stars/real_1_天璇.png` | 1130924 | `324078f4611b1ad5` |
| `docs/data_snapshots/20261015_config_center_seven_stars/real_2_天枢.png` | 817656 | `80d51a353e037214` |
| `docs/data_snapshots/20261015_config_center_seven_stars/real_3_天玑.png` | 1009340 | `8970aebceb84cda8` |
| `docs/data_snapshots/20261015_config_center_seven_stars/real_4_玉衡.png` | 998946 | `347cab70f669a0af` |
| `docs/data_snapshots/20261015_config_center_seven_stars/real_page_full.png` | 998946 | `347cab70f669a0af` |

## 北斗七星阵那批 (20261015) 的重建命令

```bash
cd /home/ubuntu/zmax
# 真显示器渲染 (需 DISPLAY=:0), 出 4 张页签图 + 整页图:
DISPLAY=:0 ./gui-venv311/bin/python tools/show_config_center_7star.py
# 整屏实拍 (真控制台):
DISPLAY=:0 scrot -o docs/data_snapshots/20261015_config_center_seven_stars/console_real.png
# 离屏判据 (不看图也能判: 次序/序号/星名/一页只亮一颗/不截断):
QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python tools/verify_config_center_seven_stars.py
```

## 工程库快照 (.db · 单文件=一套工程; 同样不入库, 本机原路径可查)

| 文件 | 字节 | sha256(前16) |
|---|---|---|
| `docs/data_snapshots/2026-10-09_v5.34.0_侧栏UI定版/zmax_engineering.db` | 937984 | `01b89aaae51a886b` |
| `docs/data_snapshots/2026-10-09_v5.35.0_平台实例解耦/zmax_engineering.db` | 950272 | `e2240ee6e229a1cf` |
| `docs/data_snapshots/2026-10-09_v5.36.0_自主进化/zmax_engineering.db` | 950272 | `4b00ce1072b34ef2` |
| `docs/data_snapshots/2026-10-09_关机收尾_v5.34.2/zmax_engineering.db` | 937984 | `be1fe2bee430ef99` |
| `docs/data_snapshots/2026-10-11_关机收尾_v5.47.1/zmax_engineering.db` | 1298432 | `1e72391cab2ae166` |
| `docs/data_snapshots/2026-10-11_状态同步_v5.47.0_配置驱动功能切换+场景叠加/zmax_engineering.db` | 1298432 | `1e72391cab2ae166` |
| `docs/data_snapshots/2026-10-12_关机收尾_v5.49.1/zmax_engineering.db` | 1323008 | `cf79849f2b1886de` |

重建: 这些是当次迭代的 `data/database/zmax/zmax_engineering.db` 拷贝 —— 用工程库工具
`tools/zmax_engineering_db.py build` 可从 `zmax/sources/` 重新生成, 逐版本可比对 sha256。
