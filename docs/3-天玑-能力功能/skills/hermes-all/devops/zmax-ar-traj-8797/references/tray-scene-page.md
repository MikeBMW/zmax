# 摆盘场景页 /tray（`__TRAY` 分支）

> 必读四步，读完再动手：
> 1. 共用文件里**所有删/裁/换默认值都必须 `if(__TRAY)` 门控**，`/ar3d` 一个字不许变；
> 2. **隐藏任何 fixed 面板前先 grep 谁在量它的 rect** —— 置 `display:none` 后 rect 全 0，取景会静默错位；
> 3. **显示过滤只改画不改台账**（料盘/槽/插孔都在 `FENCES` 台账里，别删数据）；
> 4. 收工前两页各量一遍：`/tray` 与 `/ar3d` 的按钮数、围栏数、`VIEW.CX`。

同一份 `tools/web/tcp-ar.html`，`location.pathname` 进 `/tray`、`/tray.html`、`/baipan` 时 `__TRAY=true`，
只切四样：场景默认开关、左栏白名单、取景、显示过滤。渲染/几何/投影全复用 `/ar3d`，两页不会各自漂移。
服务端 `tools/tcp_ar_server.py` 路由白名单要有这三个路径；改 `.py` 要 `sudo systemctl restart zmax-traj-ar`，
改 `.html` 只要刷新（响应头已是 `Cache-Control: no-store` —— 拿 `curl -D -` 确认过再怀疑缓存，别拿"你没刷新"当解释）。

## 干净场景底线
- `drawFences()` 在 `__TRAY` 下直接 `return` —— 料盘/槽/插孔/相机盒/旧轨迹/标定预览全在 `FENCES` 台账里，
  一条都不画；`drawTrayModules()` 同样 `return`（否则盘里那批模块会重新出现）。
- 只留：实验桌 + 箱体 + 双臂(URDF) + 中央相机 + 坐标系 + 光模块 + **周转盘**。
- 周转盘（310×230×45mm）画成一个盘子：外壳长方体（`#2e6b86` 面 + `#9ad8f0` 棱）+ 内腔下沉 37mm（`#173d4e`），
  底面贴 z=0、顶沿 z=45mm；落位数由几何算并核对是否全落在桌面内（实测盘 x 665~895、y 95~405，桌 x 350~950、y -550~1050）。
  判据：临时切 `TPAN.show` 前后各渲染一次做像素差分 —— 差分 bbox 就是盘的屏幕footprint（实测 101×50px / 3314 像素），
  落在桌面投影范围内才算画对；只数"接近盘色的像素"会被别处同色几何骗（实测内腔色散在整幅画面上）。
- `drawTable()` 有 `__TRAY` 早退分支：桌面 + 4 条腿落地 + 两条下横撑；
  龙门架立柱、上横梁、角码、框架标签都不画。**尺寸标注不在这个函数里画**，见下节。

## 左栏白名单（只留看场景的开关）
`bFrames bUrdf bMod bArmR bArmL bStretch bCamTop bChs bTab bFlr bSim`（新增按钮必须同时进这张白名单，
否则按钮被 trim 掉、代码却在找它 ⇒ 点了没反应/静默 null）。
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

**尺寸只留数值标，不要标题条**：桌子 `长 1600` / `宽 600` / `高 750` 各贴在自己那条尺寸线旁；
周转盘 `长 310` / `宽 230`（**不标高**）贴在盘左侧/后侧外侧。

- 字号口径：桌子三条 **12px 粗体**（用户嫌 15px 大）、内边距 `1px 5px`、边框 `1.2px`；两块以上标签时必须两两量中心距，
  实测最近 75px 才不叠；桌子「长」标签挪到 `y0+0.18` 靠后一端，给周转盘标注让位。
- **加标签要改建 DOM 的循环次数**：`for(var i=0;i<3;i++)` 写死 3 ⇒ 新增第 4/5 块时 `getElementById('tdim3')` 是 null，
  标签静默消失；条目数组 `items` 和 div 数量必须同步。
- **两套坐标别混着比**：DOM 覆盖层的 `style.left/top` 是**视口坐标**（`cr.left+u`），而 `getImageData` 读的是**画布内坐标**；
  直接拿 787px 去跟画布 399~500px 的差分 bbox 比会误判"标签飞了"，比之前先减 `cr.left`。
不要再加「桌子 长1600 × 宽600 × 高750 mm」这类汇总条，也不要往画面下方状态行（`$('pVr')`）重复一份 ——
两处都是会被点名删掉的冗余（"删掉这个小文字条"）。数值对比度够就行，不加标题、不加单位说明牌。

- **长/宽别写反**：`TAB.w`=长 1600mm（沿 Y），`TAB.x1-TAB.x0`=宽 600mm（沿 X），`TAB.h`=高 750mm。
  写反了画面和状态行会各说一套（实测出现过 `长600 × 宽1600`）。

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

## 自验（浏览器 console 直接跑）
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

## 包函数取证的两个坑
- **别假设参数形状**：`drawUrdf(g,pr,M,off)` 的第 4 参实际是变换对象 `{R,t}` 而非数组，写成 `off.map(...)` 会抛错；
  抛在 wrapper 里会把坏函数留在页面上（后续每帧都炸）⇒ 仪器代码一律 `Array.isArray` / `typeof` 防守，
  写坏了就**重载页面**再试，别在原地补。
- 包 `drawVR` 类函数统计调用时，注意点击处理函数自己也会 `drawVR()` 一次，计数要按"清空 → 只调一次 → 读"来取，
  否则会得到 2 倍，误判成"没关掉"。
