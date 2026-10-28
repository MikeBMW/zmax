# 550B 「远程 / 局域网」连接方式显示 (底部状态带)

老倪 2026-10-23: 「550B 增加显示是远程模式, 还是连接上局域网; 远程就显示 4060 的硬件信息和模型状态,
局域网则显示 intel 的硬件状态和模型状态」。

## 唯一依据与判据 (不许界面自己猜)

连接方式由 `status_hub.collect_lan()` 判, 写进 `/status/all.lan`, 状态带只消费:

```
lan = {"mode": "lan|remote|unknown", "local_ips": [...], "hosts": {intel,orin,aoi,jig: bool}, "cache_age_s": x}
```

- `lan`    = 有产线网段 (192.168.23.0/24) 地址 **且** 至少一台产线主机 TCP 应答
- `remote` = 本机根本没有产线网段地址 (只挂 WiFi/4G) ⇒ 走远程通道
- `unknown`= 有 LAN 地址但一台都不通 (线拔了/换网段) —— 不猜, 槽里画「—」
- 探测: 4 个目标并行 socket, 单 0.5s 超时, 总等待 ≤1.5s, 4s 缓存 ⇒ 不拖采集线程。

## 界面表现 (两个地方同时变)

| 元素 | 远程 | 局域网 |
|---|---|---|
| 左侧档位 chip | `550B·4060` | `550B·Intel` |
| 第 1 个槽「链」 | 100% `远程` (busy 青) | 100% `局域网` (ok 绿) |
| 后 4 槽 | GPU/CPU/内存/磁盘 (本机 `hw.*`) | NPU/GPU/CPU/内存 (`edge.pipeline.devices` + `edge.hw`) |
| 模型 chip | 在役层 L2..L5 (`models`) | 端侧各设备真在跑的模型 + 占空 (`edge.pipeline.devices[*].models/duty_pct`) |

相机/机械臂/端侧/栈 四个观察计数不删, 移到 chip 的悬停 fact 里 (一行槽位只有 5 个格子, 塞不下)。

## 端侧 (Intel) 数据到底准不准 —— 三条硬口径

问「550C 远程状态准不许」时, 这三个数必须能回答, 否则界面就是在拿旧数当实时:

1. **数据来源**: 远程模式不走 LAN, 走 SSH 隧道 `ssh -L 127.0.0.1:18800:192.168.23.70:8800 tashan@39.102.211.79`
   (`zmax-orin-intel-fwd.service`)。数是 Intel 机上 `/health` 真采集, **不是编的**, 但经过 ECS 中转。
2. **年龄**: `collect_edge` 缓存 8s + 单请求 2.9~3.6s ⇒ 槽里的值最多落后 **~10s**; 载荷顶层 ts 只有 1s。
   实测同一时刻: 缓存 `cpu_pct 18.0 / temp 76°C` vs 直连 `/health` `55.4 / 86°C` —— 差 37 个点 / 10°C。
   ⇒ 带子右端必须画 `Intel Ns` (黄 ≥12s) ; `stale` (≥2×ttl 或 online=False) ⇒ 画红 `Intel 陈旧`
   **并把端侧槽全部降为灰灯 + 「—」** (2026-10-23 前这里是照常画旧数, 看着像实时)。
3. **NPU/GPU 的 `duty_pct` 是「每路」占空** = `busy_ratio / streams`。实测 NPU `busy_ratio 1.94` / 2 路
   ⇒ 槽面原来写 97%, 实际是**已饱和**且容易被读成「还有余量」。现口径: `busy_ratio ≥ 1.05` 写「满载」+ 满条,
   原始倍数留在悬停的并行调度里。

另: 产品档 `active_product` 会被**训练编排器**在开跑时改成 550A、跑完再改回 ⇒ 底部状态带会在
550A/550C 之间跳 (槽位/数据源跟着换)。这不是状态带 bug, 是唯一依据在变; 别把跳变当成「数据不准」。

## 改这个必须先重启 8796, 不是只重启控制台

`/status/all` 由 **sam3-seg.service** (systemd, `tools/sam3_seg.py --serve --port 8796 --lazy`) 出,
`status_hub` 在它进程里。新增的顶层字段 (`lan`) 不重启这个服务永远读不到 ——
症状是界面一直画「—」而代码明明改了。顺序:

```bash
sudo systemctl restart sam3-seg.service && sleep 6 && systemctl is-active sam3-seg.service
curl -s 127.0.0.1:8796/status/all | python3 -c "import json,sys;print(json.load(sys.stdin).get('lan'))"
```

然后再 `tools/gui/restart_console.sh` 让状态带加载新代码。

## 取证 (两个工具, 都不用切唯一依据)

- `tools/gui/status_panel.py --selftest` —— 46 项全绿, 含 550B 双模式 9 项纯判据
  (槽名/槽值/chip 名/占空/`hw` 写的是 Intel, 远程时 chip 仍是 L2..L5)。
- `tools/render_strip_550b.py --out /tmp/x` —— 离屏渲染两种模式各一张 PNG + OCR 文本,
  直接看到「远程 → GPU/CPU/内存/磁盘」「局域网 → NPU/GPU/CPU/内存 + 端侧模型 chip」。
