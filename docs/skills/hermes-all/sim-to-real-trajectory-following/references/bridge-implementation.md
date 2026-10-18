# 仿真轨迹 → 真机跟随: 实现 recipe 与实测数字

## 1. 数据面: 从仿真侧取什么

每 50ms 读状态空间落盘文件, 取三样:

```
plan_from_vff.json  →  bridge(bool 总闸) · frame · truth_xyz(仿真真值位置, 米) · u_ff_mms(期望速度)
trace_live.json     →  阶段(接近/对位/下降/抓取/抬起/转移/放下 …)
```

- `bridge=false` ⇒ 直接退出(画布开关就是总闸, 不自己发明第二套开关)。
- 阶段表随场景变(插拔 8 段, 摆盘是 下降→抓取→抬起→转移→放下, **没有"接近"**)⇒ 事件触发一律用
  "阶段变了"或 `frame` 回绕, **不要写死某场景的阶段名**。
- 幅度量级要先用真值量出来: 同一段 20s 里仿真真值振幅 X 211~280mm / Y 2~78mm / Z 41~142mm;
  而把速度直接积分出来只有 X 19 / Y 4 / Z 33mm ⇒ **别用速度积分当参考轨迹**(误差 20mm 级),
  用真值路径或真值模板。

## 2. 一次录模板, 之后只回放

```
采样真值 40s (臂不动) → 相对首点做差 → 存 {path:[[dx,dy,dz]…], dur_s, len_mm, n, stages}
```

实测一轮: 832 点 / 42s / 696mm / X270 Y78 Z142mm。

- 模板固定, 不再自动重录(否则自我衰减: 696→62→11mm)。
- 允许重录时只接受"比现有长 20% 以上"的模板, 否则打印"⏭ 录到的模板 62mm 比现有 696mm 短, 不覆盖"。

## 3. 下发: 一条完整路径 + 严格串行

```
segs = 等弧长重采样([[x*1000*scale for x in q] for q in tpl], npts)   # 米→毫米
if total > max_path: 等比缩到 max_path
dur_eff = tpl_dur * dur_scale
speed   = clamp(total / dur_eff, 2, 100)                              # 名义 mm/s

reset   →  睡 0.15s  →  path{id, points: segs, speed, zone, guard_box}
```

- **reset 先清旧队列**: 上一个进程/上一轮可能还排着命令, 不清就会两轮叠着走。
- **串行闸**: 轮询 `agent_result.json`, 只认 `id == 自己发的 id`; 见到才允许下一条。
- **静/动闸**: 用 `/pose` 判"连续 0.35s 没动"才发下一条(5Hz 真值足够), 避免在自己还在走时插命令。
- **回执里带 verdict**: `PATH DONE` = 走完; `扫掠越界急停: ['x']` = 包络拒; `ABORT 前置条件` = 模式/点动拒。

参考实现(本仓): `tools/bridge_episode_path.py`(跟随) · `tools/capture_truth_template.py`(真值模板)
· `tools/bridge_path_recorder.py`(真机轨迹录制, 给 AR 三维视图用) · `tools/stop_all_bridge.sh`(按 pid 文件停)。

## 4. 包络 (guard_box) 的正确用法

```
guard_box = {ax: [anchor[i]-band/1000, anchor[i]+band/1000] for i,ax in enumerate('xyz')}
```

- 锚点 = **启动那一刻的 TCP**; 现场手动挪过臂之后必须重锚, 否则连拒。
- 拒绝要能被自己识别并恢复: `if "越界" in verdict: anchor = 当前位姿; 重建 guard_box; 打印 ↺`。
- "前置条件"类拒绝要退避:`if "前置条件" in verdict: print(腿原话); sleep(1)`。

## 5. 实测数据 (留给下一次对口径)

| 场景 | 仿真真值振幅(20s) | 真机 40mm/轮 的 12s 振幅 | 备注 |
|---|---|---|---|
| 插拔 | X 211 · Y 41 · Z 41mm | X 12.9 · Y 2.3 · Z 7.6mm | 横向只有仿真的 1/5 量级 |
| 摆盘 | X 280 · Y 2 · Z 79mm | 同上量级 | 摆盘的"横向"其实是 X 大范围搬移 |

- 一条 40mm 的路(50 点) 名义 4.3mm/s ⇒ 控制器实际约 4s 走完(≈10mm/s), 之后 0.5~1s 空档。
- 想让用户"看得见在动"又要小幅度: 优先压 `--max-path` 到 25~40mm, 再把 `--dur-scale` 压小提速,
  别把幅度放大去换速度。

## 6. 时序/网络不是瓶颈(先量再改架构)

现场怀疑"网络不够实时"时, 一次量完:

```
ip route get <控制器 IP>            → 走哪块网卡(实测 USB 网卡 1Gb 全双工)
ip -s link show <if>               → drops/errors 必须为 0
ping -c 20 -i 0.05 <控制器 IP>     → 实测 RTT 0.098/0.141/0.288ms, mdev 0.046ms, 0% 丢包
写命令→拿到回执的往返               → 实测 11ms(5 次 10.7~11.0ms, 抖动 ±0.3ms)
```

网络 OK 时, "一顿一顿"的锅在**下发结构**(单段命令 = 一次直线)和**主机 CPU 抢占**
(实测相机推流 300% CPU) ⇒ 给跟随进程 `nice -15` + `taskset` 绑核(四核), 而不是改网络。
