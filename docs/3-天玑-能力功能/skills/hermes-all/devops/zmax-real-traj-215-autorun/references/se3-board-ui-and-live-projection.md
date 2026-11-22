# SE(3) 几何看板: 实时投影 + 页面可读性 (实测过的坑)

看板 = `tools/se3_geom_server.py`(systemd `zmax-se3-geom`, 8815) + `tools/web/se3_geom.html`。
本文件只讲反复出问题的地方: **“现在”在流形上的定位**、**页面看着舒服**、**节拍账怎么画**。

## 一 · 实时定位: 全局最近点会在自交点跳分支

轨迹有 22 处几何近重合(关节差 <1°), 全局 `argmin` 距离会把当前点认成另一分支 —— 实测跑到
`#60~71` 时页面报 `#2`(偏轨 10mm), 看起来像“机器人跑错地方了”。

正解 = **相位连续性窗口**: 记住上次索引 `_LAST["i"]`, 只在 `[last-6, last+40]` 里找最近点;
窗口内最小距离超出 `max(6×全局最小, 25mm)` 时才回退全局。

```python
_li = _LAST.get("i")
if _li is None:
    i = d.index(min(d))
else:
    lo, hi = max(0, _li - 6), min(len(P), _li + 40)
    win = d[lo:hi]
    j = lo + win.index(min(win))
    i = j if min(win) <= max(6.0 * min(d), 25.0) else d.index(min(d))
_LAST["i"] = i
```

- 为什么窗口不能只往前(top 40)又往后 6: 分块下发时一块 12 点, 索引会整块跳; 回退要允许 6 点的重锚抖动。
- 这条与执行链的 `exec_index()` 是同一个道理(那边只认 `start+done`/日志 progress, 不用最近点), 两边都别用全局最近点做判据。
- 验证: 臂停在起点 `665.2/-29.0/296.1` 时最近点应是 `#214` 偏轨 ~2.3mm(首末 3.91mm 的缝);
  若回 `#0` 且偏轨 >10mm, 先查 `latest.json` 是否陈旧/单位是否毫米, 再怀疑投影。

## 二 · 实时值要“抬”到页面上, 不能只画针

每 1s 拉 `/api/se3`, 五块都要用实时量并把滑块**自动跟随**:

- 大号点号/相位数字以前绑的是滑块 `idx`(默认 0) ⇒ 真机在跑也永远显示 `#0 / 214`(用户会当场问“怎么总是 0/214”)。
  定式: `const _ei = (LIVE && LIVE.nearest) ? LIVE.nearest.i : idx;` 数字、刻度高亮一起用它。
- 滑块跟随要留“用户优先”: 手动拖动后 20s 内不抢(`_scrubT = Date.now()`), 否则他一看数字就跳回去。
- B/C/D/E 四块分别叠实时轴箭头 / 四元数点 / φ 指针 / s 指针, 并在 `*.sub` 前加 `● 实时` —— 他自己要能区分“标注值”和“现在值”。
- `file://` 打开时 `fetch('/api/se3')` 必失败: `catch` 里置 `LIVE=null` 并让渲染降级, **不许抛错**(抛一次就整页停)。

## 三 · 字体小 / 文字重合: 三处根因, 一起治

1. **卡片右上读数绝不能 `position:absolute`** —— 标题一长就压字。改成两栏 flex:
   ```html
   <div class="hd"><h2>…</h2><span class="sub" id="aSub"></span></div>
   ```
   ```css
   .hd{display:flex;justify-content:space-between;align-items:baseline;gap:10px}
   .hd .sub{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
   ```
2. **字号缩放变量必须声明在 `:root`**: 写在 `body{--fs:…}` 里时, `documentElement.style.setProperty('--fs', …)` 会被 body
   自己的声明盖掉 ⇒ 点 A+ 毫无反应(实测 1.15→1.45 只有画布变、页面文字不变)。
3. **画布内文字统一走一个缩放函数**: `var SF=1.15; function P(n){return Math.round(n*SF);}`,
   所有 `g.font` 写成 `g.font = P(13)+'px sans-serif'` / `'600 '+P(15)+'px sans-serif'`, 否则页面字放大了、画布还是原尺寸。

🔴 **`P` 这个名字容易被局部变量遮蔽**: `drawA()` 里原本有 `const P = rel.map(proj…)`, 一加字号函数就每帧
`TypeError: P is not a function`, 页面整张死掉(浏览器 `js_errors` 只给空 message, 看不出行号)。局部数组改名 `PT`。

## 四 · 验收用测量, 不用肉眼

```javascript
// ① 头部是否重合 + 字号是否真的变了
const R=e=>e.getBoundingClientRect();
const ov=[];document.querySelectorAll('.hd').forEach(hd=>{const a=R(hd.querySelector('h2')),b=R(hd.querySelector('.sub'));
  if(!(a.right<=b.left||b.right<=a.left||a.bottom<=b.top||b.bottom<=a.top))ov.push(hd.querySelector('h2').textContent);});
({ov, bodyFs:getComputedStyle(document.body).fontSize});

// ② 画布文字是否溢出面板宽度
const g=document.getElementById('a').getContext('2d');
g.font='600 '+Math.round(15*SF)+'px sans-serif';
({need:g.measureText('现在 #59 · s 26.2% · 偏轨 3.5 mm · 0.0s').width, have:document.getElementById('a').getBoundingClientRect().width});

// ③ 按钮到底通不通: 直接 click(), 再读 localStorage 与字号
for(let k=0;k<3;k++)document.getElementById('fsUp').click();
({sf:localStorage.getItem('se3_sf'), fs:getComputedStyle(document.body).fontSize});
```

- `browser_click(<ref>)` 对这类小按钮有时落不到 handler 上(元素在、可点、事件不走) ⇒ 验功能一律用 `.click()`,
  和轨迹页按钮同一个结论。
- 页面改完只需 `sudo systemctl restart zmax-se3-geom`; 只改 HTML 甚至不用重启(服务每次请求都读文件)。
- 生成/大改 HTML 后**先**抽 `<script>` 跑 `node --check` 再打开页面 —— 语法错时浏览器只报一条空异常。

## 五 · 相位环画成“扇形 + 节拍构成 + 状态文字”

需求形态: “相位环的进度按实际状态标成扇形, 根据节拍时间构成, 扇形旁边要有文字显示当时的状态”。
数据来自跑批日志的每块 `progress` 行 (`i0/i1/s0/s1/secs/speed_cmd`), 服务器在 `/api/se3` 里增一个
`sectors` 段:

```python
sectors = {
  "blocks": [{"i0","i1","n_pts","s0","s1","t_s","speed","state","state_tags","t_per_mm","frac"}],
  "tiers":  [{"speed","t_s","frac","s_frac","color"}],   # 按速度档聚合的时间/相位占比
  "total_s", "n_blocks", "slowest": [{"i0","i1","t_s","state","speed"}],
}
```

### 编码规则 (三个量各占一个通道, 不许混)

| 通道 | 编码什么 | 为什么 |
|---|---|---|
| 角度 | **相位 s**(真实弧长) | 环的主变量是“走到哪”; 拿时间占比当角度会让人以为时间=相位 |
| 径向厚度 | 该块实测耗时 (`5+10·t/tmax`) | 慢块厚、快块薄, 一眼看出瓶颈扇区 |
| 颜色 | 速度档 (100青/85绿/70橙/60红) | 与 flow 档同源, 能对上执行日志的 `speed_cmd` |

时间构成**另画一个小饼**(角度 = 时间占比), 放环右侧 —— 两套坐标放同一个环上必然误读。

### 四条渲染坑

1. 🔴 **极短扇区等于看不见**: 相位跨度 <0.57° 的块按径向刻度线画 (2.2px 宽, 从内圈到环外)
   —— 本轨迹有 3 块 <1° (0.93° / 0.98° / 0.46°), 纯按角度填色会整块消失, 用户会问“少了一块”。
2. 🔴 **扇区用实色, 不要半透明**: `#f5a623`(橙) 与 `#e0563f`(红) 混合深底后都变成 ~(160,110,30),
   像素采样最近邻会互相判错 (实测 22/37 判对)。实色 + 1px 深色描边分隔。
3. 🔴 **状态文字放不下就跳过, 别让 `chip()` 夹边**: 那个胶囊 helper 会把 x 夹进画布内 ⇒ 贴边时直接压到扇形上。
   定式: 先算锚点与文本宽, 若 `ax<6 || ax+tw+pad > w-4 || ly` 越界就**放弃这个标签**, 由右侧清单兜底;
   同时按角度去重 (相邻 <0.46rad 只留一个), 否则短段标签会叠成一团。
4. 🔴 **窄版不许裁字**: 右侧“状态·耗时”清单要先用 `w-(px+pr+16) >= 112` 判剩余宽度, 不够就整块不画 ——
   网格视图只有 343px, 画了会被裁在画布外 (用户看到半截字)。宽版 (`?focus=s1`, 589px) 才画完整清单。

### 状态标签的口径

- 状态 = **推断**, 依据只有两条可核证据: 停留点 (`#9 合爪 / #125·#151 金手指AOI / #172 表面检测 / #205 松爪`)
  + 该块实测速度档。标签后面同时挂实测异常量 (`轴断层17°` / `滚转26°` / `碎步2点`) ⇒ 阶段名粗一点也不影响可用。
- 三处文字: ①环外径向胶囊(连续同状态的块**合并成状态段**, 带引线, 标“状态+该段耗时”) ②右侧“状态·耗时”清单
  (全部状态段按时间降序, 秒 + 占比) ③左上“现在 X”胶囊 + 卡片副标题追加当前状态。
- 副标题顺手报 **相位覆盖率** `Σ(s1−s0)`: 正常应 <100% (本轨迹 81.4%) —— 那 18.6% 是块间记账空隙,
  不是画错, 见 SKILL.md 的那条。

### 像素验收 (canvas 没有 DOM, 只能采样)

```javascript
// ① 每个扇区是否按其档位色画出来了
const {cx,cy,RO}=E_GEO, g=document.getElementById('e').getContext('2d');
LIVE.sectors.blocks.map(b=>{const a=(b.s0+b.s1)/2*6.2832-Math.PI/2;
  return [b.i0, b.speed, g.getImageData(Math.round(cx+Math.cos(a)*(RO-7)), Math.round(cy+Math.sin(a)*(RO-7)),1,1).data.slice(0,3)];});
// ② 小饼四色都在: 绕 4° 步长、两个半径采样, 统计命中档位色的像素数
// ③ 右边界不许有文字 (防裁字): 扫 x∈[W-8,W) 的亮像素应为 0
// ④ 清单是否真画了: 在 x0 起的色条区域数档位色像素 (5 行 ≈ 220px) + 白字像素 >300
```

实测结论(本轮): 37 块全部有扇区, 其中 33 块能被像素采样直接命中; 剩下 4 块是亚像素宽度的短块(已有刻度线), 属采样问题不是漏画。

## 六 · 某张图要放大并与另一张并列 → `grid-template-areas` + 语义类, 别用 nth-child

需求形态: 「E 相位图太小了, 放大, 跟 A 图并列放在第一行, 下一行 BCD」。

```css
.grid{display:grid;grid-template-columns:repeat(6,1fr);gap:14px;
      grid-template-areas:"a a a e e e" "b b c c d d"}
.g-a{grid-area:a} .g-e{grid-area:e} .g-b{grid-area:b} .g-c{grid-area:c} .g-d{grid-area:d}
```

- 🔴 **焦点/精简视图的隐藏规则必须按语义类, 不许 `nth-child`**: `body.focus-s1 .card:nth-child(1),(2),(3){display:none}`
  在 DOM 重排(E 移到第二位)之后把 **E 自己**隐藏了, 焦点视图意外只剩 C/D, 页面不报错、也不空白。
  改成 `body.focus-s1 .g-a,body.focus-s1 .g-b,body.focus-s1 .g-c{display:none}` + 焦点样式自己写 `grid-areas:"d e"`。
- **放大要等比放大画布内部, 不只是撑外框**: 环半径(`RO` 64→121)、时间饼半径、环内外字号(读数 16→21px)、
  右侧清单行距/字号一起放大。只改 canvas 的 CSS 宽高 = 外框变大、图还是小的(用户会说"没放大")。
- 验收: `getBoundingClientRect()` 读五张卡的 `x/y/w/h`(并列的两张 `y` 必须相同、宽度差 ≤2px),
  再采样环内着色像素数(半径 1.9× ⇒ 像素应 ~3.6×)。响应式 ≤1100 / ≤760 各break一次, 断言无横向滚动、无裁字。

## 七 · 离散事件点(停留点/告警/关键帧)画在环上

三个通道已被角度(相位)/厚度(耗时)/颜色(档位)占满 ⇒ 事件点只能用**独立字形 + 环外清单**, 不许改那三条编码。

- **字形要跟"现在"严格区分**: 实时位置是绿圆点, 事件点用**菱形**(旋转 45° 方块) + 深色光晕垫底(压在青/绿/橙/红扇区上都清楚)
  + 中心亮色序号。不要用圆点/不要只换颜色 —— 换颜色在四种档位色里认不出来。
- **按类分色**, 且与档位四色都不撞: 夹爪 `#ffd166`(琥珀)、AOI `#9fe8ff`(亮青)。
- **时长用环外一小段弧表达** (长度 ∝ 停留毫秒) ⇒ 2.0s 与 2.6s 能一眼分出谁停得久。
  🔴 **没采到时长的(如 AOI 到达即检测)画固定短线并把时长留空, 不许编一个数**。
- 🔴 **环贴着画布边缘时, 环外没有放文字的空间**: `cx=126, RO=121` ⇒ 左缘在 x=5, 径向外标签实测落到
  `x=-14/-93/-55` 被静默丢掉(有标记没名字)。定式 = 环上只画**序号**, 名字与时长放**底部一行清单**
  (「◆ 停留点 ① 合爪·抓取 2.0s ② 金手指AOI ③ …」), 放不下自动换行; 判据: 扫画布四边 8px 边带, `edge_clip` 必须 0。
- **点位与语义都从真源取, 不另列一份**: 相位取 `traj_phase.json`(与扇形同一坐标), 停留点取
  `real_traj_grip.json` 的 `grip[].i` + `tools/rokae/arm_step_traj.py::AOI_ON_ARRIVE`。
- 像素验收: 在每个标记中心采样判色(实测光晕内琥珀 41~46px / 亮青 24~27px), 再全图数一遍该类色像素数
  —— 只验"代码里有这段 draw" 不算。

## 八 · 换了点表, A/B/C/D 四块还是旧点 (页面内嵌快照)

`se3_geom.html` 里写死了一个 `const D={frames:[…215 帧…]}` 快照, 四块面板全从 `D.frames` 算。
服务端切到新表(239 点)后, `/api/se3` 的 `nearest.i` 已在新索引空间, 而画面还是旧 215 点 ⇒ 轨迹是旧点、高亮是新点,
两者对不上且**不报错**。用户的说法是「位置 ℝ³ 轨迹也更新成新点」。

定式(已落地):

1. 服务端加 `GET /api/geo` —— 回与内嵌 `D` **完全同形**的帧: `p(mm) / n / phi / q / dn / dphi / spd / s / s_mm`,
   数据源就是当前 set 的 `real_traj_joints* / traj_hopf* / traj_phase*`(与 `/api/se3` 同一套表)。
   单位必须归一: `if max(|p|)<20: p = p*1000`(录制文件里米/毫米并存)。
   `spd` 从 `sectors.blocks` 反填(没命中给 100), 否则速度着色全一样。
2. 页面把 `const F/N/S_END/PROG/PW` 改成 `let`, 合出一个 `deriveGeo()` 重算派生量, 再 `loadGeo()`:
   帧数不同才重建(`if(j.frames.length===N) return;` —— 同表重建会拽视角), 同时 `sc.max=N-1`、
   `idx` 夹回范围、`D.frames=F`。
3. 新增速度档(如接触段 15)要在 `SPC` 里补颜色: `SPC[15]` 为 undefined ⇒ 全画成灰 `#888`。

验收三条一起(缺一条就只是“看着换了”): `window.selftest()` 的 `n` = 新点数 · `F[0]/F[N-1]` 与表首末点对得上 ·
`#sc.max = N-1` · 且 `selftest().idx` 与 `/api/se3` 的 `nearest.i` **同源一致**。
实测 239 点: `n=239 · sc.max=238 · F[0]=(663,-29,292) · idx 44 == nearest.i 44`。

- 🔴 同源的另一半是**状态行**: `PHASES` 由 `point_stops_<set>.json` 生成 ⇒ 改状态名 = 改停点数,
  两者一起改、一起重启(`sudo systemctl restart zmax-se3-geom`), 否则 A 块新点 + E 块旧状态, 现场必问“你改了个空”。
  耦合细则见 `playback-points-mode.md` §7。
