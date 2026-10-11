# AR 场景 · AOI 联合检查 · 摆盘 — 连夜自主完成记录 (2026-10-11 夜)

> 老倪原话: 「把 3D场景的力控, 改成 AR…应用产品大屏的所有数据(金手指 AOI点位/空间点位/臂相机/以前记录的点位)
> 叠加到真实场景中。插拔已完成; 摆盘要**真实**完成光模块从料盘拿到 tray 盘; AR 要完成 AOI 检查,
> 联合工控机的 AOI 程序做缺陷检测、金手指矩形搜索、侧边位置修正; AR 场景要有光模块的标定能力。」

---

## 0. 一句话结论

| 事项 | 状态 | 证据 |
|---|---|---|
| RealSense D435 驱动 + 接入 AR 服务 | ✅ 完成 | `tools/realsense_probe.py` · 8797 `/api/rs_info` 实测 |
| 3D场景「🧩 力控」→「🥽 AR」 | ✅ 完成(已入库, 控制台已重启) | `ss_dreamview.py` 按钮/方法 + 工位总览页也加了「🥽 AR 场景」入口 |
| AR 画面 = RealSense 实拍 + 叠加层 | ✅ 服务/页面就绪 | `http://<本机>:8797/ar?cam=rs` · `/cam.mjpg?c=rs` 实测 1.9MB/5s 流 |
| AOI 联合检查(缺陷检测) | ✅ 实测通过 | 真拍 → `verdict=OK · count=0 · 推理 1715ms` |
| 金手指矩形搜索 | ✅ 实测通过 | `/region.quad` 4 点 · bbox `[1045,1439,365,29]` · 倾角 1.75° |
| 侧边位置修正 | ✅ 实测输出 | Δx=+4.0px · 反旋 −1.75° (px→mm 待现场雅可比) |
| 摆盘(功能链) | ✅ 仿真 3/3 合格 | `reports/tray_place_latest.mp4` · Δxy≤0.47mm / 姿态≤0.04° |
| 摆盘(**真机**取放) | ⛔ **卡在运动授权** | 8793 `motion_armed=false` · `auth.armed=false` · `left_s=0` |
| 光模块 AR 标定能力 | ✅ 工具 + 自检通过, 真点待采 | `tools/ar_calib_module.py` selftest `rms 0.0px / dR 0.0° / dt 0.0mm` |
| 插拔 | ✅ 之前已完成(本次未动) | — |

**唯一需要你动手的一件事**: 在工位总览页 (8793 `/station`) 开一次**运动授权窗** —— 真机摆盘取放与
AR 相机真实标定点采集都在等它(见 §5)。

---

## 1. RealSense D435: 装驱动 → 接入 AR 服务

- 设备: `Bus 002 Device 006: ID 8086:0b07 Intel Corp. RealSense D435` (v4l2 占 `/dev/video8..13`) · 自报型号 `RealSense D435` · **固件 5.15.1.55** · `pyrealsense2` 导入自检 OK
- 驱动: `pyrealsense2 2.59.1` (装进 `gui-venv311`, 不动系统 python)
- 实测(640×480): 彩色 `fx=603.45 fy=602.22 ppx=320.11 ppy=258.20`, 深度 `scale=1mm`,
  深度有效率 **76%** · 中位 **1.5m**; 帧率 ~30fps, `age_s≈0.02s`
- ⚠️ **相机是独占设备**: 谁来起 pipeline 谁独占。AR 服务(8797)持有 ⇒ **别的进程直接 `import realsense_source` 会
  `Device or resource busy`**; 要用就得走 8797 的接口(下表)。这条已写进技能。

### AR 服务(8797, `tools/tcp_ar_server.py`)新增端点

| 端点 | 作用 |
|---|---|
| `/rs.mjpg` · `/snapshot/rs.jpg` | RealSense 彩色流 / 单帧 (AR 底图) |
| `/cam.mjpg?c=rs` | 页面按相机名取流(rs 走本机源, 不走 8791 代理) |
| `/api/rs_info` | 出厂内参 + 深度体检 + 帧龄 |
| `/api/rs_point?u=&v=` | 像素 → **相机系 3D**(用深度量, 不是猜) |
| `/api/rs_detect` | 在 AR 相机帧里跑**在役权重** `models/yolo_peg_live.pt` → bbox/conf + 相机系 3D |
| `/api/aoi/inspect` (POST) | 真拍 → 缺陷判决 + 矩形 + 侧边修正(落 `zmax_data/ar_aoi_state.json`) |
| `/api/aoi/state` `/api/aoi/read` `/api/aoi/gold.jpg` | 最近结果 / 只读体检 / 金手指判据图 |

AR 页面 (`tools/web/tcp-ar.html`, 按 mtime 热读, 改页面不用重启): 默认底图改成 **RealSense**,
新增「🔍 联合工控机 AOI」卡片(请求检测/只读体检 + 判据图)与「🔎 找光模块(YOLO) / 📐 标定信息」;
顶部标签实时显示 `RealSense 帧 N · 帧龄 x.xxs · 深度中位 xxxx mm`。

## 2. 3D 场景: 「🧩 力控」→「🥽 AR」

- `tools/gui/ss_dreamview.py` 第三个场景按钮从「🧩 力控(保持当前波形)」换成「🥽 AR」:
  点它 → 校验 8797 服务与 RealSense 是否有帧 → 打开 `http://127.0.0.1:8797/ar?cam=rs` →
  状态栏回报「帧数/帧龄/深度中位」; **服务没起/没帧就照实说, 不弹空窗、不用旧帧冒充**。
  (原力控波形窗口代码保留未删, 只是不再挂在这个按钮上。)
- 工位总览页(8793, 热读)也加了「🥽 AR 场景」按钮(产线内网可达; 公网域名下点不开属预期)。

## 3. AOI 联合检查(实测数字, 2026-10-11 22:56 与 23:0x 两次)

链路: 本机 → 8797 `/api/aoi/inspect` → `tools/aoi_link.py` → 工控机 `192.168.23.23:10082`。

| 项 | 实测 |
|---|---|
| 触发拍照 | `POST /capture_detect` → `{"code":200,"msg":"success"}` · 3.7s(含冷路径) |
| 缺陷判决 | `GET /last_result` → `verdict=OK · count=0 · 推理 1715ms` |
| 金手指矩形 | `/region` → quad 4 点 · `bbox=[1045,1439,365,29]` · 倾角 **1.75°** · minAreaRect 中心 (1228.0,1453.9) 尺寸 **363.8×17.5px** |
| 侧边位置修正 | Δx=**+4.0px**(画面偏右) · 反旋 **−1.75°**(px→mm 需现场雅可比, 已留字段, **不编数**) |
| 判据图 | `/picture?kind=crop` → 900×332, 黑底占比 0.406(有效画面) |
| 判据版本 | `v36-gold19-cxwin-20261009`, `state=ok`, `n_keys` 实测 8~13 在跳 |

⚠️ **两点如实记录**:
1. 本次区域的**几何只有 363×17.5px**(技能里记的前视真值是 1455×70) ⇒ 当前工件/相机位姿与"前视满条"不同,
   `n_keys` 也因此在 8~13 之间跳(与技能里记的"根数逐帧翻"是同一类问题), 判决 `state=ok` 只说明**判据渲染成功**,
   不等于"19 根定案"。要按 19 根口径判, 需要先把工件摆回前视工位再拍。
2. `/last_result` 的 `OK · count=0` **不等于合格** —— 工件不在位时也报这个(技能已记录), 别当质检结论用。

## 4. 摆盘(光模块 → tray 盘)

- 配置真源: `config/tasks/tasks.json` TASK-06-TRAY = 「摆盘取放」, 5 步: 定位识别 → **取件(末端下降至吸附位,
  真空建立 ≤200ms 后抬起离盘)** → 转运对位 → **放入(断真空释放, 姿态偏差 ≤1°)** → 判态循环。
- 实跑(仿真链, `tools/ss_task_runner.py --task TASK-06-TRAY`, 22:58): **3/3 颗合格**
  · Δxy = (+0.06,+0.34) / (−0.12,+0.43) / (−0.13,+0.47) **mm** · Δz = +1.78mm
  · 姿态 = 0.04 / 0.02 / 0.02 **°**(判据 ≤1mm / ≤1°) · 2708 步 / 2.6s
  · 视频 `reports/tray_place_latest.mp4`(1.42MB, 22:58:00)
- **两个超差项(如实报)**: 真空(进带→锁) **425/538/525ms** > 配方 ≤200ms; 单颗 CT **10.6~11.6s** > 目标 ≤3.15s。
  即"放得准"已达标, "节拍与真空建立时间"未达标 —— 下一步该从这两处收。

## 5. 为什么真机摆盘没动(以及怎么让它能动)

按你自己定的规矩 —— **真机动作的现场授权只认工位总览页(8793), 聊天里的动作词不算授权** —— 我在下发前查了闸门:

```
ctl.motion_armed = false
ctl.auth.armed   = false     (window_s=2700, left_s=0, 上次 armed 来源 IP 10.163.146.78)
TCP 真值 = (0.5927, 0.1406, 0.6436)  帧龄 0.2s   ← 真值通道健康
产线 motion 节点: 未在跑(只有被动的 live_motion_recorder + 待命的 l2_daemon)
```

⇒ **未授权 ⇒ 一条运动指令都没发**(这是设计行为, 不是失败)。等你在 `/station` 开授权窗后, 我可以立刻:
① 用已示教点位做 **AR 相机 ↔ base 真实标定**(采 5~8 对, 全程慢速); ② 按 TASK-06-TRAY 配方走**真机取放**
(先 dry-run 只算目标核对路径, 再慢速下发; 每次下发前后读 TCP 真值 + 力判据)。

## 6. AR 场景的「光模块标定能力」

回忆之前的做法(为什么这么设计): 标 YOLO 时用的是 **在役权重单点指针**(`models/yolo_peg_live.pt`)+
**同口径真机帧评测**; 标固定相机外参用的是 **DLT 线性初值 + RQ 分解 + 非线性收细** + 「没外参就不画」。
这次把两者接起来: **YOLO 在 AR 相机里找光模块 → 深度给相机系 3D → 与该模块的 base 真值配对 → 解外参**。

- 工具 `tools/ar_calib_module.py`:
  `detect`(零运动, 在 AR 帧里跑在役 YOLO + 深度 3D) · `pair`(追加一对 uv↔base; base 缺省取 TCP 真值,
  帧龄 >1s **拒收脏点**) · `solve`(≥5 对, **用出厂内参只解 R,t**, 落 `data/scene/cam_calib.json["rs"]` +
  重投影 RMS/逐点误差/散布) · `selftest`(合成相机自测)。
- **自检实测**: `rms_px=0.0` · `dR=0.0°` · `dt=0.0mm`(焦距用设备值 603.45) ⇒ 解算管线正确。
- **真实检测实测**: `/api/rs_detect` 返回 `model=models/yolo_peg_live.pt · n=0` ——
  当前 RealSense 视野里**没有光模块**(或没对准工作区) ⇒ 标定取点前需把相机对准料盘/tray 区(或把模块停在视野内)。
- 页面侧同样可用: 「🎯 进入标定」点夹爪/工具尖(该相机有出厂内参, **4 点即可**, 建议 5~8 点) → 「💾 解算并保存」。

## 6·补、相机系 3D 位姿叠加（不依赖外参的 AR 叠加, 已在真实深度上跑通）

`tools/ar_calib_module.py pose` / 8797 `GET /api/rs_pose` / AR 页面「📦 目标位姿(相机系)」:
在**真实画面**上画出虚拟 3D 坐标架 + 目标框, 数值全来自深度真值:
有 YOLO 检出框就量光模块, 没有就量画面中心那块面。输出: 相机系中心(mm) · 尺寸(mm) · 长轴方位 · 平面法向 ·
平面 RMS · 有效深度占比 · 叠加图 `zmax_data/ar_rs/rs_pose_last.png`。

实测(2026-10-11 23:0x, 中心 ROI `[192,144,448,336]`): 相机系中心 **[1.7, −15.8, 2156.3]mm** ·
尺寸 5641×1620mm · 平面 RMS **193mm** · 有效深度 58%(28548 点) · 深度中位 **1.767m** ⇒
**相机在 ~2.2m 外对着一个大面(墙/隔断级尺度, 不是工作台)** ⇒ 这台相机现在**没对着料盘/tray 工作区**,
`/api/rs_detect` 连续两次 `n=0`(视野里没有光模块)。要把它当 AR 底图看工件, 得先把机位对准工作区(见 §5)。

## 5·补、为什么真机摆盘**不能**靠"眼睛找槽位"凑（复核过台账, 不是我懒）

- `tools/probe_tray_slots.py` 头注留档(2026-09-28, 臂上 D405 视角): 料盘**全盘槽位阵列在这路相机上检不出** ——
  9 组(核×阈值)组合候选数在 0~7 之间乱跳, 命中的是 ROI 角与绿色工装, 不是泡棉槽腔;
  黑泡棉上的槽腔属"黑上更黑", 对比度不足, 且该帧深度对槽位高低无分辨力(整片 0.4~0.6m 平坦, 独立视觉复核确认)。
  ⇒ 能给的只有 **示教槽位 2 个 + 当前占用槽 2 个**; 要全盘槽位得换顶摄 + 平面单应。
- `tools/place_module_boxes.py` 头注: 光模块实测尺寸 **91.0 × 18.6 × 20mm**(两视角独立量到同一量级),
  锚点=绿手把、朝向=手把长轴, 当帧重测不吃旧值 —— 这套量测口径可直接喂 AR 叠加(光模块真实尺寸有了)。
- 结论: 「从料盘取 → 放进 tray 槽」这两个位姿属**新点位**, 且槽位几何**没有可自动测量的真源**
  ⇒ 按纪律(新/危险点位老倪先做 + 真机授权只认 8793) **不该由我盲下**; 我把它整理成"授权后即可跑"的状态(§5 ① ②)。

## 7. 命令速查

```bash
# RealSense 自检 / 取帧
gui-venv311/bin/python tools/realsense_probe.py
gui-venv311/bin/python tools/realsense_source.py            # 打印内参/深度体检
# AR 服务(8797)重启(只碰 AR, 不动 8791/8793)
bash /home/ubuntu/.hermes/cache/scratch/restart_ar.sh
# AR 页面
http://192.168.23.50:8797/ar?cam=rs
# AOI 联合检查
gui-venv311/bin/python tools/aoi_link.py health 10082        # 只读
gui-venv311/bin/python tools/aoi_link.py inspect 10082       # 真拍+判决+矩形+侧边修正
curl -sX POST -H 'Content-Type: application/json' -d '{"port":10082}' http://127.0.0.1:8797/api/aoi/inspect
# 光模块标定
gui-venv311/bin/python tools/ar_calib_module.py selftest|detect|pairs|solve
# 摆盘(仿真链)
gui-venv311/bin/python tools/ss_task_runner.py --task TASK-06-TRAY
```

## 8. 本次改动文件

- 新增: `tools/realsense_source.py` · `tools/realsense_probe.py` · `tools/aoi_link.py` · `tools/ar_calib_module.py`
- 改动: `tools/tcp_ar_server.py`(rs 相机源 + rs/aoi 端点) · `tools/laptop_cam_solve.py`(`f_fixed/cx/cy`, 已知内参只解 R,t) ·
  `tools/gui/ss_dreamview.py`(力控→AR) · `tools/web/tcp-ar.html`(默认 rs + AOI/光模块面板) · `tools/web/station.html`(🥽 AR 场景入口)
- 产物: `zmax_data/ar_rs/{color.png,depth.png,probe.json,rs_detect_last.png}` · `zmax_data/ar_aoi_state.json`
