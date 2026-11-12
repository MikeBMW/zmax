# 给画布节点加右键入口 (看该节点此刻的输入帧/数据)

菜单本体在 `tools/gui/simulink_module.py` 的 `_show_node_menu()`：先 `menu.addAction()` 逐个条件建项，
再 `menu.exec_()` 后一条长 `elif chosen == a_xxx` 分发链。按这个顺序改，六条都要做到。

## 0. 看画面一律开浏览器，不弹独立 Qt 窗口

凡是「看一眼画面」的入口（单帧 / 渲染帧 / 直播流），一律浏览器新窗口，不要独立 Qt 窗口。
用户会对独立窗口直接打回（"也用浏览器打开，不用单独窗口"），一次做对省一轮返工。

- 页面落 `tools/web/dl/*.html`，右键里调 `open_render_stream_window(url=_dl_page_url("xxx.html"))`
  （现成实现：`chromium --new-window` 再 `wmctrl -a` 抬前台，失败才退 xdg-open；`webbrowser` 在 snap/chromium 下常只塞后台标签，看着像没打开）。
- `_dl_page_url(page)` = `http://<局域网出口 IP>:8799/dl/<page>`，host 用 UDP connect 取，
  这样同一条 URL 手机也能开；需要固定入口时用 `ZMAX_DL_BASE` 覆盖。
- 已经写好的独立 Qt 看图窗口要**删掉**，别留两套口径 —— 菜单、文件、注释三处只认浏览器这一路。

## 1. 条件项必须在 if 之前声明 `a_xxx = None`

菜单项只在某类节点上出现时（例如只在 YOLO 节点），若漏了这行，其它节点右键走到
`elif a_xxx is not None` 会直接 `NameError` —— 整条菜单失效，而且只在「点别的节点」时复现，
最容易漏测。新增任何条件项，先回头把 `a_xxx = None` 补上，再写 `if` 里的 `addAction`。

菜单项文字不要带 emoji（缺字形 ⇒ 黑块），行为用文字说明，例如
`当前看到的单帧 -> 浏览器打开 (YOLO 实际输入那一帧)`。

## 2. 跨进程只能靠固定文件名落盘

引擎节点（systemd 常驻）与 GUI（studio.py）是两个进程：节点里的模块级缓存（`_YOLO_CACHE` 之类）
GUI 读不到，别指望传内存对象。做法是节点每拍把产物原子写到固定路径（`tmp + os.replace`，
消费方轮询才读不到半张图 / 半截 JSON）。

- 固定三件套最省事：原图（取证）+ 画框版（命令行/汇报直接用）+ json 元数据（源/时间/帧龄/权重/检出/gaps）。
- 浏览器要读的再写一份副本到 `tools/web/dl/`（jpg + json），目录不存在就跳过写入。
- 写入必须**静默失败**：旁路落盘不许把感知链路带崩，`except Exception: return None, None` 即可。
- 落盘要节流（节点本身通常已被周期参数节流到 ~2Hz），否则每拍写 jpg 会把 IO 打满。

## 3. 静态页投放：用 8799 现成的只读服务，不新起端口

`tools/dashboard_server.py`（:8799）白名单里的 `/dl/<file>` 每次请求都从磁盘读，
**新增或改 `tools/web/dl/*.html` 立即生效，不需要重启任何服务**；它本身就是只读、可随时起停、
与在役链路无关。加浏览器入口优先走它，比改 8802/8791 或在役服务安全得多。

- 它的 CT 表只覆盖 html/json/apk/png/js/css；`.jpg` 会以 `application/octet-stream` 发出。
  页面里用 `fetch(url,{cache:"no-store"}).then(r=>r.blob()).then(b=>img.src=URL.createObjectURL(b))`
  绕开 content-type（`<img src=/dl/x.jpg>` 也能显示，但 blob 这路在浏览器上更确定），或者干脆落 `.png`。
- 页面轮询用固定间隔 + 查询串破缓存（`?t=Date.now()`），json 的 `t`/检出没变就不重画，
  避免闪烁和空转；创建新 blob 前 `URL.revokeObjectURL` 旧的那个。

## 4. 帧的定义与零副作用

「当前看到的单帧」= 这一拍**实际喂进网络的那一帧**（节点内部落盘），不是重新取图、重新渲染、
重新推理。重取会抢相机/抢渲染，且和节点那一拍不是同一帧，「看到的」就不再是「送进网络的」，
用户当场能看出两张图不一致。

## 5. 画面自身要标状态

源、拍照时间、帧龄、权重、检出数（含框尺寸/conf）压一条横幅；超过阈值没新帧就变橙写
「帧已停 (感知节点没在跑)」，不要拿旧帧冒充实时。路径可选中复制，另存为时顺带同名 `.json`。
检测框在页面里按 json 的原帧像素坐标 × 显示尺寸/原尺寸 画 overlay（`position:absolute` 的 div 即可），
别只给一张画好框的位图 —— 要能拿坐标和 json 对账。

## 6. 复现与验收（不改常驻服务也能验）

- 先 `systemctl cat <svc> | grep -E 'ExecStart|WorkingDirectory'` 确认**服务用的是哪个解释器**：
  引擎跑 `gui-venv311`，不一定是 `venvs/lerobot-venv`；用错 venv 会缺依赖或走另一份代码。
- 用同一个 python 起独立进程直接调节点函数（`node_xxx({'log': print})`），看产物是否落盘，
  再 `json.load` 打印源/时间/检出/框坐标 —— 这一步同时证明「节点真写了」和「消费方读得到」。
- 节点源在独立进程里没有画布内存状态，`_canvas_source()` 返回空 ⇒ 用 `ZMAX_L2_SRC=real|ar|sim`
  环境变量兜底（节点代码里本来就是「画布优先、env 兜底」）。
- 页面验收用真浏览器，不只看 curl：`browser_navigate` 打开页面，`browser_console` 取
  `img.naturalWidth/clientWidth`、框元素的 `style` 与 json 的 box 对账、横幅文本是否带源/拍照时间/帧龄；
  再 `curl` 一次局域网 IP 的同一 URL（手机要能开），静态资源 200 + 字节数一并记录。
- 改完 `simulink_module.py` 或引擎节点代码后，**两个进程都要重启才生效**；按红线只停不起、重启要点名。
  交付时明说「菜单项/落盘要重启 studio.py 与对应引擎服务才看得到」，并附页面 URL 与离线实证产物路径。
