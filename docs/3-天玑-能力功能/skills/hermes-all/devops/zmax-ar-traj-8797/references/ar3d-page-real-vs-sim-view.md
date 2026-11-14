# ar3d 页「机器人不同步」＝ 页面视图模式问题，不是链路问题

> 场景元素（插口/料盘/槽位）要增改时看同目录 `ar-scene-cells-place-cells.md`（fences.json → scene_places_build → 回读）。

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
