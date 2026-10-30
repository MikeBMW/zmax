# 记忆层真正进状态空间回路 (L2/L3/L4)

## 1. 桥模块 `src/lerobot/memory/mem_feed.py` 的三个职责

| 职责 | 落点 | 契约 |
|---|---|---|
| 热通道 | `/dev/shm/zmax_mem/feed.json` | 记忆节点每拍 `publish(section, payload)`；规划节点每拍 `feed()` 读；payload 带 `t` + `fresh`(3s 内) |
| L2 肌肉 | `data/memory/ar_muscle.json` | 按 `kind` 累计段实测时长 `{n, mean_t, plan_t, labels}` + `total_segs` |
| L3 流程 | `data/memory/ar_cycles.jsonl` | 每圈一行：`wall_s / n_mods / tact_s / uph / acc_s / travel_s / scale / kl2 / jumps / ok` |
| L4 安全 | `data/memory/ar_safety.json` | 违规累积 (段间硬跳/超速) + 由它收紧的 `v_cap / dv_cap / smooth / continuity_mm` |

铁律：
- 读一律 `(mtime_ns, size)` 缓存。`muscle_memory.json` 4.7MB，10Hz 回路每拍 `json.load` 一次就是 70ms。
- 写一律 tmp + `os.replace`，且节流；写失败只记日志，**绝不断回路**。
- feed 缺席/过期 ⇒ 规划走标称值（记忆是增强，不是依赖）。

## 2. 节点壳的三道闸 (只开一道等于没开)

1. `PURE = False` ⇒ `compute()` 只 `_passthrough`，实现不执行。trace 状态会写「直通 (PURE=False)」。
2. `IMPL_KEY` 漂移 ⇒ 壳调用别的实现（实测 L4 记忆节点指到 `ss_world`，跑的是执行节点）。改壳时同时核 `IMPL_KEY`。
3. 实现返回 `True/bool` ⇒ 壳判“非 dict”按直通处理。**实现必须 return 业务 dict**；这份 dict 顺带当 `out1` 供下游/画布显示。

验收：`prj.step(only=[...])` 后逐节点看 `status` 是否为「实现执行」，再看 `out1` 端口值是不是那块数据（不是 None、不是上游透传）。

## 3. 回路性能预算 (10Hz ⇒ 单拍 <100ms)

- `canvas_loop.json` 现在带逐节点 `ms`（`project.step` 里按 `perf_counter` 记，落 `traces[].ms`），加节点前后对比这一列，别看 `is-active`。
- 记忆节点本身很便宜（0.02ms 级），消失的预算多在：大 json parse（未缓存）、每拍写共享记忆、每拍刷盘。
- 节流套路：`st.put(...)` 60s、`publish(...)` 1Hz、节流期间返回上次视图（`_LAST[section]`），下游/取证仍拿到值。

## 4. 学习归一 (否则越练越慢)

两个偏差，要分两步消：

```
① 量化偏置: 段时长被回路 tick 量化 (6Hz ⇒ 每段多算 ~半拍 83ms; 0.40s 的段实测 0.51s ⇒ k=1.27)
   ⇒ k_kind = clamp(mean_t / plan_t, 0.8, 1.3) 后, 每个 k 除同类中位数
② 总量漂移: 记忆成熟度不同会让整圈总时长不同 (同表两台机 294 vs 302 UPH)
   ⇒ 再把全部 k 缩放到 Σt·k = Σt; L2 只决定“段间怎么分配”, 一圈总长归 L3 节拍
```

收敛判据：`kl2` 相邻圈变化 <3% 且样本 `n` 在涨 = 已收敛；某 `kind` 的 k 顶到 clamp 边界 = 它的标称 `t` 与实测形态不一致，去查段表，不要继续放大 k。

## 5. 节拍：真值只有圈墙钟

```
acc   = Σ max(t_i·k_i, dist_i / v_cap) + Σ gap_i / v_travel     # 物理下限
scale = min(1.0, acc / (tact_target × n_mods))                  # 只许放慢, 不许超速
wall  ≈ acc  (差 <1s)  ⇒  tact = wall / n_mods  ⇒  UPH = 3600 / tact
ok    = tact ≤ 3600 / uph_target          # 对目标判, 不对内部留余量的目标判
```

- `gap_i = dist(prev.b, next.a)`：跨件/换工位的换位缺口。不补时间 = 单帧瞬移白拿时间（实测每圈 10 处、合计 14.9m，能虚报 +7%）。
- 补法：`t_eff[i] += gap/v_travel`，并把该段起点改成上一段终点（视觉与执行都连续）。
- 小缝（≤60mm）直接连续化；大缝必须走上面的过渡预算，**不要**用线性插值硬拉（900mm/0.4s = 2260mm/s 超速扫掠）。
- `v_cap` / `v_travel` 都是声明口径：接真机前按机器实测重设，报告里写明 UPH 依赖哪个值。
- 段内平顺：`u = smoothstep(ratio)`（五次 S 曲线、首末速度为 0）。验收逐拍核 `u == smoothstep(mem.u_ratio)`，命中率 100% 才叫生效（段 <1 拍的样本不作数）。

## 6. 常驻监控 (7 条判据, 每 15s 取证 / 60s 落台账)

| # | 判据 | 阈值 |
|---|---|---|
| ① | 回路 | tick 在涨、age<3s、`cost_ms`<100、`err` 空 |
| ② | L2 | `n_total` 在涨、`kl2` 邻圈漂移 <3%（收敛） |
| ③ | L3 | 最近一圈 `uph ≥ 目标`、`tact ≤ 3600/target`、`|wall−acc|<1s` |
| ④ | L4 | `big_jumps=0`、`overspeed=0`、`v_cap` 未被动收紧 |
| ⑤ | 记录 | 图像+位姿记录器帧龄 <3s、今日帧数在涨、图-位姿同拍 skew<50ms |
| ⑥ | 建图 | 地图服务 `ready`，且深度/图像源不陈旧 |
| ⑦ | 零指令 | `actuator_calls.log` 不存在或 0 字节（没下发过动作） |

输出：`/dev/shm/zmax_mem/watch.json`（最新，供 CLI/页面）+ `zmax_data/ss_live/mem_watch.jsonl`（60s 一行）+ 判据翻转才写 `mem_alert.txt`（不刷屏）。

## 7. 带时间戳的图像+位姿记录

- 触发式采集（“臂动才记”）满足不了“持续记录”；另起一个固定频率的记录器（2Hz）无条件记录。
- 每行：`ts_grab / ts_pose / ts_pose_recv / skew_ms / frame / src / wh / bytes / pose{xyz+q+rpy} / pose_clock_drift_ms`。
- **控制器时钟可能与主机差几十秒**（实测 `tcp_pose` header 比主机墙钟快 51s）⇒ 配准用“本机收到位姿的墙钟”，header 戳单独留证。
- 磁盘红线按 GB 上限删最旧日期目录；状态落 `/dev/shm/.../status.json`（`ok/fps/n_today/skew/disk_gb`）给监控读。

## 8. 取证命令

```bash
python3 -c "import json;d=json.load(open('zmax_data/ss_live/canvas_loop.json'));print(d['cost_ms'],[ (t['id'],t.get('status'),t.get('ms')) for t in d['traces']])"
python3 -c "import json;c=json.load(open('zmax_data/ss_live/ar_cmd.json'));m=c['mem'];print(m['seg_t_eff'],m['seg_t_raw'],m.get('acc_s'),m.get('travel_s'))"
# 逐拍验 S 曲线 + 图位姿 skew
tail -1 data/memory/ar_cycles.jsonl
```
