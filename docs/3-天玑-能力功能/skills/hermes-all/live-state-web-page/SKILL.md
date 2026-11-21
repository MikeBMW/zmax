---
name: live-state-web-page
description: "Use when 要给真机/在役服务做只读实时跟随页."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [web-page, read-only, realtime, follow, verification, zmax]
    related_skills: [status-aggregation-endpoint, user-facing-dashboard-delivery, zmax-live-video-stream]
---

# 只读实时页 (浏览器/手机跟随在役设备状态)

## When to Use

- 用户说「先给我个网页，我自己打开」，要**看**真机/服务当前状态（位置、速度、判据、帧龄），不要你截图。
- 需要「跟随真机」：页面上的点/轨迹随设备变化走，不是一次性快照。
- 判据（势能、门控、阈值比较）要独立于执行链可视化给他看。

往**已被 systemd 独占的端口**加只读路由是另一件事，按 `status-aggregation-endpoint` 做；
本技能只管「另起一个小服务 + 一个页面」这条形态。

## 骨架（约 150 行，够用就别加）

- 一个 `ThreadingHTTPServer`，`0.0.0.0:<未占用端口>`；只两条路由：`/` 出 HTML，`/api/state` 出 JSON。
- 前端单文件、无外部 CDN（内网/离线要能开）；`fetch('/api/state')` 每 1~2s 轮询即可，
  真值源 5Hz 也不必跟到 5Hz。
- 服务端每次请求**现算**（或极短 TTL 缓存），不落中间文件。
- 常驻用 `setsid` / `background=true` 起，日志重定向到固定文件（`/tmp/<name>.log`）供排查。
  ⚠️ **`setsid` 起的进程重启就没了** —— 用户下次开机打开收藏的链接就是 404，而他会认为"页面被删了"。
  一旦确认这个页面要长期给人看，就落一个 systemd unit（`Restart=always` +
  `StandardOutput=append:<repo>/zmax_data/logs/<name>.log`，`After=` 它依赖的只读真值服务），
  按端口 kill 掉手工 pid → `systemctl enable --now` → 复核 `is-enabled` / `is-active` / 页面 200 / 静态资产 200。
  交接时分开写：**哪几个端口已由 unit 托管**、**哪几个仍是手工进程（开机要人拉）**。

## 五条硬规则

1. 🔴 **只暴露白名单路由**：`/` 与 `/api/state`，其余 404。**绝不把仓库根当静态目录**
   （secrets / 权重 / 凭据都在里面）—— 别用 `SimpleHTTPRequestHandler(directory=repo)` 图省事。
2. 🔴 **判据用节点同一份实现现算**：偏差 / 势能 / 门控 import 执行链用的**同一个模块**
   （如 `phase_corridor` / `manifold_engine`），不在页面服务里重写一遍公式 ——
   抄一份就必然出现「页面说在通道内、执行器说越界」。
3. 🔴 **时间戳字段先打开真文件核对再解析**：历史 jsonl 常见 `ts`，不是 `t`。读错时「参考样本」
   退化成当前样本 ⇒ 偏差 / 速度 / 势能**恒为 0**，而位置、帧龄、状态词全正常 ——
   这是最像「一切正常」的假象。验收时必须让某个量在设备动起来后非零，静止恒 0 不算通过。
4. 🔴 **静止/陈旧阈值用实测抖动，不拍脑袋**：5Hz 真值停着也有 ~1mm 抖动、差分速度 ~1mm/s。
   「设备静止就回看更早的历史轨迹」这类兜底若按 0.05mm 判，永远不触发。
   先量 30s 静止样本的跨度与速度，取约 2 倍作阈值，并把判据写到页面上（「臂静止 · 显示更早的真实轨迹」）。
   陈旧判定同理：阈值要与**消费方**同口径，别自己定一个更严的数。
5. **页面必须显示采样时刻与帧龄**（`age_s`）+ 一个状态词（实时 / 陈旧 / 断流）。
   只给数字读者判不了新鲜度；他自己会拿帧龄当结论。
6. 🔴 **新加的内容放页面第一栏，且默认自动播**：他会打开页面直接看首屏，翻不到也不点按钮。
   新增区块一律插到页头之下第一个 `<section>`（给 `id` 便于 `#anchor` 直达），动画/回放**打开即开播并循环**
   （走完停 ~0.8s 从头再来），页面顶部给一行状态：「▶ 1x 自动循环回放中 / 第 N 遍」；
  暂停按钮仍要有（点一下停、再点「▶ 继续」）。提交给用户时用带 cache-buster 的 URL（`?v=3`）。
  判据：刷新后**不做任何点击**，5 秒内读到的进度/读数必须已经和首屏不同。
7. 🔴 **页面自带 build 戳与帧计数**：页头放 `build <标记> · 帧 N`，N 每 20 帧刷一次（顺手把数据点数/录制时长也写进状态行）。
   用户说「没动 / 没看到」而你自己这边在动时，按这个顺序问：有没有 build 行（没有 = 旧缓存，`Ctrl+Shift+R`）→ 帧号涨不涨
   （不涨 = JS 抛错，`tick` 外面包 `try/catch` 把 message 写到状态行，别让它静默）→ 索引动不动。
   同一句「没动」解释到第二次，就别再解释页面：**换证据形态**，给一个不依赖 JS 与缓存的产物直链
   （`references/phase-portrait.md` §8 的 MP4，挂同一端口）—— 他打开就能看到运动。

## 跟随视图怎么写（不引第三方库）

- 等轴测手写投影（固定旋转矩阵 + 平移 + 缩放），把 mm 坐标投到 canvas 2D；
  点 = 当前位置、短线 = 姿态轴、折线 = 近期轨迹。
- 轨迹分两层：**近期**（最近 60s，实时刷新）与**历史**（设备静止时回看更早的真实路径，用更暗的颜色）。
  这样页面在设备不动时也有内容，不会看起来像挂掉。
- 公差环/阈值线用虚线画，并注明是否各向异性（径向 0.3mm 与轴向 6mm 差 20 倍，画一个环会误导）。
- 页面文案给一句「现在在动什么」，不堆参数名。

## 给已有画布加视图切换按钮（「相」这类单字按钮）

用户只丢一个 URL + 一句「增加一个 <字> 按钮，在画布上」时，按下面做，**不要先问选择题**：

- 按钮浮在画布右上角：外层 `.cwrap{position:relative}`，按钮 `position:absolute;top:8px;right:8px;z-index:2`
  且放在 canvas **之前**的兄弟位置；label 就是他要的那个字，别扩写成「相空间」长标题。
  激活态只改样式不改词义：`textContent = "相 ✓"` + `classList.toggle("on", 激活)`，title 里写两种状态各是什么。
- 🔴 **视图判定的分支必须放在每拍自动重绘的入口**，不能只在 onclick 里画一次：
  `function drawScene(j){ if(VIEW_MODE==="phase"){ drawPhaseView(j); return; } … }`。
  页面每 1~2s 轮询重绘，只在 handler 里切视图 ⇒ 下一个 tick 立刻刷回旧视图，表现成「点了没反应」。
  两种视图共用同一个 canvas 与同一个 2d context；切回时用最后一次数据立即重绘（`if(last) drawScene(last)`）。
- 🔴 **自动定标 + 半透明标注带 = 数据退化成常数时标注带铺满整张画布**：设备静止时 θ 只有 1 种取值，
  坐标轴范围被压到 0，±1° 的容差带就占满全宽，整张画布被刷成一层淡色（实测 70% 像素被
  `rgba(45,212,191,.10)` 盖住），看着像「画布被搞坏了」。给最小跨度：`minSpan = max(12*tol, 6)`（度），
  并在图内写一句「设备静止 · 相点停在势阱谷底」，别让它静默成一片色块。
- 新按钮/新 canvas 的 id 先查重（`grep -o 'id="[^"]*"' <page>.html | sort | uniq -d`），别撞页内已有的文本节点 id。

## 验收（不靠眼睛）

```
curl -s http://127.0.0.1:PORT/api/state | python3 -m json.tool | head -40   # 字段齐全 + 关键值非零
ss -ltnp | grep :PORT                                                       # 监听者是刚起的那个 pid
```

浏览器侧（无视觉工具也能验）：取 DOM 文本核关键读数，再 `canvas.getContext('2d').getImageData()`
**按颜色计像素**：蓝=近期轨迹、灰=历史轨迹、点=当前位置，三者都 >0 才算真画上了。
空画布同样 HTTP 200，页面「能打开」不等于「画上了」。

补三条判据（这次踩出来的）：

- **颜色判据要互斥**：`B>170 && B>R+70` 会把青色容差带也算成「蓝色轨迹」，导致「轨迹很多」的假证据。
  按 RGB 三元组近精确比对，或一轮只断一类颜色。
- **把画布降采样成亮度字符图**确认「画的是图不是色块」：20 行 × 76 列，`. : - + * #` 按亮度分档打印。
  铺满一片同档亮度 = 某条 `fillRect` 盖满了整块（先查标注带的范围），不是产物。
- **真机数据退化时用合成数据验绘制路径**：设备静止时 `trail` 全是同一个点，折线一笔也画不出（蓝像素 = 0，
  但这时不代表代码坏）。造一段 `[{θ,p}]` 直接调 `drawPhaseView({phase:{trail:…}})`，蓝像素涨到几千、
  橙点 >0 即证明绘制与定标都对；然后在汇报里写明「现在是静止所以只有一个点」，别把退化当通过。
- **浮在画布上的按钮要先证明它在最上层**：`document.elementFromPoint(中心)` 必须返回按钮自己（z-index 生效）；
  元素在视口外时 `browser_click` 会落空（点击不报错、状态也没变）—— 先 `scrollIntoView({block:'center'})`
  再点，点完读 `textContent` + `className` 是否变化才算真点到。

## 坑

| 坑 | 症状 | 修法 |
|---|---|---|
| 旧进程还占着端口 | 改完代码、重启「成功」，页面数字和文案仍是旧的 | 新进程只在日志里报 `Address already in use`，`curl` 照样 200（旧代码）。定式：按端口取 pid → 杀掉 → 确认端口空 → 重启 → 用**本次新增字段**能取到才算生效 |
| 判据对象当 dict 用 | JSON 里某段恒为 `null` / 空 | 多是 dataclass，按属性取再 `asdict`；别 `obj['k']` |
| 阈值写在前端 | 换采样率/设备后判据全错 | 阈值放 `/api/state` 一起返回，页面只渲染不重算 |
| 刷新整页重载 | 画面闪、轨迹断 | 只替换数字节点 + 重绘 canvas，不 `location.reload()` |
| 端口被同仓别的脚本硬编码占用 | 你新起的页面把别人昨天的页面顶掉了，用户说「找回来」 | 起服务前先 `grep -rn "<端口>" --include=*.py --include=*.service --include=*.sh .` 看既有占用者（仓里常有 mock/临时服务写死同一端口）；新页面一律用没被引用的端口 |
| 交出去的 URL 是根路径 | 用户打开是 `no route` / 404，而页面其实活得好好的 | 服务的页面常在子路由（`/follow`）而 `/` 直接 404。交 URL 前逐个探：`for p in / /<page> /api/...; do curl -s -o /dev/null -w "$p %{http_code}\n" http://host:PORT$p; done`，只有 200 且正文是 HTML 才算 |
| 页面「丢了」= 临时静态服务没了，不是页面被删 | 重启后昨天那个 `http://host:PORT/xxx.jpg` 404 | 用 `python -m http.server --directory /tmp` 起的服务随重启/清理就没了；**文件本体还在** `zmax_data/<domain>/`。复活 = 重新挂那个目录（`--directory`），不要重做页面 |
| 新 canvas 的 id 与页内已有元素撞名 | `document.getElementById('phase').getContext is not a function`；绘图函数 `return` 掉，画布空白但页面其它数字正常 | 页里常已有同名**文本节点**（如 `#phase` 是 S¹ 读数的 span）。加画布前先 `grep -o 'id="[^"]*"' <page>.html | sort | uniq -d` 看重复，取新名（`phcanvas`）；`$("id")` 缓存也一并改 |
| 在 agent 侧驱动页面演给他看 | 你说「跑了一遍、都正常」，他回「没看到，再走一遍」 | 你的无头浏览器不是他的屏幕 —— 在他屏幕上看到的东西只由**页面自己的默认行为**决定。要么把页面改成打开即自动循环（规则 6），要么给他可复现的驱动方式（URL 参数/按钮）；agent 侧点按钮只能用来自己取证 |
| 回放/动画用 `requestAnimationFrame` | 页面开着但动画一帧不走、进度恒 #0，**没有任何报错** | 浏览器对后台/失焦标签挂起 rAF ⇒ 改 `setInterval(50ms)` + 墙钟推轨迹时间（`tt=(performance.now()-t0)*speed/1000`）；速度在**页面内**比 `轨迹t差/墙钟` 验证（跨 tool call 量会把往返延迟误读成“播放太快”） |
| 播放按钮点了没反应 | 按钮文案变了、动画一帧不走、`js_errors` 可能为空 | handler 引用了别的函数作用域的别名（`D` 只在 `load215()` 里存在）⇒ `ReferenceError` 被事件循环吞掉。handler 首行自取一次：`const D = T215.data; if(!D) return;`；改完在无头页里**真点一次**，读按钮文案 + 进度是否变化才算过 |
| 用户两次说「没动」，你这边画面在动 | 他那个标签页还是旧 HTML（旧版 JS 本来就是坏的） | 让他看 build 戳（规则 7）→ `?v=N` URL → 直接给 MP4 直链；别在「我这边在动」上跟他争 |
| `cv2.VideoWriter(mp4v)` 的视频浏览器「无法播放」 | 页面 video 报 `Unable to play media`，`video.error.code` 非空 | mp4v 是 MPEG-4 Part 2，Chrome 不解码；`ffmpeg -i a.mp4 -c:v libx264 -pix_fmt yuv420p -crf 23 -movflags +faststart b.mp4` 换 H.264（42.9s/880x440 → 313KB）|
| 内嵌 video 不自动播 | 控制台 `NotAllowedError: play() failed because the user didn't interact` | 即使没有音轨也要写 `muted`：`<video muted autoplay loop playsinline preload="auto">` |
| 页内 mp4 拖不动进度条 / 播一遍就卡死 | 服务端对 `Range` 请求也整份回 200 | 路由里认 `Range: bytes=a-b` 回 **206** + `Content-Range: bytes a-b/len` + `Accept-Ranges: bytes`；验收 `curl -s -r 0-1023 -o /dev/null -w '%{http_code}'` 要为 **206**，另测一次整份 `200` 与 `Content-Type: video/mp4` |

## 参考

- `references/phase-portrait.md` —— 相空间相位图（横轴 θ 转角 / 纵轴 p 动量）：先验坐标真会变、等能线与 E=2k 分界线的解析画法、静止→一个点的诚实标注、像素验收。
  用户说「相空间画得不好 / 应该有相位图」时按它做，别拿三维位置视图充数。
  已有画布上要加一个「相」按钮（同一张画布切 空间轴测 ⇄ 相空间）时按 §9：按钮浮层 + 分支放重绘入口 + 最小跨度。
  用户进一步要求「映射真的哈密顿量」时，按里面 §6 的**球摆约化**（r=|TCP| · θ=与 +Z 夹角 · V=g·z · p=I·ω · H=p²/2I+g·z，全部从真值+录制时间戳算）做，别再用 k=1/I=1 的归一玩具摆。
  要「用 215 点轨迹走一遍看效果」时按 §7：独立只读 `/api/traj215` + 真实时间轴回放，**不连执行服务、不下发动作**。

## 汇报口径

- 需求只有一个字/一句话（「加一个 相 按钮」）时：按最合理读法直接做完、给出实测证据，
  末尾用**一句话**给出替代读法（「如果相=导出图片，说三个字我改」）。他会用三个字纠正；
  先抛选择题等于把决策丢回给他。
- 改的是仓库里的页面文件（服务每请求现读 ⇒ 不用重启）：说清文件路径、是否已 commit、他点头再提交。

给三件：① 完整 URL（含 `/api/state`）；② 一句结论（「能跟随」/「还不能」+ 为什么）；
③ 三条实测证据（帧龄、当前位置、轨迹点数或像素计数）。
不要只说「已实现跟随」却不给数字 —— 他会自己打开，也会自己验。
