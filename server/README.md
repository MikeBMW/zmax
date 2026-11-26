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
