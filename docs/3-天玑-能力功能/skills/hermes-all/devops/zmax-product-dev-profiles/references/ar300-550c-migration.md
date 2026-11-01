# AR 300UPH 配置链 + 550A→550C 迁移（实操清单）

场景：本机 4060 按 550A 开发完整工程 → 推 Intel 550C 工厂执行。**全程 AR 仿真，真机零指令（`real_cmd=false`）**。

## 六步交付链（每步都有自带判据，缺一条不算完）

| 步 | 工具 | 判据 |
|---|---|---|
| ① 元任务 | `tools/ss_meta_task_ar.py` | 392 段逐段重建一致；次数守恒 5/5 |
| ② 四类配置 | `tools/ar300_config.py` | 功能 module_ref→画布名 100% 命中；TASK 绑定 8 段；模型 4/4；perf 4 条；工位 1 |
| ③ 工单 | `tools/ar300_workorder.py` | 10 项：工序=4 元任务 / 每步带 arm+meta_task / ar_300uph=300 |
| ④ 文档 | `project_doc_export.py` + `sor_export.py --task TASK-07-AOI` | 立项 `--check` 全绿；SOR 附录 A-J 齐 |
| ⑤ 迁移 | `tools/push_ar300_to_550c.sh` | Intel 侧回读 8 项 |
| ⑥ 节点跑起来 | `tools/deploy_ssplan_550c.sh` | `ar_cmd.json` 带 `mt_id` 且龄 <5s |

## 🔴 迁移三大坑（都实际踩过）

1. **段表不在清单里** → Intel 上 `plan_long_impl.run()` 静默返回 `{"out1": None}`（不报错！）。根因是 `_load()` 里 `os.path.getmtime(_PLAN)` 抛 OSError 后 `LAST_STATUS` 只写状态不抛异常。
   必须推 `zmax_data/runtime/traj/sim_insert.json`。判定：`ar_cmd.json` 不生成 + `out1=null` ⇒ 先查段表。
2. **`ZMAX_UPH_AR_PUB=0` 不写 ar_cmd** → 服务 active、日志正常、`canvas_loop.json` 有 tick，但 `ar_cmd.json` 不存在。要设 `1`。
3. **`load_project()` 读工程库不读画布 json** → 画布 json 94 节点，节点循环只加载 79（可执行集）。两边都 79 才是对的；别拿 94 当基准去查“丢了 15 个节点”。

## Intel 侧路径事实（省得到处 find）

- `/home/intel/zmax` → **软链** 到 `/home/intel/zmax_550c`（同一个目录，别以为是两份）
- 档位真源：`defaults/config/platform/zmax_product.json`（**不是** `config/platform/`）
- `config/` 下只有 `orders/`（本地覆盖层）
- 服务 WorkingDirectory = `/home/intel/zmax_550c`，python = `/home/intel/gsxun-venv/bin/python`（gsxpu-venv）
- SSH 免密可用（key 已配）：`ssh intel@192.168.23.70`

## 工单生成的两个陷阱

- `flows/scenes_5jobs.json` 是真源，`config/orders/*.json` 是生成物（勿手改）。要改工单先改场景。
- `build_sheet.py` 只搬 `t/dur/name/desc/force` 五个字段，**`arm`/`meta_task` 会丢**；`recipe` 是 **list** 不是 dict。要双臂/元任务归属必须在生成后做后处理补回。
- 所有工单 readiness 会被 `T_base_cam` / `plane_z` 未标定拖红（AR 链用段表几何不受影响，真机前必须补）。

## 改节点名会连带破配置

改画布节点名 → 必须同步 `config_meta.json` 里该功能的 `name` + `module_ref`，否则「功能 module_ref → 画布节点名 100% 命中」判据破。
实例：`ssllm` 从「L3 长程序列规划器」改名后 `FN-SYS2-02` 立刻失配；`FN-SYS0-59` 的 `module_ref` 写「MoveIt 运动规划 · SDK 直驱桥」，而画布 `n_moveit` 实际叫「运动规划」（历史遗留漂移）。
修法：`ar300_config.py` 内置 `drift_fix` 映射，幂等自动对齐。

## AR 开关会过期（页面回落自播）

`exec_switches.json` 有 30 分钟新鲜度（`AR_SW_FRESH_S=1800`）。控制台一夜不开就过期，
`/api/ar/mode` 返回 `raw_ar_scene=true` 但 `ar_scene=false` ⇒ 页面有动画但 `PREV.ssOn=0`（自播，不是状态空间驱动）。
重新 `set_ar_switch.py 1 0` + `pub_exec_switches.py 1 0` 即恢复。
