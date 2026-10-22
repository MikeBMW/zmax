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

### 全量训练档 (用户说「全量训练 / 全系统整体连跑」时用这组)
```
tools/fullflow_tasks7.py --sim-target 16 --steps 150 --yolo-epochs 12 --l5-steps 60
```
实测单任务分项 (4060, 全参训练, `--no-lora-l4 --no-lora-l3`):

| 阶段 | 实测 | 折算规则 |
|---|---|---|
| ② 仿真 16 轨迹 | ~60 s | 快，不是瓶颈 |
| ③ L4 INTACT | **97 s / rc=0** | ~0.6 s/步 + 启动 |
| ③ L3 SmolVLA | **4.80 s/step** ⇒ 150 步 ≈ 12 min | ~40 s 启动 + 4.8 s/步（**决定总时长**）|
| ③ L2 YOLO | ~32 s/epoch ⇒ 12 轮 ≈ 6~7 min | ~20 s 启动 + 32 s/epoch |
| ③ L5 Qwen LoRA | ~1 min | ~1 s/步 |

⇒ **单任务 ≈ 23 min, 7 任务 ≈ 2.7 h**（对比 40 步/3 epochs 的轻量档 ~480 s/任务、全程 ~75 min）。
选档原则: 要“链路通 + 有报告”用轻量档; 要“全量训练能拿上台面”用全量档, 并**先把 ETA 用实测速率报给用户**, 不要拿 75 分钟的经验值套。

启动与取证（缺一步就会“看起来没跑”）:
```bash
cd ~/zmax && LOG=reports/fullflow7/run_full_$(date +%Y%m%d_%H%M%S).log
setsid nohup gui-venv311/bin/python tools/fullflow_tasks7.py <档位参数> > "$LOG" 2>&1 < /dev/null &
tail -5 "$LOG"                     # 确认已进入 ② 并开始报 seed/traj
```
- 必须 `setsid ... < /dev/null`，否则会话一断训练就被带走（日志目录用 `reports/fullflow7/run_full_<ts>.log`，别复盖历史）。
- GPU 全负荷举证: 训练中连采 10 次 `nvidia-smi --query-gpu=utilization.gpu`，报**几次=100%**（实测 `0 73 100 99 100 0 100 100 100 100`），单点采样不算。
- 仿真阶段每条轨迹报 `插深 0.0mm` 属常见: 不代表轨迹失败，但**必须在报告里单列**（否则等于把“未插入”写成“已插入”）。

## 坑：L3 SmolVLA 会在中途"卡住"（不是跑得慢）
症状：日志停在某个 step 不再增长（实测 90/150）、GPU util **0%** 但显存仍占 ~6.9 GB、主线程 **99.9% CPU 自旋**、其余线程全 idle。
判据（三条同时满足就必须介入，别再等）：日志字节数 15 s 内的两次读取不变 + `nvidia-smi` util=0 且 power~11 W + 进程 STATE=R。
```bash
S1=$(stat -c%s $LOG); sleep 15; S2=$(stat -c%s $LOG)   # 相等 = 停
py-spy dump --pid <train_pid>                          # 本机: ~/.hermes/tools/*/bin/py-spy
```
实测栈：`inputs_merger`(modeling_smolvlm.py:488) → `torch_compilable_check` → `_check_tensor_all_with` 的 `cond._is_all_true().item()`，即**卡在 CUDA 流同步自旋，不是判据为假**。
诱因：内存压力（当时 swap 8.8 G 已用 / avail 9.4 G / 单进程 RES 8.6 G）。
处置顺序：① 降 `num_workers` 到 4~8、停掉 studio.py/chromium 等非必需进程；② 给 L3 加墙钟守护（单步 ~5.4 s，150 步 ≈ 13.5 min；>25 min 无增长即判卡死 → 杀训练/记栈/跳过该头继续 L2、L5）；③ 别把整条编排压在这一个头上——它停了 `fullflow_tasks7.py` 会一起等，7 任务整体作废。

## 坑 (都实测踩过)
1. **`collect_simreal_vla_data.py --target` 计的是成功轨迹数, 不是尝试数** — 失败 seed 每个还要空跑 ~20s
   (`tr["done"][-1]` 为假即「未完成, 跳过」)。target=24 时只出 8~13 条成功、白磨 4 分钟; **用 10**,
   并给仿真段加墙钟上限 (SIM_TIMEOUT_S, 默认 900) 防 target 不可达把循环拖死。
2. **判据脚本别硬编码任务**: `run_l4_intent_models.py` 曾写死 TASK-06-TRAY, 换任务后 ④摆盘轨迹真源/⑦回路口径
   两条判据假失败。真源 = `config/ss_task_binding.json#active_task` (+ 任务表的 scene_ref)。
3. **训练要独占显卡**: 先停自己的常驻回路, 跑完再起回。占 GPU 的不只 `l3_live.pid`,
   **`zmax_data/ss_live/engine_loop.pid` (ss_engine_loop --encoder l4) 是最大的一个**——先看
   `pgrep -af "ss_engine_loop|l3_live|ss_torque"` 把带 cuda 的逐个停（停前把 cmdline 记下来，跑完按原参数起回）。
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
- 用户说“连上机器人了”时，先做**只读四件套**并把数字报回去，再谈下一步: ① `curl 8793/pose` 200;
  ② `zmax_data/rokae_sdk/tcp_out/latest.json` 帧龄 (<1 s 才算活); ③ 相机 `8797/api/cams` 的 `online/age_s/fps`;
  ④ `calibrated` 字段。
  两个容易误判的点: `8793/status`、`/health` 类端点在这个服务上是 **404**（只有 `/pose`），别把 404 当链断;
  `ft_out/latest.json` 可以是隔天的旧文件（力矩流没在推）—— 不影响建图/训练，但要区分开报，不能说成“都在刷新”。
  相机 `calibrated=false` ⇒ 无内参/手眼，建图/3D 前先补内参，别直接跑。
- 老账照实说: INTACT z_pred NaN (上游动作块空), LoRA 未证提升前不进默认档。
