# Z-MAX 标准服务目录 (server/)

> 2026-11-26 · v5.50.786 · 老倪：「这些服务都是状态空间工程的标准服务，
> 建立代码专有路径，在 zmax 根目录下面建立 server 文件夹，将所有服务都放到里面」

## 这是什么

Z-MAX 全部 **标准服务** 的统一入口目录。以前这些脚本散落在 `tools/` 下（那是杂物间，
1753 个历史脚本都堆在 `pkgtools/`），服务没有一个"家"，也没有一份清单说清楚
"到底有哪些服务、在哪个端口、属于哪一层、依赖哪个硬件"。

现在：

| 文件 | 作用 |
|---|---|
| `services.json` | **服务清册（单一真源）**：28 个标准服务的端口 / 脚本 / 所在机器 / L层归属 / 系统归属 / 硬件依赖 |
| `arch_map.json` | **系统架构唯一依据**：系统 2/1/0 × L1~L5 与状态空间 85 个画布节点、78 个工程节点、241 条连线的完整映射（由 `tools/gen_arch_map.py` 生成） |
| `web/arch_map.html` | 系统架构图（读 arch_map.json） |
| `web/arch_map_standalone.html` | 同上，**数据内联，双击即可打开，不依赖任何服务** |
| `*.py` | 服务实现本体（从 tools/ 同步过来的部署副本） |

## 端口速查

### 本机 工位机 4060 (192.168.23.100)

| 端口 | 服务 | 脚本 | 层 |
|---|---|---|---|
| 8793 | 工位总览 · 相机六路 | `cam_live_stream.py` | L1/L2 |
| 8797 | AR 3D · 位姿桥 | `tcp_ar_server.py` | L3 |
| 8799 | 产品大屏 · 全局汇总 | `dashboard_server.py` | L5 |
| 8802 | AR 场景渲染 | `ar_scene_render_server.py` | L4 |
| 8794 | Agent 中枢 | `agent_hub.py` | L5 |
| 8898 | 臂相机 YOLO 叠加流 | `arm_yolo_stream.py` | L2 |

### Intel 550C (192.168.23.70)

| 端口 | 服务 | 说明 |
|---|---|---|
| 8816 | 3DGS 实时渲染推流 | `gs_render_stream_intel.py`（**注意：gsplat SYCL 后端必须 `packed=False`**） |
| 8901 | 相机中继 | `zmax-cam-relay.service` |
| 39053 | 中继 | `zmax-relay.service` |
| — | 位姿真值中继 | `arm-pose-relay.service` → `/tmp/arm_tcp_pose.json`，源 = `192.168.23.100:8797` |

### Orin (192.168.23.66) / 工控机 (192.168.23.23)

| 端口 | 服务 |
|---|---|
| 8792 / 8794 | Orin 相机帧 |
| 39061 | Orin 位姿/控制桥（珞石 endInRef 5Hz） |
| 10082 / 10083 | AOI 金手指 / 表面检测 |

## 状态空间分层（L1~L5）与三系统

老倪 2026-11-26 定：**系统 0/1/2 是全面的系统工程，要连接所有标准服务。**

```
系统 2 · 慢思考 (1~10 Hz)   ← L5 场景理解+自动标注 · L4 自主安全/流形世界模型
系统 1 · 快反应 (10~100 Hz) ← L3 连续功能 · L2 基础功能
系统 0 · 反射   (200~1000 Hz) ← L1 机器人接口（执行器/安全/物理闭环）
```

映射来源：`flows/state_space_obs.json`（状态空间主画布）的 15 个层级带 + 
`src/lerobot/engineering/node_map.json` 的 78 个工程节点。

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

## 重新生成架构图

```bash
python tools/gen_arch_map.py --write     # 重新生成 server/arch_map.json
# 然后重新内联数据（如需 standalone 版）
```

## 部署注意

- 本目录的 `*.py` 是**部署副本**。改代码请改这里，并同步回 `tools/`
  （打包脚本与旧 exe 仍按 `tools/` 路径找文件，两边必须一致）。
- 老倪要求"代码对齐本地 Ubuntu 的静静，不要搞出两个版本"——
  本目录 + `tools/` 的差异要随每次迭代提交，不要只在一边改。
- `launch_zmax.ps1` 已改为 **server/ 优先、tools/ 回落**：
  找不到 `server/xxx.py` 时才用 `tools/xxx.py`，保证老包不炸。
