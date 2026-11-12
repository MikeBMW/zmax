# 渲染/真值/控制站端点 (8802) 与站页面 (8805)

单进程持有 Env 的场景服务: 渲染线程 + HTTP 线程。坐标单位要明确 (m 内部 / mm 展示)。

## 8802 · 场景服务 (`tools/ar_scene_render_server.py`)

| 端点 | 方法 | 作用 / 关键字段 |
|---|---|---|
| `/frame.png` | GET | 当前渲染帧 (960×720), 感知输入; **可能整帧冻结** (status.n 照涨), 要用 md5+truth 判活 |
| `/frame.png?az=&el=&dist=&tx=&ty=&tz=` | GET | 按指定机位**现渲染**一帧 (页面视角 → 模型输入走这条); 实测可靠 |
| `/status.json` | GET | `n` 帧号·`ts`·`mean`·`gold_px`(目标像素数 = 像素级真值)·`box`·`calib.res_mm_med` |
| `/label.json` | GET | 像素真值框 + `note`("像素连通域外接框 = 像素级真值, 非模型预测") |
| `/state.json` | GET | `truth`: `tcpL/tcpR`(mm)·`qL/qR`·`gold`(m)·`hole`·`mode` |
| `/control` | POST | 键是 **`L`/`R`(关节角, 度)** + `gripL/gripR`(0..1) + `mode`; mode `sim` 步进物理 / `idle` 只写 ctrl 不动。**未知键 (qL/qR) 静默忽略且回 ok:true** ⇒ 下完必读 `/state.json#truth` |
| `/reset` | POST | 复位双臂 home + 工件回位; 复位后置 idle |
| `/ik?side=R&x=&y=&z=` | GET | 雅可比 DLS 逆解 → `deg`; 多初值 + 限位罚分 |
| `/proj`, `/unproj` | GET | 点 ↔ 像素 (单应), 用于真值叠加与 2D→3D |

## 站页面 8805 (`tools/ar_render_station.py`)

| 端点 | 作用 |
|---|---|
| `/` | 单页: 渲染图 + 检测框叠加 + 定位/真值偏差 + plan 步骤表 + 执行结果 + 复测对比 + 取证图路径 |
| `/api/live` | 全量状态 JSON (phase/l2/perc/plan/act/truth/log) — 页面 1s 轮询 |
| `/api/frame.jpg` | 最近一帧 (页面画布底图) |
| `/api/run` | 跑一轮: 抓帧→感知→plan→双臂执行→复测 |
| `/api/auto` | 连跑 (每轮约 17s) |
| `/api/reset` | 场景复位 |

## 字段口径

- `act[].reached_mm` 一律来自 `/state.json` 真值, 不是规划目标值。
- `act[].passes` 记录残差回补轮数; `passes>1` 说明静差被补过, 正常现象不是 bug。
- `perc.err_mm` = 感知 3D 与 `truth.gold` 的欧氏距离; 页面必须显示, 否则"定位准不准"无从判断。
- `frame_age_s` 必须显示: 帧龄大的数字不可信 (渲染线程卡住时尤其)。

## 把“3D 坐标/URDF”变成模型能看的图

1. `/ik?side=R&x=&y=&z=` 得 `deg` (真值目标 mm 口径; 场景内部是 m)。
2. `/control {"mode":"sim","L":<当前 L deg>,"R":<新 R deg>}` — 两侧都要发, 否则另一侧停在上一位姿;
   未知键不回错, 必须用 `/state.json#truth` 的 `tcpR` 对目标算残差 (实测 IK 1.5mm → 真值 6.7mm)。
3. 等收敛后取图: 定机位用 `/frame.png`, 要跟页面同视角用 `/frame.png?az/el/dist/tx/ty/tz`。
4. 模型输入只接服务端渲染帧; 浏览器画布截图实测纯白且不同域 (检出 0), 不要走那条。

## 机位预设与直播页 (用户入口)

| 机位 | 参数 | 语义 |
|---|---|---|
| `ar3d` (全景) | `lookat [0.62,0.25,0.42]` · dist 2.25 · el −20 · az 0 · fovy 69 | 跟随 AR 页相机 (页面 `POST /cam` → `ar3d_cam.json`) |
| `close` (特写) | 见 `VIEWS["close"]` | 料盘/工件特写, 判读用 |
| `top` (顶视) | `lookat [0.55,0.19,0.11]` · dist 1.30 · el −89 · az 0 · fovy 42 | 正俯视全工位; **现渲染, 不读 `views` 缓存** |

- 顶视取景: 1.75m/55° 时工位只占中间一条横带, 上下约 60% 是棋盘地板 (行亮度实测上 300 行全暗); 收到 1.30m/42° 且 `lookat z=0.11` 后 120~660 行都有内容。
- 顶视必须关掉几何组 3 (`geomgroup[3]=0`), 否则横梁/相机盒盖住料盘; 预设循环与自由机位两条渲染路径都要加。
- 直播页: `/video` 带 `Accept: text/html` 返 HTML 外壳, 不带则返 MJPEG (脚本/`Invoke-WebRequest` 会一直挂着)。机位可用 `?cam=` 指定, 页面顶部还有「全景/顶视/特写」按钮直接切 `VIEW` 变量, 不用改 URL。
- 取图客户端 (无闪): `fetch(u,{cache:'no-store'}) → blob → URL.createObjectURL → img.src` → 旧 URL `revokeObjectURL`; 串行拉, 上一张没到就跳过这一拍。

## systemd

两个 unit: `zmax-ar-render.service` (:8802, 依赖 `DISPLAY=:0` + `MUJOCO_GL=glfw`)、`zmax-ar-render-station.service` (:8805, 依赖前者)。都 `Restart=always`; 重启后先用 `/status.json` 确认 `n` 在涨再继续。
