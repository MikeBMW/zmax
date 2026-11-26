# AOI 检测系统 现场操作手册

> **这份文件是给「工控机现场」用的。** 4060 上那份在 `D:\ZMAX\server\README.md`(服务目录的一节),
> 这里是拆出来单独的一份, 可以拷到工控机桌面直接看。
>
> 2026-11-26 · Z-MAX v5.50.786

## 这台机器是什么

```
工控机   192.168.23.23   (Windows, TTL=128)
         ├─ 10082  金手指检测  detect_type=gf
         └─ 10083  表面检测    detect_type=housing
对外只有这两个 HTTP 端口。445(假open)/135(假open)/22/3389/5985 全部不可用。
```

**重要**: 从 4060 无法远程管理这台机器 —— 不是权限问题, 是协议层被拦。
停服务、重启、改配置都必须**在本机操作**。

## AOI 检测操作手册（工控机 192.168.23.23）

> 2026-11-26 实测记录。所有命令都在 **4060（本机）** 上执行。

### 一、发检测请求

两个服务**用同一个端点** `POST /capture_detect`，只换端口：

| 端口 | 产品 | detect_type | 耗时 |
|---|---|---|---|
| 10082 | 金手指 | `gf` | 0.6 ~ 1.6 s |
| 10083 | 表面 | `housing` | 8.8 s |

**直连工控机**（PowerShell，最原始）：

```powershell
Invoke-RestMethod -Method Post -Uri "http://192.168.23.23:10082/capture_detect"
```

**经 8793**（推荐：会落本地盘、进日志、进统计）：

```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8793/api/aoi/detect?port=10082"
```

两者区别：直连只拿到工控机原始响应；经 8793 会额外写
`D:\AOI_images\<type>\incoming\`、记进 `/api/aoi/log`（页面上那两个终端就靠它）、
进 `/station/status` 的 aoi 统计，并返回 `saved_locally` / `fresh`。

### 二、取图（不触发拍照）

```bash
curl "http://192.168.23.23:10082/picture?kind=origin"           # 整板原图 2448x2048
curl "http://192.168.23.23:10082/picture?kind=crop"             # 判据图
curl "http://192.168.23.23:10082/picture?kind=origin&grab=1"    # 真拍一张(~0.6s)
curl "http://192.168.23.23:10082/region"                        # 模板匹配 bbox
curl "http://192.168.23.23:10082/last_result"                   # 最后一次判决
curl "http://192.168.23.23:10083/picture?kind=crop"             # 表面判据图 1280x1280
```

**关键区别**：不带 `grab` 读工控机内存里的最近一帧（4~86 ms，很轻）；
带 `grab=1` 是真拍照（0.55~0.62 s，占相机）。

### 三、曝光参数

```bash
# 查当前值
curl "http://192.168.23.23:10082/param"
# 设（POST 到 8793，实时生效，并自动落盘）
curl -X POST "http://127.0.0.1:8793/api/aoi/param?port=10082&exposure=3000&gain=1.8"
```

已标定档位：

| 场景 | 曝光 | 增益 | 依据 |
|---|---|---|---|
| **10082 金手指（推荐）** | **3000 us** | **1.8** | 死白 1.72%，可检出 |
| 10082 pt1 档 | 20000 us | 8 | 产线验收档，但**对镀金镜面会死白** |
| 10082 pt2 档 | 40000 us | 8 | 背面点（20000 太暗） |
| 10083 表面 | 20000 us | 8 | 当前值 |

落盘位置：`~/zmax/zmax_data/aoi_v4/cam_param_persist.json`（重启后自动复原）。

**坑**：金手指是镀金镜面，曝光过 20000us 直接死白（实测 RGB 253/254/244）；
3000us 下空背景会全黑（mean≈4），这是**正常的**——等产品进画面才亮。

### 四、停 AOI：**从 4060 做不到**

实测四条路全被拒：

```
445 SMB     TCP 能连，但 SMB2 negotiate 超时（假 open，不是真开）
135 RPC     net view → 1702 绑定句柄无效
22 / 3389 / 5985   全 closed（无 SSH / 无远程桌面 / 无 WinRM）
net use     → 67 找不到网络名
tasklist /S → 用户名或密码不正确
```

**结论**：工控机拒绝一切远程管理，`admin/admin` 也进不去——**不是权限问题，
是协议层被拦**（防火墙只放行 TCP 握手，不放行 SMB/RPC）。

**只能现场停**：

```
任务管理器 → 详细信息 → 右键列头 → 勾"命令行"
→ 找跑 10082 / 10083 的 python.exe → 结束任务
```

若结束又活：查 `services.msc`（服务）或 `taskschd.msc`（计划任务）里的守护。

**要让远程能操作**（会扩大攻击面，非必要不开）：

```powershell
Enable-PSRemoting -Force        # 开 WinRM 5985
```

### 五、判据指标怎么看

| 指标 | 含义 | 正常 |
|---|---|---|
| `gold_cover` | 金手指覆盖率 | 有产品 > 0.1 |
| `stripe_cols` | 模板匹配到的条带列数 | 有产品 > 0 |
| `bright_frac` | 死白像素占比 | ≈0.017（1.7%） |
| `judge_ok` | 判据图本身是否合格 | true |

**⚠ 假阳性**：画面里没有产品时 `gold_cover=0`、`stripe_cols=0`，
但 `verdict` 仍会返回 **OK**（0 缺陷）。**不能只看 verdict**，
必须同时看 `gold_cover` / `stripe_cols` 确认「有没有检测对象」。

**⚠ judge_ok=false 但 verdict=OK**：说明判据图不合格（如
"上边缘不直(残差 10.80px > 3px)"），这个 OK 是保守放行，不可当真。

### 六、延时为什么大

```
相机采集  ~0.6 s/帧   ← 2448x2048 的硬件上限(≈1.7fps)，改不了
8793 转发 ~0.01 s     ← 已经很快
浏览器     ~0.05 s
```

页面卡顿是**相机物理极限**，不是 8793 拖慢。要快只能降相机分辨率或换连续采集模式，
而这两项都不在 `/param` 里（只有曝光/增益/gamma），改不到。

---

## 附: 本机 PowerShell 快速自检

```powershell
# 1. 两个服务还在不在
Test-NetConnection 127.0.0.1 -Port 10082
Test-NetConnection 127.0.0.1 -Port 10083

# 2. 谁占着这两个端口(拿到 PID 再决定停哪个)
Get-NetTCPConnection -LocalPort 10082,10083 -State Listen |
    Select-Object LocalPort, OwningProcess |
    ForEach-Object {
        $p = Get-Process -Id $_.OwningProcess
        [PSCustomObject]@{
            端口 = $_.LocalPort
            PID  = $p.Id
            进程 = $p.ProcessName
            路径 = $p.Path
        }
    }

# 3. 只停某一个(把 PID 换成上一步查到的)
Stop-Process -Id <PID> -Force

# 4. 停完确认端口是否真关了
Get-NetTCPConnection -LocalPort 10082,10083 -State Listen -ErrorAction SilentlyContinue
```

**注意**: 别一次全杀。两个端口可能是两个独立进程(一个金手指一个表面),
先停你要停的那个。硬杀可能让相机句柄卡住, 那要重启整台机器才能恢复。

## 附: 相机参数自检

```powershell
# 看当前曝光/增益
Invoke-RestMethod "http://127.0.0.1:10082/param" | Select-Object -Expand now

# 金手指标定值: 3000us × 1.8dB  (过 20000us 对镀金镜面直接死白)
# 表面当前值:   20000us × 8dB
```
