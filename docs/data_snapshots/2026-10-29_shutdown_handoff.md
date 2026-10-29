# 2026-10-29 收工存档 · 关机交接单

- 机器: 本机 (Z-MAX 550C 主节点 / 工控机 + Orin 双机), Ubuntu, 主机名见 `hostname`
- 时间: 2026-10-29 16:45 CST
- 代码: `0b8b1ced` (main, 已 push; `git ls-remote origin main` 回读一致)
- 版本号: 未改 (老倪本轮没给号; 现号 5.50.758)

## 一、本轮做了什么 (按最后指令顺序)

1. **右臂不平顺取证** — 加 `/control` 指令流取证 (`/state.json.ctl`): 实测 5661 次下发,
   单次最大关节变化 **0.70°**, `>1.2°` 的 **0 次** ⇒ 指令本身连续, 之前的"1.2m/s 峰值 = PD 过冲"判断是错的。
   真因: 渲染站 `--hz 8` ⇒ 真值 125ms 才刷一帧, 350mm/s × 125ms = 44mm 台阶 (采样别名)。
2. **渲染站解耦** — `--phys-hz 50 --render-hz 20`, 真值刷新 8.5Hz → 16~21Hz; close 每拍出图, ar3d 每 3 拍。
3. **L2 全链 17 节点接入** (`tools/ss_l2_chain.py` 新增) — 顺序真实执行 + 每节点 calls/ms/ok/note 记账;
   `/api/l2` GET/POST 逐节点开关, 落盘 `config/platform/l2_chain_switches.json`;
   无数据源节点 (sstactile) 如实 `ok=false` 不造假; ssaoi 用当拍帧统计, ss_mem_l2 用段表模板比对。
4. **exec_replay 每采样点跑全链** — 指令点优先用**预测位姿**(同侧且偏差<8mm 才采用), 否则退回轨迹点。
5. 工程库重建 + `check` 判据全绿 (894 个数字 / 2161 条链接 / 19 个来源 / 1.89MB)。

## 二、实测数字 (可复核)

```
L2 节点:      17 个 (15 真跑 + 1 无源如实不跑 + 全开时 sstactile 报 why)
调用/耗时:    每节点 2487 次 · 0.02~5.31ms (sis_mem_l2 最慢 5.31ms)
指令流:       5661 次 · 单次最大 0.70° · >1.2° 0 次
真值刷新:     8.5Hz → 16~21Hz (phys 50Hz / render 20Hz 解耦)
闭环:         6/6 · 20.1s (平滑前 29.6s) · 单步 7.1~9.7mm (tol 10)
大跳:         >100mm 4 → 0 次
静止占比:     all_on 一轮 1504 样本只有 230 在动 (15%) ⇒ 85% 时间在段间等位
```

**平顺度结论 (未解)**: 单段内部已连续, 顿挫来自"6 个独立动作 + 每段判到位才走下一步"。
UPH 顺是"整条段表按时间连续播放"。下一步 = 6 段合成一条连续轨迹 (corner blending + 到点只记录不硬停)。

## 三、存档产物

| 项 | 路径 | 体积/校验 |
|---|---|---|
| 状态快照 | `data/database/zmax/archive/zmax_state_20261029_1643.tar.gz` | 4.1 MB · 1015 文件 |
| 场景/画布快照 | `zmax_data/snapshots/scene_20261029_164347.tar.gz` | 50 文件 · sha256[:16] `d666319ae55c6170` · `--verify` 过 |
| 工程库 | `data/database/zmax/zmax_engineering.db` | 1.89 MB · `engineering_db check` 全绿 |
| 工程存档 | `data/database/zmax/zmax_space.proj` | 95 节点 / 219 连线 |
| L2 开关 | `config/platform/l2_chain_switches.json` | 已落盘, 已进状态快照 |
| 代码 | commit `0b8b1ced` | 已 push |

## 四、开机自启 (52 个 system unit + 1 个 user unit, 全部 enabled)

含: `zmax-ar-render` `zmax-ar-render-station` `zmax-ss-engine-loop` `zmax-ss-canvas-loop`
`zmax-l2-daemon` `zmax-moveit-plan-req` `zmax-pose-relay` `zmax-orin-legs` `zmax-tunnel-*`
`zmax-*cam*`/`dds-*`/`web-agent-bridge` + timers (lan-autoheal/legs-watchdog/studio-mem-guard 等)
+ `systemctl --user` 的 `zmax-studio.service`。
**开机不会自己起**: `tools/boot_restore.sh` (l5_live_mark / vl_safety_monitor / 深度源 / 实时标注器)
⇒ 重启后手动 `bash tools/boot_restore.sh local`。

## 五、关机影响面

一关机就死 (都跑在本机):
- 所有 87xx/88xx 页面与推流: 8797 AR 页 · 8791 相机 · 8793 画布/手动控制 · 8802 渲染 · 8805 AR 站 · 8790/8798 数据面
- 隧道/反代: `zmax-tunnel-lhr` `zmax-tunnel-proxy` `zmax-vnc-tunnel` `zmax-proxy` ⇒ 远程访问全断
- AR + L2 闭环、`ss-engine-loop`、`ss-canvas-loop`、`l2-daemon` (FIFO 下发)、MoveIt 规划请求
- Orin 直连腿 (`zmax-orin-legs` / `orin-arm-fwd`) ⇒ 遥测与转发现场断

不受本机重启影响: Orin (自身独立) · 珞石控制器 · AOI `.23` 的 10082/10083 服务。

## 六、已知不可用 (重启后依旧)

- L4 编码器 `z_source`: `URLError 13684 次`, `confidence≈0.018`, `z_latent` 退 PCA
- 8797 `/ar3d` 位姿真值 stale (桥 `No route to host 192.168.23.70`)
- 内置相机 `privacy=1` 只读, `camera_power=0`; `arm/local2/aoi_gold/aoi_surface` offline
- `sstactile` 无触觉数据源 (AR 场景), 打开也只报 why
- 抓取物理不成立 (两指沿 x 并列, 16mm 模块夹不成对) — 搬运未做
- 本机无 Qwen2.5-VL-3B 权重 ⇒ 端侧离线 VLM 不可用

## 七、回滚开关

- 平滑回放: `ZMAX_STATION_REPLAY=0` (回老 P 环)
- 渲染帧率: 删 `/etc/systemd/system/zmax-ar-render.service.d/zzz-hz30.conf` 即回 `--hz 8` 单频
- L2 链: `/api/l2 {"all":false}` 全关; 单节点 `{"node":"sspred","on":false}`
- 画布: `data/database/zmax/sources/canvas/_archive/*.json` 逐份回填
