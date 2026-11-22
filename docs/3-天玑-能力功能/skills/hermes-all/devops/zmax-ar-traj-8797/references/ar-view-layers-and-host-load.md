# AR 3D 视图图层辨识 / 注入标记 / 主机变慢排查 (2026-11-22 实测)

## 1. 「蓝色轨迹」指哪一层
- 老倪说「把这么多蓝色轨迹删掉」= `🦾 URDF 外形` 那层淡紫蓝线条（`#c4b5fd` / `#c084fc`），**不是** `drawTrayModules` / `SLOT_MM` 的光模块蓝块（`#60a5fa`），也不是 fences 里的 `#60a5fa` 料盘块。
- 关它：`VR.urdf=false`（第 ~674 行 VR 初始化）+ 按钮 `bUrdf` 去掉 `on` 类（第 ~293 行）。改默认值 ⇒ 刷新后仍保持关。
- 量化取证：3D canvas 蓝色像素 19,674 → 12,595（847×474）。
- 归属定位方法（比猜快）：挂 `CanvasRenderingContext2D.prototype.stroke/fill`，当前 `strokeStyle/fillStyle` 偏蓝时记录 `new Error().stack` 的调用点，按 `颜色 + 调用点` 聚合。实测一次就分出 `drawUrdf` / `drawFences` / `drawFlatModule` / `drawTargetPose` 各画了多少笔。
- 判据 caveat：`b-r>50 && b-g>20` 会把紫 `#c084fc`、青 `#22d3ee` 一起算成「蓝」；别看总数，要看调用点。

## 2. 改页面 / 注入标记都不必重启服务
- `tools/web/tcp-ar.html` 是**热读**的：改完让用户 F5 即可，不要重启 8797（重启须点名）。
- 往 3D 场景加东西不必改服务端：往 `zmax_data/ar_rs/fences.json` 写一个 `type=points` 元素即可，页面 `fetch('/api/fence')` 热读。
  例：`{id:'TP1', type:'points', name:'🎯目标位姿 槽位3', color:'#ffd23f', pts:[p0,p1], enabled:true, pose:{pos_m:[...],quat:[w,x,y,z],dims_mm:[...]}}`；前端用 `item.pose` 画真尺寸盒 + 三轴 + 预抓虚线，`pts` 兜底成一条线。
- 改 `fences.json` 前先备份（`fences.json.bak-<ts>`）；删「回放轨迹」这类元素同理（按 `type=='points' && '轨迹' in name` 精确定位，别按颜色删）。

## 3. 「系统太慢」先查服务崩溃死循环
- 判据：`systemctl show <unit> -p NRestarts`。实测 `zmax-traj-ar.service` 因一个整天前手动起的**裸进程占着 8797**，端口冲突 ⇒ 退出 1 ⇒ `Restart=always` 重拉 ⇒ **9,657 次重启**，单次 9s CPU，load 冲到 72（32 核）。
- 修：`ss -ltnp :8797` 认 owner → `kill` 裸进程 → service 立刻接管 → `systemctl reset-failed` → `curl -o /dev/null -w '%{http_code}' :8797/` 复核 200。
- 成本排序：把 `ps` 按 `/proc/<pid>/cgroup` 归到 unit 再聚合，避免一个个猜；同一脚本两份裸进程优先杀；`zmax-l2-probe` 这类探针、`shadow_live.py`、`ar_yolo_train_eval`、`live_motion_recorder` 都是可停的重负载。
- 只停不禁：`sudo systemctl stop <unit>` 合规，别 `disable`。停完复核 8797 / 8791 / 8815 仍 200。
- swap 长期满（15G/15G）不会自己回收；清它要单独确认（会卡顿）。
