# 3D 围栏编辑层 — 实现细节 (base 世界系 · 长方体/正方体/直线)

服务：`tools/tcp_ar_server.py` + `tools/web/tcp-ar.html` (按 mtime 热读 ⇒ 改页面不用重启)
存储：`tools/fence_store.py` (纯函数，可被页面服务与跟随器共用) ⇒ `zmax_data/ar_rs/fences.json`

## 数据真源

```json
{"updated": "2026-10-18 18:03:17", "margin_mm": 10,
 "items": [{"id":"F980947","type":"box","name":"台面禁区",
            "p1":[0.50,0.05,0.30],"p2":[0.62,0.15,0.42],
            "color":"#ff9f1c","enabled":true,"note":"","at":"…"}]}
```

- 坐标单位 **米**(base 世界系)，页面输入框用 **mm**(÷1000 后存)。存米是为了直接和 TCP `/pose` 对判。
- `box/cube` 两点 = 对角线，存前先排序成 `lo/hi`; `line` 两点 = 端点(保留方向，不排序)。
- 原子写盘：`tmp` + `os.replace`，避免页面轮询读到半个 JSON。
- `enabled:false` 的条目照存不参与判定(不要删，用户是在试)。

## 端点表

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/fence` | 列表 + `margin_mm` |
| POST | `/api/fence/add` | `{type,p1,p2,name,color}` → 新条目 |
| POST | `/api/fence/update` | `{id,p1,p2,name,color,enabled}` → 改 |
| POST | `/api/fence/delete` | `{id}` |
| POST | `/api/fence/clear` | 清空(测试完自己清干净) |
| POST | `/api/fence/margin` | `{margin_mm}` |
| GET | `/api/fence/check?x=&y=&z=` | 该点是否在某围栏内(米) + 命中条目 + 距离 |

`check` 同时被人工排查与跟随器复用；跟随器**直接 import `fence_store`**(同机，不必绕 HTTP)。

## 判定

```python
def _in_box(p, lo, hi, m):      # m = margin (米)
    return all(lo[i]-m <= p[i] <= hi[i]+m for i in range(3))

def _pt_seg(p, a, b, m):        # 点到线段距离 < m ⇒ 命中
    ab = [b[i]-a[i] for i in range(3)]; ap = [p[i]-a[i] for i in range(3)]
    d = sum(x*x for x in ab)
    t = 0.0 if d == 0 else max(0.0, min(1.0, sum(ab[i]*ap[i] for i in range(3))/d))
    c = [a[i]+ab[i]*t for i in range(3)]
    return math.dist(p, c) < m
```

`check_points(pts)` 返回 `{hit, n_pts, first:{i, by:[命中条目…]}, any:…}` —— `by` 里带 `dist_mm`，
日志直接用「第 i 点 / 撞「名字」」，用户看得懂。

## 点图取点(反投影到水平面)

页面每帧在 `drawVR()` 里存下相机:`VIEW={eye,R,U,fwd,F,CX,CY}` (F = 焦距像素, CX/CY = 主点)。
像素 (u,v) → 射线 → 与 z=Z 平面求交：

```js
function _pickPlane(u, v, Z){
  const d = [fwd[0] + (u-CX)/F*R[0] - (v-CY)/F*U[0], …];   // 三轴同理
  if (Math.abs(d[2]) < 1e-6) return null;
  const t = (Z - eye[2]) / d[2];
  if (t <= 0) return null;
  return [eye[0]+t*d[0], eye[1]+t*d[1], Z];
}
```

要点：
- **Z 由输入框给，不从像素猜** —— 单目没有深度；猜 Z 会让人觉得自己画的盒子飘着。
- 注意 v 是向下增长: `U` 的系数取 `-(v-CY)/F`。
- 点击必须与拖动区分: `mousedown→mouseup` 位移 <4px 才算"点击取点"，否则会打断旋转。
- Shift+点击取第二点(不弹窗、不切模式)。

## 渲染

- 盒子：8 角点 → 6 个面，**按面中心到相机距离降序**画(远先画), `fillStyle` 同色 alpha≈0.10,
  再画 12 条棱 alpha≈0.9; 文字标在角点最小的那个角旁(`名字 · 120×100×120mm`)。
- 直线：`lineWidth 3`、`setLineDash([8,6])` 可选; 两端画 A/B 小圆点 + 文字。
- 画在 **URDF 外形之后、轨迹之前**: 围栏是空间体积，压在臂前面才看得出"这块不能进"。
- 颜色：盒子 `#ff9f1c`(橙，与"真机轨迹橙"同色系但面透明度低，靠形状区分)、直线 `#ff5d9e`。
  做像素验收时用更严的条件(如 `R>230 && 130<G<200 && B<90`)避免把橙色轨迹数进来。

## 验收(全用真执行, 不看"没报错")

```bash
curl -s localhost:8797/api/fence                       # 初始 n
curl -s -X POST -d '{"type":"box","p1":[0.5,0.05,0.3],"p2":[0.62,0.15,0.42],"name":"x"}' localhost:8797/api/fence/add
curl -s "localhost:8797/api/fence/check?x=0.56&y=0.10&z=0.36"   # 应命中 + dist
```

浏览器控制台(DOM 驱动 UI, 不靠手点)：

```js
$('fCube').click(); $('fX1').value=300; $('fY1').value=-100; $('fZ1').value=250;
$('fSide').value=60; $('fCube').click();   // 生成 p2 = p1 + 60mm
$('fAdd').click();                          // 之后轮询 FENCES[last]
```

- 像素: `getImageData` 数围栏色像素 >0(实测 438px / 847×633 说明真画了)。
- 取点: `$('fPick').click()` 后在画布上 `dispatchEvent(new MouseEvent('mousedown'…))` +
  `mouseup`(Shift 版带 `shiftKey:true`) ⇒ 看输入框被填成合理 mm 值。
- 离线四类路径判定(拒/拒/放行/放行) 用 `fence_store` 直接跑，别等现场。
- 测完 **清空**(`/api/fence/clear` 或逐条 delete) —— 留着假围栏会真的拦住后续动作。
