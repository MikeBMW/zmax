# 改 8797 页面显示 · 叠位姿层 · 画布颜色归因

覆盖三件事：改 tcp-ar.html 的显示层、不碰服务端往三维场景里叠一个位姿/标记、用户说「把这堆蓝色XX删掉」时如何定位到具体层。

## 1. HTML 热读：改页面不要重启服务
- `tools/web/tcp-ar.html` 由服务端每次按 mtime 热读 ⇒ 改 HTML/JS 后**只要浏览器 F5** 就生效。**不要重启 8797**（重启须用户点名）；只有改服务端 python 才需要动进程。
- 改完必须自己用浏览器打开页面取证：`window.X` 能取到值、自增计数器在涨（如 `__TP_DRAWN__`）、按颜色数画布像素、`browser_console` 无 JS 错误。

## 2. 往三维场景叠一个位姿/标记（服务端零改动）
- 页面只从 `/api/fence` 拿 3D 元素，而 items 是**任意 dict，额外键原样返回** ⇒ 把 `{id:'TP1', type:'points', pts:[p0,p1], pose:{pos_m, quat, dims_mm, slot, valid, src}}` 写进 `zmax_data/ar_rs/fences.json`，页面每 ~1.5s fetch 后自绘即可。
- 画法：quat→R，由 pos+边长画盒 + 三轴 + 预抓虚线。**真尺寸在远景只有 ~17px** ⇒ 另加固定像素靶环/十字当视觉锚点；盒子本身不许放大（放大等于改尺寸口径）。
- 未观测/先验位姿必须画虚线并写「⚠未观测(先验)」，不许让先验看起来像实测。
- 位姿来源是测地线引导模块：`plan_guide.target_pose(slot_id=…)` + `publish_target(slot_id=…)`；命令行 `tools/publish_target_pose.py --slot N [--fusion|--clear]`。

## 3. 「这堆蓝色XX删掉」怎么定位

### 3.1 顺序
1. **先量规模**：数目标颜色像素 + 连通域，判断是「很多细长条（轨迹线）」还是「2~3 个大实心块（外壳/盒面）」。形状决定候选层，比颜色名可靠。
2. **再归因**：插桩 Canvas2D 原型，把 stroke/fill 的颜色和调用栈一起记，按调用点聚合 → 直接给出「函数:行号 + 颜色」。
3. **最后按精确 id 切层**：每次只切一层显示，重测像素数，差值就是该层的量。
4. 只把用户点名那层改默认（`VR.xxx=false` + 按钮去掉 `on`），**其余层保持原样**；顺手改的要回退。
5. 报量：改前/改后像素数 + 剩下哪些颜色还占多少 + 各自对应哪个开关。

### 3.2 量像素 + 连通域
```js
// 场景画布通常不是第 0 个（相机底图是 0），按尺寸找
const cv=[...document.querySelectorAll('canvas')].find(c=>c.width>800&&c.height>440);
const g=cv.getContext('2d'), d=g.getImageData(0,0,cv.width,cv.height).data;
let n=0; for(let k=0;k<d.length;k+=4){const r=d[k],g2=d[k+1],b=d[k+2];
  if(b>150&&b-r>50&&b-g2>20) n++;}
```
连通域：二值化后 8 邻域 flood fill，输出每个组件 `{n,w,h}` 和组件数。几十个 <400px 的细长组件 = 轨迹/包络线；2~3 个上万像素的块 = 外壳或盒面填充。

### 3.3 归因插桩
```js
(()=>{const P=CanvasRenderingContext2D.prototype, seen={};
 const isB=(x)=>{const m=String(x||'');
   if(m.startsWith('#')&&m.length===7){const r=parseInt(m.slice(1,3),16),g=parseInt(m.slice(3,5),16),b=parseInt(m.slice(5,7),16);
     return b>150&&b-r>50&&b-g>20;}
   if(m.startsWith('rgb')){const n=m.replace(/[^0-9.,]/g,'').split(',').map(Number);
     return n[2]>150&&n[2]-n[0]>50&&n[2]-n[1]>20;}
   return false;};
 const os=P.stroke, of=P.fill;
 const rec=(ctx,kind)=>{const c=isB(ctx.strokeStyle)?String(ctx.strokeStyle):(isB(ctx.fillStyle)?String(ctx.fillStyle):null);
   if(!c) return;
   const st=(new Error()).stack.split('\n').slice(3,4).join('').replace(/https?:\/\/[^ )]+\//g,'').trim().slice(0,80);
   seen[kind+' '+c+' @'+st]=(seen[kind+' '+c+' @'+st]||0)+1;};
 P.stroke=function(){try{rec(this,'stroke')}catch(e){} return os.apply(this,arguments)};
 P.fill  =function(){try{rec(this,'fill')}catch(e){}   return of.apply(this,arguments)};
 setTimeout(()=>{P.stroke=os;P.fill=of;window.__B__=seen;},700);})()
// 之后: Object.entries(window.__B__).sort((a,b)=>b[1]-a[1]).slice(0,8)
```

### 3.4 按 id 切层
```js
for(const id of ['bUrdf','bSim','bMod','bChs','bCells']){const b=document.getElementById(id);
  if(!b) continue; b.click(); await sleep(700); out[id]=M(); b.click(); await sleep(400);}
```
- 只点**纯显示**开关，且用 `getElementById` 的精确 id；页面里有会开真机的按钮（`bRTraj` 之类），**绝不按文字模糊匹配点**。
- 场景可能自动环绕，像素数逐次抖几十个；只有量级差（上万）才是信号。

### 3.5 已踩的坑
- **紫/青算「蓝」**：`#c084fc`（插孔框）、`#c4b5fd`（URDF 外壳）、`#22d3ee`（料盘框）全部命中 `b-r>50` 判据 ⇒ 必须先打印真实颜色再下结论，否则删错层。实测外壳一层就占 ~1.1 万 px（关掉 19.7k→12.6k）。
- **量完才改**：先改页面再测，会因为自动环绕/开关状态变了而看不出差别；顺序必须是 先量 → 归因 → 切层 → 改默认。
- **别把对照层一起关**：料盘蓝模块（`#60a5fa`）和轨迹线是两层，用户要说哪一个就只动哪一个。
