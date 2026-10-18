# URDF 外形渲染 (2D canvas, 无 WebGL)

目标: 在 AR 页的三维视图里画出**这条臂的真实外形**, 姿态跟真机关节角走。

## 1. 服务端: 外形 → 降采样点云

`tools/urdf_proxy.py`(约 150 行, 只用 stdlib):

- 正则抽 joint: `<joint name type>` → `parent/child/origin xyz/rpy/axis`; 抽 link → 第一个 `<visual><mesh filename>`。
- STL: 二进制优先(`84 + ntri*50 == filesize` 判), 否则 ASCII 正则 `vertex x y z`; 每三角形取一个顶点, 按三角形数等间隔抽 `PTS_PER_LINK=220`。
- **单位**: 读到的点若 `max|坐标| > 5` ⇒ 整体 `/1000`(这套 STL 是毫米)。返回体里带每 link 的 `n`, 便于页面侧核对。
- 输出 `{links, joints, base, tip, n_links, n_joints, src}`, 一次 47KB。

服务端只解析一次并缓存(`_URDF_CACHE`), `/api/urdf` 直接回缓存; 失败回 `{ok:false, err}` 不抛异常拖垮整页。

## 2. 页面: 正运动学

```js
// RPY (URDF 固定轴) → R = Rz(y)·Ry(p)·Rx(r)
function rpy2R(r,p,y){...}
// Rodrigues 轴角
function axisRot(ax,q){...}
// 逐 joint 左乘:  M_child = M_parent · (Trans(xyz)·RPY) · Rot(axis,q)
// 只有 revolute/continuous 吃 q; fixed 不吃; q 按 URDF 出现顺序对应 joints[qi++]
```

关键点:
- 用 **4×4 拆成 (R,t)** 就够, 不必写完整 mat4; 复合 `(Ra,ta)·(Rb,tb) = (Ra·Rb, Ra·tb + ta)`。
- `parent` 为 `world` 的 fixed joint 给恒等矩阵, 保证链从 base 起算。
- 点云在 link 自身坐标系 ⇒ 每个点乘该 link 的 (R,t) 后即世界系。

## 3. 页面: 画成实体

- 每 link: 点云投影 → `_hull()`(Andrew monotone chain) → `fill`(深金属色) + `stroke`(亮色);
  `globalAlpha` / `lineWidth` 按 `1/z` 收, 远的淡、近的粗。
- 关节骨骼线: 父 link 原点 → 子 link 原点, 半透明白, 让链看着连贯。
- 画完再画轨迹/坐标轴 ⇒ 轨迹永远在最上层。
- 开关: `VR.urdf` + 独立按钮; 每帧先 `LINKM = urdfFK(TCP.joints)` 再 `drawUrdf(g, pr)`。

## 4. 自检脚本(控制台一段就能跑)

1. `/api/urdf` → 报 links/joints/点数, 每条 link 的 bbox(米) —— bbox 是 500 量级就是单位没换。
2. 页内: 复制 `drawVR` 的相机公式算 `pr()`(F/CX/CY 一起), 遍历点云求屏幕 bbox:
   - `tool1` 投影与 `TCP` 投影距离 < 3px;
   - bbox 完整在画布内;
   - bbox 高度 / 画布高 ≥ 45%。
3. 像素: `getImageData` 数 link 填充色像素 > 0。

## 5. 状态

- 页面按 mtime 热读 ⇒ 改 HTML 用户 F5 即可; **改服务端 Python 必须 `systemctl restart zmax-traj-ar`**, 否则 `/api/urdf`/`joints` 不存在。
- `window.X` 拿不到页面顶层 `let` 变量 ⇒ 控制台自检写裸名。
