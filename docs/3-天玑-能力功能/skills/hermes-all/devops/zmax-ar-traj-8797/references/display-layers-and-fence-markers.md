# 3D AR 页的图层/注记/场景标记怎么改才不返工

适用: 8797 的三维视图里「多出一坨蓝」「黑底空文字条」「回放轨迹删不掉」「要把某个位姿标到某个槽位」。

## 1 黑底文字条删不干净
页面在 `CanvasRenderingContext2D.prototype` 上挂了 `VR_TEXT===false` 就 return 的补丁, 但拦的只有
`fillText/strokeText`。标签的背板是单独一句 `g.fillStyle='rgba(0,0,0,.6~.8)'; g.fillRect(...)`,
**不受拦** ⇒ 画面上只剩一排没有字的黑底板。

规则: 删注记要连背板一起关 —— 把 `fillRect` 也包进同一个 `VR_TEXT!==false` 判断(或删掉那两行),
只删 `fillText` 等于没删。用户原话口径就是「把屏幕的黑色背景的文字条删掉」。

## 2 场景标记 = fences.json(热读, 不用重启)
- `zmax_data/ar_rs/fences.json` 的 `items`: type `box` 实体盒 / `line` 直线 / `points` 轨迹点。
- 服务端 `/api/fence` **每次请求热读**该文件; 前端 `tcp-ar.html` 也按 mtime 热读 ⇒ **改标记/改页面只要刷新浏览器**。
- 重启 8797 是 systemd 单元操作, 属于「重启须点名」的范围 —— 能用热读解决就不要重启。

要把一个目标位姿标进场景: upsert 一个 `points` 元素(`id` 固定, 如 `TP1`), 两点定原点+长轴,
额外键存 `pose`(pos/quat/dims) 供前端解析; 前端在 `drawVR()` 里 `fetch('/api/fence')` 找该 id 自绘
真尺寸盒 + 三轴 + 预抓虚线 + 固定像素靶环。不要为一次性标记去改服务端路由。

删轨迹: 按 id 从 `items` 里删 `points` 元素, **先备份** `fences.json.bak-<ts>`, 删完 `curl /api/fence` 复核
只剩预期元素。服务端 `traj/state` 的 `show=false`、`plan_hidden=true` 是默认值, 别把「看不见的录制历史」
当成残留轨迹反复清。

## 3 先量再删, 别按颜色猜图层
用户报「这么多蓝色轨迹」时, 在页面上下文给 `CanvasRenderingContext2D.prototype.stroke/fill` 挂
300~700ms 的临时探针, 记录 `new Error().stack` 前两帧 + 当前 `strokeStyle/fillStyle` ⇒ 直接得到
「哪个函数画的、画了多少次」。再用蓝像素连通域统计区分:
- 大块面(150×195 级) = 手臂外壳(URDF 外形)、料盘/插孔框的半透明面;
- 几十个小块 = 槽内光模块(28 个 #60a5fa);
- 细长串 = 真轨迹(239 点聚色线)。

坑: `#c084fc`(紫)、`#c4b5fd`(淡紫)、`#22d3ee`(青) 都会被「蓝」判据算进去, 报数时说明是同色系。

## 4 改默认可见性要改两处
只在脚本里把 `VR.<flag>=false` 不够: HTML 上那颗按钮带 `class="sm on"`, 刷新后又亮。
两处一起改(`class="sm on"`→`class="sm"`), 刷新后才是真的默认关。

## 5 浏览器取证(没有截图渠道时)
- 取 3D 画布: `[...document.querySelectorAll('canvas')].find(c=>c.width>800&&c.height>440)` ——
  按尺寸挑, 别写死下标(画布数量/顺序会变)。
- 自加计数器入 `drawXxx`(`window.__X_DRAWN__++`) + 记投影坐标(`window.__X_SCREEN__`), 用来证明
  「这一帧真的画了」; 像素计数(gold/blue)配 bbox 证明画在哪。
- 验证完把标签页导航到 `about:blank`: 三维页面渲染很吃 CPU, 开着会自己把整机负载抬上去。
