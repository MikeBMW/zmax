# 定位"用户真正在看的那个面" + 核验"改动真的生效了"（2026-09-26 实测）

配套 SKILL.md 的「第 0 步：先定位 artifact」—— 本节是同一会话后半段的**新板斧与判据**。

## ★ 用户引用的文案 = 指纹，不是精确字符串（本轮最大弯路）
用户说「还是**等待上报**」→ 我按字面 `grep -rln '等待上报'` **0 命中**
→ 据此判定"这不是我的页面" → 又白跑数轮。
真相：代码里写的是 **「等待 4060 上报」（中间有空格）** 与 **「Mac 未上报」**。

```bash
# 拆词搜；只搜最独特的两个字；两词同现
grep -rlnE '等待|上报|未上报' --include=*.html --include=*.py --include=*.js . | grep -v site-packages
grep -rln '等待' . | xargs -r grep -l '上报'
# JS 里中文常是 \uXXXX 转义 → 也搜转义形式（\u7b49\u5f85 = 等待）
# 换分支再搜一遍：同名定义可能在我插错的那份里（死代码）
```
**0 命中的结论只能是「这段文字不在我搜的范围里」，不能是「这不是我的页面」。**
用户能引用的文案，几乎一定来自某个你搜得到的文件。

## ★ 限定 artifact 的三条新板斧（接在"四板斧"之后）
```bash
# ⑤ 用户说的是「手机 APP」→ 找 APK 工程，读它的 loadUrl = 他屏幕上真正加载的页面
find <home> -maxdepth 4 -name 'AndroidManifest.xml'
grep -rn 'loadUrl' --include=*.java <apk_project>/
#   实测: loadUrl("https://<host>/state-3d.html")  ← 又是一个不同的页面

# ⑥ 直接拉线上那个页面，逐字找用户要的字段
curl -s https://<host>/<page>.html | grep -cE 'gpu|显存|vram|硬件'      # 0 = 这页没有该能力
curl -s https://<host>/<page>.html | grep -oE 'fetch\([^)]*\)|/api/[a-z_]+'   # 它的数据源

# ⑦ 结论要有"能不能做"的判断力
#    页面里根本没有硬件的渲染代码 ⇒ 无论上传多少数据都不会显示
#    ⇒ 要么改那个页面（需对方站点权限），要么**自己做一个不依赖它的入口**
```

## ★ 一次动作产生多个产物："还是老样子"时先枚举产物（三轮弯路换来）

用户报「打开 X 还是小窗口 / 一点都没变」时，**不要继续放大、美化你已经改的那个产物**——
「一点都没变」只说明一件事：**你改的那个产物不是他看的那个产物**。

实测经过（同一句抱怨，三个候选产物）：**弹出的浏览器窗口** · **画布节点上贴的实时画面** ·
**页面里的舞台布局**。我先改页面布局、再改窗口尺寸与搬屏，两个产物的尺寸都没动 ⇒
用户原话"还是老样子…一点都没变"；直到他明说"不要在画布上放小窗口，直接打开浏览器"，
才定位到真产物 = **画布节点上那块拼图**（前两轮的改动全白做）。

枚举法（代码 + 屏幕两头夹）：
```bash
# ① 代码里列出这次动作的**全部**可见结果
grep -n "def <回调名>" -A60 <gui文件>.py | grep -nE "Popen|openUrl|setPixmap|start_|show\\(|QDialog"
# ② 屏幕侧列出这次动作到底产生了什么窗口/画面
wmctrl -lG                 # 开窗口了吗？落在哪块屏(x<屏宽 vs 超出)？多大？
scrot -o /tmp/now.png      # 截图 → 按窗口几何裁切 → 量化
```
量化判据（比"我觉得够大了"强得多）：
```python
band = win[int(h*0.40):int(h*0.80)]        # 取舞台中间带(避开工具栏)
col  = band.mean(axis=(0, 2))              # 逐列平均亮度
nz   = np.where(col >= 2.0)[0]             # 纯黑列 = 信箱黑边
print("画面占窗口宽 %.1f%%  左黑边 %d 右黑边 %d" % ((nz[-1]-nz[0]+1)/w*100, nz[0], w-1-nz[-1]))
```
- **报成功前必须读回几何**：`wmctrl -lG` 实测尺寸 + x 坐标。新窗常落在**另一块显示器**，
  `--start-maximized` 在 GNOME 下未必生效（要 wmctrl 补一刀），而**认窗不能只靠标题**
  （标题要等页面加载完才更新）：启动前记下已有窗口 id → 按"新出现的 id"认 → 等足 20~25s →
  搬屏/最大化/激活各做 2 轮 → 再读回几何确认落在哪块屏。
- **Web 页上"图看着小"多半是信箱黑边，不是窗口小**：4:3 画面在宽屏上 `object-fit:contain`
  只能占窗口宽 ~46%（两侧各几百像素纯黑）。修法是用满宽度（默认多格并排）或给"铺满/全屏"按钮，
  不是去改窗口尺寸。
- 用户否掉一个产物后**把它删掉**（并在入口处 stop/clear 历史残留，免得旧方块还挂在那里），
  不是改大、改清晰、改好看。
- 用户喊"赶快修"时也要问一句**二分问题**（"你看到的是画布上那个方块，还是新弹出的浏览器窗口？"）——
  第三次猜错的代价远大于一句话。
- 行为改了，**验收断言同步改口径**：旧断言（如"画布节点已出画面 ✅"）会继续报绿而用户仍看不到；
  新断言要包含**反面断言**（那个产物**不存在**）。

## ★ 对端数据只出现在「对端自己上报的落点」
把 Mac 卡片接到**本机 DDS 桥** → Mac 永远显示未上报；
因为那台机器**根本不往本机 DDS 发**，它上报的是**公网 relay**。
- **核实方法**：读对端自己的上报**载荷**，看它有哪些字段、落在哪个 key，再决定取值来源。
- 对端载荷里的字段常本身就是答案：`training:{active:false,count:0,procs:[]}`
  已经回答了"它那边有没有在跑模型"，比推测可靠。
- 若落点是"最新包覆盖"语义（后来的包顶掉前面的），取值要**重试若干次**
  （单次可能抓到不含对端的包 → 写出 null）。

## ★ 推送成功 ≠ 改动生效（stale ref，比推失败更隐蔽）
从 detached worktree `git push origin HEAD:main` 成功，
但**本地 `main` 引用没更新**；而脚本读的是 `git show main:<path>` → **一直用旧文件**。
表现：**"已推送、已成功"，但线上内容没变**。

```bash
# 判据: 改了文件 + 报成功 + 内容没变 ⇒ 先怀疑 ref 没跟上
git fetch -q origin <branch> && git branch -f <branch> origin/<branch>
# 更稳: 定时脚本 / 常驻服务里直接读远端 ref
git show origin/main:<path>          # 而不是 git show main:<path>
# 终极核验: 从远端回读，用"改动标志"确认
git show origin/main:<path> | grep -c '<新加的函数名/字段>'
```
**"已推送"不是证据；从远端回读到的改动标志才是。**

## ★ 改的那份不是生效的那份（同名定义被后定义者覆盖）
`grep -n 'def _show_link_menu'` 只命中 1 处 → 我在那里加功能；
实际**另一个类里还有同名定义且写在后面 → 后者生效**，我的改动成了**死代码**（点了没反应）。
```bash
grep -n 'def <方法名>' <file>     # 必须看**全部**命中，别停在第 1 条
# ≥2 处时：确认是否在不同 class；Python 同名方法**后定义者覆盖前者**
# 判哪份生效：看它用 self.xxx 还是 self.module.xxx（属于哪个类）
```
**铁律**：改造前 `grep -n` 出所有同名定义，确认要改的就是生效那份，改完 `git diff` 核验位置。

同一族的两个 Web 变体（都表现为"改了但页面上没有"）：
- **服务端热读一个 HTML 文件 + 代码里另有一份内嵌死码页面**：唯一依据是那个文件（按 mtime 热读 ⇒ 改完**不用重启**），
  内嵌那份只是遗留保障；改前先看路由是 `open(<file>)` 还是 `return """<HTML>"""`。
  判据：`curl -s :<port>/<page> | grep -c '<新按钮文字/新文案>'` —— 数**服务端返回的字节**，
  不要数本地文件（本地文件当然有刚写的内容，那证明不了用户会看到）。
- **改动要不要重启，看它在哪一层**：页面的 HTML/JS/CSS 与数据文件 ⇒ 热读，刷新即见效；
  路由表/白名单/常量/接口逻辑（在服务端 py 里）⇒ **必须重启那个进程**才生效。
  收尾时两件都做一次：重启服务 + `curl` 回读页面出现新文案，才算"改到了用户看的那份且已生效"。
- 纯前端改动的零桌面自检（长连接画面会让浏览器根本无法打开页面，没法靠肉眼）：
  数 `<div`/`</div>` 平衡 + 抽内联 `<script>` 嗂 `node --check`（页面 JS 语法错 = 整页白屏）。

## ★ 用户引用的内容名 = 定位真界面的钥匙（比界面名可靠）

用户说「给**三维视图**加五个按钮，对应小红直线、正方形轨迹…」——「三维视图」这个说法在仓库里能命中**好几个页面**
（状态空间 3D 页、手机 3D 页、自包含 Three.js 页、AR 叠加页），逐个试很贵。

**搜他说的那个内容，不要搜界面的名字。**「小红」这种专有名词全局只有 4 处命中，直线指到
`tools/run_along_line.py` → 它的数据源是 `fence_store` → 真正渲染它的页面是 `tcp-ar.html`。
```bash
search_files '<用户嘴里那个专有名词>'          # 小红 / 安全点1 / 某个按钮文字
# 命中可能的数据源文件 → 看它 import 什么 store → 再 grep 哪个页面 fetch 那条接口
```
内容名指向**唯一依据**，唯一依据再指向**真界面**；这一步同时把「轨迹点从哪读」也解决了。

### 用户说「已有的 X」时，先核实 X 真的存在
本例：「已有的正方形轨迹」——`fence_store` 里只有 3 个 box 元素（132×393 / 196×803 / 138×199mm），
**没有一个是正方形**。
⇒ 此时只有两条路：**用几何规则构造**（并标明“构造”）或**明说做不到**。
绝不能把构造出来的东西当成“用户已有的那条”交付 —— 他一看坐标就知道不是他画的。
同理，取不到的点数要写 `0 + 原因`（“机器人这段时间没动”），不能画一条假线凑上。

## ★ 画布类界面的“真画上屏了么”：headless 截图 + 目标色像素计数

没有浏览器自动化时，用系统 chromium 直接截：
```bash
chromium --headless --no-sandbox --disable-gpu --hide-scrollbars \
  --window-size=1500,940 --virtual-time-budget=9000 \
  --screenshot=/tmp/k.png "http://127.0.0.1:<port>/?<auto-load 参数>"
```
- 页面需要**自加载参数**（`?traj=<key>` / `?only=<panel>`）才能在不点按钮的情况下复现某种态 ——
  顺带给用户一个“发链接就能看”的入口，一举两得。
- 判据是**目标色像素数 + 命中像素的 bbox**：
```python
m = (np.abs(im - np.array(rgb)).max(axis=2) <= 26)
ys, xs = np.where(m)
print(m.sum(), xs.min() if m.sum() else -1, xs.max() if m.sum() else -1)   # bbox 能告诉你是“画了但很短”还是“一点没画”
```
- ⚠️ **多画布页面必须先把画布隔离出来再数**：一个 260px 高的 3D canvas 嵌在 940px 的页里，
  整页计数只会得到十几像素，看起来像“没画”。先加一个 `?only=<panel>` 模式把它单独满屏（对手机看也更清楚），再截图。
- 文件大小几乎一样（892515 / 892511 / 892508 B）**不能**说明内容一样，也不能说明轨迹没画 —— 必须数像素。

### 三个“代码看着对、画不出来”的常见机制
1. **重绘被指纹缓存跳过**：绘制入口常是 `drawIfChanged()`，它算一串指纹（轨迹长度、TCP、开关位）再决定要不要画。
   新增了一种可绘制状态却没把它的 key/点数放进指纹 ⇒ 状态变了、指纹没变、**函数直接 return**，屏幕上一点反应都没有。
   修法：① 新状态的字段进指纹；② 状态变更处**直接强制调用绘制函数**，别依赖“变化检测会帮我调”。
2. **取景/自适应先于绘制才有用**：把 off-screen 的点拉回视野靠的是 `fitBox()` 重算相机目标与距离，
   它必须**在绘制之前**跑（`fitBox(); draw();`）。顺序反了就是“点确实在数据里，但投影到视锥外 ⇒ 一次都不落像素”。
3. **一条 `beginPath()` 会被任一 null 投影点毁掉**：投影函数对不可见点返回 null，连续 `moveTo/lineTo` 中间夹一个跳过，
   整条 path 就可能只剩散点。改成**逐段画**（相邻两点一组，各自 `beginPath/moveTo/lineTo/stroke`），断点不影响其他段。

## ★ 「按钮呢?」= 在 DOM 里但在视口外（同一天被问两次）

用户报「**新增的 5 个按钮呢?**」，而 `curl <page> | grep -c 'id="t[1-5]"'` = 5、`display:block`、`opacity:1`
—— 一条都没坏。合计：页面高 3000px、视口只有 577px；按钮先落在右栏卡片 `top≈1009`，搬到三维视图正下方后
变成 `top≈1381`，**两次都在屏幕外面**。

### 一条 console 探针定性（几何 + 重复 id）
```js
(()=>{
  const ids = ['t1','tA1'];                       // 你想查的控件 id
  const buttons = ids.map(id=>{ const e=document.getElementById(id);
    if(!e) return {id, missing:true};
    const r=e.getBoundingClientRect(), c=getComputedStyle(e);
    return {id, top:Math.round(r.top), left:Math.round(r.left), w:Math.round(r.width),
            display:c.display, visibility:c.visibility, opacity:c.opacity,
            inView: r.top>=0 && r.bottom<=innerHeight};
  });
  const se = document.scrollingElement;
  return {viewportH: innerHeight, pageH: se.scrollHeight,
          scrollable: se.scrollHeight > innerHeight + 2,
          dupIds: [...document.querySelectorAll('[id]')].map(e=>e.id).filter((v,i,a)=>a.indexOf(v)!==i),
          buttons};
})()
```
判读：
- `inView:false` + `display:block` + `opacity:1` ⇒ **纯粹在屏幕外**，别去改样式/清缓存。
- `dupIds` 非空 ⇒ 你复制了控件却没换 id；`getElementById` 只给第一个，**第二处点了没反应**。
- `scrollable:true` 而用户仍说看不到 ⇒ 长页面问题（要他滚 1.5 屏 = 不可用），走下面的定式。

### 定式：sticky 一份 + 原位一份，id 不同、handler 同一个
```html
<!-- 顶部工具条: 开页即见, 这些控件在这一条里 -->
<button id="tA1" class="sm">① 小红</button> … <button id="tAoff" class="sm">✕</button>
```
```js
// 两处各自绑同一个动作; 高亮状态在一个地方统一切
[['t1','xiaohong'],['t2','square'],['t3','map'],['t4','safe'],['t5','real']]
  .forEach(([id,k])=>{ const el=$(id); if(el) el.addEventListener('click',()=>loadNamed(k)); });
[['tA1','xiaohong'],['tA2','square'],['tA3','map'],['tA4','safe'],['tA5','real']]
  .forEach(([id,k])=>{ const el=$(id); if(el) el.addEventListener('click',()=>loadNamed(k)); });
// 选中态: 把两批 id 一起 toggle, 别只盖一处(用户会以为点了没生效)
['t1','t2','t3','t4','t5','tA1','tA2','tA3','tA4','tA5'].forEach(id=>{
  const key=['xiaohong','square','map','safe','real'][Number(id.replace('tA',''))-1];
  $(id)?.classList.toggle('on', key===k && !!NAMED[k]);
});
```
第三处重复的那组**改成一句指路文字**（"这五个按钮在三维视图正下方"），不要留三份同 id。

### 🔴 后置刷新必须单独 try，否则成功会被自己的异常吃掉
```js
// 反例(实测把 41 点覆盖成报错): 全页没有 refreshTraj 这个函数, 真名是 refresh
if(typeof drawVR==='function') drawVR();
await refreshTraj();            // ← ReferenceError
// catch 里写 el.textContent='⚠ 请求失败: '+e.message  ⇒ 用户看到的是"按钮坏了"

// 正解: 只有渲染在 try 里; 刷新单独兜住, 失败只 warn
try { if (typeof refresh === 'function') await refresh(); }
catch (e2) { console.warn('刷新失败(不影响已取到的点):', e2); }
```
落盘/显示顺序同理：**先写"拿到了什么"，再写"刷新"** ——反过来时，一次刷新失败就把结论擦掉了。

### 验收循环（真点、真读，不要只看 click 的返回值）
```js
(async()=>{
  const map=[['tA1','xiaohong'],['tA2','square'],['tA3','map'],['tA4','safe'],['tA5','real']], out=[];
  for(const [id,k] of map){
    document.getElementById(id).click();
    await new Promise(r=>setTimeout(r,1400));            // 等 fetch + 重绘
    out.push({id, k, cls: document.getElementById(id).className,
              text: (document.getElementById('pNamed').textContent||'').replace(/\s+/g,' ').slice(0,150)});
  }
  return {viewportH: innerHeight, results: out};
})()
```
- 每条结果里必须有**它自己的结论**：点数 + 来源 + 为什么是 0（"机器人这段时间没走过路"，不许留空、不许画假线）。
- 构造/推演出来的数据要在文本里标出来（`⚠ 构造: 工程配置无正方形元素`），用户一眼能分辨真值。
- 这份页面在**两台主机**都提供服务时，改完 `md5sum` 对一次两边（页面按 mtime 热读 ⇒ F5 即见；
  只有把 HTML 读进内存的服务才需要重启）。
- 🔴 **按钮搬过去了不等于那里能出数**：第二台主机上页面/按钮全部在位、接口也回 200，但 `n=0` ——
  因为数据**唯一依据文件只在本机**（围栏配置 / 建图产物 / 台账快照 / 实测录制）。这类文件都很小，逐个同步过去再复验点数；
  与此同时**页面必须把"为什么是 0"写在结果里**，否则用户把"空"读成"功能没做"。

## ★ 常驻服务引用的脚本放"分支外路径"
新脚本留在仓库里，切分支/stash 就消失 → 服务起不来（实测踩过两次）。
常驻服务的 `ExecStart` 指向 `~/` 等分支外路径，或先 commit 再引用仓库路径。

## ★ 内外一致收尾（用户说"可以关机了"时的清单）
1. 提交**两处**（主仓 + 另一个 worktree/分支），并确认推送后用**远端回读**核验
2. 技能沉淀（新增/更新）+ 记忆更新（压缩腾位，批量原子写）
3. 小版本：**按 VERSION.md 列的位置逐个同步**（本项目是 studio.py 显示位 +
   update_checker 的 CURRENT_VERSION + version_sync 的 zmax_ver）；
   **只改显示位与新增 changelog 块，绝不改历史块**；
   改完 `git diff` 核验"改动只有这几行"
4. 打 tag → 推送 → 等 CI 出产物（要 `releases/tags/<tag>` 里看到资产才算发布）
5. 停测试/调试进程，**保留交付链**（`systemctl is-active` 逐个确认），GPU 归零
