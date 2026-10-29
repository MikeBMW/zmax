# 渲染/真值/控制站端点 (8802) 与站页面 (8805)

单进程持有 Env 的场景服务: 渲染线程 + HTTP 线程。坐标单位要明确 (m 内部 / mm 展示)。

## 8802 · 场景服务 (`tools/ar_scene_render_server.py`)

| 端点 | 方法 | 作用 / 关键字段 |
|---|---|---|
| `/frame.png` | GET | 当前渲染帧 (960×720), 感知输入 |
| `/status.json` | GET | `n` 帧号·`ts`·`mean`·`gold_px`(目标像素数 = 像素级真值)·`box`·`calib.res_mm_med` |
| `/label.json` | GET | 像素真值框 + `note`("像素连通域外接框 = 像素级真值, 非模型预测") |
| `/state.json` | GET | `truth`: `tcpL/tcpR`(mm)·`qL/qR`·`gold`(m)·`hole`·`mode` |
| `/control` | POST | `{mode, qR, qL, gripR, gripL}`; mode `sim` 步进物理 / `idle` 保持 |
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

## systemd

两个 unit: `zmax-ar-render.service` (:8802, 依赖 `DISPLAY=:0` + `MUJOCO_GL=glfw`)、`zmax-ar-render-station.service` (:8805, 依赖前者)。都 `Restart=always`; 重启后先用 `/status.json` 确认 `n` 在涨再继续。
