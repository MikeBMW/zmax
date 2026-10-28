---
name: autonomous-exploration-trajectory
description: "Use when 规划自主建图/自主探索的路线轨迹并要三维视图看。"
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [exploration, frontier, astar, mapping, threejs, zmax]
    related_skills: [zmax-state-3d-mobile, depth-cloud-map-service, phone-video-3d-map-app]
---

# 自主探索轨迹规划 + 三维可视化

## When to Use (何时用)
- 用户要「自主建图 / 自主探索」并要一条能看的路线轨迹。
- 要证明探索算法真在跑(覆盖率/航点/路径可复算), 而不是画条示意图。
- 要把轨迹放进三维视图给非开发人员目检。

「自主建图 / 自主探索」在没真机数据时也能先交付**可执行的规划器 + 能看的 3D 轨迹**,
不要拿一条手画的假曲线糊过去 —— 轨迹必须由真算法在真场景布局上跑出来,
每条数字(覆盖率 / 航点数 / 路径步数)都能复算。

## 算法定式: frontier + 信息增益 + A*

Yamauchi 1997 那套至今最好用: 可解释、无训练、给任何阈值都能说明白为什么选那一点。

| 步 | 做法 |
|---|---|
| 地图 | 栅格 `int8`, `unknown=0 / free=1 / occ=2`。2cm 格够用, 0.64×0.60m 台面 ⇒ 32×30 |
| frontier | `free` 且 8 邻域含 `unknown` 的格 —— 已知世界的边界 |
| 聚类 | frontier 格 BFS 成簇, `min_size=3` 滤噪 |
| 增益 | `gain = 簇内 unknown 邻居数 / (A* 路径距离 + 1)` |
| 选点 | 取 gain 最大簇的代表格(离簇几何中心最近的 free 格), **不是质心** (质心常落在障碍里) |
| 路径 | A* 8 邻域, 对角 `√2`, **禁切角** (对角两侧任一是 `occ` 就不许斜走) |
| 观测 | 沿路径**每格都 reveal 一次**(真实机器人边走边看), FOV 扇形内 `unknown→free`, 障碍后不可见 |
| 终止 | 覆盖率 ≥ 目标, 或连续 3 轮无新格(收敛), 或无可达 frontier |

覆盖率分母取 `free + unknown`(占用格不计), 否则围栏/夹具会把分子分母一起缩水。

## 场景必须用真布局

随机障碍跑出来的轨迹没有参考价值。光模块产线工位用真几何:
工作台 0.64×0.60m + 料盘(左) + 孔位盒(右, 对应 `HOLE_MOUTH` 一带) + 2 处工装夹具(必须绕开)。
坐标从引擎抄, 不拍脑袋 —— 与 `zmax-state-3d-mobile` 同一口径。

## 🔴 测试用例自己造错, 会连报两次假失败

写 A* 绕障用例时把墙横竖搞反, 路径实际**根本没被挡**, 直线过去是对的, 判据却 FAIL:

- 第 1 次 `g2[1:10, 6]=OCC` —— 以为「i=6 整列墙」, 实际是「j=6 处一道竖线」;
- 第 2 次 `g2[1:11, 6]=OCC` —— 同一个错, 只改了范围没改轴。

numpy 是 `[行 i, 列 j]`。要「i=6 整列挡住、j=10 留口」= `g2[6, 1:11]=OCC; g2[6,10]=FREE`。
**判据 FAIL 时先怀疑用例**: 打印墙的实际占用格和路径的 max/min 坐标, 而不是急着改算法。
同族陷阱: `reveal()` 用 `atan2(dj, di)` 而栅格是 `(i,j)` ⇒ 角度与轴序必须对齐,
否则视锥朝错方向, 自检里要有一条「反方向仍是 unknown」的负判据。

## 三维视图

- 单文件 HTML, **数据内联**(`__DATA__` 占位替换), 双击/手机都能开, 不依赖本地 JSON。
- **Three.js r128**, 不用 0.157+ —— 后者删了 `examples/js/OrbitControls.js`, 404 直接黑屏。
- 坐标: 栅格 `(i,j)` → `(i*CELL-CX, 高度, j*CELL-CY)`, 减半宽让台面居中。
- 一眼看懂的四层: 逐格地面着色(`occ` 立成小方块有立体感) · 轨迹按时间 HSL 渐变 ·
  航点球 + canvas 序号牌(`S`=起点) · 每个航点的 FOV 扇形(线框 + 极淡填充)。
- 按钮只做**显示开关**(轨迹/视锥/自动旋转/俯视), 不造假交互。
- `THREE` 未定义要 try/catch 弹可见错误, 别留黑屏让人猜。

## 自检要覆盖

地图尺寸/占用数 · A* 绕过末口且不穿障碍 · 目标在障碍内 ⇒ 无路径 · frontier 聚簇且都在 free 边界 ·
观测只揭示朝向一侧 · 覆盖率单调不降 · 最终覆盖 ≥80% · 路径全在非占用格 · 航点坐标 == 栅格×CELL。

## 交付口径

汇报写清算法名与实测数(如 15.1%→96.4%, 6 轮, 7 航点, 54 步), 并说明**这是规划器输出**,
不是真机走过 —— 真机要接底盘/机械臂执行链才有里程与误差可言。

实现: `tools/explore_path_planner.py`(规划+自检), `tools/gui/explore_3d_view.py`(生成 HTML),
输出 `zmax_data/ss_live/explore_traj.json` + `explore_3d.html`。
