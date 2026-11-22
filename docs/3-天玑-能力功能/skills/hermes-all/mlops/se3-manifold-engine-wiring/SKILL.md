---
name: se3-manifold-engine-wiring
description: "Use when 流形引擎要真出 SE(3) 或让 L5 语义引导引擎. 五个静默假通的坑+判据。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [manifold, se3, engine, l5, vlm, canvas, zmax]
    related_skills: [su2-unified-state-space, state-space-canvas-engineering, manifold-engine-math-verify]
---

# 流形引擎 SE(3) 真出 + L5 语义引导 (接线坑)

## When to Use

- 要把流形引擎从 SU(2)/S³ 切到真 SE(3) 输出，或排查“分支有代码但不生效”
- 要让 L5/VLM 场景理解引导引擎（阶段→目标、置信→势场权重）
- 接 H-JEPA 语义（hjepa）/ 几何（hjepa_mr）双通道 provider
- 画布上某条边看着连着、引擎却没反应（端口空转）
- 判据变红但怀疑是判据本身选错（欧拉角等价解那类）

目标链: L5 语义 → T_goal/k → 引擎 SE(3) 螺旋 → decoder → cond[15] → action_head。
下面每条都是**看着对、实测错**的，必须按判据验。

## 1. `Navigator.step` 的 se3 分支默认不是螺旋
原实现是 `slerp(R) + lerp(t)`（注册表却写“螺旋运动”）。ρ 与 φ 不平行、角度 1.2rad 时
与真 SE(3) 指数差 **163mm / 10.1°**；ρ∥φ 或小角度则恰好一致 ⇒ 小样本测不出来。
修：`T2 = T @ se3_exp([ρ;φ]*dt)`（平移经 V(φ) 耦合）。判据：三种情形 max|Δ|=0。

## 2. `ManifoldEngine.project()` 会把位姿洗成 I + 零平移
`project(state)` 内部先 `encoder.encode(state)` 做 PCA 再投影 ⇒ 传 12 维位姿进去，
输出是 `R=I, t=[0,0,0]`（实测），后面螺旋从原点出发，距离反涨。
修：SE(3) 模式**直连** `eng.projector.project(p12)`（SVD 正交化，residual≈1e-16, drift=0）。

## 3. ξ 的方向 + 分量序，两处都要对
- 方向：navigator 是**体坐标右乘** `T @ exp(ξ·dt)` ⇒ ξ 必须是 `log(T⁻¹·Tg)`。
  用 `log(Tg⁻¹T)` 会不进反退（实测 18.130→18.169mm）。
- 序：`se3_chain` 的 ξ = `[ρ(平移); φ(旋转)]`，而 `Navigator.step` 的 v = `[φ; ρ]`
  （源码里 `w=v[:3]`, `v[3:6]` 才是平移）。不重排 ⇒ 平移当旋转、5 步涨到 20.04mm。
判据：连续 8 步距离单调下降 + det(R)=1。

## 4. 静默降级一律改成报错
`p.size < 12` 时老代码 `return p + v*dt`（欧氏直线）——看着像 SE3，实际不是。
改成 `ValueError`，否则调试时永远看不到“分支没走”。

## 5. 语义通道必须用 `HJEPAStateProvider`，不是 `HJEPALiveProvider`
`HJEPALiveProvider.__call__` 返回**裸 ndarray**；引擎 `_hjepa_read` 要 `dict{z1,z2,z3,energy}`
⇒ `manifold_engine.py` 的 `if not out:` 直接 `ValueError: truth value of an array is ambiguous`。
这会被误诊为“引擎没接”，实际是 provider 选错。
- 语义：`hjepa_state.HJEPAStateProvider(root, state_fn, frame_path)` → z_dim=640 (256+256+128)
- 几何：`hjepa_manifold_provider.HJEPAManifoldProvider(state_fn=..., mode="weak")` → ξ(6)/v_n(3)/d_se3/d_normal
- 两通道 **并存不替代**（引擎注释原话：姿态误差与语义纹理揉在单一欧氏 latent 会互相污染）
- `w_phi` 默认 0 = 只观测不动动作，别默认打开

## 6. state7 口径与分量来源要分开标
`state7 = [x,y,z(m), rx,ry,rz(rad), grip]`（与 `_rpy_to_T` 的 Rz@Ry@Rx 严格互逆）。
43D obs 里**只有位置没有姿态**：
```
[0:3]手位置 [3]夹爪 [4:7]光模块位置 [7:11]四元数 [11:18]pad7 [18:36]上帧 [36:39]孔位 [39:43]触觉
```
⇒ 位置/夹爪取 in1 的 43D，姿态必须取 TCP 真值，输出里逐分量标 src，别整体报“来自真值”。

## 7. 画布边不许空转：每条入边写 used/why
`ss_mani_eng` 七个入边（in1 有两条上游）。SE3 改造后只有 in1（43D+L5语义）、in5（阶段先验）
真被消费，其余 in2/in3/in4/in6 在 SE3 模式下不用 —— **必须在输出里写 why**，
否则就是“看着有线其实没人读”。别删边：`SS_MANI_TYPE=su2` 回退时它们还要用。

## 8. L5 引导: **自主标定优先**, 回放点只作参考 (目标来源决定是不是真自主)

分层职责(这条决定架构对不对, 不是实现细节):
```
215 点回放表  = 只读安全基准, L2~L5 只能从它学, 不能改它, 也不能拿它的点当自主目标
L5            = 自主标定: 相机看工件 → 手眼 T_cam2tool → T_tool_base(endInRef) → base_link 3D 目标
L4            = 流形引擎: 用 L5 的视觉目标算 ξ/φ 势场 + 度量
L3            = 模仿学习: obs + cond(L4) → 7 维 action chunk
L2            = 原子技能/标准动作: 从真实轨迹 feed/end_episode 固化标杆
```

**“阶段 → 215 点表区间出口 = T_goal”不是自主标定** — 那是把回放点当目标, 用户明确否掉。
`L5Guide` 的正确优先级:
```
visual_goal()   P_cam→T_cam2tool→T_tool_base→P_base   成立即 return, goal_src="L5_visual"
stage 区间      仅当视觉算不出时退回, goal_src="215点表(参考)" + range_src="均分假设(未标定)"
```
- `visual_goal(port_data)`: 从端口挖相机系 3D 点(`det_xyz_cam`/`xyz_cam`/`peg_xyz_m`/裸 3 元组),
  挖不到就返回 `None` **不编**; 幅值 >5 判为毫米自动 /1000。目标姿态沿用当前工具姿态(位置自主, 姿态暂不猜)。
- 手眼外参读 `models/handeye_state.json` 的 `T_cam2tool`, 加载时验 `det(R)≈1`。
- 置信门控照旧: `conf<0.40 ⇒ k_l5=0`; 视觉目标算出但置信不足 ⇒ 仍返回 T_goal 但 `k_l5=K_MIN` 并标注。
- 取不到语义也取不到视觉 ⇒ `ok=False` + why, 引擎退回 `traj_default` 并如实标。

## 8b. 回放轨迹只读锁: 内容一变就 raise, 不静默继续
`tools/web/real_traj_joints.json` 是 L2~L5 的**唯一安全基准**, 任何层写它就是错:
```python
TRAJ_MD5 = "15e4a986d06eb40f25701fed1270712f"; TRAJ_N = 215
def assert_traj_untouched(path):
    md5 = hashlib.md5(open(path,'rb').read()).hexdigest()
    if md5 != TRAJ_MD5: raise RuntimeError("回放轨迹被修改 …只允许读")
```
在 `_frames()` 加载前调 — 校验点在**每次读**而不是写侧, 因为改它的人可能是别的进程/别的层。
要换代必须经用户确认后**显式更新 TRAJ_MD5**, 那是一次口径变更, 不允许顺手改完继续跑。
换代前先整套备份 + 上锁: `bash tools/backup_traj_215.sh` 拷 joints/phase/hopf/step_cmd/layers_215/跑批日志到
`zmax_data/traj_backup/traj_215_<ts>/` 并出 `sha256sums.txt`(当场 `sha256sum -c` 全 OK), 再
`chmod 444 tools/web/real_traj_joints.json` —— 新轨迹一律写新文件, 物理上堵住覆盖。
验证: 拷一份改一个字节(`0.663`→`0.664`) ⇒ 必须当场抓到 md5 不符。

## 9. 判据要选物理量，别选数值等价物
`R_to_rpy` 验证：用**旋转矩阵往返**（R→rpy→R，500 组 worst=1e-14）；
用“欧拉角数值相等”会因 ry 超出 ±π/2 的等价角假红 88/200 —— 那是多解不是 bug。

## 10. Qwen 权重路径
权重在 `zmax_data/hf_cache/hub/models--Qwen--Qwen2.5-VL-3B-Instruct`（7.1G, 完整），
`hf_home` 是空目录（只有 CACHEDIR.TAG）。`scene_vlm.py` 只找 hf_home ⇒ `_LOCAL_DEF=None`
⇒ 回退联网名 ⇒ 离线必失败 ⇒ `l5_scene_vec.json` 永远 `vec=null, conf=0`。
已改成三根探测（hf_cache → hf_home → ~/.cache/huggingface）。
3B fp16 要约 6-7G 显存，训练占着时起不来。

## 11. A~E 五流形接法 (位置/轴/四元数/滚转/相位) — 五个口径坑

`src/lerobot/manifold/se3_layers.py` 用 **5 个真 ManifoldEngine 实例**承载 A ℝ³(`euclidean`) /
B S²(`sphere`) / C S³(`su2`) / D S¹(`torus`) / E S¹(`torus`), C⇄(B,D) 用 Hopf 耦合;
`MANIFOLD_REGISTRY["se3_layers"]=ready` + `ManifoldEngine.se3_layers()` 惰性构造(不用不建 ⇒ 零回归)。
`ss_engine_loop` 里 `ZMAX_SE3_LAYERS=1` 才每拍算, 写 `rec["se3"]` + `/dev/shm/se3_layers.json`。

1. **C 不许用引擎的 su2 投影器**: 那条分支是 `SU2Element.from_rotvec(bounded_rotvec(v, gain=2.0))`,
   是**有界控制器映射**(转角被 gain 压掉), 当投影用会把四元数改掉。C 的投影=S³ 恒等归一;
   引擎 su2 的**度量**(`e8ds`) 照用 —— 度量链仍是引擎的。
2. **S¹ 用 T² 的退化切片** `[θ, 0]`: 引擎只有 `torus`, 第二角恒 0 时 T² 距离恰等于圆上环绕距离,
   不是近似。D=`[φ,0]`, E=`[2πs,0]`。
3. **`n = R·e₃`, 不是 `R·e₁`**: `tools/se3_hopf.py` 头注释写 `R·e₁` 是笔误, 代码算的是第三列
   (工具接近轴)。判据: 与 R 第 3 列夹角 1.5e-06°, 与第 1 列 90°。别按注释去"修".
4. **Hopf 右逆的纤维生成元是体 z 轴**: `q = s(n)·quat_z(φ−φ_s)`, 截面 `s(n)` 把 **e₃** 转到 n。
   写 `quat_x` 会得 179° 误差(整条轨迹)。叉积顺序也必须是 `e₃×n=(−ny,nx,0)`, 反了转成 −n(误差≈180−0.3°)。
   叉积退化(‖n×e₃‖≈0)时不能直接返回单位四元数 —— 还要按 `acos(c)` 转。
   判据: 215 帧往返 max `2.4e-06°`。
5. **对账别用 arccos 角度**: `traj_hopf.json` 的 n 只存 6 位小数, `dot→1` 时 1e-6 舍入被放大成 0.06°
   的假红。判据看**分量最大差**(实测 5.0e-07), 角度只作参考。测地线判据同理: 只测 `0.5°<d<150°`
   的帧对(近对跖/近重合的中点不唯一, 会把 1e-8 放大成 1e-4)。

实测开销 `0.29 ms/拍`(100 拍 29.3 ms, 预算 100 ms); 真值帧龄 0.14 s 时 A/B/C/D/E 与真值逐项一致。

## 12. 五流形上引擎常驻 + 远端看板 (两个必踩的坑)

- **开启方式**: `systemctl edit` drop-in `Environment=ZMAX_SE3_LAYERS=1` → restart `zmax-ss-engine-loop`。
  `layer_calls.jsonl` 每 10 个引擎周期(1 Hz)多一条 `rec["se3"]`, `/dev/shm/se3_layers.json` 同步。
- 🔴 **E（相位）会钉在末帧 `s=0.9995`**: `snapshot(i=None)` 默认取最后一帧索引。接了实时位姿时必须用
  **TCP 投影到轨迹的最近帧**算 i (`nearest_i()`, 相位连续窗口), 否则 A/B/C/D 在动而 E 不动。
  实测改前整轮 E_s 恒 0.9995, 改后 0.3058→0.3190 随真机推进。
- 🔴 **另一台机看实时信号: 它没有珞石 SDK**。做法 = 在引擎侧的 8797 `GET /api/tcp` 上加
  `Environment=ZMAX_SE3_TRUTH_URL=http://<engine-host>:8797/api/tcp`, 本地 `latest.json` 帧龄>2s 才拉远端;
  远端回包归一成 `{x,y,z(m), qx..qw, joints(rad), ts}`。注意 `/api/tcp` 的 `quat` 已经是 `[qx,qy,qz,qw]`。
- 🔴 **最近点连续性窗口会让停回起点的臂报错帧**: 窗口赢过 2.3mm 的全局最近点时(自交 22 处),
  看板报 `#69 偏轨 2.3mm` 而真实是 `#214`。加一条前置规则: `min(d)≤3mm` 就直接取全局最近, 不走窗口。

## 13. 五流形 → flow matching: 条件编码 + 流形感知噪声 (接法已定, 提升未证)

状态向量的用途从"观测/闸门/看板"扩到"策略条件"时, 照这四条做 (`src/lerobot/manifold/se3_flow_cond.py`):

1. **条件向量 20 维** = A(p/1000,3) + B(n,3) + C(q,4, 统一 w≥0) + D(cosφ,sinφ,2) + E(cos2πs,sin2πs,2) + TQ(q̇/100,6)。
   S¹ 一律 (cos,sin): 裸角度在 0/2π 处跳变。四元数双覆盖必须把 w 统一到 ≥0, 否则同一个姿态两个编码。
2. **噪声不许是 N(0,I)**: 从当前状态出发在各自流形上采 —— B 切平面高斯再走测地线, C 右乘 exp(½σω),
   D/E 环上相加并 wrap, A 欧氏。实测欧氏直接加噪 B **100% 出球面**(范数均差 0.111), 流形采 0%(1e-16)。
   同理 FM 插值路径要在流形上做: C 的欧氏直线中点范数可低到 **0.0175**(姿态信息全丢), 测地线 1e-16。
3. **注入点用现成的头, 不新造**: `multi_task_dit:135 conditioning_vec = observation_encoder.encode(batch)`
   拼 20 维并把 `conditioning_dim += 20`; `smolvla:812 sample_actions(noise=...)` 直接吃流形噪声;
   L3 节点 `engineering/nodes/flow_matching_impl.py` 走的就是这两个头, 不用改。
4. **分开报账**: 只加条件向量 / 加流形噪声 / 换测地线插值路径 三步单独做同口径对照,
   有提升才进默认档(仅不回退只能留影子)。

🔴 **引擎 `geodesic("B")` 的 slerp 分支要先归一输入**: 轨迹 json 的 n 只有 6 位小数(`‖n‖=1±1e-7`),
不归一的中点范数偏 1.7e-7 —— 会被误判成插值实现错。

细节(维度表/σ 取值/实测对照/自检判据/门槛)见 `references/flow-matching-conditioning.md`。

## 14. E 相位↔状态 对账 (跑完一轮就能查, 判据三条)

`tools/check_phase_vs_state.py` 读跑批日志 + 8815 实况采样 + sectors, 输出三张表:
停留点相位 (参考 s vs 日志 s, 判据 Δs<1%) · 相位反查状态是否等于预期 · 实况 s 单调性。
判定口径: `静置抖动 |Δs|<0.003` 不算异常, `0.003~0.02` 算**可疑回退**(判据要求 0), `≤-0.02` 是自交换分支。

🔴 **停车/慢速时几何最近点会沿轨迹后退**: 实测 7 次 × 25~76 mm (i 回退 1~7 帧), 在夹爪/AOI 停留点前最明显。
两步治: ① 跑批期用 8797 `cursor` 锚定投影窗口 `[cursor-2, cursor+14]` (`ZMAX_SE3_STATUS_URL`);
② 再对索引做**单向钳制** `i = max(i, last_i)` —— 回放是单向的, 这条先验是对的。
实测效果: 换分支 14→1, 抖动/回退 7→0, s 全程 0.0000→0.9995 单调。

🔴 **`quats` 键名写错不报错, 只是静默降级**: 执行器只读 `cmd["quats"]` (`arm_step_traj.py:641`);
写成 `quats0` 时 flow v2 退回纯关节口径 —— 日志 `axis_dn_max/roll_dp_max` 全 0, 分块从 36 变 32、
整轮从 477.6s 变 464.2s。看到"轴/滚转两列全 0"先查这个键。

## 16. 新真源(239 点)接 L4→L3 / L2 时的四个必踩坑 (2026-11-21 实测)

1. **`…manifold` 相对导入深度错 = 条件通道静默变空**。`engineering/nodes/flow_matching_impl.py` 写
   `from ..manifold.se3_engine import SE3Engine` ⇒ 解析成 `lerobot.engineering.manifold`（不存在）⇒
   ImportError 被 `except` 吞掉 ⇒ `cond=None` ⇒ L3 永远拿不到 L4 条件，日志只剩一行“不出条件”。
   包内真身是 `lerobot.manifold.se3_engine`，正确写法 `from ...manifold.se3_engine import SE3Engine`。
   判据：`importlib.util.resolve_name('...manifold.se3_engine','lerobot.engineering.nodes')` 结果必须是
   `lerobot.manifold.se3_engine`。
2. **`/api/tcp` 没有 `rpy` 键**（只有 `quat` xyzw）——采真值时 `d.get("rpy") or [0,0,0]` 不报错,
   但 L2 action 的旋转 3 维恒为 0（看着有值其实是空）。必须由 quat 现算 rpy（与 Rz@Ry@Rx 同口径）。
3. **新轨迹 json 没有 `q`**：v2 只有 `p/rpy/j`，`SE3Layered` 读 `f["q"]` 直接 KeyError。
   用 `R = Rz@Ry@Rx` 把 rpy 转成四元数落一份 `*_v2q.json`（动作真源仍用原 v2，别改它）。
   口径核对：与 215 表在 ≤0.7mm 重合处的姿态差 ≤0.02°；差到 1~2° 的位置都是 3~6mm 采样差。
4. **`traj_phase_v2.json` 末帧 s 正好 = 1.0**，S¹ 要求 s∈[0,1) ⇒ `se3_layers.selftest()` 报
   `phase back_steps=1 / closure_err=1.0`。215 表当年用的是 0.9995（分母含收口段）。
   按同一口径重算：`s_i = cum_i / (cum_last + |p_last−p_0|)`，实测 E_s 0→0.99909、回退 0。

## 17. 单条平滑回放轨迹上, flow-matching 预测下一状态**打不过线性外推**

239 点真值 (711 样本 / 5 折 / 2000 epoch / XPU) 实测 A_mm 中位: **model 35.6 · persist 18.6 · linear 4.1**;
旋转 B_deg model 4.19 vs persist 0.95 vs linear 0.136。原因不是实现错, 是数据性质:
8mm 等弧长、100mm/s 匀速回放的下一拍位置≈线性外推, 而模型要学整条流形上的速度场,
样本少(单轨迹)+
测地线积分误差累积。⇒ 结论照铁律写: **进影子, 不进默认档**;
要提升必须喂“非平滑”真值 (接触段抖动/停走/夹爪事件), 这正是白天采集 (`--collect`) 的用途。

## 18. 拿真机图像训 L4 cond 投影: 三个坑 + 现成采集器 (2026-11-22)

1. **`zmax_live_215ep1_128` 的 `images/` 是空的**(0 个文件)。它有 state13/action4/9171 帧,
   但图像没导出来 ⇒ 策略前向跑不起 ⇒ 在那上面训 `l4_cond_proj` 只能得到随机投影。
   开训前先 `find <ds>/images -type f | wc -l`, 为 0 就别开跑。
2. **8791 的三个快照端点只有一个有图**: `/snapshot/arm.jpg` 是真图(1280×720, mean≈42, std≈32, ~75KB);
   `/snapshot/local.jpg` 与 `/snapshot/overlay_local.jpg` 当前是**黑图**(mean 6.0 / max 13 / std 1.2)。
   判据要用**亮度统计**，不能只看“HTTP 200 且文件存在”。
3. **采集器**: `tools/collect_live_dataset.py --secs 1800 --hz 5 [--keep-still]` (默认 cam=arm)。
   取图走 **MJPEG 流 `/arm.mjpg` 的最新帧**(后台线程持续收/主循环取 `reader.frame()`),
   不是逐次请求 `/snapshot/*.jpg` — 后者实测 2.00s/张 ⇒ 卡在 0.5Hz 且不报错; 改流后间隔中位
   **0.20s** (8s 收到 119 个不同帧 ≈15Hz 可用)。默认过滤静止帧(位移+50×转角<0.5), 要学
   “到位停住/夹爪保持”这类等待动作磀 `--keep-still` 全录 (写另一个出目录, 转换时再按
   “连续静止 >1.5s 只留首尾几帧”去重)。每帧同时抓 `/api/tcp` 真值 →
   `pose7(mm+rad)+joints6(deg)`, 落
   `zmax_data/live_ds/episode_00000N/{images/observation.images.top/frame_*.jpg, data/frames.jsonl}`;
   行式元数据逐行 `flush()` (否则进程一挂只剩没对齐的图)。
4. **昼夜自主进化** 在 550C: `zmax-se3-evolve.timer` 每 30 分钟, 白天(7–21)采真值+1 代轻量,
   夜间 4 代完整; 台账 `zmax_data/se3_evolve/ledger.jsonl`。实测 79 代 0 采纳 —— 超参变异改不了
   “平滑回放下一拍≈线性外推”这个事实, 要提升必须换数据而不是继续调参。
5. **cond 只在推理时注入 = 训不出来**: 训练脚本一次没传过 `l4_cond`(grep `src/lerobot/scripts/` 零命中),
   `l4_cond_proj` 用 `normal_(0, 0.02)` 随机初始化 ⇒ 条件只是噪声。测得的“cond 增益 +0.58%”是没训过的结果,
   不是条件无用。真要训必须先补图, 再在训练循环里逐样本算 `build_cond(15)` 当额外 token。

## 15. 跟随未知新轨迹: 学路径 + 相位语义 (8817)

8815 是**已知轨迹**看板(相位靠投影到那 215 点); 一旦换新轨迹, 8815 的 `s` 没意义, 只能当“离旧轨迹多远”参考。
跟新轨迹用 `tools/se3_follow.py` + systemd `zmax-se3-follow.service` (8817, 20 Hz, 只读 `/api/tcp`, 零下发)。

- **学习语义**: 位移 ≥2mm 记一个路径点(`A_mm/B/C/D/j/t`); 首尾≤30mm 且总长≥500mm ⇒ 闭环, E 从
  `learning`(学习进度 mm, **不报 s**) 切 `closed`(相位 s)。未闭环就报 s 等于编。
- **S¹ 要取模**: 闭环后继续走会 `s>1`(实测 1.8344)。`s=(cum % L)/L` + 单独给 `laps`。
- 🔴 **首尾重合 ≠ 闭环**: 从口里退出来一路开回起点, 首尾差 15mm、总长 1600mm ⇒ 旧规则直接判闭环并报 `s=0/圈1`,
  其实是**往返**。判别量 = 回程贴合度: 后半段每点到前半段折线最近距离的**中位** `<25mm ⇒ retrace`, 否则 `loop`。
  E 三态: `learning`(不报 s) / `retrace`(三角波 0→1→0, 标签写"非闭环") / `closed`(真环路, S¹ 取模)。
  监视/守望脚本只在 `shape=loop` 结闭环, 否则每次回原点都会被当成"跑完一轮"提前收工。
- 🔴 **真值断流期不许记点**: 控制器重启时 `latest.json` 还在但冻住(`age_s` 涨到几十秒), 照记就是拿冻住的位姿凑路径。
  `age_s>5s` 直接跳过并写 `err`; 恢复后按 **reanchor** 记一条 `gap_mm` 点, 不计入弧长、不计 `jumps`
  (重启期间臂可能被搬走, 那是断流不是跳变)。
- 🔴 **会话状态文件必须原子写 + 备份 + 加载回退**: `json.dump(open(path,'w'))` 在 `systemctl restart` 撞上写一半
  ⇒ 0 字节文件 ⇒ 重启后 load 失败, 已学路径(实测 161 点)整体清零。写法 `tmp→fsync→os.replace`, 同时刷 `.bak.json`,
  load 时主文件坏就退 `.bak`; 启动默认接上旧会话, 只有显式 `--fresh` 才清。
- 🔴 **真值源跳变必须丢**: 换源/单位错会把弧长算成 66 万 mm。单次跳变 >300mm(20Hz 下真机最快 ~50mm/次)
  不记入弧长, 记 `jumps`/`last_jump_mm` 并重锚 —— 否则整条路径长度都废了。
- **口径自检**: `--import tools/web/real_traj_joints.json` 应得 215 帧 `cum=7861.8mm`, 与 `traj_phase.json`
  的 `L_open` 逐位一致; 不一致就是弧长/单位算错。
- **验学习逻辑不占真机**: `tools/mock_truth_circle.py` 起假真值(8819, 圆 R=120mm ω=0.5rad/s), 跟 37s
  应得 2.94 圈、闭环 L 误差 -1.7%(2mm 采样弦差) —— 用理论值对账, 不是“看着像圆”。
- 留痕: `tools/se3_follow_watch.py` 每 5s 记 `/api/follow` 到 `zmax_data/se3_follow/progress_*.jsonl`,
  只在闭环/跳变/E 模式切换时打一行。
- 自建 HTTP 小服务(ThreadingHTTPServer)回包必须 `json.dumps`: 直接 `wfile.write(dict)` 抛
  `TypeError: a bytes-like object is required, not 'dict'`, 而 `Content-Length` 已被写成**键数**⇒ 每个请求一个 500、
  页面空白但 `ss -ltnp` 看着服务在。
- 页面 `/follow` 五视图(A 路径俯视+z 亮度 / B 球 / C θ 表盘 / D 滚转表盘 / E 相位环)验证方式:
  按 canvas 采样非背景像素数(实测 696/3459/7163/2043/9770) + 回读 DOM 数字与 `/api/tcp` 对账。
- 🔴 **同步改 /ar3d 页面才叫“也能看”**: 8797 页面每请求**热读** `tools/web/tcp-ar.html`, 改 HTML 不用重启;
  但页面里的 `syncArmFollow()` **从没人调**(`SYNCARM.follow=false`) —— 三维臂只显示不走, 而游标还挂着旧 215 点。
  做法: `body.vrfull` 时打开即 `syncArmFollow(true)` + `setInterval(2s)` 兜底重挂, 再拉 8817 的 `session.json`
  塞 `NAMED['follow']` 画青色新轨迹线, 并在左上 HUD 写 `跟随中/未跟随 · TCP mm · 真值帧龄`。
  判据不是“按钮发了”, 而是 `PREV.on==true` 且与 `/api/tcp` 关节 **maxdiff 0.000°**; 像素校验要数 `#vr` 画布
  (第一个 canvas 是 `#vid` 视频层, 数它会得到 0 而误判“画不出来”)。
- 🔴 **页面里的 `PREV/NAMED/SHOW/TRAJ` 是 `let` 声明, 不在 `window` 上**: 写 `window.PREV && PREV.on` 永远是 false,
  会把“正在跟随”报成“未跟随”。追加脚本里直接引用同名变量, 别走 window。

## 改动画布时
六断言 + `_archive` 备份 + 剔除新增后逐条比对，见 `state-space-canvas-engineering`。
本链做到“零画布改动”是因为 `n_vlm_llm → ss_mani_eng in1` 这条线本来就有，只是代码不读它。
