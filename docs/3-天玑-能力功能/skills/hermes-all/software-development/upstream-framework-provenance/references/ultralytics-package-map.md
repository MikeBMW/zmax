# ultralytics 8.x 安装包地图（实测 8.4.126）

## 定位

```bash
python -c "import ultralytics,os;print(ultralytics.__version__, os.path.dirname(ultralytics.__file__))"
# → 8.4.126 /…/site-packages/ultralytics
```

安装形态判定：目录在 `site-packages` 且同级有 `ultralytics-<ver>.dist-info` ⇒ pip 安装产物，不是 fork。

## 目录职责（体量按 8.4.126 实测）

| 目录 | py 文件 / 行数 | 职责 |
|---|---|---|
| `engine/` | 8 / 7.7k | `model.py` 统一门面（train/val/predict/export/tune 五动词）· `predictor.py` 推理循环 · `trainer.py` 训练 · `validator.py` 指标 · `exporter.py` 导出 · `results.py` 结果对象 |
| `nn/` | 32 / 11.4k | `tasks.py` 各任务模型类（DetectionModel / Segmentation / Pose / OBB / Classification）· `modules/` 层积木（Conv、C2f、SPPF、Detect head）· `autobackend.py` 推理后端（pt / ONNX / TensorRT / OpenVINO）· `text_model.py` 文本编码 |
| `utils/` | 54 / 20.5k | `nms.py` · `ops.py` 框变换/IoU · `loss.py` · `metrics.py` · `plots.py` · `checks.py` 环境自检 · `downloads.py` 权重下载 · `autobatch`/`autodevice` · `callbacks/` · `export/` |
| `models/` | 85 / 22k | 按任务与代际的模型包：`yolo/{detect,segment,classify,pose,obb,world}` · `sam/` · `rtdetr/` · `fastsam/` |
| `cfg/` | 1 / 1.2k | `default.yaml` 全局超参 · `models/*.yaml` 网络结构 · `trackers/*.yaml` |
| `data/` | 11 / 8.7k | 数据集基类、加载、增强（Mosaic/MixUp/HSV/翻转）——只有训练链用 |
| `trackers/` | 15 / 3.9k | ByteTrack / BoTSORT（`model.track()`） |
| `solutions/` | 20 / 3.6k | 区域计数、越线计数、速度估让等应用模板 —— 工业判据不用 |
| `optim/` | 2 / 0.3k | 优化器与学习率调度封装 |

顶层只有 `__init__.py`（导出 YOLO/RTDETR/SAM 等 + 环境检查）。

## 推理链关键行号

```
engine/model.py:461          YOLO.predict 入口（参数校验、拼 source）
engine/predictor.py:74       BasePredictor
engine/predictor.py:160        preprocess（letterbox、BGR→RGB、归一化、拼 batch）
engine/predictor.py:293        stream_inference（setup_source → 前向 → 后处理）
engine/predictor.py:219        postprocess（尺度还原到原图）
nn/tasks.py:440              DetectionModel
nn/tasks.py:1043               DetectionModel.predict（前向）
utils/nms.py:13               non_max_suppression
```
行号随版本漂，引用时以当前安装为准（`grep -n "    def predict" engine/model.py`）。

## 我们只在三处接触它

包装层 `src/lerobot/policies/yolo_3d/yolo_state_aligner.py`：
- `YOLO(weights)` 构造 + `model.predict(bgr, conf=…)` 调用
- 读 `res.boxes` / `res.names`（`model.model.names` 覆写才生效）
- 读 `.depth.data`（深度头）—— GPU 后是 cuda tensor，必须 `.detach().cpu().numpy()`

## 取源码改框架

```bash
pip download ultralytics==8.4.126 --no-deps --no-binary :all: -d /tmp/ul
# 解包后 pip install -e /tmp/ul/ultralytics-8.4.126
```
改动量小于一个函数时更安全的做法：包装层 monkey-patch，把补丁、动机、实测现象写在同一处注释里，升级后重跑一遍验证。
