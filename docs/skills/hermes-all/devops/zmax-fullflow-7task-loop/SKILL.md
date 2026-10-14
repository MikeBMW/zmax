---
name: zmax-fullflow-7task-loop
description: Use when 要跑 Z-MAX 7 任务全流程闭环 (仿真造数据→训练→推理→报告→飞书) 或要把话题接进信号分析.
version: 1.0.0
author: Hermes
license: proprietary
metadata:
  hermes:
    tags: [zmax, fullflow, data-loop, dds, signal-analysis]
    related_skills: [zmax-console, zmax-data-closed-loop, manifold-engine-energy]
---

# Z-MAX 7 任务全流程闭环 (仿真造数据 → 训练 → 推理 → 报告 → 飞书)

## When to Use
- 「循环配置所有7个任务，从仿真环境生成数据，训练，推理」/「全功率训练加推理」/「数据路径要通」
- 「把 <某话题> 放到信号分析」

## 编排器 (唯一入口, 别手搓命令)
`tools/fullflow_tasks7.py` — 每任务 5 段真跑, 每段落证据, 可续跑:

```
gui-venv311/bin/python tools/fullflow_tasks7.py \
  --sim-target 10 --steps 40 --yolo-epochs 3 --l5-steps 20 [--tasks TASK-01-FW,...] [--resume] [--no-feishu]
```
① 配置任务 `ss_task_bind --activate <T>` + `ss_scene_switch --task <T>` (画布数据源同切)
② 仿真造数据 `collect_simreal_vla_data.py` → `data/datasets/sim_<T>/` (LeRobot: data/chunk-000/*.parquet + meta/)
③ 训练 `joint_train_all.py --only L4,L3,L2,L5` (每层 rc/耗时 + GPU 峰值采样)
④ 推理 `ss_engine_loop --encoder l4` + `run_l4_intent_models.py` + `ss_meta_predict --scene <SCN>`
⑤ TASK-07 追加真机**只读**推理 (8791 arm 帧 + tcp_pose 真值 + AOI 10082/10083 各真调一次)
收尾: `reports/fullflow7/<ts>/REPORT.md|json` + `tools/feishu_send_file.py` 发报告群。

节奏参考 (4060, 10 轨迹/任务, L4/L3 40 步): **~630s/任务, 7 任务 ≈ 75 分钟**; 单任务训练 GPU 峰值 ~100%/6.7GB。

## 坑 (都实测踩过)
1. **`collect_simreal_vla_data.py --target` 计的是成功轨迹数, 不是尝试数** — 失败 seed 每个还要空跑 ~20s
   (`tr["done"][-1]` 为假即「未完成, 跳过」)。target=24 时只出 8~13 条成功、白磨 4 分钟; **用 10**,
   并给仿真段加墙钟上限 (SIM_TIMEOUT_S, 默认 900) 防 target 不可达把循环拖死。
2. **判据脚本别硬编码任务**: `run_l4_intent_models.py` 曾写死 TASK-06-TRAY, 换任务后 ④摆盘轨迹真源/⑦回路口径
   两条判据假失败。真源 = `config/ss_task_binding.json#active_task` (+ 任务表的 scene_ref)。
3. **训练要独占显卡**: 先停自己的常驻回路 (`kill $(cat zmax_data/ss_live/l3_live.pid)`), 跑完再起回。
   同刻两个训练进程 = 8GB OOM。
4. 后台长跑把 stdout 重定向进文件 (如 `reports/fullflow7/run7_full.log`); 进程包装层会「无新输出」,
   属正常 — 进度看**日志文件**, 不要以为卡死。
5. 仿真阶段证据取收集器真报数 (`✅ 完成: N 轨迹 / M 帧`), 别去数 `episode*` 文件名 (布局是
   `data/chunk-000/file-000.parquet`, 数文件名恒 0)。

## 把话题接进「信号分析」(4 处 + 重启哪个服务)
真源链: 发布者 → DDS topic → `zmax_data/dataspace/live.json` → 信号分析页 (读 live.json + busdb)。
**live.json 的写者是 `zmax-dataspaces-probe.service`** (`venvs/dds-venv/bin/python src/lerobot/dataspace/probe.py --watch --interval 2`),
**不是** `zmax-dataspaces-loop.service` (那个写 loop.json)。话题清单 = probe 的
`self.keys = T.topics_for_mode(mode)`, mode 来自 `~/.zmax_telemetry_mode`, 表在
`src/lerobot/dataspace/topics.py::MODE_TOPICS`。

加一条话题 (以 `ss_meta_pred` 为例, 全跑通):
1. `dds/ss_types.py` 加 IdlStruct 类型 (镜像同类, 如 SSMetaTask)。
2. `dds/zmax_node.py` 注册 type + QOS class。
3. `tools/dds/ss_daemon.py` 加 `pub_<x>()` + MODE_TOPICS + 挂到 tick 线程; **别用 `ZMAX_DATA` 变量**
   (不存在), 用 `os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")` 拼路径。
4. `src/lerobot/dataspace/topics.py::MODE_TOPICS` (diag/calib/test) + 目录册条目;
   `tools/gui/zmax_telemetry.py::MODE_TOPICS` 同改。
5. 重启 `zmax-dds-ss.service` (发布者) 与 **`zmax-dataspaces-probe.service`** (live.json 写者);
   等 30~40s 再回读, 别在 15s 内下结论。

回读判据:
```
sudo systemctl restart zmax-dds-ss.service zmax-dataspaces-probe.service
CYCLONEDDS_URI=file:///home/ubuntu/zmax/dds/cyclonedds_unicast.xml \
  venvs/dds-venv/bin/python tools/dds_sub_meta_pred.py --seconds 22
# live.json 话题数应从 10 → 14, 且新话题有 hz/fields
```
元任务预测 topic 已存在: `zmax/ss_meta_pred` (输入 = 流形引擎驱动扭矩 tap; 5s 节拍;
帧龄 >180s 自动标「预测陈旧」; trained/frozen 如实转发)。

## 如实口径 (别把「跑过」说成「有效」)
- 训练 rc=0 + GPU 峰值才叫全功率证据; 判据几比几要报原文行。
- 元任务预测未训练头/恒定输入 ⇒ 只报得分, 附 `frozen/degraded` 与「仅供参考」。
- 真机段是**只读** (抓帧/读位姿/调 AOI), 不下发动作; 授权只从 8793 且需现场放行。
- 老账照实说: INTACT z_pred NaN (上游动作块空), LoRA 未证提升前不进默认档。
