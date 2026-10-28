---
name: robot-sim-mujoco-rendering
description: Use when mujoco/metaworld 仿真进程内多轮/多线程 env 渲染黑帧或做来料干扰鲁棒性测试.
---

# mujoco/metaworld 进程内渲染线程亲和 + env 生命周期 + 摆放干扰注入

Z-MAX 真实化引擎 (state_space_sim_real.py, R0/R1) 多轮调试沉淀。metaworld/gymnasium-mujoco 通用。

## 1. 渲染器绑定创建线程 (黑帧根因, 2026-09-09 实锤)

mujoco renderer 的 GL/EGL 上下文**绑定第一次创建它的线程**。GUI 每轮真实化若新建 worker
线程跑复用 env → 从第二轮起渲染黑帧 → YOLO 0% 检出 → 视觉全瞎 → 手飞 9.9m (特征距离!)。

- 探针验证: 同 env 线程 A 跑 100% 检出 → 线程 B 跑 0% (glfw/egl 都如此); 同线程两次都 100%。
- **修复**: 全部真实化任务提交到进程级单线程池 `ThreadPoolExecutor(max_workers=1)` —
  首个建 env 的线程 = 永远渲染线程。abort/join 语义不变 (future.done() 轮询替代 is_alive)。
- 防重入: submit 前检查旧 future 未 done 则拒绝 (单线程池排队会交错写结果)。
- 不要用"每轮新建 env"心智 —— 见下。

## 2. env 是进程级单例, 永远不要 close

`_make_env()` 返回模块级 `_ENV` 单例, 跨轮 `reset(seed)` 复用 (metaworld 官方语义)。
**close 单例 → 下轮复用已关 env → 渲染黑 → YOLO 0%** (自引入回归实锤, 表现为"重启 GUI 后
第一轮好、第二轮坏")。run 结束/异常都别 close; mujoco 资源随进程退出释放。

## 3. metaworld reset(seed) 忽略 seed

sawyer_xyz_env 的 reset(seed=) 参数被忽略, 布局由**全局 np.random** 决定 →
同 seed 在不同用例序列后布局漂移 (测试顺序耦合)。修复: reset 前 `np.random.seed(seed*7919+13)`
再 reset, reset 后 `_freeze_rand_vec=True` → 同 seed 恒同布局 (可复现, 非造假)。

## 4. 摆放干扰注入 (来料移位/转向鲁棒性测试)

peg 是 **free body** (qpos 7 维: 平移3+四元数4)。找它: 遍历 body 名 `"peg"` →
`body_jntadr[body_id]` → `jnt_qposadr`。**joint 名未必含 "peg"**, 别按 joint 名搜。
注入: qpos 平移 += Δxy(±4cm)/Δz + 四元数绕竖轴 yaw; 然后 `mujoco.mj_forward(model, data)`
→ 之后**现场几何/obs 全部重读** (决策链靠现场几何自恢复, 不预先固定常量)。
注入时机: env.reset 后、obs/geom 采样前。可控复现: 引擎加 `_jitter_override` dict 供回归矩阵。

**钉/搬运一个 free body: 设 qpos 必须同时清 qvel** (否则速度继续累积, 每步掉 ~9.81×ctrl_dt):
```python
jid = m.body_jntadr[m.body(name).id]
d.qpos[m.jnt_qposadr[jid]:+3] = pos          # 必要时再写 :+7 四元数
d.qvel[m.jnt_dofadr[jid]:+6] = 0.0           # 漏这行 ⇒ 钉 0.35 读到 0.343, 且逐帧越掉越深
mujoco.mj_forward(m, d)
```
漏清 qvel 的典型症状: 被"刚性夹持/吸附"的件读数持续低于指令位姿, 抬起段目标一旦锚在活件上就飞车 (见 §9)。

## 5. 死局早停判据必须排除夹持转移段

"peg 漂移 >10cm → 布局死局换重试" 只在 **未夹持** 时判定 (抓起 peg 转移去孔位, peg 离初始
>10cm 是**正常**的; 不排除会误杀成功轮)。判据加 `not grasped`。

## 6. 干扰鲁棒性 = 多布局 attempts (来料重摆语义)

单次布局成功率非 100% (peg 被碰移成"冰球"死循环是典型失败模式) → 失败换新随机干扰布局
重试 ≤5 次直到任务完成 (真实工厂来料重摆语义)。每次 attempt 前 `_jitter_round += 1` 得新布局。

## 7. 模型部署 state_dict 必须架构一致

旁路模型 (如 WorldModelPredictor) 训练时 hidden_dim/num_layers 若与默认不同, 引擎实例化
必须显式传同一架构, 否则 `load_state_dict` 报 Unexpected key → 静默回退随机权重。
日志里 "predictor 注入失败: Unexpected key(s)" 即此。

## 8. 出片机位: env.render() 的相机在构造时锁死, 想换要自己建 Renderer

- `env.render()` 的相机 = **构造 env 时的 camera_name**, 之后设 `env.camera_name=...` 或传
  `render(camera_name=...)` **都无效** (gymnasium 的 `MujocoEnv.render()` 不接受任何参数 →
  `TypeError: unexpected keyword argument 'camera_name'`); 逐个相机试出来像素**逐位相同**即此症状。
- 分辨率受模型的离屏缓冲限制 (metaworld 默认 `vis.global_.offwidth/offheight = 480`):
  直接开 960×720 会 `ValueError: Image width 960 > framebuffer width 480`。
  **先放大缓冲再建渲染器**:
```python
m.vis.global_.offwidth, m.vis.global_.offheight = 960, 720
ren = mujoco.Renderer(m, height=720, width=960)
cam = mujoco.MjvCamera(); mujoco.mjv_defaultCamera(cam)
cam.lookat[:] = (0, 0.56, 0.02); cam.distance = 0.92; cam.azimuth = 90.0
cam.elevation = -89.5          # 见下
ren.update_scene(d, camera=cam); frame = ren.render()
```
- **elevation 选角要按遮挡算**: 斜视 (-78°) 时深盘/深槽的壁会把里面的件挡掉 (实测末帧金色
  像素 0~8); 近正俯视 (-89.5°) 才看得见, 件像素可差 20 倍以上。
- **腔体内件必须自己验可见性, 不能凭"我传了相机"就信**: 消融法 —— 把目标件移到视野外
  (如 z=-5) 渲一帧, 与正常帧求差, 变化区的 bbox/像素数就是该件在画面里的真实占位
  (件宽 52mm、视距 0.92m 时约 950px/颗)。数字太小 ⇒ 画面拍了等于没拍。

## 9. 仿真控制三坑 (都是"判据全错但不报错"类)

1. **目标不能锚在活件上**: 若 target = 活件当前位姿 + 偏置, 而活件又被钉在工具上, 目标会随件
   自抬升 ⇒ 正反馈飞车 (手飞到台面外)。抓/吸成功那一刻把目标锚定 (`top0 = 当前件顶面`),
   之后的抬起/转移/下放全部相对锚点算。
2. **先验几何可行性, 再看控制**: 控制链路全绿却放不进去时, 先量**间隙** (槽位开口 vs 件外形)。
   实测: 隔板 20mm 厚 + 节距 30mm ⇒ 开口 10~15mm < 件宽 20mm, 件物理上放不进去, 只能骑在
   隔板棱上 (落座高 +3.6mm、单边偏 2.5mm) —— 看着像"控制精度不够", 实际是几何不可行。
   夹具/槽位的尺寸与节距必须在唯一依据里对得上, 仿真与 3D 视图同源改一次即同步。
3. **释放时机决定横向残差**: 距落座 6mm 就断真空/开爪 ⇒ 件自由落体时横向漂 2.2mm 撞壁;
   收到 1.5mm 内再放, 残差 ≤0.5mm。判据要按工艺配方定 (单边 ≤1mm / 姿态 ≤1°), 别自己放宽。

## 10. 动作不以「速度」身份进 MuJoCo — 只写 mocap 目标, dt 口径必须先量

被问「引擎/前馈的速度是直接进 mujoco 么」时, 先看清写入目标 —— 答案通常是否:

- metaworld `set_xyz_action` 只做 `data.mocap_pos += act × action_scale`（目标点), 再靠 mocap weld + 关节执行器 `mj_step` 驱臂。**qvel 由 MuJoCo 动力学算, 不从外部写**。要判「速度语义准不准」只能量每步稳态位移, 不能看代码推算。
- 一个 `env.step` 的真实物理时长 = `frame_skip × model.opt.timestep`（metaworld 常见 5×0.0025=**12.5ms**, 不是 20ms 也不是 0.1s)。任何 `K_ACT = act/m·s⁻¹` 类的标定都隐含一个 dt; dt 算错就整体偏倍。实测: 名义 0.5 的 K_ACT（隐含 20ms）在 12.5ms 步下中小段实际 **1.6×** 指令, act 到顶时因臂饱和回落到 ~1.07×。
- 引擎侧还有个独立的 `DT_ENV` 常量常与真实步长差数量级 (实测 0.1s vs 12.5ms) ⇒ 凡折速度/步数预算的地方都偏, 必须跟 `frame_skip×timestep` 对齐后再用。
- 解析仿真路（无 mujoco, `v ← v+(u−v)dt/τ; x += v·dt`) 与真物理路的「速度」语义不同源, 对比两路数据前先声明用哪一条。

口径表/两路链路/改法见 `references/action-to-physics-mapping.md`; 量它用 `scripts/probe_action_mapping.py`（一条命令打 action_scale/frame_skip/timestep + 各 act 的稳态位移与真实速度）。

## 关联

- 肌肉记忆标杆必须绑定摆放指纹 (布局变则失效关快通道) — 见 user-owned zmax-muscle-memory 坑 8。
- 诊断/回归纪律: CLI 多轮测试前 `SS_MUSCLE=0` 隔离固化库, 否则假回归。
