# Z-MAX 550B 工位 (VSCode 扩展)

把 **550B 调试档**的「标定 / 测量 / 诊断 / 配置」搬进 VSCode 开发界面。
定位: **又一个前端** —— 只做「取真源 + 展示 + 触发」, 不复制任何业务逻辑。

## 契约: 每块 ↔ 真源 (改任何一处都以此表为准)

| 视图 | 数据来源 (只读) | 写操作 (需授权) |
|---|---|---|
| 诊断 | `GET /station/status` → `ctl.exec / collisions / gate / last_cmd / robot / tcp`;`/station/ledger`;`tools/verify_*.py` | 无 |
| 测量 | `/station/status` → `stats`(6 路相机带帧龄) / `ctl.depth` / `ctl.tcp` / `aoi`;`/snapshot/<cam>.jpg` | 无 |
| 标定 | 真源 `flows/calib_closure.json`(候选多路径) · 实现 `src/lerobot/calibration/calibration_layer.py` · `ctl.auth` | `POST /ctl/record_point` · `POST /ctl/clear_point` · `POST /ctl/gs_map` |
| 配置 | 真源 `config/platform/zmax_product.json`(`products["550B"].dev_profile`) · `config/platform/param_spec.json` · `/station/status` → `cam_src / aoi_auto` | `POST /cam/src`(仅复制命令, 不静默改) · `POST /ctl/arm` |

状态栏(左下)三项: **真机 TCP 帧龄** · **授权剩余** · **撞车候选数**;离线时告警色。

## 设计红线
1. 真源唯一 = 8793 只读口 + 仓库配置真源;**不新造后端、不复制业务逻辑**。
2. 写操作全部走后端闸门: 默认未授权 → 两步确认 → 5 分钟自动失效;**扩展不新开旁路**。
3. 任何标「当前」的数值**必带帧龄**(`age_s` / `log_age_s`), 不隐藏新鲜度。
4. 只对 **550B** 生效(`vscode_debug=true`);切档只改真源文件, 扩展本身不升降档。
5. 失败必须明说原因(HTTP 码/错误文本), 不静默降级。

## 安装 (本机)
```bash
cd /home/ubuntu/zmax/vscode-zmax
npm run package                      # → zmax550b-0.1.0.vsix
code --install-extension zmax550b-0.1.0.vsix
# 卸载: code --uninstall-extension zmax.zmax550b
```

## 配置项
| 键 | 默认 | 说明 |
|---|---|---|
| `zmax550b.baseUrl` | `http://127.0.0.1:8793` | 工位控制服务(只读状态 + 授权闸) |
| `zmax550b.arUrl` | `http://127.0.0.1:8797` | AR / 3D 视图 |
| `zmax550b.refreshSeconds` | `2` | 轮询间隔 |
| `zmax550b.repoRoot` | 自动探测 | Z-MAX 仓库根 |

## 验收判据 (P0)
1. 状态栏 TCP 帧龄 / 授权 / 撞车 三项与 `curl -s 127.0.0.1:8793/station/status` 逐字段一致。
2. 四个树视图能展开并列出真源条目;离线时明示「8793 取不到 + 错误原因」而非空白。
3. 测量面板显示 4 路画面, 帧龄随刷新变化。
4. 命令面板可执行: 刷新 / 原始 JSON / 工位页 / 3D / 抓帧 / 跑判据 / 台账 / 标定真源 / 档位真源。
5. 授权必须两步 modal 确认;未授权时状态栏显示「未授权」, 不出现"看起来能动"的假象。

## 边界
- 只读优先: P0 不含真机动作下发(方向键/移动), 那部分仍由控制台/8793 页面承担。
- 不内嵌整页网站到 Webview, 避免变成"另一个 GUI"双源漂移。
- 扩展与宿主解耦: 宿主随 `apt --only-upgrade code` 升;扩展随本目录发版。
