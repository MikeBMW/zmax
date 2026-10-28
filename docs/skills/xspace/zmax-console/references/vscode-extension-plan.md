# 把 Z-MAX 插进 VSCode 开发界面 (自研 vsix 扩展方案)

触发: 用户说「用插件/扩展的方式把 Z-MAX 插进 VSCode」「VSCode 定制/开源升级/能不能按 VSCode 改」。

## 分工 (先讲清, 别答"不是开源所以做不了")
- VSCode = 半个开源: 上游 **Code-OSS (MIT)**, 官方发行版另带专有层 (遥测/品牌/部分扩展/Marketplace 条款)。
- **宿主继续用官方 deb 版** (Pylance/Remote 才可用), 定制全走自研 `.vsix` —— 自研扩展在官方版 / Code-OSS / VSCodium **都能装**。
- 不自己编译 VSCode (每次升版重编重签, 不划算), 除非将来要内网离线分发。
- 解耦: 宿主 `sudo apt-get install --only-upgrade code` 升级; 扩展随自己仓库发版 (版本号跟主工程走, 不自主升级)。

## 定位红线 (预先固定)
- 扩展 = **又一个前端**, 业务逻辑一行不重写; 只做"取唯一依据 + 展示 + 触发" (否则双源漂移)。
- 所有写操作 (真机动作/切档/训练) 走 8793 授权闸: 默认未授权 + 两步确认 + 窗口内失效; 不新增旁路。
- 任何标"当前"的值必须带帧龄/时间戳 (直接显示 `age_s`)。
- Webview 不许内嵌整页网站 (否则又是"另一个 GUI"); 只放数据 + 小控件。

## 唯一依据 (无需新造后端)
- `http://127.0.0.1:8793/station/status` → 200 / ~11.5KB: `stats` 六路相机 (online/fps/kb_per_frame/compress_x/age_s) · `ctl.tcp`(xyz/abc/age_s) · `ctl.auth`(armed/left_s/ip) · `ctl.robot` · `ctl.motion` · `ctl.exec`(pid/skills/log_age_s) · `ctl.collisions` · `ctl.gate` · `aoi{10082,10083}`。
- 其他: 8797 AR (`/api/cams`, `/snap/<k>.jpg`) · 8791 相机 · 8798 工程库 (仅本机)。
- `.vscode/launch.json`(F5 三配置) + `tasks.json` 已在 ⇒ 调试/任务集成有现成地基。

## 能力映射 (VSCode 原生元素)
1. 状态栏: 真机 TCP `age_s` + 授权 `left_s` + collisions + 控制台 exec 存活。
2. 侧边栏树「Z-MAX 工位」: 六路相机/AOI/exec/闸门, 点击就地打开。
3. 侧边栏 Webview「信号分析」: 复用画布数据源 (插拔场景绿标), 波形 + 万有引力表 (力大小 |F| / 实部 w)。
4. 命令面板: 跑判据/拍帧/授权/开 3D/重启控制台/核验链路/训练 —— 复用现有脚本, 不新增旁路。
5. CodeLens + F12 Go to Definition: 节点源码映射原生化 (取代控制台右键 `code -g` 那条路)。
6. Diagnostics: 画布 JSON / 场景 / 档位配置打开即校验 (编号重复、参数越界、节点断线、开关不一致)。
7. Output 面板: `l2_daemon` / 流形引擎日志尾随。

## 阶段 (每阶段独立验收)
- P0 (1天): 骨架 + 状态栏 + 3~5 命令。判据 = 状态栏数字与 `/station/status` 逐字段一致。
- P1 (1~2天): 侧边栏「Z-MAX 工位」树。
- P2 (2~3天): 信号分析 Webview。
- P3 (1~2天): CodeLens/F12 + Diagnostics。
- P4 (3~5天): 画布自定义编辑器 (`.zmax_space.json` 双击进画布, 先只读)。
- P5 (另立, 别现在做): 自研 DAP 适配器接节点单步 —— 现有 F5 + 断点已够。

## 交付
- 源码进仓库 `vscode-zmax/` (TypeScript), CI 打 `.vsix` + 挂 Release; 安装 = `code --install-extension zmax-X.Y.Z.vsix` (可离线)。
- 状态: 方案已给用户 (P0-P5 全表), 等开工指令。
