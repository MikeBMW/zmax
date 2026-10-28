# MANIFEST · 评估分析页「插拔/摆盘 场景 × Phase 0→4」迭代面板 离屏真渲染截图

* 生成时间: 2026-10-15 22:23 (CST) · 版本 v5.50.735 · 基线 5.50.735
* 唯一依据: `zmax_data/eval/scene_phase_iteration.json` (由 `tools/scene_phase_iteration.py` 生成, 界面只读)
* 控件: `tools/gui/iteration_roadmap_panel.py` → `class ScenePhaseIterationView` (评估分析页内嵌面板第 4 个页签)
* 截图方式: `QT_QPA_PLATFORM=offscreen` 真起控件后 `QWidget.grab()`(真渲染, 非合成), 未缩放
* 说明: `docs/data_snapshots/**/*.png` 按仓库规矩**不入库**(.gitignore), 本文件留名字 + sha256 + 重建命令;
  图片本身留在本机同目录, 可直接看。
* 判据同源: `tools/verify_scene_phase_iteration_panel.py` **41/41 PASS** (本次出图就是它跑的那一遍)

## 重建命令 (一条命令重出全部 11 张 + 逐条判据)

```bash
cd /home/ubuntu/zmax
./gui-venv311/bin/python tools/verify_scene_phase_iteration_panel.py \
      --shot-dir docs/data_snapshots/20261015_scene_phase_iteration_gui
```

## 文件清单 (name · sha256 · bytes)

| # | 文件 | 内容 | sha256 | bytes |
|---|---|---|---|---|
| 00 | 00_评估分析页整页_场景迭代页签.png | 真起 `studio.EvalModule` 整页, 迭代路线图区块第 4 页签选中(证明真内嵌) | b58f954319c01a878857c3e2416955f347dfaf38959c9ce9fc758f9d9767c5fd | 272781 |
| 01 | 01_评估分析页_迭代路线图区块(场景迭代页签).png | 迭代路线图区块(面板级): 场景切换条 + 三子视图页签 | 5c22dc83a0159959fa6d03ef3ea35782838de05a3b836ef4328c2a78b500bfd9 | 266690 |
| 02 | 02_组合迭代_FW_展开.png | 插拔 FW · 组合迭代(展开 carried/added/upgraded 明细) | 0eb5a374f092b6be5c891605f963f4f690751202da7ebde0ea6e28ccab3580fb | 178303 |
| 03 | 03_组合迭代_TRAY.png | 摆盘 TRAY · 组合迭代(切场景后) | d7c643814d2fd71053ae342a54f4219dea862c25073fe39ef48da8e90d4e83bc | 176468 |
| 04 | 04_迭代验证_FW.png | 插拔 FW · ① 配置完备性核验 + ② 实测 vs 目标 | c2e66bd9fa3431b6912b1ad38fd466bf3a3cc406492df19ac07085e3cd24cc1a | 207904 |
| 05 | 05_迭代验证_TRAY.png | 摆盘 TRAY · 同上(两场景读数不同) | 1b294fecedac6928b99b335a4a0d3f6c26af451beb3624d1104ff2a4e58d8bca | 202747 |
| 06 | 06_对比分析_并列FW+TRAY.png | 对比分析 ① 矩阵并列(FW p0..p4 与 TRAY p0..p4) ② 达标率 ③ 组合增量 ④ 与基线 | e83339c8ca3cb8077a10ec0fc92b224a87db9777c5d103c021983e2a9e48ae42 | 142691 |
| 07 | 07_对比分析_只看FW.png | 对比分析 · 视图切「只看 FW」(TRAY 列真隐藏) | 957314f492a81a7bb8d9de48a25df3fe1e5bc78f7f75256ef856d07d4a263c9b | 159601 |
| 08 | 08_唯一依据缺失_尚未生成.png | 唯一依据指到不存在文件 ⇒ 「⛔ 尚未生成」横幅 + 全表 0 行(绝不假 0) | 4fa03f52a920d0f072e65ddc09d8806bf7ca6193a4140d14ab27e22627e16d54 | 149253 |
| 09 | 09_组合迭代_FW_折叠(默认).png | 组合迭代默认折叠态(点该格展开/收起) | 443e9c3c01481e0d090a5a18f8336bab3e623d4ffd1cb413f2caf462353da225 | 150637 |
| 10 | 10_重跑失败_真实退出码3.png | 🔄 重跑失败横幅: **真实退出码 3 + 真 stderr**(`boom: 采集口径不可达`), 不静默 | a1340c41a8eece9f53f3161fd21503e5490d5ea7eea74d8742d4159f2d595da6 | 166367 |

## 出图时的唯一依据读数 (与图上一致, 可回查 json)

* FW 插拔: 58 指标 · 达标 0 · 未达标 1 · 未测 57 · 末阶段 coverage 10/10 · 组合 total 5→8→9→5→10 · vs 基线 提升0/持平2/回退0
* TRAY 摆盘: 58 指标 · 达标 1 · 未达标 4 · 未测 51 · 末阶段 coverage 10/10 · 组合 total 5→8→9→5→10 · vs 基线 提升0/持平8/回退0
* 升级准入三闸: 两场景 5 阶段均 ①✔ ②✘ ③✔ · 未开闸 · 矩阵 58 行

> 注: 2026-10-15 22:21 本目录曾清空重出过一次(旧文件名 `scene_*.png` / `panel_tab3_full.png` 等)。
> 当前目录内只有上表 11 张(命名统一 `NN_内容.png`), 覆盖: 整页内嵌 / 面板级 / 两场景 × 三子视图 /
> 折叠与展开 / 唯一依据缺失 / 重跑失败真实退出码 —— 重建命令同上, 执行一遍即得。
