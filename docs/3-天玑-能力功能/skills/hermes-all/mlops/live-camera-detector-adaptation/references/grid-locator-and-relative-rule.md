# 排状目标（N 个等距单元）的确定性定位与逐单元判据

适用：狭窄条带上一排等距单元（金手指、齿排、引脚排），**没有良品基准**、在役权重也废了，
但用户要「有检测输出」（框 + 判定）。这里是不依赖训练的完整做法。

## 1. 定位：自相关求周期 → 傅里叶相位定起点 → 纯等间距铺 N 格

```python
def locate_grid(bgr, info, n=19, region_fn=None):
    """bgr=原图(未拉伸); info 来自模板法裁剪函数; region_fn(bgr,info)->{"region":{"bbox":[x0,y0,w,h]}}"""
    bb = region_fn(bgr, info)["region"]["bbox"]
    x0, y0, bw, bh = [int(v) for v in bb[:4]]
    x0, y0 = max(0, x0), max(0, y0)
    bw = min(bw, bgr.shape[1] - x0)
    bh = min(bh, bgr.shape[0] - y0)

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    col = gray[y0:y0 + bh, x0:x0 + bw].mean(axis=0)      # 列亮度剖面
    c = col - float(col.mean())

    # ① 周期：整段自相关，暗单元不影响
    ac = np.correlate(c, c, "full")[len(c) - 1:]
    lo, hi = max(3, int(bw / (n + 6))), max(5, int(bw / (n - 6)))
    per = float(lo + int(np.argmax(ac[lo:hi])))

    # ② 起点：全段加权相位，单根暗不拉偏
    xs = np.arange(len(col))
    ph = (c * np.exp(-2j * np.pi * xs / per)).sum()
    start = float((-np.angle(ph) % (2 * np.pi)) * per / (2 * np.pi))

    # ③ 边界余量：否则后几格越界 → Sobel 抛 !_src.empty()
    while start + (n - 1) * per + 0.34 * per > bw and start > 0:
        start -= 1.0

    half = per * 0.34
    boxes = [[int(round(start + i * per - half)) + x0, y0,
              int(round(start + i * per + half)) + x0, y0 + bh] for i in range(n)]
    return boxes, {"pitch": round(per, 1), "start": round(start, 1), "n": n}
```

### 为什么不能逐格微调

| 做法 | 同一批帧的间距 |
|---|---|
| 逐格在 ±per/4 内找局部峰 | **27~61px**（氧化最暗那格把峰拉到邻格） |
| 纯等间距不微调 | **45.0~45.0**（原图尺 71~71）恒定，N 恒定 |

### 左右界用纹理，不用亮度

| 区 | V / 中位 | G（梯度） |
|---|---|---|
| 空白/背景 | **1.85×**（更亮） | **≈0.01**（平坦） |
| 真单元 | 1.0× | 1.0× |

按亮度找起点会多出 4 个"空单元"。用 `np.abs(np.diff(gray, axis=0)).mean(axis=0)` 的能量 1%/99% 分位定界。

### 不要在拉伸过的规整图上定位

规整图是窄条带单向拉伸（110 行 → 330 行）的产物，纹理周期不固定：
period 在 **29.1 / 31.7** 之间跳；若搜索区间放宽还会给出 **52.7**（19×52.7 > 图宽 ⇒ 越界）。
定位一律在**原图裁出的未拉伸条带**上做。

## 2. 逐单元判据（相对中位数）

```
DARK    V    < 0.80 × median(V)     变暗（氧化）
DECOLOR S    < 0.70 × median(S)     失去金色
SMOOTH  grad < 0.65 × median(grad)  纹理丢失（划伤/磨损）
COUNT   n != N                      漏格/断裂
```

`V` = 灰度均值；`S` = HSV 饱和度均值；`grad` = Sobel 幅值均值。

实测：氧化最重的两根在**每个曝光档**下都被稳定抓出（`bad` 恒含 1 和末位，相邻格偶尔带上）。
「DARK + SMOOTH 同时出现」对应"氧化 + 划伤"，而只 DARK 对应"纯氧化"——把 flags 原样带出去，别压成布尔。

## 3. 成像诊断（判"失色"之前先量这三个数）

| 量 | 正常镀金参考 | 异常时的含义 |
|---|---|---|
| ROI 内 S | **≥100** | S 12~28 + V 227~250 = 打白过曝；S 43~55 = 真的失去金色 |
| hue (OpenCV) | **20~30 金黄** | hue 80~90 = 偏绿 ⇒ 白平衡/光源问题，不是氧化 |
| V≥250 占比 | 越低越好 | 17.9% = 严重过曝，单元细节被冲掉 |

曝光扫描实测（同一工件同一姿态）：

| 曝光/增益 | 过曝占比 | ROI 内 S | hue | 结果 |
|---|---|---|---|---|
| 8000us / 2.0 | 17.9% | 20 | 23 | 金属打白，无彩色 |
| 4000us | 3.2% | 31 | 80 | 偏绿 |
| 2000us | 1.6% | 28 | 90 | 绿 |
| 1000us | 0.0% | 26 | 42 | 亮区只剩 3.5% |
| **700us / 16.38dB** | 8.0% | 55 | 35 | 采用 |

关键推论：降曝光后 S 只从 43 涨到 55（远达不到 100）⇒ **失色是零件表面状态，不是曝光**；
过曝只是叠加在其上。这是把"曝光害的"与"零件真氧化"分开的判据。

## 4. 要重训时：数据集构建入口

- 裁剪函数返回 `(reg_img, info)`；region 几何在 `info["strip"]`，取 bbox 走 `_region_payload(bgr, info)`。
  **不要猜内部函数名** —— 先 grep 调用点，猜错会静默返回 `None` 导致“生成 0 张”而看不到任何报错。
- 条带裁出来后按上面的规则自动打标（缺陷类 = bad，正常类 = ok），生成 `train.txt` / `val.txt` 切分。
  🔴 这是**自蒸馏**：指标只能证明"和规则打得像"，不能证明泛化（见 SKILL.md §1）。
- 数据多样性先量：同一工件连拍上百帧的 md5 全唯一、相邻帧差也超标，但**与首帧相关系数 0.999** ⇒ 仍是同一张图。
  整批同一件时，交"标注/训练管道已就位 + 明确的采件需求单"，不要把增强凑数当数据集。
- 废帧要先滤：全黑（`std < 8`）/ 全白（`mean ≈ 255`）在历史目录里很常见，混进去会让统计全失效。

## 5. 输出契约

```json
{
  "ok": true, "n": 19, "expect": 19, "pitch": 71.0,
  "median": {"V": 132.0, "S": 52.4, "grad": 92.5},
  "bad": [1, 2, 19],
  "fingers": [{"k": 1, "box": [x0,y0,x1,y1], "V": 69.2, "S": 62.3, "grad": 67.6, "flag": ["DARK","SMOOTH"]}],
  "verdict": "NG", "why": "异常根 1,2,19"
}
```

总判决与模型口径取并集，但**分字段上报**（`verdict_rule` / `verdict_model`），页面上标明谁判的。
验收：连跑两次逐字一致。
