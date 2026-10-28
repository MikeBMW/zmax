---
name: zmax-fullflow-7tasks-loop
description: Use when 循环跑 7 任务造数据→训练→推理全流程.
---

# Z-MAX 7 任务全流程闭环编排

老倪口径原话:「你来根据场景，造数据，训练所有模型，保证状态空间的数据闭环…循环配置所有7个任务，从仿真环境生成数据，训练，推理，再到任务7的真实环境推理，保证所有模型的依次运行，数据路径要通，流形引擎要预测每个元任务，将元任务预测的topic放到信号分析，写成报告发到飞书，开始全流程，全功率训练加推理，包括工控机联通AOI程序」。

编排器: `tools/fullflow_tasks7.py` (gui-venv311)。每个任务 5 段, 每段留日志+证据:

| 段 | 干什么 | 唯一依据/证据 |
|---|---|---|
| ① 配置任务 | `ss_task_bind.py --activate <T>` + `ss_scene_switch.py --task <T>` | `config/ss_task_binding.json` active_task |
| ② 仿真造数据 | `collect_simreal_vla_data.py --target N --out data/datasets/sim_<T>` | 收集器 stdout「✅ 完成: N 轨迹 / M 帧」+ `meta/tasks.parquet` |
| ③ 训练所有模型 | `joint_train_all.py --only L4,L3,L2,L5` | `reports/joint_train_*/stages.jsonl` + 每层 rc + GPU 峰值 |
| ④ 推理 | `ss_engine_loop.py run --encoder l4 --seconds 18` · `run_l4_intent_models.py` · `ss_meta_predict.py --scene <SCN> --write --json` | 回路口径 + L4 意图模型判据 + top-k 候选 |
| ⑤ 任务7 真机只读 | arm/local2 抓帧 · `tcp_out/latest.json` 位姿 · `aoi_call.py gold|surface` | 只读, 不下发动作 |

收尾: `reports/fullflow7/<ts>/REPORT.md` + `REPORT.json` → `tools/feishu_send_file.py`(报告群)。
`state.json` 是唯一依据, 可回填后重生成报告: `import fullflow_tasks7 as F; F.stage_report(run_dir, state, run_dir, send=False)`。

## 坑 (全部实测踩过)

1. **`collect_simreal_vla_data --target` 计的是成功轨迹数**, 失败 seed 每个空跑 ~20s。target=24 实测只出 8 条成功、其余「未完成, 跳过」把每任务白拖 4 分钟 ⇒ 用 **target 10** 左右 + 墙钟上限 (编排器已给 `SIM_TIMEOUT_S`, 默认 900)。轨迹/帧数**从收集器 stdout 解析**, 别去数 `episode*` 文件名 (LeRobot 布局是 `data/chunk-000/file-000.parquet`, 数不到 ⇒ 恒 0)。
2. **元任务预测的输入是 per-场景 tap** `/dev/shm/zmax_torque/torque_<SCN>.jsonl` (由 `tools/tdrive_bus.py` 写)。没跑过的场景没有 tap ⇒ `ss_meta_predict` 如实「不预测(不猜)」、候选 0 ⇒ 看起来「预测没做」。推理段要为该任务场景补一段真驱动扭矩再预测。
3. **`tdrive_bus` 单写入器锁** (`zmax_data/ss_live/torque.pid`): 常驻发布器在跑就抢不到锁 (报「已有写入器在跑」) ⇒ 补 tap 必须 `--instance <name>` (独立 pid 锁, tap 仍写同一 TAP_DIR, 对齐 `ss_engine_loop --instance`)。
4. **只给 `--scene` 不锁场景**: 发布循环每 5s「跟随活跃配置」, 会把 tap 写到别的场景去 (实测 `torque_SCN-02-HANDLE.jsonl` 里混进 SCN-07-AOI 的帧)。显式 `--scene` 必须锁住该场景。
5. **`run_l4_intent_models.py` 的任务/场景必须读当前 active_task**, 不能硬编码 (硬编码 TASK-06-TRAY 时换成别的任务 ⇒ ④⑦ 两条判据假 ❌, 报「8/10 有失败」)。
6. **预测「有输出」≠「预测有用」**: 核输入是否退化 —— 各场景驱动扭矩若完全相同 (实测 7 场景全 ‖T‖=51.9615 N·m, 位姿同一点) ⇒ 输出差别只来自各场景候选池, **无区分度** ⇒ 报告必须写这条, 不能写「7/7 预测成功」了事 (老倪零容忍)。tap 尾帧取 ‖T‖ 要读尾 256KB 后**倒序找完整行** (写入器还在追加, 末行常是半行)。
7. **飞书上传偶发** `URLError: [SSL: UNEXPECTED_EOF_WHILE_READING]` ⇒ 退避重试即可 (实测重试即成功), 别当成 token/权限问题 (那类错误是 99991663 ⇒ 重启 gateway)。
8. **训练前腾 GPU**: 停 L3 常驻回路等占卡进程 (`tools/ss_l3_loop_ctl.sh stop`), 跑完 `start` 起回; 「全功率」证据 = `joint_train_all` 的 GPU 峰值采样 (实测 100% / 6794MB @4060)。同刻只跑一个重模型进程 (工具内存 ~8GB, 超则 OOM)。
9. **日志重定向坑**: 后台跑编排器时 stdout 全进日志文件 ⇒ 进程心跳会显示「无新输出」, 要看 `reports/fullflow7/run7_full.log` 里 `── [TASK-xx] 完成` 行判进度 (实测 ~620s/任务)。

## 判据/验收

- 7/7 `── [TASK-0x-*] 完成 · Ns · infer rc=0`; 训练每层 rc=0; 无 ❌。
- 元任务预测: 7/7 任务有候选(≥30) **且** 报告里如实写出输入是否退化。
- 信号分析可见: DDS 新增 `zmax/ss_meta_pred` (dds/ss_types.py `SSMetaPred` + ss_daemon `pub_meta_pred` + `tools/gui/zmax_telemetry.py` 与 `src/lerobot/dataspace/topics.py` MODE_TOPICS) ⇒ 重启 `zmax-dataspaces-probe.service` (它才写 live.json) 后 live.json 话题数应从 10 变 14, `ss_meta_pred` 有值; 订阅器 `tools/dds_sub_meta_pred.py`。
- 任务7 真机段: arm 帧 bytes>0 · 位姿 `age_s`<30 · AOI 10082/10083 各 `code=200` (接口只投递不返判决)。

## 结果同步（老倪「飞书的结果，同步」= 三处同源，不是再发一遍）

1. **大屏**：`tools/fullflow_status.py`（新，只读 state.json + tap 尾帧；唯一依据键 `train.gpu_peak={util,mem}`）⇒ 已挂进
   `tools/dashboard_source.py` 的 `fullflow` 段 ⇒ 刷新大屏：`gui-venv311/bin/python tools/dashboard_source.py`
   （写 `zmax_data/datapush/dashboard.json` + `tools/web/dashboard.json` + `unified_app.html` 页内快照）。
2. **飞书卡片**：卡片渲染 `tools/feishu_dashboard_push.py`（已加「🔁 全流程闭环」行 + 输入退化/未跑异常项）
   ⇒ `--dry` 看 JSON、`--send` 真发（报告群）。发完**回读**：`tools/feishu_check_messages.py`，确认 message_id 在群里 `deleted:false`。
3. **归档快照**：`tools/snapshot_20261014_fullflow7.py` ⇒ `docs/data_snapshots/<日期>_<主题>/`（REPORT.md/json/state.json
   + MANIFEST.json + README.md，逐件 sha256；大文件 [全量日志/数据集/工程库] 只留绝对路径 + 重建命令，不进库）。
4. **提交/版本**：先 `python3 tools/verify_version_sync.py` 看偏差 ⇒ 修掉再提交。踩过：本机**没 gh CLI 也没 GitHub 令牌**⇒
   只能 `git push origin <tag>`，**远端 Release 建不了**（大屏会留一条版本同源偏差，要建 Release 必须先给令牌）。
5. 报告里固定不变的数字（如「磁盘 ~86%」）必须改成**实测** `shutil.disk_usage(ROOT)` —— 老倪会拿工具核。

## 相关技能

`live-service-change-discipline`(改常驻服务) · `zmax-console`(控制台/版本/窗口) · `manifold-engine-energy`(流形引擎数学与 tap) · `unattended-job-orchestration`(长跑+哨兵)。
