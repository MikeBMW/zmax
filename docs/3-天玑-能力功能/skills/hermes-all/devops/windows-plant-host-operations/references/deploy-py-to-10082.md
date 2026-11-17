# 把单个 .py 部署到工控机 10082 并重启服务（实测跑通的路线）

适用于 `D:\xspace\ultralytics_AOI\cam_finger_10082_work_v*.py` 这类「只在工控机上、本机没有副本」的服务脚本。

## 1. 上传：本机 HTTP + 工控机拉取（别用 base64 通道）

`tools/win_cmd.py` 的 PowerShell 通道对**超长回执**只回 tag（15B），base64 传文件必然丢内容。定式：

```bash
# 本机（/tmp 里放待传文件），必须用 background=true 起，否则前台 `( ... &)` 会被杀
cd /tmp && python3 -m http.server 8899 --directory /tmp
```
```powershell
# 工控机：拉取 + 立刻回 sha256
Invoke-WebRequest -Uri http://192.168.23.50:8899/up_v20.py -OutFile D:\xspace\ultralytics_AOI\cam_finger_10082_work_v20.py -UseBasicParsing;
(Get-FileHash D:\xspace\ultralytics_AOI\cam_finger_10082_work_v20.py -Algorithm SHA256).Hash.ToLower()
```
本机 `sha256sum` 与回读值**必须逐字符相同**再往下走。

通用做法优先用部署器 `tools/aoi_remote_deploy.py --only 10082`：推 SHA256 → 备份 `.bak_<ts>` → `Stop-Process`
→ 无窗口拉起 → 等 150~200s 两端口监听 → 验收 `/picture?grab=1` → 复原 `cam_param_persist.json` 档位。

## 2. 解释器路径：从**在跑进程**的命令行取，不要猜

`C:\Program Files\Python310\python.exe` 在这台机上**不存在**（踩过：直接拿它 `py_compile` 得到的是
`COMPILE_FAIL`/`CommandNotFoundException`，看着像代码坏了，其实是解释器路径错）。

```powershell
$c = Get-NetTCPConnection -LocalPort 10082 -State Listen -ErrorAction SilentlyContinue
$p = $c.OwningProcess
(Get-CimInstance Win32_Process -Filter "ProcessId=$p").CommandLine
# 实测：C:\Users\admin\AppData\Local\Programs\Python\Python310\python.exe cam_finger_10082_work_v20.py
```

`Get-Command python` 在该会话里可能是空的（PATH 没配），所以**只认进程命令行**。

## 3. 编译校验 → 杀监听 pid → 等保活拉起

```powershell
& "C:\Users\admin\AppData\Local\Programs\Python\Python310\python.exe" -m py_compile D:\xspace\ultralytics_AOI\cam_finger_10082_work_v20.py;
if ($?) {"COMPILE_OK"} else {"COMPILE_FAIL"}
# 通过后再杀：
$c = Get-NetTCPConnection -LocalPort 10082 -State Listen -ErrorAction SilentlyContinue
if ($c) { Stop-Process -Id $c.OwningProcess -Force; "KILLED" }
```

- **杀掉后由 `ZMAX_AOI_KeepAlive` 计划任务拉起**，实测恢复 **30~65s**（不是秒级）——用
  `for i in $(seq 1 20); do sleep 5; curl -s http://192.168.23.23:10082/param && break; done` 轮询，别只看一次。
- **不要先 `Stop-Process` 再编译**：编译失败时服务已经停了，白丢一次产线检测。
- 报错要看正文时用 `2>&1 | Select-Object -Last 4 | Out-String`；不带 `2>&1` 只会回一句 `COMPILE_FAIL`。

## 4. 验收（缺一不算成功）

```
GET /param          → 现场档位原值还在（如 700us / 16.38dB；重启会按 persist 复原）
GET /picture?kind=origin&grab=1 → 真图尺寸/均值正常（不是全黑 0 字节）
改动对应的能力端点 → 回读新行为（例：/region、判据图尺寸）
判「图口径改对了」→ 见 §7 的三者同源验证, 只报尺寸不算
```

## 5. 现役有哪些接口（问「10082 有什么服务 / 怎么这么多」时）

`grep -n '@app.route' cam_finger_10082_work_v20.py` 出 11 个路由。**按调用方分层回答，别整张表倒给用户**
（他会追问"怎么这么多、都有用么、简化"）：

| 层 | 路由 | 用途 |
|---|---|---|
| 生产链 | `POST /capture_detect` | 抓拍 → 裁条带 → 判缺陷 → OK/NG；机械臂到位点调它 |
| 生产链 | `POST /guide_pose` | 抓拍 → 定位键排 → 算 `pose_target`（3D 引导） |
| 生产链 | `GET /last_result` | 上次判定（GUI 与执行链都读） |
| 生产链 | `GET\|POST /picture` | `kind=crop`(默认=模型推理输入)`\|judge`(判据图)`\|origin\|natural\|modelin`；`grab=1` 触发抓拍，`file=1` 读落盘文件 |
| 标定 | `GET\|POST /guide_calib` | `k_mm_px` / `axis_sign`；换镜头必重标 |
| 诊断 | `GET /region` | 条带 bbox + `gold_px`/`gold_cover`/`bright_frac`/`focus` |
| 诊断 | `GET /param` | 现役曝光/增益。`file_defaults` 只是源码兜底常量（如 20000/8），**实际按 `cam_param_persist.json`**（如 8000/2.0） |
| 诊断 | `GET /crop_info` | 上次裁剪信息（只有 `capture_detect` 之后才非空） |
| 诊断 | `GET /preview.jpg` | 最近一帧 |
| 运维 | `GET /storage` | 图片目录统计；**保活与起停脚本判活就看它 200** |
| 运维 | `POST\|GET /prune` | 清旧图（GET 是 dry-run 只报告；目前无调用方，图会一直堆） |

- **哪些真在用必须 grep 出来，别按名字猜**：
  `grep -rhno '10082/[a-z_.?=0-9]*' tools/ *.py | sed 's/[?].*//' | sort | uniq -c`
  —— `picture`/`storage`/`region` 这些词在代码里也当变量名, 先粗 grep 会把调用方数量虚高十倍。
- 🔴 **`/capture_detect` 只回 `{"code":200,"msg":"success"}`, 不含判定**: 它只说"我干完了"。
  要 OK/NG 必须再取 `/last_result`；只盯这一个接口的返回会以为"没结果=没检测"。
  反向也成立: `/last_result` 在没触发过检测时回 404, 两者要成对用。
- **不要提议删路由**：GUI（`tools/gui/studio.py` 一万三千行附近）直接调 `/last_result`、`/picture`；
  `/storage` 是保活判据；`/guide_calib` 是唯一重标入口。删了界面报错、自愈失能。
- 服务刚重启时 `/last_result`、`/crop_info`、`/region` 回 404「尚无…」是**正常**（内存结果为空），
  不是接口坏了 —— 跑一次 `/capture_detect` 就都有。
- 文件内部 `VERSION` 可能与文件名不一致（例：文件叫 `_v20.py`、`VERSION = "v21"`）⇒ 别拿日志里的版本号去对文件名。
- **交付接口清单要带「真实返回值」而不是只给路径**：用户会连着要"返回值也写进去"。
  做法是**先跑一次真检测**（`/last_result`、`/crop_info`、`/region` 才有数据），再逐个抓
  JSON、裁掉长数组并注明「略」, 每个字段后面跟一行说明、关键的标 ★; 两张图的接口给**字节数基准**
  （原图 ~304KB / 条带 50KB / 预览 ~304KB —— 掉到几 KB 就是取流坏了）。
  用 PowerShell 的 `irm` 举例而不是 `curl`：`-Body '{...}'` 不用处理引号转义。

## 6. 定式教训

- **改完不等重启就验证 = 验的是旧进程**：`/param` 之类只读端点会立刻回 200，很容易误判“已生效”。
- **先备份再覆盖**：`Copy-Item ... .bak_<日期>_<标记>`，回滚只需一条命令。
- **`pkill -f <pattern>` 会杀掉自己那条 shell**（命令行里含同一串）——按端口/pid 定位（`ss -ltnp`）再 kill。

## 7. 「落盘/展示的那张图」必须是模型真正吃的那张（图口径）

用户原话「我要看到真正进入 yolo 推理的图」。判据图（切条带+调平+去背景）是**给人看**的，不是喂模型的；
两者尺寸/几何都不同，拿判据图当模型输入展示，用户看图会以为模型吃的是那张。

**正确口径（10082 金手指）**

| 角色 | 落盘文件 | 来源 |
|---|---|---|
| 模型推理输入 | `Finger_TopView_W960_H960_No_<n>.png` | `crop_goldfinger_regular()` 规整裁剪（条带拉伸成 960×960）|
| 判据图（诊断） | `Finger_Judge_W900_H332_No_<n>.png` | `render_judge_gated()` |
| 相机原图 | `Finger_Image_W<w>_H<h>_No_<n>.png` | `GrabAndSaveImage` 原帧 |

**10083 表面本来就是这个口径**：落盘 `Surface_Letterbox_W1280_H1280_*`（= `letterbox_square()` 的输出，
模型吃的就是它），判据图另存 `Surface_Judge_*`，`?kind=crop` 默认返回规范图。
🔴 **用户说「10083 也同样改」时先核现状**：它可能已经是对的。只报"两个都改了"而实际另一个没动
（或者白改一轮）都会让他以为你在敷衍；先读 `/last_result` 的 `model_input`/`topview`/`judge_file` 三个字段对齐再动手。

**实现要点**

- 🔴 **让检测器直接读落盘的那个文件**，别再往 `%TEMP%` 另写一份临时图：
  `mi_path = top_path if (save and model_in is not None) else None`。这样
  「落盘的那张」==「模型吃的那张」==「`/picture?kind=crop&file=1` 取回来的」在物理上是同一个文件，
  不存在走样可能，也不再有"临时图堆 `%TEMP%`"的老问题。
- **删除临时图的清理逻辑要跟着改**：原来靠 `basename.startswith("zmax_main_960")` 判断，改名后不再命中就
  自动安全；但如果保留旧前缀判断，新落盘图会被 worker 当临时图删掉。改完 grep 一遍 `os.remove`。
- 🔴 **全局"上一张"变量不能无条件覆盖**：`_LAST_JUDGE = judge_path or ""` 在 `grab`（`save=False`）时会把
  它写成**一个不存在的新路径** ⇒ `/picture?kind=judge` 立刻 404、诊断图整条路瞎掉。
  正确写法 `_LAST_JUDGE = judge_path or _LAST_JUDGE`（不落盘就沿用上次真检测的那张）。
  落盘函数 `_iw()` 内部看 `_TL.save` 决定写不写，所以**变量赋值不能跟着无条件走**。
- **`/last_result.topview` 也要一起改**：它原来是 `judge_path or topview_path`（= 判据图）。留着不改，
  接口上"模型输入"和"展示图"就还是两张，用户点开还是看到判据图。
- **`_PRUNE_PATTERNS` 要加新前缀**（否则判据图无限增长）: `("Finger_Judge_W*_H*_No_*.png", KEEP_CANON)`。

**三者同源验证（只报尺寸不算）**

```python
rec  = last_result['model_input_md5']
m_mem  = md5(imdecode(get('/picture?kind=modelin')))        # 内存无损那份
m_disk = md5(imdecode(get('/picture?kind=crop&file=1')))    # 落盘 PNG
assert m_mem == m_disk == rec
```

- 🔴 **`md5` 必须在同一帧内比**：每次 `/capture_detect` 都会让 `n` 递增，在两次检测之间取值会得到
  **假的 False**（实测白查一轮）。要比就先记 `n0`，触发后轮询到 `n != n0` 再取三项。
- 🔴 **`kind=crop` 不带 `file=1` 走的是内存 JPEG（有损）**，md5 **必然**与记录的像素 md5 不同 —— 那不是 bug。
  尺寸对（960×960）就说明口径对了；要逐位相等必须加 `file=1` 或走 `kind=modelin`。
- **换图尺寸后要重估保留上限**：900×332 PNG ≈ 177KB，960×960 PNG 实测 **1.44MB**（8 倍）。
  `KEEP_CANON=400` 就是 ~576MB；上线前查一次 `Get-PSDrive D` 的 Free，并在交付说明里写清"涨了多少、上限多少"。

## 8. 交付「关服务」脚本：必须连保活一起停，并默认保持停用

用户会要「一个关闭程序的脚本，有时候需要关 10082 和 10083」。只杀进程是**无效交付**：
`ZMAX_AOI_KeepAlive` 每分钟一轮，发现端口没人听就拉起来，一分钟后服务自己回来，用户以为脚本没用。

定式（两个脚本，成对交付）

- `stop_all.ps1`：① `Disable-ScheduledTask ZMAX_AOI_KeepAlive` ② 按端口取属主 pid 精确 `Stop-Process`
  ③ 清同名残留副本 ④ **双证据复核**（端口 Listen 计数 0 + 同名进程 0）。**保活保持 Disabled，不自动恢复** ——
  这才是"真关"。
- `start_all.ps1`：清残留 → 用 `WScript.Shell.Run(..., 0, $false)` 无窗口起两个 → 等端口 + **等 `/storage` 200** →
  `Enable-ScheduledTask` 恢复保活。判据是 `/storage` 200，不是"端口在听"（v20 的脸在 `/storage`）。
- **两个都支持 `-Port` 只动一路**、`-NoPause` 给远程/自动化调用：脚本末尾的 `ReadKey`（"按任意键关闭"）
  在非交互环境会**挂住整条通道**。
- 🔴 **双击 `.ps1` 默认是记事本打开，不执行** —— 必须配一个 `.bat` 薄壳：
  `@echo off` / `chcp 65001 >nul` / `powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop_all.ps1" %*`。
  `%*` 透传参数，所以远程测 `stop_AOI.bat -NoPause` 走的正是双击那条路。
- **`.ps1` 存 UTF-8 with BOM**（PS 5.1 读无 BOM 的 UTF-8 中文会乱码/语法崩），`.bat` 纯 ASCII + CRLF。
  分发走 8794 静态目录 + `Invoke-WebRequest -OutFile`（字节原样，BOM 保留）。
- **交付前双向真跑一遍**：stop → 端口全释放 + 保活 `Disabled`；start → 两路 `/storage` 200 + 保活 `Ready`；
  再验一次真功能（`/picture?grab=1` 出图、`/guide_pose` 仍判居中）。只验 stop 不验 start，等于交给他一个关得上开不回来的开关。
- **桌面快捷方式给三个**（`AOI-Folder` / `AOI-Start` / `AOI-Stop`），**名字用 ASCII**：
  经反向通道下发的命令里的**中文标识符会被通道转坏**，建出来的 `.lnk` 名字真的是乱码
  （回读 `Get-ChildItem $desk -Filter 'AOI*'` 看到的就是坏名字）。中文只放在 README 正文里（走 HTTP 下载，字节原样，没问题）。
