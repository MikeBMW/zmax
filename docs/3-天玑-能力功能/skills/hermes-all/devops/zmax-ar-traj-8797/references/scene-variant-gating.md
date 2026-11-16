# 共用渲染页派生新场景页(显示门控)

适用: `tcp-ar.html` 这种一份文件多入口 —— `/ar3d` 是用户天天在用的原页(不许改), `/tray` 之类是派生场景页。
派生页要"什么都没有/只剩干净的场景", 原页要一字不变。

## 1 门控骨架(四件套, 缺一就会串页)
1. 判定常量放 `__USP` 旁: `__TRAY = pathname ∈ ['/tray','/tray.html','/baipan']`。
2. 服务端路由白名单 `tcp_ar_server.py` 加同一组路径 —— 改 `.py` 必须 `sudo systemctl restart zmax-traj-ar`; 改 `.html`/`.json` 只 Ctrl+F5。
3. CSS 标题按 `body.vrfull #vrRail::before` 分支, 原页保持原文案。
4. 初始化尾部 `if(__TRAY) traySceneInit();`, 场景默认值 + 左栏白名单 + 机位都在这里。

## 2 只做显示过滤, 不动台账
- 围栏/料盘/插孔/轨迹台账是**全站共用真源**(原页、真机侧都读), 派生页要"没有"就在绘制入口 `return` 或 filter, 绝不改数据。
- 名字正则过滤写在 `filter` 回调**内部**: `FENCES.filter(it=> ... && !(_isTray && /料盘|槽/.test(it.name)))`。把正则提成外部变量去引用 `it` 会落到别的作用域上, 静默失效。

## 3 清场顺序(按图层逐个找, 别只改一处)
一个"料盘"往往同时存在于: ① 围栏盒 `drawFences` ② 盘里的模块 `drawXxxModules` ③ 桌子/工装结构 ④ 专有函数(模块盒、坐标系)。
- 先 `grep` 出所有绘制入口, 再逐条 `return`。
- 每清一层都用**调用计数**验证(见 §7), 不要靠肉眼。

## 4 面板与文案的隐藏
- 左栏裁剪按**祖先链白名单**(保留若干开关的祖先节点, 其余整块 display:none), 不是逐个 button 隐藏 —— 否则残留「游标 215/215」「真机也走」「姿态: 死值常量」这类非按钮文字。
- 异步 `innerHTML` 建出来的面板(右侧节拍栏、左下状态条)只用 trim 里 `style.display='none'` 压不住: 建出来时会重新显形。改为注入一次性样式表
  `document.head.appendChild(<style id=trayClean>)`, 内容 `#tactPanel,#zflow,...{display:none!important}` —— 幂等(先判 id 是否存在), 且后建也压得住。
- 同一按钮文案在多处赋值时, 收口成 `xxxLabel()` 一个函数。只改初始 `textContent` 会被点击/刷新写回原文案(典型: 4 处 `textContent='…_仿真'`)。
- 一个开关要管**多条渲染路径**: 仿真层、真机层、末端模块、坐标系往往各自读不同标志。定义统一谓词 `const visible = a!==false || b!==false`, 所有路径共用它; 漏一条就是"关了还显示"。

## 5 布局数学的隐藏元素陷阱(最坑)
取景居中常按"被固定面板遮挡的宽度"算:
```js
_ovw = Math.min(w, canvasRect.right - panelRect.left);   // 面板 display:none 后 rect 全 0
CX = (w - _ovw)/2;                                       // ⇒ _ovw=w ⇒ CX=0
```
症状: 整个场景被推到画布左边缘外(投影出负 u, 桌子只剩一角), 标注全部跑出画布, 而画面"看起来只是偏了"。
- 规则: 任何 `getBoundingClientRect()` 参与布局数学前先判 `offsetWidth>0 && rect.width>0`, 否则按 0 遮挡处理。
- 自检: 无遮挡时 `VIEW.CX ≈ canvas.width/2`; 对象四角投影都在 `[0,W]×[0,H]` 内。

## 6 画布内标注(尺寸/名牌)
- 标注必须画在**整帧最后**(`drawVR()` 末尾), 画在物体自己的 `drawXxx` 里会被后画的箱体/双臂盖成一片黑 —— 症状就是用户说"尺寸是黑字看不到"。
- 位置夹进画布: `u = clamp(u, tw/2+6, W-tw/2-6)`, 端点跑出画布时文字不能跟着消失。
- 标签要黑底 + 高对比描边 + 14px 粗体; 单位(mm)写进文字里。
- 两条同姿态镜像臂肉眼分不清 ⇒ 末端挂名牌(`tool1 · 右臂` / `左臂 tool1`), 否则用户会把剩下的左臂当成"右臂没关掉"。

## 7 验收清单(每改一条都跑, 别攒到最后)
1. 语法: 抽 `<script>` 块(跳过 `type=json` 的) 拼成一个文件 `node --check`。
2. 服务端: `curl -s -o /dev/null -w '%{http_code} %{size_download}' http://127.0.0.1:8797/tray` —— 200 且字节数随之变化。
3. 图层计数: monkeypatch 目标 draw 函数统计调用次数+入参, 调一次 `drawVR()`, 看谁还在画。
4. 像素/坐标: `getImageData` 采样标注位置是否真亮; `VIEW.pr` 四角是否在画布内; `VIEW.CX`。
5. 原页回归: `/ar3d` 的左栏可见按钮数、料盘围栏条数、`CX`、画臂次数 四项与改前一致。
6. 一条改动一条 commit, 消息里写实测数字(次数/坐标/像素), 不写"应该"。

### 探针片段(浏览器 console)
```js
// 统计谁在画 + 关键入参
(async()=>{const s=ms=>new Promise(r=>setTimeout(r,ms));
  for(let i=0;i<40&&!document.getElementById('bArmR');i++) await s(250);
  const c={}; ['drawUrdf','drawFences','drawModuleBox','drawTable'].forEach(n=>{const f=window[n];
    if(typeof f!=='function')return; c[n]=[]; window[n]=function(){c[n].push([...arguments].map(a=>a&&a.t? a.t.map(v=>Math.round(v*1000)):null)); return f.apply(this,arguments);};});
  drawVR(); return c;})()
```
```js
// 标注是否真在画布内且真亮
(()=>{const cv=document.getElementById('vr'),cx=cv.getContext('2d');const out=[];
  const of=cx.fillText.bind(cx); cx.fillText=function(s,x,y){const t=String(s); if(/长 |宽 |高 |桌子/.test(t)) out.push({t,x:Math.round(x),y:Math.round(y)}); return of.apply(cx,arguments);};
  drawVR(); cx.fillText=of;
  return out.map(o=>({...o, 在画面内:o.x>0&&o.x<cv.width-20&&o.y>0&&o.y<cv.height}));})()
```

## 8 用户口径(这类活通用)
- 连续快速追加删改时: 每次只做点名那一条, 做完立刻给实测数字, 不要问确认、不要顺手改别的、不要列选项。
- 用户会把画面当结果 ⇒ 画面必须自解释: 名牌、尺寸、单位、状态都画出来/标出来。
- 收到"隐藏了还显示": 先量后改 —— 用调用计数判定是哪条路径在画, 再补门控; 不要凭猜改开关。
- 改的是用户正在用的页面 ⇒ 每次都给原页回归证据(按钮数/条数/坐标), 不要只说"没动"。
