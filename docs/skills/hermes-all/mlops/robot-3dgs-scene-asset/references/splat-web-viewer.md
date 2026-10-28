# 3DGS `.splat` 网页查看器 (交付面)

触发: 用户要「在窗口里转着看高斯球渲染后的场景」/要资产链接给手机看。
产物 = `gs.ply`(真尺度) + `gs.splat`(查看器格式) + `renders/*.png`; 本文件只讲"怎么让人真的看到"。

## 1. 先验资产字节, 再怪查看器

每高斯 **32B**, 记录序: 位置 Float32×3 · 尺度 Float32×3(**已激活=线性**) · 颜色 RGBA uint8 · 四元数 4×uint8。
`gsplat.export_splats(..., format="splat")` 收的是**原始参数**(log 域 scales / logit opacities), 它自己按查看器约定激活
⇒ 读 `.splat` **不需要再 `exp`**(读 `.ply` 才按 log/logit 反解)。

字节级 probe(只读, 一眼定性):

| 检查 | 期望 | 不对时的含义 |
|---|---|---|
| `len % 32` | == 0; 高斯数 = len/32 | 格式不是这套 |
| 位置 | 有限、与工作区尺度同量级(米) | 全 0/NaN = 资产废 |
| 尺度 | **全为正的小数**(实测 p50 ~2e-4 m、p99 ~1e-2 m) | 大片负数/挤在 −12~0 = log 域被直接写出 ⇒ 标准查看器尺度全错 |
| 颜色 RGB | 均值与采集画面亮度同量级(画面亮度 104 ⇒ RGB≈105) | 全 0 = 颜色通道写错 |
| alpha | 大多不透明(实测 61% ≥128、仅 2% 为 0) | 全 0 = 不透明度写错 ⇒ 透明黑屏 |
| 四元数 | 非全 0 | 全 0 = 朝向废 |

若尺度分布过小(实测 59 万高斯 / 0.5m 场景、p50 0.2mm)⇒ 相机稍远就看着稀疏发暗; 要更"实"是调**致密化/正则**
(少而大), 别用查看器参数掩盖。

## 2. 服务端: 挂在既有页服务上, 别另起端口

- **同源是硬要求**: 页面与 `.splat` 走**同一个**服务(页面 `/gsview` + 资产 `/gs/latest.splat`)。
  公网反代入口(形如 `/st/<页>` → 反代回本机端口)会自动继承 ⇒ 本机、局域网、手机都能开, 且不踩
  "https 页取 http 流"的混合内容红线(页面 https、资产 http = 必被拦)。
- 路由四件套(照这个形状加, 别每次重设计):
  - `/gsview`(+`.html`/别名) → 页面, **热读** `tools/web/gs_view.html`(按 mtime 重读 ⇒ 改页面**不用重启**)。
  - `/gs/list` → 资产清单 JSON: 名 · 字节数 · mtime · 留出 PSNR · 高斯数(从各资产目录的 `train_report.json` 取)。
  - `/gs/latest.splat` → **选 mtime 最新**的 `<资产>/gs.splat`(页面默认就吃这个, 新资产建完即出现)。
  - `/gs/<名>.splat` → 定点资产。**名字必须白名单正则 + realpath 落在资产根目录内**;
    越界(`/lib/../../etc/passwd.js` 这类)、非白名单扩展名、路径不存在 ⇒ **都要实测回 404**(写路由时顺手验)。
- 🔴 **这类页服务通常没有通用静态文件分支** ⇒ 同域查看器 JS 必须另加一条白名单静态路由(如 `/lib/...` → `tools/web/lib/...`,
  同样 realpath 限定 + 扩展名白名单)。不加 = JS 404 = 页面能开但**永远黑**。
- 现场要能看出"看的是哪一版": 页面状态条上标**建图时刻 + 留出 PSNR + 高斯数**(清单里就有)。

## 3. 查看器壳页(antimatter15/splat 一类 WebGL .splat 查看器)

- 把查看器 JS **下到同域**(`tools/web/lib/splat/`)并把它的默认资产地址改成**同域相对路径**
  (`params.get("url") || "gs/latest.splat"`, base = `location.href`)。出厂默认打 CDN ⇒ 弱网/手机内置浏览器必被拦, 永远转圈。
- 🔴 **DOM 契约**: 它会 `getElementById` 并写 `canvas / message / progress / spinner / fps / camid`。
  **少一个就是 `TypeError: Cannot set properties of null (setting 'innerText')` 抛在 main() 里** ⇒
  页面看着正常、资产也拉到了, 但**一直黑**。自己写的壳页要把这 6 个节点都建出来
  (`#progress` 用 `<div>` 而不是 `<progress>`; 多余的那几个用 `position:fixed;left:-9999px` 藏起来)。
  壳页还应带: 资产下拉(切换 = 带 `?a=<名>` 重新引导) · 重载按钮 · 状态条 · **错误直接显示在屏幕中央**(不自静默转圈)。
- 🔴 **相机口径 = 黑屏的头号原因**: 查看器默认视图对着**原点**、距离写死(实测 ~6.55,
  是为 10 单位级的展示场景调的); 而我们的 `.splat` 是**真尺度世界坐标**(实测场景中心 (0.57,−0.05,0.31)、半跨度 0.4~0.5m)
  ⇒ 场景要么在视野外、要么只占画面百分之几 = 看着全黑。**浏览器侧定式**(不动资产文件、不改训练、不改服务端):
  1. 拉 `.splat` → 对每条记录的位置整体减质心(尺度不动, 仍是真尺寸; 记录序固定, 位置就是每 32B 记录的前 3 个 float)
     → `new Blob([ab])` → `URL.createObjectURL` → 让查看器吃这个 URL;
  2. 用 `location.hash` 传视图矩阵 `[1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,dist,1]`,
     `dist = max(半跨度)×2.6`(这套实现把平移放在**最后一行**; 查看器读到 hash 会同时**关掉自动轮播**);
  3. 质心/半跨度/相机距离写进状态条 —— 现场要看得见"这一版有多大多远"。
  ⚠️ 交付前**先看 `.splat` 的尺度分布**再判"太稀": 尺度 p50 亚毫米级时, 相机再近也是稀疏微光(见 §1)。

## 4. 无头取证: "到底渲染出来没有"(别用错的取法给出假黑/假亮)

- WebGL 画布默认 `preserveDrawingBuffer=false` ⇒ 在 **rAF 之外** `readPixels` / `drawImage` / `toDataURL`
  读到的是**已清空缓冲**, 会给出**假黑**(实测同一个页面: 场外取样全 0, rAF 内取样有真实内容)。
- 可信取法: 在 `requestAnimationFrame` 回调里(**排在查看器本轮绘制之后**)把画布 `drawImage` 进一个 2D 画布
  → `getImageData` → 统计 平均亮度 · 非黑占比 · 唯一色数 · alpha 占比。
- 判据: 唯一色 == 1 且亮度 == 0 ⇒ 真黑; 出现纯白(通道和 765)、唯一色上百 ⇒ 有真实内容。
- ⛔ **PNG 体积不是证据**(黑图也能因 alpha 噪声有几十 KB, 而带内容的图可能只 16KB) ⇒ 一律**解码看像素**。
- 控制台要先读: 查看器通常 `console.log` 出**加载到的高斯数**; `js_errors` 为空 + 有高斯数 = 资产与 JS 都到位,
  这时才轮到怀疑相机/GL(无头软件 GL 与真机不同, 现场目检永远优先)。

## 5. 运维口径

- 页服务常是**手工起的进程**(无 systemd): 改**路由**要重启, 改**页面 HTML** 不用重启(热读, 改完核 md5 即可)。
  重启**用启动脚本, 别手写 kill+命令**: 仓库里那条推流启动脚本自己做完了全套 —— 按**端口**找回 pid(不用 `pkill -f`,
  会匹配到执行它的 shell 自己) → 停 → 抬 fd 上限并 `closerange` → 用**原参数**以 nohup 拉起 → 打印复核(两个端口 200 + 各路相机映射)。
  起来后自己核: 两个端口都 200 · 相机路仍是你选的那台(`/stats` 的 label) · 新路由 200(如 `/gs/latest_display.splat`)。
  一句话: **一次一版 + 回读才算生效**, 别把"重启命令成功"当成"服务已带新代码"。
- 页面真源判定: `curl -s :<port>/<页> | md5sum` 必须等于 `md5sum tools/web/<页>.html`;
  资产同理: `curl -s :<port>/gs/latest.splat | md5sum` == 最新资产文件的 md5。
- 🔴 `tools/web/lib` 常被 `.gitignore` 里的 `lib` 规则挡掉: vendored JS **没入库**, 克隆后的仓库页面 404 白屏。
  修法 = 加 `!tools/web/lib/` + `!tools/web/lib/**` → `git check-ignore -v <文件>` **验证不再忽略** → `git add -f` 补提交。
- 入口挂法: 在既有站页加一个**相对链接**(`href="gsview"`)—— 相对路径在"根路径访问"与"子路径反代"两种入口下都解析正确,
  写成绝对路径会在反代下 404。

## 6. 大资产(百万高斯/几十 MB)的加载体验: 挑显示副本要线性, 加载期必须有画面

### 6.1 挑 KMAX 个显示高斯 = 两趟线性 + 直方图, 绝不 `sort(比较器)`

`idx.sort((a,b)=>alpha[b]-alpha[a])` 在 200 万+ 高斯时比较器被调用约 4000 万次 ⇒ 主线程卡十几秒~几十秒,
现场看到的就是"白屏/点开就假死", 而服务端毫秒级、console 也不报错。线性定式:

```js
var KMAX = 60000;
if (n > KMAX) {                              // n 大 = 必须降采样显示
  var u8 = new Uint8Array(ab), hist = new Uint32Array(256), i;
  for (i = 0; i < n; i++) hist[u8[i*32+27]]++;          // ① alpha 直方图(每记录第 28 字节)
  var acc = 0, thr = 255;
  for (; thr >= 0; thr--) { acc += hist[thr]; if (acc >= KMAX) break; }
  if (thr < 0) thr = 0;
  var nb = new ArrayBuffer(KMAX*32), sd = new Uint8Array(nb), w = 0, raw = n;
  for (i = 0; i < n && w < KMAX; i++)                   // ② 阈值以上全要
    if (u8[i*32+27] > thr) { sd.set(u8.subarray(i*32, i*32+32), w*32); w++; }
  for (i = 0; i < n && w < KMAX; i++)                   // ③ 不足从阈值桶补满
    if (u8[i*32+27] === thr) { sd.set(u8.subarray(i*32, i*32+32), w*32); w++; }
  ab = nb; n = w;                                       // ④ 之后所有步骤用新缓冲
  setMeta('显示降采样 ' + n + ' / 原始 ' + raw + ' 高斯(保最实) · ');
}
```
砍掉的是**最透明的那批**(雾状粒子), 视觉几乎无损; 顺序稳定、无比较器 ⇒ 亚秒级。

### 6.2 加载期不许留空屏

- 页面里垫一张 `#pre` 静态图(<img src="gs_render.png">, 全屏 `object-fit:contain`, 盖在 canvas 上),
  `loadViewer()` 之后 `setTimeout(hide, ~6s)` 撤掉; 顶部放一个「🖼 参考图」按钮 toggle 它。
  这样**从打开到渲染完成任何一刻都有画面**, 且这条兜底同时覆盖"没拉下来"和"WebGL 起不来"。
- 宿主页(工位页那格 iframe)另加**超时退回**: N 秒后 `iframe.contentDocument.title` 仍读不到 ⇒
  收起 iframe、显示静态图、并把提示改成"要可拖拽的 3D 点「↗ 新窗口打开」"。

### 6.3 三种"白屏"的区分(用户看不到、你也看不到时)

| 现场念出的一行字 | 成因 | 现场动作 |
|---|---|---|
| 停在「拉取 …」 | 同源 6 连接被页面上多路 MJPEG/快照占着, 几十 MB 请求轮不到 | 「🔄 重载」或「↗ 新窗口打开」(独立连接池) |
| 「高斯 <N> · 已居中缩放…」而画面空 | 拉到了但没画出来: WebGL2 被禁/走软件渲染 | 让他看 `chrome://gpu` 的 WebGL2 是否 "Hardware accelerated" |
| 屏幕上有红框 | 查看器 JS 抛错(DOM 契约缺节点/资产格式) | 直接要那句原文 |

### 6.4 无头验收的边界
软件 GL 下重渲染会占满主线程: 同一个页面**先能 eval、之后连读 DOM 文本的 eval 都超时**(不是页面坏了)。
所以验收证据用: ① 页面字节 == 仓库文件 md5 ② `/gs/latest.splat` 200 且字节数 == 资产文件 ③ 首次加载时查看器
console 里的"加载到 N 个高斯" ④ 用户念出的那一行字。**别把"应该会显示"讲成已验证**, 如实说看不到他的屏幕。

### 6.5 真正的收口: 服务端先预算一份轻量显示副本(不把全量发给浏览器)

§6.1 只解决了"排序"这一段; 下载 + 解析几十 MB 同样在宿主页**同一个主线程**上, 而且和视频流抢**同一个**
同源连接池。症状就是用户说的「打开太卡, 卡住鼠标和其它窗口」(不是他自己那台机器的问题)。
定式 = **服务端算好一份轻量副本, 页面默认只吃它**; 全量只走显式入口。

服务端预算(纯 numpy, 与前端同一套挑选口径: 每 32B 记录的第 28 字节 alpha 取前 K 大):

```python
def _gs_display_splat(name, kmax=60000):
    src = f"{ROOT}/{name}/gs.splat"; dst = f"{ROOT}/{name}/gs.display{kmax//1000}k.splat"
    if os.path.isfile(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
        return dst                                    # 按源 mtime 失效, 不是每天重建
    a = np.fromfile(src, dtype=np.uint8)
    a = a[:(len(a) // 32) * 32].reshape(-1, 32)       # 整记录切, 不切碎 32B 边界
    if a.shape[0] > kmax:
        a = a[np.argpartition(a[:, 27].astype(np.int16), -kmax)[-kmax:]]
    a.tofile(dst)
    return dst
```

- 缓存文件名**不能叫 `gs.splat`**(资产清单是按这个名扫描目录的, 否则轻量副本会被列成一个新资产)。
- 路由: `/gs/latest_display.splat` + `/gs/<名>.display60k.splat`, **放在 `p.endswith('.splat')` 那条宽分支之前**
  (否则会被全量分支先吃掉)。找不到就 404, 让前端回落全量。
- 实测: 284 万高斯 / 86.7MB → 6 万高斯 / 1.8MB(47×, 预算 0.04s; 缓存命中后毫秒级)。
- 前端: 默认拉轻量副本(取不到再 `catch` 回落全量), 另给一个「🐘 全量(卡)」按钮(`?full=1`)—— 全量不是不可用,
  只是变成**用户要它才拉**, 且提示"要看全量就在新窗口"。状态条写明当前是「🪶 轻量副本」还是「🐘 全量」。
- 宿主页那格: **默认不加载 3D**(静态图秒出), 用户点了才把 iframe 指向查看器; 既省连接又不会卡住鼠标。
