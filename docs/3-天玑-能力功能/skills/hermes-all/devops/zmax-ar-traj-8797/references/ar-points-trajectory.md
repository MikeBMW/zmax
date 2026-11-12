# 录制的真实轨迹画进 AR 三维（points + 取景 + 一键开关）

背景（2026-11-11 实测）：老倪跑完真实流程后要「先在 AR 场景画出 3D 轨迹」，接着要「一个按钮，可以打开和关闭真实轨迹」。

## 1. 数据怎么进去
- 录制：`tools/pose_record.py`（5Hz 真值 `zmax_data/rokae_sdk/tcp_out/latest.json` 逐拍落盘 poses.jsonl，断拍记 gap）。
- 入库：`tools/pose_to_ar.py --rec latest --tol 1.0 --color "#ff2dfb" --name "真实轨迹 <rec>"`
  → `POST /api/fence/add {type:'points', pts:[[x,y,z]m...]}`，写完回读 `/api/fence` 对账 `n`。
- `--per-run` 按空闲 >4s 分轮各一条（轮1/轮2 不同色）；只想看整条就用默认单条。
- 出图/统计：`tools/pose_map.py --with-scene`（gui-venv311 有 matplotlib）→ map_top/map_side/map_3d + coverage.json。

## 2. 为什么“画了却看不见”
`vrFitBox()` 原来只算 TRAJ / NAMED / TCP / URDF / 箱体 / 桌子 / 坐标系。轨迹抬到 z≈998mm 时上半段直接落在画外
（实测洋红像素 bbox 的上边正好 y=0）。两处都要改：

1. `vrFitBox()` 里加：
   ```js
   if(typeof FENCES!=='undefined' && FENCES && FENCES.filter){
     FENCES.filter(i=>i && i.type==='points' && i.enabled!==false).forEach(i=>(i.pts||[]).forEach(p=>pts.push(p)));
   }
   ```
2. `loadFences()` 成功拿到数据后补一次一次性取景（启动那拍 fit 早于 `/api/fence` 返回）：
   ```js
   if(!window.__FIT_AFTER_PTS && FENCES.some(i=>i.type==='points' && i.enabled!==false)){
     window.__FIT_AFTER_PTS=1;
     const _po=VR.panOff||[0,0,0];
     if(Math.abs(_po[0])+Math.abs(_po[1])+Math.abs(_po[2])<1e-6){ VR.auto=true; VR.camLock=0; vrFitBox(); drawVR(); }
   }
   ```
   尊重用户中键平移是硬要求（否则一加载就把用户刚调好的视角拉走）。

## 3. 一键开关按钮（用户明确要的交互）
- 位置：轨迹行尾部，`🎯 对准` 之后：`<button id="tReal" class="sm">📍 真实轨迹</button>`。
- 选目标：
  ```js
  function realTrajItem(){ const P=(FENCES||[]).filter(i=>i && i.type==='points');
    const R=P.filter(i=>/真实轨迹/.test(i.name||'')); return R[R.length-1] || P[P.length-1] || null; }
  ```
- 点击：`await fencePost('/api/fence/update',{id:it.id, enabled:!it.enabled})`（fencePost 内部 loadFences+drawVR），
  打开后 `VR.auto=true; VR.camLock=0; VR.panOff=[0,0,0]; vrFitBox(); drawVR();`，最后 `paintRealBtn()`。
- 状态回写：`loadFences()` 里调 `paintRealBtn()`；文案带点数（`📍 真实轨迹 182点`），class 用 `on`。

## 4. 自验口径（不靠肉眼）
- 颜色必须全页独有：料盘青 `#22d3ee` / 橙 `#f59e0b` 会和青/橙轨迹撞色，录制轨迹用 `#ff2dfb`。
- 开 → 数洋红像素 2077~2612，且 bbox 四边都在画布内（dist 2337/2207）；关 → 14 像素；再开回 2612。
- `/ar` 与 `/ar3d` 两颗按钮都要在（同一个 tcp-ar.html，两条路径）。
- 合成 `document.getElementById('tReal').click()` 能触发 addEventListener 处理器；
  Playwright 的 click 在被浮层盖住的按钮上可能静默不生效 —— 先看 DOM class 有没有翻，别当功能坏了。
- 页面版本戳同一批递号（r93 取景 / r94 补取景 / r95 按钮），改完让用户 Ctrl+Shift+R 并核对版本号。
