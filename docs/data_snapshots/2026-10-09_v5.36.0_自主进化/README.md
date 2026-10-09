# v5.36.0 现场数据存档 (2026-10-09)

**主题**: 自主进化首版 —— 全系统联通体检 + 全量四层训练跑通 + 5 处真实缺陷修复

## 本目录文件
| 文件 | 是什么 |
|---|---|
| `zmax_engineering.db` | 单一工程库（24 表；本版 check 全绿） |
| `canvas_state_space_obs.json` | 状态空间画布真源（本版当时状态，74 功能节点全对齐代码） |
| `zmax_space.proj` | 总工程（7 段：画布/面板/标定/主参数/测量/任务/指纹） |
| `ss_task_binding.json` | 任务绑定（活跃 TASK-01-FW） |
| `zmax_calib.json` / `zmax_manifold.json` | 标定真源 + 主参数（M） |
| `l5_vlm_train_*.json` | L5 训练报告（120 步 · loss 0.58→0.12 · 3.12GB） |
| `l5_vlm_ab_*.json` | L5 同口径 A/B（基座 vs LoRA，12 帧） |
| `yolo_live_eval_*.json` | L2 同口径 A/B（在役 vs 新权重，40 张新鲜真机帧） |
| `judges.txt` | 本版判据实跑输出 |

## 本版关键结果
- 全量训练：L4 342.5s · L3 1373.8s(500步) · L2 30轮 · L5 120步/82s —— 四层都能训、都能推
- 同口径对照：L2 新权重 conf 0.662 vs 在役 0.649（检出同为 21/21）⇒ 未证明提升，**不上默认档**；
  L5 LoRA 合法率 0.75 vs 基座 0.8333 ⇒ 未证明提升（val 仅 12 帧，样本不足不下结论）
- 修的缺陷：存档 tasks 重绑 / 3 个 phantom 节点 / L5 清单旧路径 + _req 未初始化 / L2 data.yaml 旧路径 / 老机器写死路径

## 恢复方式
```bash
cp docs/data_snapshots/2026-10-09_v5.36.0_自主进化/zmax_engineering.db  data/database/zmax/
cp docs/data_snapshots/2026-10-09_v5.36.0_自主进化/canvas_state_space_obs.json \
   data/database/zmax/sources/canvas/state_space_obs.json
python3 tools/engineering_db.py build && python3 tools/engineering_db.py check
```
