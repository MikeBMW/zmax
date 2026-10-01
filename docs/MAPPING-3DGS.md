# 自动建图 (3DGS) — 完整链路与命令

> 目标(老倪 2026-10-01): **L5 看画面 → 给出环境理解 → 指导 3DGS 建图; 一边移动机器人, 一边自己学环境, 一边建立场景视图。**
> 交付物: 场景资产 `gs.ply` / `gs.splat` + 网页查看器 + 一份**可判定**的质量报告(过了门才算成果)。

## 一、链路(每一环都是既有真链路, 不新开通道)

```
选点  tools/gs_l5_select.py   L5(DeepSeek 视觉)看当前画面 → 环境理解 + 下一步方向
                              ↓ 软件把「画面方向」翻成 base 系方向, 在**已示教可达点**里
                                挑最贴合该方向、且最没拍过的点(打分与理由进日志/状态)
移动  POST 127.0.0.1:8793/ctl/move {skill:"L2.goto_spaceN"}   与页面按钮**同一条**授权+收口+安全链
      到位判据 = TCP 真值 <3mm 且连续 1s 稳定(不靠超时猜)
采集  tools/gs_capture.py     臂上 D405 原始 JPEG + TCP 真值位姿逐帧配对(只读)
                              **内容没变不落盘**(md5 判)
建库  tools/gs_dataset.py     按图像内容 md5 去重 + 位姿取该图**首现时刻**(+取图延迟补偿)
训练  tools/run_gs_train.sh   CUDA shim 环境 + gsplat 官方配方(30k 步 / 40% 停致密化)
质检  tools/gs_quality.py     数据集健康 + 与「平凡基线」比; **不过门就停, 不把废资产当成果**
状态  ~/zmax_data/gs_map/status.json  页面 /ctl/gs_map 轮询; 结束附判定与资产路径
```

一键闭环: `tools/gs_map_run.py`(见下)

## 二、命令

```bash
# 1) 全自动闭环(L5 指导选点 + 移动 + 采集 + 建图 + 质检)
~/gs-venv/bin/python tools/gs_map_run.py --rounds 7 --targets l5 --dwell 8 --steps 30000
#    不移动的链路验证(不碰臂)          --dry-run
#    用已有录像重跑 建库→质检(→训练)    --from-recording ~/zmax_data/gs_scan/scan_20261001_064113
#    兼容旧行为(固定 space1..7 顺序)     --targets spaces --order fixed|novelty

# 2) 单步
~/gs-venv/bin/python tools/gs_l5_select.py --session <会话>   --k 3   # 只出选点建议(+JSON)
~/gs-venv/bin/python tools/gs_capture.py   --out <会话> --secs 30
~/gs-venv/bin/python tools/gs_dataset.py   --session <会话> --out <数据集> [--max-frames 400]
bash tools/run_gs_train.sh --data <数据集> --out <模型> --steps 30000 --refine-stop 12000
~/gs-venv/bin/python tools/gs_quality.py   --session <会话> --dataset <数据集> --model <模型>

# 3) 停训练(必须独立脚本, 内联 pkill 会把自己 shell 一起杀掉)
bash tools/stop_gs_train.sh
```

## 三、L5 指导选点的接口契约

`gs_l5_select.py` 输出 JSON(页面/下游只读字段, 只增不改):

| 字段 | 含义 |
|---|---|
| `l5_used` / `l5_err` | L5 是否真用上; 失败原因**如实写**(不假装) |
| `l5_scene` | 一句话场景理解 |
| `l5_regions[]` | `{name, seen: good\|partial\|bad, why}` |
| `l5_missing[]` | 看不全/可能没拍过的区域(决定下一步去哪儿) |
| `candidates[]` | `{pos:[x,y,z], dir, dist_mm, why, source, score, reachable}` — `source=l5` 或 `coverage` |
| `visited_regions` | 覆盖度统计(位姿 bbox / 不同视点数) |

**「画面方向」怎么变成可执行动作**(关键工程约束):
L5 只给**画面语义方向**(画面左/右/上/下/靠近/远离 + 距离 mm)。软件按手眼把
`R_base_cam` 乘上相机系单位向量, 得到 base 系方向; 再在该方向上挑**已示教可达点**
(`data/skills/l2_atomic/space_points.json` + `ctl_abs_skills.json` 白名单)里
`align≥0.30` 且最没拍过的那个点。理由: 目前运动白名单只有示教点类技能
(`L2.goto_spaceN` 等), **没有任意笛卡尔运动原语** —— L5 想去的任意位姿暂时无法直接执行,
所以设计成"L5 出意图 → 软件在可达域内选点"。等开了任意笛卡尔/增量点动, 把
`pick_by_direction()` 的候选目录换成笛卡尔候选即可, 上层契约不变。

L5 不可用(超时/解析失败)时: 自动退**覆盖度兜底**(选离已访问视点最远的可达点), 并在
`l5_err` 里写明原因 —— 链路不因 L5 挂掉而中断, 也不假装是 L5 选的。

## 四、质量门(判据先定后跑, 不假装成功)

三处门, 任一 FAIL 即停:

1. **采集会话门** `session_checks`: 同一画面(md5)若被存成多个文件且位姿不一致 ⇒ FAIL。
   > 这就是 2026-10-01 那次扫场的坑: 取图端点按 8Hz 取, 但相机有效出帧率低得多 ⇒
   > 118,586 次取图只对应 5,830 张唯一画面(77.7% 重复), 每次取图还各记一个**不同** TCP 位姿
   > ⇒ 数据集里"同图配多位姿" = **矛盾监督** ⇒ 训练视角都拟合不上(训练视角 PSNR 16.5dB、
   > 留出 11~13dB, **低于"填常数"平凡基线 11.8~12.3dB**)。采集器已加"内容没变不落盘"。
2. **数据集门** `dataset_checks`: 唯一图占比 >90%、真正不同视点 ≥50、相机位姿跨度 ≥150mm、
   同一位姿不同时刻画面差异中位 <8/255(≥5 对样本才判)、无黑帧/无纹理帧。
3. **模型门** `model_checks`:
   - `beats_trivial`: 留出视角 PSNR 必须 **> 平凡基线 +3dB**(平凡基线 = 用该图均值填满的 PSNR); 不用绝对阈值。
   - `fits_training_views`: 训练视角 PSNR > 平凡基线 +5dB(连训练视角都拟合不上 ⇒ 数据自相矛盾)。
   - `has_structure`: 渲染图唯一色 >100(纯色=没建出东西)。
   - 报告里同时给出 `n_gaussians`、`psnr_train_db`、`psnr_holdout_db`、平凡基线, 便于横向比。

## 五、踩过的坑(必须保留在调用方认知里)

| 坑 | 症状 | 正解 |
|---|---|---|
| 渲染把 **log 域尺度**当线性尺度喂 `gsplat.rasterization` | 整帧单一纯色(唯一色=1)、参数冻死、`0 split/0 duplicate`、PSNR 12.9 平在平凡基线附近 | 渲染前 `torch.exp(params["scales"])`; 导出 `.ply/.splat` 才存 log/logit 域 |
| 位置学习率**不衰减** | 后期 loss 回升(0.16→0.29)、高斯爆到 140 万、留出 PSNR 回落 | 按官方配方指数衰减到 1e-6; 致密化 40% 步数停 |
| 采集**每取必存** + 每次记位姿 | 77.7% 重复帧, 同图配多位姿 = 矛盾监督 | 采集端按内容 md5 去重; 建库端再兜一层; 位姿取该图首现时刻 |
| 直接跑 `gs_train.py` | `AttributeError: 'NoneType' object has no attribute 'CameraModelType'` | gsplat CUDA 扩展 JIT 编不过被吞 ⇒ 必须走 `tools/run_gs_train.sh`(CUDA shim) |
| 内联 `pkill -f "gs_train.py …"` | 把自己的 shell 一起杀掉 | 用 `tools/stop_gs_train.sh`(先取 pid 再排除自身) |
| 机械臂**蹲点不动**扫场 | 4.1h 采到 5,830 张唯一画面但**真正不同视点只有 ~170~530 个**、视差不足 | 闭环要求"每点移动 + 每点采集", 质检看真正不同视点数 |

## 六、未完成 / 下一步

1. **任意笛卡尔运动原语**: L5 现在只能在示教点里选点。开了笛卡尔点动(或示教点自动扩展)
   才能真正"L5 想去哪就去哪"。
2. **增量建图**: 目前每轮结束是一次性批训练; 需求是"边移动边建"。可行路径: 每轮把新增帧
   并入数据集做**增量/继续训练**(gsplat 支持从已有 `.ply` 初始化), 并周期性出中间资产。
3. **位姿自检**: 大跨度扫描里若有少量帧位姿错(与光轴一致性、Sampson 误差可检), 应在建库前
   剔除或用 SfM 重新求解 —— 当前只有"同画面对比"这一层弱校验。
4. 真机跑闭环前: 先 `--dry-run` 验证链路, 再确认 8793 `motion_armed` 授权; **未授权绝不发动作**。
