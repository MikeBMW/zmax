# 2026-10-22 收工存档（全量连跑中断版）

> 本文只写实测到的东西。凡是"跑了但没跑完"的，明确标未完成，不写成已完成。

## 一、这轮做了什么

| 项 | 实测 |
|---|---|
| 启动 | 11:27:38 · `tools/fullflow_tasks7.py --sim-target 16 --steps 150 --yolo-epochs 12 --l5-steps 60`（全量档，L4/L3 全参，非 LoRA） |
| 独占显卡 | 先停 `ss_engine_loop`(原 PID 3303) 与 `auto_loop`(原 PID 6817)，cmdline 备份在 `zmax_data/backup_20261022_1127/loops.txt` |
| ① 配置任务 | TASK-01-FW 已激活，工程库同步（76 节点 / 204 连线 / 277 话题 / 115 信号） |
| ② 仿真造数据 | ✅ **完成 16 轨迹 / 7252 帧**，243 s → `data/datasets/sim_TASK-01-FW`（每条轨迹"插深 0.0mm"，照实单列，不等于已插入） |
| ③ L4 INTACT | ✅ **rc=0，113.9 s**，日志 `reports/joint_train_20261022_113143/L4.log` |
| ③ L3 SmolVLA | ❌ **卡死于 step 90/150**（action_loss 0.2371 时为最后一行，11:42:50），GPU 0% / 11 W，主线程 99.9% CPU 自旋，显存 6866 MiB 挂着不放 |
| ③ L2 YOLO / L5 LoRA | ⛔ 未开始（被 L3 卡住） |
| ④⑤⑥ 推理 / 真机只读段 / 报告 | ⛔ 未开始 |
| 其余 6 个任务 | ⛔ 未开始 |

### L3 卡死根因（py-spy 实测栈）

```
_check_tensor_all_with (torch/__init__.py:1773)        ← cond._is_all_true().item()  CUDA 流同步自旋
torch_compilable_check (transformers/utils/import_utils.py:1846)
inputs_merger (transformers/models/smolvlm/modeling_smolvlm.py:488)
   torch.all(num_image_tokens % patch_size == 0)        ← 判据本身只是 batch 级小张量
forward → _get_multimodal_embeds (lerobot/policies/smolvla_lew/modeling_smolvla_lew.py:214)
forward → update_policy (lerobot_train.py:136) → train (lerobot_train.py:639)
```

判读：**不是判据为假（那会直接抛错），是 `.item()` 卡在流同步自旋**。当时 `swap 8.8G/16G 已用、avail 9.4G、单进程 RES 8.6G`——归属内存/显存压力下的同步卡死，不是模型逻辑错。
证据：`zmax_data/archive/20261022_fullflow_abort/evidence/stall_stack.txt`（含停机上栈、内存、GPU 快照）
停滞时长：日志最后写入 **11:42:50**，其后两次间隔 15 s 取文件大小均为 101608 B（0 增长），GPU 全程 0%。注意本机时钟有跳变，故不报"精确 1.5 小时"，只报可复核的字节数与 mtime。

## 二、机器人侧（全程只读，未下发任何动作）

11:24–11:31 实测（网卡还在时）：
- `8793/pose` → 200，`age_s 0.14`
- `zmax_data/rokae_sdk/tcp_out/latest.json` 帧龄 0.2 s，pos=(0.6639, −0.0293, 0.2935)，frame=`base_link`
- `8797/api/cams` → arm 在线，`age_s 0.05`，fps 1.82，`calibrated=false`（无内参/手眼 ⇒ 本轮不做建图/3D 反投影）
- ECS `api/relay/orin/status`：Orin 在线，`robot_driver=true`、`motion=true`、`ros_domain=0`、cpu_temp 65.6 ℃、load1 31.2

**之后断链（本机侧，非机器人侧）**：
- `r8152` USB 有线网卡 `enx00e04c0c32a0`（产线 192.168.23.x）已从 `lsusb` 消失；`ip -br addr` 只剩 `lo / wlp0s20f3(10.163.146.78) / docker0`
- dmesg：12:52:38 网卡 reset 过一次，14:41:15–16 一批 USB 设备(1-3/2-2/1-4/1-8)断开，网卡随之掉出
- 后果：`tcp_out/latest.json` 帧龄停在 11:24 之后的旧值；`8791/8793` 相机流进程已退出；容器 `rokae_tcp_sampler` 报 `network: network connection` 已重启 12 次并处于 restarting
- **判读：机器人栈在 Orin 侧是活的（ECS 遥测为准），断的是本机 USB 网卡 ⇒ 现场需要重插/复位那块 USB 网卡，不是机器人掉线**

## 三、数据已保存到哪里

| 内容 | 路径 | 校验 |
|---|---|---|
| 场景数据快照 | `zmax_data/snapshots/scene_20261022_131511.tar.gz` + `MANIFEST_20261022_131511.json` | 49 文件 · sha256[:16] `5bc7d47289b6c719` · 自校验 ✅ |
| 本轮现场存档 | `zmax_data/archive/20261022_fullflow_abort/`（1.6 MB） | 编排日志 + 三层训练日志 + 卡死证据 + sim 数据集整包副本 |
| 仿真数据集（原地） | `data/datasets/sim_TASK-01-FW`（7252 帧 / 1.3 MB，整包已复制进存档） | 16 轨迹 |
| L4 权重 | `zmax_data/stable-wm-cache/checkpoints/intact_goal_optical_insert_v6lora_150_20261022_113143/weights_epoch_1.pt`（rc=0 产物，已核对存在） | — |

## 四、下电前预检（tools/preflight_shutdown.sh）

- ✅ 机械臂无真动授权（`ctl_auth.json` 窗口已过期，epoch=196；VL 现场放行不存在 ⇒ fail-closed）
- ✅ 无采集/训练在写（本轮训练进程已全部停止，GPU 已释放）
- ❌ 家目录顶层有 2 个 zmax 相关项：`zmax` + `zmax_data`（后者是 41 MB 的旧副目录：ar_browser/evidence/hf_cache/logs，与 `zmax/zmax_data` 不是同一份；本轮不动它）
- ⚠️ 仓库未提交 10 个（均为 tmp 探针脚本与新 deploy 文件，见下）
- ✅ 磁盘 113 GB 可用（71% 已用）· 内存已用 7 G / 30 G
- ✅ 服务单元 38 个在跑 · 容器 `ss-remote-tap` / `zmax-sdk-arm-agent` Up；`rokae_tcp_sampler` restarting（网卡掉，正常现象）

## 五、开机后按序做（别跳）

```bash
cd ~/zmax
# 0) 先确认 USB 网卡回来（这是本轮断链的唯一根因）
ip -br addr | grep -E 'enx|enp|eth'      # 没有 ⇒ 现场重插那块 r8152 USB 网卡
ping -c2 192.168.23.66 && ping -c2 192.168.23.160

# 1) 位姿真值 + 相机流回来
sudo docker restart rokae_tcp_sampler
bash tools/cam_live_stream_ctl.sh           # 8791+8793；进程已死时它会用内置默认 argv 起，活着则按原参数重启
curl -s localhost:8793/pose | head -c 200    # age_s 要 < 1

# 2) 把为训练停掉的两个常驻回路按原参数起回
pgrep -af "ss_engine_loop|auto_loop"         # 空 ⇒ 起
nohup gui-venv311/bin/python tools/ss_engine_loop.py run --hz 10 --encoder l4 --l4-hz 1 \
  --l4-frame-url http://127.0.0.1:8799/frame.png --pipeline --pipe-every 10 \
  --pipe-img http://127.0.0.1:8799/frame.png >> zmax_data/logs/ss_engine_loop_restore.log 2>&1 &
nohup venvs/lerobot-venv/bin/python tools/auto_loop.py >> outputs/auto_loop.log 2>&1 &

# 3) 续跑全量档（TASK-01 会从 ② 重来；若要跳过已完成任务加 --resume）
#    先按"防再次卡死"改参数：L3 步数降到 100，并限制 dataloader worker 数（见下）
tools/fullflow_tasks7.py --sim-target 16 --steps 100 --yolo-epochs 12 --l5-steps 60
```

## 六、下次跑之前必须先做的两件事（针对本次卡死）

1. **不要把 16 个 dataloader worker 和 8.6 G 模型同时塞进 30 G 内存**：本轮 swap 用到 8.8 G。L3 训练前把 `num_workers` 降到 4–8（`configs/generated_train_configs/config_smolvla_lew_lora_*`），并把 `studio.py`、chromium 等非必需进程停掉。
2. **加墙钟守护**：L3 单步 5.4 s，150 步 ≈ 13.5 min；超 25 min 无日志增长就判卡死 → 杀训练、记栈、跳过该头继续 L2/L5（不要像本轮这样整条编排停在 90/150）。

## 七、如实口径（别把没做的说成做了）

- 全量档**没有跑完**：7 个任务里只有 TASK-01 的 ①② 完成、③ 只完成 L4；L3 卡死，L2/L5 与 ④⑤⑥ 全未开始。
- 仿真段的"插深 0.0mm"未改善，仍是结构先验式轨迹，不代表插入成功。
- 元任务预测 `trained=false / degraded=true`（驱动扭矩恒定的老账），未在本轮修。
- intel 192.168.23.70 仍掉线（连同 8801 边缘建图/推理不可用），本轮推理全部走本机。
