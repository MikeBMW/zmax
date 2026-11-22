# ar3d「轨迹点」(fences type=points)：清旧画新 + 只读验收 + 按钮红线

ar3d 上除命名轨迹 1~5 外，还有一类 `type="points"` 的围栏元素（fences.json），它就是「把一条录制/回放
轨迹整条画在三维里」的通道（`📍 真实轨迹 N点` 按钮管的就是它）。换一条新轨迹 = 删旧 points + 加新 points。

## 🔴 按钮红线（这条是拿真机动换来的）

- 同一页并存 `▶ 显示轨迹`(`bShow`) / `▶ 执行轨迹`(`bFit`) / `▶ 右臂跑真实轨迹`(`bRTraj`) 三条**不同通道**；
  按文字模糊匹配点按钮（`btns.find(b=>b.textContent.includes('真实轨迹'))`）会点到 `bRTraj`。
- `bRTraj` 的 title 写「只仿真·不动真机」，**但实测点下去真机沿旧录制轨迹动了一圈**（同时容器里有
  `docker run … arm_step_traj.py` 在下发）—— 页面口径与真实执行链不一致，别信 title。
- 铁律：看/查轨迹一律走只读（`GET /api/fence` + 画布像素）；要动按钮先
  `[...document.querySelectorAll('button')].map(b=>[b.id,b.textContent])` 把 id 打出来，带
  `▶ / 执行 / 右臂 / 播放 / 回放` 的一律视为会下发。停不住时见 `rokae-sdk-motion-semantics`
  的「杀客户端 ≠ 停臂」（新会话 `moveReset()`）。

## 数据结构

```json
{"id":"Fcf0a3a","type":"points","name":"真实轨迹 <日期> <说明>","color":"#ff9f1c",
 "enabled":true,"pts":[[0.663,-0.029,0.292], …],"p1":[…],"p2":[…],"n":239}
```

- 🔴 **`pts` 单位是米**（`0.663` 不是 `663`）；同页的 `constraint_boxes` 也是米，两边一致，别一处 mm 一处 m。
- 🔴 **名字必须含「真实轨迹」**：页面 `realTrajItem()` 先按 `/真实轨迹/` 筛，筛不到才退到「最后一条 points」
  ⇒ 名字叫别的话会被其它 points 元素顶掉，按钮上的点数会忽有忽无。

## 操作顺序

```
# ① 先看现有 points（单位/点数/开关）
curl -s http://127.0.0.1:8797/api/fence | python3 -c "import sys,json;[print(i['id'],i['name'],len(i.get('pts') or []),i.get('enabled')) for i in json.load(sys.stdin)['items'] if i.get('type')=='points']"
# ② 删旧轨迹（服务端自动快照）。手眼标定那 7 点不是本趟轨迹，不要删
curl -s -X POST -d '{"id":"<旧 id>"}' -H 'Content-Type: application/json' http://127.0.0.1:8797/api/fence/delete
# ③ 加新轨迹
curl -s -X POST -H 'Content-Type: application/json' \
  -d '{"type":"points","name":"真实轨迹 20261121 新表239点","color":"#ff9f1c","enabled":true,"pts":[[x,y,z],…]}' \
  http://127.0.0.1:8797/api/fence/add
# ④ 回读：只剩一条本趟轨迹、enabled=true、点数对得上
```

## 🧹 「清空轨迹」是**两层**，只做一层就不算清空

用户说「原来的轨迹帮我清空，影响视线」时，画面上能看见的轨迹来自两处，必须分开清：

| 层 | 数据 | 清法 | 症状（只清另一层时） |
|---|---|---|---|
| 实测走过的 trace（细碎折线） | `zmax_data/ss_live/bridge_real_path.json` / 页面 trace 缓冲 | `POST /api/traj/clear`（写 `baseline_n`，把已收点数记为基线，之后只画新增） | 平白一片碎线，像“没清” |
| 整条 `type=points` 轨迹线 | `fences.json` 里那条 points 元素 | `POST /api/fence/update {id, enabled:false}`（或直接 delete） | 一条干净的长折线，也像“没清” |

- 洋红规划航路（`TRAJ.plan`）是第三层，看清空范围要不要连它一起关（闸门 `NAMED_ON[planOwner()]`）。
- 🔴 **`📍 真实轨迹`(`tReal`) 按钮点一下会 `POST /api/fence/update {id, enabled:!enabled}` 写回服务端**
  ⇒ 拿它做“开关对照”会把元素永久关掉（实测点两下就 enabled=false，画布上什么都没了）。要开关就显式传值，改完回读 `/api/fence`。
- 清完必查一处：`GET /api/traj/state` 的 `n`/`baseline` 与 `GET /api/fence` 的 `enabled` **两个都要是“空”**，
  否则用户刷新后还会看到一半。

## 🔁 服务端改完，已开页面不会自己刷新（「没有清空」的真正来源）

`loadFences()` 只在页面首载跑一次 ⇒ 你在服务端删/关了轨迹，用户那个标签页照样把旧元素画着，
他报「没有清空」而你以为已经清干净了。这不是缓存，是页面根本没有再拉一次。

- 修法（`tools/web/tcp-ar.html`，加在 `setInterval(loadCfgPts, 10000)` 附近）：
  ```js
  setInterval(loadFences, 3000);   // 内部按 id+':'+enabled 指纹比对，变了才重绘
  ```
- 🔴 **验收口径 = 不刷新也跟随**，不是让他 `Ctrl+Shift+R`：
  1. 页面保持打开不动；`POST /api/fence/update {enabled:true}` → 等 ~7s → 数目标色像素应上升；
  2. `POST … {enabled:false}` → 等 ~7s → 像素回落到基线。
  实测 `#ff9f1c`：关 **698** → 开 **1092** → 再关 **698**（全程零刷新）。
- 让用户硬刷一次只适用于“页面代码本身改了”，**不适用于“数据/开关变了”** —— 后者页面有责任自己跟上。

## 只读验收（不要去点按钮）

- 页面 `FENCES` 是**惰性加载**：导航后首屏快照可能还是 0 条，实测等 ~4s 才出现 ⇒ 先
  `await new Promise(r=>setTimeout(r,4000))` 再读，否则会把“还没加载”误判成“没画”。
- 像素判据（唯一可信的“真的画出来了”）：数 `#vr` 画布上该颜色的像素数，关/开两次对比应有数百像素差。
  实测 `#ff9f1c` 轨迹 239 点：关 869 → 开 1069 px；连续两次开都是 869/870 就说明根本没画。
- 若元素已 enabled 但像素不涨：页面 `FENCES` 还是空的 —— `await loadFences(); drawVR();` 再数一次
  （`loadFences` / `drawVR` / `realTrajItem` 都在 window 上，可直接调）。
- 画布还有别的点缀色（目标点圈、通道管）也是橙/黄系 ⇒ 颜色判据要按接近色而非阈值区间，并且必须“关→开”对比，
  不要拿绝对像素数下结论。
