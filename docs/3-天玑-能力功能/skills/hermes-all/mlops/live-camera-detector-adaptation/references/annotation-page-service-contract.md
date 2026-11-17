# 标注页服务契约（窄条目标 / 固定个数类）

适用: 要在**现有 HTTP 服务**上加一个「取原图 → 自动给框 → 人手改 → 存训练集 → 点训」的标注页。
零新进程、零新端口; 取图、存样本、训练全部走同一份 handler 的函数调用。

## 路由表（实测形状）

| 路由 | 方法 | 作用 | 要点 |
|---|---|---|---|
| `/station/gold` | GET | Canvas 标注页 | 返回 **bytes**（`str` → 0 字节空白页） |
| `/station/gold/frame.png?grab=1` | GET | 原始帧（本例 2448×2048） | 抓一次就缓存进模块变量，供保存时复用同一帧 |
| `/station/gold/auto` | GET | 自动框 | 返回 `{w,h,n,pitch,boxes:[[x1,y1,x2,y2],…]}` + 一句判据说明 |
| `/station/gold/save` | POST | 存样本 | body `{boxes:[…], note:""}`；用缓存的**原始帧** |
| `/station/gold/train` | POST | 起训练 | 先 build 数据集再 train；返回 `{pid, log}` |
| `/station/gold/stats` | GET | 样本数/类别/权重/日志尾 | 页面必须回显“有无权重” |

## 关键实现点

```python
# 1) 缓存被标注的那一帧（否则用户标的框与存进去的图不是同一张）
_GOLD_ANNOT = {"rgb": None, "ts": 0.0}

def _gold_annot_fetch():
    bgr = 从相机/上游 HTTP 取原始帧()          # 原始图，不是叠加后的显示副本
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    _GOLD_ANNOT.update(rgb=rgb, ts=time.time())
    return bgr

# 2) 存样本: boxes 是像素坐标，类名/id 从 classes.txt 取
import yolo_annot_dataset as DS
DS.save_sample(DS.ROOT_DEFAULT, _GOLD_ANNOT["rgb"],
               [(x1, y1, x2, y2, "OPT_Gold") for x1, y1, x2, y2 in boxes],
               src="原始图 2448x2048 (标注页)", note=note)
```

- 数据集目录形状: `data/datasets/yolo_annot/{sessions/<会话>/{frames,labels}, annotations.jsonl, truth.jsonl, classes.txt}`。
  验收: `labels/*.txt` 的行数 == 框数，每行 `cls cx cy w h`（归一化），宽高换算回去对得上原图像素。
- 训练入口: `python tools/yolo_annot_dataset.py --build` → `python tools/yolo_annot_train.py --epochs N --imgsz 640 --device 0`。
  小集(<300 张)按另文规则走热启动 + 低 lr + 冻骨干，别从 COCO 重训。

## 前端最小交互（用户明确要求过的）

```text
拖空白 = 新画框
拖框内 = 移动整框
拖角/边 = 缩放（仅选中框出现 8 个手柄）
方向键 = 微调 1px（Shift = 10px）
Del/Backspace = 删选中    Esc = 取消选中
```

- 命中容差用**屏幕像素**（如 10px）再除以显示缩放换算成图像坐标；否则放大/缩小后手柄抓不住。
- 框要夹在图像边界内、最小边 ≥4px；缩放时对边不许越过另一边。
- 改完不自动写盘；页面上常驻一行「N 个框 · 未保存」。
- 按钮组坑: 若页面里有「换 MJPEG 源」的按钮组（组内 handler 读 `dataset.stream` 并赋给 `img.src`），
  **新功能按钮必须放在组外** —— 否则 `im.src = undefined` 会把画面搞没。

## 验收清单（不看页面也能判）

```bash
curl -s -o /tmp/p.html -w '%{http_code} %{size_download}\n' .../station/gold     # 200 且 >0 字节
curl -s .../station/gold/auto | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d["n"],d["pitch"])'
curl -s -X POST -d '{"boxes":[[..]],"note":"自测"}' .../station/gold/save
# 回读: 会话目录里的 labels 行数、annotations.jsonl 新增一条、stats 样本数 +1
```
