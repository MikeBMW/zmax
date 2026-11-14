---
name: skill-constraint-corridor
description: "Use when 原子技能要按3D坐标+节拍约束在几何通道内并画进AR。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [robotics, constraints, corridor, zmax, ar, gui, skill-layer]
    related_skills: [zmax-ar-traj-8797, state-space-canvas-engineering, layered-capability-stack]
---

# 原子技能的 3D 约束通道 (corridor)

## When to Use
- 用户说「根据 3D 坐标 + 动作状态 + 节拍, 把每个原子动作约束在有效通道之内」—— 而不是只要速度/加速度上限。
- 要把约束边界画进 AR/三维场景, 或要在左侧面板逐段检查每个技能的约束。
- 已有 ①②③⑤ 标量闸 (`physics_constraints`) 但仍出现"偏到孔外 3mm 会怎样"这类几何问题。

## 核心口径: 标量上限回答不了几何偏离

五条闸 (速度/加速度/加加速度/动量/位移) 都是**标量上限**, 每拍把 `u` 等比缩小、方向不变。
等比缩**只减速不回中** ⇒ 偏差永久留在管外。通道层补的就是"偏了多少、要往哪回"。

| 量 | 怎么来 | 注意 |
|---|---|---|
| 轴 `axis` | `a`→`b` 两点真 3D 坐标 (`trace_live.json` 的 `末端`/`光模块`, 与 AR 场景同源) | 单位统一 mm/m; 零长度段要有竖直兜底 |
| 半径 `r_mm` | **全部段统一 10.0mm** = 末端执行器可通行通道半径 (老倪定的口径, 1cm) | 半径只在两份表里: `tools/ss_corridor_build.py` 的 `R_MM`(建通道/画 AR) 与 `state_space/corridor.py` 的 `DEFAULT_R_MM`(无真源时的回退) —— **改半径两处一起改 + 重跑 builder**, 只改一处会出现"代码 10mm、页面 25mm"; 要分段收紧写 `config/calib/zmax_corridor.json` 由 `ZMAX_CORRIDOR_CALIB` 指过去, 别改代码 |
| 节拍预算 | `v_along_cap = min(v_cap, L/tact_s)`, `s_tick = min(s_step, L/ticks)`, `ticks=max(1,tact_s/dt)` | 这是"UPH 节拍参与约束"的**唯一正确落点**, 别把节拍只当显示数字 |
| 越界处理 | 向外速度**归零** + 补回中速度; 轴向超 `L` 时轴向归零 | 不是等比缩! 等比缩等于没回中 |
| 无坐标 | 返回 `None` **跳过**, 界面显"无 3D 坐标" | 坐标过期 (帧龄 > 30~60s) 一律当没有, **绝不编坐标** |

## 接线: 实现一份, 调用在每个技能

- **实现只有一份** (`AtomicSkill.corridor_finish()`), 但**调用点是每个技能的 `clamp()` 末尾**:
  `return self.corridor_finish(_out)` —— 这样断点能落在具体某个技能上, 栈里看得见是哪一段。
  九份**实现副本**才是灾难; 一行调用不是。
- `cognition.skill_step()` 只在技能返回值没带 `corridor` 字段时兜底投影一次 —— 不许两处都投
  (回中会被算两遍, 且断点永远只停在 cognition)。
- 开关 `ZMAX_CORRIDOR=0` ⇒ 原样放行, `u` 逐位不变。改完必跑 A/B: 段序列与拍数必须完全一致 (通道只改幅度不改编排)。
- 判据 (不跑就是"只画了条线"): 造一个「轴外 3r + 向外 0.3 m/s」的动作丢进投影函数, 断言
  削因含 `横向切外 + 回中` 且 `step_mm <= s_tick_mm`; 关闸时输出与输入逐位相同。

## 🔴 引擎把 state_space 下的模块当顶层模块加载 ⇒ 相对 import 全瞎

在 `state_space/cognition.py` 里写 `from . import corridor` 会报
`ModuleNotFoundError: No module named 'ss_real'` —— 因为引擎用 importlib 按文件路径加载六层控制器,
父包名是 `ss_real` 而不是 `state_space`; 同一个坑会让 `skills/__init__.py` 的副作用 import 一起炸。

```python
import importlib.util as ilu, os, sys
m = sys.modules.get("zmax_skill_corridor")
if m is None:
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "corridor.py")
    spec = ilu.spec_from_file_location("zmax_skill_corridor", p)   # 固定模块名
    m = ilu.module_from_spec(spec); sys.modules["zmax_skill_corridor"] = m
    spec.loader.exec_module(m)
```

GUI 页/构建工具用**同一个模块名**复用缓存 ⇒ "技能过闸"与"面板显示"是同一份算法, 不会两套口径。
排查提示: 先看 traceback 第一帧是不是 `from . import ...`; 是就换按路径加载, 不要去改包结构。

## 画进 AR 场景: 写页面已经在读的那个真源

- 通道边界写成 AR 页**本来就渲染**的元素 (实测 `zmax_data/ar_rs/fences.json`, `type="line"`,
  id `COR-SKxx-axis` / `-edge1..4`: 每段 1 轴 + 4 母线), 页面按 `GET /api/fence` 取。
- 不要新开渲染通道、不要往页面塞新 API ⇒ 页面刷新即见, 也不用改服务。
- 落地后**回读接口数一遍**, 只看到文件写成功不算。条数口径是 **Σ每条机动的母线数**, 不是「段数×5」:
  builder 每条机动写 **4 条母线** (没有逐机动的轴线), 所以 `COR-` 条数 = Σ机动数×4;
  实测条数随来源变: plan 段表建的 1288 条, 真机轨迹(--real215)建的 332 条 ⇒ 一律按 `--real215` 现建的
  段表重新数, 不要引用别的会话留下的字面条数当判据。
  按「段数×5」核会得出「少了 30 条」的假缺口, 按「段×4」核又多出 8 段差 —— 分摊到每个技能再对一遍才准。

## 🔴 轴心必须是真机录制轨迹, 不是 plan 段表

- 同一个 builder 有两种轴心: `seg_table()`(plan_long_impl 的「14 孔 × 8 段」合成直段) 与
  `segs_from_real215()`(真机 `zmax_data/pose_records/<rec>/poses.jsonl` 的折线)。前者与真机真走的路径毫无关系,
  实测轴心偏离真实轨迹 **中位 96~480mm、最大 710.8mm** —— 用户说「通道没有对应上, 得配合真实轨迹」就是这个。
  只要机器人的动作来自那条录制轨迹, 通道就必须用 `--real215` 建。
- 量偏差时**先减半径**: 母线本来就在轴心 ±r 上, 母线中点距真轨迹 80mm 才是贴合; 不减去 r 会把好通道误判成差 80mm。
- 重建与判据:

```bash
./gui-venv311/bin/python tools/ss_corridor_build.py --real215      # 轴心=真机折线, 段长/节拍/半径全真值
```

  判据(逐条都要有数): ① 每条子折线上的点距真机折线 ≤0.001mm; ② 子折线首尾衔接缝 = 0;
  ③ `L_mm` 与真路径逐段长度一致; ④ `/api/fence` 的 `COR-` 条数 = 母线条数。
- 🔴 **零位移(原地停驻)样本要跳过, 不许塞 1mm 假段**: 用 `[A[0],A[1],A[2]-1]` 占位会切断折线 ⇒
  实测 0.94mm 偏差 + 1mm 衔接缝, 判据永远不过。
- 🔴 **核偏差要遍历 `polys` 全部子折线, 不能只看 `polys[0]`**: 逐段建出来的通道是多条 2 点子折线首尾相接,
  只看第 1 条会得出「轴心只有 2 个点」的错觉, 误以为整段被塌成一条弦。

### 🔴 默认关: 通道与预测引导都不许自己加

用户口径: 通道/引导点只要与他心里的真实动作不一致就是错, 会被直接否掉（「通道也不对啊」「引导点也不准」）。所以:

- `fences.json` 的 `COR-*` 全部 `enabled=false`、页面 `CORPRE=false`、**不放**「未来 N 点」/「逐点通道」按钮。
- 三处一起关, 只关一处必复发: 真源 `fences.json` 的 `enabled` · `tools/ss_corridor_build.py` 的 `_line()` 默认值 ·
  页面 `CORPRE`/`#btnCorPre` 的 class。
- 下面两节(未来 N 点 / 逐点通道)是**已验证可行的做法存档**, 不是默认要上的功能; 要重新上线必须先得到明确要求,
  并先把轴心与真轨迹的偏差量到 ≤0.001mm 再给用户看。

### 未来 N 点通道 (已知真实轨迹 ⇒ 查表, 不是模型预测)

轨迹已经录下来了, 所谓「预测未来 10 个点」就是查表: 当前走到 i, 取 i+1…i+N 的真实位姿围成管子, 机器人前进一帧,
管子跟着挪一帧。工具 `tools/pred_corridor_from_traj.py`:

```bash
./gui-venv311/bin/python tools/pred_corridor_from_traj.py --i 30 --n 10     # 只看数
./gui-venv311/bin/python tools/pred_corridor_from_traj.py --write          # 写进 AR
./gui-venv311/bin/python tools/pred_corridor_from_traj.py --watch --write  # 1Hz 跟随真机
```

- 起点定位: 默认读 `zmax_data/rokae_sdk/traj_step_state.json` 的 `cursor`; **游标走完(≥214)或真机正在跑时改用最近真机位姿**
  (`tcp_out/latest.json` 的 x/y/z) 反查最近点, 否则「未来 10 点」永远是空的。
- 走到轨迹末尾要**跨圈接下一件的头** (连续生产), 不要返回空管子。
- 画法: 2 条母线 + 每个预测点 1 条横档(看得出走到第几个点), 颜色 `#f0a020`, 写进 `fences.json` 即页面可见。
- 🔴 **`fence_store.add()` 自己发 id, 不认调用方给的 id** ⇒ 按 id 前缀 `PRED-` 去删永远删不到, 每跑一次多一份;
  必须按 **name 前缀**(如 `🔮 未来`)认自己画的线并删除, 再重画。幂等判据: 连跑两次, `items` 总数与未来通道条数都不变。
- 回报口径: 用户要的是「一条母线+端面+轴线」这种**能看出走到第几个点**的画法, 所以逐点横档必须有;
  只给两条母线会被当成"又是一条长管子", 看不出预测步数。

### 逐点通道 (先给出下一个点的通道, 臂再进这一点)

用户口径是**顺序**: 「每个点的通道, 一个点一个点的给出, 先给出下一个点的通道, 右臂再进入到下一个点的轨迹」。
即同一时刻只存在 **i→i+1 这一段** 的管, 通道先立住, 臂再进点, 到位后才放下一点的管 —— 这就是"先约束后动作"。

- 每步只画 **5 根线**: 双层母线 ×2 (r=80mm) + 两端面 + 一条**红色不透明轴线**(轴线就是那个点本身的位置)。
  重画前先按自己的 id 组清掉上一步的 5 根 ⇒ 页面上永远只有一段 (`PST.ids.length==5`)。
- 节奏: 通道先给 **≈300ms** 让它在画面里立住, 再让臂按真实关节角从 `frames[i].j` 走到 `frames[i+1].j`;
  本步耗时取真值 `frames[i+1].t - frames[i].t`, 夹在 **[0.5, 3.0]s**(太短看不清、太长像卡住), 关节角在角度域线性插值。
- 自验(有数才算): 轴线两端 == `frames[i].p` / `frames[i+1].p` 逐位相同 (实测 i=9: 649.24/252.71/114.90 → 651.49/255.27/172.55);
  每步 `PST.ids` 恒为 5; 再点一下停 ⇒ `PST.ids=0` 且页面 `PST-*` 线 0 条。
- 🔴 **必须先把"跟随真机"和回放都让位**, 否则通道在动、臂不动: 启动前 `mirrorStop()` + `RTRAJ.playing=false`,
  结束后 `mirrorStart()`; 三路 (MIRROR 10Hz / 状态空间跟随 100ms / 回放 rAF) 都在写 `PREV.q`, 谁后写谁生效。
  同理, 通道几何也必须在**真机位姿坐标系**里算, 不能用 ar_cmd 的合成段表 (那就是"通道对不上"的根因)。

## 🧊 画成圆柱通道 (不是矩形带) — 渲染口径

写进 fences 的通道是 **1 条轴 + 4 条母线 (`edge1..4`)**, 即轴向两侧各偏 ±r 的平面带 ⇒ 页面画出来必然是
**一个矩形/扁带**, 用户会直接问「为什么每个技能的约束都是一个矩形, 不应该是一个围绕理想轨迹的圆柱通道么」。
那不是渲染 bug, 是数据只有两维偏移。要圆柱就在页面侧用轴 + r 现生成:

- 几何: `u=norm(b-a)`, 取与 `u` 垂直的两条正交基 `e1,e2`, 沿圆周取 **N=24** 点 → 两端各一个圆环;
  相邻母线围成四边形**半透明填充**当管壁; 两端圆环 `alpha≈0.6` 描边当进出口边界;
  再单独画一条**不透明**的轴线 (理想轨迹) + 两个端点 —— 三件叠起来才是「有透明度、既见轨迹又见边界」。
- 🔴 **半径从 `note` 里解 `r=([0-9.]+)mm`, 不要解 `name`**: `name` 只有「包络 SK01 #11 母线1-2」这种文字,
  按 name 取半径得 0 ⇒ 画函数里的 `if(!(r>0)) return 0` **静默不画**, 页面上不报错, 只剩线框或什么都不剩。
  这是「通道突然不见了」的头号原因, 排查先打一行 `console.log(rNote)`。
- 🔴 **真值半径在屏幕上只有几个像素**: 统一 10mm 时 ×1 约 **2px** 宽、几乎看不见 (旧的分段 3mm 更糟)。
  给一个**显示放大** ×1/2/3/5 (默认 3), 只乘渲染半径, 标签同时写真值: `通道 r=10.0mm(画×3)`。
  绝不能让显示尺寸冒充数值 —— 汇报里永远给真值。
- 只给当前这一步画一条 (当前段 + 当前工件匹配出来的那条多折线), 不铺整组; 逐段圆柱之间不连续是正常的,
  因为约束本来就是逐段的。
- **画函数的实际参数与开关现值一律现读, 不要引用本文件的历史值**: 渲染入口是 `drawCorTube(g, pr, A, B, r, opt)`
  (`N=24` 圆环 / `alpha` 管壁 `COR_ALPHA` 现值 0.22 / 两端圆环 `alpha×3.4` / 中线不透明),
  工程半径 `COR_GAIN` 现值 **1** (放大按钮仍可切 ×2/3/5); 汇报前 `grep -n 'let COR_GAIN\|let COR_ALPHA\|let COR_TUBE'` 取现值。
- 🔴 **半径真值与文件头注释会打架, 先读真值再报数**: `corridor.py` 头注释写「统一 10mm」, 而同文件 `DEFAULT_R_MM`
  与 `tools/ss_corridor_build.py` 的 `R_MM` 八段**全是 80.0**, `skill_corridors.json` / `fences.json` 的 `note` 也写 `r=80.0mm`
  —— 也就是说她自己的文档承诺 (1cm 可通行) 与在役几何 (8cm 外廓包络) 不一致。
  口径: 汇报半径永远按**真源文件现值**给, 并单独一句点明「注释/文档与该值不一致, 未动」;
  要按 1cm 口径落地就两处表 + 重跑 builder + 回读 `note`, 别只改注释或只改一处。
- 自验(全部在浏览器 console): ① 圆环每个点到轴的距离 == r (实测误差 0µm)、到轴的法向投影分量 == 0 ⇒ 是圆柱不是平面;
  ② 透明度 6% 与 50% 两帧 `getImageData` 逐像素差 >1000px ⇒ 半透明层真的在画且可调;
  ③ 投影半径随 r 与视距变化 (实测 r=10mm 画×3 ⇒ 截面圆环屏幕半径 5.3~7.5px, 整根管子约 8000 像素) ⇒
  必须开显示放大才看得见; ④ 关掉预执行约束两帧差 = 管子占的像素数 (实测 7966), 停机后红线归 0。
- 🔴 **管子里出现的矩形 = 场景立方体, 不是通道**: 围栏盒/料盘/插孔/工件长方体, 以及已放下模块的扁平小矩形,
  在通道经过它们时自然落进管子。回答用户要分两种空间: **盒子=不可进, 通道=可走**。同时提供「只看通道」
  一键把非包络元素全部隐藏(纯显示开关, 不改配置) —— 用户看通道时不该被盒子挡。
  判「哪个盒子进了管子」用**点到轴的距离 ≤ 显示半径**, 不要用 bbox 膨胀(实测会把 311mm 外的检测设备也报进来)。

## 🔵 下沉到**每个技能里** + 断点调试 (2026-11-01 老倪「迁移到状态空间工程, 要在每个技能里, 我要用代码调试, 进入断点」)

收口不再只在 `cognition.skill_step()`: 每个 `clamp()` 末尾都是 `return self.corridor_finish(_out)`,
所以断点可以打在**某一个技能**上。落点 (文件 `src/lerobot/policies/left_right/state_space/skills/atomic_skills.py`):

| 技能 | clamp 断点行 | 段 |
|---|---|---|
| SK01Approach | 665 | 接近 |
| SK02Align | 783 | 对位 |
| SK03Descend | 902 | 下降 |
| SK04Grasp | 1021 | 抓取 |
| SK05Lift | 1139 | 抬起 |
| SK06Transfer | 1258 | 转移 |
| SK07Insert | 1378 | 插入 |
| SK07Place | 1505 | 放入 (零位移, N/A) |
| SK08Complete | 1623 | 完成 |

(行号会随文件编辑漂移, 以 `grep -n 'self.corridor_dbg()' atomic_skills.py` 的实时输出为准;
上表是 2026-11-01 加 `__repr__`/`debugger_attached` 之后的实测值。)

公共件: `__repr__()` 226 · `debugger_attached()` 248 · `corridor_dbg()` 273 · `corridor_finish()` 311
(文件 `src/lerobot/policies/left_right/state_space/skills/atomic_skills.py`)。

**断点是真打进代码的** (`corridor_dbg()` → `breakpoint()`), 不是只要靠手打红点:
- 无 env + 有调试器 (VSCode F5 / `python -m pdb`) ⇒ 每个技能本进程**自动停一次**;
- `ZMAX_CORRIDOR_BREAK=1|SK03|下降` ⇒ 该技能**每拍都停**; `=0` 全关;
- 无调试器 + 无 env (生产跑引擎) ⇒ 永不停, 不会把引擎挂住。
- ⚠️ **判调试器不能只看 `sys.gettrace()`**: `python -m pdb` 下它返回 **None**, 真凭据是调用栈帧上的
  `f_trace == Bdb.trace_dispatch` ⇒ 必须沿 `f_back` 查 `f_trace`; 另加 `sys.stdin.isatty()` 闸,
  否则 CI/pytest 里 `breakpoint()` 会去读 stdin 把进程挂死 (实测 pty 下才停得住)。
  自证: `p self.code` 得 `'SK03'`; `w` 栈里看得见 `atomic_skills.py(881)clamp()` → `(282)corridor_dbg()`.
- 🔴 **调试器里 `p self` 只打 `<...SK03Descend object at 0x7f...>`** (类名+地址, 没有任何数值) ⇒ 技能基类必须实现
  `__repr__`, 把 `技能号/段/半径/当前 pos/本段行程` 打出来: `<SK03Descend SK03 下降 r=10.0mm pos=(652,364,290)mm travel=0mm>`。
  `__repr__` 里只读不写、自己绝不许抛异常 (调试器任意时刻都会调它)。
调试入口: `ZMAX_CORRIDOR_BREAK=1|SK03|下降` 触发 `breakpoint()`; 工具 `tools/ss_corridor_debug.py`
(`--list` / `--all` / `--skill SK03 --mode out -v`)。VSCode `.vscode/launch.json` 现在**只保留一条**配置:
「🧪 全界面调试 · 控制台+画布+三维+数据空间+AR (studio.py)」 (老倪 2026-11-01「就留下一个配置, 其它全删掉」);
引擎全流程调试走终端 `tools/run_engine_debug.py` (不进 launch.json), 旧配置备份在 `.vscode/launch.backup-*.json`。
A/B: `tools/ab_corridor_engine.py [--gate 0|1] [--seed 101]`。

### 工艺点级通道库 (查表直通, 不再每次现建)
- 通道已入 L2 记忆库 `data/memory/l2_store/corridors.json` (第 8 库, writer=`ss_mem_l2`), 键 = `起点工艺点->终点工艺点|阶段`;
  查 `l2_store.corridor("槽3","孔2","转移")` / `corridors("real")`; 建库 = `tools/l2_mem_build.py::collect_corridors()`。
  用户在 PPT/AR 上看"每段通道多少"时读这一份, 不要再跑一遍 bench 建表说数字。
- 🔴 **阶段名不能决定点位** (实测: 对位/插入/完成 在**孔**上, 接近/下降/抓取 在**槽**上, 转移 是槽→孔, 抬起 两处都有)。
  按「阶段→固定点位」归组 ⇒ 抓取系 5 段全落进孔, end_err 62~222mm 全错。归组只能按**每条机动自己的起终点**认点。
- 认点用**水平距离 ≤25mm** 就近匹配槽位/孔口/孔底 (悬停高度差不算另一个点; 用 3D 距离会把 240mm 悬停点判成「无此点」)。
- 每条必须标 `kind=real` (有实跑机动, end_err≈0) / `kind=geom` (点位几何 + 同形段中位 z 偏置), 报数**分开报**, 不许把 geom 说成实测。
- 选「代表条目」按**技能语义挑形状**: 抓取系 槽→槽 · 转移 槽→孔 · 对位/插入/完成 孔→孔; 不要按 n_poly 最大挑 ——
  接近 在计划里既有「槽上悬停」也有「飞到孔上方」, 取后者会让人以为 SK01 是搬运。

### 几何两个来源, 一个投影算法
1. **真源包络** `skill_corridors.json`: 轴 = 每条历史机动的真实折线 (机器人基座/AR 坐标)。无「本段目标」时用。
2. **活通道** `corridor.build(stage, A, 本段目标)`: 轴 = 理想轨迹, 坐标系跟调用方一致 (仿真 metaworld / 真机 base_link 都行)。
   有目标时优先用它。

### 三个必踩坑
- 🔴 **活通道的轴必须锚在「本段起点」**, 不能每拍拿「当前位姿→目标」重算 —— 那样横向偏差恒为 0,
  管子等于没约束 (实测 dev 全程 0.0mm)。起点在段首拍锁定 (`self._cor_a`), 段切换由 `cognition._goto()` 调
  `corridor_reset()` 清掉; 不清会把上一段的轴带进下一段。
- 🔴 **坐标系不同源的指纹 = dev 半米到一米**: 通道真源是基座/AR 坐标 (plan mm, x≈650), 仿真末端是
  (34,611,127)mm。直接把引擎 `self.x×1000` 灌进去 ⇒ 九个技能全部 `dev 560~960mm` 判越界, 动作被往错方向回中。
  现在用 `dev > max(100mm, 8r)` 判串系并跳过 (不许回中), 同时 `corridor._live_pos_mm()` 只认基座系来源
  (`trace_live.json` 的 `src` 含 metaworld/仿真/episode ⇒ 返回 None)。
- ⚠️ **`skill_calls.log` 只记 dev/r/why/in/err, 不记 geometry mode** ⇒ 想区分 stored/live 要看 dev 的量级
  (stored 串系是 500mm+, live 是 0~50mm), 或给日志补 `mode` 字段。

### 实测 (seed 101, 引擎 395 步 · 半径统一 10mm)
- `ZMAX_SKILL_GATE=0` 通道开/关: 395/395 拍, 段序与终点**逐位相同** ⇒ 零回归。
- 通道开: dev p50 **3.7mm** / max 48.8mm / **越界 38 拍** ⇒ 真在约束, 不是只画线。
  (半径从分段 3~25mm 收到统一 10mm 后, 越界从 ~0 升到 38 拍 = 约束变严, 但编排没变。)
- `ZMAX_SKILL_GATE=1` (技能输出真替换动作): 两臂都 1000 步未完成, 终点 0.2705 vs 0.2711mm ⇒ 通道不是新的失效源。
- 逐技能自检 `tools/ss_corridor_debug.py --all`: **8/8 PASS** (管内开关逐位相同 + 管外 dev=30mm>r=10mm 切外回中且单拍不超),
  放入(SK07Place) 在 plan 里是零位移段 ⇒ 标 N/A, 不造管子。
- 半径改动后必回读三处: `skill_corridors.json` 八段全 `r_mm=10.0` · AR `fences.json` 1288 条 `note` 全含 `r=10.0mm` ·
  `GET /api/fence` 同样是 1288 条且 note 一致 (只看文件写成功不算)。

## 左侧面板「原子技能约束」: 每段一行 + 一个检查按钮

- 列: 段 / 技能号 / 半径 / 轴长 / 节拍 / 轴向 v 上限 / 单拍限额 / 当前偏差 / 状态 / 操作。
- 每行「检查」把**故意越界**的动作过同一份投影函数, 打印越界量 → 削成多少 → 削因; 这才是"通道真的在约束"的证据。
- 面板读 `skill_corridors.json` + 实时 trace, 坐标过期就显"无 3D 坐标"并禁用偏差列; 「重算通道」按钮调 builder 重算并同时刷新 AR 边界。
- GUI 侧挂载三步 (缺一就是点了没反应): 侧栏加卡 (配色进 `CARD_BORDER`) · `_lazy(key, builder)` 注册页面 ·
  导航分发里 `target==key` 时 `setCurrentWidget` 并 `refresh()`。

## 验证清单 (按顺序跑, 每条都要有数)

```bash
./gui-venv311/bin/python tools/ss_corridor_build.py            # 建通道 + 写 AR 边界, 打印 8 段表
curl -s http://127.0.0.1:8797/api/fence | grep -c COR-         # 边界真的在页面上 (== 段数×5)
QT_QPA_PLATFORM=offscreen ./gui-venv311/bin/python -c "..."    # 面板: 行数=8 + 逐段检查全过
ZMAX_CORRIDOR=1|0 <引擎入口> --steps 60                        # A/B: 段序列/拍数一致, 只有幅度不同
```

- 面板离屏自验要比对"行数 / 列数 / 每段状态文案", 只看"页面没报错"不算。
- 汇报时把「通道半径/轴长/节拍预算」与「实测越界→回中」的数字一起给; 只描述公式会被当成没做。

## Pitfalls

| 坑 | 症状 | 修法 |
|---|---|---|
| 用等比缩小处理越界 | 速度降下来了, 位置一直在管外 | 切外要把向外分量归零 + 补回中分量 |
| 通道数据用 stale trace | 面板一直显示同一偏差 / 永远"通道内" | 帧龄阈值内才用, 过期返回 None 并显式标注 |
| 在九个 `clamp()` 里各写一遍通道**实现** | 九份逻辑漂移, 改一处漏八处 | 实现在基类 `corridor_finish()`, 每个 `clamp()` 只留一行调用 |
| 技能和 `skill_step` 两处都投影 | 回中速度算两遍 / 断点永远停在 cognition | 技能带回 `corridor` 字段时 `skill_step` 必须跳过 |
| 只写 4 条母线就交付 | 用户看到的是矩形带, 不是通道 | 页面侧按轴+r 生成圆环管壁 + 边界圆环 + 不透明中线 |
| 从 `name` 解半径 | 半径 0 ⇒ 画函数静默 return, 通道凭空消失 | 半径在 `note` 的 `r=<num>mm`, 解不到先打印再判 |
| 按真值半径直接画 | 10mm 在 ×1 下约 2px, 看不见 | 显示放大 ×3, 标签同时写真值 |
| 只改 `corridor.py` 的默认半径 | 代码 10mm 但页面/真源还是旧值 | `R_MM` 与 `DEFAULT_R_MM` 一起改, 重跑 builder, 回读 `/api/fence` 的 `note` 里 `r=` |
| 按阶段名归组通道 | 抓取系 5 段全落进孔, end_err 62~222mm | 按每条机动的起终点认点 (水平 ≤25mm), 键写成 起点->终点|阶段 |
| 自行加预测/通道叠加层 | 用户一眼看出"不对", 全部推翻 | 默认 `enabled=false`, 只在明确要求时开, 先量偏差再上 |
| 新增画布连线后不重建总线 | 节点端口有了, 话题里没有, 下游收不到 | 连着线跑 `tools/mw_db.py sync`, 再 `tools/mw_db.py node <id>` 数入口话题 |
