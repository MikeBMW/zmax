# 离线 AOI 开发 (无相机 / 无工控机也能改判据、跑检测)

> 老倪 2026-11-11: 「一会我离线，但是你要保证，离线也可以进行AOI开发，代码你要copy完整。」
>
> 结论: 已经能做到。相机线、OPT SDK、加密模型权重都在工控机上，但**判据/检测代码已经逐字节搬过来**，
> 帧用本地离线帧库，整条链在本机自洽跑通，不依赖 192.168.23.23。

## 一、离线能做什么 / 不能做什么

| 能做 | 怎么保证 |
|---|---|
| 改判据、调阈值、改几何、看判据图 | `service/prod/*.py` 与工控机现役**逐字节一致**(sha256 对账)，本机直接跑就是产线行为 |
| 金手指 900x332 判据图 / n_keys / 节距 / 行带 | `render_judge_gated` 原函数，不重写 |
| 表面 1400x300 判据图 / 厚度 / 台阶右界 | `render_judge_surface` 原函数 |
| 节点整链(光学检测节点) | `policies/aoi/quality.inspect_aoi` 本机镜像优先，见 `gold_local` / `surface_local` |
| 回归验证 | `tools/verify_aoi_offline.py` 18 项 + `tools/verify_aoi_local_service.py` 22 项 |
| 用本机 YOLO 做观测 | `models/yolo_gold_v2.pt` 在本地(gui-venv311)，`ZMAX_AOI_YOLO=1` 才启用 |

| 不能做(本机物理上没有) | 现状 |
|---|---|
| 拍新照片 | 相机接在工控机；用 `corpus` 帧库或 `POST /frame` 推帧 |
| 产线缺陷模型判决 | 权重是加密件(.pt.enc)只在工控机；本机 verdict 来自判据几何，回执里 basis 明写 |
| 改曝光/增益 | `/param` `/exposure` 在本机回 `ok=false camera_absent`，要改对工控机下发 |

## 二、第一次准备 (只做一次)

```bash
bash tools/aoi/setup_aoi_venv.sh          # 建 .venv-aoi310: numpy 1.26.4 / opencv 4.10.0.84 / flask
./.venv-aoi310/bin/python tools/aoi/offline_manifest.py   # 代码完整性清单(sha256)，missing 必须为空
```

`gui-venv311` 是 cv2 5.0.0 —— 同一帧会命中不同窗口，**不能**用来复现产线判据。

## 三、日常离线循环

```bash
# 1) 起本机镜像(两路)，帧源用离线帧库
ZMAX_AOI_LOCAL_GOLD_SRC=corpus ZMAX_AOI_LOCAL_SURFACE_SRC=corpus \
  bash tools/aoi_local_service.sh start both

# 2) 改代码(判据在 prod/，或在本机镜像 app.py 的判决口径)
#    prod/*.py 改完先跑：  ./.venv-aoi310/bin/python tools/verify_aoi_offline.py

# 3) 真检测一次，看回执(判据图 + 判据量 + 判决 + 来源)
curl -s -X POST http://127.0.0.1:20082/capture_detect | head -c 400      # 金手指
curl -s -X POST http://127.0.0.1:20083/capture_detect | head -c 400      # 表面
curl -s -o /tmp/j.jpg "http://127.0.0.1:20082/picture?kind=judge"        # 判据图

# 4) 停
bash tools/aoi_local_service.sh stop both
```

帧源可选 (环境变量 `ZMAX_AOI_LOCAL_<KIND>_SRC`)：

| 写法 | 含义 |
|---|---|
| `corpus` | 离线帧库 `zmax_data/aoi_offline/<kind>/`，按顺序循环取 |
| `file:/path/x.jpg` | 指定一张 |
| `dir:/path/` | 目录里最新的图 |
| `push` | 只吃 `POST /frame` 推上来的帧 |
| `remote:192.168.23.23` | 工控机在跑时取它的原图(产线程序或 `cam_provider.py`) |
| `cam:http://127.0.0.1:8797/snap/gold.jpg` | 抓任意 JPEG URL |

⚠️ `remote:` 失败时会**自动回落离线帧库**(`ZMAX_AOI_LOCAL_OFFLINE_FALLBACK=0` 可关)，
回执 `source.how` 变成 `offline-corpus:<文件>` 且 `source.offline=true` —— 一眼能看出这不是现场实拍。

## 四、扩帧库 (想用什么场景就存什么)

```bash
# 工控机在线时批量抓真帧(走 provider 或产线程序)
./.venv-aoi310/bin/python - <<'PY'
import urllib.request, os
d="zmax_data/aoi_offline/surface"; os.makedirs(d, exist_ok=True)
for i in range(20):
    u="http://192.168.23.23:10083/picture?kind=origin&grab=1"
    b=urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent":"x"}), timeout=15).read()
    open(os.path.join(d, "surface_%03d.jpg"%i), "wb").write(b)
PY
```

仓库里另带 4 张真实帧 fixture (`tests/fixtures/aoi_frames/`，2 金手指 2 表面，共 1.4MB)，
用于 clone 下来就能跑的最小闭环。完整帧库放在 `zmax_data/aoi_offline/`(数据目录，不进 git)。

## 五、完整文件清单

`docs/aoi_offline_manifest.json` 是机器生成的清单(每个文件 sha256 + 作用)，
`tools/aoi/offline_manifest.py` 可随时重算。离线前跑一次，`missing` 为空即可放心走。

关键几件：

| 文件 | 作用 |
|---|---|
| `service/prod/gold_10082_prod.py` | 工控机现役金手指程序 206,094B sha `a595c39e…` |
| `service/prod/surface_10083_prod.py` | 工控机现役表面程序 65,368B sha `0f9206b5…` |
| `service/{stubs,prodload,sources,app,run}.py` | SDK 桩 / 加载器 / 帧源 / 路由 / 入口 |
| `policies/aoi/{local,quality,gold,surface,gold_yolo}.py` | 节点侧旁路 + 算法层 |
| `tools/aoi/cam_provider.py` + `provider_ctl.py` | 工控机只当"快门"(在线时用) |
| `tools/verify_aoi_offline.py` / `verify_aoi_local_service.py` | 18 项 / 22 项验收 |

## 六、回到现场(工控机在线)

```bash
# 10083 只取图: 工控机 provider (不加载模型/不写盘)
./gui-venv311/bin/python tools/aoi/provider_ctl.py start --port 10083 --sn D265250099 --exposure 80000 --gain 1.8
# 4060 判据
ZMAX_AOI_LOCAL_SURFACE_SRC=remote:192.168.23.23 bash tools/aoi_local_service.sh start surface
# 要回产线程序(自带 YOLO 判决)
./gui-venv311/bin/python tools/aoi/provider_ctl.py stop --port 10083
# 然后在工控机上起 cam_surface_10083_work_v20.py
```
