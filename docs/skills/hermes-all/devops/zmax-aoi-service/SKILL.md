---
name: zmax-aoi-service
description: Use when 调用产线 AOI 检测服务(10082 金手指/10083 表面).
---

# 产线 AOI 检测服务 (Z-MAX, 工控机 192.168.23.23)

与 Orin 同网段(192.168.23.x)。跑两份 Flask 程序「Z-MAX 表面检测 AOI 程序 · 优化版 v3」,
**端口→模型映射**决定检测类型。

## 🆕 表面判据图 (10083 v12.1, 2026-09-30 老倪现场要求)

原话: 「表面检测也要增加判据图, 你要将光模块**整体切割出来**, 调整好**水平状态**; 类似金手指的判据图,
**只要光模块的部分, 不要背景**; 现在有点倾斜, 你要修正; 增加**判据图 和 整板原图 两个按钮**;
你要修改工控机的程序, 修改 v12 版本」。

- 工控机 v12.1 **→ v12.2** 新增 `GET /picture?kind=judge` = 只切光模块 + 调平 + 去背景, 定尺 **1400x300**;
  落盘 `Surface_Judge_W1400_H300_No_*.png`; `/crop_info` 多出 `judge_ok` / `judge_mode` / `judge_rot_deg` /
  `judge_bbox` / `judge_cover` / `judge_ms` / `judge`(完整 meta, 含 `right_edge_x`/`right_edge_src`/`thick_med`/`band_y`);
  `/last_result` 的 `judge`(人看的) 与 `model_input`(模型吃的) **明写区分**。
- **v12.2 两处关键修正**(2026-09-30 像素级反解 + 真机复核):
  1. **模块右界改为数据驱动认"上边缘竖直台阶"** —— 原来固定用 ROI 右界(1815), 而那儿上下都是 255 无任何边,
     判据图右端必然出现"切在亮料中间"的断口, 且多带入一块夹具。实测台阶在 **x≈1503**
     (长条上边缘在此竖直上跳 35px、下边缘下掉 65px、右侧那块高 277px vs 长条 175px、底部磨砂麻点 vs 长条纯 255、
     并连到带螺钉/贴纸的底座) ⇒ 模块本体止于此。改后模块宽 **1453 → 1156 px**, 右端之后为纯背景。
     方向性很重要: 只认**向上**的台阶(y_base − y_top ≥ +18px 且持续 ≥8 列), 左端那块更矮的"舌尖"不会误触发。
  2. **纵向收带**: 掩膜限制在 [上边缘基线 −12, 基线 + 实测中位厚度×1.3] —— 否则 bbox 被那块 277px 的料撑满 300px 高、
     白留边浪费分辨率。
  3. 画布 1600→**1400x300**, 缩放 `min(..., 1.0)` **只缩不放**(不插值放大 ⇒ 保像素真实)。
- **模型吃的 1280 全幅 letterbox 一字未改** —— 改"人看的图"绝不动"模型吃的图"(沿用金手指 v7/v10 铁律)。
- 4060 页面(表面格) 两条流: `/aoi_surface.mjpg` = 判据图(`kind=judge`, **本地零加工**) ·
  `/aoi_surface_raw.mjpg` = 整板原图(低频 `kind=origin`); 按钮「判据图 / 整板原图」; 模型输入看 `/aoi_surface_modelin.png`。
- 算法/参数/验收数字/失败闸门见 `references/surface-judge-v121.md`; 离线验收脚本 `~/aoi_v4/test_v12_1_judge.py`(21 项)。

## ⚠️ 部署或验收前必做: 先杀干净重复实例(否则"假失败 → 自动回滚")

- 现象: `POST /capture_detect` → **HTTP 500 `图像抓取失败`**, 但同一时刻 `GET /picture?kind=judge&grab=1` → 200 正常。
- 原因: 相机**独占**, 而工控机上**两个启动机制**都会拉起 AOI 程序 —— 保活任务 `ZMAX_AOI_KeepAlive`(用
  `venv\Scripts\python.exe`) 与部署器/agent 侧(用 PATH 里的裸 `python` = Python310); 程序启动要 ~10s 才 bind,
  这期间端口探测看到的是"没人应答" ⇒ 两个机制各起一份; Windows **SO_REUSEADDR** 让第二份 bind 也"成功"
  ⇒ 两份并存, 相机只归先抓到的那份。**两份都能收连接**(OS 会在同端口两个 socket 间分流) —— 所以会出现
  "一部分接口 200、另一部分 500"的诡异组合(实测 judge 流 200 而 origin 抓帧 500), 别据此以为是某个接口的 bug。
- 处置: 部署/验收前先 `Stop-Process` 掉所有匹配 `cam_*_10083*` 的 python, 只起一份, 并**在同一分钟内立刻抓一帧占住相机**
  (否则保活/agent 那一分钟内的补起会抢走相机); 正常态(只剩一份且 `/storage` 200) 不要手动再起第二份。
- 根治方向(未做, 已问用户): 让**只有一个启动者**(给保活或 agent 侧去掉重复启动), 或程序启动时用
  `SO_EXCLUSIVEADDRUSE`/锁文件独占 ⇒ 第二份 bind 失败即自行退出。

### ⚠️ 部署器的验收探针**必须带等待**(2026-10-08 实测: 两条误回滚)

金手指 v21 上线时连续两次"部署成功→验收失败→自动回滚", **两次都不是新版本的问题**, 而是部署器的探针没有等待:
1. `POST /capture_detect` 只打**一次** —— 撞上"冷启动首抓必失败"(该路由自己会重连重试, 但要几分钟才 200)
2. `/storage` 在重启命令后 **~25s** 就查 —— 实测要 **~89s** 才 LISTEN ⇒ 拿到 `HTTP 0`
⇒ 已入码修复(`tools/aoi_remote_deploy.py`): `/storage` readiness 轮询 **≤200s**、`capture_detect` 轮询 **≤180s**,
与既有的 `/last_result`(≤45s) 同口径。**新写任何 AOI 验收断言前, 先问自己"服务这时起来了吗"**。
判据: 只要出现"一部分接口 ✅ 另一部分 ❌"或"HTTP 0/500 但同一时刻别的口 200", 先怀疑**重复实例 + 探针过早**, 不要怀疑新版本。

### 🔎 一条命令拿工控机 AOI 全貌(免引号坑, 2026-10-08 定稿)

PowerShell 里裸写 `-match python` 会被 PS 解析成缺值表达式 ⇒ 把脚本 **UTF-16LE 转 base64** 用 `-EncodedCommand` 调, 彻底绕开嵌套引号:

```bash
B64=$(python3 - <<'PY'
import base64
ps = r'''
$ErrorActionPreference='SilentlyContinue'
$p='D:\\xspace\\ultralytics_AOI\\cam_finger_10082_work_v20.py'
Write-Output ('FILE ' + (Get-FileHash $p -Algorithm SHA256).Hash + ' size=' + (Get-Item $p).Length)
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'cam_(finger_10082|surface_10083)_work' } | ForEach-Object { Write-Output ('RUN {0} :: {1}' -f $_.ProcessId, $_.CommandLine) }
Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -in 10082,10083 } | ForEach-Object { Write-Output ('PORT {0} PID {1}' -f $_.LocalPort, $_.OwningProcess) }
Get-Content 'D:\\xspace\\ultralytics_AOI\\v5f.log' -Tail 10
'''
print(base64.b64encode(ps.encode('utf-16-le')).decode())
PY
)
gui-venv311/bin/python tools/station_cmd.py "powershell -NoProfile -EncodedCommand $B64" 130
# 回执在 ~/zmax/zmax_data/agent_hub/out/<epoch>.txt, 用 grep -a 取
```

**"磁盘文件已是新版、跑起来还是旧行为"怎么判**: 比对 `FILE <hash>` 与 `RUN` 行的**启动方式** ——
带 `cmd /c cd /d D:\xspace\ultralytics_AOI && venv\python` 的是保活那份(工作目录正确),
只有裸 `Python310\python.exe cam_xxx_work_v20.py`(无 `cd`)的是 agent 侧那份,**它的工作目录可能是别处的旧副本** ⇒
端口被它占住时, 产线跑的就是旧代码(判据图 meta 字段能直接看出来: v21 有 `n_keys/width_uniform_px/lattice_pitch_px`, v20 是 `kept_rows/x_trim/k`)。
处置顺序: 杀全部匹配进程 → **立刻**只起保活那份 → **同一分钟内抓一帧占住相机**(否则另一机制的补起会抢走)。

### 🆕 金手指判据图 v21 口径(2026-10-08 老倪现场逐字要求, 已交付)

老倪原话串: 「不要歪斜 · 右侧那块不是金手指要去掉 · 只显示金手指且显示成矩形 · 其余全黑 · 不要曝光太亮」→
「只是A, 但要剔除上边的一大横条; 金手指是跟钢琴按键一样, 一个小竖线, 没有一大横条」→
「金手指为什么宽度不一样呢? 实际的金手指宽度很均匀啊」.

落地口径(程序 `cam_finger_10082_work_v21.py`, 只改判据渲染, **模型输入零改动**):
1. **按键 = 列方向周期性**: 行窗口内亮段 ≥6 且间距抖动 <25% 判为按键行; 行亮占比 ≥0.85 = 满宽横条 ⇒ 剔除
2. **横条只截断键带起点, 不打洞**(中间挖行会把一排键切成上下两段)
3. **等宽栅格**(宽度为什么不一样的正解): 由可靠键求出**一个间距 + 一个相位 + 一个中位宽度**, 按栅格铺,
   落在栅格上的结构全部补回(被离群规则误删的暗键也回来) ⇒ 现场帧 **20 根键 × 42px 全等 · 间距 71px**
4. 自动增益(饱和 0.0%, 原帧 25.9%) + 画布 **900x332** 纯黑居中
- 键数别用亮阈值硬数(会数出 26 虚高): 键宽 × 根数 ≈ 条体宽度 才自洽
- 离线复跑: `cd ~/zmax/zmax_data/aoi_v4 && ../../gui-venv311/bin/python test_v21_routes_offline.py`
  (路由级 E2E: 判据图口径 + 取图口 md5 == /last_result.model_input_md5, 直接硬证模型输入没变)

### ⚠️ v21 会**静默回退成旧 960x960 口径** ⇒ 现场看到"右侧那块方块还在" (2026-10-08 晚实测)

现象: 老倪说"金手指还是没改好, 右侧有方块区域, 不是金手指"。**版本其实上去了** (文件 sha 与交付件逐位一致 +
日志是 v21 独有打印 + 现役页面确实出 900x332/黑占比 0.84~0.86) —— 但**每 ~20 帧有 1 帧判据渲染失败**, 那一刻
`GrabAndSaveImage` 里 `if judge is None: judge = crop` 把 **960x960 旧口径**(右侧灰块没切) 端到页面上 ⇒ 看上去像"没改好"。

- **失败判据必须用对**(我第一版判据踩坑): `/crop_info.judge` 里 `out` / `kept_rows` **永远是 null**(别名键名写错:
  `met["out"]=met.get("out_size")` 而 v21 meta 里没有 `out_size`; `kept_rows=met.get("key_rows")` 实际叫 `n_key_rows`/`key_row_span`)
  ⇒ **别拿它们判成败**。可靠判据: **`fix_hw`(或 `k` / `x_trim`) 为 None = 渲染失败**(render_judge 失败时提前 return, 整个 v20 别名块都没写)。
- 工控机日志实测: 失败行 `⚠️ 判据图渲染失败(too few keys after detection (1)) ⇒ topview 回退为规整图口径` +
  `【落盘】... Finger_TopView_W960_H960_No_375.png (960x960)`(成功那版是 `W900_H332`)。整份日志 98 次失败。
- **失败帧指纹**: `judge.sat_before≈0.63`(正常帧 **0.21~0.38**) · `【金手指截取】` 的**残余倾角 7.5~8.0 px/1000**
  (正常 0.2~0.7) ⇒ 键行带被过曝区撑开(`_v21_render` 里 `ky0=min(y0)/ky1=max(y1)` 把**所有命中窗合并成一条大带**,
  多一个杂窗就把带子撑进过曝区) ⇒ 列方向门限整体通过 ⇒ 合成 **1 根键** ⇒ `<3` 放弃。
- **复现前提(必须全满足, 否则测不出)**: ① 数值栈 = 工控机的 **py3.10/cv2 4.10.0/np 1.26.4**
  (`uv pip install --python <v>/bin/python numpy==1.26.4 opencv-python==4.10.0.84 flask`;
  本机 `gui-venv311` 是 **cv2 5.0.0**, 同一份代码/同一帧会给出不同命中的窗口 ⇒ 不能用来断言);
  ② **`templates/gf_strip_template.png` 要在模块旁**(快照目录里没有 ⇒ 静默走 legacy 几何, 结果完全不同);
  ③ 用 HTTP `?kind=origin&grab=1` 拿到的帧**测不出失败** —— 实测 39 帧(cv2 5.0)与 39 帧(cv2 4.10)全过,
  sat_before 只到 0.383 ⇒ **失败帧从 HTTP 拿不到**, 只能给工控机加"失败时把输入帧+完整 meta 落固定文件"的**有界取证**。
### ✅ v22 (2026-10-08 晚) 已上线并真机验收: 失败率 20.6% → 0

- **真根因(实测, 非推测)**: 过曝的金属外壳区里会出现一个"命中窗"(y≈1200) → `ky1 = max(y1)` 把**合并键行带**
  从 [690,819](130 行) 撑到 **[680,1249](≈570 行)** → 带内 63~67% 像素 ≥250 → 列方向亮度剖面整段通过
  → 键列塌成 **1 根**(需 ≥3) → `too few keys after detection (1)` → 老代码 `if judge is None: judge = crop`
  **静默回退旧的 960x960 拉伸图**(右侧灰块没切) = 现场"右侧有方块区域, 不是金手指"。
- **频率/指纹**: 高频守帧(150s)实测 **131 帧 27 失败 = 20.6%**; 失败帧 `judge.sat_before` **0.635~0.668**
  vs 正常帧 **0.221~0.338**(两簇完全分离, 可直接当判据用)。
- **修法(v22)**: ① 失败时端**上一张好判据图 + 红条(帧龄/原因)**, 绝不再端 960x960;
  ② 失败时**逐窗 + 放宽门限**重试(第 1 遍仍是 v21 原口径 ⇒ 成功帧像素逐位不变; 重试结果过验收闸
  `sat≤0.55 / 键≥5 / 黑底≥0.45` 才采纳, 防"救回一张错的"); ③ 失败时**有界取证**
  `debug_judge_fail_last.png/.json`(输入帧+完整 meta+命中窗, 覆盖式不增长);
  ④ `/crop_info.judge` 补 `state/ver/why/err/n_keys/attempt` + 顶层 `judge_ver`(原来失败时 11 个别名全 null ⇒ 故障隐形)。
- **真机验收口径**: `judge_ver=v22-gold-judge-20261008`; 100s/77 帧 ⇒ 第1遍 ok 48 + 重试救回 29 + **stale 0**,
  页面那张(`/picture?kind=crop`)**77/77 = 900x332**; 改前约 20% 的帧是 960x960 旧口径。
- **捞真失败帧的正确姿势(可复用)**: 轮询 `/crop_info`, 判据 `judge.out is None` ⇒ 立刻
  `GET /picture?kind=origin`(**不要带 `grab=1`** —— 不带才返回内存里那一帧) 存盘。
  注意下一次 grab 会覆盖内存帧 ⇒ 约只有 1/3 的尝试能捞到真失败帧(其余是好帧, 别当成矛盾)。
- **离线复现/验收环境**: 必须用工控机的数值栈
  (`uv pip install --python <v>/bin/python numpy==1.26.4 opencv-python==4.10.0.84 flask`) +
  `_stub/`(SciCam 桩) + `templates/gf_strip_template.png` 在场; 本机 `gui-venv311` 是 cv2 **5.0.0**, 结论会不同。
- **⚠️ 相机曝光/增益不要顺手改**: 程序里 `EXPOSURE_US=10000.0`/`GAIN_DB` 是固定的, 改它 = 改**模型吃的那张图**
  (违反"模型输入绝不动"铁律)。v22 已在过曝帧上自愈; 真要根治过曝, 须带"模型召回前后对照"单独评估。
- **更正**: `gold_judge_v21_exposure.json` **不是部署漏项**(此前我判断有误) —— 全仓 grep 只有独立渲染器
  `tools/aoi/gold_judge_rect_v21.py` 读它, **app 里没有任何引用**。

### ⚠️⚠️ 页面看到的 ≠ 工控机判据图: 金手指格是「口径感知」的 (2026-10-08 晚 老倪「金手指也没变化啊」)

- 本机 `tools/cam_live_stream.py` 的 `_aoi_gold_worker` 默认口径 **`canonical`** = 取工控机 **`kind=origin`**
  原图 → **本机自己加工**(原比例 + 去倾角 + `vstretch=3.0` → 定尺 900x332)。这张**没有黑底**,
  把金属外壳白块/背景一起带进画面 ⇒ 现场"右侧有方块区域, 不是金手指"。
- 工控机的判据图是 **`kind=crop`**(纯黑底 + 等宽键, 黑底占比 ~0.76)。**只有口径 = `same` 时页面才直接显示它**(本地零加工)。
- 实测(同一时刻): 页面 `/aoi_gold.mjpg` 900x332 `black=0.000 sat=0.183` vs 工控机 `kind=crop`
  900x332 `black=0.760 sat=0.000`, 平均像素差 **144** ⇒ 两张完全不同的图。
  ⇒ **结论: 只改工控机的判据程序, 页面不会有任何变化** —— 必须同时确认口径(否则现场说"改了没变化"时先查这个)。
- 工控机 app **没有 `/caliber` 路由(实测 GET /caliber = 404)** ⇒ `_aoi_caliber()` 永远读失败 → 回落 `canonical`;
  页面也没有口径切换按钮 ⇒ 那个"可切换"实际是死的。
- 处置: `_aoi_gold_worker` 默认改成 **`same`**(直接用 `kind=crop`, 本机零加工);
  环境变量 **`ZMAX_AOI_GOLD_CALIBER=canonical`** 可回老街口; 重启本服务前存证: 页面 `black 0.000→0.782`,
  与 `kind=crop` 平均像素差 **5.65** = 同一张(残差只是 JPEG 质量差)。
- cam_live_stream 是**手起进程**(gnome-terminal scope) ⇒ 重启必须走官方脚本
  **`bash tools/start_station_stream.sh`**(按端口找 pid 杀、按卡名解析相机、抬 fd 上限、日志到 `/tmp/zmax_scene_overlay.log`);
  **不要**内联 `pkill`/手动 setsid 重放(会杀自己 shell、还会走成另一份日志路径)。
- 口径差异要知道: 工控机判据图**不拉伸短边**(键高仅 78/332 px, 上下留黑边), 老街口是 3× 纵向拉伸(看着更大)
  ⇒ 切口径后现场可能说"怎么变小了"; 要放大就做**纯显示**放大(不动口径)。

## 端点（唯一路由, 无需参数/鉴权）

| 端口 | 模型 | 相机 SN / 型号 |
|---|---|---|
| **10082** | `gf` = 金手指 | D265250070 「金手指检测相机 OPT-CC1-GG50」 |
| **10083** | `housing` = 表面 | D265250099 「表面检测相机 OPT-CC1-C050-GG3-00」 |

```bash
curl -s -X POST http://192.168.23.23:10082/capture_detect   # 实测 0.53s
# {"code":200,"msg":"success"}
```

## 语义（关键）: 纯异步, 秒回

1. 相机**常驻**(首次请求初始化, 之后只 Grab)
2. 拍照 → 存到工控机的 `./goldfinger_images/`(10082) 或 `./surface_images/`(10083)
3. **立即返回** `{"code":200,"msg":"success"}`（不阻塞产线节拍）
4. YOLO 推理在后台线程跑, **检测结果只打印在工控机终端** ✗ API 不返回结果

## 所以: 要拿到"检测结果"必须补一条通道

- 现状: 结果(缺陷数/OK-NG/类别/conf/bbox)只出现在 .23 的终端 stdout ✗
- 可选: ①请 web 侧在同一个 Flask 里加结果端点(如 `GET /last_result`, 把 worker 的最近结果存全局) ②或读 `./goldfinger_images/` 里的原图自行推理
- 本机(4060)与 Orin 都只能**触发**拍照检测, 拿不到判决 —— 这点要在对外表述里说清, 不能假报 OK/NG。

## 10082 金手指"规整截取" (v4 模板法, 2026-09-20 实测)

### 老版(v2/v3)截取为什么"歪歪扭扭" —— 三个叠在一起的原因
1. **固定透视窗** `src=[[400,1000],[2000,1000],[2000,1250],[400,1250]]` 与实际金手指条对不上:
   条中心 y 在 **1008~1450** 之间漂移(≈400px),条本身还带 **+0.6~1.0° 倾角** → 窗子时上时下地切过条。
2. **输出尺寸被静默拉成原图尺寸**: `warp_goldfinger_topview()` 里 `out_w=None → out_w=img_w`,
   调用处没传 out 尺寸 → 物理上是 1600x250 的窗被拉到 **2448x2048**(横向1.53x/纵向8.2x拉伸)。
   文件名却一直写 `W1600_H220`(**名字在撒谎**, 内容从来不是 1600x220)。
3. 真值口径: 金手指条实测 **1441x59 px @(1200,1222)**, 倾角 +0.60°(质心线残差 0.11px)。

### v4 做法 (模板法)
- 模板 = 参考真图去倾斜后的**条 ROI**(居中存放): `templates/gf_strip_template.png` + 同名 `.json`(条几何 sidecar)。
  相机/产品换了就重做: `python gf_template.py <新参考图>`
- 运行期三段: ① 1/4 尺度多角度粗搜(±3°, 步0.5°) → ② 1/1 尺度局部窗精修(角度±1°步0.1° / 尺度 0.97~1.03)
  → ③ **角度扫描精修**: 直接以"裁剪图里条质心线斜率"为目标度量扫 ±1°(热启动 ±0.25°), 把斜率压到 ≈0
  → ④ 单次仿射映射到规范化画布(保比例: 1600xauto, 条固定落在 x[48,1552] / 行[43,127])
- 交付物: `cam_finger_10082_work_v4.py` + `gf_crop.py` + `gf_metric.py` + `templates/`
- 新端点 `GET /crop_info` = 最近一次裁剪的 score/残余倾角/线残差/金覆盖率/角度扫描曲线; 终端每个周期打印同一组指标

### 实测(5 张真图, 同一批 goldfinger_images)
| 方案 | 条质心线斜率 px/1000 | 残差px | 备注 |
|---|---|---|---|
| v3 现状(拉 2448x2048) | 18.6 ~ 37.0 | 122 ~ 152 | 歪 + 8.2x 纵向拉伸 |
| v3 按设计(1600x220) | 2.4 ~ 7.2 | 10.8 ~ 17.6 | 只是不拉伸了, 仍是固定窗 |
| **v4 模板法(保比例)** | **0.09 ~ 0.89** | **5.0 ~ 5.4** | score 0.954~0.990, 冷启~500ms/热启 130~143ms |

### 踩过的坑 (再做同类截取直接抄)
- **HSV 金色掩膜在本机台上不可靠**: 宽阈值 `(8,60,50)-(45,255,255)` 把无关黄色区域也选进来(全图 1.4~2.4% "金"像素里约一半是杂的),
  严格阈值 `(15,120,120)` 只剩 **10 个像素** → **别把 minAreaRect/颜色掩膜当定位主手段**, 只能当兜底。
- 用"最大轮廓"量条会随闭合核大小跳变(核(61,5)→1559x164 / 核(41,5)→1455x98); 改用**逐行/逐列剖面 + 分位数**定边界稳得多。
- "顶边"当规整度判据太脆(顶边残差 ~11px, 含焊盘本身的台阶); 改用**质心线**(每列金像素质心行)残差 ~5px, 斜率也亚像素级。
- `cv2.getAffineTransform(dst, src)` 再 `warpAffine`(不带 `WARP_INVERSE_MAP`) = **双重反变换**, 结果裁到空图/黑图。
  标准写法是 `getAffineTransform(src, dst)` → `warpAffine`。
- **平纹理会给假高分**: 模板若大部分是平坦背景, NCC 处处 ≈0.99 → 出现 "score 0.988 但裁剪里一个金像素都没有" 的假成功。
  终判据必须是**裁剪内的实质指标**(金覆盖/质心线有效性), 不能只看 score。
- 首次别把"角度闭环"做成符号猜测试探(会发散: 角度从 0.6° 跑到 -2.6°, 斜率反而变差); 改成**扫描目标度量取最小**是确定性的。

### ⚠️ 风险 + 上线方式(必须与现场确认)
检测模型 `gf: bestgf05088.pt.enc, imgsz=960, conf=0.30`(config.yaml) 的**训练输入几何未知**;
v4 输出 1600x172 与 v3 的 2448x2048 分布差异很大(焊盘在 960 输入里约 56px vs 原 273px)。
⇒ 若召回下降, 用 v4 口径的图重训/微调该模型(数据闭环有这条路)。

**通道必须保持 10082**(产线 HMI/PLC 打的就是它), 且 **相机是独占设备 —— v3 与 v4 不能同时跑**
(同一台相机 SN,D265250070,第二个打开会失败)。所以是"切换"不是"并行":
1. 在 v3 的终端 Ctrl+C 停掉(或 `netstat -ano | findstr :10082` + `taskkill /PID <pid> /F`)
2. `python .\cam_finger_10082_work_v4.py`(默认就是 10082; 程序启动会做端口占用自检, 被占直接报错退出)
3. `curl -X POST http://127.0.0.1:10082/capture_detect` → `{"code":200,"msg":"success"}`;
   `curl http://127.0.0.1:10082/crop_info` → 本次裁剪的 score/残余倾角/线残差/金覆盖
4. 同一批料比 v3/v4 的检测判决与图; 不行就 Ctrl+C 回滚启动 v3(文件都在, 零改动)
- v4 已把"通道→模型"映射按**实际运行端口**注册, 所以换端口自测也不会再报 400(但产线仍用 10082)
- 换产品/换相机后重做模板: `python gf_template.py <新参考图>`

## 区域检测 → 机械臂视觉伺服对准 + 自动对焦 (2026-09-20 交付)

### 接口语义 (现场要求, 别记错)
| 接口 | 语义 |
|---|---|
| `GET /picture` | **原始图** 2448x2048 (默认; `?kind=crop` 才是规整裁剪图) |
| `GET /crop_info` | 裁剪结果指标 (score/残余倾角/线残差/金覆盖/高亮占比) |
| `GET /region?grab=1` | **原始图坐标系的金手指区域**(定向框/四边形/外接框) + 对焦清晰度 `focus` |
| `POST /capture_detect` | 拍照 + 异步检测 (判决仍只打工控机终端) |

### 裁剪边界 v4.2 (现场两轮目检后的口径, 以这版为准)
参考图纵向成分 (No_8, 源像素): 焊盘排 y[1097,1162] (66行, 金覆盖 29.8%, |gx|=28.6 边缘密集=**金手指本身**)
· 缝 y[1163,1179] · **实心金带** y[1180,1265] (86行, 覆盖 64.3%, |gx|=8.3) · 塑料本体亮边沿 y≥1258 (亮度冲到 255)
- 现场口径: **只保留金手指本身** → 取"最上面那片 边缘密集(|gx|≥18) 且 高≥20" 的 run (行密度分 run, 空隙≤6行合并);
  下方实心金带与塑料亮边沿**都不进画布** (第一版把它们裁进来, 现场说"下面多了厚厚的边沿")
- 左右端用**最大金连通域**的 x 范围 (焊盘两端在部分帧里金像素稀疏, 用 run 自己的列剖面会抖 ±90px) → 1455 稳定
- 实测 5 张真图: **1454~1462 x 70~72**, 倾角 0.8~1.0°, 跨帧一致
- ⚠️ 金手指只占 21:1 太扁, YOLO 会压成一条细线 → 规范化画布默认 **960x960 方图**
  (与 `yolo_detector/config.yaml` 的 `imgsz=960` 对齐: 不做 letterbox 也不上采样), 金手指纵向**拉伸填满**;
  同时另存一份"原比例 1455x70"版供目检 —— 两版都落盘 (`Finger_TopView_W960_H960_*` / `Finger_CropNatural_*`)
- **规整度指标必须在"原比例版"上算**: 拉伸 13 倍的画布会把斜率也放大 13 倍, 口径失真

### 规整度判据 (口径统一, 别再用整幅)
只在**实心金带核心行**（行密度 ≥95% 峰值 ±3 行）上拟合金像素质心线 → 斜率 = 残余倾角。
用整块 ROI 会被上排离散焊盘带偏（实测 −5~+2 px/1000），用核心行则一致 ≈0（三套掩膜口径都验过）。
v4.2 实测（原比例版）：**−0.94 ~ 0.61 px/1000**；v3 现状 0.87~1.02（整幅残差 98px）。

### 伺服 (tools/aoi_gold_servo.py, 注册名 L2.aoi_gold_align)
- 控制律: 误差 `e=(cx-cx*, cy-cy*)`px → `Δarm = -M·e` (**符号必须为负**: M 是"臂动1mm图像动多少px"的逆,
  要消掉偏差得让图像反向移动 e; 离线测试①专门抓这个符号, 写成 +M·e 会越跑越偏)
- 对焦: 沿光轴 L2.lift/lower **退火爬坡** 0.8→0.4→0.2mm, 判据 = 区域内 Laplacian 方差, 变差则退回+反向, 峰值停
- 雅可比 M 由 `calibrate` 现场量 (沿臂 X/Y 各推 1mm 看区域中心移动多少 px)
- 四级闸: ①授权(默认 dry-run, 真动要 --authorize) ②检测可靠(score≥0.85 且 金覆盖≥0.45) ③限幅(单步2mm/单轴15mm/25次)
  ④跳变闸(实测位移 vs 雅可比预期 >3× 立即停) — 全在 L2 收口, 脚本自身无自研运动学
- 现场三步: `check`(只读) → `teach`(人工摆最佳视角记基准) → `calibrate --authorize` → `serve --authorize`
- 基准/雅可比: `data/skills/l2_atomic/aoi_gold_target.json` (data/ 被 gitignore, 属运行时状态)

### 第二阶段: 换成 YOLO 区域检测 (数据自动标)
`tools/aoi_gold_region_label.py` 用模板法几何当**真值框**自动标注 (低可信 score<0.90 或 覆盖<0.45 自动挑出人工复核),
产出标准 YOLO 检测集 (`0 cx cy w h` + data.yaml + manifest.jsonl); 实测 5 张真图 5 标好/5 张裁剪图正确判低可信。
训练: `yolo detect train data=data/gf_region_ds/data.yaml model=yolo11n.pt epochs=100 imgsz=960`。
注意: 模板法给的是定向框, 现落成轴对齐框(含 ±1° 旋转外扩~21px); 要更紧改 OBB 旋转框数据集。

## 状态空间侧接线（2026-09-20, 老倪问「状态空间的 AOI 技能同步了吗」→ 已对齐）
- **L2 注册表** `data/skills/l2_atomic/registry.json`（技能清单对话框读它）当前 9 条 AOI 技能：
  金手指拉长图(喂YOLO) `?kind=crop` · 金手指原比例图 `?kind=natural` · 金手指区域检测 `/region?grab=1` ·
  裁剪质量指标 `/crop_info` · **金手指对准+自动对焦 `L2.aoi_gold_align`(ros=script, dry_default)** ·
  金手指AOI检测 `POST /capture_detect` · 表面AOI · 图片 · 实拍
- **画布 `ssaoi` 节点**: desc 写 v4.2 口径 + `crop_geometry_v4_2`(焊盘排 1455x70 → 960x960, 明确排除下方金带/亮边沿) + `aoi_interfaces`(5 个 URL + 伺服技能); 改前先备份, 校验**节点 83 / 连线数零变化**
- **技能清单图片预览**: `tools/gui/l2_skill_dialog.py` 的预览原来写死 `/picture` —— 而那个口按现场要求已改成**原始图**,
  所以老倪会问「技能清单里怎么看不到拉长后的金手指」。已加「来源」下拉(拉长960 默认 / 原图 / 原比例), 双击任意 `L2.aoi*` 都会刷新。
  ⚠️ **GUI 改码必须重启 studio 才生效**(无 autosave); 重启后 `ps` 查双开。
- 相关: `tools/l2_daemon.py` 执行器对注册表 mtime 热加载(改技能不用重启), 但 **GUI 的 .py 改了必须重启**

## ⚠️ 诊断: "AOI 图片没传过来" = 服务端本轮无拍照记录 (2026-09-23 实测)

现场症状: 画布/技能清单的 AOI 图片预览空白, 像是"图没传到本机"。**不是网络问题** ——
`.23.23` ping 0.3ms, 10082/10083 端口都开, 服务进程在跑。逐接口探 (只读 GET, 不打 capture):

| 接口 | 无拍照记录时的返回 |
|---|---|
| `GET /picture` | **404** `{"code":404,"msg":"尚无照片: 先 POST /capture_detect 或 GET /picture?grab=1"}` |
| `GET /picture?kind=crop` | **404** (同上; crop 依赖最近照片) |
| `GET /crop_info` | **404** `尚无裁剪记录` |
| `GET /region` | **404** (尚无照片) |
| `GET /picture?kind=natural` | **200 image/png** ✅ (命中落盘的历史原比例图, 135KB 级) |
| `GET http://…:10083/picture` | 404 Flask 默认 HTML 页 → 10083 那套**没有 /picture 路由** |

⇒ 根因: **Flask 进程内存里的 "最近照片/裁剪" 为空** (刚重启过 / 本轮没触发过拍照)。
GUI 技能清单预览默认取 `?kind=crop` → 默认必 404 → 看起来"图没传过来"。

**⚠️ + 该记录会过期 (2026-09-23 实测)**: 19:04 触发拍照后全接口 200; **55 分钟后** (无新拍照)
`/picture` `?kind=crop` `/crop_info` `/region` 全部回到 404, 只有 `?kind=natural` (落盘图) 仍 200。
⇒ 任何"看图/检测"前都必须**先触发一次拍照** (`POST /capture_detect` 或 `?grab=1`), 不能复用上次。

**⚠️ 技能清单点 L2.aoi* 不会下发 (2026-09-23 修)**: `tools/gui/l2_skill_dialog.py::_go()` 原来
开头就把 `id.startswith("L2.aoi")` 全部 `return`(只刷新预览) → 点「金手指AOI检测」永远不 POST,
表现就是"点了没反馈"。已改为 **双击=预览 / 「开始」按钮=真下发到常驻执行器** (http → POST),
并回显执行器返回 + 自动刷新这次的图。GUI 改码需重启 studio 生效。
验证通道 (不下发运动、只读): 往 FIFO 写 `{"skill": "L2.aoi_crop_info"}` → 4s 内 `~/zmax_data/l2_daemon.log`
出现 `HTTP ... → 200/404 ...` 回显 —— 这条就是 GUI 会显示的"反馈"。

处置: ① 触发一次拍照 (需用户同意, 真拍产线台): `curl -X POST http://192.168.23.23:10082/capture_detect`
或 `GET /picture?grab=1`; 之后 `/picture` `?kind=crop` `/region` `/crop_info` 全部有内容。
② 只想看历史图不拍照 → 预览源切 `金手指原比例(?kind=natural)` (落盘图, 不受内存状态影响)。

## 🆕 路由真相 (2026-09-23 用 OPTIONS 探明, 不用拍照)

`curl -X OPTIONS -D - http://192.168.23.23:<port><path>` 只看 `Allow:` 就能判定路由存在与否 (零副作用):

| 端口 | 存在并可用的路由 |
|---|---|
| **10082** 金手指 | `POST /capture_detect` · `GET/HEAD/POST /picture` · `GET /crop_info` · `GET /region` · **`GET /last_result`** ✅ |
| **10083** 表面 | 只有 `POST /capture_detect` (无 /picture /crop_info /region /last_result);
  55 条候选路径已穷举确认(2026-09-27) |
| **10081** | **与 AOI 无关** (上述路由全 404 → 不是相机程序, 不构成对金手指相机的抢占嫌疑) |

**`/last_result` = 判决通道其实存在** (旧记录"判决只打工控机终端、API 不返回"已过时)。无成功检测时回
`{"code":404,"msg":"尚无检测结果"}`; 相机恢复+拍照成功后应能取到 OK/NG/缺陷数 → GUI 可直接显示, 不必再靠终端。

**故障归因排除表 (2026-09-23 20:45~20:55 实测)**: 网络✅(ping 0.3ms/端口开) · 10082 进程路由✅ ·
10081 抢占❌(路由无关) · 表面相机✅(10083 POST 200) → 只剩**金手指相机 D265250070 本身**:
被另一程序独占(常见: v3 与 v4 同开, 同一 SN 第二个打开必失败) / USB 掉线 / 未上电。

## 🔎 一键体检工具 `tools/aoi_health.py` (2026-09-23 落地)

```bash
cd /home/ubuntu/lerobot-smolvla-lew
./gui-venv311/bin/python tools/aoi_health.py          # 只读(不拍照)
./gui-venv311/bin/python tools/aoi_health.py --grab   # 含抓帧项(会真拍, 需现场同意)
```
逐项打印 ①触发拍照 ②实拍原图 ③拉长960 ④原比例 ⑤区域 ⑥指标 ⑦表面, 含 HTTP/msg/**图的尺寸+亮度**,
并把 500 的 `相机初始化失败` 直译成现场动作。**区分单台相机故障**: 若 ⑦表面(:10083) 200 而 ①金手指(:10082) 500
⇒ 工控机 Flask 与网络都好, **只有金手指那台相机 (SN D265250070) 坏/被独占**(两套程序抢同一台相机是常见诱因)。

**故障态实测对照 (2026-09-23 20:45)**: ①`500 相机初始化失败` · ②`500 相机初始化失败` · ③`404 尚无照片` ·
④`200 但 18x364 mean=39`(落盘旧残图, 不是金手指条) · ⑤`500` · ⑥`404 尚无裁剪记录` · ⑦`200 success`。
⇒ 「看图技能没图片」的三种不同表现 (500/404/旧残图) 其实同一个根: 金手指相机拍不了。

## 🔥 曝光: 工控机拉伸图 73% 死白 → 原始图自裁 (2026-09-24 老倪现场发现, 必读)

**症状 (真拍实测 10082)**: `?kind=topview` (工厂规整拉伸图) **73% 是死白** —— y≥255 起逐行亮度**恒在 238.5±0.5**、
饱和像素(≥250)占 **61.5%**、死白行 **532/960**、最差列饱和 **100%**、细节能量 Tenengrad 仅 **2300**;
底部出现不自然强光边缘 (Cliff edge, 原始图 y≈582 处 12.1/行跳变, sat 带 y 592~1184)。
老倪原话: 「灰度信息丢失(过曝), 底线到 255 纯白, 明暗细节/纹理/衬度完全消失」。

**修法 (4060 侧, 无需工控机改动, 已上线)**: **别用工控机的拉伸图, 改从 `?kind=origin` 原始图自裁**
(`tools/aoi_exposure_fix.py::clean_judge_frame`):
1. **行方向**: 切掉过曝带 (行 sat>40%, 实测 213 行) → 只留"边缘密集(P92) 且高≥20 行"的金手指条 (实测 y 948~1147)
2. **列方向也裁** (⚠️ 只做行裁会留 100% 饱和的边列, 实测最右 10 列饱和 100%) → 裁到条自身 x 范围 (实测 x[433,2056])
3. 归一化到 head 的 imgsz; 台账如实记录 (裁掉行数/保留区间/列裁/cliff/规则)
**实测效果**: 饱和 61.5%→**5.6%** · 死白行 532→**0** · 最差列 100%→31.2% · Tenengrad 2300→**29394 (×12.8)**
命令行诊断: `./gui-venv311/bin/python tools/aoi_exposure_fix.py <origin.png>` (打印逐行剖面/过曝带/cliff/条带候选)
窗口: 「过曝切除」勾选 (默认开, 可关掉对比工厂图)。
**根治仍建议工控机侧降曝光/增益** (`set_exposure/set_gain` 或 config.yaml): 验收 sat 条内 ≤5%、无列 >60%。

## 🆕 OPT 相机取图客户端 + 外观质量检测窗口接入 (2026-09-24 实测, 老倪需求)

**链路**: Orin `192.168.23.66`(tashan) / 本机 `192.168.23.50` ──HTTP──> 工控机 `192.168.23.23` ──> OPT 相机
（实测 Orin→工控机 **0.82ms**; 本机直连 **1.8ms**; 两条通道读到**同一条判决**, `t` 逐位一致 → 双通道等价）

**工具 (已交付, 直接复用)**:
```bash
cd ~/lerobot-smolvla-lew
./gui-venv311/bin/python tools/opt_camera_client.py --health            # 只读: 路由 + 判决 (零副作用, 不拍照)
./gui-venv311/bin/python tools/opt_camera_client.py --last-result       # 工控机自家判决
./gui-venv311/bin/python tools/opt_camera_client.py --cam 1 --grab --out /tmp/a.png   # ⚠️ 真拍 (--via orin 走 Orin)
./gui-venv311/bin/python tools/verify_opt_camera.py --authorize         # 全链取证 (11/11)
```
窗口入口: 画布右键「🔍 外观质量检测」→「打开质量检测终端」→ **源=🏭 OPT 相机** + 相机(金手指10082/表面10083)
+ 通道(本机直连/经 Orin) + `📸拍帧`(真拍) / `🖼最近图`(不拍) / `📋工控机判决`(同表对照, source=opt-工控机)。
**纪律**: OPT 源**绝不自动真拍**(需手动点), 不批量轮询; 每次真拍写审计 `reports/opt_capture_log.jsonl`。

**实测真图 (金手指 10082)**: `POST /capture_detect` 1109~1626ms → `GET /picture?kind=topview` =
**960x960, 灰度均值 204, std 72.5, Tenengrad 2304, 749KB, 15.3ms** (真实结构, 非空白帧)。
`/last_result` 实测有数据: `verdict=OK count=0 detect_type=gf`。

**⚠️ 判据坑 (会误报的两处)**:
1. `/last_result` 刚重启服务返回 **404 `尚无检测结果`**(内存空) → **不是故障**, 拍照后才变 200。
   断言必须容纳**两种合法形态**: `200 + verdict/count` ‖ `404 + msg`。
2. **ARP 抖动**: 邻居表 `STALE/DELAY→FAILED` 期间 curl 瞬时 `rc=7 / http=000 / t=0.0003s`, 而 ping 同时正常 →
   重试即可, 别急着归因"服务挂了"(本次实测就是这样: 1 分钟后自行恢复)。

**10083 表面相机缺口**: 只有 `/capture_detect`, **无 `/picture`** → 只能触发拍照拿不到图。
补丁已写好交工控机侧: `docs/patch/opt_surface_10083_add_picture_route.md` (粘 30 行 + 现场 4 步验证)。
补齐后 4060 侧**零改动**即可取表面图 (`CAMERAS[2]["has_picture"]` 自动为 True 的那天, 只需改这一处标记)。

## 🧪 判决语义 + 模型输入 + 飞书推图 (2026-09-24 全部实测, 必读)

**① `POST /capture_detect` 返回 `{"code":200,"msg":"success"}` ≠ 合格！**
程序流程: `ensure_camera()` → `GrabAndSaveImage()` → 写 `_LAST_PIC` → `_enqueue_detect(topview, origin, type)` → **立即 return 200**
（源码里那行打印就是「📸 已拍照, 投递检测队列 (不阻塞动作)」）。200 只表示"拍照成功 + 检测已进队列"。
**真判决在后台 worker 线程**（`_detect_worker_loop`）: `detector.detect()` → 缺陷数/OK-NG →
只打在**工控机终端** + 存进 `_LAST_RESULT` → **用 `GET /last_result` 读**（verdict/count/defects/ms/n + origin/topview 文件名）。
老倪问"为什么反馈成功/是不是调 yolo"时, 用这条回答: 200 是受理, 判决在 /last_result。

**② YOLO 检测的是"裁减图", 不是原图**（实测证据链）:
- `cam_finger_10082_work_v3.py:399 _enqueue_detect(img_topview_path, ...)` → `:318 result = detector.detect(topview_path, ...)`
- `/last_result.topview` == `/crop_info.crop_file` == `Finger_TopView_W960_H960_No_<n>.png`（同名）
- `/crop_info.canonical = [960,960]` 与模型 `imgsz=960` 1:1
- ⇒ **裁减/规整质量直接决定召回**: `crop_info.score` 实测 0.4378（v4 模板法验收口径 **≥0.95**, v3 固定窗约 0.29）
  ⇒ 裁减 score 低时"OK"不可信: 模型根本没看全焊盘。交叉验证要**同口径**（我们的启发式阈值不是方图口径, 直接跑会假阳性）

**③ 判据图口径 (4060 侧窗口)**: 手动框选(永远优先, 与"过曝切除"开关解耦) > 原始图自裁(切过曝带/死白列) > 工控机拉长图(显式告警)。
**拉长 = 短边×2, 长边不动**（原来的 2448x2048/960x960 方图 = 纵向 8~13 倍, 现场判"太长了"）。
圈选状态每次拖框自动落盘 `reports/aoi_console_state.json`（roi/k/来源/判据图尺寸/框内饱和·死白行·Tenengrad）——
  **Agent 看不到屏幕, 就靠这个文件核对"人圈的是哪一块"**；`🎯 识别金手指并框` 可一键用算法兜底。
⚠️ 两个已修真 bug（都属"看了不算数"类）: ① 手选框被"过曝切除"开关挡掉 → 掉回工厂图 ② 手选框只换显示、没换 `_last_rgb`
  → **任务头推理仍在旧帧上跑**; 另: 500ms 定时器曾把工厂图重新塞回判据图面板, 覆盖显式结果 → OPT 源画面只在显式取图时更新。

**④ 把裁减图实时推飞书**: `tools/aoi_feishu_push.py`（飞书原工具只有 text/media, 无图片）
```
POST /open-apis/im/v1/images (multipart: image_type=message + image) → image_key
→ POST /im/v1/messages  msg_type=image  {"image_key": ...}   (+ 说明文字另发一条)
--once [--grab] [--ours]      # 推最新裁减图; --grab 才真拍; --ours 连自裁判据图一起
--watch --interval 8          # 盯 /last_result 的 topview 文件名变化 → 新拍照自动推 (只读, 绝不触发拍照)
```
token **每次现取** → 不依赖 gateway 进程内缓存（gateway 报 99991663 时本通道照样能发）。
实测: 文本 code=0; 图 image_key=img_v3_... code=0 message_id=om_...; 监听实推 No_288 ✅

**⑤ 补丁交接单**: `docs/patch/opt_surface_10083_add_picture_route.md`（10083 无 /picture 取不到图）·
`docs/patch/opt_10082_gold_stretch_2x.md`（拉长短边×2 + 窗按原比例 + 文件名写真实尺寸）

## ❌ 10083 表面相机取图: 已穷举到底 (2026-09-27, 别再重复试)

老倪反复问「10083 还是没有信号」。三条路都试到底了(全部零副作用/只读):
1. **10083 上 55 条候选路径逐个 `OPTIONS`** (`/picture` `/image` `/snapshot` `/stream` `/static`
   `/surface_images` `/last_result` `/camera` `/get_picture` 拼音名…): **只有 `/capture_detect`**
   (`Allow: POST, OPTIONS`), 其余全 404。工具: `tools/probe_aoi_routes.py`、`tools/probe_10083_deep.py`。
2. **工控机全端口扫描**(`tools/sweep_opt_host_ports.py`): 没有第二个 HTTP 服务能取表面相机图;
   10081 的 `/picture` 也是 404。
3. **取它落盘的 `./surface_images/`**: 445/139 开着, 但 `smbclient -N` → `NT_STATUS_ACCESS_DENIED`
   (无匿名共享, 本机也没有那台机器的凭据; RDP/SSH 均闭)。
⇒ 结论: 那套 Flask **没实现取图口**。唯一修法 = 上补丁
`docs/patch/opt_surface_10083_add_picture_route.md`(30 行 + 4 步自测)。
**补丁一上, 4060 侧零改动就会出图** —— 面板一直按 0.25Hz 轮询 `GET /picture?kind=origin`,
一有 200 立刻显示。别用别的相机图/旧图冒充这一格。

### 10082 金手指 “没图” 的另一半(已修)
除了“内存里没照片”(404 尚无照片), 面板还要能看到**整板**: 除判据图外另存一张整板缩图
(长边≤1400)。另外加**自动取景**(发现 404 就替它现拍一张、最快 30s 一次、页面上可关)后,
拍后 90s 内即使它又没照片也按**在线**报 —— 否则面板一边显示新图一边写“取图失败”会被人当成坏的。

## v5 (两路) —— 不检测时不落盘 (2026-09-27 老倪「不检测的时候不用保存那么多图片」)

在 v4 基础上生成 (`make_v5.py` 机械变换 + `test_v5_offline.py` 离线契约), **端口/路由/回执语义一字不改**。

| 动作 | 落盘? | 说明 |
|---|---|---|
| `POST /capture_detect`(真检测) | **写盘** | 模型 `detect(path)` 必须读文件 ⇒ 不能省; 写完按上限清旧图 |
| `GET /picture?grab=1`(只看一眼/总览页「拍帧」) | **不写盘** | 图编码后只留内存 (`_MEM`), 磁盘文件数不变 |
| `GET /picture?kind=…`(取图) | 不写盘 | **内存优先**(`X-Frame-Source: memory`), 无内存帧才回落到文件 |
| `GET /picture?grab=1&save=1` | 写盘 | 显式要存才存 |
| 标注图/legacy 图 | 默认不写 | `AOI_SAVE_DEBUG=1` 才写 |

新增两个自查口: `GET /storage`(每类张数/占用MB/上限/内存帧大小) · `POST /prune`(立刻按上限清, GET 只预览)。
保留上限(张, 环境变量): `AOI_KEEP_CANON`=400 · `AOI_KEEP_ORIGIN`=120, 每次落盘后 `_prune_dir()` 删最旧。

**两个必须踩到的实现细节(改 v5 代码时别再犯)**:
- 落盘开关用 `threading.local()` 传(`_TL.save`), **不要用模块级全局** —— Flask threaded=True, 一边 grab(不存) 一边 detect(要存) 会互相翻开关, 后果是检测文件没写 → 模型读不到 → 检测失败。
- 内存帧分支必须放在 `/picture` 的 `if not os.path.exists(path): return 404` **之前**, 否则 grab(save=False, 没有文件) 会先 404 ⇒ 不落盘的图永远看不到(实测就是这个坑)。
- 金手指那路原图不是 `cv2.imwrite` 而是 SDK `SciCam_Payload_SaveImage` ⇒ 全局替换 `cv2.imwrite`→`_iw` 时**别把 `_iw` 自己的实体也替换掉**(会递归爆栈: `maximum recursion depth exceeded in comparison`); SDK 落盘要单独加 `if _tl.save` 判断。

上线包 `http://192.168.23.50:8794/v5/`(旧 v4 URL 仍可用): 两程序 + `upgrade_aoi_v5.ps1`(自检 / 试跑 10084·10085 / `-Apply` 正式升级) + README + sha256。
离线自测: `cd ~/aoi_v4 && .venv-test/bin/python test_v5_offline.py` → 两路各 5/5。

## 🆕 工控机重启后 10083 表面 AOI 不自己起来 = 计划任务被禁用 (2026-09-30)

症状: 10081/10082 在听、**10083 closed**(`/dev/tcp` 探测), 本机 8793 表面格 `online=false frames=0`;
`ZMAX_AOI_KeepAlive` 的日志 `zmax_keepalive.log` 停在某个历史时间点且**没有任何新行**。

根因: 计划任务被置为 **已禁用** ⇒ 工控机一重启, 10083 再没人拉(它不像 10082 那样被别的机制带起来)。
两条取证命令(中文 Windows 下 `schtasks /query /v` 的字段名是中文, 用 `Select-String '状态|上次'` 匹配英文会**空手而归**):
```powershell
(Get-ScheduledTask -TaskName ZMAX_AOI_KeepAlive).State                    # Ready=启用 / Disabled=被禁
(Get-ScheduledTaskInfo -TaskName ZMAX_AOI_KeepAlive) | Select LastRunTime,LastTaskResult
```

修法(从 4060 走反向通道, 一条命令):
```bash
./gui-venv311/bin/python tools/station_cmd.py "schtasks /change /tn ZMAX_AOI_KeepAlive /enable; schtasks /run /tn ZMAX_AOI_KeepAlive" 90
```
⚠️ **起服务慢: 实测从 run 到 10083 LISTEN 约 89s**(首抓失败要重连相机) —— 45s 就去看端口会误判成"没起来",
  然后手搓再起一份(相机独占 → 抢相机/端口占用)。**等 ≥90s 再验**。
- 验活: `(Get-NetTCPConnection -State Listen | ? {$_.LocalPort -in 10082,10083}).LocalPort` + `GET /storage`=200。
- keepalive 拉起的正常形态是**两个 python 进程**: venv 解释器(启动壳, 父=cmd) + 它换成的 Python310 实例(**端口属主**)。
  看见两个别当重复副本杀错 —— 端口属主那个才是活的。
- 该脚本本身只"动手时才写日志", 所以"日志没有新行"≠"任务没跑"; 判活要看任务 State/LastRunTime + 端口/`/storage`。

### 🆕 `LastTaskResult=1` + 日志长期无新行 = **脚本自身解析失败(编码)**, 不是任务被禁 (2026-10-08 实测)

症状: 两路 `10082/10083` 全 closed; `ZMAX_AOI_KeepAlive` 的 **State=Ready**(启用着) 但
`LastTaskResult=**1**`, `zmax_keepalive.log` 停在 09-28(十天没一行), `v5f.log/v5s.log` 也不再长;
`aoi_watch.sh` 每 5 分钟报一次"自愈失败"却永远救不回来; 反向通道**正常**(心跳 <5s, 工控机在接单跑 KeepAlive)。
- 真因: **`D:\xspace\ultralytics_AOI\zmax_keepalive.ps1` 里有中文注释**。该文件头部自称 "ASCII only, PS 5.1 safe",
  但 v6 版把一段中文说明塞进了第 100~103 行(UTF-8 无 BOM + 中文里的 `"` 引号) ⇒ **PS 5.1 按 ANSI/GBK 读**,
  整脚本解析失败(`意外的标记")"`) ⇒ 任务 exit 1 ⇒ **一行日志都不写**(解析都过不去)、AOI 永远起不来。
  实测 5852B / 333 个非 ASCII 字节 / sha CC8FEE97…; 三方(仓库 `docs/deliver/v6/` · 8794 发布目录 · 工控机现役)逐位一致。
- 取证(只读, 走反向通道):
  ```powershell
  (Get-ScheduledTask -TaskName ZMAX_AOI_KeepAlive).State
  (Get-ScheduledTaskInfo -TaskName ZMAX_AOI_KeepAlive) | Select LastRunTime,LastTaskResult   # 1 = 失败
  (Get-ScheduledTask -TaskName ZMAX_AOI_KeepAlive).Actions                                    # 看它跑哪个 .ps1
  & powershell -ExecutionPolicy Bypass -NoProfile -File D:\xspace\ultralytics_AOI\zmax_keepalive.ps1
  #   ↑ 直接跑它, 报 `ParserError … 意外的标记")"` = 语法/编码坏, 与"任务被禁"是两码事
  $b=[IO.File]::ReadAllBytes('D:\xspace\ultralytics_AOI\zmax_keepalive.ps1'); (@($b|?{$_ -gt 127})).Count   # >0 就是元凶
  ```
- 修法(只改注释, 代码零改动): 把非 ASCII 注释行改写成 ASCII 同义英文 → 本机 `sha256` 更新 → 拷进 8794 发布目录
  (`~/zmax_data/aoi_v4/deliver/v6/`, 即 `http://<主节点>:8794/v6/`) → 工控机 `iwr` 下载 + `Get-FileHash` 核对
  (不一致绝不执行) → 再跑一次保活。实测改后 5825B / nonascii=0 / sha 3396253B…, 一跑两路 **10082 pid 8696 · 10083 pid 18832**,
  `/storage` 均 200, 8793 的 `aoi_gold`/`aoi_surface` 两格同时上线。
- **铁律**: 给工控机的任何 `.ps1/.py` 一律**纯 ASCII 注释** (中文只留在 4060 侧的 .md/说明里), 提交前用
  `python3 -c "print(sum(c>127 for c in open(p,'rb').read()))"` 自查 = 0。`aoi_watch.sh` 与 KeepAlive 都只会在
  "动手时"写日志, 所以"日志无新行 + LastResult=1"这条组合要**先去查脚本能不能被解析**, 别浪费时间查通道/任务状态。

## ⚠️ 两个必踩的坑 (2026-09-27 现场踩过, 改 v5 代码/排障时先看)

**① 取图路由缺"重连再抓" ⇒ 冷启/空闲后稳定 500「抓帧失败」**
- 现象: `/storage` 200 · `POST /capture_detect` 200 且 `/last_result` 判决正常(n/ms 推进) · `/picture?kind=origin`(不带 grab) 200,
  但 **`GET /picture?kind=origin&grab=1` 稳定 500 `{"code":500,"msg":"抓帧失败"}`**(每次卡 ~5.0s) ⇒ 总览面板/技能预览没图。
- 根因: `GrabAndSaveImage` 里 `SciCam_Grab` **冷启或空闲一段后首抓就会失败**返回 (None,None);
  `/capture_detect` 一直有兜底("⚠️抓帧失败 → `Close_Device()` → `ensure_camera()` → 再抓一次"), 而
  **`/picture?grab=1` 与 `/region?grab=1` 没有** ⇒ 首抓失败就直接 500。
- 修法(v5.1, 两路四處): 那两个路由补上**与 /capture_detect 逐字相同**的重连+重试, 再失败才 500。
  实测修后: 10082 `grab=1` 200/520918B/0.73s · 10083 200/237123B/0.26s (真 JPEG)。
- 教训: **同一相机在同一个进程里有两条取帧路径时, 兜底必须两边一致**。

**② "端口在听" ≠ "我们的 v5 在听"** (老倪手动 `python cam_xxx_work_v5.py` 两次的教训)
- 第二个进程的症状: 10082 报 **`打开相机失败 100120003`**(相机独占, 后者打不开) · 10083 报 **`端口 10083 已被占用`**。
  ⇒ 告诉他: 服务由计划任务托管, **不要手动再起一份**。
- 对自动化的影响: 只按端口判活的保活会漏掉 v2/哑掉的进程 ⇒ `zmax_keepalive.ps1` 改成:
  ①没在听→起 v5 ②在听但 `GET /storage` 非 200→杀该 pid 再起 v5 ③**同程序名超额副本→只留端口属主(及其启动壳), 其余杀掉**
  (抢相机的残留会在活实例重启时把相机抢走 → 重启后它又报 100120003)。


老倪明令: 「你是主节点, 要完全控制工控机和 Orin; **不要用 10084 10085 通道**; 还得用 10082 10083;
以后你得自主更新工控机的程序」。⇒ 更新/重启/回滚**不再请示**, 但**只能在 10082/10083 上做**, 也不许用测试口“先试”。

**一、工控机已装两个 SYSTEM 计划任务 (不再需要老倪贴命令行)**:
- `ZMAX_Agent`(`/sc onstart`) → `zmax_agent_loop.ps1` → 反向通道轮询(崩了 10s 自拉起) ⇒ 我随时可驱动。
- `ZMAX_AOI_KeepAlive`(`/sc minute /mo 1`) → `zmax_keepalive.ps1`: 10082/10083 哪个没在听就拉起它(平时不打日志)。实测: kill 掉 10083 → 25s 内自行恢复。
- 脚本都在 `D:\xspace\ultralytics_AOI\{zmax_keepalive.ps1,zmax_agent_loop.ps1,zmax_agent.ps1}` (纯 ASCII); 源文件在 4060 `~/aoi_v4/deliver/v5/`。
- 改写/换新时: 改 4060 上的源 → 用反向通道重新 `iwr` 下来覆盖即可(任务指向文件名, 不需重建)。

**二、自主更新器 `tools/aoi_remote_deploy.py`(唯一该走的上线路径)**:
```bash
cd ~/zmax_rel && ./gui-venv311/bin/python tools/aoi_remote_deploy.py \
  --finger ~/aoi_v4/cam_finger_10082_work_v6.py --surface ~/aoi_v4/cam_surface_10083_work_v6.py
# 现役文件名(房内命名族 cam_*, 2026-09-27 起): D:\xspace\ultralytics_AOI\cam_finger_10082_work_v6.py · cam_surface_10083_work_v6.py
# (改名后务必同步改 zmax_keepalive.ps1 的 $prog 与 deployer 的 FILENAME_* + start_pair 启动行, 否则自愈会拉错文件)
# ①拷进 8794 静态目录 → ②工控机 iwr 下载 + Get-FileHash 逐位核对(不一致即中止, 产线一字未动)
# ③现役备份 .bak → ④停旧起新(**只 10082/10083**, 分离启动) → ⑤验收 → ⑥失败自动回滚+复验
```
验收项(缺一即失败): `/storage`200 · `POST /capture_detect` 回执 `code=200` · `/last_result` 判决通道 ·
`grab=1` 出图字节>0 · **`grab=1` 前后 `files_total` 不增**。实测幂等重发 v5: 两路 6/6 全过。
⚠️ 坑: `/last_result` 在刚拍完时会是 **404「尚无检测结果」**(后台推理未完成; 表面 housing 实测 ~8.9s)。
断言必须**轮询最多 45s** 并接受两种合法形态(`200+verdict/count` ‖ `404+尚无`) —— 固定等 6s 会假失败并触发回滚。

**三、上线后自查(从 4060, 只读)**:
```bash
curl -s http://192.168.23.23:10082/storage   # 200 + 张数/上限
curl -s http://192.168.23.23:10083/last_result
curl -s -o /dev/null -w '%{http_code} %{size_download}\n' 'http://192.168.23.23:10082/picture?kind=origin&grab=1'
```
v6 已在 10082/10083 跑(2026-09-27, = v5 + 取图两路由的重连重试修复 + 版本号统一), 日志 `D:\xspace\ultralytics_AOI\v5f.log` / `v5s.log`。

**现役已换 v20 (2026-10-08)**: 两路统一版本号 v20 ——
金手指 `cam_finger_10082_work_v20.py`(内容 = v12: 判据图 + 模型吃 960 同帧派生图) ·
表面 `cam_surface_10083_work_v20.py`(内容 = v13: v12.1 判据图 / v12.2 台阶右界 / v13 曝光·增益可调)。
`zmax_keepalive.ps1` 的 `$prog` 与 `tools/aoi_remote_deploy.py` 的 `FILENAME_*`/`start_pair`/默认路径均已同步到 v20。
台账: `reports/aoi_v20_上线台账_20261008.md`。
⚠️ **换版时推荐顺序: 先停保活 → 先下载+哈希核对(**在役服务不动**) → 再停现役 → 起新版 → 验收 → 重开保活**。
把下载/核对放在停服之前, 产线中断窗口从"整段部署"压到只有停-起(~100s), 且哈希不符时能在停服前中止。
⚠️ 冷启动首探陷阱(2026-10-08 实测): 启动后 100s 时 `POST /capture_detect` 在 10083 上仍会回 **500**
(首抓失败→该路由靠自己重连重试), 数分钟后复测 200 ⇒ **别把冷启首探的 500 当成版本回归**。


## 升级到 v4 (表面 10083 / 金手指 10082) —— 历史/回滚参考 (已被 v5 取代)

> 现状(2026-09-27 09:5x): 工控机 `D:\xspace\ultralytics_AOI\` 跑的就是
> `cam_finger_10082_work_v5.py`(10082) 与 `surface_10083_work_v5.py`(10083), 分离启动, 日志 `v5f.log`/`v5s.log`;
> 验收: `/last_result` 两路 200 (gf ms≈1.6s / housing ms≈8.9s), `capture_detect` 回执 `{"code":200,"msg":"success"}` 逐字未变,
> `grab=1` 出图(385KB/261KB)且 `files_total` 不变。下面 v4 段落只作历史/回滚参考。


程序本体(**早就写好、离线验过, 别再重写**):
- 表面: `~/aoi_v4/surface_10083_work_v4.py` (488 行, 默认端口 10083)
- 金手指: `~/aoi_v4/cam_finger_10082_work_v4.py` (30137B, 同结构; 10082 尚未上线)
- 离线契约测试(不需相机/不需真权重):
  `cd ~/aoi_v4 && .venv-test/bin/python test_surface_v4_offline.py` —— `_stub/`+`_stubmods/` 假 SciCam/假检测器;
  实际输出必须 5/5: `capture_detect 200` · `picture?kind=crop 200 1280×1280` · `kind=origin 200 2048×2448` ·
  `last_result 200 verdict/count/ms` · `crop_info 200 canonical/mean`。

v4 相对 v2 = **只加不减**(升级不破坏产线口径): `POST /capture_detect` 回执逐字一致
`{"code":200,"msg":"success"}`; 新增 `GET /picture?kind=crop|origin[&meta=1][&grab=1]` · `/last_result` · `/crop_info`;
相机常驻 + 单 worker 异步队列; 表面规范图 = `config.yaml` housing 的 `imgsz=1280` 保比例 letterbox。

上线包(4060 上现成): `~/aoi_v4/deliver_10083_v4/` = 程序 + `upgrade_10083_v4.ps1` + README + sha256;
仓库副本 `docs/deliver/10083_v4/`。ps1 三段式: `-CheckOnly` 只自检 / 不带参 = 起在 **10084** 试跑路由(不碰 v2) /
`-Apply` = 停 v2 → 起 v4 → 真拍一张 → 存 `v4_check_crop.png`+`v4_check_origin.png`。

## 怎么给工控机送文件 + 怎么"驱动"它 (无 SSH/RDP/WinRM 时) —— 2026-09-27 已跑通并上线 v5
工控机`192.168.23.23`只开 10081/10082/10083 + 135/139/445(无匿名共享, 本机无凭据)。

**① 送文件(单向)**: 4060 起静态服务 `python3 -m http.server 8794 --bind 0.0.0.0 --directory <目录>`,
老倪在那边的 PowerShell 里 `iwr http://192.168.23.50:8794/<文件> -OutFile <文件>`。
**② 驱动它(双向, 反向通道)** —— 没有登录口时唯一可靠做法: `tools/agent_hub.py`(4060:8794) 出命令队列,
Windows 端一行 `agent_start_ascii.ps1` 每 3s 来 `GET /agent/cmd` 取一条、跑完把输出 `POST /agent/out` 回来。
- 纪律: **命令队列只有 4060 本机可写**(网络侧只能取不能投)、带 token、关窗即断、无凭据无自启。
- ⚠️ 脚本要**纯 ASCII**(PS 5.1 读无 BOM 的 UTF-8 会把中文变乱码, 极端情况破坏解析)。
- ⚠️ 老倪第一遍会"卡住": PS 5.1 的 `irm` 不带 `-UseBasicParsing` 卡在代理/IE 初始化 ⇒ 下载/轮询一律加
  `-UseBasicParsing -TimeoutSec 20`; 卡住时先让他跑 `Test-NetConnection 192.168.23.50 -Port 8794 -InformationLevel Quiet`。
- ⚠️ 回传命令里**别用 `Write-Host`**(它写 information 流, `2>&1|Out-String` 抓不到 ⇒ 我这边只看到空); 要用管道输出(字符串表达式/cmdlet)。
- ⚠️ 长命令分小步; 我 hub 的回执文件名按 `int(time.time())`, 同一秒两条会互相覆盖。

**③ v5 上线做法(已验证, 通道不变)**: 送两文件→`Get-FileHash` 核对→本机 `venv\Scripts\python.exe -m py_compile`→
试跑测试口(金手指 `--port 10084`; 表面**位置参数** `10085`)→真拍+`grab=1` 验收→停试跑→启正式口。
- **务必分离启动**(否则关窗会把服务带走): `$sh=New-Object -ComObject WScript.Shell; $sh.Run("cmd /c <venv python> <脚本> > <日志> 2>&1",0,$false)`。
- 表面那套 `POST /capture_detect` 在**非 10083 端口**会回 400「未配置检测模型, 可选端口 ['10083']」= **端口绑定的模型映射, 属设计**, 所以表面真检测只能在正式口验。
- 起完自查: `Get-NetTCPConnection -LocalPort 10082,10083 -State Listen` + 从 4060 `curl /storage` `/last_result` `/picture?kind=origin&grab=1`。


## 上线纪律 (相机独占)
- v2 与 v4 **不能同时开拍**: 同一通道(10083)只能一个进程, 相机(D265250099)也是独占。
  v4 起不来并打印"端口已被占用" = v2 还在跑。
- **不改 v2 的文件**(老倪明确要求): v4 是独立文件名, 回滚 = 停 v4 再按原方式启 v2。
- 上完后验收看 4060 侧那一格: 4s 内出图 + 标题栏带「上轮判定 OK/NG (n 缺陷 · 推理 xxms)」,
  或直接 `curl http://192.168.23.23:10083/picture?meta=1` / `/last_result`。

## 🆕 v10: 模型吃 960 同帧派生图(不落盘), 只落判据图一张 (2026-09-30)
老倪: 「Finger_ModelIn_* 不要了; 保留 Finger_TopView_W900_H332_*; 确认模型吃的是哪张」⇒ 实测改前吃的是 ModelIn(960)。
四条硬教训(别让模型直接吃判据图 / 临时图别写在高频路径 / 通道命令必须有界 / 部署器状态码与判据口径)
见 `references/aoi-v7-judge-and-channel-20260929.md` 的 v10 段。在役 v10; 回滚 `cam_finger_10082_work_v6.py.bak`。

## 🆕 v7: 落盘/展示的 topview = 「判据图」口径 (2026-09-29)

改前 topview = **960x960 方图**(1455x70 条带纵向拉 13.7 倍), 网页判据图 = **900x332** ⇒ 肉眼两张图。
修法: 口径从 `tools/aoi_exposure_fix.py` **逐条移植**进工控机(`render_judge`: 过曝带切除+只留金手指条+列裁死白列+
短边×2+按实测倾角反旋+定尺 900x332), `?kind=crop|topview` 与落盘都给判据图; **模型输入逐位不变**
(仍 960x960 送检, 另存 `Finger_ModelIn_*`), `/last_result` 同时报 `topview`/`model_input`。
改动前必读: `references/aoi-v7-judge-and-channel-20260929.md`(口径细节/离线契约测试的坑/验收 r≥0.98/交付与回滚)。

## 🆕 反向通道"死了"≠ agent 死了 (2026-09-29)

三根因(**按此序查, 别先怀疑 agent**): ①hub 没托管(`ss -ltnp | grep 8794` 没人听 ⇒ `zmax-agent-hub.service`)
②队列在 `/tmp` 被内核 `fs.protected_regular` 拒写 ⇒ 运行态搬 `~/zmax_data/agent_hub/`
③两端 token 不一致(客户端带的是 `ZMAX_AOI_KeepAlive`) ⇒ hub 多 token。
判活手段: `tcpdump -A ... 'host 192.168.23.23 and port 8794'` 看**它发的请求**(403=我们拒它, 不是它死);
取回执 `tools/station_cmd.py "<PowerShell>"`。细节见 `references/aoi-v7-judge-and-channel-20260929.md`。

## 调用纪律

- 它是**产线设备**的检测服务

**差在哪(实测量)**: 改前 topview = **960x960 方图**(1455x70 条带纵向拉 ~13.7 倍填满方框), 网页判据图 = **900x332**
(原比例条带 + 纵向×2 + 反倾角 + 定尺) ⇒ 同一张原图两种口径, 肉眼完全不同。

**修法(工控机程序 v7, 只改 10082)**: 把 4060 侧 `tools/aoi_exposure_fix.py` 的口径**逐条移植**进工控机
(`render_judge`: 过曝带切除 → 只留金手指条 → 列裁死白列 → 短边×2 → 按实测倾角反旋(白底) → 定尺 **900x332**),
落盘/`?kind=crop|topview` 都给判据图; `/crop_info.judge` 出台账; 渲染失败**回退+警告**, 不硬裁一张错的。
- ⚠️ 灰度加权必须 `0.299R+0.587G+0.114B`(进出各转一次颜色); 喂 BGR 会**裁错行**。
- ✅ **模型输入逐位不变**: YOLO 仍吃 960x960 模板法规整图(`imgsz=960` ⇒ 召回不受影响), 另存
  `Finger_ModelIn_W960_H960_No_*.png` 并送检; `/last_result` 同时给 `topview`(人看的=判据图) 与 `model_input`(模型吃的)。
  ⇒ **改"人看的图"时绝不动"模型吃的图"**; 两者都落盘+都进台账, 追溯不断。
- 验收口径(可复现): 工控机 `?kind=crop`(900x332) vs 4060 网页判据图帧 → **r≥0.98**(实测 0.9847, 行剖面 0.9971);
  离线对同源原图 → r≥0.99(实测 0.9973)。**别只看尺寸对**。
- 离线契约测试: `cd ~/aoi_v4 && ~/zmax_rel/gui-venv311/bin/python test_v7_judge_offline.py`
  (桩相机喂**真实原图** + 桩 detector **记录它被喂了哪张文件** ⇒ 能硬证"模型输入没变")。
  坑: 桩路比真相机多一道去马赛克(桩喂的是已处理好的 PNG) ⇒ 它自测的倾角会偏(-1.5° vs 真值 -0.75°),
  直调对比要用**真相机 /region 的实测倾角**, 且桩会**原地改**你传进去的像素数组(直调要重新 imread 一份)。
- 交付件 `docs/deliver/v7/`(程序 + `judge_render.py` + 离线测试 + SHA256; 场侧 SHA256 与仓库逐位一致)。

## 🆕 反向通道"死了"≠ agent 死了 (2026-09-29 三故障, 排障顺序照抄)

症状: `aoi_remote_deploy.py` 卡「通道没回执」; `aoi_watch.sh` 报「工控机 agent 已 N 分钟没轮询」;
而 AOI 产线本身正常(10082/10083 由工控机自己的分钟任务托管)。**先别信"agent 死了"**, 三步查:
1. `sudo ss -ltnp | grep 8794` → hub 在不在(**必须在**, 手工起的断一次就没了) ⇒ 已建 `zmax-agent-hub.service`(enabled)。
2. `sudo timeout 20 tcpdump -A -s 0 -n -i <产线网卡> 'host 192.168.23.23 and port 8794' | grep -aE 'GET|HTTP/|403'`
   —— **看它到底发了什么**: 实测客户端每 5s 都在 `GET /agent/cmd?t=ZMAX_AOI_KeepAlive`, 我们回 **403 token 不对**
   ⇒ "客户端活着, 是主节点这头拒它"。**两端 token 可能不一致** ⇒ hub 支持多 token(`--token a,b`), 两个都认。
3. 队列文件若还在 `/tmp`: 服务以 root 跑、文件属主是 ubuntu ⇒ root 重写 sticky 目录下他人文件被内核
   `fs.protected_regular` 拒(`PermissionError: /tmp/zmax_agent_cmd.jsonl`) ⇒ 队列**取不走**(表象=通道断)。
   运行态统一搬 `~/zmax_data/agent_hub/`(`cmd.jsonl`/`out/`/`hub.log`/`beat`; 旧 `/tmp/zmax_agent_beat` 仍写, 兼容看门狗)。
   同一坑: 工具里的 `OUT_DIR` 必须与 hub 一致, 否则"命令跑了但收不到回执"(假超时)。
- 取回执一行命令: `./gui-venv311/bin/python tools/station_cmd.py "<PowerShell>"`(缺 `tools/station_cmd.py` 时,
  `agent_hub.py --enqueue` + 读 `~/zmax_data/agent_hub/out/` 最新文件同样可)。回执里 `whoami` = `nt authority\system` ⇒ 计划任务跑起来了。
- 教训: **通道健康要用"它发来的请求"判, 不能用日志行数/本机自检判**(本机 curl 会把 beat 探活, 看门狗脚本已特意排除本机来源)。

## 调用纪律

- 它是**产线设备**的检测服务: 调用=真拍一张真机台照片 → **先问用户再打**, 不批量轮询
- 想连这台工控机做别的(SSH/RDP/VNC)都是**关的** ✗; 只有 10081/10082/10083 三个 HTTP 口开着
- 10081 是同族的第三个 Flask 服务(端口映射未在其中写明), 需要时用 `POST /capture_detect` 试

## 🔴 真根因: 相机自动曝光/自动增益出厂就是开着的 (2026-10-08, 本条最值钱)

**症状**: 画面发糊 + 判据图金手指根数 19/21/22 来回变 + "曝光改了没反应"。
**根因链**(实测, 不是推测):
1. 这台 OPT-LCRT1500 (SN D265250070) 出厂 `ExposureAuto`/`GainAuto` **开着**; 此状态下对
   `ExposureTime`/`Gain` 的写入一律返回 `rv=100100010`(值非法) → 调用方只打印"设置失败"就过去了
   ⇒ **文件里写的 10000us 从来没有生效过**。
2. 相机自己拉 **~94ms 超长曝光**在亮金属上硬扛 ⇒ 恒定过曝(条带内 20%~32% 像素 ≥250)。
3. 过曝 ⇒ 金手指之间的**暗缝被糊白桥接**成一条宽亮段 ⇒ 宽度归整把"两片粘成一片"判错 ⇒ **根数忽多忽少**。
   ⇒ **根因不在认领/归整算法, 在相机取像参数**(别再去改归整逻辑)。
**处方(顺序不可换, 逐条 rv=0 实测)**:
```
ExposureAuto->"Off"   # SetEnumValueByString, 大小写敏感: "off"/"Off " 都会被拒
GainAuto->"Off"
ExposureTime -> Gain -> Gamma    # 三个都用 SetFloatValue
```
- ⛔ **禁用「停采集→写→恢复采集」**: 实测 `StartGrabbing` 卡死不返回, 整路相机死掉(只能 kill 进程重开)。
- 读值要用 SDK 的 `SCI_NODE_VAL_FLOAT` 结构(`ctypes.byref(struct)`); 传 `c_float/c_double` 会 TypeError。
- 定值(扫档; p50=片亮度 / p10=缝亮度 / 对比度=p50-p10):
  `20000us×8.0 → 206/49/157` ← 选它(曝光仅自动档 1/5 ⇒ 更锐) · `30000×8` 与 `60000×4 → 149/115/34`(等价 ⇒ 曝光×增益线性可换)
  · `120000×2 → 146/113/33`。范围: 曝光 1~1e7us · 增益 1.33~16.38(写 1.0 会被拒) · Gamma 0~3.999。
- 现场光源偏暗是客观事实(10000us 下整幅均值仅 16、最亮区 94, 要 ~9.4 倍补偿) ⇒ 先查灯; 程序侧用"高增益+短曝光"换锐度。
- 一帧自检: `AOIQualityChecker().assess_frame(帧)` → `ok / too_dark / overexposed / gaps_washed` + `need_x`(还差几倍)。
- 判据图正解仍是 **19 根**(674→1952 等距); 边缘那两块(左端亮条/右端过曝端壁)都不是金手指。

## 判据渲染的隐藏崩溃: 别用参数名当局部变量 (2026-10-08)
`_v21_render_core` 里 `gate = min(bg+25, 1.35*bg)` **覆盖了同名参数 dict** ⇒ 暗帧走到 fallback 分支必抛
`AttributeError: 'float' object has no attribute 'get'` ⇒ **判据图整个报错**(表象: 判据图有时不对/空)。
修法: 局部变量改名 `edge_gate`。⇒ 规矩: **函数参数名不许在本函数里复用为局部变量**。

## 产线/调试分工 + 旁路对齐 (2026-10-08 老倪定)
| 角色 | 在哪 | 怎么改 |
|---|---|---|
| **产线程序** | **工控机** `D:\xspace\ultralytics_AOI\cam_finger_10082_work_v20.py`(10082) / `cam_surface_10083_work_v20.py`(10083) | 只能经 `tools/aoi_remote_deploy.py`(哈希核对 + 失败回滚 + 合法404放行) |
| **调试程序** | 本仓库 `tools/aoi/` 同名副本 + `src/lerobot/policies/yolo_3d/quality_check.py::AOIQualityChecker` | 直接改; 自检 `gui-venv311/bin/python src/lerobot/policies/yolo_3d/quality_check.py` |

- 清单(端口/远端文件名/仓库副本/sha256): `tools/aoi/PRODUCTION_MANIFEST.json`
- 旁路对齐: `python3 tools/aoi/production_sync.py status|verify|diff|pull --port 10082`
  (`pull` 经反向通道把产线那份 base64 取回并与仓库副本比 sha256; 只在工控机上跑一次性 PowerShell 用 `tools/aoi_remote_run.py`)
- 画布节点「🔍 外观质量检测」真执行时会把 **取像参数行 + 产线/调试关系行 + 取像体检** 打进终端日志;
  三类逻辑(取像参数 / 画面健康度 / 缺陷判据)全在 `AOIQualityChecker` 一个类里, 节点 params 里也存了同一份(`camera_params`/`architecture`/`production`/`debug`)。

## 反向通道"死了"先分三类: 通道 / 服务 / **整机** (2026-10-08 新增判据)
| 现象 | 判据 | 结论 |
|---|---|---|
| 回执不来, 但别的都没事 | `ls ~/zmax_data/agent_hub/in/` 有堆积 + 无 out | agent 没在轮询(计划任务/会话), **服务本身还活着** |
| 10082/10083 也不通 | `ping 192.168.23.23` | 往下查 |
| `ip neigh` 显示 `192.168.23.23 INCOMPLETE` + 同网段**别的设备可达**(如 Orin `192.168.23.66`、`.23.160`) | 二层 ARP 都不应答 | **工控机整机不在线**(关机/休眠/网线/网口) —— 别再去修本机网卡/通道 |
一条命令取证: `ip -br addr; ip neigh show dev <产线网卡>; ping -c2 192.168.23.66; timeout 5 bash -c 'echo > /dev/tcp/192.168.23.23/10082'`
本机 8793 流服务会刷 `[local] 读帧失败 xN` —— 那是**症状**(它取的是工控机的图), 不是它的故障。


## 🆕 页面「🔍 请求检测」回 500「图像抓取失败」= 推流端在抢相机 (2026-10-08 实测)

症状: 页面上点「🔍 请求检测」→ `500 {"code":500,"msg":"图像抓取失败"}`; 但**直连工控机** `POST /capture_detect` 却 200。
同一格的 `/picture?kind=...&grab=1`(推流取帧)一直 200 —— 相机没坏、产线程序也没坏, 别去动机器/程序。

根因(实测): 8793 推流端"有人在看"那一格时每轮带 `&grab=1`(≈2 次/秒), 与 `/capture_detect` **抢同一台 OPT 相机**
(该 SDK 不支持并发抓图) ⇒ **只要页面开着看画面, 检测就抓不到帧**。证据: `D:\xspace\ultralytics_AOI\v5s.log` 里
`GET /picture?...&grab=1 200` 与 `POST /capture_detect 500` 逐秒交错, 且"关掉页面再看就成功"。

修法(`tools/cam_live_stream.py`, **服务端收口, 零产线改动**): 新增 `_AOI_DETECT_BUSY`(port → 忙到时刻) +
`_aoi_busy/_aoi_busy_enter/_aoi_busy_release`; `_aoi_detect()` **进门占住 30s**(覆盖 POST 往返含冷启重连)、
**出门留 4s 尾巴**; 两处 `_watching` 计算 + 两处"自动现拍"分支统统加 `not _aoi_busy(port)` ⇒ 检测期间推流只读内存帧。
实测(**观众在场**下点按钮): 10082 / 10083 `POST /api/aoi/detect` 均 `HTTP 200 + ok=True + fresh=True`
(金手指 1495ms · 表面 8747ms, 各自回 `saved_incoming` 落盘路径)。顺带: 金手指等待窗 2.5 → 4.0s(拍照往返 + 1.6s 推理)。

⚠️ 相机被抢后**表面程序会卡死掉线**(端口释放、后续请求 `000`): 这时 `ZMAX_AOI_KeepAlive` 会自己拉一份新的(新 pid),
   等它绑上端口(实测 <90s)就恢复; **别手搓第二份**(会变成两份抢相机, 更坏)。

⚠️ 判据语义(老倪会追问): 两路 `/last_result` 在**工件不在位**时也报 `verdict=OK · count=0` ⇒ **"0 缺陷"不等于"合格"**。
   表面程序自带 `judge_ok` / `judge_why`(实测 `亮条上边缘点太少(0) —— 画面里没找到过曝条(没拍到位/曝光变了?)`)可当"在位"前置判据;
   金手指侧没有这个字段时, 用 `AOIQualityChecker().assess_frame(帧)` 先体检再谈缺陷判定。

### 🆕 怎么判「工件不在位」而不是「相机/曝光坏了」(2026-10-08 双向实测)

背景: 判据图是程序按认领规则**画**出来的, 工件不在位时它**照样画一排键**(实测这一帧 900x332 上画了 16 根,
节距 55.5±1.0px、宽 ~31px、极规整) ⇒ **判据图本身不能当"工件在位"的证据**。同样, 两路 `/last_result` 会报
`verdict=OK · count=0`(空场景也是"0 缺陷") ⇒ **"0 缺陷"≠"合格"**。

判据(按可靠性排序):
1. **原帧上的周期结构**(最硬): 对金手指原帧做列向自相关 / 在 60~80px 上扫 Goertzel —— 工件在位时主峰就在
   实测节距 **~71px**; 不在位时**全程单调衰减、无任何峰**(实测: 只剩标注线造成的 ~100px 假峰)。
2. **判据图的尺度换算**: 判据图是定尺(900x332)的规范化裁剪, 图内节距实测 **55.5px**(≠原帧 71px, 比值 ~0.78)
   ⇒ 跨图比数字必须先换算, 别拿 55.5 去对原帧的 71。
3. 表面(10083): `/last_result` 自带 `judge_ok` / `judge_why`(如「亮条上边缘点太少(0) —— 画面里没找到过曝条(没拍到位/曝光变了?)」) ⇒ 直接当在位/拍到位的判据。
   金手指(10082)没有这个字段 ⇒ 用 `AOIQualityChecker().assess_frame(帧)`: 它会区分 `too_dark / overexposed /
   gaps_washed` 并把"还差几倍"算出来(实测该帧 blown 14.9% ⇒ `overexposed`, 亮带 y≈104~146 里 71% 像素 >=250)。

现场这一帧看到的是什么(实例): 一整块亮物 x≈405~2020, 结构为「颗粒状表面 → 过曝纯白镜面反光带 → 下方均匀无特征暗区(灰度~41)」
⇒ 金手指面没朝向这台相机 / 被掠射光洗掉 —— 此时**不要改曝光去"救"**, 那是工件/工位问题; 先让工件在位上。

### ✅ 金手指根数定案 = **19 根** (2026-10-08, 三重独立确认)

1. **程序自报**: `/crop_info` → `judge.n_keys = 19`(`state=ok` · `sat_after=0.0` · `kept_rows=[670,820]` · `ver=v24-gold-judge-20261008`)
2. **独立复核**(不靠程序): 取 `/region` 的 `region.quad` 做透视矫正成 1455x70 条 → 列剖面按阈值切亮片得 21 段,
   其中 2 处是**单根被阈值切成两段**(表现为成对异常 21px/60px 与 58px/20px) ⇒ **21-2 = 19 根**;
   正规节距 **~70.5px**(连续 12 段 70/71), 整排跨度 ~1371px(1455 条内两端各留边)
3. **用户目视**: 19 根 —— 与上两条一致 ⇒ 定案, 程序不用改

⚠️ **判据锚点必须用 `/region` 的 quad/bbox, 不要"找最亮行/找周期性"** —— 实测同一帧里:
   · y≈1164 最亮行 = **镜面反光带**(不是排);
   · y≈1570~1750 = 工件**下方背景/阴影**, 自相关在 55px 上假峰高达 0.93(那是散焦纹理), 一根片都没有;
   · 真排在 **y≈679~768**(=`/region.bbox [492,679,1456,89]`, 倾角 -0.75°, 条纹残差 3.36px)。
   我自己和两次目检子代理都在那两个假带上栽过 ⇒ **先要 `/region`, 再谈像素**。
   出图给目检时也要带上原图 x 标尺 + 明确 y 范围, 否则对方无法判断"这条带在工件哪一面"。

### 🎯 判据图"根数跳"(19/18/16/21)的真因与修法 —— v25 (2026-10-08)

症状: 同一姿态下判据图根数在 19/18/16/21 之间跳(用户最初抱怨「你怎么显示那么多呢」的残留)。

**诊断四步(全部可离线复现, 别在现场瞎猜):**
1. **先证"与姿态无关"**: 连拍 12 帧记 `/crop_info` 的 `n_keys` + `/region` 的 `cx/倾角/残差`
   → 实测姿态一帧不变(横向偏移 0.5px、倾角 −0.75°、残差 3.2px)而根数在跳 ⇒ 排除机械/取景。
2. **抓"跟着跳的字段"**: `/crop_info.judge` 的 `x_trim.dropped_cols`(442/493)与 `v24_claims_span`
   与 n_keys 同步变化; `sat_before` 只落在几个离散档(实测 0.2346/0.279/0.2945) ⇒ 是**画面亮度在漂**。
3. **离线复放装置(=可复现的证据台)**: 把产线程序当模块 import(桩掉 `SciCam*`/`Mv*`/`yolo_detector`/`gf_crop`;
   模块级会 `SciCamera()`/`YoloDetector()` 实例化 ⇒ 先把 `_Dummy` 类塞进模块命名空间再 exec),
   抓一帧原图**存盘冻结**, 对同一帧做 λ∈[0.75,1.18] 亮度缩放再调 `render_judge` ⇒ v24 立刻复现 19/21/16/16/19/19。
   ⚠️ **必须用冻结帧**: 每次重新抓帧会让不同批次的数字不可比(实测抓两批: 一批 16/18、一批全 19, 差点误判)。
4. **定位到具体阈值**: `_v21_strip_cols`(裁剪)的 `_V21_EDGE_CUT = 2.5` 是**绝对**阈值, 亮列门限 `frac×lvl`
   依赖绝对 `lvl` ⇒ 亮度一变, 左端那块 ~78px 金属边块就在"单键窗 / 拒收窗 / 双键窗"之间漂
   ⇒ 认领跨度在 `[-2,18]`/`[3,18]`/`[0,18]` 之间漂 ⇒ 21/16/19。

**修法(v25, 已在产线 10082):**
- 几何分析(键行窗/裁剪/亮列/键掩膜)统一走**逐帧增益归一化副本 `ga`**: 把中位灰度校正到现场正常状态的 **63/255**。
  选 p50 当参照是因为它**随光照精确等比**(实测同一帧 ×0.75~×1.18 → p50 = 47.2/53.6/58.0/63.0/68.0/74.3 = 63×λ);
  p90/p97/p99 在正常状态就已饱和(255), 亮区不能当参照。增益夹紧 `[0.70,1.50]` + 死区 `0.03`。
- **正常状态增益=1 ⇒ 出图与 v24 逐位相同**(实测 ×1.00 像素差 0.00 / max 0), 只有亮度漂移的帧才走归一化把跨度拉回 `[0,18]`。
- 渲染像素仍取原图(`block = src[...]`), `sat_before`/曝光增益仍用原图 `g`;
  **模型输入 `get_cropper`/`crop_goldfinger_regular`/`warp_goldfinger_topview` 一行没碰**。

**验收口径(必须这样报):** v25 六个亮度档全 19 且正常档像素差 0.00(max 0); v24 = [19,21,22] 不稳。
**套路复用:** 任何"同一场景下判据量跳"的问题, 先**冻结一帧 + 离线复放**把跳变复现出来再改;
改完必须给"正常状态像素差 0"的证据, 否则可能把在役观感偷偷改了。

**第二层病根(现场复放真帧才发现, 比第一层更隐蔽):**
- 部署第一版后**现场仍跳 16/19** ✗ ⇒ 抓 12 帧真帧逐帧记几何: **p50 恒 63.0、cx 恒 1224.5、倾角恒 −0.75°、金覆盖恒 0.157**
  ⇒ 不是全局亮度漂移(第一层的归一化治不到它), 而是**端部认领那一刀**对帧间 ±1px 噪声敏感:
  左端那块 ~78px 金属边块的宽度在"单键窗(≤1.60×中键宽)"与"拒收窗(<1.35×节距)"之间摇摆,
  帧间噪声让它过线/不过线 ⇒ 同一姿态下 16(少认 3 格)/19/22(多认 2 格) 随机跳。
- ⚠️ **离线复放必须用"真帧序列"**: 只对同一帧做亮度缩放(第一版验收就是这么做的)会得出"已修好"的假结论 ——
  因为全局增益归一化正好把那点缩放抵消掉了, 而真帧的变化不在全局增益这一维。
- 🛠️ **修法 = 短窗逐格投票**(v25b): 物理事实是"同一个工件的金手指阵列静止" ⇒ 端部不该由单帧一刀决定。
  最近 7 帧里被认领 ≥2 次的格子才认领(`_V25_VOTE_WIN=7` / `_V25_VOTE_MIN=2`)。效果(8 真帧 × 3 轮复放):
  预热 3 帧后**恒 19**(其中 13 帧原始为 16, 由 `healed=[0,1,2]` 补回); 偶发多认格得票 0~1/7 ⇒ 被否掉。
  代价: 启动/换件后 3 帧(~1.5s)预热期, 期间仍按单帧结果。
- 套路: "同一场景下判据量跳"要**分两层查** —— 先查全局量(亮度/增益), 再查**判决边界的一刀切**
  (阈值恰好落在结构的宽度/高度边缘)。第二层用"真帧序列复放 + 逐格投票"这类时间维度手段收敛,
  比继续调阈值稳得多。

### 🎯 金手指点2(背面视角) 的检测极限 —— 动臂实验实测 (2026-10-08)

老倪: 「金手指点2 是金手指的另一面, 目测很黑, 你来调整检测」→「直接动，你来实验」(带警报)。
**先把"黑"量清楚**: 点2 帧 p50=32(前视 63)、41% 像素 ≤20、8% ≥250；判据图 p50=0、83% 纯黑、均值 14 ⇒ "很黑"是真的。
根因链: ① 中位 32 ⇒ v25 归一化需要增益 **1.97×**，而 `_V25_GAIN_LIM=(0.70,1.50)` **夹住**（实测放宽到 ≥2.0
后根数 8→16，正好在 1.97 处饱和 ⇒ 硬证）② 放宽夹紧后**首遍仍 `state=None`**（靠 v22 重试救，现场 `attempt=3`）
⇒ 夹紧只是必要条件，不是充分条件。

**动臂实验（11 步，全部原地纯旋转、零抬升、零位移，走 8793 授权窗）**:
| 轴 | 结果 |
|---|---|
| **A 绕工具X(俯仰) +3°** | **最优**: r 0.401→**0.488** · focus 86.6→**137.4** · 周期带 540px→**40px** |
| A+6° | 变差(0.371) ⇒ 最优在 +3° 附近 |
| B 绕工具Y(倾侧) ±3° | 中性(0.466/0.479) |
| C 绕工具Z(自转) +3° | **有害**(r 0.319, 根数 16→9) |
| J6 自转 5° | **有害**(r 0.391, 根数 16→7; 且 TCP 走 2.1mm 非原地) |

**三条硬结论**:
1. ~~姿态有杠杆但天花板 r≈0.49~~ **已作废(见下方更正: r 系误测, 真值 0.891)**。
2. **"黑"不是姿态问题**: 所有姿态下 p50 恒 28~33 ⇒ 3~6° 旋转对入射光几乎无影响（此前的"转一点能改受光"假设
   被自己的数据否掉）。黑 = 光的角度/强度 ⇒ 只能在**取像侧(曝光)或补光**解决。
3. `/region` 全程 `bbox=null`：v4 **模板法是前视专用** ⇒ 与姿态无关，别在这上面耗。

**真正的下一步（按性价比）**: ① 软件: 夹紧放宽到 3.0（零风险，前视增益 1.0 落在任何夹紧内 ⇒ 逐位不变）——
只是必要条件 ② 取像: 点2 单独一档曝光(2×) —— **实测可实时切换, 不用重启**(见下面「✅ 按点位切曝光」一节)
③ 硬件: 背面补光 ④ 模型: 点2 视角自己的数据（**决定点2 能不能真检测**，现模型只见过前视）。
判据提醒: **"目测很黑"必须先用 p50/饱和率量一遍**再谈修法；**"动臂调姿态"不能拿 focus 当目标**——
focus ∝ 对比度²，提亮同一帧就能把它抬起来（实测 49→90.8），会去追一个被亮度污染的指标。

### ✅ 按点位切曝光: 实时写曝光**其实有效**, "必须重启"是过期论断 (2026-10-08 21:16 实测翻案)

**旧论断**(程序注释 + 本技能上一版都这么写): "这台 OPT 相机在**采集过程中**写 ExposureTime/Gain 必失败(SDK 非 0);
想绕过就去 StopGrabbing→写→StartGrabbing, 那会把相机**卡死**(现场真卡死过一次)" ⇒ 结论曾是"曝光只能在启动时生效,
切档要重启服务(≈100s)"。

**实测**: 自动曝光关掉之后, 采集过程中直接写 **完全有效** ——
```
POST http://192.168.23.23:10082/param?exposure=40000&gain=8
-> {"ok":true,"applied":{"exposure_us":{"ok":true,"want":40000.0}, ...}}
-> 下一帧 p50 33.0 -> 67.0 (正中标定值 63 附近); 再写回 20000 -> p50 回到 33.0 (连抓两帧 sha 不同 ⇒ 是新帧不是缓存)
```
⇒ 旧观察是**自动曝光/增益还开着那一天**的产物(那时任何写入都 rv=100100010 "值非法", 见本文件 🔴 节) ——
**和 `record_point_sdk.py` 老路径 bug 同一类病: 结论没跟着代码更新**。教训: 写"XX 必失败"这类硬论断时,
**记下当时的先决条件**(自动开关状态/相机状态), 否则日后照着"必失败"把自己卡死。

**落地(2026-10-08 老倪「按点位切曝光」)**: 做在 8793 侧, **产线程序零改动、零重启** ——
`tools/cam_live_stream.py` 加 `POST /api/aoi/param?port=10082&profile=pt1|pt2`(也可 `&exposure=&gain=` 自定义),
转发工控机 `/param`; 档位表 `AOI_EXPOSURE_PROFILES`: `pt1=20000us×8`(正面, 产线已验收) · `pt2=40000us×8`(背面, 实测 p50 33→67)。
页面 `station.html` 的 **点1/点2 按钮各自先切档再回点**(`setAoiProfile()`, 失败如实打在点位提示里) ⇒ 一次点按钮 = 动到位 + 光就对。
未知档位**被拒**(不乱写相机参数)。

**⚠️ 切档后要等 ≥1 帧**: 紧跟 POST 之后抓的那一张**可能仍是旧曝光**(实测踩到过, 误判成"写回失败")。
判"切档是否生效"要**抓两帧看 p50/哈希**, 别拿紧邻的那一张下结论。

### 🔴🔴 更正(2026-10-08 21:3x): 点2 的 r 先前**测错了**, 真病是"判据的前视假设"不是结构

上面「动臂实验」那张表里的 r(0.32~0.49)是**误测** —— 当时用滑窗 + 偏窄的节距搜索范围, 把真正的周期峰漏掉了。
用**判据自己的带 y980~1050** 重测: 点2 齿排自相关 **r=0.891**(前视同口径 0.912) —— **结构完全够, 不比前视差**;
判据自己识别出的**节距 72.0px / 相位 510** 也都对。⇒ 「姿态天花板 ≈0.49、结构是限制」**作废**。
姿态实验保留的可靠结论只有: A 轴+3° 让周期带收紧、focus +59%(而 focus 被亮度污染, 不能当唯一判据)。
**教训**: 报"结构差/自相关低"之前, 先确认自己的**节距搜索范围**覆盖了真周期(前视 lag≈47, 点2 lag≈72)。

**点2 真病(离线跑判据本体 8 帧复现, 与现场 11/16 跳动一致)** —— 一串"按前视定的假设"接连失手:
| 环节 | 前视假设 | 点2 实况 | 后果 |
|---|---|---|---|
| 列掩膜跨度 | 齿排贯穿条带 | 掩膜只到 x1607, 结构延续到 x≈1922(右端槽位亮度 200~228, **比中间还亮**) | 最右 3~4 根从没进计算 |
| 相邻列合并 | 齿间有暗缝 | 出现 w=188(2.6×节距)、w=346 的**粘连大块** | 几根并成一块 |
| 畸形块剔除 | 异常宽块整块丢 | 粘连块被判 `too_wide` **整块丢弃**(`outlier_dropped=3`) | 连块里的真齿一起丢 |
| 补格 | 只在已 merged 段范围内补 | `lattice_added_vs_kept=3`, 补不够 | 最终 16 |
第二来源: **光源相位闪烁** —— 帧间 sat_before 0.240↔0.286 交替、被拒边缘段跟着变 ⇒ 同一条排带被拍到两种亮度。
修法(风险由低到高): ① 补格改用**周期性**判据(沿节距/相位向两侧走, 槽位均值 ≥0.6×中位槽就继续) ② 粘连块按节距**切开**而非整块丢弃
③ 光源换成直流/在判据侧做主相位投票。**验收**: 前视逐位不变 + 点2 稳定等于真值 + 对照组(不改的 v25)同批帧序列。
诊断全文: 仓库 `docs/AOI-PT2-JUDGE-DIAGNOSIS-20261008.md`; 8 帧基线: `zmax_data/aoi_v4/snapshots/20261008_pt2_frames_exp40000/`。

## 🔴 按点位切曝光/增益必须**落盘 + 重启复原**（2026-10-08 现场踩坑）

**症状**：老倪「判据图还是总变」。部署重启后当场复现 —— 判据图尺寸恒定 900×332、state 全 ok，
但**每 4~5 帧整幅换一次**：均值 13.7 → 50.7（4 倍亮）、与上帧差异 55.6%，`kept_rows` 在
`[990,1039] ↔ [990,1469] ↔ [990,1199]` 之间跳。

**根因**：10082 程序**重启会把取像参数打回默认 20000**，而点2（背面）在 20000 下太暗 ⇒
行带搜索在"齿排 y≈990-1039"与"下方焊死亮面 y→1469"之间选错 ⇒ 带一变、判据图渲染的就是另一块区域。
`/api/aoi/param?profile=pt2` 只在**点击那一下**生效，**不持久** ⇒ 任何重启（部署/异常/人工）都会静默回退。

**实测对照（同一点2，只改曝光）**
| 曝光 | kept_rows(10帧) | 帧间差异 |
|---|---|---|
| 20000（默认，太暗） | 1039 / 1469 / 1199 **乱跳** | 55.6% / 30.3% ✗ |
| 40000（点2 该有的档） | **恒 [990,1039]** | 0.9~5.4% ✅ |

**修法（已上线）**
1. 8793 侧 `_aoi_param()` 写成功后调 `_persist_cam_param()` ⇒ 落盘 `zmax_data/aoi_v4/cam_param_persist.json`。
2. `_restore_cam_param(port)` 按落盘补回；部署器验收后 **⑤b** 自动跑一次（`aoi_remote_deploy.py`）。
3. 重启 8793 用**现役命令行原样**重启（`tr '\0' ' ' < /proc/<pid>/cmdline` 取），参数：`--port 8791 … --station-port 8793`。

**通用教训**：凡是"改设备/相机参数"的功能，都要问一句**"重启后它还在吗"**；
不在就落盘 + 在重启路径（部署器/启动钩子）里自动复原。否则现场看到的是"改过没用/自己变回去了"，
而代码里看不出任何错。

**判据图"变"的分层归因（排查顺序，别一上来就怀疑算法）**
① 取像参数档位对不对（本视角的曝光）→ ② 行带 `kept_rows` 稳不稳 → ③ 根数 → ④ 才是判据算法。
本次 ①②③ 全被曝光带偏，算法本身（v25 判据）在正确档位下是稳的。

## 🔴 判据图"一闪一闪/不断跳动" = 齿带纵向位置与高度每帧变 (2026-10-08 定案)

现场投诉:「金手指的判据图怎么还是一闪一闪的? 不断跳动变化」。**不是亮度闪, 是齿带上下移动 + 缩放变化**。

**先排除的三件事(全部实测, 别再重复查)**:
- 原图 `GET /picture?kind=origin&grab=1` ×5 + `GET /picture` ×6 ⇒ **逐帧一致**(亮度 53.4 恒定 · 帧差 0.7 · 水平/垂直位移 0) ⇒ 相机/光源/工件**都没动**;
- 曝光 `GET /param` 连读 12 次(18s)恒 **40000**(没被打回默认, 排除"档位不持久"那条旧病);
- `/crop_info` 的 `strip.w 1411.35` / `scale 0.97` 基本稳 ⇒ 不是整体裁剪几何在变。

**真凶: `judge.kept_rows` 每帧在变** —— 实测 `[1550,1709]` / `[1550,1599]` / `[1550,1619]`(行带高度 **159 / 49 / 69 行**来回跳)。
判据图按这条带渲染 ⇒ 出图里齿带的 y 范围变成 `62-168` / `87-244` / `136-195` / `123-208` …
(起点漂 **74px**、高度 **60~157px** @332 高) ⇒ 肉眼就是"一跳一跳 + 忽大忽小"。

**根因(程序自己每次都打在 warn 里): `⚠️ 模板匹配弱 score=0.378 < 0.55`** —— 匹配分只有门槛七成,
行带锁不牢。对照设计口径(v4 模板法验收 **score 0.954~0.990**)⇒ 模板已与当前取像/光照对不上。

**判"跳"要量这两个量(别被表象骗)**: ①`judge.kept_rows` 行带高度稳不稳 ②出图里齿带的 y 范围稳不稳。
实测这些帧的**黑底占比 0.58~0.92 / 饱和 0.000 全都过闸** —— 只看 v22 验收闸会判"图是好的", 但它在跳。

**修法(风险由低到高)**: ①重建 `templates/gf_strip_template.png`(当前在位帧可当参考) ⇒ 验收 `score ≥ 0.7`;
②行带高度加**上限**(齿排 ~50 行)+ 以**节距自相关**当锚点, 不许吃进上方暗区;
③同一静止工件**按住几何**(带/缩放)别每帧重算 —— 与"根数短窗投票"同一原理(静物不该由单帧一刀定)。

## 提交这类改动的操作纪律（踩过两次）
`git commit -m "..."` 里只要出现**直引号**(")或跨多段中文，shell 就会把消息拆开、报
`No such file or directory`，而**中文内容里夹直引号极容易被忽略**。⇒ 一律**写进文件再用
`git commit -F <file>`**；文件放 scratch，消息里的引号随便写。

## 判据图"跳动"的分层定位（2026-10-08/09 实测定案，别再混为一谈）

交付图"看着在跳"至少是**三层不同**的病，症状相似、治法完全不同 —— 逐层量，别跨层下结论：

| 层 | 判据（怎么量） | 真因 | 治法 |
|---|---|---|---|
| 相机层 | 取 `kind=origin` **原始帧**看均值 | 相机处于**自动曝光/自动增益**（本机型 OPT-CC1-GG50 出厂就是开的），每帧覆盖写入的曝光值 | **重启服务**让开机时序 `set_auto_off()` 生效；**绝不能停采集再写**（会卡死相机）。验证：原始帧均值恒定 |
| 整幅换区 | 看 `key_rows` 是否在宽度差很大的带之间跳 | `_v21_render_core` 里 `ky0=min(hit.y0) / ky1=max(hit.y1)` 的**并集**：逐帧一个远端 hit 冒头/消失就把整条带撑宽或缩窄 | **取最上簇 + 簇内只收与锚窗重叠的窗 + 静止保持(±100px/15s)** — 已上线 **v28**(判据自报 `v28-gold-judge-20261009`, 源件 `tools/aoi/cam_finger_10082_work_v27.py`)。⚠️ 并集方案**方向反了**：并集只会更宽，假结构(下方过曝亮面, 节距 46 vs 真排 70~72)一旦并进来就**永久停在宽带上**。同口径 A/B(12 帧冻真帧)：并集 **行带 2 种/根数 7↔15/帧差 6.6** vs 最上簇 **行带 1 种/根数恒 15/帧差 5.1** |
| 逐根宽度/个数 | 看 `rects` 宽度与 `n_keys`/`pitch` | 切分规则（节距/齿宽/软阈值）**按前视几何写死**（节距 47px/齿宽 26px）；点2 是另一面（≈72px、齿更大、右侧被照度梯度冲掉）。宽度帧内被 `_v21_uniformize` **强制均匀**，所以"宽度不固定"= 它每帧选的统一宽度在 64~123px 摆 | ① 列剖面**低频背景归一（平场）** ② 切分节距/齿宽**自适应**（按本帧实测，不写死）。**未完成** |

**三条铁律**
1. **复放对照必须每视角独立进程**：同进程连跑多视角会带 `_LAST_GOOD_JUDGE` 等跨帧全局状态，伪造"回归/无变化"。
2. **`py_compile` 通过 ≠ 能跑**：`NameError`/函数缺失是运行期错误 —— 每份改动都要**真跑一次**再报"改好了"；改/删函数或常量的**定义**必须同时核验**调用点**。
3. **A/B 必须用同一时刻的输入**：拿"修复前抓的帧"去判"修复后的行为"，会得出完全错误的结论（本轮为此白走一轮）。
4. **冻结帧必须用判据自己的取像方式**：`GET /picture?kind=origin&grab=1` ✓；`GET /picture`(工控机缓存帧)逐帧一致，在它上面**复现不出跳动** ⇒ 会误判"图是好的"。
5. **上线后必须回读版本**：`curl -s http://192.168.23.23:10082/crop_info` 里 `judge.ver` 要不是你推的那版 ⇒ 根本没生效。
   实测踩过：**部署日志全绿(推送/重启/验收全过)、产线跑的却还是旧版** —— 两个会话并行改同一份产线文件时互相覆盖。⇒ 上线前先 `python3 tools/aoi/production_sync.py pull --port 10082` 看产线现版；**合并时从产线现版改起**(别从仓库旧副本改, 会丢产线侧改动)。
6. **探针必须带 UA**：`urllib` 直连工控机要加 `headers={"User-Agent": "zmax-probe"}`，不带 UA 的请求会被服务丢掉(实测同一批端点不带 UA 全 0 字节; `curl` 自带 UA 所以看不出这个坑)。

**已知残留(2026-10-09, v28 尚未盖)**: 同一现场可能同时存在**多个**候选结构 —— 实测连采 10 次拿到候选位 `1330 / 1570 / 1650`(各高 50 行), 每帧"最上簇"落在哪一个会变 ⇒ 即使每帧带高稳定 50 行, **跨结构跳仍可达 240~320px**。
当前静止保持是 **±100px / 15s** ⇒ 挡不住这种跨结构跳(超容差就重认)。若现场再现: 改成**场景变化门** —— 用粗缩略图帧差(静物差 ≈0)做闸, 静物就一直沿用旧带(不设px容差), 画面真变了才重认; 别用"上帧带并集"(只会更宽, 见上表)。

### ❌ 已试过并否决: 节距保持(治不了根数逐帧翻)
第三层(逐根个数)活体仍在翻: 行带稳定在 `[1520,1599]` 内**根数 4 / 7 / 8 跳**。怀疑链: 每帧现算节距在 `95 / 151 / 176` 之间翻(≈基频的 1× / 1.6× / 1.85×, 因为相邻键被亮边粘成宽块 ⇒ 中位间隔变成基频整数倍), 而 v25b 端部逐格投票按节距分桶 ⇒ 桶被拆散。
两版都试了, **都未证明提升, 均未上线**:
1. **取最小当基频** ⇒ 锁到 **47.8px(=基频一半的次谐波)** ⇒ 根数从 15 **翻成 28**; 直接否决;
2. **取窗口 9 帧中位当基频**(偏离 >25% 的离群帧采用基频) ⇒ 离线 12 帧根数 15/15/…/**16/16**/15, 与 v28 的 **恒 15** 相比**没提升反略差** ⇒ 不上线。
⇒ 根数那层不是"节距不稳"单独造成的。⚠️ 另一个关键差异: **活体数量(4/7/8)与离线同帧(恒 15)不一致** —— 说明活体走的不是 `render_judge(bgr)` 这条路径(它带 `/region` 的 deskew 角度与 v22 重试档), 下轮**必须按活体入口 + 同参数复现**再改。

**✅ 活体入口已查到(2026-10-09)**: 产线就是 `render_judge(bgr, deskew_deg=float(info.get("angle") or 0.0))`, 喂**原始帧**(2448×2048), `info` 来自 `crop_goldfinger_regular`。
复现脚本 `~/.hermes/cache/scratch/live_entry_repro.py <N> <判据.py>`(同帧先 `?kind=origin&grab=1` 取图再 `GET /region` 取角度, 两种 deskew 各跑一遍)。
实测(10 帧): deskew=0 与 deskew=活体角度(0.15~0.25) **结果一样**(根数 9/15 混合) ⇒ **角度不是根数翻的原因**。

**根数翻的真正驱动量 = 列切分的"合并档"**: 同批次里 `n_merged=8 → 根数 9`、`n_merged=11 → 根数 15`(节距随之报 177~206 vs 95)。
即"相邻键被亮边粘成宽块"的档位在帧间变 ⇒ 格点数跟着变。**下轮的治法在这里**(列剖面**低频背景归一/平场** + 按本帧实测节距/齿宽**自适应**切分, 不写死前视几何), 不是节距保持、不是行带、不是角度。

### 🧪 层③ 平场+自适应版 (ROUND4, 2026-10-09) — 离线达标, 但**未过验收 / 未部署 / 未上产线**

上面"下轮的治法"那一版**已经写出来**, 但**不满足上线门槛**, 状态如下(别拿它当"已上线"):

- **算法**: 列剖面**低频背景归一(平场)** + 切分节距/齿宽**自适应**(按本帧实测, 不写死前视几何)。
- **真源**: `/home/ubuntu/zmax/zmax_data/aoi_v4/cam_finger_10082_work_v26.py` (sha256 前12位 `13c448854092`, ≈2458 行)。
- **仓库镜像**: `tools/aoi/_wip/cam_finger_10082_work_v26.py`(2026-10-09 同步; 两边 sha256 前12位**必须相等** `13c448854092`)。⚠️ 此前的仓库镜像是**旧版(无带锁)**, 别再拿旧镜像当"平场版"。
- **离线段(点2)**: `n_keys` **20~23(众数 22)** · 宽度 **21~23px** · **13/13 帧出图**; 对照**改前** 2~16 根 / 11~692px / **有帧出不了图**。
- **前视回归**: 8/8 帧与在役 v25 **逐位相同**(正常态像素差 0)。
- **层①/② 已上线**(与本版无关, 但同批已落地): 层① 相机自动曝光已修 · 层② 整幅带跳已修并上线
  (`122070B · sha 8CBFDEE53D65 · pid 21596 · 档位复原 40000us×8`; 前视独立进程复放 **8/8 帧与 v25 逐位相同**)。
- **❌ 为什么禁止直接部署到产线**:
  1. **层③(逐根宽度/个数)验收本身未过** —— 靶子是"节距/齿宽写死前视几何", 但**活体(现场真帧)尚未按活体入口 + 同参数复现合格**:
     活体与离线同帧结果不一致的老问题(活体根数 4/7/8 vs 离线恒 15)必须先按**活体入口**复现出稳定数字, 才算真过验收。
  2. **镜像 ≠ 产线**: 产线现役是 `cam_finger_10082_work_v20.py`(判据自报 v28), 这份 v26 是**调试版**;
     部署只能经 `tools/aoi_remote_deploy.py`(哈希核对 + 失败回滚), 且**上线前先 `production_sync.py pull --port 10082` 从产线现版改起**(别从仓库旧副本改, 会丢产线侧改动)。
  3. **相机独占 + 层①②刚上线**: 任何拿不准的改动**不许为"试一下"动产线**(动了就抢相机/回退观感)。
- **收口判据(缺一即拒绝上线)**: 层③按**活体入口 + 同一时刻真帧 + 每视角独立进程**复现, 前后视都稳 **且** 前视逐位不变, 再走 `aoi_remote_deploy.py` 的验收闸。
