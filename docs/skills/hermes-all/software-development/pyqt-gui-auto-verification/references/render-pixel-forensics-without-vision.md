# 无视觉时"看懂"一帧画面 + 判定用户屏幕上是哪个状态 (2026-09-17 实战)

> 场景: 用户拿"你看这画面里 XX 不对"质疑结果, 而**本模型看不了图**。
> 不要靠"再截一张图""让用户描述" —— 用下面三件套把"屏幕上是什么"变成可断言的数字。
> 项目侧落地工具 (Z-MAX 仓库) 与领域语义见 `zmax-console` 技能的
> `references/metaworld-insert-semantics-and-pixel-forensics-2026-09-17.md`。

## 1) 抓窗口 → 与"已知状态候选帧"比对 (最有力的第一步)

```python
# 抓某个窗口: Qt 自带, 不依赖 ImageMagick/xwd
app = QApplication([]); pm = app.primaryScreen().grabWindow(wid)   # wid = wmctrl 第一列
pm.save("/tmp/win_now.png", "PNG")
```
候选帧 = 你能在**同一进程/同一机位**重放出来的那些状态 (初始态 / 跑完终态 / idle 回退帧)。
判定 `cv2.matchTemplate` **多尺度** (0.4~2.6 step 0.02) 找最佳相关与位置;
⚠️ 整体相关只作辅助 —— 静态背景占大头时 0.85 vs 0.96 差距不够判案。
**用"会动/有颜色的那个物体"的像素质心 + 包围盒当指纹**: 本次 (绿=光模块)
窗口窗格相关 0.9423、绿像素 323 vs 319、包围盒**逐像素一致**、质心差 0.2×0.6px ⇒ 结论确定。
另存一份对照 PNG 给用户目检 (`/tmp/cand_*.png`), 让他也能对齐"我在说的这一帧"。

## 2) 世界坐标 → 像素投影 + 自检 (有 3D 场景/相机时)

```python
cid = model.camera("corner2").id
cpos, cmat = data.cam_xpos[cid], data.cam_xmat[cid].reshape(3, 3)
f = 0.5 * H / np.tan(np.radians(model.cam_fovy[cid] / 2))
def proj(p):
    v = np.asarray(p, float) - cpos
    xc, yc, zc = cmat[:,0]@v, cmat[:,1]@v, cmat[:,2]@v
    depth = -zc                      # MuJoCo/GL: 视轴 = 相机 −z
    if depth < 0: depth, xc, yc = -depth, -xc, -yc   # 约定不确定时按符号保障
    return (W/2 + f*xc/depth, H/2 - f*yc/depth) if depth > 1e-6 else None
```
**必须自检**: 投影一个"图里必然可见"的物体 (本次=绿色光模块中心), 其像素点要落在该颜色像素质心
附近 (实测差 3~4px)。**没自检过的投影不许拿来下结论** (符号/朝向错了会给出漂亮但反的答案)。

## 3) 纯文本"看图": 字符画 + 色类 + 几何标记叠加

- 降采样字符画: 每格取块均值 → 亮 `#` / 中灰 `·` / 暗空格; 目标颜色像素占比 >25% 打专用字母 (如绿=`P`)。
  96×48 够读场景结构 (注意物体在画面里可能只有几十像素, 只能定性)。
- 插入区放大: 逐像素分类 (绿/红/亮/偏蓝/暗) 打字符 → 能分清"哪块是盒体哪个面、杆从哪儿进"。
- **把投影点当标记叠到字符画上** (`M`=孔口 `G`=终点 `1/2`=物体两端 `W`=插槽立柱…) →
  直接读"物体 vs 目标特征"的相对关系, 这是"我看了一眼图"的等价物。
- 结论仍以数字为准 (mm/px), 字符画只用于**定位问题在画面的哪一块**。

## 4) 逐条颜色/样式断言: 必须数"渲染像素", 不能读 item 数据

用户说"这个颜色怎么没生效 / 绿色没设上"时, 症状在**渲染层**, 用数据层断言会得到假绿。

- **真因形态 (Qt)**: 样式表里写了 `QTreeWidget::item{color:#xxx;}` / `QTableWidget::item{color:…}`,
  它会**压掉** item 级 `setForeground(QColor(场景色))` ⇒ `item.foreground(0).color()` 读出来是场景色,
  屏幕上却全是样式表那一个灰 (实测: 34 行数据全绿, 离屏全分辨率渲染绿色像素 = **0**)。
  修: 条目默认色交回 palette/item 数据, 样式表那段只留 `padding` 之类非颜色属性。
- **离屏真渲染 + 数色** (不弹窗、可进判据):

```python
from PyQt5.QtGui import QImage, QPainter
w.setAttribute(Qt.WA_DontShowOnScreen, True); w.resize(W, H); w.show()
for _ in range(20): app.processEvents(); time.sleep(0.05)
im = QImage(W, H, QImage.Format_RGB32); im.fill(0)
p = QPainter(im); w.render(p); p.end()
# ⚠️ 只数目标控件的矩形 (mapTo 取几何) —— 页面别处的同色按钮/分组标题会污染计数
rect = tree.mapTo(w, QPoint(0, 0)); rect = (rect.x(), rect.y(), rect.x()+tree.width(), rect.y()+tree.height())
```

  实测教训: 全窗数色时负对照里"旧样式"仍报 80px 绿(来自顶部同色按钮) ⇒ 判据自相矛盾;
  限定到控件矩形后归零, 判据才可信。
- **必须配负对照**: 把"修前"的样式 `setStyleSheet` 贴回去重渲染, 彩色像素必须落到 0 ——
  这才证明这条判据抓的是这个坑, 而不是恰好数到了别处的同色像素。
- **数据在写 ≠ 界面在刷**: 分开断言。(a) 数据源文件帧龄 → 证明链路有数据;
  (b) 目标窗口中"当前值/帧龄"列的像素差 (live 段 vs stale 基线) → 证明界面在跟随;
  (c) 波形/图表面板可能是**另一条刷新路径**, 树在动面板不动时单独测面板: 离屏喂一份新数据再渲染一次,
  面板像素差异显著 ⇒ 面板本身会重画, 问题在它的刷新门槛 (跟随档/x 轴窗口), 不在数据链。
- **现场窗口连拍前先置顶目标窗口** (`wmctrl -i -a <win>`): 否则 scrot 抓到的是压在上面的别的窗口,
  差异读数会把"另一个窗口在动画"误判成"这个窗口在动画" (反之亦然)。
- **Qt 进程内做像素统计用 QImage→numpy, 不要 import cv2**: cv2 自带一份 Qt 平台插件,
  同进程会撞出 "Could not load the Qt platform plugin xcb" 直到 core dump; 取数方式:

```python
im = im.convertToFormat(QImage.Format_RGB32)
buf = im.constBits(); buf.setsize(im.byteCount())
a = np.frombuffer(buf, np.uint8).reshape(im.height(), im.width(), 4)[:, :, :3].astype(int)
```

## 坑 (本次踩到)

- **`grep`/`find` 找几何体时先确认几何挂在哪**: 该场景 `body("box")` **geoms=0**, 9 个 geom 全在
  **同名 unnamed 子 body** 上 → 按名字找 body 再扫它的 geom 会一无所获, 要全模型扫或遍历 children。
- **跨进程数字不可比**: 同一 seed 换个进程, 布局会漂 (本次实测盒体 y 差 0.2m)。
  所以"用户窗口"和"真值"必须在**同一进程**里量, 或先把真值落盘成文件再比。
- **带 `$(...)` 命令替换或超长拼接的 terminal 命令会被 Hermes 硬拦** (本次两次),
  文件读取/搜索一律用 read_file / search_files 工具, 别在 shell 里塞 `$(grep ...)`。
