# 工位页「金手指判据图」那一格 · 取景/放大/提亮/调试

适用: 老倪指着 `http://<host>:8793/station` 的金手指格说「看不到金手指」「太矮小」「宽度太窄」
「是歪斜的」「要按金属手指做成矩形」。这一格 = `8791 /aoi_gold.mjpg` → 页面 `<img id="i_aoi_gold">`。

## 1. 调用链与代码位置 (`tools/cam_live_stream.py`)

```
抓帧   10082 /picture?kind=origin&grab=1
裁带   _gold_natural_bgr()        —— 选条带
提亮   _judge_level()             —— 软件自动色阶(只显示)
拉高   _gold_rectify(stretch=5.0) —— 横向等比 + 纵向倍数
出流   MJPEG /aoi_gold.mjpg → 8793 /station 的 #i_aoi_gold
调试   /gold_debug(页) · /gold_debug/frame.png(整帧+网格+当前框)
```

## 2. 条带选择: 先 `/region`, 再用"根数"验收

- 锚: `GET :10082/region` 的 `region.bbox = [x,y,w,h]`(模板匹配, 带 `angle` 与 `focus`)。
- 闸: 在候选条带上求列剖面自相关
  ```
  pr = band.mean(axis=0) - mean;  ac = 归一化自相关
  lag = argmax over [w/(expect*3.5), w/4];  count = round(w/lag)
  通过条件: |count - expect| 最小, 且 r>=0.55 且 对比度>=15
  ```
- 实测对照(同一帧, 2448×2048):
  | 候选 | lag | count | 结果 |
  |---|---|---|---|
  | `/region` bbox 条带 (y964~1040) | 71px | ≈20 | ✅ 现场就是 19 根 |
  | "自动找周期带"(y1762~1844) | 15px | ≈97 | ❌ 噪声/亮边, 裁出平滑亮块 |
- **别只信 r**: 平滑竖直边缘也能给出 r≈0.97。必须叠加物理数量(19)。

## 3. 放大: 只动纵向 stretch, 不动页面框

- `_gold_rectify(stretch=s)`: `s=1.0` 是严格等比; 内容高度 ≈ `H0 * (Ws/W0) * s`。
  实测同一 28 行条带: s=1 → 914×32, s=5 → 914×104, s=8 → 914×155(多出来的十几 px 是固定留边)。
- 页面侧**禁止**给 img 加 `aspect-ratio`: 格子是 4:3 + `object-fit:contain`, 锁成 `900/1660` 会把宽度压成窄条
  (现场原话"宽度太窄")。要更高就调 `stretch`, 让 contain 自己排。
- 屏显高度 = `框宽 × 图高/图宽`; 现场对比: 914×32 → 屏显 614×21; 914×165 → 614×111; 914×348(19 根条带) → 614×234。

## 4. 提亮(硬件不动): 软件自动色阶

```python
lab = cv2.cvtColor(band, cv2.COLOR_BGR2LAB); L = lab[:,:,0]
lo, hi = percentile(L, 2), percentile(L, 98)
L = clip((L-lo)*255/(hi-lo), 0, 255);  L = 255*(L/255)**0.9
```
- 实测(700us 现场帧, 片排 82 行): 亮度 24 → **118~124**, 列对比 17 → **100**, 周期 r 0.97 不变。
- `hi-lo < 4` 时不拉(本来就没信息), 原样返回。
- 代价: 噪声同比放大(700us 信噪比本来就比 8000us 差 4~5 倍), 交付时要说清。

## 5. 曝光能不能实时切 —— 判据, 别抄注释

- 产线程序 `/param` 的注释里写着"采集过程中写曝光必失败 / 停采集会卡死"。那是**自动曝光还开着那天**的结论,
  不等于今天不能写。判"写没写进去"只看两件: ①`POST /param` 的 `applied[*].ok` ②切档后**抓两帧**看 p50(紧跟的那帧可能仍是旧档)。
- 本轮实测: 700us/16.38dB 设成功并回读一致; 但**换档抓帧那一瞬**会出全黑/平灰帧(传感器重配), 必须
  "换档 → 等 ~0.2s → 连续抓到非黑帧才用", 并**复位成设备当前值**(运行时记录), 不能用文件默认常数复位。
- 硬件透传式"判据图用亮档、检测用暗档"如果做, 换档窗口必须与检测抓帧互斥(一把锁), 否则检测图会吃到亮档。
- 更省事且本轮实际交付的: 硬件固定现场要的那一档, 判据图只做**软件色阶**(不动检测口径)。

## 6. 整帧网格调试页 (盲区沟通定式)

`/gold_debug` 返回 HTML, `/gold_debug/frame.png` 返回 PNG:
整帧 + 200px 网格(标 `x400`/`y1200` 刻度) + 上 1/3/中/下 2/3 三条参考线 + 当前自动框(绿色, 带 `r`/`pitch`)。
让操作员回一句"金手指在 y≈1000"或"绿框下面一格", 就把那排坐标锁死成配置值, 不再自动找。
比在本地猜几何快一个数量级; 也给后续复核留了坐标基准。

## 7. 这一格看不到/没变化时的第一检查: 谁在占 8791

- `systemctl is-active zmax-cam-live-stream` + `NRestarts`(实测曾 18242) + `ss -ltnp | grep 8791` 的 pid
  与 `systemctl show -p MainPID` 对比。不是同一个 = 手起进程占着端口, unit 反复退出重启 ⇒ **你改的 .py 根本没跑**。
- 处置: 停掉手起那个 pid, unit 立刻接管(实测 14s 内 active), 之后重新取流复核尺寸/亮度。
- 页面 img 跨端口(8791 vs 8793)会被 canvas 标为 tainted, 别在页面里 `getImageData` 量像素 —— 用 curl 取流在本地量。

## 8. 把判据图送进 AOI 的 YOLO 标注集(标定入口)

- 窗口: `tools/gui/aoi_inspect_console.py::AoiInspectConsole`(标题「🔍 光学质量检测 · 汇总终端」),
  有 ✏️标定 / 标定基准(原始图 2448×2048 ‖ 判据图 960×960) / 🎯识别金手指并框 / 💾记住此框 / 🚀训练。
- 数据层: `tools/yolo_annot_dataset.py`; 根 `data/datasets/yolo_annot/`(`sessions/<会话>/frames+labels`,
  `annotations.jsonl`, `truth.jsonl`, `classes.txt`)。
- 入库: `save_sample(ROOT_DEFAULT, rgb, boxes, device=, src=, annotator=, tag=, extra={"truth": ...})`,
  `boxes=[(x1,y1,x2,y2, 类名或 cls_id)]`, 像素坐标 + RGB + 不旋转; 宽或高 <2px 的退化框会被静默丢弃。
- 🔴 类别先 `load_classes()` 读(本机 `['peg','OPT_Gold']`), 金手指必须 `OPT_Gold`; 传 0 会静默落成 `peg`,
  且样本已写进 jsonl —— 清理要连 frames/labels/annotations 一起。
- 自动标: 判据图列剖面周期峰值 → 19 个竖框(实测间距 31px), 与 `/region` 的 19 根一致; 标完回读 `n_boxes`,
  并把"自动生成"写进 `annotator`, 让现场知道要目检。
- 窗口显示 `yolo_aoi_annot 权重无(启发式)` = 这条 YOLO 还没训过, 此时"识别金手指并框"走启发式而不是模型。
