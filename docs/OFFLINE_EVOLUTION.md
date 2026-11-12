# 离线自主进化 (2026-11-12)

现场一走，机器人位姿、相机画面、工控机程序、Orin 驱动全都不在了。这份手册管两件事：

1. **先把现场抄下来**（断网前几分钟能做完，1.5MB）
2. **断网后照样进化**（不依赖现场任何服务、不依赖外网，判据不变）

---

## 一、抄现场：`tools/site_snapshot.py` + `tools/site_inventory.py`

```bash
# 1) 数据面: 位姿序列 / 相机帧 / AR 帧 / 配置 / 代码指纹 / Orin 口径
python tools/site_snapshot.py --seconds 90 --frames 6 --gap 3
#    产物: zmax_data/site_snapshot/<ts>/{pose,frames,labels,ar,cfg,code,orin,manifest.json}

# 2) 程序面: 三机的服务/端口/ExecStart/隧道/代码版本 + Orin ROS 话题类型与节点
python tools/site_inventory.py --out zmax_data/site_snapshot/<ts>
#    产物: inventory.json
```

**实测（2026-11-12 19:43-19:47，现场在线时）**

| 项 | 实测值 |
|---|---|
| 位姿序列 | 893 拍 / 90s（含 xyz + abc_deg + quat + src，来源 8791 `/pose` = SDK 原生 p6，与产线 `/robot/tcp_pose` 同口径） |
| 相机帧 | 24 张（arm / local / overlay_arm / overlay_local），每帧同刻 `/boxes` 一并存 |
| AR 帧 | 8802 `/frame.png` |
| 配置 | 15 个（calib / 产品档 / 画布 / DDS 类型等） |
| 代码指纹 | git `008c9f77` + 5 个核心文件 md5 |
| Orin 口径 | 46 话题 + `/robot/tcp_pose`=PoseStamped(1 发 3 收) + `/joint_states`=JointState + 节点 `/d405_color_pub /external_comm /gripper_drive` |
| 三机程序 | 本机 40 服务/37 监听 · 550C 40/32 · Orin 8/23；隧道 4 条（含 `-L 10082:192.168.23.23:10082`） |
| 体积 | 1.5MB（已另存 550C `~/zmax_map/zmax_data/site_snapshot/<ts>`） |

**两条别踩的坑**

- **AOI 10082/10083 在本机只是 ssh 隧道**（`ssh -N ... -L 127.0.0.1:10082:192.168.23.23:10082 orin-lan`）。现场 AOI 机器一断，本机端口还在听但连接被 reset ⇒ 快照里要记"经隧道转发 + 目标不可达"，别把它当成"服务在本机"。
- Orin 的 ssh 别名 `orin` 走 wifi（192.168.43.19），断网就死；产线口是 `orin-lan`（192.168.23.66）。快照器优先 `orin-lan`。

---

## 二、断网进化：`tools/offline_evolve.sh`

```bash
bash tools/offline_evolve.sh --rounds 4 --n 400 --clutter 6 --epochs 30    # 正式
bash tools/offline_evolve.sh --rounds 1 --n 16 --clutter 6 --epochs 1 --fullflow 0   # 冒烟
```

它保证四件事：

1. **真离线**：在 `sudo unshare -n` 里跑，只有 `lo` 且 DOWN —— 没有外网，连本机 127.0.0.1 都没有。开场自证 `ip -br addr` + `curl 1.1.1.1`，不过就 `exit 8`。
2. **不污染现场台账**：沙箱根默认 `/tmp/evo_offline`（`ZMAX_OFFLINE_ROOT` 可改），训练/台账全在沙箱；现场 `zmax_data/ar_evolve/ledger.json` 不动。
3. **判据同一把尺子**：主判据仍是 hard 留出集（clutter16, seed 31337）的 **mAP50-95**，mAP50 只做"不许回退"护栏。留出集缺了就本地 mujoco 造（不需要网）。
4. **不抢现场显存**：默认 `ZMAX_TRAIN_DEVICE=cpu`；现场训练停了可以 `ZMAX_TRAIN_DEVICE=0` 用卡。

### 实测（同一台机、`unshare -n`、CPU）

```
✔ 离线自证: 无外网 / 无本机回环 (只有 lo DOWN)
数据: 造 24 张 (clutter 6)                1.7s
训练: 1 epoch                            11.9s
评测: hard  mAP50=0.7847  mAP50-95=0.7004  recall=0.875
      hc    mAP50=0.9052  mAP50-95=0.8386  recall=0.875
      legacy 见 gen_*/train_eval.json
```

即：**断网、没有现场、没有 CUDA（CPU 训练）也能出完整一代**（造数据→训练→三把尺子评测→台账）。

第二轮实测（`--rounds 1 --n 16 --clutter 6 --epochs 1`，18 秒出结果）：

```
[20:04:27] ① 造数据 clutter=6 n=16 seed=70137
[20:04:28] ②③ 训练 1 epoch + 固定留出集评测
[20:04:45] ⏸ 不晋级: hard50-95 0.7004 vs prev None (improved=True no_regress=False)
台账: 代数=1 采纳=0 best=None
```

**判据真的在判**：`improved=True` 但 `no_regress=False` —— 1 epoch 的模型 hard recall 只有 0.875，低于 0.90 红线，所以拒。同一把尺子在 15 epoch（n=200）那轮给的是 `verdict="promote"`（hard50-95 0.8348 / recall 达标）。两轮方向相反 ⇒ 尺子有分辨力，不是恒真恒假。

### 三个坑（都踩过）

1. **`--free-gpu` 默认是 1**：会让 evolve 去停 `zmax-ss-canvas-loop` 和 `sam3_seg` 腾显存。离线跑用 CPU 根本不需要，还会把现场在跑的服务踢掉 ⇒ `offline_evolve.sh` 默认补 `--free-gpu 0`。
2. **heredoc 里写 `\$ARGS` 参数会丢**（内层拿到空串，悄悄退回默认 n=200/clutter=4/epochs=15，白跑 12 分钟才发现）。写内层脚本时引号要分清。
3. **离线时飞书推送必然失败**（`URLError: Temporary failure in name resolution`），日志里 `飞书 rc=1` 属正常，台账/报告照写，不算失败。

---

## 三、边界（必须知道）

| 边界 | 现状 | 影响 |
|---|---|---|
| 现场真帧**没进判据** | 快照里有 24 张真机帧 + 当时 `/boxes`，但 `/boxes` 是 AR 叠加标注（轨迹/槽位），不是 YOLO 类别框 | 真帧只能做"域检查"（亮度/尺寸/清晰度），不能当 mAP 尺子；要当尺子得人工标或伪标签（必须标 `_weak_label`） |
| 550C 与 4060 代码**已分叉** | 550C 在役树 `~/zmax_map` 是旧布局（节点在 `engineering/nodes/library.py`，无 `quat_truth.py`） | 状态空间四层结构/权重/参考姿态**没同步过去**，硬塞会 import 断；需要单独一轮旧树回移 |
| AOI 离线开发 | 已有 `zmax_data/aoi_offline/` + `tools/aoi/offline_manifest.py` | AOI 侧离线开发独立于本手册 |
| 位姿真值来源 | `zmax_data/ss_live/quat_truth_latest.json` + 8791 `/pose` | `~/zmax_data/tcp_out/latest.json` 不存在，别等它 |

---

## 四、断网后先跑什么

```bash
# 1) 确认快照在
ls ~/zmax_data/site_snapshot/*/manifest.json

# 2) 体检: 快照完整性 (缺项会明确写"未采集", 不会编数)
python -c "import json,glob;d=json.load(open(sorted(glob.glob('$HOME/zmax_data/site_snapshot/*/manifest.json'))[-1]));print(d['summary'])"

# 3) 跑一代离线进化
bash tools/offline_evolve.sh --rounds 1 --n 24 --clutter 6 --epochs 1 --fullflow 0
```
