---
name: zmax-phase-traj-ar3d
description: Use when 相位轨迹渲染到 ar3d 或仿真回放。
---

# 相位轨迹 → ar3d 渲染与仿真回放

## 真源

`http://192.168.23.50:8815/api/geo` — Z-MAX SE(3) 分层几何看板。返回：
- `frames`: 每帧 `{p:[x,y,z]mm, q:[w,x,y,z], n:[法向], phi, spd, s_mm}`
- `states`: 相位段表 `[{i0,i1,name}]` — "有相位状态"的唯一依据
- `n` / `len_mm` / `set`

demo 集 = 251 帧 / 5888mm / 26 相位段，停留相位 13 个：初始点 → 槽2抓取 → 扫码 → 插入到底 → 等待检测 → 钩拉环解锁 → **金手指检测1(110-112) → 金手指检测点2(158-160)** → 侧面点1(177-179) → 侧面点2(182) → 侧面点3(194-196) → 侧面点4(219-221) → 下盘放料。

同机 `:8815/api/se3` 给实时 TCP + 最近点 + phi；`:8815/api/stop`。

## 渲染到 8797 /ar3d（不改后端、不重启）

8797 是 systemd 服务，**不要自己重启**（红线）。加接口不是唯一办法：

`_traj_named("map")` 优先读 `zmax_data/ss_live/explore_traj_fenced.json` 的 `pts`（米制）。
把 8815 frames 的 `p/1000` 写成这个文件的 `pts` + `note`，前端点「轨迹3」就能看见。先备份原文件（那是建图轨迹）。

前端按 note 改名：在 `loadNamed()` 的 `NAMED[k]=d.pts` 之前插
`if(k==='map' && /8815 全流程相位/.test(d.note||"")) d.label='轨迹6 · 全流程相位 …'`。
再改按钮文字（`id="t3"`）并在 `window.addEventListener('load')` 里自动 `loadNamed('map')` —— 用户要的是「一打开就看得见」，不是「渲染好了你自己找按钮」。

## 仿真回放（真机不动）

通路：`fetch('/api/orbit_frames')` → `rtrajPlayJoints(d)`。
`/api/orbit_frames` 读 `zmax_data/capture_plan/{port_sweep_joints,port_orbit_joints}.json` 里 mtime 最新那份。

生成脚本 `tools/phase_traj_ik2.py`（MuJoCo IK），三条硬规矩：

1. **四元数顺序是 `[w,x,y,z]`**。按 `[x,y,z,w]` 解会让工具 z 轴差 140°，IK 33% 崩。
   验证：用真机当前 `rx,ry,rz` 反推 R 去比 — `[w,x,y,z]` 差 5.2°，`[x,y,z,w]` 差 140.5°。
2. **IK 每步必须限幅**（`max_step≈0.06 rad`）。不限幅会在解支间跳，实测关节角冲到 445°、单帧跳 180°，播出来手臂乱翻。不收敛的帧 **沿用上一帧关节角**（画面停住），不要插值到未来解。
3. **`t` 字段必须是秒**（`i/25`）。原样放 8815 的 `s`（弧长归一化 0~0.93）会让 372 帧在 0.93 秒内闪完 —— 现象就是"点了回放什么都没看见"。

残留解支跳变（单帧 >15°）在关节空间插过渡帧，每帧 ≤6°，位置同步线性插值；播到那里会看到手腕"转一下"，属正常。

## 真机 vs 仿真：两个按钮，永不可混

- `bRTraj`「▶ 右臂跑真实轨迹」= `runRealTraj()` → `POST /api/arm/step_traj` → 容器 `arm_step_traj.py` MoveAbsJ，**真机真的动**。
- `bSimTraj`「▶ 仿真回放·不动真机」= fetch `/api/orbit_frames` → `rtrajPlayJoints()`，只驱动三维模型 + 推 8802。

**坑**：`rtrajUI(on,txt)` 原来改的是 `bRTraj`，把文字写成「只仿真·不动真机」—— 文字说不动、点下去真动。实测因此把真机从 632,230,309 走到 673,194,214。改后 `rtrajUI` 只改 `bSimTraj`，`bRTraj` 文字永不被覆盖。

真机回放停法（三步都要做）：`POST :39071/stop`（moveReset）→ `sudo kill -9` 掉 `sudo docker run` + `python3 /repo/arm_step_traj.py` → `traj_step_state.json` 置 `running=false`。只停一处不够：桥停了执行器还会发下一点。

## 围栏盲区（碰撞的真实原因）

`precheck_move.py` 只算 `enabled=true` 的围栏。台账里 `F668833 检测设备`
`x 711.7~843.7 / y -91.4~301.6 / z 0~340` 是 `enabled:false` —— 预检完全不看它，
却报「PASS 最小余量 98.1mm」（那只是对 4 个料盘的余量）。
215 点录制轨迹有 **50 点**落在该盒内（(763,228,190)、(790,227,191)、(811,228,189)、(815,227,200) 等）。
**任何轨迹下真机前，按启用围栏 + 未启用围栏双份比对**，别只信 precheck 的 PASS。

## 已归档资产

`zmax_data/traj_phase/phase251_20261124/`
- `geo_raw.json` 8815 原始 251 帧
- `joints_372f.json` IK 后 372 帧回放数据
- `MANIFEST.json` 来源/相位表/IK 口径/使用方式
