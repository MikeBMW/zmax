# Z-MAX 全系统配置清单（交付件 5.50.B）

文档编号: ZMAX-CFGL-20261013 · 版本: v1.0
编制: Z-MAX 工程组 · 日期: 2026-10-13 · 适用版本: 5.50.B（Z-MAX 优化配置版；对应开发版 5.50.2）
唯一依据扫描生成器: `tools/delivery/gen_config_inventory.py`（从在役系统扫出，每个数可回读复核）

> 本清单逐项给出：**配置名 / 值或范围 / 唯一依据文件与键路径 / 单位 / 消费代码位置**。
> 凡在役系统扫描（扫描时点 **2026-10-13 07:37:17**）可得者标注扫描值；凡唯一依据无实测值者标注「**待实测**」并给出取数命令。
> 全量扫描件（机读）另存：`docs/deliverables/全系统配置清单_5.50.B.md` / `.json`。

---

## 1. 版本

| 配置名 | 值或范围 | 唯一依据文件与键路径 | 单位 | 消费代码位置 |
|:---|:---|:---|:---|:---|
| 界面品牌版本 | 5.50.1（开发工作区将升 5.50.2） | `tools/gui/update_checker.py` → `CURRENT_VERSION` | — | `tools/gui/studio.py` 品牌小字/窗口标题 |
| 版本号同步位 | 5.50.1 | `tools/gui/version_sync.py` → `zmax_ver` | — | `tools/gui/docs_sync.py`（`version`/`zmax_version` 两键） |
| VERSION.md 记载 | 5.50.1（最新条目） | `VERSION.md` 版本历史表首行 | — | 人工/交付文档引用 |
| git HEAD | `6462c27` | 仓库 git | — | `tools/delivery/gen_config_inventory.py` |
| 交付版号段 | 5.50.A / 5.50.B / 5.50.C | `docs/deliverables/版本策略_5.50.A_B_C.md` | — | 交付文档 |

---

## 2. 任务与场景

| 配置名 | 值或范围 | 唯一依据文件与键路径 | 单位 | 消费代码位置 |
|:---|:---|:---|:---|:---|
| 活跃任务 | **TASK-07-AOI**（生成时间 2026-10-13 07:31:46） | `config/ss_task_binding.json` → `active_task` | — | `tools/ss_task_bind.py` · `tools/ss_task_runner.py` |
| 任务总数 | 7 | `config/tasks/tasks.json` → `counts.tasks` | 条 | `tools/task_build.py` |
| 配方段总数 | 8 | `config/tasks/tasks.json` → `counts.segments_total` | 段 | `tools/ss_task_bind.py` → `segment_node_map` |
| 绑定工程画布 | 89 节点 / 184 连线 | `config/ss_task_binding.json` → `project.nodes` / `project.links` | 个 | `tools/gui/simulink_module.py` |
| 画布唯一依据文件 | `src/lerobot/engineering/flows/state_space_obs.json` | `config/ss_task_binding.json` → `project.canvas_file` | — | `tools/gui/flows.py` `save_canvas` |
| 画布结构指纹 | `652bfe663460ede0107bb6fa7cd54c9d`（结构指纹，剔除 `cfg_*` 挂载键） | `config/ss_task_binding.json` → `project.canvas_md5` | — | `tools/ss_task_bind.py` 幂等判定 |
| 段覆盖节点数 | 52 / 89（未覆盖 22） | `config/ss_task_binding.json` → `coverage` | 个 | `tools/ss_task_bind.py` |
| 场景 → 色标（插拔） | 绿 `#2e8b57` | `config/topics/scene_tags.json` → `colors.插拔场景` | — | `tools/ss_scene_switch.py` · `tools/sig_scene_tags.py` |
| 场景 → 色标（摆盘） | 蓝 `#1f6feb` | `config/topics/scene_tags.json` → `colors.摆盘场景` | — | 同上 |
| 场景 → 色标（AR） | 紫 `#8957e5` | `config/topics/scene_tags.json` → `colors.AR场景` | — | 同上 |
| 场景 → 色标（未分类） | 白 `#ffffff` | `config/topics/scene_tags.json` → `colors.未分类` | — | 同上 |
| 信号场景标数 | 插拔 4 / 摆盘 104 / AR 176 / 未分类 0 | `config/topics/scene_tags.json` → `counts` | 条 | `tools/sig_scene_tags.py` |

> 每任务交付指标（`config/tasks/tasks.json#tasks[].targets`）：`TASK-06-TRAY` 单颗CT ≤3.15s(PVT) · 成功率 ≥99%(PVT) · 取放精度 单边 ≤1mm/≤1° · 连续 ≥12 盘；`TASK-01-FW` 合格率 ≥99%。

---

## 3. 结构化流形 / 标定 / 健康度

| 配置名 | 值或范围 | 唯一依据文件与键路径 | 单位 | 消费代码位置 |
|:---|:---|:---|:---|:---|
| 主参数 M（尺度） | **3.643** | `config/calib/zmax_manifold.json` → `M` | 等效惯量尺度(无量纲) | `src/lerobot/manifold/metric_field.py` · `tools/config_to_M.py` |
| 度量维度 dim | **6** | `config/calib/zmax_manifold.json` → `metric.dim` | 维 | `src/lerobot/manifold/metric_field.py` |
| 度量模式 mode | **diag** | `config/calib/zmax_manifold.json` → `metric.mode` | — | 同上（`isotropic`/`diag`/`full` 三态） |
| 度量形状 G（diag） | **[10,10,50,10,10,10]** | `config/calib/zmax_manifold.json` → `metric.diag` | 无量纲（det G=1 归一） | 同上 |
| M 标定范围 | **[0, 8]** | `config/calib/zmax_manifold.json` → `_range` | 同上 | `src/lerobot/engineering/nodes/library.py`（主参数 M 节点） |
| 零回归开关 inertia | false（默认，零回归） | `config/calib/zmax_manifold.json` → `inertia` | — | `src/lerobot/manifold/metric_field.py` |
| 任务→M 尺度 | TASK-01-FW 3.643 · TASK-06-TRAY 4.423 · TASK-07-AOI 3.283 | `tools/config_to_M.py`（规则表 R1–R5） | 同上 | 画布节点「主参数 M」· `tools/engine_bus_publish.py` |
| 健康度定义 H | (1/κ)·λ_min | `config/calib/zmax_health.json` → `definition.H` | — | `src/lerobot/manifold/health.py` |
| 分级阈值 | excellent 0.5 · good 0.1 · warning 0.01 | `config/calib/zmax_health.json` → `grades` | — | `src/lerobot/manifold/health.py`（>0.5 优秀/0.1–0.5 良好/0.01–0.1 警告/≤0.01 危险） |
| κ 告警阈值 | 100.0 | `config/calib/zmax_health.json` → `kappa_warn` | — | 同上 |
| H 趋势判据 | `|slope|≤trend_eps` 稳定 | `config/calib/zmax_health.json` → `trend_eps`(1e-4) | — | 同上 |
| 相机内参 K | fx 394.0624 · fy 393.4724 · cx 318.4436 · cy 238.6584 | `config/calib/zmax_calib.json` → `camera.fx/fy/cx/cy` | px | `src/lerobot/calibration/` · AOI/AR 模块 |
| 相机畸变 dist | [-0.05392, 0.05710, 0.000344, 0.000952, -0.01932] | `config/calib/zmax_calib.json` → `camera.dist` | — | 同上（模型 plumb_bob） |
| T_base_cam（手眼） | **null（未标定）** | `config/calib/zmax_calib.json` → `T_base_cam.value` | m/rad | `tools/board_handeye_solve.py`（现场标定） |
| plane_z（台面高度） | **null（未标定）** | `config/calib/zmax_calib.json` → `plane_z.value` | m | 现场夹爪/塞尺量取 |
| cell_geometry.points | **null（未示教）** | `config/calib/zmax_calib.json` → `cell_geometry.points` | m | `tools/ss_geom_calib.py --record` |
| 工具负载质量 | 1.51 | `config/calib/zmax_calib.json` → `tool_payload.mass_kg` | kg | 力控/动力学 |
| 机器人自由度 | 6 | `config/calib/zmax_calib.json` → `robot.dof` | — | `config/robot/zmax_robot_spec.json` |
| 深度尺度（仿真专用） | 0.9616 | `config/calib/zmax_calib.json` → `depth_scale.value` | — | 仿真单目深度链（真机走 RealSense 米制/plane_z 回退） |

---

## 4. 数据总线（DDS / 状态空间）

| 配置名 | 值或范围 | 唯一依据文件与键路径 | 单位 | 消费代码位置 |
|:---|:---|:---|:---|:---|
| 总线节点数 | 89 | `zmax_data/dataspace/busdb.json` → `counts.nodes` | 个 | `tools/ss_bus_topics.py` |
| 总线信号数 | 271 | `zmax_data/dataspace/busdb.json` → `counts.signals` | 条 | 同上 |
| 总线报文数 | 16 | `zmax_data/dataspace/busdb.json` → `counts.messages` | 条 | 同上 |
| 合成 topic 数 | 89（每节点 1 个独立输出 topic） | `zmax_data/dataspace/busdb.json` → `counts.synth_topics` | 个 | `tools/ss_bus_topics.py` · `tools/gui/dds_canoe.py` |
| 按层节点分布 | L2 26 · L3 5 · L4 18 · L5 11 · meta 14 | `zmax_data/dataspace/busdb.json` → `counts.nodes_by_layer` | 个 | `tools/meta_moe_router.py` |
| 唯一依据连线数 | 182（verify 判定：连线不减） | `tools/verify_ss_bus_topics.py`（唯一依据连线 ≥182） | 条 | 判据脚本 |
| 话题注册表常量数 | 1（扫描值） | `src/lerobot/dataspace/topics.py` | 个 | `tools/dataspace_catalog.py` |
| 数据总线实时件 | `zmax_data/dataspace/live.json` | 扫描项 `数据空间.live` | — | `tools/gui/dds_canoe.py` |
| AR/AOI 信号数 | 6（扫描值，注册表另存） | `config/topics/ar_aoi_signals.json` | 条 | `tools/ar_aoi_bus.py` |

---

## 5. 相机与 AOI

| 配置名 | 值或范围 | 唯一依据文件与键路径 | 单位 | 消费代码位置 |
|:---|:---|:---|:---|:---|
| 臂上 D405（arm） | fps 29.91 · 帧龄 0.01s · 未卡死 | 流服务通道（扫描 `相机与AOI.流服务通道.arm`） | fps/s | `tools/cam_live_stream.py`（:8791/:8793） |
| 内置 RGB（local） | fps 5.0 · 帧龄 0.19s | 同上 `local` | fps/s | 同上 |
| MAXHUB（local2） | fps 25.66 · 帧龄 0.0s | 同上 `local2` | fps/s | 同上 |
| D405 深度图（depth） | fps 0.0 · 帧龄 1845.93s ·**卡死** | 同上 `depth` | fps/s | 同上（**待现场实测**：需唤醒） |
| 金手指检测（aoi_gold） | fps 0.21 · 帧龄 3.28s（工控机 OPT 10082） | 同上 `aoi_gold` | fps | `tools/aoi_link.py`（`PORTS.gf=10082`） |
| 表面检测（aoi_surface） | fps 0.21 · 帧龄 2.92s（工控机 OPT 10083） | 同上 `aoi_surface` | fps | `tools/aoi_link.py`（`PORTS.housing=10083`） |
| AOI 端口 10082 采集参数 | exposure 20000us · gain 8.0 · gamma 1.0 | 工控机 `192.168.23.23:10082` 回读（扫描 `相机与AOI.AOI端口.10082`） | us/dB | 工控机 AOI 程序 |
| AOI 端口 10083 采集参数 | us 80000（默认）· gain 1.0（当前） | 工控机 `192.168.23.23:10083` 回读 | us/dB | 工控机 AOI 程序（`D:\xspace\ultralytics_AOI\surface_exposure.json`） |

> AOI 工控机地址：`192.168.23.23`（扫描项标注）。
> **待现场实测**：深度通道帧率、10083 最终在役曝光档（唯一依据含「默认 80000us / 当前 gain 1.0」两值，现场以回读为准）。

---

## 6. 在役服务与端口

| 配置名 | 值或范围 | 唯一依据 | 单位 | 消费代码位置 |
|:---|:---|:---|:---|:---|
| 监听端口 | 8791 · 8793 · 8797 · 8888 · 8796 | 在役扫描（`ss -ltnp`） | — | —— |
| systemd 单元 | 20 个 active（含 `zmax-traj-ar` · `zmax-dds-*` · `zmax-engdb` · `zmax-station-gate` 等） | 在役扫描（`systemctl`） | 个 | —— |
| crontab | 12 项（磁盘红线 / L2 守护 / 安全看门狗 / 发布 / 隧道保活等） | 在役扫描（`crontab -l`） | 条 | `tools/tunnel_keepalive.sh` · `.hermes/scripts/*` |
| AOI 检测服务 | 10082 金手指 · 10083 表面 | `tools/aoi_link.py` → `PORTS` | 端口 | `tools/aoi_link.py` |
| AR 底图服务 | 8797 | `tools/tcp_ar_server.py` | 端口 | 控制台 3D 页「🥽 AR」 |

---

## 7. 运行环境（扫描值）

| 配置名 | 值或范围 | 唯一依据 | 单位 |
|:---|:---|:---|:---|
| 内核 | 6.17.0-14-generic | 在役扫描 | — |
| CPU | 32 核 | 在役扫描 | 核 |
| 内存 | 30 GB（可用 16 GB） | 在役扫描 | GB |
| 磁盘 | 396G 总 / 60G 可用（85% 已用） | 在役扫描 | GB |
| GPU | NVIDIA GeForce RTX 4060 Laptop GPU · 8188 MiB · 驱动 580.126.09 | 在役扫描 | MiB |
| Python | 3.11.15 | 在役扫描 | — |
| 工程库 | `data/database/zmax/zmax_engineering.db`（1.3 MB） | 扫描项 `状态空间工程.工程库` | MB |

---

## 8. 配置唯一依据文件指纹（扫描，2026-10-13 07:37:17）

| 文件 | 字节 | sha256_12 |
|:---|---:|:---|
| `config/ss_task_binding.json` | 32684 | 810489438c4f |
| `config/topics/ar_aoi_signals.json` | 11298 | 87db2f4edaec |
| `config/topics/scene_tags.json` | 10947 | 609384d6d081 |
| `config/mcd/match_matrix.json` | 10569 | c0975b334974 |
| `config/mcd/param_registry.json` | 72361 | 0a6974bf9714 |
| `config/mcd/zmax_mcd.json` | 73757 | fd176116ae74 |
| `config/cc_snapshot.json` | 23073 | 9c0da4a0cbe9 |
| `config/dds_cycle.json` | 1934 | 6f8166ed80e9 |
| `config/library_curation.json` | 7306 | f4d6337c42c0 |
| `config/task_state.json` | 3227 | f5bc01cf1230 |
| `config/task_state_ledger.json` | 14745 | 3246e8f68a35 |
| `config/task_state_manual.json` | 136 | 6b4a5f295ffa |

---

## 9. 待实测 / 待核项（诚实列出）

| # | 条目 | 现状 | 取数命令 |
|:--|:---|:---|:---|
| 1 | 活跃任务 | 扫描时点值 `TASK-07-AOI`（生成 07:31:46）；随现场激活变动 | `python3 -c "import json;print(json.load(open('config/ss_task_binding.json'))['active_task'])"` |
| 2 | 画布结构指纹 | 扫描值 `652bfe66…`（结构指纹，非文件 md5；文件 md5 `a6395a1f…`） | `md5sum data/database/zmax/sources/canvas/state_space_obs.json` |
| 3 | 全部 58 条 `perf.*` 指标 | **待实测**（唯一依据 `value` 为空） | `gui-venv311/bin/python -c "import json;d=json.load(open('config/platform/zmax_perf_spec.json'));print(sum(len(g['metrics']) for g in d['groups']))"` |
| 4 | 站点几何 `T_base_cam`/`plane_z`/`cell_geometry.points` | **未标定**（唯一依据 null） | `config/calib/zmax_calib.json` 对应键；`python3 tools/ss_geom_calib.py --check` |
| 5 | 深度通道帧率 | **0 fps / 卡死**（扫描值） | `curl -s http://127.0.0.1:8791/api/cams \| grep depth` |
| 6 | 10083 在役曝光档 | 唯一依据含默认 80000us / 当前 gain 1.0 两值，**现场以回读为准** | 工控机 `GET http://192.168.23.23:10083/exposure` |
| 7 | 各层「模型是否真在回路」 | **待核** | `python3 tools/audit_full_chain.py` |

---

## 10. 复核方式

```bash
# 重新扫描生成全系统配置清单（每个数可回读）
gui-venv311/bin/python tools/delivery/gen_config_inventory.py --ver 5.50.B
# 产物: docs/deliverables/全系统配置清单_5.50.B.md / .json
```

> 本文档中的配置值均可由上述命令或对应唯一依据文件键路径回读复核；扫描时点不同，动态项（活跃任务/帧率/指纹）以当次回读为准。

---

*本清单所有配置值来自 2026-10-13 在役系统扫描与工程唯一依据；未实测/未标定项一律标注，不作推测。*
