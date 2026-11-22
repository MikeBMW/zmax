# 8815 停点清单: 可编辑(改名/删点) + 单向高亮

用途: 让老倪在 `http://<host>:8815/` 的 E 面板上,**直接给每个停点起名字、点一下删掉不要的点**,
同时让高亮严格按轨迹顺序从上往下走。服务端 `tools/se3_geom_server.py`, 前端 `tools/web/se3_geom.html`。

## 1. 停点判据(方向突变, 不是速度≈0)

```python
STOP_SPEED_FRAC = 0.0      # 0 = 不卡速度, 只要方向突变
STOP_TURN_DEG   = 45.0     # 转角阈值
STOP_WIN        = 5        # 前后各 5 帧算方向(抑噪)
STOP_MIN_MM     = 10.0     # 前后段太短(抖动)不算
STOP_DEDUP      = 5        # 5 帧内多次触发只留转角最大的
```

- 本轨迹(W=5/turn=45/sep=5)得 **22 个停点**: `10 18 29 35 42 60 69 79 86 101 107 119 125 132 140 149 167 177 184 190 199 209`。
- 参数对照: 卡速度 0.15 + turn 25 只剩 4 个(会漏掉无位置停顿的动作点); turn 25/W 3 会炸出 160 个(录制折线本身抖)。
- `sectors.holds` = 删点后的停点帧号表, 执行器 `ZMAX_RT_HOLD_AT` 直接用它; `holds_ms` 给 1000。

## 2. 服务端 API

```
POST /api/stop  {"i": 125, "name": "金手指点2"}   → 改名
POST /api/stop  {"i": 209, "del": true}          → 删掉这个停点
POST /api/stop  {"i": 209, "name": ""}           → 清空 = 恢复
回执: {"ok": true, "stops": [...]}               (stops 已合并标签、去掉已删)
```

- 标签文件 `zmax_data/rokae_sdk/stop_labels.json` = `{"<帧号>": {"name": "…"} | {"del": true}}`, 原子写(`tmp` + `os.replace`)。
- 🔴 **两个缓存都要清**: `_J.pop("stops")` 与 `_J.pop("sectors")`。只清前者, `/api/se3` 仍从 `_J["sectors"]` 拿旧表,
  现象是「改了名字页面没变」「删了点又回来」。
- 默认名给空串, 页面上退化成 `#帧号`。别用"停留(速度≈0·换向)"这类描述当默认名 —— 判据已经不是速度了, 名字会自相矛盾。

## 3. 前端: DOM 列表压在 canvas 上

canvas 上画不了真 `<input>`, 所以 E 面板右侧改成绝对定位的 DOM 列表, canvas 只画环:

```html
<div class="card g-e"> … <canvas id="e"></canvas><div id="stopList" class="stops"></div></div>
```

- 布局: `.stops{position:absolute;top:42px;right:8px;width:47%;max-height:calc(100% - 50px);overflow-y:auto}`。
- 行: `<span class=i>#帧号</span><input value=名字><button>✕</button>`; 左边框颜色按状态名(`_stopColor`)上色。
- `input` 的 `change`(不是 `input`, 否则每敲一个字都打接口) 时 `POST /api/stop`; `keydown` Enter 直接 `blur()`。
- `✕` 点击即 `POST {del:true}`, 回执后的 `stops` 直接**回填到 `LIVE.sectors.stops`** 并置 `_STOPS_KEY=""` 让下一帧重建。
- 重建闸: `key = stops.map(i:label).join() + '#' + hi` —— 只有集合或高亮行变了才重建, 否则正在输入的内容会被打断。
- 画布那段行清单用 `if(!DOM_STOPS && …)` 关掉, 避免两份文字叠在一起。

## 4. 高亮: 已走过的最上面那个停点

```js
let hi = -1;
st.forEach((o,k)=>{ if(cur_i>=0 && o.i<=cur_i+1) hi=k; });   // 序号最大且已到达
```

- 不要写 `Math.abs(o.i-cur_i)<=2`: 两个停点中间它会来回挑, 现场看到「方框上下跳」。
- 页面上永远只有一个 `.cur`; 重建后按 `getBoundingClientRect` 判断是否出可视区, 出界才微调 `scrollTop`(`block:'nearest'` 语义),
  不要每帧 `scrollIntoView`, 会跟用户手动滚动打架。

## 5. 浏览器内验收(不用截图)

```js
// a) 行数与集合
({rows: document.querySelectorAll('.stops .r').length,
  cur: [...document.querySelectorAll('.stops .r.cur')].map(r=>r.querySelector('.i').textContent)})
// b) 改名真的落盘(改完再 GET 一次, 别只看输入框回显)
document.querySelector('.stops .r input').value='测试点';
document.querySelector('.stops .r input').dispatchEvent(new Event('change',{bubbles:true}));
await (await fetch('/api/se3')).json();
// c) 删点
[...document.querySelectorAll('.stops .r')].pop().querySelector('button').click();
await (await fetch('/api/se3')).json();   // holds 应少一条、rows 少一行
```

- 改完名字若 API 仍回旧值 ⇒ 是 `_J["sectors"]` 没清(见 §2)。
- 用 `browser_click` 点画布区域可能落到陈旧 ref 上; 验按钮统一用 `.click()` + 回读接口。
- 控制台偶尔会挂到 `about:blank`(另一 tab): 断言前先 `location.href`, 不是目标页就重新 navigate 再测。
