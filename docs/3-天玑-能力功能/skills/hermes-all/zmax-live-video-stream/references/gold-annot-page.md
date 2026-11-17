# 金手指标注页 `/station/gold`（原始图 → YOLO 标注数据集 → 训练）

工位总览页「🔍 金手指检测」格里的 **🏷 标注** 按钮打开它。全部挂在 **8793 现有的 http handler** 里
（`tools/cam_live_stream.py`），**不新起进程、不开新端口** —— 新端口会多一份进程要守、还会和 `zmax-cam-live-stream` unit 抢。

## 路由契约

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/station/gold` | 标注页（Canvas：拖框 / 点框选中 / `Del` 删 / `Esc` 取消） |
| GET | `/station/gold/frame.png?grab=1` | 原始图 `2448×2048`（10082 `?kind=origin&grab=1`），服务端缓存本次帧 |
| GET | `/station/gold/auto` | 给一版 19 框 + `band`/`pitch`/`rule`，供人工再修 |
| POST | `/station/gold/save` | `{"boxes":[[x1,y1,x2,y2],...],"note":""}` → 写进 YOLO 数据集 |
| POST | `/station/gold/train` | `{"epochs":100,"imgsz":640}` → 后台 build 数据集 + 训练 |
| GET | `/station/gold/stats` | 样本数 / 类别 / 最新 `best.pt` / 训练 pid 与日志尾 |

**保存必须用「展示给他的那一帧」**：取图时把 RGB 存进模块级缓存（`_GOLD_ANNOT["rgb"]`），
`save` 只读这份缓存。否则他标的是旧帧、存的是新帧（人眼看不出来，训练集就废了）。

## `auto` 的 19 框怎么算（判据必须是"物理根数"）

1. 条带取源服务 `/region` 的 `bbox`（模板匹配给出的金手指排），**不要自己找最亮行**。
2. 列剖面先用**自相关测出真实周期**（现场 lag≈68~71px），再用这个周期做去趋势窗口 + 最小峰间距。
   🔴 用固定小窗口（如 15px）去趋势会把**一根手指判成左右两条边**：实测间距掉到 35px、只覆盖半条，19 框全错位。
3. 峰数多于 19 时按"19 连窗口 + 间距方差最小"选一段，保证均匀覆盖整条而不是只取前半截。

`band`/`pitch` 要回给页面显示，操作员才能判断这版框可不可信。

## 落盘口径（`tools/yolo_annot_dataset.py`）

```python
import yolo_annot_dataset as DS
DS.ROOT_DEFAULT                      # data/datasets/yolo_annot
DS.load_classes(DS.ROOT_DEFAULT)     # 现场 ['peg', 'OPT_Gold'] —— 金手指是 **OPT_Gold（class id 1）**
DS.save_sample(DS.ROOT_DEFAULT, rgb, [(x1,y1,x2,y2,"OPT_Gold"), ...],
               src="原始图 2448x2048 (标注页 /station/gold)", annotator="人工标注", tag="gold_finger")
```

- 帧图落 `sessions/<session>/frames/*.jpg`，标签落 `labels/*.txt`（YOLO 归一化行），
  台账 `annotations.jsonl` + 真值侧车 `truth.jsonl`。
- 类别写错（例如给了 `peg`）标签就是错的 —— **写完回读 `labels/*.txt` 的行数 = 框数、首列 = 1**，别只看接口 `ok:true`。
- 训练：`tools/yolo_annot_dataset.py --build --check` → `tools/yolo_annot_train.py --epochs N --imgsz 640 --device 0`
  （本机 RTX 4060 8G 可用）。权重落在 `outputs/yolo_annot/<name>/weights/best.pt`；
  统计页显示「权重 无(未训练)」时，控制台那条 `yolo_aoi_annot` 走的是**启发式**，不是模型。

## 坑（都实测踩过）

1. 🔴 **`_send(code, ctype, str)` 会写出 0 字节**：HTTP 200、`size_download 0`、页面全白。
   新增任何路由，响应体先 `.encode("utf-8")`。诊断顺序永远是「先量字节数，再看前端」。
2. 🔴 **改 Python 必须 restart `zmax-cam-live-stream`**：`tools/web/station.html` 是按 mtime 热读的，
   `cam_live_stream.py` 不是 —— 只改 Python 而不重启，页面上看到的是旧逻辑。
3. **工位总览加按钮要放在换源按钮组之外**：`#gview` 里的按钮会被绑定成"换 MJPEG 源"（`im.src = b.dataset.stream`），
   多一个没有 `data-stream` 的按钮会被当成源、把画面打成空。标注按钮单独放组外，只负责 `window.open('/station/gold')`。
4. **取图慢**（PNG 2448×2048 ≈ 3.8MB）：页面只在点「📸 取新图」时抓，别在轮询里抓；`stats` 不触发出图。
5. 页面/接口都**不碰硬件参数**：相机曝光写不进去（见 SKILL.md 那条），提亮只在显示侧做。

## 验收（缺一不算通）

```
page   200 / >7KB                       （0 字节 = 坑 1）
frame  200 · cv2 读到 2448×2048
auto   n=19 · pitch≈68px · 覆盖整条（不是半条）
save   ok:true · labels 行数=19 · 首列=1 · stats 样本数 +1
```
