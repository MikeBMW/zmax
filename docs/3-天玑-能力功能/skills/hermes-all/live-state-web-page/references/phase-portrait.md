# 相空间相位图（哈密顿相图）画法

用户说「相空间画得不好，应该有哈密顿相空间的相位图吧？横轴转角、纵轴动量」时——
他要的不是三维位置视图，是 **(q, p) 平面上的相位图**：等能线 + 分界线 + 当前相点。

## 1. 先选一个**真会变**的广义坐标，再决定纵轴

- 项目里天然的角度量：`D 滚转 φ`（弧度）、`S¹ 相位 s`（0~1，环上量）、四元数反解转角。
- **先量它到底有没有变化**，再画：
  ```python
  rows = [json.loads(l) for l in open(<history.jsonl>, encoding='utf-8') if l.strip()][-20000:]
  roll = [r["vector"][11] for r in rows]          # 16 维布局: idx11 = D 滚转
  print(len({round(x, 6) for x in roll}), min(roll), max(roll), (rows[-1]["ts"]-rows[0]["ts"])/60)
  ```
  只有 1 种取值 ⇒ 设备静止，相图**就是一个点**。这是物理正确（停在势阱谷底 p=0），
  但必须把「θ 取值 N 种 / 跨度 M min ⇒ 臂静止」写进页面，否则用户读成"图没画"。
- 纵轴 p = 角动量 = `I·dθ/dt`。I 未知就取 1 并在页面上标注「I=1 归一，单位 rad/s」——
  **不许**悄悄乘一个编出来的惯量让数字好看。

## 2. 服务端：现算序列，别在页面里堆历史

```python
_th0 = roll[-1]
trail = []
for i in range(1, len(rows)):
    dt = rows[i]["ts"] - rows[i-1]["ts"]
    if dt <= 0 or dt > 0.6:            # 断流段直接跳过, 别用大间隔算差分
        continue
    trail.append([round(math.degrees(roll[i]), 3), round((roll[i]-roll[i-1])/dt, 4)])
out["phase"] = {"theta_deg": math.degrees(_th0), "p": trail[-1][1] if trail else 0.0,
                "p_ref": 2.0, "k": 1.0, "theta_tol_deg": 1.0,
                "kinds": len({round(x,6) for x in roll}),
                "span_min": (rows[-1]["ts"]-rows[0]["ts"])/60,
                "trail": trail[::max(1, len(trail)//600)]}
```
抽稀到 ≤600 点即可（2s 刷新，再多也画不出差别）。

## 3. 前端：等能线就是解析式，不用数值积分

`H(θ,p) = p²/2 + k·(1 − cos(θ − θ_eq))`，取 k=1：

```js
const energies = [0.15, 0.4, 0.8, 1.3, 1.85, 2.0, 2.6, 3.6];   // 2.0 = 分界线 E=2k
energies.forEach(E => {
  const sep = Math.abs(E - 2*k) < 1e-6;      // 分界线: 谷内摆动 / 越顶旋转的分水岭
  for (const sgn of [1, -1]) {
    g.beginPath(); let started = false;
    for (let th = th0-180; th <= th0+180; th += 1) {
      const d = (th - th0) * Math.PI / 180;
      const v = 2*(E - k*(1 - Math.cos(d)));
      if (v < 0) { started = false; continue; }        // 该能量到不了 → 断线, 别连成直线
      const p = sgn * Math.sqrt(v);
      if (Math.abs(p) > PREF) { started = false; continue; }
      started ? g.lineTo(X(th), Y(p)) : (g.moveTo(X(th), Y(p)), started = true);
    }
    g.stroke();
  }
});
```

配套三件，缺一件图就读不懂：
- **分界线单独用醒目色 + 虚线**，并在右缘标 `E=2k 分界`；其余等能线灰色细线。
- **当前相点用大圈 + 实心小点**，旁边直接写 `当前 θ=… p=…`（用户会把图当结论）。
- **θ 容差带**（竖条）与轴名（θ 转角 (°) / p 角动量 (rad/s, I=1)）。

## 4. 诚实的三种空/静态

| 实测 | 画法 |
|---|---|
| 设备静止（θ 只有 1 种取值） | 相点落在谷底 p=0，页面写「臂静止 ⇒ 相点停在谷底」 |
| 有历史轨迹（`trail` 里 p 非零） | 折线画全程，颜色用蓝；跨等能线的地方自然显形 |
| 只有一个断点、没有连续段 | 只画点，别硬连线成假轨迹 |

**绝不用解析梯形速度曲线伪造一条"受控轨迹"**摆在真值相图上——要看演示就单独一块并标「演示」。

## 5. 验收（无视觉工具）

```js
const c = document.getElementById('phcanvas');
const d = c.getContext('2d').getImageData(0,0,c.width,c.height).data;
// 分别计: 总墨量 / 青(分界线) / 橙(当前点) / 绿(容差带) / 灰(等能线)
```
五类都 >0 才算真画上；再读 `#pth / #pp / #pmeta` 三处 DOM 文本核对数值与静止标注。
空画布同样 HTTP 200 —— 「页面能打开」不算验收。

---

## 6. 用户说「相位图要映射真的哈密顿量」⇒ 球摆约化（不是归一玩具摆）

k=1 / I=1 的摆只能定性（等能线形状对，数字没物理含义）。要「真」就得让**每一项都从真值文件算出来**，
不要拟合质量/惯量，也不要拿关节角的 i/214 当相位。能直接落地的约化是把臂沿轨迹的运动投到
**以基座为中心的球摆**上：

```
r = |TCP|                 逐帧实测 (mm)           —— 摆长
θ = acos(z/r)             TCP 与 +Z 夹角 (deg)    —— 广义坐标
V = g·z                   重力势, 单位质量 (J/kg)
p_θ = I·ω,  I = r²        共轭动量 (m²/s), ω 由**录制时间戳**差分
H(θ,p) = p²/(2I) + g·z    —— 每项都是真值, 无拟合系数
```

输入就两份现成真值：轨迹 `{frames:[{p(m),q,j,t}]}` + 每点实测耗时 `{points:[{secs}]}`。
动力学差分用**录制** `t`（`dur_s` ≈ 43s / 215 点），不要用执行耗时 `secs`（4~8s/点，会把速度抹平 10 倍）。

```python
om = [0.0]*n
for i in range(1, n):
    dt = tt[i] - tt[i-1]
    om[i] = math.radians(th[i]-th[i-1])/dt if dt > 1e-6 else om[i-1]
I  = [r*r for r in r_mm]              # mm², 单位质量
p  = [I[i]*om[i]/1e6 for i in range(n)]   # m²/s
H  = [p[i]*p[i]/(2*max(I[i]/1e6,1e-9)) + 9.80665*z[i]/1000 for i in range(n)]
```

等能线用 **r 的均值**画（单帧 r 变化几个百分点，逐帧不同画不成线），并在图左上写
`等能线 H=<min>…<max> J/kg · r̄=<r̄>m`；轴名写 `p_θ (m²/s, I=r²·单位质量)`。

**必须说出口的三句诚实标注**：
- 约化是「6 轴臂 → 单摆」，只有 1 个自由度；不要暗示这是全 6 轴的能量。
- H 的起伏就是**电机做的功**（实测 1.13 → 9.80 J/kg，Δ=8.67），正是「强跨等能线」的量化证据；别把轨迹不在等能线上说成画错了。
- 静差检验：停留点 p 应回到 ≈0（实测 #9 抓取 p=+0.0005、#205 松爪 p=+0.024）；
  进停留点**前一帧** p 可以很大（实测 #125 减速前 p=−0.341），那不是噪声，是真实减速段。
- 球心默认取**世界坐标原点**（基座安装面），所以 `V=g·z` 才是重力势；基座不在原点时这条曲线只是形似。
  交付时把这句说出口，并给出改法：`r=|P[i]-P_base|`、θ 同理换到基座系——别默认他知道球心在哪。

## 7. 只读轨迹回放（「用 215 点走一遍我看看」，不动设备）

分两层：服务端一次算完出数组，前端只按时间轴播放。

- 独立路由 `/api/traj215`，**只读两份真值文件**，按 `(mtime_file1, mtime_file2)` 缓存；
  返回 `theta_deg / p / H / r_mm / z_mm / t / secs / dur_rec_s / dur_exec_s / r_bar_mm / Hmin,Hmax / stops`。
  全程不连执行服务（8797 之类）、不发任何 POST —— 这一点要在回复里明确写出来。
- 前端动画用 **`setInterval(50ms)` + 墙钟** 对**录制时间轴**推进：
  `tt = (performance.now() - t0) * speed / 1000`，指针只前进（`while(i<n-1 && t[i+1] <= tt) i++`）；
  **页面加载即自动开播并循环**（`load215()` 末尾直接 `play215()`）：走到末点就 `i=0; draw215(0); t0=now;`
  并把状态行写成「▶ 第 N 遍 1x 回放中」。他不点按钮，所以「要点才会动」的交付等于没交付。
  暂停：`clearInterval` + 按钮变「▶ 继续」；恢复时按**当前点**重算 `t0`（`play215()` 里统一算）。
  🔴 不要把「播完 clearInterval 停住」当默认——那会让他看了一眼之后画面就是死的。
  🔴 **不要用 `requestAnimationFrame`**：后台标签/窗口失焦时 rAF 被浏览器挂起，动画**一帧都不推进也不报错**，
  表现为「点了播放、按钮变 ⏸、进度永远 #0」；`setInterval` 在后台只被降频、仍会前进。
  🔴 **走完后再点必须归零**：`if(T215.i >= D.n-1){ T215.i = 0; draw215(0); }` 再起定时器，
  否则 `t0` 按末点算 ⇒ 下一次点击瞬间就「播完」，看着像按钮坏了。
- 🔴 **handler 别引用别的函数内的别名**：播放按钮里写 `D.n-1` / `D.t[i]`，而 `D` 只在 `load215()` 作用域里有 ⇒
  点击抛 `ReferenceError` 被事件循环吞掉，**按钮文案先变了、动画不动、控制台 js_errors 也可能为空**。
  handler 第一行自带守卫：`const D = T215.data; if(!D) return;  // 数据没到就别动`。
- 倍速按钮 x1/x4/x10 + 一个 `input[type=range]` 手动定位（`sl.oninput → draw(i)`）。
  🔴 **默认就是 1x 真实录制速度**：他要看的是真机节拍，加速版不算证据（他会直接说「1x，不用加速」）。
  x4/x10 只给自己验收快进用，页面初始选中态与交回的话术都必须写 1x。
- 三层画法：已走过=亮蓝实线、未走过=暗灰细线、当前点=橙圈；
  停留点画**菱形**（区分于实时绿圆点），旁边读数给 `#i · 段名`（段名表与轨迹段表同源，别自编）。
- 验收（无视觉工具）：`getImageData` 分色计数——蓝(已走)>0、紫(停留点)≈5×每菱形像素、橙(当前点)>0；
  播完后断言 `#i215 == "#214 / 215"` 且蓝像素较起点涨一个量级（实测 15 → 8762），
  再 `browser_console(clear=true)` 断言 `js_errors` 为空。
- 🔴 **倍速只能在页面内量，不能跨 tool call 量**：页面里记 `m={t:performance.now(), i:当前点}` →
  等若干秒 → 同一页面再算 `implied_speed = (t[now]-t[from]) / ((performance.now()-m.t)/1000)`，1x 应回 **1.00**
  （实测 9.44s 墙钟推进 9.40s 轨迹）。跨调用量会把工具往返那几秒算成「播放太快」，我据此误判过一次 2 倍速 ——
  先核口径，再怀疑代码。
- 页里已有的 `#phase` 之类文本节点会和新 canvas id 撞名 —— 新画布一律用独立 id（如 `t215`）。

---

## 9. 同一张画布两副面孔：空间轴测 ⇄ 相空间（画布上的单字按钮）

用户已经有一张「末端轨迹」画布，再要一个「相」按钮时，不要新开一张画布——**同一 canvas + 同一个 2d context**
切视图，他能在原位对照同一个末端。骨架：

```html
<div class="cwrap">
  <button id="bviewphase" class="pill cbtn" title="切换这张画布: 空间轴测轨迹 ⇄ 相空间 (θ, p)">相</button>
  <canvas id="view" width="880" height="340" style="width:100%;height:auto"></canvas>
</div>
<style>.cwrap{position:relative} .cbtn{position:absolute;top:8px;right:8px;z-index:2;min-width:36px}</style>
```

```js
let VIEW_MODE = "space";
function drawScene(j){
  if(VIEW_MODE === "phase"){ drawPhaseView(j); return; }   // ← 在每拍重绘的入口分支
  …原有空间视图…
}
document.getElementById("bviewphase").onclick = () => {
  VIEW_MODE = (VIEW_MODE === "space") ? "phase" : "space";
  const b = document.getElementById("bviewphase");
  b.classList.toggle("on", VIEW_MODE === "phase");
  b.textContent = VIEW_MODE === "phase" ? "相 ✓" : "相";
  if(last) drawScene(last);                                  // 立刻重绘, 不等下一个 tick
};
```

相空间视图直接用 `/api/state` 里的 `phase.trail`（`[[theta_deg, p], …]`，已抽稀 ≤600 点）与
`theta_tol_deg / p_lim / kinds / span_min`，等能线按 §3 的解析式画，不新增服务端字段。

🔴 **定标必须给最小跨度**：设备静止时 `theta` 全相同，`tmax-tmin=0` ⇒ ±1° 容差带 `fillRect` 占满全宽，
整张画布一层淡青（看起来像画坏了）。`const minSpan = Math.max(12*(ph.theta_tol_deg||1), 6);`
再把 `[tmin,tmax]` 撑到 `minSpan` 并加 6% padding；`kinds<=1` 时在图内补一行「臂静止 · 相点停在势阱谷底」。

验收口径：静省时蓝像素可以为 0（折线画不出），所以**必须**再造一段变化的 `[{θ,p}]` 直接调 `drawPhaseView()`
证明蓝像素上千、橙点 >0；两边都拿到再交，并在汇报里说清真实数据现在是静止的。

---

## 8. 兼底：把回放出成 MP4（不依赖 JS、不受缓存/JS 报错影响）

用户第二次说「没动」之后，不要再调页面了 —— 用同一份数据出视频挂在**同一端口**，他点开就能看。

出片（离屏，无头也能跑，640 帧约 3s）：

```python
base = 预画好的底图            # 坐标轴 + 等能线 + 图例, 只建一次
base[:] = (22,16,13)           # BGR 深底; 网格 (48,36,27); 等能线 (90,68,51)
vw = cv2.VideoWriter("phase215_replay.mp4", cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W,H))
for fi in range(int(t[-1]*FPS)):        # 按**录制**时间轴, 不是执行耗时
    tt = fi/FPS; while idx<n-1 and t[idx+1]<=tt: idx+=1
    img = base.copy(); 逐段画蓝线; 停留点菱形; 当前点圆圈; HUD 行(#点/θ/p/H/z)
    vw.write(img)
vw.release()
```

🔴 `mp4v` 出来的文件 Chrome 报 `Unable to play media`（MPEG-4 Part 2 不解码）。必须转 H.264：

```bash
ffmpeg -hide_banner -loglevel error -y -i phase215_replay.mp4 \
  -c:v libx264 -pix_fmt yuv420p -crf 23 -movflags +faststart phase215.mp4
# 42.9s / 880x440 → 313KB; ffprobe -show_entries stream=codec_name,width,height,duration
```

服务端路由（要支持 Range，否则拖进度条/循环播会失败）：`/Range: bytes=a-b` → `206 + Content-Range + Accept-Ranges`，
无 Range → `200 + Content-Length`，`Content-Type: video/mp4` + `Cache-Control: no-store`。
页内内嵌（自动播必须 `muted`）：

```html
<video src="/phase215.mp4" controls loop muted autoplay playsinline preload="auto"
       style="width:100%;border-radius:10px;background:#000"></video>
```

验收：`curl -o /dev/null -w "%{http_code} %{size_download}B"`（200 + 全量）与 `-r 0-1023`（206）；
页面里读 `video.currentTime/duration/videoWidth`——currentTime 在涨且 `video.error===null` 才算成。
视频里的数与 `/api/traj215` 同一份（同一次算出），别为了好看改数。
