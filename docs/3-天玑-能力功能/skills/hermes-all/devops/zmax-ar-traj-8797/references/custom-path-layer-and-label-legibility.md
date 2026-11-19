# 在 /ar3d 上显示「任意自定义航路」+ 标签可读性

用途: 要让页面画一条**不属于五条命名轨迹**的航路(补采航路 / 规划草稿 / 仿真回放), 并让用户真的看见。

## 1. plan 层的绘制闸: 不是「有数据就画」

- `_traj()` 的 `plan` 来自 8791 `scene.json` 的 `path3d` box; 页面上真正画不画由 `NAMED_ON[planOwner()]` 决定,
  而 `planOwner()` 只按 `planLabel` 里的关键词(`建图|安全|实时|小红`)归类, **其余一律落到 `'square'`**
  ⇒ 自定义标签的航路只有「轨迹2 矩形」开着才画, 否则静默不显示(接口里明明有 44 个点)。
- 定式: 加一层 `planVisible()`
  ```js
  function orbitOn(){ return /<自定义标记>/.test((TRAJ&&TRAJ.planLabel)||''); }
  function planVisible(){ return !!(NAMED_ON[planOwner()] || orbitOn()); }
  ```
  把**所有绘制闸都换成 `planVisible()`**: 三维 `drawTube(TRAJ.plan)` · VR 的 `tube(TRAJ.plan)` ·
  canvas 上那块「粗线+点+起终点+标签」。只改一处会得到「三维有、2D 画布没有」这种半截现象。
- 服务端预览开关做成**文件 flag**(如 `zmax_data/runtime/traj/orbit_show.flag`): 存在时 `/api/traj` 用
  `planned_traj.json` 的 `pts_mm` 顶掉命名轨迹层, 删文件即恢复 —— 只影响画面, 不碰执行链/8791。

## 2. 黑条 = 标签的黑色底框被长文案撑成横贯画面的一条

- 航路标签的绘制是 `fillRect(lx-4, ly-15, tw+12, 21)` + 文字, `tw = measureText(lbl).width`;
  标签 70 多个汉字时 `tw` ≈ 画布宽度 ⇒ 屏幕上一条黑带挡住整个视图(用户只说「黑条, 删掉, 挡我视线」)。
- 定式(两处都要): ①服务端 `plan_label` 只给**短标签**(如 `插口补采 · 44点/651mm`), 不要拼 note;
  ②绘制侧硬截断 `if(lbl.length>30) lbl=lbl.slice(0,29)+'…'`。判据: `measureText` 出来 < 画布宽 1/3。
- 同类风险: 任何 `fillRect(..., tw+…)` 的画布标签都适用这条, 不要指望数据侧永远短。

## 3. 入口必须是页面上的按钮, 不是 URL 片段

- 给 `#orbit` 这类 hash 自动播放**只能当附加**: 用户不会去敲片段, 现场直接回「没看到」。
- 定式: 在按钮行加一个显眼按钮(带 `border-color/color` 强调), `onclick` 调同一个启动函数; hash 自动播留给调试。
- 该页 HTML 由 8797 以 `Cache-Control: no-store` 从磁盘直发 ⇒ **改完 `systemctl restart zmax-traj-ar` 再让现场硬刷新一次**。

## 4. 「仿真右臂走这条航路」怎么放(零下发)

- 页面内嵌的 `rtrajData` 是 215 点真值,**别覆盖它**; 走独立的 `rtrajPlayJoints(d)` 播放器:
  `d = {frames:[{p:[3]m, q:[4], j:[6]rad, t:s}], n_frames, path_mm, rot_total_deg, src_rec}`,
  它会冻结左臂、播完自动切回「跟随真机」, 全程不发真机指令。
- 关节帧来自离线 IK:`MjSpec.from_file(URDF)` 编译后做阻尼最小二乘 IK(6 轴)。
  🔴 **URDF 的 `tool0` 是法兰, 控制器 TCP 在法兰前 258.7mm(工具)**: 用实时关节角做 FK 得到法兰位置,
  与控制器 TCP 的差向量模长恒 ≈ 工具长度且方向 == 法兰 +z ⇒ 解 IK 前先把目标换成 `flange = TCP − 0.2587·R[:,2]`。
  直接把 URDF 的 `tool0` 当 TCP 用会差 20cm 以上(实测 46/129mm 量级)。
- 端点 `GET /api/orbit_frames` 直发那份 frames JSON; 页面 `fetch` 后先 `ensureTrajJoints()`(左臂冻结/FK 依赖 215 点那份)
  再 `rtrajPlayJoints(d)`。
- MuJoCo 编译 URDF 时 **STL 必须与 URDF 同目录**(URDF 里写的是裸文件名), 否则 `Error opening file 'XMS5-…_base.stl'`;
  做法是复制 urdf + 全部 `*.stl` 到一个 scratch 目录再加载。

## 5. 验收: 像素级, 不靠“接口有数据”

- 判据三件: `TRAJ.plan.length` == 点数 · 三维 canvas 里目标色像素 >1000 · 播完 `RTRAJ.fi == n-1` 且 HUD 显示
  「走完 N 帧 · … 真机没动」。
- 取像素做法: 把 canvas `drawImage` 进 2D 画布再 `getImageData` 统计目标颜色(如 cyan 0,229,255)像素数。
- ⚠️ 接口返回 44 个点 **不等于**画出来了(可能被 `planVisible` 拦掉); 只说「接口有数据」会被现场当场否掉。
- ⚠️ 用无头浏览器点按钮时, `browser_click` 可能落在被遮挡的位置而“看起来没反应” —— 判据用
  `document.getElementById('bOrbit').click()` 复测一次, 再下结论; 真页面上 `onclick` 已绑定就算可用。
