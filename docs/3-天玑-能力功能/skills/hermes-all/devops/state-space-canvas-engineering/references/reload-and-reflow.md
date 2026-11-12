# 重载通道与自动重排（改完坐标没生效的两个原因）

## 1. 文件改了、界面没变 —— 内存里还是旧布局
画布运行中直接改 `flows/state_space_obs.json`（真源软链到 `data/database/zmax/sources/canvas/`）不会生效。
**触发重载**：把一行 `ss_canvas` 写进控制台命令通道
```bash
printf 'ss_canvas\n' > /tmp/zmax_nav_cmd
```
重载成功的硬证据：该 JSON 的 mtime 被刷新（`normalize_after_load(persist=True)` 会回写）。

## 2. 重载会按行重排 —— 手改的 x 会被推走
`normalize_after_load` → `_relayout_row_gaps()`：按 y 分桶，桶内按 x 升序，**只把重叠的往后推到「前一个右缘 + 56」**（只往右推，不往左回拉）。
所以「把某个节点换到第一列」如果改了哪个节点的左邻，重载后邻居的 x 会被连带推移（实测 sslat 4280→4336、ss_moe 4620→4672）。

改完必须 `git diff` 归类差异：
- 允许：坐标 / 数组顺序（这是你要的改动）
- 顺带出现：`loaded_at`·`cfg_loaded_at`·`sha256` —— 运行时字段，还原即可（`git checkout -- <json>`）

## 3. 对象别搞错：画布 ≠ 方案册
用户口中的「某层第 N 位」可能是**交付 PPT 的页序**，不是画布节点位置。
实测被明确纠正过：「没让你改画布，我说的是 ppt」。
动手前一句话确认对象（画布节点坐标 / PPT 页序），比改完回滚便宜。
