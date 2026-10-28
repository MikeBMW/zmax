# detect_3d 断点排查三因 + YOLO 旁路真相 + R0 真实化 (2026-09-04 会话记录)

本文件是 SKILL.md "▶运行/单步/右键 执行语义" 节的 2026-09-04 深化。
(注: 后台 curator 无法 patch 本技能 SKILL.md — read-before-write 机制与 view dedup 冲突,
故追加在此。前台会话可把以下三节合并进 SKILL.md。)

## ⚠️ "detect_3d 断点进不去" 排查三因 (第三次踩同坑)
链路: ▶运行 → 引擎 sim.run() 500 步 (每步走 _build_obs→fuse_sensors 等**引擎源码**)
→ 跑完才 simulink_module.py:10373 `_real_yolo_sense_once()` → detect_3d **只调一次**。
1. **引擎内部源码断点挡路 (最高频)**: 断点放 perception.py fuse_sensors / parallel.py
   predict 等引擎主循环源码 → 每步命中, 需 500 次 F5 放行才轮到 detect_3d, 表现为
   "进不了 yolo"。09-01/09-02/09-04 已三次 (parallel.py:60 / perception.py:33/34)。
   解法: 点掉引擎内部断点; 或断点设在 10373 `_real_yolo_sense_once()` 调用行
   (引擎跑完必停), 再 F11 进 detect_3d。怀疑假卡死先 py-spy 查 do_wait_suspend。
2. **画布无 ss_yolo 节点**: _real_yolo_sense_once 6139 行找不到节点 → **原静默 return**
   (诊断黑洞, 已加显式日志 "⚠️ ▶运行: 当前画布无「🎯 YOLO 目标检测」节点")。
3. **断点打在死代码/展示层**: 右键源码走 _EXTERNAL_LOC 映射 — 若映射指旧实现则永不命中。
   实例: 「📐 2D→3D 解算」_EXTERNAL_LOC["yolo_align"] 原指 pixel_to_ray(yolo_state_aligner.py:11)
   — 2026-08-23 改 cam_mat0 矩阵反投影后成**死代码** (全仓库零执行调用, 只剩源码映射展示),
   真实反投影在 detect_3d 103-125 行 (rot90 坐标还原 W-u/H-v → cam_mat0.T@pc 世界方向 →
   深度优先 / 预先固定 z 平面回退)。已改映射 → def detect_3d(53行)。铁律: 源码映射必须指真实
   执行符号。断点打 104-110(循环内)还需该帧 YOLO 检出框 (boxes 非空)。
- 排查手法: 改代码/映射后必重启 studio.py; GUI 日志区 ①"🧮 状态空间真实仿真…"
  ②"🎯 YOLO 目标检测 (真实): n/3" ③"⚠️ ▶运行: 当前画布无…" 三条定位到分叉点。

## 🎯 YOLO 真实感知 = 旁路证据, 不进闭环 (架构真相)
老倪深挖 "融合怎么按 YOLO 的 1 帧结果继续算?" — 诚实答案: **融合/前馈没有吃 YOLO 结果**:
- 引擎侧 (state_space_sim.py / perception.py / state_space/) 对 _YOLO_CACHE **零引用**;
  引擎 500 步的 43D obs = _build_obs 世界状态直读 (self.x/v/peg/HOLE_POS 拼 visual39,
  fuse_sensors 只做 39+4 拼接), conf 标 "--"(引擎无 YOLO 模型, 不伪装)。
- YOLO 那 1 帧 (metaworld reset(seed0)+render 一次, det3d/det2d/obs39/img 进缓存) 消费点
  全是展示/调试: 播放演示 _demo_node_output (node_logic 124行)、📐2D→3D 单节点 align
  (1441 取缓存)、AOI 检测 (2384)。→ **两条平行链只有展示层相交**: 引擎闭环链
  (训练/3D/播放/总线, obs=上帝视角真值 — 仿真阶段合理) 与 YOLO 感知链 (metaworld 帧→
  YOLO→3D→39D→43D, 独立验证真机同构链路能验证通过的证据采样)。
- "1 帧够不够/稳不稳" 不影响闭环正确性, 只影响展示证据置信度。真闭环 = R0/R1 真实化。

## 🔄 闭环真实化 R0 (方案2 落地)
老倪拍板: 引擎世界换 metaworld + YOLO 每 N 步喂 obs。设计: docs/closed_loop_realization_design.md。
- **R0 物理真实化** (tools/gui/state_space_sim_real.py, 已提交 109e6a68): 六层控制器源码
  importlib 直载 (同引擎), 指令→env.step 真实物理, 感知真值直读。**单轮全流程验证通过**
  (seed100: 接近→对位→下降→抓取 grp0.41 锁存→抬起 gf=1 真夹持→转移→插入 cp0.93→完成)。
- **R1 感知真实化** (YOLO 喂 obs) 未做 — 决策点 D2(前馈解析律 vs 引擎 MLP 语义错位)、
  D3(感知刷新 N) 待老倪拍板。
- 复用六层 + 关键改动: 前馈显式解析律 (不挂引擎训练 MLP); 每轮现场采样几何存 self.geom;
  每轮新建 ActionModulator (grasp_th=0.28/lift_h=0.08/max_veto=5); est/dyn B=0.02;
  夹持=抓取阶段 grp<0.78 连续3步锁存 → 抬起 peg 随动验证 (gf), 滑脱交调度器夹持丢失回退;
  env.step 包 try/except ValueError (truncate 500 步上限)。
- **遗留**: 多轮 0/8 — 8 seed 轨迹全同 (metaworld seed 冻结语义疑点: reset(seed) 后布局
  未随 seed 变) + 控制器对当轮布局敏感 (抬起段夹持丢失回退循环); GUI 接入未做。
  探针12 流程是抓取金标准 (悬停 z=销+8cm 对准→垂直降被销顶住→闭合 20-30 步→抬升 act 0.5)。
- 12 发探针全部保留: tools/probes_real/probe_mw_real*.py (标定工具)。

## 🔴 「断点不进函数体 / 进了却不停」的三因 (2026-10-17, 与上面三条互补)

问的是**具体某一行**(如 `return self._ff(obs)`), 且代码看着没问题。按序分离, 每步都有便宜证据:

1. **那行根本没执行** — 方法被**实例属性**整体覆盖掉了:
   `self.accel.forward = self.accel.analytic_forward` (门是 `SS_USE_MLP != "1"`) ⇒ `FeedforwardAccelerator.forward`
   的方法体对那个对象是死代码, 断点放哪都不停 (与上面第 3 条同类: 死代码不属于"跑得到"的范围)。
   证据: `print(obj.forward.__qualname__)` · `tr '\0' '\n' < /proc/<pid>/environ | grep SS_USE_MLP`。
   同类: `PURE=False` 只直通的薄壳、feature flag 的早退分支。
2. **跑这段的是另一个进程** — 常驻引擎 (`ss_engine_loop.py run --hz 10`) 是独立 pid, cmdline 里**没有 pydevd**;
   在 studio 的 F5 会话里设的断点对它零作用。证据: `pgrep -af "debugpy|pydevd"` + 目标 pid 的 cmdline,
   再 `ps -o lstart= -p <pid>` 比文件 mtime。修法: `debugpy --listen 127.0.0.1:5678 --pid <引擎pid>` 或改在 studio 进程内跑。
3. **模块是动态加载的, debugpy 解析不到** — `importlib.util.spec_from_file_location(...)` + `exec_module()`
   **不把模块放进 `sys.modules`** ⇒ 函数真在跑、VSCode 不停 (本仓已多次中招)。

断点友好的加载器 (每次按路径加载都要用; 仓库里**每个** `_load()` 都要改, 只改一个文件另一条路照旧不停):

```python
import sys, types
src = open(path, encoding="utf-8").read()
m = types.ModuleType(mod_name)
m.__file__, m.__name__ = os.path.abspath(path), mod_name
sys.modules[mod_name] = m
exec(compile(src, m.__file__, "exec"), m.__dict__)      # co_filename = 真实绝对路径
```

失败再退回 spec 加载并打一行提示 (不静默改变语义)。加载完自证:
`m.__name__ in sys.modules` · `cls.method.__code__.co_filename == os.path.abspath(path)`。
`state_space_sim_real._load` 早已是这个写法, `state_space_sim._load` 直到 2026-10-17 才补齐 ——
**看到同类 `spec_from_file_location` 就顺手对齐**, 别等下次再问一遍。

调试器无关的保障 (断点绑定失败也能拿到"到底跑了没"):

```python
if os.environ.get("SS_FF_BREAK") == "1":
    try:
        import debugpy
        if debugpy.is_client_connected():
            debugpy.breakpoint()
    except Exception:
        pass
if self.n_calls % 100 == 1:
    print(f"🧠 前馈加速器: MLP 真身执行 #{self.n_calls} (域内 {self.n_mlp} · 守卫 {self.n_guard}) · loaded={self.loaded}", flush=True)
```

判读: 这行 `真身执行 #N` **不出现 = 路径没跑**(去查开关/装配), **出现但断点不停 = 绑定问题**(查进程/加载器)。
交付口径: 先把这三条按序报给用户并给命令, 再说"改了什么"; 控制台/引擎重启只给命令, 不自己重启。
