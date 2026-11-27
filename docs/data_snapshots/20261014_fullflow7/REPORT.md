# Z-MAX 7 任务全流程闭环报告

生成: 2026-10-15 06:14:58 · 运行目录: `reports/fullflow7/20261014_215744`

## 一、目标与结论
- 目标: 循环配置 7 个任务 → 仿真造数据 → 训练全部模型 → 推理 → 任务7 真机(只读)推理; 数据路径通、流形引擎逐元任务预测、元任务预测进信号分析、报告发飞书。
- 结论: 7/7 任务完成推理; 训练 7 个任务 rc=0; 仿真新增 70 条轨迹; 元任务预测 覆盖每个任务。

## 二、逐任务 (真跑证据)
| 任务 | 名称 | 场景 | 仿真数据 | 训练 | 推理 | 元任务预测 top1 | 结果 |
|---|---|---|---|---|---|---|---|
| TASK-01-FW | FW Loading + EEPRO | SCN-01-FW | 10 轨迹 4448 帧 | rc=0 484.7s GPU 100%/6794MB | L4 潜空间 接入 · 意图模型 rc=0 | FN-SYS2-29(0.052) | ✅ |
| TASK-02-HANDLE | 料盘/治具上下料搬运 | SCN-02-HANDLE | 10 轨迹 4377 帧 | rc=0 480.4s GPU 100%/6794MB | L4 潜空间 接入 · 意图模型 rc=0 | FN-SYS2-21(0.086) | ✅ |
| TASK-03-BI | BI老化箱模块插拔 | SCN-03-BI | 10 轨迹 4448 帧 | rc=0 514.7s GPU 100%/6794MB | L4 潜空间 接入 · 意图模型 rc=0 | FN-SYS2-21(0.086) | ✅ |
| TASK-04-THERMAL | 热海柜体电口+光口插拔 | SCN-04-THERMAL | 10 轨迹 4446 帧 | rc=0 471.5s GPU 100%/6794MB | L4 潜空间 接入 · 意图模型 rc=0 | FN-SYS2-21(0.086) | ✅ |
| TASK-05-ATS | ATS/线外检测插接 (核心挑战场景 | SCN-05-ATS | 10 轨迹 4445 帧 | rc=0 473.6s GPU 100%/6794MB | L4 潜空间 接入 · 意图模型 rc=0 | FN-SYS2-21(0.086) | ✅ |
| TASK-06-TRAY | 光模块摆盘 (周转盘 → 上料 Tr | SCN-06-TRAY | 10 轨迹 4447 帧 | rc=0 475.1s GPU 100%/6794MB | L4 潜空间 接入 · 意图模型 rc=0 | FN-SYS2-29(0.052) | ✅ |
| TASK-07-AOI | AR 光学质量检测 (AOI 联合检 | SCN-07-AOI | 10 轨迹 4445 帧 | rc=0 471.4s GPU 100%/6794MB | L4 潜空间 接入 · 意图模型 rc=0 | FN-SYS2-21(0.086) | ✅ |

## 三、数据路径 (闭环)
仿真采样 `collect_simreal_vla_data.py` → `data/datasets/sim_<TASK>/` (+ meta/tasks.parquet) → `joint_train_all.py --only L4,L3,L2,L5` → `reports/joint_train_*/stages.jsonl` + `outputs/train/*` → 推理 `ss_engine_loop --encoder l4` (L4 潜空间 VLM→度规→16 维) / `run_l4_intent_models.py` / `ss_meta_predict.py --scene <SCN>` → `zmax_data/ss_live/meta_pred.json` → DDS `zmax/ss_meta_pred` → 信号分析.

## 四、任务7 真机只读 (不下发任何动作)
- cam_arm: {"ok": true, "http": 200, "bytes": 22598}
- cam_local2: {"ok": true, "http": 200, "bytes": 17348}
- tcp_pose: {"ok": true, "age_s": 0.1, "x": 0.658505, "y": 0.008092, "z": 0.359935}
- aoi_gold_10082: {"rc": 0, "tail": ["{\"code\":200,\"msg\":\"success\"}", "", "✅ 已触发拍照+检测投递 (注意: 判决在工控机终端, 本接口不返回结果)"]}
- aoi_surface_10083: {"rc": 0, "tail": ["{\"code\":200,\"msg\":\"success\"}", "", "✅ 已触发拍照+检测投递 (注意: 判决在工控机终端, 本接口不返回结果)"]}

## 五、链路与资源
- 链路核对见 state.json 的 recon 段 (网卡/Orin/AOI 10082+10083/相机/位姿真值)。
- 磁盘余量: 训练前后记录在每任务 train.disk_free_gb_*。

## 六、瓶颈与缺口 (如实)
- 过程项无 (逐任务 rc=0 / L4 潜空间接入 True)
- 元任务预测覆盖: 7/7 任务有候选(≥30) · top1 取值 2 种 (FN-SYS2-21/FN-SYS2-29) · 驱动扭矩 ‖T‖ 取值 1 种 (51.9615)
- ⚠️ 真缺口: 7 个场景的驱动扭矩完全相同 (‖T‖=51.9615 N·m, 位姿同一点) ⇒ **元任务预测输入不含场景信息**、无区分度 (top1 差别只来自各场景候选池)。要真正按场景预测元任务, 须把场景相关特征 (工件/孔位/装配件) 并入驱动扭矩, 或训练预测头。
- 已知长期缺口: INTACT z_pred 仍 NaN (上游动作块空); LoRA A/B 未证明提升前不进默认档; 磁盘 84% (余 41.2GB)。
