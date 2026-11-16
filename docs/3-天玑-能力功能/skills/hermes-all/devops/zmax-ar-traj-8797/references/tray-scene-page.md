# 摆盘场景页 /tray（`__TRAY` 分支）

> 必读四步，读完再动手：
> 1. 共用文件里**所有删/裁/换默认值都必须 `if(__TRAY)` 门控**，`/ar3d` 一个字不许变；
>    反过来也要门控：**新增的摆盘按钮/物体在 `/ar3d` 上必须隐藏**（见「反向门控」一节），
>    只把它们加进 `KEEP` 白名单是不够的 —— 白名单只在摆盘页收别的按钮，管不到反方向；
> 2. **隐藏任何 fixed 面板前先 grep 谁在量它的 rect** —— 置 `display:none` 后 rect 全 0，取景会静默错位；
> 3. **显示过滤只改画不改台账**（料盘/槽/插孔都在 `FENCES` 台账里，别删数据）；
> 4. 收工前两页各量一遍：`/tray` 与 `/ar3d` 的按钮数、围栏数、`VIEW.CX`；
> 5. **一轮一个单一目的的 commit**（中文标题写清"删掉什么 / 加什么 / 挪到哪"）+ push，回复直接给
>    "用户 Ctrl+F5" + 毫米坐标 + 屏幕像素数；他说"回退"就是把上一轮那条 `git revert` 掉，不手删。
>    改完要报"改了什么"而不是复述过程；尺寸/位置全部给实测数（mm 范围、px、被遮障像素数），不给形容词。

> 在末端 / `tool1` 上加夹具、夹爪、工装几何（含大寰选型口径与"自建正交基"做法）见 `references/end-effector-fixture-on-tool1.md`。
> 用夹具把某工位的盘搬到另一工位（高度公式、IK 代价函数选择、逐点续解、连续动画）见 `references/tray-carry-motion.md`。

同一份 `tools/web/tcp-ar.html`，`location.pathname` 进 `/tray`、`/tray.html`、`/baipan` 时 `__TRAY=true`，
只切四样：场景默认开关、左栏白名单、取景、显示过滤。渲染/几何/投影全复用 `/ar3d`，两页不会各自漂移。
服务端 `tools/tcp_ar_server.py` 路由白名单要有这三个路径；改 `.py` 要 `sudo systemctl restart zmax-traj-ar`，
改 `.html` 只要刷新（响应头已是 `Cache-Control: no-store` —— 拿 `curl -D -` 确认过再怀疑缓存，别拿"你没刷新"当解释）。

## 干净场景底线
- `drawFences()` 在 `__TRAY` 下直接 `return` —— 料盘/槽/插孔/相机盒/旧轨迹/标定预览全在 `FENCES` 台账里，
  一条都不画；`drawTrayModules()` 同样 `return`（否则盘里那批模块会重新出现）。
- 只留：实验桌 + 箱体 + 双臂(URDF) + 中央相机 + 坐标系 + 光模块 + **托盘（周转盘 / 4#方盘）**。
- **托盘是同一套画法的多个实例**：`drawTrayPan(g,pr,T)` 收一个 spec（`{show,name,L,W,H,wall,cx,cy,fill,inner,edge}`），
  当前三个盘（都是一条 spec，别复制绘制函数）：
  - `TPANL` / `TPANR` 左盘 / 右盘 545(L)×380(W)×25 —— 绿 `#2f6f4f` / 蓝 `#3b4f86` ⇒ x 350~730，
    y 505~1050 与 -550~-5（各贴桌面长边一头，关于 `TAB.cy` 对称）。
  - 4#方盘 315(L)×230(W)×40 —— 棕 `#8a5a2b` / 内腔 `#4a2f16` / 棱 `#e0b070`，**同一个 SKU 有三个实例**，各占一个名字
    （标签也按名字出，否则几条都写「4#方盘」分不清）：
    `TPAN2` 左上盘 x 870~1100 / y 735~1050（贴 `(x1,y1)`）、`TPANT` 右上盘 x 870~1100 / y -550~-235（贴 `(x1,y0)`）、
    `TPANM` 中方盘 x 350~580 / y 93~408（`cx = TAB.x0 + W/2`，`cy = TAB.cy`）。
  - `TPAN5` 中上托盘 545(L)×380(W)×25 —— 青 `#356b7d` / 内腔 `#173039` / 棱 `#8fc4d6`，x 730~1110 / y -40~505。
    远端那条带被侧盘挤到只剩 370，**标称 380 照写，多出的 10mm 探出桌面远端边沿**（用户口径「宽是 380, 可以探出桌子边沿」）；
    靠侧盘那侧仍贴 x=730，长度 545 贴满 `右盘`(y≤-5) 与 `左盘`(y≥505) 之间的空档。
    ⚠️ 别为了"塞进桌面内"擅自把 `W` 改小成 370 —— 先报差 10mm 可以，但用户点名要标称值时会再让你改回来并接受探边；
    探出量 `x1 - TAB.x1` 要在回复里报数。探边只改变视觉/干涉口径，不放松"与其它盘不重叠"这条校验。
    ⚠️ 原来这里放过 `TPANU`「中上盘 4#方盘」，用户改口要 545 长的托盘后**换掉**（不是叠加）——同一格只留一个。
    远端带 x 870~1100 是一列竖排（y 分三段），近端带 x 350~730 放侧盘与中方盘 —— 新增盘先看哪条带还空。
  **所有托盘一律贴机器人侧桌沿**：`cx = TAB.x0 + W/2`。用户会点名「要靠着机器人这边儿的边沿」——
  按桌面 X 居中摆会被打回一轮；新加盘直接照这条算 `cx`，别再居中试。
  长度方向按用户指的位置定 `cy`（「桌子中间」= `TAB.cy`；「左右两边」= 沿 Y 贴两头、关于 `TAB.cy` 对称）。
  盘多了以后按"带"校重叠：近端带 x 350~730（侧盘 + 中方盘）、远端带 x 870~1100（三个 4#方盘竖排 y -550~-235 / 93~408 / 735~1050），
  两条带 x 不交 ⇒ 只要带内 y 不碰就必然不重叠；落位后用矩形相交断言复核一遍，别用目测。
  （曾有的周转盘 310×230×45 青盘 `#2e6b86` 已被用户点名「删掉 长310 的周转盘」整块移除：定义/绘制/标注/按钮绑定全删，
  连 `T= T||TPAN` 这种默认参数也要改成 `TPAN2`，否则残留引用静默抛错。要再加盘就照同一个 spec 再造实例，别复制函数。）
- **成组的盘（一摞 N 个）不要写成 N 条独立 spec**：`TP8` / `TPB8` 是块 spec `{show,n,L,W,H,gap,cols,rows}`，
  位置由 `block8Range('tray'|'target')` 从桌面角推出包围盒（`'tray'` 贴 `(TAB.x1, TAB.cy+TAB.w/2)`、`'target'` 贴 `(TAB.x1, TAB.cy-TAB.w/2)`），
  `drawBlock8()` 用 `i%cols / floor(i/cols)` 摆 n 个（第 9 槽空着就是 8 个），`drawBlock8Target()` 只画线框
  （`rgba(255,209,102,.12)` 填充 + `#ffd166` 棱）。换摆法只改 `cols/rows/gap`，绘制代码不动。
  ⚠️ 这套 `TP8/TPB8` 已被用户「不对，错了，回退」整块 `git revert` 掉，**当前代码里没有它**；
  留下的是方法（块 spec + 包围盒推导 + 目标位只画线框），下次要用直接照这个形状重建。
- **新物体和现有物体占同一块桌面时，别删旧的、也别全开着**：旧 spec 的定义和按钮都留着，只把它 `show:false`、按钮去掉 `on`，
  回复里点名「默认关掉了，点一下就回来」。删掉会丢用户此前点名要的东西，全开又会穿模（下一句就是"怎么叠在一起了"）。
  `L` 沿 Y、`W` 沿 X；靠机器人侧的盘就 `cx = TAB.x0 + W/2`（贴住近端桌沿），长度方向 `cy=TAB.cy` 居中；
  落位后要核两件事：**全落在桌面内**、**两盘互不重叠**（实测间隙 30mm）。
- 盘子画法：外壳长方体（面 + 棱两色）+ 内腔下沉 ~90% 高度，底面贴 z=0、顶沿 z=H；内腔色不要用太接近场景暗部的色，
  否则差分/肉眼都分不出"画了没有"。
  判据：临时切 `TPAN.show` 前后各渲染一次做像素差分 —— 差分 bbox 就是盘的屏幕footprint（实测 101×50px / 3314 像素），
  落在桌面投影范围内才算画对；只数"接近盘色的像素"会被别处同色几何骗（实测内腔色散在整幅画面上）。
- `drawTable()` 有 `__TRAY` 早退分支：桌面 + 4 条腿落地 + 两条下横撑；
  龙门架立柱、上横梁、角码、框架标签都不画。**尺寸标注不在这个函数里画**，见下节。

## 桌面摆位：先算放不放得下，再定「左上 / 右上」
需求形如"左上放 N 个盘、右上用同样 N 个盘的边界框标出"时，**先做算术，再画**：
1. 块尺寸 `bw = cols*W+(cols-1)*gap`、`bl = rows*L+(rows-1)*gap`；
2. 桌面宽 750 只并得下 3 个 `W=230` ⇒ 8 盘的紧凑块是 3 列×3 排(填 8) = 694×949，**不是** 2×4(460×1266)；
3. 两个块并排要 `2*bl`：`2*949 = 1898 > 1600` ⇒ 这张桌上两个全尺寸块**必然重叠 ~300mm**。
   不要假装不重叠，也不要在用户没点头时偷偷缩小 —— 把数字报给他，并给出唯一干净的替代（N 个盘**叠成一摞**：
   占地 `L×W`、高 `n*H`，目标框画成同一个长方体）。
4. **屏幕上的「左上 / 右上」必须用真投影算，别猜、也别用探针近似**：`VIEW` 不是全局变量（console 读会
   `VIEW is not defined`），但任何绘制函数都收 `pr` ⇒ 包一个收 `pr` 的函数把它捞出来：
```js
var o=window.drawTrayPan, pr=null;
window.drawTrayPan=function(g,p,T){ pr=p; return o.apply(null,arguments); };
drawVR(); window.drawTrayPan=o;
var q=(x,y)=>{ var r=pr([x,y,0]); return [Math.round(r.u), Math.round(r.v)]; };
```
   实测（980×577 画布、`VR.dist=1.80`）：`(x1,y0)`=(509,204)、`(x0,y0)`=(546,215)/`(x1,y1)`=(206,356)。
   结论：`x1` 远端那两个角在上方，**屏幕左上 = `(x1, y1)`**（远端+左臂侧）、右上 = `(x1, y0)`；按世界轴"上=+Y"猜会摆到反角。
   ⚠️ 用"把 spec 缩成 40mm 当探针再差分"得到的是 bbox 中心，与真实角点差 40~70px（曾得到 554/578 这类数），
   只能判"大概在哪一侧"，定坐标必须用 `pr()` 直接投影。
   θ 这条透视很陡：远端右角距相机最远，同一个 230×315 盘在左上角占 ~130×75px、在右上角只有 **~38×33px / 837 像素** ——
   画得对但看着极小，别当"没画"去改代码；判"有没有画"用 `show` 前后差分像素数，判"该不该这么大"用四角投影。
5. **「在 X 角放一个盘」默认是新增，不是搬移**：把已有实例改 `cx/cy` 挪过去，用户下一句就是「中间的找回来，不要删啊」。
   做法：新建一个 spec 实例（新名字 + 自己的标注），旧的保持 `show:true` 原地不动；同一个 SKU 的多个实例共用一个按钮（`bPan` 一次管 4 个 4#方盘），
   不同尺寸/种类的盘各给一个按钮。
6. **整块功能被否掉时用 `git revert <commit>` 回滚，别手删**：revert 一条提交就把"新几何 + 新按钮 + 白名单项 + 标签"一次退干净，
   还能保留下次直接捡回来的代码。回滚判据：`grep -c <新函数名>` 归零、页面字节数回到上一版、五个盘 mm 范围与标签条数复测一致。
7. **"这位置还能再放一个么"先跑落位搜索再回答**：把现有盘的 `(x0,x1,y0,y1)` 列成矩形表，10mm 步长穷举候选位，
   两种朝向都试（`380×545` / `545×380`），同时校验"在桌面内 + 不与任何矩形相交"。
   实测口径（四个 4#方盘 + 两个侧盘之后）：最大连续空位只剩 x 730~1100(**370**)×y -230~730(960)；
   `545×380` 的盘差 10mm 放不下，`4#方盘 315×230` 放得下。回答就把这个数报出去（"横向最多 370，要 380"），
   再说一句要让它能放需改什么（桌宽 +10~15mm 或侧盘离沿 15mm），别让用户以为可以硬塞。
8. **报完"放不下"之后用户仍点名要 ⇒ 下一轮就直接摆上，把宿让写进回复，不要再劝**：他说「可以，先摆上我看看」/「要放一个 545 的盘」
   就已经拍板了。做法：把当格能容下的尺寸当实尺寸建 spec（例：545×**370**×25，而非标称 380），
   落位后照旧跑矩形相交校验，回复里单独一句说清"宽只给了 370，要严格 380 得动侧盘或加宽桌面"。
   反过来也成立：他要的东西跟已有盘抢同一格时，**换掉那个格的盘**（4#方盘 → 545 托盘），不要两个叠着画。

## 桌子对面再加一台从机器人（协作摆位）
需求形如"桌子对面加一个从机器人、朝桌子、两台一起合作"时，**不要新建任何模型**：
现成的 `drawChassis` / `drawTopCam` / `drawUrdf` 全都只通过 `pr` 把世界坐标投到屏幕上 ⇒ **换一个 `pr` 就能整台复用**。
```js
// base 系 → 世界：绕竖直轴转 180°（点反射 = Rz(180°)，不是镜像，左右手不翻）
var SLAVE={ show:true, mx:0.725, my:0.25, x:1.45, y:0.50 };
function slavePr(pr){
  var mx=SLAVE.mx, my=SLAVE.my;
  return function(w){ return pr([2*mx-w[0], 2*my-w[1], w[2]]); };
}
function drawSlaveBase(g,pr){      // 箱体：画桌子之前
  if(!SLAVE.show || !g || typeof g.beginPath!=='function') return;
  drawChassis(g, slavePr(pr));
}
function drawSlaveTop(g,pr){       // 中央相机 + 一条臂：画桌子之后
  if(!SLAVE.show || !g || typeof g.beginPath!=='function') return;
  drawTopCam(g, slavePr(pr));
  drawUrdf(g, pr, LINKM, {R:[[-1,0,0],[0,-1,0],[0,0,1]], t:[SLAVE.x,SLAVE.y,0],
                          fill:'#46648c', stroke:'#a8c6ea', alpha:1});
}
```
- **用户会补一句「单臂机器人也有箱体、也有中央相机，只是单臂」**：一开始只画一根 `_box3` 立柱会被打回。
  正解是上面这套 `slavePr` —— 箱体（同款 600×800×750，本体 680+轮 70，前脸 HMI 朝桌子）+ 立柱式中央相机（`axis1H()` + D435 俯 35°，方向也跟着转 180°）+ **一条**臂。
  复用前提：被借的函数**所有几何都经过 `pr`**；有写死屏幕坐标的（`g.fillRect` 贴字那种）借过去会错位，要单独处理。
- **「单臂要变成右臂」= 装到它自己的右手侧，不是换 FK**：朝 `f`、上 `u` 时右手方向 `r = f × u`。
  从机器人朝 `-X` ⇒ `r = (0,+1,0)` ⇒ 臂基座 `y = 0.50`（机身中线 +250mm）。这正好等于主机器人右臂的位置
  （主臂 `y=0` 即中线 −250mm，绕竖直轴转 180° 后变 +250mm）。**别用镜像 `x→-x`** 去凑，镜像会把右手变成左手。
  判据：`LINKM['tool1'].t` 过一遍 `{R,t}` 后应为 `(784, 526, 298)`（y>0 在它右手侧，x 已伸到桌面上方），
  与主臂 `tool1 (666,-26,298)` 隔着桌子相对。
- `drawUrdf(g,pr,M,X)` 第 3 参是 FK 结果（`LINKM`=右臂当前姿态）、第 4 参是刚体变换 `{R,t,fill,stroke,alpha}`
  ⇒ 一台机器只给 `R,t` 加配色即可，不用 IK、不用第二套 URDF。
- **遮挡顺序是手画的，这个渲染器没有深度缓冲**：从机器人在桌子外侧 ⇒ 必须拆两段 ——
  箱体（以及任何 `z<0` 的东西）放在 `drawTable` **之前**，否则会"透"到桌面前面；
  相机与臂放在 `drawTable` / `drawChassis` **之后**，否则被桌面盖住。
  判据：`TAB.show` 开/关两次差分，桌子在时可见像素比全貌少一截箱体（实测 13511 → 12019，被挡 1492px）。
- **中央相机开关是全局 `TCAM.show`**：关掉「📷 顶视相机」两台机器人的相机一起消失（整幅影响 100223px）——
  别以为是"只关了主机器人"，也别为此给从机器人再造一个独立开关。
- 加完第二台必须重算机位：`VR.dist 1.80 → 2.35`（实测落 2.39），否则对面那台在画外，用户会以为没加。
- 新按钮进白名单（`bSlave`「🤝 从机器人」），绘制入口一律 `if(__TRAY)` 门控，`/ar3d` 不许出现第二台。

## 左栏白名单（只留看场景的开关）
`bFrames bUrdf bMod bArmR bArmL bStretch bPan bPan5 bPanSide bSlave bCamTop bChs bTab bFlr bSim`（实测 15 个按钮；新增按钮必须同时进这张白名单，
否则按钮被 trim 掉、代码却在找它 ⇒ 点了没反应/静默 null）。
- 托盘开关按"一个 SKU 一个按钮"给：`bPan` = 「🧺 4#方盘」管 `TPAN2/TPANM/TPANT.show`（同 SKU 的多个实例同开同关）；
  `bPan5` = 「🧺 中上托盘」单独管 `TPAN5`（尺寸不同就单独一个按钮）；
  `bPanSide` = 「🧺 左右托盘」管 `TPANL/TPANR.show`（两个侧盘同开同关）。
  多实例按钮写成"任一没开就一起开"：`var on=!(A.show&&B.show&&C.show&&D.show); A.show=B.show=C.show=D.show=on;`，
  别用取反单个实例的写法（会出现"按了没反应"的半开态）。
  按钮文案要跟盘子实际叫什么一致（删了 310 盘就把「🧺 周转盘」改掉，别留旧名）。
  盘关掉时它那两条长/宽标签也必须一起消失（覆盖层遗留问题见下节）。
- 回放/单步/同步/轨迹/围栏/节拍这些摆盘还没定义 ⇒ 按"祖先链"整块 `display:none`，别只按按钮隐藏
  （会留下"相对点数/游标 215/215/真机也走/左臂位姿"这类非按钮文字）。
- 右臂合成一个 `🦾 右臂`：`bArmReal` 不进白名单并显式隐藏。**开关只许切一个独立总变量**（`VR.armShow`），
  `drawVR` 里每条画臂路径都先查它：`VR.real`（真机臂）、`VR.simArm`（仿真/落地臂）、`PREV` 幽灵臂、
  `drawModuleBox`、`tool0/tool1` 三轴。**不要**写成 `bArmR` 的 click 里 `VR.real = VR.simArm`。
  机制：`VR.real` 还有别的写者（AR 模式轮询、镜像看门狗每 1.5–2s 把它置回 true），同步过去的 false 下一拍就被冲掉 ⇒
  画面照旧有臂、按钮却是灭的，用户看到的就是「点了隐藏还在显示」。独立总变量没人翻得回去。
  判据不看按钮 class，看绘制次数：钩 `drawUrdf` 记第 4 个参数（`X.t[1]≈0.5` 即左臂），关掉后应为
  右臂 0 次 / 左臂 1 次 / `drawModuleBox` 0 次；再点回来三者都恢复。
- 零散横幅/浮窗按 id 一起压掉：`#visBar`(愿景条) `#uphBox`(全流程并行 UPH) `#uphPill` `#uphChip` `#idealBtn`
  `#tactPanel` `#tactArrow` `#zflow`(左下「🤖 全流程」状态条) `#mjframe` `#mjtag` `#mktDock`。
- `#tactPanel` `#tactArrow` `#zflow` 是**异步 `innerHTML` 建的**，只在 trim 里按 id 隐藏会被后插回来 ⇒
  注入一条 `<style>`（如 `#trayClean`）用 `display:none!important` 压死。
  ⚠️ 注入时**每条规则各写一行，绝不能拿 `;` 串成一条**：`textContent='a{…};b{…}'` 里那个顶层分号会让浏览器
  把**后面所有规则整段丢掉**（第一条还生效，之后静默失效 ⇒ 会以为"样式没应用"，实际是被解析器吃了）。
  用 `[ 'a{…}', 'b{…}' ].join('\n')`，写完 `st.sheet.cssRules.length` 数一遍条数对不对。
- 开关文案不加「(关)」这类后缀（用户会问「这啥意思」）—— 开/关靠按钮高亮表达，实际状态写进画布上的状态牌。

## 取景与那个 CX=0 的坑
取景：`traySceneInit()` 里 `VR.auto=false; VR.tgt=[0.55,0.30,0.10]; VR.dist=1.80`。

`CX` 不是画布宽的一半，而是"可见区中心"：

```js
let _ovw=0;
const tp=document.getElementById('tactPanel'), cr=$('vr').getBoundingClientRect();
if(tp && !tp.classList.contains('hide') && tp.offsetWidth>0){   // ← 守卫必须有
  const pr2=tp.getBoundingClientRect();
  if(pr2.width>0) _ovw=Math.max(0, Math.min(w, cr.right-pr2.left));
}
let CX=(w-_ovw)/2;
```

把节拍栏 `display:none` 后它的 rect 全 0 ⇒ `cr.right-0` = 画布右边界 ⇒ `_ovw=w` ⇒ `CX=0`，
场景被推到左边缘外(桌面投影 u 会变负)，看起来像"相机坏了"。
修好后判据：`VIEW.CX ≈ 490`（980 宽画布）、桌面四角投影全在 `[0,w]×[0,h]` 内。

## 左臂 tool1 + 光模块
左臂没有独立关节角时 `LARM.q` 为 null ⇒ `LARMFK` 为 null（渲染照抄右臂），要退回链矩阵：

```js
const LF=(LARMFK && LARMFK['tool1']) ? LARMFK : (__TRAY && LINKM && LINKM['tool1'] ? LINKM : null);
const W=larmXform(), t1=LF['tool1'], AX=_cols(_m3mul(W.R, attR()));
const O=[0,1,2].map(i=> W.R[i][0]*t1.t[0]+W.R[i][1]*t1.t[1]+W.R[i][2]*t1.t[2]+W.t[i]);
```
左臂在右臂基座 +500mm Y 的镜像位；实测模块落在右臂末端镜像点（右臂 tool1 y=-26 ⇒ 左臂 y=+474）。
三轴用同一 `AX` 画红X/绿Y/蓝Z + `L·tool1` 标注，只加在 `__TRAY` 里。

## 一个开关必须管到「这个物体的每一条绘制路径」
右臂在画面上至少有四条独立路径，只关一条就还会留东西：
- 骨架：`drawUrdf` 真机路径看 `VR.real!==false`、仿真路径看 `VR.simArm!==false`；
- 末端光模块：`drawModuleBox` 原来只看 `VR.mod`，与臂开关无关 ⇒ 臂关了模块还悬在半空；
- `tool0/tool1` 坐标系：直接读 `TCP.frames` 真值 ⇒ 臂关了轴还在（只保留世界系 `base`）；
- `SIM骨骼`：`SIMB.R` 单独一条，`SIMON` 开着时完全不吃臂开关。
做法：`drawVR` 里先算一次 `const _rArmOn=(VR.simArm!==false)||(VR.real!==false);`（再派 `_hideArmInTray`），
各层都用这一个变量门控，别在每个函数里各判一遍。

## 「点了关了，还在显示」——先证明哪一层在画，别猜
一次拿三样证据：包 `drawUrdf/drawModuleBox` 数调用次数 + 看传参里的平移量、抓 `fillText` 看还剩哪些标注、
对开关前后两帧做像素差分定位变化区域（逐像素 `|Δ|>12` 计数 + bbox）。差分区域落在臂上 ~7k 像素 ⇒ 确实关掉了。
若关完还剩一条臂，那通常是**镜像的另一条臂**（左臂 +500mm Y，屏幕上只差 ~100px，肉眼分不清）：
解法不是继续删，而是让画面自己说明 —— 每条臂挂名牌（`tool1 · 右臂` / `左臂 tool1`）+ 一块状态牌
「🦾 右臂: 显示/已隐藏 · 🤖 左臂: …」，用户就不用靠按钮文案猜。

## 标注/文字必须画在整帧最后，且自带对比度
尺寸线、文字牌写在 `drawTable` 里 ⇒ 后面的箱体、双臂都盖在它上面，字被压成一片黑（用户会说"看不到"）。
提成全局函数（`trayTableDims(g,pr)`），在 `drawVR` 末尾（`drawCfgPts` 之后）调用；其它叠加层同理。

**看不见就换渲染通道，不在 canvas 颜色上来回试** —— 阶梯最多两级：

1. **一级（canvas 内一次做到位）**：纯黑底板 + 白框 + `bold 16px`，先黑描边 `strokeText` 再白 `fillText`；
   尺寸线再往外挪 50mm（`x1+0.07→0.12`、`y0-0.07→0.12`），让数字落在桌外深色区而不是浅木色桌面上。
2. **二级（用户仍说看不见 ⇒ 立刻上）**：数字整体改 **HTML 覆盖层**，canvas 只留尺寸线。
   实测证据链：钩子显示 `fillStyle` 在 `fillText` 调用时刻已是 `#ffffff`、坐标在画布内，画面上依然没字 ⇒
   继续改颜色只是再浪费一轮，换 DOM 后用户当场就看见了。

**机制（别跳过这步去改颜色）**：脚本开头给 `CanvasRenderingContext2D.prototype.fillText/strokeText`
打过全局补丁，开关是 `var VR_TEXT=false;`（默认就是 false）：
**画布上所有文字默认一个像素都不画**，与颜色、字号、字体、坐标全都无关。
- canvas 字看不见时第一件事查 `window.VR_TEXT`，而不是调色；它是"全关文字减干扰"的总闸。
- 要在 3D 里稳定显示的信息（尺寸、状态、名牌）一律走 DOM 覆盖层；canvas 侧 `label()` 首行判 `#trayDims` 存在即 return。

### 让 canvas 注记整体恢复可见（摆盘专用）
用户报"还有好几个区域的字符串也是黑色看不到"时，那些注记往往**只画了 `rgba(0,0,0,.85)` 底板、字被 VR_TEXT 拦掉** ——
看上去就是一排黑块，不是颜色问题。摆盘页要读注记就两步一起做：
1. `traySceneInit()` 里 `window.VR_TEXT=true;`（只影响 `/tray`，`/ar3d` 保持 false 不动）；
2. **每条注记都加「黑底板 + 纯白字」**，不是只把暗色刷白：
```js
var P=CanvasRenderingContext2D.prototype, _f=P.fillText;
P.fillText=function(txt,x,y){
  if(!(typeof __TRAY!=='undefined'&&__TRAY) || window.VR_TEXT===false) return _f.apply(this,arguments);
  var prev=this.fillStyle;
  try{                                   // 按对齐方式算外框, 先铺底板
    var w=this.measureText(String(txt)).width, sz=parseFloat(this.font)||11, x0=x, al=this.textAlign;
    if(al==='center') x0=x-w/2; else if(al==='right'||al==='end') x0=x-w;
    var y0=y-sz, bl=this.textBaseline;
    if(bl==='middle') y0=y-sz/2; else if(bl==='top'||bl==='hanging') y0=y;
    this.fillStyle='rgba(0,0,0,.78)'; this.fillRect(x0-3, y0-1, w+6, sz+4);
  }catch(e){}
  this.fillStyle='#ffffff';
  var r=_f.apply(this,arguments); this.fillStyle=prev; return r;
};
```
- **只刷「亮度<0.5 的暗字」不够**，实测仍有三类读不出：没有底板的标注（`tool0` 浅灰字直接压在青色臂网格上，对比度 3.3:1）、
  8px 彩色点位小标（暗蓝/暗黄褐的「?号位」压在彩点上）、`#535F6B` 这类中灰说明行。
  底板由 wrapper 自己铺 ⇒ 不再依赖"注记原来的底板有没有被场景盖住"，也不再依赖文字自身颜色。
- `strokeText` 不要一起加底板（会画两层）；描边只做描边，对比度交给 fillText 的底板。
- 验收判据（逐条、别只看全图）：钩 `fillText` 记下每个 `(text,x,y)`，对每条取 `x±` ~170×32 区域数亮度 >0.85 像素，
  **24/24 全部 >3** 才算过；`/ar3d` 仍 `VR_TEXT=false`、161 按钮、无 `#trayDims`。
- 开关打开后画面会出现全部注记（地面/箱体/相机/臂/模块/点位名）——用户嫌多就按条的给，别整块关回去。

### 反向：用户改口"除了尺寸以外全隐"时，只关字不够
`VR_TEXT=false` 只拦 `fillText/strokeText`；注记的深黑底板是 `fillRect` 画的，**字没了底板还在** ⇒
画面上留一排空黑框，用户会当成"还是黑的看不到"。要连底板一起收：
```js
var P=CanvasRenderingContext2D.prototype, _fr=P.fillRect;
P.fillRect=function(){
  if((typeof __TRAY!=='undefined'&&__TRAY) && window.VR_TEXT===false){   // 只拦注记那种深黑半透明
    var c=String(this.fillStyle||'');
    if(/^rgba\(\s*0\s*,\s*0\s*,\s*0\s*,\s*0?\.(7|8|9)/.test(c) || /^#0{3,6}$/i.test(c)) return;
  }
  return _fr.apply(this,arguments);
};
```
- 白字 wrapper 留着无害（它首行就判 `VR_TEXT===false` 直接放行），两种模式共用一个补丁集。
- 判据三条一起看：`fillText` 调用次数（被拦也算调用）不算数，要看**画布近白像素**（有注记 3623 → 关掉后 859，差掉的 2764 全是注记）；
  `fillRect` 命中深黑底板应为 0 次实际落笔；DOM 尺寸标仍 `children.length` 全在。
- 关注记后残留的几百个亮像素是场景自身的亮边/高光，不是文字 —— 别为了清零去改场景配色。

### 二级：HTML 覆盖层（实测唯一生效的做法）

```js
function trayDimDom(pr){
  var box=document.getElementById('trayDims');
  if(!box){                                   // 建一次, 之后每帧只改 left/top/textContent
    box=document.createElement('div'); box.id='trayDims';
    box.style.cssText='position:fixed;left:0;top:0;width:0;height:0;pointer-events:none;z-index:60';
    document.body.appendChild(box);
    for(var i=0;i<3;i++){ var d=document.createElement('div'); d.id='tdim'+i;
      d.style.cssText='position:absolute;white-space:nowrap;transform:translate(-50%,-50%);'
        +'font:700 15px ui-monospace,monospace;color:#ffffff;background:rgba(0,0,0,.92);'
        +'border:1.5px solid #ffffff;border-radius:5px;padding:2px 7px';
      box.appendChild(d); }
  }
  var cr=document.getElementById('vr').getBoundingClientRect();
  var items=[['长 '+TL, pr([x1+0.12,(y0+y1)/2,0])],
             ['宽 '+TW, pr([(x0+x1)/2,y0-0.12,0])],
             ['高 '+TH, pr([x1+0.06,y1+0.06,fl/2])]];
  for(var k=0;k<items.length;k++){ var d=document.getElementById('tdim'+k), q=items[k][1];
    if(!q || !isFinite(q.u) || !isFinite(q.v)){ d.style.display='none'; continue; }
    d.style.display='block'; d.textContent=items[k][0];
    d.style.left=Math.round(Math.max(cr.left+70, Math.min(cr.right-70, cr.left+q.u)))+'px';
    d.style.top =Math.round(Math.max(cr.top+16,  Math.min(cr.bottom-16, cr.top+q.v)))+'px'; }
}
```

- 定位 = **画布 `getBoundingClientRect()` + 投影 `u/v`**（`position:fixed`），必须夹在 `cr.left..cr.right` 内，
  否则数字被窗口边缘切掉；`pointer-events:none` 保证不挡鼠标旋转/缩放。
- 覆盖层存在时 canvas 的 `label()` 首行要 `if(document.getElementById('trayDims')) return;` —— 否则两套文字叠在一起。
- 判据：`#trayDims.children.length` + 每块 `textContent` / `getBoundingClientRect()` 是否落在画布 rect 内 /
  `getComputedStyle(d).color`。**不要数像素**判文字（见下节"自验"）。
- **覆盖层「建一次就不管」是错的，每帧要核对子节点数**：外层 `div` 可能在某次早期调用里已建好、但内层循环没跑完
  （异常/时机被打断）⇒ 之后每帧 `getElementById` 都非空、永不再建子节点，整块牌一个都不出现，控制台却无报错。
  做法：`if(box && box.children.length!==N){ box.remove(); box=null; }` 再走建分支 —— 幂等重建。
  判据不是"元素存在"，而是 `children.length===N` 且每块 `style.display` 为其显示值。

**尺寸只留数值标，不要标题条**：桌子 `长 1600` / `宽 750` / `高 750` 各贴在自己那条尺寸线旁；
托盘一律**只标长/宽、不标高**（用户口径），且**盘删了标签也要跟着删**：
现在是 15 条 —— 桌子「长 1600」「宽 750」「高 750」+「左上盘 / 中方盘 / 右上盘 各 长 315 / 宽 230」
+「中上托盘 长 545 / 宽 370」+「左盘 长 545」「左盘 宽 380」+「右盘 长 545」「右盘 宽 380」，
长标在盘左侧（`x0-0.06`）、宽标在盘后侧（`y1+0.06`），全部走同一个 `items` 数组（盘用 `[TPAN2].concat(TPANSIDE).forEach(...)` 生成）。

- 字号口径：桌子三条 **12px 粗体**（用户嫌 15px 大）、内边距 `1px 5px`、边框 `1.2px`；两块以上标签时必须两两量中心距，
  实测最近 75px 才不叠；桌子「长」标签挪到 `y0+0.18` 靠后一端，给周转盘标注让位。
- **加标签要改建 DOM 的循环次数**：`for(var i=0;i<3;i++)` 写死 3 ⇒ 新增第 4/5 块时 `getElementById('tdim3')` 是 null，
  标签静默消失；条目数组 `items` 和 div 数量必须同步（只许多建，别少建）。
- **条目变少时也要显式隐藏**：隐藏某个物体后 `items` 从 5 条掉回 3 条，`tdim3..6` 不会自己消失 ⇒
  上一帧的文字留在画面上（用户会以为"关不掉"）。fill 循环之后再补一条：
  `for(var kz=items.length;kz<box.children.length;kz++) box.children[kz].style.display='none';`
- **两套坐标别混着比**：DOM 覆盖层的 `style.left/top` 是**视口坐标**（`cr.left+u`），而 `getImageData` 读的是**画布内坐标**；
  直接拿 787px 去跟画布 399~500px 的差分 bbox 比会误判"标签飞了"，比之前先减 `cr.left`。
不要再加「桌子 长1600 × 宽600 × 高750 mm」这类汇总条，也不要往画面下方状态行（`$('pVr')`）重复一份 ——
两处都是会被点名删掉的冗余（"删掉这个小文字条"）。数值对比度够就行，不加标题、不加单位说明牌。

- **长/宽别写反**：`TAB.w`=长 1600mm（沿 Y），`TAB.x1-TAB.x0`=宽（沿 X），`TAB.h`=高 750mm。
  写反了画面和状态行会各说一套（实测出现过 `长600 × 宽1600`）。
- **桌面尺寸是实测几何，不是装饰参数**：定版 `x0=0.35 / x1=1.10`（宽 750）× 长 1600 × 高 750，地面 z=-750。
  用户报"宽度增加到 750"时改 `TAB.x1` 并向远侧（机器人前方）长，**近端桌沿 x0 不动**；改完必须重算派生量：
  托盘 `cx`（跟桌面中心）、尺寸标签、以及伸展/够角的落点（`TAB.x1` 变了，可达性结论也要重跑，见 arm-pose-gestures.md）。
  `TAB` 是 `/ar3d` 与 `/tray` 共用的几何 ⇒ 改它等于两页一起改；`/ar3d` 默认 `TAB.show=false` 不显示桌子，所以只在用户手动打开「🧪 实验桌」时才看得到。

## 画布主题与配色：深色是既定口径
本页**默认深色**（画布 `#070a0e`、左栏 `#0d1117`）。白底方案用户已明确否掉（"还是改成原来的背景"）——
不要因为某次"看不清"就整体换主题；看不清先按上节加描边/底板，再不行换 DOM 覆盖层，主题不动。

若哪天确实要做浅色主题，一次性做完并留一行回退路径，别散改常量：
- 画布 `drawVR` 的填充、`body`/`#vr`/`#vrcard` 三处都要设，且**要内联再设一次** ——
  `mjToggle()` 里有 `$('vr').style.background='#070a0e'`，inline 会盖掉只写在样式表里的规则；
- 左栏 `html body.tray #vrRail`（加 `html` 前缀才压得过 `body.vrfull #vrRail`），按钮白底深字、开态蓝底白字；
- 白底后必须重配颜色：地面 `rgba(244,246,249)` + 网格 `#e4e9ef`；桌子木色加深；坐标轴名牌 `#e6edf3`→`#1f2328`
  （近白字在白底上彻底消失，最容易漏）；尺寸文字改深 gold/green/blue；
- 判据：`getComputedStyle` body/#vr/#vrRail + 抓 `fillText` 打印每个标注的 `fillStyle`。
- 回退时**每一处都要真的回退**：画布填充、`body`/`#vr` 内联背景、`mjToggle()`、地面/桌面/名牌颜色、注入的
  白底样式规则，一漏就是一页半白半黑（用户下一句就是"还是改成原来的"）。

## 姿态动作按钮（伸展等）
「🙆 伸展」这类"点一下把两条臂摆成某个姿态"的需求，走关节空间直接摆姿势（不 IK、不下发真机）——
求解器、动画、末端模块跟随、复位与 `/ar3d` 隐藏的完整做法见 `references/arm-pose-gestures.md`。

## 加按钮：handler 的插入锚点会决定它到底是加了一次还是每帧一次
左栏按钮的 click handler 全部写在 `bSlave` 那一带的 `if($('bXXX')) $('bXXX').addEventListener('click',…)` 区（4000 行以后）；
而 `drawVR` 里到处是 `// 🤝 从机器人(桌面对面)` 这类**同句注释**。拿注释当 patch 锚点会插进 `drawVR` ⇒ 每帧加一个监听器：
- 症状：点一下"没反应"或状态翻不回来 —— N 个监听器一起 `DIM.show=!DIM.show`，偶数次抵消；点两下才变一下也属这类。
- 规矩：**锚点取已有 `addEventListener('click'` 行**，不取注释；插完 `grep -c "bXXX').addEventListener" ` 必须等于 **1**，
  并用行号确认落在 handler 区（~4000+）而不是 `drawVR`（~2500）里。
- 新按钮同时要进 `KEEP` 白名单（否则被 `trim()` 隐掉，`$('bDim')` 为 null ⇒ click 静默不绑）。

## 总开关式按钮（一键隐藏一类东西）
形如「关闭所有尺寸」给一个**总变量**，不要在每条标注上各加一个 flag：
```js
var DIM={ show:true };                                  // 总闸
function trayDimDom(pr){
  var box=document.getElementById('trayDims');
  if(!DIM.show){ for(var i=0;i<box.children.length;i++) box.children[i].style.display='none'; return; }
  …原有逐条定位逻辑…
}
```
- 首行整批 `display:'none'` 再 `return`，比逐条判更省事，也不会漏掉最后几条；重新打开靠下一帧正常走一遍就恢复。
- 判据：连点 4 次看 `children` 可见条数 `15→0→15→0` 且按钮 `classList.contains('on')` 同步；只测一次容易漏"翻不回来"。

## 从 FK 结果里读某个 link 的位姿：`LINKM` 是 `{R,t}`，不是 `{origin,x,y,z}`
`LINKM`（=`urdfFK(q)`）每个 link 是 4×4 式的 `{R:3×3, t:[m,m,m]}`（米）。直接 `LINKM['tool1'].origin` 是 `undefined`，
而这段又常套在 `try{}catch{}` 里 ⇒ **不报错、什么都不画**，看着像"这功能没生效"。正解一律走 `_frameOf(M,name)`：
```js
var t1=_frameOf(LINKM,'tool1');     // → {origin:[x,y,z], x:[…], y:[…], z:[…]}
```
- 从机器人末端补 tool1：它是右臂 FK 绕竖直轴转 180° 再平移到 `(SLAVE.x, SLAVE.y, 0)` ⇒ origin 与三轴同样被转：
  `origin' = [SLAVE.x-o[0], SLAVE.y-o[1], o[2]]`，轴端 `o' - d*L`（x/y 取反、z 不变）。
- 判据（实测）：从机 tool1 `(784, 526, 298)mm`、屏幕 `(414,253)`；主臂 `(666,-26,298)`，两臂隔桌相对。

## 小叠加层的像素取证：用「饱和度」+ 2×2 矩阵，别拿精确色号数像素
三轴（`#ff5d5d`/`#5dff8f`/`#5db8ff`）这种小东西只有几十像素，按色号 ±70 数容易被抗锯齿/覆盖色骗成 0：
```js
const sat=(cx,cy,rad)=>{ const d=ctx.getImageData(0,0,cv.width,cv.height).data; let n=0;
  for(…y…x…){ const i=(y*cv.width+x)*4, mx=Math.max(d[i],d[i+1],d[i+2]), mn=Math.min(d[i],d[i+1],d[i+2]);
    if(mx-mn>90) n++; } return n; };      // 高饱和才算: 灰蓝臂身(#46648c)不算
```
- 归因用 **2×2**：`图层开×物开 / 图层开×物关 / 图层关×物开 / 都关`，净贡献 = `A-B-(C-D)`（实测 154px）。
  只做「图层开 vs 关」会把主臂/桌面的同色几何一起数进去。
- **量到 0 先证绘制函数本身**：直调 `drawSlaveTop(ctx,pr)` 不吞异常地跑一次；再量。直接调能画出而 `drawVR` 里没有 ⇒
  是调用路径（`try/catch` + 参数形状）问题，不是绘制代码问题。
- 坐标对不上先查 DPR：`cv.width / cv.getBoundingClientRect().width`，等于 1 才能拿 `pr()` 的 u/v 直接当 `getImageData` 坐标。

## 自验（浏览器 console 直接跑）
**读像素前先让出一拍**：`X.show=…; drawVR(); await sleep(250~300)` 再 `getImageData`。
`drawVR()` 返回 ≠ 像素已落盘 —— 同步读实测拿到 `diff=0`，会把"已经画好的东西"误判成"没画出来"，然后去改本来是对的代码
（同一段夹具几何等一拍后 2964px，不等就是 0）。判据两条一起报：调用计数（证路径活着）+ 等帧后的像素差与 bbox（证真落画面）。
0. **先断言页面真的在这个 URL 上**：`location.href` 不是 `/tray` 就重新导航再测。
   导航失败后 console 会落在 `about:blank`，`document.querySelectorAll('*')` 返回空 ⇒ 所有扫描都得出"没有问题"的假阴性。
1. 绘制计数：包 `drawTable/drawChassis/drawTopCam/drawUrdf/drawFences/drawTrayModules/drawModuleAt/drawModuleBox`
   读调用次数 —— 料盘模块应为 0；正常桌子 `_boxFaces` 的 z 分布应 `-750..0`（出现 0.2m 以上的盒子 ⇒ 龙门架没去掉）。
2. 几何：`VIEW.CX`、桌面四角 `VIEW.pr()` 包围盒是否全在画布内。
3. **文字只看钩子/DOM、不看像素**：包 `fillText` 记录 `(text, fillStyle, font, x, y)` 判 canvas 侧；
   覆盖层读 `#trayDims children` 的 `textContent` + rect 判 DOM 侧。
   ⚠️ 不要用"亮像素计数"凭经验判 canvas 文字是否可见 —— 缺字形的渲染环境（部分远程/headless 浏览器）里 glyph 根本不上像素，
   会把正常白字判成"没画"，然后你去改一段本来是对的代码。
   先**证这一步环境会画字形**：挑一处必然有字的标注，取它 `fillText` 记录坐标周围 ~160×28 的 rect 数近白像素
   （有字 ⇒ 几十~上百；空底板 ⇒ 0），证完再用同一窗口做刷白前后对比。像素采样其余用途只判形状（差分、包围盒、非背景占比）。
4. 按钮：`[...document.querySelectorAll('#vrRail button')].filter(b=>b.offsetParent!==null)` 的数量与文案。
5. 两页各跑一遍：`/ar3d` 必须 `__TRAY=false`、按钮/围栏/`CX` 与改动前一致
   （基线：161 个按钮、深色像素 ~89%、右臂文案「🦾 右臂_仿真」、无 `#trayClean` 样式表、无 `#trayDims`）。

## 取证：把画布抓出来交给视觉模型（判断"哪几处文字读不出"）
自己数像素判不出"这行字是什么、能不能读"时，直接把画面送去视觉判读，比反复猜颜色快：
1. 本机起一个只收 POST、把 body 落成 png 的 60 行 `http.server`（**先 `ss -ltn | grep :PORT` 挑空闲端口**）；
2. 页面里 `cv.toDataURL('image/png')` → `atob` 成 `Uint8Array` → `fetch('http://<host>:PORT/shot',{method:'POST',body:arr})`
   （跨端口用简单请求，别带自定义头，否则要多一轮预检）；
3. **必须回到宿主机 `ls` 确认文件真的落盘**：端口被别的 handler 占着时它会回 501，而 `mode:'no-cors'` 的
   fetch 无论成败都 resolve，看着"提交成功"其实一个字节没收到；
4. 把 png 交给视觉子代理，要求"逐条列文字 + 位置 + 可读性，标出几乎看不见的"，它会给出比像素统计更准的清单。

## 往 drawVR 里加新物体：三条例行
- **别用 `g` 当局部变量名**：绘制函数签名是 `(g,pr)`；`var R=…, W=…, g=TP8.gap` 会把画布 ctx 覆盖成 2mm，
  下一行 `_box3(g,pr,…)` 抛 `g.beginPath is not a function`。间隙叫 `gp`。
- **每个物体各用一个 try/catch**：几个 `drawX(g,pr)` 串在同一个 `try{…}catch(e){}` 里，前一个抛错 ⇒ 后面全部不画，
  外层 catch 还把异常吞掉。典型症状：某个物体"怎么都不出现"，但把前一个物体关掉它就出现了（因为前一个提前 return）。
- **新绘制函数第一行加 ctx 守卫**：`if(!T.show || !g || typeof g.beginPath!=='function') return;` ——
  `drawVR` 有不止一条绘制路径，其中一条传进来的不是 canvas ctx；有守卫就是跳过，没守卫就把整个 try 带走。
- 判据：**两个颜色同时数**（8 盘棕 amber 4845 + 目标框黄 4790 同时非零才算都画了）；只数一种色，另一个没画也看不出来。

## 包函数取证的两个坑
- **别假设参数形状**：`drawUrdf(g,pr,M,off)` 的第 4 参实际是变换对象 `{R,t}` 而非数组，写成 `off.map(...)` 会抛错；
  抛在 wrapper 里会把坏函数留在页面上（后续每帧都炸）⇒ 仪器代码一律 `Array.isArray` / `typeof` 防守，
  写坏了就**重载页面**再试，别在原地补。
- 包 `drawVR` 类函数统计调用时，注意点击处理函数自己也会 `drawVR()` 一次，计数要按"清空 → 只调一次 → 读"来取，
  否则会得到 2 倍，误判成"没关掉"。
- **多实例（多个托盘）取证要逐实例做**：每次只翻一个 spec 的 `show`，渲染前后差分，各自 bbox 都应落在桌面投影内
  （实测左盘 8656px、右盘 3961px、4#方盘 2473px）。一次翻两个得到的是并集，分不清是哪个没画出来。
- **别用 stub 掉绘制函数来测"这一段画了多少"**：把 `window.drawXxx=function(){}` 换空后差分可能是 0（脚本作用域里的调用不走那个属性，
  于是"0 像素变化"被读成"这段没画"）。要分离贡献用**它自己的 `show` 开关**（`TPAN.show` / `TP8.show`）或整块 `TAB.show` / `CHS.show`，
  差分出的 bbox+像素数才是可信的。
- console 里手写验收对象时，**键名不要以数字开头**（`{4号盘mm:…}` 直接 SyntaxError）；中文键可以，数字开头不行。

## 反向门控：摆盘专用按钮不许出现在 `/ar3d`
`KEEP` 白名单只在摆盘页「收起」别的按钮，管不到反方向：把「4#方盘 / 3×10 光模块 / 尺寸 / 从机器人 /
中上托盘 / 左右托盘 / 伸展」直接写进共用左栏 HTML，`/ar3d` 上就**全露出来**（用户会直接投诉「这是 ar3d，不是 tray，
左侧的按钮跟 tray 怎么能是一样的」）。做法：`__TRAY` 判定后给根元素打一个场景类，再用 CSS 只在非摆盘场景压掉这些 id。
```js
try{ if(__TRAY) document.documentElement.classList.add('sceneTray'); }catch(e){}
```
```css
html:not(.sceneTray) #bPan,  html:not(.sceneTray) #bPan5, html:not(.sceneTray) #bPanSide,
html:not(.sceneTray) #bPanUp, html:not(.sceneTray) #bSlave, html:not(.sceneTray) #bStretch,
html:not(.sceneTray) #bDim,   html:not(.sceneTray) #bMod30 { display:none!important; }
```
- 类挂 `documentElement` 不挂 `body`：`__TRAY` 在脚本前段就算出来了，那一刻 `body` 未必解析完，而 `html` 一直在。
- 用 CSS 隐藏、**不删节点** ⇒ 摆盘页的 `trim()/KEEP` 与 `$('bDim').addEventListener` 绑定原样有效，`/ar3d` 也不会因缺节点静默 null。
- 判据（改前先量基线，改完再量，别凭"看着少了"）：`/ar3d` 的
  `[...document.querySelectorAll('#vrRail button')].filter(b=>b.offsetParent!==null)` 数量回基线（本机页面 161 / 小静静打包版 126），
  且上面这些 id 的 `offsetParent` 全为 `null`；`/tray` 侧 17 个按钮、这些 id 全在。

## 同一 URL 两次刷新一个样一个不一样：异步面板会把 `trim()` 结果冲掉
「轨迹 / 原子技能包络 / 工程配置点位」几块在 `#vrRail` 里，是 fetch 回来才建的；建完会把 `trim()` 刚设成
`display:none` 的容器**重新显出来** ⇒ 同一页面连刷两次，一次干净一次一堆按钮（只看一次会得出错误结论）。
- 定时补拍（`[200,600,1500,3000,6000].forEach(t=>setTimeout(trim,t))`）**不够**：异步渲染可以落在任何一拍之后。
- 做法：盯 `#vrRail` 的节点增删 + 2s 心跳兜底；`trim()` 本身幂等，重复调用无副作用：
```js
try{
  var _r=document.getElementById('vrRail');
  if(_r && !window.__trayTrimWatch){
    var _tid=null;
    window.__trayTrimWatch=new MutationObserver(function(){
      if(_tid) return; _tid=setTimeout(function(){ _tid=null; try{ trim(); }catch(e){} }, 120);
    });
    window.__trayTrimWatch.observe(_r, {childList:true, subtree:true});
    window.__trayTrimTimer=setInterval(function(){ try{ trim(); }catch(e){} }, 2000);
  }
}catch(e){}
```
- observer 只收 `childList/subtree`，**不要收属性过滤**：trim 自己就在改 `style.display`，收属性会自己触发自己。
- 判据：等 ~9s 再量。刚导航完拿到的快照是**首帧**（面板本来就还在），用它判"没修好"必然误判。
  过关线：左栏稳定 17 个按钮、`#tactPanel`/`#zflow` 不可见、body 里没有 `▶ 回放`。

## 重复物体 + 细窄特征（拉环/标签/条纹）：先排序，再决定描不描边
这个渲染器**没有深度缓冲**：同一批重复物体（30 个光模块、一摞盘）按数组顺序画，等于拿数组顺序当遮挡顺序。
- 症状：每个模块尾部的绿色拉环**画了 30 次、画面上一个绿像素都没有**（开关差分只涨 2px）。
  机制：模块长 149.7mm、行距 164.7mm，斜视时后一排的块体正好压住前一排的尾部，而尾部就是拉环。
- 做法：先算好每块包围盒，用 `pr(中心).z` 从大到小（远→近）排一遍再画：
```js
var list=[], i=0;
for(r…) for(c…){ var ccx=…, ccy=…;
  var q=pr([ccx,ccy,zt]); list.push({x0:…,y0:…,y1:…,x1:…,z:(q&&q.z!=null)?q.z:0}); i++; }
list.sort(function(a,b){ return b.z-a.z; });                      // 远 → 近
for(var k=0;k<list.length;k++) drawModOne(g,pr,list[k].x0,list[k].x1,list[k].y0,list[k].y1,zb,zt);
```
- **细窄面不要描边**：画面上只有 4~6px 宽的特征，默认 1.1px 的棱线会把填充整个吃掉（排序后绿像素仍只有 2px 就是这个原因）。
  该段 `_box3(..., fill, null)`，环状/边框细节只在投影边够长时才补：
  `var _big=P[0]&&P[1]&&Math.hypot(P[1].u-P[0].u,P[1].v-P[0].v)>6;`
- 判据一律「开关差分 + 精确色容差」，不信"代码调用了"：`drawVR()` 记 on → `X.show=false; drawVR()` 记 off，
  按 `|ΔR|,|ΔG|,|ΔB|<22` 数像素，**三个颜色都报**（实测金属 +556 / 塑料 +53 / 绿 +1543 px；30/30 块拉环位检到绿；单帧 3.7ms）。
  只数一种颜色 ⇒ 另外两段没画也看不出来。
- 光模块实物比例（用户口径「前半部分是金属，后半部分是塑料拉环，拉环是绿色的」）—— 全部走 `MOD30` 对象里的参数，别写死在绘制里：
  `fMetal=0.52` 金属银白 `#cdd5dd` / `fPlast=0.72` 塑料深灰 `#2b333d` / 尾段 28% 绿 `#2ee05f`（拉环段比本体高 1mm，俯视才不被本体吃掉），
  另有 `seam:'#0f1419'`（金|塑 之间 1px 分界缝）与 `ring_hole:'#0d2f16'`（拉环投影 >7px 时在中间挖深绿"孔"，看着是能勾手指的环而不是一块绿胶）。
  - **拉环占比宁大不小**：22%（`fPlast=0.78~0.80`）时拉环在默认机位只有 ~6px，用户会说"还是一块灰、看不出样子"；28% 才读得出，实测沿长边 0~40% 金属[194,215,220] / 50~60% 缝+塑料 / 70~100% 绿[51,225,107]，
    逐块点位金属 27/30、塑料 29/30、绿 30/30（差的是被邻块遮挡）。改比例只动 `fMetal/fPlast` 两个数，绘制代码不动。
  - 深色塑料别用 `#2b3138` 这类与桌下暗部同档的值（差分不出来），要亮一档；金属和塑料之间有缝才看得出"两种材质"。
- 默认机位整盘只有 ~120px 宽、一块模块 ~30px、三截各 3~5px ⇒ 颜色能分、结构看不出。要证"确实画对了"就压近机位量
  （`?near=mod30` 时一块 ~59px，三色 15416/80983/7685px）。回复里给这个缩放口径 + URL，**别承诺默认视角也看得出结构**。

## 把既有盘装满零件 + 叠成一摞（`nLayer` / z 偏移）
需求形如「左上角的盘装满 X，堆叠 8 盘，要有 8 层高」：
1. **先算，再决定要不要让零件互相穿插**：内腔 = `(L-2*wall) × (W-2*wall)`。实测 4#方盘内腔 305×220，
   模块 149.7×22.58 沿长边排 2 排 = 299.4、每排 8 个 = 180.6 ⇒ **不重叠就放得下**。
   算完把余量报给用户（实际 2.8mm / 19.7mm），别顺着「拉环可以叠加」的假设去叠；他说「可以挨着放置」⇒ `gap:0`，不再留缝。
2. **盘绘制函数加 z 偏移参数，不要复制一份"堆叠版"**：`drawTrayPan(g,pr,T,zoff)`，内部 `var z0=zoff||0`，
   外壳 `_box3(…, T.H+z0, z0, …)`、内腔 `… +0.008+z0`。不传第 4 参时行为与原来逐字一致（老调用点一行不改）。
   底座那只盘仍由原调用画，堆叠只补上面 `nLayer-1` 只，每只抬 `T.H`。
3. **只画最上层的内容**：下面几层的料被上一只盘的盘底压住，物理上看不见 ⇒ 省掉 7/8 绘制量（实测 8 层仍单帧 3.3ms）。
   回复里主动说一句「下面几层有料但被压住，所以只画顶层」，否则用户会以为漏了。
4. **层数只留一个数字**：`MOD16.nLayer`。改高度只动它，不动几何。
5. **尺寸覆盖层要报总高**：`items.push(['<盘名> 8 层 高 320', pr([x0-0.06,(y0+y1)/2, topZ*0.55])])`。
   注意 div 槽位是写死的（`for(i<17)`）⇒ 加条目后确认 `items.length ≤ box.children.length`，超了标签静默不显示。
6. 判据（数调用，别数像素）：钩 `_box3` 按 fill 计数 —— 盘外壳 = **3 个同色实例 + (nLayer-1) 只叠加**；
   金属/塑料/绿环各 = 左盘 30 + 顶层 16 = 46；盘 z 区间应为 `0~0.04 … 0.24~0.28 … 0.28~0.32`。
   ⚠️ 三个 4#方盘共用同一个 `fill`（`#8a5a2b`）⇒ 按颜色数"画了几只盘"会算错，按 z 区间或调用次数判。

## 「给这个新增项一个更近的机位」：URL 参数 + 每帧钉住
用户要"凑近看"某块区域时，加一个**只由 URL 决定**的近看机位，不要动页面上的按钮/交互：
```js
// traySceneInit() 里只登记意图
if(/[?&]near=mod30/.test(location.search)) window.__NEAR_MOD30=true;
// drawVR() 开头每帧钉住 —— 一次性赋值撑不住
if(window.__NEAR_MOD30){ VR.auto=false; VR.tgt=[0.54,0.7775,0.02]; VR.dist=0.75; }
```
- **先 grep 这个 query 名有没有被占用**：`?cam=` 在本页已是**图源选择**（`arm/gold/surface`，`new URLSearchParams(location.search).get('cam')`），
  拿 `?cam=mod30` 当机位开关会把相机图源一起弄坏 ⇒ 换 `near=`。加参数前搜一遍 `location.search` 的既有用法。
- **必须每帧重设**：`VR.dist/tgt` 在初始化之后还有别的写者（取景/自适应），只赋值一次下一拍就被改回去，
  现象是"参数加了没效果"。放在 `drawVR` 最前面钉住，比在初始化里设更可靠。
- 判据：页面里读 `VR.dist` 应为目标值、`window.__NEAR_MOD30===true`，并沿模块长轴按百分比取色报三截序列。

## headless 截图当证据前，先证明它拍的是"此刻这一页"
- snap 版 chromium 的 profile 有 `SingletonLock`：直接 `--user-data-dir=~/x` 会被映射回默认 profile 而 abort；
  用 `--user-data-dir=/home/<user>/snap/chromium/common/<newdir>` 才起得来，并加 `--headless=new --no-sandbox --disable-gpu --hide-scrollbars --virtual-time-budget=15000`。
- **三个不同 URL 截出同一张 png（md5 相同）= 截图没意义**：先把"明显该不一样"的两页（如 `/ar3d` vs `/tray`）各截一张比 md5，
  确认不同再拿它当证据；宁可给用户\"你打开这个 URL 自己看\"，也不要把一张没验证的图或同图三份当三份证据。
- 临时反代静态图：起 `python3 -m http.server` 前先 `ss -ltnp | grep :PORT` 挑空口（老端口常被别的 handler 占着，GET 会回 501），
  用完 kill 自己起的 pid（`kill` 外层壳不动子进程，要杀 `ss` 里那个 python pid）。

## 给工位编号（位置牌 UI）：先翻成世界轴，再两色对齐、扇形散开
需求形如「主机器人视角：左上 1、左下 4、右上 6、右下 5、中上 3、中下 2，你来设计 UI，让我能看到这 6 个位置」。
1. **先把方位翻成世界轴，别凭屏幕直觉**：主机器人站桌子近端朝 `+X` ⇒ **它左手边 = `+Y`、右手边 = `-Y`**；
   「上」= 远端（x 大）、「下」= 靠机器人（x 小）。由此 ①=左上盘 ②=中方盘 ③=中上托盘 ④=左盘 ⑤=右盘 ⑥=右上盘。
   编号→盘**只写一张表** `POS6=[{n,name,pan,color,note}]`，绘制/划线/牌子/开关全从这张表生成；
   在三个地方各抄一遍名字，改一处就三处不一致。
2. **两层同时给才一眼对上**：3D 层给每只盘沿扫一圈 2.2px **同色**描边（堆叠的盘画在 `T.H*nLayer` 顶面，不是底座）；
   覆盖层给每只盘上方一块 DOM 牌「大号数字 + 盘名(+容量)」，颜色与描边同色。颜色是给"牌↔盘"做对应，不是装饰。
3. **牌子朝桌子外侧扇形散开**：都放盘中心正上方时，透视下 6 块会互相压。沿「桌面中心 → 该盘中心」外推 ~90mm 再抬高：
   `var ux=T.cx-0.725, uy=T.cy-0.25, ud=Math.sqrt(ux*ux+uy*uy)||1;`
   `pr([T.cx+ux/ud*0.09, T.cy+uy/ud*0.09, ztop+0.06])`。判据是**两两 `getBoundingClientRect()` 求交面积 = 0**（不是看截图）；
   实测牌宽 54~106px、6 块零重叠。字号收到 17px 数字 + 10.5px 名字，比大块牌子好摆。
4. **显示条件互相独立**：`POS.show`(总开关) × `T.show`(盘关掉就该没牌)；**不许跟着「📏 尺寸」走** ——
   位置标不是尺寸标，实测关尺寸时 6 块牌应仍在。牌子/描边一律写在 `if(__TRAY)` 分支里，`/ar3d` 不许出现。
5. 自检三条：牌数 = 6；语义断言（①的 u < ⑥、①的 v < ④、④的 u < ⑤、③的 v < ②）；开关连点两次 `6→0→6` 且按钮 `on` 态同步。
6. **编号目前只是可视标记，没进执行链**（不参与抓取目标、UPH、段表）：回复里要明说，别让它听起来像已经能当料位用；
   用户点头后再把它接进状态空间/段表。
