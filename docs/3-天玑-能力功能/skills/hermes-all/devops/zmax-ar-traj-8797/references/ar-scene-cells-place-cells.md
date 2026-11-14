# AR 场景元素（插口/料盘/槽位）只有一条改法：fences.json → scene_places_build → 回读 place_cells

页面 🧭 位置细胞 层的东西（tray / slot / socket / station / teach_point / motion_anchor …）**全部**来自
`/api/place_cells`，生成物是 `data/skills/l2_atomic/place_cells.json`（build_tool 写着 "禁止手改"）。
改生成物 = 下一拍被冲掉；改页面 = 只有这一页对。真源永远是下面两份。

## 加/改一个元素的四步

1. **改输入** `zmax_data/ar_rs/fences.json` 的 `items[]`，一条一个 AABB：
   `{"id","type":"box","name","p1":[x,y,z],"p2":[...],"color","enabled":true,"note","at"}`
   🔴 `p1/p2` 是**米制**（台面 1.4×0.8 那种量级）；写毫米 ⇒ 生成物 pos_mm 缩 1000 倍且页面看不出来。
   改前先 `cp fences.json fences.json.bak_$(date +%H%M%S)` —— `zmax_data/` 不入库，没有 git 兜底。
2. **加名字→id 映射** `tools/scene_places_build.py` 的 `FIX_IDS`（另有 `TRAY_IDS`）：
   `"🔌 光模块插孔②·下口(真轨迹插入·示教实测)": "socket.optical2"`。
   kind 由**名字里的关键词**推（含「插孔」→ socket，含「料盘」→ tray）；不映射时落到自动 id，页面/下游按 id 取值的会断。
   同一个元素别改两次名字 —— id 跟着映射走，改名字等于换 id。
3. **重建**（幂等，随时可再跑）: `./gui-venv311/bin/python tools/scene_places_build.py | tail -6`
   输出末尾自带一致性 checks：`socket.fence_vs_page_arrow`、`socket.taught_vs_fence`、`slot.inside_parent_tray`、
   `sim.chassis_vs_page` —— **全 ✅ 才算真源对上**；出现新 ✖ 说明你加的盒子与示教/页面箭头不自洽。
4. **回读两处才算交付**：
   - 服务端: `curl -s http://127.0.0.1:8797/api/place_cells` → `counts.<kind>` 与 `cells[].pos_mm/size_mm`
   - 页面侧: 控制台 `PC.doc.total` / `PC.doc.counts.<kind>` / `PC.doc.built_at`（页面读的是自己那份缓存，
     必须点一次「🧭 位置细胞」重新拉，否则你看的是旧数据；`PC.n` 恒 0，别拿它当判据）

## 「两个插口」怎么定，别按轨迹段数猜

真实 215 点轨迹里**两段插入（20~44、91~115）插的是同一个口**：两段 X 最深都是 817.8，Y 差 0.4mm。
真正的两个口是**上下两个 Z**：

| 口 | 真源示教点 | 生成物中心 (mm) |
|---|---|---|
| 上口 | 光模块插入口 766.5/228.2/278.0 → 光模块插入点 813.5/228.1/277.5 | 790.5 / 228.0 / 278.05 |
| 下口 | 插入口_拖拽1020b 761.3/228.7/189.2 → 插入到位_1020c 811.6/230.6/184.3 | 786.45 / 229.8 / 187.55 |

⇒ 判定「一个口还是两个口」看 **Z 差（约 90mm）**，不看轨迹插入了几次。
下口盒子的口径照抄上口（y ±7.2mm、z 高 9.5mm），x 跨「口→到位」，`note` 里写明两个示教点坐标。

## 孔位**数量**改（4 个 → 实际 2 个）是三处联动，不是只改场景盒

孔位在**段表侧**另有一份真源，比场景盒更容易漏；只改 fences 会让插拔全流程仍按 4 孔排产。

1. `config/points/cell_points.json` 的 `holes[]`（`mouth`/`insert`，mm）是 `cycle_plan` 的唯一输入。
   `mouth` 取「插入口」示教点、`insert` 取「插入到位」示教点；上下口靠 **Z 差**区分。
   🔴 坐标只认示教/围栏实测 —— 现场只有上下两个口，原来那 4 个孔（全 z=278、Y 每 -60）是**按等距补出来的**，
   用户会直接说「现场没有这一排」。凡是「对称/等距补出来」的孔位槽位，一律当 bug 处理，先问真值在哪。
   ⚠ `config/points` 是软链到数据目录 ⇒ `git add config/points/...` 报 `beyond a symbolic link`；
   备份和改动都按真实数据目录做，代码库里没有这份文件（改完口头交代位置，别声称已提交）。
2. `src/lerobot/engineering/nodes/cycle_plan.py` **与** `src/lerobot/middleware/nodes/impl/cycle_plan.py`
   是两份同源实现，**必须同时改**。原来写死 4 孔，改孔数会崩或跑空轮：
   `pair_holes={1:[HOLES[0],HOLES[1]],2:[HOLES[2],HOLES[3]]}`、`occupied[1 if h["id"]<=2 else 2]`、
   `insert_mods=[1,2,3,4]`、`while queue or occupied[1] or occupied[2]`、`pair_turn=1 if pair==2 else 2`。
   一律改成按 `len(HOLES)` 自适应：`pairs=[HOLES[i:i+2] …]` + `pair_of` 映射 + `any(occupied.values())`
   + `pair_turn = 1 if pair==len(pairs) else pair+1`。
3. 页面 `drawInspHoles()` 的孔高可能写死 `cy=278/1000` ⇒ 下口被画到上口那一层。改成每孔 `h.mouth[2]/1000`，
   孔内模块同样用各自 z，夹具底板按所有孔的 Y/Z 范围包。

判据（三处一起核，缺一条就是假完成）:

```bash
curl -s http://127.0.0.1:8797/api/sim_insert | python3 -c "import json,sys;print(len(json.load(sys.stdin)['holes']))"
# 页面: INSP.holes.length 同值; plan 里出现的 hole 编号只在实际集合内
```

段数/节拍要跟着变（实测 4 孔 399 段 → 2 孔 392 段、11.28 s/件、UPH 319）；只换坐标不改孔数，节拍不变就是没生效。

## 元素的「位置」与「尺寸」真值分级不同，别混着答

- **位置**: 示教真值可直接进场景（slot6 `647.4/255.9/110.1`，与抓取位实测差 6.1mm 交叉验证）。
- **尺寸**: 只有近距离俯拍（拿已知 49mm 槽距当标尺）或标定后投影预标注才有毫米级。
  以下三条实测全部 0 命中，**是分辨率/密度问题，不是算法问题**，不够就当场说做不了、别写检测器烧时间:
  顶摄 2.6mm/px 量 45mm 槽位（±5mm）· 98k 点铺 1.4×1.8m ≈ 3mm 间距量 10mm 级孔 · 640×480 臂上机位量 49mm 槽距。
- 🔴 **拿已有外参投影前先判它过期没**。`models/handeye_state.json` 那份 T_cam2tool（14 视图、残差 0.06mm）
  在**相机换过/重装过**之后就是废的 —— 残差是当年那次的历史指标，不含「相机走了」这件事。
  判据: 把已知示教点投到一帧实拍图，投影像素必须落在画面里真实的那个物体上；落在暗空区（灰度 7~14）
  而目标物体在另一侧亮区（145~157）⇒ 外参失效。失效就重标，**别拿它算尺寸、做可见性表、生成预标注** ——
  它不会报错，只会给出一整套看着合理的假数据。

## 先看 gaps 再动手

`/api/place_cells` 的 `gaps[]` 直接告诉你这批元素缺什么（如 `tray_grasp_pose_missing`：左盘/下盘/废料盘
没有任何号位示教 ⇒ 摆盘/下料只能用几何中心 + 现算姿态，不是示教真值）。用户问「为什么 AR 里这个盘不能用」时，
先翻 gaps，别翻渲染代码。

## 别把「位置细胞」和「场景库」搞混

- 位置细胞 = 上面这套（`ar_rs/fences.json` → `l2_atomic/place_cells.json`），服务 ar3d 页的坐标层/围栏/插口。
- 场景库 = `data/scene/scenes/<ID>/objects3d.json`（`tools/scene_registry.py` 生成），服务 studio 的 3D 视图/编辑器。
  同一台设备在两边各有一份坐标，改了一边另一边不会跟着变 —— 用户说「3D 里看不到」时先问清是哪个页面。
