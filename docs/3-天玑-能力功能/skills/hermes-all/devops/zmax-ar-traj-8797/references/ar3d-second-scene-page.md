# 从 ar3d 派生第二个场景页（不重写渲染）

用户说「仿照这个场景, 再做一个场景」时, **不要另写一套渲染**: 同一份 `tcp-ar.html` + 一个 path 标志,
几何/URDF/桌/箱体/中央相机全部沿用。两套渲染迟早画得不一样, 现场又是"看着不对"。

## 接入方式

- 在**脚本最前面**判定 path（`/ar3d` 已有先例）:
  `const __TRAY = pathname==='/tray' || usp.get('scene')==='tray'`, 并入 `__BARE`（走 vrfull 版式）,
  再 `document.body.classList.add('tray')`。版式差异只放 CSS（`body.tray #vrRail::before{content:"…"}`）,
  不动 DOM 结构 —— 删 DOM 会打断引擎对元素 id 的依赖。
- 服务端路由是**代码里的白名单**: HTML 每请求热读, 但**加路径必须重启进程**。重启后两条路径都要验
  （`/ar3d` 与 `/tray` 都 200, 且服务端内容 md5 与磁盘逐字节一致）。

## 场景默认值

- 用**幂等设值**（`TAB.show=true; bTab.classList.toggle('on',true)`）, 不要 `click()` ——
  toggle 会把本来就是开的关掉。实验桌在 ar3d 默认是**关**的, 新场景必须显式打开。
- 开关的"亮"与"画"必须对得上: 设了 `X.show` 就同步 `button.classList.toggle('on')`。

## 左栏精简: 保留祖先链

- 🔴 逐个 `button` 隐藏会把「相对点数」「游标 215/215」「真机也走」「左臂位姿」这类**非按钮残留**留一排。
- 正确做法: 取白名单按钮集合 → 收集它们的**祖先链**（`Set`）→ 从 `#vrRail` 递归,
  在链上的往下走、不在链上的 `display:none`。留下的正好是那几个开关。
- 页面是异步渲染的（轨迹/工程点位 fetch 之后才出现）⇒ trim 要在 0/200/600/1500/3000/6000ms 多拍几次。
- 底部回放条、`#mktDock`（生产演练）、姿态脚注 单独按 id 或文本关掉。

## 取景: 自动取景不含桌子

- `vrFitBox()` 只按**臂的点云**算包围盒 ⇒ 1600mm 长的实验桌会被画布边缘切掉（实测 −5px）。
- 新场景固定机位并关自动取景: `VR.auto=false; VR.tgt=[0.55,0.30,0.10]; VR.dist=1.80`
  （980×577 下四角留边 ≥14px）。确认 `drawVR` 里 `if(VR.auto){VR.auto=false; vrFitBox();}` 不会再改回去。

## 验收（不靠肉眼）

1. 状态量: 各 `*.show` / `VR.*` 全 true; 可见按钮数 == 白名单长度。
2. 左栏无残留: 遍历 `#vrRail` 叶子节点, `offsetParent!==null` 且非空文本、且不在按钮内的应为 0 条。
3. 几何: 把桌/箱体/相机角点用 `VIEW.pr` 投影出来, 断言全在画布内（带 8~14px 边距）。
4. 绘制: 给 `drawTable/drawChassis/drawFloor/drawTopCam/drawUrdf` 计数后手动调一次 `drawVR()`,
   次数 >0 才算"画了"; `drawUrdf` 应为 2（双臂）。
5. 回归 `/ar3d`: 标题、按钮、自动取景都不许变。

## 操作区留空

用户说"具体操作我来重新定义"⇒ 先把场景画全, 左栏只留场景开关, 操作按钮等他说了再加。
别自作主张把回放/单步/轨迹那一套搬进新场景。
