# Z-MAX 550A/550B/550C 阶段结果（远程模式）· 2026-10-26 06:36

**当前环境**：非局域网。远程链路 = 本机 → ECS 47.93.88.143:22 → ECS 环回 22022（Orin 反向隧道）→
Orin 192.168.23.66 → Intel 192.168.23.70:22（经 18822 转发）。公网 22022 被挡，只能走 ECS:22 跳板。
本机无 192.168.23.x 地址（产线 USB 网卡不在位），所以**一切 Intel/Orin 操作都是远程模式**。

---

## 1. SE(3) 几何阻抗算法：Intel 上真跑，9 组判据全过

在 550C(Intel) 的 `train_venv` 上执行 `python -m lerobot.manifold.se3_impedance --selftest`：

| # | 判据 | 结果 |
|---|---|---|
| ① | 分量转换 [ω;v]→[ρ;ω] 与往返 | PASS |
| ② | 伴随 Ad_g·Ad_g⁻¹=I；纯平移分块 | PASS |
| ③ | 误差/势（g=g_d ⇒ ξ_e=0,V=0） | PASS |
| ④ | **被动性 V̇≤0**（含负刚度反向验证能测出 V̇>0） | PASS |
| ⑤ | 闭环收敛（V 单调降，残差→0） | PASS |
| ⑥ | 各向异性：轴向 4.00N vs 侧向 0.80N（5×），方向朝目标 | PASS |
| ⑦ | 饱和 + 一阶低通 | PASS |
| ⑧ | 力前馈（Kf=0 恒等于 F_d；kf_z=0.5 时 F_d−3N） | PASS |
| ⑨ | 体雅可比 τ=Jᵀu（维数/逐位） | PASS |

**代码一致性**：550B ↔ 550C 共 2457 个 `.py` 文件 md5 **全等（0 差异）**；
`src/lerobot/manifold/se3_impedance.py` md5 = `4b45443a4aabc9700b2c314f90c5e48f` 两边同值。

与原始方案文档的两处差异（已在代码注释里写死原因，避免被"修回去"）：
- 符号用 `u = +K·ξ_e − B·ξ + F_d`（文档写 `−K·ξ_e` 是把 g̃ 当成 g_d⁻¹g 的笔误；按文档符号闭环
  实测 V 从 0.08 炸到 1.8e7、残余 299 米）
- 分量顺序统一 `[ρ; ω]`（`lie_intent.se3_log` 返回 `[ω; v]`，必须转，否则"侧向软/轴向硬"静默变反）

## 2. 550C 自主进化：在跑，已 864 代

Intel 上 `se3_gravity_evolver_intel.py` 进化**阻抗参数**（k_lat/k_ax/k_rot_*/α/kf_z；u_max 不进搜索空间）：

- 代数 **864** · best_fitness **−0.0681**（4 项归一化加权 + 被动性硬闸）
- 最优：`k_lat=199.7, k_ax=360.0, k_rot_lat=1.78, k_rot_ax=2.86, α=0.192, kf_z=0.505`
- 被动性违反次数：**0**（违反一次整代废弃，不是加权项）
- 诚实项：**近 324 代未再提升（平台期）**，末代 fitness −1.68（未采纳并回滚）

**已修的管理问题**：同一进化器被起了 14 个 `zmax_evolve_intel` 实例、3 个 `symmetry_evolve` 实例，
互相抢 CPU、并发写同一份台账 → 已归并为各 1 个（`tools/sync_evolution_550.py`，含保活与采纳）。

## 3. 550A 同步训练 → 550C 部署（开发→训练→部署全流程闭环）

- 用 550C 进化出的 HP（`MR_HP`）在 4060 上训 400 步：**101,266 参数**，dp_med **3.96 mm**
- 产物 `geometric_branch_550a.pt` (403KB) 推到 Intel → **在 Intel 上真加载**：
  `missing=0, unexpected=0`；前向输出 `xi[2,6] / v_n[2,3] / h_g[2,128] / log_sigma[2,9]`
- 证据脚本：`tools/smoke_load_ckpt_intel.py`（在目标机上加载+前向，不是只看文件到位）

## 4. 550C 节点级取证（92 节点 / 70 可执行）

| 结论 | 数量 | 说明 |
|---|---|---|
| ✅ 真在 Intel 跑 | **52** | 引擎主循环 10Hz（cycle 519,468，单周期 8.1ms）、万有引力 gravity_trace、逐技能物理闸、SU(2)/流形/标定、YOLO-OpenVINO(8800)、AR/轨迹台(8797)、DDS 桥、进化器 |
| ❌ 未在 Intel | **16** | SAM3 分割(ss_seg)、L3/L5 LLM 系(ssllm/ssreason/ss_l5/n_dsvl/n_vlm_llm/ss_lora_l3/ss_mem_l3/ss_mem_field/ssintact_dec)、INTACT 系(ssintact/swintact/ss_lora_l4)、仿真世界 3 个(swds/sworld/ssdata，属 550B) |
| · 非执行 | 22 | 背景行/可视化/UI/模式开关 |
| ? 未归类 | 2 | ss_moe / n_realscene |

明细：`zmax_data/runtime/550c_nodes_audit.json`（含每节点证据串：文件新鲜度/端口/进程）。

## 5. 550B 单线程调试程序

查到真问题：桌面快捷方式起的控制台（pid 52080）环境里**没有** `ZMAX_SINGLE_THREAD` /
`OMP_NUM_THREADS`，实测 **41 个线程**，而档位表写着"线程=1"。
已在 `tools/gui/studio.py` 解释器最早处强制注入与 `vscode_launch.SINGLE_THREAD_ENV` 同源的 10 个变量
（含 `ZMAX_MULTI_THREAD=1` 逃生口），实测 `torch.get_num_threads()=1`，下次启动即生效。
未重启正在看的控制台。

## 6. 链路稳定性（远程模式的关键修复）

故障链：5 个 tunnel unit 各起一条 ssh（每条再带一个到 ECS 的 ProxyCommand）→ 断一条各重启各的 →
十几秒内对 ECS 打十几次重连 → 撞 MaxStartups → "Connection closed by remote host" 随机踢 →
越踢越重启 → 最后 **0 个端口在监听**（看着像 Orin 死了，实际 39053/39061 都活着）。

修法：**一条 ssh 带走全部 10 个端口** + ExecStartPre 等端口释放 + 无限重启（RestartSec=5）+ 20s 巡看。
现状态：18822/39071/8792/18800/10082/10083/8816/8812 全在听，`zmax-orin-legs` NRestarts=0。

## 7. 阻塞项（需要产线网卡 or 额外资源）

| 项 | 现状 | 解锁条件 |
|---|---|---|
| SAM3 在 Intel 完整跑 | Intel 无权重、无 transformers、无外网；走 ECS 推 3.3G 实测每次 10 秒就 broken pipe（~350kB/s） | 产线网卡直连后自动推（`zmax-onboard-550c.timer` 每 60s 巡看，到位即推 SAM3 3.3G + L5 972M + INTACT + 装配件 + 校 sha256） |
| L3/L5 节点在 Intel | Intel 无 LLM 权重、无外网；DeepSeek 走 API 需要出网 | 同上（或给 Intel 出网/代理） |
| INTACT L4 执行体在 Intel | 权重在 550B，Intel 未见常驻进程 | 同上 |

## 8. 交付物清单（可直接打开）

- `zmax_data/runtime/550c_nodes_audit.json` — 92 节点逐条取证
- `zmax_data/runtime/evolution_sync.json` — 进化同步每轮结果
- `zmax_data/runtime/hjepa_mr_550a/` — 550A 训练产物（ckpt + result.json）
- 代码：`tools/sync_evolution_550.py`、`tools/verify_550c_nodes_on_intel.py`、
  `tools/smoke_load_ckpt_intel.py`、`tools/orin_path_autoswitch.py`、`tools/onboard_550c_assets.sh`
- 提交：`ce65442`（已 push）
