# ar3d: 仿真臂=真轨迹位姿 · 引导10点 · 通道=真轨迹 (2026-11-14, r96→r101)

老倪这一串要求有共同内核: **画面上的右臂和线, 必须和真机录下来的那 215 个点同源同数**。
凡是用"合成段表 / plan 段表 / 自己拼端点"画出来的东西, 他都会一句"没对应上"打回。

## 1. 仿真右臂 = 真轨迹位姿 (r96 → r99)

| 阶段 | 错法 | 正确做法 |
|---|---|---|
| r96 | 仿真臂 `PREV.q` 取自 `ar_cmd.json`(状态空间合成的 14 孔段表, 60Hz) | 新增 `MIRROR`: **10Hz** 读 `/api/tcp`(真值来自 `tcp_out/latest.json`) → `PREV.q = joints` → `mjPushQ`/`mjPushQForce` 同帧推 8802; 帧龄 **>1.5s 丢弃** |
| r96 | `plantStep()` 每帧写 `PREV` 覆盖镜像 | `MIRROR.on` 时 `plantStep` 直接 return |
| r98 | 点「全流程 UPH」右臂不动 | 三条路径争变量: `plantToggle` 误用 `PLANT.on` 判"在跑"(自动跟随也会置 true) ⇒ 判 `PLANT.on && PLANT.local`; `autoMirrorMaybe`/`ssFollowStart` 每 100ms 把 `PLANT.local` 打回 false ⇒ 加 early return; `plantStep` 的 `if(SSMODE.on && !isAR) return` 永久挡本地时钟 ⇒ 加 `&& !PLANT.local` |
| r99 | 全流程里右臂走的是 plantAt 解的 IK 近似线 | 本地全流程的 `PREV.q` 改成**真轨迹关节角帧**(页面内嵌 `rtrajData` = `real_traj_joints.json`)按 `PLANT.simT % T` 插值, 与真值 `maxErr = 0` |

判据: `PREV.q` 与 `frames[i].j` 逐位相同(误差 0), 停后 `PREV.q` 又等于 `/api/tcp joints`。
另外「默认不要打开 MuJoCo 同视角 / 点位全关 / 实验桌隐藏」对应 `MJCAM` 默认关、`CFG_ON=false`、`VR.table` 初始 false。

## 2. 肌肉记忆通道 = 真机录制 (real215 桶)

- 工具 `tools/mm_build_from_real_traj.py`: 从 `zmax_data/pose_records/rec_20261111_181020/poses.jsonl`(真时间戳)切 8 段, 写 `data/muscle_memory.json` 的 **`("real215", stage)`** 桶。
- `src/lerobot/skills/muscle_memory.py`: `_load` 允许非数字桶; `get_champ` **real215 优先**, seed 桶兜底, `SS_MM_REAL=0` 回旧口径。
- 三个必踩的坑(已写进 `zmax-muscle-memory` 技能): 录制 ~5.4Hz vs 引擎 dt=0.02(必须 50Hz 重采样); 末帧速度必须置 0(否则 ∑u·dt 多走一步, 实测 5.5mm); 段边界必须在原始时间轴上按几何事件定(否则 135s 空档吞进"接近")。

## 3. 通道(COR-SK01..08) = 真轨迹扫掠包络

`tools/ss_corridor_build.py` 原来取 `plan_long_impl` 的段表(14 孔 × 8 段 = 112 次机动), 轴心与真机轨迹无关。
实测偏离: SK01 531.6 / SK03 603.1 / SK05 679.6 / SK08 **710.8 mm** ⇒ 老倪一眼"通道不对"。

修: `python3 tools/ss_corridor_build.py --real215` —— 轴心改真机录制折线(逐样本, 原地停驻样本**跳过**, 不能塞 1mm 假段否则折线断 1mm/偏差 0.94mm)。
结果: 8 段各 1 条链, 段长与真路径逐段一致(101.2/106.4/160.7/57.8/49.6/491.8/50.0/7.6 mm), 逐点偏差 ≤0.0005mm。

## 4. 引导 10 点 (r101, 老倪最终要的形态)

他说"通道也不对, 变成引导的 10 个点的轨迹" ⇒ **不要画管子**, 画引导:
- 青色折线 = 未来 10 点路径; 每点一个三维小十字(±10mm); 下一个要进的点 = 红色大十字(±26mm); 另加一个 `type:'points'` 项把引导纳入取景(否则会被裁到画外)。
- 一步: 先画引导 → 右臂按真实关节角从 `frames[i].j` 走到 `frames[i+1].j` → 到位后窗口前滑一个点。
- 实测 44 个元素(10 段 + 30 十字 + 3 目标十字 + 1 点列), 引导点与 `frames[i+1..i+10]` 逐位相同。
- 按钮是 `bPst`(运行时 `insertAdjacentElement` 插到 `bRTraj` 后面, 不改 HTML 标记)。

## 5. 命令行侧同源工具

- `tools/pred_corridor_from_traj.py` —— `--n 1` 出下一个点, `--n 10` 出十个点, `--write` 写 AR, `--watch` 1Hz; 游标走完/正在跑时用**最近真机位姿**定位, 走完 214 后自动跨圈接下一件。
- 坑: `fence_store.add()` **自己发 id**, 按 `id` 前缀删不掉自己画的线 ⇒ 必须按**名字前缀**删(`未来母线`/`未来点`, 且它会吃掉名字里的 emoji)。
- 幂等判据: 连跑两次 items 数不变(实测 415 = 388 + 27)。

## 6. 手眼仍卡(2026-11-14 放宽重扫结论)

800 帧 13 字典放宽 ⇒ 4488 条检出, 但 `side_px ≥ 12` 只剩 **78** 条, 其余是纹理误检(3~6px)。
最大一组 `id=0 DICT_ARUCO_ORIGINAL` 13 条/11 游标/side 中位 26.6px ⇒ AX=XB 闭合离散 **535mm / 180°**, 不可用。
结论: **不是参数问题, 是标记太小太斜**。必须实体把板放 D405 正前 30~40cm、占画面 1/3、摆 8~12 个不同姿态再采。

## 7. 改这个页面的自验套路(可直接照抄)

1. `node -e` 对每个 `<script>` 块 `new Function(...)` 查语法(页面混合 HTML/JS, 中文注释多, 靠 brower 报错太晚)。
2. 浏览器 `?v=rNNN` 强制新版本, 读 `PST/FENCES/PREV` 等全局量做数值判据(别只看截图)。
3. 数值判据举例: 引导点 == 真轨迹逐位; 每步元素数恒定说明上一步线已清; 停后 `PST.ids == 0`。
