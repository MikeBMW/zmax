# 侧面(表面)检测 10083 · 通道与常量

## 服务
- 基址 `http://192.168.23.23:10083`(工控机 OPT 程序; 同机 10082 = 金手指)。
- 触发检测: `POST /capture_detect` → 然后轮询 `GET /last_result` 拿判据(实测一轮约 3~9s, 偶发 5xx)。
- 取图: `GET /picture?kind=origin`(原图 2448x2048) / `kind=judge`(判据图) / `kind=crop`(letterbox 1280x1280);
  带 `&grab=1` = 另抓一帧实时图 —— **它和检测帧不是同一光照**, 别拿来跟检测帧比位移。

## 常量
- 原图 **2448x2048**; 模型输入 letterbox 1280x1280。
- 程序 ROI(原图坐标) = `(330,960)-(1815,1440)`(“亮条/过曝条”必须落在这个带里)。
- 判据字段: `judge_ok`(必须 true 才算拍到位) · `count` · `defects` · `judge_why`(直接说明原因, 如
  “亮条上边沿点太少(0) —— 画面里没找到过曝条”)。`judge_ok=false` 时 `count/defects` 不可信。
- 曝光异常同样会让它判不出来 ⇒ 用 `tools/aoi_surface_exposure_sweep.py` 单独排查(只读, 不动机器人)。

## 侧面观察位(示教点真源 `data/skills/l2_atomic/taught_points.json`)
- `侧面点0/1/2/3` = 表面检测观察位; `准备点` = 现场确认的安全退让位(比观察位低、再往外退)。
- **任何侧面调整的目标 XY 必须落在这些点附近 —— 不自己发明侧面 XY。**
- 不在观察位上时, 先按两点转移铁律把工件送到观察位附近(垂直抬 ≥50mm → 横移 → 到目标上方 → 垂直下落), 再谈微调。

## 工具
- `tools/aoi_surface_offset.py` — 统一口径测量(触发 → 轮询 → 取原图 → 算亮物 bbox/中心 与 ROI 偏差 px, 出 JSON)。
- `tools/probe_surface_live.py` — 整轮存证(判据图/原图 + 量化), 目录 `reports/aoi_surface_probe_<ts>/`。
- `tools/aoi_gold_servo.py` — 10082 金手指的成熟伺服(check/teach/calibrate/serve + 四级闸), 建 10083 伺服时照它同构。

## 参数单一真源
`data/config/aoi_surface_params.json` — 安全区域 / 运动速度 / 侧面检测 / 伺服四段, 每项带
value·unit·range·说明·代码位置; 现场改这一个文件。

## 报数口径
偏差数字**每次现测**(场景/光照会变, 不照抄历史 bbox); 报的时候分“运动链”与“反馈链”两栏。
