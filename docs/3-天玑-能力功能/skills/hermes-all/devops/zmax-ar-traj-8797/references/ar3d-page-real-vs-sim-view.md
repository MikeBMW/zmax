# ar3d 页「机器人不同步」＝ 页面视图模式问题，不是链路问题

> 场景元素（插口/料盘/槽位）要增改时看同目录 `ar-scene-cells-place-cells.md`（fences.json → scene_places_build → 回读）。
> 要仿照本页另做一个「新场景页」（同机器人同桌子、操作后定义）看同目录 `scene-page-derivation.md`
> （复用同一份 HTML，只换场景默认值/白名单/标题，不另写渲染器）。
> 回放/单步/甘特光标/末端模块+tool1 的口径看 `right-arm-real-traj-replay.md`。

用户口径: 「http://<host>:8797/ar3d 机器人怎么不同步了？」。
先把**后端**与**前端视图**分开判，别一上手就查 8797 / 相机 / 中继。

## 1. 先证后端是新鲜的

```bash
curl -s http://127.0.0.1:8797/api/tcp | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['ok'],d['age_s'],[round(d[k]*1000,1) for k in ('x','y','z')],len(d.get('joints') or []))"
# 期望: True  <0.3  [x,y,z mm]  6
```

- `ok=true` + `age_s<0.3` + `joints` 6 维 ⇒ 服务端位姿每拍都在更。
- 再取一条**独立**读数对账: `bash tools/rokae_sdk_run.sh state` → 证据 json 的 `pose.tcp`(m) 与 `sampler{x,y,z}`。
  两次采样相隔几秒时允许差几十毫米(臂在动)，但姿态量级与工作区要一致。
- 页面取位姿走 `fetch('/api/tcp')` 的 `joints`(rad)。注意键名: 服务端给 `joints`，`latest.json` 原名是 `joint`，
  页面两者都兼容 —— 报「页面拿不到关节」前先确认键名。

## 2. 后端新鲜而画面不跟 ⇒ 查页面视图模式

真源: `zmax_data/ss_live/exec_switches.json`

```json
{"node":"ssact", "ar_scene": true, "real_auth": false, "src":"画布 🤖 机器人执行器 开关", "_kept_alive_by":"ss_canvas_loop (只续 ar_scene)"}
```

`tools/web/tcp-ar.html`:

- `arViewSet(true)` ⇒ `VR.real = false`（**真机右臂让位**）、`VR.simArm = true`（**仿真双臂接管**，按
  `ar_cmd.json` 的段/插值/节拍走帧）。用户盯着的那条臂是**仿真**，当然不跟真机。
- `arModePoll` / `arModeApply` **每 2s** 跑一次 ⇒ 手点「🦾 右臂_真机」按钮 2 秒内被抢回，症状是「点了没反应」。
  别反复点这个按钮。
- 左栏「🧠 状态空间」拨杆一旦被动过(`SSMODE.touched`) 就以拨杆为准，不再每 2s 被画布开关抢回。

判据与修法（按这个顺序做，别跳步）:

1. 控制台读态: `typeof VR!=='undefined' && {real:VR.real, simArm:VR.simArm}`；再看两个按钮 class 里有没有 `on`、
   按钮文案带不带「(已隐藏)」。
2. **先关全局开关**: 把 `exec_switches.json` 的 `ar_scene` 写 `false`（`t`/`t_str` 一起更新，`src` 写清原因）。
   实测把它写成 false 后 351s 未被 `ss_canvas_loop` 抢回 —— 它只续「开」，不会把「关」翻回来。
   但**只写文件不够**：页面自己的拨杆 `#ssSw`（label role=switch, `aria-checked`）仍是 `true`，画面还是仿真臂。
3. **再关页面拨杆**: 控制台 `document.getElementById('ssSw').click()` 直到 `aria-checked=false`。
   这一步之后「🦾 右臂_真机」文案才会脱掉「(已隐藏)」。
4. **最后收掉仿真臂**: 点「🦾 右臂_仿真」。🔴 两个按钮是**互斥**的 —— 仿真一开就把真机臂重新藏起来，
   所以「点真机 → 点仿真」的顺序会得到「真机又藏了、仿真还亮」（实测连点三次都是这个结果，别反复点真机）。
   正确终态: 真机 button `class=on` 且文案无「已隐藏」；仿真文案带「(已隐藏)」、class 无 `on`。
5. 自证（这就是「一模一样」的判据，别用肉眼看）: 页面全局 `TCP.joints` 与 `/api/tcp` 的 `joints` **逐位相同**。
   实测 `[0.155385,-0.064705,-2.542765,1.432273,0.432679,-0.687576]` 两边一致 ⇒ 同源数据，不是「接近」。
6. `arViewSet(false)` 仍可作为一次性急救调用；`real_auth=false` 只说明「这一页没有真机授权」，
   与臂是否在动无关（授权真源仍是 8793 / `ctl_auth.info()`）。

页面层按钮语义: 「🦾 右臂_真机」= 只藏/显那条跟随 `/api/tcp` 的臂；「🦾 右臂_仿真」= 仿真臂层；
两者可同屏，左侧 Δ 面板看两臂偏差。

## 2b. 「仿真臂没按真实轨迹走」= 数据源错，不是渲染/链路

症状: 真机在跑 215 点，ar3d 里的**仿真**右臂在走另一条轨迹（节奏、姿态都不对）。
真因: 仿真臂的关节角只由 `ar_cmd.json`（状态空间合成段表，`plantStep` 60Hz）喂，
`/api/tcp` 的真机 `joints` **从来没进过仿真臂**。链路是好的，源不对。

修法（MIRROR 镜像，页面侧，纯只读、不下发）:

- 10Hz `fetch('/api/tcp')` ⇒ `PREV.q = d.joints.slice(0,6)`（弧度）、`PREV.target=[x*1000,y*1000,z*1000]`、
  `PREV.M=urdfFK(q)`；每拍 `mjPushQ()`、每 3 拍 `mjPushQForce()`（8802 同帧）。
- `d.age_s > 1.5` 直接 return —— 真值过期就不许动，别拿陈旧位姿当真机。
- 🔴 必须加闸，但**闸要带例外**：`plantStep()` 顶部
  `if(MIRROR.on && !PLANT.local){ PLANT.raf=requestAnimationFrame(plantStep); return; }`。
  不加闸，ar_cmd 那一路 60Hz 会把 PREV 盖掉（看起来仍「没按真实轨迹走」）；写成无条件的 `MIRROR.on`，
  人点「🏭 全流程 UPH」时本地仿真被永久压死（右臂一动不动）。两种错法都出现过，闸必须两段式。

## 2c. 三路抢 `PREV`：先定优先级，再逐处加守卫

`PREV`（三维里那条仿真/幽灵臂）会被三路写：本地全流程 `plantStep`、状态空间信号 `ar_cmd`、真机镜像 `MIRROR`。
只加一路的守卫必然「另一路被按死」，症状统一表现为**点了按钮右臂不动**。优先级与守卫（缺一处就复现）：

1. 本地全流程 `PLANT.local` 最高：`mirrorTick()` 开头 `if(PLANT.on && PLANT.local) return;`。
2. `autoMirrorMaybe()` 与 `ssFollowStart()` 都要 `if(PLANT.on && PLANT.local) return;`
   —— 它们会把 `PLANT.local` 打回 false 并把 PREV 交还 ar_cmd（`arCmdPoll` 每 100ms 调一次）。
3. `plantStep()` 里那句「接了状态空间但信号断了就停在最后一帧」的 `if(SSMODE.on && !isAR) return;`
   必须加 `&& !PLANT.local` —— `SSMODE.on` 是「接入」的事实、不是「在跟」，不加就把本地全流程挡死。
4. 按钮判据别用 `PLANT.on`：自动镜像那条路也会把它置 true ⇒ 第一次点击执行的是「停」（而按钮文字还没变），
   人看到的就是点了没反应。用 `PLANT.on && PLANT.local`。
5. `zmax_data/ss_live/ar_cmd.json` 由画布/执行器节点按拍重写（约 4s 一次）⇒ **别手改这个文件**去换轨迹，
   改完立刻被覆盖；要换源就改驱动源（页面镜像，或节点侧）。

判据（不用肉眼）: 点全流程后 `PREV.q` 两秒内变化 > 0.1 rad；再点停 ⇒ `PREV.q` 回到 `/api/tcp` 的 `joints`（逐位相同）。

### 2c-1. 全流程/本地仿真下的右臂也要用真轨迹关节角

用户口径: 「右臂仿真，要改成真实轨迹的位姿」—— 不限于点「📍 右臂跑真实轨迹」那一刻，**只要在本机仿真里动，就必须是真轨迹的数**。

- `plantStep()` 的本地分支里，`plantAt()` 只用来算 HUD/产量，右臂位姿在它之后**用内嵌 `rtrajData`（`ensureTrajJoints()`）覆盖**：
  `t = PLANT.simT % frames[last].t` → 找相邻两帧 → 关节角线性插值 → `PREV.q=q; PREV.M=urdfFK(q); PREV.target=f2.p`，
  并置 `PREV.src='traj215'`、`PREV.trajT=t` 供自检。
- 判据: 「轨迹插值算出的 q」与 `PREV.q` **逐位相同（maxErr 0）**，且 `PREV.trajT` 随时间递增（实测 3.01s→8.60→10.67→12.83s），
  臂的末端目标沿录制路径推进；停止后 `PREV.q` 回到 `/api/tcp` 的 `joints`。
- 不要再回到「plantAt 自己解 IK」—— 那是合成 14 孔计划，不是这段录制，用户会直接看出「不是真实轨迹」。

### 2c-2. 预测/通道类叠加层：默认关，不许自己加

用户对「我看不准就等于错」的画面元素是**零容忍**: 约束通道(管状包络)、未来 N 点引导、逐点通道都曾被直接否掉
（「通道也不对啊」「引导点也不准」）。规则:

- 这类叠加层**默认全关**, 且不要为了「展示能力」自己加按钮。真要加, 先问一句, 得到明确要才做。
- 三个开关一起关, 只关一处必复发: `zmax_data/ar_rs/fences.json` 里 `COR-*` 全部 `enabled=false`;
  建造器 `tools/ss_corridor_build.py` 的 `_line()` 默认写 `enabled=False`; 页面 `CORPRE=false` 且 `#btnCorPre` 不带 `on`。
- 已经写进 fences.json 的临时预测线要有可识别的名字前缀(如 `🔮 未来`), 清理时**按名字前缀**删 —— `fence_store.add()`
  自己发 id(`F93623a`), 调用方给的 id 一律被丢弃; 按 id 前缀删会一条也删不掉, 重画一次多一批。
- 页面按钮若用过脚本注入(不改 HTML), 撤功能时要连注入块一起删, 否则留着死按钮/死代码, 下次接手以为还在用。
- 通道几何/偏差判据/逐点做法看 `skill-constraint-corridor`(轴心必须取真机折线, 默认关)。

### 2c-3. 「右臂位置突变」= 三家写者在同一帧里抢 PREV，且写进来的是另一支解

症状: 用户说「右臂位置突变」，画面单帧跳几十度(实测 4.06 rad ≈ 233°)。三路都会迟到写:

1. **`plantAt()` 内部解 IK 后直接写 `PREV.q`** —— 合成 14 孔计划的 IK 有翻腕支，与录制轨迹差整支。
   修: 本地全流程期间禁止 plantAt 写 PREV(`window.__NO_PLANT_PREV` 布尔闸, plantStep 调用前后置位/复位),
   右臂只由 215 点关节角驱动; 若轨迹帧还没加载完(异步), **保持上一帧 q 不动**, 绝不许拿 IK 解顶上去。
2. **`mirrorTick()` 的 `fetch` 回来时全流程已经开始** —— 入口那句 `if(PLANT.on&&PLANT.local) return` 发生在请求发出前,
   `.then()` 里必须**再查一次**, 否则真机位姿照样写进 PREV(实测 3.65 rad)。
3. **停全流程切回跟随真机** —— 一帧跳回真机姿态(实测 0.97 rad)。修: `mirrorStart()` 记 `blendFrom/blendT0`,
   之后 600ms 内把真机 q 与 blendFrom 线性混合再写。

同理，起播也不许硬切: 按当前关节角找**最近的轨迹帧**做起点(`trajOff`), 头 600ms 从当前姿态 blend 过去,
并在页面加载 1.5s 时 `ensureTrajJoints()` 预热关节角(否则首帧就落回 IK 解)。

**定位手法(比肉眼快)**: 在控制台给 PREV 的字段装 setter, 抓写入栈, 一次就能指到函数:

```js
window.__QS=[];let _q=PREV.q.slice();
Object.defineProperty(PREV,'q',{configurable:true,get(){return _q;},
  set(v){const d=Math.max(...v.map((x,i)=>Math.abs(x-_q[i])));
    if(d>0.5)__QS.push({d:+d.toFixed(2),st:new Error().stack.split('\n').slice(1,4)});_q=v;}});
// 点按钮跑 2~3s, 然后看 __QS: 栈里直接是 plantAt→plantStep / mirrorTick
```

验收判据(用 `requestAnimationFrame` 逐帧量, 100ms 采样会漏掉单帧尖峰):
运行期单帧最大 ≤0.15 rad、停后回切 ≤0.25 rad、`>0.5 rad` 的写入 0 次、停下来后 `PREV.q` 与 `/api/tcp` 的 joints 逐位相同。

## 2d. 页面默认口径（用户口径，每版都要保持）
- 原子技能包络 / 预执行约束 / 未来 N 点引导**默认全关**（见 2c-2）: `CORPRE=false`、`COR*` 的 `enabled=false`、
  不放任何「未来 N 点」按钮；用户没要的叠加层不加。
- MuJoCo 同视角**默认不接**：删掉 `mjInit()` 末尾那段自动 `mjToggle()`，改为隐藏 `#mjframe`、`#vr` 背景恢复不透明、
  `#bMj` 去掉 `on` 且文案回到「🎥 MuJoCo 同视角」。
- 工程配置点位**默认全关**：`CFG_ON[p.name]=false`（原默认 true）+ `VR_TEXT=false`（等价按「全关」，3D 批注文字一起不画）。
- 实验桌**默认隐藏**：`TAB.show=false`，HTML 里 `#bTab` 的 `class` 去掉 `on`。
- 任何默认值改完都 bump 版本戳（`<title>` / `#bVer` / `bld` 三处 `rNN`），否则无法证明用户拿到的是新页。
- 交接: `rtrajPlayJoints()` 开头 `mirrorStop()`，回放结束（`VR.simArm` 时）`mirrorStart()`；两路同时写 PREV 会互踩。
- 起停挂钩: 页面加载 1.5s 后若 `VR.simArm!==false` 自动 `mirrorStart()`；点「🦾 右臂_仿真」后按 `VR.simArm` 起停；
  `arViewSet(on)` 里 on ⇒ mirrorStart、off ⇒ mirrorStop（与真机臂路由同源）。

判据（别用肉眼看）: 控制台 `MIRROR.on===true && MIRROR.n 递增 && MIRROR.err===null`，且
`PREV.q` 与 `/api/tcp` 的 `joints` **逐位相同**。`PREV.q` 才是仿真臂真正用的那份；
`TCP.joints` 相同只能证明页面拿到了真值，证明不了仿真臂在用它。

## 2e. 同一个物体被**两套位姿**各画一遍 ⇒ 画面上出现两个、而且错开

用户口径: 「黄色光模块前边还有个绿色光模块, 位置不对, 前面的绿色应该向后与黄色重合」。

- 两条绘制路径各取各的源: `drawModuleBox()` 用 `TCP.frames.tool1`(真机位姿)，
  `drawFlatModule()` 用 `PREV.M['tool1']`(幽灵/仿真臂位姿) ⇒ 手里同一个模块**画了两遍**。
  实测两者只差 3mm(真机 `695/226/202` vs 幽灵 `695/229/205`)，但**绘制口径不同**
  (一个沿 tool1 的 Z 轴长出去，一个按「长轴∥世界 X」摆平) ⇒ 投到画面上错开一截，看着像飘在前上方。
- 定式: **真机位姿可用时，所有跟随末端的叠加层都锚到真机那一份**，只在真机位姿缺失时才退回幽灵臂。
  外层 `if` 也要一起放宽（原来把 `PREV.M['tool1']` 当必要条件，真机有值、幽灵没值时反而不画了）。
- 🔴 **不能就地替换成 `{t: TCP.frames.tool1.origin}`** —— `TCP.frames.tool1` 的结构是
  `{origin, x, y, z}`，**没有 `R`**。下游十几行之后一定有用 `_cols(_rpT1.R)` / `_rpT1.R[*][2]` 的地方，
  少给 `R` 就是 `_cols(undefined)` ⇒ 抛异常 ⇒ `drawVR` 从那里往后全不画(见 2j)。
  `_cols(R)` 取**三列=三轴**，所以要把三个轴向量拼成列矩阵:
  `R=[[x[0],y[0],z[0]],[x[1],y[1],z[1]],[x[2],y[2],z[2]]]`，并把 `z` 单独留在对象上供长度轴用。
- **改口径比改源更关键**: 两块重合的前提是**同一个几何口径**，只把 origin 对齐还不够。
  口径表(务必分清，混淆一次就是半个身长的偏差):

  | 函数 | 传进去的点 | 内部怎么算 |
  |---|---|---|
  | `drawModuleAt(g, pr, O, AX, ...)` | `O` = **头部中心** | `C = O + AX[2]*(L/2)` |
  | `drawModuleBox(g, pr, FR)` | `TCP.frames.tool1.origin` = 头部中心 | `C = origin + AX[2]*(L/2*sgn)` |
  | `drawFlatModule(g, pr, c, ...)` | `c` = **体心** | `c ± (L/2, W/2, T/2)` |

  用户口径: 「tool1 的原心，是光模块的**头部中心**，而你画成了尾部中心」。
  把头部原点喂给 `drawFlatModule` 再自己补 `+[L/2,0,0]`，等于把头部挪到半个身长处 ⇒ 整体退半个身长。
  正确做法是改用 `drawModuleAt`（口径就是「头在 O」），并把 `AX[2]` 按与 `drawModuleBox` **同号**处理:
  `sgn=(tool0.origin−tool1.origin)·AX[2] >= 0 ? +1 : -1`，为负就把 `AX[2]` 取反。
  不同号会头对头、身子朝两边，看着像一个双倍长的模块。
- 判据(控制台，别用肉眼): 把两个**体心**各算一遍相减，应为 `0/0/0`；差在几 mm 内却仍看得出错位 ⇒
  是**绘制口径**问题，不是位姿链路问题，别去查 mirror/ar_cmd。

## 2f. 场景几何**不许写死**，一律读真值文件

- 实测一处「✅ 已插入 47mm」的绿色模块 z 写死 `0.278`，而 2# 孔真值是 `761.3/229.8/**187.6**`(插到位 811.6)
  ⇒ 高了 **90mm**，画面上飘在孔上方。孔轴是水平 +x，插入件的 z 就该等于孔口 z。
- 真值源: `zmax_data/runtime/traj/sim_insert.json`（孔下口 / 插到位 / 孔轴方向）。任何「插入到位」「留在盘里」
  「放在槽里」的位置都从它推，不写常量。
- 用户说「位置不对 / 应该重合」时，**先把自己画的那个点与真值点的三轴差算出来并报给他**，再改；
  90mm 这种量级一定是常量错，不是透视错觉，也不是他的眼睛有问题。

## 2g. 场景物体「尺寸不一致」: 先算绘制范围 vs 标称，常见是隐含底面偏移

用户口径: 「ar3d 中的方盘与实际尺寸不一致, 你得按照方盘的尺寸画」(尺寸已由现场确认 315×230×40)。

- 先核**标称值本身**: 控制台读 `TPAN2.L/W/H` 与 `tpanRange(TPAN2)` 的 `x1-x0`/`y1-y0`
  (实测回 `230 / 315` mm，与标称一致 ⇒ 尺寸定义没错，**别去改 L/W**)。
- 再核**绘制**: `drawTrayPan` 里 `zb = 0.008 + z0`(桌面板厚) 而 `zt = T.H + z0` ⇒ 40mm 的盘只画出 **32mm**。
  凡「坐在台面上」的体(盘/箱体/工装)，**底偏移会把标称厚度吃掉一段**；用户目检出来的「尺寸不对」常常就是这个 8mm。
- 顺序: 标称常量 → `tpanRange` 的换算方向(`L` 沿 Y、`W` 沿 X) → 绘制里的 zb/壁厚 → 最后才怀疑透视。
- 报口径时把「屏幕上看方不方」与「实际尺寸对不对」分开说: 315:230 在斜视下必然被压扁，**顶视图**才判得了比例。
- 顺手 `grep` 一遍有没有别处在运行时改 `TPAN*.L/W/H/cx/cy`(实测零命中) —— 排除「被别的按钮/动画覆盖」这条假设，
  省得用户下次再问时又从头怀疑一遍。

## 2h. 三维画面上不许压黑底文字牌 (用户口径: 挡视线)

用户口径: 「这个场景有两个黑条, 应该是文字, 影响我视线, 删掉」—— 实测就是 `trayTableDims()` 里两块 42px 黑底文字牌:
① 桌子尺寸牌(`桌子 长…×宽…×高… mm` + `桌面 z=0…`，画在桌子右前三点的 x 最大处 +24)
② 左右臂状态牌(`🦾 右臂: 显示` / `🤖 左臂: 显示`，画在 `(8, H-58)`)。

- 定则: **画面上只留贴着模型走的标注**(尺寸线 `dimLine` 那种)，**信息牌一律不进三维画面** ——
  尺寸进「🧪 实验桌 / 📦 箱体」面板，显示状态看顶部按钮的 on/off。
- 这类 `fillRect + fillText` 的牌子 grep 抓手是 `rgba(0,0,0,.` + `fillRect`；只删牌子那段、
  别顺手把 `dimLine`/`label()` 一起删（那是用户认的尺寸线）。
- 改完在控制台核准: `document.getElementById('trayDims')` 是否存在(有 DOM 层时 canvas 牌本来就该跳过)、
  `document.querySelectorAll('canvas').length` 仍为 4、无 JS 错误 —— 三件全过才叫删干净。

## 2i. 对「相机实测 vs 场景几何」的毫米级承诺，先读标定残差再开口

- 用户会要求「按手臂相机看到的改 ar3d 的尺寸」。能做的是**尺寸/标称/真值对齐**；
  「按画面正投影对齐到毫米」需要手眼外参可信。
- 实测 `zmax_data/calib/handeye_tcp_cam.json` 的 `residual` 是 `axxb_trans 92.4mm / rot 12.5°` ⇒
  **用它反投影会带来几十毫米误差**，比要修的那个 8mm 厚度 bug 大一个量级。
- 定式: 先读 `residual`，把数字报出来再决定能不能承诺；不够就直说「要重做手眼标定（用已有的 215 点配对数据即可，
  不需新增动作）」，**不要嘴上说能做到、手上用错外参去改**。用户对夸大的容忍度是零。

## 2j. `drawVR()` 是长链: 中间抛异常 = 整屏**静默**丢元素

症状: 用户报「怎么丢了那么多元素」，而浏览器**零 JS 错误**、`canvas` 还是 4 个 —— 因为绘制挂在
`requestAnimationFrame` 里，异常被吞掉，`drawVR` 从抛点往后全部不画(桌子/盘/模块/围栏/坐标轴一起消失)。
改这个文件时逐条守住:

1. **绝不在绘制链中间 `return`**。要「不画」就 `if(cond){ ... }` 包住那一段，或给安全占位值
   (`if(!T) T={t:[0,0,0], z:[1,0,0], R:[[1,0,0],[0,1,0],[0,0,1]], _none:true}`)。
2. **不要引入未定义变量**。重构时把某个对象的形状换成 `{t:...}`，下游还在用 `.R`/`.z`，
   就在十几行之后炸 —— 改的那一行本身完全没错，所以极难看出来。
3. 取矩阵的调用一律兜默认值: `_cols(T.R || [[1,0,0],[0,1,0],[0,0,1]])`。
4. 变量名别撞: 同一条链里 `var _rpC` 先当坐标、十几行后又当颜色数组，不报错但颜色全错。

改完的自证(控制台，三件全过才算没改坏): `TPAN2.show`、`TAB` 有值、`MOD30.show`、`VR.mod` 为 true 且
`document.querySelectorAll('canvas').length===4`。任一为 `undefined` 说明脚本没跑完，别急着交付。

## 2k. 节拍/阶段面板必须按**真机游标**判，不许按时间空转

症状: 用户报「现在还是插入阶段，但是你的节拍显示拔出」。真因是 `mtNow()` 用
`PLANT.simT % cycle_s` 自己走时间轴 ⇒ 与真机完全脱钩，真机还在插入，面板已经循环到下一个元任务。

- 定式: `mtNow()` 第一优先判据是 `SYNCUR.cursor`，按游标落段映射元任务(段界与段表同源)，
  并在返回的 `src` 里写明 `真机游标 N → MT-0X`；时间轴只在没有真机游标时兜底。
- 判据: 读面板 `#mtNow` 文本，必须带「真机游标 N → MT-0X」；游标停在插入段时不许出现「拔出」。
- 段表只有一份真源、三处副本: `arm_step_traj.py:GANTRY_SEGS` / `ss_meta_task_ar.py:_REPLAY_SEGS` /
  `replay_derive.py:SEGS` —— 改一处必须同步三处，改完重跑 `ss_meta_task_ar.py` 生成
  `config/tasks/ar_meta_tasks.json`，再用**旧名计数为 0** 自证(不是看新名存在就算数)。
- `step_traj` 返回的 `steps[].seg` 是**上一次跑批时**写进日志的历史值，改段表后它不会立刻变；
  别把「日志里还是旧名」误判成「改动没生效」。
- 段名要跟真机实际动作对齐，判据是 TCP 几何而不是耗时猜测: 例如插入段应满足
  `孔下口.x ≤ tcp.x ≤ 插到位.x`。命名反了会让用户当场看出「阶段不对」。

两种语义要分清，别默认用户想点按钮:

| 用户说 | 含义 | 做法 |
|---|---|---|
| 「仿真没按真实轨迹走 / 改成真实轨迹」 | 真机怎么动仿真怎么动 | MIRROR（默认态，无需点按钮） |
| 「让仿真把真实轨迹跑一遍」 | 仿真自己演一遍 | 点「📍 右臂跑真实轨迹」（内嵌 `rtrajData` 215 帧关节角真值，走完自动回 mirror） |

改完必须 bump 页面版本戳（`<title>` 与 `#bVer` 里的 `rNN`）再让用户刷新 —— 不 bump 你无法证明他看的是新页，
他也无法自证。

## 3. 位姿数值「看着离谱」不一定是坐标错

实测一次 z≈650mm 被当成坐标错，实际是 215 点轨迹的高位段: `frame[128]=456.6/206.3/662.0`，
与真机只差 **1.8mm**。先用 `tools/action_check.py`（或 `action_bus.nearest_index()`）对一次最近点，
再决定要不要查标定/坐标系。判据:

- 关节差 ≤0.2° 且末端差 ≤3mm ⇒ 同一个点，数值正常（差的那点来自 `TOL_DEG` 到位容差）。
- 关节差 >1° 或末端差 >10mm 才去查点号/游标/标定。
