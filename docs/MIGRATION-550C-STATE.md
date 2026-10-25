# 550C 迁移状态 (2026-10-25 中断点)

## 架构约定 (老倪定)
- **550C = Intel 端侧主节点** (Nodka-PTL-Demo, 192.168.23.70) — 全部服务跑这里
- **550A = 4060 本机** (192.168.23.50 LAN / 10.163.146.78 WiFi) — 旁路测试
- **550B = VSCode 单线程版** — 逻辑调试/debug

## 已完成 (Intel 侧)
| 项 | 状态 | 位置 |
|---|---|---|
| 代码 | ✅ 369MB / 16446 文件 | `~/zmax_550c` |
| 模型 | ✅ 12G / 167 文件 | `~/zmax_550c/zmax_data/models` |
| systemd unit | ✅ 23 个已改路径/User | `~/.zmax_migrated_units/` |
| 运行环境 | ✅ **gsxpu-venv** (不是 venv550c) | cv2 5.0.0 + numpy 2.5.2 + torch 2.10.0+xpu |
| 软链 | ✅ | `/home/intel/zmax -> zmax_550c` (旧目录备份 `zmax_old_20261025`) |
| 软链 | ✅ | `/home/ubuntu -> /home/intel` (解决硬编码路径) |
| 服务 | ✅ **26 个 active** | 8797 AR / 8798 工程库 / 8799 大屏 全部 HTTP 200 |

## 未完成
1. **核心服务缺依赖**：`ss-engine-loop` / `ss-skill-dispatch`
   - 已补: draccus, mergedeep, einops, regex, transformers, accelerate, scipy, pandas, timm, av, safetensors, gymnasium (45 whl / 247M)
   - 当前卡点: `Could not import module 'AutoProcessor'` (transformers 懒加载依赖，需要 DEBUG 看原始错误)
   - 补法: 本机 `pip download --no-deps --python-version 312 --only-binary=:all: -d /tmp/whl550c <pkg>` → scp → Intel `pip install --no-deps --no-index`
   - **教训: 必须带 `--no-deps`**，否则 transformers 会拉 CUDA 版 torch + nvidia 包(几个 G)，Intel 用 XPU 全白下
2. **secrets 未同步**：`ZMAX_SS3D_TOKEN` / `ZMAX_AGENT_TOKEN`
   - 影响: `ss3d-live-push` / `agent-hub` fail-closed 不启动
   - 需用户决定: Intel 手工贴 / 授权 scp / 在 Intel 重新生成
3. **Intel 无外网** — pip/pypi/清华镜像全部不通，只能本机下载中转

## 恢复步骤 (ECS 起来后)
```bash
# 1) 验证链路
nc -z -w4 39.102.211.79 22022
ssh -p 22022 tashan@39.102.211.79 'hostname'          # 应落在 ubuntu(Orin)
ssh -J tashan@39.102.211.79:22022 intel@192.168.23.70 'hostname'

# 2) 看 Intel 服务
ssh intel 'systemctl list-units "zmax-*" --plain | head -30'

# 3) 继续补依赖 (本机下载 → Intel 装)
# 4) 全部 active 后出飞书报告
```

## ⚠️ ECS 风险
今天崩 4 次 (12:04 / 13:14 / 13:35 / 15:3x)，症状一致: TCP 能连、SSH banner timeout = 资源耗尽。
资源: 内存 1.6G 用 1.2G / 磁盘 90% (剩 3.8G)。**必须迁移新 ECS**，清单见 `docs/ECS-MIGRATION.md`。
