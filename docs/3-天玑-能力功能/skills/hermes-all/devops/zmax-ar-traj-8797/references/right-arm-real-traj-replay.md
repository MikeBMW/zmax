# 让仿真右臂“按真实轨迹走一遍”

页面里三个按钮, 数据同源(`poses.jsonl` 的 6 轴关节角真值), 只动仿真:

| 按钮 | 行为 | 用途 |
|---|---|---|
| `bRTraj` 📍 右臂跑真实轨迹 | 按时间连续回放(1× 真实时间 43s, 时间轴线性插值) | 看整条轨迹“怎么跑” |
| `bSyncStep` ⏭ 同步操作 + `iSyncN` 输入点数 | **一点一点走**: 每点 smoothstep 420ms 到位 → dwell 300ms 停住 → 下一点 | 逐点校位/对数, “输入3点就走3点” |
| `bPlant` 🏭 全流程 UPH | 本地时钟跑节拍, **右臂关节角直接取内嵌真轨迹帧** | 看连续生产时的真实姿态 |

## 关节角真值回放（三个按钮共用基础）

位置 IK 只匹配 xyz，姿态由求解器自己挑 ⇒ 真机那 952° 累计转动、J4 −8°→247° 的翻面全会丢。
`tools/real_traj_joints.py` 从录制导出回放帧（双闸抽稀 8mm/3°、只留运动段、静止压缩），215 帧。

## 仿真臂的姿态源头: 只有两个合法来源

1. **跟随真机 (`MIRROR`)**: 10Hz 读 `/api/tcp` 的 `joints`(6 轴弧度) → `PREV.q` → `mjPushQ`/`mjPushQForce`。
   帧龄 >1.5s 直接丢弃（宁停帧不骗人）。`MIRROR.on` 期间 `plantStep` **禁止写 `PREV`** —— 否则 60Hz 的
   `ar_cmd` 合成段表(14 孔计划)会把真机位姿盖掉, 用户看到的就是“仿真臂不按真实轨迹跑”。
2. **真轨迹帧 (`traj215`)**: 本地全流程分支里 `PREV.q` 直接取内嵌 `rtrajData` 的帧，按 `simT % T` 线性插值，
   不再用 `plantAt()` 的 IK 近似线。`plantAt()` 仍然要跑（节拍/计数/料盘状态），只是**姿态由轨迹帧覆盖**。
   停止后自动切回跟随真机。

判据（缺一不可）:
- `PREV.src === 'traj215'`，且 `PREV.q` 与 `simT` 处轨迹帧插值 **逐位相同**（实测 maxErr = 0）；
- `trajT` 随时间推进（3s 采样 8.6→10.7→12.8s），末端目标沿录制路径移动；
- 点停后 `PREV.q` 与 `/api/tcp` 的 `joints` 逐位相同（回到跟随真机）。

## 关键坑

1. **8797 只白名单服务 `tcp-ar.html` 本身**，`/xxx.json` 全 404 ⇒ 数据必须**内嵌**页面：
   `<script id="rtrajData" type="application/json">…</script>`，由 `real_traj_joints.py --embed` 写入。
2. **内嵌块在页面末尾** ⇒ 加载时读不到（DOM 还没到）⇒ 必须**惰性读**（`ensureTrajJoints()` 在点击时才取），
   不能加载时读一次缓存 null。函数声明会提升，`plantStep` 里提前调用也安全。
3. **回放期必须 ~30Hz `mjPushQForce()` 抢 8802 时间片**，否则多开 `/ar3d` 页会两个写者互斗、臂在两姿态间跳。
4. 各回放模式**互斥**：开同步操作/本地全流程前先 `rtrajStop()`，否则两个 rAF 同时改 `PREV.q`。
5. 点数上限取数据帧数（215），运行时 `inp.max=max` 自动设，用户填 999 也不越界。
6. **“在跑”的唯一判据是 `PLANT.local`**。`PLANT.on` 会被状态空间自动跟随一起置 true，用它判断 ⇒ 点一下按钮变成“停”，
   这是“点了不动”的头号原因。连带三处必须同时改：`plantToggle()` 判 `PLANT.on && PLANT.local`；
   `autoMirrorMaybe()` / `ssFollowStart()` 每 100ms 会把 `local` 打回 false 并把 `PREV` 交还 `ar_cmd` ⇒ 开头加
   `if(PLANT.on && PLANT.local) return;`；`plantStep()` 里 `if(SSMODE.on && !isAR) return` 会永久挡本地时钟 ⇒ 改成
   `if(SSMODE.on && !isAR && !PLANT.local)`。改一处无效，四处是一组。
7. **改完必须 bump 版本戳**（页头 `r95→r96…` 与 `bld`），并用 `?v=rNN` 重载验证：不 bump 会看到旧 JS，
   会误判“改了没生效”。

## 验收口径（必须看到的）

- 页面：`SYNC.i` 逐点递增到 N−1、`ph` 在 move/dwell 间切换、文案报“已到第 k/N 点” → “已走 N 点”。
- 8802 侧：`zmax_data/ss_live/ar_mj_q.json` 的 `R` 与页面末帧关节角（度）一致 ⇒ 仿真真到位，不是只改前端。
- 真机零指令：不写执行开关、不调 8793 授权。
