# 进化环设计：让「训练→评估→择优」真的在搜索

适用：任何「每代从 best 权重微调 → 固定验证集评估 → 有提升才采纳」的自进化守护
（intel `zmax_evolve_intel.py` 是第一个实例，但规则与机器无关）。

## 1. 先诊断：环是不是在真搜索

| 现象 | 根因 | 动作 |
|---|---|---|
| 连续多代 mAP50 到 15 位小数全同 | 训练确定性 + 零变异：每代把同一件事重算一遍 | 加变异表 + 换 seed |
| 连续十几代 rejected、值几乎不动 | 同上（看起来像「数据到顶」） | 同上，别只加 epoch |
| 某一代起整体掉一大截（如 -8 点） | 配置被改小（`epochs=1`）或 lr 过大 | 回到能采的上一版配置，按下面 3 条钉死超参 |
| 台账里 lr 档位从不生效 | `optimizer=auto` 静默忽略 `lr0` | 显式 `optimizer="AdamW"` |
| `phase:error` + traceback 有内容 + `alive:true` | XPU 偶发 device lost，不是服务死 | 同代重试 |

台账是唯一证据源：没有 `mutation` 字段的台账，从结构上就无法证明「在搜索」。

## 2. 变异表（按短板选方向）

先看指标短板再定变异方向：precision 已 0.99、recall 0.58 ⇒ 往「更刁的样本」走，
不要去动置信度/阈值（那是推理期参数，不是能力）。

```python
MUTATIONS = [                      # (名字, 训练参数覆盖, 采样权重)
    ("base",      {},                                                  1),
    ("lr_mid",    {"lr0": 0.0040, "cos_lr": True},                     3),
    ("lr_low",    {"lr0": 0.0008, "cos_lr": True},                     2),
    ("aug_scale", {"scale": 0.80, "translate": 0.15},                  3),
    ("aug_rot",   {"degrees": 12.0, "scale": 0.50, "translate": 0.10}, 3),
    ("mosaic_hi", {"mosaic": 1.0, "close_mosaic": 0},                  2),
    ("hsv_hi",    {"hsv_h": 0.02, "hsv_s": 0.70, "hsv_v": 0.50, "scale": 0.60}, 2),
    ("nofmix",    {"mosaic": 0.0, "mixup": 0.0, "scale": 0.9, "translate": 0.10}, 2),
    ("freeze10",  {"freeze": 10, "lr0": 0.0020},                       2),
]
WIDE = {"aug_scale", "aug_rot", "hsv_hi", "mosaic_hi"}   # 平台期只在「大变异」里挑
```

采样器（确定性：同代可复现，不同代必不同）：

```python
def _sample_config(gen, streak):
    rng = random.Random(7919 * (gen + 1))
    pool = MUTATIONS if streak < 3 else [m for m in MUTATIONS if m[0] in WIDE]
    pick = rng.choices(pool, weights=[m[2] for m in pool], k=1)[0]
    kwargs = dict(pick[1])
    kwargs.setdefault("optimizer", "AdamW")   # auto 会忽略 lr0
    kwargs.setdefault("lr0", 0.002)           # 从 best.pt 微调，0.01 会打散能力
    kwargs.setdefault("warmup_epochs", 0.5)   # 默认 3.0 在 3~4 epoch 里吃掉整程
    kwargs["seed"] = 1000 + gen               # 断掉同一条轨迹
    kwargs["cos_lr"] = True
    return {"mutation": pick[0], "epochs": _epochs_for(streak), "kwargs": kwargs}
```

## 3. 算力阶梯（平台期加算力，而不是再换一组增广）

`streak` = 连续未采纳代数。**小步微调连续 3 代不涨点，就已经证明这条路走完了。**

| streak | epochs | 单代时长（18900 张, 640px, B390 iGPU） |
|---|---|---|
| 0–2 | 3 | ≈ 1 小时 |
| 3–5 | 4 + 只挑 WIDE 变异 | ≈ 1.3 小时 |
| 6–8 | 12 | ≈ 4 小时 |
| ≥ 9 | 20 | ≈ 7 小时 |

## 4. 台账必须有的字段

`generation / at / started_from / epochs / mutation / mutation_kwargs / escalated /
seconds / train_map50 / val{map50,map50_95,precision,recall} / best_map50_before /
accepted / reason / weights_kept / dataset{train_images,val_images,cache_bytes}`

`dataset` 指纹是分界点：指纹变了说明数据换过，那前后的代不可直接比。

## 5. 运维两条

**换代码不要打断正在跑的这一代。** 后台哨兵轮询 `/health`，等 `phase` 变 `cooldown`
再 `install` + `systemctl restart`：

```bash
for i in $(seq 1 480); do
  ph=$(curl -s --max-time 5 http://127.0.0.1:8810/health | python3 -c 'import json,sys;print(json.load(sys.stdin).get("phase",""))')
  case "$ph" in cooldown*) install -m 644 /tmp/new.py $DST; sudo systemctl restart $SVC; exit 0;; esac
  sleep 30
done
```

**看进度读 CSV，别 grep 日志。**

```bash
python3 -c "import csv;p='/home/intel/evolve/runs/gen022/results.csv';
for r in csv.DictReader(open(p)): print(r['epoch'], round(float(r['metrics/mAP50(B)']),4), round(float(r['metrics/recall(B)']),3))"
```

ultralytics 的进度行带 `\r`、每步一行，`grep -o "...it/s..."` 一次能吐十几万字符。

## 6. 采纳之后才是闭环

采纳只写 `best.pt` + `models/genNNN.pt` 的话，改进对线上是**空的**。
落地链路：`best.pt` → ONNX → OpenVINO IR（`ov.convert_model`，参考
`tools/edge/sam3_onnx_to_ir.py`）→ 替换在役 `ir/*.xml(.bin)` → `systemctl restart <edge svc>`
→ `/models` 核对 sha16 + 打一张真图验证。换在役模型前先确认这是「有提升」且同口径验证过。
