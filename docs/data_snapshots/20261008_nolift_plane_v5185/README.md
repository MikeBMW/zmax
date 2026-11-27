# 数据快照 · 2026-10-08 删抬升 + 空间点重记同平面 (v5.18.5)

现场指令（老倪逐字）：「不要抬升，不要抬升，不要抬升 …… 马上删掉上升的逻辑；重做」

## 改了什么
- `tools/l2_daemon.py`：`adapt_point` 段由 `t[2] = _aneed`（自动把 z 抬到该点高度）**删除**，
  改为「该点 z > 当前 z + 5mm ⇒ 整单拒发」；`_lim += _adapt_exempt_mm`（必升豁免）→ 0。
- 空间点 1~7 由老倪**重新记录**：7 个点同一平面 `z = 0.1727` ⇒ 点间移动 = 纯横移，零上升。
- `tools/rokae/l2_transport_sdk.py`：`MAX_SPEED_MM_S` 60 → 150（实测≈15mm/s，页面 2000 档）。
- 配方 `L2.goto_space1~7`：三段单轴（竖直到该点高度 / 保持高度横移 / 到位），`speed_max` 2000。

## 为什么
2026-10-08 一天内三次近失/碰撞，全部是「先抬到转移高度」引起（space1 上空升到 0.3330/0.3435 撞）。
转移高度余量删到 0 仍不够 ⇒ 这次把「自动抬升」这件事从代码里删掉。

## 文件
- `space_points.json`：7 点真源（同平面 z=0.1727，updated_at 2026-10-08 11:34:19）
- `registry.json`：`goto_space1~7` 三段单轴 + `speed_max 2000`
- `collision_points.json` / `estop_events.jsonl`：今天的碰撞点与急停流水
- `backups/`：改动前的原文（l2_daemon.py / l2_transport_sdk.py / registry.json）
