# Z-MAX 工位（Windows 移植版）运维要点

现场拓扑：Windows 主机 D:\ZMAX 跑 cam_live_stream(8793)/tcp_ar_server(8797)/dashboard(8799)，Intel 550C(`192.168.23.70`, intel/intel, SSH 可用) 跑 3DGS 采集训练渲染，工控机 `192.168.23.23` 只有 AOI 10082/10083 在听（22 端口不通）。

## 改页面的坑
- 8793 读 **D:\ZMAX\server\web\station.html**。`tools/web/station.html` 是另一份同名文件，改了不生效——先 `curl 127.0.0.1:8793/station | grep <新文案>` 确认改对了文件。
- 8793 每次请求实时读盘，改 HTML/CSS 不用重启；改 .py 必须重启进程。
- 重启子服务：按原 cmdline 参数用 python `subprocess.Popen([exe, script, ...args], creationflags=DETACHED_PROCESS|CREATE_NO_WINDOW, stdout/stderr 重定向)`。**不要用 PowerShell `Start-Process -ArgumentList`** —— 含空格的中文参数（如 `--local2-label "🎥 中央相机 (Intel 8812)"`）会被拆成多个 argv，脚本报 `unrecognized arguments`。
- **服务端拼 HTML 不要用 `%` 格式化**：模板里 HTML/CSS/JS 的裸百分号（`height:100%`、`Math.round(z*100)+"%"`）会被当成占位符，端点直接 `TypeError: not all arguments converted during string formatting` 报 500 —— 而且只有访问那个路由才炸，服务其余部分看起来全正常，很容易误判成路由没注册。改用 `@@TITLE@@` 之类占位符 + `.replace()`。

## 移动链路（Windows 无 l2_daemon）
- 原因：daemon 命令通道是 Unix FIFO（`os.mkfifo`），Windows 起不来，`exec.online` 恒 false。不要把页面文案写成「执行器离线」，改成 `online=null` + note 更准确。
- 平动：8793 `_ctl_move` 里 `os.name == "nt"` 分支把 `line_rel` 技能按 registry 的 axis（x_pos/x_neg/y_pos/y_neg/z_pos/z_neg）翻译成 8797 `/api/arm/move_rel` 的 dx/dy/dz，单次限幅 5mm。
- 旋转：8797 `/api/arm/rot_rel` 读当前 TCP 的 RPY → 绕**工具自身轴**右乘增量矩阵 → 回 RPY → `sdk_ctl.py move-abs`（`--rx/--ry/--rz`，米/弧度），限幅 5°。技能参数 deg 校验范围是 **[1, 30]**，传 0.5 会被拒。
- **万向节锁**：pitch(B) 接近 ±90° 时 A/C 退化。实测 B=-89.75° 转 1°，A/C 各跳 23°；反向转跳 142°。表现就是用户说的「B 轴有时候正有时候负」。已加闸：`|B| > 85°` 拒绝 B 轴旋转并提示先用 A/C 转开。直接改 RPY 分量（`rpy[idx] += d`）在非奇异区等价、奇异区必错，不要图省事。
- 授权：`POST /ctl/arm {on:true}` 开 30 分钟窗口（`mode:debug` 无时限）。**页面「不动」最常见原因就是窗口到期**，先 `tools/ctl_auth.py info` 看 `armed/left_s` 再排查别处。

## 金手指 AOI 相机（10082）
- 取参：`GET /param`；改参：**`POST /param?exposure=<us>&gain=<dB>`**（query 参数，不是 JSON body —— 传 JSON 会回 `applied:{}` 白干）。
- 可用档位：**5000us / 4dB** 画面对比最好、检测 bad 3 根；**20000us 全白过曝**（输出恒定 ~5667B）；3000us/1.8dB 太暗，19 根糊成灰条纹且 bad 涨到 9 根（全是误判）。
- 用户要求 10dB 增益时：曝光必须降到 **2000us**（2500us 起过曝），此时 bad 仍为 3 根；1000us 偏暗出 5 根 bad。
- 用 JPEG 字节数判过曝/欠曝：~50KB = 有细节，~5.7KB = 纯白/纯黑。
- `gf19 已关闭(GF19_ON=0)` 时 `finger_det.boxes` 为空（画面无叠加框），但逐根数据在 `fingers.fingers[].box`；开关在工控机上，本机改不了。
- 检测要重新抓：`POST /api/aoi/detect?port=10082`（内部走 `POST /capture_detect`，空 body）。

## 记录示教点
- `POST /ctl/record_point {name}`，白名单含 金手指点1/点2/准备点/侧面点0~3/安全点N/slot1~7/space1~7。AOI 点走 `tools/record_point_sdk.py`，同时写 `data/skills/l2_atomic/taught_points.json` 与 `reports/aoi_points/<点名>.json`（配置中心读台账）。
- 该脚本原本硬依赖 `~/zmax/zmax_data/rokae_sdk/tcp_out/latest.json`，而 rokae_tcp_sampler 容器在本机常年不起 ⇒ 任何点都录不了。已加兜底：读不到就改读 `8793/pose`（它本身回退 Orin 39061 珞石桥，endInRef 同口径）。
- **兜底要连前置闸一起拆**：`main()` 里还有一道 `if not os.path.exists(SRC): print("❌ 读不到真值源"); return 1`，
  它先于采样执行，光给 `_one()` 加回落没用 —— 现象是加了兜底仍然报同一句「读不到真值源」。
  必须把这道 exists 判断删掉，让 `_one()` 自己 try/except 回落。
- 8793 调子脚本必须显式 `encoding="utf-8"`，否则 Windows 按 GBK 解 UTF-8 中文失败、stdout 变空，页面报「记录脚本无 JSON 回执」。
- 记录是零运动，不需要授权；6 帧极差 >1e-4m 会拒（臂必须停稳）。
- 带中文的 JSON **不要用 git-bash 的 curl**：`curl -d '{"name":"金手指点1"}'` 发出去是乱码，服务端回执里能看到 `收到 'ָ1'`。用 Python `urllib.request`，`json.dumps(..., ensure_ascii=False).encode('utf-8')` + `Content-Type: application/json; charset=utf-8`。
- **「记录」类按钮是写操作，不是只读探针。** 为了验证新按钮真点一次，会把生产示教点覆盖成**当下**的臂位姿；臂已经离开目标位，这个点就废了（实测把金手指点1 覆盖到另一处坐标，事后得按 6 帧回执的值写回并重新补 abc）。验证记录链路请走 API + 临时点名，或者先确认臂确实站在该点上。
- 回执里 `abc` 常常是 `None`（脚本只落 pos/quat）。显示或核对 a b c 时从落盘的 quat 反算（ZYX：`R = Rz(y)Ry(p)Rx(r)`，`p=asin(-R20)`、`y=atan2(R10,R00)`、`r=atan2(R21,R22)`），并同时写回 taught_points 与台账。

## 采集/训练（550C）
- 打包条件：`帧数 >= GS_MIN_FRAMES(120)` **且** `idle > 20s`（最后一帧后静置）—— 光凑够帧数不会立刻提交。跨度门槛 `GS_MIN_SPAN_M=0.10`。
- 状态：`http://192.168.23.70:8806/health`（cur.frames / config / trains_submitted），历史 `sessions.jsonl`，日志 `daemon.log`。
- 550C 无 swap、32G 内存，load 常态 15~35；卡死时先 `systemctl disable zmax-550c-shadow zmax-evolve-intel zmax-symmetry-evolve` 降载。
- `gs_render_stream_intel.py` 对已 `_normalized=True` 的 cameras 不能再乘 S（会推出点云 8 米全黑），用 `S_cam=1, center=0`。

## 提示音
- 原 `tools/motion_beep.py` 用 paplay/pw-play/aplay（Linux 音频），Windows 上启动即退。改用 `tools/motion_beep_win.py`（winsound.Beep，轮询 8793/pose：>3mm/s 660Hz、>25mm/s 1050Hz、z 上涨 880Hz×3、不动静音）。
- `_beep_alive()` 原本扫 `/proc`，Windows 恒 false ⇒ 「抬升」被安全闸一律拒发。已改成 Win32_Process 同时认 motion_beep.py / motion_beep_win.py。

## 改站台页面的排版
- `#goldbar` / `#sidebar` 走 `.slotbar{display:grid;grid-template-columns:repeat(7,minmax(0,1fr))}`，窄屏媒体查询里降到 4 列。往里插 `grid-column:span N` 的宽内容，只要 N 或内容宽度超过当前行剩余格，会**静默换到下一行**（实测 span 3 的面板被挤到按钮下面，「显示在按钮右侧」直接不成立）。要「按钮 + 旁边一块信息面板」同行同高，就把两者包进一个 `grid-column:span N` 的 **flex 容器**里，别单独给面板设 span。
- `.panel img{aspect-ratio:4/3;object-fit:contain}` 是全局规则：960×330 的金手指条带塞进 4:3 框会上下各留 80px 黑边、图被缩小，看着像变形/不齐。给该图单独 `#i_aoi_gold{aspect-ratio:960/330}`。
- **「窗口太小」优先用整行 + 真比例，不要先加 `max-height`**：`max-height:46vh` 会压过 `aspect-ratio` 把图压扁（实测 713×195，比例 3.66 而非 2.91），看起来又像变形。做法是给面板加 id 后 `#p_gold{grid-column:1/-1}` 占满 `.grid` 整行，图只留 `aspect-ratio` + `width:100%`。
- **辅助终端不要占图像区**：用户明确要求「把终端挪到最下面，按钮下面」⇒ 把 `<div class="term">` 从各 `.panel` 里摘出来，在 `</main>` **之后**建 `#termbar{display:grid;grid-template-columns:1fr 1fr;gap:10px}` 统一摆两个。移动只改 DOM 位置，`aoiTermTick(id)` 仍按 id 取元素，JS 不用动。改完用 `panel.contains(termEl) === false` 验一句。
- 「没变就不重建」的缓存键（`bar.dataset.sig`）要带上**值的指纹**（例如 `recorded_at`），否则数值更新了页面不重绘，会误判成写入没生效。
- **内联 `<script>` 里的 JS 字符串不能直接写 `</script>`**：HTML 解析器不看 JS 上下文，遇到这串就提前闭合脚本块，整段 JS 全废（表现是函数「未定义」、页面半残、`typeof fn === 'undefined'`）。拼弹窗 HTML 时写 `'<\/script>'`。
- 给某张图加「右键/双击打开独立大窗口」用**事件委托**挂在 document 上（`e.target.closest('#i_aoi_gold,#i_aoi_surface')` + `preventDefault()`），不要给每个 `img` 直接绑：这些图的 `src` 会被定时重设，直接绑的处理器会丢。
- **大窗口页面必须由服务端给（真路由），不要 `window.open('') + document.write`**：实测部分 Chrome 写成空窗口（标题对、内容全空，`getElementById` 全 null），而 CDP 里 `attachToTarget` 之后的 `evaluate`/截图仍打在主页上下文，根本分不清是弹窗被拦、`write` 失败还是别的原因。做法：加 `GET /aoi_big?name=<stream>` 返回整页 HTML（黑底 + `img` + HUD），页面侧只 `window.open('/aoi_big?name='+name, 'aoibig_'+name, 'width=1680,height=920,...')`。真路由还能直接开 tab 验证、可收藏、可贴给别人。
- 大窗口的交互（用户会立刻追问「能继续放大么」）：滚轮以光标为中心缩放（25%~1600%，`transform-origin:0 0` + `translate/scale`）、左键拖动平移、双击切全屏、`0` 复位 / `1` 归 100% / `+``-` 步进 / `R` 重连、`Esc` 退全屏，右上角 HUD 显示倍率并在鼠标移入时淡到 ~28%。**要主动说明放大是显示放大**，不增加分辨率：规整图只有 960×330，过 300% 就是像素块，看细节应切「原图」那路（2448×2048）。
- 「规整图 / 原图」是**同一个 img 换源**（按钮的 `data-stream`），右键时要认当前 `src` 里的流名（`new URL(im.currentSrc||im.src).pathname.match(/\/([A-Za-z0-9_]+)\.mjpg/)`）。写死流名会表现为「看原图却弹出规整图」。
- **mjpg 是长连接，`img` 不能预置 `src`**：先写死 `src=".../x.mjpg?t=0"` 再让 JS 设成带时间戳的 URL，浏览器会把两条请求当同一个流复用 ⇒ 画面**停在第一帧**（用户原话「独立窗口怎么不跟着我的移动变化呢」）。只由 JS 设一次。
- **停帧自愈不能只靠 `onerror`**：worker 停帧时 TCP 还活着，`error` 不会触发，画面静默定格。每 4~5s 取 `/stats` 的 `age_s`，连续两轮 >6s 就换 `src` 强制重连（主页面那套 6s `frames_served` 心跳同理）。

## 规整图「一直在晃」

现象：`/aoi_gold.mjpg` 每帧上下跳一大截，但工件没动、亮度也没变。

- **先量化再动手**：连抓 3~5 帧存 jpg，取**行亮度剖面**（每行均值），对基准帧做一维互相关找位移。实测水平 0px、垂直 -41px、平均亮度差 0.2% ⇒ 不是工件在动、也不是曝光在闪，而是**工控机每次 `grab=1` 都重新走一遍模板裁剪（~486ms），裁出的行带位置本身在跳**。
- 修法在显示层：模块级缓存首帧的行剖面作基准，每帧算最佳位移后 `cv2.warpAffine` 平移回去，`borderMode=cv2.BORDER_REPLICATE`（不要黑边填充，黑边会被当成画面内容）。只对那一格生效。
- **对齐做完还会剩一种「逐帧微抖」，来源是几何校正矩阵自己**：每帧重新拟合四角 ⇒ M 逐帧微变 ⇒ 整个画面轻微呼吸。修法是给 M 做指数平滑（旧 85% + 新 15%）再归一化（`M / M[2,2]`）；同时给垂直对齐的参考帧加**相关性门槛**（最佳相关系数 < 0.75 就换基准），否则工件被挪走后仍硬按旧基准拽画面。实测帧间位移压到 0~1px。
- **只动显示帧**：送 YOLO 的那张仍由工控机产出。这个项目一直守「页面看到的 == 模型输入」，任何几何加工都要留在这条线以内。
- 顺带：判断「整体旋转 vs 镜头透视」时也要按单根条纹追中心（见上节），跳变量与条纹节距同量级时按序号配对会凭空量出十几度。

## 从图里量倾角（本机 PIL 怎么跑）
- **尺寸对了不代表画面对了**：每改一次裁切/缩放参数，抓一帧后先自己用视觉看一眼再报给用户 ——
  宽度高度都对得上、但内容可能已经切到触点、边缘留了空洞、或糊成一片。只看 JPEG 尺寸就回
  「已改好」，会在下一轮被他一句「还是不全 / 又补多了」打回。
- 系统 Python **没有 numpy / PIL**；`D:\ZMAX\Z-MAX_Console.exe`（PyInstaller 包）里带 cv2/PIL/numpy，图像分析直接用它跑：`"D:/ZMAX/Z-MAX_Console.exe" script.py <img>`（stderr 会有 `getdata` 的 DeprecationWarning，无害）。
- **周期性条纹不能按「同一序号」配对上下带的边缘**：间距 ~45px 时错配一个周期就凭空量出 12° 倾角（实际 <0.2°）。正确做法：挑一根条纹，在 4~5 个高度上追它的**中心**再拟合斜率；要判断「整体旋转 vs 镜头透视」，就把从左到右每根都量一遍 —— 全同向同度=旋转（可 deskew 补偿），两侧反向发散=透视（旋转补不掉，得在采集端做 homography 或镜头标定）。
- 金手指这类 `kind=crop` 判据图是工控机 template 规整后透传的（残余倾角标称 -0.25°）。默认**不要** deskew/natural/resize —— 会让页面那张和送 YOLO 的判据图不是同一张。但「整排歪」不是单根条纹歪（见下节），用户反复要求时必须修，修在**显示层**，并明确告诉他送检图未改。

## 规整图「不正 / 歪斜」的正确量法

用户说「歪」时**不要只量单根条纹的倾角**：实测单根 -0.25°（几乎垂直），于是怎么量都「没问题」，连着三轮都答不到点上。真正歪的是**整排的上下边界**：上边界 +2.72°、下边界 +2.17°，右边比左边低约 45px —— 人眼看到的「整块板歪了」就是这个。

量法（PIL 逐列扫描，用 `D:\ZMAX\Z-MAX_Console.exe` 跑脚本）：逐列取亮区（灰度 > `(min+max)/2`）的上下沿，只留高度 >45% 图高的完整条纹列，丢掉上下沿偏离中位数 >25% 图高的离群列，再对 `(x, top)` 与 `(x, bottom)` 各拟合一条直线。两条线的斜率即「歪」的量，同时能区分整体旋转（两条同向同度）与透视（发散）；发散时用左右端点截距直接取四角。

**量完要如实回答「正不正」，别默认他要改。** 走到 origin + `quad→矩形` 的路线之后，倾斜在
裁切那一步就被拉平了：实测 19 根条纹的**亮度质心**拟合直线，倾角只有 **+0.080°**
（1341px 宽上右端低 3.8px，属于测量噪声级）。这时正确回应是「数据上是正的，0.08° 肉眼看不出」
＋给一个手动旋钮（`ZMAX_GOLD_ROT_DEG`，`getRotationMatrix2D` 绕中心转、`BORDER_REPLICATE`），
而不是继续改几何 —— 反复「纠正」只会把已经对齐的东西又弄歪。
质心量法：逐列求亮区质心行 → 以条纹中心 x 为自变量拟合 `y = a x + b`，`atan(a)` 即整排倾角；
低矮图（<150px）上不能用「追单根条纹上下端」那套，边缘检测会失效、量出 +6°~+12° 的假值。

**先分清「歪」是真几何问题，还是「看不清」。** 用户连着四轮说「还是歪斜」，我三次都在
纠正几何（homography → 逐列 remap），全被退回 —— 他要的其实是看得清，不是纠形。
但也不能靠「拉长」去解决：`h*3` 纵向拉长会被立刻否掉（「你怎么还拉长的更长了呢」），
因为那是**在一张已经被拉长过的图上再拉一次**。根因见下面第 0 步。

决策顺序（照这个走，别跳）：

0. **先确认手里这张图是不是原像素。** 工控机 `GET /picture?kind=crop` 给的 960×330
   并不是原图里金手指的样子 —— 它是把原图 **1456×89** 的条带**纵向拉伸约 3.7 倍**得来的。
   所以在它上面做任何「还原」（压回真实比例、纠倾角、加边距）都是猜，越还原越缺料 ——
   实测压回真实比例后右下角直接缺一块，用户原话「右侧下部在扩大，不完整」。
   **要原图就去取原图**：`GET /region` 取 `region.quad`（原图坐标，顺序 左上/右上/右下/左下）
   与 `region.w/h`，再 `GET /picture?kind=origin&grab=1` 取 2448×2048，
   `getPerspectiveTransform(quad, 同尺寸矩形)` + `warpPerspective` 裁出 **1455×70 的原像素**。
   不缩放、不拉伸、不插值 —— 这是唯一让用户认下「完整」的做法。
1. **裁切范围必须外扩，横向/纵向要分开给倍数 —— `quad` 只圈到条纹本体。**
   右下角的焊盘/连接端在 quad 外面，照原样裁会被说「右侧、下面你截断得太多了，把右下角找回来」。
   四角**同比例**外扩（×1.14）不够：quad 只有 70px 高，而连接器整体约 230px，
   所以**纵向必须多放、横向几乎不用放**。做法：以四边形中心为原点
   `src = c + (src - c) * (GX, GY)`（x 用 GX、y 用 GY），输出尺寸同步 `ow*GX × oh*GY`。
   **起始值 GX=1.02 / GY=1.85（约 1484×130），但用户会继续要求收紧 —— 实测最终收敛在
   GX=0.95 / GY=1.55（1382×108）**，再往下就开始切最外两根了。
   纵向不要一步给到 3.2 —— 那样上下空太多，用户会连说「补多了、减少」，然后一轮一轮往下试
   （实测 3.2 → 2.45 → 2.10 → 1.85 → 1.72 → 1.55 才落定）。**从紧的开始给**，因为「少一点」
   比「补回来」更容易判断；微调按 0.1~0.15 一档，每改一次抓帧 + 量尺寸给他看。
   `GX < 1.0` 意味着向内裁（会切掉最外两根的外侧）—— 用户明确要「左右也收」时就给，别拿
   「会切到」当理由拒绝；只是要在回执里点明代价。
   判据：上到下依次是「黑外壳 → 19 根触点 → 下方金色基板」，上下只留细黑边。

   **只收单边**（「只有左边收一点，其它边不动」）：不要动 GX，直接改对应两个控制点的 x ——
   `_trim = ow*0.03; src[0][0] += _trim; src[3][0] += _trim; ow -= _trim`（左上/左下），
   右两角与上下边一个像素都不碰。**输出宽度同步减掉**，否则内容会被横向压扁。

   **「高度变成 N 倍」与「不要拉长」不是一回事**：前者是他主动要的显示放大，一句
   `cv2.resize(out, (ow, int(oh*VS)))` 只改高度即可（实测 ×2 后 1341×216，触点上下两段更清楚）；
   后者骂的是「为了把画面摆正而纵向拉伸」（`h*3` 那种，会在他已经嫌长的图上再拉一次）。
   两者别混为一谈，也别因为挨过一次批评就拒绝放大。
2. 确实需要放大才看得清时，**等比**放大（宽高同乘、`cv2.resize` 插值），不要只拉一个方向。
   比率一变，页面 `#i_aoi_gold` 的 `aspect-ratio` 必须同步改，否则图被压扁、又被当成「变形」。
3. 整体几何确实歪（整排上下沿斜）才动 homography：四角 → `getPerspectiveTransform` +
   `warpPerspective`，`borderMode=BORDER_REPLICATE`（不要黑边填充）。它只能修「整排斜」，
   **修不掉边缘单根的局部弯曲**（实测最右两根 -2.35°/-1.86° 校正后仍是 -2.35°）。
4. 边缘单根也歪（镜头畸变）→ 逐列 remap：每列的上下沿各自拉到 0 和 h。实测极差 3.47°→0.74°、
   全部落在 ±0.37° 内，确实「正」了 —— **但代价是条纹横向粗细不均**，用户看成品仍会说别扭。
   只在明确要求「必须垂直」时用，用前先把两个代价讲清楚。
5. 走 origin 路线后帧率会降：origin 每帧约 0.7s（crop 只要 0.13s），1.5fps → 约 1.3fps。
   真要提速就只在页面有人看时才走这条路，别为了帧率退回拉伸图。

共同约束：加工只挂在**显示层**（`_rectify_gold_show`），送 YOLO 的判据图始终是工控机那张；
留 `ZMAX_GOLD_RECTIFY=0` 关闭开关；顺序是先做帧间垂直对齐再做几何处理。
输出尺寸一变，页面 `#i_aoi_gold` 的 `aspect-ratio` 必须跟着改（960×330 ↔ 960×990），
否则图会被压扁、看起来又像「歪了/变形」。

⚠ 逐列扫描前把 `g.min()+g.max()` 转 `float`：uint8 相加**溢出**会让阈值算错，整图二值化成一整块，量出「斜率 0.00°、四角正好是图像边界」的假结果，看着像「本来就不歪」。
