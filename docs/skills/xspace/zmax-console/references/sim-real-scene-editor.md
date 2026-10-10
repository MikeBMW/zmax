# Sim&Real 场景编辑器 + 实时数据条 + 控制台数据同步

适用: 改控制台场景页/数据集页/模型引擎页/监控页; 给页面挂实时只读数据; 场景真源 data/scene/* 的读写。

## 1. 页面改名与定位
- 首页卡/页/导航: `插拔场景/Z700` → **`Sim&Real`**（副标题「仿真 · 真机 同一场景」, 描述「对象·标记·轨迹·保护围栏 可编辑 / 建图·AR 标记 · 地图同步」）。老倪明确: 描述里**不要再出现 Z700**。
- 类名仍是 `PluggingSceneModule`（改类名会牵动导航/别名表, 只用文案替换）。带旧名处: 首页卡列表、页 super().__init__、导航 names 列表、别名元组、代码注释。
- 原页只有 L2/L3/L4 **产品形态对比**（营销内容, 读不到真实场景、不能改）= 老倪说的「显示功能不对」。修法: 真实编辑器**置顶**, 原内容下移为参考, **不删**。

## 2. 场景编辑器分层（单一写路径）
- UI: `tools/gui/sim_real_page.py` `build_body()` → studio.py 里 `bl.addWidget(_sr_build())`。四张表: 对象/现场标记/保护围栏/自定义轨迹; 顶部一条真源路径+条数+采集时间。
- 数据层: `tools/scene_edit.py`（GUI 与参数中心只经它, 绝不自己写 JSON）。真源 `data/scene/{objects3d,overlay_spec,traj_display}.json`; **`scene_state.json` 是运行中的实时感知状态, 只读禁写**。
- 写纪律: 带时间戳备份 → 唯一 `.tmp` 原子 `os.replace` → 回读核对 → 失败回滚; load-modify-dump **只动自己的键**, 保留一切不认识的键, 从不改 ts/updated_at。围栏硬校验(多边形≥3点 / z_min<z_max / 体积>0 / 坐标 ±3m, 越界拒写)。
- **`overlay_spec.json` 是热文件**: 8793 叠加服务(l5_live_mark)每轮刷 ts/updated_at/l5live/cameras ⇒ **拿 md5 前后比来验「dry 有没有写」是错的**（md5 必变）。要验写纪律就 `ZMAX_SCENE_DIR=<沙箱>` 复制副本再测。
- 数据层自带的坑: 写权限探针**曾在真文件 traj_display.json 上做并覆盖了它**（内容逐字重建、mtime 丢失）。权限探针一律在临时文件上做。
- **同签名派发表 ⇒ 每个 kind 都要各测一遍**: `NORM = {"objects":…, "markers":…}` 统一按 `(data, existing, items)` 调用, 但 `norm_object` 只接 2 个参数 ⇒ **objects 的 add/update 全挂, markers 却正常**。只测了一种 kind 的交付看起来是全绿的。改共用签名后必须重跑全部 kind: `add/update/rm` × objects/markers/fences/trajectories。

## 3. live_strip / LiveTable 使用契约
- `fmt` 回调**必须返回三元组** `(summary, detail, ok)`: summary 显示在条上, detail 进 tooltip, ok=False 时红字且**保留上次值**。返回裸字符串 ⇒ 页面显示「格式化失败: too many values to unpack」。
- `LiveTable(title, cmd, fmt, rows, interval_s, max_rows)`: `cmd` 是参数表(解释器自动选 gui-venv311), `rows(payload, err) -> (cols, rows)`。表要 `_build_table_into(layout)` 才能上屏。
- QProcess 用 `MergedChannels` ⇒ 工具写 stderr 的告警(如 `[redaction] 断言 PASS`)会混进 JSON 前 ⇒ 解析必失败。已修: 先整体 `json.loads`, 失败退一步取「第一个 `{` 到最后一个 `}`」再解析, 仍失败才报错(错误红字显示, 不掩盖)。新工具**日志写 stderr, stdout 保持纯 JSON**。
- QProcess **不要挂 parent**: 父控件先析构会 delete 掉在飞的进程 → `QProcess: Destroyed while process is still running` → **Python abort (core dump)**, 用户侧就是「点一下换页控制台没了」。改成 `self._proc` 显式持有 + `closeEvent`/`stop()` + `sender()` 取回。
- 挂载点: 数据集页(数据资产表) · 模型引擎页(GPU/模型表) · 监控页(远程同源表) · 架构页(架构数据条)。

## 4. 远程监控同源（产品大屏数据源）
- `tools/remote_monitor_aggregate.py`: 18 端点(本机 8791/8793/8794/8795/8796/8798 · Orin 8792 · 工控机 AOI 10082/10083 · ECS 公网 7) 实采 → `{endpoints:[{name,url,owner,ok,status,data_age_s,stale,fields,err}], same_source:[{fact,sources,consistent,tol,note}]}`。凭据正则脱敏 + 落盘/打印前硬断言(已知口令逐值 grep 输出命中 0)。
- 同源判定必须**显式容差**且**新鲜度前置**: 源数据龄 >10s 判 `不可比`(consistent=None), 不允许把过期快照算「一致」—— 瞬时指标(GPU 利用率)尤其如此。

## 5. 版本同源体检
- `tools/verify_version_sync.py` → 9 处同步点逐个 file:line + 远端 tag/Release + GUI 显示; exit 1=有偏差。
- 会漂的不是版本号本体, 而是**没人同步的显示点**: GUI 状态栏/关于框的陈旧字面量、`update_checker.REPO` 指向另一个仓(其 latest 更低 ⇒ 自动更新误报「发现新版本」并去下别的仓的产物)。改版本时把这些一起扫。
- 「xspace 版本」= GUI 品牌名 XSpace Studio(= Z-MAX 控制台)的版本号 = Z-MAX 版本线; 上游旧仓/旧路径已不存在。**不要**拿 external 历史仓(另一条版本线)当对齐目标。
- 判据已进 `tools/run_gui_verifiers.sh`: scenesim / version_sync / remote_monitor。

## 6. 控制台改码/重启/接线纪律
- **改码攒批, 一次重启**; 重启方式 `cd tools/gui && DISPLAY=:0 QT_QPA_PLATFORM=xcb <venv>/bin/python studio.py`, 起来后验: 进程在 + `xdotool search --name "^zmax$"` 有窗 + 启动日志 `grep -c Traceback` = 0。
- **新页面一律做成独立模块**(如 `sim_real_page.build_body()` / `live_strip`), 在 studio.py 里用 `try: from X import build_body; bl.addWidget(build_body()) except Exception as e: 页面内显红字`, 绝不把逻辑塞进 studio.py 本体。好处: 模块缺失/报错只让那一页降级可见, 不会拖垮控制台; 并行作业时也不会和别人改同一个文件打架。
- 并行派活时明确告诉子代理「**不要碰 studio.py / simulink_module.py**」, GUI 接线由主节点收口。
- 杀 GUI 一律: 先 `pgrep -f "studio[.]py"` 看清 PID → 写脚本 `kill <PID>`。`pkill -f "...studio.py"` 会**连自己的 shell 一起杀**(命令行文本含该模式, exit -15)。

## 7. 画面证据（无视觉工具时的取证口径）
- 真机画面: 8793 的 `*/snapshot/*.jpg`(overlay_arm / overlay_local / depth) 与 `*.mjpg`(aoi_gold/aoi_surface) 才是图源; `/snapshot?cam=arm` 这类查询参数写法 404。取证 = HTTP 200 + 字节数 + `file -b` 认出 JPEG/MJPEG; 判读画面内容要靠用户目检, 不要替他说「画面正常」。
- 仿真画面: `reports/ss_episode_latest.mp4`(ffprobe 出分辨率/帧数/时长) + 每次 rollout 的 `tr["key_frames"]`(阶段关键帧图像)。
- 造数据入口(实测定时): `MUJOCO_GL=egl MUJOCO_EGL_DEVICE=0 <venv>/bin/python tools/l5_plan_and_gen.py --n N --steps 400 --out <h5> --seed S --vision 1`(= L5 定方向·造数据: 规划器出变体 → 引擎真跑 → 落 h5)。量级: 8 变体 → 3,116 帧 / 65s。产物落 `zmax_data/stable-wm-cache/datasets/*.h5`, **数据集管理(`dataset_inventory.py`)的 generated 类里能直接看到**, 不需要另建入口。
