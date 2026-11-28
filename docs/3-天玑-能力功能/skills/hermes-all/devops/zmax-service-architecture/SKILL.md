---
name: zmax-service-architecture
description: Use when maintaining Z-MAX services or arch map.
---

# Z-MAX 标准服务与系统架构

## 用户红线：不许抢鼠标 / 不许替他开窗口

- **不要替用户启动 GUI**（`launch_zmax.vbs`、桌面快捷方式、任何 Qt 窗口）。窗口一 show 就抢焦点，
  他正在打的字会断、正在点的鼠标会丢 —— 用户原话就是「别抢我鼠标」。他要开，自己会双击。
- 验证界面改动只用**只读手段**：`curl` 端点、读日志、`Get-NetTCPConnection -LocalPort ... -State Listen`、
  `Get-Process | Select MainWindowTitle`。**不要** `MoveWindow`、`SetForegroundWindow`、模拟点击、
  坐标盲点，也不要为了"确认能不能打开"替他把页面/窗口拉起来。
- 需要重启或重开时，把动作交给他的手："关掉控制台后跑这条命令"，而不是我起。
- 替换 exe、改桌面图标、动他正在用的程序文件，**先问再动**。

## 开场巡检（用户说「元气恢复」「现在什么状态」时）

不要问他要查什么 —— 直接跑一轮探测，用**实际数字**报一份状态，只展开异常项。
三条并行命令就能覆盖：

```bash
date; powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object {$_.CommandLine -match 'ZMAX|zmax'} | Select ProcessId,Name"
netstat -ano | grep LISTENING | grep -E ":(8793|8797|8799|8802|8794)\b"
ipconfig | grep -E "适配器|IPv4|默认网关"
for ip in 192.168.23.66 192.168.23.70 192.168.23.23 192.168.23.160; do ping -n 1 -w 800 $ip >/dev/null && echo "$ip OK" || echo "$ip FAIL"; done
```

判据（齐了才算“元气在”）：

- 本机 8793 / 8797 / 8799 / 8802 在听，且 **8797 的 HTTP 能回包**（`curl` 不是 000/exit 52 ——
  只测端口会漏掉“孤儿进程占着 socket 不干活”）。
- USB 网卡带着 `192.168.23.100`；掉了就ping 全 FAIL，参 memory 里的静态 IP 配置。
- 对端 8816 / 8806 / 8888 能回 JSON，而不是只看 ping。

常见的不健康态按概率排序：

1. **子服务成孤儿**（主程序退出后 8793/8797/8802 还在）→ 首页功能模块空白、左侧平台卡取不到。
   先杀孤儿再启动，别在页面上反复刷新。
2. **8797 只占端口不处理请求**（`/api/arm/*` 全 000）⇒ 动臂类按钮全失效，但 8793 页面看着正常。
3. **对端 550C 整机饥饿**（load 40+、ping 通但 HTTP 全超时）⇒ 先降载，见
   `references/3dgs-render-diagnosis.md` §4.5。

报状态用“全部通过 / N 项异常”开头，异常项才展开到
“现象 + 根因 + 下一步”。不要把每条探测命令和返回都贴一遍。

## 目录契约

```
D:\ZMAX\server\            ← 所有标准服务的家 (v5.50.786 起)
├── services.json           ← 服务清册单一真源: 28 项, port/script/host/system/layers/hw
├── arch_map.json           ← 架构唯一依据 (125KB, tools/gen_arch_map.py 生成, 勿手改)
├── README.md               ← 端口速查 + 分层说明
├── web/arch_map.html       ← 架构图 (fetch arch_map.json)
├── web/arch_map_standalone.html  ← 数据内联版, 双击可开
└── *.py                    ← 44 个: 22 个服务脚本 + 22 个它们 import 的兄弟模块
```

**复制而非移动**: `Z-MAX_Console.exe` 的 PYZ 里硬编码了 `tools/xxx.py`。
直接 mv 会让在跑的服务找不到脚本。`launch_zmax.ps1` 改成 server/ 优先、tools/ 回落。

## 分层铁律：算法进 `policies/`，节点只做壳

写任何检测/判据/识别/分类逻辑之前，先问一句**它属于哪一层**——放错层的代价不是报错，
是「功能看着有、但状态空间工程里查不到它」，用户会直接问「代码是在光学质量检查节点里吗」。

```
src/lerobot/policies/aoi/          ← 算法真身（判据/阈值/测量/推理都在这里）
  quality.py      inspect_aoi() 唯一入口，串起下面几路
  gold.py         工控机 10082 真判决搬运
  gold_yolo.py    本机 YOLO 推理
  gold_geometry.py 几何测量 + 封装约束校验
  surface.py      表面 10083
src/lerobot/middleware/nodes/impl/
  ss_aoi.py       ← 节点薄壳：取 ctx → 调 policies → 原样返回业务 dict
server/ + tools/  ← 标准服务与命令行工具，**不是**状态空间工程的层
```

规则：

- **节点脚本里不许出现阈值、判据、分类逻辑**，只做「拿 context、调算法层、把业务字典返回」。
  在 `ss_aoi.py` 里加判据，等于把算法从 10Hz 动作循环里割出去，节点自己和下游都拿不到。
- **先在 `policies/<域>/` 里找现成的旁路**再写新文件：AOI 已有 gold / gold_yolo / surface 三路，
  新能力通常是「加第四路并挂进 `quality_report()` 的返回字典」，不是另起一个服务。
- **回写要进返回字典**，不是只打日志。`quality_report()` / `inspect_aoi()` 的 dict 是节点对外的
  唯一口径；只 print 的东西页面上永远看不到，会被判成「没做」。
- **算法层不能 import middleware**（方向反了就是循环依赖）。要跨层只走「节点调算法」。
- 调用方（8793 这类服务）可以 `import` 算法层做旁路，但**同一份算法不要在两处各写一遍**：
  先迁到 `policies/`，服务再 import 它。历史上 `tools/` 与 `server/` 各存一份同名脚本、
  改了不生效的坑，在分层上会以「节点里没有、服务里有一份野的」的形式重演。
- **重活要缓存**。节点循环预算 100ms/拍，抓图 + 测量的单次成本可能 0.8s；
  用 `_X_CACHE = {"v": None, "t": 0.0}` + 60s TTL，别每拍都跑。

## 远程访问：链接要指「访问者所在网段的那个 IP」

从外网段（corp guest `10.163.x`）看服务页时，页面里凡是写死产线网 `192.168.23.x` 的链接
**一律打不开**——生产网段对 guest 不可路由。这不是服务故障，是地址选错。

- 先查本机在各网段的口子：`Get-NetIPAddress -AddressFamily IPv4`（WLAN 那种是 guest 网地址）。
- 汇总页里给远程用户看的入口，必须用 **guest 网那个 IP**；产线网 IP 的那条保留给现场用。
  两条并存比二选一好：现场和远程各自点得通。
- 对端汇总索引页在 Intel 550C 的 `/home/intel/zmax_web/console/index.html`（nginx `8888` 直吐静态文件，
  改完不用重启，刷新即生效）。改前先 `sftp` 存一份 `.bak-<日期>`。
- 加完入口用**实际 HTTP 状态码**验收，不要只看 HTML 里 grep 到那串地址：
  对每条链接 `curl -s -o /dev/null -w '%{http_code}' <url>`，200 才算通。
- **`a.click()` 验证不了 `target="_blank"` 的入口**——脚本点击被拦，URL 不变；
  直接 `goto_url()` 打目标地址来验，别据此判「链接坏了」。

## 页面精简：数据源不存在的块要整块收掉，别留红字

Windows 冻结包里不少页面的状态条数据源是**对端才有的端口**（典型 `8796/status/all`）。
这类块永远显示「状态源离线」，占一整行还吓人，而它 `title` 里通常写着真实数据源，
一眼就能确认是不是死的：`grep -n 'id="zstat"' -A 2 <页面html>` 看那个 `title=`。

- 收起放在**降级函数**里（`degrade()`），不要直接删 DOM：数据源某天回来了，
  删掉就再也显示不出来；`display:none` 一行注释就够回滚。
- **先确认块的边界再隐藏**。父容器把「有用的」（模型明细、状态）和「死的」（资源四格）
  装在同一个 `div` 里是常态；按 `id` 精确定位子元素，别 `root.style.display='none'` 一刀切。
- 隐藏后必须回验三件事：目标块 `display:none`、页面上不再出现那串红字、**其余按钮/画面数量不变**
  （例：`document.querySelectorAll('button[data-skill]').length` 前后一致）。

## arch_map 生成的两个必踩坑

1. **画布 `flows/state_space_obs.json` 没有 layer 字段**。层级靠 15 个 `row_bg`
   层级带的 **y 区间几何划分**推出 (节点 y 落在哪个带就属哪层)。改名或移动层级带会让映射整体错位。
2. **「执行层」必须归 L1**。画布里那条带叫「🔧 L2 基础辅助功能 · 执行层 (执行器 → 物理闭环)」，
   名字里带 L2 但按口径 L1 = 机器人接口(执行器/安全/物理世界)。算成 L2 的话
   **系统 0 一个节点都没有**，三系统断一环。判断顺序：先看"执行层/执行器"关键词，再看 `\bL([1-5])\b`。

## 系统 ↔ 层映射 (老倪 2026-11-26 定)

```
S2 慢思考 1~10Hz    ← L5 场景理解+自动标注 · L4 自主安全/流形世界模型
S1 快反应 10~100Hz  ← L3 连续功能 · L2 基础功能
S0 反射   200~1000Hz ← L1 机器人接口
```

## 架构图 UI 要点

- 241 条连线**全画**会糊成一片 ⇒ 按关系远近分透明度: 同层 0.30 / 同系统跨层 0.15 / 跨系统 0.06。
- 头部 flex 元素必须 `white-space:nowrap; flex-shrink:0`，否则中文被压成竖排单字。
- 改完 `arch_map.json` 要重新内联生成 standalone 版 (替换 fetch 为 `window.__ARCH_MAP__`)。

## ⚠ server/ 与 tools/ 脱节会静默失效

`launch_zmax.ps1` 现在是 **server/ 优先**。只改 `tools/` 不同步 `server/`，服务会跑旧版 ——
表现不是报错，而是“改了没生效”或“端点 404”。实测：8799 的 `/api/services` 返回 404，
因为 `server/dashboard_server.py` 还是 3.6KB 旧版，新版 21.6KB 在 `tools/` 里被绕过。

每次改完 tools/ 必须校验一遍：

```bash
for f in server/*.py; do cmp -s "$f" "tools/$(basename $f)" || echo "★ $f 不一致"; done
```

无输出 = 全部一致。`server/web/` 下的 html 同样要比 —— 而且**浏览器拿到的是 server/ 那份**：
`tools/web/station.html` 只是源，`server/web/station.html` 才是 8793 实际吐出去的。
只改 tools/ 那份，`curl /station` 逐字节没变，很容易判成"改了没生效"或"浏览器缓存"，
然后去查无缓存头、去重启服务，一圈都白走。

**而且 8793 每次请求都重读盘**，改对文件后根本不用重启：

```bash
curl -s http://127.0.0.1:8793/station | grep -c '<新文案>'   # >0 即已生效
```

为改一行文案去重启 8793 是纯风险 —— 一重启就得原样抄回 `--local2-url/--local2-label/--local2-fps`，
漏了中央相机那一格静默变黑。先 `grep` 验证，再决定要不要动进程。

**只比对“同名文件”不够 —— 依赖模块根本没进 server/ 时不 manifest 任何“不一致”，
而是到运行期才炸。** `tcp_ar_server.py` 一跑就
`ModuleNotFoundError: No module named 'laptop_cam_solve'`，现象是 AR 3D 端口一片 000。
建 server/ 时只复制“服务脚本”本体是常态陷阱：每个服务还 import 十几个 `tools/` 下的
兄弟模块（`scene_overlay` / `opt_box3d` / `ar_mujoco_env` / `fence_store` …），它们不会自己跟过来。

补齐用迭代扫描（会连带发现依赖的依赖）：

```bash
python tools/fill_server_deps.py    # 扫 server/*.py 全部 import, 从 tools/ 补同名 .py, 迭代到无新增
```

实测一次补了 20 个（分 2 轮 —— 第 2 轮才发现上一轮补进来的模块自己还差 `ar_mujoco_urdf`）。
脚本在 `tools/fill_server_deps.py`，以后改了 server 依赖随时重跑。

**新增一个标准服务 = 三处都要动**：`server/services.json` 登记 · `server/` 放脚本 ·
`launch_zmax.ps1` 加“端口没听就拉起”的块。少最后一步，服务每次开机都得手动起，
而依赖它的按钮/页面只会给一句“服务不可达”。

## 控制台侧

- `studio.py` 的 `ArchFlowBar` 从 `server/arch_map.json` 读真实节点数 (取不到则回落为实本文案，不编数)。
- **`tools/gui/` 下所有 py 都在 exe 的 PYZ 里**（不只 studio.py）—— 改源码**不重新打包不生效**，
  包括 `simulink_module.py`。交付时要说清"代码已提交，按钮要重新打包才进桌面版"，
  并给出**当前不打包也能用的既有入口**（例如双击节点），别让用户对着没变的界面猜。
- 画布工具栏按钮统一走 `mk_btn(text, tip, fn, color)` 工厂 + `FlowBar`，
  新按钮只需 `self.btn_x = mk_btn(...); tl.addWidget(self.btn_x)`，别自己写一套样式。
- **新增打开入口必须复用已有的打开函数**，不要为同一个页面写第二条路径。
  既有函数里若硬编码了 `xdg-open`（Linux）当 fallback，Windows 上等于死路 ——
  按 `sys.platform` 分支到 `os.startfile` / `open` / `xdg-open`。
- 打包 → 验证 → 杀掉孤儿子服务 → 备份 → 替换 exe 与 `_internal` 的完整流程
  （含回退手法）见 `references/console-build-and-replace.md`。

## 服务重启纪律

- **systemd 管的服务，`pkill` 等于白干**。杀掉后 systemd 立刻用**默认配置**重启，
  命令行前缀设的环境变量 (`ZMAX_TCP_URL=... python3 xxx.py`) 全部丢失，看起来像"改了没生效"。
  正确做法：**把默认值改到脚本里**，再 `systemctl restart <unit>`。
  判据：`tr '\0' '\n' < /proc/<pid>/environ | grep KEY` —— 空输出说明跑的是默认值。
- **`d.get("k") or default` 会把 `0` / `0.0` / `""` 当成缺失**。位姿中继里
  `float(d.get("age_s") or 9e9)` 把 `age_s=0.0`（最新鲜的值）判成 90 亿秒过旧，
  日志只说"真值过旧"，完全看不出根因。判缺失用 `is None`，不要用 `or`。
- **unit 里没写 `Environment=` 时，服务会静默退回一个不存在的默认地址，然后读陈旧文件**。
  症状：端点一直 200，但数据是几天前的（`age_s` 六位数、`stale=true`、`fallback_err`
  里写着"文件 Ns 没更新"）。排查顺序：`systemctl cat <unit> | grep Environment`
  → 与代码里 `os.environ.get("KEY", <默认值>)` 的默认值逐字比对 → 不匹配就补
  `Environment=KEY=真实地址` 再 `daemon-reload && restart`。
  **改环境变量、不改代码**，是对端最小侵入的修法。
- 查进程/端口用 `ss -ltnp` 或 `Get-NetTCPConnection -LocalPort N -State Listen`；
  **不要 `ps | grep 名字`** —— 会把自己、grep 进程和包装脚本一起算进去。
- **手动重拉控制台子进程必须带输出重定向**：
  `Start-Process Z-MAX_Console.exe -ArgumentList <脚本>,--port,<N> -WorkingDirectory D:\ZMAX -RedirectStandardOutput x.out -RedirectStandardError x.err`。
  不带重定向时子进程的 stdout 句柄无效，HTTP 响应写进去就**静默失败** ——
  症状是端口在听、TCP 连得上、`curl` 一律空回复（exit 52），日志里什么都没有。
  极易误判成"孤儿进程没救"或"脚本代码坏了"，实际只是启动方式错；补上重定向立刻恢复。
- **参数里带空格或 emoji 时不要用 `Start-Process -ArgumentList`**：PowerShell 会把
  `'🎥 中央相机 (Intel 8812)'` 拆成多个 token，子进程报 `error: unrecognized arguments: 中央相机 (Intel 8812)`
  然后退出，外面只看到端口没起来。这类多参数服务（8793 的 `--local2-label` 就是）
  用 Python 起最稳，数组传参不经过 shell，且能一并拿到重定向与脱离父进程：

  ```python
  p = subprocess.Popen([r"D:\ZMAX\Z-MAX_Console.exe", r"D:\ZMAX\server\cam_live_stream.py",
                        "--port", "8793", "--local2-label", "🎥 中央相机 (Intel 8812)"],
                       cwd=r"D:\ZMAX", stdout=out, stderr=err, stdin=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS)
  ```

  起完睡 10 秒再看 `netstat`：`alive: True` 却无 LISTENING 说明参数仍被解析掉，去读那份 `.err`。
- **降载必须 `stop` + `disable` 成对**。只 `stop` 的话重启后 systemd 原样拉起，
  压死过一次的东西全部复活，等于白降。停之前先记一份 `systemctl is-enabled` 清单，
  将来恢复按同样清单 `enable --now`，不要凭记忆。

## 3DGS 渲染 (Intel 550C · gsplat XPU)

- **`packed=True` 在 gsplat 的 SYCL 后端会崩**：
  `opacities.view(B,N)[batch_ids, gaussian_ids]` → `IndexError: shapes [0], [0, 2]`。
  `nnz=0`（没有高斯落进视野）时索引形状不匹配。改 `packed=False` 即恢复（实测 5.4 fps）。
- **`GS_RENDER_DEV=cpu` 不是退路**：XPU 版 gsplat 只编了 SYCL kernel，CPU 路径在
  `fully_fused_projection` 直接抛错（且 `import gsplat` 时就已打印 "Using SYCL XPU backend"）。
- 崩之前先分清**渲染问题**还是**资产问题**：PLY 的 `f_dc_*` 转 RGB 用
  `0.5 + 0.28209479 * f_dc`。均值 ≈ 0.5 且 std < 0.1 = 高斯还是初始化灰色，
  **模型没收敛**，渲染修好也只有白雾。此时正确结论是"要重采重训"，不是继续调渲染参数。
- `--sync off` 与 `--path-mode cam` **都**崩 ⇒ 与位姿无关，别再查 relay / 手眼。
- **两种对照都全黑（不是崩）时查归一化口径**：`cameras.json` 的帧可能带
  `_normalized: true`（平移已在 ±1 量级、围绕 0），渲染器若再按 `train_report.normalize`
  做一次 `S*(t-center)`，相机被推到点云外十几米 ⇒ 纯黑 JPEG（8~9KB），
  而 `/health` 的 ok / fps / src 全都正常，指不出问题。判据与修法见 reference §1.5。

- **渲染器可能被 `gs_force_out.conf` 钉死在某个老资产上**：`tools/gs_force_out.conf` 首行
  一行目录就强制指定资产（例：`out_merged_3k`），日志会打「强制指定 … PSNR留出 20.88」——
  此时新采新训的 `out_*` 根本不会被采用。看到"训练跑完了画面没变"先查这个文件，
  别去怀疑训练失败或 pick 逻辑。

完整判定顺序见 `references/3dgs-render-diagnosis.md`。

## 3DGS 采集 (autocap) 与训练

- **采集 daemon 自带 HTTP 状态口**：`8806/health`（当前会话帧数、跳过计数、生效阈值、
  已提交训练数）+ `8806/sessions`（历轮帧数 / 跨度 / trained / skip_reason）。
  对端负载高时 SSH 要等 banner 甚至连不上，这个口 60ms 就回 ——
  **监控优先走 HTTP，不要用 SSH 轮询对端**。
  自建守候脚本打基线时，**状态为空也要推进哨兵值**（`last_sess = sid or "__NONE__"`）：
  否则“当前无会话”的每一轮都判成首次，每 15 秒重打一条基线，通知把上下文刷满。
  同理**不要按帧数间隔报进度**（“每涨 40 帧报一次”在快走时会连报），只在四个状态迁移上出声：
  就绪基线 / 刚跨过帧数门槛 / 一轮结束（train id 或 skip_reason）/ 接口异常与恢复。
- 一轮会不会进训练看两条门槛：帧数（`GS_MIN_FRAMES`）与轨迹跨度（`GS_MIN_SPAN_M`）。
  **不达标的会话整轮丢弃，连 ds 目录都不保留**，事后无法补训。阈值调高就是当场丢数据；
  临时放宽用 drop-in（`/etc/systemd/system/<unit>.d/*.conf` 里写 `Environment=`）再
  `daemon-reload && restart`，别改 unit 本体。
- 采帧是按**末端位移**触发的（默认 0.4mm），同一条路线走快了帧数就少。
  "跨度够但帧数不够"先请用户走慢些，不要先怀疑相机或识别。
- 判断训练质量只看 `train_report.json` 的 `psnr_holdout_db`：十几 dB 是没收敛，
  和已上线的老资产（20+ dB、二十多万高斯）不是一回事。训练耗时也异常（3000 步跑一小时）
  时先查是不是被同机的影子推理 / 进化搜索抢了 CPU，见 reference 的整机饥饿一节。

## 位姿链路 (Orin 39061 → relay → 8797/api/tcp)

- **`conn_ts` 是建连/重连时刻，不是新鲜度**。它停在几小时前不代表数据陈旧 ——
  控制器重启后 Orin 会重连并刷新这个戳。判新鲜度看三处：`/health` 的 `sdk:true` +
  `calls` 计数在涨 + 值末位在抖，三者齐了就是活的。
  **反之 `calls` 归零或大幅回退 = 进程刚重启**（实测 195130 → 268 → 514），
  这期间的 503 是重启窗口，等几秒再测，别当成链路坏掉去翻代码。
- **机器人静止时位姿只在 1e-7 量级抖**（伺服保持），6 位小数显示出来就是“一个数都不变”。
  连采几次完全一致时，先确认机器人是不是根本没动，别直接判“数据卡死/吐缓存”。
- 位姿可能来自多条路（Orin 直连 39061 / Intel 的 pose-relay / 本机 ECS 隧道 19061），
  默认值写在 `tcp_ar_server.py`；`src` 字段标当前走哪条，`err` 非空才是真失败。
- 页面侧是否“跟随”是独立开关（`MIRROR.on` / 仿真臂 `VR.simArm`），10Hz 拉 `/api/tcp` 写 `PREV.q`；
  链路正常但臂不动时，先看是仿真臂被隐藏了，还是页面拿的是旧构建（标题旁有构建戳，比对 r 号）。

## 真机轨迹 (右臂跑真实轨迹)

页面 `bRTraj` → `POST /api/arm/step_traj` → `tools/rokae/arm_step_traj.py`，三层闸缺一不动：
授权 (`ctl.motion_armed`) · 控制器 TCP 可达 · Linux 执行环境。

**授权是限时窗口，到期就自动掉 —— 「怎么又不动了」第一件查的事。** `armed:false` + `left_s:0.0`
且 `until` 已过，就是窗口过期（默认 `window` 模式 1800s），不是链路坏了；续期：
`POST /ctl/arm {"on":true,"mode":"window"}`（`mode:"debug"` 无时限，要用户明确点头才用）。
`tools/ctl_auth.py arm` **开不了窗口**，它只会把当前状态打印一遍 —— 别拿它当续期命令。

Windows 移植版的清单（页面双份文件、子服务重启用 Python Popen、AOI 曝光/增益配对、
示教点双写与误覆盖风险、页面 grid/图比例、右键大窗口（真路由 + 缩放四件套）、
mjpg 停帧自愈、规整图晃动的对齐、以及「不正/歪斜」—— **先分清是嫌小嫌矮还是要纠正几何**：
纵向拉长、homography、逐列拉直全被退回，最终认的是「从 `kind=origin` 原图按 `/region.quad`
裁出原像素」）见 `references/windows-station-ops.md`。

**金手指裁切的真口径（2026-11-26 反复六轮才定）**：`/region` 的 `quad` 只圈住**触点那一排**
（实测 70px 高、1455px 宽），而整个连接器——上外壳 + 触点排 + 下方金色基板——有约 **230px** 高。
所以按 quad 直接裁、或四角等比外扩 14%，右下角一定缺肉（用户会连着说「截断太多」「还是没有全」）。
正确做法：**分方向外扩——横向 ×1.02 起、纵向 ×1.85 起**，再 `warpPerspective` 到 `ow*GX × oh*GY`
（约 1484×130）。判据是画面从上到下能依次看到「黑外壳 → 19 根金色触点 → 下方金色基板」，
且上下只留细黑边。**纵向别一步给到 3.2** —— 那会把上下空掉一大截，用户会连说「补多了、减少」。
**从紧的开始给**，实测一路收到 GX 0.95 / GY 1.55（1382×108）才落定；GX<1.0 就是向内裁、会切
最外两根，用户要「左右也收」时就照做并点明代价。
三种后续微调是常事，别当新需求：① 只收单边 —— 不动 GX，只把对应两个角的 x 加上 trim、输出宽同步减；
② 高度变 N 倍 —— `cv2.resize(out,(ow,int(oh*VS)))` 只改高度，这是他主动要的放大，与
③「不要拉长」不矛盾 —— 后者骂的是「为了让画面摆正而纵向拉伸」（在已被拉伸的图上再拉一次）。
**量完要如实说「正不正」**：走 origin 路线后倾斜已在 `quad→矩形` 那步拉平（实测质心拟合仅 +0.08°），
这时应回答「数据上是正的」＋给手动旋钮，而不是继续改几何把已对齐的东西又弄歪。

**量倾角要用「条纹亮度质心连线」拟合，别用逐条边缘追踪**。规整图只有 100~200px 高时，
逐条测上下沿会在每根内部乱跳（实测同一张图报 +6~12°、极差 27°，全是噪声），据此转一下
就把好好的图转歪了。可靠做法：按列求剖面 → 切出每根条纹 → 每根算亮度加权质心行 → 
对 (质心x, 质心y) 最小二乘拟合直线，`deg = atan(斜率)`。判据是首末质心 y 差 / 总宽。

**自动摆正（derot）可以加，但注意旋转方向的符号**：测出边沿倾角 `d` 后
`getRotationMatrix2D((ow/2, oh/2), angle, 1)` 的 `angle` **要和 `d` 同号**才是把右端抬起来。
实测第一版写 `-d`（按数学直觉"反向抵消"）结果从 +0.08° 变成 +0.36°，越转越歪；改成 `+d` 后
落到 +0.019°。角度测量**要缓存**（5s 够），逐帧重算会让画面自己抖。`borderMode=BORDER_REPLICATE`
避免黑角，`|d| < 0.02°` 就跳过不动。

**收敛后的参考参数**（2026-11-26 现场逐轮微调的落点，可作下次的起点）：
`GX 0.95 / GY 1.55`（1382×108）→ 左边单边 trim 3% → 上边单边 trim 5% → `VS 2.0` ⇒ **1341×206**，
实测质心倾角 +0.019°。用户说「上边沿再收一点」「只有左边收一点」这类**单边**要求时，
只动对应两个角的那一个坐标，其余角和输出宽/高按联动改，别整体缩。
这也解释了一路错下来的原因：工控机那张 `kind=crop` 的 960×330 是把 89 行**纵向拉伸 3.7 倍**
造出来的，在它上面做压缩/还原/拉直都是在猜，必须回到 `kind=origin`。

**用户报「臂不动」时不要直接下发位移去试，按这条阶梯逐段零风险验证：**

```bash
# ① 授权状态（只读）。数据文件在 C:\Users\Admin\zmax\zmax_data\ctl_auth.json，不在 D:\ZMAX\zmax_data
python -c "import importlib.util as u,json;s=u.spec_from_file_location('c',r'D:\ZMAX\tools\ctl_auth.py');m=u.module_from_spec(s);s.loader.exec_module(m);print(json.dumps(m.info(),ensure_ascii=False))"
# ② 取位姿（8793 的 POST 端点，只报数不下发，安全）
curl -s -X POST -H "Content-Type: application/json" -d '{}' "http://127.0.0.1:8793/api/aoi/guide?port=10082"
# ③ 8797 路由（dry 只回显，不动臂）
curl -s -X POST -H "Content-Type: application/json" -d '{"dx":0.1,"dry":true}' http://127.0.0.1:8797/api/arm/move_rel
```

①`armed:true` + ②`guide.act:"move"` 且带 `d_mm` + ③`ok:true,dry:true` ⇒ 前三层都通，
断点只可能在最后一步执行层：`rokae_sdk_run.sh` 找不到 `$SDK_DIR/xcoresdk_python` 会
`exit 2` 打印「⛔ 找不到 SDK」。这时结论是「某台机器缺 SDK 副本」，不要再回头查页面或授权。
注意 `/api/aoi/guide` 是 **POST-only**，GET 过去返回 `not found`，与路径不存在无法区分。

**③ 的 `dry:true` 在 handler 开头就 return 了，根本不进 subprocess** —— 它只证明路由与参数校验，
证不了执行层。要验执行层又不让臂动，发 `{"dx": 0.0001, "speed": 5}`：0.0001mm 能过
`max(abs(...)) > 1e-9` 的闸，走完整条 docker + SDK 链路，位移低于伺服精度、肉眼看不出来。
回 `ok:true, rc:0` 才算执行层通；`rc:2` 而 `raw_tail` 为空，几乎一定是 bash 层（见下条）。

- **Windows 服务里 `subprocess` 调 `bash` 有三道必踩的坎**，任一条都会让「命令行能跑、服务里跑不动」：
  PATH 先命中 `System32\bash.exe`（WSL；vhdx 丢了还报 `ERROR_PATH_NOT_FOUND`，且是 UTF-16 乱码）·
  把 `D:\...` 反斜杠路径喂给 bash，`dirname`/`cd` 失败、`set -e` 直接退出（**rc=2 且 stdout/stderr 全空**）·
  `text=True` 在中文 Windows 用 GBK 解码 UTF-8 输出抛 `UnicodeDecodeError`，异常发生在读取线程里，
  `rc` 照样 0 但返回值被吞，页面只剩 `ok:false`。
  修法（`_find_bash()` / `_msys_path()` / `encoding="utf-8", errors="replace"`）见
  `references/camera-and-robot-hardware.md` 的「从 Windows 服务里调 bash」。

- **ping/ARP 通 ≠ 服务在听**。控制器在线但 `30001/30002/30003` 全 closed 时，
  任何软件都连不上，结论只能是"控制器侧开远程控制/SDK"，不要改脚本。
  从同网段另一台机器复测一遍排除本机防火墙。
- **`rokae_sdk_run.sh` 能在 Windows 上跑通，别预设它只能在 Linux 侧跑。** SDK 是
  `cpython-310-x86_64-linux-gnu.so`，但这只要求**容器**是 Linux —— Docker Desktop 跑 Linux
  容器就够，`--network host` 实测能直连控制器 192.168.23.160。三处适配缺一不可：
  ① SDK 副本放到 `D:\ZMAX\zmax_data\rokae_sdk`（含 `xcoresdk_python`），用 tar+sftp 从对端拉，24MB 压完 6.4MB；
  ② 脚本先探测该目录、找不到才回落 `/home/ubuntu/...`；
  ③ **`command -v sudo` 在 Windows 11 会命中系统自带的被禁用 `sudo.exe`**，必须实测
  `sudo -n true` 通过才加 sudo，否则直接报「已在此计算机上禁用 Sudo」，看起来像脚本坏了。
  镜像 `ros:humble-ros-base` 要先 `docker pull`（约 1.16GB）。
  验证阶梯：`state`（只读，回位姿/关节/ec=success）→ `move-rel --dx 0 --dy 0 --dz 0`（零位移，回 PASS）→
  才让用户点真移动。完整配方见 `references/camera-and-robot-hardware.md` 的「执行环境」一节。
- `traj_step_state.json` 里 `running: true` 而 pid 已死会把后续下发**永久判成 busy**，
  清成 `running=False, pid=0`。判活看 pid 真在不在，不要只信 `running` 字段。

- **「执行器离线」先分清是文案还是闸**。页面顶部那行红字来自 `/station/status` 的
  `ctl.exec.online`，而它在页面代码里只参与拼文案，按钮的 onclick 并不检查它。
  判法：`grep -n "ex.online" <页面html>` —— 只有一处且在 `_L=` 赋值里 ⇒ 纯提示，
  按钮照样能发。真被拒时按钮旁边会把服务端原文摆出来（`⛔ 没发出去: <msg>`），**以那行为准**，
  不要被"不能动"的横幅带偏去查授权/链路。
- **执行器 `l2_daemon` 在 Windows 上起不来是架构不兼容，不是配置问题**：单实例锁用
  `fcntl.flock`（`No module named 'fcntl'`），绕过后命令通道 `os.mkfifo` 直接
  `AttributeError` —— 它是 Unix 命名管道模型。`_exec_health()` 也按 `/proc/*/cmdline`
  找进程，Windows 上恒为 `online:false`。含义：手动控制台的**技能按钮**在 Windows 侧不可用；
  「按位姿移动」走 8797 → `sdk_ctl` 那条路不经过 daemon，不受影响。
  要让技能面板可用，三条路：① 把 FIFO 换成 Windows 命名管道（独立工程）；② 把 daemon 放到 Linux 侧；
  ③ **实测已采用：平动技能直连绕过 daemon** —— `cam_live_stream.py` 在 `os.open(_L2_FIFO, ...)` 之前
  插 Windows 分支，按 `data/skills/l2_atomic/registry.json` 里技能的 `ros/axis` 翻译：
  `line_rel` + `x_pos/x_neg/y_pos/y_neg/z_pos/z_neg` → 8797 `/api/arm/move_rel` 的 `dx/dy/dz`，
  单次限幅 5mm、`dry=not want_real`，返回 `{ok, direct:true, axis, d_mm, move:{...}}`。
  实测 `L2.forward` 2mm 回 `ok:true rc:0 elapsed 7s`，臂真走了。
  **`pose_rot` 类（rot_a/b/c）走另一条直连**：8797 `/api/arm/rot_rel` 读当前 TCP 的 RPY、
  绕**工具自身轴**右乘增量矩阵、再回 RPY 喂 `sdk_ctl move-abs`（`--rx/--ry/--rz`，米/弧度），限幅 5°。
  技能参数 deg 的校验范围是 **[1, 30]**，传 0.5 会被参数闸拒掉、回一句「超出允许范围」。
  **绝不要用 `rpy[idx] += d` 直接改分量** —— pitch 到 ±90° 附近就是万向节锁：实测 B=-89.75° 时转 +1°，
  A/C 各跳 23°；反向转各跳 142°。姿态本身是对的，但控制器要横跨那么大的弧，走出来看着就是反的
  （用户原话「B 轴有时候正有时候负」）。用矩阵算姿态，并对 `|pitch| > 85°` 的 B 轴请求回
  `stage:"gimbal"` 的拒绝 + 提示「先用 A 轴或 C 轴把姿态转开」——拒绝要带理由，不要静默。
  `goto_point` / `goto_gold_pt1` 这类回点技能仍依赖 daemon，要一并明确拒。

  **方向键的真实端点是 `/ctl/move`（不是 `/api/move`）**，body 为
  `{skill:'L2.forward', d_mm:2, speed_mm_s:5, arm:1}`（`arm:1` 才真动，0 是演练）。
  页面里 `grep -o "post('/ctl/move',[^)]*"` 能看到全部调用形态。
  查端点别靠猜：先 `grep -o "'/api/[a-z/]*'\|'/ctl/[a-z/]*'" <页面html> | sort -u`。
  只修"检测"的话，`os.name == "nt"` 分支用 `Get-CimInstance Win32_Process` 查 cmdline
  （配 5 秒缓存），并把页面文案改成中性表述，不要说成"离线"。
  **这条 PowerShell 查询会匹配到它自己**：`Where-Object { $_.CommandLine -like '*l2_daemon.py*' }`
  会命中正在执行查询的 powershell.exe / bash.exe（它们的命令行里就含这个字符串），
  返回一个早已退出的 PID ⇒ `online:true` 的**假绿**。假绿比假红更难发现：页面显示"正常"，
  实际技能按钮仍然发不出去。必须排除 shell 本身，并复核 PID 真在：

```python
_ps = ("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*l2_daemon.py*' "
       "-and $_.Name -notin @('powershell.exe','bash.exe','cmd.exe','sh.exe','conhost.exe') } "
       "| Select-Object -First 1 -ExpandProperty ProcessId")
```

  页面侧的判断也要跟着改：三态（true / false / null）必须写 `ex.online === false` 才报红，
  `null` 走中性分支 —— 写成 `if(!ex.online)` 会把 null 一起判成红字"不能动"。

## 启动顺序 (8793 必须早于主程序)

主程序 `Z-MAX_Console.exe` 会自己拉一版**裸的** `cam_live_stream.py --port 8793`
（没有 local2 参数），且**不检查端口是否已被占用**。所以带参数的 8793 必须在它之前起，
主程序那份 bind 失败自行退出。

往 `launch_zmax.ps1` 插启动块后**必须查重复 spawn**：

```bash
grep -c 'Start-Process -FilePath $exe -WorkingDirectory $root -PassThru' launch_zmax.ps1
```

应为 1。插块时顺手把这段也复制进去很常见 ⇒ 主程序被拉两次。

手动重启 8793 时**先抄回原启动参数再杀**，否则 `--local2-url/--local2-label/--local2-fps`
丢掉后中央相机那一格静默变黑（不报错）：

```bash
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'cam_live_stream' } | ForEach-Object { $_.CommandLine }"
```

- **`.ps1` 必须存成 UTF-8 with BOM + CRLF**。Windows PowerShell 5.1 按系统 ANSI(GBK) 读脚本，
  UTF-8 无 BOM 的中文注释会解成乱码，把语法解析直接打断（`表达式或语句中包含意外的标记`），
  现象是整段不执行、只报 ParserError 行号，完全看不出是编码问题。
  写完补 BOM 再用 `Parser::ParseFile` 验语法：

```bash
python -c "d=open('x.ps1','rb').read(); open('x.ps1','wb').write(d if d.startswith(b'\xef\xbb\xbf') else b'\xef\xbb\xbf'+d)"
```

## 改页面/拼 HTML 的三个静默陷阱 (2026-11-26 实测)

1. **JS 字符串里不能直接写 `</script>`**。HTML 解析器不认 JS 字符串上下文，会把它当成脚本块
   结束符提前截断，后面整段 JS 变成裸文本 —— 症状是页面上连函数都没定义
   （`typeof openAoiBig === "undefined"`），而控制台没有显眼报错，很容易判成"缓存没清"。
   拼 HTML 时写成 `'</scr' + 'ipt>'`。
2. **Python 里拼 HTML/CSS/JS 模板不能用 `%` 格式化**。`height:100%`、`Math.round(z*100)+"%"`
   这类裸百分号会被当占位符，抛 `TypeError: not all arguments converted during string formatting`，
   端点直接 500（浏览器只看到空白页）。用 `@@TITLE@@` 之类占位符 + `.replace()`。
3. **mjpg 流不能给 `<img>` 预置 src 再用 JS 换 src**。浏览器把两条请求当成同一条长连接复用，
   画面永远停在第一帧 —— 用户会说"独立窗口怎么不跟着我的移动变化"。`<img>` 不带 src，
   只由 JS 设一次；再配 `/stats` 的 `age_s` 心跳自愈（连续两轮 >6s 就换 src 重连），
   因为停帧时 TCP 还活着、`onerror` 根本不会触发。

## 页面媒体地址

- 页面里的图片/流地址必须走**同端口相对路径**，不要硬编码第二个端口。
  端口从不存在时浏览器只显示黑框、**不报错**，极难发现。
  查法：取 `img.src` 看主机端口，再逐条 `curl -o /dev/null -w '%{http_code}'`。
  **Git-Bash/MSYS 的 curl `%{size_download}` 不可信**：配合 `-o /dev/null` 时实测一直报 0，
  哪怕 body 完全正常。判有无内容要 `curl -o 临时文件` 再 `file` / `ls -l` ——
  否则会把“200 + 37479 字节的 640x480 JPEG”误读成空响应，白查一轮。
  同名坑：某格写死 `127.0.0.1:8898/xxx.jpg` 而后端服务没起 —— 要回落到主服务的
  `/snapshot/xxx.jpg`，不要指望那个专用端口。
- **`store_true` 的默认值如果由环境变量反推，未设变量就等于关掉功能**。
  `ap.add_argument("--no-local2", action="store_true", default=not os.environ.get("ZMAX_CAM_LOCAL"))`
  ⇒ 环境变量没设时 `not None` = True ⇒ local / local2 两路被 `if` 直接跳过，
  **不报错、不打日志**，状态里只有 `online=False fps=0.0 age=-1.0`。
  看到"某格永远无帧但一切正常"先查这类反推默认值，别从相机硬件查起。
- 相机源对照 + 中央相机(Intel 8812) + 真机轨迹三层闸：见 `references/camera-and-robot-hardware.md`。

## 跨平台同步 (Windows ⇄ Ubuntu 双系统)

- 新顶层目录（如 `server/`）必须加进 `tools/sync_from_dzmax.sh` 的 `DIRS` 白名单，
  否则 Ubuntu 侧跑同步会**静默跳过**它，用户会以为已经对齐了。
- **用户说「必须同步」「马上同步」时，先做双向归档，不要覆盖现役文件。** 两侧同名文件经常
  不是同一个东西（`server/dashboard_server.py` 27KB 服务汇总 vs `zmax_550c/tools/dashboard_server.py`
  3.6KB 纯静态服务；一边 nginx+systemd、一边 exe 拉子进程），直接互盖会把对端搞挂。
  做法：Windows 改动 → 对端 `tmp_sync/<stamp>/`；对端改动 → 本机 `_sync_from_<host>_<date>/`
  （`sudo tar -czf` 后 sftp 拉回、**保留原路径层级**解包，便于按原位置对照）；
  两边各放一份 `CHANGELOG_<date>.md`，逐条写「改了什么 / 备份文件名 / 哪几项是平台特定不该同步」。
  归档完必须**明说这是归档不是合并**，再给真要合并的几条路让他选 —— 直接讲"同步好了"
  而实际只是拷了副本，是最容易被追着问的地方。
- Windows 侧 commit 完**不需要 push** 就能让 Ubuntu 侧看到：D 盘共享，Ubuntu 挂 `/mnt/wD/ZMAX`。
  push 交给有凭据的那一侧做。仓库状态整理见 `references/git-cross-platform-reconciliation.md`。

- **MSYS 下的 git 不认中文路径参数**：`git add 中文名.md` 会**静默吞掉**（rc=0 但暂存区里没有），
  表现得像提交成功、实际文件没进库。仓库里的文件名用英文，中文只放进内容。
- `git add -u` 会把 `src/` 下**被 Windows 物化成实体文件的 symlink** 一起提交（索引里 mode 120000，
  提交后 Ubuntu 侧的软链就变成实体副本）。只 add 明确列出的路径，别用 `-u` / `.` 收尾。
- 远程主机（Intel/Orin）的 SSH + 探活套路（paramiko 后台进程挂死、pkill 自杀、端口扫描）
  见 `references/peer-host-diagnostics.md`。
- **对端已有一套 Ubuntu 适配版服务时，改配置（systemd `Environment=`），不要整包覆盖** ——
  Intel 的 `/home/intel/zmax_550c/` 是 Linux 适配版（含 20+ 个 systemd unit、`--network host`、
  `.so` SDK），盖 Windows 那套会把它们一起弄挂。具体手法见上面那份 reference 的
  “往 Intel 部署/修服务”。
- **“服务都迁到 Intel 了”要按三层核对，不能凭印象**：
  ① `server/services.json` 的端口 vs 对端 `ss -ltn` 求差集（剥掉本就不该在那台机器的）→
  ② 差集里逐个 `find` 脚本，区分"真没代码"和"代码在但没起 systemd unit"（实测多数脚本代码早就在，
  只是没 unit）→ ③ 起了之后按 `/stats` **逐路**验 `online/fps`。
  端口在听、`/` 回 200、页面能打开，都证不了那一路有画面。
  迁到对端的是**另一份 fork**：路径可能写死 `/home/ubuntu/`、设备名 `--` 本机没有，
  html 也可能是旧版（没新增的格子）—— “数据通了”和“用户看得到”要分开报。
  完整步骤见 `references/peer-host-diagnostics.md` 的「启动了 ≠ 用户能看到」。

## 服务归集：把 28 项收拢到一台主机（控制台即服务站）

用户说「所有服务都常驻到 X」「X 就是控制台」时，**先按硬件依赖分三类，再动手**。
分依据现成：`server/services.json` 每条都有 `hw` 字段。

| 类 | 判据 | 做法 |
|---|---|---|
| **A 纯软件** | `hw` 为空 | 直接在对端起 systemd unit |
| **B 只依赖网络设备** | `hw` 全是 Orin / 珞石控制器 / 工控机这类能走网的 | 同上，对端有产线网就能跑 |
| **C 依赖本地硬件** | `hw` 含 USB 相机 / GPU / 深度相机 | **进程留原机**，对端只做反向代理 |

**C 类不要试图迁**：代码搬过去也是空的。实测在 Intel 起 8793，`/stats` 里
`arm`/`local`/`local2`/`depth` 全 `online=false`，只有走网络的 `aoi_gold` 活着。
正确形态是「对端 = 统一入口 + 软件载体，原机退化成硬件节点」，端口与页面保持与原地一致。
**这一层要主动跟用户讲清楚**，否则他以为你在偷懒 —— 但也要给出他真正能拿到的东西：
全部端口在对端可访问，只是请求被转发。

分完类再查**这些端口是否已被对端自己的实现占用**：常见结果是 C 类里一大半
对端早就有本地实现（Intel 的 8793/8802/8810/8806 都是它自己的），那些根本不用代理，
只剩真正缺的那几个才配反代。**先查占用，别先写代理**。

**起 A/B 类之前必须核对脚本默认端口**：迁移到对端的脚本默认值几乎都和
`services.json` 对不上，而且会撞车 —— `mod_overlay_server.py` 默认 8796（撞 Orin 位姿中继）、
`cy_slice_server.py` 默认 8810（对端已被自己的服务占了）、`se3_geom_server.py` 默认 8815、
`l2_watch_server.py` 默认 8820。一律显式给 `--port N` 或对应环境变量，不要靠默认值。

**跨机 sudo 前先测免密**：`sudo -n true` 返回 0 才能直接 `sudo`。
`echo 密码 | sudo -S` 会被 Hermes 的安全策略直接拦掉（判为密码爆破），
整条命令连执行都不会发生 —— 看到 `BLOCKED: sudo password guessing via stdin`
就去测免密，不要改写管道形式再试。

**「常驻」的验收必须包含一次真重启**：`enable` 只证明配置写对了，不证明开机自启。
重启后核对 `uptime -s`、全表 `is-active/is-enabled`、`systemctl --failed`、nginx 监听端口、
一个业务端点的实时性。**用户说「重启了」不等于重启了** —— 先看 `uptime -s` / `up N min`，
还是 `up 2h36m` 就是没重启，按没重启继续办；基于错误前提报"自启通过"，通过的是你手动
`start` 的效果，不是自启。

**agent 执行不了机器重启**：`systemctl reboot` / `shutdown` 在 Hermes 的无条件黑名单里，
`--yolo`、关审批、cron 都过不去。把命令交给用户，自己只做重启后的验证。

**外部探测 `closed` 但本机 `curl` 通 = 只绑了 `127.0.0.1`，不是故障**。
`sudo ss -ltnp` 看到 `127.0.0.1:8811` 就是这种情况。中继/工具类服务本就只给本机用，
报"N 项挂掉"之前先看绑定地址。

完整配方（分类脚本、nginx 反代、统一控制台页、跨机 systemd 汇总、逐项验活、重启验收）见
`references/cross-host-service-consolidation.md`；
管理脚本本体是 `templates/zmaxctl.sh`，拷到 `/usr/local/bin/zmaxctl` 即用。

## 端口速查

| 端口 | 服务 | 层 |
|---|---|---|
| 8793 | 工位总览/相机六路 | L1/L2 |
| 8797 | AR 3D/位姿桥 | L3 |
| 8799 | 产品大屏/全局汇总 | L5 |
| 8802 | AR 场景渲染 | L4 |
| 8794 | Agent 中枢 | L5 |
| 8898 | 臂相机 YOLO 叠加流 | L2 |
| Intel 8816 | 3DGS 渲染 | L4 |
| Orin 39061 | 位姿/控制桥 | L1 |
| AOI 10082/10083 | 金手指/表面检测 | L2 |

**端口号跨机器语义不同**：`8810` 在本机是卡拉比丘流形（`cy_slice_server.py`，「🧿 弦」按钮的目标），
在 Intel 550C 上是 YOLO 自动训练进度。排查前先确认 host，别把另一台的同号端口当同一服务。
判定两个 IP 是否同一台机器：取同一端点比对响应体是否**逐字节相同** —— 双网卡会给出完全一样的 `/health`。

## 对端服务探活：404/500 不等于挂了

对端（工控机 / Intel / Orin）多是 Flask 或 BaseHTTP 小服务，端点名由各自代码决定。
凭常识猜 `/status` `/health` `/last_result` 会拿到 404，Flask 还会把内部 404 包成 **500**
返回（`{"code":500,"msg":"NotFound: 404 Not Found...","stage":"uncaught"}`）——
看着像服务崩了，其实只是路径不对。

**HTTP 方法错了也是这个症状**。8793 的 `/api/aoi/*` 是 POST-only，GET 过去返回
`not found`，与"路径不存在"无法区分。报路径不对之前，先确认端点是不是要求 POST：
`grep -n 'def do_POST\|def do_GET' <caller>.py` 定位那个 `elif p in (...)` 属于哪个 handler。

- **判活前先从调用方代码里取真实 URL**：
  `grep -oE "http://[^\"' ]*(10082|端口)[^\"' ]*" <caller>.py | sort -u`。
  拿错端点得出的"服务挂了"是假警报，会让现场白查一圈。
- **端口 open ≠ 能远程管理**。工控机 `445` / `135` 探测都 open，但真正发 SMB2 negotiate
  会**超时**：`net use` → 错误 67「找不到网络名」，`net view` → 1702「绑定句柄无效」，
  `tasklist /S /U /P` → 「用户名或密码不正确」。这不是凭据问题 —— 防火墙只放行 TCP 握手，
  不放行协议层，换十个账号也进不去。**判法：别只看 TCP 通，真发一次协议报文**；
  确认被拦后结论就是「停服务/重启/改配置只能到现场做」，不要继续试凭据、装 impacket、
  反复改用户名格式（`机器名\user` / `.\user` 都一样失败）。
- **给现场用的操作手册必须单独成文件**，不能只写成仓库 README 的一节。
  写成 `server/README.md` 的章节对站在工控机前面的人等于不存在。
  拆一份 `<主题>_README.md` 到仓库根，开头写清「这台机器是什么」（端口/服务/对外可达性），
  末尾补「本机 PowerShell 自检」（查端口占用 → 拿 PID+路径 → 停指定进程 → 复查），
  再告诉用户 U 盘拷过去或从 GitHub 下载。
  **但别停在"拷过去"就不管了**：用户可能既没有 U 盘、目标机也没外网。
  这时开一个临时 HTTP 投递服务（源机绑产线网 IP + 隔离目录 + 子网限定的防火墙规则，
  再从第三台机器验证可达）是本机唯一走得通的路 —— 完整步骤见
  `references/peer-host-diagnostics.md` 的「往锁死的对端送文件」。
- **只读优先**：能不带 `grab=1` 就读到旧图，就不要触发真拍 —— 真拍会让现场设备动一下。
- **TCP 连得上 ≠ 机器可用**。sshd 的 accept 由内核完成：进程完全调度不上时，
  `22` 端口照样 CONNECTED，但读不到 SSH banner、认证超时；反过来连接数打满时
  又变成 `URLError`（内核直接拒）。判整机死活要用**需要用户态处理的 HTTP 端口**
  （nginx 的 8888 / 80），不要拿 22 当探活依据 —— 汇总服务里用它算 `_host_up`，
  会让整页在故障时逐个等满超时。
- **动手建新能力之前先问对端有没有现成的**：用户提"保存实时数据要有时间戳"这类需求时，
  先 `systemctl list-unit-files | grep -iE 'rec|ts-|record|trace'` 扫一遍。
  对端常常已经有一个在跑的录制器，重建纯属浪费，还会造成两套并存。

AOI 工控机端点、`/region` 字段含义、`/param` 曝光诊断（纯白=过曝 / 纯黑=欠曝）、
请求流水终端（分辨"没人叫"还是"叫了失败"）、以及 Intel 时间戳录制器
（四个时间戳各自用途、控制器时钟漂移怎么处理）见 `references/aoi-and-timestamp-recording.md`。

**被要求「训练 YOLO 做缺陷检测」时，先判成像与样本量，不要先标框。**
金手指氧化/划伤这类任务，卡点几乎总在成像分辨率与样本量，不在模型：每根触点只有几十像素、
边沿模糊、照明不匀时，氧化（褐黑渐变斑）与划伤（线状）在像素上根本区分不开，硬标出来的标签
自己都不信。逐根切取、量化指标（含「必须先分割触点本体再统计，否则背景黑区把 19 根全判异常」这个坑）、
现成数据集与训练/部署管线的复用方式见 `references/aoi-defect-detection.md`。

**要「量出每根矩形的长/宽/面积并做封装识别」时，用 `zmax-gold-geometry` 技能**，别在这里重造。
两条独立证据要一起报：几何说「形状对不对」、YOLO 说「表面脏不脏」，交叉一致才算数。
几何测量有两个硬限制写在那个技能里（对曝光敏感、单帧节距离散会尖刺），照着避。

**曝光/增益用 query 参数，不要用 JSON body**：`POST /param?exposure=5000&gain=4` 回
`applied:{exposure_us:{ok:true},gain_db:{ok:true}}` 并立即生效；写成 `-d '{"exposure_us":5000}'`
则 `applied:{}`（空对象）、`now` 里数值纹丝不动，**HTTP 照样 200**，很容易误判成"硬件拒绝写入"。
参数名是 `exposure` / `gain`（不是 `exposure_us` / `gain_db`）。读取用 `GET /param` 看 `now`。

**这台机（OPT-CC1-GG50，SN D265250070）的合适档位实测**：`3000us/1.8dB` 太暗 ⇒ aoi_gold 流只有
一片模糊灰条纹、19 根里 6 根被误判成 bad；文件默认 `20000us/8dB` 会**全白过曝**（JPEG 仅 5.7KB）；
`5000us/4dB` 与 `2000us/10dB` 都能让 19 根全检出、bad 只剩 1/2/19（这两档判定结果一致，
10dB 代价是触点中间略饱和）。**选档不要只看拉普拉斯方差**：`3000us/10dB` 实测锐度最高（245）
却是**过曝假锐** —— 触点被打成纯白、白/黑边缘更陡，方差虚高；判过曝要同时看饱和像素占比
`(g>=250).mean()`。判色（金色 vs 褐黑氧化）还要求不饱和档：`1200us/6dB` 虽不饱和但画面灰白发暗，
触点根本看不出金色。判过曝看 JPEG 体积骤降到 ~5.6KB 且画面纯白，别只信 `applied.ok`。
若确实写不进去（`applied.*.ok=false` + `hint`），不要反复换数值硬试、也不要停采集去写；
改工控机侧源码的 `file_defaults` 再重启。本机 `cam_param_persist.json` **只对本机 8793 生效，传不到工控机**。

## 生成命令

```bash
python tools/gen_arch_map.py --write
```

期望: `画布节点 85 · 连线 241 · 工程节点 78 · 标准服务 28 · 层级带 15`,
且 `未归层画布节点 0 · 不在画布上的工程节点 0`。这两个 0 是健康判据。
