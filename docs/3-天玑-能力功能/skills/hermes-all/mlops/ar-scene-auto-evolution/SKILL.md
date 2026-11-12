---
name: ar-scene-auto-evolution
description: Use when AR 场景自造数据自进化检测器, 或进化无提升/OOM/黑帧。
version: 1.0.0
author: Hermes
license: proprietary
metadata:
  hermes:
    tags: [zmax, evolution, ar, yolo, mujoco, closed-loop]
    related_skills: [zmax-fullflow-7task-loop, zmax-multilayer-pipeline, gpu-training-load-guard]
---

# AR 场景自主进化 (自造数据 → 训练 → 同源评测 → 择优晋级)

## When to Use
- 「结合 AR 场景, 自动生成数据, 自己进化」/ 要检测器持续自我提升
- 自进化跑了一堆代却「没有提升」/ 每代 mAP 一模一样
- 训练 OOM 但 nvidia-smi 显示都是别人的进程

## 唯一入口
```bash
cd ~/zmax && gui-venv311/bin/python tools/evolve_ar_world.py \
  --rounds 0 --n 200 --clutter 4 --epochs 20 --cooldown 1800    # rounds=0 ⇒ 无限
```
常驻: `zmax-evolve-ar.service` (550A, enabled, 日志 `/var/log/zmax-evolve-ar.log`)
产物: `zmax_data/ar_evolve/{ledger.json,best.pt,weights/,gen_NN_*}` + `reports/evolution_ar/<ts>/`

每代 4 段真跑:
1. `tools/ar_mujoco_clutter.py --gen` → MuJoCo AR 工位渲染 + **干扰件**(非金色模块), 标签=金色像素主连通域
2. `tools/ar_yolo_train_eval.py` → 训练 + **同一权重**跑三个固定留出集 (hard=holdout_hard/clutter16, hc=holdout_clutter, legacy=干净)
3. 门禁: 主判据 **hard.map50_95 ≥ best + margin**, 且 hc/legacy 的 map50 与 map50-95 均不回退(超 `--no-regress-tol`)、hc recall≥0.98 ⇒ 才换 `best.pt` / `models/yolo_ar_evolve.pt`
4. 台账 `ledger.json` 追加 (可回滚), `REPORT.md` → 飞书 (intel 侧 bot)

## 关键口径 (决定有没有真进化)
- 🔴 **训练造数参数必须与留出集一致 —— 这一条比"加数据"值钱得多 (2026-11-07 实测)**:
  `holdout_clutter` 是 `clutter=6 / n=240 / seed=31337` 生成的，而常驻服务默认 `--clutter 4` ⇒ **训练分布 ≠ 评测分布** ⇒
  gen 10→125 连续 115 代全部"保持"(hc mAP50 在 0.8775~0.9915 之间摆，永远够不到 best+0.004)。
  对照实验: 只把数据加到 **800 张 / 40 epoch** 反而掉到 **0.8596**("保持")⇒ 瓶颈不是数据量。
  把 `--clutter` 改成 6 对齐后 **第一代就晋级**: hc mAP50 **0.9891→0.9950**、precision **0.9322→0.9998**、legacy 0.9950 不回退，
  下一代复现 0.9950/0.9998(非偶然)。⇒ 先 `cat <holdout>/meta.json` 看 `stats.clutter`/`n`/`seed`，再定训练参数。
- **干净场景已饱和**: 在役 `yolo_ar_peg.pt` 在原留出集 mAP50=0.995、外观退化难档(`ar_hard_holdout.py`)也是 0.995 ⇒ 那里「有提升」数学上不可达。
  有真实空间的是**带干扰件**留出集: 在役只到 mAP50 0.908 / precision **0.595**(误检多), 训一代即 0.982 / 0.886。汇报必须说清口径。
- `data.yaml` 的 `val:` **只能写目录**(`<holdout>/images`) 或相对路径; 写 `xxx/data.yaml` 会报
  `Error loading data from ...data.yaml` 且训练 rc≠0。
- 训练内 `val=False`, 数字统一由固定留出集给 ⇒ 训练集与评测集不相交, 代际可比。
- 门禁两把尺: 提升尺(hc) + 回退尺(legacy)。只报 mAP50 会掩盖 mAP50-95 轻微下滑, 报告两个都列。
- margin 0.004 下会出现「0.9855 vs 0.9823 差 0.0008 不晋级」——这是闸在工作, 不是失败; 别放水。

## 门禁空转: mAP50 封顶 0.995 (2026-11-12 实测, 530 代白跑)
- 症状: 日志连续 `⏸ 不晋级: hc 0.9950 vs prev 0.995 (improved=False)`, 台账 `best.gen` 几天不涨。
- 根因: ultralytics 的 mAP50 上限就是 **0.995**; best 一旦到 0.995, 门禁 `hc.map50 >= prev + margin(0.004)` **数学上永不成立**
  ⇒ gen_128~657 连续 530 代零晋级, 每代仍照样造数据+训练 4 分钟 (纯烧卡)。
- 判据: `ledger.best.hc_map50 == 0.995` **且** 近 N 代 `improved=False` 全为同一值 ⇒ 不是模型不行, 是尺子封顶。
- 修: 主判据换 **mAP50-95**(带上限 1.0, 近 100 代 std≈0.006 有分辨力), map50/recall/legacy 只做「不回退」兜底;
  换尺子必须先量现任 `best.pt` 在新尺子上的分写进 `ledger.best`(否则第一代等于无条件晋级) ——
  `tools/seed_hard_baseline.py`(CPU 评测, 不抢显存)。
- ⚠️ 但换尺子≠有提升: clutter 6→16 只把 hard mAP50-95 从 0.9224 降到 **0.9181** ⇒ 加干扰件几乎不降分,
  因为合成任务本身可分离(标签=金色像素连通域, 干扰件为非金色)。**这类饱和只能靠换数据**(真机图/遮挡/小目标/过曝),
  加代数、加干扰件、加数据量都救不回来; 汇报时别把「门禁修好」说成「进化有提升」。

## 训练卡死在内核态 (CUDA kernel hang)
- 症状: 某代 `results.csv` 停在 epoch k 十几分钟不动, GPU util 4~6%, 进程 state=R 还吃 30% CPU, 12 个 dataloader worker 全 idle。
- 确诊: `py-spy dump` 只给到 `_do_train (trainer.py:566)`(那行是 `pbar.set_description` 里的 `_get_memory()`), 看不出真因;
  用 **`sudo gdb -p <pid> -batch -ex "thread 1" -ex "bt 25"`** 看到 `cuStreamSynchronize` + `_local_scalar_dense`(即 `.item()`) ⇒
  loss 的 `.item()` 在等一个永不返回的 kernel。
- 处置: 杀训练进程树(父驱动 `evolve_ar_world.py` 会记 `ok:false` 继续下一轮), 显存立刻回收;
  冒烟 `torch.randn(2000,2000,device='cuda')@a` 0.2s 回来自证 GPU 没坏。别急着重启服务。
- 🔴 `subprocess.run(timeout=)` 超时抛 **TimeoutExpired 未捕获 ⇒ 整条进化服务挂掉**, 不只是这一代。
  `sh()` 必须 try/except 返回 `rc=124`, 并把训练 timeout 从 7200s 收到 **900s**(正常 260s)。

## 显存: 8GB 卡的硬账
常驻占位 (实测): 引擎 1.8G + 画布回路 **2.2G** + INTACT worker 1.3G + 小服务 ⇒ 训练必 OOM (free 剩 17MB)。
处置: 训练前 `sudo -n systemctl stop zmax-ss-canvas-loop.service` + 停 `sam3_seg.py --serve`(懒服务),
训完起回。服务态里 `systemctl` 要交互认证 ⇒ **必须 `sudo -n`**(本机免密), 失败要吵出来。
只动「自身只读回路」; 执行腿/授权链/位姿中继一根都不许碰。

## 渲染黑帧 (MUJOCO_GL)
症状: `ar_scene_render_server` 起得来但 `/frame.png` 503, `/state.json` 写
`构造失败: FatalError: gladLoadGL error`。
原因: systemd 服务没有 `XAUTHORITY`(X 由 gdm 起, cookie 在 /run/user/1000/gdm/Xauthority)。
修: drop-in 加 `XAUTHORITY=/run/user/1000/gdm/Xauthority` + `DISPLAY=:0` + `MUJOCO_GL=glfw`。
EGL 在 4060 上反而 `EGLError`; `osmesa`/`glfw` 可用。

## L4 潜表示「假通」的判据
`engine_latest.z_source` 出现 `回退内建 PCA` = 假通 (z_latent 仍在但非 VLM 编码)。
看 `成功 N/失败 M` + `帧龄`: 帧龄 <5s 且成功在涨才算通。
常见根因只有一个: `zmax-fw-render`(8801) **inactive**(unit 是 static 不 enabled) ⇒ 引擎每拍 `URLError: Connection refused`
(实测累计 50215 次、成功 0) ⇒ 回退 PCA。处置: `sudo systemctl start zmax-fw-render` → 8801 `/frame.png` 回 200(190KB)、
帧龄 0.0s、成功计数开始递增、`ss_wiring_audit.py` 里 L4 潜表示由 ❌ 变 ✅(在链 5/7→6/7)。启动后要等 10~20s 才 LISTEN。
`zmax-fw-render.service`(8801, 引擎 `--l4-frame-url`)是 static 未 enabled, 死时 URLError 刷屏;
`systemctl start zmax-fw-render`(同样要 XAUTHORITY drop-in) 即恢复, 不必重启引擎。

## 打通审计
`python tools/ss_wiring_audit.py` → `reports/ss_wiring/<ts>.json|md`
在链 = `zmax_data/ss_live/layer_calls.jsonl` 末行 5 层全 ok + 引擎 z_source 非 PCA + chunk 有块。
`gravity_trace.json` 受任务闸(`TASK_OK="TASK-01-FW"`)限制, 换场景刻意不发 ⇒ 标「—」不算故障。
