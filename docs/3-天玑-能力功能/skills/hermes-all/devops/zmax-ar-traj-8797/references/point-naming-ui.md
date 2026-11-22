# ar3d 轨迹点命名(8797) + 为什么字必须画在 DOM 上

真源: `zmax_data/ar_live/pt_names.json`  `{"<traj_id>": {"<i>": "名字"}}`
接口: `GET /api/pts/names` / `POST /api/pts/names {id,i,name}`（`name=""` 即删除）
代码: `tools/tcp_ar_server.py` 尾部 + `tools/web/tcp-ar.html` 尾部的 `#ptnPanel` / `#ptnLabels`

## 🔴 核心坑: canvas 的 fillText 在某些浏览器/无头环境里一个像素都不出

- 现象: 画了圆角框 + `fillStyle='#ffd479'` + `fillText(...)` → 屏幕上只有
  **黄边黑底的空长条**, 一个字都没有。用户会把它当成"多余的黄框黑条阴影"要求删掉。
- 实测判定: 在**干净的新 canvas** 上 `fillStyle='#ffffff'; fillText('TEST',10,35)` 后
  `getImageData` 全区域 → 白像素 **0**; 同一 canvas 上 `fillRect` 白块 → 300 像素正常。
  即: 不是坐标/字体/颜色的问题, 是这个环境**不做文字栅格化**。
- 所以 **像素计数不能用来验收「文字有没有画出来」**, 只能验框/点。
- 结论: **不要用 canvas 画需要人读的标签**。改成 canvas 上盖一层 DOM:
  ```html
  <div id="ptnLabels" style="position:fixed;left:0;top:0;width:0;height:0;pointer-events:none;z-index:55"></div>
  ```
  每帧(`drawVR` 包装, 节流 60ms)按 `VIEW.pr(点)` 投影 → `left=r.left+q.u/sx+9; top=r.top+q.v/sx-22`,
  子 div 用 `color:#fff;font:bold 13px ui-monospace` + 深底 + 细白边, `pointer-events:auto` 可点。
- 副产品: 标签本身可点 → 直接 `showEditor(i,...)`, 是「点不中那个小球」的兜底。

## 视觉约束(老倪口味)

- 白字, 13px 加粗, 深底 `rgba(9,12,16,.9)`, 边 `rgba(255,255,255,.32)`; 只用名字, 坐标放 `title`/编辑框。
- 相邻点(8mm 等弧长, 常有两点坐标几乎重合)标签必须**贪心下推避让**(`y += h+3`), 否则叠成一条看不清。
- 需要时可一键关: 面板「👁 显示名字：开/关」→ `SHOWNAMES`。

## 点选(pick)铁律

- **不要设半径门槛后静默失败**。原来 "离任何点 >26px 就 return" → 用户点偏一点就报"点选不中"。
  正解: 永远取最近点弹编辑框; 偏离 >50px 时框里写 "⚠ 最近点还在 xx px 外, 用 ◀ ▶ 挪"。
- 密集轨迹相邻点常同屏重合(两点坐标只差 1mm) → 编辑框必须给 `◀ ▶` 逐点挪。
- 监听用 `document.addEventListener('pointerdown', h, true)` + `e.target===canvas` 判定, 命中后
  `stopImmediatePropagation()` 才不会把点击漏给页面原有的取点/拖拽。关掉点选后画布点击要完全还给页面。

## 🔴 写操作(删除/改名)必须有反馈, 禁止静默 return

- 实测故障: 用户报「删除失败了」。根因是 `save()` 开头 `var it=curItem(); if(!it) return;` ——
  轨迹点条目的开关被关过/还没加载时 `curItem()` 返回 null, 于是**点了删除什么都不发生, 也没有任何提示**。
  在用户那里, 静默失败 = 功能坏了。
- 修法三条一起上:
  1. `curItem()` 记住 `LAST_ITEM`(上次命中的 points 条目), 找不到时回退到它, 不要返回 null;
  2. 成功 → 绿色 toast「已删除 #N 的名字」/「已保存 #N = 名字」; 失败 → 红色 toast 带原因;
  3. 成功后 `PNAMES=d.names; window.__PTN_SIG=''; paint();` 并逐个 `LBL[key].style.display='none'`
     清掉已删标签(否则三维里名字还在)。
- 验收不许只看"点了没报错": 必须 `GET /api/pts/names` 回读服务端少一条 + 列表行消失 + toast 文本。
        
## 用户端是旧页面 —— 改完前端必强调强刷

- 现象: 代码已经改好、服务端已重启, 用户那边还是旧行为(按钮没反应/删除无效)。
- 规则: 动过 `tcp-ar.html` 后, 交付话里必须写明 **Ctrl+Shift+R 强刷**(或给 `?v=<tag>` 的 URL),
  否则用户会把旧页面的表现当成新代码的 bug, 反过来质疑修复无效。

## 列表刷新延迟(验收时容易误判)

- `paint()` 有 sig 守卫(名字/条目没变就不重画), `loadNames()` 是 **15s** 轮询。
- 从外部(API/脚本)写入后, 页面最长 15s 才出现在列表里; 验收要等 ≥16s 或直接调 `loadNames()`,
  不要 0.6s 就断言"没生效"。

## 命名点索引: 靠几何定量, 不许靠相邻索引猜

- 用户口径「插入之后第一次到底就是工作点」= **该段里 z 最低/插入最深的那一帧**, 不是"跟着插入点往后数一个"。
  实测按后者取, 会差 1mm、正好落在底点之上那一帧, 被判"工作点错了"。
- 做法: 先打区间几何表再定索引, 一次性给用户看清楚:
  ```python
  d=json.loads(urlopen('http://127.0.0.1:8815/api/geo?set=v2').read())
  F={f['i']:f for f in d['frames']}
  for i in range(96,137): print(i, F[i]['p'], F[i]['spd'], F[i]['dn'], F[i]['s_mm'])
  ```
  按 `p` 判"最深(z 最小)/最里(插入方向最大)", 别按停点表名字猜。
- 定完把结论连同候选一起报:`#128 813,230,188 (z 最低)` / `#129 810,230,189` / `#131 801,230,189`,
  并给一句"不对就点它改名或报编号"——用户要的是一眼可核对, 不是一段解释。

## 名字是两套表: 改了名不会自动改停点

- 名字真源 `zmax_data/ar_live/pt_names.json`(要给人看的标签) 和
  **停点/相位表 `zmax_data/rokae_sdk/point_stops_v2.json`**(决定在哪停、8815 显示哪个状态) **是两份**。
- 定案(2026-11-21): 工作点 = **#99**(老倪定的), 停点表已从 #129 改到 #99(备份 `*.bak-129工作点.json`)。
  改完必须重算 8815, 否则会出现"名字在工作点 #99、动作却在 #129 停"。
- **重合陷阱**: #99 与 #100 坐标全同(`819,227,190`)、弧长都 `1008.4mm` → 两个都当停点会在相位环上
  多出一个长度为 0 的状态。要么只留一个, 要么把名挪到真正那一段的起点。

## 8815 重算(改停点表后必做)

```
cd ~/zmax && ./gui-venv311/bin/python tools/make_v2_phase.py \
  --chunks <真机整圈日志: 只留 {"step":...} 行>   # ← 不带这个参数会退化成 1 块/86s
systemctl restart zmax-se3-geom
```
- 缺省无 `--chunks` 时 blocks 只一块、`total_s` 变录制时长(86s), 节拍全错(实测踩过)。
  从整圈回放的 process-results JSON 里抽 `{"step"...}` 行存成 .log 喂进去, 恢复 54 块/288.69s。
- 验收看 `/api/se3 → sectors`: `n_blocks≈54`、`total_s≈288.7`、`stops` 11 条且 `s_mm` 单调递增。

## 面板位置

- `position:fixed;right:14px;top:70px;width:238px`。别放左下 —— 实测会盖住 `#bRTraj`
  ("▶ 右臂跑真实轨迹", 点了直接开真机) 和 回退/单步/倍速 按钮; 改完用
  `document.elementFromPoint` + 遍历按钮 rect 做重叠检测, 要求 **overlaps=0**。
