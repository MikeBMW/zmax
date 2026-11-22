# ar3d(8797) 上画/清点位轨迹

## 轨迹点存在 fences.json 里, type=points
- HTTP: `GET /api/fence` → `items[]`；`POST /api/fence/add` / `update` / `delete`
- 结构: `{id, type:'points', name, p1, p2, pts:[[x,y,z]...], color, enabled}`，**座标是米**
- 339+ 条目是常态（包络线 335 条 line + 52 box），只有 `type=points` 是轨迹

## 换一条轨迹（清旧画新）
1. 先列出所有 `type=points`，确认哪条是旧的（名字里常带日期），`POST /api/fence/delete {id}`
2. `POST /api/fence/add {type:'points', name, pts, p1, p2, color, note}` —— 一条 239 点约 24KB，一次请求即可
3. `POST /api/fence/update {id, enabled:true}` 打开；不传的字段会被**清掉**，改名字时要把 enabled 一起带上

## 清"原来的轨迹"（挡住视线的那条）
挡视线的一般不是 fences 的 points，而是**画面上积累的实测 trace**（可能几万点，橙色）：
```bash
curl -s http://127.0.0.1:8797/api/traj/state     # recorded_pts / baseline_n
curl -sX POST -d '{}' http://127.0.0.1:8797/api/traj/clear   # baseline_n=recorded_pts
```
clear 只影响显示，录制历史文件不动；洋红规划线(plan, 5 点)仍会在，属正常。

## 验证口径
- 页面按钮 `#tReal` 文字带点数（`📍 真实轨迹 239点`）+ class 含 `on` ⇒ 已加载且显示
- 像素法：`#vr` canvas 取 `getImageData`，按轨迹色数点数（例如 `#ff9f1c`）；
  关闭/开启各数一次，差值 >0 才算真画出来
- ⚠️ 新开的页面 `FENCES` 常常是**空**的（首帧 loadFences 未完成），等 3~4s 再判，
  或在 console 里手动 `loadFences(); drawVR()`
- ⚠️ **不要**按文字去点按钮：`▶ 右臂跑真实轨迹`(id=`bRTraj`) 会真的让真机动
