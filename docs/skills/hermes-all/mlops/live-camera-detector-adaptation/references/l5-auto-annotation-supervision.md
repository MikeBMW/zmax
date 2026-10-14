# L5 VLM 自动标注 → L2 数据集的失败归因（0 有效框 ≠ 相机故障）

适用：数据不是人工标的，而是编排脚本用本地 VLM 自动标注实拍帧、再喂给 L2 检测器数据集
（本项目 `tools/l5_annotate_train_loop.py`：interact → annotate → supervision → train → merge）。
用户红线：**标注产出 0 框必须判失败并说清原因，不许当成功往下训**。

## 1. 诊断分支只能读「本函数真有的量」
判 0 框原因的代码读了一个**本函数从不设置**的键（`r["summary"]["n_ok"]`）⇒ 恒 0
⇒ 无论真因如何都报「所有相机都没拿到帧（相机离线）」，把现场带偏。
实测反例：同一批 4 路 `ok=True`、4 帧、VLM 正常返回（163s），只是框全不在类别表。

规则：接手一段「报错文案」的归因逻辑时，先确认它读的每个键在**同一函数里真被赋过值**
（`grep -n '<键名>' -B5 -A20 <文件>`，看赋值点是否在同一函数/同一 dict）；
恒假/恒真的条件会把「数据问题」报成「采集故障」，比不报错更坏——它让用户去查错的环节。

## 2. 0 有效框必须分三类报，并把现场数字写进原因
1. **真没帧**：`n_frames == 0` 或各路 `ok` 全 False ⇒ 流没起 / 相机离线。
2. **VLM 没给出目标**：有帧但 `objects` 总数为 0。再分：单片 latency 很大 ⇒ content 为空/超时；
   正常返回但 0 objects ⇒ 图过暗/无目标。
3. **有框但全不在类别表**：VLM 标了 N 个框，无一映射到训练类别。
   本项目 L2 类别表只有 `peg` / `OPT_Gold`，映射表只认「光模块/模块/插芯/光纤…」与「金手指/卡缘/连接器…」；
   实测一批 7 框全跳过（插槽/托盘槽位×4 · 夹爪 · 线缆 · 手），且 VLM 自己的场景描述就写着「未见明显光模块」
   ⇒ 结论 = **画面里没有可训练目标**，不是相机/流的问题。
原因串要带：`N 路 ok · N 帧 · 跳过标签计数（降序取前几） · VLM 场景描述（截断）`，并显式写「不是相机/流的问题」。
→ 判失败仍然要判（不训练），但**必须归到「数据/画面」而不是「采集」**，这样用户改的是相机朝向而不是去重启流。

## 3. `raise SystemExit(main())` 的 rc=1：先看状态、再看阶段
rc=1 只是「某个阶段 `ok=False`」的传声，别在入口 debug：
① state 文件（本项目 `zmax_data/l5_loop/state.json`）→ `status` / `last_result`（阶段 `reason`、`stats`）；
② 本轮日志（`run_*.log`）尾部：阶段成败 + 原因串 + 该阶段 stdout 尾部数行；
③ 再进那个 stage 函数看判据。

## 4. 修完怎么验：用**同一批现场数据**重放那个阶段，不重跑整链
```bash
./gui-venv311/bin/python - <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("l5loop", "tools/l5_annotate_train_loop.py")
m = importlib.util.module_from_spec(spec); sys.modules["l5loop"] = m; spec.loader.exec_module(m)
r = m.stage_supervision({"started": "verify"}, "zmax_data/auto_annotate/batch_<现场批次>")
print(r["ok"], r["zero_box_reason"])
PY
```
秒级、不占 GPU、只重写数据集索引；整链重跑要十几分钟。**验证必须拿现场那批数据**，否则文案对不上现场。

## 5. 让闭环真的跑通：先让画面里有目标
看批目录里**每路**的 json（`cam / ok / n_obj / latency_s / scene`）比看总数有用。实测常见组合：
一路全黑帧（曝光为零）+ 一路拍的是别的房间 + 一路拍的是**空料盘** ⇒ 0 可训练框。
处置：把相机对准工件 / 用 `--cams` 只留有目标的那路 / 用 `--batch-dir` 复用一批有目标的既有批次。
判据：**画面里没有目标时，任何「重训 / 调参」都是白费**。
