# 场景 3D 元素坐标的唯一真源（位置细胞库）· 2026-11-09

老倪：「这些 3D 元素的坐标在哪里？状态空间工程的参数中心，应该记录 3D 场景元素的精确坐标；
ar3d 是可视化的窗口，但是工程配置中，要有所有的配置坐标；L2 层的记忆库，要记录所有这些位置信息，
与大脑神经元的位置细胞同样作用。」

## 一、改造前：坐标散在 5 处，各说各话

| 谁 | 文件 | 条数 | 单位/坐标系 | 谁在用 |
|---|---|---|---|---|
| 工装几何（料盘/42 槽/插孔/检测设备/横梁） | `zmax_data/ar_rs/fences.json`（type=box） | 51 | 米 / base_link | AR 页显示、围栏避让 |
| 示教点位台账 | `data/skills/l2_atomic/taught_points.json` | 69 | 米 / base_link | L2 技能、8793 点位台账 |
| 标记模式空间点 | `data/skills/l2_atomic/space_points.json` | 8 | 米+quat / base_link | 安全区、轨迹 |
| AOI 活数据 | `zmax_data/ar_live/ar_aoi_live.json` | 11 个点名（只有 `末端` 给全 xyz） | 米 | 信号分析、AR 叠加 |
| 结构件常量 | `tools/web/tcp-ar.html`（`CHS`/`TAB`/`FLR`/`TCAM`/axis1H） | 4 | 米 / base_link | 只在页面里画 |
| 仿真场景 | `zmax_data/ar_mujoco/ar_env.xml` | 6 | 米 | 8802 渲染（**不是真值**） |

后果：同一个东西两套数（例：插孔包络 767→814 与页面箭头 767/814 靠人肉核对）；「号位」和「槽」
被当成同一件事（实测号位比槽心偏 +156mm，那是夹爪进给方向，不是坐标准不准）；页面常量不在任何配置里。

## 二、改造后：一张表 + 一个构建器 + 一个运行时

- 库：`data/skills/l2_atomic/place_cells.json`（133 枚细胞 · 14 类 · 90KB；与 `taught_points.json`/`space_points.json`
  同目录 = L2 记忆库本体。该目录被 GUI 工程 `.gitignore` 的 `data/` 排除 ⇒ 属数据不入代码库，符合「大文件/数据不进库」口径）
- 构建：`tools/scene_places_build.py`（从上面 5 个测量真源汇总，**禁止手改库**；`--check` 报漂移）
- 运行时：`tools/scene_place_cells.py`（`fire` / `contains` / `anchor` / `selftest`）

### 细胞字段

```
id          稳定主键，一物一 id（撞车直接 assert 失败，防静默覆盖）
kind        tray|slot|socket|fixture*|structure|sensor|station|approach_pose|motion_anchor|teach_point|live_probe
pos_mm      base_link 毫米（入库统一换算，禁止再混米/mm）
size_mm     盒体尺寸；点类为 null
parent      槽 → 料盘
slot_ref    号位 → 对应槽（抓取位姿与几何中心的对应关系，写进数据不靠猜）
tags        能力视角标签（抓取/放置/插入/检测/对位/示教…）
prov        出处文件+键 + 精度(measured|measured_tcp|design|derived) + 测量时间 + 原始备注
```

### 位置细胞怎么"发放"（L2 用）

`fire(p)`：每个细胞按高斯场 `w = exp(-½·(d/r)²)` 同时发放，`r` = 该细胞自身尺度（盒体取半对角线，
示教点取 20mm）。不是一个"最近点"，而是「4 号槽在亮，3 号槽也有余量」——正好对应位置细胞的群体编码。

`anchor(p)` 给出 L2 定位口径的一次完整回答：

```
python3 tools/scene_place_cells.py anchor 516,347,109
→ tray=cell.tray.right · slot=槽4(26.4mm) · grasp=slot4 [647.36,353.93,110.52] · 插孔 324.7mm
```

即：检测到一个 3D 点，就能同时得到「它在哪个盘、第几个槽、该槽示教抓取位姿是哪条、离插孔多远」。

## 三、验收（全部真跑）

构建期对拍 6 条全过：

```
✅ socket.fence_vs_page_arrow   围栏 x[767,814] vs 页面口767/到位814 mm
✅ slot.inside_parent_tray      42 槽全在所属料盘盒内
✅ sim.gold_module_in_scene     仿真模块 [518.8,347.8,112.1] → 槽4
✅ sim.chassis_vs_page          页面箱体高 750 vs 仿真 650（仿真无轮，已知简化 20mm）
✅ taught.slot_approach_offset  号位-槽 偏移均值 [156.1,1.9,-7.5]mm · 7 个号位最大偏离 3.8mm
✅ socket.taught_vs_fence       围栏 x[767,814] vs 示教 口766.5/到位813.5 mm
```

运行时自检 10/10（`python3 tools/scene_place_cells.py selftest`），另加 42/42 槽心 anchor 回自身。

## 四、缺口（写在库里 `gaps`，不藏）

1. **7 个槽没有示教抓取位姿**：槽8~14（右盘后 7 位）无号位 ⇒ L3 不能自动抓。
2. **左盘/下盘/废料盘零号位示教** ⇒ 摆盘/下料只能用几何中心现算姿态。
3. **`ar_aoi_live.json` 10 个点名只有 `.x`**（金手指点1/2 · 侧面点0~3 · 准备点 · 安全点1 · 空间点1/7），
   缺 y/z ⇒ AR 页这几点走台账静态值，不是实时值；要实时得补写入端。
4. **箱体/实验桌/地面只有设计尺寸**（页面常量），无实测 ⇒ 碰撞判定够用，mm 级标定要一次实测。

## 五、维护口径

```bash
python3 tools/scene_places_build.py            # 改了围栏/示教点/页面常量后重生成（入库）
python3 tools/scene_places_build.py --check     # 只对拍，不写；报 id 变化与位移
python3 tools/scene_place_cells.py selftest     # 运行时硬判据
```

- 页面（ar3d）：**已接**（r91，2026-11-09 16:16 重启 8797 上线）。端点 `GET /api/place_cells`
  （`?stats=1` 只回摘要 · `?kind=slot` 过滤 · `?q=516,347,109&k=3` 查高斯发放），每次热读磁盘 ⇒ 改库不用重启。
  左栏「🧭 位置细胞」层实测：133 枚 · 画盒 53 个 + 点 25 个（7 号位 + 10 站点 + 8 空间点）· 库龄秒级 · JS 零报错。
  动作锚点（motion/tuning 共 52 个）故意不画 —— 会糊屏，要看用 `?kind=motion_anchor` 取数。
- 真相进出只走构建器：新元素 → 先在它该在的测量真源里出现（围栏/示教/测量文件），再重生成。
  不要在页面或技能里手打坐标。
