# canvas 页上的可读标注:用 DOM 覆盖层,别用 canvas 画字

适用于任何自绘 canvas 页(ar3d/摆盘/看板)需要给用户看的文字:点名、点位标签、图例、状态说明,以及“点一下标签就编辑它”的交互。

## 铁律

1. **给用户读的字不要用 `ctx.fillText` 画在 canvas 上。** 它只是像素:不可选、不可点、缩放后糊,还可能整段不出像素 —— 你画了框画了字,屏幕上只剩“有框没字的空条”,用户只会说“这两个黄色边框黑色背景的长条是什么,删掉”。
2. **canvas 只承担图形(点/线/框/引线),文字全部走 DOM 覆盖层。** 一个 `position:fixed; pointer-events:none; width:0; height:0` 的容器盖在画布上,每个标注一个绝对定位 `div`。
3. **投影用页面同一个函数**(如 `VIEW.pr(P)`),不要自己另算一套矩阵,否则标签和轨迹线错位;每帧或 60~100ms 节流,在 `drawVR` 之后重算 `left/top`。
4. **标签给 `pointer-events:auto` + `onclick`**,点了就打开该条目的编辑框。用户点 13px 的字比点 3px 的轨迹点容易得多,这是“点选不中”的兜底。
5. **相邻点标签必然重叠**(相邻轨迹点在屏幕上常只差 1~3px),定位后做贪心下推:按 y 排序,与已放置矩形相交则 `y += h+3`,上限 8 次;交付前实测相交数=0。
6. **样式**:白色 `bold 13px` 等宽字 + 深色半透明底 + 细白边 `rgba(255,255,255,.32)` + 4px 圆角。不要琥珀/暗黄字压黑底,用户原话是“看不到写的是什么,你要用白色字体显示”。
7. **给一个总开关**(“👁 显示名字:开/关”)控制容器 `display`,用户嫌挡视线时一键关掉,不要让他要求删代码。

## 拾取:屏幕点 → 最近轨迹点

- **不要设“离任何点超过 N 像素就什么都不做”的阈值。** 点偏一点就静默无反应,用户判定为功能坏了(原话“点选不中”)。
- 正确做法:**永远取最近的那个点并弹编辑框**;偏离超过 ~50px 时在框里明确写“⚠ 最近点还在 xx px 外,用 ◀ ▶ 挪”,绝不静默。
- **密集段相邻点坐标可能完全相同**(例如插入段两个点都是 819,227,190),靠屏幕最近分不出来 ⇒ 编辑框必须有 `◀ ▶` 逐点微调,并在标题显示 `#索引 + x,y,z mm`,让用户能确认自己选的是哪个点。
- 监听用 `document` 捕获阶段,先判 `e.target===canvas`;命中后 `preventDefault + stopImmediatePropagation`,避免同时触发页面原有的取点/拖拽。
- **退出拾取模式必须把画布点击还回去**(恢复 `cursor`、不再弹框),否则页面原有交互被永久劫持。
- 点按钮只按 `id` 操作。同页常同时存在显示开关与真机运动按钮(如“右臂跑真实轨迹”),按文字模糊匹配会直接开真机 —— 这是安全事故,不是 UI bug。

## 往大 HTML 末尾追加整块的三个坑

1. **别拿 `</script>\n</body></html>` 当锚点整段替换。** 替换会吃掉那个 `</script>`,你的 `<div>` 就变成上一段脚本的**文本内容**:元素根本不进 DOM(`getElementById` 返回 null),而页面其它功能照常运行 —— 现象像“代码没生效”。
   正确:`</script>\n</body></html>` → `</script>\n<你的块>\n</body></html>`,即保留原有闭合标签。写完 grep 一次 `</script>` 与 `<div id=...>` 的相对顺序。
2. **页面有缓存。** 改完用 `?v=<随机>` 打开,并且必须同时满足两个判据:`document.documentElement.outerHTML.includes('你的id')` 与 `document.getElementById('你的id')` 都为真。只有前者为真,就是第 1 条那个坑(成了脚本文本)。
3. **包 `drawVR` 做后置绘制时,异常会被 `try/catch` 吞掉** ⇒ 标注整段消失且控制台无报错。排查时把绘制函数暴露成 `window.__X__.draw` 直接调用,让它把异常抛出来,别隔着 try 猜。

## 验收:用 DOM 断言,不要靠像素

```js
// 1) 标注存在且是白字、互不重叠
const host=document.getElementById('lblHost');
[...host.children].forEach(d=>getComputedStyle(d).color);   // 应为 rgb(255,255,255)
// 两两矩形相交计数必须为 0

// 2) 拾取:点在偏移处也要命中预期点
document.elementFromPoint(cx,cy) === canvas;               // 先证明点落在画布上
canvas.dispatchEvent(new PointerEvent('pointerdown',{clientX:cx+12,clientY:cy+9,bubbles:true,cancelable:true,pointerId:1}));
// 编辑框标题应为 “第 #N 点 · x,y,z mm”

// 3) 点标签 = 打开编辑框且名字预填
document.getElementById('lblHost').children[i].click();
```

- **像素计数只能验图形**(点/线/框的颜色像素数),**不能验 canvas 里的文字**:canvas 文字可能整段不出像素,会把“字没画”误判成“字画了”,也可能相反。要判“字清楚”就看 DOM 的 computed style。
- 面板位置改完要做一次**矩形相交检查**(面板 vs 页面所有 button/select/input),重叠数必须为 0:面板压住运动按钮会引发误点。

## 数据存放(点命名 这类面向现场的标注)

- 名称存单一真源 JSON(如 `zmax_data/ar_live/pt_names.json`),按 `{traj_id, index}` 两级键;前后端只读写这一份,不要在前端内存里另存一份“当前名字”。
- 接口:一个 `GET` 返回全量对照表,一个 `POST {id,i,name}` 兼顾存/改名/删(`name=""` 即删)。改完必须回读接口确认落盘,不要只信按钮变绿。
