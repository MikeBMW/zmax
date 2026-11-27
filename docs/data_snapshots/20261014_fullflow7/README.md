# 现场快照 · 7 任务全流程闭环 (2026-10-14)

口径 (老倪): 「循环配置所有7个任务…仿真环境生成数据, 训练, 推理, 再到任务7的真实环境推理, 保证所有模型的依次运行, 数据路径要通, 流形引擎要预测每个元任务, 将元任务预测的topic放到信号分析, 写成报告发到飞书, 开始全流程, 全功率训练加推理, 包括工控机联通AOI程序」

run 目录: `/home/ubuntu/zmax/reports/fullflow7/20261014_215744`

## 一、拷进库的证据 (逐件 sha256)

- `REPORT.md` · 3921 字节 · sha256 `e5a611556851d50ef271101ca93327134d78f548c08b2973901bd3b8c934c066`
- `REPORT.json` · 29060 字节 · sha256 `992af0f984b8137b8dd59ac82d155e4ba1c3520482cc7fee9f3ee5741cb4c6e5`
- `state.json` · 27982 字节 · sha256 `9ea268d0d5208d0c98f5fdd26ed15dde4c235dd1c22f82e0569e80fce122b9b9`

## 二、逐任务分段落日志 (仅记 sha256, 文件在 run 目录)

- **TASK-01-FW**: configure.log(296B), infer.log(11239B), sim_data.log(2333B), train.log(119101B)
- **TASK-02-HANDLE**: configure.log(398B), infer.log(8360B), sim_data.log(2337B), train.log(118813B)
- **TASK-03-BI**: configure.log(394B), infer.log(8257B), sim_data.log(2334B), train.log(119372B)
- **TASK-04-THERMAL**: configure.log(399B), infer.log(8386B), sim_data.log(2340B), train.log(119424B)
- **TASK-05-ATS**: configure.log(395B), infer.log(8282B), sim_data.log(2336B), train.log(118842B)
- **TASK-06-TRAY**: configure.log(507B), infer.log(11309B), sim_data.log(2337B), train.log(118683B)
- **TASK-07-AOI**: aoi.log(496B), configure.log(496B), infer.log(10820B), sim_data.log(2336B), train.log(118749B)

## 三、**未进库**的大文件/目录 (绝对值 + 重建命令)

- `/home/ubuntu/zmax/reports/fullflow7/run7_full.log` (900KB 全量日志)
  · 重建: `/home/ubuntu/zmax gui-venv311/bin/python tools/fullflow_tasks7.py --sim-target 10 --steps 40 --yolo-epochs 3 --l5-steps 20 > reports/fullflow7/run7_full.log 2>&1`
- `/home/ubuntu/zmax/data/datasets` (仿真 LeRobot 数据集, 7×10 轨迹/31056 帧)
  · 重建: `/home/ubuntu/zmax/tools/collect_simreal_vla_data.py --task "metaworld 光模块插拔 …" --target 10 --out data/datasets/sim_<TASK>`
- 训练产物 (L4/L3/L2/L5 权重) 见 `outputs/train/*` 与 `reports/joint_train_*/`

## 四、判据回放 (任意时刻可复跑)

- 大屏/卡片数据源: `python3 tools/fullflow_status.py` (只读 state.json)
- 元任务预测 topic: `tools/dds_sub_meta_pred.py`; 信号分析真源 `zmax_data/dataspace/live.json`
- 报告重生成: `python3 -c "import sys,json;sys.path.insert(0,'tools');import fullflow_tasks7 as F;F.stage_report('/home/ubuntu/zmax/reports/fullflow7/20261014_215744', json.load(open('/home/ubuntu/zmax/reports/fullflow7/20261014_215744/state.json')), '/home/ubuntu/zmax/reports/fullflow7/20261014_215744', send=False)"`
