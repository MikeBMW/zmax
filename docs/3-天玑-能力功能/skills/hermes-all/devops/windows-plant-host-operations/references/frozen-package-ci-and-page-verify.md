# 冻结包: 构建参数坑 + 交付页面自验

## CI: workflow_dispatch 的输入默认值会把 Windows 构建搞死

`workflow_dispatch` 的 `inputs.tag` 若默认成非语义版本(如 `dev-snapshot`),构建脚本把它塞进
`version_info.txt` 的 `filevers=()` ⇒ 文件内容出现 `filevers=(dev-snapshot,0,0,0)` ⇒ PyInstaller
执行该文件报 `NameError: name 'dev' is not defined`,整个 Windows 构建失败,而日志里只有
`Failed to deserialize VSVersionInfo` 这种二手信息。

规则:
- 用 API 触发构建时**必须显式传** `{"ref":"main","inputs":{"tag":"vX.Y.Z"}}`,不要只传 ref。
- 构建脚本里加兜底: 版本串不是 `x.y.z` 就从 `VERSION.md` 抓真版本,并对每段做 `isdigit()` 兜底。
- 失败排查顺序: 先看是不是版本号/元数据步骤,再看编译步骤 —— 这类错误发生在打包最前面,后面全是假象。

## 交付页面自验: 别只看 HTTP 200

页面能打开 ≠ 画面是对的。三维/AR 页面必须两段验:

1. 数据段(命令行): 逐个打数据接口,看 `ok` 与数量,例如
   `curl http://<host>:8797/api/sim_bones | jq '{ok,n,L:(.L|length),R:(.R|length)}'`。
2. 渲染段(用代理自己的浏览器): 直接导航到同一个 URL,然后在页面上下文里读全局状态 + 数像素:
   - 读状态: `SIMON`、`SIMB.ok/n` 这类页面全局变量,证明“开关真的开了、数据真的到了”。
   - **枚举所有 canvas 再取样**: 页面上第一个 canvas 常常是视频画面,三维视图是另一个 id(如 `#vr`)。
     只取 `document.querySelectorAll('canvas')[0]` 会得到 0 像素的假阴性 —— 这是最容易误判的一步。
   - 数颜色: 按期望的图层颜色(如左臂青 / 右臂橙)统计像素,`>100` 即证明该图层画出来了。

## 一个可选接口 500 会静默掐死整条刷新链

页面 `refresh()` 里的第一句 `await fetch('/api/traj')` 若返回 500,异常直接跳进 catch,
后面所有更新(读位姿、开图层、拉骨骼)**一行都不执行**,表现为“按钮/开关都在,画面永远空”。

规则:
- 服务端: 可选的辅助接口取不到数据时返回 `200 + {"ok":false, ...空数组}`,**绝不 500**。
- 页面端: 画面上必须出现的关键兜底(有数据就画)放在**独立定时器**里,不要挂在主刷新链尾部。
- 排查“页面不动/空”时,先看主刷新链第一句的接口是否 500,再看渲染。

## 后台进程必须挂到交互会话,不能挂在自己的 SSH 会话上

代理(SSH/终端会话)里 `Start-Process` / `Invoke-CimMethod Win32_Process Create` 拉起的窗口和
服务,会话一断就被回收:表现是“刚查还在,过一分钟没了”。

- 启动 GUI/常驻服务: `schtasks /Create /TN ... /SC ONCE /ST 00:00 /RL HIGHEST /F` + `schtasks /Run`
  (或 `Register-ScheduledTask -LogonType Interactive`),让它活在用户交互会话里。
- `Win32_Process Create` 不能写 shell 重定向(`>> log`): 命令行里出现重定向符会立刻退出。
  需要合并输出就写成 `.bat` 再让任务去跑这个 bat。
- 停进程只按 **CommandLine 过滤**: 同一个 exe 往往同时跑 GUI 和 3 个本机服务,
  按 `Name='xxx.exe'` 一把杀会把刚起来的服务一起干掉。

## 跨平台代码里的“Linux 默认假设”

同一份脚本在 Windows 冻结包里起不来,常见三件套:

- `os.getuid()` / `os.geteuid()` 不存在 ⇒ 用 `getattr(os,'getuid',lambda:0)()` 或 `os.name` 分支。
- 写死的数据根 `/home/ubuntu/...` ⇒ 改成按 `_MEIPASS`/包根探测,Windows 上会解析成不存在的路径,
  表现为“服务起来了但读不到数据/写不出文件”。
- 依赖 `/proc` 或 shell 工具(ffmpeg 之外的 linux 命令) ⇒ 加存在性判断,失败只降级不抛。

判断口径: 服务端口起来了(200)只说明 HTTP 通了,还要看日志里有没有 AttributeError/FileNotFoundError,
以及数据文件是否真的落在 Windows 盘上。

## 用户说“刷新了还是没有”时的三层判定

自己那边验通了、对方还是看不到,不要再改代码,先把**三层**分开:

1. **他的页面是不是新页** — 服务端访问日志里没有他那一轮 `/ar3d` 请求 ⇒ 浏览器直接吐了缓存(或他在看别的窗口/别的端口)。
   对策: 给带版本号的 URL(`/ar3d?b=<n>`)让他新开标签页,并把**构建号写进 `<title>`**,让他一句话就能报“我这页是哪一版”。
   页面响应应带 `Cache-Control: no-store` —— 有了也不排除前端路由/内嵌浏览器缓存。
2. **他的页面是不是在轮询** — **先把自己的代理浏览器导航到 about:blank**,再看服务日志里那个接口的兴趣频率。
   请求还在 = 他的页真在跑新逻辑 ⇒ 问题在图层/机位,不在投递;请求没了 = 他那侧根本没在跑这段码。
3. **图层真的画出来了没有** — 回到像素取数。**像素数少也是“看不见”**: 4px 细线在默认机位下调不过来时,
   用户只会说“没有机器人”。对策: 自动开图层的同时把描边加粗(≥6px)、把点加粗,并把机位对准数据包围盒,
   而不是等他调视角。

口径合并: “接口有数据 + 页面状态真开 + 像素有量 + 标题版本对得上” 四条齐了才算交付;
少任何一条就按上面三层定位,别让用户描述画面。

## 让页面自己上报运行时状态(最强取证,省掉 N 轮问答)

对方说“没有”时,不要靠他描述画面,也不要靠你在自己机器上复现。让**他的页面**把内部状态写回来:

- 页面把关键标志拼进一个 GET(`/api/<x>_diag?...`)的 query:`bld`(构建号)、`vis`(visibilityState)、
  `cw/ch`(画布宽高)、各图层开关、数据量 `n`、数据年龄 `age`、**绘制次数 `drw`**。
- 服务端把这条请求(或它的解析结果)落进自己的访问日志/诊断文件 ⇒ 主脑 `grep` 日志就读到**他那台浏览器**的真实状态。
- 判读: `bld` 旧 ⇒ 他跑的是旧页;`vis:hidden` ⇒ 标签页在后台(不动画);`n>0` 但 `drw` 小 ⇒ 数据到了但没画(见下条)。
- ⚠️ 别把诊断文件写到 `/dev/shm` 之类 Linux 专属路径: Windows 上 `open()` 直接失败,诊断静默全丢。

## 「数据有、画面不动」: 3D 画布是**按需重绘**,没有相机帧就再也不画

这类页面常把渲染挂在“新相机帧到达/用户拖拽”上,而不是 rAF 循环。机器上没有相机(笔记本/无相机站)⇒
帧泵一直失败 ⇒ 即使骨骼/位姿数据每 200ms 都在更新,**画布停在最后一帧**,用户看到的就是“什么都没有”。
判据极简: 诊断里的 `drw` 计数不涨(实测整页只画了 4 帧)。
修法: 数据轮询成功后**主动调用一次重绘**,自己做节流(如 `if(now-last>100) draw();`),
别指望另一个驱动源。验证就看 `drw` 是否持续增长 + 目标颜色像素数。

## 静态资源“接口返回空”= 文件不在 + 路径被写死成 Linux

`/api/urdf`(或任何 `/api/<asset>`)回 `ok:false` 且 body 很小,含义是**服务端找不到模型文件**,不是接口坏了。
两个独立原因要同时修:

- **发布包没带那份资产**: 建模/网格数据常放在源树 `data/database/...` 下、既不进 git 也不进 PyInstaller。
  修: 拷到目标机**所有候选根**的 `data/` 下,并在 CI 里 `--add-data "<workspace>\data\...;data\..."` 固化(几 MB,值得带)。
- **代码写死了仓库根**: `REPO = os.environ.get("ZMAX_REPO", "/home/ubuntu/zmax")` 在 Windows 上
  `os.path.join` 会拼出 `/home/ubuntu/zmax\data\...` 这种混合路径 ⇒ 明明把文件放对了也 `FileNotFoundError`。
  修: 候选链 `env ZMAX_<X> > dirname(__file__) > _MEIPASS > 上溯 1~3 级(冻结包 `_internal`→`app`→安装根) > ~/zmax`,
  取第一个存在的,并让日志报出**最终选中的路径**(报错里能看出是混合路径就一眼定位)。
- 数据可迁移性口径(用户原话“数据都在 data 路径,对不?”): 所有资产按 `data/` 相对定位就对了;
  回答时把**资产名 + 实际路径 + 打没打进包**一起说清。

## 冻结包里哪些能热修、哪些只能重打包

- **能热修**: `_internal\tools\*.py`、`_internal\tools\web\*.html`、`_internal\src\**.py` —— `scp` 覆盖后
  **重启那个服务进程**(Python 模块在 import 时缓存,不重启不生效);HTML 只要 `scp` 完让用户新开 URL 即可。
- **不能热修**: 编译进 exe 的入口/界面模块(如 `studio.py` 主体)—— 改了必须走 CI 出新包。
- 因此每个修复都放到能热修的那一层(工具脚本/参考数据/前端),交付时明确说这版是热修还是新包。

## `schtasks /Run` 回“成功”但进程没起

实测: 任务 Last Run 正常、Last Result `0`,端口依旧没人听。常见原因是**上一实例刚被杀、端口还在 TIME_WAIT**,
服务脚本 bind 失败即退出 ⇒ 任务“成功”但什么都没留下。
可靠做法: 停完 `sleep 10~15` 再起;持久化用
`Invoke-CimMethod Win32_Process -MethodName Create -Arguments @{CommandLine='cmd.exe /c "<bat>"'}`
(bat 里自带 `>> log 2>&1`)—— 父进程是 WMI 服务,不随 SSH 会话回收。起完**读端口 + 读日志尾部**双证。
