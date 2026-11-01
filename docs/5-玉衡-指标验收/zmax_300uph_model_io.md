# Z-MAX 状态空间工程 · 各层模型 I/O 与 action 传递链（实测）

生成 2026-10-29 · 数据源 `zmax_data/ss_live/model_io_snapshot.json`（`tools/probe_model_io.py` 实跑 22 个节点）
标杆：回放段表 `tact_steady_s=11.42s ⇒ 315 UPH`，目标 `uph_target=300`（每件预算 12000ms）

---

## 1. 四层 I/O 表

### L2 感知（elapsed 5.17s）

| 节点 | 状态 | 单拍 | 输出（实际值） | 去吃 |
|---|---|---|---|---|
| `ssyolo` | **实现执行** | **5103ms** | `frame=world units=mm verified=false`，source: metaworld渲染帧 / K=fovy / ext=cam_pos+mat0 / depth=yolo-depth-head | `ssplan.in2`（视觉） |
| `ssaoi` | **直通 PURE=False** | 0.2ms | 无 | 应→ `ssplan` / L2 检测 |
| `ssvlm` | **直通 PURE=False** | 25ms | 无 | — |
| `ss2d3d` | **直通 PURE=False** | 9ms | `frame=world`（无点） | — |
| `sssensor` | **直通 PURE=False** | 32ms | 无 | `ss_mani_eng.in1` |

**判断**：L2 感知只有 YOLO 一路在真跑，且它单拍 5.1s —— 300UPH 每件 12s，感知就吃掉 42%。AOI/VLM/2D3D/传感器四路都还是空壳。

### L2 规划（0.06s）

| 节点 | 状态 | 单拍 | 输出 | 去吃 |
|---|---|---|---|---|
| `ssplan` | 实现执行 | 18.8ms | `seq=1 kind=move label="→ 槽1 上方" a=[490,499,240] b=[490,499,218] t=0.3` · `mt_name="右臂 · 上料槽取模块 → 插入目标孔"` · `mt_n=56` · vision `verified=false conf_max=0.974 n_points=3` | `ssact.in1` |
| `sslat` | 直通 | 16ms | 无 | `ss_mani_eng.in4` |
| `ssllm` | 实现执行 | 28ms | `n=4 src=TaskPlanner.plan` | — |

### L2 执行（0.05s）

| 节点 | 状态 | 单拍 | 输出 | 去吃 |
|---|---|---|---|---|
| `ssff` | **直通** | 15ms | 无 | — |
| `sslimit` | **直通 PURE=False** | 24ms | **无 `u_sat`** | `n_exec.in2` / `ss_grav_h.in5` |
| `n_exec` | **直通** | 0.2ms | 无 | `ssact.in1` |
| `ssact` | 实现执行 | 8.8ms | `u_sat=[0,0,0,0] u_cmd=[0,0,0,0] real_send=false` | `ssworld` |

### L3（0.03s）

| 节点 | 状态 | 单拍 | 输出 | 去吃 |
|---|---|---|---|---|
| `ssdec` | 实现执行 | 33.7ms | `base_L2`→`nominal_L3` 有真值；**常驻引擎下** `nominal_src="SmolVLA+LEW 前向 (checkpoints/004000)" degraded=false`；**单跑一拍** 则 `degraded=true nominal_src="降级: 测地线块"`；`l4_cond_injected=false` | `n_moveit.in2` / `ssff.in2` / `ss_grav_h.in3` |

### L4（12.72s）

| 节点 | 状态 | 单拍 | 输出 | 去吃 |
|---|---|---|---|---|
| `n_calib_mani` | 实现执行 | **923ms** | `M=3.643 frame_real=true src=manifold_engine.py` | `ss_mani_eng.in6` |
| `ss_mani_eng` | 实现执行 | 56ms | `dim/mode/min_eig/det_g/kappa/tau/H` + `p/phi/grad` | `ssintact_dec.in1` · `ssmani_c.in2` · `ssmani_p.in2` · `ssched.in4` · `n_intent_direct.in1` |
| `ssmani_c` | 实现执行 | 17.9ms | `progress_m=0.0113 risk_m=0.05 Vdot=-0.00595 axis=[0,0,1]` | `ssdec.in5` · `ssvideo.in3` |
| `ssmani_p` | 实现执行 | 8.7ms | `V_p=0.1606 eta=0.0 grad=[0.279,-0.331,-0.131]` | `ssdec.in5` · `ssvideo.in4` |
| `ssintact` | 实现执行 | **11586ms 冷 / 32ms 热** | `trained=true policy=direct chunk_shape=[8,10] source=metaworld skill_ctx_dim=24` | `ssintact_dec` |
| `ssintact_dec` | 实现执行 | 125ms | `u_ff=[0.0641,0.0261,0.0917,-1.0] u_ff_source="intact(chunk×K_ACT=0.5)" l4_cond_dim=192 weight=0.3` | `ssdec.in1` |

**判断**：L4 是唯一四路全真跑且都有真值的一层 —— 流形引擎、接触流形、性能流形、INTACT 全在出数。

### L5（0.05s）

| 节点 | 状态 |
|---|---|
| `ss_l5` / `n_dsvl` / `n_vlm_llm` | **全部直通 PURE=False** |

---

## 2. action 是怎么被影响的（接线 + 断点）

```
ssplan.out1 ──► ssact.in1       段表(右臂绝对点 a→b, t=0.3/段)
L4 流形族 ───► ss_mani_eng ──┬─► ssintact_dec ──► ssdec.in1   (l4_cond 192维, 未注入模型)
                             ├─► ssmani_c.out1 ──► ssdec.in5  (接触流形, 未注入)
                             ├─► ssmani_p.out1 ──► ssdec.in5  (性能流形, 未注入)
                             └─► sssched.in4 / n_intent_direct.in1
ssdec.out1 ──┬─► n_moveit.in2    action 直通 MoveIt
             ├─► ssff.in2        前馈/肌肉记忆
             └─► ss_grav_h.in3   L3 名义动作 ξ_d
sslimit.out1 ─► n_exec.in2       🛡 限幅 → 执行器   ← 直通，不出 u_sat
n_exec.out1 ──► ssact.in1        动作命令 → 本体
ss_grav_h.out1 ► n_moveit.in3    力场裁剪后动作
ss_grav_h.out2 ► n_exec.in3      u(6)=[F;M] 力/力矩 → L2 收口（标签注明**默认关**）
```

**实测结论（2026-10-29 修复后）**：`ssact.u_cmd = [-0.034, -0.0774, -0.0072, 0.6]`，不再是全 0。

修了两处断链：

1. **`_SS_STATE["u"]` 全仓库没人写** —— L3 只把 `nominal_L3` 落盘，从不写运行时状态；
   `sslimit` 读 `_SS_STATE.get("u", zeros)` ⇒ 永远 zeros ⇒ `u_sat=zeros` ⇒ `ssact u_cmd=zeros`。
   修：`flow_matching_impl.run` 输出前写 `_SS_STATE[u]/u_src/u_degraded/u_ts`。
2. **`sslimit` 双闸** —— `n_limiter.PURE=False` + `safety_limit_impl return True`（非 dict ⇒ 壳又判直通）。
   修：PURE 默认开（`ZMAX_LIMIT_OFF=1` 退）+ 返回业务字典。

实测：

    ssdec    172.1 ms  nominal_L3 = [-0.033999, -0.077432, -0.007174, 1.1]
    sslimit   26.8 ms  u_sat      = [-0.033999, -0.077432, -0.007174, 0.6]  clipped_dims=1
    ssact      9.2 ms  u_cmd      = [-0.033999, -0.077432, -0.007174, 0.6]  real_send=false

第 4 维 1.1 被 0.6 限幅 —— 安全边界真的在起作用。
安全口径不变：sslimit 只做数值饱和不下发；真机仍需 8793 授权，由 n_exec/ssact 收口。

## 2b. AOI 旁路（2026-10-29 接入）

`ssaoi` → `n_inspection` PURE 默认开；真实现 = 本机 `quality_check.AOIQualityChecker.check`
（图像处理缺陷检测，不依赖 .23 远程服务）+ `_surface_bypass` 走 10083。

实测输出（无真值但有输出、接口对齐）：

    kind=aoi · pass=False · verdict=gaps_washed · scratch=58 · blob=14
    defect_n=72 · items=6 · focus=446.6 · gray_dev=39.1 · edge_frac=0.0427

性能：冷 8042ms → **热 11.3ms**（10083 不在线时 0.25s 探活短路 + 60s 冷却）。
注：`.23` 整机不在线，远程 10082/10083 模型旁路等它上线才能接；当前用本机图像处理口径，接口已对齐。

---

## 3. 到 300UPH 的断点（按影响排序 · 2026-10-29 现状）

1. ~~`ssintact` 冷启 11.6s~~ → 热态 32ms；冷启只在第一拍付，常驻引擎预热即可。
2. ~~`ssyolo` 单拍 5.1s~~ → **热态 7.5ms**（冷启 4.9s = 对齐器加载 3.7s + 首推理 1.15s）。
3. **`n_calib_mani` 923ms** —— 已内部节流 5s/次，单次仍近 1s，属可接受但不参与每拍。
4. **仍未开的 PURE**：`ssff`、`n_exec`、`ss2d3d`、`sssensor`、L5 三个（`sslimit`/`ssaoi` 已开）。
5. **L4→L3 无因果**：`l4_cond_injected=false`（ckpt 未训该通道，`ensure_l4_cond` 是 scale=0.02 随机投影）。
6. **段表 392 段全部 `arm=none`** —— 左臂只按"等效时间 3.0s/循环"计入速度剖面，**没有自己的段**。
   这是"左右手臂都动"的直接缺口：现在只有右臂在动。
7. ~~AOI 未接入~~ → 已接（本机图像处理口径）；`.23` 远程 10082/10083 待其上线。
8. **L5 全直通**：`ss_l5` / `n_dsvl` / `n_vlm_llm` 都不参与，场景理解没进链路。

---

## 4. 执行顺序（对齐 300UPH）

| 阶段 | 动作 | 验收判据 |
|---|---|---|
| S0（本次）| I/O 全表 + 飞书 10 分钟报告 + 配置中心 | 报告能自动发、字段是实测值 |
| S1 L2 | AOI 10082/10083 旁路进 `ssaoi`；`ss2d3d`/`sssensor` 置真跑；`ssyolo` 降时延 | `ssaoi` 状态=实现执行且带判决；感知合计 <2s |
| S2 L2 | `sslimit` 置真限幅写 `u_sat`；`ssff`/`n_exec` 接真值；段表补 `arm` 字段 + 左臂段 | `ssact.u_cmd ≠ 0`；左右臂都有段 |
| S3 L3 | SmolVLA+LEW 常驻预热（冷启 22.7s 挪到启动期）；`degraded=false` 稳定 | 连续 10 拍 `degraded=false`，`n_done` 递增 |
| S4 L4/L5 | 证明流形引擎有效性：关/开流形对比 `Vdot`、`risk_m` 与落地误差 | 有量化对照（非"接上了"） |
| S5 | 全闭环 UPH 实测 ≥300，否则回退重训 | `11.47s/件 → ≤12.0s/件` 且双臂都动 |

全程 AR 场景仿真，真机零指令（`real_send=false`）。
