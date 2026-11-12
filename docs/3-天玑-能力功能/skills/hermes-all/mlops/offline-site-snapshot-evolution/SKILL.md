---
name: offline-site-snapshot-evolution
description: Use when 断网前要记住现场并保证离线自主进化。
---

# 离线自主进化: 先把现场抄下来, 再断网跑

## 何时用

- 用户说「现场数据你要记住」「一会离线, 也要能自主进化」「包括位姿/工控机程序/相机/Orin 驱动」
- 离场/断网前 10 分钟的例行动作
- 需要证明「进化不依赖现场任何服务、不依赖外网」

## 四步

```bash
# 1) 数据面 (1.5MB, 90s 内可完成)
python tools/site_snapshot.py --seconds 90 --frames 6 --gap 3
#   → zmax_data/site_snapshot/<ts>/{pose 893拍 @10Hz, frames 24张, labels 同刻, ar, cfg 15个, code 指纹, orin, manifest.json}

# 2) 程序面 (三机服务/端口/ExecStart/隧道/代码版本 + Orin ROS 话题类型与节点)
python tools/site_inventory.py --out zmax_data/site_snapshot/<ts>

# 3) 冗余: 快照抄一份到 550C
rsync -a --relative zmax_data/site_snapshot/<ts> intel:~/zmax_map/

# 4) 断网跑一代 (真离线 + 独立台账 + 默认 CPU)
bash tools/offline_evolve.sh --rounds 1 --n 16 --clutter 6 --epochs 1 --fullflow 0   # 冒烟 ~18s
bash tools/offline_evolve.sh --rounds 4 --n 400 --clutter 6 --epochs 30              # 正式
```

手册: `docs/OFFLINE_EVOLUTION.md`。

## 验收口径 (实测值 2026-11-12)

| 项 | 实测 |
|---|---|
| 离线自证 | `unshare -n` 里只有 `lo` DOWN，`curl 1.1.1.1` 失败，否则脚本 exit 8 |
| 造数据 | 24 张 clutter16 留出集 1.7s（mujoco，本地） |
| 训练 | CPU 1 epoch 12s（ZMAX_TRAIN_DEVICE=cpu）；GPU 15 epoch 约 12min |
| 评测 | hard mAP50-95 0.7004 / hc 0.8386（1ep）；15ep 那轮 hard 0.8348 → verdict=promote |
| 判据有分辨力 | 1ep: `improved=True no_regress=False`(recall 0.875<0.90) 拒；15ep: promote |
| 现场快照 | 893 拍位姿 + 24 帧 + 46 个 Orin 话题 + 三机 40/40/8 服务 |

## 坑（都亲自踩过）

1. **`--free-gpu` 默认 1** —— evolve 会去 `systemctl stop zmax-ss-canvas-loop` + `kill sam3_seg` 腾显存，把现场在跑的服务踢掉。离线跑必须 `--free-gpu 0`（runner 已默认补）。踢了它会自己起回，但别指望。
2. **heredoc 里 `\$ARGS` 会丢参数** —— 内层拿到空串，静默退回默认 `n=200/clutter=4/epochs=15`，白跑 12 分钟。内层脚本里参数不要转义。
3. **AOI 10082/10083 在本机只是 ssh 隧道**（`-L 127.0.0.1:10082:192.168.23.23:10082`）。端口在听 ≠ 服务在跑；连上立即 reset 就是目标机不可达。
4. **Orin 的 `orin` 别名走 wifi**（192.168.43.19，断网即死）；产线口是 `orin-lan`（192.168.23.66）。快照/清单器都优先 `orin-lan`。
5. **离线跑飞书必失败**（`URLError: Temporary failure in name resolution`），`飞书 rc=1` 属正常，台账/报告照写。
6. **两台树已分叉**：550C 在役树是 `~/zmax_map`（旧布局，节点在 `engineering/nodes/library.py`，无 `quat_truth.py`），不能直接覆盖 4060 的 `middleware/nodes/impl/`；同步前 `systemctl cat <unit> | grep ExecStart` 确认路径。
7. **现场真帧不能当 mAP 尺子**：`/boxes` 是 AR 叠加标注（轨迹/槽位，坐标含负），不是类别框。真帧只能做域检查；要当尺子须人工标或伪标签（标 `_weak_label`）。

## 不许做的

- 缺项不许编数：快照器对不可达源写 `ok=false + reason`，manifest 里看得到。
- 不许把离线沙箱写进现场台账：`ZMAX_OFFLINE_ROOT` 默认 `/tmp/evo_offline`，现场 `zmax_data/ar_evolve/ledger.json` 不动。
- 不许为了「离线也全绿」把判据放宽：主判据仍是 hard 留出集 mAP50-95 + hard recall ≥ 0.90 红线。
