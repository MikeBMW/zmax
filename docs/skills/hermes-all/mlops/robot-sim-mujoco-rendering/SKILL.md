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
→ 之后**现场几何/obs 全部重读** (决策链靠现场几何自恢复, 不写死常量)。
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
   夹具/槽位的尺寸与节距必须在真源里对得上, 仿真与 3D 视图同源改一次即同步。
3. **释放时机决定横向残差**: 距落座 6mm 就断真空/开爪 ⇒ 件自由落体时横向漂 2.2mm 撞壁;
   收到 1.5mm 内再放, 残差 ≤0.5mm。判据要按工艺配方定 (单边 ≤1mm / 姿态 ≤1°), 别自己放宽。

## 10. 动作不以「速度」身份进 MuJoCo — 只写 mocap 目标, dt 口径必须先量

被问「引擎/前馈的速度是直接进 mujoco 么」时, 先看清写入目标 —— 答案通常是否:

- metaworld `set_xyz_action` 只做 `data.mocap_pos += act × action_scale`（目标点), 再靠 mocap weld + 关节执行器 `mj_step` 驱臂。**qvel 由 MuJoCo 动力学算, 不从外部写**。要判「速度语义准不准」只能量每步稳态位移, 不能看代码推算。
- 一个 `env.step` 的真实物理时长 = `frame_skip × model.opt.timestep`（metaworld 常见 5×0.0025=**12.5ms**, 不是 20ms 也不是 0.1s)。任何 `K_ACT = act/m·s⁻¹` 类的标定都隐含一个 dt; dt 算错就整体偏倍。实测: 名义 0.5 的 K_ACT（隐含 20ms）在 12.5ms 步下中小段实际 **1.6×** 指令, act 到顶时因臂饱和回落到 ~1.07×。
- 引擎侧还有个独立的 `DT_ENV` 常量常与真实步长差数量级 (实测 0.1s vs 12.5ms) ⇒ 凡折速度/步数预算的地方都偏, 必须跟 `frame_skip×timestep` 对齐后再用。
- 解析仿真路（无 mujoco, `v ← v+(u−v)dt/τ; x += v·dt`) 与真物理路的「速度」语义不同源, 对比两路数据前先声明用哪一条。

口径表/两路链路/改法见 `references/action-to-physics-mapping.md`; 量它用 `scripts/probe_action_mapping.py`（一条命令打 action_scale/frame_skip/timestep + 各 act 的稳态位移与真实速度）。

## 无头环境渲染: 必须 `MUJOCO_GL=osmesa`

headless Linux 上 `mujoco.Renderer` 报 `an OpenGL platform library has not been loaded into this process`。三后端实测：

| MUJOCO_GL | 结果 |
|---|---|
| `egl` | `glCheckError` → `EGLError`（无 GPU EGL 时不可用）|
| `glfw` | `AttributeError: 'Renderer' object has no attribute '_mjr_context'` |
| `osmesa` | ✅ 软件渲染正常出图 |

⇒ 无头/远程一律 `MUJOCO_GL=osmesa`。代价：960×720 约 0.3~0.5s/帧，批量造数据集可接受。

## 真源箱体里的「结构件包围盒」不能当实体画

从配置/真源读的箱体元素里，**结构参照件**（横梁/相机支架/设备外框）的包围盒往往跨越整个工位。按 p1/p2 直接画实心 box ⇒ 正俯视时把下面全盖死，表现是「目标明明在画面里却 0 像素」。实测：`长方体-上横梁` 200×1600×18mm（1.6m 长）一条梁盖死整张台面。

对策：名字含 `横梁 / 相机 / 检测设备` 的结构件**只用来定台面范围，不进 worldbody**。
同理**料盘要画「薄底 + 四壁」，不能画实心盒** —— 实测料盘 z=100~140mm 的实心盒把槽（z=110~125）和坐在 130mm 的模块整个包住，目标色像素归零。

## 可见性必做消融法（区分「没画出来」vs「被挡住了」）

只看「传了相机、图不黑」不够。标准动作：把目标 geom 移到 `[0,0,-5]` 再渲一帧，与正常帧求差。差 = 0 ⇒ **拍了等于没拍**。

排查 0 差异的顺序（实测有效）：
1. 确认 `model.geom_pos[gid]` 赋值生效（`mj_forward` 后 `data.geom_xpos` 应跟着变）
2. **只留目标**：其余 geom `geom_rgba[:,3]=0`、目标 `=1` 单独渲一次 —— 单独能出像素 ⇒ 机位没问题、是遮挡；单独也 0 ⇒ 位置/机位错
3. 逐个单独渲染其他 geom，看谁盖住目标的屏幕坐标 → 直接点名遮挡者

## 渲染图天然带真值：颜色分割自动标注

仿真渲染最大红利是不用人标。目标用独特颜色（如 `0.94 0.76 0.22`），按 `R 高 / B 低` 阈值 + 连通域外接框 ⇒ **像素级真值标注**，直接产 YOLO 格式。
盲区：目标被遮挡时分割为空 ⇒ 空图标签留空并单独计数，**不要拿空图配「有目标」标签**。

实测：300 张渲染自动标注 → yolov8n 60 epoch（2.6min/4060）→ 换 seed 重生 60 张**未见机位** holdout，召回 100%、置信度 0.871~0.969、框位误差 1~2px。
注意「同集验证 mAP50 0.995」不算泛化指标，必须另出 holdout 才报数。

## 🔴 静态场景 ≠ 闭环能力：渲染+检测只支撑感知层

用真源箱体拼出来的 MuJoCo 场景（只有 `<geom>`）能**渲染 + 跑检测**，但**支撑不了任何一层需要
「动作→状态→下一帧」的能力**。问「这套场景所有层模型跑通了么」时必须把两件事拆开报：

| 需要什么 | 静态场景 | 要补什么 |
|---|---|---|
| 渲染出图 | ✅ 有 geom 就够 | — |
| 2D/3D 感知 (L2) | ✅ 渲图→YOLO | — |
| 动作→位姿变化 (L3/L4 闭环) | ❌ 臂是静止 capsule | `<joint>` + `<actuator>` + `mj_step` |
| 状态回读 (TCP 位姿/关节角) | ❌ 无真值通道 | `data.xpos`/`site_xpos` 取 TCP |
| 策略训练数据 (观测,动作) 对 | ❌ 臂不动采不出对 | 上面两条都完成 |

铁律：**没 actuator / 没 step / 没状态输出就不得声称场景支持全层**。
正确的分层报法：`L2 已在本场景真跑 (检出 conf/框位) · L3/L4/L5 仍在原 metaworld 场景，
本场景要接进去还差 ①双臂 MJCF 关节+actuator ②env 适配器 (reset/step/render/state) ③重采数据`。

## 从「静态场景」补到「带动力学 env」的四组必踩坑（实测已打通）

上面那张表里的缺口是可以补的（`tools/ar_mujoco_env.py` 已做到：动作→位姿→下一帧闭环、四层全跑）。
补的时候踩到的坑比渲染坑更隐蔽，因为**它们都不报错**：

### 1. `<joint range>` / `<position ctrlrange>` 单位是**度**，不是弧度 🔴

写 `range="-3.0 3.0"` 想表达 ±3 rad，mujoco 解成 ±3°，`jnt_range` 读回 `[-0.0524, 0.0524]`。
现象：`data.ctrl` 设 1.4，`mj_step` 跑 500 步 `qpos` 只转 0.063 rad —— 极像「actuator 没接上」或「kp 太小」，
容易白调半天增益。

```xml
<joint name="j1" type="hinge" range="-170 170"/>              <!-- ✅ 度 -->
<position joint="j1" kp="60" kv="6" ctrlrange="-170 170"/>    <!-- ✅ 度 -->
```

`<slide range>` 例外（米）。`data.ctrl`/`data.qpos` 内部一律弧度/米。
判别口诀：**500 步动得极少 ⇒ 先 print `m.jnt_range[jid]` 看是不是被解成 ±0.05。**

### 2. freejoint 刚体的位置在 `body_pos`，不在 `geom_pos`

freejoint body 的 `geom_pos` 是相对 body 的 `[0,0,0]`，拿它当世界坐标会把件扔到原点（渲图 0 目标色像素）。
静态取值用 `model.body_pos[bid]`；运行中真实位姿在 `data.qpos[jnt_qposadr:+3]`（见 §4）。

### 3. 臂「够不到」是几何问题，不是控制问题 —— 先算再调

初始 `ctrl=0` ⇒ 臂竖直朝上（TCP z 比料盘高 0.7m 以上），与料盘相距 > 臂展 ⇒ 永远进不了「接近」阶段，
下游视觉估值恒为 None、距离全是 9.9 哨兵。零位臂一定要在 `reset()` 里主动设成**前伸探身姿态**
（直接写 `qpos` + `ctrl`，别等 actuator 自己收敛）。
基座摆放两条算术：① 到目标的水平距要在臂展的**弯肘舒适区**（约 0.25~0.45m）；
② 方位角 `atan2(dy, dx)` 要落进 j0 的搜索范围（j0 扫 ±0.6 rad 永远搜不到 152° 的基座朝向）。

### 4. env 适配 metaworld 接口：具名对象 + obs 索引语义 + 跨域模型

runtime 只认具名对象和固定索引，缺一个就 KeyError 四档全挂，静默错配则不报错但数字全错：

- **具名对象**：`endEffector` / `pegHead` / `hole` / `goal`（site）+ `box`（body）。建场景时一次补齐。
- **obs 索引按 metaworld 语义**：`o[0:3]` hand、`o[3]` 夹爪标量、`o[4:7]` 目标件位置、`o[36:39]` 孔位。
  把旋转矩阵/其他量塞进 4:7 ⇒ 距离算出 9.9m 鬼值。
- **类别名要映射成调用方读的中文键**：模型类 `gold_module`，runtime 读 `det3d.get("光模块")`；不映射则「检出了也不采信」。
- **跨域模型必须禁**：在 A 场景训的深度回归器拿去推 B 场景渲图会瞎猜（实测 z=-0.8，台面下 0.8m），
  于是每帧触发"幽灵件"判据、视觉估值恒 None。换场景时**主动关掉深度模型，走几何/常量 z 兜底**。
- **兜底常量也是场景相关的**：z 兜底写成训练场景口径（光模块 0.03）套到新工位（0.112）差 8cm，
  同样每帧触发幽灵判据。用环境变量按场景注入（`SS_ZMAP_*`），别硬编码。

验收顺序（每步都能把问题缩到一个变量）：
`渲染消融差 >500px` → `YOLO 检出非零` → `det3d 的 x/y 接近真值` → `z 接近真值` →
`视觉估值落进 `_vis`/`_peg_cur`（不再是 None）` → `距离是真实值不是哨兵` → `多档终点毫米级`。
哪一步第一次出现 None/哨兵，就在那一步往上一层查。

🔴 **“视觉已采信、距离却还是哨兵”的第一嫌疑：`getattr(obj, "k", fallback)` 在属性“存在但为 None”时不回落**。
运行时写的是 `pg = getattr(self, "_peg_cur", self.geom["peg_grasp"])`，而 `_peg_cur` 是**一开始就初始化成 None 的成员**
⇒ getattr 拿到 None，fallback 永远用不上，下游恒返 `9.9` 哨兵。现象是 `_vis["peg"]` 已经有值、检出也 6/6，
距离却一字不变 —— 非常像视觉链路没通，容易往错的方向查半天。
判别：把 `_vis` / `_peg_cur` / `geom[...]` **三个一起打印**（都有值却用不上 ⇒ 就是它）；
修法是调用处改 `getattr(...) or fallback` 或显式 `if x is None`，**不要去改视觉层**。

## 关联

- 肌肉记忆标杆必须绑定摆放指纹 (布局变则失效关快通道) — 见 user-owned zmax-muscle-memory 坑 8。
- 诊断/回归纪律: CLI 多轮测试前 `SS_MUSCLE=0` 隔离固化库, 否则假回归。
