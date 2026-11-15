# 仿真臂跟真机 / 回放元任务入口

适用: 在 8797/ar3d 页新增或修改「让仿真右臂跟随真机」的入口、轨迹回放元任务、以及验证它们真的生效。

## PREV.q 只有一个主驱动: MIRROR

- `MIRROR` 每 100ms 拉 `/api/tcp` 的 `joints`(真机关节角, 50Hz 采样)写 `PREV.q` + `mjPushQ` + `drawVR`。这是「仿真臂画在真机那一格」的唯一正规路径。
- 新增任何臂驱动都要显式声明让位关系: `rtrajPlayJoints` 入口 `mirrorStop()`、结束 `mirrorStart()`。两路同时写 `PREV.q` 会互踩, 画面在两侧反复跳。
- **不要为跟随另起轮询器**。`syncArmFollow()`(自己拉 `/api/tcp`, 给「同步操作」用) 与 `MIRROR` 职责重叠; 跟随真机复用 `MIRROR`, 多一套定时器只多一个抢写者。
- `MIRROR` 内部有 `PLANT.on && PLANT.local` 闸: 本地全流程在跑时它主动让位给本地仿真。新增模式要沿用同一套判断, 不要另写一套。

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
