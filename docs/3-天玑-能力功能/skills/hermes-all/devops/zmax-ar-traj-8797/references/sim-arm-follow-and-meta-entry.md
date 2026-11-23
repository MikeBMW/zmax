# 仿真臂跟真机 / 回放元任务入口

适用: 在 8797/ar3d 页新增或修改「让仿真右臂跟随真机」的入口、轨迹回放元任务、以及验证它们真的生效。

## PREV.q 只有一个主驱动: MIRROR

- `MIRROR` 每 100ms 拉 `/api/tcp` 的 `joints`(真机关节角, 50Hz 采样)写 `PREV.q` + `mjPushQ` + `drawVR`。这是「仿真臂画在真机那一格」的唯一正规路径。
- 新增任何臂驱动都要显式声明让位关系: `rtrajPlayJoints` 入口 `mirrorStop()`、结束 `mirrorStart()`。两路同时写 `PREV.q` 会互踩, 画面在两侧反复跳。
- **不要为跟随另起轮询器**。`syncArmFollow()`(自己拉 `/api/tcp`, 给「同步操作」用) 与 `MIRROR` 职责重叠; 跟随真机复用 `MIRROR`, 多一套定时器只多一个抢写者。
- `MIRROR` 内部有 `PLANT.on && PLANT.local` 闸: 本地全流程在跑时它主动让位给本地仿真。新增模式要沿用同一套判断, 不要另写一套。

## 页面「不跟真机」先查有没有人挂跟随

- 三维臂跟真机的能力(函数)存在 ≠ 在跑。`/ar3d` 实测打开后 `SYNCARM.follow=false`、`PREV.on=false`、`PREV.q=[]` —— 页面里没有任何初始化路径去调跟随，看着「页面对不上真机」其实是根本没启动。判据只认 `PREV.on` 与 `PREV.q` 六轴对 `/api/tcp` 的 `joints` 逐位相等，不认画面上「臂好像在动」。
- 优先复用页面已有的跟随主驱动(有 `MIRROR` 在跑就直接用它)；`/ar3d` 这类独立页若没有任何跟随入口，再挂 `syncArmFollow(true)`，并每 2s 兜底重挂一次(`!SYNCARM.follow` 才挂) —— 别处初始化会把它关掉，用户刷新一下就又不跟了。
- 跟随开关自身不带陈旧闸：`syncArmFollow` 里的 `d.ts` 在 `/api/tcp` 回包里**不存在**(字段是 `t` 字符串 + `age_s` 数值) ⇒ `age=0` 永远通过。要判陈旧就自己读 `age_s` 与 `stale`。

## 页面变量是 let 声明 ⇒ 不要用 window.X 判状态

- `PREV` / `NAMED` / `SHOW` / `TCP` 都用 `let` 在顶层声明：后续 `<script>` 能按名字直接读写(同一全局词法环境)，但它们**不是 `window` 的属性**。写 `window.PREV && PREV.on` 会永远 false —— 实测因此把「跟随中」写成「未跟随」、把轨迹点数写成 0，误判成功能没生效。
- 正确写法: `typeof PREV!=='undefined' && PREV.on`；验证同样按名字读，别走 `window.`。

## 把「正在学的新轨迹」画进三维视图

- 页面画轨迹的现成通道是 `NAMED[key]` + `NAMED_ON[key]`：点集是**米**的 `[x,y,z]`，`drawNamedVR` 在每次 `drawVR` 里无条件遍历 `NAMED_ON`(长度≥2 才画)。所以外部轨迹只要塞 `NAMED['follow']=pts; NAMED_ON['follow']=true; NAMED_COL['follow']='#22d3ee'; SHOW=true; drawVR()` 就出现在画面里，不必碰渲染管线、也不必重启 8797。
- 数据源走跟随服务(8817)的 `/session.json`(含 `path[].A_mm` 与 `cum_mm`)，2s 拉一次；`A_mm→/1000`。点数 <2 时不要建层(会画出一个点)。
- 页面是**热读**的(`/ar3d` 每次请求都从磁盘读 `tools/web/tcp-ar.html`) ⇒ 改显示一律改 HTML、刷新即可，不需要重启 8797；只有改 `tcp_ar_server.py` 里的接口/白名单才要重启。
- 🔴 **验像素必须按 id 取画布**: 页里有 4 个 canvas —— `#vid`(1280×720 视频) / `#ov`(640×480 叠加) / `#loupe`(176) / `#vr`(980×577 三维)。
  `document.querySelector('canvas')` 拿到的是 **#vid**, 在它上面数青色像素永远是 0 ⇒ 会误判"轨迹层没画出来"。
  取 `document.getElementById('vr')`; 注入 4 点测试线前后比青色像素差(实测 +115px)才算"画得上"。
- **跟随状态要画在画面上**: 左上角常驻 `position:fixed` HUD, 三行 = `跟随真机 · 跟随中/未跟随` / `TCP x / y / z mm` /
  `真值帧龄 x.xx s` + `跟随轨迹 N 点`, 边框按 `stale` 绿/红。用户是看画面判状态的, 只报"代码改了"他会反复问"到底跟没跟"。

## 「对不上」的根因几乎总是时间尺度

- 独立回放按录制时长 `dur_s`(如 215 点 / 42.85s, 100% 速度连续)从头播; 真机 `traj_loop` 是逐点循环(20% 速度 + 每点驻留 dwell)。两者差数倍, 帧号永远对不上。
- 结论: 独立回放只能算预览, UI 上要标清; 真机在动时必须用跟随模式。用户说「右臂要对应上」就是这个含义, 不是让你调回放速度。
- **「对应上」的判据是数值相等, 不是看着在动**: `PREV.q` 六轴与 `/api/tcp` 的 `joints` 逐位相等(采样时刻差 ~0.03 rad 内可接受)。只报「右臂在动」等于没验。
- 跟随画的是真机**真实关节角**, 不是轨迹表里的点。真机停在两点之间时仿真也画在两点之间, 这是对的, 不要「纠正」成吸附到最近轨迹点。

## 两种模式并列且互斥

- `▶ 回放`(独立 215 点匀速) / `🎯 跟随真机`(MIRROR + 左臂冻结), 共用一个 `⏹ 停`(内部 `rtrajStop(); rtrajFollowOff();`)。
- 启动一方必须停另一方: `arTrajReplay()` 开头 `rtrajFollowOff()`; `rtrajFollowOn()` 开头 `RTRAJ.playing=false` + `cancelAnimationFrame`。
- 按钮态靠 `RTRAJ.playing` / `RTRAJ_FOLLOW.on` 分别高亮, 两者不会同时亮。

## 左臂冻结

- `larmFreezeOn(LARM.q)` 拍的是当时的 FK 快照(`LARM.holdQ/holdFK`), 之后右臂怎么动左臂都不跟。
- 左臂无自身位姿时默认照抄右臂 ⇒ 冻结在右臂**当时**位置。所以左臂 tool1 与右臂 tool1 重合不是 bug, 是「冻结在右臂那一刻」。验证冻结要跨时间对比左臂自身前后值, 不能拿它和右臂比。

## 左仿真臂去某个引导位姿 (IK 求解口径)

- 左臂没有控制器，它的“到位”只能靠页面 IK：`ikTool1(target, seed)` 是**位置**解，可信(实测 0.01~0.2mm)；
  `ikTool1Pose(target, seed, Rdes)` 是 6 维解，在本页 URDF 上**不可靠**(拿右侧已知目标做控制组也偏 330mm) ⇒
  别拿它当“姿态也对了”的证据。
- **种子必须是真机示教录制的抓取关节角**(`zmax_data/rokae_sdk/real_traj_absj.json` 里抓取帧的 `q`)，
  且只接受 `max|Δq| ≤ 0.5rad` 的解。用“看起来自然”的空想种子、或按“工具轴朝下”挑解，
  会选出大关节角姿态 —— 整条臂躺倒(用户只会说“左臂怎么躺下了”)。
- 换目标槽后要重跑一次；判据两条同时看: FK tool1 与目标点差 <1mm **且** Δq(相对种子) ≤0.5rad。
- 解完必须 `larmFreezeOn(q)`，否则下一拍它又照抄右臂；状态写 `window.__LARM_GO__`(err_mm/dq_seed_rad/fk_tool1_m) 供 console 复核。

## 元任务「做完」的判据

- **有可点击入口才算交付**。只在元任务列表里渲染一行只读文字(`document.querySelectorAll('#mtBox button').length === 0`)不算做完。
- 用户问「做完了么」时先数 `#mtBox` 里的 button 并打印它们的 `onclick` 属性, 不要用 innerText 里出现过元任务号来交差 —— 元任务清单里本来就会列出全部元任务名。
- 元任务若与双臂泳道口径不同(如回放单件 vs 泳道 11.28s/件 循环), 单独做一格独立控制条, 不要硬塞进泳道。
- 控制条上要同时给出**执行方式与三个时间量**: `N 点 · X s/点 · Y min/轮 · Z UPH · 另一臂状态`。秒数上百时按分钟显示(`(dur/60).toFixed(1) + 'min/轮'`), 直接印 2352.1s 没人读得出来。

## 生成物对、API 却返回 null: 查字段白名单

- `/api/ar/meta` 是把生成物**逐字段挑选**后透出的, 不是整包转发。`meta_tasks` 的挑选列表里少了哪个键, 前端就是 `null`, 而磁盘上的 JSON 完全正确。
- 症状: 新加的字段(如 `uph` / `s_per_point` / `speed_pct`)在 `ar_meta_tasks.json` 里有值, 接口回来是 null, 页面显示空白。
- 排查顺序: 先直接读生成物确认有值, 再看 `tools/tcp_ar_server.py` 里拼 `meta_tasks` 的那段字典字面量, 缺就补键。改完必须重启进程才生效 —— 这类白名单是启动时读进内存的路径, 不重启永远看不到。
- **重启要原样带启动参数**: 8797 常是手工起的孤儿进程(PPID=1, 不在 systemd 里), 没有 unit 可 restart。停之前先从 `/proc/<pid>/cmdline` 与 `/proc/<pid>/environ` 取出原命令和关键 env, 再照抄重启: `cd ~/zmax && ZMAX_REPO=/home/ubuntu/zmax ZMAX_PLAN_SPEED_MM_S=60 ./gui-venv311/bin/python tools/tcp_ar_server.py >> /var/log/zmax-traj-ar.log 2>&1`。漏了 env 会让规划速度、仓库路径悄悄退回默认值, 症状比服务起不来更难查。

## 浏览器验证: snapshot ref 会在 DOM 重建后失效

- `mtBox` 的内容由 `mtRender` 用 `innerHTML` 重建, 控件是每轮新生成的节点。用快照 ref 点击会「报成功但没生效」—— 点的是已被替换掉的旧节点。
- 复现过: 点击返回 `clicked: @eNN`, 但目标状态变量没变、进度仍是 0。别据此判断「功能坏了」或去改业务代码。
- **可靠的自动验证方式**: 在 console 里用 `document.querySelectorAll('#mtBox button')` 按文本筛出目标, 再 `.click()`; 随后立刻回读状态变量(`playing` / `follow_on` / `frames.length`)与 `onclick` 属性确认绑定存在。
- 判断按钮是否真的在页面上, 用 `#mtBox` 的 `innerHTML.length` 与 `querySelectorAll('#mtBox button').length`, 不要用整页 innerText 里是否出现元任务号 —— 元任务清单里本来就写着全部元任务名, 会假阳性。

## mtRender 的 key 节流

- `mtRender` 用 `cur|i|n|meta_tasks.length|cycle_s` 做 key, 不变就 return 不重画。帧号、进度这类每拍都变的东西塞进去不会刷新, 会冻在某个旧值。
- 进度类更新挂到 `mtTick`(160ms) 上, 直接改 DOM 文本; 状态类(按钮高亮、模式切换)走 `mtRender`, 因为它们是低频变化。
