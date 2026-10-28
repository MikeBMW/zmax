# Z-MAX 5.50.5 交付文档包 · 汇总索引

文档编号: ZMAX-IDX-5.50.5-20261013 · 版本: v1.0
编制: Z-MAX 工程组 · 日期: 2026-10-13 · 适用版本: **5.50.5**(与开发工程同版本, 取 `tools/gui/update_checker.py::CURRENT_VERSION`)
工程: `/home/ubuntu/zmax` · 对外口径:「符合 5 个场景的具身方案技术协议」
本版取代: 5.50.B(`INDEX_5.50.B.md` 保留作历史, 其 SOR/配置清单**已被本版取代**)

> 本索引汇总 5.50.5 交付文档包的全部文件、编号、适读对象与唯一依据依据。所有数字由工具从工程唯一依据**现取现算**并可复核；未达标/未实测项一律如实列明。

---

## 1. 交付文档清单

| # | 文档 | 编号 | 文件 | 适读对象 |
|:--|:---|:---|:---|:---|
| 1 | 供应商外发 SOR · 摆盘 TASK-06-TRAY | ZMAX-SOR-20261013-5.50.5 | `docs/deliverables/供应商SOR_摆盘_TASK-06-TRAY_5.50.5_20261013.{docx,md,json,manifest.json}` | 供应商 / 整机厂 |
| 2 | 全系统总配置清单 | ZMAX-CFGL-20261013-5.50.5 | `docs/deliverables/全系统配置清单_5.50.5.{md,json}` | 客户 / 供应商 / 运维 |
| 3 | **摆盘性能对账 + 主参数 M 映射对账** | ZMAX-PERF-20261013-5.50.5 | `docs/deliverables/摆盘性能对账_5.50.5.{md,json}` | 供应商 / 内部 / 评审 |
| 4 | 交付包说明(README) | ZMAX-PKG-20261013-5.50.5 | `docs/deliverables/README_交付包_摆盘TASK-06-TRAY_5.50.5.md` | 全部 |
| 5 | 交付包(zip) | — | `docs/deliverables/Z-MAX_交付文档_摆盘TASK-06-TRAY_5.50.5_20261013.zip` | 全部 |
| 6 | 本索引 | ZMAX-IDX-5.50.5-20261013 | `docs/deliverables/INDEX_5.50.5.md` | 全部 |

**历史件(不取代, 留档)**: `INDEX_5.50.B.md` · `全系统配置清单_5.50.{A,B}.*` · `供应商SOR_摆盘_TASK-06-TRAY_5.50.B_20261013.*` · `功能说明_5.50.{A,B}*` · `立项文档_Z-MAX_5.50.B_20261013.md` · `版本策略_5.50.A_B_C.md` · 2026-10-12 首批交付件。

---

## 2. 本版(5.50.5)核心变化

| # | 变化 | 依据/证据 |
|:--|:---|:---|
| A | SOR 新增 **附录 H 性能指标对账** / **附录 I 主参数 M** / **附录 J 验收试验设计** | `tools/sor_export.py` 读 `摆盘性能对账_5.50.5.json` 同源渲染(不手写数字) |
| B | 文档版本号与开发工程**同版本** | `_dev_version()` 现读 `tools/gui/update_checker.py::CURRENT_VERSION` ⇒ 只有一处唯一依据 |
| C | 摆盘场景信号命名 = 真空吸持/吸住(原“夹爪/抓住”为插拔底座旧名) | `tools/scene_signal_names.py`(命名唯一依据) + `verify_tray_vacuum.py` |
| D | 驱动扭矩话题 `ss_torque` 落为**常驻服务**并跟随活跃场景 | `tools/systemd/zmax-torque-bus.service` + `tools/tdrive_bus.py`(scene 从 `ss_scene_switch` 现取) |
| E | 数据空间发现层修复(单播配置 + 全参与者同一张) | `dds/cyclonedds_unicast.xml` + 四单元 `CYCLONEDDS_URI` + `tools/dds/gen_unicast_cfg.py` |

---

## 3. 判据总表(可复跑)

| 能力 | 判据脚本 | 结果 |
|:---|:---|:---|
| 主参数 M(度量张量) | `tools/verify_metric_main_param.py` | **23/23 PASS** |
| 配置单 → M 映射 | `tools/config_to_M.py --task TASK-06-TRAY` | 可跑(摆盘算得 M=4.423 · dim 6 · isotropic) |
| 摆盘末端工具 = 真空吸盘 | `tools/verify_tray_vacuum.py` | **PASS**(非夹爪) |
| 驱动扭矩话题端到端 | `tools/verify_driving_torque_topic.py` | **30 项 / 29 通过 / 1 未过**(未过=真录像依赖) |
| 性能对账(11 项) | `tools/delivery/gen_tray_perf_report.py` | 生成即判定(见 §4) |
| 任务绑定一致性 | `tools/ss_task_bind.py --check` | PASS |
| 工程库完整性 | `tools/engineering_db.py check` | PASS |

---

## 4. 未达标 / 未实测(跨文档汇总 · 诚实列出)

| # | 条目 | 目标 | 实测/现状 | 出现位置 | 取数命令 |
|:--|:---|:---|:---|:---|:---|
| 1 | 单颗节拍 | ≤3.15 s(硬上限 3.5 s) | **10.637 / 11.550 / 11.625 s ⇒ 未达标(约 3.4~3.7×)** | SOR §5 · 附录 H · README | `gen_tray_perf_report.py` |
| 2 | 节拍可达性(配置项) | 改配置即达标 | **代码级不可达**: `speed_scale` 闸恒 1.0、上限 1.5× < 需 3.38×、`est=11.0` 硬编码 | SOR 附录 H.3 | `gen_tray_perf_report.py` |
| 3 | 连续动作成功率 | ≥99% | **3/3(单 seed) 不构成证据**; 需 ≥299 颗连续 0 失效 | SOR 附录 H/J | 逐 seed 汇总 |
| 4 | 真空建立 | ≤200 ms | **425 / 537.5 / 525 ms ⇒ 全不合格(2.1~2.7×)** | SOR 附录 H · README | `reports/*.npz` judges[] |
| 5 | 真空保持 | 配置 5.0 s | 实测 5.49 s(超 9.7%) | SOR 附录 H | 同上 |
| 6 | 连续盘数 | ≥12 盘 | 未测(单盘 3 颗) | SOR 附录 J | 轮次日志 |
| 7 | 主参数 M 落役 | 在役 == 配置单算出 | **在役 3.283(dim3/full) ≠ 算出 4.423(dim6/isotropic) ⇒ 未落役** | SOR 附录 I · 对账表 #9 | `config_to_M.py` |
| 8 | 数据空间话题灯 | 全部绿 | `ss_state/ss_action/ss_link_value/ss_plan/ss_energy` 黑(办公模式无源); `ss_calib` 红(0.2 Hz 设计 vs 19.84 Hz 实测) | 配置清单 §7 | `zmax_data/dataspace/live.json` |
| 9 | 全部 58 条 `perf.*` | — | 唯一依据 `value` 空 ⇒ 待实测 | SOR §5 · 配置清单 §9 | `zmax_perf_spec.json` |
| 10 | 站点几何 `T_base_cam`/`plane_z`/`cell_geometry.points` | — | 未标定(唯一依据 null) | SOR 附录 C | `config/calib/zmax_calib.json` |
| 11 | 在役 L3 权重 sha256 | — | 未登记(`model.ckpt_l3`) | SOR 附录 C | `models/active_models.json` |
| 12 | 商务静态项(价格/交期/质保) | — | 待填 | SOR 附录 C | — |

---

## 5. 复核与再生成

```bash
# 性能对账(数字现取现算: 配置单 targets · 真跑产物 judges · M 唯一依据 · 扭矩判据)
python3 tools/delivery/gen_tray_perf_report.py --ver 5.50.5

# 重新导出 SOR(版本自动取开发工程版本) + 配置清单
gui-venv311/bin/python tools/sor_export.py --project PROJ-TH-TRAY --task TASK-06-TRAY --json
python3 tools/delivery/gen_config_inventory.py --ver 5.50.5

# 一致性闸
python3 tools/ss_task_bind.py --check && python3 tools/engineering_db.py check
```

> 再生成顺序有依赖: **先** `gen_tray_perf_report.py`(产出对账 JSON), **再** `sor_export.py`(附录 H/I/J 读它)。

---

*本索引所引数字均来自工程唯一依据与 2026-10-13 在役系统扫描/真跑产物；未达标与未实测项一律如实标注，不作推测、不柔化。*
