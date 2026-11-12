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

## 9. L2 记忆库: 技能库 / 操作库 / 标杆 / 轨迹, 一个只读入口

口径: **要记忆的工程配置·操作·点位全部由记忆节点落库, 其它节点只 `query()` 查询**, 不直读原始 json。

| 库 | 持有节点 | 内容 |
|---|---|---|
| `skills.json` | `n_l2_muscle` | 技能点定义 + 功能接口 (ros 接口 / 参数 schema / 前置 / 判据 / 步骤) |
| `ops_cards / ops_points / ops_seq` | `ss_mem_l2` | 工艺卡(工艺编排) · 固定轨迹点(示教 tcp) · 段序列+节拍口径 |
| `champs.json / ledger.json` | `ss_mem_l2` | 固化标杆 `(seed|stage)→champ_u/champ_x` · 实测台账 `{n, mean_t, plan_t}` |
| `traj.json` | `ss_mem_l2` | 理想轨迹, 每条必带 `executable` |

实现要点 (可复用):

- 只读入口一个函数: `query({skill|iface|card|point|champ|traj|measured|seq|stats})`; 再加 `stats()` 给节点输出/大屏/报告同源。
- **写权限写进代码**: `put_*(entry, writer=...)` 只接受记忆节点名 (`n_l2_muscle` / `ss_mem_l2`), 其它抛 `PermissionError` ——"只许记忆节点写"靠自觉一定会被绕过。
- 每条 entry 带 `src`(原文件) + `sha`(内容指纹) + `at`(入库时间); 重建脚本从真源现算, 旧库先备份, 自检拿 sha 对账 ⇒ **改真源不重建 = 自检红**, 这是特性。
- 计数对账一定按"真源条目集合的并集"算 (原子+组合+示教去重); 工艺卡按**工单号**做主键, 场景号只做查询回话 (`SCN-07-AOI` 可能有 T1/T2/T3/主 四张), 用场景号当 key 会静默丢卡。
- `index.json` 承载 `counts + 每库 sha + built_at`, 界面/报告只看这一份, 别各自扫目录。

轨迹库必须标 `executable`, 否则就会拿参考序列当真机指令:

| kind | 来源 | 可下发 |
|---|---|---|
| `sim_champ` | 仿真标杆整段 u/x | 否 (归一化, 只能作前馈参考/预览) |
| `taught` | 示教技能点位序列 (tcp pos+quat) | 是 (move_line 逐点) |
| `spline` | 示教点五次插值稠密路径 | 是 |
| `demo_file` | 手把手录制文件 | 是 (按文件回放; **只索引不复制**大文件) |

## 10. `mm_hits = 0` 的三种成因 (别一律当"链断了")

1. **该 seed 没练过**: 标杆按 `seed|stage` 分桶, 库里只有 101~104 时跑 seed 0 必然 0 命中。
2. **读到了另一份库**: 引擎 `get_memory()` 的默认 path **相对模块目录**解析 ⇒ 常是 `src/data/muscle_memory.json`, 不是仓库根的 `data/muscle_memory.json`; 同仓见过三份副本各存一半。
3. **按设计旁路**: L4 干扰轮会主动 `_mm_on=False` (「布局变了无标杆」), 此时 0 命中是正确行为。

一分半钟的三连确认: `print(sim.muscle.path)` → `len(sim.muscle.db)` → `sim.muscle.get_champ(seed, 段)`。
取证脚本对第 1 种要打印「该 seed 无标杆 (库 n=0)」而不是 ❌ 未接管 —— 否则读报告的人把"没练过"当缺陷去修。

## 11. UPH 必须双口径 + 按段类归因

同一条段表给两个数, 合写一句就是承诺超交付:

```
计划口径 = Σ 段表 t / 件数                      # 按速度上限规划出来的
实测口径 = Σ (t × 台账 mean_t/plan_t) / 件数    # 把现场实测均值代回每一段
300 UPH ⇒ tact ≤ 12.000 s/件
```

- 段表按 **`mod` 字段**取"一件一组"(每件固定段数, 例如 28 段 / 11.5s), **不要用整表均值** —— 整表含平铺/搬运段, 会稀释成好看的数。
- 台账是**活数据**: `n` 每轮在长, 连 `plan_t` 都会被上游改写 ⇒ 报数字要带采集时刻, 并说明随跑动会变。
- 差额按段类列 (`move +3.5s / up +1.0s / down +0.7s / pull +0.6s`), 结论形如「独立运行 ✅ · 计划口径 300 ✅ · 实测口径 300 ❌ (差 X s/件)」, 再给出要保 300 必须动哪几类 (改路径/提速/合并行程), 不让"能"或"不能"单字结案。
- 复量脚本落 `tools/` (cap=l2 独立跑 + 双口径 + 归因), 别每次对话手算。

## 12. 记忆节点自己的库, 别指望 `IMPL_KEY` 注册

`PURE=True` 只是第一道闸: 壳仍要走 `registry.get(IMPL_KEY)` 拿实现, 记忆节点这种"自己就是库"的节点如果没注册, 状态会停在「实现未注册 → 直通」。两条路二选一并在验收里写清:

- 在 `compute()` 里**直接读库** (记忆节点持有库, 合法), 顺带把查询入参 `ctx["in1"].value` 透传 (`{"skill": id}` 之类);
- 或注册实现, 但实现必须 return 业务 dict (返回 `True` 会被壳当"非 dict"再过滤成直通)。

两条都要带 try/except → 回退直通, 并且 `LAST_STATUS` 要写清是"技能库查询 (N 条)"还是"异常 → 直通", 否则事后分不清是没接还是抛了。
