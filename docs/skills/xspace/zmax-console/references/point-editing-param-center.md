# 点位 (空间点/号位示教点) 怎么改 —— 参数中心 + 命令行 + 微调工具

来源: 老倪 2026-10-10「空间点的7个点已经标记了…我要改变空间点的位置, 如何在功能清单中找到这个功能, 在参数中心修改空间点的位置?」
→ 当时参数中心**查不到任何点位** (只躺在 JSON 真源里) ⇒ 已接进参数中心。

## 三个真源

| 库 | 文件 | 内容 | 参数 id 前缀 |
|---|---|---|---|
| 空间点 | `data/skills/l2_atomic/space_points.json` | 空间1..7 + 安全区 (站台页标定, frame=base_link) | `space:` |
| 号位/示教点 | `data/skills/l2_atomic/taught_points.json` | 61 点: slot1/2 · 金手指点1 · insert_pose · aoi_gold_view · loop20_*/afx*_* 循环路点 | `teach:` |
| 演示学习轨迹 | `data/skills/l2_muscle/光模块_抓放_演示学习_v1.json` | 未接参数中心 (同名以 taught 为准) | — |

每点 7 个数 = `pos[0..2]` (m) + `quat[0..3]` (x,y,z,w)。共 483 个点位参数。

## 改的三条路

1. **参数中心页** (在线改数, 不动臂): 左树 `🩷空间点` / `📍号位示教点` → 双击 `空间1 · Z (m)` → 弹窗先给影响链 (功能 FN-SYS0-59 / 模块 / 系统 sys0) → 「应用」。
2. **命令行**: `python3 tools/param_registry.py set space:space1.pos[2] 0.5196 [--write]` (不带 --write 是干跑)。
3. **毫米级微调** (不动臂, 刚性平移): `python3 tools/adjust_point_offset.py 空间3 --dy=-2 [--dry] [--space|--teach]`
   —— 现场叫法自动归一 (空间1→space1, 1号位→slot1); 上限 ±20mm; 备份 `/tmp/<库>.pre_off_*`。
   更大改动 / 新点位 ⇒ 回现场点动 + 站台页「📝 记住此点」(`POST /ctl/record_point`)。

## 生效口径 (实测, 不是推测)

- 8793 站台页 `/ctl/points` 与规划请求**每次请求都读文件** (`_taught_points()` / `_space_points()` / `_resolve_target()` 无缓存)
  ⇒ 参数中心改完**立即生效, 不用重启**。实测: 改空间1 Z 0.5166→0.5196, 同一秒 `/ctl/points` 就返回 0.5196。
- 若某条常驻进程另有缓存才需重启那条链 (8793 无)。

## 两层写前哨 (防手误)

`param_registry._guard_point()` + `adjust_point_offset` 写前自检:
- 位置 **±1.2m 包络** (抓取动作在 0.3~0.9m)
- 改完与同库其它点距 **<1mm 拒写** —— 只拦**新产生**的重合对; 老数据里循环路点本来就差 0.2µm, 不能因此把整份文件锁死

## 坑

- `_write_json_path()` 内部把 ref 的 `json:` 前缀剥掉后再回读 `_read_json_path(ref)` → `split("json:",1)[1]` **IndexError**:
  症状极坏 —— **文件已写但工具崩栈、无回执**, 看起来像没写。已改 `split("json:",1)[-1]` (2026-10-10)。
  排查口诀: 写操作 CLI 吐 traceback 时, 先 `git diff` 真源文件确认真落盘没有, 别急着重试。
- 参数注册表 `_backup()` 把 `.bak_<ts>` 写在**真源文件旁边** (`data/skills/l2_atomic/`), 多跑几次会堆一片 ⇒ 定期挪到 `zmax_data/backups/point_edit_bak/`。
- GUI 参数中心分组图标写在 `tools/gui/param_center.py` 的 `CAT_ICON`; 分组本身由注册表 `groups` 动态生成, 新组不加图标也能显示 (只是没图标)。
